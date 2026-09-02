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

from ._util import DAY, House, num

# A runway shorter than this is worth a row; longer is not yet news.
BATTERY_RUNWAY_DAYS = 21
# Fewer points than this and a line through them is a guess.
BATTERY_MIN_POINTS = 10
# A slope shallower than this (percent per day) is noise: a battery that
# will last two years does not need forecasting.
BATTERY_MIN_SLOPE = 0.15


def _fit(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Least-squares slope and intercept for (x, y), or None when flat."""
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
    intercept = (sy - slope * sx) / n
    return slope, intercept


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


CHECKS = [
    {"id": "forecast.battery", "title": "Batteries running down",
     "needs": ("states", "registry", "battery_stats"), "run": battery_runway},
]
