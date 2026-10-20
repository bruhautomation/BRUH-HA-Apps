#!/usr/bin/env python3
"""BRUH Bambu Studio's panel: the ingress target and the printers' one owner.

Three jobs, one process.

* It is the SIDEBAR. Bambu Studio runs on a virtual screen (Xvfb), x11vnc
  reads that screen on loopback, and this serves noVNC and bridges its
  websocket to x11vnc (`vnc_bridge`), so the slicer is a page in Home
  Assistant with nothing published to the LAN.
* It OWNS THE PRINTERS. One MQTT session per printer (`bambu.client`), the
  storage upload (`bambu.ftps`), and every command. A second process that
  also held a printer session would be a second answer to "what is this
  printer doing" — so the HA bridge forwards to the routes here and never
  talks to a printer itself.
* It SLICES, through Bambu Studio's own command line (`slicer`), and runs
  print jobs: slice if the file needs it, upload, start.

Long work — the 200 MB download, a slice, a print job — is a job with a
state the caller polls. A request that waits minutes for an answer is a
request ingress cuts off, and what arrives in the browser is not the
panel's error but its absence.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bambu_atomic  # noqa: E402
import discover  # noqa: E402
import ha_setup  # noqa: E402
import importer  # noqa: E402
import installer  # noqa: E402
import library  # noqa: E402
import slicer  # noqa: E402
import store  # noqa: E402
import thumbs  # noqa: E402
import vnc_bridge  # noqa: E402
from bambu import camera as cameras  # noqa: E402
from bambu import ftps, protocol, threemf  # noqa: E402
from bambu.client import PrinterClient  # noqa: E402
from design import brain_link, designer, options, painting, parts, profiles, runner  # noqa: E402
from studio import Studio  # noqa: E402

log = logging.getLogger("bruh_bambu")

PANEL_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
NOVNC_DIR = Path(os.environ.get("BAMBU_NOVNC_DIR", "/usr/share/novnc"))
# three.js, fetched at image build time (see the Dockerfile), for the
# Design tab's 3D view. A panel with none still works and says so.
VENDOR_DIR = Path(os.environ.get("BAMBU_VENDOR_DIR", "/opt/bruh-bambu/vendor"))
SHARED = Path(os.environ.get("BAMBU_SHARED", "/config/.bruh_bambu"))
STATE_FILE = SHARED / "state.json"
BIND_HOST = "0.0.0.0"
PORT = int(os.environ.get("BAMBU_PANEL_PORT", "8093"))
TICK_S = 5
MAX_PRINT_JOBS = 30
# How long a caller may ask a route to wait for a job before it answers
# with the job as it stands. The HA bridge asks for this much; a browser
# never waits.
MAX_WAIT_S = 900

ACTIONS = ("pause", "resume", "stop", "speed", "light", "gcode",
           "temperature", "home", "refresh", "reconnect", "ams_refresh")
# Home Assistant's camera entity asks for frames by touching a file here,
# and reads them back from the same folder (there is no port between them).
CAMERA_DIR = SHARED / "camera"
HA_WANTS_S = 30


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class Panel:
    def __init__(self, *, start_clients: bool = True):
        self.studio = Studio()
        self.clients: dict[str, PrinterClient] = {}
        self.jobs: dict[str, dict] = {}
        self.cameras: dict[str, cameras.Camera] = {}
        # What each print job put on each printer, so the printer card can
        # show the picture of the job it is printing: {printer id: {name: library path}}.
        self.uploaded: dict[str, dict] = {}
        self.start_clients = start_clients
        self._mirror = ""
        self._mirrored_at = 0.0
        self._lock = threading.Lock()

    # -- printers ----------------------------------------------------------
    def sync_clients(self) -> None:
        rows = {r["id"]: r for r in store.load()}
        codes = store.codes()
        for pid in list(self.clients):
            row, client = rows.get(pid), self.clients[pid]
            if row is None or (row["host"], codes.get(pid)) != (client.host, client.code):
                client.stop()
                self.clients.pop(pid)
                camera = self.cameras.pop(pid, None)
                if camera:
                    camera.stop()
        for pid, row in rows.items():
            if pid not in self.clients and codes.get(pid):
                client = PrinterClient(row["host"], row["serial"], codes[pid])
                self.clients[pid] = client
                if self.start_clients:
                    client.start()

    def printer(self, wanted: str | None) -> tuple[dict, PrinterClient]:
        row = store.resolve(store.load(), wanted)
        client = self.clients.get(row["id"])
        if client is None:
            raise LookupError(f"{row['name']} has no access code saved. Add it again "
                              f"on the Printers tab.")
        return row, client

    def reconnect(self, pid: str) -> None:
        """Drop the printer's session and open a new one."""
        client = self.clients.pop(pid, None)
        if client is not None:
            client.stop()
        camera = self.cameras.pop(pid, None)
        if camera is not None:
            camera.stop()
        self.sync_clients()

    def camera(self, pid: str) -> cameras.Camera:
        row, client = self.printer(pid)
        summary = client.summary()
        kind = protocol.camera_kind(row.get("model"), summary.get("rtsp_url"))
        current = self.cameras.get(row["id"])
        if current is None or current.kind != kind or current.host != row["host"]:
            if current is not None:
                current.stop()
            want = CAMERA_DIR / f"{row['id']}.want"

            def ha_wants(path=want) -> bool:
                try:
                    return time.time() - path.stat().st_mtime < HA_WANTS_S
                except OSError:
                    return False
            current = cameras.Camera(row["host"], client.code, kind, summary.get("rtsp_url"),
                                     mirror=CAMERA_DIR / f"{row['id']}.jpg", mirror_wanted=ha_wants)
            self.cameras[row["id"]] = current
        return current

    def printers(self) -> list[dict]:
        out = []
        for row in store.load():
            client = self.clients.get(row["id"])
            summary = client.summary() if client else {
                "online": False, "connection_error": "No access code saved."}
            item = {**row, **summary}
            camera = self.cameras.get(row["id"])
            item["camera"] = camera.state() if camera else {
                "kind": protocol.camera_kind(row.get("model"), summary.get("rtsp_url")),
                "streaming": False, "frame_age_s": None, "error": ""}
            item.pop("rtsp_url", None)
            known = self.uploaded.get(row["id"]) or {}
            source = known.get(summary.get("file") or "") or known.get(
                os.path.basename(str(summary.get("gcode_file") or "")))
            item["job_picture"] = (f"api/thumb?path={urllib.parse.quote(source)}"
                                   if source else None)
            out.append(item)
        return out

    # -- jobs --------------------------------------------------------------
    def new_job(self, kind: str, **fields) -> dict:
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "state": "running",
               "phase": "", "error": "", "started": time.time(),
               "finished": None, **fields}
        with self._lock:
            self.jobs[job["id"]] = job
            for old in sorted(self.jobs.values(), key=lambda j: j["started"])[:-MAX_PRINT_JOBS]:
                self.jobs.pop(old["id"], None)
        return job

    def job(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id) or slicer.get(job_id)

    def state(self) -> dict:
        return {
            "ok": True,
            "version": os.environ.get("ADDON_VERSION", "dev"),
            "studio": self.studio.state(),
            "printers": self.printers(),
            "jobs": sorted([*self.jobs.values(), *slicer.JOBS.values()],
                           key=lambda j: j["started"], reverse=True)[:10],
            "ha": ha_setup.status(),
        }

    # -- the timer ---------------------------------------------------------
    def tick(self) -> None:
        self.studio.tick()
        for client in list(self.clients.values()):
            client.tick()
        self._ha_cameras()
        self.publish()
        try:
            ha_setup.check()
        except Exception:  # noqa: BLE001 - asking Home Assistant must not stop the timer
            log.exception("Checking the Home Assistant integration failed")

    def _ha_cameras(self) -> None:
        """Start a camera Home Assistant has asked for (its entity touches a file)."""
        try:
            wants = list(CAMERA_DIR.glob("*.want"))
        except OSError:
            return
        for path in wants:
            try:
                fresh = time.time() - path.stat().st_mtime < HA_WANTS_S
            except OSError:
                continue
            if fresh and path.stem in self.clients:
                try:
                    self.camera(path.stem).want()
                except LookupError:
                    pass  # a printer removed since its entity asked

    def publish(self) -> None:
        """Mirror what Home Assistant reads into the shared folder.

        Skipped on a checkout with no /config (a dev box must not grow a
        stray one), and only written when it changed.
        """
        if not SHARED.parent.is_dir():
            return
        state = self.state()
        mirror = {
            "version": state["version"],
            "studio": {k: state["studio"][k] for k in ("installed", "version", "running")},
            "printers": state["printers"],
            "generated_at": int(time.time()),
        }
        text = json.dumps({**mirror, "generated_at": 0}, sort_keys=True)
        # Rewritten when it changed, and at least once a minute so the
        # integration can tell a quiet panel from a dead one by the stamp.
        if text == self._mirror and time.time() - self._mirrored_at < 60:
            return
        self._mirror, self._mirrored_at = text, time.time()
        try:
            SHARED.mkdir(parents=True, exist_ok=True)
            # No explicit mode: Core reads this as root, so the file needs no
            # world-readable bit, and the umask's default is what it gets.
            bambu_atomic.write_json(STATE_FILE, mirror)
        except OSError as exc:
            log.warning("Could not write %s: %s", STATE_FILE, exc)


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def run_command(client: PrinterClient, action: str, body: dict) -> dict:
    """One control action, by name. ValueError for a bad argument."""
    value = body.get("value")
    if action in ("pause", "resume", "stop"):
        payload = protocol.simple(action)
    elif action == "speed":
        payload = protocol.speed(value)
    elif action == "light":
        on = value if isinstance(value, bool) else str(value).lower() in ("on", "true", "1")
        payload = protocol.light(on)
    elif action == "gcode":
        payload = protocol.gcode(value)
    elif action == "temperature":
        payload = protocol.temperature(body.get("target"), value)
    elif action == "home":
        payload = protocol.gcode("G28")
    elif action == "refresh":
        payload = protocol.pushall()
    elif action == "ams_refresh":
        try:
            slot = int(value)
        except (TypeError, ValueError):
            raise ValueError("Name the AMS tray to read again (0 for the first).") from None
        if not 0 <= slot < 16:
            raise ValueError("An AMS tray is 0 to 15.")
        payload = protocol.ams_refresh(slot // 4, slot % 4)
    else:
        raise ValueError(f"Unknown action {action!r}. Known: {', '.join(ACTIONS)}.")
    if action in ("gcode", "temperature", "home") and client.summary().get("state") in (
            "running", "prepare"):
        raise ValueError("The printer is printing; G-code and temperature changes "
                         "wait until it is paused or finished.")
    return client.send(payload)


def describe_slice(info: dict) -> str:
    """A sliced job in one sentence: how long, how much, of what."""
    bits = []
    if info.get("seconds"):
        minutes = round(info["seconds"] / 60)
        bits.append(f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min")
    use = [f for f in info.get("filament_use") or [] if f.get("grams")]
    if info.get("grams"):
        total = f"{info['grams']:g} g of filament"
        if len(use) > 1:
            total += " (" + ", ".join(
                f"{f['grams']:g} g {' '.join(x for x in (f.get('colour'), f.get('type')) if x)}"
                for f in use) + "; colour changes purge into the prime tower or the infill and that is counted here)"
        bits.append(total)
    return ", ".join(bits)


def _print_job(panel: Panel, job: dict, row: dict, client: PrinterClient,
               body: dict, env: dict, prepared: dict | None = None,
               after=None, notify=None) -> None:
    """Slice if needed, upload, start.

    `prepared` is a part's (or a bare model's) own settings files
    (design/profiles.py), built from what was asked and never taken off a
    request as paths. `after` is told the finished job; `notify` is told
    each step in a sentence, so a conversation can say what is happening.
    """
    start = options.clean_start(body)
    copies = int(start.get("copies") or 1)

    def say(text: str) -> None:
        job["note"] = text
        if notify:
            try:
                notify(text)
            except Exception:  # noqa: BLE001 - a note must not stop a print
                log.exception("Telling the conversation about the print failed")

    try:
        source = library.path_of(body["file"])
        info = threemf.inspect(str(source)) if source.name.lower().endswith(".3mf") else {
            "sliced": False}
        if not info.get("sliced") or copies > 1:
            job["phase"] = "slicing"
            if prepared:
                paths = prepared["paths"]
                slice_job = slicer.start_paths(
                    source, machine=Path(paths["machine"]), process=Path(paths["process"]),
                    filaments=[Path(f) for f in paths.get("filaments") or [paths["filament"]]],
                    arrange=True, orient=bool(body.get("orient")), env=env, copies=copies)
            else:
                slice_job = slicer.start(body["file"], plate=int(body.get("plate") or 0),
                                         machine=body.get("machine") or "",
                                         process=body.get("process") or "",
                                         filaments=body.get("filaments") or None,
                                         arrange=bool(body.get("arrange")) or copies > 1,
                                         orient=bool(body.get("orient")), env=env,
                                         copies=copies)
            job["slice_job"] = slice_job["id"]
            done = slicer.wait(slice_job["id"], slicer.TIMEOUT_S + 30)
            if not done or done["state"] != "done":
                raise RuntimeError((done or {}).get("error") or "Slicing did not finish.")
            source = library.path_of(done["output"])
            info = done["info"]
            summary_line = describe_slice(info)
            if summary_line:
                say(f"Sliced: {summary_line}.")
        plates = info.get("plates") or [1]
        plate = int(body.get("plate") or plates[0])
        if plate not in plates:
            raise ValueError(f"Plate {plate} is not in that file; it has plates "
                             f"{', '.join(map(str, plates))}.")
        if client.summary().get("printing"):
            raise RuntimeError(f"{row['name']} is already printing.")
        name = ftps.safe_name(re.sub(r"\s+", "_", source.name))
        job["phase"] = "uploading"
        with ftps.Storage(row["host"], client.code) as storage:
            storage.upload(str(source), name,
                           progress=lambda s, t: job.update(progress=round(s / t * 100) if t else None))
        panel.uploaded.setdefault(row["id"], {})[name] = library.relative(source)
        panel.uploaded[row["id"]][re.sub(r"(\.gcode)?\.3mf$", "", name)] = library.relative(source)
        job["phase"] = "starting"
        use_ams = body.get("use_ams")
        if use_ams is None:
            use_ams = bool(client.summary().get("ams"))
        mapping = body.get("ams_mapping") or threemf.ams_mapping(info)
        payload = protocol.project_file(
            name, plate, use_ams=bool(use_ams), ams_mapping=[int(x) for x in mapping],
            timelapse=bool(start.get("timelapse", body.get("timelapse", False))),
            bed_leveling=bool(start.get("bed_leveling", body.get("bed_leveling", True))),
            flow_cali=bool(start.get("flow_cali", body.get("flow_cali", False))),
            vibration_cali=bool(start.get("vibration_cali", body.get("vibration_cali", True))),
            bed_type=options.mqtt_bed_type(start.get("plate_type")),
            layer_inspect=bool(start.get("layer_inspect", False)))
        answer = client.send(payload)
        if start.get("speed") and start["speed"] != "standard":
            try:
                client.send(protocol.speed(start["speed"]))
            except (ConnectionError, RuntimeError, ValueError) as exc:
                log.info("Setting %s's speed after the start: %s", row["name"], exc)
        job.update(state="done", phase="started", file=library.relative(source),
                   plate=plate, acknowledged=answer.get("acknowledged"),
                   seconds=info.get("seconds"), grams=info.get("grams"),
                   filament_use=info.get("filament_use"))
    except (OSError, ValueError, LookupError, RuntimeError, ConnectionError,
            EOFError) as exc:
        job.update(state="failed", error=str(exc) or exc.__class__.__name__)
    finally:
        job["finished"] = time.time()
        if after:
            try:
                after(job)
            except Exception:  # noqa: BLE001 - a bookkeeping hook must not lose the job
                log.exception("Recording the print failed")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# The image's aiohttp is Debian bookworm's 3.8, which has no AppKey (3.9).
# A plain string key is what 3.8 uses, and it still works on a newer one.
PANEL_KEY = web.AppKey("panel", Panel) if hasattr(web, "AppKey") else "panel"


def _panel(request) -> Panel:
    return request.app[PANEL_KEY]


async def _body(request) -> dict:
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text=json.dumps({"ok": False, "error": "Send JSON."}),
                                 content_type="application/json") from None
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text=json.dumps({"ok": False, "error": "Send a JSON object."}),
                                 content_type="application/json")
    return data


def _err(message: str, status: int = 400) -> web.Response:
    return web.json_response({"ok": False, "error": message}, status=status)


async def _wait_for(panel: Panel, job: dict, seconds) -> dict:
    try:
        seconds = min(float(seconds or 0), MAX_WAIT_S)
    except (TypeError, ValueError):
        seconds = 0
    deadline = time.time() + seconds
    while job.get("state") == "running" and time.time() < deadline:
        await asyncio.sleep(1)
    return job


async def h_health(_request):
    return web.json_response({"ok": True})


async def h_state(request):
    return web.json_response(await asyncio.to_thread(_panel(request).state))


async def h_install(request):
    body = await _body(request)
    panel = _panel(request)
    started = installer.start_install(
        os.environ.get("BAMBU_STUDIO_VERSION", "latest") if body.get("version") is None
        else str(body["version"]),
        os.environ.get("BAMBU_APPIMAGE_URL", ""), force=bool(body.get("force")),
        after=lambda: panel.studio.restart())
    return web.json_response({"ok": True, "started": started,
                              "install": dict(installer.STATE)})


async def h_studio(request):
    panel = _panel(request)
    action = request.match_info["action"]
    if action == "restart":
        await asyncio.to_thread(panel.studio.restart)
    elif action == "stop":
        await asyncio.to_thread(panel.studio.stop)
    elif action == "open":
        body = await _body(request)
        try:
            path = library.path_of(body.get("file"))
        except ValueError as exc:
            return _err(str(exc))
        if not path.is_file():
            return _err("No such file in the library.", 404)
        await asyncio.to_thread(panel.studio.restart, str(path))
    else:
        return _err("Unknown action.", 404)
    return web.json_response({"ok": True, "studio": panel.studio.state()})


async def h_printers(request):
    return web.json_response({"ok": True, "printers": _panel(request).printers(),
                              "models": [m for m in store.MODELS if m]})


async def h_printer_save(request):
    body = await _body(request)
    try:
        row = await asyncio.to_thread(store.save, body, body.get("access_code"))
    except ValueError as exc:
        return _err(str(exc))
    await asyncio.to_thread(_panel(request).sync_clients)
    return web.json_response({"ok": True, "printer": row})


def _scan_job(job: dict, subnet: str) -> None:
    """Blocking: which networks, then every printer on them, against the saved list."""
    try:
        if subnet:
            networks = [discover.narrowed(subnet)]
            if networks[0] is None:
                raise ValueError(f"{subnet} is not a LAN network to scan.")
        else:
            networks = discover.lan_networks()
            for row in store.load():
                net = discover.narrowed(f"{row['host']}/24")
                if net is not None and net not in networks:
                    networks.append(net)
        if not networks:
            raise ValueError("Could not tell which network Home Assistant is on. Give the "
                             "network to scan, such as 192.168.1.0/24.")
        job.update(phase="scanning", networks=[str(n) for n in networks])
        found = discover.scan(networks, lambda d, t: job.update(progress=round(d / t * 100)))
        saved = {row["serial"]: row for row in store.load()}
        for row in found:
            known = saved.get(row["serial"])
            if known:
                row.update(known=known["id"], name=known["name"], moved=known["host"] != row["host"],
                           saved_host=known["host"], model=known.get("model") or row["model"])
        job.update(state="done", phase="done", found=found, progress=None)
    except ValueError as exc:
        job.update(state="failed", error=str(exc))
    except OSError as exc:
        job.update(state="failed", error=f"The scan could not run: {exc}")
    finally:
        job["finished"] = time.time()


async def h_printer_scan(request):
    body = await _body(request)
    panel = _panel(request)
    job = panel.new_job("scan")
    threading.Thread(target=_scan_job, args=(job, str(body.get("subnet") or "").strip()),
                     daemon=True).start()
    job = await _wait_for(panel, job, body.get("wait"))
    return web.json_response({"ok": job["state"] != "failed", "job": job,
                              **({"error": job["error"]} if job["state"] == "failed" else {})})


async def h_printer_delete(request):
    removed = await asyncio.to_thread(store.remove, request.match_info["id"])
    await asyncio.to_thread(_panel(request).sync_clients)
    return web.json_response({"ok": removed})


async def h_command(request):
    body = await _body(request)
    try:
        row, client = _panel(request).printer(body.get("printer"))
    except LookupError as exc:
        return _err(str(exc), 404)
    action = str(body.get("action") or "").strip().lower()
    if action == "reconnect":
        await asyncio.to_thread(_panel(request).reconnect, row["id"])
        return web.json_response({"ok": True, "printer": row["name"], "action": action,
                                  "acknowledged": True, "note": ""})
    try:
        answer = await asyncio.to_thread(run_command, client, action, body)
    except ValueError as exc:
        return _err(str(exc))
    except (ConnectionError, RuntimeError) as exc:
        return _err(f"{row['name']}: {exc}", 409)
    note = "" if answer.get("acknowledged") else (
        "The printer did not confirm it. On recent firmware a printer obeys "
        "commands from Home Assistant only with LAN-only mode and Developer "
        "mode switched on.")
    return web.json_response({"ok": True, "printer": row["name"], "action": action,
                              **answer, "note": note})


async def h_storage(request):
    try:
        row, client = _panel(request).printer(request.query.get("printer"))
    except LookupError as exc:
        return _err(str(exc), 404)

    def _list():
        with ftps.Storage(row["host"], client.code) as storage:
            return storage.listing("/")

    try:
        files = await asyncio.to_thread(_list)
    except Exception as exc:  # noqa: BLE001 - ftplib raises its own zoo of errors
        return _err(f"Could not read {row['name']}'s storage: {exc}", 502)
    # Print jobs first, newest name last is how the printer lists them; the
    # card wants the jobs and nothing else (the logs and caches are folders).
    jobs = [f for f in files if not f["dir"] and f["name"].lower().endswith((".3mf", ".gcode"))]
    for f in jobs:
        f["printable"] = True
        f["picture"] = (f"api/printer/thumb?printer={urllib.parse.quote(row['id'])}"
                        f"&name={urllib.parse.quote(f['name'])}&size={f.get('size') or 0}"
                        if f["name"].lower().endswith(".3mf") else None)
        source = (_panel(request).uploaded.get(row["id"]) or {}).get(f["name"])
        f["library"] = source
    others = [f for f in files if f not in jobs]
    return web.json_response({"ok": True, "printer": row["name"], "files": jobs + others})


STORAGE_NAME = re.compile(r"^[^/\\\x00-\x1f]{1,200}$")


def _storage_name(name) -> str:
    """A file on the printer, as named in its own listing: no folders, nothing hidden."""
    text = str(name or "")
    if not STORAGE_NAME.match(text) or text.startswith(".") or ".." in text:
        raise ValueError("That is not a file on the printer.")
    return text


async def h_printer_thumb(request):
    try:
        row, client = _panel(request).printer(request.query.get("printer"))
        name = _storage_name(request.query.get("name"))
        size = int(request.query.get("size") or 0)
    except (LookupError, ValueError) as exc:
        return _err(str(exc), 404)

    def _read():
        return thumbs.printer(row["serial"], name, size,
                              lambda: ftps.Storage(row["host"], client.code))

    try:
        data = await asyncio.to_thread(_read)
    except Exception as exc:  # noqa: BLE001 - ftplib raises its own zoo of errors
        return _err(f"Could not read the picture: {exc}", 502)
    if not data:
        return _err("No picture in that file.", 404)
    return web.Response(body=data, content_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


async def h_printer_file_delete(request):
    try:
        row, client = _panel(request).printer(request.query.get("printer"))
        name = _storage_name(request.query.get("name"))
    except (LookupError, ValueError) as exc:
        return _err(str(exc), 404)

    def _delete():
        with ftps.Storage(row["host"], client.code) as storage:
            storage.ftp.delete(name)

    try:
        await asyncio.to_thread(_delete)
    except Exception as exc:  # noqa: BLE001 - ftplib raises its own zoo of errors
        return _err(f"Could not delete it from {row['name']}: {exc}", 502)
    return web.json_response({"ok": True})


def _start_stored(panel: Panel, row: dict, client: PrinterClient, name: str, body: dict) -> dict:
    """Start a job that is already on the printer's storage."""
    if client.summary().get("printing"):
        raise RuntimeError(f"{row['name']} is already printing.")
    start = options.clean_start(body)
    info: dict = {}
    source = (panel.uploaded.get(row["id"]) or {}).get(name)
    if source:
        try:
            info = threemf.inspect(str(library.path_of(source)))
        except ValueError:
            info = {}
    if not info and name.lower().endswith(".3mf"):
        size = int(body.get("size") or 0)
        if size:
            with ftps.Storage(row["host"], client.code) as storage:
                info = threemf.inspect(ftps.RemoteFile(storage, name, size))
    plates = info.get("plates") or [1]
    plate = int(body.get("plate") or plates[0])
    if name.lower().endswith(".gcode"):
        payload = {"print": {"command": "gcode_file", "param": f"/sdcard/{name}"}}
    else:
        if plate not in plates:
            raise ValueError(f"Plate {plate} is not in that file; it has plates "
                             f"{', '.join(map(str, plates))}.")
        use_ams = body.get("use_ams")
        if use_ams is None:
            use_ams = bool(client.summary().get("ams"))
        payload = protocol.project_file(
            name, plate, use_ams=bool(use_ams),
            ams_mapping=[int(x) for x in body.get("ams_mapping") or threemf.ams_mapping(info)],
            timelapse=bool(start.get("timelapse", False)),
            bed_leveling=bool(start.get("bed_leveling", True)),
            flow_cali=bool(start.get("flow_cali", False)),
            vibration_cali=bool(start.get("vibration_cali", True)),
            bed_type=options.mqtt_bed_type(start.get("plate_type")),
            layer_inspect=bool(start.get("layer_inspect", False)))
    answer = client.send(payload)
    return {"acknowledged": answer.get("acknowledged"), "plate": plate}


async def h_printer_file_print(request):
    body = await _body(request)
    panel = _panel(request)
    try:
        row, client = panel.printer(body.get("printer"))
        name = _storage_name(body.get("name"))
    except (LookupError, ValueError) as exc:
        return _err(str(exc), 404)
    try:
        answer = await asyncio.to_thread(_start_stored, panel, row, client, name, body)
    except (ValueError, RuntimeError, ConnectionError) as exc:
        return _err(f"{row['name']}: {exc}", 409)
    except Exception as exc:  # noqa: BLE001 - ftplib raises its own zoo of errors
        return _err(f"Could not read that file on {row['name']}: {exc}", 502)
    return web.json_response({"ok": True, "printer": row["name"], **answer})


async def h_camera(request):
    """The newest frame from a printer's camera, as a JPEG."""
    panel = _panel(request)
    try:
        camera = panel.camera(request.query.get("printer"))
    except LookupError as exc:
        return _err(str(exc), 404)
    frame = await asyncio.to_thread(camera.latest, 8.0)
    if frame is None:
        return _err(camera.error or "The camera has not sent a picture yet.", 503)
    return web.Response(body=frame, content_type="image/jpeg", headers={
        "Cache-Control": "no-store",
        "X-Frame-Age": str(round(time.time() - camera.frame_at, 1))})


async def h_thumb(request):
    """A library file's picture (a 3MF's own, or one drawn from the mesh)."""
    try:
        path = library.path_of(request.query.get("path"))
        plate = max(1, int(request.query.get("plate") or 1))
    except ValueError as exc:
        return _err(str(exc), 404)
    if not path.is_file():
        return _err("No such file.", 404)
    data = await asyncio.to_thread(thumbs.library, path, plate)
    if not data:
        return _err("No picture for that file.", 404)
    return web.Response(body=data, content_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"})


async def h_ha_check(_request):
    return web.json_response({"ok": True, "ha": {
        **await asyncio.to_thread(ha_setup.check, True), **ha_setup.status()}})


async def h_ha_restart(_request):
    ok, why = await asyncio.to_thread(ha_setup.restart_core)
    if not ok:
        return _err(f"Home Assistant did not restart: {why}", 502)
    return web.json_response({"ok": True})


async def h_print_options(_request):
    return web.json_response({"ok": True, **options.catalog()})


def _profiles() -> dict:
    return {kind: slicer.profile_names(kind) for kind in ("machine", "process", "filament")}


def _file_rows(working: bool) -> list[dict]:
    rows = library.listing(working)
    if not working:
        for row in parts.final_files():
            row.update(threemf.inspect(str(library.path_of(row["path"]))))
            rows.append(row)
    rows.sort(key=lambda r: r["modified"], reverse=True)
    return rows


async def h_files(request):
    working = request.query.get("working") in ("1", "true", "yes")
    payload = {"ok": True, "root": str(library.ROOT),
               "files": await asyncio.to_thread(_file_rows, working)}
    # The profile names a bare model is sliced with, for a caller (brAIn, an
    # automation) that has to name one. Asked for, because it is a long list.
    if request.query.get("profiles"):
        payload["profiles"] = await asyncio.to_thread(_profiles)
    return web.json_response(payload)


async def h_upload(request):
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return _err("Send the file as multipart field 'file'.")
    try:
        name = library.safe_upload_name(field.filename)
    except ValueError as exc:
        return _err(str(exc))
    await asyncio.to_thread(library.ensure)
    dest = library.unique(library.ROOT / name)
    size = 0
    with open(dest, "wb") as out:
        while chunk := await field.read_chunk(1 << 20):
            size += len(chunk)
            if size > library.MAX_UPLOAD:
                out.close()
                dest.unlink(missing_ok=True)
                return _err("That file is over 512 MB.", 413)
            out.write(chunk)
    return web.json_response({"ok": True, "path": library.relative(dest)})


async def h_import(request):
    """Bring a model in from a link (importer.py says which links work)."""
    body = await _body(request)
    panel = _panel(request)
    url = str(body.get("url") or "").strip()
    if not url:
        return _err("Paste a link to a model (Printables) or to a model file.")
    try:
        await asyncio.to_thread(library.ensure)
    except OSError as exc:
        return _err(f"The Bambu library cannot be written: {exc}", 500)
    job = panel.new_job("import", url=url[:500])
    threading.Thread(target=importer.run, args=(job, url), daemon=True).start()
    job = await _wait_for(panel, job, body.get("wait"))
    return web.json_response({"ok": job["state"] != "failed", "job": job,
                              **({"error": job["error"]} if job["state"] == "failed" else {})})


async def h_file_delete(request):
    try:
        path = library.path_of(request.query.get("path"))
    except ValueError as exc:
        return _err(str(exc))
    if not path.is_file():
        return _err("No such file.", 404)
    if library.relative(path).split(os.sep, 1)[0] == library.DESIGNS:
        # A version's file is part of the part: its history, its prints
        # and brAIn's next turn all read it.
        return _err("That file belongs to a designed part — delete the part on the "
                    "Design tab instead.", 409)
    path.unlink()
    return web.json_response({"ok": True})


async def h_slice(request):
    body = await _body(request)
    panel = _panel(request)
    try:
        job = await asyncio.to_thread(
            slicer.start, str(body.get("file") or ""), plate=int(body.get("plate") or 0),
            machine=str(body.get("machine") or ""), process=str(body.get("process") or ""),
            filaments=[str(f) for f in body.get("filaments") or []],
            arrange=bool(body.get("arrange")), orient=bool(body.get("orient")),
            env=panel.studio.env())
    except (ValueError, LookupError, FileNotFoundError, RuntimeError) as exc:
        return _err(str(exc))
    job = await _wait_for(panel, job, body.get("wait"))
    return web.json_response({"ok": job["state"] != "failed", "job": job,
                              **({"error": job["error"]} if job["state"] == "failed" else {})})


def _bare_model_profiles(body: dict, row: dict, client: PrinterClient) -> dict | None:
    """Profiles for a model that carries none, chosen the way a designed part's are.

    An STL, a STEP or a 3MF from Printables names no printer and no process,
    so the CLI cannot slice it as it is. Bambu Studio's own profiles for this
    printer's model are used, with the filament profile following the tray:
    `slot` names an AMS tray (its material decides), "external" is the
    external spool with `material` (PLA when unsaid), and no slot is the
    AMS tray that best matches `material` and `colour`. A Bambu Studio
    project, or a request that names its own profiles, is left alone.
    Mutates `body` with the AMS choice the print is started with.
    """
    source = library.path_of(body["file"])
    if body.get("machine") or body.get("process"):
        return None
    if source.name.lower().endswith(".3mf"):
        info = threemf.inspect(str(source))
        if info.get("sliced") or info.get("project"):
            return None
    slot = body.get("slot")
    material = str(body.get("material") or "PLA").upper()
    trays = client.summary().get("ams") or []
    if slot is None and trays:
        slot = recommend_tray(trays, material, str(body.get("colour") or ""))
    if isinstance(slot, int) and not isinstance(slot, bool) and 0 <= slot < 16:
        tray = next((t for t in trays if t.get("slot") == slot), None)
        if not tray:
            raise LookupError(f"{row['name']} has no AMS tray {slot + 1}.")
        material = str(tray.get("type") or material).upper()
        body.update(use_ams=True, ams_mapping=[slot])
    else:
        body.update(use_ams=False, ams_mapping=[0])
    scratch = Path(tempfile.gettempdir()) / "bruh-bambu-profiles" / row["id"]
    settings = {**(body.get("settings") if isinstance(body.get("settings"), dict) else {}),
                "material": material}
    if body.get("plate_type"):
        settings["plate_type"] = body["plate_type"]
    return profiles.prepare(row.get("model"), settings, scratch)


async def h_print(request):
    body = await _body(request)
    panel = _panel(request)
    if not body.get("file"):
        return _err("Name the file to print (its path in the library).")
    try:
        row, client = panel.printer(body.get("printer"))
        library.path_of(body["file"])
    except (LookupError, ValueError) as exc:
        return _err(str(exc), 404 if isinstance(exc, LookupError) else 400)
    if not client.connected:
        return _err(f"{row['name']} is not connected: "
                    f"{client.last_error or 'still connecting'}.", 409)
    try:
        prepared = await asyncio.to_thread(_bare_model_profiles, body, row, client)
    except (LookupError, OSError, ValueError) as exc:
        return _err(str(exc), 409)
    job = panel.new_job("print", printer=row["name"], file=body["file"])
    threading.Thread(target=_print_job,
                     args=(panel, job, row, client, body, panel.studio.env(), prepared),
                     daemon=True).start()
    job = await _wait_for(panel, job, body.get("wait"))
    return web.json_response({"ok": job["state"] != "failed", "job": job,
                              **({"error": job["error"]} if job["state"] == "failed" else {})})


async def h_job(request):
    job = _panel(request).job(request.match_info["id"])
    if job is None:
        return _err("No such job.", 404)
    return web.json_response({"ok": True, "job": job})


async def h_profiles(_request):
    return web.json_response({"ok": True, **await asyncio.to_thread(_profiles)})


# ---------------------------------------------------------------------------
# Design with brAIn (optional: every route works without brAIn except a turn)
# ---------------------------------------------------------------------------

COLOUR_NAMES = {
    "black": (0, 0, 0), "white": (255, 255, 255), "grey": (128, 128, 128),
    "gray": (128, 128, 128), "silver": (192, 192, 192), "red": (200, 30, 30),
    "orange": (240, 130, 20), "yellow": (240, 210, 30), "green": (40, 160, 60),
    "blue": (30, 90, 200), "cyan": (0, 180, 220), "purple": (120, 50, 160),
    "pink": (240, 120, 170), "brown": (120, 80, 40), "beige": (220, 200, 160),
    "gold": (210, 170, 50),
}


def _rgb(hex_colour: str):
    text = str(hex_colour or "").lstrip("#")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4)) if len(text) >= 6 else None
    except ValueError:
        return None


def recommend_tray(trays: list[dict], material: str, colour: str) -> int | None:
    """The AMS slot that best fits what brAIn recommended: the material
    first (a PETG part on a PLA tray is a different part), then the colour."""
    material = str(material or "").upper()
    wanted = _rgb(colour) if str(colour or "").startswith("#") else next(
        (rgb for name, rgb in COLOUR_NAMES.items() if name in str(colour).lower()), None)
    best, best_score = None, None
    for tray in trays:
        kind = str(tray.get("type") or "").upper()
        score = 0 if kind == material else 1 if kind.startswith(material) else 3
        rgb = _rgb(tray.get("colour"))
        if wanted and rgb:
            score += sum((a - b) ** 2 for a, b in zip(wanted, rgb)) ** 0.5 / 450
        if best_score is None or score < best_score:
            best, best_score = tray.get("slot"), score
    return best if best_score is not None and best_score < 3 else None


def _part_or_404(request) -> dict:
    try:
        return parts.load(request.match_info["id"])
    except (ValueError, LookupError):
        raise web.HTTPNotFound(text=json.dumps({"ok": False, "error": "No such part."}),
                               content_type="application/json") from None


async def h_design_status(_request):
    return web.json_response({"ok": True, "brain": brain_link.status(),
                              "cad": runner.available(),
                              "viewer": (VENDOR_DIR / "three.module.min.js").is_file()})


async def h_design_parts(_request):
    return web.json_response({"ok": True, "parts": await asyncio.to_thread(parts.listing)})


async def h_design_create(request):
    body = await _body(request)
    await asyncio.to_thread(library.ensure)
    part = await asyncio.to_thread(parts.create, body.get("name") or "New part")
    started = False
    if str(body.get("message") or "").strip():
        if brain_link.status()["state"] != "ok":
            return _err(brain_link.status()["sentence"], 409)
        started = await asyncio.to_thread(designer.start_turn, part["id"], body["message"])
        part = parts.load(part["id"])
    return web.json_response({"ok": True, "part": part, "started": started})


async def h_design_part(request):
    return web.json_response({"ok": True, "part": _part_or_404(request)})


async def h_design_delete(request):
    part = _part_or_404(request)
    if part.get("state") in ("thinking", "building", "fixing", "printing"):
        return _err("brAIn is still working on this part.", 409)
    import shutil
    await asyncio.to_thread(shutil.rmtree, parts.folder(part["id"]), True)
    return web.json_response({"ok": True})


async def h_design_message(request):
    part = _part_or_404(request)
    body = await _body(request)
    status = brain_link.status()
    if status["state"] != "ok":
        return _err(status["sentence"], 409)
    try:
        started = await asyncio.to_thread(designer.start_turn, part["id"], body.get("text"))
    except ValueError as exc:
        return _err(str(exc))
    if not started:
        return _err("brAIn is still working on the last message.", 409)
    return web.json_response({"ok": True, "part": parts.load(part["id"])})


async def h_design_update(request):
    """Rename, make a version current, or edit the print settings."""
    part = _part_or_404(request)
    body = await _body(request)
    if "name" in body:
        part["name"] = str(body["name"]).strip()[:80] or part["name"]
    if "current" in body:
        row = parts.version(part, body["current"])
        if row is None or not row.get("ok"):
            return _err("That version did not build, so it cannot be the current one.")
        part["current"] = row["n"]
        parts.say(part, "system", f"Went back to version {row['n']}; the next change builds on it.")
    if "print_settings" in body:
        settings = designer.clean_settings(body["print_settings"])
        if settings is None:
            return _err("Those print settings could not be read.")
        part["print_settings"] = settings
    await asyncio.to_thread(parts.save, part)
    return web.json_response({"ok": True, "part": part})


async def h_design_file(request):
    part = _part_or_404(request)
    try:
        n = int(request.query.get("v") or part.get("current") or 0)
        path = parts.file_in(part["id"], n, request.query.get("path") or "")
    except (ValueError, LookupError):
        return _err("No such file.", 404)
    return web.FileResponse(path, headers={"Cache-Control": "no-cache"})


async def h_design_thumb(request):
    part = _part_or_404(request)
    path = parts.folder(part["id"]) / "thumb.png"
    if request.method == "GET":
        if not path.is_file():
            return _err("No picture yet.", 404)
        return web.FileResponse(path, headers={"Cache-Control": "no-cache"})
    data = await request.read()
    if len(data) > 1_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _err("Send a PNG under 1 MB.")
    await asyncio.to_thread(bambu_atomic.write_bytes, path, data)
    return web.json_response({"ok": True})


def _version_3mf(part: dict, n) -> tuple[int, dict, Path]:
    n = int(n or part.get("current") or 0)
    row_v = parts.version(part, n)
    if not row_v or not row_v.get("ok") or not (row_v.get("files") or {}).get("3mf"):
        raise PrintRefused("This part has no built version to print yet.")
    return n, row_v, parts.version_dir(part["id"], n) / row_v["files"]["3mf"]


def _body_colours(part: dict, row_v: dict, names: list[str] | None) -> dict:
    """Each body's colour: the script's COLORS, else brAIn's suggestion."""
    fallback = (part.get("print_settings") or {}).get("colour", "")
    colours = row_v.get("colors") or {}
    return {name: colours.get(name) or fallback for name in (names or ["Part"])}


def _plan(part: dict, printer_row: dict, client: PrinterClient | None) -> dict:
    settings = part.get("print_settings") or {}
    trays = (client.summary().get("ams") if client else None) or []
    plan = {"settings": settings, "trays": trays,
            "recommended_slot": recommend_tray(trays, settings.get("material", "PLA"),
                                               settings.get("colour", ""))}
    try:
        _n, row_v, source = _version_3mf(part, None)
        names = painting.bodies(source)
    except PrintRefused:
        row_v, names = {}, None
    # A part whose 3MF names a filament per body is offered a tray per
    # body; an older one prints in one filament.
    if names and len(names) > 1:
        material = settings.get("material", "PLA")
        plan["bodies"] = [{"name": name, "colour": colour,
                           "recommended_slot": recommend_tray(trays, material, colour)}
                          for name, colour in _body_colours(part, row_v, names).items()]
    try:
        machine = profiles.machine_for(printer_row.get("model"))
        plan["machine"] = machine
        plan["process"] = profiles.process_for(machine, settings.get("layer_height"))
        plan["filament"] = profiles.filament_for(machine, settings.get("material", "PLA"))
    except LookupError as exc:
        plan["problem"] = str(exc)
    return plan


async def h_design_plan(request):
    part = _part_or_404(request)
    panel = _panel(request)
    try:
        row, client = panel.printer(request.query.get("printer"))
    except LookupError as exc:
        return _err(str(exc), 404)
    plan = await asyncio.to_thread(_plan, part, row, client)
    return web.json_response({"ok": True, "printer": row["name"], **plan})


TURN_STATES = ("thinking", "building", "fixing", "printing")
RECORD_WAIT_S = 1800


class PrintRefused(Exception):
    """A design print that cannot start, with the status a route answers."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _slot_word(slot, trays: dict) -> str:
    if slot == "external":
        return "the external spool"
    tray = trays.get(slot) or {}
    return f"AMS {slot + 1} ({' '.join(x for x in (tray.get('colour'), tray.get('type')) if x)})"


def _chosen_slots(names: list[str] | None, slots, trays: dict, material: str,
                  colours: dict) -> dict:
    """{body: tray or "external"} from what was asked, filling in the rest.

    `slots` is one slot for the whole part, or {body: slot}; a body nobody
    named takes the tray that best fits its colour, else the external spool.
    """
    keys = names or ["Part"]
    if isinstance(slots, dict) and not names:
        # A version from before per-body filaments prints in one: the first named.
        slots = next(iter(slots.values()), None)
    if not isinstance(slots, dict):
        slots = {name: slots for name in keys}
    chosen = {}
    for name in keys:
        slot = slots.get(name)
        if slot is None or slot == "":
            slot = recommend_tray(list(trays.values()), material, colours.get(name, ""))
            slot = "external" if slot is None else slot
        if slot in ("external", -1, "-1"):
            chosen[name] = "external"
            continue
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            raise PrintRefused(f"{slot!r} is not an AMS tray.") from None
        if slot not in trays:
            raise PrintRefused(f"AMS tray {slot + 1} has no filament loaded.", 409)
        chosen[name] = slot
    return chosen


def _part_note(part_id: str, text: str, **extra) -> None:
    """A line in a part's conversation from outside a turn.

    A turn holds the part in memory and saves it when it ends; a note written
    under it would be lost, so it waits for the turn to finish.
    """
    deadline = time.time() + RECORD_WAIT_S
    while parts.load(part_id).get("state") in TURN_STATES and time.time() < deadline:
        time.sleep(0.2)
    fresh = parts.load(part_id)
    for key, value in extra.items():
        fresh.setdefault(key, []).append(value)
    parts.say(fresh, "system", text)
    parts.save(fresh)


def start_design_print(panel: Panel, part_id: str, *, version=None, printer=None,
                       slots=None, settings=None, timelapse=False) -> tuple[dict, dict, str]:
    """Slice a designed part for one printer and send it: (job, prepared, sentence).

    The one path for the dialog's Slice and print and for brAIn starting a
    print from the conversation. PrintRefused says why it cannot start.
    """
    part = parts.load(part_id)
    n, row_v, source = _version_3mf(part, version)
    try:
        row, client = panel.printer(printer)
    except LookupError as exc:
        raise PrintRefused(str(exc), 404) from None
    if not client.connected:
        raise PrintRefused(f"{row['name']} is not connected: "
                           f"{client.last_error or 'still connecting'}.", 409)
    summary = client.summary()
    if summary.get("printing"):
        raise PrintRefused(f"{row['name']} is already printing.", 409)
    trays = {t["slot"]: t for t in summary.get("ams") or [] if isinstance(t.get("slot"), int)}
    settings = designer.clean_settings({**(part.get("print_settings") or {}),
                                        **(settings or {})}) or {}
    if timelapse:
        settings["timelapse"] = True
    names = painting.bodies(source)
    colours = _body_colours(part, row_v, names)
    chosen = _chosen_slots(names, slots, trays, settings.get("material", "PLA"), colours)
    order, filament = painting.plan(chosen)
    if len(order) > 1 and "external" in order:
        raise PrintRefused("The external spool holds one filament; a part in several "
                           "filaments prints from the AMS.", 409)
    use_ams = order != ["external"]
    wanted = []
    for slot in order:
        tray = trays.get(slot) if slot != "external" else None
        wanted.append({"material": str(tray["type"]).upper() if tray and tray.get("type")
                       else settings.get("material", "PLA"),
                       "colour": (tray or {}).get("colour") or ""})
    settings["material"] = wanted[0]["material"]
    work = parts.version_dir(part["id"], n) / f"slicing-{row['id']}"
    try:
        prepared = profiles.prepare(row.get("model"), settings, work, wanted)
        if names:
            # The parts' filament numbers follow the trays used, in order.
            target = work / source.name
            painting.retarget(source, target, filament)
            source = target
    except (LookupError, OSError, ValueError, KeyError) as exc:
        raise PrintRefused(str(exc), 409) from None
    job_body = {**options.clean_start(settings), "file": library.relative(source),
                "use_ams": use_ams, "ams_mapping": order if use_ams else [0]}
    job = panel.new_job("print", printer=row["name"], file=job_body["file"], part=part["id"])
    if names and len(chosen) > 1:
        where = "; ".join(f"{body} from {_slot_word(slot, trays)}" for body, slot in chosen.items())
    else:
        where = f"from {_slot_word(next(iter(chosen.values())), trays)}"
    sentence = f"version {n} on {row['name']}, {where}"
    extras: list[str] = []
    if settings.get("print_sequence") == "by object":
        extras.append("one object at a time")
    if int(settings.get("copies") or 1) > 1:
        extras.append(f"{settings['copies']} copies")
    if settings.get("plate_type") and settings["plate_type"] != "auto":
        extras.append(options.PLATES[settings["plate_type"]][0])
    if extras:
        sentence += " (" + ", ".join(extras) + ")"
    if prepared.get("adjusted"):
        sentence += ". Changed to slice: " + " ".join(prepared["adjusted"])

    def record(finished: dict) -> None:
        _part_note(part["id"], (
            f"Started {sentence} ({prepared['filament']}, {prepared['process']}). "
            "Watch it on the Printers tab."
            if finished["state"] == "done" else f"Printing version {n} failed: {finished.get('error')}"),
            prints={"at": time.time(), "printer": row["name"], "version": n,
                    "job": finished["id"], "state": finished["state"],
                    "error": finished.get("error", ""), "material": settings.get("material"),
                    "slots": chosen, "seconds": finished.get("seconds"),
                    "grams": finished.get("grams")})

    def notify(text: str) -> None:
        _part_note(part["id"], text)

    threading.Thread(target=_print_job, args=(panel, job, row, client, job_body,
                                              panel.studio.env(), prepared, record, notify),
                     daemon=True).start()
    return job, prepared, sentence


async def h_design_print(request):
    part = _part_or_404(request)
    panel = _panel(request)
    body = await _body(request)
    slots = body.get("slots") if isinstance(body.get("slots"), dict) else body.get("slot")
    try:
        job, prepared, _sentence = await asyncio.to_thread(
            start_design_print, panel, part["id"], version=body.get("version"),
            printer=body.get("printer"), slots=slots,
            settings=body.get("print_settings") or {}, timelapse=bool(body.get("timelapse")))
    except PrintRefused as exc:
        return _err(str(exc), exc.status)
    job = await _wait_for(panel, job, body.get("wait"))
    return web.json_response({"ok": job["state"] != "failed", "job": job, "plan": {
        k: prepared[k] for k in ("machine", "process", "filament", "material")},
        **({"error": job["error"]} if job["state"] == "failed" else {})})


async def h_design_studio(request):
    """Open one version's 3MF in Bambu Studio, to set it up and print there."""
    part = _part_or_404(request)
    panel = _panel(request)
    body = await _body(request)
    try:
        _n, _row, source = _version_3mf(part, body.get("version"))
    except PrintRefused as exc:
        return _err(str(exc), exc.status)
    if not source.is_file():
        return _err("That version's 3MF is missing.", 404)
    opened, note = await asyncio.to_thread(_studio_copy, panel, part, _row, source, body.get("printer"))
    await asyncio.to_thread(panel.studio.restart, str(opened))
    return web.json_response({"ok": True, "studio": panel.studio.state(), "note": note})


def _studio_copy(panel: Panel, part: dict, row_v: dict, source: Path, printer=None) -> tuple[Path, str]:
    """A copy of a version's 3MF that Bambu Studio opens as a project.

    Without Metadata/project_settings.config naming a Bambu Lab printer, the
    GUI loads it as geometry only, under "The 3mf file has invalid config".
    The copy carries the real profiles for one of the person's printers (the
    one asked for, else the first with a model set), the part's settings and
    one filament per colour. With no printer model known it opens the file
    as it is, and says why.
    """
    rows = [r for r in store.load() if r.get("model")]
    if printer:
        rows = [r for r in rows if printer in (r.get("id"), r.get("name"))] or rows
    if not rows:
        return source, "Set a printer's model on the Printers tab so Bambu Studio opens it with its settings."
    row = rows[0]
    settings = part.get("print_settings") or {}
    names = painting.bodies(source)
    colours = _body_colours(part, row_v, names)
    order: list[str] = []
    for name in names or ["Part"]:
        colour = str(colours.get(name) or "").upper()
        if colour not in order:
            order.append(colour)
    filaments = [{"material": settings.get("material") or "PLA", "colour": c} for c in order]
    try:
        project = profiles.project_settings(row["model"], settings, filaments)
        target = source.with_name(source.stem + ".studio.3mf")
        painting.with_project(source, target, project)
    except (LookupError, OSError, ValueError, KeyError) as exc:
        log.warning("Opening %s without project settings: %s", source.name, exc)
        return source, f"Opened as geometry only: {exc}"
    return target, f"Opened with {row['name']}'s settings."


# Each model's build volume (X, Y, Z in mm), as Bambu Lab publishes it.
BUILD_VOLUMES = {"X1C": [256, 256, 256], "X1": [256, 256, 256], "X1E": [256, 256, 256],
                 "P1S": [256, 256, 256], "P1P": [256, 256, 256], "P2S": [256, 256, 256],
                 "A1": [256, 256, 256], "A1 mini": [180, 180, 180], "H2D": [325, 320, 325],
                 "H2S": [340, 320, 340]}


class DesignPrinting:
    """What the conversation needs from the printers: what is there, and
    starting a print brAIn chose (designer.PRINTING)."""

    def __init__(self, panel: Panel):
        self.panel = panel

    def context(self) -> list[dict]:
        out = []
        for row in self.panel.printers():
            out.append({
                "id": row["id"], "name": row["name"], "model": row.get("model") or "",
                "build_volume_mm": BUILD_VOLUMES.get(row.get("model") or ""),
                "nozzle_mm": row.get("nozzle_diameter") or "0.4",
                "online": bool(row.get("online")), "state": row.get("state") or "unknown",
                "stage": row.get("stage"), "progress": row.get("progress"),
                "remaining_min": row.get("remaining_min"),
                "printing": bool(row.get("printing")),
                "loaded_in_nozzle": row.get("active_tray"),
                "external_spool": ({"material": row["external_spool"].get("type"),
                                    "colour": row["external_spool"].get("colour")}
                                   if row.get("external_spool") else None),
                "ams_humidity": [u.get("humidity") for u in row.get("ams_units") or []],
                "trays": [{"slot": t["slot"], "material": t.get("type"), "colour": t.get("colour"),
                           "remaining_percent": t.get("remaining")} for t in row.get("ams") or []],
            })
        return out

    def start(self, part_id: str, request: dict) -> str:
        try:
            _job, _prepared, sentence = start_design_print(
                self.panel, part_id, printer=request.get("printer"),
                slots=request.get("slots"), settings=request.get("settings") or {},
                timelapse=bool(request.get("timelapse")))
        except (PrintRefused, LookupError, ValueError, OSError) as exc:
            return f"The print did not start: {exc}"
        return f"Slicing and sending {sentence}. Follow it on the Printers tab."


def _asset(name: str, content_type: str):
    async def handler(_request):
        return web.FileResponse(PANEL_DIR / name, headers={
            "Content-Type": content_type, "Cache-Control": "no-cache"})
    return handler


@web.middleware
async def json_errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:  # noqa: BLE001 - one bad route must not take the panel down
        log.exception("Unhandled error on %s", request.path)
        return _err("Something went wrong inside the panel; the add-on log has the details.", 500)


def _for_log(text, limit: int = 200) -> str:
    return "".join(c if c.isprintable() and c.isascii() else "?" for c in str(text))[:limit]


class QuietAccessLogger(AbstractAccessLogger):
    """Successful polls are not news; failures always log."""

    QUIET = ("/api/state", "/api/health", "/api/files", "/api/job", "/websockify",
             "/novnc/", "/vendor/", "/api/design/parts/", "/api/printer/camera",
             "/api/thumb", "/api/printer/thumb")

    def log(self, request, response, time_taken):  # noqa: D102
        status = getattr(response, "status", 0)
        path = getattr(request, "path", "")
        method = _for_log(getattr(request, "method", "?"), 8)
        if status < 400 and any(path.startswith(p) for p in self.QUIET):
            self.logger.debug("%s %s %s", method, _for_log(path), status)
            return
        level = logging.WARNING if status >= 400 else logging.INFO
        self.logger.log(level, "%s %s %s (%.0fms)", method, _for_log(path),
                        status, time_taken * 1000)


async def _ticker(app):
    panel = app[PANEL_KEY]

    async def loop():
        while True:
            try:
                await asyncio.to_thread(panel.tick)
            except Exception:  # noqa: BLE001 - the timer must outlive one bad tick
                log.exception("Panel tick failed")
            await asyncio.sleep(TICK_S)

    task = asyncio.create_task(loop())
    yield
    task.cancel()


def build_app(panel: Panel | None = None, *, ticker: bool = True) -> web.Application:
    app = web.Application(middlewares=[json_errors],
                          client_max_size=library.MAX_UPLOAD + (1 << 20))
    app[PANEL_KEY] = panel or Panel()
    # The conversation reads the printers and starts the prints brAIn chose.
    designer.PRINTING = DesignPrinting(app[PANEL_KEY])
    # A headless slice may close the window for its memory (studio.make_room).
    studio_ = getattr(app[PANEL_KEY], "studio", None)
    slicer.MAKE_ROOM = getattr(studio_, "make_room", None)
    r = app.router
    r.add_get("/", _asset("index.html", "text/html"))
    r.add_get("/app.js", _asset("app.js", "application/javascript"))
    r.add_get("/style.css", _asset("style.css", "text/css"))
    r.add_get("/favicon.svg", _asset("favicon.svg", "image/svg+xml"))
    r.add_get("/websockify", vnc_bridge.handle)
    if NOVNC_DIR.is_dir():
        r.add_static("/novnc/", NOVNC_DIR)
    r.add_get("/api/health", h_health)
    r.add_get("/api/state", h_state)
    r.add_post("/api/studio/install", h_install)
    r.add_post("/api/studio/{action}", h_studio)
    r.add_get("/api/printers", h_printers)
    r.add_post("/api/printers", h_printer_save)
    r.add_post("/api/printers/scan", h_printer_scan)
    r.add_delete("/api/printers/{id}", h_printer_delete)
    r.add_post("/api/printer/command", h_command)
    r.add_get("/api/printer/storage", h_storage)
    r.add_delete("/api/printer/storage", h_printer_file_delete)
    r.add_post("/api/printer/storage/print", h_printer_file_print)
    r.add_get("/api/printer/thumb", h_printer_thumb)
    r.add_get("/api/printer/camera", h_camera)
    r.add_get("/api/thumb", h_thumb)
    r.add_post("/api/ha/check", h_ha_check)
    r.add_post("/api/ha/restart", h_ha_restart)
    r.add_get("/api/print/options", h_print_options)
    r.add_get("/api/files", h_files)
    r.add_post("/api/files", h_upload)
    r.add_post("/api/import", h_import)
    r.add_delete("/api/files", h_file_delete)
    r.add_post("/api/slice", h_slice)
    r.add_post("/api/print", h_print)
    r.add_get("/api/job/{id}", h_job)
    r.add_get("/api/profiles", h_profiles)
    r.add_get("/viewer.js", _asset("viewer.js", "application/javascript"))
    r.add_get("/design.js", _asset("design.js", "application/javascript"))
    if VENDOR_DIR.is_dir():
        r.add_static("/vendor/", VENDOR_DIR)
    r.add_get("/api/design/status", h_design_status)
    r.add_get("/api/design/parts", h_design_parts)
    r.add_post("/api/design/parts", h_design_create)
    r.add_get("/api/design/parts/{id}", h_design_part)
    r.add_delete("/api/design/parts/{id}", h_design_delete)
    r.add_post("/api/design/parts/{id}", h_design_update)
    r.add_post("/api/design/parts/{id}/message", h_design_message)
    r.add_get("/api/design/parts/{id}/file", h_design_file)
    r.add_get("/api/design/parts/{id}/thumb", h_design_thumb)
    r.add_post("/api/design/parts/{id}/thumb", h_design_thumb)
    r.add_get("/api/design/parts/{id}/plan", h_design_plan)
    r.add_post("/api/design/parts/{id}/print", h_design_print)
    r.add_post("/api/design/parts/{id}/studio", h_design_studio)
    if ticker:
        app.cleanup_ctx.append(_ticker)
    return app


def main() -> None:
    level = os.environ.get("BAMBU_LOG_LEVEL", "info").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="[panel %(asctime)s] %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("aiohttp.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    panel = Panel()
    library.ensure()
    panel.sync_clients()
    designer.recover()
    if installer.installed() is None or os.environ.get("BAMBU_STUDIO_VERSION", "latest") not in (
            "latest", (installer.installed() or {}).get("version")):
        installer.start_install(os.environ.get("BAMBU_STUDIO_VERSION", "latest"),
                                os.environ.get("BAMBU_APPIMAGE_URL", ""),
                                after=lambda: panel.studio.restart())
    log.info("Starting the BRUH Bambu Studio panel on %s:%s", BIND_HOST, PORT)
    web.run_app(build_app(panel), host=BIND_HOST, port=PORT,
                access_log_class=QuietAccessLogger,
                access_log=logging.getLogger("bruh_bambu.access"),
                print=lambda *_a: log.info("Panel listening on %s:%s", BIND_HOST, PORT))


if __name__ == "__main__":
    main()
