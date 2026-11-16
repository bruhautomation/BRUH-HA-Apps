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
    def available(self) -> bool:
        # The problem and cooking sensors read on or off while the appliance is
        # offline (why it is offline is the status sensor's to say): the last
        # error seen stands, and an appliance that was idle when contact went is
        # not cooking.
        if self.entity_description.key in ("problem", "cooking"):
            return self.appliance.on_account
        return super().available

    @property
    def is_on(self) -> bool | None:
        appliance = self.appliance
        if (
            self.entity_description.key == "cooking"
            and not (self.coordinator.connected and appliance.status.online)
        ):
            # Cooking when contact went: unknown until it answers (the status
            # sensor's offline_reason says so). Otherwise off.
            cook = appliance.last_cook
            return None if cook is not None and not cook.get("ended_at") else False
        return self.entity_description.value_fn(appliance)
