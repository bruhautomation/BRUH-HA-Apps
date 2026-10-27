"""File-based IPC with Morph's service in brAIn's container — the
repository's one mechanism.

A request is a JSON file with a unique id in /config/.morph/requests; the
answer is a file of the same name in responses. It works whichever of Core
and the add-on started first, and a request written while the add-on is
restarting is still there when it comes back. Only WRITES come this way:
everything the panel reads is a mirror the add-on keeps in /config/.morph,
read directly, so opening the dashboard never waits on a round trip.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from .const import REQUEST_DIR, REQUEST_TIMEOUT, RESPONSE_DIR

POLL = 0.2


async def send_request(kind: str, payload: dict, *, timeout: int = REQUEST_TIMEOUT) -> dict:
    request_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()

    def _write() -> None:
        REQUEST_DIR.mkdir(parents=True, exist_ok=True)
        RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
        scratch = REQUEST_DIR / f".{request_id}.tmp"
        scratch.write_text(json.dumps({"id": request_id, "kind": kind, "ts": time.time(),
                                       "payload": payload}))
        scratch.replace(REQUEST_DIR / f"{request_id}.json")

    await loop.run_in_executor(None, _write)
    response = RESPONSE_DIR / f"{request_id}.json"
    waited = 0.0
    while waited < timeout:
        if response.exists():
            def _read() -> dict:
                try:
                    data = json.loads(response.read_text())
                finally:
                    response.unlink(missing_ok=True)
                return data if isinstance(data, dict) else {}
            try:
                return await loop.run_in_executor(None, _read)
            except (json.JSONDecodeError, OSError):
                pass  # caught mid-write: read it again on the next poll
        await asyncio.sleep(POLL)
        waited += POLL

    def _withdraw() -> None:
        (REQUEST_DIR / f"{request_id}.json").unlink(missing_ok=True)

    await loop.run_in_executor(None, _withdraw)
    return {"ok": False, "error": "brAIn's dashboard service did not answer. Is brAIn started, "
                                 "with the Morph dashboard switched on in ⚙ › Features?"}
