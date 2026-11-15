"""What the house's walkthrough of 0.1.4 found: presets in whole degrees, an offline appliance
that still says what it did last, an account that says how it stands, and ids that follow a name."""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bruh_cooking.const import DOMAIN
from custom_components.bruh_cooking.entity_ids import async_check_entity_ids, issue_id
from custom_components.bruh_cooking.presets import BUILTIN_PRESETS, describe_preset
from custom_components.bruh_cooking.repairs import async_create_fix_flow

from .common import APPLIANCES, JOULE, OVEN_IDLE, FakeSocket, csj, flush, push
from .test_services import ask


async def test_presets_read_in_whole_degrees_with_a_note(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    answer = await ask(hass, "get_presets")
    presets = {p["id"]: p for p in answer["presets"]}
    assert presets["steak_rare"]["temperature"] == 126.0
    assert presets["steak_medium_rare"]["temperature"] == 133.0
    assert presets["steak_well_done"]["temperature"] == 158.0
    assert presets["frozen_fries"]["temperature"] == 400.0
    for preset in presets.values():
        if preset["temperature"] is not None:
            assert preset["temperature"] == int(preset["temperature"]), preset["id"]
        assert preset["temperature_unit"] == "°F"
    assert all(presets[p.id]["note"] for p in BUILTIN_PRESETS if p.id in presets)
    assert "safe to eat raw" in presets["salmon"]["note"]
    assert all(describe_preset(p) for p in BUILTIN_PRESETS)


async def test_an_offline_cooker_keeps_its_last_cook_and_a_problem_reading(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket
) -> None:
    await push(hass, socket, csj("ACTIVE", 3, timeRemaining=240, bathTemp=55.1))
    await ask(hass, "stop", appliance="countertop")
    await push(hass, socket, csj("OFFLINE", 0))
    status = hass.states.get("sensor.countertop_status")
    assert status.state == "offline"
    cook = status.attributes["last_cook"]
    assert cook["started_at"] and cook["target_temperature_c"] == 56.0 and "preset" in cook
    assert "finish_at" in cook
    assert status.attributes["offline_reason"] and status.attributes["last_contact"]
    assert hass.states.get("binary_sensor.countertop_problem").state == "off"


async def test_the_last_cook_survives_a_restart(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket
) -> None:
    await push(hass, socket, csj("ACTIVE", 3, timeRemaining=240, bathTemp=55.1))
    coordinator = entry.runtime_data
    saved = coordinator._remembered[JOULE]["last_cook"]
    assert saved["target_temperature_c"] == 56.0
    coordinator.appliances.clear()
    coordinator._restore(appliance := type("A", (), {"serial": JOULE, "last_contact": None, "last_cook": None})())
    assert appliance.last_cook == saved and appliance.last_contact is not None


async def test_the_account_says_how_it_stands(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket
) -> None:
    await push(hass, socket, OVEN_IDLE, csj("ACTIVE", 3, bathTemp=55.1))
    account = (await ask(hass, "get_status"))["accounts"][0]
    assert account["connection"] == "connected" and account["appliances_found"] == 2
    assert account["last_poll"]
    assert [item["name"] for item in account["not_driven"]] == ["Espresso"]
    assert "BES995" in account["not_driven"][0]["reason"]
    # Nothing in it identifies the person.
    assert "me@example.com" not in str(account)
    assert hass.states.get("sensor.countertop_status").attributes["account"] == account


async def test_ids_follow_a_rename_when_the_owner_confirms(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock, socket: FakeSocket
) -> None:
    registry = er.async_get(hass)
    assert registry.async_get("sensor.countertop_status") is not None
    renamed: dict[str, Any] = copy.deepcopy(APPLIANCES)
    renamed["appliances"][0]["name"] = "Supper"
    client.get_appliances.return_value = renamed
    await entry.runtime_data.async_refresh()
    await flush(hass)
    # Nothing was renamed by itself.
    assert registry.async_get("sensor.countertop_status") is not None
    assert hass.states.get("sensor.countertop_status").attributes["friendly_name"].startswith("Supper")
    async_check_entity_ids(hass, entry.entry_id)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id(JOULE))
    assert issue is not None and issue.is_fixable

    flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    form = await flow.async_step_init()
    assert form["type"] == "form"
    done = await flow.async_step_confirm({})
    assert done["type"] == "create_entry"
    assert registry.async_get("sensor.countertop_status") is None
    assert registry.async_get("sensor.supper_status") is not None
    assert registry.async_get("sensor.supper_temperature") is not None
    # The oven, not renamed, kept its ids.
    assert registry.async_get("sensor.kitchen_oven_status") is not None
