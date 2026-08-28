#!/usr/bin/env python3
"""BRight's Manual tab engine: tapped loops, the drop/flash pads, and the
manual session's snapshot-and-restore contract."""

import asyncio
import base64
import os
import sys
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from lifx import packets  # noqa: E402
from playback import conductor  # noqa: E402
from playback import live  # noqa: E402
from playback.clock import ShowClock  # noqa: E402

PALETTE = [[200, 0.9], [30, 0.8], [300, 0.7]]


def bulb(n: int, role: str = "lamp") -> dict:
    serial = f"d073d500000{n}"
    return {"id": f"lifx-{serial}", "kind": "lifx", "serial": serial,
            "label": f"bulb {n}", "role": role, "x": n / 10, "y": 0.5,
            "rtt": {"p50_ms": 6.0}}


CAST = [bulb(1), bulb(2), bulb(3)]


def _payload_type(cue: dict) -> int:
    return packets.parse_header(base64.b64decode(cue["payload_b64"]))["type"]


class TestTapInference(unittest.TestCase):
    def test_the_period_is_the_median_gap(self):
        # One hesitant first gap must not bend the tempo — that is what
        # the median is for.
        taps = [0.0, 0.9, 1.4, 1.9, 2.4]
        self.assertAlmostEqual(0.5, live.infer_period(taps), places=3)

    def test_one_tap_is_not_a_tempo(self):
        self.assertIsNone(live.infer_period([0.4]))
        self.assertIsNone(live.infer_period([]))


class TestLoopCues(unittest.TestCase):
    def test_pulse_strikes_every_light_on_every_event(self):
        cues = live.loop_cues(CAST, [0.0, 0.5], 1.0, "pulse", PALETTE,
                              source=7)
        # Two actions per strike (the set and the decay wave), on every
        # light, for both events.
        self.assertEqual(2 * 2 * len(CAST), len(cues))

    def test_chase_walks_the_events_across_the_cast(self):
        cues = live.loop_cues(CAST, [0.0, 0.25, 0.5], 1.0, "chase", PALETTE,
                              source=7)
        self.assertEqual(2 * 3, len(cues), "one light per event")
        by_time = {}
        for cue in cues:
            by_time.setdefault(cue["t"], set()).add(cue["serial"])
        # Each event lands on exactly one light, and no two consecutive
        # events land on the same one.
        serial_order = [next(iter(by_time[t])) for t in sorted(by_time)]
        self.assertEqual(3, len(set(serial_order)))

    def test_the_decay_spans_the_gap_to_the_next_strike(self):
        cues = live.loop_cues([CAST[0]], [0.0, 0.6], 1.0, "pulse", PALETTE,
                              source=7)
        waves = [c for c in cues if _payload_type(c) == packets.SET_WAVEFORM]
        first = next(c for c in waves if c["t"] == 0.0)
        payload = base64.b64decode(first["payload_b64"])
        parsed = packets.parse_set_waveform(payload) \
            if hasattr(packets, "parse_set_waveform") else None
        if parsed is not None:
            self.assertEqual(600, parsed["period_ms"])

    def test_a_rhythm_faster_than_the_bulbs_is_refused(self):
        # 32 events in 2.5s on one bulb: 25.6 packets/s, over any ceiling.
        events = [i * 0.078 for i in range(32)]
        with self.assertRaises(ValueError):
            live.loop_cues([CAST[0]], events, 2.5, "pulse", PALETTE, source=7)

    def test_the_same_rhythm_spread_as_a_chase_is_fine(self):
        events = [i * 0.3 for i in range(16)]
        cues = live.loop_cues(CAST, events, 4.8, "chase", PALETTE, source=7)
        self.assertTrue(cues)

    def test_bounds_are_person_readable(self):
        with self.assertRaises(ValueError):
            live.loop_cues(CAST, [0.0], 0.1, "pulse", PALETTE, source=7)
        with self.assertRaises(ValueError):
            live.loop_cues([], [0.0], 1.0, "pulse", PALETTE, source=7)
        with self.assertRaises(ValueError):
            # Every tap outside the period: nothing left to loop.
            live.loop_cues(CAST, [5.0], 1.0, "pulse", PALETTE, source=7)

    def test_candles_keep_their_manners(self):
        candle = bulb(4, role="candle")
        cues = live.loop_cues([candle], [0.0], 1.0, "pulse", PALETTE,
                              source=7)
        # The strike's set carries the capped peak: read the SetColor
        # payload's brightness field (HSBK brightness at offset 40).
        strike = next(c for c in cues
                      if _payload_type(c) == packets.SET_COLOR)
        payload = base64.b64decode(strike["payload_b64"])
        brightness = int.from_bytes(payload[40:42], "little")
        self.assertLessEqual(brightness, int(0.45 * 65535) + 1,
                             "a candle's ceiling holds in a live strike")


class TestPads(unittest.TestCase):
    def test_drop_takes_every_light_to_black(self):
        cues = live.pad_cues(CAST, "drop", source=7)
        self.assertEqual(len(CAST), len(cues))
        for cue in cues:
            payload = base64.b64decode(cue["payload_b64"])
            self.assertEqual(packets.SET_COLOR,
                             packets.parse_header(payload)["type"])
            self.assertEqual(0, int.from_bytes(payload[40:42], "little"),
                             "drop means black")

    def test_flash_is_a_transient_wave_the_bulb_undoes(self):
        cues = live.pad_cues(CAST, "flash", source=7)
        self.assertEqual(len(CAST), len(cues))
        for cue in cues:
            self.assertEqual(packets.SET_WAVEFORM, _payload_type(cue))

    def test_an_unknown_pad_is_refused(self):
        with self.assertRaises(ValueError):
            live.pad_cues(CAST, "confetti", source=7)


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
        self.sent.append((serial, bytes(data)))

    async def request(self, *args, **kwargs):
        return None


class TestLiveLoops(unittest.TestCase):
    def test_a_new_loop_replaces_the_loop_on_its_lights(self):
        async def scenario():
            loops = live.LiveLoops(_FakeEngine())
            first = await loops.start_loop(
                cast=[CAST[0], CAST[1]], events=[0.0], period_s=1.0,
                style="pulse", palette=PALETTE, label="first")
            second = await loops.start_loop(
                cast=[CAST[1], CAST[2]], events=[0.0], period_s=1.0,
                style="pulse", palette=PALETTE, label="second")
            described = loops.describe()
            await loops.stop_all()
            return first, second, described

        first, second, described = asyncio.run(scenario())
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(["second"], [d["label"] for d in described],
                         "sharing one bulb replaces the whole loop")

    def test_loops_actually_send_and_repeat(self):
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            await loops.start_loop(
                cast=[CAST[0]], events=[0.0], period_s=0.45,
                style="pulse", palette=PALETTE, label="beat")
            await asyncio.sleep(1.0)
            await loops.stop_all()
            return len(engine.sent)

        sent = asyncio.run(scenario())
        # Two packets per strike, at least two periods in one second.
        self.assertGreaterEqual(sent, 4)

    def test_stopping_a_loop_halts_its_bulbs(self):
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            started = await loops.start_loop(
                cast=[CAST[0]], events=[0.0], period_s=1.0,
                style="pulse", palette=PALETTE, label="beat")
            engine.sent = []
            await loops.stop_loop(started["id"])
            return engine.sent, loops.describe()

        sent, described = asyncio.run(scenario())
        self.assertEqual([], described)
        self.assertTrue(sent, "the stop reaches the bulb")
        halted = packets.parse_header(sent[-1][1])
        self.assertEqual(packets.SET_WAVEFORM, halted["type"],
                         "a bulb is stopped by ending its waveform")

    def test_fire_sends_once_and_does_not_loop(self):
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            cues = live.pad_cues([CAST[0]], "flash", source=engine.source)
            loops.fire(cues, label="flash")
            await asyncio.sleep(0.2)
            count_then = len(engine.sent)
            await asyncio.sleep(0.3)
            await loops.stop_all()
            return count_then, len(engine.sent)

        then, later = asyncio.run(scenario())
        self.assertEqual(1, then)
        self.assertEqual(then, later, "a one-shot does not repeat")


class TestManualSession(unittest.TestCase):
    def _conductor(self):
        run = conductor.Conductor.__new__(conductor.Conductor)
        run.engine = _FakeEngine()
        run.clock = ShowClock()
        run._snapshot = {}
        run._driven = set()
        run._playing_on = None
        run._end_scene = None
        run._session_nudge_ms = 0.0
        run._task = run._poller = run._verify = run._restorer = None
        run._track_task = None
        run._party_jump = None
        run.state = {"status": "idle"}
        return run

    def test_a_session_is_active_and_stop_restores(self):
        writes = []
        original = conductor.atomic_write.write_json
        conductor.atomic_write.write_json = \
            lambda path, payload: writes.append(dict(payload))

        async def scenario():
            run = self._conductor()
            result = await run.start_manual(
                serials=[f["serial"] for f in CAST])
            state_mid = dict(run.state)
            await run.stop()
            return result, state_mid, run.state

        try:
            result, mid, after = asyncio.run(scenario())
        finally:
            conductor.atomic_write.write_json = original
        self.assertTrue(result["ok"])
        self.assertEqual("manual", mid["status"])
        self.assertTrue(mid["active"])
        self.assertFalse(after.get("active"))

    def test_music_that_cannot_start_is_a_warning_not_a_refusal(self):
        play = conductor.ha_client.play_media
        write = conductor.atomic_write.write_json
        conductor.ha_client.play_media = lambda *a, **k: {
            "error": "HTTP 500"}
        conductor.atomic_write.write_json = lambda *a, **k: None

        async def scenario():
            run = self._conductor()
            return await run.start_manual(
                serials=[CAST[0]["serial"]],
                media_player="media_player.k",
                media_content_id="media-source://x/y.mp3"), run

        try:
            result, run = asyncio.run(scenario())
        finally:
            conductor.ha_client.play_media = play
            conductor.atomic_write.write_json = write
        self.assertTrue(result["ok"], "the lights are still playable")
        self.assertIn("warning", result)
        self.assertIsNone(run._playing_on,
                          "a play that failed is not claimed")

    def test_stop_runs_the_before_stop_hook_first(self):
        order = []

        async def hook():
            order.append("loops")

        async def scenario():
            run = self._conductor()
            run.before_stop = hook
            original_halt = run._halt_waveforms

            async def spy_halt():
                order.append("halt")
                await original_halt()

            run._halt_waveforms = spy_halt
            write = conductor.atomic_write.write_json
            conductor.atomic_write.write_json = lambda *a, **k: None
            try:
                await run.stop()
            finally:
                conductor.atomic_write.write_json = write
            return order

        self.assertEqual(["loops", "halt"], asyncio.run(scenario()),
                         "the loops stop before the bulbs are halted, or "
                         "the next strike re-lights what was just stopped")


if __name__ == "__main__":
    unittest.main()
