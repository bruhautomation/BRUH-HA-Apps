"""What learning wrote lately: one count per learner, under ⚙ › Features.

The Learning loop switch governs everything that learns (`features.py`), so
the place it is switched is the place a person can see what it has been
doing. Each count is read off a ledger the learner already keeps, never a
model's account of itself, and never what the lines say — only how many:

* **memory** — lines filed into the memory inbox (`inbox/*.jsonl` and
  `inbox/processed/`), by who filed them: the conversation extractor,
  voice's `remember_fact`, a study session (`study:<topic>` as `study`)…
* **reflect** — judgements the nightly reflect wrote into the facts store
  (`judgement:` predicates), counted by when each was first written;
* **presence** — growth notes brAIn wrote about itself (`by: self` in the
  personality file) and per-person notes in the presence store;
* **morph** — commits Morph's learning pass made in `/config/morph`, and
  how many of them touched `LEARNED.md`.

Deterministic, read-only, and never raises: a ledger that cannot be read is
a learner with nothing to show, not an error on the settings page.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

DAYS = 7
SHARED_DIR = Path(os.environ.get("BRAIN_SHARED_DIR", "/config/.brain"))
MEMORY_DIR = Path(os.environ.get("BRAIN_MEMORY_DIR", str(SHARED_DIR / "memory")))
FACTS_FILE = Path(os.environ.get(
    "BRAIN_FACTS_FILE", str(MEMORY_DIR / "facts.json")))
PERSONALITY_FILE = Path(os.environ.get(
    "BRAIN_PERSONALITY_FILE", str(SHARED_DIR / "personality.json")))
PRESENCE_FILE = Path(os.environ.get("BRAIN_PRESENCE_FILE", "/data/presence.json"))
MORPH_DIR = Path(os.environ.get("MORPH_DIR", "/config/morph"))
# Morph's learning pass commits under this address (morph/service/gitrepo.py
# AUTHORS["learning"]); its name is what `git log --author` matches.
MORPH_LEARNING_EMAIL = "learning@morph.local"
JUDGEMENT_PREFIX = "judgement:"   # outcomes.JUDGEMENT_PREFIX
SELF = "self"                     # personality.SELF
# An inbox is a queue of small files; this many is far past any real week
# and keeps a runaway writer from making the settings page slow.
MAX_INBOX_FILES = 5000
MAX_SOURCE = 32
GIT_TIMEOUT_S = 10

LABELS = {
    "memory": "Memory",
    "reflect": "Reflect",
    "presence": "Presence",
    "morph": "Morph learning",
}


def _ts(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


def _source_word(source) -> str:
    word = str(source or "").strip() or "unknown"
    if word.startswith("study:"):
        word = "study"
    return word[:MAX_SOURCE]


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def memory(since: int) -> dict:
    """Inbox lines filed since ``since``, by source."""
    by: dict[str, int] = {}
    inbox = MEMORY_DIR / "inbox"
    seen = 0
    for folder in (inbox, inbox / "processed"):
        try:
            paths = sorted(folder.glob("*.jsonl"))
        except OSError:
            continue
        for path in paths:
            seen += 1
            if seen > MAX_INBOX_FILES:
                break
            try:
                if path.stat().st_mtime < since:
                    continue  # appended to last before the window opened
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in raw.splitlines():
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict) or _ts(obj.get("ts")) < since:
                    continue
                word = _source_word(obj.get("source"))
                by[word] = by.get(word, 0) + 1
    return {"count": sum(by.values()),
            "by_source": dict(sorted(by.items(), key=lambda kv: (-kv[1], kv[0])))}


def reflect(since: int) -> dict:
    """Judgements reflect wrote since ``since`` that still stand."""
    data = _json(FACTS_FILE)
    rows = data.get("facts") if isinstance(data, dict) else data
    count = 0
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if not str(row.get("predicate") or "").startswith(JUDGEMENT_PREFIX):
            continue
        if _ts(row.get("first_seen") or row.get("ts")) >= since:
            count += 1
    return {"count": count}


def presence(since: int) -> dict:
    """brAIn's own growth notes and the presence loop's person notes."""
    growth = 0
    data = _json(PERSONALITY_FILE)
    for entry in (data.get("growth") if isinstance(data, dict) else None) or []:
        if isinstance(entry, dict) and entry.get("by") == SELF \
                and _ts(entry.get("at")) >= since:
            growth += 1
    # A revision of the paragraph it keeps about how to be here: the
    # current version and the ones it replaced, each stamped when written.
    learned = data.get("learned") if isinstance(data, dict) else None
    learned = learned if isinstance(learned, dict) else {}
    versions = [(learned.get("by"), learned.get("updated_at"))
                if learned.get("text") else (None, None)]
    versions += [(v.get("by"), v.get("at"))
                 for v in learned.get("history") or [] if isinstance(v, dict)]
    revisions = sum(1 for by, at in versions
                    if by == SELF and _ts(at) >= since)
    notes = 0
    store = _json(PRESENCE_FILE)
    people = store.get("people") if isinstance(store, dict) else None
    for rec in (people or {}).values() if isinstance(people, dict) else []:
        for note in (rec.get("notes") if isinstance(rec, dict) else None) or []:
            if isinstance(note, dict) and _ts(note.get("at")) >= since:
                notes += 1
    return {"count": growth + notes + revisions, "growth": growth,
            "notes": notes, "revisions": revisions}


def morph(since: int) -> dict:
    """Commits Morph's learning pass made since ``since``."""
    out = {"count": 0, "learned_md": 0}
    if not (MORPH_DIR / ".git").exists():
        return out
    try:
        r = subprocess.run(
            ["git", "-c", "safe.directory=*", "-c", "core.quotepath=off",
             "log", f"--since=@{int(since)}", f"--author={MORPH_LEARNING_EMAIL}",
             "--format=\x1e%at", "--name-only"],
            cwd=str(MORPH_DIR), capture_output=True, text=True,
            timeout=GIT_TIMEOUT_S, check=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    except (OSError, subprocess.SubprocessError):
        return out
    if r.returncode != 0:
        return out
    for chunk in r.stdout.split("\x1e"):
        lines = [x.strip() for x in chunk.splitlines() if x.strip()]
        if not lines:
            continue
        out["count"] += 1
        if any(Path(x).name == "LEARNED.md" for x in lines[1:]):
            out["learned_md"] += 1
    return out


def last_days(days: int = DAYS, now: float | None = None) -> dict:
    """``{days, since, total, learners: [{key, label, count, …}]}``."""
    now = time.time() if now is None else now
    since = int(now - days * 86400)
    learners = []
    for key, fn in (("memory", memory), ("reflect", reflect),
                    ("presence", presence), ("morph", morph)):
        try:
            row = fn(since)
        except Exception:  # noqa: BLE001 — a ledger that cannot be read is nothing to show
            row = {"count": 0}
        learners.append({"key": key, "label": LABELS[key], **row})
    return {"days": days, "since": since,
            "total": sum(r["count"] for r in learners), "learners": learners}
