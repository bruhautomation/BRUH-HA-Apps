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
import sys
import time
from pathlib import Path

import aiofiles
from aiohttp import web

# The RCON client lives next to the other shell/python tools. Adding its
# directory to sys.path keeps the import working both in production (where
# run.sh copies scripts to /opt/bruh-mc/scripts) and in the unit-test
# harness, which exercises panel/server.py directly from the repo checkout.
_SCRIPTS_DIR = os.environ.get(
    "BRUH_MC_SCRIPTS_DIR",
    "/opt/bruh-mc/scripts",
)
for _candidate in (_SCRIPTS_DIR, str(Path(__file__).resolve().parent.parent / "scripts")):
    if _candidate and _candidate not in sys.path:
        sys.path.insert(0, _candidate)
from rcon_client import Rcon  # noqa: E402

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
STATIC = HERE
MC_SERVER_DIR = Path(os.environ.get("MC_SERVER_DIR", "/config/minecraft"))
_MC_BACKUP_DIR_ENV = Path(os.environ.get("MC_BACKUP_DIR", "/config/minecraft-backups"))
MC_PANEL_STATE = Path(os.environ.get("MC_PANEL_STATE", "/data/panel"))
MC_CONSOLE_LOG = Path(os.environ.get("MC_CONSOLE_LOG", str(MC_PANEL_STATE / "console.log")))
MC_INPUT_FIFO = Path(os.environ.get("MC_INPUT_FIFO", "/tmp/mc-stdin.fifo"))
SCRIPTS_DIR = Path("/opt/bruh-mc/scripts")
# Add-on version, exported by run.sh via resolve_addon_version. Used to
# cache-bust style.css + app.js so a HA add-on update is picked up by the
# browser without users having to hard-refresh. Falls back to "dev" if the
# var isn't set (test harness, local podman builds with broken templating).
ADDON_VERSION = os.environ.get("ADDON_VERSION", "dev")


def _resolve_backup_dir() -> Path:
    """Return the active world's backup directory.

    `MC_BACKUP_DIR` is normally exported by run.sh pointing directly at
    `/config/minecraft-backups/<active>/`. For belt-and-suspenders against
    older deployments where the env var still points at the parent dir
    (the legacy pre-1.5.6 layout), drop down into `<active>/` ourselves
    when the parent looks like a profile container — that's where git/
    and archives/ actually live.
    """
    base = _MC_BACKUP_DIR_ENV
    if (base / "git").is_dir() or (base / "archives").is_dir():
        return base
    active = os.environ.get("ACTIVE_WORLD", "").strip()
    if active and (base / active).is_dir():
        return base / active
    # No usable subdir — return as-is. Callers handle the missing case.
    return base


MC_BACKUP_DIR = _resolve_backup_dir()

RCON_HOST = "127.0.0.1"
RCON_PORT = 25575
BIND_HOST = "0.0.0.0"
BIND_PORT = 8099


# ---------------------------------------------------------------------------
# Console-stream noise filter
# ---------------------------------------------------------------------------
# stats-collector.py polls Paper over RCON every 15 seconds for /list and
# (when supported) /tps and /version. Each RCON round-trip emits THREE log
# lines into console.log:
#
#   [hh:mm:ss INFO]: Thread RCON Client /127.0.0.1 started
#   [hh:mm:ss INFO]: [Essentials] Rcon issued server command: /list
#   [hh:mm:ss INFO]: Thread RCON Client /127.0.0.1 shutting down
#
# So every minute the live console picks up 12 noise lines, drowning out
# the actual server events users care about (joins, deaths, chat, plugin
# warnings). Backup runs add three more lines per snapshot via save-off /
# save-all flush / save-on. We strip these at the SSE boundary so the
# console.log file on disk stays complete for offline debugging while
# the live view stays useful. (See CHANGELOG 1.5.6 for the full story.)
_RCON_NOISE_PATTERNS = (
    re.compile(r"Thread RCON Client /127\.0\.0\.1 (started|shutting down)"),
    re.compile(
        r"\[Essentials\] Rcon issued server command: "
        r"/(list|tps|version|save-all|save-off|save-on)\b"
    ),
)


def _is_rcon_noise(line: str) -> bool:
    return any(p.search(line) for p in _RCON_NOISE_PATTERNS)


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
        with Rcon(RCON_HOST, password, port=RCON_PORT, timeout=5) as r:
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
    "enforce-secure-profile",
    "hardcore",
    "allow-nether",
    "generate-structures",
    "spawn-monsters",
    "spawn-animals",
    "spawn-npcs",
    "prevent-proxy-connections",
    "hide-online-players",
    "resource-pack",
    "resource-pack-sha1",
    "require-resource-pack",
    "max-world-size",
    "network-compression-threshold",
    "entity-broadcast-range-percentage",
    "op-permission-level",
    "level-seed",
    "level-type",
    "level-name",
}

VALID_PLAYER_NAME = re.compile(r"^[A-Za-z0-9_]{1,16}$")


# ---------------------------------------------------------------------------
# Routes: static
# ---------------------------------------------------------------------------
def _render_index_html() -> str:
    """Return index.html with `__VERSION__` placeholders substituted for
    the running add-on version. Used as a cheap cache-buster — every
    release ships a new `?v=<version>` query string on style.css / app.js
    links so the browser never sticks on a stale stylesheet from the
    previous add-on version. (1.5.7's nav fix landed but users kept
    seeing the broken 1.5.6 layout because their browsers cached the
    old style.css — that's the bug this works around.) Read fresh per
    request rather than at module load because tests rewrite index.html
    in place; the cost is one ~12 KB file read, which is negligible
    against the rest of the request pipeline.
    """
    html = (STATIC / "index.html").read_text()
    return html.replace("__VERSION__", ADDON_VERSION)


async def index(_: web.Request) -> web.Response:
    return web.Response(
        text=_render_index_html(),
        content_type="text/html",
        # Don't let the HTML itself get cached — without this the browser
        # would happily reuse a cached index.html with last release's
        # version string baked in, defeating the cache-busting query.
        headers={"Cache-Control": "no-store"},
    )


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
                        if _is_rcon_noise(line):
                            continue
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
# Routes: API — switchable server profiles ("worlds")
# ---------------------------------------------------------------------------
MC_WORLDS_DIR = Path(os.environ.get("MC_WORLDS_DIR", "/config/minecraft-worlds"))
WORLD_MANAGER = SCRIPTS_DIR / "world-manager.sh"
VALID_WORLD_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


async def _run_world_manager(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        str(WORLD_MANAGER), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    out_b, _ = await proc.communicate()
    return proc.returncode or 0, out_b.decode("utf-8", "replace")


async def api_worlds_list(_: web.Request) -> web.Response:
    rc, out = await _run_world_manager("list")
    worlds: list[dict] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            worlds.append({
                "name": parts[0],
                "size_bytes": int(parts[1]),
                "active": parts[2] == "true",
            })
        except ValueError:
            continue
    # Also surface the active name even when the world list is empty.
    rc2, active = await _run_world_manager("active")
    return web.json_response({
        "worlds": worlds,
        "active": active.strip() if rc2 == 0 else None,
    })


async def api_worlds_create(request: web.Request) -> web.Response:
    body = await request.json()
    name = str(body.get("name", "")).strip()
    seed = str(body.get("seed", "")).strip()
    if not VALID_WORLD_NAME.match(name):
        return web.json_response({"error": "invalid name (1-32 chars, A-Z a-z 0-9 _ -)"}, status=400)
    rc, out = await _run_world_manager("create", name, seed) if seed else await _run_world_manager("create", name)
    if rc != 0:
        return web.json_response({"error": out.strip()}, status=400)
    return web.json_response({"ok": True, "output": out})


async def api_worlds_switch(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if not VALID_WORLD_NAME.match(name):
        return web.json_response({"error": "invalid name"}, status=400)
    rc, out = await _run_world_manager("switch", name)
    if rc != 0:
        return web.json_response({"error": out.strip()}, status=400)

    # The active_world add-on option is now updated, but we still need the
    # `/config/minecraft` symlink repointed at the new profile — that happens
    # in `ensure_worlds_layout` inside `main()` of run.sh, which only runs
    # when the add-on CONTAINER restarts (not when the JVM alone restarts).
    # The header "Restart" button just RCON-stops the JVM and lets
    # run_server_loop relaunch it in the same container, so the symlink
    # never changes — users saw the same world keep loading.
    #
    # Trigger a full add-on restart via the Supervisor so the switch
    # actually takes effect without a second manual step. The Supervisor
    # queues the restart and returns immediately, so this response still
    # makes it back to the browser before the panel goes down.
    restart_err = await _supervisor_restart_self()
    if restart_err:
        return web.json_response({
            "ok": True,
            "warning": (
                f"active_world set to '{name}', but auto-restart failed: "
                f"{restart_err}. Click Restart on the HA add-on page to "
                f"activate the switch."
            ),
        })
    return web.json_response({
        "ok": True,
        "message": (
            f"Switched to '{name}'. The add-on is restarting now — "
            f"this panel will be unreachable for ~30 seconds while the new "
            f"world loads."
        ),
    })


async def _supervisor_restart_self() -> str | None:
    """Ask the Supervisor to restart this add-on. Returns None on success
    or a short error string on failure. Fire-and-forget: the Supervisor
    queues the restart and responds immediately."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return "SUPERVISOR_TOKEN not set"
    base = os.environ.get("SUPERVISOR_API_URL", "http://supervisor")
    # aiohttp is already imported at module scope (from aiohttp import web);
    # we use the client session from the same package here.
    import aiohttp
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base}/addons/self/restart",
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status == 200:
                    return None
                body = (await resp.text())[:200]
                return f"Supervisor HTTP {resp.status}: {body}"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


async def api_worlds_delete(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if not VALID_WORLD_NAME.match(name):
        return web.json_response({"error": "invalid name"}, status=400)
    rc, out = await _run_world_manager("delete", name)
    if rc != 0:
        status = 409 if "active profile" in out else 400
        return web.json_response({"error": out.strip()}, status=status)
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
    # Switchable server profiles
    app.router.add_get("/api/worlds", api_worlds_list)
    app.router.add_post("/api/worlds", api_worlds_create)
    app.router.add_post("/api/worlds/{name}/switch", api_worlds_switch)
    app.router.add_delete("/api/worlds/{name}", api_worlds_delete)
    return app


def main() -> None:
    MC_PANEL_STATE.mkdir(parents=True, exist_ok=True)
    web.run_app(build_app(), host=BIND_HOST, port=BIND_PORT, access_log=None)


if __name__ == "__main__":
    main()
