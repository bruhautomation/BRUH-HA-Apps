"""Run-now buttons for BRUH Claude insight jobs."""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, ENTRY_TYPE_INSIGHT

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add a Run-now button for each insight job entry."""
    from . import entry_type  # local import: avoid cycle

    if entry_type(config_entry) != ENTRY_TYPE_INSIGHT:
        return
    async_add_entities([BruhClaudeInsightRunButton(config_entry)])


class BruhClaudeInsightRunButton(ButtonEntity):
    """Fires the insight job immediately (same as bruh_claude.run_insight)."""

    _attr_has_entity_name = True
    _attr_name = "Run now"
    _attr_icon = "mdi:play-circle-outline"

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_run_now"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"insight_{config_entry.entry_id}")},
            name=config_entry.title,
            manufacturer="BRUH Automation",
            model="Claude Insight Job",
        )

    async def async_press(self) -> None:
        from . import _async_run_insight  # local import: avoid cycle

        _LOGGER.info("Insight job '%s' triggered via button", self._entry.title)
        self.hass.async_create_task(_async_run_insight(self.hass, self._entry))
