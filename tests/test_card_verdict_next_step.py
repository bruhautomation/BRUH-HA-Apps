#!/usr/bin/env python3
"""A card that is not fine says what to do; a card about nothing is no card.

A house's design report (#793): insight cards reported non-events and
admitted what they could not check, and opened with a list of what was
ruled out rather than with what to do. The bar:

* every card carries one verdict (all fine / worth a look / needs action),
  and a card whose verdict is not all fine carries ONE next step (`next`),
  taken from the card's own words when the reply left the field out: the
  fix of a finding it filed, the open finding it points to, or a
  suggestion it made — never invented; an all-fine card carries none;
* a card whose only content is that nothing changed is folded into the
  quiet line even when it carries no verdict ("Nothing new since …" is
  the rewrite that takes the verdict off, and it was drawn as a card);
* a card whose whole body is what brAIn could not check is not a card:
  a scheduled one keeps the last card, a first one is folded.

The examples are invented: a water softener, a garage dehumidifier, a
loft fan and a hot tub.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import card_claims  # noqa: E402
import card_verdict  # noqa: E402
import categories  # noqa: E402

from test_card_verdict_post_check import GenerateCase  # noqa: E402

PREVIOUS = {"generated_at": "2026-10-20T08:00:00", "title": "Hot tub",
            "summary": "The hot tub heater ran 3 h 10 min on Mon.",
            "highlights": [{"label": "Heater", "value": "3 h 10 min"}]}


class TestANextStep(unittest.TestCase):
    def test_a_worth_a_look_card_takes_its_findings_fix(self):
        card = {"title": "Garage dehumidifier: 0 kWh since Sat",
                "verdict": "worth a look",
                "summary": "It drew nothing for 3 days while the garage "
                           "sat at 71% humidity.",
                "highlights": [{"label": "Humidity", "value": "71%",
                                "status": "warning"}],
                "findings": [{"text": "Garage dehumidifier draws no power",
                              "fix": "Check that the dehumidifier's plug "
                                     "is switched on.",
                              "severity": "warning"}]}
        got = card_verdict.review(card, PREVIOUS)["obj"]
        self.assertEqual(got["verdict"], card_verdict.LOOK)
        self.assertEqual(got["next"], "Check that the dehumidifier's plug "
                                      "is switched on.")

    def test_its_own_next_step_is_kept(self):
        card = {"title": "Loft fan: 14 h a day, twice the usual",
                "verdict": "needs action", "next": "Lower the loft fan's "
                "humidity limit to 65%.",
                "summary": "It ran 14 h a day this week against about 7 h.",
                "highlights": [{"label": "Runtime", "value": "14 h"}]}
        got = card_verdict.review(card, PREVIOUS)["obj"]
        self.assertEqual(got["next"], "Lower the loft fan's humidity "
                                      "limit to 65%.")

    def test_a_card_pointing_at_an_open_finding_says_to_see_it(self):
        rows = [{"ts": 1, "entity_id": "sensor.hot_tub_temperature",
                 "name": "Hot tub temperature",
                 "text": "Hot tub temperature reads 0 °F since Tue",
                 "fix": "Re-seat the hot tub's temperature probe."}]
        card = {"title": "Hot tub: heater ran 3 h on Mon",
                "summary": "All fine. The Hot tub temperature stayed "
                           "steady and the heater ran 3 h.",
                "highlights": [{"label": "Heater", "value": "3 h"}]}
        got = card_verdict.review(card, PREVIOUS, open_rows=rows)["obj"]
        self.assertEqual(got["verdict"], card_verdict.LOOK)
        self.assertEqual(got["next"], "Re-seat the hot tub's temperature "
                                      "probe.")

    def test_an_all_fine_card_carries_no_next_step(self):
        card = {"title": "Hot tub: heater ran 3 h on Mon, as usual",
                "verdict": "all fine", "next": "Keep an eye on it.",
                "summary": "It ran 3 h against its usual 3 h 10 min.",
                "highlights": [{"label": "Heater", "value": "3 h"}]}
        got = card_verdict.review(card, None)["obj"]
        self.assertNotIn("next", got)

    def test_the_schema_and_the_contract_ask_for_it(self):
        self.assertIn("next", categories.CARD_SCHEMA["properties"])
        self.assertIn('"next"', categories._CARD_CONTRACT)
        self.assertLess(len(categories._CARD_CONTRACT), 9100)


class TestNothingChangedIsNoCard(unittest.TestCase):
    def test_nothing_new_with_no_verdict_folds(self):
        # The "nothing new" rewrite takes the verdict off; the card it
        # leaves is still only that nothing changed.
        card = {"title": "Hot tub: nothing new since Mon 19 Oct",
                "summary": "Nothing new since Mon 19 Oct: the heater last "
                           "ran 3 h 10 min.",
                "highlights": [{"label": "Heater", "value": "3 h 10 min"}]}
        self.assertTrue(card_verdict.folds_quiet(card))

    def test_a_second_shape_with_no_verdict_folds(self):
        card = {"title": "Water softener",
                "summary": "It has not regenerated since Thu 15 Oct.",
                "highlights": [{"label": "Last", "value": "Thu 15 Oct"}]}
        self.assertTrue(card_verdict.folds_quiet(card))

    def test_a_sensor_gone_silent_is_not_folded(self):
        card = {"title": "Porch motion",
                "summary": "It hasn't reported since 3am.",
                "highlights": [{"label": "Last report", "value": "03:00"}]}
        self.assertFalse(card_verdict.folds_quiet(card))

    def test_news_or_a_judgement_is_still_a_card(self):
        news = {"title": "Water softener: 3 regenerations, usually 1",
                "summary": "It regenerated 3 times this week against 1.",
                "highlights": [{"label": "Runs", "value": "3"}]}
        self.assertFalse(card_verdict.folds_quiet(news))
        look = {"title": "Water softener", "verdict": "worth a look",
                "summary": "It has not regenerated since Thu 15 Oct.",
                "highlights": []}
        self.assertFalse(card_verdict.folds_quiet(look))


class TestACheckThatCouldNotBeDone(unittest.TestCase):
    GAPS = {"title": "Water softener regeneration",
            "summary": "brAIn could not read the softener's salt level. "
                       "Its regeneration history is missing for the week.",
            "highlights": [{"label": "Salt", "value": "no data"}]}

    def test_a_body_of_only_gaps_is_blind(self):
        self.assertTrue(card_claims.blind_lead(self.GAPS))

    def test_a_scheduled_one_keeps_the_last_card(self):
        got = card_verdict.review(self.GAPS, PREVIOUS)
        self.assertEqual(got["hold"], card_claims.BLIND_WHY)

    def test_a_first_one_is_folded(self):
        got = card_verdict.review(self.GAPS, None)
        self.assertTrue(card_verdict.folds_quiet(got["obj"]))

    def test_a_gap_beside_a_real_reading_is_still_a_card(self):
        card = dict(self.GAPS, highlights=[{"label": "Salt", "value": "40%"}])
        self.assertFalse(card_claims.blind_lead(card))


class TestThroughGenerate(GenerateCase):
    def test_the_next_step_is_stored(self):
        self.plant_previous()
        self.reply.update(
            title="Back door: evening openings 14 → 25",
            verdict="needs action",
            summary="Evening openings rose from 14 to 25, most after 22:00.",
            next="Check the back door's latch closes on its own.")
        card = self.generate(scheduled=False)
        self.assertEqual(card["verdict"], card_verdict.ACTION)
        self.assertEqual(card["next"],
                         "Check the back door's latch closes on its own.")


if __name__ == "__main__":
    unittest.main()
