"""Binary sensor platform."""
from __future__ import annotations

import time

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BruhMinecraftCoordinator
from .entity import BruhMinecraftEntity


# The stats collector writes every 15 s. Stats older than this mean it (or the
# whole add-on) is no longer running, whatever the last file said.
STALE_AFTER_SECONDS = 90

# Add-on states in which the Java server is not running.
DOWN_STATUSES = ("stopped", "waiting_for_setup")


def server_is_up(stats: dict, state: dict, now: float | None = None) -> bool:
    """True when the stats say the server answers, and they are not a dead
    server's last words: fresh, and the add-on has not marked it stopped."""
    if not stats.get("reachable"):
        return False
    if str((state or {}).get("status") or "") in DOWN_STATUSES:
        return False
    updated = stats.get("updated_at")
    if isinstance(updated, (int, float)):
        if (now if now is not None else time.time()) - updated > STALE_AFTER_SECONDS:
            return False
    return True


BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="reachable",
        name="Online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="rcon_ok",
        name="RCON reachable",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_registry_enabled_default=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BruhMinecraftCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BruhBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class BruhBinarySensor(BruhMinecraftEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: BruhMinecraftCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:  # type: ignore[override]
        stats = self.stats
        value = bool(stats.get(self.entity_description.key))
        # Both sensors are about a live server: a stopped or silent one is off.
        return value and server_is_up(stats, self.state_info)
