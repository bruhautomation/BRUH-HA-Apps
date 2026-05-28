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
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
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
MC_BACKUPS_ROOT = Path(os.environ.get("MC_BACKUPS_ROOT", "/config/minecraft-backups"))
# Resource packs are GLOBAL (one pack serves multiple worlds), so they live
# alongside the worlds directory rather than inside any one of them.
MC_RESOURCE_PACKS = Path(os.environ.get("MC_RESOURCE_PACKS", "/config/resource-packs"))
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


def _unescape_java_property(value: str) -> str:
    """Reverse the escaping Java's `Properties.store()` applies to values.

    Minecraft re-saves `server.properties` on shutdown using Java's
    Properties format, which escapes `:`, `=`, `#`, `!`, leading whitespace,
    and `\\` itself. The on-disk file ends up with values like
    `level-type=minecraft\\:normal` and the panel was displaying the raw
    escaped form (the literal backslash), which was confusing.

    We unescape conservatively: only the handful of escapes Java's properties
    writer emits. Unicode `\\uXXXX` is handled because Minecraft's MOTD can
    contain it. Anything else `\\?` falls through unchanged so we never
    corrupt a value we didn't recognise."""
    if "\\" not in value:
        return value
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch != "\\" or i + 1 >= len(value):
            out.append(ch)
            i += 1
            continue
        nxt = value[i + 1]
        if nxt in ":=# !\\":
            out.append(nxt); i += 2
        elif nxt == "n":  out.append("\n"); i += 2
        elif nxt == "t":  out.append("\t"); i += 2
        elif nxt == "r":  out.append("\r"); i += 2
        elif nxt == "u" and i + 5 < len(value):
            try:
                out.append(chr(int(value[i + 2:i + 6], 16))); i += 6
            except ValueError:
                out.append(ch); i += 1
        else:
            out.append(ch); i += 1
    return "".join(out)


def _read_properties() -> dict[str, str]:
    props: dict[str, str] = {}
    path = MC_SERVER_DIR / "server.properties"
    if not path.is_file():
        return props
    for line in path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Java's Properties.store() escapes colons/equals/etc. in values; we
        # unescape so the panel shows readable values (e.g. `minecraft:normal`
        # instead of `minecraft\:normal`).
        props[key.strip()] = _unescape_java_property(value)
    return props


# Per-world gameplay keys the panel may edit, with their value type. As of
# 1.8.0 these live ONLY in the active world's server.properties (there are no
# global add-on options for them anymore), so editing here writes straight to
# that file — which IS the source of truth, so the change persists and is
# per-world. `type` drives validation. enforce-whitelist is deliberately
# absent: it has no independent meaning (the add-on derives it from
# white-list), so it shows up read-only.
EDITABLE_PROP_TYPES: dict[str, str] = {
    "motd": "str",
    "difficulty": "enum",
    "gamemode": "enum",
    "force-gamemode": "bool",
    "max-players": "int",
    "view-distance": "int",
    "simulation-distance": "int",
    "pvp": "bool",
    "allow-flight": "bool",
    "white-list": "bool",
    "spawn-protection": "int",
    "enable-command-block": "bool",
    "op-permission-level": "int",
    "online-mode": "bool",
    "enforce-secure-profile": "bool",
    "hardcore": "bool",
    "allow-nether": "bool",
    "generate-structures": "bool",
    "spawn-monsters": "bool",
    "spawn-animals": "bool",
    "spawn-npcs": "bool",
    "prevent-proxy-connections": "bool",
    "hide-online-players": "bool",
    "resource-pack": "str",
    "resource-pack-sha1": "str",
    "require-resource-pack": "bool",
    "max-world-size": "int",
    "network-compression-threshold": "int",
    "entity-broadcast-range-percentage": "int",
    "level-seed": "str",
    "level-type": "enum",
    "level-name": "str",
    "initial-enabled-packs": "str",
    "initial-disabled-packs": "str",
    "connection-throttle": "int",
    "player-idle-timeout": "int",
}

EDITABLE_PROPS = set(EDITABLE_PROP_TYPES)


# Allowed values for the enum properties (mirrors config.yaml's old schema).
# Validating BEFORE we touch RCON or write the file (a) gives the user a clear
# error and (b) stops a value with spaces (e.g. "creative SomeProbe") from
# smuggling extra arguments into the `gamemode <v> @a` RCON command.
_PROP_ENUMS = {
    "difficulty": {"peaceful", "easy", "normal", "hard"},
    "gamemode": {"survival", "creative", "adventure", "spectator"},
    "level-type": {
        "minecraft:normal", "minecraft:flat", "minecraft:large_biomes",
        "minecraft:amplified", "minecraft:single_biome_surface",
        # Allow legacy short forms too.
        "default", "flat", "largebiomes", "amplified",
    },
}
# Int ranges for editable int properties.
_PROP_INT_RANGE = {
    "max-players": (1, 1000),
    "view-distance": (3, 32),
    "simulation-distance": (3, 32),
    "spawn-protection": (0, 10000),
    "max-world-size": (1, 29999984),
    "network-compression-threshold": (-1, 65536),
    "entity-broadcast-range-percentage": (10, 1000),
    "op-permission-level": (1, 4),
    "connection-throttle": (0, 60000),
    "player-idle-timeout": (0, 1440),
}


def _validate_prop_value(key: str, value: str, type_: str) -> str | None:
    """Return None if `value` is acceptable for `key`, else an error string.

    Rejects anything that would corrupt server.properties (newlines),
    out-of-range ints, bad enums, or non-bool bools — which also closes
    RCON argument-smuggling on the live-applied keys."""
    if "\n" in value or "\r" in value:
        return "value may not contain line breaks"
    if type_ == "bool":
        if value.strip().lower() not in ("true", "false"):
            return f"{key} must be true or false"
        return None
    if type_ == "int":
        try:
            n = int(value.strip())
        except ValueError:
            return f"{key} must be a whole number"
        lo, hi = _PROP_INT_RANGE.get(key, (None, None))
        if lo is not None and (n < lo or n > hi):
            return f"{key} must be between {lo} and {hi}"
        return None
    if type_ == "enum":
        allowed = _PROP_ENUMS.get(key)
        if allowed is not None and value not in allowed:
            return f"{key} must be one of: {', '.join(sorted(allowed))}"
    return None

# ---------------------------------------------------------------------------
# Hardware-aware settings recommender
# ---------------------------------------------------------------------------
# Inspects host RAM and CPU count and proposes sensible values for the keys
# that actually move performance: memory_mb (global add-on option),
# view-distance + simulation-distance (per-world server.properties). Reads
# /proc/meminfo (which inside an HA add-on container reports HOST memory).
# An override path (MEMINFO_PATH env) keeps it unit-testable.
def _host_total_memory_mb() -> int:
    path = os.environ.get("MEMINFO_PATH", "/proc/meminfo")
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError):
        pass
    return 0


def _recommend_settings() -> dict:
    """Return a dict of recommended values + rationale for the panel UI."""
    host_mb = _host_total_memory_mb()
    cpu_count = os.cpu_count() or 2

    # Reserve at least 2 GB for the HA OS / Core / other add-ons. The rest is
    # what we'd consider safe to hand to the JVM, but we also cap so we don't
    # gift a small server a runaway 16 GB heap with diminishing returns past
    # the point Aikar's flags can keep GC pauses sane.
    headroom_mb = 2048
    available_mb = max(host_mb - headroom_mb, 1024) if host_mb else 2048
    if available_mb >= 16384:
        memory_mb = 8192
    elif available_mb >= 8192:
        memory_mb = 6144
    elif available_mb >= 6144:
        memory_mb = 4096
    elif available_mb >= 4096:
        memory_mb = 3072
    elif available_mb >= 3072:
        memory_mb = 2048
    else:
        memory_mb = max(1024, available_mb)
    # Round down to the nearest 256 MB so the value looks deliberate.
    memory_mb = (memory_mb // 256) * 256
    # Clamp to schema bounds (int(512,65536)).
    memory_mb = max(512, min(65536, memory_mb))

    # View / sim distance scale with the heap we recommended. simulation
    # distance is the bigger TPS lever, so keep it ≤ view-distance.
    if memory_mb >= 6144:
        view_distance, simulation_distance = 12, 10
    elif memory_mb >= 3072:
        view_distance, simulation_distance = 10, 8
    elif memory_mb >= 2048:
        view_distance, simulation_distance = 8, 6
    else:
        view_distance, simulation_distance = 6, 5

    return {
        "host_total_mb": host_mb,
        "cpu_count": cpu_count,
        "memory_mb": memory_mb,
        "view_distance": view_distance,
        "simulation_distance": simulation_distance,
        "rationale": {
            "memory": (
                f"Host has {host_mb} MB; reserving {headroom_mb} MB for HA / OS / "
                f"other add-ons leaves ~{available_mb} MB. Capped at sensible "
                f"diminishing-returns ceilings so the JVM heap stays GC-friendly."
                if host_mb else
                "Couldn't detect host memory — defaulting to a safe 2 GB heap."
            ),
            "distances": (
                f"Picked to keep memory pressure low at {memory_mb} MB. "
                f"simulation-distance is the bigger TPS lever so it's kept "
                f"≤ view-distance."
            ),
            "cpus": f"Detected {cpu_count} CPU(s); Aikar's flags handle the rest.",
        },
    }


# Player-name validator for the Players tab actions (op/kick/ban/whitelist).
# Vanilla Mojang names are `[A-Za-z0-9_]{1,16}`, but with Geyser + Floodgate
# enabled (the default on this add-on) Bedrock players join with a
# Floodgate username-prefix — `.` by default, configurable to `*` or any
# single ASCII char. The prefix counts toward the 16-char Minecraft limit.
# Without this, OP/kick/ban from the Players tab returns "invalid name" for
# every Bedrock player (the leading dot is rejected) and the user has to
# fall back to the console. We accept `.`, `*`, and `_` anywhere; the
# character set is still tightly bounded so no quoting/injection risk
# downstream over RCON.
VALID_PLAYER_NAME = re.compile(r"^[A-Za-z0-9_.*]{1,16}$")


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
        "setup_required": _setup_required(),
        "crash": _detect_crash(state),
    })


# Marker file that records "the first-run wizard has been completed on this
# install." Lives under /data/ so it survives add-on upgrades (which preserve
# /data) and is cleared on uninstall (which clears /data) — exactly the
# lifecycle we want for the wizard.
SETUP_MARKER = MC_PANEL_STATE / ".setup-completed"


def _setup_required() -> bool:
    """True when the welcome wizard should be shown — i.e. this looks like a
    brand-new install.

    Gated on TWO signals so a single dropped/edited value can't make the
    wizard reappear after the user has already done it:

      1. The completed-marker file is missing (`/data/panel/.setup-completed`).
         Written on every successful wizard submit AND opportunistically by
         the panel whenever it sees a server that's actually been set up
         (EULA accepted *and* a world exists on disk) — that's the "upgrade
         from a pre-wizard release" case where the user shouldn't suddenly
         see the wizard.
      2. The EULA hasn't been accepted (`/data/options.json`'s `eula`
         field). This is also the gate run.sh checks before launching the
         JVM, so it lines up with "the server actually can't run yet."

    Both must be true for the wizard to show. After the user clicks Start
    the marker is written and we never bother them again, even if eula gets
    flipped back to false for some weird reason."""
    # Belt-and-suspenders: marker present always wins.
    if SETUP_MARKER.is_file():
        return False
    try:
        with open(os.environ.get("MC_OPTIONS_FILE", "/data/options.json")) as f:
            eula_accepted = bool(json.load(f).get("eula", False))
    except (OSError, ValueError):
        # Couldn't read options — err on the side of NOT showing the wizard.
        # If the user really does need setup, they can re-install or hit the
        # EULA gate in run.sh which logs a clear warning.
        return False
    # If EULA is accepted but the marker is missing (upgrade from a
    # pre-wizard release, or a panel-only restart), claim the setup-
    # completed state now so we never show the wizard for an already-
    # configured install.
    if eula_accepted:
        try:
            SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
            SETUP_MARKER.write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        except OSError:
            pass
        return False
    # EULA is false AND no marker — true first run.
    return True


def _detect_crash(state: dict) -> dict | None:
    """Surface the last few lines of the console log when the server is in a
    'crashed' state — i.e. it was running, then exited non-zero, and the
    auto-restart loop has either kicked off a new attempt or given up. The
    panel uses this to render a banner with the actionable error.

    We treat `state.status == "stopped"` plus a recent non-zero exit as a
    crash. Run.sh writes `state.json` with `status: stopped` after every JVM
    exit, but only an UNEXPECTED stop deserves the crash banner — clicking
    the panel's Stop button writes `no_restart` first, which we honour by
    suppressing the banner.
    """
    if state.get("status") != "stopped":
        return None
    if (MC_PANEL_STATE / "no_restart").is_file():
        return None
    log_path = MC_CONSOLE_LOG
    if not log_path.is_file():
        return None
    # Show the last ~30 lines that look like error context.
    try:
        with open(log_path, errors="replace") as f:
            tail = f.readlines()[-200:]
    except OSError:
        return None
    if not tail:
        return None
    # Keep lines that look interesting (ERROR/WARN/Exception/stack frames).
    interesting = [
        ln.rstrip("\n") for ln in tail
        if re.search(r"\b(ERROR|SEVERE|Exception|Caused by|\tat )\b", ln)
    ]
    excerpt = (interesting or [ln.rstrip("\n") for ln in tail])[-30:]
    return {"excerpt": excerpt, "log_size": log_path.stat().st_size}


async def api_players(_: web.Request) -> web.Response:
    return web.json_response(_read_json(MC_PANEL_STATE / "players.json", {
        "players": [], "online": 0, "max": 0,
    }))


async def api_properties_get(_: web.Request) -> web.Response:
    props = _read_properties()
    safe = {k: v for k, v in props.items() if k != "rcon.password"}
    # Expose the type metadata so the panel can render typed widgets — a
    # `<select>` for `gamemode` / `difficulty` / `level-type`, a number
    # input for view-distance, a checkbox-like select for bools — instead
    # of plain text fields where the user has to guess what shape a value
    # takes (the "what goes in minecraft\:normal" confusion).
    return web.json_response({
        "properties": safe,
        "editable": sorted(EDITABLE_PROPS),
        "types": EDITABLE_PROP_TYPES,
        "enums": {k: sorted(v) for k, v in _PROP_ENUMS.items()},
        "int_ranges": {k: list(v) for k, v in _PROP_INT_RANGE.items()},
    })


async def api_properties_post(request: web.Request) -> web.Response:
    body = await request.json()
    key = str(body.get("key", "")).strip()
    value = str(body.get("value", "")).strip()
    if key not in EDITABLE_PROPS:
        return web.json_response({"error": f"key '{key}' not editable"}, status=400)

    # Validate before writing: rejects newline-injection into
    # server.properties, out-of-range ints / bad enums, and value-with-spaces
    # RCON argument smuggling on the live-applied keys.
    err = _validate_prop_value(key, value, EDITABLE_PROP_TYPES[key])
    if err:
        return web.json_response({"error": err}, status=400)

    # Write straight to the ACTIVE world's server.properties. That file is the
    # per-world source of truth — the add-on no longer overwrites gameplay keys
    # on boot — so this edit persists and stays scoped to this world.
    props = _read_properties()
    props[key] = value
    lines = [
        "# server.properties — active world is the source of truth.",
        "# Gameplay keys are edited here / from the panel and preserved on boot.",
        f"# Last edited via panel: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
    ]
    lines.extend(f"{k}={props[k]}" for k in sorted(props))
    tmp = MC_SERVER_DIR / "server.properties.tmp"
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(MC_SERVER_DIR / "server.properties")

    # Live-apply a handful of keys via RCON where possible (others need a
    # restart, which the frontend tells the user).
    live_reply = None
    try:
        if key == "difficulty":
            live_reply = await _rcon_command(f"difficulty {value}")
        elif key == "gamemode":
            # Set the default for new players AND move every online player —
            # `defaultgamemode` alone never touches players who have already
            # joined, which is the whole reason creative "didn't stick".
            await _rcon_command(f"defaultgamemode {value}")
            live_reply = await _rcon_command(f"gamemode {value} @a")
        elif key == "white-list":
            live_reply = await _rcon_command(f"whitelist {'on' if value == 'true' else 'off'}")
    except Exception as exc:  # noqa: BLE001
        live_reply = f"live-apply failed: {exc}"

    return web.json_response({"ok": True, "live": live_reply})


# ---------------------------------------------------------------------------
# Routes: API — settings recommender ("Tune for my hardware")
# ---------------------------------------------------------------------------
async def api_recommend_get(_: web.Request) -> web.Response:
    """Return the recommendation alongside the current effective values and a
    per-key delta, so the Tune dialog can show only what would actually
    change (or say "no changes needed" when settings already match)."""
    rec = _recommend_settings()
    # Current global memory_mb lives in /data/options.json (Supervisor-managed).
    cur_mem = None
    try:
        with open(os.environ.get("MC_OPTIONS_FILE", "/data/options.json")) as f:
            cur_mem = int(json.load(f).get("memory_mb"))
    except (OSError, ValueError, TypeError):
        cur_mem = None
    # View / sim distance are per-world server.properties keys (the active
    # world is what's loaded via the symlink).
    props = _read_properties()
    def _as_int(s):
        try: return int(s)
        except (TypeError, ValueError): return None
    cur_view = _as_int(props.get("view-distance"))
    cur_sim = _as_int(props.get("simulation-distance"))

    rec["current"] = {
        "memory_mb": cur_mem,
        "view_distance": cur_view,
        "simulation_distance": cur_sim,
    }
    rec["delta"] = {
        "memory_mb": cur_mem != rec["memory_mb"],
        "view_distance": cur_view != rec["view_distance"],
        "simulation_distance": cur_sim != rec["simulation_distance"],
    }
    rec["any_change"] = any(rec["delta"].values())
    return web.json_response(rec)


async def api_recommend_apply(_: web.Request) -> web.Response:
    """Apply the current recommendation.

    Splits the writes by scope:
      * memory_mb is a GLOBAL add-on option (one JVM runs at a time) — written
        back to the Supervisor.
      * view-distance and simulation-distance are PER-WORLD server.properties
        keys — written to the ACTIVE world's file. (Switching worlds later
        won't inherit them; that's the per-world model.)
    Returns what was applied and where, plus a hint that the JVM needs a
    restart for any of it to take effect."""
    rec = _recommend_settings()
    applied: dict[str, object] = {}
    warnings: list[str] = []

    warn = await _persist_option("memory_mb", rec["memory_mb"])
    if warn:
        warnings.append(f"memory_mb: {warn}")
    else:
        applied["memory_mb"] = rec["memory_mb"]

    # Per-world: write view/sim distance straight into the active world's
    # server.properties. We re-use the property writer's preserve-existing
    # behaviour by reading first, merging, then writing.
    props = _read_properties()
    props["view-distance"] = str(rec["view_distance"])
    props["simulation-distance"] = str(rec["simulation_distance"])
    lines = [
        "# server.properties — active world is the source of truth.",
        "# Gameplay keys are edited here / from the panel and preserved on boot.",
        f"# Last edited via panel (recommend/apply): {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
    ]
    lines.extend(f"{k}={props[k]}" for k in sorted(props))
    tmp = MC_SERVER_DIR / "server.properties.tmp"
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(MC_SERVER_DIR / "server.properties")
    applied["view-distance"] = rec["view_distance"]
    applied["simulation-distance"] = rec["simulation_distance"]

    return web.json_response({
        "ok": True,
        "applied": applied,
        "scope": {
            "memory_mb": "global (add-on option)",
            "view-distance": "active world only",
            "simulation-distance": "active world only",
        },
        "warnings": warnings or None,
        "restart_required": True,
        "note": (
            "Memory change takes effect on the next add-on restart; "
            "view/sim distance on the next JVM restart."
        ),
    })


# ---------------------------------------------------------------------------
# Routes: API — first-run wizard
# ---------------------------------------------------------------------------
# Curated popular-plugin options the wizard can flip on. Kept in sync with
# config.yaml's install_* options + popular-plugins.sh PLUGIN_SLUGS.
_WIZARD_PLUGIN_KEYS = (
    "install_essentialsx", "install_essentialsx_chat", "install_luckperms",
    "install_worldedit", "install_coreprotect", "install_griefprevention",
    "install_mcmmo", "install_chestsort", "install_veinminer", "install_spark",
)


async def api_setup(request: web.Request) -> web.Response:
    """Accept the multi-step first-run wizard's submission.

    The wizard walks the user through nine steps (EULA, server software,
    connectivity, first world basics, players + access, performance,
    plugins, maintenance, review) and POSTs one body here. We split the
    writes by scope:

      * Global add-on options (eula, server_type, active_world, memory_mb,
        install_*) -> Supervisor `/addons/self/options`.
      * Per-world gameplay (gamemode, difficulty, level-type, level-seed,
        pvp, hardcore, online-mode, view-distance, simulation-distance) ->
        the target world's `server.properties`.

    The target world is determined by `active_world` in the body (default
    "default"). If the world directory doesn't exist yet we stage the
    skeleton (plugins/, mods/, backup dir) so the next add-on boot can use
    it without help from world-manager.sh.

    Finally we trigger a Supervisor restart so run.sh re-enters and boots
    the JVM with the new options."""
    body = await request.json()
    if not body.get("eula"):
        return web.json_response({"error": "eula must be accepted"}, status=400)

    warnings: list[str] = []

    # ── Validate inputs up front so a malformed wizard payload can't half-
    # apply (worlds dir created with junk gameplay keys, etc.).
    server_type = body.get("server_type")
    valid_server_types = {"paper", "purpur", "folia", "vanilla", "fabric", "forge"}
    if server_type and server_type not in valid_server_types:
        return web.json_response({"error": "invalid server_type"}, status=400)

    world_name = (body.get("active_world") or "default").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", world_name):
        return web.json_response({"error": "invalid active_world name"}, status=400)

    if "gamemode" in body and body["gamemode"] not in {
        "survival", "creative", "adventure", "spectator",
    }:
        return web.json_response({"error": "invalid gamemode"}, status=400)
    if "difficulty" in body and body["difficulty"] not in {
        "peaceful", "easy", "normal", "hard",
    }:
        return web.json_response({"error": "invalid difficulty"}, status=400)
    if "level_type" in body and body["level_type"] not in _PROP_ENUMS["level-type"]:
        return web.json_response({"error": "invalid level_type"}, status=400)

    # Strict bool validation. Python's `bool("false") is True` (any non-empty
    # string is truthy), so a non-JS caller posting {"hardcore": "false"} used
    # to silently turn hardcore ON. Reject anything that isn't a JSON bool.
    for bool_key in (
        "online_mode", "enable_bedrock_support", "force_gamemode", "pvp",
        "hardcore", "white_list",
    ):
        if bool_key in body and not isinstance(body[bool_key], bool):
            return web.json_response(
                {"error": f"{bool_key} must be true or false"}, status=400,
            )

    memory_mb = body.get("memory_mb")
    if memory_mb is not None:
        try:
            memory_mb = int(memory_mb)
        except (TypeError, ValueError):
            return web.json_response({"error": "memory_mb must be an integer"}, status=400)
        if memory_mb < 512 or memory_mb > 65536:
            return web.json_response({"error": "memory_mb out of range (512-65536)"}, status=400)

    # Per-world integer validation up front so a bad backup interval or
    # spawn-protection value doesn't leave the world half-staged.
    def _bounded_int(key: str, lo: int, hi: int):
        if key not in body:
            return None
        try:
            n = int(body[key])
        except (TypeError, ValueError):
            return f"{key} must be an integer"
        if n < lo or n > hi:
            return f"{key} out of range ({lo}-{hi})"
        return n
    range_err_keys = [
        ("max_players", 1, 1000),
        ("spawn_protection", 0, 10000),
        ("view_distance", 3, 32),
        ("simulation_distance", 3, 32),
        ("backup_interval_minutes", 5, 1440),
        ("backup_keep_count", 1, 500),
    ]
    int_values: dict[str, int] = {}
    for key, lo, hi in range_err_keys:
        v = _bounded_int(key, lo, hi)
        if isinstance(v, str):  # error message
            return web.json_response({"error": v}, status=400)
        if v is not None:
            int_values[key] = v

    # ── Write the GLOBAL options to the add-on.
    global_writes: list[tuple[str, object]] = [("eula", True)]
    if server_type:
        global_writes.append(("server_type", server_type))
    global_writes.append(("active_world", world_name))
    if memory_mb is not None:
        global_writes.append(("memory_mb", memory_mb))
    if "enable_bedrock_support" in body:
        global_writes.append(("enable_bedrock_support", bool(body["enable_bedrock_support"])))
    if "backup_interval_minutes" in int_values:
        global_writes.append(("backup_interval_minutes", int_values["backup_interval_minutes"]))
    if "backup_keep_count" in int_values:
        global_writes.append(("backup_keep_count", int_values["backup_keep_count"]))
    if body.get("auto_restart_schedule"):
        global_writes.append(("auto_restart_schedule", str(body["auto_restart_schedule"])))
    for plugin_key in _WIZARD_PLUGIN_KEYS:
        if plugin_key in body:
            global_writes.append((plugin_key, bool(body[plugin_key])))

    for key, value in global_writes:
        err = await _persist_option(key, value)
        if err:
            warnings.append(f"{key}: {err}")

    # ── Stage the world skeleton + per-world `server.properties`.
    world_dir = MC_WORLDS_DIR / world_name
    world_dir.mkdir(parents=True, exist_ok=True)
    (world_dir / "plugins").mkdir(exist_ok=True)
    (world_dir / "mods").mkdir(exist_ok=True)
    (MC_BACKUPS_ROOT / world_name).mkdir(parents=True, exist_ok=True)

    props_path = world_dir / "server.properties"
    props: dict[str, str] = {}
    if props_path.is_file():
        for line in props_path.read_text().splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            props[k.strip()] = v

    # Per-world keys come from the wizard's "first world" + "performance"
    # steps. Coerce types here so the rendered file is valid out of the box.
    def _bool(b: object) -> str:
        return "true" if bool(b) else "false"
    if "gamemode" in body:        props["gamemode"] = str(body["gamemode"])
    if "force_gamemode" in body:  props["force-gamemode"] = _bool(body["force_gamemode"])
    if "difficulty" in body:      props["difficulty"] = str(body["difficulty"])
    if "level_type" in body:      props["level-type"] = str(body["level_type"])
    if "level_seed" in body:
        # `str(None) or ""` is the literal string "None" (truthy) — guard
        # the JSON-null case so a missing seed doesn't get written as "None".
        seed = body["level_seed"]
        props["level-seed"] = "" if seed is None else str(seed)
    if "pvp" in body:             props["pvp"] = _bool(body["pvp"])
    if "hardcore" in body:        props["hardcore"] = _bool(body["hardcore"])
    if "white_list" in body:      props["white-list"] = _bool(body["white_list"])
    if "max_players" in int_values:
        props["max-players"] = str(int_values["max_players"])
    if "spawn_protection" in int_values:
        props["spawn-protection"] = str(int_values["spawn_protection"])
    if "view_distance" in int_values:
        props["view-distance"] = str(int_values["view_distance"])
    if "simulation_distance" in int_values:
        props["simulation-distance"] = str(int_values["simulation_distance"])
    if "online_mode" in body:
        props["online-mode"] = _bool(body["online_mode"])
        # Offline-mode safety: enforce-secure-profile must be off or every
        # client is kicked. (setup-server-properties.sh enforces this on
        # boot too — belt-and-suspenders.)
        if not body["online_mode"]:
            props["enforce-secure-profile"] = "false"

    lines = [
        "# server.properties — staged by the BRUH first-run wizard.",
        f"# Wizard run: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
    ]
    lines.extend(f"{k}={v}" for k, v in sorted(props.items()))
    props_path.write_text("\n".join(lines) + "\n")

    # ── Drop the setup-completed marker before we restart, so even if
    # something downstream wipes /data/options.json's eula key, the wizard
    # never reappears on this install. The marker survives upgrades
    # (persisted under /data) and is only cleared on add-on uninstall.
    try:
        SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SETUP_MARKER.write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    except OSError as e:
        warnings.append(f"setup-marker: {e}")

    # ── Restart the add-on so run.sh boots the JVM with the new options.
    restart_err = await _supervisor_restart_self()
    if restart_err:
        warnings.append(f"restart: {restart_err}")

    return web.json_response({
        "ok": not warnings,
        "warnings": warnings or None,
        "world": world_name,
        "message": (
            f"Setup complete — staged '{world_name}' and restarting the "
            f"add-on. The panel will be unreachable for ~30 seconds while "
            f"the server boots."
        ),
    })


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
    # level-name is a per-world server.properties setting now, not a global env.
    level = _read_properties().get("level-name", "world") or "world"
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
    # Guard the optional on-disk filename against path traversal — it's passed
    # straight to install-plugin.sh which writes into plugins/.
    if name and ("/" in name or "\\" in name or ".." in name):
        return web.json_response({"error": "invalid name"}, status=400)
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


# Per-world settings the Worlds tab summarises in each row. Surfacing these
# at-a-glance makes it obvious that gameplay settings are PER-WORLD — when
# you switch to "creative_one" you're getting *that world's* gamemode +
# difficulty, not whatever you last set on a different world. Helps users
# whose mental model expected global settings.
_WORLD_LIST_PROP_KEYS = (
    "gamemode", "difficulty", "level-type", "level-name",
    "online-mode", "white-list",
)


def _read_world_props(name: str) -> dict[str, str]:
    """Read just the highlight keys from `<MC_WORLDS_DIR>/<name>/server.properties`
    for display in the Worlds tab. Returns an empty dict if the world has
    no properties file yet (a freshly-created world before its first boot)."""
    path = MC_WORLDS_DIR / name / "server.properties"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k in _WORLD_LIST_PROP_KEYS:
                out[k] = _unescape_java_property(v)
    except OSError:
        pass
    return out


async def api_worlds_list(_: web.Request) -> web.Response:
    rc, out = await _run_world_manager("list")
    worlds: list[dict] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            name = parts[0]
            worlds.append({
                "name": name,
                "size_bytes": int(parts[1]),
                "active": parts[2] == "true",
                "settings": _read_world_props(name),
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


async def _persist_option(option_key: str, value) -> str | None:
    """Write a single add-on option (e.g. memory_mb) via the Supervisor API.
    Returns None on success or a short error string.

    Supervisor's POST /addons/self/options REPLACES the entire options object
    and validates it against the schema, so we must GET the current options,
    merge our key in, and POST the merged object — otherwise every other
    required field reads as "missing" and the call is rejected."""
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return "SUPERVISOR_TOKEN not set"
    base = os.environ.get("SUPERVISOR_API_URL", "http://supervisor")
    import aiohttp
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{base}/addons/self/info", headers=headers) as resp:
                if resp.status != 200:
                    return f"info HTTP {resp.status}"
                info = await resp.json()
            options = (info.get("data") or {}).get("options") or {}
            options[option_key] = value
            async with session.post(
                f"{base}/addons/self/options",
                headers=headers,
                json={"options": options},
            ) as resp:
                if resp.status == 200:
                    return None
                body = (await resp.text())[:200]
                return f"Supervisor HTTP {resp.status}: {body}"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"


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


# What we put inside an exported world zip. plugins/, mods/, and the backup
# tree are deliberately excluded — they're either install-specific (the
# receiver's add-on installs its own plugins from the URL list) or
# enormous (backups). Save data + server.properties is what the receiver
# needs to actually play this world.
_EXPORT_INCLUDE_PREFIXES = ("world", "world_nether", "world_the_end")


def _build_world_zip(world_dir: Path, out_path: Path) -> None:
    """Build a streaming-friendly zip of the world's save dirs into out_path.

    Runs in a thread (asyncio.to_thread). Uses ZIP_DEFLATED with a low
    compression level — Minecraft worlds are mostly already-compressed
    .mca region files, so heavy compression wastes CPU for ~1% gain."""
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for prefix in _EXPORT_INCLUDE_PREFIXES:
            sub = world_dir / prefix
            if not sub.is_dir():
                continue
            for entry in sub.rglob("*"):
                if entry.is_file():
                    zf.write(entry, entry.relative_to(world_dir))
        # server.properties lets the receiver pick up gamemode / difficulty /
        # seed without having to ask.
        sp = world_dir / "server.properties"
        if sp.is_file():
            zf.write(sp, "server.properties")


async def api_worlds_export(request: web.Request) -> web.StreamResponse:
    """Stream the named world's save data back as a `.zip` for sharing or
    off-host backup. The active world is safe to download too — the JVM
    keeps writing during the export, but the zip is built from a
    point-in-time read of region files which Minecraft tolerates well
    enough for sharing purposes. For consistent backups use the Backups
    tab instead (RCON save-all flush + git/tar snapshot)."""
    name = request.match_info["name"]
    if not VALID_WORLD_NAME.match(name):
        return web.json_response({"error": "invalid name"}, status=400)
    world_dir = MC_WORLDS_DIR / name
    if not world_dir.is_dir():
        return web.json_response({"error": "world not found"}, status=404)

    # Build the zip in a temp file we own so we can stream + cleanup. We
    # put it under MC_PANEL_STATE/exports rather than /tmp because /tmp on
    # many HA hosts is tmpfs and a multi-GB world would OOM the box.
    out_dir = MC_PANEL_STATE / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Best-effort: purge any leftover exports older than an hour. If a
    # previous request was killed mid-stream the temp file lingers; this
    # keeps the directory from accumulating gigabytes over time.
    cutoff = time.time() - 3600
    for stale in out_dir.glob("*.zip"):
        try:
            if stale.stat().st_mtime < cutoff:
                stale.unlink()
        except OSError:
            pass

    handle = tempfile.NamedTemporaryFile(delete=False, dir=out_dir, suffix=".zip")
    out_path = Path(handle.name)
    handle.close()
    try:
        await asyncio.to_thread(_build_world_zip, world_dir, out_path)
        size = out_path.stat().st_size
        ts = time.strftime("%Y-%m-%d")
        resp = web.StreamResponse(status=200, headers={
            "Content-Type": "application/zip",
            "Content-Length": str(size),
            "Content-Disposition": f'attachment; filename="{name}-{ts}.zip"',
            "Cache-Control": "no-store",
        })
        await resp.prepare(request)
        with open(out_path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                await resp.write(chunk)
        await resp.write_eof()
        return resp
    finally:
        out_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Routes: API — resource-pack hosting
# ---------------------------------------------------------------------------
# Packs are stored at /config/resource-packs/ (global; shared across worlds)
# and exposed publicly at GET /pack/<filename> on the same port the panel
# binds — host_network: true means that port is directly reachable on the
# LAN, which is what Minecraft clients need to fetch the pack on join.
VALID_PACK_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}\.zip$")
MAX_PACK_SIZE = 250 * 1024 * 1024  # 250 MB — Mojang's own client cap


def _pack_sha1(path: Path) -> str:
    h = hashlib.sha1()  # noqa: S324 — Minecraft requires SHA-1 for resource-pack-sha1
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


async def api_resource_packs_list(_: web.Request) -> web.Response:
    MC_RESOURCE_PACKS.mkdir(parents=True, exist_ok=True)
    packs = []
    for p in sorted(MC_RESOURCE_PACKS.glob("*.zip")):
        stat = p.stat()
        packs.append({
            "name": p.name,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "sha1": _pack_sha1(p),
            # The "url" is computed from the request host on the client side
            # so the panel can show "use this URL" without us guessing what
            # IP the user reaches us at.
        })
    return web.json_response({"packs": packs})


async def api_resource_pack_upload(request: web.Request) -> web.Response:
    """Stream a multipart upload to /config/resource-packs/<name>.zip and
    return its SHA-1 so the user can copy it (or use the apply endpoint to
    write it to the active world automatically)."""
    MC_RESOURCE_PACKS.mkdir(parents=True, exist_ok=True)
    reader = await request.multipart()
    name = None
    saved: Path | None = None
    total = 0
    async for part in reader:
        if part.name == "name":
            name = (await part.text()).strip()
        elif part.name == "file":
            # Use the form's "name" if provided, otherwise fall back to the
            # uploaded filename. Validate either way.
            target_name = name or (part.filename or "").strip()
            if not VALID_PACK_NAME.match(target_name or ""):
                return web.json_response(
                    {"error": "name must end in .zip and contain only A-Z a-z 0-9 . _ -"},
                    status=400,
                )
            saved = MC_RESOURCE_PACKS / target_name
            tmp = saved.with_suffix(saved.suffix + ".uploading")
            with open(tmp, "wb") as f:
                while True:
                    chunk = await part.read_chunk(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_PACK_SIZE:
                        f.close()
                        tmp.unlink(missing_ok=True)
                        return web.json_response(
                            {"error": f"upload exceeds {MAX_PACK_SIZE // (1024*1024)} MB limit"},
                            status=413,
                        )
                    f.write(chunk)
            tmp.replace(saved)
    if saved is None:
        return web.json_response({"error": "no file uploaded"}, status=400)
    return web.json_response({
        "ok": True,
        "name": saved.name,
        "size": saved.stat().st_size,
        "sha1": _pack_sha1(saved),
    })


async def api_resource_pack_delete(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    if not VALID_PACK_NAME.match(name):
        return web.json_response({"error": "invalid name"}, status=400)
    target = MC_RESOURCE_PACKS / name
    if not target.is_file():
        return web.json_response({"error": "not found"}, status=404)
    target.unlink()
    return web.json_response({"ok": True})


async def api_resource_pack_apply(request: web.Request) -> web.Response:
    """Write the pack's URL + SHA-1 into the active world's server.properties.
    The URL is built from the request's host header so the user doesn't have
    to figure out what IP/hostname Minecraft clients will reach this add-on at.
    """
    name = request.match_info["name"]
    if not VALID_PACK_NAME.match(name):
        return web.json_response({"error": "invalid name"}, status=400)
    pack = MC_RESOURCE_PACKS / name
    if not pack.is_file():
        return web.json_response({"error": "not found"}, status=404)
    sha1 = _pack_sha1(pack)
    # The host header tells us how Minecraft clients reach this box. If we
    # ever sit behind ingress (no direct port), the user has to override the
    # host — but host_network: true on this add-on means the panel's port is
    # directly reachable on the LAN.
    body = await request.json() if request.body_exists else {}
    host = (body.get("host") or request.host).split(":", 1)[0]
    port = body.get("port") or 8099
    url = f"http://{host}:{port}/pack/{name}"

    props = _read_properties()
    props["resource-pack"] = url
    props["resource-pack-sha1"] = sha1
    lines = [
        "# server.properties — active world is the source of truth.",
        f"# Resource pack staged via panel: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
    ]
    lines.extend(f"{k}={v}" for k, v in sorted(props.items()))
    tmp = MC_SERVER_DIR / "server.properties.tmp"
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(MC_SERVER_DIR / "server.properties")

    return web.json_response({"ok": True, "url": url, "sha1": sha1})


async def serve_pack(request: web.Request) -> web.Response:
    """Public endpoint Minecraft clients fetch the pack from. No auth — packs
    are by definition public assets the server hands to anyone who joins."""
    name = request.match_info["name"]
    if not VALID_PACK_NAME.match(name):
        return web.Response(status=400, text="invalid name")
    target = MC_RESOURCE_PACKS / name
    if not target.is_file():
        return web.Response(status=404, text="not found")
    return web.FileResponse(target, headers={
        "Content-Type": "application/zip",
        "Cache-Control": "public, max-age=86400",
    })


# ---------------------------------------------------------------------------
# Routes: API — world import (upload a .zip → switchable world)
# ---------------------------------------------------------------------------
MAX_WORLD_ZIP_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB


def _find_world_root(extracted: Path) -> Path | None:
    """Inside an extracted zip, locate the directory containing level.dat —
    that's the actual world root. Returns None if not found.

    Handles three common zip shapes:
      * level.dat at the top of the zip (zip created from inside the world).
      * SomeName/level.dat one level deep (most common — players zip the
        world folder).
      * SomeName/SomeNested/level.dat (rare but seen with re-zipped backups).
    """
    for level_dat in extracted.rglob("level.dat"):
        return level_dat.parent
    return None


async def api_worlds_import(request: web.Request) -> web.Response:
    """Accept a multipart upload of a Minecraft world `.zip` and stage it as
    a new switchable world profile. The new profile is empty otherwise — the
    operator should switch to it (panel → Worlds → Switch) to boot in."""
    reader = await request.multipart()
    name: str | None = None
    upload_path: Path | None = None
    total = 0
    async for part in reader:
        if part.name == "name":
            name = (await part.text()).strip()
        elif part.name == "file":
            handle = tempfile.NamedTemporaryFile(
                delete=False, suffix=".zip", dir="/tmp",
            )
            upload_path = Path(handle.name)
            try:
                while True:
                    chunk = await part.read_chunk(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_WORLD_ZIP_SIZE:
                        handle.close()
                        upload_path.unlink(missing_ok=True)
                        return web.json_response(
                            {"error": f"upload exceeds {MAX_WORLD_ZIP_SIZE // (1024**3)} GB limit"},
                            status=413,
                        )
                    handle.write(chunk)
            finally:
                handle.close()

    if not name or not VALID_WORLD_NAME.match(name):
        if upload_path:
            upload_path.unlink(missing_ok=True)
        return web.json_response(
            {"error": "name must match 1-32 chars of A-Z a-z 0-9 _ -"},
            status=400,
        )
    if upload_path is None:
        return web.json_response({"error": "no file uploaded"}, status=400)

    target_dir = MC_WORLDS_DIR / name
    if target_dir.exists():
        upload_path.unlink(missing_ok=True)
        return web.json_response(
            {"error": f"world '{name}' already exists — pick a different name"},
            status=409,
        )

    extract_root = Path(tempfile.mkdtemp(prefix="world-import-", dir="/tmp"))
    try:
        try:
            with zipfile.ZipFile(upload_path) as zf:
                # Guard against zip-slip: refuse any member that resolves
                # outside extract_root.
                for member in zf.namelist():
                    resolved = (extract_root / member).resolve()
                    if extract_root.resolve() not in resolved.parents \
                       and resolved != extract_root.resolve():
                        return web.json_response(
                            {"error": f"zip contains unsafe path: {member}"},
                            status=400,
                        )
                zf.extractall(extract_root)
        except zipfile.BadZipFile:
            return web.json_response(
                {"error": "file is not a valid .zip"},
                status=400,
            )
        world_src = _find_world_root(extract_root)
        if world_src is None:
            return web.json_response(
                {"error": "no level.dat found in the zip — not a Minecraft world"},
                status=400,
            )
        target_dir.mkdir(parents=True)
        # Move the world into the new profile under the default level-name
        # ("world") so server.properties' level-name=world works out of the
        # box. setup-server-properties.sh seeds the rest on first boot.
        shutil.move(str(world_src), str(target_dir / "world"))
        # Standard skeleton.
        (target_dir / "plugins").mkdir(exist_ok=True)
        (target_dir / "mods").mkdir(exist_ok=True)
        (MC_BACKUPS_ROOT / name).mkdir(parents=True, exist_ok=True)
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)
        upload_path.unlink(missing_ok=True)

    return web.json_response({
        "ok": True,
        "name": name,
        "size_bytes": sum(p.stat().st_size for p in target_dir.rglob("*") if p.is_file()),
        "message": (
            f"World '{name}' imported. Switch to it from the Worlds tab "
            f"to boot in (the add-on restarts; ~30s)."
        ),
    })


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
    app.router.add_get("/api/recommend", api_recommend_get)
    app.router.add_post("/api/recommend/apply", api_recommend_apply)
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
    app.router.add_post("/api/worlds/import", api_worlds_import)
    app.router.add_get("/api/worlds/{name}/export", api_worlds_export)
    app.router.add_post("/api/worlds/{name}/switch", api_worlds_switch)
    app.router.add_delete("/api/worlds/{name}", api_worlds_delete)
    # First-run wizard
    app.router.add_post("/api/setup", api_setup)
    # Resource-pack hosting (manage via authenticated panel endpoints,
    # serve to clients via a public path on the same port).
    app.router.add_get("/api/resource-packs", api_resource_packs_list)
    app.router.add_post("/api/resource-packs", api_resource_pack_upload)
    app.router.add_delete("/api/resource-packs/{name}", api_resource_pack_delete)
    app.router.add_post("/api/resource-packs/{name}/apply", api_resource_pack_apply)
    app.router.add_get("/pack/{name}", serve_pack)
    return app


def main() -> None:
    MC_PANEL_STATE.mkdir(parents=True, exist_ok=True)
    web.run_app(build_app(), host=BIND_HOST, port=BIND_PORT, access_log=None)


if __name__ == "__main__":
    main()
