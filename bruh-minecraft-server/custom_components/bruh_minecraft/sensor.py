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

from . import worldview
from .const import DOMAIN
from .coordinator import BruhMinecraftCoordinator
from .entity import BruhMinecraftEntity


@dataclass(frozen=True, kw_only=True)
class BruhSensorDescription(SensorEntityDescription):
    # From the server's stats and state (stats.json, state.json) ...
    value_fn: Callable[[dict, dict], object] | None = None
    # ... or from the world (world.json): value and attributes.
    world_fn: Callable[[dict], object] | None = None
    world_attrs_fn: Callable[[dict], dict] | None = None


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
    # What is going on in the world (#573), from panel/mcworld.py.
    BruhSensorDescription(
        key="world_time",
        name="World time",
        icon="mdi:weather-sunset",
        world_fn=worldview.time_state,
        world_attrs_fn=worldview.time_attrs,
    ),
    BruhSensorDescription(
        key="world_day",
        name="World day",
        icon="mdi:calendar-today",
        world_fn=worldview.day_state,
    ),
    BruhSensorDescription(
        key="world_weather",
        name="World weather",
        icon="mdi:weather-partly-rainy",
        world_fn=worldview.weather_state,
        world_attrs_fn=worldview.weather_attrs,
    ),
    BruhSensorDescription(
        key="world_feed",
        name="World feed",
        icon="mdi:script-text-outline",
        world_fn=worldview.feed_state,
        world_attrs_fn=worldview.feed_attrs,
    ),
    BruhSensorDescription(
        key="last_save",
        name="Last save",
        icon="mdi:content-save-outline",
        device_class=SensorDeviceClass.TIMESTAMP,
        world_fn=worldview.last_save,
    ),
    BruhSensorDescription(
        key="last_backup",
        name="Last backup",
        icon="mdi:backup-restore",
        device_class=SensorDeviceClass.TIMESTAMP,
        world_fn=worldview.last_backup,
    ),
    BruhSensorDescription(
        key="vesper_building",
        name="Vesper building",
        icon="mdi:hammer-wrench",
        world_fn=worldview.building_state,
        world_attrs_fn=worldview.building_attrs,
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
    # Where everybody is and the feed move every few seconds while people
    # play; the state is what history wants, these are for the card.
    _unrecorded_attributes = frozenset({"details", "events", "last_seen", "recent", "current"})

    def __init__(
        self,
        coordinator: BruhMinecraftCoordinator,
        description: BruhSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def world(self) -> dict:
        return (self.coordinator.data or {}).get("world") or {}

    @property
    def available(self) -> bool:  # type: ignore[override]
        # A world sensor has nothing to say until the add-on writes world.json.
        if self.entity_description.world_fn is not None and not self.world:
            return False
        return bool(getattr(self.coordinator, "last_update_success", True))

    @property
    def native_value(self):  # type: ignore[override]
        d = self.entity_description
        try:
            if d.world_fn is not None:
                return d.world_fn(self.world)
            return d.value_fn(self.stats, self.state_info)
        except Exception:  # noqa: BLE001
            return None

    @property
    def extra_state_attributes(self) -> dict:
        d = self.entity_description
        if d.world_attrs_fn is not None:
            try:
                return d.world_attrs_fn(self.world)
            except Exception:  # noqa: BLE001
                return {}
        if d.key == "players_online":
            attrs = {"players": self.stats.get("players", [])}
            if self.world:
                attrs.update(worldview.players_attrs(self.world))
            return attrs
        if self.entity_description.key == "version":
            return {"brand": self.stats.get("version_brand")}
        return {}
