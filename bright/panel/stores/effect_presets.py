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


# ---------------------------------------------------------------------------
# The library as something Claude can read and use
# ---------------------------------------------------------------------------
def _summarise_select(effect: dict) -> str:
    select = effect.get("select") or {}
    parts = []
    for key, label in (("roles", "role"), ("zones", "zone"), ("ids", "")):
        values = [v for v in (select.get(key) or []) if isinstance(v, str)]
        if values:
            parts.append(f"{label} {', '.join(values)}".strip())
    return "; ".join(parts) or "every light"


# Named rather than written inline in the list below, and this is the
# second time that has mattered: a paragraph split across adjacent string
# literals inside a list is one missing comma away from silently becoming
# two list items — legal Python, invisible in review, and it would quietly
# reshape a prompt. As a constant, the same slip is a syntax error.
_HOW_TO_USE = (
    'Use one with {"use": "<name>"} anywhere an effect goes. Override '
    'anything by naming it alongside: {"use": "kitchen chase", '
    '"params": {"step_beats": 1}} keeps the selection and changes the '
    "speed. These are worth reaching for — they were kept because they "
    "looked good in THIS room."
)


def describe(presets: list[dict] | None = None) -> str:
    """The saved library, written out for a prompt.

    Without this the library is invisible to the thing most able to use
    it: BRight would hold a dozen effects somebody spent an evening
    getting right, and then ask Claude to write a show from a blank page.
    Every show started from nothing, so no show could be better than the
    last one — which is the opposite of what a library is for.

    Effects are listed with their selection and the parameters that were
    actually set, because "kitchen chase" is not a name Claude can reason
    about; "a chase across the three kitchen lamps, half a beat a step"
    is.
    """
    presets = load() if presets is None else presets
    if not presets:
        return ("SAVED EFFECTS: none yet. Anything good you write here can "
                "be saved to the library afterwards and reused by name in "
                "later shows.")
    lines = ["SAVED EFFECTS — this room's own library, built up over time.",
             "", _HOW_TO_USE, ""]
    for preset in presets:
        effect = preset.get("effect") or {}
        params = effect.get("params") or {}
        shown = ", ".join(f"{k}={v}" for k, v in list(params.items())[:6])
        line = (f'  "{preset.get("name")}" — {effect.get("type")} on '
                f"{_summarise_select(effect)}")
        if effect.get("order"):
            line += f', travelling {effect["order"]}'
        if shown:
            line += f" ({shown})"
        lines.append(line)
        note = str(preset.get("note") or "").strip()
        if note:
            lines.append(f"      {note}")
    return "\n".join(lines)


class UnknownPreset(ValueError):
    """A script named a saved effect that is not in the library."""


def _expand_one(item: dict) -> dict:
    """`{"use": name, ...}` becomes the stored effect with overrides."""
    name = str(item.get("use") or "").strip()
    preset = get(name)
    if preset is None:
        known = ", ".join(f'"{p["name"]}"' for p in load()) or "nothing yet"
        raise UnknownPreset(
            f'no saved effect called "{name}" — the library holds: {known}')
    effect = json.loads(json.dumps(preset.get("effect") or {}))
    # Overrides are shallow except params, which merge: changing the speed
    # of a saved chase must not silently drop the rest of its parameters,
    # and that is exactly what a wholesale replace would do.
    for key in ("name", "select", "order", "start", "end"):
        if key in item:
            effect[key] = item[key]
    if isinstance(item.get("params"), dict):
        effect["params"] = {**(effect.get("params") or {}), **item["params"]}
    effect.setdefault("name", name)
    return effect


def expand_script(script: dict) -> dict:
    """Resolve every `use` in a script into the effect it names.

    Done once, before the script is validated, compiled or saved, so what
    lands on disk is the effect in full. A show that stored the NAME would
    be a show that changes when somebody edits the library — silently, and
    usually the night after they edited it. The library is a place to copy
    from, not a layer a saved show depends on.
    """
    if not isinstance(script, dict):
        return script
    out = json.loads(json.dumps(script))
    for scene in out.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        effects = scene.get("effects")
        if isinstance(effects, list):
            scene["effects"] = [
                _expand_one(e) if isinstance(e, dict) and e.get("use") else e
                for e in effects]
    moments = out.get("moments")
    if isinstance(moments, list):
        for moment in moments:
            if not isinstance(moment, dict):
                continue
            inner = moment.get("effect")
            if isinstance(inner, dict) and inner.get("use"):
                moment["effect"] = _expand_one(inner)
            elif moment.get("use"):
                # A moment written as the effect itself, which the compiler
                # already allows.
                expanded = _expand_one(moment)
                expanded["t"] = moment.get("t", expanded.get("start", 0.0))
                moment.clear()
                moment.update(expanded)
    return out
