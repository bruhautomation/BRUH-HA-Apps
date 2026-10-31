#!/usr/bin/env python3
"""memory_mb against the host's memory (#585): a 6 GB heap on a 16 GB host left
about 320 MB free and the kernel killed Java. The check only warns - it never
changes the stored option - and the panel shows the warning."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "bruh-minecraft-server" / "scripts" / "memory-check.py"


def _mod():
    spec = importlib.util.spec_from_file_location("memory_check", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


MEMINFO = "MemTotal:       {t} kB\nMemFree:  1 kB\nMemAvailable:   {a} kB\n"


class TestAssess(unittest.TestCase):
    def test_small_heap_on_a_big_host_is_fine(self):
        self.assertIsNone(_mod().assess(4096, 16384, 9000))

    def test_exactly_two_gb_left_is_fine(self):
        self.assertIsNone(_mod().assess(14336, 16384, 15000))

    def test_six_gb_on_a_small_host_warns_with_a_suggestion(self):
        w = _mod().assess(6144, 6500, 4000)
        self.assertEqual(w["suggested_mb"], 4352)
        self.assertEqual(w["leaves_mb"], 356)
        self.assertIn("356 MB", w["message"])
        self.assertIn("4352", w["message"])

    def test_little_free_right_now_warns_even_with_room_in_total(self):
        w = _mod().assess(4096, 16384, 3000)
        self.assertIsNotNone(w)
        self.assertIn("free right now", w["message"])

    def test_unreadable_meminfo_says_nothing(self):
        self.assertIsNone(_mod().assess(6144, 0, 0))

    def test_suggestion_never_drops_below_a_gig(self):
        self.assertEqual(_mod().assess(2048, 2048, 500)["suggested_mb"], 1024)

    def test_reads_meminfo(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "meminfo"
            p.write_text(MEMINFO.format(t=16384 * 1024, a=2048 * 1024))
            self.assertEqual(_mod().read_meminfo(str(p)), (16384, 2048))
            self.assertEqual(_mod().read_meminfo(str(Path(tmp) / "none")), (0, 0))


class TestCli(unittest.TestCase):
    def _run(self, tmp: str, memory_mb: int, total_mb: int, avail_mb: int):
        info = Path(tmp) / "meminfo"
        info.write_text(MEMINFO.format(t=total_mb * 1024, a=avail_mb * 1024))
        env = {"MEMORY_MB": str(memory_mb), "MEMINFO_PATH": str(info),
               "MC_PANEL_STATE": tmp, "PATH": "/usr/bin:/bin"}
        return subprocess.run([sys.executable, str(SCRIPT)], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_warning_is_printed_and_written_for_the_panel(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(tmp, 6144, 6500, 4000)
            self.assertEqual(proc.returncode, 0)
            self.assertIn("memory_mb is 6144", proc.stdout)
            data = json.loads((Path(tmp) / "memory-warning.json").read_text())
            self.assertEqual(data["suggested_mb"], 4352)

    def test_no_warning_removes_an_old_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "memory-warning.json").write_text("{}")
            proc = self._run(tmp, 2048, 16384, 9000)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout.strip(), "")
            self.assertFalse((Path(tmp) / "memory-warning.json").exists())


class TestWiring(unittest.TestCase):
    def test_run_sh_runs_it_and_the_panel_reports_it(self):
        self.assertIn("memory-check.py", (BASE_DIR / "bruh-minecraft-server" / "run.sh").read_text())
        panel = (BASE_DIR / "bruh-minecraft-server" / "panel" / "server.py").read_text()
        self.assertIn("memory-warning.json", panel)
        self.assertIn("memory_warning", panel)


if __name__ == "__main__":
    unittest.main()
