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
    DOMAIN,
    GAMEMODES,
    PLAYER_PATTERN,
    SERVICE_ADDON_INSTALL,
    SERVICE_ADDON_REMOVE,
    SERVICE_ADDON_SEARCH,
    SERVICE_ADDONS,
    SERVICE_BACKUP,
    SERVICE_BAN,
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
    SERVICE_WEATHER,
    SERVICE_WHITELIST_ADD,
    SERVICE_WHITELIST_REMOVE,
)
from .coordinator import BruhMinecraftCoordinator

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


def _reply(answer: dict[str, Any]) -> dict[str, Any]:
    reply = answer.get("reply")
    return {"reply": str(reply).strip() if reply is not None else ""}


def _register_services(hass: HomeAssistant) -> None:
    async def run(command: str) -> dict[str, Any]:
        return _reply(await _ask("command", {"command": _one_line(command)}))

    async def handle_command(call: ServiceCall) -> dict[str, Any]:
        return await run(call.data["command"])

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
        return {k: answer.get(k) for k in ("online", "max", "players", "state", "stats")}

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

    async def handle_backup(_: ServiceCall) -> dict[str, Any]:
        answer = await _ask("backup", {}, timeout=120.0)
        return {"output": str(answer.get("output", ""))[-2000:]}

    async def handle_restart(_: ServiceCall) -> None:
        await _ask("restart", {}, timeout=30.0)

    async def handle_stop(_: ServiceCall) -> None:
        await _ask("stop", {}, timeout=30.0)

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
    register(SERVICE_BACKUP, handle_backup, empty_schema, optional)
    register(SERVICE_RESTART, handle_restart, empty_schema)
    register(SERVICE_STOP, handle_stop, empty_schema)

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
