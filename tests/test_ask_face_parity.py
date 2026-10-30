#!/usr/bin/env python3
"""The chat and the terminal are one Claude Code, launched the same way.

Ask has two faces (`terminal_ui`): "chat" renders Claude Code as messages,
"classic" is ttyd + tmux. The owner's rule is that they behave the same,
and the "What brAIn brings to a run" page found they did not: only the
chat's own `--settings` carried the `UserPromptSubmit` hook that hands a
message the facts matching it, so the same words typed in the terminal
were handed nothing.

Driven here, through the real code paths rather than described:

* what the panel writes for a terminal session (`_write_terminal_prompt`)
  carries the chat's hook — the same entry, from one definition — and the
  real `brain-terminal-start.sh` puts it on the CLI's argv;
* the hook script, run with a terminal session's input shape against a
  fake panel, asks the same route and prints the same context as it does
  for the chat's;
* both faces' launch configuration, built by their real builders, matches
  field by field: the appended prompt, the hooks, the model, the
  permission mode (and the platform deny-list beside it), the MCP servers
  and project settings (neither narrows them) and the working directory;
* the session picker (auto-launch off) starts its sessions through the
  same start script, so it is the terminal too;
* Discuss on the terminal face is told to make a change it is asked for,
  as the chat is, rather than nothing.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
HOOK = SCRIPTS / "brain-chat-context.py"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(BASE_DIR / "tests"))

from test_chat_context import FakePanel, load_hook  # noqa: E402

pytestmark = pytest.mark.slow

FLAG = "--dangerously-skip-permissions"


def _recorder(path: Path, log: Path) -> None:
    """A claude-run stand-in that records its argv as JSON."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
    path.chmod(0o755)


def _value(argv: list, flag: str) -> str:
    return argv[argv.index(flag) + 1] if flag in argv else ""


class _Faces(unittest.TestCase):
    """The server's builders over a temporary /data, and the real start
    script over a recording claude-run."""

    def setUp(self):
        import chat_session
        import engine
        import server
        import settings_store
        self.server, self.chat_session = server, chat_session
        self.engine, self.settings_store = engine, settings_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.prompt_file = root / "brain-terminal-prompt.md"
        self.settings_file = root / "brain-terminal-settings.json"
        self.perms = root / "brain-permissions"
        self.log = root / "argv.json"
        self.run = root / "claude-run"
        _recorder(self.run, self.log)
        patches = [
            unittest.mock.patch.object(server, "TERMINAL_PROMPT_FILE",
                                       self.prompt_file),
            unittest.mock.patch.object(server, "TERMINAL_SETTINGS_FILE",
                                       self.settings_file),
            unittest.mock.patch.object(chat_session, "CONTEXT_HOOK", str(HOOK)),
            unittest.mock.patch.object(settings_store, "SETTINGS_FILE",
                                       root / "settings.json"),
            unittest.mock.patch.dict(os.environ, {
                "BRAIN_CLAUDE_BIN": str(FAKE)}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.env = {
            "PATH": os.environ["PATH"],
            "BRAIN_TERMINAL_HANDOFF": str(root / "terminal-handoff.json"),
            "BRAIN_TERMINAL_PROMPT_FILE": str(self.prompt_file),
            "BRAIN_TERMINAL_SETTINGS_FILE": str(self.settings_file),
            "BRAIN_PERMISSIONS_FILE": str(self.perms),
            "BRAIN_PERMS_ENV_FILE": str(root / "no-env"),
            "BRAIN_PERMS_LIB": str(SCRIPTS / "brain-permissions.sh"),
            "BRAIN_CLAUDE_RUN": str(self.run),
        }

    def terminal_argv(self, *args) -> list:
        """What a terminal session starting now runs, written the way the
        panel writes it when it opens a window."""
        self.assertTrue(self.server._write_terminal_prompt())
        out = subprocess.run(
            ["bash", str(SCRIPTS / "brain-terminal-start.sh"), *args],
            env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(self.log.read_text())

    def chat_argv(self, skip: bool, model: str) -> list:
        session = self.chat_session.ChatSession()
        session.skip_permissions = skip
        session.model = model
        return session._argv()


class TestTheTerminalIsHandedTheSameFacts(_Faces):

    def test_the_terminal_settings_carry_the_chats_hook(self):
        argv = self.terminal_argv()
        terminal = json.loads(_value(argv, "--settings"))
        chat = self.chat_session.ChatSession()._settings()
        self.assertEqual(terminal["hooks"], chat["hooks"])
        [entry] = terminal["hooks"]["UserPromptSubmit"]
        [hook] = entry["hooks"]
        self.assertEqual(hook["command"], f"python3 {HOOK}")
        self.assertEqual(hook["timeout"], self.chat_session.CONTEXT_HOOK_TIMEOUT)
        # Written from the one definition the chat reads.
        self.assertEqual(terminal["hooks"],
                         self.chat_session.conversation_settings()["hooks"])

    def test_a_missing_hook_script_is_named_on_neither_face(self):
        """Exit 2 from this hook blocks the prompt, and Python exits 2 for a
        script that is not there: a terminal must not refuse every message
        any more than the chat may."""
        with unittest.mock.patch.object(self.chat_session, "CONTEXT_HOOK",
                                        str(self.root / "gone.py")):
            argv = self.terminal_argv()
            settings = json.loads(_value(argv, "--settings") or "{}")
            self.assertNotIn("hooks", settings)
            self.assertNotIn("hooks", self.chat_session.ChatSession()._settings())

    def test_a_settings_file_that_does_not_parse_starts_the_terminal_anyway(self):
        self.settings_file.write_text("{not json")
        self.prompt_file.write_text("You are brAIn.")
        out = subprocess.run(
            ["bash", str(SCRIPTS / "brain-terminal-start.sh")],
            env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        argv = json.loads(self.log.read_text())
        self.assertNotIn("--settings", argv)
        self.assertIn("--append-system-prompt", argv)

    def test_a_terminal_without_the_file_starts_as_before(self):
        out = subprocess.run(
            ["bash", str(SCRIPTS / "brain-terminal-start.sh")],
            env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(self.log.read_text()), [])

    def test_the_hook_answers_a_terminal_message_as_it_answers_the_chats(self):
        """The interactive CLI hands the hook its own shape (it adds the
        permission mode); the route, the body and the context printed are
        the same as for the chat's message."""
        words = "why is the kitchen light on?"
        shapes = {
            "chat": {"session_id": "chat-1", "transcript_path": "/x/c.jsonl",
                     "cwd": "/config", "hook_event_name": "UserPromptSubmit",
                     "prompt": words},
            "terminal": {"session_id": "chat-1", "transcript_path": "/x/c.jsonl",
                         "cwd": "/config", "permission_mode": "default",
                         "hook_event_name": "UserPromptSubmit",
                         "prompt": words},
        }
        printed, asked = {}, {}
        for face, event in shapes.items():
            panel = FakePanel({"context": "The kitchen light is on a timer."})
            try:
                out = subprocess.run(
                    [sys.executable, str(HOOK)], input=json.dumps(event),
                    capture_output=True, text=True, timeout=20,
                    env={**os.environ, "BRAIN_PANEL_URL": panel.url})
            finally:
                panel.close()
            self.assertEqual(out.returncode, 0, out.stderr)
            printed[face] = json.loads(out.stdout)
            asked[face] = panel.seen
        self.assertEqual(printed["terminal"], printed["chat"])
        self.assertEqual(asked["terminal"], asked["chat"])
        self.assertEqual(asked["terminal"][0]["path"], "/api/chat/context")
        self.assertEqual(
            printed["terminal"]["hookSpecificOutput"]["additionalContext"],
            "The kitchen light is on a timer.")

    def test_a_terminal_with_no_panel_types_on(self):
        hook = load_hook()
        out = io.StringIO()
        with unittest.mock.patch.object(hook, "PANEL_URL", "http://127.0.0.1:9"):
            code = hook.main(io.StringIO(json.dumps({
                "prompt": "hello", "permission_mode": "default"})), out)
        self.assertEqual((code, out.getvalue()), (0, ""))


class TestBothFacesAreLaunchedAlike(_Faces):
    """One table, both faces, every field the owner's request names."""

    def _faces(self, skip: bool, model: str) -> dict:
        self.settings_store.save({"chat_model": model})
        self.perms.write_text("bypass\n" if skip else "ask\n")
        chat = self.chat_argv(skip, self.server.eff_chat_model())
        terminal = self.terminal_argv()
        return {"chat": chat, "terminal": terminal}

    @staticmethod
    def _launch(argv: list) -> dict:
        settings = json.loads(_value(argv, "--settings") or "{}")
        bypass = (FLAG in argv
                  or _value(argv, "--permission-mode") == "bypassPermissions")
        denied = set(settings.get("permissions", {}).get("deny", []))
        denied |= {t for t in _value(argv, "--disallowedTools").split(",") if t}
        return {
            "prompt": _value(argv, "--append-system-prompt"),
            "hooks": settings.get("hooks"),
            "model": _value(argv, "--model") or settings.get("model", ""),
            "bypass": bypass,
            "denied_in_bypass": sorted(denied) if bypass else None,
            # Neither face names its own MCP servers or narrows the
            # settings sources: both read /config/.mcp.json and
            # /config/.claude/settings.local.json (PreToolUse protect,
            # the action gate, the edit snapshot, the memory extractor's
            # Stop hook) from the directory they stand in.
            "mcp_flags": [a for a in argv if a.startswith(
                ("--mcp-config", "--strict-mcp-config", "--setting-sources"))],
        }

    def test_switch_off_with_a_model_picked(self):
        faces = self._faces(False, "claude-sonnet-4-5")
        chat, terminal = (self._launch(faces[f]) for f in ("chat", "terminal"))
        self.assertTrue(chat["prompt"])
        self.assertTrue(chat["hooks"])
        self.assertEqual(chat["model"], "claude-sonnet-4-5")
        self.assertFalse(chat["bypass"])
        for field in chat:
            self.assertEqual(terminal[field], chat[field], field)

    def test_switch_on_following_the_global_model(self):
        faces = self._faces(True, "")
        chat, terminal = (self._launch(faces[f]) for f in ("chat", "terminal"))
        self.assertTrue(chat["bypass"])
        self.assertTrue(set(self.engine.PLATFORM_DENIED)
                        <= set(chat["denied_in_bypass"]))
        for field in chat:
            self.assertEqual(terminal[field], chat[field], field)

    def test_both_faces_stand_in_the_same_directory(self):
        run = (BASE_DIR / "brain" / "run.sh").read_text()
        self.assertIn('CLAUDE_PROJECT_DIR="/config"', run)
        self.assertIn("-c '${CLAUDE_PROJECT_DIR}' '/usr/local/bin/brain-terminal-start'",
                      run)
        chat = (PANEL / "chat_session.py").read_text()
        self.assertIn('BRAIN_CHAT_WORKDIR", "/config"', chat)

    def test_picking_a_model_rewrites_what_the_next_terminal_starts_on(self):
        src = (PANEL / "server.py").read_text()
        start = src.index("async def h_chat_model(")
        body = src[start:src.index("\nasync def ", start + 10)]
        self.assertIn("_write_terminal_prompt", body)


class TestThePickerIsTheTerminalToo(unittest.TestCase):
    """With auto-launch off the picker starts the sessions, and they used to
    be bare `claude-run`: no prompt, no hook. They go through the start
    script now, which leaves a waiting handoff for the window it names."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "tmux.log"
        for name in ("sleep", "clear"):
            stub = self.bin / name
            stub.write_text("#!/bin/bash\nexit 0\n")
            stub.chmod(0o755)
        tmux = self.bin / "tmux"
        tmux.write_text(
            '#!/bin/bash\n'
            '[ "$1" = "has-session" ] && exit 1\n'
            '[ "$1" = "list-windows" ] && exit 0\n'
            f': > "{self.log}"\n'
            f'for a in "$@"; do printf "%s\\n" "$a" >> "{self.log}"; done\n')
        tmux.chmod(0o755)
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "BRAIN_PERMISSIONS_FILE": str(root / "perms"),
            "BRAIN_PERMS_ENV_FILE": str(root / "no-env"),
            "BRAIN_PERMS_LIB": str(SCRIPTS / "brain-permissions.sh"),
            "BRAIN_TASK_DIR": str(root / "tasks"),
            "CLAUDE_PROJECT_DIR": str(root),
        }

    def _picker(self, choice: str) -> str:
        out = subprocess.run(["bash", str(SCRIPTS / "brain-menu.sh")],
                             env=self.env, input=choice + "\n",
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return self.log.read_text().splitlines()[-1]

    def test_new_continue_and_resume_go_through_the_start_script(self):
        self.assertEqual(self._picker("1"),
                         "/usr/local/bin/brain-terminal-start --no-handoff")
        self.assertEqual(self._picker("2"),
                         "/usr/local/bin/brain-terminal-start --no-handoff -c")
        self.assertEqual(self._picker("3"),
                         "/usr/local/bin/brain-terminal-start --no-handoff -r")

    def test_no_handoff_leaves_the_waiting_request_alone(self):
        handoff = self.root / "terminal-handoff.json"
        handoff.write_text(json.dumps({"ts": 9999999999, "session_id": "abc"}))
        log = self.root / "argv.json"
        run = self.root / "claude-run"
        _recorder(run, log)
        out = subprocess.run(
            ["bash", str(SCRIPTS / "brain-terminal-start.sh"), "--no-handoff", "-c"],
            env={**self.env, "BRAIN_CLAUDE_RUN": str(run),
                 "BRAIN_TERMINAL_HANDOFF": str(handoff),
                 "BRAIN_TERMINAL_PROMPT_FILE": str(self.root / "none.md"),
                 "BRAIN_TERMINAL_SETTINGS_FILE": str(self.root / "none.json")},
            capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(log.read_text()), ["-c"])
        self.assertTrue(handoff.exists())


class TestDiscussOnTheTerminalMayAct(unittest.TestCase):
    """The chat's discussion is told to make a change it is asked for; the
    terminal's was told nothing, so the same card read differently on the
    two faces. Only the buttons (offer_resolutions, a plan) stay the
    chat's: the terminal has nothing to draw them on."""

    def test_the_terminal_opener_says_to_make_the_change(self):
        import server
        row = {"ts": 1, "text": "Garage freezer warm", "severity": "warning",
               "entity_id": "sensor.garage_freezer"}
        terminal = server._discuss_prompt(row, offer=False, act=True)
        self.assertIn("make the change here", terminal)
        self.assertNotIn("offer_resolutions", terminal)
        self.assertNotIn("approval card", terminal)
        phone = server._discuss_prompt(row, offer=False)
        self.assertNotIn("make the change here", phone)


if __name__ == "__main__":
    unittest.main()
