#!/usr/bin/env python3
"""A finding that says two readings disagree is judged on the disagreement.

Reported from a real house: several "cooling time yesterday reads 0" rows
were held with a reason like "zero cooling in late September is normal for
the season" — while the row's own detail said the air conditioning ran for
hours that same day and the sensor still read 0. The claim was the mismatch
between two pieces of evidence; the reviewer judged one number. The look and
the investigation are now told, in the prompts they are actually sent, that
the claim is what is judged, that a reason explaining one reading does not
answer a disagreement between two, and that a dismissal may never contradict
evidence the finding itself states.

Driven through the real prompt builders, and through the real loop for the
first look (the system prompt the CLI was handed, not the constant).
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import resident  # noqa: E402
from test_resident_loop import LoopCase, reply  # noqa: E402

MISMATCH = ("Cooling hours yesterday reads 0 although the air conditioning "
            "ran for several hours")


class TestTheLookIsToldToJudgeTheClaim(LoopCase):

    def test_the_first_look_the_cli_was_handed_carries_the_rule(self):
        self.file_check_row(text=MISMATCH, source="hvac",
                            entity_id="sensor.example_cooling_hours",
                            detail="the climate entity was cooling for hours")
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "normal for the season"}]))
        self.tick()
        [call] = self.look_calls
        system = call["system"]
        self.assertIn(resident.CLAIM_RULE, system)
        # And the row's own evidence rides in the batch it judged.
        self.assertIn("cooling for hours", call["prompt"])

    def test_the_investigation_the_cli_was_handed_carries_the_rule(self):
        self.file_check_row(text=MISMATCH, source="hvac",
                            entity_id="sensor.example_cooling_hours",
                            detail="the climate entity was cooling for hours")
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "two readings disagree"}]))
        self.investigations.append({"ok": True, "error": "",
                                    "text": json.dumps({"claim": ""}),
                                    "meta": {"session_id": "inv-1"}})
        self.tick()
        [call] = self.analyst_calls
        self.assertIn(resident.CLAIM_RULE, call["system"])
        self.assertIn(resident.DISMISS_RULE, call["prompt"])


class TestTheLookSeesTheEvidence(unittest.TestCase):
    """The detail a filed row rests on rode as evidence AFTER its title and
    sentence, and those alone filled the row's character budget — so the
    look judged "reads 0" without "while the air conditioning ran"."""

    def row(self, **extra):
        import signals
        sig = signals.make(
            "check", "sensor.example_cooling_hours", now=1000.0,
            text="Some check title [warning]: " + MISMATCH + " " + "x" * 60,
            evidence=[signals.evidence_row(
                "sensor.example_cooling_hours", "cooling ran 3.7 h", 1000.0)])
        return signals.prompt_rows([{**sig, **extra}], 1000.0)[0]

    def test_a_filed_rows_detail_is_never_cut_by_its_own_title(self):
        self.assertIn("cooling ran 3.7 h", self.row(finding_ts=1))

    def test_a_live_signal_keeps_the_ordinary_budget(self):
        import signals
        self.assertLessEqual(len(self.row()), signals.ROW_CHARS)


class TestTheRuleSaysWhatItMeans(unittest.TestCase):

    def test_the_rule_names_the_mismatch_and_the_dismissal(self):
        rule = resident.CLAIM_RULE.lower()
        self.assertIn("claim", rule)
        self.assertIn("disagree", rule)
        self.assertIn("contradict", rule)

    def test_a_refining_prompt_puts_the_rule_beside_the_row(self):
        prompt = resident.investigate_prompt(
            {"kind": "check", "subject": "sensor.x", "text": MISMATCH},
            refining={"text": MISMATCH, "detail": "it ran for hours"})
        row_at = prompt.index(MISMATCH)
        self.assertGreater(prompt.index(resident.DISMISS_RULE), row_at)

    def test_a_signal_with_no_row_is_not_told_about_dismissing_one(self):
        prompt = resident.investigate_prompt(
            {"kind": "state", "subject": "light.x", "text": "on"})
        self.assertNotIn(resident.DISMISS_RULE, prompt)


if __name__ == "__main__":
    unittest.main()
