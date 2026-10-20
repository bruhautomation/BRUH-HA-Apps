#!/usr/bin/env python3
"""Settings Bambu Studio would refuse, and a part it opens as a project.

The slicer's validate() (PrintConfig.cpp) refuses a config whose settings
disagree — 100 % infill in a pattern that cannot be solid, a spiral vase
with walls, infill, a top or supports — and the CLI ends on exit -18. The
part's settings over the profile's defaults can each be valid and still
disagree, so the final process is reconciled before it is written.

And the GUI opens a 3MF whose project config names no Bambu Lab printer as
geometry only, under "The 3mf file has invalid config" (Plater.cpp,
is_bbl_vendor_config), so "Open in Bambu Studio" writes a copy carrying one.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from bambu_env import load  # noqa: E402

options, profiles, painting, slicer, installer, server, store = load(
    "design.options", "design.profiles", "design.painting", "slicer", "installer", "server", "store")


def write_profiles(root: Path) -> Path:
    base = root / "resources" / "profiles" / "BBL"
    for kind in ("machine", "process", "filament"):
        (base / kind).mkdir(parents=True)

    def put(kind, name, **data):
        (base / kind / f"{name}.json").write_text(json.dumps({"name": name, "type": kind, **data}))

    put("machine", "fdm_machine_common", instantiation="false", printer_model="",
        nozzle_diameter=["0.4"])
    put("machine", "Bambu Lab A1 0.4 nozzle", inherits="fdm_machine_common",
        instantiation="true", printer_model="Bambu Lab A1", setting_id="GM001")
    # The profile's own default pattern is grid: 100 % over it is the -18.
    put("process", "fdm_process_common", instantiation="false", layer_height="0.2",
        wall_loops="2", sparse_infill_density="15%", sparse_infill_pattern="grid",
        top_shell_layers="5")
    put("process", "0.20mm Standard @BBL A1", inherits="fdm_process_common",
        instantiation="true", compatible_printers=["Bambu Lab A1 0.4 nozzle"])
    put("filament", "Bambu PLA Basic @BBL A1", instantiation="true", filament_type=["PLA"],
        filament_colour=["#FFFFFF"], nozzle_temperature=["220"], filament_id="GFA00",
        compatible_printers=["Bambu Lab A1 0.4 nozzle"])
    return root / "resources"


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        res = write_profiles(self.root)
        profiles._index.cache_clear()
        self.addCleanup(profiles._index.cache_clear)
        for patch in (mock.patch.object(installer, "resources", return_value=res),
                      mock.patch.object(installer, "installed",
                                        return_value={"version": "v02.03.01.51"})):
            patch.start()
            self.addCleanup(patch.stop)


class TestTheSlicerNeverMeetsADisagreement(unittest.TestCase):
    def test_full_infill_in_a_pattern_that_cannot_be_solid_becomes_rectilinear(self):
        out, notes = options.reconcile({"sparse_infill_density": "100%",
                                        "sparse_infill_pattern": "grid"})
        self.assertEqual(out["sparse_infill_pattern"], "zig-zag")
        self.assertEqual(len(notes), 1)
        self.assertIn("100", notes[0])

    def test_every_pattern_bambu_studio_allows_at_full_infill_is_kept(self):
        for pattern in ("zig-zag", "concentric", "alignedrectilinear", "monotonic"):
            with self.subTest(pattern=pattern):
                out, notes = options.reconcile({"sparse_infill_density": "100%",
                                                "sparse_infill_pattern": pattern})
                self.assertEqual((out["sparse_infill_pattern"], notes), (pattern, []))

    def test_a_partial_infill_keeps_its_pattern(self):
        out, notes = options.reconcile({"sparse_infill_density": "15%",
                                        "sparse_infill_pattern": "gyroid"})
        self.assertEqual((out["sparse_infill_pattern"], notes), ("gyroid", []))

    def test_a_spiral_vase_has_nothing_a_vase_cannot_have(self):
        out, notes = options.reconcile({"spiral_mode": "1", "wall_loops": "3",
                                        "sparse_infill_density": "15%", "top_shell_layers": "4",
                                        "enable_support": "1"})
        self.assertEqual((out["wall_loops"], out["sparse_infill_density"], out["top_shell_layers"],
                          out["enable_support"], out["enforce_support_layers"]),
                         ("1", "0%", "0", "0", "0"))
        self.assertEqual(len(notes), 1)

    def test_brains_own_choice_is_corrected_where_it_is_cleaned(self):
        got = options.clean_slice({"infill_percent": 100, "infill_pattern": "gyroid"})
        self.assertEqual(got["infill_pattern"], "rectilinear")
        self.assertEqual(options.process_values(got)["sparse_infill_pattern"], "zig-zag")

    def test_the_slicers_escaped_percent_is_shown_as_one(self):
        lines = ["[error] run found error", "Param values in 3mf/config error:",
                 "sparse_infill_pattern: grid doesn't work at 100%% density "]
        self.assertEqual(slicer.rejected(lines),
                         ["sparse_infill_pattern: grid doesn't work at 100% density"])


class TestThePreparedProcess(Isolated):
    def test_full_infill_over_the_profiles_grid_is_written_as_rectilinear(self):
        prepared = profiles.prepare("A1", {"material": "PLA", "infill_percent": 100},
                                    self.root / "slicing")
        process = json.loads(Path(prepared["paths"]["process"]).read_text())
        self.assertEqual(process["sparse_infill_density"], "100%")
        self.assertEqual(process["sparse_infill_pattern"], "zig-zag")
        self.assertEqual(len(prepared["adjusted"]), 1)

    def test_nothing_is_said_when_nothing_had_to_change(self):
        prepared = profiles.prepare("A1", {"material": "PLA", "infill_percent": 20},
                                    self.root / "slicing")
        self.assertEqual(prepared["adjusted"], [])


class TestAPartOpensInBambuStudioAsAProject(Isolated):
    def part_3mf(self) -> Path:
        path = self.root / "v1" / "bracket.3mf"
        path.parent.mkdir()
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("3D/3dmodel.model", "<model/>")
            z.writestr("Metadata/model_settings.config",
                       '<config><object id="3"><part id="1"><metadata key="name" value="Body"/>'
                       '<metadata key="extruder" value="1"/></part><part id="2">'
                       '<metadata key="name" value="Logo"/><metadata key="extruder" value="2"/>'
                       '</part></object></config>')
        return path

    def test_the_project_names_a_bambu_lab_printer_and_one_filament_per_colour(self):
        project = profiles.project_settings(
            "A1", {"material": "PLA", "infill_percent": 100},
            [{"material": "PLA", "colour": "#FFFFFF"}, {"material": "PLA", "colour": "#18C241"}])
        self.assertEqual(project["printer_model"], "Bambu Lab A1")
        self.assertEqual(project["printer_settings_id"], "Bambu Lab A1 0.4 nozzle")
        self.assertEqual(project["print_settings_id"], "0.20mm Standard @BBL A1")
        self.assertEqual(project["filament_settings_id"], ["Bambu PLA Basic @BBL A1"] * 2)
        self.assertEqual(project["filament_colour"], ["#FFFFFF", "#18C241"])
        self.assertEqual(project["filament_type"], ["PLA", "PLA"])
        self.assertEqual(project["sparse_infill_pattern"], "zig-zag")
        self.assertEqual((project["name"], project["from"], project["version"]),
                         ("project_settings", "project", "02.03.01.51"))
        for meta in ("inherits", "instantiation", "compatible_printers", "setting_id", "type",
                     "filament_id"):
            self.assertNotIn(meta, project)
        # Bambu Studio's JSON loader wants every list to hold one type.
        for key, value in project.items():
            if isinstance(value, list):
                self.assertTrue(all(isinstance(v, str) for v in value), key)

    def test_the_copy_carries_the_project_and_everything_the_part_had(self):
        source = self.part_3mf()
        part = {"print_settings": {"material": "PLA"}}
        row_v = {"colors": {"Body": "#ffffff", "Logo": "#18C241"}}
        printers = [{"id": "p1", "name": "Bambu A1", "model": "A1"}]
        with mock.patch.object(server.store, "load", return_value=printers):
            opened, note = server._studio_copy(None, part, row_v, source)
        self.assertEqual(opened.name, "bracket.studio.3mf")
        self.assertIn("Bambu A1", note)
        with zipfile.ZipFile(opened) as z:
            names = set(z.namelist())
            project = json.loads(z.read("Metadata/project_settings.config"))
        self.assertLessEqual({"3D/3dmodel.model", "Metadata/model_settings.config"}, names)
        self.assertEqual(project["filament_colour"], ["#FFFFFF", "#18C241"])
        self.assertTrue(source.is_file())  # the version itself is left alone

    def test_with_no_printer_model_the_file_opens_as_it_is_and_says_why(self):
        source = self.part_3mf()
        with mock.patch.object(server.store, "load", return_value=[{"id": "p1", "name": "X"}]):
            opened, note = server._studio_copy(None, {}, {}, source)
        self.assertEqual(opened, source)
        self.assertIn("model", note)


if __name__ == "__main__":
    unittest.main()
