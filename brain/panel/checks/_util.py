"""Shared helpers for the house checks: names, times, and entity references.

Small on purpose. Anything that needs the snapshot's shape lives here so
the individual checks stay readable as rules.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any, Iterable, Iterator

DAY = 86400.0

# Domains that hold *software* objects: their being "unavailable" is not a
# device gone quiet, and their sitting still for a week is not a stuck
# sensor. The device checks skip them.
SOFTWARE_DOMAINS = frozenset({
    "automation", "script", "scene", "zone", "person", "sun", "group",
    "input_boolean", "input_number", "input_select", "input_text",
    "input_datetime", "input_button", "schedule", "timer", "counter",
    "tts", "conversation", "stt", "wake_word", "assist_satellite",
    "update", "tag", "event", "date", "time", "datetime", "text",
    "number", "select", "button", "image", "notify", "todo", "calendar",
    "device_tracker",
})

# Entity ids look like `domain.object_id`, and so do a hundred other things
# in a YAML file ("3.5", "e.g.", "v2.0"). A reference is only counted when
# its domain is one Home Assistant actually has — the snapshot's states
# supply the domains this house has, and this set covers the ones a
# reference could name that happen to hold no entity right now.
_CORE_DOMAINS = frozenset({
    "alarm_control_panel", "automation", "binary_sensor", "button", "calendar",
    "camera", "climate", "cover", "date", "datetime", "device_tracker",
    "event", "fan", "humidifier", "image", "input_boolean", "input_button",
    "input_datetime", "input_number", "input_select", "input_text",
    "lawn_mower", "light", "lock", "media_player", "number", "person",
    "remote", "scene", "script", "select", "sensor", "siren", "switch",
    "text", "time", "timer", "todo", "update", "vacuum", "valve",
    "water_heater", "weather", "zone", "counter", "schedule", "group",
    "sun", "tag", "assist_satellite", "conversation", "stt", "tts",
    "wake_word", "air_quality", "geo_location", "plant",
})

_ENTITY_RE = re.compile(r"(?<![\w.])([a-z_]+)\.([a-z0-9_]+)(?![\w.])")
# HA lets a template reference look like states.sensor.x or states('sensor.x');
# the first form has no "domain.object" token on its own, so it gets its
# own pattern.
_STATES_ATTR_RE = re.compile(r"\bstates\.([a-z_]+)\.([a-z0-9_]+)")


def parse_ts(value: Any) -> float | None:
    """An HA timestamp (ISO string, or epoch seconds) as epoch seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Registry `created_at` is epoch seconds; a few payloads carry ms.
        return float(value) / (1000.0 if value > 1e11 else 1.0)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.timestamp()


def age_days(value: Any, now: float) -> float | None:
    ts = parse_ts(value)
    return None if ts is None else max(0.0, (now - ts) / DAY)


def when(value: Any) -> str:
    """A short date for a `detail` line: '3 Sep' / '3 Sep 2025'."""
    ts = parse_ts(value)
    if ts is None:
        return "an unknown time"
    d = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
    return d.strftime("%-d %b %Y") if d.year != dt.datetime.now(dt.timezone.utc).year \
        else d.strftime("%-d %b")


def num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f  # NaN reads as no number


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


class House:
    """Lookups over a snapshot that several checks want."""

    def __init__(self, snap: dict):
        self.snap = snap
        self.states: dict[str, dict] = snap.get("states") or {}
        self.entities: list[dict] = snap.get("entities") or []
        self.devices: dict[str, dict] = {
            d["id"]: d for d in (snap.get("devices") or []) if d.get("id")}
        self.areas: dict[str, str] = {
            a["area_id"]: a.get("name") or a["area_id"]
            for a in (snap.get("areas") or []) if a.get("area_id")}
        self.registry: dict[str, dict] = {
            e["entity_id"]: e for e in self.entities if e.get("entity_id")}
        self.known_domains = (
            {domain_of(e) for e in self.states} | _CORE_DOMAINS)

    # -- names -------------------------------------------------------------
    def name(self, entity_id: str) -> str:
        st = self.states.get(entity_id) or {}
        attrs = st.get("attributes") or {}
        if attrs.get("friendly_name"):
            return str(attrs["friendly_name"])
        reg = self.registry.get(entity_id) or {}
        return str(reg.get("name") or reg.get("original_name") or entity_id)

    def device_of(self, entity_id: str) -> dict | None:
        reg = self.registry.get(entity_id) or {}
        return self.devices.get(reg.get("device_id") or "")

    def device_name(self, device: dict) -> str:
        return str(device.get("name_by_user") or device.get("name")
                   or device.get("id") or "a device")

    def area_of(self, entity_id: str) -> str:
        reg = self.registry.get(entity_id) or {}
        area = reg.get("area_id")
        if not area:
            dev = self.device_of(entity_id)
            area = (dev or {}).get("area_id")
        return self.areas.get(area or "", "")

    def where(self, entity_id: str) -> str:
        """' in the Kitchen' or ''. For a sentence about an entity."""
        area = self.area_of(entity_id)
        return f" in the {area}" if area else ""

    def exists(self, entity_id: str) -> bool:
        return entity_id in self.states or entity_id in self.registry

    def enabled(self, entity_id: str) -> bool:
        reg = self.registry.get(entity_id)
        if reg is None:
            return entity_id in self.states
        return not reg.get("disabled_by")

    # -- automations -------------------------------------------------------
    def automation_entity(self, config_id: str) -> str:
        """The entity_id an automation config's `id` registered as."""
        for e in self.entities:
            if (e.get("platform") == "automation"
                    and str(e.get("unique_id") or "") == str(config_id)):
                return e["entity_id"]
        return ""

    def entity_refs(self, obj: Any) -> set[str]:
        """Every entity id mentioned anywhere in a config tree.

        A service name has the same shape as an entity id
        (``light.turn_on`` / ``light.kitchen``), so the values of the keys
        that hold one are skipped, and so is anything that is a registered
        service — ``light.turn_on`` inside a template is still a service.
        """
        services = set(self.snap.get("services") or ())
        out: set[str] = set()
        for text in _strings(obj):
            for domain, obj_id in _ENTITY_RE.findall(text):
                ref = f"{domain}.{obj_id}"
                if (domain in self.known_domains and domain != "notify"
                        and ref not in services):
                    out.add(ref)
            for domain, obj_id in _STATES_ATTR_RE.findall(text):
                if domain in self.known_domains:
                    out.add(f"{domain}.{obj_id}")
        return out


# Keys whose string value names a service, a trigger kind or a platform —
# never an entity.
_NOT_ENTITY_KEYS = frozenset({"service", "action", "trigger", "platform",
                              "domain", "event_type", "condition", "mode"})


def _strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
                if k in _NOT_ENTITY_KEYS and isinstance(v, str):
                    continue
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def walk(obj: Any) -> Iterator[Any]:
    """Every node of a config tree, depth first."""
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from walk(v)


def listify(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def join_names(names: Iterable[str], limit: int = 6) -> str:
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" and {len(names) - limit} more"
