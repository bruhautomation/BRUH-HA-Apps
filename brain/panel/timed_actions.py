"""Something to do now and undo later, without writing an automation.

*"Water the garden for 90 minutes."* *"In an hour turn on the porch
light."* Neither is a rule about the house: each is a couple of service
calls at two moments, asked for by somebody who is there. Until this
module the interpreter read them as a one-off and brAIn drafted a run-once
automation that waited on a card for somebody to accept it — a file
written into `automations.yaml`, a reload, a verification and a press,
for something the person had already said in as many words. These are
**timed actions**: a short list of steps brAIn runs itself, listed in the
panel and in Morph, each one stoppable.

(The automation listener's task folder is "tasks"; these are not those.)

Five rules.

**Words become steps in one cheap tool-less run, and code decides.** The
`timed` job is handed the sentence and the controllable entities the
house has, and answers with steps under a schema (:data:`SCHEMA`). Every
step is then checked here (:func:`build`): its service through
`plan_ops.clean_op` — the same reader a fix's `call_service` op goes
through, so the refused domains, the security-reducing services, the
same-domain rule and the no-area-target rule are one rule and not two —
and then against the house: each entity has to exist in the states read
for this request, none may be on the protected list or be the tripwire,
and none may be a garage, door or gate cover being opened
(`unfix.OPENING_COVER_CLASSES`). A service that runs OTHER things
(:data:`RUNS_OTHER_THINGS`: a script, a scene, an automation, a button)
is refused, because what it reaches cannot be checked from the step. A
sentence that is not something to do on a timer, or that the run could
not read, is handed back so the caller does what it did before; a step
refused for safety is said, never handed to the automation path, which
would offer the same thing as a card.

**Each step goes through the chokepoint every panel call goes through.**
The loop in the server carries a step out with `typed_fix.execute`: the
protected list and the tripwire are asked again at that moment, the
before-state is read, and the call is written to the action ledger under
the channel `timed`, so the Timeline attributes it to brAIn. The step is
also re-checked here (:func:`check_step`) against the entity's state as
it is now, because a cover's class or the protected list may have changed
since the sentence was read.

**Never hours late** (:func:`decide`). A step whose moment passed while
the add-on was down is run on the next tick if it is under
:data:`LATE_S` late, or if a later step in the same task is still to come
(the window it belongs to is still open — the valve can still run the
rest of its ninety minutes). Otherwise it is recorded as missed and the
task's other ordinary steps with it. The task's FINAL step, when it is
the one that puts the house back (`ends`, the valve turned off), is run
however late it is and only if something before it ran: it is the step
that stops a thing that would otherwise go on, so the later it is the
more it is owed.

**A failure is recorded on the task and said once.** The step carries the
reason; the task's later ordinary steps are skipped and its final `ends`
step still runs at its time, so whatever did happen is put back. The
server notifies once per task (`notified`).

**Stop runs the ending.** Stopping a task cancels every pending step and,
when the task has an `ends` step and something before it ran, runs that
step at once: stopping the watering turns the valve off.

The store is `/data/timed-actions.json`: capped (:data:`MAX_LIVE` live,
:data:`MAX_ROWS` kept), written through `atomic_write`, read back after a
restart.

Stdlib only, plus the panel's own modules.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

import atomic_write
import automation_writer
import plan_ops
import prompt_kit
import textclip
import unfix

STORE = Path(os.environ.get("BRAIN_TIMED_FILE", "/data/timed-actions.json"))

# How many may be waiting or running at once. Past this the list has
# stopped being a short list of things about to happen, and the add is
# refused rather than room made — `todo_store`'s rule.
MAX_LIVE = 10
# Finished ones are kept, newest first, so "did that run?" has an answer.
MAX_ROWS = 40
MAX_STEPS = 6
# A timed action is about the next day at most. Anything longer is a rule.
MAX_AFTER_MIN = 24 * 60
MAX_TITLE = 120
MAX_SAID = 300
MAX_CANDIDATES = 250
# A step this late is still on time enough to run.
LATE_S = 300
TIMEOUT_S = 45

STATUSES = ("scheduled", "running", "done", "stopped", "missed", "failed")
LIVE = frozenset({"scheduled", "running"})
STEP_STATUSES = ("pending", "done", "failed", "skipped", "missed", "stopped")

# The domains a sentence can be about. Readings, people and the house's
# own machinery are not things to switch on for an hour.
CONTROLLABLE = frozenset({
    "light", "switch", "fan", "cover", "valve", "climate", "media_player",
    "humidifier", "water_heater", "vacuum", "lawn_mower", "input_boolean",
    "siren", "lock", "alarm_control_panel", "number", "select",
    "input_number", "input_select",
})
# Services whose reach is whatever SOMETHING ELSE says: a script's actions,
# a scene's states, an automation's actions, whatever a button is wired to.
# A step names the things it changes, so these are refused whole.
RUNS_OTHER_THINGS = frozenset({"script", "scene", "automation", "button",
                               "input_button"})
# A cover of one of these classes is a way into the house: only closing or
# stopping one is a step brAIn takes on a timer.
COVER_SAFE_SERVICES = frozenset({"close_cover", "stop_cover",
                                 "close_cover_tilt", "stop_cover_tilt"})
# One list with Undo's restore rule, which never opens one either.
OPENING_COVER_CLASSES = unfix.OPENING_COVER_CLASSES

_LOCK = threading.Lock()


class Refused(ValueError):
    """A step brAIn will not take. The message is the sentence."""


# ---------------------------------------------------------------------------
# The run that reads the sentence
# ---------------------------------------------------------------------------

# Model-facing: code checks every step before anything runs; the person
# never reads this run's words except the title. A tool-less schema run.
SYSTEM = prompt_kit.assemble(
    "You turn one thing a homeowner asked their smart home to do into a "
    "short list of timed steps — what to call, on which devices, and how "
    "many minutes from now. You do not act; code checks every step and "
    "runs it.",
    inputs=(
        "You are given what they asked and the devices the house has, each "
        "as its entity id and its name."),
    tools="none",
    good=(
        "One step per moment something changes, each naming the devices "
        "by their entity ids from the list and a service of that device's "
        "own kind. When the request is for a while (\"for 90 minutes\"), "
        "the last step puts it back and has ends: true."),
    example=(
        "\"Water the garden for 90 minutes\" with valve.garden_zone_1 "
        "(Garden zone 1) → title \"Water the garden for 90 minutes\", steps "
        "[{after_minutes: 0, domain: valve, service: open_valve, entities: "
        "[valve.garden_zone_1]}, {after_minutes: 90, domain: valve, "
        "service: close_valve, entities: [valve.garden_zone_1], ends: "
        "true}]. \"In an hour turn on the porch light\" → one step, "
        "after_minutes 60, light.turn_on."),
    rules="""\
- timed is false when the request is not something to do now or after a
  delay — when it waits for something to happen ("when the guests
  leave"), or should happen every time ("every evening") — and then the
  steps are empty.
- Use only entity ids from the list. A device the list does not have is
  timed false.
- after_minutes is from now, 0 to 1440.
- Never unlock, open a garage, door or gate, or disarm an alarm.
- title is their request said back in a few plain words.""",
    person_facing=False,
)

SCHEMA = {
    "type": "object",
    "properties": {
        "timed": {"type": "boolean"},
        "title": {"type": "string"},
        "steps": {
            "type": "array",
            "maxItems": MAX_STEPS,
            "items": {
                "type": "object",
                "properties": {
                    "after_minutes": {"type": "number", "minimum": 0,
                                      "maximum": MAX_AFTER_MIN},
                    "domain": {"type": "string"},
                    "service": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"},
                                 "maxItems": plan_ops.MAX_ENTITIES},
                    "data": {"type": "object"},
                    "ends": {"type": "boolean"},
                },
                "required": ["after_minutes", "domain", "service", "entities"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["timed", "steps"],
    "additionalProperties": False,
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _name_of(row: dict) -> str:
    attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) \
        else {}
    return " ".join(str(attrs.get("friendly_name") or "").split())[:80]


def candidates(states: dict, sentence: str,
               cap: int = MAX_CANDIDATES) -> list[tuple[str, str]]:
    """The controllable entities to offer the run, the likeliest first.

    `states` is `{entity_id: state row}`. An entity whose name or id shares
    a word with the sentence goes ahead of the rest, so the cap takes the
    ones the sentence is about; ties sort by id so a pass is repeatable.
    """
    words = set(_WORD_RE.findall(str(sentence or "").lower()))
    scored = []
    for eid, row in (states or {}).items():
        if not isinstance(row, dict) or "." not in str(eid):
            continue
        if eid.split(".", 1)[0] not in CONTROLLABLE:
            continue
        name = _name_of(row)
        hits = len(words & set(_WORD_RE.findall((name + " " + eid).lower())))
        scored.append((-hits, eid, name))
    scored.sort()
    return [(eid, name) for _h, eid, name in scored[:cap]]


def prompt(sentence: str, offered: list[tuple[str, str]]) -> str:
    lines = [f"They asked: “{str(sentence or '')[:MAX_SAID]}”",
             "The devices (entity id — name):"]
    lines += [f"- {eid} — {name or 'no name'}" for eid, name in offered]
    if not offered:
        lines.append("- none")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checking a step
# ---------------------------------------------------------------------------

def _cover_class(row: dict | None) -> str:
    attrs = (row or {}).get("attributes") if isinstance(row, dict) else {}
    return str((attrs or {}).get("device_class") or "").lower()


def check_step(step: dict, states: dict, protected=None,
               honeytokens=()) -> dict:
    """One step, normalised and checked against the house, or `Refused`.

    `states` is `{entity_id: state row}` as read for THIS check: at build
    time the request's read, at run time a fresh read of the step's own
    entities. An entity missing from it does not exist (or could not be
    seen), and a step about something brAIn cannot see is not taken.
    """
    op = plan_ops.clean_op({"op": "call_service",
                            "domain": step.get("domain"),
                            "service": step.get("service"),
                            "entities": step.get("entities"),
                            "data": step.get("data") or {}})
    domain, service = op["domain"], op["service"]
    if domain in RUNS_OTHER_THINGS:
        raise Refused(f"a {domain} runs other things brAIn cannot check from "
                      "here, so it is not a timed step — name the devices "
                      "themselves")
    for eid in op["entities"]:
        row = states.get(eid) if isinstance(states, dict) else None
        if not isinstance(row, dict):
            raise Refused(f"brAIn cannot see {_spoken(eid)} in Home Assistant, "
                          "so it will not act on it")
        if domain == "cover" and service not in COVER_SAFE_SERVICES \
                and _cover_class(row) in OPENING_COVER_CLASSES:
            raise Refused(f"{_name_of(row) or _spoken(eid)} is a way into the house, "
                          "and brAIn only ever closes one on a timer")
    why = plan_ops.protected_refusal([op], protected, honeytokens)
    if why:
        # `protected_refusal` is the rule; the sentence is this module's,
        # because a person reads it: the device by its name, and the
        # tripwire by nothing at all.
        tokens = {str(t).lower() for t in honeytokens or ()}
        if any(e in tokens for e in op["entities"]):
            raise Refused("that is a device brAIn never acts on")
        named = next((e for e in op["entities"]
                      if automation_writer.is_protected(
                          e, automation_writer.protected_patterns(protected))),
                     "")
        if named:
            row = states.get(named) or {}
            raise Refused(f"{_name_of(row) or _spoken(named)} is on the "
                          "protected entities list, so brAIn will not act "
                          "on it")
        raise Refused(why)
    return op


def build(answer, sentence: str, states: dict, *, protected=None,
          honeytokens=(), now: float | None = None, via: str = "") -> dict:
    """A task from the run's answer, or `Refused`, or None.

    None is "not a timed action" — the run said timed false, or answered
    nothing readable, or named no step — and the caller does what it did
    before this module existed. `Refused` is a step brAIn will not take,
    and its message is said to the person.
    """
    now = time.time() if now is None else float(now)
    if not isinstance(answer, dict) or answer.get("timed") is not True:
        return None
    raw = answer.get("steps")
    if not isinstance(raw, list) or not raw:
        return None
    if len(raw) > MAX_STEPS:
        raise Refused(f"a timed action has at most {MAX_STEPS} steps")
    steps = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        after = item.get("after_minutes")
        if isinstance(after, bool) or not isinstance(after, (int, float)):
            return None
        if not 0 <= after <= MAX_AFTER_MIN:
            raise Refused("a timed action happens within the next day; "
                          "anything longer is a rule brAIn can write as an "
                          "automation")
        try:
            op = check_step(item, states, protected, honeytokens)
        except plan_ops.Refused as exc:
            raise Refused(str(exc)) from None
        steps.append({"at": int(now + float(after) * 60),
                      "domain": op["domain"], "service": op["service"],
                      "entities": op["entities"], "data": op["data"],
                      # What each is called now, so the list reads in names
                      # before any checks pass has named the house.
                      "names": {e: _name_of(states[e]) for e in op["entities"]
                                if _name_of(states[e])},
                      "ends": item.get("ends") is True,
                      "status": "pending"})
    steps.sort(key=lambda s: s["at"])
    ends = [i for i, s in enumerate(steps) if s["ends"]]
    if len(ends) > 1 or (ends and ends[0] != len(steps) - 1) or \
            (ends and len(steps) == 1):
        # Only the last step can be the one that puts the house back, and
        # a single step has nothing before it to undo.
        for s in steps:
            s["ends"] = False
        if ends and len(steps) > 1:
            steps[-1]["ends"] = True
    title = textclip.clip(" ".join(str(answer.get("title") or "").split())
                          or " ".join(str(sentence or "").split()), MAX_TITLE)
    return {"title": title,
            "said": textclip.clip(" ".join(str(sentence or "").split()),
                                  MAX_SAID),
            "via": str(via or "")[:32], "created": int(now),
            "status": "scheduled", "steps": steps}


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _read() -> list[dict]:
    try:
        rows = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(
        r.get("id"), int) and isinstance(r.get("steps"), list)] \
        if isinstance(rows, list) else []


def _write(rows: list[dict]) -> None:
    live = [r for r in rows if r.get("status") in LIVE]
    done = sorted((r for r in rows if r.get("status") not in LIVE),
                  key=lambda r: -int(r.get("created") or 0))
    keep = live + done[:max(0, MAX_ROWS - len(live))]
    keep.sort(key=lambda r: -int(r.get("created") or 0))
    atomic_write.write_json(STORE, keep, indent=1)


def load() -> list[dict]:
    with _LOCK:
        return _read()


def get(task_id: int) -> dict | None:
    for row in load():
        if row.get("id") == task_id:
            return row
    return None


def add(task: dict) -> dict | None:
    """Store a built task. None when :data:`MAX_LIVE` are already waiting."""
    with _LOCK:
        rows = _read()
        if sum(1 for r in rows if r.get("status") in LIVE) >= MAX_LIVE:
            return None
        task_id = int(task.get("created", time.time()) * 1000)
        taken = {r.get("id") for r in rows}
        while task_id in taken:
            task_id += 1
        row = {**task, "id": task_id, "notified": False}
        rows.append(row)
        _write(rows)
        return row


def _update(task_id: int, change) -> dict | None:
    with _LOCK:
        rows = _read()
        for row in rows:
            if row.get("id") == task_id:
                change(row)
                _settle(row)
                _write(rows)
                return row
    return None


def _settle(row: dict) -> None:
    """The task's status, read off its steps."""
    if row.get("status") == "stopped":
        return
    states = [s.get("status") for s in row["steps"]]
    if "pending" in states:
        row["status"] = "running" if any(
            s in ("done", "failed") for s in states) else "scheduled"
        return
    if "failed" in states:
        row["status"] = "failed"
    elif "missed" in states:
        # A step that came too late to run is the answer to "did it
        # happen", even where an ending put the house back after it.
        row["status"] = "missed"
    elif "done" in states:
        row["status"] = "done"
    else:
        row["status"] = "missed"


def decide(task: dict, index: int, now: float) -> str:
    """What to do with a due step: `run`, `missed` or `skip`.

    The never-hours-late rule (module docstring). `skip` is a step that
    will not run because of what happened earlier in the task.
    """
    steps = task["steps"]
    step = steps[index]
    before = steps[:index]
    ran = any(s.get("status") == "done" for s in before)
    broke = any(s.get("status") in ("failed", "missed", "skipped")
                for s in before)
    if step.get("ends"):
        return "run" if ran else "skip"
    if broke:
        return "skip"
    late = now - int(step["at"])
    if late <= LATE_S:
        return "run"
    later_open = any(int(s["at"]) > now for s in steps[index + 1:])
    return "run" if later_open else "missed"


def due(now: float) -> list[tuple[int, int]]:
    """`(task id, step index)` for every pending step whose moment came."""
    out = []
    for row in load():
        if row.get("status") not in LIVE:
            continue
        for i, step in enumerate(row["steps"]):
            if step.get("status") == "pending" and int(step["at"]) <= now:
                out.append((row["id"], i))
    out.sort(key=lambda pair: pair)
    return out


def mark_step(task_id: int, index: int, status: str, *, error: str = "",
              now: float | None = None) -> dict | None:
    if status not in STEP_STATUSES:
        raise ValueError(status)
    stamp = int(time.time() if now is None else now)

    def change(row):
        step = row["steps"][index]
        step["status"] = status
        step["when"] = stamp
        if error:
            step["error"] = textclip.clip(str(error), 300)
            row["error"] = step["error"]
    return _update(task_id, change)


def mark_notified(task_id: int) -> dict | None:
    return _update(task_id, lambda row: row.__setitem__("notified", True))


def stop(task_id: int, now: float | None = None) -> tuple[dict | None, int]:
    """Cancel every pending step. Returns `(task, index of the ending to
    run now)` — the index is -1 when there is none to run (no `ends` step,
    it already ran, or nothing before it ran)."""
    stamp = int(time.time() if now is None else now)
    holder = {"run": -1}

    def change(row):
        steps = row["steps"]
        ran = any(s.get("status") == "done" for s in steps
                  if not s.get("ends"))
        for i, step in enumerate(steps):
            if step.get("status") != "pending":
                continue
            if step.get("ends") and ran:
                holder["run"] = i
                continue
            step["status"] = "stopped"
            step["when"] = stamp
        row["stopped_at"] = stamp
    with _LOCK:
        rows = _read()
        for row in rows:
            if row.get("id") != task_id:
                continue
            if row.get("status") not in LIVE:
                return row, -1
            change(row)
            if holder["run"] < 0:
                row["status"] = "stopped"
            else:
                _settle(row)
            _write(rows)
            return row, holder["run"]
    return None, -1


def finish_stop(task_id: int) -> dict | None:
    """After the ending a Stop ran: the task reads as stopped."""
    return _update(task_id, lambda row: row.__setitem__("status", "stopped"))


# ---------------------------------------------------------------------------
# Words a person reads
# ---------------------------------------------------------------------------

_VERBS = {"turn_on": "Turn on", "turn_off": "Turn off", "toggle": "Switch",
          "open_valve": "Open", "close_valve": "Close", "open_cover": "Open",
          "close_cover": "Close", "stop_cover": "Stop", "lock": "Lock",
          "start": "Start", "stop": "Stop", "return_to_base": "Send home",
          "set_temperature": "Set the temperature of",
          "set_hvac_mode": "Set the mode of", "media_pause": "Pause",
          "media_play": "Play", "media_stop": "Stop", "set_value": "Set",
          "select_option": "Set", "set_percentage": "Set the speed of"}


def _spoken(entity_id: str) -> str:
    """An entity with no name, read aloud rather than shown as an id."""
    return str(entity_id).split(".", 1)[-1].replace("_", " ")


def describe_step(step: dict, names: dict | None = None) -> str:
    names = names or {}
    kept = step.get("names") if isinstance(step.get("names"), dict) else {}
    things = [str((names.get(e) or {}).get("name") or kept.get(e)
                  or _spoken(e))
              for e in step.get("entities") or []]
    verb = _VERBS.get(step.get("service"),
                      str(step.get("service") or "").replace("_", " ")
                      .capitalize())
    return f"{verb} {', '.join(things)}".strip()


def summary(row: dict, now: float, names: dict | None = None) -> dict:
    """A task as the panel and Morph draw it, with the time left."""
    pending = [s for s in row["steps"] if s.get("status") == "pending"]
    nxt = min((int(s["at"]) for s in pending), default=0)
    last = max((int(s["at"]) for s in row["steps"]), default=0)
    out = {"id": row["id"], "title": row.get("title") or "",
           "said": row.get("said") or "", "status": row.get("status"),
           "created": row.get("created"), "via": row.get("via") or "",
           "next_at": nxt or None, "ends_at": last or None,
           "left_s": max(0, int(last - now)) if row.get("status") in LIVE
           else 0,
           "next_in_s": max(0, int(nxt - now)) if nxt else None,
           "can_stop": row.get("status") in LIVE,
           "stop_runs": next((describe_step(s, names) for s in pending
                              if s.get("ends")), ""),
           "steps": [{"at": int(s["at"]), "does": describe_step(s, names),
                      "status": s.get("status"),
                      **({"error": s["error"]} if s.get("error") else {})}
                     for s in row["steps"]]}
    if row.get("error"):
        out["error"] = row["error"]
    return out


def listing(now: float | None = None, names: dict | None = None) -> dict:
    now = time.time() if now is None else float(now)
    rows = load()
    live = [summary(r, now, names) for r in rows if r.get("status") in LIVE]
    live.sort(key=lambda r: r["next_at"] or 0)
    done = [summary(r, now, names) for r in rows if r.get("status") not in LIVE]
    return {"tasks": live, "finished": done[:10], "max": MAX_LIVE}


STOP_REQUEST_KIND = "timed"


def morph_payload(now: float | None = None, names: dict | None = None) -> dict:
    """`timed.json` for Morph: what is waiting or running, and how to stop
    one — a request on the finding-request queue, the shape every other
    Morph press already rides."""
    now = time.time() if now is None else float(now)
    tasks = []
    for row in listing(now, names)["tasks"]:
        # Morph counts down from the stamps itself: a file rewritten every
        # second to move a number would be a write nobody needs.
        row = {k: v for k, v in row.items() if k not in ("left_s",
                                                          "next_in_s")}
        tasks.append({**row, "stop": {"kind": STOP_REQUEST_KIND,
                                      "action": "stop", "id": row["id"]}})
    return {"v": 1, "at": int(now), "tasks": tasks}


__all__ = ["CONTROLLABLE", "LATE_S", "LIVE", "MAX_AFTER_MIN", "MAX_LIVE",
           "MAX_ROWS", "MAX_STEPS", "Refused", "RUNS_OTHER_THINGS", "SCHEMA",
           "STATUSES", "STOP_REQUEST_KIND", "STORE", "SYSTEM", "TIMEOUT_S",
           "add", "build", "candidates", "check_step", "decide",
           "describe_step", "due", "finish_stop", "get", "listing", "load",
           "mark_notified", "mark_step", "morph_payload", "prompt", "stop",
           "summary"]
