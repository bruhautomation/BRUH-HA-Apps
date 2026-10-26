#!/usr/bin/env python3
"""Two cards about one device or system tell one story.

A house had a water card titled about a garden hose whose summary opened
on the septic pump's figure (48 gal beside the pump card's own 50 gal), and
a new heat card beside an older air-handler card still worded as live about
the same heat pump. Three things now hold:

* a run is handed the other cards about the same device or system first and
  in full — their figures and when they were read — and told to quote them
  or say why its own differ (`server._other_cards_block`);
* a card whose whole subject a newer card covers (each entity it names is
  one the newer names, or on a device the newer names) is marked
  `superseded_by` and the panel folds it under the newer one;
* a first sentence about another card's subject, and nothing else this
  card names, is not the card's lead (`card_verdict.review(others=)`).

Invented examples only: a well pump and a garden tap, a heat pump's two
sensors, and a second pair (a freezer) the issue never mentioned.
"""

import asyncio
import json
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import card_verdict  # noqa: E402

from test_card_findings_clear import ClearCase  # noqa: E402

NAMES = {
    "sensor.well_pump_water": {"name": "Well pump water", "device": "dev-well"},
    "sensor.garden_tap_flow": {"name": "Garden tap flow", "device": "dev-tap"},
    "sensor.heat_pump_runtime": {"name": "Heat pump runtime",
                                 "device": "dev-hp"},
    "sensor.heat_pump_supply": {"name": "Heat pump supply air",
                                "device": "dev-hp"},
    "sensor.chest_freezer_temp": {"name": "Chest freezer temperature",
                                  "device": "dev-fz"},
    "sensor.chest_freezer_power": {"name": "Chest freezer power",
                                   "device": "dev-fz"},
}


def stored(cid, title, summary, made, highlights=(), category=None):
    return {"id": cid, "category": category or cid, "icon": "💧",
            "category_title": cid.title(), "question": None,
            "title": title, "summary": summary,
            "highlights": list(highlights), "html": "<p>x</p>",
            "generated_at": made}


class SiblingCase(ClearCase):
    def setUp(self):
        super().setUp()
        self._names = dict(self.server._NAMES)
        self.server._NAMES.clear()
        self.server._NAMES.update(NAMES)
        self.server._NAMED_PATTERN[:] = [None, None, {}]

    def tearDown(self):
        self.server._NAMES.clear()
        self.server._NAMES.update(self._names)
        self.server._NAMED_PATTERN[:] = [None, None, {}]
        super().tearDown()

    def plant(self, card):
        path = Path(self.tmp.name) / f"{card['id']}.json"
        path.write_text(json.dumps(card), encoding="utf-8")

    def listing(self):
        resp = asyncio.run(self.server.h_insights(None))
        return {i["id"]: i for i in json.loads(resp.text)["insights"]}


class TestAnOlderCardIsFoldedUnderTheNewerOne(SiblingCase):
    def test_the_same_device_through_other_sensors(self):
        self.plant(stored("lighting", "Heat pump runtime: 0 h today",
                          "Heat pump runtime read 0 h by 13:11.",
                          "2026-10-20T13:11:00"))
        self.plant(stored("custom-heat", "Heat pump supply air: 41 °C",
                          "Heat pump supply air held 41 °C; Heat pump "
                          "runtime reached 6 h.", "2026-10-21T09:00:00",
                          category="custom"))
        cards = self.listing()
        self.assertEqual(cards["lighting"].get("superseded_by"), "custom-heat")
        self.assertNotIn("superseded_by", cards["custom-heat"])

    def test_a_second_device_the_issue_never_named(self):
        old = stored("lighting", "Chest freezer power: 90 W",
                     "Chest freezer power averaged 90 W.",
                     "2026-10-20T08:00:00")
        new = stored("custom-fz", "Chest freezer temperature: -18 °C",
                     "Chest freezer temperature held -18 °C.",
                     "2026-10-22T08:00:00", category="custom")
        self.assertEqual(self.server._superseded([old, new]),
                         {"lighting": "custom-fz"})

    def test_a_card_with_more_than_the_newer_covers_stands(self):
        old = stored("lighting", "Water", "Well pump water rose to 50 gal; "
                     "Chest freezer power averaged 90 W.",
                     "2026-10-20T08:00:00")
        new = stored("custom-w", "Well pump water: 50 gal",
                     "Well pump water rose to 50 gal.",
                     "2026-10-22T08:00:00", category="custom")
        self.assertEqual(self.server._superseded([old, new]), {})

    def test_a_card_naming_nothing_is_never_folded(self):
        old = stored("lighting", "Evenings", "Quiet evenings all week.",
                     "2026-10-20T08:00:00")
        new = stored("custom-w", "Well pump water: 50 gal",
                     "Well pump water rose to 50 gal.",
                     "2026-10-22T08:00:00", category="custom")
        self.assertEqual(self.server._superseded([old, new]), {})


class TestTheRunIsToldTheSiblingsFigures(SiblingCase):
    def test_a_card_about_the_same_device_is_listed_with_figures_and_time(self):
        self.plant(stored("custom-pump", "Well pump water: 50 gal",
                          "Well pump water rose to 50 gal since Thu.",
                          "2026-10-21T13:11:00",
                          [{"label": "Water", "value": "50 gal",
                            "delta": "since Thu"}], category="custom"))
        block = self.server._other_cards_block(
            "lighting", {"entities": ["sensor.well_pump_water"]})
        head, _sep, _rest = block.partition("OTHER CARDS ON THIS DASHBOARD")
        self.assertIn("SAME DEVICE OR SYSTEM", head)
        self.assertIn("quote these figures and say the time", head)
        self.assertIn("Water: 50 gal (since Thu)", head)
        self.assertIn("read Wed 21 Oct 13:11", head)

    def test_a_device_shared_through_another_sensor_counts(self):
        self.plant(stored("custom-hp", "Heat pump runtime: 0 h",
                          "Heat pump runtime read 0 h.", "2026-10-21T13:11:00",
                          [{"label": "Runtime", "value": "0 h"}],
                          category="custom"))
        block = self.server._other_cards_block(
            "lighting", {"entities": ["sensor.heat_pump_supply"]})
        self.assertIn("SAME DEVICE OR SYSTEM", block)
        self.assertIn("Runtime: 0 h", block)

    def test_an_unrelated_card_stays_in_the_plain_list(self):
        self.plant(stored("custom-fz", "Chest freezer power: 90 W",
                          "Chest freezer power averaged 90 W.",
                          "2026-10-21T13:11:00", category="custom"))
        block = self.server._other_cards_block(
            "lighting", {"entities": ["sensor.well_pump_water"]})
        self.assertNotIn("SAME DEVICE OR SYSTEM", block)
        self.assertIn("Chest freezer power: 90 W", block)

    def test_the_generating_run_carries_it(self):
        self.plant(stored("custom-pump", "Well pump water: 50 gal",
                          "Well pump water rose to 50 gal.",
                          "2026-10-21T13:11:00",
                          [{"label": "Water", "value": "50 gal"}],
                          category="custom"))
        self.plant(stored("lighting", "Garden tap flow: 48 gal",
                          "Garden tap flow and Well pump water both moved.",
                          "2026-10-20T13:11:00"))
        self.generate()
        self.assertIn("SAME DEVICE OR SYSTEM", self.prompts[-1])
        self.assertIn("Water: 50 gal", self.prompts[-1])


class TestAnotherCardsSubjectIsNotTheLead(unittest.TestCase):
    SUBJECTS = {
        "Well pump water": "sensor.well_pump_water",
        "Garden tap flow": "sensor.garden_tap_flow",
        "Chest freezer power": "sensor.chest_freezer_power",
    }

    def names_in(self, text):
        return {eid for name, eid in self.SUBJECTS.items() if name in text}

    def test_the_hose_card_does_not_open_on_the_pump(self):
        card = {"title": "Garden tap: 48 gal today",
                "summary": "Well pump water rose to 48 gal. Garden tap flow "
                           "ran 22 min after 18:00.",
                "highlights": [{"label": "Garden tap flow", "value": "22 min"}]}
        got = card_verdict.review(card, None, others=[{"sensor.well_pump_water"}],
                                  names_in=self.names_in)
        self.assertEqual(got["obj"]["summary"],
                         "Garden tap flow ran 22 min after 18:00.")
        self.assertIn("another card's subject as the lead", got["changed"])

    def test_a_second_pair(self):
        card = {"title": "Kitchen: 3 kWh",
                "summary": "Chest freezer power averaged 90 W. The oven ran "
                           "twice on Sun.",
                "highlights": [{"label": "Oven", "value": "2 runs"}]}
        got = card_verdict.review(
            card, None, others=[{"sensor.chest_freezer_power"}],
            names_in=self.names_in)
        self.assertEqual(got["obj"]["summary"], "The oven ran twice on Sun.")

    def test_a_card_whose_own_subject_another_card_shares_keeps_its_lead(self):
        card = {"title": "Well pump: 50 gal",
                "summary": "Well pump water rose to 50 gal. It ran 6 times.",
                "highlights": [{"label": "Well pump water", "value": "50 gal"}]}
        got = card_verdict.review(card, None,
                                  others=[{"sensor.well_pump_water"}],
                                  names_in=self.names_in)
        self.assertEqual(got["obj"]["summary"], card["summary"])

    def test_a_one_sentence_card_is_left_alone(self):
        card = {"title": "Garden tap", "summary": "Well pump water rose.",
                "highlights": []}
        got = card_verdict.review(card, None,
                                  others=[{"sensor.well_pump_water"}],
                                  names_in=self.names_in)
        self.assertEqual(got["obj"]["summary"], "Well pump water rose.")


if __name__ == "__main__":
    unittest.main()
