"""Saved effects: the ones somebody built and wants back.

An effect that took ten minutes to get right in the builder is worth
keeping, and it is worth keeping *by name* — because a show script can
then name it too (`{"type": "preset", ...}` is deliberately NOT how that
works; a preset is expanded into its effect when it is used, so a show
never depends on a store the compiler cannot see).

Presets hold the whole effect, selection included. That is on purpose: a
"kitchen chase" is a chase AND the three lights it runs across, and a
preset that remembered only the parameters would need the selection typed
again every time, which is the part that takes the ten minutes.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import atomic_write

PRESETS_FILE = (Path(os.environ.get("BRIGHT_STATE", "/data"))
                / "effect-presets.json")

MAX_PRESETS = 200
_NAME_RE = re.compile(r"^[\w \-'&().,!/]{1,48}$")


def load() -> list[dict]:
    try:
        data = json.loads(PRESETS_FILE.read_text())
    except (OSError, ValueError):
        # No presets yet, or an unreadable file — the empty list is the
        # honest answer and the next save rewrites it.
        return []
    presets = data.get("presets") if isinstance(data, dict) else data
    return presets if isinstance(presets, list) else []


def _save(presets: list[dict]) -> None:
    atomic_write.write_json(PRESETS_FILE,
                            {"version": 1, "updated_at": time.time(),
                             "presets": presets}, indent=2)


def clean_name(raw: str) -> str:
    name = str(raw or "").strip()
    if not _NAME_RE.fullmatch(name):
        raise ValueError("a name: letters, digits, spaces and simple "
                         "punctuation, up to 48 characters")
    return name


def save(name: str, effect: dict, note: str = "") -> dict:
    """Add or replace a preset. The name is the identity — saving over one
    is how you edit it, and it is what the builder's Save does."""
    name = clean_name(name)
    presets = [p for p in load() if p.get("name") != name]
    if len(presets) >= MAX_PRESETS:
        raise ValueError(f"the preset list is full ({MAX_PRESETS}) — delete "
                         "one before saving another")
    preset = {"name": name, "effect": effect, "note": str(note or "")[:200],
              "saved_at": time.time()}
    presets.append(preset)
    _save(sorted(presets, key=lambda p: p["name"].lower()))
    return preset


def remove(name: str) -> bool:
    presets = load()
    kept = [p for p in presets if p.get("name") != name]
    if len(kept) == len(presets):
        return False
    _save(kept)
    return True


def get(name: str) -> dict | None:
    for preset in load():
        if preset.get("name") == name:
            return preset
    return None
