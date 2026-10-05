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

import numfmt

from . import devices
from ._util import House, domain_of

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
    if devices.out_of_range(st, eid, house.world):
        return False
    return domain_of(eid) == "sensor"


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
        if not st or not eligible(house, eid, st):
            continue
        if not house.should_report(eid, "base.unusual"):
            continue
        # A reading far from normal on a sensor that has been walking one
        # way for a month is the walk, and `forecast.decline` says so with
        # the fix that matters ("before it reaches a number that does").
        # Reporting both is the same sensor under two fixes, which is how
        # a list stops being read — and they share `baselines.trend`, so
        # they cannot disagree about whether it is drifting.
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
        hits.append((abs(found["sigmas"]), eid, found, baseline))

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
        where = house.where(eid)
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
                f"{numfmt.quantity(found['value'], unit)} now, against a "
                f"usual {numfmt.quantity(found['median'], unit)} {against}. "
                f"That is {numfmt.times(abs(found['sigmas']))} its normal "
                "variation."
                + (f" {where}." if where else "")),
            "fix": ("Look at what it is measuring. If this is normal for a "
                    "reason brAIn cannot see — a guest, a heatwave, a new "
                    "appliance — press Ignore and say why, and it will stop "
                    "reporting it."),
            "severity": "info",
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
]

__all__ = ["CHECKS"]
