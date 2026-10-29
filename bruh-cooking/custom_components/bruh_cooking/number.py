"""Target temperature and cook time.

While a cook runs, changing a value edits the cook. Otherwise it sets what
the next cook (started with the Cook switch) will use.
"""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrevilleConfigEntry
from .appliance import (
    MODEL_BOV950,
    MODELS,
    OVEN_MODES,
    CookSettings,
    CookState,
    OvenMode,
    OvenModeType,
    duration_limits,
    temp_limits,
)
from .entity import BrevilleEntity, async_add_appliance_entities

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrevilleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_appliance_entities(
        entry,
        async_add_entities,
        lambda coordinator, appliance: (
            TargetTemperatureNumber(coordinator, appliance, "target_temperature"),
            CookTimeNumber(coordinator, appliance, "cook_time"),
        ),
    )


class BrevilleSettingNumber(BrevilleEntity, RestoreNumber):
    _attr_mode = NumberMode.BOX

    @property
    def oven_mode(self) -> OvenMode | None:
        """The mode whose limits apply: the running one, else the selected one."""
        appliance = self.appliance
        if appliance.model != MODEL_BOV950:
            return None
        if appliance.status.active and appliance.status.mode in OVEN_MODES:
            return OVEN_MODES[appliance.status.mode]
        return OVEN_MODES.get(appliance.settings.mode or "")

    @property
    def limit_settings(self) -> CookSettings:
        """Settings to take limits from, using the running oven mode if any."""
        settings = self.appliance.settings
        mode = self.oven_mode
        if mode is None or mode.option == settings.mode:
            return settings
        return replace(settings, mode=mode.option)

    def _changed(self) -> None:
        # Other entities' limits and options depend on the settings.
        self.coordinator.async_update_listeners()


class TargetTemperatureNumber(BrevilleSettingNumber):
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def available(self) -> bool:
        if self.appliance.model == MODEL_BOV950:
            mode = self.oven_mode
            if mode is None or mode.type is not OvenModeType.TEMP:
                return False
        return super().available

    @property
    def native_min_value(self) -> float:
        return temp_limits(self.appliance.model, self.limit_settings)[0]

    @property
    def native_max_value(self) -> float:
        return temp_limits(self.appliance.model, self.limit_settings)[1]

    @property
    def native_step(self) -> float:
        mode = self.oven_mode
        return float(mode.round_to) if mode else 0.1

    @property
    def native_value(self) -> float | None:
        status = self.appliance.status
        if status.active and status.target_temp_c is not None:
            return status.target_temp_c
        return self.appliance.settings.temperature_c

    async def async_set_native_value(self, value: float) -> None:
        appliance = self.appliance
        if appliance.status.active:
            await self.coordinator.async_edit_cook(appliance, temperature_c=value)
        else:
            appliance.settings.temperature_c = value
            self._changed()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self.appliance.settings.temperature_c = last.native_value


class CookTimeNumber(BrevilleSettingNumber):
    """Cook time in minutes; 0 holds the temperature until stopped (sous vide)."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_step = 1

    @property
    def native_min_value(self) -> float:
        return duration_limits(self.appliance.model, self.limit_settings)[0] // 60

    @property
    def native_max_value(self) -> float:
        return duration_limits(self.appliance.model, self.limit_settings)[1] // 60

    @property
    def native_value(self) -> float | None:
        appliance = self.appliance
        status = appliance.status
        if status.active:
            # Where a running cook can be changed, a new time replaces what's
            # left, so show that. Otherwise show the cook's length.
            if (
                MODELS[appliance.model].can_edit_cook
                and status.state is CookState.COOKING
                and status.time_remaining_s is not None
            ):
                return round(status.time_remaining_s / 60)
            if status.cook_time_s is not None:
                return round(status.cook_time_s / 60)
            # Sous vide without a timer holds until stopped. An oven always
            # has one, but doesn't report it until preheating is done.
            return None if appliance.model == MODEL_BOV950 else 0
        return round((appliance.settings.duration_s or 0) / 60)

    async def async_set_native_value(self, value: float) -> None:
        appliance = self.appliance
        seconds = int(value * 60)
        if appliance.status.active:
            await self.coordinator.async_edit_cook(appliance, duration_s=seconds)
        else:
            appliance.settings.duration_s = seconds or None
            self._changed()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last and last.native_value is not None:
            self.appliance.settings.duration_s = int(last.native_value * 60) or None
