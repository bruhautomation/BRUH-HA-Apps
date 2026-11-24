"""Binary sensors for Breville+ appliances."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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
        # offline: the last error seen stands, and cooking keeps what it was
        # when contact went.
        if self.entity_description.key in ("problem", "cooking"):
            return self.appliance.on_account
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        key = self.entity_description.key
        if key == "cooking" and not self.coordinator.in_contact(self.appliance):
            return self.coordinator.last_known(self.appliance)
        if key == "problem" and self.appliance.status.error == "none" and self.is_on:
            # On with no error reported: the appliance has been out of contact.
            # Why, and what to try, on the entity that is on, so a person reads
            # it on the card; the same report as the status sensor's, written
            # as a state attribute is (the time, not how long ago).
            attrs: dict[str, Any] = {"cause": "offline"}
            if (report := self.coordinator.offline_report(self.appliance, live=False)) is not None:
                attrs["reason"] = report["text"]
                attrs["to_try"] = report["to_try"]
            return attrs
        return None

    @property
    def is_on(self) -> bool | None:
        appliance = self.appliance
        if self.entity_description.key == "cooking" and not self.coordinator.in_contact(appliance):
            # The last known value, marked as old: on when a cook was open as
            # contact went (the status sensor's offline_reason says it may have
            # ended since), otherwise off.
            cook = appliance.last_cook
            return cook is not None and not cook.get("ended_at")
        if self.entity_description.key == "problem" and self.coordinator.offline_problem(appliance):
            # Out of contact past OFFLINE_PROBLEM_AFTER is a problem too; its
            # reason and to_try attributes say since when, why and what to try.
            return True
        return self.entity_description.value_fn(appliance)
