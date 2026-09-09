"""`brain-landing.sh` is the shell half of engine.py's landing: one sourced
library for every path that drives `claude -p` from a shell (study, ask,
both listeners). Driven by sourcing it in a real bash with a fake `claude`
on PATH, and pinned against the engine's own numbers so the two halves
cannot drift apart.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIB = REPO_ROOT / "brain" / "scripts" / "brain-landing.sh"
sys.path.insert(0, str(REPO_ROOT / "brain" / "panel"))

import engine  # noqa: E402
import journal  # noqa: E402


def bash(script: str, env: dict | None = None, cwd: str | None = None):
    full = dict(os.environ)
    full.update(env or {})
    return subprocess.run(
        ["bash", "-c", f". '{LIB}'\n{script}"],
        capture_output=True, text=True, env=full, cwd=cwd)


class TestTheDetector(unittest.TestCase):
    def _hit(self, output: str, stderr: str = "") -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            err = Path(tmp) / "err"
            err.write_text(stderr)
            # $1 is easier than quoting arbitrary JSON into the script
            r = subprocess.run(
                ["bash", "-c", f". '{LIB}'\nbrain_hit_turn_cap \"$1\" '{err}'",
                 "_", output],
                capture_output=True, text=True)
            return r.returncode == 0

    def test_a_json_envelope_is_judged_by_its_subtype_and_never_its_words(self):
        self.assertTrue(self._hit(json.dumps(
            {"type": "result", "subtype": "error_max_turns", "is_error": True})))
        # An answer that mentions turns is an answer.
        self.assertFalse(self._hit(json.dumps(
            {"type": "result", "subtype": "success",
             "result": "the boiler hit its max turns per hour"})))
        self.assertFalse(self._hit(json.dumps(
            {"type": "result", "subtype": "error_during_execution"})))

    def test_plain_output_and_stderr_are_matched_on_the_clis_wording(self):
        self.assertTrue(self._hit("", "Error: Reached max turns (5)"))
        self.assertTrue(self._hit("Error: Reached max turns (5)"))
        self.assertFalse(self._hit("The kitchen light is on.", ""))
        self.assertFalse(self._hit("", "Invalid API key · Please run /login"))

    def test_the_wording_agrees_with_journal_classify(self):
        """Two readers of the CLI's stderr — the shell half and the Python
        half — must reach the same verdict on the same line."""
        for line in ("Error: Reached max turns (5)",
                     "the run hit the turn limit",
                     "error_max_turns",
                     "Claude timed out after 480s",
                     "claude exited 1: no output",
                     "Failed to authenticate: OAuth session expired"):
            with self.subTest(line=line):
                self.assertEqual(
                    self._hit("", line),
                    journal.classify({"ok": False, "error": line}) == "max_turns")


class TestTheLanding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "argv.log"
        self.stdin = self.root / "stdin.txt"
        fake = self.root / "claude"
        fake.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$*\" >> '{self.log}'\n"
            f"cat > '{self.stdin}'\n"
            "echo 'landed answer'\n")
        fake.chmod(0o755)
        self.env = {"PATH": f"{self.root}:{os.environ.get('PATH', '')}"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_resumes_the_session_with_two_turns_and_the_landing_prompt(self):
        r = bash("brain_land 'abc-123' 60 err.txt -- claude -p --output-format text --model haiku",
                 env=self.env, cwd=self.tmp.name)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "landed answer")
        argv = self.log.read_text().split()
        self.assertEqual(argv[argv.index("--resume") + 1], "abc-123")
        self.assertEqual(argv[argv.index("--max-turns") + 1], "2")
        # The caller's own flags ride along unchanged.
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--output-format") + 1], "text")
        # And what the CLI is told is the landing prompt, on stdin.
        self.assertEqual(self.stdin.read_text(), engine.LANDING_PROMPT)

    def test_without_a_session_or_the_time_for_one_nothing_runs(self):
        for call in ("brain_land '' 60 err.txt -- claude -p",
                     "brain_land 'abc-123' 5 err.txt -- claude -p",
                     "brain_land 'abc-123' 60 err.txt --"):
            with self.subTest(call=call):
                r = bash(call, env=self.env, cwd=self.tmp.name)
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse(self.log.exists(), call)

    def test_the_session_id_is_read_off_the_envelope(self):
        r = bash("brain_session_from_output '{\"type\":\"result\",\"session_id\":\"s-1\"}'; echo; "
                 "brain_session_from_output 'plain text'; echo END",
                 env=self.env)
        self.assertEqual(r.stdout, "s-1\nEND\n")

    def test_the_numbers_are_the_engines(self):
        """One implementation in each language, and the same landing: a
        shell path that landed with three turns while the panel landed
        with two would be two answers to what landing is."""
        r = bash('printf "%s\\n%s\\n%s" "$BRAIN_LANDING_TURNS" '
                 '"$BRAIN_LANDING_MIN_S" "$BRAIN_LANDING_PROMPT"', env=self.env)
        turns, min_s, prompt = r.stdout.split("\n", 2)
        self.assertEqual(int(turns), engine.LANDING_TURNS)
        self.assertEqual(int(min_s), engine.LANDING_MIN_S)
        self.assertEqual(prompt, engine.LANDING_PROMPT)


if __name__ == "__main__":
    unittest.main()
