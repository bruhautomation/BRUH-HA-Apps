"""Morph's settings: the add-on options are where they START, and the
Settings view in Morph is where they are changed.

An option is read at boot from the environment run.sh exports; a value set
in Morph's own Settings is stored in /data and wins from then on, so
changing it never needs a restart. ``reset`` drops the stored value and
the option answers again.
"""
from __future__ import annotations

import os

import paths

THEMES = ("auto", "dark", "light", "medium")
MODELS = ("", "haiku", "sonnet", "opus")

DEFAULTS = {
    "learning": True,
    "learning_hours": 24,
    "report_code_issues": True,
    "tell_model": "",
    "learn_model": "",
    "theme": "auto",
    "reduce_motion": False,
    "hold_ms": 540,
    # Morph 1.0: quiet rooms fold to a line (vision §6.1); off keeps every
    # room open as before.
    "fold_rooms": True,
    # A habit whose prediction was ignored is halved, and one use restores
    # it (vision §4.3): {entity_id: weight}, kept here so every device of
    # the house agrees.
    "habit_weights": {},
}

HABIT_FLOOR = 1 / 16
MAX_HABITS = 400


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def options() -> dict:
    return {
        "learning": _env_bool("MORPH_OPT_LEARNING", DEFAULTS["learning"]),
        "report_code_issues": _env_bool("MORPH_OPT_REPORT", DEFAULTS["report_code_issues"]),
    }


def load() -> dict:
    stored = paths.read_json(paths.SETTINGS, {}) or {}
    out = dict(DEFAULTS)
    out.update(options())
    if isinstance(stored, dict):
        out.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return clean(out)


def clean(s: dict) -> dict:
    out = dict(DEFAULTS)
    for key in ("learning", "report_code_issues", "reduce_motion", "fold_rooms"):
        out[key] = bool(s.get(key, DEFAULTS[key]))
    try:
        out["learning_hours"] = max(6, min(24 * 14, int(s.get("learning_hours") or 24)))
    except (TypeError, ValueError):
        pass  # an unreadable interval keeps the default
    try:
        out["hold_ms"] = max(300, min(1500, int(s.get("hold_ms") or 540)))
    except (TypeError, ValueError):
        pass  # an unreadable hold time keeps the default
    out["theme"] = s.get("theme") if s.get("theme") in THEMES else "auto"
    for key in ("tell_model", "learn_model"):
        out[key] = s.get(key) if s.get(key) in MODELS else ""
    out["habit_weights"] = clean_weights(s.get("habit_weights"))
    return out


def clean_weights(raw) -> dict:
    """Entity ids to weights in [1/16, 1); a weight of 1 is no entry."""
    out: dict = {}
    if not isinstance(raw, dict):
        return out
    for eid, w in list(raw.items())[:MAX_HABITS]:
        if not isinstance(eid, str) or "." not in eid or len(eid) > 120:
            continue
        try:
            w = float(w)
        except (TypeError, ValueError):
            continue
        if w >= 1:
            continue
        out[eid] = max(HABIT_FLOOR, w)
    return out


def habit(entity_id: str, used: bool) -> dict:
    """A prediction used (back to full weight) or ignored (halved)."""
    cur = load()
    weights = dict(cur.get("habit_weights") or {})
    if used:
        weights.pop(entity_id, None)
    else:
        weights[entity_id] = weights.get(entity_id, 1.0) * 0.5
    return update({"habit_weights": weights})


def update(patch: dict) -> dict:
    stored = paths.read_json(paths.SETTINGS, {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    for key, value in (patch or {}).items():
        if key in DEFAULTS:
            stored[key] = value
    merged = dict(DEFAULTS)
    merged.update(options())
    merged.update(stored)
    cleaned = clean(merged)
    paths.write_json(paths.SETTINGS, {k: cleaned[k] for k in stored if k in cleaned})
    return cleaned
