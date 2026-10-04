"""The panel's long-lived loops: one that dies says so, and the worker
cannot die of one job.

`asyncio.create_task` keeps an exception to itself until somebody asks,
and nobody asked: a loop that raised left an unretrieved-exception line
at some later garbage collection while `/api/status` went on saying
"queued" and the health verdict said ok. And the generation worker had no
`except` at all, so `_run_fix`'s own error path — which writes the
findings store, which `atomic_write` re-raises out of on a full disk —
was enough to end it for good. Driven through the server's real
`_supervise`, `_worker`, `_loop_health` and the real `health` rules,
because "the loop is supervised" and "the verdict says so" are two claims
and only the second is what a person reads.

The scheduler's half is here too: a card that failed waits out a backoff
before the timer runs it again, a usage limit holds every card behind it,
and `/api/status` reads what it reads off the event loop.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import health  # noqa: E402


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        srv = self.server
        self._loops = dict(srv.LOOPS)
        self._worker_state = dict(srv.WORKER_STATE)
        self._jobs = dict(srv.JOBS)
        self._queue = srv.QUEUE
        self._failures = dict(srv.CARD_FAILURES)
        self._rate = dict(srv.RATE_LIMIT_STATE)
        srv.LOOPS.clear()
        srv.CARD_FAILURES.clear()
        srv.RATE_LIMIT_STATE.update(until=0.0, streak=0, detail="")

    def tearDown(self):
        srv = self.server
        srv.LOOPS.clear()
        srv.LOOPS.update(self._loops)
        srv.WORKER_STATE.clear()
        srv.WORKER_STATE.update(self._worker_state)
        srv.JOBS.clear()
        srv.JOBS.update(self._jobs)
        srv.QUEUE = self._queue
        srv.CARD_FAILURES.clear()
        srv.CARD_FAILURES.update(self._failures)
        srv.RATE_LIMIT_STATE.clear()
        srv.RATE_LIMIT_STATE.update(self._rate)


async def settle() -> None:
    """Let done-callbacks scheduled with `call_soon` run."""
    for _ in range(3):
        await asyncio.sleep(0)


class TestTheWorkerOutlivesItsJobs(ServerCase):
    def test_a_handler_that_raises_costs_its_own_job_and_nothing_else(self):
        srv = self.server
        calls = []

        async def fake_fix(job_id):
            calls.append(job_id)
            if job_id == "fix:1":
                # What `atomic_write` does on a read-only /data, from
                # inside `_run_fix`'s own except block.
                raise OSError(30, "Read-only file system")
            srv._set_job(job_id, state="done")

        old = srv._run_fix
        srv._run_fix = fake_fix
        try:
            async def run():
                srv.QUEUE = asyncio.Queue()
                srv.JOBS["fix:1"] = {"kind": "fix", "state": "queued"}
                srv.JOBS["fix:2"] = {"kind": "fix", "state": "queued"}
                task = srv._supervise("worker", srv._worker())
                await srv.QUEUE.put("fix:1")
                await srv.QUEUE.put("fix:2")
                await asyncio.wait_for(srv.QUEUE.join(), 3)
                await settle()
                alive = not task.done()
                health_now = srv._loop_health()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await settle()
                return alive, health_now, dict(srv.LOOPS["worker"])

            alive, during, after = asyncio.run(run())
        finally:
            srv._run_fix = old
        self.assertEqual(calls, ["fix:1", "fix:2"])
        self.assertTrue(alive, "the worker must still be taking jobs")
        self.assertEqual(srv.JOBS["fix:1"]["state"], "error")
        self.assertIn("Read-only", srv.JOBS["fix:1"]["error"])
        self.assertEqual(srv.JOBS["fix:2"]["state"], "done")
        self.assertTrue(during["worker"]["alive"])
        self.assertEqual(during["worker"]["busy_s"], 0)
        self.assertEqual(health._loop_problems({"loops": during}), [])
        # A cancelled loop is a shutdown, and says nothing.
        self.assertTrue(after["stopped"])


class TestADeadLoopIsAVerdict(ServerCase):
    def _run(self, coro_factory, name="checks", stall_after_s=None):
        srv = self.server

        async def run():
            task = srv._supervise(name, coro_factory(), stall_after_s)
            await asyncio.gather(task, return_exceptions=True)
            await settle()
            return srv._loop_health()

        with self.assertLogs("brain", level="WARNING") as logs:
            out = asyncio.run(run())
        return out, logs.output

    def test_a_loop_that_raised_is_reported_with_its_reason(self):
        async def dies():
            await asyncio.sleep(0)
            raise RuntimeError("the store went away")

        loops, logs = self._run(dies)
        row = loops["checks"]
        self.assertFalse(row["alive"])
        self.assertIn("RuntimeError: the store went away", row["error"])
        self.assertTrue(any("checks loop died" in line for line in logs), logs)
        problems = health._loop_problems({"loops": loops})
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["state"], "degraded")
        self.assertIn("has stopped", problems[0]["what"])
        self.assertIn("the store went away", problems[0]["fix"])

    def test_a_dead_worker_is_a_failed_panel(self):
        async def returns():
            return None

        loops, _logs = self._run(returns, name="worker")
        problems = health._loop_problems({"loops": loops})
        self.assertEqual([p["state"] for p in problems], ["failed"])
        self.assertIn("it returned", loops["worker"]["error"])

    def test_the_diagnostics_payload_carries_the_loops(self):
        """The rule reads `loops` off the payload every door serves, so
        the payload has to carry them — or the rule never fires."""
        async def dies():
            raise ValueError("boom")

        self._run(dies, name="weekly")
        # `_loop_health` skips loops from a closed event loop (an app that
        # has gone away), so the payload is built while one is open.
        async def payload():
            task = self.server._supervise("brief", self._stalled())
            self.server.LOOPS["brief"]["beat_at"] = time.time() - 4000
            self.server.LOOPS["brief"]["stall_after_s"] = 600
            out = self.server._loop_health()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return out

        loops = asyncio.run(payload())
        problems = health._loop_problems({"loops": loops})
        self.assertEqual([p["id"] for p in problems], ["loop:brief"])
        self.assertIn("has not gone round", problems[0]["what"])

    async def _stalled(self):
        await asyncio.sleep(3600)


class TestTheLoopRuleIsPure(unittest.TestCase):
    """`health` reads a dict; these are the shapes it is handed."""

    def test_no_loops_block_is_not_a_fault(self):
        self.assertEqual(health._loop_problems({}), [])
        self.assertEqual(health._loop_problems({"loops": None}), [])

    def test_a_worker_stuck_on_one_job(self):
        loops = {"worker": {"alive": True, "beat_age_s": 5, "busy_s": 5000,
                            "busy_limit_s": 3000}}
        problems = health._loop_problems({"loops": loops})
        self.assertEqual([p["id"] for p in problems], ["loop:worker:busy"])
        self.assertEqual(problems[0]["state"], "degraded")

    def test_an_idle_worker_waiting_hours_is_health(self):
        loops = {"worker": {"alive": True, "beat_age_s": 90_000, "busy_s": 0,
                            "busy_limit_s": 3000, "stall_after_s": None}}
        self.assertEqual(health._loop_problems({"loops": loops}), [])

    def test_a_stopped_loop_says_nothing(self):
        loops = {"scheduler": {"alive": False, "stopped": True, "error": ""}}
        self.assertEqual(health._loop_problems({"loops": loops}), [])


class TestAFailingCardBacksOff(ServerCase):
    def setUp(self):
        super().setUp()
        import settings_store
        self.settings = settings_store
        self.tmp = tempfile.TemporaryDirectory()
        self._settings_file = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "s.json")
        settings_store.save({"refresh_mode": "always"})

    def tearDown(self):
        self.settings.SETTINGS_FILE = self._settings_file
        self.tmp.cleanup()
        super().tearDown()

    def test_exponential_and_the_two_questions_agree(self):
        srv = self.server
        eff = {"id": "energy", "enabled": True, "refresh_hours": 1}
        now = 1_800_000_000.0
        base = srv.CARD_BACKOFF_BASE_S
        self.assertTrue(srv._refresh_due(eff, "", now, mode="always"))

        srv._note_card_failure("energy", "Claude run timed out", now=now)
        self.assertEqual(srv.CARD_FAILURES["energy"]["outcome"], "timeout")
        self.assertFalse(srv._refresh_due(eff, "", now + 60, mode="always"))
        self.assertTrue(srv._refresh_due(eff, "", now + base + 1, mode="always"))
        # "When" and "now?" are one arithmetic: the foot of the card says
        # the time the scheduler will actually queue it.
        self.assertEqual(srv._next_due(eff, "", now + 60), now + base)

        srv._note_card_failure("energy", "Claude run timed out", now=now)
        self.assertFalse(srv._refresh_due(eff, "", now + base + 1, mode="always"))
        self.assertTrue(srv._refresh_due(eff, "", now + 2 * base + 1,
                                         mode="always"))
        self.assertEqual(srv._next_due(eff, "", now + 60), now + 2 * base)

    def test_the_backoff_is_capped(self):
        srv = self.server
        now = 1_800_000_000.0
        srv.CARD_FAILURES["energy"] = {"count": 40, "at": now}
        self.assertEqual(srv._card_backoff_until("energy"),
                         now + srv.CARD_BACKOFF_MAX_S)

    def test_another_card_is_not_held(self):
        srv = self.server
        now = 1_800_000_000.0
        srv._note_card_failure("energy", "boom", now=now)
        self.assertTrue(srv._refresh_due({"id": "climate", "refresh_hours": 1},
                                         "", now + 1, mode="always"))


class TestAUsageLimitHoldsTheCards(ServerCase):
    def _row(self, **kw):
        # The shape `journal.record` writes for a Claude run.
        row = {"ts": 1_800_000_000.0, "source": "insight", "turns": 1,
               "duration_s": 0.5}
        row.update(kw)
        return row

    def test_it_escalates_and_a_success_ends_it(self):
        srv = self.server
        listen = srv._journal_rate_listener
        listen(self._row(outcome="rate_limited", ok=False,
                         error="You've hit your limit"))
        first = srv.RATE_LIMIT_STATE["until"]
        self.assertEqual(first, 1_800_000_000.0 + srv.RATE_LIMIT_PAUSE_S)
        listen(self._row(outcome="rate_limited", ok=False, error="again"))
        self.assertEqual(srv.RATE_LIMIT_STATE["until"],
                         1_800_000_000.0 + 2 * srv.RATE_LIMIT_PAUSE_S)
        listen(self._row(outcome="ok", ok=True))
        self.assertEqual(srv.RATE_LIMIT_STATE["until"], 0.0)
        self.assertEqual(srv.RATE_LIMIT_STATE["streak"], 0)

    def test_a_summary_row_about_the_same_failure_is_not_a_second_one(self):
        """`_generate` writes its own row about a failed card; it ran no
        model, so it must not double every streak."""
        srv = self.server
        srv._journal_rate_listener({"ts": 1.0, "source": "insight",
                                    "outcome": "rate_limited", "ok": False})
        self.assertEqual(srv.RATE_LIMIT_STATE["streak"], 0)

    def test_the_real_journal_reaches_it(self):
        """Through `journal.record` and its own listener list, because a
        row shape written down twice is a shape that drifts."""
        srv = self.server
        # The server's own copy: other test files swap `journal` in
        # sys.modules, and a listener registered on a copy nothing records
        # through is a test of nothing.
        jr = srv.journal
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = jr.JOURNAL_FILE
        jr.JOURNAL_FILE = str(Path(tmp.name) / "journal.jsonl")
        # Only this listener: a test that reloads `server` and starts its
        # app leaves one registration per reload, every one of them writing
        # this module's globals, and ten of them make a streak of ten.
        listeners = list(jr._LISTENERS)
        jr._LISTENERS[:] = []
        jr.on_record(srv._journal_rate_listener)
        try:
            jr.record("card", "rate_limited", ok=False,
                      error="You've hit your limit · resets 3pm",
                      duration_s=1.2, turns=1)
        finally:
            jr._LISTENERS[:] = listeners
            jr.JOURNAL_FILE = old
        self.assertGreater(srv.RATE_LIMIT_STATE["until"], time.time())
        self.assertEqual(srv.RATE_LIMIT_STATE["streak"], 1)


class TestNoSecondRefusal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def test_which_failures_skip_the_snapshot(self):
        nf = self.server._no_fallback
        self.assertTrue(nf({"ok": False, "error": "You've hit your limit"}))
        self.assertTrue(nf({"ok": False, "error": "OAuth token has expired"}))
        self.assertTrue(nf({"ok": False,
                            "error": "API Error: 529 Overloaded"}))
        # What the snapshot is the floor under.
        self.assertFalse(nf({"ok": False, "error": "max number of turns"}))
        self.assertFalse(nf({"ok": False, "error": "Claude run timed out"}))
        self.assertFalse(nf({"ok": False, "error": "unparseable"}))
        self.assertFalse(nf({"ok": True, "error": ""}))


class TestStatusReadsOffTheLoop(ServerCase):
    def test_generated_at_is_read_once_per_file_version(self):
        srv = self.server
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old = srv.INSIGHTS_DIR
        srv.INSIGHTS_DIR = Path(tmp.name)
        try:
            path = srv._insight_path("energy")
            path.write_text(json.dumps({"generated_at": "2026-10-01T08:00:00",
                                        "html": "x" * 1000}))
            reads = []
            real = srv._read_json

            def counting(p):
                reads.append(p)
                return real(p)

            srv._read_json = counting
            try:
                self.assertEqual(srv._generated_at("energy"),
                                 "2026-10-01T08:00:00")
                self.assertEqual(srv._generated_at("energy"),
                                 "2026-10-01T08:00:00")
                self.assertEqual(len(reads), 1)
                path.write_text(json.dumps({"generated_at": "2026-10-02T09:00:00"}))
                os.utime(path, ns=(time.time_ns(), time.time_ns() + 10**9))
                self.assertEqual(srv._generated_at("energy"),
                                 "2026-10-02T09:00:00")
                path.unlink()
                self.assertIsNone(srv._generated_at("energy"))
            finally:
                srv._read_json = real
        finally:
            srv.INSIGHTS_DIR = old

    def test_the_route_reads_on_another_thread(self):
        """The credential stores, every card and four stores are read in
        one call that never runs on the event loop's own thread."""
        from aiohttp.test_utils import TestClient, TestServer
        srv = self.server
        seen = []
        real = srv._status_payload

        def spy():
            seen.append(threading.current_thread() is threading.main_thread())
            return real()

        srv._status_payload = spy
        try:
            async def run():
                srv.QUEUE = asyncio.Queue()
                client = TestClient(TestServer(srv.make_app()))
                await client.start_server()
                try:
                    resp = await client.get("/api/status")
                    return resp.status, await resp.json()
                finally:
                    await client.close()

            status, body = asyncio.run(run())
        finally:
            srv._status_payload = real
        self.assertEqual(status, 200)
        self.assertIn("categories", body)
        self.assertEqual(seen, [False])


if __name__ == "__main__":
    unittest.main()
