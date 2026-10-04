#!/usr/bin/env python3
""""Let brAIn act without asking" — one switch, two doors, two faces.

The add-on option `dangerously_skip_permissions` used to reach the classic
terminal only, as a flag baked into the command ttyd was started with at
boot, so a change needed an add-on restart and the chat went on asking
whatever it said. It is one switch now:

* **two doors that agree** — ⚙ → Terminal & chat writes the add-on's own
  option through the Supervisor, and a Configuration-tab edit shows in ⚙;
* **the terminal reads it when a session STARTS**, off a one-word file the
  panel publishes (`permission_mode.publish`) and run.sh writes at boot,
  through `scripts/brain-permissions.sh`, which only ever fails toward
  asking;
* **the chat spawns with `--permission-mode bypassPermissions`**, applied
  to an idle conversation on its next message through the respawn `send`
  already does, while a discussion always names `default`.

Everything here drives the real code: the shell library and both launchers
run as the subprocesses they are, run.sh's boot writer is lifted out of the
real file and run, the chat spawns the fake CLI and its argv is read back
off the fake's own log, and the mirror goes through the panel's real routes
against a fake Supervisor speaking the real endpoints.
"""

import asyncio
import importlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
RUN_SH = BASE_DIR / "brain" / "run.sh"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"
LIB = SCRIPTS / "brain-permissions.sh"
FLAG = "--dangerously-skip-permissions"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import addon_options  # noqa: E402
import permission_mode  # noqa: E402
import settings_store  # noqa: E402
from test_insights_option_sync import SupervisorMixin  # noqa: E402


def _read_flag(env: dict) -> str:
    """Source the REAL library and print what it says a session starts with."""
    out = subprocess.run(
        ["bash", "-c", f'. "{LIB}"; brain_perms_flag'],
        env={"PATH": os.environ["PATH"], **env},
        capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


class TestTheShellReader(unittest.TestCase):
    """`brain_perms_flag`, the one reader both launchers ask."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name, "brain-permissions")
        self.env_file = Path(self.tmp.name, "brain_env")
        self.env = {"BRAIN_PERMISSIONS_FILE": str(self.file),
                    "BRAIN_PERMS_ENV_FILE": str(self.env_file)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_bypass_is_the_one_word_that_acts(self):
        for text in ("bypass", "bypass\n", "  bypass  \n"):
            self.file.write_text(text)
            self.assertEqual(_read_flag(self.env), FLAG, repr(text))

    def test_ask_and_garbage_both_mean_asking(self):
        # Garbage must mean asking — and a value that merely CONTAINS the
        # word is garbage, or a half-written file reading "bypassXX" or a
        # stray "nobypass" would act.
        for text in ("ask", "ask\n", "", "\n", "true", "yes", "BYPASS",
                     "bypassed", "nobypass", "bypass ask", FLAG,
                     "\x00\x01garbage"):
            self.file.write_text(text)
            self.assertEqual(_read_flag(self.env), "", repr(text))

    def test_garbage_does_not_fall_back_to_the_boot_value(self):
        """Something at the path that cannot be read is not the same claim
        as nothing having been written — only an ABSENT file falls back."""
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        self.file.write_text("garbage")
        self.assertEqual(_read_flag(self.env), "")
        self.file.unlink()
        self.file.mkdir()          # a directory where the word should be
        self.assertEqual(_read_flag(self.env), "")
        self.file.rmdir()
        os.symlink(Path(self.tmp.name, "nowhere"), self.file)   # dangling
        self.assertEqual(_read_flag(self.env), "")

    @unittest.skipIf(os.geteuid() == 0, "root reads a 000 file anyway")
    def test_a_file_this_user_cannot_read_means_asking(self):
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        self.file.write_text("bypass")
        self.file.chmod(0)
        try:
            self.assertEqual(_read_flag(self.env), "")
        finally:
            self.file.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def test_an_absent_file_falls_back_to_exactly_the_boot_flag(self):
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        self.assertEqual(_read_flag(self.env), FLAG)
        # run.sh's OFF value is "", and `:-` reading that as unset is the
        # failure this library was written not to repeat.
        self.env_file.write_text('export BRAIN_CLAUDE_PERMS_FLAG=""\n')
        self.assertEqual(_read_flag(self.env), "")
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}x"\n')
        self.assertEqual(_read_flag(self.env), "")

    def test_nothing_at_all_means_asking(self):
        self.assertEqual(_read_flag(self.env), "")

    def test_the_panels_writer_and_the_terminals_reader_agree(self):
        """One file, two processes that cannot import each other: what the
        panel publishes is exactly what a session starts with."""
        with mock.patch.dict(os.environ,
                             {"BRAIN_PERMISSIONS_FILE": str(self.file)}):
            self.assertTrue(permission_mode.publish(True))
            self.assertEqual(_read_flag(self.env), FLAG)
            self.assertTrue(permission_mode.publish(False))
            self.assertEqual(_read_flag(self.env), "")

    def test_the_python_reads_agree_with_the_shell_reader(self):
        """`published` (the posture check's) and `boot_flag_set` (the
        publisher's last resort) read the same two files the shell reader
        does, and a file with two answers is two different switches — so
        they are driven over one set of files and compared."""
        env = {"BRAIN_PERMISSIONS_FILE": str(self.file),
               "BRAIN_PERMS_ENV_FILE": str(self.env_file)}
        with mock.patch.dict(os.environ, env):
            for text in ("bypass", "bypass\n", "  bypass  \n", "by pass",
                         "ask", "ask\n", "", "true", "BYPASS", "bypassed",
                         "bypass ask", "\x00garbage", "bypass\t\r\n"):
                self.file.write_text(text)
                self.assertEqual(permission_mode.published() is True,
                                 _read_flag(env) == FLAG, repr(text))
            self.file.unlink()
            self.assertIsNone(permission_mode.published())
            for text in (f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n',
                         'export BRAIN_CLAUDE_PERMS_FLAG=""\n',
                         f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}x"\n',
                         f'BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n',
                         f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n'
                         'export BRAIN_CLAUDE_PERMS_FLAG=""\n',
                         'export BRAIN_CLAUDE_PERMS_FLAG=""\n'
                         f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n',
                         "garbage\n", ""):
                self.env_file.write_text(text)
                self.assertEqual(permission_mode.boot_flag_set(),
                                 _read_flag(env) == FLAG, repr(text))
            self.env_file.unlink()
            self.assertFalse(permission_mode.boot_flag_set())

    def test_the_path_is_spelled_the_same_in_all_three(self):
        """A shell script, run.sh and a Python module each spell the path,
        and a rename in one of them goes silent in the others."""
        default = permission_mode.DEFAULT_FILE
        self.assertIn(f'BRAIN_PERMISSIONS_FILE:-{default}', LIB.read_text())
        self.assertIn(f'BRAIN_PERMISSIONS_FILE:-{default}', RUN_SH.read_text())
        self.assertIn(
            f'BRAIN_PERMS_ENV_FILE:-{permission_mode.DEFAULT_ENV_FILE}',
            LIB.read_text())


class TestThePublisher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name, "brain-permissions")
        self.env_file = Path(self.tmp.name, "brain_env")
        patcher = mock.patch.dict(os.environ,
                                  {"BRAIN_PERMISSIONS_FILE": str(self.file),
                                   "BRAIN_PERMS_ENV_FILE": str(self.env_file)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_it_writes_one_word_readable_by_the_terminal_user(self):
        self.assertTrue(permission_mode.publish(True))
        self.assertEqual(self.file.read_text(), "bypass\n")
        # The panel is root and the terminal is the `claude` user.
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o644)
        self.assertTrue(permission_mode.publish(False))
        self.assertEqual(self.file.read_text(), "ask\n")

    def test_an_unchanged_switch_writes_nothing(self):
        permission_mode.publish(True)
        before = self.file.stat().st_mtime_ns
        with mock.patch.object(permission_mode.atomic_write, "write_text",
                               side_effect=AssertionError("rewrote it")):
            self.assertTrue(permission_mode.publish(True))
        self.assertEqual(self.file.stat().st_mtime_ns, before)

    def _reader_env(self):
        return {"BRAIN_PERMISSIONS_FILE": str(self.file),
                "BRAIN_PERMS_ENV_FILE": str(self.env_file)}

    def test_a_failed_off_write_never_hands_back_to_a_boot_flag(self):
        """The failure the delete used to cause: the add-on booted with the
        switch ON, so the boot fallback IS the flag; the person turns it
        off, the write fails (a full SD card), and removing the stale
        `bypass` handed the next session straight back to that flag. The
        file is left EMPTY instead, which reads as asking whatever the
        boot value says — and the log line says what is true."""
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        self.assertTrue(permission_mode.publish(True))
        self.assertEqual(_read_flag(self._reader_env()), FLAG)
        full = OSError(28, "No space left on device")
        with mock.patch.object(permission_mode.atomic_write, "write_text",
                               side_effect=full), \
                self.assertLogs("brain.permissions", "WARNING") as logs:
            self.assertFalse(permission_mode.publish(False))
        self.assertTrue(self.file.exists(), "the path was left to the fallback")
        self.assertEqual(self.file.read_bytes(), b"")
        self.assertEqual(_read_flag(self._reader_env()), "")
        self.assertIn("will ask", "\n".join(logs.output))
        # And the next publish that CAN land writes the word again.
        self.assertTrue(permission_mode.publish(False))
        self.assertEqual(self.file.read_text(), "ask\n")

    def test_the_old_recipe_did_fail_open(self):
        """The delete, run on the same fixture, to show what was fixed: a
        missing file falls back to the boot flag."""
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        self.file.write_text("bypass\n")
        self.file.unlink()
        self.assertEqual(_read_flag(self._reader_env()), FLAG)

    def test_a_failed_write_with_nothing_there_still_leaves_an_empty_file(self):
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        with mock.patch.object(permission_mode.atomic_write, "write_text",
                               side_effect=OSError(28, "full")):
            self.assertFalse(permission_mode.publish(False))
        self.assertEqual(self.file.read_bytes(), b"")
        self.assertEqual(_read_flag(self._reader_env()), "")

    def test_a_symlink_is_replaced_not_followed(self):
        target = Path(self.tmp.name, "somebody-elses-file")
        target.write_text("precious\n")
        os.symlink(target, self.file)
        with mock.patch.object(permission_mode.atomic_write, "write_text",
                               side_effect=OSError(28, "full")):
            permission_mode.publish(False)
        self.assertEqual(target.read_text(), "precious\n")
        self.assertFalse(self.file.is_symlink())
        self.assertEqual(self.file.read_bytes(), b"")

    def test_a_path_that_cannot_be_cleared_is_kept_if_removing_it_would_act(self):
        """Removal is the last resort, and never while the boot value it
        hands the answer to is the flag. The error says nothing was fixed."""
        self.env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        self.file.write_text("bypass\n")
        real_open = os.open

        def refuse(path, *args, **kwargs):
            if str(path) == str(self.file):
                raise OSError(30, "Read-only file system")
            return real_open(path, *args, **kwargs)

        with mock.patch.object(permission_mode.atomic_write, "write_text",
                               side_effect=OSError(30, "ro")), \
                mock.patch.object(permission_mode.os, "open", refuse), \
                self.assertLogs("brain.permissions", "ERROR") as logs:
            self.assertFalse(permission_mode.publish(False))
        self.assertTrue(self.file.exists())
        self.assertIn("could not clear it", "\n".join(logs.output))
        # With a boot value that asks, removing it is the safe answer.
        self.env_file.write_text('export BRAIN_CLAUDE_PERMS_FLAG=""\n')
        with mock.patch.object(permission_mode.atomic_write, "write_text",
                               side_effect=OSError(30, "ro")), \
                mock.patch.object(permission_mode.os, "open", refuse):
            self.assertFalse(permission_mode.publish(False))
        self.assertFalse(self.file.exists())
        self.assertEqual(_read_flag(self._reader_env()), "")

    def test_no_parent_directory_is_a_dev_checkout_not_a_mkdir(self):
        missing = Path(self.tmp.name, "no", "such", "brain-permissions")
        with mock.patch.dict(os.environ,
                             {"BRAIN_PERMISSIONS_FILE": str(missing)}):
            self.assertFalse(permission_mode.publish(True))
        self.assertFalse(missing.parent.exists())

    def test_startup_reads_only_an_explicit_true(self):
        for value, want in (("true", True), ("TRUE", True), ("false", False),
                            ("", False), ("1", False), ("yes", False)):
            with mock.patch.dict(os.environ, {"BRAIN_SKIP_PERMISSIONS": value}):
                self.assertEqual(permission_mode.startup(), want, value)


class TestWhatIsStillRunning(unittest.TestCase):
    """`terminal_sessions`: which terminal Claudes did not get the switch.

    ttyd re-attaches to the same tmux session on every visit, so a flip
    reaches a terminal session only when one STARTS. What ⚙ says about the
    ones already open is read off the process table.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _add(self, pid, ppid, argv, comm="x"):
        d = self.proc / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv)
                                    + b"\0")
        (d / "stat").write_text(f"{pid} ({comm}) S {ppid} 1 1 0 -1\n")

    def _house(self):
        self._add(1, 0, ["/init"])
        self._add(10, 1, ["ttyd", "-p", "7681", "tmux", "new-session"])
        # tmux's server keeps the argv of the client that started it.
        self._add(11, 1, ["tmux", "new-session", "-A", "-s", "claude"],
                  comm="tmux: server")
        self._add(12, 11, ["bash", "/usr/local/bin/brain-terminal-start"])
        # The panel and everything it runs: none of it is the terminal.
        self._add(20, 1, ["python3", "/opt/panel/server.py"])
        self._add(21, 20, ["/root/.local/bin/claude", "-p", "--input-format",
                           "stream-json", "--permission-mode",
                           "bypassPermissions"])
        self._add(22, 20, ["/root/.local/bin/claude", "setup-token"])
        self._add(23, 20, ["/root/.local/bin/claude", FLAG, "-p", "x"])

    def test_a_session_started_acting_is_counted_as_acting(self):
        self._house()
        self._add(13, 12, ["/root/.local/bin/claude", FLAG],
                  comm="claude (2.1) )")
        # A helper the CLI starts of itself is the same session.
        self._add(14, 13, ["/root/.local/bin/claude", FLAG, "--child"])
        self.assertEqual(permission_mode.terminal_sessions(str(self.proc)),
                         {"acting": 1, "asking": 0})

    def test_a_session_started_asking_is_counted_as_asking(self):
        self._house()
        self._add(13, 12, ["/root/.local/bin/claude", "--resume", "abc"])
        self.assertEqual(permission_mode.terminal_sessions(str(self.proc)),
                         {"acting": 0, "asking": 1})

    def test_a_background_task_the_picker_started_acting_counts(self):
        self._house()
        self._add(13, 12, ["/root/.local/bin/claude", FLAG, "-p", "tidy"])
        self._add(15, 12, ["/root/.local/bin/claude", "-p", "tidy"])
        self.assertEqual(permission_mode.terminal_sessions(str(self.proc)),
                         {"acting": 1, "asking": 0})

    def test_nothing_outside_tmux_is_the_terminal(self):
        self._house()
        self.assertEqual(permission_mode.terminal_sessions(str(self.proc)),
                         {"acting": 0, "asking": 0})

    def test_a_table_that_cannot_be_read_is_not_none_open(self):
        self.assertIsNone(permission_mode.terminal_sessions(
            str(self.proc / "missing")))

    def test_a_real_process_table(self):
        """The same over the real /proc: a stand-in tmux running a stand-in
        terminal Claude, named the way exec names them."""
        if not os.path.isdir("/proc/self"):
            self.skipTest("no /proc here")
        before = permission_mode.terminal_sessions()
        script = ('exec -a tmux bash -c \''
                  'exec -a /root/.local/bin/claude python3 -c '
                  '"import time; time.sleep(30)" ' + FLAG + ' & wait\'')
        proc = subprocess.Popen(["bash", "-c", script],
                                start_new_session=True)
        try:
            for _ in range(100):
                now = permission_mode.terminal_sessions()
                if now["acting"] > before["acting"]:
                    break
                time.sleep(0.05)
            self.assertEqual(now["acting"], before["acting"] + 1)
            self.assertEqual(now["asking"], before["asking"])
        finally:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


def _lift_function(text: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.S | re.M)
    assert match, f"{name} not found in run.sh"
    return match.group(0)


class TestRunShWritesTheSwitchAtBoot(unittest.TestCase):
    """`publish_permission_switch`, lifted out of the real run.sh and run.

    It runs before ttyd: the file outlives a restart, so a word the panel
    published last boot must not answer for an option changed since.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name, "brain-permissions")
        self.fn = _lift_function(RUN_SH.read_text(), "publish_permission_switch")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, value: str):
        script = ('bashio::log.warning() { echo "WARN $*" >&2; }\n'
                  + self.fn + f'publish_permission_switch "{value}"\n')
        return subprocess.run(
            ["bash", "-c", script],
            env={"PATH": os.environ["PATH"],
                 "BRAIN_PERMISSIONS_FILE": str(self.file)},
            capture_output=True, text=True, timeout=10)

    def test_true_is_bypass_and_anything_else_is_ask(self):
        self.assertEqual(self._run("true").returncode, 0)
        self.assertEqual(self.file.read_text(), "bypass\n")
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o644)
        for value in ("false", "", "True", "yes"):
            self._run(value)
            self.assertEqual(self.file.read_text(), "ask\n", value)

    def test_a_write_that_fails_leaves_last_boots_word_empty_not_gone(self):
        """Gone would hand the answer to /data/.brain_env, which at this
        point in boot still holds the LAST boot's value — the flag, on an
        add-on that was started with the switch on."""
        self.file.write_text("bypass\n")
        env_file = Path(self.tmp.name, "brain_env")
        env_file.write_text(f'export BRAIN_CLAUDE_PERMS_FLAG="{FLAG}"\n')
        # The scratch name is a directory, so the write cannot land.
        Path(str(self.file) + ".tmp").mkdir()
        out = self._run("false")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(self.file.exists(), "the path was left to the fallback")
        self.assertEqual(self.file.read_bytes(), b"", "a stale bypass survived")
        self.assertIn("will ask", out.stderr)
        self.assertEqual(_read_flag({"BRAIN_PERMISSIONS_FILE": str(self.file),
                                     "BRAIN_PERMS_ENV_FILE": str(env_file)}),
                         "")

    def test_a_symlink_at_boot_is_replaced_not_truncated_through(self):
        target = Path(self.tmp.name, "elsewhere")
        target.write_text("precious\n")
        os.symlink(target, self.file)
        Path(str(self.file) + ".tmp").mkdir()
        self._run("false")
        self.assertEqual(target.read_text(), "precious\n")
        self.assertFalse(self.file.is_symlink())

    def test_init_environment_calls_it_with_the_option(self):
        text = RUN_SH.read_text()
        init = text[text.index("init_environment() {"):]
        init = init[:init.index("\n}\n")]
        self.assertIn('publish_permission_switch "$skip_perms"', init)
        self.assertIn("bashio::config 'dangerously_skip_permissions'", init)

    def test_the_terminal_launch_command_bakes_no_flag(self):
        """A flag in ttyd's command is a value frozen at boot."""
        text = RUN_SH.read_text()
        fn = _lift_function(text, "get_claude_launch_command")
        self.assertNotIn("perms", fn)
        self.assertNotIn(FLAG, fn)
        self.assertNotIn("get_permissions_flag", text)


def _recorder(path: Path, log: Path) -> None:
    """A stand-in that writes each argument it was given on its own line —
    and nothing at all for no arguments, which `printf` with an empty
    argument list would not manage."""
    path.write_text('#!/bin/bash\n'
                    f': > "{log}"\n'
                    f'for a in "$@"; do printf "%s\\n" "$a" >> "{log}"; done\n')
    path.chmod(0o755)


class TestTheTerminalStartsWithTheCurrentValue(unittest.TestCase):
    """brain-terminal-start and the session picker, run for real."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.file = root / "brain-permissions"
        self.log = root / "argv.log"
        self.bin = root / "bin"
        self.bin.mkdir()
        self.env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "BRAIN_PERMISSIONS_FILE": str(self.file),
            "BRAIN_PERMS_ENV_FILE": str(root / "no-env"),
            "BRAIN_PERMS_LIB": str(LIB),
            "BRAIN_TERMINAL_HANDOFF": str(root / "no-handoff.json"),
            "BRAIN_TASK_DIR": str(root / "tasks"),
            "CLAUDE_PROJECT_DIR": str(root),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _start(self, *args) -> list[str]:
        run = self.bin / "claude-run"
        _recorder(run, self.log)
        out = subprocess.run(
            ["bash", str(SCRIPTS / "brain-terminal-start.sh"), *args],
            env={**self.env, "BRAIN_CLAUDE_RUN": str(run)},
            capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return self.log.read_text().splitlines()

    def test_a_session_starts_with_what_the_switch_says_now(self):
        self.file.write_text("bypass\n")
        self.assertEqual(self._start(), [FLAG])
        # Flipped between two sessions, with nothing restarted.
        self.file.write_text("ask\n")
        self.assertEqual(self._start(), [])

    def test_garbage_and_a_missing_file_start_asking(self):
        self.file.write_text("perhaps")
        self.assertEqual(self._start(), [])
        self.file.unlink()
        self.assertEqual(self._start(), [])

    def test_a_flag_baked_into_an_older_launch_command_is_decided_again(self):
        self.file.write_text("ask\n")
        self.assertEqual(self._start(FLAG, "-c"), ["-c"])
        self.file.write_text("bypass\n")
        self.assertEqual(self._start(FLAG, "-c"), [FLAG, "-c"])

    def test_no_library_is_no_flag(self):
        self.file.write_text("bypass\n")
        self.env["BRAIN_PERMS_LIB"] = str(Path(self.tmp.name, "gone.sh"))
        # And no copy beside the script either: run a copy from a folder
        # that holds nothing else.
        lone = Path(self.tmp.name, "lone")
        lone.mkdir()
        start = lone / "brain-terminal-start.sh"
        start.write_text((SCRIPTS / "brain-terminal-start.sh").read_text())
        run = self.bin / "claude-run"
        _recorder(run, self.log)
        out = subprocess.run(["bash", str(start)],
                             env={**self.env, "BRAIN_CLAUDE_RUN": str(run)},
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(self.log.read_text().splitlines(), [])

    def _picker(self, choice: str) -> list[str]:
        """Run the real picker, choose `choice`, read what tmux was given."""
        _recorder(self.bin / "tmux", self.log)
        for name in ("sleep", "clear"):
            stub = self.bin / name
            stub.write_text("#!/bin/bash\nexit 0\n")
            stub.chmod(0o755)
        # `tmux has-session` is asked first; the recorder answers 0 for it,
        # so a has-session call must not be mistaken for the launch.
        has = self.bin / "tmux"
        has.write_text(
            '#!/bin/bash\n'
            '[ "$1" = "has-session" ] && exit 1\n'
            '[ "$1" = "list-windows" ] && exit 0\n'
            f': > "{self.log}"\n'
            f'for a in "$@"; do printf "%s\\n" "$a" >> "{self.log}"; done\n')
        has.chmod(0o755)
        out = subprocess.run(["bash", str(SCRIPTS / "brain-menu.sh")],
                             env=self.env, input=choice + "\n",
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 0, out.stderr)
        return self.log.read_text().splitlines()

    def test_the_picker_reads_the_switch_when_a_session_starts(self):
        self.file.write_text("bypass\n")
        self.assertEqual(self._picker("1")[-1], f"claude-run {FLAG}")
        self.file.write_text("ask\n")
        self.assertEqual(self._picker("1")[-1].strip(), "claude-run")
        self.file.write_text("garbage")
        self.assertEqual(self._picker("2")[-1].strip(), "claude-run  -c")


class ChatCase(unittest.IsolatedAsyncioTestCase):
    """A real ChatSession spawning the fake CLI."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, "argv.log")
        self.perms_log = os.path.join(self.tmp.name, "perms.log")
        self._env = mock.patch.dict(os.environ, {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(self.tmp.name, "t.json"),
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(self.tmp.name, "chat"),
            "BRAIN_SETTINGS_FILE": os.path.join(self.tmp.name, "settings.json"),
            "BRAIN_CHAT_WORKDIR": self.tmp.name,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_RUN_SOURCES": os.path.join(self.tmp.name, "rs.jsonl"),
            "FAKE_CHAT_MODE": "ok",
            "FAKE_CHAT_LOG": self.log,
            "FAKE_CHAT_PERMS_LOG": self.perms_log,
        })
        self._env.start()
        for key in ("FAKE_CHAT_SUGGESTIONS", "FAKE_CHAT_REFUSE",
                    "FAKE_CHAT_BROKEN", "FAKE_CHAT_NOPROMPTFLAG"):
            os.environ.pop(key, None)
        import engine
        importlib.reload(engine)
        import chat_session
        self.mod = importlib.reload(chat_session)
        self.session = self.mod.ChatSession()

    async def asyncTearDown(self):
        await self.session.stop()
        self._env.stop()
        for key in ("FAKE_CHAT_SUGGESTIONS", "FAKE_CHAT_REFUSE"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    async def _spawns(self, count, timeout=6.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        lines = []
        while loop.time() < deadline:
            try:
                lines = [json.loads(line) for line in
                         Path(self.log).read_text().splitlines() if line]
            except OSError:
                lines = []
            if len(lines) >= count:
                return lines
            await asyncio.sleep(0.05)
        raise AssertionError(f"only {len(lines)} of {count} spawns were logged")

    async def _drain(self, until, timeout=10.0):
        queue = self.session.subscribe()
        got = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while loop.time() < deadline:
                try:
                    got.append(await asyncio.wait_for(
                        queue.get(), deadline - loop.time()))
                except asyncio.TimeoutError:
                    break
                if until(got):
                    return got
        finally:
            self.session.unsubscribe(queue)
        return got

    async def _turn(self, text="go"):
        """Send and wait for the turn to land: a `ready` AFTER the `busy`
        the send set, so a spawn's own `ready` (a respawn makes one) is
        never mistaken for the answer."""
        def landed(evs):
            states = [e.get("state") for e in evs if e.get("type") == "state"]
            return "busy" in states and "ready" in states[states.index("busy"):]
        task = asyncio.create_task(self._drain(landed))
        await asyncio.sleep(0.05)
        await self.session.send(text)
        return await task

    @staticmethod
    def _mode(argv):
        return argv[argv.index("--permission-mode") + 1] \
            if "--permission-mode" in argv else None


class TestTheChatsMode(ChatCase):
    async def test_on_spawns_with_bypass_and_the_platform_deny_list(self):
        self.session.skip_permissions = True
        await self.session.start()
        argv = (await self._spawns(1))[0]
        self.assertEqual(self._mode(argv), "bypassPermissions")
        # Deny rules are checked before the mode, and the list rides the
        # argv too so it holds without the project settings file.
        denied = argv[argv.index("--disallowedTools") + 1].split(",")
        import engine
        self.assertEqual(sorted(denied), sorted(engine.PLATFORM_DENIED))

    async def test_off_sends_no_mode_at_all(self):
        await self.session.start()
        argv = (await self._spawns(1))[0]
        self.assertIsNone(self._mode(argv))
        self.assertNotIn("bypassPermissions", argv)
        self.assertNotIn("--disallowedTools", argv)

    async def test_a_discussion_names_default_whatever_the_switch_says(self):
        self.session.skip_permissions = True
        self.session.about(1_700_000_000)
        await self.session.start()
        argv = (await self._spawns(1))[0]
        self.assertEqual(self._mode(argv), "default")
        self.assertNotIn("bypassPermissions", argv)
        # Its ask rules are still on the argv: a discussion asks.
        settings = json.loads(argv[argv.index("--settings") + 1])
        self.assertIn("ask", settings["permissions"])

    async def test_a_change_respawns_an_idle_session_on_its_next_send(self):
        await self._turn("first")
        first = self.session.proc
        self.assertIsNone(self._mode((await self._spawns(1))[0]))
        self.session.skip_permissions = True
        await self._turn("second")
        spawns = await self._spawns(2)
        self.assertIsNot(self.session.proc, first)
        self.assertEqual(self._mode(spawns[-1]), "bypassPermissions")
        # The conversation came with it.
        self.assertIn("--resume", spawns[-1])
        # And back off again, the same way.
        self.session.skip_permissions = False
        await self._turn("third")
        self.assertIsNone(self._mode((await self._spawns(3))[-1]))

    async def test_an_unchanged_switch_does_not_respawn(self):
        self.session.skip_permissions = True
        await self._turn("first")
        proc = self.session.proc
        await self._turn("second")
        self.assertIs(self.session.proc, proc)
        self.assertEqual(len(await self._spawns(1)), 1)

    async def test_a_busy_session_keeps_its_mode_until_it_is_idle(self):
        os.environ["FAKE_CHAT_MODE"] = "hang"
        await self.session.start()
        await self.session.send("long one")
        await asyncio.sleep(0.3)
        proc = self.session.proc
        self.session.skip_permissions = True
        with self.assertRaises(RuntimeError):
            await self.session.send("now")
        self.assertIs(self.session.proc, proc, "a busy answer was killed")
        self.assertEqual(len(await self._spawns(1)), 1)

    async def test_a_cli_that_refuses_the_flag_loses_it_and_asks(self):
        os.environ["FAKE_CHAT_REFUSE"] = "--permission-mode"
        self.session.skip_permissions = True
        await self.session.start()
        self.assertTrue(self.session.alive(), "the chat did not start")
        spawns = await self._spawns(2)
        self.assertEqual(self._mode(spawns[0]), "bypassPermissions")
        self.assertIsNone(self._mode(spawns[1]))
        self.assertNotIn("--disallowedTools", spawns[1])
        # And the dropped flag is not chased round a respawn every send.
        await self._turn("hello")
        self.assertEqual(len(await self._spawns(2)), 2)

    async def test_on_means_no_approval_card_reaches_the_panel(self):
        os.environ["FAKE_CHAT_MODE"] = "permission"
        self.session.skip_permissions = True
        events = await self._turn("delete that file")
        self.assertFalse([e for e in events if e.get("type") == "permission"])
        self.assertTrue(any(e.get("type") == "tool_result" for e in events),
                        "the call did not run")

    async def test_a_stopped_conversation_reopens_with_the_switch_as_it_is_now(self):
        """A held conversation the cap (or a handoff) stopped spawns again
        when it is reopened — with what the switch says now, not with what
        it said when the session was first adopted."""
        registry = self.mod.SessionRegistry()
        try:
            await registry.open("conv-held", [])
            held = registry.get("conv-held")
            self.assertIsNone(self._mode((await self._spawns(1))[-1]))
            await held.stop()
            registry.skip_permissions = True
            await registry.open("conv-held", [])
            spawns = await self._spawns(2)
            self.assertEqual(self._mode(spawns[-1]), "bypassPermissions")
            self.assertTrue(held.skip_permissions)
        finally:
            await registry.stop_all()

    async def test_off_still_asks(self):
        os.environ["FAKE_CHAT_MODE"] = "permission"
        await self.session.start()
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "permission" for e in evs)))
        await asyncio.sleep(0.05)
        await self.session.send("delete that file")
        perm = next(e for e in await task if e["type"] == "permission")
        self.assertTrue(perm["stop_asking"], "the way out was not offered")
        await self.session.respond_permission(perm["id"], False)


SUGGESTIONS = [
    {"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "rm:*"}],
     "behavior": "allow", "destination": "localSettings"},
    # Dropped: outlives the add-on's own rewrite of settings.local.json.
    {"type": "addRules", "rules": [{"toolName": "Bash"}],
     "behavior": "allow", "destination": "userSettings"},
    # Dropped: would replace the reading allow-list run.sh writes.
    {"type": "replaceRules", "rules": [{"toolName": "Bash"}],
     "behavior": "allow", "destination": "session"},
    # Dropped: a permission switch wearing a suggestion's clothes.
    {"type": "setMode", "mode": "bypassPermissions", "destination": "session"},
    # Dropped: a rule that DENIES is not "always allow".
    {"type": "addRules", "rules": [{"toolName": "Write"}],
     "behavior": "deny", "destination": "session"},
]


class TestAlwaysAllowThis(ChatCase):
    async def _ask(self, suggestions):
        os.environ["FAKE_CHAT_MODE"] = "permission"
        if suggestions is not None:
            os.environ["FAKE_CHAT_SUGGESTIONS"] = json.dumps(suggestions)
        await self.session.start()
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "permission" for e in evs)))
        await asyncio.sleep(0.05)
        await self.session.send("delete that file")
        return next(e for e in await task if e["type"] == "permission")

    async def test_the_suggestion_goes_back_in_the_sdk_shape(self):
        perm = await self._ask(SUGGESTIONS)
        self.assertEqual(perm["always"], "Bash(rm:*)")
        self.assertEqual(perm["always_until"], "restart")
        done = asyncio.create_task(self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready"
            for e in evs)))
        await asyncio.sleep(0.05)
        out = await self.session.respond_permission(perm["id"], True,
                                                    always=True)
        self.assertTrue(out["always"])
        events = await done
        # The fake checks the update against the CLI SDK's schema before
        # logging it, and refuses the turn on a malformed one.
        self.assertFalse([e for e in events if e.get("type") == "notice"
                          and "Malformed" in str(e.get("text"))])
        sent = [json.loads(line) for line in
                Path(self.perms_log).read_text().splitlines()]
        self.assertEqual(sent, [[SUGGESTIONS[0]]])
        finished = [e for e in events if e.get("type") == "permission_done"]
        self.assertTrue(finished and finished[-1]["always"])

    async def test_once_sends_no_rule(self):
        perm = await self._ask(SUGGESTIONS)
        await self.session.respond_permission(perm["id"], True)
        await asyncio.sleep(0.4)
        self.assertFalse(Path(self.perms_log).exists())

    async def test_nothing_offered_is_nothing_to_always_allow(self):
        perm = await self._ask(None)
        self.assertEqual(perm["always"], "")
        with self.assertRaises(ValueError):
            await self.session.respond_permission(perm["id"], True,
                                                  always=True)
        # Refused, not downgraded: the question is still waiting.
        self.assertEqual(self.session.pending_permission["id"], perm["id"])
        await self.session.respond_permission(perm["id"], False)

    async def test_session_scoped_suggestions_say_so(self):
        perm = await self._ask([
            {"type": "setMode", "mode": "acceptEdits", "destination": "session"},
            {"type": "addDirectories", "directories": ["/share"],
             "destination": "session"}])
        self.assertEqual(perm["always"], "every file edit, files in /share")
        self.assertEqual(perm["always_until"], "conversation")
        await self.session.respond_permission(perm["id"], False)

    async def test_a_discussion_offers_neither_way_out(self):
        self.session.about(1_700_000_000)
        perm = await self._ask(SUGGESTIONS)
        self.assertEqual(perm["always"], "")
        self.assertFalse(perm["stop_asking"])
        with self.assertRaises(ValueError):
            await self.session.respond_permission(perm["id"], True,
                                                  always=True)
        await self.session.respond_permission(perm["id"], False)


class TestTheCleaner(unittest.TestCase):
    """`permission_updates` over shapes the CLI would and would not send."""

    def setUp(self):
        import chat_session
        self.mod = chat_session

    def test_only_allow_rules_dirs_and_accept_edits_survive(self):
        kept = self.mod.permission_updates(SUGGESTIONS)
        self.assertEqual(kept, [SUGGESTIONS[0]])

    def test_malformed_entries_are_dropped_not_passed_through(self):
        for raw in (None, "x", [None], [{"type": "addRules"}],
                    [{"type": "addRules", "behavior": "allow",
                      "destination": "session", "rules": "Bash"}],
                    [{"type": "addRules", "behavior": "allow",
                      "destination": "session", "rules": [{"toolName": 3}]}],
                    [{"type": "addDirectories", "destination": "session",
                      "directories": [""]}],
                    [{"type": "setMode", "mode": "acceptEdits"}]):
            self.assertEqual(self.mod.permission_updates(raw), [], repr(raw))


class TestTheTwoDoors(SupervisorMixin, unittest.TestCase):
    """⚙ and the Configuration tab are one switch, through the real routes."""

    supervisor_options = {**SupervisorMixin.supervisor_options,
                          "dangerously_skip_permissions": False}

    def setUp(self):
        super().setUp()
        self.file = Path(self.tmp.name, "brain-permissions")
        self._env = mock.patch.dict(os.environ, {
            "BRAIN_PERMISSIONS_FILE": str(self.file),
            "BRAIN_DIR": os.path.join(self.tmp.name, "insights"),
            "BRAIN_SECRETS": os.path.join(self.tmp.name, "secrets"),
            "BRAIN_SETTINGS_FILE": settings_store.SETTINGS_FILE,
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(self.tmp.name, "chat"),
            "BRAIN_CHAT_WORKDIR": self.tmp.name,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_SKIP_PERMISSIONS": "false",
        })
        self._env.start()
        self.addCleanup(self._env.stop)
        import chat_session
        importlib.reload(chat_session)
        import server
        self.server = importlib.reload(server)

    async def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        client = TestClient(TestServer(self.server.make_app()))
        await client.start_server()
        self.closers.append(client.close)
        return client

    def test_a_gear_change_writes_the_option_and_the_terminals_file(self):
        async def run():
            client = await self._client()
            # Startup published the current value.
            self.assertEqual(self.file.read_text(), "ask\n")
            resp = await client.put("/api/settings",
                                    json={"dangerously_skip_permissions": True})
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertIs(data["settings"]["dangerously_skip_permissions"], True)
            self.assertIs(self.supervisor.options["dangerously_skip_permissions"],
                          True)
            self.assertEqual(self.supervisor.options["log_level"], "info")
            self.assertEqual(self.file.read_text(), "bypass\n")
            self.assertTrue(self.server.eff_skip_permissions())
            # The chat is told on its next request, the way `model` is.
            self.assertTrue(self.server._chat().skip_permissions)
            # Nothing is left behind locally to shadow the add-on's value.
            self.assertIsNone(settings_store.load()["dangerously_skip_permissions"])

            await client.put("/api/settings",
                             json={"dangerously_skip_permissions": False})
            self.assertIs(self.supervisor.options["dangerously_skip_permissions"],
                          False)
            self.assertEqual(self.file.read_text(), "ask\n")
            self.assertFalse(self.server._chat().skip_permissions)
        self.with_supervisor(run)

    def test_a_configuration_tab_change_shows_in_the_gear(self):
        async def run():
            client = await self._client()
            self.supervisor.options["dangerously_skip_permissions"] = True
            addon_options._read_at = 0.0      # past the read cache
            data = await (await client.get("/api/settings")).json()
            self.assertIs(data["settings"]["dangerously_skip_permissions"], True)
        self.with_supervisor(run)

    def test_the_options_poller_republishes_the_terminals_file(self):
        """A Configuration-tab edit reaches the next terminal session
        without a restart: the poller that already re-reads the options
        publishes the switch."""
        async def run():
            await self._client()
            self.assertEqual(self.file.read_text(), "ask\n")
            self.supervisor.options["dangerously_skip_permissions"] = True
            with mock.patch.object(self.server, "OPTIONS_POLL_SECONDS", 0.01):
                task = asyncio.create_task(self.server._options_poller())
                try:
                    for _ in range(200):
                        if self.file.read_text() == "bypass\n":
                            break
                        await asyncio.sleep(0.02)
                finally:
                    task.cancel()
            self.assertEqual(self.file.read_text(), "bypass\n")
        self.with_supervisor(run)

    def test_a_string_is_refused_before_the_supervisor_sees_it(self):
        async def run():
            client = await self._client()
            for bad in ("true", 1, "yes"):
                resp = await client.put(
                    "/api/settings", json={"dangerously_skip_permissions": bad})
                self.assertEqual(resp.status, 400, bad)
            self.assertEqual(self.supervisor.writes, [])
            self.assertEqual(self.file.read_text(), "ask\n")
        self.with_supervisor(run)

    def test_a_refused_on_is_not_kept_locally(self):
        """A failed write of "act" may not turn the switch on behind the
        Configuration tab's back: it is refused in words, the switch stays
        off, and nothing is left locally to outrank a later edit."""
        async def run():
            client = await self._client()
            self.supervisor.reject = True
            resp = await client.put("/api/settings",
                                    json={"dangerously_skip_permissions": True})
            self.assertEqual(resp.status, 409)
            self.assertIn("still asking", await resp.text())
            self.assertIsNone(
                settings_store.load()["dangerously_skip_permissions"])
            self.assertFalse(self.server.eff_skip_permissions())
            self.assertEqual(self.file.read_text(), "ask\n")
            self.assertFalse(self.server._chat().skip_permissions)
        self.with_supervisor(run)

    def test_a_refused_off_still_takes_effect_and_says_where_it_was_kept(self):
        async def run():
            self.supervisor.options["dangerously_skip_permissions"] = True
            client = await self._client()
            self.assertEqual(self.file.read_text(), "bypass\n")
            self.supervisor.reject = True
            resp = await client.put("/api/settings",
                                    json={"dangerously_skip_permissions": False})
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data["saved_locally"],
                             ["dangerously_skip_permissions"])
            self.assertIs(data["settings"]["dangerously_skip_permissions"], False)
            # The Supervisor still says on; the local "ask" wins anyway.
            self.assertIs(self.supervisor.options["dangerously_skip_permissions"],
                          True)
            self.assertFalse(self.server.eff_skip_permissions())
            self.assertEqual(self.file.read_text(), "ask\n")
        self.with_supervisor(run)

    def test_a_stale_local_on_is_outranked_by_the_configuration_tab(self):
        """A local "act" left from before (or by a box that had no
        Supervisor when it was saved) does not outlive an "ask" the
        Supervisor answers with."""
        async def run():
            settings_store.save({"dangerously_skip_permissions": True})
            await addon_options.refresh(force=True)
            self.assertFalse(self.server.eff_skip_permissions())
            # With no Supervisor value to outrank it, it still counts.
            self._reset_cache()
            addon_options.TOKEN = ""
            self.assertTrue(self.server.eff_skip_permissions())
        self.with_supervisor(run)

    def test_startup_promotes_a_local_off_and_drops_a_local_on(self):
        async def run():
            settings_store.save({"dangerously_skip_permissions": True})
            await self.server._options_sync()
            self.assertIs(self.supervisor.options["dangerously_skip_permissions"],
                          False, "a stale local 'act' was promoted")
            self.assertIsNone(
                settings_store.load()["dangerously_skip_permissions"])

            self.supervisor.options["dangerously_skip_permissions"] = True
            settings_store.save({"dangerously_skip_permissions": False})
            await self.server._options_sync()
            self.assertIs(self.supervisor.options["dangerously_skip_permissions"],
                          False, "a local 'ask' was not promoted")
            self.assertIsNone(
                settings_store.load()["dangerously_skip_permissions"])
        self.with_supervisor(run)

    def test_the_gear_is_told_what_is_still_running(self):
        """⚙ says which open terminal session did not get the switch, so the
        payload carries the count — and None, never zero, when it could not
        look."""
        async def run():
            client = await self._client()
            with mock.patch.object(self.server.permission_mode,
                                   "terminal_sessions",
                                   return_value={"acting": 1, "asking": 0}):
                data = await (await client.put(
                    "/api/settings",
                    json={"dangerously_skip_permissions": False})).json()
            self.assertEqual(data["permission_sessions"],
                             {"acting": 1, "asking": 0})
            with mock.patch.object(self.server.permission_mode,
                                   "terminal_sessions", return_value=None):
                data = await (await client.get("/api/settings")).json()
            self.assertIsNone(data["permission_sessions"])
        self.with_supervisor(run)

    def test_without_a_supervisor_the_switch_still_takes_effect(self):
        async def run():
            addon_options.TOKEN = ""
            client = await self._client()
            resp = await client.put("/api/settings",
                                    json={"dangerously_skip_permissions": True})
            self.assertEqual(resp.status, 200)
            self.assertTrue(self.server.eff_skip_permissions())
            self.assertEqual(self.file.read_text(), "bypass\n")
        self.with_supervisor(run)


class TestTheApprovalRoute(unittest.IsolatedAsyncioTestCase):
    """POST /api/chat/permission carries "Always allow this" to the CLI."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.perms_log = os.path.join(self.tmp.name, "perms.log")
        self._env = mock.patch.dict(os.environ, {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(self.tmp.name, "t.json"),
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(self.tmp.name, "chat"),
            "BRAIN_CHAT_WORKDIR": self.tmp.name,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_SETTINGS_FILE": os.path.join(self.tmp.name, "settings.json"),
            "BRAIN_DIR": os.path.join(self.tmp.name, "insights"),
            "BRAIN_SECRETS": os.path.join(self.tmp.name, "secrets"),
            "BRAIN_RUN_SOURCES": os.path.join(self.tmp.name, "rs.jsonl"),
            "BRAIN_PERMISSIONS_FILE": os.path.join(self.tmp.name, "perms"),
            "FAKE_CHAT_MODE": "permission",
            "FAKE_CHAT_PERMS_LOG": self.perms_log,
            "FAKE_CHAT_SUGGESTIONS": json.dumps(SUGGESTIONS[:1]),
        })
        self._env.start()
        for name in ("engine", "settings_store", "run_sources", "conversations",
                     "chat_session", "server"):
            module = importlib.import_module(name)
            setattr(self, name, importlib.reload(module))
        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self._env.stop()
        self.tmp.cleanup()

    async def _pending(self):
        await self.client.post("/api/chat/send", json={"text": "risky"})
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while loop.time() < deadline:
            snap = await (await self.client.get("/api/chat/state")).json()
            if snap.get("permission"):
                return snap["permission"]
            await asyncio.sleep(0.1)
        self.fail("the question never surfaced")

    async def test_always_allow_hands_back_the_suggestion(self):
        perm = await self._pending()
        self.assertEqual(perm["always"], "Bash(rm:*)")
        self.assertTrue(perm["stop_asking"])
        resp = await self.client.post("/api/chat/permission", json={
            "id": perm["id"], "allow": True, "always": True})
        self.assertEqual(resp.status, 200)
        self.assertTrue((await resp.json())["always"])
        for _ in range(100):
            if Path(self.perms_log).exists():
                break
            await asyncio.sleep(0.05)
        self.assertEqual(json.loads(Path(self.perms_log).read_text()),
                         SUGGESTIONS[:1])

    async def test_always_on_a_request_that_offered_nothing_is_refused(self):
        os.environ.pop("FAKE_CHAT_SUGGESTIONS")
        perm = await self._pending()
        resp = await self.client.post("/api/chat/permission", json={
            "id": perm["id"], "allow": True, "always": True})
        self.assertEqual(resp.status, 400)
        # Only a JSON true asks for it: a truthy string is an ordinary yes.
        resp = await self.client.post("/api/chat/permission", json={
            "id": perm["id"], "allow": True, "always": "yes"})
        self.assertEqual(resp.status, 200)
        self.assertFalse((await resp.json())["always"])


class TestTheWordsOnTheOption(unittest.TestCase):
    def test_the_option_has_a_plain_name_that_says_what_stays_guarded(self):
        import yaml
        text = (BASE_DIR / "brain" / "translations" / "en.yaml").read_text()
        entry = yaml.safe_load(text)["configuration"][
            "dangerously_skip_permissions"]
        self.assertEqual(entry["name"], "Let brAIn act without asking")
        for words in ("terminal", "chat", "protected entities"):
            self.assertIn(words, entry["description"])

    def test_the_option_says_where_the_guards_stop(self):
        """Shell commands run unasked with this on, the hook knows only the
        obvious ones, a shell change reaches no undo journal, and an open
        terminal session keeps the setting it started with. A description
        that leaves any of that out promises more than the switch keeps."""
        import yaml
        text = (BASE_DIR / "brain" / "translations" / "en.yaml").read_text()
        words = yaml.safe_load(text)["configuration"][
            "dangerously_skip_permissions"]["description"]
        self.assertNotIn("stay refused", words)
        self.assertIn("not checked", words)
        self.assertIn("shell changes cannot", words)
        self.assertIn("/exit", words)


if __name__ == "__main__":
    unittest.main()
