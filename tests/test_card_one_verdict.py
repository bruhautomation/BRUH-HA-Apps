#!/usr/bin/env python3
"""A card carries ONE verdict, as a chip, and its prose never says it again.

A house's cards wrote their judgement six different ways inside the
summary ("Verdict: normal.", "Needs action.", "Nothing to fix.", "This needs
one change.", "Neither unit is broken.") so the one thing a person scans a
dashboard for was a sentence to read on every card, worded differently on
each. The reply now carries `verdict` from a fixed set (`CARD_SCHEMA`,
`card_verdict.VERDICTS`), the contract says the summary never repeats it,
`card_verdict` takes a verdict sentence off the front of a summary and
reads it as the chip, and a card stored before the field existed is shown
the same way (`card_verdict.legacy`) on the panel and the dashboard page.

Driven through `card_verdict` directly, through the real `_generate` with
the model's reply stubbed, through the real listing and through the real
dashboard page.
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
import categories  # noqa: E402

from test_card_verdict_post_check import GenerateCase, PREVIOUS  # noqa: E402

# Invented cards, one per way a verdict was written into the prose, and
# what each is as a chip.
LEADS = (
    ("Verdict: normal.", card_verdict.FINE),
    ("Needs action.", card_verdict.ACTION),
    ("Nothing to fix.", card_verdict.FINE),
    ("This needs one change.", card_verdict.ACTION),
    ("Neither pump is broken.", card_verdict.FINE),
    # Two the house never wrote, so the reading is of the shape and not of
    # six strings.
    ("The boiler looks fine.", card_verdict.FINE),
    ("Worth a look.", card_verdict.LOOK),
)
REST = "The well pump ran 6 times overnight, 4 min each, against a usual 3."


def card(summary, title="Well pump: 6 runs overnight", **extra):
    return {"title": title, "summary": summary,
            "highlights": [{"label": "Runs", "value": "6"}], **extra}


class TestTheSchemaAndTheContract(unittest.TestCase):
    def test_the_reply_carries_a_verdict_from_the_fixed_set(self):
        prop = categories.CARD_SCHEMA["properties"]["verdict"]
        self.assertEqual(prop["type"], "string")
        self.assertEqual(tuple(prop["enum"]), card_verdict.VERDICTS)
        self.assertIn("verdict", categories.CARD_SCHEMA["required"])

    def test_the_contract_names_it_and_keeps_it_out_of_the_summary(self):
        contract = categories._CARD_CONTRACT
        for system in (contract, categories.SYSTEM_PROMPT,
                       categories.ANALYST_SYSTEM):
            self.assertIn('"verdict": "all fine|worth a look|needs action"',
                          system)
            self.assertIn("the summary never repeats it", system)
            self.assertIn('("Normal.", "Needs action.")', system)
        self.assertIn("never a verdict",
                      categories.CARD_SCHEMA["properties"]["summary"]
                      ["description"])


class TestASentenceThatIsAVerdict(unittest.TestCase):
    def test_each_way_it_was_written_is_read_as_its_chip(self):
        for lead, verdict in LEADS:
            with self.subTest(lead=lead):
                self.assertEqual(card_verdict.verdict_of_sentence(lead),
                                 verdict)

    def test_a_finding_is_not_a_verdict(self):
        for said in (REST, "The pump needs a new float switch by Friday.",
                     "Nothing ran on the kitchen plugs: 0 kWh since Sat."):
            with self.subTest(said=said):
                self.assertEqual(card_verdict.verdict_of_sentence(said), "")

    def test_review_takes_it_off_and_sets_the_chip(self):
        for lead, verdict in LEADS:
            with self.subTest(lead=lead):
                got = card_verdict.review(card(f"{lead} {REST}"), PREVIOUS)
                self.assertEqual(got["obj"]["summary"], REST)
                self.assertEqual(got["obj"]["verdict"], verdict)

    def test_a_field_and_a_sentence_are_one_verdict_not_two(self):
        got = card_verdict.review(
            card(f"Needs action. {REST}", verdict="needs action"), PREVIOUS)
        self.assertEqual(got["obj"]["summary"], REST)
        self.assertEqual(got["obj"]["verdict"], "needs action")

    def test_the_field_wins_over_what_the_prose_said(self):
        got = card_verdict.review(
            card(f"Nothing to fix. {REST}", verdict="worth a look"), PREVIOUS)
        self.assertEqual(got["obj"]["verdict"], "worth a look")
        self.assertEqual(got["obj"]["summary"], REST)

    def test_a_title_ending_in_a_verdict_loses_it(self):
        got = card_verdict.review(card(REST, title="Well pump: normal"),
                                  PREVIOUS)
        self.assertEqual(got["obj"]["title"], "Well pump")
        self.assertEqual(got["obj"]["verdict"], card_verdict.FINE)

    def test_a_summary_that_is_only_an_all_clear_keeps_its_words(self):
        got = card_verdict.review(card("Nothing to fix."), None)
        self.assertEqual(got["obj"]["summary"], "Nothing to fix.")
        self.assertEqual(got["obj"]["verdict"], card_verdict.FINE)

    def test_a_word_outside_the_set_is_no_verdict(self):
        self.assertEqual(card_verdict.clean_verdict("great"), "")
        self.assertEqual(card_verdict.clean_verdict(" Needs Action "),
                         "needs action")


class TestACardStoredBeforeTheField(unittest.TestCase):
    def test_it_is_read_with_one_verdict(self):
        for lead, verdict in LEADS:
            with self.subTest(lead=lead):
                shown = card_verdict.legacy(card(f"{lead} {REST}"))
                self.assertEqual(shown["summary"], REST)
                self.assertEqual(shown["verdict"], verdict)

    def test_a_card_with_the_field_is_shown_as_stored(self):
        shown = card_verdict.legacy(card(REST, verdict="needs action"))
        self.assertEqual(shown["summary"], REST)
        self.assertEqual(shown["verdict"], "needs action")

    def test_a_card_that_says_nothing_of_the_kind_has_no_chip(self):
        shown = card_verdict.legacy(card(REST))
        self.assertEqual(shown["verdict"], "")
        self.assertEqual(shown["summary"], REST)


class TestThroughThePanel(GenerateCase):
    def listing(self):
        resp = asyncio.run(self.server.h_insights(None))
        return {i["id"]: i for i in json.loads(resp.text)["insights"]}

    def test_a_new_card_is_stored_with_its_chip_and_no_verdict_sentence(self):
        self.plant_previous()
        self.reply.update(card(f"This needs one change. {REST}",
                               verdict="needs action"))
        stored = self.generate()
        self.assertEqual(stored["verdict"], "needs action")
        self.assertEqual(stored["summary"], REST)

    def test_a_reply_without_the_field_gets_its_chip_from_its_lead(self):
        self.plant_previous()
        self.reply.update(card(f"Verdict: normal. {REST}"))
        self.reply.pop("verdict", None)
        stored = self.generate()
        self.assertEqual(stored["verdict"], card_verdict.FINE)
        self.assertEqual(stored["summary"], REST)

    def test_an_old_card_is_listed_with_one_verdict(self):
        old = self.plant_previous()
        old["summary"] = f"Neither pump is broken. {REST}"
        self.path.write_text(json.dumps(old), encoding="utf-8")
        listed = self.listing()["lighting"]
        self.assertEqual(listed["verdict"], card_verdict.FINE)
        self.assertEqual(listed["summary"], REST)
        # The file is a record and is not rewritten by being read.
        self.assertIn("Neither pump is broken.",
                      self.path.read_text(encoding="utf-8"))

    def test_the_dashboard_page_shows_the_chip_once(self):
        old = self.plant_previous()
        old["summary"] = f"Needs action. {REST}"
        page = self.server._whole_card_page(old)
        self.assertEqual(page.count('class="vd '), 1)
        self.assertIn(">Needs action</span>", page)
        self.assertNotIn("<b>Needs action.</b>", page)
        self.assertIn("The well pump ran 6 times overnight", page)


if __name__ == "__main__":
    unittest.main()
