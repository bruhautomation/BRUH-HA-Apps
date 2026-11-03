#!/usr/bin/env python3
"""Every supervised loop beats, and has a time after which not beating is
a stall.

Ten of the panel's loops (the notification flush, the brief, the bedtime
pass, healing, the weekly report, the maintainer, HA-side answers, the
notification suggestions, the Resident and the situation) never called
`_beat` and were started with no `stall_after_s`, so a loop hung on an
await looked exactly like a healthy one: alive, and never asked how long
since it went round (#638).

Two halves: the source holds every `_supervise` call to a threshold and its
loop to a beat (the worker is the one exception — it blocks on its queue
for hours by design and is judged by how long it has been on one job); and
a loop that stops going round, supervised for real, turns health degraded.
"""

import ast
import asyncio
import sys
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import health  # noqa: E402

SERVER = PANEL / "server.py"
# Judged by `busy_s` against `busy_limit_s` instead: idle on its queue for
# hours is the worker's health.
NOT_BEATING = {"worker"}


def supervised(tree: ast.AST) -> list[tuple[str, str, ast.Call]]:
    """`(loop name, coroutine function, call)` for every `_supervise(...)`."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_supervise" and len(node.args) >= 2):
            name = node.args[0]
            coro = node.args[1]
            if (isinstance(name, ast.Constant) and isinstance(coro, ast.Call)
                    and isinstance(coro.func, ast.Name)):
                out.append((name.value, coro.func.id, node))
    return out


class TestTheSourceHoldsEveryLoopToABeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        cls.funcs = {n.name: n for n in ast.walk(cls.tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        cls.loops = supervised(cls.tree)

    def test_the_loops_were_found(self):
        self.assertGreaterEqual(len(self.loops), 15)

    def test_every_loop_has_a_stall_threshold(self):
        missing = [name for name, _fn, call in self.loops
                   if name not in NOT_BEATING
                   and not any(k.arg == "stall_after_s" for k in call.keywords)]
        self.assertEqual(missing, [])

    def test_every_loop_beats_under_its_own_name(self):
        missing = []
        for name, fn, _call in self.loops:
            if name in NOT_BEATING:
                continue
            body = self.funcs.get(fn)
            beats = body is not None and any(
                isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_beat" and n.args
                and isinstance(n.args[0], ast.Constant) and n.args[0].value == name
                for n in ast.walk(body))
            if not beats:
                missing.append(f"{name} ({fn})")
        self.assertEqual(missing, [])

    def test_every_loop_has_words_in_health(self):
        self.assertEqual([n for n, _f, _c in self.loops if n not in health.LOOPS], [])


class TestAStalledLoopIsDegraded(unittest.TestCase):
    def test_a_loop_that_stops_going_round(self):
        import server

        async def go():
            async def stuck():
                server._beat("stuck")
                await asyncio.Event().wait()     # an await that never returns

            task = server._supervise("stuck", stuck(), stall_after_s=60)
            await asyncio.sleep(0)
            try:
                fresh = server._loop_health()["stuck"]
                later = server._loop_health(
                    server.LOOPS["stuck"]["beat_at"] + 61)["stuck"]
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                server.LOOPS.pop("stuck", None)
            return fresh, later

        fresh, later = asyncio.run(go())
        self.assertEqual(health.problems({"loops": {"stuck": fresh}}), [])
        found = health.problems({"loops": {"stuck": later}})
        self.assertEqual([p["state"] for p in found], ["degraded"])
        self.assertEqual(found[0]["id"], "loop:stuck")


if __name__ == "__main__":
    unittest.main()
