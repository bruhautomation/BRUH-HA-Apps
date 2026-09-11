"""A successful mutation answers `result: null`, and that is not a failure.

`_ws_commands` returns Core's `result` field per command and `None` for
anything that went wrong. Right for every command that ASKS for
something — a registry list, a statistics window, the energy prefs, all
of which answer with a payload — and wrong for one that CHANGES
something, because Core answers a successful `input_number/delete` with
`result: null`. That lands in the same slot, with the same value, as a
refusal.

The rehearsal read it that way and reported *"Home Assistant would not
delete input_number.brain_test_reading"* on every clean run, while its
own leftovers scan — reading the states, where the helper really had
gone — disagreed with it in the same sentence. Two answers to "did that
work", and the louder one was wrong.

Driven against a real aiohttp WebSocket server speaking Core's handshake
and result frames, because the defect is in how a frame is READ: a fake
that hands back a hand-written dict proves only that the fake matches the
code that mocked it, and the shipped fake returned a truthy `{}` where
Core sends `null` — which is why no test could see this.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import ha_data  # noqa: E402


class WsCase(unittest.IsolatedAsyncioTestCase):
    """A Core that authenticates and then answers whatever was asked."""

    ANSWERS: dict = {}

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        answers = self.ANSWERS

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "auth_required"})
            async for msg in ws:
                data = msg.json()
                if data.get("type") == "auth":
                    await ws.send_json({"type": "auth_ok"})
                    continue
                reply = answers.get(data.get("type"),
                                    {"success": True, "result": None})
                await ws.send_json({"id": data["id"], "type": "result", **reply})
            return ws

        app = web.Application()
        app.router.add_get("/websocket", handler)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self._ws = ha_data.CORE_WS
        ha_data.CORE_WS = str(self.server.make_url("/websocket"))
        self.addCleanup(setattr, ha_data, "CORE_WS", self._ws)


class TestASuccessfulDeleteIsNotAFailure(WsCase):
    ANSWERS = {
        "input_number/delete": {"success": True, "result": None},
        "input_number/create": {"success": True,
                                "result": {"id": "brain_test_reading_2"}},
        "config/entity_registry/remove": {"success": True, "result": None},
    }

    async def test_a_null_result_is_reported_as_ok(self):
        got = await ha_data._ws_calls(
            self.client.session, [{"type": "input_number/delete",
                                   "input_number_id": "x"}])
        self.assertEqual(got, [{"ok": True, "result": None, "error": ""}])

    async def test_the_old_reading_cannot_tell_it_from_a_refusal(self):
        """The bug, stated as the thing the old shape could not express."""
        got = await ha_data._ws_commands(
            self.client.session, [{"type": "input_number/delete",
                                   "input_number_id": "x"}])
        self.assertEqual(got, [None])   # indistinguishable, by construction

    async def test_a_created_item_carries_the_id_core_minted(self):
        got = await ha_data._ws_calls(
            self.client.session, [{"type": "input_number/create"}])
        self.assertTrue(got[0]["ok"])
        self.assertEqual(got[0]["result"]["id"], "brain_test_reading_2")


class TestARefusalSaysWhy(WsCase):
    ANSWERS = {
        "input_number/delete": {
            "success": False,
            "error": {"code": "not_found", "message": "Unable to find x"}},
    }

    async def test_the_message_rides_back(self):
        got = await ha_data._ws_calls(
            self.client.session, [{"type": "input_number/delete"}])
        self.assertFalse(got[0]["ok"])
        self.assertEqual(got[0]["error"], "Unable to find x")

    async def test_ws_commands_still_answers_none(self):
        """The asking callers are unchanged — that contract still holds."""
        got = await ha_data._ws_commands(
            self.client.session, [{"type": "input_number/delete"}])
        self.assertEqual(got, [None])


class TestOrderAndArity(WsCase):
    ANSWERS = {
        "a/one": {"success": True, "result": 1},
        "b/two": {"success": False, "error": {"message": "no"}},
        "c/three": {"success": True, "result": None},
    }

    async def test_results_come_back_in_the_order_asked(self):
        got = await ha_data._ws_calls(
            self.client.session,
            [{"type": "a/one"}, {"type": "b/two"}, {"type": "c/three"}])
        self.assertEqual([c["ok"] for c in got], [True, False, True])
        self.assertEqual([c["result"] for c in got], [1, None, None])


if __name__ == "__main__":
    unittest.main()
