"""Sensors for Breville+ appliances."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import BrevilleConfigEntry
from .appliance import ERROR_OPTIONS, MODEL_BOV950, REPORTED_MODE_OPTIONS, CookState
from .const import BRAND_SAGE, CONF_BRAND
from .coordinator import (
    CONNECTION_STATES,
    Appliance,
    BrevilleCoordinator,
    account_identifier,
)
from .entity import BrevilleEntity, async_add_appliance_entities

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BrevilleSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Appliance], StateType | datetime]
    models: frozenset[str] | None = None
    always_available: bool = False


SENSORS: tuple[BrevilleSensorDescription, ...] = (
    BrevilleSensorDescription(
        key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[state.value for state in CookState],
        value_fn=lambda a: a.status.state.value,
        always_available=True,
    ),
    BrevilleSensorDescription(
        key="current_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda a: a.status.current_temp_c,
    ),
    BrevilleSensorDescription(
        key="preheat",
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda a: a.status.preheat_pct,
    ),
    BrevilleSensorDescription(
        key="time_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda a: a.status.time_remaining_s,
    ),
    BrevilleSensorDescription(
        key="cook_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda a: a.status.ends_at,
    ),
    BrevilleSensorDescription(
        key="active_mode",
        device_class=SensorDeviceClass.ENUM,
        options=REPORTED_MODE_OPTIONS,
        models=frozenset({MODEL_BOV950}),
        value_fn=lambda a: a.status.mode if a.status.active else None,
    ),
    BrevilleSensorDescription(
        key="error",
        device_class=SensorDeviceClass.ENUM,
        options=ERROR_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda a: a.status.error,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BrevilleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([BrevilleAccountSensor(entry.runtime_data)])
    async_add_appliance_entities(
        entry,
        async_add_entities,
        lambda coordinator, appliance: (
            BrevilleSensor(coordinator, appliance, description)
            for description in SENSORS
            if description.models is None or appliance.model in description.models
        ),
    )


class BrevilleAccountSensor(CoordinatorEntity[BrevilleCoordinator], SensorEntity):
    """How the Breville account stands: the connection, as the state; the appliances
    found, the last good poll, and any appliance on the account that is not driven
    (with the reason), as attributes. Never the email or a token."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "account"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONNECTION_STATES

    def __init__(self, coordinator: BrevilleCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        brand = "Sage" if entry.data.get(CONF_BRAND) == BRAND_SAGE else "Breville"
        self._attr_unique_id = f"account_{entry.entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={account_identifier(entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer=brand,
            name=f"{brand} account",
        )

    @property
    def available(self) -> bool:
        # It says how the connection stands, including when it is down.
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.connection

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self.coordinator.account_summary()
        summary.pop("connection")
        return summary


class BrevilleSensor(BrevilleEntity, SensorEntity):
    entity_description: BrevilleSensorDescription

    def __init__(self, coordinator, appliance, description: BrevilleSensorDescription) -> None:
        super().__init__(coordinator, appliance, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        if self.entity_description.key == "status":
            # Offline is what this sensor says, with the reason as attributes.
            return self.appliance.on_account
        if self.entity_description.always_available:
            return self.cloud_available
        return super().available

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "status":
            return None
        appliance = self.appliance
        attrs: dict[str, Any] = {
            "last_contact": appliance.last_contact.isoformat(timespec="seconds")
            if appliance.last_contact
            else None,
            "last_cook": appliance.last_cook,
        }
        if (report := self.coordinator.offline_report(appliance)) is not None:
            attrs["offline_cause"] = report["cause"]
            attrs["offline_since"] = report["since"]
            attrs["offline_reason"] = report["text"]
        return attrs

    @property
    def native_value(self) -> StateType | datetime:
        if self.entity_description.key == "status" and not self.cloud_available:
            return CookState.OFFLINE.value
        return self.entity_description.value_fn(self.appliance)
