#!/usr/bin/env python3
"""Tests for the health verdict — "is brAIn working".

The verdict exists because the failures this add-on has actually shipped
were quiet ones: a listener that died, a credential that expired on a
Tuesday afternoon, a consolidator running and landing nothing. Every one
was visible from inside the add-on for hours before anybody noticed from
outside it.

So the tests that matter here are the ones about NOT crying wolf — an
add-on with the terminal switched off has no ttyd and nothing is wrong —
and the ones about a verdict going stale, which is the same failure the
usage sensors had: a reading nothing can correct.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import health  # noqa: E402

NOW = 1_700_000_000.0
ALL_DAEMONS = {name: {"running": True} for name in (
    "ttyd", "usage_tracker", "memory_consolidator", "study_watcher",
    "assist_worker_pool", "assist_listener", "automation_listener")}


def diag(**over) -> dict:
    """A healthy add-on with everything switched on."""
    payload = {
        "auth": {"state": "ok"},
        "daemons": {k: dict(v) for k, v in ALL_DAEMONS.items()},
        "checks": {"finished_at": int(NOW - 1800), "ran": ["a"], "error": ""},
        "journal": {"runs": 20, "by_outcome": {"ok": 19, "error": 1}},
        "usage": {"source": "account", "used_percent": 12},
        "options": {"enable_terminal": True, "enable_assist": True,
                    "enable_automations": True, "checks_interval_hours": 6},
    }
    payload.update(over)
    return payload


def ids(found) -> set:
    return {p["id"] for p in found}


class TestAHealthyAddOnIsSilent(unittest.TestCase):
    def test_nothing_is_wrong_with_the_clean_fixture(self):
        got = health.verdict(diag(), now=NOW)
        self.assertEqual(got["state"], "ok")
        self.assertEqual(got["problems"], [])

    def test_ok_does_not_hedge(self):
        """A verdict that says "mostly fine" is one nobody reads twice, and
        this is the entity people put on a dashboard so they can stop
        checking."""
        self.assertEqual(health.verdict(diag(), now=NOW)["fix"], "")

    def test_a_switched_off_face_is_not_a_fault(self):
        """The roll-call is descriptive on purpose; the interpretation is
        here, and it is against the options."""
        snap = diag(daemons={**ALL_DAEMONS,
                             "ttyd": {"running": False},
                             "automation_listener": {"running": False},
                             "assist_worker_pool": {"running": False},
                             "assist_listener": {"running": False}},
                    options={"enable_terminal": False, "enable_assist": False,
                             "enable_automations": False,
                             "checks_interval_hours": 6})
        self.assertEqual(health.verdict(snap, now=NOW)["state"], "ok")

    def test_a_roll_call_that_could_not_be_taken_accuses_nobody(self):
        """An empty roll-call is /proc unreadable, not seven dead daemons."""
        got = health.verdict(diag(daemons={}), now=NOW)
        self.assertEqual(got["state"], "ok")

    def test_a_fresh_install_with_no_checks_pass_is_not_overdue(self):
        got = health.verdict(diag(checks={}), now=NOW)
        self.assertNotIn("checks_overdue", ids(got["problems"]))


class TestTheThingsThatMatter(unittest.TestCase):
    def test_a_dead_credential_fails_rather_than_degrades(self):
        """Nothing that needs a turn can run: insights, chat, voice and the
        consolidator all stop together."""
        got = health.verdict(diag(auth={"state": "error", "error": "401"}), now=NOW)
        self.assertEqual(got["state"], "failed")
        self.assertIn("signed in", got["reason"])
        self.assertIn("401", got["fix"])

    def test_a_check_in_flight_is_not_a_failure(self):
        self.assertEqual(
            health.verdict(diag(auth={"state": "checking"}), now=NOW)["state"], "ok")

    def test_a_dead_automation_listener_fails(self):
        """Its absence is silent from outside: brain.run_task times out with
        nothing reading it."""
        snap = diag(daemons={**ALL_DAEMONS, "automation_listener": {"running": False}})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "failed")

    def test_either_assist_implementation_answers_for_voice(self):
        """The channel is one job with two implementations and which one runs
        depends on assist_fast_mode. Asking after both by name would report
        the one that is correctly absent."""
        for alive in ("assist_worker_pool", "assist_listener"):
            daemons = {**ALL_DAEMONS,
                       "assist_worker_pool": {"running": False},
                       "assist_listener": {"running": False},
                       alive: {"running": True}}
            self.assertNotIn("assist",
                             ids(health.problems(diag(daemons=daemons), now=NOW)),
                             alive)

    def test_neither_assist_implementation_is_a_failure(self):
        daemons = {**ALL_DAEMONS,
                   "assist_worker_pool": {"running": False},
                   "assist_listener": {"running": False}}
        got = health.verdict(diag(daemons=daemons), now=NOW)
        self.assertEqual(got["state"], "failed")
        self.assertIn("voice", got["reason"])

    def test_a_consolidator_that_runs_and_never_lands_is_degraded(self):
        """The process being alive was never the question — the queue moving
        is."""
        daemons = {**ALL_DAEMONS,
                   "memory_consolidator": {"running": True,
                                           "last_pass_hours_ago": 40.0}}
        got = health.verdict(diag(daemons=daemons), now=NOW)
        self.assertEqual(got["state"], "degraded")
        self.assertIn("consolidation", ids(got["problems"]))

    def test_a_fresh_install_that_has_never_consolidated_is_not_stale(self):
        """No marker file is a real state, reported by the field's absence
        rather than by a made-up number."""
        self.assertNotIn("consolidation", ids(health.problems(diag(), now=NOW)))

    def test_checks_that_have_stopped_running_are_noticed(self):
        snap = diag(checks={"finished_at": int(NOW - 40 * 3600), "ran": ["a"]})
        self.assertIn("checks_overdue", ids(health.problems(snap, now=NOW)))

    def test_a_slow_pass_is_not_a_stopped_one(self):
        """A pass takes minutes and a Pi under load takes longer. A sensor
        that cries wolf on a slow morning is a sensor people disable."""
        snap = diag(checks={"finished_at": int(NOW - 7 * 3600), "ran": ["a"]})
        self.assertNotIn("checks_overdue", ids(health.problems(snap, now=NOW)))

    def test_mostly_failing_runs_are_degraded_and_name_the_outcome(self):
        snap = diag(journal={"runs": 10,
                             "by_outcome": {"ok": 2, "timeout": 7, "error": 1}})
        found = [p for p in health.problems(snap, now=NOW) if p["id"] == "runs"]
        self.assertEqual(len(found), 1)
        self.assertIn("timeout", found[0]["fix"])

    def test_two_failures_out_of_three_runs_is_an_anecdote(self):
        """Below a handful of runs a failure rate is noise, and a sensor
        that flickers is a sensor nobody trusts."""
        snap = diag(journal={"runs": 3, "by_outcome": {"ok": 1, "error": 2}})
        self.assertNotIn("runs", ids(health.problems(snap, now=NOW)))

    def test_a_usage_tracker_that_cannot_report_is_degraded_not_failed(self):
        """The pill falls back to a local estimate. That is worth saying and
        it is not brAIn being broken."""
        snap = diag(usage={"source": "estimate", "limits": "http_429"})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "degraded")


class TestTheWorstThingWins(unittest.TestCase):
    def test_the_reason_is_the_worst_problem_not_the_first_found(self):
        snap = diag(auth={"state": "error"},
                    usage={"source": "estimate", "limits": "http_429"})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "failed")
        self.assertIn("signed in", got["reason"])

    def test_everything_else_rides_underneath(self):
        """A verdict is a state and a sentence, never a score — one number
        over a house hides its worst problem inside an average."""
        snap = diag(auth={"state": "error"},
                    usage={"source": "estimate", "limits": "http_429"})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(len(got["problems"]), 2)

    def test_every_problem_names_the_switch_rather_than_the_symptom(self):
        snap = diag(auth={"state": "error"},
                    checks={"finished_at": int(NOW - 40 * 3600)},
                    journal={"runs": 10, "by_outcome": {"ok": 1, "timeout": 9}},
                    usage={"source": "estimate", "limits": "http_429"},
                    daemons={**ALL_DAEMONS,
                             "automation_listener": {"running": False},
                             "usage_tracker": {"running": False},
                             "memory_consolidator": {
                                 "running": True, "last_pass_hours_ago": 40.0}})
        found = health.problems(snap, now=NOW)
        self.assertGreaterEqual(len(found), 6)
        for problem in found:
            self.assertTrue(problem["fix"].strip(), problem["id"])
            self.assertIn(problem["state"], health.STATES)


class TestReadingItFromOutside(unittest.TestCase):
    """The integration reads a file the panel writes, so it has one question
    the panel does not: is this still true?"""

    def test_a_missing_mirror_is_a_state_not_an_absence(self):
        got = health.from_mirror(None, None, now=NOW)
        self.assertEqual(got["state"], "failed")
        self.assertTrue(got["fix"])

    def test_a_fresh_mirror_is_read_as_written(self):
        self.assertEqual(health.from_mirror(diag(), 0.2, now=NOW)["state"], "ok")

    def test_a_stale_mirror_fails_however_healthy_it_reads(self):
        """Serving the last good verdict would be a reading nothing can
        correct — exactly the usage sensors' bug."""
        got = health.from_mirror(diag(), 9.0, now=NOW)
        self.assertEqual(got["state"], "failed")
        self.assertIn("stopped publishing", got["reason"])

    def test_a_stale_mirror_keeps_what_it_did_say_underneath(self):
        got = health.from_mirror(diag(auth={"state": "error"}), 9.0, now=NOW)
        self.assertIn("mirror", ids(got["problems"]))
        self.assertIn("auth", ids(got["problems"]))

    def test_the_freshness_window_is_published_rather_than_agreed_twice(self):
        """The reader has to know when to stop believing the file, and a
        second copy of the number on that side is a second copy that
        drifts."""
        self.assertEqual(health.verdict(diag(), now=NOW)["stale_after_h"],
                         health.MIRROR_STALE_H)

    def test_the_sensor_falls_back_to_the_same_window(self):
        sensor = (BASE_DIR / "brain" / "custom_components" / "brain"
                  / "sensor.py").read_text()
        self.assertIn(f"HEALTH_STALE_AFTER_H = {health.MIRROR_STALE_H}", sensor)

    def test_the_sensor_uses_the_same_state_vocabulary(self):
        sensor = (BASE_DIR / "brain" / "custom_components" / "brain"
                  / "sensor.py").read_text()
        block = sensor.split("class BrainHealthSensor", 1)[1]
        for state in health.STATES:
            self.assertIn(f'"{state}"', block, state)


if __name__ == "__main__":
    unittest.main()
