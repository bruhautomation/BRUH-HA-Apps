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
import re
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
# And what a temperature-classed reading can be that is NOT a temperature
# anybody is standing in. Every one of these is published by weather
# integrations with `device_class: temperature` and no area — which is
# exactly the branch `pick_outdoor` falls through to — so without this the
# reference is settled by whichever sorts first, and `dewpoint` sorts
# before `temperature`. That is how a real house came to have every `k` in
# it measured against `sensor.astroweather_2m_dewpoint`: a number that
# tracks humidity, sits well above the night air, and made a check report
# an irrigation manifold as a room with a window open.
#
# It is a name gate, which is a guess, made in the direction where being
# wrong is cheap (`measures_something_hot`'s trade): refusing a real
# outdoor sensor with an odd name costs the model, and the payload SAYS it
# found no reference, where accepting a derived one costs every room's
# physics silently. A frost point and a wet bulb are the same claim.
DERIVED_WORDS = ("dew point", "dewpoint", "dew_point", "feels like",
                 "feels_like", "apparent", "heat index", "heat_index",
                 "wind chill", "wind_chill", "windchill", "wet bulb",
                 "wet_bulb", "wetbulb", "frost point", "frost_point")
# --- which sensor is outside: ranked, never the alphabet's first --------
# A name that says "outside" in as many words, and the ones that only
# suggest it. "Ambient" is what most air conditioners and thermostats call
# their INDOOR sensor, and "garden" is a garden room as often as a garden,
# so they count for less than the words that cannot mean indoors.
STRONG_OUTDOOR_WORDS = ("outdoor", "outside", "exterior", "external")
# What an area called outdoors is called. An area is a person's own word
# for where a thing is, which is better evidence than an entity's name —
# and a thermometer in an area NOT called any of these is indoors and is
# never the reference, which is the one rule that cannot be outvoted.
OUTDOOR_AREA_WORDS = ("outdoor", "outside", "exterior", "garden", "yard",
                      "patio", "balcony", "terrace", "porch", "deck",
                      "driveway", "roof")
# Named like a reading of a machine or of water rather than of the air: a
# heat pump's outdoor coil, a pool, a pipe. The coil is the case that
# matters — "Heat pump outdoor coil" carries the strongest outdoor word
# there is and reads twenty degrees off the air whenever it runs.
NOT_AIR_WORDS = ("coil", "discharge", "compressor", "evaporator",
                 "condenser", "pool", "water", "pipe", "flow", "return",
                 "supply", "tank", "soil", "probe")
# The same claim as a `world_model` reading rather than a word, which is
# how it is made about a house that does not name things in English. A
# confident reading REPLACES the name's evidence in `rank_outdoor` — the
# words answer only where the reading has nothing to say — and never the
# area, the integration, the weather entity or the swing, which are not
# words and need no reading.
NOT_AIR_READINGS = ("heater", "cold_storage", "appliance_power")
# A sensor within this of a weather entity's own current temperature is
# reading the same air; one this far from it is not. Celsius; scaled for
# a Fahrenheit house.
TRACKS_WEATHER_C = 2.5
FAR_FROM_WEATHER_C = 8.0
# Outside air swings across a day; a room, a pool and a probe in a wall
# barely move. Median of the daily max-min over the month, Celsius.
MIN_OUTDOOR_SWING_C = 3.0
FLAT_SWING_C = 1.0
# How many of the ranked candidates the nightly pass fetches a month of,
# to read their swing. One statistics batch either way.
OUTDOOR_TRIALS = 3
# How many candidates ride in the store for the Knowledge tab's picker.
OUTDOOR_LISTED = 8

# A weather service's own temperature sensor is a MODEL's value for a grid
# square, not a thermometer at this house: an AstroWeather "2m temperature"
# is the forecast model's air at two metres, and it can be several degrees
# from the garden on a clear night. It is still a usable reference — often
# the only one — but every room's `k` is then measured against a model, and
# the payload says so rather than presenting the physics as measured.
MODEL_PLATFORMS = frozenset({
    "astroweather", "open_meteo", "met", "met_eireann", "pirateweather",
    "tomorrowio", "meteoblue", "visual_crossing", "weatherbit", "weatherkit",
    "accuweather", "openweathermap", "smhi", "dwd_weather",
})
_MODEL_NAME = re.compile(r"\b(forecast|forecasted|model|modelled|modeled|"
                         r"predicted|\d+\s?m)\b")

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
# What a room is doing NOW
# ---------------------------------------------------------------------------
#
# The model is a month old by construction and answers how a room *behaves*;
# whether one is cooling faster than it can right now is a live question, and
# the checks pass fetches it for itself — the same split `appliances` keeps,
# and cheap for the same reason: a handful of modelled rooms over a few
# hours, never the house over a month.

# Five-minute statistics, because an hourly mean cannot see a window that
# was opened forty minutes ago — it is still inside the hour that has not
# closed. Home Assistant keeps this resolution for ten days.
RECENT_HOURS = 4
# A rate measured over less than this is measuring the sensor's own quantum:
# a thermometer that reports in tenths moves 0.1 at a time, and two readings
# a few minutes apart put that step over a tiny window.
MIN_SPAN_MIN = 25.0
# And a fall has to be big enough to be a fall. Degrees, in the room's unit.
MIN_FALL = 0.4


async def fetch_recent(session, ids: list[str], start: dt.datetime,
                       end: dt.datetime | None = None) -> dict:
    """Five-minute means per entity, or {} when nothing answered."""
    import ha_data  # noqa: PLC0415

    out: dict[str, list] = {}
    base: dict = {
        "type": "recorder/statistics_during_period",
        "start_time": start.isoformat(),
        "statistic_ids": [],
        "period": "5minute",
        "types": ["mean"],
    }
    if end is not None:
        base["end_time"] = end.isoformat()
    for i in range(0, len(ids), 10):
        command = {**base, "statistic_ids": ids[i:i + 10]}
        try:
            results = await ha_data._ws_commands(session, [command])
        except Exception as exc:  # noqa: BLE001 — a batch that failed is a
            # batch that failed; the rest of the rooms still get a reading.
            log.info("thermal recent batch failed: %s", exc)
            continue
        for sid, rows in (results[0] or {}).items():
            out[sid] = rows or []
    return out


def recent_fall(rows: list, now: float) -> dict | None:
    """How fast a room has been falling, and over what.

    ``None`` unless the readings span `MIN_SPAN_MIN` and actually fall by
    `MIN_FALL` — a room that is steady, rising, or only just observed has
    no rate worth quoting, and quoting one anyway is how a check about a
    draught starts firing on a thermometer's own rounding.

    The rate is the **whole span**, first reading to last, rather than a
    fitted line: a window is a step change and a line through one reports
    half of it, which is exactly the half that decides whether this is
    reported at all.
    """
    points = sorted(_hourly_map(rows).items())
    if len(points) < 2:
        return None
    first_ts, first = points[0]
    last_ts, last = points[-1]
    span_min = (last_ts - first_ts) / 60.0
    if span_min < MIN_SPAN_MIN:
        return None
    fall = first - last
    if fall < MIN_FALL:
        return None
    return {
        "rate": fall / (span_min / 60.0),   # degrees per hour, positive down
        "from": round(first, 2),
        "to": round(last, 2),
        "span_min": round(span_min, 1),
        "age_min": round(max(0.0, (now - last_ts) / 60.0), 1),
        "n": len(points),
    }


def latest(rows: list) -> tuple[float, float] | None:
    """`(when, reading)` of the newest five-minute mean, or None."""
    points = sorted(_hourly_map(rows).items())
    if not points:
        return None
    ts, value = points[-1]
    return float(ts), value


def expected_fall(entry: dict, indoor: float, outdoor: float) -> float | None:
    """Degrees per hour this room loses at this difference, with no heating.

    The model's own prediction, and the thing an observed fall is measured
    against. A room warmer than outside falls; one that is not cannot, and
    a negative expectation would make any fall look enormous against it.
    """
    k = (entry or {}).get("k")
    if not k or indoor <= outdoor:
        return None
    return k * (indoor - outdoor)


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _empty() -> dict:
    return {"built_at": 0, "tz": "", "outdoor": "", "unit": "", "rooms": {},
            "coldest": None, "reason": "", "outdoor_source": "",
            "outdoor_why": "", "outdoor_candidates": [],
            "outdoor_modelled": False, "outdoor_unavailable": []}


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


def progress(payload: dict | None = None, path: str | None = None,
             now: float | None = None) -> dict:
    """How many rooms of this house have a measured thermal model.

    The two ways of having none are different answers and this is the
    module that can tell them apart: a house with no outdoor thermometer,
    or with no indoor one in an area, can never have a model however long
    it waits (`unavailable`, carrying the store's own sentence), while
    one whose month held no cold night simply has not had the weather for
    it yet (`collecting`).
    """
    import baselines  # noqa: PLC0415
    import house  # noqa: PLC0415 — panel-local, one shape and one eta

    now = time.time() if now is None else now
    payload = load(path) if payload is None else payload
    rooms = payload.get("rooms") or {}
    built = int(payload.get("built_at") or 0) or None
    detail = {"outdoor": payload.get("outdoor") or "",
              "rooms": len(rooms),
              "coldest": payload.get("coldest")}
    common = {"unit": "rooms", "need": 1, "have": len(rooms),
              "detail": detail, "updated_at": built,
              "per_unit_s": baselines.PROGRESS_UNIT_S, "now": now}

    if payload.get("error"):
        return house.progress(
            state=house.UNAVAILABLE, reason=str(payload["error"])[:200],
            summary=f"The last pass could not measure anything: {payload['error']}.",
            **common)
    if not built:
        return house.progress(
            state=house.NOT_STARTED, reason="no pass has run yet",
            summary=("Nothing measured yet — the first pass runs overnight "
                     f"and reads {HISTORY_DAYS} days of temperatures."),
            **common)
    if not rooms and not payload.get("outdoor"):
        return house.progress(
            state=house.UNAVAILABLE,
            reason=str(payload.get("reason") or "no outdoor temperature sensor"),
            summary=("No outdoor temperature sensor, so there is nothing to "
                     "measure a room against."),
            **common)
    if not rooms and not payload.get("asked"):
        return house.progress(
            state=house.UNAVAILABLE,
            reason=str(payload.get("reason") or "no room to measure"),
            summary=("No indoor thermometer is in an area and reporting in "
                     f"{payload.get('unit') or 'the same unit'}, so there is "
                     "no room to measure."),
            **common)
    if is_stale(payload, now):
        return house.progress(
            state=house.STALE,
            reason=f"last measured {house.days_ago(built, now)}",
            summary=(f"Measured {house.days_ago(built, now)} — the nightly "
                     "pass has not run since."),
            **common)
    if rooms:
        # The room with the shortest time constant is the one that loses
        # heat fastest, which is the one fact a sentence about a whole
        # house's thermal model can usefully carry.
        timed = [(v["tau_h"], k, v) for k, v in rooms.items()
                 if isinstance(v, dict) and v.get("tau_h")]
        asked = int(payload.get("asked") or 0)
        counted = (f"{len(rooms)} of {house.plural(asked, 'room')}"
                   if asked > len(rooms)
                   else house.plural(len(rooms), 'room'))
        said = (f"{counted} measured against "
                f"{payload.get('outdoor') or 'outdoors'}")
        if payload.get("outdoor_modelled"):
            said += (" (a forecast model's value for this location, not a "
                     "thermometer here)")
        missing = [str(u) for u in payload.get("outdoor_unavailable") or []]
        if missing:
            said += (f" — {', '.join(missing)} is unavailable, so it could "
                     "not be used")
        if timed:
            tau, eid, entry = min(timed)
            said += (f" · {entry.get('area') or entry.get('name') or eid} "
                     f"holds its heat about {round(tau)} h")
        detail["asked"] = asked
        detail["outdoor_modelled"] = bool(payload.get("outdoor_modelled"))
        detail["outdoor_unavailable"] = missing
        return house.progress(state=house.READY, summary=said + ".", **common)
    return house.progress(
        state=house.COLLECTING,
        reason=str(payload.get("reason") or "no room could be measured yet"),
        summary=(f"{house.plural(int(payload.get('asked') or 0), 'room')} "
                 "watched, none measurable yet — the fit needs a month of "
                 "nights with the outdoor temperature moving."),
        **common)


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


def _name_of(eid: str, st: dict) -> str:
    return (str(((st.get("attributes") or {}).get("friendly_name")) or "")
            + " " + eid).lower()


def _read_measures(world, eid: str) -> str | None:
    """What a confident `world_model` reading says this sensor measures,
    or None — below the floor, `unknown` and no reading all read alike."""
    import world_model  # noqa: PLC0415 — a leaf

    value = world_model.attribute(world, eid, "measures", None)
    return value if isinstance(value, str) else None


def _looks_outdoor(eid: str, st: dict, world=None) -> bool:
    """Named outdoors, or read as outdoors by `world_model`.

    The reading answers first when it is confident — `buiten` is outside
    in Dutch and no list here will ever say so — and the words answer
    whenever it has nothing to say."""
    import world_model  # noqa: PLC0415 — a leaf

    def by_name() -> bool:
        name = _name_of(eid, st)
        return any(word in name for word in OUTDOOR_WORDS)

    return world_model.is_outdoor(world, eid, by_name)


def is_derived(eid: str, st: dict, world=None) -> bool:
    """A temperature-classed reading that is not the air temperature.

    Checked BEFORE the outdoor words rather than after them, because
    "Outdoor Dew Point" satisfies both and only one of them decides
    whether the number means what the model needs it to mean. A
    confident `world_model` reading of `derived_index` answers it in any
    language (`dauwpunt`); the words are the fallback.
    """
    import world_model  # noqa: PLC0415

    def by_name() -> bool:
        name = _name_of(eid, st)
        return any(word in name for word in DERIVED_WORDS)

    return world_model.is_derived(world, eid, by_name)


def _world_for(states: dict, registries: dict | None) -> dict:
    """The current entity readings for these states and registries."""
    try:
        import world_model  # noqa: PLC0415
        reg = registries or {}
        snap = {"states": states, "entities": reg.get("entities") or [],
                "devices": reg.get("devices") or [],
                "areas": reg.get("areas") or []}
        return world_model.view(world_model.load(),
                                world_model.candidates(snap))
    except Exception:  # noqa: BLE001 — a reading is optional; the build is not
        return {}


def _area_is_outdoors(area: str) -> bool:
    text = str(area or "").lower()
    return any(word in text for word in OUTDOOR_AREA_WORDS)


def _celsius_delta(delta: float, unit: str) -> float:
    """A difference in `unit` degrees, in Celsius degrees."""
    return delta / 1.8 if unit == "°F" else delta


def _weather_readings(states: dict) -> list[tuple[str, float, str]]:
    """`(entity_id, temperature, unit)` for every weather entity that has one."""
    out = []
    for eid, st in sorted((states or {}).items()):
        if not eid.startswith("weather.") or not isinstance(st, dict):
            continue
        attrs = st.get("attributes") or {}
        try:
            value = float(attrs.get("temperature"))
        except (TypeError, ValueError):
            continue
        unit = normalise_unit(attrs.get("temperature_unit")) or "°C"
        out.append((eid, value, unit))
    return out


def _to_unit(value: float, have: str, want: str) -> float:
    if have == want:
        return value
    if have == "°F" and want == "°C":
        return (value - 32.0) / 1.8
    if have == "°C" and want == "°F":
        return value * 1.8 + 32.0
    return value


def rank_outdoor(states: dict, areas: dict | None = None,
                 entities: list | None = None, world=None) -> list[dict]:
    """Every thermometer that could be the outdoor reference, best first.

    It used to be the alphabetically first sensor whose name held an
    outdoor word anywhere — so a heat pump's outdoor coil, an outdoor
    pool's water and an indoor "Ambient" sensor could each become the one
    reading every room's `k` is fitted against, with nothing to check it
    and nothing to override it. Now each candidate collects the evidence
    for and against it, in sentences, and the most plausible wins:

      * an area somebody called outdoors (+2), or no area at all (+1),
        which is how a weather service's own sensor arrives — and an area
        NOT called outdoors rules it out, whatever its name says;
      * a name that says outside (+2) or only suggests it (+1), and one
        that names a coil, a pool or a pipe (−3);
      * the integration that also provides a `weather` entity (+3);
      * reading within `TRACKS_WEATHER_C` of a weather entity's own
        temperature right now (+3), or further than `FAR_FROM_WEATHER_C`
        from it (−3) — the one signal that needs no word at all, which is
        what makes it work in a house named in any language.

    Eligible means not ruled out and a score above zero. A derived reading
    (`is_derived`) is not a candidate at all. Ties go to the entity id, so
    the order is the same every night. The month's daily swing is the
    last piece of evidence and needs the history, so `build` adds it.
    """
    areas = areas or {}
    platform = {str(r.get("entity_id")): str(r.get("platform") or "")
                for r in (entities or [])
                if isinstance(r, dict) and r.get("entity_id")}
    weather = _weather_readings(states)
    weather_platforms = {platform.get(w[0], ""): w[0] for w in weather
                         if platform.get(w[0])}
    out = []
    for eid, st, unit in _temperature_sensors(states):
        if is_derived(eid, st, world):
            continue
        name = str(((st.get("attributes") or {}).get("friendly_name"))
                   or eid)
        text = _name_of(eid, st)
        reasons: list[str] = []
        score = 0
        ruled_out = ""
        area = areas.get(eid)
        if area:
            if _area_is_outdoors(area):
                score += 2
                reasons.append(f"is in the {area} area, which is outdoors")
            else:
                ruled_out = f"is in the {area} area, which is indoors"
        else:
            score += 1
            reasons.append("is in no area, which is how a weather "
                           "service's own sensor arrives")
        named = 0
        read = _read_measures(world, eid)
        if read == "outdoor":
            # A confident reading counts like a name that says outside —
            # and is what makes `buiten` count at all.
            named = 2
            reasons.append("was read by brAIn as measuring the outdoor air")
        elif read in NOT_AIR_READINGS:
            score -= 3
            reasons.append("was read by brAIn as a reading of a machine or "
                           "of water rather than of the air")
        elif read == "room_air":
            score -= 2
            reasons.append("was read by brAIn as a room's air rather than "
                           "the outdoor air")
        else:
            # No confident reading: the words answer, exactly as before.
            if any(word in text for word in STRONG_OUTDOOR_WORDS):
                named = 2
                reasons.append("is named as outdoors")
            elif any(word in text for word in OUTDOOR_WORDS):
                named = 1
                reasons.append("has a name that suggests outdoors")
            if any(word in text for word in NOT_AIR_WORDS):
                score -= 3
                reasons.append("is named like a reading of a machine or of "
                               "water rather than of the air")
        score += named
        source = platform.get(eid, "")
        if source and source in weather_platforms:
            score += 3
            reasons.append(f"comes from {source}, the integration behind "
                           f"{weather_platforms[source]}")
        try:
            value = float(st.get("state"))
        except (TypeError, ValueError):
            value = None
        if value is not None and weather:
            gaps = [(abs(value - _to_unit(w_value, w_unit, unit)), w_eid)
                    for w_eid, w_value, w_unit in weather]
            gap, w_eid = min(gaps)
            gap_c = _celsius_delta(gap, unit)
            if gap_c <= TRACKS_WEATHER_C:
                score += 3
                reasons.append(f"reads within {gap:.1f}{unit} of {w_eid}")
            elif gap_c >= FAR_FROM_WEATHER_C:
                score -= 3
                reasons.append(f"reads {gap:.1f}{unit} away from {w_eid}")
        if ruled_out and not named:
            # An indoor thermometer that never claimed to be outdoors is
            # not a candidate anybody needs to see refused.
            continue
        modelled = bool(source in MODEL_PLATFORMS or _MODEL_NAME.search(text))
        if modelled:
            reasons.append("is a weather service's modelled value for this "
                           "location, not a thermometer here")
        missing = str(st.get("state") or "") in ("unavailable", "unknown", "")
        if missing:
            reasons.append("is unavailable right now")
        out.append({"entity_id": eid, "name": name[:60], "unit": unit,
                    "score": score, "reasons": reasons,
                    "ruled_out": ruled_out, "named": named,
                    "modelled": modelled, "unavailable": missing,
                    "eligible": not ruled_out and score > 0})
    out.sort(key=lambda c: (not c["eligible"], -c["score"], c["entity_id"]))
    return out


def _why(candidate: dict) -> str:
    reasons = candidate.get("reasons") or []
    if not reasons:
        return f"{candidate['name']} ({candidate['entity_id']}) was the only candidate."
    if len(reasons) > 1:
        said = ", ".join(reasons[:-1]) + " and " + reasons[-1]
    else:
        said = reasons[0]
    return f"{candidate['name']} ({candidate['entity_id']}) {said}."


def _caveats(choice: dict) -> dict:
    """`modelled` and `unavailable` for a choice, and its `why` saying so.

    A reference that is a forecast model's value is said as one; and when
    it is, any candidate that measures the air here and would have been
    the better reference — not ruled out, not itself a model — but is
    unavailable right now is named, because "the station was down, so the
    model was used" is the sentence that explains every number after it.
    """
    eid = choice.get("entity_id") or ""
    cands = choice.get("candidates") or []
    picked = next((c for c in cands if c.get("entity_id") == eid), None)
    modelled = bool(picked and picked.get("modelled"))
    unavailable = []
    if modelled:
        unavailable = [c["entity_id"] for c in cands
                       if c.get("entity_id") != eid and c.get("unavailable")
                       and not c.get("modelled") and not c.get("ruled_out")
                       and (c.get("named") or 0) > 0]
    why = choice.get("why") or ""
    if modelled and "forecast model" not in why:
        why += (" It is a forecast model's value rather than a thermometer "
                "here, so every room is measured against a model.")
    if unavailable:
        names = ", ".join(next((c["name"] for c in cands
                                if c["entity_id"] == u), u)
                          + f" ({u})" for u in unavailable)
        why += (f" {names}, which measures the air here, is unavailable, "
                "so it could not be used.")
    return {**choice, "why": why.strip(), "modelled": modelled,
            "unavailable": unavailable}


def choose_outdoor(states: dict, areas: dict | None = None,
                   entities: list | None = None,
                   override: str | None = None, world=None) -> dict:
    """The outdoor reference, why, and what else could have been.

    `{"entity_id", "unit", "source", "why", "candidates"}`. `source` is
    `chosen` when somebody named it in brAIn's settings (`thermal_outdoor`,
    set from the Knowledge tab) and `ranked` when `rank_outdoor` picked it;
    a choice that names no temperature sensor here is said and ignored,
    because a reference that is not a thermometer would measure every room
    against nothing. "" with no entity is a house with no plausible
    reference, and `why` says so.
    """
    ranked = rank_outdoor(states, areas, entities, world)
    listed = ranked[:OUTDOOR_LISTED]
    note = ""
    if override:
        for eid, st, unit in _temperature_sensors(states):
            if eid == override:
                name = str(((st.get("attributes") or {}).get("friendly_name"))
                           or eid)
                return _caveats(
                    {"entity_id": eid, "unit": unit, "source": "chosen",
                     "why": (f"{name} ({eid}) was chosen as the outdoor "
                             "reference in brAIn's settings."),
                     "candidates": listed})
        note = (f"The reference chosen in brAIn's settings, {override}, is "
                "not a temperature sensor with statistics here, so brAIn "
                "picked one itself. ")
    eligible = [c for c in ranked if c["eligible"]]
    if not eligible:
        return {"entity_id": "", "unit": "", "source": "",
                "why": note + ("No temperature sensor here looks like the "
                               "outdoor air."),
                "candidates": listed, "modelled": False, "unavailable": []}
    best = eligible[0]
    return _caveats({"entity_id": best["entity_id"], "unit": best["unit"],
                     "source": "ranked", "why": note + _why(best),
                     "candidates": listed})


def pick_outdoor(states: dict, areas: dict | None = None,
                 entities: list | None = None,
                 world=None) -> tuple[str, str]:
    """The outdoor reference, and its unit. `("", "")` when there is none.

    `choose_outdoor`'s answer without the reasons. It is **recorded in the
    payload** rather than only used, because a reference nobody can check
    is a reference nobody can correct — and every ``k`` in the house is
    measured against this one choice.

    A derived temperature is refused outright (`is_derived`): a weather
    integration publishes several temperature-classed readings that are
    not the air temperature, and a dew point that sorts before the real
    reading is how one house had every room measured against humidity.
    """
    chosen = choose_outdoor(states, areas, entities, world=world)
    return chosen["entity_id"], chosen["unit"]


def daily_swing(rows: list, tz: dt.tzinfo) -> float | None:
    """The median day's max-min, from hourly rows. None without three days.

    A day counts only with most of its hours, or a day the recorder
    caught three hours of reports a swing of three hours.
    """
    by_day: dict[str, list[float]] = {}
    for start, mean in _hourly_map(rows).items():
        key = dt.datetime.fromtimestamp(start, tz).date().isoformat()
        by_day.setdefault(key, []).append(mean)
    ranges = sorted(max(v) - min(v) for v in by_day.values() if len(v) >= 18)
    if len(ranges) < 3:
        return None
    return percentile(ranges, 50.0)


def _settled_outdoor(choice: dict, rows: dict, tz: dt.tzinfo) -> dict:
    """`choose_outdoor`'s pick, with the month's swing read in.

    Only between the leading candidates of the reference's own unit (a
    Fahrenheit sensor cannot replace a Celsius one under rooms already
    chosen in Celsius), and never over somebody's own choice.
    """
    if choice.get("source") != "ranked":
        return choice
    unit = choice["unit"]
    swing_c = MIN_OUTDOOR_SWING_C * (1.8 if unit == "°F" else 1.0)
    flat_c = FLAT_SWING_C * (1.8 if unit == "°F" else 1.0)
    trial = [dict(c, reasons=list(c["reasons"]))
             for c in choice["candidates"]
             if c["eligible"] and c["unit"] == unit][:OUTDOOR_TRIALS]
    if not trial:
        return choice
    for c in trial:
        swing = daily_swing(rows.get(c["entity_id"]) or [], tz)
        if swing is None:
            continue
        if swing >= swing_c:
            c["score"] += 2
            c["reasons"].append(f"swings about {swing:.1f}{unit} a day, "
                                "as outside air does")
        elif swing < flat_c:
            c["score"] -= 2
            c["reasons"].append(f"barely moves across a day ({swing:.1f}"
                                f"{unit}), which outside air does not")
    best = sorted(trial, key=lambda c: (-c["score"], c["entity_id"]))[0]
    rest = [c for c in choice["candidates"]
            if c["entity_id"] not in {t["entity_id"] for t in trial}]
    return _caveats({**choice, "entity_id": best["entity_id"],
                     "why": _why(best),
                     "candidates": sorted(trial, key=lambda c: (-c["score"],
                                                                c["entity_id"]))
                     + rest})


def room_candidates(states: dict, outdoor: str, unit: str,
                    areas: dict | None = None, world=None) -> list[str]:
    """Indoor thermometers worth a model, in a stable order.

    The unit has to match the reference's — ``k`` is only unit-free while
    both halves of the delta are in the same degrees — and the reading has
    to be one a person could be living in, which is what keeps the freezer
    and the hot water tank out.
    """
    areas = areas or {}
    out = []
    for eid, st, own in _temperature_sensors(states):
        if eid == outdoor or own != unit or _looks_outdoor(eid, st, world):
            continue
        # A dew point sitting in a room's area reads inside the band and
        # carries the class, so the band alone lets one through as a room.
        if is_derived(eid, st, world):
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
        if _area_is_outdoors(areas[eid]):
            # A thermometer in the garden is not a room, whatever it is
            # called — and it is one of `rank_outdoor`'s candidates.
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
                       days: int = HISTORY_DAYS) -> dict | None:
    """Hourly means per entity for the window.

    `{}` is the recorder holding nothing for these ids; None is the
    recorder refusing every batch, which `build` answers by leaving the
    store alone rather than writing a house with no rooms over it.
    """
    import ha_data  # noqa: PLC0415 — see the checks snapshot's own note

    if not ids:
        return {}
    start = dt.datetime.fromtimestamp(now - days * 86400, tz=dt.timezone.utc)
    out: dict[str, list] = {}
    answered = 0
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
        rows_by_id = results[0] if results else None
        if not isinstance(rows_by_id, dict):
            log.info("thermal statistics batch refused by the recorder")
            continue
        answered += 1
        for sid, rows in rows_by_id.items():
            out[sid] = rows or []
    return out if answered else None


async def build(session, states: dict, registries: dict | None = None,
                now: float | None = None, path: str | None = None,
                world: dict | None = None) -> dict:
    """Measure every room and write the store. Returns the payload.

    A fetch the recorder refused writes nothing and hands back the
    previous store with `error` beside it (`baselines.refused`). A house
    with nothing to measure still writes, with `reason` saying why.

    `world` is the entity readings (`world_model`); left out, the store
    is read here and matched against the registries this pass fetched,
    so a renamed sensor's old reading is never what picks the outdoor
    reference. A store that cannot be read is `{}` and the word lists
    answer, which is this module before the readings existed.
    """
    import baselines  # noqa: PLC0415

    if world is None:
        world = _world_for(states, registries)
    now = time.time() if now is None else now
    tz, tz_name = baselines.house_timezone()
    areas = area_map(registries)
    payload = _empty()
    payload.update({"built_at": int(now), "tz": tz_name, "days": HISTORY_DAYS})

    override = None
    try:
        import settings_store  # noqa: PLC0415 — panel-local; never fatal
        override = settings_store.load().get("thermal_outdoor")
    except Exception as exc:  # noqa: BLE001 — a choice nobody could read
        # is a choice not made, which is the ranked pick.
        log.debug("thermal: could not read the outdoor choice: %s", exc)
    choice = choose_outdoor(states, areas,
                            (registries or {}).get("entities"), override,
                            world=world)
    outdoor, unit = choice["entity_id"], choice["unit"]
    payload["outdoor"] = outdoor
    payload["unit"] = unit
    payload["outdoor_source"] = choice["source"]
    payload["outdoor_why"] = choice["why"]
    payload["outdoor_candidates"] = choice["candidates"]
    payload["outdoor_modelled"] = bool(choice.get("modelled"))
    payload["outdoor_unavailable"] = list(choice.get("unavailable") or [])
    if not outdoor:
        # Not a failure and not an empty house: there is nothing to
        # measure a room against, and every number here is a difference.
        payload["reason"] = (
            "no outdoor temperature sensor — every number here is a "
            "difference from outside, so without one there is nothing to "
            "measure a room against")
        save(payload, path)
        return payload

    ids = room_candidates(states, outdoor, unit, areas, world)
    payload["asked"] = len(ids)
    if not ids:
        payload["reason"] = (
            "no indoor temperature sensor in an area reports in "
            f"{unit} — a room needs one to be named and one to be measured")
        save(payload, path)
        return payload

    trial = ([c["entity_id"] for c in choice["candidates"]
              if c["eligible"] and c["unit"] == unit][:OUTDOOR_TRIALS]
             if choice["source"] == "ranked" else [])
    fetch_ids = list(dict.fromkeys([outdoor] + trial + ids))
    rows = await fetch_hourly(session, fetch_ids, now)
    if rows is None:
        return baselines.refused(
            "thermal", load(path),
            f"the recorder did not answer for any of the {len(fetch_ids)} "
            "thermometers asked about")
    # The last piece of evidence: how much each leading candidate moved
    # across a day this month. Read before any room is fitted, so every
    # `k` below is measured against the reference that won.
    choice = _settled_outdoor(choice, rows, tz)
    outdoor = choice["entity_id"]
    payload["outdoor"] = outdoor
    payload["outdoor_why"] = choice["why"]
    payload["outdoor_candidates"] = choice["candidates"][:OUTDOOR_LISTED]
    payload["outdoor_modelled"] = bool(choice.get("modelled"))
    payload["outdoor_unavailable"] = list(choice.get("unavailable") or [])
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
    "MIN_FALL", "MIN_SPAN_MIN", "RECENT_HOURS", "STORE", "area_map", "build",
    "build_room", "ceiling", "coast", "expected_fall", "fetch_recent", "fit_gain",
    "fit_loss", "fetch_hourly", "hours_to_fall", "hours_to_warm", "latest",
    "in_room_band", "is_night", "is_stale", "load", "normalise_unit",
    "OUTDOOR_TRIALS", "choose_outdoor", "daily_swing", "rank_outdoor",
    "percentile", "pick_outdoor", "progress", "recent_fall",
    "room_candidates", "save",
]
