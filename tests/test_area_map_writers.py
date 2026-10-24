"""Two writers of the voice area map, one scratch name between them.

The worker pool's `refresh_area_map` wrote each of its three map files
through `path + ".tmp"`, and it is called from more than one thread. Two
calls at once both create the same scratch file, the first rename moves
it, and the second raises `FileNotFoundError` out of the refresh — which
is what a real house's log showed, twice in a day. The classic listener
had the same shape in shell. Each writer now holds a scratch name nobody
else can pick, and a refresh whose write fails says so and returns False
rather than raising. The usage tracker's own three writes of one file are
the same class and are driven here too.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_assist_exposure import load_pool  # noqa: E402
from test_classic_voice_listener import listener_body  # noqa: E402
from test_usage_tracker import load_tracker  # noqa: E402

RENDERED = "Weather: weather.home\nKitchen: light.kitchen, switch.kettle\n"


class _Answer:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.text.encode()


class TestThePoolsWritersDoNotShareAName(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.mod = load_pool(self.tmp, {})
        self.mod.SUPERVISOR_TOKEN = "test"
        self.mod.apply_exposure = lambda rendered, force=False: rendered
        self.mod.debug_log = lambda *a, **kw: None

    def _refresh(self):
        with patch.object(self.mod.urllib.request, "urlopen",
                          lambda *a, **kw: _Answer(RENDERED)):
            return self.mod.refresh_area_map()

    def test_a_second_writer_between_write_and_rename_loses_nothing(self):
        """The interleaving, made deterministic: the moment the first
        writer is about to rename its scratch file onto the exposed map, a
        second refresh runs to completion. With one shared scratch name the
        second moved the first one's file away and the first raised."""
        real_replace = os.replace
        fired = []

        def replace(src, dst):
            if (str(dst) == self.mod.AREA_MAP_EXPOSED_FILE and not fired):
                fired.append(True)
                self.assertTrue(self._refresh())
            return real_replace(src, dst)

        with patch("os.replace", replace):
            self.assertTrue(self._refresh())
        self.assertTrue(fired, "the interleaving never happened")
        with open(self.mod.AREA_MAP_EXPOSED_FILE) as fh:
            self.assertEqual(fh.read(), RENDERED)
        self.assertEqual(
            [n for n in os.listdir(self.mod.CACHE_DIR) if "tmp" in n], [])

    def test_many_threads_at_once(self):
        errors = []

        def run():
            try:
                for _ in range(20):
                    self._refresh()
            except Exception as exc:  # noqa: BLE001 — the failure under test
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(6)]
        with patch.object(self.mod.urllib.request, "urlopen",
                          lambda *a, **kw: _Answer(RENDERED)):
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])

    def test_a_write_that_fails_is_a_false_not_an_exception(self):
        os.makedirs(self.mod.AREA_MAP_EXPOSED_FILE)
        self.assertFalse(self._refresh())

    def test_the_maps_stay_readable_by_the_other_processes(self):
        self.assertTrue(self._refresh())
        mode = os.stat(self.mod.AREA_MAP_FILE).st_mode & 0o777
        self.assertEqual(mode & 0o044, 0o044, oct(mode))

    def test_the_heartbeat_and_profile_writes_share_no_name_either(self):
        """Every fixed-name writer in the file, not only the one reported."""
        src = Path(self.mod.__file__).read_text(encoding="utf-8")
        for name in ("AREA_MAP", "LAST_PROFILE_FILE", "API_ENDPOINT_FILE",
                     "POOL_STATUS_FILE"):
            self.assertNotIn(f'{name} + ".tmp"', src, name)
        self.assertNotIn('path + ".tmp"', src)


class TestTheClassicListenerToo(unittest.TestCase):

    def test_parallel_refreshes_leave_no_error_and_no_scratch(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / "work").mkdir()
        script = "\n".join([
            "bashio::log.info() { :; }", "bashio::log.warning() { :; }",
            "bashio::log.error() { :; }", "bashio::log.debug() { :; }",
            "bashio::config() { echo ''; }",
            listener_body(),
            "curl() { printf '%s' \"$TEST_RENDERED\"; }",
            "for i in $(seq 24); do refresh_area_map & done",
            "wait",
        ])
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "HOME": str(tmp), "TEST_SHARED": str(tmp / "shared"),
               "TEST_WORK": str(tmp / "work"), "TEST_CLAUDE_BIN": "true",
               "TEST_RENDERED": RENDERED, "SUPERVISOR_TOKEN": "test",
               "BRAIN_SCRIPTS_DIR": str(Path(__file__).resolve().parent.parent
                                        / "brain" / "scripts")}
        proc = subprocess.run(["bash", "-c", script], env=env,
                              capture_output=True, text=True, timeout=120)
        self.assertNotIn("No such file", proc.stderr)
        self.assertNotIn("cannot stat", proc.stderr)
        cache = tmp / "shared" / "cache"
        self.assertTrue((cache / "area_map_full.txt").is_file(), proc.stderr)
        self.assertEqual([n for n in os.listdir(cache) if "tmp" in n], [])


class TestTheTrackersWritesOfOneFile(unittest.TestCase):

    def test_two_writers_at_once_lose_nothing(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        mod = load_tracker({})
        mod.USAGE_FILE = os.path.join(tmp, "usage_limits.json")
        real_replace = os.replace
        fired = []

        def replace(src, dst):
            if str(dst) == mod.USAGE_FILE and not fired:
                fired.append(True)
                mod.write_error_status("network_error")
            return real_replace(src, dst)

        with patch("os.replace", replace):
            mod.write_usage({"five_hour": {"utilization": 3}})
        self.assertTrue(fired)
        with open(mod.USAGE_FILE) as fh:
            self.assertEqual(json.load(fh)["five_hour"]["utilization"], 3)
        self.assertEqual([n for n in os.listdir(tmp) if "tmp" in n], [])


if __name__ == "__main__":
    unittest.main()
