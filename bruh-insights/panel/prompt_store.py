"""Per-category prompt overrides for BRUH Insights.

Users can rewrite each category's analysis focus, disable a category, or
give it its own refresh interval. Overrides live in one JSON file (atomic
tmp+replace, like insight storage) and are merged over the shipped defaults
from categories.py at read time — categories.py itself stays untouched and
dependency-free.

File shape: {"categories": {"<id>": {"focus": "...", "enabled": false,
"refresh_hours": 12}}} — every key is optional per category; an absent key
means "use the shipped default".

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from categories import get_category

OVERRIDES_FILE = os.environ.get("BRUH_INSIGHTS_PROMPTS_FILE", "/data/prompt_overrides.json")

OVERRIDE_FIELDS = ("focus", "enabled", "refresh_hours")


def load_overrides() -> dict:
    """The stored override map; tolerates a missing or corrupt file."""
    try:
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cats = data.get("categories")
        if isinstance(cats, dict):
            return {"categories": cats}
    except (OSError, ValueError, AttributeError):
        pass
    return {"categories": {}}


def _write(data: dict) -> None:
    path = Path(OVERRIDES_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def save_override(cat_id: str, fields: dict) -> dict:
    """Merge ``fields`` into a category's override; a None value clears
    that field. Returns the category's stored override after the merge."""
    data = load_overrides()
    entry = dict(data["categories"].get(cat_id) or {})
    for key, value in fields.items():
        if key not in OVERRIDE_FIELDS:
            continue
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    if entry:
        data["categories"][cat_id] = entry
    else:
        data["categories"].pop(cat_id, None)
    _write(data)
    return entry


def reset_override(cat_id: str) -> None:
    """Drop every override for the category (back to shipped defaults)."""
    data = load_overrides()
    if cat_id in data["categories"]:
        del data["categories"][cat_id]
        _write(data)


def effective_category(cat_id: str) -> dict | None:
    """The shipped category merged with any stored override.

    Adds three keys on top of the categories.py shape:
      enabled        — bool, default True
      refresh_hours  — int override, or None (= use the global default)
      overridden     — list of field names an override is active for
    """
    base = get_category(cat_id)
    if base is None:
        return None
    entry = load_overrides()["categories"].get(cat_id)
    if not isinstance(entry, dict):
        entry = {}
    eff = dict(base)
    overridden: list[str] = []
    focus = entry.get("focus")
    if isinstance(focus, str) and focus.strip():
        eff["focus"] = focus
        overridden.append("focus")
    enabled = entry.get("enabled")
    if isinstance(enabled, bool):
        eff["enabled"] = enabled
        overridden.append("enabled")
    else:
        eff["enabled"] = True
    hours = entry.get("refresh_hours")
    if isinstance(hours, int) and not isinstance(hours, bool):
        eff["refresh_hours"] = hours
        overridden.append("refresh_hours")
    else:
        eff["refresh_hours"] = None
    eff["overridden"] = overridden
    return eff
