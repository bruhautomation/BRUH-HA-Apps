#!/usr/bin/env python3
"""Copies of a print: arranged the way Bambu Studio's command line takes them.

Reports #367 and #328: a designed part printed with copies: 2 failed to slice,
"Invalid params: can not set repetitions when slice all" (exit 254). The panel
already asked for plate 1 with `--repetitions`, and the CLI threw that away:
src/BambuStudio.cpp resets the plate to 0 ("not support to slice plate %2%,
reset to 0") for any input that is not a 3MF Bambu Studio itself wrote — its
importer (bbs_3mf.cpp) knows one by the model's `Application` metadata
starting "BambuStudio-" — and then refuses `--repetitions` with plate 0.

So `--repetitions` is only for Bambu Studio's own projects. Another 3MF (a
designed part is one, written by cad/mf3.py) is handed over as a copy whose
build lists each item once per copy, which the importer reads as instances
(_handle_start_item), and an STL or OBJ is handed over once per copy;
`--arrange 1` lays them out either way. The stand-in CLI here refuses the way
the real one does.
"""
import os
import re
import sys
import time
import unittest
import unittest.mock as mock
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_design_slice_params import (  # noqa: E402
    REAL_PRINT_JOB, A1PrintTest, installer, parts, server, slicer)

# The real CLI's rule, in shell: the plate given survives only for a 3MF whose
# model names Bambu Studio as its application, and --repetitions needs a plate.
REFUSING_CLI = r"""#!/bin/sh
for a in "$@"; do printf "%s\n" "$a"; done > "$RECORD"
plate=0; reps=0; last=""; prev=""
for a in "$@"; do
  [ "$prev" = "--slice" ] && plate="$a"
  [ "$prev" = "--repetitions" ] && reps="$a"
  prev="$a"; last="$a"
done
cp "$last" "$RECORD.input" 2>/dev/null
case "$last" in
  *.3mf) unzip -p "$last" 3D/3dmodel.model 2>/dev/null | grep -q 'name="Application">BambuStudio-' || plate=0 ;;
  *) plate=0 ;;
esac
if [ "$reps" -gt 1 ] && [ "$plate" = 0 ]; then
  echo "[error] Invalid params: can not set repetitions when slice all."
  echo "run found error, return -2, exit..."
  exit 254
fi
echo "[error] stand-in: stopping here"
exit 1
"""


def items_in(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        model = archive.read("3D/3dmodel.model").decode()
    build = re.search(r"<build\b[^>]*>(.*?)</build>", model, re.S).group(1)
    return re.findall(r"<item\b[^>]*/>", build)


class CopiesTest(A1PrintTest):
    def setUp(self):
        super().setUp()
        run = mock.patch.object(server, "_print_job", REAL_PRINT_JOB)
        run.start()
        self.addCleanup(run.stop)
        self.record = self.root / "argv.txt"
        self.app = self.root / "AppRun"
        self.app.write_text(REFUSING_CLI)
        self.app.chmod(0o755)
        env = mock.patch.dict(os.environ, {"RECORD": str(self.record)})
        env.start()
        self.addCleanup(env.stop)

    def slice(self, source: Path, copies: int, **kwargs) -> tuple[dict, list[str]]:
        with mock.patch.object(installer, "apprun", return_value=self.app), \
                mock.patch.object(slicer, "MAKE_ROOM", None), \
                mock.patch.object(slicer, "SLICE_HOME", self.root / "slicer-home"):
            job = slicer.start_paths(source, copies=copies, env=dict(os.environ), **kwargs)
            done = slicer.wait(job["id"], 20)
        return done, self.record.read_text().splitlines()

    def opts(self, argv):
        return {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}


class TestADesignedPartInCopies(CopiesTest):
    def test_a_designed_part_with_two_copies_is_two_instances_and_no_repetitions(self):
        part = self.part()
        with mock.patch.object(installer, "apprun", return_value=self.app), \
                mock.patch.object(slicer, "MAKE_ROOM", None), \
                mock.patch.object(slicer, "SLICE_HOME", self.root / "slicer-home"):
            job, _prepared, sentence = server.start_design_print(
                self.panel, part["id"], printer="A1", slots={"Cube": 1, "Logo": 0},
                settings={"copies": 2})
            deadline = time.time() + 20
            while job["state"] == "running" and time.time() < deadline:
                time.sleep(0.05)
        self.assertIn("2 copies", sentence)
        argv = self.record.read_text().splitlines()
        self.assertNotIn("can not set repetitions", job.get("error", ""))
        self.assertNotIn("--repetitions", argv)
        opts = self.opts(argv)
        self.assertEqual(opts["--slice"], "0")
        self.assertEqual(opts["--arrange"], "1")
        handed = Path(str(self.record) + ".input")
        self.assertEqual(len(items_in(handed)), 2)
        # The copy keeps the part's own filament numbers.
        with zipfile.ZipFile(handed) as archive:
            self.assertIn("Metadata/model_settings.config", archive.namelist())

    def test_one_copy_is_handed_over_as_it_is(self):
        part = self.part()
        source = parts.version_dir(part["id"], 1) / "cube_logo.3mf"
        _done, argv = self.slice(source, 1)
        self.assertNotIn("--repetitions", argv)
        self.assertEqual(argv[-1], str(source))
        self.assertEqual(len(items_in(Path(str(self.record) + ".input"))), 1)


class TestEveryKindOfFileInCopies(CopiesTest):
    def test_a_bambu_studio_project_repeats_one_plate(self):
        source = self.root / "share" / "project.3mf"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("3D/3dmodel.model",
                             '<model><metadata name="Application">BambuStudio-02.08.02.61'
                             '</metadata><resources/><build><item objectid="1"/></build></model>')
        done, argv = self.slice(source, 3)
        opts = self.opts(argv)
        self.assertEqual((opts["--slice"], opts["--repetitions"]), ("1", "3"))
        self.assertNotIn("can not set repetitions", done["error"])

    def test_a_3mf_from_somewhere_else_is_handed_over_with_its_items_repeated(self):
        source = self.root / "share" / "printables.3mf"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("3D/3dmodel.model",
                             '<model><metadata name="Application">PrusaSlicer-2.7</metadata>'
                             '<resources/><build><item objectid="1" transform="1 0 0 0 1 0 '
                             '0 0 1 10 10 0"/><item objectid="2"/></build></model>')
        done, argv = self.slice(source, 2)
        self.assertNotIn("--repetitions", argv)
        self.assertNotIn("can not set repetitions", done["error"])
        self.assertEqual(self.opts(argv)["--arrange"], "1")
        self.assertEqual(len(items_in(Path(str(self.record) + ".input"))), 4)
        self.assertTrue(source.is_file(), "the library's own file is left as it was")
        self.assertEqual(len(items_in(source)), 2)

    def test_a_bare_model_is_handed_over_once_per_copy(self):
        source = self.root / "share" / "bracket.stl"
        source.write_text("solid x\nendsolid x\n")
        machine = self.root / "m.json"
        process = self.root / "p.json"
        for p in (machine, process):
            p.write_text("{}")
        done, argv = self.slice(source, 3, machine=machine, process=process)
        self.assertNotIn("--repetitions", argv)
        self.assertNotIn("can not set repetitions", done["error"])
        self.assertEqual(argv[-3:], [str(source)] * 3)
        self.assertEqual(self.opts(argv)["--arrange"], "1")

    def test_the_command_alone_never_asks_for_repetitions_beside_every_plate(self):
        for way in ("instances", "files"):
            argv = slicer.command("/AppRun", Path("/x/part.3mf"), Path("/o/p.gcode.3mf"),
                                  copies=2, copies_as=way)
            self.assertNotIn("--repetitions", argv, way)
            self.assertEqual(argv[argv.index("--slice") + 1], "0", way)


if __name__ == "__main__":
    unittest.main()
