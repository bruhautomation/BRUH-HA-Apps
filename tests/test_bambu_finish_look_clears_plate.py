#!/usr/bin/env python3
"""The finish look's own answer about the plate counts.

A print finishes and brAIn is asked for one last look. When that look says the
plate is empty (or lifted out of the printer), the card's "finished print is on
the plate" must clear, not wait for a second look that never comes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_failure_detection import Harness, judge, noisy  # noqa: E402


class TestTheFinishLookAnswersThePlate(Harness):
    def finish_with(self, answer):
        self.start_print()
        self.run_to(2)
        self.grid = noisy(42)  # the printed part is on the plate in the picture
        self.answers = [answer]
        self.client.st.update(state="finish", layer=150)
        self.step(3, every=60)

    def test_an_empty_plate_seen_by_the_finish_look_clears_it(self):
        self.finish_with({"verdict": "cannot_see", "confidence": 0.9, "problem": "none",
                          "summary": "The plate has been lifted out.", "plate": "empty"})
        self.assertEqual(self.pw.plate["state"], "clear")

    def test_a_print_still_there_stays_occupied(self):
        self.finish_with({"verdict": "ok", "confidence": 0.9, "problem": "none",
                          "summary": "Looks like the picture.", "plate": "has_print"})
        self.assertEqual(self.pw.plate["state"], "occupied")

    def test_an_unsure_answer_does_not_clear_it(self):
        self.finish_with({"verdict": "ok", "confidence": 0.3, "problem": "none",
                          "summary": "Maybe empty.", "plate": "empty"})
        self.assertEqual(self.pw.plate["state"], "occupied")

    def test_the_prompts_say_a_lifted_out_plate_is_empty(self):
        self.assertIn("taken out", judge.prompt({}))
        self.assertIn("taken out", judge.plate_prompt({}))
