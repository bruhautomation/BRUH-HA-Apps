"""The owner's "is this fixed?" question, through the real panel.

`devloop/verify.py` decides; this drives the server half: the pass files
the question through `findings_store.add_case`, Yes and No end it through
the same case route every card uses, the answer lands on the queue entry
for the send pass to post, the question is settled under the kind no
scorecard counts, nothing reaches the memory inbox, and the toast's Undo
forgets an answer not yet posted.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_dispatch import DispatchCase  # noqa: E402

TOKEN = "github_pat_" + "A1b2C3d4E5f6G7h8I9j0" * 2


class TestTheQuestionThroughThePanel(DispatchCase):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.point("devloop", DATA_DIR=root / "devloop",
                   TOKEN_FILE=root / "secrets" / "devloop_github_token")
        dl = self.server.devloop
        dl.save_settings({"enabled": True, "repo": "me/reports", "review": False})
        dl.save_token(TOKEN)
        self.fp = "ab12cd34ef56ab12"
        dl.upstream._save({"version": "2.17.2", "items": {self.fp: {
            "fp": self.fp, "stream": "look", "state": "sent", "issue": 7,
            "issue_url": "https://github.test/me/reports/issues/7",
            "where": "Looks", "what": "the brief never mentions the boiler",
            "verdict": "fixed", "fixed_in": "2.17.2", "closed_at": time.time() - 3600,
            "version": "2.17.0", "first_seen": time.time() - 86400,
            "last_seen": time.time() - 86400, "seen": 1}}})

    def run_pass(self) -> int:
        return asyncio.run(self.server._devloop_verify_pass())

    def question(self):
        rows = [f for f in self.server.findings_store.list_all()
                if f.get("source") == self.server.devloop.verify.SOURCE]
        return rows[0] if rows else None

    def end(self, case_id, verb, note=""):
        cases = self.server.cases
        ended = cases.end(case_id, verb, note, hooks=self.server.CASE_HOOKS)
        self.assertIsNotNone(ended)
        work = ended.pop("result", None)
        return asyncio.run(work()) if callable(work) else None

    def owner(self) -> dict:
        return (self.server.devloop.upstream._load()["items"][self.fp].get("owner")
                or {})

    def inbox_files(self) -> int:
        d = Path(str(self.server.MEMORY_INBOX_DIR))
        return len(os.listdir(d)) if d.is_dir() else 0

    def test_the_pass_asks_once_and_the_question_names_the_release(self):
        self.assertEqual(self.run_pass(), 1)
        q = self.question()
        self.assertEqual(q["kind"], "question")
        self.assertIn("brAIn 2.17.2 was meant to fix this", q["claim"])
        self.assertIn("boiler", q["claim"])
        self.assertEqual(self.run_pass(), 0, "asked again while it waits")

    def test_yes_lands_held_on_the_queue_and_teaches_memory_nothing(self):
        self.run_pass()
        q = self.question()
        before = self.inbox_files()
        payload = self.end(f"f:{q['ts']}", "do")
        self.assertEqual(self.owner().get("verdict"), "held")
        self.assertFalse(self.owner().get("posted"))
        self.assertIsNone(self.server.findings_store.get(q["ts"]))
        self.assertEqual(self.inbox_files(), before)
        # Settled under the kind no scorecard counts.
        [entry] = [e for e in self.server.findings_store._load_settled()
                   if e.get("source") == self.server.devloop.verify.SOURCE]
        self.assertEqual(entry["kind"], "not_applicable")
        self.assertEqual([r for r in self.server.findings_store.scorecard()
                          if r["source"] == self.server.devloop.verify.SOURCE], [])
        # Undo forgets an answer the send pass has not posted.
        import undo_store
        restored, _ = self.server._undo_finding(undo_store.take(payload["undo"]))
        self.assertTrue(restored)
        self.assertEqual(self.owner(), {})
        self.assertEqual(self.server.devloop.verify.load()[self.fp]["answer"], "")

    def test_no_carries_the_words_for_the_reopen(self):
        self.run_pass()
        q = self.question()
        self.end(f"f:{q['ts']}", "wrong", "still nothing about the boiler")
        owner = self.owner()
        self.assertEqual(owner.get("verdict"), "not_fixed")
        self.assertEqual(owner.get("note"), "still nothing about the boiler")
        self.assertEqual(self.server.devloop.verify.load()[self.fp]["answer"], "not_fixed")
        self.assertEqual(self.run_pass(), 0, "asked once per fix")

    def test_the_question_never_folds_into_another_row_and_cannot_be_muted(self):
        fs, cases = self.server.findings_store, self.server.cases
        self.assertIn(self.server.devloop.verify.SOURCE, fs.SUBJECT_FOLD_EXCLUDED)
        self.assertIn(self.server.devloop.verify.SOURCE, cases.UNMUTABLE_SOURCES)


if __name__ == "__main__":
    unittest.main()
