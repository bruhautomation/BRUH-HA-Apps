"""A washer, a dishwasher, a dryer: idle, running, and finished.

The chore engine the roadmap asks for is "the dishwasher finished and
has not been opened in an hour" — and the hard part is not the chore, it
is knowing the dishwasher finished. Nothing in Home Assistant says so. A
smart plug reports watts, and every rule anybody writes on top of one is
a number typed into a box: `> 10 W` is a running dishwasher in one house
and a phone charger in the next.

So the numbers are measured, per appliance, from its own history — the
same argument `baselines.py` makes about the word "unusual", applied to
a distribution that is a different shape. A power reading is not a band
with a middle and a spread; it is **bimodal**: hours near a floor, and
runs well above it. That shape is what an appliance *is*, and a sensor
that does not have it (a router, a standing fridge draw) gets no profile
rather than a guessed one.

Five rules, and four of them are about the ways this is confidently
wrong.

**The floor is a low percentile, never the minimum.** One reading of
zero during a power cut, or the second the plug was re-paired, would
otherwise set the idle level for the whole house.

**"Below the threshold" is not "finished".** A dishwasher's dry phase
draws almost nothing for twenty minutes and a washer pauses to soak, so
a machine that reports done the moment the draw drops reports done three
times a cycle. The wait is measured too: the gaps between draws are
*themselves* bimodal — lulls of minutes inside a cycle, idles of hours
between them — and the widest jump in that sorted list is the appliance
saying how long its own quiet phases last.

**A blip is not a cycle.** Every fridge compressor, every kettle, every
inrush when something is switched on clears a threshold for a moment.
A run under `MIN_RUN_MIN` never happened.

**"Unloaded" cannot be seen from power at all**, and this deliberately
does not pretend otherwise. A dishwasher that finished and was emptied
draws exactly what one that finished and was not draws. Three states are
measured — `idle`, `running`, `finished` — and the fourth is a person
saying so, which is what the To-do list and the notification buttons are
for. A state machine that inferred it would be inventing the one fact
the chore is about.

**And nothing here decides anything.** It answers what an appliance is
doing and when it stopped; whether that is worth telling somebody is the
check's, and the check has its own floors.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time

log = logging.getLogger("brain.appliances")

STORE = os.environ.get("BRAIN_APPLIANCE_FILE", "/data/appliances.json")

# Home Assistant keeps five-minute statistics for ten days and hourly
# ones forever, and an hour is useless here: a dishwasher's dry phase is
# twenty minutes and a kettle is ninety seconds. Ten days is what the
# resolution costs, and it is plenty — a machine's shape does not change.
HISTORY_DAYS = 10
BUCKET_S = 300.0
# The unit here is a DRAW — one contiguous above-threshold stretch — and
# not a cycle, because a cycle with a quiet phase is two draws and the
# gaps between draws are exactly what the settle time is measured from.
# Three draws is two gaps, which is the fewest a jump can be found in:
# the floor is not a taste, it is the arithmetic below needing something
# to work on.
MIN_DRAWS = 3
# The floor, as a percentile of the readings rather than the minimum.
IDLE_PCT = 20.0
# What "running" looks like, likewise: the top of the distribution
# without the one spike that would set it.
BUSY_PCT = 95.0
# Bimodal or nothing. A sensor whose busy level is not clearly above its
# floor is a constant draw, and a threshold through the middle of one
# would report a router as an appliance running all week.
# Both floors have to hold, and neither alone would do: a ratio alone
# passes a 3W-to-9W phone charger, and a span alone passes anything
# large that never switches off. A true zero floor passes the ratio by
# construction, which is right — nothing is more clearly bimodal than a
# machine that draws nothing at all between runs.
MIN_SPAN_W = 20.0
MIN_SPAN_RATIO = 3.0
# A quarter of the way up from the floor: above the noise, below any
# real draw. A fraction of the measured span rather than a wattage,
# because a wattage is the guess this module exists to avoid.
THRESHOLD_FRACTION = 0.25
# Shorter than this never happened — an inrush, a compressor, a kettle.
MIN_RUN_MIN = 8.0
# Bounds on the measured quiet phase. The floor is what stops a machine
# with no lulls at all reporting "finished" during a one-bucket dip; the
# cap is what stops a sensor with one strange gap deciding a cycle lasts
# all afternoon.
MIN_SETTLE_MIN = 10.0
MAX_SETTLE_MIN = 45.0
# Past this a finish is history rather than a chore.
MAX_ENTITIES = 40


# ---------------------------------------------------------------------------
# The shape of one appliance
# ---------------------------------------------------------------------------

def percentile(values: list[float], pct: float) -> float:
    """The `pct`th percentile by nearest rank. Empty is 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round(pct / 100.0 * (len(ordered) - 1)))
    return float(ordered[max(0, min(idx, len(ordered) - 1))])


def is_power(eid: str, attrs: dict) -> bool:
    """Whether this entity reports watts the recorder keeps five-minute
    statistics for. Anything else has no shape to measure."""
    if not str(eid or "").startswith("sensor."):
        return False
    attrs = attrs or {}
    if attrs.get("device_class") != "power":
        return False
    return attrs.get("state_class") == "measurement"


def candidates(states: dict) -> list[str]:
    """Power sensors worth asking about, in a stable order.

    Sorted before the cap for `baselines.candidates`' reason: an
    arbitrary set that changed nightly would give half the house a
    profile that keeps appearing and disappearing.
    """
    out = []
    for eid, st in (states or {}).items():
        if not isinstance(st, dict):
            continue
        if not is_power(eid, st.get("attributes") or {}):
            continue
        if st.get("state") in ("unavailable", "unknown", None):
            continue
        out.append(eid)
    return sorted(out)[:MAX_ENTITIES]


def _readings(points: list) -> list[tuple[float, float]]:
    """`[(start, watts), ...]` from statistics rows, rubbish dropped."""
    out = []
    for row in points or []:
        if not isinstance(row, dict):
            continue
        start, value = row.get("start"), row.get("mean")
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        when = float(start) / 1000.0 if float(start) > 1e11 else float(start)
        out.append((when, float(value)))
    out.sort()
    return out


def segments(points: list[tuple[float, float]], threshold: float
             ) -> list[tuple[float, float]]:
    """The above-threshold stretches, as `(start, end)` pairs.

    A stretch ends one bucket after its last reading, because a
    five-minute statistic describes the five minutes that follow it —
    which also means a single low bucket does not split a run, and that
    is deliberate: one dip is noise, and the quiet phase that genuinely
    interrupts a cycle is what `settle_minutes` measures.
    """
    runs: list[list[float]] = []
    for when, value in points:
        if value < threshold:
            continue
        if runs and when - runs[-1][1] <= BUCKET_S:
            runs[-1][1] = when + BUCKET_S
        else:
            runs.append([when, when + BUCKET_S])
    return [(a, b) for a, b in runs]


def settle_minutes(runs: list[tuple[float, float]]) -> float | None:
    """How long this appliance goes quiet *inside* a cycle.

    The gaps between draws are bimodal in the same way the draws are:
    lulls of minutes within one cycle, and idles of hours between them.
    The widest jump in the sorted gaps is where one becomes the other,
    and it is the appliance's own answer rather than a number typed here.

    None when there is nothing to measure it from — which is a different
    answer from "no lulls", and the caller falls back to the floor.
    """
    gaps = sorted((runs[i + 1][0] - runs[i][1]) / 60.0
                  for i in range(len(runs) - 1))
    gaps = [g for g in gaps if g > 0]
    if len(gaps) < 2:
        return None
    widest, at = 0.0, 0
    for i in range(len(gaps) - 1):
        step = gaps[i + 1] - gaps[i]
        if step > widest:
            widest, at = step, i
    # Everything up to the jump is a lull; the wait has to outlast the
    # longest of them or the machine reports finished mid-cycle.
    return gaps[at]


def profile(points: list, now: float | None = None) -> dict | None:
    """What this sensor's own history says about it, or None.

    None means "this is not an appliance" — a constant draw, too little
    history, or too few runs to have measured a quiet phase from. It is
    never a guess with low confidence attached.
    """
    now = time.time() if now is None else now
    readings = _readings(points)
    if len(readings) < 288:  # a day of five-minute buckets
        return None
    watts = [v for _t, v in readings]
    idle = percentile(watts, IDLE_PCT)
    busy = percentile(watts, BUSY_PCT)
    span = busy - idle
    # Bimodal or nothing: see MIN_SPAN_W.
    if span < MIN_SPAN_W or busy < idle * MIN_SPAN_RATIO:
        return None

    threshold = idle + span * THRESHOLD_FRACTION
    runs = [r for r in segments(readings, threshold)
            if (r[1] - r[0]) / 60.0 >= MIN_RUN_MIN]
    if len(runs) < MIN_DRAWS:
        return None

    measured = settle_minutes(runs)
    settle = MIN_SETTLE_MIN if measured is None else measured
    settle = max(MIN_SETTLE_MIN, min(settle, MAX_SETTLE_MIN))
    lengths = sorted((b - a) / 60.0 for a, b in runs)

    return {
        "idle_w": round(idle, 2),
        "busy_w": round(busy, 2),
        "threshold_w": round(threshold, 2),
        "settle_min": round(settle, 1),
        "measured_settle": measured is not None,
        # Draws, not cycles: see MIN_DRAWS.
        "draws": len(runs),
        "typical_run_min": round(percentile(lengths, 50.0), 1),
        "built_at": int(now),
    }


# ---------------------------------------------------------------------------
# What it is doing now
# ---------------------------------------------------------------------------

IDLE, RUNNING, FINISHED = "idle", "running", "finished"


def state_at(shape: dict, points: list, now: float | None = None) -> dict:
    """`{state, since, finished_at, watts}` for one appliance.

    `finished` is a run that ended and has stayed below the threshold
    for longer than this appliance's own quiet phase — which is the
    whole reason the phase is measured. Until then it is still
    `running`, dry cycle and all.

    There is no `unloaded`, deliberately: see the module docstring.
    """
    now = time.time() if now is None else now
    readings = _readings(points)
    if not shape or not readings:
        return {"state": "", "since": 0.0, "finished_at": 0.0, "watts": None}

    threshold = float(shape.get("threshold_w") or 0)
    settle_s = float(shape.get("settle_min") or MIN_SETTLE_MIN) * 60.0
    runs = [r for r in segments(readings, threshold)
            if (r[1] - r[0]) / 60.0 >= MIN_RUN_MIN]
    watts = readings[-1][1]

    if not runs:
        return {"state": IDLE, "since": readings[0][0], "finished_at": 0.0,
                "watts": watts}

    last_start, last_end = runs[-1]
    quiet = now - last_end
    if quiet <= settle_s:
        # Inside its own quiet phase: still running, however low the
        # draw is right now.
        return {"state": RUNNING, "since": last_start, "finished_at": 0.0,
                "watts": watts}
    return {"state": FINISHED, "since": last_end, "finished_at": last_end,
            "watts": watts}


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"entities": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entities"), dict):
        return {"entities": {}}
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
        log.warning("could not write the appliance store: %s", exc)


def age_days(payload: dict, now: float | None = None) -> float | None:
    built = (payload or {}).get("built_at")
    if not isinstance(built, (int, float)) or not built:
        return None
    return max(0.0, ((time.time() if now is None else now) - built) / 86400.0)


async def fetch(session, ids: list[str], start: dt.datetime,
                end: dt.datetime | None = None) -> dict:
    """Five-minute means per entity, or {} when nothing answered."""
    import ha_data  # noqa: PLC0415

    out: dict[str, list] = {}
    command: dict = {
        "type": "recorder/statistics_during_period",
        "start_time": start.isoformat(),
        "statistic_ids": [],
        "period": "5minute",
        "types": ["mean"],
    }
    if end is not None:
        command["end_time"] = end.isoformat()
    for i in range(0, len(ids), 10):
        command = {**command, "statistic_ids": ids[i:i + 10]}
        try:
            results = await ha_data._ws_commands(session, [command])
        except Exception as exc:  # noqa: BLE001 — a batch that failed is a
            # batch that failed; the rest of the house still gets a profile.
            log.info("appliance statistics batch failed: %s", exc)
            continue
        for sid, rows in (results[0] or {}).items():
            out[sid] = rows or []
    return out


async def build(session, states: dict, now: float | None = None,
                path: str | None = None) -> dict:
    """Measure every power sensor's shape and write the store."""
    now = time.time() if now is None else now
    ids = candidates(states)
    payload: dict = {"built_at": int(now), "days": HISTORY_DAYS,
                     "asked": len(ids), "entities": {}}
    if not ids:
        save(payload, path)
        return payload

    start = dt.datetime.fromtimestamp(now - HISTORY_DAYS * 86400,
                                      tz=dt.timezone.utc)
    series = await fetch(session, ids, start)
    for eid, points in series.items():
        shape = profile(points, now)
        if not shape:
            continue
        name = ((states.get(eid) or {}).get("attributes") or {}).get(
            "friendly_name")
        if name:
            shape["name"] = str(name)[:60]
        payload["entities"][eid] = shape
    save(payload, path)
    return payload


__all__ = [
    "BUCKET_S", "BUSY_PCT", "FINISHED", "HISTORY_DAYS", "IDLE", "IDLE_PCT",
    "MAX_ENTITIES", "MAX_SETTLE_MIN", "MIN_DRAWS", "MIN_RUN_MIN",
    "MIN_SETTLE_MIN", "MIN_SPAN_RATIO", "MIN_SPAN_W", "RUNNING", "STORE",
    "THRESHOLD_FRACTION", "age_days", "build", "candidates", "fetch",
    "is_power", "load", "percentile", "profile", "save", "segments",
    "settle_minutes", "state_at",
]
