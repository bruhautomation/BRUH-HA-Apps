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

import numfmt

from . import _util
from ._util import (CouldNotLook, House, clock, domain_of, parse_ts,
                    state_words)

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


# What `chore.waiting` says. Power shows a machine stopped and nothing ran
# since — never whether its drum is empty, which is why "still full" was
# marked Wrong — so that is said only where a door or contact sensor on the
# same machine has stayed shut since the cycle ended. `was` carries the old
# wording, so an answer given to it is an answer to this report.
FINISHED_TEXT = "{machine} finished a cycle and nothing has run since"
FULL_TEXT = "{machine} has finished and is still full"
DOOR_CLASSES = frozenset({"door", "opening"})


def _door_of(house: House, eid: str) -> str:
    for other in sorted(house.siblings(eid)):
        if domain_of(other) != "binary_sensor":
            continue
        attrs = (house.states.get(other) or {}).get("attributes") or {}
        if str(attrs.get("device_class") or "") in DOOR_CLASSES:
            return other
    return ""


def _door_since(house: House, eid: str, finished: float) -> str:
    """``"closed"`` when the machine's door has stayed shut since the cycle
    ended, ``"opened"`` when it has moved since, "" for no door to read."""
    door = _door_of(house, eid)
    if not door:
        return ""
    st = house.states.get(door) or {}
    changed = parse_ts(st.get("last_changed"))
    if st.get("state") == "off" and changed is not None and changed < finished:
        return "closed"
    if st.get("state") in ("on", "off"):
        return "opened"
    return ""


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
        when = numfmt.ago_minutes(ago)
        door = _door_since(house, eid, finished)
        if door == "opened":
            continue        # its door has been opened since: emptied
        full = door == "closed"
        shut = (f"; {house.name(_door_of(house, eid))} has stayed shut"
                if full else "")
        out.append({
            # Stable across runs — the minutes change every pass and the
            # store dedupes on this text, so they live in `detail`. "Still
            # full" only where a door on the machine says it has stayed
            # shut: power cannot see whether a drum is empty.
            "text": (FULL_TEXT if full else FINISHED_TEXT).format(
                machine=KIND_NAMES[kind]),
            "was": [FULL_TEXT.format(machine=KIND_NAMES[kind])],
            "detail": (f"It stopped drawing power {when} "
                       f"(at {clock(finished)}), and nothing has run "
                       f"since{shut}. Measured from {house.name(eid)}: this "
                       f"machine draws about {shape.get('busy_w', 0):.0f}W "
                       f"running against {shape.get('idle_w', 0):.0f}W "
                       "idle, and goes quiet for up to "
                       f"{shape.get('settle_min', 0):.0f} minutes "
                       + ("mid-cycle." if shape.get("measured_settle")
                          else "mid-cycle (not yet measured here).")),
            "fix": ("Empty it if it needs emptying, then tick it off — "
                    "brAIn cannot see that you have, because an empty "
                    "machine and a full one draw exactly the same power. "
                    "It clears itself if the machine runs again."
                    if not full else
                    "Empty it, then tick it off. It clears itself when its "
                    "door is opened or the machine runs again."),
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


# A power or energy reading of a machine that cycles is bimodal by
# construction — near nothing, then hundreds of watts for an hour — so an
# hour-of-the-week band lands between the two where it never is, and a wash
# reads as "hundreds of spreads out". `checks/baseline.not_a_house_reading`
# and `appliances.select` both ask this, so the band checks and the nightly
# cap cannot disagree about which sensors those are. Two kinds of evidence,
# both this module's own vocabulary and never a second word list: a name
# (the sensor's or its device's) that `kind_of` reads as a washer, dryer or
# dishwasher, or a status entity on the same device speaking the job
# vocabulary (`JOB_RUNNING` / `JOB_FINISHED`), which is a machine saying in
# words that it runs cycles.
CYCLE_READING_CLASSES = frozenset({"power", "energy"})
CYCLE_READING_UNITS = frozenset({"W", "kW", "Wh", "kWh"})


def is_cycle_reading(attrs: dict) -> bool:
    """A power or energy reading — what a machine's cycle moves."""
    attrs = attrs or {}
    if str(attrs.get("device_class") or "") in CYCLE_READING_CLASSES:
        return True
    return str(attrs.get("unit_of_measurement") or "").strip() in CYCLE_READING_UNITS


def says_a_job(st) -> bool:
    """Whether a status entity's state, or the states it can take, speak the
    job vocabulary: it is a machine that reports running and finishing."""
    if not isinstance(st, dict):
        return False
    word = job_state(st.get("state"))
    if word in JOB_FINISHED or _running(word):
        return True
    options = (st.get("attributes") or {}).get("options")
    if isinstance(options, (list, tuple)):
        return any(_running(job_state(o)) for o in options)
    return False


# A machine at rest says one of these: what a printer's own status reads
# between jobs. Beside `JOB_FINISHED`, the only words that mean nothing is
# running; any other word a status that speaks the job vocabulary says
# (`prepare`, `heatbed_preheating`, `pause`, `changing_filament`) is the
# machine working.
JOB_IDLE = frozenset({"idle", "standby", "ready", "operational", "stopped",
                      "failed", "failure", "cancelled", "canceled",
                      "offline", "sleep", "sleeping"})
# Words that say nothing about whether it is working.
JOB_UNKNOWN = frozenset({"unavailable", "unknown", "", "removed", "none"})
_WORKING_WORDS = frozenset({"pause", "paused", "prepare", "preparing",
                            "heating", "preheating", "slicing", "init"})


def _status_word(st) -> str:
    """The job word a sibling status says now, or "" when it is not one.

    A sibling is a status when its own word is in the job vocabulary, or
    its options (an enum's) carry a running word — never any sensor with
    text in it, because a printer publishes its active spool's name too.
    """
    if not isinstance(st, dict):
        return ""
    word = job_state(st.get("state"))
    if (word in JOB_FINISHED or word in JOB_IDLE or _running(word)
            or word in _WORKING_WORDS):
        return word
    options = (st.get("attributes") or {}).get("options")
    if isinstance(options, (list, tuple)) and any(
            _running(job_state(o)) for o in options):
        return word
    return ""


def machine_status(house: House, eid: str) -> tuple[str, float | None, str]:
    """``(state, since, status_entity)`` for the machine `eid` belongs to.

    ``state`` is ``"working"`` when any status on the device says it is,
    ``"idle"`` when every status there says finished or idle (``since`` the
    latest of their changes), and ``""`` when nothing on the device speaks
    the job vocabulary or a status cannot be read — "could not tell", which
    no caller may read as idle.
    """
    statuses = []
    for other in sorted(house.siblings(eid)):
        if domain_of(other) != "sensor":
            continue
        st = house.states.get(other)
        word = _status_word(st)
        if word or (isinstance(st, dict)
                    and job_state(st.get("state")) in JOB_UNKNOWN
                    and says_a_job(st)):
            statuses.append((other, word, st))
    if not statuses:
        return "", None, ""
    idle_since, name = None, ""
    for other, word, st in statuses:
        if word in JOB_UNKNOWN:
            return "", None, ""
        if word not in JOB_FINISHED and word not in JOB_IDLE:
            return "working", None, other
        changed = parse_ts(st.get("last_changed"))
        if changed is None:
            return "", None, ""
        if idle_since is None or changed > idle_since:
            idle_since, name = changed, other
    return "idle", idle_since, name


def status_entity(house: House, eid: str) -> str:
    """The job status entity on `eid`'s device, or "" when there is none.

    The same test `machine_status` reads its statuses with, so a reason
    resolved against "the printer's status" names the entity that
    function will later read.
    """
    for other in sorted(house.siblings(eid)):
        if domain_of(other) != "sensor":
            continue
        st = house.states.get(other)
        if _status_word(st) or says_a_job(st):
            return other
    return ""


# --- a reason that names when the machine is meant to be like that ------
# "Normal while the printer is printing. Only unusual if hot while the
# printer is idle" is not "never tell me about the nozzle": it says the
# report is wanted in ONE of the machine's two states. Read in words, in
# the cheap direction — a reason this cannot place is asked about rather
# than guessed (`server._record_exception`), so a miss costs a question and
# never a silenced check.
_IDLE_PHRASES = ("not printing", "not running", "not working", "not in use",
                 "isn't printing", "isnt printing", "isn't running",
                 "nothing printing", "nothing is printing", "between prints",
                 "not on", "switched off", "turned off")
_IDLE_WORDS = frozenset({"idle", "idling", "standby", "finished", "done",
                         "off", "stopped", "asleep", "sleeping", "unused"})
_WORKING_WORDS_SAID = frozenset({"printing", "running", "working", "washing",
                                 "drying", "busy", "heating", "printer's",
                                 "print", "printed", "cycle", "on", "use"})
_ONLY_CLAUSE = re.compile(
    r"\bonly\b[^.;!?]*?\b(?:when|whenever|if|while|once|after|during)\b"
    r"([^.;!?]*)|\bunless\b([^.;!?]*)", re.I)
_NORMAL_CLAUSE = re.compile(
    r"\b(?:normal|fine|ok|okay|expected|usual)\b[^.;!?]*?"
    r"\b(?:while|when|whenever|during)\b([^.;!?]*)", re.I)


def _state_said(clause: str) -> str:
    text = " ".join(re.split(r"[^a-z']+", str(clause or "").lower()))
    if any(p in text for p in _IDLE_PHRASES):
        return "idle"
    words = set(text.split())
    if words & _IDLE_WORDS:
        return "idle"
    if words & _WORKING_WORDS_SAID:
        return "working"
    return ""


def report_while(reason: str) -> str:
    """`"idle"` or `"working"`: the machine state in which the person said
    the report IS wanted, or "" when the words do not say one.

    "Only unusual if hot while it is idle" and "fine unless it is idle" say
    idle; "normal while it is printing", with no "only" clause, says the
    report is wanted in the other state, idle.
    """
    for match in _ONLY_CLAUSE.finditer(str(reason or "")):
        said = _state_said(match.group(1) or match.group(2) or "")
        if said:
            return said
    for match in _NORMAL_CLAUSE.finditer(str(reason or "")):
        said = _state_said(match.group(1) or "")
        if said:
            return "working" if said == "idle" else "idle"
    return ""


def condition_holds(house: House, eid: str, reason: str) -> bool | None:
    """Whether a correction whose reason names a machine state stands the
    check down NOW. None when the reason names no state brAIn can read on
    this device — the rule is then the plain one it always was.

    True while the machine is in the state the person said was normal;
    False in the state they said they want to hear about, and False when
    the status cannot be read, because "could not tell" excepts nothing.
    """
    wanted = report_while(reason)
    if not wanted or not status_entity(house, eid):
        return None
    state, _since, _status = machine_status(house, eid)
    if not state:
        return False
    return state != wanted



_util.CONDITION_HOLDS = condition_holds

def cycling_kind(names, sibling_states) -> str:
    """Which cycling machine this is, `"machine"` for one known only by its
    status, or "" when nothing says it cycles.

    ``names`` are the sensor's own names and its device's; ``sibling_states``
    the live states of the `sensor` entities on the same device.
    """
    for name in names:
        kind = kind_of(name)
        if kind:
            return kind
    if any(says_a_job(st) for st in sibling_states or ()):
        return "machine"
    return ""


def cycling_machine(house: House, eid: str) -> str:
    """`cycling_kind` over a snapshot: the sensor's names, its device's name
    and the status entities beside it on that device."""
    st = house.states.get(eid) or {}
    reg = house.registry.get(eid) or {}
    names = [str((st.get("attributes") or {}).get("friendly_name") or ""),
             str(reg.get("name") or ""), str(reg.get("original_name") or ""),
             eid]
    device = house.device_of(eid)
    if device:
        names += [str(device.get("name_by_user") or ""),
                  str(device.get("name") or "")]
    siblings = [house.states.get(s) for s in house.siblings(eid)
                if domain_of(s) == "sensor"]
    return cycling_kind([n for n in names if n], siblings)


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


# BRUH Bambu Studio's print failure detection publishes, per printer, a
# "Plate clear" binary sensor: off while a print is on the plate, on once it
# has been taken off, unknown when nothing has looked. It is read off the
# snapshot by what the integration REGISTERED (its platform and translation
# key, or the unique id it builds), never by name, and nothing is imported
# from that add-on.
PLATE_PLATFORM = "bruh_bambu"
PLATE_KEY = "plate_clear"


def _is_plate(reg: dict) -> bool:
    if str(reg.get("platform") or "") != PLATE_PLATFORM:
        return False
    if str(reg.get("translation_key") or "") == PLATE_KEY:
        return True
    return str(reg.get("unique_id") or "").endswith("_" + PLATE_KEY)


def plate_for(house: House, eid: str) -> str:
    """The plate sensor for the printer this status entity belongs to, or
    "". On the same device, or on a device carrying the same serial number
    (the add-on's own device beside another integration's)."""
    device = house.device_of(eid) or {}
    if not device:
        return ""
    serial = str(device.get("serial_number") or "").strip()
    for other in house.entities:
        oid = str(other.get("entity_id") or "")
        if domain_of(oid) != "binary_sensor" or not _is_plate(other):
            continue
        if other.get("device_id") == device.get("id"):
            return oid
        theirs = house.devices.get(other.get("device_id") or "") or {}
        if serial and str(theirs.get("serial_number") or "").strip() == serial:
            return oid
    return ""


def plate_reading(house: House, plate: str, finished: float) -> str:
    """`"clear"`, `"occupied"`, or "" when the plate says nothing about
    THIS print: no reading, or a clear plate whose reading predates the
    finish (it was cleared before the job, not after)."""
    st = house.states.get(plate) or {}
    if st.get("state") == "off":
        return "occupied"
    if st.get("state") == "on":
        changed = parse_ts(st.get("last_changed"))
        if changed is not None and changed >= finished:
            return "clear"
    return ""


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
        plate = plate_for(house, eid) if kind == "printer" else ""
        seen = plate_reading(house, plate, finished) if plate else ""
        if seen == "clear":
            continue        # taken off: the chore is done
        hits.append((finished, kind, eid, seen))

    if len(hits) > MAX_ROWS:
        house.gave_up("chore.job_done", [{"entity_id": h[2]} for h in hits],
                      f"{len(hits)} machines said they had finished at once "
                      f"— past {MAX_ROWS} that is a status read wrong, not "
                      "a house full of chores")
        return []
    hits.sort()

    out = []
    for finished, kind, eid, seen in hits:
        ago = int((now - finished) / 60.0)
        when = numfmt.ago_minutes(ago)
        state = state_words((states.get(eid) or {}).get("state"))
        out.append({
            # Stable across runs; the minutes live in `detail`.
            "text": JOB_TEXT[kind],
            "detail": (f"{house.name(eid)} went from running to "
                       f"“{state}” {when}, and has not started "
                       "another job since. Read from the status its own "
                       "integration publishes."),
            "fix": ("Take the print off. This clears itself once BRUH "
                    "Bambu Studio sees the plate clear."
                    if seen == "occupied" else
                    ("Take the print off" if kind == "printer"
                     else "Empty it")
                    + ", then mark it done — brAIn cannot see that "
                    "you have, because the status says the same thing "
                    "either way. It clears itself when the next job "
                    "starts."),
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# A dehumidifier that stopped while the room is still damp
# ---------------------------------------------------------------------------
#
# A dehumidifier is not a machine that finishes and waits: it stops when the
# air is dry, and it stops when its tank is full. Power alone cannot tell the
# two apart, and the room's humidity can — so the appliance store records,
# for a machine it knows is a dehumidifier (`appliances.dehumidifiers`), the
# humidity in its room and the level it measurably starts running at, read
# off its own runs. A machine switched on, at standby for `DRY_STOPPED_H`,
# in a room `DRY_MARGIN` points above that level is a tank to empty. It
# clears itself when the machine runs again or the air dries. Floors: no
# level is no row (nothing measured it), a plug switched off is somebody's
# choice, and more than `MAX_ROWS` at once is a measurement gone wrong.
DRY_STOPPED_H = 3.0
DRY_MARGIN = 5.0


def dehumidifier(snap: dict, now: float) -> list[dict]:
    """Dehumidifiers at standby in a room damper than they run at."""
    import appliances  # noqa: PLC0415

    store = snap.get("appliances") or {}
    shapes = store.get("entities") or {}
    recent = store.get("recent") or {}
    house = House(snap)
    hits = []
    for eid, shape in shapes.items():
        if shape.get("kind") != appliances.DEHUMIDIFIER:
            continue
        level = shape.get("runs_from_rh")
        rh_eid = str(shape.get("humidity_entity") or "")
        if not isinstance(level, (int, float)) or not rh_eid:
            continue
        if not house.enabled(eid) or not house.should_report(
                eid, "chore.dehumidifier"):
            continue
        try:
            humidity = float((house.states.get(rh_eid) or {}).get("state"))
        except (TypeError, ValueError):
            continue
        if humidity < float(level) + DRY_MARGIN:
            continue
        switches = [o for o in house.siblings(eid) if domain_of(o) == "switch"]
        if switches and not any((house.states.get(o) or {}).get("state")
                                == "on" for o in switches):
            continue
        plug = next((o for o in switches
                     if (house.states.get(o) or {}).get("state") == "on"), "")
        points = recent.get(eid) or []
        reading = appliances.state_at(shape, points, now)
        if reading.get("state") not in (appliances.IDLE, appliances.FINISHED):
            continue
        watts = reading.get("watts")
        if not isinstance(watts, (int, float)) or watts >= float(
                shape.get("threshold_w") or 0):
            continue
        since = float(reading.get("finished_at") or reading.get("since") or 0)
        if not since or now - since < DRY_STOPPED_H * 3600:
            continue
        hits.append((since, eid, humidity, float(level), rh_eid, plug,
                     float(watts)))
    if len(hits) > MAX_ROWS:
        house.gave_up("chore.dehumidifier", [{"entity_id": h[1]} for h in hits],
                      f"{len(hits)} dehumidifiers stopped at once — past "
                      f"{MAX_ROWS} that is a measurement gone wrong")
        return []
    out = []
    for since, eid, humidity, level, rh_eid, plug, watts in sorted(hits):
        hours = int((now - since) // 3600)
        device = house.device_of(eid)
        name = house.device_name(device) if device else house.name(eid)
        out.append({
            "text": f"{name} has stopped while the air is still damp",
            "detail": (f"It has drawn only standby power for {hours} hours, "
                       f"while {house.name(rh_eid)} reads {humidity:.0f}% — "
                       f"it usually starts running at about {level:.0f}%. "
                       "A full tank stops it like this."
                       + house.placed(eid, name)),
            # What brAIn read, never "check it is switched on": the plug's
            # state and its draw say the power reaches it.
            "fix": ((f"{house.name(plug)} reads on and the plug draws "
                     if plug else "The plug draws ")
                    + f"{watts:.0f} W, so it has power: empty its tank. "
                    "This clears itself when it runs again."),
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# A print the printer stopped itself, on its own failure detection
# ---------------------------------------------------------------------------
#
# A printer that pauses a print because its failure detection saw spaghetti
# — or fails one outright — goes quiet: nothing is wrong with any device, the
# heaters may still be on, and the print sits at 10 % until somebody looks.
# `chore.print_stopped` reads three things off the same device, all of them
# states the snapshot already holds: the status says paused or failed, and a
# problem flag (a `problem` binary sensor that is on) or a failure-detection
# sensor reading failure or warning says the printer did it. A pause with no
# flag is a person pressing pause and says nothing. Read by what the
# integration registered (its translation key) first and by name second, so
# BRUH Bambu Studio's sensors and another printer integration's both count.
STOPPED_WORDS = frozenset({"pause", "paused", "failed", "failure", "error"})
PROBLEM_KEYS = frozenset({"print_problem", "print_error", "hms_errors"})
FAILURE_KEYS = frozenset({"failure_detection"})
FAILURE_WORDS = frozenset({"failure", "warning"})
BED_KEYS = frozenset({"bed", "bed_temp", "bed_temperature"})
PROGRESS_KEYS = frozenset({"progress", "print_progress"})
# Warm enough that "the bed is still hot" is worth saying.
BED_WARM = {"°C": 40.0, "°F": 104.0}


def _key_or_words(house: House, eid: str, keys, phrase: str) -> bool:
    reg = house.registry.get(eid) or {}
    if str(reg.get("translation_key") or "") in keys:
        return True
    name = " ".join(_WORD_RE.findall(house.name(eid).lower()))
    return phrase in name


def _flagged(house: House, eid: str) -> str:
    """The sibling that says the printer stopped this print itself, or ""."""
    for other in sorted(house.siblings(eid)):
        st = house.states.get(other) or {}
        attrs = st.get("attributes") or {}
        if domain_of(other) == "binary_sensor" and st.get("state") == "on" and (
                str(attrs.get("device_class") or "") == "problem"
                or _key_or_words(house, other, PROBLEM_KEYS, "print problem")):
            return other
        if domain_of(other) == "sensor" and job_state(
                st.get("state")) in FAILURE_WORDS and _key_or_words(
                    house, other, FAILURE_KEYS, "failure detection"):
            return other
    return ""


def _sibling_reading(house: House, eid: str, keys, word: str):
    for other in sorted(house.siblings(eid)):
        if domain_of(other) != "sensor":
            continue
        reg = house.registry.get(other) or {}
        words = set(_WORD_RE.findall(house.name(other).lower()))
        if str(reg.get("translation_key") or "") in keys or (
                word in words and "target" not in words):
            st = house.states.get(other) or {}
            try:
                return other, float(st.get("state"))
            except (TypeError, ValueError):
                return other, None
    return "", None


def _is_printer(house: House, eid: str) -> bool:
    from . import devices  # noqa: PLC0415 — devices reads this module's words
    if devices.machine_of(house, eid) == "printer":
        return True
    return bool(job_kind_of(house.name(eid)) == "printer")


def print_stopped(snap: dict, now: float) -> list[dict]:
    """A print the printer paused or failed on its own failure detection."""
    house = House(snap)
    out = []
    for eid in sorted(house.states):
        if domain_of(eid) != "sensor" or not house.enabled(eid):
            continue
        st = house.states.get(eid) or {}
        if job_state(st.get("state")) not in STOPPED_WORDS:
            continue
        if _key_or_words(house, eid, FAILURE_KEYS, "failure detection"):
            continue
        if not house.device_of(eid) or not _is_printer(house, eid):
            continue
        flag = _flagged(house, eid)
        if not flag:
            continue        # paused by a person: nothing to say
        if not house.should_report(eid, "chore.print_stopped"):
            continue
        printer = house.device_name(house.device_of(eid) or {})
        since = parse_ts(st.get("last_changed"))
        how_long = (numfmt.ago_minutes(int((now - since) / 60.0))
                    if since is not None else "at a time brAIn cannot read")
        word = state_words(st.get("state") or "")
        bits = [f"{house.name(eid)} has said “{word}” since {how_long}, and "
                f"{house.name(flag)} says the printer stopped it."]
        _prog, progress = _sibling_reading(house, eid, PROGRESS_KEYS,
                                           "progress")
        if progress is not None:
            bits.append(f"It stopped at {numfmt.number(progress)} %.")
        bed, bed_value = _sibling_reading(house, eid, BED_KEYS, "bed")
        if bed and bed_value is not None:
            unit = str(((house.states.get(bed) or {}).get("attributes") or {})
                       .get("unit_of_measurement") or "")
            warm = BED_WARM.get(unit)
            hot = warm is not None and bed_value >= warm
            bits.append(f"The bed is {'still hot at' if hot else 'at'} "
                        f"{numfmt.quantity(bed_value, unit)}"
                        + ("." if hot else ", cooled down."))
        out.append({
            # Stable while the print stays stopped; how long lives in detail.
            "text": f"{printer} stopped a print on its own failure detection",
            "detail": " ".join(bits) + house.placed(eid),
            "fix": ("Look at the print, then resume it or cancel it from the "
                    "printer or BRUH Bambu Studio. A cancelled print turns "
                    "the heaters off; a paused one may keep the bed hot."),
            "severity": "warning",
            "fixable": False,
            "entity_id": eid,
        })
    return out


CHECKS = [
    {"id": "chore.dehumidifier", "area": "devices",
     "title": "Dehumidifier stopped in a damp room",
     "needs": ("states", "registry", "appliances"), "run": dehumidifier},
    {"id": "chore.waiting", "area": "devices",
     "title": "Finished and not run since",
     "needs": ("states", "registry", "appliances"), "run": waiting},
    # Needs no key of its own up front: on a house with nothing finished
    # it has nothing to read, and when something has finished and the
    # history could not be fetched it says so (`CouldNotLook`).
    {"id": "chore.job_done", "area": "devices",
     "title": "Finished and waiting",
     "needs": ("states", "registry"), "run": job_done},
    {"id": "chore.print_stopped", "area": "devices",
     "title": "Print stopped by the printer",
     "needs": ("states", "registry"), "run": print_stopped},
]

__all__ = ["CHECKS"]
