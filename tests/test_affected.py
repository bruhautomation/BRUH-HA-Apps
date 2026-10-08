#!/usr/bin/env python3
"""tests/affected.py, driven over the repository it selects from.

A selector is judged by what it leaves out, and the failure it is built
against is the quiet one: a change whose tests were not selected reports a
green run over a break. So most of these ask the real module about real
files and check the answer against what the test files really contain,
read here independently — a test that wrote down the selector's own idea of
who imports what would only ever agree with it. The rules that could not
be shown on the repository as it stands (a stem nobody imports, a short
word in prose) are shown on a small index built for the purpose, and the
one that can is shown on both.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent
sys.path.insert(0, str(TESTS))

import affected  # noqa: E402

INDEX = None


def setUpModule():
    global INDEX
    INDEX = affected.Index()


# Paths this file asks about but no test may READ, spelled in pieces: the
# selector reads this file too, and a whole path in a string literal here
# is exactly the read that would make this file a test of it.
UNHEARD = "/".join(("brain", "panel", "zz_" + "unheard_of" + ".py"))
NOTE = "/".join(("docs", "design", "brain-ai-" + "first.md"))


def select(*paths, **kw):
    return affected.select(list(paths), INDEX, **kw)


def files_matching(pattern):
    """Every test file whose source matches ``pattern``, read here rather
    than through the module under test."""
    rx = re.compile(pattern, re.M)
    return {f"tests/{p.name}" for p in TESTS.glob("test_*.py")
            if rx.search(p.read_text(encoding="utf-8", errors="replace"))}


class TestAPanelModuleSelectsItsImporters(unittest.TestCase):
    def test_findings_store_selects_the_tests_that_import_it(self):
        for name in ("test_findings.py", "test_cases.py"):
            src = (TESTS / name).read_text(encoding="utf-8")
            self.assertRegex(src, r"(?m)^import findings_store\b",
                             f"{name} no longer imports findings_store")
        sel = select("brain/panel/findings_store.py")
        self.assertFalse(sel.whole)
        self.assertIn("tests/test_findings.py", sel.tests)
        self.assertIn("tests/test_cases.py", sel.tests)

    def test_every_plain_importer_is_selected(self):
        importers = files_matching(r"^\s*import findings_store\b")
        self.assertTrue(importers)
        self.assertLessEqual(importers, select(
            "brain/panel/findings_store.py").tests)

    def test_a_check_selects_the_importers_of_its_package(self):
        """checks/__init__.py imports every check, so `import checks` and
        `checks.run_all` exercise devices.py without naming it."""
        init = (REPO / "brain/panel/checks/__init__.py").read_text()
        self.assertRegex(init, r"from \. import \([^)]*\bdevices\b")
        sel = select("brain/panel/checks/devices.py")
        self.assertLessEqual(files_matching(r"^\s*import checks\b"), sel.tests)
        self.assertLessEqual(
            files_matching(r"^\s*from checks import[^\n]*\bdevices\b"), sel.tests)


class TestTheShapesOfAnImport(unittest.TestCase):
    """Every shape a test here uses to reach a module, on a small index."""

    def index(self, tests):
        return affected.Index(REPO, tests=tests, measures={}, scripts={})

    def test_each_import_context_is_seen_and_a_lookalike_is_not(self):
        idx = self.index({
            "tests/test_a.py": "import os, server as srv\n",
            "tests/test_b.py": "from server import h_status\n",
            "tests/test_c.py": 'server = importlib.import_module("server")\n',
            "tests/test_d.py": 'sys.modules.pop("server", None)\n',
            "tests/test_e.py": 'with patch("server._claude"):\n    pass\n',
            "tests/test_f.py": 'SRC = PANEL / "server.py"\n',
            "tests/test_g.py": "import serverless\n# the server is up\n",
            "tests/test_h.py": 'x = "server"\n',
        })
        sel = affected.select(["brain/panel/server.py"], idx)
        self.assertEqual(sel.tests, {f"tests/test_{c}.py" for c in "abcdef"})

    def test_a_short_stem_in_prose_selects_nothing(self):
        """`house` is a module and an ordinary word. Only an import, the
        file's own name or the test's own file name may select it."""
        idx = self.index({
            "tests/test_quiet.py": (
                '"""The house is quiet; a house check says nothing."""\n'
                "import os\nHOUSE = {'house': 1}\nhouse = None\n"),
            "tests/test_reads.py": "import house\n",
            "tests/test_house_book.py": "import house_book\n",
            "tests/test_household.py": "import household\n",
        })
        sel = affected.select(["brain/panel/house.py"], idx)
        self.assertEqual(sel.tests, {"tests/test_reads.py",
                                     "tests/test_house_book.py"})

    def test_the_same_holds_on_the_real_tests(self):
        src = (TESTS / "test_appliances.py").read_text(encoding="utf-8")
        self.assertRegex(src, r"\bhouse\b", "the fixture lost its prose")
        self.assertNotRegex(src, r"(?m)^\s*(import|from) house\b")
        sel = select("brain/panel/house.py")
        self.assertNotIn("tests/test_appliances.py", sel.tests)
        self.assertNotIn("tests/test_household.py", sel.tests)
        self.assertIn("tests/test_house.py", sel.tests)

    def test_a_brain_stem_does_not_select_another_addons_tests(self):
        """`import server` in a brAIn test is not about BRight's server."""
        idx = self.index({
            "tests/test_cases.py": "import server\n",
            "tests/test_bright_party.py": "x = 1\n",
            "tests/test_mixed.py": 'import server\nROOT / "bright"\n',
        })
        sel = affected.select(["bright/panel/server.py"], idx)
        self.assertEqual(sel.tests, {"tests/test_bright_party.py",
                                     "tests/test_mixed.py"})


class TestAScriptSelectsWhatDrivesIt(unittest.TestCase):
    def test_brain_learn_selects_every_test_naming_it(self):
        named = files_matching(r"brain-learn\.sh")
        self.assertTrue(named)
        sel = select("brain/scripts/brain-learn.sh")
        self.assertFalse(sel.whole)
        self.assertLessEqual(named, sel.tests)

    def test_a_sourced_helper_reaches_the_tests_of_its_callers(self):
        learn = (REPO / "brain/scripts/brain-learn.sh").read_text()
        self.assertIn("brain-run-source.sh", learn)
        sel = select("brain/scripts/brain-run-source.sh")
        self.assertLessEqual(files_matching(r"brain-learn\.sh"), sel.tests)

    def test_the_mcp_server_is_reached_by_its_file_name(self):
        named = files_matching(r"ha_mcp_server\.py")
        self.assertTrue(named)
        self.assertLessEqual(
            named, select("brain/ha-mcp-server/ha_mcp_server.py").tests)


class TestTheBrowserFiles(unittest.TestCase):
    def test_app_js_selects_the_brain_measures_and_no_others(self):
        sel = select("brain/panel/app.js")
        for m in ("measure-home.mjs", "measure-topbar.mjs",
                  "measure-settings.mjs"):
            self.assertIn(f"tests/manual/{m}", sel.measures)
        for m in ("measure-effects.mjs", "measure-print-panel.mjs",
                  "measure-print-card.mjs"):
            self.assertNotIn(f"tests/manual/{m}", sel.measures)
        readers = files_matching(r"""["'](?:[^"'\n]*/)?app\.js["']""")
        self.assertIn("tests/test_brain_addon.py", readers)
        self.assertLessEqual(readers, sel.tests)

    def test_bright_python_reaches_the_measures_that_boot_it(self):
        sel = select("bright/panel/server.py")
        self.assertIn("tests/manual/measure-effects.mjs", sel.measures)
        self.assertNotIn("tests/manual/measure-home.mjs", sel.measures)

    def test_a_fixture_selects_the_measures_that_import_it(self):
        sel = select("tests/manual/today-fixture.mjs")
        users = {f"tests/manual/{p.name}"
                 for p in (TESTS / "manual").glob("measure-*.mjs")
                 if "today-fixture" in p.read_text(encoding="utf-8")}
        self.assertTrue(users)
        self.assertEqual(sel.measures, users)

    def test_the_cli_prints_measures_on_request(self):
        out = subprocess.run(
            [sys.executable, str(TESTS / "affected.py"), "--measures",
             "brain/panel/style.css"],
            cwd=tempfile.gettempdir(), capture_output=True, text=True,
            timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        lines = out.stdout.split()
        self.assertIn("tests/manual/measure-topbar.mjs", lines)
        self.assertTrue(all(x.startswith("tests/manual/measure-")
                            for x in lines))


class TestTheWholeSuite(unittest.TestCase):
    def test_shared_infrastructure_is_everything(self):
        for path in ("tests/conftest.py", "tests/fake_claude.py",
                     "tests/brain_ha_env.py", "tests/corpus/build.py",
                     "pytest.ini", "tests/requirements-dev.txt"):
            with self.subTest(path=path):
                sel = select(path)
                self.assertTrue(sel.whole)
                self.assertEqual(sel.output(), ["tests/"])
                self.assertIn("shared test infrastructure", sel.reasons[0])

    def test_a_module_no_test_names_is_everything_and_says_which(self):
        sel = select(UNHEARD)
        self.assertTrue(sel.whole)
        self.assertEqual(sel.unplaced, [UNHEARD])
        self.assertEqual(sel.output(), ["tests/"])

    def test_every_panel_module_is_placed_or_falls_back(self):
        """Nothing may select nothing. The modules that fall back are
        printed, because that list is where a test is missing."""
        fallback = []
        modules = sorted(p for p in (REPO / "brain/panel").rglob("*.py")
                         if "__pycache__" not in p.parts)
        self.assertGreater(len(modules), 100)
        for path in modules:
            rel = path.relative_to(REPO).as_posix()
            sel = select(rel)
            self.assertTrue(sel.tests or sel.whole, rel)
            if sel.whole:
                fallback.append(rel)
        print(f"\nfalls back to the whole suite ({len(fallback)}): "
              + (", ".join(fallback) or "none"), file=sys.stderr)


class TestQuietFiles(unittest.TestCase):
    def test_a_design_note_nobody_reads_selects_nothing(self):
        self.assertTrue((REPO / NOTE).is_file())
        sel = select(NOTE)
        self.assertFalse(sel.whole)
        self.assertEqual(sel.output(), [])
        self.assertIn("nothing", sel.reasons[0])

    def test_the_cli_says_nothing_and_succeeds(self):
        out = subprocess.run(
            [sys.executable, str(TESTS / "affected.py"), NOTE],
            cwd=tempfile.gettempdir(), capture_output=True, text=True,
            timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, "")
        self.assertIn("nothing", out.stderr)

    def test_a_ci_script_a_test_runs_is_not_quiet(self):
        sel = select(".github/scripts/check-version-bump.sh")
        self.assertFalse(sel.whole)
        self.assertIn("tests/test_check_version_bump.py", sel.tests)


class TestTheAddonWideFiles(unittest.TestCase):
    def test_run_sh_selects_the_tests_that_read_it(self):
        sel = select("brain/run.sh")
        for t in ("test_addon_hardening.py", "test_brain_addon.py",
                  "test_permission_mode.py"):
            self.assertIn(f"tests/{t}", sel.tests)

    def test_another_addons_manifest_selects_its_own(self):
        sel = select("bright/config.yaml")
        self.assertIn("tests/test_bright_addon.py", sel.tests)
        self.assertIn("tests/test_addon_hardening.py", sel.tests)
        self.assertLessEqual(
            {f"tests/{p.name}" for p in TESTS.glob("test_bright_*.py")},
            sel.tests)


class TestTheIntegration(unittest.TestCase):
    def test_a_module_selects_everything_that_loads_the_package(self):
        loaders = files_matching(r"^\s*(import brain_ha_env|from brain_ha_env)")
        self.assertTrue(loaders)
        self.assertLessEqual(
            loaders, select("brain/custom_components/brain/todo.py").tests)


class TestTheseTwoFiles(unittest.TestCase):
    def test_this_file_selects_itself(self):
        self.assertEqual(select("tests/test_affected.py").tests,
                         {"tests/test_affected.py"})

    def test_the_selector_selects_this_file(self):
        sel = select("tests/affected.py")
        self.assertIn("tests/test_affected.py", sel.tests)
        self.assertFalse(sel.whole)

    def test_a_path_typed_from_another_directory_is_the_same_path(self):
        here = os.getcwd()
        try:
            os.chdir(REPO / "brain" / "panel")
            sel = affected.select(["findings_store.py"], INDEX)
        finally:
            os.chdir(here)
        self.assertIn("tests/test_findings.py", sel.tests)


class TestGit(unittest.TestCase):
    def test_committed_staged_unstaged_and_untracked_are_all_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                subprocess.run(
                    ["git", "-c", "user.email=t@example.invalid",
                     "-c", "user.name=t", *args],
                    cwd=tmp, check=True, capture_output=True, timeout=30)
            git("init", "-q", "-b", "main")
            for name in ("a.txt", "b.txt", "c.txt"):
                Path(tmp, name).write_text("1\n")
            git("add", ".")
            git("commit", "-q", "-m", "base")
            git("checkout", "-q", "-b", "work")
            Path(tmp, "committed.txt").write_text("x\n")
            git("add", "committed.txt")
            git("commit", "-q", "-m", "work")
            Path(tmp, "a.txt").write_text("2\n")          # unstaged
            Path(tmp, "b.txt").write_text("2\n")
            git("add", "b.txt")                            # staged
            Path(tmp, "new.txt").write_text("x\n")        # untracked
            got = affected.changed_from_git("main", Path(tmp))
        self.assertEqual(got, ["a.txt", "b.txt", "committed.txt", "new.txt"])

    def test_an_unknown_base_is_said_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "init", "-q"], cwd=tmp, check=True,
                           timeout=30)
            with self.assertRaises(RuntimeError):
                affected.changed_from_git("no-such-ref", Path(tmp))


class TestTheCommand(unittest.TestCase):
    def test_a_selection_runs_by_file_under_xdist(self):
        sel = affected.Selection(tests={"tests/test_b.py", "tests/test_a.py"})
        cmd = affected.pytest_command(sel, parallel=True)
        self.assertEqual(cmd[1:], ["-m", "pytest", "-q", "-n", "auto",
                                   "--dist", "loadfile",
                                   "tests/test_a.py", "tests/test_b.py"])

    def test_the_whole_suite_and_lf(self):
        sel = affected.Selection(whole=True, tests={"tests/test_a.py"})
        cmd = affected.pytest_command(sel, last_failed=True, parallel=False)
        self.assertEqual(cmd[1:], ["-m", "pytest", "-q", "--lf", "tests/"])

    def test_nothing_selected_is_nothing_to_run(self):
        self.assertEqual(affected.pytest_command(affected.Selection()), [])


if __name__ == "__main__":
    unittest.main()
