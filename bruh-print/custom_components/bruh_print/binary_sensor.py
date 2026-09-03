"""Is BRUH Print ready to print right now?

One entity, because that is one question, and it is the question a dashboard
conditional card and an automation both ask. It is `problem`-classed rather
than `connectivity` on purpose: "on means trouble" is what makes a bare
badge readable at a glance, and the trouble here is not only a disconnected
printer — an empty roll and a stopped add-on look the same to somebody
pressing print.

The reason lives in an attribute and the entity never goes unavailable,
because Home Assistant hides the attributes of an unavailable entity and the
reason would go with them.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BruhPrintCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            add_entities: AddEntitiesCallback) -> None:
    coordinator: BruhPrintCoordinator = hass.data[DOMAIN][entry.entry_id]
    add_entities([ReadyBinarySensor(coordinator, entry)])


class ReadyBinarySensor(CoordinatorEntity[BruhPrintCoordinator],
                        BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_problem"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "BRUH Print",
            "manufacturer": "BRUH Automation",
            "model": "Label printer",
        }

    def _trouble(self) -> str:
        data = self.coordinator.data or {}
        if not data.get("available"):
            return str(data.get("reason") or "The add-on is not running.")
        if not data.get("printer"):
            if data.get("printer_count", 0) > 1:
                return ("More than one DYMO is plugged in and none is chosen. "
                        "Pick one on the panel's Printer tab.")
            return (data.get("printer_error")
                    or "No DYMO printer is plugged in.")
        rolls = data.get("rolls") or {}
        printer = data.get("printer") or {}
        bays = ["left", "right"] if printer.get("twin") else ["left"]
        if not any((rolls.get(side) or {}).get("loaded") for side in bays):
            return ("BRUH Print does not know what labels are loaded, so it "
                    "cannot check a label against the roll.")
        return ""

    @property
    def is_on(self) -> bool:
        return bool(self._trouble())

    @property
    def extra_state_attributes(self) -> dict:
        return {"reason": self._trouble()}
