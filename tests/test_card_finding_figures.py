#!/usr/bin/env python3
"""A card and an open finding about the same thing say the same thing.

A house had a card saying a smart plug dropped off 7 times since Saturday
while the open finding about that plug counted 14 times in 7 days, and a
card saying a new interlock automation now handles a case while the open
finding about the same automation still told the owner to add one. Now:

* the card's prompt hands it each open row's figures and window and says a
  count over a different window names its window in words;
* a sentence about a device an open row names whose count disagrees with
  the row's is taken off and the row leads (`card_verdict.disagreeing_row`),
  the chip read as worth a look;
* a card that reads an open row as already fixed — in its `fixed` field or
  in words — has that row's own check asked again (`_rerun_check`), so the
  row clears or is reworded by the rule that filed it.

Driven with a replayed pair through the real `_generate`, the model's reply
stubbed. Invented names: a dehumidifier plug and a sump interlock, plus a
second pair (a well pump's gallons) the issue never mentioned.
"""

import asyncio
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import card_verdict  # noqa: E402
import findings_store  # noqa: E402

from test_card_findings_clear import ClearCase  # noqa: E402

PLUG = {"text": "The Dehumidifier plug keeps dropping off Wi-Fi",
        "detail": "It went offline 14 times in 7 days, last at 03:10.",
        "entity_id": "switch.dehumidifier_plug", "name": "Dehumidifier plug",
        "source": "check:dev.flapping", "ts": 1}
INTERLOCK = {"text": "Nothing stops the sump pump and the drain valve "
                     "running together",
             "detail": "Both ran at once 3 times this week.",
             "entity_id": "automation.sump_interlock", "name": "Sump interlock",
             "source": "check:auto.conflict", "ts": 2}
WELL = {"text": "The Well pump uses more water than usual",
        "detail": "50 gal on Tue against a usual 30 gal.",
        "entity_id": "sensor.well_pump_water", "name": "Well pump",
        "source": "check:base.unusual", "ts": 3}


class TestACountThatDisagrees(unittest.TestCase):
    def test_the_plug_count(self):
        card = {"title": "Utility room: dehumidifier",
                "summary": "The Dehumidifier plug dropped 7 times since Sat. "
                           "Humidity held 52 %.",
                "highlights": [{"label": "Humidity", "value": "52 %"}],
                "verdict": "all fine"}
        got = card_verdict.review(card, None, open_rows=[PLUG])
        obj = got["obj"]
        self.assertNotIn("7 times", obj["summary"])
        self.assertTrue(obj["summary"].startswith(
            "Open finding: The Dehumidifier plug keeps dropping off Wi-Fi."))
        self.assertIn("Humidity held 52 %.", obj["summary"])
        self.assertEqual(obj["verdict"], card_verdict.LOOK)
        self.assertIn("a figure that disagrees with an open finding",
                      got["changed"])

    def test_a_second_count_the_issue_never_named(self):
        card = {"title": "Water", "summary": "The Well pump drew 48 gal on Tue."
                " The garden tap was quiet.", "highlights": []}
        got = card_verdict.review(card, None, open_rows=[WELL])
        self.assertTrue(got["obj"]["summary"].startswith("Open finding:"))
        self.assertNotIn("48 gal", got["obj"]["summary"])

    def test_the_same_count_is_left_alone(self):
        card = {"title": "Utility room",
                "summary": "The Dehumidifier plug went offline 14 times in 7 "
                           "days. Humidity held 52 %.", "highlights": []}
        got = card_verdict.review(card, None, open_rows=[PLUG])
        self.assertEqual(got["obj"]["summary"], card["summary"])

    def test_a_count_about_something_else_is_left_alone(self):
        card = {"title": "Utility room",
                "summary": "The dryer ran 7 times since Sat.", "highlights": []}
        got = card_verdict.review(card, None, open_rows=[PLUG])
        self.assertEqual(got["obj"]["summary"], card["summary"])


class TestAFixAlreadyInPlace(unittest.TestCase):
    def test_the_field_names_it(self):
        card = {"title": "Sump", "summary": "The pump ran 4 times.",
                "fixed": ["automation.sump_interlock"]}
        self.assertEqual(card_verdict.claims_fixed(card, [INTERLOCK, PLUG]),
                         [INTERLOCK])

    def test_words_name_it(self):
        for said in ("The Sump interlock now handles the pump and the valve.",
                     "The Sump interlock has been fixed since Mon."):
            with self.subTest(said=said):
                card = {"title": "Sump", "summary": said}
                self.assertEqual(card_verdict.claims_fixed(card, [INTERLOCK]),
                                 [INTERLOCK])

    def test_a_card_that_claims_nothing(self):
        card = {"title": "Sump", "summary": "The Sump interlock ran twice."}
        self.assertEqual(card_verdict.claims_fixed(card, [INTERLOCK]), [])


class TestThePromptHandsTheFiguresOver(ClearCase):
    def test_the_window_and_the_fixed_field_are_in_the_block(self):
        findings_store.add_many([{
            "text": PLUG["text"], "detail": PLUG["detail"],
            "entity_id": PLUG["entity_id"], "severity": "warning",
            "source": PLUG["source"], "status": "open"}])
        block = findings_store.prompt_block(figures=True)
        self.assertIn("14 times in 7 days", block)
        self.assertIn("says which window, in words", block)
        self.assertIn("lists its entity_id in `fixed`", block)


class TestAReplayedPair(ClearCase):
    """A stored open finding and a card reply about the same automation."""

    def setUp(self):
        super().setUp()
        findings_store.add_many([{
            "text": INTERLOCK["text"], "detail": INTERLOCK["detail"],
            "entity_id": INTERLOCK["entity_id"], "severity": "warning",
            "source": INTERLOCK["source"], "status": "open"}])
        self.asked = []
        self._rerun = self.server._rerun_check

        async def rerun(source):
            self.asked.append(source)
            return {"checked": True, "check": source[6:], "keys": set()}

        self.server._rerun_check = rerun

    def tearDown(self):
        self.server._rerun_check = self._rerun
        super().tearDown()

    def run_card(self):
        async def go():
            await self.server._generate("lighting")
            await asyncio.gather(*list(self.server._CARD_RECHECKS))
        asyncio.run(go())

    def test_a_card_reporting_the_fix_asks_the_rows_check_again(self):
        self.reply.update(title="Sump: 4 runs",
                          summary="The pump ran 4 times, never with the valve.",
                          fixed=["automation.sump_interlock"])
        self.run_card()
        self.assertEqual(self.asked, ["check:auto.conflict"])

    def test_saying_so_in_words_is_the_same(self):
        self.reply.update(title="Sump: 4 runs",
                          summary="The Sump interlock now handles the pump "
                                  "and the valve.")
        self.server._NAMES["automation.sump_interlock"] = {
            "name": "Sump interlock"}
        try:
            self.run_card()
        finally:
            self.server._NAMES.pop("automation.sump_interlock", None)
        self.assertEqual(self.asked, ["check:auto.conflict"])

    def test_a_card_that_does_not_asks_nothing(self):
        self.reply.update(title="Sump: 4 runs",
                          summary="The pump ran 4 times overnight.")
        self.run_card()
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()
