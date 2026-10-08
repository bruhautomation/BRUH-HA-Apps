"""Forecasts — findings with a date on them.

A finding says what has already failed. Almost every failure in a house is
preceded by a trend, and the trends are already in long-term statistics.
The first forecast is the one every smart-home owner has wished for: how
long the battery has left, from the slope of its discharge, rather than a
threshold that fires the day before it dies.

The text of a forecast is stable ("… is running down"); the number of days
lives in ``detail`` so the finding refreshes rather than re-files.
"""
from __future__ import annotations

import re

import numfmt

from . import baseline as baseline_check
from . import devices
from ._util import DAY, House, num

# A runway shorter than this is worth a row; longer is not yet news.
BATTERY_RUNWAY_DAYS = 21
# Fewer points than this and a line through them is a guess.
BATTERY_MIN_POINTS = 10
# A slope shallower than this (percent per day) is noise: a battery that
# will last two years does not need forecasting.
BATTERY_MIN_SLOPE = 0.15

# --- forecast.decline ---------------------------------------------------
# How far the reading has to have travelled across the window, in units of
# the noise it is travelling through. `baselines.trend` measures that
# noise about the fitted line, which is the one estimate the drift itself
# cannot inflate.
DECLINE_SPREADS = 4.0
# And by something a person would recognise, not merely by arithmetic:
# four spreads of a band 0.01 wide is nothing anybody can act on.
DECLINE_MIN_MOVE = 0.5
# Past this, what has drifted is the measurement rather than the house —
# the same reasoning `base.unusual` caps itself with, and a smaller
# number because a season moves everything at once.
DECLINE_MAX_ROWS = 3
# Two thermometers drifting together is a house; five is the weather.
SAME_CLASS_MAX = 2
# A drift is a finding only where its cause could be inside the house. The
# producer scorecard read 0 confirmed against 3 marked Wrong, and the rows
# were the grid's carbon intensity falling over a month, a car's charge
# level following how far somebody drove, and soil drying out in a dry
# spell — each a real drift, measured correctly, about something the house
# does not control and no device in it is doing wrong. What they have in
# common is checkable: what they measure is outside (the weather's own
# classes, the soil), a tariff or an intensity per unit of energy (the
# grid, not the meter), something a person carries (a phone, or a device
# that also reports where it is), or a weather or grid integration's
# figure. A freezer, a room, a boiler's pressure stay — those are what the
# check is for. Each is a guess in the cheap direction: a missed drift on
# one of these costs one card, and a false one is the list.
OUTSIDE_CLASSES = frozenset({
    "moisture", "precipitation", "precipitation_intensity", "wind_speed",
    "wind_direction", "irradiance", "illuminance", "atmospheric_pressure",
    "aqi", "pm1", "pm10", "pm25", "ozone", "nitrogen_dioxide",
    "sulphur_dioxide", "monetary", "distance", "speed",
})
OUTSIDE_PLATFORMS = frozenset({
    "mobile_app", "met", "met_eireann", "openweathermap", "accuweather",
    "pirateweather", "tomorrowio", "nws", "buienradar", "smhi", "ipma",
    "aemet", "environment_canada", "meteo_france", "bom", "open_meteo",
    "weatherkit", "weatherflow", "weatherflow_cloud", "co2signal",
    "electricity_maps", "nordpool", "entsoe",
})
# A tariff or an intensity: anything per kWh/MWh/Wh, which is the grid's
# number rather than the house's.
_PER_ENERGY = re.compile(r"/\s*[kmg]?wh$", re.I)
# Words that cannot mean a thing indoors. Not "grid" (a grid power meter
# is the house's own draw), not "carbon" (a carbon monoxide detector), not
# "external" (a freezer's external probe).
OUTSIDE_WORDS = frozenset({"outdoor", "outside", "exterior", "soil",
                           "weather", "forecast"})


def outside_cause(house: House, eid: str, st: dict, unit: str) -> str:
    """Why a drift on this reading is not the house's, or "" when it may be."""
    attrs = st.get("attributes") or {}
    reg = house.registry.get(eid) or {}
    if str(attrs.get("device_class") or "") in OUTSIDE_CLASSES:
        return "what it measures is outside"
    if _PER_ENERGY.search(str(unit or "").strip()):
        return "a tariff or intensity per unit of energy"
    if str(reg.get("platform") or "") in OUTSIDE_PLATFORMS:
        return "a weather, grid or phone integration"
    device = reg.get("device_id")
    if device and any(e.get("device_id") == device
                      and str(e.get("entity_id") or "").startswith("device_tracker.")
                      for e in house.entities):
        return "a device somebody carries"
    for name in (attrs.get("friendly_name"), reg.get("name"),
                 reg.get("original_name"), eid.split(".", 1)[-1]):
        if set(re.split(r"[^a-z0-9]+", str(name or "").lower())) & OUTSIDE_WORDS:
            return "named as outdoors"
    import thermal  # noqa: PLC0415 — panel-local, like checks/thermal.py
    if thermal._area_is_outdoors(house.area_of(eid)):  # noqa: SLF001
        return "in an area called outdoors"
    return ""


def _fit(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least-squares slope and intercept for (x, y), or None when flat.

    The arithmetic lives in `baselines`, which fits the same line through
    a month of hourly means. One question, one answer: a second copy here
    would be the one that drifts, because a battery's discharge is the
    obvious case and nothing would ever notice the two disagreeing.
    """
    import baselines  # noqa: PLC0415 — the package stays importable
                      # without the panel on the path; see checks/baseline.py

    return baselines.least_squares(points)


def battery_runway(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    series = snap.get("battery_stats") or {}
    out = []
    for eid, rows in series.items():
        st = house.states.get(eid)
        if not st or not house.enabled(eid):
            continue
        if st.get("state") in ("unavailable", "unknown"):
            continue
        # A battery somebody charges is not one to have a replacement
        # ready for — `dev.battery_low`'s rule, through the same helper.
        if devices.rechargeable(house, eid):
            continue
        points = []
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            start = num(r.get("start"))
            mean = num(r.get("mean"))
            if start is None or mean is None:
                continue
            points.append(((start - now) / DAY, mean))
        if len(points) < BATTERY_MIN_POINTS:
            continue
        fit = _fit(points)
        if fit is None:
            continue
        slope, intercept = fit  # percent per day, level "today"
        if slope > -BATTERY_MIN_SLOPE:
            continue
        current = num(st.get("state"))
        level = current if current is not None else intercept
        if level <= 0:
            continue
        days_left = level / -slope
        if days_left > BATTERY_RUNWAY_DAYS:
            continue
        if not house.should_report(eid, "forecast.battery"):
            continue
        dev = house.device_of(eid)
        who = house.device_name(dev) if dev else house.name(eid)
        span = -points[0][0]
        out.append({
            "text": f"{who} battery is running down",
            "detail": f"About {max(1, round(days_left))} day"
                      f"{'' if round(days_left) == 1 else 's'} left at the "
                      f"current rate: {level:g}% now, losing "
                      f"{-slope:.1f}% a day over the last {round(span)} "
                      f"days{house.where(eid)}.",
            "fix": "Have a replacement ready; it will need changing before "
                   "the automations that depend on it notice.",
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


def decline(snap: dict, now: float) -> list[dict]:
    """A reading that has been walking in one direction for weeks.

    The failure with no bad reading in it. A freezer 6°C warmer than it
    was a month ago has never once been outside the band `base.unusual`
    draws, because the band is built from the same weeks the drift
    happened in and moved along with it — measured on a real-shaped
    series, that freezer reads 2.3 spreads to `base.unusual` and 16 to
    the trend. Nobody notices until something spoils.

    `baselines.trend` does the measuring; what is here is the judgement
    about when it is worth telling somebody.
    """
    store = snap.get("baselines") or {}
    entities = store.get("entities") or {}
    if not entities:
        return []

    house = House(snap)
    hits = []
    for eid, baseline in entities.items():
        moved = baseline.get("trend")
        if not moved or not moved.get("consistent"):
            continue
        if abs(moved.get("spreads") or 0.0) < DECLINE_SPREADS:
            continue
        st = house.states.get(eid)
        # The same question `base.unusual` asks, asked once: both checks
        # report a sensor reading, so a sensor one of them will not speak
        # about is one neither should, and two copies of that list is how
        # they end up disagreeing about which box a battery is in.
        if not st or not baseline_check.eligible(house, eid, st):
            continue
        unit = baseline.get("unit") or (st.get("attributes") or {}).get(
            "unit_of_measurement")
        if abs(moved.get("move") or 0.0) < baseline_check.min_move(
                unit, DECLINE_MIN_MOVE):
            continue
        if outside_cause(house, eid, st, unit):
            continue
        attrs = st.get("attributes") or {}
        hits.append((abs(moved["spreads"]), eid, moved,
                     str(attrs.get("device_class") or ""), baseline))

    # A house that turned its heating on has every thermometer drifting,
    # and that is the weather rather than a device. More than a couple of
    # one kind moving together is the environment moving; the whole class
    # stands down rather than filling the list with the season.
    by_class: dict[str, int] = {}
    for _rank, _eid, _moved, klass, _b in hits:
        by_class[klass] = by_class.get(klass, 0) + 1
    together = [h for h in hits if by_class.get(h[3], 0) > SAME_CLASS_MAX]
    if together:
        house.gave_up("forecast.decline",
                      [{"entity_id": h[1]} for h in together],
                      "several sensors of the same kind were drifting the "
                      "same way at once — that is the weather or the season "
                      "moving, not one device")
    hits = [h for h in hits if by_class.get(h[3], 0) <= SAME_CLASS_MAX
            and house.should_report(h[1], "forecast.decline")]

    if len(hits) > DECLINE_MAX_ROWS:
        house.gave_up("forecast.decline", [{"entity_id": h[1]} for h in hits],
                      f"{len(hits)} readings were drifting at once — past "
                      f"{DECLINE_MAX_ROWS} that is the measurement rather "
                      "than the house")
        return []
    if not hits:
        return []
    hits.sort(reverse=True)

    out = []
    for _rank, eid, moved, _klass, baseline in hits:
        unit = baseline.get("unit") or ""
        rising = (moved.get("per_day") or 0.0) > 0
        where = house.where(eid)
        out.append({
            # Stable text: every number in here moves every night.
            "text": (f"{house.name(eid)} has been drifting "
                     f"{'up' if rising else 'down'} for weeks"),
            "detail": (
                f"{numfmt.quantity(moved['move'], unit, signed=True)} over "
                f"the last {round(moved['days'])} days "
                f"({numfmt.quantity(moved['per_day'], unit, signed=True)} a "
                f"day), against a normal wobble of "
                f"{numfmt.quantity(moved['noise'], unit)} — "
                f"{numfmt.times(abs(moved['spreads']))} "
                "it. Every single reading has been inside its usual range "
                "the whole time, which is why nothing else has said so."
                + (f" {where}." if where else "")),
            "fix": ("Look at what it is measuring before it reaches a "
                    "number that matters. If this is a season, a new "
                    "appliance or a move brAIn cannot see, press Ignore and "
                    "say why."),
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


CHECKS = [
    {"id": "forecast.battery", "title": "Batteries running down",
     "needs": ("states", "registry", "battery_stats"), "run": battery_runway},
    {"id": "forecast.decline", "title": "Readings drifting for weeks",
     "needs": ("states", "registry", "baselines"), "run": decline},
]
