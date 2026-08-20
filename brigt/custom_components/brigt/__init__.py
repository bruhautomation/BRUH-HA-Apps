"""BRigt integration entry-point.

Registers:
* a sensor platform polling /config/.brigt/state.json (show status)
* brigt.party_mode / brigt.start_show / brigt.stop_show, forwarded to the
  add-on via the file-based bridge
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .bridge import send_request
from .const import (
    DOMAIN,
    SERVICE_PARTY_MODE,
    SERVICE_START_SHOW,
    SERVICE_STOP_SHOW,
)
from .coordinator import BrigtCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Only ever set up from a config entry — the add-on announces itself to the
# Supervisor and async_step_hassio picks it up. Saying so is what stops HA
# assuming there might be YAML to import.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = BrigtCoordinator(hass)
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
PARTY_MODE_SCHEMA = vol.Schema(
    {
        vol.Optional("media_player"): cv.entity_id,
        vol.Optional("folder"): cv.string,
        vol.Optional("vibe"): cv.string,
    }
)

START_SHOW_SCHEMA = vol.Schema(
    {
        vol.Required("track"): cv.string,
        vol.Optional("media_player"): cv.entity_id,
    }
)


def _register_services(hass: HomeAssistant) -> None:
    async def handle_party_mode(call: ServiceCall) -> None:
        await send_request(SERVICE_PARTY_MODE, dict(call.data))

    async def handle_start_show(call: ServiceCall) -> None:
        await send_request(SERVICE_START_SHOW, dict(call.data))

    async def handle_stop_show(call: ServiceCall) -> None:
        await send_request(SERVICE_STOP_SHOW, {})

    hass.services.async_register(
        DOMAIN, SERVICE_PARTY_MODE, handle_party_mode, schema=PARTY_MODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_START_SHOW, handle_start_show, schema=START_SHOW_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_STOP_SHOW, handle_stop_show)
