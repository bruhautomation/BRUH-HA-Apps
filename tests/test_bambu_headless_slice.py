"""The headless slice owns Bambu Studio while it runs.

A print from the panel slices with Bambu Studio's own command line, then
uploads over FTPS and starts over MQTT on the LAN. These hold the parts
that keep that run from fighting the window in the sidebar: its own home
(so the two never share a profile folder), the window closed while memory
is short and reopened afterwards, the GPU-free WebKit settings that stop
the window dying on /dev/dri, and a failure that names a signal.
"""

import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

(slicer, studio, installer) = bambu_env.load("slicer", "studio", "installer")


class TestTheSliceHasItsOwnHome(unittest.TestCase):
    def test_home_is_the_slicers_and_the_rest_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "slicer-home"
            with unittest.mock.patch.object(slicer, "SLICE_HOME", home):
                env = slicer.slice_env({"HOME": "/data/home", "DISPLAY": ":1"})
            self.assertEqual(env["HOME"], str(home))
            self.assertEqual(env["DISPLAY"], ":1")
            self.assertTrue(home.is_dir())

    def test_a_home_that_cannot_be_made_still_slices(self):
        with unittest.mock.patch.object(slicer, "SLICE_HOME", Path("/proc/nope/home")):
            env = slicer.slice_env({"HOME": "/data/home"})
        self.assertEqual(env["HOME"], "/data/home")


class TestASignalIsNamed(unittest.TestCase):
    def test_memory_is_named_for_a_kill(self):
        self.assertIn("memory", slicer.exit_reason(-9))
        self.assertIn("memory", slicer.exit_reason(137))

    def test_a_crash_is_a_crash(self):
        self.assertEqual(slicer.exit_reason(-11), "it crashed")
        self.assertEqual(slicer.exit_reason(139), "it crashed")


def _script(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return str(path)


class TestTheWindowMakesRoom(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = unittest.mock.patch.object(slicer, "SLICE_HOME", self.root / "home")
        p.start()
        self.addCleanup(p.stop)

    def run_slice(self, make_room, code=239):
        events = []

        def room(need):
            events.append(("room", need))
            out = make_room(need)
            if out is None:
                return None

            def resume():
                events.append(("resume",))
                out()
            return resume

        run = _script(self.root / "AppRun", f"echo sliced; exit {code}\n")
        job = {"log": [], "state": "running"}
        with unittest.mock.patch.object(slicer, "MAKE_ROOM", room):
            slicer._run(job, [run], self.root / "out.gcode.3mf", None)
        return job, events

    def test_the_window_comes_back_after_a_failed_slice(self):
        job, events = self.run_slice(lambda need: (lambda: None))
        self.assertEqual(events, [("room", slicer.SLICE_MEMORY_MB), ("resume",)])
        self.assertEqual(job["state"], "failed")
        self.assertIn("window was closed", job["log"][0])
        self.assertIn("sliced", job["log"])

    def test_no_room_needed_closes_nothing(self):
        job, events = self.run_slice(lambda need: None)
        self.assertEqual(events, [("room", slicer.SLICE_MEMORY_MB)])
        self.assertFalse(any("window was closed" in line for line in job["log"]))

    def test_asking_for_room_cannot_stop_a_slice(self):
        def broken(need):
            raise RuntimeError("no")
        job = {"log": [], "state": "running"}
        run = _script(self.root / "AppRun", "exit 1\n")
        with unittest.mock.patch.object(slicer, "MAKE_ROOM", broken):
            slicer._run(job, [run], self.root / "out.gcode.3mf", None)
        self.assertEqual(job["state"], "failed")
        self.assertIn("exit 1", job["error"])

    def test_the_slice_runs_in_its_own_home(self):
        out = self.root / "home.txt"
        run = _script(self.root / "AppRun", f'echo "$HOME" > {out}; exit 1\n')
        job = {"log": [], "state": "running"}
        with unittest.mock.patch.object(slicer, "MAKE_ROOM", None):
            slicer._run(job, [run], self.root / "out.gcode.3mf", {"HOME": "/data/home"})
        self.assertEqual(out.read_text().strip(), str(self.root / "home"))


class FakeProc:
    def __init__(self):
        self.ended = False

    def poll(self):
        return 0 if self.ended else None

    def terminate(self):
        self.ended = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.ended = True


class TestStudioMakeRoom(unittest.TestCase):
    def make(self):
        s = studio.Studio()
        s.proc = FakeProc()
        s.file = "/share/bambu/part.3mf"
        return s

    def test_enough_memory_keeps_the_window(self):
        s = self.make()
        with unittest.mock.patch.object(studio, "available_mb", return_value=4000):
            self.assertIsNone(s.make_room(1500))
        self.assertTrue(s.running())
        self.assertEqual(s.paused_for, "")

    def test_memory_unknown_keeps_the_window(self):
        s = self.make()
        with unittest.mock.patch.object(studio, "available_mb", return_value=None):
            self.assertIsNone(s.make_room(1500))
        self.assertTrue(s.running())

    def test_nothing_running_closes_nothing(self):
        s = studio.Studio()
        with unittest.mock.patch.object(studio, "available_mb", return_value=100):
            self.assertIsNone(s.make_room(1500))

    def test_short_of_memory_closes_and_reopens_the_same_file(self):
        s = self.make()
        with unittest.mock.patch.object(studio, "available_mb", return_value=600):
            resume = s.make_room(1500)
        self.assertIsNotNone(resume)
        self.assertFalse(s.running())
        self.assertFalse(s.wanted)
        self.assertIn("600 MB", s.state()["paused_for"])
        s.tick()  # the panel's timer must not reopen it mid-slice
        self.assertIsNone(s.proc)
        with unittest.mock.patch.object(s, "_spawn") as spawn:
            resume()
        spawn.assert_called_once()
        self.assertTrue(s.wanted)
        self.assertEqual(s.file, "/share/bambu/part.3mf")
        self.assertEqual(s.paused_for, "")


class TestTheWindowNeedsNoGPU(unittest.TestCase):
    def test_webkit_is_kept_off_the_gpu(self):
        env = studio.Studio().env()
        self.assertEqual(env["WEBKIT_DISABLE_DMABUF_RENDERER"], "1")
        self.assertEqual(env["LIBGL_ALWAYS_SOFTWARE"], "1")
        self.assertEqual(env["GALLIUM_DRIVER"], "llvmpipe")


if __name__ == "__main__":
    unittest.main()
