#!/usr/bin/env python3
"""The terminal proxy's headers, exercised rather than grepped.

brAIn publishes one ingress port, so ttyd is reached *through* the panel.
ttyd takes a generated Basic credential (its own port is reachable from the
LAN if a user publishes it), and the proxy holds that credential and
presents it upstream so an ingress user never meets a prompt. Two header
rules carry that design, and both are security properties:

- whatever `Authorization` the client sent is dropped before ours is added,
  or a browser holding a credential for the ingress origin could present it
  to ttyd in place of the real one;
- ttyd's `WWW-Authenticate` never reaches the browser, because a Basic-auth
  dialog inside the ingress iframe asks for a password nobody has been shown.

The first was asserted by grepping terminal_proxy.py for the literal line
`headers.pop("Authorization", None)`. That test passed for as long as the
guarantee was broken: the pop is case-sensitive and `_clean` keys its dict
by whatever case the client sent, so `AUTHORIZATION:` — a spelling HTTP
considers identical — went upstream beside the credential added after it.
These tests drive the functions instead.
"""

import base64
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

from multidict import CIMultiDict

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

_CRED_DIR = tempfile.TemporaryDirectory()
_CRED = Path(_CRED_DIR.name) / "terminal-credential"
_CRED.write_text("brain:s3cret\n", encoding="utf-8")
os.environ["BRAIN_TTYD_CREDENTIAL_FILE"] = str(_CRED)

import terminal_proxy  # noqa: E402

terminal_proxy = importlib.reload(terminal_proxy)

REAL = "Basic " + base64.b64encode(b"brain:s3cret").decode("ascii")


class _Request:
    """Just the attribute `_upstream_headers` reads. `request.headers` is a
    CIMultiDict carrying the case the client actually sent — which is the
    whole point of these tests, so it must not be a plain dict."""

    def __init__(self, headers):
        self.headers = CIMultiDict(headers)


def _auth_values(headers) -> list[str]:
    return [v for k, v in headers.items() if k.lower() == "authorization"]


class TestTheClientCredentialNeverReachesTtyd(unittest.TestCase):
    SPELLINGS = (
        "Authorization",
        "authorization",
        "AUTHORIZATION",
        "AuthoriZation",
        "aUTHORIZATION",
    )

    def test_every_spelling_is_replaced_by_ours(self):
        for spelling in self.SPELLINGS:
            with self.subTest(spelling=spelling):
                headers = terminal_proxy._upstream_headers(
                    _Request([(spelling, "Basic YXR0YWNrZXI6cHc=")])
                )
                self.assertEqual(
                    _auth_values(headers), [REAL],
                    "exactly one Authorization may go upstream, and it must "
                    "be the proxy's",
                )

    def test_the_clients_value_is_gone_entirely(self):
        """Not merely outranked — absent. Two Authorization headers leave it
        to ttyd which one counts, and that was never ours to decide."""
        for spelling in self.SPELLINGS:
            with self.subTest(spelling=spelling):
                headers = terminal_proxy._upstream_headers(
                    _Request([(spelling, "Basic YXR0YWNrZXI6cHc=")])
                )
                self.assertNotIn(
                    "Basic YXR0YWNrZXI6cHc=", list(headers.values())
                )

    def test_a_request_with_no_credential_still_carries_ours(self):
        headers = terminal_proxy._upstream_headers(
            _Request([("Accept", "text/html")])
        )
        self.assertEqual(_auth_values(headers), [REAL])
        self.assertEqual(headers.get("Accept"), "text/html")

    def test_ordinary_headers_survive(self):
        headers = terminal_proxy._upstream_headers(
            _Request([("Accept", "*/*"), ("User-Agent", "brAIn"),
                      ("AUTHORIZATION", "Basic bad")])
        )
        self.assertEqual(headers.get("Accept"), "*/*")
        self.assertEqual(headers.get("User-Agent"), "brAIn")

    def test_no_credential_file_means_no_authorization_at_all(self):
        """A missing credential must not fall back to the client's."""
        missing = Path(_CRED_DIR.name) / "does-not-exist"
        original = terminal_proxy.CREDENTIAL_FILE
        terminal_proxy.CREDENTIAL_FILE = str(missing)
        try:
            headers = terminal_proxy._upstream_headers(
                _Request([("AUTHORIZATION", "Basic YXR0YWNrZXI6cHc=")])
            )
            self.assertEqual(_auth_values(headers), [])
        finally:
            terminal_proxy.CREDENTIAL_FILE = original


class TestHopByHopHeadersAreDropped(unittest.TestCase):
    def test_every_hop_header_is_dropped_in_any_case(self):
        for name in sorted(terminal_proxy.HOP_BY_HOP):
            for spelling in (name, name.upper(), name.title()):
                with self.subTest(header=spelling):
                    cleaned = terminal_proxy._clean(
                        CIMultiDict([(spelling, "x"), ("Accept", "*/*")])
                    )
                    self.assertNotIn(
                        spelling, cleaned,
                        f"{spelling} must not be relayed",
                    )
                    self.assertEqual(cleaned.get("Accept"), "*/*")

    def test_the_ttyd_challenge_never_reaches_the_browser(self):
        """A Basic-auth dialog inside the ingress iframe asks for a password
        the user has never been shown."""
        for spelling in ("WWW-Authenticate", "www-authenticate",
                         "WWW-AUTHENTICATE"):
            with self.subTest(spelling=spelling):
                cleaned = terminal_proxy._clean(
                    CIMultiDict([(spelling, 'Basic realm="ttyd"')])
                )
                self.assertEqual(_auth_values(cleaned), [])
                self.assertNotIn(spelling, cleaned)

    def test_clean_leaves_the_response_authorization_rule_to_the_caller(self):
        """`_clean`'s default drop set is the hop-by-hop one; only the
        upstream direction adds the credential rule, because a response
        carries no client credential to strip."""
        self.assertNotIn("authorization", terminal_proxy.HOP_BY_HOP)
        self.assertIn("authorization", terminal_proxy.CLIENT_DROPPED)


class TestUpstreamUrlMapping(unittest.TestCase):
    class _Req:
        def __init__(self, path, query=""):
            self.match_info = {"path": path}
            self.query_string = query
            self.headers = CIMultiDict()

    def test_the_prefix_is_stripped(self):
        self.assertEqual(
            terminal_proxy._upstream_url(self._Req("ws")),
            f"{terminal_proxy.TTYD_BASE}/ws",
        )

    def test_the_query_string_survives(self):
        self.assertEqual(
            terminal_proxy._upstream_url(self._Req("token", "a=1&b=2")),
            f"{terminal_proxy.TTYD_BASE}/token?a=1&b=2",
        )


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# The websocket bridge, against a real ttyd-shaped server.
#
# The bridge is what the Terminal tab IS, and it had no test at all: every
# invariant below (frames crossing both ways, the credential reaching ttyd
# and the client's not, a failure arriving with its reason) was enforced by
# reading the file. A hand-rolled fake of a websocket would only prove the
# fake matches the code that mocked it, so this stands up an aiohttp server
# speaking ttyd's handshake and points the proxy at it.
# ---------------------------------------------------------------------------

import asyncio  # noqa: E402
import contextlib  # noqa: E402

import aiohttp  # noqa: E402
from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402


class _FakeTtyd:
    """The half of ttyd the proxy talks to: a `tty`-subprotocol websocket."""

    def __init__(self, mode: str = "echo"):
        self.mode = mode
        self.seen_headers: CIMultiDict | None = None
        self.app = web.Application()
        self.app.router.add_route("*", "/{path:.*}", self._handle)

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        self.seen_headers = CIMultiDict(request.headers)
        if request.headers.get("Upgrade", "").lower() != "websocket":
            return web.Response(text="ttyd bundle")
        ws = web.WebSocketResponse(protocols=("tty",))
        await ws.prepare(request)
        if self.mode == "close_at_once":
            await ws.close()
            return ws
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                if self.mode == "abort_on_first_frame":
                    # Kill the TCP connection without a close frame — what a
                    # ttyd whose process died looks like from this side.
                    request.transport.abort()
                    return ws
                await ws.send_str(f"ttyd saw {msg.data}")
        return ws


class _Bridge:
    """The panel's /terminal routes, pointed at a _FakeTtyd."""

    def __init__(self, mode: str = "echo"):
        self.ttyd = _FakeTtyd(mode)

    async def __aenter__(self):
        self.ttyd_server = TestServer(self.ttyd.app)
        await self.ttyd_server.start_server()
        self._saved_base = terminal_proxy.TTYD_BASE
        terminal_proxy.TTYD_BASE = str(self.ttyd_server.make_url("")).rstrip("/")

        app = web.Application()
        terminal_proxy.setup(app)
        self.panel = TestServer(app)
        await self.panel.start_server()
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc):
        await self.session.close()
        await self.panel.close()
        await self.ttyd_server.close()
        terminal_proxy.TTYD_BASE = self._saved_base

    def url(self, path: str) -> str:
        return str(self.panel.make_url(path))


class _CapturedLoopErrors:
    """Collect anything asyncio reports as an unhandled task exception.

    "Task exception was never retrieved" is emitted at garbage-collection
    time through the loop's exception handler, not raised — so the only way
    to fail a test on it is to install a handler and look.
    """

    def __init__(self):
        self.errors: list[dict] = []

    def __enter__(self):
        self.loop = asyncio.get_event_loop()
        self._saved = self.loop.get_exception_handler()
        self.loop.set_exception_handler(
            lambda loop, context: self.errors.append(context)
        )
        return self

    def __exit__(self, *exc):
        self.loop.set_exception_handler(self._saved)


class TestTheWebsocketBridge(unittest.IsolatedAsyncioTestCase):
    async def test_frames_cross_in_both_directions(self):
        async with _Bridge() as bridge:
            async with bridge.session.ws_connect(
                bridge.url("/terminal/ws"), protocols=("tty",)
            ) as ws:
                await ws.send_str("hello")
                self.assertEqual((await ws.receive()).data, "ttyd saw hello")
                await ws.send_str("again")
                self.assertEqual((await ws.receive()).data, "ttyd saw again")

    async def test_ttyd_receives_the_proxys_credential(self):
        async with _Bridge() as bridge:
            async with bridge.session.ws_connect(
                bridge.url("/terminal/ws"), protocols=("tty",)
            ) as ws:
                await ws.send_str("x")
                await ws.receive()
            self.assertEqual(
                _auth_values(bridge.ttyd.seen_headers), [REAL],
                "the bridge must present ttyd the panel's own credential",
            )

    async def test_a_client_credential_never_reaches_ttyd_over_the_socket(self):
        """The same rule as the HTTP path — the websocket upgrade carries
        headers too, and it is the request that opens a shell."""
        async with _Bridge() as bridge:
            async with bridge.session.ws_connect(
                bridge.url("/terminal/ws"),
                protocols=("tty",),
                headers={"AUTHORIZATION": "Basic YXR0YWNrZXI6cHc="},
            ) as ws:
                await ws.send_str("x")
                await ws.receive()
            self.assertEqual(_auth_values(bridge.ttyd.seen_headers), [REAL])
            self.assertNotIn(
                "Basic YXR0YWNrZXI6cHc=", list(bridge.ttyd.seen_headers.values())
            )

    async def test_the_tty_subprotocol_is_negotiated(self):
        """ttyd's client refuses a socket that does not echo `tty` back."""
        async with _Bridge() as bridge:
            async with bridge.session.ws_connect(
                bridge.url("/terminal/ws"), protocols=("tty",)
            ) as ws:
                self.assertEqual(ws.protocol, "tty")

    async def test_upstream_closing_ends_the_client_socket(self):
        async with _Bridge("close_at_once") as bridge:
            async with bridge.session.ws_connect(
                bridge.url("/terminal/ws"), protocols=("tty",)
            ) as ws:
                msg = await asyncio.wait_for(ws.receive(), timeout=5)
                self.assertIn(
                    msg.type,
                    (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING,
                     aiohttp.WSMsgType.CLOSED),
                )

    async def test_an_aborted_upstream_leaves_no_unretrieved_exception(self):
        """ttyd's process dying takes the TCP connection with it."""
        with _CapturedLoopErrors() as captured:
            async with _Bridge("abort_on_first_frame") as bridge:
                with contextlib.suppress(Exception):
                    async with bridge.session.ws_connect(
                        bridge.url("/terminal/ws"), protocols=("tty",)
                    ) as ws:
                        await ws.send_str("boom")
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(ws.receive(), timeout=5)
                await asyncio.sleep(0.1)
        self.assertEqual(
            [c for c in captured.errors
             if "never retrieved" in str(c.get("message", ""))],
            [],
        )


class TestSettlingTheTwoPumps(unittest.IsolatedAsyncioTestCase):
    """`_settle` is the two things `asyncio.wait` does not do.

    Driven directly, because through a real socket the interesting case —
    one pump raising while the other is mid-send — is not something a test
    can schedule reliably, and the bug was never about the socket.
    """

    async def _race(self, winner, loser):
        tasks = [asyncio.create_task(winner()), asyncio.create_task(loser())]
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_COMPLETED)
        await terminal_proxy._settle(done, pending)
        return tasks

    async def test_a_failing_pump_raises_into_the_caller(self):
        """Without this the proxy logged nothing and the terminal just
        dropped: `except (ClientError, OSError)` cannot catch what never
        left the task."""
        async def dies():
            raise ConnectionResetError("upstream died mid-frame")

        async def waits():
            await asyncio.sleep(30)

        with self.assertRaises(ConnectionResetError):
            await self._race(dies, waits)

    async def test_the_losing_pump_is_finished_not_merely_asked(self):
        """A cancelled task can still be inside a send. If _settle returns
        while it runs, the caller closes the socket under it."""
        state = {"stopped": False}

        async def wins():
            return None

        async def lingers():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await asyncio.sleep(0.05)   # still writing a frame
                state["stopped"] = True
                raise

        tasks = await self._race(wins, lingers)
        self.assertTrue(
            state["stopped"],
            "_settle returned while the losing pump was still running",
        )
        self.assertTrue(all(t.done() for t in tasks))

    async def test_a_clean_close_raises_nothing(self):
        async def closes():
            return None

        async def waits():
            await asyncio.sleep(30)

        tasks = await self._race(closes, waits)
        self.assertTrue(all(t.done() for t in tasks))

    async def test_a_cancelled_winner_is_not_read_for_an_exception(self):
        """Task.exception() on a cancelled task raises CancelledError; the
        outer request being cancelled must not become a proxy error."""
        async def cancelled_immediately():
            await asyncio.sleep(30)

        task = asyncio.create_task(cancelled_immediately())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.wait({task})
        self.assertTrue(task.cancelled())
        await terminal_proxy._settle({task}, set())

    async def test_nothing_is_left_unretrieved(self):
        with _CapturedLoopErrors() as captured:
            async def dies():
                raise ConnectionResetError("boom")

            async def waits():
                await asyncio.sleep(30)

            with contextlib.suppress(ConnectionResetError):
                await self._race(dies, waits)
            await asyncio.sleep(0.05)
        self.assertEqual(
            [c for c in captured.errors
             if "never retrieved" in str(c.get("message", ""))],
            [],
        )

    async def test_the_losers_parting_error_does_not_mask_the_reason(self):
        """A pump cancelled mid-send can come back with an error of its own.

        The first fix awaited each losing task under
        `suppress(CancelledError)`, so a loser that raised anything else
        propagated from there — the proxy logged `BrokenPipeError: send
        failed` (incidental to the shutdown) while the winner's
        `ConnectionResetError` (the reason for it) went unread, and left the
        bare "Task exception was never retrieved" traceback behind. The bug
        this function exists to stop, one case narrower.
        """
        with _CapturedLoopErrors() as captured:
            async def winner():
                raise ConnectionResetError("ttyd hung up")

            async def loser():
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    raise BrokenPipeError("send failed on the way out") from None

            with self.assertRaises(ConnectionResetError) as caught:
                await self._race(winner, loser)
            self.assertIn("ttyd hung up", str(caught.exception))
            await asyncio.sleep(0.05)

        self.assertEqual(
            [c for c in captured.errors
             if "never retrieved" in str(c.get("message", ""))],
            [],
            "the loser's own failure must be retrieved too, not left for the "
            "garbage collector to print",
        )

    async def test_waiting_for_the_loser_never_raises_by_itself(self):
        """Whatever the losing pump does on its way out, _settle reaches the
        loop that decides what to report."""
        async def clean_winner():
            return None

        async def messy_loser():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                raise BrokenPipeError("noise") from None

        with self.assertRaises(BrokenPipeError):
            await self._race(clean_winner, messy_loser)
