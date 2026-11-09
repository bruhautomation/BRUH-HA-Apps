"""BRUH Minecraft integration entry-point.

Registers:
* DataUpdateCoordinator polling /config/.bruh_minecraft/*.json
* sensor + binary_sensor + button + notify platforms
* Service calls that forward to the add-on via the file-based bridge

**An answer that is dropped is a success nobody earned.** Every service
awaited the bridge and ignored what came back, so a command the server
refused — or a server that was not running at all — gave an automation a
green tick. A bridge answer with `ok: false`, and a bridge that never
answered, now raise `HomeAssistantError` with the add-on's own sentence,
which is what puts a reason in an automation trace (BRight's services had
the same bug and the same fix). The services that have something to say
(`rcon_command`, `get_status` and every player action) also return it as
response data, which is how brAIn — or an automation — reads the server's
reply rather than guessing it.
"""
from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

try:  # 2023.7+ — older cores register the services without response data
    from homeassistant.core import SupportsResponse
except ImportError:  # pragma: no cover — exercised only on an old core
    SupportsResponse = None  # type: ignore[assignment]

try:
    from homeassistant.exceptions import HomeAssistantError
except ImportError:  # pragma: no cover — the test harness stubs HA
    class HomeAssistantError(Exception):  # type: ignore[no-redef]
        """Stand-in used only where Home Assistant is not installed."""

from .bridge import send_request
from .const import (
    ADDON_KINDS,
    BUILD_STATUSES,
    DOMAIN,
    GAMEMODES,
    PLAYER_PATTERN,
    SERVICE_ADDON_INSTALL,
    SERVICE_ADDON_REMOVE,
    SERVICE_ADDON_SEARCH,
    SERVICE_ADDONS,
    SERVICE_SCRIPTS,
    SERVICE_SCRIPT_REMOVE,
    SERVICE_SCRIPT_WRITE,
    SCRIPT_KINDS,
    SCRIPT_MAX_BYTES,
    SCRIPT_NAME_PATTERN,
    SERVICE_BACKUP,
    SERVICE_BAN,
    SERVICE_BUILD_DELETE,
    SERVICE_BUILD_SAVE,
    SERVICE_BUILDS,
    SERVICE_COMMAND,
    SERVICE_DEOP,
    SERVICE_GAMEMODE,
    SERVICE_GIVE,
    SERVICE_KICK,
    SERVICE_OP,
    SERVICE_PARDON,
    SERVICE_RESTART,
    SERVICE_SAY,
    SERVICE_STATUS,
    SERVICE_STOP,
    SERVICE_TELEPORT,
    SERVICE_TIME,
    SERVICE_RENAME_WORLD,
    SERVICE_ASK_CHOICE,
    SERVICE_ATLAS,
    SERVICE_COMPANION,
    SERVICE_COMPANION_APPEAR,
    SERVICE_COMPANION_BUILD,
    SERVICE_COMPANION_EDIT,
    SERVICE_COMPANION_PROGRESS,
    SERVICE_COMPANION_BAR,
    SERVICE_GIVE_SPYGLASS,
    SERVICE_COMPANION_THOUGHT,
    SERVICE_GIVE_JOURNAL,
    SERVICE_LABEL_PLACE,
    SERVICE_LOOK_BLOCKS,
    SERVICE_ROOM,
    SERVICE_COMPANION_HANDOVER,
    SERVICE_COMPANION_SAY,
    SERVICE_SET_COMPANION,
    SERVICE_SET_SKIN,
    SERVICE_SET_ZONE,
    SERVICE_UNDO_ACTION,
    SERVICE_WEATHER,
    SERVICE_WHITELIST_ADD,
    SERVICE_WHITELIST_REMOVE,
    SERVICE_WORLD,
)
from .coordinator import BruhMinecraftCoordinator
from .fingerprint import record_loaded

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NOTIFY,
]


# This integration is only ever set up from a config entry — the add-on
# announces itself to the Supervisor and `async_step_hassio` picks it up.
# There is nothing to configure in configuration.yaml, and saying so is
# what stops Home Assistant assuming there might be.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    # What this Home Assistant loaded (fingerprint.py, taken at import), for the
    # add-on's run.sh: it says a restart is needed only when the code it deploys
    # differs from this.
    await hass.async_add_executor_job(record_loaded, hass.config.path(".bruh_minecraft/integration.json"))
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = BruhMinecraftCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
_PLAYER_RE = re.compile(PLAYER_PATTERN)


def _player(value: Any) -> str:
    """A player name or selector, or a refusal that says what one looks like."""
    text = str(value or "").strip()
    if not _PLAYER_RE.match(text):
        raise vol.Invalid(
            f"{text!r} is not a Minecraft player name (letters, digits and _, "
            "up to 16, with a Bedrock prefix) or one of @a/@p/@r/@s")
    return text


VALID_PLAYER_NAME = _player


def _coordinate(value: Any) -> str:
    """One coordinate: a number, or a relative/local one (`~`, `~5`, `^-2`)."""
    text = str(value).strip()
    if not re.match(r"^([~^]-?\d*(\.\d+)?|-?\d+(\.\d+)?)$", text):
        raise vol.Invalid(f"{text!r} is not a coordinate")
    return text


def _one_line(value: Any) -> str:
    """A command or message is one line: a newline is a second command."""
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


_SCRIPT_NAME_RE = re.compile(SCRIPT_NAME_PATTERN)


def _script_name(value: Any) -> str:
    """A script's name: no folders, no extension needed, nothing to escape."""
    text = str(value or "").strip()
    for ext in (".sk", ".mcfunction"):
        if text.endswith(ext):
            text = text[: -len(ext)]
    if not _SCRIPT_NAME_RE.match(text):
        raise vol.Invalid(
            f"{text!r} is not a script name: 1 to 48 lowercase letters, digits, _ and -")
    return text


def _script_content(value: Any) -> str:
    text = str(value if value is not None else "")
    size = len(text.encode("utf-8"))
    if not text.strip():
        raise vol.Invalid("The script is empty")
    if size > SCRIPT_MAX_BYTES:
        raise vol.Invalid(f"The script is {size} bytes; the most is {SCRIPT_MAX_BYTES}")
    return text


def teleport_command(data: dict[str, Any]) -> str:
    """The console command a teleport call means, or a refusal.

    To a player, or to x/y/z — exactly one. `minecraft:tp` rather than
    `tp`, because EssentialsX overrides `/tp` and its version refuses
    some console forms the vanilla one accepts.
    """
    player = data["player"]
    target = data.get("to_player")
    coords = [data.get(k) for k in ("x", "y", "z")]
    have = [c is not None and str(c).strip() != "" for c in coords]
    if target and any(have):
        raise HomeAssistantError("Teleport either to a player or to x/y/z, not both.")
    if target:
        return f"minecraft:tp {player} {target}"
    if all(have):
        return "minecraft:tp " + player + " " + " ".join(str(c).strip() for c in coords)
    raise HomeAssistantError("Teleport needs to_player, or all three of x, y and z.")


async def _ask(kind: str, payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    """One bridge round trip whose failure is an error, never a silence."""
    try:
        answer = await send_request(kind, payload, timeout=timeout)
    except TimeoutError as exc:
        raise HomeAssistantError(
            "The BRUH Minecraft add-on did not answer. Is it running, with "
            "'Home Assistant integration' switched on?") from exc
    if not isinstance(answer, dict):
        raise HomeAssistantError("The BRUH Minecraft add-on sent an answer it could not read.")
    if not answer.get("ok", False):
        raise HomeAssistantError(
            str(answer.get("error") or "The Minecraft server refused the request."))
    return answer


# How the server says no. RCON answers every command with text and no
# status, so a refused one ("Unknown item 'minecraft:chilli'") came back as
# a successful call carrying the refusal as its reply, and brAIn told the
# person it had been done. Matched on the reply's first line, colour codes
# stripped; a reply that merely informs ("Nothing changed. The player is
# already an operator") is not a refusal and still answers.
REFUSAL_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"^unknown or incomplete command",
    r"^unknown command",
    r"^unknown (item|block|entity|effect|enchantment|gamemode)",
    r"^no player was found",
    r"^no entity was found",
    r"^no targets matched",
    r"^that player does not exist",
    r"^player not found",
    r"^incorrect argument for command",
    r"^expected ",
    r"^invalid ",
    r"<--\[here\]",
))


def refused(reply: str) -> bool:
    """True when the server's reply is the server saying no."""
    first = re.sub(r"\u00a7.", "", str(reply or "")).strip().splitlines()
    line = first[0].strip() if first else ""
    return any(p.search(line) for p in REFUSAL_PATTERNS)


def _reply(answer: dict[str, Any]) -> dict[str, Any]:
    reply = answer.get("reply")
    text = str(reply).strip() if reply is not None else ""
    if refused(text):
        raise HomeAssistantError(f"The Minecraft server refused it: {text}")
    return {"reply": text}


# How long a skin is waited for: the add-on's own 30 s, and the round trip.
SKIN_TIMEOUT = 45.0


def _register_services(hass: HomeAssistant) -> None:
    async def run(command: str, timeout: float = 15.0) -> dict[str, Any]:
        return _reply(await _ask("command", {"command": _one_line(command)}, timeout=timeout))

    async def handle_command(call: ServiceCall) -> dict[str, Any]:
        command = call.data["command"]
        # SkinsRestorer answers a skin command seconds after RCON returns,
        # and the add-on waits up to 30 s for it (scripts/skins.py).
        late = re.match(r"^/?(?:skinsrestorer:)?skin\s", str(command).strip(), re.IGNORECASE)
        return await run(command, timeout=SKIN_TIMEOUT if late else 15.0)

    async def handle_set_skin(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("skin", {"player": call.data["player"],
                                          "skin": call.data["skin"]}, timeout=SKIN_TIMEOUT))

    async def handle_say(call: ServiceCall) -> dict[str, Any]:
        return _reply(await _ask("say", {"message": _one_line(call.data["message"])}))

    async def handle_give(call: ServiceCall) -> dict[str, Any]:
        parts = ["give", call.data["player"], _one_line(call.data["item"]).split(" ")[0]]
        if (amount := call.data.get("amount")):
            parts.append(str(amount))
        return await run(" ".join(parts))

    async def handle_weather(call: ServiceCall) -> dict[str, Any]:
        return await run(f"weather {call.data['weather']}")

    async def handle_time(call: ServiceCall) -> dict[str, Any]:
        return await run(f"time set {call.data['time']}")

    async def handle_teleport(call: ServiceCall) -> dict[str, Any]:
        return await run(teleport_command(call.data))

    async def handle_gamemode(call: ServiceCall) -> dict[str, Any]:
        return await run(f"gamemode {call.data['gamemode']} {call.data['player']}")

    async def handle_status(_: ServiceCall) -> dict[str, Any]:
        answer = await _ask("status", {})
        # `reachable` and `note` are what tell a server that is down from a
        # server nobody is on; both have an empty player list.
        return {k: answer.get(k) for k in ("reachable", "note", "online", "max",
                                           "players", "state", "stats")}

    def _strip(answer: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in answer.items() if k != "ok"}

    async def handle_addons(_: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("addon_list", {}))

    async def handle_addon_search(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("addon_search", {
            "kind": call.data.get("kind", ""), "query": call.data.get("query", ""),
            "offset": call.data.get("offset", 0)}, timeout=60.0))

    async def handle_addon_install(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("addon_install", {
            "id": call.data["id"], "kind": call.data["kind"]}, timeout=180.0))

    async def handle_addon_remove(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("addon_remove", {"id": call.data["id"]}, timeout=60.0))

    # Scripts written into the running world (panel/worldscripts.py). A
    # script that did not load is a refusal carrying the loader's errors.
    async def handle_scripts(_: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("script_list", {}))

    async def handle_script_write(call: ServiceCall) -> dict[str, Any]:
        payload = {"kind": call.data["kind"], "name": _script_name(call.data["name"]),
                   "content": _script_content(call.data["content"])}
        if "by" in call.data:
            payload["by"] = _one_line(call.data["by"])
        return _strip(await _ask("script_write", payload, timeout=60.0))

    async def handle_script_remove(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("script_remove", {
            "kind": call.data["kind"], "name": _script_name(call.data["name"])}, timeout=60.0))

    # The world and the build log (panel/mcworld.py). Reading the world
    # asks the panel now, not the mirrored file, so a caller is never
    # handed a state up to fifteen seconds old.
    async def handle_world(_: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("world", {}))

    async def handle_builds(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("builds_list", {
            k: call.data[k] for k in ("status", "limit") if k in call.data}))

    async def handle_build_save(call: ServiceCall) -> dict[str, Any]:
        payload = dict(call.data)
        if not payload.get("id") and not str(payload.get("title") or "").strip():
            raise HomeAssistantError("A new build job needs a title; to change one, give its id.")
        return _strip(await _ask("build_save", payload, timeout=30.0))

    async def handle_build_delete(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("build_delete", {"id": call.data["id"]}))

    # The companion's hands (panel/companion.py). The add-on's panel holds the
    # one implementation; these carry a companion's request to it and answer
    # with what was done, or raise with why not.
    async def handle_companion(_: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion", {}))

    async def handle_set_companion(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion_identity", {
            k: call.data[k] for k in ("name", "colour", "active", "by", "model")
            if k in call.data}))

    async def handle_companion_say(call: ServiceCall) -> dict[str, Any]:
        to = call.data.get("to", "everyone")
        payload = {"to": to, "message": _one_line(call.data["message"])}
        for key in ("name", "colour", "chime", "by"):
            if key in call.data:
                payload[key] = call.data[key]
        return _strip(await _ask("companion_say", payload))

    async def handle_companion_appear(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion_appear", {
            k: call.data[k] for k in ("player", "seconds", "kind", "name", "colour", "chime",
                                      "text", "by") if k in call.data}))

    async def handle_ask_choice(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion_ask", {
            k: call.data[k] for k in ("player", "question", "options", "person", "name", "by")
            if k in call.data}))

    async def handle_companion_build(call: ServiceCall) -> dict[str, Any]:
        payload = {k: call.data[k] for k in ("blocks", "player", "dimension", "title", "name",
                                             "by") if k in call.data}
        return _strip(await _ask("companion_build", payload, timeout=60.0))

    async def handle_companion_edit(call: ServiceCall) -> dict[str, Any]:
        payload = {k: call.data[k] for k in ("blocks", "fills", "shapes", "player", "dimension",
                                             "title", "name", "by", "job") if k in call.data}
        if not any(payload.get(k) for k in ("blocks", "fills", "shapes")):
            raise HomeAssistantError("Give blocks, fills or shapes to change.")
        return _strip(await _ask("companion_edit", payload, timeout=180.0))

    async def handle_companion_progress(call: ServiceCall) -> dict[str, Any]:
        payload = {"to": call.data["to"], "text": _one_line(call.data["text"])}
        for key in ("percent", "colour"):
            if key in call.data:
                payload[key] = call.data[key]
        return _strip(await _ask("companion_progress", payload))

    async def handle_companion_bar(call: ServiceCall) -> dict[str, Any]:
        payload = {"player": call.data["player"], "key": call.data["key"]}
        if "text" in call.data:
            payload["text"] = _one_line(call.data["text"])
        for key in ("percent", "end"):
            if key in call.data:
                payload[key] = call.data[key]
        return _strip(await _ask("companion_bar", payload))

    async def handle_give_spyglass(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion_spyglass", {
            "player": call.data["player"], "name": _one_line(call.data["name"])}))

    async def handle_companion_thought(call: ServiceCall) -> dict[str, Any]:
        payload = {"player": call.data["player"], "state": call.data.get("state", "working")}
        for key in ("text", "key", "title", "name", "colour"):
            if key in call.data:
                payload[key] = _one_line(call.data[key])
        if "percent" in call.data:
            payload["percent"] = call.data["percent"]
        return _strip(await _ask("companion_thought", payload))

    async def handle_give_journal(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion_journal", {
            "player": call.data["player"], "name": _one_line(call.data["name"])}))

    async def handle_atlas(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("atlas", {
            k: call.data[k] for k in ("player", "x", "y", "z", "dimension", "radius", "query")
            if k in call.data}, timeout=60.0))

    async def handle_room(call: ServiceCall) -> dict[str, Any]:
        if not any(k in call.data for k in ("player", "room", "x")):
            raise HomeAssistantError("Give a player, a room id, or x, y and z.")
        return _strip(await _ask("atlas_room", {
            k: call.data[k] for k in ("player", "room", "x", "y", "z", "dimension")
            if k in call.data}, timeout=60.0))

    async def handle_label_place(call: ServiceCall) -> dict[str, Any]:
        if not any(k in call.data for k in ("room", "building", "x")):
            raise HomeAssistantError("Give a room id, a building id, or x, y and z.")
        return _strip(await _ask("atlas_label", {
            k: call.data[k] for k in ("room", "building", "x", "y", "z", "dimension", "name",
                                      "by") if k in call.data}, timeout=60.0))

    async def handle_look_blocks(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion_look", {
            k: call.data[k] for k in ("player", "x", "y", "z", "size", "dimension")
            if k in call.data}, timeout=60.0))

    async def handle_undo_action(call: ServiceCall) -> dict[str, Any]:
        if call.data.get("job"):
            # Every edit recorded for a job, newest first (a cancelled job).
            return _strip(await _ask("companion_undo", {"job": call.data["job"]},
                                     timeout=150.0))
        return _strip(await _ask("companion_undo", {"id": call.data.get("id") or "last"},
                                 timeout=60.0))

    async def handle_set_zone(call: ServiceCall) -> dict[str, Any]:
        return _strip(await _ask("companion_zone", dict(call.data)))

    async def handle_companion_handover(call: ServiceCall) -> dict[str, Any]:
        # The 1.17.7 engine's per-world state, once; `done: true` retires it.
        kind = "companion_legacy_retire" if call.data.get("done") else "companion_legacy"
        return _strip(await _ask(kind, {}))

    async def handle_rename_world(call: ServiceCall) -> dict[str, Any]:
        # Renaming the active world restarts the add-on once it has answered.
        return _strip(await _ask("rename_world", {"name": call.data["name"]}, timeout=150.0))

    async def handle_backup(_: ServiceCall) -> dict[str, Any]:
        answer = await _ask("backup", {}, timeout=120.0)
        return {"output": str(answer.get("output", ""))[-2000:]}

    # Both answer, like every other action here: brAIn calls each service
    # with return_response=True, and Core refuses that outright for a
    # service registered without response support.
    async def handle_restart(_: ServiceCall) -> dict[str, Any]:
        await _ask("restart", {}, timeout=30.0)
        return {"done": True, "note": "The server saved the world and is restarting."}

    async def handle_stop(_: ServiceCall) -> dict[str, Any]:
        await _ask("stop", {}, timeout=30.0)
        return {"done": True, "note": "The server saved the world and stopped. "
                "It stays stopped until it is started from the add-on."}

    async def handle_player_action(call: ServiceCall, action: str) -> dict[str, Any]:
        return _reply(await _ask(
            "player_action", {"name": call.data["player"], "action": action}))

    command_schema = vol.Schema({vol.Required("command"): cv.string})
    say_schema = vol.Schema({vol.Required("message"): cv.string})
    give_schema = vol.Schema({
        vol.Required("player"): _player,
        vol.Required("item"): cv.string,
        vol.Optional("amount"): vol.All(vol.Coerce(int), vol.Range(1, 64)),
    })
    weather_schema = vol.Schema({
        vol.Required("weather"): vol.In(["clear", "rain", "thunder"]),
    })
    time_schema = vol.Schema({
        vol.Required("time"): vol.Any(vol.In(["day", "night", "noon", "midnight"]), vol.Coerce(int)),
    })
    teleport_schema = vol.Schema({
        vol.Required("player"): _player,
        vol.Optional("to_player"): _player,
        vol.Optional("x"): _coordinate,
        vol.Optional("y"): _coordinate,
        vol.Optional("z"): _coordinate,
    })
    gamemode_schema = vol.Schema({
        vol.Required("player"): _player,
        vol.Required("gamemode"): vol.In(list(GAMEMODES)),
    })
    addon_search_schema = vol.Schema({
        vol.Optional("kind"): vol.In(list(ADDON_KINDS)),
        vol.Optional("query"): cv.string,
        vol.Optional("offset"): vol.All(vol.Coerce(int), vol.Range(0, 10000)),
    })
    addon_install_schema = vol.Schema({
        vol.Required("id"): cv.string,
        vol.Required("kind"): vol.In(list(ADDON_KINDS)),
    })
    addon_remove_schema = vol.Schema({vol.Required("id"): cv.string})
    script_write_schema = vol.Schema({
        vol.Required("kind"): vol.In(list(SCRIPT_KINDS)),
        vol.Required("name"): _script_name,
        vol.Required("content"): _script_content,
        vol.Optional("by"): cv.string,
    })
    script_remove_schema = vol.Schema({
        vol.Required("kind"): vol.In(list(SCRIPT_KINDS)),
        vol.Required("name"): _script_name,
    })
    builds_schema = vol.Schema({
        vol.Optional("status"): vol.In(list(BUILD_STATUSES)),
        vol.Optional("limit"): vol.All(vol.Coerce(int), vol.Range(1, 200)),
    })
    build_save_schema = vol.Schema({
        vol.Optional("id"): cv.string,
        vol.Optional("title"): cv.string,
        vol.Optional("part"): cv.string,
        vol.Optional("status"): vol.In(list(BUILD_STATUSES)),
        vol.Optional("progress"): vol.All(vol.Coerce(int), vol.Range(0, 100)),
        vol.Optional("bounds"): dict,
        vol.Optional("notes"): cv.string,
        vol.Optional("image"): cv.string,
        vol.Optional("by"): cv.string,
    })
    build_delete_schema = vol.Schema({vol.Required("id"): cv.string})
    option_schema = vol.Any(cv.string, vol.Schema({
        vol.Required("label"): cv.string,
        vol.Optional("picture"): cv.string,
        vol.Optional("item"): cv.string,
        vol.Optional("gift"): cv.string,
        vol.Optional("gift_count"): vol.All(vol.Coerce(int), vol.Range(1, 16)),
    }))
    speaker = vol.All(cv.string, vol.Length(min=1, max=16))
    colour_name = vol.In(["black", "dark_blue", "dark_green", "dark_aqua", "dark_red",
                          "dark_purple", "gold", "gray", "dark_gray", "blue", "green", "aqua",
                          "red", "light_purple", "yellow", "white"])
    by_schema = vol.All(cv.string, vol.Length(max=40))
    set_companion_schema = vol.Schema({
        vol.Optional("name"): speaker,
        vol.Optional("colour"): colour_name,
        vol.Optional("active"): bool,
        vol.Optional("by"): by_schema,
        vol.Optional("model"): vol.All(cv.string, vol.Length(max=60)),
    })
    player_name = vol.All(cv.string, vol.Length(min=1, max=40))
    companion_say_schema = vol.Schema({
        vol.Optional("to", default="everyone"): vol.Any(
            player_name, vol.All([player_name], vol.Length(min=1, max=20))),
        vol.Required("message"): vol.All(cv.string, vol.Length(min=1, max=640)),
        vol.Optional("name"): speaker,
        vol.Optional("colour"): colour_name,
        vol.Optional("chime"): bool,
        vol.Optional("by"): by_schema,
    })
    companion_appear_schema = vol.Schema({
        vol.Required("player"): player_name,
        vol.Optional("seconds", default=25): vol.All(vol.Coerce(int), vol.Range(3, 120)),
        vol.Optional("kind", default="visit"): vol.In(["greet", "visit"]),
        vol.Optional("name"): speaker,
        vol.Optional("colour"): colour_name,
        vol.Optional("chime", default="full"): vol.In(["full", "short", "none"]),
        vol.Optional("text"): vol.All(cv.string, vol.Length(max=200)),
        vol.Optional("by"): by_schema,
    })
    ask_choice_schema = vol.Schema({
        vol.Required("player"): player_name,
        vol.Required("question"): vol.All(cv.string, vol.Length(min=1, max=200)),
        vol.Optional("options"): vol.All([option_schema], vol.Length(min=2, max=3)),
        vol.Optional("person"): vol.All(cv.string, vol.Length(max=40)),
        vol.Optional("name"): speaker,
        vol.Optional("by"): by_schema,
    })
    block_schema = vol.Schema({
        vol.Required("x"): vol.Coerce(int), vol.Required("y"): vol.Coerce(int),
        vol.Required("z"): vol.Coerce(int), vol.Required("block"): cv.string,
    })
    companion_build_schema = vol.Schema({
        vol.Required("blocks"): vol.All([block_schema], vol.Length(min=1, max=64)),
        vol.Optional("player"): player_name,
        vol.Optional("dimension"): cv.string,
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=60)),
        vol.Optional("name"): speaker,
        vol.Optional("by"): by_schema,
    })
    edit_block_schema = vol.Schema({
        vol.Required("x"): vol.Coerce(int), vol.Required("y"): vol.Coerce(int),
        vol.Required("z"): vol.Coerce(int), vol.Optional("block", default=""): cv.string,
        vol.Optional("mode"): vol.In(["set", "replace", "remove"]),
    })
    fill_schema = vol.Schema({
        vol.Required("x1"): vol.Coerce(int), vol.Required("y1"): vol.Coerce(int),
        vol.Required("z1"): vol.Coerce(int), vol.Required("x2"): vol.Coerce(int),
        vol.Required("y2"): vol.Coerce(int), vol.Required("z2"): vol.Coerce(int),
        vol.Required("block"): cv.string,
    })
    # A shape ({kind, block, from/to, center, radii, …}) and a job id are
    # checked by the add-on, which expands the shape (panel/shapes.py) and
    # says in words what is wrong with either.
    job_id = vol.All(cv.string, vol.Length(min=1, max=40))
    companion_edit_schema = vol.Schema({
        vol.Optional("blocks"): vol.All([edit_block_schema], vol.Length(max=4096)),
        vol.Optional("fills"): vol.All([fill_schema], vol.Length(max=64)),
        vol.Optional("shapes"): vol.All([dict], vol.Length(max=64)),
        vol.Optional("player"): player_name,
        vol.Optional("dimension"): cv.string,
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=60)),
        vol.Optional("name"): speaker,
        vol.Optional("by"): by_schema,
        vol.Optional("job"): job_id,
    })
    companion_progress_schema = vol.Schema({
        vol.Required("to"): vol.Any(player_name, vol.All([player_name], vol.Length(min=1, max=20))),
        vol.Required("text"): vol.All(cv.string, vol.Length(min=1, max=160)),
        vol.Optional("percent"): vol.All(vol.Coerce(float), vol.Range(0, 100)),
        vol.Optional("colour"): colour_name,
    })
    companion_bar_schema = vol.Schema({
        vol.Required("player"): player_name,
        vol.Required("key"): vol.All(cv.string, vol.Length(min=1, max=24)),
        vol.Optional("text"): vol.All(cv.string, vol.Length(max=160)),
        vol.Optional("percent"): vol.All(vol.Coerce(float), vol.Range(0, 100)),
        vol.Optional("end"): bool,
    })
    companion_thought_schema = vol.Schema({
        vol.Required("player"): player_name,
        vol.Optional("text"): vol.All(cv.string, vol.Length(max=160)),
        vol.Optional("state"): vol.In(["thinking", "working", "done", "failed", "clear"]),
        vol.Optional("key"): vol.All(cv.string, vol.Length(min=1, max=24)),
        vol.Optional("title"): vol.All(cv.string, vol.Length(max=32)),
        vol.Optional("percent"): vol.All(vol.Coerce(float), vol.Range(0, 100)),
        vol.Optional("name"): vol.All(cv.string, vol.Length(max=16)),
        vol.Optional("colour"): colour_name,
    })
    give_journal_schema = vol.Schema({
        vol.Required("player"): player_name,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=32)),
    })
    give_spyglass_schema = vol.Schema({
        vol.Required("player"): player_name,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=32)),
    })
    point_fields = {
        vol.Optional("x"): vol.Coerce(float), vol.Optional("y"): vol.Coerce(float),
        vol.Optional("z"): vol.Coerce(float), vol.Optional("dimension"): cv.string,
    }
    atlas_schema = vol.Schema({
        vol.Optional("player"): player_name, **point_fields,
        vol.Optional("radius"): vol.All(vol.Coerce(int), vol.Range(8, 256)),
        vol.Optional("query"): vol.All(cv.string, vol.Length(max=60)),
    })
    room_schema = vol.Schema({
        vol.Optional("player"): player_name, vol.Optional("room"): cv.string, **point_fields,
    })
    label_place_schema = vol.Schema({
        vol.Optional("room"): cv.string, vol.Optional("building"): cv.string, **point_fields,
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=60)),
        vol.Optional("by"): by_schema,
    })
    look_blocks_schema = vol.Schema({
        vol.Optional("player"): player_name,
        vol.Optional("x"): vol.Coerce(int), vol.Optional("y"): vol.Coerce(int),
        vol.Optional("z"): vol.Coerce(int),
        vol.Optional("size"): vol.All([vol.Coerce(int)], vol.Length(min=3, max=3)),
        vol.Optional("dimension"): cv.string,
    })
    set_skin_schema = vol.Schema({
        vol.Required("player"): player_name,
        vol.Required("skin"): vol.All(cv.string, vol.Length(min=1, max=320)),
    })
    undo_action_schema = vol.Schema({vol.Optional("id"): cv.string,
                                     vol.Optional("job"): job_id})
    set_zone_schema = vol.Schema({
        vol.Required("name"): cv.string,
        vol.Optional("x"): vol.Coerce(float),
        vol.Optional("z"): vol.Coerce(float),
        vol.Optional("radius"): vol.All(vol.Coerce(int), vol.Range(1, 512)),
        vol.Optional("dimension"): cv.string,
        vol.Optional("protect"): bool,
        vol.Optional("kind"): vol.In(["family", "companion"]),
        vol.Optional("delete"): bool,
    })
    handover_schema = vol.Schema({vol.Optional("done"): bool})
    rename_world_schema = vol.Schema({
        vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=60))})
    player_schema = vol.Schema({vol.Required("player"): _player})
    empty_schema = vol.Schema({})

    optional = getattr(SupportsResponse, "OPTIONAL", None)
    only = getattr(SupportsResponse, "ONLY", None)

    def register(name, handler, schema, response=None) -> None:
        if response is not None:
            hass.services.async_register(
                DOMAIN, name, handler, schema=schema, supports_response=response)
        else:
            hass.services.async_register(DOMAIN, name, handler, schema=schema)

    register(SERVICE_COMMAND, handle_command, command_schema, optional)
    register(SERVICE_SAY, handle_say, say_schema, optional)
    register(SERVICE_GIVE, handle_give, give_schema, optional)
    register(SERVICE_WEATHER, handle_weather, weather_schema, optional)
    register(SERVICE_TIME, handle_time, time_schema, optional)
    register(SERVICE_TELEPORT, handle_teleport, teleport_schema, optional)
    register(SERVICE_GAMEMODE, handle_gamemode, gamemode_schema, optional)
    register(SERVICE_STATUS, handle_status, empty_schema, only)
    register(SERVICE_ADDONS, handle_addons, empty_schema, only)
    register(SERVICE_ADDON_SEARCH, handle_addon_search, addon_search_schema, only)
    register(SERVICE_ADDON_INSTALL, handle_addon_install, addon_install_schema, optional)
    register(SERVICE_ADDON_REMOVE, handle_addon_remove, addon_remove_schema, optional)
    register(SERVICE_SCRIPTS, handle_scripts, empty_schema, only)
    register(SERVICE_SCRIPT_WRITE, handle_script_write, script_write_schema, optional)
    register(SERVICE_SCRIPT_REMOVE, handle_script_remove, script_remove_schema, optional)
    register(SERVICE_WORLD, handle_world, empty_schema, only)
    register(SERVICE_BUILDS, handle_builds, builds_schema, only)
    register(SERVICE_BUILD_SAVE, handle_build_save, build_save_schema, optional)
    register(SERVICE_BUILD_DELETE, handle_build_delete, build_delete_schema, optional)
    register(SERVICE_COMPANION, handle_companion, empty_schema, only)
    register(SERVICE_SET_COMPANION, handle_set_companion, set_companion_schema, optional)
    register(SERVICE_COMPANION_SAY, handle_companion_say, companion_say_schema, optional)
    register(SERVICE_COMPANION_APPEAR, handle_companion_appear, companion_appear_schema, optional)
    register(SERVICE_ASK_CHOICE, handle_ask_choice, ask_choice_schema, optional)
    register(SERVICE_COMPANION_BUILD, handle_companion_build, companion_build_schema, optional)
    register(SERVICE_COMPANION_EDIT, handle_companion_edit, companion_edit_schema, optional)
    register(SERVICE_LOOK_BLOCKS, handle_look_blocks, look_blocks_schema, only)
    register(SERVICE_SET_SKIN, handle_set_skin, set_skin_schema, optional)
    register(SERVICE_COMPANION_PROGRESS, handle_companion_progress, companion_progress_schema,
             optional)
    register(SERVICE_COMPANION_BAR, handle_companion_bar, companion_bar_schema, optional)
    register(SERVICE_GIVE_SPYGLASS, handle_give_spyglass, give_spyglass_schema, optional)
    register(SERVICE_COMPANION_THOUGHT, handle_companion_thought, companion_thought_schema,
             optional)
    register(SERVICE_GIVE_JOURNAL, handle_give_journal, give_journal_schema, optional)
    register(SERVICE_ATLAS, handle_atlas, atlas_schema, only)
    register(SERVICE_ROOM, handle_room, room_schema, only)
    register(SERVICE_LABEL_PLACE, handle_label_place, label_place_schema, optional)
    register(SERVICE_UNDO_ACTION, handle_undo_action, undo_action_schema, optional)
    register(SERVICE_SET_ZONE, handle_set_zone, set_zone_schema, optional)
    register(SERVICE_COMPANION_HANDOVER, handle_companion_handover, handover_schema, only)
    register(SERVICE_RENAME_WORLD, handle_rename_world, rename_world_schema, optional)
    register(SERVICE_BACKUP, handle_backup, empty_schema, optional)
    register(SERVICE_RESTART, handle_restart, empty_schema, optional)
    register(SERVICE_STOP, handle_stop, empty_schema, optional)

    for svc, action in (
        (SERVICE_OP, "op"),
        (SERVICE_DEOP, "deop"),
        (SERVICE_KICK, "kick"),
        (SERVICE_BAN, "ban"),
        (SERVICE_PARDON, "pardon"),
        (SERVICE_WHITELIST_ADD, "whitelist_add"),
        (SERVICE_WHITELIST_REMOVE, "whitelist_remove"),
    ):
        register(svc, lambda c, a=action: handle_player_action(c, a), player_schema, optional)
