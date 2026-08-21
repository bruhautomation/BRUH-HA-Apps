#!/usr/bin/env python3
"""Auto-sync by ear: the phone's recording, matched against the playing
track itself. Ground truth is synthesized — the "track" is built here, the
"recording" is a slice of it taken at a KNOWN offset, so the measurement
is graded against an answer it did not produce. The ffmpeg decode is the
one boundary mocked, same policy as the analyzer suite.
"""

import io
import os
import sys
import unittest
import unittest.mock as mock
import wave
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

import numpy as np  # noqa: E402

from analyzer import decode  # noqa: E402
from playback import autosync, clock  # noqa: E402

SR = decode.SAMPLE_RATE


def synth_track(seconds: float = 60.0, seed: int = 11) -> np.ndarray:
    """Music-shaped audio with IRREGULAR onsets, on purpose: a metronome
    correlates equally well at every beat, and a sync test that could
    lock onto the wrong beat proves only that beats repeat."""
    rng = np.random.default_rng(seed)
    audio = rng.normal(0.0, 0.004, int(seconds * SR)).astype(np.float32)
    t = 0.3
    while t < seconds - 0.3:
        length = int(0.08 * SR)
        start = int(t * SR)
        tone = np.sin(2 * np.pi * rng.uniform(120, 900)
                      * np.arange(length) / SR)
        burst = (tone * np.exp(-np.arange(length) / SR * 30.0)
                 * rng.uniform(0.4, 1.0))
        audio[start:start + length] += burst.astype(np.float32)
        t += rng.uniform(0.18, 0.6)
    return audio


def as_wav(samples: np.ndarray, rate: int = SR) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(
            (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


class TestMeasure(unittest.TestCase):
    TRACK = synth_track()

    def _measure(self, recording, expected_pos_s):
        def fake_window(path, start_s, duration_s, sample_rate=SR):
            lo = int(start_s * SR)
            hi = lo + int(duration_s * SR)
            return self.TRACK[lo:hi]

        with mock.patch.object(autosync.decode, "pcm_window", fake_window):
            return autosync.measure(recording, Path("/fake.mp3"),
                                    expected_pos_s)

    def _recording_at(self, true_pos_s, seconds=4.0, noise=0.01, seed=3):
        lo = int(true_pos_s * SR)
        slice_ = self.TRACK[lo:lo + int(seconds * SR)].copy()
        rng = np.random.default_rng(seed)
        slice_ += rng.normal(0.0, noise, len(slice_)).astype(np.float32)
        return as_wav(slice_)

    def test_an_in_tune_room_measures_near_zero(self):
        result = self._measure(self._recording_at(20.0), expected_pos_s=20.0)
        self.assertLess(abs(result["delta_s"]), 0.02, result)
        self.assertGreaterEqual(result["confidence"],
                                autosync.MIN_CONFIDENCE)

    def test_audio_ahead_of_the_clock_reads_positive(self):
        # The room really hears 20.3s while the clock claims 20.0 — the
        # lights are late, and the positive delta is what nudge() takes
        # to move them earlier. The sign IS the feature.
        result = self._measure(self._recording_at(20.3), expected_pos_s=20.0)
        self.assertAlmostEqual(0.3, result["delta_s"], delta=0.02)

    def test_audio_behind_the_clock_reads_negative(self):
        result = self._measure(self._recording_at(19.6), expected_pos_s=20.0)
        self.assertAlmostEqual(-0.4, result["delta_s"], delta=0.02)

    def test_near_the_track_start_the_clamp_keeps_the_answer_honest(self):
        # expected 1.0s: the search window cannot reach back past 0, and
        # the clamped start must be folded into the position arithmetic.
        result = self._measure(self._recording_at(1.4), expected_pos_s=1.0)
        self.assertAlmostEqual(0.4, result["delta_s"], delta=0.02)

    def test_silence_is_a_retry_not_a_measurement(self):
        silent = as_wav(np.zeros(SR * 4, dtype=np.float32))
        with self.assertRaises(ValueError) as caught:
            self._measure(silent, expected_pos_s=20.0)
        self.assertIn("silence", str(caught.exception))

    def test_noise_scores_below_the_confidence_floor(self):
        rng = np.random.default_rng(9)
        noise = as_wav(rng.normal(0.0, 0.2, SR * 4).astype(np.float32))
        result = self._measure(noise, expected_pos_s=20.0)
        self.assertLess(result["confidence"], autosync.MIN_CONFIDENCE)

    def test_a_too_short_recording_is_refused(self):
        with self.assertRaises(ValueError):
            self._measure(as_wav(np.ones(SR // 2, dtype=np.float32) * 0.1),
                          expected_pos_s=20.0)


class TestApplyingTheMeasurement(unittest.TestCase):
    """The clock side: small corrections slew, big ones step."""

    def test_a_step_lands_whole_and_at_once(self):
        fake_time = [100.0]
        c = clock.ShowClock(monotonic=lambda: fake_time[0])
        c.anchor(100.0, 0.0)
        fake_time[0] = 110.0
        c.step_drift(0.8)
        self.assertAlmostEqual(10.8, c.now(), places=6)
        # And it stays: no slew-back, no pending target.
        fake_time[0] = 111.0
        self.assertAlmostEqual(11.8, c.now(), places=6)

    def test_a_step_folds_in_any_slew_still_in_flight(self):
        fake_time = [100.0]
        c = clock.ShowClock(monotonic=lambda: fake_time[0])
        c.anchor(100.0, 0.0)
        c.add_drift(0.08)          # slewing toward +80ms...
        fake_time[0] = 105.0       # ...40ms of it applied so far
        c.step_drift(0.5)          # the step takes what WAS applied + 0.5
        applied = c.now() - 5.0
        self.assertAlmostEqual(0.54, applied, places=6)


if __name__ == "__main__":
    unittest.main()
