"""Anthropic usage limit sensors for brAIn.

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
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import (
    CONF_INSIGHT_TEMPLATE,
    DOMAIN,
    ENTRY_TYPE_INSIGHT,
    SHARED_DIR,
    SIGNAL_INSIGHT_UPDATE,
)
from .insight_format import build_card_yaml, make_preview

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)

USAGE_LIMITS_FILENAME = "usage_limits.json"

# A reading the tracker stopped refreshing is not a reading. It polls every
# half hour, so anything this old means it is failing or not running, and
# reporting last night's utilization as if it were now is the one answer
# worse than "unavailable". Same window the panel's usage_store applies to
# the same file. The tracker's 429 backoff waits are deliberately longer
# than this window, so during a rate-limit wall these sensors WILL go
# unavailable — the diagnostic sensor below reads the tracker's recorded
# ``last_error`` so that moment arrives with its reason attached.
USAGE_STALE_AFTER = timedelta(hours=2)

# Device that groups Anthropic usage limit sensors together.
USAGE_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "usage_limits")},
    name="brAIn Usage Limits",
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
    """Set up brAIn sensors (once, not per conversation)."""
    from . import entry_type, load_insight_payload  # local import: avoid cycle

    if entry_type(config_entry) == ENTRY_TYPE_INSIGHT:
        async_add_entities([
            BruhClaudeInsightSensor(hass, config_entry, load_insight_payload)
        ])
        return

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

    # Why the four above are unavailable, when they are. Four entities that
    # vanish with no stated reason send people to redo a working sign-in;
    # this one never goes unavailable, because its whole job is to be
    # readable at the moment the others are not.
    entities.append(
        BrainUsageTrackerSensor(config_entry=config_entry, usage_path=usage_path)
    )

    # What brAIn knows, and when it last learned something.
    entities.append(BrainFactsSensor(config_entry))
    entities.append(BrainLastLearnedSensor(config_entry))

    # What brAIn thinks is broken, countable from an automation.
    entities.append(BrainOpenFindingsSensor(config_entry))

    async_add_entities(entities, update_before_add=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reading_age(data: dict[str, Any]) -> timedelta | None:
    """How long ago the tracker wrote this file, or None if it won't say."""
    when = _parse_timestamp(data.get("updated_at", ""))
    if when is None:
        return None
    return datetime.now(timezone.utc) - when


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
        # An absent or unparseable timestamp is reported as no timestamp; the
        # sensor renders without one rather than going unavailable.
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
        """Return True if the usage data is available, current, and clean."""
        if not self._usage_data:
            return False
        if "error" in self._usage_data:
            return False
        if self._period_key not in self._usage_data:
            return False
        age = _reading_age(self._usage_data)
        return age is not None and age < USAGE_STALE_AFTER

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
            # File deleted or unreadable: go unavailable (like the pool
            # binary_sensor does) instead of reporting the last value as
            # live data forever.
            self._usage_data = {}
            self._attr_native_value = None
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


class BrainUsageTrackerSensor(SensorEntity):
    """Whether the usage tracker is working, and what stopped it if not.

    States are the tracker's own vocabulary, so the state answers the
    question instead of prompting another one:

      ``ok``                            reporting real numbers
      ``no_oauth_token``                nobody has signed in yet
      ``api_key_has_no_usage_limits``   signed in with an API key, which
                                        bills per token and has no window
      ``http_401``                      the token was found and refused
      ``http_429``                      the usage endpoint is rate-limiting
                                        the poll — nothing to do with the
                                        account's own usage; brAIn backs off
      ``network_error`` / ``http_5xx``  Anthropic unreachable right now
      ``stale``                         last reading is too old to trust,
                                        and the tracker recorded no reason
      ``not_running``                   no file at all — tracker never wrote

    A status the tracker can gloss arrives with a ``detail`` attribute, and
    the codes that most need one are the codes people read as something
    else: ``http_429`` is the endpoint's limit, not a usage cap.

    A reading that went stale *because* the tracker is waiting out a
    failure reports that failure, not ``stale``: the tracker leaves
    ``last_error`` beside a reading it deliberately did not overwrite, and
    the moment the reading ages out is exactly the moment the reason is
    needed. During a 429 backoff — whose waits are longer than the
    staleness window on purpose — that is the difference between four
    sensors going unavailable with an explanation and without one. While
    the reading is still fresh the failure is a ``note``, because the
    numbers on show are still the honest answer. ``next_attempt_at`` says
    when the tracker will ask again, in every state that has one.
    """

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Usage tracker"
    _attr_icon = "mdi:cloud-question-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_device_info = USAGE_DEVICE_INFO

    def __init__(self, config_entry: ConfigEntry, usage_path: str) -> None:
        self._entry = config_entry
        self._usage_path = usage_path
        self._attr_unique_id = f"{DOMAIN}_usage_tracker_status"
        self._attr_native_value = "not_running"
        self._attrs: dict[str, Any] = {}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    async def async_update(self) -> None:
        data = await self.hass.async_add_executor_job(self._read)
        if data is None:
            self._attr_native_value = "not_running"
            self._attrs = {"detail": "the tracker has not written a reading yet"}
            return

        attrs: dict[str, Any] = {}
        updated = data.get("updated_at")
        if updated:
            attrs["last_updated"] = updated
        next_attempt = data.get("next_attempt_at")
        if next_attempt:
            attrs["next_attempt_at"] = next_attempt

        error = data.get("error")
        if error:
            detail = data.get("detail")
            if detail:
                attrs["detail"] = str(detail)
            self._attr_native_value = str(error)
            self._attrs = attrs
            return

        last_error = data.get("last_error")
        last_error = last_error if isinstance(last_error, str) else None
        last_detail = data.get("last_error_detail")

        age = _reading_age(data)
        if age is None or age >= USAGE_STALE_AFTER:
            # Stale with a recorded reason IS that reason — "stale" alone is
            # the state that sent people here not understanding why.
            if last_error:
                self._attr_native_value = last_error
                if last_detail:
                    attrs["detail"] = str(last_detail)
            else:
                self._attr_native_value = "stale"
        else:
            self._attr_native_value = "ok"
            if last_error:
                attrs["note"] = (
                    f"last poll failed ({last_error}); showing the previous "
                    "reading until it ages out"
                )
                if last_detail:
                    attrs["detail"] = str(last_detail)
        self._attrs = attrs

    def _read(self) -> dict | None:
        if not os.path.isfile(self._usage_path):
            return None
        try:
            with open(self._usage_path) as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            _LOGGER.debug("Could not read usage limits: %s", exc)
            return None
        return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Insight job sensor
# ---------------------------------------------------------------------------

class BruhClaudeInsightSensor(SensorEntity):
    """Holds the latest result of one insight job.

    State is the last successful run time; the generated markdown lives in
    attributes (kept out of the recorder — it can be sizeable and the live
    state machine is all a dashboard card needs).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:lightbulb-on-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _unrecorded_attributes = frozenset({"markdown", "card_yaml"})

    def __init__(self, hass, config_entry: ConfigEntry, loader) -> None:
        self.hass = hass
        self._entry = config_entry
        self._loader = loader
        self._payload: dict[str, Any] = {}
        self._attr_name = "Insight"
        self._attr_unique_id = f"{config_entry.entry_id}_insight"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"insight_{config_entry.entry_id}")},
            name=config_entry.title,
            manufacturer="BRUH Automation",
            model="Claude Insight Job",
        )

    async def async_added_to_hass(self) -> None:
        # Restore the last persisted result so restarts don't blank the card
        payload = await self.hass.async_add_executor_job(
            self._loader, self.hass, self._entry.entry_id
        )
        if payload:
            self._apply(payload)
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_INSIGHT_UPDATE.format(self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, payload: dict) -> None:
        # Must be a @callback: async_dispatcher_connect treats an
        # undecorated sync target as an executor job (HassJobType.Executor),
        # so async_write_ha_state() would run off the event loop and trip
        # HA's thread-safety guard. @callback runs it inline on the loop.
        self._apply(payload)
        self.async_write_ha_state()

    def _apply(self, payload: dict) -> None:
        # Errors keep the previous markdown so the card never goes blank
        previous_markdown = self._payload.get("markdown")
        merged = {**self._payload, **payload}
        if payload.get("error") and previous_markdown and not payload.get("markdown"):
            merged["markdown"] = previous_markdown
        self._payload = merged
        self._attr_native_value = _parse_timestamp(merged.get("last_success"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        opts = {**self._entry.data, **self._entry.options}
        # Short/readable first; the long blobs (full report, card YAML) last
        return {
            "preview": make_preview(self._payload.get("markdown")),
            "error": self._payload.get("error"),
            "duration_s": self._payload.get("duration_s"),
            "template": opts.get(CONF_INSIGHT_TEMPLATE),
            "markdown": self._payload.get("markdown"),
            "card_yaml": build_card_yaml(
                self.entity_id or "sensor.insight", self._entry.title
            ),
        }


# ---------------------------------------------------------------------------
# Learning sensors — memory made visible outside the panel
# ---------------------------------------------------------------------------

MEMORY_DEVICE_INFO = DeviceInfo(
    identifiers={(DOMAIN, "brain_memory")},
    name="brAIn memory",
    manufacturer="BRUH Automation",
    model="Home memory",
)


class BrainFactsSensor(SensorEntity):
    """How much brAIn currently knows about this home.

    Counted from the change log rather than by parsing the document, so a
    hand-edited memory file can never make the number disagree with the
    history behind it.
    """

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Facts learned"
    _attr_icon = "mdi:brain"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "facts"
    _attr_device_info = MEMORY_DEVICE_INFO

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_facts_learned"
        self._attr_native_value = 0

    def update(self) -> None:
        from .learning import total_learned
        try:
            self._attr_native_value = total_learned(self.hass)
        except Exception:  # noqa: BLE001 — never take HA down over a sensor
            _LOGGER.debug("could not count learned facts", exc_info=True)


class BrainOpenFindingsSensor(SensorEntity):
    """How many findings are waiting on the homeowner, with what they are.

    This exists to be *automatable* — the panel's badge answers the same
    question, but a badge cannot ring a phone at a sensible hour or sit on
    a dashboard. State is the open count; the attributes carry the severity
    split and the texts, because an automation that only knows "3" cannot
    put what is actually broken on a lock screen.

    Reads the mirror the add-on republishes on every findings change
    (`findings.py`); unavailable until the add-on has ever written one,
    which is what tells a fresh install apart from a clean bill of health.
    """

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Open findings"
    _attr_icon = "mdi:home-alert"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "findings"
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "brain_findings")},
        name="brAIn findings",
        manufacturer="BRUH Automation",
        model="Home findings",
    )

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_open_findings"
        self._attr_native_value = 0
        self._state: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        return self._state is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._state or {}
        by_sev = state.get("by_severity") or {}
        rows = state.get("findings") or []
        return {
            "critical": int(by_sev.get("critical") or 0),
            "serious": int(by_sev.get("serious") or 0),
            "warning": int(by_sev.get("warning") or 0),
            "info": int(by_sev.get("info") or 0),
            "findings": [str(f.get("text") or "") for f in rows[:20]],
            "newest": str(rows[0].get("text") or "") if rows else None,
        }

    def update(self) -> None:
        from .findings import read_findings_state
        try:
            state = read_findings_state(self.hass)
        except Exception:  # noqa: BLE001 — never take HA down over a sensor
            _LOGGER.debug("could not read the findings mirror", exc_info=True)
            return
        if state is None:
            # Never written (fresh install / add-on predates the mirror):
            # stay/go unavailable rather than claiming a clean house.
            self._state = None
            return
        self._state = state
        self._attr_native_value = int(state.get("open") or 0)


class BrainLastLearnedSensor(SensorEntity):
    """When brAIn last learned something, with what it was."""

    _attr_has_entity_name = True
    _attr_should_poll = True
    _attr_name = "Last learned"
    _attr_icon = "mdi:lightbulb-on-10"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_device_info = MEMORY_DEVICE_INFO

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._attr_unique_id = f"{DOMAIN}_last_learned"
        self._attr_native_value = None
        self._facts: list[str] = []

    @property
    def extra_state_attributes(self) -> dict:
        return {"facts": self._facts, "latest": self._facts[-1] if self._facts else None}

    def update(self) -> None:
        from .learning import last_learned
        try:
            when, facts = last_learned(self.hass)
            self._attr_native_value = when
            self._facts = facts
        except Exception:  # noqa: BLE001
            _LOGGER.debug("could not read the memory change log", exc_info=True)
