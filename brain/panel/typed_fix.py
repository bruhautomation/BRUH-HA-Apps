"""Carrying out the deterministic half of an approved fix — no model.

`plan_ops` turns a plan into typed operations; this is what performs the
five that are not `agentic`. Each one is a single, checkable change the
panel can make itself, so a fix that is "change this automation's
trigger, then reload" no longer spends an Opus run with a shell to do two
things the panel already knows how to do exactly.

Four rules.

**Show the change before it is made** (`edit_preview`). An
`edit_automation` op is a whole new config, and "change the automation"
on a card is a sentence nobody can check — so the plan carries the diff
of the bytes that will change in `automations.yaml`, cut the same way
`automation_writer.replace_entry` will cut them, plus a replay of the old
and the new config over the recorder's week. An edit this cannot locate
is refused at the plan, because an Apply that would fail at the writer is
an Apply the card should not offer.

**The floors are asked again at the moment of acting.** The plan was
checked when it was written; the protected list may have grown since, and
the tripwire entity may have been made since. `execute` re-asks both of
every op before the first one runs, and refuses the whole set if any
answer changed — never a partial apply.

**Stop at the first failure, and put back what can be put back exactly.**
A file edit has a snapshot and a registry change has the value it
replaced, so both are reversed, newest first, when a later op fails. A
service call is NOT reversed here: reversing one is acting on a recorded
before-state, and that is a press a person makes (`unfix.restore_plan`),
never something the panel does on its own because a different op failed.
The result says which calls stand, so the card can offer the restore.

**Every service call is recorded where brAIn's other calls are**
(`ledger_row`): the same row shape `ha_mcp_server.record_action` writes,
with the before-state read first, so the action miner attributes it to
brAIn, the undo lists it and the restore can put it back. The two writers
are held to one shape by a test that drives both.

Everything that touches Core arrives as a hook, so the suite drives this
over fakes that record what was asked for, and the server supplies the
real calls (`_apply_accepted`, `ha_data.call_core_service`, the registry
WebSocket).
"""
from __future__ import annotations

import difflib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import automation_writer
import plan_ops

# The attributes a before-state keeps, the same set the MCP server keeps:
# what a restore can hand back to Home Assistant's own reproduce_state.
BEFORE_ATTRS = frozenset({
    "brightness", "color_mode", "color_temp_kelvin", "hs_color", "rgb_color",
    "xy_color", "effect", "current_position", "current_tilt_position",
    "temperature", "target_temp_high", "target_temp_low", "hvac_mode",
    "preset_mode", "fan_mode", "swing_mode", "humidity", "percentage",
    "oscillating", "direction", "volume_level", "is_volume_muted", "source",
    "device_class", "friendly_name",
})
REPLAY_DAYS = 7


@dataclass
class Hooks:
    """What `execute` may do to Core. Every one may raise."""

    # write → reload → verify, putting the file back itself on failure
    # (`server._apply_accepted`): returns (written, "") or (None, reason)
    apply_edit: Callable[[dict], Awaitable[tuple[dict | None, str]]]
    # put an applied edit back and reload; returns "" or the reason
    revert_edit: Callable[[dict], Awaitable[str]]
    # one Core service call
    call: Callable[[str, str, dict], Awaitable[Any]]
    # one state row, or None
    state: Callable[[str], Awaitable[dict | None]]
    # registry WebSocket commands → `ha_data._ws_calls`' shape
    ws: Callable[[list[dict]], Awaitable[list[dict]]]
    # append one action-ledger row; None writes nothing
    ledger: Callable[[dict], None] | None = None
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# The preview — shown before Apply, never written
# ---------------------------------------------------------------------------

def edit_preview(op: dict, config_dir: str | None = None) -> dict:
    """The diff an `edit_automation` op will make, and the config it replaces.

    `{"diff", "before_config", "path"}` or `{"error": <sentence>}`. Cut
    with the writer's own `locate` and re-indented with its own `_dump`,
    so the bytes shown are the bytes `replace_entry` will write — a diff
    computed any other way is a picture of a different change.
    """
    root = Path(config_dir or automation_writer.CONFIG_DIR)
    path = root / automation_writer.AUTOMATIONS_FILE
    text = automation_writer._read_text(path)
    if text is None:
        return {"error": f"brAIn could not read {path.name}, so it cannot "
                         "show what this would change"}
    entry_id = str(op.get("id") or "")
    located = automation_writer.locate(text, entry_id)
    if located is None:
        if entry_id not in automation_writer.entry_ids(text):
            return {"error": f"there is no automation with the id {entry_id} "
                             f"in {path.name} — it may live in a package or "
                             "have been made in a way brAIn cannot edit"}
        return {"error": f"brAIn could not find exactly one entry {entry_id} "
                         f"in {path.name} that it could edit cleanly"}
    start, end = located
    line = text[start:end]
    indent = line[:len(line) - len(line.lstrip(" \t"))]
    try:
        new_block = automation_writer._reindent(
            automation_writer._dump(op["new_config"]), indent)
    except Exception as exc:  # noqa: BLE001 — a config that will not dump
        return {"error": f"the new automation could not be written as YAML: "
                         f"{exc}"}
    old_block = text[start:end]
    diff = "".join(difflib.unified_diff(
        old_block.splitlines(keepends=True), new_block.splitlines(keepends=True),
        fromfile=f"{path.name} (now)", tofile=f"{path.name} (after)", n=2))
    before = None
    try:
        import yaml  # noqa: PLC0415 — see automation_writer._dump

        for item in yaml.safe_load(text) or []:
            if isinstance(item, dict) and str(item.get("id")) == entry_id:
                before = item
                break
    except Exception:  # noqa: BLE001 — the diff is still right without it
        before = None
    if not diff:
        return {"error": f"the new config for {entry_id} is identical to the "
                         "one already there, so there is nothing to change"}
    return {"diff": diff[:plan_ops.MAX_DIFF], "before_config": before,
            "path": str(path)}


# ---------------------------------------------------------------------------
# Before-state and the ledger row
# ---------------------------------------------------------------------------

def _short(value):
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        return value[:64]
    if isinstance(value, (list, tuple)) and len(value) <= 4 and all(
            isinstance(v, (int, float)) for v in value):
        return list(value)
    return None


def before_of(row: dict | None) -> dict:
    """One state row as a before-state, the MCP server's shape exactly."""
    if not isinstance(row, dict) or "state" not in row:
        return {"unknown": True}
    attrs = {}
    for key, value in (row.get("attributes") or {}).items():
        if key in BEFORE_ATTRS:
            kept = _short(value)
            if kept is not None:
                attrs[key] = kept
    return {"state": str(row.get("state"))[:64], "attributes": attrs}


def ledger_row(domain: str, service: str, entities: list[str], *,
               before: dict, channel: str = "fix", intervention: str = "",
               when: float | None = None) -> dict:
    """The action-ledger row for a call the PANEL made, in the MCP shape."""
    row = {"ts": time.time() if when is None else when, "domain": domain,
           "service": service, "entities": list(entities)}
    if channel:
        row["channel"] = channel
    if before:
        row["before"] = before
    if intervention:
        row["intervention"] = intervention
    return row


def append_ledger(row: dict, path: str) -> None:
    """Append one row. Never raises, and never creates the directory
    (`ha_mcp_server.record_action`'s rule, for its reason)."""
    try:
        if not os.path.isdir(os.path.dirname(path) or "."):
            return
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        # Accounting must not fail the change it is accounting for: a ledger
        # this cannot write costs an attribution and the restore of this
        # call, never the call itself.
        pass


# ---------------------------------------------------------------------------
# Carrying it out
# ---------------------------------------------------------------------------

async def _registry_entity(hooks: Hooks, entity_id: str) -> dict | None:
    out = await hooks.ws([{"type": "config/entity_registry/get",
                           "entity_id": entity_id}])
    if out and out[0].get("ok") and isinstance(out[0].get("result"), dict):
        return out[0]["result"]
    return None


async def _registry_device(hooks: Hooks, device_id: str) -> dict | None:
    out = await hooks.ws([{"type": "config/device_registry/list"}])
    if out and out[0].get("ok") and isinstance(out[0].get("result"), list):
        for row in out[0]["result"]:
            if isinstance(row, dict) and row.get("id") == device_id:
                return row
    return None


async def _update(hooks: Hooks, command: dict) -> str:
    out = await hooks.ws([command])
    if not out or not out[0].get("ok"):
        return str((out[0] if out else {}).get("error")
                   or "Home Assistant refused it")
    return ""


async def _one(op: dict, hooks: Hooks, intervention: str) -> dict:
    """Carry out one op. `{ok, detail, undo?, call?}` — never raises past
    a hook's own exception, which the caller turns into a failure."""
    kind = op["op"]
    if kind == "edit_automation":
        row = {"edits": op["id"], "config": op["new_config"],
               "automation": {"entity_id": str(op.get("entity_id") or "")}}
        written, why = await hooks.apply_edit(row)
        if written is None:
            return {"ok": False, "detail": why or "brAIn could not write it"}
        return {"ok": True, "detail": f"Changed the automation {op['id']}",
                "undo": {"kind": "edit", "written": written},
                "journal_ts": written.get("journal_ts")}

    if kind == "reload":
        await hooks.call(op["domain"], "reload", {})
        return {"ok": True,
                "detail": f"Reloaded Home Assistant's {op['domain']} config"}

    if kind == "call_service":
        before = {}
        for eid in op["entities"]:
            try:
                before[eid] = before_of(await hooks.state(eid))
            except Exception:  # noqa: BLE001 — "could not see" is recorded
                before[eid] = {"unknown": True}
        data = dict(op.get("data") or {})
        data["entity_id"] = list(op["entities"])
        await hooks.call(op["domain"], op["service"], data)
        row = ledger_row(op["domain"], op["service"], op["entities"],
                         before=before, intervention=intervention)
        if hooks.ledger is not None:
            hooks.ledger(row)
        return {"ok": True, "detail": plan_ops.describe(op), "call": row}

    if kind == "rename_entity":
        current = await _registry_entity(hooks, op["entity_id"])
        if current is None:
            return {"ok": False, "detail": f"{op['entity_id']} is not in the "
                    "entity registry, so it cannot be renamed"}
        command = {"type": "config/entity_registry/update",
                   "entity_id": op["entity_id"]}
        undo = {"kind": "entity", "entity_id": op.get("new_entity_id")
                or op["entity_id"], "restore": {}}
        if op.get("name"):
            command["name"] = op["name"]
            undo["restore"]["name"] = current.get("name")
        if op.get("new_entity_id"):
            command["new_entity_id"] = op["new_entity_id"]
            undo["restore"]["new_entity_id"] = op["entity_id"]
        why = await _update(hooks, command)
        if why:
            return {"ok": False, "detail": f"Home Assistant would not rename "
                    f"{op['entity_id']}: {why}"}
        return {"ok": True, "detail": plan_ops.describe(op), "undo": undo}

    if kind == "set_area":
        if op.get("device_id"):
            current = await _registry_device(hooks, op["device_id"])
            if current is None:
                return {"ok": False, "detail": f"there is no device "
                        f"{op['device_id']} in the registry"}
            why = await _update(hooks, {"type": "config/device_registry/update",
                                        "device_id": op["device_id"],
                                        "area_id": op["area_id"]})
            undo = {"kind": "device", "device_id": op["device_id"],
                    "restore": {"area_id": current.get("area_id")}}
        else:
            current = await _registry_entity(hooks, op["entity_id"])
            if current is None:
                return {"ok": False, "detail": f"{op['entity_id']} is not in "
                        "the entity registry, so it has no area to set"}
            why = await _update(hooks, {"type": "config/entity_registry/update",
                                        "entity_id": op["entity_id"],
                                        "area_id": op["area_id"]})
            undo = {"kind": "entity", "entity_id": op["entity_id"],
                    "restore": {"area_id": current.get("area_id")}}
        if why:
            return {"ok": False, "detail": f"Home Assistant would not move it: "
                    f"{why}"}
        return {"ok": True, "detail": plan_ops.describe(op), "undo": undo}

    return {"ok": False, "detail": f"{kind} is not something the panel carries "
            "out itself"}


async def undo_one(item: dict, hooks: Hooks) -> str:
    """Reverse one recorded change. "" or the reason it could not be."""
    try:
        if item.get("kind") == "edit":
            return await hooks.revert_edit(item.get("written") or {})
        if item.get("kind") == "entity":
            command = {"type": "config/entity_registry/update",
                       "entity_id": item["entity_id"], **item.get("restore", {})}
            return await _update(hooks, command)
        if item.get("kind") == "device":
            return await _update(hooks, {"type": "config/device_registry/update",
                                         "device_id": item["device_id"],
                                         **item.get("restore", {})})
    except Exception as exc:  # noqa: BLE001 — an undo reports, never raises
        return str(exc)[:200]
    return "brAIn does not know how to put that back"


async def execute(ops: list[dict], hooks: Hooks, *, intervention: str = "",
                  protected=None, honeytokens=()) -> dict:
    """Carry out every deterministic op, in order, or none of the reversible
    ones.

    Returns `{"ok", "done": [...], "undo": [...], "calls": [...],
    "journal_ts": [...], "error", "rolled_back": [...]}`. `undo` is what a
    later Undo press reverses; `calls` is what a Restore press can put back.
    """
    out: dict = {"ok": False, "done": [], "undo": [], "calls": [],
                 "journal_ts": [], "error": "", "rolled_back": []}
    # The floors, asked again now — the list may have grown since the plan.
    refusal = plan_ops.protected_refusal(ops, protected, honeytokens)
    if refusal:
        out["error"] = refusal
        return out
    for op in ops:
        if op.get("op") not in plan_ops.DETERMINISTIC:
            continue
        try:
            step = await _one(op, hooks, intervention)
        except Exception as exc:  # noqa: BLE001 — every way an op fails is
            # the same answer to the person waiting: it did not happen.
            step = {"ok": False, "detail": f"{plan_ops.describe(op)} failed: "
                                           f"{str(exc)[:300]}"}
        if not step["ok"]:
            out["error"] = step["detail"]
            for item in reversed(out["undo"]):
                why = await undo_one(item, hooks)
                out["rolled_back"].append(why or "put back")
            out["undo"] = []
            return out
        out["done"].append(step["detail"])
        if step.get("undo"):
            out["undo"].append(step["undo"])
        if step.get("call"):
            out["calls"].append(step["call"])
        if step.get("journal_ts"):
            out["journal_ts"].append(step["journal_ts"])
    out["ok"] = True
    return out


__all__ = ["BEFORE_ATTRS", "Hooks", "REPLAY_DAYS", "append_ledger",
           "before_of", "edit_preview", "execute", "ledger_row", "undo_one"]
