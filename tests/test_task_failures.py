#!/usr/bin/env python3
"""A task that failed crosses the boundary AS a failure.

The automation listener wrote `"status": "completed"` on every result it
ever wrote — an expired login, a timeout and a run that produced nothing
included — and the bridge read `.result` and nothing else, so the sentence
about the failure came back to `brain.run_task`, to `brain.ask` (with
`data: None` beside it, which an automation's `| default(false)` reads as a
real "no") and to an insight job, which filed it as that morning's report
and pushed it to a phone.

These drive the REAL `process_task` out of the real listener against the
fake CLI, then hand the result file it wrote to the REAL bridge — the two
halves of a wire format, each driven rather than written down twice. The
one substitution is the working directory (`cd /config` becomes a temp
directory), because a test that cd's into the machine's /config is a test
with a side effect.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
PANEL_DIR = ADDON_DIR / "panel"
SCRIPTS_DIR = ADDON_DIR / "scripts"
INTEGRATION_DIR = ADDON_DIR / "custom_components" / "brain"
LISTENER = ADDON_DIR / "integrations" / "automation-listener.sh"
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"

LIFTED = ("extract_claude_result", "claim_task_session", "task_tool_flags",
          "write_task_result", "task_gate", "task_memory_block",
          "journal_task", "extract_claude_data", "process_task")


def lift(name: str) -> str:
    src = LISTENER.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", src, re.S | re.M)
    assert match, f"automation-listener.sh no longer defines {name}"
    return match.group(0)


def lift_line(prefix: str) -> str:
    src = LISTENER.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(prefix)}.*$", src, re.M)
    assert match, f"automation-listener.sh no longer sets {prefix}"
    return match.group(0)


class ListenerCase(unittest.TestCase):
    """One real `process_task` per test, over a task file this writes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for sub in ("tasks", "results", "logs", "work"):
            (self.tmp / sub).mkdir()
        self.memory = self.tmp / "memory.md"
        self.settings = self.tmp / "settings.json"
        self.journal = self.tmp / "journal.jsonl"
        self.argv_log = self.tmp / "argv.log"
        self.curl_log = self.tmp / "curl.log"

    def run_task(self, task: dict, fake_mode: str = "ok",
                 settings: dict | None = None) -> dict:
        task = {"id": "t1", "prompt": "how is the house?", "ts": time.time(),
                "timeout": 120, **task}
        (self.tmp / "tasks" / "t1.json").write_text(json.dumps(task))
        if settings is not None:
            self.settings.write_text(json.dumps(settings))
        body = "\n\n".join(lift(n) for n in LIFTED)
        body = body.replace("cd /config", 'cd "$WORK_DIR"')
        script = "\n".join([
            "set -u",
            "bashio::log.info() { :; }", "bashio::log.warning() { :; }",
            "bashio::log.error() { :; }", "bashio::log.debug() { :; }",
            "verify_mcp_config_fast() { :; }",
            "verify_mcp_config_full() { :; }",
            "cleanup_stale_files() { :; }",
            # The event and the notification, captured rather than posted.
            # One line per call, the pretty-printed payload folded into it.
            'curl() { printf "%s" "$*" | tr "\\n" " " >> "$CURL_LOG";'
            + ' echo >> "$CURL_LOG"; }',
            f'TASKS_DIR="{self.tmp}/tasks"', f'RESULTS_DIR="{self.tmp}/results"',
            f'LOG_DIR="{self.tmp}/logs"', f'SHARED_DIR="{self.tmp}"',
            'MAX_TURNS=200', 'CLAUDE_TIMEOUT=300', 'TIMEOUT_MARGIN=15',
            'SUPERVISOR_TOKEN=""',
            f'CLAUDE_BIN="{sys.executable} {FAKE_CLAUDE}"',
            lift_line("AUTH_REMEDY="),
            lift_line("export BRAIN_CHANNEL="),
            body,
            f'process_task "{self.tmp}/tasks/t1.json"',
            # The journal row is written in the background, after the
            # result; waited for here so the test can read it.
            "wait",
        ])
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.tmp),
            "WORK_DIR": str(self.tmp / "work"),
            "CURL_LOG": str(self.curl_log),
            "FAKE_MODE": fake_mode,
            "FAKE_CLAUDE_LOG": str(self.argv_log),
            "BRAIN_PANEL_DIR": str(PANEL_DIR),
            "BRAIN_SCRIPTS_DIR": str(SCRIPTS_DIR),
            "BRAIN_JOURNAL_FILE": str(self.journal),
            "BRAIN_USAGE_NUDGE": str(self.tmp / "usage-nudge"),
            "BRAIN_USAGE_FILE": str(self.tmp / "usage.json"),
            "BRAIN_USAGE_LIMITS": str(self.tmp / "usage_limits.json"),
            "BRAIN_SETTINGS_FILE": str(self.settings),
            "BRAIN_MEMORY_FILE": str(self.memory),
            "BRAIN_FACTS_FILE": str(self.tmp / "facts.json"),
            "BRAIN_FACTS_INGEST_STATE": str(self.tmp / "facts-ingest.json"),
        }
        proc = subprocess.run(["bash", "-c", script], env=env,
                              capture_output=True, text=True, timeout=120,
                              check=False)
        out = self.tmp / "results" / "t1.json"
        self.assertTrue(out.is_file(),
                        f"no result file written\n{proc.stdout}\n{proc.stderr}")
        return json.loads(out.read_text())

    def claude_ran(self) -> bool:
        return self.argv_log.is_file() and self.argv_log.read_text().strip() != ""

    def journal_rows(self) -> list[dict]:
        if not self.journal.is_file():
            return []
        return [json.loads(line) for line in
                self.journal.read_text().splitlines() if line.strip()]


class TestTheResultSaysItFailed(ListenerCase):

    def test_an_answer_is_completed_and_carries_no_error(self):
        result = self.run_task({})
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("error", result)
        self.assertIn("ONESHOT", result["result"])

    def test_an_expired_login_is_a_failed_task_naming_the_panel_button(self):
        """Before: `status: completed`, and the text told somebody to run
        `/login` in a terminal the panel may not even have."""
        result = self.run_task({}, fake_mode="autherror")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "auth")
        self.assertIn("Sign in again", result["result"])
        self.assertNotIn("/login", result["result"])
        self.assertNotIn("OAuth session expired", result["result"])

    def test_a_turn_cap_with_no_landing_is_a_failed_task_in_words(self):
        """An `error_max_turns` envelope has an empty `.result`, so what
        reached the caller was the raw JSON. It is a failure, coded, with a
        sentence a person can act on."""
        result = self.run_task({}, fake_mode="max_turns")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "max_turns")
        self.assertNotIn('"subtype"', result["result"])
        self.assertIn("turn limit", result["result"])

    def test_the_event_carries_the_same_status(self):
        self.run_task({}, fake_mode="autherror")
        posted = self.curl_log.read_text()
        event = [line for line in posted.splitlines()
                 if "brain_task_complete" in line]
        self.assertTrue(event, posted)
        self.assertIn('"status":"failed"', event[0].replace(" ", ""))
        self.assertIn('"error":"auth"', event[0].replace(" ", ""))

    def test_the_mcp_server_a_task_launches_is_told_it_is_a_task(self):
        """The server's per-channel rules key on `BRAIN_CHANNEL`, and a task
        that said nothing was read as whichever channel the default is."""
        self.run_task({})
        lines = self.argv_log.read_text().splitlines()
        self.assertIn("ENV BRAIN_CHANNEL=task", lines)

    def test_a_failed_and_an_answered_task_are_both_journaled(self):
        """A task ran Claude in a process of its own and nothing counted it,
        so a failing one reported nothing anywhere."""
        self.run_task({}, fake_mode="autherror")
        self.run_task({})
        rows = self.journal_rows()
        self.assertEqual([r["source"] for r in rows], ["task", "task"], rows)
        self.assertEqual([r["outcome"] for r in rows], ["auth", "ok"])


class TestAScheduledRunAnswersToThePanel(ListenerCase):
    """An insight job's timer is a run nobody pressed, and every other
    unattended Claude run in the add-on stops for the pause switch and the
    usage budget. This one did not."""

    def test_a_paused_house_skips_a_scheduled_run_and_spends_nothing(self):
        result = self.run_task({"scheduled": True},
                               settings={"auto_enabled": False})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "paused")
        self.assertIn("Automatic insights", result["result"])
        self.assertFalse(self.claude_ran(), "a paused house spent a run")
        # A refusal doing its job is not a fault: nothing ran, nothing is
        # journaled.
        self.assertEqual(self.journal_rows(), [])

    def test_a_press_runs_whatever_the_switch_says(self):
        result = self.run_task({"scheduled": False},
                               settings={"auto_enabled": False})
        self.assertEqual(result["status"], "completed")
        self.assertTrue(self.claude_ran())

    def test_an_unreadable_panel_lets_the_run_go(self):
        """The gate is a budget and not a safety scope: "I could not read
        the settings" must not silently stop every report a house has."""
        self.settings.write_text("{ not json")
        result = self.run_task({"scheduled": True})
        self.assertEqual(result["status"], "completed")


class TestTheInsightPromptCarriesWhatBrainKnows(ListenerCase):

    def test_memory_rides_in_front_of_the_prompt_when_asked_for(self):
        self.memory.write_text("## Devices\n- The beer fridge is the garage plug.\n")
        result = self.run_task({"memory": True, "prompt": "Morning report"})
        # The fake CLI echoes what it was handed on stdin.
        self.assertIn("Known about this home:", result["result"])
        self.assertIn("beer fridge", result["result"])
        self.assertLess(result["result"].index("beer fridge"),
                        result["result"].index("Morning report"))

    def test_no_memory_unless_the_task_asked(self):
        self.memory.write_text("- The beer fridge is the garage plug.\n")
        result = self.run_task({"prompt": "Morning report"})
        self.assertNotIn("beer fridge", result["result"])


# ---------------------------------------------------------------------------
# The other half of the wire: the real bridge reading a failed result
# ---------------------------------------------------------------------------


def load_bridge(tmp: Path):
    """The real bridge.py, with homeassistant.core stubbed and sys.modules
    put back afterwards (other modules install their own stubs)."""
    saved = {k: sys.modules.get(k) for k in (
        "homeassistant", "homeassistant.core", "brain_task_bridge",
        "brain_task_bridge.bridge", "brain_task_bridge.const")}
    try:
        ha = types.ModuleType("homeassistant")
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = type("HomeAssistant", (), {})
        sys.modules["homeassistant"] = ha
        sys.modules["homeassistant.core"] = core
        pkg = types.ModuleType("brain_task_bridge")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_task_bridge"] = pkg
        import importlib  # noqa: PLC0415
        return importlib.import_module("brain_task_bridge.bridge")
    finally:
        for key, value in saved.items():
            if key.startswith("brain_task_bridge"):
                continue
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


class FakeHass:
    def __init__(self, base: Path):
        self.base = base
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(str(base), *parts))

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class TestTheBridgeRaisesOnAFailedResult(ListenerCase):

    def _bridge_answer(self, result_file: dict):
        bridge_mod = load_bridge(self.tmp)
        hass = FakeHass(self.tmp)
        bridge = bridge_mod.ClaudeBridge(hass, timeout=10)

        async def main():
            async def answer_later():
                # Whatever task the bridge wrote, answered with this file.
                for _ in range(200):
                    names = [n for n in os.listdir(bridge.tasks_dir)
                             if n.endswith(".json")] \
                        if os.path.isdir(bridge.tasks_dir) else []
                    if names:
                        task = json.loads(
                            Path(bridge.tasks_dir, names[0]).read_text())
                        os.makedirs(bridge.task_results_dir, exist_ok=True)
                        Path(bridge.task_results_dir,
                             f"{task['id']}.json").write_text(
                                 json.dumps({"id": task["id"], **result_file}))
                        return
                    await asyncio.sleep(0.02)

            helper = asyncio.ensure_future(answer_later())
            try:
                return await bridge.async_send_task_full(
                    prompt="p", timeout=10, tools="read_only")
            finally:
                await helper
        return bridge_mod, asyncio.new_event_loop().run_until_complete(main())

    def test_a_result_the_listener_wrote_as_failed_raises(self):
        """Driven off the file the real listener writes, not a copy of it."""
        written = self.run_task({}, fake_mode="autherror")
        bridge_mod = load_bridge(self.tmp)
        with self.assertRaises(bridge_mod.BrainRunError) as caught:
            self._bridge_answer({k: v for k, v in written.items()
                                 if k != "id"})
        self.assertEqual(caught.exception.code, "auth")
        self.assertIn("Sign in again", caught.exception.text)

    def test_a_completed_result_is_an_answer(self):
        _mod, answer = self._bridge_answer(
            {"result": "All quiet.", "status": "completed"})
        self.assertEqual(answer["text"], "All quiet.")

    def test_a_result_from_an_older_listener_with_no_status_is_an_answer(self):
        _mod, answer = self._bridge_answer({"result": "All quiet."})
        self.assertEqual(answer["text"], "All quiet.")


if __name__ == "__main__":
    unittest.main()
