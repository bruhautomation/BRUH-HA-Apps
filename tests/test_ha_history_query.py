"""One place builds Core's history query, and it is not a string.

Three callers built it by hand — `ha_data.get_history`,
`closures.fetch_history` and `shadow.fetch_history` — each pasting
`','.join(ids)` into the URL after the `?`. `_rest_get`'s own docstring
says not to, and says why, and all three were written past it.

On the replay path the ids come out of an automation config that arrived
in an HTTP body, so an id carrying `&` is a second parameter rather than
a value: CodeQL reported that as a partial SSRF and was right. Off that
path the ids come from the registry and the same character corrupts the
call quietly, which is the failure nobody would ever trace.

So the shapes are asserted against a REAL aiohttp server rather than
against a string this file wrote: what matters is what reaches the wire,
and the valueless flags Core wants (`&minimal_response`) are exactly the
sort of detail a hand-written expectation gets wrong in the same way the
code does.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import ha_data  # noqa: E402

UTC = dt.timezone.utc
START = dt.datetime(2026, 2, 2, 0, 0, tzinfo=UTC)
END = dt.datetime(2026, 2, 3, 0, 0, tzinfo=UTC)


class TestWhatCountsAsAnId(unittest.TestCase):

    def test_an_ordinary_id_survives(self):
        self.assertEqual(ha_data.safe_entity_ids(["light.hall"]),
                         ["light.hall"])

    def test_the_characters_that_steer_a_request_are_dropped(self):
        # Each of these, pasted into a URL after a `?`, is a different
        # request: a second parameter, a fragment, another path.
        for bad in ("light.hall&foo=bar", "light.hall#frag",
                    "../../secrets", "light.hall bar", "light.hall%26x",
                    "Light.Hall", "http://evil/x", "light.hall/../x"):
            self.assertEqual(ha_data.safe_entity_ids([bad]), [], bad)

    def test_a_bad_one_does_not_take_the_good_ones_with_it(self):
        self.assertEqual(
            ha_data.safe_entity_ids(["light.hall", "&evil", "switch.fan"]),
            ["light.hall", "switch.fan"])

    def test_order_is_kept_and_repeats_are_not(self):
        self.assertEqual(
            ha_data.safe_entity_ids(["b.two", "a.one", "b.two"]),
            ["b.two", "a.one"])

    def test_nothing_is_not_an_empty_filter(self):
        # A `filter_entity_id=` with nothing after it asks Core for the
        # whole house, which is the opposite of what a caller with no
        # ids wanted.
        self.assertNotIn("filter_entity_id", ha_data.history_params([]))
        self.assertNotIn("filter_entity_id",
                         ha_data.history_params(["not an id"]))


class TestThePathHoldsNothingTyped(unittest.TestCase):

    def test_it_is_a_timestamp_and_a_prefix(self):
        path = ha_data.history_path(START)
        self.assertEqual(path, "/history/period/2026-02-02T00:00:00+00:00")
        self.assertNotIn("?", path)
        self.assertNotIn("&", path)


class TestNobodyBuildsItByHandAnyMore(unittest.TestCase):
    """The grep that stops a fourth copy, not a test of behaviour.

    Same reasoning as the one guarding `atomic_write`: the pattern is
    easy to reach for, three modules reached for it, and a fourth would
    reintroduce the alert without touching a line anything here drives.
    """

    def test_no_panel_module_pastes_ids_into_a_url(self):
        offenders = []
        for path in sorted(PANEL.rglob("*.py")):
            body = path.read_text(encoding="utf-8")
            # The literal query key next to an `=` inside an f-string or
            # a concatenation — never as a params dict key, which is
            # quoted and followed by a `"]` or `":`.
            for m in re.finditer(r"[?&]filter_entity_id=", body):
                line = body[:m.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(BASE_DIR)}:{line}")
        self.assertEqual(offenders, [],
                         "build the query with ha_data.history_params, not "
                         "by pasting ids into the URL")


class TestWhatActuallyReachesTheWire(unittest.IsolatedAsyncioTestCase):
    """Driven against a real aiohttp server, because the flags are the point."""

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        self.seen = {}

        async def handler(request):
            self.seen["path"] = request.path
            self.seen["query"] = dict(request.query)
            self.seen["url"] = str(request.rel_url)
            return web.json_response([])

        app = web.Application()
        app.router.add_get("/history/period/{stamp}", handler)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self._core = ha_data.CORE_API
        ha_data.CORE_API = str(self.server.make_url("")).rstrip("/")

    async def asyncTearDown(self):
        ha_data.CORE_API = self._core

    async def fetch(self, **kw):
        await ha_data._rest_get(
            self.client.session, ha_data.history_path(START),
            params=ha_data.history_params(**kw))
        return self.seen

    async def test_an_id_with_an_ampersand_cannot_add_a_parameter(self):
        seen = await self.fetch(ids=["light.hall", "switch.fan&admin=1"])
        self.assertEqual(seen["query"], {"filter_entity_id": "light.hall"})
        self.assertNotIn("admin", seen["query"])

    async def test_the_valueless_flags_arrive_as_keys(self):
        seen = await self.fetch(ids=["light.hall"], minimal=True,
                                no_attributes=True)
        self.assertIn("minimal_response", seen["query"])
        self.assertIn("no_attributes", seen["query"])
        self.assertEqual(seen["query"]["minimal_response"], "")

    async def test_the_end_time_rides_as_a_parameter(self):
        seen = await self.fetch(ids=["light.hall"], end=END)
        self.assertEqual(seen["query"]["end_time"], END.isoformat())

    async def test_the_path_is_the_period_and_nothing_else(self):
        seen = await self.fetch(ids=["light.hall"])
        self.assertEqual(seen["path"], ha_data.history_path(START))


if __name__ == "__main__":
    unittest.main()
