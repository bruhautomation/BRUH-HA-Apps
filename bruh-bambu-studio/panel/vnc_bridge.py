"""noVNC's websocket, bridged to x11vnc's TCP port.

This is what websockify does, in forty lines inside the panel instead of a
second process on a second port. x11vnc listens on loopback only
(`-localhost`), so the only way to the screen is through ingress — which is
authenticated and, with `panel_admin: true`, admin-only — and through this.

The two pumps race and the first to finish ends the other, but the loser is
WAITED for rather than abandoned: a pump cancelled mid-send that is left
alone raises into nothing and is reported later as "Task exception was
never retrieved", attributed to nothing (brAIn's terminal bridge met the
same thing, and `_settle` is its answer copied).
"""
from __future__ import annotations

import asyncio
import contextlib
import os

from aiohttp import WSMsgType, web

VNC_HOST = "127.0.0.1"
VNC_PORT = int(os.environ.get("BAMBU_VNC_PORT", "5900"))
CHUNK = 64 * 1024


async def _settle(done, pending) -> None:
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending)
    for task in list(done) + list(pending):
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None and not isinstance(exc, (ConnectionError, asyncio.CancelledError)):
            raise exc


async def handle(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(protocols=("binary",), heartbeat=30, max_msg_size=0)
    await ws.prepare(request)
    try:
        reader, writer = await asyncio.open_connection(VNC_HOST, VNC_PORT)
    except OSError:
        await ws.close(code=1011, message=b"The Bambu Studio screen is not running.")
        return ws

    async def browser_to_vnc():
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                writer.write(msg.data)
                await writer.drain()
            elif msg.type == WSMsgType.TEXT:
                writer.write(msg.data.encode())
                await writer.drain()
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break

    async def vnc_to_browser():
        while True:
            data = await reader.read(CHUNK)
            if not data:
                break
            await ws.send_bytes(data)

    tasks = {asyncio.create_task(browser_to_vnc()), asyncio.create_task(vnc_to_browser())}
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        await _settle(done, pending)
    finally:
        writer.close()
        with contextlib.suppress(OSError, ConnectionError):
            await writer.wait_closed()
        await ws.close()
    return ws
