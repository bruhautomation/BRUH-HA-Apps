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

import re

from ._util import CouldNotLook, House, domain_of, parse_ts

# The three machines that finish and then wait for somebody. Matched
# against the entity's own name, lower-cased; see the module docstring
# for why this is a name and not a measurement.
WAITING_KINDS = {
    "washer": ("washing machine", "washer", "washing-machine"),
    "dryer": ("tumble dryer", "dryer", "tumble-dryer"),
    "dishwasher": ("dishwasher", "dish washer"),
}
# A name that also says it is one of these is the thing that SERVES the
# machine, not the machine: a booster fan in a dryer's vent duct is named
# for the dryer and draws like a small motor that runs and stops, so the
# measurement profiles it and the phrase above calls it the dryer. Whole
# words only ("fancy" is no fan). The same cheap-direction guess as the
# rest of the gate: a missed chore costs nothing, a false one costs the
# list.
NOT_THE_MACHINE = frozenset({
    "fan", "fans", "blower", "blowers", "booster", "boosters", "vent",
    "vents", "exhaust", "duct", "ducts", "ducting"})
_WORD_RE = re.compile(r"[a-z]+")

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


def kind_of(name: str, world=None, entity_id: str = "") -> str:
    """Which of the three machines this name is, or "".

    Longest phrase first, so "washing machine" is not read as a dryer by
    a name that happens to contain both words.

    With `world` and the entity id, a confident `world_model` reading
    answers first — `Wasmachine` is a washer in any language — and the
    phrase match below is the fallback it always was.
    """
    if world and entity_id:
        import world_model  # noqa: PLC0415

        return world_model.chore_machine(
            world, entity_id, lambda: kind_of(name))
    text = str(name or "").lower()
    if NOT_THE_MACHINE & set(_WORD_RE.findall(text)):
        return ""
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
        kind = kind_of(shape.get("name") or house.name(eid) or eid,
                       house.world, eid)
        if not kind:
            continue
        if not house.should_report(eid, "chore.waiting"):
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

    if len(hits) > MAX_ROWS:
        house.gave_up("chore.waiting", [{"entity_id": h[2]} for h in hits],
                      f"{len(hits)} machines looked finished at once — past "
                      f"{MAX_ROWS} that is a measurement gone wrong, not a "
                      "house full of washing")
        return []
    if not hits:
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


# ---------------------------------------------------------------------------
# The same chore, read off the machine's own STATUS rather than its power
# ---------------------------------------------------------------------------
#
# A 3D printer whose integration publishes a print status — and a washer
# whose integration publishes an operation state — says when its job
# ended in words, and has no power sensor for the half above to profile.
# So `chore.job_done` reads the status, and reads it the only way that
# cannot be fooled by a status that has said `finish` since Tuesday: a
# TRANSITION, a running word followed by a finished word, read off the
# recorder. A finished word alone is not a job that just ended — a
# restart re-publishes it, and a printer left alone says it for days.
#
# Three closed vocabularies, matched on the state lower-cased with spaces
# and hyphens as underscores and an enum's dotted prefix dropped
# (`BSH.Common.EnumType.OperationState.Finished` is `finished`).
JOB_FINISHED = frozenset({"finish", "finished", "complete", "completed",
                          "done", "end", "ended"})
JOB_RUNNING = frozenset({"running", "run", "printing", "washing", "drying",
                         "rinsing", "spinning", "in_progress", "busy",
                         "active"})
# Words a running-then-finished history may pass THROUGH without either
# confirming or breaking it: a restart's unavailable, a pause mid-print.
# Anything else between the two (idle, failed, cancelled, offline) breaks
# the chain, and a broken chain says nothing.
JOB_PASS_THROUGH = frozenset({"unavailable", "unknown", "", "pause",
                              "paused"})
# The one kind only the status path has. A printer is matched on what its
# status entity is CALLED — the integration names it "Print status" — and
# not on "printer", because a label printer and an office printer are
# printers nobody takes a part off. Kept out of `WAITING_KINDS` on purpose:
# a plug called "3D printer" draws like anything else with a heater, and
# the power path's behaviour does not move.
PRINTER_WORDS = ("3d printer", "3d-printer", "3dprinter", "print status",
                 "print job")
JOB_TEXT = {
    "washer": "The washing machine has finished and is waiting to be emptied",
    "dryer": "The dryer has finished and is waiting to be emptied",
    "dishwasher": "The dishwasher has finished and is waiting to be emptied",
    "printer": "The 3D printer has finished and the print is waiting",
}
# How many status entities one checks pass asks the recorder about. One
# house has one printer and perhaps a washer; past this it is a house
# full of statuses that are not chores, and asking about them all is not
# what a checks pass is for.
JOB_FETCH_MAX = 6


def job_state(value) -> str:
    """A status word in the shape the vocabularies are written in."""
    text = str(value or "").strip().lower()
    text = text.rsplit(".", 1)[-1]
    return text.replace(" ", "_").replace("-", "_")


def _running(word: str) -> bool:
    return word in JOB_RUNNING or word.startswith("printing_")


def job_kind_of(name: str) -> str:
    """Which chore a status entity's name says it is, or "".

    The power path's own phrases first, then the printer's. Name only —
    `world_model`'s chore reading is asked of power sensors and has
    nothing to say about a status entity.
    """
    kind = kind_of(name)
    if kind:
        return kind
    text = str(name or "").lower()
    return "printer" if any(w in text for w in PRINTER_WORDS) else ""


def job_candidates(states: dict, now: float) -> list[str]:
    """Status entities worth asking the recorder about this pass.

    A `sensor` whose live state is a finished word, changed inside
    `STALE_HOURS`, on something whose name is a chore — newest first,
    then by id so two passes over the same house ask the same question,
    capped at `JOB_FETCH_MAX`. Pure, so the collector and the check
    agree about which entities a missing history leaves unread.
    """
    picked: list[tuple[float, str]] = []
    for eid, st in (states or {}).items():
        if domain_of(eid) != "sensor" or not isinstance(st, dict):
            continue
        if job_state(st.get("state")) not in JOB_FINISHED:
            continue
        changed = parse_ts(st.get("last_changed"))
        if changed is None or not 0 <= now - changed <= STALE_HOURS * 3600:
            continue
        name = (st.get("attributes") or {}).get("friendly_name") or ""
        if not job_kind_of(name):
            continue
        picked.append((changed, eid))
    picked.sort(key=lambda p: (-p[0], p[1]))
    return [eid for _changed, eid in picked[:JOB_FETCH_MAX]]


def job_finished_at(rows: list, now: float) -> float | None:
    """When the job that is finished now ended, or None if none did.

    Walked newest first: through finished words (each one moves the
    finish earlier, so a restart that re-published `finish` does not make
    a forty-minute-old job look two minutes old) and the pass-through
    words, until a running word — which confirms it — or anything else,
    which does not. A history that never reached a running word is a
    status that has said "finished" all along.
    """
    seq = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        ts = parse_ts(row.get("last_changed") or row.get("last_updated"))
        if ts is None or ts > now:
            continue
        seq.append((ts, job_state(row.get("state"))))
    seq.sort(key=lambda r: r[0])
    finished = None
    for ts, word in reversed(seq):
        if word in JOB_FINISHED:
            finished = ts
        elif word in JOB_PASS_THROUGH:
            continue
        elif _running(word):
            return finished
        else:
            return None
    return None


def _power_owns(house: House, snap: dict, eid: str) -> bool:
    """Does a power-profiled chore on the same device already cover this?

    A washer with both a smart plug and an operation state would otherwise
    be two rows about one load of washing, from two checks that cannot
    clear each other's. The power path was there first and keeps it.
    """
    device = (house.registry.get(eid) or {}).get("device_id")
    if not device:
        return False
    shapes = ((snap.get("appliances") or {}).get("entities") or {})
    for power_eid, shape in shapes.items():
        if (house.registry.get(power_eid) or {}).get("device_id") != device:
            continue
        if kind_of(shape.get("name") or house.name(power_eid)):
            return True
    return False


def job_done(snap: dict, now: float) -> list[dict]:
    """Status entities whose job finished a while ago and has not restarted."""
    states = snap.get("states") or {}
    candidates = job_candidates(states, now)
    if not candidates:
        return []
    if not (snap.get("available") or {}).get("job_status"):
        # Something says it finished and its history could not be read:
        # that is "I could not look", which may not clear last pass's row.
        raise CouldNotLook(
            (snap.get("errors") or {}).get("job_status")
            or "the recorder did not answer for the job status history")
    history = snap.get("job_status") or {}
    house = House(snap)

    hits = []
    for eid in candidates:
        if not house.enabled(eid):
            continue
        kind = job_kind_of(house.name(eid))
        if not kind or _power_owns(house, snap, eid):
            continue
        if not house.should_report(eid, "chore.job_done"):
            continue
        finished = job_finished_at(history.get(eid) or [], now)
        if finished is None:
            continue
        ago_min = (now - finished) / 60.0
        if ago_min < QUIET_MIN or ago_min > STALE_HOURS * 60.0:
            continue
        hits.append((finished, kind, eid))

    if len(hits) > MAX_ROWS:
        house.gave_up("chore.job_done", [{"entity_id": h[2]} for h in hits],
                      f"{len(hits)} machines said they had finished at once "
                      f"— past {MAX_ROWS} that is a status read wrong, not "
                      "a house full of chores")
        return []
    hits.sort()

    out = []
    for finished, kind, eid in hits:
        ago = int((now - finished) / 60.0)
        when = (f"{ago} minutes ago" if ago < 90
                else f"{ago // 60} hours ago")
        state = (states.get(eid) or {}).get("state")
        out.append({
            # Stable across runs; the minutes live in `detail`.
            "text": JOB_TEXT[kind],
            "detail": (f"{house.name(eid)} went from running to "
                       f"“{state}” {when}, and has not started "
                       "another job since. Read from the status its own "
                       "integration publishes."),
            "fix": ("Take it off, then tick it off — brAIn cannot see that "
                    "you have, because the status says the same thing "
                    "either way. It clears itself when the next job "
                    "starts."),
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


CHECKS = [
    {"id": "chore.waiting",
     "title": "Finished and still full",
     "needs": ("states", "registry", "appliances"), "run": waiting},
    # Needs no key of its own up front: on a house with nothing finished
    # it has nothing to read, and when something has finished and the
    # history could not be fetched it says so (`CouldNotLook`).
    {"id": "chore.job_done",
     "title": "Finished and waiting",
     "needs": ("states", "registry"), "run": job_done},
]

__all__ = ["CHECKS"]
