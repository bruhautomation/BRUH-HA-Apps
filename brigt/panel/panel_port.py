#!/usr/bin/env python3
"""Which port the panel serves on — asked once, answered for everyone.

`host_network: true` means the panel binds a REAL host port, and a port
number written into config.yaml is a number some other service on somebody's
box may already own. BRigt shipped 8095 — picked only because BRUH Minecraft
already owns 8099 — and met exactly that on a real install::

    OSError: [Errno 98] error while attempting to bind on address
    ('0.0.0.0', 8095): address in use

...on every boot, forever: the panel died, `run.sh`'s `wait` returned, the
container exited, the Supervisor restarted it, and the next attempt asked the
same host for the same taken port. A guard that refuses has to change the
next attempt, and a hardcoded port cannot change anything.

So config.yaml asks for `ingress_port: 0`, which is what Home Assistant
documents for host-network add-ons: the Supervisor picks a free host port and
the add-on reads it back over the API. Three processes need that answer —
`run.sh` (which logs and announces it), the panel (which binds it) and the HA
bridge (which posts show commands to it) — and a second copy of the lookup is
a second answer waiting to disagree, which is a bridge posting into nothing.
So it is resolved here and nowhere else.

Order: `BRIGT_PANEL_PORT` first (run.sh resolved it once and exported it into
the process tree *and* into /data/.brigt_env, the only route an answer has
into a `with-contenv` child), then the Supervisor's own answer for this
add-on, then `DEFAULT_PORT` for a dev checkout with no Supervisor behind it.
The default is a fallback for a machine that cannot be asked — never a claim
about which port is free.
"""
from __future__ import annotations

import errno
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.request

# Only reached when nothing can be asked: `podman run` on a laptop, or the
# tests. On a real install the Supervisor's answer wins before this is read.
DEFAULT_PORT = 8095

ENV_VAR = "BRIGT_PANEL_PORT"
SUPERVISOR_API_URL = os.environ.get("SUPERVISOR_API_URL", "http://supervisor")

# Long enough to survive a busy Supervisor, short enough that a wedged one
# does not hold the whole add-on's startup.
SUPERVISOR_TIMEOUT = 10

log = logging.getLogger("brigt.panel.port")


class PortInUse(OSError):
    """The port we must serve on is held by something else on this host."""


def _valid(value: object) -> int | None:
    """A port we could actually bind, or None.

    0 is what config.yaml *asks* with and never what the Supervisor answers,
    so it reads here as "no answer yet" rather than "bind an ephemeral port"
    — a panel on a port the Supervisor does not know about is a panel ingress
    cannot reach.
    """
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def from_env() -> int | None:
    """The port run.sh already resolved, if this process is one of its
    children."""
    return _valid(os.environ.get(ENV_VAR))


def from_supervisor(timeout: int = SUPERVISOR_TIMEOUT) -> int | None:
    """Ask the Supervisor which port it assigned this add-on's ingress.

    `hassio_api: true` is enough — an add-on may always read its own info.
    Every failure answers None: no token, no Supervisor, a timeout, a body
    that is not what we expect. A caller with no answer falls back; a caller
    handed a wrong answer binds the wrong port.
    """
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return None

    request = urllib.request.Request(
        f"{SUPERVISOR_API_URL}/addons/self/info",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode() or "{}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        log.warning("Could not ask the Supervisor for the ingress port: %s", exc)
        return None

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None
    return _valid(data.get("ingress_port"))


def resolve() -> int:
    """The one answer, in the order that keeps every process agreeing."""
    return from_env() or from_supervisor() or DEFAULT_PORT


def bind(host: str, port: int, *, attempts: int = 5,
         delay: float = 2.0) -> socket.socket:
    """A bound listening socket, or a `PortInUse` that says what to do.

    The retry is for one case only: our own predecessor. A watchdog restart
    tears down a panel that stopped answering, and a wedged process can still
    be holding the socket for a moment after the new container starts. Any
    other holder is not going to let go, which is why this ends in a sentence
    a person can act on rather than the traceback that shipped.
    """
    last: OSError | None = None
    for attempt in range(1, max(1, attempts) + 1):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as exc:
            sock.close()
            if exc.errno != errno.EADDRINUSE:
                raise
            last = exc
            if attempt < attempts:
                log.warning(
                    "Port %s is still held by something; retrying in %.0fs "
                    "(%d/%d)", port, delay, attempt, attempts)
                time.sleep(delay)
            continue
        return sock

    raise PortInUse(
        errno.EADDRINUSE,
        f"Something else on this machine already owns port {port}. BRigt runs "
        f"with host_network, so that is a port on the HOST, not one inside "
        f"the container. Free it and restart BRigt.",
    ) from last
