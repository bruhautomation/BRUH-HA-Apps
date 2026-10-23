#!/usr/bin/env python3
"""A guess the house already answers is not asked.

A real house was asked "Is the X air handler in Room 14?" while memory held
a confirmed fact saying so and two of the air handler's sensors were
assigned to that room. Before a guess is filed (`hypotheses.propose`), it
is read against what settles it: a confirmed, corrected or taught fact
saying the same thing, and the rooms the registry gives the things it
names. A guess either answers is dropped. The house book's "where is it"
rule, one queue over.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import hypotheses  # noqa: E402

NAMES = {
    "sensor.x_air_handler_supply_temperature": {
        "name": "X Air Handler Supply Temperature", "area": "Room 14"},
    "sensor.x_air_handler_return_temperature": {
        "name": "X Air Handler Return Temperature", "area": "Room 14"},
    "light.hall": {"name": "Hall light", "area": "Hall"},
}
CONFIRMED = [{"text": "The Y boiler is in the garage.", "source": "confirmed"}]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (hypotheses.HYPOTHESES_FILE, hypotheses.KNOWN_ANSWER)
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "hypotheses.jsonl"

    def tearDown(self):
        hypotheses.HYPOTHESES_FILE, hypotheses.KNOWN_ANSWER = self._old
        self.tmp.cleanup()


class TestTheRegistryAnswersWhere(Case):
    def test_a_room_the_things_sensors_are_assigned_to_is_not_asked(self):
        self.assertTrue(hypotheses.known_answer(
            "Is the X air handler in Room 14?", [], NAMES))

    def test_a_room_they_are_not_in_is_still_asked(self):
        self.assertFalse(hypotheses.known_answer(
            "Is the X air handler in the Hall?", [], NAMES))

    def test_a_question_about_something_else_is_still_asked(self):
        self.assertFalse(hypotheses.known_answer(
            "Does the X air handler run longer on cold nights?", [], NAMES))


class TestAFactAnswers(Case):
    def test_a_confirmed_fact_saying_it_settles_it(self):
        self.assertTrue(hypotheses.known_answer(
            "Is the Y boiler in the garage?", CONFIRMED, {}))

    def test_a_correction_settles_it_too(self):
        facts = [{"text": "The Y boiler is not in the garage, it is in "
                          "the cellar.", "source": "correction"}]
        self.assertTrue(hypotheses.known_answer(
            "Is the Y boiler in the garage?", facts, {}))

    def test_a_machine_guess_does_not(self):
        facts = [{"text": "The Y boiler is in the garage.",
                  "source": "insights"}]
        self.assertFalse(hypotheses.known_answer(
            "Is the Y boiler in the garage?", facts, {}))

    def test_a_different_claim_is_still_asked(self):
        self.assertFalse(hypotheses.known_answer(
            "Does the Y boiler heat the hot water too?", CONFIRMED, {}))


class TestProposeAsksFirst(Case):
    def test_an_answered_guess_is_not_filed(self):
        hypotheses.KNOWN_ANSWER = lambda text: hypotheses.known_answer(
            text, CONFIRMED, NAMES)
        self.assertIsNone(hypotheses.propose(
            "Is the X air handler in Room 14?", "climate"))
        self.assertIsNone(hypotheses.propose(
            "Is the Y boiler in the garage?", "climate"))
        self.assertEqual(hypotheses.list_all(), [])
        self.assertIsNotNone(hypotheses.propose(
            "Is the X air handler in the Hall?", "climate"))


if __name__ == "__main__":
    unittest.main()
