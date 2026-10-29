"""How the sidebar panel draws each appliance: its kind, finish and oven modes.

No Home Assistant imports. The panel receives these as `finish` and
`oven_modes` (frontend/src/types.ts).
"""

from __future__ import annotations

import re
from typing import Any

from .appliance import (
    MODEL_BOV950,
    MODELS,
    OVEN_MODES,
    TASK_ENGINE_MODES,
    BroilLevel,
    OvenModeType,
    SlowCookLevel,
)

# The Joule and the Joule Turbo look the same: a white body with polished
# stainless trim.
FINISH_WHITE_POLISHED = "white_polished"
FINISH_BRUSHED_STAINLESS = "brushed_stainless"
FINISH_BLACK_STAINLESS = "black_stainless"
FINISHES = (FINISH_WHITE_POLISHED, FINISH_BRUSHED_STAINLESS, FINISH_BLACK_STAINLESS)

# The finish part of an oven's item number, as sold: BOV950BSS1BUS1 is brushed
# stainless, BOV950BST1BUS1 black stainless.
OVEN_ITEM_FINISH = re.compile(r"^BOV950(BSS|BST)", re.IGNORECASE)
ITEM_FINISHES = {"BSS": FINISH_BRUSHED_STAINLESS, "BST": FINISH_BLACK_STAINLESS}
# The app's parseSerialNumber: supplier, brand, region, colour, subcategory,
# version, then nine digits. The colour code is the fifth character.
SERIAL = re.compile(r"^[A-Z0-9]{2}[A-Z0-9][A-Z0-9]([A-Z0-9])[A-Z0-9]{2}[A-Z0-9]\d{9}$", re.IGNORECASE)
# Colour codes with an oven drawing: A stainless steel, H black stainless.
SERIAL_FINISHES = {"A": FINISH_BRUSHED_STAINLESS, "H": FINISH_BLACK_STAINLESS}

LEVELS = {
    OvenModeType.BROIL: {"low": BroilLevel.LOW, "medium": BroilLevel.MEDIUM, "high": BroilLevel.HIGH},
    OvenModeType.SLOW_COOK: {"low": SlowCookLevel.LOW, "high": SlowCookLevel.HIGH},
}

# What the oven drawing shows for each mode: the accessory on the rack, the
# food on it, and which elements glow. The oven doesn't report its elements,
# so they follow the mode. Modes that can only be started on the oven are
# here too, for when it reports them. A rack here is the instruction book's,
# for modes whose recipe doesn't place one (position 1 is the top).
OVEN_DRAWING: dict[str, dict[str, Any]] = {
    "bake": {"accessory": "roasting_pan", "food": "croissants", "elements": "top_bottom"},
    "bottom_bake": {"accessory": "roasting_pan", "food": "casserole", "elements": "bottom"},
    "gentle_broil": {"accessory": "air_fry_basket", "food": "fries", "elements": "top"},
    "roast": {"accessory": "broil_rack", "food": "chicken", "elements": "top_bottom"},
    "broil": {"accessory": "broil_rack", "food": "steak", "elements": "top"},
    "bottom_broil": {"accessory": "broil_rack", "food": "steak", "elements": "bottom"},
    "outer_top_broil": {"accessory": "broil_rack", "food": "steak", "elements": "outer_top"},
    "middle_top_broil": {"accessory": "broil_rack", "food": "steak", "elements": "middle_top"},
    "windy_broil": {"accessory": "broil_rack", "food": "steak", "elements": "top"},
    "air_fry": {"accessory": "air_fry_basket", "food": "fries", "elements": "top"},
    "pizza": {"accessory": "pizza_pan", "food": "pizza", "elements": "top_bottom"},
    "cookies": {"accessory": "roasting_pan", "food": "cookies", "elements": "top_bottom"},
    "reheat": {"accessory": "wire_rack", "food": "plate", "elements": "top_bottom"},
    "slow_cook": {"accessory": "pot", "food": None, "elements": "bottom_low"},
    "proof": {"accessory": "wire_rack", "food": "dough", "elements": "bottom_low", "rack": 8},
    "warm": {"accessory": "wire_rack", "food": "covered_dish", "elements": "low"},
    "dehydrate": {"accessory": "air_fry_basket", "food": "fruit", "elements": "low"},
    "toast": {"accessory": "wire_rack", "food": "bread", "elements": "top_bottom", "rack": 4},
    "bagel": {"accessory": "wire_rack", "food": "bagel", "elements": "top_bottom", "rack": 4},
    "crispy_reheat": {"accessory": "wire_rack", "food": "pizza_slice", "elements": "top_bottom"},
    "keep_warm": {"accessory": "wire_rack", "food": "covered_dish", "elements": "low"},
}
# Where the rack goes for other modes: the middle of the 8 positions.
MIDDLE_RACK = 4


def detect_finish(model: str, item_number: str | None, serial: str | None) -> str:
    """The appliance's finish, from its item number, else its serial number's colour code.

    The serial number is only read here; it never leaves the backend.
    """
    if model != MODEL_BOV950:
        return FINISH_WHITE_POLISHED
    if item_number and (match := OVEN_ITEM_FINISH.match(item_number.strip())):
        return ITEM_FINISHES[match.group(1).upper()]
    if serial and (match := SERIAL.match(serial.strip())):
        return SERIAL_FINISHES.get(match.group(1).upper(), FINISH_BRUSHED_STAINLESS)
    return FINISH_BRUSHED_STAINLESS


def kind_of(model: str) -> str:
    return MODELS[model].kind.value


def _mode(option: str) -> dict[str, Any]:
    """One mode as the panel describes it (OvenModeSpec)."""
    mode = OVEN_MODES.get(option)
    drawing = dict(OVEN_DRAWING[option])
    rack = drawing.pop("rack", MIDDLE_RACK)
    if mode is None:
        # Started on the oven itself: the panel only draws it.
        return {"id": option, "remote": False, "type": None, "rack": rack, **drawing}
    levels = LEVELS.get(mode.type)
    return {
        "id": option,
        "remote": True,
        "type": mode.type.value,
        "rack": mode.rack or rack,
        "preheat": mode.preheat,
        "temperature_c": (
            {"default": mode.temp[0], "min": mode.temp[1], "max": mode.temp[2], "step": mode.round_to}
            if mode.temp
            else None
        ),
        "levels": list(levels) if levels else None,
        "default_level": (
            next(name for name, value in levels.items() if value == mode.level) if levels else None
        ),
        "default_seconds": mode.default_seconds(),
        "convection": list(mode.convection_allowed),
        "default_convection": mode.convection,
        "frozen": mode.frozen_default,
        "keep_warm": mode.keep_warm_allowed,
        **drawing,
    }


def oven_mode_table() -> list[dict[str, Any]]:
    """Every mode the oven can report, those that can be started remotely first."""
    reported = [option for option in dict.fromkeys(TASK_ENGINE_MODES.values()) if option in OVEN_DRAWING]
    return [_mode(option) for option in (*OVEN_MODES, *(o for o in reported if o not in OVEN_MODES))]
