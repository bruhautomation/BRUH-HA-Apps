"""devloop-guard: an automated PR cannot change what judges it."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "devloop_guard", ROOT / ".github" / "scripts" / "devloop_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

BASE_FILES = {
    ".claude/devloop.json": (ROOT / ".claude" / "devloop.json").read_text(),
    ".github/scripts/devloop_guard.py": "# the guard\n",
    ".github/workflows/ci.yml": "name: CI\n",
    "tests/test_action_gate.py": "def test_gate():\n    assert True\n",
    "brain/config.yaml": 'name: brAIn\nversion: "1.0.0"\nslug: brain\n',
    "brain/panel/gate.py": "ALLOW = False\n",
    "brain/panel/cards.py": "X = 1\n",
    "brain/panel/style.css": "a{}\n",
    "bright/panel/show.py": "Y = 1\n",
}


class GuardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.old = os.getcwd()
        os.chdir(self.repo)
        self.git("init", "-q", "-b", "main")
        self.write(BASE_FILES)
        self.commit("base")
        self.git("checkout", "-q", "-b", "devloop/fix")

    def tearDown(self):
        os.chdir(self.old)
        self.tmp.cleanup()

    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                        "-c", "commit.gpgsign=false", *args],
                       check=True, capture_output=True)

    def write(self, files):
        for rel, text in files.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def judge(self, files, branch="devloop/fix"):
        self.write(files)
        self.commit("change")
        tier, problems = guard.judge("main", branch)
        return tier, [rule for rule, _ in problems]


class TestWhatAnAutomatedPrMayNotTouch(GuardCase):
    def test_every_kind_of_grader_is_refused(self):
        for path in (".github/scripts/devloop_guard.py",
                     ".github/workflows/ci.yml", ".claude/devloop.json",
                     "tests/test_action_gate.py", "tests/test_new.py",
                     ".claude/skills/fix-from-house/SKILL.md", "pytest.ini"):
            with self.subTest(path):
                self.git("checkout", "-q", "-B", "devloop/fix", "main")
                tier, rules = self.judge({path: "changed\n"})
                self.assertEqual(rules, ["grader"])
                self.assertEqual(tier, "C")

    def test_deleting_a_safety_test_is_refused(self):
        (self.repo / "tests/test_action_gate.py").unlink()
        self.commit("drop it")
        self.assertEqual([r for r, _ in guard.judge("main")[1]], ["grader"])

    def test_a_manifest_may_change_its_version_and_nothing_else(self):
        tier, rules = self.judge(
            {"brain/config.yaml": 'name: brAIn\nversion: "1.0.1"\nslug: brain\n'})
        self.assertEqual((tier, rules), ("A", []))
        tier, rules = self.judge(
            {"brain/config.yaml": 'name: brAIn\nversion: "1.0.1"\nslug: other\n'})
        self.assertEqual(rules, ["version-only"])


    def test_the_retro_may_record_lessons_and_nothing_else(self):
        lessons = ".claude/skills/fix-from-house/lessons.json"
        self.assertEqual(self.judge({lessons: "[]\n"}), ("C", ["grader"]))
        self.git("checkout", "-q", "-B", "devloop/fix", "main")
        self.assertEqual(self.judge({lessons: "[]\n"}, "devloop-meta/retro"),
                         ("M", []))
        tier, rules = self.judge(
            {".claude/skills/fix-from-house/SKILL.md": "x\n"},
            "devloop-meta/retro")
        self.assertEqual(rules, ["grader"])


class TestTheTier(GuardCase):
    def test_tiers_follow_the_paths(self):
        for files, want in (
                ({"brain/panel/style.css": "b{}\n"}, "A"),
                ({"brain/panel/cards.py": "X = 2\n"}, "B"),
                ({"brain/panel/gate.py": "ALLOW = True\n"}, "C"),
                ({"brain/panel/cards.py": "X = 3\n",
                  "bright/panel/show.py": "Y = 2\n"}, "C")):
            with self.subTest(want=want, files=sorted(files)):
                self.git("checkout", "-q", "-B", "devloop/fix", "main")
                self.assertEqual(self.judge(files), (want, []))


if __name__ == "__main__":
    unittest.main()
