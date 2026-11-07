#!/usr/bin/env python3
"""Findings and cards worded in one vocabulary.

1. developer words in a check's rows: held by `test_finding_words_sweep`;
2. one vocabulary: the shared prompts name the assistant and the owner one
   way, and no shipped prompt mixes "you" with "the homeowner";
3. a log error's detail says what it means, what it affects and usual
   against now, and never "something it was doing failed";
"""

import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "brain" / "panel"))
sys.path.insert(0, str(BASE / "tests"))

import categories  # noqa: E402
import house_words  # noqa: E402
import prompt_kit  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
