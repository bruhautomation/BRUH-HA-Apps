"""BRight integration entry-point.

Registers:
* a sensor platform polling /config/.bright/state.json (show status)
* bright.party_mode / bright.start_show / bright.stop_show, forwarded to the
  add-on via the file-based bridge
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .bridge import send_request
from .const import (
    DOMAIN,
    SERVICE_PARTY_MODE,
    SERVICE_START_PARTY,
    SERVICE_START_SHOW,
    SERVICE_STOP_SHOW,
)
from .coordinator import BrightCoordinator

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
    coordinator = BrightCoordinator(hass)
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
        vol.Optional("party"): cv.string,
        vol.Optional("media_player"): cv.entity_id,
        vol.Optional("folder"): cv.string,
        vol.Optional("vibe"): cv.string,
        vol.Optional("end_scene"): cv.entity_id,
        vol.Optional("shuffle"): cv.boolean,
    }
)

# Named parties get their own service rather than a field on party_mode,
# because they are a different ask: party_mode is "run something", and
# this is "run the evening I set up". The name is required here, which is
# what makes an automation fail loudly on a typo instead of quietly
# playing the default folder.
START_PARTY_SCHEMA = vol.Schema(
    {
        vol.Required("party"): cv.string,
        vol.Optional("media_player"): cv.entity_id,
        vol.Optional("end_scene"): cv.entity_id,
    }
)

START_SHOW_SCHEMA = vol.Schema(
    {
        vol.Required("track"): cv.string,
        vol.Optional("media_player"): cv.entity_id,
    }
)

STOP_SHOW_SCHEMA = vol.Schema(
    {
        # A scene instead of restoring: the show WAS the evening, and what
        # comes next is a room somebody has already described in Home
        # Assistant. Restoring would put the lights back to whatever they
        # were at 6pm, which is nobody's idea of "stop the party".
        vol.Optional("scene"): cv.entity_id,
    }
)


async def _forward(kind: str, data: dict) -> dict:
    """Send one request to the add-on and make its answer the caller's.

    The three services used to `await send_request(...)` and drop what came
    back, so an automation that asked for party mode with nothing analyzed
    got a green tick and a dark room: the add-on's "no analyzed tracks in
    /media/music — run the Library tab first" travelled all the way to Core
    and was thrown away one line from the person who needed it.

    A refusal is a `HomeAssistantError`, which is what puts the sentence in
    the automation trace and in the UI's red toast.
    """
    try:
        response = await send_request(kind, data)
    except TimeoutError as exc:
        raise HomeAssistantError(
            f"BRight did not answer in time — is the add-on running? ({exc})"
        ) from exc
    except OSError as exc:
        raise HomeAssistantError(
            f"BRight could not be reached: {exc}. The add-on and Home "
            f"Assistant share a folder under /config, so this usually means "
            f"the add-on is stopped."
        ) from exc
    if isinstance(response, dict) and response.get("ok") is False:
        raise HomeAssistantError(
            str(response.get("error") or f"BRight refused {kind}"))
    return response if isinstance(response, dict) else {}


def _register_services(hass: HomeAssistant) -> None:
    async def handle_party_mode(call: ServiceCall) -> None:
        await _forward(SERVICE_PARTY_MODE, dict(call.data))

    async def handle_start_show(call: ServiceCall) -> None:
        await _forward(SERVICE_START_SHOW, dict(call.data))

    async def handle_start_party(call: ServiceCall) -> None:
        await _forward(SERVICE_START_PARTY, dict(call.data))

    async def handle_stop_show(call: ServiceCall) -> None:
        await _forward(SERVICE_STOP_SHOW, dict(call.data))

    hass.services.async_register(
        DOMAIN, SERVICE_PARTY_MODE, handle_party_mode, schema=PARTY_MODE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_START_PARTY, handle_start_party,
        schema=START_PARTY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_START_SHOW, handle_start_show, schema=START_SHOW_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_STOP_SHOW, handle_stop_show, schema=STOP_SHOW_SCHEMA
    )
