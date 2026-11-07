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

    def _flood(self, domain="tado", logger=None, **group):
        from test_house_checks import NOW as CNOW, house
        from checks import integrations
        snap = house()
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": logger or f"homeassistant.components.{domain}",
            "domain": domain, "count": 1200, "last": CNOW, "ips": [],
            "message": "Something odd happened", **group}]}
        return integrations.log_flood(snap, CNOW)[0]["detail"]

    def test_the_flood_check_compares_only_with_its_filing_point(self):
        detail = self._flood()
        self.assertNotIn("something it was doing failed", detail)
        self.assertIn("1200 times", detail)
        self.assertNotIn("handful", detail)
        self.assertNotIn("Usually", detail)
        self.assertIn("point at which brAIn files it", detail)

    def test_no_clause_about_updating_for_a_library(self):
        detail = self._flood(domain="", logger="urllib3.connectionpool")
        self.assertNotIn("may not update", detail)
        self.assertNotRegex(detail, r"[a-z,;] (?:The|A|An) ")

    def test_an_integration_by_name_still_says_what_it_affects(self):
        self.assertIn("Until it stops, Tado may not update.", self._flood())

    def test_a_named_device_is_what_the_line_is_about(self):
        from test_house_checks import NOW as CNOW, house
        from checks import integrations
        snap = house()
        eid = next(iter(snap["states"]))
        snap["devices"].append({"id": "dev-x", "name": "Kitchen blind"})
        snap["entities"].append({"entity_id": eid, "platform": "tado",
                                 "device_id": "dev-x"})
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": "homeassistant.components.tado", "domain": "tado",
            "count": 1200, "last": CNOW, "ips": [],
            "message": f"Error talking to {eid}"}]}
        rows = integrations.log_flood(snap, CNOW)
        if rows and "Kitchen blind" in rows[0]["detail"]:
            self.assertIn("It is about Kitchen blind.", rows[0]["detail"])
            self.assertNotIn("It affects", rows[0]["detail"])

    def test_a_second_example_the_night_check(self):
        logs = [{"message": "Something odd happened", "count": 12,
                 "last_hours_ago": 2.0, "integration": "tado"}]
        said = sre._log_said(logs, {"names": {}})
        self.assertNotIn("something it was doing failed", said)
        self.assertNotIn("A few of these", said)
        self.assertIn("past 5", said)


if __name__ == "__main__":
    unittest.main()
