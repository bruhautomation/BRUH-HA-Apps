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


def progress(payload: dict | None = None, path: str | None = None,
             now: float | None = None) -> dict:
    """How much of the week this house's doors have been watched for.

    The unit is an **hour of the week**, because that is what a bucket
    is: `have` is the best-watched entity's count of them, since one door
    with a full picture is what makes the bedtime check sayable at all
    and an average over the house would hide it.
    """
    import baselines  # noqa: PLC0415 — one staleness floor, one home
    import house  # noqa: PLC0415 — panel-local, one shape and one eta

    now = time.time() if now is None else now
    payload = load(path) if payload is None else payload
    entities = payload.get("entities") or {}
    best = max((len(e.get("buckets") or {}) for e in entities.values()
                if isinstance(e, dict)), default=0)
    built = int(payload.get("built_at") or 0) or None
    asked = int(payload.get("asked") or 0)
    common = {"unit": "hours", "need": MIN_BUCKETS, "have": best,
              "detail": {"entities": len(entities)}, "updated_at": built,
              # A bucket needs an hour of watching, and until the week
              # wraps that is one more of them per hour of wall clock.
              "per_unit_s": SECONDS_PER_HOUR, "now": now}

    if payload.get("error"):
        return house.progress(
            state=house.UNAVAILABLE, reason=str(payload["error"])[:200],
            summary=f"The last pass could not measure anything: {payload['error']}.",
            **common)
    if not built:
        return house.progress(
            state=house.NOT_STARTED, reason="no pass has run yet",
            summary=("Nothing measured yet — the first pass runs overnight "
                     f"and reads {HISTORY_DAYS} days of door history."),
            **common)
    if not asked:
        return house.progress(
            state=house.UNAVAILABLE,
            reason="no door, window, lock or cover in this house",
            summary=("No door, window, lock or cover to watch, so there is "
                     "nothing here to be left open."),
            **common)
    if baselines.is_stale(payload, now):
        return house.progress(
            state=house.STALE,
            reason=f"last measured {house.days_ago(built, now)}",
            summary=(f"Measured {house.days_ago(built, now)} — the nightly "
                     "pass has not run since."),
            **common)
    if best >= MIN_BUCKETS:
        return house.progress(
            state=house.READY,
            summary=(f"{house.plural(len(entities), 'closure')} watched of "
                     f"{asked} · the best-watched has {best} hours of the "
                     "week with a picture."),
            **common)
    return house.progress(
        state=house.COLLECTING,
        reason=(f"{asked} closures watched, the best with {best} of the "
                f"{MIN_BUCKETS} hours one needs"),
        summary=(f"{house.plural(asked, 'closure')} watched, none with the "
                 f"{MIN_BUCKETS} hours of history one needs before "
                 "“usually open then” means anything."),
        **common)


async def fetch_history(session, ids: list[str], start: dt.datetime,
                        end: dt.datetime) -> dict | None:
    """Raw state changes per entity — not the bundle's downsampled shape.

    `ha_data.get_history` keeps only the newest `MAX_STATE_CHANGES` of a
    non-numeric series, which is right for a prompt and wrong here: the
    whole point is the weeks behind the last few changes.

    ``end`` is required for the reason :func:`ha_data.history_params`
    spells out: without it Core answers with the single day that follows
    `start`, which here is a day four weeks ago and outside the
    recorder's retention on any default install. That returned `[]` for
    every door in the house, and `[]` is a list — so this read it as "the
    history holds nothing for these ids" rather than as a refusal, and
    `build` wrote an empty store with no error every night. The store
    then looked measured (`built_at` set, `asked: 18`) while holding
    nothing, `snapshot` marked the key unavailable, and
    `evening.left_open` was skipped for the life of the feature.
    """
    import ha_data  # noqa: PLC0415

    if not ids:
        return {}
    out: dict[str, list] = {}
    answered = 0
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        try:
            raw = await ha_data._rest_get(
                session, ha_data.history_path(start), timeout=90,
                params=ha_data.history_params(
                    batch, end, minimal=True, no_attributes=True))
        except Exception as exc:  # noqa: BLE001 — a batch that failed is a
            # batch that failed; the rest of the house still gets measured.
            log.info("closure history batch failed: %s", exc)
            continue
        if not isinstance(raw, list):
            log.info("closure history batch answered with no list")
            continue
        answered += 1
        for series in raw:
            if not series:
                continue
            eid = series[0].get("entity_id", "")
            if not eid:
                continue
            out[eid] = [
                [(p.get("last_changed") or p.get("last_updated") or ""),
                 p.get("state")]
                for p in series]
    # None is "Core did not answer for any batch"; {} is a house whose
    # history holds nothing for these ids. `build` writes on the second
    # and refuses on the first.
    return out if answered else None


async def build(session, states: dict, now: float | None = None,
                path: str | None = None) -> dict:
    """Measure every closure and write the store. Returns the payload.

    A fetch nothing answered writes nothing and hands back the previous
    store with `error` beside it (`baselines.refused`); a house with no
    closures still writes an empty store.
    """
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
    series = await fetch_history(
        session, ids, start, dt.datetime.fromtimestamp(now, tz=dt.timezone.utc))
    if series is None:
        return baselines.refused(
            "closures", load(path),
            f"Home Assistant did not answer for any of the {len(ids)} "
            "closures asked about")
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
    "load", "progress", "save", "spread_interval", "usual_open",
]
