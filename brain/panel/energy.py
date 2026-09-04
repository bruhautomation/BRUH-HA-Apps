"""What the house used, and whether that is more than the week before.

"Energy and cost" is the first line of the weekly report the roadmap
asks for, and the arithmetic is the easy half. The hard half is *which
meters*, and getting it wrong produces a number nobody can tell is
wrong.

**The set of meters is Home Assistant's own, never ours.** Summing
"every sensor with `device_class: energy`" double-counts by
construction: a whole-home clamp, the solar inverter, and every smart
plug behind them all carry that class, so a house with six plugs reports
using roughly twice what it used. Nothing on screen would say so.
`energy/get_prefs` is the set the person themselves told the Energy
dashboard are their grid sources, and it is the only set anybody has
declared. Where there is no energy configuration this says **nothing at
all** rather than picking a plausible group — a fabricated total is
worse than a missing section, and a missing section is a sentence
("no energy configuration") that tells somebody exactly what to do.

**Cost is reported only where a cost STATISTIC exists.** A `flow_from`
entry may instead carry a price to multiply, in which case Home
Assistant creates its own cost sensor under a derived entity id — and
guessing that id is how a report ends up quoting a number that belongs
to a different sensor. `stat_cost` or no cost.

**Both windows are seven complete days.** A partial week compared
against a full one reports a forty per cent drop that is nothing but the
calendar, on the one number in the report people will act on. The
comparison runs to local midnight and never to `now`.

**A negative day is a meter reset, not a negative amount of
electricity.** A firmware reset, a replaced meter or a purged statistic
makes a day's consumption come out below zero. The day is dropped and
the window reports itself short, because a reset week whose total looks
plausible is the failure this rule exists for.

**The recorder can answer this itself, and where it can it is asked.**
`types: ["change"]` is consumption per period, computed by the component
that owns the statistics; the cumulative `sum` is the fallback for a
core that predates it, and deriving from it costs an extra day at the
front of the fetch — the first row of any range has no predecessor and
yields nothing, so without that day the earlier window would be six days
against the later one's seven and the whole comparison would be a
one-seventh fall that is nothing but the fetch.
"""
from __future__ import annotations

import datetime as dt
import logging

log = logging.getLogger("brain.energy")

# One week against the one before it. Seven days is what people plan by,
# and it also cancels the weekday/weekend shape that would otherwise
# dominate any shorter comparison.
WEEK_DAYS = 7
# Below this many usable days in either window there is no comparison to
# make. It is a floor on the *comparison*, not on the total: five days
# against seven is a 30% fall that is entirely the two missing days.
MIN_DAYS = 6
# A move smaller than this is not news. Meters drift, a warm week is a
# warm week, and a report that says "1% more than last week" every week
# is a report that stops being read.
MIN_CHANGE_PCT = 5.0
# Statistic ids per WebSocket call. The recorder answers a long list
# happily; this is the same courtesy `checks.snapshot` extends it.
BATCH = 100


# ---------------------------------------------------------------------------
# Which meters
# ---------------------------------------------------------------------------

async def preferences(session) -> dict | None:
    """The house's own Energy dashboard configuration, or None.

    None means "I could not look" *and* "there is nothing configured" —
    both of which are reasons to say nothing about energy, and neither of
    which is a reason to invent a set of meters.
    """
    import ha_data  # noqa: PLC0415 — panel-local

    try:
        results = await ha_data._ws_commands(session, [{"type": "energy/get_prefs"}])
    except Exception as exc:  # noqa: BLE001 — a house with no energy
        # configuration answers this with an error, and that is an
        # ordinary state rather than a failure of the report.
        log.info("no energy preferences: %s", exc)
        return None
    prefs = results[0] if results else None
    return prefs if isinstance(prefs, dict) else None


def sources(prefs: dict | None) -> tuple[list[str], list[str]]:
    """`(consumption statistic ids, cost statistic ids)` from the prefs.

    Grid consumption only. Solar production, batteries, gas and water are
    each a different unit and a different sentence; reporting them as one
    total is the double-count this module exists to avoid, one level up.
    """
    energy: list[str] = []
    cost: list[str] = []
    for src in (prefs or {}).get("energy_sources") or []:
        if not isinstance(src, dict) or src.get("type") != "grid":
            continue
        for flow in src.get("flow_from") or []:
            if not isinstance(flow, dict):
                continue
            stat = flow.get("stat_energy_from")
            if isinstance(stat, str) and stat:
                energy.append(stat)
            # `stat_cost` only. See the module docstring: a price to
            # multiply means Home Assistant made its own cost sensor
            # under an id we would have to guess.
            money = flow.get("stat_cost")
            if isinstance(money, str) and money:
                cost.append(money)
    return energy, cost


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------

def midnight(now: float, tz: dt.tzinfo) -> dt.datetime:
    """Local midnight at the start of today. The end of the last full day."""
    local = dt.datetime.fromtimestamp(now, tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def windows(now: float, tz: dt.tzinfo) -> tuple[dt.datetime, dt.datetime, dt.datetime]:
    """`(two weeks ago, one week ago, local midnight)` — two equal windows.

    Subtracting a `timedelta` from an *aware* datetime is wall-clock
    arithmetic in Python, not absolute-time arithmetic, so each boundary
    lands on a local midnight and the two windows are seven calendar days
    each — 169 hours and 168 across a daylight-saving change, which is
    what makes them comparable, since a daily statistic starts at local
    midnight. Doing this in UTC, or on the epoch, would put a boundary at
    23:00 and let one window swallow an extra day's row.
    """
    end = midnight(now, tz)
    mid = end - dt.timedelta(days=WEEK_DAYS)
    return mid - dt.timedelta(days=WEEK_DAYS), mid, end


def consumption(rows: list[dict]) -> list[tuple[float, float]]:
    """Daily rows as `(start, used)` pairs.

    `change` is the recorder's own per-period consumption and is used
    wherever it is present. Where it is not, the step between two
    cumulative `sum` values is the same quantity derived — which is why
    the first row of a range yields nothing, and why the caller fetches
    one day more than it means to report.

    A negative value is a meter reset (see the module docstring) and is
    dropped rather than added, so the caller's day count falls and the
    window reports itself short.
    """
    out: list[tuple[float, float]] = []
    previous: float | None = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        start = row.get("start")
        if isinstance(start, bool) or not isinstance(start, (int, float)):
            continue
        # HA sends milliseconds over the WebSocket and seconds over some
        # REST paths. Anything past the year 5138 is the former.
        when = float(start) / 1000.0 if float(start) > 1e11 else float(start)

        moved, running = row.get("change"), row.get("sum")
        has_change = (isinstance(moved, (int, float))
                      and not isinstance(moved, bool))
        has_sum = (isinstance(running, (int, float))
                   and not isinstance(running, bool))

        if has_change:
            if float(moved) >= 0:
                out.append((when, float(moved)))
        elif has_sum and previous is not None:
            step = float(running) - previous
            if step >= 0:
                out.append((when, step))
        if has_sum:
            # Kept even where `change` answered, so a range that loses
            # the key part way through still has its predecessor.
            previous = float(running)
    return out


def total(series: dict[str, list[dict]], start: dt.datetime,
          end: dt.datetime) -> tuple[float, int]:
    """`(used, complete days)` across every meter, inside `[start, end)`.

    Days are counted as the *fewest* any one meter contributed, not the
    sum: two meters each missing a different day leave a total that is
    short on two days, and a count that averaged them would call that
    window complete.
    """
    used = 0.0
    days: int | None = None
    lo, hi = start.timestamp(), end.timestamp()
    for rows in series.values():
        inside = [(w, v) for w, v in consumption(rows) if lo <= w < hi]
        used += sum(v for _w, v in inside)
        days = len(inside) if days is None else min(days, len(inside))
    return used, days or 0


def change_pct(this: float, last: float) -> float | None:
    """How much more, as a percentage of last week. None when there is no
    denominator — a week that used nothing has no percentage, and
    reporting infinity as a number is how a report loses its reader."""
    if last <= 0:
        return None
    return (this - last) / last * 100.0


def worth_mentioning(pct: float | None) -> bool:
    return pct is not None and abs(pct) >= MIN_CHANGE_PCT


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------

async def _fetch(session, ids: list[str], start: dt.datetime,
                 end: dt.datetime) -> dict[str, list[dict]]:
    import ha_data  # noqa: PLC0415

    out: dict[str, list[dict]] = {}
    for i in range(0, len(ids), BATCH):
        results = await ha_data._ws_commands(session, [{
            "type": "recorder/statistics_during_period",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "statistic_ids": ids[i:i + BATCH],
            "period": "day",
            "types": ["sum", "change"],
        }])
        for sid, rows in (results[0] or {}).items():
            out[sid] = rows or []
    return out


async def _units(session, ids: list[str]) -> dict[str, str]:
    """The unit each statistic is recorded in, from the recorder itself.

    Asked of the statistics metadata rather than of the entity: a
    statistic outlives the entity that produced it (an energy source can
    name one that no longer exists), and fetching every state in the
    house to read one string would be the most expensive line in the
    report.
    """
    import ha_data  # noqa: PLC0415

    try:
        results = await ha_data._ws_commands(session, [{
            "type": "recorder/list_statistic_ids", "statistic_type": "sum"}])
    except Exception as exc:  # noqa: BLE001 — a unit is a label, and a
        # number with no unit is still the number.
        log.info("could not read statistic units: %s", exc)
        return {}
    out: dict[str, str] = {}
    for row in results[0] or []:
        if not isinstance(row, dict):
            continue
        sid = row.get("statistic_id")
        unit = (row.get("display_unit_of_measurement")
                or row.get("unit_of_measurement"))
        if isinstance(sid, str) and sid in ids and unit:
            out[sid] = str(unit)[:12]
    return out


def _first_unit(units: dict[str, str], ids: list[str]) -> str:
    for eid in ids:
        if units.get(eid):
            return units[eid]
    return ""


async def week(session, now: float | None = None,
               tz: dt.tzinfo | None = None) -> dict:
    """Last week against the week before, in whatever units the house uses.

    Always answers with an `available` flag and, when it is false, a
    `reason` in words — "no energy configuration" and "the recorder had
    nothing to say" send somebody to two different places, and a bare
    absent section sends them nowhere.
    """
    import time  # noqa: PLC0415

    now = time.time() if now is None else now
    if tz is None:
        import baselines  # noqa: PLC0415
        tz, _name = baselines.house_timezone()

    prefs = await preferences(session)
    energy_ids, cost_ids = sources(prefs)
    if not energy_ids:
        return {"available": False,
                "reason": "no energy configuration in Home Assistant"}

    prior_start, mid, end = windows(now, tz)
    # One fetch covering both windows: two calls could straddle a purge
    # and disagree about the same day, and the split is arithmetic. It
    # starts a day early so the `sum` fallback has a predecessor for the
    # earlier window's first day — see `consumption`.
    rows = await _fetch(session, energy_ids + cost_ids,
                        prior_start - dt.timedelta(days=1), end)
    if not rows:
        return {"available": False,
                "reason": "the recorder has no statistics for those meters"}

    def _half(ids: list[str]) -> dict | None:
        series = {k: v for k, v in rows.items() if k in ids}
        if not series:
            return None
        this, this_days = total(series, mid, end)
        last, last_days = total(series, prior_start, mid)
        pct = (change_pct(this, last)
               if this_days >= MIN_DAYS and last_days >= MIN_DAYS else None)
        return {"this": round(this, 2), "last": round(last, 2),
                "days": this_days, "days_before": last_days,
                "change_pct": None if pct is None else round(pct, 1),
                "comparable": this_days >= MIN_DAYS and last_days >= MIN_DAYS}

    units = await _units(session, energy_ids + cost_ids)
    out: dict = {"available": True, "reason": "",
                 "from": int(mid.timestamp()), "to": int(end.timestamp())}
    used = _half(energy_ids)
    if used:
        used["unit"] = _first_unit(units, energy_ids) or "kWh"
        out["energy"] = used
    money = _half(cost_ids)
    if money:
        money["unit"] = _first_unit(units, cost_ids)
        out["cost"] = money
    if "energy" not in out:
        return {"available": False,
                "reason": "the recorder has no statistics for those meters"}
    return out


__all__ = [
    "BATCH", "MIN_CHANGE_PCT", "MIN_DAYS", "WEEK_DAYS", "change_pct",
    "consumption", "midnight", "preferences", "sources", "total", "week",
    "windows", "worth_mentioning",
]
