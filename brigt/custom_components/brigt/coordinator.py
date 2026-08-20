"""DataUpdateCoordinator that polls the add-on's shared state file."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, SCAN_INTERVAL, STATE_FILE

_LOGGER = logging.getLogger(__name__)


class BrigtCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the shared /config/.brigt/state.json the add-on mirrors."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        def _load() -> dict[str, Any]:
            path = Path(STATE_FILE)
            if not path.is_file():
                return {}
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}

        return await asyncio.to_thread(_load)
