"""What is normal for this house, per entity, per hour of the week.

"Unusual" is the word behind most of what people want a smart home to
notice — water running at night, a freezer drifting, a boiler on for
twice as long as it usually is — and until there is a number behind it,
every rule that uses it is a threshold somebody guessed. This turns it
into arithmetic: for each numeric entity, what it normally reads at this
hour of this day of the week, and how far it normally strays.

Five decisions shape what is here.

**The bucket is an hour of the week, in the HOUSE's timezone.** A day of
the week matters (a weekday 7am is not a Sunday 7am) and so does the
local hour — UTC would smear every household's morning across two
buckets and move it twice a year. The timezone comes from the cache
`run.sh` writes; a house whose timezone cannot be read gets UTC and says
so, rather than silently bucketing somebody's evening as their morning.

**Spread is the median absolute deviation, not the standard deviation.**
One enormous reading — a meter that spiked when the oven came on — sets a
standard deviation wide enough to swallow everything that follows, so the
band it draws is a band nothing can ever fall outside. The MAD is the
same measurement with that reading outvoted.

**A sensor that never moves has no spread, and dividing by it makes every
change an emergency.** A thermostat's setpoint sits at 20.0 for weeks;
its MAD is zero, and 20.5 is then infinitely unusual. So the spread has a
floor, relative to the reading's own size, and an entity whose whole
history is one value is reported as having no useful baseline at all
rather than as one that is exquisitely sensitive.

**A bucket with too few samples says nothing.** Four weeks of history
gives four samples per hour-of-week bucket at best, and a house that has
been up for six days has one. `MIN_SAMPLES` is what stops "unusual" from
meaning "I have seen this hour twice".

**Nothing here decides anything.** It answers "how far outside its own
normal is this", in units of that entity's own spread, and the checks and
the model decide what is worth saying. A baseline that also raised alarms
would be two rules in one place, and the threshold would be invisible.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

log = logging.getLogger("brain.baselines")

STORE = os.environ.get("BRAIN_BASELINE_FILE", "/data/baselines.json")
TZ_CACHE = os.environ.get("BRAIN_TZ_CACHE",
                          "/config/.brain/cache/ha_timezone")

# Four weeks: enough for four samples in every hour-of-week bucket, and
# short enough that a house that changed in the spring is not being
# measured against its winter.
HISTORY_DAYS = 28
# Below this many samples a bucket is an anecdote, not a normal.
MIN_SAMPLES = 3
# The floor under a bucket's spread, as a fraction of its own median. A
# reading that never moves would otherwise make every change infinite.
MIN_SPREAD_FRACTION = 0.02
# And an absolute floor, for a reading whose median is zero (a power
# meter at night, a rain gauge). Without it, 0.0 ± 0 has the same
# problem in a different disguise.
MIN_SPREAD_ABS = 1e-6
# An entity whose entire history is one value has no baseline worth
# having. Reported as such rather than as one that is very sensitive.
FLAT_MAD_FRACTION = 0.0
# Past this a baseline describes a house that may have changed.
STALE_DAYS = 10.0
# One statistics call per batch; the same bound the checks snapshot uses,
# for the same reason — a Pi answers a batch comfortably and a thousand
# ids at once is a request that times out.
BATCH = 50
# 28 days of hourly rows is 672 per entity. The cap is on entities, not
# rows: the fetch is nightly and local, but a house with two thousand
# numeric sensors should not turn it into a five-minute pass.
MAX_ENTITIES = 400

HOURS_PER_WEEK = 168

# --- the trend, which is a different question from the band -------------
# A drift needs whole daily cycles under it: a fridge's hourly means rise
# and fall every day, and a line fitted across three days is fitting that
# cycle rather than any drift.
TREND_MIN_DAYS = 14.0
# Fewer hourly points than this and the line is drawn through gaps.
TREND_MIN_POINTS = 120
# A `total` or `total_increasing` sensor only ever goes up — that is what
# the state class means — so a trend on one says nothing at all. This is
# the single way this check could have fired on every energy meter in
# every house, and it is a property of the class rather than of the row.
TREND_STATE_CLASSES = frozenset({"measurement"})


# ---------------------------------------------------------------------------
# The house's own clock
# ---------------------------------------------------------------------------

def house_timezone(path: str | None = None) -> tuple[dt.tzinfo, str]:
    """The house's timezone, and its name.

    Falls back to UTC *and says which* — a baseline bucketed in the wrong
    timezone is not a slightly worse baseline, it is somebody's evening
    filed as their morning, and nothing downstream could tell.
    """
    try:
        with open(path or TZ_CACHE, "r", encoding="utf-8") as fh:
            name = fh.read().strip()
    except OSError:
        name = ""
    if name:
        try:
            from zoneinfo import ZoneInfo  # noqa: PLC0415 — stdlib, optional data
            return ZoneInfo(name), name
        except Exception:  # noqa: BLE001 — an unknown zone is a missing zone
            log.info("timezone %r is not one this system knows; using UTC", name[:40])
    return dt.timezone.utc, "UTC"


def hour_of_week(ts: float, tz: dt.tzinfo) -> int:
    """0 = Monday 00:00 local, 167 = Sunday 23:00 local."""
    when = dt.datetime.fromtimestamp(ts, tz)
    return when.weekday() * 24 + when.hour


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------

def median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def mad(values: list[float], centre: float | None = None) -> float:
    """Median absolute deviation — the spread that one outlier cannot set."""
    if not values:
        return 0.0
    centre = median(values) if centre is None else centre
    return median([abs(v - centre) for v in values])


def least_squares(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Slope and intercept through (x, y), or None when there is no line.

    The one copy. `checks/forecasts.py` fits the same line through a
    battery's discharge and this fits it through a month of hourly means;
    two implementations of "the slope of these points" is two answers to
    a question that has one, and the copy that drifts is the one nobody
    is looking at.
    """
    n = len(points)
    if n < 2:
        return None
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    den = n * sxx - sx * sx
    if abs(den) < 1e-9:
        return None
    slope = (n * sxy - sx * sy) / den
    return slope, (sy - slope * sx) / n


def spread_floor(centre: float) -> float:
    """The smallest spread a bucket may claim.

    Without it a constant reading divides by zero and every change is an
    emergency; the fraction handles a big number and the absolute handles
    a reading whose normal is zero.
    """
    return max(abs(centre) * MIN_SPREAD_FRACTION, MIN_SPREAD_ABS)


def summarise(values: list[float]) -> dict | None:
    """One bucket, or None when there is not enough of it to mean anything."""
    if len(values) < MIN_SAMPLES:
        return None
    centre = median(values)
    return {
        "median": round(centre, 4),
        "spread": round(max(mad(values, centre), spread_floor(centre)), 6),
        "n": len(values),
    }


def build_buckets(rows: list[dict], tz: dt.tzinfo) -> dict:
    """Hourly statistics rows as {hour_of_week: bucket} plus an overall.

    ``overall`` is what answers for an hour this house has no samples in
    yet — a fortnight-old install has most of the week empty, and "no
    baseline at all" and "no baseline for 3am on a Tuesday" are different
    answers to somebody asking whether a reading is odd.
    """
    by_bucket: dict[int, list[float]] = {}
    every: list[float] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        start = row.get("start")
        value = row.get("mean")
        if not isinstance(start, (int, float)) or isinstance(start, bool):
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        by_bucket.setdefault(hour_of_week(float(start), tz), []).append(float(value))
        every.append(float(value))

    if not every:
        return {}
    # A reading that has never moved has no baseline worth having. Saying
    # so is the honest answer; the alternative is a band so narrow that
    # every change clears it.
    if mad(every) <= FLAT_MAD_FRACTION and len(set(every)) <= 1:
        return {"flat": True, "value": round(every[0], 4), "samples": len(every)}

    buckets = {}
    for bucket, values in by_bucket.items():
        summary = summarise(values)
        if summary:
            buckets[str(bucket)] = summary
    overall = summarise(every)
    if not overall:
        return {}
    return {"buckets": buckets, "overall": overall, "samples": len(every)}


def deviation(value: float, baseline: dict, bucket: int) -> dict | None:
    """How far outside its own normal a reading is, in its own spreads.

    ``None`` when this entity has no usable baseline, or none for this
    hour and none overall — which is a different answer from "normal",
    and every caller has to tell them apart.
    """
    if not baseline or baseline.get("flat"):
        return None
    rows = baseline.get("buckets") or {}
    entry = rows.get(str(bucket))
    source = "hour"
    if not entry:
        entry = baseline.get("overall")
        source = "overall"
    if not entry:
        return None
    spread = entry.get("spread") or spread_floor(entry.get("median") or 0.0)
    centre = entry.get("median") or 0.0
    return {
        "value": value,
        "median": centre,
        "spread": spread,
        "sigmas": round((value - centre) / spread, 2),
        "n": entry.get("n", 0),
        "source": source,
    }


def trend(rows: list[dict], built: dict, tz: dt.tzinfo,
          now: float) -> dict | None:
    """How far the readings have travelled across the window, and how surely.

    A different question from `deviation`, and one that question cannot
    answer. `base.unusual` buckets by hour of the week, so a *drift* moves
    the bucket along with the reading: a freezer 6°C warmer than a month
    ago has bucket samples of 0, 2, 4, 6 — a median of 3 and a spread of
    2 — and today's 6 comes out at one and a half spreads. Structurally
    invisible, however far it has gone, because every single reading is
    inside the band the drift itself widened.

    So this fits a line instead, and it fits it to what is left once the
    week's own pattern is taken out: each hourly mean minus the median
    for its hour of the week. Subtracting a constant per bucket removes
    the daily and weekly shape without touching a slope, so what is left
    is the drift plus genuine noise — and the noise is then measured as
    the spread *about the line*, which is the one estimate the drift
    cannot inflate.

    Returns the measurement and nothing else. Whether four spreads of
    travel is worth telling somebody about is the check's judgement, and
    keeping it there is what stops the threshold from being invisible.
    """
    buckets = (built or {}).get("buckets") or {}
    overall = (built or {}).get("overall") or {}
    if not overall:
        return None

    points: list[tuple[float, float]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        start = row.get("start")
        value = row.get("mean")
        if not isinstance(start, (int, float)) or isinstance(start, bool):
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        entry = buckets.get(str(hour_of_week(float(start), tz))) or overall
        points.append(((float(start) - now) / 86400.0,
                       float(value) - (entry.get("median") or 0.0)))

    if len(points) < TREND_MIN_POINTS:
        return None
    points.sort()
    span = points[-1][0] - points[0][0]
    if span < TREND_MIN_DAYS:
        return None

    whole = least_squares(points)
    if whole is None:
        return None
    slope, intercept = whole

    # A line through a V has a slope and is not a drift. Both halves of
    # the window have to be going the same way, or what happened is that
    # something turned around in the middle of it.
    half = len(points) // 2
    first = least_squares(points[:half])
    second = least_squares(points[half:])
    consistent = bool(
        first and second
        and (first[0] > 0) == (second[0] > 0) == (slope > 0))

    residuals = [y - (slope * x + intercept) for x, y in points]
    noise = max(mad(residuals), spread_floor(overall.get("median") or 0.0))
    move = slope * span
    return {
        "per_day": round(slope, 6),
        "move": round(move, 4),
        "days": round(span, 2),
        "noise": round(noise, 6),
        "spreads": round(abs(move) / noise, 2),
        "consistent": consistent,
        "points": len(points),
    }


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    """Whatever was last built, or an empty payload.

    A missing file is a house brAIn has not measured yet, which is a real
    state on a fresh install and reads as "no baselines" everywhere
    downstream — never as "nothing is unusual".
    """
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"built_at": 0, "tz": "", "entities": {}}
    if not isinstance(data, dict):
        return {"built_at": 0, "tz": "", "entities": {}}
    data.setdefault("entities", {})
    return data


def is_stale(payload: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    built = payload.get("built_at") or 0
    return (now - built) > STALE_DAYS * 86400


def age_days(payload: dict, now: float | None = None) -> float | None:
    now = time.time() if now is None else now
    built = payload.get("built_at") or 0
    if not built:
        return None
    return max(0.0, (now - built) / 86400.0)


def save(payload: dict, path: str | None = None) -> None:
    """Write the store. Skipped silently on a dev checkout with no /data.

    Uses the panel's atomic writer: the checks pass reads this file while
    the nightly build replaces it, and `tmp + rename` derived from the
    target name is the race every store in here already had once.
    """
    import atomic_write  # noqa: PLC0415 — panel-local, and this module is
                         # imported by the checks package without it

    target = path or STORE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    try:
        atomic_write.write_json(target, payload)
    except OSError as exc:
        log.warning("could not write the baseline store: %s", exc)


# ---------------------------------------------------------------------------
# The one thing here that touches the network
# ---------------------------------------------------------------------------

def candidates(states: dict) -> list[str]:
    """Numeric entities worth a baseline, in a stable order.

    Anything with a `state_class` is what the recorder keeps long-term
    statistics for, so asking about anything else is asking for rows that
    do not exist. Sorted so the cap takes the same entities every night
    rather than a different arbitrary set each time.
    """
    out = []
    for eid, st in (states or {}).items():
        if not isinstance(st, dict):
            continue
        attrs = st.get("attributes") or {}
        if not attrs.get("state_class"):
            continue
        if st.get("state") in ("unavailable", "unknown", None):
            continue
        out.append(eid)
    return sorted(out)[:MAX_ENTITIES]


async def fetch_hourly(session, ids: list[str], now: float,
                       days: int = HISTORY_DAYS) -> dict:
    """Hourly means per entity for the window, or {} if nothing answered."""
    import ha_data  # noqa: PLC0415 — see the checks snapshot's own note

    start = dt.datetime.fromtimestamp(now - days * 86400, tz=dt.timezone.utc)
    out: dict[str, list] = {}
    for i in range(0, len(ids), BATCH):
        batch = ids[i:i + BATCH]
        try:
            results = await ha_data._ws_commands(session, [{
                "type": "recorder/statistics_during_period",
                "start_time": start.isoformat(),
                "statistic_ids": batch,
                "period": "hour",
                "types": ["mean"],
            }])
        except Exception as exc:  # noqa: BLE001 — a batch that failed is a
            # batch that failed; the rest of the house still gets a baseline.
            log.info("baseline statistics batch failed: %s", exc)
            continue
        for sid, rows in (results[0] or {}).items():
            clean = []
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                start_ts = row.get("start")
                if isinstance(start_ts, (int, float)) and start_ts > 1e11:
                    # Core reports milliseconds here and seconds elsewhere.
                    start_ts = start_ts / 1000.0
                clean.append({"start": start_ts, "mean": row.get("mean")})
            out[sid] = clean
    return out


async def build(session, states: dict, now: float | None = None,
                path: str | None = None) -> dict:
    """Measure the house and write the store. Returns the payload."""
    now = time.time() if now is None else now
    tz, tz_name = house_timezone()
    ids = candidates(states)
    payload = {"built_at": int(now), "tz": tz_name, "days": HISTORY_DAYS,
               "asked": len(ids), "entities": {}}
    if not ids:
        save(payload, path)
        return payload
    rows = await fetch_hourly(session, ids, now)
    for eid, series in rows.items():
        built = build_buckets(series, tz)
        if not built:
            continue
        attrs = ((states.get(eid) or {}).get("attributes") or {})
        unit = attrs.get("unit_of_measurement")
        if unit:
            built["unit"] = str(unit)[:16]
        # A `total_increasing` meter goes up because that is what the
        # class means. Fitting a line to one finds a slope every time,
        # in every house, so the gate is here rather than in the check:
        # a trend nothing should read is a trend nothing should store.
        if str(attrs.get("state_class") or "") in TREND_STATE_CLASSES:
            moved = trend(series, built, tz, now)
            if moved:
                built["trend"] = moved
        payload["entities"][eid] = built
    save(payload, path)
    log.info("baselines: %d of %d entities measured over %d days (%s)",
             len(payload["entities"]), len(ids), HISTORY_DAYS, tz_name)
    return payload
