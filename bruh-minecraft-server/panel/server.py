#!/usr/bin/env python3
"""
BRUH Minecraft ingress panel — aiohttp API + static asset server.

Routes
------
GET  /                      — dashboard HTML
GET  /style.css, /app.js    — static assets
GET  /api/status            — current stats + state
GET  /api/players           — player list (JSON)
GET  /api/backups           — list backups (git commits + tar archives)
GET  /api/properties        — current server.properties
POST /api/properties        — update a managed key
POST /api/command           — run arbitrary RCON command
POST /api/say               — broadcast chat message (uses /say)
POST /api/player/<name>/<op|deop|kick|ban|pardon|whitelist_add|whitelist_remove>
POST /api/backup            — trigger a backup now
POST /api/restore/<ref>     — restore git commit or tar archive by name
POST /api/restart           — stop the server; run.sh auto-restarts
POST /api/stop              — graceful stop (clears auto-restart flag file)
GET  /api/logs/tail         — Server-Sent Events stream of console.log tail

Runs as the `minecraft` user on 0.0.0.0:8099. The HA supervisor proxies the
ingress URL into /api/hassio_ingress/<token>/...; we therefore use only
relative links in the HTML and let aiohttp serve at /.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

import aiofiles
from aiohttp import web
from mcrcon import MCRcon

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
STATIC = HERE
MC_SERVER_DIR = Path(os.environ.get("MC_SERVER_DIR", "/config/minecraft"))
MC_BACKUP_DIR = Path(os.environ.get("MC_BACKUP_DIR", "/config/minecraft-backups"))
MC_PANEL_STATE = Path(os.environ.get("MC_PANEL_STATE", "/data/panel"))
MC_CONSOLE_LOG = Path(os.environ.get("MC_CONSOLE_LOG", str(MC_PANEL_STATE / "console.log")))
MC_INPUT_FIFO = Path(os.environ.get("MC_INPUT_FIFO", "/tmp/mc-stdin.fifo"))
SCRIPTS_DIR = Path("/opt/bruh-mc/scripts")

RCON_HOST = "127.0.0.1"
RCON_PORT = 25575
BIND_HOST = "0.0.0.0"
BIND_PORT = 8099


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _rcon_password() -> str:
    secret = MC_PANEL_STATE / "rcon.secret"
    if secret.is_file():
        return secret.read_text().strip()
    return os.environ.get("RCON_PASSWORD", "")


def _read_json(path: Path, default: dict | list) -> dict | list:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return default


async def _rcon_command(command: str) -> str:
    password = _rcon_password()

    def _exec() -> str:
        with MCRcon(RCON_HOST, password, port=RCON_PORT, timeout=5) as r:
            return r.command(command)

    return await asyncio.to_thread(_exec)


def _read_properties() -> dict[str, str]:
    props: dict[str, str] = {}
    path = MC_SERVER_DIR / "server.properties"
    if not path.is_file():
        return props
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        props[key.strip()] = value
    return props


# Keys the panel is allowed to edit directly. Other keys require editing the
# add-on options to avoid surprising overrides.
EDITABLE_PROPS = {
    "motd",
    "difficulty",
    "gamemode",
    "max-players",
    "view-distance",
    "simulation-distance",
    "pvp",
    "allow-flight",
    "white-list",
    "enforce-whitelist",
    "spawn-protection",
    "enable-command-block",
    "online-mode",
    "hardcore",
}

VALID_PLAYER_NAME = re.compile(r"^[A-Za-z0-9_]{1,16}$")


# ---------------------------------------------------------------------------
# Routes: static
# ---------------------------------------------------------------------------
async def index(_: web.Request) -> web.Response:
    return web.FileResponse(STATIC / "index.html")


async def favicon(_: web.Request) -> web.Response:
    icon = STATIC / "favicon.svg"
    if icon.is_file():
        return web.FileResponse(icon)
    return web.Response(status=404)


# ---------------------------------------------------------------------------
# Routes: API — status / info
# ---------------------------------------------------------------------------
async def api_status(_: web.Request) -> web.Response:
    stats = _read_json(MC_PANEL_STATE / "stats.json", {})
    state = _read_json(MC_PANEL_STATE / "state.json", {})
    meta = _read_json(MC_SERVER_DIR / ".server-meta.json", {})
    launcher_pid = (MC_PANEL_STATE / "launcher.pid")
    running = launcher_pid.is_file()
    if running:
        try:
            pid = int(launcher_pid.read_text().strip())
            os.kill(pid, 0)
        except Exception:  # noqa: BLE001
            running = False
    return web.json_response({
        "running": running,
        "state": state,
        "stats": stats,
        "server_meta": meta,
    })


async def api_players(_: web.Request) -> web.Response:
    return web.json_response(_read_json(MC_PANEL_STATE / "players.json", {
        "players": [], "online": 0, "max": 0,
    }))


async def api_properties_get(_: web.Request) -> web.Response:
    props = _read_properties()
    safe = {k: v for k, v in props.items() if k != "rcon.password"}
    return web.json_response({"properties": safe, "editable": sorted(EDITABLE_PROPS)})


async def api_properties_post(request: web.Request) -> web.Response:
    body = await request.json()
    key = str(body.get("key", "")).strip()
    value = str(body.get("value", "")).strip()
    if key not in EDITABLE_PROPS:
        return web.json_response({"error": f"key '{key}' not editable"}, status=400)

    props = _read_properties()
    props[key] = value
    lines = [
        "# server.properties — managed by BRUH Minecraft Server add-on",
        "# Hand-edited keys not managed by the UI are preserved on restart.",
        f"# Last edited via panel: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
    ]
    lines.extend(f"{k}={props[k]}" for k in sorted(props))
    tmp = MC_SERVER_DIR / "server.properties.tmp"
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(MC_SERVER_DIR / "server.properties")

    # Live-apply a handful of keys via RCON where possible
    live_reply = None
    try:
        if key in ("difficulty",):
            live_reply = await _rcon_command(f"difficulty {value}")
        elif key == "gamemode":
            live_reply = await _rcon_command(f"defaultgamemode {value}")
        elif key in ("white-list", "enforce-whitelist"):
            live_reply = await _rcon_command(f"whitelist {'on' if value == 'true' else 'off'}")
    except Exception as exc:  # noqa: BLE001
        live_reply = f"live-apply failed: {exc}"
    return web.json_response({"ok": True, "live": live_reply})


# ---------------------------------------------------------------------------
# Routes: API — commands / player management
# ---------------------------------------------------------------------------
async def api_command(request: web.Request) -> web.Response:
    body = await request.json()
    command = str(body.get("command", "")).strip().lstrip("/")
    if not command:
        return web.json_response({"error": "command required"}, status=400)
    try:
        reply = await _rcon_command(command)
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response({"reply": reply})


async def api_say(request: web.Request) -> web.Response:
    body = await request.json()
    message = str(body.get("message", "")).strip()
    if not message:
        return web.json_response({"error": "message required"}, status=400)
    message = message.replace("\n", " ")[:256]
    reply = await _rcon_command(f"say {message}")
    return web.json_response({"reply": reply})


_PLAYER_ACTIONS = {
    "op": lambda n: f"op {n}",
    "deop": lambda n: f"deop {n}",
    "kick": lambda n: f"kick {n}",
    "ban": lambda n: f"ban {n}",
    "pardon": lambda n: f"pardon {n}",
    "whitelist_add": lambda n: f"whitelist add {n}",
    "whitelist_remove": lambda n: f"whitelist remove {n}",
}


async def api_player_action(request: web.Request) -> web.Response:
    name = request.match_info.get("name", "")
    action = request.match_info.get("action", "")
    if not VALID_PLAYER_NAME.match(name):
        return web.json_response({"error": "invalid name"}, status=400)
    cmd_factory = _PLAYER_ACTIONS.get(action)
    if not cmd_factory:
        return web.json_response({"error": "unknown action"}, status=400)
    try:
        reply = await _rcon_command(cmd_factory(name))
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response({"reply": reply})


# ---------------------------------------------------------------------------
# Routes: API — lifecycle / backups
# ---------------------------------------------------------------------------
async def api_restart(_: web.Request) -> web.Response:
    try:
        await _rcon_command("save-all flush")
        await _rcon_command("stop")
        return web.json_response({"ok": True, "note": "server stopping; run.sh will restart"})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)}, status=500)


async def api_stop(_: web.Request) -> web.Response:
    try:
        # Write flag to prevent auto-restart on next JVM exit
        (MC_PANEL_STATE / "no_restart").write_text("1")
        await _rcon_command("save-all flush")
        await _rcon_command("stop")
        return web.json_response({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)}, status=500)


async def api_backup(_: web.Request) -> web.Response:
    proc = await asyncio.create_subprocess_exec(
        str(SCRIPTS_DIR / "backup.sh"),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out_bytes, _ = await proc.communicate()
    return web.json_response({
        "ok": proc.returncode == 0,
        "output": out_bytes.decode("utf-8", "replace")[-4096:],
    })


async def api_backups_list(_: web.Request) -> web.Response:
    result: dict[str, list] = {"git": [], "archives": []}

    git_dir = MC_BACKUP_DIR / "git"
    if (git_dir / ".git").is_dir():
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(git_dir), "log",
            "--pretty=format:%H%x1f%ct%x1f%s",
            "-n", "100",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out_b, _ = await proc.communicate()
        for line in out_b.decode("utf-8", "replace").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3:
                result["git"].append({
                    "sha": parts[0], "ts": int(parts[1]), "subject": parts[2],
                })

    archives_dir = MC_BACKUP_DIR / "archives"
    if archives_dir.is_dir():
        for p in sorted(archives_dir.glob("world-*.tar.gz"), reverse=True):
            stat = p.stat()
            result["archives"].append({
                "name": p.name, "size": stat.st_size, "ts": int(stat.st_mtime),
            })
    return web.json_response(result)


async def api_restore(request: web.Request) -> web.Response:
    ref = request.match_info["ref"]
    # Accept either a git SHA (40 hex) or an archive basename
    if re.fullmatch(r"[0-9a-f]{7,40}", ref):
        return await _restore_from_git(ref)
    if re.fullmatch(r"world-[\w\-]+\.tar\.gz", ref):
        return await _restore_from_archive(ref)
    return web.json_response({"error": "unrecognised backup ref"}, status=400)


async def _restore_from_git(sha: str) -> web.Response:
    try:
        await _rcon_command("save-off")
        await _rcon_command("stop")
    except Exception:  # noqa: BLE001
        pass
    repo = MC_BACKUP_DIR / "git"
    level = os.environ.get("LEVEL_NAME", "world")
    for world in (level, f"{level}_nether", f"{level}_the_end"):
        src = repo / world
        dst = MC_SERVER_DIR / world
        if not src.exists():
            continue
        # Check out the requested sha so src reflects its state, then rsync
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo), "checkout", sha, "--", world,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        await proc.communicate()
        proc = await asyncio.create_subprocess_exec(
            "rsync", "-a", "--delete", f"{src}/", f"{dst}/",
        )
        await proc.communicate()
    # Always reset the working tree to HEAD so future backups stay linear
    await asyncio.create_subprocess_exec(
        "git", "-C", str(repo), "reset", "--hard", "HEAD",
    )
    return web.json_response({"ok": True, "restored": sha})


async def _restore_from_archive(name: str) -> web.Response:
    src = MC_BACKUP_DIR / "archives" / name
    if not src.is_file():
        return web.json_response({"error": "archive not found"}, status=404)
    try:
        await _rcon_command("save-off")
        await _rcon_command("stop")
    except Exception:  # noqa: BLE001
        pass
    proc = await asyncio.create_subprocess_exec(
        "tar", "-xzf", str(src), "-C", str(MC_SERVER_DIR),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out_b, _ = await proc.communicate()
    return web.json_response({
        "ok": proc.returncode == 0,
        "output": out_b.decode("utf-8", "replace")[-2048:],
    })


# ---------------------------------------------------------------------------
# Routes: API — log streaming (SSE)
# ---------------------------------------------------------------------------
async def api_logs_sse(request: web.Request) -> web.StreamResponse:
    resp = web.StreamResponse(status=200, reason="OK", headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
    await resp.prepare(request)

    log_path = MC_CONSOLE_LOG
    last_size = 0
    if log_path.is_file():
        last_size = max(0, log_path.stat().st_size - 16_384)

    while not request.transport or not request.transport.is_closing():
        try:
            if log_path.is_file():
                size = log_path.stat().st_size
                if size < last_size:
                    last_size = 0  # log rotated
                if size > last_size:
                    async with aiofiles.open(log_path, mode="r", errors="replace") as f:
                        await f.seek(last_size)
                        chunk = await f.read(size - last_size)
                    last_size = size
                    for line in chunk.splitlines():
                        payload = json.dumps({"line": line, "ts": time.time()})
                        await resp.write(f"data: {payload}\n\n".encode())
            await asyncio.sleep(1.0)
        except (ConnectionResetError, asyncio.CancelledError):
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(2.0)
    return resp


# ---------------------------------------------------------------------------
# Routes: API — server-update / plugins
# ---------------------------------------------------------------------------
async def api_server_update(_: web.Request) -> web.Response:
    proc = await asyncio.create_subprocess_exec(
        str(SCRIPTS_DIR / "download-server.sh"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env={**os.environ},
    )
    out_b, _ = await proc.communicate()
    return web.json_response({
        "ok": proc.returncode == 0,
        "output": out_b.decode("utf-8", "replace")[-4096:],
    })


async def api_plugin_install(request: web.Request) -> web.Response:
    body = await request.json()
    url = str(body.get("url", "")).strip()
    name = str(body.get("name", "")).strip()
    if not url.startswith(("https://", "http://")):
        return web.json_response({"error": "url must be http(s)"}, status=400)
    args = [str(SCRIPTS_DIR / "install-plugin.sh"), url]
    if name:
        args.append(name)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out_b, _ = await proc.communicate()
    return web.json_response({
        "ok": proc.returncode == 0,
        "output": out_b.decode("utf-8", "replace"),
    })


async def api_plugin_list(_: web.Request) -> web.Response:
    plugins_dir = MC_SERVER_DIR / "plugins"
    if not plugins_dir.is_dir():
        return web.json_response({"plugins": []})
    entries = []
    for jar in sorted(plugins_dir.glob("*.jar")):
        stat = jar.stat()
        entries.append({"name": jar.name, "size": stat.st_size, "mtime": int(stat.st_mtime)})
    return web.json_response({"plugins": entries})


async def api_plugin_delete(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if "/" in name or ".." in name or not name.endswith(".jar"):
        return web.json_response({"error": "invalid name"}, status=400)
    target = MC_SERVER_DIR / "plugins" / name
    if not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    target.unlink()
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
def build_app() -> web.Application:
    app = web.Application()

    # Static
    app.router.add_get("/", index)
    app.router.add_get("/favicon.ico", favicon)
    app.router.add_get("/favicon.svg", favicon)
    app.router.add_static("/static/", path=str(STATIC), name="static")
    async def _send_style(_: web.Request) -> web.Response:
        return web.FileResponse(STATIC / "style.css")
    async def _send_app(_: web.Request) -> web.Response:
        return web.FileResponse(STATIC / "app.js")
    app.router.add_get("/style.css", _send_style)
    app.router.add_get("/app.js", _send_app)

    # API
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/api/players", api_players)
    app.router.add_get("/api/properties", api_properties_get)
    app.router.add_post("/api/properties", api_properties_post)
    app.router.add_post("/api/command", api_command)
    app.router.add_post("/api/say", api_say)
    app.router.add_post("/api/player/{name}/{action}", api_player_action)
    app.router.add_post("/api/restart", api_restart)
    app.router.add_post("/api/stop", api_stop)
    app.router.add_post("/api/backup", api_backup)
    app.router.add_get("/api/backups", api_backups_list)
    app.router.add_post("/api/restore/{ref}", api_restore)
    app.router.add_get("/api/logs/tail", api_logs_sse)
    app.router.add_post("/api/server/update", api_server_update)
    app.router.add_get("/api/plugins", api_plugin_list)
    app.router.add_post("/api/plugins", api_plugin_install)
    app.router.add_delete("/api/plugins/{name}", api_plugin_delete)
    return app


def main() -> None:
    MC_PANEL_STATE.mkdir(parents=True, exist_ok=True)
    web.run_app(build_app(), host=BIND_HOST, port=BIND_PORT, access_log=None)


if __name__ == "__main__":
    main()
