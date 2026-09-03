"""Who or what changed something — the action miner.

A state carries no cause. ``light.kitchen`` is on; nothing in the state
machine says whether a person pressed a switch, an automation fired, a
voice command asked, or brAIn did it. The one place Home Assistant records
that is the **logbook**, which walks each event's context chain back to
whatever started it, and this module reads the logbook and files every
change under a cause.

Four things are worth knowing before changing anything here.

**Proximate cause and root cause are different, and both are recorded.**
An automation a person started from the UI carries *both* a
``context_entity_id`` (the automation) and a ``context_user_id`` (the
person). The automation is what changed the light; the person is why the
automation ran. Reporting only the user turns every automation into "you
did this", and reporting only the automation loses the one fact that
explains an unexpected run. ``cause``/``by`` are the proximate half and
``root_user`` is the other.

**brAIn's own actions are recorded, not inferred.** Nothing in a context
says "brAIn": the MCP server calls Core over the REST API with the
Supervisor's token, exactly like every other add-on, so a change brAIn
made is indistinguishable from one any integration made. So the MCP
server appends every service call it makes to a ledger
(``/config/.brain/actions.jsonl``) and this module joins the logbook
against it. Knowing what we did because we wrote it down is the only
honest version of this; guessing it from a token that a dozen other
things share is not.

**A change with no context at all is ``unattributed``, and that is a
finding-shaped answer, not a failure.** A physical press on a wall switch
and a push from a device's integration reach Home Assistant the same way.
Calling either one is a guess, and a timeline that guesses is a timeline
nobody can use as evidence.

**Nothing here is persisted.** Every question this answers is a question
about a window — a day for the timeline, a day for the override check —
so every function is pure over one fetch. A store would buy longer
windows at the cost of a second thing to keep true.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import urllib.parse
from typing import Any

log = logging.getLogger("brain.actions")

LEDGER_FILE = os.environ.get("BRAIN_ACTION_LEDGER",
                             "/config/.brain/actions.jsonl")
# How long after brAIn asked for something the resulting state change may
# arrive and still be attributed to it. A service call is synchronous but
# the state it produces is not: a bulb answers in well under a second, a
# thermostat can take several.
BRAIN_MATCH_S = 20.0
# A person putting something back within this long after an automation
# moved it is undoing the automation, not making an unrelated decision.
OVERRIDE_WINDOW_S = 900.0
# Above this many entries one fetch is not a window any more. Mining stops
# and says so rather than parsing an unbounded list.
MAX_ENTRIES = 40_000

# The fixed vocabulary. A cause outside this set is a bug, not a new kind
# of cause: every reader (the check, the tab's filter, the MCP tool)
# switches on it.
CAUSES = (
    "brain",          # brAIn, matched against its own ledger
    "automation",
    "script",
    "scene",
    "voice",          # a conversation agent — Assist, or another one
    "person",         # a signed-in user, with no automation above them
    "unattributed",   # a wall switch, or a device's integration; unknowable
)
# Home Assistant's own entity-id shape. This is a *barrier*, not a
# nicety: an entity id arrives from a URL path and is put into the query
# of a request this process then makes to Core, so anything unvalidated
# there is somebody else choosing what brAIn asks Core for. Quoting alone
# would stop the `&` and keep the rest; refusing anything that is not an
# entity id is the answer to a question that has exactly one legal shape.
ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def is_entity_id(value: str) -> bool:
    return bool(ENTITY_RE.match(str(value or "")))


# The domains of a context_entity_id that name what ran, in the order they
# are tested. A scene called by a script is reported as the script: the
# outer thing is the one somebody would go and edit.
CONTEXT_DOMAINS = ("automation", "script", "scene")


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def parse_when(value: Any) -> float | None:
    """A logbook ``when`` as epoch seconds, in both shapes it comes in.

    The REST endpoint formats it as an ISO string and the WebSocket event
    stream as a float, from the same processor — so anything that reads
    one and not the other works until somebody points it at the other
    transport.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.timestamp()


def domain_of(entity_id: str) -> str:
    return str(entity_id or "").split(".", 1)[0]


# ---------------------------------------------------------------------------
# brAIn's own ledger
# ---------------------------------------------------------------------------

def read_ledger(since: float, path: str | None = None) -> list[dict]:
    """brAIn's own service calls since ``since``.

    The writer is ``ha_mcp_server.record_action`` — a different process,
    running as a different user, which cannot import this module. The two
    halves therefore agree by contract rather than by construction, and
    ``tests/test_actions.py`` drives the real writer into this reader so
    the contract is checked rather than described.

    A missing file means brAIn has not acted, which is the same answer as
    an empty one. A malformed line is skipped: this file is appended to by
    a process that may be killed mid-write.
    """
    out: list[dict] = []
    try:
        with open(path or LEDGER_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                ts = parse_when(row.get("ts"))
                if ts is None or ts < since:
                    continue
                row["ts"] = ts
                out.append(row)
    except OSError:
        return []
    return out


def _ledger_index(calls: list[dict]) -> dict[str, list[float]]:
    """{entity_id: [call time, ...]} for the entities brAIn named.

    An area or device target is deliberately not resolved: the MCP server
    records what it was asked for, and resolving a target here would need
    the registries at the time of the call rather than now. A change
    brAIn made through an area target therefore reads as unattributed —
    the honest answer, and the reason ``control_*`` tools name entities.
    """
    index: dict[str, list[float]] = {}
    for call in calls:
        for eid in call.get("entities") or []:
            if isinstance(eid, str) and eid:
                index.setdefault(eid, []).append(call["ts"])
    for times in index.values():
        times.sort()
    return index


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _brain_did_it(index: dict[str, list[float]], entity_id: str,
                  ts: float) -> bool:
    for called in index.get(entity_id, ()):
        if called <= ts <= called + BRAIN_MATCH_S:
            return True
    return False


def classify(entry: dict, users: dict[str, str] | None = None,
             brain_index: dict[str, list[float]] | None = None) -> dict:
    """One logbook entry's cause, as ``cause``/``by``/``by_name`` plus the
    root user behind it.

    Home Assistant has already walked the context chain by the time an
    entry reaches here — ``context_entity_id`` names what ran and
    ``context_user_id`` names who started it. What is left is deciding
    which of the two is the answer, and that is the proximate/root split
    in this module's docstring.
    """
    users = users or {}
    entity_id = str(entry.get("entity_id") or "")
    ts = parse_when(entry.get("when"))
    user_id = str(entry.get("context_user_id") or "")
    user_name = users.get(user_id, "")
    out = {
        "cause": "unattributed",
        "by": "",
        "by_name": "",
        "root_user": user_id,
        "root_user_name": user_name,
    }

    if brain_index and ts is not None and _brain_did_it(brain_index, entity_id, ts):
        out["cause"] = "brain"
        out["by_name"] = "brAIn"
        return out

    ctx_entity = str(entry.get("context_entity_id") or "")
    ctx_domain = str(entry.get("context_domain") or "")
    # The context entity is the authority when it is one of the three
    # domains that *run* something; context_domain alone is not, because
    # a `light.turn_on` service call sets it to "light".
    ctx_kind = domain_of(ctx_entity) if ctx_entity else ""
    if ctx_kind not in CONTEXT_DOMAINS and ctx_domain in CONTEXT_DOMAINS:
        ctx_kind = ctx_domain
    if ctx_kind in CONTEXT_DOMAINS and ctx_entity != entity_id:
        out["cause"] = ctx_kind
        out["by"] = ctx_entity
        out["by_name"] = str(entry.get("context_entity_id_name")
                             or entry.get("context_name") or ctx_entity)
        return out

    if ctx_domain == "conversation":
        out["cause"] = "voice"
        out["by_name"] = str(entry.get("context_name") or "a voice assistant")
        return out

    if user_id:
        out["cause"] = "person"
        out["by"] = user_id
        out["by_name"] = user_name or "someone signed in"
        return out
    return out


# ---------------------------------------------------------------------------
# Mining
# ---------------------------------------------------------------------------

def mine(entries: list[dict], users: dict[str, str] | None = None,
         brain_calls: list[dict] | None = None,
         cap: int = MAX_ENTRIES) -> dict:
    """Logbook entries as attributed actions, oldest first.

    Entries with no ``entity_id`` are dropped — a logbook line about an
    automation triggering is the *cause* of the changes around it, and
    keeping it too would report every automation run twice.
    """
    brain_index = _ledger_index(brain_calls or [])
    actions: list[dict] = []
    capped = False
    for i, entry in enumerate(entries or []):
        if i >= cap:
            capped = True
            break
        if not isinstance(entry, dict):
            continue
        entity_id = str(entry.get("entity_id") or "")
        state = entry.get("state")
        if not entity_id or state is None:
            continue
        ts = parse_when(entry.get("when"))
        if ts is None:
            continue
        action = {
            "ts": ts,
            "entity_id": entity_id,
            "name": str(entry.get("name") or entity_id),
            "state": str(state),
        }
        action.update(classify(entry, users, brain_index))
        actions.append(action)
    actions.sort(key=lambda a: a["ts"])
    return {"actions": actions, "capped": capped,
            "counts": count_causes(actions)}


def count_causes(actions: list[dict]) -> dict[str, int]:
    counts = {c: 0 for c in CAUSES}
    for a in actions:
        counts[a["cause"]] = counts.get(a["cause"], 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Overrides — a person undoing an automation
# ---------------------------------------------------------------------------

AUTOMATED = ("automation", "script", "scene", "brain")


def find_overrides(actions: list[dict],
                   window_s: float = OVERRIDE_WINDOW_S) -> list[dict]:
    """Every time a person put back what something automated had just done.

    Evidence, not a verdict. Somebody turning a light off after a motion
    rule turned it on is the single clearest signal a house gives about an
    automation being wrong for it, and it is invisible in every other
    view: the automation ran, nothing errored, and the light is off.

    The state has to actually differ. An automation setting a light to on
    and a person pressing on again is agreement, and counting it as a
    fight would put the best-behaved automation in the house at the top of
    the list.
    """
    last_auto: dict[str, dict] = {}
    out: list[dict] = []
    for action in sorted(actions, key=lambda a: a["ts"]):
        eid = action["entity_id"]
        if action["cause"] in AUTOMATED:
            last_auto[eid] = action
            continue
        if action["cause"] != "person":
            continue
        prior = last_auto.get(eid)
        if not prior:
            continue
        if action["ts"] - prior["ts"] > window_s:
            continue
        if action["state"] == prior["state"]:
            continue
        out.append({
            "ts": action["ts"],
            "entity_id": eid,
            "name": action["name"],
            "from_state": prior["state"],
            "to_state": action["state"],
            "by": prior["by"],
            "by_name": prior["by_name"],
            "by_cause": prior["cause"],
            "person": action["by_name"],
            "after_s": round(action["ts"] - prior["ts"], 1),
        })
        # One automation move is undone once. Without this a person
        # nudging a dimmer three times counts as three fights.
        last_auto.pop(eid, None)
    return out


def group_overrides(overrides: list[dict]) -> dict[str, dict]:
    """Overrides gathered under the automation that was undone."""
    groups: dict[str, dict] = {}
    for o in overrides:
        key = o["by"] or o["by_name"]
        if not key:
            continue
        group = groups.setdefault(key, {
            "by": o["by"], "by_name": o["by_name"],
            "by_cause": o["by_cause"], "count": 0, "entities": [],
            "last_ts": 0.0,
        })
        group["count"] += 1
        if o["entity_id"] not in group["entities"]:
            group["entities"].append(o["entity_id"])
        group["last_ts"] = max(group["last_ts"], o["ts"])
    return groups


# ---------------------------------------------------------------------------
# One entity's story
# ---------------------------------------------------------------------------

def explain(actions: list[dict], entity_id: str, limit: int = 12) -> list[dict]:
    """The most recent changes to one entity, newest first.

    This is the whole of "why did that happen" that arithmetic can
    answer: what it became, when, and what did it. Whether the automation
    that did it was *right* to is a question for the model, and it reads
    this rather than guessing from a state.
    """
    rows = [a for a in actions if a["entity_id"] == entity_id]
    rows.sort(key=lambda a: a["ts"], reverse=True)
    return rows[:limit]


# ---------------------------------------------------------------------------
# The one thing here that touches the network
# ---------------------------------------------------------------------------

async def fetch_logbook(session, start: float, end: float,
                        entity_id: str = "", timeout: int = 90) -> list[dict]:
    """Raw logbook entries for a window, or ``None`` if it cannot be read.

    ``None`` and ``[]`` are different answers and both happen: a house
    where nothing changed overnight returns an empty list, and a house
    with the ``logbook`` integration left out of ``configuration.yaml``
    answers 404. Only the first may be reported as "nothing happened" —
    the same rule the checks snapshot applies to every key it fetches.

    aiohttp and ``ha_data`` are imported here rather than at module level
    so the mining half stays importable — and testable — without the
    add-on's runtime.
    """
    import ha_data  # noqa: PLC0415 — see docstring

    def iso(value: float) -> str:
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()

    path = f"/logbook/{iso(start)}?end_time={iso(end)}"
    if entity_id:
        # Refused rather than sent. The caller validates too — this is the
        # last line before the request leaves, and a barrier that is only
        # at the edge is a barrier the next caller forgets.
        if not is_entity_id(entity_id):
            log.info("refusing a logbook fetch for %r: not an entity id",
                     entity_id[:64])
            return None
        path += "&entity=" + urllib.parse.quote(entity_id, safe="")
    try:
        raw = await ha_data._rest_get(session, path, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — every failure is "cannot look"
        log.info("logbook unavailable: %s", exc)
        return None
    if not isinstance(raw, list):
        # An envelope this does not know is not an empty logbook.
        log.info("logbook answered %s, not a list", type(raw).__name__)
        return None
    return raw


async def collect(session, start: float, end: float,
                  users: dict[str, str] | None = None,
                  entity_id: str = "") -> dict:
    """Fetch a window and mine it. ``available`` is False when the logbook
    could not be read, and every reader has to branch on it.

    ``entity_id`` filters at the logbook rather than after it, which is
    what makes "why is this one thing the way it is" a cheap question on
    a window that is expensive to fetch whole.
    """
    entries = await fetch_logbook(session, start, end, entity_id)
    if entries is None:
        return {"available": False, "error": "logbook could not be read",
                "actions": [], "overrides": [], "counts": count_causes([]),
                "capped": False, "start": start, "end": end}
    mined = mine(entries, users, read_ledger(start))
    return {
        "available": True,
        "error": "",
        "start": start,
        "end": end,
        "actions": mined["actions"],
        "capped": mined["capped"],
        "counts": mined["counts"],
        "overrides": find_overrides(mined["actions"]),
    }
