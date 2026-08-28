#!/usr/bin/env python3
"""BRight's Manual tab, as a DAW: the transport, clips on its grid, the
live send path that never sleeps, and the power-on that makes a dark
room answer at all.

Three bugs are pinned here by name, because each of them was invisible
from the outside and each cost a whole feature:

* a bulb that is powered off accepts every packet and shows nothing;
* `send_governed` deepens a token debt the NEXT caller waits out, so
  live latency stacked instead of spiking;
* loops that free-ran from a button press had no relationship to the
  music, however carefully the tempo was tapped.
"""

import asyncio
import base64
import os
import struct
import sys
import time
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from lifx import engine as engine_mod  # noqa: E402
from lifx import packets  # noqa: E402
from playback import conductor  # noqa: E402
from playback import live  # noqa: E402
from playback.clock import ShowClock  # noqa: E402
from playback.transport import Transport  # noqa: E402

PALETTE = [[200, 0.9], [30, 0.8], [300, 0.7]]


def bulb(n: int, role: str = "lamp") -> dict:
    serial = f"d073d500000{n}"
    return {"id": f"lifx-{serial}", "kind": "lifx", "serial": serial,
            "label": f"bulb {n}", "role": role, "x": n / 10, "y": 0.5,
            "rtt": {"p50_ms": 6.0}}


CAST = [bulb(1), bulb(2), bulb(3)]


class Ticker:
    """A monotonic clock a test moves by hand.

    Both the transport and the `ShowClock` under it read this, so a
    whole song can be walked through without spending a second of it.
    """

    def __init__(self, start: float = 1000.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


def breathing_beats(count: int = 64, first: float = 0.6,
                    shrink: float = 0.004) -> list[float]:
    """A track whose tempo speeds up, beat by beat.

    The point of the whole transport: a grid taken from an average beat
    and a grid taken from the analyzer's own array agree at the start
    and disagree by whole beats a minute in. Everything asserting the
    array is consulted is asserted against this.
    """
    beats, at, gap = [], 0.0, first
    for _ in range(count):
        beats.append(round(at, 6))
        at += gap
        gap = max(0.2, gap - shrink)
    return beats


def track(beats: list[float], bar_beats: int = 4) -> dict:
    return {"beats": beats, "downbeats": beats[::bar_beats], "bpm": 100.0}


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


# ---------------------------------------------------------------------------
# The transport
# ---------------------------------------------------------------------------
class TestTransportTrackMode(unittest.TestCase):
    def setUp(self):
        self.tick = Ticker()
        self.beats = breathing_beats()
        self.clock = ShowClock(monotonic=self.tick)
        self.clock.anchor(self.tick(), 0.0)
        self.transport = Transport(monotonic=self.tick)
        self.assertTrue(
            self.transport.bind_track(track(self.beats), self.clock))

    def test_a_bound_transport_is_ready_and_says_which_kind(self):
        self.assertEqual("track", self.transport.kind)
        self.assertTrue(self.transport.ready)
        self.assertAlmostEqual(100.0, self.transport.bpm, places=2)

    def test_a_track_with_no_beats_is_refused_rather_than_faked(self):
        # A transport that answered anyway would hand every clip a bar
        # line derived from nothing at all.
        empty = Transport(monotonic=self.tick)
        self.assertFalse(empty.bind_track({"beats": []}, self.clock))
        self.assertFalse(empty.ready)

    def test_an_unanchored_clock_is_refused_too(self):
        cold = Transport(monotonic=self.tick)
        self.assertFalse(
            cold.bind_track(track(self.beats), ShowClock(monotonic=self.tick)))

    def test_bar_one_is_the_bar_the_session_started_inside(self):
        # Bar 1's downbeat is at track second 0, which is where the clock
        # is, so bar_time(1) is now.
        self.assertAlmostEqual(self.tick(), self.transport.bar_time(1),
                               places=6)
        self.assertEqual(1, self.transport.position()["bar"])

    def test_bars_come_from_the_downbeats_array_not_from_a_bar_length(self):
        start = self.tick()
        for bar in (2, 3, 5, 9):
            self.assertAlmostEqual(
                start + self.beats[(bar - 1) * 4],
                self.transport.bar_time(bar), places=6,
                msg="a bar line is the analyzer's downbeat")
        # And that is NOT what four times the median beat would give, on
        # a track whose tempo moves.
        four_beats = 4 * self.transport.beat_s
        self.assertNotAlmostEqual(start + 8 * four_beats,
                                  self.transport.bar_time(9), places=2)

    def test_a_beat_offset_is_looked_up_in_the_beats_array(self):
        start = self.tick()
        # Bar 5, two beats in, is beats[18] — not bar 5 plus two average
        # beats, which by then is most of a beat away.
        self.assertAlmostEqual(start + self.beats[18],
                               self.transport.beat_time(5, 2.0), places=6)
        naive = self.transport.bar_time(5) + 2 * self.transport.beat_s
        self.assertGreater(abs(naive - self.transport.beat_time(5, 2.0)),
                           0.05, "the two answers really do diverge")

    def test_a_fractional_offset_interpolates_inside_its_own_beat(self):
        start = self.tick()
        expected = self.beats[17] + 0.5 * (self.beats[18] - self.beats[17])
        self.assertAlmostEqual(start + expected,
                               self.transport.beat_time(5, 1.5), places=6)

    def test_past_the_end_of_the_array_it_extrapolates_rather_than_stops(self):
        # A clip outliving the analysis is a clip that keeps playing, not
        # a clip that stops on the last beat the analyzer found.
        far = self.transport.bar_time(200)
        self.assertGreater(far, self.transport.bar_time(199))

    def test_position_walks_the_bars_as_the_clock_moves(self):
        self.tick.advance(self.beats[4] + 0.01)      # into bar 2
        position = self.transport.position()
        self.assertEqual(2, position["bar"])
        self.assertEqual(1, position["beat"])
        self.tick.advance(self.beats[6] - self.beats[4])
        self.assertEqual(3, self.transport.position()["beat"])

    def test_the_next_bar_line_is_the_next_one(self):
        self.tick.advance(self.beats[1])             # mid bar 1
        self.assertAlmostEqual(self.transport.bar_time(2),
                               self.transport.next_bar_time(), places=6)

    def test_beats_since_walks_the_array_back(self):
        self.tick.advance(self.beats[6])             # bar 2, two beats in
        self.assertAlmostEqual(2.0, self.transport.beats_since(2), places=6)

    def test_the_sync_payload_carries_what_a_phone_extrapolates_from(self):
        payload = self.transport.sync_payload()
        for key in ("kind", "bpm", "beat_s", "bar_beats", "bar", "beat",
                    "server_now", "next_bar_at"):
            self.assertIn(key, payload)
        self.assertEqual(self.tick(), payload["server_now"])


class TestTransportTapped(unittest.TestCase):
    def setUp(self):
        self.tick = Ticker()
        self.transport = Transport(monotonic=self.tick)

    def tap_at(self, *gaps):
        self.transport.tap()
        for gap in gaps:
            self.tick.advance(gap)
            self.transport.tap()

    def test_two_taps_are_not_a_tempo(self):
        self.tap_at(0.5)
        self.assertFalse(self.transport.ready)

    def test_three_taps_are(self):
        self.tap_at(0.5, 0.5)
        self.assertEqual("tapped", self.transport.kind)
        self.assertTrue(self.transport.ready)
        self.assertAlmostEqual(120.0, self.transport.bpm, places=1)

    def test_one_clumsy_gap_does_not_bend_the_tempo(self):
        self.tap_at(0.9, 0.5, 0.5, 0.5)
        self.assertAlmostEqual(120.0, self.transport.bpm, places=1)

    def test_the_most_recent_tap_is_a_beat_boundary(self):
        self.tap_at(0.5, 0.5, 0.5)
        self.assertAlmostEqual(0.0, self.transport.position()["beat_phase"],
                               places=3)

    def test_a_long_silence_starts_the_count_again(self):
        # Two attempts at tapping a tempo are not one very slow bar.
        self.tap_at(0.5, 0.5)
        self.tick.advance(9.0)
        self.tap_at(0.4, 0.4)
        self.assertAlmostEqual(150.0, self.transport.bpm, places=1)

    def test_mark_downbeat_rephases_and_leaves_the_tempo_alone(self):
        self.tap_at(0.5, 0.5, 0.5)
        bpm = self.transport.bpm
        self.tick.advance(0.31)                       # off the "1"
        self.assertGreater(self.transport.position()["bar_phase"], 0.0)
        self.transport.mark_downbeat()
        self.assertAlmostEqual(bpm, self.transport.bpm, places=6,
                               msg="the DJ move moves phase, never tempo")
        self.assertAlmostEqual(0.0,
                               self.transport.position()["bar_phase"],
                               places=3)
        self.assertAlmostEqual(self.tick(), self.transport.bar_time(
            self.transport.position()["bar"]), places=6)

    def test_bars_run_from_the_phase_reference(self):
        self.tap_at(0.5, 0.5, 0.5)
        self.transport.mark_downbeat()
        start = self.transport.position()["bar"]
        self.assertAlmostEqual(self.tick() + 2.0,
                               self.transport.bar_time(start + 1), places=6)

    def test_set_tempo_keeps_the_bar_number_going_forward(self):
        # A clip stores the bar its cycle aligns to, so a tempo change
        # that renumbered the bars would move every clip in the session.
        self.tap_at(0.5, 0.5, 0.5)
        self.tick.advance(1.0)
        before = self.transport.position()["bar"]
        self.transport.set_tempo(180.0)
        self.assertGreaterEqual(self.transport.position()["bar"], before)
        self.assertAlmostEqual(180.0, self.transport.bpm, places=6)


class TestQuantize(unittest.TestCase):
    def setUp(self):
        self.transport = Transport()

    def test_it_snaps_to_the_nearest_division(self):
        self.assertAlmostEqual(1.0, self.transport.quantize_beats(0.9, 1.0))
        self.assertAlmostEqual(0.5, self.transport.quantize_beats(0.6, 0.5))
        self.assertAlmostEqual(0.25, self.transport.quantize_beats(0.3, 0.25))

    def test_zero_is_off_and_that_is_a_real_setting(self):
        self.assertAlmostEqual(0.937,
                               self.transport.quantize_beats(0.937, 0))
        self.assertAlmostEqual(0.937,
                               self.transport.quantize_beats(0.937, None))

    def test_a_tap_just_before_the_loop_point_wraps_to_the_top(self):
        # The whole reason tapping on the downbeat works: quantizing a
        # hair-early tap lands it on the clip's own length, and that
        # moment IS beat zero of the next cycle.
        length = 4.0
        snapped = self.transport.quantize_beats(3.96, 1.0)
        self.assertAlmostEqual(4.0, snapped)
        self.assertAlmostEqual(0.0, snapped % length)


# ---------------------------------------------------------------------------
# The send path
# ---------------------------------------------------------------------------
class _Recorder:
    """Stands in for the datagram transport: every packet, in order."""

    def __init__(self):
        self.sent = []

    def sendto(self, data, addr):
        self.sent.append((bytes(data), addr))

    def close(self):
        pass


def real_engine() -> engine_mod.LifxEngine:
    """A real engine with a fake wire, so the tests read actual bytes."""
    engine = engine_mod.LifxEngine()
    engine._transport = _Recorder()
    engine.devices = {f["serial"]: {"serial": f["serial"], "ip": "10.0.0.5",
                                    "port": 56700} for f in CAST}
    return engine


class TestTokenBucket(unittest.TestCase):
    def test_try_acquire_does_not_deepen_the_debt_on_a_refusal(self):
        # `acquire` drives tokens negative on purpose, which is right for
        # a compiled show and is exactly the stacking latency a played
        # gesture cannot afford.
        tick = Ticker(0.0)
        bucket = engine_mod.TokenBucket(rate=10.0, burst=2.0, clock=tick)
        self.assertTrue(bucket.try_acquire())
        self.assertTrue(bucket.try_acquire())
        for _ in range(20):
            self.assertFalse(bucket.try_acquire())
        tick.advance(0.1)                       # exactly one token back
        self.assertTrue(bucket.try_acquire(),
                        "twenty refusals cost the next caller nothing")

    def test_acquire_still_queues_for_the_compiled_show(self):
        tick = Ticker(0.0)
        bucket = engine_mod.TokenBucket(rate=10.0, burst=1.0, clock=tick)
        self.assertEqual(0.0, bucket.acquire())
        first = bucket.acquire()
        second = bucket.acquire()
        self.assertGreater(second, first, "the debt is what orders them")


class TestSendLive(unittest.TestCase):
    def test_it_never_awaits_and_drops_instead_of_sleeping(self):
        engine = real_engine()
        self.assertFalse(asyncio.iscoroutinefunction(engine.send_live))
        serial = CAST[0]["serial"]
        packet = packets.halt_waveform(target=bytes.fromhex(serial),
                                       source=engine.source, sequence=1)
        started = time.monotonic()
        sent = sum(1 for _ in range(60)
                   if engine.send_live(serial, packet, ("10.0.0.5", 56700)))
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.05, "a saturated bucket costs no time")
        self.assertEqual(int(engine_mod.MAX_MSGS_PER_SECOND), sent)
        self.assertEqual(60 - sent, engine.dropped)
        self.assertEqual(sent, len(engine._transport.sent))

    def test_priority_goes_out_through_a_dry_bucket(self):
        engine = real_engine()
        serial = CAST[0]["serial"]
        packet = packets.halt_waveform(target=bytes.fromhex(serial),
                                       source=engine.source, sequence=1)
        for _ in range(60):
            engine.send_live(serial, packet, ("10.0.0.5", 56700))
        before = len(engine._transport.sent)
        self.assertTrue(engine.send_live(serial, packet,
                                         ("10.0.0.5", 56700), priority=True))
        self.assertEqual(before + 1, len(engine._transport.sent))


class TestPowerOn(unittest.TestCase):
    """The regression guard for the bug that made a dark room do nothing.

    `packets.set_light_power` had zero callers in the whole repo, and a
    powered-off LIFX bulb accepts colour and waveform packets and shows
    none of them — so every gesture was sent, accepted and invisible.
    """

    def test_the_engine_powers_every_named_bulb(self):
        engine = real_engine()
        engine.power_on([f["serial"] for f in CAST])
        powered = {}
        for data, _addr in engine._transport.sent:
            header = packets.parse_header(data)
            if header["type"] == packets.SET_LIGHT_POWER:
                level = struct.unpack_from("<H", header["payload"])[0]
                powered[header["target"].hex()] = level
        self.assertEqual({f["serial"] for f in CAST}, set(powered))
        self.assertEqual({65535}, set(powered.values()), "on, not dimmed")

    def test_a_bulb_off_the_registry_is_skipped_not_fatal(self):
        engine = real_engine()
        self.assertEqual(len(CAST),
                         engine.power_on([f["serial"] for f in CAST]
                                         + ["d073d5ffffff"]))

    def test_starting_a_session_powers_the_room_and_sets_a_base(self):
        engine = real_engine()
        session = live.LiveClips(engine)
        session.begin(cast=CAST, palette=PALETTE)
        kinds = [packets.parse_header(data)["type"]
                 for data, _ in engine._transport.sent]
        self.assertEqual(len(CAST), kinds.count(packets.SET_LIGHT_POWER))
        self.assertEqual(len(CAST), kinds.count(packets.SET_COLOR),
                         "and a dim base, so the first strike is visible")
        self.assertLess(kinds.index(packets.SET_LIGHT_POWER),
                        kinds.index(packets.SET_COLOR),
                        "power first: a colour sent to a dark bulb is a "
                        "colour nobody sees")


# ---------------------------------------------------------------------------
# Cues
# ---------------------------------------------------------------------------
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

    def test_a_pad_reaches_the_room_through_a_dry_bucket(self):
        # The one gesture that must never be the packet that got dropped:
        # a person mashing DROP over a session that has been spending
        # tokens all evening.
        engine = real_engine()
        session = live.LiveClips(engine)
        session.begin(cast=CAST, palette=PALETTE)
        strike = packets.halt_waveform(
            target=bytes.fromhex(CAST[0]["serial"]), source=engine.source,
            sequence=1)
        for fixture in CAST:
            for _ in range(40):
                engine.send_live(fixture["serial"], strike,
                                 ("10.0.0.5", 56700))
        before = len(engine._transport.sent)
        session.fire_pad(live.pad_cues(CAST, "drop", engine.source), "drop")
        self.assertEqual(before + len(CAST), len(engine._transport.sent))


class TestPowerCues(unittest.TestCase):
    def test_the_base_is_dim_and_respects_a_candle(self):
        candle = bulb(4, role="candle")
        cues = live.power_cues([CAST[0], candle], PALETTE, source=7)
        self.assertEqual(2, len(cues))
        for cue in cues:
            self.assertEqual(packets.SET_COLOR, _payload_type(cue))
            self.assertLessEqual(_set_colour(cue)[2],
                                 int(live.BASE_LEVEL * 65535) + 1)


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------
class _FakeEngine:
    def __init__(self):
        self.source = 0x42420001
        self.sent = []
        self.powered = []
        self.devices = {}
        self.dropped = 0
        self._sequence = 0

    async def start(self):
        pass

    def _addr(self, serial):
        return ("10.0.0.5", 56700)

    def _next_sequence(self):
        self._sequence = (self._sequence + 1) & 0xFF
        return self._sequence

    def send_live(self, serial, data, addr, *, priority=False):
        self.sent.append((serial, bytes(data)))
        return True

    async def send_governed(self, serial, data, addr):
        self.sent.append((serial, bytes(data)))

    def power_on(self, serials, addr_of=None):
        self.powered.extend(serials)
        return len(list(self.powered))

    async def request(self, *args, **kwargs):
        return None


def tapped_session(bpm: float = 300.0) -> live.LiveClips:
    """A session with a grid and no wall-clock music behind it."""
    session = live.LiveClips(_FakeEngine())
    session.begin(cast=CAST, palette=PALETTE)
    session.transport.set_tempo(bpm)
    return session


async def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


class TestClipLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_a_clip_starts_on_the_bar_line_and_not_on_the_press(self):
        session = tapped_session()                    # 0.2s beat, 0.8s bar
        transport = session.transport
        armed = session.arm_clip(bars=1, quantize=0.25)
        clip = session.clip(armed["id"])
        bar_line = transport.next_bar_time()
        self.assertEqual("armed", clip.state)
        self.assertGreater(bar_line - time.monotonic(), 0.0,
                           "the count-in is a real wait, not a formality")
        self.assertTrue(await wait_for(lambda: clip.state != "armed"))
        began = time.monotonic()
        self.assertEqual("recording", clip.state)
        self.assertGreaterEqual(began, bar_line - 0.05)
        self.assertEqual(transport.bar_at(bar_line), clip.start_bar)
        await session.stop_all()

    async def test_a_take_records_quantized_taps_then_loops_itself(self):
        session = tapped_session()
        engine = session.engine
        armed = session.arm_clip(bars=1, quantize=0.25)
        clip = session.clip(armed["id"])
        self.assertTrue(await wait_for(lambda: clip.state == "recording"))
        self.assertIsNone(session.tap(CAST[0]["id"]))
        self.assertEqual(1, len(clip.events))
        beat = clip.events[0]["beat"]
        self.assertAlmostEqual(beat, round(beat / 0.25) * 0.25, places=3,
                               msg="a tap lands on the quantize grid")
        self.assertLess(beat, clip.length_beats(session.transport))
        engine.sent = []
        self.assertTrue(await wait_for(lambda: clip.state == "looping"))
        self.assertTrue(await wait_for(lambda: len(engine.sent) >= 2),
                        "and the take plays itself back")
        await session.stop_all()

    async def test_a_state_change_nobody_pressed_for_is_announced(self):
        # armed → recording → looping happen on their own, and a phone
        # whose status only refreshes on a press is wrong exactly while
        # something is happening.
        session = tapped_session()
        seen = []
        session.on_change = lambda: seen.append(
            [c["state"] for c in session.describe()])
        armed = session.arm_clip(bars=1, quantize=1.0)
        clip = session.clip(armed["id"])
        self.assertTrue(await wait_for(lambda: clip.state == "looping"))
        flat = [state for states in seen for state in states]
        self.assertIn("armed", flat)
        self.assertIn("recording", flat)
        self.assertIn("looping", flat)
        await session.stop_all()

    async def test_a_clip_needs_a_grid_before_it_can_be_armed(self):
        session = live.LiveClips(_FakeEngine())
        session.begin(cast=CAST, palette=PALETTE)
        with self.assertRaises(ValueError) as caught:
            session.arm_clip(1, 1.0)
        self.assertIn("tempo", str(caught.exception))


class TestOverdubAndEditing(unittest.IsolatedAsyncioTestCase):
    async def looping(self, bars: int = 1, quantize: float = 1.0):
        session = tapped_session()
        armed = session.arm_clip(bars=bars, quantize=quantize)
        clip = session.clip(armed["id"])
        self.assertTrue(await wait_for(lambda: clip.state == "looping"))
        return session, clip

    async def test_a_tap_over_a_looping_clip_joins_it(self):
        session, clip = await self.looping()
        self.assertTrue(clip.rec_enabled)
        session.tap(CAST[1]["id"])
        self.assertEqual(1, len(clip.events))
        self.assertEqual([CAST[1]["id"]], clip.events[0]["ids"])
        await session.stop_all()

    async def test_two_bulbs_on_one_beat_are_one_event(self):
        session, clip = await self.looping()
        session.add_tap(clip.id, CAST[0]["id"])
        beat = clip.events[0]["beat"]
        # A second bulb inside the merge window joins the event rather
        # than making a new one a thirty-second note away.
        session._merge(clip, beat + live.MERGE_BEATS / 2, [CAST[2]["id"]])
        self.assertEqual(1, len(clip.events))
        self.assertEqual([CAST[0]["id"], CAST[2]["id"]], clip.events[0]["ids"])
        await session.stop_all()

    async def test_record_enable_is_exclusive(self):
        # Two clips taking the same tap is a tap recorded twice, which
        # nobody asks for and nobody can see happening.
        session, first = await self.looping()
        second = session.clip(session.arm_clip(bars=1, quantize=1.0)["id"])
        self.assertFalse(first.rec_enabled)
        # Nothing is listening during a count-in — an armed clip has no
        # take to put a tap in yet, and the loop it replaced has already
        # handed its record-enable over.
        self.assertIsNone(session.recording_clip())
        self.assertTrue(await wait_for(lambda: second.state == "recording"))
        self.assertEqual(second, session.recording_clip())
        await session.stop_all()

    async def test_a_muted_clip_keeps_its_pattern_and_sends_nothing(self):
        session, clip = await self.looping()
        session.add_tap(clip.id, CAST[0]["id"])
        session.set_muted(clip.id, True)
        session.engine.sent = []
        await asyncio.sleep(1.0)
        self.assertEqual([], session.engine.sent)
        self.assertEqual(1, len(clip.events))
        await session.stop_all()

    async def test_clear_empties_the_pattern_and_keeps_the_clip(self):
        session, clip = await self.looping()
        session.add_tap(clip.id, CAST[0]["id"])
        self.assertTrue(session.clear_clip(clip.id))
        self.assertEqual([], clip.events)
        self.assertEqual([clip.id], [c["id"] for c in session.describe()])
        await session.stop_all()

    async def test_delete_takes_the_clip_and_halts_its_bulbs(self):
        session, clip = await self.looping()
        session.add_tap(clip.id, CAST[0]["id"])
        session.engine.sent = []
        self.assertTrue(await session.delete_clip(clip.id))
        self.assertEqual([], session.describe())
        self.assertTrue(session.engine.sent, "the stop reaches the bulb")
        halted = packets.parse_header(session.engine.sent[-1][1])
        self.assertEqual(packets.SET_WAVEFORM, halted["type"],
                         "a bulb is stopped by ending its waveform")
        await session.stop_all()

    async def test_a_rhythm_faster_than_one_bulb_can_follow_is_refused(self):
        session, clip = await self.looping(bars=1, quantize=0.25)
        # 0.2s beats, four beats a bar: a bulb on every sixteenth is 40
        # packets a second against a 20/s ceiling.
        refusals = [session._merge(clip, i * 0.25, [CAST[0]["id"]])
                    for i in range(16)]
        del refusals
        self.assertIsNotNone(session._too_fast(clip, CAST[0]["id"], 4.0))
        await session.stop_all()

    async def test_a_bulb_off_the_map_is_a_sentence_not_a_traceback(self):
        session, clip = await self.looping()
        self.assertIn("no bulb", session.add_tap(clip.id, "lifx-gone") or "")
        await session.stop_all()


class TestSchedulingIsRederived(unittest.TestCase):
    """The anti-drift claim, proven twice: once against a song whose
    tempo breathes, once against a tempo somebody changes mid-run."""

    def test_every_cycle_comes_from_the_transports_own_bar_lines(self):
        tick = Ticker()
        beats = breathing_beats()
        clock = ShowClock(monotonic=tick)
        clock.anchor(tick(), 0.0)
        transport = Transport(monotonic=tick)
        transport.bind_track(track(beats), clock)
        session = live.LiveClips(_FakeEngine(), transport=transport)
        session.begin(cast=CAST, palette=PALETTE)
        clip = live.Clip(id=1, bars=1, quantize=1.0, state="looping",
                         start_bar=1, events=[{"beat": 1.0,
                                               "ids": [CAST[0]["id"]]}])
        start = tick()
        for cycle in range(8):
            self.assertAlmostEqual(start + beats[cycle * 4],
                                   session._cycle_start(clip, cycle),
                                   places=6)
            self.assertAlmostEqual(start + beats[cycle * 4 + 1],
                                   session._event_time(clip, cycle,
                                                       clip.events[0]),
                                   places=6)
        # A loop that accumulated a period would be here instead, and by
        # cycle 8 it is most of a beat adrift.
        naive = start + 8 * 4 * transport.beat_s
        self.assertGreater(abs(naive - session._cycle_start(clip, 8)), 0.1)

    def test_a_tempo_change_moves_the_next_cycle_and_not_the_clip(self):
        session = tapped_session(bpm=120.0)           # 0.5s beat, 2s bar
        transport = session.transport
        clip = live.Clip(id=1, bars=1, quantize=1.0, state="looping",
                         start_bar=transport.bar_at())
        before = session._cycle_start(clip, 1)
        transport.set_tempo(240.0)                    # 0.25s beat, 1s bar
        after = session._cycle_start(clip, 1)
        self.assertNotAlmostEqual(before, after, places=3)
        self.assertAlmostEqual(
            transport.bar_time(clip.start_bar + 1), after, places=9,
            msg="the cycle is the transport's answer, never a stored one")


class TestDropStale(unittest.TestCase):
    def test_a_late_send_is_counted_and_dropped(self):
        session = live.LiveClips(_FakeEngine())
        # `due` well in the past: the loop stalled through this strike.
        self.assertTrue(session._too_late(live.time.monotonic() - 1.0,
                                          live.LOOP_LATE_S))
        self.assertEqual(1, session.skipped)

    def test_a_send_inside_its_window_is_sent(self):
        session = live.LiveClips(_FakeEngine())
        self.assertFalse(session._too_late(live.time.monotonic() - 0.02,
                                           live.LOOP_LATE_S))
        self.assertEqual(0, session.skipped, "an on-time send is not a skip")

    def test_a_one_shot_gets_the_wider_window(self):
        session = live.LiveClips(_FakeEngine())
        due = live.time.monotonic() - 0.2
        self.assertTrue(session._too_late(due, live.LOOP_LATE_S))
        self.assertFalse(session._too_late(due, live.SHOT_LATE_S),
                         "a gesture survives what a beat does not")

    def test_a_stall_skips_the_cycles_it_stalled_through(self):
        # Playing the missed cycles back to catch up would machine-gun
        # them into the room, off every beat they were meant to be on.
        session = tapped_session(bpm=120.0)
        clip = live.Clip(id=1, bars=1, quantize=1.0, state="looping",
                         start_bar=session.transport.bar_at())
        session.transport.set_tempo(300.0)   # the grid ran away from us
        self.assertGreaterEqual(session._catch_up(clip, 1), 1)


class TestOneShots(unittest.TestCase):
    def test_fire_sends_once_and_does_not_loop(self):
        async def scenario():
            engine = _FakeEngine()
            session = live.LiveClips(engine)
            session.begin(cast=CAST, palette=PALETTE)
            cues = live.pad_cues([CAST[0]], "flash", source=engine.source)
            engine.sent = []
            session.fire(cues, label="flash")
            await asyncio.sleep(0.2)
            count_then = len(engine.sent)
            await asyncio.sleep(0.3)
            await session.stop_all()
            return count_then, len(engine.sent)

        then, later = asyncio.run(scenario())
        self.assertEqual(1, then)
        self.assertEqual(then, later, "a one-shot does not repeat")


class TestPadCoalescing(unittest.TestCase):
    def _session(self):
        session = live.LiveClips(_FakeEngine())
        session.begin(cast=CAST, palette=PALETTE)
        session.engine.sent = []
        return session

    def test_a_mashed_pad_is_one_press(self):
        session = self._session()
        cues = live.pad_cues(CAST, "drop", source=session.engine.source)
        first = session.fire_pad(cues, "drop")
        second = session.fire_pad(cues, "drop")
        self.assertNotIn("coalesced", first)
        self.assertTrue(second.get("coalesced"))
        self.assertEqual(len(CAST), len(session.engine.sent),
                         "one drop reached the room")

    def test_two_different_pads_do_not_coalesce_each_other(self):
        session = self._session()
        drop = live.pad_cues(CAST, "drop", source=session.engine.source)
        flash = live.pad_cues(CAST, "flash", source=session.engine.source)
        session.fire_pad(drop, "drop")
        second = session.fire_pad(flash, "flash")
        self.assertNotIn("coalesced", second)
        self.assertEqual(2 * len(CAST), len(session.engine.sent))


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

    def test_music_that_started_anchors_the_clock_the_bars_come_from(self):
        # Without this the transport has no track grid to bind to, and a
        # session on an analyzed track falls back to tapping a tempo it
        # already knows.
        play = conductor.ha_client.play_media
        write = conductor.atomic_write.write_json
        conductor.ha_client.play_media = lambda *a, **k: {"ok": True}
        conductor.atomic_write.write_json = lambda *a, **k: None

        async def scenario():
            run = self._conductor()
            await run.start_manual(
                serials=[CAST[0]["serial"]],
                media_player="media_player.k",
                media_content_id="media-source://x/y.mp3")
            return run

        try:
            run = asyncio.run(scenario())
        finally:
            conductor.ha_client.play_media = play
            conductor.atomic_write.write_json = write
        self.assertTrue(run.clock.anchored)

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
        self.assertFalse(run.clock.anchored,
                         "and no grid is claimed for music nobody heard")

    def test_stop_runs_the_before_stop_hook_first(self):
        order = []

        async def hook():
            order.append("clips")

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

        self.assertEqual(["clips", "halt"], asyncio.run(scenario()),
                         "the clips stop before the bulbs are halted, or "
                         "the next strike re-lights what was just stopped")


if __name__ == "__main__":
    unittest.main()
