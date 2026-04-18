#!/usr/bin/env python3
"""Tail the Minecraft console log and auto-kick ghost sessions.

Problem:
    Bedrock clients (iOS especially) sometimes hang during the Geyser
    login handshake. The user force-quits the app and retries, but Paper
    still has their previous connection registered as "online" — so the
    retry is rejected with "You are already connected to this server!"
    and stays rejected until Geyser's ~60-90s RakNet keepalive fires.

Fix:
    Watch the console log for Paper's duplicate-login rejection. Extract
    the offending player name. Fire `/kick <name>` over RCON to remove
    the ghost immediately. The user's next retry now succeeds because
    the slot is free.

Example log line (Paper 1.21.x):
    [Server thread/INFO]: com.mojang.authlib.GameProfile@1a2b[id=...,
      name=Kid1, properties={}] (/192.168.1.42:54321) lost connection:
      You are already connected to this server!

This script runs as a lightweight daemon alongside the stats collector.
Gated on $AUTO_KICK_GHOST_SESSIONS=true so it can be switched off via
the add-on option.
"""
from __future__ import annotations

import os
import re
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rcon_client import Rcon  # noqa: E402

RCON_HOST = os.environ.get("RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
PANEL_STATE = Path(os.environ.get("MC_PANEL_STATE", "/data/panel"))
CONSOLE_LOG = Path(os.environ.get("MC_CONSOLE_LOG", str(PANEL_STATE / "console.log")))

# Match Paper's duplicate-login rejection. The player name is inside
# GameProfile@HASH[..., name=X, ...]. Paper prints two variants:
#
#   [Server thread/INFO]: com.mojang.authlib.GameProfile@ff[...,name=X,
#     properties={}] (/192.168.1.42:54321) lost connection: You are
#     already connected to this server!
#
#   [Server thread/INFO]: Disconnecting com.mojang.authlib.GameProfile
#     [id=uuid,name=X,properties={}]: You are already connected to
#     this server!
#
# Both have name=X and "You are already connected to this server" on
# the same line. The error phrase is specific enough to anchor on
# without also requiring "lost connection" / "Disconnecting" — those
# words appear in opposite orders in the two variants.
DUPLICATE_LOGIN_RE = re.compile(
    r"name=(?P<name>[A-Za-z0-9_\.]{1,32})"
    r"[^\n]*?You are already connected to this server",
)

# Rate-limit kicks per name so we don't flap if Paper emits the message
# repeatedly for the same session. 10 seconds is long enough for the
# kick to take effect and the user's retry to succeed.
KICK_COOLDOWN_SECONDS = 10


def _log(msg: str) -> None:
    print(f"[ghost-watcher {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _rcon_password() -> str:
    env = os.environ.get("RCON_PASSWORD")
    if env:
        return env
    secret = PANEL_STATE / "rcon.secret"
    if secret.is_file():
        return secret.read_text().strip()
    return ""


def kick(name: str) -> str:
    password = _rcon_password()
    if not password:
        return "no rcon password available"
    try:
        with Rcon(RCON_HOST, password, port=RCON_PORT, timeout=5) as r:
            return r.command(f"kick {name} ghost session cleared")
    except Exception as exc:  # noqa: BLE001 — surface all failures
        return f"rcon failed: {exc}"


def tail(path: Path):
    """Generator yielding new lines appended to `path`, handling log
    rotation (truncation resets our position)."""
    last_size = 0
    if path.is_file():
        last_size = path.stat().st_size
    buffer = ""
    while True:
        try:
            if not path.is_file():
                time.sleep(1.0)
                continue
            size = path.stat().st_size
            if size < last_size:
                # log rotated
                last_size = 0
                buffer = ""
            if size > last_size:
                with path.open("r", errors="replace") as f:
                    f.seek(last_size)
                    chunk = f.read(size - last_size)
                last_size = size
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    yield line
            time.sleep(0.5)
        except (OSError, IOError):
            time.sleep(2.0)


def main() -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    if os.environ.get("AUTO_KICK_GHOST_SESSIONS", "true").lower() not in ("1", "true", "yes"):
        _log("auto_kick_ghost_sessions is disabled; exiting")
        return 0

    _log(f"Tailing {CONSOLE_LOG} for duplicate-login kicks")
    cooldown: dict[str, float] = {}

    for line in tail(CONSOLE_LOG):
        m = DUPLICATE_LOGIN_RE.search(line)
        if not m:
            continue
        name = m.group("name")
        now = time.monotonic()
        last = cooldown.get(name, 0)
        if now - last < KICK_COOLDOWN_SECONDS:
            continue
        cooldown[name] = now
        _log(f"Detected ghost session for '{name}' — kicking via RCON")
        reply = kick(name)
        _log(f"  -> {reply}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
