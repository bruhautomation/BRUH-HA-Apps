"""Proposals — what could be better, and the change that would make it so.

brAIn keeps four kinds of knowledge apart on purpose, because mixing them
makes each one worse. Memory is what is *true*. A hypothesis is what brAIn
might have *wrong*. A finding is what is *broken*. Activity is what
*happened*. This is the fifth: what could be **better**.

It gets its own store and its own tab rather than joining the work list,
and that is not tidiness. A list of things you might want, sitting beside
a list of things that are broken, makes both worse — the broken things
stop looking urgent and the nice-to-haves start to. The Findings tab
empties; this one does not have to.

The lifecycle is short, because a list of suggestions nobody ever answers
is a second inbox:

    proposed ──"Try it"──▶ trialling ──▶ accepted   it is a real automation now
             └──"No"──────────────────▶ declined    with a note that teaches

**Nothing brAIn writes is ever enabled without a trial**, and that is the
whole point of the store existing. A trial runs the proposed automation in
shadow — evaluating against live events and logging what it *would* have
done, calling nothing — and reports at the end: *it would have fired six
times; on five of those you did the same thing by hand within three
minutes; on one you did not.* An automation you accepted after watching it
be right five times out of six is a different object from one you accepted
because it sounded reasonable.

**A decline carries a note, and the note is the half that teaches.** "No"
suppresses one proposal; *"the hall light stays on because my partner works
nights"* is a fact brAIn did not have, and it is the difference between a
list that gets quieter and one that keeps making the same suggestion in new
words. It goes to the memory inbox exactly as a finding's "Wrong" does —
and the box is never required, because a mandatory field turns a one-press
dismissal into a chore and fills up with "no".

**A declined proposal is remembered by its KEY, not by its row.** The rows
are prunable and the ledger is not, for the same reason the findings ledger
is an index rather than a queue: sweeping it is how a suggestion you
already answered comes back next month.

**Nothing here writes an automation.** The store records what was decided;
performing an accepted change is the server's, through the same path the
fixer already uses. A store that could edit `/config` would be a second
writer to somebody's automations with none of the snapshotting the first
one has.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

import atomic_write

STORE = Path(os.environ.get("BRAIN_PROPOSALS_FILE", "/data/proposals.json"))
SETTLED_FILE = Path(os.environ.get(
    "BRAIN_PROPOSALS_SETTLED", "/data/proposals-settled.json"))
# Home Assistant cannot see /data, so the tab's own state is republished
# here for the integration to read — derived, never read back.
SHARED = Path(os.environ.get("BRAIN_PROPOSALS_SHARED",
                             "/config/.brain/proposals_state.json"))

STATUSES = ("proposed", "trialling", "accepted", "declined")
# The two a person still owes an answer on. `open` spans both, because
# "how much is waiting on me" is the only question a badge answers.
OPEN_STATUSES = ("proposed", "trialling")

# Seven days, which is the shortest window that contains a whole week of
# a household's habits — a trial over three days answers about Tuesday.
TRIAL_DAYS = 7
# More than this on the tab and it has stopped being a list of things you
# might want and become a second inbox. New proposals are refused rather
# than pushing an unanswered one out.
MAX_OPEN = 12
MAX_ROWS = 200
MAX_SETTLED = 500
NOTE_MAX = 500
TITLE_MAX = 160


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

def key_for(obj: dict) -> str:
    """What makes two proposals the same proposal.

    The **automation**, not the sentence describing it: a miner that
    rewords its own explanation next month is still offering the change
    you already declined, and keying on the prose would offer it again.
    """
    config = obj.get("config")
    if config:
        body = json.dumps(config, sort_keys=True, separators=(",", ":"))
    else:
        body = _normalise(str(obj.get("title") or ""))
    return hashlib.sha256(
        f"{obj.get('kind') or ''}|{body}".encode()).hexdigest()[:16]


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def _read(path: Path, root: str) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get(root) if isinstance(data, dict) else data
    return [r for r in (rows or []) if isinstance(r, dict)]


def listing() -> list[dict]:
    """Every proposal, newest first."""
    return sorted(_read(STORE, "proposals"),
                  key=lambda r: r.get("ts", 0), reverse=True)


def _write(rows: list[dict]) -> None:
    rows = rows[-MAX_ROWS:]
    atomic_write.write_json(STORE, {"proposals": rows})
    publish_state(rows)


def settled_keys() -> dict[str, dict]:
    return {r["key"]: r for r in _read(SETTLED_FILE, "settled") if r.get("key")}


def _write_settled(rows: list[dict]) -> None:
    atomic_write.write_json(SETTLED_FILE, {"settled": rows[-MAX_SETTLED:]})


def publish_state(rows: list[dict] | None = None) -> None:
    """Republish the mirror. Skipped where the shared volume is absent.

    Hooked into every write rather than called by the caller, so no path
    can change the store without the mirror following — the arrangement
    `findings_store` already keeps. An OSError is a warning and never a
    lost proposal: the row is safe in /data before this is touched.
    """
    rows = listing() if rows is None else rows
    if not SHARED.parent.parent.exists():
        return                       # a dev checkout must not grow a /config
    payload = {
        "generated_at": int(_now()),
        "open": sum(1 for r in rows if r.get("status") in OPEN_STATUSES),
        "proposals": [{k: r.get(k) for k in
                       ("ts", "key", "kind", "title", "why", "status",
                        "source", "trial_ends_at")}
                      for r in rows if r.get("status") in OPEN_STATUSES],
    }
    try:
        SHARED.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(SHARED, payload)
    except OSError:
        pass                         # see the docstring: never a lost row


# ---------------------------------------------------------------------------
# Offering one
# ---------------------------------------------------------------------------

def add(obj: dict) -> dict | None:
    """Offer a proposal, or `None` if it is already known or the tab is full.

    Deduped against the live rows **and** the settled ledger, so a
    proposal you declined in March is not offered again in April by a
    miner that has forgotten it asked.
    """
    key = key_for(obj)
    rows = listing()
    if any(r.get("key") == key for r in rows):
        return None
    if key in settled_keys():
        return None
    if sum(1 for r in rows if r.get("status") in OPEN_STATUSES) >= MAX_OPEN:
        # Refused rather than pushing an unanswered one out: a list that
        # silently drops what you have not answered is worse than one
        # that stops growing.
        return None

    row = {
        "ts": int(_now() * 1000),
        "key": key,
        "kind": str(obj.get("kind") or "automation")[:40],
        "title": str(obj.get("title") or "")[:TITLE_MAX],
        "why": str(obj.get("why") or "")[:1000],
        "source": str(obj.get("source") or "")[:60],
        "config": obj.get("config"),
        "replay": obj.get("replay"),
        "status": "proposed",
        "note": "",
    }
    if not row["title"]:
        return None
    rows.append(row)
    _write(rows)
    return row


def get(ts: int) -> dict | None:
    for row in listing():
        if row.get("ts") == ts:
            return row
    return None


# ---------------------------------------------------------------------------
# Answering one
# ---------------------------------------------------------------------------

def start_trial(ts: int, now: float | None = None) -> dict | None:
    """Move a proposal into its shadow week. Only from `proposed`."""
    now = _now() if now is None else now
    rows = listing()
    for row in rows:
        if row.get("ts") != ts:
            continue
        if row.get("status") != "proposed":
            return None
        row["status"] = "trialling"
        row["trial_started_at"] = int(now)
        row["trial_ends_at"] = int(now + TRIAL_DAYS * 86400)
        _write(rows)
        return row
    return None


def trial_due(row: dict, now: float | None = None) -> bool:
    """Whether a trial has run its week."""
    now = _now() if now is None else now
    return (row.get("status") == "trialling"
            and now >= (row.get("trial_ends_at") or 0))


def record_trial(ts: int, result: dict) -> dict | None:
    """Attach what the shadow week saw. Does not end the trial.

    Separate from `start_trial` and from the endings on purpose: the
    report is evidence a person reads, and a store that ended a trial by
    writing its own result would be deciding the thing it is reporting
    on.
    """
    rows = listing()
    for row in rows:
        if row.get("ts") == ts and row.get("status") == "trialling":
            row["trial_result"] = result
            _write(rows)
            return row
    return None


def _settle(row: dict, status: str, note: str, now: float) -> None:
    ledger = _read(SETTLED_FILE, "settled")
    ledger.append({
        "key": row.get("key"),
        "kind": row.get("kind"),
        "title": row.get("title"),
        "status": status,
        "note": note,
        "source": row.get("source"),
        "settled_at": int(now),
    })
    _write_settled(ledger)


def decide(ts: int, status: str, note: str = "",
           now: float | None = None) -> dict | None:
    """Accept or decline. The row leaves the list and the key is remembered.

    `note` is optional by design — "not for me" needs no essay, and a
    required field turns a one-press dismissal into a chore.
    """
    if status not in ("accepted", "declined"):
        return None
    now = _now() if now is None else now
    rows = listing()
    for i, row in enumerate(rows):
        if row.get("ts") != ts:
            continue
        if row.get("status") not in OPEN_STATUSES:
            return None
        note = str(note or "").strip()[:NOTE_MAX]
        row["status"] = status
        row["note"] = note
        row["decided_at"] = int(now)
        _settle(row, status, note, now)
        rows.pop(i)
        _write(rows)
        return row
    return None


def memory_line(row: dict, status: str) -> str:
    """The plain fact an ending records, in the homeowner's own words.

    A decline with a reason is a fact about the house; one without is a
    preference about a suggestion, which memory has no use for. An accept
    is always worth recording: the house now behaves differently.
    """
    title = row.get("title") or "a proposal"
    if status == "accepted":
        return f"Accepted brAIn's suggestion: {title}"
    note = (row.get("note") or "").strip()
    if not note:
        return ""
    return f"Declined brAIn's suggestion ({title}). They said: {note}"


def counts(rows: list[dict] | None = None) -> dict:
    rows = listing() if rows is None else rows
    out = {s: 0 for s in STATUSES}
    for row in rows:
        status = row.get("status")
        if status in out:
            out[status] += 1
    out["open"] = sum(out[s] for s in OPEN_STATUSES)
    return out


__all__ = [
    "MAX_OPEN", "MAX_ROWS", "OPEN_STATUSES", "SETTLED_FILE", "SHARED",
    "STATUSES", "STORE", "TRIAL_DAYS", "add", "counts", "decide", "get",
    "key_for", "listing", "memory_line", "publish_state", "record_trial",
    "settled_keys", "start_trial", "trial_due",
]
