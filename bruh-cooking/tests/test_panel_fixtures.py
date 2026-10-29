"""The sidebar panel's fixtures: what the panel receives in each state, from the real integration.

Each fixture in tests/fixtures/panel/ holds one appliance as the websocket API sends it, with
its entities' states as Home Assistant writes them, so the frontend's tests and demo page work
from exactly what the backend makes. The oven's states come from issue #1's diagnostics, set to
°F as the tester's was; the Joule's from the owner's probe captures, in °C. Nothing personal:
names are made up, ids are placeholders.

These tests fail when a fixture no longer matches; run them with UPDATE_PANEL_FIXTURES=1 to
write them again, and look at the diff.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.json import ExtendedJSONEncoder
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bruh_cooking.const import CONF_ALLOW_UNTESTED_CONTROL, DOMAIN
from custom_components.bruh_cooking.panel_api import panel_message

from .common import JOULE, OVEN, FakeSocket, call, csj, flush, push

FIXTURES = Path(__file__).parent / "fixtures" / "panel"
NOW = datetime(2026, 10, 25, 18, 0, tzinfo=UTC)
UPDATE = os.environ.get("UPDATE_PANEL_FIXTURES") == "1"


def oven(state: str = "active", **reported: Any) -> dict:
    """A stateReport shaped like the real BOV950's in issue #1 (set to °F)."""
    shadow = {
        "state": state, "model": "BOV950", "door": 1, "motor": 1, "errors": [],
        "cfg": {"temp_unit": 1, "vol": 11}, "timers": [None, None],
        "firmware": {"commFirmware": "1.10.131", "teFirmware": "2.4.0", "ctrlFirmware": "1.10.21"},
        "heater": {"state": 2, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 160},
        "appliance": {"mode": 3, "rotate_state": 0, "preset": 0, "cook_segment": 0, "frozen": 0},
        "recipe": "manual_x", "cookUUID": "cook-7", "currentStage": 0, "currentStep": 0,
        "currentInstruction": 10, "currentStepState": "active", **reported,
    }
    oven.version += 1
    return {"serialNumber": OVEN, "messageType": "stateReport", "version": oven.version, "data": {"reported": shadow}}


oven.version = 100

IDLE_HEATER = {"state": 0, "temp_sp": 0, "temp_sp_f": 0, "temp_sp_m": 0, "cur_temp": 21}
# The air fry cook in issue #1: 400 °F, its sensor held at 191 °C, ten minutes on the timer.
AIR_FRY = {"appliance": {"mode": 8, "frozen": 0}, "motor": 2,
           "heater": {"state": 2, "temp_sp": 205, "temp_sp_f": 400, "temp_sp_m": 191, "cur_temp": 188}}


def timer(left: int, total: int = 600, running: bool = True) -> list:
    """A running timer reports its length and when it started; a paused one, the time left."""
    return [{"id": 0, "timestamp": int(NOW.timestamp()) - (total - left), "now": total if running else left,
             "state": 1 if running else 2, "down_from_n": total, "usage": 6}, None]


# Keeping warm after a 350 °F bake with Keep warm on (issue #1, 0.08): an active cook in the keep
# warm mode, with a fresh hour-long timer at 160 °F.
KEEP_WARM = {"appliance": {"mode": 19, "frozen": 0}, "currentInstruction": 17,
             "heater": {"state": 2, "temp_sp": 70, "temp_sp_f": 160, "temp_sp_m": 65, "cur_temp": 160}}

SCENARIOS: dict[str, tuple] = {
    "joule-idle": ("metric", JOULE, [lambda: csj("IDLE", 0, setPoint=None, cookId=None, bathTemp=21.2)]),
    "joule-preheating": ("metric", JOULE, [lambda: csj("ACTIVE", 1, bathTemp=38.4, cookTime=5400)]),
    "joule-ready": ("metric", JOULE, [lambda: csj("ACTIVE", 2, bathTemp=56.0, cookTime=5400)]),
    "joule-cooking": ("metric", JOULE, [lambda: csj("ACTIVE", 3, bathTemp=55.8, cookTime=5400, timeRemaining=4320)]),
    "joule-done": ("metric", JOULE, [lambda: csj("ACTIVE", 4, bathTemp=56.1, cookTime=5400)]),
    "joule-low-water": ("metric", JOULE, [lambda: csj("ACTIVE", 5, errorState=1, eventReason=3, bathTemp=50.2)]),
    "joule-cooking-us": ("us_customary", JOULE, [
        lambda: csj("ACTIVE", 3, bathTemp=55.8, cookTime=5400, timeRemaining=4320),
    ]),
    "oven-idle": ("us_customary", OVEN, [lambda: oven("idle", heater=IDLE_HEATER, motor=0)]),
    "oven-press-start": ("us_customary", OVEN, [
        lambda: oven("physicalButtonPress", heater=IDLE_HEATER, motor=0, currentStepState="waiting"),
    ]),
    "oven-preheating": ("us_customary", OVEN, [
        lambda: oven(heater={"state": 1, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 104}),
    ]),
    "oven-ready": ("us_customary", OVEN, [
        lambda: oven("virtualButtonPress", currentStepState="done",
                     heater={"state": 2, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 158}),
    ]),
    "oven-cooking": ("us_customary", OVEN, [lambda: oven(**AIR_FRY, timers=timer(468))]),
    "oven-cooking-metric": ("metric", OVEN, [lambda: oven(**AIR_FRY, cfg={"temp_unit": 0, "vol": 11}, timers=timer(468))]),
    "oven-door-open": ("us_customary", OVEN, [lambda: oven(**AIR_FRY, door=0, timers=timer(402, running=False))]),
    "oven-keeping-warm": ("us_customary", OVEN, [
        lambda: oven(timers=timer(10, total=300)),
        lambda: oven(**KEEP_WARM, timers=timer(3598, total=3600)),
    ], [("switch", "turn_on", "switch.kitchen_oven_keep_warm")]),
    "oven-finished": ("us_customary", OVEN, [
        lambda: oven("virtualButtonPress", currentStepState="done",
                     heater={"state": 0, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 160}),
    ]),
}

PLACEHOLDERS = {"entry": "entry-1", JOULE: "device-joule", OVEN: "device-oven"}


def _fixture(hass: HomeAssistant, entry: MockConfigEntry, serial: str) -> dict:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, serial)})
    message = panel_message(hass, [])
    [appliance] = [a for a in message["appliances"] if a["device_id"] == device.id]
    appliance = {**appliance, "device_id": PLACEHOLDERS[serial], "entry_id": PLACEHOLDERS["entry"]}
    states = {}
    for domains in appliance["entities"].values():
        for entity_id in domains.values():
            state = hass.states.get(entity_id)
            states[entity_id] = {
                "entity_id": entity_id,
                "state": state.state,
                "attributes": dict(state.attributes),
                "last_changed": state.last_changed.isoformat(),
                "last_updated": state.last_updated.isoformat(),
            }
    area = ar.async_get(hass).async_get_area(device.area_id) if device.area_id else None
    return json.loads(
        json.dumps(
            {
                "now": NOW.isoformat(),
                "unit_system": "us_customary" if hass.config.units is US_CUSTOMARY_SYSTEM else "metric",
                "appliance": appliance,
                "device": {
                    "id": PLACEHOLDERS[serial],
                    "name": device.name,
                    "name_by_user": None,
                    "area_id": device.area_id,
                    "model": device.model,
                    "model_id": device.model_id,
                    "manufacturer": device.manufacturer,
                    "sw_version": device.sw_version,
                },
                "area": {"area_id": area.id, "name": area.name} if area else None,
                "states": dict(sorted(states.items())),
            },
            cls=ExtendedJSONEncoder,
            sort_keys=False,
        )
    )


@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_panel_fixture(
    hass: HomeAssistant, freezer, client, socket: FakeSocket, name: str
) -> None:
    units, serial, messages, *settings = SCENARIOS[name]
    freezer.move_to(NOW)
    hass.config.units = US_CUSTOMARY_SYSTEM if units == "us_customary" else METRIC_SYSTEM
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1", title="me@example.com",
        data={"email": "me@example.com", "id_token": "x.e30.x", "refresh_token": "r"},
        options={CONF_ALLOW_UNTESTED_CONTROL: True},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    kitchen = ar.async_get(hass).async_get_or_create("Kitchen")
    for each in (JOULE, OVEN):
        device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, each)})
        dr.async_get(hass).async_update_device(device.id, area_id=kitchen.id)
    for domain, service, entity_id in settings[0] if settings else []:
        await call(hass, domain, service, entity_id)
    await push(hass, socket, *(make() for make in messages))
    fixture = _fixture(hass, entry, serial)
    path = FIXTURES / f"{name}.json"
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    assert path.exists(), f"Run with UPDATE_PANEL_FIXTURES=1 to write {path.name}"
    assert json.loads(path.read_text(encoding="utf-8")) == fixture, (
        f"{path.name} is out of date: run with UPDATE_PANEL_FIXTURES=1 and check the diff"
    )
    await hass.config_entries.async_unload(entry.entry_id)


async def test_shared_fixture(hass: HomeAssistant) -> None:
    """The oven's modes and the built-in presets, as every message carries them."""
    message = panel_message(hass, [])
    shared = {"oven_modes": message["oven_modes"], "presets": message["presets"]}
    path = FIXTURES / "shared.json"
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(shared, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(json.dumps(shared))
