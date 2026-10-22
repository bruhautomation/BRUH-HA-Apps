"""Reads the add-on's state mirror on a timer."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import mirror
from .const import DOMAIN, SCAN_INTERVAL_SECONDS, STATE_FILE

_LOGGER = logging.getLogger(__name__)


class TaskManagerCoordinator(DataUpdateCoordinator[dict]):
    """One reader of /config/.bruh_task_manager/state.json for every entity."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )

    async def _async_update_data(self) -> dict:
        # Never raised as an update failure: an absent or stale file is a
        # state with a reason, which the entities report.
        return await self.hass.async_add_executor_job(mirror.read, STATE_FILE)
