#!/usr/bin/env python3
"""
BRight ingress panel — aiohttp API + static asset server.

Routes
------
GET  /                      — panel HTML
GET  /style.css, /app.js    — static assets
GET  /favicon.svg           — the BRight tile
GET  /api/health            — liveness, polled by run.sh over loopback
GET  /api/status            — version + options snapshot for the UI

Runs as the `bright` user on 0.0.0.0, on the port `panel_port.resolve()`
answers with — the Supervisor assigns it (config.yaml asks with
`ingress_port: 0`) because on a host-network add-on a port written into a
manifest is a port somebody else's box may already own. The HA Supervisor
proxies the ingress URL into /api/hassio_ingress/<token>/...; we therefore
use only relative links in the HTML and let aiohttp serve at /.

Why 0.0.0.0 is not the same as "public"
---------------------------------------
This add-on sets `host_network: true` (LIFX discovery is a UDP broadcast,
and cue latency is the product), so binding 0.0.0.0 puts this server
on the *host's* network — reachable from every device on the LAN, with no
Home Assistant login in front of it. Ingress is a proxy, not a gate: it
authenticates its own callers and has no say over anyone who types the IP
directly. That is the exposure Home Assistant documented in
GHSA-gh5m-4m97-c95h, and it is why the `_lan_gate` middleware below allows
the Supervisor's own networks and loopback and nothing else. Nothing at all
is public: `/api/health` used to be, for the Supervisor watchdog polling it
from off-network, and that watchdog is gone (config.yaml says why). The
health poll that replaced it runs inside this container, over loopback,
which the gate already trusts.
"""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import logging
import math
import os
import random
import re
import sys
import time
from pathlib import Path

from aiohttp import web

HERE = Path(__file__).resolve().parent
# APPENDED, not inserted at 0: running as a script already puts this
# directory first, and the append only serves spec-loaded imports (the
# tests). At the front it would shadow the brAIn panel's same-named
# modules for every test that imports `server` after this file loads.
if str(HERE) not in sys.path:
    sys.path.append(str(HERE))

import atomic_write  # noqa: E402
import ha_client  # noqa: E402
import media_source  # noqa: E402
import jobs  # noqa: E402
import panel_port  # noqa: E402
import playback_check  # noqa: E402
from analyzer import decode, features, library, pipeline  # noqa: E402
from calibrate import correlate, reference  # noqa: E402
from lifx import engine as lifx_engine  # noqa: E402
from director import build as director_build  # noqa: E402
from director import room  # noqa: E402
from director import claude_director  # noqa: E402
from director import choreographer  # noqa: E402
from director import compiler  # noqa: E402
from director import palettes as director_palettes  # noqa: E402
from director import preview as director_preview  # noqa: E402
from director.compiler import CompileError  # noqa: E402
from playback import autosync  # noqa: E402
from playback import conductor as conductor_mod  # noqa: E402
from director import effects as fx  # noqa: E402
from stores import calibration as calibration_store  # noqa: E402
from stores import effect_presets  # noqa: E402
from stores import folders as folders_store  # noqa: E402
from stores import light_map  # noqa: E402
from stores import parties as parties_store  # noqa: E402

STATIC = HERE
DATA_DIR = Path(os.environ.get("BRIGHT_STATE", "/data"))
ENV_FILE = Path(os.environ.get("BRIGHT_ENV_FILE", "/data/.bright_env"))
# The Supervisor's own copy of the add-on's options. Read directly for the
# one option that is a LIST — see `_additional_music_folders`.
OPTIONS_FILE = Path(os.environ.get("BRIGHT_OPTIONS", "/data/options.json"))
# Home Assistant's media folder, as this container sees it. Everything the
# add-on hands a media player has to live under it — the folders it scans
# for music, and the calibration click track it writes.
MEDIA_DIR = Path(os.environ.get("BRIGHT_MEDIA", "/media"))
# The one directory Home Assistant Core and this add-on can both see.
# /data is ours alone, so anything Core needs is mirrored here — derived,
# never read back.
SHARED_DIR = Path(os.environ.get("BRIGHT_SHARED", "/config/.bright"))
ADDON_VERSION = os.environ.get("ADDON_VERSION", "dev")
SUPERVISOR_API_URL = os.environ.get("SUPERVISOR_API_URL", "http://supervisor")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

BIND_HOST = "0.0.0.0"
# Resolved in main(), not here: importing this module (the tests do) must
# never reach for the Supervisor, and the answer is the same either way.

log = logging.getLogger("bright.panel")


# ---------------------------------------------------------------------------
# LAN gate — who is allowed to reach the panel
# ---------------------------------------------------------------------------
# The Supervisor proxies ingress requests from its own container, so a
# legitimate panel request arrives from the hassio docker network. These are
# the ranges the Supervisor documents for it, plus loopback for anything the
# add-on calls on itself.
_ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(cidr) for cidr in (
        "172.30.32.0/23",          # hassio bridge (Supervisor, ingress)
        "fd0c:ac1e:2100::/48",     # hassio bridge, IPv6
        "127.0.0.0/8",
        "::1/128",
    )
)

# Paths that answer anyone — deliberately none. A prefix belongs here only
# for a caller that cannot come from the Supervisor's networks or loopback,
# and since the port became the Supervisor's to assign there is no such
# caller left: run.sh polls /api/health on 127.0.0.1.
_PUBLIC_PREFIXES: tuple[str, ...] = ()


def _peer_ip(request: web.Request) -> str | None:
    """Source address of the connection itself.

    Deliberately NOT X-Forwarded-For: that header is set by the client on a
    direct connection, so trusting it would let a LAN caller claim to be the
    Supervisor and walk straight through this gate.
    """
    peer = request.transport.get_extra_info("peername") if request.transport else None
    # A TCP peername is (host, port[, ...]); a unix-socket one is a string
    # path, and a closed transport gives None. Only the tuple form carries
    # an address — anything else has no address to trust, and `_is_trusted`
    # turns that into a refusal rather than an exception in the middleware.
    if not isinstance(peer, tuple) or not peer:
        return None
    host = peer[0]
    if not isinstance(host, str):
        return None
    # IPv4-mapped IPv6 (::ffff:192.168.1.5) — compare as the IPv4 it is.
    if host.startswith("::ffff:"):
        host = host[len("::ffff:"):]
    return host


def _is_trusted(host: str | None) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _ALLOWED_NETWORKS)


def _for_log(value: str, limit: int = 256) -> str:
    """Flatten caller-supplied text to a single bounded log line.

    aiohttp hands us the path percent-decoded, so `%0a` arrives as a real
    newline and a caller could otherwise write its own lines into the log.
    Spelled out as `replace` calls rather than anything cleverer because
    the line break is the whole point, and each one is worth seeing named
    here (same reasoning as the Minecraft panel's copy of this).
    """
    return (str(value)
            .replace("\r\n", " ").replace("\n", " ")
            .replace("\r", " ").replace("\t", " ")[:limit])


@web.middleware
async def _lan_gate(request: web.Request, handler):
    """Refuse requests that did not come through the Supervisor."""
    if any(request.path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await handler(request)

    host = _peer_ip(request)
    if _is_trusted(host):
        return await handler(request)

    log.warning(
        "refused %s %s from %s — the panel is reachable on the LAN because "
        "host_network is on, but only Home Assistant may drive it",
        _for_log(request.method), _for_log(request.path), _for_log(host or "unknown"),
    )
    return web.json_response(
        {"error": "forbidden: open this panel from Home Assistant"},
        status=403,
    )


# ---------------------------------------------------------------------------
# Options snapshot
# ---------------------------------------------------------------------------
def _options_from_env() -> dict:
    """The options run.sh exported, read back from /data/.bright_env.

    The env file is the one route an add-on option has into a process
    started under with-contenv; the panel inherits the exports directly but
    reads the file so a restarted panel and a fresh one agree.
    """
    options = {
        "music_folder": os.environ.get("BRIGHT_MUSIC_FOLDER", "/media/music"),
        "director_mode": os.environ.get("BRIGHT_DIRECTOR_MODE", "auto"),
        "log_level": os.environ.get("BRIGHT_LOG_LEVEL", "info"),
    }
    try:
        for line in ENV_FILE.read_text().splitlines():
            if not line.startswith("export BRIGHT_"):
                continue
            key, _, raw = line[len("export "):].partition("=")
            value = raw.strip().strip("'")
            name = key[len("BRIGHT_"):].lower()
            if name in options:
                options[name] = value
    except OSError:
        # No env file yet (fresh install, or a dev checkout with no
        # run.sh) — the environment-variable defaults above already
        # answer, so a missing file costs nothing.
        pass
    return options


def _under_media(raw: str) -> Path | None:
    """`raw` as a folder inside /media, or None if it is not one.

    The confinement is not only about what the panel may read. A track BRight
    can see but Home Assistant cannot serve is a track that analyzes
    perfectly and then never plays: `conductor.media_content_id_for` builds a
    `media-source://media_source/local/…` URI, and that URI only exists for
    files under the media folder Core shares. A folder outside it would fill
    the Library tab with tracks whose every show ends in "no media id".

    Both spellings are accepted, because both are what people type: an
    absolute `/media/parties`, and a bare `parties` meaning the same thing.

    The path is then rebuilt **one component at a time** rather than
    normalised after the fact. Normalising and checking the prefix is the
    usual recipe and it is a check bolted onto a string that already said
    something else; joining validated components onto MEDIA_DIR cannot
    express an escape in the first place, which is a different and better
    kind of guarantee. A component may be any name a filesystem allows
    except the two that mean "somewhere else" — `.` is dropped, `..` is
    refused, and a separator cannot survive the split.

    Symlinks are deliberately followed: `/media/music` pointing at a NAS
    mount is a setup people really have, and anyone able to plant a symlink
    inside Home Assistant's media folder has the filesystem already.
    """
    text = str(raw).strip()
    if not text:
        return None
    base = str(MEDIA_DIR)
    if text == base:
        return MEDIA_DIR
    if text.startswith(base + os.sep):
        text = text[len(base) + 1:]
    else:
        text = text.lstrip("/").removeprefix("media/")
    folder = MEDIA_DIR
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == ".." or "\0" in part:
            return None
        folder = folder / part
    return folder


def _additional_music_folders() -> list[Path]:
    """The `additional_music_folders` option, from the Supervisor's own file.

    Every other option rides /data/.bright_env, because that file is the only
    route an option has into a process started under `with-contenv`. A LIST
    cannot ride it: packing several paths into one shell string needs a
    separator, and every separator is a character a path may legally contain
    — `/media/best of 80s:90s` is a folder somebody has. The panel is not a
    with-contenv child (run.sh starts it directly), so it reads the typed
    value from the file the Supervisor wrote, and nothing else reads this
    option at all — one reader, no separator, no second answer.

    Anything unreadable answers "no extra folders", never an exception: the
    music folder on its own is a working add-on.
    """
    try:
        options = json.loads(OPTIONS_FILE.read_text())
    except (OSError, ValueError):
        return []
    raw = options.get("additional_music_folders") if isinstance(options, dict) else None
    if not isinstance(raw, list):
        return []
    folders = []
    for item in raw:
        if not isinstance(item, str):
            continue
        folder = _under_media(item)
        if folder is not None:
            folders.append(folder)
    return folders


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def h_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "uptime_s": int(time.monotonic() - _STARTED)})


async def h_status(request: web.Request) -> web.Response:
    return web.json_response({
        "version": ADDON_VERSION,
        "options": {
            **_options_from_env(),
            "additional_music_folders": [str(f) for f in _additional_music_folders()],
        },
    })


def _render_index_html() -> str:
    html = (STATIC / "index.html").read_text()
    return html.replace("__VERSION__", ADDON_VERSION)


async def h_index(request: web.Request) -> web.Response:
    return web.Response(
        text=_render_index_html(),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Lab — the feasibility gate: real latency numbers from the real house
# ---------------------------------------------------------------------------
ENGINE = lifx_engine.LifxEngine()
HA_PROBES_FILE = DATA_DIR / "cache" / "ha-latency.json"


# Wire data becomes filenames (calibration profiles) and service payloads,
# so entity ids are validated to HA's own shape at the boundary — not
# best-effort-sanitized later.
_ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def _entity(body: dict, key: str = "media_player",
            domain: str | None = "media_player") -> str | None:
    value = str(body.get(key, ""))
    if not _ENTITY_RE.fullmatch(value):
        return None
    if domain and not value.startswith(f"{domain}."):
        return None
    return value


def _number(body: dict, key: str, default: float, low: float,
            high: float) -> float:
    """One number off the wire, clamped, never an exception.

    `int(body.get("count", 20) or 20)` reads fine and answers a bare HTTP
    500 for `{"count": "lots"}` — a traceback in the log about a value the
    panel is allowed to refuse in a sentence. Clamping rather than
    rejecting, because every caller here has a range where any answer is
    fine and the edges are the answer.
    """
    raw = body.get(key, default)
    try:
        value = float(raw if raw not in (None, "") else default)
    except (TypeError, ValueError):
        value = float(default)
    if math.isnan(value):
        value = float(default)
    return min(high, max(low, value))


async def _json_body(request: web.Request) -> dict:
    try:
        body = await request.json()
        return body if isinstance(body, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


async def h_lifx_devices(request: web.Request) -> web.Response:
    return web.json_response(
        {"devices": sorted(ENGINE.devices.values(),
                           key=lambda d: d.get("label") or d["serial"])})


async def h_lifx_discover(request: web.Request) -> web.Response:
    devices = await ENGINE.discover()
    return web.json_response({"devices": devices})


async def h_lifx_probe(request: web.Request) -> web.Response:
    body = await _json_body(request)
    serial = str(body.get("serial", ""))
    count = int(_number(body, "count", 20, 5, 100))
    if serial not in ENGINE.devices:
        return web.json_response({"error": "unknown device; discover first"},
                                 status=404)
    stats = await ENGINE.echo_probe(serial, count=count)
    return web.json_response(stats)


async def h_lifx_rate_test(request: web.Request) -> web.Response:
    body = await _json_body(request)
    serial = str(body.get("serial", ""))
    if serial not in ENGINE.devices:
        return web.json_response({"error": "unknown device; discover first"},
                                 status=404)
    job = jobs.start(f"rate-test:{serial}",
                     lambda: ENGINE.rate_ramp(serial))
    status = 409 if job.get("already") else 202
    return web.json_response({"job": job["id"]}, status=status)


async def h_lifx_waveform_demo(request: web.Request) -> web.Response:
    body = await _json_body(request)
    serial = str(body.get("serial", ""))
    if serial not in ENGINE.devices:
        return web.json_response({"error": "unknown device; discover first"},
                                 status=404)
    result = await ENGINE.waveform_demo(
        serial,
        bpm=_number(body, "bpm", 120, 30, 300),
        seconds=_number(body, "seconds", 10, 2, 60),
        hue_deg=_number(body, "hue_deg", 200, -3600, 3600) % 360.0,
    )
    return web.json_response(result)


async def h_ha_entities(request: web.Request) -> web.Response:
    domain = request.query.get("domain", "") or None
    states, error = await ha_client.async_states_or_error(domain)
    if error:
        # An empty picker is what this used to be, and it reads as "you own
        # no speakers" rather than "I could not ask Home Assistant".
        return web.json_response(
            {"error": f"could not read entities from Home Assistant: {error}",
             "entities": []},
            status=502)
    entities = [
        {
            "entity_id": s.get("entity_id"),
            "state": s.get("state"),
            "name": (s.get("attributes") or {}).get("friendly_name")
                    or s.get("entity_id"),
        }
        for s in states
    ]
    return web.json_response({"entities": entities})


async def h_ha_latency_probe(request: web.Request) -> web.Response:
    body = await _json_body(request)
    entity_id = _entity(body, key="entity_id", domain=None)
    if entity_id is None:
        return web.json_response({"error": "entity_id required"}, status=400)
    rounds = int(_number(body, "rounds", 6, 2, 20))

    async def _run():
        result = await ha_client.async_latency_probe(entity_id, rounds)
        # The report survives restarts: cue lead times are compiled from it.
        try:
            stored = json.loads(HA_PROBES_FILE.read_text())
        except (OSError, ValueError):
            # No file yet, or an unreadable one. Either way this probe is
            # the first entry rather than an addition to what was there.
            stored = {}
        if not isinstance(stored, dict):
            stored = {}
        stored[entity_id] = {**result, "measured_at": time.time()}
        try:
            atomic_write.write_json(HA_PROBES_FILE, stored, indent=2)
        except OSError:
            log.warning("could not persist HA latency probe result")
        return result

    job = jobs.start(f"ha-probe:{entity_id}", _run)
    status = 409 if job.get("already") else 202
    return web.json_response({"job": job["id"]}, status=status)


async def h_job(request: web.Request) -> web.Response:
    job = jobs.get(request.match_info["job_id"])
    if job is None:
        return web.json_response({"error": "unknown job"}, status=404)
    return web.json_response(job)


async def h_lab_report(request: web.Request) -> web.Response:
    """Everything the Lab has measured, in one read."""
    try:
        ha_probes = json.loads(HA_PROBES_FILE.read_text())
    except (OSError, ValueError):
        ha_probes = {}
    return web.json_response({
        "lifx": lifx_engine.stats_for_report(ENGINE.devices),
        "ha_service_calls": ha_probes,
        "generated_at": time.time(),
    })


# ---------------------------------------------------------------------------
# Library — the music folder, analyzed ahead of the party
# ---------------------------------------------------------------------------
def _music_folder() -> Path:
    """The main folder — the one option every install has set."""
    return Path(_options_from_env()["music_folder"])


def _picked_music_folders() -> list[Path]:
    """The folders someone ticked in the Library tab.

    Stored relative to /media (the store says why), and re-checked against
    /media on the way out rather than trusted: the file outlives the panel
    that wrote it, and a path is only ever as good as the last thing that
    validated it.
    """
    picked = []
    for relative in folders_store.load():
        folder = _under_media(relative)
        if folder is not None:
            picked.append(folder)
    return picked


def _music_folders() -> list[Path]:
    """Everywhere BRight looks for music: the music folder, then the options'
    extras, then anything ticked in the panel.

    Ordered and de-duplicated by path, so naming a folder twice costs
    nothing. Overlap costs nothing either — the scan de-duplicates by track
    hash, which is what makes a folder nested inside another one harmless.

    Two sources, one list, and neither is a second answer: the options are
    configuration that survives a reinstall, the store is what somebody
    ticked without editing YAML.
    """
    folders = [_music_folder()]
    for folder in _additional_music_folders() + _picked_music_folders():
        if folder not in folders:
            folders.append(folder)
    return folders


def _folder_listing(folder: Path) -> dict:
    """One level of /media, as folders with a hint of what is in them.

    The count is the audio files *directly* inside — not a recursive scan,
    which on a real library is thousands of stat calls for a number nobody
    asked for. It is there to answer "is this the folder I meant", so it
    says `12+` rather than pretending to be a total.
    """
    picked = set(folders_store.load())
    scanned = {str(f) for f in _music_folders()}
    entries = []
    try:
        children = sorted(folder.iterdir(), key=lambda c: c.name.lower())
    except OSError as exc:
        return {"error": f"cannot read {folder}: {exc}"}
    for child in children:
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            audio = sum(1 for f in child.iterdir()
                        if f.is_file()
                        and f.suffix.lower() in library.AUDIO_EXTENSIONS)
        except OSError:
            audio = 0
        relative = str(child.relative_to(MEDIA_DIR))
        entries.append({
            "name": child.name,
            "path": relative,
            "audio_files": audio,
            # `picked` is this folder exactly; `scanned` covers a parent
            # already being scanned, which is why a tick can be redundant.
            "picked": relative in picked,
            "scanned": str(child) in scanned,
        })
    return {"folders": entries}


def _browse_media(raw: str) -> Path | None:
    """A folder to open, found by walking real directory entries.

    Browsing turns something typed into a directory to list, which is the
    exact shape a path traversal is written for — and checking the string
    and hoping is the answer everybody writes. This matches each component
    against what `iterdir` actually reports instead, so the path that comes
    out is built from directory entries rather than from the request, and a
    name that is not there is simply not found. `_under_media` still runs
    first, because "that is not a path inside /media" and "there is no such
    folder" are different answers and the caller sends different statuses.
    """
    confined = _under_media(raw) if str(raw).strip() else MEDIA_DIR
    if confined is None:
        return None
    folder = MEDIA_DIR
    for wanted in confined.relative_to(MEDIA_DIR).parts:
        try:
            match = next((child for child in folder.iterdir()
                          if child.is_dir() and child.name == wanted), None)
        except OSError:
            return None
        if match is None:
            return None
        folder = match
    return folder


async def h_media_tree(request: web.Request) -> web.Response:
    """Browse /media so folders can be picked instead of typed.

    The filesystem, not Home Assistant's media browser: this list has to be
    folders BRight can *read* (the analyzer opens the files), and /media is
    exactly the set it can. What Core will serve from them is a different
    question, and `/api/playback/check` is the one that asks it.
    """
    raw = request.query.get("path", "")
    if raw and _under_media(raw) is None:
        return web.json_response({"error": "folder must live under /media"},
                                 status=400)
    folder = await asyncio.to_thread(_browse_media, raw)
    if folder is None:
        return web.json_response({"error": "no such folder under /media"},
                                 status=404)
    listing = await asyncio.to_thread(_folder_listing, folder)
    if listing.get("error"):
        return web.json_response(listing, status=500)
    here = "" if folder == MEDIA_DIR else str(folder.relative_to(MEDIA_DIR))
    parent = None
    if here:
        parent = str(Path(here).parent) if str(Path(here).parent) != "." else ""
    return web.json_response({
        "path": here,
        "parent": parent,
        "root": str(MEDIA_DIR),
        "folders": listing["folders"],
        "scanning": [str(f) for f in _music_folders()],
    })


async def h_media_folder(request: web.Request) -> web.Response:
    """Tick or untick a folder for scanning."""
    body = await _json_body(request)
    raw = str(body.get("path", "") or "")
    confined = _under_media(raw)
    if confined is None or confined == MEDIA_DIR:
        return web.json_response(
            {"error": "pick a folder inside /media"}, status=400)
    # Found by walking, not by trusting: what gets stored is a path built
    # from directory entries, and a folder that is not there cannot be
    # ticked in the first place.
    folder = await asyncio.to_thread(_browse_media, raw)
    if folder is None or folder == MEDIA_DIR:
        return web.json_response(
            {"error": f"no such folder under /media: {raw}"}, status=404)
    relative = str(folder.relative_to(MEDIA_DIR))
    try:
        if body.get("add"):
            folders_store.add(relative)
        else:
            folders_store.remove(relative)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    return web.json_response({"scanning": [str(f) for f in _music_folders()],
                              "picked": folders_store.load()})


async def h_library(request: web.Request) -> web.Response:
    folders = _music_folders()
    tracks = await asyncio.to_thread(library.scan_all, folders)
    return web.json_response({
        # `folder`/`exists` describe the main folder and stay for a panel
        # served before this update; `folders` is what the page renders.
        "folder": str(folders[0]),
        "exists": folders[0].is_dir(),
        "folders": [{"path": str(f), "exists": f.is_dir()} for f in folders],
        "tracks": tracks,
    })


async def h_library_analyze(request: web.Request) -> web.Response:
    body = await _json_body(request)
    force = bool(body.get("force"))
    folders = _music_folders()
    present = [f for f in folders if f.is_dir()]
    if not present:
        missing = ", ".join(str(f) for f in folders)
        return web.json_response(
            {"error": f"none of these folders exist: {missing} — put music in "
                      "one of them, or point the music_folder option (and "
                      "additional_music_folders) somewhere else"},
            status=404)
    job = jobs.start(
        "analyze-folder",
        lambda report: pipeline.analyze_folders(present, progress=report,
                                                force=force))
    status = 409 if job.get("already") else 202
    return web.json_response({"job": job["id"]}, status=status)


async def h_track_analysis(request: web.Request) -> web.Response:
    hash_hex = request.match_info["hash"]
    try:
        analysis = await asyncio.to_thread(library.load_analysis, hash_hex)
    except ValueError:
        return web.json_response({"error": "not a track hash"}, status=400)
    if analysis is None:
        return web.json_response({"error": "not analyzed yet"}, status=404)
    return web.json_response(analysis)


# ---------------------------------------------------------------------------
# The light map — the director's cast list
# ---------------------------------------------------------------------------
async def h_map(request: web.Request) -> web.Response:
    data = light_map.load()
    reachable = set(ENGINE.devices)
    for fixture in data["fixtures"]:
        if fixture.get("kind") == "lifx":
            fixture["reachable"] = fixture.get("serial") in reachable
    # The zones in use ride down with the map. They are not a stored list —
    # a zone exists exactly as long as a light is in it — so this is derived
    # on every read rather than kept, which is what stops a renamed-away zone
    # lingering in a picker forever.
    return web.json_response({**data, "roles": list(light_map.ROLES),
                              "zones": room.zones(data["fixtures"])})


async def h_map_upsert(request: web.Request) -> web.Response:
    body = await _json_body(request)
    try:
        fixture = light_map.upsert(body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"fixture": fixture})


async def h_map_remove(request: web.Request) -> web.Response:
    if light_map.remove(request.match_info["fixture_id"]):
        return web.json_response({"ok": True})
    return web.json_response({"error": "no such fixture"}, status=404)


async def h_map_import_lifx(request: web.Request) -> web.Response:
    added = light_map.merge_lifx(ENGINE.devices)
    return web.json_response({"added": added})


async def h_map_candidates(request: web.Request) -> web.Response:
    """Discovered bulbs that are not on the map yet.

    "Add discovered bulbs" adds every one of them at once, which is the
    right button for a first run and the wrong one after that: it drops
    six lamps on the middle of the floor plan named after their serials.
    This is what the picker reads — one bulb at a time, with a role and a
    zone chosen as it goes on.
    """
    known = {f.get("serial") for f in light_map.load()["fixtures"]
             if f.get("kind") == "lifx"}
    candidates = [
        {"serial": serial,
         "label": device.get("label") or serial,
         "ip": device.get("ip"),
         "rtt": device.get("rtt")}
        for serial, device in sorted(ENGINE.devices.items())
        if serial not in known
    ]
    return web.json_response({"candidates": candidates,
                             "discovered": len(ENGINE.devices),
                             "roles": list(light_map.ROLES)})


async def h_map_add_lifx(request: web.Request) -> web.Response:
    """Put one discovered bulb on the map, where the picker chose."""
    body = await _json_body(request)
    serial = str(body.get("serial", "")).lower()
    device = ENGINE.devices.get(serial)
    if device is None:
        return web.json_response(
            {"error": "that bulb has not been discovered — run Lab "
                      "discovery first"}, status=404)
    try:
        fixture = light_map.upsert({
            "kind": "lifx",
            "serial": serial,
            "label": str(body.get("label") or device.get("label") or serial),
            "role": body.get("role", "lamp"),
            "zone": body.get("zone", ""),
            "x": _number(body, "x", 0.5, 0.0, 1.0),
            "y": _number(body, "y", 0.5, 0.0, 1.0),
        })
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"fixture": fixture})


# ---------------------------------------------------------------------------
# Effects — the builder, its preview, and the presets it saves
# ---------------------------------------------------------------------------
def _map_fixtures() -> list[dict]:
    """Every fixture on the map, annotated with whether it can be reached.

    The builder works on the map, not on what answered a broadcast three
    minutes ago: an effect is designed for a room, and a bulb being off
    right now is not a reason to leave it out of the design. Reachability
    rides along so the preview can say which dots are hypothetical.
    """
    devices = ENGINE.devices
    out = []
    for fixture in light_map.load()["fixtures"]:
        if fixture.get("kind") == "lifx":
            device = devices.get(fixture.get("serial", ""))
            out.append({**fixture, "reachable": device is not None,
                        "rtt": (device or {}).get("rtt")})
        else:
            out.append({**fixture, "reachable": True})
    return out


def _preview_grid(body: dict) -> fx.Grid:
    """A beat grid from a BPM, because the bench has no track.

    Every effect that steps does so on beats, and a preview that ran on
    wall-clock seconds would be a preview of something the show never
    does. The BPM box in the builder is that grid.
    """
    bpm = _number(body, "bpm", 120, 30, 300)
    duration = _number(body, "duration_s", 12, 2, 60)
    beat_s = 60.0 / bpm
    beats = [round(i * beat_s, 4) for i in range(int(duration / beat_s) + 2)]
    return fx.Grid(beats, beats[::4], bpm)


def _preview_palette(body: dict) -> list:
    palette = body.get("palette")
    cleaned = []
    if isinstance(palette, list):
        for pair in palette:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                try:
                    cleaned.append([float(pair[0]) % 360.0,
                                    min(1.0, max(0.0, float(pair[1])))])
                except (TypeError, ValueError):
                    continue
    if cleaned:
        return cleaned
    name = str(body.get("palette_name", "") or "")
    for entry_name, entry in director_palettes.PALETTES:
        if entry_name == name:
            return [list(pair) for pair in entry]
    return [list(pair) for pair in director_palettes.PALETTES[3][1]]


def _effects_from(body: dict) -> list[dict]:
    raw = body.get("effects")
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ValueError("send an effect (or a list of them) to preview")
    return raw[:24]


async def h_effects_catalog(request: web.Request) -> web.Response:
    """Everything the builder needs to draw itself, in one read."""
    fixtures = _map_fixtures()
    zones = room.zones(fixtures)
    return web.json_response({
        "catalog": fx.catalog_payload(),
        "orders": list(fx.ORDERS),
        "default_order": fx.DEFAULT_ORDER,
        "default_align": fx.DEFAULT_ALIGN,
        "alignments": list(fx.ALIGNMENTS),
        "shapes": list(fx.SHAPES),
        "roles": list(light_map.ROLES),
        "zones": zones,
        "fixtures": fixtures,
        "palettes": [{"name": name, "colours": [list(p) for p in colours]}
                     for name, colours in director_palettes.PALETTES],
        "presets": effect_presets.load(),
    })


async def h_effect_describe(request: web.Request) -> web.Response:
    """A sentence becomes one effect, in the builder, unsaved.

    It lands in the form rather than in a file on purpose: an effect you
    have not looked at is not an effect you want, and the preview is one
    press away. Nothing here writes.
    """
    body = await _json_body(request)
    description = str(body.get("description", "") or "")
    fixtures = _map_fixtures()
    if not fixtures:
        return web.json_response(
            {"error": "no lights on the map yet — the Light Map tab is where "
                      "an effect gets something to drive"}, status=409)
    if not claude_director.available():
        return web.json_response(
            {"error": "writing an effect from a description runs through "
                      "brAIn's task surface, and brAIn is not installed on "
                      "this Home Assistant. Everything else in this tab "
                      "works without it."}, status=409)
    try:
        effect = await asyncio.to_thread(
            claude_director.write_effect, description, fixtures)
    except (ValueError, RuntimeError) as exc:
        # 409 and not 500: nothing is broken — Claude was asked and either
        # could not be reached or wrote something unusable, and the sentence
        # says which.
        return web.json_response({"error": str(exc)}, status=409)
    return web.json_response({"effect": effect})


async def h_effect_invent(request: web.Request) -> web.Response:
    """Effects for this room, with nothing typed in.

    The other half of `describe`: knowing what to ask for assumes you
    already know what is possible in your own room, which is the thing
    somebody with a new light map most reliably does not. Same room
    description, same catalog, same validator — these are ordinary effects
    that arrive unsaved, and each carries one sentence about why it suits
    the room, which is the part that makes the list worth reading rather
    than six names to click through.
    """
    body = await _json_body(request)
    try:
        count = int(body.get("count", 4))
    except (TypeError, ValueError):
        count = 4
    fixtures = _map_fixtures()
    if not fixtures:
        return web.json_response(
            {"error": "no lights on the map yet — the Light Map tab is where "
                      "an effect gets something to drive"}, status=409)
    if not claude_director.available():
        return web.json_response(
            {"error": "inventing effects runs through brAIn's task surface, "
                      "and brAIn is not installed on this Home Assistant. "
                      "Everything else in this tab works without it."},
            status=409)
    try:
        effects = await asyncio.to_thread(
            claude_director.invent_effects, fixtures, count)
    except (ValueError, RuntimeError) as exc:
        return web.json_response({"error": str(exc)}, status=409)
    return web.json_response({"effects": effects})


async def h_effects_preview(request: web.Request) -> web.Response:
    """One or more effects, rendered on the bench.

    Answers with frames (what the panel animates), the cue figures (what
    it would cost on the wire) and the rate verdict — all from the same
    render, so the picture and the packets cannot disagree.
    """
    body = await _json_body(request)
    try:
        effects = _effects_from(body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    fixtures = _map_fixtures()
    if not fixtures:
        return web.json_response(
            {"error": "the light map is empty — add some lights first, "
                      "because an effect is a thing lights do"}, status=409)
    duration = _number(body, "duration_s", 12, 2, 60)
    grid = _preview_grid(body)
    palette = _preview_palette(body)
    try:
        rendered = await asyncio.to_thread(
            compiler.compile_preview, effects, fixtures, grid=grid,
            duration_s=duration, palette=palette,
            base_brightness=_number(body, "base_brightness", 0.35, 0, 1),
            source=ENGINE.source)
    except fx.EffectError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    frames = await asyncio.to_thread(
        fx.simulate, rendered["actions"], fixtures, duration_s=duration,
        fps=int(_number(body, "fps", 15, 4, 30)))
    return web.json_response({
        "preview": frames,
        "effects": rendered["effects"],
        "cues": len(rendered["cues"]),
        "peak_per_device_hz": rendered["peak_per_device_hz"],
        "over_budget": rendered["over_budget"],
        "budget_hz": compiler.MAX_RATE_HZ,
        "busiest_device": rendered["busiest_device"],
    })


async def h_effects_live(request: web.Request) -> web.Response:
    """Run the effect on the actual bulbs, with no music behind it."""
    body = await _json_body(request)
    try:
        effects = _effects_from(body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    fixtures = [f for f in _map_fixtures() if f.get("reachable")]
    if not fixtures:
        return web.json_response(
            {"error": "none of the mapped lights are reachable — run Lab "
                      "discovery, or preview it on screen instead"},
            status=409)
    duration = _number(body, "duration_s", 12, 2, 60)
    try:
        rendered = await asyncio.to_thread(
            compiler.compile_preview, effects, fixtures,
            grid=_preview_grid(body), duration_s=duration,
            palette=_preview_palette(body),
            base_brightness=_number(body, "base_brightness", 0.35, 0, 1),
            source=ENGINE.source)
    except fx.EffectError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    if rendered["over_budget"]:
        return web.json_response(
            {"error": f"that would send {rendered['peak_per_device_hz']:.0f} "
                      f"messages a second to one bulb — the ceiling is "
                      f"{compiler.MAX_RATE_HZ:.0f}. Slow it down or narrow "
                      f"what it runs on."}, status=422)
    label = str(body.get("label") or "effect preview")[:60]
    result = await _conductor().run_cues(
        rendered["cues"], duration_s=duration + 1.0, label=label)
    return web.json_response(result, status=200 if result.get("ok") else 409)


async def h_effect_presets(request: web.Request) -> web.Response:
    return web.json_response({"presets": effect_presets.load()})


async def h_effect_preset_save(request: web.Request) -> web.Response:
    body = await _json_body(request)
    try:
        effect = fx.clean_effect(body.get("effect"))
        preset = effect_presets.save(body.get("name", ""), effect,
                                     body.get("note", ""))
    except (ValueError, fx.EffectError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"preset": preset,
                              "presets": effect_presets.load()})


async def h_effect_preset_remove(request: web.Request) -> web.Response:
    if effect_presets.remove(request.match_info["name"]):
        return web.json_response({"ok": True, "presets": effect_presets.load()})
    return web.json_response({"error": "no preset by that name"}, status=404)


# ---------------------------------------------------------------------------
# Parties — a saved evening, startable by name
# ---------------------------------------------------------------------------
async def h_parties(request: web.Request) -> web.Response:
    return web.json_response({"parties": parties_store.load()})


async def h_party_save(request: web.Request) -> web.Response:
    body = await _json_body(request)
    try:
        party = parties_store.save(body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    _publish_parties()
    return web.json_response({"party": party,
                              "parties": parties_store.load()})


async def h_party_remove(request: web.Request) -> web.Response:
    if parties_store.remove(request.match_info["name"]):
        _publish_parties()
        return web.json_response({"ok": True,
                                  "parties": parties_store.load()})
    return web.json_response({"error": "no party by that name"}, status=404)


async def h_party_list_for_bridge(request: web.Request) -> web.Response:
    """The same list, over POST, because the bridge only speaks POST."""
    return web.json_response({"ok": True,
                              "parties": [p["name"] for p in parties_store.load()]})


def _publish_parties() -> None:
    """Mirror the party names where Home Assistant can see them.

    /data is invisible to Core, and "which parties exist" is a question a
    dashboard asks. The mirror is derived and never read back — the store
    under /data is the record.
    """
    target = SHARED_DIR / "parties.json"
    if not SHARED_DIR.parent.is_dir():
        return
    try:
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(
            target, {"parties": [p["name"] for p in parties_store.load()],
                     "updated_at": time.time()}, indent=2)
    except OSError as exc:
        log.warning("could not mirror the party list: %s", exc)


# ---------------------------------------------------------------------------
# Compile — script tier + THE compiler, per track
# ---------------------------------------------------------------------------
async def h_show_compile(request: web.Request) -> web.Response:
    body = await _json_body(request)
    hash_hex = str(body.get("track_hash", ""))
    # `director` overrides the option for THIS compile, which is what makes
    # "rewrite this one with Claude" a button rather than a settings trip.
    # The option stays the default, because it is the answer for every show
    # nobody has an opinion about.
    asked = str(body.get("director", "") or "").strip().lower()
    if asked and asked not in ("auto", "claude", "algorithmic"):
        return web.json_response(
            {"error": f"director must be auto, claude or algorithmic "
                      f"(not {asked!r})"}, status=400)
    mode = asked or _options_from_env()["director_mode"]
    vibe = str(body.get("vibe", "") or "").strip()[:200] or None
    writer = None
    if mode in ("auto", "claude") and claude_director.available():
        writer = claude_director.write_script
    elif mode == "claude":
        return web.json_response(
            {"error": "director_mode is 'claude' but brAIn is not installed "
                      "— the Claude director runs through brAIn's task "
                      "surface. Install brAIn or switch to 'auto'."},
            status=409)
    try:
        show = await asyncio.to_thread(
            director_build.build_show, hash_hex, ENGINE.devices,
            ENGINE.source, mode, writer, vibe)
    except CompileError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    return web.json_response({
        "tier": show["tier"],
        "palette": show.get("palette_name"),
        "stats": show["stats"],
        # The whole point of the override: a caller that asked for Claude
        # has to be told whether it got Claude, in the same answer. A show
        # tagged `algorithmic` with no reason beside it is how a week of
        # silent fallbacks went unnoticed.
        "director": show.get("director"),
    })


def _waveform_payload(hash_hex: str) -> tuple[int, dict]:
    """The song as something to look at, with its landmarks.

    Everything a person needs to see WHEN things happen: the shape of the
    audio, and the beats, sections and drops the show is hung off. They
    travel together because they are drawn together — two requests would
    let the picture and the marks disagree about which track they are of.

    An analysis made before envelopes existed has none, so one is computed
    from the file and folded back in rather than making somebody re-analyse
    a library to get a picture. That costs an ffmpeg pass, once, and only
    for old analyses.
    """
    if not library.is_track_hash(hash_hex):
        return 400, {"error": "not a track hash"}
    analysis = library.load_analysis(hash_hex)
    if analysis is None:
        return 404, {"error": "not analyzed yet — the Library tab analyses a "
                              "track before there is anything to show"}
    envelope = analysis.get("envelope")
    if not envelope:
        path = Path(analysis.get("file") or "")
        if not path.is_file():
            return 409, {"error": f"this track was analysed before BRight drew "
                                  f"waveforms, and the file it was analysed "
                                  f"from ({path or 'unknown'}) is not there "
                                  f"any more — re-analyse it from the Library "
                                  f"tab"}
        try:
            envelope = features.envelope(decode.pcm(path))
        except (OSError, ValueError) as exc:
            return 422, {"error": f"could not read the audio: "
                                  f"{playback_check.flat(exc)}"}
        analysis["envelope"] = envelope
        library.save_analysis(hash_hex, analysis)
    tags = analysis.get("tags") or {}
    return 200, {
        "envelope": envelope,
        "duration_s": library.duration_of(analysis),
        "bpm": analysis.get("bpm"),
        "title": tags.get("title") or "",
        "artist": tags.get("artist") or "",
        # Downbeats rather than every beat: at four minutes a beat every
        # half second is 480 lines on a 900px canvas, which is a grey wash
        # and not a grid. The bar lines are what a person can actually
        # count against.
        "downbeats": analysis.get("downbeats") or [],
        "sections": analysis.get("sections") or [],
        "drops": analysis.get("drops") or [],
    }


async def h_track_waveform(request: web.Request) -> web.Response:
    hash_hex = request.match_info["hash"]
    status, payload = await asyncio.to_thread(_waveform_payload, hash_hex)
    return web.json_response(payload, status=status)


async def h_show_prompt(request: web.Request) -> web.Response:
    """Exactly what Claude is handed for this track.

    Built by the same function that builds it for a real run rather than
    described, because a page describing the prompt is a second copy of it
    and would start lying the first time the real one changed. Nothing here
    runs Claude or costs anything — it is the brief, readable before you
    decide to spend a couple of minutes on the answer, and it is the
    fastest way to see whether the director actually knows about the room
    you drew.
    """
    hash_hex = request.match_info["hash"]
    try:
        analysis = await asyncio.to_thread(library.load_analysis, hash_hex)
    except ValueError:
        return web.json_response({"error": "not a track hash"}, status=400)
    if analysis is None:
        return web.json_response(
            {"error": "not analyzed yet — the Library tab analyses a track "
                      "before there is anything to brief Claude about"},
            status=404)
    fixtures = director_build.fixtures_for_show(ENGINE.devices)
    if not fixtures:
        return web.json_response(
            {"error": "no reachable fixtures — run Lab discovery, then place "
                      "your lights on the Light Map"}, status=409)
    vibe = str(request.query.get("vibe", "") or "").strip()[:200] or None
    prompt = await asyncio.to_thread(
        claude_director.digest, analysis, fixtures, vibe)
    return web.json_response({
        "prompt": prompt,
        "chars": len(prompt),
        "fixtures": len(fixtures),
        "available": claude_director.available(),
    })


async def h_show_director(request: web.Request) -> web.Response:
    """How the show on disk came to be written — read back later.

    The compile response carries this too, but a panel showing a show it
    did not just compile has no other way to ask, and "was this one
    actually Claude's?" is the question the Shows list is most often
    being scanned for.
    """
    hash_hex = request.match_info["hash"]
    try:
        report = await asyncio.to_thread(director_build.load_report, hash_hex)
    except ValueError:
        return web.json_response({"error": "not a track hash"}, status=400)
    if report is None:
        return web.json_response(
            {"error": "no record of how this show was written — it predates "
                      "the record, or it has not been compiled yet"},
            status=404)
    return web.json_response(report)


# ---------------------------------------------------------------------------
# The show script — the file the whole show is, opened for editing
# ---------------------------------------------------------------------------
def _script_payload(hash_hex: str) -> tuple[int, dict]:
    analysis = library.load_analysis(hash_hex)
    if analysis is None:
        return 404, {"error": "track not analyzed — run the Library tab first"}
    script = None
    try:
        script = json.loads(library.script_path(hash_hex).read_text())
    except (OSError, ValueError):
        # No script yet (never compiled) or an unreadable one. Either way
        # the honest answer is "nothing to edit yet", not an error about
        # a file the person has never heard of.
        pass
    show = library.load_show(hash_hex)
    mirror = library.find_mirror(hash_hex)
    return 200, {
        "track_hash": hash_hex,
        "title": (analysis.get("tags") or {}).get("title") or hash_hex[:8],
        "bpm": analysis.get("bpm"),
        "duration_s": library.duration_of(analysis),
        "script": script,
        "compiled": bool(show and show.get("cues")),
        "stats": (show or {}).get("stats"),
        "effects": (show or {}).get("effects"),
        "file": str(mirror) if mirror else None,
    }


async def h_show_script(request: web.Request) -> web.Response:
    try:
        library.analysis_path(request.match_info["hash"])
    except ValueError:
        return web.json_response({"error": "not a track hash"}, status=400)
    status, payload = await asyncio.to_thread(
        _script_payload, request.match_info["hash"])
    return web.json_response(payload, status=status)


def _compile_script(hash_hex: str, script: dict) -> dict:
    analysis = library.load_analysis(hash_hex)
    if analysis is None:
        raise ValueError("track not analyzed — run the Library tab first")
    problems = choreographer.validate_script(script)
    if problems:
        raise ValueError("this script will not run: " + "; ".join(problems[:6]))
    fixtures = director_build.fixtures_for_show(ENGINE.devices)
    if not fixtures:
        raise ValueError("no reachable fixtures — run Lab discovery, then "
                         "place your lights on the Light Map")
    script = {**script, "track_hash": hash_hex,
              "tier": script.get("tier") or "edited"}
    return director_build.compile_and_save(hash_hex, script, analysis,
                                           fixtures, ENGINE.source)


async def h_show_script_save(request: web.Request) -> web.Response:
    """Take an edited script, compile it, keep it.

    The same door the director's own output goes through — validator,
    compiler, rate budget, mirror — because "automatic but editable" is
    only true if the edited version is not a second-class show.
    """
    hash_hex = request.match_info["hash"]
    body = await _json_body(request)
    script = body.get("script")
    if isinstance(script, str):
        try:
            script = json.loads(script)
        except ValueError as exc:
            return web.json_response(
                {"error": f"that is not valid JSON — {exc}"}, status=400)
    if not isinstance(script, dict):
        return web.json_response({"error": "send the script as an object"},
                                 status=400)
    try:
        show = await asyncio.to_thread(_compile_script, hash_hex, script)
    except CompileError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    status, payload = await asyncio.to_thread(_script_payload, hash_hex)
    return web.json_response({**payload, "stats": show["stats"]})


async def h_show_script_import(request: web.Request) -> web.Response:
    """Read the hand-edited file back off the shared volume and compile it."""
    hash_hex = request.match_info["hash"]
    try:
        script = await asyncio.to_thread(library.read_mirrored_script, hash_hex)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    if script is None:
        return web.json_response(
            {"error": "there is no file to read yet — compile the show once "
                      "and it appears in /config/.bright/shows/"}, status=404)
    try:
        show = await asyncio.to_thread(_compile_script, hash_hex, script)
    except CompileError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    status, payload = await asyncio.to_thread(_script_payload, hash_hex)
    return web.json_response({**payload, "stats": show["stats"],
                              "imported": True})


async def h_show_revise(request: web.Request) -> web.Response:
    """Notes on a show somebody watched, applied by the Claude director.

    The request waits for the whole revision — same posture as compile,
    which already lives with a minutes-long director run — and nothing is
    written unless the revised script validates and compiles, so a failed
    revision costs an error message and never the show.
    """
    hash_hex = request.match_info["hash"]
    body = await _json_body(request)
    feedback = str(body.get("feedback", "") or "").strip()
    if not feedback:
        return web.json_response({"error": "say what you want changed first"},
                                 status=400)
    if not claude_director.available():
        return web.json_response(
            {"error": "brAIn is not installed — revising a show with Claude "
                      "runs through brAIn's task surface"}, status=409)
    try:
        show = await asyncio.to_thread(
            director_build.revise_show, hash_hex, ENGINE.devices,
            ENGINE.source, feedback, claude_director.revise_script)
    except CompileError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except RuntimeError as exc:
        # brAIn's side of it: not installed after all, timed out, task
        # failed. The show on disk is untouched, and the message says so.
        return web.json_response(
            {"error": f"{exc} — the show is unchanged"}, status=502)
    status, payload = await asyncio.to_thread(_script_payload, hash_hex)
    return web.json_response({**payload, "stats": show["stats"],
                              "director": show.get("director"),
                              "revised": True})


def _preview_inputs(hash_hex: str, body: dict) -> tuple[dict, list[dict], dict]:
    """The script, the cast and the song a preview is about.

    The script comes from the REQUEST when the editor sent one and from
    disk otherwise, and that is the whole reason the editor can be live:
    what you are looking at is the show as currently edited, not the show
    as last saved. Nothing here writes anything.

    Raises ValueError with a person-readable message.
    """
    analysis = library.load_analysis(hash_hex)
    if analysis is None:
        raise ValueError("track not analyzed — run the Library tab first")
    script = body.get("script")
    if isinstance(script, str):
        try:
            script = json.loads(script)
        except ValueError as exc:
            raise ValueError(f"that script is not valid JSON: {exc}") from None
    if not isinstance(script, dict):
        try:
            script = json.loads(library.script_path(hash_hex).read_text())
        except (OSError, ValueError):
            raise ValueError("no show for this track yet — compile one "
                             "first, then it can be edited") from None
    fixtures = director_build.fixtures_for_show(ENGINE.devices)
    if not fixtures:
        raise ValueError("no reachable fixtures — run Lab discovery, then "
                         "place your lights on the Light Map")
    return script, fixtures, analysis


async def h_show_preview(request: web.Request) -> web.Response:
    """The room at an instant, and for a few seconds either side of it.

    This is the scrub path, so it is the one that has to stay cheap: a
    window of frames, not the whole show, and no writes of any kind. An
    unfinished edit is previewed rather than refused — the compiler's own
    refusals (a flooded bulb, an impossible selection) still come back
    here, which is how you find out you have asked for too much while you
    are still typing rather than at save.
    """
    hash_hex = request.match_info["hash"]
    body = await _json_body(request)
    start_s = _number(body, "start_s", 0.0, 0.0, 100000.0)
    span_s = _number(body, "span_s", director_preview.WINDOW_S, 0.5, 60.0)

    def _run() -> dict:
        script, fixtures, analysis = _preview_inputs(hash_hex, body)
        return director_preview.window(script, fixtures, analysis,
                                       start_s=start_s, span_s=span_s)

    try:
        return web.json_response(await asyncio.to_thread(_run))
    except (ValueError, compiler.CompileError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def h_show_outline(request: web.Request) -> web.Response:
    """The whole show at a glance: the strip, and the furniture behind it.

    Asked for once per edit rather than once per scrub, which is why it
    can afford to simulate the entire song.
    """
    hash_hex = request.match_info["hash"]
    body = await _json_body(request)
    columns = int(_number(body, "columns", director_preview.OVERVIEW_COLUMNS,
                          24, 1200))

    def _run() -> dict:
        script, fixtures, analysis = _preview_inputs(hash_hex, body)
        return {
            **director_preview.overview(script, fixtures, analysis,
                                        columns=columns),
            "timeline": director_preview.timeline(script, analysis),
        }

    try:
        return web.json_response(await asyncio.to_thread(_run))
    except (ValueError, compiler.CompileError) as exc:
        return web.json_response({"error": str(exc)}, status=400)


async def h_show_cues(request: web.Request) -> web.Response:
    """The compiled timeline, readable — what actually goes on the wire.

    Without the packets: a base64 datagram per row is most of the file
    and none of the meaning. What a person needs from a cue list is when,
    which light, and which effect asked for it.
    """
    hash_hex = request.match_info["hash"]
    try:
        show = await asyncio.to_thread(library.load_show, hash_hex)
    except ValueError:
        return web.json_response({"error": "not a track hash"}, status=400)
    if not show:
        return web.json_response({"error": "not compiled yet"}, status=404)
    limit = int(_number(dict(request.query), "limit", 500, 1, 5000))
    offset = int(_number(dict(request.query), "offset", 0, 0, 100000))
    cues = show.get("cues") or []
    rows = [{"t": c["t"], "ch": c["ch"], "lead_ms": c.get("lead_ms"),
             "target": c.get("serial") or (c.get("data") or {}).get("entity_id"),
             "desc": c.get("desc")}
            for c in cues[offset:offset + limit]]
    return web.json_response({"total": len(cues), "offset": offset,
                              "cues": rows, "stats": show.get("stats"),
                              "effects": show.get("effects")})


# ---------------------------------------------------------------------------
# Shows — compiled choreography when it exists, the metronome otherwise
# ---------------------------------------------------------------------------
CONDUCTOR: conductor_mod.Conductor | None = None


def _conductor() -> conductor_mod.Conductor:
    global CONDUCTOR
    if CONDUCTOR is None:
        CONDUCTOR = conductor_mod.Conductor(ENGINE)
    return CONDUCTOR


async def _start_show_for(hash_hex: str, media_player: str,
                          *, metronome: bool = False,
                          serials: list[str] | None = None
                          ) -> tuple[int, dict]:
    # A bulb selection reaches the METRONOME only: its cues are built from
    # the device list, so filtering the list is filtering the show. A
    # compiled show's cues are already built; parties filter those at
    # dispatch (filter_cues), which is a different door for a different
    # caller.
    devices = ENGINE.devices
    if metronome and serials:
        wanted = set(serials)
        devices = {s: d for s, d in devices.items() if s in wanted}
        if not devices:
            return 409, {"error": "none of the selected bulbs are known — "
                                  "run Lab discovery first"}
    try:
        show = await asyncio.to_thread(
            lambda: conductor_mod.load_show_for_track(
                hash_hex, devices, ENGINE.source, metronome=metronome))
    except ValueError:
        return 400, {"error": "not a track hash"}
    if show is None:
        return 404, {"error": "track not analyzed — run the Library tab first"}
    if not show["cues"]:
        return 409, {"error": "no LIFX bulbs known — run Lab discovery first"}
    if show["media_content_id"] is None:
        return 409, {"error": "track is outside /media, so the player "
                              "cannot be handed it"}
    result = await _conductor().start(
        show["cues"], media_player=media_player,
        media_content_id=show["media_content_id"], title=show["title"],
        duration_s=show["duration_s"],
        track_hash=show.get("track_hash", ""))
    return (200 if result.get("ok") else 409), result


async def h_show_start(request: web.Request) -> web.Response:
    body = await _json_body(request)
    media_player = _entity(body)
    if media_player is None:
        media_player = calibration_store.best_entity()
    if media_player is None:
        return web.json_response(
            {"error": "no media_player given and none calibrated yet"},
            status=400)
    track = str(body.get("track", ""))
    hash_hex = str(body.get("track_hash", ""))
    if track and not hash_hex:
        # The wire names a file we will open (to hash it) and hand to the
        # media player — it may only ever be a file under /media, and that
        # is one rule with one implementation (`_under_media`), not a second
        # copy of the string arithmetic to keep in step with the first.
        path = _under_media(track)
        if path is None or path == MEDIA_DIR:
            return web.json_response({"error": "track must live under /media"},
                                     status=400)
        if not path.is_file():
            return web.json_response({"error": f"no such track: {path}"},
                                     status=404)
        hash_hex = await asyncio.to_thread(library.track_hash, path)
    if not hash_hex:
        return web.json_response({"error": "track or track_hash required"},
                                 status=400)
    # One handler serves /start_show and /metronome — everything about
    # them is identical except which cues play, so the path is the flag.
    # The sync proof MUST get the metronome even when a compiled show
    # exists: it is a demo of the clock, not a way to start the evening.
    metronome = request.path.endswith("/metronome")
    serials = [str(x) for x in (body.get("serials") or [])
               if isinstance(x, str)]
    status, payload = await _start_show_for(hash_hex, media_player,
                                            metronome=metronome,
                                            serials=serials or None)
    return web.json_response(payload, status=status)


async def h_show_nudge(request: web.Request) -> web.Response:
    """Trim the running show's sync by ear, a few ms per press."""
    body = await _json_body(request)
    try:
        ms = float(body.get("ms", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "ms must be a number"}, status=400)
    if not ms:
        return web.json_response({"error": "ms must be non-zero"}, status=400)
    result = _conductor().nudge(ms)
    return web.json_response(result, status=200 if result.get("ok") else 409)


async def h_show_nudge_keep(request: web.Request) -> web.Response:
    result = await asyncio.to_thread(_conductor().keep_nudge)
    return web.json_response(result, status=200 if result.get("ok") else 409)


async def h_show_autosync(request: web.Request) -> web.Response:
    """The phone listened to the room; line the lights up with what it
    heard. The page has already mapped its record-start moment onto OUR
    clock (via /api/calibrate/ping), same contract as the calibration
    wizard — the arithmetic here never compares two different clocks."""
    body = await _json_body(request)
    try:
        record_start_ms = float(body["record_start_epoch_ms"])
        wav = base64.b64decode(str(body["wav_b64"]))
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "missing recording fields"},
                                 status=400)
    conductor = _conductor()
    state = conductor.state
    if not state.get("active") or not conductor.clock.anchored:
        return web.json_response(
            {"error": "nothing is playing to sync against"}, status=409)
    track_hash = str(state.get("track_hash") or "")
    analysis = await asyncio.to_thread(library.load_analysis, track_hash) \
        if track_hash else None
    if analysis is None:
        return web.json_response(
            {"error": "the running track has no analysis to match against"},
            status=409)
    track_file = Path(analysis.get("file") or "")
    if not track_file.is_file():
        return web.json_response(
            {"error": f"the file this track was analysed from "
                      f"({track_file or 'unknown'}) is not there any more — "
                      f"re-analyse it from the Library tab"}, status=409)
    # Where the show clock believed the room was when the phone started
    # listening: its position now, walked back by how long ago that was.
    expected_pos_s = conductor.clock.now() \
        - (time.time() * 1000.0 - record_start_ms) / 1000.0
    if expected_pos_s < -autosync.MARGIN_S:
        return web.json_response(
            {"error": "the track changed while the phone was listening — "
                      "try again"}, status=409)
    try:
        result = await asyncio.to_thread(
            autosync.measure, wav, track_file, expected_pos_s)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    if result["confidence"] < autosync.MIN_CONFIDENCE:
        return web.json_response(
            {"error": "could not match what it heard against the song — "
                      "move the phone closer to the speaker and try again",
             "confidence": result["confidence"]}, status=422)
    delta_ms = result["delta_s"] * 1000.0
    applied = conductor.apply_sync(delta_ms)
    if applied.get("error"):
        return web.json_response(applied, status=409)
    return web.json_response({"ok": True,
                              "delta_ms": round(delta_ms, 1),
                              "confidence": result["confidence"],
                              "nudge_ms": applied["nudge_ms"]})


async def h_party_skip(request: web.Request) -> web.Response:
    """Transport for a running party: next track (+1) or previous (-1)."""
    body = await _json_body(request)
    try:
        step = int(body.get("step", 1))
    except (TypeError, ValueError):
        return web.json_response({"error": "step must be 1 or -1"}, status=400)
    result = _conductor().skip(step)
    return web.json_response(result, status=200 if result.get("ok") else 409)


async def h_show_stop(request: web.Request) -> web.Response:
    """Stop, and put the room back — into a scene if one was asked for.

    A stop takes an optional `scene`, and a running party's own end scene
    is used when the caller names none. Restoring is right when the show
    interrupted an evening; a scene is right when the show *was* the
    evening and what comes next is bedtime.
    """
    body = await _json_body(request)
    scene = _entity(body, key="scene", domain="scene") if body.get("scene") \
        else None
    if body.get("scene") and scene is None:
        return web.json_response(
            {"error": "scene must be a scene entity id, like "
                      "scene.good_night"}, status=400)
    conductor = _conductor()
    if scene:
        conductor.set_end_scene(scene)
    result = await conductor.stop(restore=True)
    return web.json_response({**result, "scene": scene
                              or conductor.state.get("ended_with_scene")})


async def h_show_state(request: web.Request) -> web.Response:
    return web.json_response(_conductor().state)


async def h_show_party(request: web.Request) -> web.Response:
    """`bright.party_mode`, end to end: scan the folder, queue every
    analyzed track (shuffled), compile the next show while the current one
    plays, re-anchor per track."""
    body = await _json_body(request)
    # A named party is a saved set of these same answers, and anything
    # given explicitly still wins over it — an automation that says
    # "Saturday Night, but on the kitchen speaker" means that.
    party = None
    wanted = str(body.get("party", "") or "").strip()
    if wanted:
        party = parties_store.get(wanted)
        if party is None:
            known = ", ".join(p["name"] for p in parties_store.load()) or "none"
            return web.json_response(
                {"error": f"no party called {wanted!r} — saved parties: "
                          f"{known}"}, status=404)
        body = {**party, **{k: v for k, v in body.items() if v not in (None, "")}}

    media_player = _entity(body) or calibration_store.best_entity()
    if media_player is None:
        return web.json_response(
            {"error": "no media_player given and none calibrated yet — "
                      "run the Calibrate tab first"},
            status=400)
    end_scene = _entity(body, key="end_scene", domain="scene") \
        if body.get("end_scene") else None
    allow = set(body.get("fixtures") or []) or None
    folders = _music_folders()
    raw_folder = str(body.get("folder", "") or "")
    if raw_folder:
        # One folder was named for this party: it wins over the options, and
        # it has to be somewhere Home Assistant can serve from.
        chosen = _under_media(raw_folder)
        if chosen is None:
            return web.json_response({"error": "folder must live under /media"},
                                     status=400)
        folders = [chosen]
    vibe = str(body.get("vibe", "") or "")[:120]

    # A playlist beats the folder. It is a choice of exact songs in an
    # exact order, and merging it with "everything in the folder" would
    # un-choose them. Tracks that have lost their analysis since the list
    # was made are skipped and NAMED, not silently dropped — a playlist
    # that quietly shrinks is how one missing file becomes "the party
    # skipped my song and I don't know why".
    playlist = [str(t) for t in (body.get("tracks") or [])
                if isinstance(t, str)]
    skipped: list[str] = []
    if playlist:
        queue = []
        for hash_hex in playlist:
            analyzed = await asyncio.to_thread(library.load_analysis, hash_hex)
            if analyzed is None:
                skipped.append(hash_hex[:8])
            else:
                queue.append(hash_hex)
        if not queue:
            return web.json_response(
                {"error": "none of the playlist's tracks are analyzed any "
                          "more — re-analyze them from the Library tab"},
                status=409)
        # A playlist's order IS the point; shuffle only when asked, and
        # the saved party's own flag decides (default off for playlists —
        # you ordered the songs, so the order is the request).
        if body.get("shuffle", False):
            random.shuffle(queue)
    else:
        tracks = await asyncio.to_thread(library.scan_all, folders)
        queue = [t["hash"] for t in tracks if t["analyzed"]]
        if not queue:
            where = " or ".join(str(f) for f in folders)
            return web.json_response(
                {"error": f"no analyzed tracks in {where} — run the Library "
                          "tab first"},
                status=409)
        if body.get("shuffle", True):
            random.shuffle(queue)

    mode = _options_from_env()["director_mode"]
    preparer = None
    if mode in ("auto", "claude") and claude_director.available():
        def preparer(hash_hex: str) -> None:
            if library.load_show(hash_hex) is not None:
                return  # already choreographed
            try:
                director_build.build_show(
                    hash_hex, ENGINE.devices, ENGINE.source, mode,
                    lambda a, f: claude_director.write_script(a, f, vibe=vibe))
            except Exception as exc:  # noqa: BLE001 — that track plays its floor show
                log.warning("party prepare failed for %s: %s", hash_hex[:8], exc)

    result = await _conductor().start_party(
        queue, media_player=media_player,
        loader=lambda h: conductor_mod.load_show_for_track(
            h, ENGINE.devices, ENGINE.source),
        preparer=preparer, name=(party or {}).get("name"),
        end_scene=end_scene, allow=allow)
    if skipped and result.get("ok"):
        result["skipped_tracks"] = skipped
    status = 200 if result.get("ok") else 409
    return web.json_response(result, status=status)


# ---------------------------------------------------------------------------
# Calibration — how long the speaker takes, measured, never configured
# ---------------------------------------------------------------------------
REFERENCE_WAV = MEDIA_DIR / "bright" / "calibration.wav"
# What media_player.play_media is handed for the file above (HA maps the
# /media mount to the local media source).
REFERENCE_RELATIVE = "bright/calibration.wav"


def reference_media_id() -> str:
    """The click track's media id, with whatever source id discovery has
    learned. A function and not a constant because the id is a fact about
    the user's configuration.yaml, and constants cannot be corrected."""
    return media_source.build(media_source.current_id(), REFERENCE_RELATIVE)

# The position-reliability check that runs while the reference plays,
# keyed by entity. In memory: it describes the run in progress.
_POSITION_CHECKS: dict[str, dict] = {}


def _ensure_reference() -> str | None:
    """None once the click track is on disk, or the sentence to send back.

    This is the failure that shipped. /media belongs to root on a Home
    Assistant install and this panel runs as the `bright` user, so
    `mkdir("/media/bright")` raised PermissionError, aiohttp turned that into
    a bare `500 Internal Server Error` with no body, and the wizard could
    only report `HTTP 500` — about a folder, in a message that never named
    it. run.sh creates the folder as root and hands it over now; if the
    write still cannot happen, this is what says so.
    """
    try:
        reference.ensure(REFERENCE_WAV)
    except OSError as exc:
        log.error("cannot write the click track to %s: %s", REFERENCE_WAV, exc)
        return (f"could not write the click track to {REFERENCE_WAV}: "
                f"{exc.strerror or exc}. BRight creates that folder at startup "
                f"and writes it as the 'bright' user — restart the add-on, and "
                f"check that Home Assistant's media folder exists.")
    return None


async def h_cal_reference(request: web.Request) -> web.Response:
    error = await asyncio.to_thread(_ensure_reference)
    if error:
        return web.json_response({"error": error}, status=500)
    # The file is on disk, so now it can be used as the probe that finds
    # which of Core's media sources actually is our /media. This is the
    # first thing the calibration wizard does, which makes it the right
    # place to learn the id everything else will build with.
    await media_source.ensure()
    return web.json_response({
        **reference.describe(),
        "media_content_id": reference_media_id(),
        "media_source": media_source.state(),
    })


async def h_playback_check(request: web.Request) -> web.Response:
    """Why nothing is playing, one link of the chain at a time.

    Defaults to the click track because that is the file BRight controls
    end to end — if this cannot play, nothing else was ever going to, and
    the answer is about the house rather than about the music.
    """
    body = await _json_body(request)
    entity_id = _entity(body)
    if entity_id is None:
        return web.json_response({"error": "media_player entity required"},
                                 status=400)

    media_id = str(body.get("media_content_id", "") or "")
    path = None
    expected = None
    if not media_id:
        error = await asyncio.to_thread(_ensure_reference)
        if error:
            return web.json_response({"error": error}, status=500)
        await media_source.ensure()
        media_id = reference_media_id()
        path = REFERENCE_WAV
        expected = reference.expected_size()
    # A caller-supplied media id is deliberately NOT turned into a path.
    # The file step exists for the click track, whose path is ours; for
    # anything else Home Assistant's own resolve step answers "is the file
    # there" better than a stat does, and a media id is not always a local
    # file at all. Statting one meant a path expression built from the
    # request, in the one handler people reach for when something is
    # already wrong.

    result = await playback_check.check(entity_id, media_id, path=path,
                                        expected_size=expected)
    # 200 either way: the report IS the answer, and a non-2xx would send the
    # page down its error path with the diagnosis in it.
    return web.json_response(result)


async def h_media_source(request: web.Request) -> web.Response:
    """Which media source BRight is building ids with, and what else Core
    has. Read by the Lab tab so a mismatch is legible before anything is
    played rather than after a speaker sits silent."""
    return web.json_response(media_source.state())


async def h_media_rediscover(request: web.Request) -> web.Response:
    """Look again. This is the button somebody presses after editing
    `media_dirs` and restarting Core — a cached wrong answer must never be
    something you have to restart the add-on to clear."""
    error = await asyncio.to_thread(_ensure_reference)
    if error:
        return web.json_response({"error": error}, status=500)
    return web.json_response(await media_source.discover(force=True))


async def h_cal_stop(request: web.Request) -> web.Response:
    """Silence the click track.

    The reference is 13 seconds long, and thirteen seconds is a long time
    in a quiet house at midnight with no way to end it — the wizard could
    start a sound and could not stop one. Also what the Party and Shows
    stops now do for their own music, offered here for the one player the
    wizard is pointed at.
    """
    body = await _json_body(request)
    entity_id = _entity(body)
    if entity_id is None:
        return web.json_response({"error": "media_player entity required"},
                                 status=400)
    result = await asyncio.to_thread(ha_client.media_stop, entity_id)
    if isinstance(result, dict) and result.get("error"):
        return web.json_response(
            {"error": f"could not stop {entity_id}: {result['error']}"},
            status=409)
    return web.json_response({"stopped": entity_id})


async def h_cal_profile_delete(request: web.Request) -> web.Response:
    """Remove a calibrated player that is no longer used.

    Not an archive: `best_entity` picks from these profiles, so a stale
    one is a candidate for every show that names no speaker. Deleting is
    cheap to reverse — calibration is a measurement, and re-taking it is
    a minute in the wizard.
    """
    entity_id = request.match_info["entity"]
    try:
        removed = await asyncio.to_thread(calibration_store.remove, entity_id)
    except ValueError:
        return web.json_response({"error": "not an entity id"}, status=400)
    if not removed:
        return web.json_response(
            {"error": f"{entity_id} has no calibration to delete"},
            status=404)
    return web.json_response(
        {"deleted": entity_id,
         "profiles": await asyncio.to_thread(calibration_store.all_profiles)})


async def h_cal_ping(request: web.Request) -> web.Response:
    """The phone's clock and ours differ; a few of these round trips let
    the wizard page estimate the offset (server minus client, from the
    lowest-RTT exchange)."""
    return web.json_response({"server_epoch_ms": time.time() * 1000.0})


async def _position_check(entity_id: str) -> dict:
    """Poll the player's reported position while the reference plays —
    the drift corrector may only trust players this proved."""
    samples = []
    for _ in range(6):
        await asyncio.sleep(2.0)
        snapshot = await asyncio.to_thread(ha_client.position_snapshot, entity_id)
        samples.append(snapshot)
    positions = [s.get("media_position") for s in samples
                 if isinstance(s.get("media_position"), (int, float))]
    increases = sum(1 for a, b in zip(positions, positions[1:]) if b > a)
    result = {
        "reliable": len(positions) >= 4 and increases >= 2,
        "reports_position": bool(positions),
        "samples": len(positions),
        # Not about drift at all — this poll is already watching the player
        # while the click track should be audible, so it is the one thing in
        # a position to answer "did the speaker actually play". A wizard that
        # heard nothing has two very different explanations and they need
        # different sentences.
        "ever_playing": any(
            s.get("state") in playback_check.PLAYING_STATES for s in samples),
        "states": sorted({str(s.get("state")) for s in samples}),
    }
    _POSITION_CHECKS[entity_id] = result
    return result


async def h_cal_play(request: web.Request) -> web.Response:
    body = await _json_body(request)
    entity_id = _entity(body)
    if entity_id is None:
        return web.json_response({"error": "media_player entity required"},
                                 status=400)
    error = await asyncio.to_thread(_ensure_reference)
    if error:
        return web.json_response({"error": error}, status=500)
    _POSITION_CHECKS.pop(entity_id, None)
    play_epoch_ms = time.time() * 1000.0
    result = await asyncio.to_thread(
        ha_client.play_media, entity_id, reference_media_id())
    if isinstance(result, dict) and result.get("error"):
        # Name what was asked for. Home Assistant answers a media it cannot
        # resolve with its own HTTP 500, which arrives here as a string and
        # reached the wizard as "HTTP 500" — a number about somebody else's
        # request, which is how this looked like a panel crash.
        return web.json_response({
            "error": f"Home Assistant would not play the click track on "
                     f"{entity_id}: {result['error']}. It was asked for "
                     f"{reference_media_id()}, which is {REFERENCE_WAV} in the "
                     f"add-on.",
        }, status=502)
    jobs.start(f"position-check:{entity_id}",
               lambda: _position_check(entity_id))
    return web.json_response({"play_epoch_ms": play_epoch_ms})


async def h_cal_analyze(request: web.Request) -> web.Response:
    """The wizard's recording, correlated. The page has already mapped its
    record-start moment onto OUR clock (via /api/calibrate/ping), so the
    arithmetic here never compares two different clocks."""
    body = await _json_body(request)
    entity_id = _entity(body)
    if entity_id is None:
        return web.json_response({"error": "media_player entity required"},
                                 status=400)
    try:
        record_start_ms = float(body["record_start_epoch_ms"])
        play_epoch_ms = float(body["play_epoch_ms"])
        wav = base64.b64decode(str(body["wav_b64"]))
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "missing recording fields"},
                                 status=400)
    try:
        estimate = await asyncio.to_thread(correlate.estimate_offset, wav)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    if estimate["confidence"] < correlate.MIN_CONFIDENCE:
        # "Move the phone closer" is the wrong advice — and infuriating —
        # when the speaker never made a sound. The position poll ran through
        # the same seconds the phone was listening, so it knows which of the
        # two happened.
        watched = _POSITION_CHECKS.get(entity_id) or {}
        if watched.get("ever_playing") is False:
            return web.json_response({
                "error": f"{entity_id} never started playing, so there was "
                         f"nothing for the phone to hear "
                         f"(it stayed {', '.join(watched.get('states') or ['idle'])}). "
                         f"Press Test playback to find out why.",
                "confidence": estimate["confidence"],
                "never_played": True,
            }, status=422)
        return web.json_response({
            "error": "could not hear the clicks clearly — move the phone "
                     "closer to the speaker, raise the volume, and try again",
            "confidence": estimate["confidence"],
        }, status=422)

    audible_epoch_ms = record_start_ms + estimate["lag_s"] * 1000.0
    offset_ms = audible_epoch_ms - play_epoch_ms
    if not -500.0 <= offset_ms <= 30000.0:
        return web.json_response({
            "error": f"measured {offset_ms:.0f}ms, which is not a plausible "
                     "speaker latency — was the right speaker playing?",
        }, status=422)
    profile = calibration_store.add_run(
        entity_id, offset_ms, method="mic",
        confidence=estimate["confidence"],
        position_attr=_POSITION_CHECKS.get(entity_id))
    return web.json_response({"measured_offset_ms": round(offset_ms, 1),
                              "profile": profile})


async def h_cal_taps(request: web.Request) -> web.Response:
    """The fallback: the person taps along with the clicks. Reaction time
    rides in (roughly +100ms), which is why the mic path is the default
    and this one says what it is in the stored method."""
    body = await _json_body(request)
    entity_id = _entity(body)
    if entity_id is None:
        return web.json_response({"error": "media_player entity required"},
                                 status=400)
    try:
        play_epoch_ms = float(body["play_epoch_ms"])
        taps = sorted(float(t) for t in body["taps_epoch_ms"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "missing tap fields"}, status=400)
    clicks = reference.CLICK_TIMES_S
    if len(taps) < 4:
        return web.json_response(
            {"error": "need at least 4 taps to average out reaction time"},
            status=422)
    pairs = min(len(taps), len(clicks))
    offsets = sorted(
        taps[i] - play_epoch_ms - clicks[i] * 1000.0 for i in range(pairs))
    offset_ms = offsets[len(offsets) // 2]
    spread = offsets[-1] - offsets[0]
    if spread > 700.0:
        watched = _POSITION_CHECKS.get(entity_id) or {}
        if watched.get("ever_playing") is False:
            return web.json_response(
                {"error": f"{entity_id} never started playing, so those taps "
                          f"were not on anything. Press Test playback to find "
                          f"out why.",
                 "never_played": True},
                status=422)
        return web.json_response(
            {"error": f"taps disagree by {spread:.0f}ms — try again, one "
                      "tap per click"},
            status=422)
    profile = calibration_store.add_run(
        entity_id, offset_ms, method="taps",
        position_attr=_POSITION_CHECKS.get(entity_id))
    return web.json_response({"measured_offset_ms": round(offset_ms, 1),
                              "profile": profile})


async def h_cal_manual(request: web.Request) -> web.Response:
    """Type the delay in and get on with it.

    Everything downstream is gated on a calibration profile — a show
    refuses to start without one, which is right, because a show whose
    offset nobody measured lands its cues somewhere unknowable. But it also
    means one broken step (a speaker that will not play the click track)
    takes the whole add-on with it, and that is not a gate, it is a brick.

    So: a profile a person typed, recorded as `method: "manual"` so the
    stored record never claims to have been measured. 0 is a perfectly good
    answer for a wired speaker, and the Shows tab works the moment it exists.
    """
    body = await _json_body(request)
    entity_id = _entity(body)
    if entity_id is None:
        return web.json_response({"error": "media_player entity required"},
                                 status=400)
    try:
        offset_ms = float(body["offset_ms"])
    except (KeyError, TypeError, ValueError):
        return web.json_response({"error": "offset_ms must be a number"},
                                 status=400)
    if not -2000.0 <= offset_ms <= 10000.0:
        return web.json_response(
            {"error": "offset_ms must be between -2000 and 10000 — a speaker "
                      "delay outside that is a different problem"},
            status=400)
    profile = calibration_store.add_run(entity_id, offset_ms, method="manual")
    return web.json_response({"profile": profile})


async def h_cal_adjust(request: web.Request) -> web.Response:
    body = await _json_body(request)
    entity_id = _entity(body)
    if entity_id is None:
        return web.json_response({"error": "media_player entity required"},
                                 status=400)
    try:
        adjust_ms = float(body.get("adjust_ms", 0))
    except (ValueError, TypeError):
        return web.json_response({"error": "adjust_ms must be a number"},
                                 status=400)
    profile = calibration_store.set_adjust(entity_id,
                                           max(-2000.0, min(2000.0, adjust_ms)))
    return web.json_response({"profile": profile})


async def h_cal_profiles(request: web.Request) -> web.Response:
    return web.json_response({"profiles": calibration_store.all_profiles()})


def _static_file(name: str, content_type: str):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(
            text=(STATIC / name).read_text(),
            content_type=content_type,
        )
    return handler


_STARTED = time.monotonic()


def build_app() -> web.Application:
    # client_max_size covers the calibration upload: ~14s of 48kHz 16-bit
    # PCM is ~1.4MB, ~1.9MB as base64 inside JSON. Default is 1MB.
    app = web.Application(middlewares=[_lan_gate], client_max_size=16 * 1024 ** 2)
    app.router.add_get("/api/health", h_health)
    app.router.add_get("/", h_index)
    app.router.add_get("/style.css", _static_file("style.css", "text/css"))
    app.router.add_get("/app.js", _static_file("app.js", "application/javascript"))
    app.router.add_get("/favicon.svg", _static_file("favicon.svg", "image/svg+xml"))
    app.router.add_get("/api/status", h_status)
    # Lab
    app.router.add_get("/api/lifx/devices", h_lifx_devices)
    app.router.add_post("/api/lifx/discover", h_lifx_discover)
    app.router.add_post("/api/lifx/probe", h_lifx_probe)
    app.router.add_post("/api/lifx/rate-test", h_lifx_rate_test)
    app.router.add_post("/api/lifx/waveform-demo", h_lifx_waveform_demo)
    app.router.add_get("/api/ha/entities", h_ha_entities)
    app.router.add_post("/api/ha/latency-probe", h_ha_latency_probe)
    app.router.add_get("/api/job/{job_id}", h_job)
    app.router.add_get("/api/lab/report", h_lab_report)
    # Light map
    app.router.add_get("/api/map", h_map)
    app.router.add_post("/api/map/fixture", h_map_upsert)
    app.router.add_delete("/api/map/fixture/{fixture_id}", h_map_remove)
    app.router.add_post("/api/map/import-lifx", h_map_import_lifx)
    app.router.add_get("/api/map/candidates", h_map_candidates)
    app.router.add_post("/api/map/add-lifx", h_map_add_lifx)
    # Effects — the builder, the preview, the presets
    app.router.add_get("/api/effects/catalog", h_effects_catalog)
    app.router.add_post("/api/effects/describe", h_effect_describe)
    app.router.add_post("/api/effects/invent", h_effect_invent)
    app.router.add_post("/api/effects/preview", h_effects_preview)
    app.router.add_post("/api/effects/preview-live", h_effects_live)
    app.router.add_get("/api/effects/presets", h_effect_presets)
    app.router.add_post("/api/effects/presets", h_effect_preset_save)
    app.router.add_delete("/api/effects/presets/{name}", h_effect_preset_remove)
    # Parties — saved evenings, startable by name
    app.router.add_get("/api/parties", h_parties)
    app.router.add_post("/api/parties", h_party_save)
    app.router.add_delete("/api/parties/{name}", h_party_remove)
    # Shows (the bridge forwards bright.* service calls to /api/show/*)
    app.router.add_post("/api/show/compile", h_show_compile)
    app.router.add_post("/api/show/start_show", h_show_start)
    app.router.add_post("/api/show/metronome", h_show_start)
    app.router.add_post("/api/show/stop_show", h_show_stop)
    app.router.add_post("/api/show/nudge", h_show_nudge)
    app.router.add_post("/api/show/nudge/keep", h_show_nudge_keep)
    app.router.add_post("/api/party/skip", h_party_skip)
    app.router.add_post("/api/show/autosync", h_show_autosync)
    app.router.add_post("/api/show/party_mode", h_show_party)
    # `start_party` is party_mode under the name the service uses: an
    # automation asks for a party, not for a mode.
    app.router.add_post("/api/show/start_party", h_show_party)
    app.router.add_post("/api/show/list_parties", h_party_list_for_bridge)
    app.router.add_get("/api/show/state", h_show_state)
    app.router.add_get("/api/show/{hash}/script", h_show_script)
    app.router.add_put("/api/show/{hash}/script", h_show_script_save)
    app.router.add_post("/api/show/{hash}/script/import", h_show_script_import)
    app.router.add_post("/api/show/{hash}/revise", h_show_revise)
    app.router.add_get("/api/show/{hash}/cues", h_show_cues)
    app.router.add_get("/api/show/{hash}/director", h_show_director)
    app.router.add_get("/api/show/{hash}/prompt", h_show_prompt)
    app.router.add_get("/api/track/{hash}/waveform", h_track_waveform)
    app.router.add_post("/api/show/{hash}/preview", h_show_preview)
    app.router.add_post("/api/show/{hash}/outline", h_show_outline)
    # Library
    app.router.add_get("/api/media/tree", h_media_tree)
    app.router.add_post("/api/media/folder", h_media_folder)
    app.router.add_get("/api/library", h_library)
    app.router.add_post("/api/library/analyze", h_library_analyze)
    app.router.add_get("/api/track/{hash}/analysis", h_track_analysis)
    # Calibration
    app.router.add_get("/api/media/source", h_media_source)
    app.router.add_post("/api/media/source/rediscover", h_media_rediscover)
    app.router.add_post("/api/calibrate/reference", h_cal_reference)
    app.router.add_post("/api/calibrate/ping", h_cal_ping)
    app.router.add_post("/api/calibrate/play", h_cal_play)
    app.router.add_post("/api/calibrate/stop", h_cal_stop)
    app.router.add_delete("/api/calibrate/profile/{entity}",
                          h_cal_profile_delete)
    app.router.add_post("/api/calibrate/analyze", h_cal_analyze)
    app.router.add_post("/api/calibrate/taps", h_cal_taps)
    app.router.add_post("/api/calibrate/manual", h_cal_manual)
    app.router.add_post("/api/calibrate/adjust", h_cal_adjust)
    app.router.add_get("/api/calibrate/profiles", h_cal_profiles)
    app.router.add_post("/api/playback/check", h_playback_check)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    port = panel_port.resolve()
    # Bound before the "listening" line, because the old order announced a
    # port it then failed to take — every log this add-on has ever written
    # about port 8095 says it was listening on it.
    try:
        sock = panel_port.bind(BIND_HOST, port)
    except panel_port.PortInUse as exc:
        log.error("%s", exc.strerror or exc)
        raise SystemExit(1) from None
    log.info("BRight panel v%s listening on %s:%s", ADDON_VERSION, BIND_HOST, port)
    web.run_app(build_app(), sock=sock, access_log=None, print=None)


if __name__ == "__main__":
    main()
