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

import json
import os
import re
import sys
import tempfile
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
        # `config.yaml`'s own names. They were `enable_assist` and
        # `enable_automations` here and in `health.DAEMONS`, which the
        # add-on has never had — so the fixture agreed with the code and
        # both were wrong, and two `failed` verdicts could never fire on
        # a real install. See TestTheOptionNamesAreTheAddonsOwn.
        "options": {"enable_terminal": True,
                    "enable_assist_integration": True,
                    "assist_fast_mode": True,
                    "enable_automation_integration": True, "learning": True,
                    "checks_interval_hours": 6},
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
                    options={"enable_terminal": False,
                             "enable_assist_integration": False,
                             "enable_automation_integration": False,
                             "checks_interval_hours": 6})
        self.assertEqual(health.verdict(snap, now=NOW)["state"], "ok")

    def test_a_roll_call_that_could_not_be_taken_accuses_nobody(self):
        """An empty roll-call is /proc unreadable, not seven dead daemons."""
        got = health.verdict(diag(daemons={}), now=NOW)
        self.assertEqual(got["state"], "ok")

    def test_a_fresh_install_with_no_checks_pass_is_not_overdue(self):
        got = health.verdict(diag(checks={}), now=NOW)
        self.assertNotIn("checks_overdue", ids(got["problems"]))


# What `usage_store.limits_problem()` really returns, which is a dict and
# was written down here as a bare string. `http_429` moved out of the fault
# set with this release, so the one that stands for a real problem is a
# refusal naming something a person can act on.
REAL_PROBLEM = {"code": "http_401"}
# And the one out of the user report that prompted the narrowing, verbatim.
REFRESH_PENDING = {
    "code": "oauth_token_awaiting_refresh",
    "needs_nothing": True,
    "detail": ("The signed-in account credential's access token has lapsed "
               "and Claude Code mints the next one itself, from the refresh "
               "token beside it, the next time anything runs Claude."),
    "next_attempt": NOW + 300,
}


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

    def test_learning_off_is_not_two_dead_daemons(self):
        """run.sh starts neither the consolidator nor the study watcher
        when `learning` is off, so their absence is the option, and the
        age of a pass nothing is meant to make is not staleness. This was
        a permanent `degraded` on every house that switched learning off."""
        snap = diag(daemons={**ALL_DAEMONS,
                             "memory_consolidator": {"running": False,
                                                     "last_pass_hours_ago": 400.0},
                             "study_watcher": {"running": False}},
                    options={**diag()["options"], "learning": False})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "ok", got["problems"])
        self.assertEqual(got["problems"], [])

    def test_learning_on_still_notices_the_two_daemons_missing(self):
        """The control: with learning on, the same roll-call is a fault."""
        snap = diag(daemons={**ALL_DAEMONS,
                             "memory_consolidator": {"running": False},
                             "study_watcher": {"running": False}})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "degraded")
        self.assertEqual({"daemon:memory_consolidator", "daemon:study_watcher"},
                         ids(got["problems"]))

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
        snap = diag(usage={"source": "estimate", "limits": REAL_PROBLEM})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "degraded")

    def test_a_code_whose_remedy_is_nothing_is_not_a_fault(self):
        """Copied from a real report rather than written down from the
        shape the code expects — the fixture above was a bare string for
        the life of this check, which is why `if usage.get("limits")`
        passed on it and nobody could see that every code was a fault.

        An access token lapses several hours out of every day and Claude
        Code mints the next one on its next run. Reporting that as
        `degraded` put a Repairs issue and a problem report in front of
        somebody daily, about a credential doing what credentials do."""
        snap = diag(usage={"source": "estimate", "limits": REFRESH_PENDING})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "ok")
        self.assertNotIn("usage", ids(health.problems(snap, now=NOW)))

    def test_a_mirror_written_before_this_release_still_reports(self):
        """`health` reads a flag the payload carries rather than deciding
        which codes mean what — it is stdlib-only and pure over the dict it
        is handed, and `usage_store` owns that vocabulary. An older mirror
        has no flag, which reads as False: the fault surfaces, which is the
        safe direction."""
        snap = diag(usage={"source": "estimate",
                           "limits": {"code": "oauth_token_awaiting_refresh"}})
        self.assertIn("usage", ids(health.problems(snap, now=NOW)))


class TestTheWorstThingWins(unittest.TestCase):
    def test_the_reason_is_the_worst_problem_not_the_first_found(self):
        snap = diag(auth={"state": "error"},
                    usage={"source": "estimate", "limits": REAL_PROBLEM})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(got["state"], "failed")
        self.assertIn("signed in", got["reason"])

    def test_everything_else_rides_underneath(self):
        """A verdict is a state and a sentence, never a score — one number
        over a house hides its worst problem inside an average."""
        snap = diag(auth={"state": "error"},
                    usage={"source": "estimate", "limits": REAL_PROBLEM})
        got = health.verdict(snap, now=NOW)
        self.assertEqual(len(got["problems"]), 2)

    def test_every_problem_names_the_switch_rather_than_the_symptom(self):
        snap = diag(auth={"state": "error"},
                    checks={"finished_at": int(NOW - 40 * 3600)},
                    journal={"runs": 10, "by_outcome": {"ok": 1, "timeout": 9}},
                    usage={"source": "estimate", "limits": REAL_PROBLEM},
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


class TestAHoldThatNeverEnds(unittest.TestCase):
    """The failure that would make quiet hours a lie.

    Holding rather than dropping is only honest if the hold ends. A flush
    loop that died is invisible from every surface — the findings are on
    the tab, nothing errors, and the phone is simply quiet — which is the
    exact shape of every quiet failure this module exists to catch.
    """

    NOW = 1_700_000_000.0

    def diag(self, **notify):
        return diag(notify={"service": True, "held": 0, "held_since": 0,
                            "quiet_start": 22, "quiet_end": 7, **notify})

    def keys(self, diag):
        return {p["id"] for p in health.problems(diag, now=self.NOW)}

    def test_an_empty_queue_is_silent(self):
        self.assertNotIn("notify-hold", self.keys(self.diag()))

    def test_an_ordinary_overnight_hold_is_silent(self):
        self.assertNotIn("notify-hold", self.keys(self.diag(
            held=3, held_since=int(self.NOW - 5 * 3600))))

    def test_a_hold_no_morning_ever_ended_is_reported(self):
        problems = health.problems(
            self.diag(held=3, held_since=int(self.NOW - 40 * 3600)),
            now=self.NOW)
        row = next(p for p in problems if p["id"] == "notify-hold")
        self.assertEqual(row["state"], "degraded")
        self.assertIn("3", row["what"])
        self.assertIn("Restart", row["fix"])

    def test_a_count_with_no_stamp_accuses_nobody(self):
        # An older queue file, or one written before the stamp existed.
        # "I cannot tell how long" is not "it has been days".
        self.assertNotIn("notify-hold",
                         self.keys(self.diag(held=3, held_since=0)))

    def test_a_payload_with_no_notify_block_at_all_is_silent(self):
        self.assertNotIn("notify-hold", self.keys(diag()))


class TestTheOptionNamesAreTheAddonsOwn(unittest.TestCase):
    """Every option this module gates a daemon on has to exist.

    `DAEMONS` asked after `enable_assist` and `enable_automations`; the
    add-on's options are `enable_assist_integration` and
    `enable_automation_integration`, which is what `run.sh` reads when it
    decides whether to start either. `dict.get` answers `None` for a name
    that is not there, so both entries were skipped on every install: the
    automation listener dying was reported by nothing, and
    `_assist_daemon` — the one `failed` verdict about voice — returned on
    its first line and could never fire. Nothing failed; two guards were
    simply off.

    The suite could not see it because the fixture wrote the same names
    down that the code did, which is what makes reading them out of
    `config.yaml` the load-bearing half of the fix rather than a tidy-up:
    a name is checked against the file that defines it, never against a
    second copy of somebody's memory of it.
    """

    @staticmethod
    def schema_keys() -> set:
        text = (BASE_DIR / "brain" / "config.yaml").read_text(encoding="utf-8")
        body = text.split("\nschema:", 1)[1]
        return set(re.findall(r"^  ([a-z_]+):", body, re.M))

    def test_every_daemon_option_is_a_real_option(self):
        known = self.schema_keys()
        self.assertIn("enable_assist_integration", known)
        for name, spec in health.DAEMONS.items():
            if spec.get("always"):
                continue
            self.assertIn(spec["option"], known,
                          f"{name} is gated on an option that does not exist")

    def test_the_assist_gate_is_a_real_option(self):
        """`_assist_daemon`'s own name, driven rather than grepped for."""
        known = self.schema_keys()
        asked = [k for k in known
                 if health._assist_daemon(
                     {"daemons": {"assist_worker_pool": {"running": False},
                                  "assist_listener": {"running": False}}},
                     {k: True})]
        self.assertTrue(asked, "no option in config.yaml switches the assist "
                               "check on, so it can never fire")
        self.assertIn("enable_assist_integration", asked)


class TestWhichDaemonsWereAskedFor(unittest.TestCase):
    """`expected_daemons` — the inventory's half of the same question.

    `reports.faults` read the roll-call raw and opened every fast-mode
    install's report with `not running: assist_listener`, which is a
    choice reported as a fault by the one function whose docstring says
    a refusal doing its job is not one.
    """

    def test_the_unchosen_assist_implementation_is_not_expected(self):
        fast = health.expected_daemons({"enable_assist_integration": True,
                                        "assist_fast_mode": True})
        self.assertIn("assist_worker_pool", fast)
        self.assertNotIn("assist_listener", fast)
        classic = health.expected_daemons({"enable_assist_integration": True,
                                           "assist_fast_mode": False})
        self.assertIn("assist_listener", classic)
        self.assertNotIn("assist_worker_pool", classic)

    def test_assist_switched_off_expects_neither(self):
        got = health.expected_daemons({"enable_assist_integration": False})
        self.assertNotIn("assist_listener", got)
        self.assertNotIn("assist_worker_pool", got)

    def test_an_option_that_is_off_is_not_expected(self):
        self.assertNotIn("ttyd", health.expected_daemons({}))
        self.assertIn("ttyd", health.expected_daemons({"enable_terminal": True}))

    def test_the_always_on_ones_are_always_expected(self):
        self.assertIn("usage_tracker", health.expected_daemons({}))

    def test_it_agrees_with_the_verdict_about_what_was_asked_for(self):
        """One answer to "was this wanted", two loudnesses.

        Anything `expected_daemons` leaves out must not produce a problem
        when it is down, or the inventory and the verdict disagree about
        the same house.
        """
        options = {"enable_terminal": True, "enable_assist_integration": True,
                   "assist_fast_mode": True,
                   "enable_automation_integration": False, "learning": False}
        wanted = health.expected_daemons(options)
        down = {name: {"running": name in wanted} for name in ALL_DAEMONS}
        got = health.problems({"daemons": down, "auth": {"state": "ok"}},
                              options, now=NOW)
        self.assertEqual([p["id"] for p in got], [])


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Which codes mean "there is nothing to do" — usage_store's own claim
# ---------------------------------------------------------------------------

class TestWhichMissingFiguresAreFaults(unittest.TestCase):
    """The vocabulary lives beside `limits_problem`, which is the reader
    that owns the tracker's file, and the flag it stamps is what `health`
    goes on. Driven through the real function over a real file, because a
    fixture that writes the shape down from the same guess the code did is
    the failure `_error_code` shipped and this module's own `limits` string
    repeated for four releases."""

    def setUp(self):
        import usage_store
        self.usage_store = usage_store
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old = usage_store.LIMITS_FILE
        self.addCleanup(setattr, usage_store, "LIMITS_FILE", self._old)
        usage_store.LIMITS_FILE = os.path.join(self.tmp.name, "limits.json")

    def problem(self, code: str) -> dict:
        with open(self.usage_store.LIMITS_FILE, "w", encoding="utf-8") as fh:
            json.dump({"error": code}, fh)
        return self.usage_store.limits_problem()

    def test_a_credential_between_refreshes_needs_nothing(self):
        """It says in as many words that nothing is wrong with the sign-in
        and that signing in again will not help, so a verdict of `degraded`
        put a Repairs issue in front of somebody several hours out of every
        day about a credential doing what credentials do."""
        got = self.problem("oauth_token_awaiting_refresh")
        self.assertTrue(got["needs_nothing"])

    def test_an_api_key_has_no_window_to_report(self):
        """And never will, so this one could not clear at all."""
        self.assertTrue(self.problem("api_key_has_no_usage_limits")
                        ["needs_nothing"])

    def test_the_endpoints_own_rate_limit_is_a_refusal_doing_its_job(self):
        """The tracker answers a 429 with a backoff ladder built for it."""
        self.assertTrue(self.problem("http_429")["needs_nothing"])

    def test_everything_that_names_something_a_person_can_do_is_a_fault(self):
        for code in ("no_oauth_token", "http_401",
                     "oauth_token_lacks_usage_scope"):
            self.assertFalse(self.problem(code)["needs_nothing"], code)

    def test_a_code_nothing_recognises_is_a_fault(self):
        """"I do not know what this means" and "there is nothing to do" are
        different claims, and only the second may keep one off a verdict."""
        self.assertFalse(self.problem("something_new")["needs_nothing"])
        self.assertFalse(self.usage_store.needs_nothing(""))
