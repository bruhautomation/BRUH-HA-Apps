"""Automation, script and scene checks.

What breaks an automation, in the order people hit it: it names something
that is gone, it calls a service that is gone, it errors when it runs, it
runs and never gets past its own condition, it fights itself over `mode:
single`, it was switched off to debug and forgotten, it never fires at all,
or it is a copy of another one.

All of these read the config files (``automations.yaml`` and friends), the
entity registry, the automation entities' state and the traces Home
Assistant keeps in ``.storage/trace.saved_traces``. None of them need the
model.
"""
from __future__ import annotations

import json
import logging
import os

from ._util import DAY, House, age_days, join_names, listify, walk, when

log = logging.getLogger("brain.checks.automations")

# An automation is "old enough to have fired" after this long. Younger ones
# are still being written.
NEVER_FIRED_DAYS = 30
FORGOTTEN_OFF_DAYS = 30
# Traces the store keeps per automation is small (5 by default), so these
# thresholds are about the *shape* of the recent history, not a census.
CONDITION_MIN_RUNS = 3
ALREADY_RUNNING_MIN = 3
# How long a trigger entity has to have been unavailable before the
# automation it belongs to counts as broken rather than restarting.
TRIGGER_DEAD_DAYS = 2
# Trigger kinds that legitimately go months without firing.
RARE_TRIGGERS = frozenset({"event", "webhook", "tag", "homeassistant", "mqtt",
                           "persistent_notification", "conversation"})


def _automations(house: House) -> list[dict]:
    out = []
    for cfg in house.snap.get("automations") or []:
        if not isinstance(cfg, dict):
            continue
        cid = str(cfg.get("id") or "")
        entity_id = house.automation_entity(cid) if cid else ""
        alias = str(cfg.get("alias") or entity_id or cid or "an automation")
        out.append({"config": cfg, "id": cid, "entity_id": entity_id,
                    "alias": alias})
    return out


def _scripts(house: House) -> list[dict]:
    out = []
    scripts = house.snap.get("scripts") or {}
    if isinstance(scripts, dict):
        for key, cfg in scripts.items():
            if isinstance(cfg, dict):
                out.append({"config": cfg, "id": str(key),
                            "entity_id": f"script.{key}",
                            "alias": str(cfg.get("alias") or key)})
    return out


def _scenes(house: House) -> list[dict]:
    out = []
    for cfg in house.snap.get("scenes") or []:
        if isinstance(cfg, dict):
            name = str(cfg.get("name") or cfg.get("id") or "a scene")
            out.append({"config": cfg, "id": str(cfg.get("id") or ""),
                        "entity_id": "", "alias": name})
    return out


def _label(kind: str, item: dict) -> str:
    return f"{kind} '{item['alias']}'"


# ---------------------------------------------------------------------------
# auto.dead_ref — names an entity that does not exist
# ---------------------------------------------------------------------------

def dead_ref(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for kind, items in (("Automation", _automations(house)),
                        ("Script", _scripts(house)),
                        ("Scene", _scenes(house))):
        for item in items:
            refs = house.entity_refs(item["config"])
            # An automation's own entity id can appear inside its config
            # (a "disable myself" action); that is not a dead reference.
            refs.discard(item["entity_id"])
            dead = sorted(r for r in refs if not house.exists(r))
            if not dead:
                continue
            out.append({
                "text": f"{_label(kind, item)} refers to entities that do "
                        "not exist",
                "detail": "Missing: " + join_names(dead) + ". "
                          + ("It cannot work as written." if kind != "Scene"
                             else "Those parts of the scene do nothing."),
                "fix": "Point it at the entity that replaced "
                       + ("them" if len(dead) > 1 else "it")
                       + ", or remove the reference.",
                "severity": "serious" if kind != "Scene" else "warning",
                "fixable": True,
                "entity_id": item["entity_id"] or dead[0],
            })
    return out


# ---------------------------------------------------------------------------
# auto.dead_service — calls a service that is not registered
# ---------------------------------------------------------------------------

def _service_calls(config) -> set[str]:
    calls: set[str] = set()
    for node in walk(config):
        if not isinstance(node, dict):
            continue
        for key in ("service", "action"):
            val = node.get(key)
            if isinstance(val, str) and "." in val and "{" not in val:
                calls.add(val.strip().lower())
    return calls


def _closest_notify(target: str, services: set[str]) -> str:
    if not target.startswith("notify."):
        return ""
    candidates = sorted(s for s in services if s.startswith("notify.mobile_app_"))
    return candidates[0] if len(candidates) == 1 else ""


def dead_service(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    services = set(snap.get("services") or [])
    if not services:
        return []
    out = []
    for kind, items in (("Automation", _automations(house)),
                        ("Script", _scripts(house))):
        for item in items:
            missing = sorted(s for s in _service_calls(item["config"])
                             if s not in services)
            if not missing:
                continue
            hint = _closest_notify(missing[0], services)
            out.append({
                "text": f"{_label(kind, item)} calls a service that no "
                        "longer exists",
                "detail": "Not registered: " + join_names(missing) + ". "
                          "The action fails every time it runs.",
                "fix": (f"Change it to {hint} — the only mobile notify "
                        "service registered now." if hint else
                        "Change the action to a service that exists "
                        "(Developer tools → Actions lists them)."),
                "severity": "serious",
                "fixable": True,
                "entity_id": item["entity_id"],
            })
    return out


# ---------------------------------------------------------------------------
# Trace-based checks: errors, conditions that never pass, mode: single
# ---------------------------------------------------------------------------

def _traces_for(snap: dict, entity_id: str) -> list[dict]:
    traces = snap.get("traces") or {}
    rows = traces.get(entity_id)
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return []
    rows = [r for r in rows if isinstance(r, dict)]
    rows.sort(key=lambda r: str((r.get("timestamp") or {}).get("start") or ""))
    return rows


def _trace_start(trace: dict) -> str:
    return str((trace.get("timestamp") or {}).get("start") or "")


def trace_error(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _automations(house) + _scripts(house):
        if not item["entity_id"]:
            continue
        rows = _traces_for(snap, item["entity_id"])
        if not rows:
            continue
        last = rows[-1]
        execution = str(last.get("script_execution") or "")
        error = last.get("error")
        if execution != "error" and not error:
            continue
        # Only the *latest* run counts: an error three runs ago that has
        # since run clean is history, not a finding.
        kind = "Script" if item["entity_id"].startswith("script.") else "Automation"
        step = str(last.get("last_step") or "")
        out.append({
            "text": f"{_label(kind, item)} failed the last time it ran",
            "detail": (f"On {when(_trace_start(last))}"
                       + (f", at step {step}" if step else "")
                       + (f": {str(error)[:300]}" if error else
                          ": the run ended in an error.")),
            "fix": "Open the automation's trace in Home Assistant and fix "
                   "the failing step.",
            "severity": "serious",
            "fixable": True,
            "entity_id": item["entity_id"],
        })
    return out


def condition_never_passes(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _automations(house):
        eid = item["entity_id"]
        if not eid:
            continue
        rows = _traces_for(snap, eid)
        if len(rows) < CONDITION_MIN_RUNS:
            continue
        if not all(str(r.get("script_execution") or "") == "failed_conditions"
                   for r in rows):
            continue
        state = house.states.get(eid) or {}
        if state.get("state") == "off":
            continue
        out.append({
            "text": f"{_label('Automation', item)} triggers but its "
                    "condition never passes",
            "detail": f"Every one of its last {len(rows)} runs (most "
                      f"recently {when(_trace_start(rows[-1]))}) stopped at "
                      "the condition. It is alive and cannot act.",
            "fix": "Check the condition against the entities it tests — "
                   "it is probably comparing against a state or value that "
                   "never occurs.",
            "severity": "warning",
            "fixable": True,
            "entity_id": eid,
        })
    return out


def already_running(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _automations(house):
        eid = item["entity_id"]
        if not eid:
            continue
        rows = _traces_for(snap, eid)
        recent = []
        for r in rows:
            if str(r.get("script_execution") or "") != "failed_single":
                continue
            age = age_days(_trace_start(r), now)
            # `age is not None`, not `age or`: a trace from this very second
            # ages 0.0, which is false, and would drop the freshest evidence.
            if age is not None and age <= 1:
                recent.append(r)
        if len(recent) < ALREADY_RUNNING_MIN:
            continue
        out.append({
            "text": f"{_label('Automation', item)} keeps being skipped "
                    "because it is already running",
            "detail": f"{len(recent)} triggers in the last day arrived "
                      "while a previous run was still going, and `mode: "
                      "single` drops them.",
            "fix": "If every trigger should be handled, set `mode: queued`; "
                   "if only the latest matters, `mode: restart`.",
            "severity": "warning",
            "fixable": True,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# auto.never_fired / auto.forgotten_off
# ---------------------------------------------------------------------------

def _trigger_platforms(config: dict) -> set[str]:
    kinds: set[str] = set()
    for trig in listify(config.get("triggers") or config.get("trigger")):
        if isinstance(trig, dict):
            kind = trig.get("trigger") or trig.get("platform")
            if isinstance(kind, str):
                kinds.add(kind)
    return kinds


def never_fired(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _automations(house):
        eid = item["entity_id"]
        state = house.states.get(eid) if eid else None
        if not state or state.get("state") != "on":
            continue
        attrs = state.get("attributes") or {}
        if attrs.get("last_triggered"):
            continue
        reg = house.registry.get(eid) or {}
        age = age_days(reg.get("created_at"), now)
        if age is None or age < NEVER_FIRED_DAYS:
            continue
        kinds = _trigger_platforms(item["config"])
        if kinds and kinds <= RARE_TRIGGERS:
            continue
        out.append({
            "text": f"{_label('Automation', item)} has never fired",
            "detail": f"Enabled since {when(reg.get('created_at'))} and its "
                      "trigger has not happened once.",
            "fix": "Check the trigger against what actually happens in the "
                   "house — or delete it if it is no longer wanted.",
            "severity": "info",
            "fixable": False,
            "entity_id": eid,
        })
    return out


def forgotten_off(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _automations(house):
        eid = item["entity_id"]
        state = house.states.get(eid) if eid else None
        if not state or state.get("state") != "off":
            continue
        age = age_days(state.get("last_changed"), now)
        if age is None or age < FORGOTTEN_OFF_DAYS:
            continue
        out.append({
            "text": f"{_label('Automation', item)} has been switched off "
                    "for a long time",
            "detail": f"Off since {when(state.get('last_changed'))}. "
                      "Automations get disabled to debug something and "
                      "forgotten.",
            "fix": "Turn it back on, or delete it if it is not coming back.",
            "severity": "info",
            "fixable": True,
            "entity_id": eid,
        })
    return out


# ---------------------------------------------------------------------------
# auto.duplicate / auto.blueprint_missing
# ---------------------------------------------------------------------------

def _signature(config: dict) -> str:
    body = {k: config.get(k) for k in
            ("triggers", "trigger", "conditions", "condition", "actions", "action")
            if config.get(k) is not None}
    return json.dumps(body, sort_keys=True, default=str)


def duplicate(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    seen: dict[str, dict] = {}
    out = []
    for item in _automations(house):
        sig = _signature(item["config"])
        if sig == "{}":
            continue
        first = seen.get(sig)
        if first is None:
            seen[sig] = item
            continue
        out.append({
            "text": f"{_label('Automation', item)} is a copy of "
                    f"'{first['alias']}'",
            "detail": "Same triggers, conditions and actions. Both run every "
                      "time, which doubles notifications and races on "
                      "anything that toggles.",
            "fix": "Delete one, or change what makes them different.",
            "severity": "info",
            "fixable": True,
            "entity_id": item["entity_id"],
        })
    return out


def blueprint_missing(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    base = snap.get("blueprints_dir") or ""
    if not base:
        return []
    out = []
    for kind, items, sub in (("Automation", _automations(house), "automation"),
                             ("Script", _scripts(house), "script")):
        for item in items:
            use = item["config"].get("use_blueprint")
            path = use.get("path") if isinstance(use, dict) else None
            if not isinstance(path, str) or not path:
                continue
            if os.path.isfile(os.path.join(base, sub, path)):
                continue
            out.append({
                "text": f"{_label(kind, item)} uses a blueprint that is "
                        "missing",
                "detail": f"blueprints/{sub}/{path} is not there. Home "
                          "Assistant reported this once at startup and has "
                          "been quiet since.",
                "fix": "Re-import the blueprint, or rebuild the automation "
                       "without it.",
                "severity": "serious",
                "fixable": False,
                "entity_id": item["entity_id"],
            })
    return out


# ---------------------------------------------------------------------------
# auto.trigger_unavailable — the automation is fine, its trigger is dead
# ---------------------------------------------------------------------------

# Trigger kinds that watch an entity's state. A `time` or `event` trigger
# names no entity, and a `device` trigger names one that HA resolves for
# itself.
_STATE_TRIGGERS = frozenset({"state", "numeric_state", "device"})


def _triggers(config: dict) -> list[dict]:
    """The trigger blocks, under either of the two keys HA accepts."""
    raw = config.get("triggers")
    if raw is None:
        raw = config.get("trigger")
    return [t for t in listify(raw) if isinstance(t, dict)]


def _trigger_kind(trig: dict) -> str:
    # 2024.10 renamed `platform:` to `trigger:` and kept both working.
    return str(trig.get("platform") or trig.get("trigger") or "").lower()


def trigger_unavailable(snap: dict, now: float) -> list[dict]:
    """An automation whose trigger watches an entity that is not reporting.

    This is the failure with no symptom: nothing errors, no trace is
    written, the automation simply never fires again — and the automation
    is switched on, so every list says it is fine. It is deliberately
    separate from `dev.unavailable`, which reports the *device*: that row
    says a sensor is down, this one says which automation stopped working
    because of it, and only the second answers "why did the hallway light
    stop coming on".
    """
    house = House(snap)
    out = []
    for item in _automations(house):
        state = (house.states.get(item["entity_id"]) or {}).get("state")
        if state == "off":
            continue  # a switched-off automation is auto.forgotten_off's
        broken: list[str] = []
        for trig in _triggers(item["config"]):
            if _trigger_kind(trig) not in _STATE_TRIGGERS:
                continue
            for eid in listify(trig.get("entity_id")):
                if not isinstance(eid, str) or "." not in eid:
                    continue
                st = house.states.get(eid)
                if st is None:
                    continue  # a missing entity is auto.dead_ref's
                if st.get("state") != "unavailable":
                    continue
                age = age_days(st.get("last_changed"), now)
                if age is not None and age >= TRIGGER_DEAD_DAYS:
                    broken.append(eid)
        if not broken:
            continue
        broken = sorted(set(broken))
        out.append({
            "text": f"{_label('Automation', item)} is triggered by an "
                    "entity that is not reporting",
            "detail": join_names([f"{house.name(e)} ({e})" for e in broken])
                      + " has been unavailable for days, so this automation "
                        "cannot fire. It is switched on, so nothing else "
                        "will tell you.",
            "fix": "Fix or replace the device behind that entity, or point "
                   "the trigger at one that works.",
            "severity": "serious",
            "fixable": True,
            "entity_id": item["entity_id"] or broken[0],
        })
    return out


# ---------------------------------------------------------------------------
# auto.overridden — an automation a person keeps undoing
# ---------------------------------------------------------------------------

# Three in a day. Once is a one-off, twice is a coincidence; three times
# in one day is somebody fighting their house, and it is the one finding
# on this list that nothing else in Home Assistant can see — the
# automation ran, nothing errored, and the light is off.
OVERRIDE_MIN = 3
# And three of WHAT. A count with nothing under it is not evidence: three
# undos of a rule that ran three times is a rule that is wrong for this
# house, and three undos of one that ran three hundred is a person having
# an unusual Tuesday. The first shipped without this and reported both
# identically, which is the shape of finding people learn to ignore.
OVERRIDE_RATE = 0.25
# A rate needs something to be a rate OF. Below this many runs the share
# is one or two events deciding it — 3 of 3 is 100% and says nothing more
# than the count already did — so the floor above carries it alone.
RATE_MIN_RUNS = 8

# Two automations undoing each other. Lower than OVERRIDE_MIN because
# nobody is choosing to do this: a person overriding a rule twice may
# simply have changed their mind, while two rules that have disagreed
# twice will disagree every time their triggers land in that order.
CONFLICT_MIN = 2


def _override_history() -> dict[str, list[dict]]:
    """The ledger, grouped. Empty on a dev checkout, or a fresh install.

    Read here rather than carried in the snapshot because it is the one
    thing on this check that is not about the window the snapshot covers
    — and a snapshot key that meant "unavailable" would stop
    `clear_resolved` clearing rows the acute half is perfectly able to
    answer for.
    """
    try:
        import override_ledger  # noqa: PLC0415 — the package stays
        # importable without the panel on the path; see checks/baseline.py
        return override_ledger.by_automation(override_ledger.load())
    except Exception as exc:  # noqa: BLE001 — no ledger is no history,
        # which is a real state on a fresh install and never a failure.
        log.debug("override ledger unreadable: %s", exc)
        return {}


def _override_pattern(rows: list[dict], now: float) -> dict | None:
    """The shape of a run of overrides, or None when there isn't one.

    ``now`` is the pass's own clock, not the wall clock: the recency gate
    that stops a fixed automation being reported for eight more weeks has
    to age from the same instant every other check in the pass does.
    """
    if not rows:
        return None
    try:
        import baselines  # noqa: PLC0415
        import override_ledger  # noqa: PLC0415

        tz, _name = baselines.house_timezone()
        return override_ledger.pattern(rows, tz, now)
    except Exception as exc:  # noqa: BLE001 — a pattern is an extra
        # sentence on a finding, never a reason to lose the finding.
        log.debug("override pattern unavailable: %s", exc)
        return None


def _pattern_sentence(shape: dict | None) -> str:
    """The half that teaches — *when* is the condition the rule is missing."""
    if not shape:
        return ""
    bits = []
    if "from_hour" in shape:
        bits.append(f"between {shape['from_hour']:02d}:00 and "
                    f"{shape['to_hour']:02d}:00")
    if shape.get("when_days"):
        bits.append(f"only on {shape['when_days']}")
    if not bits:
        return ""
    return (" Almost always " + " and ".join(bits)
            + f" ({shape['events']} times over {shape['days']} days).")


def _pattern_fix(shape: dict | None) -> str:
    if shape and ("from_hour" in shape or shape.get("when_days")):
        return ("The times you override it are the condition it is "
                "missing — add one that stands the automation down then. ")
    return ("Change the automation's condition so it does not run when you "
            "do not want it to; the times you overrode it are the "
            "condition. ")


def overridden(snap: dict, now: float) -> list[dict]:
    """Automations whose work a person has undone repeatedly today.

    Read off the action miner's overrides rather than recomputed here: the
    window, the "the state has to actually differ" rule and the one-undo-
    per-move rule all live in ``actions.find_overrides`` and there must
    not be a second copy of them.
    """
    mined = snap.get("actions") or {}
    groups = {}
    for o in mined.get("overrides") or []:
        if o.get("by_cause") != "automation":
            continue
        key = o.get("by") or o.get("by_name") or ""
        if not key:
            continue
        g = groups.setdefault(key, {"name": o.get("by_name") or key,
                                    "count": 0, "entities": [], "last": 0.0})
        g["count"] += 1
        if o["entity_id"] not in g["entities"]:
            g["entities"].append(o["entity_id"])
        g["last"] = max(g["last"], o.get("ts") or 0.0)

    moves = mined.get("moves") or {}
    history = _override_history()
    out = []

    # Two routes in, and the second is the one that matters most. The
    # acute case is a bad evening; the chronic one is somebody putting
    # the same thing back once a day for a month, which never reaches
    # three in any single day and so was invisible to the first version
    # of this check entirely.
    keys = sorted(set(groups) | set(history))
    for key in keys:
        g = groups.get(key)
        past = history.get(key) or []
        acute = bool(g) and g["count"] >= OVERRIDE_MIN
        if acute:
            # The denominator. An automation that ran often and was undone
            # a few times is a person; one undone a quarter of the time is
            # a rule that does not fit this house. Below RATE_MIN_RUNS the
            # share is one event either way, so the count stands alone.
            ran = int(moves.get(key) or 0)
            if ran >= RATE_MIN_RUNS and g["count"] / ran < OVERRIDE_RATE:
                acute = False
        shape = _override_pattern(past, now)
        if not acute and not shape:
            continue

        name = (g or {}).get("name") or (past[0].get("by_name") if past else key)
        entities = sorted((g or {}).get("entities")
                          or {r["entity_id"] for r in past if r.get("entity_id")})
        last = max((g or {}).get("last") or 0.0,
                   float(shape["last"]) if shape else 0.0)

        if acute:
            ran = int(moves.get(key) or 0)
            said = (f"{g['count']} of the {ran} times it acted"
                    if ran >= g["count"] else f"{g['count']} times")
            lead = f"{said} in the last day"
        else:
            lead = (f"{shape['events']} times across {shape['days']} "
                    "different days")

        out.append({
            # Stable across runs: every number in here moves, so they all
            # live in `detail` and the store can refresh them in place.
            "text": f"You keep undoing what '{name}' does",
            "detail": (lead + ", on " + join_names(entities)
                       + f". The last was {when(last)}."
                       + _pattern_sentence(shape)
                       + " The automation is working; it is doing the wrong "
                         "thing for this house."),
            "fix": (_pattern_fix(shape)
                    + "Ask brAIn to read the automation and the overrides "
                      "together if it is not obvious."),
            "severity": "info",
            "fixable": False,
            "entity_id": key if key.startswith("automation.") else "",
        })
    return out


def conflicting(snap: dict, now: float) -> list[dict]:
    """Two automations that keep undoing each other.

    The failure with two working automations in it. Both ran, neither
    errored, and the entity is in whichever state the later trigger left
    it — so which one "wins" depends on the order two triggers happened
    to fire in, which is not a thing anybody designed. No check that
    reads Core can see it and no trace shows it, because nothing went
    wrong in either run.

    Read off `actions.find_conflicts` rather than recomputed here, the
    same reason `overridden` reads `find_overrides`: the window, the
    must-differ rule and the one-undo-per-move rule have one home.
    """
    mined = snap.get("actions") or {}
    pairs: dict[tuple, dict] = {}
    for c in mined.get("conflicts") or []:
        first, second = c.get("first") or "", c.get("second") or ""
        if not first or not second:
            continue
        # A pair is a pair whichever way round it happened this time —
        # keyed unordered, or A-undoes-B and B-undoes-A count as two
        # separate disagreements between the same two rules.
        key = tuple(sorted((first, second)))
        names = {first: c.get("first_name") or first,
                 second: c.get("second_name") or second}
        p = pairs.setdefault(key, {"names": names, "count": 0,
                                   "entities": [], "last": 0.0})
        p["names"].update(names)
        p["count"] += 1
        if c["entity_id"] not in p["entities"]:
            p["entities"].append(c["entity_id"])
        p["last"] = max(p["last"], c.get("ts") or 0.0)

    out = []
    for key, p in sorted(pairs.items()):
        if p["count"] < CONFLICT_MIN:
            continue
        a, b = (p["names"].get(k, k) for k in key)
        out.append({
            "text": f"'{a}' and '{b}' keep undoing each other",
            "detail": (f"{p['count']} times in the last day, on "
                       + join_names(sorted(p["entities"]))
                       + f". The last was {when(p['last'])}. Both ran and "
                         "neither failed — which one wins depends on the "
                         "order their triggers happen to fire in, so the "
                         "result is different from one day to the next."),
            "fix": ("Decide which one should own "
                    + join_names(sorted(p["entities"]))
                    + " and give the other a condition that stands down, "
                      "or merge them into one automation with the "
                      "decision written out."),
            "severity": "warning",
            "fixable": False,
            "entity_id": key[0] if key[0].startswith("automation.") else "",
        })
    return out


CHECKS = [
    {"id": "auto.dead_ref", "title": "Automations naming missing entities",
     "needs": ("states", "registry", "automations"), "run": dead_ref},
    {"id": "auto.trigger_unavailable",
     "title": "Automations whose trigger is not reporting",
     "needs": ("states", "registry", "automations"), "run": trigger_unavailable},
    {"id": "auto.dead_service", "title": "Automations calling missing services",
     "needs": ("services", "automations"), "run": dead_service},
    {"id": "auto.trace_error", "title": "Automations whose last run failed",
     "needs": ("registry", "automations", "traces"), "run": trace_error},
    {"id": "auto.condition_never_passes",
     "title": "Automations whose condition never passes",
     "needs": ("states", "registry", "automations", "traces"),
     "run": condition_never_passes},
    {"id": "auto.already_running",
     "title": "Automations dropping triggers on mode: single",
     "needs": ("registry", "automations", "traces"), "run": already_running},
    {"id": "auto.never_fired", "title": "Automations that have never fired",
     "needs": ("states", "registry", "automations"), "run": never_fired},
    {"id": "auto.forgotten_off", "title": "Automations left switched off",
     "needs": ("states", "registry", "automations"), "run": forgotten_off},
    {"id": "auto.duplicate", "title": "Duplicate automations",
     "needs": ("registry", "automations"), "run": duplicate},
    {"id": "auto.blueprint_missing", "title": "Automations on a missing blueprint",
     "needs": ("registry", "automations"), "run": blueprint_missing},
    {"id": "auto.conflict",
     "title": "Automations undoing each other",
     "needs": ("actions",), "run": conflicting},
    {"id": "auto.overridden", "title": "Automations a person keeps undoing",
     "needs": ("actions",), "run": overridden},
]

__all__ = ["CHECKS", "DAY"]
