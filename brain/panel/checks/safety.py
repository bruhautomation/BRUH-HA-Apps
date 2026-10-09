"""A smoke, gas, CO or leak detector that reads tripped NOW.

The safety lane (`server._note_safety`) files a card on a TRANSITION into
the tripped state, seen on the event bus. That is the right door for a
detector going off while somebody is home, and the wrong one for every
other case: a sensor that was already wet when the panel started, or that
tripped while the add-on was being updated, was never a transition anything
saw — so the only thing between it and a person was the Resident's first
look, and on a real house that look set a related row to "watch" saying
there was "no active leak" while the moisture sensor beside it had read
`on` for a week.

So this is the deterministic half of the same rule: on every checks pass,
any binary sensor of a hot safety class whose state is a tripped state is a
critical row. No window and no floor — a leak sensor that reads wet is the
one state in a house that is wrong by itself. The text is stable (it names
the sensor and what it detects; how long it has read so is in the detail),
so the store dedupes it pass after pass, and it clears itself when the
sensor reads dry, `clear_resolved`'s rule for a check that ran.

The classes and states are the lane's (`signals.HOT_SAFETY_CLASSES` /
`HOT_SAFETY_STATES`), spelled here because the checks import nothing of the
panel's, and a test holds the two equal. Only a class the registry or the
state declares counts: a model's reading that ADDS a safety class
(`world_model.added_safety`) deliberately does not reach a deterministic
lane, and this is one.
"""
from __future__ import annotations

from ._util import House, domain_of, evidence_for, parse_ts

TRIPPED_CLASSES = frozenset({"smoke", "gas", "carbon_monoxide", "moisture"})
TRIPPED_STATES = frozenset({"on", "detected", "wet", "unsafe"})

# What each class detects, in the words the card leads with. The lane's own
# labels (`server.SAFETY_LABELS`) are titles; these sit inside a sentence.
DETECTS = {"moisture": "a water leak", "smoke": "smoke", "gas": "gas",
           "carbon_monoxide": "carbon monoxide"}

FIX = ("Go and look. brAIn does not act on smoke, water or gas on its own. "
       "If the sensor is wrong — wet from cleaning, or faulty — dry or "
       "replace it, and this clears itself the next time it reads clear.")


def _class_of(house: House, eid: str, st: dict) -> str:
    attrs = st.get("attributes") or {}
    reg = house.registry.get(eid) or {}
    return str(attrs.get("device_class") or reg.get("device_class")
               or reg.get("original_device_class") or "")


def _since(value, now: float) -> str:
    ts = parse_ts(value)
    if ts is None:
        return ""
    hours = max(0.0, now - ts) / 3600
    if hours < 1:
        return " for under an hour"
    if hours < 48:
        return f" for about {int(round(hours))} hours"
    return f" for about {int(round(hours / 24))} days"


def tripped(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for eid in sorted(house.states):
        if domain_of(eid) != "binary_sensor" or not house.enabled(eid):
            continue
        st = house.states.get(eid) or {}
        state = str(st.get("state") or "").lower()
        if state not in TRIPPED_STATES:
            continue
        klass = _class_of(house, eid, st)
        if klass not in TRIPPED_CLASSES:
            continue
        if not house.should_report(eid, "safety.tripped"):
            continue
        name = house.label(eid)
        what = DETECTS.get(klass, "a safety alarm")
        out.append({
            "text": f"{name} is reporting {what}",
            "detail": (f"{name} has read {state}"
                       f"{_since(st.get('last_changed'), now)}. A tripped "
                       "detector is reported on every pass while it stays "
                       "tripped, whether or not anything saw it go off."
                       + house.placed(eid)),
            "fix": FIX,
            "severity": "critical",
            "fixable": False,
            "entity_id": eid,
            "evidence": evidence_for([eid], state),
        })
    return out


CHECKS = [
    {"id": "safety.tripped", "title": "Safety detectors reading tripped",
     "needs": ("states", "registry"), "run": tripped},
]
