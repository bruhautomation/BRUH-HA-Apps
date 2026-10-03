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
# What "running" looks like: the middle of the readings the machine spent
# RUNNING — those above the noise floor (see `noise_floor`) — and never a
# percentile of the whole window. A 95th percentile of ten days is the
# idle level for any machine that ran less than half a day of them, so a
# washer doing six 90-minute loads a week read busy == idle and was
# reported as "not an appliance", which is the commonest washer and dryer
# there is. Measured against the shipped arithmetic: 1 W idle, 500 W
# running, ten days — nothing up to eight 90-minute cycles, a profile at
# nine. The median of the running readings, because a quarter of the
# typical running draw is what separates idle from running: the peak (a
# heater's 2 kW) would put the threshold above the motor phase that is
# just as much the machine working.
BUSY_PCT = 50.0
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
# How many power sensors one nightly pass reads, because five-minute
# statistics are many rows per sensor and this runs on a Pi. Past the cap
# what goes first is NOT what the chore exists for: a sensor named as a
# washer, a dryer or a dishwasher is ranked ahead of the rest (`select`),
# because an inverter's twelve circuits sorting ahead of `sensor.washer_
# power` is how chore.waiting went silent on exactly the houses with the
# most power monitoring. What the cap cut is recorded and reported.
MAX_ENTITIES = 40
# How many of the cut ids ride in the store, for the diagnostics. The
# count is always there; the names are a sample.
CUT_SAMPLE = 20


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


def _chore_kind(eid: str, st: dict) -> str:
    """Which of the three chore machines this sensor is named as, or "".

    `checks.chores.kind_of` and nothing else, read on the friendly name
    AND the id (a plug called "Utility Plug" with an id of
    `sensor.washer_power` is a washer), so the cap's ranking and the
    check's gate cannot disagree about which sensors those are.
    """
    try:
        from checks import chores  # noqa: PLC0415 — panel-local
    except Exception:  # noqa: BLE001 — a ranking, never a reason to fail
        return ""
    name = str(((st or {}).get("attributes") or {}).get("friendly_name") or "")
    return chores.kind_of(f"{name} {eid}")


def select(states: dict) -> dict:
    """The power sensors to read tonight, and what the cap left out.

    `{"ids": [...], "eligible": n, "cut": [...]}`. A washer, dryer or
    dishwasher by name is ranked first; the rest are sorted by id, for
    `baselines.candidates`' reason — an arbitrary set that changed
    nightly would give half the house a profile that keeps appearing and
    disappearing.
    """
    out = []
    for eid, st in (states or {}).items():
        if not isinstance(st, dict):
            continue
        if not is_power(eid, st.get("attributes") or {}):
            continue
        if st.get("state") in ("unavailable", "unknown", None):
            continue
        out.append((0 if _chore_kind(eid, st) else 1, eid))
    ranked = [eid for _rank, eid in sorted(out)]
    return {"ids": ranked[:MAX_ENTITIES], "eligible": len(ranked),
            "cut": sorted(ranked[MAX_ENTITIES:])}


def candidates(states: dict) -> list[str]:
    """The ids `select` reads, in the order it reads them."""
    return select(states)["ids"]


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


def noise_floor(idle: float) -> float:
    """The least a reading has to be to count as the machine running.

    Both bimodality floors at once (`MIN_SPAN_W` above idle and
    `MIN_SPAN_RATIO` times it), which is what keeps a phone charger's
    3 W to 9 W and a router's steady draw out: neither ever reads above
    it, so neither has a running level to measure.
    """
    return max(idle + MIN_SPAN_W, idle * MIN_SPAN_RATIO)


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
    # Bimodal or nothing: the busy level is read off the readings that
    # clear the noise floor, however few of the window they are. See
    # BUSY_PCT for why it is not a percentile of the whole window.
    running = [w for w in watts if w >= noise_floor(idle)]
    if not running:
        return None
    busy = percentile(running, BUSY_PCT)
    span = busy - idle

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


def progress(payload: dict | None = None, path: str | None = None,
             now: float | None = None) -> dict:
    """How many machines in this house have a measured power shape.

    `chore_capable` is the narrower count and both belong in the answer:
    the measurement is universal — every power sensor with an appliance's
    shape gets a profile — while a *chore* is one of three machines
    matched on its name, so "four profiled, none of them a washer" is why
    no chore ever arrives, and one number could not say it.
    """
    import baselines  # noqa: PLC0415 — one staleness floor, one home
    import house  # noqa: PLC0415 — panel-local, one shape and one eta

    now = time.time() if now is None else now
    payload = load(path) if payload is None else payload
    entities = payload.get("entities") or {}
    built = int(payload.get("built_at") or 0) or None
    asked = int(payload.get("asked") or 0)
    cut = int(payload.get("cut_count") or 0)
    chores = 0
    try:
        from checks import chores as chore_check  # noqa: PLC0415
        chores = len([e for e in entities.values()
                      if isinstance(e, dict)
                      and chore_check.kind_of(e.get("name") or "")])
    except Exception as exc:  # noqa: BLE001 — the narrower count is a detail
        log.debug("could not count chore machines: %s", exc)
    common = {"unit": "machines", "need": 1, "have": len(entities),
              "detail": {"profiled": len(entities), "chore_capable": chores,
                         "cut": cut},
              "updated_at": built, "per_unit_s": baselines.PROGRESS_UNIT_S,
              "now": now}

    if payload.get("error"):
        return house.progress(
            state=house.UNAVAILABLE, reason=str(payload["error"])[:200],
            summary=f"The last pass could not measure anything: {payload['error']}.",
            **common)
    if not built:
        return house.progress(
            state=house.NOT_STARTED, reason="no pass has run yet",
            summary=("Nothing measured yet — the first pass runs overnight "
                     f"and reads {HISTORY_DAYS} days of power readings."),
            **common)
    if not asked:
        return house.progress(
            state=house.UNAVAILABLE,
            reason="no power sensor in this house",
            summary=("No power sensor, so there is no machine whose own "
                     "watts could say when it finished."),
            **common)
    if baselines.is_stale(payload, now):
        return house.progress(
            state=house.STALE,
            reason=f"last measured {house.days_ago(built, now)}",
            summary=(f"Measured {house.days_ago(built, now)} — the nightly "
                     "pass has not run since."),
            **common)
    # The cap's cut, in words, wherever a sentence is said: a machine the
    # pass never read is the one silence nothing else could explain.
    beyond = (f" ({cut} more power sensors were past the nightly cap of "
              f"{MAX_ENTITIES} and were not read)" if cut else "")
    if entities:
        said = (f"{house.plural(len(entities), 'machine')} measured of "
                f"{asked} power sensors")
        said += (f" · {chores} of them a washer, dryer or dishwasher"
                 if chores else
                 " · none of them named as a washer, dryer or dishwasher, so "
                 "no chore is raised")
        return house.progress(state=house.READY, summary=said + beyond + ".",
                              **common)
    return house.progress(
        state=house.COLLECTING,
        reason=(f"{asked} power sensors read, none that ran "
                f"{MIN_DRAWS} separate times above its own idle yet"),
        summary=(f"{house.plural(asked, 'power sensor')} read, none that has "
                 f"run {MIN_DRAWS} separate times above its own idle in the "
                 f"last {HISTORY_DAYS} days{beyond}."),
        **common)


async def fetch(session, ids: list[str], start: dt.datetime,
                end: dt.datetime | None = None) -> dict | None:
    """Five-minute means per entity.

    `{}` is the recorder holding nothing for these ids; None is the
    recorder refusing every batch (`_ws_commands` answers None for a
    command Core rejected). The nightly `build` and the checks snapshot
    both branch on the difference.
    """
    import ha_data  # noqa: PLC0415

    if not ids:
        return {}
    out: dict[str, list] = {}
    answered = 0
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
        rows_by_id = results[0] if results else None
        if not isinstance(rows_by_id, dict):
            log.info("appliance statistics batch refused by the recorder")
            continue
        answered += 1
        for sid, rows in rows_by_id.items():
            out[sid] = rows or []
    return out if answered else None


async def build(session, states: dict, now: float | None = None,
                path: str | None = None) -> dict:
    """Measure every power sensor's shape and write the store.

    A fetch the recorder refused writes nothing and hands back the
    previous store with `error` beside it (`baselines.refused`); a house
    with no power sensors still writes an empty one.
    """
    import baselines  # noqa: PLC0415

    now = time.time() if now is None else now
    chosen = select(states)
    ids = chosen["ids"]
    payload: dict = {"built_at": int(now), "days": HISTORY_DAYS,
                     "asked": len(ids), "eligible": chosen["eligible"],
                     "cut_count": len(chosen["cut"]),
                     "cut": chosen["cut"][:CUT_SAMPLE], "entities": {}}
    if chosen["cut"]:
        log.info("appliances: %d power sensors past the cap of %d were not "
                 "read", len(chosen["cut"]), MAX_ENTITIES)
    if not ids:
        save(payload, path)
        return payload

    start = dt.datetime.fromtimestamp(now - HISTORY_DAYS * 86400,
                                      tz=dt.timezone.utc)
    series = await fetch(session, ids, start)
    if series is None:
        return baselines.refused(
            "appliances", load(path),
            f"the recorder did not answer for any of the {len(ids)} power "
            "sensors asked about")
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
    "is_power", "load", "noise_floor", "percentile", "profile", "progress",
    "save", "segments", "select", "settle_minutes", "state_at",
]
