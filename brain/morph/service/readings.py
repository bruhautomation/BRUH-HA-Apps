"""Readings brAIn must not quote: a device that looks dead (#1468).

A card that asks brAIn for a sentence about a room (`converse`) sends the
readings it shows as context, and brAIn wrote them back as facts: a soil
probe that had read a flat 0% for a day beside a low battery became "the
soil is bone dry, the rain should help". Soil dries over hours and a probe
that stops answering lands on its range's end and stays there, so a
reading is doubted from typed data only, never from the words around it:

* the entity is ``unavailable`` or ``unknown`` (no reading now);
* a percentage at 0 that got there straight from 10 or more within 15
  minutes (Morph's `fellToZero`, util.js);
* a percentage at an end of its range beside a battery on its device at or
  under ``BATTERY_LOW_PCT`` (brAIn's `dev.battery_low` mark) or a
  low-battery flag that is on;
* a percentage at an end of its range that has not moved for
  ``FLAT_AFTER_S`` on a device that runs on a battery.

Each doubted reading becomes one sentence handed to brAIn beside the card's
context, saying what was measured and that the reading is not to be given
as one. Nothing here changes what a card draws.
"""
from __future__ import annotations

import datetime
import re

import ha

BATTERY_LOW_PCT = 15  # brAIn's checks/devices.py BATTERY_LOW_PCT
FLAT_AFTER_S = 24 * 3600
CLIFF_FROM = 10  # Morph's util.js CLIFF_FROM
CLIFF_S = 15 * 60
HISTORY_S = 48 * 3600
MAX_ENTITIES = 40
READ_DOMAINS = ("sensor", "binary_sensor")
_ENTITY = re.compile(r"\b((?:sensor|binary_sensor)\.[a-z0-9_]+)\b")
_OWN_BATTERY = ("battery_level", "battery")


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _ts(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _when(t: float, now: float) -> str:
    lt = datetime.datetime.fromtimestamp(t)
    clock = lt.strftime("%I:%M %p").lstrip("0")
    days = (datetime.date.fromtimestamp(now) - lt.date()).days
    if days <= 0:
        return clock
    if days == 1:
        return f"yesterday {clock}"
    return f"{lt.strftime('%b')} {lt.day}, {clock}"


def _fmt(x: float) -> str:
    return f"{x:g}"


def mentioned(context: str, states: dict, entities=()) -> list[str]:
    """The readings a card's context is about: the entity ids it names or
    sent in `entities`, and sensors whose friendly name it carries whole."""
    out = [e for e in entities or () if isinstance(e, str) and e in states]
    out += [e for e in _ENTITY.findall(context or "") if e in states]
    for eid, st in states.items():
        if eid.partition(".")[0] not in READ_DOMAINS:
            continue
        name = str(((st or {}).get("attributes") or {}).get("friendly_name") or "")
        if len(name) >= 4 and name in (context or ""):
            out.append(eid)
    return list(dict.fromkeys(out))[:MAX_ENTITIES]


def battery_of(eid: str, states: dict, registry: list) -> dict | None:
    """The battery of the device an entity is on: its percentage, its
    low-battery flag, or its voltage (said, not judged: a voltage's floor
    depends on the cell). ``None`` when the device shows no battery."""
    dev = next((r.get("device_id") for r in registry if r.get("entity_id") == eid), None)
    found: dict = {}
    for r in registry if dev else ():
        other = r.get("entity_id")
        if r.get("device_id") != dev or other == eid:
            continue
        st = states.get(other) or {}
        a = st.get("attributes") or {}
        cls = a.get("device_class")
        if other.startswith("binary_sensor.") and cls == "battery":
            found["low_flag"] = st.get("state") == "on"
        elif other.startswith("sensor.") and cls == "battery" and _num(st.get("state")) is not None:
            found["pct"] = _num(st.get("state"))
        elif other.startswith("sensor.") and cls == "voltage" and _num(st.get("state")) is not None \
                and "batt" in f"{other} {a.get('friendly_name') or ''}".lower():
            found["volts"] = f"{_fmt(_num(st.get('state')))} {a.get('unit_of_measurement') or 'V'}".strip()
    own = (states.get(eid) or {}).get("attributes") or {}
    for key in _OWN_BATTERY:
        if "pct" not in found and _num(own.get(key)) is not None:
            found["pct"] = _num(own.get(key))
    return found or None


def _series(rows) -> list[tuple[float, float | None]]:
    """History rows as Home Assistant sends them (``{s, lu}``, ``lu`` in
    seconds, or ``state``/``last_updated``) as (time, number) pairs."""
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        t = _ts(r.get("lu") if "lu" in r else r.get("last_updated") or r.get("last_changed"))
        if t is not None:
            out.append((t, _num(r.get("s") if "s" in r else r.get("state"))))
    return sorted(out)


def fell_to_end(pts: list[tuple[float, float | None]], end: float) -> float | None:
    """The reading it fell from, when it reached ``end`` straight from
    ``CLIFF_FROM`` or more away (the reading before, or any within the 15
    minutes before), else ``None``: util.js's `fellToZero`, for either end."""
    v = [p for p in pts if p[1] is not None]
    if not v or v[-1][1] != end:
        return None
    i = len(v) - 1
    while i > 0 and v[i - 1][1] == end:
        i -= 1
    if i == 0:
        return None
    t0 = v[i][0]
    for j in range(i - 1, -1, -1):
        if j < i - 1 and t0 - v[j][0] > CLIFF_S:
            break
        if abs(v[j][1] - end) >= CLIFF_FROM:
            return v[j][1]
    return None


def flat_since(pts: list[tuple[float, float | None]], value: float, changed: float | None) -> float | None:
    """When the reading last moved to ``value``: the start of the run of it
    at the end of the history, or the state's own `last_changed`."""
    since = changed
    for t, x in reversed(pts):
        if x != value:
            break
        since = t if since is None else min(since, t)
    return since


def doubts(eids, states: dict, registry: list, history: dict, now: float) -> list[dict]:
    """``[{entity, name, said}]``: a sentence per reading that is not to be
    given as one, and why, from the typed data only."""
    out = []
    for eid in eids:
        st = states.get(eid)
        if not st or eid.partition(".")[0] not in READ_DOMAINS:
            continue
        a = st.get("attributes") or {}
        name = str(a.get("friendly_name") or eid)
        state = st.get("state")
        if state in ("unavailable", "unknown"):
            seen = _ts(st.get("last_changed"))
            out.append({"entity": eid, "name": name,
                        "said": f"{name} has no reading now (Home Assistant says {state}"
                                + (f", since {_when(seen, now)}" if seen else "") + ")."})
            continue
        value = _num(state)
        if value is None or a.get("unit_of_measurement") != "%" or value not in (0.0, 100.0):
            continue
        if a.get("device_class") == "battery":
            continue  # a battery at 100 is a full battery
        pts = _series(history.get(eid))
        bat = battery_of(eid, states, registry)
        why = []
        # Only a fall to 0: soil watered from 50 to 100 in minutes is real.
        fell = fell_to_end(pts, 0.0) if value == 0 else None
        if fell is not None:
            why.append(f"it went straight to {_fmt(value)}% from {_fmt(fell)}%")
        if bat and (bat.get("low_flag") or (bat.get("pct") is not None and bat["pct"] <= BATTERY_LOW_PCT)):
            why.append("its battery is low" + (f" ({_fmt(bat['pct'])}%)" if bat.get("pct") is not None else ""))
        since = flat_since(pts, value, _ts(st.get("last_changed")))
        flat = since is not None and now - since >= FLAT_AFTER_S
        if flat and bat:
            # A run that reaches the start of the history read began earlier.
            whole = bool(pts) and all(x == value for _, x in pts)
            why.append(f"it has not moved from {_fmt(value)}% since {_when(since, now)}"
                       + (" or earlier" if whole else ""))
        if not why:
            continue
        if bat and bat.get("volts") and not any(w.startswith("its battery") for w in why):
            why.append(f"its battery reads {bat['volts']}")
        out.append({"entity": eid, "name": name,
                    "said": f"{name} reads {_fmt(value)}%, but the device looks offline: "
                            + "; ".join(why) + "."})
    return out


def lead(found: list[dict]) -> str:
    """The block handed to brAIn beside a card's context, or ""."""
    if not found:
        return ""
    return ("Morph checked the readings this card is about against Home Assistant. These come "
            "from devices that look offline or out of battery, so they are not readings: do not "
            "quote them or build advice on them. Say the device looks offline or needs a battery "
            "(or leave it out), and use the other readings:\n"
            + "\n".join(f"- {d['said']}" for d in found))


async def check(context: str, entities=(), now: float | None = None) -> str:
    """Read the house and answer `lead` for what a card's context is about.
    "" when Home Assistant could not be asked or nothing is in doubt."""
    import time
    now = now or time.time()
    res = await ha.ws_calls([{"type": "get_states"}, {"type": "config/entity_registry/list"}])
    if not res or res[0] is None:
        return ""
    states = {s.get("entity_id"): s for s in res[0] if isinstance(s, dict)}
    registry = [r for r in res[1] or [] if isinstance(r, dict)]
    eids = mentioned(context, states, entities)
    if not eids:
        return ""
    start = datetime.datetime.fromtimestamp(now - HISTORY_S, datetime.timezone.utc).isoformat()
    hist = await ha.ws_calls([{"type": "history/history_during_period", "start_time": start,
                               "entity_ids": eids, "minimal_response": True, "no_attributes": True,
                               "significant_changes_only": False}])
    history = (hist or [None])[0] or {}
    return lead(doubts(eids, states, registry, history if isinstance(history, dict) else {}, now))


__all__ = ["check", "doubts", "lead", "mentioned", "battery_of", "fell_to_end", "flat_since"]
