"""The two presses brAIn offers as Home Assistant buttons.

An insight job's **Run now**, one per job entry — and **Run house checks**
on the brAIn System device, which is the scheduled checks pass brought
forward. The second one exists because the pass is the only thing in the
add-on with an hours-long timer in front of it: "I just fixed that, is it
clear yet" had no answer except opening the panel, or waiting.

It calls `brain.check` through the service registry rather than writing a
request itself, so there is exactly one implementation of what asking for
a pass means — the button, an automation and a voice command all land on
the same handler, and the log line says the same thing about each.
"""

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
    """A Run-now button per insight job, and one Run-checks button in all."""
    from . import entry_type  # local import: avoid cycle

    if entry_type(config_entry) == ENTRY_TYPE_INSIGHT:
        async_add_entities([BruhClaudeInsightRunButton(config_entry)])
        return

    # Account-wide, like the health binary sensor it shares a device with:
    # there is one add-on and one checks pass however many agent entries a
    # house has, and a button per entry would be several controls that all
    # do the identical thing. The flag pair is cleared on unload so a
    # reload brings the button back.
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_checks_button_added"):
        return
    domain_data["_checks_button_added"] = True
    domain_data["_checks_button_entry"] = config_entry.entry_id
    async_add_entities([BrainRunChecksButton(config_entry)])


class BruhClaudeInsightRunButton(ButtonEntity):
    """Fires the insight job immediately (same as brain.run_insight)."""

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


class BrainRunChecksButton(ButtonEntity):
    """Asks brAIn to run its house checks now (same as brain.check)."""

    _attr_has_entity_name = True
    _attr_name = "Run house checks"
    _attr_icon = "mdi:home-search-outline"
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "system_health")},
        name="brAIn System",
        manufacturer="BRUH Automation",
        model="Claude Terminal",
    )

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_run_checks"

    async def async_press(self) -> None:
        # Through the service, never around it: `brain.check` is the one
        # implementation of asking for a pass, and a button that wrote its
        # own request file would be a second one to keep in step.
        await self.hass.services.async_call(DOMAIN, "check", {}, blocking=True)
