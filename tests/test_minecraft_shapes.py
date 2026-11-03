"""Shapes in a trusted edit: trunks, canopies, rocks and towers in one call.

A companion asked for "a giant tree" used to send every block of it, and an
edit held 32,768 cells sent as one `setblock` each. `companion_edit` now
takes `shapes` — a tapering line, an ellipsoid, a seeded blob, a cylinder
and a box — expanded to cells by the add-on before the undo snapshot, up
to 131,072 cells in one edit, written as `fill` runs along x, and recorded
with the caller's `job` so every edit of a job can be undone together.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_companion_edit import DAD, OW, EditingHandsBase  # noqa: E402
from test_minecraft_companion import companion  # noqa: E402

shapes = companion.shapes


def ext(cells):
    xs, ys, zs = zip(*cells)
    return (min(xs), max(xs)), (min(ys), max(ys)), (min(zs), max(zs))


class TestTheShapes(unittest.TestCase):
    def cells(self, shape, base=None):
        return shapes.expand(shape, base=base)

    def test_box_and_hollow_box(self):
        self.assertEqual(len(self.cells({"kind": "box", "from": [0, 0, 0], "to": [2, 2, 2]})), 27)
        hollow = self.cells({"kind": "box", "from": [0, 0, 0], "to": [2, 2, 2], "hollow": True})
        self.assertEqual(len(hollow), 26)
        self.assertNotIn((1, 1, 1), hollow)

    def test_cylinder_tapers_and_hollows(self):
        self.assertEqual(len(self.cells({"kind": "cylinder", "base": [0, 0, 0], "height": 5,
                                         "radius": 0})), 5)
        self.assertEqual(len(self.cells({"kind": "cylinder", "base": [0, 0, 0], "height": 3,
                                         "radius": 2})), 63)
        taper = self.cells({"kind": "cylinder", "base": [0, 0, 0], "height": 3, "radius": 2,
                            "radius_top": 0})
        self.assertEqual(len(taper), 21 + 9 + 1)
        tube = self.cells({"kind": "cylinder", "base": [0, 0, 0], "height": 2, "radius": 2,
                           "hollow": True})
        self.assertNotIn((0, 0, 0), tube)
        self.assertIn((2, 0, 0), tube)

    def test_ellipsoid_extents(self):
        cells = self.cells({"kind": "ellipsoid", "center": [10, 70, 10], "radii": [3, 1, 2]})
        self.assertEqual(ext(cells), ((7, 13), (69, 71), (8, 12)))
        shell = self.cells({"kind": "ellipsoid", "center": [0, 0, 0], "radii": [3, 3, 3],
                            "hollow": True})
        self.assertNotIn((0, 0, 0), shell)
        self.assertLess(len(shell), len(self.cells({"kind": "ellipsoid", "center": [0, 0, 0],
                                                    "radii": [3, 3, 3]})))

    def test_line_is_a_tapering_trunk(self):
        straight = self.cells({"kind": "line", "from": [0, 0, 0], "to": [0, 10, 0], "radius": 0})
        self.assertEqual(sorted(straight), [(0, y, 0) for y in range(11)])
        trunk = self.cells({"kind": "line", "from": [0, 0, 0], "to": [0, 20, 0], "radius": 4,
                            "radius_end": 1})
        at = lambda y: sum(1 for c in trunk if c[1] == y)  # noqa: E731
        self.assertGreater(at(0), at(10))
        self.assertGreater(at(10), at(20))
        diagonal = self.cells({"kind": "line", "from": [0, 0, 0], "to": [8, 8, 8], "radius": 0})
        self.assertIn((4, 4, 4), diagonal)
        self.assertIn((8, 8, 8), diagonal)

    def test_a_blob_is_the_same_for_the_same_seed(self):
        a = self.cells({"kind": "blob", "center": [0, 80, 0], "radius": 6, "density": 0.7,
                        "seed": 4})
        self.assertEqual(a, self.cells({"kind": "blob", "center": [0, 80, 0], "radius": 6,
                                        "density": 0.7, "seed": 4}))
        self.assertNotEqual(a, self.cells({"kind": "blob", "center": [0, 80, 0], "radius": 6,
                                           "density": 0.7, "seed": 5}))
        full = self.cells({"kind": "blob", "center": [0, 80, 0], "radius": 6, "density": 1,
                           "seed": 4})
        self.assertLess(len(a), len(full))
        self.assertGreater(len(a), len(full) // 2)
        (x1, x2), _, _ = ext(full)
        self.assertLessEqual(x2 - x1, 13)

    def test_offsets_and_refusals(self):
        cells = self.cells({"kind": "box", "from": [0, 0, 0], "to": [1, 0, 0]}, base=[100, 64, -5])
        self.assertEqual(cells, {(100, 64, -5), (101, 64, -5)})
        for bad in ({"kind": "torus"}, {"kind": "box", "from": [0, 0], "to": [1, 1, 1]},
                    {"kind": "line", "from": [0, 0, 0], "to": [0, 9, 0], "radius": 500},
                    {"kind": "ellipsoid", "center": [0, 0, 0], "radii": [60, 60, 60]}):
            with self.assertRaises(shapes.ShapeError, msg=bad):
                self.cells(bad)
        with self.assertRaises(shapes.ShapeError):
            self.cells({"kind": "box", "from": [0, 0, 0], "to": [500, 0, 0]}, base=[0, 64, 0])


class TestARefusalShowsAValidShape(unittest.TestCase):
    def test_each_shape_error_carries_a_working_example(self):
        for bad in ({"kind": "torus"}, {"kind": "ellipsoid", "center": [0, 0, 0], "radii": [1]},
                    {"kind": "cylinder", "base": 3, "height": 4, "radius": 2},
                    {"kind": "box", "from": [0, 0], "to": [1, 1, 1]}):
            with self.assertRaises(shapes.ShapeError) as err:
                shapes.expand(bad)
            kind = bad["kind"] if bad["kind"] in shapes.KINDS else "box"
            self.assertIn("For example", str(err.exception), bad)
            example = shapes.EXAMPLES[kind]
            self.assertTrue(shapes.expand(example), kind)


class TestAGiantTree(EditingHandsBase):
    def tree(self, job="job-7"):
        return self.hands.edit(player=DAD, title="a giant oak", job=job, shapes=[
            {"kind": "line", "from": [6, 0, 6], "to": [6, 48, 6], "radius": 5, "radius_end": 2,
             "block": "oak_log[axis=y]"},
            {"kind": "blob", "center": [6, 52, 6], "radius": 15, "density": 0.85, "seed": 11,
             "block": "oak_leaves[persistent=true]"},
        ])

    def test_it_fits_one_edit_is_written_as_runs_and_is_undone_exactly(self):
        self.join(DAD)
        before = dict(self.world.blocks)
        act = self.tree()
        self.assertEqual(act["status"], "done")
        self.assertEqual(act["job"], "job-7")
        self.assertGreater(act["changed"], 10_000)
        self.assertLessEqual(act["changed"], companion.EDIT_MAX)
        writes = [c for c in self.world.commands if " minecraft:fill " in c
                  or " minecraft:setblock " in c]
        self.assertLess(len(writes), act["changed"] / 4)          # runs, not cells
        logs = [k for k, v in self.world.blocks.items() if v == "minecraft:oak_log[axis=y]"]
        self.assertEqual(min(k[2] for k in logs), 64)
        # The log keeps a large edit's cells beside it, and the undo reads them.
        stored = self.hands.actions.list(1)[0]
        self.assertEqual(stored["cells"], [])
        self.hands.undo(act["id"])
        self.assertEqual({k: v for k, v in self.world.blocks.items() if v != "minecraft:air"},
                         {k: v for k, v in before.items() if v != "minecraft:air"})

    def test_a_job_is_undone_whole_and_a_too_big_shape_is_refused(self):
        self.join(DAD)
        self.tree()
        self.hands.edit(player=DAD, job="job-7", shapes=[
            {"kind": "box", "from": [-3, 0, -3], "to": [-1, 2, -1], "block": "stone"}])
        self.hands.edit(player=DAD, job="other", blocks=[{"x": 20, "y": 0, "z": 0,
                                                          "block": "glass"}])
        out = self.hands.undo_job("job-7")
        self.assertEqual(len(out["undone"]), 2)
        self.assertEqual(self.world.blocks[(OW, 20, 64, 0)], "minecraft:glass")
        self.assertNotIn("minecraft:stone", self.world.blocks.values())
        with self.assertRaisesRegex(companion.CompanionError, "131072|split"):
            self.hands.edit(player=DAD, shapes=[{"kind": "box", "from": [0, 0, 0],
                                                 "to": [60, 60, 60], "block": "stone"}])
        with self.assertRaisesRegex(companion.CompanionError, "job"):
            self.hands.edit(player=DAD, job="no spaces!", blocks=[{"x": 1, "y": 0, "z": 1,
                                                                    "block": "glass"}])


if __name__ == "__main__":
    unittest.main()
