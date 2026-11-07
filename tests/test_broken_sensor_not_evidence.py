#!/usr/bin/env python3
"""A sensor the owner called broken is not read as evidence of anything.

A house answered "this sensor is broken, please ignore it" on an
impossible-readings row about a manifold pressure sensor, and the Resident
went on citing its negative readings as evidence of an air leak (#692,
#701), while the band check kept judging the same readings. The answer is
about the SENSOR (`corrections.known_faulty`), so:

- every check that judges a sensor's readings stands down for it — the
  band (`base.unusual`) and the drift (`forecast.decline`) beside the
  impossible-readings and frozen checks it already covered;
- the Resident is told, in its own prompt, which sensors the owner called
  broken and that their readings are evidence of nothing;
- a case that cites one in its words (not only in an evidence row) is
  refused.

Driven with a fridge door-seal sensor, a sensor the reports never named.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import resident  # noqa: E402
from checks._util import House  # noqa: E402

SEAL = "sensor.fridge_door_seal_pressure"
REASON = "this sensor is broken, please ignore it"


def house() -> House:
    return House({"states": {SEAL: {"state": "-4", "attributes": {}}},
                  "entities": [{"entity_id": SEAL, "device_id": "d1"}],
                  "faulty": {SEAL: REASON}, "answers": {}})


class TestEveryReadingCheckStandsDown(unittest.TestCase):
    def test_the_band_and_the_drift_are_quiet_on_a_broken_sensor(self):
        for check in ("base.unusual", "forecast.decline", "dev.implausible",
                      "dev.frozen"):
            with self.subTest(check=check):
                self.assertFalse(house().should_report(SEAL, check))

    def test_a_check_about_something_else_is_not(self):
        self.assertTrue(house().should_report(SEAL, "auto.never_fired"))


class TestTheResidentIsTold(unittest.TestCase):
    def test_the_investigation_prompt_names_the_broken_sensor(self):
        prompt = resident.investigate_prompt(
            {"subject": "switch.garage_compressor", "text": "compressor ran"},
            faulty={SEAL: REASON})
        self.assertIn(SEAL, prompt)
        self.assertIn(REASON, prompt)
        self.assertIn("not evidence", prompt)

    def test_the_first_look_prompt_names_it_too(self):
        prompt = resident.first_look_prompt(
            [{"subject": "switch.garage_compressor", "text": "ran"}],
            faulty={SEAL: REASON})
        self.assertIn(SEAL, prompt)

    def test_no_block_when_nothing_was_called_broken(self):
        prompt = resident.investigate_prompt(
            {"subject": "switch.garage_compressor", "text": "ran"}, faulty={})
        self.assertNotIn("not evidence", prompt)


class TestACaseCitingItInWordsIsRefused(unittest.TestCase):
    def test_named_in_the_detail_only(self):
        case = {"entity_id": "switch.garage_compressor",
                "claim": "The compressor may have an air leak",
                "detail": f"{SEAL} read -4 kPa overnight, which points to a "
                          "leak.", "evidence": []}
        self.assertIn(SEAL, resident.faulty_case(case, [], {SEAL: REASON}))

    def test_a_case_not_resting_on_it_stands(self):
        case = {"entity_id": "switch.garage_compressor",
                "claim": "The compressor ran for six hours",
                "detail": "switch.garage_compressor stayed on.",
                "evidence": []}
        self.assertEqual(resident.faulty_case(case, [], {SEAL: REASON}), "")


if __name__ == "__main__":
    unittest.main()
