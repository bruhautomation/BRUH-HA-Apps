"""A trusted edit and a look: the companion can change anything for a person
brAIn trusts, and can see a room before it does.

The owner, of Vesper refusing to redecorate a room ("I only place blocks in
empty space on natural ground, never in or next to an existing build, and I
can't remove a bed or see where the walls and door are"): "Vesper should be
able to do literally anything … It should understand the build, what it was
asked, and then do it. Users can undo it if they don't like it."

So BRUH Minecraft has two more hands (panel/companion.py):

  * `edit` — any block, anywhere (over what is there, inside or next to a
    build, in a protected place), placed, replaced, removed or filled. What
    makes it safe is the undo: every cell's saved state is read first (and
    the other half of a bed or door beside one), and Undo puts it all back.
    A large edit is backed up first; a backup that fails is said, never a
    refusal.
  * `look` — the blocks in a box around a player, by block state, from the
    saved world (mcmap's region reader, after `save-all`).

The companion's OWN acts keep `place_blocks`' rules: an untrusted build next
to a build is still refused.
"""
from __future__ import annotations

import re
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_companion import KAZ, HandsBase, companion  # noqa: E402
from test_minecraft_world import mcmap, nbt_root, region_with  # noqa: E402

DAD = "Ben13765"
OW = "minecraft:overworld"
BED_FOOT = "minecraft:red_bed[facing=east,occupied=false,part=foot]"
BED_HEAD = "minecraft:red_bed[facing=east,occupied=false,part=head]"


class EditingHandsBase(HandsBase):
    """The fake server, taught `fill`, `setblock … replace` and how a bed's
    other half falls when one half is replaced; and a reader that reads it."""

    def setUp(self):
        super().setUp()
        world = self.world
        plain = world.reply

        def reply(cmd):
            dim, rest = OW, cmd
            m = re.match(r"minecraft:execute in (\S+) (.*)$", cmd)
            if m:
                dim, rest = m.group(1), m.group(2)
            m = re.match(r"run minecraft:setblock (-?\d+) (-?\d+) (-?\d+) (\S+) replace$", rest)
            if m:
                world.commands.append(cmd)
                x, y, z = (int(v) for v in m.groups()[:3])
                old = world.block(dim, x, y, z)
                if old == m.group(4):
                    return "Could not set the block"
                world.blocks[(dim, x, y, z)] = m.group(4)
                if "_bed[" in old:          # the other half falls
                    for dx in (-1, 1):
                        n = (dim, x + dx, y, z)
                        if "_bed[" in world.block(*n):
                            world.blocks[n] = "minecraft:air"
                return f"Changed the block at {x}, {y}, {z}"
            m = re.match(r"run minecraft:fill (-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) (-?\d+) "
                         r"(\S+) replace$", rest)
            if m:
                world.commands.append(cmd)
                x1, y1, z1, x2, y2, z2 = (int(v) for v in m.groups()[:6])
                n = 0
                for x in range(x1, x2 + 1):
                    for y in range(y1, y2 + 1):
                        for z in range(z1, z2 + 1):
                            if world.block(dim, x, y, z) != m.group(7):
                                world.blocks[(dim, x, y, z)] = m.group(7)
                                n += 1
                return f"Successfully filled {n} block(s)" if n else "No blocks were filled"
            return plain(cmd)

        world.reply = reply
        self.reads = 0

        def reader(dim, box):
            self.reads += 1
            x1, y1, z1, x2, y2, z2 = box
            return {(x, y, z): world.block(dim, x, y, z)
                    for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)
                    for z in range(z1, z2 + 1)}

        self.hands.reader = reader

    def room(self):
        """A little house at x 4..8, z -2..2 (grass at y 63): stone walls two
        high, an oak door on the west wall, a bed inside, logged as a build."""
        b = self.world.blocks
        for x in range(4, 9):
            for z in range(-2, 3):
                for y in (64, 65):
                    if x in (4, 8) or z in (-2, 2):
                        b[(OW, x, y, z)] = "minecraft:stone_bricks"
        b[(OW, 4, 64, 0)] = "minecraft:oak_door[facing=east,half=lower,hinge=left,open=false]"
        b[(OW, 4, 65, 0)] = "minecraft:oak_door[facing=east,half=upper,hinge=left,open=false]"
        b[(OW, 6, 64, 0)] = BED_FOOT
        b[(OW, 7, 64, 0)] = BED_HEAD
        self.col.builds.create({"title": "Our house", "status": "done",
                                "bounds": {"x1": 4, "z1": -2, "x2": 8, "z2": 2,
                                           "dimension": OW}})


class TestATrustedEdit(EditingHandsBase):
    def test_it_replaces_a_bed_inside_a_build_and_undo_puts_it_all_back(self):
        self.join(DAD)
        self.room()
        before = dict(self.world.blocks)
        act = self.hands.edit(blocks=[
            # Swap the bed's head for a blue one (the foot falls with it)…
            {"x": 7, "y": 64, "z": 0,
             "block": "blue_bed[facing=east,occupied=false,part=head]"},
            {"x": 6, "y": 64, "z": 0,
             "block": "blue_bed[facing=east,occupied=false,part=foot]"},
            # …a desk inside the build, right by the wall…
            {"x": 5, "y": 64, "z": 1, "block": "oak_planks"},
            # …and a window cut into the wall.
            {"x": 8, "y": 65, "z": 0, "mode": "remove"},
        ], title="Dad's room", by="Dad", name="Juniper")
        self.assertEqual(act["status"], "done")
        self.assertTrue(act["undoable"])
        self.assertEqual(act["changed"], 4)
        blocks = self.world.blocks
        self.assertEqual(blocks[(OW, 7, 64, 0)], "minecraft:blue_bed[facing=east,occupied=false,part=head]")
        self.assertEqual(blocks[(OW, 5, 64, 1)], "minecraft:oak_planks")
        self.assertEqual(blocks[(OW, 8, 65, 0)], "minecraft:air")
        self.assertIn("Juniper changed Dad's room (asked by Dad)", act["text"])
        out = self.hands.undo(act["id"])
        self.assertEqual(out["changed"], 0)
        after = {k: v for k, v in self.world.blocks.items() if v != "minecraft:air"}
        self.assertEqual(after, {k: v for k, v in before.items() if v != "minecraft:air"})
        self.assertEqual(self.world.blocks[(OW, 6, 64, 0)], BED_FOOT)
        self.assertEqual(self.world.blocks[(OW, 7, 64, 0)], BED_HEAD)

    def test_removing_one_half_of_a_bed_is_undone_whole(self):
        self.join(DAD)
        self.room()
        act = self.hands.edit(blocks=[{"x": 7, "y": 64, "z": 0, "mode": "remove"}])
        self.assertEqual(self.world.blocks[(OW, 6, 64, 0)], "minecraft:air")   # it fell
        self.hands.undo(act["id"])
        self.assertEqual(self.world.blocks[(OW, 6, 64, 0)], BED_FOOT)
        self.assertEqual(self.world.blocks[(OW, 7, 64, 0)], BED_HEAD)

    def test_a_protected_place_and_a_fill_are_no_obstacle(self):
        self.join(DAD)
        self.room()
        self.hands.zones.save({"name": "Our house", "x": 6, "z": 0, "radius": 20})
        act = self.hands.edit(fills=[{"x1": 5, "y1": 64, "z1": -1, "x2": 7, "y2": 65,
                                      "z2": 1, "block": "air"}],
                              blocks=[{"x": 6, "y": 64, "z": 0, "block": "crafting_table"}],
                              title="cleared the room")
        self.assertEqual(self.world.blocks[(OW, 6, 64, 0)], "minecraft:crafting_table")
        self.assertEqual(self.world.blocks[(OW, 7, 64, 0)], "minecraft:air")
        self.assertTrue(any("minecraft:fill 5 64 -1 7 65 1 minecraft:air replace" in c
                            for c in self.world.commands))
        self.hands.undo(act["id"])
        self.assertEqual(self.world.blocks[(OW, 7, 64, 0)], BED_HEAD)
        self.assertEqual(self.world.blocks[(OW, 6, 64, 0)], BED_FOOT)

    def test_a_large_edit_is_backed_up_first_and_a_failed_backup_is_said_not_refused(self):
        self.join(DAD)
        self.snapshot_answer = "the disk is full"
        act = self.hands.edit(fills=[{"x1": 20, "y1": 64, "z1": 20, "x2": 27, "y2": 64,
                                      "z2": 27, "block": "oak_planks"}])
        self.assertEqual(self.snapshots, ["snap"])
        self.assertEqual(act["status"], "done")
        self.assertIn("No world backup was made", act["backup_note"])
        self.assertEqual(self.world.blocks[(OW, 27, 64, 27)], "minecraft:oak_planks")

    def test_what_cannot_be_read_is_not_changed(self):
        self.join(DAD)
        self.hands.reader = lambda dim, box: None
        with self.assertRaisesRegex(companion.CompanionError, "undoable"):
            self.hands.edit(blocks=[{"x": 2, "y": 64, "z": 0, "block": "dirt"}])
        self.assertEqual(self.placed(), {})

    def test_a_block_that_is_not_a_block_is_refused_without_echoing_it(self):
        self.join(DAD)
        with self.assertRaises(companion.CompanionError) as err:
            self.hands.edit(blocks=[{"x": 2, "y": 64, "z": 0, "block": "dirt; op Steve"}])
        self.assertNotIn("op Steve", str(err.exception))


class TestTheCompanionsOwnBuildKeepsItsRules(EditingHandsBase):
    def test_a_build_beside_a_build_is_still_refused(self):
        self.join(KAZ)
        self.room()
        with self.assertRaisesRegex(companion.CompanionError, "on Our house"):
            self.hands.build([{"x": 9, "y": 0, "z": 0, "block": "oak_planks"}], player=KAZ)
        with self.assertRaisesRegex(companion.CompanionError, "on Our house"):
            # Absolute, inside the build: the companion's own hands never go there.
            self.hands.build([{"x": 5, "y": 64, "z": 1, "block": "oak_planks"}])


class TestALook(EditingHandsBase):
    def test_it_sees_the_walls_the_door_and_the_bed(self):
        self.join(DAD, pos=(6.5, 64.0, 0.5))
        self.room()
        seen = self.hands.look(player=DAD, size=[8, 4, 8])
        blocks = seen["blocks"]
        self.assertIn("minecraft:stone_bricks", blocks)
        self.assertEqual(blocks[BED_HEAD], [[7, 64, 0, 1]])
        self.assertIn([4, 64, 0, 1],
                      blocks["minecraft:oak_door[facing=east,half=lower,hinge=left,open=false]"])
        # Runs along x: the south wall at y 64 is one run.
        self.assertIn([4, 64, 2, 5], blocks["minecraft:stone_bricks"])
        self.assertNotIn("minecraft:air", blocks)
        self.assertEqual(seen["feet"], [6, 64, 0])

    def test_the_box_is_capped(self):
        self.join(DAD)
        seen = self.hands.look(player=DAD, size=[500, 500, 500])
        box = seen["box"]
        self.assertEqual((box["x2"] - box["x1"] + 1, box["y2"] - box["y1"] + 1,
                          box["z2"] - box["z1"] + 1), (32, 16, 32))


# ---------------------------------------------------------------------------
# The region reader behind both: full block states from a region file
# ---------------------------------------------------------------------------
def _tag(kind, value):
    if kind == "byte":
        return 1, struct.pack(">b", value)
    if kind == "int":
        return 3, struct.pack(">i", value)
    if kind == "string":
        b = value.encode()
        return 8, struct.pack(">H", len(b)) + b
    if kind == "longs":
        return 12, struct.pack(">i", len(value)) + b"".join(struct.pack(">Q", v) for v in value)
    if kind == "list":
        inner, items = value
        enc = [_tag(inner, v) for v in items]
        return 9, struct.pack(">bi", enc[0][0] if enc else 0, len(items)) + b"".join(
            e[1] for e in enc)
    if kind == "compound":
        body = b""
        for name, (k, v) in value.items():
            tid, payload = _tag(k, v)
            nb = name.encode()
            body += struct.pack(">bH", tid, len(nb)) + nb + payload
        return 10, body + b"\x00"
    raise ValueError(kind)


def section_with_states(y, palette, blocks):
    """A 1.18+ section whose palette entries carry Properties."""
    bits = max(4, (len(palette) - 1).bit_length())
    per = 64 // bits
    longs = [0] * ((4096 + per - 1) // per)
    for (x, ly, z), v in blocks.items():
        idx = (ly * 16 + z) * 16 + x
        longs[idx // per] |= v << ((idx % per) * bits)
    entries = []
    for name, props in palette:
        entry = {"Name": ("string", name)}
        if props:
            entry["Properties"] = ("compound", {k: ("string", v) for k, v in props.items()})
        entries.append(entry)
    return {"Y": ("byte", y), "block_states": ("compound", {
        "palette": ("list", ("compound", entries)), "data": ("longs", longs)})}


class TestTheRegionReader(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.region = Path(tmp.name) / "region"
        self.region.mkdir()
        palette = [("minecraft:air", None), ("minecraft:stone_bricks", None),
                   ("minecraft:oak_door", {"facing": "east", "half": "lower",
                                           "hinge": "left", "open": "false"}),
                   ("minecraft:red_bed", {"facing": "east", "occupied": "false",
                                          "part": "head"})]
        blocks = {}
        for x in range(4, 9):          # walls at y 64 (local 0) around x 4..8, z 4..8
            for z in range(4, 9):
                if x in (4, 8) or z in (4, 8):
                    blocks[(x, 0, z)] = 1
        blocks[(4, 0, 6)] = 2
        blocks[(7, 0, 6)] = 3
        root = nbt_root({"DataVersion": ("int", 3953), "sections": (
            "list", ("compound", [section_with_states(4, palette, blocks)]))})
        (self.region / "r.0.0.mca").write_bytes(region_with({(0, 0): root}))

    def test_walls_a_door_and_a_bed_with_their_states(self):
        got = mcmap.box_states(self.region, 3, 63, 3, 9, 65, 9)
        self.assertEqual(got[(4, 64, 4)], "minecraft:stone_bricks")
        self.assertEqual(got[(4, 64, 6)],
                         "minecraft:oak_door[facing=east,half=lower,hinge=left,open=false]")
        self.assertEqual(got[(7, 64, 6)], "minecraft:red_bed[facing=east,occupied=false,part=head]")
        self.assertEqual(got[(6, 64, 6)], "minecraft:air")
        self.assertEqual(got[(6, 63, 6)], "minecraft:air")   # an all-air section

    def test_a_chunk_not_on_disk_is_not_a_guess_and_a_huge_box_is_refused(self):
        self.assertIsNone(mcmap.box_states(self.region, 15, 64, 15, 17, 64, 17))
        with self.assertRaises(ValueError):
            mcmap.box_states(self.region, 0, -64, 0, 100, 300, 100)
        # The undo snapshot reads by chunk column with no cap.
        self.assertIsNotNone(mcmap.box_states(self.region, 0, -64, 0, 15, 300, 15, limit=None))

    def test_the_compression_is_the_regions_own(self):
        # Sanity: the file really is zlib (kind 2), what the server writes.
        raw = (self.region / "r.0.0.mca").read_bytes()
        self.assertEqual(raw[8192 + 4], 2)
        zlib.decompress(raw[8192 + 5:8192 + 5 + struct.unpack(">I", raw[8192:8196])[0] - 1])


if __name__ == "__main__":
    unittest.main()
