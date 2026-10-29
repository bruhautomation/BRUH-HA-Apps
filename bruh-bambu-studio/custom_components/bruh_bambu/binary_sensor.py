"""Three yes-or-no answers from print failure detection, per printer.

* Print problem — on while an alert is open (a warning, or a failure the
  printer was paused for); `level` says which. The trigger an automation
  wants: "flash the office light when the print has a problem".
* Plate clear — on when the finished print has been taken off, off while a
  print is on the plate, unknown when nothing has looked (the plate watch
  off, or a plate nobody has seen empty). The plate watch runs after a
  finish with failure detection on or off, so it does not need detection.
* Camera covered — on while the lens is covered (or the chamber too dark to
  see), which is when nothing is being checked.

They read the same mirror the sensors do, and a printer added later gets
them on the next refresh.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BruhBambuCoordinator


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
            new.extend(cls(coordinator, entry, printer) for cls in BINARY_SENSORS)
        if new:
            add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class _WatchBinary(CoordinatorEntity[BruhBambuCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    key = ""

    def __init__(self, coordinator, entry: ConfigEntry, printer: dict) -> None:
        super().__init__(coordinator)
        self._pid = printer["id"]
        self._attr_unique_id = f"{entry.entry_id}_{self._pid}_{self.key}"
        self._attr_translation_key = self.key
        self._attr_device_info = {"identifiers": {(DOMAIN, self._pid)}}

    def _watch(self) -> dict | None:
        data = self.coordinator.data or {}
        if not data.get("available"):
            return None
        for printer in data.get("printers") or []:
            if printer.get("id") == self._pid:
                return printer.get("failure_detection") or {}
        return None

    @property
    def available(self) -> bool:
        watch = self._watch()
        return bool(watch is not None and watch.get("enabled"))


class PrintProblem(_WatchBinary):
    key = "print_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def _alert(self) -> dict:
        alert = (self._watch() or {}).get("alert") or {}
        return alert if alert.get("open") else {}

    @property
    def is_on(self) -> bool:
        return bool(self._alert())

    @property
    def extra_state_attributes(self) -> dict:
        alert = self._alert()
        if not alert:
            return {"bruh_bambu_printer": self._pid}
        return {"level": alert.get("level"), "problem": alert.get("problem"),
                "summary": alert.get("summary"), "paused": alert.get("paused"),
                "pause_error": alert.get("pause_error") or None, "alert_id": alert.get("id"),
                "confidence": alert.get("confidence"), "bruh_bambu_printer": self._pid}


class PlateClear(_WatchBinary):
    key = "plate_clear"

    @property
    def available(self) -> bool:
        watch = self._watch()
        return bool(watch is not None and watch.get("plate_watch"))

    @property
    def is_on(self) -> bool | None:
        state = ((self._watch() or {}).get("plate") or {}).get("state")
        if state == "clear":
            return True
        if state in ("occupied", "printing"):
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict:
        plate = (self._watch() or {}).get("plate") or {}
        return {k: v for k, v in (("state", plate.get("state")), ("why", plate.get("why")),
                                  ("bruh_bambu_printer", self._pid)) if v}


class CameraCovered(_WatchBinary):
    key = "camera_covered"

    @property
    def is_on(self) -> bool | None:
        view = (self._watch() or {}).get("view")
        if view in ("covered", "dark"):
            return True
        if view == "ok":
            return False
        return None

    @property
    def extra_state_attributes(self) -> dict:
        return {"view": (self._watch() or {}).get("view"), "bruh_bambu_printer": self._pid}


BINARY_SENSORS = (PrintProblem, PlateClear, CameraCovered)
