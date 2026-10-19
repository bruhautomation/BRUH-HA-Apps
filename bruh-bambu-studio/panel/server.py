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
import threading
import time
import uuid
from pathlib import Path

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import atomic_write  # noqa: E402
import installer  # noqa: E402
import library  # noqa: E402
import slicer  # noqa: E402
import store  # noqa: E402
import vnc_bridge  # noqa: E402
from bambu import ftps, protocol, threemf  # noqa: E402
from bambu.client import PrinterClient  # noqa: E402
from studio import Studio  # noqa: E402

log = logging.getLogger("bruh_bambu")

PANEL_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
NOVNC_DIR = Path(os.environ.get("BAMBU_NOVNC_DIR", "/usr/share/novnc"))
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
           "temperature", "home", "refresh")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class Panel:
    def __init__(self, *, start_clients: bool = True):
        self.studio = Studio()
        self.clients: dict[str, PrinterClient] = {}
        self.jobs: dict[str, dict] = {}
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

    def printers(self) -> list[dict]:
        out = []
        for row in store.load():
            client = self.clients.get(row["id"])
            summary = client.summary() if client else {
                "online": False, "connection_error": "No access code saved."}
            out.append({**row, **summary})
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
        }

    # -- the timer ---------------------------------------------------------
    def tick(self) -> None:
        self.studio.tick()
        for client in list(self.clients.values()):
            client.tick()
        self.publish()

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
            atomic_write.write_json(STATE_FILE, mirror, mode=0o644)
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
    else:
        raise ValueError(f"Unknown action {action!r}. Known: {', '.join(ACTIONS)}.")
    if action in ("gcode", "temperature", "home") and client.summary().get("state") in (
            "running", "prepare"):
        raise ValueError("The printer is printing; G-code and temperature changes "
                         "wait until it is paused or finished.")
    return client.send(payload)


def _print_job(panel: Panel, job: dict, row: dict, client: PrinterClient,
               body: dict, env: dict) -> None:
    try:
        source = library.path_of(body["file"])
        info = threemf.inspect(str(source)) if source.name.lower().endswith(".3mf") else {
            "sliced": False}
        if not info.get("sliced"):
            job["phase"] = "slicing"
            slice_job = slicer.start(body["file"], plate=int(body.get("plate") or 0),
                                     machine=body.get("machine") or "",
                                     process=body.get("process") or "",
                                     filaments=body.get("filaments") or None,
                                     arrange=bool(body.get("arrange")),
                                     orient=bool(body.get("orient")), env=env)
            job["slice_job"] = slice_job["id"]
            done = slicer.wait(slice_job["id"], slicer.TIMEOUT_S + 30)
            if not done or done["state"] != "done":
                raise RuntimeError((done or {}).get("error") or "Slicing did not finish.")
            source = library.path_of(done["output"])
            info = done["info"]
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
        job["phase"] = "starting"
        use_ams = body.get("use_ams")
        if use_ams is None:
            use_ams = bool(client.summary().get("ams"))
        mapping = body.get("ams_mapping") or threemf.ams_mapping(info)
        payload = protocol.project_file(
            name, plate, use_ams=bool(use_ams), ams_mapping=[int(x) for x in mapping],
            timelapse=bool(body.get("timelapse", False)),
            bed_leveling=bool(body.get("bed_leveling", True)),
            flow_cali=bool(body.get("flow_cali", False)),
            vibration_cali=bool(body.get("vibration_cali", True)))
        answer = client.send(payload)
        job.update(state="done", phase="started", file=library.relative(source),
                   plate=plate, acknowledged=answer.get("acknowledged"),
                   seconds=info.get("seconds"), grams=info.get("grams"))
    except (OSError, ValueError, LookupError, RuntimeError, ConnectionError,
            EOFError) as exc:
        job.update(state="failed", error=str(exc) or exc.__class__.__name__)
    finally:
        job["finished"] = time.time()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

PANEL_KEY = web.AppKey("panel", Panel)


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
    return web.json_response({"ok": True, "printer": row["name"], "files": files})


def _profiles() -> dict:
    return {kind: slicer.profile_names(kind) for kind in ("machine", "process", "filament")}


async def h_files(request):
    payload = {"ok": True, "root": str(library.ROOT),
               "files": await asyncio.to_thread(library.listing)}
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


async def h_file_delete(request):
    try:
        path = library.path_of(request.query.get("path"))
    except ValueError as exc:
        return _err(str(exc))
    if not path.is_file():
        return _err("No such file.", 404)
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
    job = panel.new_job("print", printer=row["name"], file=body["file"])
    threading.Thread(target=_print_job,
                     args=(panel, job, row, client, body, panel.studio.env()),
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
             "/novnc/")

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
    r.add_delete("/api/printers/{id}", h_printer_delete)
    r.add_post("/api/printer/command", h_command)
    r.add_get("/api/printer/storage", h_storage)
    r.add_get("/api/files", h_files)
    r.add_post("/api/files", h_upload)
    r.add_delete("/api/files", h_file_delete)
    r.add_post("/api/slice", h_slice)
    r.add_post("/api/print", h_print)
    r.add_get("/api/job/{id}", h_job)
    r.add_get("/api/profiles", h_profiles)
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
