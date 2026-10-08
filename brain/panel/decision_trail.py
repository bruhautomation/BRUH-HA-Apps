"""Why brAIn said nothing — one line for every time it decided not to.

Every surface brAIn has reports what it DID: a card, a finding, a
notification, a proposal. None of them can answer the question people
actually ask when something went wrong in silence — *"why didn't you tell
me the garage was open?"* — because the decisions that produced the
silence left nothing behind. A check that gave up because a dozen sensors
looked frozen at once, a report deduped against an answer given in March,
a rule somebody corrected, a producer somebody muted, a message held for
quiet hours, a batch the usage budget would not pay for, a first look
that let a signal go: each was a deliberate choice, made for a reason the
code knew at the time and threw away.

This is where the reason goes. One JSON line per suppression, written by
the code that made it, read back by `GET /api/why` and the
`explain_decision` tool. Four rules.

**The vocabulary is closed** (:data:`KINDS`). A reader keys on it, the
panel words it, and a free-text kind is a second policy nobody can see.

**Nothing here decides anything.** Every writer has already made its
choice; this records it. A trail that also suppressed things would be a
rule hidden inside an audit log.

**"I have no record of seeing it" is an answer, and a different one from
"I decided not to".** :func:`for_subject` returning nothing is the first;
a row is the second, with its reason. The explain path is told which it
has, and a reader of an unreadable file is told that too (`readable`),
because "I could not look" is never "nothing there".

**It is a trail, not a log of every tick.** A paused house holds the same
batch every minute and a muted producer drops the same row every pass, so
an identical `(kind, subject, check, reason)` inside :data:`MERGE_S` is
the same decision and is written once: the row says when brAIn FIRST made
it, which is the instant a person is asking about. A standing decision
(:data:`FOLD_KINDS`) made again past that window folds into its row —
``count`` and ``last_seen`` — rather than being a new line every pass. The file is capped by
line count the way the run journal is, rewritten only well past the cap.

It never creates its own directory — `/data` exists in the add-on, and a
dev checkout or a test that did not point it somewhere has nowhere it
should be writing (`facts_store.writable`'s rule) — and it never raises:
every caller is in the middle of deciding something else.

Stdlib only, plus `atomic_write`.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

import atomic_write

log = logging.getLogger("brain.decisions")

TRAIL_FILE = os.environ.get("BRAIN_DECISIONS_FILE", "/data/decisions.jsonl")
MAX_LINES = 2000
# The same decision about the same thing inside this window is one row.
MERGE_S = 3600
MAX_REASON = 300
MAX_SUBJECT = 255
MAX_ENTITIES = 12

# What each kind of silence is, in the words a person reads. The keys are
# the vocabulary; `explain` and the panel render the values.
KINDS = {
    "cap": "a check gave up: too many at once to mean anything",
    "dedupe": "it had already been answered",
    "exception": "you said this is not a problem here",
    "mute": "you asked brAIn to stop raising these",
    "shadow": "the rule that found it is still on trial",
    "no_target": "no notification service is set",
    "notify_quiet": "below your notification floor, so it went to the list "
                    "only",
    "quiet_hold": "held for quiet hours",
    "gate_hold": "brAIn was not allowed to spend a run on it then",
    "look_ignore": "the first look let it go",
    "look_watch": "the first look decided to watch it",
    "held": "looked at, and held back from the list",
}

# The decisions that are STANDING answers rather than events: a re-report
# the settled ledger swallowed, a rule somebody corrected, a muted
# producer, a rule on trial, a check that gave up. Each checks pass makes
# the same one again about the same row — ten lines a day saying "you said
# you had fixed it" about one finding, which is a trail nobody can read past
# the first screen. So an identical one past `MERGE_S` FOLDS into the row
# already there: `count` goes up and `last_seen` moves, while `ts` stays the
# first time, which is still the instant a person asks about. A hold, a
# look's verdict or a notification decision is an event at a time and is
# written again past the window, as before.
FOLD_KINDS = frozenset({"dedupe", "exception", "mute", "shadow", "cap"})

_LOCK = threading.Lock()
# `(kind, subject, check, reason)` -> when it was last written. In memory:
# a restart writes the decision once more, which is one line and the
# honest answer to "it was still being made after the restart".
_RECENT: dict[tuple, float] = {}
_RECENT_MAX = 4000


def _parent_exists() -> bool:
    parent = os.path.dirname(TRAIL_FILE) or "."
    return os.path.isdir(parent)


def _clean(row: dict, now: float) -> dict | None:
    kind = str(row.get("kind") or "")
    if kind not in KINDS:
        return None
    subject = str(row.get("subject") or "").strip()[:MAX_SUBJECT]
    entities = []
    for eid in row.get("entities") or ():
        eid = str(eid or "").strip()[:MAX_SUBJECT]
        if eid and eid not in entities and len(entities) < MAX_ENTITIES:
            entities.append(eid)
    if subject and subject not in entities and "." in subject:
        entities.insert(0, subject)
        entities = entities[:MAX_ENTITIES]
    out = {
        "ts": int(row.get("ts") or now),
        "kind": kind,
        "subject": subject,
        "check": str(row.get("check") or "").strip()[:96],
        "reason": " ".join(str(row.get("reason") or "").split())[:MAX_REASON],
    }
    if entities:
        out["entities"] = entities
    text = " ".join(str(row.get("text") or "").split())[:MAX_REASON]
    if text:
        out["text"] = text
    source = str(row.get("source") or "").strip()[:64]
    if source:
        out["source"] = source
    return out


def note_many(rows, now: float | None = None) -> int:
    """Append a batch of decisions. Returns how many lines were written.

    Never raises. A row with a kind outside :data:`KINDS` is dropped —
    an unknown word is a reader that cannot say what happened — and an
    identical decision written inside :data:`MERGE_S` is not written again.
    """
    now = time.time() if now is None else float(now)
    try:
        cleaned = [c for c in (_clean(r, now) for r in rows or ()
                               if isinstance(r, dict)) if c]
    except Exception as exc:  # noqa: BLE001 — accounting never fails a caller
        log.debug("could not read the decisions handed over: %s", exc)
        return 0
    if not cleaned or not _parent_exists():
        return 0
    fresh = []
    with _LOCK:
        for row in cleaned:
            key = (row["kind"], row["subject"], row["check"], row["reason"])
            last = _RECENT.get(key)
            if last is not None and now - last < MERGE_S:
                continue
            _RECENT[key] = now
            fresh.append(row)
        if len(_RECENT) > _RECENT_MAX:
            for key in sorted(_RECENT, key=_RECENT.get)[:len(_RECENT) // 4]:
                del _RECENT[key]
        if not fresh:
            return 0
        try:
            if _fold(fresh, now):
                return len(fresh)
            with open(TRAIL_FILE, "a", encoding="utf-8") as fh:
                for row in fresh:
                    fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            if _count_lines() > MAX_LINES + MAX_LINES // 4:
                kept = _read_all()[-MAX_LINES:]
                _rewrite(kept)
        except OSError as exc:
            log.debug("could not write the decision trail: %s", exc)
            return 0
    return len(fresh)


def _key(row: dict) -> tuple:
    return (row.get("kind"), row.get("subject") or "", row.get("check") or "",
            row.get("reason") or "")


def _rewrite(rows: list[dict]) -> None:
    atomic_write.write_text(
        TRAIL_FILE, "".join(json.dumps(r, separators=(",", ":")) + "\n"
                            for r in rows))


def _fold(fresh: list[dict], now: float) -> bool:
    """Fold standing decisions into the rows already on disk; append the
    rest. True when the file was rewritten (and `fresh` is all recorded),
    False when there was nothing to fold and the caller appends. Read off
    the file rather than memory, so a restart folds too."""
    if not any(r["kind"] in FOLD_KINDS for r in fresh):
        return False
    if not os.path.exists(TRAIL_FILE):
        return False
    rows = _read_all()
    where = {_key(r): i for i, r in enumerate(rows) if r["kind"] in FOLD_KINDS}
    folded = False
    for row in fresh:
        i = where.get(_key(row)) if row["kind"] in FOLD_KINDS else None
        if i is None:
            rows.append(row)
            if row["kind"] in FOLD_KINDS:
                where[_key(row)] = len(rows) - 1
            continue
        old = rows[i]
        old["count"] = int(old.get("count") or 1) + 1
        old["last_seen"] = int(now)
        folded = True
    if not folded:
        return False
    _rewrite(rows[-MAX_LINES:])
    return True


def _seen(row: dict) -> int:
    """When a decision was last made: a folded row's `last_seen`, else its
    one time."""
    return int(row.get("last_seen") or row.get("ts") or 0)


def note(kind: str, subject: str = "", reason: str = "", *, check: str = "",
         text: str = "", source: str = "", entities=(),
         now: float | None = None) -> int:
    """One decision. The single-row form of :func:`note_many`."""
    return note_many([{"kind": kind, "subject": subject, "reason": reason,
                       "check": check, "text": text, "source": source,
                       "entities": list(entities or ())}], now)


def _count_lines() -> int:
    try:
        with open(TRAIL_FILE, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _read_all() -> list[dict]:
    out: list[dict] = []
    with open(TRAIL_FILE, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("kind") in KINDS:
                out.append(row)
    return out


def read() -> tuple[list[dict], bool]:
    """Every row, oldest first, and whether the file could be read.

    A file that does not exist yet is readable and empty — nothing has
    been withheld — while one that cannot be opened is not, and the two
    must not reach a person as the same sentence.
    """
    if not os.path.exists(TRAIL_FILE):
        return [], True
    try:
        return _read_all(), True
    except OSError as exc:
        log.debug("could not read the decision trail: %s", exc)
        return [], False


def _about(row: dict, subject: str) -> bool:
    if row.get("subject") == subject or row.get("check") == subject:
        return True
    return subject in (row.get("entities") or ())


def for_subject(subject: str, *, since: float = 0.0, limit: int = 20,
                rows: list[dict] | None = None) -> dict:
    """What brAIn decided about one entity (or one check), newest first.

    ``{"subject", "readable", "rows", "kinds"}``. No rows on a readable
    trail is "no record of a decision", which is not "brAIn decided to
    say nothing" — the caller says which.
    """
    subject = str(subject or "").strip()
    readable = True
    if rows is None:
        rows, readable = read()
    hits = [dict(r) for r in rows
            if _about(r, subject) and _seen(r) >= since]
    hits.sort(key=_seen, reverse=True)
    hits = hits[:max(1, int(limit or 20))]
    for row in hits:
        row["meaning"] = KINDS.get(row["kind"], "")
    return {"subject": subject, "readable": readable, "rows": hits,
            "kinds": sorted({r["kind"] for r in hits})}


def summary(now: float | None = None, window_s: float = 86400.0) -> dict:
    """What `/api/diagnostics` carries: a count per kind over the last day,
    the newest stamp, and whether the file could be read at all."""
    now = time.time() if now is None else float(now)
    rows, readable = read()
    recent = [r for r in rows if _seen(r) >= now - window_s]
    counts: dict[str, int] = {}
    for row in recent:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    return {"readable": readable, "rows": len(rows),
            "last": max((_seen(r) for r in rows), default=0),
            "day": counts, "writable": _parent_exists()}


def _check_of(row: dict) -> str:
    source = str(row.get("source") or "")
    return source[len("check:"):] if source.startswith("check:") else source


def rows_for(findings, kind: str, reason: str) -> list[dict]:
    """One decision per finding, for a writer that withheld a batch.

    The subject is the row's entity where it has one; a row about nothing
    in particular (a system check, a digest) keeps its producer as the
    `check`, which is what "why does this rule never say anything" reads.
    """
    out = []
    for row in findings or ():
        if not isinstance(row, dict):
            continue
        out.append({"kind": kind, "subject": str(row.get("entity_id") or ""),
                    "check": _check_of(row), "reason": reason,
                    "text": str(row.get("text") or row.get("claim") or "")})
    return out


# What a settled-ledger kind means, for a re-report the ledger swallowed.
_SETTLED_WORDS = {
    "ignored": "you marked it Not a problem",
    "fixed": "you said you had fixed it",
    "accepted": "it is on your to-do list",
}


def pass_rows(result: dict, *, created_keys, settled: dict, muted,
              normalize) -> list[dict]:
    """Every decision a checks pass made that nothing else records.

    Three kinds, each read off what the pass already holds: what a check
    withheld itself (`run_all`'s ``withheld`` — a correction, a cap), a
    muted producer's rows (`triage.gate` drops them at the door), and a
    re-report the settled ledger swallowed (`add_many` drops it silently).
    A row already open on the list is not here: it was reported, and the
    list is where it is. Pure over what it is handed, so a test can drive
    it without a store.
    """
    out = [dict(r) for r in (result.get("withheld") or ())
           if isinstance(r, dict)]
    muted = set(muted or ())
    created_keys = set(created_keys or ())
    for row in result.get("findings") or ():
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "")
        key = normalize(str(row.get("text") or ""))
        if source in muted:
            out.extend(rows_for([row], "mute",
                                "you asked brAIn to stop raising these"))
        elif key not in created_keys and key in settled:
            out.extend(rows_for([row], "dedupe", _SETTLED_WORDS.get(
                settled[key], "it had already been answered")))
    out.extend(rows_for(result.get("shadow") or (), "shadow",
                        "this rule is still on trial and reaches nobody"))
    return out


def clear_memory() -> None:
    """Forget which decisions were written recently — for tests."""
    with _LOCK:
        _RECENT.clear()


__all__ = ["FOLD_KINDS", "KINDS", "MAX_LINES", "MERGE_S", "TRAIL_FILE", "clear_memory",
           "for_subject", "note", "note_many", "pass_rows", "read",
           "rows_for", "summary"]
