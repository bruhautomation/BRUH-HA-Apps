#!/usr/bin/env python3
"""Watches /config/.bruh_minecraft/requests/ for JSON request files written by
the companion HA integration, dispatches them, and writes a response file back
to /config/.bruh_minecraft/responses/<id>.json.

Also mirrors /data/panel/{stats,state,players}.json into /config/.bruh_minecraft/
every few seconds so HA Core can read them.
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import Any

from mcrcon import MCRcon

PANEL_STATE = Path(os.environ.get("MC_PANEL_STATE", "/data/panel"))
SHARED = Path("/config/.bruh_minecraft")
REQ_DIR = SHARED / "requests"
RES_DIR = SHARED / "responses"
SCRIPTS_DIR = Path("/opt/bruh-mc/scripts")

RCON_HOST = "127.0.0.1"
RCON_PORT = 25575

MIRROR_FILES = ("stats.json", "state.json", "players.json")
MIRROR_INTERVAL = 5
POLL_INTERVAL = 0.5


def _log(msg: str) -> None:
    print(f"[ha-bridge {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _rcon_password() -> str:
    secret = PANEL_STATE / "rcon.secret"
    if secret.is_file():
        return secret.read_text().strip()
    return os.environ.get("RCON_PASSWORD", "")


def _write_response(req_id: str, payload: dict[str, Any]) -> None:
    tmp = RES_DIR / f"{req_id}.json.tmp"
    dst = RES_DIR / f"{req_id}.json"
    tmp.write_text(json.dumps(payload))
    tmp.replace(dst)


async def _rcon(command: str) -> str:
    pw = _rcon_password()

    def _exec() -> str:
        with MCRcon(RCON_HOST, pw, port=RCON_PORT, timeout=5) as r:
            return r.command(command)

    return await asyncio.to_thread(_exec)


async def handle(request: dict[str, Any]) -> dict[str, Any]:
    kind = request.get("kind", "")
    payload = request.get("payload", {}) or {}
    try:
        if kind == "command":
            reply = await _rcon(str(payload.get("command", "")).strip())
            return {"ok": True, "reply": reply}

        if kind == "say":
            msg = str(payload.get("message", "")).strip().replace("\n", " ")[:256]
            reply = await _rcon(f"say {msg}")
            return {"ok": True, "reply": reply}

        if kind == "backup":
            proc = await asyncio.create_subprocess_exec(
                str(SCRIPTS_DIR / "backup.sh"),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            out, _ = await proc.communicate()
            return {"ok": proc.returncode == 0, "output": out.decode(errors="replace")[-4096:]}

        if kind == "restart":
            try:
                await _rcon("save-all flush")
                await _rcon("stop")
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
            return {"ok": True}

        if kind == "stop":
            (PANEL_STATE / "no_restart").write_text("1")
            try:
                await _rcon("save-all flush")
                await _rcon("stop")
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}
            return {"ok": True}

        if kind == "player_action":
            name = str(payload.get("name", ""))
            action = str(payload.get("action", ""))
            mapping = {
                "op": f"op {name}",
                "deop": f"deop {name}",
                "kick": f"kick {name}",
                "ban": f"ban {name}",
                "pardon": f"pardon {name}",
                "whitelist_add": f"whitelist add {name}",
                "whitelist_remove": f"whitelist remove {name}",
            }
            cmd = mapping.get(action)
            if not cmd:
                return {"ok": False, "error": "unknown action"}
            reply = await _rcon(cmd)
            return {"ok": True, "reply": reply}

        return {"ok": False, "error": f"unknown kind '{kind}'"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


async def request_loop() -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    RES_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            items = sorted(REQ_DIR.glob("*.json"))
        except OSError:
            items = []
        for path in items:
            try:
                data = json.loads(path.read_text())
            except Exception as exc:  # noqa: BLE001
                _log(f"bad request {path.name}: {exc}")
                path.unlink(missing_ok=True)
                continue
            req_id = str(data.get("id", path.stem))
            _log(f"request {data.get('kind')} id={req_id[:8]}")
            try:
                result = await handle(data)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc)}
            _write_response(req_id, result)
            path.unlink(missing_ok=True)
        await asyncio.sleep(POLL_INTERVAL)


async def mirror_loop() -> None:
    SHARED.mkdir(parents=True, exist_ok=True)
    while True:
        for name in MIRROR_FILES:
            src = PANEL_STATE / name
            dst = SHARED / name
            if not src.is_file():
                continue
            try:
                if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                    continue
                shutil.copy2(src, dst)
            except Exception as exc:  # noqa: BLE001
                _log(f"mirror {name} failed: {exc}")
        await asyncio.sleep(MIRROR_INTERVAL)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(s, lambda: sys.exit(0))


async def main() -> None:
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)
    _log("starting request + mirror loops")
    await asyncio.gather(request_loop(), mirror_loop())


if __name__ == "__main__":
    asyncio.run(main())
