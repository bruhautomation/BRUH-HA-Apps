"""FastAPI server for the BRUH Claude chat UI.

Serves:
  GET /            -> chat UI static bundle (built from chat-ui/)
  GET /assets/*    -> chat UI assets
  GET /healthz     -> liveness probe
  WS  /ws/chat     -> bidirectional bridge to a `claude` subprocess

Auth: relies entirely on Home Assistant ingress in front. No auth here.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from claude_session import ClaudeSession

logging.basicConfig(
    level=os.environ.get("BRUH_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bruh-chat")

STATIC_DIR = Path(os.environ.get("BRUH_CHAT_UI_DIST", "/opt/chat-ui-dist"))

app = FastAPI(title="BRUH Claude Chat", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket) -> None:
    await ws.accept()

    # Optional bootstrap params (session_id, model, permission_mode) sent as
    # the first JSON message before any user turn. If the client jumps
    # straight to a user message, dispatch it after the session boots.
    init: dict = {}
    pending_first_msg: Optional[dict] = None
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
        if first.get("type") == "init":
            init = first
        else:
            pending_first_msg = first
    except (asyncio.TimeoutError, ValueError):
        pass

    default_perm = os.environ.get("BRUH_CHAT_PERMISSION_MODE", "acceptEdits")
    session_kwargs = {
        "cwd": init.get("cwd") or os.environ.get("BRUH_CHAT_CWD", "/config"),
        "model": init.get("model"),
        "permission_mode": init.get("permission_mode") or default_perm,
    }
    if init.get("session_id"):
        session_kwargs["session_id"] = init["session_id"]
    session = ClaudeSession(**session_kwargs)

    try:
        await session.start()
    except Exception as e:
        log.exception("failed to start claude session")
        await ws.send_json({
            "type": "server_error",
            "error": f"failed to start claude: {e!r}",
        })
        await ws.close()
        return

    await ws.send_json({
        "type": "session_ready",
        "session_id": session.session_id,
        "cwd": session.cwd,
        "permission_mode": session.permission_mode,
    })

    async def pump_events_to_client() -> None:
        try:
            async for event in session.events():
                await ws.send_json(event)
        except Exception as e:
            log.warning("event pump terminated: %r", e)
        finally:
            tail = session.stderr_tail()
            await ws.send_json({"type": "session_closed", "stderr_tail": tail})

    pump_task = asyncio.create_task(pump_events_to_client())

    try:
        if pending_first_msg is not None:
            await _dispatch_client_message(session, pending_first_msg)
        while True:
            msg = await ws.receive_json()
            await _dispatch_client_message(session, msg)
    except WebSocketDisconnect:
        log.info("client disconnected, session %s", session.session_id)
    except Exception as e:
        log.exception("ws error: %r", e)
    finally:
        pump_task.cancel()
        await session.close()


async def _dispatch_client_message(session: ClaudeSession, msg: dict) -> None:
    """Route a single client→server WS message to the right session method."""
    mtype = msg.get("type")
    if mtype == "user":
        content = msg.get("content", "")
        if isinstance(content, list):
            # Allow rich content array; for v1 we flatten to plain text.
            content = "".join(b.get("text", "") for b in content if b.get("type") == "text")
        await session.send_user_message(content)
    elif mtype == "interrupt":
        session.interrupt()
    elif mtype == "ping":
        # Client keepalive; the WS framing already covers liveness, this is for
        # clients that want a round-trip confirmation.
        pass
    else:
        log.debug("ignoring unknown client message type=%r", mtype)


# Static file serving. Must come last so it doesn't shadow API routes.
if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str) -> FileResponse:
        # Serve any static file that exists, else fall back to index.html so
        # the SPA can handle client-side routing.
        target = STATIC_DIR / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(STATIC_DIR / "index.html")
else:
    @app.get("/")
    async def missing_ui() -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": "chat UI bundle missing",
                "expected_at": str(STATIC_DIR),
            },
        )
