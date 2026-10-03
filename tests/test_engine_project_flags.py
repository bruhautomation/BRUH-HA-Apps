"""The engine runs from CLAUDE_HOME and has to be LENT the Home Assistant
project, or the analyst has no tools and the fixer reports, accurately,
that it is confined to /data/home. Driven through the fake CLI's argv
log, not grepped."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "brain" / "panel"))

import engine  # noqa: E402

FAKE = REPO_ROOT / "tests" / "fake_claude.py"


class TestProjectFlags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "config"
        (self.project / ".claude").mkdir(parents=True)
        (self.project / ".mcp.json").write_text("{}")
        (self.project / ".claude" / "settings.local.json").write_text("{}")
        # The headless allow-list run.sh writes beside the project, which
        # is what the fixer is lent now instead of the shared file.
        (self.project / ".brain").mkdir()
        self.headless = self.project / ".brain" / "headless_settings.json"
        self.headless.write_text('{"permissions": {"allow": ["Bash(*)"]}}')
        self.log = Path(self.tmp.name) / "argv.log"
        shim = Path(self.tmp.name) / "claude"
        shim.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
        shim.chmod(0o755)
        self.env = unittest.mock.patch.dict(os.environ, {
            "BRAIN_CLAUDE_BIN": str(shim), "FAKE_CLAUDE_LOG": str(self.log),
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-" + "x" * 30})
        self.env.start()
        os.environ.pop("BRAIN_HEADLESS_SETTINGS", None)
        self.proj = unittest.mock.patch.object(engine, "HA_PROJECT", str(self.project))
        self.proj.start()

    def tearDown(self):
        self.proj.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _argv(self) -> list[str]:
        # The fake logs one JSON array per invocation and an ENV line after.
        rows = [ln for ln in self.log.read_text().splitlines()
                if ln.startswith("[")]
        return json.loads(rows[-1])

    def _after(self, argv: list[str], flag: str) -> str | None:
        return argv[argv.index(flag) + 1] if flag in argv else None

    def test_the_fixer_is_lent_the_server_the_files_and_the_permissions(self):
        """The permissions are the HEADLESS file now, not the shared
        project one: the shared file is what the interactive terminal and
        the chat load too, and a person at a prompt should be asked."""
        engine.run_agent("p", "s", timeout=30, max_turns=1)
        argv = self._argv()
        self.assertEqual(self._after(argv, "--mcp-config"),
                         str(self.project / ".mcp.json"))
        self.assertEqual(self._after(argv, "--add-dir"), str(self.project))
        self.assertEqual(self._after(argv, "--settings"), str(self.headless))
        self.assertIn("--strict-mcp-config", argv)
        # No setting SOURCE: from CLAUDE_HOME the user file and the
        # "project" one are the same file, which is the one /advisor
        # writes to.
        self.assertEqual(self._after(argv, "--setting-sources"), "")

    def test_the_analyst_gets_the_server_and_nothing_that_widens_it(self):
        engine.run_analyst("p", "s", timeout=30, max_turns=1)
        argv = self._argv()
        self.assertEqual(self._after(argv, "--mcp-config"),
                         str(self.project / ".mcp.json"))
        # Its allow-list is the whole answer: the settings it is handed
        # are the isolation floor and grant nothing.
        settings = json.loads(self._after(argv, "--settings"))
        self.assertNotIn("allow", settings.get("permissions", {}))
        self.assertEqual(settings["crossSessionInbound"], "refuse")
        self.assertIs(settings["autoMemoryEnabled"], False)
        self.assertNotIn("--add-dir", argv)
        # The built-in harness is off the run and only the one server loads.
        self.assertEqual(self._after(argv, "--tools"), "")
        self.assertIn("--strict-mcp-config", argv)
        self.assertEqual(self._after(argv, "--setting-sources"), "")

    def test_a_snapshot_run_starts_no_server(self):
        engine.run_claude("p", "s", timeout=30)
        self.assertNotIn("--mcp-config", self._argv())

    def test_a_missing_project_adds_no_flag_at_all(self):
        with unittest.mock.patch.object(engine, "HA_PROJECT",
                               str(Path(self.tmp.name) / "nowhere")):
            engine.run_agent("p", "s", timeout=30, max_turns=1)
        argv = self._argv()
        for flag in ("--mcp-config", "--add-dir"):
            self.assertNotIn(flag, argv)
        # With no headless file to lend, the fixer stands on the same
        # isolation floor every other run does — and is granted nothing.
        settings = json.loads(self._after(argv, "--settings"))
        self.assertNotIn("allow", settings.get("permissions", {}))

    def _every_argv(self) -> list[list[str]]:
        return [json.loads(ln) for ln in self.log.read_text().splitlines()
                if ln.startswith("[")]

    def _once_each(self, argv: list[str]) -> None:
        for flag in ("--mcp-config", "--add-dir", "--settings",
                     "--allowedTools", "--disallowedTools",
                     "--append-system-prompt"):
            self.assertLessEqual(argv.count(flag), 1, f"{flag} twice: {argv}")

    def test_no_project_flag_is_sent_twice_on_any_path(self):
        """A flag sent twice leaves the CLI to pick one, and `--settings`
        is the permission file — "which of two did it read" is not a
        question an unattended run should be left to answer. Every path
        that re-spawns rebuilds the argv (the overload retry, the landing),
        so each invocation is checked, not just the last."""
        for runner in (engine.run_agent, engine.run_analyst, engine.run_claude):
            runner("p", "s", timeout=30, max_turns=1)
        once = Path(self.tmp.name) / "once"
        with unittest.mock.patch.dict(os.environ, {
                "FAKE_MODE": "overloaded_then_ok", "FAKE_ONCE_FILE": str(once)}), \
                unittest.mock.patch.object(engine, "OVERLOAD_RETRY_S", 0), \
                unittest.mock.patch.object(engine, "LANDING_MIN_S", 0):
            engine.run_agent("p", "s", timeout=30, max_turns=1)
        with unittest.mock.patch.dict(os.environ, {"FAKE_MODE": "max_turns_then_land"}), \
                unittest.mock.patch.object(engine, "LANDING_MIN_S", 0):
            engine.run_agent("p", "s", timeout=30, max_turns=1)
        argvs = self._every_argv()
        # Three plain runs, the 529 and its retry, the capped run and its
        # landing: seven spawns, and the retry and the landing both happened.
        self.assertEqual(len(argvs), 7)
        self.assertTrue(any("--resume" in a for a in argvs))
        for argv in argvs:
            self._once_each(argv)
        # Every engine run takes its settings by flag (`isolation_flags`):
        # the isolation JSON for a run that reads, the headless allow-list
        # file — which carries the same keys — for the agent that acts. So
        # every one of the seven carries `--settings`, and once.
        self.assertEqual(sum("--settings" in a for a in argvs), 7)


if __name__ == "__main__":
    unittest.main()
