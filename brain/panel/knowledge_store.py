"""Local knowledge base for BRain — what the analyst has learned.

This is the add-on's own durable memory, independent of the BRain
integration (whose memory.md we can only read). Two collections live in one
JSON file at /data/knowledge.json:

  facts      — durable discoveries about this home (from the model's
               "findings", homeowner answers, or typed in by the user).
               Deduplicated by normalized text so the same discovery is
               never stored — or re-announced — twice.
  questions  — every clarifying question the analyst has ever asked, with
               a lifecycle: open → answered | dismissed. The store is the
               single source of truth for "has this been asked before?",
               which is what stops the analyst re-asking the same thing
               run after run.

``prompt_block()`` renders the whole store as a compact text block that is
injected into every generation prompt, so the model *builds on* what it
knows instead of rediscovering it.

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
from pathlib import Path

KNOWLEDGE_FILE = os.environ.get("BRAIN_KNOWLEDGE_FILE", "/data/knowledge.json")

MAX_FACTS = 200
MAX_QUESTIONS = 200
MAX_TEXT_CHARS = 500
MAX_ANSWER_CHARS = 1000
# prompt_block caps: newest-first inclusion until the budget is spent
PROMPT_FACTS = 60
PROMPT_QA = 30
PROMPT_OPEN = 15
PROMPT_MAX_CHARS = 8000

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
    path = Path(KNOWLEDGE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


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


def remove_fact(ts: int) -> bool:
    data = _load()
    kept = [f for f in data["facts"] if int(f.get("ts") or 0) != ts]
    if len(kept) == len(data["facts"]):
        return False
    data["facts"] = kept
    _write(data)
    return True


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
    """The store rendered for the generation prompt, or "" when empty.

    Three sections, each newest-first and capped: known facts, answered
    questions (with their answers), and questions already asked. The whole
    block is budgeted so a very chatty store can't crowd out the data.
    """
    facts = list_facts()[-PROMPT_FACTS:]
    answered = list_questions("answered")[-PROMPT_QA:]
    open_qs = list_questions("open")[-PROMPT_OPEN:]
    dismissed = list_questions("dismissed")

    parts: list[str] = []
    if facts:
        parts.append("KNOWN FACTS about this home (already learned — build on them, "
                     "never present one as a new discovery):")
        parts += [f"- {f['text']}" for f in reversed(facts)]
    if answered:
        parts.append("\nANSWERED QUESTIONS (the homeowner already told you — use these "
                     "answers, never ask again):")
        parts += [f"- Q: {q['text']}\n  A: {q['answer']}" for q in reversed(answered)]
    if open_qs:
        parts.append("\nQUESTIONS ALREADY ASKED, awaiting an answer (do NOT ask these, "
                     "or minor variations of them, again):")
        parts += [f"- {q['text']}" for q in open_qs]
    if dismissed:
        parts.append("\nQUESTIONS THE HOMEOWNER DISMISSED AS NOT RELEVANT — you were on "
                     "the wrong track. Treat these lines of inquiry as dead ends: don't "
                     "re-ask them and don't build analysis around them:")
        parts += [f"- {q['text']}" for q in dismissed]
    if not parts:
        return ""
    block = "\n".join(parts)
    if len(block) > PROMPT_MAX_CHARS:
        block = block[:PROMPT_MAX_CHARS].rsplit("\n", 1)[0]
    return block
