#!/usr/bin/env python3
"""The shape of the Resident's prompts, read off the real builders.

What a model is handed decides what it does, and each of these was a gap
measured in the prompt text rather than in a reply: no worked example of a
verdict, a salience score on every row that reads as a judgement already
made, a refine contract buried in the base contract every run was handed,
open cases with no way to tell which device they were about, a camera line
after the sign-off, and a second opinion never told that "no" was allowed.
"""

import importlib
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import prompt_kit  # noqa: E402
import resident  # noqa: E402
import signals  # noqa: E402

NOON = 1_757_937_600.0


def signal(**over) -> dict:
    return signals.make("check", over.pop("subject", "sensor.hall_temp"),
                        now=NOON, salience=over.pop("salience", 0.73),
                        text=over.pop("text", "frozen for 9 days"), **over)


class TestTheFirstLook(unittest.TestCase):
    def test_it_carries_a_worked_example_of_each_cheap_verdict(self):
        system = resident.FIRST_LOOK_SYSTEM
        self.assertIn("FOR EXAMPLE", system)
        example = system.split("FOR EXAMPLE", 1)[1].split("Rules:", 1)[0]
        for verdict in ("ignore", "watch", "investigate"):
            self.assertIn(f"    {verdict}: ", example, verdict)
        # The ignore answers the CLAIM (it is frozen) with the home's own
        # account, which is what CLAIM_RULE asks for.
        self.assertIn("flat reading there is the machine working", example)

    def test_the_shared_privacy_and_data_blocks_are_in_it(self):
        self.assertIn(prompt_kit.PRIVACY, resident.FIRST_LOOK_SYSTEM)
        self.assertIn(prompt_kit.DATA_FENCE, resident.FIRST_LOOK_SYSTEM)
        self.assertIn(resident.CLAIM_RULE, resident.FIRST_LOOK_SYSTEM)

    def test_no_row_carries_the_salience_score(self):
        sig = signal(salience=0.73)
        for rows in (signals.prompt_rows([sig], NOON, numbered=False), [sig]):
            text = resident.first_look_prompt(rows)
            self.assertNotIn("0.73", text)
            self.assertNotIn(" s=", text)
            self.assertNotIn("salience", text)

    def test_the_order_still_carries_the_salience(self):
        low = signal(subject="sensor.low", salience=0.1)
        high = signal(subject="sensor.high", salience=0.9)
        text = resident.first_look_prompt(
            signals.prompt_rows(signals.rank([low, high]), NOON,
                                numbered=False))
        self.assertLess(text.index("sensor.high"), text.index("sensor.low"))


class TestTheInvestigation(unittest.TestCase):
    def test_the_base_says_nothing_about_ending_a_row(self):
        base = resident.INVESTIGATE_SYSTEM
        self.assertNotIn("A GOOD DISMISSAL", base)
        self.assertNotIn(resident.DISMISS_RULE, base)
        self.assertEqual(resident.investigate_system(), base)
        self.assertEqual(resident.investigate_system({"text": ""}), base)

    def test_a_refine_adds_the_endings_with_an_example_of_each(self):
        system = resident.investigate_system({"text": "Sensor frozen"})
        self.assertTrue(system.startswith(resident.INVESTIGATE_SYSTEM))
        self.assertIn(resident.DISMISS_RULE, system)
        self.assertIn("A GOOD DISMISSAL", system)
        self.assertIn("A GOOD REWRITE", system)
        rewrite = system.split("A GOOD REWRITE", 1)[1]
        # Specific: the device by its name, the hub, local time — no ids.
        self.assertIn("Zigbee hub", rewrite)
        self.assertIn("14:10", rewrite)
        self.assertNotIn("sensor.", rewrite)
        self.assertNotIn("UTC", rewrite)

    def test_the_shared_blocks_are_in_the_base(self):
        for block in (prompt_kit.PRIVACY, prompt_kit.HONEST_EMPTY,
                      prompt_kit.DATA_FENCE, resident.CLAIM_RULE):
            self.assertIn(block, resident.INVESTIGATE_SYSTEM)

    def test_the_schema_is_unchanged(self):
        self.assertEqual(
            resident.CASE_SCHEMA["required"],
            ["claim", "detail", "confidence", "stakes", "evidence",
             "actions", "escalate"])
        self.assertIn("dismiss", resident.CASE_SCHEMA["properties"])

    def test_the_camera_line_comes_before_the_sign_off(self):
        line = "\n\nCameras: you may look at camera.hall once."
        text = resident.investigate_prompt(signal(), camera_line=line)
        self.assertLess(text.index("camera.hall"),
                        text.index("Reply with the JSON contract"))
        self.assertTrue(text.endswith("nothing else."))
        self.assertNotIn("Cameras", resident.investigate_prompt(signal()))

    def test_the_second_opinion_is_told_an_empty_claim_is_an_answer(self):
        text = resident.investigate_prompt(
            signal(), prior_case={"claim": "The hall sensor is stuck",
                                  "confidence": 0.3})
        self.assertIn("second opinion", text)
        self.assertIn("An EMPTY claim is a valid answer", text)
        plain = resident.investigate_prompt(signal())
        self.assertNotIn("EMPTY claim", plain)

    def test_open_cases_are_explained_as_carrying_their_device(self):
        text = resident.investigate_prompt(
            signal(), open_cases_rows=["[problem] Hall sensor stuck — "
                                       "sensor.hall_temp"])
        self.assertIn("the id after a row is the device", text)
        self.assertIn("sensor.hall_temp", text)


class TestTheOpenCasesCarryTheirEntity(unittest.TestCase):
    """`server._open_case_rows`, driven over a stubbed case list."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.cases = self.server.cases
        self._old = self.cases.list_cases

    def tearDown(self):
        self.cases.list_cases = self._old

    def test_each_row_ends_with_its_entity_id_even_past_the_cap(self):
        self.cases.list_cases = lambda *a, **k: [
            {"kind": "problem", "claim": "The hall sensor is stuck",
             "entity_id": "sensor.hall_temp"},
            {"kind": "question", "claim": "word " * 80,
             "entity_id": "binary_sensor.landing_motion"},
            {"kind": "opportunity", "claim": "Dim the porch at night",
             "entity_id": ""},
        ]
        rows = self.server._open_case_rows()
        self.assertEqual(rows[0],
                         "[problem] The hall sensor is stuck — sensor.hall_temp")
        self.assertTrue(rows[1].endswith(" — binary_sensor.landing_motion"))
        self.assertLessEqual(len(rows[1]), 160)
        self.assertEqual(rows[2], "[opportunity] Dim the porch at night")

    def test_an_excluded_claim_is_still_left_out(self):
        self.cases.list_cases = lambda *a, **k: [
            {"kind": "problem", "claim": "Mine", "entity_id": "sensor.a"}]
        self.assertEqual(self.server._open_case_rows(exclude={"Mine"}), [])


if __name__ == "__main__":
    unittest.main()
