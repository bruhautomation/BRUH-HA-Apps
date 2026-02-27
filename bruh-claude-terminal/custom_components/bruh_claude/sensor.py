"""Anthropic usage limit sensors for BRUH Claude.

Reads real Anthropic account usage limits from usage-limits-tracker.py,
then exposes them as Home Assistant sensors.

These sensors are account-level — one set total, not per conversation agent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SHARED_DIR

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

USAGE_LIMITS_FILENAME = "usage_limits.json"

# Device that groups Anthropic usage limit sensors together.
USAGE_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "usage_limits")},
    name="BRUH Claude Usage Limits",
    manufacturer="BRUH Automation",
    model="Claude Terminal",
)


# ---------------------------------------------------------------------------
# Sensor descriptions — Anthropic usage limits (real account data)
# ---------------------------------------------------------------------------

# (key, name, icon, unit, state_class, device_class, period_key, value_key)
USAGE_LIMIT_TYPES: list[
    tuple[str, str, str, str | None, SensorStateClass | None, SensorDeviceClass | None, str, str]
] = [
    ("session_usage_percent", "Session Usage", "mdi:gauge", "%", None, None, "five_hour", "utilization"),
    ("session_usage_reset", "Session Usage Resets At", "mdi:timer-sand", None, None, SensorDeviceClass.TIMESTAMP, "five_hour", "resets_at"),
    ("weekly_usage_percent", "Weekly Usage", "mdi:gauge", "%", None, None, "seven_day", "utilization"),
    ("weekly_usage_reset", "Weekly Usage Resets At", "mdi:calendar-clock", None, None, SensorDeviceClass.TIMESTAMP, "seven_day", "resets_at"),
]


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up BRUH Claude sensors (once, not per conversation)."""
    domain_data = hass.data.get(DOMAIN, {})

    # Guard: sensors are account-wide — only create them from the first entry.
    if domain_data.get("_sensors_added"):
        return
    domain_data["_sensors_added"] = True
    domain_data["_sensors_entry"] = config_entry.entry_id

    entities: list[SensorEntity] = []

    # Anthropic usage limit sensors (real account data from API)
    usage_path = hass.config.path(SHARED_DIR, USAGE_LIMITS_FILENAME)
    for key, name, icon, unit, state_cls, device_cls, period, value_key in USAGE_LIMIT_TYPES:
        entities.append(
            BruhClaudeUsageLimitSensor(
                config_entry=config_entry,
                usage_path=usage_path,
                sensor_key=key,
                sensor_name=name,
                sensor_icon=icon,
                sensor_unit=unit,
                sensor_state_class=state_cls,
                sensor_device_class=device_cls,
                period_key=period,
                value_key=value_key,
            )
        )

    async_add_entities(entities, update_before_add=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO timestamp string to a timezone-aware datetime."""
    try:
        if isinstance(value, str):
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except (ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Anthropic usage limit sensor entity
# ---------------------------------------------------------------------------

class BruhClaudeUsageLimitSensor(SensorEntity):
    """A sensor that reads real Anthropic account usage limits.

    Data is fetched by the add-on's usage-limits-tracker.py script,
    which queries the Anthropic API and writes to usage_limits.json.
    """

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(
        self,
        config_entry: ConfigEntry,
        usage_path: str,
        sensor_key: str,
        sensor_name: str,
        sensor_icon: str,
        sensor_unit: str | None,
        sensor_state_class: SensorStateClass | None,
        sensor_device_class: SensorDeviceClass | None,
        period_key: str,
        value_key: str,
    ) -> None:
        self._usage_path = usage_path
        self._period_key = period_key
        self._value_key = value_key
        self._is_timestamp = sensor_device_class == SensorDeviceClass.TIMESTAMP
        self._attr_name = sensor_name
        self._attr_unique_id = f"{DOMAIN}_{sensor_key}"
        self._attr_icon = sensor_icon
        self._attr_native_unit_of_measurement = sensor_unit
        self._attr_state_class = sensor_state_class
        self._attr_device_class = sensor_device_class
        self._attr_device_info = USAGE_DEVICE_INFO
        self._attr_native_value: float | int | datetime | None = None
        self._usage_data: dict[str, Any] = {}

    @property
    def available(self) -> bool:
        """Return True if the usage data is available (no API errors)."""
        if not self._usage_data:
            return False
        if "error" in self._usage_data:
            return False
        return self._period_key in self._usage_data

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose extra detail from the usage limits data."""
        attrs: dict[str, Any] = {}
        period_data = self._usage_data.get(self._period_key, {})

        # Include the complementary field as an attribute
        if self._value_key == "utilization":
            resets_at = period_data.get("resets_at")
            if resets_at:
                attrs["resets_at"] = resets_at
        elif self._value_key == "resets_at":
            util = period_data.get("utilization")
            if util is not None:
                attrs["utilization"] = util

        # Data source info
        source = self._usage_data.get("source")
        if source:
            attrs["data_source"] = source
        updated = self._usage_data.get("updated_at")
        if updated:
            attrs["last_updated"] = updated

        error = self._usage_data.get("error")
        if error:
            attrs["error"] = error

        return attrs

    async def async_update(self) -> None:
        """Read the usage limits file and update the sensor value."""
        data = await self.hass.async_add_executor_job(self._read_usage)
        if data is None:
            return
        self._usage_data = data
        period_data = data.get(self._period_key, {})
        value = period_data.get(self._value_key)
        if value is not None:
            if self._is_timestamp:
                self._attr_native_value = _parse_timestamp(value)
            else:
                self._attr_native_value = value

    def _read_usage(self) -> dict | None:
        """Read the usage limits JSON file from disk."""
        if not os.path.isfile(self._usage_path):
            return None
        try:
            with open(self._usage_path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            _LOGGER.debug("Could not read usage limits: %s", exc)
            return None
