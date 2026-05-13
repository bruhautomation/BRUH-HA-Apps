"""FastAPI server for the BRUH Claude chat UI.

Serves:
  GET /            -> chat UI static bundle (built from chat-ui/)
  GET /assets/*    -> chat UI assets
  GET /healthz     -> liveness probe
  WS  /ws/chat     -> bidirectional bridge to a `claude` subprocess

Auth: relies entirely on Home Assistant ingress in front. No auth here.

HA ingress quirk — the addon is served at `/api/hassio_ingress/<token>/` but
Astro builds asset references as absolute paths (`/assets/foo.css`). Inside
the ingress iframe the browser resolves those against the HA host root, not
the ingress prefix, so every asset 404s and the SPA renders unstyled + un-
hydrated. HA sets `X-Ingress-Path: /api/hassio_ingress/<token>` on every
proxied request; we read that header and rewrite the asset URLs in the
served HTML so the browser fetches them via the ingress path. Direct-port
access has no header → no rewrite → absolute URLs work natively.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
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


# --- Asset URL rewrite for HA ingress -------------------------------------
#
# Astro emits the SPA HTML with absolute asset references:
#     <link rel="stylesheet" href="/assets/index.HASH.css">
#     <astro-island component-url="/assets/Chat.HASH.js"
#                   renderer-url="/assets/client.HASH.js" ...>
#
# Under HA ingress these resolve against the HA host root, not the
# `/api/hassio_ingress/<token>/` iframe URL, so every fetch 404s. The fix is
# a string replace on the served HTML using the `X-Ingress-Path` header HA
# attaches to proxied requests. Direct-port access (no header) keeps
# absolute URLs unchanged.
#
# We match on the QUOTE + leading slash + asset-dir prefix, which covers
# `href=`, `src=`, `component-url=`, `renderer-url=`, and any other
# attribute-form reference Astro happens to add later. Inline scripts can't
# accidentally trip this because they'd need to embed the literal `"/assets/`
# substring, which only happens in the asset-reference path.
_ASSET_PREFIXES = ("/assets/", "/_astro/")


def rewrite_asset_urls(html: str, ingress_prefix: str) -> str:
    if not ingress_prefix:
        return html
    # Trim any trailing slash so we don't double up on `prefix//assets/...`.
    prefix = ingress_prefix.rstrip("/")
    for sub in _ASSET_PREFIXES:
        html = html.replace(f'"{sub}', f'"{prefix}{sub}')
        html = html.replace(f"'{sub}", f"'{prefix}{sub}")
    return html


_INDEX_HTML_CACHE: Optional[str] = None


def _load_index_html() -> Optional[str]:
    global _INDEX_HTML_CACHE
    if _INDEX_HTML_CACHE is None:
        path = STATIC_DIR / "index.html"
        if not path.exists():
            return None
        _INDEX_HTML_CACHE = path.read_text(encoding="utf-8")
    return _INDEX_HTML_CACHE


# Static file serving. Must come last so it doesn't shadow API routes.
if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa_fallback(path: str, request: Request) -> Response:
        # Serve any static file that exists, else fall back to index.html so
        # the SPA can handle client-side routing.
        target = STATIC_DIR / path
        if path and target.is_file():
            return FileResponse(target)
        html = _load_index_html()
        if html is None:
            return JSONResponse(
                status_code=500,
                content={"error": "index.html disappeared after startup"},
            )
        prefix = request.headers.get("x-ingress-path", "")
        return HTMLResponse(rewrite_asset_urls(html, prefix))
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
