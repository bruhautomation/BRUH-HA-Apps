#!/usr/bin/env python3
"""A source file points at the slice already made from it.

The Files list keeps the add-on's own slices out (they are not what somebody
brought in), so a reprint of something already sliced needed another slice:
the source said `sliced: false` and nothing led to the ready-to-print file.
Each source row now carries `sliced_path`, the newest slice made from it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_files_and_import import STL, RouteTest, make_part  # noqa: E402
from test_bambu_panel import make_3mf  # noqa: E402


class TestSourceRowsLinkTheirSlice(RouteTest):
    def rows(self):
        _, body = self.call("GET", "/api/files")
        return {f["path"]: f for f in body["files"]}

    def test_an_upload_points_at_its_newest_slice(self):
        (self.lib / "bracket.stl").write_bytes(STL)
        make_3mf(self.lib / "sliced" / "bracket-20260101-010101.gcode.3mf")
        make_3mf(self.lib / "sliced" / "bracket-20260102-010101.gcode.3mf")
        os.utime(self.lib / "sliced" / "bracket-20260102-010101.gcode.3mf", (2e9, 2e9))
        rows = self.rows()
        self.assertEqual(rows["bracket.stl"]["sliced_path"],
                         "sliced/bracket-20260102-010101.gcode.3mf")

    def test_a_design_points_at_the_slice_of_its_file(self):
        make_part("Bracket")
        make_3mf(self.lib / "sliced" / "bracket.gcode.3mf")
        design = [f for f in self.rows().values() if f.get("design")][0]
        self.assertEqual(design["sliced_path"], "sliced/bracket.gcode.3mf")

    def test_a_source_nothing_was_sliced_from_has_none(self):
        (self.lib / "other.stl").write_bytes(STL)
        make_3mf(self.lib / "sliced" / "bracket.gcode.3mf")
        self.assertIsNone(self.rows()["other.stl"].get("sliced_path"))

    def test_a_longer_name_with_the_same_start_is_not_its_slice(self):
        (self.lib / "bracket.stl").write_bytes(STL)
        make_3mf(self.lib / "sliced" / "bracket_large-20260101-010101.gcode.3mf")
        self.assertIsNone(self.rows()["bracket.stl"].get("sliced_path"))
