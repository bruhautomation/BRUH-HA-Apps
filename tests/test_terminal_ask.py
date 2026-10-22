"""The Ask tab is Claude Code's own terminal, and the panel opens windows on it.

Three things are driven here rather than described:

- the handoff file the panel writes carries a first message, and the real
  `brain-terminal-start.sh` hands those words to the CLI as one argument,
  quotes and newlines intact, with brAIn's appended prompt beside them;
- a message that opens with "-" is not read as a flag;
- a settings file written before 4.0 (which wrote "chat" back on every save)
  reads as the terminal face, while a choice made since is kept.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = BASE_DIR / "brain" / "scripts"
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import chat_session  # noqa: E402
import settings_store  # noqa: E402


def _json_recorder(path: Path, log: Path) -> None:
    """A claude-run stand-in that records its argv as JSON, so an argument
    holding a newline is still one argument."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
    path.chmod(0o755)


class TestTheWindowOpensWithTheWords(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.handoff = root / "terminal-handoff.json"
        self.prompt_file = root / "brain-terminal-prompt.md"
        self.log = root / "argv.json"
        self.run = root / "claude-run"
        _json_recorder(self.run, self.log)
        self.env = {
            "PATH": os.environ["PATH"],
            "BRAIN_TERMINAL_HANDOFF": str(self.handoff),
            "BRAIN_TERMINAL_PROMPT_FILE": str(self.prompt_file),
            "BRAIN_PERMISSIONS_FILE": str(root / "no-perms"),
            "BRAIN_PERMS_ENV_FILE": str(root / "no-env"),
            "BRAIN_CLAUDE_RUN": str(self.run),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _start(self) -> list:
        out = subprocess.run(
            ["bash", str(SCRIPTS / "brain-terminal-start.sh")],
            env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(self.log.read_text())

    def _write_handoff(self, session_id="", prompt=""):
        with mock.patch.object(chat_session, "HANDOFF_FILE", str(self.handoff)), \
                mock.patch.object(chat_session, "_tmux_argv",
                                  return_value=["false"]), \
                mock.patch.object(os, "chown"):
            chat_session._open_in_terminal(session_id, prompt)

    def test_the_first_message_is_one_argument_with_its_quotes_and_lines(self):
        words = 'Tell me about "the garage light".\nIt keeps coming on; why?'
        self._write_handoff(prompt=words)
        record = json.loads(self.handoff.read_text())
        self.assertNotIn("session_id", record)
        self.assertEqual(base64.b64decode(record["prompt_b64"]).decode(), words)
        argv = self._start()
        self.assertEqual(argv[-1], words)
        self.assertNotIn("--resume", argv)
        self.assertFalse(self.handoff.exists(), "a handoff is taken once")

    def test_a_conversation_and_a_message_resume_that_conversation(self):
        self._write_handoff("abc-123", "carry on")
        argv = self._start()
        self.assertEqual(argv[:2], ["--resume", "abc-123"])
        self.assertEqual(argv[-1], "carry on")

    def test_a_message_opening_with_a_dash_is_not_a_flag(self):
        self._write_handoff(prompt="--dangerously-skip-permissions please")
        argv = self._start()
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertEqual(argv[-1].strip(), "--dangerously-skip-permissions please")

    def test_brains_prompt_rides_beside_it(self):
        self.prompt_file.write_text("You are brAIn.")
        self._write_handoff(prompt="hello")
        argv = self._start()
        i = argv.index("--append-system-prompt")
        self.assertEqual(argv[i + 1], "You are brAIn.")
        self.assertEqual(argv[-1], "hello")

    def test_an_old_handoff_opens_nothing(self):
        self.handoff.write_text(json.dumps({
            "ts": int(time.time()) - 3600,
            "prompt_b64": base64.b64encode(b"stale").decode()}))
        self.assertEqual(self._start(), [])

    def test_a_long_message_is_cut_to_the_cap(self):
        self._write_handoff(prompt="x" * (chat_session.TERMINAL_PROMPT_MAX + 50))
        record = json.loads(self.handoff.read_text())
        self.assertEqual(len(base64.b64decode(record["prompt_b64"])),
                         chat_session.TERMINAL_PROMPT_MAX)


class TestTheFaceIsTheTerminal(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.patch = mock.patch.object(settings_store, "SETTINGS_FILE", self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_a_file_saved_before_the_change_reads_as_the_terminal(self):
        self.path.write_text(json.dumps({"terminal_ui": "chat"}))
        self.assertEqual(settings_store.load()["terminal_ui"], "classic")

    def test_a_choice_made_since_is_kept(self):
        settings_store.save({"terminal_ui": "chat"})
        self.assertEqual(settings_store.load()["terminal_ui"], "chat")
        # …and survives a later save of something else.
        settings_store.save({"auto_enabled": False})
        self.assertEqual(settings_store.load()["terminal_ui"], "chat")


if __name__ == "__main__":
    unittest.main()


class TestDiscussOpensTheTerminal(unittest.IsolatedAsyncioTestCase):
    """With the terminal face (the default), Discuss on a card opens a
    terminal window whose first message is the card, and spawns no chat."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        env = {
            "BRAIN_SETTINGS_FILE": str(root / "settings.json"),
            "BRAIN_FINDINGS_FILE": str(root / "findings.json"),
        }
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        import importlib
        import findings_store
        importlib.reload(settings_store)
        self.findings_store = findings_store
        self.server = importlib.import_module("server")
        self.patches = [
            mock.patch.object(settings_store, "SETTINGS_FILE", str(root / "settings.json")),
            mock.patch.object(findings_store, "FINDINGS_FILE", root / "findings.json"),
            mock.patch.object(self.server, "TERMINAL_PROMPT_FILE", root / "prompt.md"),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    async def test_the_card_is_the_windows_first_message(self):
        entry, _ = self.findings_store.add(
            "Porch light never comes on", entity_id="light.porch",
            source="check:auto.dead_ref")
        opened = []

        def fake_open(session_id="", prompt=""):
            opened.append((session_id, prompt))
            return True

        from aiohttp.test_utils import make_mocked_request
        req = make_mocked_request("POST", f"/api/finding/{entry['ts']}/discuss",
                                  match_info={"ts": str(entry["ts"])})
        with mock.patch.object(chat_session, "_open_in_terminal", fake_open), \
                mock.patch.object(self.server, "_chat_registry",
                                  side_effect=AssertionError("no chat spawned")):
            res = await self.server.h_finding_discuss(req)
        self.assertEqual(res.status, 200)
        data = json.loads(res.body)
        self.assertEqual(data["face"], "terminal")
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0][0], "")
        self.assertIn("Porch light never comes on", opened[0][1])
        self.assertTrue((Path(self.tmp.name) / "prompt.md").read_text().startswith(
            "You are brAIn"))


class TestDevelopmentModeIsSaidToEverySession(unittest.TestCase):
    """Development mode is opt-in, and the appended prompt says which it is."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import importlib
        self.server = importlib.import_module("server")
        self.devloop = self.server.devloop
        self.patch = mock.patch.object(self.devloop, "DATA_DIR", Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_off_by_default_and_on_only_with_both_switches(self):
        self.assertFalse(self.server.development_mode())
        self.assertIn(self.server.DEVELOPMENT_MODE_OFF, self.server._chat_system_prompt(None))
        self.devloop.save_settings({"enabled": True})
        self.assertFalse(self.server.development_mode())
        self.devloop.save_settings({"autopilot": True})
        self.assertTrue(self.server.development_mode())
        self.assertIn(self.server.DEVELOPMENT_MODE_ON, self.server._chat_system_prompt(None))
