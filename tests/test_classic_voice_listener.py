#!/usr/bin/env python3
"""The classic voice listener keeps the pool's contract, in shell.

`assist_fast_mode: false` runs voice through `assist-listener.sh` rather
than the worker pool, and every promise the pool makes it has to make too
or the same agent behaves differently depending on a switch nobody thinks
about: the request's context in the TURN, a resumed conversation answered
under this request's system prompt, the plan's voice depth, the voice
channel named for the MCP server, a failure written as one, and a journal
row for every turn.

Driven through the REAL `process_request`: the listener's whole body up to
its watch loop is run in a shell with three substitutions — the shared
directory, the working directory (`cd /config`) and the CLI, which is the
fake one — because a test that wrote into the machine's /config would be a
test with a side effect.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
LISTENER = ADDON_DIR / "integrations" / "assist-listener.sh"
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"


def listener_body() -> str:
    """The listener from its first export to just before the watch loop."""
    src = LISTENER.read_text(encoding="utf-8")
    start = src.index("export BRAIN_CHANNEL=voice")
    end = src.index("listen_for_requests() {")
    body = src[start:end]
    for old, new in (
            ('SHARED_DIR="/config/.brain"', 'SHARED_DIR="$TEST_SHARED"'),
            ('CLAUDE_BIN="claude-run"', 'CLAUDE_BIN="$TEST_CLAUDE_BIN"'),
            ("if [ ! -x /usr/local/bin/claude-run ]; then", "if false; then"),
            ("cd /config", 'cd "$TEST_WORK"')):
        assert old in body, f"assist-listener.sh no longer has {old!r}"
        body = body.replace(old, new)
    return body


class ClassicCase(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.shared = self.tmp / "shared"
        (self.tmp / "work").mkdir()
        self.argv_log = self.tmp / "argv.log"
        self.journal = self.tmp / "journal.jsonl"

    def run_requests(self, requests: list[dict], *, fake_mode="ok",
                     fake_help="", plan: dict | None = None) -> list[dict]:
        """Each request through `process_request`, in order, in one shell."""
        (self.shared / "requests").mkdir(parents=True, exist_ok=True)
        lines = ["set -u",
                 "bashio::log.info() { :; }", "bashio::log.warning() { :; }",
                 "bashio::log.error() { :; }", "bashio::log.debug() { :; }",
                 listener_body(),
                 # Stubbed after the definitions they replace: neither has
                 # anything to do in a temp directory with no Core.
                 "verify_mcp_config_fast() { :; }",
                 "verify_mcp_config_full() { :; }",
                 "refresh_area_map() { :; }"]
        for req in requests:
            path = self.shared / "requests" / f"{req['id']}.json"
            path.write_text(json.dumps(req))
            lines.append(f'process_request "{path}"')
        lines.append("wait")
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp),
            "TEST_SHARED": str(self.shared),
            "TEST_WORK": str(self.tmp / "work"),
            "TEST_CLAUDE_BIN": f"{sys.executable} {FAKE_CLAUDE}",
            "FAKE_MODE": fake_mode,
            "FAKE_HELP": fake_help,
            "FAKE_CLAUDE_LOG": str(self.argv_log),
            "BRAIN_SCRIPTS_DIR": str(ADDON_DIR / "scripts"),
            "BRAIN_PANEL_DIR": str(ADDON_DIR / "panel"),
            "BRAIN_JOURNAL_FILE": str(self.journal),
            "BRAIN_USAGE_NUDGE": str(self.tmp / "usage-nudge"),
            "BRAIN_RUN_SOURCES": str(self.tmp / "run-sources.jsonl"),
            "BRAIN_MEMORY_DIR": str(self.tmp / "memory"),
            **(plan or {}),
        }
        proc = subprocess.run(["bash", "-c", "\n".join(lines)], env=env,
                              capture_output=True, text=True, timeout=120,
                              check=False)
        out = []
        for req in requests:
            path = self.shared / "responses" / f"{req['id']}.json"
            self.assertTrue(path.is_file(),
                            f"no response for {req['id']}\n{proc.stderr[-2000:]}")
            out.append(json.loads(path.read_text()))
        return out

    def spawns(self) -> list[list[str]]:
        return [json.loads(line) for line in self.argv_log.read_text().splitlines()
                if line.startswith("[")]


def req(text, conv="c1", **extra) -> dict:
    return {"id": uuid.uuid4().hex, "conversation_id": conv, "text": text,
            "type": "conversation", "ts": time.time(), "timeout": 60,
            "conversation_history": [], **extra}


class TestTheTurnCarriesItsContext(ClassicCase):

    def test_the_room_reaches_the_cli_ahead_of_the_words(self):
        [resp] = self.run_requests([req("turn off the lights", context={
            "area": "Kitchen", "floor": "Ground floor",
            "device": "Kitchen satellite"})])
        # The fake CLI echoes what it was handed on stdin.
        text = resp["text"]
        self.assertIn("Kitchen area", text)
        self.assertLess(text.index("Kitchen area"),
                        text.index("turn off the lights"))
        self.assertNotIn("error", resp)

    def test_a_request_with_no_context_is_the_turn_it_always_was(self):
        [resp] = self.run_requests([req("turn off the lights")])
        self.assertNotIn("Context for this request", resp["text"])


class TestFlagsTheCliMustKnow(ClassicCase):

    def test_a_resumed_turn_is_answered_under_this_requests_prompt(self):
        self.run_requests([req("lights off"), req("and the hall")],
                          fake_help="--system-prompt-snapshot")
        first, second = self.spawns()[-2:]
        self.assertNotIn("--system-prompt-snapshot", first)
        self.assertIn("--resume", second)
        self.assertEqual(second[second.index("--system-prompt-snapshot") + 1],
                         "off")

    def test_a_cli_that_does_not_list_it_is_not_sent_it(self):
        self.run_requests([req("lights off"), req("and the hall")])
        self.assertTrue(all("--system-prompt-snapshot" not in a
                            for a in self.spawns()))

    def test_the_plans_depth_rides_with_the_plans_model_only(self):
        plan = {"BRAIN_MODEL_VOICE": "voice-tier-x", "BRAIN_EFFORT_VOICE": "low"}
        self.run_requests([req("lights off", conv="a"),
                           req("lights off", conv="b", model="chosen")],
                          fake_help="--effort", plan=plan)
        planned, chosen = self.spawns()[-2:]
        self.assertEqual(planned[planned.index("--model") + 1], "voice-tier-x")
        self.assertEqual(planned[planned.index("--effort") + 1], "low")
        self.assertEqual(chosen[chosen.index("--model") + 1], "chosen")
        self.assertNotIn("--effort", chosen)

    def test_the_mcp_server_is_told_this_is_voice(self):
        self.run_requests([req("hi")])
        channels = [line for line in self.argv_log.read_text().splitlines()
                    if line.startswith("ENV BRAIN_CHANNEL=")]
        self.assertEqual(set(channels), {"ENV BRAIN_CHANNEL=voice"})


class TestAFailureIsWrittenAsOne(ClassicCase):

    def test_an_expired_login_is_coded_and_names_the_panel_button(self):
        [resp] = self.run_requests([req("hi")], fake_mode="autherror")
        self.assertEqual(resp["error"], "auth")
        self.assertIn("Sign in again", resp["text"])
        self.assertNotIn("/login", resp["text"])

    def test_every_turn_is_journaled(self):
        self.run_requests([req("hi", conv="a")])
        self.run_requests([req("hi", conv="b")], fake_mode="autherror")
        rows = [json.loads(line) for line in self.journal.read_text().splitlines()
                if line.strip()]
        self.assertEqual([r["source"] for r in rows], ["voice", "voice"])
        self.assertEqual([r["outcome"] for r in rows], ["ok", "auth"])
        self.assertEqual(rows[0]["extra"], {"mode": "classic"})


if __name__ == "__main__":
    unittest.main()
