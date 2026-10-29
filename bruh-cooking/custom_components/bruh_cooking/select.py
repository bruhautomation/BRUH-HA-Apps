"""Oven mode, convection and level for the next BOV950 cook."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import BrevilleConfigEntry
from .appliance import (
    CONVECTION_ALL,
    MODEL_BOV950,
    OVEN_MODES,
    BroilLevel,
    OvenMode,
    OvenModeType,
    SlowCookLevel,
    oven_mode_defaults,
)
from .const import DOMAIN
from .entity import BrevilleEntity, async_add_appliance_entities

PARALLEL_UPDATES = 0

LEVEL_OPTIONS = {
    OvenModeType.BROIL: {"low": BroilLevel.LOW, "medium": BroilLevel.MEDIUM, "high": BroilLevel.HIGH},
    OvenModeType.SLOW_COOK: {"low": SlowCookLevel.LOW, "high": SlowCookLevel.HIGH},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrevilleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_appliance_entities(
        entry,
        async_add_entities,
        lambda coordinator, appliance: (
            (
                OvenModeSelect(coordinator, appliance, "oven_mode"),
                ConvectionSelect(coordinator, appliance, "convection"),
                LevelSelect(coordinator, appliance, "level"),
            )
            if appliance.model == MODEL_BOV950
            else ()
        ),
    )


class OvenSettingSelect(BrevilleEntity, SelectEntity, RestoreEntity):
    @property
    def mode(self) -> OvenMode | None:
        """The mode whose options apply: the running one, else the selected one."""
        status = self.appliance.status
        if status.active and (running := status.cook_mode or status.mode) in OVEN_MODES:
            return OVEN_MODES[running]
        return OVEN_MODES.get(self.appliance.settings.mode or "")

    def _ensure_idle(self) -> None:
        if self.appliance.status.active:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="stop_cook_first"
            )

    def _changed(self) -> None:
        self.coordinator.async_update_listeners()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state in self.options:
            self._restore(last.state)

    def _restore(self, option: str) -> None:
        raise NotImplementedError


class OvenModeSelect(OvenSettingSelect):
    _attr_options = list(OVEN_MODES)

    @property
    def current_option(self) -> str | None:
        status = self.appliance.status
        if status.active:
            # Keeping warm after a cook, the cook's own mode.
            mode = status.cook_mode or status.mode
            return mode if mode in OVEN_MODES else None
        return self.appliance.settings.mode

    async def async_select_option(self, option: str) -> None:
        self._ensure_idle()
        settings = self.appliance.settings
        defaults = oven_mode_defaults(OVEN_MODES[option])
        defaults.auto_start_timer = settings.auto_start_timer
        defaults.keep_warm = settings.keep_warm
        self.appliance.settings = defaults
        self._changed()

    def _restore(self, option: str) -> None:
        # Only the mode: the restored temperature and time stay as they were.
        self.appliance.settings.mode = option


class ConvectionSelect(OvenSettingSelect):
    @property
    def options(self) -> list[str]:
        mode = self.mode
        return list(mode.convection_allowed) if mode else list(CONVECTION_ALL)

    @property
    def current_option(self) -> str | None:
        status = self.appliance.status
        if status.active:
            return status.convection
        return self.appliance.settings.convection

    async def async_select_option(self, option: str) -> None:
        self._ensure_idle()
        self.appliance.settings.convection = option
        self._changed()

    def _restore(self, option: str) -> None:
        self.appliance.settings.convection = option


class LevelSelect(OvenSettingSelect):
    """Broil intensity or slow-cook level, depending on the mode."""

    @property
    def _levels(self) -> dict[str, int]:
        mode = self.mode
        return LEVEL_OPTIONS.get(mode.type, {}) if mode else {}

    @property
    def available(self) -> bool:
        return bool(self._levels) and super().available

    @property
    def options(self) -> list[str]:
        return list(self._levels) or ["low", "medium", "high"]

    @property
    def current_option(self) -> str | None:
        status = self.appliance.status
        # The running cook's level when the oven reports it, else the next cook's.
        level = status.level if status.active and status.level else self.appliance.settings.level
        return next((name for name, value in self._levels.items() if value == level), None)

    async def async_select_option(self, option: str) -> None:
        self._ensure_idle()
        self.appliance.settings.level = int(self._levels[option])
        self._changed()

    def _restore(self, option: str) -> None:
        if option in self._levels:
            self.appliance.settings.level = int(self._levels[option])
