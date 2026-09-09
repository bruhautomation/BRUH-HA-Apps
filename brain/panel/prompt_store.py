"""Per-category prompt overrides for brAIn.

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
the scheduler and everything it stored is erased. That is the whole of it —
there is no restore list. brAIn proposes the cards a given home should have;
a graveyard of shipped ones to resurrect is the opposite of that idea.

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os

from categories import CATEGORIES, get_category

import atomic_write

OVERRIDES_FILE = os.environ.get("BRAIN_PROMPTS_FILE", "/data/prompt_overrides.json")

OVERRIDE_FIELDS = (
    "title", "icon", "focus", "enabled", "hidden", "refresh_hours", "schedule")

MAX_TITLE = 60
MAX_ICON = 4


def load_overrides() -> dict:
    """The stored override map; tolerates a missing or corrupt file."""
    out: dict = {"categories": {}, "accepted": []}
    try:
        with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cats = data.get("categories")
        if isinstance(cats, dict):
            out["categories"] = cats
        picked = data.get("accepted")
        if isinstance(picked, list):
            out["accepted"] = [c for c in picked if isinstance(c, str)]
    except (OSError, ValueError, AttributeError):
        # No overrides file, or an unreadable one, means no overrides — which
        # is the shipped behaviour, not a broken one.
        pass
    return out


def _write(data: dict) -> None:
    atomic_write.write_json(OVERRIDES_FILE, data)


# ---------------------------------------------------------------------------
# Which shipped cards this home has, on an install that was asked
# ---------------------------------------------------------------------------
# brAIn shipped nine categories enabled from the moment it was installed,
# and onboarding replaced that with "study the home, then propose" — for
# the CUSTOM proposals only. The nine went on appearing the moment
# onboarding finished, so a person who ticked two proposals got eleven
# cards and nine of them were the generic ones the flow exists to avoid.
#
# `accepted` is the list of shipped ids this home actually asked for, and
# it is consulted ONLY when `curated_categories` is set — a flag written
# by the first onboarding that finishes under this release. An install
# that onboarded before it exists has no flag, reads as uncurated, and
# keeps every card it has: a release that silently deleted somebody's
# dashboard would be a far worse failure than the one this fixes.

def is_curated() -> bool:
    """True when this install's shipped-card set was chosen, not shipped."""
    import settings_store  # noqa: PLC0415 — panel-local, and no cycle

    return bool(settings_store.load().get("curated_categories"))


def accepted_ids() -> set[str] | None:
    """The shipped ids this home accepted, or None for "all of them".

    None is not an empty set and the two must not be conflated: an
    uncurated install has never been asked and shows everything, while a
    curated install that accepted nothing shows nothing and that is the
    answer somebody gave.
    """
    if not is_curated():
        return None
    return set(load_overrides()["accepted"])


def set_accepted(ids) -> list[str]:
    """Record which shipped cards this home has. Returns what was stored."""
    known = {c["id"] for c in CATEGORIES}
    picked = [c["id"] for c in CATEGORIES
              if c["id"] in known and c["id"] in set(ids or ())]
    data = load_overrides()
    data["accepted"] = picked
    _write(data)
    return picked


def accept(cat_id: str) -> list[str]:
    """Add one shipped card to what this home has, keeping shipped order."""
    return set_accepted(set(load_overrides()["accepted"]) | {cat_id})


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
    """Shipped categories this home has and hasn't removed, in shipped order.

    Two different filters and they answer different questions: `hidden`
    is a card somebody deleted, `accepted` is the set they were offered
    and chose from. On an uncurated install the second is not asked at
    all, which is exactly the behaviour every release before this had.
    """
    hidden = {
        cid for cid, entry in load_overrides()["categories"].items()
        if isinstance(entry, dict) and entry.get("hidden") is True
    }
    allowed = accepted_ids()
    return [c for c in CATEGORIES
            if c["id"] not in hidden
            and (allowed is None or c["id"] in allowed)]
