"""BRUH Bambu Studio integration entry point.

Registers:
* sensors per printer, read from the add-on's state mirror
* the print and control services, forwarded to the add-on over the file
  bridge, each answering with the add-on's own reply so a script can
  branch on it — and raising with the add-on's own sentence when it
  refuses, so the reason is in the automation trace rather than a log
"""
from __future__ import annotations

import json
import time
from pathlib import Path

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
    RUNNING_FILE,
    ALERT_ACTIONS,
    SERVICE_ALERT_ACTION,
    SERVICE_CHECK_PRINT,
    SERVICE_DESIGN,
    SERVICE_DESIGN_STATUS,
    SERVICE_FIND,
    SERVICE_GCODE,
    SERVICE_IMPORT,
    SERVICE_LIGHT,
    SERVICE_LIST_FILES,
    SERVICE_OPEN,
    SERVICE_PAUSE,
    SERVICE_PRINT_FILE,
    SERVICE_PRINT_PART,
    SERVICE_PRINTER_FILES,
    SERVICE_RECONNECT,
    SERVICE_REFRESH,
    SERVICE_RESUME,
    SERVICE_SET_DETECTION,
    SERVICE_SLICE_FILE,
    SERVICE_SPEED,
    SERVICE_STATUS,
    SERVICE_STOP,
    SERVICE_TEMPERATURE,
    card_url,
)
from .alerts import AlertNotifier
from .coordinator import BruhBambuCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CAMERA]
PLATE_TYPES = ["auto", "textured_pei", "smooth_pei", "cool", "engineering"]
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
    vol.Optional("plate_type"): vol.In(PLATE_TYPES),
    vol.Optional("speed"): vol.In(["silent", "standard", "sport", "ludicrous"]),
    vol.Optional("layer_inspect"): cv.boolean,
    vol.Optional("copies"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    vol.Optional("settings"): dict,
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
    SERVICE_RECONNECT: PRINTER_ONLY,
    SERVICE_REFRESH: PRINTER_ONLY,
    SERVICE_CHECK_PRINT: PRINTER_ONLY,
    SERVICE_ALERT_ACTION: vol.Schema({
        PRINTER: cv.string, vol.Required("action"): vol.In(ALERT_ACTIONS),
        vol.Optional("alert"): cv.string}),
    SERVICE_SET_DETECTION: vol.Schema({
        PRINTER: cv.string,
        vol.Optional("enabled"): cv.boolean,
        vol.Optional("mode"): vol.In(["pause", "warn"]),
        vol.Optional("sensitivity"): vol.In(["low", "medium", "high"]),
        vol.Optional("light"): cv.boolean,
        vol.Optional("plate"): cv.boolean,
        vol.Optional("notify"): cv.string}),
}
DESIGN_SCHEMA = vol.Schema({
    vol.Optional("description"): cv.string,
    vol.Optional("name"): cv.string,
    vol.Optional("part"): cv.string,
    vol.Optional("message"): cv.string,
})

PRINT_PART_SCHEMA = vol.Schema({
    vol.Required("part"): cv.string,
    vol.Optional("version"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    PRINTER: cv.string,
    vol.Optional("slot"): vol.Any("external", vol.All(vol.Coerce(int), vol.Range(min=0, max=15))),
    vol.Optional("copies"): vol.All(vol.Coerce(int), vol.Range(min=1, max=50)),
    vol.Optional("timelapse"): cv.boolean,
    vol.Optional("settings"): dict,
})

# Design with brAIn: they answer with data and start work that takes
# minutes, so they answer as soon as it has started.
DESIGN_SERVICES = {
    SERVICE_DESIGN: DESIGN_SCHEMA,
    SERVICE_DESIGN_STATUS: vol.Schema({vol.Optional("part"): cv.string}),
    SERVICE_PRINT_PART: PRINT_PART_SCHEMA,
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
    notifier = AlertNotifier(hass, entry, coordinator, _forward)
    entry.async_on_unload(notifier.start())
    await hass.async_add_executor_job(_record_running)
    await _register_card(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _record_running() -> None:
    """Tell the add-on which copy of the integration Home Assistant runs."""
    try:
        manifest = json.loads((Path(__file__).parent / "manifest.json").read_text())
        RUNNING_FILE.parent.mkdir(parents=True, exist_ok=True)
        RUNNING_FILE.write_text(json.dumps({"version": manifest.get("version"),
                                            "at": int(time.time())}))
    except (OSError, ValueError):
        pass  # the add-on then reads "restart needed" a little longer than it is


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


def _check_design(data: dict) -> None:
    """A new part needs a description; a part already started needs a message."""
    if data.get("part"):
        if not str(data.get("message") or data.get("description") or "").strip():
            raise HomeAssistantError(
                "Say what to change about the part in `message`.")
    elif not str(data.get("description") or "").strip():
        raise HomeAssistantError(
            "Describe the part to design in `description`, or name a part in `part` "
            "with a `message` to change it.")


def _register_services(hass: HomeAssistant) -> None:
    def make(kind: str):
        async def handler(call: ServiceCall) -> dict:
            data = dict(call.data)
            if kind == SERVICE_DESIGN:
                _check_design(data)
            return await _forward(kind, data)
        return handler

    for name, schema in {**READS, **DESIGN_SERVICES}.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, make(name), schema=schema,
                                         supports_response=SupportsResponse.ONLY)
    for name, schema in SERVICES.items():
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, make(name), schema=schema,
                                         supports_response=SupportsResponse.OPTIONAL)
