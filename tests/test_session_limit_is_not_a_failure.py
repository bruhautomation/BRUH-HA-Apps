#!/usr/bin/env python3
"""A session limit, and a run that fell back, are not failures.

Copied from a real report (2.11.0): 488 runs in a day, 111 `ok`, 84
`fallback` (each of which still produced a card) and 293 `error`, most of
them the account's "You've hit your session limit · resets 10:20pm". Health
read every non-`ok` word as a failure and said "most Claude runs are
failing"; the fault list opened with six identical session-limit rows; and
a notification the dispatcher had held until 07:00 tomorrow was reported as
one the flush "should have emptied".

  the count            health sums `!= "ok"` -> fallbacks and limits fail it
  the legacy row       outcome_of ignores the text -> an `error` written
                       before `classify` knew the wording still fails it
  one row per fact     no grouping -> six identical lines, then "4 more"
  a timed hold         ignore `next_hold_at` -> a hold doing its job is a fault
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import health  # noqa: E402
import journal  # noqa: E402
import reports  # noqa: E402

LIMIT = "You've hit your session limit · resets 10:20pm (America/New_York)"
NOW = 1_791_131_775


def limit_row(i: int) -> dict:
    return {"ts": NOW - 60000 + i * 600, "source": "resident",
            "outcome": "error", "ok": False, "error": LIMIT,
            "extra": {"job": "first_look"}}


class TestTheJournalCountsWhatFailed(unittest.TestCase):

    def test_a_legacy_error_row_carrying_the_limit_is_rate_limited(self):
        self.assertEqual(journal.outcome_of(limit_row(0)), "rate_limited")
        self.assertFalse(journal.is_failure(limit_row(0)))

    def test_a_real_error_stays_one(self):
        row = {"outcome": "error", "ok": False, "error": "claude exited 1"}
        self.assertEqual(journal.outcome_of(row), "error")
        self.assertTrue(journal.is_failure(row))

    def test_the_classifier_already_knows_this_wording(self):
        self.assertEqual(journal.classify({"ok": False, "error": LIMIT}),
                         "rate_limited")


class TestHealthReadsTheFailureCount(unittest.TestCase):

    def diag(self, journal_block):
        return {"auth": {"state": "ok"}, "daemons": {}, "options": {},
                "checks": {"finished_at": NOW - 600, "ran": ["a"], "error": ""},
                "usage": {"source": "account"}, "journal": journal_block}

    def test_fallbacks_and_limits_do_not_make_most_runs_fail(self):
        block = {"runs": 488, "by_outcome": {"ok": 111, "rate_limited": 209,
                                             "fallback": 84, "error": 84},
                 "failed": 84, "failed_by_outcome": {"error": 84}}
        found = {p["id"] for p in health.problems(self.diag(block), now=NOW)}
        self.assertNotIn("runs", found)

    def test_real_failures_still_degrade_it_and_name_the_word(self):
        block = {"runs": 20, "by_outcome": {"ok": 5, "timeout": 15},
                 "failed": 15, "failed_by_outcome": {"timeout": 15}}
        found = health.problems(self.diag(block), now=NOW)
        runs = [p for p in found if p["id"] == "runs"]
        self.assertTrue(runs)
        self.assertIn("'timeout'", runs[0]["fix"])

    def test_an_older_payload_keeps_the_old_arithmetic(self):
        block = {"runs": 20, "by_outcome": {"ok": 5, "error": 15}}
        self.assertIn("runs", {p["id"] for p in
                               health.problems(self.diag(block), now=NOW)})


class TestTheFaultListSaysEachThingOnce(unittest.TestCase):

    def test_session_limit_rows_are_not_faults(self):
        diag = {"generated_at": NOW,
                "journal": {"failures": [limit_row(i) for i in range(10)]}}
        self.assertFalse([r for r in reports.faults(diag)
                          if r["where"].startswith("Run")])

    def test_identical_failures_are_one_row_with_a_count(self):
        boom = {"source": "card", "outcome": "error", "ok": False,
                "error": "claude exited 1"}
        diag = {"generated_at": NOW,
                "journal": {"failures": [dict(boom, ts=i) for i in range(7)]}}
        rows = [r for r in reports.faults(diag) if r["where"].startswith("Run")]
        self.assertEqual(len(rows), 1)
        self.assertIn("7 times", rows[0]["what"])


class TestAHoldUntilLaterIsNotAFault(unittest.TestCase):

    def notify_rows(self, **notify):
        diag = {"generated_at": NOW, "notify": {"quiet_now": False, **notify}}
        return [r for r in reports.faults(diag) if r["where"] == "Notifications"]

    def test_the_reported_case(self):
        self.assertFalse(self.notify_rows(
            held=1, dispatch={"timed_holds": 1, "next_hold_at": NOW + 66225}))

    def test_a_timed_hold_whose_time_has_passed_is(self):
        self.assertTrue(self.notify_rows(
            held=1, dispatch={"timed_holds": 1, "next_hold_at": NOW - 60}))

    def test_an_untimed_hold_outside_quiet_hours_is(self):
        self.assertTrue(self.notify_rows(held=1))
        self.assertTrue(self.notify_rows(
            held=2, dispatch={"timed_holds": 1, "next_hold_at": NOW + 600}))


if __name__ == "__main__":
    unittest.main()
