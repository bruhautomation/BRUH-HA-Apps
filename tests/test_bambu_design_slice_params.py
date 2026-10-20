#!/usr/bin/env python3
"""A designed part slices on an A1: the settings it is handed, and the words when it does not.

A house running Bambu Studio 02.08.02.61 on an A1 with an AMS lite saw every
print of a designed part end "Bambu Studio could not slice it (exit 254):
run found error, return -2, exit...". 254 is the CLI's -2,
CLI_INVALID_PARAMS (src/libslic3r/Utils.hpp), and that last line is only the
CLI signing off (the flush_and_exit macro in src/BambuStudio.cpp); the reason
is the "[error]" line it logged before it.

These drive the real path — profiles.prepare, painting.retarget, the real
_print_job and slicer.command — for a two-body part on an A1 printing from
two AMS trays, with a stand-in for Bambu Studio that records what it was
handed and answers the way the CLI does.
"""
import json
import os
import sys
import time
import unittest
import unittest.mock as mock
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402,F401
from test_bambu_design_printing import (  # noqa: E402
    FakeClient, PrintTest, installer, parts, profiles, server, store)

slicer = server.slicer

REAL_PRINT_JOB = server._print_job
A1 = "Bambu Lab A1 0.4 nozzle"
START = ";===== machine: A1 =====\nG392 S0\n"
TRAYS = [{"slot": 0, "type": "PLA", "colour": "#FFFFFF", "remaining": 80},
         {"slot": 1, "type": "PLA", "colour": "#101010", "remaining": 40}]


def write_a1_profiles(root: Path) -> Path:
    """Bambu Studio 2.8's own shape: the A1's G-code lives in template files
    its profile names under "include" (resources/profiles/BBL/machine)."""
    base = root / "resources" / "profiles" / "BBL"
    for kind in ("machine", "process", "filament"):
        (base / kind).mkdir(parents=True)

    def put(kind, name, **data):
        (base / kind / f"{name}.json").write_text(json.dumps({"name": name, **data}))

    put("machine", "fdm_machine_common", type="machine", **{"from": "system"},
        instantiation="false", printer_model="", machine_start_gcode="")
    put("machine", "fdm_bbl_3dp_001_common", type="machine", inherits="fdm_machine_common",
        instantiation="false", nozzle_diameter=["0.4"])
    put("machine", f"{A1} template machine_start_gcode", instantiation="false",
        machine_start_gcode=START)
    put("machine", f"{A1} template change_filament_gcode", instantiation="false",
        change_filament_gcode="M620 S[next_extruder]A\n")
    put("machine", A1, type="machine", inherits="fdm_bbl_3dp_001_common",
        instantiation="true", printer_model="Bambu Lab A1",
        include=[f"{A1} template machine_start_gcode", f"{A1} template change_filament_gcode"])
    put("process", "fdm_process_common", type="process", instantiation="false",
        layer_height="0.2", wall_loops="2", sparse_infill_density="15%")
    put("process", "0.20mm Standard @BBL A1", type="process", inherits="fdm_process_common",
        instantiation="true", compatible_printers=[A1])
    put("filament", "Bambu PLA Basic @BBL A1", type="filament", instantiation="true",
        filament_type=["PLA"], compatible_printers=[A1])
    return root / "resources"


def fake_cli(path: Path, record: Path, lines: list[str], code: int) -> Path:
    body = "\n".join(f"echo {json.dumps(line)}" for line in lines)
    path.write_text("#!/bin/sh\n"
                    f'for a in "$@"; do printf "%s\\n" "$a"; done > {json.dumps(str(record))}\n'
                    f"{body}\nexit {code}\n")
    path.chmod(0o755)
    return path


class A1PrintTest(PrintTest):
    def setUp(self):
        super().setUp()
        res = write_a1_profiles(self.root / "a1")
        profiles._index.cache_clear()
        p = mock.patch.object(installer, "resources", return_value=res)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(profiles._index.cache_clear)
        store.save({"name": "A1", "host": "10.0.0.3", "serial": "BBBB11112222",
                    "model": "A1"}, "abcd1234")
        self.client = FakeClient(TRAYS)
        self.panel.clients["bbbb11112222"] = self.client


class TestTheA1sProfilesCarryTheirOwnGcode(A1PrintTest):
    """The command line's own loader does not read "include" (Config.cpp keeps it
    as a key/value and PresetBundle.cpp is what applies it), so a flattened
    profile that left it out handed the CLI an A1 with no start G-code."""

    def test_the_included_templates_are_in_the_machine_file(self):
        prepared = profiles.prepare("A1", {"material": "PLA"}, self.root / "slicing",
                                    [{"material": "PLA", "colour": "#101010"},
                                     {"material": "PLA", "colour": "#FFFFFF"}])
        machine = json.loads(Path(prepared["paths"]["machine"]).read_text())
        self.assertEqual(machine["machine_start_gcode"], START)
        self.assertIn("M620", machine["change_filament_gcode"])
        self.assertNotIn("include", machine)
        self.assertEqual((machine["name"], machine["inherits"], machine["from"]),
                         (A1, A1, "User"))
        self.assertEqual(machine["type"], "machine")

    def test_the_project_settings_carry_them_too(self):
        project = profiles.project_settings("A1", {"material": "PLA"})
        self.assertEqual(project["machine_start_gcode"], START)
        self.assertNotIn("include", project)

    def test_a_template_that_is_not_there_is_said(self):
        base = installer.resources() / "profiles" / "BBL" / "machine"
        (base / f"{A1} template change_filament_gcode.json").unlink()
        profiles._index.cache_clear()
        with self.assertRaises(LookupError) as caught:
            profiles.flatten("machine", A1)
        self.assertIn("change_filament_gcode", str(caught.exception))


CLI_SAYS = [
    "[2026-10-20 08:12:01.402] [0x7f] [warning] cli mode, Current BambuStudio Version 02.08.02.61",
    "[2026-10-20 08:12:01.880] [0x7f] [error]   uptodate_filaments size 1 not equal to filament_count 2 ",
    "run found error, return -2, exit...",
]


class TestADesignedPartOnTheA1(A1PrintTest):
    def setUp(self):
        super().setUp()
        run = mock.patch.object(server, "_print_job", REAL_PRINT_JOB)
        run.start()
        self.addCleanup(run.stop)
        self.record = self.root / "argv.txt"

    def _slice(self, lines, code):
        app = fake_cli(self.root / "AppRun", self.record, lines, code)
        part = self.part()
        with mock.patch.object(installer, "apprun", return_value=app), \
                mock.patch.object(slicer, "MAKE_ROOM", None), \
                mock.patch.object(slicer, "SLICE_HOME", self.root / "slicer-home"):
            job, _prepared, _sentence = server.start_design_print(
                self.panel, part["id"], printer="A1", slots={"Cube": 1, "Logo": 0})
            deadline = time.time() + 20
            while job["state"] == "running" and time.time() < deadline:
                time.sleep(0.05)
            deadline = time.time() + 5
            while time.time() < deadline and not any(
                    "failed" in m["text"] for m in parts.load(part["id"])["messages"]):
                time.sleep(0.05)
        argv = self.record.read_text().splitlines()
        return job, argv, parts.load(part["id"])

    def test_what_bambu_studio_is_handed_meets_every_parameter_check(self):
        """Each CLI_INVALID_PARAMS a design print could meet in BambuStudio.cpp:
        a plate the file has (`--slice` 0 or 1, "invalid plate id"), no
        `--repetitions` with every plate ("can not set repetitions when slice
        all"), no load_filament_ids/clone_objects/assemble beside a 3MF, one
        input file, at most one machine and one process in --load-settings,
        and a filament for every number the parts name."""
        _job, argv, _part = self._slice(CLI_SAYS, 254)
        opts = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
        self.assertIn(opts["--slice"], ("0", "1"))
        if "--repetitions" in opts:
            self.assertEqual(opts["--slice"], "1")
        for refused in ("--load-filament-ids", "--load_filament_ids", "--clone-objects",
                        "--clone_objects", "--assemble", "--load-assemble-list",
                        "--uptodate-filaments", "--estimate-mode"):
            self.assertNotIn(refused, argv)
        settings = opts["--load-settings"].split(";")
        kinds = [json.loads(Path(p).read_text())["type"] for p in settings]
        self.assertEqual(kinds, ["machine", "process"])
        filaments = opts["--load-filaments"].split(";")
        self.assertEqual([json.loads(Path(p).read_text())["type"] for p in filaments],
                         ["filament", "filament"])
        source = Path(argv[-1])
        self.assertTrue(source.is_file())
        self.assertFalse(argv[-2].startswith("--") and argv[-2] not in opts)
        with zipfile.ZipFile(source) as archive:
            config = ET.fromstring(archive.read("Metadata/model_settings.config"))
            names = archive.namelist()
        used = {int(m.get("value")) for m in config.iter("metadata") if m.get("key") == "extruder"}
        self.assertTrue(used and max(used) <= len(filaments), (used, filaments))
        # A 3MF with no plates of its own is one plate to the CLI.
        self.assertFalse(any(n.startswith("Metadata/plate_") for n in names))
        machine = json.loads(Path(settings[0]).read_text())
        self.assertEqual(machine["machine_start_gcode"], START)

    def test_the_conversation_and_the_jobs_list_get_the_whole_reason(self):
        job, _argv, part = self._slice(CLI_SAYS, 254)
        self.assertEqual(job["state"], "failed")
        error = job["error"]
        self.assertIn("exit 254", error)
        self.assertIn(slicer.EXIT_REASONS[-2], error)
        self.assertIn("the filaments it was handed do not match the part's filaments", error)
        self.assertIn("uptodate_filaments size 1 not equal to filament_count 2", error)
        self.assertNotIn("run found error", error)
        slice_job = slicer.get(job["slice_job"])
        self.assertEqual(slice_job["error"], error)
        note = [m["text"] for m in part["messages"] if "failed" in m["text"]][-1]
        self.assertIn(error, note)
        # The jobs list shows a job's error as it is.
        listed = [j for j in self.panel.jobs_payload() if j["id"] == job["id"]] \
            if hasattr(self.panel, "jobs_payload") else [job]
        self.assertEqual(listed[0]["error"], error)

    def test_a_long_line_from_bambu_studio_is_not_cut(self):
        long_line = ("[t] [0x1] [error]   Invalid params:invalid plate 2 to slice, total 1 "
                     + "and " * 120 + "the end")
        job, _argv, _part = self._slice([long_line, "run found error, return -2, exit..."], 254)
        self.assertIn("the end", job["error"])
        self.assertIn("a plate the file does not have", job["error"])


class TestEveryExitCodeHasWords(unittest.TestCase):
    # The cli_errors table of src/BambuStudio.cpp v02.08.02.61, by its codes
    # in src/libslic3r/Utils.hpp.
    CODES = (-1, -2, -3, -4, -5, -6, -7, -8, -9, -10, -11, -12, -13, -14, -15, -16, -17,
             -18, -19, -20, -21, -22, -23, -24, -25, -50, -51, -52, -53, -54, -55, -56,
             -57, -58, -59, -60, -61, -62, -63, -64, -65, -66, -67, -68, -100, -101,
             -102, -103, -104, -105)

    def test_each_code_reads_as_a_sentence(self):
        for code in self.CODES:
            with self.subTest(code=code):
                words = slicer.exit_reason(256 + code)
                self.assertTrue(words, code)
                self.assertEqual(words, slicer.EXIT_REASONS[code])
                self.assertNotIn("_", words)

    def test_invalid_parameters_say_what_to_do(self):
        text = slicer.failure_message(254, ["run found error, return -2, exit..."])
        self.assertIn("settings it could not use together", text)
        self.assertIn("Open the part in Bambu Studio", text)
        self.assertNotIn("run found error", text)

    def test_the_error_lines_are_read_whole_and_in_order(self):
        lines = ["[a] [b] [info]   loading", "[a] [b] [error]   first: one",
                 "No such file: /x.json", "[a] [b] [error]   second 100%% done",
                 "run found error, return -3, exit..."]
        self.assertEqual(slicer.cli_error_lines(lines),
                         ["first: one", "No such file: /x.json", "second 100% done"])


if __name__ == "__main__":
    unittest.main()
