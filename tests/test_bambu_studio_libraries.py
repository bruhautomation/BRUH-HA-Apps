"""Bambu Studio is not started when the image lacks a library it links.

0.1.1 shipped WebKitGTK 4.0 only, and Bambu Studio 2.x links 4.1, so the
slicer died on its first line with a loader error, was restarted, and died
again. The image now carries 4.1; this holds the other half: a gap the
image has not caught up with is named on the panel instead of restarted.
"""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests import bambu_env

ROOT = os.path.join(os.path.dirname(__file__), "..", "bruh-bambu-studio")

LDD_OUTPUT = """\
\tlinux-vdso.so.1 (0x00007ffd)
\tlibwebkit2gtk-4.1.so.0 => not found
\tlibgtk-3.so.0 => /lib/x86_64-linux-gnu/libgtk-3.so.0 (0x00007f)
\tlibjavascriptcoregtk-4.1.so.0 => not found
"""


class _Install:
    """A squashfs-root shaped like the extracted AppImage, and a fake ldd."""

    def __init__(self, ldd_output: str):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "squashfs-root"
        (root / "bin").mkdir(parents=True)
        self.apprun = root / "AppRun"
        self.apprun.write_text("#!/bin/sh\n")
        (root / "bin" / "bambu-studio").write_text("ELF")
        (root / "bin" / "libbambu_networking.so").write_text("ELF")
        (root / "bin" / "README").write_text("not a library")
        tools = Path(self.tmp.name) / "tools"
        tools.mkdir()
        self.calls = Path(self.tmp.name) / "calls"
        ldd = tools / "ldd"
        ldd.write_text(f"#!/bin/sh\necho \"$1\" >> {self.calls}\ncat <<'OUT'\n{ldd_output}OUT\n")
        ldd.chmod(ldd.stat().st_mode | stat.S_IEXEC)
        self.path = f"{tools}:{os.environ.get('PATH', '')}"

    def close(self):
        self.tmp.cleanup()


class TestMissingLibraries(unittest.TestCase):
    def setUp(self):
        (self.installer,) = bambu_env.load("installer")
        self.installer._MISSING_CACHE.clear()

    def test_every_not_found_is_named_once(self):
        fake = _Install(LDD_OUTPUT)
        self.addCleanup(fake.close)
        with unittest.mock.patch.dict(os.environ, {"PATH": fake.path}):
            missing = self.installer.missing_libraries(fake.apprun)
        self.assertEqual(missing, ["libjavascriptcoregtk-4.1.so.0", "libwebkit2gtk-4.1.so.0"])
        asked = fake.calls.read_text().split()
        self.assertEqual(sorted(Path(a).name for a in asked),
                         ["bambu-studio", "libbambu_networking.so"])

    def test_a_complete_image_reports_nothing(self):
        fake = _Install("\tlibgtk-3.so.0 => /lib/libgtk-3.so.0 (0x1)\n")
        self.addCleanup(fake.close)
        with unittest.mock.patch.dict(os.environ, {"PATH": fake.path}):
            self.assertEqual(self.installer.missing_libraries(fake.apprun), [])

    def test_no_ldd_is_could_not_look_not_all_clear(self):
        fake = _Install(LDD_OUTPUT)
        self.addCleanup(fake.close)
        with unittest.mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertIsNone(self.installer.missing_libraries(fake.apprun))


class TestStudioIsNotStartedWithoutItsLibraries(unittest.TestCase):
    def setUp(self):
        self.installer, self.studio = bambu_env.load("installer", "studio")

    def _studio(self, missing):
        studio = self.studio.Studio()
        patches = [
            unittest.mock.patch.object(self.studio.installer, "apprun",
                                       return_value=Path("/x/squashfs-root/AppRun")),
            unittest.mock.patch.object(self.studio.installer, "missing_libraries",
                                       return_value=missing),
            unittest.mock.patch.object(self.studio.installer, "installed",
                                       return_value={"version": "v02.08.02.61"}),
            unittest.mock.patch.object(self.studio.subprocess, "Popen"),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        return studio, mocks[3]

    def test_missing_libraries_are_reported_and_nothing_is_spawned(self):
        studio, popen = self._studio(["libwebkit2gtk-4.1.so.0"])
        studio.restart()
        studio.tick()
        popen.assert_not_called()
        self.assertEqual(studio.state()["missing_libraries"], ["libwebkit2gtk-4.1.so.0"])

    def test_could_not_look_still_starts(self):
        studio, popen = self._studio(None)
        studio.restart()
        popen.assert_called_once()
        self.assertEqual(studio.state()["missing_libraries"], [])


class TestTheImageCarriesWhatStudioLinks(unittest.TestCase):
    def test_both_webkitgtk_apis_are_installed(self):
        with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("libwebkit2gtk-4.1-0", text)   # Bambu Studio 2.x
        self.assertIn("libwebkit2gtk-4.0-37", text)  # an older pinned release

    def test_the_panel_says_which_libraries(self):
        with open(os.path.join(ROOT, "panel", "app.js"), encoding="utf-8") as f:
            self.assertIn("missing_libraries", f.read())


if __name__ == "__main__":
    unittest.main()
