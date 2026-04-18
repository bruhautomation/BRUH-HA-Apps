"""File-based IPC bridge: HA Core writes command requests; the add-on processes
them and writes responses.

Design rationale:
    HA Core can't talk to the add-on directly over HTTP because the add-on's
    hassio_role is only `default`, and HA Core cannot reach the add-on's
    internal ports without extra plumbing. We instead share a directory via
    /config (which both sides can read/write), drop JSON request files, and
    poll for matching response files.
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
    tmp = req_path.with_suffix(".json.tmp")

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

    # Timed out — best-effort cleanup of orphan request
    await asyncio.to_thread(req_path.unlink, missing_ok=True)
    raise TimeoutError(f"bruh_minecraft: no response for {kind} within {timeout}s")
