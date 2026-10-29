"""Binary sensors for Breville+ appliances."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BrevilleConfigEntry
from .appliance import MODEL_BOV950
from .coordinator import Appliance
from .entity import BrevilleEntity, async_add_appliance_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BrevilleBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Callable[[Appliance], bool | None]
    models: frozenset[str] | None = None


BINARY_SENSORS: tuple[BrevilleBinarySensorDescription, ...] = (
    BrevilleBinarySensorDescription(
        key="cooking",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda a: a.status.active,
    ),
    BrevilleBinarySensorDescription(
        key="door",
        device_class=BinarySensorDeviceClass.DOOR,
        models=frozenset({MODEL_BOV950}),
        value_fn=lambda a: a.status.door_open,
    ),
    BrevilleBinarySensorDescription(
        key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda a: a.status.error != "none",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrevilleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_appliance_entities(
        entry,
        async_add_entities,
        lambda coordinator, appliance: (
            BrevilleBinarySensor(coordinator, appliance, description)
            for description in BINARY_SENSORS
            if description.models is None or appliance.model in description.models
        ),
    )


class BrevilleBinarySensor(BrevilleEntity, BinarySensorEntity):
    entity_description: BrevilleBinarySensorDescription

    def __init__(self, coordinator, appliance, description: BrevilleBinarySensorDescription) -> None:
        super().__init__(coordinator, appliance, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.appliance)
