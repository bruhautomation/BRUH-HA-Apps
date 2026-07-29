"""Per-card tag edits.

Tags are written by the model on every run — good ones ("batteries",
"left-on") are how one chip surfaces every card that found the same kind of
thing. Bad ones are noise the dashboard then filters by, and before this the
only way to lose one was to hope the next run didn't repeat it.

What is stored is a **diff, not a list**: which tags this card had removed,
and which were added by hand. Storing the final list instead would freeze
the card's tags forever — a run that discovers a battery problem could never
add "batteries" again, because the stored list would keep overriding it.
With a diff, a new tag from a new run still shows up unless it is one you
specifically threw away.

File shape: {"cards": {"<card_id>": {"hide": ["x"], "add": ["y"]}}}

Stdlib only, so the test suite can import it without the add-on runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

TAGS_FILE = Path(os.environ.get("BRAIN_CARD_TAGS_FILE", "/data/card_tags.json"))

MAX_TAGS = 8
MAX_TAG_CHARS = 24


def clean_tag(tag: str) -> str:
    """One tag, in the only form the dashboard stores: lowercase, trimmed of
    the decoration people type ("#Batteries " → "batteries")."""
    return str(tag or "").strip().strip("#").strip().lower()[:MAX_TAG_CHARS]


def clean_tags(tags) -> list[str]:
    if not isinstance(tags, list):
        return []
    out: list[str] = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = clean_tag(tag)
        if tag and tag not in out:
            out.append(tag)
        if len(out) >= MAX_TAGS:
            break
    return out


def _load() -> dict:
    try:
        data = json.loads(TAGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cards = data.get("cards") if isinstance(data, dict) else None
    return {k: v for k, v in cards.items() if isinstance(v, dict)} \
        if isinstance(cards, dict) else {}


def _write(cards: dict) -> None:
    TAGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TAGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"cards": cards}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(TAGS_FILE)


def base_tags(insight: dict) -> list[str]:
    """The tags a card would carry with no edits: what the model wrote, plus
    the card's own category (or "asked" for an ad-hoc question).

    The category tag is included deliberately — it is a tag like any other on
    the filter bar, so it has to be removable like any other.
    """
    tags = clean_tags(insight.get("tags"))
    category = str(insight.get("category") or "")
    if category == "custom":
        own = "asked"
    else:
        own = clean_tag(category)
    if own and own not in tags:
        tags.insert(0, own)
    return tags[:MAX_TAGS]


def effective_tags(insight: dict) -> list[str]:
    """What the card actually shows: base tags minus removals plus additions."""
    entry = _load().get(str(insight.get("id") or "")) or {}
    hide = set(clean_tags(entry.get("hide")))
    out = [t for t in base_tags(insight) if t not in hide]
    for tag in clean_tags(entry.get("add")):
        if tag not in out:
            out.append(tag)
    return out[:MAX_TAGS]


def set_tags(card_id: str, insight: dict, tags) -> list[str]:
    """Store the edit that turns this card's base tags into ``tags``.

    Returns the effective list, which equals ``tags`` — the caller can render
    it straight back without re-reading.
    """
    wanted = clean_tags(tags)
    base = base_tags(insight)
    entry = {
        "hide": [t for t in base if t not in wanted],
        "add": [t for t in wanted if t not in base],
    }
    cards = _load()
    if entry["hide"] or entry["add"]:
        cards[card_id] = {k: v for k, v in entry.items() if v}
    else:
        cards.pop(card_id, None)
    _write(cards)
    return wanted


def forget(card_id: str) -> None:
    """Drop a deleted card's tag edits so its id can't inherit them later."""
    cards = _load()
    if cards.pop(card_id, None) is not None:
        _write(cards)
