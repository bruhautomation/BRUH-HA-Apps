"""Per-insight homeowner feedback for brAIn.

Feedback given on a generated card ("too much detail", "ignore the guest
room sensor", "show cost in dollars") is stored per category — shipped or
user-defined — and injected into every future generation of that card as a
standing instruction, so the analyst actually addresses it next time. Each
entry is also handed to the home's memory at submit time (server-side).

Entries persist until the user removes them; only the newest
MAX_PER_CATEGORY are kept and injected.

File shape: {"categories": {"<id>": [{"ts": 1752…, "text": "..."}]}}.

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

FEEDBACK_FILE = os.environ.get("BRAIN_FEEDBACK_FILE", "/data/feedback.json")

MAX_PER_CATEGORY = 10
MAX_CHARS = 500


def _load() -> dict:
    try:
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cats = data.get("categories")
        if isinstance(cats, dict):
            return {"categories": cats}
    except (OSError, ValueError, AttributeError):
        pass
    return {"categories": {}}


def _write(data: dict) -> None:
    path = Path(FEEDBACK_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def list_feedback(cat_id: str) -> list[dict]:
    """Stored feedback for a category, oldest first: [{ts, text}, ...]."""
    entries = _load()["categories"].get(cat_id)
    out: list[dict] = []
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"].strip():
            out.append({"ts": int(e.get("ts") or 0), "text": e["text"][:MAX_CHARS]})
    return out[-MAX_PER_CATEGORY:]


def add_feedback(cat_id: str, text: str) -> dict:
    """Append one feedback entry; returns it. Raises ValueError on bad input."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("feedback text required")
    if len(text) > MAX_CHARS:
        raise ValueError(f"feedback too long (max {MAX_CHARS} chars)")
    data = _load()
    entries = list_feedback(cat_id)
    ts = int(time.time())
    # unique ts so entries are individually addressable for deletion
    used = {e["ts"] for e in entries}
    while ts in used:
        ts += 1
    entry = {"ts": ts, "text": text}
    entries.append(entry)
    data["categories"][cat_id] = entries[-MAX_PER_CATEGORY:]
    _write(data)
    return entry


def remove_feedback(cat_id: str, ts: int) -> bool:
    data = _load()
    entries = list_feedback(cat_id)
    kept = [e for e in entries if e["ts"] != ts]
    if len(kept) == len(entries):
        return False
    if kept:
        data["categories"][cat_id] = kept
    else:
        data["categories"].pop(cat_id, None)
    _write(data)
    return True


def clear(cat_id: str) -> None:
    data = _load()
    if cat_id in data["categories"]:
        del data["categories"][cat_id]
        _write(data)
