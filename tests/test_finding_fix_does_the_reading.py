#!/usr/bin/env python3
""""What to do" is the person's step, never brAIn's reading.

Cards on a house said "Press Fix and brAIn reads the run's trace", "watch
whether it continues", "look in UniFi for a task scheduled at 5:20" and
"check the access point's channel utilisation". Each sends the person off
to read something — a trace, a log, a history, another app — that brAIn
reads with its own tools, or says brAIn will read it later when it could
have read it before writing. So a check's `fix`, and the investigation's
contract, say the step only a person can take (a battery, a decision), and
the reading is done first.

Two halves, because a check sentence only reaches the sweep when a fixture
plants its defect: every row the check test modules produce is linted
(`test_finding_text_plain`'s sweep), and every string literal in the check
modules is linted too, so a sentence no fixture reaches cannot keep the
old shape.
"""

import ast
import io
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PANEL_DIR = TESTS_DIR.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(TESTS_DIR))

import resident  # noqa: E402
from test_finding_text_plain import SWEEP_MODULES, _Capture  # noqa: E402

# What a fix may not say. The reading these name is brAIn's to do.
READING = re.compile(
    r"watch (?:whether|to see|if)\b"
    r"|\blook in\b"
    r"|\blook (?:it )?up\b"
    r"|press fix(?: it)? and brain reads"
    r"|\bcheck (?:the |its |their |whether |if )?[\w' -]{0,40}?"
    r"\b(?:log|logs|trace|traces|history|logbook)\b"
    r"|\blog tab\b"
    r"|look at (?:its|the|their) last run"
    r"|\bcheck (?:whether|if)\b",
    re.I)


def _docstrings(tree) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value,
                                                          ast.Constant):
                out.add(id(first.value))
    return out


def literals(path: Path):
    """Every string a check module could put on a card, f-strings with
    their placeholders read as blanks, docstrings left out."""
    tree = ast.parse(path.read_text())
    docs = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docs:
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            yield node.lineno, "".join(
                v.value if isinstance(v, ast.Constant) else "…"
                for v in node.values)


class TestTheLintSeesTheOldSentences(unittest.TestCase):
    def test_it_refuses_each_shape_from_the_report(self):
        for said in ("Press Fix and brAIn reads the run's trace",
                     "watch whether it continues",
                     "look in UniFi for a task scheduled at 5:20",
                     "check the add-on's log for the reason",
                     "Open the add-on's Log tab",
                     "Check whether the device is still alive"):
            self.assertRegex(said, READING)

    def test_it_lets_a_physical_step_through(self):
        for said in ("Replace the battery in the hall sensor.",
                     "Check its power and its connection, then reload its "
                     "integration.",
                     "Shut whatever is open: a window or a vent."):
            self.assertNotRegex(said, READING)


class TestNoCheckSendsAPersonToRead(unittest.TestCase):
    def test_no_literal_in_a_check_module(self):
        bad = []
        for path in sorted((PANEL_DIR / "checks").glob("*.py")):
            for line, text in literals(path):
                m = READING.search(text)
                if m:
                    bad.append(f"{path.name}:{line}: {m.group(0)!r} in "
                               f"{text[:120]!r}")
        self.assertEqual(bad, [])

    def test_no_row_the_sweep_produces(self):
        with _Capture() as cap:
            suite = unittest.defaultTestLoader.loadTestsFromNames(
                SWEEP_MODULES)
            result = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertTrue(cap.rows)
        bad = [f"{cid}: {row.get('fix')!r}" for cid, row, _snap in cap.rows
               if READING.search(str(row.get("fix") or ""))]
        self.assertEqual(bad, [])


class TestTheInvestigationDoesTheReadingFirst(unittest.TestCase):
    def test_the_contract_says_to_read_before_writing(self):
        text = resident.INVESTIGATE_SYSTEM
        self.assertIn("Before you write", text)
        for word in ("trace", "history", "registry", "reload"):
            self.assertIn(word, text)
        self.assertIn("watch whether", text)   # named as forbidden
        self.assertIn("cannot see", text)

    def test_the_contract_never_tells_the_person_to_read(self):
        # The contract quotes the forbidden shapes inside "never …"; what
        # it may not do is ask for one itself.
        for m in READING.finditer(resident.INVESTIGATE_SYSTEM):
            before = resident.INVESTIGATE_SYSTEM[max(0, m.start() - 80):m.start()]
            self.assertRegex(before.lower(), r"never|not ")


if __name__ == "__main__":
    unittest.main()
