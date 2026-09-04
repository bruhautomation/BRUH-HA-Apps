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


CHECKS = [
    {"id": "climate.underheated",
     "title": "Asked for a temperature it never reaches",
     "needs": ("states", "registry", "thermal"), "run": underheated},
    {"id": "climate.heat_loss",
     "title": "Loses heat faster than the rest of the house",
     "needs": ("states", "registry", "thermal"), "run": heat_loss},
]

__all__ = ["CHECKS", "underheated_rooms"]
