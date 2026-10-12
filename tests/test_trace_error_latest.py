"""`auto.trace_error` judges the automation's most recent FINISHED run.

One transient error (a Z-Wave send that timed out once) filed a serious
card saying the automation "failed the last time it ran", and the card
stayed open after later runs finished cleanly. Three things decide what
"the last time" is, and each is driven here:

* runs are ordered by when they FINISHED, parsed as times — a parallel
  run that started earlier and ended later is the later answer;
* a run the trace window does not hold still moved `last_triggered`, so
  an automation whose actions ran after the error finished has a later
  run, and the error is history;
* a single failure among clean runs is not reported at `serious`.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))
sys.path.insert(0, os.path.dirname(__file__))

from checks import automations  # noqa: E402
from test_house_checks import NOW, core_run, house, iso  # noqa: E402


KEY = "automation.morning-1"


class TestTheMostRecentFinishedRunDecides(unittest.TestCase):

    def test_a_later_run_the_window_does_not_hold_clears_it(self):
        snap = house()
        snap["traces"][KEY] = [core_run("1", "error", 3600, error="send failed")]
        # The automation's actions ran an hour after that error finished.
        snap["states"]["automation.morning"]["attributes"]["last_triggered"] = iso(60)
        self.assertEqual(automations.trace_error(snap, NOW), [])

    def test_the_run_that_finished_last_decides_not_the_one_that_started_last(self):
        snap = house()
        clean = core_run("1", "finished", 600)
        clean["timestamp"]["finish"] = iso(10)      # a long run, ended last
        broken = core_run("2", "error", 300, error="send failed")
        broken["timestamp"]["finish"] = iso(290)
        snap["traces"][KEY] = [clean, broken]
        snap["states"]["automation.morning"]["attributes"]["last_triggered"] = iso(300)
        self.assertEqual(automations.trace_error(snap, NOW), [])

    def test_times_are_compared_as_times_not_strings(self):
        snap = house()
        clean = core_run("1", "finished", 120)
        clean["timestamp"] = {"start": "2026-01-01T00:00:00+00:00",
                              "finish": "2026-01-01T00:00:01+00:00"}
        broken = core_run("2", "error", 300, error="send failed")
        # Earlier in absolute time, but sorts after as a string.
        broken["timestamp"] = {"start": "2026-01-01T01:00:00+05:00",
                               "finish": "2026-01-01T01:00:01+05:00"}
        snap["traces"][KEY] = [broken, clean]
        snap["states"]["automation.morning"]["attributes"]["last_triggered"] = (
            "2025-12-31T00:00:00+00:00")
        self.assertEqual(automations.trace_error(snap, NOW), [])

    def test_one_failure_among_clean_runs_is_not_serious(self):
        snap = house()
        snap["traces"][KEY] = [
            core_run("1", "finished", 7200), core_run("2", "finished", 3600),
            core_run("3", "error", 30, error="send failed")]
        snap["states"]["automation.morning"]["attributes"]["last_triggered"] = iso(30)
        found = automations.trace_error(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertNotEqual(found[0]["severity"], "serious")
        self.assertIn("1 of its last 3 runs", found[0]["detail"])

    def test_repeated_failures_stay_serious(self):
        snap = house()
        snap["traces"][KEY] = [
            core_run("1", "error", 7200, error="send failed"),
            core_run("2", "error", 30, error="send failed")]
        snap["states"]["automation.morning"]["attributes"]["last_triggered"] = iso(30)
        found = automations.trace_error(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "serious")
        self.assertIn("2 of its last 2 runs", found[0]["detail"])


if __name__ == "__main__":
    unittest.main()
