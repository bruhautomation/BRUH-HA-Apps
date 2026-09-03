"""Sensors reading the add-on's state mirror.

Four kinds, and the split is about what each one answers.

`sensor.bruh_print_printer` is the printer's name, so a dashboard can say
which LabelWriter is attached and an automation can notice when none is. Its
attributes carry the model's geometry, which is what tells a template whether
the second roll exists at all.

One sensor per roll, whose STATE is the estimated count and whose attributes
name the stock. The state is a number because that is what a gauge card and a
numeric-state trigger want — "warn me when the cryo roll is under 50" is the
whole reason these exist — and it is documented as an estimate everywhere it
appears, because nothing on a LabelWriter reports a real level.

`sensor.bruh_print_last_label` is what came out most recently, which is the
one thing you want on a wall dashboard beside the printer.

None of them goes unavailable when the add-on is stopped. They report it, in
words, and keep their attributes — an unavailable entity hides its attributes
in Home Assistant, so the reason would go with them.
"""
from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BruhPrintCoordinator

SIDES = ("left", "right")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            add_entities: AddEntitiesCallback) -> None:
    coordinator: BruhPrintCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        PrinterSensor(coordinator, entry),
        LastLabelSensor(coordinator, entry),
        PrintedTodaySensor(coordinator, entry),
    ]
    entities.extend(RollSensor(coordinator, entry, side) for side in SIDES)
    add_entities(entities)


class _Base(CoordinatorEntity[BruhPrintCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BruhPrintCoordinator,
                 entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "BRUH Print",
            "manufacturer": "BRUH Automation",
            "model": "Label printer",
        }

    @property
    def _data(self) -> dict:
        return self.coordinator.data or {}

    @property
    def _offline_reason(self) -> str:
        if self._data.get("available"):
            return ""
        return str(self._data.get("reason")
                   or "The BRUH Print add-on is not running.")


class PrinterSensor(_Base):
    _attr_name = "Printer"
    _attr_icon = "mdi:printer-pos"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "printer")

    @property
    def native_value(self) -> str:
        if self._offline_reason:
            return "add-on stopped"
        printer = self._data.get("printer")
        if not printer:
            count = self._data.get("printer_count", 0)
            return "several — none chosen" if count > 1 else "none"
        return printer.get("name", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        printer = self._data.get("printer") or {}
        return {
            "reason": self._offline_reason,
            "connected": bool(printer),
            "printers_found": self._data.get("printer_count", 0),
            "two_rolls": bool(printer.get("twin")),
            "dots_across": printer.get("dots"),
            "printable_inches": printer.get("printable_in"),
            "serial": printer.get("serial", ""),
            "recognised": printer.get("recognised", True),
            "error": self._data.get("printer_error", ""),
            "add_on_version": self._data.get("version", ""),
        }


class RollSensor(_Base):
    """One bay's estimated remaining count."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "labels"
    _attr_icon = "mdi:roll"

    def __init__(self, coordinator, entry, side: str) -> None:
        super().__init__(coordinator, entry, f"roll_{side}")
        self._side = side
        self._attr_name = f"{side.title()} roll"

    @property
    def _roll(self) -> dict:
        return (self._data.get("rolls") or {}).get(self._side) or {}

    @property
    def available(self) -> bool:
        """A single-roll printer has no right bay, and an entity for one is a
        number about something that does not exist.

        The left bay is always available — on a one-roll model it IS the
        printer — so only the right one can disappear, and only once we have
        actually seen a printer that says it has one roll.
        """
        if self._side == "left":
            return True
        printer = self._data.get("printer")
        return not printer or bool(printer.get("twin"))

    @property
    def native_value(self) -> int:
        return int(self._roll.get("remaining", 0) or 0)

    @property
    def extra_state_attributes(self) -> dict:
        stock_id = self._roll.get("stock", "")
        stock = (self._data.get("stocks") or {}).get(stock_id) or {}
        changed = self._roll.get("changed_at") or 0
        return {
            "loaded": bool(self._roll.get("loaded")),
            "stock": stock_id,
            "stock_name": stock.get("name", ""),
            "size": stock.get("label", ""),
            "changed": (datetime.fromtimestamp(changed, timezone.utc).isoformat()
                        if changed else None),
            "note": self._roll.get("note", ""),
            "estimate": "Counted from prints, not reported by the printer.",
            "reason": self._offline_reason,
        }


class LastLabelSensor(_Base):
    _attr_name = "Last label"
    _attr_icon = "mdi:label"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "last_label")

    @property
    def native_value(self) -> str:
        last = self._data.get("last_print") or {}
        # Truncated because a sensor state over 255 characters is refused by
        # Core outright, and a label's title is whatever somebody typed.
        return (last.get("title") or "nothing yet")[:255]

    @property
    def extra_state_attributes(self) -> dict:
        last = self._data.get("last_print") or {}
        at = last.get("at") or 0
        return {
            "at": (datetime.fromtimestamp(at, timezone.utc).isoformat()
                   if at else None),
            "copies": last.get("copies", 0),
            "side": last.get("side", ""),
            "stock": last.get("stock", ""),
            "template": last.get("template", ""),
            "source": last.get("source", ""),
            "entry_id": last.get("id", ""),
            "reason": self._offline_reason,
        }


class PrintedTodaySensor(_Base):
    _attr_name = "Printed today"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "labels"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "printed_today")

    @property
    def native_value(self) -> int:
        return int(self._data.get("printed_today", 0) or 0)
