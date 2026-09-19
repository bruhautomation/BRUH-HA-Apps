"""The event bus, driven against a real Home Assistant handshake.

A hand-rolled fake of a protocol proves only that the fake matches the
code that mocked it — which is why `_ws_calls`' `result: null` bug lived
for as long as the suite's fake returned a truthy `{}` where Core sends
`null`. Everything here therefore runs against an aiohttp WebSocket server
that speaks Core's own handshake (`auth_required` → `auth` → `auth_ok`),
answers `subscribe_events` with a `result` frame, and sends `event` frames
the way Core does.

What is asserted, in the order the failures would hurt:

* the token goes down the socket and never into the log — an add-on log is
  a thing people paste into issues;
* the subscription is the named list and never `subscribe_events` with no
  type, which is every event Core fires;
* a dropped socket comes back, which is the one behaviour a listener has
  that a request does not;
* the ceiling counts what it drops, because a listener that silently
  discards nine tenths of its input is one nobody can trust;
* a consumer that raises does not end the subscription, and does not get
  reported as Home Assistant dropping the connection;
* and a dev checkout with no token starts, because the panel has to come
  up on a machine that is not inside Home Assistant.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import eventbus  # noqa: E402
import signals  # noqa: E402

TOKEN = "supervisor-token-nobody-should-ever-see-in-a-log"


def state_changed(entity_id: str, to: str, was: str = "off",
                  **attrs) -> dict:
    """One `event` frame in Core's shape."""
    return {
        "id": 1, "type": "event",
        "event": {
            "event_type": "state_changed",
            "time_fired": "2026-09-15T12:00:00.000000+00:00",
            "origin": "LOCAL",
            "context": {"id": "01ABC", "user_id": None, "parent_id": None},
            "data": {
                "entity_id": entity_id,
                "old_state": {"entity_id": entity_id, "state": was,
                              "attributes": {}},
                "new_state": {"entity_id": entity_id, "state": to,
                              "attributes": dict(attrs)},
            },
        },
    }


class CoreCase(unittest.IsolatedAsyncioTestCase):
    """A Core that authenticates, accepts subscriptions, and sends what a
    test tells it to."""

    # What the server sends once the subscriptions are in.
    FRAMES: list[dict] = []
    # Close the socket after the frames rather than holding it open.
    CLOSE_AFTER = True

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        self.seen_auth: list[dict] = []
        self.subscribed: list[dict] = []
        self.connections = 0
        self.ready = asyncio.Event()
        self.sent = asyncio.Event()
        test = self

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            test.connections += 1
            await ws.send_json({"type": "auth_required", "ha_version": "2026.9"})
            async for msg in ws:
                data = msg.json()
                if data.get("type") == "auth":
                    test.seen_auth.append(data)
                    await ws.send_json({"type": "auth_ok", "ha_version": "2026.9"})
                    continue
                if data.get("type") == "subscribe_events":
                    test.subscribed.append(data)
                    await ws.send_json({"id": data["id"], "type": "result",
                                        "success": True, "result": None})
                    if len(test.subscribed) >= len(eventbus.EVENT_TYPES):
                        test.ready.set()
                        for frame in test.FRAMES:
                            await ws.send_json(frame)
                        test.sent.set()
                        if test.CLOSE_AFTER:
                            await ws.close()
                            return ws
            return ws

        app = web.Application()
        app.router.add_get("/websocket", handler)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

        self.addCleanup(setattr, eventbus, "CORE_WS", eventbus.CORE_WS)
        self.addCleanup(setattr, eventbus, "SUPERVISOR_TOKEN",
                        eventbus.SUPERVISOR_TOKEN)
        eventbus.CORE_WS = str(self.server.make_url("/websocket"))
        eventbus.SUPERVISOR_TOKEN = TOKEN

    def bus(self, **kwargs) -> tuple[eventbus.EventBus, list[dict]]:
        """A bus wired to the fake Core, and the list its signals land in.

        The session is the test client's own, so the socket really is one
        aiohttp opened and closed — a bus that made its own would leave a
        connector open past the test.
        """
        got: list[dict] = []
        kwargs.setdefault("session_factory", lambda: self.client.session)
        bus = eventbus.EventBus(got.append, **kwargs)
        self.addAsyncCleanup(bus.stop)
        return bus, got

    async def settle(self, bus, *, frames: bool = True) -> None:
        """Wait for the handshake, and for the frames if any were sent."""
        await asyncio.wait_for(self.ready.wait(), timeout=5)
        if frames:
            await asyncio.wait_for(self.sent.wait(), timeout=5)
        # One turn of the loop for the pump to read what the server sent.
        for _ in range(20):
            await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# The handshake
# ---------------------------------------------------------------------------

class TestTheHandshake(CoreCase):
    FRAMES: list[dict] = []
    CLOSE_AFTER = False

    async def test_the_token_reaches_core(self):
        bus, _ = self.bus()
        await bus.start()
        await self.settle(bus, frames=False)
        self.assertEqual(self.seen_auth[0]["access_token"], TOKEN)

    async def test_and_never_reaches_the_log(self):
        """An add-on log is a thing people paste into issues."""
        with self.assertLogs("brain.eventbus", level="DEBUG") as caught:
            bus, _ = self.bus()
            await bus.start()
            await self.settle(bus, frames=False)
            await bus.stop()
        blob = "\n".join(caught.output)
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn("access_token", blob)

    async def test_only_the_named_event_types_are_subscribed(self):
        """`subscribe_events` with no type is every event Core fires."""
        bus, _ = self.bus()
        await bus.start()
        await self.settle(bus, frames=False)
        asked = [s.get("event_type") for s in self.subscribed]
        self.assertEqual(asked, list(eventbus.EVENT_TYPES))
        self.assertNotIn(None, asked)

    async def test_stats_says_it_is_connected_and_since_when(self):
        bus, _ = self.bus()
        await bus.start()
        await self.settle(bus, frames=False)
        stats = bus.stats()
        self.assertTrue(stats["connected"])
        self.assertGreater(stats["connected_since"], 0)
        self.assertEqual(sorted(stats), sorted([
            "connected", "connected_since", "reconnects", "events_seen",
            "events_dropped", "signals_emitted", "last_event_at",
            "idle_reason", "last_error"]))

    async def test_a_second_start_is_not_a_second_socket(self):
        """Two subscriptions deliver every event twice, and the duplicate
        looks exactly like a house doing something twice."""
        bus, _ = self.bus()
        await bus.start()
        await self.settle(bus, frames=False)
        await bus.start()
        await asyncio.sleep(0.05)
        self.assertEqual(self.connections, 1)

    async def test_stop_lets_go_of_the_socket(self):
        bus, _ = self.bus()
        await bus.start()
        await self.settle(bus, frames=False)
        await bus.stop()
        self.assertFalse(bus.stats()["connected"])


class TestAuthRefused(unittest.IsolatedAsyncioTestCase):
    """A rejected token is reported and retried, never raised out of the
    listener — the panel must not fall over because Core said no."""

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"type": "auth_required"})
            async for _msg in ws:
                await ws.send_json({"type": "auth_invalid",
                                    "message": "Invalid access token"})
                await ws.close()
                return ws
            return ws

        app = web.Application()
        app.router.add_get("/websocket", handler)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.addCleanup(setattr, eventbus, "CORE_WS", eventbus.CORE_WS)
        self.addCleanup(setattr, eventbus, "SUPERVISOR_TOKEN",
                        eventbus.SUPERVISOR_TOKEN)
        eventbus.CORE_WS = str(self.client.server.make_url("/websocket"))
        eventbus.SUPERVISOR_TOKEN = TOKEN

    async def test_the_refusal_lands_on_stats_rather_than_on_the_panel(self):
        bus = eventbus.EventBus(lambda _s: None,
                                session_factory=lambda: self.client.session)
        self.addAsyncCleanup(bus.stop)
        with self.assertLogs("brain.eventbus", level="WARNING"):
            await bus.start()
            for _ in range(200):
                if bus.stats()["last_error"]:
                    break
                await asyncio.sleep(0.01)
        self.assertIn("auth rejected", bus.stats()["last_error"])
        self.assertNotIn(TOKEN, bus.stats()["last_error"])


# ---------------------------------------------------------------------------
# Reading events
# ---------------------------------------------------------------------------

class TestWhatComesOut(CoreCase):
    CLOSE_AFTER = False
    FRAMES = [
        # Not a signal: a reading nothing holds a fact about.
        state_changed("sensor.grid_power", "412", was="408"),
        # A signal, and hot: a leak detector reading wet.
        state_changed("binary_sensor.under_sink", "on",
                      device_class="moisture", friendly_name="Under sink"),
        # A signal: an entity brAIn holds a fact about.
        state_changed("light.hall", "on", friendly_name="Hall"),
    ]

    async def test_only_what_matters_becomes_a_signal(self):
        bus, got = self.bus(known_ids=lambda: {"light.hall"})
        await bus.start()
        await self.settle(bus)
        self.assertEqual([s["subject"] for s in got],
                         ["binary_sensor.under_sink", "light.hall"])

    async def test_the_leak_comes_out_hot_and_the_light_does_not(self):
        bus, got = self.bus(known_ids=lambda: {"light.hall"})
        await bus.start()
        await self.settle(bus)
        self.assertTrue(got[0]["hot"])
        self.assertFalse(got[1]["hot"])

    async def test_every_event_is_counted_including_the_ones_dropped(self):
        """"The house went quiet" and "the socket died" have to be
        tellable apart, which is what `events_seen` is for."""
        bus, got = self.bus(known_ids=lambda: {"light.hall"})
        await bus.start()
        await self.settle(bus)
        stats = bus.stats()
        self.assertEqual(stats["events_seen"], 3)
        self.assertEqual(stats["signals_emitted"], 2)
        self.assertGreater(stats["last_event_at"], 0)

    async def test_the_raw_hook_sees_everything_that_survived_the_ceiling(self):
        raw: list[tuple] = []
        bus, _got = self.bus(known_ids=lambda: set(),
                             on_event=lambda t, d: raw.append((t, d)))
        await bus.start()
        await self.settle(bus)
        self.assertEqual([t for t, _ in raw], ["state_changed"] * 3)

    async def test_a_consumer_that_raises_does_not_end_the_subscription(self):
        """A raise inside the pump would unwind, be reported as the socket
        dropping, and reconnect — so brAIn would lose its event stream
        over a typo in a consumer and the log would blame Core."""
        seen: list[dict] = []

        def boom(signal):
            seen.append(signal)
            raise RuntimeError("a consumer's bug")

        bus = eventbus.EventBus(
            boom, known_ids=lambda: {"light.hall"},
            session_factory=lambda: self.client.session)
        self.addAsyncCleanup(bus.stop)
        with self.assertLogs("brain.eventbus", level="WARNING"):
            await bus.start()
            await self.settle(bus)
        self.assertEqual(len(seen), 2)
        self.assertTrue(bus.stats()["connected"])
        self.assertEqual(bus.stats()["reconnects"], 0)
        self.assertIn("callback", bus.stats()["last_error"])


class TestAReplyIsASignalToo(CoreCase):
    CLOSE_AFTER = False
    FRAMES = [{
        "id": 2, "type": "event",
        "event": {"event_type": "mobile_app_notification_action",
                  "data": {"action": "BRAIN_WRONG",
                           "reply_text": "that cupboard is never opened"}},
    }]

    async def test_answering_a_push_reaches_the_resident(self):
        bus, got = self.bus()
        await bus.start()
        await self.settle(bus)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "reply")
        self.assertEqual(got[0]["source"], "reply:notification")
        self.assertIn("never opened", got[0]["text"])


class TestFramesThatAreNotEvents(CoreCase):
    CLOSE_AFTER = False
    FRAMES = [
        {"id": 9, "type": "result", "success": True, "result": None},
        {"id": 9, "type": "pong"},
        {"id": 9, "type": "event", "event": "not a dict"},
        state_changed("light.hall", "on"),
    ]

    async def test_only_event_frames_are_read(self):
        bus, got = self.bus(known_ids=lambda: {"light.hall"})
        await bus.start()
        await self.settle(bus)
        self.assertEqual(len(got), 1)
        self.assertEqual(bus.stats()["events_seen"], 1)


# ---------------------------------------------------------------------------
# Reconnecting
# ---------------------------------------------------------------------------

class TestItComesBack(CoreCase):
    CLOSE_AFTER = True
    FRAMES = [state_changed("light.hall", "on", friendly_name="Hall")]

    async def test_a_dropped_socket_is_reconnected(self):
        """The one behaviour a listener has that a request does not."""
        self.addCleanup(setattr, eventbus, "BACKOFF_BASE_S",
                        eventbus.BACKOFF_BASE_S)
        eventbus.BACKOFF_BASE_S = 0.01
        bus, got = self.bus(known_ids=lambda: {"light.hall"})
        with self.assertLogs("brain.eventbus", level="INFO"):
            await bus.start()
            # Waiting on the SIGNALS rather than on the connection count:
            # a second socket that has not read anything yet is a
            # reconnect that proves nothing, which is the assertion this
            # test exists to make.
            for _ in range(500):
                if len(got) >= 2:
                    break
                await asyncio.sleep(0.01)
        self.assertGreaterEqual(self.connections, 2)
        self.assertGreaterEqual(bus.stats()["reconnects"], 1)
        # And it is still doing its job on the second socket.
        self.assertGreaterEqual(len(got), 2)


class TestTheBackoffLadder(unittest.TestCase):

    def test_every_rung_is_longer_than_the_last_until_the_cap(self):
        """A backoff whose only test is that it returns a float is one
        nobody has checked the shape of."""
        rungs = [eventbus.backoff_delay(i, rand=lambda: 0.5) for i in range(8)]
        for earlier, later in zip(rungs, rungs[1:]):
            self.assertGreaterEqual(later, earlier)
        self.assertEqual(rungs[-1], eventbus.BACKOFF_MAX_S)

    def test_nothing_is_ever_instant_and_nothing_exceeds_the_cap(self):
        for rand in (lambda: 0.0, lambda: 1.0, lambda: 0.5):
            for i in range(12):
                delay = eventbus.backoff_delay(i, rand=rand)
                self.assertGreater(delay, 0.0)
                self.assertLessEqual(
                    delay, eventbus.BACKOFF_MAX_S * (1 + eventbus.BACKOFF_JITTER))

    def test_the_jitter_is_real_so_two_add_ons_do_not_knock_together(self):
        """A Core restart drops every add-on's socket at the same instant,
        and a fixed ladder makes all of them come back on the same second."""
        low = eventbus.backoff_delay(4, rand=lambda: 0.0)
        high = eventbus.backoff_delay(4, rand=lambda: 1.0)
        self.assertLess(low, high)


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------

class TestTheFloodCeiling(unittest.TestCase):
    """Driven through `_admits` directly: what is being tested is the
    arithmetic of a per-second window, and pushing four hundred frames
    through a socket to reach it would be testing aiohttp."""

    def setUp(self):
        self.bus = eventbus.EventBus(lambda _s: None, clock=lambda: 1000.0)

    def admit(self, n: int, entity: str, now: float = 1000.0) -> int:
        return sum(1 for _ in range(n)
                   if self.bus._admits("state_changed",
                                       {"entity_id": entity}, now))

    def test_under_the_ceiling_everything_is_looked_at(self):
        kept = self.admit(eventbus.MAX_EVENTS_PER_S, "sensor.power")
        self.assertEqual(kept, eventbus.MAX_EVENTS_PER_S)
        self.assertEqual(self.bus.stats()["events_dropped"], 0)

    def test_past_it_the_readings_are_the_ones_dropped(self):
        """A flood is nearly always one integration reporting a number,
        and dropping a door because a power meter is chatty would be the
        ceiling deciding what a house is told."""
        self.admit(eventbus.MAX_EVENTS_PER_S, "sensor.power")
        self.assertFalse(self.bus._admits("state_changed",
                                          {"entity_id": "sensor.power"}, 1000.0))
        self.assertTrue(self.bus._admits("state_changed",
                                         {"entity_id": "lock.front"}, 1000.0))

    def test_and_the_count_says_what_was_left_out(self):
        self.admit(eventbus.MAX_EVENTS_PER_S + 25, "sensor.power")
        self.assertEqual(self.bus.stats()["events_dropped"], 25)

    def test_past_the_hard_ceiling_everything_goes(self):
        """The bound this process actually needs. Something producing four
        hundred events a second is an integration in a loop."""
        self.admit(eventbus.HARD_CEILING_PER_S + 1, "sensor.power")
        self.assertFalse(self.bus._admits("state_changed",
                                          {"entity_id": "lock.front"}, 1000.0))

    def test_the_next_second_starts_again(self):
        self.admit(eventbus.HARD_CEILING_PER_S + 10, "sensor.power")
        self.assertTrue(self.bus._admits("state_changed",
                                         {"entity_id": "sensor.power"}, 1001.0))

    def test_a_reading_domain_is_the_same_list_the_timeline_drops(self):
        self.assertIn("sensor", eventbus.READING_DOMAINS)
        self.assertNotIn("lock", eventbus.READING_DOMAINS)
        self.assertNotIn("binary_sensor", eventbus.READING_DOMAINS)


# ---------------------------------------------------------------------------
# A machine that is not a house
# ---------------------------------------------------------------------------

class TestADevCheckoutStarts(unittest.IsolatedAsyncioTestCase):

    async def test_no_token_is_said_once_and_then_idle(self):
        """The panel has to come up on a machine that is not inside Home
        Assistant, and an import that works with a start that throws is the
        same failure one line later."""
        self.addCleanup(setattr, eventbus, "SUPERVISOR_TOKEN",
                        eventbus.SUPERVISOR_TOKEN)
        eventbus.SUPERVISOR_TOKEN = ""
        bus = eventbus.EventBus(lambda _s: None)
        with self.assertLogs("brain.eventbus", level="INFO") as caught:
            await bus.start()
        self.assertEqual(len(caught.output), 1)
        stats = bus.stats()
        self.assertFalse(stats["connected"])
        self.assertIn("SUPERVISOR_TOKEN", stats["idle_reason"])
        # And stopping an idle bus is not an error either.
        await bus.stop()


class TestTheContext(unittest.TestCase):

    def test_the_protected_list_is_read_through_the_one_parser(self):
        """A second reading of that option is a second answer to "may
        brAIn touch this", and the one that acts is the wrong one."""
        bus = eventbus.EventBus(lambda _s: None, protected="lock.front_door",
                                clock=lambda: 10.0)
        ctx = bus._refresh_context(10.0)
        self.assertTrue(ctx.is_protected("lock.front_door"))
        self.assertFalse(ctx.is_protected("light.hall"))

    def test_it_is_rebuilt_on_a_timer_and_not_per_event(self):
        calls: list[int] = []
        bus = eventbus.EventBus(lambda _s: None,
                                known_ids=lambda: calls.append(1) or {"light.a"})
        bus._refresh_context(100.0)
        bus._refresh_context(100.0 + eventbus.CTX_REFRESH_S - 1)
        self.assertEqual(len(calls), 1)
        bus._refresh_context(100.0 + eventbus.CTX_REFRESH_S + 1)
        self.assertEqual(len(calls), 2)

    def test_a_known_set_that_cannot_be_read_keeps_the_last_one(self):
        """"I could not look" is not "nothing is protected", and here the
        difference decides whether a lock moving is hot."""
        state = {"fail": False}

        def known():
            if state["fail"]:
                raise OSError("the store is mid-write")
            return {"light.hall"}

        bus = eventbus.EventBus(lambda _s: None, known_ids=known)
        first = bus._refresh_context(100.0)
        self.assertTrue(first.is_known("light.hall"))
        state["fail"] = True
        with self.assertLogs("brain.eventbus", level="DEBUG"):
            later = bus._refresh_context(100.0 + eventbus.CTX_REFRESH_S + 1)
        self.assertTrue(later.is_known("light.hall"))

    def test_the_bus_emits_signals_and_never_anything_else(self):
        """The architectural claim: its only output is `on_signal`."""
        import ast
        source = (PANEL / "eventbus.py").read_text(encoding="utf-8")
        names = {n.names[0].name.split(".")[0]
                 for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Import)}
        names |= {n.module.split(".")[0]
                  for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.ImportFrom) and n.module}
        for banned in ("server", "engine", "findings_store", "notify_router",
                       "cases", "subprocess"):
            self.assertNotIn(banned, names, banned)

    def test_a_lock_survives_the_filter_without_being_on_any_list(self):
        """`closures.is_closure` answers yes for every `lock`, so a front
        door reaches the Resident whether or not anybody put it on the
        protected list — which is the right answer and is why that one
        rule is read rather than restated here."""
        bus = eventbus.EventBus(lambda _s: None, clock=lambda: 1000.0)
        sig = bus._to_signal(
            "state_changed",
            {"entity_id": "lock.front", "old_state": {"state": "locked"},
             "new_state": {"state": "unlocked", "attributes": {}}},
            1000.0)
        self.assertEqual(sorted(sig), sorted(signals.SIGNAL_KEYS))
        self.assertEqual(sig["subject"], "lock.front")

    def test_a_reading_nothing_knows_about_is_not_a_signal(self):
        """The filter, said from the bus's side."""
        bus = eventbus.EventBus(lambda _s: None, clock=lambda: 1000.0)
        self.assertIsNone(bus._to_signal(
            "state_changed",
            {"entity_id": "sensor.grid_power", "old_state": {"state": "408"},
             "new_state": {"state": "412", "attributes": {}}}, 1000.0))

    def test_the_two_context_types_read_into_no_signal_here(self):
        """Subscribed for `on_event` and for the count; the reading of
        them is `actions.py`'s over the logbook, where Core has already
        walked the chain."""
        bus = eventbus.EventBus(lambda _s: None, clock=lambda: 1000.0)
        self.assertIsNone(bus._to_signal("call_service", {}, 1000.0))
        self.assertIsNone(bus._to_signal("automation_triggered", {}, 1000.0))


if __name__ == "__main__":
    logging.getLogger("brain.eventbus").setLevel(logging.DEBUG)
    unittest.main()
