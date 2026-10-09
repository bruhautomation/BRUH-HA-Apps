#!/usr/bin/env python3
"""A question card says it is a question.

A guess brAIn wants confirmed (Yes / No / Snooze) wore the "Suggestion"
chip beside the proposals, which ask for an Apply — two different asks
under one word. `answers.chip` stamps "question" on a question case, the
panel's word for it is "Question", and every other card keeps the four it
had: Urgent, Problem, Tidy-up, Suggestion.
"""

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import answers  # noqa: E402


def case(**over):
    base = {"id": "f:1", "kind": "problem", "origin": {"store": "findings", "key": 1},
            "severity": "warning", "source": "check:dev.frozen"}
    base.update(over)
    return base


class TestAQuestionWearsItsOwnChip(unittest.TestCase):
    def test_a_hypothesis_is_a_question(self):
        kase = case(id="h:5", kind="question",
                    origin={"store": "hypotheses", "key": 5})
        self.assertEqual(answers.chip(kase), "question")
        self.assertEqual(answers.CHIP_WORDS["question"], "Question")
        self.assertIn("question", answers.CHIPS)

    def test_a_question_the_resident_filed_is_a_question_too(self):
        self.assertEqual(answers.chip(case(kind="question")), "question")

    def test_urgent_still_wins(self):
        self.assertEqual(answers.chip(case(kind="question"), urgent=True), "urgent")

    def test_everything_else_keeps_its_chip(self):
        self.assertEqual(answers.chip(case(kind="opportunity",
                                           origin={"store": "proposals", "key": 2})),
                         "suggestion")
        self.assertEqual(answers.chip(case()), "problem")
        self.assertEqual(answers.chip(case(severity="info")), "tidy")

    def test_the_panel_has_a_word_for_it(self):
        app = (PANEL_DIR / "app.js").read_text(encoding="utf-8")
        words = re.search(r"const CHIP_WORDS = \{(.*?)\};", app, re.S)
        self.assertIsNotNone(words)
        self.assertIn('question: "Question"', words.group(1))
        # The card drawn for a question no case covers wears it too.
        loose = re.search(r"function makeLooseQuestion\(h\) \{(.*?)\n\}", app, re.S)
        self.assertIsNotNone(loose)
        self.assertIn('chip: "question"', loose.group(1))


if __name__ == "__main__":
    unittest.main()
