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
}


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
    for key in ("learning", "report_code_issues", "reduce_motion"):
        out[key] = bool(s.get(key, DEFAULTS[key]))
    try:
        out["learning_hours"] = max(6, min(24 * 14, int(s.get("learning_hours") or 24)))
    except (TypeError, ValueError):
        pass
    try:
        out["hold_ms"] = max(300, min(1500, int(s.get("hold_ms") or 540)))
    except (TypeError, ValueError):
        pass
    out["theme"] = s.get("theme") if s.get("theme") in THEMES else "auto"
    for key in ("tell_model", "learn_model"):
        out[key] = s.get(key) if s.get(key) in MODELS else ""
    return out


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
