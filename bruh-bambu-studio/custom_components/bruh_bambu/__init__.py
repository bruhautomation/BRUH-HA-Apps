"""BRUH Bambu Studio integration entry point.

Registers:
* sensors per printer, read from the add-on's state mirror
* the print and control services, forwarded to the add-on over the file
  bridge, each answering with the add-on's own reply so a script can
  branch on it — and raising with the add-on's own sentence when it
  refuses, so the reason is in the automation trace rather than a log
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later

from .bridge import send_request
from .const import (
    CARD_FILE,
    CARD_RETRY_SECONDS,
    CARD_RETRY_TRIES,
    DOMAIN,
    SERVICE_FIND,
    SERVICE_GCODE,
    SERVICE_IMPORT,
    SERVICE_LIGHT,
    SERVICE_LIST_FILES,
    SERVICE_OPEN,
    SERVICE_PAUSE,
    SERVICE_PRINT_FILE,
    SERVICE_PRINTER_FILES,
    SERVICE_RESUME,
    SERVICE_SLICE_FILE,
    SERVICE_SPEED,
    SERVICE_STATUS,
    SERVICE_STOP,
    SERVICE_TEMPERATURE,
    card_url,
)
from .coordinator import BruhBambuCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PRINTER = vol.Optional("printer")
PLATE = vol.All(vol.Coerce(int), vol.Range(min=0, max=64))

PRINTER_ONLY = vol.Schema({PRINTER: cv.string})

PRINT_FILE_SCHEMA = vol.Schema({
    vol.Required("file"): cv.string,
    PRINTER: cv.string,
    vol.Optional("plate"): PLATE,
    vol.Optional("use_ams"): cv.boolean,
    vol.Optional("ams_mapping"): vol.All(cv.ensure_list, [vol.Coerce(int)]),
    vol.Optional("timelapse"): cv.boolean,
    vol.Optional("bed_leveling"): cv.boolean,
    vol.Optional("flow_cali"): cv.boolean,
    vol.Optional("vibration_cali"): cv.boolean,
    vol.Optional("machine"): cv.string,
    vol.Optional("process"): cv.string,
    vol.Optional("filaments"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("slot"): vol.Any("external", vol.All(vol.Coerce(int), vol.Range(min=0, max=15))),
    vol.Optional("material"): cv.string,
    vol.Optional("colour"): cv.string,
})

IMPORT_SCHEMA = vol.Schema({vol.Required("url"): cv.string})

SLICE_SCHEMA = vol.Schema({
    vol.Required("file"): cv.string,
    vol.Optional("plate"): PLATE,
    vol.Optional("machine"): cv.string,
    vol.Optional("process"): cv.string,
    vol.Optional("filaments"): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional("arrange"): cv.boolean,
    vol.Optional("orient"): cv.boolean,
})

SERVICES = {
    SERVICE_PRINT_FILE: PRINT_FILE_SCHEMA,
    SERVICE_SLICE_FILE: SLICE_SCHEMA,
    SERVICE_PAUSE: PRINTER_ONLY,
    SERVICE_RESUME: PRINTER_ONLY,
    SERVICE_STOP: PRINTER_ONLY,
    SERVICE_SPEED: vol.Schema({PRINTER: cv.string, vol.Required("speed"): vol.In(
        ["silent", "standard", "sport", "ludicrous"])}),
    SERVICE_LIGHT: vol.Schema({PRINTER: cv.string, vol.Required("on"): cv.boolean}),
    SERVICE_TEMPERATURE: vol.Schema({
        PRINTER: cv.string, vol.Required("target"): vol.In(["nozzle", "bed"]),
        vol.Required("temperature"): vol.All(vol.Coerce(int), vol.Range(min=0, max=300))}),
    SERVICE_GCODE: vol.Schema({PRINTER: cv.string, vol.Required("gcode"): cv.string}),
    SERVICE_OPEN: vol.Schema({vol.Required("file"): cv.string}),
    SERVICE_IMPORT: IMPORT_SCHEMA,
}
# Reads: they answer with data and change nothing.
READS = {
    SERVICE_STATUS: vol.Schema({}),
    SERVICE_LIST_FILES: vol.Schema({}),
    SERVICE_PRINTER_FILES: PRINTER_ONLY,
    SERVICE_FIND: vol.Schema({vol.Optional("subnet"): cv.string}),
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = BruhBambuCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await _register_card(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _register_card(hass: HomeAssistant, tries: int = 0) -> None:
    """Put the printer card in the dashboard card picker.

    `add_extra_js_url` works in storage and YAML mode alike and needs no
    restart. The file is looked for again for a while, because Core can set
    this entry up before the add-on has copied the card in; it is never
    registered while missing, or every page load logs a 404.
    """
    def _url() -> str | None:
        return card_url(CARD_FILE) if CARD_FILE.is_file() else None

    url = await hass.async_add_executor_job(_url)
    if url is None:
        if tries + 1 < CARD_RETRY_TRIES:
            async_call_later(hass, CARD_RETRY_SECONDS,
                             lambda _now: hass.async_create_task(_register_card(hass, tries + 1)))
        return
    try:
        from homeassistant.components.frontend import add_extra_js_url
    except ImportError:  # pragma: no cover - frontend is always there in core
        return
    add_extra_js_url(hass, url)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _forward(kind: str, data: dict) -> dict:
    """Send one request and make the add-on's answer the caller's."""
    try:
        response = await send_request(kind, data)
    except TimeoutError as exc:
        raise HomeAssistantError(str(exc)) from exc
    except OSError as exc:
        raise HomeAssistantError(
            f"BRUH Bambu Studio could not be reached: {exc}. The add-on and Home "
            f"Assistant share a folder under /config, so this usually means the "
            f"add-on is stopped.") from exc
    if not isinstance(response, dict):
        return {}
    if response.get("ok") is False:
        raise HomeAssistantError(
            str(response.get("error") or f"BRUH Bambu Studio refused {kind}"))
    job = response.get("job")
    if isinstance(job, dict) and job.get("state") == "failed":
        raise HomeAssistantError(str(job.get("error") or f"{kind} failed"))
    return {k: v for k, v in response.items() if k != "ok"}


def _register_services(hass: HomeAssistant) -> None:
    def make(kind: str):
        async def handler(call: ServiceCall) -> dict:
            return await _forward(kind, dict(call.data))
        return handler

    for name, schema in READS.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, make(name), schema=schema,
                                         supports_response=SupportsResponse.ONLY)
    for name, schema in SERVICES.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, make(name), schema=schema,
                                         supports_response=SupportsResponse.OPTIONAL)
