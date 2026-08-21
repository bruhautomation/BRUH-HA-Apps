#!/usr/bin/env python3
"""Party mode: the playlist loop, per-track re-anchoring, next-track
preparation, and the add-on side of the file bridge."""

import asyncio
import base64
import importlib.util
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import ha_client  # noqa: E402
from stores import parties  # noqa: E402
from lifx import packets  # noqa: E402
from playback import conductor as conductor_mod  # noqa: E402
from stores import calibration  # noqa: E402


class _FakeEngine:
    def __init__(self):
        self.source = 0x42420001
        self.sent = []
        self.devices = {}
        self._sequence = 0

    async def start(self):
        pass

    def _addr(self, serial):
        return ("10.0.0.5", 56700)

    def _next_sequence(self):
        self._sequence = (self._sequence + 1) & 0xFF
        return self._sequence

    async def send_governed(self, serial, data, addr):
        self.sent.append(serial)

    async def request(self, *args, **kwargs):
        return None


def _tiny_show(name: str) -> dict:
    packet = packets.set_color(1, 2, 3, 3500, 50, target=bytes(6), source=1)
    return {
        "cues": [{"t": 0.0, "ch": "lifx", "serial": "aa" * 6, "lead_ms": 0,
                  "payload_b64": base64.b64encode(packet).decode()}],
        "title": name,
        "duration_s": 0.05,
        "media_content_id": f"media-source://media_source/local/{name}.mp3",
    }


class TestPartyLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._cal_dir = calibration.CALIBRATION_DIR
        calibration.CALIBRATION_DIR = Path(self.tmp.name)
        calibration.add_run("media_player.living", 100.0, method="mic")
        self._state = conductor_mod.STATE_FILE
        conductor_mod.STATE_FILE = Path(self.tmp.name) / "state.json"
        self._play = ha_client.play_media
        self.played = []

        def fake_play(entity, content_id, *a, **kw):
            self.played.append((entity, content_id))
            return []

        ha_client.play_media = fake_play

    def tearDown(self):
        calibration.CALIBRATION_DIR = self._cal_dir
        conductor_mod.STATE_FILE = self._state
        ha_client.play_media = self._play
        self.tmp.cleanup()

    def test_the_queue_plays_through_with_per_track_anchors(self):
        prepared = []

        async def scenario():
            run = conductor_mod.Conductor(_FakeEngine())
            result = await run.start_party(
                ["hash-one", "hash-two"],
                media_player="media_player.living",
                loader=_tiny_show,
                preparer=prepared.append)
            self.assertTrue(result["ok"], result)
            await asyncio.wait_for(run._task, 10)
            return run

        run = asyncio.run(scenario())
        self.assertEqual(2, len(self.played),
                         "each track gets its own play_media = its own anchor")
        self.assertEqual(["hash-two"], prepared,
                         "the NEXT track compiles while the current plays")
        self.assertEqual("idle", run.state["status"])

    def test_a_broken_track_does_not_end_the_night(self):
        def loader(hash_hex):
            if hash_hex == "bad":
                return None
            return _tiny_show(hash_hex)

        async def scenario():
            run = conductor_mod.Conductor(_FakeEngine())
            await run.start_party(["bad", "good"],
                                  media_player="media_player.living",
                                  loader=loader)
            await asyncio.wait_for(run._task, 10)

        asyncio.run(scenario())
        self.assertEqual(1, len(self.played))
        self.assertIn("good", self.played[0][1])

    def test_an_uncalibrated_player_is_refused(self):
        async def scenario():
            run = conductor_mod.Conductor(_FakeEngine())
            return await run.start_party(
                ["x"], media_player="media_player.never_measured",
                loader=_tiny_show)

        result = asyncio.run(scenario())
        self.assertFalse(result["ok"])
        self.assertIn("calibrated", result["error"])


def _load_bridge():
    path = os.path.join(BASE_DIR, "bright", "integrations", "ha-bridge.py")
    spec = importlib.util.spec_from_file_location("bright_ha_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestWhoJoinsInAndHowItEnds(unittest.TestCase):
    """A party may name the lights it uses and the scene it ends with —
    the two things that turn "run something" into "run my evening"."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._cal_dir = calibration.CALIBRATION_DIR
        calibration.CALIBRATION_DIR = Path(self.tmp.name)
        calibration.add_run("media_player.living", 100.0, method="mic")
        self._state = conductor_mod.STATE_FILE
        conductor_mod.STATE_FILE = Path(self.tmp.name) / "state.json"
        self._play = ha_client.play_media
        self._call = ha_client.call_service
        self.calls = []
        ha_client.play_media = lambda *a, **kw: []
        ha_client.call_service = lambda domain, service, data=None, **kw: (
            self.calls.append((domain, service, data)) or [])

    def tearDown(self):
        calibration.CALIBRATION_DIR = self._cal_dir
        conductor_mod.STATE_FILE = self._state
        ha_client.play_media = self._play
        ha_client.call_service = self._call
        self.tmp.cleanup()

    def test_only_the_named_lights_are_driven(self):
        cues = [
            {"t": 0.0, "ch": "lifx", "serial": "aa" * 6, "lead_ms": 0},
            {"t": 0.0, "ch": "lifx", "serial": "bb" * 6, "lead_ms": 0},
            {"t": 0.0, "ch": "ha", "service": "homeassistant.turn_on",
             "data": {"entity_id": "switch.laser"}, "lead_ms": 0},
        ]
        kept = conductor_mod.filter_cues(
            cues, {"lifx-" + "aa" * 6, "switch.laser"})
        self.assertEqual(2, len(kept))
        self.assertNotIn("bb" * 6, [c.get("serial") for c in kept])

    def test_no_restriction_means_every_light(self):
        cues = [{"t": 0.0, "ch": "lifx", "serial": "aa" * 6, "lead_ms": 0}]
        self.assertEqual(cues, conductor_mod.filter_cues(cues, None))
        self.assertEqual(cues, conductor_mod.filter_cues(cues, set()))

    def test_an_end_scene_is_called_instead_of_restoring(self):
        async def scenario():
            run = conductor_mod.Conductor(_FakeEngine())
            run._snapshot = {"aa" * 6: {"hue": 1, "saturation": 2,
                                        "brightness": 3, "kelvin": 3500}}
            run.set_end_scene("scene.good_night")
            await run.stop(restore=True)
            return run

        run = asyncio.run(scenario())
        self.assertIn(("scene", "turn_on", {"entity_id": "scene.good_night"}),
                      self.calls)
        self.assertEqual({}, run._snapshot,
                         "the snapshot was applied as well as the scene")

    def test_a_scene_that_fails_falls_back_to_restoring(self):
        """The room must never keep the party colours because a scene was
        deleted last week."""
        def boom(domain, service, data=None, **kw):
            raise RuntimeError("no such scene")

        ha_client.call_service = boom

        async def scenario():
            engine = _FakeEngine()
            run = conductor_mod.Conductor(engine)
            run._snapshot = {"aa" * 6: {"hue": 1, "saturation": 2,
                                        "brightness": 3, "kelvin": 3500}}
            run.set_end_scene("scene.gone")
            await run.stop(restore=True)
            return engine

        engine = asyncio.run(scenario())
        self.assertEqual(["aa" * 6], engine.sent,
                         "the lights were left where the show put them")

    def test_a_failing_scene_cannot_write_its_own_log_lines(self):
        """The scene id arrives on the wire and the exception text is
        whatever raised it — a newline in either is that caller writing
        log lines of its own (CodeQL called this one)."""
        def boom(domain, service, data=None, **kw):
            raise RuntimeError("no such scene\nWARNING all clear")

        ha_client.call_service = boom
        logged = []

        class _Catch(logging.Handler):
            def emit(self, record):
                logged.append(record.getMessage())

        handler = _Catch()
        conductor_mod.log.addHandler(handler)
        try:
            async def scenario():
                run = conductor_mod.Conductor(_FakeEngine())
                run.set_end_scene("scene.good\nnight")
                await run.stop(restore=True)

            asyncio.run(scenario())
        finally:
            conductor_mod.log.removeHandler(handler)

        self.assertTrue(logged, "the failure was not logged at all")
        for message in logged:
            self.assertNotIn("\n", message)

    def test_state_says_when_a_run_is_actually_in_progress(self):
        async def scenario():
            run = conductor_mod.Conductor(_FakeEngine())
            self.assertFalse(run.state["active"])
            result = await run.start_party(
                ["hash-one"], media_player="media_player.living",
                loader=_tiny_show, name="Saturday")
            self.assertTrue(result["ok"], result)
            self.assertTrue(run.state["active"])
            self.assertEqual("Saturday", run.state["party"])
            await asyncio.wait_for(run._task, 10)
            return run

        run = asyncio.run(scenario())
        self.assertFalse(run.state["active"],
                         "an ended party would still show a Stop button")


class TestBridge(unittest.TestCase):
    def setUp(self):
        self.bridge = _load_bridge()
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.bridge.SHARED = base
        self.bridge.REQ_DIR = base / "requests"
        self.bridge.RES_DIR = base / "responses"
        self.bridge.RES_DIR.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_kinds_forward_to_the_panel(self):
        calls = []

        def fake_post(path, payload):
            calls.append((path, payload))
            return {"ok": True, "queue": 3}

        self.bridge._panel_post = fake_post
        result = asyncio.run(self.bridge.handle(
            {"kind": "party_mode", "payload": {"vibe": "rave"}}))
        self.assertEqual({"ok": True, "queue": 3}, result)
        self.assertEqual([("/api/show/party_mode", {"vibe": "rave"})], calls)

    def test_the_panels_reason_survives_the_trip(self):
        """The panel's body carries the sentence and its status carries a
        number. Reporting the number is how "no analyzed tracks in
        /media/music — run the Library tab first" reached an automation as
        "panel answered HTTP 409"."""
        import io
        import urllib.error

        def refusing_post(path, payload):
            raise urllib.error.HTTPError(
                "http://127.0.0.1/api/show/party_mode", 409, "Conflict", {},
                io.BytesIO(json.dumps({
                    "error": "no analyzed tracks in /media/music — run the "
                             "Library tab first"}).encode()))

        self.bridge._panel_post = refusing_post
        result = asyncio.run(self.bridge.handle({"kind": "party_mode"}))
        self.assertFalse(result["ok"])
        self.assertIn("Library tab", result["error"])
        self.assertNotIn("409", result["error"])

    def test_a_refusal_with_no_reason_still_says_something(self):
        import io
        import urllib.error

        def refusing_post(path, payload):
            raise urllib.error.HTTPError(
                "http://127.0.0.1/api/show/stop_show", 500, "Server Error", {},
                io.BytesIO(b"not json at all"))

        self.bridge._panel_post = refusing_post
        result = asyncio.run(self.bridge.handle({"kind": "stop_show"}))
        self.assertFalse(result["ok"])
        self.assertIn("500", result["error"])

    def test_a_missing_route_no_longer_claims_to_be_a_skeleton_build(self):
        """That wording was true in 0.1.0 and has been a lie since 0.5."""
        import io
        import urllib.error

        def missing(path, payload):
            raise urllib.error.HTTPError(
                "http://127.0.0.1/api/show/start_show", 404, "Not Found", {},
                io.BytesIO(b"{}"))

        self.bridge._panel_post = missing
        result = asyncio.run(self.bridge.handle({"kind": "start_show"}))
        self.assertNotIn("skeleton", result["error"])
        self.assertIn("up to date", result["error"])

    def test_unknown_kinds_answer_instead_of_hanging(self):
        result = asyncio.run(self.bridge.handle({"kind": "format_disk"}))
        self.assertFalse(result["ok"])
        self.assertIn("unknown", result["error"])

    def test_response_files_land_under_the_request_id(self):
        self.bridge._write_response("abc123", {"ok": True})
        payload = json.loads((self.bridge.RES_DIR / "abc123.json").read_text())
        self.assertTrue(payload["ok"])


if __name__ == "__main__":
    unittest.main()


class TestPartyPlaylists(unittest.TestCase):
    """A playlist is a choice of exact songs in an exact order."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._file = parties.PARTIES_FILE
        parties.PARTIES_FILE = Path(self.tmp.name) / "parties.json"

    def tearDown(self):
        parties.PARTIES_FILE = self._file
        self.tmp.cleanup()

    def test_a_playlist_round_trips_in_order(self):
        first, second = "ab" * 20, "cd" * 20
        parties.save({"name": "Vinyl Night", "tracks": [second, first]})
        saved = parties.get("vinyl night")
        self.assertEqual([second, first], saved["tracks"],
                         "the order given is the order kept — that is what "
                         "makes it a playlist rather than a filter")

    def test_junk_in_the_tracks_list_is_dropped_not_fatal(self):
        parties.save({"name": "Messy", "tracks": [
            "ab" * 20, "not-a-hash", 42, {"hash": "cd" * 20}]})
        self.assertEqual(["ab" * 20], parties.get("Messy")["tracks"])

    def test_the_same_song_twice_is_a_choice_not_a_mistake(self):
        parties.save({"name": "Encore", "tracks": ["ab" * 20, "ab" * 20]})
        self.assertEqual(2, len(parties.get("Encore")["tracks"]))

    def test_a_party_without_a_playlist_has_an_empty_list(self):
        parties.save({"name": "Folder Night"})
        self.assertEqual([], parties.get("Folder Night")["tracks"])
