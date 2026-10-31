"""The 1.17.7 companion engine, retired (#592/#593).

Up to BRUH Minecraft 1.17.7 the add-on ran its own companion, named after
one house's persona ("Vesper"), with its state in each world and its own
card. From 1.17.8 the companion is brAIn's and the add-on is a neutral lane
(tests/test_minecraft_companion.py, tests/test_brain_minecraft_faculty.py).
What is left of the old engine is its retirement, held here:

* its per-world state (family list, memory, settings) is read once, the
  action and question logs it kept for undo are carried into the new
  folder, and the old folder is retired (`panel/companion_legacy.py`);
* the entities it tagged are swept, by the old tag, alongside the new one;
* no persona name ships in the add-on, outside the allow-list that has to
  name the old folder and tag, and the release note that lists the renames.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "bruh-minecraft-server"
PANEL = ADDON / "panel"
KAZ = ".Kaz8044"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PANEL / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


companion = _load("test_retired_engine_companion", "companion.py")
legacy = companion.legacy


class TestTheOldEngineIsHandedOver(unittest.TestCase):
    def test_read_carry_and_retire(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            old = legacy.legacy_dir(data)
            old.mkdir()
            (old / "family.json").write_text(json.dumps({"people": [
                {"person": "Kaz", "role": "child", "players": [KAZ]}]}))
            (old / "people.json").write_text(json.dumps({"Kaz": {"sessions": 3}}))
            (old / "engine.json").write_text(json.dumps({"enabled": True,
                                                          "bedtime_entity": "input_boolean.bed"}))
            (old / "actions.json").write_text(json.dumps({"actions": [
                {"id": "20261030-abcdef", "t": 1, "tag": legacy.LEGACY_PREFIX + "abcdef",
                 "status": "done", "cells": []}]}))
            state = legacy.read_state(data)
            self.assertEqual(state["family"][0]["person"], "Kaz")
            self.assertEqual(state["memory"]["Kaz"]["sessions"], 3)
            self.assertTrue(state["settings"]["enabled"])
            new = data / companion.DIR_NAME
            self.assertEqual(legacy.carry_mechanics(data, new), ["actions.json"])
            self.assertEqual(legacy.carry_mechanics(data, new), [])
            self.assertTrue(legacy.retire(data, new))
            self.assertIsNone(legacy.read_state(data))
            self.assertTrue((new / legacy.HANDED / "family.json").exists())
            self.assertFalse(legacy.retire(data, new))


class TestNoPersonaShipsInTheAddOn(unittest.TestCase):
    """#593: "No string Vesper ships in the add-on." That was one house's
    name for its assistant; the add-on is everybody's.

    The allow-list is the code that must name the old engine to retire it:
    `panel/companion_legacy.py` finds the state 1.17.7 kept in each world
    (`.bruh-world/<old name>/`), hands it to brAIn once, and sweeps the
    entities that version tagged — none of which can be done without the
    folder's and the tag's real name. And CHANGELOG.md's 1.17.8 entry lists
    the services and sensors renamed, which the owner asked to be listed as
    a breaking change; a reader of the release notes needs the old names to
    know what to replace. Nothing else may carry it — a new mention fails
    here with its file and line.
    """
    WORD = re.compile(r"vesper", re.I)

    def test_only_the_allow_listed_places_name_it(self):
        found = []
        for path in sorted(ADDON.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".png", ".jar"):
                continue
            rel = path.relative_to(ADDON).as_posix()
            if rel == "panel/companion_legacy.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            entry = None
            for n, line in enumerate(text.splitlines(), 1):
                if rel == "CHANGELOG.md" and line.startswith("## "):
                    entry = line
                if not self.WORD.search(line):
                    continue
                if rel == "CHANGELOG.md" and entry == "## 1.17.8" and (
                        "renamed" in line.lower() or "services are gone" in line):
                    continue
                found.append(f"{rel}:{n}: {line.strip()[:120]}")
        self.assertEqual(found, [])

    def test_the_legacy_module_is_the_one_that_names_it(self):
        text = (PANEL / "companion_legacy.py").read_text()
        self.assertRegex(text, self.WORD)
        self.assertNotRegex((PANEL / "companion.py").read_text(), self.WORD)


class TestTheOldEntitiesAreSwept(unittest.TestCase):
    def test_the_chokepoint_lets_a_sweep_name_the_old_tag_and_nothing_else_old(self):
        companion.check_command(f"minecraft:kill @e[tag={legacy.LEGACY_TAG}]")
        companion.check_command(f"minecraft:kill @e[tag={legacy.LEGACY_PREFIX}abcdef]")
        with self.assertRaises(companion.GuardError):
            companion.check_command(f"minecraft:summon minecraft:allay ~ ~ ~ "
                                    f'{{Tags:["{legacy.LEGACY_TAG}"]}}')
        self.assertEqual(legacy.kill_selectors(), [f"@e[tag={legacy.LEGACY_TAG}]"])


if __name__ == "__main__":
    unittest.main()
