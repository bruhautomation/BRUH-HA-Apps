#!/usr/bin/env python3
"""A finding never tells somebody to type a placeholder (#446).

A fix arrived reading `add wait_template: "a template" (timeout 2 h,
continue_on_timeout)` — the store's door turns template code into the words
"a template", which is right in prose about a trigger and is a hole where a
value belongs in a step somebody is meant to carry out. Every writer of a
finding's fix and detail refuses text holding a placeholder and keeps the
sentence it had: `add_case`, `refine`, `set_fix`, a model-written row in
`add_many`, and the investigation's own parse.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store  # noqa: E402
import house_words  # noqa: E402
import resident  # noqa: E402

HOLED = (
    'Add wait_template: "a template" with a two hour timeout.',
    "Set the threshold to <value> in the automation.",
    "Point the automation at <entity> instead.",
    "Replace YOUR_ENTITY_ID with the hall sensor.",
    "TODO: work out which relay this is.",
    "Set the delay to xxx seconds.",
    "Change the trigger to: … and reload.",
    'Set "brightness" to "…" in the scene.',
    "Change its offset to {{ states('input_number.offset') }} minutes.",
)
FINE = (
    "Replace the coin-cell battery in the garage freezer thermometer.",
    "Its trigger is a template, so brAIn cannot replay it.",
    "Move the hall sensor to the landing and reload the automation.",
    "The relay has been unavailable since 14:10, so restart the hub.",
)
GOOD = "Restart the access point the garage cameras connect through."


class TestWhatAPlaceholderIs(unittest.TestCase):

    def test_each_holed_sentence_is_seen(self):
        for text in HOLED:
            self.assertTrue(house_words.placeholder(house_words.templates(
                text)), text)

    def test_ordinary_sentences_are_not(self):
        for text in FINE:
            self.assertEqual(house_words.placeholder(text), "", text)


class Store(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.INBOX_DIR = root / "inbox"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "none" / ".brain" / "state.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def case(self, fix=GOOD, detail="Four drops today."):
        return findings_store.add_case({
            "text": "The garage cameras keep dropping off the network",
            "claim": "The garage cameras keep dropping off the network",
            "detail": detail, "fix": fix, "kind": "problem",
            "entity_id": "camera.garage_side"})


class TestEveryWriterRefusesOne(Store):

    def test_add_case_files_the_case_without_the_holed_fix(self):
        row = self.case(fix=HOLED[0], detail=HOLED[1])
        self.assertIsNotNone(row)
        self.assertEqual(row["fix"], "")
        self.assertEqual(row["detail"], "")

    def test_refine_keeps_the_sentence_it_had(self):
        row = self.case()
        out = findings_store.refine(row["ts"], {
            "claim": row["claim"], "fix": HOLED[2], "detail": HOLED[3]})
        self.assertEqual(out["fix"], GOOD)
        self.assertEqual(out["detail"], "Four drops today.")

    def test_set_fix_refuses_it(self):
        row = self.case()
        self.assertIsNone(findings_store.set_fix(row["ts"], HOLED[4], "chat"))
        self.assertEqual(findings_store.get(row["ts"])["fix"], GOOD)

    def test_a_model_written_row_is_filed_without_it(self):
        [row] = findings_store.add_many([{
            "text": "The porch light comes on an hour late",
            "detail": "Sunset is at 18:00.", "fix": HOLED[0],
            "severity": "warning", "source": "lighting",
            "entity_id": "light.porch"}])
        self.assertEqual(row["fix"], "")

    def test_the_investigations_parse_drops_it(self):
        got = resident.parse_case({"claim": "The porch light is late",
                                   "fix": HOLED[0], "detail": HOLED[5],
                                   "stakes": "low"})
        self.assertEqual(got["fix"], "")
        self.assertEqual(got["detail"], "")

    def test_the_contract_says_a_fix_names_real_values(self):
        self.assertIn("A fix names real", resident.INVESTIGATE_SYSTEM)
        self.assertIn("placeholder", resident.INVESTIGATE_SYSTEM)


if __name__ == "__main__":
    unittest.main()
