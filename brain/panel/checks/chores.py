"""The washing that finished and is still in the machine.

Everything else in this package reads a state and asks whether it is
wrong. This asks a question no state answers at all: a dishwasher that
finished an hour ago and a dishwasher that finished an hour ago and was
emptied draw exactly the same watts, sit in exactly the same `off`, and
are the same row in every registry. `panel/appliances.py` measures the
first half — when a cycle actually ended, from the machine's own history
rather than a wattage somebody typed — and this is the part that decides
whether that is worth saying.

**Only what a person has to empty.** The measurement is universal: any
power sensor with an appliance's bimodal shape gets a profile, and the
API and the panel can read every one of them. The *chore* is narrower,
and it is narrowed by NAME — the one guess here, made deliberately and
in the direction where being wrong is cheap. A washer, a dryer and a
dishwasher are the three machines that finish and then wait for
somebody; a television, a kettle and an oven finish and are done. Not
recognising a machine costs a missing chore. Recognising the wrong one
costs a notification telling somebody to go and empty their TV, and that
is the notification that gets the whole feature turned off.

**It waits, and the wait is not a threshold on a state.** A cycle that
ended four minutes ago is a person standing at the machine. `QUIET_MIN`
is how long the house gets to deal with it before this is a chore at
all — and it is on top of the appliance's own measured settle time, so a
long dry phase never reads as a finish.

**And it stops asking.** Past `STALE_HOURS` the washing from yesterday
morning is not a chore, it is a fact about the week; the row clears
itself the moment the machine runs again, because a second cycle is
somebody having dealt with the first. What it cannot see is the machine
being emptied — nothing in the power draw says so — which is exactly
what the To-do list and the notification buttons are for: the ending is
a person's, and there is one press for it.
"""
from __future__ import annotations

from ._util import House

# The three machines that finish and then wait for somebody. Matched
# against the entity's own name, lower-cased; see the module docstring
# for why this is a name and not a measurement.
WAITING_KINDS = {
    "washer": ("washing machine", "washer", "washing-machine"),
    "dryer": ("tumble dryer", "dryer", "tumble-dryer"),
    "dishwasher": ("dishwasher", "dish washer"),
}
# What to call it in the sentence, which is not the entity's name: a
# sensor called "Utility Plug Power" is a washing machine to the check
# and "Utility Plug Power" to nobody.
KIND_NAMES = {"washer": "The washing machine", "dryer": "The dryer",
              "dishwasher": "The dishwasher"}

# On top of the appliance's own measured settle time. Somebody standing
# at the machine as it beeps does not need telling.
QUIET_MIN = 20.0
# Past this it is not a chore any more. Being told at lunchtime about
# yesterday's washing is how a list stops being read.
STALE_HOURS = 14.0
# More than this at once means the measurement moved, not the house.
MAX_ROWS = 3


def kind_of(name: str) -> str:
    """Which of the three machines this name is, or "".

    Longest phrase first, so "washing machine" is not read as a dryer by
    a name that happens to contain both words.
    """
    text = str(name or "").lower()
    best, longest = "", 0
    for kind, words in WAITING_KINDS.items():
        for word in words:
            if word in text and len(word) > longest:
                best, longest = kind, len(word)
    return best


def waiting(snap: dict, now: float) -> list[dict]:
    """Appliances that finished a while ago and have not run since."""
    import appliances  # noqa: PLC0415

    store = snap.get("appliances") or {}
    shapes = store.get("entities") or {}
    recent = store.get("recent") or {}
    if not shapes:
        return []
    house = House(snap)

    hits = []
    for eid, shape in shapes.items():
        if not house.enabled(eid):
            continue
        kind = kind_of(shape.get("name") or house.name(eid) or eid)
        if not kind:
            continue
        reading = appliances.state_at(shape, recent.get(eid) or [], now)
        if reading.get("state") != appliances.FINISHED:
            continue
        finished = float(reading.get("finished_at") or 0)
        if not finished:
            continue
        ago_min = (now - finished) / 60.0
        if ago_min < QUIET_MIN or ago_min > STALE_HOURS * 60.0:
            continue
        hits.append((finished, kind, eid, shape))

    if not hits or len(hits) > MAX_ROWS:
        return []
    # Oldest first: the one that has been sitting longest is the one to
    # deal with.
    hits.sort()

    out = []
    for finished, kind, eid, shape in hits:
        ago = int((now - finished) / 60.0)
        when = (f"{ago} minutes ago" if ago < 90
                else f"{ago // 60} hours ago")
        out.append({
            # Stable across runs — the minutes change every pass and the
            # store dedupes on this text, so they live in `detail`.
            "text": f"{KIND_NAMES[kind]} has finished and is still full",
            "detail": (f"It stopped drawing power {when}, and has not run "
                       f"since. Measured from {house.name(eid)}: this "
                       f"machine draws about {shape.get('busy_w', 0):.0f}W "
                       f"running against {shape.get('idle_w', 0):.0f}W "
                       "idle, and goes quiet for up to "
                       f"{shape.get('settle_min', 0):.0f} minutes "
                       + ("mid-cycle." if shape.get("measured_settle")
                          else "mid-cycle (not yet measured here).")),
            "fix": ("Empty it, then tick it off — brAIn cannot see that "
                    "you have, because an empty machine and a full one "
                    "draw exactly the same power. It clears itself if the "
                    "machine runs again."),
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


CHECKS = [
    {"id": "chore.waiting",
     "title": "Finished and still full",
     "needs": ("states", "registry", "appliances"), "run": waiting},
]

__all__ = ["CHECKS"]
