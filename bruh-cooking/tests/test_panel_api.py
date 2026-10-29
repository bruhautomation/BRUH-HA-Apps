"""The sidebar panel's websocket API: the subscription and the preset commands.

The payload is `PanelMessage` in frontend/src/types.ts.
"""

from __future__ import annotations

from datetime import timedelta
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.bruh_cooking import panel_api
from custom_components.bruh_cooking.const import (
    CONF_ALLOW_UNTESTED_CONTROL,
    CONF_SHOW_SIDEBAR_PANEL,
    DOMAIN,
)
from custom_components.bruh_cooking.presets import BUILTIN_PRESETS, MAX_CUSTOM_PRESETS

from .common import JOULE, OVEN, OVEN_IDLE, FakeSocket, csj, flush, make_jwt, push, real_oven

TURBO = "T600123"


async def subscribe(client) -> dict:
    """Subscribe, and return the PanelMessage sent at once."""
    await client.send_json_auto_id({"type": f"{DOMAIN}/panel/subscribe"})
    result = await client.receive_json()
    assert result["success"], result
    event = await client.receive_json()
    assert (event["id"], event["type"]) == (result["id"], "event")
    return event["event"]


async def next_message(hass: HomeAssistant, client) -> dict:
    """The next PanelMessage, sent once a burst of changes is over."""
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    event = await client.receive_json()
    assert event["type"] == "event", event
    return event["event"]


async def assert_nothing_sent(hass: HomeAssistant, client) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
    await client.send_json_auto_id({"type": "ping"})
    assert (await client.receive_json())["type"] == "pong"


async def command(client, kind: str, **data: Any) -> dict:
    await client.send_json_auto_id({"type": f"{DOMAIN}/panel/{kind}", **data})
    return await client.receive_json()


def by_model(message: dict) -> dict[str, dict]:
    return {appliance["model"]: appliance for appliance in message["appliances"]}


def device_id(hass: HomeAssistant, serial: str) -> str:
    return dr.async_get(hass).async_get_device(identifiers={(DOMAIN, serial)}).id


def registered_entities(hass: HomeAssistant, entry: MockConfigEntry, serial: str) -> dict:
    entities: dict[str, dict[str, str]] = {}
    for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if not entity.disabled and entity.unique_id.startswith(f"{serial}_"):
            key = entity.unique_id.removeprefix(f"{serial}_")
            entities.setdefault(key, {})[entity.domain] = entity.entity_id
    return entities


async def test_the_snapshot_describes_each_appliance(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client
) -> None:
    message = await subscribe(await hass_ws_client(hass))

    joule, oven = by_model(message)["CSJ100"], by_model(message)["BOV950"]
    assert joule == {
        "device_id": device_id(hass, JOULE),
        "entry_id": entry.entry_id,
        "name": "Countertop",
        "model": "CSJ100",
        "product": "Joule Sous Vide",
        "kind": "sous_vide",
        "finish": "white_polished",
        # No state from it yet.
        "available": False,
        "tested": True,
        "control_allowed": True,
        "can_edit_cook": True,
        "sensor_target_c": None,
        "limits": {"min_temp_c": 20.0, "max_temp_c": 98.0, "max_cook_s": 345600},
        "entities": registered_entities(hass, entry, JOULE),
    }
    assert joule["entities"]["cook"] == {"switch": "switch.countertop_cook"}
    assert joule["entities"]["preheat"] == {"sensor": "sensor.countertop_preheat"}
    assert "frozen" not in joule["entities"]
    assert oven["kind"] == "oven"
    assert oven["finish"] == "brushed_stainless"
    # Tested, but a running oven cook can't be changed.
    assert (oven["tested"], oven["control_allowed"], oven["can_edit_cook"]) == (True, True, False)
    assert oven["entities"]["frozen"] == {"switch": "switch.kitchen_oven_frozen_food"}
    assert oven["entities"]["door"] == {"binary_sensor": "binary_sensor.kitchen_oven_door"}

    assert [mode["id"] for mode in message["oven_modes"]][:3] == ["bake", "air_fry", "roast"]
    assert {"toast", "bagel", "keep_warm", "crispy_reheat"} <= {m["id"] for m in message["oven_modes"]}
    assert [preset["id"] for preset in message["presets"]] == [p.id for p in BUILTIN_PRESETS]
    # Plain JSON, and the serial numbers stay in the backend.
    text = json.dumps(message)
    assert json.loads(text) == message
    assert JOULE not in text and OVEN not in text


async def test_a_joule_turbo_is_described(
    hass: HomeAssistant, client: MagicMock, socket: FakeSocket, hass_ws_client
) -> None:
    client.get_appliances.return_value = {
        "appliances": [{"model": "BSV600", "serialNumber": TURBO, "name": "Turbo", "itemNumber": "BSV600PSS"}]
    }
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1",
        data={"email": "me@example.com", "id_token": make_jwt(), "refresh_token": "r"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)

    [turbo] = (await subscribe(await hass_ws_client(hass)))["appliances"]
    assert (turbo["kind"], turbo["finish"], turbo["product"]) == (
        "sous_vide", "white_polished", "Joule Turbo Sous Vide"
    )
    assert turbo["limits"]["max_temp_c"] == 92.0
    assert (turbo["tested"], turbo["control_allowed"]) == (False, False)


async def test_live_changes_are_sent_once_a_burst_is_over(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await subscribe(client)
    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None), OVEN_IDLE)
    appliances = by_model(await next_message(hass, client))
    assert appliances["CSJ100"]["available"] is True
    assert appliances["BOV950"]["available"] is True

    # The oven's sensor target, while it cooks.
    await push(hass, socket, real_oven(11))
    assert by_model(await next_message(hass, client))["BOV950"]["sensor_target_c"] == 161
    # A temperature change alone changes nothing the panel is sent.
    await push(hass, socket, real_oven(
        12, heater={"state": 2, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 162}
    ))
    await assert_nothing_sent(hass, client)


async def test_disabled_entities_are_left_out(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await subscribe(client)
    er.async_get(hass).async_update_entity(
        "sensor.countertop_preheat", disabled_by=er.RegistryEntryDisabler.USER
    )
    joule = by_model(await next_message(hass, client))["CSJ100"]
    assert "preheat" not in joule["entities"]


async def test_options_are_followed_without_a_reload(
    hass: HomeAssistant, client: MagicMock, hass_ws_client
) -> None:
    # The Joule Turbo is still untested, so the option decides whether it can be controlled.
    client.get_appliances.return_value = {
        "appliances": [{"model": "BSV600", "serialNumber": TURBO, "name": "Turbo", "itemNumber": "BSV600PSS"}]
    }
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1",
        data={"email": "me@example.com", "id_token": make_jwt(), "refresh_token": "r"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    ws = await hass_ws_client(hass)
    assert by_model(await subscribe(ws))["BSV600"]["control_allowed"] is False
    hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_UNTESTED_CONTROL: True})
    assert by_model(await next_message(hass, ws))["BSV600"]["control_allowed"] is True

    hass.config_entries.async_update_entry(
        entry, options={CONF_ALLOW_UNTESTED_CONTROL: True, CONF_SHOW_SIDEBAR_PANEL: False}
    )
    assert (await next_message(hass, ws))["appliances"] == []
    assert entry.state is ConfigEntryState.LOADED


async def test_a_reload_keeps_the_appliances_in_place(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await subscribe(client)
    await push(hass, socket, OVEN_IDLE)
    before = by_model(await next_message(hass, client))["BOV950"]
    assert before["available"] is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    during = by_model(await next_message(hass, client))
    assert during["BOV950"] == {**before, "available": False}

    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    await push(hass, socket, OVEN_IDLE | {"version": 20})
    assert by_model(await next_message(hass, client))["BOV950"] == before

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert (await next_message(hass, client))["appliances"] == []


async def test_presets_are_saved_renamed_updated_and_deleted(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, hass_ws_client, hass_storage
) -> None:
    client = await hass_ws_client(hass)
    await subscribe(client)
    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
    await next_message(hass, client)
    joule = device_id(hass, JOULE)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.countertop_target_temperature", "value": 57.5},
        blocking=True,
    )
    saved = await command(client, "save_preset", device_id=joule, name="  Sunday   roast ")
    assert saved["success"], saved
    preset = saved["result"]["preset"]
    assert preset == {
        "id": preset["id"], "kind": "sous_vide", "builtin": False, "name": "Sunday roast",
        "note": None, "settings": {"temperature_c": 57.5, "duration_s": 0},
    }
    message = await next_message(hass, client)
    assert message["presets"][-1] == preset
    stored = hass_storage[panel_api.STORAGE_KEY]["data"]["presets"]
    assert stored == [{"id": preset["id"], "kind": "sous_vide", "name": "Sunday roast",
                       "settings": {"temperature_c": 57.5, "duration_s": 0}}]

    renamed = await command(client, "save_preset", preset_id=preset["id"], name="Roast")
    assert renamed["result"]["preset"]["name"] == "Roast"
    assert renamed["result"]["preset"]["settings"] == preset["settings"]
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.countertop_cook_time", "value": 90}, blocking=True
    )
    updated = await command(client, "save_preset", preset_id=preset["id"], device_id=joule)
    assert updated["result"]["preset"]["name"] == "Roast"
    assert updated["result"]["preset"]["settings"]["duration_s"] == 5400
    # An oven's settings don't fit a sous vide preset.
    wrong = await command(client, "save_preset", preset_id=preset["id"], device_id=device_id(hass, OVEN))
    assert wrong["error"]["code"] == "invalid_preset"
    # Built-in presets can't be changed.
    builtin = await command(client, "save_preset", preset_id="steak_rare", name="Mine")
    assert builtin["error"]["code"] == "unknown_preset"

    deleted = await command(client, "delete_preset", preset_id=preset["id"])
    assert deleted["success"]
    assert hass_storage[panel_api.STORAGE_KEY]["data"]["presets"] == []
    again = await command(client, "delete_preset", preset_id=preset["id"])
    assert again["error"]["code"] == "unknown_preset"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({"name": ""}, "invalid_preset"),
        ({"name": "x" * 41}, "invalid_preset"),
        ({}, "invalid_preset"),
        ({"name": "Mine", "device_id": "nope"}, "unknown_appliance"),
    ],
)
async def test_invalid_presets_are_refused(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client, data: dict, code: str
) -> None:
    client = await hass_ws_client(hass)
    data = {"device_id": device_id(hass, JOULE), **data}
    response = await command(client, "save_preset", **data)
    assert response["error"]["code"] == code


async def test_there_can_be_fifty_custom_presets(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    joule = device_id(hass, JOULE)
    for index in range(MAX_CUSTOM_PRESETS):
        assert (await command(client, "save_preset", device_id=joule, name=f"P{index}"))["success"]
    response = await command(client, "save_preset", device_id=joule, name="One more")
    assert response["error"]["code"] == "too_many_presets"


async def test_only_admins_change_presets(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client, hass_read_only_access_token
) -> None:
    client = await hass_ws_client(hass, hass_read_only_access_token)
    joule = device_id(hass, JOULE)
    response = await command(client, "save_preset", device_id=joule, name="Mine")
    assert response["error"]["code"] == "unauthorized"
    response = await command(client, "delete_preset", preset_id="anything")
    assert response["error"]["code"] == "unauthorized"
    # Everyone can apply one.
    response = await command(client, "apply_preset", device_id=joule, preset_id="steak_medium_rare")
    assert response["success"], response


async def test_a_sous_vide_preset_fills_in_the_settings(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock, hass_ws_client
) -> None:
    ws = await hass_ws_client(hass)
    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
    response = await command(ws, "apply_preset", device_id=device_id(hass, JOULE), preset_id="chicken_breast")
    assert response["success"], response
    assert hass.states.get("number.countertop_target_temperature").state == "63.0"
    assert hass.states.get("number.countertop_cook_time").state == "120"
    # Nothing starts.
    client.load_manual_recipe.assert_not_awaited()

    # Not while a cook runs.
    await push(hass, socket, csj("ACTIVE", 3, timeRemaining=240))
    response = await command(ws, "apply_preset", device_id=device_id(hass, JOULE), preset_id="steak_rare")
    assert response["error"]["code"] == "cook_running"
    # An oven preset doesn't fit a Joule.
    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
    response = await command(ws, "apply_preset", device_id=device_id(hass, JOULE), preset_id="cake")
    assert response["error"]["code"] == "invalid_preset"
    response = await command(ws, "apply_preset", device_id=device_id(hass, JOULE), preset_id="nope")
    assert response["error"]["code"] == "unknown_preset"


async def test_an_oven_preset_uses_the_unit_home_assistant_shows(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, hass_ws_client
) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    ws = await hass_ws_client(hass)
    await push(hass, socket, OVEN_IDLE)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.kitchen_oven_keep_warm"}, blocking=True
    )
    oven = device_id(hass, OVEN)
    assert (await command(ws, "apply_preset", device_id=oven, preset_id="frozen_pizza"))["success"]
    assert hass.states.get("select.kitchen_oven_mode").state == "pizza"
    assert float(hass.states.get("number.kitchen_oven_target_temperature").state) == 400
    assert hass.states.get("number.kitchen_oven_cook_time").state == "16"
    assert hass.states.get("switch.kitchen_oven_frozen_food").state == "on"
    # As choosing a mode does, Keep warm stays as it was.
    assert hass.states.get("switch.kitchen_oven_keep_warm").state == "on"

    assert (await command(ws, "apply_preset", device_id=oven, preset_id="salmon_fillets"))["success"]
    assert hass.states.get("select.kitchen_oven_mode").state == "broil"
    assert hass.states.get("select.kitchen_oven_level").state == "high"
    assert hass.states.get("switch.kitchen_oven_frozen_food").state == "unavailable"


async def test_presets_go_with_the_last_entry(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client, hass_storage
) -> None:
    client = await hass_ws_client(hass)
    await command(client, "save_preset", device_id=device_id(hass, JOULE), name="Mine")
    assert panel_api.STORAGE_KEY in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert panel_api.STORAGE_KEY not in hass_storage


async def test_saved_presets_are_loaded_and_bad_ones_skipped(
    hass: HomeAssistant, client: MagicMock, hass_storage, hass_ws_client
) -> None:
    hass_storage[panel_api.STORAGE_KEY] = {
        "version": 1,
        "key": panel_api.STORAGE_KEY,
        "data": {"presets": [
            {"id": "a", "kind": "oven", "name": "Toast it",
             "settings": {"mode": "bake", "temperature_c": 180, "duration_s": 600}},
            {"id": "b", "kind": "oven", "name": "Too hot",
             "settings": {"mode": "bake", "temperature_c": 900, "duration_s": 600}},
            {"id": "c", "kind": "sous_vide", "name": ""},
            "junk",
        ]},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="Salesforce|1",
        data={"email": "me@example.com", "id_token": make_jwt(), "refresh_token": "r"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    message = await subscribe(await hass_ws_client(hass))
    custom = [preset for preset in message["presets"] if not preset["builtin"]]
    assert [preset["name"] for preset in custom] == ["Toast it"]
