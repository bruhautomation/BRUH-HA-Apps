"""File-based IPC with the add-on.

A request is a JSON file with a unique id; the answer is a file named after
it. That is deliberately the same mechanism the other add-ons in this
repository use, and it is chosen for one property: it works when Core and the
add-on disagree about who started first. There is no socket to be refused, no
port to be taken, and a request written while the add-on is restarting is
still there when it comes back.

The response file is polled rather than watched. `asyncio.sleep` in a loop is
not elegant, but an inotify watch on a folder inside a bind mount is a
promise this cannot keep across every host filesystem Home Assistant runs on.
"""
from __future__ import annotations

import asyncio
import json
import uuid

from .const import REQUEST_DIR, REQUEST_TIMEOUT, RESPONSE_DIR

POLL = 0.25


async def send_request(kind: str, payload: dict, *,
                       timeout: int = REQUEST_TIMEOUT) -> dict:
    """Ask the add-on to do something and wait for its answer."""
    request_id = uuid.uuid4().hex

    def _write() -> None:
        REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
        # Written to a scratch name and renamed, so the bridge can never read
        # a half-written request — it polls a glob, and a partially flushed
        # file matches it.
        scratch = REQUEST_DIR / f".{request_id}.tmp"
        scratch.write_text(json.dumps(
            {"id": request_id, "kind": kind, "payload": payload}))
        scratch.replace(REQUEST_DIR / f"{request_id}.json")

    await asyncio.get_running_loop().run_in_executor(None, _write)

    response_path = RESPONSE_DIR / f"{request_id}.json"
    waited = 0.0
    while waited < timeout:
        if response_path.exists():
            def _read() -> dict:
                try:
                    data = json.loads(response_path.read_text())
                finally:
                    response_path.unlink(missing_ok=True)
                return data if isinstance(data, dict) else {}
            try:
                return await asyncio.get_running_loop().run_in_executor(
                    None, _read)
            except (json.JSONDecodeError, OSError):
                # A response file caught mid-rename is a race we lost by a
                # hair; the next poll gets it whole.
                pass
        await asyncio.sleep(POLL)
        waited += POLL

    # The request file is left in place. The add-on may be mid-restart, and
    # deleting the ask would turn "slow" into "never happened" — whereas an
    # abandoned request costs one stale label at worst, and the add-on's own
    # unlink-before-work rule stops it being replayed forever.
    raise TimeoutError(
        f"BRUH Print did not answer in {timeout}s. Is the add-on running?")
