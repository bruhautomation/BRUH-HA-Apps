#!/usr/bin/env python3
"""Every figure in a card's title is in its body, with the same unit.

A real house's cards said "0 kWh over the last 8 days" in the title and
"all 11 days" in the body, "no cooling at 73 °F" over a body whose
afternoon "passed 65 °F", and "The forecast flipped from 43 to clear" with
no unit or meaning for the 43. A title is what is read; a figure in it the
body does not stand behind is a figure nobody can check.

`card_claims.title_figures` is the deterministic check at the point a card
is accepted (`card_verdict.review`): a title figure the summary and tiles
do not state with the same value and unit, or a bare number that says
neither a unit nor what it counts, is taken out of the title — with the
words that only framed it ("over the last", "at") — and a title left with
nothing after its subject is the subject. The examples are not the house's.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import card_claims  # noqa: E402
import card_verdict  # noqa: E402
import categories  # noqa: E402


def card(title, summary, *tiles):
    return {"title": title, "summary": summary,
            "highlights": [{"label": lbl, "value": val} for lbl, val in tiles]}


class TestAFigureTheBodyDoesNotSay(unittest.TestCase):
    def test_a_window_the_body_states_differently_leaves_the_title(self):
        got = card_verdict.review(card(
            "Well pump: 212 gal in the last 3 days",
            "The well pump moved 212 gal since Fri, all of it before 09:00.",
            ("Water", "212 gal")))["obj"]
        self.assertEqual(got["title"], "Well pump: 212 gal")

    def test_a_temperature_the_body_never_reached_leaves_the_title(self):
        got = card_verdict.review(card(
            "Hot tub: heater off at 104 °F",
            "The heater stopped at 18:00 when the water reached 102 °F.",
            ("Water", "102 °F")))["obj"]
        self.assertEqual(got["title"], "Hot tub: heater off")

    def test_the_same_value_in_another_unit_is_not_the_same_figure(self):
        got = card_verdict.review(card(
            "Attic fan: ran 40 min",
            "It ran while the attic sat at 40 °F above the hall.",
            ("Attic", "40 °F")))["obj"]
        self.assertEqual(got["title"], "Attic fan")

    def test_figures_the_body_says_stay(self):
        for title, summary, tiles in (
                ("Back door: evening openings 14 → 5",
                 "Evening openings fell from 14 to 5 this week.", ()),
                ("Den heating: 34 h",
                 "The den heated for 33 h 55 min over the week.", ()),
                ("Freezer: 9 °F and rising",
                 "It rose from 0 °F at 06:00.", (("Freezer", "9 °F"),)),
                ("Sauna: 2 h 5 min on Sat 24 Oct",
                 "The heater ran from 17:00.", (("Sat", "2 h 5 min"),))):
            with self.subTest(title=title):
                got = card_verdict.review(card(title, summary, *tiles))["obj"]
                self.assertEqual(got["title"], title)


class TestABareNumber(unittest.TestCase):
    def test_a_number_with_no_unit_or_meaning_leaves_the_title(self):
        got = card_verdict.review(card(
            "Thermostat: the schedule jumped from 68 to 74",
            "The schedule moved from 68 °F to 74 °F at 05:00.",
            ("Setpoint", "74 °F")))["obj"]
        self.assertEqual(got["title"], "Thermostat: the schedule jumped")

    def test_bare_is_read_by_the_helper(self):
        self.assertEqual(
            [f["value"] for f in card_claims.title_figures(
                "Air quality turned from 12 to good") if f["bare"]], [12.0])
        self.assertFalse(any(f["bare"] for f in card_claims.title_figures(
            "Bedroom light: only 1 override")))


class TestTheContract(unittest.TestCase):
    def test_it_says_so(self):
        self.assertIn("same value and unit", categories._CARD_CONTRACT)


if __name__ == "__main__":
    unittest.main()
