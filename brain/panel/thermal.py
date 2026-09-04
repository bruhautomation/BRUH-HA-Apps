"""How fast each room loses heat, and how fast anything can put it back.

Every climate capability people actually want — start the heating so the
bedroom is warm *when we get up*, tell me a window is open because the
room is cooling faster than it can, warn me the pipes will freeze by
morning, say what a 17 °C setback would cost — is the same two numbers
about a room, and brAIn held neither. Without them each of those is a
threshold somebody typed into a box, and a threshold that is right in one
house is wrong in the next: a stone cottage and a new flat lose heat an
order of magnitude apart, and so do two rooms of one house.

The two numbers are Newton's:

    dT/dt  =  h  −  k · (T_in − T_out)

``k`` is the **loss coefficient**, per hour: how quickly the room falls
towards outdoors when nothing is heating it. Its reciprocal is the room's
time constant, which is the number people have an intuition for — "this
room holds its heat for about eight hours". ``h`` is the **gain**, in
degrees per hour: what the heating adds while it is calling.

Both are measured from a month of hourly statistics, per room, and every
rule below exists because of a way this is confidently wrong.

**The sun is the confounder, and night is the gate.** A south-facing room
warms with the heating off, and a fit that includes an afternoon reports
a room that gains heat as it gets colder outside. So ``k`` is measured
only in the deep-night hours — no sun, and in most houses no heating
either. This is the same shape of gate as the ``state_class`` one on
``baselines.trend``: a measurement that would be wrong in every house
belongs in the *build*, not in the check that reads it.

**A fit is not a measurement until it is graded.** A month of night hours
in a house whose outdoor temperature barely moved has no leverage — every
point sits at the same x, the line through them is whatever the noise
says, and it looks exactly like a real answer. So the outdoor delta has
to *span* something (``MIN_DELTA_SPAN``), the fit is graded against the
scatter about its own line, and a ``k`` whose signal does not clear that
scatter is no ``k`` at all.

**A number outside physics is not a room.** A time constant of twenty
minutes is a thermometer in a draught; one of a fortnight is a
thermometer in a wall. ``k`` is required to land inside a band a building
can actually occupy, and a room outside it is reported unmeasured rather
than measured badly.

**Indoors and outdoors have to agree about what a degree is.** ``k`` is
per hour and unit-free, but only if both halves of ``T_in − T_out`` are
in the same unit — a Fahrenheit reference against a Celsius room is a
loss rate wrong by 1.8 and nothing downstream could tell. A room whose
unit does not match the reference gets no model.

**And a freezer has a device class of `temperature` too.** So does a hot
water tank and a barbecue probe. A room is a reading that spends the
month inside a band people live in; anything else is a temperature that
is not a room's.

**Nothing here decides anything.** It answers how fast a room loses heat
and how fast it can gain, and what those imply for a given night. Whether
any of that is worth telling somebody is the check's — the same split
`baselines.py` and `closures.py` keep, and for the same reason: a
measurement that also raised alarms would be two rules in one place with
the threshold invisible.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import os
import time

log = logging.getLogger("brain.thermal")

STORE = os.environ.get("BRAIN_THERMAL_FILE", "/data/thermal.json")

# The same month the baselines read, for the same reason: a season's worth
# of outdoor temperatures is what gives the fit its leverage, and a room's
# insulation does not change inside one.
HISTORY_DAYS = 28
# Deep night, local. Late enough that an evening's cooking and bodies have
# gone, early enough that no morning schedule has started, and dark at
# both ends in every latitude this is honest in.
NIGHT_FROM = 1
NIGHT_TO = 5
# An hourly mean is one point. A fortnight of nights is the floor; below
# it the line is drawn through a fortnight of weather rather than a house.
MIN_POINTS = 20
# The outdoor delta has to move, or the fit has no leverage and its slope
# is whatever the scatter says. Degrees, in the sensors' own unit.
MIN_DELTA_SPAN = 4.0
# What a building can be. A time constant under two hours is a
# thermometer in a draught; over five days is one inside a wall.
MIN_TAU_H = 2.0
MAX_TAU_H = 120.0
# The fit's slope has to beat the scatter about its own line. The signal
# is what the slope explains across the observed delta span; the noise is
# the residual spread. Two is deliberately modest — this gates "no line
# at all", not "a beautiful line".
MIN_FIT_RATIO = 2.0
# What a room is. A freezer, a hot water tank and a barbecue probe all
# carry `device_class: temperature`, and each would fit beautifully.
ROOM_MIN_C = 2.0
ROOM_MAX_C = 40.0
ROOM_MIN_F = 35.0
ROOM_MAX_F = 104.0
# The gain is the high end of what this room was seen to do once the loss
# it was fighting is added back — not the maximum, which is one hour when
# somebody opened the oven, and not the mean, which is every hour the
# heating was off.
GAIN_PCT = 90.0
MIN_GAIN_POINTS = 12
# Degrees per hour. Below this nothing was heating the room; the number is
# the noise floor of an hourly mean rather than a rate anybody would name.
MIN_GAIN = 0.15
# Rooms, capped so a house of ninety thermometers does not turn the
# nightly pass into a statistics job. Sorted before capping, so the cap
# takes the same rooms every night.
MAX_ROOMS = 60
# What the words in an entity's name have to say for it to be the outdoor
# reference. Longest phrase first is not needed here — these do not nest.
OUTDOOR_WORDS = ("outdoor", "outside", "exterior", "garden", "backyard",
                 "back yard", "patio", "balcony", "terrace", "porch",
                 "ambient", "external")
# A store older than this describes a season that has ended.
STALE_DAYS = 10.0

BATCH = 50
CELSIUS = ("°c", "c", "celsius")
FAHRENHEIT = ("°f", "f", "fahrenheit")


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------

def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile. `None` for nothing to take one of."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (pct / 100.0) * (len(ordered) - 1)
    low = int(math.floor(pos))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def normalise_unit(unit: object) -> str:
    """`°C` / `°F` / `""`. The empty string is "this is not a temperature"."""
    text = str(unit or "").strip().lower()
    if text in CELSIUS:
        return "°C"
    if text in FAHRENHEIT:
        return "°F"
    return ""


def in_room_band(value: float, unit: str) -> bool:
    """Whether a reading is one a person could be living in."""
    if unit == "°F":
        return ROOM_MIN_F <= value <= ROOM_MAX_F
    return ROOM_MIN_C <= value <= ROOM_MAX_C


def is_night(ts: float, tz: dt.tzinfo) -> bool:
    """Deep night, local — the hours with no sun and, usually, no schedule."""
    return NIGHT_FROM <= dt.datetime.fromtimestamp(ts, tz).hour < NIGHT_TO


def fit_loss(points: list[tuple[float, float]]) -> dict | None:
    """``k`` and its grade, from (T_in − T_out, dT/dt) pairs.

    The line is ``dT/dt = intercept − k · delta``, so the slope comes back
    negative in a room that loses heat and ``k`` is its negation. The
    intercept is kept because it is not a nuisance term: it is whatever
    was warming the room at zero delta, and a large one is the room saying
    the night hours were not free-running after all.
    """
    import baselines  # noqa: PLC0415 — panel-local, and this module is
                      # imported by the checks package without it

    if len(points) < MIN_POINTS:
        return None
    deltas = [p[0] for p in points]
    span = max(deltas) - min(deltas)
    if span < MIN_DELTA_SPAN:
        return None
    line = baselines.least_squares(points)
    if line is None:
        return None
    slope, intercept = line
    k = -slope
    if k <= 0:
        # A room that warms as it gets colder outside is not a room this
        # can describe: something is heating it, or the reference is not
        # outdoors. Either way the honest answer is no model.
        return None
    tau = 1.0 / k
    if not (MIN_TAU_H <= tau <= MAX_TAU_H):
        return None
    residuals = [y - (slope * x + intercept) for x, y in points]
    scatter = baselines.mad(residuals)
    signal = k * span
    # A scatter of zero is a synthetic series, not a suspiciously good
    # room: the ratio is infinite and the fit passes, which is right.
    ratio = float("inf") if scatter <= 0 else signal / scatter
    if ratio < MIN_FIT_RATIO:
        return None
    return {
        "k": round(k, 5),
        "tau_h": round(tau, 2),
        "intercept": round(intercept, 4),
        "span": round(span, 2),
        "fit": round(ratio, 2) if ratio != float("inf") else None,
        "points": len(points),
    }


def fit_gain(points: list[tuple[float, float]], k: float) -> dict | None:
    """``h`` — degrees per hour, from the hours the room was gaining.

    An hour's rise understates what the heating did by exactly the loss it
    was fighting, so the loss is added back before the percentile is
    taken: ``h = dT/dt + k · (T_in − T_out)``. A high percentile rather
    than the maximum, because the maximum is the hour somebody opened the
    oven; and rather than the mean, because the mean is mostly hours with
    the heating off.
    """
    gains = [rate + k * delta for delta, rate in points if rate > 0]
    if len(gains) < MIN_GAIN_POINTS:
        return None
    value = percentile(gains, GAIN_PCT)
    if value is None or value < MIN_GAIN:
        return None
    return {"gain": round(value, 3), "points": len(gains)}


# ---------------------------------------------------------------------------
# What the two numbers answer
# ---------------------------------------------------------------------------

def coast(entry: dict, indoor: float, outdoor: float,
          hours: float) -> float | None:
    """Where an unheated room is after `hours`, or None with no model."""
    k = (entry or {}).get("k")
    if not k or hours < 0:
        return None
    return outdoor + (indoor - outdoor) * math.exp(-k * hours)


def hours_to_fall(entry: dict, indoor: float, outdoor: float,
                  target: float) -> float | None:
    """How long an unheated room takes to fall to `target`.

    ``None`` when it never gets there — a room cannot fall below what is
    outside it, and saying "in 400 hours" about that would be a forecast
    with a date on something that will not happen.
    """
    k = (entry or {}).get("k")
    if not k:
        return None
    if indoor <= target:
        return 0.0
    if target <= outdoor:
        return None
    return math.log((indoor - outdoor) / (target - outdoor)) / k


def ceiling(entry: dict, outdoor: float) -> float | None:
    """The warmest this room gets at this outdoor temperature.

    ``T_out + h/k`` — where the gain and the loss balance. This is the one
    number that says a radiator is undersized rather than a schedule being
    short, and it needs both halves of the model.
    """
    k = (entry or {}).get("k")
    gain = (entry or {}).get("gain")
    if not k or not gain:
        return None
    return outdoor + gain / k


def hours_to_warm(entry: dict, indoor: float, outdoor: float,
                  target: float) -> float | None:
    """How long the heating takes to bring the room to `target`.

    ``None`` when the room cannot reach it at this outdoor temperature —
    which is not a slow answer, it is a different one, and the caller has
    to say so rather than rounding it up to a long wait.
    """
    top = ceiling(entry, outdoor)
    k = (entry or {}).get("k")
    if top is None or not k:
        return None
    if indoor >= target:
        return 0.0
    if target >= top:
        return None
    return math.log((top - indoor) / (top - target)) / k


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _empty() -> dict:
    return {"built_at": 0, "tz": "", "outdoor": "", "unit": "", "rooms": {},
            "coldest": None, "reason": ""}


def load(path: str | None = None) -> dict:
    """Whatever was last built, or an empty payload.

    A missing file is a house brAIn has not measured yet, which is a real
    state on a fresh install and reads as "no thermal model" everywhere
    downstream — never as "this house is fine".
    """
    try:
        with open(path or STORE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    data.setdefault("rooms", {})
    return data


def is_stale(payload: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    return (now - (payload.get("built_at") or 0)) > STALE_DAYS * 86400


def save(payload: dict, path: str | None = None) -> None:
    """Write the store. Skipped silently on a dev checkout with no /data."""
    import atomic_write  # noqa: PLC0415 — panel-local, as above

    target = path or STORE
    parent = os.path.dirname(target)
    if parent and not os.path.isdir(parent):
        return
    try:
        atomic_write.write_json(target, payload)
    except OSError as exc:
        log.warning("could not write the thermal store: %s", exc)


# ---------------------------------------------------------------------------
# Which sensors
# ---------------------------------------------------------------------------

def area_map(registries: dict | None) -> dict[str, str]:
    """`{entity_id: area name}` from the three registries.

    An entity's area is its own when it has one and its device's when it
    does not, which is Home Assistant's own rule and the same one
    ``checks._util.House.area_of`` follows. It lives here rather than in
    the checks package because the nightly build needs it too, and two
    answers to "which room is this in" is one too many.
    """
    registries = registries or {}
    names = {a.get("area_id"): (a.get("name") or a.get("area_id"))
             for a in (registries.get("areas") or [])
             if isinstance(a, dict) and a.get("area_id")}
    devices = {d.get("id"): d.get("area_id")
               for d in (registries.get("devices") or [])
               if isinstance(d, dict) and d.get("id")}
    out: dict[str, str] = {}
    for row in (registries.get("entities") or []):
        if not isinstance(row, dict) or not row.get("entity_id"):
            continue
        area = row.get("area_id") or devices.get(row.get("device_id") or "")
        name = names.get(area or "")
        if name:
            out[row["entity_id"]] = str(name)
    return out


def _temperature_sensors(states: dict) -> list[tuple[str, dict, str]]:
    """`(entity_id, state, unit)` for every statistics-backed thermometer."""
    out = []
    for eid, st in sorted((states or {}).items()):
        if not isinstance(st, dict) or not eid.startswith("sensor."):
            continue
        attrs = st.get("attributes") or {}
        if attrs.get("device_class") != "temperature":
            continue
        if attrs.get("state_class") != "measurement":
            continue
        unit = normalise_unit(attrs.get("unit_of_measurement"))
        if not unit:
            continue
        out.append((eid, st, unit))
    return out


def _looks_outdoor(eid: str, st: dict) -> bool:
    name = (str(((st.get("attributes") or {}).get("friendly_name")) or "")
            + " " + eid).lower()
    return any(word in name for word in OUTDOOR_WORDS)


def pick_outdoor(states: dict, areas: dict | None = None) -> tuple[str, str]:
    """The outdoor reference, and its unit. `("", "")` when there is none.

    Named first, because a sensor somebody called "Outside temperature" is
    somebody telling us; then a thermometer in no area at all, which is
    what a weather integration's own sensor almost always is. It is
    **recorded in the payload** rather than only used, because a reference
    nobody can check is a reference nobody can correct — and every ``k``
    in the house is measured against this one choice.
    """
    areas = areas or {}
    named: list[tuple[str, str]] = []
    unplaced: list[tuple[str, str]] = []
    for eid, st, unit in _temperature_sensors(states):
        if _looks_outdoor(eid, st):
            named.append((eid, unit))
        elif not areas.get(eid):
            unplaced.append((eid, unit))
    if named:
        return named[0]
    if unplaced:
        return unplaced[0]
    return "", ""


def room_candidates(states: dict, outdoor: str, unit: str,
                    areas: dict | None = None) -> list[str]:
    """Indoor thermometers worth a model, in a stable order.

    The unit has to match the reference's — ``k`` is only unit-free while
    both halves of the delta are in the same degrees — and the reading has
    to be one a person could be living in, which is what keeps the freezer
    and the hot water tank out.
    """
    areas = areas or {}
    out = []
    for eid, st, own in _temperature_sensors(states):
        if eid == outdoor or own != unit or _looks_outdoor(eid, st):
            continue
        try:
            value = float(st.get("state"))
        except (TypeError, ValueError):
            continue
        if not in_room_band(value, unit):
            continue
        if not areas.get(eid):
            # Without an area the finding cannot name a room, and an
            # unplaced thermometer is as likely to be a shed as a bedroom.
            continue
        out.append(eid)
    return sorted(out)[:MAX_ROOMS]


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

def _hourly_map(rows: list) -> dict[int, float]:
    """`{hour_start_epoch: mean}` for the rows that carry one."""
    out: dict[int, float] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        start = row.get("start")
        mean = row.get("mean")
        if not isinstance(start, (int, float)) or mean is None:
            continue
        if start > 1e11:  # Core reports milliseconds here and seconds elsewhere
            start = start / 1000.0
        try:
            out[int(start)] = float(mean)
        except (TypeError, ValueError):
            continue
    return out


def _pairs(room: dict[int, float], out: dict[int, float],
           tz: dt.tzinfo, night_only: bool) -> list[tuple[float, float]]:
    """`(T_in − T_out, dT/dt)` for consecutive hours we have both ends of.

    A gap in the recorder is skipped rather than interpolated: the rate
    between 01:00 and 05:00 is not four times the rate between 01:00 and
    02:00, and treating it as one would report a room that barely moves.
    """
    points = []
    for start, indoor in sorted(room.items()):
        nxt = room.get(start + 3600)
        outdoor = out.get(start)
        if nxt is None or outdoor is None:
            continue
        if night_only and not is_night(start, tz):
            continue
        points.append((indoor - outdoor, nxt - indoor))
    return points


def build_room(room_rows: list, outdoor_rows: list, tz: dt.tzinfo,
               unit: str) -> dict | None:
    """One room's model, or None when it cannot be measured honestly."""
    room = _hourly_map(room_rows)
    out = _hourly_map(outdoor_rows)
    if not room or not out:
        return None
    # A thermometer that spent the month outside the band people live in
    # is not a room, whatever it is called: the live state is one instant
    # and this is the month.
    middle = percentile(sorted(room.values()), 50.0)
    if middle is None or not in_room_band(middle, unit):
        return None
    loss = fit_loss(_pairs(room, out, tz, night_only=True))
    if loss is None:
        return None
    entry = dict(loss)
    entry["unit"] = unit
    # What the room was actually SEEN to do, beside what the model says it
    # could. The model's ceiling is an extrapolation and the warmest hour
    # is evidence, and the one check that reads the ceiling is required to
    # have both — see `climate.underheated`, whose whole false-positive
    # case is a room that never needed to go higher.
    entry["warmest"] = round(max(room.values()), 2)
    entry["coolest"] = round(min(room.values()), 2)
    entry["hours"] = len(room)
    # The gain is measured over the whole day, not the night: the heating
    # runs in the morning and the evening, and a night-only window is
    # exactly the hours it does not.
    gain = fit_gain(_pairs(room, out, tz, night_only=False), loss["k"])
    if gain:
        entry["gain"] = gain["gain"]
        entry["gain_points"] = gain["points"]
    return entry


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
            # batch that failed; the rest of the house still gets a model.
            log.info("thermal statistics batch failed: %s", exc)
            continue
        for sid, rows in (results[0] or {}).items():
            out[sid] = rows or []
    return out


async def build(session, states: dict, registries: dict | None = None,
                now: float | None = None, path: str | None = None) -> dict:
    """Measure every room and write the store. Returns the payload."""
    import baselines  # noqa: PLC0415

    now = time.time() if now is None else now
    tz, tz_name = baselines.house_timezone()
    areas = area_map(registries)
    payload = _empty()
    payload.update({"built_at": int(now), "tz": tz_name, "days": HISTORY_DAYS})

    outdoor, unit = pick_outdoor(states, areas)
    payload["outdoor"] = outdoor
    payload["unit"] = unit
    if not outdoor:
        # Not a failure and not an empty house: there is nothing to
        # measure a room against, and every number here is a difference.
        payload["reason"] = (
            "no outdoor temperature sensor — every number here is a "
            "difference from outside, so without one there is nothing to "
            "measure a room against")
        save(payload, path)
        return payload

    ids = room_candidates(states, outdoor, unit, areas)
    payload["asked"] = len(ids)
    if not ids:
        payload["reason"] = (
            "no indoor temperature sensor in an area reports in "
            f"{unit} — a room needs one to be named and one to be measured")
        save(payload, path)
        return payload

    rows = await fetch_hourly(session, [outdoor] + ids, now)
    outdoor_rows = rows.get(outdoor) or []
    outdoor_map = _hourly_map(outdoor_rows)
    if outdoor_map:
        payload["coldest"] = round(min(outdoor_map.values()), 2)
        payload["outdoor_hours"] = len(outdoor_map)
    for eid in ids:
        entry = build_room(rows.get(eid) or [], outdoor_rows, tz, unit)
        if not entry:
            continue
        name = ((states.get(eid) or {}).get("attributes") or {}).get(
            "friendly_name")
        if name:
            entry["name"] = str(name)[:60]
        if areas.get(eid):
            entry["area"] = areas[eid]
        payload["rooms"][eid] = entry
    if not payload["rooms"]:
        payload["reason"] = (
            "no room could be measured honestly yet — a month of nights "
            "with the outdoor temperature moving is what the fit needs")
    save(payload, path)
    log.info("thermal: %d of %d rooms measured over %d days against %s (%s)",
             len(payload["rooms"]), len(ids), HISTORY_DAYS, outdoor, tz_name)
    return payload


__all__ = [
    "GAIN_PCT", "HISTORY_DAYS", "MAX_ROOMS", "MAX_TAU_H", "MIN_DELTA_SPAN",
    "MIN_FIT_RATIO", "MIN_POINTS", "MIN_TAU_H", "NIGHT_FROM", "NIGHT_TO",
    "STORE", "area_map", "build", "build_room", "ceiling", "coast", "fit_gain",
    "fit_loss", "fetch_hourly", "hours_to_fall", "hours_to_warm",
    "in_room_band", "is_night", "is_stale", "load", "normalise_unit",
    "percentile", "pick_outdoor", "room_candidates", "save",
]
