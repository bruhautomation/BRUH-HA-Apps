"""Five sensors per printer, read from the add-on's state mirror.

`status` is the printer's own word for what it is doing (idle, prepare,
running, pause, finish, failed — lower-cased, never translated, so a word
added by a firmware update still reads as itself) with everything else as
attributes. Progress, time left and the two temperatures are their own
sensors because that is what a gauge, a history graph and a
numeric-state trigger ("tell me when it is under 10 minutes") want.

Printers added on the panel later get their sensors on the next refresh;
nobody has to reload the integration.
"""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BruhBambuCoordinator

# Everything a card needs is on the status sensor, so a card names one
# entity per printer and reads one state rather than five.
ATTRS = ("file", "stage", "progress", "remaining_min", "layer", "total_layers", "speed",
         "chamber_light", "ams", "ams_units", "active_tray", "external_spool",
         "error_code", "hms_count", "hms", "hms_notes", "fans", "nozzle_c",
         "nozzle_target_c", "bed_c", "bed_target_c", "chamber_c", "nozzle_diameter",
         "connection_error", "host", "serial", "model", "printing")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            add_entities: AddEntitiesCallback) -> None:
    coordinator: BruhBambuCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = []
        for printer in (coordinator.data or {}).get("printers") or []:
            pid = printer.get("id")
            if not pid or pid in known:
                continue
            known.add(pid)
            new.extend(cls(coordinator, entry, printer) for cls in SENSORS)
        if new:
            add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class _PrinterSensor(CoordinatorEntity[BruhBambuCoordinator], SensorEntity):
    _attr_has_entity_name = True
    key = ""
    field = ""

    def __init__(self, coordinator, entry: ConfigEntry, printer: dict) -> None:
        super().__init__(coordinator)
        self._pid = printer["id"]
        self._attr_unique_id = f"{entry.entry_id}_{self._pid}_{self.key}"
        self._attr_translation_key = self.key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self._pid)},
            "name": printer.get("name") or "Bambu printer",
            "manufacturer": "Bambu Lab",
            "model": printer.get("model") or None,
            "serial_number": printer.get("serial"),
        }

    def _printer(self) -> dict | None:
        data = self.coordinator.data or {}
        if not data.get("available"):
            return None
        for printer in data.get("printers") or []:
            if printer.get("id") == self._pid:
                return printer
        return None

    @property
    def available(self) -> bool:
        printer = self._printer()
        return bool(printer and printer.get("online"))

    @property
    def native_value(self):
        printer = self._printer() or {}
        return printer.get(self.field)


class StatusSensor(_PrinterSensor):
    key, field = "status", "state"

    @property
    def available(self) -> bool:
        # Never unavailable: an unavailable entity hides its attributes, and
        # the reason it is not reporting is one of them.
        return True

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        if not data.get("available"):
            return "unknown"
        printer = self._printer()
        if printer is None:
            return "removed"
        if not printer.get("online"):
            return "offline"
        return printer.get("state") or "unknown"

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        printer = self._printer() or {}
        attrs = {k: printer.get(k) for k in ATTRS if printer.get(k) is not None}
        # The id the services take, and the mark the cards find printers by.
        attrs["bruh_bambu_printer"] = self._pid
        attrs["printer_name"] = printer.get("name") or self._pid
        if not data.get("available"):
            attrs["reason"] = data.get("reason")
        return attrs


class ProgressSensor(_PrinterSensor):
    key, field = "progress", "progress"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT


class RemainingSensor(_PrinterSensor):
    key, field = "remaining", "remaining_min"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES


class NozzleSensor(_PrinterSensor):
    key, field = "nozzle", "nozzle_c"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT


class BedSensor(_PrinterSensor):
    key, field = "bed", "bed_c"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT


class StageSensor(_PrinterSensor):
    """What the printer is doing inside its state: levelling, heating, changing filament."""
    key, field = "stage", "stage"

    @property
    def native_value(self):
        printer = self._printer() or {}
        return printer.get("stage") or ("Printing" if printer.get("printing") else "Idle")


SENSORS = (StatusSensor, StageSensor, ProgressSensor, RemainingSensor, NozzleSensor, BedSensor)
