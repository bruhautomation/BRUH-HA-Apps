"""A route that raised is a fault the loop can see.

aiohttp answered a crashed route with 500 and logged the traceback to its
own logger, and nothing else happened: no journal row, so no fault row in
⚙ › Diagnostics, no problem file with the log tail, no issue in the
development loop. The middleware writes one journal row per route and
exception type per spacing window and re-raises, so the browser's answer
is unchanged and a polled route that crashes every 2.5 s is one row every
ten minutes. Driven over a real aiohttp app with the real middleware and
the real journal, pointed at this test's own file.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))


class TestACrashedRouteIsJournaled(unittest.TestCase):
    def setUp(self):
        self.server = importlib.import_module("server")
        self.journal = self.server.journal
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (self.journal.JOURNAL_FILE, dict(self.server._CRASH_SEEN))
        self.journal.JOURNAL_FILE = str(Path(self.tmp.name) / "journal.jsonl")
        self.server._CRASH_SEEN.clear()

    def tearDown(self):
        self.journal.JOURNAL_FILE, seen = self._old
        self.server._CRASH_SEEN.clear()
        self.server._CRASH_SEEN.update(seen)
        self.tmp.cleanup()

    def _app(self):
        app = web.Application(middlewares=[self.server.crash_middleware])

        async def boom(request):
            data = None
            return web.json_response(data["x"])  # TypeError, like a real one

        async def refused(request):
            raise web.HTTPBadRequest(text="bad path")

        async def fine(request):
            return web.json_response({"ok": True})

        app.router.add_get("/api/boom/{id}", boom)
        app.router.add_get("/api/refused", refused)
        app.router.add_get("/api/fine", fine)
        return app

    def _drive(self, paths: list[str]) -> list[int]:
        async def go():
            async with TestClient(TestServer(self._app())) as client:
                out = []
                for p in paths:
                    r = await client.get(p)
                    out.append(r.status)
                return out
        return asyncio.run(go())

    def test_the_answer_is_still_500_and_the_journal_says_where(self):
        self.assertEqual(self._drive(["/api/boom/7"]), [500])
        [row] = self.journal.tail(10)
        self.assertEqual((row["source"], row["outcome"]), ("panel", "crash"))
        self.assertTrue(self.journal.is_failure(row))
        self.assertFalse(self.journal.is_claude_run(row))
        self.assertIn("TypeError", row["error"])
        self.assertRegex(row["error"], r"@ test_panel_crash\.py:\d+")
        # The route pattern, not the path: one fault per route, not per id.
        self.assertEqual(row["extra"]["stage"], "GET /api/boom/{id}")

    def test_a_refusal_and_a_success_write_nothing(self):
        self.assertEqual(self._drive(["/api/refused", "/api/fine"]), [400, 200])
        self.assertEqual(self.journal.tail(10), [])

    def test_a_route_crashing_on_every_poll_is_one_row_per_window(self):
        self._drive(["/api/boom/1", "/api/boom/2", "/api/boom/3"])
        self.assertEqual(len(self.journal.tail(10)), 1)
        # Past the window it is said again, once.
        self.server._CRASH_SEEN.clear()
        self._drive(["/api/boom/4"])
        self.assertEqual(len(self.journal.tail(10)), 2)

    def test_the_fault_list_renders_it(self):
        self._drive(["/api/boom/1"])
        import reports
        rows = reports.faults({"versions": {"addon": "3.1.0"},
                               "health": {"state": "ok"},
                               "journal": self.journal.summary(24)})
        [row] = [r for r in rows if r["where"].startswith("Run (panel")]
        self.assertIn("GET /api/boom/{id}", row["where"])
        self.assertIn("ended crash", row["what"])
        self.assertIn("TypeError", row["detail"])


if __name__ == "__main__":
    unittest.main()
