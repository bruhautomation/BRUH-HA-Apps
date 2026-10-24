#!/usr/bin/env python3
"""A card never contradicts an open finding about what it covers, and it
compares like with like.

Two things real houses reported about their insight cards:

* #354 — a climate card said "nothing new needs doing" about a
  dehumidifier while an open finding said it had not run though the
  humidity was over its setting; other cards told a finding's story again
  in different words. The card's prompt listed the twelve NEWEST live
  rows whatever the card was about, so on a house with a busy list the
  row about this card's own device was not there to agree with. Rows about
  what the card covers (its domains, its device classes, the entities it
  named last time) now go first, the contract says an open finding is the
  verdict on its device, and `card_verdict` takes a "fine" off a card that
  names a device a live row says is not.
* #351 — "0.43 min per °F below 65 per hour" and "for each kWh the washer
  used, the dryer used 5.9 kWh". The contract says to compare like with
  like in everyday units, raw value beside the claim, and never a made-up
  compound unit.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import card_verdict  # noqa: E402
import categories  # noqa: E402
import findings_store  # noqa: E402

from test_card_findings_clear import ClearCase  # noqa: E402

CONTRACT = categories._CARD_CONTRACT
SYSTEMS = (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM)

DEHUMIDIFIER = {
    "text": "The basement dehumidifier has not run while humidity was over "
            "its setting",
    "detail": "Basement humidity 68 % against a 50 % setting since 06:00; "
              "the dehumidifier drew 0 W.",
    "severity": "warning", "entity_id": "humidifier.basement_dehumidifier",
    "source": "check:base.unusual"}


class TestTheContract(unittest.TestCase):
    def rule(self, *phrases):
        for phrase in phrases:
            self.assertIn(phrase, CONTRACT)
            for system in SYSTEMS:
                self.assertIn(phrase, system)

    def test_an_open_finding_is_the_verdict_on_its_device(self):
        self.rule("an open one about a device this card covers is the "
                  "verdict on it", "point to it in one clause",
                  "never call that device fine")

    def test_like_is_compared_with_like_in_everyday_units(self):
        self.rule("compare like with like in everyday units",
                  "(minutes, °F, kWh per load)",
                  "the raw value beside any claim about it",
                  '"min per °F per hour"', '"kWh of one per kWh of another"')

    def test_the_contract_still_fits_its_ceiling(self):
        self.assertLess(len(CONTRACT), 9100)


class TestTheRowAboutThisCardIsInItsPrompt(ClearCase):
    def setUp(self):
        super().setUp()
        self._names = dict(self.server._NAMES)
        self.server._NAMES.clear()
        self.server._NAMES["humidifier.basement_dehumidifier"] = {
            "name": "Basement dehumidifier", "area": "Basement"}
        findings_store.add_many([dict(DEHUMIDIFIER, status="open")])
        # Twelve newer rows about other things: the cap used to be spent
        # on these before the row this card is about.
        findings_store.add_many([
            {"text": f"Garden light {i} has been on all day",
             "severity": "info", "entity_id": f"light.garden_{i}",
             "source": "check:dev.frozen", "status": "open"}
            for i in range(14)])

    def tearDown(self):
        self.server._NAMES.clear()
        self.server._NAMES.update(self._names)
        super().tearDown()

    def test_a_climate_card_is_shown_the_dehumidifier_row(self):
        self.reply["findings"] = []
        self.generate("climate")
        prompt = self.prompts[-1]
        self.assertIn(DEHUMIDIFIER["text"], prompt)
        self.assertIn("Basement humidity 68 %", prompt)


    def test_the_stored_card_points_to_the_row_rather_than_calling_it_fine(self):
        self.reply.update(title="Basement: nothing needs doing",
                          summary="Nothing needs doing; the Basement "
                                  "dehumidifier ran 3 h yesterday.",
                          findings=[])
        card = self.generate("climate")
        self.assertTrue(card["summary"].startswith("Open finding: "
                                                   + DEHUMIDIFIER["text"]),
                        card["summary"])
        self.assertEqual(card["title"], "Basement")


class TestAFineVerdictOverAnOpenRowIsTakenOff(unittest.TestCase):
    OPEN = [{"text": DEHUMIDIFIER["text"],
             "entity_id": "humidifier.basement_dehumidifier",
             "name": "Basement dehumidifier"}]

    def test_the_verdict_points_to_the_row(self):
        card = {"title": "Basement humidity: nothing needs doing",
                "summary": "Nothing new needs doing; the Basement "
                           "dehumidifier ran 3 h yesterday.",
                "highlights": [{"label": "Basement dehumidifier",
                                "value": "3 h"}]}
        out = card_verdict.review(card, None, open_rows=self.OPEN)
        self.assertNotIn("nothing needs doing", out["obj"]["title"].lower())
        self.assertNotIn("nothing new needs doing",
                         out["obj"]["summary"].lower())
        self.assertIn(DEHUMIDIFIER["text"], out["obj"]["summary"])
        self.assertIn("open finding", " ".join(out["changed"]))

    def test_a_card_about_something_else_is_not_pointed_at_the_row(self):
        # It asserted the summary came back exactly as written, opening
        # "Fine;". That opener is the reassurance a card no longer leads
        # with (`test_card_verdict_post_check.TestNoReassuranceOpener`);
        # what this test is about is that no open finding is dragged in.
        card = {"title": "Bedroom: fine", "summary": "Fine; the bedroom "
                "held 20 °C all night.", "highlights": []}
        out = card_verdict.review(card, None, open_rows=self.OPEN)
        self.assertEqual(out["obj"]["summary"],
                         "The bedroom held 20 °C all night.")
        self.assertNotIn("Open finding", out["obj"]["summary"])
        self.assertNotIn("no fine verdict over an open finding",
                         out["changed"])


if __name__ == "__main__":
    unittest.main()
