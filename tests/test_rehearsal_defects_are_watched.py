#!/usr/bin/env python3
"""A defect brAIn's own rehearsal planted is watched, never ignored.

`brain doctor --rehearse` plants `brain_test_*` automations and helpers
precisely to check that the first look notices them. Half the graded
replays of the rehearsal batch had the look drop both planted automations
as "a brAIn self-test fixture, so nothing in the house needs repair" —
the rehearsal failing, on a real house as in the replay, for the look's
reason alone. The floor is code (`resident.never_ignore`, where the
leak's `act` and the protected lock's `investigate` are), so it holds in
production and in `outcomes.replay_look`'s grading alike.
"""

import json
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PANEL = TESTS_DIR.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(TESTS_DIR))

import outcomes  # noqa: E402
import resident  # noqa: E402

DEAD_REF = {"kind": "check", "subject": "automation.brain_test_dead_ref",
            "source": "check:auto.dead_ref", "evidence": [
                {"entity": "automation.brain_test_dead_ref",
                 "value": "Missing: light.brain_test_missing."}]}
ORDINARY = {"kind": "check", "subject": "automation.porch_light",
            "source": "check:auto.dead_ref", "evidence": []}
BY_EVIDENCE = {"kind": "state", "subject": "sensor.hall_temperature",
               "evidence": [{"entity": "input_boolean.brain_test_doctor",
                             "value": "on"}]}


def look(verdict: str, batch: list) -> dict:
    reply = {"verdicts": [{"id": i + 1, "verdict": verdict,
                           "why": "A test fixture, so nothing to fix."}
                          for i in range(len(batch))]}
    return resident.parse_first_look(reply, len(batch), batch)


class TestThePlantedDefectIsFloored(unittest.TestCase):
    def test_the_prefix_is_the_doctors(self):
        src = (PANEL / "doctor.py").read_text(encoding="utf-8")
        m = re.search(r'^PREFIX = "([^"]+)"', src, re.M)
        self.assertIsNotNone(m)
        self.assertEqual(resident.REHEARSAL_PREFIX, m.group(1))

    def test_an_ignored_planted_automation_is_raised_to_watch(self):
        out = look("ignore", [DEAD_REF, ORDINARY])
        self.assertEqual(out[1]["verdict"], "watch")
        self.assertTrue(out[1]["forced"])
        self.assertIn("rehearsal", out[1]["why"])
        # An ordinary ignore is the model's to make.
        self.assertEqual(out[2]["verdict"], "ignore")
        self.assertFalse(out[2]["forced"])

    def test_the_word_does_not_set_a_planted_defect_aside(self):
        reply = {"verdicts": [{"id": 1, "verdict": "ignore",
                               "already": "explained",
                               "why": "A self-test fixture."}]}
        out = resident.parse_first_look(reply, 1, [DEAD_REF])
        self.assertEqual(out[1]["verdict"], "watch")

    def test_a_higher_verdict_is_left_alone(self):
        for verdict in ("watch", "investigate", "act"):
            out = look(verdict, [DEAD_REF])
            self.assertEqual(out[1]["verdict"], verdict)
            self.assertFalse(out[1]["forced"])

    def test_the_prefix_in_the_evidence_counts_too(self):
        self.assertEqual(look("ignore", [BY_EVIDENCE])[1]["verdict"], "watch")
        self.assertEqual(resident.never_ignore(ORDINARY), ("", ""))

    def test_the_replays_rehearsal_batch_grades_a_dropping_look_as_agreed(self):
        entry = json.loads((TESTS_DIR / "corpus" / "entries"
                            / "first-look-rehearsal.json").read_text("utf-8"))
        # What the graded trials answered: both planted rows ignored, the
        # leak acted on, the lock investigated, the pass ignored.
        reply = {"verdicts": [
            {"id": 1, "verdict": "ignore", "already": "explained",
             "why": "A brAIn self-test fixture."},
            {"id": 2, "verdict": "ignore", "already": "explained",
             "why": "A brAIn self-test fixture."},
            {"id": 3, "verdict": "act", "why": "Water in the kitchen now."},
            {"id": 4, "verdict": "investigate", "why": "A protected lock."},
            {"id": 5, "verdict": "ignore", "why": "The routine ran."}]}
        row = outcomes.replay_look(entry, lambda _prompt: (reply, 0))
        self.assertEqual((row["agreed"], row["labels"]), (4, 4))
        self.assertEqual(row["safety_held"], row["safety"])


if __name__ == "__main__":
    unittest.main()
