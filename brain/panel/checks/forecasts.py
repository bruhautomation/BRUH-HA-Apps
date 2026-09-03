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

from . import baseline as baseline_check
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
        if abs(moved.get("move") or 0.0) < DECLINE_MIN_MOVE:
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
    hits = [h for h in hits if by_class.get(h[3], 0) <= SAME_CLASS_MAX]

    if not hits or len(hits) > DECLINE_MAX_ROWS:
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
                f"{'+' if rising else ''}{moved['move']:g}{unit} over the "
                f"last {round(moved['days'])} days "
                f"({'+' if rising else ''}{moved['per_day']:.3g}{unit} a "
                f"day), against a normal wobble of "
                f"{moved['noise']:.3g}{unit} — {moved['spreads']:g} times "
                "it. Every single reading has been inside its usual range "
                "the whole time, which is why nothing else has said so."
                + (f" {where}." if where else "")),
            "fix": ("Look at what it is measuring before it reaches a "
                    "number that matters. If this is a season, a new "
                    "appliance or a move brAIn cannot see, press Wrong and "
                    "say so."),
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
