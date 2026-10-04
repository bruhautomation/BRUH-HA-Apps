"""What one engine run is handed, and what happens when a spawn is retried.

Four claims, every one about the process and driven through the real
`engine._run_cli` against `tests/fake_claude.py` — the argv it logged, the
journal row the run wrote and the run-sources ledger are the evidence, and
none of them is grepped for:

* a snapshot run and a first look get their `structured_output` back,
  because they no longer deny the CLI's own StructuredOutput tool;
* every re-spawn mints and claims its own session id, so the 529 retry
  can actually retry;
* a usage-limit reply is `rate_limited`, which is not a failure;
* a typed Fable model never reaches a run nobody pressed for.

The fake refuses StructuredOutput under a `*` deny and refuses a
`--session-id` whose transcript already exists, so each fix is shown
against the old behaviour on the same fake before it is asserted.
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
import model_plan  # noqa: E402
import run_sources  # noqa: E402
import settings_store  # noqa: E402

FAKE = REPO_ROOT / "tests" / "fake_claude.py"
SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


class RunCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.log = root / "argv.log"
        self.sessions = root / "sessions"
        self.sessions.mkdir()
        shim = root / "claude"
        shim.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
        shim.chmod(0o755)
        self.env = unittest.mock.patch.dict(os.environ, {
            "BRAIN_CLAUDE_BIN": str(shim), "FAKE_CLAUDE_LOG": str(self.log),
            "FAKE_MODE": "structured", "FAKE_SESSIONS_DIR": str(self.sessions),
            "BRAIN_MODEL": "",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-" + "x" * 30})
        self.env.start()
        for key in ("FAKE_REJECT", "FAKE_STRUCTURED", "FAKE_ONCE_FILE",
                    "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
                    "CLAUDE_CODE_DISABLE_ADVISOR_TOOL"):
            os.environ.pop(key, None)
        self.patches = [
            unittest.mock.patch.object(journal, "JOURNAL_FILE",
                                       str(root / "journal.jsonl")),
            unittest.mock.patch.object(run_sources, "LEDGER",
                                       root / "run-sources.jsonl"),
            unittest.mock.patch.object(engine, "HA_PROJECT",
                                       str(root / "nowhere")),
            unittest.mock.patch.object(settings_store, "SETTINGS_FILE",
                                       str(root / "settings.json")),
            unittest.mock.patch.object(engine, "OVERLOAD_RETRY_S", 0),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _lines(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def _argvs(self) -> list[list[str]]:
        return [json.loads(ln) for ln in self._lines() if ln.startswith("[")]

    @staticmethod
    def _after(argv: list[str], flag: str) -> str | None:
        return argv[argv.index(flag) + 1] if flag in argv else None

    def _row(self) -> dict:
        return journal.tail(5)[-1]


class TestTheStructuredAnswerComesBack(RunCase):
    """`--disallowedTools "*"` denied the StructuredOutput tool with
    everything else; `--tools ""` does not."""

    def test_the_old_deny_left_a_schema_run_with_prose(self):
        """The same fake, the flags that shipped: no structured_output,
        five turns spent, and `data` is whatever the prose happened to
        hold — here, nothing."""
        result = engine._run_cli(
            "look", ["--disallowedTools", "*", "--system-prompt", "s"],
            "", 60, 4, "timed out", "resident", schema=SCHEMA)
        self.assertTrue(result["ok"])
        self.assertIsNone(result.get("data"))
        self.assertEqual(result["meta"]["num_turns"], 5)

    def test_a_snapshot_run_gets_its_object(self):
        os.environ["FAKE_STRUCTURED"] = '{"ok": true, "verdicts": [1, 2]}'
        result = engine.run_claude("look", "be brief", timeout=60,
                                   source="resident", schema=SCHEMA)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"], {"ok": True, "verdicts": [1, 2]})
        self.assertEqual(result["meta"]["num_turns"], 2)
        argv = self._argvs()[0]
        self.assertEqual(self._after(argv, "--tools"), "")
        self.assertNotIn("--disallowedTools", argv)
        self.assertIn("--strict-mcp-config", argv)

    def test_an_analyst_run_keeps_its_two_lists_and_drops_the_harness(self):
        result = engine.run_analyst("look", "read only", timeout=60,
                                    source="card", schema=SCHEMA)
        self.assertEqual(result["data"], {"ok": True})
        argv = self._argvs()[0]
        self.assertEqual(self._after(argv, "--tools"), "")
        self.assertIn("SendMessage",
                      self._after(argv, "--disallowedTools").split(","))
        self.assertIn("--strict-mcp-config", argv)

    def test_a_cli_without_tools_gets_the_deny_that_shipped(self):
        """Dropping `--tools ""` alone would leave a snapshot run with
        every built-in; its fallback is the old `*` deny, which is what a
        CLI that old ran with before."""
        os.environ["FAKE_REJECT"] = "tools"
        result = engine.run_claude("look", "s", timeout=60, schema=SCHEMA)
        self.assertTrue(result["ok"], result)
        first, second = self._argvs()
        self.assertIn("--tools", first)
        self.assertNotIn("--tools", second)
        self.assertEqual(self._after(second, "--disallowedTools"), "*")
        self.assertEqual(self._row()["extra"]["dropped_flags"], ["tools"])

    def test_a_flag_with_no_value_is_dropped_without_its_neighbour(self):
        os.environ["FAKE_REJECT"] = "strict-mcp-config"
        engine.run_claude("look", "s", timeout=60)
        first, second = self._argvs()
        self.assertNotIn("--strict-mcp-config", second)
        # `--system-prompt` followed it; removing a value it does not have
        # would have taken that flag instead.
        self.assertEqual(self._after(second, "--system-prompt"), "s")

    def test_an_error_that_merely_mentions_a_flag_word_is_not_a_rejection(self):
        self.assertIsNone(engine._rejected_flag(
            {"ok": False, "error": "the effort was wasted: --disallowedTools refused"}))
        self.assertEqual(engine._rejected_flag(
            {"ok": False, "error": "error: unknown option '--effort'"}), "effort")


class TestEverySpawnIsItsOwnConversation(RunCase):
    def setUp(self):
        super().setUp()
        self.once = self.root / "once"
        os.environ["FAKE_ONCE_FILE"] = str(self.once)

    def test_reusing_the_id_is_what_killed_the_retry(self):
        """The old arrangement on the same fake: the first attempt
        reached the API and left a transcript, so the second, under the
        same id, is refused before any request."""
        argv = engine._claude_argv() + ["-p", "--output-format", "json",
                                        "--session-id", "aaaa-1"]
        engine._spawn_cli(argv, "p", 60, "t")
        again = engine._spawn_cli(argv, "p", 60, "t")
        self.assertFalse(again["ok"])
        self.assertTrue(engine.session_in_use(again), again)

    def test_the_overload_retry_runs_under_a_fresh_claimed_id(self):
        os.environ["FAKE_MODE"] = "overloaded_then_ok"
        result = engine.run_claude("p", "s", timeout=60, source="card")
        self.assertTrue(result["ok"], result)
        first, second = self._argvs()
        sid1 = self._after(first, "--session-id")
        sid2 = self._after(second, "--session-id")
        self.assertTrue(sid1 and sid2)
        self.assertNotEqual(sid1, sid2)
        # Both labelled as the run they were: the overloaded attempt's
        # transcript is a card's too.
        self.assertEqual(run_sources.lookup([sid1, sid2]),
                         {sid1: "card", sid2: "card"})
        row = self._row()
        self.assertEqual(row["outcome"], "ok")
        self.assertEqual(row["extra"]["retried"], "overloaded")
        self.assertEqual(row["run_id"], sid2)

    def test_an_id_found_in_use_is_replaced_once(self):
        taken = "00000000-0000-0000-0000-00000000aaaa"
        fresh = "00000000-0000-0000-0000-00000000bbbb"
        (self.sessions / taken).write_text("")
        ids = iter([taken, fresh])
        with unittest.mock.patch.object(engine.uuid, "uuid4",
                                        side_effect=lambda: next(ids)):
            result = engine.run_claude("p", "s", timeout=60, source="card",
                                       schema=SCHEMA)
        self.assertTrue(result["ok"], result)
        self.assertEqual([self._after(a, "--session-id") for a in self._argvs()],
                         [taken, fresh])

    def test_a_flag_retry_mints_its_own_id_too(self):
        os.environ["FAKE_REJECT"] = "effort"
        engine.run_claude("p", "s", timeout=60, job="card")
        first, second = self._argvs()
        self.assertNotEqual(self._after(first, "--session-id"),
                            self._after(second, "--session-id"))


class TestAUsageLimitIsAWaitNotAFault(RunCase):
    def test_the_reply_is_classed_rate_limited_and_is_not_retried(self):
        os.environ["FAKE_MODE"] = "ratelimited"
        result = engine.run_claude("p", "s", timeout=60, source="card")
        self.assertFalse(result["ok"])
        self.assertEqual(len(self._argvs()), 1)
        row = self._row()
        self.assertEqual(row["outcome"], "rate_limited")
        self.assertFalse(journal.is_failure(row))

    def test_the_wordings(self):
        for error in ("You've hit your limit · resets 3pm (UTC)",
                      "Claude AI usage limit reached|1700000000",
                      "API Error: 429 rate_limit_error",
                      "Server is temporarily limiting requests"):
            self.assertEqual(journal.classify({"ok": False, "error": error}),
                             "rate_limited", error)
        # An overload is retried inside the run, not waited out by the
        # scheduler; and a credential is a credential.
        self.assertNotEqual(journal.classify(
            {"ok": False, "error": "API Error: 529 Overloaded"}), "rate_limited")
        self.assertEqual(journal.classify(
            {"ok": False, "error": "Failed to authenticate: 401"}), "auth")


class TestAFableOverrideNeverReachesATimer(RunCase):
    def test_a_job_nobody_pressed_for_runs_its_planned_tier(self):
        engine.run_claude("p", "s", model="fable", timeout=60, job="card")
        argv = self._argvs()[-1]
        self.assertEqual(self._after(argv, "--model"), "sonnet")
        self.assertTrue(self._row()["extra"]["refused_override"])

    def test_a_press_runs_what_was_typed(self):
        engine.run_claude("p", "s", model="fable", timeout=60, job="card",
                          pressed=True)
        self.assertEqual(self._after(self._argvs()[-1], "--model"), "fable")

    def test_a_typed_opus_is_honoured_and_named_on_the_result(self):
        result = engine.run_claude("p", "s", model="claude-opus-5-5",
                                   timeout=60, job="first_look")
        self.assertEqual(self._after(self._argvs()[-1], "--model"),
                         "claude-opus-5-5")
        # What the ledger charges by: the model actually sent.
        self.assertEqual(result["meta"]["model"], "claude-opus-5-5")
        self.assertEqual(model_plan.tier_of(result["meta"]["model"]), "opus")

    def test_the_setting_override_meets_the_same_guard(self):
        settings_store.save({"model": "fable"})
        self.assertEqual(engine.planned("first_look")[0], "haiku")
        self.assertEqual(engine.planned("first_look", pressed=True)[0], "fable")


class TestEveryRunIsIsolated(RunCase):
    def test_no_auto_memory_and_no_advisor_reach_the_process(self):
        engine.run_claude("p", "s", timeout=60)
        env = [ln for ln in self._lines() if ln.startswith("ENV CLAUDE_CODE")]
        self.assertIn("ENV CLAUDE_CODE_DISABLE_AUTO_MEMORY=1", env)
        self.assertIn("ENV CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1", env)

    def test_no_setting_source_is_loaded_and_peers_are_refused(self):
        engine.run_claude("p", "s", timeout=60)
        argv = self._argvs()[-1]
        self.assertEqual(self._after(argv, "--setting-sources"), "")
        settings = json.loads(self._after(argv, "--settings"))
        self.assertEqual(settings["crossSessionInbound"], "refuse")
        self.assertIs(settings["autoMemoryEnabled"], False)
        self.assertEqual(settings["permissions"]["deny"], engine.PLATFORM_DENIED)


if __name__ == "__main__":
    unittest.main()
