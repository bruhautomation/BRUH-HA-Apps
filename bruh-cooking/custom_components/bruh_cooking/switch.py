"""Cook switch (start/stop) and cook options."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import BrevilleConfigEntry
from .appliance import MODEL_BOV950, OVEN_MODES
from .const import DOMAIN
from .entity import BrevilleEntity, async_add_appliance_entities
from .services import start_settings

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrevilleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    def entities_for(coordinator, appliance) -> list[BrevilleSwitch]:
        entities: list[BrevilleSwitch] = [
            CookSwitch(coordinator, appliance, "cook"),
            AutoStartTimerSwitch(coordinator, appliance, "auto_start_timer"),
        ]
        if appliance.model == MODEL_BOV950:
            entities.append(KeepWarmSwitch(coordinator, appliance, "keep_warm"))
            entities.append(FrozenSwitch(coordinator, appliance, "frozen"))
        return entities

    async_add_appliance_entities(entry, async_add_entities, entities_for)


class BrevilleSwitch(BrevilleEntity, SwitchEntity):
    async def async_start_cook_service(self, **kwargs: Any) -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="target_cook_switch"
        )


class CookSwitch(BrevilleSwitch):
    """On while a cook runs; turning it on starts one with the current settings."""

    @property
    def is_on(self) -> bool:
        return self.appliance.status.cooking

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_start_cook(self.appliance)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_stop_cook(self.appliance)

    async def async_start_cook_service(self, **kwargs: Any) -> None:
        """bruh_cooking.start_cook: start a cook with explicit settings."""
        settings = start_settings(self.hass, self.appliance, kwargs)
        await self.coordinator.async_start_cook(self.appliance, settings)


class BrevilleOptionSwitch(BrevilleSwitch, RestoreEntity):
    """A cook option stored in the appliance's settings."""

    _attr_entity_category = EntityCategory.CONFIG
    _field: str

    @property
    def available(self) -> bool:
        return self.cloud_available

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.appliance.settings, self._field))

    async def async_turn_on(self, **kwargs: Any) -> None:
        setattr(self.appliance.settings, self._field, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        setattr(self.appliance.settings, self._field, False)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Not from "unavailable": that says nothing about the setting.
        if (last := await self.async_get_last_state()) is not None and last.state in (
            STATE_ON,
            STATE_OFF,
        ):
            setattr(self.appliance.settings, self._field, last.state == STATE_ON)


class AutoStartTimerSwitch(BrevilleOptionSwitch):
    """Start the timer when the setpoint is reached instead of waiting for food."""

    _field = "auto_start_timer"


class KeepWarmSwitch(BrevilleOptionSwitch):
    """Keep food warm when an oven cook finishes."""

    _field = "keep_warm"


class FrozenSwitch(BrevilleOptionSwitch):
    """Cook from frozen, for the oven modes that offer it (pizza, cookies, reheat).

    Choosing a mode resets it to that mode's default.
    """

    _field = "frozen"

    @property
    def available(self) -> bool:
        mode = OVEN_MODES.get(self.appliance.settings.mode or "")
        return super().available and mode is not None and mode.frozen_default is not None
