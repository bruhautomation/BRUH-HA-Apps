"""The shell half's runs reach the run journal, and the panel books them.

Study, the consolidator, the automation listener and the memory extractor
drive `claude -p` from processes that cannot call `journal.record`, so for
as long as they existed their failures filed no report, their runs nudged
no usage reading, and their tokens were missing from the breakdown and the
estimate — while every other Claude run counted. `journal.py record` is the
one door, run from the process that ran the model; `book_shell_rows` is the
panel meeting those rows with the listeners an in-process row meets.

Driven as the processes they are: the CLI as a subprocess, the shell
helper by sourcing the real library, the consolidator end to end over a
fake claude, and the booking through the server's own handlers.
"""
from __future__ import annotations

import importlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PANEL = ROOT / "brain" / "panel"
SCRIPTS = ROOT / "brain" / "scripts"
sys.path.insert(0, str(PANEL))

import journal  # noqa: E402

SID = "3f2a9c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b"


class ShellCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.journal_file = self.base / "journal.jsonl"
        self.nudge = self.base / "usage-nudge"
        self.home = self.base / "home"
        self.env = dict(os.environ,
                        BRAIN_JOURNAL_FILE=str(self.journal_file),
                        BRAIN_USAGE_NUDGE=str(self.nudge),
                        BRAIN_USAGE_FILE=str(self.base / "usage.json"),
                        HOME=str(self.home),
                        CLAUDE_CONFIG_DIR=str(self.home / ".claude"))
        self.env.pop("BRAIN_SHELL_MARK_FILE", None)

    def cli(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(PANEL / "journal.py"),
                               "record", *args],
                              env=self.env, capture_output=True, text=True,
                              timeout=30)

    def rows(self) -> list[dict]:
        if not self.journal_file.exists():
            return []
        return [json.loads(line) for line in
                self.journal_file.read_text().splitlines() if line.strip()]

    def write(self, name: str, text: str) -> str:
        path = self.base / name
        path.write_text(text)
        return str(path)


class TestTheCommandLine(ShellCase):
    def test_a_timeout_is_a_timeout_and_nudges(self):
        err = self.write("err", "starting\n\n")
        proc = self.cli("--source", "memory", "--exit", "124", "--stderr", err,
                        "--run-id", SID, "--model", "haiku", "--duration", "480")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout + proc.stderr, "")
        [row] = self.rows()
        self.assertEqual(row["outcome"], "timeout")
        self.assertFalse(row["ok"])
        self.assertEqual(row["run_id"], SID)
        self.assertEqual(row["extra"], {"shell": True, "exit": 124})
        self.assertTrue(journal.is_shell_row(row))
        self.assertTrue(journal.is_claude_run(row))
        self.assertTrue(self.nudge.exists(), "a finished run nudges the tracker")

    def test_a_failure_carries_the_clis_last_line(self):
        err = self.write("err", "loading\nError: Session ID x is already in use.\n")
        self.cli("--source", "study", "--exit", "1", "--stderr", err)
        [row] = self.rows()
        self.assertEqual(row["outcome"], "error")
        self.assertIn("already in use", row["error"])

    def test_a_bare_exit_is_a_crash_with_its_code(self):
        self.cli("--source", "study", "--exit", "3")
        [row] = self.rows()
        self.assertEqual(row["outcome"], "crash")
        self.assertEqual(row["error"], "claude exited 3")

    def test_the_envelope_is_the_authority(self):
        cases = [
            ({"type": "result", "subtype": "success", "is_error": False,
              "result": "done", "session_id": SID, "num_turns": 4,
              "duration_ms": 2500,
              "usage": {"input_tokens": 100, "cache_creation_input_tokens": 50,
                        "cache_read_input_tokens": 9000, "output_tokens": 25}},
             0, "ok"),
            ({"type": "result", "subtype": "success", "is_error": True,
              "result": "You've hit your limit · resets 3pm (UTC)",
              "session_id": SID, "num_turns": 1}, 1, "rate_limited"),
            ({"type": "result", "subtype": "error_max_turns", "is_error": True,
              "result": "", "session_id": SID, "num_turns": 200}, 1, "max_turns"),
            ({"type": "result", "subtype": "success", "is_error": True,
              "result": "Failed to authenticate: OAuth session expired",
              "session_id": SID}, 1, "auth"),
        ]
        for envelope, code, outcome in cases:
            with self.subTest(outcome=outcome):
                self.journal_file.unlink(missing_ok=True)
                out = self.write("out", json.dumps(envelope))
                self.cli("--source", "automation", "--exit", str(code),
                         "--envelope", out)
                [row] = self.rows()
                self.assertEqual(row["outcome"], outcome)
                self.assertEqual(row["run_id"], SID)
        # The usage block counts what burns the window, never a cache read.
        self.journal_file.unlink()
        self.cli("--source", "automation", "--exit", "0",
                 "--envelope", self.write("out", json.dumps(cases[0][0])))
        [row] = self.rows()
        self.assertEqual((row["tokens"], row["turns"], row["duration_s"]),
                         (175, 4, 2.5))

    def test_a_caller_may_fail_a_run_that_exited_cleanly(self):
        self.cli("--source", "study", "--exit", "0",
                 "--error", "unparseable: the session answered with no JSON")
        [row] = self.rows()
        self.assertEqual(row["outcome"], "unparseable")

    def test_a_text_run_is_counted_off_its_transcript(self):
        """The consolidator and study read text, so no envelope: the CLI's
        own transcript carries one usage block per call — written once per
        content block, so counted once per message id."""
        project = self.home / ".claude" / "projects" / "-config"
        project.mkdir(parents=True)
        usage = {"input_tokens": 10, "output_tokens": 5,
                 "cache_creation_input_tokens": 1, "cache_read_input_tokens": 500}
        lines = [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "message": {"id": "msg_1", "usage": usage}},
            {"type": "assistant", "message": {"id": "msg_1", "usage": usage}},
            {"type": "assistant", "message": {"id": "msg_2", "usage": usage}},
        ]
        (project / f"{SID}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
        self.cli("--source", "memory", "--exit", "0", "--run-id", SID)
        [row] = self.rows()
        self.assertEqual(row["tokens"], 32)

    def test_an_id_that_is_not_an_id_names_no_file(self):
        self.assertEqual(journal.transcript_tokens("../../etc/passwd",
                                                   [str(self.home)]), 0)
        self.assertEqual(journal.transcript_tokens("*", [str(self.home)]), 0)

    def test_it_never_fails_its_caller(self):
        self.assertEqual(self.cli("--bogus").returncode, 0)
        self.env["BRAIN_JOURNAL_FILE"] = str(self.base / "file" / "journal.jsonl")
        (self.base / "file").write_text("a file where a directory should be")
        proc = self.cli("--source", "memory", "--exit", "1")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))


class TestTheShellHelper(ShellCase):
    def test_sourcing_the_real_library_records_a_row(self):
        script = (f". {SCRIPTS / 'brain-run-source.sh'}\n"
                  "brain_journal_record study 0 --run-id " + SID + "\n"
                  "echo rc=$?\n")
        env = dict(self.env, BRAIN_PANEL_DIR=str(PANEL),
                   BRAIN_RUN_SOURCES=str(self.base / "run-sources.jsonl"))
        proc = subprocess.run(["bash", "-c", script], env=env,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.stdout.strip(), "rc=0")
        [row] = self.rows()
        self.assertEqual((row["source"], row["outcome"]), ("study", "ok"))

    def test_a_missing_panel_records_nothing_and_says_nothing(self):
        script = (f". {SCRIPTS / 'brain-run-source.sh'}\n"
                  "brain_journal_record study 1\necho rc=$?\n")
        env = dict(self.env, BRAIN_PANEL_DIR=str(self.base / "nowhere"))
        proc = subprocess.run(["bash", "-c", script], env=env,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual((proc.stdout.strip(), proc.stderr), ("rc=0", ""))
        self.assertEqual(self.rows(), [])


class TestTheConsolidatorRecordsItsPass(ShellCase):
    CONSOLIDATOR = SCRIPTS / "brain-memory-consolidate.sh"

    def _fake(self, body: str) -> Path:
        fake = self.base / "fake_claude.sh"
        fake.write_text("#!/bin/bash\ncat > /dev/null\n" + body)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        return fake

    def _run(self, fake: Path) -> subprocess.CompletedProcess:
        memory = self.base / "memory"
        inbox = memory / "inbox"
        inbox.mkdir(parents=True)
        (memory / "memory.md").write_text("# Home Memory\n\n## Preferences\n")
        (inbox / f"{int(time.time())}-assist.jsonl").write_text(json.dumps(
            {"ts": int(time.time()), "source": "assist",
             "fact": "We call the office lamp 'the beacon'"}) + "\n")
        env = dict(self.env, BRAIN_MEMORY_DIR=str(memory),
                   BRAIN_CLAUDE_BIN=str(fake),
                   BRAIN_SHARE_INBOX=str(self.base / "share-inbox"),
                   BRAIN_RUN_SOURCE_LIB=str(SCRIPTS / "brain-run-source.sh"),
                   BRAIN_RUN_SOURCES=str(self.base / "run-sources.jsonl"),
                   BRAIN_PANEL_DIR=str(PANEL))
        return subprocess.run(["bash", str(self.CONSOLIDATOR), "--once"],
                              env=env, capture_output=True, text=True,
                              timeout=60)

    def test_a_pass_that_worked_is_one_ok_row_under_its_own_id(self):
        fake = self._fake("cat << 'OUT'\n# Home Memory\n\n## Preferences\n"
                          "- 'the beacon' = light.office_lamp\n\n"
                          "## Entity nicknames\n\n## Household patterns\n\n"
                          "## Device notes\n-----VOICE-----\n- beacon\nOUT\n")
        proc = self._run(fake)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        rows = [r for r in self.rows() if r["source"] == "memory"]
        self.assertEqual(len(rows), 1, self.rows())
        self.assertEqual(rows[0]["outcome"], "ok")
        claimed = [json.loads(line)["id"] for line in
                   (self.base / "run-sources.jsonl").read_text().splitlines()]
        self.assertEqual(rows[0]["run_id"], claimed[-1])
        self.assertTrue(self.nudge.exists())

    def test_a_pass_that_failed_carries_why(self):
        fake = self._fake("echo 'API Error: 500 upstream went away' >&2\nexit 2\n")
        self._run(fake)
        rows = [r for r in self.rows() if r["source"] == "memory"]
        self.assertEqual(len(rows), 1, self.rows())
        self.assertEqual(rows[0]["outcome"], "error")
        self.assertIn("upstream went away", rows[0]["error"])
        self.assertEqual(rows[0]["extra"]["exit"], 2)


class TestTheConsolidatorHearsTheCliItRuns(ShellCase):
    """The CLI as 2.1.295 really answers, not as a fixture guessed.

    In `-p` text mode the CLI prints its OWN verdict on a failed run —
    "Error: Reached max turns (1)", "Execution error", an API error, a
    signed-out account — to STDOUT, and exits 1 with stderr empty (read off
    the bundle: `print()` writes through the stdout writer). The
    consolidator kept stdout as the answer file, deleted it on failure, and
    handed the journal only stderr: six passes out of seven in a day were
    filed as "claude exited 1" with the reason thrown away. The fake above
    (`test_a_pass_that_failed_carries_why`) writes its error to stderr,
    which is the shape the code guessed rather than the shape the CLI has.
    """

    CONSOLIDATOR = TestTheConsolidatorRecordsItsPass.CONSOLIDATOR
    _run = TestTheConsolidatorRecordsItsPass._run

    MERGED = ("# Home Memory\n\n## Preferences\n"
              "- 'the beacon' = light.office_lamp\n\n"
              "## Entity nicknames\n\n## Household patterns\n\n"
              "## Device notes\n-----VOICE-----\n- beacon\n")

    def _cli(self, verdict: dict | None) -> Path:
        """A CLI that answers like the real one: an envelope under
        `--output-format json`, the result text (or its error line on
        stdout, exit 1) otherwise."""
        fake = self.base / "fake_cli.py"
        fake.write_text(
            "#!" + sys.executable + "\n"
            "import json, sys\n"
            "sys.stdin.read()\n"
            f"verdict = {verdict!r}\n"
            f"merged = {self.MERGED!r}\n"
            "args = sys.argv[1:]\n"
            "as_json = 'json' in args and '--output-format' in args\n"
            "if verdict is None:\n"
            "    env = {'type': 'result', 'subtype': 'success', 'is_error': False,\n"
            "           'result': merged, 'num_turns': 1,\n"
            "           'usage': {'input_tokens': 40, 'output_tokens': 60}}\n"
            "    print(json.dumps(env) if as_json else merged, end='')\n"
            "    sys.exit(0)\n"
            "env = dict({'type': 'result', 'is_error': True, 'num_turns': 1}, **verdict)\n"
            "if as_json:\n"
            "    print(json.dumps(env))\n"
            "else:\n"
            "    print(verdict.get('line') or env.get('result') or '')\n"
            "sys.exit(1)\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        return fake

    def _row(self) -> dict:
        rows = [r for r in self.rows() if r["source"] == "memory"]
        self.assertEqual(len(rows), 1, self.rows())
        return rows[0]

    def test_an_api_error_is_named_on_the_row(self):
        self._run(self._cli({"subtype": "success",
                             "result": "API Error: 529 Overloaded"}))
        row = self._row()
        self.assertIn("529", row["error"])
        self.assertNotEqual(row["error"], "claude exited 1")

    def test_a_signed_out_account_is_auth_not_a_crash(self):
        proc = self._run(self._cli({
            "subtype": "success",
            "result": "Invalid API key \u00b7 Please run /login"}))
        row = self._row()
        self.assertEqual(row["outcome"], "auth", row)
        self.assertIn("Invalid API key", proc.stdout)

    def test_the_turn_cap_is_max_turns_not_a_crash(self):
        # The error_max_turns envelope carries no `result`: the reason is
        # its subtype, and the row has to say so in words too.
        self._run(self._cli({"subtype": "error_max_turns",
                             "line": "Error: Reached max turns (1)"}))
        row = self._row()
        self.assertEqual(row["outcome"], "max_turns", row)
        self.assertNotEqual(row["error"], "claude exited 1")

    def test_a_pass_that_worked_files_the_result_and_counts_it(self):
        proc = self._run(self._cli(None))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        memory = (self.base / "memory" / "memory.md").read_text()
        self.assertIn("the beacon", memory)
        self.assertNotIn('"type"', memory)
        row = self._row()
        self.assertEqual((row["outcome"], row["tokens"]), ("ok", 100))


class TestThePanelBooksThem(ShellCase):
    def setUp(self):
        super().setUp()
        self._old = (journal.JOURNAL_FILE, journal.SHELL_MARK_FILE)
        journal.JOURNAL_FILE = str(self.journal_file)
        journal.SHELL_MARK_FILE = ""
        self.addCleanup(self._restore)

    def _restore(self):
        journal.JOURNAL_FILE, journal.SHELL_MARK_FILE = self._old

    def _shell(self, outcome="ok", now=None, **kw):
        return journal.record("study", outcome, ok=outcome == "ok",
                              run_id=SID, extra={"shell": True, "exit": 0},
                              now=now, **kw)

    def test_each_row_is_booked_once_across_a_restart(self):
        now = time.time()
        journal.record("insight", "ok", run_id=SID, now=now)   # in-process
        self._shell(now=now)
        self._shell("timeout", now=now)                         # same second
        seen = []
        self.assertEqual(journal.book_shell_rows([seen.append]), 2)
        self.assertEqual(journal.book_shell_rows([seen.append]), 0)
        self.assertEqual([r["outcome"] for r in seen], ["ok", "timeout"])
        # Another row in the SAME second as the mark is still news.
        self._shell("crash", now=now)
        self.assertEqual(journal.book_shell_rows([seen.append]), 1)
        # The mark is on disk, beside the journal: a restart is not a
        # reason to book everything again.
        self.assertTrue((self.base / "journal-shell-mark.json").exists())
        self.assertEqual(journal.book_shell_rows([seen.append]), 0)
        self.assertEqual(len(seen), 3)

    def test_a_first_boot_does_not_book_last_week(self):
        old = time.time() - 7 * 86400
        self._shell("timeout", now=old)
        seen = []
        self.assertEqual(journal.book_shell_rows([seen.append]), 0)
        self._shell("crash")
        self.assertEqual(journal.book_shell_rows([seen.append]), 1)

    def test_a_handler_that_raises_costs_only_itself(self):
        self._shell()
        seen = []

        def boom(_row):
            raise RuntimeError("no")

        self.assertEqual(journal.book_shell_rows([boom, seen.append]), 1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(journal.book_shell_rows([seen.append]), 0)

    def test_a_shell_row_meets_the_listeners_only_through_the_booking(self):
        """Written in-process with listeners installed — the panel's own
        test of itself — it must still be booked once, not twice."""
        heard = []
        listeners = list(journal._LISTENERS)
        journal._LISTENERS[:] = []
        journal.on_record(heard.append)
        try:
            self._shell("crash")
            journal.record("insight", "ok")
        finally:
            journal._LISTENERS[:] = listeners
        self.assertEqual([r["source"] for r in heard], ["insight"])
        seen = []
        self.assertEqual(journal.book_shell_rows([seen.append]), 1)
        self.assertEqual([r["outcome"] for r in seen], ["crash"])

    def test_the_servers_handlers_report_count_and_hold(self):
        server = importlib.import_module("server")
        # The copies the server's handlers read: other test files swap
        # `journal` and `usage_store` in sys.modules, so whatever a bare
        # import answers here may not be the module the server writes to.
        jr, usage_store = server.journal, server.usage_store
        old_files = (jr.JOURNAL_FILE, jr.SHELL_MARK_FILE)
        jr.JOURNAL_FILE, jr.SHELL_MARK_FILE = str(self.journal_file), ""
        old_usage = usage_store.USAGE_FILE
        usage_store.USAGE_FILE = str(self.base / "usage.json")
        reported = []
        old_report = server._report_async
        server._report_async = lambda fn, row, **kw: reported.append(row)
        rate = dict(server.RATE_LIMIT_STATE)
        try:
            now = time.time()
            for outcome, tokens, error in (
                    ("crash", 1200, "claude exited 1"),
                    ("rate_limited", 40, "You've hit your limit"),
                    ("ok", 300, "")):
                jr.record("study", outcome, ok=outcome == "ok", run_id=SID,
                          extra={"shell": True, "exit": 0}, now=now,
                          tokens=tokens, error=error)
            self.assertEqual(jr.book_shell_rows(server._SHELL_HANDLERS), 3)
            runs = json.loads((self.base / "usage.json").read_text())
            booked = runs.get("runs", runs) if isinstance(runs, dict) else runs
            self.assertEqual(sorted(r["tokens"] for r in booked), [40, 300, 1200])
            self.assertTrue(all(r["id"] == "study" for r in booked))
            self.assertEqual([r["outcome"] for r in reported], ["crash"])
            # The limit was met and then a run succeeded: the pause ended.
            self.assertEqual(server.RATE_LIMIT_STATE["until"], 0.0)
        finally:
            jr.JOURNAL_FILE, jr.SHELL_MARK_FILE = old_files
            usage_store.USAGE_FILE = old_usage
            server._report_async = old_report
            server.RATE_LIMIT_STATE.clear()
            server.RATE_LIMIT_STATE.update(rate)


if __name__ == "__main__":
    unittest.main()
