"""The changes a fix plan may make, as typed operations, and what each touches.

A plan used to be a list of sentences, and the run that carried it out
held every tool the add-on has — so what a person consented to was prose,
and what happened was whatever a model with a shell decided that prose
meant. This module is the vocabulary that turns the prose into a
contract.

**Six operations, a closed set** (`OP_KINDS`). Five are deterministic and
the panel performs them itself, without a model: change one automation in
place (`edit_automation`, through `automation_writer.replace_entry`, the
byte splice with its snapshot), reload one config domain (`reload`), call
one service on named entities (`call_service`), rename an entity
(`rename_entity`) and move an entity or device to an area (`set_area`).
The sixth, `agentic`, is what is left when a change cannot be said as one
of those — and it is the only one that spawns a tool-enabled run, held to
the calls and files the operation lists (`contract_for`), with the MCP
chokepoint refusing any call off it.

**Everything is validated in code, and a plan with an operation this
cannot read is refused whole** (`clean_ops`). An op that is silently
dropped is a plan whose steps describe a change that will not be made —
the half-applied fix nobody approved — so one bad op makes the whole plan
unapprovable, `shadow`'s rule that a refusal is never trimmed. The
checks are deliberately narrow: entities by id only (an area, device,
label or floor target is refused, because the contract has to be able to
name what it allows), a deterministic `call_service` only on its own
domain's entities, never a domain that administers Home Assistant, and
never a service that lowers security (unlocking, disarming) — none of
those is ever a fix a card should be able to make on a press.

**`verify_by` is what the follow-up looks will check** (`VERIFY_KINDS`):
an automation's trace inside a window, an entity's state, or the finding's
own check no longer reporting it. An unreadable one is dropped to None,
which is not a refusal: the plan is still a plan, and the follow-up falls
back to a cheap gated look — whose "could not check" never counts as the
change having held.

Stdlib plus `automation_writer` (for the protected-entity question, asked
the same way the writer asks it), so the suite imports it without the
add-on runtime.
"""
from __future__ import annotations

import json
import re

import automation_writer
import textclip

OP_KINDS = ("edit_automation", "reload", "call_service", "rename_entity",
            "set_area", "agentic")
# The ops the panel performs itself. `agentic` is the one that is not.
DETERMINISTIC = frozenset(OP_KINDS) - {"agentic"}
VERIFY_KINDS = ("trace_within_h", "state_is", "finding_clears")

# Domains whose own `reload` service re-reads YAML a fix may have edited.
# A domain off this list has no reload, or one that is a decision about the
# whole house (`homeassistant.reload_all`) rather than about one file.
RELOADABLE = frozenset({
    "automation", "script", "scene", "group", "input_boolean",
    "input_number", "input_select", "input_text", "input_datetime",
    "input_button", "timer", "counter", "schedule", "template", "zone",
    "person",
})
# Domains a fix may never call a service in, deterministic or agentic:
# they administer Home Assistant itself, run arbitrary commands, or are
# brAIn's own registry tools — each of which has its own typed op or is
# not a fix at all.
REFUSED_DOMAINS = frozenset({
    "homeassistant", "hassio", "update", "recorder", "shell_command",
    "backup", "brain", "system_log", "logger", "python_script", "pyscript",
    "rest_command", "command_line", "frontend", "lovelace", "auth",
})
# Services that make a house less secure. A fix that needs one is a fix
# a person makes with their own hands.
SECURITY_REDUCING = frozenset({
    ("lock", "unlock"), ("lock", "open"),
    ("alarm_control_panel", "alarm_disarm"),
})

MAX_OPS = 8
MAX_ENTITIES = 10
MAX_FILES = 6
MAX_INSTRUCTION = 1000
MAX_CONFIG_BYTES = 20_000
MAX_EFFECT = 300
MAX_VERIFY_HOURS = 720
NAME_MAX = 100

ENTITY_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")
CONFIG_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
NAME_RE = re.compile(r"^[a-z0-9_]+$")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SCOPE_KEYS = ("area_id", "device_id", "label_id", "floor_id")


class Refused(ValueError):
    """An op this module will not accept. The message is the sentence."""


def _entities(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise Refused("an entity list was not a list of entity ids")
    out = []
    for item in value:
        eid = str(item or "").strip().lower()
        if not ENTITY_RE.match(eid):
            raise Refused(f"`{str(item)[:60]}` is not an entity id")
        if eid not in out:
            out.append(eid)
    if len(out) > MAX_ENTITIES:
        raise Refused(f"an operation may name at most {MAX_ENTITIES} entities")
    return out


def _service_pair(domain, service) -> tuple[str, str]:
    d = str(domain or "").strip().lower()
    s = str(service or "").strip().lower()
    if not (NAME_RE.match(d) and NAME_RE.match(s)):
        raise Refused(f"`{d}.{s}` is not a service name")
    if d in REFUSED_DOMAINS:
        raise Refused(f"a fix may not call {d} services — those run Home "
                      "Assistant itself rather than fixing one thing in it")
    if (d, s) in SECURITY_REDUCING:
        raise Refused(f"{d}.{s} makes the house less secure, so it is never "
                      "a change brAIn makes on a press")
    return d, s


def _no_scope(*blocks) -> None:
    for block in blocks:
        if isinstance(block, dict):
            for key in SCOPE_KEYS:
                if block.get(key):
                    raise Refused(
                        f"it targets by {key.replace('_id', '')}; a fix names "
                        "the entities it changes one by one, so what it may "
                        "touch can be checked")


def _clean_call(raw: dict) -> dict:
    domain, service = _service_pair(raw.get("domain"), raw.get("service"))
    target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
    _no_scope(target, data)
    named = []
    for source in (target.get("entity_id"), data.get("entity_id"),
                   raw.get("entity_id"), raw.get("entities")):
        if source:
            named += _entities(source)
    named = list(dict.fromkeys(named))
    if len(named) > MAX_ENTITIES:
        raise Refused(f"an operation may name at most {MAX_ENTITIES} entities")
    data = {k: v for k, v in data.items() if k != "entity_id"}
    try:
        if len(json.dumps(data)) > 4000:
            raise Refused("the service data is too large to be a fix")
    except (TypeError, ValueError):
        raise Refused("the service data is not plain JSON") from None
    return {"domain": domain, "service": service, "entities": named,
            "data": data}


def _clean_files(value) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise Refused("the files an agentic step may edit must be a list")
    out = []
    for item in value:
        path = str(item or "").strip()
        if not path.startswith("/config/") or "/.." in path or "\x00" in path:
            raise Refused(f"`{path[:80]}` is not a file under /config")
        name = path.rsplit("/", 1)[-1]
        if name == "secrets.yaml" or "/.storage/" in path:
            raise Refused(f"{path} holds credentials or Home Assistant's own "
                          "storage, which no fix edits")
        if path not in out:
            out.append(path)
    if len(out) > MAX_FILES:
        raise Refused(f"an agentic step may edit at most {MAX_FILES} files")
    return out


def clean_op(raw) -> dict:
    """One op, validated and normalised, or `Refused` with the reason."""
    if not isinstance(raw, dict):
        raise Refused("an operation was not an object")
    kind = str(raw.get("op") or "").strip()
    if kind not in OP_KINDS:
        raise Refused(f"`{kind[:40]}` is not an operation brAIn can carry out")

    if kind == "edit_automation":
        entry_id = str(raw.get("id") or "").strip()
        if not CONFIG_ID_RE.match(entry_id):
            raise Refused("an automation edit has to name the automation's "
                          "own config id")
        config = raw.get("new_config")
        if not isinstance(config, dict):
            raise Refused(f"the edit to {entry_id} carries no new config")
        config = dict(config)
        if str(config.get("id") or entry_id) != entry_id:
            raise Refused(f"the new config for {entry_id} names a different id")
        config["id"] = entry_id
        if not (config.get("trigger") or config.get("triggers")):
            raise Refused(f"the new config for {entry_id} has no trigger")
        if not (config.get("action") or config.get("actions")):
            raise Refused(f"the new config for {entry_id} has no action")
        try:
            if len(json.dumps(config)) > MAX_CONFIG_BYTES:
                raise Refused(f"the new config for {entry_id} is too large")
        except (TypeError, ValueError):
            raise Refused(f"the new config for {entry_id} is not plain "
                          "data") from None
        return {"op": kind, "id": entry_id, "new_config": config}

    if kind == "reload":
        domain = str(raw.get("domain") or "").strip().lower()
        if domain not in RELOADABLE:
            raise Refused(f"`{domain[:40]}` is not a domain a fix may reload")
        return {"op": kind, "domain": domain}

    if kind == "call_service":
        call = _clean_call(raw)
        if not call["entities"]:
            raise Refused(f"{call['domain']}.{call['service']} names no "
                          "entity, and a fix changes named things")
        wrong = [e for e in call["entities"]
                 if e.split(".", 1)[0] != call["domain"]]
        if wrong:
            raise Refused(f"{call['domain']}.{call['service']} may only act "
                          f"on {call['domain']} entities, not {wrong[0]}")
        return {"op": kind, **call}

    if kind == "rename_entity":
        eid = _entities(raw.get("entity_id"))
        if len(eid) != 1:
            raise Refused("a rename names exactly one entity")
        out = {"op": kind, "entity_id": eid[0]}
        name = str(raw.get("name") or "").strip()
        if name:
            out["name"] = name[:NAME_MAX]
        new_id = str(raw.get("new_entity_id") or "").strip().lower()
        if new_id:
            if not ENTITY_RE.match(new_id):
                raise Refused(f"`{new_id[:60]}` is not an entity id")
            if new_id.split(".", 1)[0] != eid[0].split(".", 1)[0]:
                raise Refused("an entity cannot be renamed into another domain")
            out["new_entity_id"] = new_id
        if len(out) == 2:
            raise Refused(f"the rename of {eid[0]} gives no new name")
        return out

    if kind == "set_area":
        area = str(raw.get("area_id") or "").strip().lower()
        if not NAME_RE.match(area):
            raise Refused("moving something to an area names the area's id")
        if raw.get("device_id"):
            device = str(raw["device_id"]).strip()
            if not DEVICE_ID_RE.match(device):
                raise Refused("that is not a device id")
            return {"op": kind, "device_id": device, "area_id": area}
        eid = _entities(raw.get("entity_id"))
        if len(eid) != 1:
            raise Refused("an area move names one entity or one device")
        return {"op": kind, "entity_id": eid[0], "area_id": area}

    # agentic
    instruction = " ".join(str(raw.get("instruction") or "").split())
    if not instruction:
        raise Refused("an agentic step has to say what it is to do")
    calls = []
    for item in raw.get("calls") or []:
        if not isinstance(item, dict):
            raise Refused("an agentic step's calls must be objects")
        call = _clean_call(item)
        calls.append({"domain": call["domain"], "service": call["service"],
                      "entities": call["entities"]})
    files = _clean_files(raw.get("files"))
    if not calls and not files:
        raise Refused("an agentic step has to list the calls it may make or "
                      "the files it may edit — with neither it can change "
                      "nothing, and with an open list it could change "
                      "anything")
    return {"op": kind, "instruction": instruction[:MAX_INSTRUCTION],
            "calls": calls, "files": files}


def clean_ops(raw) -> list[dict]:
    """Every op, validated; `Refused` for the first that is not acceptable."""
    if not isinstance(raw, list) or not raw:
        raise Refused("the plan names no operations brAIn can check")
    if len(raw) > MAX_OPS:
        raise Refused(f"a fix has at most {MAX_OPS} operations")
    return [clean_op(item) for item in raw]


def clean_verify(raw) -> dict | None:
    """A checkable condition, or None — never a refusal of the plan."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()

    def hours(key, default):
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError):
            return None
        if not 0 < value <= MAX_VERIFY_HOURS:
            return None
        return round(value, 2)

    if kind == "trace_within_h":
        auto = str(raw.get("automation") or "").strip().lower()
        h = hours("hours", 48)
        if not (ENTITY_RE.match(auto) and auto.startswith("automation.")) \
                or h is None:
            return None
        return {"kind": kind, "automation": auto, "hours": h}
    if kind == "state_is":
        eid = str(raw.get("entity") or "").strip().lower()
        state = str(raw.get("state") or "").strip()
        h = hours("within_h", 24)
        if not ENTITY_RE.match(eid) or not state or h is None:
            return None
        return {"kind": kind, "entity": eid, "state": state[:64], "within_h": h}
    if kind == "finding_clears":
        h = hours("hours", 24)
        return None if h is None else {"kind": kind, "hours": h}
    return None


def entities_named(ops: list[dict]) -> list[str]:
    """Every entity an op set names — what the protected list is asked of."""
    out = []
    for op in ops or []:
        if op.get("op") == "call_service":
            out += op.get("entities") or []
        elif op.get("op") in ("rename_entity", "set_area"):
            if op.get("entity_id"):
                out.append(op["entity_id"])
            if op.get("new_entity_id"):
                out.append(op["new_entity_id"])
        elif op.get("op") == "agentic":
            for call in op.get("calls") or []:
                out += call.get("entities") or []
    return list(dict.fromkeys(out))


def protected_refusal(ops: list[dict], patterns, honeytokens=()) -> str | None:
    """Why this op set may not be approved, asked the writer's way, or None.

    The MCP chokepoint asks again at call time and `replace_entry` asks of
    the new automation at write time; this is the ask at the PLAN, so a card
    never offers an Apply that something downstream will refuse.
    """
    patterns = automation_writer.protected_patterns(patterns)
    tokens = {str(t).lower() for t in honeytokens or ()}
    for eid in entities_named(ops):
        if eid in tokens:
            return f"{eid} is brAIn's tripwire entity, which no fix acts on"
        if automation_writer.is_protected(eid, patterns):
            return (f"{eid} is on the protected entities list, so brAIn will "
                    "not change it")
    for op in ops or []:
        if op.get("op") == "edit_automation":
            why = automation_writer._protected_refusal(op["new_config"], patterns)
            if why:
                return why
            for eid in shadow_entities(op["new_config"]):
                if eid in tokens:
                    return (f"the edited automation would act on {eid}, "
                            "brAIn's tripwire entity")
        if op.get("op") == "set_area" and op.get("device_id") and patterns:
            # A device's area moves every entity on it, and which those are
            # is the registry's answer, not this op's.
            return ("moving a whole device to another area cannot be checked "
                    "against the protected list from the plan; move the "
                    "entities by name instead")
    return None


def shadow_entities(config: dict) -> list[str]:
    """The entities an automation's actions name, through shadow's reader."""
    import shadow  # noqa: PLC0415 — panel-local, only needed here

    out = []
    for call in shadow.would_do(config):
        entity = call.get("entity_id")
        for eid in ([entity] if isinstance(entity, str) else list(entity or [])):
            if isinstance(eid, str):
                out.append(eid.strip().lower())
    return out


def contract_for(ops: list[dict], contract_id: str) -> dict:
    """What a tool-enabled run carrying the `agentic` ops may do.

    Only the agentic ops' own lists: the deterministic ops are carried out
    by the panel, and a contract that also allowed them would let the run
    make each change a second time.
    """
    calls, files = [], []
    for op in ops or []:
        if op.get("op") != "agentic":
            continue
        for call in op.get("calls") or []:
            row = {"domain": call["domain"], "service": call["service"],
                   "entities": list(call.get("entities") or [])}
            if row not in calls:
                calls.append(row)
        for path in op.get("files") or []:
            if path not in files:
                files.append(path)
    return {"id": contract_id, "calls": calls, "files": files}


def has_agentic(ops: list[dict]) -> bool:
    return any(op.get("op") == "agentic" for op in ops or [])


def describe(op: dict) -> str:
    """One op in the words a person consents to."""
    kind = op.get("op")
    if kind == "edit_automation":
        alias = str((op.get("new_config") or {}).get("alias") or "")
        return (f"Change the automation {op['id']}"
                + (f" (“{alias}”)" if alias else "")
                + " — the exact change is shown below")
    if kind == "reload":
        return f"Reload Home Assistant's {op['domain']} configuration"
    if kind == "call_service":
        data = op.get("data") or {}
        extra = (" with " + ", ".join(f"{k}={json.dumps(v)}" for k, v in
                                      list(data.items())[:4])) if data else ""
        return (f"Call {op['domain']}.{op['service']} on "
                f"{', '.join(op['entities'])}{extra}")
    if kind == "rename_entity":
        parts = []
        if op.get("name"):
            parts.append(f"call it “{op['name']}”")
        if op.get("new_entity_id"):
            parts.append(f"change its id to {op['new_entity_id']}")
        return f"Rename {op['entity_id']}: " + " and ".join(parts)
    if kind == "set_area":
        what = op.get("entity_id") or f"device {op.get('device_id')}"
        return f"Move {what} to the area {op['area_id']}"
    if kind == "agentic":
        reach = []
        if op.get("calls"):
            reach.append("may call " + "; ".join(
                f"{c['domain']}.{c['service']}"
                + (f" on {', '.join(c['entities'])}" if c["entities"] else "")
                for c in op["calls"]))
        if op.get("files"):
            reach.append("may edit " + ", ".join(op["files"]))
        return (f"Have brAIn carry out: {op['instruction']} — it "
                + " and ".join(reach) + ", and nothing else")
    return str(kind)


def verify_sentence(verify: dict | None) -> str:
    """How brAIn will check the change did its job, in words."""
    if not verify:
        return ("brAIn will look again after a day, a week and a month to "
                "see whether the problem came back.")
    kind = verify.get("kind")
    if kind == "trace_within_h":
        return (f"brAIn will check that {verify['automation']} runs within "
                f"{_hours(verify['hours'])}, then look again after a week and "
                "a month.")
    if kind == "state_is":
        return (f"brAIn will check that {verify['entity']} reads "
                f"“{verify['state']}”, after a day, a week and a month.")
    if kind == "finding_clears":
        return ("brAIn will run the check that found this again after a day, "
                "a week and a month, and reopen it if it comes back.")
    return ""


def _hours(h: float) -> str:
    if h >= 48 and h % 24 == 0:
        return f"{int(h // 24)} days"
    return f"{int(h) if float(h).is_integer() else h} hours"


def clean_stored(value) -> dict:
    """The typed half of a stored plan, re-validated on every read.

    A plan on disk is re-checked rather than trusted, because Apply reads it
    off the row: an op that no longer validates (the vocabulary narrowed in
    a later release) makes the plan unapprovable rather than reaching the
    house in a shape nothing checked.
    """
    if not isinstance(value, dict):
        return {}
    if not value.get("ops"):
        # A refusal recorded on an earlier read stays recorded: the reason
        # a plan cannot be applied is the sentence the card shows.
        why = value.get("ops_refused")
        return {"ops_refused": textclip.clip(why, 300)} if isinstance(why, str) and why \
            else {}
    try:
        ops = clean_ops(value.get("ops"))
    except Refused as exc:
        return {"ops": [], "ops_refused": textclip.clip(str(exc), 300)}
    out = {"ops": ops,
           "expected_effect": textclip.clip(
               str(value.get("expected_effect") or "").strip(), MAX_EFFECT),
           "verify_by": clean_verify(value.get("verify_by"))}
    # Derived on every read, never stored as prose: the card says how the
    # follow-up looks will check, in the words this module owns.
    out["verify_text"] = verify_sentence(out["verify_by"])
    preview = value.get("preview")
    if isinstance(preview, list):
        out["preview"] = [_clean_preview(p) for p in preview[:MAX_OPS]]
    return out


MAX_DIFF = 8000
LEGACY_PLAN = ("this plan was written before brAIn checked each change as an "
               "operation it can carry out, so there is nothing to approve — "
               "press Fix it again for a plan it can apply")


def _clean_preview(value) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    if isinstance(value.get("diff"), str):
        out["diff"] = value["diff"][:MAX_DIFF]
    for key in ("error", "replay_note"):
        if isinstance(value.get(key), str):
            out[key] = textclip.clip(value[key], 400)
    for key in ("replay", "replay_before"):
        rep = value.get(key)
        if isinstance(rep, dict):
            out[key] = {k: rep[k] for k in ("would_run", "triggered",
                                            "blocked_by_conditions", "days",
                                            "error", "refused")
                        if k in rep}
    if isinstance(value.get("entity_id"), str):
        out["entity_id"] = value["entity_id"][:255]
    return out


__all__ = ["DETERMINISTIC", "LEGACY_PLAN", "MAX_OPS", "OP_KINDS", "REFUSED_DOMAINS",
           "RELOADABLE", "Refused", "SECURITY_REDUCING", "VERIFY_KINDS",
           "clean_op", "clean_ops", "clean_stored", "clean_verify",
           "contract_for", "describe", "entities_named", "has_agentic",
           "protected_refusal", "shadow_entities", "verify_sentence"]
