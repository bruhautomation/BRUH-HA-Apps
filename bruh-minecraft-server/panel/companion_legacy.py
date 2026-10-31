#!/usr/bin/env python3
"""Up to 1.17.7 the add-on ran the companion itself, under one house's
persona name, and kept its state in each world. This module is the only
place that old name appears, because it is how that state is found, handed
to brAIn once and retired, and how the entities that version summoned are
swept out of the world (the add-on's tests allow-list this file and
nothing else; tests/test_minecraft_companion_neutral.py says why).

* `LEGACY_TAG` — the tag every entity of the old engine carried, and
  `LEGACY_PREFIX` its per-action tags. `companion.check_command` lets a
  `kill` name them, so a world upgraded mid-greeting is left clean.
* `legacy_dir` — `.bruh-world/<old name>/` in a world folder.
* `read_state` — what the old engine knew (its family list, memory, settings
  and the questions it asked), for brAIn's first look through
  `bruh_minecraft.get_companion`. Read-only.
* `carry_mechanics` — the action and question logs are the add-on's own
  (they hold what an undo needs), so they move into `.bruh-world/companion/`
  the first time it is made.
* `retire` — once brAIn says it has kept the state, the old folder is
  renamed `.bruh-world/companion/handed-over/` and nothing reads it again.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

LEGACY_NAME = "vesper"
LEGACY_TAG = LEGACY_NAME
LEGACY_PREFIX = LEGACY_NAME + "_"
HANDED = "handed-over"
MECHANICS = ("actions.json", "questions.json")
STATE_FILES = {"family": "family.json", "memory": "people.json",
               "settings": "engine.json", "talks": "talks.json"}


def legacy_dir(data_dir: Path) -> Path:
    return Path(data_dir) / LEGACY_NAME


def is_legacy_tag(tag: str) -> bool:
    return tag == LEGACY_TAG or str(tag).startswith(LEGACY_PREFIX)


def kill_selectors() -> list[str]:
    """The `kill` targets that sweep everything the old engine summoned."""
    return [f"@e[tag={LEGACY_TAG}]"]


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_state(data_dir: Path) -> dict[str, Any] | None:
    """The old engine's per-world state, or None when there is none (or it
    was already handed over). Shapes are the old files' own:
    `family` {people: [{person, role, players}]}, `memory` {person: record},
    `settings` {enabled, bedtime_entity, daily_actions, daily_chats, paused}."""
    root = legacy_dir(data_dir)
    if not root.is_dir():
        return None
    out: dict[str, Any] = {}
    for key, name in STATE_FILES.items():
        value = _read(root / name)
        if value is not None:
            out[key] = value
    if not out:
        return None
    family = out.get("family")
    if isinstance(family, dict):
        out["family"] = family.get("people") or []
    return out


def carry_mechanics(data_dir: Path, new_root: Path) -> list[str]:
    """Copy the old action and question logs into the new folder, once:
    only when the new one has none of its own yet. The names copied."""
    root = legacy_dir(data_dir)
    copied = []
    if not root.is_dir():
        return copied
    new_root.mkdir(parents=True, exist_ok=True)
    for name in MECHANICS:
        src, dest = root / name, new_root / name
        if src.is_file() and not dest.exists():
            text = src.read_text(encoding="utf-8", errors="replace")
            # The old per-action tags stay what they were: an undo of an
            # old action removes what that action summoned.
            dest.write_text(text, encoding="utf-8")
            copied.append(name)
    return copied


def retire(data_dir: Path, new_root: Path) -> bool:
    """Move the old folder aside for good. True when something moved."""
    root = legacy_dir(data_dir)
    if not root.is_dir():
        return False
    dest = new_root / HANDED
    new_root.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    os.replace(root, dest)
    return True


__all__ = ["LEGACY_TAG", "LEGACY_PREFIX", "legacy_dir", "is_legacy_tag", "kill_selectors",
           "read_state", "carry_mechanics", "retire"]
