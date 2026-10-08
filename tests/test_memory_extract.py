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
pwd > "$ARGV_LOG.cwd"
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

# A CLI from before --tools and --setting-sources: refuses each by name, the
# way the real arg parser does, and answers once it is asked without them.
FAKE_CLAUDE_ANCIENT = """#!/bin/sh
cat > /dev/null
printf '%s\\n' "$@" > "$ARGV_LOG"
for a in "$@"; do
  case "$a" in
    --tools|--setting-sources)
      echo "error: unknown option '$a'" >&2
      exit 1 ;;
  esac
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
        self.home = root / "home"
        self.home.mkdir()
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
            "BRAIN_HOME": str(self.home),
        })
        # No panel: the journal row is asserted where it is asked for, and
        # must not reach the real /data anywhere else.
        env.pop("BRAIN_PANEL_DIR", None)
        env["BRAIN_PANEL_DIR"] = str(Path(self.tmp.name) / "no-panel")
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
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertNotIn("--disallowedTools", argv)
        self.assertIn("--max-turns", argv)
        self.assertEqual(argv[argv.index("--max-turns") + 1], "1")
        self.assertIn("--session-id", argv)

    def test_the_run_stands_where_the_engines_runs_do(self):
        """From /config the pass paid for the whole generated CLAUDE.md,
        the project's MCP server and its own Stop hook firing again, to
        read four kilobytes. It runs from CLAUDE_HOME now, on its own
        system prompt, with no MCP and no setting source — and the
        isolation it names is the engine's own, kept in step by hand
        because the hook must start without the panel."""
        import engine
        self.run_hook()
        self.wait_for_inbox()
        argv = self.argv_log.read_text().split("\n")
        self.assertEqual(Path(self.argv_log.with_name("argv.log.cwd")
                              .read_text().strip()).resolve(),
                         self.home.resolve())
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(json.loads(argv[argv.index("--settings") + 1]),
                         engine.isolation_settings())
        # The system prompt spans lines, and the argv log is one per line.
        self.assertIn("--system-prompt", argv)
        self.assertIn("EARLIER is context", self.argv_log.read_text())
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")

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


class TestOnlyWhatIsNewIsRead(ExtractCase):
    """Every window used to reach back to the previous user turn, so from
    the second turn of a conversation it held two and the keyword gate was
    never asked: one run per turn over overlapping windows. A window now
    starts after the last message a pass read."""

    def env(self, **extra):
        return super().env(BRAIN_EXTRACT_SPACING="0", **extra)

    def append(self, n: int, user_text: str):
        lines = self.transcript.read_text().splitlines()
        lines.append(json.dumps({
            "type": "user", "uuid": f"u{n}", "isSidechain": False,
            "message": {"role": "user", "content": user_text}}))
        lines.append(json.dumps({
            "type": "assistant", "uuid": f"a{n}", "isSidechain": False,
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "Understood."}]}}))
        self.write_transcript(lines)

    def prompt(self) -> tuple[str, str]:
        text = self.argv_log.with_name("argv.log.prompt").read_text()
        earlier, _, new = text.partition("NEW:")
        return earlier, new

    def test_a_second_pass_reads_only_what_was_said_since(self):
        self.run_hook()
        self.assertTrue(self.wait_for_inbox())
        earlier, new = self.prompt()
        self.assertIn("porch motion sensor", new)
        self.assertIn("how many lights", earlier)
        for path in self.inbox_files():
            path.unlink()
        self.append(2, "We always keep the garage heater off at night, on purpose.")
        self.run_hook()
        self.assertTrue(self.wait_for_inbox())
        earlier, new = self.prompt()
        self.assertIn("garage heater", new)
        self.assertNotIn("porch motion sensor", new)
        self.assertIn("porch motion sensor", earlier, "context, not content")

    def test_a_stop_with_nothing_new_buys_nothing(self):
        self.run_hook()
        self.assertTrue(self.wait_for_inbox())
        self.argv_log.unlink()
        self.run_hook()
        time.sleep(2.0)
        self.assertFalse(self.argv_log.exists(), "a pass over nothing new ran")

    def test_two_exchanges_no_longer_skip_the_gate(self):
        """The bug itself: a first window of two exchanges whose newest
        message carries no teaching language used to pass on its count."""
        self.write_transcript(transcript_lines(
            exchanges=2,
            user_text="and how many are on upstairs, give me the whole list"))
        proc, _ = self.run_hook()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.settle(), [])
        self.assertFalse(self.argv_log.exists())

    def test_a_message_judged_not_worth_a_pass_moves_the_window(self):
        self.write_transcript(transcript_lines(
            exchanges=1,
            user_text="how many lights are on downstairs right now please"))
        self.run_hook()
        self.assertEqual(self.settle(1.5), [])
        self.append(5, "Actually the hall lamp is on a smart plug, never the switch.")
        self.run_hook()
        self.assertTrue(self.wait_for_inbox())
        earlier, new = self.prompt()
        self.assertIn("smart plug", new)
        self.assertNotIn("downstairs right now", new)


class TestTheRunIsJournalled(ExtractCase):
    def test_a_pass_records_itself_through_the_panels_journal(self):
        journal_file = Path(self.tmp.name) / "journal.jsonl"
        env = self.env(BRAIN_PANEL_DIR=str(PANEL),
                       BRAIN_JOURNAL_FILE=str(journal_file),
                       BRAIN_USAGE_NUDGE=str(Path(self.tmp.name) / "nudge"))
        self.run_hook(env=env)
        files = self.wait_for_inbox()
        run_id = json.loads(files[0].read_text().splitlines()[0])["run_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not journal_file.exists():
            time.sleep(0.05)
        rows = [json.loads(line) for line in journal_file.read_text().splitlines()]
        self.assertEqual([(r["source"], r["outcome"], r["run_id"]) for r in rows],
                         [("memory_extract", "ok", run_id)])
        self.assertTrue(rows[0]["extra"]["shell"])


class TestAnAncientCli(ExtractCase):
    FAKE = FAKE_CLAUDE_ANCIENT

    def test_flags_it_does_not_know_are_dropped_and_the_pass_still_runs(self):
        self.run_hook()
        self.assertTrue(self.wait_for_inbox(), "the pass never ran")
        argv = self.argv_log.read_text().split("\n")
        self.assertNotIn("--tools", argv)
        self.assertNotIn("--setting-sources", argv)
        # The deny-everything spelling an older CLI does know stands in.
        self.assertEqual(argv[argv.index("--disallowedTools") + 1], "*")
        self.assertIn("--strict-mcp-config", argv)


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


# A fake CLI that records the credential it was handed, and nothing else
# about it beyond whether it was there.
FAKE_CLAUDE_CRED = """#!/bin/sh
cat > /dev/null
printf '%s|%s' "${CLAUDE_CODE_OAUTH_TOKEN-<unset>}" "${ANTHROPIC_API_KEY-<unset>}" > "$ARGV_LOG.cred"
echo '{"fact": "the boiler is in the loft", "confidence": "high", "subject": "house", "kind": "fact"}'
"""

# Stands in for the Claude Code process: it holds the credential in its OWN
# environment and runs the hook with that credential scrubbed, the way CLI
# 2.1.293 does (measured: CLAUDE_CODE_OAUTH_TOKEN and ANTHROPIC_API_KEY never
# reach a hook, while an ordinary variable does), naming itself in
# CLAUDE_PID exactly as the CLI does.
CLI_PARENT = """
import os, subprocess, sys
script, payload, pid_mode = sys.argv[1], sys.argv[2], sys.argv[3]
env = dict(os.environ)
env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
env.pop("ANTHROPIC_API_KEY", None)
if pid_mode == "self":
    env["CLAUDE_PID"] = str(os.getpid())
elif pid_mode == "stranger":
    env["CLAUDE_PID"] = os.environ["STRANGER_PID"]
proc = subprocess.run([sys.executable, script], input=payload, text=True,
                      env=env, timeout=20)
sys.exit(proc.returncode)
"""


class TestTheCredentialIsTheCLIsOwn(ExtractCase):
    """The Stop hook's environment does not carry the credential the CLI
    was started with — Claude Code strips it from every hook — so the pass
    used to fall through to the CLI's own .credentials.json, which the
    panel never refreshes because it hands the CLI its token in the
    environment instead. Every chat and card ran; every extraction ended
    `auth`. The hook now reads the two credential variables off the CLI
    process that ran it, and only those."""

    FAKE = FAKE_CLAUDE_CRED

    def run_under_cli(self, pid_mode="self", **cli_env):
        env = self.env(**cli_env)
        env.pop("CLAUDE_PID", None)
        proc = subprocess.run(
            [sys.executable, "-c", CLI_PARENT, str(SCRIPT),
             json.dumps(self.payload()), pid_mode],
            capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def cred(self):
        path = Path(str(self.argv_log) + ".cred")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not path.exists():
            time.sleep(0.05)
        time.sleep(0.1)
        return path.read_text() if path.exists() else None

    def test_the_pass_is_handed_the_token_the_cli_was_started_with(self):
        self.run_under_cli(CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-panel-token")
        self.assertEqual(self.cred(), "sk-ant-oat01-panel-token|<unset>")

    def test_an_api_key_travels_the_same_way(self):
        self.run_under_cli(ANTHROPIC_API_KEY="sk-ant-api03-key")
        self.assertEqual(self.cred(), "<unset>|sk-ant-api03-key")

    def test_a_cli_signed_in_by_its_own_file_hands_on_nothing(self):
        """The CLI authenticating from .credentials.json is the cli_login
        case, and the pass then does the same: nothing invented."""
        self.run_under_cli()
        self.assertEqual(self.cred(), "<unset>|<unset>")

    def test_a_process_that_did_not_run_the_hook_is_not_asked(self):
        """CLAUDE_PID is honoured only for an ancestor: a variable naming
        some other process is not where this hook's credential lives."""
        stranger = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            env={**os.environ, "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-stranger"})
        self.addCleanup(stranger.kill)
        self.run_under_cli(pid_mode="stranger", STRANGER_PID=str(stranger.pid))
        self.assertEqual(self.cred(), "<unset>|<unset>")


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
