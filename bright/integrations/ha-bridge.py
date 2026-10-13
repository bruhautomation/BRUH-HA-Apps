#!/usr/bin/env python3
"""Watches /config/.bright/requests/ for JSON request files written by the
companion HA integration, dispatches them, and writes a response file back
to /config/.bright/responses/<id>.json.

Also mirrors the add-on's show state into /config/.bright/state.json every
few seconds so HA Core (which cannot see /data) can read it.

Show control (party_mode / start_show / stop_show) is forwarded to the
panel's local API on loopback — the panel owns the conductor, and a
second process driving the lights would be a second answer to "what is
playing". While the panel has no show endpoints yet (the skeleton build),
the forward comes back as a clear "not in this build yet" rather than a
timeout.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# The panel's port is the Supervisor's to choose, so it is looked up rather
# than known — from the same module the panel binds with, because a bridge
# posting to a port the panel is not on is every show service timing out.
sys.path.append(str(Path(__file__).resolve().parent.parent / "panel"))
import panel_port  # noqa: E402

SHARED = Path("/config/.bright")
REQ_DIR = SHARED / "requests"
RES_DIR = SHARED / "responses"
STATE_SRC = Path(os.environ.get("BRIGHT_STATE", "/data")) / "state.json"
STATE_DST = SHARED / "state.json"

PANEL_URL = f"http://127.0.0.1:{panel_port.resolve()}"

POLL_INTERVAL = 0.5
MIRROR_INTERVAL = 5

KNOWN_KINDS = ("party_mode", "start_party", "start_show", "stop_show",
               "list_parties", "get_status", "import_show")

# How long the panel may take over a request. An import compiles a whole
# show, which on a small machine is longer than starting or stopping one;
# the integration waits a little longer than this for the same reason.
PANEL_TIMEOUT_S = 10
SLOW_KINDS = {"import_show": 90}


def _log(msg: str) -> None:
    print(f"[ha-bridge {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _write_response(req_id: str, payload: dict[str, Any]) -> None:
    # The scratch name embeds the response's own id — unique per request, so
    # two writers can never pick the same scratch file.
    tmp = RES_DIR / f".{req_id}.tmp"
    dst = RES_DIR / f"{req_id}.json"
    tmp.write_text(json.dumps(payload))
    tmp.replace(dst)


def _panel_post(path: str, payload: dict[str, Any],
                timeout: float = PANEL_TIMEOUT_S) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{PANEL_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


async def handle(request: dict[str, Any]) -> dict[str, Any]:
    kind = request.get("kind", "")
    payload = request.get("payload", {}) or {}

    if kind not in KNOWN_KINDS:
        return {"ok": False, "error": f"unknown request kind: {kind!r}"}

    def _forward() -> dict[str, Any]:
        try:
            path = f"/api/show/{kind}"
            slow = SLOW_KINDS.get(kind)
            return (_panel_post(path, payload, timeout=slow) if slow
                    else _panel_post(path, payload))
        except urllib.error.HTTPError as exc:
            # The panel's body carries the sentence; the status carries a
            # number. Reporting the number is how "no analyzed tracks in
            # /media/music — run the Library tab first" reached an
            # automation as "panel answered HTTP 409", which is the same
            # failure the Calibrate tab used to have one layer in.
            detail = ""
            try:
                body = json.loads(exc.read().decode() or "{}")
                detail = str(body.get("error", "") or "")
            except (ValueError, OSError, UnicodeDecodeError):
                detail = ""
            if detail:
                return {"ok": False, "error": detail}
            if exc.code == 404:
                return {"ok": False,
                        "error": f"BRight's panel has no /api/show/{kind} "
                                 f"route — is the add-on up to date?"}
            return {"ok": False, "error": f"panel answered HTTP {exc.code} "
                                          f"with no reason in it"}
        except (urllib.error.URLError, OSError) as exc:
            return {"ok": False, "error": f"panel unreachable: {exc}"}

    return await asyncio.to_thread(_forward)


async def _serve(req_id: str, request: dict[str, Any]) -> None:
    response = await handle(request)
    try:
        _write_response(req_id, response)
    except OSError as exc:
        _log(f"could not answer {request.get('kind')}: {exc}")
        return
    _log(f"handled {request.get('kind')} -> ok={response.get('ok')}")


# Requests in flight, held so the loop cannot collect a task it only
# scheduled. Each request is served on its own: an import compiling a show
# must not make a stop_show pressed meanwhile wait for it.
_IN_FLIGHT: set = set()


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
                path.unlink(missing_ok=True)
                req_id = str(request.get("id", ""))
                if not req_id:
                    continue
                task = asyncio.create_task(_serve(req_id, request))
                _IN_FLIGHT.add(task)
                task.add_done_callback(_IN_FLIGHT.discard)
        except OSError as exc:
            _log(f"request loop error: {exc}")
        await asyncio.sleep(POLL_INTERVAL)


async def mirror_loop() -> None:
    while True:
        try:
            if STATE_SRC.is_file():
                state = STATE_SRC.read_text()
            else:
                state = json.dumps({"status": "idle"})
            tmp = SHARED / ".state.mirror.tmp"
            tmp.write_text(state)
            tmp.replace(STATE_DST)
        except OSError as exc:
            _log(f"mirror error: {exc}")
        await asyncio.sleep(MIRROR_INTERVAL)


async def main() -> None:
    _log("BRight HA bridge starting")
    await asyncio.gather(request_loop(), mirror_loop())


if __name__ == "__main__":
    asyncio.run(main())
