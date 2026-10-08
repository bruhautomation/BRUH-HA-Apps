#!/usr/bin/env python3
"""A failed run's fault row says which card it was and when.

"Run (card): ended crash — claude exited 143: no output" named a kind of
run and nothing a person could go and look at: not the card, not the
time. The journal row carries what the run was about when its caller
knew (`extra.title`, `extra.label`, else `extra.id`), and the row says
so; the latest occurrence's time rides in the detail, where the devloop
fingerprint (digits folded, words kept) cannot be split by a weekday.
`reports.faults` stays pure over the payload it is handed.
"""

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import reports  # noqa: E402

T0 = 1_800_000_000


def diag(*rows):
    return {"journal": {"failures": list(rows)}}


def run(ts, **extra):
    row = {"ts": ts, "source": "insight", "outcome": "timeout", "ok": False,
           "error": "the run took too long"}
    if extra:
        row["extra"] = extra
    return row


class TestTheRowNamesTheRun(unittest.TestCase):

    def test_the_card_is_named(self):
        [row] = reports.faults(diag(run(T0, id="energy", title="Energy use")))
        self.assertIn("Energy use", row["what"])

    def test_an_id_is_the_floor_for_a_row_with_no_title(self):
        [row] = reports.faults(diag(run(T0, id="custom-ab12")))
        self.assertIn("custom-ab12", row["what"])

    def test_the_latest_time_is_said_in_the_detail(self):
        rows = reports.faults(diag(run(T0, id="energy", title="Energy use"),
                                   run(T0 + 7200, id="energy",
                                       title="Energy use")))
        [row] = rows
        self.assertIn("2 times", row["what"])
        latest = time.strftime("%a %H:%M", time.localtime(T0 + 7200))
        self.assertIn(latest, row["detail"])
        self.assertIn("the run took too long", row["detail"])
        # The time is never in `what`, which a fingerprint is taken over.
        self.assertNotIn(latest, row["what"])

    def test_two_cards_are_two_rows(self):
        rows = reports.faults(diag(run(T0, id="energy", title="Energy use"),
                                   run(T0 + 60, id="climate",
                                       title="Climate")))
        self.assertEqual(len(rows), 2)

    def test_a_row_that_says_nothing_about_itself_reads_as_before(self):
        [row] = reports.faults(diag(run(T0)))
        self.assertEqual(row["where"], "Run (insight)")
        self.assertTrue(row["what"].startswith("ended timeout"))


if __name__ == "__main__":
    unittest.main()
