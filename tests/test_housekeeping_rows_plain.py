#!/usr/bin/env python3
"""brAIn's own housekeeping questions are named in words, never by key.

Three findings on a house read "Was this fixed: 70766c7a7025546b (brAIn
3.8.6)" — the development loop's question about whether a fix held, named
by the report's fingerprint with the release as its subject — and another
"Mute suggestion about check:base.unusual", a rule named by its id. Both
were the producer's dedupe key put on the screen.

So the row's `text` (its key, which a loose card and History show) and
everything else a person reads name the report by its own words and where
it was, and the rule by its title; the key the producer needs to find its
row again rides in its own ledger.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"
                       / "panel"))

import mute_offer  # noqa: E402
from devloop import verify  # noqa: E402

HEX = re.compile(r"\b[0-9a-f]{16}\b")
CHECK_ID = re.compile(r"\bcheck:")
VERSION_FIRST = re.compile(r"^\W*(?:brAIn|GardenRX|Morph|BRight|BRUH \w+)? ?"
                           r"\d+\.\d+\.\d+")
ENTRY = {"fp": "70766c7a7025546b", "fixed_in": "3.8.6", "stream": "look",
         "where": "Today", "what": "the morning brief never mentions the boiler"}


def lint(row: dict) -> list[str]:
    bad = []
    for field in ("text", "claim", "detail"):
        said = str(row.get(field) or "")
        for pat in (HEX, CHECK_ID, VERSION_FIRST):
            m = pat.search(said)
            if m:
                bad.append(f"{field}: {m.group(0)!r} in {said!r}")
    return bad


class TestTheFixQuestionIsNamedInWords(unittest.TestCase):
    def test_no_fingerprint_and_no_release_as_its_subject(self):
        self.assertEqual(lint(verify.question_row(ENTRY)), [])

    def test_it_names_the_report_and_where_it_was(self):
        row = verify.question_row(ENTRY)
        self.assertIn("never mentions the boiler", row["claim"])
        self.assertIn("Today", row["claim"])

    def test_its_row_is_found_again_without_parsing_its_words(self):
        row = verify.question_row(ENTRY)
        state = verify.record_asked({}, ENTRY["fp"], 42, "3.8.6", 0,
                                    text=row["text"])
        self.assertEqual(verify.fp_for_finding(state, {"ts": 7,
                                                       "text": row["text"]}),
                         ENTRY["fp"])
        self.assertEqual(verify.fp_for_finding(state, {"ts": 42}), ENTRY["fp"])

    def test_a_row_filed_the_old_way_is_still_found(self):
        old = {"text": "Was this fixed: 70766c7a7025546b (brAIn 3.8.6)"}
        self.assertEqual(verify.fp_for_finding({}, old), ENTRY["fp"])

    def test_a_new_fix_asks_again(self):
        self.assertNotEqual(verify.question_row(ENTRY)["text"],
                            verify.question_row({**ENTRY,
                                                 "fixed_in": "3.8.7"})["text"])


class TestTheMuteQuestionNamesTheRule(unittest.TestCase):
    def plan(self, **row) -> dict:
        card = [{"source": "check:base.unusual",
                 "title": "Readings far outside their usual band",
                 "total": 6, "wrong": 6, "last": "wrong", **row}]
        [item] = mute_offer.plan(card, {}, 0.0, set(), set())
        return item

    def test_no_rule_id_on_the_row(self):
        self.assertEqual(lint(self.plan()["row"]), [])

    def test_it_names_the_rule_by_its_title(self):
        row = self.plan()["row"]
        self.assertIn("Readings far outside their usual band", row["text"])
        self.assertIn("Readings far outside their usual band", row["claim"])

    def test_its_row_is_found_again(self):
        item = self.plan()
        state = mute_offer.record_asked({}, item["source"], 9, 6, 6, 0.0,
                                        text=item["row"]["text"])
        self.assertEqual(mute_offer.source_for_finding(
            state, {"ts": 1, "text": item["row"]["text"]}),
            "check:base.unusual")
        self.assertEqual(mute_offer.source_for_finding(
            {}, {"text": "Mute suggestion about check:base.unusual"}),
            "check:base.unusual")


if __name__ == "__main__":
    unittest.main()
