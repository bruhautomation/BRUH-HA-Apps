#!/usr/bin/env python3
"""BRigt's playback engine: the clock, drift handling, cue scheduling and
the metronome show's budget arithmetic."""

import asyncio
import base64
import os
import sys
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "brigt", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from lifx import packets  # noqa: E402
from playback import conductor  # noqa: E402
from playback.clock import ShowClock  # noqa: E402
from playback.drift import DriftEstimator  # noqa: E402


class TestShowClock(unittest.TestCase):
    def _clock(self):
        mono = [100.0]
        clock = ShowClock(monotonic=lambda: mono[0])
        return clock, mono

    def test_anchor_is_play_call_plus_speaker_latency(self):
        clock, mono = self._clock()
        clock.anchor(play_call_monotonic=100.0, output_latency_s=2.0)
        self.assertAlmostEqual(-2.0, clock.now(), places=6,
                               msg="sound hasn't started yet")
        mono[0] = 102.0
        self.assertAlmostEqual(0.0, clock.now(), places=6)
        mono[0] = 132.0
        self.assertAlmostEqual(30.0, clock.now(), places=6)

    def test_drift_slews_never_steps(self):
        clock, mono = self._clock()
        clock.anchor(100.0, 0.0)
        mono[0] = 110.0
        clock.add_drift(0.100)  # the room is 100ms ahead of us
        before = clock.now()
        mono[0] = 110.5  # half a second later: at most 4ms applied
        applied = clock.now() - before - 0.5
        self.assertLess(applied, 0.0045)
        self.assertGreater(applied, 0.003)
        mono[0] = 140.0  # long after: fully applied, and no more
        self.assertAlmostEqual(40.1, clock.now(), places=3)

    def test_negative_drift_slews_too(self):
        clock, mono = self._clock()
        clock.anchor(100.0, 0.0)
        mono[0] = 110.0
        clock.add_drift(-0.080)
        mono[0] = 130.0
        self.assertAlmostEqual(29.92, clock.now(), places=3)

    def test_sleep_needed(self):
        clock, mono = self._clock()
        clock.anchor(100.0, 1.0)
        mono[0] = 100.0
        self.assertAlmostEqual(3.5, clock.sleep_needed(2.5), places=6)
        mono[0] = 200.0
        self.assertEqual(0.0, clock.sleep_needed(2.5), "the past needs no sleep")


class TestDriftEstimator(unittest.TestCase):
    def test_never_acts_on_one_report(self):
        estimator = DriftEstimator()
        self.assertIsNone(estimator.report(10.5, 10.0))

    def test_consistent_error_becomes_a_correction(self):
        estimator = DriftEstimator()
        estimator.report(10.2, 10.0)
        correction = estimator.report(15.2, 15.0)
        self.assertIsNotNone(correction)
        self.assertGreater(correction, 0.1)

    def test_noise_inside_the_deadband_is_ignored(self):
        estimator = DriftEstimator()
        for show_time in (10.0, 15.0, 20.0):
            self.assertIsNone(estimator.report(show_time + 0.02, show_time))

    def test_a_wild_report_is_a_lie_not_a_drift(self):
        estimator = DriftEstimator()
        estimator.report(10.1, 10.0)
        self.assertIsNone(estimator.report(55.0, 15.0),
                          "a paused/stale player must not yank the show")


class _FakeEngine:
    """Records governed sends with the show-clock time they went out."""

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
        self.sent.append((serial, data))

    async def request(self, *args, **kwargs):
        return None  # no snapshot available — restore becomes a no-op


class TestCueScheduling(unittest.TestCase):
    """The loop, run for real over a tiny timeline: order and lead
    subtraction are what matter; absolute timing gets a generous window
    because CI machines wheeze."""

    def test_cues_fire_in_send_order_with_leads(self):
        async def scenario():
            import time as _time
            engine = _FakeEngine()
            run = conductor.Conductor.__new__(conductor.Conductor)
            run.engine = engine
            run.clock = ShowClock()
            run._snapshot = {}
            run.state = {}
            run._update_state = lambda **kw: None
            run._write_state = lambda **kw: None
            run._restore_snapshot = _noop

            pulse = packets.set_waveform(
                transient=True, hue=0, saturation=0, brightness=65535,
                kelvin=3500, period_ms=100, cycles=2.0,
                target=bytes(6), source=engine.source)
            cues = [
                {"t": 0.16, "ch": "lifx", "serial": "aa" * 6, "lead_ms": 100,
                 "payload_b64": base64.b64encode(pulse).decode()},
                {"t": 0.10, "ch": "lifx", "serial": "bb" * 6, "lead_ms": 0,
                 "payload_b64": base64.b64encode(pulse).decode()},
            ]
            run.clock.anchor(_time.monotonic(), 0.0)
            stamps = []
            original = engine.send_governed

            async def stamped(serial, data, addr):
                stamps.append((serial, run.clock.now()))
                await original(serial, data, addr)

            engine.send_governed = stamped
            await run._run(sorted(cues, key=run._send_time), duration_s=0.2)
            return stamps

        stamps = asyncio.run(scenario())
        self.assertEqual(["aa" * 6, "bb" * 6], [s for s, _ in stamps],
                         "the 0.16s cue leads by 100ms so it sends FIRST")
        self.assertLess(abs(stamps[0][1] - 0.06), 0.05)
        self.assertLess(abs(stamps[1][1] - 0.10), 0.05)

    def test_sequence_is_stamped_per_send(self):
        async def scenario():
            import time as _time
            engine = _FakeEngine()
            run = conductor.Conductor.__new__(conductor.Conductor)
            run.engine = engine
            run.clock = ShowClock()
            run._snapshot = {}
            run._update_state = lambda **kw: None
            run._write_state = lambda **kw: None
            run._restore_snapshot = _noop
            packet = packets.set_color(1, 2, 3, 3500, 100,
                                       target=bytes(6), source=engine.source)
            cue = {"t": 0.0, "ch": "lifx", "serial": "cc" * 6, "lead_ms": 0,
                   "resend": True,
                   "payload_b64": base64.b64encode(packet).decode()}
            run.clock.anchor(_time.monotonic(), 0.0)
            await run._run([cue], duration_s=0.05)
            return engine.sent

        sent = asyncio.run(scenario())
        self.assertEqual(2, len(sent), "resend cues go out twice")
        sequences = [packets.parse_header(data)["sequence"]
                     for _, data in sent]
        self.assertNotEqual(sequences[0], sequences[1],
                            "each send needs its own sequence number")


async def _noop():
    return None


class TestMetronomeShow(unittest.TestCase):
    ANALYSIS = {
        "beats": [round(0.5 * i, 2) for i in range(1, 241)],  # 120 BPM, 2min
        "tags": {"title": "Test Track", "duration": 121.0},
        "file": "/media/music/test.mp3",
    }

    DEVICES = {
        "d073d5000001": {"serial": "d073d5000001", "ip": "10.0.0.7",
                         "rtt": {"p50_ms": 6.0}},
        "d073d5000002": {"serial": "d073d5000002", "ip": "10.0.0.8"},
    }

    def test_budget_stays_far_under_the_ceiling(self):
        cues = conductor.metronome_cues(self.ANALYSIS, self.DEVICES, source=1)
        self.assertTrue(cues)
        self.assertLess(conductor.peak_rate_per_device(cues), 20.0)

    def test_pulses_ride_waveforms_not_per_beat_packets(self):
        cues = conductor.metronome_cues(self.ANALYSIS, self.DEVICES, source=1)
        per_device = [c for c in cues if c["serial"] == "d073d5000001"]
        beats = len(self.ANALYSIS["beats"])
        self.assertLess(len(per_device), beats / 4,
                        "the bulb runs the beats; the network must not")
        pulse = next(c for c in per_device if c["desc"].startswith("beat"))
        payload = base64.b64decode(pulse["payload_b64"])
        header = packets.parse_header(payload)
        self.assertEqual(packets.SET_WAVEFORM, header["type"])

    def test_leads_come_from_measured_rtt(self):
        cues = conductor.metronome_cues(self.ANALYSIS, self.DEVICES, source=1)
        measured = next(c for c in cues if c["serial"] == "d073d5000001")
        self.assertEqual(3.0, measured["lead_ms"], "half the p50 RTT")

    def test_media_content_id_stays_inside_media(self):
        self.assertEqual(
            "media-source://media_source/local/music/test.mp3",
            conductor.media_content_id_for(self.ANALYSIS))
        outside = {"file": "/config/secrets.yaml"}
        self.assertIsNone(conductor.media_content_id_for(outside))


if __name__ == "__main__":
    unittest.main()
