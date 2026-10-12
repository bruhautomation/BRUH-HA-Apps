"""Home Assistant's WebSocket API, through the Supervisor's proxy.

The registries — floors, areas, devices, entities — are WebSocket-only, and
they are what the first dashboard is built from. Everything here answers
``None`` for "I could not ask", which callers keep distinct from an empty
list: a house with no floors and a Core that did not answer are different
answers, and only the first may shape a dashboard.
"""
from __future__ import annotations

import asyncio
import logging
import os

import aiohttp

log = logging.getLogger("morph.ha")

WS_URL = os.environ.get("MORPH_CORE_WS", "ws://supervisor/core/websocket")
TIMEOUT_S = 30


async def ws_calls(commands: list[dict]) -> list | None:
    """Run several commands on one connection. Each answer is the command's
    ``result``, or ``None`` for that command when Core refused it."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(WS_URL, heartbeat=20, max_msg_size=0) as ws:
                hello = await asyncio.wait_for(ws.receive_json(), TIMEOUT_S)
                if hello.get("type") != "auth_required":
                    return None
                await ws.send_json({"type": "auth", "access_token": token})
                ok = await asyncio.wait_for(ws.receive_json(), TIMEOUT_S)
                if ok.get("type") != "auth_ok":
                    log.warning("Core refused the Supervisor token")
                    return None
                answers: dict[int, object] = {}
                for i, cmd in enumerate(commands, start=1):
                    await ws.send_json({"id": i, **cmd})
                while len(answers) < len(commands):
                    msg = await asyncio.wait_for(ws.receive_json(), TIMEOUT_S)
                    if msg.get("type") != "result":
                        continue
                    answers[msg["id"]] = msg.get("result") if msg.get("success") else None
                return [answers.get(i) for i in range(1, len(commands) + 1)]
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
        log.warning("Could not reach Home Assistant: %s", exc)
        return None


async def house() -> dict | None:
    """Everything the generator reads, in one round trip."""
    res = await ws_calls([
        {"type": "get_states"},
        {"type": "config/area_registry/list"},
        {"type": "config/floor_registry/list"},
        {"type": "config/device_registry/list"},
        {"type": "config/entity_registry/list"},
    ])
    if res is None or res[0] is None:
        return None
    states, areas, floors, devices, entities = res
    return {"states": states or [], "areas": areas or [], "floors": floors or [],
            "devices": devices or [], "entities": entities or [],
            "floors_read": floors is not None}
