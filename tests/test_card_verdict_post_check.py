#!/usr/bin/env python3
"""A card's opening verdict is read against the card's own evidence.

Three shapes came back from a real house that the contract alone did not
stop, and each is driven here through `card_verdict.review` and then
through the real `_generate` with the model's reply stubbed:

* "Dryer: no run since Sat, so no new vent reading" opened "The vent looks
  fine": a verdict over nothing new. It says there is nothing new since
  the last card and gives no verdict.
* "Mon morning 193 min vs Sun 112 min" opened "Nothing needs action" and
  then said the room was working harder: the verdict is taken off and the
  figures lead.
* "0 kWh, nothing ran": a scheduled card about nothing is not stored as a
  fresh card. The previous card is kept, the hold says why, and the
  scheduler counts the card's age from the look so the next tick does not
  queue the same run again. A press is never held.

An ordinary card passes untouched.
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

import card_verdict  # noqa: E402
import categories  # noqa: E402
import settings_store  # noqa: E402

PREVIOUS = {"generated_at": "2026-10-17T08:00:00", "title": "Dryer vent",
            "summary": "The vent is clear: 41 min dry on Sat.",
            "highlights": [{"label": "Last dry", "value": "41 min"}]}

DRYER = {"title": "Dryer vent looks fine",
         "summary": "The vent looks fine: no run since Sat, so no new vent "
                    "reading.",
         "highlights": [{"label": "Last run", "value": "Sat 17 Oct",
                         "status": "good"}]}
AIR = {"title": "Air handler: fine",
       "summary": "Fine, nothing points to filter trouble; readings are 3 "
                  "days old.",
       "highlights": [{"label": "Filter pressure", "value": "0.4 inH2O"}]}
HEAT = {"title": "Den heating: nothing needs action",
        "summary": "Nothing needs action — Mon morning 193 min vs Sun 112 min "
                   "to reach 68 °F, so the room is working harder.",
        "highlights": [{"label": "Mon heat-up", "value": "193 min",
                        "delta": "vs 112 min Sun"}]}
QUIET = {"title": "Kitchen plugs: 0 kWh",
         "summary": "Nothing ran on the kitchen plugs: 0 kWh since Sat.",
         "highlights": [{"label": "Kitchen plugs", "value": "0 kWh"}]}
OVERRIDES = {"title": "Bedroom light: only 1 override",
             "summary": "Only 1 override in 48 h, at 07:10 Mon.",
             "highlights": [{"label": "Overrides", "value": "1"}]}
ORDINARY = {"title": "Back door: evening openings 14 → 5",
            "summary": "Evening openings fell from 14 to 5 this week, all "
                       "before 21:00.",
            "highlights": [{"label": "Openings", "value": "5",
                            "delta": "-64% vs last week"}]}


class TestTheReview(unittest.TestCase):
    def test_no_verdict_over_nothing_new(self):
        for card in (DRYER, AIR):
            with self.subTest(card=card["title"]):
                got = card_verdict.review(card, PREVIOUS)
                obj = got["obj"]
                self.assertEqual(got["hold"], "")
                self.assertTrue(obj["summary"].startswith(
                    "Nothing new since Sat 17 Oct"))
                for verdict in ("fine", "nothing points to"):
                    self.assertNotIn(verdict, obj["summary"].lower())
                    self.assertNotIn(verdict, obj["title"].lower())
                self.assertIn("nothing new since Sat 17 Oct", obj["title"])
                self.assertFalse(any(h.get("status") == "good"
                                     for h in obj["highlights"]))

    def test_no_fine_verdict_over_a_rise(self):
        got = card_verdict.review(HEAT, PREVIOUS)
        obj = got["obj"]
        self.assertEqual(got["hold"], "")
        self.assertNotIn("nothing needs action", obj["summary"].lower())
        self.assertNotIn("nothing needs action", obj["title"].lower())
        self.assertTrue(obj["summary"].startswith("Mon morning 193 min"))
        self.assertEqual(obj["title"], "Den heating")

    def test_a_rise_under_half_still_loses_its_opening_reassurance(self):
        # This kept "Nothing needs action —" as the opener when the rise was
        # under half. A card leads with what it found: the reassurance in
        # front of a card that has something to say is the boilerplate
        # seven cards in eleven opened with (`TestNoReassuranceOpener`).
        steady = {**HEAT, "summary": "Nothing needs action — Mon morning "
                  "120 min vs Sun 112 min to reach 68 °F."}
        got = card_verdict.review(steady, PREVIOUS)
        self.assertEqual(got["obj"]["summary"],
                         "Mon morning 120 min vs Sun 112 min to reach 68 °F.")
        self.assertEqual(got["obj"]["title"], "Den heating")

    def test_a_card_about_nothing_is_held(self):
        for card in (QUIET, OVERRIDES):
            with self.subTest(card=card["title"]):
                got = card_verdict.review(card, PREVIOUS)
                self.assertEqual(got["hold"], card_verdict.HOLD_WHY)

    def test_a_first_card_about_nothing_is_still_the_first_card(self):
        self.assertEqual(card_verdict.review(QUIET, None)["hold"], "")

    def test_a_zero_reading_is_not_nothing_happening(self):
        freezer = {"title": "Freezer holding at 0 °F",
                   "summary": "The freezer held 0 °F all week.",
                   "highlights": [{"label": "Freezer", "value": "0 °F"}]}
        self.assertEqual(card_verdict.review(freezer, PREVIOUS)["hold"], "")

    def test_an_ordinary_card_passes_untouched(self):
        got = card_verdict.review(ORDINARY, PREVIOUS)
        self.assertEqual(got, {"obj": ORDINARY, "hold": "", "changed": []})

    def test_the_reply_handed_in_is_not_touched(self):
        before = json.dumps(HEAT, sort_keys=True)
        card_verdict.review(HEAT, PREVIOUS)
        self.assertEqual(json.dumps(HEAT, sort_keys=True), before)


# Seven of eleven cards on a real house opened with the same reassurance,
# and the one card that needed action was lost among them.
REASSURED = (
    ("There's no leak and nothing to fix — the sump ran 4 times overnight, " +
     "12 min each.", "The sump ran 4 times overnight, 12 min each."),
    ("No action. The dryer finished at 14:10 and the drum is still full.",
     "The dryer finished at 14:10 and the drum is still full."),
    ("Normal, nothing to do: the attic fan ran 3 h 10 min on Tue.",
     "The attic fan ran 3 h 10 min on Tue."),
    ("Nothing to fix; the freezer held 0 °F all week.",
     "The freezer held 0 °F all week."),
    ("All good — the front door was locked by 22:15 every night.",
     "The front door was locked by 22:15 every night."),
    ("Nothing to worry about. Hall motion fired 31 times, mostly 07:00–08:00.",
     "Hall motion fired 31 times, mostly 07:00–08:00."),
)


def _card(summary, title="Utility room"):
    return {"title": title, "summary": summary,
            "highlights": [{"label": "Runs", "value": "4"}]}


class TestNoReassuranceOpener(unittest.TestCase):
    def test_the_opening_reassurance_comes_off_a_card_with_content(self):
        for said, kept in REASSURED:
            with self.subTest(said=said):
                got = card_verdict.review(_card(said), PREVIOUS)
                self.assertEqual(got["obj"]["summary"], kept)
                self.assertIn("no opening reassurance", got["changed"])

    def test_a_card_that_is_only_an_all_clear_keeps_it(self):
        for said in ("Nothing to fix.", "No action needed."):
            with self.subTest(said=said):
                got = card_verdict.review(_card(said), None)
                self.assertEqual(got["obj"]["summary"], said)

    def test_a_reassurance_after_the_finding_is_left_where_it_is(self):
        said = "The sump ran 4 times overnight; nothing to fix."
        got = card_verdict.review(_card(said), PREVIOUS)
        self.assertEqual(got["obj"]["summary"], said)

    def test_a_title_that_is_a_reassurance_loses_it(self):
        got = card_verdict.review(
            _card("No action. The sump ran 4 times.", "Sump: nothing to fix"),
            PREVIOUS)
        self.assertEqual(got["obj"]["title"], "Sump")

    def test_a_scheduled_card_whose_news_is_nothing_new_is_held(self):
        for said in ("Nothing new since the dryer finished.",
                     "No change since Tue 13 Oct."):
            with self.subTest(said=said):
                card = {"title": "Dryer", "summary": said,
                        "highlights": [{"label": "Last run",
                                        "value": "Tue 13 Oct"}]}
                self.assertEqual(card_verdict.review(card, PREVIOUS)["hold"],
                                 card_verdict.HOLD_WHY)


# The title holds the headline; the summary's first sentence repeated it.
# A fixture card set: each title, the summary the model wrote, and the
# summary a person reads.
ECHOES = (
    ("Septic pump: 34 h, 143 gal since Thu",
     "It last ran 33 h 55 min ago, with 143 gal since. That is twice its " +
     "usual gap, so the float switch is the first thing to look at.",
     "That is twice its usual gap, so the float switch is the first thing " +
     "to look at."),
    ("Dehumidifiers: 1.2 kWh for 17–23 Oct, down from 49.3",
     "The dehumidifiers used 1.2 kWh over 17–23 Oct, down from 49.3 kWh. " +
     "The basement one has been switched off since Sat 17 Oct.",
     "The basement one has been switched off since Sat 17 Oct."),
    ("Back door: evening openings 14 → 5",
     "Evening openings fell from 14 to 5 this week, all before 21:00.",
     "Evening openings fell from 14 to 5 this week, all before 21:00."),
    ("Garage: 3 openings after 22:00",
     "The garage opened 3 times after 22:00. Each was under 2 min.",
     "Each was under 2 min."),
    ("Freezer: 0 °F all week",
     "The compressor ran 41% of the time to hold 0 °F, up from 30%. The " +
     "seal is the likely cause.",
     "The compressor ran 41% of the time to hold 0 °F, up from 30%. The " +
     "seal is the likely cause."),
)


class TestTheSummaryDoesNotRepeatTheTitle(unittest.TestCase):
    def test_a_first_sentence_that_restates_the_title_is_dropped(self):
        for title, said, kept in ECHOES:
            with self.subTest(title=title):
                card = {"title": title, "summary": said,
                        "highlights": [{"label": "x", "value": "1"}]}
                got = card_verdict.review(card, PREVIOUS)
                self.assertEqual(got["obj"]["summary"], kept)
                self.assertEqual(got["obj"]["title"], title)
                self.assertEqual("the title said twice" in got["changed"],
                                 kept != said)

    def test_the_figures_compared(self):
        self.assertEqual(card_verdict.title_echo(
            "Septic pump: 34 h, 143 gal since Thu",
            "It last ran 33 h 55 min ago, with 143 gal since."), 2)
        self.assertEqual(card_verdict.title_echo(
            "Garage: 3 openings after 22:00", "Each was under 2 min."), 0)


class TestTheContractSaysSo(unittest.TestCase):
    def test_the_two_rules_are_in_the_contract(self):
        contract = categories._CARD_CONTRACT
        self.assertIn('"nothing new since <date>"', contract)
        self.assertIn("rising by more than half", contract)


from test_insights_knowledge import InsightsServerCase  # noqa: E402


class GenerateCase(InsightsServerCase):
    def setUp(self):
        super().setUp()
        self.engine = self.server.engine
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "gather_mode": "snapshot"})
        self.reply = dict(ORDINARY, tags=["doors"],
                          html="<!DOCTYPE html><html><body>ok</body></html>")
        self._olds_gen = (self.ha_data.collect_bundle, self.engine.run_claude,
                      self.engine.get_auth)

        async def fake_collect(category, days, question=None):
            return {"entities": []}

        def fake_run(prompt, *a, **k):
            return {"ok": True, "text": json.dumps(self.reply), "error": "",
                    "meta": {"duration_ms": 5}}

        self.ha_data.collect_bundle = fake_collect
        self.engine.run_claude = fake_run
        self.engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.server.REFRESH_HOLDS.pop("lighting", None)
        self.path = Path(self.tmp.name) / "lighting.json"

    def tearDown(self):
        (self.ha_data.collect_bundle, self.engine.run_claude,
         self.engine.get_auth) = self._olds_gen
        self.server.REFRESH_HOLDS.pop("lighting", None)
        self.server.JOBS.pop("lighting", None)
        super().tearDown()

    def plant_previous(self):
        card = {"id": "lighting", "category": "lighting", "icon": "💡",
                "category_title": "Lighting", "question": None,
                "title": "Back door: evening openings 14 → 9",
                "summary": "Evening openings fell from 14 to 9.",
                "highlights": [{"label": "Openings", "value": "9"}],
                "html": "<p>old</p>",
                "generated_at": "2026-10-17T08:00:00"}
        self.path.write_text(json.dumps(card), encoding="utf-8")
        return card

    def generate(self, scheduled=False):
        self.server.JOBS["lighting"] = {"scheduled": scheduled}
        asyncio.run(self.server._generate("lighting"))
        return json.loads(self.path.read_text(encoding="utf-8"))


class TestThroughGenerate(GenerateCase):
    def test_a_rise_is_stored_without_its_fine_verdict(self):
        self.plant_previous()
        self.reply.update(HEAT)
        card = self.generate()
        self.assertNotIn("nothing needs action", card["summary"].lower())
        self.assertEqual(card["title"], "Den heating")

    def test_a_scheduled_card_about_nothing_keeps_the_previous_card(self):
        before = self.plant_previous()
        self.reply.update(QUIET)
        card = self.generate(scheduled=True)
        self.assertEqual(card["title"], before["title"])
        self.assertEqual(card["generated_at"], before["generated_at"])
        self.assertTrue(card.get("checked_at"))
        self.assertEqual(self.server.REFRESH_HOLDS["lighting"]["why"],
                         card_verdict.HOLD_WHY)
        # The scheduler counts from the look, so the next tick does not
        # queue the same run again.
        self.assertEqual(self.server._due_stamp(card), card["checked_at"])
        self.assertGreater(card["checked_at"], card["generated_at"])

    def test_a_press_is_never_held(self):
        self.plant_previous()
        self.reply.update(QUIET)
        card = self.generate(scheduled=False)
        self.assertEqual(card["title"], QUIET["title"])
        self.assertNotIn("lighting", self.server.REFRESH_HOLDS)

    def test_a_restated_title_and_a_reassurance_are_taken_off_when_stored(self):
        self.plant_previous()
        title, said, kept = ECHOES[0]
        self.reply.update(title=title, summary="Nothing to fix. " + said)
        card = self.generate(scheduled=True)
        self.assertEqual(card["title"], title)
        self.assertEqual(card["summary"], kept)

    def test_an_ordinary_card_is_stored_as_written(self):
        self.plant_previous()
        card = self.generate(scheduled=True)
        self.assertEqual(card["title"], ORDINARY["title"])
        self.assertEqual(card["summary"], ORDINARY["summary"])


if __name__ == "__main__":
    unittest.main()
