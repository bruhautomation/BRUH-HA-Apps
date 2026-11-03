#!/usr/bin/env python3
"""A Resident that is not looking says so, in health and on the status line.

A house's Resident spent its allowance at 03:19 and held every look for
the rest of the day with 456 of 500 queued, while health said "ok —
everything brAIn runs is running" and the status line said "Watching ·
last look 46 min ago" — the 46 minutes were a routine checks pass, read as
a look because the line took the newer of the two (#631).

Now a hold by an allowance is timed (`RESIDENT_STATE["held_since"]`) and
past an hour is `degraded` with the reason; a queue over 80% is
`degraded`; and the status line reads the Resident's own last look.
"""

import sys
import time
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import health  # noqa: E402

NOW = 1_800_000_000.0


def resident(**over) -> dict:
    return {"resident": {"queue_len": 3, "queue_max": 500, "held_since": 0.0,
                         "last_error": "", **over}}


class TestTheRules(unittest.TestCase):
    def ids(self, diag):
        return [p["id"] for p in health.problems(diag, {}, NOW)]

    def test_looking_normally_is_nothing(self):
        self.assertEqual(self.ids(resident()), [])

    def test_a_short_hold_is_nothing(self):
        self.assertEqual(self.ids(resident(held_since=NOW - 600)), [])

    def test_held_past_an_hour_is_degraded_and_says_why(self):
        why = "the sonnet allowance for today is spent (32 of 32)"
        found = health.problems(resident(held_since=NOW - 8 * 3600,
                                         last_error=why), {}, NOW)
        self.assertEqual([p["state"] for p in found], ["degraded"])
        self.assertEqual(found[0]["id"], "resident:held")
        self.assertIn("8 hour", found[0]["what"])
        self.assertIn(why, found[0]["fix"])
        self.assertNotIn("Resident", found[0]["what"] + found[0]["fix"])
        self.assertEqual(health.verdict(resident(held_since=NOW - 8 * 3600),
                                        {}, NOW)["state"], "degraded")

    def test_a_nearly_full_queue_is_degraded(self):
        self.assertEqual(self.ids(resident(queue_len=456)), ["resident:queue"])
        self.assertEqual(self.ids(resident(queue_len=400)), [])


class TestTheServerKeepsTheHold(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.saved = dict(server.RESIDENT_STATE)
        self.saved_checks = dict(server.CHECKS_STATE)

    def tearDown(self):
        self.server.RESIDENT_STATE.clear()
        self.server.RESIDENT_STATE.update(self.saved)
        self.server.CHECKS_STATE.clear()
        self.server.CHECKS_STATE.update(self.saved_checks)

    def test_the_hold_starts_once_and_reaches_diagnostics(self):
        srv = self.server
        srv.RESIDENT_STATE["held_since"] = 0.0
        srv._resident_held(NOW - 7200)
        srv._resident_held(NOW - 60)          # still the same hold
        diag = {"resident": srv._resident_diagnostics()}
        self.assertEqual(diag["resident"]["held_since"], NOW - 7200)
        self.assertIn("resident:held",
                      [p["id"] for p in health.problems(diag, {}, NOW)])

    def test_the_status_line_reads_the_residents_own_look(self):
        srv = self.server
        now = time.time()
        srv.RESIDENT_STATE["last_look_at"] = now - 8 * 3600
        srv.CHECKS_STATE["last"] = {"finished_at": now - 46 * 60}
        st = srv._brain_status(settings={}, budget={}, auth="token", now=now)
        self.assertEqual(st["last_look_at"], int(now - 8 * 3600))


if __name__ == "__main__":
    unittest.main()
