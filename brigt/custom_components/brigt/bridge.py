"""File-based IPC bridge: HA Core writes request files; the add-on's
ha-bridge.py processes them and writes responses.

HA Core can't reach the add-on's panel port directly without extra
plumbing (hassio_role is only `default`), so both sides share a directory
under /config instead: drop a JSON request file, poll for the matching
response file.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .const import COMMAND_REQ_DIR, COMMAND_RES_DIR


async def send_request(kind: str, payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    """Drop a request file and wait up to `timeout` seconds for a response."""
    Path(COMMAND_REQ_DIR).mkdir(parents=True, exist_ok=True)
    Path(COMMAND_RES_DIR).mkdir(parents=True, exist_ok=True)

    req_id = uuid.uuid4().hex
    req_path = Path(COMMAND_REQ_DIR) / f"{int(time.time())}-{req_id}.json"
    res_path = Path(COMMAND_RES_DIR) / f"{req_id}.json"

    body = {"id": req_id, "kind": kind, "payload": payload, "ts": time.time()}
    # The scratch name embeds the request's own unique id, so two callers can
    # never race each other for it the way a target-derived name would.
    tmp = req_path.with_name(f".{req_id}.tmp")

    def _write() -> None:
        tmp.write_text(json.dumps(body))
        tmp.replace(req_path)

    await asyncio.to_thread(_write)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await asyncio.to_thread(res_path.is_file):
            def _read_and_clean() -> dict[str, Any]:
                data = json.loads(res_path.read_text())
                res_path.unlink(missing_ok=True)
                return data
            return await asyncio.to_thread(_read_and_clean)
        await asyncio.sleep(0.25)

    # Timed out — best-effort cleanup of the orphan request.
    await asyncio.to_thread(req_path.unlink, missing_ok=True)
    raise TimeoutError(f"brigt: no response for {kind} within {timeout}s")
