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

import re

import numfmt

from ._util import House, domain_of, join_names, num

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


def _room_air(house: House, rooms: dict, check_id: str) -> dict:
    """The measured rooms whose thermometer reads the room's air.

    The nightly build leaves out what an entity's own name says is a
    machine (`thermal.room_candidates`); this reads the registries too, at
    the check, so a store built before cannot carry one in: a reading filed
    as the device's own, or one on a device that is a manifold, a coil, a
    pipe or a tank (`thermal.on_a_machine`), or a printer's or a computer's
    (`devices.machine_of`), or one the owner marked as not measuring the
    room's air or called broken (`House.room_air_verdict`). Each left out
    is one `explained` trail line. Not read by `climate.freeze`: a pipe heading for freezing is
    still news (it skips the owner's mark alone, `freezing_rooms`).
    """
    import thermal  # noqa: PLC0415 — panel-local, like every other check

    from . import devices  # noqa: PLC0415 — it imports this package's util

    out = {}
    for eid, entry in rooms.items():
        kind, said = house.room_air_verdict(eid)
        if kind in ("marked", "not_air", "broken"):
            house.gave_up(check_id, [{"entity_id": eid}],
                          f"{said}, so it is not read as a room",
                          kind="explained")
            continue
        why = thermal.on_a_machine(house.registry.get(eid),
                                   house.device_of(eid))
        if not why and devices.machine_of(house, eid):
            why = "it is a printer's or a computer's temperature"
        if why:
            house.gave_up(check_id, [{"entity_id": eid}],
                          f"{why}, not the air of a room", kind="explained")
            continue
        out[eid] = entry
    return out


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
    rooms = _room_air(house, rooms, "climate.underheated")
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
    house = House(snap)
    hits = [h for h in underheated_rooms(snap)
            if house.should_report(h["entity_id"], "climate.underheated")]
    if not hits or len(hits) > MAX_UNDERHEATED:
        return []
    out = []
    for hit in hits:
        unit = hit["unit"]
        short = hit["target"] - hit["warmest"]
        out.append({
            "text": f"{hit['room']} never reaches the temperature it is set to",
            "detail": (
                f"{hit['name']} is asked for {numfmt.temperature(hit['target'], unit)} and the "
                f"warmest it has been in the last month is "
                f"{numfmt.temperature(hit['warmest'], unit)}. At the coldest it got outside "
                f"({numfmt.temperature(hit['coldest'], unit)}) the heat going in balances the "
                f"heat going out at about {numfmt.temperature(hit['ceiling'], unit)}, so it "
                f"is short by roughly {numfmt.temperature(short, unit, delta=True)} whatever the "
                "thermostat is set to."),
            "fix": (
                "Something is limiting the heat that reaches this room, "
                "rather than the schedule being too short: a valve or vent "
                "that does not open fully, a heater too small for the room, "
                "or a zone that never calls for heat. Check the valve or "
                "vent first — it is the cheapest to rule out."),
            "severity": "warning",
            "fixable": False,
            "entity_id": hit["entity_id"],
        })
    return out


# What the snapshot can say about where a room's heat goes: its own door
# and window sensors. A list of fixtures the data does not show (a mail
# slot, a flue, an attic hatch) is a guess about somebody's house dressed
# as advice, so only the openings the house has sensors on are named.
OPENING_CLASSES = frozenset({"door", "window", "opening", "garage_door"})


def _openings_in(house: House, eid: str) -> list[str]:
    area = house.area_of(eid)
    if not area:
        return []
    names = []
    for other, st in sorted(house.states.items()):
        if not other.startswith("binary_sensor."):
            continue
        attrs = (st or {}).get("attributes") or {}
        if str(attrs.get("device_class") or "") not in OPENING_CLASSES:
            continue
        if house.area_of(other) != area:
            continue
        names.append(house.label(other))
    return names


def _heat_loss_fix(house: House, eid: str, room: str) -> str:
    area = house.area_of(eid)
    room = f"the {area}" if area else "this room"
    openings = _openings_in(house, eid)
    if openings:
        return (f"Look for where {room} lets heat out: check that "
                f"{join_names(openings)} close and seal properly, then the "
                "gaps around the room's other doors and windows.")
    return (f"Look for where {room} lets heat out: the gaps around its "
            "doors and windows are the usual place, and an opening left "
            "open is the cheapest one to rule out.")


# --- which rooms a heat-loss ranking may compare ---------------------------
# A switch whose name says it heats a room. Home Assistant has no device
# class for "this switch is a heater", so the words are the only reading;
# a `climate` entity needs none.
HEATER_DOMAINS = frozenset({"switch", "input_boolean"})
_HEATER_WORDS = re.compile(
    r"\b(heater|heaters|heating|radiator|radiators|underfloor|baseboard|"
    r"floor heat|space heater)\b", re.I)
# What the household says about a space nothing conditions. "Not heated"
# and "isn't heated" are the same sentence; "well insulated" is the
# opposite one and must not match, so every alternative names the absence.
_UNCONDITIONED = re.compile(
    r"\b(unheated|uninsulated|unconditioned|non[- ]?heated|"
    r"(?:not|isn'?t|is not|never|no)\s+(?:heated|insulated|conditioned)|"
    r"no (?:heating|heat|insulation|thermostat))\b", re.I)


def unconditioned_from(rows) -> dict:
    """The rooms and sensors the household said nothing heats.

    ``rows`` are facts-store rows (any source, the Wrong reasons among
    them). An `area:` subject names the room; an entity subject names a
    sensor, whose room the check resolves against the registry it holds.
    ``{"areas": [...], "entities": [...], "stated": {"areas", "entities"}}``,
    sorted, for the snapshot: ``stated`` is the part said as a fact about
    the house rather than as the reason for a Wrong (`source` is not
    `correction`), which is all `frost_ahead` names a space on (#1200).
    """
    found = {"all": (set(), set()), "stated": (set(), set())}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        if not _UNCONDITIONED.search(str(row.get("text") or "")):
            continue
        subjects = row.get("subjects")
        if not isinstance(subjects, list) or not subjects:
            subjects = [row.get("subject") or ""]
        into = ["all"] + ([] if row.get("source") == "correction"
                          else ["stated"])
        for subject in subjects:
            subject = str(subject or "")
            for which in into:
                areas, entities = found[which]
                if subject.startswith("area:") and subject[5:]:
                    areas.add(subject[5:])
                elif "." in subject and ":" not in subject:
                    entities.add(subject)
    areas, entities = found["all"]
    stated_areas, stated_entities = found["stated"]
    return {"areas": sorted(areas), "entities": sorted(entities),
            "stated": {"areas": sorted(stated_areas),
                       "entities": sorted(stated_entities)}}


def conditioned_areas(house: House) -> set[str]:
    """The area ids something heats: a thermostat, or a heater switch.

    A `climate` entity counts whatever it is doing now — off in August is
    still the room's heating — and a room the household said is
    unheated or uninsulated (`snap["unconditioned"]`, read off the facts
    store by the collector) is not one, thermostat or not.
    """
    return heated_areas(house) - said_unconditioned(house)


def heated_areas(house: House) -> set[str]:
    """The area ids something heats by what is in them (a thermostat, a
    heater switch), whatever the household said about the room."""
    heated: set[str] = set()
    for eid in set(house.states) | set(house.registry):
        domain = domain_of(eid)
        if domain == "climate" or (
                domain in HEATER_DOMAINS
                and _HEATER_WORDS.search(f"{eid.replace('_', ' ')} "
                                         f"{house.name(eid)}")):
            area = house.area_id_of(eid)
            if area:
                heated.add(area)
    return heated


def said_unconditioned(house: House) -> set[str]:
    """The area ids the household said nothing heats (`snap["unconditioned"]`):
    a room named, or the room of a sensor named.

    A fact about the ROOM, not a correction of one check, so every check
    that judges a room by how it cools against the house's heating reads
    it (`heat_loss` through `conditioned_areas`, `window`, `freeze`): a
    porch the owner said is unheated tracks outside, and its falling is
    not a fault. A room with no heating that nobody described is left as
    it was.
    """
    said = house.snap.get("unconditioned") or {}
    if not isinstance(said, dict):
        return set()
    areas = {str(a) for a in said.get("areas") or () if a}
    areas |= {house.area_id_of(str(e)) for e in said.get("entities") or ()}
    return {a for a in areas if a}


def follows_outside(house: House, eid: str) -> str:
    """Why this thermometer's slow drift is the weather, by the household's
    own word, or "" (#1317).

    A temperature reading of a room's air in a space the household said
    nothing heats (`said_unconditioned`) follows outside: weeks of it
    falling into winter is the season, not the house losing heat. Only a
    reading the heat model measured AS a room (`snap["thermal"]["rooms"]`,
    which every room-air test has passed: in the band a room sits in, not
    named or behaving as a machine) and nothing since set aside
    (`House.room_air_verdict`, a probe's device): a freezer's probe in an
    unheated garage is never a room there, and is judged as before.
    """
    import thermal  # noqa: PLC0415 — panel-local, like every other check

    from . import devices  # noqa: PLC0415 — it imports this package's util

    area = house.area_id_of(eid)
    # "Uninsulated" is said of heated rooms too: a room with a thermostat
    # or a heater of its own is heated whatever was said about its walls.
    if area not in said_unconditioned(house) or area in heated_areas(house):
        return ""
    if eid not in _rooms(house.snap)[1]:
        return ""
    if house.room_air_verdict(eid)[0]:
        return ""
    if thermal.on_a_machine(house.registry.get(eid), house.device_of(eid)) \
            or devices.machine_of(house, eid):
        return ""
    return ("you said nothing heats this space, so its temperature follows "
            "outside and a drift over weeks is the season")


def _left_unheated(house: House, eid: str, unheated: set[str],
                   check_id: str) -> bool:
    """True, with its trail line, when ``eid`` is in a room the household
    said nothing heats."""
    if house.area_id_of(eid) not in unheated:
        return False
    house.gave_up(check_id, [{"entity_id": eid}],
                  "you said nothing heats this room, so it is expected to "
                  "follow the outside temperature", kind="explained")
    return True


def heat_loss(snap: dict, now: float) -> list[dict]:
    """A room that empties much faster than the rest of the house.

    Only rooms something heats are compared — with each other, and for
    the median. A garage or a loft with no thermostat has no heat of the
    house's to lose, so it was the leakiest room in every house that had
    one, and it says nothing about a heated room that it falls faster.
    """
    import baselines  # noqa: PLC0415

    store, rooms = _rooms(snap)
    house = House(snap)
    rooms = _room_air(house, rooms, "climate.heat_loss")
    heated = conditioned_areas(house)
    measured = {eid: e for eid, e in rooms.items()
                if e.get("k") and house.area_id_of(eid) in heated}
    unheated = sorted(eid for eid, e in rooms.items()
                      if e.get("k") and eid not in measured)
    if unheated:
        house.gave_up("climate.heat_loss",
                      [{"entity_id": eid} for eid in unheated],
                      "nothing heats this room (no thermostat or heater, or "
                      "you said it is unheated), so it is not compared",
                      kind="explained")
    if len(measured) < MIN_ROOMS:
        return []
    claimed = {h["entity_id"] for h in underheated_rooms(snap)}
    middle = baselines.median([float(e["k"]) for e in measured.values()])
    if middle <= 0:
        return []

    hits = []
    for eid, entry in sorted(measured.items()):
        if eid in claimed:
            continue
        k = float(entry["k"])
        tau = float(entry.get("tau_h") or (1.0 / k))
        if k < middle * LOSS_FACTOR or tau > FAST_TAU_H:
            continue
        if not house.should_report(eid, "climate.heat_loss"):
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
            "fix": _heat_loss_fix(house, eid, room),
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
    rooms = _room_air(house, rooms, "climate.preheat")
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
        if not house.should_report(eid, "climate.preheat"):
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
                f"{numfmt.temperature(at_wake, unit)} at {int(wake) // 60:02d}:"
                f"{int(wake) % 60:02d}, which is when somebody here is "
                f"first up, and it is asked for {numfmt.temperature(target, unit)}. It gets "
                f"there later in the morning, so nothing is broken — the "
                f"heating starts too late rather than falling short. From "
                f"that temperature this room takes about "
                f"{numfmt.span(lead_min * 60)} to climb, so the call "
                f"would need to come at about {start // 60:02d}:"
                f"{start % 60:02d}."),
            "fix": (
                "Move the heating schedule for this room earlier by about "
                f"{numfmt.span(lead_min * 60)}, or give the thermostat a "
                "target that starts before the house does."),
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


def freezing_rooms(snap: dict, now: float,
                   set_aside: list | None = None) -> list[dict]:
    """Rooms falling now that reach the freeze floor inside the horizon.

    Shared, so `climate.window` can stand down for a room this claims
    rather than reporting the same room under a second fix.

    A thermometer the owner called broken (#1202, `House.said_broken`) is
    not evidence of freezing: what it would have claimed goes into
    ``set_aside`` when the caller hands a list, so `freeze` can say it did
    not rely on it, and it is never a hit. Every other room is read as
    before.
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

    house = House(snap)
    unheated = said_unconditioned(house)
    out = []
    for eid, entry in sorted(rooms.items()):
        # A probe on a pipe is still read here, on purpose; a sensor the
        # owner said does not measure the room's air (#1082: a manifold
        # they called broken, a thermometer inside a box) is not, and
        # a room they said nothing heats (#1200) is marked for `freeze` to
        # leave out (still claimed here, so `window` does not take it up).
        # One the owner called broken (#1202) is set aside, never a hit;
        # `window` leaves it out too (`_room_air`).
        verdict = house.room_air_verdict(eid)[0]
        if verdict == "marked":
            continue
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
        hit = {"entity_id": eid, "entry": entry, "indoor": indoor,
               "outside": outside, "hours": hours, "unit": unit,
               "floor": floor,
               "said_unheated": house.area_id_of(eid) in unheated}
        if verdict == "broken":
            if set_aside is not None:
                set_aside.append(hit)
            continue
        out.append(hit)
    return out


def _other_thermometers(house: House, rooms: dict, eid: str) -> list[str]:
    """The modelled thermometers in the same area as ``eid`` that the freeze
    check still reads — none marked, none called broken."""
    area = house.area_id_of(eid)
    if not area:
        return []
    return [other for other in sorted(rooms) if other != eid
            and house.area_id_of(other) == area
            and house.room_air_verdict(other)[0] not in ("marked", "broken")]


def _deg_absolute(celsius: float, unit: str) -> float:
    """A temperature, not a difference — 5 °C is 41 °F."""
    return celsius * 1.8 + 32.0 if unit == "°F" else celsius


def freeze(snap: dict, now: float) -> list[dict]:
    """A room on course for the temperature pipes are at risk at."""
    house = House(snap)
    unheated = said_unconditioned(house)
    # A room the household said nothing heats (#1200) follows outside by
    # design, "check the heating is reaching it" has no heating to check,
    # and its cold night is `climate.frost_ahead`'s to warn about, as the
    # unheated space it is — the warning they can answer.
    set_aside: list[dict] = []
    hits = [h for h in freezing_rooms(snap, now, set_aside)
            if not (h["said_unheated"] and _left_unheated(
                house, h["entity_id"], unheated, "climate.freeze"))
            and house.should_report(h["entity_id"], "climate.freeze")]
    # What a sensor the owner called broken would have said is not a
    # warning (#1202), and the trail says so in words. A room it was the
    # only thermometer for is NOT MEASURED, never fine: the sentence says
    # brAIn cannot tell, so "why didn't you warn me" has its answer.
    _, rooms = _rooms(snap)
    for hit in set_aside:
        eid, unit = hit["entity_id"], hit["unit"]
        area = house.area_of(eid)
        room = f"the {area}" if area else "this room"
        others = _other_thermometers(house, rooms, eid)
        house.gave_up("climate.freeze", [{"entity_id": eid}], (
            f"it reads {numfmt.temperature(hit['indoor'], unit)} and is falling, but you "
            "said this sensor is broken, so brAIn did not warn about "
            "freezing from it — "
            + (f"the other thermometers in {room} are still read"
               if others else
               f"nothing else measures {room}, so whether it is cold "
               "there is not measured")), kind="explained")
    if not hits or len(hits) > MAX_FREEZE:
        return []
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
                f"{house.name(eid)} reads {numfmt.temperature(hit['indoor'], unit)} and is "
                f"falling, and it is {numfmt.temperature(hit['outside'], unit)} outside. At "
                f"the rate this room loses heat it reaches "
                f"{numfmt.temperature(hit['floor'], unit)} in {when} if nothing heats it — "
                "which is where water in an outside wall starts to be at "
                "risk, well before the room's own thermometer reads "
                "freezing."),
            "fix": (
                "Check the heating is actually reaching this room, and "
                "that nothing is open."),
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
    rooms = _room_air(house, rooms, "climate.window")
    unheated = said_unconditioned(house)
    hits = []
    for eid, entry in sorted(rooms.items()):
        if eid in claimed or not entry.get("k"):
            continue
        fall = thermal.recent_fall(recent.get(eid) or [], now)
        if fall is None or fall["age_min"] > WINDOW_MAX_AGE_MIN:
            continue
        if fall["from"] - outside < min_delta:
            continue
        # A room cooling toward outdoors approaches the outdoor reading and
        # cannot pass it — that is the law the whole model is. So a span
        # that ENDS below the reference disproves its own premise: either
        # this is not a room (it is outdoors, or refrigerated, or being
        # cooled on purpose) or the reference is wrong, and in both cases
        # `expected_fall` was computed from something that did not happen.
        # It costs one comparison and it is the guard that would have
        # caught an irrigation manifold reported as a room with a window
        # open, measured against a dew point.
        if fall["to"] <= outside:
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
        if _left_unheated(house, eid, unheated, "climate.window"):
            continue
        if not house.should_report(eid, "climate.window"):
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
                f"{house.name(eid)} fell from {numfmt.temperature(fall['from'], unit)} to "
                f"{numfmt.temperature(fall['to'], unit)} over the last "
                f"{numfmt.span(fall['span_min'] * 60)} — about "
                f"{numfmt.temperature(fall['rate'], unit, delta=True)} an hour, where this room's own "
                f"measured insulation allows about {numfmt.temperature(expected, unit, delta=True)} an "
                f"hour at {numfmt.temperature(outside, unit)} outside. Heat is leaving by "
                "some route the walls do not have."),
            "fix": (
                "Shut whatever is open: a window, a door to outside, a roof "
                "light, or a vent."),
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# climate.frost_ahead — a near-freezing night, and what holds water outside
# ---------------------------------------------------------------------------
#
# `climate.freeze` watches a room already falling and is a safety check no
# answer may quiet. This one reads the FORECAST (`snap["forecast"]`, the
# occasions read's hourly temperatures) and names what in this house holds
# water where the heating does not reach: irrigation and outdoor taps, a
# pool, a space the household said nothing heats (or a garage, crawl space
# or shed with a thermometer and no heating). One row per cold night,
# naming them all, so a house with six valves is told once; the night's
# date is in the text, so it is not filed again each pass and the next cold
# night is a new row. Kept apart from `climate.freeze` because the owner
# may quiet this one — a thing they stopped watching or explained is left
# out (`House.should_report`, `owner_explained` on this check).
FROST_CHECK = "climate.frost_ahead"
# Within this of freezing is "near freezing": a forecast low is a regional
# figure and a hose bib against a north wall reads colder than it.
FROST_WARN_C = 2.0
# How far ahead: tonight, from any pass made during the day.
FROST_AHEAD_H = 24
# Integrations that run irrigation or a pool, read off the registry's
# platform: what the device IS, where a name is only what it is called.
IRRIGATION_PLATFORMS = frozenset({
    "rachio", "hydrawise", "rainbird", "opensprinkler", "bhyve",
    "orbit_bhyve", "linktap", "gardena_bluetooth", "melnor", "rain_bird",
    "hunter_hydrawise", "b_hyve", "netro_watering", "rainmachine"})
POOL_PLATFORMS = frozenset({
    "screenlogic", "omnilogic", "iaqualink", "intellicenter", "pentair",
    "poolsync", "aqualink", "fluidra"})
_IRRIGATION_WORDS = re.compile(
    r"\b(irrigation|sprinklers?|drip|hose ?bibs?|spigots?|garden taps?|"
    r"outdoor (?:taps?|faucets?|water)|outside (?:taps?|faucets?)|"
    r"yard hydrants?)\b", re.I)
_POOL_WORDS = re.compile(r"\b(pool|spa|hot ?tub|jacuzzi)\b", re.I)
_COLD_SPACE_WORDS = re.compile(
    r"\b(garage|crawl ?space|crawlspace|shed|barn|pump ?house|well ?house|"
    r"outbuilding|workshop|greenhouse)\b", re.I)
FROST_KINDS = ("irrigation", "pool", "space")
MAX_FROST_NAMES = 8
# How many of them the sentence names before "and N more". The card shows
# every one under its count line (`items`, Show all), and a sentence naming
# eight was cut mid-name by the card's three-line clamp (#1190).
FROST_SENTENCE_NAMES = 3


def _frost_night(forecast: dict, now: float) -> dict | None:
    """The coldest hour in the next `FROST_AHEAD_H`, when it is within
    `FROST_WARN_C` of freezing: ``{"temp", "unit", "hm", "date", "night"}``
    where ``night`` is the date of the evening it belongs to (an hour
    before noon is the night before's)."""
    import datetime as _dt  # noqa: PLC0415

    unit = str((forecast or {}).get("unit") or "°C")
    fahrenheit = unit == "°F"
    rows = [r for r in (forecast or {}).get("hourly") or ()
            if isinstance(r, dict) and num(r.get("temp")) is not None
            and now - 3600 <= float(r.get("t") or 0) <= now + FROST_AHEAD_H * 3600]
    if not rows:
        return None
    low = min(rows, key=lambda r: (float(r["temp"]), float(r["t"])))
    celsius = (float(low["temp"]) - 32.0) * 5.0 / 9.0 if fahrenheit \
        else float(low["temp"])
    if celsius > FROST_WARN_C:
        return None
    # The warning lasts until the last near-freezing hour after the low has
    # passed (#1265): past it, the night it was about is over.
    until = float(low["t"])
    for row in sorted(rows, key=lambda r: float(r["t"])):
        t = float(row["t"])
        if t <= until:
            continue
        temp = float(row["temp"])
        if ((temp - 32.0) * 5.0 / 9.0 if fahrenheit else temp) > FROST_WARN_C:
            break
        until = t
    night = str(low.get("date") or "")
    try:
        if int(low.get("hour", 12)) < 12:
            night = (_dt.date.fromisoformat(night)
                     - _dt.timedelta(days=1)).isoformat()
        label = _dt.date.fromisoformat(night)
        night_words = f"{label:%a} {label.day} {label:%b}"
        day = _dt.date.fromisoformat(str(low.get("date") or ""))
        day_words = f"on {day:%a} {day.day} {day:%b}"
    except (TypeError, ValueError):
        night_words, day_words = night, ""
    return {"temp": float(low["temp"]), "unit": unit,
            "until": int(until + 3600), "t": float(low["t"]),
            "hm": str(low.get("hm") or ""), "date": str(low.get("date") or ""),
            "night": night, "night_words": night_words,
            "day_words": day_words}


def _frost_kind(house: House, eid: str, conditioned: set[str],
                said_cold: dict) -> str:
    """Which of `FROST_KINDS` this entity is at risk as, or ""."""
    reg = house.registry.get(eid) or {}
    platform = str(reg.get("platform") or "")
    domain = domain_of(eid)
    device = house.device_of(eid) or {}
    names = " ".join([house.name(eid), eid.replace("_", " "),
                      str(device.get("name_by_user") or ""),
                      str(device.get("name") or "")])
    area = house.area_of(eid)
    if domain in ("switch", "valve") and (
            platform in IRRIGATION_PLATFORMS or _IRRIGATION_WORDS.search(names)):
        return "irrigation"
    if platform in POOL_PLATFORMS or (
            domain in ("switch", "sensor", "water_heater", "climate", "pump")
            and (_POOL_WORDS.search(names) or _POOL_WORDS.search(area))):
        return "pool"
    if domain == "sensor":
        attrs = (house.states.get(eid) or {}).get("attributes") or {}
        if str(attrs.get("device_class") or reg.get("device_class")
               or reg.get("original_device_class") or "") != "temperature":
            return ""
        area_id = house.area_id_of(eid)
        if not ((eid in said_cold["entities"]
                 or (area_id and area_id in said_cold["areas"]))
                or (area_id and area_id not in conditioned
                    and _COLD_SPACE_WORDS.search(area))):
            return ""
        # A thermometer is the evidence a space is there and cold. One the
        # owner said does not read the room's air, one the heat model found
        # is a machine's, and one it found something keeps warm at night
        # are not that evidence (#1131): a room whose only thermometers are
        # those is not named. One the model merely lacked nights for still
        # counts — a cold garage is exactly what this warns about.
        kind, said = house.room_air_verdict(eid)
        if kind:
            house.gave_up(FROST_CHECK, [{"entity_id": eid}],
                          f"{said}, so it is not evidence of a space that "
                          "gets cold", kind="explained")
            return ""
        return "space"
    return ""


# A space whose own measured heat loss keeps it at least this far above
# freezing through the forecast low needs nothing done (#1312).
FROST_SAFE_MARGIN_C = 2.0
# And the outside is held this much colder than the forecast low for it:
# a forecast low is routinely a few degrees off, and in doubt the space
# is listed.
FROST_FORECAST_ERROR_C = 3.0


def _to_celsius(value: float, unit: str) -> float:
    return (value - 32.0) * 5.0 / 9.0 if unit == "°F" else value


def _space_holds(house: House, eid: str, night: dict, now: float) -> str:
    """Why this thermometer's space stays above freezing through the night
    without anything done, or "" (#1312).

    Measured, never assumed: the space's own heat-loss figure (the heat
    model's `k` for this thermometer) coasting from its live reading with
    the outside held `FROST_FORECAST_ERROR_C` under the forecast low the
    whole time, still `FROST_SAFE_MARGIN_C` above freezing at the last
    near-freezing hour of the night. No model, no live reading, or a unit nobody can convert
    is "" — the space stays named."""
    import thermal  # noqa: PLC0415

    entry = _rooms(house.snap)[1].get(eid)
    if not isinstance(entry, dict) or not entry.get("k"):
        return ""
    unit = str((house.snap.get("thermal") or {}).get("unit") or "")
    attrs = (house.states.get(eid) or {}).get("attributes") or {}
    if str(attrs.get("unit_of_measurement") or unit) != unit \
            or unit not in ("°C", "°F"):
        return ""
    reading = num((house.states.get(eid) or {}).get("state"))
    if reading is None:
        return ""
    low = _to_celsius(night["temp"], night["unit"]) - FROST_FORECAST_ERROR_C
    # Through the last near-freezing hour of the night, not only to the
    # low's hour: a long cold stretch keeps pulling the space down.
    hours = max(0.0, (night["until"] - 3600 - now) / 3600.0)
    ahead = thermal.coast(entry, _to_celsius(reading, unit), low, hours)
    if ahead is None or ahead < FROST_SAFE_MARGIN_C:
        return ""
    return f"{numfmt.temperature(reading, unit, whole=True)} now"


def frost_ahead(snap: dict, now: float) -> list[dict]:
    """A near-freezing night in the forecast, and what here holds water
    where the heating does not reach. One row a night."""
    night = _frost_night(snap.get("forecast") or {}, now)
    if night is None:
        return []
    house = House(snap)
    conditioned = conditioned_areas(house)
    # A room is named as a cold space on what the household STATED about
    # it, never on the reason they gave for waving off a report about it:
    # "it's an unheated porch" said to the heat-loss card means leave the
    # porch alone, and naming it on the next cold night undid that answer
    # (#1200). Every climate check that compares rooms reads both.
    said_cold = snap.get("unconditioned") or {"areas": [], "entities": []}
    if isinstance(said_cold.get("stated"), dict):
        said_cold = said_cold["stated"]
    said_cold = {"areas": set(said_cold.get("areas") or ()),
                 "entities": set(said_cold.get("entities") or ())}
    found: dict[str, list[str]] = {k: [] for k in FROST_KINDS}
    # What each name IS, as the keys this check asks by: a room's
    # `area:<id>`, a device's entities. A Wrong on the card writes its rule
    # under the row's `items` (`server._exception_rule`), and the names a
    # person reads are not anything `should_report` is ever asked about —
    # the porch answered Wrong one night was named again the next (#1200).
    keys: dict[str, list[str]] = {}
    seen: set[str] = set()
    safe: dict[str, tuple[str, str]] = {}
    for eid in sorted(set(house.states) | set(house.registry)):
        if not house.enabled(eid):
            continue
        kind = _frost_kind(house, eid, conditioned, said_cold)
        if not kind:
            continue
        if not house.should_report(eid, FROST_CHECK):
            continue
        said = house.owner_explained(eid, {FROST_CHECK})
        if said:
            house.gave_up(FROST_CHECK, [{"entity_id": eid}],
                          f"you explained it: {said['text']}", kind="explained")
            continue
        # A space is named by its room, a device by its device: six zones
        # of one controller are one thing to drain.
        area_id = house.area_id_of(eid)
        if kind == "space":
            what = house.area_of(eid) or house.label(eid)
            key = f"area:{area_id}" if area_id else eid
            # Safe only while EVERY thermometer of it says so.
            if what:
                holds = _space_holds(house, eid, night, now)
                if what.lower() not in safe:
                    safe[what.lower()] = (what, holds)
                elif not holds:
                    safe[what.lower()] = (what, "")
        else:
            device = house.device_of(eid)
            what = house.device_name(device) if device else house.label(eid)
            key = eid
        if not what:
            continue
        if what.lower() not in seen:
            seen.add(what.lower())
            found[kind].append(what)
        held = keys.setdefault(what.lower(), [])
        if key not in held:
            held.append(key)
    # What is already safe is said once, never listed as at risk (#1312).
    held = [(what, why) for what, why in safe.values() if why]
    for what, why in held:
        found["space"] = [n for n in found["space"] if n != what]
        house.gave_up(FROST_CHECK, [{"entity_id": k}
                                    for k in keys.get(what.lower()) or ()],
                      f"it reads {why}, and at the rate it loses heat it "
                      "stays above freezing through the forecast low",
                      kind="explained")
    names = [n for k in FROST_KINDS for n in found[k]]
    if not names:
        return []
    named = names[:MAX_FROST_NAMES]
    items = list(dict.fromkeys(k for n in named for k in keys[n.lower()]))
    temp, unit = night["temp"], night["unit"]
    low = numfmt.temperature(temp, unit, whole=True)
    # How far from freezing the low is, in the forecast's own degrees.
    freezing = 32.0 if unit == "°F" else 0.0
    margin = round(temp - freezing)
    below = margin <= 0
    margin_words = (
        "right at freezing" if margin == 0 else
        f"{numfmt.temperature(abs(margin), unit, delta=True, whole=True)} "
        f"{'below' if margin < 0 else 'above'} freezing")
    margin_words += (
        ", so water left in these will freeze" if below else
        ", so only water in the most exposed spots is at risk")
    nothing = ""
    if held:
        nothing = (" Nothing needed for "
                   + join_names([f"{what} ({why})" for what, why in held])
                   + (": at the rate each loses heat, each stays"
                      if len(held) > 1 else
                      ": at the rate it loses heat, it stays")
                   + " above freezing through the low.")
    steps = []
    if found["irrigation"]:
        steps.append("shut off and drain the outdoor taps and irrigation")
    if found["pool"]:
        steps.append("keep the pool pump running or drain its lines")
    if found["space"]:
        steps.append("keep the unheated spaces above freezing (a heater, or "
                     "leave a tap dripping)")
    fix = "; ".join(steps)
    return [{
        "text": f"{'Below' if below else 'Near'} freezing the night of "
                f"{night['night_words']}: protect what holds water outside",
        "detail": (f"The forecast low is {low} around {night['hm']} "
                   f"{night['day_words']}, {margin_words}. At risk here: "
                   + join_names(names[:MAX_FROST_NAMES],
                                limit=FROST_SENTENCE_NAMES) + "."
                   + nothing),
        "fix": fix[:1].upper() + fix[1:] + ".",
        "severity": "warning",
        "fixable": False,
        "entity_id": "",
        # The keys the rule is written under, and the names the card shows
        # for them under its count line (`findings_store.item_labels`).
        "items": items,
        "item_names": named,
        "evidence": [{"entity": "", "value": f"forecast low {low}",
                      "when": f"{night['date']} {night['hm']}"}],
        # Retired once the cold hours are over, even by a pass that could
        # not read a forecast (`findings_store.resolve_clear`).
        "valid_until": night["until"],
    }]


CHECKS = [
    {"id": "climate.underheated", "area": "devices",
     "title": "Asked for a temperature it never reaches",
     "needs": ("states", "registry", "thermal"), "run": underheated},
    {"id": "climate.heat_loss", "area": "devices",
     "title": "Loses heat faster than the rest of the house",
     "needs": ("states", "registry", "thermal"), "run": heat_loss},
    {"id": "climate.preheat", "area": "devices",
     "title": "Still warming when the house gets up",
     "needs": ("states", "registry", "thermal", "baselines"), "run": preheat},
    {"id": "climate.freeze", "area": "devices",
     "title": "On course to get cold enough to matter",
     "needs": ("states", "registry", "thermal"), "run": freeze},
    {"id": "climate.window", "area": "devices",
     "title": "Losing heat faster than it can",
     "needs": ("states", "registry", "thermal"), "run": window},
    {"id": FROST_CHECK, "area": "devices",
     "title": "Near-freezing night for outdoor water",
     "needs": ("states", "registry", "forecast"), "run": frost_ahead},
]

__all__ = ["CHECKS", "freezing_rooms", "underheated_rooms"]
