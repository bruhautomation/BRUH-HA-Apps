"""What the thermal model makes sayable: a room that cannot get warm, and
a room that cannot hold it.

`panel/thermal.py` measures two numbers per room — how fast it falls
towards outdoors, and how fast anything can put heat back. Neither is a
finding on its own; what they answer is a pair of questions a house
otherwise cannot be asked, because both are invisible from any single
state.

**"This room never gets as warm as it is asked to be."** Nothing errors.
The thermostat calls, the valve opens, the boiler runs, and the room
sits two degrees under its setpoint all winter — which reads from inside
as *the heating is on, so it must be working*. Every part of that is
true and the room is still cold.

**"This room empties faster than the rest of the house."** A draught, a
missing loft hatch seal, an open flue: the temperature is fine while the
heating runs and the room is cold an hour after it stops, and no state
anywhere records the difference.

Both are extrapolations from a fit, so both are floored hard.

**A model is not evidence, and the ceiling check needs both.** The
measured gain is what the room was *seen* to do, and a thermostat that
switches off at its setpoint never lets the room show what it could have
done — so a well-heated room's measured ceiling understates it, and a
check reading the ceiling alone would fire on the healthiest houses
first. `climate.underheated` requires the arithmetic *and* the evidence:
the room must never once have been seen at the temperature it is asked
for, over a month of hours.

**A mild month cannot answer a cold-night question.** The ceiling is
computed at the coldest outdoor temperature this house actually saw, and
if that was not cold the check says nothing rather than extrapolating a
January answer out of an August.

**A comparison needs something to compare against.** `climate.heat_loss`
says nothing in a house with fewer than `MIN_ROOMS` measured rooms — two
rooms have no "rest of the house" — and it needs the room to be fast in
absolute terms as well as relatively, because twice the loss rate of a
very well insulated house is still a good room.

**And a room under two fixes is how a list stops being read.** A draughty
room that never reaches its setpoint is one problem; reporting it as both
"the heating cannot reach this" and "this room loses heat quickly" is two
cards and two fixes about one room. They share `underheated_rooms`, so
they cannot disagree about which room that is — the same arrangement
`dev.unavailable` and `dev.zwave_dead` keep.

Three more read the same model against what a room is doing *now*, or
against what it does every morning.

**`climate.preheat`** is the one the model was built for. A schedule that
starts the heating at a fixed hour warms the bedroom to its setpoint at
07:40 in a house that is up at 07:00, every weekday, and nothing anywhere
records that as a fault — the automation ran, the thermostat called, the
room got warm. It needs three measurements agreeing: `rhythm` for when
this house actually gets up, `baselines` for what the room reads at that
hour of the week, and the model for how long the climb takes. It reports
weekday mornings only, because that is where a schedule exists and where
`rhythm` has the days — a weekend takes about five weeks to measure — and
it says nothing at all until the wake time is measured rather than
guessed, since a preheat time pinned to a typed-in 07:00 is a guess
wearing a number.

**`climate.window`** compares a room's observed fall against what its own
`k` allows. Falling twice as fast as physics permits is something open —
and the whole check is only sayable because the model exists: the same
half-degree in ten minutes is a draught in one room and an ordinary
evening in another.

**`climate.freeze`** takes the current reading and asks when it reaches
the floor pipes burst at. It requires the room to be *already falling*
rather than assuming nothing heats it, because `coast` describes an
unheated room and "the heating is off" is not something any state says.

Both live checks read five-minute statistics rather than hourly ones: an
hourly mean cannot see a window opened forty minutes ago, because it is
still inside the hour that has not closed. And both stand down for the
room the other claims, freeze first — a room freezing because a window is
open is one problem, and the sentence that names the freezing is the one
worth waking somebody for.
"""
from __future__ import annotations

from ._util import House, num

# How far under its setpoint a room has to have stayed, all month, before
# this is a fault rather than a thermostat that is slightly optimistic.
# Degrees Celsius; converted for a Fahrenheit house.
UNDER_MARGIN_C = 1.0
# The coldest outdoor hour in the window has to be at least this cold, or
# the month held no night that could test the heating.
COLD_ENOUGH_C = 10.0
# A house needs this many measured rooms before one of them can be
# unusual against the others.
MIN_ROOMS = 4
# How far above the house's median loss rate is "far".
LOSS_FACTOR = 2.0
# And how fast is fast, whatever the rest of the house does: a room that
# is half way to outdoors in six hours.
FAST_TAU_H = 6.0
# Past this it is the measurement, not a room. A cold snap, a boiler that
# was off for a week, or a recorder that was purged moves every room at
# once — the same cap `base.unusual` and `evening.left_open` carry.
MAX_UNDERHEATED = 3
MAX_LOSS_ROWS = 2


# --- climate.preheat -------------------------------------------------------
# How far under its setpoint the room has to be at the moment the house
# gets up. Under this it is a schedule that is very slightly early rather
# than one that is wrong.
PREHEAT_SHORTFALL_C = 1.0
# How much later to look for proof the heating *does* get there. Two hours
# after the house is up is still the morning, and a room that has not
# arrived by then is `climate.underheated`'s finding, not this one.
PREHEAT_LATER_H = 2
# Weekday buckets that have to carry a sample before their median means
# anything. Three of five is a fortnight of ordinary weeks.
PREHEAT_MIN_BUCKETS = 3
# A lead under this is not worth moving a schedule for, and one over it
# says the model or the setpoint is wrong rather than the schedule.
PREHEAT_MIN_LEAD_MIN = 20.0
PREHEAT_MAX_LEAD_H = 4.0
MAX_PREHEAT = 2

# --- climate.window --------------------------------------------------------
# How much faster than the model allows counts as "something is open". A
# room cannot lose heat faster than its own coefficient says without
# either a hole in it or a wrong model, and the factor is what keeps an
# ordinary fit's slop out.
WINDOW_FACTOR = 2.2
# And the excess has to be a real rate, not a factor over almost nothing:
# twice 0.1 degrees an hour is 0.2 degrees an hour.
WINDOW_MIN_EXCESS = 0.8
# Below this difference between the room and outside there is nothing for
# a window to do — an open window in mild weather changes nothing, and the
# model's own prediction near zero is where its errors are largest.
WINDOW_MIN_DELTA_C = 6.0
# A statistics row this old is not "now".
WINDOW_MAX_AGE_MIN = 45.0
# A house being aired out moves every room at once, and reporting that as
# four draughts is reporting the weather.
MAX_WINDOW = 2

# --- climate.freeze --------------------------------------------------------
# Where pipes are at risk. Not zero: water in an outside wall freezes long
# before the room's own thermometer reads freezing.
FREEZE_FLOOR_C = 5.0
# How far ahead it is worth saying. Past this the answer is about the
# weather rather than about tonight, and the next pass will say it again
# when it is true.
FREEZE_HORIZON_H = 12.0
MAX_FREEZE = 3

def _deg(celsius: float, unit: str) -> float:
    """A temperature *difference* in the room's own unit."""
    return celsius * 1.8 if unit == "°F" else celsius


def _rooms(snap: dict) -> tuple[dict, dict]:
    """`(store, rooms)` for the thermal store, or two empty dicts."""
    store = snap.get("thermal") or {}
    return store, (store.get("rooms") or {})


def _target_for(house: House, area: str) -> tuple[float, str] | None:
    """The setpoint asked for in this area, and the entity that asks it.

    A climate entity that is off is not asking for anything, and one
    running a range (heat_cool, with a high and a low) is answering a
    different question than "is this room warm enough" — the low is what
    the heating is asked for, so that is what is read.
    """
    if not area:
        return None
    best: tuple[float, str] | None = None
    for eid, st in sorted((house.states or {}).items()):
        if not eid.startswith("climate.") or house.area_of(eid) != area:
            continue
        state = str(st.get("state") or "").lower()
        if state in ("off", "unavailable", "unknown", ""):
            continue
        attrs = st.get("attributes") or {}
        target = num(attrs.get("temperature"))
        if target is None:
            target = num(attrs.get("target_temp_low"))
        if target is None:
            continue
        # The coolest setpoint in the room is the one it has to clear:
        # two thermostats in one area asking for different things is a
        # room that is warm enough when it meets the lower of them.
        if best is None or target < best[0]:
            best = (target, eid)
    return best


def underheated_rooms(snap: dict) -> list[dict]:
    """Rooms asked for a temperature they were never once seen to reach.

    Shared, so `heat_loss` can stand down for a room this claims rather
    than reporting the same room under a second fix.
    """
    import thermal  # noqa: PLC0415 — panel-local, like every other check

    store, rooms = _rooms(snap)
    coldest = store.get("coldest")
    if not rooms or not isinstance(coldest, (int, float)):
        return []
    unit = str(store.get("unit") or "°C")
    if coldest > _cold_enough(unit):
        # No night in the window was cold enough to test the heating, so
        # a ceiling computed at this outdoor temperature says nothing
        # about January. "I could not look" rather than "it is fine".
        return []

    house = House(snap)
    margin = _deg(UNDER_MARGIN_C, unit)
    out = []
    for eid, entry in sorted(rooms.items()):
        if not entry.get("gain") or not entry.get("k"):
            continue
        warmest = num(entry.get("warmest"))
        if warmest is None:
            continue
        area = house.area_of(eid) or entry.get("area") or ""
        asked = _target_for(house, area)
        if asked is None:
            continue
        target, thermostat = asked
        # The evidence first: a room that has been at its setpoint is not
        # a room that cannot reach it, whatever the fit extrapolates.
        if warmest > target - margin:
            continue
        top = thermal.ceiling(entry, float(coldest))
        if top is None or top >= target:
            continue
        out.append({
            "entity_id": eid, "room": area or house.name(eid),
            "name": house.name(eid), "target": target,
            "thermostat": thermostat, "warmest": warmest,
            "ceiling": top, "unit": unit, "coldest": float(coldest),
            "entry": entry,
        })
    return out


def _cold_enough(unit: str) -> float:
    """The coldest an outdoor hour has to have been, in the house's unit."""
    return COLD_ENOUGH_C * 1.8 + 32.0 if unit == "°F" else COLD_ENOUGH_C


def underheated(snap: dict, now: float) -> list[dict]:
    """A room the heating cannot bring to what it is asked for."""
    hits = underheated_rooms(snap)
    if not hits or len(hits) > MAX_UNDERHEATED:
        return []
    out = []
    for hit in hits:
        unit = hit["unit"]
        short = hit["target"] - hit["warmest"]
        out.append({
            "text": f"{hit['room']} never reaches the temperature it is set to",
            "detail": (
                f"{hit['name']} is asked for {hit['target']:g}{unit} and the "
                f"warmest it has been in the last month is "
                f"{hit['warmest']:g}{unit}. At the coldest it got outside "
                f"({hit['coldest']:g}{unit}) the heat going in balances the "
                f"heat going out at about {hit['ceiling']:.1f}{unit}, so it "
                f"is short by roughly {short:g}{unit} whatever the "
                "thermostat is set to."),
            "fix": (
                "Something is limiting what reaches this room rather than "
                "the schedule being short: a radiator valve not opening "
                "fully, a radiator undersized for the room, a bled system, "
                "or a zone that never calls. Check the valve first — it is "
                "the cheapest of the four to rule out."),
            "severity": "warning",
            "fixable": False,
            "entity_id": hit["entity_id"],
        })
    return out


def heat_loss(snap: dict, now: float) -> list[dict]:
    """A room that empties much faster than the rest of the house."""
    import baselines  # noqa: PLC0415

    store, rooms = _rooms(snap)
    measured = {eid: e for eid, e in rooms.items() if e.get("k")}
    if len(measured) < MIN_ROOMS:
        return []
    claimed = {h["entity_id"] for h in underheated_rooms(snap)}
    middle = baselines.median([float(e["k"]) for e in measured.values()])
    if middle <= 0:
        return []

    house = House(snap)
    hits = []
    for eid, entry in sorted(measured.items()):
        if eid in claimed:
            continue
        k = float(entry["k"])
        tau = float(entry.get("tau_h") or (1.0 / k))
        if k < middle * LOSS_FACTOR or tau > FAST_TAU_H:
            continue
        hits.append((tau, eid, entry))
    if not hits or len(hits) > MAX_LOSS_ROWS:
        return []
    hits.sort()

    out = []
    house_tau = 1.0 / middle
    for tau, eid, entry in hits:
        room = house.area_of(eid) or entry.get("area") or house.name(eid)
        out.append({
            "text": f"{room} loses heat much faster than the rest of the house",
            "detail": (
                f"Measured over a month of nights, {house.name(eid)} falls "
                f"half way to outside in about {tau:.1f} hours; the rest of "
                f"this house takes about {house_tau:.1f}. Nothing is wrong "
                "with the heating — the heat is leaving as fast as it "
                "arrives."),
            "fix": (
                "Look for where it is going: a draught under a door or "
                "through a letterbox, a window that does not seal, an open "
                "flue, a loft hatch, or a room with much more glass than "
                "the others. If this room is meant to be cool, press Wrong "
                "and say so."),
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# climate.preheat
# ---------------------------------------------------------------------------

def _weekday_wake(now: float) -> tuple[float | None, str]:
    """The measured weekday wake minute, and the timezone name.

    ``None`` when this house has not been measured yet — which is a real
    state for the first few weeks and reads as "say nothing", never as
    seven o'clock. `rhythm` is asked through its own helper rather than
    by reaching into the profile, so this cannot drift from what the
    morning brief reads.
    """
    try:
        import baselines  # noqa: PLC0415
        import rhythm  # noqa: PLC0415
    except Exception:  # noqa: BLE001 — the package stays importable without
                       # the panel around it, exactly as `evening` does
        return None, "UTC"
    import datetime as dt  # noqa: PLC0415

    tz, name = baselines.house_timezone()
    local = dt.datetime.fromtimestamp(now, tz)
    # Any weekday will do — `wake_minute` keys on the *kind* of day, and a
    # Monday is what the weekday half was measured from.
    monday = local - dt.timedelta(days=local.weekday())
    return rhythm.wake_minute(rhythm.profile(), monday), name


def _weekday_median(entry: dict, hour: int) -> float | None:
    """The median of this entity's weekday buckets at `hour`.

    One weekday is a day; five of them is a habit. A bucket with no
    samples is absent rather than zero, and under `PREHEAT_MIN_BUCKETS`
    the answer is "not measured at this hour" rather than a median of two.
    """
    import baselines  # noqa: PLC0415

    buckets = (entry or {}).get("buckets") or {}
    seen = []
    for dow in range(5):
        bucket = buckets.get(str(dow * 24 + hour))
        if isinstance(bucket, dict) and isinstance(bucket.get("median"),
                                                   (int, float)):
            seen.append(float(bucket["median"]))
    if len(seen) < PREHEAT_MIN_BUCKETS:
        return None
    return baselines.median(seen)


def preheat(snap: dict, now: float) -> list[dict]:
    """A room still climbing at the hour this house actually gets up."""
    import thermal  # noqa: PLC0415

    store, rooms = _rooms(snap)
    outdoor_id = store.get("outdoor") or ""
    if not rooms or not outdoor_id:
        return []
    unit = str(store.get("unit") or "°C")
    wake, _tz = _weekday_wake(now)
    if wake is None:
        return []
    hour = int(wake // 60)
    # A wake time late enough that "two hours later" is the next day is
    # not a morning, and wrapping the bucket would compare a room to
    # itself on a different day.
    if hour + PREHEAT_LATER_H > 23:
        return []

    base = (snap.get("baselines") or {}).get("entities") or {}
    outside = _weekday_median(base.get(outdoor_id) or {}, hour)
    if outside is None:
        return []

    house = House(snap)
    claimed = {h["entity_id"] for h in underheated_rooms(snap)}
    margin = _deg(PREHEAT_SHORTFALL_C, unit)
    hits = []
    for eid, entry in sorted(rooms.items()):
        if eid in claimed or not entry.get("k") or not entry.get("gain"):
            continue
        at_wake = _weekday_median(base.get(eid) or {}, hour)
        later = _weekday_median(base.get(eid) or {}, hour + PREHEAT_LATER_H)
        if at_wake is None or later is None:
            continue
        area = house.area_of(eid) or entry.get("area") or ""
        asked = _target_for(house, area)
        if asked is None:
            continue
        target = asked[0]
        if at_wake > target - margin:
            continue
        # The heating has to actually get there later in the morning. A
        # room that never arrives is `climate.underheated`'s, and saying
        # "start earlier" about one is advice that cannot work.
        if later < target - margin:
            continue
        lead_h = thermal.hours_to_warm(entry, at_wake, outside, target)
        if lead_h is None:
            continue
        lead_min = lead_h * 60.0
        if lead_min < PREHEAT_MIN_LEAD_MIN or lead_h > PREHEAT_MAX_LEAD_H:
            continue
        hits.append((-(target - at_wake), eid, entry, at_wake, target,
                     lead_min, area))

    if not hits or len(hits) > MAX_PREHEAT:
        return []
    hits.sort()

    out = []
    for _rank, eid, entry, at_wake, target, lead_min, area in hits:
        room = area or house.name(eid)
        start = int(wake - lead_min) % 1440
        out.append({
            "text": f"{room} is still warming up when this house gets up",
            "detail": (
                f"On weekday mornings {house.name(eid)} reads about "
                f"{at_wake:.1f}{unit} at {int(wake) // 60:02d}:"
                f"{int(wake) % 60:02d}, which is when somebody here is "
                f"first up, and it is asked for {target:g}{unit}. It gets "
                f"there later in the morning, so nothing is broken — the "
                f"heating starts too late rather than falling short. From "
                f"that temperature this room takes about "
                f"{int(round(lead_min))} minutes to climb, so the call "
                f"would need to come at about {start // 60:02d}:"
                f"{start % 60:02d}."),
            "fix": (
                "Move the heating schedule for this room earlier by about "
                f"{int(round(lead_min))} minutes, or give the thermostat a "
                "target that starts before the house does. brAIn measured "
                "the wake time rather than assuming it — if mornings here "
                "have changed, press Wrong and say so."),
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# climate.window and climate.freeze — the same live reading, two questions
# ---------------------------------------------------------------------------

def _live(snap: dict) -> tuple[dict, dict, str, float | None]:
    """`(rooms, recent, unit, outdoor_now)` for the two live checks."""
    import thermal  # noqa: PLC0415

    store, rooms = _rooms(snap)
    recent = store.get("recent") or {}
    unit = str(store.get("unit") or "°C")
    outdoor_id = store.get("outdoor") or ""
    seen = thermal.latest(recent.get(outdoor_id) or []) if outdoor_id else None
    return rooms, recent, unit, (seen[1] if seen else None)


def freezing_rooms(snap: dict, now: float) -> list[dict]:
    """Rooms falling now that reach the freeze floor inside the horizon.

    Shared, so `climate.window` can stand down for a room this claims
    rather than reporting the same room under a second fix.
    """
    import thermal  # noqa: PLC0415

    rooms, recent, unit, outside = _live(snap)
    if not rooms or outside is None:
        return []
    floor = _deg_absolute(FREEZE_FLOOR_C, unit)
    if outside > floor:
        # A room cannot fall below what is outside it, so there is nothing
        # to forecast — and `hours_to_fall` says so structurally.
        return []

    out = []
    for eid, entry in sorted(rooms.items()):
        rows = recent.get(eid) or []
        seen = thermal.latest(rows)
        if seen is None or not entry.get("k"):
            continue
        _when, indoor = seen
        # Already falling, measured — rather than assuming nothing heats
        # it. `coast` describes an unheated room and no state anywhere
        # says the heating is off.
        fall = thermal.recent_fall(rows, now)
        if fall is None or fall["age_min"] > WINDOW_MAX_AGE_MIN:
            continue
        hours = thermal.hours_to_fall(entry, indoor, outside, floor)
        if hours is None or hours > FREEZE_HORIZON_H:
            continue
        out.append({"entity_id": eid, "entry": entry, "indoor": indoor,
                    "outside": outside, "hours": hours, "unit": unit,
                    "floor": floor})
    return out


def _deg_absolute(celsius: float, unit: str) -> float:
    """A temperature, not a difference — 5 °C is 41 °F."""
    return celsius * 1.8 + 32.0 if unit == "°F" else celsius


def freeze(snap: dict, now: float) -> list[dict]:
    """A room on course for the temperature pipes are at risk at."""
    hits = freezing_rooms(snap, now)
    if not hits or len(hits) > MAX_FREEZE:
        return []
    house = House(snap)
    hits.sort(key=lambda h: h["hours"])
    out = []
    for hit in hits:
        eid, unit = hit["entity_id"], hit["unit"]
        room = house.area_of(eid) or hit["entry"].get("area") or house.name(eid)
        hours = hit["hours"]
        when = "under an hour" if hours < 1 else f"about {hours:.0f} hours"
        out.append({
            "text": f"{room} is on course to get cold enough to matter",
            "detail": (
                f"{house.name(eid)} reads {hit['indoor']:.1f}{unit} and is "
                f"falling, and it is {hit['outside']:.1f}{unit} outside. At "
                f"the rate this room loses heat it reaches "
                f"{hit['floor']:g}{unit} in {when} if nothing heats it — "
                "which is where water in an outside wall starts to be at "
                "risk, well before the room's own thermometer reads "
                "freezing."),
            "fix": (
                "Check the heating is actually reaching this room, and "
                "that nothing is open. If this room is meant to be unheated "
                "and its pipes are lagged, press Wrong and say so."),
            "severity": "critical",
            "fixable": False,
            "entity_id": eid,
        })
    return out


def window(snap: dict, now: float) -> list[dict]:
    """A room losing heat faster than its own coefficient allows."""
    import thermal  # noqa: PLC0415

    rooms, recent, unit, outside = _live(snap)
    if not rooms or outside is None:
        return []
    claimed = {h["entity_id"] for h in freezing_rooms(snap, now)}
    min_delta = _deg(WINDOW_MIN_DELTA_C, unit)
    min_excess = _deg(WINDOW_MIN_EXCESS, unit)

    house = House(snap)
    hits = []
    for eid, entry in sorted(rooms.items()):
        if eid in claimed or not entry.get("k"):
            continue
        fall = thermal.recent_fall(recent.get(eid) or [], now)
        if fall is None or fall["age_min"] > WINDOW_MAX_AGE_MIN:
            continue
        if fall["from"] - outside < min_delta:
            continue
        # Measured against where the room STARTED, which is the fastest
        # the model ever claims over this span: as the room falls its own
        # prediction falls with it, so using the start is the reading that
        # gives the model the benefit of the doubt.
        expected = thermal.expected_fall(entry, fall["from"], outside)
        if expected is None or expected <= 0:
            continue
        if fall["rate"] < expected * WINDOW_FACTOR:
            continue
        if fall["rate"] - expected < min_excess:
            continue
        hits.append((-(fall["rate"] / expected), eid, entry, fall, expected))

    if not hits or len(hits) > MAX_WINDOW:
        return []
    hits.sort()

    out = []
    for _rank, eid, entry, fall, expected in hits:
        room = house.area_of(eid) or entry.get("area") or house.name(eid)
        out.append({
            "text": f"{room} is losing heat faster than it can",
            "detail": (
                f"{house.name(eid)} fell from {fall['from']:g}{unit} to "
                f"{fall['to']:g}{unit} over the last "
                f"{int(round(fall['span_min']))} minutes — about "
                f"{fall['rate']:.1f}{unit} an hour, where this room's own "
                f"measured insulation allows about {expected:.1f}{unit} an "
                f"hour at {outside:.1f}{unit} outside. Heat is leaving by "
                "some route the walls do not have."),
            "fix": (
                "Something is open: a window, a door to outside, a roof "
                "light, or a vent. If nothing is, the room may have been "
                "measured during a spell that does not describe it — press "
                "Wrong and brAIn will stop asking about this one."),
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


CHECKS = [
    {"id": "climate.underheated",
     "title": "Asked for a temperature it never reaches",
     "needs": ("states", "registry", "thermal"), "run": underheated},
    {"id": "climate.heat_loss",
     "title": "Loses heat faster than the rest of the house",
     "needs": ("states", "registry", "thermal"), "run": heat_loss},
    {"id": "climate.preheat",
     "title": "Still warming when the house gets up",
     "needs": ("states", "registry", "thermal", "baselines"), "run": preheat},
    {"id": "climate.freeze",
     "title": "On course to get cold enough to matter",
     "needs": ("states", "registry", "thermal"), "run": freeze},
    {"id": "climate.window",
     "title": "Losing heat faster than it can",
     "needs": ("states", "registry", "thermal"), "run": window},
]

__all__ = ["CHECKS", "freezing_rooms", "underheated_rooms"]
