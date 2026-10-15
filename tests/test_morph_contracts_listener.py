#!/usr/bin/env python3
"""A conversation task: brAIn's chat, by task (contract E).

Morph's Ask hands a conversation to brAIn's task folder with `kind:
"conversation"` and, from the second turn, the `session_id` the first one
answered with. The listener runs it on the chat's channel, resumes the
session, starts fresh (and says so) when the CLI no longer holds it, and
does NOT claim the session as an automation's, so it is the person's own
conversation in brAIn's Ask tab.

Driven through the REAL `process_task` lifted out of the listener, over the
fake CLI — `test_task_failures`' harness, with an exported
`brain_claim_session` recording what would have been claimed.

Mutations each test names:

  the channel is a task's   drop `export BRAIN_CHANNEL=chat` -> the argv log
                            says `task`
  the session is claimed    claim a conversation -> the claim log is not empty
  a lost session fails      drop the fresh-start fallback -> the result is a
                            failure and `resumed` is absent
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_task_failures import (FAKE_CLAUDE, LIFTED, PANEL_DIR,  # noqa: E402
                                SCRIPTS_DIR, ListenerCase, lift, lift_line)


class ConversationCase(ListenerCase):
    def run_conversation(self, task: dict, **env_over) -> dict:
        task = {"id": "t1", "prompt": "why is it warm upstairs?",
                "ts": time.time(), "timeout": 120, "kind": "conversation",
                **task}
        (self.tmp / "tasks" / "t1.json").write_text(json.dumps(task))
        body = "\n\n".join(lift(n) for n in LIFTED)
        body = body.replace("cd /config", 'cd "$WORK_DIR"')
        script = "\n".join([
            "set -u",
            "bashio::log.info() { :; }", "bashio::log.warning() { :; }",
            "bashio::log.error() { :; }", "bashio::log.debug() { :; }",
            "verify_mcp_config_fast() { :; }",
            "verify_mcp_config_full() { :; }",
            "cleanup_stale_files() { :; }",
            "curl() { :; }",
            'brain_claim_session() { echo "$1 $2" >> "$CLAIM_LOG"; }',
            f'TASKS_DIR="{self.tmp}/tasks"', f'RESULTS_DIR="{self.tmp}/results"',
            f'LOG_DIR="{self.tmp}/logs"', f'SHARED_DIR="{self.tmp}"',
            'MAX_TURNS=200', 'CLAUDE_TIMEOUT=300', 'TIMEOUT_MARGIN=15',
            'SUPERVISOR_TOKEN=""',
            f'CLAUDE_BIN="{sys.executable} {FAKE_CLAUDE}"',
            lift_line("AUTH_REMEDY="),
            lift_line("export BRAIN_CHANNEL="),
            body,
            f'process_task "{self.tmp}/tasks/t1.json"',
            "wait",
        ])
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp),
            "WORK_DIR": str(self.tmp / "work"),
            "CLAIM_LOG": str(self.tmp / "claims.log"),
            "FAKE_JSON_ENVELOPE": "1",
            "FAKE_CLAUDE_LOG": str(self.argv_log),
            "BRAIN_PANEL_DIR": str(PANEL_DIR),
            "BRAIN_SCRIPTS_DIR": str(SCRIPTS_DIR),
            "BRAIN_JOURNAL_FILE": str(self.journal),
            "BRAIN_USAGE_NUDGE": str(self.tmp / "usage-nudge"),
            "BRAIN_USAGE_FILE": str(self.tmp / "usage.json"),
            "BRAIN_USAGE_LIMITS": str(self.tmp / "usage_limits.json"),
            "BRAIN_SETTINGS_FILE": str(self.settings),
            **env_over,
        }
        proc = subprocess.run(["bash", "-c", script], env=env,
                              capture_output=True, text=True, timeout=120,
                              check=False)
        out = self.tmp / "results" / "t1.json"
        self.assertTrue(out.is_file(),
                        f"no result file written\n{proc.stdout}\n{proc.stderr}")
        return json.loads(out.read_text())

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.argv_log.read_text().splitlines()
                if line.startswith("[")]

    def claims(self) -> str:
        path = self.tmp / "claims.log"
        return path.read_text() if path.is_file() else ""


class TestAConversationIsTheChat(ConversationCase):
    def test_on_the_chats_channel_unclaimed_and_naming_its_session(self):
        result = self.run_conversation({})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["session_id"],
                         "22222222-2222-2222-2222-222222222222")
        self.assertNotIn("resumed", result)
        self.assertIn("ENV BRAIN_CHANNEL=chat",
                      self.argv_log.read_text().splitlines())
        self.assertNotIn("--resume", self.calls()[0])
        self.assertEqual(self.claims(), "")

    def test_the_next_turn_resumes_it(self):
        sid = "33333333-3333-3333-3333-333333333333"
        result = self.run_conversation({"session_id": sid})
        call = self.calls()[0]
        self.assertEqual(call[call.index("--resume") + 1], sid)
        self.assertEqual(result["session_id"], sid)
        self.assertIs(result["resumed"], True)

    def test_a_session_the_cli_lost_is_begun_again_and_said(self):
        sid = "44444444-4444-4444-4444-444444444444"
        result = self.run_conversation({"session_id": sid},
                                       FAKE_RESUME_MISSING=sid)
        self.assertEqual(result["status"], "completed", result)
        self.assertIs(result["resumed"], False)
        self.assertIn("could not pick up the earlier conversation",
                      result["result"])
        calls = self.calls()
        self.assertEqual(len(calls), 2)
        self.assertNotIn("--resume", calls[1])
        self.assertEqual(result["session_id"],
                         "22222222-2222-2222-2222-222222222222")

    def test_a_session_id_that_is_not_one_is_never_an_argument(self):
        self.run_conversation({"session_id": "x; rm -rf /"})
        self.assertNotIn("--resume", self.calls()[0])

    def test_an_ordinary_task_is_unchanged(self):
        result = self.run_task({})
        self.assertEqual(set(result), {"id", "result", "status"})
        self.assertIn("ENV BRAIN_CHANNEL=task",
                      self.argv_log.read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
