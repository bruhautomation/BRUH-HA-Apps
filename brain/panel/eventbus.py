"""The event bus listener — the first thing in brAIn that is *watched*
rather than polled.

Every scheduled thing in this add-on is a timer or a predicate. The checks
run every six hours over a snapshot, the baselines are rebuilt nightly, the
evening pass wakes at a measured bedtime, and "something just happened,
does it matter?" has never had a path at all. The panel has spoken Core's
WebSocket since the registries needed listing (`ha_data._ws_commands_inner`)
and has never used the one command that makes it a stream:
``subscribe_events``.

This module is that subscription and nothing else. It connects, it
authenticates, it subscribes to a named handful of event types, it turns
the ones it has a reader for into :mod:`signals`, and it hands each to one
callback. Four rules keep it that small.

**It files nothing and it asks nothing.** No store write, no model, no
notification, no verdict. Its only output is ``on_signal(signal)``, and
the decision about what any of it means belongs one tier up, in the first
look. A listener that could file would be the old architecture with a
socket in front of it.

**It never subscribes to everything.** ``subscribe_events`` with no
``event_type`` is every event Core fires, which on a real house is tens of
thousands an hour of things nothing here reads — and the cost of reading
them lands on the event loop that also drives the chat stream and the
terminal proxy. Each entry in :data:`EVENT_TYPES` is named, and says who
reads it.

**A chatty house may not take the loop with it.** There is a per-second
ceiling, and past it readings are dropped first and everything is dropped
second. Both are counted and both ride in :func:`stats`, because a listener
that silently discards nine tenths of its input is one nobody can trust —
the same reason `episodes` counts the readings it drops rather than
quietly not showing them.

**A dev checkout must start.** With no ``SUPERVISOR_TOKEN`` there is
nothing to authenticate with, so ``start()`` says so once and stays idle
rather than raising or retrying a connection that cannot be made. The
panel has to come up on a machine that is not inside Home Assistant, and
an import that works and a start that throws is the same failure one line
later.

What it deliberately does **not** do is work out who caused a change.
``state_changed`` carries a context id and no chain; Home Assistant walks
that chain itself when it writes the logbook, which is where
:mod:`actions` reads it from. Re-deriving attribution off the raw stream
would be a second answer to "who did this", and the wrong one would
attribute somebody's press to an automation.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import time

import signals

log = logging.getLogger("brain.eventbus")

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
# The same two the rest of the panel reads, spelled the same way, so a
# test that points one at a fake server points this at it too.
CORE_WS = os.environ.get("BRAIN_CORE_WS", "ws://supervisor/core/websocket")

# What is subscribed, and who reads it. A type with no reader is a type
# that costs a frame per occurrence and buys nothing, so each one here
# names its consumer.
EVENT_TYPES = (
    # Read by `signals.from_state_change`, which returns None for the
    # overwhelming majority — a protected entity, a person, a closure, a
    # safety sensor or something brAIn holds a fact about is what survives.
    "state_changed",
    # Read by `signals.from_reply`: the companion app's notification
    # actions, which is how somebody answers a case from a lock screen.
    "mobile_app_notification_action",
    # Not read into a signal here, and subscribed on purpose: these two
    # are the CONTEXT a later change is read against, and the reading of
    # them is `actions.py`'s over the logbook, where Core has already
    # walked the chain. They reach `on_event` for whoever wires this up
    # and they are counted, which is what makes "the house went quiet"
    # tellable from "the socket died".
    "automation_triggered",
    "call_service",
)

# How many events a second this will look at before it starts dropping.
# A settled house publishes single digits; a house mid-recorder-purge or
# with a chatty power meter publishes hundreds, and the cost of each is
# a JSON parse on the loop that also drives the chat stream.
MAX_EVENTS_PER_S = 60
# Past this, everything goes — including a leak sensor, which is the cost
# and is said out loud rather than hidden behind an exception for hot
# events. Something producing four hundred events a second is an
# integration in a loop, and the checks pass is what still finds a leak on
# such a house six hours later. A ceiling nothing can exceed is the only
# kind that bounds this process.
HARD_CEILING_PER_S = 400
# Drop the cheap ones first. `signals.from_state_change` already refuses
# most of these, so what the ceiling buys is skipping the parse — which is
# the expensive half when a meter is reporting ten times a second.
READING_DOMAINS = frozenset({
    "sensor", "number", "input_number", "counter", "weather", "air_quality",
    "update", "button", "input_button", "event", "image", "todo",
    "stt", "tts", "conversation", "text", "input_text",
    "date", "datetime", "time", "input_datetime",
})

# Reconnect. Capped exponential with a jitter, because a Core restart
# drops every add-on's socket at the same instant and a fixed ladder makes
# all of them knock on the same second — `usage-limits-tracker`'s rule
# about a backoff that is itself the load.
BACKOFF_BASE_S = 2.0
BACKOFF_MAX_S = 120.0
BACKOFF_JITTER = 0.25          # ± a quarter, so no two add-ons agree
# How long a connection has to have lasted before it counts as healthy
# and the ladder resets. Without it a socket that authenticates and dies
# immediately reconnects at the base delay for ever.
HEALTHY_AFTER_S = 60.0
# aiohttp's own ping cadence. Ingress and Core both close an idle socket,
# and a listener that reconnects every two minutes is a listener whose
# reconnect count says nothing.
HEARTBEAT_S = 20.0
# How long the auth handshake may take before the attempt is abandoned.
# A socket that opens and never says `auth_required` is a proxy in front
# of something else, and waiting on it for ever is how a listener looks
# connected while reading nothing.
AUTH_TIMEOUT_S = 30.0

# How often the registry context is rebuilt. The protected list changes
# when somebody edits an option and restarts; the known-entity set changes
# when a fact is filed. Five minutes is far quicker than either and costs
# one list comprehension.
CTX_REFRESH_S = 300.0


def backoff_delay(attempt: int, rand=random.random) -> float:
    """How long to wait before reconnect attempt `attempt` (0-based).

    Capped exponential with a jitter, and `rand` is an argument so a test
    can pin it: a backoff whose only test is that it returns a float is a
    backoff nobody has checked the shape of, and the shape — that every
    rung is longer than the last until the cap, and that none is zero — is
    the whole of what it promises.
    """
    base = min(BACKOFF_BASE_S * (2 ** max(0, int(attempt))), BACKOFF_MAX_S)
    return max(0.1, base * (1.0 + BACKOFF_JITTER * (2.0 * rand() - 1.0)))


class EventBus:
    """One subscription to Home Assistant's event bus.

    ``on_signal`` is the only output and takes one :mod:`signals` dict. It
    is called from the loop the pump runs on, so a callback that blocks
    blocks the read — the wiring is expected to hand the signal to a queue
    and return, which is also what makes the first look's batching
    possible.

    ``on_event`` is the raw hook: ``(event_type, data)`` for every
    subscribed type that survived the ceiling, including the two this
    module reads no signal out of. It exists so the Resident can grow a
    reader without this module growing a verdict.

    ``known_ids`` is a callable answering the set of entity ids brAIn
    holds a fact about. A callable rather than a set, because the answer
    changes while this runs and a listener holding a snapshot from boot
    would be deaf to every fact filed since.

    ``rhythm_payload`` takes a callable for the same reason, and a dict
    still works. What it decides is which hours count as this house's
    night, and `rhythm.py` needs a fortnight of days before it has an
    answer at all — so a listener that froze the boot snapshot would use
    the fallback 23–6 for ever on exactly the install that has just
    measured its own.
    """

    def __init__(self, on_signal, *, on_event=None, known_ids=None,
                 protected=None, session_factory=None,
                 event_types=EVENT_TYPES, clock=time.time,
                 rhythm_payload=None, tz=None):
        self._on_signal = on_signal
        self._on_event = on_event
        self._known_ids = known_ids
        self._protected = protected
        self._session_factory = session_factory
        self._event_types = tuple(event_types)
        self._clock = clock
        self._rhythm = rhythm_payload
        self._tz = tz

        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._ctx = signals.EMPTY_CONTEXT
        self._ctx_at = 0.0
        # The per-second window: (second, count). One tuple rather than a
        # deque because the only question asked of it is "how many so far
        # this second", and a rolling window would be a second answer to
        # a ceiling that is stated per second.
        self._second = -1.0
        self._in_second = 0
        # The measured night, resolved on the context timer when it is a
        # callable. Seeded from the argument so a caller that handed in a
        # dict is answered without a call.
        self._rhythm_cache = None if callable(rhythm_payload) else rhythm_payload
        self._rhythm_at = 0.0

        self._connected = False
        self._connected_since = 0.0
        self._reconnects = 0
        self._events_seen = 0
        self._events_dropped = 0
        self._signals_emitted = 0
        self._last_event_at = 0.0
        self._idle_reason = ""
        self._last_error = ""

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Begin listening, or say once why it cannot.

        Idempotent: a second start while one is running is a no-op rather
        than a second socket, because two subscriptions would deliver every
        event twice and the duplicate would look exactly like a house doing
        something twice.
        """
        if self._task and not self._task.done():
            return
        if not SUPERVISOR_TOKEN:
            # A dev checkout, or the panel started outside the Supervisor.
            # Said once, at info: it is the ordinary state of a machine
            # that is not a Home Assistant box, and a warning per boot on
            # a developer's laptop is a warning nobody reads on a house.
            self._idle_reason = "no SUPERVISOR_TOKEN — nothing to authenticate with"
            log.info("event bus idle: %s", self._idle_reason)
            return
        self._stopping.clear()
        self._idle_reason = ""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop listening and wait for the pump to let go of the socket."""
        self._stopping.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._connected = False

    def stats(self) -> dict:
        """What this listener has seen, for `/api/diagnostics`.

        A queue nobody can see is a queue that silently swallows, and this
        one can fail in three directions that look identical from outside:
        a socket that never connected, a socket that connected and is
        reading nothing because the house is quiet, and a socket that is
        dropping everything because something is flooding it. Each of the
        three has its own number here.
        """
        return {
            "connected": self._connected,
            "connected_since": self._connected_since,
            "reconnects": self._reconnects,
            "events_seen": self._events_seen,
            "events_dropped": self._events_dropped,
            "signals_emitted": self._signals_emitted,
            "last_event_at": self._last_event_at,
            "idle_reason": self._idle_reason,
            "last_error": self._last_error,
        }

    # -- the context -------------------------------------------------------

    def _refresh_context(self, now: float) -> signals.RegistryContext:
        """The protected patterns and the known-entity set, rebuilt on a
        timer rather than per event.

        The protected list is read through `automation_writer`, which is
        the one parser for that option — a second reading of it is a second
        answer to "may brAIn touch this", and the one that acts is the
        wrong one. A failure to read either half leaves the previous
        context standing rather than an empty one: "I could not look" is
        not "nothing is protected", and here the difference decides whether
        a lock moving is hot.
        """
        if self._ctx_at and now - self._ctx_at < CTX_REFRESH_S:
            return self._ctx
        try:
            import automation_writer  # noqa: PLC0415 — panel-local
            patterns = automation_writer.protected_patterns(self._protected)
        except (ImportError, OSError, ValueError) as exc:
            log.debug("event bus kept the last protected list: %s", exc)
            return self._ctx
        known: frozenset[str] = frozenset()
        if callable(self._known_ids):
            try:
                known = frozenset(self._known_ids() or ())
            except (OSError, ValueError, TypeError) as exc:
                log.debug("event bus could not read the known entities: %s", exc)
                known = self._ctx.known
        self._ctx = signals.RegistryContext(patterns, known, built_at=now)
        self._ctx_at = now
        return self._ctx

    def _rhythm_now(self) -> dict | None:
        """This house's measured night, re-read on the context interval.

        A failure leaves what it had: `signals.night_window` falls back to
        a fixed 23–6 and says which answer it is giving, and reading "I
        could not look" as "this house has no rhythm" would file somebody's
        evening as their morning.
        """
        if not callable(self._rhythm):
            return self._rhythm
        now = self._clock()
        if self._rhythm_at and now - self._rhythm_at < CTX_REFRESH_S:
            return self._rhythm_cache
        try:
            self._rhythm_cache = self._rhythm() or None
        except Exception as exc:  # noqa: BLE001 — a consumer's bug is not ours
            log.debug("event bus kept the last measured night: %s", exc)
        self._rhythm_at = now
        return self._rhythm_cache

    # -- the ceiling -------------------------------------------------------

    def _admits(self, event_type: str, data: dict, now: float) -> bool:
        """Whether this event is looked at, counting the ones that are not.

        Two tiers, because a flood is nearly always one integration
        reporting a number and dropping a door because a power meter is
        chatty would be the ceiling deciding what a house is told. Past
        `MAX_EVENTS_PER_S` the readings go; past `HARD_CEILING_PER_S`
        everything does, that being the bound this process actually needs.
        """
        second = float(int(now))
        if second != self._second:
            self._second = second
            self._in_second = 0
        self._in_second += 1
        if self._in_second <= MAX_EVENTS_PER_S:
            return True
        if self._in_second > HARD_CEILING_PER_S:
            self._events_dropped += 1
            return False
        if event_type == "state_changed":
            entity = str((data or {}).get("entity_id") or "")
            if signals.domain_of(entity) in READING_DOMAINS:
                self._events_dropped += 1
                return False
        return True

    # -- the pump ----------------------------------------------------------

    async def _run(self) -> None:
        """Connect, subscribe, read, and come back when it breaks."""
        attempt = 0
        while not self._stopping.is_set():
            started = self._clock()
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — see below
                # Deliberately wide, and deliberately reported. A socket
                # can fail with an OSError, an aiohttp client error, a
                # JSON error off a frame, a TimeoutError or a RuntimeError
                # from the handshake, and listing them is a list that goes
                # stale the first time aiohttp adds one — what matters is
                # that the listener comes back and that the reason is on
                # `stats()` rather than swallowed.
                self._last_error = f"{type(exc).__name__}: {exc}"[:200]
                log.warning("event bus dropped: %s", self._last_error)
            finally:
                self._connected = False
            if self._stopping.is_set():
                break
            # A connection that lasted is a healthy one, whatever ended it,
            # so the ladder starts again from the bottom. Without this a
            # nightly Core restart would walk the delay up to two minutes
            # over a week of perfectly good nights.
            if self._clock() - started >= HEALTHY_AFTER_S:
                attempt = 0
            self._reconnects += 1
            delay = backoff_delay(attempt)
            attempt += 1
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=delay)

    async def _session(self) -> None:
        """One socket, from the handshake to whatever ends it."""
        import aiohttp  # noqa: PLC0415 — the image has it; the suite may not

        if self._session_factory is not None:
            session = self._session_factory()
            owned = False
        else:
            session = aiohttp.ClientSession()
            owned = True
        try:
            async with session.ws_connect(CORE_WS,
                                          heartbeat=HEARTBEAT_S) as ws:
                await self._authenticate(ws)
                await self._subscribe(ws)
                self._connected = True
                self._connected_since = self._clock()
                log.info("event bus listening for %s",
                         ", ".join(self._event_types))
                await self._pump(ws, aiohttp.WSMsgType.TEXT)
        finally:
            if owned:
                await session.close()

    async def _authenticate(self, ws) -> None:
        """Core's handshake: `auth_required` → `auth` → `auth_ok`.

        The token is sent and never logged — not at debug, not inside a
        frame dump, not in the error a refusal raises. It is the
        Supervisor's, it reaches the Core API as a bearer, and an add-on
        log is a thing people paste into issues.
        """
        deadline = self._clock() + AUTH_TIMEOUT_S
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise RuntimeError("Home Assistant did not finish the "
                                   "WebSocket auth handshake in time")
            msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
            data = _frame(msg)
            if data is None:
                raise RuntimeError("the WebSocket closed during the auth "
                                   "handshake")
            kind = data.get("type")
            if kind == "auth_required":
                await ws.send_json({"type": "auth",
                                    "access_token": SUPERVISOR_TOKEN})
            elif kind == "auth_invalid":
                raise RuntimeError("WebSocket auth rejected by HA Core")
            elif kind == "auth_ok":
                return

    async def _subscribe(self, ws) -> None:
        """One `subscribe_events` per type, never one for all of them."""
        for i, event_type in enumerate(self._event_types, 1):
            await ws.send_json({"id": i, "type": "subscribe_events",
                                "event_type": event_type})

    async def _pump(self, ws, text_type) -> None:
        """Read frames until the socket ends, turning what it can into
        signals. Anything that is not an event frame is ignored — a
        `result` acknowledging a subscription is not news."""
        async for msg in ws:
            if self._stopping.is_set():
                return
            if msg.type != text_type:
                return
            data = _frame(msg)
            if data is None or data.get("type") != "event":
                continue
            event = data.get("event")
            if not isinstance(event, dict):
                continue
            self._handle(event)

    def _handle(self, event: dict) -> None:
        """One event frame: count it, admit it, and emit what it means."""
        event_type = str(event.get("event_type") or "")
        payload = event.get("data") if isinstance(event.get("data"), dict) else {}
        now = self._clock()
        self._events_seen += 1
        self._last_event_at = now
        if not self._admits(event_type, payload, now):
            return
        if callable(self._on_event):
            self._deliver(self._on_event, event_type, payload)
        signal = self._to_signal(event_type, payload, now)
        if signal is None:
            return
        self._signals_emitted += 1
        self._deliver(self._on_signal, signal)

    def _to_signal(self, event_type: str, payload: dict,
                   now: float) -> dict | None:
        """The one place an event becomes a signal, or does not."""
        if event_type == "state_changed":
            return signals.from_state_change(
                payload, self._refresh_context(now), now,
                rhythm_payload=self._rhythm_now(), tz=self._tz)
        if event_type == "mobile_app_notification_action":
            return signals.from_reply({**payload, "via": "notification"}, now)
        return None

    def _deliver(self, callback, *args) -> None:
        """Call out, and never let a caller's bug end the subscription.

        The callback is somebody else's code running inside a socket pump.
        A raise there would unwind through `_pump` into `_run`'s handler,
        be reported as the socket dropping, and reconnect — so brAIn would
        lose its event stream over a typo in a consumer, and the log would
        blame Home Assistant. It is reported here instead, where the
        sentence names the thing that actually failed.
        """
        if not callable(callback):
            return
        try:
            callback(*args)
        except Exception as exc:  # noqa: BLE001 — a consumer's bug is not ours
            self._last_error = f"callback: {type(exc).__name__}: {exc}"[:200]
            log.warning("event bus callback failed: %s", self._last_error)


def _frame(msg) -> dict | None:
    """One text frame as a dict, or None if it is not one.

    A frame that will not parse is not a reason to drop the socket: Core
    has never sent one, and treating a single bad frame as a dead
    connection would reconnect the whole subscription over it.
    """
    try:
        data = msg.json()
    except (ValueError, TypeError, AttributeError):
        return None
    return data if isinstance(data, dict) else None


__all__ = [
    "AUTH_TIMEOUT_S", "BACKOFF_BASE_S", "BACKOFF_JITTER", "BACKOFF_MAX_S",
    "CORE_WS", "CTX_REFRESH_S", "EVENT_TYPES", "EventBus",
    "HARD_CEILING_PER_S", "HEALTHY_AFTER_S", "HEARTBEAT_S",
    "MAX_EVENTS_PER_S", "READING_DOMAINS", "backoff_delay",
]
