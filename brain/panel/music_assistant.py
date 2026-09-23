"""Music Assistant: its players, its providers, its queues, its settings.

Music Assistant is a server of its own — an add-on, usually — with a
WebSocket API that is the only door into most of what it holds. Home
Assistant's integration shows a slice of it as `media_player` entities, and
Home Assistant's registry tools can rename or delete those entities, but a
player Music Assistant still *remembers* comes straight back: the config
that says it exists lives in Music Assistant, and only its API can forget
it. That is the gap this module closes. Everything the Music Assistant
frontend can do is a command on that socket, so brAIn speaks it.

**Reaching the server took reading its source rather than guessing.** From
schema 28 (Music Assistant 2.7) every WebSocket connection has to send an
`auth` command with a token before anything else. Music Assistant mints
one for Home Assistant's own integration and announces it through the
Supervisor's discovery with the address of its *ingress* site — port 8094,
bound on the hassio network — and Home Assistant stores both in the
`music_assistant` config entry (`url`, `token`). That token belongs to a
system user who is refused on the ordinary port 8095 and accepted on 8094,
which is exactly the address the entry holds. So brAIn reads the entry out
of `/config/.storage/core.config_entries` (the one it can already read) and
connects where Home Assistant connects, as Home Assistant does. No setup.

**What that token may do is Music Assistant's decision, and it says so.**
The system user has the `service` role: control every player, change every
player's settings, remove and group players, write the library. What it may
not do is reconfigure a music provider, change server settings or manage
users — those are an admin's. `music_assistant_token` takes an admin's
long-lived token (Music Assistant → Settings → your profile → Tokens) and it
is tried first. A refusal Music Assistant sends for want of a scope is
reported with that sentence attached, never as "it did not work".

**Two things are asked before a player is touched.** `protected_entities`
covers the Home Assistant entity a Music Assistant player is (the device
Home Assistant registers under `("music_assistant", player_id)`), and a
player whose id *is* an entity id — the Home Assistant players provider —
is checked as that entity. A registry that could not be read refuses while
the list is non-empty, because "I could not tell" and "nothing is
protected" are different claims. And every command name is checked for
shape, because it arrives off the wire and goes into a JSON message.

**A player that will not go away is three different things**, and the
clean-up says which: a player Music Assistant remembers and has not seen
since (its config outlived it — removing the config ends it), one that is
registered but unavailable (removable only where its provider supports
removing players; otherwise the honest answer is to disable it, or to deal
with the provider that keeps announcing it), and one that is working.
`stale_players` lists the first two with the reason on each row; the third
is never on it.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web

import automation_writer
import ha_data

log = logging.getLogger("brain.music_assistant")

DOMAIN = "music_assistant"
STORAGE_DIR = Path(os.environ.get("BRAIN_HA_STORAGE_DIR", "/config/.storage"))
SUPERVISOR_API = os.environ.get("BRAIN_SUPERVISOR_API", "http://supervisor")
# Music Assistant's ingress site: bound on the hassio network, the address
# its own discovery announces and the only port its Home Assistant token
# is accepted on.
INGRESS_PORT = 8094
# From this schema on, a connection is refused everything until `auth`.
AUTH_SCHEMA = 28

CONNECT_TIMEOUT_S = 10
COMMAND_TIMEOUT_S = 45
ROUTE_TTL_S = 300
MAX_RESULT_CHARS = 60_000

# A command name goes into a JSON message on somebody else's server, so it
# is checked for the shape Music Assistant's own names have.
COMMAND_RE = re.compile(r"^[a-z][a-z0-9_]*(?:/[a-z0-9_]+){0,4}\Z")

# Error codes, from music_assistant_models.errors — the ones a person can do
# something about get their own sentence.
ERR_PROVIDER_UNAVAILABLE = 1
ERR_NOT_FOUND = 2
ERR_UNSUPPORTED = 9
ERR_PLAYER_UNAVAILABLE = 10
ERR_INVALID_COMMAND = 12
ERR_ACTION_UNAVAILABLE = 19
ERR_AUTH_REQUIRED = 20
ERR_AUTH_FAILED = 21
ERR_INSUFFICIENT = 22
ERR_INVALID_TOKEN = 23

# Commands that only read. The analyst's tool may run these and nothing
# else; `auth/*` and `diagnostics/get` are left out on purpose — neither is
# something an unattended card needs, and both carry more than it should.
READ_EXACT = frozenset({
    "info", "time", "providers", "providers/manifests", "providers/manifests/get",
    "config/players", "config/players/get", "config/players/get_value",
    "config/players/get_entries", "config/players/dsp/get",
    "config/providers", "config/providers/get", "config/providers/get_value",
    "config/providers/get_entries", "config/core", "config/core/get",
    "config/core/get_value", "config/core/get_entries",
    "config/player_queues", "config/player_queues/get",
    "config/player_queues/get_value", "config/player_queues/get_entries",
    "config/dsp_presets/get", "config/dsp_irs/list",
    "players/all", "players/get", "players/get_by_name", "players/player_control",
    "players/player_controls", "players/plugin_source", "players/plugin_sources",
    "players/tts_engines", "players/sleep_timer/get",
    "player_queues/all", "player_queues/get", "player_queues/items",
    "player_queues/get_active_queue",
    "music/search", "music/browse", "music/item", "music/item_by_uri",
    "music/item_by_name", "music/track_by_name", "music/get_library_item",
    "music/recently_played_items", "music/recently_added_tracks",
    "music/in_progress_items",
    "metadata/get_track_lyrics", "logging/get", "streams/info",
    "tasks/list", "tasks/get", "tasks/log",
    "dashboard/dashboards", "translations/locales",
})
# `music/<media type>/<read>`: library listings and lookups, one set per
# type. The shape alone is not enough — `add_playlist_tracks` ends in
# `tracks` — so a name opening with a verb that changes something is never
# a read, whatever it ends in.
READ_MUSIC_RE = re.compile(
    r"^music/[a-z_]+/(?:count|library_items|get|get_[a-z_]+|top_[a-z_]+|"
    r"similar_[a-z_]+|podcast_episode|[a-z_]+_(?:versions|tracks|albums|artists|"
    r"episodes|audiobooks|artist_types))\Z")
WRITE_VERB_RE = re.compile(
    r"/(?:add|remove|create|delete|update|import|export|refresh|set|save|sync|"
    r"mark|move|clear)(?:_[a-z_]*)?\Z")

# Every argument name through which a command reaches a player.
PLAYER_ARGS = ("player_id", "queue_id", "target_player", "source_queue_id",
               "target_queue_id")
PLAYER_LIST_ARGS = ("child_player_ids", "player_ids", "player_ids_to_add",
                    "player_ids_to_remove", "members")


class MAError(Exception):
    """A command Music Assistant refused, with its own code and words."""

    def __init__(self, code: int, details: str):
        super().__init__(details)
        self.code = code
        self.details = details


def is_read_only(command: str) -> bool:
    if command in READ_EXACT:
        return True
    return bool(READ_MUSIC_RE.match(command)) and not WRITE_VERB_RE.search(command)


# ---------------------------------------------------------------------------
# Where the server is, and what to say when it is not
# ---------------------------------------------------------------------------

def url_option() -> str:
    return os.environ.get("BRAIN_MUSIC_ASSISTANT_URL", "").strip().rstrip("/")


def token_option() -> str:
    return os.environ.get("BRAIN_MUSIC_ASSISTANT_TOKEN", "").strip()


def ha_entry() -> dict | None:
    """Home Assistant's own Music Assistant entry: its url and its token.

    `None` for "there is no entry" — a house without the integration — and
    a dict carrying `error` for a file that could not be read, because the
    two send a person to different places.
    """
    path = STORAGE_DIR / "core.config_entries"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return {"error": f"could not read {path}: {exc}"}
    entries = ((doc or {}).get("data") or {}).get("entries") or []
    rows = [e for e in entries if isinstance(e, dict) and e.get("domain") == DOMAIN]
    # An enabled entry before a disabled one: a house that tried a second
    # server and switched it off is not driven through the one it abandoned.
    rows.sort(key=lambda e: e.get("disabled_by") is not None)
    for row in rows:
        data = row.get("data") or {}
        if data.get("url"):
            return {"url": str(data["url"]).rstrip("/"),
                    "token": str(data.get("token") or ""),
                    "title": row.get("title") or "Music Assistant",
                    "disabled": row.get("disabled_by") is not None}
    return None


def pick_addon(addons: list) -> dict | None:
    """The Music Assistant add-on — stable before beta, running before not."""
    rows = []
    for row in addons or []:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "")
        base = re.sub(r"[-_](beta|dev|nightly)$", "", slug)
        if not base.endswith("music_assistant") and not base.endswith("music-assistant"):
            continue
        channel = 0 if base == slug else 1
        running = 0 if row.get("state") == "started" else 1
        rows.append((running, channel, slug, row))
    rows.sort(key=lambda r: r[:3])
    return rows[0][3] if rows else None


async def _supervisor_get(session: aiohttp.ClientSession, path: str) -> Any:
    async with session.get(
            f"{SUPERVISOR_API}{path}",
            headers={"Authorization": f"Bearer {ha_data.SUPERVISOR_TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        body = await resp.json(content_type=None)
    return body.get("data") if isinstance(body, dict) else None


async def candidates(session: aiohttp.ClientSession) -> tuple[list[dict], list[str]]:
    """Every (url, token) worth trying, in order, and what could not be read.

    An admin token beats the integration's token wherever both could work,
    because it can do everything the other can and more.
    """
    notes: list[str] = []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(url: str, token: str, via: str) -> None:
        key = (url, token)
        if url and key not in seen:
            seen.add(key)
            out.append({"url": url, "token": token, "via": via})

    opt_url, opt_token = url_option(), token_option()
    entry = ha_entry()
    if entry and entry.get("error"):
        notes.append(entry["error"])
        entry = None
    if opt_url:
        add(opt_url, opt_token, "option")
        if entry and not opt_token and entry["url"] == opt_url:
            add(opt_url, entry["token"], "option")
    if entry:
        if opt_token:
            add(entry["url"], opt_token, "entry+token")
        add(entry["url"], entry["token"], "entry")
    if not out and ha_data.SUPERVISOR_TOKEN:
        # No entry: the integration is not set up. The add-on may still be
        # there, and with an admin token it can be reached without it.
        try:
            listing = await _supervisor_get(session, "/addons")
            addon = pick_addon((listing or {}).get("addons") or [])
            if addon is None:
                notes.append("no Music Assistant add-on is installed")
            else:
                info = await _supervisor_get(
                    session, f"/addons/{addon.get('slug')}/info") or {}
                if (info.get("state") or addon.get("state")) != "started":
                    notes.append(f"the {addon.get('name') or 'Music Assistant'} "
                                 "add-on is not running — start it")
                else:
                    host = str(info.get("hostname")
                               or str(addon.get("slug")).replace("_", "-"))
                    add(f"http://{host}:{INGRESS_PORT}", opt_token, "addon")
                    if not opt_token:
                        notes.append(
                            "the Music Assistant add-on is running but Home "
                            "Assistant's Music Assistant integration is not set "
                            "up, so there is no token to sign in with — add the "
                            "integration (Settings → Devices & services), or set "
                            "music_assistant_token")
        except Exception as exc:  # noqa: BLE001 — every failure is a sentence
            notes.append(f"the Supervisor's add-on list: {exc}")
    return out, notes


def ws_url(url: str) -> str:
    base = url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return base if base.endswith("/ws") else base + "/ws"


# ---------------------------------------------------------------------------
# One connection: server info, auth, commands
# ---------------------------------------------------------------------------

class Connection:
    """An open, signed-in WebSocket to one Music Assistant server."""

    def __init__(self, session: aiohttp.ClientSession, target: dict):
        self.session = session
        self.target = target
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.server_info: dict = {}
        self.user: dict = {}
        self._ids = itertools.count(1)

    async def open(self) -> "Connection":
        self.ws = await asyncio.wait_for(
            self.session.ws_connect(ws_url(self.target["url"]), heartbeat=30,
                                    max_msg_size=64 * 1024 * 1024),
            CONNECT_TIMEOUT_S)
        first = await asyncio.wait_for(self._receive(), CONNECT_TIMEOUT_S)
        if not isinstance(first, dict) or "server_version" not in first:
            raise RuntimeError("it answered, but not like a Music Assistant server")
        self.server_info = first
        if int(first.get("schema_version") or 0) >= AUTH_SCHEMA:
            token = self.target.get("token") or ""
            if not token:
                raise MAError(ERR_AUTH_REQUIRED,
                              "this Music Assistant needs a token and brAIn has none")
            answer = await self.command("auth", token=token)
            if not answer:
                raise MAError(ERR_AUTH_FAILED, "the token was refused")
            if isinstance(answer, dict):
                self.user = answer.get("user") or {}
        return self

    async def close(self) -> None:
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()

    async def _receive(self) -> Any:
        assert self.ws is not None
        msg = await self.ws.receive()
        if msg.type == aiohttp.WSMsgType.TEXT:
            return json.loads(msg.data)
        if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
            raise ConnectionError("Music Assistant closed the connection")
        raise ConnectionError(f"unexpected WebSocket message {msg.type}")

    async def command(self, command: str, timeout: float = COMMAND_TIMEOUT_S,
                      **args: Any) -> Any:
        """Send one command and wait for its result, partial chunks joined.

        A large list arrives as several messages marked `partial` before the
        final one, and the client library joins them; so does this. Events
        the server pushes in between are not this command's answer and are
        skipped.
        """
        assert self.ws is not None
        message_id = str(next(self._ids))
        await self.ws.send_json({"message_id": message_id, "command": command,
                                 "args": args})
        partial: list | None = None
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise asyncio.TimeoutError(f"{command} did not answer in {int(timeout)}s")
            msg = await asyncio.wait_for(self._receive(), left)
            if not isinstance(msg, dict) or str(msg.get("message_id")) != message_id:
                continue
            if "error_code" in msg:
                raise MAError(int(msg.get("error_code") or 0),
                              str(msg.get("details") or "no reason given"))
            result = msg.get("result")
            if msg.get("partial"):
                partial = (partial or []) + list(result or [])
                continue
            if partial is not None:
                return partial + list(result or [])
            return result


async def _connect(session: aiohttp.ClientSession) -> tuple[Connection | None, dict]:
    """The first candidate that signs in, or a status saying why none did."""
    targets, tried = await candidates(session)
    for target in targets:
        conn = Connection(session, target)
        try:
            await conn.open()
            return conn, {"reachable": True, "via": target["via"],
                          "url": target["url"]}
        except MAError as exc:
            tried.append(f"{target['url']} ({_via_words(target['via'])}): "
                         f"{exc.details}")
        except Exception as exc:  # noqa: BLE001
            tried.append(f"{target['url']} ({_via_words(target['via'])}): "
                         f"{exc or type(exc).__name__}")
        await conn.close()
    if not targets and not tried:
        tried.append("Home Assistant has no Music Assistant integration and "
                     "there is no Supervisor to ask")
    return None, {"reachable": False,
                  "reason": "brAIn could not reach Music Assistant: "
                            + "; ".join(tried) + "."}


def _via_words(via: str) -> str:
    return {"option": "the music_assistant_url option",
            "entry+token": "Home Assistant's address with your music_assistant_token",
            "entry": "Home Assistant's own connection",
            "addon": "the add-on"}.get(via, via)


class Client:
    """`async with Client() as ma:` — one session, one sign-in, many commands."""

    def __init__(self) -> None:
        self.session: aiohttp.ClientSession | None = None
        self.conn: Connection | None = None
        self.status: dict = {}

    async def __aenter__(self) -> "Client":
        self.session = aiohttp.ClientSession()
        self.conn, self.status = await _connect(self.session)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self.conn is not None:
            await self.conn.close()
        if self.session is not None:
            await self.session.close()

    @property
    def ok(self) -> bool:
        return self.conn is not None

    async def call(self, command: str, timeout: float = COMMAND_TIMEOUT_S,
                   **args: Any) -> Any:
        if self.conn is None:
            raise RuntimeError(self.status.get("reason") or "not connected")
        return await self.conn.command(command, timeout=timeout, **args)

    def identity(self) -> dict:
        if self.conn is None:
            return {}
        info = self.conn.server_info
        user = self.conn.user or {}
        return {"server_version": info.get("server_version"),
                "schema_version": info.get("schema_version"),
                "name": info.get("name") or "Music Assistant",
                "addon": bool(info.get("homeassistant_addon")),
                "status": info.get("status"),
                "signed_in_as": user.get("display_name") or user.get("username") or "",
                "role": user.get("role") or ("" if not user else "unknown"),
                "admin": str(user.get("role") or "") == "admin"}


def explain(exc: Exception) -> str:
    """One sentence for a failure, with what a person could do about it."""
    if isinstance(exc, MAError):
        if exc.code == ERR_INSUFFICIENT:
            return (f"Music Assistant refused: {exc.details}. The token brAIn is "
                    "using cannot do this — set music_assistant_token to a Music "
                    "Assistant admin's long-lived token (Music Assistant → "
                    "Settings → your profile → Tokens) and restart brAIn.")
        if exc.code in (ERR_AUTH_FAILED, ERR_INVALID_TOKEN, ERR_AUTH_REQUIRED):
            return (f"Music Assistant would not sign brAIn in: {exc.details}. "
                    "Reload the Music Assistant integration in Home Assistant, "
                    "or check music_assistant_token.")
        if exc.code == ERR_ACTION_UNAVAILABLE:
            return f"Music Assistant says it cannot do that: {exc.details}"
        if exc.code == ERR_INVALID_COMMAND:
            return f"Music Assistant has no such command: {exc.details}"
        return f"Music Assistant refused: {exc.details}"
    if isinstance(exc, asyncio.TimeoutError):
        return f"Music Assistant did not answer in time ({exc or 'timeout'})"
    return str(exc) or type(exc).__name__


def _clip(value: Any) -> tuple[Any, bool]:
    """A result small enough to hand a model, and whether it was cut."""
    text = json.dumps(value, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return value, False
    if isinstance(value, list):
        kept: list = []
        size = 2
        for item in value:
            size += len(json.dumps(item, default=str)) + 1
            if size > MAX_RESULT_CHARS:
                break
            kept.append(item)
        return kept, True
    return text[:MAX_RESULT_CHARS], True


# ---------------------------------------------------------------------------
# protected_entities, applied to players
# ---------------------------------------------------------------------------

def players_named(command: str, args: dict) -> list[str]:
    """Every player a command would reach, by any of its argument names."""
    if not (command.startswith("players/") or command.startswith("player_queues/")
            or command.startswith("config/players") or command.startswith("config/player_queues")):
        return []
    out: list[str] = []
    for key in PLAYER_ARGS:
        if isinstance(args.get(key), str) and args[key]:
            out.append(args[key])
    for key in PLAYER_LIST_ARGS:
        value = args.get(key)
        if isinstance(value, list):
            out.extend(str(v) for v in value if v)
    return out


async def _ha_player_entities(session: aiohttp.ClientSession) -> dict | None:
    """{player_id: [entity ids]} from Home Assistant's registries, or None."""
    try:
        devices, entities = await ha_data._ws_commands(session, [
            {"type": "config/device_registry/list"},
            {"type": "config/entity_registry/list"},
        ])
    except Exception:  # noqa: BLE001 — None is "could not look", below
        return None
    if not isinstance(devices, list) or not isinstance(entities, list):
        return None
    by_device: dict[str, str] = {}
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        for ident in dev.get("identifiers") or []:
            if isinstance(ident, (list, tuple)) and len(ident) == 2 \
                    and ident[0] == DOMAIN:
                by_device[dev.get("id")] = str(ident[1])
    out: dict[str, list[str]] = {}
    for row in entities:
        if not isinstance(row, dict):
            continue
        pid = by_device.get(row.get("device_id"))
        if pid is None and row.get("platform") == DOMAIN:
            pid = str(row.get("unique_id") or "")
        if pid:
            out.setdefault(pid, []).append(str(row.get("entity_id") or ""))
    return out


async def protected_refusal(session: aiohttp.ClientSession,
                            player_ids: list[str]) -> str | None:
    """Why these players may not be acted on, or None."""
    patterns = automation_writer.protected_patterns()
    if not patterns or not player_ids:
        return None
    mapping = await _ha_player_entities(session)
    if mapping is None:
        return ("brAIn could not read Home Assistant's registries, so it cannot "
                "tell whether this Music Assistant player is a protected "
                "entity — and protected_entities is set, so it will not act")
    for pid in player_ids:
        reach = list(mapping.get(pid, []))
        if re.match(r"^[a-z_]+\.[a-z0-9_]+$", pid):
            reach.append(pid)  # the Home Assistant players provider
        hit = [e for e in reach if automation_writer.is_protected(e, patterns)]
        if hit:
            return (f"the Music Assistant player {pid} is {', '.join(hit[:3])}, "
                    "which protected_entities covers — brAIn will not act on it")
    return None


# ---------------------------------------------------------------------------
# What is there
# ---------------------------------------------------------------------------

def _state(player: dict) -> str:
    return str(player.get("playback_state") or player.get("state") or "")


def compact_player(p: dict, providers: dict) -> dict:
    media = p.get("current_media") or {}
    prov = providers.get(p.get("provider")) or {}
    return {
        "player_id": p.get("player_id"),
        "name": p.get("display_name") or p.get("name") or p.get("player_id"),
        "provider": p.get("provider"),
        "provider_name": prov.get("name") or p.get("provider"),
        "provider_domain": prov.get("domain") or "",
        "type": p.get("type"),
        "available": bool(p.get("available")),
        "enabled": p.get("enabled", True) is not False,
        "powered": p.get("powered"),
        "state": _state(p),
        "volume": p.get("volume_level"),
        "muted": p.get("volume_muted"),
        "synced_to": p.get("synced_to"),
        "group_members": list(p.get("group_members") or p.get("group_childs") or []),
        "active_group": p.get("active_group"),
        "now_playing": {k: media.get(k) for k in ("title", "artist", "album", "uri")
                        if media.get(k)} or None,
        "model": ((p.get("device_info") or {}).get("model") or ""),
        "address": ((p.get("device_info") or {}).get("ip_address")
                    or (p.get("device_info") or {}).get("address") or ""),
    }


def stale_players(players: list[dict], configs: list[dict],
                  providers: dict) -> list[dict]:
    """Players worth clearing out, each with why.

    A config with no registered player is the one that never comes back on
    its own; an unavailable registered player may be a speaker that is
    unplugged tonight, so it is listed but the reason says which.
    """
    registered = {p.get("player_id"): p for p in players if isinstance(p, dict)}
    out: list[dict] = []
    for conf in configs:
        if not isinstance(conf, dict):
            continue
        pid = conf.get("player_id")
        if not pid or pid in registered:
            continue
        prov = providers.get(conf.get("provider")) or {}
        out.append({"player_id": pid,
                    "name": conf.get("name") or conf.get("default_name") or pid,
                    "provider": conf.get("provider"),
                    "provider_name": prov.get("name") or conf.get("provider"),
                    "provider_loaded": bool(prov),
                    "kind": "remembered",
                    "reason": ("Music Assistant remembers this player but has not "
                               "seen it since" + ("" if prov else
                                                  ", and its provider is not loaded")
                               + " — removing it forgets it for good")})
    for pid, p in registered.items():
        if p.get("available"):
            continue
        prov = providers.get(p.get("provider")) or {}
        out.append({"player_id": pid,
                    "name": p.get("display_name") or p.get("name") or pid,
                    "provider": p.get("provider"),
                    "provider_name": prov.get("name") or p.get("provider"),
                    "provider_loaded": bool(prov),
                    "kind": "unavailable",
                    "reason": ("registered but unavailable — if the device is gone, "
                               "remove it; if its provider will not let go of it, "
                               "disable it or remove that provider")})
    return out


def compact_provider(p: dict, configs: dict) -> dict:
    conf = configs.get(p.get("instance_id")) or {}
    return {"instance_id": p.get("instance_id"), "domain": p.get("domain"),
            "name": p.get("name"), "type": p.get("type"),
            "available": bool(p.get("available")),
            "enabled": conf.get("enabled", True) is not False,
            "last_error": conf.get("last_error") or ""}


async def overview() -> dict:
    """Server, sign-in, players, stale players and providers, in one read."""
    async with Client() as ma:
        if not ma.ok:
            return {"ok": True, "server": ma.status, "players": [],
                    "stale_players": [], "providers": []}
        errors: list[str] = []

        async def ask(command: str, **args: Any) -> list:
            try:
                result = await ma.call(command, **args)
                return result if isinstance(result, list) else []
            except Exception as exc:  # noqa: BLE001 — one section, not the page
                errors.append(f"{command}: {explain(exc)}")
                return []

        providers_raw = await ask("providers")
        provider_confs = await ask("config/providers")
        players_raw = await ask("players/all")
        player_confs = await ask("config/players")
        by_instance = {p.get("instance_id"): p for p in providers_raw
                       if isinstance(p, dict)}
        confs_by_instance = {c.get("instance_id"): c for c in provider_confs
                             if isinstance(c, dict)}
        # A configured provider that failed to load is not in `providers` at
        # all, and it is the one row somebody most needs to see.
        providers = [compact_provider(p, confs_by_instance) for p in providers_raw
                     if isinstance(p, dict)]
        for iid, conf in confs_by_instance.items():
            if iid not in by_instance:
                providers.append({"instance_id": iid, "domain": conf.get("domain"),
                                  "name": conf.get("name") or conf.get("domain"),
                                  "type": conf.get("type"), "available": False,
                                  "enabled": conf.get("enabled", True) is not False,
                                  "last_error": conf.get("last_error") or
                                  ("not loaded" if conf.get("enabled", True)
                                   else "disabled")})
        players = [compact_player(p, by_instance) for p in players_raw
                   if isinstance(p, dict)]
        players.sort(key=lambda r: (not r["available"], str(r["name"]).lower()))
        patterns = automation_writer.protected_patterns()
        if patterns and ma.session is not None:
            mapping = await _ha_player_entities(ma.session)
            for row in players:
                reach = (mapping or {}).get(row["player_id"], [])
                row["ha_entities"] = reach
                row["protected"] = mapping is None or any(
                    automation_writer.is_protected(e, patterns)
                    for e in reach + [row["player_id"]])
        return {"ok": True,
                "server": {**ma.status, **ma.identity()},
                "players": players,
                "stale_players": stale_players(players_raw, player_confs, by_instance),
                "providers": sorted(providers, key=lambda r: (r["available"],
                                                             str(r["name"]).lower())),
                "errors": errors}


# ---------------------------------------------------------------------------
# Doing things
# ---------------------------------------------------------------------------

async def run_command(command: str, args: dict | None, *, read_only: bool = False
                      ) -> dict:
    """Any Music Assistant command, guarded, with the answer as data."""
    command = str(command or "").strip()
    args = args if isinstance(args, dict) else {}
    if not COMMAND_RE.match(command):
        return {"ok": False, "error": f"{command!r} is not a Music Assistant command name"}
    if command == "auth" or command.startswith("auth/login"):
        return {"ok": False, "refused": True,
                "error": "signing in is brAIn's own business on this connection"}
    if read_only and not is_read_only(command):
        return {"ok": False, "refused": True,
                "error": f"{command} changes something, and this tool only reads — "
                         "use music_assistant_command from the chat or the terminal"}
    async with Client() as ma:
        if not ma.ok:
            return {"ok": False, "unreachable": True, "error": ma.status.get("reason")}
        assert ma.session is not None
        if not is_read_only(command):
            refusal = await protected_refusal(ma.session, players_named(command, args))
            if refusal:
                return {"ok": False, "refused": True, "error": refusal}
        try:
            result = await ma.call(command, timeout=120, **args)
        except Exception as exc:  # noqa: BLE001
            code = exc.code if isinstance(exc, MAError) else None
            return {"ok": False, "error": explain(exc), "code": code}
    result, cut = _clip(result)
    out = {"ok": True, "command": command, "result": result}
    if cut:
        out["truncated"] = (f"the answer was longer than {MAX_RESULT_CHARS} "
                            "characters and was cut — ask for less (a limit, "
                            "an offset, one item)")
    return out


PLAYER_ACTIONS = {
    "play": ("players/cmd/play", None),
    "pause": ("players/cmd/pause", None),
    "play_pause": ("players/cmd/play_pause", None),
    "stop": ("players/cmd/stop", None),
    "next": ("players/cmd/next", None),
    "previous": ("players/cmd/previous", None),
    "power": ("players/cmd/power", "powered"),
    "volume": ("players/cmd/volume_set", "volume_level"),
    "volume_up": ("players/cmd/volume_up", None),
    "volume_down": ("players/cmd/volume_down", None),
    "mute": ("players/cmd/volume_mute", "muted"),
    "seek": ("players/cmd/seek", "position"),
    "group": ("players/cmd/group", "target_player"),
    "ungroup": ("players/cmd/ungroup", None),
    "shuffle": ("player_queues/shuffle", "shuffle_enabled"),
    "repeat": ("player_queues/repeat", "repeat_mode"),
    "clear_queue": ("player_queues/clear", None),
    "enable": ("config/players/save", "enabled"),
    "disable": ("config/players/save", "enabled"),
    "rename": ("config/players/save", "name"),
}


def _coerce(action: str, value: Any) -> Any:
    if action in ("power", "mute", "shuffle"):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "on", "yes")
        return bool(value)
    if action == "volume":
        return max(0, min(100, int(float(value))))
    if action == "seek":
        return max(0, int(float(value)))
    if action == "repeat":
        value = str(value or "").lower()
        if value not in ("off", "one", "all"):
            raise ValueError("repeat is off, one or all")
        return value
    return value


async def player_action(player_id: str, action: str, value: Any = None) -> dict:
    """A named action on one player — the panel's buttons and the tool's."""
    if action not in PLAYER_ACTIONS:
        return {"ok": False, "error": f"no player action {action!r}; one of "
                                      + ", ".join(sorted(PLAYER_ACTIONS))}
    command, arg = PLAYER_ACTIONS[action]
    try:
        value = _coerce(action, value)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"{action}: {exc}"}
    key = "queue_id" if command.startswith("player_queues/") else "player_id"
    args: dict = {key: player_id}
    if command == "config/players/save":
        values = {"enabled": action == "enable"} if action in ("enable", "disable") \
            else {"name": str(value or "").strip()}
        args["values"] = values
    elif arg:
        if value is None:
            return {"ok": False, "error": f"{action} needs a value ({arg})"}
        args[arg] = value
    return await run_command(command, args)


async def play_media(player_id: str, media: Any, option: str = "",
                     radio_mode: bool = False) -> dict:
    """Play something on a player: a URI, a name to search for, or several."""
    args: dict = {"queue_id": player_id, "media": media}
    if option:
        if option not in ("play", "replace", "next", "replace_next", "add"):
            return {"ok": False, "error": "option is play, replace, next, "
                                          "replace_next or add"}
        args["option"] = option
    if radio_mode:
        args["radio_mode"] = True
    return await run_command("player_queues/play_media", args)


async def remove_players(player_ids: list[str] | None = None, *, provider: str = "",
                         stale_only: bool = True, dry_run: bool = True,
                         disable_if_held: bool = False) -> dict:
    """Forget players Music Assistant should not have any more.

    Dry run by default, the way the orphan clean-up in the Power Tools is:
    what would go is listed first, and nothing is removed until asked again
    with `dry_run: false`. `stale_only` restricts the candidates to what
    `stale_players` lists, so a working speaker is never swept up by a
    provider filter.
    """
    wanted = {str(p) for p in (player_ids or []) if p}
    if not wanted and not provider and not stale_only:
        return {"ok": False, "error": "name the players or a provider — "
                                      "brAIn will not remove every player"}
    async with Client() as ma:
        if not ma.ok:
            return {"ok": False, "unreachable": True, "error": ma.status.get("reason")}
        assert ma.session is not None
        try:
            providers_raw = await ma.call("providers")
            players_raw = await ma.call("players/all")
            configs = await ma.call("config/players")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": explain(exc)}
        by_instance = {p.get("instance_id"): p for p in providers_raw or []
                       if isinstance(p, dict)}
        stale = stale_players(players_raw or [], configs or [], by_instance)
        pool = stale if stale_only else (
            stale + [{"player_id": p.get("player_id"),
                      "name": p.get("display_name") or p.get("name"),
                      "provider": p.get("provider"), "kind": "working",
                      "reason": "working player"}
                     for p in players_raw or [] if isinstance(p, dict)
                     and p.get("available")])

        def matches(row: dict) -> bool:
            if wanted and row["player_id"] not in wanted:
                return False
            if provider:
                prov = by_instance.get(row.get("provider")) or {}
                names = {str(row.get("provider") or "").lower(),
                         str(prov.get("domain") or "").lower(),
                         str(row.get("provider_name") or "").lower()}
                if provider.lower() not in names and not any(
                        provider.lower() in n for n in names if n):
                    return False
            return True

        chosen = [r for r in pool if matches(r)]
        missing = sorted(wanted - {r["player_id"] for r in chosen})
        refusal = await protected_refusal(ma.session, [r["player_id"] for r in chosen])
        if refusal:
            return {"ok": False, "refused": True, "error": refusal}
        report: dict = {"ok": True, "dry_run": dry_run,
                        "candidates": [{k: r.get(k) for k in
                                        ("player_id", "name", "provider_name",
                                         "kind", "reason")} for r in chosen]}
        if missing:
            report["not_eligible"] = [
                {"player_id": pid,
                 "reason": ("working player — pass stale_only false to remove it"
                            if stale_only and any(p.get("player_id") == pid
                                                  for p in players_raw or [])
                            else "Music Assistant has no player by that id")}
                for pid in missing]
        if dry_run:
            report["note"] = (f"{len(chosen)} player(s) would be removed. Nothing "
                              "has been changed; call again with dry_run false.")
            return report
        removed, held, failed = [], [], []
        for row in chosen:
            pid = row["player_id"]
            try:
                await ma.call("config/players/remove", player_id=pid)
                removed.append(pid)
                continue
            except MAError as exc:
                if exc.code == ERR_NOT_FOUND or "does not exist" in exc.details:
                    try:
                        await ma.call("players/remove", player_id=pid)
                        removed.append(pid)
                        continue
                    except Exception as exc2:  # noqa: BLE001
                        failed.append({"player_id": pid, "error": explain(exc2)})
                        continue
                if exc.code in (ERR_ACTION_UNAVAILABLE, ERR_UNSUPPORTED):
                    if disable_if_held:
                        try:
                            await ma.call("config/players/save", player_id=pid,
                                          values={"enabled": False})
                            held.append({"player_id": pid, "disabled": True})
                        except Exception as exc2:  # noqa: BLE001
                            failed.append({"player_id": pid, "error": explain(exc2)})
                    else:
                        held.append({"player_id": pid, "disabled": False,
                                     "error": exc.details})
                    continue
                failed.append({"player_id": pid, "error": explain(exc)})
            except Exception as exc:  # noqa: BLE001
                failed.append({"player_id": pid, "error": explain(exc)})
        report.update(removed=removed, held_by_provider=held, failed=failed)
        # Forgetting a player is permanent on Music Assistant's side, so it is
        # the one thing here worth a line in the add-on's own log.
        log.info("Music Assistant: forgot %d player(s) %s; %d held by their "
                 "provider; %d failed", len(removed), removed[:10], len(held),
                 len(failed))
        if held and not disable_if_held:
            report["note"] = ("Some players are still registered by a provider that "
                              "cannot remove players, so Music Assistant keeps them. "
                              "Call again with disable_if_held true to disable them, "
                              "or disable/remove that provider.")
        return report


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, dumps=lambda d: json.dumps(d, default=str))


def _status_for(result: dict) -> int:
    if result.get("ok"):
        return 200
    if result.get("refused"):
        return 409
    if result.get("unreachable"):
        return 503
    return 400


async def _body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


async def h_overview(request: web.Request) -> web.Response:
    return _json(await overview())


async def h_command(request: web.Request) -> web.Response:
    body = await _body(request)
    result = await run_command(body.get("command"), body.get("args"),
                               read_only=bool(body.get("read_only")))
    return _json(result, _status_for(result))


async def h_player(request: web.Request) -> web.Response:
    body = await _body(request)
    result = await player_action(request.match_info["player_id"],
                                 request.match_info["action"], body.get("value"))
    return _json(result, _status_for(result))


async def h_play(request: web.Request) -> web.Response:
    body = await _body(request)
    result = await play_media(request.match_info["player_id"], body.get("media"),
                              str(body.get("option") or ""),
                              bool(body.get("radio_mode")))
    return _json(result, _status_for(result))


async def h_remove(request: web.Request) -> web.Response:
    body = await _body(request)
    ids = body.get("player_ids")
    result = await remove_players(
        [str(x) for x in ids] if isinstance(ids, list) else None,
        provider=str(body.get("provider") or ""),
        stale_only=body.get("stale_only", True) is not False,
        dry_run=body.get("dry_run", True) is not False,
        disable_if_held=bool(body.get("disable_if_held")))
    return _json(result, _status_for(result))


async def h_provider_reload(request: web.Request) -> web.Response:
    result = await run_command("config/providers/reload",
                               {"instance_id": request.match_info["instance_id"]})
    return _json(result, _status_for(result))


def setup(app: web.Application) -> None:
    """Register the /api/music-assistant routes."""
    app.router.add_get("/api/music-assistant", h_overview)
    app.router.add_post("/api/music-assistant/command", h_command)
    app.router.add_post("/api/music-assistant/players/remove", h_remove)
    app.router.add_post("/api/music-assistant/player/{player_id}/play", h_play)
    app.router.add_post("/api/music-assistant/player/{player_id}/{action}", h_player)
    app.router.add_post("/api/music-assistant/provider/{instance_id}/reload",
                        h_provider_reload)
