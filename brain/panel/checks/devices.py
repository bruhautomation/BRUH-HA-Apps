"""Device and sensor checks.

The physical half of the house: what has gone quiet, what is running on a
dying battery, what is reading a number no sensor should read, what has sat
on exactly one value for a week, and what belongs to an integration that is
no longer there.
"""
from __future__ import annotations

from ._util import (SOFTWARE_DOMAINS, House, age_days, domain_of, join_names,
                    num, when)

UNAVAILABLE_DAYS = 1.0
BATTERY_LOW_PCT = 15
BATTERY_SILENT_DAYS = 7
FROZEN_DAYS = 7
FROZEN_MIN_DAYS = 5

# Sane physical ranges by device class and unit. A reading outside these is
# a broken sensor, not a hot day.
_RANGES = {
    ("temperature", "°C"): (-40.0, 60.0),
    ("temperature", "°F"): (-40.0, 140.0),
    ("humidity", "%"): (0.0, 100.0),
    ("battery", "%"): (0.0, 100.0),
    ("illuminance", "lx"): (0.0, 200000.0),
    ("pressure", "hPa"): (800.0, 1100.0),
    ("pressure", "mbar"): (800.0, 1100.0),
}


def _live_hardware(house: House):
    for eid, st in house.states.items():
        if domain_of(eid) in SOFTWARE_DOMAINS:
            continue
        if not house.enabled(eid):
            continue
        yield eid, st


# ---------------------------------------------------------------------------
# dev.unavailable — grouped by device, or a dead hub files forty rows
# ---------------------------------------------------------------------------

def unavailable(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    by_device: dict[str, list[tuple[str, float]]] = {}
    loose: list[tuple[str, float]] = []
    for eid, st in _live_hardware(house):
        if st.get("state") != "unavailable":
            continue
        age = age_days(st.get("last_changed"), now)
        if age is None or age < UNAVAILABLE_DAYS:
            continue
        # An entity whose integration is gone is the `restored` check's.
        if (st.get("attributes") or {}).get("restored"):
            continue
        dev = house.device_of(eid)
        if dev:
            by_device.setdefault(dev["id"], []).append((eid, age))
        else:
            loose.append((eid, age))
    out = []
    for dev_id, rows in by_device.items():
        dev = house.devices[dev_id]
        rows.sort(key=lambda r: r[1], reverse=True)
        first, longest = rows[0]
        name = house.device_name(dev)
        out.append({
            "text": f"{name} has been unavailable for more than a day",
            "detail": f"Since {when(house.states[first].get('last_changed'))}"
                      f"{house.where(first)}"
                      + (f"; {len(rows)} of its entities are affected"
                         if len(rows) > 1 else "")
                      + ".",
            "fix": "Check its power and its connection (batteries, Wi-Fi, "
                   "the hub it pairs through), then reload its integration.",
            "severity": "serious",
            "fixable": False,
            "entity_id": first,
        })
    for eid, age in loose:
        out.append({
            "text": f"{house.name(eid)} has been unavailable for more than "
                    "a day",
            "detail": f"Since {when(house.states[eid].get('last_changed'))}"
                      f"{house.where(eid)}.",
            "fix": "Check whatever provides it, then reload its integration.",
            "severity": "serious",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# dev.battery_low — a threshold, and the case a threshold misses
# ---------------------------------------------------------------------------

def _is_battery(st: dict) -> bool:
    attrs = st.get("attributes") or {}
    return attrs.get("device_class") == "battery" and attrs.get(
        "unit_of_measurement") == "%"


def battery_low(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for eid, st in _live_hardware(house):
        if not _is_battery(st):
            continue
        level = num(st.get("state"))
        dev = house.device_of(eid)
        who = house.device_name(dev) if dev else house.name(eid)
        if level is not None and level <= BATTERY_LOW_PCT:
            out.append({
                "text": f"{who} battery is low",
                "detail": f"{level:g}% as of {when(st.get('last_updated'))}"
                          f"{house.where(eid)}.",
                "fix": "Replace the battery.",
                "severity": "warning" if level > 5 else "serious",
                "fixable": False,
                "entity_id": eid,
            })
            continue
        # A dead device stops reporting its own battery, and the last
        # value it sent is whatever it was — often a healthy number. Only
        # `last_reported` (HA 2024.4+) says whether the sensor is still
        # talking; `last_updated` does not move on an unchanged value.
        reported = st.get("last_reported")
        silent = age_days(reported, now) if reported else None
        if silent is not None and silent >= BATTERY_SILENT_DAYS \
                and st.get("state") not in ("unavailable", "unknown"):
            out.append({
                "text": f"{who} has stopped reporting its battery",
                "detail": f"Last heard {when(reported)}{house.where(eid)}; "
                          f"it still shows {st.get('state')}%, which is the "
                          "last thing it said, not what it is now.",
                "fix": "Check whether the device is still alive; a flat "
                       "battery is the usual reason it went quiet.",
                "severity": "warning",
                "fixable": False,
                "entity_id": eid,
            })
    return out


# ---------------------------------------------------------------------------
# dev.implausible — a reading no sensor should give
# ---------------------------------------------------------------------------

def implausible(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for eid, st in _live_hardware(house):
        attrs = st.get("attributes") or {}
        key = (attrs.get("device_class"), attrs.get("unit_of_measurement"))
        bounds = _RANGES.get(key)
        if not bounds:
            continue
        value = num(st.get("state"))
        if value is None:
            continue
        lo, hi = bounds
        if lo <= value <= hi:
            continue
        out.append({
            "text": f"{house.name(eid)} is reporting an impossible value",
            "detail": f"{value:g}{key[1]} as of {when(st.get('last_updated'))}"
                      f"{house.where(eid)}; a {key[0]} sensor cannot read "
                      f"outside {lo:g}–{hi:g}{key[1]}.",
            "fix": "The sensor is faulty or misconfigured. Check its wiring "
                   "or pairing, and exclude it from automations until it "
                   "reads sanely.",
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# dev.frozen — exactly one value for a week, from long-term statistics
# ---------------------------------------------------------------------------

def frozen(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    stats = snap.get("stats") or {}
    out = []
    for eid, rows in stats.items():
        st = house.states.get(eid)
        if not st or domain_of(eid) in SOFTWARE_DOMAINS or not house.enabled(eid):
            continue
        if st.get("state") in ("unavailable", "unknown"):
            continue
        attrs = st.get("attributes") or {}
        # Batteries sit at 100 for weeks and signal strength sits wherever
        # the router is. Neither is a stuck sensor.
        if attrs.get("device_class") in ("battery", "signal_strength"):
            continue
        days = [r for r in rows if isinstance(r, dict)
                and r.get("min") is not None and r.get("max") is not None]
        if len(days) < FROZEN_MIN_DAYS:
            continue
        lo = min(num(r["min"]) or 0.0 for r in days)
        hi = max(num(r["max"]) or 0.0 for r in days)
        if hi - lo > 1e-9:
            continue
        if abs(lo) < 1e-9:
            # A power sensor on an idle plug reads 0 for a week and is fine.
            continue
        unit = attrs.get("unit_of_measurement") or ""
        out.append({
            "text": f"{house.name(eid)} has read exactly the same value "
                    "for a week",
            "detail": f"{lo:g}{unit} on every one of the last {len(days)} "
                      f"days{house.where(eid)}. A real sensor moves.",
            "fix": "Check the sensor — it has probably stopped updating "
                   "while its integration keeps repeating the last value.",
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# dev.restored — the integration that provided it is gone
# ---------------------------------------------------------------------------

def restored(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    by_platform: dict[str, list[str]] = {}
    for eid, st in house.states.items():
        if (st.get("attributes") or {}).get("restored") is not True:
            continue
        reg = house.registry.get(eid) or {}
        by_platform.setdefault(str(reg.get("platform") or "unknown"), []).append(eid)
    out = []
    for platform, eids in sorted(by_platform.items()):
        eids.sort()
        out.append({
            "text": f"Entities from the '{platform}' integration are left "
                    "over with nothing providing them",
            "detail": f"{len(eids)} restored entit{'y' if len(eids) == 1 else 'ies'}: "
                      + join_names(eids) + ". They show as unavailable and "
                      "clutter every picker.",
            "fix": "Reinstall the integration if it was removed by mistake, "
                   "or delete the entities (brain.delete_orphaned_entities "
                   "does it in one go).",
            "severity": "info",
            "fixable": True,
            "entity_id": eids[0],
        })
    return out


CHECKS = [
    {"id": "dev.unavailable", "title": "Devices unavailable for a day",
     "needs": ("states", "registry"), "run": unavailable},
    {"id": "dev.battery_low", "title": "Batteries low or gone quiet",
     "needs": ("states", "registry"), "run": battery_low},
    {"id": "dev.implausible", "title": "Impossible sensor readings",
     "needs": ("states", "registry"), "run": implausible},
    {"id": "dev.frozen", "title": "Sensors frozen on one value",
     "needs": ("states", "registry", "stats"), "run": frozen},
    {"id": "dev.restored", "title": "Entities with no integration",
     "needs": ("states", "registry"), "run": restored},
]
