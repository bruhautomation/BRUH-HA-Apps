"""GardenRX sensors.

Each sensor's state is the one number a person would put on a dashboard, and
its attributes carry what the GardenRX cards draw: the cards find a sensor by
its `gardenrx` attribute rather than by entity id, so a renamed entity keeps
its card. The long lists are kept out of the recorder — a database row per
poll of every recent harvest would be history nobody asked for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_KIND, DOMAIN, VERSION
from .coordinator import GardenRxCoordinator


@dataclass(frozen=True, kw_only=True)
class GardenRxSensorDescription(SensorEntityDescription):
    kind: str
    value: Callable[[dict], Any]
    attrs: Callable[[dict], dict[str, Any]]


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _harvest_attrs(d: dict) -> dict[str, Any]:
    h = d.get("harvest") or {}
    return {
        "year": h.get("year"),
        "total_value": h.get("total_value"),
        "picks": h.get("picks"),
        "by_crop": h.get("by_crop", []),
        "recent": h.get("recent", []),
        "units": h.get("units", []),
        "crops": d.get("crops", []),
    }


def _spray_attrs(d: dict) -> dict[str, Any]:
    s = d.get("sprays") or {}
    last = s.get("last") or {}
    return {
        "days_ago": last.get("days_ago"),
        "products": last.get("products", []),
        "crops": last.get("crops", []),
        "this_year": s.get("this_year"),
        "recent": s.get("recent", []),
        "queued": s.get("queued", []),
        "phi": (d.get("phi") or {}).get("crops", []),
    }


SENSORS: tuple[GardenRxSensorDescription, ...] = (
    GardenRxSensorDescription(
        key="harvest_season",
        translation_key="harvest_season",
        kind="harvest",
        native_unit_of_measurement="lb",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        value=lambda d: (d.get("harvest") or {}).get("total_lb"),
        attrs=_harvest_attrs,
    ),
    GardenRxSensorDescription(
        key="harvest_value",
        translation_key="harvest_value",
        kind="harvest_value",
        native_unit_of_measurement="USD",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value=lambda d: (d.get("harvest") or {}).get("total_value"),
        attrs=lambda d: {"year": (d.get("harvest") or {}).get("year")},
    ),
    GardenRxSensorDescription(
        key="last_spray",
        translation_key="last_spray",
        kind="sprays",
        device_class=SensorDeviceClass.DATE,
        value=lambda d: _date(((d.get("sprays") or {}).get("last") or {}).get("date")),
        attrs=_spray_attrs,
    ),
    GardenRxSensorDescription(
        key="queued_sprays",
        translation_key="queued_sprays",
        kind="queued",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: len((d.get("sprays") or {}).get("queued", [])),
        attrs=lambda d: {"queued": (d.get("sprays") or {}).get("queued", [])},
    ),
    GardenRxSensorDescription(
        key="pre_harvest_intervals",
        translation_key="pre_harvest_intervals",
        kind="phi",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: (d.get("phi") or {}).get("active_count"),
        attrs=lambda d: {"crops": (d.get("phi") or {}).get("crops", [])},
    ),
    GardenRxSensorDescription(
        key="low_stock",
        translation_key="low_stock",
        kind="inventory",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda d: (d.get("inventory") or {}).get("low_count"),
        attrs=lambda d: {"items": (d.get("inventory") or {}).get("items", [])},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: GardenRxCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(GardenRxSensor(coordinator, entry, desc) for desc in SENSORS)


class GardenRxSensor(CoordinatorEntity[GardenRxCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset(
        {"by_crop", "recent", "crops", "units", "queued", "phi", "items", "products"}
    )
    entity_description: GardenRxSensorDescription

    def __init__(
        self, coordinator: GardenRxCoordinator, entry: ConfigEntry, desc: GardenRxSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        self._attr_unique_id = f"{DOMAIN}_{desc.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="GardenRX",
            manufacturer="BRUH Automation",
            model="GardenRX add-on",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return {ATTR_KIND: self.entity_description.kind, **self.entity_description.attrs(data)}
