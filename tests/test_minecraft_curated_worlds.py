#!/usr/bin/env python3
"""Tests for the curated / featured worlds feature (1.14.0).

Covers three pieces:

* scripts/curated-worlds.json — the catalog is valid and the Drehmal entry has
  everything the installer + panel need (download source, version pins, props).
* scripts/convert-java-pack-to-bedrock.py — a Java resource pack converts into a
  VALID Bedrock .mcpack (manifest + atlases), applies the Java->Bedrock name
  map, and skips animated textures. This is what lets Geyser push textures to
  iPad/iPhone (Bedrock) clients with zero local install.
* scripts/install-curated-world.sh — end-to-end staging of a curated world into
  a switchable profile using local file:// "downloads", including the world
  save + bundled datapacks, server.properties, the .curated.json marker, the
  hosted Java pack, and the converted Bedrock pack in the Geyser packs folder.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON = BASE_DIR / "bruh-minecraft-server"
SCRIPTS = ADDON / "scripts"
CATALOG = SCRIPTS / "curated-worlds.json"
INSTALLER = SCRIPTS / "install-curated-world.sh"
CONVERTER = SCRIPTS / "convert-java-pack-to-bedrock.py"
MAP = SCRIPTS / "java2bedrock-map.json"

# A 1x1 byte blob standing in for a PNG — the converter/installer only copy
# texture files, they never decode them, so real pixels aren't needed here.
FAKE_PNG = b"\x89PNG\r\n\x1a\n-fake-"


def _load_converter():
    spec = importlib.util.spec_from_file_location(
        "j2b_converter", str(CONVERTER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _make_java_pack(path: Path) -> None:
    """Write a minimal-but-realistic Java resource pack zip."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("pack.mcmeta", json.dumps(
            {"pack": {"pack_format": 15, "description": "Test Drehmal Pack"}}))
        zf.writestr("pack.png", FAKE_PNG)
        zf.writestr("assets/minecraft/textures/block/stone.png", FAKE_PNG)
        zf.writestr("assets/minecraft/textures/block/oak_planks.png", FAKE_PNG)
        # Animated texture — has a sibling .mcmeta, must be SKIPPED.
        zf.writestr("assets/minecraft/textures/block/water_still.png", FAKE_PNG)
        zf.writestr("assets/minecraft/textures/block/water_still.png.mcmeta",
                    json.dumps({"animation": {}}))
        zf.writestr("assets/minecraft/textures/item/iron_ingot.png", FAKE_PNG)


def _make_world_zip(path: Path) -> None:
    """A tiny Minecraft world zip with a wrapper dir + bundled datapack."""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("DREHMAL v2.2/level.dat", b"\x0a\x00\x00fake-nbt")
        zf.writestr("DREHMAL v2.2/datapacks/drehmal/pack.mcmeta",
                    json.dumps({"pack": {"pack_format": 15}}))
        zf.writestr("DREHMAL v2.2/region/r.0.0.mca", b"\x00" * 16)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
class TestCatalog(unittest.TestCase):
    def test_catalog_is_valid_json(self):
        data = json.loads(CATALOG.read_text())
        self.assertIn("worlds", data)
        self.assertIsInstance(data["worlds"], dict)

    def test_drehmal_entry_complete(self):
        entry = json.loads(CATALOG.read_text())["worlds"]["drehmal"]
        self.assertEqual(entry["minecraft_version"], "1.20.1")
        self.assertEqual(entry["server_type"], "paper")
        # A download source for the world (gdrive id or a plain URL).
        self.assertTrue(entry["world"].get("gdrive_id") or entry["world"].get("url"))
        # A resource pack to convert for Bedrock.
        self.assertTrue(entry["resource_pack"]["url"])
        self.assertTrue(entry["resource_pack"].get("convert_to_bedrock"))
        # Server props that matter for Drehmal.
        self.assertEqual(entry["properties"]["enable-command-block"], "true")
        self.assertEqual(entry["properties"]["spawn-protection"], "0")
        # Offline/no-Xbox so family iPad/iPhone (Bedrock) clients join via
        # Geyser without an Xbox sign-in (online-mode=true -> floodgate ->
        # "Please log into Xbox to join this server").
        self.assertEqual(entry["properties"]["online-mode"], "false")


# ---------------------------------------------------------------------------
# Java -> Bedrock converter
# ---------------------------------------------------------------------------
class TestConverter(unittest.TestCase):
    def test_converts_to_valid_bedrock_pack(self):
        conv = _load_converter()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            java = tmp / "java.zip"
            out = tmp / "out.mcpack"
            _make_java_pack(java)
            result = conv.convert(java, out, "Test Pack", MAP)
            self.assertTrue(result["ok"])
            self.assertTrue(out.is_file())

            with zipfile.ZipFile(out) as zf:
                names = set(zf.namelist())
                # Valid Bedrock manifest with the required fields.
                manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(manifest["format_version"], 2)
                self.assertIn("uuid", manifest["header"])
                self.assertEqual(manifest["modules"][0]["type"], "resources")
                # Icon carried over.
                self.assertIn("pack_icon.png", names)
                # Block textures present + atlas written.
                self.assertIn("textures/blocks/stone.png", names)
                # oak_planks was REMAPPED to the Bedrock key planks_oak.
                self.assertIn("textures/blocks/planks_oak.png", names)
                self.assertNotIn("textures/blocks/oak_planks.png", names)
                # Animated texture was SKIPPED.
                self.assertNotIn("textures/blocks/water_still.png", names)
                # Item mapped + atlas written.
                self.assertIn("textures/items/iron_ingot.png", names)
                terrain = json.loads(zf.read("textures/terrain_texture.json"))
                self.assertIn("planks_oak", terrain["texture_data"])
                self.assertIn("stone", terrain["texture_data"])
                item = json.loads(zf.read("textures/item_texture.json"))
                self.assertIn("iron_ingot", item["texture_data"])

    def test_deterministic_uuid(self):
        conv = _load_converter()
        a = conv._det_uuid("Drehmal", "header")
        b = conv._det_uuid("Drehmal", "header")
        c = conv._det_uuid("Other", "header")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_rejects_non_pack(self):
        conv = _load_converter()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bad = tmp / "bad.zip"
            with zipfile.ZipFile(bad, "w") as zf:
                zf.writestr("random.txt", "nope")
            with self.assertRaises(ValueError):
                conv.convert(bad, tmp / "o.mcpack", "X", MAP)


# ---------------------------------------------------------------------------
# Installer (end-to-end, using file:// "downloads")
# ---------------------------------------------------------------------------
class TestInstaller(unittest.TestCase):
    def _env(self, root: Path) -> dict:
        return {
            **os.environ,
            "MC_WORLDS_DIR": str(root / "minecraft-worlds"),
            "MC_BACKUPS_ROOT": str(root / "minecraft-backups"),
            "MC_RESOURCE_PACKS": str(root / "resource-packs"),
            "SERVER_CACHE": str(root / "cache"),
            "BRUH_MC_SCRIPTS_DIR": str(SCRIPTS),
        }

    def _catalog(self, root: Path, world_zip: Path, pack_zip: Path) -> Path:
        cat = {
            "worlds": {
                "testworld": {
                    "name": "Test World",
                    "version": "1.0",
                    "server_type": "paper",
                    "minecraft_version": "1.20.1",
                    "world": {"url": f"file://{world_zip}"},
                    "resource_pack": {
                        "url": f"file://{pack_zip}",
                        "name": "test-rp.zip",
                        "convert_to_bedrock": True,
                    },
                    "properties": {
                        "difficulty": "normal",
                        "gamemode": "survival",
                        "enable-command-block": "true",
                    },
                }
            }
        }
        path = root / "catalog.json"
        path.write_text(json.dumps(cat))
        return path

    def _run(self, root: Path, catalog: Path, *args: str):
        env = self._env(root)
        env["CURATED_WORLDS_FILE"] = str(catalog)
        return subprocess.run(
            ["bash", str(INSTALLER), *args],
            env=env, capture_output=True, text=True, check=False, timeout=120,
        )

    def test_installs_world_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_zip = root / "world.zip"
            pack_zip = root / "pack.zip"
            _make_world_zip(world_zip)
            _make_java_pack(pack_zip)
            cat = self._catalog(root, world_zip, pack_zip)

            proc = self._run(root, cat, "testworld", "drehmal_test")
            self.assertEqual(proc.returncode, 0, proc.stderr)

            wdir = root / "minecraft-worlds" / "drehmal_test"
            # World save staged with its bundled datapack.
            self.assertTrue((wdir / "world" / "level.dat").is_file())
            self.assertTrue((wdir / "world" / "datapacks" / "drehmal").is_dir())
            # server.properties from the catalog recipe.
            props = (wdir / "server.properties").read_text()
            self.assertIn("level-name=world", props)
            self.assertIn("enable-command-block=true", props)
            self.assertIn("gamemode=survival", props)
            # Curated marker pins server software + version.
            marker = json.loads((wdir / ".curated.json").read_text())
            self.assertEqual(marker["id"], "testworld")
            self.assertEqual(marker["server_type"], "paper")
            self.assertEqual(marker["minecraft_version"], "1.20.1")
            self.assertTrue(marker["requires_bedrock_support"])
            # Java resource pack hosted globally.
            self.assertTrue((root / "resource-packs" / "test-rp.zip").is_file())
            # Bedrock pack converted into the world's Geyser packs folder.
            mcpack = wdir / "plugins" / "Geyser-Spigot" / "packs" / "testworld.mcpack"
            self.assertTrue(mcpack.is_file(), proc.stderr)
            with zipfile.ZipFile(mcpack) as zf:
                self.assertIn("manifest.json", zf.namelist())

    def test_rejects_unknown_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_zip = root / "world.zip"
            pack_zip = root / "pack.zip"
            _make_world_zip(world_zip)
            _make_java_pack(pack_zip)
            cat = self._catalog(root, world_zip, pack_zip)
            proc = self._run(root, cat, "nope")
            self.assertEqual(proc.returncode, 2, proc.stderr)

    def test_refuses_duplicate_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_zip = root / "world.zip"
            pack_zip = root / "pack.zip"
            _make_world_zip(world_zip)
            _make_java_pack(pack_zip)
            cat = self._catalog(root, world_zip, pack_zip)
            (root / "minecraft-worlds" / "dup").mkdir(parents=True)
            proc = self._run(root, cat, "testworld", "dup")
            self.assertEqual(proc.returncode, 3, proc.stderr)


if __name__ == "__main__":
    unittest.main()
