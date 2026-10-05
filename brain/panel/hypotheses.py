"""The hypothesis queue — things brAIn believes but hasn't had confirmed.

This is the replacement for the open-ended question list. The difference
that matters is not the wording but the lifecycle: a question sat open
forever and had to be carried in every prompt so it wasn't re-asked, so
the list only ever grew. A hypothesis is a claim with an end state.

  open  ──✓──▶ confirmed   the claim becomes a plain memory line
        ──✗──▶ rejected    recorded as a dead end, never revisited
        ──⏱──▶ expired     nobody answered within the TTL

Only `open` is ever shown or offered — and an open guess somebody
dismissed is not shown either, until its `snoozed_until` comes round.
**A dismissed guess is still open, and it is not being ASKED.** "Not now"
on a question used to snooze it in the case feed's own sidecar until its
fourteen-day expiry, so the button that promised "brAIn brings it back
later" quietly killed it — and while it sat there it went on holding one
of the `MAX_OPEN` slots, so the gentlest press also stopped brAIn asking
anything else for up to a fortnight. So the snooze lives on the entry
itself (`snooze`): a sleeping guess does not count against the cap, and
its TTL clock runs from when it is next put in front of somebody
(`_asked_at`), which is what makes "it comes back" true rather than a
guess about which of two dates arrives first. `rejected` is the one status worth
putting back in a prompt ("you were on the wrong track here"), and it is
capped hard. Confirmed ones leave no trace here at all — their content
lives in the memory document, which is the point.

Backed by the same JSONL the `brain memory` CLI reads, so the panel and
the terminal are looking at one queue rather than two views that drift.

**Which is also why every write here takes a cross-process lock.** One
queue with three writers: this module (read the file, change one entry,
write it all back), `brain-learn.sh` appending a proposed guess with a
bare `>>`, and the consolidator's `retire_stale_hypotheses` rewriting the
whole file. `atomic_write` makes each of those writes indivisible and
does nothing whatever for the window between a read and its rename — a
guess a study session appended in that window is not corrupted, it is
*gone*, and nothing raises, because the file the panel wrote is complete
and correct and simply predates it. So every read-modify-write below is
wrapped in `atomic_write.locked(HYPOTHESES_FILE)`, and both shell writers
take the same lock through `brain-memory-lock.sh`.

`list_all` is the one that had to change shape rather than grow a lock: it
expires stale entries, so a plain *read* rewrote the file on every call —
the Findings tab asking what is open was a writer, competing with the two
that had something to say. It now checks first and only takes the lock,
re-reads and writes when something has genuinely aged out.

Deliberately stdlib-only so the tests can import it without the add-on
runtime.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path

import atomic_write

MEMORY_DIR = Path(os.environ.get("BRAIN_MEMORY_DIR", "/config/.brain/memory"))
HYPOTHESES_FILE = Path(
    os.environ.get("BRAIN_HYPOTHESES_FILE", str(MEMORY_DIR / "hypotheses.jsonl")))

# A queue longer than this stops being a queue and becomes the wall of
# open questions this design exists to remove.
MAX_OPEN = int(os.environ.get("BRAIN_MAX_HYPOTHESES", "3"))
TTL_DAYS = int(os.environ.get("BRAIN_HYPOTHESIS_TTL_DAYS", "14"))
MAX_TEXT_CHARS = 400
# Why the homeowner said no. Same ceiling as a finding's correction note —
# both are one sentence of context handed to a model, not a document.
MAX_NOTE_CHARS = 400

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    """Case/punctuation-insensitive form, used to avoid re-proposing a guess
    in slightly different words."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _read() -> list[dict]:
    try:
        raw = HYPOTHESES_FILE.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # a torn line must not take the whole queue down
        if isinstance(entry, dict) and entry.get("text"):
            out.append(entry)
    return out


def _write(entries: list[dict]) -> None:
    atomic_write.write_lines(HYPOTHESES_FILE, entries)


def _locked():
    """The queue's lock, read off the module attribute at call time — the
    tests (and the CLI) repoint HYPOTHESES_FILE, and a lock resolved at
    import would guard whatever the file was called then."""
    return atomic_write.locked(HYPOTHESES_FILE)


STATUSES = ("open", "confirmed", "rejected", "expired")


def _status_of(entry: dict) -> str:
    """An unknown or missing status reads as `open`, which is what
    ``list_all`` has always rendered — said once so the cap and the filter
    cannot come to different conclusions about the same line."""
    st = entry.get("status")
    return st if st in STATUSES else "open"


def _unique_ts(used: set[int]) -> int:
    """A timestamp no open entry already holds.

    ts doubles as the id the panel settles by, and a study session or an
    insight run can propose several claims inside the same second. Without
    this they collide, and confirming the second one settles the first —
    i.e. the UI appears to act on the wrong row.
    """
    ts = int(time.time())
    while ts in used:
        ts += 1
    return ts


def _num(value) -> float:
    """A stamp off disk, or 0 for anything that is not one — the file is
    written by three processes and one of them is `jq`."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _asked_at(entry: dict) -> float:
    """When this guess was last put in front of somebody.

    Its proposal, or the moment a dismissal let it come back, whichever is
    later — so a guess dismissed on day ten is asked again with a whole
    TTL ahead of it rather than expiring while it slept. The shell writers
    (`brain-memory.sh`, `brain-memory-consolidate.sh`) retire stale guesses
    with the same `max(ts, snoozed_until)`, because two answers to "has
    this one aged out" is a guess that comes back on one screen and is
    already gone on the other.
    """
    return max(_num(entry.get("ts")), _num(entry.get("snoozed_until")))


def asleep(entry: dict, now: float | None = None) -> bool:
    """Whether a dismissal is still keeping this guess off every screen."""
    return _num(entry.get("snoozed_until")) > (time.time() if now is None
                                                else now)


def _expire(entries: list[dict], now: float | None = None) -> bool:
    """Retire anything nobody answered in time. Returns True if changed."""
    if TTL_DAYS <= 0:
        return False
    cutoff = (now or time.time()) - TTL_DAYS * 86400
    changed = False
    for e in entries:
        if e.get("status") == "open" and _asked_at(e) < cutoff:
            e["status"] = "expired"
            changed = True
    return changed


def list_all(status: str | None = None) -> list[dict]:
    entries = _read()
    if _expire(entries):
        # Only now is this read a write. Re-read under the lock rather than
        # writing back the copy taken outside it: between the two, a study
        # session may have appended a guess this list has never seen, and
        # writing our copy would delete it.
        with _locked():
            entries = _read()
            if _expire(entries):
                _write(entries)
    out = []
    for e in entries:
        st = _status_of(e)
        if status is not None and st != status:
            continue
        out.append({
            "ts": int(e.get("ts") or 0),
            "text": str(e.get("text"))[:MAX_TEXT_CHARS],
            "topic": str(e.get("topic") or ""),
            "status": st,
            "settled_at": int(e.get("settled_at") or 0),
            "note": str(e.get("note") or "")[:MAX_NOTE_CHARS],
            "snoozed_until": int(_num(e.get("snoozed_until"))),
        })
    return out


def awake(now: float | None = None) -> list[dict]:
    """The open guesses somebody is actually being asked right now.

    What every surface renders and what the cap counts: a guess somebody
    dismissed is still open — it comes back — and it is not a question
    on anybody's screen until it does.
    """
    return [e for e in list_all("open") if not asleep(e, now)]


def open_count() -> int:
    return len(awake())


def budget() -> int:
    """How many more guesses may be proposed right now.

    Counted over the AWAKE ones: a dismissed guess is not being asked, and
    a slot it held while it slept was a slot nothing else could use.
    """
    return max(0, MAX_OPEN - open_count())


def is_known(text: str) -> bool:
    """True if this claim has been proposed before in ANY status — including
    settled ones, so a rejected guess is never floated a second time."""
    key = normalize(text)
    if not key:
        return True
    return any(normalize(e["text"]) == key for e in list_all())


def propose(text: str, topic: str = "", *, subject: str = "",
            fact: str = "") -> dict | None:
    """Queue a new guess, or return None if it is known or the queue is full.

    ``subject`` is what the guess is about (an entity id), and ``fact`` the
    statement to file if somebody says yes. Both optional and both for the
    same reason: a curiosity guess is "<because> — <question>?", and
    confirming it filed that whole string — a question mark and all — as a
    standing fact about the house, tagged by scanning a sentence written in
    friendly names. The because is the fact; the question was the asking.

    The known-check, the cap and the append are one decision over one read,
    taken under the lock. Asking ``is_known``/``budget`` first and appending
    afterwards — which is what this did — re-reads the file three times and
    settles the cap against a queue two other writers are still changing:
    two runs proposing at once both see two open guesses and both append,
    and a queue whose whole design is that it holds three ends up holding
    four.
    """
    text = str(text or "").strip()[:MAX_TEXT_CHARS]
    key = normalize(text)
    if not text or not key:
        return None
    with _locked():
        entries = _read()
        _expire(entries)
        if any(normalize(e.get("text") or "") == key for e in entries):
            return None     # proposed before, in any status — never re-floated
        now = time.time()
        if sum(1 for e in entries if _status_of(e) == "open"
               and not asleep(e, now)) >= MAX_OPEN:
            return None
        entry = {"ts": _unique_ts({int(e.get("ts") or 0) for e in entries}),
                 "text": text, "topic": str(topic or "")[:64], "status": "open"}
        if subject:
            entry["subject"] = str(subject)[:255]
        if fact:
            entry["fact"] = str(fact).strip()[:MAX_TEXT_CHARS]
        entries.append(entry)
        _write(entries)
    return entry


def find_open(text: str) -> dict | None:
    """The open claim matching this text, by normalized comparison.

    Insight cards carry the claim's TEXT, not its id — they are rendered
    from a stored insight, not from the queue. Without this, settling from
    a card can't reach the queue entry at all.
    """
    key = normalize(text)
    if not key:
        return None
    for e in list_all("open"):
        if normalize(e["text"]) == key:
            return e
    return None


def _settle(ts: int, status: str, note: str = "") -> dict | None:
    note = str(note or "").strip()[:MAX_NOTE_CHARS]
    with _locked():
        entries = _read()
        for e in entries:
            if int(e.get("ts") or 0) == ts and e.get("status") == "open":
                e["status"] = status
                e["settled_at"] = int(time.time())
                if note:
                    e["note"] = note
                _write(entries)
                return {"ts": ts, "text": e["text"], "status": status,
                        "note": note, "subject": str(e.get("subject") or ""),
                        "fact": str(e.get("fact") or "")}
    return None


def snooze(ts: int, until: float) -> dict | None:
    """Keep an open guess off every screen until ``until``, and no longer.

    It stays `open` — "not now" is not an answer — so it comes back by
    itself, with its TTL running from then (`_asked_at`), and while it
    sleeps it does not count against `MAX_OPEN`. Unknown ids and settled
    guesses return None: a dismissal arriving after somebody answered is
    about a question nobody is asking any more.
    """
    with _locked():
        entries = _read()
        for e in entries:
            if int(e.get("ts") or 0) == ts and _status_of(e) == "open":
                e["snoozed_until"] = int(until)
                _write(entries)
                return {"ts": ts, "text": e["text"], "status": "open",
                        "snoozed_until": int(until)}
    return None


def confirm(ts: int) -> dict | None:
    """Accept a guess. The caller queues its text as a memory fact — the
    claim is the durable part, and this record is not."""
    return _settle(ts, "confirmed")


def reject(ts: int, note: str = "") -> dict | None:
    """Turn a guess down, optionally saying why.

    The reason is worth more than the rejection: "no" retires one claim,
    and the sentence explaining it is usually true of the house and rules
    out everything else built on the same mistake. It is kept on the entry
    and rendered with it in ``dead_ends``.
    """
    return _settle(ts, "rejected", note=note)


def reopen(ts: int) -> dict | None:
    """Put a settled guess back in the queue — the undo half of an answer.

    Only ever reverses a yes or a no somebody has just pressed, so it does
    not consult the cap: the claim was open a moment ago and counted against
    it then. An expired one stays expired — nobody pressed anything, and
    fourteen days is the answer.
    """
    with _locked():
        entries = _read()
        for e in entries:
            if int(e.get("ts") or 0) == ts and e.get("status") in (
                    "confirmed", "rejected"):
                e["status"] = "open"
                e.pop("settled_at", None)
                e.pop("note", None)
                # Put back in front of somebody, which is what a reopen is.
                e.pop("snoozed_until", None)
                _write(entries)
                return {"ts": ts, "text": e["text"], "status": "open"}
    return None


# How a rejected claim and the homeowner's reason are joined into one line.
# Named because ``knowledge_store.prompt_block`` renders the union of these
# and its own dismissed questions, and has to split the claim back out to
# dedupe on it — a separator written down twice is a dedupe that stops
# working the day one of them gains a comma.
DEAD_END_SEP = " — they said: "


def dead_ends(limit: int = 20) -> list[str]:
    """Rejected claims, newest last — the only part of this queue worth
    putting in a prompt. A claim the homeowner explained comes with their
    explanation: the correction is the part that generalises."""
    out = []
    for e in list_all("rejected")[-limit:]:
        note = e.get("note") or ""
        out.append(f"{e['text']}{DEAD_END_SEP}{note}" if note else e["text"])
    return out


def prompt_block(limit: int = MAX_OPEN * 2) -> str:
    """The guesses still waiting on the homeowner, for an insight card.

    Open guesses only, sleeping ones included — a dismissed question is
    still unanswered, and still possibly the reason for what a card is
    looking at. Labelled as unconfirmed so a run cannot read one as a
    fact; an empty queue is no block at all.
    """
    try:
        open_ = list_all("open")[-limit:]
    except Exception:  # noqa: BLE001 — a queue that will not read costs the block
        return ""
    lines = [f"- {e['text']}" for e in open_ if e.get("text")]
    if not lines:
        return ""
    return ("OPEN QUESTIONS waiting on the homeowner (unconfirmed — never state "
            "one as fact, but name it when it could explain what this card "
            "shows):\n" + "\n".join(lines))
