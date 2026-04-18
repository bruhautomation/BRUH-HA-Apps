"""Binary sensor platform."""
from __future__ import annotations

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
        return bool(self.stats.get(self.entity_description.key))
