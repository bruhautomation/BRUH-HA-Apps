#!/usr/bin/env python3
"""The Stop hook that teaches memory what the terminal was told.

Voice has reflected into the memory inbox since the worker pool existed;
the terminal and the panel chat — where the person who actually knows how
the house is wired does most of their typing — taught nothing. This is
that pass, hung off Claude Code's own ``Stop`` hook.

Everything here drives the REAL script. A hook is a process the CLI spawns
with JSON on stdin, and the two claims worth holding are both about
processes: that it gets out of the turn's way at once, and that the work
it hands off actually reaches the inbox. Neither is something a grep of
the source can say — which is the whole lesson of the ``pop`` line that
did not case-fold.

The fake ``claude`` is a shell script that records its own argv, because
"the flag reached the code" and "the flag reached the process" are
different claims and only the second decides what Anthropic is asked for.
"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "brain" / "scripts" / "brain-memory-extract.py"
PANEL = BASE_DIR / "brain" / "panel"
ADDON_DIR = BASE_DIR / "brain"

sys.path.insert(0, str(PANEL))


# A fake CLI: drains the prompt, records its argv, answers with two facts.
FAKE_CLAUDE = """#!/bin/sh
cat > "$ARGV_LOG.prompt"
printf '%s\\n' "$@" > "$ARGV_LOG"
sleep "${FAKE_DELAY:-0}"
cat <<'JSON'
{"fact": "the porch sensor reads on continuously by design", "confidence": "high", "subject": "binary_sensor.porch", "kind": "correction"}
{"fact": "the utility room is called the boot room", "confidence": "medium", "subject": "area:utility", "kind": "fact"}
JSON
"""

# A CLI from before --session-id: refuses the flag by name, works without.
FAKE_CLAUDE_OLD = """#!/bin/sh
cat > /dev/null
printf '%s\\n' "$@" >> "$ARGV_LOG"
for a in "$@"; do
  if [ "$a" = "--session-id" ]; then
    echo "error: unknown option '--session-id'" >&2
    exit 1
  fi
done
echo '{"fact": "the boiler is in the loft", "confidence": "high", "subject": "house", "kind": "fact"}'
"""

# A CLI that answers with something nobody can read.
FAKE_CLAUDE_GARBAGE = """#!/bin/sh
cat > /dev/null
printf '%s\\n' "$@" > "$ARGV_LOG"
echo 'Sure! Here are some facts about your house:'
echo '- the boiler is in the loft'
"""


def transcript_lines(exchanges: int = 2, user_text: str = "") -> list[str]:
    """Claude Code's own transcript shape, as it is written under
    ~/.claude/projects/<dir>/<session>.jsonl: one JSON object per line,
    the conversation on the user/assistant lines, ``message.content`` a
    string for a person and a list of blocks for the model."""
    said = user_text or (
        "Actually the porch motion sensor reads on all the time — that is "
        "how it is wired, not a fault. And we call the utility room the "
        "boot room."
    )
    out = []
    for i in range(exchanges):
        out.append(json.dumps({
            "type": "user", "sessionId": "s", "uuid": f"u{i}",
            "cwd": "/config", "isSidechain": False,
            "timestamp": "2026-09-19T10:00:00.000Z",
            "message": {"role": "user", "content": said if i == exchanges - 1
                        else "how many lights are on downstairs?"},
        }))
        out.append(json.dumps({
            "type": "assistant", "sessionId": "s", "uuid": f"a{i}",
            "cwd": "/config", "isSidechain": False,
            "timestamp": "2026-09-19T10:00:01.000Z",
            "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "ignored", "signature": "x"},
                {"type": "tool_use", "id": "t1", "name": "get_all_states",
                 "input": {}},
                {"type": "text", "text": "Noted — I will remember that."},
            ]},
        }))
    return out


class ExtractCase(unittest.TestCase):
    """One temp house per test: a ledger, an inbox, a state dir, a
    transcript and a fake CLI."""

    FAKE = FAKE_CLAUDE
    DELAY = "0"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ledger = root / "run-sources.jsonl"
        self.inbox = root / "inbox"
        self.state = root / "state"
        self.chat_dir = root / "chat"
        self.argv_log = root / "argv.log"
        self.child_log = root / "child.log"
        self.transcript = root / "session.jsonl"
        self.chat_dir.mkdir()
        self.claude = root / "claude"
        self.claude.write_text(self.FAKE)
        self.claude.chmod(0o755)
        self.write_transcript(transcript_lines())
        self.session = "11111111-2222-3333-4444-555555555555"
        self.addCleanup(self.tmp.cleanup)

    def write_transcript(self, lines):
        self.transcript.write_text("\n".join(lines) + "\n")

    def env(self, **extra):
        env = dict(os.environ)
        env.update({
            "BRAIN_RUN_SOURCES": str(self.ledger),
            "BRAIN_MEMORY_INBOX_DIR": str(self.inbox),
            "BRAIN_EXTRACT_STATE_DIR": str(self.state),
            "BRAIN_CHAT_TRANSCRIPT_DIR": str(self.chat_dir),
            "BRAIN_CLAUDE_BIN": str(self.claude),
            "BRAIN_EXTRACT_LOG": str(self.child_log),
            "ARGV_LOG": str(self.argv_log),
            "FAKE_DELAY": self.DELAY,
        })
        env.update(extra)
        return env

    def payload(self, **over):
        # The shape the CLI bundle builds for a Stop hook: wj()'s four
        # fields plus the two Stop ones.
        out = {
            "session_id": self.session,
            "transcript_path": str(self.transcript),
            "cwd": str(Path(self.tmp.name)),
            "permission_mode": "default",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        }
        out.update(over)
        return out

    def run_hook(self, payload=None, env=None):
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=json.dumps(payload if payload is not None else self.payload()),
            capture_output=True, text=True, timeout=20,
            env=env or self.env(),
        )
        return proc, time.monotonic() - started

    def inbox_files(self):
        if not self.inbox.is_dir():
            return []
        return sorted(self.inbox.glob("*.jsonl"))

    def wait_for_inbox(self, seconds=10.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            files = self.inbox_files()
            if files:
                return files
            time.sleep(0.05)
        return []

    def settle(self, seconds=3.0):
        """Give a child that should write nothing time to have written it."""
        time.sleep(seconds)
        return self.inbox_files()

    def claim(self, source, session_id=None):
        with self.ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"id": session_id or self.session,
                                 "source": source,
                                 "ts": int(time.time())}) + "\n")


class TestTheHookGetsOutOfTheWay(ExtractCase):
    """A hook runs between somebody pressing enter and the turn ending, so
    a second spent here is a second added to every turn in the terminal.
    The fake CLI sleeps, so the child is demonstrably still working when
    the hook has already exited."""

    DELAY = "2"

    def test_it_exits_at_once_and_the_child_carries_on(self):
        proc, elapsed = self.run_hook()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "",
                         "a hook that prints can change what the CLI does")
        self.assertLess(elapsed, 2.0,
                        "the hook waited for the extraction it handed off")
        files = self.wait_for_inbox(15.0)
        self.assertTrue(files, "the detached child never filed anything")


class TestWhatItFiles(ExtractCase):
    def test_the_record_carries_the_six_keys(self):
        proc, _ = self.run_hook()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        files = self.wait_for_inbox()
        self.assertEqual(len(files), 1, "one file per call")
        records = [json.loads(line) for line in
                   files[0].read_text().splitlines() if line.strip()]
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(
                set(record), {"ts", "source", "fact", "confidence",
                              "subject", "run_id"})
            self.assertIn(record["confidence"], ("high", "medium", "low"))
            self.assertTrue(record["fact"])
            self.assertTrue(record["subject"])

    def test_a_correction_is_filed_under_the_word_the_consolidator_knows(self):
        """`kind: correction` means the homeowner is telling brAIn it read
        the house wrong, and the consolidator is already told what to do
        with a line whose source is `correction`: record the standing truth
        the reason implies, never the report."""
        self.run_hook()
        files = self.wait_for_inbox()
        sources = [json.loads(line)["source"]
                   for line in files[0].read_text().splitlines() if line.strip()]
        self.assertEqual(sources, ["correction", "terminal"])

    def test_the_filename_names_the_face_that_was_typed_into(self):
        self.run_hook()
        files = self.wait_for_inbox()
        self.assertTrue(files[0].name.endswith("-terminal.jsonl"), files[0].name)

    def test_a_conversation_the_panel_chat_holds_is_filed_as_chat(self):
        """The chat keeps its own scrollback per conversation, named for
        the session id. That file existing is the one signal that tells the
        two faces apart from inside a hook."""
        (self.chat_dir / f"{self.session}.json").write_text("[]")
        self.run_hook()
        files = self.wait_for_inbox()
        self.assertTrue(files[0].name.endswith("-chat.jsonl"), files[0].name)
        sources = {json.loads(line)["source"]
                   for line in files[0].read_text().splitlines() if line.strip()}
        self.assertEqual(sources, {"correction", "chat"})

    def test_the_run_id_resolves_to_memory_through_the_real_ledger(self):
        """The extraction is itself a Claude run from /config. Unclaimed it
        would file in the Chats rail as a conversation somebody had — the
        machine prompts burying the person's own chats that run_sources
        exists to prevent. The claim is read back with the panel's OWN
        lookup, so the hand-written row and the module cannot drift."""
        self.run_hook()
        files = self.wait_for_inbox()
        run_ids = {json.loads(line)["run_id"]
                   for line in files[0].read_text().splitlines() if line.strip()}
        self.assertEqual(len(run_ids), 1, "one run, one id")
        os.environ["BRAIN_RUN_SOURCES"] = str(self.ledger)
        try:
            import run_sources
            importlib.reload(run_sources)
            found = run_sources.lookup(run_ids)
        finally:
            os.environ.pop("BRAIN_RUN_SOURCES", None)
        self.assertEqual(set(found.values()), {"memory"})
        self.assertEqual(set(found), run_ids)

    def test_the_run_is_capped_and_holds_no_tools(self):
        self.run_hook()
        self.wait_for_inbox()
        argv = self.argv_log.read_text().split("\n")
        self.assertIn("-p", argv)
        self.assertIn("--disallowedTools", argv)
        self.assertIn("*", argv)
        self.assertIn("--max-turns", argv)
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        self.assertIn("--session-id", argv)

    def test_the_model_comes_from_the_plan_and_defaults_to_haiku(self):
        """run.sh writes BRAIN_MODEL_MEMORY into /data/.brain_env from
        model_plan.py's own table; the empty string must fall through to
        the fallback rather than being sent as a model name."""
        self.run_hook(env=self.env(BRAIN_MODEL_MEMORY=""))
        self.wait_for_inbox()
        argv = self.argv_log.read_text().split("\n")
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")

        self.argv_log.unlink()
        for path in self.inbox_files():
            path.unlink()
        # A second run over the same session is inside the spacing window,
        # so a different session is what shows the plan's answer landing.
        payload = self.payload(session_id="99999999-0000-0000-0000-000000000000")
        self.run_hook(payload, env=self.env(BRAIN_MODEL_MEMORY="claude-fake-4-5"))
        self.wait_for_inbox()
        argv = self.argv_log.read_text().split("\n")
        self.assertEqual(argv[argv.index("--model") + 1], "claude-fake-4-5")


class TestWhatItRefuses(ExtractCase):
    def assert_nothing_filed(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.settle(), [], self.child_log.read_text()
                         if self.child_log.exists() else "")

    def test_a_claimed_session_is_not_a_persons_conversation(self):
        """Voice reflects for itself; a consolidator's, a study session's or
        a triage run's "facts" are its own prompt read back."""
        for source in ("voice", "memory", "study", "doctor", "triage",
                       "automation", "resident"):
            with self.subTest(source=source):
                self.ledger.write_text("")
                self.claim(source)
                proc, _ = self.run_hook()
                self.assertEqual(proc.returncode, 0)
                self.assertEqual(self.inbox_files(), [])
        self.assertEqual(self.settle(), [])

    def test_an_unclaimed_neighbour_does_not_claim_this_one(self):
        self.claim("voice", "aaaaaaaa-0000-0000-0000-000000000000")
        proc, _ = self.run_hook()
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(self.wait_for_inbox())

    def test_learning_off_files_nothing_from_either_source(self):
        """`learning: false` is the master switch over every writer, and
        the hook has two routes to the option: the variable the terminal's
        shell sourced, and the env file the chat's process never read."""
        env = self.env()
        env["BRAIN_ASSIST_LEARNING"] = "false"
        proc, _ = self.run_hook(env=env)
        self.assert_nothing_filed(proc)

        env = self.env()
        env.pop("BRAIN_ASSIST_LEARNING", None)
        env_file = Path(self.tmp.name) / ".brain_env"
        env_file.write_text('export BRAIN_OTHER="x"\nexport BRAIN_ASSIST_LEARNING="false"\n')
        env["BRAIN_ENV_FILE"] = str(env_file)
        proc, _ = self.run_hook(env=env)
        self.assert_nothing_filed(proc)

        env_file.write_text('export BRAIN_ASSIST_LEARNING="true"\n')
        proc, _ = self.run_hook(env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(self.wait_for_inbox(), "learning on files as before")

    def test_stop_hook_active_does_nothing(self):
        """The CLI is already inside a stop hook: whatever ends this turn
        is a continuation of one we have seen, not a new thing said."""
        proc, _ = self.run_hook(self.payload(stop_hook_active=True))
        self.assert_nothing_filed(proc)

    def test_a_trivial_turn_is_not_worth_a_model_call(self):
        self.write_transcript(transcript_lines(exchanges=1, user_text="ok"))
        proc, _ = self.run_hook()
        self.assert_nothing_filed(proc)

    def test_a_single_exchange_with_no_teaching_language_is_skipped(self):
        self.write_transcript(transcript_lines(
            exchanges=1,
            user_text="how many lights are on downstairs right now please"))
        proc, _ = self.run_hook()
        self.assert_nothing_filed(proc)

    def test_a_repeat_inside_the_spacing_window_writes_nothing(self):
        proc, _ = self.run_hook()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(self.wait_for_inbox()), 1)
        proc, _ = self.run_hook()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(len(self.settle()), 1,
                         "a second Stop bought a second identical extraction")

    def test_a_missing_transcript_is_silent(self):
        proc, _ = self.run_hook(
            self.payload(transcript_path=str(self.transcript) + ".gone"))
        self.assert_nothing_filed(proc)

    def test_a_session_id_that_is_not_one_is_refused(self):
        """It becomes a filename under the state directory and it arrives
        from outside this process."""
        proc, _ = self.run_hook(self.payload(session_id="../../etc/passwd"))
        self.assert_nothing_filed(proc)

    def test_garbage_on_stdin_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)], input="not json at all",
            capture_output=True, text=True, timeout=20, env=self.env())
        self.assert_nothing_filed(proc)


class TestAReplyNobodyCanRead(ExtractCase):
    FAKE = FAKE_CLAUDE_GARBAGE

    def test_prose_instead_of_jsonl_files_nothing_and_still_exits_zero(self):
        proc, _ = self.run_hook()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        time.sleep(3.0)
        self.assertEqual(self.inbox_files(), [])
        self.assertTrue(self.argv_log.exists(), "the run did happen")


class TestAnOlderCli(ExtractCase):
    FAKE = FAKE_CLAUDE_OLD

    def test_a_cli_that_rejects_the_label_still_gets_its_run(self):
        """The label is optional; the run is not — the same contract
        brain-run-source.sh and engine._run_cli keep."""
        proc, _ = self.run_hook()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        files = self.wait_for_inbox()
        self.assertTrue(files, "the retry without --session-id never happened")
        argv = self.argv_log.read_text()
        self.assertIn("--session-id", argv, "the first attempt asked for it")
        self.assertIn("--max-turns", argv)
        records = [json.loads(line) for line in
                   files[0].read_text().splitlines() if line.strip()]
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["run_id"],
                        "the id is still minted and still claimed")


class TestTheHookIsRegistered(unittest.TestCase):
    """run.sh writes /config/.claude/settings.local.json at every start, and
    that file is the only route this hook has into the CLI. The heredoc is
    parsed rather than grepped: a trailing comma would leave a settings
    file Claude Code refuses whole, taking the allow-list with it."""

    @classmethod
    def setUpClass(cls):
        import re
        run_sh = (ADDON_DIR / "run.sh").read_text()
        m = re.search(r"cat > \"\$claude_settings_dir/settings\.local\.json\""
                      r" << 'SETTINGS'\n(.*?)\nSETTINGS\n", run_sh, re.S)
        assert m, "the settings heredoc moved"
        cls.settings = json.loads(m.group(1))

    def test_the_stop_hook_is_installed_beside_the_snapshot_one(self):
        hooks = self.settings["hooks"]
        self.assertIn("PreToolUse", hooks)
        stop = hooks["Stop"]
        self.assertEqual(len(stop), 1)
        entry = stop[0]["hooks"][0]
        self.assertEqual(entry["type"], "command")
        self.assertIn("brain-memory-extract.py", entry["command"])

    def test_it_carries_a_timeout(self):
        """A hook with no timeout is one the CLI waits the default on. This
        one hands off and returns, so the budget is small on purpose."""
        entry = self.settings["hooks"]["Stop"][0]["hooks"][0]
        self.assertIsInstance(entry["timeout"], int)
        self.assertLessEqual(entry["timeout"], 30)


if __name__ == "__main__":
    unittest.main()
