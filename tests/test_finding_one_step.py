#!/usr/bin/env python3
"""A what-to-do is ONE step brAIn has already chosen, never a fork (#536).

Seen on a house: "Either the car has not had its service, or the reminder
was never reset" with a step for each; "Also confirm the voice satellite's
pipeline uses …" about a setting brAIn can read itself; "restore it if
asked" without saying whether anybody will ask. Each hands the household a
decision or a lookup that brAIn had the data to settle, which is the job a
finding exists to take off them.

Two halves, the way placeholders (#446) are held: the finding-writing
prompts say to resolve the fork from what brAIn can read before writing, and
a deterministic floor (`house_words.fork`) refuses a stored `fix` or
`todo_text` that still holds one — the row then keeps the step it had,
exactly as a placeholder is refused. Every example is invented.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import categories  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import prompt_kit  # noqa: E402
import resident  # noqa: E402

FORKS = (
    ("Either the boiler's filter is blocked or the pressure has dropped; "
     + "bleed the radiators or top up the pressure."),
    ("Replace the battery in the shed sensor. Also confirm the hub's channel "
     + "is set to 15."),
    "Restart the doorbell; if not, re-add it to the integration.",
    "Put the old schedule back if asked.",
    "Check whether the porch light's automation is still enabled.",
    "Turn the dehumidifier back on if needed.",
)
ONE_STEP = (
    "Replace the coin-cell battery in the garage freezer thermometer.",
    ("Re-add the doorbell to its integration; it has been unavailable since "
     + "14:10."),
    "Either way the hub is online, so replace the shed sensor's battery.",
    "Move the porch light's schedule to 18:30, after sunset this month.",
    "Nothing is needed: the speaker was switched off at 21:00.",
    "Check the gutter above the back door for leaves.",
)


class TestTheFloor(unittest.TestCase):
    def test_a_fork_is_found(self):
        for text in FORKS:
            self.assertTrue(house_words.fork(text), text)

    def test_a_single_step_is_not(self):
        for text in ONE_STEP:
            self.assertEqual(house_words.fork(text), "", text)

    def test_a_forked_fix_is_refused_where_a_model_row_is_stored(self):
        row = {"source": findings_store.RESIDENT_SOURCE,
               "claim": "The shed sensor stopped reporting",
               "detail": "Either the battery is flat or the hub dropped it; "
                         "its battery read 3% on Tuesday.",
               "fix": FORKS[1], "todo_text": FORKS[2]}
        with mock.patch.object(findings_store, "_names_now", return_value={}), \
                mock.patch.object(findings_store, "_tz_now", return_value=None):
            out = findings_store._plain_row(row)
        self.assertEqual(out["fix"], "")
        self.assertEqual(out["todo_text"], "")
        # The account of what was found may weigh two causes; only the step
        # a person is asked to carry out must be one.
        self.assertTrue(out["detail"])

    def test_a_single_step_survives(self):
        row = {"source": findings_store.RESIDENT_SOURCE,
               "claim": "The shed sensor stopped reporting",
               "fix": ONE_STEP[0]}
        with mock.patch.object(findings_store, "_names_now", return_value={}), \
                mock.patch.object(findings_store, "_tz_now", return_value=None):
            out = findings_store._plain_row(row)
        self.assertEqual(out["fix"], ONE_STEP[0])

    def test_an_investigation_reply_with_a_forked_fix_keeps_its_claim(self):
        case = resident.parse_case({
            "claim": "The car's service reminder is overdue",
            "detail": "The reminder has read overdue since 3 October.",
            "fix": "Either book the service or reset the reminder.",
            "todo_text": "Book the car's service.",
            "confidence": 0.8, "stakes": "low", "kind": "problem",
            "evidence": [], "actions": []})
        self.assertEqual(case["claim"], "The car's service reminder is overdue")
        self.assertEqual(case["fix"], "")
        self.assertEqual(case["todo_text"], "Book the car's service.")


class TestTheChatsDoor(unittest.TestCase):
    """`set_fix` — the chat's "What you'd need to do" — refuses a fork the
    way it refuses a placeholder, and the row keeps the step it had."""

    def test_set_fix_refuses_a_fork(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(findings_store, "FINDINGS_FILE",
                                   Path(tmp) / "findings.json"), \
                    mock.patch.object(findings_store, "SETTLED_FILE",
                                      Path(tmp) / "settled.json"), \
                    mock.patch.object(findings_store, "_names_now",
                                      return_value={}), \
                    mock.patch.object(findings_store, "_tz_now",
                                      return_value=None):
                [row] = findings_store.add_many([{
                    "text": "The shed sensor has not reported in two days",
                    "fix": "Replace the shed sensor's battery.",
                    "severity": "warning", "entity_id": "sensor.shed",
                    "source": "check:dev.frozen"}])
                self.assertIsNone(findings_store.set_fix(
                    row["ts"], "Replace the battery; if not, re-pair it.",
                    "chat"))
                self.assertEqual(findings_store.get(row["ts"])["fix"],
                                 "Replace the shed sensor's battery.")
                self.assertIsNotNone(findings_store.set_fix(
                    row["ts"], "Re-pair the shed sensor with the hub.",
                    "chat"))


class TestThePromptsSayIt(unittest.TestCase):
    def test_the_rule_is_in_every_finding_writing_prompt(self):
        rule = prompt_kit.ONE_STEP
        self.assertIn("either", rule.lower())
        self.assertIn(rule, resident.INVESTIGATE_SYSTEM)
        self.assertIn(rule, resident.REFINE_SYSTEM)
        # The card contract is held under a size ceiling, so it carries the
        # rule in its own short words beside its findings line.
        self.assertIn('"fix" is ONE chosen step, never "either…or"',
                      categories._CARD_CONTRACT)


if __name__ == "__main__":
    unittest.main()
