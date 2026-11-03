"""The spyglass: how anybody — a child who does not type — points at something.

The owner: *"there really needs to be an item you can point at something
and it comes up with ideas."* BRUH Minecraft ships a small data pack
(`bruh_companion`) that counts spyglass uses and tags the player; the panel
asks over RCON about once a second whether anybody is tagged (ONE command
while nobody is), reads that player's eyes and facing, saves, ray-casts
through the region files to the first solid block within 96, and fires
`bruh_minecraft_point`. Nothing is said in chat.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_layout import chunk_nbt, write_region  # noqa: E402
from test_minecraft_world import PANEL, section  # noqa: E402


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PANEL / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


spyglass = _load("test_bruh_mc_spyglass", "spyglass.py")
OW = "minecraft:overworld"


def wall_world(root: Path) -> Path:
    """A stone wall at x 8 (y 64..70), water at x 5, in chunk (0, 0)."""
    blocks = {}
    for z in range(16):
        for ly in range(7):
            blocks[(8, ly, z)] = 1
            blocks[(5, ly, z)] = 2
    world = root / "world"
    write_region(world / "region", {(0, 0): chunk_nbt([section(
        4, ["minecraft:air", "minecraft:stone", "minecraft:water"], blocks)])})
    return world


class TestTheRay(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.world = wall_world(Path(tmp.name))
        self.region = self.world / "region"

    def test_through_water_to_the_first_solid_block(self):
        # Facing +x is yaw -90 (Minecraft: x = -sin(yaw)).
        hit = spyglass.ray_target(self.region, (2.5, 65.62, 4.5), -90.0, 0.0)
        self.assertEqual(hit, {"x": 8, "y": 65, "z": 4, "block": "minecraft:stone"})
        down = spyglass.ray_target(self.region, (2.5, 66.62, 4.5), -90.0, 20.0)
        self.assertEqual((down["x"], down["block"]), (8, "minecraft:stone"))
        self.assertLess(down["y"], 66)

    def test_nothing_within_reach_and_what_cannot_be_read(self):
        self.assertIsNone(spyglass.ray_target(self.region, (2.5, 65.62, 4.5), 90.0, 0.0))
        self.assertIsNone(spyglass.ray_target(self.region, (2.5, 65.62, 4.5), 0.0, -90.0))
        self.assertIsNone(spyglass.ray_target(self.region, (2.5, 65.62, 4.5), -90.0, 0.0,
                                              reach=4))


class FakeRcon:
    """What the server answers to the spyglass's questions."""

    def __init__(self):
        self.commands: list[str] = []
        self.tagged: set[str] = set()
        self.seq: dict[str, int] = {}
        self.players = {"Ben13765": {"Pos": "[2.5d, 64.0d, 4.5d]", "Rotation": "[-90.0f, 0.0f]",
                                     "Dimension": '"minecraft:overworld"'}}
        self.enabled = False

    def command(self, cmd: str) -> str:
        self.commands.append(cmd)
        if cmd == "minecraft:execute if entity @a[tag=bruh_pointing]":
            return f"Test passed, count: {len(self.tagged)}" if self.tagged else "Test failed"
        if cmd.startswith("minecraft:execute if entity @a[name="):
            name = cmd.split("name=", 1)[1].split(",", 1)[0]
            return "Test passed, count: 1" if name in self.tagged else "Test failed"
        if cmd.startswith("minecraft:scoreboard players get "):
            name = cmd.split()[3]
            if name not in self.seq:
                return f"Can't get value of bruh_spy_n for {name}; none is set"
            return f"{name} has {self.seq[name]} [bruh_spy_n]"
        if cmd.startswith("minecraft:data get entity "):
            name, path = cmd[len("minecraft:data get entity "):].rsplit(" ", 1)
            return f"{name} has the following entity data: {self.players[name][path]}"
        if cmd == "minecraft:datapack list enabled":
            return ("There are 2 data pack(s) enabled: [vanilla (built-in)]"
                    + (", [file/bruh_companion (world)]" if self.enabled else ""))
        if cmd.startswith("minecraft:datapack enable"):
            self.enabled = True
            return "Now enabling data pack [file/bruh_companion (world)]"
        return "Unknown or incomplete command"


class Col:
    def __init__(self, rcon, root: Path):
        self.session = rcon
        self.sessions = {"Ben13765": 0.0}
        self.reachable = True
        self.nicknames = {"dad": "Ben13765"}
        self.server_dir = root


class TestThePoll(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.world = wall_world(self.root)
        (self.world / "level.dat").write_bytes(b"")
        self.rcon = FakeRcon()
        self.col = Col(self.rcon, self.root)
        self.events: list[dict] = []
        self.saves = 0
        self.t = 1000.0

        def save():
            self.saves += 1

        self.pointer = spyglass.Pointer(
            self.col, world_dir=lambda: self.world, emit=self.events.append, save=save,
            here=lambda dim, x, y, z: {"building": {"id": "b:overworld:8:0", "name": "the wall"},
                                       "room": None},
            clock=lambda: self.t)

    def beat(self, seconds=1.0):
        self.t += seconds
        self.pointer.step()

    def test_the_pack_is_installed_and_enabled_once(self):
        self.beat()
        pack = self.world / "datapacks" / "bruh_companion"
        meta = json.loads((pack / "pack.mcmeta").read_text())
        self.assertIn("min_format", meta["pack"])
        tick = (pack / "data" / "bruh_companion" / "function" / "tick.mcfunction").read_text()
        self.assertIn("bruh_pointing", tick)
        load = (pack / "data" / "bruh_companion" / "function" / "load.mcfunction").read_text()
        self.assertIn("minecraft.used:minecraft.spyglass", load)
        self.assertEqual(json.loads((pack / "data" / "minecraft" / "tags" / "function" /
                                     "tick.json").read_text())["values"],
                         ["bruh_companion:tick"])
        self.assertTrue(self.rcon.enabled)
        self.rcon.commands.clear()
        self.beat()
        self.assertFalse(any("datapack" in c for c in self.rcon.commands))

    def test_command_block_output_is_switched_off_once_per_world(self):
        """The world's command blocks chatter into the server log (particle,
        fill and entity replies); a world gets the rule off once, and a
        person who switches it back on keeps it."""
        seen = self.rcon.command

        def command(cmd):
            self.rcon.commands.append(cmd)
            if cmd.startswith("minecraft:execute unless score #quiet bruh_spy"):
                if self.rcon.quiet:
                    return "Test failed"
                if "gamerule commandBlockOutput" in cmd:
                    return "Unknown or incomplete command"      # a newer server's spelling
                self.rcon.quiet = True
                return "Game rule command_block_output is now set to: false"
            if cmd == "minecraft:scoreboard players set #quiet bruh_spy 1":
                return "Set score of bruh_spy for #quiet to 1"
            n = len(self.rcon.commands)
            reply = seen(cmd)
            del self.rcon.commands[n:]
            return reply
        self.rcon.quiet = False
        self.rcon.command = command
        self.beat()
        self.assertTrue(self.rcon.quiet)
        self.assertIn("minecraft:scoreboard players set #quiet bruh_spy 1", self.rcon.commands)
        self.assertTrue(any("gamerule minecraft:command_block_output false" in c
                            for c in self.rcon.commands))

    def test_one_command_while_nobody_points_then_one_event_per_use(self):
        self.beat()
        self.rcon.commands.clear()
        for _ in range(5):
            self.beat()
        self.assertEqual(self.rcon.commands,
                         ["minecraft:execute if entity @a[tag=bruh_pointing]"] * 5)
        self.assertEqual(self.events, [])
        # A spyglass use: the pack tags him and counts it.
        self.rcon.tagged.add("Ben13765")
        self.rcon.seq["Ben13765"] = 1
        self.beat()
        self.assertEqual(len(self.events), 1)
        ev = self.events[0]
        self.assertEqual(ev["kind"], "point")
        self.assertEqual((ev["player"], ev["shown"], ev["dimension"]), ("Ben13765", "dad", OW))
        self.assertEqual(ev["target"], {"x": 8, "y": 65, "z": 4, "block": "minecraft:stone"})
        self.assertEqual(ev["building"]["id"], "b:overworld:8:0")
        self.assertEqual(self.saves, 1)
        self.assertFalse(any(c.startswith(("minecraft:tag ", "tag ", "minecraft:say",
                                           "minecraft:tellraw")) for c in self.rcon.commands))
        # Still tagged a second later (the pack holds the tag a moment): not twice.
        self.beat()
        self.assertEqual(len(self.events), 1)
        self.rcon.seq["Ben13765"] = 2
        self.beat()
        self.assertEqual(len(self.events), 2)

    def test_the_pack_goes_in_before_anyone_joins_and_before_the_server_answers(self):
        self.col.sessions = {}
        self.col.reachable = False
        self.beat()
        self.assertTrue((self.world / "datapacks" / "bruh_companion" / "pack.mcmeta").is_file())
        self.assertEqual(self.rcon.commands, [])
        self.col.reachable = True
        self.beat(spyglass.ENABLE_RETRY_S)
        self.assertTrue(self.rcon.enabled)

    def test_quiet_when_nobody_is_on(self):
        self.beat()
        self.col.sessions = {}
        self.rcon.commands.clear()
        self.beat()
        self.assertEqual(self.rcon.commands, [])
        self.assertGreater(self.pointer.interval(), 1)


class TestTheEvent(unittest.TestCase):
    def test_point_is_a_game_event_with_its_fields(self):
        from test_minecraft_companion import _load_panel
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for d in ("server", "backups", "state", "worlds"):
                (root / d).mkdir(parents=True)
            panel = _load_panel(root)
            self.assertIn("point", panel.GAME_EVENTS)
            name, data = panel.game_event(
                {"t": 5, "kind": "point", "player": "Ben13765", "shown": "dad",
                 "dimension": OW, "target": {"x": 1, "y": 2, "z": 3, "block": "minecraft:stone"},
                 "building": {"id": "b", "name": "x"}, "room": None},
                lambda p: (True, ""), "world")
            self.assertEqual(name, "bruh_minecraft_point")
            self.assertEqual({k: data[k] for k in ("player", "name", "verified", "dimension",
                                                   "target", "building", "room")},
                             {"player": "Ben13765", "name": "dad", "verified": True,
                              "dimension": OW, "building": {"id": "b", "name": "x"},
                              "room": None,
                              "target": {"x": 1, "y": 2, "z": 3, "block": "minecraft:stone"}})


if __name__ == "__main__":
    unittest.main()
