#!/usr/bin/env python3
"""Every test the fast run leaves out is a test that exists.

`conftest.SLOW` names tests by node id, and a node id is a string: a test
renamed or moved after the list was written stops matching, picks up no
mark, and the fast local run (`-m "not slow"`) quietly starts spending its
seconds on it again — or, the other way round, an entry that matches
nothing is a line somebody reads as a promise. Neither fails anything on
its own, so this holds each entry to a file, a class and a function the
source tree really has, read off the files' own syntax rather than by
collecting the suite a second time from inside it.
"""

import ast
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import conftest  # noqa: E402


def _names(tree: ast.Module) -> dict:
    """{class or function name: set of method names (empty for a function)}."""
    out: dict = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out[node.name] = {
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = set()
    return out


def _inherited(tree: ast.Module, cls: str, names: dict) -> set:
    """A class's methods with those of its bases in the same file, since
    unittest collects a test defined once on a base under every subclass."""
    found: set = set()
    seen: set = set()
    todo = [cls]
    bases = {n.name: [b.id for b in n.bases if isinstance(b, ast.Name)]
             for n in tree.body if isinstance(n, ast.ClassDef)}
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        found |= names.get(name, set())
        todo.extend(bases.get(name, []))
    return found


class TestEveryEntryNamesARealTest(unittest.TestCase):
    def test_every_entry_resolves(self):
        self.assertTrue(conftest.SLOW, "the fast run would leave nothing out")
        for entry in conftest.SLOW:
            with self.subTest(entry=entry):
                parts = entry.split("::")
                path = TESTS / parts[0]
                self.assertTrue(path.is_file(), f"{parts[0]} is not a test file")
                if len(parts) == 1:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                names = _names(tree)
                self.assertIn(parts[1], names,
                              f"{parts[0]} has no {parts[1]}")
                if len(parts) == 3:
                    self.assertIn(parts[2], _inherited(tree, parts[1], names),
                                  f"{parts[1]} has no {parts[2]}")

    def test_no_entry_is_listed_twice_or_under_another(self):
        """A test named alone inside a file or class already named whole is
        a line that does nothing, and the next edit trusts it."""
        entries = list(conftest.SLOW)
        self.assertEqual(len(entries), len(set(entries)))
        for entry in entries:
            for other in entries:
                if other != entry:
                    self.assertFalse(entry.startswith(other + "::"),
                                     f"{entry} is already covered by {other}")


class TestTheMarkIsWhatTheFilterReads(unittest.TestCase):
    def test_a_listed_node_is_slow_and_its_neighbour_is_not(self):
        entry = next(e for e in conftest.SLOW if e.count("::") == 2)
        self.assertTrue(conftest._is_slow(entry))
        self.assertTrue(conftest._is_slow(entry + "[case-1]"))
        self.assertFalse(conftest._is_slow(entry + "_and_more"))
        whole = next(e for e in conftest.SLOW if "::" not in e)
        self.assertTrue(conftest._is_slow(whole + "::TestAnything::test_x"))
        self.assertFalse(conftest._is_slow(whole[:-3] + "_other.py::test_x"))


if __name__ == "__main__":
    unittest.main()
