"""BRUH Minecraft integration entry-point.

Registers:
* DataUpdateCoordinator polling /config/.bruh_minecraft/*.json
* sensor + binary_sensor + button platforms
* Service calls that forward to the add-on via file-based bridge
"""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .bridge import send_request
from .const import (
    DOMAIN,
    SERVICE_BACKUP,
    SERVICE_BAN,
    SERVICE_COMMAND,
    SERVICE_DEOP,
    SERVICE_GIVE,
    SERVICE_KICK,
    SERVICE_OP,
    SERVICE_RESTART,
    SERVICE_SAY,
    SERVICE_STOP,
    SERVICE_TIME,
    SERVICE_WEATHER,
    SERVICE_WHITELIST_ADD,
    SERVICE_WHITELIST_REMOVE,
)
from .coordinator import BruhMinecraftCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


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
VALID_PLAYER_NAME = vol.All(cv.string, vol.Length(min=1, max=16))


def _register_services(hass: HomeAssistant) -> None:
    async def handle_command(call: ServiceCall) -> None:
        await send_request("command", {"command": call.data["command"]})

    async def handle_say(call: ServiceCall) -> None:
        await send_request("say", {"message": call.data["message"]})

    async def handle_give(call: ServiceCall) -> None:
        parts = [
            "give",
            call.data["player"],
            call.data["item"],
        ]
        if (amount := call.data.get("amount")):
            parts.append(str(amount))
        await send_request("command", {"command": " ".join(parts)})

    async def handle_weather(call: ServiceCall) -> None:
        await send_request("command", {"command": f"weather {call.data['weather']}"})

    async def handle_time(call: ServiceCall) -> None:
        await send_request("command", {"command": f"time set {call.data['time']}"})

    async def handle_backup(_: ServiceCall) -> None:
        await send_request("backup", {}, timeout=120.0)

    async def handle_restart(_: ServiceCall) -> None:
        await send_request("restart", {}, timeout=30.0)

    async def handle_stop(_: ServiceCall) -> None:
        await send_request("stop", {}, timeout=30.0)

    async def handle_player_action(call: ServiceCall, action: str) -> None:
        await send_request(
            "player_action",
            {"name": call.data["player"], "action": action},
        )

    command_schema = vol.Schema({vol.Required("command"): cv.string})
    say_schema = vol.Schema({vol.Required("message"): cv.string})
    give_schema = vol.Schema({
        vol.Required("player"): VALID_PLAYER_NAME,
        vol.Required("item"): cv.string,
        vol.Optional("amount"): vol.All(vol.Coerce(int), vol.Range(1, 64)),
    })
    weather_schema = vol.Schema({
        vol.Required("weather"): vol.In(["clear", "rain", "thunder"]),
    })
    time_schema = vol.Schema({
        vol.Required("time"): vol.Any(vol.In(["day", "night", "noon", "midnight"]), vol.Coerce(int)),
    })
    player_schema = vol.Schema({vol.Required("player"): VALID_PLAYER_NAME})
    empty_schema = vol.Schema({})

    hass.services.async_register(DOMAIN, SERVICE_COMMAND, handle_command, schema=command_schema)
    hass.services.async_register(DOMAIN, SERVICE_SAY, handle_say, schema=say_schema)
    hass.services.async_register(DOMAIN, SERVICE_GIVE, handle_give, schema=give_schema)
    hass.services.async_register(DOMAIN, SERVICE_WEATHER, handle_weather, schema=weather_schema)
    hass.services.async_register(DOMAIN, SERVICE_TIME, handle_time, schema=time_schema)
    hass.services.async_register(DOMAIN, SERVICE_BACKUP, handle_backup, schema=empty_schema)
    hass.services.async_register(DOMAIN, SERVICE_RESTART, handle_restart, schema=empty_schema)
    hass.services.async_register(DOMAIN, SERVICE_STOP, handle_stop, schema=empty_schema)

    for svc, action in (
        (SERVICE_OP, "op"),
        (SERVICE_DEOP, "deop"),
        (SERVICE_KICK, "kick"),
        (SERVICE_BAN, "ban"),
        (SERVICE_WHITELIST_ADD, "whitelist_add"),
        (SERVICE_WHITELIST_REMOVE, "whitelist_remove"),
    ):
        hass.services.async_register(
            DOMAIN, svc,
            lambda c, a=action: handle_player_action(c, a),
            schema=player_schema,
        )
