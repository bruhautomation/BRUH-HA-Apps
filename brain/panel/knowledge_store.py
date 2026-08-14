"""Dedup index for the insights analyst — what it has already said and asked.

Two collections live in one JSON file at /data/knowledge.json:

  facts      — discoveries the analyst has already announced. Deduplicated
               by normalized text so the same finding is never announced,
               or re-queued to memory, twice.
  questions  — every clarifying question ever put to the homeowner, with a
               lifecycle: open → answered | dismissed. This is the single
               source of truth for "have I asked this before?".

This store is a DEDUP INDEX, not memory. Memory is the document at
memory.md, which the consolidator owns and which is injected separately.
What lives here is the bookkeeping that stops the analyst repeating
itself: which discoveries it has already announced, and which questions
it has already put to the homeowner.

``prompt_block()`` therefore renders almost none of it — only the
rejected questions, because "that was the wrong track" is something the
model cannot work out for itself.

File shape:
  {"facts": [{"ts": 1752…, "text": "...", "source": "insights",
              "category": "energy"}],
   "questions": [{"ts": 1752…, "text": "...", "category": "energy",
                  "status": "open"|"answered"|"dismissed",
                  "answer": "...", "answered_at": 1752…,
                  "asked_count": 2, "last_asked": 1752…}]}

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata

import atomic_write

KNOWLEDGE_FILE = os.environ.get("BRAIN_KNOWLEDGE_FILE", "/data/knowledge.json")

MAX_FACTS = 200
MAX_QUESTIONS = 200
MAX_TEXT_CHARS = 500
MAX_ANSWER_CHARS = 1000
# prompt_block renders ONLY rejected lines of inquiry, hard-capped. Facts
# live in the memory document and are injected from there; the ask-history
# is enforced in code, not in the prompt.
PROMPT_DEAD_ENDS = 20
PROMPT_MAX_CHARS = 2000

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    """Case/punctuation/whitespace-insensitive form used for deduplication."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load() -> dict:
    try:
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        facts = data.get("facts")
        questions = data.get("questions")
        return {
            "facts": [f for f in facts if isinstance(f, dict)] if isinstance(facts, list) else [],
            "questions": [q for q in questions if isinstance(q, dict)]
            if isinstance(questions, list) else [],
        }
    except (OSError, ValueError, AttributeError, TypeError):
        return {"facts": [], "questions": []}


def _write(data: dict) -> None:
    atomic_write.write_json(KNOWLEDGE_FILE, data)


def _unique_ts(used: set[int]) -> int:
    ts = int(time.time())
    while ts in used:
        ts += 1
    return ts


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

def list_facts() -> list[dict]:
    """All stored facts, oldest first: [{ts, text, source, category}, ...]."""
    out = []
    for f in _load()["facts"]:
        text = str(f.get("text") or "").strip()
        if text:
            out.append({
                "ts": int(f.get("ts") or 0),
                "text": text[:MAX_TEXT_CHARS],
                "source": str(f.get("source") or "insights"),
                "category": str(f.get("category") or ""),
            })
    return out


def add_fact(text: str, source: str = "insights", category: str = "") -> tuple[dict | None, bool]:
    """Store a fact unless an equivalent one exists.

    Returns (entry, created): the stored/existing entry and whether it is
    new. Callers use `created` to avoid re-announcing (or re-submitting to
    the shared memory) a fact the store already holds.
    """
    text = str(text or "").strip()[:MAX_TEXT_CHARS]
    if not text:
        return None, False
    key = normalize(text)
    if not key:
        return None, False
    data = _load()
    for f in data["facts"]:
        if normalize(f.get("text", "")) == key:
            return f, False
    entry = {
        "ts": _unique_ts({int(f.get("ts") or 0) for f in data["facts"]}),
        "text": text,
        "source": str(source or "insights")[:32],
        "category": str(category or "")[:64],
    }
    data["facts"].append(entry)
    data["facts"] = data["facts"][-MAX_FACTS:]
    _write(data)
    return entry, True


# There is deliberately no remove_fact. The ledger is a dedup index —
# deleting an entry is how the analyst comes to re-announce something the
# homeowner has already seen — and the one function that could do it sat
# here for months, called by nothing, waiting to be "helpfully" wired up.


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------

def list_questions(status: str | None = None) -> list[dict]:
    """Stored questions, oldest first; optionally filtered by status."""
    out = []
    for q in _load()["questions"]:
        text = str(q.get("text") or "").strip()
        if not text:
            continue
        st = q.get("status")
        if st not in ("open", "answered", "dismissed"):
            st = "open"
        if status is not None and st != status:
            continue
        out.append({
            "ts": int(q.get("ts") or 0),
            "text": text[:MAX_TEXT_CHARS],
            "category": str(q.get("category") or ""),
            "status": st,
            "answer": str(q.get("answer") or "")[:MAX_ANSWER_CHARS],
            "answered_at": int(q.get("answered_at") or 0),
            "asked_count": int(q.get("asked_count") or 1),
            "last_asked": int(q.get("last_asked") or q.get("ts") or 0),
        })
    return out


def is_known_question(text: str) -> bool:
    """True when an equivalent question exists in ANY status — i.e. the
    analyst has asked it before and must not surface it again."""
    key = normalize(text)
    if not key:
        return True  # blank never surfaces
    return any(normalize(q.get("text", "")) == key for q in _load()["questions"])


def record_question(text: str, category: str = "") -> dict | None:
    """Register that the analyst asked a question.

    A brand-new question is stored open. An equivalent existing question
    just gets its asked_count/last_asked bumped — its status (answered,
    dismissed) is never reset, so it stays retired.
    """
    text = str(text or "").strip()[:MAX_TEXT_CHARS]
    key = normalize(text)
    if not key:
        return None
    data = _load()
    now = int(time.time())
    for q in data["questions"]:
        if normalize(q.get("text", "")) == key:
            q["asked_count"] = int(q.get("asked_count") or 1) + 1
            q["last_asked"] = now
            _write(data)
            return q
    entry = {
        "ts": _unique_ts({int(q.get("ts") or 0) for q in data["questions"]}),
        "text": text,
        "category": str(category or "")[:64],
        "status": "open",
        "answer": "",
        "answered_at": 0,
        "asked_count": 1,
        "last_asked": now,
    }
    data["questions"].append(entry)
    data["questions"] = data["questions"][-MAX_QUESTIONS:]
    _write(data)
    return entry


def answer_question(text: str, answer: str) -> dict | None:
    """Mark a question answered (matched by normalized text; created if it
    was never recorded). The answer itself is durable knowledge — callers
    should also add_fact("Q … → A …") so it lands in the facts list."""
    answer = str(answer or "").strip()[:MAX_ANSWER_CHARS]
    if not answer:
        return None
    key = normalize(text)
    if not key:
        return None
    data = _load()
    now = int(time.time())
    for q in data["questions"]:
        if normalize(q.get("text", "")) == key:
            q["status"] = "answered"
            q["answer"] = answer
            q["answered_at"] = now
            _write(data)
            return q
    entry = {
        "ts": _unique_ts({int(q.get("ts") or 0) for q in data["questions"]}),
        "text": str(text).strip()[:MAX_TEXT_CHARS],
        "category": "",
        "status": "answered",
        "answer": answer,
        "answered_at": now,
        "asked_count": 1,
        "last_asked": now,
    }
    data["questions"].append(entry)
    data["questions"] = data["questions"][-MAX_QUESTIONS:]
    _write(data)
    return entry


def dismiss_question(ts: int) -> bool:
    """Retire a question without answering — it will never be re-asked."""
    data = _load()
    for q in data["questions"]:
        if int(q.get("ts") or 0) == ts:
            q["status"] = "dismissed"
            _write(data)
            return True
    return False


def remove_question(ts: int) -> bool:
    """Forget a question entirely (it becomes askable again)."""
    data = _load()
    kept = [q for q in data["questions"] if int(q.get("ts") or 0) != ts]
    if len(kept) == len(data["questions"]):
        return False
    data["questions"] = kept
    _write(data)
    return True


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

def prompt_block() -> str:
    """The only part of this store worth putting in a prompt: dead ends.

    Facts are NOT rendered here. The memory document is the single source
    of what this home is, and it is injected separately — duplicating it
    out of this ledger was how the same fact ended up stated two ways in
    one prompt. Likewise the ask-history: re-asking is prevented in code
    by ``is_known_question``, not by pasting every question ever asked
    into the context.

    What survives is the rejected list, because "you were on the wrong
    track here" is information the model cannot derive on its own. It is
    capped hard — an unbounded dead-ends section is exactly the runaway
    this redesign removed.
    """
    dismissed = list_questions("dismissed")[-PROMPT_DEAD_ENDS:]
    if not dismissed:
        return ""
    parts = ["LINES OF INQUIRY THE HOMEOWNER REJECTED — you were on the wrong "
             "track. Don't revisit these or build analysis around them:"]
    parts += [f"- {q['text']}" for q in reversed(dismissed)]
    block = "\n".join(parts)
    if len(block) > PROMPT_MAX_CHARS:
        block = block[:PROMPT_MAX_CHARS].rsplit("\n", 1)[0]
    return block
