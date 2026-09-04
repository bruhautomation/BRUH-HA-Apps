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
from unittest import mock

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
        self.log = Path(self.tmp.name) / "argv.log"
        shim = Path(self.tmp.name) / "claude"
        shim.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} \"$@\"\n")
        shim.chmod(0o755)
        self.env = mock.patch.dict(os.environ, {
            "BRAIN_CLAUDE_BIN": str(shim), "FAKE_CLAUDE_LOG": str(self.log),
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-" + "x" * 30})
        self.env.start()
        self.proj = mock.patch.object(engine, "HA_PROJECT", str(self.project))
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
        engine.run_agent("p", "s", timeout=30, max_turns=1)
        argv = self._argv()
        self.assertEqual(self._after(argv, "--mcp-config"),
                         str(self.project / ".mcp.json"))
        self.assertEqual(self._after(argv, "--add-dir"), str(self.project))
        self.assertEqual(self._after(argv, "--settings"),
                         str(self.project / ".claude" / "settings.local.json"))

    def test_the_analyst_gets_the_server_and_nothing_that_widens_it(self):
        engine.run_analyst("p", "s", timeout=30, max_turns=1)
        argv = self._argv()
        self.assertEqual(self._after(argv, "--mcp-config"),
                         str(self.project / ".mcp.json"))
        # Its allow-list is the whole answer; the project's permission file
        # pre-approves Bash and Write, which an unattended run may not have.
        self.assertNotIn("--settings", argv)
        self.assertNotIn("--add-dir", argv)

    def test_a_snapshot_run_starts_no_server(self):
        engine.run_claude("p", "s", timeout=30)
        self.assertNotIn("--mcp-config", self._argv())

    def test_a_missing_project_adds_no_flag_at_all(self):
        with mock.patch.object(engine, "HA_PROJECT",
                               str(Path(self.tmp.name) / "nowhere")):
            engine.run_agent("p", "s", timeout=30, max_turns=1)
        argv = self._argv()
        for flag in ("--mcp-config", "--add-dir", "--settings"):
            self.assertNotIn(flag, argv)


if __name__ == "__main__":
    unittest.main()
