"""The services brAIn calls: appliances by name, every answer in words, every refusal raised."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bruh_cooking.const import CONF_ALLOW_UNTESTED_CONTROL, DOMAIN

from .common import JOULE, OVEN, OVEN_IDLE, FakeSocket, csj, push


async def ask(hass: HomeAssistant, service: str, **data: Any) -> dict[str, Any]:
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=True)


async def test_status_names_every_appliance(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket
) -> None:
    await push(hass, socket, OVEN_IDLE, csj("ACTIVE", 3, timeRemaining=240, bathTemp=55.1))
    answer = await ask(hass, "get_status")
    by_name = {a["name"]: a for a in answer["appliances"]}
    assert set(by_name) == {"Countertop", "Kitchen Oven"}
    joule = by_name["Countertop"]
    assert (joule["kind"], joule["state"], joule["cooking"]) == ("sous_vide", "cooking", True)
    assert (joule["current_temperature"], joule["target_temperature"]) == (55.1, 56.0)
    assert joule["time_remaining_minutes"] == 4
    assert joule["control_allowed"] is True
    oven = by_name["Kitchen Oven"]
    assert (oven["kind"], oven["state"], oven["mode"]) == ("oven", "idle", "bake")
    assert oven["next_cook"]["mode"] == "bake"
    # One by name.
    answer = await ask(hass, "get_status", appliance="kitchen oven")
    assert [a["name"] for a in answer["appliances"]] == ["Kitchen Oven"]


async def test_the_name_a_person_gave_the_device_wins(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket
) -> None:
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, JOULE)})
    registry.async_update_device(device.id, name_by_user="Sous Vide")
    answer = await ask(hass, "get_status", appliance="sous vide")
    assert [a["name"] for a in answer["appliances"]] == ["Sous Vide"]
    # By device id and by serial too.
    for key in (device.id, JOULE):
        answer = await ask(hass, "get_status", appliance=key)
        assert answer["appliances"][0]["device_id"] == device.id


async def test_an_unknown_or_ambiguous_appliance_is_refused_with_the_names(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "stop", appliance="toaster")
    assert err.value.translation_key == "unknown_appliance"
    assert err.value.translation_placeholders["names"] == "Countertop, Kitchen Oven"
    # Two appliances and none named: which one?
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "stop")
    assert err.value.translation_key == "which_appliance"


async def test_start_by_name_with_a_preset_and_an_override(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    await push(hass, socket, OVEN_IDLE, csj("IDLE", 0, setPoint=None, cookId=None))
    answer = await ask(hass, "start", appliance="countertop", preset="steak_medium_rare")
    assert answer["started"] is True and answer["temperature"] == 56
    assert answer["duration_minutes"] == 90
    steps = client.load_manual_recipe.await_args.args[3]
    assert steps[0]["holdingTemperature"] == 56.0
    # Anything said beside the preset wins.
    answer = await ask(hass, "start", appliance="countertop", preset="Steak medium rare", temperature=54)
    assert client.load_manual_recipe.await_args.args[3][0]["holdingTemperature"] == 54.0
    # The oven waits for Start on its panel, and says so.
    answer = await ask(hass, "start", appliance="oven", mode="air_fry")
    assert answer["mode"] == "air_fry"
    assert "Start" in answer["message"]
    assert client.load_manual_recipe.await_args.args[0] == OVEN


async def test_start_refusals_raise(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    await push(hass, socket, OVEN_IDLE, csj("IDLE", 0, setPoint=None, cookId=None))
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "start", appliance="countertop", preset="no such thing")
    assert err.value.translation_key == "unknown_preset"
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "start", appliance="countertop", preset="frozen_fries")
    assert err.value.translation_key == "preset_does_not_fit"
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "start", appliance="countertop", mode="bake")
    assert err.value.translation_key == "mode_oven_only"
    # Already cooking: stop it first, rather than a second cook over the first.
    await push(hass, socket, csj("ACTIVE", 3, timeRemaining=240))
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "start", appliance="countertop", temperature=60)
    assert err.value.translation_key == "already_cooking"
    client.load_manual_recipe.assert_not_awaited()


async def test_untested_models_stay_monitor_only(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    from custom_components.bruh_cooking.appliance import MODELS

    MODELS_TESTED = MODELS["CSJ100"].tested
    try:
        object.__setattr__(MODELS["CSJ100"], "tested", False)
        await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
        with pytest.raises(ServiceValidationError) as err:
            await ask(hass, "start", appliance="countertop", temperature=60)
        assert err.value.translation_key == "untested_control"
        hass.config_entries.async_update_entry(entry, options={CONF_ALLOW_UNTESTED_CONTROL: True})
        assert (await ask(hass, "start", appliance="countertop", temperature=60))["started"]
    finally:
        object.__setattr__(MODELS["CSJ100"], "tested", MODELS_TESTED)


async def test_stop_and_continue(
    hass: HomeAssistant, entry: MockConfigEntry, socket: FakeSocket, client: MagicMock
) -> None:
    await push(hass, socket, csj("IDLE", 0, setPoint=None, cookId=None))
    answer = await ask(hass, "stop", appliance="countertop")
    assert answer["stopped"] is False
    client.stop_recipe.assert_not_awaited()
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "continue_cook", appliance="countertop")
    assert err.value.translation_key == "nothing_to_continue"

    await push(hass, socket, csj("ACTIVE", 2))
    answer = await ask(hass, "continue_cook", appliance="countertop")
    assert answer["continued"] is True
    client.finish_wait.assert_awaited_once_with(JOULE, "CSJ100", {})
    answer = await ask(hass, "stop", appliance="countertop")
    assert answer["stopped"] is True
    assert client.stop_recipe.await_args.args == (JOULE, "CSJ100")


async def test_presets_are_the_ones_each_appliance_can_cook(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    answer = await ask(hass, "get_presets", appliance="countertop")
    ids = {p["id"] for p in answer["presets"]}
    assert "steak_medium_rare" in ids and "frozen_fries" not in ids
    every = await ask(hass, "get_presets")
    fries = next(p for p in every["presets"] if p["id"] == "frozen_fries")
    assert fries["fits"] == ["Kitchen Oven"] and fries["mode"] == "air_fry"


async def test_with_nothing_set_up_the_services_say_so(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(ServiceValidationError) as err:
        await ask(hass, "get_status", appliance="countertop")
    assert err.value.translation_key == "no_appliances"
    assert await ask(hass, "get_status") == {"appliances": []}
