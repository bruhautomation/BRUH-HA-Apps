#!/usr/bin/env python3
"""What the October walkthrough found brAIn being told, and not told.

Every case here is a prompt or a page built the way production builds it,
read for the sentence that was missing:

  * D3 — a card compared a week of readings against a week that was
    mostly empty, and credited the dehumidifier with a fall while a
    question about somebody switching it to continuous sat unread. The
    card contract says empty periods are missing, not zero, and the open
    questions reach the card's prompt.
  * D4 — findings called each other "signal 7". The card contract and
    both Resident prompts forbid brAIn's own numbering.
  * D7 — the first look called a Wemo plug "no known critical load" while
    an automation ran the crawl-space fan through it. The automations
    that name an entity reach the look and the investigation.
  * D10 — the brief told somebody to switch off a switch labelled Always
    On, in two clock formats. Labels and facts for the brief's subjects
    reach its prompt, and one clock format is named.
  * D12 — the house book cited its own question's wrapper, a standby
    reading as typical, and one setpoint three times.
  * D14 — a dashboard card ten days old said so in 11px, in a frame a
    third of its height.
"""

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import brief  # noqa: E402
import categories  # noqa: E402
import house_book  # noqa: E402
import hypotheses  # noqa: E402
import resident  # noqa: E402


CATEGORY = {"id": "energy", "title": "Energy", "focus": "Where the power goes."}


class TestTheCardContract(unittest.TestCase):
    def test_empty_days_are_missing_data_not_zero(self):
        contract = categories._CARD_CONTRACT
        self.assertIn("NO samples is missing data, never zero", contract)
        self.assertIn("leave it out of BOTH sides", contract)
        for system in (categories.SYSTEM_PROMPT, categories.ANALYST_SYSTEM):
            self.assertIn("missing data, never zero", system)

    def test_internal_numbers_are_never_cited(self):
        self.assertIn("\"signal 7\"", categories._CARD_CONTRACT)

    def test_open_questions_reach_both_prompt_builders(self):
        block = ("OPEN QUESTIONS waiting on the homeowner (unconfirmed):\n"
                 "- Somebody switched the upstairs dehumidifier to continuous?")
        snap = categories.build_prompt(CATEGORY, {"entities": []},
                                       pending=block)
        search = categories.build_orientation_prompt(
            CATEGORY, {"domains": {}}, pending=block)
        for prompt in (snap, search):
            self.assertIn("switched the upstairs dehumidifier", prompt)
        self.assertNotIn("OPEN QUESTIONS", categories.build_prompt(
            CATEGORY, {"entities": []}))


class TestOpenQuestionsBlock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = hypotheses.HYPOTHESES_FILE
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "hypotheses.jsonl"

    def tearDown(self):
        hypotheses.HYPOTHESES_FILE = self._old
        self.tmp.cleanup()

    def test_an_empty_queue_is_no_block(self):
        self.assertEqual(hypotheses.prompt_block(), "")

    def test_open_guesses_are_listed_and_settled_ones_are_not(self):
        hypotheses.propose("The upstairs dehumidifier was switched to continuous yesterday?")
        gone = hypotheses.propose("The garage fridge runs 24/7?")
        hypotheses.reject(gone["ts"], "it is unplugged")
        block = hypotheses.prompt_block()
        self.assertIn("switched to continuous", block)
        self.assertNotIn("garage fridge", block)
        self.assertIn("unconfirmed", block)


class TestResidentPrompts(unittest.TestCase):
    ROW = "switch.wemo_mini_1 (Wemo Mini 1): used by automation “Crawl space fan”"

    def test_the_first_look_is_shown_what_uses_a_device(self):
        inputs = {}
        prompt = resident.first_look_prompt(
            ["[check] switch.wemo_mini_1 — unavailable for 2 h"],
            "", [], used_by=[self.ROW], inputs=inputs)
        self.assertIn("WHAT USES THESE DEVICES", prompt)
        self.assertIn("Crawl space fan", prompt)
        self.assertEqual(inputs["used_by"], [self.ROW])
        self.assertNotIn("WHAT USES THESE DEVICES", resident.first_look_prompt(
            ["[check] switch.x — unavailable"], "", []))

    def test_the_investigation_is_shown_it_too(self):
        prompt = resident.investigate_prompt(
            {"subject": "switch.wemo_mini_1"}, used_by=[self.ROW])
        self.assertIn("Crawl space fan", prompt)

    def test_both_systems_refuse_internal_numbers_and_no_load_claims(self):
        self.assertIn('"signal 7"', resident.FIRST_LOOK_SYSTEM)
        self.assertIn('"signal 7"', resident.INVESTIGATE_SYSTEM)
        self.assertIn("no\n  known load", resident.FIRST_LOOK_SYSTEM)
        self.assertIn("USED BY", resident.INVESTIGATE_SYSTEM)


class TestTheBrief(unittest.TestCase):
    def test_clock_style_follows_the_country_then_the_zone(self):
        self.assertEqual(brief.clock_style("US", ""), "12h")
        self.assertEqual(brief.clock_style("gb", "America/New_York"), "24h")
        self.assertEqual(brief.clock_style("", "America/Los_Angeles"), "12h")
        self.assertEqual(brief.clock_style("", "Europe/Berlin"), "24h")
        self.assertEqual(brief.clock_style("", "America/Sao_Paulo"), "24h")

    def test_format_clock(self):
        self.assertEqual(brief.format_clock(23, 28, "12h"), "11:28 PM")
        self.assertEqual(brief.format_clock(0, 5, "12h"), "12:05 AM")
        self.assertEqual(brief.format_clock(12, 0, "12h"), "12:00 PM")
        self.assertEqual(brief.format_clock(23, 28, "24h"), "23:28")

    def test_the_frame_carries_labels_and_one_clock(self):
        state = {"about": ["Lab Bathroom Vanity (switch.lab_bathroom_vanity), "
                           "labels: always on"],
                 "clock_style": "12h"}
        prompt = brief.frame(["Left on overnight: Lab Bathroom Vanity"], state)
        self.assertIn("labels: always on", prompt)
        self.assertIn("12-hour form", prompt)
        self.assertIn("Always On", brief.SYSTEM)
        self.assertIn("ONE format", brief.SYSTEM)


class TestTheHouseBook(unittest.TestCase):
    WRAPPED = ("For the house book, about Downstairs Siren AC mains "
               "disconnected: (The homeowner added: Downstairs is in the "
               "kitchen, up")

    def test_the_wrapper_comes_off_an_old_fact(self):
        self.assertEqual(
            house_book.clean_fact_text(self.WRAPPED),
            "Downstairs Siren AC mains disconnected: Downstairs is in the "
            "kitchen, up")
        self.assertEqual(house_book.clean_fact_text("The boiler is in the loft"),
                         "The boiler is in the loft")

    def test_an_answer_is_filed_as_the_fact_it_is(self):
        self.assertEqual(house_book.answer_fact("Mains valve:", "under the sink"),
                         "Mains valve: under the sink")
        self.assertEqual(house_book.answer_fact(
            "For the house book, about Mains valve:", "under the sink"),
            "Mains valve: under the sink")
        self.assertEqual(house_book.answer_fact("Mains valve:", "  "), "")

    def test_a_question_row_carries_no_wrapper(self):
        rows = house_book.question_rows([{
            "question": "Where is the mains valve?", "why": "",
            "subject": "entity:switch.mains_valve", "label": "Mains valve"}],
            [], 0)
        self.assertEqual(rows[0]["memory_hint"], "Mains valve:")

    def test_citations_that_say_the_same_thing_are_one(self):
        dig = {"index": {"fact:a": "Heating setpoint is 20°C",
                         "fact:b": "heating setpoint is 20 °C.",
                         "automation:x": "Heat in the morning"}}
        got = house_book.parse({"sections": [{"key": "heating", "entries": [{
            "text": "The heating holds 20°C.",
            "sources": [{"kind": "fact", "id": "a"}, {"kind": "fact", "id": "b"},
                        {"kind": "automation", "id": "x"}]}]}]}, dig)
        keys = [s["key"] for s in got["sections"][0]["entries"][0]["sources"]]
        self.assertEqual(keys, ["fact:a", "automation:x"])

    def test_the_book_is_told_a_reading_is_not_typical(self):
        self.assertIn("A reading is not what a thing typically does",
                      house_book.SYSTEM)

    def test_duplicate_facts_are_one_source(self):
        rows = [{"id": "1", "text": "Heating setpoint is 20°C", "subject": ""},
                {"id": "2", "text": "heating setpoint is 20°C.", "subject": ""},
                {"id": "3", "text": self.WRAPPED, "subject": ""}]
        import facts_store
        with patch.object(facts_store, "_load", return_value=rows):
            got = house_book._fact_rows()
        self.assertEqual([r["id"] for r in got], ["2", "3"])
        self.assertNotIn("For the house book", got[1]["text"])


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")


class TestUsedBy(ServerCase):
    def test_automations_and_scripts_name_what_they_use(self):
        snap = {
            "states": {"switch.wemo_mini_1": {"state": "off", "attributes": {
                "friendly_name": "Wemo Mini 1"}}},
            "entities": [], "devices": [], "areas": [],
            "automations": [{"id": "fan", "alias": "Crawl space fan hourly",
                             "actions": [{"action": "switch.turn_on", "target": {
                                 "entity_id": "switch.wemo_mini_1"}}]}],
            "scripts": {"vent": {"alias": "Vent the crawl space", "sequence": [
                {"action": "switch.toggle",
                 "target": {"entity_id": "switch.wemo_mini_1"}}]}},
        }
        old_used, old_names = dict(self.server._USED_BY), dict(self.server._NAMES)
        try:
            self.server._note_registry(snap)
            rows = self.server._used_by_rows(["switch.wemo_mini_1", "light.x"])
        finally:
            self.server._USED_BY.clear()
            self.server._USED_BY.update(old_used)
            self.server._NAMES.clear()
            self.server._NAMES.update(old_names)
        self.assertEqual(len(rows), 1)
        self.assertIn("Wemo Mini 1", rows[0])
        self.assertIn("Crawl space fan hourly", rows[0])
        self.assertIn("Vent the crawl space", rows[0])


class TestBriefSubjects(ServerCase):
    def test_labels_on_the_brief_subjects(self):
        old = dict(self.server._NAMES)
        try:
            self.server._NAMES.clear()
            self.server._NAMES["switch.lab_vanity"] = {
                "name": "Lab Bathroom Vanity", "area": "Lab Bathroom",
                "labels": ["always_on"]}
            state = {"new_findings": [{"entity_id": "switch.lab_vanity",
                                       "text": "on since 23:28"}],
                     "morning": {"left_on": [{"entity_id": "light.hall"}]}}
            subjects = self.server._brief_subjects(state)
            about = self.server._about_lines(subjects)
        finally:
            self.server._NAMES.clear()
            self.server._NAMES.update(old)
        self.assertEqual(subjects, ["switch.lab_vanity", "light.hall"])
        self.assertIn("labels: always on", about[0])


class TestHouseBookAnswerIsFiledClean(ServerCase):
    def test_the_answer_reaches_memory_without_the_wrapper(self):
        filed = []

        async def submit(fact, source="insights", **about):
            filed.append(fact)

        finding = {"ts": 1, "text": "House book: Where is the siren?",
                   "source": house_book.SOURCE, "kind": "question",
                   "memory_hint": "For the house book, about Downstairs Siren:",
                   "entity_id": ""}
        with patch.object(self.server, "_submit_memory", submit), \
                patch.object(self.server.findings_store, "settle_and_clear",
                             lambda *a, **k: None), \
                patch.object(self.server, "_findings_payload", lambda: {}):
            asyncio.run(self.server._end_finding(
                finding, self.server.FINDING_VERBS["confirm"],
                "In the kitchen, up high"))
        self.assertEqual(filed, ["Downstairs Siren: In the kitchen, up high"])


class TestTheMirroredCard(ServerCase):
    INSIGHT = {"id": "custom-1", "title": "Home Battery Levels — 5 Critical",
               "summary": "Five batteries are under 10%. " * 3,
               "highlights": [{"label": f"L{i}", "value": "5%"} for i in range(6)],
               "generated_at": "2026-09-24T10:09:00", "html": "<p>x</p>"}

    def setUp(self):
        # _dashboard_card names the file by the card token, and minting one
        # creates /data/secrets: root's to create here, nobody's on CI.
        self._tmp = tempfile.TemporaryDirectory()
        self._old_token_file = self.server.CARD_TOKEN_FILE
        self.server.CARD_TOKEN_FILE = Path(self._tmp.name) / "secrets" / "card_token"

    def tearDown(self):
        self.server.CARD_TOKEN_FILE = self._old_token_file
        self._tmp.cleanup()

    def test_the_page_says_how_old_it_is(self):
        page = self.server._whole_card_page(self.INSIGHT)
        self.assertIn('id="age"', page)
        self.assertIn('data-made="2026-09-24T10:09:00"', page)
        self.assertIn("days old", page)
        self.assertRegex(page, r"if\(d<2\)\{e\.hidden=true;return;\}")
        # And every card says its age prominently, not only an old one:
        # "Updated 7 h ago" beside the eyebrow, re-worked every minute.
        self.assertIn('id="upd"', page)
        self.assertIn('"Updated "+ago(s)', page)
        self.assertIn("setInterval(tick,60000)", page)
        # The 11px "analysed …" foot is gone; the age line replaced it.
        self.assertNotIn('class="f"', page)

    def test_the_page_fits_its_frame_rather_than_scrolling_inside_it(self):
        page = self.server._whole_card_page(self.INSIGHT)
        # The page is exactly the frame's height with nothing to scroll,
        # and the chart takes what is left — a frame sized to the chart's
        # content inside a fixed-ratio Webpage card was the scrollbar.
        self.assertIn("html,body{margin:0;height:100%;overflow:hidden;", page)
        self.assertIn("flex:1 1 auto!important;min-height:0", page)
        self.assertNotIn("bruh-size", page)
        # The summary clamps at three lines, so it cannot push the chart
        # off the bottom of the card.
        self.assertIn("-webkit-line-clamp:3", page)

    def test_a_whole_card_frame_is_tall_enough_for_the_card(self):
        card = self.server._dashboard_card(self.INSIGHT, True, 90)
        ratio = int(card["aspect_ratio"].rstrip("%"))
        self.assertGreater(ratio, 200)
        self.assertLessEqual(ratio, 300)
        # The chart alone keeps what the panel measured.
        self.assertEqual(self.server._dashboard_card(
            self.INSIGHT, False, 60)["aspect_ratio"], "60%")


if __name__ == "__main__":
    unittest.main()
