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
import re
import shutil
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = os.environ.get(
    "BRUH_MC_SCRIPTS_DIR",
    "/opt/bruh-mc/scripts",
)
for _candidate in (_SCRIPTS_DIR, str(Path(__file__).resolve().parent.parent / "scripts")):
    if _candidate and _candidate not in sys.path:
        sys.path.insert(0, _candidate)
from rcon_client import Rcon  # noqa: E402
import console_reply  # noqa: E402
import skins  # noqa: E402

PANEL_STATE = Path(os.environ.get("MC_PANEL_STATE", "/data/panel"))
SHARED = Path("/config/.bruh_minecraft")
REQ_DIR = SHARED / "requests"
RES_DIR = SHARED / "responses"
SCRIPTS_DIR = Path("/opt/bruh-mc/scripts")

# The add-on browser lives in the panel, and the bridge asks it over
# loopback — which the panel's LAN gate lets through — rather than holding a
# second copy of Modrinth search, the hash check and the per-world record.
PANEL_URL = os.environ.get("BRUH_MC_PANEL_URL", "http://127.0.0.1:8099")

RCON_HOST = "127.0.0.1"
RCON_PORT = 25575

# The server's console (the launcher's copy of stdout): where a plugin's
# answer to a console command goes when it sends RCON nothing.
CONSOLE_LOG = Path(os.environ.get("MC_CONSOLE_LOG", str(PANEL_STATE / "console.log")))

# The server's folder: SkinsRestorer's record of a player is under it.
SERVER_DIR = Path(os.environ.get("MC_SERVER_DIR", "/config/minecraft"))

MIRROR_FILES = ("stats.json", "state.json", "players.json", "world.json")
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
        with Rcon(RCON_HOST, pw, port=RCON_PORT, timeout=5) as r:
            return r.command(command)

    return await asyncio.to_thread(_exec)


async def _rcon_answer(command: str) -> str:
    """RCON's reply, or the console lines the server wrote right after the
    command when RCON said nothing (SkinsRestorer, Skript and many other
    plugins answer the console, not the sender): scripts/console_reply.py."""
    pw = _rcon_password()

    def _exec(cmd: str) -> str:
        with Rcon(RCON_HOST, pw, port=RCON_PORT, timeout=5) as r:
            return r.command(cmd)

    return await asyncio.to_thread(console_reply.command, _exec, command, CONSOLE_LOG)


async def skin(skin_value: Any, player: Any, cmd: str | None = None) -> dict[str, Any]:
    """Put a skin on one player and say whether it went on, in
    SkinsRestorer's words (scripts/skins.py: its answer comes seconds
    after RCON returns)."""
    pw = _rcon_password()

    def _exec(c: str) -> str:
        with Rcon(RCON_HOST, pw, port=RCON_PORT, timeout=5) as r:
            return r.command(c)

    try:
        out = await asyncio.to_thread(skins.apply, _exec, skin_value, player, CONSOLE_LOG,
                                      SERVER_DIR, cmd=cmd)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if out["worked"] is False:
        return {"ok": False, "worked": False, "reply": out["reply"],
                "error": f"SkinsRestorer did not change the skin: {out['reply']}"}
    answer = {"ok": True, "worked": out["worked"], "reply": out["reply"],
              "player": str(player)}
    if out["worked"] is None:
        answer["note"] = (f"SkinsRestorer said nothing within {skins.SKIN_WAIT_S:.0f} s, so it "
                          "is not known whether the skin went on (is SkinsRestorer installed?).")
    return answer


_LIST_RE = re.compile(
    r"There are (?P<online>\d+) of a max(?: of)? (?P<max>\d+) players online:? ?(?P<players>.*)"
)


def parse_list(reply: str) -> dict[str, Any] | None:
    """`minecraft:list`'s answer as numbers and names, or None if unreadable.

    The same pattern the stats collector reads; `§` colour codes are
    stripped first, because a plugin that colours names would otherwise
    hand a caller `§aSteve` as a player it can never target.
    """
    plain = re.sub(r"§.", "", reply or "")
    m = _LIST_RE.search(plain)
    if not m:
        return None
    return {
        "online": int(m.group("online")),
        "max": int(m.group("max")),
        "players": [p.strip() for p in m.group("players").split(",") if p.strip()],
    }


def _read_json(name: str) -> dict[str, Any]:
    try:
        data = json.loads((PANEL_STATE / name).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def status() -> dict[str, Any]:
    """Who is on, asked of the server now, beside the last collected stats.

    A server that is not answering is still an answer — `reachable: false`
    with the last state the collector wrote — because "the server is down"
    is exactly what somebody asking is trying to find out, and an error
    would hide it.
    """
    out: dict[str, Any] = {"ok": True, "state": _read_json("state.json"),
                           "stats": _read_json("stats.json")}
    try:
        parsed = parse_list(await _rcon("minecraft:list"))
    except Exception as exc:  # noqa: BLE001 — offline is a state, not a failure
        parsed = None
        out["note"] = f"The server did not answer RCON: {exc}"
    out["reachable"] = parsed is not None
    out.update(parsed or {"online": 0, "max": 0, "players": []})
    return out


def _panel(method: str, path: str, body: dict | None = None, timeout: float = 150) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        PANEL_URL + path, data=data, method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            answer = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        try:
            answer = json.loads(exc.read().decode() or "{}")
        except ValueError:
            answer = {}
        return {"ok": False, "error": answer.get("error") or f"The panel answered HTTP {exc.code}."}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"The panel did not answer: {exc}"}
    if isinstance(answer, dict) and answer.get("error"):
        return {"ok": False, "error": answer["error"]}
    return {"ok": True, **(answer if isinstance(answer, dict) else {"result": answer})}


async def addons(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "addon_list":
        return await asyncio.to_thread(_panel, "GET", "/api/addons")
    if kind == "addon_search":
        query = urllib.parse.urlencode({
            "kind": str(payload.get("kind") or ""), "q": str(payload.get("query") or ""),
            "offset": str(int(payload.get("offset") or 0))})
        return await asyncio.to_thread(_panel, "GET", f"/api/addons/search?{query}")
    if kind == "addon_install":
        return await asyncio.to_thread(_panel, "POST", "/api/addons/install",
                                       {"id": str(payload.get("id") or ""),
                                        "kind": str(payload.get("kind") or "")})
    pid = urllib.parse.quote(str(payload.get("id") or ""), safe="")
    return await asyncio.to_thread(_panel, "DELETE", f"/api/addons/{pid}")


async def scripts(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Skript scripts and data pack functions in the running world, written by
    the panel (panel/worldscripts.py), which checks every name and owns the
    record of what was written."""
    if kind == "script_list":
        return await asyncio.to_thread(_panel, "GET", "/api/scripts", None, 15)
    if kind == "script_write":
        return await asyncio.to_thread(_panel, "POST", "/api/scripts", {
            "kind": str(payload.get("kind") or ""), "name": str(payload.get("name") or ""),
            "content": payload.get("content"), "by": str(payload.get("by") or "")}, 60)
    path = "/api/scripts/{}/{}".format(
        urllib.parse.quote(str(payload.get("kind") or ""), safe=""),
        urllib.parse.quote(str(payload.get("name") or ""), safe=""))
    return await asyncio.to_thread(_panel, "DELETE", path, None, 60)


_JOB_ID = re.compile(r"^[0-9]{8}-[0-9a-f]{6}$")
_JOB_FIELDS = ("title", "part", "status", "progress", "bounds", "started_at",
               "finished_at", "image", "notes", "by")


async def world(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The world's state and the build log, asked of the panel.

    The panel holds the one collector and the one writer of the build log
    (panel/mcworld.py); this only carries the request there.
    """
    if kind == "world":
        return await asyncio.to_thread(_panel, "GET", "/api/world", None, 15)
    if kind == "builds_list":
        query = urllib.parse.urlencode({k: str(payload[k]) for k in ("status", "limit")
                                        if payload.get(k)})
        return await asyncio.to_thread(_panel, "GET", "/api/builds" + (f"?{query}" if query else ""),
                                       None, 15)
    job_id = str(payload.get("id") or "")
    if job_id and not _JOB_ID.match(job_id):
        return {"ok": False, "error": f"'{job_id}' is not a build job id."}
    if kind == "build_save":
        body = {k: payload[k] for k in _JOB_FIELDS if k in payload}
        if job_id:
            return await asyncio.to_thread(_panel, "PATCH", f"/api/builds/{job_id}", body, 30)
        return await asyncio.to_thread(_panel, "POST", "/api/builds", body, 30)
    if kind == "build_delete":
        if not job_id:
            return {"ok": False, "error": "Name the job to delete (its id)."}
        return await asyncio.to_thread(_panel, "DELETE", f"/api/builds/{job_id}", None, 15)
    return {"ok": False, "error": f"unknown kind '{kind}'"}


COMPANION_KINDS = ("companion", "companion_identity", "companion_say", "companion_appear",
                   "companion_ask", "companion_build", "companion_edit", "companion_look",
                   "companion_undo", "companion_zone", "companion_progress", "companion_bar",
                   "companion_spyglass", "companion_thought", "companion_journal", "atlas", "atlas_room", "atlas_label",
                   "companion_legacy", "companion_legacy_retire", "rename_world")
_JOB = re.compile(r"^[A-Za-z0-9_.:\-]{1,40}$")


def _pick(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: payload[k] for k in keys if k in payload}


async def companion(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The companion's hands and the world's name, asked of the panel
    (panel/companion.py holds the one implementation; this only carries
    the request there)."""
    if kind == "companion":
        return await asyncio.to_thread(_panel, "GET", "/api/companion", None, 15)
    if kind == "companion_identity":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/identity", _pick(
            payload, ("name", "colour", "active", "by", "model")), 15)
    if kind == "companion_say":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/say", _pick(
            payload, ("to", "message", "name", "colour", "chime", "by")), 15)
    if kind == "companion_appear":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/appear", _pick(
            payload, ("player", "seconds", "kind", "name", "colour", "chime", "text", "by")), 15)
    if kind == "companion_ask":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/ask", _pick(
            payload, ("player", "question", "options", "person", "name", "by")), 15)
    if kind == "companion_build":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/build", _pick(
            payload, ("blocks", "player", "dimension", "title", "name", "by")), 60)
    if kind == "companion_edit":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/edit", _pick(
            payload, ("blocks", "fills", "shapes", "player", "dimension", "title", "name", "by",
                      "job")), 170)
    if kind == "companion_progress":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/progress", _pick(
            payload, ("to", "text", "percent", "colour")), 15)
    if kind == "companion_bar":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/bar", _pick(
            payload, ("player", "key", "text", "percent", "end")), 15)
    if kind == "companion_spyglass":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/spyglass", _pick(
            payload, ("player", "name")), 15)
    if kind == "companion_thought":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/thought", _pick(
            payload, ("player", "text", "state", "key", "title", "percent", "name", "colour")),
            15)
    if kind == "companion_journal":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/journal", _pick(
            payload, ("player", "name")), 15)
    if kind == "atlas":
        return await asyncio.to_thread(_panel, "POST", "/api/atlas", _pick(
            payload, ("player", "x", "y", "z", "dimension", "radius", "query")), 55)
    if kind == "atlas_room":
        return await asyncio.to_thread(_panel, "POST", "/api/atlas/room", _pick(
            payload, ("player", "room", "x", "y", "z", "dimension")), 55)
    if kind == "atlas_label":
        return await asyncio.to_thread(_panel, "POST", "/api/atlas/labels", _pick(
            payload, ("room", "building", "x", "y", "z", "dimension", "name", "by")), 55)
    if kind == "companion_look":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/look", _pick(
            payload, ("player", "x", "y", "z", "size", "dimension")), 55)
    if kind == "companion_undo" and payload.get("job"):
        job = str(payload["job"])
        if not _JOB.match(job):
            return {"ok": False, "error": f"'{job}' is not a job id."}
        return await asyncio.to_thread(_panel, "POST", f"/api/companion/jobs/{job}/undo", {}, 120)
    if kind == "companion_undo":
        action_id = str(payload.get("id") or "last")
        if action_id != "last" and not _JOB_ID.match(action_id):
            return {"ok": False, "error": f"'{action_id}' is not one of the companion's action ids."}
        return await asyncio.to_thread(_panel, "POST", f"/api/companion/actions/{action_id}/undo",
                                       {}, 60)
    if kind == "companion_zone":
        if payload.get("delete"):
            name = urllib.parse.quote(str(payload.get("name") or ""), safe="")
            return await asyncio.to_thread(_panel, "DELETE", f"/api/companion/zones/{name}",
                                           None, 15)
        return await asyncio.to_thread(_panel, "POST", "/api/companion/zones", _pick(
            payload, ("name", "x", "z", "radius", "dimension", "protect", "kind")), 15)
    if kind == "companion_legacy":
        return await asyncio.to_thread(_panel, "GET", "/api/companion/legacy", None, 15)
    if kind == "companion_legacy_retire":
        return await asyncio.to_thread(_panel, "POST", "/api/companion/legacy/retire", {}, 15)
    if kind == "rename_world":
        # Renaming the active world restarts the add-on, this bridge with it,
        # once the panel has answered.
        return await asyncio.to_thread(_panel, "POST", "/api/world/rename",
                                       {"name": str(payload.get("name") or "")}, 150)
    return {"ok": False, "error": f"unknown kind '{kind}'"}


async def handle(request: dict[str, Any]) -> dict[str, Any]:
    kind = request.get("kind", "")
    payload = request.get("payload", {}) or {}
    try:
        if kind == "command":
            command = str(payload.get("command", "")).strip().lstrip("/")
            if not command:
                return {"ok": False, "error": "No command given."}
            sr = skins.COMMAND.match(command)
            if sr:
                # SkinsRestorer answers seconds later: wait for its word (#760).
                out = await skin(None, sr.group("player"), cmd=command)
                return {"ok": True, "reply": out.get("reply") or out.get("error") or ""}
            # A check's `run say ok` would be in every player's chat (#761).
            reply = await _rcon_answer(console_reply.quiet_probe(command.replace("\n", " ")))
            return {"ok": True, "reply": reply}

        if kind == "skin":
            return await skin(payload.get("skin"), payload.get("player"))

        if kind == "status":
            return await status()

        if kind in ("addon_list", "addon_search", "addon_install", "addon_remove"):
            return await addons(kind, payload)

        if kind in ("script_list", "script_write", "script_remove"):
            return await scripts(kind, payload)

        if kind in ("world", "builds_list", "build_save", "build_delete"):
            return await world(kind, payload)

        if kind in COMPANION_KINDS:
            return await companion(kind, payload)

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
            text = out.decode(errors="replace")[-4096:]
            if proc.returncode == 0:
                return {"ok": True, "output": text}
            # A failed backup says why: the last line the script wrote.
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            return {"ok": False, "output": text,
                    "error": "The backup did not finish: "
                             + (lines[-2] if len(lines) > 1 and lines[-1].endswith("FAILED") else
                                (lines[-1] if lines else f"backup.sh exited {proc.returncode}"))}

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
