#!/usr/bin/env python3
"""
BRigt ingress panel — aiohttp API + static asset server.

Routes
------
GET  /                      — panel HTML
GET  /style.css, /app.js    — static assets
GET  /favicon.svg           — the BRigt tile
GET  /api/health            — liveness for the Supervisor watchdog (public)
GET  /api/status            — version + options snapshot for the UI

Runs as the `brigt` user on 0.0.0.0:8095. The HA Supervisor proxies the
ingress URL into /api/hassio_ingress/<token>/...; we therefore use only
relative links in the HTML and let aiohttp serve at /.

Why 0.0.0.0 is not the same as "public"
---------------------------------------
This add-on sets `host_network: true` (LIFX discovery is a UDP broadcast,
and cue latency is the product), so binding 0.0.0.0:8095 puts this server
on the *host's* network — reachable from every device on the LAN, with no
Home Assistant login in front of it. Ingress is a proxy, not a gate: it
authenticates its own callers and has no say over anyone who types the IP
directly. That is the exposure Home Assistant documented in
GHSA-gh5m-4m97-c95h, and it is why the `_lan_gate` middleware below allows
the Supervisor's own networks and loopback and nothing else — except
`/api/health`, which the Supervisor watchdog polls and which reports
liveness only.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import time
from pathlib import Path

from aiohttp import web

HERE = Path(__file__).resolve().parent
STATIC = HERE
DATA_DIR = Path(os.environ.get("BRIGT_STATE", "/data"))
ENV_FILE = Path(os.environ.get("BRIGT_ENV_FILE", "/data/.brigt_env"))
ADDON_VERSION = os.environ.get("ADDON_VERSION", "dev")
SUPERVISOR_API_URL = os.environ.get("SUPERVISOR_API_URL", "http://supervisor")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

BIND_HOST = "0.0.0.0"
BIND_PORT = 8095

log = logging.getLogger("brigt.panel")


# ---------------------------------------------------------------------------
# LAN gate — who is allowed to reach the panel
# ---------------------------------------------------------------------------
# The Supervisor proxies ingress requests from its own container, so a
# legitimate panel request arrives from the hassio docker network. These are
# the ranges the Supervisor documents for it, plus loopback for anything the
# add-on calls on itself.
_ALLOWED_NETWORKS = tuple(
    ipaddress.ip_network(cidr) for cidr in (
        "172.30.32.0/23",          # hassio bridge (Supervisor, ingress)
        "fd0c:ac1e:2100::/48",     # hassio bridge, IPv6
        "127.0.0.0/8",
        "::1/128",
    )
)

# Paths that answer anyone. Health is a liveness bit for the Supervisor
# watchdog and exposes no state.
_PUBLIC_PREFIXES = ("/api/health",)


def _peer_ip(request: web.Request) -> str | None:
    """Source address of the connection itself.

    Deliberately NOT X-Forwarded-For: that header is set by the client on a
    direct connection, so trusting it would let a LAN caller claim to be the
    Supervisor and walk straight through this gate.
    """
    peer = request.transport.get_extra_info("peername") if request.transport else None
    # A TCP peername is (host, port[, ...]); a unix-socket one is a string
    # path, and a closed transport gives None. Only the tuple form carries
    # an address — anything else has no address to trust, and `_is_trusted`
    # turns that into a refusal rather than an exception in the middleware.
    if not isinstance(peer, tuple) or not peer:
        return None
    host = peer[0]
    if not isinstance(host, str):
        return None
    # IPv4-mapped IPv6 (::ffff:192.168.1.5) — compare as the IPv4 it is.
    if host.startswith("::ffff:"):
        host = host[len("::ffff:"):]
    return host


def _is_trusted(host: str | None) -> bool:
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in _ALLOWED_NETWORKS)


def _for_log(value: str, limit: int = 256) -> str:
    """Flatten caller-supplied text to a single bounded log line.

    aiohttp hands us the path percent-decoded, so `%0a` arrives as a real
    newline and a caller could otherwise write its own lines into the log.
    """
    flat = "".join(ch if ch.isprintable() else "?" for ch in str(value))
    return flat[:limit]


@web.middleware
async def _lan_gate(request: web.Request, handler):
    """Refuse requests that did not come through the Supervisor."""
    if any(request.path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await handler(request)

    host = _peer_ip(request)
    if _is_trusted(host):
        return await handler(request)

    log.warning(
        "refused %s %s from %s — the panel is reachable on the LAN because "
        "host_network is on, but only Home Assistant may drive it",
        _for_log(request.method), _for_log(request.path), _for_log(host or "unknown"),
    )
    return web.json_response(
        {"error": "forbidden: open this panel from Home Assistant"},
        status=403,
    )


# ---------------------------------------------------------------------------
# Options snapshot
# ---------------------------------------------------------------------------
def _options_from_env() -> dict:
    """The options run.sh exported, read back from /data/.brigt_env.

    The env file is the one route an add-on option has into a process
    started under with-contenv; the panel inherits the exports directly but
    reads the file so a restarted panel and a fresh one agree.
    """
    options = {
        "music_folder": os.environ.get("BRIGT_MUSIC_FOLDER", "/media/music"),
        "director_mode": os.environ.get("BRIGT_DIRECTOR_MODE", "auto"),
        "log_level": os.environ.get("BRIGT_LOG_LEVEL", "info"),
    }
    try:
        for line in ENV_FILE.read_text().splitlines():
            if not line.startswith("export BRIGT_"):
                continue
            key, _, raw = line[len("export "):].partition("=")
            value = raw.strip().strip("'")
            name = key[len("BRIGT_"):].lower()
            if name in options:
                options[name] = value
    except OSError:
        pass
    return options


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
async def h_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "uptime_s": int(time.monotonic() - _STARTED)})


async def h_status(request: web.Request) -> web.Response:
    return web.json_response({
        "version": ADDON_VERSION,
        "options": _options_from_env(),
    })


def _render_index_html() -> str:
    html = (STATIC / "index.html").read_text()
    return html.replace("__VERSION__", ADDON_VERSION)


async def h_index(request: web.Request) -> web.Response:
    return web.Response(
        text=_render_index_html(),
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


def _static_file(name: str, content_type: str):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(
            text=(STATIC / name).read_text(),
            content_type=content_type,
        )
    return handler


_STARTED = time.monotonic()


def build_app() -> web.Application:
    app = web.Application(middlewares=[_lan_gate])
    app.router.add_get("/api/health", h_health)
    app.router.add_get("/", h_index)
    app.router.add_get("/style.css", _static_file("style.css", "text/css"))
    app.router.add_get("/app.js", _static_file("app.js", "application/javascript"))
    app.router.add_get("/favicon.svg", _static_file("favicon.svg", "image/svg+xml"))
    app.router.add_get("/api/status", h_status)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    log.info("BRigt panel v%s listening on %s:%s", ADDON_VERSION, BIND_HOST, BIND_PORT)
    web.run_app(build_app(), host=BIND_HOST, port=BIND_PORT,
                access_log=None, print=None)


if __name__ == "__main__":
    main()
