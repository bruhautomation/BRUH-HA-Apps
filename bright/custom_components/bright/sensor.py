"""Show-status sensor for BRight."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import BrightCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BrightCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BrightShowStatusSensor(coordinator, entry)])


class BrightShowStatusSensor(CoordinatorEntity[BrightCoordinator], SensorEntity):
    """What the director is doing right now: idle, compiling, or playing."""

    _attr_has_entity_name = True
    _attr_translation_key = "show_status"

    def __init__(self, coordinator: BrightCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_show_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BRight",
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def native_value(self) -> str:
        return str(self.coordinator.data.get("status", "idle") or "idle")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "track": data.get("track"),
            "media_player": data.get("media_player"),
            "position_s": data.get("position_s"),
            # `active` is the add-on's own answer to "is a run in
            # progress", and `lights_busy` to "are cues still going out".
            # A template that wants to offer a Stop button reads these
            # rather than comparing the state string to a list of the
            # words that happen to mean running today.
            "active": bool(data.get("active")),
            "lights_busy": bool(data.get("lights_busy")),
            "party": data.get("party"),
            "queue_left": data.get("queue_left"),
            "cues_sent": data.get("cues_sent"),
            "cues_total": data.get("cues_total"),
            "parties": data.get("parties") or [],
            "playback_warning": data.get("playback_warning"),
            "error": data.get("error"),
        }
