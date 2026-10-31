"""DataUpdateCoordinator that polls the add-on's shared JSON state files."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (DOMAIN, PLAYERS_FILE, SCAN_INTERVAL, STALE_AFTER, STATE_FILE,
                    STATS_FILE, WORLD_FILE)

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
            # The world layer is newer than the integration's first three
            # files, so its key is there only when the add-on writes it.
            p = Path(WORLD_FILE)
            if p.is_file():
                try:
                    world = json.loads(p.read_text())
                except (json.JSONDecodeError, OSError):
                    world = {}
                data["world"] = world if isinstance(world, dict) else {}
            return stale(data, time.time())

        return await asyncio.to_thread(_load)


def stale(data: dict[str, Any], now: float) -> dict[str, Any]:
    """Files the add-on stopped writing say nobody is on and nothing answers.

    A stopped add-on leaves its last stats.json behind, and that file said
    the server was online with whoever was on at the time — so "Online"
    stayed on, and the players stayed on, until the add-on came back. A
    file older than STALE_AFTER is read as the server being down. A file
    with no `updated_at` (an older add-on) is taken as it is.
    """
    stats = data.get("stats")
    if isinstance(stats, dict) and _old(stats.get("updated_at"), now):
        data["stats"] = {**stats, "reachable": False, "rcon_ok": False,
                         "online": 0, "players": [], "stale": True}
    world = data.get("world")
    if isinstance(world, dict) and _old(world.get("updated_at"), now):
        data["world"] = {**world, "reachable": False, "online": 0, "players": [],
                         "time": None, "stale": True}
    return data


def _old(stamp: Any, now: float) -> bool:
    return isinstance(stamp, (int, float)) and now - stamp > STALE_AFTER
