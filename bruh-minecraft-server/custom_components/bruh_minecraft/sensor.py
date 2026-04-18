"""Sensor platform for BRUH Minecraft."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BruhMinecraftCoordinator
from .entity import BruhMinecraftEntity


@dataclass(frozen=True, kw_only=True)
class BruhSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict, dict], object]


SENSORS: tuple[BruhSensorDescription, ...] = (
    BruhSensorDescription(
        key="players_online",
        name="Players online",
        icon="mdi:account-group",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats, state: stats.get("online", 0),
    ),
    BruhSensorDescription(
        key="players_max",
        name="Max players",
        icon="mdi:account-multiple",
        value_fn=lambda stats, state: stats.get("max_players") or state.get("max_players"),
    ),
    BruhSensorDescription(
        key="tps_1m",
        name="TPS (1m)",
        icon="mdi:speedometer",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats, state: stats.get("tps_1m"),
    ),
    BruhSensorDescription(
        key="tps_5m",
        name="TPS (5m)",
        icon="mdi:speedometer-medium",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats, state: stats.get("tps_5m"),
    ),
    BruhSensorDescription(
        key="tps_15m",
        name="TPS (15m)",
        icon="mdi:speedometer-slow",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda stats, state: stats.get("tps_15m"),
    ),
    BruhSensorDescription(
        key="latency_ms",
        name="Latency",
        icon="mdi:timer-outline",
        native_unit_of_measurement="ms",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats, state: stats.get("latency_ms"),
    ),
    BruhSensorDescription(
        key="uptime",
        name="Uptime",
        icon="mdi:clock-outline",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda stats, state: stats.get("uptime_seconds"),
    ),
    BruhSensorDescription(
        key="version",
        name="Version",
        icon="mdi:package-variant",
        value_fn=lambda stats, state: stats.get("version") or state.get("minecraft_version"),
    ),
    BruhSensorDescription(
        key="server_type",
        name="Server type",
        icon="mdi:minecraft",
        value_fn=lambda stats, state: state.get("server_type"),
    ),
    BruhSensorDescription(
        key="motd",
        name="MOTD",
        icon="mdi:message-text",
        value_fn=lambda stats, state: state.get("motd") or stats.get("motd"),
    ),
    BruhSensorDescription(
        key="difficulty",
        name="Difficulty",
        icon="mdi:shield-sword",
        value_fn=lambda stats, state: state.get("difficulty"),
    ),
    BruhSensorDescription(
        key="gamemode",
        name="Default gamemode",
        icon="mdi:gamepad-variant",
        value_fn=lambda stats, state: state.get("gamemode"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BruhMinecraftCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(BruhSensor(coordinator, d) for d in SENSORS)


class BruhSensor(BruhMinecraftEntity, SensorEntity):
    entity_description: BruhSensorDescription

    def __init__(
        self,
        coordinator: BruhMinecraftCoordinator,
        description: BruhSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):  # type: ignore[override]
        try:
            return self.entity_description.value_fn(self.stats, self.state_info)
        except Exception:  # noqa: BLE001
            return None

    @property
    def extra_state_attributes(self) -> dict:
        if self.entity_description.key == "players_online":
            return {"players": self.stats.get("players", [])}
        if self.entity_description.key == "version":
            return {"brand": self.stats.get("version_brand")}
        return {}
