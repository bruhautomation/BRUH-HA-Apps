"""The tripwire: an entity nothing should ever act on, and what it means if
something does.

Every guard in this add-on is a rule about what a run MAY do. None of them
says whether a run is doing something it was talked into — text in an
entity's name, a calendar event, a notification someone else wrote, read by
a tool and taken as an instruction. The untrusted-text tagging in the MCP
server is the half that lowers the odds; this is the half that notices.

A **honeytoken** is an entity no person ever asks brAIn to touch. brAIn
creates one on a press (`input_boolean.brain_honeytoken`, read back from
the create call rather than derived — `IDManager`'s `_2` rule) and a person
may name others in settings. The MCP chokepoint refuses any acting call on
one **before every other guard**, and reports it here; this files a
`security` case, deterministically, the way the safety lane files a leak —
no gate, no model, because a tripwire that waited for a budget is one that
sleeps through the break-in.

Three rules.

**The file is the contract, and the MCP server reads the file**
(`HONEYTOKEN_FILE`, `{"entities": [...]}`). An option would reach only the
MCP processes started after it was set; a file is read at call time
(mtime-cached), so a tripwire made this afternoon guards the voice worker
that has been running since Tuesday. It is written by the panel only, and
only when its directory exists (`publish_state`'s rule: a dev checkout
must not grow a stray `/config`).

**The entity is never named to a model.** Not in a prompt, not in a plan,
not in a tool description: a tripwire a run has been told about is one it
can be told to avoid. A refusal says "brAIn's tripwire entity", which is
true and is the sentence a person reading the transcript needs.

**One case per trip, and the case says which channel and which run**, so
"what read what" is answerable from the conversation that tripped it. The
text carries the local time for the safety lane's reason: the store
dedupes by text, and the second trip is not a duplicate of the first.

Stdlib plus `atomic_write` and `settings_store`.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import atomic_write
import settings_store

HONEYTOKEN_FILE = Path(os.environ.get(
    "BRAIN_HONEYTOKEN_FILE", "/config/.brain/honeytoken.json"))
# The name brAIn gives the one it creates. Chosen so its slug lands on
# `input_boolean.brain_honeytoken` while that is free; the id actually
# minted is read back off the create call and is the one recorded.
HONEYTOKEN_NAME = "brAIn honeytoken"
SOURCE = "security"
SOURCE_TITLE = "Tripwire"
MAX_CALL = 120

STATE: dict = {"tripped": 0, "last_at": 0, "last_entity": "",
               "last_error": "", "repeats": 0}


def read_file() -> dict:
    """`{"entities", "created", "error"}` — never raises.

    "Could not read" is its own answer (`error`): a tripwire file that
    exists and will not parse is a guard that is not running, which is a
    fault worth showing, where a missing file is simply none made yet.
    """
    try:
        raw = HONEYTOKEN_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"entities": [], "created": [], "error": ""}
    except OSError as exc:
        return {"entities": [], "created": [], "error": str(exc)[:200]}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return {"entities": [], "created": [], "error": f"unreadable: {exc}"}
    if not isinstance(data, dict):
        return {"entities": [], "created": [], "error": "not an object"}
    created = [c for c in data.get("created") or []
               if isinstance(c, dict) and isinstance(c.get("entity_id"), str)]
    entities = [str(e).lower() for e in data.get("entities") or []
                if isinstance(e, str)]
    return {"entities": entities, "created": created, "error": ""}


def configured() -> list[str]:
    try:
        return list(settings_store.load().get("honeytoken_entities") or [])
    except Exception:  # noqa: BLE001 — an unreadable setting adds nothing
        return []


def honeytoken_ids() -> list[str]:
    """Every tripwire: the ones brAIn made plus the ones a person named."""
    out: list[str] = []
    for eid in [c["entity_id"] for c in read_file()["created"]] + configured():
        eid = str(eid).lower()
        if eid and eid not in out:
            out.append(eid)
    return out


def publish(created: list[dict] | None = None) -> list[str]:
    """Rewrite the file from what brAIn made and what a person named.

    Returns the entities written. Skipped (and returns them anyway) when
    the directory does not exist, which is a dev checkout or a test.
    """
    if created is None:
        created = read_file()["created"]
    entities = []
    for eid in [c["entity_id"] for c in created] + configured():
        eid = str(eid).lower()
        if eid and eid not in entities:
            entities.append(eid)
    # Nothing to guard and nothing on disk is nothing to write: a boot that
    # created an empty file would be a file a person has to wonder about.
    if not entities and not HONEYTOKEN_FILE.exists():
        return entities
    if HONEYTOKEN_FILE.parent.is_dir():
        atomic_write.write_text(HONEYTOKEN_FILE, json.dumps(
            {"entities": entities, "created": created}, indent=1))
    return entities


def case_row(entity: str, call: str, channel: str, run_id: str,
             when: float, local_stamp: str) -> dict:
    """The security case one trip files. Deterministic; no model wrote it."""
    who = channel or "an unnamed run"
    text = f"Something tried to act on brAIn's tripwire entity ({local_stamp})"
    detail = (f"A {who} run asked to call {call[:MAX_CALL]} on {entity}, "
              "which nothing should ever touch. It was refused before it "
              "reached Home Assistant. This usually means the run read text "
              "somewhere — an entity name, a calendar entry, a notification, "
              "a web page — and took it as an instruction.")
    if run_id:
        detail += " The conversation that asked is linked below."
    return {
        "text": text,
        "claim": text,
        "detail": detail,
        "kind": "problem",
        "severity": "critical",
        "stakes": "high",
        "confidence": 1.0,
        "entity_id": entity,
        "fixable": False,
        "source": SOURCE,
        "source_title": SOURCE_TITLE,
        "run_id": str(run_id or "")[:64],
        "evidence": [{"entity": entity, "value": call[:MAX_CALL],
                      "when": local_stamp}],
        "fix": ("Open the conversation it came from and look for what it "
                "read just before; then decide whether the channel that "
                "asked should keep the reach it has."),
    }


def note_trip(entity: str, when: float | None = None) -> None:
    STATE["tripped"] += 1
    STATE["last_at"] = int(when if when is not None else time.time())
    STATE["last_entity"] = entity


def diagnostics() -> dict:
    data = read_file()
    return {**STATE, "entities": len(honeytoken_ids()),
            "file_error": data["error"]}


__all__ = ["HONEYTOKEN_FILE", "HONEYTOKEN_NAME", "SOURCE", "STATE",
           "case_row", "configured", "diagnostics", "honeytoken_ids",
           "note_trip", "publish", "read_file"]
