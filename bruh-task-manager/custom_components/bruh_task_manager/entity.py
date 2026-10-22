"""The one device every entity hangs off."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TaskManagerCoordinator


class TaskManagerEntity(CoordinatorEntity[TaskManagerCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TaskManagerCoordinator, entry: ConfigEntry,
                 key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "BRUH Task Manager",
            "manufacturer": "BRUH Automation",
            "model": "Task manager",
        }

    @property
    def data(self) -> dict:
        return self.coordinator.data or {}
