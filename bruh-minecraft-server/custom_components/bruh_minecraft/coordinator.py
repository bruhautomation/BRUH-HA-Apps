"""DataUpdateCoordinator that polls the add-on's shared JSON state files."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN, SCAN_INTERVAL, STATS_FILE, STATE_FILE, PLAYERS_FILE

_LOGGER = logging.getLogger(__name__)


class BruhMinecraftCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll the shared /config/.bruh_minecraft/*.json files."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        def _load() -> dict[str, Any]:
            data: dict[str, Any] = {"stats": {}, "state": {}, "players": {}}
            for key, path in (
                ("stats", STATS_FILE),
                ("state", STATE_FILE),
                ("players", PLAYERS_FILE),
            ):
                p = Path(path)
                if p.is_file():
                    try:
                        data[key] = json.loads(p.read_text())
                    except (json.JSONDecodeError, OSError):
                        data[key] = {}
            return data

        return await asyncio.to_thread(_load)
