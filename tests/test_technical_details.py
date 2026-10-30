#!/usr/bin/env python3
"""A card's sentences carry no developer strings; Details keeps them (#563).

Findings about brAIn's own files, voice and checks showed the owner a config
path with a line number, a tool's name, a hex error code and a firmware
build string, and one such finding asked again what a question already
waiting for the owner asked. Now a model-written row's owner-facing fields
(text, claim, detail, fix) lose those strings (`house_words.technical`),
and a look's conclusion loses all but a file name, which
`test_open_row_look_reason` holds on screen: they move to the row's `technical` list, which
the card shows under Details, and a row about brAIn's own setup beside an
open question about it is folded into that question. The strings below are
invented, and the everyday sentences with a version or a time pass as
written.
"""

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
from test_cases import StoresCase  # noqa: E402,F401  (setUp/tearDown)

DEVELOPER = re.compile(
    r"/(?:config|data|opt)/|\.(?:md|ya?ml|json|py)\b|\bline \d+\b"
    r"|\bmcp__|\b0x[0-9a-f]+\b|\bset_assistant_exposure\b|\bget_findings\b"
    r"|-build\.\d+|\+g[0-9a-f]{7}", re.I)

LEAVE_ALONE = [
    "Firmware 1.2 is fine on the gate controller.",
    "The update to 2026.10.1 installed at 0:30.",
    "The pump ran 3.5 hours, from 14:10 to 17:40.",
    "The heater is set to 21.5 degrees.",
    "It reads 0 watts between cycles.",
    "The shed light runs on version 4.2.0 firmware.",
]


class TestTheFloor(unittest.TestCase):
    def test_each_kind_leaves_the_sentence_and_is_kept(self):
        cases_ = {
            "Edit /config/.brain/instructions/garden_voice.md line 14.":
                "/config/.brain/instructions/garden_voice.md line 14",
            "Call set_assistant_exposure to hide it.": "set_assistant_exposure",
            "Use `mcp__ha__get_findings` first.": "mcp__ha__get_findings",
            "The gate hub returned error 0x2f twice.": "0x2f",
            "The hub stopped (0x1a) at night.": "0x1a",
            "It runs firmware 3.1.4-build.8812 now.": "3.1.4-build.8812",
            "It runs firmware 5.0.2+g1a2b3c4d now.": "5.0.2+g1a2b3c4d",
        }
        for said, token in cases_.items():
            with self.subTest(said):
                out, found = house_words.technical(said)
                self.assertNotRegex(out, DEVELOPER)
                self.assertIn(token, found)
                self.assertTrue(out.strip())

    def test_a_build_string_keeps_its_version(self):
        out, _ = house_words.technical("It runs firmware 3.1.4-build.8812 now.")
        self.assertEqual(out, "It runs firmware 3.1.4 now.")

    def test_everyday_sentences_pass_untouched(self):
        for said in LEAVE_ALONE:
            with self.subTest(said):
                self.assertEqual(house_words.technical(said), (said, []))

    def test_the_tool_names_are_the_mcp_servers(self):
        names = house_words.tool_names()
        self.assertIn("set_assistant_exposure", names)
        self.assertIn("get_findings", names)
        # A one-word tool is also an everyday word, and never matched.
        self.assertNotIn("recall", names)


class TestAModelRow(StoresCase):
    def _file(self, **fields):
        [row] = findings_store.add_many([{
            "source": "resident", "severity": "info", **fields}])
        return findings_store.get(row["ts"])

    def test_owner_fields_are_plain_and_details_keep_the_strings(self):
        stored = self._file(
            text="Gate hub reports a fault code",
            detail="The gate hub returned error 0x2f after firmware "
                   "3.1.4-build.8812 went on.",
            fix="Restart the gate hub from its device page.")
        for field in ("text", "detail", "fix"):
            with self.subTest(field=field):
                self.assertNotRegex(stored[field], DEVELOPER)
        self.assertIn("0x2f", stored["technical"])
        self.assertIn("3.1.4-build.8812", stored["technical"])

    def test_the_case_carries_them_for_details(self):
        stored = self._file(text="Gate hub fault", detail="It returned 0x2f.")
        case = cases.get(cases.case_id("findings", stored["ts"]))
        self.assertIsNotNone(case)
        self.assertEqual(case["technical"], ["0x2f"])

    def test_a_looks_conclusion_on_the_card(self):
        [row] = findings_store.add_many([{
            "text": "Gate hub fault again", "detail": "It faulted.",
            "severity": "warning", "source": "check:dev.unavailable"}])
        findings_store.hold_after_look(
            row["ts"], "The hub logged 0x2f once and recovered within a "
            "minute, so nothing needs doing.", run_id="r")
        entry = findings_store.get(row["ts"])
        look = findings_store.shown_look(entry["triage"], entry)
        self.assertNotRegex(look["reason"], DEVELOPER)
        self.assertIn("recovered", look["reason"])

    def test_a_check_row_is_left_as_its_rule_wrote_it(self):
        stored = self._file(text="Kettle plug offline",
                            detail="The plug returned 0x2f.",
                            source="check:dev.unavailable")
        self.assertIn("0x2f", stored["detail"])
        self.assertNotIn("technical", stored)


class TestAQuestionIsNotAskedTwice(StoresCase):
    def test_a_row_about_brains_own_setup_folds_into_the_open_question(self):
        [question] = findings_store.add_many([{
            "text": "Should brAIn's spoken voice stay as it is?",
            "claim": "Should brAIn's spoken voice stay as it is?",
            "kind": "question", "source": "resident", "severity": "info"}])
        self.assertEqual(question["kind"], "question")
        again = findings_store.add_many([{
            "text": "brAIn's personality instructions mention an old voice",
            "detail": "The personality says one voice and the speaker uses "
                      "another.",
            "source": "resident", "severity": "info"}])
        self.assertEqual(again, [])

    def test_a_house_row_about_a_voice_satellite_is_still_filed(self):
        findings_store.add_many([{
            "text": "Should brAIn's spoken voice stay as it is?",
            "claim": "Should brAIn's spoken voice stay as it is?",
            "kind": "question", "source": "resident", "severity": "info"}])
        [row] = findings_store.add_many([{
            "text": "The den voice satellite stopped answering",
            "detail": "It has not answered since 21:40.",
            "source": "resident", "severity": "warning"}])
        self.assertTrue(row)


if __name__ == "__main__":
    unittest.main()
