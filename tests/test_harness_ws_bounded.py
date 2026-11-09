"""The harness page's question to Home Assistant is bounded: a Core that
never answers gets an error back, not a request handler held forever (which
held the capture's runner cleanup, and the test suite, with it)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))


class TestTheHarnessQuestionIsBounded(unittest.TestCase):
    def test_a_core_that_never_answers_gets_a_504_promptly(self):
        import server  # noqa: PLC0415
        from aiohttp import web  # noqa: PLC0415
        from aiohttp.test_utils import TestClient, TestServer  # noqa: PLC0415

        async def never(session, commands, **kw):
            await asyncio.sleep(30)
            return [{"ok": True, "result": {}}]

        async def go():
            app = web.Application()
            app.router.add_get("/devloop/harness/ws", server.h_harness_ws)
            async with TestClient(TestServer(app)) as client:
                started = time.monotonic()
                r = await client.get("/devloop/harness/ws", params={
                    "msg": json.dumps({"type": "get_states"})})
                return r.status, await r.json(), time.monotonic() - started

        with unittest.mock.patch.object(server, "HARNESS_WS_TIMEOUT_S", 0.3, create=True), \
                unittest.mock.patch("ha_data._ws_calls", never):
            status, body, took = asyncio.run(asyncio.wait_for(go(), 15))
        self.assertEqual(status, 504)
        self.assertIn("did not answer in time", body["error"])
        self.assertLess(took, 5)

    def test_the_bound_is_below_the_pages_own_wait(self):
        import server  # noqa: PLC0415
        import devloop.screens as screens  # noqa: PLC0415
        self.assertLess(server.HARNESS_WS_TIMEOUT_S, screens.ANSWERS_MAX_S)
