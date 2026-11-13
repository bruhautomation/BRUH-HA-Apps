"""The Walkthrough's per-app switches are what decides where Claude runs
are spent, and a Screens pass that could not look must say so.

Two of the development loop's own gates: an app the owner did not switch
on is never looked at on a schedule (autopilot included), and a stream
that failed to look leaves a row the Faults stream files rather than a
silence that reads as a clean result.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import devloop  # noqa: E402
from devloop import upstream  # noqa: E402

APPS = [{"key": "brain", "installed": True, "version": "9.9.9"},
        {"key": "morph", "installed": True, "version": "9.9.9"},
        {"key": "bright", "installed": True, "version": "1.2.0"},
        {"key": "gardenrx", "installed": False, "version": ""}]


class DevloopCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = devloop.DATA_DIR
        devloop.DATA_DIR = Path(tmp.name)
        self.addCleanup(setattr, devloop, "DATA_DIR", old)


class TestWalkSwitches(DevloopCase):
    def test_autopilot_does_not_switch_the_other_apps_on(self):
        settings = devloop.save_settings({"enabled": True, "autopilot": True})
        self.assertTrue(all(settings["streams"].values()))
        self.assertEqual([k for k, on in settings["walks"].items() if on],
                         ["brain", "morph"])
        self.assertEqual(upstream.walks_due(APPS, settings["walks"]),
                         ["brain", "morph"])

    def test_only_switched_on_installed_apps_with_a_new_version_are_owed(self):
        walks = devloop.save_settings(
            {"walks": {"bright": True, "gardenrx": True}})["walks"]
        self.assertEqual(upstream.walks_due(APPS, walks), ["brain", "morph", "bright"])
        upstream.note_walk("brain", "9.9.9", 2, now=100.0)
        upstream.note_walk("morph", "9.9.8", 0, now=50.0)
        # brAIn's version was looked at; Morph's was not; BRight never was,
        # so it goes first. The stream's own Run looks at all three again.
        self.assertEqual(upstream.walks_due(APPS, walks), ["bright", "morph"])
        self.assertEqual(upstream.walks_due(APPS, walks, None, True),
                         ["bright", "morph", "brain"])

    def test_a_failed_look_is_still_owed_and_goes_to_the_back(self):
        walks = devloop.load_settings()["walks"]
        upstream.note_walk("brain", "9.9.9", 0, "the run failed", now=200.0)
        self.assertEqual(upstream.walks_due(APPS, walks), ["morph", "brain"])

    def test_an_unknown_app_is_refused(self):
        with self.assertRaises(ValueError):
            devloop.save_settings({"walks": {"somebody-elses-addon": True}})


class TestAScreensPassThatCouldNotLook(DevloopCase):
    def test_it_is_a_fault_row_until_a_capture_succeeds(self):
        devloop.save_settings({"enabled": True, "streams": {"screens": True}})
        upstream.note_blind("screens", "capture", "Timeout 900s")
        upstream.note_blind("screens", "capture", "Timeout 900s")
        rows = upstream.blind_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["where"], "Screens")
        self.assertIn("2 tries", rows[0]["detail"])
        self.assertIn("screens", upstream.blind_notes())
        # One fingerprint per reason class, whatever the error said.
        first = upstream.fingerprint(rows[0]["where"], rows[0]["what"])
        upstream.note_blind("screens", "capture", "Connection reset")
        again = upstream.blind_rows()[0]
        self.assertEqual(upstream.fingerprint(again["where"], again["what"]), first)
        upstream.note_photographed("9.9.9")
        self.assertEqual(upstream.blind_rows(), [])
        self.assertEqual(upstream.blind_notes(), {})

    def test_a_release_not_photographed_is_owed_after_the_gap_not_the_week(self):
        devloop.save_settings({"enabled": True, "streams": {"screens": True}})
        now = 1_800_000_000.0
        upstream.ingest("faults", [], {"versions": {"addon": "9.9.9"}}, now=now)
        gap = upstream.SCREENS_RELEASE_GAP_H * 3600
        upstream.mark_run("screens", now - gap + 60)
        self.assertNotIn("screens", upstream.due_streams(now))
        upstream.mark_run("screens", now - gap - 60)
        self.assertIn("screens", upstream.due_streams(now))
        upstream.note_photographed("9.9.9", now)
        self.assertNotIn("screens", upstream.due_streams(now))


if __name__ == "__main__":
    unittest.main()
