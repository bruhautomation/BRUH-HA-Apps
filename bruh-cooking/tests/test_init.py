"""Integration setup, live updates and commands, with the cloud client mocked."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import json
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.json import ExtendedJSONEncoder
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bruh_cooking import async_remove_config_entry_device
from custom_components.bruh_cooking.api import BrevilleAuthError
from custom_components.bruh_cooking.appliance import OVEN_MODES
from custom_components.bruh_cooking.const import CONF_ALLOW_UNTESTED_CONTROL, DOMAIN
from custom_components.bruh_cooking.diagnostics import (
    REDACTED,
    async_get_config_entry_diagnostics,
)

from .common import (
    APPLIANCES,
    JOULE,
    OVEN,
    OVEN_IDLE,
    PROFILE,
    FakeSocket,
    call,
    csj,
    flush,
    make_jwt,
    push,
    real_oven,
)

async def test_setup_creates_entities_for_supported_models(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket
) -> None:
    assert entry.state is ConfigEntryState.LOADED
    assert socket.subscribed == [(JOULE, "CSJ100"), (OVEN, "BOV950")]
    registry = er.async_get(hass)
    joule = {e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id) if e.unique_id.startswith(JOULE)}
    assert joule == {
        "sensor.countertop_status", "sensor.countertop_temperature", "sensor.countertop_preheat",
        "sensor.countertop_time_remaining",
        "sensor.countertop_cook_end", "sensor.countertop_error", "binary_sensor.countertop_cooking",
        "binary_sensor.countertop_problem", "number.countertop_target_temperature",
        "number.countertop_cook_time", "switch.countertop_cook",
        "switch.countertop_start_timer_automatically", "button.countertop_continue",
    }
    for entity_id in ("select.kitchen_oven_mode", "select.kitchen_oven_convection",
                      "binary_sensor.kitchen_oven_door", "sensor.kitchen_oven_active_mode",
                      "switch.kitchen_oven_keep_warm", "switch.kitchen_oven_frozen_food"):
        assert registry.async_get(entity_id), entity_id
    # Connected, but no state from the Joule yet.
    assert hass.states.get("sensor.countertop_status").state == "offline"
    assert hass.states.get("switch.countertop_cook").state == STATE_UNAVAILABLE

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_sage_account(
    hass: HomeAssistant, client_class: MagicMock, socket: FakeSocket
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1",
        data={"email": "me@example.com", "brand": "sage", "id_token": make_jwt(), "refresh_token": "r"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    assert client_class.call_args.kwargs["endpoints"].app_channel == "sageJoule"
    devices = dr.async_get(hass)
    assert devices.async_get_device(identifiers={(DOMAIN, OVEN)}).manufacturer == "Sage"
    assert devices.async_get_device(identifiers={(DOMAIN, JOULE)}).manufacturer == "ChefSteps"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_appliances_added_and_removed_later(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    coordinator = entry.runtime_data
    turbo = {"model": "BSV600", "serialNumber": "T600123", "name": "Turbo", "itemNumber": "BSV600BSS"}
    client.get_appliances.return_value = {
        "appliances": [APPLIANCES["appliances"][0], turbo], "ownedModels": [],
    }
    await coordinator.async_refresh()
    await flush(hass)

    # The new appliance appears without a reload.
    assert hass.states.get("sensor.turbo_status") is not None
    assert hass.states.get("switch.turbo_cook") is not None
    assert ("T600123", "BSV600") in socket.subscribed

    # The oven has left the account: unavailable, and its device can be deleted.
    assert hass.states.get("sensor.kitchen_oven_status").state == STATE_UNAVAILABLE
    devices = dr.async_get(hass)
    joule = devices.async_get_device(identifiers={(DOMAIN, JOULE)})
    oven = devices.async_get_device(identifiers={(DOMAIN, OVEN)})
    assert await async_remove_config_entry_device(hass, entry, joule) is False
    assert await async_remove_config_entry_device(hass, entry, oven) is True
    assert OVEN not in coordinator.appliances and socket.unsubscribed == [OVEN]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_joule_cook_lifecycle(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None, bathTemp=21.2))
    assert hass.states.get("sensor.countertop_status").state == "idle"
    assert hass.states.get("sensor.countertop_temperature").state == "21.2"
    assert hass.states.get("switch.countertop_cook").state == STATE_OFF
    assert hass.states.get("button.countertop_continue").state == STATE_UNAVAILABLE

    # Idle: settings only, no cloud call.
    await call(hass, "number", "set_value", "number.countertop_target_temperature", value=55)
    await call(hass, "number", "set_value", "number.countertop_cook_time", value=45)
    client.csj_update_program.assert_not_awaited()

    await call(hass, "switch", "turn_on", "switch.countertop_cook")
    serial, model, firmware, steps = client.load_manual_recipe.await_args.args
    assert (serial, model, firmware) == (JOULE, "CSJ100", {"commFirmware": "52", "ctrlFirmware": "123"})
    assert steps[0]["holdingTemperature"] == 55.0
    assert steps[0]["phases"][0]["seconds"] == 2700
    assert client.load_manual_recipe.await_args.kwargs["locale"] == "en-US"

    await push(hass, socket, csj("ACTIVE", 2))
    assert hass.states.get("sensor.countertop_status").state == "ready"
    assert hass.states.get("switch.countertop_cook").state == STATE_ON
    await call(hass, "button", "press", "button.countertop_continue")
    client.finish_wait.assert_awaited_once_with(JOULE, "CSJ100", {})

    await push(hass, socket, csj("ACTIVE", 3, timeRemaining=240))
    assert hass.states.get("sensor.countertop_status").state == "cooking"
    assert float(hass.states.get("sensor.countertop_time_remaining").state) == 4
    assert hass.states.get("number.countertop_cook_time").state == "4"
    assert hass.states.get("sensor.countertop_cook_end").state != "unknown"

    # Running: changing the temperature edits the cook, keeping its timer.
    await call(hass, "number", "set_value", "number.countertop_target_temperature", value=57)
    serial, program = client.csj_update_program.await_args.args
    assert program["setPoint"] == 57.0 and program["cookTime"] == 240
    assert program["programMetadata"] == {"cookId": "cook1", "guideId": "manual_x"}

    await call(hass, "switch", "turn_off", "switch.countertop_cook")
    assert client.stop_recipe.await_args.args == (JOULE, "CSJ100")
    assert client.stop_recipe.await_args.kwargs["firmware"] == {"commFirmware": "52", "ctrlFirmware": "123"}

    await push(hass, socket, csj("ACTIVE", 5, errorState=2, eventReason=4))
    assert hass.states.get("binary_sensor.countertop_problem").state == STATE_ON
    assert hass.states.get("sensor.countertop_error").state == "tipped_over"

    await push(hass, socket, csj("OFFLINE", 0))
    assert hass.states.get("sensor.countertop_status").state == "offline"
    assert hass.states.get("number.countertop_target_temperature").state == STATE_UNAVAILABLE
    await hass.config_entries.async_unload(entry.entry_id)


OVEN_ROASTING = {
    "serialNumber": OVEN, "messageType": "changeReport", "version": 11,
    "data": {"reported": {"state": "active", "cookUUID": "c-9", "currentStep": 1,
                          "appliance": {"mode": 4},
                          "heaters": [{"cur_temp": 150, "temp_sp": 190, "state": 2}]}},
}


TURBO = "T600123"
TURBO_IDLE = {
    "serialNumber": TURBO, "messageType": "stateReport", "version": 10,
    "data": {"reported": {"state": "idle", "model": "BSV600", "errors": [],
                          "heater": {"state": 0, "cur_temp": 21, "temp_sp": 0}}},
}
TURBO_COOKING = {
    "serialNumber": TURBO, "messageType": "changeReport", "version": 11,
    "data": {"reported": {"state": "active", "cookUUID": "c-3", "currentStep": 1,
                          "heater": {"state": 2, "cur_temp": 56.5, "temp_sp": 57}}},
}


async def test_untested_models_are_monitor_only(
    hass: HomeAssistant, socket: FakeSocket, client: MagicMock
) -> None:
    client.get_appliances.return_value = {
        "appliances": [{"model": "BSV600", "serialNumber": TURBO, "name": "Turbo", "itemNumber": "BSV600PSS"}]
    }
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1", title="me@example.com",
        data={"email": "me@example.com", "id_token": make_jwt(**PROFILE), "refresh_token": "refresh"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    await push(hass, socket, TURBO_IDLE)
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "switch", "turn_on", "switch.turbo_cook")
    assert err.value.translation_key == "untested_control"
    assert str(err.value).startswith("Control of the Joule Turbo Sous Vide hasn't been tested")
    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "start_cook", "switch.turbo_cook", temperature=60)
    client.load_manual_recipe.assert_not_awaited()

    # A cook started on the appliance itself can be watched and stopped, not changed.
    await push(hass, socket, TURBO_COOKING)
    assert hass.states.get("switch.turbo_cook").state == STATE_ON
    with pytest.raises(ServiceValidationError):
        await call(hass, "number", "set_value", "number.turbo_target_temperature", value=60)
    client.update_cook.assert_not_awaited()
    await call(hass, "switch", "turn_off", "switch.turbo_cook")
    client.stop_recipe.assert_awaited_once()

    # The option applies straight away, without a reload.
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_UNTESTED_CONTROL: True})
    await call(hass, "switch", "turn_on", "switch.turbo_cook")
    client.load_manual_recipe.assert_awaited_once()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_the_oven_is_tested(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    """Tried on a real oven (issue #1), the Joule Oven can be controlled without the option."""
    await push(hass, socket, OVEN_IDLE)
    await call(hass, "switch", "turn_on", "switch.kitchen_oven_cook")
    client.load_manual_recipe.assert_awaited_once()

    # A running oven cook still can't be changed, as in the app.
    await push(hass, socket, OVEN_ROASTING)
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, "number", "set_value", "number.kitchen_oven_target_temperature", value=200)
    assert err.value.translation_key == "stop_cook_first"
    client.update_cook.assert_not_awaited()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_oven_preheat_counts_its_time_limit(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, freezer
) -> None:
    """Seen from its start, an oven's preheat counts the 5 minutes it allows itself."""
    cold = {"state": 1, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 21}
    await push(hass, socket, real_oven(1, state="physicalButtonPress"))
    await push(hass, socket, real_oven(2, heater=cold))
    assert hass.states.get("sensor.kitchen_oven_preheat").state == "14"
    freezer.tick(timedelta(seconds=150))
    await push(hass, socket, real_oven(3, heater={**cold, "cur_temp": 60}))
    # Halfway through the 5 minutes, ahead of its 41% by temperature.
    assert hass.states.get("sensor.kitchen_oven_preheat").state == "50"
    await push(hass, socket, real_oven(
        4, state="virtualButtonPress", currentStepState="done", heater={**cold, "state": 2, "cur_temp": 95},
    ))
    assert hass.states.get("sensor.kitchen_oven_status").state == "ready"
    assert hass.states.get("sensor.kitchen_oven_preheat").state == "unknown"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_oven_settings_and_start_service(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_UNTESTED_CONTROL: True})
    await push(hass, socket, OVEN_IDLE)
    assert hass.states.get("select.kitchen_oven_mode").state == "bake"
    assert hass.states.get("binary_sensor.kitchen_oven_door").state == STATE_OFF
    assert hass.states.get("select.kitchen_oven_level").state == STATE_UNAVAILABLE

    await call(hass, "select", "select_option", "select.kitchen_oven_mode", option="air_fry")
    temp = hass.states.get("number.kitchen_oven_target_temperature")
    assert (temp.state, temp.attributes["min"], temp.attributes["max"]) == ("205.0", 150, 250)
    assert hass.states.get("select.kitchen_oven_convection").attributes["options"] == ["super"]

    await call(hass, "select", "select_option", "select.kitchen_oven_mode", option="broil")
    assert hass.states.get("number.kitchen_oven_target_temperature").state == STATE_UNAVAILABLE
    await call(hass, "select", "select_option", "select.kitchen_oven_level", option="medium")

    await call(
        hass, DOMAIN, "start_cook", "switch.kitchen_oven_cook",
        mode="roast", temperature=190, duration=timedelta(minutes=50),
    )
    serial, model, firmware, steps = client.load_manual_recipe.await_args.args
    assert (serial, model) == (OVEN, "BOV950")
    assert firmware == {"commFirmware": "1.0", "ctrlFirmware": "2.0"}
    # The timer starts by itself by default, so preheating is part of the cook step.
    assert [s["stepType"] for s in steps] == ["default", "aBitMore", "keepWarm"]
    preheat, cook = steps[0]["phases"]
    assert preheat["seconds"] == 0
    assert (cook["mode"], cook["temperatureCelsius"], cook["seconds"]) == ("roast", 190, 3000)
    # The service doesn't change the entities' own settings.
    assert hass.states.get("select.kitchen_oven_mode").state == "broil"

    with pytest.raises(ServiceValidationError):
        await call(hass, DOMAIN, "start_cook", "switch.kitchen_oven_keep_warm", temperature=200)

    # Cooking: as in the app, nothing about the running cook can change.
    await push(hass, socket, OVEN_ROASTING)
    assert hass.states.get("sensor.kitchen_oven_active_mode").state == "roast"
    with pytest.raises(ServiceValidationError):
        await call(hass, "select", "select_option", "select.kitchen_oven_mode", option="bake")
    for entity_id, value in (("target_temperature", 200), ("cook_time", 20)):
        with pytest.raises(ServiceValidationError) as err:
            await call(hass, "number", "set_value", f"number.kitchen_oven_{entity_id}", value=value)
        assert err.value.translation_key == "stop_cook_first"
    client.update_cook.assert_not_awaited()
    await hass.config_entries.async_unload(entry.entry_id)


async def test_real_oven_cook(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    """The BOV950 sequence from the issue #1 diagnostics, from preheated to finished."""
    await push(hass, socket, real_oven(
        1, state="virtualButtonPress", currentInstruction=6, currentStepState="done",
    ))
    assert hass.states.get("sensor.kitchen_oven_status").state == "ready"
    assert hass.states.get("number.kitchen_oven_cook_time").state == "unknown"
    await call(hass, "button", "press", "button.kitchen_oven_continue")
    # The oven ignores finish-wait; the app goes on to the cook step instead.
    client.finish_wait.assert_not_awaited()
    client.send_step.assert_awaited_once_with(
        OVEN, "BOV950",
        {"commFirmware": "1.10.131", "ctrlFirmware": "1.10.21", "teFirmware": "2.4.0"},
        "manual_x", 1,
    )

    # Its only timer has id 0. The door was opened and closed with 339 s left.
    started = int(dt_util.utcnow().timestamp())
    timer = {"id": 0, "timestamp": started, "now": 339, "state": 1, "down_from_n": 900, "usage": 6}
    await push(hass, socket, real_oven(2, timers=[timer, None]))
    assert hass.states.get("sensor.kitchen_oven_status").state == "cooking"
    assert 5 <= float(hass.states.get("sensor.kitchen_oven_time_remaining").state) <= 6
    # The cook's length, since it can't be changed.
    assert hass.states.get("number.kitchen_oven_cook_time").state == "15"
    assert hass.states.get("binary_sensor.kitchen_oven_cooking").state == STATE_ON

    # Time's up: a report with the run-out timer, then the heater goes off.
    timer["timestamp"] = started - 339
    await push(hass, socket, real_oven(
        3, state="virtualButtonPress", currentInstruction=14, currentStepState="done",
        timers=[timer, None],
    ))
    assert hass.states.get("sensor.kitchen_oven_status").state == "done"
    await push(hass, socket, real_oven(
        4, state="virtualButtonPress", currentInstruction=14, currentStepState="done",
        heater={"state": 0, "temp_sp": 175, "temp_sp_f": 345, "temp_sp_m": 161, "cur_temp": 160},
    ))
    assert hass.states.get("sensor.kitchen_oven_status").state == "done"
    assert hass.states.get("binary_sensor.kitchen_oven_cooking").state == STATE_OFF
    assert hass.states.get("button.kitchen_oven_continue").state == STATE_UNAVAILABLE
    # Not the 345 °F the oven reports once it's off: the next cook's setting.
    target = hass.states.get("number.kitchen_oven_target_temperature")
    assert float(target.state) == OVEN_MODES["bake"].temp[0]
    # The cook stays open until it's turned off.
    assert hass.states.get("switch.kitchen_oven_cook").state == STATE_ON
    await call(hass, "switch", "turn_off", "switch.kitchen_oven_cook")
    client.stop_recipe.assert_awaited_once()

    # Idle, the oven's temperature reading goes stale, so it isn't shown.
    await push(hass, socket, real_oven(
        5, state="idle", recipe=None, cookUUID=None, currentStep=None,
        heater={"state": 0, "temp_sp": 0, "temp_sp_f": 0, "temp_sp_m": 0, "cur_temp": 59},
    ))
    assert hass.states.get("sensor.kitchen_oven_temperature").state == "unknown"
    assert hass.states.get("switch.kitchen_oven_cook").state == STATE_OFF
    await hass.config_entries.async_unload(entry.entry_id)


def panel_cook(version: int, **reported) -> dict:
    """A cook started on the oven's own panel: no recipe or step, only a cook (issue #1, 0.10)."""
    message = real_oven(version, **reported)
    for key in ("recipe", "currentStage", "currentStep", "currentInstruction", "currentStepState"):
        message["data"]["reported"].pop(key)
    return message


async def test_cooks_started_on_the_oven(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    """Followed as they run, with the running cook's settings, and stopped from Home Assistant."""
    now = int(dt_util.utcnow().timestamp())
    no_setpoint = {"state": 2, "temp_sp": 0, "temp_sp_f": 0, "temp_sp_m": 0, "cur_temp": 30}
    # A toast can't be started from Home Assistant, so Mode has nothing to show.
    await push(hass, socket, panel_cook(
        1, cookUUID="toast-1", motor=0, heater=no_setpoint,
        appliance={"mode": 0, "rotate_state": 0, "preset": 3, "cook_segment": 0, "frozen": 0},
        timers=[{"id": 0, "timestamp": now, "now": 263, "state": 1, "down_from_n": 264, "usage": 6}, None],
    ))
    assert hass.states.get("sensor.kitchen_oven_status").state == "cooking"
    assert hass.states.get("sensor.kitchen_oven_active_mode").state == "toast"
    assert hass.states.get("select.kitchen_oven_mode").state == STATE_UNKNOWN
    assert hass.states.get("select.kitchen_oven_level").state == STATE_UNAVAILABLE
    await call(hass, "switch", "turn_off", "switch.kitchen_oven_cook")
    client.stop_recipe.assert_awaited_once()

    # A bottom broil on Medium, with the next cook set to bake: the selects show the broil's.
    await push(hass, socket, panel_cook(
        2, cookUUID="broil-1", motor=0, heater=no_setpoint,
        appliance={"mode": 14, "rotate_state": 0, "preset": 2, "cook_segment": 0, "frozen": 0},
        timers=[{"id": 0, "timestamp": now, "now": 600, "state": 1, "down_from_n": 600, "usage": 6}, None],
    ))
    assert hass.states.get("select.kitchen_oven_mode").state == "bottom_broil"
    level = hass.states.get("select.kitchen_oven_level")
    assert (level.state, level.attributes["options"]) == ("medium", ["low", "medium", "high"])
    convection = hass.states.get("select.kitchen_oven_convection")
    assert (convection.state, convection.attributes["options"]) == ("off", ["off"])
    assert hass.states.get("number.kitchen_oven_cook_time").state == "10"

    # A bake: its timer is there from the start, waiting for preheating to end.
    await push(hass, socket, panel_cook(
        3, cookUUID="bake-1", motor=1,
        heater={"state": 1, "temp_sp": 205, "temp_sp_f": 400, "temp_sp_m": 189, "cur_temp": 51},
        appliance={"mode": 3, "rotate_state": 1, "preset": 3, "cook_segment": 0, "frozen": 0},
        timers=[{"id": 0, "timestamp": now, "now": 960, "state": 0, "down_from_n": 960, "usage": 6}, None],
    ))
    assert hass.states.get("sensor.kitchen_oven_status").state == "preheating"
    assert hass.states.get("sensor.kitchen_oven_preheat").state == "29"
    assert hass.states.get("sensor.kitchen_oven_time_remaining").state == STATE_UNKNOWN
    assert hass.states.get("number.kitchen_oven_cook_time").state == "16"
    target = hass.states.get("number.kitchen_oven_target_temperature")
    assert float(target.state) == pytest.approx(204.4, abs=0.1)  # 400 °F
    # The preset left over from the broil isn't a level for a bake.
    assert hass.states.get("select.kitchen_oven_level").state == STATE_UNAVAILABLE

    # Stopped, it reports the bake once more with the heater off before going idle.
    await call(hass, "switch", "turn_off", "switch.kitchen_oven_cook")
    await push(hass, socket, panel_cook(
        4, cookUUID="bake-1", motor=1,
        heater={"state": 0, "temp_sp": 205, "temp_sp_f": 400, "temp_sp_m": 189, "cur_temp": 48},
        appliance={"mode": 3, "rotate_state": 1, "preset": 3, "cook_segment": 0, "frozen": 0},
        timers=[{"id": 0, "timestamp": now, "now": 960, "state": 0, "down_from_n": 960, "usage": 6}, None],
    ))
    assert hass.states.get("sensor.kitchen_oven_status").state == "preheating"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_cloud_errors_become_ha_errors(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    from custom_components.bruh_cooking.api import BrevilleApiError

    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
    client.load_manual_recipe.side_effect = BrevilleApiError("POST", "u", 500, "oops")
    with pytest.raises(HomeAssistantError):
        await call(hass, "switch", "turn_on", "switch.countertop_cook")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_websocket_auth_failure_starts_reauth(
    hass: HomeAssistant, client: MagicMock, socket: FakeSocket
) -> None:
    socket.connect_error = BrevilleAuthError("expired")
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1",
        data={"email": "me@example.com", "id_token": make_jwt(), "refresh_token": "r"},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_have_no_personal_information(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    await push(hass, socket, csj(
        "ACTIVE", 3, timeRemaining=100, macAddress="A4:CF:12:34:56:78",
        circulatorAddress="0123456789abcdef", customerId="C-123456",
        wifi={"ssid": "Home Network", "wifiMac": "a4cf12345679", "localIp": "192.168.1.20", "rssi": -60},
        note="Set up by Pat Example (pat@example.org) on Countertop, a4:cf:12:34:56:79",
    ))
    # A real BOV950 names itself in its state, here differently from the account's list.
    oven = OVEN_IDLE["data"]["reported"] | {"name": "A950-0099", "serialNumber": "A950-0099"}
    await push(hass, socket, OVEN_IDLE | {"data": {"reported": oven}})
    client.recent_requests = [
        {"method": "POST", "endpoint": "update-cook", "status": 200,
         "body": {"model": "BOV950", "uuid": "c-9", "note": "Kitchen Oven"}},
        {"method": "GET", "endpoint": "appliances",
         "error": "InvalidURL('https://iot-api.breville.com/user/v2/user/Salesforce|0051234/appliances')"},
        {"method": "POST", "endpoint": "finish-wait", "status": 200,
         "body": {"applianceModel": "CSJ100"}, "response": {JOULE: {"owner": "patex"}}},
    ]
    diag = await async_get_config_entry_diagnostics(hass, entry)

    # Nothing personal anywhere in the file, inside other text or keys either.
    downloaded = json.dumps(diag, cls=ExtendedJSONEncoder).casefold()
    for personal in (
        *PROFILE.values(), "Salesforce|0051234", "Salesforce|1", "pat@example.org",
        JOULE, OVEN, "A950-0099", "Countertop", "Kitchen Oven", "A4:CF:12:34:56:78", "a4:cf:12:34:56:79",
        "a4cf12345679", "0123456789abcdef", "Home Network", "192.168.1.20",
    ):
        assert personal.casefold() not in downloaded, personal
    assert diag["entry"]["refresh_token"] == REDACTED
    # What's needed to debug an appliance is kept.
    joule = diag["appliances"][0]
    assert (joule["model"], joule["tested"]) == ("CSJ100", True)
    data = joule["recent_messages"][-1]["message"]["data"]
    assert (data["bathTemp"], data["firmwareVersion"], data["wifi"]["rssi"]) == (55.1, "123", -60)
    assert (data["guideId"], data["cookId"]) == ("manual_x", REDACTED)
    assert diag["recent_requests"][0]["body"]["model"] == "BOV950"
    oven = diag["appliances"][1]
    assert oven["tested"] is True
    assert (oven["reported"]["name"], oven["reported"]["state"]) == (REDACTED, "idle")
    await hass.config_entries.async_unload(entry.entry_id)


async def test_start_cook_service_options(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_UNTESTED_CONTROL: True})
    await push(hass, socket, OVEN_IDLE, csj("IDLE", 0, setPoint=None, cookId=None))

    def cook_phase() -> dict:
        steps = client.load_manual_recipe.await_args.args[3]
        return next(p for s in steps if s["stepType"] == "default" for p in s["phases"] if p.get("seconds"))

    await call(hass, DOMAIN, "start_cook", "switch.kitchen_oven_cook", mode="broil", level="high")
    assert (cook_phase()["mode"], cook_phase()["level"]) == (OVEN_MODES["broil"].cms, 3)
    await call(hass, DOMAIN, "start_cook", "switch.kitchen_oven_cook", mode="air_fry", convection="super")
    assert cook_phase()["convection"] == "super"

    with pytest.raises(ServiceValidationError) as err:
        await call(hass, DOMAIN, "start_cook", "switch.kitchen_oven_cook", mode="bake", level="high")
    assert err.value.translation_key == "level_not_for_mode"
    with pytest.raises(ServiceValidationError) as err:
        await call(hass, DOMAIN, "start_cook", "switch.countertop_cook", mode="bake")
    assert err.value.translation_key == "mode_oven_only"

    await call(hass, DOMAIN, "start_cook", "switch.countertop_cook", temperature=60, auto_start_timer=True)
    assert client.load_manual_recipe.await_args.args[3][0]["defaultAutostart"] is True
    await hass.config_entries.async_unload(entry.entry_id)


async def test_start_timer_automatically_switch(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
    for state, expected in ((STATE_ON, True), (STATE_OFF, False)):
        service = "turn_on" if state == STATE_ON else "turn_off"
        await call(hass, "switch", service, "switch.countertop_start_timer_automatically")
        assert hass.states.get("switch.countertop_start_timer_automatically").state == state
        await call(hass, "switch", "turn_on", "switch.countertop_cook")
        assert client.load_manual_recipe.await_args.args[3][0]["defaultAutostart"] is expected
    await hass.config_entries.async_unload(entry.entry_id)


async def test_frozen_food_switch(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_UNTESTED_CONTROL: True})
    await push(hass, socket, OVEN_IDLE)
    # Bake doesn't offer it.
    assert hass.states.get("switch.kitchen_oven_frozen_food").state == STATE_UNAVAILABLE
    await call(hass, "select", "select_option", "select.kitchen_oven_mode", option="pizza")
    assert hass.states.get("switch.kitchen_oven_frozen_food").state == STATE_ON
    await call(hass, "switch", "turn_off", "switch.kitchen_oven_frozen_food")
    await call(hass, "switch", "turn_on", "switch.kitchen_oven_cook")
    assert client.load_manual_recipe.await_args.args[3][0]["phases"][0]["frozen"] == "off"
    # A mode change resets it to the mode's default.
    await call(hass, "select", "select_option", "select.kitchen_oven_mode", option="cookies")
    assert hass.states.get("switch.kitchen_oven_frozen_food").state == STATE_OFF
    await hass.config_entries.async_unload(entry.entry_id)


async def test_preheat_sensor(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket
) -> None:
    await push(hass, socket, csj("ACTIVE", 1, bathTemp=28))
    preheat = hass.states.get("sensor.countertop_preheat")
    assert (preheat.state, preheat.attributes["unit_of_measurement"]) == ("50", "%")
    await push(hass, socket, csj("ACTIVE", 2))
    assert hass.states.get("sensor.countertop_preheat").state == "unknown"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_websocket_reconnects(
    hass: HomeAssistant, client: MagicMock, socket: FakeSocket
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1",
        data={"email": "me@example.com", "id_token": make_jwt(), "refresh_token": "r"},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.bruh_cooking.coordinator.WS_RECONNECT_MIN", 0.01):
        await hass.config_entries.async_setup(entry.entry_id)
        await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
        assert hass.states.get("sensor.countertop_status").state == "idle"

        await push(hass, socket, None)  # the cloud closes the connection
        for _ in range(20):
            await asyncio.sleep(0.01)
        await flush(hass)
        # Reconnected and subscribed again, with the last state kept.
        assert socket.connected and len(socket.subscribed) == 4
        assert hass.states.get("sensor.countertop_status").state == "idle"
        await hass.config_entries.async_unload(entry.entry_id)


async def test_appliance_list_errors(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    from custom_components.bruh_cooking.api import BrevilleError

    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
    coordinator = entry.runtime_data
    client.get_appliances.side_effect = BrevilleError("down")
    await coordinator.async_refresh()
    await flush(hass)
    # A failed refresh alone doesn't make the appliance unavailable.
    assert not coordinator.last_update_success
    assert hass.states.get("switch.countertop_cook").state == STATE_OFF

    client.get_appliances.side_effect = BrevilleAuthError("expired")
    await coordinator.async_refresh()
    await flush(hass)
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    await hass.config_entries.async_unload(entry.entry_id)
