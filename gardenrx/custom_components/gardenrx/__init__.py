"""GardenRX — the garden's harvests, sprays and stock, in Home Assistant.

The GardenRX add-on owns the data (a SQLite file in its own /data) and the
panel in the sidebar. This integration is the other half: sensors polled from
the add-on, services that do what the panel's buttons do, and the cards. It
never touches the database — every write goes to the add-on, which is the one
writer, so a harvest logged from a card and one logged in the panel are the
same insert.
"""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GardenRxClient, GardenRxError
from .const import (
    ACTIONS,
    CARDS_FILE,
    CARDS_URL_BASE,
    CONF_HOST,
    CONF_PORT,
    DEFAULT_PORT,
    DOMAIN,
    HARVEST_UNITS,
    SERVICE_COMPLETE_QUEUED_SPRAY,
    SERVICE_DELETE_HARVEST,
    SERVICE_DELETE_QUEUED_SPRAY,
    SERVICE_LOG_HARVEST,
    SERVICE_REFRESH,
    TOKEN_PATH,
    VERSION,
)
from .coordinator import GardenRxCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_ID = vol.All(vol.Coerce(int), vol.Range(min=1))

SCHEMAS = {
    SERVICE_LOG_HARVEST: vol.Schema(
        {
            vol.Required("crop"): vol.Any(cv.string, _ID),
            vol.Optional("variety"): vol.Any(cv.string, _ID),
            vol.Required("weight"): vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False)),
            vol.Optional("unit", default="lb"): vol.In(HARVEST_UNITS),
            vol.Optional("date"): cv.date,
            vol.Optional("notes"): vol.All(cv.string, vol.Length(max=500)),
        }
    ),
    SERVICE_DELETE_HARVEST: vol.Schema({vol.Required("id"): _ID}),
    SERVICE_COMPLETE_QUEUED_SPRAY: vol.Schema(
        {
            vol.Required("id"): _ID,
            vol.Optional("volume_gallons"): vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False)),
            vol.Optional("date"): cv.date,
        }
    ),
    SERVICE_DELETE_QUEUED_SPRAY: vol.Schema({vol.Required("id"): _ID}),
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await _register_cards(hass)
    return True


async def _register_cards(hass: HomeAssistant) -> None:
    """Serve the card file from this folder and load it on every frontend page.

    Served from the integration itself rather than /config/www, so a new
    install needs no restart for /local to exist and no dashboard resource to
    be added by hand.
    """
    if hass.data[DOMAIN].get("cards_registered"):
        return
    path = Path(__file__).parent / "frontend" / CARDS_FILE
    url_dir = f"{CARDS_URL_BASE}/{VERSION}"
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(url_dir, str(path.parent), True)]
        )
    except ImportError:  # Home Assistant before 2024.7
        hass.http.register_static_path(url_dir, str(path.parent), True)
    from homeassistant.components.frontend import add_extra_js_url

    add_extra_js_url(hass, f"{url_dir}/{CARDS_FILE}")
    hass.data[DOMAIN]["cards_registered"] = True
    _LOGGER.debug("GardenRX cards served at %s/%s", url_dir, CARDS_FILE)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = GardenRxClient(
        async_get_clientsession(hass),
        entry.data.get(CONF_HOST, "local-gardenrx"),
        int(entry.data.get(CONF_PORT, DEFAULT_PORT)),
        Path(hass.config.path(TOKEN_PATH)),
    )
    coordinator = GardenRxCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not any(isinstance(v, GardenRxCoordinator) for v in hass.data[DOMAIN].values()):
            for service in (*ACTIONS, SERVICE_REFRESH):
                hass.services.async_remove(DOMAIN, service)
    return unloaded


def _coordinator(hass: HomeAssistant) -> GardenRxCoordinator:
    for value in hass.data.get(DOMAIN, {}).values():
        if isinstance(value, GardenRxCoordinator):
            return value
    raise HomeAssistantError("GardenRX is not set up. Add it under Settings > Devices & services.")


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    def make(service: str):
        async def handle(call: ServiceCall) -> ServiceResponse:
            coordinator = _coordinator(hass)
            data = dict(call.data)
            if "date" in data:
                data["date"] = data["date"].isoformat()
            try:
                result = await coordinator.client.action(ACTIONS[service], data)
            except GardenRxError as err:
                # The add-on's own sentence, so it reaches the automation trace
                # or the card's error line instead of a green tick.
                raise HomeAssistantError(str(err)) from err
            await coordinator.async_request_refresh()
            return result

        return handle

    for service in ACTIONS:
        hass.services.async_register(
            DOMAIN,
            service,
            make(service),
            schema=SCHEMAS[service],
            supports_response=SupportsResponse.OPTIONAL,
        )

    async def refresh(call: ServiceCall) -> None:
        await _coordinator(hass).async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh)
