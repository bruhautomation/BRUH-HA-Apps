"""The Claude run queue: bounded, ordered, and on threads of its own.

Every engine run the server makes goes through `run_queue` (by way of
`server._claude`), so three claims carry the add-on's rate limit and a
Pi's memory: no more than `slots` runs at once, a seat always free of
scheduled work for a person's press, and waiters served safety, then
press, then scheduled. Each is driven here against the real queue with
real threads — a queue whose order is asserted by reading its heap would
pass while the wake-up path that actually admits a waiter was wrong,
which is the bug the first cut had (a press arriving behind only
scheduled waiters was never woken).
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import threading
import time
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import run_queue  # noqa: E402


class Gate:
    """A run that blocks its thread until released, and says it started."""

    def __init__(self):
        self.started: list[str] = []
        self.release = threading.Event()
        self.threads: dict[str, str] = {}

    def run(self, name: str) -> str:
        self.started.append(name)
        self.threads[name] = threading.current_thread().name
        self.release.wait(5)
        return name


async def until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.01)


class TestPriorityOrder(unittest.TestCase):
    def test_safety_then_press_then_scheduled_first_come_within_each(self):
        async def run():
            q = run_queue.RunQueue(slots=1)
            gate = Gate()
            first = asyncio.create_task(q.run(gate.run, "holder",
                                              priority=run_queue.PRESS))
            await until(lambda: gate.started == ["holder"])
            order = []

            def note(name):
                order.append(name)
                return name

            tasks = [
                asyncio.create_task(q.run(note, "sched-1",
                                          priority=run_queue.SCHEDULED)),
                asyncio.create_task(q.run(note, "press-1",
                                          priority=run_queue.PRESS)),
                asyncio.create_task(q.run(note, "sched-2",
                                          priority=run_queue.SCHEDULED)),
                asyncio.create_task(q.run(note, "safety",
                                          priority=run_queue.SAFETY)),
                asyncio.create_task(q.run(note, "press-2",
                                          priority=run_queue.PRESS)),
            ]
            await until(lambda: q.stats()["waiting"] == {
                "safety": 1, "press": 2, "scheduled": 2})
            gate.release.set()
            await asyncio.gather(first, *tasks)
            return order, q.stats()

        order, stats = asyncio.run(run())
        self.assertEqual(order, ["safety", "press-1", "press-2",
                                 "sched-1", "sched-2"])
        self.assertEqual(stats["running"], {"safety": 0, "press": 0,
                                            "scheduled": 0})
        self.assertEqual((stats["started"], stats["finished"]), (6, 6))


class TestTheSeatKeptForAPerson(unittest.TestCase):
    def test_scheduled_work_never_takes_the_last_seat(self):
        async def run():
            q = run_queue.RunQueue(slots=2)
            gate = Gate()
            one = asyncio.create_task(q.run(gate.run, "s1"))
            two = asyncio.create_task(q.run(gate.run, "s2"))
            await until(lambda: gate.started == ["s1"]
                        and q.stats()["waiting"]["scheduled"] == 1)
            # A second scheduled run waits with a seat free; a press does not.
            await asyncio.sleep(0.05)
            self.assertEqual(gate.started, ["s1"])
            press = asyncio.create_task(q.run(gate.run, "press",
                                              priority=run_queue.PRESS))
            await until(lambda: "press" in gate.started)
            self.assertEqual(q.stats()["running"],
                             {"safety": 0, "press": 1, "scheduled": 1})
            gate.release.set()
            await asyncio.gather(one, two, press)
            return gate.started

        started = asyncio.run(run())
        self.assertEqual(started, ["s1", "press", "s2"])

    def test_one_slot_still_runs_scheduled_work(self):
        """With a single seat there is nothing to keep back; reserving it
        would mean no scheduled run could ever start."""
        async def run():
            q = run_queue.RunQueue(slots=1)
            return await q.run(lambda: "ran")

        self.assertEqual(asyncio.run(run()), "ran")


class TestCancellation(unittest.TestCase):
    def test_a_cancelled_waiter_holds_no_seat(self):
        async def run():
            q = run_queue.RunQueue(slots=1)
            gate = Gate()
            holder = asyncio.create_task(q.run(gate.run, "holder",
                                               priority=run_queue.PRESS))
            await until(lambda: gate.started == ["holder"])
            waiter = asyncio.create_task(q.run(gate.run, "never",
                                               priority=run_queue.PRESS))
            await until(lambda: q.stats()["waiting"]["press"] == 1)
            waiter.cancel()
            gate.release.set()
            await holder
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            after = await q.run(lambda: "after", priority=run_queue.SCHEDULED)
            return after, q.stats(), gate.started

        after, stats, started = asyncio.run(run())
        self.assertEqual(after, "after")
        self.assertNotIn("never", started)
        self.assertEqual(stats["running"], {"safety": 0, "press": 0,
                                            "scheduled": 0})

    def test_a_raising_run_gives_its_seat_back(self):
        async def run():
            q = run_queue.RunQueue(slots=1)

            def boom():
                raise RuntimeError("the CLI fell over")

            with self.assertRaises(RuntimeError):
                await q.run(boom, priority=run_queue.PRESS)
            return await q.run(lambda: "next"), q.stats()

        value, stats = asyncio.run(run())
        self.assertEqual(value, "next")
        self.assertEqual(sum(stats["running"].values()), 0)


class TestItsOwnThreads(unittest.TestCase):
    def test_a_full_queue_does_not_starve_the_default_pool(self):
        """Store reads go through `asyncio.to_thread`; runs never take
        those threads, and a full run queue never makes a read wait."""
        async def run():
            q = run_queue.RunQueue(slots=2)
            gate = Gate()
            runs = [asyncio.create_task(q.run(gate.run, f"r{i}",
                                              priority=run_queue.PRESS))
                    for i in range(2)]
            await until(lambda: len(gate.started) == 2)
            read = await asyncio.wait_for(
                asyncio.to_thread(lambda: threading.current_thread().name), 2)
            gate.release.set()
            await asyncio.gather(*runs)
            return read, gate.threads

        read, threads = asyncio.run(run())
        self.assertTrue(all(name.startswith("claude-run")
                            for name in threads.values()), threads)
        self.assertFalse(read.startswith("claude-run"))


class TestTheServersOneHelper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def test_engine_runners_are_told_whether_a_person_pressed(self):
        engine = self.server.engine
        seen = []

        def fake(prompt, sp, **kw):
            seen.append(kw.get("pressed"))
            return {"ok": True, "response": prompt}

        def plain(value):
            # Not an engine runner: it is handed nothing it did not ask for.
            return value

        old = engine.run_analyst
        engine.run_analyst = fake
        try:
            async def run():
                await self.server._claude(engine.run_analyst, "a", "s",
                                          priority=run_queue.PRESS)
                await self.server._claude(engine.run_analyst, "b", "s")
                await self.server._claude(engine.run_analyst, "c", "s",
                                          priority=run_queue.SAFETY)
                return await self.server._claude(plain, "kept")

            self.assertEqual(asyncio.run(run()), "kept")
        finally:
            engine.run_analyst = old
        self.assertEqual(seen, [True, False, False])

    def test_a_queued_job_is_a_press_unless_the_scheduler_said_why(self):
        srv = self.server
        jobs = {"fixjob": {"kind": "fix"},
                "card-press": {"state": "queued"},
                "card-timer": {"state": "queued",
                               "because": "a finding it reads changed"}}
        old = dict(srv.JOBS)
        srv.JOBS.update(jobs)
        try:
            self.assertEqual(srv._job_priority("fixjob"), run_queue.PRESS)
            self.assertEqual(srv._job_priority("card-press"), run_queue.PRESS)
            self.assertEqual(srv._job_priority("card-timer"),
                             run_queue.SCHEDULED)
        finally:
            srv.JOBS.clear()
            srv.JOBS.update(old)

    def test_no_engine_run_bypasses_the_queue(self):
        """Every `engine.run_*` in the server is handed to `_claude`; a
        `to_thread` around one is a run on the store-read pool with no
        limit and no order, which is the whole failure this exists for."""
        import ast
        tree = ast.parse((PANEL / "server.py").read_text())
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "to_thread"):
                continue
            for arg in node.args[:1]:
                if (isinstance(arg, ast.Attribute)
                        and isinstance(arg.value, ast.Name)
                        and arg.value.id == "engine"
                        and arg.attr.startswith("run_")) or (
                        isinstance(arg, ast.Attribute)
                        and arg.attr == "validate_auth"):
                    offenders.append(node.lineno)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
