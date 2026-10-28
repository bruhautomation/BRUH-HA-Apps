#!/usr/bin/env python3
"""A guess is filed with the day it means, not the day it was said.

A guess written as "…switched it to continuous mode yesterday afternoon…
Right?" still said "yesterday" a week later on the Today card, which is a
different afternoon every morning it is read. `hypotheses.propose` now
writes the relative day words (today, yesterday, this morning, last
night, tonight, this afternoon/evening) as the weekday they meant when the
guess was filed, and the case carries when it was asked.
"""

import datetime as dt
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import hypotheses  # noqa: E402

# A Wednesday afternoon, local time whatever the zone the suite runs in.
NOW = dt.datetime(2026, 10, 14, 15, 30).timestamp()
TODAY = dt.datetime.fromtimestamp(NOW).strftime("%A")
YESTERDAY = dt.datetime.fromtimestamp(NOW - 86400).strftime("%A")


class TestTheWordsAreMadeAbsolute(unittest.TestCase):
    def rewrite(self, text):
        return hypotheses.absolute_days(text, NOW)

    def test_yesterday_afternoon_is_the_weekday_it_meant(self):
        out = self.rewrite("You switched the pump to continuous mode "
                           "yesterday afternoon. Right?")
        self.assertIn(f"on {YESTERDAY} afternoon", out)
        self.assertNotIn("yesterday", out.lower())

    def test_every_relative_word_goes(self):
        for said, want in (
                ("this morning", f"on {TODAY} morning"),
                ("this evening", f"on {TODAY} evening"),
                ("tonight", f"on {TODAY} night"),
                ("last night", f"on {YESTERDAY} night"),
                ("today", f"on {TODAY}"),
                ("yesterday", f"on {YESTERDAY}")):
            with self.subTest(said=said):
                out = self.rewrite(f"The heater ran {said}.")
                self.assertEqual(out, f"The heater ran {want}.")

    def test_a_preposition_already_there_is_kept_alone(self):
        self.assertEqual(self.rewrite("It has been off since yesterday."),
                         f"It has been off since {YESTERDAY}.")

    def test_the_start_of_a_sentence_keeps_its_capital(self):
        self.assertTrue(self.rewrite("Yesterday you opened it.").startswith(
            f"On {YESTERDAY} you"))

    def test_a_possessive_reads_as_one(self):
        self.assertIn(f"{TODAY}'s run", self.rewrite("today's run was short"))

    def test_words_inside_other_words_are_left(self):
        text = "The todayness of the yesterdays."
        self.assertEqual(self.rewrite(text), text)


class TestProposeFilesTheAbsoluteDay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "h.jsonl"

    def tearDown(self):
        hypotheses.HYPOTHESES_FILE = self._old
        self.tmp.cleanup()

    def test_the_stored_guess_names_the_weekday(self):
        with unittest.mock.patch.object(hypotheses.time, "time", return_value=NOW):
            entry = hypotheses.propose(
                "You turned the fan on yesterday afternoon — right?",
                fact="The fan was turned on yesterday afternoon.")
        self.assertIsNotNone(entry)
        self.assertIn(YESTERDAY, entry["text"])
        self.assertNotIn("yesterday", entry["text"].lower())
        self.assertNotIn("yesterday", entry["fact"].lower())
        # Read at the same fixed moment: a guess expires after a few days,
        # so reading it at the real clock lost it once the suite ran past
        # the fixed day it was filed on.
        with unittest.mock.patch.object(hypotheses.time, "time", return_value=NOW):
            [row] = hypotheses.list_all("open")
        self.assertIn(YESTERDAY, row["text"])

    def test_the_case_says_when_it_was_asked(self):
        import cases
        with unittest.mock.patch.object(hypotheses.time, "time", return_value=NOW):
            entry = hypotheses.propose("The porch light is on a timer?")
        case = cases._from_hypothesis(
            {**entry, "snoozed_until": 0}, {})
        self.assertEqual(case["created_at"], int(entry["ts"]))
        self.assertEqual(case["asked_at"], int(entry["ts"]))


if __name__ == "__main__":
    unittest.main()
