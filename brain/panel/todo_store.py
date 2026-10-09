"""The work you have accepted — a list that outlives the card that raised it.

A finding is brAIn saying *this looks broken*. Every ending it had was a
decision made on the spot: it is fixed, it was never a problem, come back
tomorrow. There was no way to say the one thing people actually say, which
is **yes, that is real, and I will do it** — so a battery that needs
replacing sat on the Findings tab as an open question for as long as it
took to get round to it, and the tab stopped being a list of decisions
waiting on somebody and became a list of chores nobody had a place for.

This is that place. Moving a finding here is its fourth ending: the row is
deleted, the settled key is written so nothing re-raises it, and everything
the card held arrives here as an item. And you can add your own, because a
list that only holds what brAIn noticed is not a list of what needs doing.

Six rules, and the first two are the ones that make it a different thing
from the To-do entity brAIn already shipped.

**An item carries the finding's evidence, never a pointer to it.** The
whole point of the move is that the finding row goes away, so a reference
to it would dangle by construction — the text, the detail, the suggested
fix, the entity and who raised it are copied at the moment of the move and
belong to the item afterwards. That is also what makes a hand-added item
the same kind of thing as a moved one rather than a second-class row.

**The id is minted past what is already taken.** `int(time.time() * 1000)`
is not an id: a checks pass moving three rows in a loop measured four
distinct stamps out of eight adds in `proposals.add`, and two items under
one id means the second press answers the first item. This is the same
guard, in the module that would otherwise repeat the bug.

**Completing writes the memory line the move deliberately did not.** "I
will do this later" says nothing true about the house — the battery is
still flat — so the move settles the key and files no fact. The fact is
written when the thing is actually done, which is when it becomes true,
and it is the same sentence `done` on the Findings tab would have written.

**Dropping an item without doing it puts the problem back in play.** You
decided not to, so it is presumably still there: the settled key is
released and the next checks pass is free to find it again, which is
`clear_resolved`'s own argument — if it really has stopped being true,
nothing comes back. A hand-added item has no key and releases nothing.

**Done items are kept, capped, and counted by nothing.** The Findings tab
refuses an archive because memory is the record, and that rule is about
*decisions*; this is a list of chores, and a chore list that forgets what
you did this week cannot answer "did I already do that". So they stay,
behind a filter that hides at zero, absent from every count, with one
verb — the same shape the Answered filter carries.

**And the store is the panel's**, in `/data`, mirrored to the shared
volume for the integration exactly as the findings store is. Home
Assistant cannot reach the panel's port, so what crosses the gap is a
mirror out and a request back, and there is still one writer.

Stdlib only, so the test suite can import it without the add-on runtime.
"""
from __future__ import annotations

import atomic_write

import functools
import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("brain.todo")

TODO_FILE = Path(os.environ.get("BRAIN_TODO_FILE", "/data/todo.json"))
# The integration's copy. Derived, never read back, republished on every
# write — the findings mirror's contract, for the findings mirror's reason.
STATE_FILE = Path(os.environ.get(
    "BRAIN_TODO_STATE", "/config/.brain/todo_state.json"))

# Longer than anybody's real list, short enough that a runaway producer
# cannot fill a disk. Oldest open items are never dropped: the cap is
# enforced by refusing the add, because silently losing the bottom of
# somebody's to-do list is the one failure this store must not have.
MAX_OPEN = 200
# What "did I already do that" needs, and no more.
MAX_DONE = 50

MAX_TEXT = 200
MAX_DETAIL = 600
MAX_FIX = 600
MAX_NOTE = 400

STATUSES = ("open", "done")
SEVERITIES = ("info", "warning", "serious", "critical")
# Where an item came from. `finding` is a moved card and carries a settled
# key; `hand` is one somebody typed and carries none — which is the whole
# difference dropping one has to know about.
ORIGINS = ("finding", "hand")

_LOCK = threading.RLock()


def _mutates(fn):
    """Serialise writers, and republish the mirror after every one.

    Hooked here rather than at the call sites so no code path can change
    the store without the integration seeing it — `findings_store._write`'s
    arrangement, for the same reason.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOCK:
            result = fn(*args, **kwargs)
            publish_state()
            return result
    return wrapper


def _load() -> list[dict]:
    try:
        raw = json.loads(TODO_FILE.read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


def _write(items: list[dict]) -> None:
    TODO_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write.write_json(TODO_FILE, items)


def _clean(value, cap: int) -> str:
    return str(value or "").strip()[:cap]


def _shape(entry: dict) -> dict:
    """One stored row, in the shape every reader gets."""
    status = entry.get("status")
    if status not in STATUSES:
        status = "open"
    severity = entry.get("severity")
    if severity not in SEVERITIES:
        severity = "warning"
    origin = entry.get("origin")
    if origin not in ORIGINS:
        origin = "hand"
    return {
        "id": int(entry.get("id") or 0),
        "text": _clean(entry.get("text"), MAX_TEXT),
        "detail": _clean(entry.get("detail"), MAX_DETAIL),
        "fix": _clean(entry.get("fix"), MAX_FIX),
        "entity_id": _clean(entry.get("entity_id"), 120),
        "severity": severity,
        "origin": origin,
        # Who raised it, carried from the finding so the scorecard and the
        # tab can both still say where this came from once the row is gone.
        "source": _clean(entry.get("source"), 64),
        "source_title": _clean(entry.get("source_title"), 120),
        # What the settled ledger has under suppression on this item's
        # behalf. Dropping the item is what releases it; nothing else here
        # ever touches the ledger.
        "finding_key": _clean(entry.get("finding_key"), 240),
        "run_id": _clean(entry.get("run_id"), 120),
        "status": status,
        "added_at": int(entry.get("added_at") or 0),
        "done_at": int(entry.get("done_at") or 0),
        "note": _clean(entry.get("note"), MAX_NOTE),
        # When the check that filed it said it was not done after all.
        "came_back": int(entry.get("came_back") or 0),
        # A finding about this item's entity that was NOT filed because the
        # item is open (`findings_store.add_many`): when it was last seen,
        # how many times, and what the report said. The To Do row says so,
        # because a chore nobody has got round to that the house keeps
        # reporting is worth a line, and a second card for it is not.
        "seen_again_at": int(entry.get("seen_again_at") or 0),
        "seen_again": int(entry.get("seen_again") or 0),
        "seen_again_text": _clean(entry.get("seen_again_text"), MAX_TEXT),
    }


def _next_id(items: list[dict], now: float | None = None) -> int:
    """A millisecond, bumped past anything already taken.

    `int(time.time() * 1000)` alone is not an id. A checks pass moving
    several rows in one loop does each add well inside a millisecond, and
    two items under one id is not cosmetic: every press on this tab keys
    on it, so the second of a pair would answer the first. `proposals.add`
    shipped without this guard and `intents.note` had carried it since it
    was written — a rule that exists in one module and not in its sibling
    is a rule nobody can see is missing.
    """
    stamp = int((now if now is not None else time.time()) * 1000)
    taken = {int(e.get("id") or 0) for e in items}
    while stamp in taken:
        stamp += 1
    return stamp


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def listing() -> dict:
    """Everything the To-do tab reads, and the only thing it reads."""
    items = [_shape(e) for e in _load()]
    open_items = [i for i in items if i["status"] == "open"]
    done = [i for i in items if i["status"] == "done"]
    open_items.sort(key=lambda i: (-SEVERITIES.index(i["severity"]),
                                   i["added_at"]))
    done.sort(key=lambda i: -(i["done_at"] or i["added_at"]))
    return {
        "items": open_items,
        "done": done[:MAX_DONE],
        # What a badge means here: things you have agreed to do and have
        # not done. A finished chore is waiting on nobody.
        "open": len(open_items),
        "done_count": len(done),
    }


def get(item_id: int) -> dict | None:
    for entry in _load():
        if int(entry.get("id") or 0) == int(item_id):
            return _shape(entry)
    return None


def open_entities() -> dict[str, int]:
    """`{entity id: item id}` for the open items that name an entity.

    What `findings_store.add_many` asks before filing a row: a report about
    an entity somebody has already put on this list is a chore they agreed
    to, not a new decision. A list that cannot be read answers `{}` —
    holding back nothing, the direction in which being wrong shows a card.
    """
    out: dict[str, int] = {}
    for entry in _load():
        item = _shape(entry)
        if item["status"] == "open" and item["entity_id"]:
            out.setdefault(item["entity_id"], item["id"])
    return out


@_mutates
def seen_again(item_id: int, text: str = "",
               now: float | None = None) -> dict | None:
    """Note on an open item that the house reported its problem again.

    Returns the item as it now is, or None if it is gone or finished — a
    finished chore is not one a report can be held for.
    """
    items = _load()
    found = None
    for entry in items:
        if int(entry.get("id") or 0) != int(item_id):
            continue
        if entry.get("status", "open") != "open":
            return None
        entry["seen_again_at"] = int(now if now is not None else time.time())
        entry["seen_again"] = int(entry.get("seen_again") or 0) + 1
        if str(text or "").strip():
            entry["seen_again_text"] = _clean(text, MAX_TEXT)
        found = _shape(entry)
        break
    if found is None:
        return None
    _write(items)
    return found


def counts() -> dict:
    """`open` is every open item the store holds; `shown` is what the To Do
    section lists (open and not snoozed) — the To Do count."""
    listed = listing()
    return {"open": listed["open"], "done": listed["done_count"],
            "shown": shown()["open"]}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

@_mutates
def add(text: str, *, detail: str = "", fix: str = "", entity_id: str = "",
        severity: str = "warning", origin: str = "hand", source: str = "",
        source_title: str = "", finding_key: str = "", run_id: str = "",
        now: float | None = None) -> dict | None:
    """Put something on the list. Returns the item, or None if it is not one.

    A blank line is not a chore, and neither is one past the cap: the add
    is refused rather than making room, because the room would be made by
    dropping something somebody else put there.
    """
    text = _clean(text, MAX_TEXT)
    if not text:
        return None
    items = _load()
    if len([e for e in items if e.get("status", "open") == "open"]) >= MAX_OPEN:
        return None
    entry = _shape({
        "id": _next_id(items, now),
        "text": text,
        "detail": detail,
        "fix": fix,
        "entity_id": entity_id,
        "severity": severity,
        "origin": origin,
        "source": source,
        "source_title": source_title,
        "finding_key": finding_key,
        "run_id": run_id,
        "status": "open",
        "added_at": int(now if now is not None else time.time()),
    })
    items.append(entry)
    _write(_pruned(items))
    return entry


def _pruned(items: list[dict]) -> list[dict]:
    """Keep every open item and the newest `MAX_DONE` finished ones."""
    open_items = [e for e in items if e.get("status", "open") != "done"]
    done = sorted([e for e in items if e.get("status") == "done"],
                  key=lambda e: -(int(e.get("done_at") or 0)))
    return open_items + done[:MAX_DONE]


@_mutates
def complete(item_id: int, note: str = "",
             now: float | None = None) -> dict | None:
    """Tick one off. Returns the item as it now is, or None if it is gone."""
    items = _load()
    found = None
    for entry in items:
        if int(entry.get("id") or 0) == int(item_id):
            if entry.get("status") == "done":
                return _shape(entry)
            entry["status"] = "done"
            entry["done_at"] = int(now if now is not None else time.time())
            entry["note"] = _clean(note, MAX_NOTE)
            found = _shape(entry)
            break
    if found is None:
        return None
    _write(_pruned(items))
    return found


@_mutates
def reopen(item_id: int) -> dict | None:
    """Put a finished item back — the toast's Undo, and nothing else."""
    items = _load()
    found = None
    for entry in items:
        if int(entry.get("id") or 0) == int(item_id):
            entry["status"] = "open"
            entry["done_at"] = 0
            entry["note"] = ""
            found = _shape(entry)
            break
    if found is None:
        return None
    _write(items)
    return found


# A chore that came from a house check is ticked off on somebody's word,
# and the check that filed it is the one reading that can say whether it
# is done: a ZSE44 still at 0% twelve days after "Done", an integration
# still in setup_retry. So a check that RAN and still reports the problem,
# past this long after the tick, puts the chore back on the list saying
# so. Long enough that a sleepy battery device has reported its new level
# and a reloaded integration has finished setting up; a check that did not
# run reopens nothing, `clear_resolved`'s rule.
CHORE_SETTLE_S = 2 * 3600
# Checks that can see a chore happen and cannot see it done. A printer's
# status says "finish" until the next job starts, whatever was taken off
# the bed, so re-running `chore.job_done` after the tick reports exactly
# what it reported before it — and putting the chore back "because the
# check still reports it" would be the check contradicting a person about
# the one fact it has no way to read. Their chores end on the press.
UNSEEN_DONE_SOURCES = frozenset({"check:chore.job_done"})
CAME_BACK_NOTE = ("Came back: the check that reported this still reports it "
                  "after you marked it done.")


def still_reported(sources: set[str], keep_keys: set[str],
                   now: float | None = None) -> list[dict]:
    """Done chores from a check in ``sources`` whose key that pass still
    reported, past `CHORE_SETTLE_S`. A read: nothing is written."""
    now = time.time() if now is None else float(now)
    out = []
    for entry in _load():
        item = _shape(entry)
        if (item["status"] == "done" and item["origin"] == "finding"
                and item["source"].startswith("check:")
                and item["source"] in sources
                and item["source"] not in UNSEEN_DONE_SOURCES
                and item["finding_key"] in keep_keys
                and item["done_at"]
                and now - item["done_at"] >= CHORE_SETTLE_S):
            out.append(item)
    return out


@_mutates
def came_back(item_ids: list[int], now: float | None = None) -> list[dict]:
    """Put finished chores back on the list because they are not done.

    Not `reopen` (the toast's Undo, which clears the note): this one says
    why, and stamps `came_back`, so the item reads as the check speaking
    rather than as somebody's mis-tap. Returns the items reopened.
    """
    now = time.time() if now is None else float(now)
    wanted = {int(i) for i in item_ids}
    items = _load()
    out = []
    for entry in items:
        if (int(entry.get("id") or 0) in wanted
                and entry.get("status") == "done"):
            entry["status"] = "open"
            entry["done_at"] = 0
            entry["came_back"] = int(now)
            entry["note"] = CAME_BACK_NOTE
            out.append(_shape(entry))
    if out:
        _write(items)
    return out


@_mutates
def restore(item: dict) -> dict | None:
    """Put a removed item back under its own id — the Undo for a drop.

    Refused over an occupied id, `findings_store.restore`'s rule: if
    something else has taken it, the list holds something newer and
    putting this back would throw that away.
    """
    shaped = _shape(item)
    if not shaped["text"] or not shaped["id"]:
        return None
    items = _load()
    if any(int(e.get("id") or 0) == shaped["id"] for e in items):
        return None
    items.append(shaped)
    _write(_pruned(items))
    return shaped


@_mutates
def remove(item_id: int) -> dict | None:
    """Take one off the list entirely. Returns what was removed."""
    items = _load()
    removed = None
    kept = []
    for entry in items:
        if removed is None and int(entry.get("id") or 0) == int(item_id):
            removed = _shape(entry)
            continue
        kept.append(entry)
    if removed is None:
        return None
    _write(kept)
    return removed


# ---------------------------------------------------------------------------
# The mirror
# ---------------------------------------------------------------------------

# Which open items are asleep: `{case id: epoch}` off the cases' snooze
# sidecar (`t:<id>`), handed in by the panel at import because `cases`
# reads this store and so this store may not import it. Snooze on a To Do
# row hides it on the panel until it lapses; the mirror has to hide it too,
# or the To-do app lists chores the section it copies does not.
SNOOZED = None

_LAST_PUBLISHED: str | None = None


def _asleep(now: float) -> dict[int, int]:
    """`{item id: until}` for the items whose snooze has not lapsed. A
    sidecar that cannot be read hides nothing — `cases._read_snoozes`'
    direction, one extra row rather than a hidden one."""
    if SNOOZED is None:
        return {}
    try:
        rows = SNOOZED() or {}
    except Exception as exc:  # noqa: BLE001 — never hide a chore over a read
        log.debug("could not read the to-do snoozes: %s", exc)
        return {}
    out: dict[int, int] = {}
    for key, until in rows.items():
        if not str(key).startswith("t:"):
            continue
        try:
            item_id, until = int(str(key)[2:]), int(until)
        except (TypeError, ValueError):
            continue
        if until > now:
            out[item_id] = until
    return out


def shown(now: float | None = None) -> dict:
    """What the panel's To Do section lists: the open items that are not
    snoozed, and how many are asleep. The mirror, `todo.brain` and the To
    Do count read this, so the three are one number."""
    now = time.time() if now is None else now
    listed = listing()
    asleep = _asleep(now)
    items = [i for i in listed["items"] if int(i.get("id") or 0) not in asleep]
    return {"items": items, "open": len(items),
            "snoozed": len(listed["items"]) - len(items),
            "next_wake": min(asleep.values()) if asleep else None}


def publish_state(only_if_changed: bool = False) -> bool:
    """Republish the shared-volume copy the integration reads.

    Skipped where the shared volume's parent does not exist, so a dev
    checkout does not grow a stray `/config`; an OSError is a warning and
    never a lost item, because the item is already safe in `/data` before
    this is reached. The findings mirror's rules, for its reasons.

    It lists what the panel's To Do lists — open and not snoozed. A snooze
    starts and lapses without this store being written, so the scheduler
    calls it every tick with `only_if_changed`, which writes only when
    what it would say moved. Answers whether it wrote.
    """
    global _LAST_PUBLISHED
    if not STATE_FILE.parent.parent.exists():
        return False
    try:
        view = shown()
        body = {"open": view["open"], "snoozed": view["snoozed"],
                "items": view["items"]}
        digest = json.dumps(body, sort_keys=True, default=str)
        if (only_if_changed and digest == _LAST_PUBLISHED
                and STATE_FILE.exists()):
            return False
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(STATE_FILE, {
            "generated_at": int(time.time()), **body})
        _LAST_PUBLISHED = digest
        return True
    except OSError as exc:
        log.warning("could not publish the to-do mirror: %s", exc)
        return False
