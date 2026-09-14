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


class TestWhatCountsAsAFailure(JournalCase):
    """`failures` is the outcomes that are a problem, not "everything that
    is not `ok`".

    The summary decided this with ``outcome != "ok"``, and five of the
    fourteen words are not problems: `applied` and `healed` are
    successes, `heal_skipped` and `denied` are refusals doing their job,
    and `fallback` is a quieter path that still produced a card. So a
    successful overnight heal arrived in `failures` — where
    `reports.faults` renders the list — and the report opened *what is
    wrong right now* with ``Run (healing): ended healed`` and **no detail
    on it**, which is the fault shape nobody can act on.

    The row was already carrying the answer: `record` takes `ok` from the
    caller and writes it down. `healing` passes ``ok=True``, and the
    summary read past it.
    """

    def test_a_heal_that_worked_is_not_a_failure(self):
        journal.record("healing", "healed", ok=True, now=1000,
                       extra={"remedy": "entry.reload"})
        self.assertEqual(journal.summary(now=1001)["failures"], [])

    def test_a_heal_that_did_not_work_is(self):
        journal.record("healing", "heal_failed", ok=False, error="503",
                       now=1000)
        got = journal.summary(now=1001)["failures"]
        self.assertEqual([r["outcome"] for r in got], ["heal_failed"])

    def test_every_success_and_refusal_stays_out_of_the_list(self):
        for outcome in ("applied", "healed", "heal_skipped", "denied",
                        "fallback"):
            journal.record("x", outcome, ok=True, now=1000)
        self.assertEqual(journal.summary(now=1001)["failures"], [])
        # And they are still counted: a fallback nobody counts is a
        # fallback read as the real thing.
        self.assertEqual(journal.summary(now=1001)["by_outcome"]["fallback"], 1)

    def test_every_real_failure_still_lands_in_it(self):
        for outcome in sorted(journal.FAILURE_OUTCOMES):
            journal.record("x", outcome, now=1000)
        self.assertEqual(len(journal.summary(now=1001)["failures"]),
                         len(journal.FAILURE_OUTCOMES))

    def test_a_row_with_no_ok_field_falls_back_to_the_outcome(self):
        """An older line, or one written by a caller that let `ok`
        default. "I cannot tell from the flag" must not read as fine."""
        self.assertTrue(journal.is_failure({"outcome": "crash"}))
        self.assertFalse(journal.is_failure({"outcome": "healed"}))
        self.assertFalse(journal.is_failure("not a row"))
        # A row with no outcome at all reads as `error`, which is the
        # same default `summary` counts one under and the same coercion
        # `record` applies to a word it does not know. One answer.
        self.assertTrue(journal.is_failure({}))

    def test_ok_outranks_a_failure_word(self):
        """The caller's own claim about its own run wins: that is the one
        thing the outcome vocabulary cannot always carry."""
        self.assertFalse(journal.is_failure({"outcome": "error", "ok": True}))


if __name__ == "__main__":
    unittest.main()
