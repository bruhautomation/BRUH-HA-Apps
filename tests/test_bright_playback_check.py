#!/usr/bin/env python3
"""Why nothing is playing — the diagnosis, and the client it runs on.

`media_player.play_media` answers "accepted", never "playing". Home
Assistant resolves the media, signs a path, puts a host in front of it and
hands the result to a speaker that fetches it afterwards, on its own. Every
way that goes wrong is invisible from the service call, so BRight walks the
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
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
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

    An answer may be a callable taking the whole message, for the cases
    where the reply depends on what was asked — media-source discovery
    resolves the same command with several different ids and the point is
    precisely that only one of them works.
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
        if callable(answer):
            answer = answer(message)
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
        previous_url = os.environ.get("BRIGHT_HA_WS_URL")
        previous_token = ha_ws.SUPERVISOR_TOKEN
        os.environ["BRIGHT_HA_WS_URL"] = url
        ha_ws.SUPERVISOR_TOKEN = TOKEN
        try:
            return await coro_factory()
        finally:
            ha_ws.SUPERVISOR_TOKEN = previous_token
            if previous_url is None:
                os.environ.pop("BRIGHT_HA_WS_URL", None)
            else:
                os.environ["BRIGHT_HA_WS_URL"] = previous_url
            await fake.stop()

    return asyncio.run(scenario())


class TestTheWebSocketClient(unittest.TestCase):
    """Media sources are WebSocket-only, so this is the only way to ask
    Home Assistant the one question that matters: can you resolve this?"""

    def test_the_url_is_derived_from_the_rest_base(self):
        previous = os.environ.pop("BRIGHT_HA_WS_URL", None)
        try:
            self.assertEqual("ws://supervisor/core/websocket", ha_ws.ws_url())
        finally:
            if previous is not None:
                os.environ["BRIGHT_HA_WS_URL"] = previous

    def test_a_resolved_media_comes_back(self):
        fake = FakeHomeAssistant({"media_source/resolve_media": {
            "url": "/media/local/bright/calibration.wav?authSig=x",
            "mime_type": "audio/x-wav",
        }})
        answer = run_against(fake, lambda: ha_ws.resolve_media(
            "media-source://media_source/local/bright/calibration.wav"))
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
        answer = run_against(fake, ha_ws.browse_media)
        self.assertIn("auth", answer["error"].lower())

    def test_nothing_listening_is_an_error_not_a_traceback(self):
        async def scenario():
            previous = os.environ.get("BRIGHT_HA_WS_URL")
            token = ha_ws.SUPERVISOR_TOKEN
            # Port 1 on loopback: nothing has ever listened there.
            os.environ["BRIGHT_HA_WS_URL"] = "ws://127.0.0.1:1/websocket"
            ha_ws.SUPERVISOR_TOKEN = TOKEN
            try:
                return await ha_ws.command({"type": "media_source/browse_media"})
            finally:
                ha_ws.SUPERVISOR_TOKEN = token
                if previous is None:
                    os.environ.pop("BRIGHT_HA_WS_URL", None)
                else:
                    os.environ["BRIGHT_HA_WS_URL"] = previous

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
        # "reported", not "started": the device may well be making sound.
        # Claiming it never started is a claim this check cannot make.
        self.assertIn("never reported playing", step["detail"])
        self.assertIn("idle → off", step["detail"])
        self.assertIn("host step", step["fix"])

    def test_a_receiver_that_took_the_media_is_not_the_url_case(self):
        """The failure a real install hit: an Onkyo receiver, `command`
        accepted, state stuck on `on`, and advice about the URL that was
        already proven fine two steps above.

        A device holding our media has fetched it. Its state model simply
        has no word for `playing` — so the honest answer is "you may be
        hearing this right now, and what BRight cannot do is tell when it
        started", which is a different problem with a different fix.
        """
        step = self._wait([
            {"state": "on"},
            {"state": "on",
             "attributes": {"media_content_id": "http://ha/media/x.wav"}},
            {"state": "on",
             "attributes": {"media_content_id": "http://ha/media/x.wav"}},
            {"state": "on",
             "attributes": {"media_content_id": "http://ha/media/x.wav"}},
        ])
        self.assertIs(False, step["ok"])
        self.assertIn("took the media", step["fix"])
        self.assertIn("manual tap", step["fix"],
                      "there is a way to calibrate this speaker anyway")
        self.assertNotIn("host step", step["fix"],
                         "the URL is proven fine — it fetched it")

    def test_a_player_that_never_touched_the_media_is_pointed_elsewhere(self):
        step = self._wait([{"state": "on"}, {"state": "on"},
                           {"state": "on"}, {"state": "on"}])
        self.assertIn("never picked the media up", step["fix"])
        self.assertIn("Chromecast", step["fix"],
                      "name something known to work, so the next test "
                      "separates the file from the device")


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

    def test_a_refused_command_shows_core_reason_and_our_request(self):
        """Either half alone leaves a guess.

        Core's message names what it objected to; the payload is the only
        place to see WHICH of the id and the type it meant — and the
        `media` step above shows the URL Core RESOLVED, not the
        media-source id `play_media` is actually handed, so the failing
        request is otherwise invisible on the whole page.
        """
        ha_client.play_media = lambda *a, **kw: {
            "error": "HTTP 500 from /services/media_player/play_media: "
                     "Unsupported media type music"}
        report = self._check({"url": "/media/local/x.mp3",
                              "mime_type": "audio/mpeg"})
        command = next(s for s in report["steps"] if s["name"] == "command")
        self.assertIs(False, command["ok"])
        self.assertIn("Unsupported media type music", command["detail"])
        self.assertIn("media-source://media_source/local/x.mp3",
                      command["fix"], "what BRight actually sent")
        self.assertIn("media_content_type=music", command["fix"])

    def test_a_working_chain_reports_every_step(self):
        report = self._check({"url": "/media/local/x.mp3",
                              "mime_type": "audio/mpeg"})
        self.assertTrue(report["ok"], report)
        self.assertEqual(["file", "media", "host", "player", "command", "playing"],
                         [s["name"] for s in report["steps"]])
        self.assertEqual(1, len(self.played))

    def test_an_unresolvable_media_id_stops_the_walk_and_goes_looking(self):
        """The failure mode a hardcoded `local` produces on an install that
        set `media_dirs` — and the one Core answers with its own HTTP 500.

        The walk stops, and the step's fix reports what re-discovery found:
        naming the problem and then building the next id the same wrong way
        is a diagnosis that fixes nothing.
        """
        report = self._check({"error": "Unresolvable: Unknown source directory"})
        self.assertFalse(report["ok"])
        self.assertEqual(["file", "media"], [s["name"] for s in report["steps"]])
        self.assertTrue(report["fix"], "a failed resolve said nothing about "
                                       "what to do next")
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


class TestTheDiagnosticIsNotAFileReader(unittest.TestCase):
    """The check stats the file behind a media id, and the media id comes
    off the wire. CodeQL called that a path expression depending on a
    user-provided value, and it was right: it was joined onto /media
    directly, which is a traversal wearing a media id's clothes."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        import tempfile

        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        os.environ["BRIGHT_STATE"] = cls.tmp.name
        os.environ["BRIGHT_MEDIA"] = cls.media.name
        os.environ["BRIGHT_ENV_FILE"] = os.path.join(cls.tmp.name, "no-env")
        os.environ["BRIGHT_OPTIONS"] = os.path.join(cls.tmp.name, "no-options")
        spec = importlib.util.spec_from_file_location(
            "bright_panel_pbcheck", os.path.join(PANEL_DIR, "server.py"))
        cls.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def _check(self, media_id):
        from aiohttp.test_utils import TestClient, TestServer

        seen = {}
        original = playback_check.check

        async def spy(entity_id, content_id, *, path=None, **kwargs):
            seen["path"] = path
            return {"ok": True, "steps": [], "summary": ""}

        playback_check.check = spy
        try:
            async def scenario():
                client = TestClient(TestServer(self.server.build_app()))
                await client.start_server()
                try:
                    response = await client.request(
                        "POST", "/api/playback/check",
                        json={"media_player": "media_player.kitchen",
                              "media_content_id": media_id})
                    return response.status, await response.json()
                finally:
                    await client.close()

            status, body = asyncio.run(scenario())
        finally:
            playback_check.check = original
        return status, body, seen.get("path")

    def test_a_traversing_media_id_never_becomes_a_path(self):
        status, _, path = self._check(
            "media-source://media_source/local/../../../etc/passwd")
        self.assertEqual(200, status)
        self.assertIsNone(path, f"stat would have been called on {path}")

    def test_no_media_id_off_the_wire_becomes_a_path_at_all(self):
        """Not even an innocent one. The file step exists for the click
        track, whose path is ours; for anything else Home Assistant's own
        resolve step answers "is the file there" better than a stat does —
        and a media id is not always a local file to begin with."""
        status, _, path = self._check(
            "media-source://media_source/local/music/song.mp3")
        self.assertEqual(200, status)
        self.assertIsNone(path)

    def test_the_default_still_checks_the_click_track_itself(self):
        """The one path the check does stat is a module constant."""
        from aiohttp.test_utils import TestClient, TestServer

        seen = {}
        original = playback_check.check

        async def spy(entity_id, content_id, *, path=None, **kwargs):
            seen["path"] = path
            seen["id"] = content_id
            return {"ok": True, "steps": [], "summary": ""}

        playback_check.check = spy
        try:
            async def scenario():
                client = TestClient(TestServer(self.server.build_app()))
                await client.start_server()
                try:
                    response = await client.request(
                        "POST", "/api/playback/check",
                        json={"media_player": "media_player.kitchen"})
                    return response.status
                finally:
                    await client.close()

            status = asyncio.run(scenario())
        finally:
            playback_check.check = original
        self.assertEqual(200, status)
        self.assertEqual(self.server.REFERENCE_WAV, seen["path"])
        self.assertEqual(self.server.reference_media_id(), seen["id"])


if __name__ == "__main__":
    unittest.main()

