#!/usr/bin/env python3
"""Why nothing is playing — the diagnosis, and the client it runs on.

`media_player.play_media` answers "accepted", never "playing". Home
Assistant resolves the media, signs a path, puts a host in front of it and
hands the result to a speaker that fetches it afterwards, on its own. Every
way that goes wrong is invisible from the service call, so BRigt walks the
chain instead — and this measures the walk.

The WebSocket half runs against a real aiohttp server speaking Home
Assistant's actual handshake (auth_required → auth → auth_ok → id'd
results), because a hand-rolled fake of a protocol proves only that the fake
matches the code that mocked it.
"""

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "brigt", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import ha_client  # noqa: E402
import ha_ws  # noqa: E402
import playback_check  # noqa: E402

TOKEN = "test-supervisor-token"


class FakeHomeAssistant:
    """The WebSocket half of Core, as far as this client can tell.

    `answers` maps a command type to what to send back; `before` is anything
    to send first, which is how the "Core interleaves events with results"
    case gets tested rather than described.
    """

    def __init__(self, answers=None, *, auth_ok=True, before=None):
        self.answers = answers or {}
        self.auth_ok = auth_ok
        self.before = before or []
        self.seen = []
        self._server = None

    async def start(self) -> str:
        app = web.Application()
        app.router.add_get("/websocket", self._handle)
        self._server = TestServer(app)
        await self._server.start_server()
        return str(self._server.make_url("/websocket"))

    async def stop(self) -> None:
        if self._server is not None:
            await self._server.close()

    async def _handle(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "auth_required", "ha_version": "2026.8.0"})
        auth = json.loads(await ws.receive_str())
        if not self.auth_ok or auth.get("access_token") != TOKEN:
            await ws.send_json({"type": "auth_invalid",
                                "message": "Invalid access token"})
            await ws.close()
            return ws
        await ws.send_json({"type": "auth_ok", "ha_version": "2026.8.0"})
        message = json.loads(await ws.receive_str())
        self.seen.append(message)
        for extra in self.before:
            await ws.send_json(extra)
        answer = self.answers.get(message.get("type"))
        if answer is None:
            await ws.send_json({"id": message["id"], "type": "result",
                                "success": False,
                                "error": {"code": "unknown_command",
                                          "message": "no such command"}})
        else:
            await ws.send_json({"id": message["id"], "type": "result",
                                "success": True, "result": answer})
        await ws.close()
        return ws


def run_against(fake: FakeHomeAssistant, coro_factory):
    """Start the fake, point the client at it, run one call, tear down."""
    async def scenario():
        url = await fake.start()
        previous_url = os.environ.get("BRIGT_HA_WS_URL")
        previous_token = ha_ws.SUPERVISOR_TOKEN
        os.environ["BRIGT_HA_WS_URL"] = url
        ha_ws.SUPERVISOR_TOKEN = TOKEN
        try:
            return await coro_factory()
        finally:
            ha_ws.SUPERVISOR_TOKEN = previous_token
            if previous_url is None:
                os.environ.pop("BRIGT_HA_WS_URL", None)
            else:
                os.environ["BRIGT_HA_WS_URL"] = previous_url
            await fake.stop()

    return asyncio.run(scenario())


class TestTheWebSocketClient(unittest.TestCase):
    """Media sources are WebSocket-only, so this is the only way to ask
    Home Assistant the one question that matters: can you resolve this?"""

    def test_the_url_is_derived_from_the_rest_base(self):
        previous = os.environ.pop("BRIGT_HA_WS_URL", None)
        try:
            self.assertEqual("ws://supervisor/core/websocket", ha_ws.ws_url())
        finally:
            if previous is not None:
                os.environ["BRIGT_HA_WS_URL"] = previous

    def test_a_resolved_media_comes_back(self):
        fake = FakeHomeAssistant({"media_source/resolve_media": {
            "url": "/media/local/brigt/calibration.wav?authSig=x",
            "mime_type": "audio/x-wav",
        }})
        answer = run_against(fake, lambda: ha_ws.resolve_media(
            "media-source://media_source/local/brigt/calibration.wav"))
        self.assertEqual("audio/x-wav", answer["mime_type"])
        self.assertEqual("media_source/resolve_media", fake.seen[0]["type"])

    def test_events_before_the_answer_are_not_mistaken_for_it(self):
        """Core sends what it feels like; the id is what makes an answer
        ours."""
        fake = FakeHomeAssistant(
            {"media_source/resolve_media": {"url": "/media/x", "mime_type": "audio/mpeg"}},
            before=[{"type": "event", "id": 99, "event": {"a": 1}},
                    {"id": 99, "type": "result", "success": True, "result": "not ours"}])
        answer = run_against(fake, lambda: ha_ws.resolve_media("media-source://x"))
        self.assertEqual("audio/mpeg", answer["mime_type"])

    def test_a_refused_command_is_an_error_not_an_exception(self):
        fake = FakeHomeAssistant({})  # every command unknown
        answer = run_against(fake, lambda: ha_ws.resolve_media("media-source://x"))
        self.assertIn("no such command", answer["error"])

    def test_bad_auth_says_so(self):
        fake = FakeHomeAssistant({}, auth_ok=False)
        answer = run_against(fake, lambda: ha_ws.browse_media())
        self.assertIn("auth", answer["error"].lower())

    def test_nothing_listening_is_an_error_not_a_traceback(self):
        async def scenario():
            previous = os.environ.get("BRIGT_HA_WS_URL")
            token = ha_ws.SUPERVISOR_TOKEN
            # Port 1 on loopback: nothing has ever listened there.
            os.environ["BRIGT_HA_WS_URL"] = "ws://127.0.0.1:1/websocket"
            ha_ws.SUPERVISOR_TOKEN = TOKEN
            try:
                return await ha_ws.command({"type": "media_source/browse_media"})
            finally:
                ha_ws.SUPERVISOR_TOKEN = token
                if previous is None:
                    os.environ.pop("BRIGT_HA_WS_URL", None)
                else:
                    os.environ["BRIGT_HA_WS_URL"] = previous

        answer = asyncio.run(scenario())
        self.assertIn("error", answer)

    def test_no_token_asks_nothing(self):
        token = ha_ws.SUPERVISOR_TOKEN
        ha_ws.SUPERVISOR_TOKEN = ""
        try:
            answer = asyncio.run(ha_ws.command({"type": "whatever"}))
        finally:
            ha_ws.SUPERVISOR_TOKEN = token
        self.assertIn("SUPERVISOR_TOKEN", answer["error"])


class TestTheHostStep(unittest.TestCase):
    """The step that took research rather than reading.

    Core builds the speaker's URL with `get_url()`: `internal_url` when set,
    the machine's own IP otherwise. Chromecast and Google speakers resolve
    names through Google's public DNS, so a `.local` internal URL — which a
    great many installs have — is a name the speaker is told does not exist.
    Nothing plays and nothing errors.
    """

    def test_a_local_hostname_is_the_failure_it_looks_like(self):
        step = playback_check.base_url_step(
            {"internal_url": "http://homeassistant.local:8123"})
        self.assertIs(False, step["ok"])
        self.assertIn("8.8.8.8", step["fix"])
        self.assertIn("Internal URL", step["fix"])

    def test_an_ip_address_is_fine(self):
        step = playback_check.base_url_step(
            {"internal_url": "http://192.168.1.10:8123"})
        self.assertIs(True, step["ok"])

    def test_no_internal_url_is_fine_because_core_uses_its_own_ip(self):
        """An unset setting is the *good* case here, which is the opposite
        of how it reads."""
        step = playback_check.base_url_step({"internal_url": "", "external_url": ""})
        self.assertIs(True, step["ok"])
        self.assertIn("IP address", step["detail"])

    def test_a_real_hostname_warns_without_claiming_a_failure(self):
        step = playback_check.base_url_step(
            {"internal_url": "https://ha.example.com"})
        self.assertIsNone(step["ok"])
        self.assertTrue(step["fix"])

    def test_https_on_an_ip_warns_about_the_certificate(self):
        step = playback_check.base_url_step(
            {"internal_url": "https://192.168.1.10:8123"})
        self.assertIsNone(step["ok"])
        self.assertIn("certificate", step["fix"].lower())

    def test_a_config_we_could_not_read_is_not_a_failure(self):
        step = playback_check.base_url_step({"error": "HTTP 401 from /config"})
        self.assertIsNone(step["ok"])


class TestTheFileStep(unittest.TestCase):
    def test_a_missing_file_names_itself(self):
        step = playback_check.file_step(Path("/nowhere/at/all.wav"))
        self.assertIs(False, step["ok"])
        self.assertIn("/nowhere/at/all.wav", step["detail"])

    def test_a_short_file_is_caught_before_anyone_tries_to_play_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cal.wav"
            path.write_bytes(b"x" * 10)
            step = playback_check.file_step(path, expected_size=1000)
            self.assertIs(False, step["ok"])
            self.assertIn("expected 1000", step["detail"])


class TestWaitingForPlaying(unittest.TestCase):
    """The step that separates "Home Assistant accepted the command" from
    "the speaker is making sound"."""

    def _wait(self, states, wait_s=3.0):
        ticks = iter(range(0, 100))
        original = ha_client.get_state
        sequence = list(states)

        def fake_state(entity_id, **kwargs):
            return sequence.pop(0) if sequence else {"state": "idle"}

        ha_client.get_state = fake_state
        try:
            return asyncio.run(playback_check.wait_for_playing(
                "media_player.kitchen", wait_s=wait_s, poll_s=0,
                now=lambda: next(ticks)))
        finally:
            ha_client.get_state = original

    def test_a_player_that_gets_there_passes(self):
        step = self._wait([
            {"state": "idle"},
            {"state": "buffering"},
        ])
        self.assertIs(True, step["ok"])

    def test_the_title_is_reported_when_the_player_offers_one(self):
        step = self._wait([{"state": "playing",
                            "attributes": {"media_title": "calibration.wav"}}])
        self.assertIn("calibration.wav", step["detail"])

    def test_a_player_that_never_starts_says_what_it_did_instead(self):
        step = self._wait([{"state": "idle"}, {"state": "off"},
                           {"state": "off"}, {"state": "off"}])
        self.assertIs(False, step["ok"])
        self.assertIn("never started playing", step["detail"])
        self.assertIn("idle → off", step["detail"])
        self.assertIn("host step", step["fix"])


class TestTheWholeChain(unittest.TestCase):
    """`check` walks the links in order and stops at the one that broke —
    telling somebody their speaker never started is noise when the file was
    never there."""

    def setUp(self):
        self._state = ha_client.get_state
        self._config = ha_client.get_config
        self._play = ha_client.play_media
        self.played = []
        ha_client.get_config = lambda **kw: {"internal_url": "http://10.0.0.5:8123"}
        ha_client.get_state = lambda entity_id, **kw: {
            "state": "playing",
            "attributes": {"supported_features": 512 | 4,
                           "friendly_name": "Kitchen"},
        }
        ha_client.play_media = lambda *a, **kw: self.played.append(a) or []

    def tearDown(self):
        ha_client.get_state = self._state
        ha_client.get_config = self._config
        ha_client.play_media = self._play

    def _check(self, resolve_answer, **kwargs):
        original = ha_ws.resolve_media

        async def fake_resolve(media_content_id):
            return resolve_answer

        ha_ws.resolve_media = fake_resolve
        try:
            return asyncio.run(playback_check.check(
                "media_player.kitchen", "media-source://media_source/local/x.mp3",
                wait_s=1.0, **kwargs))
        finally:
            ha_ws.resolve_media = original

    def test_a_working_chain_reports_every_step(self):
        report = self._check({"url": "/media/local/x.mp3",
                              "mime_type": "audio/mpeg"})
        self.assertTrue(report["ok"], report)
        self.assertEqual(["file", "media", "host", "player", "command", "playing"],
                         [s["name"] for s in report["steps"]])
        self.assertEqual(1, len(self.played))

    def test_an_unresolvable_media_id_stops_the_walk_and_names_media_dirs(self):
        """The failure mode a hardcoded `local` produces on an install that
        set `media_dirs` — and the one Core answers with its own HTTP 500."""
        report = self._check({"error": "Unresolvable: Unknown source directory"})
        self.assertFalse(report["ok"])
        self.assertEqual(["file", "media"], [s["name"] for s in report["steps"]])
        self.assertIn("media_dirs", report["fix"])
        self.assertEqual([], self.played,
                         "asked a speaker to play something Core cannot find")

    def test_a_player_that_cannot_be_sent_media_is_caught_before_the_command(self):
        ha_client.get_state = lambda entity_id, **kw: {
            "state": "idle", "attributes": {"supported_features": 4}}
        report = self._check({"url": "/media/local/x.mp3", "mime_type": "audio/mpeg"})
        self.assertFalse(report["ok"])
        self.assertIn("does not accept play_media", report["summary"])
        self.assertEqual([], self.played)

    def test_a_refused_command_is_reported_as_the_command_step(self):
        ha_client.play_media = lambda *a, **kw: {
            "error": "HTTP 500 from /services/media_player/play_media"}
        report = self._check({"url": "/media/local/x.mp3", "mime_type": "audio/mpeg"})
        self.assertFalse(report["ok"])
        self.assertEqual("command", report["steps"][-1]["name"])

    def test_a_warning_does_not_become_a_failure(self):
        ha_client.get_config = lambda **kw: {
            "internal_url": "https://ha.example.com"}
        report = self._check({"url": "/media/local/x.mp3", "mime_type": "audio/mpeg"})
        self.assertTrue(report["ok"])
        self.assertTrue(report["fix"], "a warning with nothing to do is noise")


if __name__ == "__main__":
    unittest.main()
