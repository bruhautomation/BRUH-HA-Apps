"""The services brAIn drives the appliances with.

`start_cook` (from upstream) targets an appliance's Cook switch, which suits
an automation and not a conversation: somebody says "the Joule" or "the
oven", not `switch.kitchen_joule_cook`. These name the appliance instead
(its name, device id or serial; left out when the account has only one),
answer with what happened in words brAIn can repeat, and raise on every
refusal, so a refused start can never read as a started one. Every rule the
entities keep applies here too: untested models are monitor-only unless the
options allow control, a running oven cook can't be changed, and stopping
always works.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util.unit_conversion import TemperatureConverter

from .appliance import (
    CONVECTION_ALL,
    MODEL_BOV950,
    MODELS,
    OVEN_MODES,
    WAITING_STATES,
    CookSettings,
    oven_mode_defaults,
)
from .const import (
    ATTR_AUTO_START_TIMER,
    ATTR_CONVECTION,
    ATTR_DURATION,
    ATTR_KEEP_WARM,
    ATTR_LEVEL,
    ATTR_MODE,
    ATTR_TEMPERATURE,
    DOMAIN,
)

if TYPE_CHECKING:
    from .coordinator import Appliance, BrevilleCoordinator

SERVICE_GET_STATUS = "get_status"
SERVICE_GET_PRESETS = "get_presets"
SERVICE_START = "start"
SERVICE_STOP = "stop"
SERVICE_CONTINUE = "continue_cook"

ATTR_APPLIANCE = "appliance"
ATTR_PRESET = "preset"

APPLIANCE_SCHEMA = vol.Schema({vol.Optional(ATTR_APPLIANCE): cv.string})
START_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_APPLIANCE): cv.string,
        vol.Optional(ATTR_PRESET): cv.string,
        vol.Optional(ATTR_TEMPERATURE): vol.Coerce(float),
        vol.Optional(ATTR_DURATION): cv.positive_time_period,
        vol.Optional(ATTR_MODE): vol.In(list(OVEN_MODES)),
        vol.Optional(ATTR_CONVECTION): vol.In(list(CONVECTION_ALL)),
        vol.Optional(ATTR_LEVEL): vol.In(["low", "medium", "high"]),
        vol.Optional(ATTR_AUTO_START_TIMER): cv.boolean,
        vol.Optional(ATTR_KEEP_WARM): cv.boolean,
    }
)


def start_settings(
    hass: HomeAssistant, appliance: Appliance, options: dict[str, Any]
) -> CookSettings:
    """The settings a start with these options cooks with.

    Left-out options come from the appliance's settings, or from the mode's
    defaults when a mode is given (apart from the timer and keep-warm
    choices, which are the person's rather than the mode's).
    """
    # Lazily: select imports the package, which imports this module.
    from .select import LEVEL_OPTIONS

    settings = replace(appliance.settings)
    if (mode := options.get(ATTR_MODE)) is not None:
        if appliance.model != MODEL_BOV950:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="mode_oven_only"
            )
        defaults = oven_mode_defaults(OVEN_MODES[mode])
        defaults.auto_start_timer = settings.auto_start_timer
        defaults.keep_warm = settings.keep_warm
        settings = defaults
    if (temperature := options.get(ATTR_TEMPERATURE)) is not None:
        settings.temperature_c = TemperatureConverter.convert(
            temperature,
            hass.config.units.temperature_unit,
            UnitOfTemperature.CELSIUS,
        )
    if (duration := options.get(ATTR_DURATION)) is not None:
        settings.duration_s = (
            int(duration.total_seconds()) if isinstance(duration, timedelta) else int(duration)
        )
    if (convection := options.get(ATTR_CONVECTION)) is not None:
        settings.convection = convection
    if (level := options.get(ATTR_LEVEL)) is not None:
        oven_mode = OVEN_MODES.get(settings.mode or "")
        levels = LEVEL_OPTIONS.get(oven_mode.type, {}) if oven_mode else {}
        if level not in levels:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="level_not_for_mode",
                translation_placeholders={"level": level},
            )
        settings.level = int(levels[level])
    if ATTR_AUTO_START_TIMER in options:
        settings.auto_start_timer = options[ATTR_AUTO_START_TIMER]
    if ATTR_KEEP_WARM in options:
        settings.keep_warm = options[ATTR_KEEP_WARM]
    return settings


# -- finding the appliance ------------------------------------------------------


def _coordinators(hass: HomeAssistant) -> list[BrevilleCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        if getattr(entry, "runtime_data", None) is not None
    ]


def _device(hass: HomeAssistant, appliance: Appliance) -> dr.DeviceEntry | None:
    return dr.async_get(hass).async_get_device(identifiers={(DOMAIN, appliance.serial)})


def appliance_name(hass: HomeAssistant, appliance: Appliance) -> str:
    """The name a person knows it by: theirs in Home Assistant, else the app's."""
    device = _device(hass, appliance)
    if device is not None and (device.name_by_user or device.name):
        return device.name_by_user or device.name
    return appliance.name or MODELS[appliance.model].product


def _all(hass: HomeAssistant) -> list[tuple[BrevilleCoordinator, Appliance]]:
    return [
        (coordinator, appliance)
        for coordinator in _coordinators(hass)
        for appliance in coordinator.appliances.values()
        if appliance.on_account
    ]


def _fold(text: str) -> str:
    return " ".join(str(text).casefold().replace("_", " ").split())


def find_appliance(
    hass: HomeAssistant, wanted: str | None
) -> tuple[BrevilleCoordinator, Appliance]:
    """One appliance, by name, device id, serial, product or kind.

    Nothing named and one appliance on every account: that one. Anything
    that matches none, or more than one, is refused with the names there
    are, so the caller can ask which.
    """
    found = _all(hass)
    if not found:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_appliances")
    names = ", ".join(sorted(appliance_name(hass, a) for _, a in found))
    if not wanted or not str(wanted).strip():
        if len(found) == 1:
            return found[0]
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="which_appliance",
            translation_placeholders={"names": names},
        )
    key = _fold(wanted)
    exact, loose = [], []
    for coordinator, appliance in found:
        device = _device(hass, appliance)
        info = MODELS[appliance.model]
        ids = {_fold(appliance.serial)}
        if device is not None:
            ids.add(_fold(device.id))
        name = _fold(appliance_name(hass, appliance))
        if key in ids or key == name:
            exact.append((coordinator, appliance))
        elif key in name or key in _fold(info.product) or key == _fold(info.kind.value):
            loose.append((coordinator, appliance))
    matches = exact or loose
    if len(matches) == 1:
        return matches[0]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_appliance" if not matches else "which_appliance",
        translation_placeholders={"appliance": str(wanted), "names": names},
    )


# -- what an appliance is doing ---------------------------------------------------


def _temperature(hass: HomeAssistant, celsius: float | None) -> float | None:
    if celsius is None:
        return None
    value = TemperatureConverter.convert(
        celsius, UnitOfTemperature.CELSIUS, hass.config.units.temperature_unit
    )
    return round(value, 1)


def _minutes(seconds: int | None) -> int | None:
    return None if seconds is None else round(seconds / 60)


def describe(
    hass: HomeAssistant, coordinator: BrevilleCoordinator, appliance: Appliance
) -> dict[str, Any]:
    """One appliance as brAIn reads it: what it is doing, and what the next cook would be."""
    status = appliance.status
    info = MODELS[appliance.model]
    settings = appliance.settings
    device = _device(hass, appliance)
    out: dict[str, Any] = {
        "name": appliance_name(hass, appliance),
        "device_id": device.id if device is not None else None,
        "product": info.product,
        "kind": info.kind.value,
        "online": status.online and coordinator.connected,
        "state": status.state.value,
        "cooking": status.cooking,
        "temperature_unit": hass.config.units.temperature_unit,
        "current_temperature": _temperature(hass, status.current_temp_c),
        "target_temperature": _temperature(hass, status.target_temp_c),
        "time_remaining_minutes": _minutes(status.time_remaining_s),
        "ends_at": status.ends_at.isoformat() if status.ends_at else None,
        "preheat_percent": status.preheat_pct,
        "error": None if status.error == "none" else status.error,
        "control_allowed": coordinator.control_allowed(appliance),
        "can_change_running_cook": info.can_edit_cook,
        "waiting_for_continue": status.state in WAITING_STATES and status.active,
        "next_cook": {
            "temperature": _temperature(hass, settings.temperature_c),
            "duration_minutes": _minutes(settings.duration_s) or None,
            "auto_start_timer": settings.auto_start_timer,
        },
    }
    if info.kind.value == "oven":
        out["mode"] = status.cook_mode or status.mode
        out["convection"] = status.convection
        out["door_open"] = status.door_open
        out["next_cook"].update(
            mode=settings.mode, convection=settings.convection, keep_warm=settings.keep_warm
        )
    return out


# -- the services -------------------------------------------------------------------


async def _custom_presets(hass: HomeAssistant) -> list[Any]:
    from .panel_api import _panel_data

    return await _panel_data(hass).async_custom()


async def _get_status(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    if call.data.get(ATTR_APPLIANCE):
        return {"appliances": [describe(hass, *find_appliance(hass, call.data[ATTR_APPLIANCE]))]}
    return {"appliances": [describe(hass, c, a) for c, a in _all(hass)]}


async def _get_presets(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    from .presets import BUILTIN_PRESETS, preset_fits

    if call.data.get(ATTR_APPLIANCE):
        appliances = [find_appliance(hass, call.data[ATTR_APPLIANCE])[1]]
    else:
        appliances = [a for _, a in _all(hass)]
    out = []
    for preset in (*BUILTIN_PRESETS, *await _custom_presets(hass)):
        fits = [appliance_name(hass, a) for a in appliances if preset_fits(preset, a.model)]
        if not fits:
            continue
        settings = preset.settings
        out.append(
            {
                "id": preset.id,
                "name": preset.name or preset.id.replace("_", " "),
                "kind": preset.kind.value,
                "builtin": preset.builtin,
                "note": preset.note,
                "temperature": _temperature(hass, settings.get("temperature_c")),
                "duration_minutes": _minutes(settings.get("duration_s")) or None,
                "mode": settings.get("mode"),
                "level": settings.get("level"),
                "fits": fits,
            }
        )
    return {"presets": out}


async def _preset_settings(
    hass: HomeAssistant, appliance: Appliance, wanted: str
) -> CookSettings:
    from .presets import BUILTIN_PRESETS, PresetError, applied_settings

    key = _fold(wanted)
    presets = (*BUILTIN_PRESETS, *await _custom_presets(hass))
    preset = next(
        (p for p in presets if _fold(p.id) == key or (p.name and _fold(p.name) == key)), None
    )
    if preset is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_preset",
            translation_placeholders={"preset": wanted},
        )
    fahrenheit = hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT
    try:
        return applied_settings(preset, appliance.model, appliance.settings, fahrenheit=fahrenheit)
    except PresetError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="preset_does_not_fit",
            translation_placeholders={"preset": wanted, "error": str(err)},
        ) from err


async def _start(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    coordinator, appliance = find_appliance(hass, call.data.get(ATTR_APPLIANCE))
    if appliance.status.active:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="already_cooking",
            translation_placeholders={"appliance": appliance_name(hass, appliance)},
        )
    options = dict(call.data)
    if options.get(ATTR_PRESET):
        base = await _preset_settings(hass, appliance, options[ATTR_PRESET])
        # The preset is the starting point; anything said beside it wins.
        # Keep the person's timer and keep-warm switches, as a mode change does.
        preset_appliance = replace(appliance, settings=base)
        settings = start_settings(hass, preset_appliance, options)
    else:
        settings = start_settings(hass, appliance, options)
    await coordinator.async_start_cook(appliance, settings)
    name = appliance_name(hass, appliance)
    unit = hass.config.units.temperature_unit
    answer: dict[str, Any] = {
        "appliance": name,
        "started": True,
        "temperature": _temperature(hass, settings.temperature_c),
        "temperature_unit": unit,
        "duration_minutes": _minutes(settings.duration_s) or None,
    }
    if appliance.model == MODEL_BOV950:
        answer["mode"] = settings.mode
        answer["message"] = (
            f"Sent the cook to {name}. The oven waits for Start to be pressed on its "
            "panel before it heats."
        )
    else:
        answer["message"] = f"Started {name}."
    return answer


async def _stop(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    coordinator, appliance = find_appliance(hass, call.data.get(ATTR_APPLIANCE))
    name = appliance_name(hass, appliance)
    if not appliance.status.cooking:
        return {"appliance": name, "stopped": False, "message": f"{name} isn't cooking."}
    await coordinator.async_stop_cook(appliance)
    return {"appliance": name, "stopped": True, "message": f"Stopped {name}."}


async def _continue(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    coordinator, appliance = find_appliance(hass, call.data.get(ATTR_APPLIANCE))
    name = appliance_name(hass, appliance)
    status = appliance.status
    if not (status.state in WAITING_STATES and status.active):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="nothing_to_continue",
            translation_placeholders={"appliance": name},
        )
    await coordinator.async_finish_wait(appliance)
    return {"appliance": name, "continued": True, "message": f"Pressed Continue on {name}."}


def async_register_services(hass: HomeAssistant) -> None:
    """Register the services brAIn calls. Every one answers."""
    table = (
        (SERVICE_GET_STATUS, _get_status, APPLIANCE_SCHEMA, SupportsResponse.ONLY),
        (SERVICE_GET_PRESETS, _get_presets, APPLIANCE_SCHEMA, SupportsResponse.ONLY),
        (SERVICE_START, _start, START_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_STOP, _stop, APPLIANCE_SCHEMA, SupportsResponse.OPTIONAL),
        (SERVICE_CONTINUE, _continue, APPLIANCE_SCHEMA, SupportsResponse.OPTIONAL),
    )
    for name, handler, schema, responds in table:

        async def run(call: ServiceCall, handler=handler) -> dict[str, Any]:
            return await handler(hass, call)

        hass.services.async_register(DOMAIN, name, run, schema=schema, supports_response=responds)
