#!/usr/bin/env python3
"""A card does not bring back what the household turned down.

A house answered a finding about a double-tap scene turning a room's light
off with "Not interested in this." and an insight card went on saying
"This needs one change" about the same thing. The card's prompt listed
dismissals, but only the newest twenty across the whole house and never by
what the card covers, so on a house that answers things the one about this
card's own light had scrolled off.

Two halves. The prompt hands a card what the household turned down about
the things it covers, with the reason they gave, keyed by entity and
outside the newest-twenty cut; and what the card writes is checked in
code: a finding or an opportunity that matches a settled Wrong — its words,
or the same entity and most of the same words — is dropped before it is
filed or offered. A different problem on the same entity still files.

Driven through the real `_generate` with the model's reply stubbed.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings_store  # noqa: E402

from test_card_findings_clear import ClearCase  # noqa: E402

DECLINED = {"text": "The hallway double-tap scene turns the hallway light off",
            "source": "check:auto.overridden", "entity_id": "light.hallway"}
NOTE = "Not interested in this."


class TurnedDownCase(ClearCase):
    def setUp(self):
        super().setUp()
        findings_store._remember_settled(dict(DECLINED), "ignored",
                                         when=1_000, note=NOTE)
        # A house that answers things: thirty newer Wrongs about other
        # devices push it out of the newest-twenty list every card sees.
        for i in range(30):
            findings_store._remember_settled(
                {"text": f"Plug {i} reads a value nobody expected",
                 "source": "check:dev.frozen",
                 "entity_id": f"sensor.plug_{i}"}, "ignored",
                when=2_000 + i)
        self.reply["findings"] = []
        self.reply["opportunities"] = []


class TestThePromptSaysWhatWasTurnedDown(TurnedDownCase):
    def test_the_cards_own_entity_is_listed_with_the_reason(self):
        self.generate()
        prompt = self.prompts[-1]
        self.assertIn("TURNED DOWN", prompt)
        self.assertIn(DECLINED["text"], prompt)
        self.assertIn(NOTE, prompt)
        self.assertIn("unless something new happened", prompt)
        self.assertIn("light.hallway", prompt)

    def test_the_block_reads_the_ledger_by_what_the_card_covers(self):
        block = findings_store.prompt_block(
            covers={"domains": ["light"], "classes": [], "entities": []})
        head = block.index("TURNED DOWN")
        self.assertIn(DECLINED["text"], block[head:])
        # Said once, under its own heading, not again in the general list.
        self.assertEqual(block.count(DECLINED["text"]), 1)


class TestWhatTheCardWritesIsChecked(TurnedDownCase):
    def test_a_matching_opportunity_and_finding_are_dropped(self):
        self.reply["opportunities"] = [
            {"text": "Make the double-tap scene leave the hallway light on",
             "entities": ["light.hallway"]}]
        self.reply["findings"] = [
            {"text": "The double-tap scene turns off the hallway light",
             "detail": "This needs one change.", "severity": "warning",
             "entity_id": "light.hallway"}]
        card = self.generate()
        self.assertEqual(card["opportunities"], [])
        self.assertEqual(self.queued(), [])
        self.assertEqual(self.card_rows(), [])

    def test_the_same_words_are_dropped_whatever_entity_they_name(self):
        self.reply["findings"] = [dict(DECLINED, source="", severity="info")]
        self.generate()
        self.assertEqual(self.card_rows(), [])

    def test_a_different_problem_on_the_same_light_still_files(self):
        self.reply["findings"] = [
            {"text": "The hallway light has been unavailable since Tue",
             "detail": "unavailable 3 days", "severity": "warning",
             "entity_id": "light.hallway"}]
        self.generate()
        self.assertEqual(len(self.card_rows()), 1)

    def test_the_rule_in_one_place(self):
        self.assertIsNotNone(findings_store.turned_down(
            "Stop the double tap scene turning off the hallway light",
            ["light.hallway"]))
        self.assertIsNone(findings_store.turned_down(
            "Stop the double tap scene turning off the hallway light",
            ["light.porch"]))
        self.assertIsNone(findings_store.turned_down(
            "The hallway light bulb is flickering", ["light.hallway"]))


if __name__ == "__main__":
    unittest.main()
