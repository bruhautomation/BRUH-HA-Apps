"""A look and an edit work wherever the work is: in the End and the Nether,
in chunks nobody is standing in, and over cells that already hold what
was asked for (#782, #776).

What the house saw, building in the End through brAIn:

  * a look or an edit by coordinates always read and changed the
    Overworld, so nothing in the End or the Nether could be looked at or
    changed by coordinates (only a look around a player followed them);
  * an edit far from everybody failed with "That position is not loaded";
  * a shape of air failed as a whole with "Could not set the block" when
    one of its cells was already air;
  * a look straight after a change read the world as saved a moment
    before it, and came back empty.

So, in panel/companion.py: without a dimension, an edit takes its job's
(the dimension that job's earlier edits were made in), and a look or an
edit takes the dimension of whoever is playing (the nearest one when they
are in several); an edit force-loads the chunks the server says are not
loaded, for as long as it takes, and lets them go after; a cell that
already holds what was asked is no failure and is left out of the undo;
and every look and edit asks for a fresh save before it reads the disk.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_companion import DAD, KAZ, _load_panel, companion  # noqa: E402
from test_minecraft_companion_edit import EditingHandsBase  # noqa: E402

OW = "minecraft:overworld"
END = "minecraft:the_end"
NETHER = "minecraft:the_nether"


class Worlds(EditingHandsBase):
    """The editing fake, taught three more things a real server does: a
    player's dimension, chunks that are not loaded (and `forceload`), and
    its answer to a block test there."""

    def setUp(self):
        super().setUp()
        world = self.world
        self.dims: dict[str, str] = {}
        self.unloaded: set[tuple[str, int, int]] = set()
        self.forced: set[tuple[str, int, int]] = set()
        self.forceloads: list[str] = []
        inner = world.reply

        def reply(cmd):
            m = re.match(r"minecraft:data get entity (\S+) Dimension$", cmd)
            if m and m.group(1) in self.dims and m.group(1) in world.players:
                world.commands.append(cmd)
                return f'{m.group(1)} has the following entity data: "{self.dims[m.group(1)]}"'
            dim, rest = OW, cmd
            m = re.match(r"minecraft:execute in (\S+) (.*)$", cmd)
            if m:
                dim, rest = m.group(1), m.group(2)
            m = re.match(r"run minecraft:forceload (add|remove|query) (-?\d+) (-?\d+)$", rest)
            if m:
                world.commands.append(cmd)
                self.forceloads.append(cmd)
                key = (dim, int(m.group(2)) >> 4, int(m.group(3)) >> 4)
                if m.group(1) == "add":
                    self.forced.add(key)
                    return "Marked chunk [x, z] in minecraft:dim to be force loaded"
                if m.group(1) == "remove":
                    self.forced.discard(key)
                    return "Unmarked chunk [x, z] in minecraft:dim for force loading"
                return (f"Chunk at [x, z] in {dim} is "
                        + ("marked" if key in self.forced else "not marked")
                        + " for force loading")
            nums = [int(v) for v in re.findall(r" (-?\d+)", rest)]
            if re.match(r"(run minecraft:(setblock|fill)|if block) ", rest) and nums:
                xs, zs = nums[0::3], nums[2::3]
                for x in range(min(xs), max(xs) + 1):
                    for z in range(min(zs), max(zs) + 1):
                        key = (dim, x >> 4, z >> 4)
                        if key in self.unloaded and key not in self.forced:
                            world.commands.append(cmd)
                            return "That position is not loaded"
            return inner(cmd)

        world.reply = reply

    def join_in(self, name: str, dim: str, pos=(0.5, 64.0, 0.5)) -> None:
        self.dims[name] = dim
        self.join(name, pos)

    def edits_in(self, dim: str) -> list[str]:
        return [c for c in self.world.commands
                if c.startswith(f"minecraft:execute in {dim} run minecraft:")
                and re.search(r"(setblock|fill) ", c)]


class TestTheDimensionOfTheWork(Worlds):
    def test_an_edit_in_the_end_follows_the_player_and_its_job_takes_it_back(self):
        self.join_in(DAD, END, pos=(100.5, 64.0, 0.5))
        act = self.hands.edit(blocks=[{"x": 100, "y": 70, "z": 0, "block": "end_stone"},
                                      {"x": 101, "y": 70, "z": 0, "block": "end_stone"}],
                              job="j1a2b3c", title="a platform")
        self.assertEqual(act["status"], "done")
        self.assertEqual(act["dimension"], END)
        self.assertEqual(self.world.blocks.get((END, 100, 70, 0)), "minecraft:end_stone")
        self.assertNotIn((OW, 100, 70, 0), self.world.blocks)
        self.assertTrue(self.edits_in(END))
        self.assertFalse(self.edits_in(OW))
        out = self.hands.undo_job("j1a2b3c")
        self.assertEqual(out["undone"], [act["id"]])
        self.assertEqual(self.world.block(END, 100, 70, 0), "minecraft:air")
        self.assertEqual(self.world.block(END, 101, 70, 0), "minecraft:air")

    def test_a_job_keeps_its_dimension_when_nobody_is_there_any_more(self):
        # The first edit names the Nether; the player then leaves, and the
        # job's next edit goes where the job is, not to the Overworld.
        self.join(DAD)
        first = self.hands.edit(blocks=[{"x": 5, "y": 80, "z": 5, "block": "netherrack"}],
                                dimension=NETHER, job="j0ffee1")
        self.assertEqual(first["dimension"], NETHER)
        self.leave(DAD)
        second = self.hands.edit(blocks=[{"x": 6, "y": 80, "z": 5, "block": "glowstone"}],
                                 job="j0ffee1")
        self.assertEqual(second["dimension"], NETHER)
        self.assertEqual(self.world.blocks.get((NETHER, 6, 80, 5)), "minecraft:glowstone")
        self.hands.undo_job("j0ffee1")
        self.assertEqual(self.world.block(NETHER, 5, 80, 5), "minecraft:air")
        self.assertEqual(self.world.block(NETHER, 6, 80, 5), "minecraft:air")

    def test_a_look_by_coordinates_reads_where_the_players_are(self):
        self.world.blocks[(END, 3, 70, 3)] = "minecraft:end_stone"
        self.join_in(KAZ, END)
        seen = self.hands.look(x=3, y=70, z=3, size=[4, 4, 4])
        self.assertEqual(seen["dimension"], END)
        self.assertIn("minecraft:end_stone", seen["blocks"])

    def test_players_in_two_dimensions_the_nearest_one_decides(self):
        self.join_in(DAD, OW, pos=(0.5, 64.0, 0.5))
        self.join_in(KAZ, NETHER, pos=(900.5, 64.0, 900.5))
        self.world.blocks[(NETHER, 901, 70, 901)] = "minecraft:glowstone"
        seen = self.hands.look(x=901, y=70, z=901, size=[4, 4, 4])
        self.assertEqual(seen["dimension"], NETHER)
        self.assertIn("minecraft:glowstone", seen["blocks"])
        near_dad = self.hands.look(x=2, y=64, z=2, size=[4, 4, 4])
        self.assertEqual(near_dad["dimension"], OW)

    def test_a_named_dimension_still_wins(self):
        self.join_in(DAD, END)
        act = self.hands.edit(blocks=[{"x": 1, "y": 70, "z": 1, "block": "stone"}],
                              dimension=OW)
        self.assertEqual(act["dimension"], OW)
        self.assertEqual(self.world.blocks.get((OW, 1, 70, 1)), "minecraft:stone")


class TestChunksNobodyIsIn(Worlds):
    def test_an_edit_far_from_everybody_loads_its_chunks_and_lets_them_go(self):
        self.join(DAD)
        self.unloaded |= {(OW, 1000 >> 4, 1000 >> 4), (OW, 1020 >> 4, 1000 >> 4)}
        act = self.hands.edit(fills=[{"x1": 1000, "y1": 70, "z1": 1000, "x2": 1003, "y2": 70,
                                      "z2": 1000, "block": "stone"}],
                              blocks=[{"x": 1020, "y": 70, "z": 1000, "block": "oak_log"}])
        self.assertEqual(act["status"], "done")
        self.assertEqual(self.world.blocks.get((OW, 1003, 70, 1000)), "minecraft:stone")
        self.assertEqual(self.world.blocks.get((OW, 1020, 70, 1000)), "minecraft:oak_log")
        self.assertEqual(self.forced, set(), "every chunk it loaded is let go")
        # …and its undo, with still nobody near, does the same.
        out = self.hands.undo(act["id"])
        self.assertEqual(out["restored"], 5)
        self.assertEqual(self.world.block(OW, 1020, 70, 1000), "minecraft:air")
        self.assertEqual(self.forced, set())

    def test_a_chunk_somebody_else_keeps_loaded_is_left_loaded(self):
        self.join(DAD)
        key = (OW, 2000 >> 4, 2000 >> 4)
        self.unloaded.add(key)
        self.forced.add(key)          # a farm the family keeps loaded
        self.hands.edit(blocks=[{"x": 2000, "y": 70, "z": 2000, "block": "stone"}])
        self.assertIn(key, self.forced)
        self.assertFalse([c for c in self.forceloads if " remove " in c])


class TestCellsThatAlreadyHoldIt(Worlds):
    def stale(self, says: dict):
        """A reader that saw the world a moment ago: these cells as they were."""
        live = self.hands.reader

        def reader(dim, box):
            got = live(dim, box)
            for (d, x, y, z), st in says.items():
                if d == dim and (x, y, z) in got:
                    got[(x, y, z)] = st
            return got
        self.hands.reader = reader

    def test_an_air_shape_over_a_cell_that_is_already_air_clears_the_rest(self):
        # A trunk of air through a pillar, one block of which was dug out a
        # moment before: each cell is its own `setblock`, and the dug one
        # answers "Could not set the block".
        self.join(DAD)
        for y in (70, 71, 72):
            self.world.blocks[(OW, 11, y, 0)] = "minecraft:stone"
        self.world.blocks[(OW, 11, 71, 0)] = "minecraft:air"
        self.stale({(OW, 11, 71, 0): "minecraft:stone"})
        act = self.hands.edit(shapes=[{"kind": "line", "from": [11, 70, 0], "to": [11, 72, 0],
                                       "radius": 0, "block": "air"}])
        self.assertEqual(act["status"], "done")
        for y in (70, 71, 72):
            self.assertEqual(self.world.block(OW, 11, y, 0), "minecraft:air")
        self.hands.undo(act["id"])
        self.assertEqual(self.world.block(OW, 11, 70, 0), "minecraft:stone")
        self.assertEqual(self.world.block(OW, 11, 72, 0), "minecraft:stone")
        self.assertEqual(self.world.block(OW, 11, 71, 0), "minecraft:air",
                         "a cell that already held it is not 'put back' to what it never was")

    def test_a_single_block_that_is_already_there_is_no_failure(self):
        self.join(DAD)
        self.world.blocks[(OW, 30, 70, 0)] = "minecraft:oak_planks"
        self.stale({(OW, 30, 70, 0): "minecraft:air"})
        act = self.hands.edit(blocks=[{"x": 30, "y": 70, "z": 0, "block": "oak_planks"},
                                      {"x": 32, "y": 70, "z": 0, "block": "glass"}])
        self.assertEqual(act["status"], "done")
        self.assertEqual(self.world.block(OW, 32, 70, 0), "minecraft:glass")
        self.hands.undo(act["id"])
        self.assertEqual(self.world.block(OW, 30, 70, 0), "minecraft:oak_planks")
        self.assertEqual(self.world.block(OW, 32, 70, 0), "minecraft:air")


class TestEveryReadIsFresh(Worlds):
    def test_a_look_and_an_edit_each_ask_for_a_fresh_read_first(self):
        asked = []
        hands = companion.Companion(self.col, reader=self.hands.reader, clock=self.clock,
                                    reading=lambda: asked.append("fresh"))
        hands.set_identity(name="Juniper", active=True, by="brAIn")
        self.join(DAD)
        hands.look(player=DAD)
        self.assertEqual(asked, ["fresh"])
        hands.edit(blocks=[{"x": 2, "y": 64, "z": 0, "block": "dirt"}])
        self.assertEqual(asked, ["fresh", "fresh"])


class TestThePanelSavesBeforeAFreshRead(unittest.TestCase):
    def test_a_save_from_a_moment_ago_is_not_trusted_after_a_change(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for d in ("server", "backups", "state"):
            (root / d).mkdir()
        (root / "server" / "server.properties").write_text("level-name=world\n")
        for key in ("MC_WWW_DIR", "MC_WORLDS_DIR", "MC_CHANGELOG"):
            self.addCleanup(os.environ.pop, key, None)
        panel = _load_panel(root)
        sent = []

        class Rcon:
            def __init__(self, *a, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def command(self, cmd):
                sent.append(cmd)
                return ""

        with unittest.mock.patch.object(panel, "Rcon", Rcon):
            panel.save_world()
            panel.save_world()            # a moment later: the save still stands
            self.assertEqual(sent, ["save-all flush"])
            panel.fresh_read()            # a look or an edit is about to read
            panel.save_world()
        self.assertEqual(sent, ["save-all flush", "save-all flush"])
