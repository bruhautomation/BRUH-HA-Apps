#!/usr/bin/env python3
"""A fault row a house turns into a bug report says what happened.

Five rows a real house filed, each a defect in how the row reads:

* a failed run said "ended error (2 times)" over "partial; last at Mon
  18:51" — nothing about what partial means, or whether to do anything;
* "One-off intents: refused 2", whose own sentence was "Nothing to do" —
  a refusal already on the tab with its reason, filed as a fault;
* the Resident's scorecard row called it a rule and told people to tick
  "Ignore all like this", a box its cards never offer;
* a task that ran past its limit told people to restart a working add-on
  over a guess about MCP;
* the raw daemon roll-call carried no word of which daemons this
  configuration asked for, so `assist_listener: false` read as broken.

`where|what` is the development loop's fingerprint and does not move; the
explanation is in the sentence and the detail.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import cases  # noqa: E402
from test_todo_list import PanelCase  # noqa: E402
import reports  # noqa: E402

NOW = 1_790_000_000


def _runs(*failures) -> dict:
    return {"journal": {"runs": 40, "claude_runs": 30,
                        "failures": list(failures)}}


class TestAFailedRunSaysWhatHappened(unittest.TestCase):
    def test_a_partial_voice_turn_says_the_device_may_have_changed(self):
        rows = reports.faults(_runs(*[
            {"source": "voice", "outcome": "error", "ok": False,
             "error": "partial", "ts": NOW - 60 * i} for i in range(2)]))
        [row] = [r for r in rows if r["where"] == "Run (voice)"]
        # The fingerprint did not move.
        self.assertEqual(row["what"], "ended error (2 times)")
        for field in ("sentence", "detail"):
            text = row[field].lower()
            with self.subTest(field=field):
                self.assertIn("broke off", text)
                self.assertIn("may or may not have changed", text)
        self.assertIn("partial", row["detail"])
        self.assertIn("2 times", row["sentence"])
        # Whether anything needs doing is said.
        self.assertIn("check", row["sentence"].lower())

    def test_a_crash_says_the_program_stopped(self):
        rows = reports.faults(_runs(*[
            {"source": "memory", "outcome": "crash", "ok": False,
             "error": "claude exited 1", "ts": NOW - 60 * i} for i in range(3)]))
        [row] = [r for r in rows if r["where"] == "Run (memory)"]
        self.assertEqual(row["what"], "ended crash (3 times)")
        self.assertIn("stopped", row["sentence"].lower())
        self.assertIn("unexpectedly", row["detail"].lower())

    def test_a_timeout_says_it_ran_past_its_limit(self):
        rows = reports.faults(_runs(
            {"source": "card", "outcome": "timeout", "ok": False,
             "error": "Claude timed out after 480s", "ts": NOW}))
        [row] = [r for r in rows if r["where"] == "Run (card)"]
        self.assertIn("time limit", row["sentence"])
        self.assertIn("time limit", row["detail"])

    def test_an_error_carries_the_cli_line(self):
        line = "API Error: 529 Overloaded"
        rows = reports.faults(_runs(
            {"source": "card", "outcome": "error", "ok": False,
             "error": line, "ts": NOW}))
        [row] = [r for r in rows if r["where"] == "Run (card)"]
        self.assertIn(line, row["sentence"])
        self.assertIn(line, row["detail"])


class TestARefusalAlreadyOnTheTabIsNotAFault(unittest.TestCase):
    def test_refused_one_offs_and_scenes_file_no_row(self):
        rows = reports.faults({"proposals": {
            "intents": {"armed": 0, "refused": 2},
            "scenes": {"designed": 0, "refused": 3}}})
        self.assertEqual([r for r in rows if r["where"] in
                          ("One-off intents", "Scene designer")], [])

    def test_no_fault_row_says_nothing_to_do_about_a_refusal(self):
        rows = reports.faults({"proposals": {"conditions": {"refused": [
            {"automation": "Hall light at night",
             "why": "the automation has no id, so it cannot be edited"}]}}})
        [row] = [r for r in rows if r["where"] == "Condition miner"]
        self.assertNotIn("Nothing to do", row["sentence"])
        # The reason is carried, by name and not as a dict's repr.
        for field in ("sentence", "detail"):
            self.assertIn("Hall light at night", row[field])
            self.assertIn("has no id", row[field])
        self.assertNotIn("{", row["detail"])


class TestTheResidentIsNotARule(unittest.TestCase):
    def _row(self, source, title):
        rows = reports.faults({"findings": {"scorecard": [
            {"source": source, "title": title, "confirmed": 2, "wrong": 3,
             "total": 5, "last": "wrong"}]}})
        [row] = [r for r in rows if r["where"].startswith("Producer")]
        return row

    def test_the_unmutable_set_is_cases_own(self):
        self.assertEqual(reports.UNMUTABLE_SOURCES, cases.UNMUTABLE_SOURCES)

    def test_the_resident_row_says_it_cannot_be_muted_and_how_to_teach(self):
        row = self._row("resident", "brAIn, watching the house")
        self.assertEqual(row["what"], "ignored 3 of 5 times")
        visible = f"{row['sentence']} {row['detail']}"
        self.assertNotIn("Ignore all like this", visible)
        self.assertNotIn("this rule is firing", visible)
        self.assertNotIn("healthy house", visible)
        self.assertIn("cannot be muted", visible)
        self.assertIn("reason", row["sentence"])
        self.assertIn("memory", row["sentence"])

    def test_safety_too(self):
        row = self._row("safety", "Safety sensors")
        self.assertNotIn("Ignore all like this", row["sentence"])
        self.assertIn("cannot be muted", row["sentence"])

    def test_a_rule_still_gets_the_mute_advice(self):
        row = self._row("check:dev.frozen", "Sensors frozen on one value")
        self.assertIn("Ignore all like this", row["sentence"])


LISTENERS = {
    "automation": BASE_DIR / "brain" / "integrations" / "automation-listener.sh",
    "assist": BASE_DIR / "brain" / "integrations" / "assist-listener.sh",
}


class TestATimeoutDoesNotSendAnybodyToRestart(unittest.TestCase):
    """The timeout branch's sentence, lifted out of the real script and
    evaluated by bash with the limit and the duration set."""

    def _sentence(self, path: Path, var: str) -> str:
        text = path.read_text()
        lines = text.splitlines()
        [i] = [n for n, line in enumerate(lines)
               if 'fail_code="timeout"' in line]
        # The assignment is the nearest `var=` line above the code.
        for j in range(i, i - 6, -1):
            if re.match(rf"\s*{var}=", lines[j]):
                line = lines[j].strip()
                break
        else:
            self.fail(f"no {var}= above the timeout code in {path.name}")
        out = subprocess.run(
            ["bash", "-c", f'claude_limit=600; duration=598; {line}; '
                           f'printf %s "${var}"'],
            capture_output=True, text=True, check=True)
        return out.stdout

    def test_the_automation_task_names_its_limit_and_no_restart(self):
        said = self._sentence(LISTENERS["automation"], "result")
        self.assertIn("600", said)
        self.assertIn("time limit", said)
        self.assertIn("partly", said)
        self.assertNotIn("restart", said.lower())
        self.assertNotIn("MCP", said)

    def test_the_classic_voice_listener_too(self):
        said = self._sentence(LISTENERS["assist"], "response")
        self.assertIn("600", said)
        self.assertNotIn("restart", said.lower())
        self.assertNotIn("MCP", said)

    def test_the_worker_pool_too(self):
        text = (BASE_DIR / "brain" / "integrations"
                / "assist-worker-pool.py").read_text()
        block = text[text.index('error = "timeout"'):][:500]
        self.assertNotIn("restarting", block)
        self.assertNotIn("MCP", block)


class TestTheRollCallSaysWhatWasAskedFor(PanelCase):
    def setUp(self):
        super().setUp()
        import chat_session
        self.chat_session = chat_session
        self._old_chat = chat_session.TRANSCRIPT_DIR
        chat_session.TRANSCRIPT_DIR = os.path.join(self.tmp.name, "chat")
        self._old = (self.server._daemon_rollcall,
                     self.server.addon_options.snapshot)
        self.server._daemon_rollcall = lambda: {
            "assist_worker_pool": {"running": True},
            "assist_listener": {"running": False},
            "automation_listener": {"running": True},
        }
        self.server.addon_options.snapshot = lambda: {
            "enable_assist_integration": True, "assist_fast_mode": True,
            "enable_automation_integration": True}

    def tearDown(self):
        (self.server._daemon_rollcall,
         self.server.addon_options.snapshot) = self._old
        self.chat_session.TRANSCRIPT_DIR = self._old_chat
        super().tearDown()

    def test_the_payload_carries_the_expected_daemons(self):
        diag = self.server._diagnostics_payload()
        expected = diag["daemons_expected"]
        self.assertIn("assist_worker_pool", expected)
        self.assertIn("automation_listener", expected)
        self.assertNotIn("assist_listener", expected)
        self.assertEqual(sorted(expected), expected)
        # One derivation: health's own answer.
        options = {k: v for k, v in diag["options"].items()}
        self.assertEqual(set(expected), set(
            self.server.health.expected_daemons(options)))
        # The existing key keeps its meaning.
        self.assertFalse(diag["daemons"]["assist_listener"]["running"])
        self.assertTrue(diag["daemons"]["automation_listener"]["running"])


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
