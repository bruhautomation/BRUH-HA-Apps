"""A turn cap is a runaway guard, never a budget — and a guard that trips
has to change what happens next, or every token the run spent is thrown
away with the answer.

`engine._run_cli` lands a run that ended on the CLI's own turn cap: one
more invocation, `--resume` on the same session, two turns, and a prompt
that says finish now with what you have. Driven through the real
`_run_cli` against the fake CLI's argv log and a real journal file — the
argv the second call carried and the row the journal wrote are the
claims, and neither is grepped for.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "brain" / "panel"))

import engine  # noqa: E402
import journal  # noqa: E402
import run_sources  # noqa: E402

FAKE = REPO_ROOT / "tests" / "fake_claude.py"


class LandingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.log = root / "argv.log"
        shim = root / "claude"
        shim.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
        shim.chmod(0o755)
        self.env = unittest.mock.patch.dict(os.environ, {
            "BRAIN_CLAUDE_BIN": str(shim), "FAKE_CLAUDE_LOG": str(self.log),
            "FAKE_MODE": "ok",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-" + "x" * 30})
        self.env.start()
        os.environ.pop("FAKE_LANDING_TEXT", None)
        self.patches = [
            unittest.mock.patch.object(journal, "JOURNAL_FILE",
                                       str(root / "journal.jsonl")),
            unittest.mock.patch.object(run_sources, "LEDGER",
                                       root / "run-sources.jsonl"),
            unittest.mock.patch.object(engine, "HA_PROJECT",
                                       str(root / "nowhere")),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _argvs(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(ln) for ln in self.log.read_text().splitlines()
                if ln.startswith("[")]

    @staticmethod
    def _after(argv: list[str], flag: str) -> str | None:
        return argv[argv.index(flag) + 1] if flag in argv else None

    def _rows(self) -> list[dict]:
        return journal.tail(50)

    # -- the landing ---------------------------------------------------

    def test_a_run_that_trips_the_guard_is_landed_on_its_own_session(self):
        os.environ["FAKE_MODE"] = "max_turns_then_land"
        result = engine.run_analyst("look at the boiler", "be an analyst",
                                    timeout=60, source="card")

        self.assertTrue(result["ok"], result)
        # The fake echoes what it was asked, so the landed answer carries
        # the landing prompt: proof the second call was the one answered.
        self.assertTrue(result["text"].startswith("LANDED: "), result["text"])
        self.assertIn(engine.LANDING_PROMPT, result["text"])

        first, second = self._argvs()
        sid = self._after(first, "--session-id")
        self.assertTrue(sid)
        # No cap of our own on the run: the wall clock is the guard.
        self.assertNotIn("--max-turns", first)
        self.assertEqual(self._after(second, "--resume"), sid)
        self.assertEqual(self._after(second, "--max-turns"),
                         str(engine.LANDING_TURNS))
        self.assertNotIn("--session-id", second)
        # The same tools and the same scoping: a landing that widened the
        # analyst's allow-list would be a different run.
        for flag in ("--allowedTools", "--disallowedTools",
                     "--append-system-prompt"):
            self.assertEqual(self._after(second, flag), self._after(first, flag))

        row = self._rows()[-1]
        self.assertEqual(row["outcome"], "ok")
        self.assertEqual(row.get("extra"), {"landed": True})
        self.assertEqual(row.get("run_id"), sid)

    def test_a_landing_that_also_fails_names_no_setting(self):
        """The old text sent people to look for a number to raise. There
        is none: the cap is a guard, and what ended the run is the model
        or the clock."""
        os.environ["FAKE_MODE"] = "max_turns"
        result = engine.run_claude("p", "s", timeout=60)

        self.assertFalse(result["ok"])
        self.assertIn("Regenerate", result["error"])
        for word in ("max_turns", "max-turns", "BRAIN_", "setting", "option"):
            self.assertNotIn(word, result["error"])
        # The landing was attempted — and it is the one that tripped again.
        self.assertEqual(len(self._argvs()), 2)
        row = self._rows()[-1]
        self.assertEqual(row["outcome"], "max_turns")
        self.assertNotIn("extra", row)

    def test_no_landing_is_attempted_without_the_time_for_one(self):
        """The landing is charged to the run's own wall clock. A landing
        that the timeout would kill costs a second run and answers
        nothing, so under the floor the run keeps its own ending."""
        os.environ["FAKE_MODE"] = "max_turns_then_land"
        result = engine.run_claude("p", "s", timeout=engine.LANDING_MIN_S - 1)

        self.assertFalse(result["ok"])
        self.assertEqual(len(self._argvs()), 1)
        self.assertEqual(self._rows()[-1]["outcome"], "max_turns")

    def test_a_run_that_did_not_trip_is_not_landed(self):
        engine.run_claude("p", "s", timeout=60)
        self.assertEqual(len(self._argvs()), 1)
        row = self._rows()[-1]
        self.assertEqual(row["outcome"], "ok")
        self.assertNotIn("extra", row)

    def test_a_landed_answer_is_the_result_a_caller_gets(self):
        """Through the public door, the way server.py calls it: the caller
        sees an ordinary ok result with the landed text and never learns
        there were two invocations."""
        os.environ["FAKE_MODE"] = "max_turns_then_land"
        os.environ["FAKE_LANDING_TEXT"] = '{"title": "partial", "items": []}'
        result = engine.run_agent("fix it", "be a fixer", timeout=60,
                                  source="fix")
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(result["text"]),
                         {"title": "partial", "items": []})

    # -- the detector --------------------------------------------------

    def test_the_verdict_is_read_off_the_envelope_not_the_words(self):
        # The CLI's own subtype is the authority; the words are for a
        # result that arrived without one.
        self.assertTrue(engine.hit_turn_cap(
            {"ok": False, "error": "anything", "meta": {"subtype": "error_max_turns"}}))
        self.assertTrue(engine.hit_turn_cap(
            {"ok": False, "error": "Error: Reached max turns (5)", "meta": {}}))
        self.assertFalse(engine.hit_turn_cap(
            {"ok": True, "text": "we hit max turns on the boiler", "meta": {}}))
        self.assertFalse(engine.hit_turn_cap(
            {"ok": False, "error": "Claude timed out after 480s", "meta": {}}))
        self.assertFalse(engine.hit_turn_cap(
            {"ok": False, "error": "claude exited 1: boom", "meta": {}}))


if __name__ == "__main__":
    unittest.main()


class TestNoTurnCapOnAPanelRun(LandingCase):
    """`_run_cli` sends no `--max-turns`, on any of the three paths.

    The Resident's first look ran under a cap of four and a structured
    reply is itself a tool turn, so a look that needed one more try ended
    `error_max_turns` — spent, unfiled, and a fault in the next report.
    The wall clock is the guard now, and the argument every runner takes
    is accepted and ignored so no caller changes shape.
    """

    def test_none_of_the_three_paths_sends_a_cap(self):
        engine.run_claude("p", "s", timeout=30, max_turns=4)
        engine.run_analyst("p", "s", timeout=30, max_turns=40)
        engine.run_agent("p", "s", timeout=30, max_turns=60)
        argvs = self._argvs()
        self.assertEqual(len(argvs), 3)
        for argv in argvs:
            self.assertNotIn("--max-turns", argv, argv)

    def test_the_landing_keeps_its_own_two_turn_room(self):
        """The landing is a "finish now" call and its cap is the one
        number here that is a guard rather than a budget."""
        os.environ["FAKE_MODE"] = "max_turns_then_land"
        engine.run_claude("p", "s", timeout=60)
        first, second = self._argvs()
        self.assertNotIn("--max-turns", first)
        self.assertEqual(self._after(second, "--max-turns"),
                         str(engine.LANDING_TURNS))


class TestAnOverloadedApiIsRetriedOnce(LandingCase):
    """A 529 with the run's budget unspent buys one more attempt after a
    pause; a second refusal is the run's ending."""

    def setUp(self):
        super().setUp()
        self.once = Path(self.tmp.name) / "once"
        os.environ["FAKE_ONCE_FILE"] = str(self.once)
        self.quick = unittest.mock.patch.object(engine, "OVERLOAD_RETRY_S", 0)
        self.quick.start()

    def tearDown(self):
        self.quick.stop()
        os.environ.pop("FAKE_ONCE_FILE", None)
        super().tearDown()

    def test_the_run_is_tried_again_and_the_journal_says_so(self):
        os.environ["FAKE_MODE"] = "overloaded_then_ok"
        result = engine.run_claude("p", "s", timeout=60, source="card")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(self._argvs()), 2)
        row = self._rows()[-1]
        self.assertEqual(row["outcome"], "ok")
        self.assertEqual(row.get("extra"), {"retried": "overloaded"})

    def test_no_retry_without_the_time_for_one(self):
        os.environ["FAKE_MODE"] = "overloaded_then_ok"
        with unittest.mock.patch.object(engine, "OVERLOAD_RETRY_S", 100):
            result = engine.run_claude("p", "s", timeout=60)
        self.assertFalse(result["ok"])
        self.assertIn("529", result["error"])
        self.assertEqual(len(self._argvs()), 1)

    def test_overloaded_is_read_off_the_error_and_nothing_else(self):
        self.assertTrue(engine.overloaded(
            {"ok": False, "error": "API Error: 529 Overloaded"}))
        self.assertTrue(engine.overloaded(
            {"ok": False, "error": "overloaded_error"}))
        self.assertFalse(engine.overloaded(
            {"ok": True, "text": "529 devices overloaded the hub", "error": ""}))
        self.assertFalse(engine.overloaded(
            {"ok": False, "error": "claude exited 1: no output"}))
