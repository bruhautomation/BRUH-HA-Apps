#!/usr/bin/env python3
"""Every way the listener's scope step could refuse a valid narrow task,
and the reason a refusal that remains carries into the run journal (#621).

4.2.5 took the house's working directory off the step's import path and
had a refusal say why. Narrow tasks still came back "tools scope could not
be honoured", so this drives each remaining route a valid scope could be
refused by — what the environment puts on the path, a list only another
scope needs, a line an import printed, a step that died without a word —
through the real shell, lifted out of `automation-listener.sh`, and then
follows a refusal into the journal row a house's report is built from.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
PANEL_DIR = ADDON_DIR / "panel"
SCRIPTS_DIR = ADDON_DIR / "scripts"
LISTENER = ADDON_DIR / "integrations" / "automation-listener.sh"

FAKE_ENGINE = '''
ANALYST_TOOLS = ["mcp__home-assistant__get_state"]
ANALYST_DENIED = ["mcp__home-assistant__call_service", "Bash", "Write"]
CAMERA_TOOL = "mcp__home-assistant__get_camera_snapshot"
'''


def lift(name: str) -> str:
    src = LISTENER.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", src, re.S | re.M)
    assert match, f"automation-listener.sh no longer defines {name}"
    return match.group(0)


def run_flags(mode: str, *, panel: Path | str = PANEL_DIR, cwd=None,
              extra_env: dict | None = None):
    harness = lift("task_tool_flags") + f'\ntask_tool_flags "{mode}"\n'
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           "BRAIN_PANEL_DIR": str(panel)}
    env.update(extra_env or {})
    result = subprocess.run(["bash", "-c", harness], capture_output=True,
                            text=True, check=False, env=env, cwd=cwd)
    return (result.returncode,
            [ln for ln in result.stdout.splitlines() if ln], result.stderr)


class _Tmp(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def fake_panel(self, body: str) -> Path:
        panel = self.tmp / "panel"
        panel.mkdir(exist_ok=True)
        (panel / "engine.py").write_text(body, encoding="utf-8")
        return panel


class TestTheEnvironmentCannotRefuseAValidScope(_Tmp):
    """`-P` kept the working directory off the path; PYTHONPATH and the
    claude user's site-packages (HOME is /data/home, where a session's
    `pip install --user` lands) were still read before the panel was."""

    def test_pythonpath_naming_a_shadowing_module_changes_nothing(self):
        shadow = self.tmp / "shadow"
        shadow.mkdir()
        for name in ("json.py", "uuid.py", "subprocess.py", "re.py"):
            (shadow / name).write_text(
                "raise ImportError('left on PYTHONPATH')\n", encoding="utf-8")
        clean = run_flags("house")
        self.assertEqual(clean[0], 0, clean[2])
        rc, flags, err = run_flags("house", extra_env={"PYTHONPATH": str(shadow)})
        self.assertEqual(rc, 0, err)
        self.assertEqual(flags, clean[1])

    def test_a_pth_file_in_the_users_site_packages_changes_nothing(self):
        ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        out = subprocess.run(["python3", "-c", "import sys; print("
                              "f'python{sys.version_info.major}."
                              "{sys.version_info.minor}')"],
                             capture_output=True, text=True, check=True)
        ver = out.stdout.strip() or ver
        site = self.tmp / "home" / ".local" / "lib" / ver / "site-packages"
        site.mkdir(parents=True)
        (site / "noisy.pth").write_text(
            "import sys; print('a line a package printed'); "
            "sys.modules.pop('json', None)\n", encoding="utf-8")
        clean = run_flags("read_only")
        rc, flags, err = run_flags("read_only",
                                   extra_env={"HOME": str(self.tmp / "home")})
        self.assertEqual(rc, 0, err)
        self.assertEqual(flags, clean[1])


class TestOneScopesListCannotRefuseAnother(_Tmp):

    def test_house_and_read_only_do_not_need_the_game_list(self):
        panel = self.fake_panel(FAKE_ENGINE)
        for mode in ("house", "read_only"):
            rc, flags, err = run_flags(mode, panel=panel)
            self.assertEqual(rc, 0, f"{mode}: {err}")
            self.assertEqual(flags[0], "--allowedTools")
        rc, _, err = run_flags("minecraft", panel=panel)
        self.assertNotEqual(rc, 0)
        self.assertIn("game tool list", err)


class TestAnImportsOutputCannotShiftTheLists(_Tmp):

    def test_a_line_printed_at_import_is_not_read_as_a_list(self):
        panel = self.fake_panel("print('hello from an import')\n" + FAKE_ENGINE)
        rc, flags, err = run_flags("read_only", panel=panel)
        self.assertEqual(rc, 0, err)
        self.assertEqual(flags, [
            "--allowedTools", "mcp__home-assistant__get_state",
            "--disallowedTools",
            "mcp__home-assistant__call_service,Bash,Write,Read,Glob,Grep,LS,NotebookRead",
        ])


class TestARefusalAlwaysHasAReason(_Tmp):

    def test_an_import_that_exits_says_so(self):
        panel = self.fake_panel("raise SystemExit(4)\n")
        rc, _, err = run_flags("house", panel=panel)
        self.assertNotEqual(rc, 0)
        self.assertIn("engine could not be imported", err)

    def test_a_step_killed_without_a_word_names_its_status(self):
        panel = self.fake_panel("import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n")
        rc, _, err = run_flags("house", panel=panel)
        self.assertNotEqual(rc, 0)
        self.assertIn("ended with status 137", err)

    def test_the_scope_word_is_read_without_case_or_spaces(self):
        src = LISTENER.read_text(encoding="utf-8")
        read = src.split("task_tools=$(jq -r '.tools // empty'", 1)[1][:400]
        self.assertIn("tr 'A-Z' 'a-z'", read)
        self.assertIn("tr -d '[:space:]'", read)


class TestTheReasonReachesTheJournalRow(_Tmp):
    """The house's report is built from the run journal, so the reason has
    to be in the row's text — not only in the add-on log."""

    def test_the_refusal_block_journals_the_specific_reason(self):
        src = LISTENER.read_text(encoding="utf-8")
        block = src.split("    local scope_err scope_why\n", 1)[1]
        block = block.split("        return\n    fi\n", 1)[0] + "        return 0\n    fi\n"
        journal = self.tmp / "journal.jsonl"
        panel = self.fake_panel("raise RuntimeError('the panel is half written')\n")
        harness = "\n".join([
            lift("task_tool_flags"),
            lift("journal_task"),
            'bashio::log.error() { :; }',
            'write_task_result() { :; }',
            'refuse_once() {',
            '    local task_id=t1 task_tools=house task_cameras="" task_model=""',
            '    local task_scheduled="" tool_flags_out',
            '    local scope_err scope_why',
            block,
            '}',
            'refuse_once',
            'wait',
        ])
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "BRAIN_PANEL_DIR": str(panel),
               "BRAIN_SCRIPTS_DIR": str(SCRIPTS_DIR),
               "BRAIN_JOURNAL_FILE": str(journal)}
        # The journal writer reads the REAL panel (it imports `journal`);
        # only the scope step is handed the broken one.
        harness = harness.replace(
            'python3 "$journal_py"',
            f'BRAIN_PANEL_DIR="{PANEL_DIR}" python3 "$journal_py"')
        subprocess.run(["bash", "-c", harness], env=env, check=False,
                       capture_output=True, text=True, timeout=60)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not journal.exists():
            time.sleep(0.05)
        rows = [json.loads(ln) for ln in journal.read_text().splitlines() if ln]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "task")
        self.assertIn("tools scope could not be honoured: the panel's engine "
                      "could not be imported (RuntimeError: the panel is half "
                      "written)", rows[0]["error"])


if __name__ == "__main__":
    unittest.main()
