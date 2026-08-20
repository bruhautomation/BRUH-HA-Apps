#!/usr/bin/env python3
"""BRight's speaker calibration: the click track, the correlation that finds
it, the profile store, and the wizard endpoints end-to-end.

The core case builds a synthetic "phone recording" — the reference track
embedded at a KNOWN offset inside noise — and asserts the estimator finds
that offset, so the math is measured against a truth it did not produce.
"""

import asyncio
import base64
import importlib.util
import io
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import numpy as np  # noqa: E402

from calibrate import correlate, reference  # noqa: E402
from stores import calibration  # noqa: E402


def wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    frames = (clipped * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return buffer.getvalue()


def synthetic_recording(lag_s: float, rate: int = 44100,
                        total_s: float = 16.0, noise: float = 0.01,
                        gain: float = 0.4) -> bytes:
    """The reference, as a room would have heard it: delayed, quieter,
    over a noise floor."""
    rng = np.random.default_rng(seed=7)
    total = int(total_s * rate)
    room = rng.normal(0.0, noise, total).astype(np.float32)
    ref = np.asarray(reference.render_samples(rate), dtype=np.float32) * gain
    start = int(lag_s * rate)
    end = min(total, start + len(ref))
    room[start:end] += ref[:end - start]
    return wav_bytes(room, rate)


class TestReference(unittest.TestCase):
    def test_clicks_are_irregular(self):
        gaps = [round(b - a, 2) for a, b in
                zip(reference.CLICK_TIMES_S, reference.CLICK_TIMES_S[1:])]
        self.assertGreater(len(set(gaps)), len(gaps) // 2,
                           "a (near-)regular click train correlates at "
                           "every multiple of its period")

    def test_wav_writes_and_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = reference.write_wav(Path(tmp) / "sub" / "cal.wav")
            with wave.open(str(path), "rb") as handle:
                self.assertEqual(1, handle.getnchannels())
                self.assertEqual(reference.SAMPLE_RATE, handle.getframerate())
                duration = handle.getnframes() / handle.getframerate()
            self.assertAlmostEqual(reference.DURATION_S, duration, places=2)

    def test_the_track_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = reference.write_wav(Path(tmp) / "a.wav").read_bytes()
            second = reference.write_wav(Path(tmp) / "b.wav").read_bytes()
        self.assertEqual(first, second)


class TestCorrelate(unittest.TestCase):
    def test_recovers_a_known_offset(self):
        for true_lag in (0.8, 2.345, 4.0):
            with self.subTest(lag=true_lag):
                estimate = correlate.estimate_offset(
                    synthetic_recording(true_lag))
                self.assertLess(abs(estimate["lag_s"] - true_lag), 0.02,
                                f"estimator answered {estimate['lag_s']}")
                self.assertGreater(estimate["confidence"],
                                   correlate.MIN_CONFIDENCE)

    def test_survives_a_quiet_recording(self):
        estimate = correlate.estimate_offset(
            synthetic_recording(2.0, gain=0.05, noise=0.02))
        self.assertLess(abs(estimate["lag_s"] - 2.0), 0.02)

    def test_noise_alone_reports_low_confidence(self):
        rng = np.random.default_rng(seed=11)
        recording = wav_bytes(rng.normal(0, 0.02, 44100 * 8).astype(np.float32),
                              44100)
        estimate = correlate.estimate_offset(recording)
        self.assertLess(estimate["confidence"], correlate.MIN_CONFIDENCE,
                        "a click-free recording must not look calibratable")

    def test_a_short_recording_is_refused(self):
        with self.assertRaises(ValueError):
            correlate.estimate_offset(wav_bytes(np.zeros(1000), 44100))

    def test_silence_is_refused(self):
        with self.assertRaises(ValueError):
            correlate.estimate_offset(wav_bytes(np.zeros(44100 * 4), 44100))


class TestCalibrationStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._dir = calibration.CALIBRATION_DIR
        calibration.CALIBRATION_DIR = Path(self.tmp.name)

    def tearDown(self):
        calibration.CALIBRATION_DIR = self._dir
        self.tmp.cleanup()

    def test_median_and_spread(self):
        for offset in (2100.0, 2050.0, 2400.0):
            profile = calibration.add_run("media_player.living", offset,
                                          method="mic", confidence=9.0)
        self.assertEqual(2100.0, profile["offset_ms"])
        self.assertEqual(350.0, profile["spread_ms"])
        self.assertEqual(2100.0, profile["effective_offset_ms"])

    def test_adjust_rides_on_top_and_survives_remeasuring(self):
        calibration.add_run("media_player.living", 2000.0, method="mic")
        profile = calibration.set_adjust("media_player.living", -60.0)
        self.assertEqual(1940.0, profile["effective_offset_ms"])
        profile = calibration.add_run("media_player.living", 2000.0,
                                      method="mic")
        self.assertEqual(-60.0, profile["adjust_ms"],
                         "a new measurement must not discard the nudge")

    def test_best_entity_is_the_most_recently_measured(self):
        calibration.add_run("media_player.old", 1000.0, method="mic")
        calibration.add_run("media_player.new", 2000.0, method="mic")
        self.assertEqual("media_player.new", calibration.best_entity())

    def test_wire_data_never_names_a_file(self):
        """Entity ids come off the wire and become filenames; anything that
        is not shaped like an entity id is refused before a path exists."""
        for hostile in ("../../etc/passwd", "media_player/../x", "",
                        "media_player.", "a.b/c", "MEDIA_PLAYER.LOUD"):
            with self.subTest(entity=hostile):
                with self.assertRaises(ValueError):
                    calibration.add_run(hostile, 1000.0, method="mic")

    def test_runs_are_capped(self):
        for i in range(20):
            profile = calibration.add_run("media_player.x", 1000.0 + i,
                                          method="mic")
        self.assertEqual(calibration.MAX_RUNS, len(profile["runs"]))


def _load_server(data_dir: str, media_dir: str):
    os.environ["BRIGHT_STATE"] = data_dir
    os.environ["BRIGHT_MEDIA"] = media_dir
    path = os.path.join(PANEL_DIR, "server.py")
    spec = importlib.util.spec_from_file_location("bright_panel_cal", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestCalibrationEndpoints(unittest.TestCase):
    """The wizard's arithmetic through the real routes (loopback passes
    the LAN gate, which is itself under test elsewhere)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.server = _load_server(cls.tmp.name, cls.media.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def setUp(self):
        self._dir = calibration.CALIBRATION_DIR
        calibration.CALIBRATION_DIR = Path(self.tmp.name) / "calibration"
        # The spec-loaded server module holds its own reference to the
        # stores package — same module object, so the patch reaches it.

    def tearDown(self):
        calibration.CALIBRATION_DIR = self._dir

    def _call(self, method, path, payload=None):
        from aiohttp.test_utils import TestClient, TestServer

        async def scenario():
            client = TestClient(TestServer(self.server.build_app()))
            await client.start_server()
            try:
                response = await client.request(method, path, json=payload)
                return response.status, await response.json()
            finally:
                await client.close()

        return asyncio.run(scenario())

    def test_analyze_reports_the_planted_latency(self):
        true_lag_ms = 2000.0
        planted_offset_ms = 2087.0
        record_start = 1_000_000.0
        play_epoch = record_start + true_lag_ms - planted_offset_ms
        status, body = self._call("POST", "/api/calibrate/analyze", {
            "media_player": "media_player.living",
            "wav_b64": base64.b64encode(
                synthetic_recording(true_lag_ms / 1000.0)).decode(),
            "record_start_epoch_ms": record_start,
            "play_epoch_ms": play_epoch,
        })
        self.assertEqual(200, status, body)
        self.assertLess(abs(body["measured_offset_ms"] - planted_offset_ms), 25)
        self.assertEqual("mic", body["profile"]["runs"][-1]["method"])

    def test_analyze_refuses_noise(self):
        rng = np.random.default_rng(seed=3)
        noise = wav_bytes(rng.normal(0, 0.02, 44100 * 8).astype(np.float32),
                          44100)
        status, body = self._call("POST", "/api/calibrate/analyze", {
            "media_player": "media_player.living",
            "wav_b64": base64.b64encode(noise).decode(),
            "record_start_epoch_ms": 0,
            "play_epoch_ms": 0,
        })
        self.assertEqual(422, status)
        self.assertIn("clicks", body["error"])

    def test_analyze_refuses_an_implausible_offset(self):
        status, body = self._call("POST", "/api/calibrate/analyze", {
            "media_player": "media_player.living",
            "wav_b64": base64.b64encode(synthetic_recording(2.0)).decode(),
            "record_start_epoch_ms": 1_000_000.0,
            # The play command "happened" a minute after the sound: nonsense.
            "play_epoch_ms": 1_000_000.0 + 62_000.0,
        })
        self.assertEqual(422, status)
        self.assertIn("plausible", body["error"])

    def test_taps_take_the_median_and_refuse_chaos(self):
        play = 5_000_000.0
        offset = 2100.0
        clicks_ms = [c * 1000.0 for c in reference.CLICK_TIMES_S]
        taps = [play + offset + c for c in clicks_ms]
        status, body = self._call("POST", "/api/calibrate/taps", {
            "media_player": "media_player.den",
            "play_epoch_ms": play,
            "taps_epoch_ms": taps,
        })
        self.assertEqual(200, status, body)
        self.assertAlmostEqual(offset, body["measured_offset_ms"], delta=1)

        status, body = self._call("POST", "/api/calibrate/taps", {
            "media_player": "media_player.den",
            "play_epoch_ms": play,
            "taps_epoch_ms": [play, play + 900, play + 5000, play + 12000],
        })
        self.assertEqual(422, status)

    def test_taps_need_enough_samples(self):
        status, body = self._call("POST", "/api/calibrate/taps", {
            "media_player": "media_player.den",
            "play_epoch_ms": 0,
            "taps_epoch_ms": [100, 200],
        })
        self.assertEqual(422, status)

    def test_reference_endpoint_writes_the_track(self):
        status, body = self._call("POST", "/api/calibrate/reference")
        self.assertEqual(200, status)
        self.assertEqual(reference.describe()["click_times_s"],
                         body["click_times_s"])
        self.assertTrue((Path(self.media.name) / "bright" / "calibration.wav").is_file())

    def test_adjust_clamps_and_persists(self):
        status, body = self._call("POST", "/api/calibrate/adjust", {
            "media_player": "media_player.living",
            "adjust_ms": 99999,
        })
        self.assertEqual(200, status)
        self.assertEqual(2000.0, body["profile"]["adjust_ms"])


class TestReferenceStruct(unittest.TestCase):
    def test_render_matches_wav_payload(self):
        """write_wav is render_samples serialized — nothing more."""
        with tempfile.TemporaryDirectory() as tmp:
            path = reference.write_wav(Path(tmp) / "cal.wav", 8000)
            with wave.open(str(path), "rb") as handle:
                frames = handle.readframes(handle.getnframes())
        rendered = reference.render_samples(8000)
        first = struct.unpack("<h", frames[:2])[0]
        self.assertEqual(int(max(-1.0, min(1.0, rendered[0])) * 32767), first)


class TestNotBeingBrickedByOneBrokenStep(unittest.TestCase):
    """A show refuses to start without a calibration profile, which is
    right — and it means a speaker that will not play the click track takes
    the whole add-on with it, which is not a gate but a brick."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.server = _load_server(cls.tmp.name, cls.media.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def setUp(self):
        self._dir = calibration.CALIBRATION_DIR
        calibration.CALIBRATION_DIR = Path(self.tmp.name) / "manual-calibration"

    def tearDown(self):
        calibration.CALIBRATION_DIR = self._dir

    def _call(self, method, path, payload=None):
        from aiohttp.test_utils import TestClient, TestServer

        async def scenario():
            client = TestClient(TestServer(self.server.build_app()))
            await client.start_server()
            try:
                response = await client.request(method, path, json=payload)
                return response.status, await response.json()
            finally:
                await client.close()

        return asyncio.run(scenario())

    def test_a_typed_offset_becomes_a_usable_profile(self):
        status, body = self._call("POST", "/api/calibrate/manual", {
            "media_player": "media_player.wired", "offset_ms": 0})
        self.assertEqual(200, status, body)
        self.assertEqual(0, body["profile"]["effective_offset_ms"])
        # The one thing a show asks for before it will run.
        self.assertEqual(0, calibration.load(
            "media_player.wired")["effective_offset_ms"])

    def test_it_never_claims_to_have_been_measured(self):
        self._call("POST", "/api/calibrate/manual", {
            "media_player": "media_player.airplay", "offset_ms": 2100})
        profile = calibration.load("media_player.airplay")
        self.assertEqual("manual", profile["runs"][-1]["method"])

    def test_a_number_that_is_not_one_is_refused(self):
        for value in ("soon", None, float("nan"), 60000, -9000):
            with self.subTest(value=value):
                status, _ = self._call("POST", "/api/calibrate/manual", {
                    "media_player": "media_player.x", "offset_ms": value})
                self.assertEqual(400, status)


class TestTheWizardSaysWhichSilenceItWas(unittest.TestCase):
    """"Move the phone closer" is the wrong advice — and infuriating — when
    the speaker never made a sound. The position poll ran through the same
    seconds the phone was listening, so it knows which of the two happened."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.server = _load_server(cls.tmp.name, cls.media.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def tearDown(self):
        self.server._POSITION_CHECKS.clear()

    def _call(self, path, payload):
        from aiohttp.test_utils import TestClient, TestServer

        async def scenario():
            client = TestClient(TestServer(self.server.build_app()))
            await client.start_server()
            try:
                response = await client.request("POST", path, json=payload)
                return response.status, await response.json()
            finally:
                await client.close()

        return asyncio.run(scenario())

    def _noise(self):
        rng = np.random.default_rng(seed=11)
        return base64.b64encode(wav_bytes(
            rng.normal(0, 0.02, 44100 * 8).astype(np.float32), 44100)).decode()

    def test_a_speaker_that_never_played_is_told_apart_from_a_quiet_room(self):
        self.server._POSITION_CHECKS["media_player.kitchen"] = {
            "ever_playing": False, "states": ["idle"]}
        status, body = self._call("/api/calibrate/analyze", {
            "media_player": "media_player.kitchen",
            "wav_b64": self._noise(),
            "record_start_epoch_ms": 0, "play_epoch_ms": 0,
        })
        self.assertEqual(422, status)
        self.assertTrue(body["never_played"])
        self.assertIn("never started playing", body["error"])
        self.assertNotIn("closer", body["error"])

    def test_a_speaker_that_did_play_still_gets_the_room_advice(self):
        self.server._POSITION_CHECKS["media_player.kitchen"] = {
            "ever_playing": True, "states": ["playing"]}
        status, body = self._call("/api/calibrate/analyze", {
            "media_player": "media_player.kitchen",
            "wav_b64": self._noise(),
            "record_start_epoch_ms": 0, "play_epoch_ms": 0,
        })
        self.assertEqual(422, status)
        self.assertIn("closer", body["error"])

    def test_taps_at_silence_say_so_too(self):
        self.server._POSITION_CHECKS["media_player.den"] = {
            "ever_playing": False, "states": ["off"]}
        status, body = self._call("/api/calibrate/taps", {
            "media_player": "media_player.den",
            "play_epoch_ms": 1000.0,
            # Wildly scattered taps: the old message blamed the tapping.
            "taps_epoch_ms": [1100.0, 5000.0, 9000.0, 14000.0],
        })
        self.assertEqual(422, status)
        self.assertTrue(body["never_played"])


class TestTheClickTrackFile(unittest.TestCase):
    """Writing it, skipping it, and healing it.

    Rendering is half a million samples through a Python loop — 1.6s on a
    laptop with `struct.pack`, several times that on a Pi — and the wizard
    used to pay it inside every press of Play.
    """

    def test_the_two_packings_agree(self):
        """`array` replaced a per-sample `struct.pack`. Same bytes, or the
        analyzer is correlating against a track nobody plays."""
        samples = reference.render_samples(8000)
        old = b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
            for s in samples
        )
        self.assertEqual(old, reference.wav_bytes(8000)[44:])

    def test_the_expected_size_is_the_size_written(self):
        """`ensure` skips on length, so the arithmetic behind that length is
        measured against a real file rather than trusted."""
        for rate in (8000, 44100):
            with self.subTest(rate=rate):
                self.assertEqual(reference.expected_size(rate),
                                 len(reference.wav_bytes(rate)))

    def test_ensure_writes_once_and_then_leaves_it_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bright" / "calibration.wav"
            reference.ensure(path, 8000)
            self.assertTrue(path.is_file())
            stamped = path.stat().st_mtime_ns
            reference.ensure(path, 8000)
            self.assertEqual(stamped, path.stat().st_mtime_ns,
                             "re-rendered a file that was already the track")

    def test_ensure_heals_a_half_written_file(self):
        """A write cut off by a restart leaves a short file, and a short
        file is a click track the correlator will never find."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.wav"
            path.write_bytes(reference.wav_bytes(8000)[:9000])
            reference.ensure(path, 8000)
            self.assertEqual(reference.wav_bytes(8000), path.read_bytes())


class TestTheClickTrackCannotBeWritten(unittest.TestCase):
    """The failure that shipped, reproduced.

    /media belongs to root on a Home Assistant install and the panel runs as
    the `bright` user, so `mkdir("/media/bright")` raised PermissionError,
    aiohttp answered `500 Internal Server Error` with no body, and the wizard
    could only report `HTTP 500` — a number, about a folder it never named.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.media = tempfile.TemporaryDirectory()
        cls.server = _load_server(cls.tmp.name, cls.media.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        cls.media.cleanup()

    def _call(self, method, path, payload=None):
        from aiohttp.test_utils import TestClient, TestServer

        async def scenario():
            client = TestClient(TestServer(self.server.build_app()))
            await client.start_server()
            try:
                response = await client.request(method, path, json=payload)
                return response.status, await response.json()
            finally:
                await client.close()

        return asyncio.run(scenario())

    def _unwritable_track(self):
        """Put the click track somewhere it cannot be created.

        A blocking *file* where a parent folder should be, rather than a
        chmod: `mkdir` raises the same OSError either way, and this one is
        the same answer for root — which is who runs the tests in a
        container, and who would otherwise skip the only case that matters.
        """
        blocker = Path(self.tmp.name) / "not-a-folder"
        blocker.write_text("a file, where /media is a folder")
        original = self.server.REFERENCE_WAV
        self.server.REFERENCE_WAV = blocker / "bright" / "calibration.wav"
        self.addCleanup(setattr, self.server, "REFERENCE_WAV", original)

    def test_the_reference_route_says_which_folder(self):
        self._unwritable_track()
        status, body = self._call("POST", "/api/calibrate/reference")
        self.assertEqual(500, status)
        self.assertIn("bright", body["error"])
        self.assertIn("click track", body["error"])

    def test_play_says_the_same_thing_and_never_asks_for_playback(self):
        """A play command for a file that does not exist is how this reached
        Home Assistant, came back as ITS 500, and read as a panel crash."""
        self._unwritable_track()
        asked = []
        original = self.server.ha_client.play_media
        self.server.ha_client.play_media = lambda *a, **k: asked.append(a)
        self.addCleanup(setattr, self.server.ha_client, "play_media", original)

        status, body = self._call("POST", "/api/calibrate/play",
                                  {"media_player": "media_player.kitchen"})
        self.assertEqual(500, status)
        self.assertIn("click track", body["error"])
        self.assertEqual([], asked)

    def test_a_refusal_from_home_assistant_names_what_it_was_asked_for(self):
        original = self.server.ha_client.play_media
        self.server.ha_client.play_media = lambda *a, **k: {
            "error": "HTTP 500 from /services/media_player/play_media"}
        self.addCleanup(setattr, self.server.ha_client, "play_media", original)

        status, body = self._call("POST", "/api/calibrate/play",
                                  {"media_player": "media_player.kitchen"})
        self.assertEqual(502, status)
        self.assertIn("media_player.kitchen", body["error"])
        self.assertIn(self.server.REFERENCE_MEDIA_ID, body["error"])

    def test_play_writes_the_track_where_home_assistant_can_serve_it(self):
        original = self.server.ha_client.play_media
        self.server.ha_client.play_media = lambda *a, **k: []
        self.addCleanup(setattr, self.server.ha_client, "play_media", original)
        started = []
        original_start = self.server.jobs.start
        self.server.jobs.start = lambda name, fn: started.append(name) or {"id": name}
        self.addCleanup(setattr, self.server.jobs, "start", original_start)

        status, body = self._call("POST", "/api/calibrate/play",
                                  {"media_player": "media_player.kitchen"})
        self.assertEqual(200, status, body)
        self.assertIn("play_epoch_ms", body)
        track = Path(self.server.REFERENCE_WAV)
        self.assertTrue(track.is_file())
        self.assertEqual(reference.expected_size(), track.stat().st_size)
        # The media id is that file, spelled the way the local media source
        # spells it — the pair has to stay in step or nothing plays.
        self.assertTrue(self.server.REFERENCE_MEDIA_ID.endswith(
            "/".join(track.parts[-2:])))


if __name__ == "__main__":
    unittest.main()
