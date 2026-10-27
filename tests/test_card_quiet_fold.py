#!/usr/bin/env python3
"""A card about nothing happening does not take a card's place.

A house's Reports pane was mostly cards saying nothing had happened — "no
cooling since 17 Oct, the next test is the first cooling run" in heating
season, "neither unit has run since", "Verdict: normal" — and the one card
that needed action was lost among them. Now:

* a SCHEDULED card whose verdict is all fine, with nothing to act on and
  nothing changed since the last card, is held: the last card is kept and
  the hold says why (`card_verdict.QUIET_WHY`), the way a card about nothing
  already was; a pressed card is never held;
* a stored card that is all fine about nothing is marked `quiet` and the
  Reports pane folds every such card into one "All quiet" line.

Replaying a set of four quiet cards and one with a real problem lists one
card plus four quiet ones (the pane's line is measured by
`tests/manual/measure-reports.mjs`).
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

from test_card_verdict_post_check import GenerateCase, PREVIOUS  # noqa: E402

QUIET_CARDS = (
    {"title": "Den cooling", "verdict": "all fine",
     "summary": "No cooling since Sat 17 Oct; heating season has begun.",
     "highlights": [{"label": "Cooling", "value": "0 h"}]},
    {"title": "Spare room heaters", "verdict": "all fine",
     "summary": "Neither unit has run since Tue 20 Oct.",
     "highlights": [{"label": "Last run", "value": "Tue 20 Oct"}]},
    # The same figures as the card before it: a steady house said twice.
    {"title": "Dryer vent", "verdict": "all fine",
     "summary": "The vent cleared the drum in 41 min.",
     "highlights": [{"label": "Last dry", "value": "41 min"}]},
)


class TestTheHold(unittest.TestCase):
    def test_all_fine_about_nothing_changed_is_held(self):
        for card in QUIET_CARDS:
            with self.subTest(card=card["title"]):
                got = card_verdict.review(card, PREVIOUS)
                self.assertEqual(got["hold"], card_verdict.QUIET_WHY)

    def test_a_first_card_is_still_the_first_card(self):
        self.assertEqual(card_verdict.review(QUIET_CARDS[0], None)["hold"], "")

    def test_all_fine_with_something_new_is_kept(self):
        card = {"title": "Dryer vent", "verdict": "all fine",
                "summary": "The vent cleared the drum in 38 min, 3 min "
                           "faster than Sat.",
                "highlights": [{"label": "Last dry", "value": "38 min"}]}
        self.assertEqual(card_verdict.review(card, PREVIOUS)["hold"], "")

    def test_something_to_act_on_is_never_held(self):
        for extra in ({"verdict": "worth a look"},
                      {"findings": [{"text": "x", "severity": "warning"}]},
                      {"highlights": [{"label": "Cooling", "value": "0 h",
                                       "status": "warning"}]}):
            with self.subTest(extra=extra):
                card = {**QUIET_CARDS[0], **extra}
                self.assertEqual(card_verdict.review(card, PREVIOUS)["hold"],
                                 "")


class TestThroughGenerate(GenerateCase):
    def test_a_scheduled_quiet_card_keeps_the_last_card_marked_quiet(self):
        before = self.plant_previous()
        self.reply.update(QUIET_CARDS[1])
        stored = self.generate(scheduled=True)
        self.assertEqual(stored["title"], before["title"])
        self.assertTrue(stored["quiet"])
        self.assertEqual(self.server.REFRESH_HOLDS["lighting"]["why"],
                         card_verdict.QUIET_WHY)

    def test_a_pressed_quiet_card_is_stored_and_marked_quiet(self):
        self.plant_previous()
        self.reply.update(QUIET_CARDS[1])
        stored = self.generate(scheduled=False)
        self.assertEqual(stored["title"], QUIET_CARDS[1]["title"])
        self.assertTrue(stored["quiet"])
        self.assertNotIn("lighting", self.server.REFRESH_HOLDS)

    def test_a_card_with_news_is_not_quiet(self):
        self.plant_previous()
        stored = self.generate(scheduled=True)
        self.assertFalse(stored["quiet"])


class TestReplayedSet(GenerateCase):
    """Four quiet cards and one with a real problem."""

    def test_one_card_and_four_quiet(self):
        made = "2026-10-21T08:00:00"
        quiet = [dict(c, id=f"custom-q{i}", category="custom", html="<p>x</p>",
                      generated_at=made, icon="✨", question=None)
                 for i, c in enumerate(QUIET_CARDS)]
        # The steady dryer is quiet only beside the card before it, so it
        # carries the flag `_generate` stored when it was made.
        quiet[2]["quiet"] = True
        # A card stored before the field existed, quiet in its own words.
        quiet.append({"id": "custom-q9", "category": "custom", "icon": "✨",
                      "question": None, "html": "<p>x</p>",
                      "generated_at": made, "title": "Garage door",
                      "summary": "Verdict: normal. Nothing changed since Mon.",
                      "highlights": []})
        problem = {"id": "custom-p", "category": "custom", "icon": "✨",
                   "question": None, "html": "<p>x</p>", "generated_at": made,
                   "title": "Freezer: 9 °F and rising",
                   "verdict": "needs action",
                   "summary": "The garage freezer rose from 0 °F to 9 °F "
                              "since 06:00.",
                   "highlights": [{"label": "Freezer", "value": "9 °F",
                                   "status": "serious"}]}
        for card in quiet + [problem]:
            (Path(self.tmp.name) / f"{card['id']}.json").write_text(
                json.dumps(card), encoding="utf-8")
        resp = asyncio.run(self.server.h_insights(None))
        cards = {i["id"]: i for i in json.loads(resp.text)["insights"]}
        self.assertEqual(sorted(i for i, c in cards.items() if c["quiet"]),
                         ["custom-q0", "custom-q1", "custom-q2", "custom-q9"])
        self.assertFalse(cards["custom-p"]["quiet"])


if __name__ == "__main__":
    unittest.main()
