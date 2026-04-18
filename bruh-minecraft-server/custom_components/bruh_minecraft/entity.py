"""Base entity shared by sensors, binary_sensors, and buttons."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import BruhMinecraftCoordinator


class BruhMinecraftEntity(CoordinatorEntity[BruhMinecraftCoordinator]):
    """Base class providing device_info + stable unique_id prefix."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BruhMinecraftCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{key}"
        version = (coordinator.data or {}).get("stats", {}).get("version")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "server")},
            name=MODEL,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=version or "unknown",
            configuration_url="homeassistant://hassio/addon/bruh_minecraft_server/info",
        )

    @property
    def stats(self) -> dict:
        return (self.coordinator.data or {}).get("stats", {})

    @property
    def state_info(self) -> dict:
        return (self.coordinator.data or {}).get("state", {})
