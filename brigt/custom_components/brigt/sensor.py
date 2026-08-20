"""Show-status sensor for BRigt."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import BrigtCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BrigtCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BrigtShowStatusSensor(coordinator, entry)])


class BrigtShowStatusSensor(CoordinatorEntity[BrigtCoordinator], SensorEntity):
    """What the director is doing right now: idle, compiling, or playing."""

    _attr_has_entity_name = True
    _attr_translation_key = "show_status"

    def __init__(self, coordinator: BrigtCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_show_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="BRigt",
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
        }
