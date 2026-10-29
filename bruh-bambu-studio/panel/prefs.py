"""The owner's preferences for what this panel asks brAIn: which model a
design conversation and a print check run on, and the standing instructions
added to every design turn (how they like parts made) and every print brAIn
starts (their default settings).

Kept in /data/preferences.json, read on every turn so a change applies to
the next message without a restart. A model is one of brAIn's CLI aliases or
"default" (brAIn's own plan picks), and nothing else: brAIn's listener puts
the value on a command line.
"""
from __future__ import annotations

import os
from pathlib import Path

import bambu_atomic

FILE = Path(os.environ.get("BAMBU_DATA", "/data")) / "preferences.json"
MODELS = ("default", "haiku", "sonnet", "opus", "fable")
MODEL_WORDS = {"default": "brAIn's choice", "haiku": "Haiku (fastest)", "sonnet": "Sonnet",
               "opus": "Opus (most capable)", "fable": "Fable"}
NOTES_MAX = 4000
DEFAULTS = {"design_model": "default", "look_model": "default",
            "design_notes": "", "print_notes": ""}


def load() -> dict:
    data = bambu_atomic.read_json(FILE, {})
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        for key in DEFAULTS:
            if key in data:
                try:
                    out[key] = clean(key, data[key])
                except ValueError:
                    pass  # a hand-edited value that no longer fits keeps the default
    return out


def clean(key: str, value):
    if key.endswith("_model"):
        text = str(value or "default").strip().lower()
        if text not in MODELS:
            raise ValueError(f"The model is one of {', '.join(MODELS)}.")
        return text
    if key.endswith("_notes"):
        text = str(value or "").replace("\r", "").strip()
        if len(text) > NOTES_MAX:
            raise ValueError(f"Keep the instructions under {NOTES_MAX} characters.")
        return text
    raise ValueError(f"Unknown preference {key!r}.")


def update(changes: dict) -> dict:
    current = load()
    unknown = [k for k in changes if k not in DEFAULTS]
    if unknown:
        raise ValueError(f"Unknown preference {unknown[0]!r}.")
    for key, value in changes.items():
        current[key] = clean(key, value)
    bambu_atomic.write_json(FILE, current)
    return current
