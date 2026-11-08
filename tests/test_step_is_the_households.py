#!/usr/bin/env python3
"""What a card says to do is the household's to do, never brAIn's (#736).

A finding told the owner to edit line 27 of one of brAIn's own instruction
files and record it through one of brAIn's tools; another sent them to
check something brAIn reads itself; a third printed "Nothing is needed"
under the what-to-do heading. The step a surface shows
(`findings_store.shown_fix`, read by the list and the feed alike) now
loses every sentence holding a file path, a line number or a tool name,
every sentence asking the household to check what brAIn can read, and a
"nothing is needed" — and a step left with nothing is not shown, so no
heading stands over it. A fix written later from a conversation is stored
in the house's words like any model's, and a Resident case that points at
a line brAIn can find in its own instructions becomes brAIn's own yes/no
question, as a model row already did.
"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import instructions  # noqa: E402
import self_care  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402

DEVELOPER = re.compile(r"\.md\b|\.ya?ml\b|\bline \d+\b|/config/|"
                       r"\bnote_personality_change\b|\bmcp__")


def shown(row):
    return findings_store.shown_fix(row)


class TestTheStepShown(unittest.TestCase):
    def test_a_step_into_brains_own_files_shows_no_path_line_or_tool(self):
        row = {"source": "resident", "fix_by": "resident",
               "fix": "Edit line 27 of chat_identity.md to remove the old "
                      "voice, then call note_personality_change to record "
                      "it. Restart the kitchen speaker."}
        got = shown(row)
        self.assertFalse(DEVELOPER.search(got), got)
        self.assertEqual(got, "Restart the kitchen speaker.")

    def test_a_check_brain_can_read_itself_is_not_a_step(self):
        row = {"source": "sre", "fix_by": "",
               "fix": "Check that the porch light is switched on and "
                      "connected. Replace its bulb."}
        self.assertEqual(shown(row), "Replace its bulb.")

    def test_nothing_is_needed_is_not_shown_as_a_step(self):
        for fix in ("Nothing is needed.",
                    "No action is needed: the heater was off on purpose."):
            for source in ("resident", "check:dev.frozen"):
                self.assertEqual(shown({"source": source, "fix": fix}), "",
                                 (source, fix))

    def test_a_plain_step_is_left_alone(self):
        for row in ({"source": "check:dev.battery_low",
                     "fix": "Replace the battery."},
                    {"source": "resident", "fix_by": "resident",
                     "fix": "Move the hub away from the microwave."}):
            self.assertEqual(shown(row), row["fix"])


class TestTheFeedAndTheList(FoldCase):
    def test_no_heading_over_an_empty_step_on_either_surface(self):
        [row] = findings_store.add_many([{
            "text": "The study heater was off all day",
            "claim": "The study heater was off all day",
            "fix": "Nothing is needed.", "source": "check:dev.frozen",
            "entity_id": "climate.study"}])
        listed = findings_store.listing()["findings"]
        self.assertEqual([f["fix"] for f in listed], [""])
        self.assertEqual([c["fix"] for c in cases.list_cases()], [""])

    def test_a_fix_from_a_conversation_is_stored_in_house_words(self):
        [row] = findings_store.add_many([{
            "text": "The hall motion sensor misses people",
            "source": "check:dev.frozen", "entity_id": "sensor.hall"}])
        got = findings_store.set_fix(
            row["ts"], "Open /config/automations.yaml at line 12 and raise "
            "the timeout. Move the sensor higher on the wall.", "chat")
        self.assertIsNotNone(got)
        self.assertFalse(DEVELOPER.search(got["fix"]), got["fix"])
        self.assertIn("Move the sensor higher", got["fix"])


class TestAResidentCaseAboutItsOwnInstructions(FoldCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self._lines = instructions.override_lines
        lines = ["Speak calmly.", "Your voice is Brian."]
        instructions.override_lines = lambda key: lines
        self.addCleanup(setattr, instructions, "override_lines", self._lines)
        self._hook = findings_store.SELF_CARE
        findings_store.SELF_CARE = self_care.as_question
        self.addCleanup(setattr, findings_store, "SELF_CARE", self._hook)
        self.key = next(iter(instructions.CATALOG))

    def test_it_becomes_brains_own_question_with_a_yes(self):
        row = findings_store.add_case({
            "claim": "brAIn's voice line is out of date",
            "detail": f"Line 2 of {self.key}.md still names the old voice.",
            "fix": f"Edit line 2 of {self.key}.md and call "
                   "note_personality_change.",
            "kind": "problem"}, run_id="r1")
        self.assertIsNotNone(row)
        self.assertEqual(row["source"], self_care.SOURCE)
        self.assertEqual(row["kind"], "question")
        self.assertIn("Shall brAIn take that line out?", row["claim"])
        self.assertEqual(row["fix"], "")


class TestTheHelper(unittest.TestCase):
    def test_it_finds_a_developer_sentence_and_leaves_a_house_one(self):
        self.assertTrue(house_words.developer_sentence(
            "Edit line 4 of house_rules.md."))
        self.assertTrue(house_words.developer_sentence(
            "Use mcp__ha__get_state to read it."))
        self.assertFalse(house_words.developer_sentence(
            "Replace the battery in the hall sensor."))


if __name__ == "__main__":
    unittest.main()
