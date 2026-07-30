"""Reverse-proxy the ttyd web terminal under /terminal/.

brAIn publishes a single ingress port. The panel owns it, so the terminal
has to be reachable *through* the panel rather than beside it — that is
what makes Terminal a tab instead of a second add-on.

ttyd speaks plain HTTP for its bundle and a WebSocket at /ws for the
session itself, so both are forwarded. ttyd's client builds its WebSocket
URL relative to the page it was served from, which means serving its HTML
at /terminal/ makes the client connect to /terminal/ws on its own — we
just strip the prefix on the way upstream.

Nothing here is reachable from outside Home Assistant: ingress already
authenticated the request before aiohttp ever sees it.
"""
from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
from aiohttp import web

log = logging.getLogger("brain.terminal")

TTYD_HOST = os.environ.get("BRAIN_TTYD_HOST", "127.0.0.1")
TTYD_PORT = int(os.environ.get("BRAIN_TTYD_PORT", "7681"))
TTYD_BASE = f"http://{TTYD_HOST}:{TTYD_PORT}"

PREFIX = "/terminal"

# Headers that describe a single hop and must not be relayed onward.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-encoding", "content-length",
}

DISABLED_PAGE = """<!doctype html><meta charset="utf-8">
<title>Terminal disabled</title>
<style>body{font:16px/1.6 system-ui,sans-serif;background:#0A1622;color:#e8eef5;
padding:3rem;max-width:34rem;margin:auto}code{background:#16273a;padding:.15em .4em;
border-radius:4px}</style>
<h2>The terminal is turned off</h2>
<p>Set <code>enable_terminal: true</code> in this add-on's configuration and
restart to use it.</p>
"""


def _clean(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


def _upstream_url(request: web.Request) -> str:
    """Map /terminal/<rest> onto ttyd's /<rest>, query string intact."""
    rest = request.match_info.get("path", "")
    url = f"{TTYD_BASE}/{rest}"
    if request.query_string:
        url = f"{url}?{request.query_string}"
    return url


def _enabled() -> bool:
    return os.environ.get("BRAIN_ENABLE_TERMINAL", "true").lower() != "false"


async def _proxy_ws(request: web.Request, url: str) -> web.StreamResponse:
    """Bridge a browser WebSocket to ttyd's, pumping frames both ways.

    ttyd negotiates the 'tty' subprotocol; the browser asks for it, so the
    same value is offered upstream and echoed back downstream or the client
    refuses the connection.
    """
    protocols = [
        p.strip() for p in
        request.headers.get("Sec-WebSocket-Protocol", "").split(",") if p.strip()
    ]
    client = web.WebSocketResponse(protocols=protocols or ("tty",))
    await client.prepare(request)

    session: aiohttp.ClientSession = request.app["ttyd_session"]
    try:
        async with session.ws_connect(
            url.replace("http://", "ws://", 1),
            protocols=protocols or ("tty",),
            headers=_clean(request.headers),
            heartbeat=30,
            max_msg_size=0,
        ) as upstream:

            async def pump(src, dst) -> None:
                async for msg in src:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await dst.send_str(msg.data)
                    elif msg.type == aiohttp.WSMsgType.BINARY:
                        await dst.send_bytes(msg.data)
                    elif msg.type in (aiohttp.WSMsgType.CLOSE,
                                      aiohttp.WSMsgType.CLOSING,
                                      aiohttp.WSMsgType.CLOSED,
                                      aiohttp.WSMsgType.ERROR):
                        break

            # Either direction closing ends the session; cancel the other.
            done, pending = await asyncio.wait(
                [asyncio.create_task(pump(client, upstream)),
                 asyncio.create_task(pump(upstream, client))],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except (aiohttp.ClientError, OSError) as exc:
        log.warning("terminal websocket upstream failed: %s", exc)
    finally:
        if not client.closed:
            await client.close()
    return client


async def handle(request: web.Request) -> web.StreamResponse:
    if not _enabled():
        return web.Response(text=DISABLED_PAGE, content_type="text/html")

    url = _upstream_url(request)

    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _proxy_ws(request, url)

    session: aiohttp.ClientSession = request.app["ttyd_session"]
    try:
        async with session.request(
            request.method, url,
            headers=_clean(request.headers),
            data=request.content if request.body_exists else None,
            allow_redirects=False,
        ) as upstream:
            body = await upstream.read()
            return web.Response(
                status=upstream.status,
                headers=_clean(upstream.headers),
                body=body,
            )
    except (aiohttp.ClientError, OSError) as exc:
        # ttyd not up yet (or disabled mid-run) — say so plainly instead of
        # letting the tab show an opaque 500.
        log.warning("terminal upstream unreachable: %s", exc)
        return web.Response(
            status=502,
            content_type="text/html",
            text="<!doctype html><meta charset=utf-8>"
                 "<p style='font:16px system-ui;padding:2rem'>The terminal isn't "
                 "responding yet. It usually takes a few seconds after a restart — "
                 "reload the tab.</p>",
        )


def setup(app: web.Application) -> None:
    """Register the /terminal routes and the upstream client session."""

    async def _open(app: web.Application) -> None:
        # No total timeout: terminal sessions are long-lived by nature.
        app["ttyd_session"] = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))

    async def _close(app: web.Application) -> None:
        session = app.get("ttyd_session")
        if session is not None:
            await session.close()

    app.on_startup.append(_open)
    app.on_cleanup.append(_close)

    # Bare /terminal needs the trailing slash, or ttyd's relative asset
    # paths resolve one level too high.
    async def _slash(request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound(PREFIX + "/")

    app.router.add_get(PREFIX, _slash)
    app.router.add_route("*", PREFIX + "/{path:.*}", handle)
