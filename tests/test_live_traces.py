"""The trace checks read what Core is holding NOW, under the key Core uses.

Three checks — `auto.trace_error`, `auto.condition_never_passes` and
`auto.already_running` — read `.storage/trace.saved_traces`, which Core
writes only as it shuts down (`trace/__init__.py`,
`_async_store_traces_at_stop`), keyed `automation.<config id>`
(`ActionTrace.key = f"{domain}.{item_id}"`, trace/models.py) and with
every run nested as `{"extended_dict": ..., "short_dict": ...}`
(`BaseTrace.as_dict`). The checks looked runs up by ENTITY id and read
`script_execution` at the top level of each row, so on a real install
they could not fire at all — and the suite passed throughout, because
its fixture was keyed by entity id and written flat: the code's own
guess, written down twice.

What replaces it is `trace/list` over the WebSocket, one command per
domain. Its answer was read off Core rather than guessed:
`trace/websocket_api.py` registers `trace/list` with `domain` required
and `item_id` optional and answers `async_list_traces`, which is
`trace.as_short_dict()` for every run in every bucket of that domain
(`trace/util.py`); `as_short_dict` is `last_step`, `run_id`, `state`,
`script_execution`, `timestamp: {start, finish}`, `domain`, `item_id`,
`error` only when there was one, and `not_triggered: True` for the
change-it-looked-at-and-declined rows Core keeps in a bucket of their
own; `AutomationTrace` adds `trigger`. So the fake below answers with
exactly those keys, and the tests drive the real `snapshot.collect`
against it — a fake that answered with the shape the checks wanted
would prove only that it matched the code that mocked it.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import checks  # noqa: E402
import ha_data  # noqa: E402

snapshot = checks.snapshot
automations = checks.automations

NOW = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.timezone.utc).timestamp()
# What the UI writes for an automation's id: a millisecond timestamp,
# which is nothing like the entity id it registers under.
UI_ID = "1700000000000"


def iso(seconds_ago: float) -> str:
    return dt.datetime.fromtimestamp(
        NOW - seconds_ago, tz=dt.timezone.utc).isoformat()


def short_dict(item_id: str, run_id: str, execution: str | None,
               seconds_ago: float, *, domain: str = "automation",
               state: str = "stopped", error: str | None = None,
               not_triggered: bool = False) -> dict:
    """`ActionTrace.as_short_dict()` + `AutomationTrace`'s `trigger`."""
    row = {"last_step": "action/0", "run_id": run_id, "state": state,
           "script_execution": execution,
           "timestamp": {"start": iso(seconds_ago),
                         "finish": None if state == "running"
                         else iso(seconds_ago - 1)},
           "domain": domain, "item_id": item_id}
    if domain == "automation":
        row["trigger"] = "state of binary_sensor.kitchen_motion"
    if not_triggered:
        row["not_triggered"] = True
    if error is not None:
        row["error"] = error
    return row


class FakeCore(unittest.IsolatedAsyncioTestCase):
    """A Core that speaks the WebSocket handshake and a little REST.

    `TRACES` answers `trace/list` by domain; a domain missing from it is
    refused the way Core refuses a command it cannot run. Everything else
    a checks pass asks for answers empty or not at all, which `collect`
    is built to survive — that is what lets this drive the real thing.
    """

    TRACES: dict = {}
    STATES: list = []

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        traces = self.TRACES
        states = self.STATES
        self.asked: list[dict] = []
        asked = self.asked

        async def ws_handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "auth_required"})
            async for msg in ws:
                data = msg.json()
                if data.get("type") == "auth":
                    await ws.send_json({"type": "auth_ok"})
                    continue
                asked.append(data)
                if data.get("type") == "trace/list":
                    domain = data.get("domain")
                    if domain in traces:
                        reply = {"success": True, "result": traces[domain]}
                    else:
                        reply = {"success": False, "error": {
                            "code": "unknown_command",
                            "message": "Unknown command."}}
                elif data.get("type", "").endswith("_registry/list"):
                    reply = {"success": True, "result": []}
                else:
                    reply = {"success": False, "error": {
                        "code": "unknown_command", "message": "no"}}
                await ws.send_json({"id": data["id"], "type": "result",
                                    **reply})
            return ws

        async def rest_states(request):
            return web.json_response(states)

        async def rest_services(request):
            return web.json_response([])

        app = web.Application()
        app.router.add_get("/websocket", ws_handler)
        app.router.add_get("/api/states", rest_states)
        app.router.add_get("/api/services", rest_services)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        for mod, name, value in (
                (ha_data, "CORE_WS", str(self.server.make_url("/websocket"))),
                (ha_data, "CORE_API", str(self.server.make_url("/api"))),
                (snapshot, "SUPERVISOR_API",
                 str(self.server.make_url("/supervisor")))):
            self.addCleanup(setattr, mod, name, getattr(mod, name))
            setattr(mod, name, value)


class TestTheFetchReadsCoresOwnShape(FakeCore):
    TRACES = {
        "automation": [
            short_dict(UI_ID, "b", "error", 60, error="Entity not found"),
            short_dict(UI_ID, "a", "finished", 3600),
            # Changes the trigger looked at and declined. Not runs.
            short_dict(UI_ID, "n1", None, 30, not_triggered=True),
            # Still going: no verdict yet.
            short_dict(UI_ID, "r1", None, 5, state="running"),
            # An automation with no `id:` — Core files every one of them
            # under "automation.None", so none of them is nameable.
            short_dict("None", "x", "error", 60, error="boom"),
        ],
        "script": [short_dict("wake", "s1", "finished", 120,
                              domain="script")],
    }

    async def test_runs_are_keyed_by_config_id_and_oldest_first(self):
        got = await snapshot.live_traces(self.client.session)
        self.assertEqual(sorted(got), ["automation." + UI_ID, "script.wake"])
        rows = got["automation." + UI_ID]
        self.assertEqual([r["run_id"] for r in rows], ["a", "b"])
        self.assertEqual(rows[-1]["error"], "Entity not found")

    async def test_it_asks_for_both_domains_in_one_round_trip(self):
        await snapshot.live_traces(self.client.session)
        lists = [a for a in self.asked if a.get("type") == "trace/list"]
        self.assertEqual(sorted(a["domain"] for a in lists),
                         ["automation", "script"])


class TestARefusalIsNotAQuietHouse(FakeCore):
    TRACES = {"automation": []}   # script refused

    async def test_either_domain_refused_answers_none(self):
        self.assertIsNone(await snapshot.live_traces(self.client.session))


STATES = [
    {"entity_id": "automation.kitchen_motion", "state": "on",
     "attributes": {"friendly_name": "Kitchen motion light", "id": UI_ID,
                    "last_triggered": iso(60)},
     "last_changed": iso(30 * 86400), "last_updated": iso(60)},
]


class TestTheCollectorEndToEnd(FakeCore):
    """`collect` against the fake, then the real check over what it built."""

    TRACES = TestTheFetchReadsCoresOwnShape.TRACES
    STATES = STATES

    async def test_a_ui_automation_that_failed_is_found(self):
        snap = await snapshot.collect(NOW)
        self.assertTrue(snap["available"]["traces"], snap["errors"])
        # The bug, stated as the lookup it used to make: the entity id
        # names no bucket, because Core never keyed one by it.
        self.assertNotIn("automation.kitchen_motion", snap["traces"])
        found = automations.trace_error(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["entity_id"], "automation.kitchen_motion")
        self.assertIn("Kitchen motion light", found[0]["text"])
        self.assertIn("Entity not found", found[0]["detail"])

    async def test_the_stored_shape_reads_the_same(self):
        """A snapshot captured from Core's store — `BaseTrace.as_dict()` —
        is unwrapped rather than read at the top level, which is the
        other half of what kept the checks dead."""
        snap = await snapshot.collect(NOW)
        key = "automation." + UI_ID
        snap["traces"][key] = [{"extended_dict": dict(r, trace={}),
                                "short_dict": r}
                               for r in snap["traces"][key]]
        found = automations.trace_error(snap, NOW)
        self.assertEqual(len(found), 1)


class TestCouldNotLookSkipsTheChecks(FakeCore):
    TRACES = {}   # both refused
    STATES = STATES

    async def test_the_key_is_unavailable_and_the_checks_do_not_run(self):
        snap = await snapshot.collect(NOW)
        self.assertFalse(snap["available"]["traces"])
        self.assertIn("traces", snap["errors"])
        result = checks.run_all(snap, NOW)
        for cid in ("auto.trace_error", "auto.condition_never_passes",
                    "auto.already_running"):
            self.assertIn(cid, result["skipped"])
            self.assertIn("traces", result["skipped"][cid])
            self.assertNotIn(cid, result["ran"])


class TestAConditionThatPassesAtNight(unittest.TestCase):
    """Five daytime `failed_conditions` runs are the ordinary shape of a
    night-only motion rule. `last_triggered` is set only once the
    conditions pass, so a recent one is the proof the condition works."""

    def snap(self, last_triggered):
        rows = [short_dict(UI_ID, str(i), "failed_conditions", 600 * i)
                for i in range(5)]
        return {
            "now": NOW, "available": {}, "errors": {},
            "states": {"automation.kitchen_motion": {
                "state": "on",
                "attributes": {"friendly_name": "Night light", "id": UI_ID,
                               "last_triggered": last_triggered}}},
            "entities": [], "devices": [], "areas": [],
            "traces": {"automation." + UI_ID: rows},
        }

    def test_ran_last_night_says_nothing(self):
        self.assertEqual(automations.condition_never_passes(
            self.snap(iso(14 * 3600)), NOW), [])

    def test_never_ran_is_the_finding(self):
        found = automations.condition_never_passes(self.snap(None), NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("never run", found[0]["detail"])

    def test_quiet_for_a_month_is_the_finding(self):
        found = automations.condition_never_passes(
            self.snap(iso(40 * 86400)), NOW)
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
