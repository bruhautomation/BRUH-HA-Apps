#!/usr/bin/env python3
"""Renaming a world (profile): scripts/world-manager.sh rename and the panel
route that stops the server around it."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MANAGER = BASE_DIR / "bruh-minecraft-server" / "scripts" / "world-manager.sh"


def _tree(root: Path, name: str = "old", level: str | None = None, active: bool = False):
    level = name if level is None else level
    w = root / "minecraft-worlds" / name
    for d in (level, f"{level}_nether", f"{level}_the_end"):
        (w / d).mkdir(parents=True)
        (w / d / "level.dat").write_text(d)
    (w / "plugins").mkdir()
    (w / "server.properties").write_text(f"motd=Hi\nlevel-name={level}\n")
    (root / "minecraft-backups" / name / "git").mkdir(parents=True)
    (root / "minecraft-backups" / name / "git" / "marker").write_text("b")
    link = root / "config-minecraft"
    if active:
        link.symlink_to(w)
        (root / "options.json").write_text(f'{{"active_world": "{name}"}}')
    return w, link


def _run(root: Path, *args: str):
    env = {**os.environ,
           "MC_WORLDS_DIR": str(root / "minecraft-worlds"),
           "MC_BACKUPS_ROOT": str(root / "minecraft-backups"),
           "MC_OPTIONS_FILE": str(root / "options.json"),
           "MC_SERVER_LINK": str(root / "config-minecraft")}
    return subprocess.run(["bash", str(MANAGER), *args], env=env,
                          capture_output=True, text=True, timeout=30)


class TestRename(unittest.TestCase):
    def test_moves_world_level_dirs_backups_and_level_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root)
            proc = _run(root, "rename", "old", "newname")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            new = root / "minecraft-worlds" / "newname"
            self.assertFalse((root / "minecraft-worlds" / "old").exists())
            self.assertEqual((new / "newname" / "level.dat").read_text(), "old")
            self.assertTrue((new / "newname_nether" / "level.dat").is_file())
            self.assertTrue((new / "newname_the_end" / "level.dat").is_file())
            self.assertTrue((new / "plugins").is_dir())
            props = (new / "server.properties").read_text()
            self.assertIn("level-name=newname", props)
            self.assertIn("motd=Hi", props)
            self.assertTrue((root / "minecraft-backups" / "newname" / "git" / "marker").is_file())
            self.assertFalse((root / "minecraft-backups" / "old").exists())

    def test_a_level_name_that_is_not_the_world_name_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root, level="world")
            self.assertEqual(_run(root, "rename", "old", "fresh").returncode, 0)
            new = root / "minecraft-worlds" / "fresh"
            self.assertTrue((new / "world" / "level.dat").is_file())
            self.assertIn("level-name=world", (new / "server.properties").read_text())

    def test_the_active_world_keeps_its_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, link = _tree(root, active=True)
            self.assertEqual(_run(root, "rename", "old", "newname").returncode, 0)
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.readlink(link), str(root / "minecraft-worlds" / "newname"))
            self.assertTrue((link / "newname" / "level.dat").is_file())

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root)
            _tree(root, name="taken")
            for new in ("taken", "old", "", "a/b", "../x", "a b", "x" * 33, ".hidden", "dot.name"):
                proc = _run(root, "rename", "old", new)
                self.assertNotEqual(proc.returncode, 0, f"accepted {new!r}")
                self.assertTrue((root / "minecraft-worlds" / "old" / "old" / "level.dat").is_file())
            self.assertNotEqual(_run(root, "rename", "missing", "other").returncode, 0)
            self.assertEqual(_run(root, "rename", "old", "taken").returncode, 2)

    def test_a_backup_folder_already_there_stops_it_before_anything_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tree(root)
            (root / "minecraft-backups" / "newname").mkdir()
            self.assertNotEqual(_run(root, "rename", "old", "newname").returncode, 0)
            self.assertTrue((root / "minecraft-worlds" / "old").is_dir())
            self.assertFalse((root / "minecraft-worlds" / "newname").exists())


from test_minecraft_panel import PanelTestBase  # noqa: E402


class TestPanelRoute(PanelTestBase):
    def _stub(self, active: str):
        calls: list = []
        w = Path(self.tmp.name) / "worlds"
        (w / "old").mkdir(parents=True)
        self.panel.MC_WORLDS_DIR = w
        self.panel.MC_PANEL_STATE = Path(self.tmp.name) / "state"
        self.panel.MC_PANEL_STATE.mkdir(exist_ok=True)

        async def manager(*args):
            calls.append(("manager", args))
            if args[0] == "active":
                return 0, active
            return 0, ""

        async def rcon(cmd):
            calls.append(("rcon", cmd))
            return "ok"

        async def persist(key, value):
            calls.append(("persist", key, value))
            return None

        async def restart():
            calls.append(("restart",))
            return None

        async def gone(timeout=90.0):
            calls.append(("held", (self.panel.MC_PANEL_STATE / "hold_restart").is_file()))
            return True

        self.panel._run_world_manager = manager
        self.panel._rcon_command = rcon
        self.panel._persist_option = persist
        self.panel._supervisor_restart_self = restart
        self.panel._wait_for_jvm_exit = gone
        return calls

    async def test_active_world_stops_server_renames_sets_option_and_restarts(self):
        calls = self._stub("old")
        resp = await self.client.request("POST", "/api/worlds/old/rename", json={"new_name": "fresh"})
        self.assertEqual(resp.status, 200, await resp.text())
        kinds = [c[0] if c[0] != "manager" else c[1][0] for c in calls]
        self.assertEqual(kinds, ["active", "rcon", "rcon", "held", "rename", "persist", "restart"])
        self.assertIn(("held", True), calls)
        self.assertIn(("persist", "active_world", "fresh"), calls)

    async def test_inactive_world_is_renamed_without_stopping_anything(self):
        calls = self._stub("other")
        resp = await self.client.request("POST", "/api/worlds/old/rename", json={"new_name": "fresh"})
        self.assertEqual(resp.status, 200)
        self.assertFalse([c for c in calls if c[0] in ("rcon", "persist", "restart")])

    async def test_unsafe_names_are_refused_before_anything_runs(self):
        calls = self._stub("old")
        for bad in ("", "a/b", "../x", "x" * 33, "a b"):
            resp = await self.client.request("POST", "/api/worlds/old/rename", json={"new_name": bad})
            self.assertEqual(resp.status, 400, bad)
        self.assertEqual(calls, [])

    async def test_existing_name_is_refused(self):
        calls = self._stub("old")
        (self.panel.MC_WORLDS_DIR / "taken").mkdir()
        resp = await self.client.request("POST", "/api/worlds/old/rename", json={"new_name": "taken"})
        self.assertEqual(resp.status, 409)
        self.assertEqual(calls, [])

    async def test_option_failure_puts_the_folders_back(self):
        calls = self._stub("old")

        async def persist(key, value):
            return "Supervisor HTTP 500"
        self.panel._persist_option = persist
        resp = await self.client.request("POST", "/api/worlds/old/rename", json={"new_name": "fresh"})
        self.assertEqual(resp.status, 500)
        renames = [c[1] for c in calls if c[0] == "manager" and c[1][0] == "rename"]
        self.assertEqual(renames, [("rename", "old", "fresh"), ("rename", "fresh", "old")])
        self.assertFalse((self.panel.MC_PANEL_STATE / "hold_restart").exists())


if __name__ == "__main__":
    unittest.main()
