"""Reads the add-on's state mirror on a timer."""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, SCAN_INTERVAL_SECONDS, STALE_AFTER_SECONDS, STATE_FILE

_LOGGER = logging.getLogger(__name__)


class BruhBambuCoordinator(DataUpdateCoordinator[dict]):
    """One reader of /config/.bruh_bambu/state.json for every entity."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> dict:
        def _read() -> dict:
            try:
                data = json.loads(STATE_FILE.read_text())
            except FileNotFoundError:
                # Not an error, and deliberately not raised as one: the file
                # does not exist until the add-on has started once. Raising
                # would make every entity unavailable with "update failed",
                # which reads as broken rather than as not-yet-running.
                return {"available": False,
                        "reason": "The BRUH Bambu Studio add-on has not started yet."}
            except (OSError, json.JSONDecodeError) as exc:
                return {"available": False, "reason": str(exc)}
            # Aged by the file's mtime, not its stamp: a clock corrected
            # after the stamp was written must not keep it fresh for ever.
            age = time.time() - STATE_FILE.stat().st_mtime
            if age > STALE_AFTER_SECONDS:
                return {"available": False,
                        "reason": "The BRUH Bambu Studio add-on has stopped "
                                  "updating; is it running?"}
            data["available"] = True
            return data

        return await self.hass.async_add_executor_job(_read)
