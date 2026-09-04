"""How often this house has something open at this hour of the week.

`baselines.py` answers "is this reading unusual" and cannot answer it for
a door, because it measures medians and spreads over numbers and a door
has neither. So the one question people most want their house to notice
at bedtime — *is anything open, unlocked or ajar that usually is not* —
had no measurement behind it at all, and any rule for it would have been
a threshold somebody guessed.

What a binary entity has instead of a median is **how much of the time it
is open**, and that is a different arithmetic: for each hour of the week,
the seconds it spent open over the seconds it was observed at all. A back
door open at 23:40 is news in a house that has it shut at that hour on 49
nights out of 50, and is not news in one where it stands open all summer.

Four things keep this bounded and honest.

**Only closures**, not every binary entity in the house. A hall motion
sensor being on at midnight is not a thing anybody wants told about, and
including it would bury the one row that matters. Doors, windows, locks,
covers and garages — chosen by device class and domain, which is what
Home Assistant already knows about them.

**Time-weighted, never sampled.** Counting "how many times was it open
when we looked" answers a question about the polling, not the door: a
door open for ten minutes and one open for ten hours look identical to a
sampler that catches each once.

**A bucket has to have been watched.** Four weeks gives four hours of
observation in each hour-of-week bucket at best, and a recorder that was
purged or an entity added on Tuesday gives less. Below
`MIN_OBSERVED_S` a bucket says nothing rather than reporting a fraction
of a fraction.

**And it decides nothing.** It answers "how much of this hour is this
normally open", and the check decides whether that is worth saying — the
same split `baselines.py` keeps, and for the same reason: a measurement
that also raised alarms would be two rules in one place with the
threshold invisible.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

log = logging.getLogger("brain.closures")

STORE = os.environ.get("BRAIN_CLOSURE_FILE", "/data/closures.json")

HISTORY_DAYS = 28
HOURS_PER_WEEK = 168
SECONDS_PER_HOUR = 3600.0

# What counts as a closure. A motion sensor is not one, and neither is a
# plug: the question is "what is open that shouldn't be", and these are
# the classes Home Assistant already uses to say so.
DOOR_CLASSES = frozenset({
    "door", "garage_door", "window", "opening",
})
COVER_CLASSES = frozenset({
    "door", "garage", "window", "gate", "awning", "shutter", "blind",
    "curtain",
})
# The states that mean "not shut", per domain.
OPEN_STATES = frozenset({"on", "open", "opening", "unlocked"})
SHUT_STATES = frozenset({"off", "closed", "closing", "locked"})

# A bucket watched for less than this is not a measurement. Four weeks
# gives four hours per bucket at best; anything under an hour is a
# recorder that was purged or an entity added part-way through.
MIN_OBSERVED_S = 3600.0
# And the whole entity needs enough of them, or a door added on Friday
# has a confident answer about Friday and nothing else.
MIN_BUCKETS = 24
# Fetching raw history is the expensive half, so this is bounded on
# purpose: a house with more closures than this has bigger questions.
MAX_ENTITIES = 60
# One history request per batch of ids.
BATCH = 15


def is_closure(entity_id: str, attrs: dict) -> bool:
    """Whether this entity is a thing that can be left open.

    Domain first, then device class — a `binary_sensor` with no class is
    not a door, and guessing that it is would fill the list with motion.
    """
    domain = str(entity_id or "").split(".", 1)[0]
    klass = str((attrs or {}).get("device_class") or "")
    if domain == "lock":
        return True
    if domain == "cover":
        return klass in COVER_CLASSES or not klass
    if domain == "binary_sensor":
        return klass in DOOR_CLASSES
    return False


def candidates(states: dict) -> list[str]:
    """The closures worth measuring, in a stable order.

    Sorted before capping so the cap takes the *same* entities every
    night — an arbitrary set that changed nightly would give half the
    house a baseline that keeps appearing and disappearing.
    """
    out = []
    for eid, st in (states or {}).items():
        if not isinstance(st, dict):
            continue
        if st.get("state") in ("unavailable", "unknown", None):
            continue
        if is_closure(eid, st.get("attributes") or {}):
            out.append(eid)
    return sorted(out)[:MAX_ENTITIES]


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------

def _parse(stamp: str) -> float | None:
    try:
        text = str(stamp).replace("Z", "+00:00")
        when = dt.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.timestamp()


def spread_interval(start: float, end: float, tz: dt.tzinfo,
                    into: dict[int, float]) -> None:
    """Add the seconds between two instants to the buckets they fall in.

    An interval routinely spans many hours — a door shut on Friday and
    opened on Monday is one interval across sixty buckets — so this walks
    the hour boundaries rather than charging the whole span to whichever
    bucket it started in, which is how a rarely-changing entity would
    otherwise report almost every hour as unobserved.
    """
    import baselines  # noqa: PLC0415 — one hour_of_week, one home

    if end <= start:
        return
    cursor = start
    while cursor < end:
        local = dt.datetime.fromtimestamp(cursor, tz)
        bucket = baselines.hour_of_week(cursor, tz)
        top = local.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
        step = min(top.timestamp(), end)
        into[bucket] = into.get(bucket, 0.0) + (step - cursor)
        # A clock that does not advance is an infinite loop, and a DST
        # boundary is exactly where that could happen.
        cursor = step if step > cursor else cursor + SECONDS_PER_HOUR


def build_entity(points: list, tz: dt.tzinfo, now: float) -> dict | None:
    """One entity's history as open-seconds and watched-seconds per bucket."""
    rows = []
    for point in points or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        when = _parse(point[0])
        state = str(point[1] or "").lower()
        if when is None or state not in OPEN_STATES | SHUT_STATES:
            continue
        rows.append((when, state in OPEN_STATES))
    if len(rows) < 2:
        return None
    rows.sort()

    watched: dict[int, float] = {}
    opened: dict[int, float] = {}
    for i, (start, is_open) in enumerate(rows):
        end = rows[i + 1][0] if i + 1 < len(rows) else now
        spread_interval(start, end, tz, watched)
        if is_open:
            spread_interval(start, end, tz, opened)

    buckets = {}
    for hour, seen in watched.items():
        if seen < MIN_OBSERVED_S:
            continue
        buckets[str(hour)] = {
            "open": round(opened.get(hour, 0.0) / seen, 4),
            "hours": round(seen / SECONDS_PER_HOUR, 2),
        }
    if len(buckets) < MIN_BUCKETS:
        return None
    total = sum(watched.values()) or 1.0
    return {"buckets": buckets,
            "overall": round(sum(opened.values()) / total, 4),
            "changes": len(rows)}


def usual_open(entry: dict, bucket: int) -> float | None:
    """How much of this hour of the week this is normally open, or None.

    `None` is "this house has not been watched at this hour", which is a
    different answer from "it is never open then" and every caller has to
    tell them apart.
    """
    if not entry:
        return None
    row = (entry.get("buckets") or {}).get(str(bucket))
    return row["open"] if row else None


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"built_at": 0, "entities": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entities"), dict):
        return {"built_at": 0, "entities": {}}
    return data


def save(payload: dict, path: str | None = None) -> None:
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or STORE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    try:
        atomic_write.write_json(target, payload)
    except OSError as exc:
        log.warning("could not write the closure store: %s", exc)


async def fetch_history(session, ids: list[str], start: dt.datetime) -> dict:
    """Raw state changes per entity — not the bundle's downsampled shape.

    `ha_data.get_history` keeps only the newest `MAX_STATE_CHANGES` of a
    non-numeric series, which is right for a prompt and wrong here: the
    whole point is the weeks behind the last few changes.
    """
    import ha_data  # noqa: PLC0415

    out: dict[str, list] = {}
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        path = (f"/history/period/{start.isoformat()}"
                f"?filter_entity_id={','.join(batch)}"
                "&minimal_response&no_attributes")
        try:
            raw = await ha_data._rest_get(session, path, timeout=90)
        except Exception as exc:  # noqa: BLE001 — a batch that failed is a
            # batch that failed; the rest of the house still gets measured.
            log.info("closure history batch failed: %s", exc)
            continue
        for series in raw or []:
            if not series:
                continue
            eid = series[0].get("entity_id", "")
            if not eid:
                continue
            out[eid] = [
                [(p.get("last_changed") or p.get("last_updated") or ""),
                 p.get("state")]
                for p in series]
    return out


async def build(session, states: dict, now: float | None = None,
                path: str | None = None) -> dict:
    """Measure every closure and write the store. Returns the payload."""
    now = time.time() if now is None else now
    import baselines  # noqa: PLC0415

    tz, tz_name = baselines.house_timezone()
    ids = candidates(states)
    payload = {"built_at": int(now), "tz": tz_name, "days": HISTORY_DAYS,
               "asked": len(ids), "entities": {}}
    if not ids:
        save(payload, path)
        return payload

    start = dt.datetime.fromtimestamp(now - HISTORY_DAYS * 86400,
                                      tz=dt.timezone.utc)
    series = await fetch_history(session, ids, start)
    for eid, points in series.items():
        built = build_entity(points, tz, now)
        if built:
            name = ((states.get(eid) or {}).get("attributes") or {}).get(
                "friendly_name")
            if name:
                built["name"] = str(name)[:60]
            payload["entities"][eid] = built
    save(payload, path)
    log.info("closures: %d of %d measured over %d days (%s)",
             len(payload["entities"]), len(ids), HISTORY_DAYS, tz_name)
    return payload


__all__ = [
    "HISTORY_DAYS", "MAX_ENTITIES", "MIN_BUCKETS", "MIN_OBSERVED_S", "STORE",
    "build", "build_entity", "candidates", "fetch_history", "is_closure",
    "load", "save", "spread_interval", "usual_open",
]
