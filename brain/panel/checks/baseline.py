"""Checks that need to know what is normal here.

Everything in the other check modules asks a question with a fixed
answer: an entity exists or it does not, a backup is a week old or it is
not. These ask a question whose answer is different in every house — is
this reading odd *for this house, at this hour* — and they can only do
that because `panel/baselines.py` measured it first.

The threshold is in **spreads of that entity's own history**, which is
what makes one number work across a freezer, a water meter and a boiler.
It is not a standard deviation: the spread is a median absolute
deviation, which for ordinary data runs about two thirds of one, so the
bar here is higher than the number looks.

The floors matter more here than anywhere else in the package, because
this is the check most able to fire on a healthy house: a reading is odd
only well outside the band, only where the baseline has real samples
behind it, and only where the entity is one whose oddness nothing else
already reports.
"""
from __future__ import annotations

import math
import re

import numfmt

from . import chores, devices
from ._util import (House, domain_of, join_names, num, parse_ts, state_words,
                    when)

# Six spreads. On ordinary data a MAD is about 0.67 of a standard
# deviation, so this is roughly four sigma — rare enough that a house
# with three hundred sensors is not handed a row a day.
UNUSUAL_SPREADS = 6.0
# Where the hour-of-week bucket had nothing and the answer came from the
# entity's whole history, the band is wider by construction (it spans
# every hour of the week), so the bar goes up with it.
UNUSUAL_SPREADS_OVERALL = 9.0
# A reading has to be outside its band by something a person would
# notice, not merely by arithmetic: a temperature 6 spreads out of a band
# 0.02 wide is 0.12 degrees. The number is in the reading's own unit, so
# one constant meant 0.5 W, 0.5 lx and 0.5 ppm as readily as half a
# degree — nothing at all on a meter that moves in hundreds. The table
# names the units whose "noticeable" is plainly different; anything else
# keeps the old half a unit, which is the cautious direction for a floor
# that only ever stands a row down.
MIN_ABSOLUTE_MOVE = 0.5
MIN_MOVE_BY_UNIT = {
    "°C": 0.5, "K": 0.5, "°F": 1.0,
    "%": 2.0,
    "W": 20.0, "kW": 0.02, "VA": 20.0, "A": 0.2, "mA": 200.0, "V": 3.0,
    "lx": 20.0,
    "ppm": 50.0, "ppb": 20.0, "µg/m³": 5.0,
    "hPa": 1.0, "mbar": 1.0, "Pa": 100.0, "kPa": 0.1, "inHg": 0.03,
    "psi": 0.2, "bar": 0.02,
    "dB": 3.0, "dBA": 3.0, "dBm": 5.0,
    "L/min": 0.5, "L/h": 10.0, "m³/h": 0.05, "gal/min": 0.2,
}


def min_move(unit: str | None, default: float = MIN_ABSOLUTE_MOVE) -> float:
    """The smallest move worth a row, in this reading's own unit.

    Shared with `forecast.decline`, whose floor had the same unitless
    half a unit for the same reason.
    """
    return MIN_MOVE_BY_UNIT.get(str(unit or "").strip(), default)
# More than this and the house is not unusual, the baseline is: a
# heating season starting, a meter replaced, a fortnight of samples
# describing a different life. Reporting fifty rows would be reporting
# the measurement rather than the house.
MAX_ROWS = 4

# Whose oddness something else already answers, better.
COVERED_BY_ANOTHER_CHECK = frozenset({"battery"})
# Entities that live in the settings pages. Their readings are real and
# nobody wants a finding about a signal strength that dipped.
BACKGROUND_CATEGORIES = frozenset({"diagnostic", "config"})
# The only state class for which "outside its usual range" means
# anything. See `eligible`.
MEASURED_CLASSES = frozenset({"measurement"})
# A reading this far into a drift is explained by the drift, and
# `forecast.decline` has the fix that matters on it.
DRIFT_SPREADS = 4.0

# --- readings that are not a measurement of the house -------------------
# `state_class: measurement` says the recorder keeps a mean, not that the
# number is something in the house moving. Both checks here spend a row
# cap, and past it they say nothing at all — so one print job, a weather
# integration's forecast and a runtime counter that resets at midnight
# were enough to stand the whole check down on a house with a real fault
# in it. Each exclusion is checkable evidence first (the integration, the
# unit, the device class), and a name only in the cheap direction (whole
# words: a missed unusual reading costs one card, a false one the list).
# A span is a configured or last-measured figure — a timer's length, how
# long the last run took, time at home today — never a quantity that is
# unusual for this hour of the week.
SPAN_CLASSES = frozenset({"duration", "timestamp", "date", "enum"})
SPAN_UNITS = frozenset({"ms", "s", "min", "h", "d", "w"})
# A print job's numbers are the job's, and so are a printer's heaters
# (unusual every time it prints).
PRINTER_PLATFORMS = devices.PRINTER_PLATFORMS
JOB_WORDS = frozenset({"progress", "layer", "layers", "remaining",
                       "elapsed", "eta", "job"})
# A setpoint is what somebody asked for, and it moves when they change it.
SETPOINT_WORDS = frozenset({"target", "setpoint", "setpoints"})
# A counter that resets every midnight is high at 23:00 and zero at 00:05
# by construction.
DAILY_WORDS = frozenset({"today", "yesterday", "daily"})
# A device's own electrical or radio figure — an element's resistance, a
# radio's received power — says how the device is, not how the house is,
# and its band moves with the device's duty rather than the hour of the week.
DEVICE_UNITS = frozenset({"Ω", "kΩ", "MΩ", "mΩ", "ohm", "ohms", "dBm"})
# A part of a machine: a heat pump's coil, an evaporator, the air in its
# ducts. Each swings with the machine's cycle, which is the machine working.
MACHINE_WORDS = frozenset({"coil", "evaporator", "condenser", "refrigerant",
                           "plenum", "duct", "ducts", "flue", "lineset"})
MACHINE_PHRASES = ("supply air", "return air", "discharge air",
                   "liquid line", "suction line", "air handler")


def _name_words(house: House, eid: str, st: dict) -> list[list[str]]:
    attrs = st.get("attributes") or {}
    reg = house.registry.get(eid) or {}
    return [[w for w in re.split(r"[^a-z0-9]+", str(name or "").lower()) if w]
            for name in (attrs.get("friendly_name"), reg.get("name"),
                         reg.get("original_name"), eid.split(".", 1)[-1])]


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
    "electricity_maps", "nordpool", "entsoe", "astroweather", "weatherbit",
    "visual_crossing", "meteoblue", "openuv", "sun", "moon", "season",
    # Relays of data about somewhere else entirely: space weather (solar
    # flux, the Kp index, X-ray flares), outdoor air quality, pollen and
    # aircraft overhead. Their numbers move with the sun, the wind and the
    # season, never with the hour of this house's week.
    "noaa_space_weather", "waqi", "airnow", "airvisual", "luftdaten",
    "iqvia", "opensky",
})
# A label somebody gave an entity that says the same thing: they filed it
# under the weather. Matched on the label id's whole words, since a label
# named "Weather" has the id `weather` and one named "Space weather" has
# `space_weather`.
OUTSIDE_LABEL_WORDS = frozenset({"weather", "forecast", "outdoor", "outside"})
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
    for label in reg.get("labels") or ():
        if set(re.split(r"[^a-z0-9]+", str(label).lower())) & OUTSIDE_LABEL_WORDS:
            return "labelled as weather or outdoors"
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


def not_a_house_reading(house: House, eid: str, st: dict) -> str:
    """Why this reading is not a measurement of the house, or "" when it is.

    Shared by `base.unusual` and `forecast.decline` through `eligible`,
    and asked BEFORE either check's row cap, which is the point: a row
    spent on a forecast is a row the cap counts.
    """
    attrs = st.get("attributes") or {}
    reg = house.registry.get(eid) or {}
    platform = str(reg.get("platform") or "")
    if platform in devices.SELF_PLATFORMS:
        return "brAIn's own sensor"
    # A machine that cycles is bimodal — near nothing, then hundreds of
    # watts for hours — and an hour-of-the-week mean lands between the two
    # where it never is: a dehumidifier running its usual morning 700 W
    # was "218,300 times its normal variation" against a usual 0.07 W. The
    # appliance store holds a measured idle/busy profile for exactly these
    # sensors and is the authority on them (`chore.waiting` reads it), so a
    # profiled sensor is not a band reading. Read off the snapshot the pass
    # already holds; a snapshot with no store profiles nothing.
    profiled = (house.snap.get("appliances") or {}).get("entities")
    if isinstance(profiled, dict) and eid in profiled:
        return "an appliance brAIn measures by its own on/off shape"
    # And the same machine with no profile yet — a washer the nightly cap
    # never read, one too new to have run three times — is still a machine
    # that cycles: a power reading named for a washer, dryer or dishwasher,
    # or one whose device carries a status saying it runs jobs. The
    # vocabulary is `chores`', so the two checks cannot disagree about which
    # machines those are.
    if chores.is_cycle_reading(attrs) and chores.cycling_machine(house, eid):
        return "a machine that runs in cycles"
    # A printer's heater is hot every time it prints and at room
    # temperature otherwise: an hour-of-the-week band is a judgement about
    # when somebody prints. `base.heater_idle` reads the printer's own
    # status instead, and files the one case that matters — hot while idle.
    if devices.printer_heater(house, eid):
        return "a printer's heater, judged by whether the printer is printing"
    if platform in PRINTER_PLATFORMS:
        return "a printer's job"
    # A computer's processor or drive follows its load, not the hour of
    # the house's week: 100 °C under a nightly backup is the machine
    # working. Narrower than `dev.implausible`'s hot gate on purpose — a
    # tank or a probe in a room is still a reading worth a band.
    if devices.computer_temperature(house, eid):
        return "a computer's own temperature, which follows its load"
    if str(attrs.get("device_class") or "") in SPAN_CLASSES:
        return "a span, not a quantity"
    if str(attrs.get("unit_of_measurement") or "").strip() in SPAN_UNITS:
        return "a span, not a quantity"
    if str(attrs.get("unit_of_measurement") or "").strip() in DEVICE_UNITS:
        return "a device's own electrical or radio reading"
    for words in _name_words(house, eid, st):
        found = set(words)
        said = " ".join(words)
        if found & MACHINE_WORDS or any(p in said for p in MACHINE_PHRASES):
            return "a part of a machine, which swings with its cycle"
        if found & SETPOINT_WORDS or "set point" in " ".join(words):
            return "a setpoint somebody chose"
        if found & DAILY_WORDS:
            return "a counter that resets daily"
        if found & JOB_WORDS and found & devices._PAIR_WORDS:  # noqa: SLF001
            return "a printer's job"
    unit = attrs.get("unit_of_measurement") or ""
    return outside_cause(house, eid, st, unit)


# Several sensors of one kind that all moved the same way at once are the
# environment moving — a season turning, a heating system switched on —
# and not one device. More than this many in a group is the weather.
SAME_GROUP_MAX = 2


def moved_together(hits: list, group_of, direction_of=None,
                   limit: int = SAME_GROUP_MAX) -> list:
    """The hits that moved with more than ``limit`` others of their group.

    ``group_of(hit)`` names the kind (a device class, a unit) and
    ``direction_of(hit)`` the way it moved; with no direction the group
    alone counts. One rule for the two checks that need it, so
    `base.unusual` and `forecast.decline` cannot disagree about what a
    season looks like.
    """
    def key(hit):
        return (group_of(hit), direction_of(hit) if direction_of else 0)
    counts: dict = {}
    for hit in hits:
        counts[key(hit)] = counts.get(key(hit), 0) + 1
    return [h for h in hits if counts[key(h)] > limit]


def eligible(house: House, eid: str, st: dict) -> bool:
    """Whether a reading from this entity is worth reporting on at all.

    Shared with `forecast.decline`, which reports the same kind of thing
    about the same kind of entity — the rule this package keeps returning
    to, and the reason `dev.unavailable` and `dev.zwave_dead` share a
    helper rather than each keeping a list of dead nodes.
    """
    if st.get("state") in ("unavailable", "unknown", None):
        return False
    if not house.enabled(eid):
        return False
    reg = house.registry.get(eid) or {}
    if reg.get("hidden_by"):
        return False
    if str(reg.get("entity_category") or "") in BACKGROUND_CATEGORIES:
        return False
    attrs = st.get("attributes") or {}
    if str(attrs.get("device_class") or "") in COVERED_BY_ANOTHER_CHECK:
        return False
    # A `total_increasing` meter is higher than it has ever been every
    # hour of its life; that is what the class means, so "far above its
    # usual" is a statement about arithmetic rather than about the house.
    # The band's own spread widens with the ramp and mostly hides this,
    # which is worse than it sounds: it means the check is quiet by
    # accident rather than on purpose, and a meter that resets is not.
    if str(attrs.get("state_class") or "") not in MEASURED_CLASSES:
        return False
    # A thermometer reading 99°C is IMPOSSIBLE before it is unusual, and
    # `dev.implausible` says so with the better fix on it. Two checks on
    # one sensor under two different fixes is how a list stops being
    # read — the same rule `dev.unavailable` follows for a dead Z-Wave
    # node, and they share the question so they cannot disagree about it.
    if devices.out_of_range(st, eid, house.world, house):
        return False
    if domain_of(eid) != "sensor":
        return False
    return not not_a_house_reading(house, eid, st)


# --- a room's own dehumidifier ------------------------------------------
# Humidity far below its band right after the room's dehumidifier ran is
# the machine doing what it is for. Decided from the live states the pass
# already holds: a `humidifier` whose device class says dehumidifier, or —
# the fallback, a whole-word name gate in the cheap direction (a missed
# dry room costs one card, a false one the list) — anything whose own
# name or device's name says dehumidifier, on or drawing power. "Recently"
# is the last change of an off one: humidity takes hours to come back.
DEHUMIDIFIER_WORDS = frozenset({"dehumidifier", "dehumidifiers",
                                "dehumidifer", "dehumidifying"})
DEHUMIDIFIER_RECENT_S = 6 * 3600
# A plug resting at standby is not a machine running.
DEHUMIDIFIER_RUNNING_W = 20.0
DEHUMIDIFIER_SWITCHED = frozenset({"switch", "input_boolean", "fan",
                                   "humidifier", "climate", "binary_sensor"})


def _says_dehumidifier(house: House, eid: str) -> bool:
    st = house.states.get(eid) or {}
    dev = house.device_of(eid) or {}
    names = (house.name(eid), eid, dev.get("name"), dev.get("name_by_user"),
             (house.registry.get(eid) or {}).get("original_name"))
    words = set()
    for name in names:
        words |= set(w for w in re.split(r"[^a-z0-9]+", str(name or "").lower())
                     if w)
    if words & DEHUMIDIFIER_WORDS:
        return True
    attrs = st.get("attributes") or {}
    return (domain_of(eid) == "humidifier"
            and str(attrs.get("device_class") or "") == "dehumidifier")


def _dehumidifier_running(house: House, eid: str, now: float) -> bool:
    st = house.states.get(eid) or {}
    state = str(st.get("state") or "")
    dom = domain_of(eid)
    if dom == "sensor":
        attrs = st.get("attributes") or {}
        if str(attrs.get("device_class") or "") != "power":
            return False
        try:
            watts = float(state)
        except (TypeError, ValueError):
            watts = 0.0
        unit = str(attrs.get("unit_of_measurement") or "W")
        if unit == "kW":
            watts *= 1000.0
        if watts >= DEHUMIDIFIER_RUNNING_W:
            return True
        return _ran_recently(house, eid, now)
    if dom not in DEHUMIDIFIER_SWITCHED:
        return False
    if state in ("on", "dry", "auto", "heat_cool", "cool"):
        return True
    if state != "off":
        return False
    changed = parse_ts(st.get("last_changed"))
    return changed is not None and 0 <= now - changed <= DEHUMIDIFIER_RECENT_S


def _ran_recently(house: House, eid: str, now: float) -> bool:
    """Whether the appliance store's own shape for this power sensor says
    it ran within `DEHUMIDIFIER_RECENT_S` — the five-minute readings the
    checks pass already fetched for `chore.waiting`, never a new read."""
    store = house.snap.get("appliances") or {}
    shape = (store.get("entities") or {}).get(eid)
    points = (store.get("recent") or {}).get(eid)
    if not shape or not points:
        return False
    try:
        import appliances  # noqa: PLC0415 — the package stays importable without it
        found = appliances.state_at(shape, points, now)
    except Exception:  # noqa: BLE001 — a stand-down, never a reason to fail
        return False
    if found.get("state") == appliances.RUNNING:
        return True
    ended = float(found.get("finished_at") or 0.0)
    return bool(ended) and 0 <= now - ended <= DEHUMIDIFIER_RECENT_S


def dehumidified(house: House, eid: str, now: float) -> str:
    """The name of a dehumidifier in `eid`'s room that is running or ran
    within `DEHUMIDIFIER_RECENT_S`, or "" — read off the live states and
    registries the pass already has, never a fetch."""
    area = house.area_id_of(eid)
    if not area:
        return ""
    for other in sorted(house.states):
        if other == eid or house.area_id_of(other) != area:
            continue
        if not house.enabled(other):
            continue
        if _says_dehumidifier(house, other) and _dehumidifier_running(
                house, other, now):
            return house.name(other)
    return ""


# What in a room can move a reading of each kind. A fix that says "look at
# what it is measuring" under every row is a sentence nobody can act on; one
# that names the dehumidifier in the same room is a place to look. Domains
# that act on the quantity count whatever they are called; a switch or a
# sensor counts only when its name says it is one of those machines (a
# smart plug carries no class for what is plugged into it).
RELATED_ACTORS = {
    "humidity": ({"humidifier", "fan", "climate"},
                 {"dehumidifier", "humidifier", "extractor", "ventilation",
                  "fan", "dryer"}),
    "temperature": ({"climate", "water_heater", "fan"},
                    {"heater", "radiator", "heating", "boiler", "fan",
                     "aircon", "ac"}),
    "carbon_dioxide": ({"fan", "climate"},
                       {"fan", "extractor", "ventilation", "purifier"}),
    "volatile_organic_compounds": ({"fan"},
                                   {"fan", "extractor", "purifier"}),
    "pm25": ({"fan"}, {"fan", "extractor", "purifier"}),
    "pm10": ({"fan"}, {"fan", "extractor", "purifier"}),
    "illuminance": ({"light", "cover"}, set()),
}
NAMED_ACTOR_DOMAINS = frozenset({"switch", "sensor", "binary_sensor",
                                 "input_boolean", "fan", "humidifier",
                                 "climate"})
RELATED_MAX = 2


# A sensor named for one of those machines is a READING of the machine,
# not the machine: a "Dehumidifier power" sensor says when it ran, and is
# named as that — never told it was "running or off" itself. Only these
# classes say anything about when a machine ran; a "Fan temperature"
# sensor says nothing about the fan.
MACHINE_READING_CLASSES = frozenset({"power", "energy", "current", "running",
                                     "power_factor", ""})


def related_nearby(house: House, eid: str, st: dict
                   ) -> tuple[list, list, list]:
    """(machines that can move this reading, sensors measuring the same,
    readings that say when one of those machines ran) in the same area as
    `eid`, by friendly name, stable order.

    Read off the registries the pass already has, so the fix names what is
    there rather than guessing; an entity with no area has no neighbours.
    """
    area = house.area_id_of(eid)
    if not area:
        return [], [], []
    attrs = st.get("attributes") or {}
    klass = str(attrs.get("device_class") or "")
    domains, words = RELATED_ACTORS.get(klass, (set(), set()))
    own_device = (house.registry.get(eid) or {}).get("device_id")
    actors, peers, traces = [], [], []
    for other in sorted(house.states):
        if other == eid or house.area_id_of(other) != area:
            continue
        if not house.enabled(other):
            continue
        other_st = house.states.get(other) or {}
        other_attrs = other_st.get("attributes") or {}
        dom = domain_of(other)
        name = house.name(other)
        if dom in domains:
            actors.append(name)
            continue
        if dom in NAMED_ACTOR_DOMAINS and words:
            found = set(re.split(r"[^a-z0-9]+", f"{name} {other}".lower()))
            if found & words:
                if dom in ("sensor", "binary_sensor"):
                    if (str(other_attrs.get("device_class") or "")
                            in MACHINE_READING_CLASSES
                            and other_attrs.get("device_class") != klass):
                        traces.append(name)
                    continue
                actors.append(name)
                continue
        if (dom == "sensor" and klass
                and other_attrs.get("device_class") == klass
                and (house.registry.get(other) or {}).get("device_id")
                != own_device):
            peers.append(name)
    return (list(dict.fromkeys(actors))[:RELATED_MAX],
            list(dict.fromkeys(peers))[:RELATED_MAX],
            list(dict.fromkeys(traces))[:RELATED_MAX])


# One action. The card already carries Ignore, and a fix that also told
# somebody to press it was two errands in one sentence. No stock list of
# causes: brAIn does not know this house had a guest, so it does not say so.
GENERIC_FIX = ("Look at what it is measuring for a change brAIn cannot see, "
               "such as something added, moved or used differently near "
               "it.")


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def outdoor_reading(house: House, klass: str) -> str:
    """What the snapshot already says it is outside, for a reading of the
    room's air, or "". Pure over the snapshot: the thermal model's outdoor
    reference for a temperature, and a weather entity's own attribute for
    a temperature or a humidity. Nothing is fetched."""
    if klass == "temperature":
        ref = str((house.snap.get("thermal") or {}).get("outdoor") or "")
        st = house.states.get(ref) or {}
        value = num(st.get("state"))
        if ref and value is not None:
            unit = str((st.get("attributes") or {}).get(
                "unit_of_measurement") or "")
            return f"{house.name(ref)} reads {_fmt(value)}{unit}"
    key = {"temperature": "temperature", "humidity": "humidity"}.get(klass)
    if not key:
        return ""
    for weid in sorted(house.states):
        if not weid.startswith("weather."):
            continue
        wattrs = (house.states.get(weid) or {}).get("attributes") or {}
        value = num(wattrs.get(key))
        if value is None:
            continue
        unit = ("%" if key == "humidity"
                else str(wattrs.get("temperature_unit") or ""))
        return (f"the weather for {house.name(weid)} has it at "
                f"{_fmt(value)}{unit} outside")
    return ""


def unusual_fix(house: House, eid: str, st: dict) -> str:
    """The fix for one unusual reading, naming what is nearby when there is.

    A reading is measured, never run: the machines in the room that drive
    it are named as what to look at, a sensor that says when one of them
    ran is named as that, and the outdoor reading is offered beside them
    when the snapshot has one.
    """
    actors, peers, traces = related_nearby(house, eid, st)
    room = house.area_of(eid)
    where = f" in the {room}" if room else ""
    klass = str((st.get("attributes") or {}).get("device_class") or "")
    outside = outdoor_reading(house, klass)
    outside_said = f" Compare it with outside: {outside}." if outside else ""
    if actors:
        one = len(actors) == 1
        said = (f"Look at what drives it{where}: {join_names(actors)}. A "
                f"change in when {'it' if one else 'they'} ran or how "
                f"{'it was' if one else 'they were'} set is the likeliest "
                "reason.")
        if traces:
            said += (f" {join_names(traces)} "
                     f"{'shows' if len(traces) == 1 else 'show'} when it ran.")
        return f"{said}{outside_said}"
    if peers:
        return (f"Compare it with {join_names(peers)}{where}: if that moved "
                "too, something in the room changed; if not, the sensor "
                f"itself may be at fault.{outside_said}")
    if outside:
        return f"{GENERIC_FIX}{outside_said}"
    return GENERIC_FIX


# How wide "usually" is, in spreads either side of the middle. A MAD is
# about two thirds of a standard deviation, so two of them is the band
# most ordinary readings sit in.
USUAL_BAND_SPREADS = 2.0


def usual_range(found: dict, unit: str) -> str:
    """What a reading normally is, in its own units — never as a ratio.

    The detail used to say "That is N times its normal variation", and a
    near-flat sensor has a variation close to nothing, so the house's own
    photographs printed "1,109,306 times its normal variation": a number
    with a denominator nobody can see, and no idea of what is normal. A
    range in the reading's own units says it, and a band so narrow it
    rounds to one number is said as that number."""
    median = float(found.get("median") or 0.0)
    spread = abs(float(found.get("spread") or 0.0)) * USUAL_BAND_SPREADS
    low, high = median - spread, median + spread
    # A reading that is never negative is never usually negative: a plug
    # resting on 0 W "usually reads between −0.4 W and 0.4 W" is noise.
    if median >= 0 and low < 0:
        low = 0.0
    lo_text = numfmt.quantity(low, unit)
    hi_text = numfmt.quantity(high, unit)
    # A band narrower than the smallest move this check would ever report
    # is a reading that holds one value: "between 0% and 0.000099%" is the
    # ratio's problem said in a different shape.
    if lo_text == hi_text or high - low < min_move(unit):
        return f"about {numfmt.quantity(median, unit)}"
    return f"between {lo_text} and {hi_text}"


def recent_level(baseline: dict, found: dict, unit: str | None) -> str:
    """Why a reading outside its band is in line with its own last week.

    The band is this hour of the week over four weeks, so at a season
    turn it is mostly the old season — a room at 70 °F was reported
    against a usual 88–105 °F after ten days at 68–74. The nightly build
    stores how far the last week sat from those same hourly medians
    (`baselines.recent_shift`); a reading within the check's own bar of
    that shifted middle, measured in the larger of the band's and the
    week's spread, is the house's new level rather than a fault. Empty
    when there is no figure (an older store), the figure cannot be read,
    or the reading is outside both — which is still reported.
    """
    recent = baseline.get("recent")
    if not isinstance(recent, dict):
        return ""
    try:
        offset = float(recent.get("offset"))
        spread = float(recent.get("spread") or 0.0)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(offset) or not math.isfinite(spread):
        return ""
    value = float(found["value"])
    centre = float(found["median"])
    # A week that sat where the band sits explains nothing the band does not.
    if abs(offset) < min_move(unit):
        return ""
    shifted = centre + offset
    width = max(abs(spread), float(found.get("spread") or 0.0))
    bar = (UNUSUAL_SPREADS if found.get("source") == "hour"
           else UNUSUAL_SPREADS_OVERALL)
    off = abs(value - shifted)
    if off >= min_move(unit) and (width <= 0 or off / width >= bar):
        return ""
    days = recent.get("days")
    days = (f"{round(days)}" if isinstance(days, (int, float))
            and not isinstance(days, bool) and math.isfinite(days) and days >= 1
            else "few")
    return (f"{numfmt.quantity(value, unit or '')} is outside the usual range "
            "for this hour of the week, but in line with where the last "
            f"{days} days have been at this hour — the "
            "season or the weather moving the range, not the device")


def unusual(snap: dict, now: float) -> list[dict]:
    """Readings well outside what this house normally does at this hour."""
    import baselines  # noqa: PLC0415 — the package stays importable without it

    store = snap.get("baselines") or {}
    entities = store.get("entities") or {}
    if not entities:
        return []
    tz, _name = baselines.house_timezone()
    bucket = baselines.hour_of_week(now, tz)

    house = House(snap)
    hits = []
    for eid, baseline in entities.items():
        st = house.states.get(eid)
        if not st:
            continue
        # Reading a value no sensor of its kind can read is
        # `dev.implausible`'s, which files it as faulty; said on the trail
        # as that, so "why was this not unusual" has the true answer.
        if devices.out_of_range(st, eid, house.world, house):
            house.gave_up("base.unusual", [{"entity_id": eid}],
                          "it is reading a value no sensor of its kind can "
                          "read, so brAIn's impossible-readings check "
                          "reports it as a faulty sensor", kind="claimed")
            continue
        if not eligible(house, eid, st):
            continue
        if not house.should_report(eid, "base.unusual"):
            continue
        # A reading far from normal on a sensor that has been walking one
        # way for a month is the walk, and `forecast.decline` says so with
        # the fix that matters ("before it reaches a number that does").
        # Reporting both is the same sensor under two fixes, which is how
        # a list stops being read — and they share `baselines.trend`, so
        # they cannot disagree about whether it is drifting.
        # A sensor that read an impossible value in the last few nights is
        # `dev.implausible`'s, which files it once as faulty; its band was
        # built without those nights, but the morning after is the fault
        # still, not something added near it (#337).
        attrs = st.get("attributes") or {}
        if devices.recently_impossible(
                baseline, now,
                devices.bounds_for(attrs, eid, house.world, house)):
            house.gave_up("base.unusual", [{"entity_id": eid}],
                          "it read values no sensor of its kind can read in "
                          "the last few days, so brAIn's impossible-readings "
                          "check reports it as a faulty sensor",
                          kind="claimed")
            continue
        drift = baseline.get("trend") or {}
        if drift.get("consistent") and abs(
                drift.get("spreads") or 0.0) >= DRIFT_SPREADS:
            continue
        try:
            value = float(st.get("state"))
        except (TypeError, ValueError):
            continue
        found = baselines.deviation(value, baseline, bucket)
        if not found:
            continue
        bar = (UNUSUAL_SPREADS if found["source"] == "hour"
               else UNUSUAL_SPREADS_OVERALL)
        if abs(found["sigmas"]) < bar:
            continue
        measured_in = baseline.get("unit") or (
            st.get("attributes") or {}).get("unit_of_measurement")
        if abs(value - found["median"]) < min_move(measured_in):
            continue
        # Dry air beside the room's own dehumidifier is the machine
        # working. Below the band only: damp air beside a running one is
        # still worth a card.
        if (str(attrs.get("device_class") or "") == "humidity"
                and value < found["median"]):
            machine = dehumidified(house, eid, now)
            if machine:
                house.gave_up("base.unusual", [{"entity_id": eid}],
                              f"humidity below its usual range beside "
                              f"{machine}, which was running — that is the "
                              "dehumidifier doing its job", kind="explained")
                continue
        # A band that is mostly last month's weather: the reading sits
        # where the last week has been sitting against this same hour.
        shift = recent_level(baseline, found, measured_in)
        if shift:
            house.gave_up("base.unusual", [{"entity_id": eid}], shift,
                          kind="drift")
            continue
        hits.append((abs(found["sigmas"]), eid, found, baseline))

    # When the seasons change, or the weather dries the house, a lot of
    # sensors are far outside their hour-of-the-week usual at once — 23,
    # 17 and 17 rows against a limit of 4, and three rooms' humidity
    # falling in the same pass under it. Sensors of one kind that moved
    # the SAME way together are the season (`forecast.decline`'s rule,
    # shared, so three or more), whatever the total, and what is left is
    # reported if it fits.
    def kind(h):
        attrs = (house.states.get(h[1]) or {}).get("attributes") or {}
        return str(attrs.get("device_class") or h[3].get("unit")
                   or attrs.get("unit_of_measurement") or "")

    seasonal = moved_together(
        hits, kind, lambda h: 1 if h[2]["value"] >= h[2]["median"] else -1)
    if seasonal:
        house.gave_up("base.unusual", [{"entity_id": h[1]} for h in seasonal],
                      "several sensors of the same kind moved the same "
                      "way at once — that is the season or the weather "
                      "moving, not one device", kind="drift")
        hits = [h for h in hits if h not in seasonal]
    if len(hits) > MAX_ROWS:
        # Too many is the measurement being wrong, not the house. Said
        # nothing rather than said fifty times — and the trail says so.
        house.gave_up("base.unusual", [{"entity_id": h[1]} for h in hits],
                      f"{len(hits)} readings were far outside their usual "
                      f"range at once — past {MAX_ROWS} that is the baseline "
                      "no longer describing the house, not the house")
        return []
    if not hits:
        return []
    hits.sort(reverse=True)

    out = []
    for _rank, eid, found, baseline in hits:
        unit = baseline.get("unit") or ""
        # `n` is a different count on each path: one reading per week in
        # an hour-of-the-week bucket, and every hourly reading in the
        # month on the whole-history fallback — where "from 650 weeks of
        # readings" is what the one sentence used to say.
        if found["source"] == "overall":
            against = (f"across all its readings (from {found['n']} hourly "
                       "readings over its whole history — this house has "
                       "not been measured at this hour of the week yet)")
        else:
            weeks = found["n"]
            against = (f"for this hour of the week (from {weeks} "
                       f"{'week' if weeks == 1 else 'weeks'} of readings)")
        out.append({
            "text": f"{house.name(eid)} is reading far outside its usual range",
            "detail": (
                f"{numfmt.quantity(found['value'], unit)} now. It usually "
                f"reads {usual_range(found, unit)} {against}."
                + house.placed(eid)),
            "fix": unusual_fix(house, eid, house.states.get(eid) or {}),
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# --- a printer's heater, by whether the printer is printing -------------
# A nozzle at 220 °C during a print and at room temperature an hour after
# it is a printer working, and an hour-of-the-week band can only say when
# somebody usually prints. What a homeowner wants to hear is the other
# case — a heater still hot with nothing printing — and the printer's own
# status says which case it is. A check of its own, rather than a branch of
# `base.unusual`, so an answer given about the band ("normal while it
# prints") is not read as an answer about this, and it is in
# `corrections.NEVER_CHECKS` so no wide rule (the whole sensor, its room)
# stands it down either: only an answer about the idle case does.
# Long enough after a print for a nozzle and a bed to have cooled.
HEATER_COOL_S = 45 * 60
# Hot for a heater with nothing to heat: well above any room.
HEATER_IDLE_HOT = {"°C": 50.0, "°F": 122.0, "K": 323.15}


def heater_idle(snap: dict, now: float) -> list[dict]:
    """A printer's heater still hot well after the printer went idle."""
    house = House(snap)
    out = []
    for eid in sorted(house.states):
        st = house.states.get(eid) or {}
        if domain_of(eid) != "sensor" or not house.enabled(eid):
            continue
        if not devices.printer_heater(house, eid):
            continue
        attrs = st.get("attributes") or {}
        unit = str(attrs.get("unit_of_measurement") or "")
        bar = HEATER_IDLE_HOT.get(unit)
        value = num(st.get("state"))
        if bar is None or value is None or value < bar:
            continue
        state, since, status = chores.machine_status(house, eid)
        if state != "idle" or since is None or now - since < HEATER_COOL_S:
            continue
        if not house.should_report(eid, "base.heater_idle"):
            continue
        word = state_words((house.states.get(status) or {}).get("state") or "")
        out.append({
            "text": f"{house.name(eid)} is hot while the printer is idle",
            "detail": (f"{numfmt.quantity(value, unit)} now, and "
                       f"{house.name(status)} has said “{word}” since "
                       f"{when(since)}. A heater this hot with nothing "
                       "printing is not cooling down."
                       + house.placed(eid)),
            "fix": ("Turn the heater off from the printer or its app; a "
                    "print that ended early or a temperature set by hand "
                    "is the usual reason it stayed on."),
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


def stale_baselines(snap: dict, now: float) -> list[dict]:
    """The measurement itself has stopped being taken.

    Not a fact about the house — a fact about brAIn — and it belongs on
    the list because every check above it silently says nothing while it
    is true, which is indistinguishable from a house with nothing odd in
    it.
    """
    import baselines  # noqa: PLC0415

    store = snap.get("baselines") or {}
    if not store.get("entities"):
        return []
    if not baselines.is_stale(store, now):
        return []
    age = baselines.age_days(store, now)
    return [{
        "text": "brAIn's picture of what is normal here has stopped updating",
        "detail": (f"The baselines were last measured "
                   f"{int(age) if age is not None else '?'} days ago, over "
                   f"{store.get('days', baselines.HISTORY_DAYS)} days of "
                   f"{len(store['entities'])} sensors. Nothing is being "
                   "compared against them until they are rebuilt, so "
                   "'unusual' has quietly stopped meaning anything."),
        "fix": ("Restart the add-on. The rebuild runs nightly, so it has "
                "either failed every night or the panel is not running it."),
        "severity": "warning",
        "fixable": False,
        "entity_id": "",
    }]


CHECKS = [
    {"id": "base.unusual", "title": "Readings outside their usual range",
     "needs": ("states", "registry", "baselines"), "run": unusual},
    {"id": "base.stale", "title": "Baselines no longer being measured",
     "needs": ("baselines",), "run": stale_baselines},
    {"id": "base.heater_idle",
     "title": "Printer heaters hot while the printer is idle",
     "needs": ("states", "registry"), "run": heater_idle},
]

__all__ = ["CHECKS"]
