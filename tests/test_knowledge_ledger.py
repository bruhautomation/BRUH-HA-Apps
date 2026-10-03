#!/usr/bin/env python3
"""The announcement ledger is a dedup index, and an index forgets nothing.

`knowledge_store` keeps the analyst's discoveries capped at `MAX_FACTS` for
the person scrolling them — and the cap took the oldest row out of the
dedup check with it, so the 201st discovery let the first one be announced
again, the one thing the ledger exists to prevent. What leaves the list is
remembered as a short digest. Driven over the real store in a temporary
file. Mutations:

  forget on overflow   drop the digest -> the first fact is new again
  digest unbounded     drop the MAX_SEEN cap -> the file grows for ever
  digest is the text   keep the sentence -> the list again, by another name
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import knowledge_store  # noqa: E402


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (knowledge_store.KNOWLEDGE_FILE, knowledge_store.MAX_FACTS,
                     knowledge_store.MAX_SEEN)
        knowledge_store.KNOWLEDGE_FILE = str(Path(self.tmp.name) / "k.json")
        knowledge_store.MAX_FACTS = 5
        knowledge_store.MAX_SEEN = 12

    def tearDown(self):
        (knowledge_store.KNOWLEDGE_FILE, knowledge_store.MAX_FACTS,
         knowledge_store.MAX_SEEN) = self._old
        self.tmp.cleanup()

    def stored(self) -> dict:
        return json.loads(Path(knowledge_store.KNOWLEDGE_FILE).read_text())


class TestAnAgedOutFactIsStillKnown(LedgerCase):

    def test_the_first_fact_is_not_new_after_the_list_has_moved_on(self):
        first = "The loft loses heat twice as fast as the lounge"
        self.assertTrue(knowledge_store.add_fact(first)[1])
        for i in range(knowledge_store.MAX_FACTS):
            knowledge_store.add_fact(f"Discovery number {i} about the house")
        listed = [f["text"] for f in self.stored()["facts"]]
        self.assertNotIn(first, listed)
        self.assertEqual(len(listed), knowledge_store.MAX_FACTS)
        # A rewording that normalises the same is the same claim.
        _row, created = knowledge_store.add_fact(
            "the loft loses heat twice as fast as the lounge!")
        self.assertFalse(created)
        self.assertNotIn(first, [f["text"] for f in self.stored()["facts"]])

    def test_the_digest_is_not_the_sentence(self):
        knowledge_store.add_fact("A very particular fact about the boiler")
        for i in range(knowledge_store.MAX_FACTS):
            knowledge_store.add_fact(f"Discovery number {i} about the house")
        raw = Path(knowledge_store.KNOWLEDGE_FILE).read_text()
        self.assertNotIn("particular fact about the boiler", raw)
        self.assertEqual(len(self.stored()["seen"]), 1)

    def test_the_digests_are_capped(self):
        for i in range(knowledge_store.MAX_FACTS + 40):
            knowledge_store.add_fact(f"Discovery number {i} about the house")
        self.assertEqual(len(self.stored()["seen"]), knowledge_store.MAX_SEEN)

    def test_an_older_file_with_no_digests_still_loads(self):
        Path(knowledge_store.KNOWLEDGE_FILE).write_text(json.dumps(
            {"facts": [{"ts": 1, "text": "Old fact"}], "questions": []}))
        self.assertFalse(knowledge_store.add_fact("Old fact")[1])
        self.assertTrue(knowledge_store.add_fact("New fact")[1])


if __name__ == "__main__":
    unittest.main()
