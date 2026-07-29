"""System health binary sensor for BRain.

Reports whether the add-on's assist channel is alive. Primary source is the
worker pool's /health endpoint (fast mode); falls back to the heartbeat file
the pool writes on the shared volume, so it still works when the HTTP API
can't be reached. Classic-listener installs (no pool) show unavailable
rather than a misleading "off".
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, POOL_STATUS_FILENAME, SHARED_DIR

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=60)

# Heartbeat is written at least every 30s; allow generous slack.
HEARTBEAT_FRESH_S = 150


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the health sensor (account-wide, once)."""
    domain_data = hass.data.get(DOMAIN, {})
    if domain_data.get("_health_added"):
        return
    domain_data["_health_added"] = True
    domain_data["_health_entry"] = config_entry.entry_id

    bridge = domain_data.get(config_entry.entry_id)
    async_add_entities(
        [BruhClaudeHealthSensor(config_entry, bridge)], update_before_add=True
    )


class BruhClaudeHealthSensor(BinarySensorEntity):
    """On when the assist worker pool answers (HTTP first, heartbeat file second)."""

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Assist healthy"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "system_health")},
        name="BRain System",
        manufacturer="BRUH Automation",
        model="Claude Terminal",
    )

    def __init__(self, config_entry: ConfigEntry, bridge) -> None:
        self._bridge = bridge
        self._attr_unique_id = f"{DOMAIN}_assist_healthy"
        self._status: dict[str, Any] = {}
        self._transport: str | None = None
        self._attr_is_on = False
        self._seen_any = False

    @property
    def available(self) -> bool:
        # Hide the sensor until the pool has ever reported (classic-listener
        # installs would otherwise show a misleading permanent "off").
        return self._seen_any

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"transport": self._transport}
        for key in ("workers", "spare_ready", "uptime_s", "tool_access"):
            if key in self._status:
                attrs[key] = self._status[key]
        last = self._status.get("last_request") or {}
        if last:
            attrs["last_request_duration_s"] = last.get("duration_s")
            attrs["last_request_mode"] = last.get("mode")
        return attrs

    async def async_update(self) -> None:
        if self._bridge is not None:
            health = await self._bridge.async_api_health()
            if health:
                self._status = health
                self._transport = "http"
                self._attr_is_on = health.get("status") == "ok"
                self._seen_any = True
                return

        status = await self.hass.async_add_executor_job(self._read_heartbeat)
        if status is not None:
            self._seen_any = True
            self._status = status
            self._transport = "file"
            age = time.time() - (status.get("ts") or 0)
            self._attr_is_on = age < HEARTBEAT_FRESH_S
        elif self._seen_any:
            self._transport = None
            self._attr_is_on = False

    def _read_heartbeat(self) -> dict | None:
        path = self.hass.config.path(SHARED_DIR, POOL_STATUS_FILENAME)
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None
