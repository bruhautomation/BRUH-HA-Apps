"""Automation, script and scene checks.

What breaks an automation, in the order people hit it: it names something
that is gone, it calls a service that is gone, it errors when it runs, it
runs and never gets past its own condition, it fights itself over `mode:
single`, it was switched off to debug and forgotten, it never fires at all,
or it is a copy of another one.

All of these read the config files (``automations.yaml`` and friends), the
entity registry, the automation entities' state and the traces Home
Assistant is holding right now (``trace/list`` over the WebSocket — see
``snapshot.live_traces``). None of them need the model.
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
            subject = item["entity_id"] or dead[0]
            if not house.should_report(subject, "auto.dead_ref"):
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
                "entity_id": subject,
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
            if not house.should_report(item["entity_id"], "auto.dead_service"):
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

def _traced(house: House) -> list[dict]:
    """Every automation and script Core is running, keyed the way it traces.

    Read off the STATES rather than `automations.yaml`, for two reasons.
    Core keys a trace `automation.<config id>`, and the config id is on
    every automation's state as its `id` attribute — so a lookup by entity
    id, which is what this used to do, finds nothing for any automation
    whose id is not its slug, and the UI writes a millisecond timestamp.
    And an automation in a package or an `!include_dir_merge_list` split
    is a running automation with traces like any other, which a walk of
    one file cannot see. The YAML's alias is used where the file has the
    entry, because it is what the person typed; otherwise the state's own
    friendly name.

    A script's trace key is its `unique_id` — the key it has in
    `scripts.yaml` — read off the registry where the registry has it and
    off the object id otherwise, which is what it is at creation.
    """
    aliases = {}
    for cfg in house.snap.get("automations") or []:
        if isinstance(cfg, dict) and cfg.get("id") is not None:
            aliases[str(cfg["id"])] = str(cfg.get("alias") or "")
    out = []
    for eid, st in sorted(house.states.items()):
        attrs = st.get("attributes") or {}
        if eid.startswith("automation."):
            cid = attrs.get("id")
            if cid is None or str(cid) == "":
                continue  # no id, no trace anybody can find
            cid = str(cid)
            out.append({"key": f"automation.{cid}", "entity_id": eid,
                        "kind": "Automation",
                        "alias": aliases.get(cid) or str(
                            attrs.get("friendly_name") or eid)})
        elif eid.startswith("script."):
            reg = house.registry.get(eid) or {}
            uid = str(reg.get("unique_id") or eid.split(".", 1)[1])
            out.append({"key": f"script.{uid}", "entity_id": eid,
                        "kind": "Script",
                        "alias": str(attrs.get("friendly_name") or eid)})
    return out


def _short(row: dict) -> dict:
    """One run as Core's `short_dict`, whichever wrapper it arrived in.

    `trace/list` answers with the short dict itself. What Core STORES is
    `BaseTrace.as_dict()` — `{"extended_dict": {...}, "short_dict":
    {...}}` — and a row in that shape read at the top level has no
    `script_execution`, no `error` and no `timestamp`, which is how three
    checks were dead on every install while their tests passed on a
    flattened guess. A snapshot captured from either is read the same.
    """
    inner = row.get("short_dict")
    if isinstance(inner, dict):
        return inner
    inner = row.get("extended_dict")
    if isinstance(inner, dict):
        return inner
    return row


def _traces_for(snap: dict, key: str) -> list[dict]:
    """The runs Core holds for one `domain.item_id` key, oldest first.

    `not_triggered` rows are not runs (see `snapshot.live_traces`), and a
    run still `running` has no verdict yet; both are dropped here as well
    as at the fetch, so a snapshot captured by hand reads the same.
    """
    traces = snap.get("traces") or {}
    rows = traces.get(key)
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return []
    rows = [_short(r) for r in rows if isinstance(r, dict)]
    rows = [r for r in rows if not r.get("not_triggered")
            and r.get("state") != "running"]
    rows.sort(key=_trace_start)
    return rows


def _trace_start(trace: dict) -> str:
    return str((trace.get("timestamp") or {}).get("start") or "")


def _label_of(item: dict) -> str:
    return f"{item['kind']} '{item['alias']}'"


def trace_error(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _traced(house):
        rows = _traces_for(snap, item["key"])
        if not rows:
            continue
        last = rows[-1]
        execution = str(last.get("script_execution") or "")
        error = last.get("error")
        if execution != "error" and not error:
            continue
        if not house.should_report(item["entity_id"], "auto.trace_error"):
            continue
        # Only the *latest* run counts: an error three runs ago that has
        # since run clean is history, not a finding.
        step = str(last.get("last_step") or "")
        out.append({
            "text": f"{_label_of(item)} failed the last time it ran",
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


# Core keeps five traces per automation by default, so a motion-triggered
# rule with a night-only condition fills its whole window with daytime
# `failed_conditions` runs in an hour — every one of them true, and the
# automation working exactly as written. What says the condition really
# never lets it act is `last_triggered`, which Core sets only once the
# conditions have PASSED and the actions run (`action_script.
# last_triggered`). A rule whose actions ran inside this window is a rule
# whose condition passes; one quiet for longer than it is worth a sentence.
CONDITION_PASSED_DAYS = 14


def condition_never_passes(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _traced(house):
        if item["kind"] != "Automation":
            continue
        eid = item["entity_id"]
        rows = _traces_for(snap, item["key"])
        if len(rows) < CONDITION_MIN_RUNS:
            continue
        if not all(str(r.get("script_execution") or "") == "failed_conditions"
                   for r in rows):
            continue
        state = house.states.get(eid) or {}
        if state.get("state") == "off":
            continue
        last_ran = (state.get("attributes") or {}).get("last_triggered")
        ran_age = age_days(last_ran, now) if last_ran else None
        if ran_age is not None and ran_age < CONDITION_PASSED_DAYS:
            continue
        if not house.should_report(eid, "auto.condition_never_passes"):
            continue
        out.append({
            "text": f"{_label_of(item)} triggers but its condition never "
                    "passes",
            "detail": f"Every one of its last {len(rows)} runs (most "
                      f"recently {when(_trace_start(rows[-1]))}) stopped at "
                      "the condition, and "
                      + (f"its actions last ran on {when(last_ran)}."
                         if last_ran else "its actions have never run.")
                      + " It is alive and cannot act.",
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
    for item in _traced(house):
        if item["kind"] != "Automation":
            continue
        eid = item["entity_id"]
        rows = _traces_for(snap, item["key"])
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
        if not house.should_report(eid, "auto.already_running"):
            continue
        out.append({
            "text": f"{_label_of(item)} keeps being skipped "
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


# brAIn's own automations — the playbooks, an accepted routine, an armed
# intent. `automation_writer.ID_PREFIX`, spelled here because this package
# stays importable without the panel (a test holds the two together).
BRAIN_PREFIX = "brain_"

# What an alarm automation watches. A smoke, gas, leak or CO response is
# DESIGNED never to fire in a healthy house, so "has never fired … or
# delete it" about one is the check telling somebody to remove the thing
# that would have woken them — and brAIn's own smoke, leak and freeze
# playbooks were exactly that, thirty days after somebody accepted them.
# By device class rather than by name: a detector declares what it is.
SAFETY_CLASSES = frozenset({"smoke", "gas", "moisture", "carbon_monoxide",
                            "safety"})
# A binary sensor's device trigger names the condition, not the class
# (`homeassistant/components/binary_sensor/device_trigger.py`): these are
# the "it went off" halves of the five classes above.
SAFETY_DEVICE_TRIGGERS = frozenset({"smoke", "gas", "moist", "co", "unsafe"})
# An alarm panel going to `triggered` is the same claim about a whole house.
SAFETY_DOMAINS = frozenset({"alarm_control_panel"})


def _resolve(house: House, ref: str) -> str:
    """An entity id, from either an entity id or a registry entry's `id`.

    A device trigger names its entity by the registry's own uuid since
    2023.x (`entity_id: 6a1b…`), which reads as an entity that does not
    exist if it is looked up as one.
    """
    if ref in house.states or ref in house.registry:
        return ref
    for row in house.entities:
        if str(row.get("id") or "") == ref and row.get("entity_id"):
            return str(row["entity_id"])
    return ref


def _watched(house: House, trig: dict) -> list[str]:
    """The entity ids one trigger names, under every key HA reads one from.

    `entity_id:` at the top of a `state`/`numeric_state`/`device` trigger,
    and `target: {entity_id: …}` — which is where HA 2026.7's
    purpose-specific triggers (`trigger: light.turned_on`, the editor's
    default) put it. An area, floor, label or device under `target:` is
    not resolved here: none of the callers would say anything true about
    "every light in the kitchen" from one of them.
    """
    out: list[str] = []
    raw = (trig.get("entity_id")
           if _trigger_kind(trig) in _STATE_TRIGGERS else None)
    target = trig.get("target")
    sources = [raw]
    if isinstance(target, dict):
        sources.append(target.get("entity_id"))
    for source in sources:
        for ref in listify(source):
            if isinstance(ref, str) and ref.strip():
                eid = _resolve(house, ref.strip())
                if eid not in out:
                    out.append(eid)
    return out


def _guards_safety(house: House, config: dict) -> bool:
    """Whether this automation answers a smoke, gas, leak or CO alarm."""
    for trig in _triggers(config):
        if (_trigger_kind(trig) == "device"
                and str(trig.get("domain") or "") == "binary_sensor"
                and str(trig.get("type") or "") in SAFETY_DEVICE_TRIGGERS):
            return True
        for eid in _watched(house, trig):
            if eid.split(".", 1)[0] in SAFETY_DOMAINS:
                return True
            attrs = (house.states.get(eid) or {}).get("attributes") or {}
            reg = house.registry.get(eid) or {}
            cls = (attrs.get("device_class") or reg.get("device_class")
                   or reg.get("original_device_class"))
            if str(cls or "") in SAFETY_CLASSES:
                return True
    return False


def never_fired(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    out = []
    for item in _automations(house):
        eid = item["entity_id"]
        state = house.states.get(eid) if eid else None
        if not state or state.get("state") != "on":
            continue
        # brAIn's own: a playbook is meant to wait for the bad night, and
        # every other one was accepted on a card that already said what it
        # was for. brAIn advising its own removal is two halves of one
        # add-on arguing in front of somebody.
        if item["id"].startswith(BRAIN_PREFIX):
            continue
        if _guards_safety(house, item["config"]):
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
        if not house.should_report(eid, "auto.never_fired"):
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
        if not house.should_report(eid, "auto.forgotten_off"):
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
        if not house.should_report(item["entity_id"], "auto.duplicate"):
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
            if not house.should_report(item["entity_id"],
                                       "auto.blueprint_missing"):
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

# Trigger kinds whose top-level `entity_id` is the entity they watch. A
# `time` or `event` trigger names no entity, and a `device` trigger names
# one by its registry id (see `_resolve`). HA 2026.7's purpose-specific
# triggers (`light.turned_on`) name theirs under `target:` instead, which
# `_watched` reads for every kind.
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
            for eid in _watched(house, trig):
                if "." not in eid:
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
        subject = item["entity_id"] or broken[0]
        if not house.should_report(subject, "auto.trigger_unavailable"):
            continue
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
            "entity_id": subject,
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
# A second rule landing this soon after the first is a RACE: both answered
# the same moment (two automations on one trigger), and which one wins is
# the order Core happened to run them in. Anything slower in one direction
# only is a sequence somebody built — see `conflicting`.
RACE_S = 5.0


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
    house = House(snap)
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

        subject = key if key.startswith("automation.") else ""
        if subject and not house.should_report(subject, "auto.overridden"):
            continue
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
            "entity_id": subject,
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

    **A sequence is not a fight, and it was most of what this reported.**
    "Motion turns the hall light on" and "no motion for two minutes turns
    it off" put the light back every single time, inside the window, in
    different states, from different rules — and that is two automations
    doing exactly what they were written to do. So were sunset-on and
    bedtime-off, and a fan that another rule stops after ten minutes. The
    producer scorecard read 3 of 4 marked Wrong, which is the Findings tab
    saying this rule is wrong about this house. What makes a disagreement
    is that NEITHER rule reliably has the last word: the pair has undone
    each other in **both** directions, or the second answered within
    `RACE_S` — the same trigger reaching two rules, where which one wins is
    the order Core ran them in. A one-way pair slower than that is a
    sequence somebody built and says nothing, whatever the count.
    """
    mined = snap.get("actions") or {}
    pairs: dict[tuple, dict] = {}
    for c in mined.get("conflicts") or []:
        first, second = c.get("first") or "", c.get("second") or ""
        if not first or not second:
            continue
        after = c.get("after_s")
        raced = after is not None and float(after) <= RACE_S
        # A pair is a pair whichever way round it happened this time —
        # keyed unordered, or A-undoes-B and B-undoes-A count as two
        # separate disagreements between the same two rules.
        key = tuple(sorted((first, second)))
        names = {first: c.get("first_name") or first,
                 second: c.get("second_name") or second}
        p = pairs.setdefault(key, {"names": names, "count": 0,
                                   "entities": [], "last": 0.0,
                                   "ways": set(), "raced": False})
        p["names"].update(names)
        p["count"] += 1
        p["ways"].add((first, second))
        p["raced"] = p["raced"] or raced
        if c["entity_id"] not in p["entities"]:
            p["entities"].append(c["entity_id"])
        p["last"] = max(p["last"], c.get("ts") or 0.0)

    house = House(snap)
    out = []
    for key, p in sorted(pairs.items()):
        if p["count"] < CONFLICT_MIN:
            continue
        if len(p["ways"]) < 2 and not p["raced"]:
            continue
        subject = key[0] if key[0].startswith("automation.") else ""
        if subject and not house.should_report(subject, "auto.conflict"):
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
            "entity_id": subject,
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
     "needs": ("states", "traces"), "run": trace_error},
    {"id": "auto.condition_never_passes",
     "title": "Automations whose condition never passes",
     "needs": ("states", "traces"), "run": condition_never_passes},
    {"id": "auto.already_running",
     "title": "Automations dropping triggers on mode: single",
     "needs": ("states", "traces"), "run": already_running},
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
