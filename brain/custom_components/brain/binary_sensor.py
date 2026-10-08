"""System health binary sensor for brAIn.

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
from .learning import read_open_hypotheses
from .status_mirror import STATUS_FILENAME
from .status_mirror import count as status_count

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
        [
            BruhClaudeHealthSensor(config_entry, bridge),
            BrainNeedsYouSensor(config_entry),
            BrainWantsInputSensor(config_entry),
        ],
        update_before_add=True,
    )


class BruhClaudeHealthSensor(BinarySensorEntity):
    """On when the assist worker pool answers (HTTP first, heartbeat file second)."""

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Assist healthy"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "system_health")},
        name="brAIn System",
        manufacturer="BRUH Automation",
        model="brAIn add-on",
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


class BrainNeedsYouSensor(BinarySensorEntity):
    """`binary_sensor.brain_needs_you`: on while the queue is not empty.

    The queue is the panel's one list of decisions — open findings, open
    questions and open suggestions — and its length is counted in one
    place (`cases.queue_count`) and published in the status mirror, so
    this is on exactly when the Today badge shows a number. It replaces
    the old "Waiting on you" sensor as the thing to automate "brAIn needs
    me" on: that one only ever counted the guesses, which is why it is
    now called what it counts ("Questions waiting").

    A mirror that is missing or stale reads as unknown with the reason —
    never "off", because "nothing needs you" is the one wrong answer that
    hides a problem.
    """

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Needs you"
    _attr_icon = "mdi:account-alert-outline"
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "system_health")},
        name="brAIn System",
        manufacturer="BRUH Automation",
        model="brAIn add-on",
    )

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_needs_you"
        # Asked for by name, for the reason `sensor.brain_status` is.
        self.entity_id = "binary_sensor.brain_needs_you"
        self._attr_is_on = None
        self._count: int | None = None
        self._reason = "not read yet"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"count": self._count}
        if self._reason:
            attrs["reason"] = self._reason
        return attrs

    def update(self) -> None:
        try:
            value, reason = status_count(
                self.hass.config.path(SHARED_DIR, STATUS_FILENAME),
                "queue_count")
        except Exception:  # noqa: BLE001 — a sensor must not take HA down
            _LOGGER.debug("could not read the status mirror", exc_info=True)
            value, reason = None, "the status file could not be read"
        self._count = value
        self._reason = reason
        self._attr_is_on = None if value is None else value > 0


class BrainWantsInputSensor(BinarySensorEntity):
    """On when brAIn has a guess waiting on a yes/no.

    This exists to be *automatable*. A guess sitting in a panel nobody has
    open is a guess that expires unanswered; a binary sensor can push it to
    a phone, where answering costs one tap.

    It was called "Waiting on you", which read as the whole queue while it
    counted only the guesses — `binary_sensor.brain_needs_you` is the
    queue now. The unique id is unchanged so its history, its entity id
    and every automation built on its `questions` attribute keep working.
    """

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Questions waiting"
    _attr_icon = "mdi:comment-question-outline"
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "brain_memory")},
        name="brAIn Memory",
        manufacturer="BRUH Automation",
        model="Home memory",
    )

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_wants_input"
        self._attr_is_on = False
        self._pending: list[dict] = []

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # The text is the point — an automation that only knows "something is
        # pending" can't put the actual question on a lock screen. The id is
        # the other half: it is what `brain.answer_question` takes, so a
        # notification's Yes/No can name the guess it was about rather than
        # matching its sentence back.
        return {
            "pending": [h["text"] for h in self._pending],
            "questions": [{"ts": h["ts"], "text": h["text"],
                           "topic": h.get("topic") or ""}
                          for h in self._pending],
            "count": len(self._pending),
            "oldest": self._pending[0]["text"] if self._pending else None,
            "oldest_ts": self._pending[0]["ts"] if self._pending else None,
        }

    def update(self) -> None:
        try:
            self._pending = read_open_hypotheses(self.hass)
        except Exception:  # noqa: BLE001 — a sensor must not take HA down
            _LOGGER.debug("could not read the hypothesis queue", exc_info=True)
            self._pending = []
        self._attr_is_on = bool(self._pending)
