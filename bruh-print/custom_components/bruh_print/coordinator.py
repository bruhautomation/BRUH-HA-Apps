"""Reads the add-on's state mirror on a timer."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, SCAN_INTERVAL_SECONDS, STATE_FILE

_LOGGER = logging.getLogger(__name__)


class BruhPrintCoordinator(DataUpdateCoordinator[dict]):
    """One reader of /config/.bruh_print/state.json for every entity."""

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
                        "reason": "The BRUH Print add-on has not started yet."}
            except (OSError, json.JSONDecodeError) as exc:
                return {"available": False, "reason": str(exc)}
            data["available"] = True
            return data

        return await self.hass.async_add_executor_job(_read)
