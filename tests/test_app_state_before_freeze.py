#!/usr/bin/env python3
"""The panel never writes a key onto an aiohttp app that has started.

`on_startup` stored every supervised loop as `app["worker"] = …`, and two
memory routes did `request.app.setdefault("consolidations", …)`. By then
aiohttp has frozen the app, and each write is "DeprecationWarning:
Changing state of started or joined application is deprecated" — 114 of
them in one day's log, and an error in a later aiohttp (#637).

The keys the panel needs are made in `make_app`, before the app is frozen,
and what is written later goes INTO them (`app["tasks"][name] = …`), which
changes no state aiohttp guards.
"""

import ast
import sys
import unittest
import warnings
from pathlib import Path

from aiohttp import web

SERVER = Path(__file__).resolve().parent.parent / "brain" / "panel" / "server.py"


def _writes_app_key(node: ast.AST) -> bool:
    """`app[...] = …` or `request.app[...] = …` (not `app["tasks"][…]`)."""
    if not isinstance(node, (ast.Assign, ast.AugAssign)):
        return False
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    for tgt in targets:
        if not isinstance(tgt, ast.Subscript):
            continue
        holder = tgt.value
        if isinstance(holder, ast.Name) and holder.id == "app":
            return True
        if isinstance(holder, ast.Attribute) and holder.attr == "app":
            return True
    return False


class TestThePremise(unittest.TestCase):
    def test_a_frozen_app_warns_on_a_new_key(self):
        app = web.Application()
        app["tasks"] = {}
        app.freeze()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app["late"] = 1
        self.assertTrue(any(issubclass(w.category, DeprecationWarning)
                            for w in caught))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app["tasks"]["late"] = 1
        self.assertFalse([w for w in caught
                          if issubclass(w.category, DeprecationWarning)])


class TestNoKeyIsSetAfterTheStart(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(SERVER.read_text(encoding="utf-8"))

    def test_no_handler_or_startup_hook_writes_an_app_key(self):
        bad = []
        for fn in ast.walk(self.tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name == "make_app":
                # Its own body runs before the freeze; its nested hooks do not.
                bodies = [n for n in ast.walk(fn)
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and n is not fn]
            else:
                bodies = [fn]
            for body in bodies:
                for node in ast.walk(body):
                    if _writes_app_key(node):
                        bad.append(f"{body.name}:{node.lineno}")
        self.assertEqual(sorted(set(bad)), [])

    def test_no_setdefault_on_a_started_app(self):
        bad = [n.lineno for n in ast.walk(self.tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "setdefault"
               and isinstance(n.func.value, ast.Attribute)
               and n.func.value.attr == "app"]
        self.assertEqual(bad, [])

    def test_the_tasks_holder_is_made_before_the_freeze(self):
        sys.path.insert(0, str(SERVER.parent))
        import server  # noqa: PLC0415
        app = server.make_app()
        self.assertEqual(app["tasks"], {})


if __name__ == "__main__":
    unittest.main()
