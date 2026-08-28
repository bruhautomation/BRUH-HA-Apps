#!/usr/bin/env python3
"""BRight's Manual tab engine: played loops, the drop/flash pads, the
drop-stale dispatch that keeps a stall from backing up the session, and
the manual session's snapshot-and-restore contract."""

import asyncio
import base64
import os
import struct
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


def _body(cue: dict) -> bytes:
    return base64.b64decode(cue["payload_b64"])[packets.HEADER_SIZE:]


def _set_colour(cue: dict) -> tuple[int, int, int]:
    """hue, saturation, brightness out of a SetColor (a reserved byte,
    then four u16s)."""
    return struct.unpack_from("<HHH", _body(cue), 1)


def _wave_colour(cue: dict) -> tuple[int, int, int]:
    """The same three out of a SetWaveform (reserved, transient, then the
    HSBK)."""
    return struct.unpack_from("<HHH", _body(cue), 2)


def _wave_period_ms(cue: dict) -> int:
    return struct.unpack_from("<I", _body(cue), 10)[0]


def _strike(at: float, *fixtures: dict) -> dict:
    return {"t": at, "ids": [f["id"] for f in fixtures]}


class TestTapInference(unittest.TestCase):
    def test_the_period_is_the_median_gap(self):
        # One hesitant first gap must not bend the tempo — that is what
        # the median is for.
        taps = [0.0, 0.9, 1.4, 1.9, 2.4]
        self.assertAlmostEqual(0.5, live.infer_period(taps), places=3)

    def test_one_tap_is_not_a_tempo(self):
        self.assertIsNone(live.infer_period([0.4]))
        self.assertIsNone(live.infer_period([]))


class TestSnapPeriod(unittest.TestCase):
    def test_a_press_near_the_beat_is_the_beat(self):
        # Four taps half a second apart; LOOP pressed 42ms late on what
        # was plainly meant to be the fifth beat.
        taps = [0.0, 0.5, 1.0, 1.5]
        self.assertAlmostEqual(2.0, live.snap_period(taps, 2.042), places=3)

    def test_a_press_nowhere_near_the_beat_is_taken_literally(self):
        # 30% of a beat out is not a missed downbeat, it is a loop that
        # is meant to be that long — guessing here would fight the
        # person rather than help them.
        taps = [0.0, 0.5, 1.0, 1.5]
        self.assertAlmostEqual(2.15, live.snap_period(taps, 2.15), places=3)

    def test_the_snap_reaches_past_one_beat(self):
        taps = [0.0, 0.5, 1.0]
        self.assertAlmostEqual(4.0, live.snap_period(taps, 3.96), places=3)

    def test_too_few_taps_carry_no_grid(self):
        self.assertAlmostEqual(1.7, live.snap_period([0.0], 1.7), places=3)
        self.assertAlmostEqual(1.7, live.snap_period([], 1.7), places=3)

    def test_a_press_before_the_first_beat_is_not_snapped_to_zero(self):
        # k rounds to 0 for a very short press, and a zero-length loop
        # is not a loop — the literal value goes on to fail the period
        # bounds with a sentence about the period.
        taps = [0.0, 1.0, 2.0]
        self.assertAlmostEqual(0.2, live.snap_period(taps, 0.2), places=3)


class TestLoopCues(unittest.TestCase):
    def test_an_event_strikes_exactly_the_bulbs_it_names(self):
        events = [_strike(0.0, CAST[0]), _strike(0.25, CAST[1]),
                  _strike(0.5, CAST[2])]
        cues = live.loop_cues(CAST, events, 1.0, PALETTE, source=7)
        self.assertEqual(2 * 3, len(cues), "two packets per strike")
        by_time = {}
        for cue in cues:
            by_time.setdefault(cue["t"], set()).add(cue["serial"])
        self.assertEqual({0.0: {CAST[0]["serial"]},
                          0.25: {CAST[1]["serial"]},
                          0.5: {CAST[2]["serial"]}}, by_time,
                         "the melody path lands where it was played")

    def test_two_bulbs_in_one_event_are_one_hit(self):
        cues = live.loop_cues(CAST, [_strike(0.0, CAST[0], CAST[2])], 1.0,
                              PALETTE, source=7)
        self.assertEqual({CAST[0]["serial"], CAST[2]["serial"]},
                         {c["serial"] for c in cues})
        self.assertNotIn(CAST[1]["serial"], {c["serial"] for c in cues},
                         "a bulb nobody tapped is left alone")

    def test_a_bulb_keeps_its_colour_across_its_strikes(self):
        events = [_strike(0.0, CAST[1]), _strike(0.5, CAST[1])]
        cues = live.loop_cues(CAST, events, 1.0, PALETTE, source=7)
        sets = [_set_colour(c) for c in cues
                if _payload_type(c) == packets.SET_COLOR]
        self.assertEqual(2, len(sets))
        self.assertEqual(sets[0][:2], sets[1][:2],
                         "hue and saturation come from the BULB's place "
                         "in the cast, not from which strike it was")
        # And a different bulb gets a different entry in the palette.
        other = live.loop_cues(CAST, [_strike(0.0, CAST[2])], 1.0, PALETTE,
                               source=7)
        self.assertNotEqual(
            sets[0][:2],
            _set_colour(next(c for c in other
                             if _payload_type(c) == packets.SET_COLOR))[:2])

    def test_the_decay_spans_the_gap_to_that_bulbs_next_strike(self):
        # Bulb 1 on beats 1 and 3, bulb 2 on beat 2: bulb 1's first
        # decay must run the whole 0.5s to its OWN next strike, not stop
        # at 0.25s under somebody else's.
        events = [_strike(0.0, CAST[0]), _strike(0.25, CAST[1]),
                  _strike(0.5, CAST[0])]
        cues = live.loop_cues(CAST, events, 1.0, PALETTE, source=7)
        first = next(c for c in cues
                     if c["serial"] == CAST[0]["serial"] and c["t"] == 0.0
                     and _payload_type(c) == packets.SET_WAVEFORM)
        self.assertEqual(500, _wave_period_ms(first))

    def test_the_last_strike_decays_around_the_loop(self):
        events = [_strike(0.0, CAST[0]), _strike(0.6, CAST[0])]
        cues = live.loop_cues(CAST, events, 1.0, PALETTE, source=7)
        last = next(c for c in cues
                    if c["t"] == 0.6 and _payload_type(c) ==
                    packets.SET_WAVEFORM)
        self.assertEqual(400, _wave_period_ms(last),
                         "0.6 to 1.0 is the wrap back to the first strike")

    def test_an_unknown_id_is_skipped_not_refused(self):
        events = [_strike(0.0, CAST[0]),
                  {"t": 0.5, "ids": ["lifx-gone-off-the-map"]}]
        cues = live.loop_cues(CAST, events, 1.0, PALETTE, source=7)
        self.assertEqual({0.0}, {c["t"] for c in cues},
                         "the rest of the rhythm is still what was played")

    def test_a_rhythm_faster_than_the_bulbs_is_refused(self):
        # 32 strikes on ONE bulb in 2.5s: 25.6 packets/s, over any
        # ceiling.
        events = [_strike(i * 0.078, CAST[0]) for i in range(32)]
        with self.assertRaises(ValueError):
            live.loop_cues(CAST, events, 2.5, PALETTE, source=7)

    def test_the_same_rhythm_spread_across_bulbs_is_fine(self):
        # The ceiling is per bulb, so the same 32 hits dealt round-robin
        # cost each of three bulbs a third of the rate.
        events = [_strike(i * 0.078, CAST[i % 3]) for i in range(32)]
        self.assertTrue(live.loop_cues(CAST, events, 2.5, PALETTE, source=7))

    def test_more_than_the_event_cap_is_refused(self):
        events = [_strike(i * 0.2, CAST[i % 3])
                  for i in range(live.MAX_EVENTS + 1)]
        with self.assertRaises(ValueError):
            live.loop_cues(CAST, events, 15.0, PALETTE, source=7)

    def test_bounds_are_person_readable(self):
        with self.assertRaises(ValueError):
            live.loop_cues(CAST, [_strike(0.0, CAST[0])], 0.1, PALETTE,
                           source=7)
        with self.assertRaises(ValueError):
            live.loop_cues([], [_strike(0.0, CAST[0])], 1.0, PALETTE,
                           source=7)
        with self.assertRaises(ValueError):
            # Every tap outside the period: nothing left to loop.
            live.loop_cues(CAST, [_strike(5.0, CAST[0])], 1.0, PALETTE,
                           source=7)
        with self.assertRaises(ValueError):
            # Taps that name no bulb at all.
            live.loop_cues(CAST, [{"t": 0.0, "ids": []}], 1.0, PALETTE,
                           source=7)

    def test_candles_keep_their_manners(self):
        candle = bulb(4, role="candle")
        cues = live.loop_cues([candle], [_strike(0.0, candle)], 1.0, PALETTE,
                              source=7)
        # The strike's set carries the capped peak, and so does the floor
        # the decay travels to.
        strike = next(c for c in cues
                      if _payload_type(c) == packets.SET_COLOR)
        self.assertLessEqual(_set_colour(strike)[2], int(0.45 * 65535) + 1,
                             "a candle's ceiling holds in a live strike")


class TestTapCues(unittest.TestCase):
    def test_a_tap_is_two_packets_a_set_then_a_decay(self):
        cues = live.tap_cues(CAST[0], 0, PALETTE, source=7)
        self.assertEqual(2, len(cues), "the cheapest thing the session sends")
        self.assertEqual([packets.SET_COLOR, packets.SET_WAVEFORM],
                         [_payload_type(c) for c in cues],
                         "the attack first, then the envelope the bulb runs")
        self.assertEqual([0.0, 0.0], [c["t"] for c in cues])

    def test_a_tap_decays_over_its_own_length(self):
        cues = live.tap_cues(CAST[0], 0, PALETTE, source=7)
        self.assertEqual(live.TAP_DECAY_MS, _wave_period_ms(cues[1]))

    def test_a_tapped_candle_keeps_its_ceiling(self):
        candle = bulb(4, role="candle")
        cues = live.tap_cues(candle, 0, PALETTE, source=7)
        self.assertLessEqual(_set_colour(cues[0])[2], int(0.45 * 65535) + 1)
        self.assertLessEqual(_wave_colour(cues[1])[2], int(0.45 * 65535) + 1)

    def test_a_tap_takes_its_colour_from_the_index_it_is_given(self):
        first = _set_colour(live.tap_cues(CAST[0], 0, PALETTE, source=7)[0])
        second = _set_colour(live.tap_cues(CAST[0], 1, PALETTE, source=7)[0])
        self.assertNotEqual(first[:2], second[:2])


class TestPads(unittest.TestCase):
    def test_drop_takes_every_light_to_black(self):
        cues = live.pad_cues(CAST, "drop", source=7)
        self.assertEqual(len(CAST), len(cues))
        for cue in cues:
            self.assertEqual(packets.SET_COLOR, _payload_type(cue))
            self.assertEqual(0, _set_colour(cue)[2], "drop means black")

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


class _StalledClock:
    """A `time` stand-in that jumps forward after the anchor is read.

    Enough of the module for `live` (which reads nothing but
    `monotonic`), so a test can put the dispatcher's cues in the past
    without spending seconds or racing the event loop.
    """

    def __init__(self, jump: float = 10.0) -> None:
        self.reads = 0
        self.jump = jump

    def monotonic(self) -> float:
        self.reads += 1
        return 0.0 if self.reads == 1 else self.jump


class TestDropStale(unittest.TestCase):
    def test_a_late_send_is_counted_and_dropped(self):
        loops = live.LiveLoops(_FakeEngine())
        # `due` well in the past: the loop stalled through this strike.
        self.assertTrue(loops._too_late(live.time.monotonic() - 1.0,
                                        live.LOOP_LATE_S))
        self.assertEqual(1, loops.skipped)

    def test_a_send_inside_its_window_is_sent(self):
        loops = live.LiveLoops(_FakeEngine())
        self.assertFalse(loops._too_late(live.time.monotonic() - 0.02,
                                         live.LOOP_LATE_S))
        self.assertEqual(0, loops.skipped, "an on-time send is not a skip")

    def test_a_one_shot_gets_the_wider_window(self):
        loops = live.LiveLoops(_FakeEngine())
        due = live.time.monotonic() - 0.2
        self.assertTrue(loops._too_late(due, live.LOOP_LATE_S))
        self.assertFalse(loops._too_late(due, live.SHOT_LATE_S),
                         "a gesture survives what a beat does not")

    def test_a_stalled_dispatch_drops_rather_than_machine_gunning(self):
        # Every cue is already ten seconds old by the time the loop gets
        # to it: sending them would land a burst off the beat AND deepen
        # the TokenBucket debt the pads then wait out.
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            cues = live.pad_cues(CAST, "flash", source=engine.source)
            original = live.time
            live.time = _StalledClock()
            try:
                loops.fire(cues, label="flash")
                await asyncio.gather(*loops._shots)
            finally:
                live.time = original
            return engine.sent, loops.skipped

        sent, skipped = asyncio.run(scenario())
        self.assertEqual([], sent, "nothing stale reaches the wire")
        self.assertEqual(len(CAST), skipped, "and every drop is counted")


class TestLiveLoops(unittest.TestCase):
    def test_a_new_loop_replaces_the_loop_on_its_lights(self):
        async def scenario():
            loops = live.LiveLoops(_FakeEngine())
            first = await loops.start_loop(
                cast=CAST, events=[_strike(0.0, CAST[0], CAST[1])],
                period_s=1.0, palette=PALETTE, label="first")
            second = await loops.start_loop(
                cast=CAST, events=[_strike(0.0, CAST[1], CAST[2])],
                period_s=1.0, palette=PALETTE, label="second")
            described = loops.describe()
            await loops.stop_all()
            return first, second, described

        first, second, described = asyncio.run(scenario())
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(["second"], [d["label"] for d in described],
                         "sharing one bulb replaces the whole loop")

    def test_a_loop_that_shares_no_bulb_runs_beside_the_first(self):
        async def scenario():
            loops = live.LiveLoops(_FakeEngine())
            await loops.start_loop(
                cast=CAST, events=[_strike(0.0, CAST[0])], period_s=1.0,
                palette=PALETTE, label="kick")
            await loops.start_loop(
                cast=CAST, events=[_strike(0.0, CAST[2])], period_s=1.0,
                palette=PALETTE, label="snare")
            described = loops.describe()
            await loops.stop_all()
            return described

        described = asyncio.run(scenario())
        self.assertEqual(["kick", "snare"], [d["label"] for d in described])

    def test_a_loop_reports_the_dots_the_panel_marks(self):
        async def scenario():
            loops = live.LiveLoops(_FakeEngine())
            started = await loops.start_loop(
                cast=CAST, events=[_strike(0.0, CAST[0]),
                                   _strike(0.5, CAST[2])],
                period_s=1.0, palette=PALETTE, label="loop")
            described = loops.describe()
            await loops.stop_all()
            return started, described

        started, described = asyncio.run(scenario())
        self.assertEqual([CAST[0]["id"], CAST[2]["id"]], started["ids"])
        self.assertEqual([CAST[0]["id"], CAST[2]["id"]], described[0]["ids"],
                         "the union of what it drives, not the cast")
        self.assertNotIn("style", described[0])

    def test_loops_actually_send_and_repeat(self):
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            await loops.start_loop(
                cast=CAST, events=[_strike(0.0, CAST[0])], period_s=0.45,
                palette=PALETTE, label="beat")
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
                cast=CAST, events=[_strike(0.0, CAST[0])], period_s=1.0,
                palette=PALETTE, label="beat")
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


class TestPadCoalescing(unittest.TestCase):
    def test_a_mashed_pad_is_one_press(self):
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            cues = live.pad_cues(CAST, "drop", source=engine.source)
            first = loops.fire_pad(cues, "drop")
            second = loops.fire_pad(cues, "drop")
            await asyncio.sleep(0.1)
            await loops.stop_all()
            return first, second, len(engine.sent)

        first, second, sent = asyncio.run(scenario())
        self.assertNotIn("coalesced", first)
        self.assertTrue(second.get("coalesced"))
        self.assertEqual(len(CAST), sent, "one drop reached the room")

    def test_the_window_closes(self):
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            cues = live.pad_cues(CAST, "drop", source=engine.source)
            loops.fire_pad(cues, "drop")
            await asyncio.sleep(0.2)
            second = loops.fire_pad(cues, "drop")
            await asyncio.sleep(0.1)
            await loops.stop_all()
            return second, len(engine.sent)

        second, sent = asyncio.run(scenario())
        self.assertNotIn("coalesced", second)
        self.assertEqual(2 * len(CAST), sent)

    def test_two_different_pads_do_not_coalesce_each_other(self):
        async def scenario():
            engine = _FakeEngine()
            loops = live.LiveLoops(engine)
            drop = live.pad_cues(CAST, "drop", source=engine.source)
            flash = live.pad_cues(CAST, "flash", source=engine.source)
            loops.fire_pad(drop, "drop")
            second = loops.fire_pad(flash, "flash")
            await asyncio.sleep(0.1)
            await loops.stop_all()
            return second

        self.assertNotIn("coalesced", asyncio.run(scenario()))


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
