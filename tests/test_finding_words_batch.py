#!/usr/bin/env python3
"""Findings and cards worded in one vocabulary.

1. developer words in a check's rows: held by `test_finding_words_sweep`;
2. one vocabulary: the shared prompts name the assistant and the owner one
   way, and no shipped prompt mixes "you" with "the homeowner";
3. a log error's detail says what it means, what it affects and usual
   against now, and never "something it was doing failed";
4. a card's first sentence is its conclusion; an absence of events or a
   closing guess is held back by code.
"""

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "brain" / "panel"))
sys.path.insert(0, str(BASE / "tests"))

import card_claims  # noqa: E402
import categories  # noqa: E402
import house_words  # noqa: E402
import prompt_kit  # noqa: E402
import sre  # noqa: E402


class TestOneVocabulary(unittest.TestCase):
    def test_the_shared_prompt_fixes_the_name_and_the_address(self):
        text = prompt_kit.IDENTITY
        self.assertIn('call it "brAIn"', text)
        self.assertIn('"you" and "your"', text)
        self.assertIn('never "the homeowner"', text)

    def test_the_card_contract_does_not_mix_the_owner_names(self):
        # The contract addresses the reader one way: the household.
        for name in ("the owner", "the user", "the homeowner"):
            self.assertNotIn(name, categories._CARD_CONTRACT.lower(), name)

    def test_one_finding_does_not_switch_voice(self):
        said = house_words.household(
            "The homeowner's plug is off. You can also reset it.")
        self.assertNotRegex(said.lower(), r"homeowner")
        self.assertNotRegex(house_words.household(
            "The owner already said so. Your hub is fine.").lower(), r"owner")


class TestTheCardPromptsNameTheReaderOneWay(unittest.TestCase):
    def test_no_homeowner_or_user_in_a_card_prompt(self):
        for text in (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM,
                     categories.MEMORY_HEAD, categories._CARD_CONTRACT):
            self.assertNotRegex(text, r"(?i)\bthe (?:home ?owner|user)\b")


class TestALogErrorSaysWhatItMeans(unittest.TestCase):
    def test_the_stock_phrase_is_gone(self):
        for message in ("Something odd happened", "", "weird"):
            said = house_words.log_meaning(message)
            self.assertNotIn("something it was doing failed", said)
            self.assertNotRegex(said, r"[0-9{}]")

    def test_the_flood_check_says_meaning_effect_and_usual(self):
        from test_house_checks import NOW as CNOW, house
        from checks import integrations
        snap = house()
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": "homeassistant.components.tado", "domain": "tado",
            "count": 1200, "last": CNOW, "ips": [],
            "message": "Something odd happened"}]}
        [row] = integrations.log_flood(snap, CNOW)
        self.assertNotIn("something it was doing failed", row["detail"])
        self.assertIn("1200 times", row["detail"])
        self.assertIn("Usually", row["detail"])
        self.assertIn("may not update", row["detail"])

    def test_a_second_example_the_night_check(self):
        logs = [{"message": "Something odd happened", "count": 12,
                 "last_hours_ago": 2.0, "integration": "tado"}]
        said = sre._log_said(logs, {"names": {}})
        self.assertNotIn("something it was doing failed", said)
        self.assertIn("well above", said)
        self.assertIn("may not update", said)


class TestACardLeadsWithItsConclusion(unittest.TestCase):
    def test_the_contract_asks_for_the_conclusion_then_usual_against_now(self):
        for text in (categories._CARD_CONTRACT, categories.SYSTEM_PROMPT,
                     categories.ANALYST_SYSTEM):
            self.assertIn("first sentence is the conclusion", text)
            self.assertIn("usual against now", text)
            self.assertIn("Never end on a guess", text)

    def test_a_card_ending_in_a_guess_loses_the_guess(self):
        out = {"summary": "The freezer held 0 °F, as usual. It may be the "
                          "new door seal."}
        changed = []
        card_claims.trim_guess(out, changed)
        self.assertEqual(out["summary"], "The freezer held 0 °F, as usual.")
        self.assertTrue(changed)

    def test_a_guess_that_carries_an_instruction_stays(self):
        out = {"summary": "The freezer reads 12 degrees above usual. Check "
                          "the door seal now; the door may have been left "
                          "ajar."}
        changed = []
        card_claims.trim_guess(out, changed)
        self.assertIn("may have been left ajar", out["summary"])
        self.assertFalse(changed)

    def test_a_guess_with_a_figure_is_a_reading(self):
        out = {"summary": "Fine. It probably cycled 14 times."}
        card_claims.trim_guess(out, [])
        self.assertIn("14", out["summary"])

    def test_a_card_that_only_reports_an_absence_is_blind(self):
        card = {"title": "Garage door", "summary": "No openings were "
                "recorded today. The sensor stayed closed."}
        self.assertEqual(card_claims.blind_lead(card, "all fine"),
                         "nothing happened")
        # A second example: nothing but a guess.
        guess = {"title": "Hall humidity", "summary": "It may be the "
                 "shower. It could be the dryer."}
        self.assertEqual(card_claims.blind_lead(guess, "all fine"),
                         "an unproven guess")

    def test_a_comparison_makes_it_news(self):
        card = {"title": "Garage door", "summary": "No openings today "
                "against 6 on a usual day."}
        self.assertEqual(card_claims.blind_lead(card, "all fine"), "")




if __name__ == "__main__":
    unittest.main()
