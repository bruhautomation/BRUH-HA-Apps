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
authenticated the request before aiohttp ever sees it. ttyd itself now
requires HTTP Basic auth, because its port *is* reachable from outside if
a user publishes it — so the proxy holds the credential and presents it
upstream, and the person coming in through ingress never sees a prompt.
The credential is deliberately added after `_clean()`, which drops any
`Authorization` the client sent — in any spelling — so a browser holding
one for the ingress origin cannot present it to ttyd in place of ours.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os

import aiohttp
from aiohttp import web

log = logging.getLogger("brain.terminal")

# Written by run.sh's setup_terminal_credential() before ttyd starts.
CREDENTIAL_FILE = os.environ.get("BRAIN_TTYD_CREDENTIAL_FILE",
                                 "/data/terminal-credential")

TTYD_HOST = os.environ.get("BRAIN_TTYD_HOST", "127.0.0.1")
TTYD_PORT = int(os.environ.get("BRAIN_TTYD_PORT", "7681"))
TTYD_BASE = f"http://{TTYD_HOST}:{TTYD_PORT}"

PREFIX = "/terminal"

# Ping both legs of the bridge, not just the upstream one.
#
# ttyd pings the proxy and the proxy pings ttyd, so that half of the link
# never looks idle. The browser half had nothing: on a terminal nobody is
# typing at, no bytes crossed it at all, and the proxy in front of us —
# ingress, or Nabu Casa remote — closed it as idle after a minute or two.
# ttyd saw the socket go, killed the session's process, the client
# reconnected, and the whole cycle repeated for as long as the tab was
# open. That is the "WS closed / killing process / started process" churn
# every minute or two in the add-on log, and it is why a terminal left open
# kept losing its place.
WS_HEARTBEAT_S = float(os.environ.get("BRAIN_TERMINAL_WS_HEARTBEAT", "25"))

# Headers that describe a single hop and must not be relayed onward.
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host",
    "content-encoding", "content-length",
    # If ttyd ever refuses our credential, relaying its challenge would pop
    # a browser Basic-auth dialog inside the ingress iframe that no password
    # the user knows can satisfy. A bare 401 is the more honest failure.
    "www-authenticate",
}

# Dropped from every request going upstream. Not hop-by-hop in the RFC
# sense — this one is a credential. The proxy presents ttyd its OWN, and a
# client holding a credential for the ingress origin must not be able to
# present it in ttyd's place.
#
# It has to be filtered by the same case-folding pass HOP_BY_HOP gets.
# Popping the two spellings "Authorization" and "authorization" off a plain
# dict was not that: `_clean` keys the dict by whatever case the client sent,
# HTTP considers every spelling of a header name identical, and aiohttp
# hands the name through as received. So `AUTHORIZATION: Basic ...` survived
# both pops and rode upstream *beside* the credential added on the next
# line — two Authorization headers, and which one ttyd honours was never
# ours to decide. Lower-casing the comparison is the whole fix; the guard
# only ever needed to be spelled the way the rest of the filtering is.
CLIENT_DROPPED = {"authorization"}

DISABLED_PAGE = """<!doctype html><meta charset="utf-8">
<title>Terminal disabled</title>
<style>body{font:16px/1.6 system-ui,sans-serif;background:#0A1622;color:#e8eef5;
padding:3rem;max-width:34rem;margin:auto}code{background:#16273a;padding:.15em .4em;
border-radius:4px}</style>
<h2>The terminal is turned off</h2>
<p>Set <code>enable_terminal: true</code> in this add-on's configuration and
restart to use it.</p>
"""


def _clean(headers, drop: set[str] = HOP_BY_HOP) -> dict:
    """Copy `headers`, dropping any whose name case-folds into `drop`."""
    return {k: v for k, v in headers.items() if k.lower() not in drop}


def _auth_header() -> dict:
    """Basic-auth header for ttyd, or {} if there is no credential yet.

    Read on every request rather than cached at import: the panel and ttyd
    are started by the same run.sh, but nothing orders the panel's import
    after the credential file exists, and a value cached as empty would
    stay empty for the life of the process.
    """
    try:
        with open(CREDENTIAL_FILE, "r", encoding="utf-8") as fh:
            credential = fh.read().strip()
    except OSError:
        return {}
    if not credential:
        return {}
    encoded = base64.b64encode(credential.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {encoded}"}


def _upstream_headers(request: web.Request) -> dict:
    """The client's headers, minus this hop's, carrying ttyd's credential.

    Whatever the client sent is dropped before ours is added, however the
    client spelled it — see CLIENT_DROPPED.
    """
    headers = _clean(request.headers, HOP_BY_HOP | CLIENT_DROPPED)
    headers.update(_auth_header())
    return headers


def _upstream_url(request: web.Request) -> str:
    """Map /terminal/<rest> onto ttyd's /<rest>, query string intact."""
    rest = request.match_info.get("path", "")
    url = f"{TTYD_BASE}/{rest}"
    if request.query_string:
        url = f"{url}?{request.query_string}"
    return url


def _enabled() -> bool:
    return os.environ.get("BRAIN_ENABLE_TERMINAL", "true").lower() != "false"


async def _settle(done: set, pending: set) -> None:
    """End the losing pump, and surface the winning one's failure.

    Two things `asyncio.wait` does not do, and the bridge needed both.

    Cancelling only ASKS. Un-awaited, the losing pump is still inside
    `dst.send_*` when the caller closes the upstream socket out from under
    it — a second failure, raised on the way out of the first. That second
    failure must not become the one reported, either: it is incidental to
    the shutdown, where the winner's is the reason for it.

    And an exception inside a task never reaches `asyncio.wait`: a bridge
    that broke mid-frame returned here indistinguishable from one the
    browser closed politely. The caller's `except` never saw it, nothing was
    logged about why the terminal dropped, and Python printed a bare "Task
    exception was never retrieved" traceback into the add-on log at some
    later collection, attributed to nothing. Re-raising puts the reason on
    the proxy's own warning line, beside the session it belongs to.
    """
    for task in pending:
        task.cancel()
    # `asyncio.wait`, not `await task`: waiting must not itself raise. A pump
    # cancelled mid-send can come back carrying a ConnectionResetError of its
    # own, and letting that propagate from here would skip the loop below —
    # reporting the loser's incidental error while the winner's real reason
    # went unread and unretrieved. That is this function's own bug, one case
    # narrower.
    if pending:
        await asyncio.wait(pending)
    # Read EVERY outcome, not just the winner's: an exception nobody
    # retrieves is exactly the bare traceback this exists to stop. `done`
    # comes first because the pump that finished on its own is the one that
    # knows why the bridge ended.
    failures: list[BaseException] = []
    for task in (*done, *pending):
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None:
            failures.append(exc)
    if failures:
        raise failures[0]


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
    client = web.WebSocketResponse(protocols=protocols or ("tty",),
                                   heartbeat=WS_HEARTBEAT_S)
    await client.prepare(request)

    session: aiohttp.ClientSession = request.app["ttyd_session"]
    try:
        async with session.ws_connect(
            url.replace("http://", "ws://", 1),
            protocols=protocols or ("tty",),
            headers=_upstream_headers(request),
            heartbeat=WS_HEARTBEAT_S,
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
            await _settle(done, pending)
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
            headers=_upstream_headers(request),
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
