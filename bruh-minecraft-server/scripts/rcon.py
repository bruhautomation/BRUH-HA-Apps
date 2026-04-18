#!/usr/bin/env python3
"""Send a single RCON command to the local Minecraft server and print the reply.

Reads the RCON password from $RCON_PASSWORD if set, otherwise from
$MC_PANEL_STATE/rcon.secret, otherwise exits 2.

Usage:
    rcon.py "<command with args>"
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from mcrcon import MCRcon

RCON_HOST = os.environ.get("RCON_HOST", "127.0.0.1")
RCON_PORT = int(os.environ.get("RCON_PORT", "25575"))
PANEL_STATE = Path(os.environ.get("MC_PANEL_STATE", "/data/panel"))


def read_password() -> str:
    pw = os.environ.get("RCON_PASSWORD")
    if pw:
        return pw
    secret = PANEL_STATE / "rcon.secret"
    if secret.is_file():
        return secret.read_text().strip()
    print("[rcon] No RCON password found", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: rcon.py '<command>'", file=sys.stderr)
        return 64
    command = " ".join(sys.argv[1:])
    password = read_password()

    # Retry for up to 20s to tolerate the JVM still starting
    deadline = time.monotonic() + 20.0
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with MCRcon(RCON_HOST, password, port=RCON_PORT, timeout=5) as rcon:
                reply = rcon.command(command)
                print(reply)
                return 0
        except Exception as exc:  # noqa: BLE001 — we surface any failure
            last_err = exc
            time.sleep(1.0)

    print(f"[rcon] failed: {last_err}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
