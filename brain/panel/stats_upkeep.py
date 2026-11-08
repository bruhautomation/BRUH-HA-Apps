"""Home Assistant's long-term statistics, kept healthy by brAIn (#576).

The owner's words: they do not want to click every "Fix issue" button on
Home Assistant's Repairs page for statistics issues; brAIn should know how
to fix and clean those up itself.

Core's recorder answers `recorder/validate_statistics` with every issue it
has with a statistic, and the Repairs page shows three of them
(`units_changed`, `state_class_removed`, `mean_type_changed`) beside the
developer tools' list of the rest. Each has one or two fixes Core itself
offers behind its "Fix issue" button, and they are not equally safe. So
this is a **closed playbook**, `healing.py`'s shape: code decides, no model
is asked, and every fix is one of two recorder calls.

**What brAIn does on its own is only what cannot lose anything.**

  * `units_changed`, where the sensor's live state reports the unit the
    issue names: the statistics' unit is set to the one the sensor now
    reports (`recorder/update_statistics_metadata`, Core's own "update the
    unit without converting"). No row of history is touched, and the unit
    it had is kept, so Undo puts it back exactly.
  * `no_state` — statistics for a sensor that no longer reports — is
    cleared (`recorder/clear_statistics`) only when the entity registry,
    read in the same pass, says the entity is **gone** (no registry entry)
    or **disabled**. An enabled entry with no state is an integration that
    has not loaded yet (a restart), and an unreadable registry is "could
    not tell", and both are left for the next pass.

**A live entity's history is never deleted by a schedule.**
`state_class_removed` and `mean_type_changed` on a sensor that still
reports have only one fix in Core — delete the old statistics — so they
become a question in Today ("Clear the old long-term statistics of …?"),
and only its Yes clears them, after validating again. **Each card carries
its own list** (`asked` holds the card's id beside every statistic it
named, `note_asked` / `answer`): a Yes clears exactly what THAT card asked
about, never a statistic the owner said No to on an earlier card and never
a second card's, open at the same time. **A No is remembered** (`declined`,
for `DECLINED_S`): never cleared, not asked again for a long time, and
forgotten by the toast's Undo (`forget_answer`). Doesn't apply records
nothing. A card that vanished unanswered (`open_questions`) is asked again.

**What is left alone is never flagged.** `entity_no_longer_recorded` and
`entity_not_recorded` are an entity the recorder's own `exclude` keeps out
on purpose; asking about one would be asking somebody to defend their own
configuration. A protected entity or a tripwire is never touched, a
`units_changed` with no unit to set waits, and a statistic whose fix the
owner put back with Undo is never fixed again (`kept`): a guard that
refuses has to change the next attempt.

**Verified, not assumed.** After the fixes the run asks Core to refresh its
Repairs (`recorder/update_statistics_issues`) and validates again; each
fix records whether its issue is gone (`held`). History › Changes lists
every one, and a unit fix carries its Undo.

Stdlib only and pure over what it is handed; the server makes the calls.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import atomic_write

STORE = Path(os.environ.get("BRAIN_STATS_UPKEEP_FILE",
                            "/data/stats_upkeep.json"))
# Due again this long after the last pass, and sooner after brAIn or Core
# restarts or updates (`due`).
INTERVAL_S = 24 * 3600
# What one pass may change. A house that has fifty statistics issues at
# once has had something happen to it that a schedule should not undo in
# one go; the rest wait for tomorrow's pass, oldest id first.
MAX_FIXES = 20
# How long a change stays on History, as `changes.CHANGES_DAYS`.
KEEP_DAYS = 30
MAX_NAMED = 5
# How long a No holds: the statistic is not asked about again for this
# long, and never cleared while it holds.
DECLINED_S = 90 * 86400
# A pass that found Core still starting (nothing may be cleared before it
# says RUNNING) is tried again this soon, not tomorrow and not every poll.
RETRY_S = 3600

# The recorder's issue types, by what brAIn may do about them.
UNITS_CHANGED = "units_changed"
NO_STATE = "no_state"
# Their only fix in Core deletes the statistics.
CLEAR_ONLY = ("state_class_removed", "mean_type_changed")
# The recorder's `exclude` at work: on purpose, never flagged.
EXCLUDED_ON_PURPOSE = ("entity_no_longer_recorded", "entity_not_recorded")

# Where a fix came from, in History's words (`changes.WHERE`).
CHANNEL = "upkeep"
SOURCE = "statistics"
SOURCE_TITLE = "Home Assistant's long-term statistics"

_WHY = {
    "state_class_removed": "the sensor no longer says what kind of "
                           "reading it is, so its old statistics no longer "
                           "match it",
    "mean_type_changed": "the sensor now reports a different kind of "
                         "average, so its old statistics no longer match it",
}


def issues_from(result) -> list[dict]:
    """`validate_statistics`' answer as rows, sorted by statistic id.

    Core answers `{statistic_id: [{"type": ..., "data": {...}}]}`.
    """
    out: list[dict] = []
    if not isinstance(result, dict):
        return out
    for sid in sorted(result):
        for issue in result.get(sid) or []:
            if not isinstance(issue, dict) or not issue.get("type"):
                continue
            data = issue.get("data") if isinstance(issue.get("data"), dict) else {}
            out.append({"statistic_id": str(sid), "type": str(issue["type"]),
                        "data": dict(data)})
    return out


def _registry_by_id(registry) -> dict | None:
    if registry is None:
        return None
    out = {}
    for row in registry or []:
        if isinstance(row, dict) and row.get("entity_id"):
            out[str(row["entity_id"])] = row
    return out


def _states_by_id(states) -> dict:
    out = {}
    for row in states or []:
        if isinstance(row, dict) and row.get("entity_id"):
            out[str(row["entity_id"])] = row
    return out


def _protected(eid: str, patterns, tokens) -> bool:
    import automation_writer  # noqa: PLC0415 — panel-local

    if str(eid).lower() in {str(t).lower() for t in tokens or ()}:
        return True
    return automation_writer.is_protected(eid, list(patterns or []))


# How long a sensor the registry does not know (a YAML or template sensor
# with no unique_id) must stay missing, seen on two passes at least this far
# apart, before its statistics are cleared: long past any restart.
MISSING_FOR_S = 6 * 3600
# Core's own word for "every integration has loaded" (`get_config`'s
# `state`). Before it, a missing sensor is one that has not loaded yet.
CORE_RUNNING = "RUNNING"


def plan(issues: list[dict], states, registry, *, patterns=(), tokens=(),
         kept=(), core_state: str = "", missing: dict | None = None,
         now: float = 0.0) -> dict:
    """What this pass may do about each issue.

    `{"fix": [...], "clear": [...], "ask": [...], "leave": [...]}`. A fix
    and a clear carry the exact recorder command, and a fix its undo; a
    leave carries why. `registry` is `config/entity_registry/list`'s
    answer, or None when it could not be read.

    Nothing is cleared unless `core_state` is Core's `RUNNING`. `missing` is
    `{statistic_id: first seen missing}` from the passes before; the answer
    carries this pass's (`out["missing"]`): a sensor that came back drops
    out of it, so its clock starts over if it goes again.
    """
    live = _states_by_id(states)
    reg = _registry_by_id(registry)
    kept_keys = {(str(k[0]), str(k[1])) for k in kept or () if len(k) == 2}
    out: dict = {"fix": [], "clear": [], "ask": [], "leave": [],
                 "missing": {}}
    seen_missing = dict(missing or {})
    running = str(core_state or "") == CORE_RUNNING

    def leave(issue: dict, why: str) -> None:
        out["leave"].append({**issue, "why": why})

    for issue in issues or []:
        sid, kind = issue["statistic_id"], issue["type"]
        data = issue.get("data") or {}
        if kind in EXCLUDED_ON_PURPOSE:
            leave(issue, "the recorder leaves it out on purpose")
            continue
        if "*" in [str(p) for p in patterns or ()]:
            leave(issue, "everything is on the protected entities list")
            continue
        if _protected(sid, patterns, tokens):
            leave(issue, "it is on the protected entities list")
            continue
        if (sid, kind) in kept_keys:
            leave(issue, "the owner put brAIn's fix back")
            continue
        state = live.get(sid)
        if kind == UNITS_CHANGED:
            unit = data.get("state_unit")
            now_unit = ((state or {}).get("attributes") or {}).get(
                "unit_of_measurement")
            if ("state_unit_class" not in data
                    or "metadata_unit_class" not in data):
                # Without both classes nothing here can tell a relabel from
                # a conversion, and "could not tell" is not "no shared
                # class": a Core that leaves them out is left alone.
                leave(issue, "Home Assistant did not say whether the two "
                             "units convert, so brAIn leaves it")
            elif (data["state_unit_class"]
                  and data["state_unit_class"] == data["metadata_unit_class"]):
                # Wh → kWh: the old values would need converting, and a
                # relabel would make each one mean a thousand times less.
                leave(issue, "the old values would need converting, which "
                             "brAIn does not do on its own")
            elif not unit:
                leave(issue, "the sensor reports no unit to set")
            elif state is None or now_unit != unit:
                leave(issue, "the sensor's live unit does not match yet")
            else:
                out["fix"].append({
                    **issue, "action": "unit",
                    "command": {"type": "recorder/update_statistics_metadata",
                                "statistic_id": sid,
                                "unit_class": data.get("state_unit_class"),
                                "unit_of_measurement": unit},
                    "undo": {"type": "recorder/update_statistics_metadata",
                             "statistic_id": sid,
                             "unit_class": data.get("metadata_unit_class"),
                             "unit_of_measurement": data.get("metadata_unit")},
                    "before": data.get("metadata_unit"), "after": unit})
            continue
        if kind == NO_STATE:
            if state is not None:
                leave(issue, "the sensor reports again")
            elif reg is None:
                leave(issue, "the entity registry could not be read")
            elif not running:
                if sid in seen_missing:
                    out["missing"][sid] = seen_missing[sid]
                leave(issue, "Home Assistant is still starting")
            elif sid not in reg:
                first = seen_missing.get(sid)
                out["missing"][sid] = first if first is not None else now
                if first is None or now - float(first) < MISSING_FOR_S:
                    leave(issue, "not in the entity registry; brAIn looks "
                                 "again before clearing it")
                else:
                    out["clear"].append({**issue, "action": "clear",
                                         "gone": "removed",
                                         "command": _clear(sid)})
            elif reg[sid].get("disabled_by"):
                out["clear"].append({**issue, "action": "clear",
                                     "gone": "disabled",
                                     "command": _clear(sid)})
            else:
                leave(issue, "the entity exists and has not reported yet")
            continue
        if kind in CLEAR_ONLY:
            if state is None:
                leave(issue, "the sensor is not reporting right now")
            else:
                out["ask"].append({**issue, "why": _WHY[kind]})
            continue
        leave(issue, "brAIn has no safe fix for this kind of issue")
    room = MAX_FIXES
    for key in ("fix", "clear"):
        out["leave"] += [{**i, "why": "more than one pass may change"}
                         for i in out[key][room:]]
        out[key] = out[key][:room]
        room = max(0, room - len(out[key]))
    return out


def _clear(sid: str) -> dict:
    return {"type": "recorder/clear_statistics", "statistic_ids": [sid]}


def verify(entries: list[dict], issues_after: list[dict]) -> list[dict]:
    """Each entry with `held`: its issue no longer reported."""
    still = {(i["statistic_id"], i["type"]) for i in issues_after or []}
    return [{**e, "held": (e.get("statistic_id"), e.get("type")) not in still}
            for e in entries]


def entry(action: dict, *, ok: bool, error: str, at: float,
          channel: str = CHANNEL) -> dict:
    """What the store keeps of one change."""
    return {
        "id": f"{int(at * 1000)}-{action['statistic_id']}"[:120],
        "at": int(at), "statistic_id": action["statistic_id"],
        "type": action["type"], "action": action["action"],
        "before": action.get("before"), "after": action.get("after"),
        "gone": action.get("gone", ""), "undo": action.get("undo"),
        "channel": channel, "ok": bool(ok), "error": str(error or "")[:200],
        "held": None, "undone_at": 0,
    }


def _name(sid: str, names: dict | None) -> str:
    row = (names or {}).get(sid) if isinstance(names, dict) else None
    name = (row or {}).get("name") if isinstance(row, dict) else ""
    if name:
        return str(name)
    obj = sid.split(".", 1)[-1] if "." in sid else sid
    return obj.replace("_", " ").strip() or sid


def _join(words: list[str]) -> str:
    shown = words[:MAX_NAMED]
    more = len(words) - len(shown)
    if more > 0:
        return ", ".join(shown) + f" and {more} more"
    if len(shown) <= 1:
        return "".join(shown)
    return ", ".join(shown[:-1]) + " and " + shown[-1]


def ask_row(asks: list[dict], names: dict | None = None) -> dict | None:
    """The one question for the statistics only a deletion would fix."""
    if not asks:
        return None
    named = [_name(a["statistic_id"], names) for a in asks]
    reasons = []
    for a in asks[:MAX_NAMED]:
        reasons.append(f"{_name(a['statistic_id'], names)}: {a['why']}")
    many = len(asks) > 1
    text = (f"Clear the old long-term statistics of {_join(named)}?")
    claim = ("Home Assistant flags the long-term statistics of "
             f"{_join(named)}. " + "; ".join(reasons) + ". The only fix "
             "Home Assistant offers deletes that history, so brAIn has not "
             "done it on its own. Shall brAIn clear "
             + ("them" if many else "it") + "? The sensor"
             + ("s keep" if many else " keeps")
             + " recording from now on either way.")
    return {"text": text, "claim": claim, "detail": "", "fix": "",
            "kind": "question", "severity": "info", "fixable": False,
            "source": SOURCE, "source_title": SOURCE_TITLE,
            "entity_id": asks[0]["statistic_id"] if not many else ""}


def change_title(e: dict, names: dict | None = None) -> str:
    """One History line for one stored change."""
    who = _name(str(e.get("statistic_id") or ""), names)
    if e.get("action") == "unit":
        title = (f"Set the unit of {who}'s long-term statistics to "
                 f"{e.get('after')} (it was {e.get('before') or 'none'})")
    else:
        why = {"removed": ", which no longer exists",
               "disabled": ", which is disabled"}.get(str(e.get("gone") or ""), "")
        title = f"Cleared the old long-term statistics of {who}{why}"
    if e.get("ok") and e.get("held") is False:
        title += " — Home Assistant still flags it"
    return title


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: Path | str | None = None) -> dict:
    import json  # noqa: PLC0415

    try:
        with open(Path(path) if path else STORE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("changes", [])
    data.setdefault("kept", [])
    # The open questions: `{statistic_id, type, at, card}`, `card` the id
    # (a finding's `ts`) of the card that named it.
    data.setdefault("asked", [])
    # The Nos: `{statistic_id: {"at", "card", "type"}}`.
    if not isinstance(data.get("declined"), dict):
        data["declined"] = {}
    return data


def save(store: dict, path: Path | str | None = None,
         now: float | None = None) -> None:
    now = time.time() if now is None else now
    since = now - KEEP_DAYS * 86400
    store["changes"] = [c for c in store.get("changes") or []
                        if float(c.get("at") or 0) >= since][-200:]
    store["declined"] = {
        sid: rec for sid, rec in (store.get("declined") or {}).items()
        if isinstance(rec, dict) and now - float(rec.get("at") or 0) < DECLINED_S}
    atomic_write.write_json(Path(path) if path else STORE, store)


def due(store: dict, now: float, *, core_version: str = "",
        booted: bool = False, core_loaded_at: float = 0.0) -> bool:
    """A pass is due daily, on the first tick after brAIn starts, as soon as
    Core's version is not the one the last pass saw, when Core has started
    again since the last pass (`core_loaded_at`: when brAIn's integration
    last set up inside Core, which is every Core start), and an hour after
    a pass that found Core still starting — never on every poll."""
    if booted:
        return True
    if core_version and store.get("core_version") \
            and core_version != store.get("core_version"):
        return True
    seen = float(store.get("core_loaded_at") or 0)
    if core_loaded_at and seen and float(core_loaded_at) != seen:
        return True
    last = float(store.get("last_run") or 0)
    # An unknown state (`get_config` unanswered) is a Core mid-restart too,
    # so a recorded state that is anything but RUNNING is retried.
    if "core_state" in store and store.get("core_state") != CORE_RUNNING \
            and now - last >= RETRY_S:
        return True
    return now - last >= INTERVAL_S


# -- the questions, one list per card -----------------------------------------

def open_questions(store: dict, live_cards) -> list[dict]:
    """The asked entries whose card is still on Today. `live_cards` is the
    ids (a finding's `ts`) of the statistics cards the findings store still
    holds, or None when it could not be read: "could not tell" drops
    nothing. An entry whose card is gone unanswered is dropped, so its
    statistic is asked about again while it is flagged."""
    asked = [dict(a) for a in store.get("asked") or [] if a.get("statistic_id")]
    if live_cards is None:
        return asked
    live = {str(c) for c in live_cards}
    return [a for a in asked if str(a.get("card")) in live]


def to_ask(store: dict, asks: list[dict], now: float) -> list[dict]:
    """The asks not already on a card and not said No to within
    `DECLINED_S`."""
    open_ids = {a.get("statistic_id") for a in store.get("asked") or []}
    declined = store.get("declined") or {}
    out = []
    for a in asks or []:
        sid = a["statistic_id"]
        if sid in open_ids:
            continue
        rec = declined.get(sid)
        if isinstance(rec, dict) and now - float(rec.get("at") or 0) < DECLINED_S:
            continue
        out.append(a)
    return out


def note_asked(store: dict, asks: list[dict], card, now: float) -> None:
    """These statistics are on the card `card`. A No that had lapsed goes:
    the new card's answer is the one that counts now."""
    store.setdefault("asked", []).extend(
        {"statistic_id": a["statistic_id"], "type": a.get("type"),
         "at": int(now), "card": str(card)} for a in asks)
    for a in asks:
        (store.get("declined") or {}).pop(a["statistic_id"], None)


def note_declined(store: dict, asks: list[dict], now: float,
                  card: str = "") -> None:
    declined = store.setdefault("declined", {})
    for a in asks:
        declined[a["statistic_id"]] = {"at": int(now), "card": str(card),
                                       "type": a.get("type")}


def answer(store: dict, card, *, outcome: str, now: float) -> list[dict]:
    """The card `card` was answered: its entries, taken off `asked`.
    `outcome` is "accepted" (Yes: the caller clears what is still flagged),
    "declined" (No: remembered) or "dropped" (Doesn't apply: nothing
    recorded). Another card's entries are never touched."""
    card = str(card)
    mine = [a for a in store.get("asked") or [] if str(a.get("card")) == card]
    store["asked"] = [a for a in store.get("asked") or []
                      if str(a.get("card")) != card]
    if outcome == "declined":
        note_declined(store, mine, now, card)
    return mine


def forget_answer(store: dict, card) -> int:
    """Undo of a No: the card is back, so its Nos go and its statistics are
    its open question again. Returns how many."""
    card = str(card)
    declined = store.get("declined") or {}
    back = [(sid, rec) for sid, rec in declined.items()
            if isinstance(rec, dict) and str(rec.get("card")) == card]
    for sid, rec in back:
        declined.pop(sid, None)
        store.setdefault("asked", []).append(
            {"statistic_id": sid, "type": rec.get("type"),
             "at": int(rec.get("at") or 0), "card": card})
    return len(back)


def undoable(store: dict) -> dict[str, dict]:
    """The changes History may offer Undo on, by id: a unit fix that
    worked, is not undone, and is the newest change to its statistic."""
    newest: dict[str, str] = {}
    for c in sorted(store.get("changes") or [],
                    key=lambda c: float(c.get("at") or 0)):
        newest[str(c.get("statistic_id"))] = str(c.get("id"))
    return {str(c["id"]): c for c in store.get("changes") or []
            if c.get("action") == "unit" and c.get("ok")
            and not c.get("undone_at") and isinstance(c.get("undo"), dict)
            and newest.get(str(c.get("statistic_id"))) == str(c.get("id"))}


def mark_undone(store: dict, change_id: str, at: float) -> dict | None:
    """The change, marked undone, and its issue kept from now on."""
    for c in store.get("changes") or []:
        if str(c.get("id")) == change_id:
            c["undone_at"] = int(at)
            key = [str(c.get("statistic_id")), str(c.get("type"))]
            if key not in store.setdefault("kept", []):
                store["kept"].append(key)
            return c
    return None


__all__ = [
    "CHANNEL", "CLEAR_ONLY", "DECLINED_S", "EXCLUDED_ON_PURPOSE",
    "INTERVAL_S", "RETRY_S", "SOURCE", "SOURCE_TITLE", "answer", "ask_row",
    "change_title", "due", "entry", "forget_answer", "issues_from", "load",
    "mark_undone", "note_asked", "note_declined", "open_questions", "plan",
    "save", "to_ask", "undoable", "verify",
]
