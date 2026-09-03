"""When this house wakes, and when it settles.

Every scheduled thing brAIn does happens at a time somebody typed into a
box, which is the definition of a timer rather than a rhythm. A brief
delivered at 07:00 is early on a Sunday and late on a Tuesday in the same
house, and the person who has to keep correcting it stops reading it.

The house already answers this and nothing was asking: `actions.py`
files every state change under a cause, and the first change caused by a
**person** is the house waking up — not a motion sensor (which fires for
a cat and for the heating), not a light coming on (an automation does
that at dawn), but somebody actually doing something. The last one is the
house settling.

Four rules keep it honest, and they are the same four the baselines and
the override ledger carry, because they are the same failure.

**A day is one sample, and a fortnight of them is an answer.** Below
`MIN_DAYS` this says nothing at all rather than reporting a habit built
out of last Tuesday.

**Weekdays and weekends are different houses**, so they are measured
apart. A single number over both is a time that is wrong on all seven
days rather than on none. The cost is worth naming: a weekend accrues
two days a week, so the weekend answer takes about five weeks to exist
where the weekday one takes two. That looks like a bug from outside and
is not — the floor is a count of days, and ten of them is ten of them
whichever days they were.

**The spread is what says whether the number means anything.** A house
that stirs anywhere between 05:00 and 11:00 has no wake time, and
reporting its median as one would be a confident answer where the data
holds none. `MAX_SPREAD_MIN` is what refuses it.

**And the median is CIRCULAR.** Settle times sit either side of midnight
— 23:40 and 00:20 are forty minutes apart and average to *noon* on a
straight number line. Everything here is measured as minutes around the
clock and the centre is found by rotating to the tightest arc first.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

log = logging.getLogger("brain.rhythm")

STORE = os.environ.get("BRAIN_RHYTHM_FILE", "/data/rhythm.json")

# A fortnight. Below this a "usual time" is last week with extra steps.
MIN_DAYS = 10
# Kept long enough to survive a holiday, short enough that a household
# whose hours changed in the spring is not being quoted its winter.
KEEP_DAYS = 90.0
# Past this much scatter there is no usual time — an answer here would be
# a confident number over data that holds none.
MAX_SPREAD_MIN = 90.0
# A day with nothing on it is a day nobody was home; it is not a 00:00.
MINUTES_PER_DAY = 1440

WEEKDAY = "weekday"
WEEKEND = "weekend"


# ---------------------------------------------------------------------------
# Clock arithmetic that does not break at midnight
# ---------------------------------------------------------------------------

def circular_median(minutes: list[int]) -> float | None:
    """The middle of a set of times of day, measured around the clock.

    A straight median puts 23:40 and 00:20 at noon, which is not a small
    error — it is the answer pointing at the opposite side of the day.
    The arc that holds every sample most tightly is found first, the
    median is taken inside it, and the result is rotated back.
    """
    if not minutes:
        return None
    import baselines  # noqa: PLC0415 — one median, one mad, one home

    best = None
    for offset in sorted(set(minutes)):
        rotated = sorted((m - offset) % MINUTES_PER_DAY for m in minutes)
        span = rotated[-1] - rotated[0]
        if best is None or span < best[0]:
            best = (span, offset, rotated)
    _span, offset, rotated = best
    return (baselines.median([float(v) for v in rotated])
            + offset) % MINUTES_PER_DAY


def circular_spread(minutes: list[int], centre: float) -> float:
    """How far these times stray from their centre, the short way round.

    The distance between two times of day is never more than twelve
    hours: 23:50 is twenty minutes from 00:10, not twenty-three hours and
    forty.
    """
    import baselines  # noqa: PLC0415

    if not minutes:
        return 0.0
    away = []
    for m in minutes:
        d = abs(m - centre) % MINUTES_PER_DAY
        away.append(min(d, MINUTES_PER_DAY - d))
    return baselines.median(away)


def clock(minutes: float | None) -> str:
    """`437.0` as `07:17`. Empty for nothing, never as `00:00`."""
    if minutes is None:
        return ""
    total = int(round(minutes)) % MINUTES_PER_DAY
    return f"{total // 60:02d}:{total % 60:02d}"


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"days": {}}
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        return {"days": {}}
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
        log.warning("could not write the rhythm store: %s", exc)


def record(actions: list[dict], tz: dt.tzinfo, now: float | None = None,
           path: str | None = None) -> int:
    """File the first and last person-caused minute of each day seen.

    Returns how many days were touched. A day already recorded is
    *widened*, never replaced: passes overlap, so a window that starts at
    04:00 sees a later "first" than the pass that saw midnight, and
    taking the newest would walk the wake time forwards all morning.
    """
    now = time.time() if now is None else now
    payload = load(path)
    days = payload["days"]
    touched = set()
    for action in actions or []:
        if not isinstance(action, dict) or action.get("cause") != "person":
            continue
        ts = action.get("ts")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            continue
        when = dt.datetime.fromtimestamp(float(ts), tz)
        key = when.date().isoformat()
        minute = when.hour * 60 + when.minute
        row = days.get(key)
        if not isinstance(row, dict):
            row = {"first": minute, "last": minute,
                   "dow": when.weekday(), "n": 0}
            days[key] = row
        # Widened, never replaced. See the docstring.
        row["first"] = min(int(row.get("first", minute)), minute)
        row["last"] = max(int(row.get("last", minute)), minute)
        row["dow"] = when.weekday()
        row["n"] = int(row.get("n", 0)) + 1
        touched.add(key)

    cutoff = dt.datetime.fromtimestamp(now - KEEP_DAYS * 86400, tz).date()
    payload["days"] = {k: v for k, v in days.items()
                       if _date(k) and _date(k) >= cutoff}
    payload["updated_at"] = int(now)
    save(payload, path)
    return len(touched)


def _date(key: str):
    try:
        return dt.date.fromisoformat(key)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------

def _shape(rows: list[dict], field: str) -> dict | None:
    minutes = [int(r[field]) for r in rows
               if isinstance(r.get(field), int)]
    if len(minutes) < MIN_DAYS:
        return None
    centre = circular_median(minutes)
    if centre is None:
        return None
    spread = circular_spread(minutes, centre)
    if spread > MAX_SPREAD_MIN:
        # No usual time. Saying so is the honest answer; a median here
        # would be a confident number over data that holds none.
        return None
    return {"minute": round(centre, 1), "at": clock(centre),
            "spread_min": round(spread, 1), "days": len(minutes)}


def profile(payload: dict | None = None, path: str | None = None) -> dict:
    """When this house usually stirs and settles, weekdays and weekends apart.

    A missing half is a real state and reads as "not measured yet"
    everywhere downstream — never as midnight, and never as the other
    half's answer.
    """
    payload = load(path) if payload is None else payload
    rows = [r for r in (payload.get("days") or {}).values()
            if isinstance(r, dict)]
    out: dict = {"days": len(rows), "updated_at": payload.get("updated_at", 0)}
    for name, keep in ((WEEKDAY, lambda d: d < 5), (WEEKEND, lambda d: d >= 5)):
        part = [r for r in rows
                if isinstance(r.get("dow"), int) and keep(r["dow"])]
        out[name] = {"wakes": _shape(part, "first"),
                     "settles": _shape(part, "last")}
    return out


def wake_minute(payload: dict, when: dt.datetime) -> float | None:
    """The usual first-activity minute for the kind of day `when` is."""
    part = payload.get(WEEKEND if when.weekday() >= 5 else WEEKDAY) or {}
    shape = part.get("wakes")
    return shape["minute"] if shape else None


def settle_minute(payload: dict, when: dt.datetime) -> float | None:
    part = payload.get(WEEKEND if when.weekday() >= 5 else WEEKDAY) or {}
    shape = part.get("settles")
    return shape["minute"] if shape else None


__all__ = [
    "KEEP_DAYS", "MAX_SPREAD_MIN", "MINUTES_PER_DAY", "MIN_DAYS", "STORE",
    "WEEKDAY", "WEEKEND", "circular_median", "circular_spread", "clock",
    "load", "profile", "record", "save", "settle_minute", "wake_minute",
]
