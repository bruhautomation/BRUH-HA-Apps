#!/usr/bin/env python3
"""Tests for the run journal — the counting that turns a field report into
a bug."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import journal  # noqa: E402


class JournalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (journal.JOURNAL_FILE, journal.MAX_LINES)
        journal.JOURNAL_FILE = os.path.join(self.tmp.name, "journal.jsonl")

    def tearDown(self):
        journal.JOURNAL_FILE, journal.MAX_LINES = self._old
        self.tmp.cleanup()


class TestRecord(JournalCase):
    def test_a_line_per_run_and_a_summary_over_them(self):
        journal.record("card", "ok", duration_s=12.34, model="sonnet", tokens=3000,
                       turns=4, now=1000)
        journal.record("card", "timeout", error="took too long", duration_s=480,
                       now=1001)
        journal.record("chat", "ok", now=1002)
        rows = journal.tail(10)
        self.assertEqual([r["source"] for r in rows], ["card", "card", "chat"])
        self.assertEqual(rows[0]["duration_s"], 12.3)
        self.assertEqual(rows[0]["tokens"], 3000)
        self.assertTrue(rows[0]["ok"])
        self.assertFalse(rows[1]["ok"])
        summary = journal.summary(hours=1, now=1500)
        self.assertEqual(summary["runs"], 3)
        self.assertEqual(summary["by_source"]["card"], {"ok": 1, "timeout": 1})
        self.assertEqual(summary["by_outcome"]["ok"], 2)
        self.assertEqual(summary["tokens"], 3000)
        self.assertEqual(len(summary["failures"]), 1)
        self.assertEqual(summary["failures"][0]["outcome"], "timeout")
        # outside the window: nothing
        self.assertEqual(journal.summary(hours=1, now=1000 + 7200)["runs"], 0)

    def test_an_unknown_outcome_word_is_error_not_free_text(self):
        row = journal.record("x", "exploded")
        self.assertEqual(row["outcome"], "error")

    def test_credentials_are_scrubbed_from_error_text(self):
        row = journal.record(
            "card", "auth",
            error="401 for sk-ant-oat01-abcdefghijklmnop with Bearer eyJabcdefghij"
                  ".0123456789abcdefghijk.abcdefghijklmnop")
        self.assertNotIn("sk-ant-", row["error"])
        self.assertNotIn("eyJ", row["error"])
        self.assertIn("[redacted]", row["error"])
        self.assertNotIn("sk-ant-", Path(journal.JOURNAL_FILE).read_text())

    def test_a_torn_line_is_skipped_and_the_rest_read(self):
        journal.record("a", "ok")
        with open(journal.JOURNAL_FILE, "a") as fh:
            fh.write('{"ts": 1, "source": "torn"\n')
        journal.record("b", "ok")
        self.assertEqual([r["source"] for r in journal.tail(10)], ["a", "b"])

    def test_the_file_is_capped_by_rewriting_the_tail(self):
        journal.MAX_LINES = 8
        for i in range(20):
            journal.record("s", "ok", now=i)
        rows = journal.tail(0)
        self.assertLessEqual(len(rows), 8)
        self.assertEqual(rows[-1]["ts"], 19)

    def test_an_unwritable_path_never_raises(self):
        blocker = os.path.join(self.tmp.name, "file")
        Path(blocker).write_text("x")
        journal.JOURNAL_FILE = os.path.join(blocker, "journal.jsonl")
        row = journal.record("card", "ok")
        self.assertEqual(row["outcome"], "ok")
        self.assertEqual(journal.tail(5), [])


class TestClassify(unittest.TestCase):
    def test_the_vocabulary(self):
        cases = [
            ({"ok": True}, "ok"),
            ({"ok": False, "error": "insight timed out after 480s"}, "timeout"),
            ({"ok": False, "error": "Claude hit the turn limit before finishing"}, "max_turns"),
            ({"ok": False, "error": "claude CLI not found"}, "no_cli"),
            ({"ok": False, "error": "OAuth session expired"}, "auth"),
            ({"ok": False, "error": "Service lock.unlock is not permitted"}, "denied"),
            ({"ok": False, "error": "claude exited 1: boom"}, "crash"),
            ({"ok": False, "error": "Claude returned an unparseable insight (no JSON/html)"}, "unparseable"),
            ({"ok": False, "error": "something odd"}, "error"),
        ]
        for result, want in cases:
            self.assertEqual(journal.classify(result), want, result)

    def test_the_exact_timeout_message_wins_over_wording(self):
        msg = "The analyst ran out of time"
        self.assertEqual(journal.classify({"ok": False, "error": msg}, msg), "timeout")

    def test_every_outcome_word_is_documented_once(self):
        self.assertEqual(len(journal.OUTCOMES), len(set(journal.OUTCOMES)))
        for word in ("ok", "timeout", "max_turns", "unparseable", "auth",
                     "denied", "no_cli", "crash", "fallback", "error"):
            self.assertIn(word, journal.OUTCOMES)


class TestEngineHooksIntoTheJournal(unittest.TestCase):
    """The engine records every invocation, whatever happened to it."""

    def test_run_cli_writes_a_line(self):
        import engine
        with tempfile.TemporaryDirectory() as tmp:
            old = journal.JOURNAL_FILE
            journal.JOURNAL_FILE = os.path.join(tmp, "j.jsonl")
            try:
                calls = []

                def fake_spawn(argv, prompt, timeout, timeout_message):
                    calls.append(argv)
                    return {"ok": False, "error": timeout_message, "text": "",
                            "meta": {"num_turns": 2}}
                original = engine._spawn_cli
                engine._spawn_cli = fake_spawn
                try:
                    engine._run_cli("hi", [], "sonnet", 5, 3, "insight timed out")
                finally:
                    engine._spawn_cli = original
                rows = journal.tail(5)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["source"], "engine")
                self.assertEqual(rows[0]["outcome"], "timeout")
                self.assertEqual(rows[0]["model"], "sonnet")
                self.assertEqual(rows[0]["turns"], 2)
                first_line = Path(journal.JOURNAL_FILE).read_text().splitlines()[0]
                self.assertEqual(json.loads(first_line)["outcome"], "timeout")
            finally:
                journal.JOURNAL_FILE = old


if __name__ == "__main__":
    unittest.main()
