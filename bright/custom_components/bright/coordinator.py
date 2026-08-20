"""DataUpdateCoordinator that polls the add-on's shared state file."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, PARTIES_FILE, SCAN_INTERVAL, STATE_FILE

_LOGGER = logging.getLogger(__name__)


class BrightCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the shared /config/.bright/state.json the add-on mirrors."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        def _read(path_str: str) -> dict[str, Any]:
            path = Path(path_str)
            if not path.is_file():
                return {}
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                # A mirror caught mid-write, or an add-on that has not
                # started yet. Both are "nothing to report this poll",
                # never an unavailable entity.
                return {}
            return data if isinstance(data, dict) else {}

        def _load() -> dict[str, Any]:
            state = _read(STATE_FILE)
            parties = _read(PARTIES_FILE).get("parties")
            return {**state,
                    "parties": parties if isinstance(parties, list) else []}

        return await asyncio.to_thread(_load)
