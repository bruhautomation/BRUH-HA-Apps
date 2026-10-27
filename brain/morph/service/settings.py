"""Morph's settings, changed in brAIn's ⚙ › Dashboard and stored in /data.

Two of them are not Morph's to keep: whether the learning loop runs and
whether Morph's faults go to the development loop are brAIn's switches
(⚙ › Features, ``/config/.brain/features.json``), read on every ``load`` so
a switch thrown in brAIn is the answer here at once. A stored value for
either is ignored: one switch, one place.
"""
from __future__ import annotations

import paths

THEMES = ("auto", "dark", "light", "medium")
MODELS = ("", "haiku", "sonnet", "opus")

DEFAULTS = {
    "learning": True,
    "learning_hours": 24,
    "report_code_issues": False,
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


# The two settings brAIn's switches decide (⚙ › Features).
SWITCHED = ("learning", "report_code_issues")


def features() -> dict:
    """brAIn's switches. Unreadable is the learning loop on and nothing
    leaving the house, which are the switches' own defaults."""
    data = paths.read_json(paths.FEATURES, {}) or {}
    return data if isinstance(data, dict) else {}


def options() -> dict:
    f = features()
    return {
        "learning": f.get("learning_loop") is not False,
        "report_code_issues": f.get("development_loop") is True,
    }


def morph_on() -> bool:
    """Whether the Morph dashboard is switched on in brAIn."""
    return features().get("morph") is True


def load() -> dict:
    stored = paths.read_json(paths.SETTINGS, {}) or {}
    out = dict(DEFAULTS)
    if isinstance(stored, dict):
        out.update({k: v for k, v in stored.items() if k in DEFAULTS and k not in SWITCHED})
    out.update(options())
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
        if key in DEFAULTS and key not in SWITCHED:
            stored[key] = value
    for key in SWITCHED:
        stored.pop(key, None)
    merged = dict(DEFAULTS)
    merged.update(stored)
    merged.update(options())
    cleaned = clean(merged)
    paths.write_json(paths.SETTINGS, {k: cleaned[k] for k in stored if k in cleaned})
    return cleaned
