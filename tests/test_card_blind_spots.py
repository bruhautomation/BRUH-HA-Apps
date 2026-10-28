#!/usr/bin/env python3
"""A card's main claim is news about the house, never brAIn's blind spot.

A real house's Reports pane carried whole cards that said they had nothing
to say: "Climate air handler: no cooling in 10 days, nothing to compare",
"both doors stayed shut" over "brAIn can't see a reopen after 1 AM", and
"door history after 1:00 AM is missing". And a card about a dehumidifier
reading 0 kWh sat beside a finding about the same dehumidifier with the
same numbers: two items, one story.

The rule is in code where a card is accepted (`card_claims`, called from
`card_verdict.review` and `_generate`), with a contract line to match:

* a card whose main claim (its title) is missing data, no comparison or
  no event, with nothing to act on, is not news: a scheduled one keeps the
  last card, a first or pressed one is stored folded (`blind`, `quiet`);
* on any card a data gap is at most ONE short line, and a tile whose value
  is a gap ("no data") is not a tile;
* a card whose every entity is an open finding's device is drawn as that
  finding (`told_in`), not as a second item.

The examples are not the house's: a pool pump's timer log, a mailbox lid
and a sauna heater, and a garage freezer card beside its finding.
"""

import asyncio
import json
import re
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
import findings_store  # noqa: E402

from test_card_verdict_post_check import GenerateCase  # noqa: E402

PREVIOUS = {"generated_at": "2026-10-20T08:00:00", "title": "Pool pump",
            "summary": "The pool pump ran 6 h 10 min on Mon.",
            "highlights": [{"label": "Runtime", "value": "6 h 10 min"}]}

BLIND = (
    # A data gap as the headline.
    {"title": "Pool pump: the timer log before Monday is missing",
     "summary": "brAIn has runtime only from Mon 26 Oct.",
     "highlights": [{"label": "Runtime", "value": "no data"}]},
    # A non-event as the headline.
    {"title": "Mailbox lid stayed closed all day",
     "summary": "The lid sensor last changed at 05:40.",
     "highlights": [{"label": "Lid", "value": "closed"}]},
    # No comparison as the headline.
    {"title": "Sauna heater: 2 h 5 min on Sat, nothing to compare it with yet",
     "summary": "This is the first week brAIn has the heater's power.",
     "highlights": [{"label": "Sat", "value": "2 h 5 min"}]},
)

NEWS = (
    {"title": "Pool pump: 6 h 10 min, 2 h more than usual",
     "summary": "It ran from 08:00 to 14:10; the usual is about 4 h.",
     "highlights": [{"label": "Runtime", "value": "6 h 10 min"}]},
    # A non-event that is the problem: something to act on.
    {"title": "Sump pump: no runs in 5 days of rain",
     "summary": "It has not run since Thu while 40 mm fell.",
     "highlights": [{"label": "Runs", "value": "0",
                     "status": "warning"}]},
)


class TestTheMainClaim(unittest.TestCase):
    def test_a_gap_a_non_event_or_no_comparison_is_blind(self):
        for card in BLIND:
            with self.subTest(title=card["title"]):
                self.assertTrue(card_claims.blind_lead(card))

    def test_news_is_not_blind(self):
        for card in NEWS:
            with self.subTest(title=card["title"]):
                self.assertFalse(card_claims.blind_lead(card))

    def test_a_scheduled_blind_card_keeps_the_last_card(self):
        for card in BLIND:
            with self.subTest(title=card["title"]):
                got = card_verdict.review(card, PREVIOUS)
                self.assertEqual(got["hold"], card_claims.BLIND_WHY)

    def test_a_first_blind_card_is_stored_folded(self):
        got = card_verdict.review(BLIND[1], None)
        self.assertEqual(got["hold"], "")
        self.assertTrue(got["obj"].get("blind"))
        self.assertTrue(card_verdict.folds_quiet(got["obj"]))

    def test_an_asked_card_is_the_answer_and_never_folded(self):
        # "Did anybody open the mailbox?" — "it stayed closed" IS the answer.
        got = card_verdict.review(BLIND[1], PREVIOUS, asked=True)
        self.assertEqual(got["hold"], "")
        self.assertFalse(got["obj"].get("blind"))

    def test_the_contract_says_it_too(self):
        self.assertIn("never the headline", categories._CARD_CONTRACT)


class TestAGapIsOneShortLine(unittest.TestCase):
    def test_extra_gap_sentences_and_gap_tiles_go(self):
        card = {"title": "Pool pump: 6 h 10 min, 2 h more than usual",
                "summary": ("It ran from 08:00 to 14:10. brAIn can't see the "
                            "timer before Monday. The flow sensor's history "
                            "is missing for Sat and Sun, so there is no "
                            "comparison for the weekend."),
                "highlights": [
                    {"label": "Runtime", "value": "6 h 10 min"},
                    {"label": "Weekend", "value": "no data"},
                    {"label": "Flow", "value": "n/a"}]}
        got = card_verdict.review(card, PREVIOUS)["obj"]
        gaps = [s for s in re.split(r"(?<=[.!?])\s+", got["summary"])
                if card_claims.is_gap(s)]
        self.assertEqual(len(gaps), 1, got["summary"])
        self.assertLessEqual(len(gaps[0]), card_claims.GAP_LINE_MAX)
        self.assertIn("08:00", got["summary"])
        self.assertEqual([h["label"] for h in got["highlights"]], ["Runtime"])


class TestACardAndAFindingAreOneItem(unittest.TestCase):
    ROWS = [{"ts": 1700000000, "entity_id": "sensor.garage_freezer_temp",
             "evidence": [], "status": "open"},
            {"ts": 1700000001, "entity_id": "light.hall", "status": "open"}]
    DEVICES = {"sensor.garage_freezer_temp": "dev-freezer",
               "sensor.garage_freezer_power": "dev-freezer"}

    def twin(self, ents):
        return card_claims.finding_twin(set(ents), self.ROWS,
                                        self.DEVICES.get)

    def test_a_card_wholly_about_a_findings_device_is_that_finding(self):
        row = self.twin(["sensor.garage_freezer_temp",
                         "sensor.garage_freezer_power"])
        self.assertEqual(row["ts"], 1700000000)

    def test_a_card_about_more_than_the_finding_stays_a_card(self):
        self.assertIsNone(self.twin(["sensor.garage_freezer_temp",
                                     "sensor.kitchen_fridge_temp"]))
        self.assertIsNone(self.twin([]))

    def test_the_reports_pane_folds_a_twinned_card(self):
        app = (PANEL_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("told_in", app)


class TestThroughGenerate(GenerateCase):
    def test_a_scheduled_blind_card_keeps_the_last_card(self):
        before = self.plant_previous()
        self.reply.update(BLIND[0])
        stored = self.generate(scheduled=True)
        self.assertEqual(stored["title"], before["title"])
        self.assertEqual(self.server.REFRESH_HOLDS["lighting"]["why"],
                         card_claims.BLIND_WHY)

    def test_a_pressed_blind_card_is_stored_folded(self):
        self.plant_previous()
        self.reply.update(BLIND[2])
        stored = self.generate(scheduled=False)
        self.assertTrue(stored["blind"])
        self.assertTrue(stored["quiet"])

    def test_a_card_and_its_finding_list_as_one(self):
        made = "2026-10-21T08:00:00"
        card = {"id": "custom-f", "category": "custom", "icon": "✨",
                "question": None, "html": "<p>x</p>", "generated_at": made,
                "title": "Garage freezer: 0 kWh since Sat",
                "summary": "sensor.garage_freezer_power read 0 kWh.",
                "highlights": [], "live": ["sensor.garage_freezer_power"]}
        (Path(self.tmp.name) / "custom-f.json").write_text(
            json.dumps(card), encoding="utf-8")
        findings_store.add_many([{
            "text": "Garage freezer has drawn no power since Sat",
            "entity_id": "sensor.garage_freezer_power", "source": "check:x",
            "severity": "warning"}])
        resp = asyncio.run(self.server.h_insights(None))
        [listed] = [i for i in json.loads(resp.text)["insights"]
                    if i["id"] == "custom-f"]
        self.assertTrue(str(listed.get("told_in") or "").startswith("f:"))


if __name__ == "__main__":
    unittest.main()
