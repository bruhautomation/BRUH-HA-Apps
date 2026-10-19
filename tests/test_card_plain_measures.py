#!/usr/bin/env python3
"""A card's figure is said in everyday words, and a threshold says whose it is.

Insight cards on a real house invented measures and limits nobody had
defined: "13 lit spells in 17 hours", "door swings", "no safety gap", "the
house mostly coasted", "far over the 350 gal flag" — whose flag? Each is a
word the model coined for something it counted, and the person reading the
card has to guess what was counted. The card contract (`_CARD_CONTRACT`,
shared by both card system prompts) tightens its existing "Plain words"
rule rather than adding a second one: no coined measure, say what happened
("the light came on 13 times"), and a threshold carries its basis ("your
usual limit is 350 gal between cycles"), never a bare "flag".
"""

import sys
import unittest
from pathlib import Path

PANEL_DIR = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import categories  # noqa: E402

CONTRACT = categories._CARD_CONTRACT
SYSTEMS = (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM)


class TestTheContractForbidsCoinedMeasures(unittest.TestCase):
    def rule(self, *phrases):
        for phrase in phrases:
            self.assertIn(phrase, CONTRACT)
            for system in SYSTEMS:
                self.assertIn(phrase, system)

    def test_a_coined_measure_is_named_and_refused(self):
        self.rule("No coined measure", '"lit spells"', '"door swings"',
                  '"safety gap"', '"coasted"')

    def test_the_everyday_words_are_shown(self):
        self.rule('say what happened ("the light came on 13 times")')

    def test_a_threshold_carries_its_basis(self):
        self.rule("A threshold says whose it is",
                  '"your usual limit is 350 gal between cycles"',
                  'never a bare "flag"')

    def test_it_is_one_rule_with_plain_words_not_a_second_copy(self):
        line = next(ln for ln in CONTRACT.splitlines()
                    if ln.startswith("- Plain words:"))
        self.assertIn("No coined measure", line)
        self.assertEqual(CONTRACT.count("No coined measure"), 1)

    def test_the_contract_still_fits_its_ceiling(self):
        self.assertLess(len(CONTRACT), 9100)


if __name__ == "__main__":
    unittest.main()
