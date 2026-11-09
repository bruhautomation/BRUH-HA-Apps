#!/usr/bin/env python3
"""A card whose headline is an open finding's thing is that finding (#759).

A house's gap report: an air handler card led with the coil sensor's
stuck reading while an open finding said the same about the same sensor,
so Reports told it twice. The card also named the outdoor temperature in
passing, and `card_claims.finding_twin` asked that EVERY entity the card
names belong to the finding, so one side remark kept the card a card.

What a card is about is its headline: when every entity its TITLE names
is an open finding's (or on its device), the card is listed `told_in`
that finding and Reports draws it as one "On Needs you" line — one
mention, the finding, with the card one press away. A card whose title
names something the finding does not stays a card.

The second example, never in the issue, is a sump pump and a rain gauge.
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import card_claims  # noqa: E402
import findings_store  # noqa: E402

from test_card_verdict_post_check import GenerateCase  # noqa: E402

COIL = "sensor.air_handler_coil_temperature"
OUTDOOR = "sensor.outdoor_temperature"
SUMP = "switch.sump_pump"
RAIN = "sensor.rain_gauge"

NAMES = {COIL: {"name": "Air handler coil temperature"},
         OUTDOOR: {"name": "Outdoor temperature"},
         SUMP: {"name": "Sump pump"},
         RAIN: {"name": "Rain gauge"}}


class TestTheHeadlineDecides(unittest.TestCase):
    ROWS = [{"ts": 1700000000, "entity_id": COIL, "status": "open"}]

    def test_a_headline_wholly_the_findings_is_that_finding(self):
        row = card_claims.finding_twin({COIL, OUTDOOR}, self.ROWS,
                                       headline={COIL})
        self.assertEqual(row["ts"], 1700000000)

    def test_a_headline_about_more_stays_a_card(self):
        self.assertIsNone(card_claims.finding_twin(
            {COIL, OUTDOOR}, self.ROWS, headline={COIL, OUTDOOR}))
        self.assertIsNone(card_claims.finding_twin(
            {COIL, OUTDOOR}, self.ROWS, headline=set()))


class TestReportsListsItOnce(GenerateCase):
    def setUp(self):
        super().setUp()
        self._names = dict(self.server._NAMES)
        self.server._NAMES.clear()
        self.server._NAMES.update(NAMES)

    def tearDown(self):
        self.server._NAMES.clear()
        self.server._NAMES.update(self._names)
        super().tearDown()

    def listed(self, card_id, title, summary, finding_text, entity):
        card = {"id": card_id, "category": "custom", "icon": "✨",
                "question": None, "html": "<p>x</p>",
                "generated_at": "2026-11-08T08:00:00",
                "title": title, "summary": summary, "highlights": []}
        (Path(self.tmp.name) / f"{card_id}.json").write_text(
            json.dumps(card), encoding="utf-8")
        findings_store.add_many([{
            "text": finding_text, "entity_id": entity,
            "source": "check:x", "severity": "warning"}])
        resp = asyncio.run(self.server.h_insights(None))
        [got] = [i for i in json.loads(resp.text)["insights"]
                 if i["id"] == card_id]
        return got

    def test_the_coil_sensor_is_one_mention(self):
        got = self.listed(
            "custom-coil",
            "Air handler coil temperature: stuck at -40 °F since Tue",
            "The Air handler coil temperature has read -40 °F since Tue "
            "while the Outdoor temperature moved from 31 to 48 °F.",
            "Air handler coil temperature reads -40 °F since Tue", COIL)
        self.assertTrue(str(got.get("told_in") or "").startswith("f:"), got)

    def test_a_sump_pump_beside_its_rain_gauge_is_one_mention(self):
        got = self.listed(
            "custom-sump",
            "Sump pump: 6 runs since 06:00",
            "The Sump pump ran 6 times since 06:00; the Rain gauge read "
            "12 mm.",
            "Sump pump ran 6 times since 06:00", SUMP)
        self.assertTrue(str(got.get("told_in") or "").startswith("f:"), got)

    def test_a_headline_about_both_stays_a_card(self):
        got = self.listed(
            "custom-both",
            "Rain gauge 12 mm and Sump pump 6 runs",
            "The Sump pump kept up with the Rain gauge's 12 mm.",
            "Sump pump ran 6 times since 06:00", SUMP)
        self.assertNotIn("told_in", got)


if __name__ == "__main__":
    unittest.main()
