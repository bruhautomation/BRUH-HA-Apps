"""GardenRX — the garden's harvests, sprays and stock, in Home Assistant.

The GardenRX add-on owns the data (a SQLite file in its own /data) and the
panel in the sidebar. This integration is the other half: sensors polled from
the add-on, services that do what the panel's buttons do, and the cards. It
never touches the database — every write goes to the add-on, which is the one
writer, so a harvest logged from a card and one logged in the panel are the
same insert.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
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
    READ_ONLY,
    SERVICE_ADD_CROP,
    SERVICE_ADD_VARIETY,
    SERVICE_ADJUST_INVENTORY,
    SERVICE_COMPLETE_QUEUED_SPRAY,
    SERVICE_DELETE_HARVEST,
    SERVICE_DELETE_QUEUED_SPRAY,
    SERVICE_GET_HARVESTS,
    SERVICE_LOG_HARVEST,
    SERVICE_LOG_NOTE,
    SERVICE_LOG_SPRAY,
    SERVICE_QUEUE_SPRAY,
    SERVICE_REFRESH,
    TOKEN_PATH,
    VERSION,
)
from .coordinator import GardenRxCoordinator
from .fingerprint import record_loaded

_LOGGER = logging.getLogger(__name__)

# What this Home Assistant loaded (fingerprint.py: the fingerprint of the
# code, taken at import), written at setup. The add-on's run.sh reads the
# record to say whether an update it deployed needs a restart of Home
# Assistant — only when the code differs.
LOADED_FILE = ".gardenrx/integration.json"

# The cards' URL carries a hash of the file and follows it: an update that
# changed only the cards owes no restart, so the URL has to move without one
# (it is served with a long cache header) for a page reload to load them.
CARDS_FOLLOW_S = 60

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_ID = vol.All(vol.Coerce(int), vol.Range(min=1))
_NAME = vol.All(cv.string, vol.Length(min=1, max=80))
_NOTES = vol.All(cv.string, vol.Length(max=500))
_POSITIVE = vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False))
# A crop or product named one at a time or as a list, by name or id.
_REFS = vol.All(cv.ensure_list, [vol.Any(cv.string, _ID)])

# What a spray is, logged or queued: the crops (or an area), the products and
# their rates. The add-on resolves the names and says which one is wrong.
_SPRAY = {
    vol.Optional("crop"): _REFS,
    # Orchard, Garden or Landscape — matched by the add-on in any case.
    vol.Optional("area"): vol.All(cv.ensure_list, [cv.string]),
    vol.Required("product"): _REFS,
    vol.Optional("rate"): vol.All(cv.ensure_list, [_POSITIVE]),
    vol.Optional("rate_unit"): vol.All(cv.ensure_list, [vol.All(cv.string, vol.Length(min=1, max=40))]),
    vol.Optional("notes"): _NOTES,
}

# Fields a service carries as a date; each is sent to the add-on as YYYY-MM-DD.
DATE_FIELDS = ("date", "planned_date", "start", "end")

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
    SERVICE_LOG_SPRAY: vol.Schema(
        {
            **_SPRAY,
            vol.Optional("volume_gallons"): _POSITIVE,
            vol.Optional("date"): cv.date,
        }
    ),
    SERVICE_QUEUE_SPRAY: vol.Schema({**_SPRAY, vol.Optional("planned_date"): cv.date}),
    SERVICE_ADJUST_INVENTORY: vol.Schema(
        {
            vol.Required("product"): vol.Any(cv.string, _ID),
            vol.Exclusive("change", "amount"): vol.Coerce(float),
            vol.Exclusive("quantity", "amount"): vol.All(vol.Coerce(float), vol.Range(min=0)),
            vol.Optional("unit"): vol.All(cv.string, vol.Length(min=1, max=20)),
            vol.Optional("notes"): _NOTES,
        }
    ),
    SERVICE_ADD_CROP: vol.Schema(
        {vol.Required("name"): _NAME, vol.Optional("crop_group"): vol.Any(cv.string, _ID)}
    ),
    SERVICE_ADD_VARIETY: vol.Schema(
        {vol.Required("crop"): vol.Any(cv.string, _ID), vol.Required("name"): _NAME}
    ),
    SERVICE_LOG_NOTE: vol.Schema(
        {
            vol.Required("place"): vol.Any(cv.string, _ID),
            vol.Required("note"): vol.All(cv.string, vol.Length(min=1, max=500)),
            vol.Optional("date"): cv.date,
        }
    ),
    SERVICE_GET_HARVESTS: vol.Schema(
        {
            vol.Optional("crop"): vol.Any(cv.string, _ID),
            vol.Optional("start"): cv.date,
            vol.Optional("end"): cv.date,
        }
    ),
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await hass.async_add_executor_job(record_loaded, hass.config.path(LOADED_FILE), VERSION)
    await _register_cards(hass)
    return True


def _cards_url(path: Path, url_dir: str) -> str | None:
    """The cards' URL with the file's own bytes on the end. Reads the file,
    so call it in the executor."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return None
    return f"{url_dir}/{CARDS_FILE}?v={digest}"


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
    from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
    from homeassistant.helpers.event import async_track_time_interval

    url = await hass.async_add_executor_job(_cards_url, path, url_dir) or f"{url_dir}/{CARDS_FILE}"
    add_extra_js_url(hass, url)
    hass.data[DOMAIN]["cards_registered"] = url
    _LOGGER.debug("GardenRX cards served at %s", url)

    async def _follow(_now=None) -> None:
        now = await hass.async_add_executor_job(_cards_url, path, url_dir)
        before = hass.data[DOMAIN].get("cards_registered")
        if now and isinstance(before, str) and now != before:
            remove_extra_js_url(hass, before)
            add_extra_js_url(hass, now)
            hass.data[DOMAIN]["cards_registered"] = now

    async_track_time_interval(hass, _follow, timedelta(seconds=CARDS_FOLLOW_S), cancel_on_shutdown=True)


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
            for field in DATE_FIELDS:
                if hasattr(data.get(field), "isoformat"):
                    data[field] = data[field].isoformat()
            try:
                result = await coordinator.client.action(ACTIONS[service], data)
            except GardenRxError as err:
                # The add-on's own sentence, so it reaches the automation trace
                # or the card's error line instead of a green tick.
                raise HomeAssistantError(str(err)) from err
            if service not in READ_ONLY:
                await coordinator.async_request_refresh()
            return result

        return handle

    for service in ACTIONS:
        hass.services.async_register(
            DOMAIN,
            service,
            make(service),
            schema=SCHEMAS[service],
            supports_response=(
                SupportsResponse.ONLY if service in READ_ONLY else SupportsResponse.OPTIONAL
            ),
        )

    async def refresh(call: ServiceCall) -> None:
        await _coordinator(hass).async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh)
