#!/usr/bin/env python3
"""BRigt's speaker calibration: the click track, the correlation that finds
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
PANEL_DIR = os.path.join(BASE_DIR, "brigt", "panel")
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

    def test_runs_are_capped(self):
        for i in range(20):
            profile = calibration.add_run("media_player.x", 1000.0 + i,
                                          method="mic")
        self.assertEqual(calibration.MAX_RUNS, len(profile["runs"]))


def _load_server(data_dir: str, media_dir: str):
    os.environ["BRIGT_STATE"] = data_dir
    os.environ["BRIGT_MEDIA"] = media_dir
    path = os.path.join(PANEL_DIR, "server.py")
    spec = importlib.util.spec_from_file_location("brigt_panel_cal", path)
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
        self.assertTrue((Path(self.media.name) / "brigt" / "calibration.wav").is_file())

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


if __name__ == "__main__":
    unittest.main()
