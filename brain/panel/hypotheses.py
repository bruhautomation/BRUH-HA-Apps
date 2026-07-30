"""The hypothesis queue — things brAIn believes but hasn't had confirmed.

This is the replacement for the open-ended question list. The difference
that matters is not the wording but the lifecycle: a question sat open
forever and had to be carried in every prompt so it wasn't re-asked, so
the list only ever grew. A hypothesis is a claim with an end state.

  open  ──✓──▶ confirmed   the claim becomes a plain memory line
        ──✗──▶ rejected    recorded as a dead end, never revisited
        ──⏱──▶ expired     nobody answered within the TTL

Only `open` is ever shown or offered. `rejected` is the one status worth
putting back in a prompt ("you were on the wrong track here"), and it is
capped hard. Confirmed ones leave no trace here at all — their content
lives in the memory document, which is the point.

Backed by the same JSONL the `brain memory` CLI reads, so the panel and
the terminal are looking at one queue rather than two views that drift.

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

MEMORY_DIR = Path(os.environ.get("BRAIN_MEMORY_DIR", "/config/.brain/memory"))
HYPOTHESES_FILE = Path(
    os.environ.get("BRAIN_HYPOTHESES_FILE", str(MEMORY_DIR / "hypotheses.jsonl")))

# A queue longer than this stops being a queue and becomes the wall of
# open questions this design exists to remove.
MAX_OPEN = int(os.environ.get("BRAIN_MAX_HYPOTHESES", "3"))
TTL_DAYS = int(os.environ.get("BRAIN_HYPOTHESIS_TTL_DAYS", "14"))
MAX_TEXT_CHARS = 400

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
    HYPOTHESES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = HYPOTHESES_FILE.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                   encoding="utf-8")
    tmp.replace(HYPOTHESES_FILE)


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


def _expire(entries: list[dict], now: float | None = None) -> bool:
    """Retire anything nobody answered in time. Returns True if changed."""
    if TTL_DAYS <= 0:
        return False
    cutoff = (now or time.time()) - TTL_DAYS * 86400
    changed = False
    for e in entries:
        if e.get("status") == "open" and float(e.get("ts") or 0) < cutoff:
            e["status"] = "expired"
            changed = True
    return changed


def list_all(status: str | None = None) -> list[dict]:
    entries = _read()
    if _expire(entries):
        _write(entries)
    out = []
    for e in entries:
        st = e.get("status") if e.get("status") in (
            "open", "confirmed", "rejected", "expired") else "open"
        if status is not None and st != status:
            continue
        out.append({
            "ts": int(e.get("ts") or 0),
            "text": str(e.get("text"))[:MAX_TEXT_CHARS],
            "topic": str(e.get("topic") or ""),
            "status": st,
            "settled_at": int(e.get("settled_at") or 0),
        })
    return out


def open_count() -> int:
    return len(list_all("open"))


def budget() -> int:
    """How many more guesses may be proposed right now."""
    return max(0, MAX_OPEN - open_count())


def is_known(text: str) -> bool:
    """True if this claim has been proposed before in ANY status — including
    settled ones, so a rejected guess is never floated a second time."""
    key = normalize(text)
    if not key:
        return True
    return any(normalize(e["text"]) == key for e in list_all())


def propose(text: str, topic: str = "") -> dict | None:
    """Queue a new guess, or return None if it is known or the queue is full."""
    text = str(text or "").strip()[:MAX_TEXT_CHARS]
    if not text or is_known(text) or budget() <= 0:
        return None
    entries = _read()
    _expire(entries)
    entry = {"ts": _unique_ts({int(e.get("ts") or 0) for e in entries}),
             "text": text, "topic": str(topic or "")[:64], "status": "open"}
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


def _settle(ts: int, status: str) -> dict | None:
    entries = _read()
    for e in entries:
        if int(e.get("ts") or 0) == ts and e.get("status") == "open":
            e["status"] = status
            e["settled_at"] = int(time.time())
            _write(entries)
            return {"ts": ts, "text": e["text"], "status": status}
    return None


def confirm(ts: int) -> dict | None:
    """Accept a guess. The caller queues its text as a memory fact — the
    claim is the durable part, and this record is not."""
    return _settle(ts, "confirmed")


def reject(ts: int) -> dict | None:
    return _settle(ts, "rejected")


def dead_ends(limit: int = 20) -> list[str]:
    """Rejected claims, newest last — the only part of this queue worth
    putting in a prompt."""
    return [e["text"] for e in list_all("rejected")][-limit:]
