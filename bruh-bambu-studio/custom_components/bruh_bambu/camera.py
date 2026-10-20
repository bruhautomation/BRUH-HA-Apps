"""A camera per printer, from frames the add-on writes beside the state mirror.

There is no port between Core and the add-on, so the camera is a pair of
files: asking for a picture touches `<printer>.want`, the add-on's camera
reader (started by that, stopped a little after nobody asks) writes the
newest frame to `<printer>.jpg`, and this reads it. A frame older than
FRESH_S is not served as current — the camera that stopped is said, not
shown frozen.
"""
from __future__ import annotations

import asyncio
import time

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CAMERA_DIR, DOMAIN
from .coordinator import BruhBambuCoordinator

FRESH_S = 10
FIRST_FRAME_WAIT_S = 8


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry,
                            add_entities: AddEntitiesCallback) -> None:
    coordinator: BruhBambuCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = []
        for printer in (coordinator.data or {}).get("printers") or []:
            pid = printer.get("id")
            if pid and pid not in known:
                known.add(pid)
                new.append(PrinterCamera(coordinator, entry, printer))
        if new:
            add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class PrinterCamera(CoordinatorEntity[BruhBambuCoordinator], Camera):
    _attr_has_entity_name = True
    _attr_translation_key = "camera"
    _attr_frame_interval = 1.0

    def __init__(self, coordinator, entry: ConfigEntry, printer: dict) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._pid = printer["id"]
        self._attr_unique_id = f"{entry.entry_id}_{self._pid}_camera"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._pid)}}

    def _printer(self) -> dict | None:
        data = self.coordinator.data or {}
        for printer in data.get("printers") or []:
            if printer.get("id") == self._pid:
                return printer
        return None

    @property
    def available(self) -> bool:
        printer = self._printer()
        return bool((self.coordinator.data or {}).get("available") and printer and printer.get("online"))

    @property
    def extra_state_attributes(self) -> dict:
        camera = (self._printer() or {}).get("camera") or {}
        return {k: v for k, v in (("kind", camera.get("kind")), ("error", camera.get("error")))
                if v}

    async def async_camera_image(self, width: int | None = None,
                                 height: int | None = None) -> bytes | None:
        want = CAMERA_DIR / f"{self._pid}.want"
        frame = CAMERA_DIR / f"{self._pid}.jpg"

        def _touch() -> None:
            CAMERA_DIR.mkdir(parents=True, exist_ok=True)
            want.touch()

        def _read() -> bytes | None:
            try:
                if time.time() - frame.stat().st_mtime > FRESH_S:
                    return None
                return frame.read_bytes()
            except OSError:
                return None

        await self.hass.async_add_executor_job(_touch)
        deadline = time.monotonic() + FIRST_FRAME_WAIT_S
        while True:
            data = await self.hass.async_add_executor_job(_read)
            if data or time.monotonic() > deadline:
                return data
            await asyncio.sleep(0.5)
