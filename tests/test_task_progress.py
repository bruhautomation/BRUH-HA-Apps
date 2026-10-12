"""What a brAIn task is doing, while it does it.

``brain-task-progress.sh`` is a PreToolUse hook in the headless settings
file; the automation listener sets ``BRAIN_TASK_PROGRESS`` per task, and
whoever handed the task over (Morph's Tell) reads the lines back. Held
here: the hook writes a line only when the variable is set, never prints
or fails (a hook is never why a call did not happen), is wired into
headless runs and not the terminal's settings, and the listener turns it on
for each task before the first Claude run, under the path Morph reads.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "brain" / "scripts" / "brain-task-progress.sh"
RUN_SH = ROOT / "brain" / "run.sh"
LISTENER = ROOT / "brain" / "integrations" / "automation-listener.sh"
MORPH_PATHS = ROOT / "morph" / "service" / "paths.py"

HAS_JQ = shutil.which("jq") is not None


def heredoc(name: str) -> dict:
    text = RUN_SH.read_text(encoding="utf-8")
    start = text.index(f"<< '{name}'\n") + len(f"<< '{name}'\n")
    end = text.index(f"\n{name}\n", start)
    return json.loads(text[start:end])


def hook_commands(settings: dict) -> list[tuple[str, str]]:
    return [(entry.get("matcher", ""), h["command"])
            for entry in settings.get("hooks", {}).get("PreToolUse", [])
            for h in entry["hooks"]]


@unittest.skipUnless(HAS_JQ, "jq is not installed")
class TestTheHook(unittest.TestCase):

    def run_hook(self, payload: str, env: dict | None = None):
        full = {k: v for k, v in os.environ.items() if k != "BRAIN_TASK_PROGRESS"}
        full.update(env or {})
        return subprocess.run(["bash", str(HOOK)], input=payload, capture_output=True, text=True,
                              env=full, timeout=10)

    def test_without_the_variable_it_writes_nothing_and_says_nothing(self):
        out = self.run_hook(json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/x"}}))
        self.assertEqual((0, "", ""), (out.returncode, out.stdout, out.stderr))

    def test_one_line_per_call_with_the_subject_and_never_the_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "t.jsonl"
            env = {"BRAIN_TASK_PROGRESS": str(path)}
            calls = [
                {"tool_name": "Edit", "tool_input": {"file_path": "/config/morph/dashboard.yaml",
                                                     "new_string": "SECRET CONTENT"}},
                {"tool_name": "Bash", "tool_input": {"command": "ls\n/config"}},
                {"tool_name": "mcp__home-assistant__get_entity_state",
                 "tool_input": {"entity_id": "light.kitchen"}},
            ]
            for c in calls:
                out = self.run_hook(json.dumps(c), env)
                self.assertEqual((0, ""), (out.returncode, out.stdout))
            rows = [json.loads(x) for x in path.read_text().splitlines()]
        self.assertEqual(["/config/morph/dashboard.yaml", "ls /config", "light.kitchen"],
                         [r["what"] for r in rows])
        self.assertNotIn("SECRET", json.dumps(rows))

    def test_garbage_or_an_unwritable_file_is_still_exit_zero(self):
        out = self.run_hook("not json", {"BRAIN_TASK_PROGRESS": "/nonexistent/dir/x.jsonl"})
        self.assertEqual((0, ""), (out.returncode, out.stdout))


class TestTheWiring(unittest.TestCase):

    def test_headless_runs_carry_the_hook_and_the_terminal_does_not(self):
        headless = hook_commands(heredoc("HEADLESS"))
        self.assertIn(("*", "/opt/scripts/brain-task-progress.sh"), headless)
        local = hook_commands(heredoc("SETTINGS"))
        self.assertFalse([c for _, c in local if "task-progress" in c],
                         "the terminal and the chat are not tasks")

    def test_the_listener_turns_it_on_before_the_first_run(self):
        text = LISTENER.read_text(encoding="utf-8")
        on = text.index('task_progress_on "$task_id"')
        first_run = text.index("${CLAUDE_BIN} -p --output-format json", text.index("process_task() {"))
        self.assertLess(on, first_run)

    def test_the_folder_is_spelled_the_same_in_both_halves(self):
        listener = re.search(r'PROGRESS_DIR="\$SHARED_DIR/([^"]+)"', LISTENER.read_text()).group(1)
        morph = re.search(r'BRAIN_PROGRESS = BRAIN_SHARED / "([^"]+)"', MORPH_PATHS.read_text()).group(1)
        self.assertEqual(listener, morph)

    def test_the_listener_function_exports_a_file_and_refuses_an_odd_id(self):
        text = LISTENER.read_text(encoding="utf-8")
        start = text.index("task_progress_on() {")
        end = text.index("\n}\n", start) + 3
        fn = text[start:end]
        with tempfile.TemporaryDirectory() as d:
            script = (f'PROGRESS_DIR="{d}/task_progress"\n{fn}\n'
                      'task_progress_on "morph-abc123"; echo "ok=${BRAIN_TASK_PROGRESS:-}"\n'
                      'unset BRAIN_TASK_PROGRESS; task_progress_on "../../etc"; echo "bad=${BRAIN_TASK_PROGRESS:-}"\n')
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
            lines = dict(x.split("=", 1) for x in out.stdout.split())
            self.assertEqual(f"{d}/task_progress/morph-abc123.jsonl", lines["ok"])
            self.assertTrue(Path(lines["ok"]).is_file())
            self.assertEqual("", lines["bad"])


if __name__ == "__main__":
    unittest.main()
