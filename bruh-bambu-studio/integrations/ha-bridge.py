#!/usr/bin/env python3
"""Watches /config/.bruh_bambu/requests/ for JSON request files written by the
companion integration, forwards each to the panel, and writes the answer back
to /config/.bruh_bambu/responses/<id>.json.

Everything is forwarded rather than handled. The panel owns the printers —
one MQTT session each, the upload, the jobs — and a second process holding
its own session would be a second answer to "what is this printer doing".

The panel's own sentence is what comes back: "Workshop X1C is already
printing" in an automation trace is a fixable mistake, and `HTTP 409` is a
mystery.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SHARED = Path(os.environ.get("BAMBU_SHARED", "/config/.bruh_bambu"))
REQ_DIR = SHARED / "requests"
RES_DIR = SHARED / "responses"
PANEL_URL = f"http://127.0.0.1:{os.environ.get('BAMBU_PANEL_PORT', '8093')}"
POLL_INTERVAL = 0.4
_TASKS: set = set()
# A print that has to be sliced first is minutes of CPU; the panel waits
# up to its own ceiling and the forward waits a little longer than that.
PRINT_WAIT_S = 900
TIMEOUT = PRINT_WAIT_S + 60


def _command(action: str, **fixed):
    def build(p: dict):
        body = {"printer": p.get("printer", ""), "action": action, **fixed}
        for key in ("value", "target"):
            if key in p:
                body[key] = p[key]
        return "POST", "/api/printer/command", body
    return build


def _with_wait(path: str):
    def build(p: dict):
        return "POST", path, {**p, "wait": p.get("wait", PRINT_WAIT_S)}
    return build


ROUTES = {
    "get_status": lambda p: ("GET", "/api/state", None),
    "list_files": lambda p: ("GET", "/api/files?profiles=1", None),
    "printer_files": lambda p: (
        "GET", "/api/printer/storage?" + urllib.parse.urlencode(
            {"printer": p.get("printer", "")}), None),
    "print_file": _with_wait("/api/print"),
    "slice_file": _with_wait("/api/slice"),
    "pause_print": _command("pause"),
    "resume_print": _command("resume"),
    "stop_print": _command("stop"),
    "set_speed": _command("speed"),
    "set_light": _command("light"),
    "set_temperature": _command("temperature"),
    "send_gcode": _command("gcode"),
    "open_in_studio": lambda p: ("POST", "/api/studio/open", {"file": p.get("file", "")}),
    "import_url": _with_wait("/api/import"),
    "find_printers": lambda p: ("POST", "/api/printers/scan",
                                {"subnet": p.get("subnet", ""), "wait": 120}),
}

# The fields a service call carries under the names people use, renamed to
# the panel's: `speed: sport` and `on: true` read better in YAML than
# `value:`, and the panel has one command route.
RENAME = {"set_speed": {"speed": "value"}, "set_light": {"on": "value"},
          "set_temperature": {"temperature": "value"}, "send_gcode": {"gcode": "value"}}


def _log(message: str) -> None:
    print(f"[ha-bridge {time.strftime('%H:%M:%S')}] {message}", flush=True)


def _write_response(request_id: str, payload: dict) -> None:
    tmp = RES_DIR / f".{request_id}.tmp"
    tmp.write_text(json.dumps(payload))
    tmp.replace(RES_DIR / f"{request_id}.json")


def summarise_state(state: dict) -> dict:
    """The panel's state trimmed to what a caller deciding what to do needs."""
    studio = state.get("studio") or {}
    return {
        "ok": True,
        "studio": {"installed": studio.get("installed"), "version": studio.get("version"),
                   "running": studio.get("running"),
                   "install": (studio.get("install") or {}).get("phase")},
        "printers": [{k: p.get(k) for k in (
            "id", "name", "model", "online", "state", "printing", "progress",
            "remaining_min", "layer", "total_layers", "file", "nozzle_c",
            "nozzle_target_c", "bed_c", "bed_target_c", "chamber_c", "speed",
            "chamber_light", "ams", "error_code", "hms_count", "connection_error")}
            for p in state.get("printers") or [] if isinstance(p, dict)],
        "jobs": [{k: j.get(k) for k in ("id", "kind", "state", "phase", "file",
                                        "source", "output", "error", "printer")}
                 for j in (state.get("jobs") or [])[:5] if isinstance(j, dict)],
    }


def _forward(method: str, path: str, payload: dict | None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{PANEL_URL}{path}", data=body, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = str(json.loads(exc.read().decode() or "{}").get("error", ""))
        except (ValueError, OSError, UnicodeDecodeError):
            detail = ""
        return {"ok": False, "error": detail or
                f"The BRUH Bambu Studio panel answered HTTP {exc.code} with no reason."}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "error": f"The BRUH Bambu Studio panel is not answering: {exc}"}


async def handle(request: dict) -> dict:
    kind = str(request.get("kind", ""))
    payload = dict(request.get("payload") or {})
    route = ROUTES.get(kind)
    if route is None:
        return {"ok": False, "error": f"BRUH Bambu Studio does not know how to do "
                                      f"{kind!r}. Known: {', '.join(sorted(ROUTES))}."}
    for old, new in RENAME.get(kind, {}).items():
        if old in payload:
            payload[new] = payload.pop(old)
    method, path, body = route(payload)
    answer = await asyncio.to_thread(_forward, method, path, body)
    if kind == "get_status" and answer.get("ok") is not False:
        return summarise_state(answer)
    return answer


async def request_loop() -> None:
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    RES_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            for path in sorted(REQ_DIR.glob("*.json")):
                try:
                    request = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    path.unlink(missing_ok=True)
                    continue
                # Unlinked before the work: a request that makes this fall
                # over must not be retried on every poll, starting a print
                # each time it nearly works.
                path.unlink(missing_ok=True)
                request_id = str(request.get("id", ""))
                if not request_id:
                    continue
                # One task per request, so a print waiting on a slice does
                # not hold up a pause somebody pressed meanwhile.
                # Held, because the loop keeps only a weak reference.
                task = asyncio.create_task(_answer(request_id, request))
                _TASKS.add(task)
                task.add_done_callback(_TASKS.discard)
        except OSError as exc:
            _log(f"request loop error: {exc}")
        await asyncio.sleep(POLL_INTERVAL)


async def _answer(request_id: str, request: dict) -> None:
    response = await handle(request)
    try:
        _write_response(request_id, response)
    except OSError as exc:
        _log(f"could not write the answer to {request_id}: {exc}")
    _log(f"{request.get('kind')} -> ok={response.get('ok')}")


async def main() -> None:
    _log(f"BRUH Bambu Studio HA bridge starting, panel at {PANEL_URL}")
    await request_loop()


if __name__ == "__main__":
    asyncio.run(main())
