"""Cook presets for the sidebar panel: the built-in ones and their rules.

A preset fills in an appliance's cook settings; it never starts a cook. The
built-in sous vide presets follow published food-safety guidance (USDA FSIS,
the FDA Food Code, and Douglas Baldwin's sous vide tables), and below 54.5 °C
(130 °F) none cooks for more than 2 hours 30 minutes. Custom presets only have
to fit the appliances' limits: they're up to the admins who save them. Oven
presets carry a round temperature in both units, so a 400 °F preset stays
400 °F.

No Home Assistant imports. The panel receives presets as `Preset` in
frontend/src/types.ts; built-in names are translated there, by id.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .appliance import (
    HOUR,
    MINUTE,
    MODEL_BOV950,
    MODELS,
    OVEN_MODES,
    CookSettings,
    Kind,
    OvenModeType,
    duration_limits,
    oven_mode_defaults,
    temp_limits,
)
from .panel_spec import LEVELS

MAX_CUSTOM_PRESETS = 50
MAX_NAME_LENGTH = 40
# Below this, sous vide doesn't pasteurize, so a cook is kept short.
SHORT_COOK_BELOW_C = 54.5
SHORT_COOK_MAX_S = 2 * HOUR + 30 * MINUTE
# Seafood below this (the FDA Food Code's 145 °F) isn't pasteurized: use fish
# that's safe to eat raw.
SEAFOOD_SAFE_C = 63.0

NOTE_RAW_SAFE_FISH = "raw_safe_fish"


@dataclass(frozen=True)
class Preset:
    """A built-in or custom preset. Built-in ones have no name; the panel translates them."""

    id: str
    kind: Kind
    settings: dict[str, Any]
    name: str | None = None
    note: str | None = None

    @property
    def builtin(self) -> bool:
        return self.name is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "builtin": self.builtin,
            "name": self.name,
            "note": self.note,
            "settings": dict(self.settings),
        }


def _sous_vide(preset_id: str, celsius: float, seconds: int, note: str | None = None) -> Preset:
    return Preset(preset_id, Kind.SOUS_VIDE, {"temperature_c": celsius, "duration_s": seconds}, note=note)


def _oven(preset_id: str, mode: str, seconds: int, **settings: Any) -> Preset:
    return Preset(preset_id, Kind.OVEN, {"mode": mode, **settings, "duration_s": seconds})


BUILTIN_PRESETS: tuple[Preset, ...] = (
    _sous_vide("steak_rare", 52, 90 * MINUTE),
    _sous_vide("steak_medium_rare", 56, 90 * MINUTE),
    _sous_vide("steak_medium", 60, 90 * MINUTE),
    _sous_vide("steak_well_done", 70, 90 * MINUTE),
    _sous_vide("beef_roast", 56, 6 * HOUR),
    _sous_vide("short_ribs", 57, 48 * HOUR),
    _sous_vide("pork_chop", 60, 2 * HOUR),
    _sous_vide("pulled_pork", 74, 24 * HOUR),
    _sous_vide("chicken_breast", 63, 2 * HOUR),
    _sous_vide("chicken_thighs", 65, 2 * HOUR),
    _sous_vide("salmon", 50, 45 * MINUTE, NOTE_RAW_SAFE_FISH),
    _sous_vide("white_fish", 55, 30 * MINUTE, NOTE_RAW_SAFE_FISH),
    _sous_vide("shrimp", 57, 30 * MINUTE, NOTE_RAW_SAFE_FISH),
    _sous_vide("soft_eggs", 63, 45 * MINUTE),
    _sous_vide("vegetables", 85, HOUR),
    _oven("frozen_fries", "air_fry", 20 * MINUTE, temperature_c=205, temperature_f=400),
    _oven("chicken_wings", "air_fry", 25 * MINUTE, temperature_c=205, temperature_f=400),
    _oven("frozen_pizza", "pizza", 16 * MINUTE, temperature_c=205, temperature_f=400, frozen=True),
    _oven("fresh_pizza", "pizza", 12 * MINUTE, temperature_c=230, temperature_f=450, frozen=False),
    _oven("roast_vegetables", "roast", 30 * MINUTE, temperature_c=205, temperature_f=400),
    _oven("roast_chicken", "roast", 75 * MINUTE, temperature_c=205, temperature_f=400),
    _oven("cookies", "cookies", 11 * MINUTE, temperature_c=175, temperature_f=350, frozen=False),
    _oven("cake", "bake", 35 * MINUTE, temperature_c=175, temperature_f=350),
    _oven("leftovers", "reheat", 15 * MINUTE, temperature_c=165, temperature_f=325, frozen=False),
    _oven("salmon_fillets", "broil", 8 * MINUTE, level="high"),
    _oven("dried_fruit", "dehydrate", 8 * HOUR, temperature_c=57, temperature_f=135),
    _oven("bread_dough", "proof", HOUR, temperature_c=29, temperature_f=85),
    _oven("pot_roast", "slow_cook", 8 * HOUR, level="low"),
)


class PresetError(ValueError):
    """A preset that can't be saved or applied, with the reason."""


def short_enough(preset: Preset) -> bool:
    """The built-in presets' safety rule: below 54.5 °C, no more than 2 hours 30 minutes."""
    if preset.kind is not Kind.SOUS_VIDE or preset.settings["temperature_c"] >= SHORT_COOK_BELOW_C:
        return True
    seconds = preset.settings.get("duration_s") or 0
    return 0 < seconds <= SHORT_COOK_MAX_S


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    return (fahrenheit - 32) * 5 / 9


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def check_settings(kind: Kind, settings: dict[str, Any]) -> None:
    """Raise PresetError unless the settings make a cook of this kind any appliance could do."""
    seconds = settings.get("duration_s")
    if seconds is not None and (not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0):
        raise PresetError("The cook time must be a whole number of seconds")
    if kind is Kind.SOUS_VIDE:
        celsius = _number(settings.get("temperature_c"))
        if celsius is None:
            raise PresetError("A sous vide preset needs a temperature")
        low = min(info.min_temp_c for info in MODELS.values() if info.kind is Kind.SOUS_VIDE)
        high = max(info.max_temp_c for info in MODELS.values() if info.kind is Kind.SOUS_VIDE)
        if not low <= celsius <= high:
            raise PresetError(f"The temperature must be {low:g}–{high:g} °C")
        if seconds and seconds > max(info.max_cook_s for info in MODELS.values()):
            raise PresetError("The cook time is too long")
        return
    mode = OVEN_MODES.get(settings.get("mode") or "")
    if mode is None:
        raise PresetError("An oven preset needs a mode that can be started remotely")
    if mode.type is OvenModeType.TEMP:
        celsius = _number(settings.get("temperature_c"))
        if celsius is None:
            raise PresetError("This mode needs a temperature")
        # Rounded first, as the oven is sent it.
        if not mode.temp[1] <= round(celsius) <= mode.temp[2]:
            raise PresetError(f"The temperature must be {mode.temp[1]}–{mode.temp[2]} °C")
    elif settings.get("level") not in LEVELS[mode.type]:
        raise PresetError("This mode needs a level")
    low, high = duration_limits(MODEL_BOV950, oven_settings(settings, CookSettings(), fahrenheit=False))
    if not seconds or not low <= seconds <= high:
        raise PresetError("The cook time doesn't fit this mode")
    convection = settings.get("convection")
    if convection is not None and convection not in mode.convection_allowed:
        raise PresetError("This mode doesn't offer that convection setting")
    frozen = settings.get("frozen")
    if frozen is not None and (not isinstance(frozen, bool) or mode.frozen_default is None):
        raise PresetError("This mode doesn't offer frozen food")


def oven_settings(
    settings: dict[str, Any], current: CookSettings, *, fahrenheit: bool
) -> CookSettings:
    """The cook settings an oven preset makes: the mode's defaults, then the preset.

    As choosing a mode does, it keeps Start timer automatically and Keep warm.
    The preset's temperature is in the unit Home Assistant shows, when it has one.
    """
    mode = OVEN_MODES[settings["mode"]]
    result = oven_mode_defaults(mode)
    result.auto_start_timer = current.auto_start_timer
    result.keep_warm = current.keep_warm
    if fahrenheit and _number(settings.get("temperature_f")) is not None:
        result.temperature_c = fahrenheit_to_celsius(settings["temperature_f"])
    elif _number(settings.get("temperature_c")) is not None:
        result.temperature_c = float(settings["temperature_c"])
    if (level := settings.get("level")) in LEVELS.get(mode.type, {}):
        result.level = int(LEVELS[mode.type][level])
    if settings.get("duration_s"):
        result.duration_s = int(settings["duration_s"])
    if settings.get("convection") in mode.convection_allowed:
        result.convection = settings["convection"]
    if mode.frozen_default is not None and isinstance(settings.get("frozen"), bool):
        result.frozen = settings["frozen"]
    return result


def preset_fits(preset: Preset, model: str) -> bool:
    """Whether an appliance can cook the preset: its kind, and its limits."""
    info = MODELS[model]
    if preset.kind is not info.kind:
        return False
    if preset.kind is Kind.SOUS_VIDE:
        celsius = preset.settings["temperature_c"]
        seconds = preset.settings.get("duration_s") or 0
        return info.min_temp_c <= celsius <= info.max_temp_c and seconds <= info.max_cook_s
    try:
        check_settings(preset.kind, preset.settings)
    except PresetError:
        return False
    return True


def applied_settings(
    preset: Preset, model: str, current: CookSettings, *, fahrenheit: bool
) -> CookSettings:
    """The appliance's cook settings once the preset is applied.

    Raises PresetError when the preset doesn't fit the appliance.
    """
    if not preset_fits(preset, model):
        raise PresetError(f"This preset doesn't fit the {MODELS[model].product}")
    if preset.kind is Kind.OVEN:
        return oven_settings(preset.settings, current, fahrenheit=fahrenheit)
    seconds = preset.settings.get("duration_s") or None
    low, high = temp_limits(model)
    return replace(
        current,
        temperature_c=min(high, max(low, float(preset.settings["temperature_c"]))),
        duration_s=seconds,
    )


def settings_preset(model: str, settings: CookSettings) -> dict[str, Any]:
    """A custom preset's settings, from an appliance's current cook settings."""
    if MODELS[model].kind is Kind.SOUS_VIDE:
        return {"temperature_c": settings.temperature_c, "duration_s": settings.duration_s or 0}
    mode = OVEN_MODES[settings.mode or "bake"]
    out: dict[str, Any] = {"mode": mode.option, "duration_s": settings.duration_s or mode.default_seconds()}
    if mode.type is OvenModeType.TEMP:
        out["temperature_c"] = settings.temperature_c
    else:
        out["level"] = next(
            (name for name, value in LEVELS[mode.type].items() if value == settings.level),
            next(name for name, value in LEVELS[mode.type].items() if value == mode.level),
        )
    if settings.convection in mode.convection_allowed:
        out["convection"] = settings.convection
    if mode.frozen_default is not None and settings.frozen is not None:
        out["frozen"] = bool(settings.frozen)
    return out


def clean_name(name: Any) -> str:
    """A custom preset's name, trimmed; raises PresetError if it's empty or too long."""
    text = " ".join(name.split()) if isinstance(name, str) else ""
    if not text:
        raise PresetError("Give the preset a name")
    if len(text) > MAX_NAME_LENGTH:
        raise PresetError(f"A preset's name can be at most {MAX_NAME_LENGTH} characters")
    return text


def read_custom(stored: Any) -> list[Preset]:
    """Custom presets from storage, skipping anything malformed."""
    presets = stored.get("presets") if isinstance(stored, dict) else None
    out: list[Preset] = []
    for item in presets if isinstance(presets, list) else []:
        try:
            kind = Kind(item["kind"])
            settings = dict(item["settings"])
            check_settings(kind, settings)
            out.append(Preset(str(item["id"]), kind, settings, name=clean_name(item["name"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out[:MAX_CUSTOM_PRESETS]


def write_custom(presets: list[Preset]) -> dict[str, Any]:
    return {
        "presets": [
            {"id": p.id, "kind": p.kind.value, "name": p.name, "settings": p.settings} for p in presets
        ]
    }
