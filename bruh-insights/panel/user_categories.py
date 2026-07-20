"""User-defined insight categories for BRUH Insights.

Users can create their own recurring insights (a title, an icon, an
analysis prompt, and an optional refresh interval) — either from scratch
via the panel's "New insight" flow or by promoting an ad-hoc Ask question
into a recurring card. Definitions live in one JSON file (atomic
tmp+replace, like insight storage) and are returned in the same shape as
the shipped categories from categories.py so the rest of the add-on
(collection, prompt building, scheduling) treats them identically.

Data collection: user categories are prompt-driven, not domain-driven, so
they see the whole (slimmed) home plus recent history — the prompt steers
what the analyst looks at.

File shape: {"categories": [{"id": "user-...", "title": "...",
"icon": "...", "focus": "...", "enabled": true, "refresh_hours": 12,
"created_at": 1752…}]} — refresh_hours may be null (= add-on default).

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

USER_CATS_FILE = os.environ.get(
    "BRUH_INSIGHTS_USER_CATS_FILE", "/data/user_categories.json")

ID_PREFIX = "user-"
MAX_USER_CATEGORIES = 24
MAX_TITLE = 60
MAX_ICON = 4
MAX_FOCUS = 4000


def _load_raw() -> list[dict]:
    try:
        with open(USER_CATS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cats = data.get("categories")
        if isinstance(cats, list):
            return [c for c in cats if isinstance(c, dict) and c.get("id")]
    except (OSError, ValueError, AttributeError):
        pass
    return []


def _write(cats: list[dict]) -> None:
    path = Path(USER_CATS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"categories": cats}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _as_category(entry: dict) -> dict:
    """A stored entry in the categories.py shape (+ user-category extras)."""
    hours = entry.get("refresh_hours")
    if not isinstance(hours, int) or isinstance(hours, bool):
        hours = None
    return {
        "id": str(entry["id"]),
        "title": str(entry.get("title") or "Custom insight")[:MAX_TITLE],
        "icon": str(entry.get("icon") or "✨")[:MAX_ICON],
        "description": str(entry.get("focus") or "")[:160],
        # prompt-driven: whole (slimmed) home + history, no domain filter
        "domains": [],
        "device_classes": [],
        "history": True,
        "stats": False,
        "focus": str(entry.get("focus") or ""),
        "enabled": entry.get("enabled") is not False,
        "refresh_hours": hours,
        "created_at": entry.get("created_at"),
        "user": True,
    }


def load() -> list[dict]:
    """All user categories, creation order, in category shape."""
    return [_as_category(e) for e in _load_raw()]


def get(cat_id: str) -> dict | None:
    for cat in load():
        if cat["id"] == cat_id:
            return cat
    return None


def _clean_fields(fields: dict, *, partial: bool) -> dict:
    """Validate/trim user-supplied fields; raises ValueError on bad input."""
    out: dict = {}
    if "title" in fields or not partial:
        title = str(fields.get("title") or "").strip()[:MAX_TITLE]
        if not title:
            raise ValueError("title required")
        out["title"] = title
    if "focus" in fields or not partial:
        focus = str(fields.get("focus") or "").strip()[:MAX_FOCUS]
        if not focus:
            raise ValueError("prompt required")
        out["focus"] = focus
    if "icon" in fields:
        icon = str(fields.get("icon") or "").strip()[:MAX_ICON]
        out["icon"] = icon or "✨"
    if "enabled" in fields:
        if not isinstance(fields["enabled"], bool):
            raise ValueError("enabled must be a boolean")
        out["enabled"] = fields["enabled"]
    if "refresh_hours" in fields:
        hours = fields["refresh_hours"]
        if hours is not None and (
                not isinstance(hours, int) or isinstance(hours, bool)
                or not 0 <= hours <= 168):
            raise ValueError("refresh_hours must be an integer 0-168 or null")
        out["refresh_hours"] = hours
    return out


def create(fields: dict) -> dict:
    """Create a user category; returns it in category shape."""
    cats = _load_raw()
    if len(cats) >= MAX_USER_CATEGORIES:
        raise ValueError(f"limit of {MAX_USER_CATEGORIES} custom insights reached")
    clean = _clean_fields(fields, partial=False)
    now = int(time.time())
    cat_id = f"{ID_PREFIX}{now}"
    existing = {c["id"] for c in cats}
    suffix = 1
    while cat_id in existing:
        suffix += 1
        cat_id = f"{ID_PREFIX}{now}-{suffix}"
    entry = {
        "id": cat_id,
        "title": clean["title"],
        "icon": clean.get("icon", "✨"),
        "focus": clean["focus"],
        "enabled": clean.get("enabled", True),
        "refresh_hours": clean.get("refresh_hours"),
        "created_at": now,
    }
    cats.append(entry)
    _write(cats)
    return _as_category(entry)


def update(cat_id: str, fields: dict) -> dict | None:
    """Merge fields into an existing user category; None when unknown."""
    cats = _load_raw()
    for entry in cats:
        if entry.get("id") == cat_id:
            entry.update(_clean_fields(fields, partial=True))
            _write(cats)
            return _as_category(entry)
    return None


def delete(cat_id: str) -> bool:
    cats = _load_raw()
    kept = [c for c in cats if c.get("id") != cat_id]
    if len(kept) == len(cats):
        return False
    _write(kept)
    return True
