#!/usr/bin/env python3
"""The director self-check: six links, and the first broken one named.

Written because "it still fails" survived three fixes. Every layer
answered "fine" about the part it could see — and the one BRight checked,
`available()`, tests whether a FOLDER exists, which is the one fact that
stays true after the listener that made it has stopped.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import director_check  # noqa: E402
from director import claude_director  # noqa: E402


class DirectorCheckCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self._saved = (claude_director.BRAIN_SHARED,
                       claude_director.TASKS_DIR,
                       claude_director.RESULTS_DIR,
                       claude_director.POLL_S,
                       claude_director.CLAIM_GRACE_S,
                       director_check.PROBE_TIMEOUT_S)
        claude_director.BRAIN_SHARED = self.base / "brain"
        claude_director.TASKS_DIR = claude_director.BRAIN_SHARED / "tasks"
        claude_director.RESULTS_DIR = claude_director.BRAIN_SHARED / "results"
        claude_director.POLL_S = 0.02
        claude_director.CLAIM_GRACE_S = 0.3
        director_check.PROBE_TIMEOUT_S = 3

    def tearDown(self):
        (claude_director.BRAIN_SHARED, claude_director.TASKS_DIR,
         claude_director.RESULTS_DIR, claude_director.POLL_S,
         claude_director.CLAIM_GRACE_S,
         director_check.PROBE_TIMEOUT_S) = self._saved
        self.tmp.cleanup()

    def failed_step(self, result):
        return next(s for s in result["steps"] if not s["ok"])


class TestTheLinksAreWalkedInOrder(DirectorCheckCase):
    def test_no_brain_at_all_stops_at_the_first_link(self):
        result = director_check.check()
        self.assertFalse(result["ok"])
        self.assertEqual("brAIn", self.failed_step(result)["step"])
        self.assertEqual(1, len(result["steps"]),
                         "a broken first link must not be followed by five "
                         "more answers about things it makes irrelevant")

    def test_a_missing_task_folder_names_the_switch_to_turn_on(self):
        claude_director.BRAIN_SHARED.mkdir(parents=True)
        result = director_check.check()
        self.assertFalse(result["ok"])
        step = self.failed_step(result)
        self.assertEqual("task folder", step["step"])
        self.assertIn("Automation", step["detail"])

    def test_a_folder_brtight_cannot_write_to_is_caught_before_waiting(self):
        """Two add-ons, two users. A folder BRight cannot write to is one
        brAIn will never read a task from — and waiting two minutes to
        discover that is two minutes of nothing."""
        claude_director.TASKS_DIR.mkdir(parents=True)
        os.chmod(claude_director.TASKS_DIR, 0o500)
        try:
            if os.access(claude_director.TASKS_DIR, os.W_OK):
                self.skipTest("running as a user that ignores file modes")
            started = time.monotonic()
            result = director_check.check()
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual("writing", self.failed_step(result)["step"])
        finally:
            os.chmod(claude_director.TASKS_DIR, 0o700)

    def test_a_folder_nobody_reads_is_the_claim_link(self):
        """The failure this whole file exists for: brAIn installed, the
        folder there, BRight writing into it happily, and nothing on the
        other end."""
        claude_director.TASKS_DIR.mkdir(parents=True)
        result = director_check.check()
        self.assertFalse(result["ok"])
        step = self.failed_step(result)
        self.assertEqual("the claim", step["step"])
        self.assertIn("never picked this up", step["detail"])
        # And the links before it are reported as working, because they
        # are — that is what makes the broken one legible.
        self.assertEqual(["brAIn", "task folder", "writing"],
                         [s["step"] for s in result["steps"][:3]])

    def test_claimed_and_silent_is_a_different_link_than_unclaimed(self):
        claude_director.TASKS_DIR.mkdir(parents=True)

        def claim_only():
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                for task in claude_director.TASKS_DIR.glob("*.json"):
                    task.rename(task.with_suffix(".work.1"))
                    return
                time.sleep(0.01)

        claimer = threading.Thread(target=claim_only, daemon=True)
        claimer.start()
        result = director_check.check()
        claimer.join()
        steps = {s["step"]: s for s in result["steps"]}
        self.assertTrue(steps["the claim"]["ok"])
        self.assertFalse(steps["the answer"]["ok"])

    def test_a_working_chain_says_so_and_names_the_model(self):
        claude_director.TASKS_DIR.mkdir(parents=True)

        def answer():
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                for task in claude_director.TASKS_DIR.glob("*.json"):
                    body = json.loads(task.read_text())
                    task.unlink()
                    claude_director.RESULTS_DIR.mkdir(parents=True,
                                                      exist_ok=True)
                    (claude_director.RESULTS_DIR /
                     f"{body['id']}.json").write_text(json.dumps(
                         {"id": body["id"], "status": "completed",
                          "result": "READY"}))
                    return
                time.sleep(0.01)

        responder = threading.Thread(target=answer, daemon=True)
        responder.start()
        result = director_check.check()
        responder.join()
        self.assertTrue(result["ok"], result)
        self.assertTrue(all(s["ok"] for s in result["steps"]))
        detail = result["steps"][-1]["detail"]
        self.assertIn("READY", detail)
        self.assertIn(claude_director._director_model(), detail)
        # A working probe is not a promise about a show, and says so.
        self.assertIn("longer answer", result["note"])

    def test_the_probe_asks_for_one_word(self):
        """It runs while somebody waits; measuring the model's prose is
        not what this is for."""
        self.assertIn("one word", director_check.PROBE_PROMPT)
        self.assertLess(len(director_check.PROBE_PROMPT), 120)


if __name__ == "__main__":
    unittest.main()
