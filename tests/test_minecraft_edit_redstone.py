"""An edit that flips a lever leaves the redstone it drives as the lever
says (#778).

What the house saw: `minecraft_world` edit set a lever from on to off, the
lever showed off, and the repeating command block beside the block it was
on stayed powered and kept running every tick.

Why: `setblock … replace` updates the six neighbours of the cell it sets,
and nothing more. A lever (or a button) powers the block it is attached
to, and that block powers ITS neighbours — the command block. In the game
a flip calls the lever's own update of the attached block's neighbours; a
`setblock` of the same block with another state never does, and placing a
lever where there was none never does either (only taking a powered one
away does).

So, in panel/companion.py: after an edit, each cell whose power changed
(a lever, button, plate, dust, torch, repeater, observer and the like set
to another power, or put in or taken away) is set for a moment to an UNLIT
redstone torch and then to what was asked. A torch's placing and its
taking away update the neighbours of all six cells around it — the
attached block's neighbours among them — and an unlit one gives no power
and drops nothing. Every other edit is sent exactly as before.

The fake below is the vanilla rules that matter here: a `setblock`/`fill`
updates the cell's neighbours; a powered lever taken away, and a redstone
torch put in or taken away, update the neighbours of the cells around them;
a command block's `powered` is whether it has a signal when it is updated.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_companion_edit import OW, EditingHandsBase  # noqa: E402

LEVER_ON = "minecraft:lever[face=floor,facing=north,powered=true]"
LEVER_OFF = "minecraft:lever[face=floor,facing=north,powered=false]"
CB = "minecraft:repeating_command_block[conditional=false,facing=up]"
SIDES = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
TORCH = re.compile(r"minecraft:redstone(_wall)?_torch\b")


def _add(a, d):
    return (a[0] + d[0], a[1] + d[1], a[2] + d[2])


def _attached(pos, state):
    """The cell a lever or button hangs on."""
    face = re.search(r"face=(\w+)", state)
    facing = re.search(r"facing=(\w+)", state)
    if face and face.group(1) == "floor":
        return _add(pos, (0, -1, 0))
    if face and face.group(1) == "ceiling":
        return _add(pos, (0, 1, 0))
    back = {"north": (0, 0, 1), "south": (0, 0, -1), "east": (-1, 0, 0), "west": (1, 0, 0)}
    return _add(pos, back[facing.group(1) if facing else "north"])


class RedstoneWorld(EditingHandsBase):
    """The editing fake, taught the vanilla updates around a lever and a
    command block's `powered` flag."""

    def setUp(self):
        super().setUp()
        world = self.world
        self.powered: dict[tuple[int, int, int], bool] = {}
        self.placed_torches: list[tuple[int, int, int]] = []
        inner = world.reply

        def reply(cmd):
            m = re.match(r"minecraft:execute in (\S+) run minecraft:(setblock|fill) (.*)$", cmd)
            if not m or m.group(1) != OW:
                return inner(cmd)
            nums = [int(v) for v in re.findall(r"-?\d+", m.group(3).split(" minecraft:")[0])]
            if m.group(2) == "setblock":
                box = nums[:3] * 2
            else:
                box = nums[:6]
            cells = [(x, y, z) for x in range(box[0], box[3] + 1)
                     for y in range(box[1], box[4] + 1) for z in range(box[2], box[5] + 1)]
            before = {c: world.block(OW, *c) for c in cells}
            out = inner(cmd)
            for c in cells:
                old, new = before[c], world.block(OW, *c)
                if old != new:
                    self._changed(c, old, new)
            return out

        world.reply = reply

    # -- vanilla --------------------------------------------------------------
    def _state(self, c):
        return self.world.block(OW, *c)

    def _strongly_powered(self, c):
        """A lever that is on powers the block it hangs on."""
        for d in SIDES:
            n = _add(c, d)
            st = self._state(n)
            if st.startswith("minecraft:lever[") and "powered=true" in st \
                    and _attached(n, st) == c:
                return True
        return False

    def _signal(self, c):
        for d in SIDES:
            n = _add(c, d)
            st = self._state(n)
            if st.startswith("minecraft:lever[") and "powered=true" in st:
                return True
            if self._strongly_powered(n):
                return True
        return False

    def _neighbour_changed(self, c):
        if self._state(c).startswith("minecraft:repeating_command_block"):
            self.powered[c] = self._signal(c)

    def _update_neighbours_at(self, c):
        for d in SIDES:
            self._neighbour_changed(_add(c, d))

    def _changed(self, c, old, new):
        old_id, new_id = old.split("[")[0], new.split("[")[0]
        if old_id != new_id:
            # The old block's removal.
            if old_id == "minecraft:lever" and "powered=true" in old:
                self._update_neighbours_at(c)
                self._update_neighbours_at(_attached(c, old))
            if TORCH.match(old):
                for d in SIDES:
                    self._update_neighbours_at(_add(c, d))
            # The new block's placing (a lever has none).
            if TORCH.match(new):
                self.placed_torches.append(c)
                for d in SIDES:
                    self._update_neighbours_at(_add(c, d))
        # What `setblock`/`fill … replace` itself does.
        self._update_neighbours_at(c)

    # -- the build ------------------------------------------------------------
    def build(self, lever):
        """A lever on a stone block, a repeating command block beside the
        stone (not beside the lever), its `powered` as the lever says."""
        self.lever, self.stone, self.cb = (10, 66, 10), (10, 65, 10), (11, 65, 10)
        self.world.blocks[(OW, *self.lever)] = lever
        self.world.blocks[(OW, *self.stone)] = "minecraft:stone"
        self.world.blocks[(OW, *self.cb)] = CB
        self.powered[self.cb] = "powered=true" in lever
        self.assertEqual(self.powered[self.cb], self._signal(self.cb))

    def flip(self, to):
        x, y, z = self.lever
        return self.hands.edit(blocks=[{"x": x, "y": y, "z": z, "block": to}],
                               title="the lever")


class TestALeverFlippedByAnEdit(RedstoneWorld):
    def test_off_unpowers_the_command_block_beside_the_block_it_is_on(self):
        self.build(LEVER_ON)
        act = self.flip(LEVER_OFF)
        self.assertEqual(act["status"], "done")
        self.assertEqual(self._state(self.lever), LEVER_OFF)
        self.assertFalse(self.powered[self.cb], "the command block kept running every tick")

    def test_on_powers_it(self):
        self.build(LEVER_OFF)
        self.flip(LEVER_ON)
        self.assertEqual(self._state(self.lever), LEVER_ON)
        self.assertTrue(self.powered[self.cb])

    def test_a_new_lever_that_is_on_powers_it_too(self):
        self.build(LEVER_OFF)
        self.world.blocks[(OW, *self.lever)] = "minecraft:air"
        self.flip(LEVER_ON)
        self.assertEqual(self._state(self.lever), LEVER_ON)
        self.assertTrue(self.powered[self.cb])

    def test_undo_puts_the_lever_and_what_it_drives_back(self):
        self.build(LEVER_ON)
        act = self.flip(LEVER_OFF)
        self.assertFalse(self.powered[self.cb])
        self.hands.undo(act["id"])
        self.assertEqual(self._state(self.lever), LEVER_ON)
        self.assertTrue(self.powered[self.cb])

    def test_the_moment_of_torch_is_unlit_and_never_left_behind(self):
        self.build(LEVER_ON)
        act = self.flip(LEVER_OFF)
        torches = [c for c in self.world.commands if TORCH.search(c)]
        self.assertTrue(torches)
        self.assertTrue(all("lit=false" in c for c in torches), torches)
        self.assertFalse([c for c, st in self.world.blocks.items() if TORCH.match(st)])
        # The undo records the lever, not the torch.
        cells = self.hands.actions.get(act["id"])["cells"]
        self.assertEqual([(c["before"], c["after"]) for c in cells], [(LEVER_ON, LEVER_OFF)])


class TestEverythingElseIsSentAsBefore(RedstoneWorld):
    def test_a_wall_of_stone_has_no_torch_moment(self):
        self.build(LEVER_ON)
        self.hands.edit(fills=[{"x1": 0, "y1": 64, "z1": 0, "x2": 3, "y2": 66, "z2": 0,
                                "block": "stone"}],
                        blocks=[{"x": 5, "y": 64, "z": 5, "block": "oak_planks"}])
        self.assertFalse([c for c in self.world.commands if TORCH.search(c)])
        self.assertTrue(self.powered[self.cb])

    def test_a_lever_set_to_the_power_it_already_had_is_left_alone(self):
        # Same power, another facing: nothing it drives changes.
        self.build(LEVER_ON)
        self.flip("minecraft:lever[face=floor,facing=east,powered=true]")
        self.assertFalse([c for c in self.world.commands if TORCH.search(c)])
        self.assertTrue(self.powered[self.cb])


if __name__ == "__main__":
    unittest.main()
