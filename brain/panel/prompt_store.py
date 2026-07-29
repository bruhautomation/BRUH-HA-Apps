"""Per-category prompt overrides for BRain.

Users can rename a shipped category, give it a different icon, rewrite its
analysis focus, disable it, remove its card entirely, or give it its own
refresh interval. Overrides live in one JSON file (atomic tmp+replace, like
insight storage) and are merged over the shipped defaults from categories.py
at read time — categories.py itself stays untouched and dependency-free.

File shape: {"categories": {"<id>": {"title": "...", "icon": "...",
"focus": "...", "enabled": false, "hidden": true, "refresh_hours": 12,
"schedule": ["07:00", "19:00"]}}} — every key is optional per category; an
absent key means "use the shipped default". A non-empty schedule (fixed
daily run times) takes precedence over refresh_hours for that category.

``hidden`` is how a shipped card gets "deleted": the definition can't go
away (it ships in the code), so the card is dropped from the dashboard and
the scheduler, and stays restorable from ⚙ Settings.

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from categories import CATEGORIES, get_category

OVERRIDES_FILE = os.environ.get("BRAIN_PROMPTS_FILE", "/data/prompt_overrides.json")

OVERRIDE_FIELDS = (
    "title", "icon", "focus", "enabled", "hidden", "refresh_hours", "schedule")

MAX_TITLE = 60
MAX_ICON = 4


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

    Adds five keys on top of the categories.py shape:
      enabled        — bool, default True
      hidden         — bool, default False (card removed from the dashboard)
      refresh_hours  — int override, or None (= use the global default)
      schedule       — list of "HH:MM" daily run times, or None; a non-empty
                       schedule takes precedence over refresh_hours
      overridden     — list of field names an override is active for

    ``title`` and ``icon`` are replaced in place when overridden, so every
    caller (status payload, prompt building, generated insights) sees the
    user's name for the card without knowing overrides exist.
    """
    base = get_category(cat_id)
    if base is None:
        return None
    entry = load_overrides()["categories"].get(cat_id)
    if not isinstance(entry, dict):
        entry = {}
    eff = dict(base)
    overridden: list[str] = []
    title = entry.get("title")
    if isinstance(title, str) and title.strip():
        eff["title"] = title.strip()[:MAX_TITLE]
        overridden.append("title")
    icon = entry.get("icon")
    if isinstance(icon, str) and icon.strip():
        eff["icon"] = icon.strip()[:MAX_ICON]
        overridden.append("icon")
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
    if entry.get("hidden") is True:
        eff["hidden"] = True
        overridden.append("hidden")
    else:
        eff["hidden"] = False
    hours = entry.get("refresh_hours")
    if isinstance(hours, int) and not isinstance(hours, bool):
        eff["refresh_hours"] = hours
        overridden.append("refresh_hours")
    else:
        eff["refresh_hours"] = None
    schedule = entry.get("schedule")
    if isinstance(schedule, list) and schedule \
            and all(isinstance(t, str) for t in schedule):
        eff["schedule"] = schedule
        overridden.append("schedule")
    else:
        eff["schedule"] = None
    eff["overridden"] = overridden
    return eff


def is_hidden(cat_id: str) -> bool:
    """True when the shipped card was removed from the dashboard."""
    entry = load_overrides()["categories"].get(cat_id)
    return isinstance(entry, dict) and entry.get("hidden") is True


def visible_categories() -> list[dict]:
    """Shipped categories the user hasn't removed, in shipped order."""
    hidden = {
        cid for cid, entry in load_overrides()["categories"].items()
        if isinstance(entry, dict) and entry.get("hidden") is True
    }
    return [c for c in CATEGORIES if c["id"] not in hidden]


def hidden_categories() -> list[dict]:
    """Removed shipped cards, in shipped order — the ⚙ Settings restore list.

    Names/icons come from the override so a card the user renamed before
    removing it is listed under the name they gave it.
    """
    out = []
    for c in CATEGORIES:
        if not is_hidden(c["id"]):
            continue
        eff = effective_category(c["id"]) or c
        out.append({
            "id": c["id"],
            "title": eff.get("title", c["title"]),
            "icon": eff.get("icon", c["icon"]),
            "default_title": c["title"],
        })
    return out
