#!/usr/bin/env python3
"""BRight's playback engine: the clock, drift handling, cue scheduling and
the metronome show's budget arithmetic."""

import asyncio
import base64
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "bright", "panel")
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


class TestAShowThatCannotStartSaysSo(unittest.TestCase):
    """`start()` answers before the show has begun, so a play command the
    speaker refuses fails with nobody listening.

    What that looked like: "Running: 412 cues" in the panel, a dark room,
    and the reason only in asyncio's "Task exception was never retrieved"
    whenever the dead task was collected.
    """

    def _run_a_doomed_show(self, tmp):
        async def scenario():
            engine = _FakeEngine()
            run = conductor.Conductor.__new__(conductor.Conductor)
            run.engine = engine
            run.clock = ShowClock()
            run._snapshot = {}
            run._task = run._poller = run._verify = None
            run.state = {"status": "idle"}

            restored = []
            original_restore = run._restore_snapshot

            async def counting_restore():
                restored.append(True)
                await original_restore()

            run._restore_snapshot = counting_restore

            started = await run.start(
                [{"t": 0.0, "ch": "lifx", "serial": "aa" * 6,
                  "payload_b64": ""}],
                media_player="media_player.kitchen",
                media_content_id="media-source://media_source/local/x.mp3",
                title="x", duration_s=1.0)

            # Awaiting the dead task re-raises what killed it, which is
            # the refusal itself — assert it rather than swallowing it.
            with self.assertRaises(RuntimeError):
                await run._task
            # The done callback runs on the next turn of the loop, and the
            # restore it schedules on the one after that.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return started, run.state, restored

        return asyncio.run(scenario())

    def test_the_state_carries_the_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_file = conductor.STATE_FILE
            conductor.STATE_FILE = Path(tmp) / "state.json"
            load = conductor.calibration_store.load
            play = conductor.ha_client.play_media
            conductor.calibration_store.load = lambda *a, **k: {
                "effective_offset_ms": 0.0}
            conductor.ha_client.play_media = lambda *a, **k: {
                "error": "HTTP 500 from /services/media_player/play_media"}
            try:
                started, state, restored = self._run_a_doomed_show(tmp)
            finally:
                conductor.STATE_FILE = state_file
                conductor.calibration_store.load = load
                conductor.ha_client.play_media = play

        self.assertTrue(started["ok"], "start answers before the show runs")
        self.assertEqual("error", state["status"])
        self.assertIn("play_media", state["error"])
        self.assertEqual([True], restored,
                         "the lights were snapshotted and never put back")


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

    def test_a_drop_gets_a_dark_then_full_flash_on_every_bulb(self):
        analysis = {**self.ANALYSIS,
                    "drops": [{"t": 60.0, "strength": 0.9}]}
        cues = conductor.metronome_cues(analysis, self.DEVICES, source=1)
        for serial in self.DEVICES:
            mine = [c for c in cues if c["serial"] == serial]
            dark = next(c for c in mine if c["desc"] == "drop blackout")
            flash = next(c for c in mine if c["desc"] == "drop flash")
            back = next(c for c in mine if c["desc"] == "back to base")
            # Dark just before, full blast ON the drop, base afterwards.
            self.assertLess(dark["t"], 60.0)
            self.assertEqual(60.0, flash["t"])
            self.assertGreater(back["t"], 60.0)
            payload = base64.b64decode(flash["payload_b64"])
            header = packets.parse_header(payload)
            self.assertEqual(packets.SET_COLOR, header["type"])
        self.assertLess(conductor.peak_rate_per_device(cues), 20.0)

    def test_no_drops_means_the_old_metronome_exactly(self):
        cues = conductor.metronome_cues(self.ANALYSIS, self.DEVICES, source=1)
        self.assertFalse([c for c in cues
                          if c["desc"].startswith("drop")])

    def test_media_content_id_stays_inside_media(self):
        self.assertEqual(
            "media-source://media_source/local/music/test.mp3",
            conductor.media_content_id_for(self.ANALYSIS))
        outside = {"file": "/config/secrets.yaml"}
        self.assertIsNone(conductor.media_content_id_for(outside))


if __name__ == "__main__":
    unittest.main()


class TestStoppingStopsTheBulbs(unittest.TestCase):
    """A waveform runs ON the bulb, so ending the cue list does not end it.

    This is the failure a person sees rather than reads: press Stop and the
    room carries on strobing to the end of a routine that was handed over
    seconds ago. Nothing BRight stops *doing* can reach it — the only thing
    that ends a running waveform is another waveform, which is what
    `packets.halt_waveform` is for.

    Every case below uses `_FakeEngine`, whose `request` answers None, so
    NOTHING is ever snapshotted. That is deliberate and it is the old bug's
    shape: stop only ever spoke to bulbs it had snapshotted.
    """

    @staticmethod
    def _run_with(cues, **attrs):
        """A conductor that has dispatched `cues`, ready to be stopped."""
        engine = _FakeEngine()
        run = conductor.Conductor.__new__(conductor.Conductor)
        run.engine = engine
        run.clock = ShowClock()
        run._snapshot = {}
        run._end_scene = None
        run._driven = set()
        run._task = run._poller = run._verify = None
        run.state = {}
        run._update_state = lambda **kw: None
        run._write_state = lambda **kw: None
        for name, value in attrs.items():
            setattr(run, name, value)
        asyncio.run(run._take_snapshot(cues))
        return run, engine

    @staticmethod
    def _cues(*serials):
        pulse = packets.set_waveform(
            transient=False, hue=0, saturation=65535, brightness=65535,
            kelvin=3500, period_ms=120, cycles=40.0,
            target=bytes(6), source=0x42420001)
        return [{"t": 0.0, "ch": "lifx", "serial": s, "lead_ms": 0,
                 "payload_b64": base64.b64encode(pulse).decode()}
                for s in serials]

    def _halts(self, engine):
        return [(serial, packets.parse_header(data))
                for serial, data in engine.sent
                if packets.parse_header(data)["type"] == packets.SET_WAVEFORM]

    def test_every_driven_bulb_is_halted_though_none_was_snapshotted(self):
        run, engine = self._run_with(self._cues("aa" * 6, "bb" * 6))
        self.assertEqual({}, run._snapshot, "the fake engine answers nothing")
        asyncio.run(run.stop())
        self.assertEqual({"aa" * 6, "bb" * 6},
                         {serial for serial, _ in self._halts(engine)},
                         "a bulb that never answered GetColor is still a bulb "
                         "this show handed a waveform to")

    def test_the_halt_is_a_waveform_and_transient(self):
        """SetColor was what stop used to send, and it is not this.

        The bulb keeps running its routine underneath a SetColor, so the
        strobe carries on around the new value. Only another waveform
        replaces it, and `transient` is what returns the light to the
        colour it held before the routine started rather than to whatever
        the halting packet happens to carry.
        """
        run, engine = self._run_with(self._cues("aa" * 6))
        asyncio.run(run.stop())
        halts = self._halts(engine)
        self.assertEqual(1, len(halts))
        # Unpacked with the module's own struct rather than hand-counted
        # offsets: a test that recomputes the layout is a second copy of it,
        # and it agrees with itself rather than with the packet.
        (_resv, transient, _h, _s, _b, _k, period_ms, cycles, _skew,
         _shape) = packets._SET_WAVEFORM.unpack_from(halts[0][1]["payload"])
        self.assertEqual(1, transient, "must return the bulb to its own colour")
        self.assertEqual(1.0, cycles, "one cycle — it ends as soon as it starts")
        self.assertEqual(packets.HALT_PERIOD_MS, period_ms)

    def test_an_end_scene_does_not_excuse_the_bulbs(self):
        """The path that returned before sending a single LIFX packet.

        With a party's end scene set, `_restore` called the scene and
        returned, so a bulb mid-strobe strobed through the scene and past
        it — the one case where the room is *most* likely to be full of
        people wondering why the lights won't stop.
        """
        called = []
        run, engine = self._run_with(
            self._cues("cc" * 6), _end_scene="scene.late_night")
        run._restore = _noop  # the scene call itself is tested elsewhere
        run._restore_called = called
        asyncio.run(run.stop())
        self.assertEqual(["cc" * 6],
                         [serial for serial, _ in self._halts(engine)])

    def test_declining_the_restore_is_not_declining_the_stop(self):
        """`restore=False` says "leave the room as it is", not "keep going"."""
        run, engine = self._run_with(self._cues("dd" * 6))
        asyncio.run(run.stop(restore=False))
        self.assertEqual(["dd" * 6],
                         [serial for serial, _ in self._halts(engine)])

    def test_a_second_stop_does_not_speak_to_the_bulbs_again(self):
        run, engine = self._run_with(self._cues("ee" * 6))
        asyncio.run(run.stop())
        before = len(engine.sent)
        asyncio.run(run.stop())
        self.assertEqual(before, len(engine.sent),
                         "nothing is running any more, so there is nothing "
                         "to stop")

    def test_one_unreachable_bulb_does_not_strand_the_rest(self):
        run, engine = self._run_with(self._cues("aa" * 6, "bb" * 6))

        def only_bb(serial):
            if serial == "aa" * 6:
                raise KeyError(serial)
            return ("10.0.0.5", 56700)

        engine._addr = only_bb
        asyncio.run(run.stop())
        self.assertEqual(["bb" * 6],
                         [serial for serial, _ in self._halts(engine)],
                         "the reachable half of the room still stops")


class TestThePartyEndsOnce(unittest.TestCase):
    """The end scene belongs to the END of the run. It used to fire after
    every track — the good-night scene called between song one and song
    two of the evening it was configured to close — and the run state
    collapsed to idle between songs, hiding every Stop button and trim
    control while nudge/skip/autosync refused against `active: false`."""

    def _scenario(self):
        events = []
        persisted = []

        async def run_it():
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
            run._write_state()

            def loader(hash_hex):
                return {"cues": [{"t": 0.0, "ch": "ha",
                                  "service": "switch.turn_on", "data": {}}],
                        "title": hash_hex, "track_hash": hash_hex,
                        "duration_s": 0.05,
                        "media_content_id": "media-source://x/" + hash_hex}

            result = await run.start_party(
                ["h1", "h2"], media_player="media_player.k",
                loader=loader, name="test", end_scene="scene.good_night")
            assert result.get("ok"), result
            await run._task
            return run

        async def fake_verify(entity):
            return {"ok": True, "detail": ""}

        originals = (conductor.calibration_store.load,
                     conductor.ha_client.play_media,
                     conductor.ha_client.call_service,
                     conductor.ha_client.media_stop,
                     conductor.playback_check.wait_for_playing,
                     conductor.atomic_write.write_json,
                     conductor.POSITION_POLL_S)
        conductor.calibration_store.load = lambda *a, **k: {
            "effective_offset_ms": 0.0}
        conductor.ha_client.play_media = lambda entity, mid: (
            events.append(("play", mid.rsplit("/", 1)[-1])) or {})
        conductor.ha_client.call_service = lambda domain, service, data: (
            events.append((domain, data.get("entity_id"))) or {})
        conductor.ha_client.media_stop = lambda entity, **kw: {}
        conductor.playback_check.wait_for_playing = fake_verify
        conductor.atomic_write.write_json = \
            lambda path, payload: persisted.append(dict(payload))
        try:
            run = asyncio.run(run_it())
        finally:
            (conductor.calibration_store.load, conductor.ha_client.play_media,
             conductor.ha_client.call_service, conductor.ha_client.media_stop,
             conductor.playback_check.wait_for_playing,
             conductor.atomic_write.write_json,
             conductor.POSITION_POLL_S) = originals
        return run, events, persisted

    def test_the_end_scene_fires_once_after_the_last_track(self):
        run, events, _ = self._scenario()
        scenes = [e for e in events if e[0] == "scene"]
        self.assertEqual([("scene", "scene.good_night")], scenes,
                         "the end scene is the run's ending, once")
        # And it fired AFTER both tracks played, not between them.
        self.assertEqual(("scene", "scene.good_night"), events[-1])
        self.assertEqual([("play", "h1"), ("play", "h2")],
                         [e for e in events if e[0] == "play"])
        self.assertIsNone(run._end_scene, "the scene is consumed on use")

    def test_the_state_never_goes_idle_between_tracks(self):
        _, _, persisted = self._scenario()
        first_party = next(i for i, s in enumerate(persisted)
                           if s.get("status") == "party")
        inactive = [i for i, s in enumerate(persisted)
                    if i > first_party and not s.get("active")]
        self.assertEqual([len(persisted) - 1], inactive,
                         "only the evening's end writes an inactive state")


class TestAShowIsStoppableFromTheFirstSecond(unittest.TestCase):
    """`start()` used to write `active: false` and only flip it after the
    snapshot round and the play command — seconds, with a slow bulb — so
    the panel hid the Stop button for exactly the window someone most
    wants it. And a stop racing the play command found `_playing_on`
    unset and left the song playing through its own stop."""

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

    def test_active_before_the_play_command_returns(self):
        stopped = []

        async def run_it():
            run = self._conductor()
            started = threading.Event()

            def slow_play(entity, mid):
                started.set()
                time.sleep(0.2)
                return {}

            conductor.ha_client.play_media = slow_play
            result = await run.start(
                [{"t": 0.0, "ch": "ha", "service": "switch.turn_on",
                  "data": {}}],
                media_player="media_player.k",
                media_content_id="media-source://x/y.mp3",
                title="y", duration_s=0.05)
            assert result.get("ok"), result
            # The play command has not returned yet; the state must
            # already offer a Stop.
            state_early = dict(run.state)
            await asyncio.wait_for(
                asyncio.to_thread(started.wait, 1.0), 2.0)
            # A stop racing the play command still silences the player.
            await run.stop()
            return state_early

        originals = (conductor.calibration_store.load,
                     conductor.ha_client.play_media,
                     conductor.ha_client.media_stop,
                     conductor.playback_check.wait_for_playing,
                     conductor.atomic_write.write_json)

        async def fake_verify(entity):
            return {"ok": True, "detail": ""}

        conductor.calibration_store.load = lambda *a, **k: {
            "effective_offset_ms": 0.0}
        conductor.ha_client.media_stop = \
            lambda entity, **kw: stopped.append(entity) or {}
        conductor.playback_check.wait_for_playing = fake_verify
        conductor.atomic_write.write_json = lambda path, payload: None
        try:
            state_early = asyncio.run(run_it())
        finally:
            (conductor.calibration_store.load, conductor.ha_client.play_media,
             conductor.ha_client.media_stop,
             conductor.playback_check.wait_for_playing,
             conductor.atomic_write.write_json) = originals

        self.assertTrue(state_early.get("active"),
                        "a show that has been asked for is stoppable")
        self.assertEqual("starting", state_early.get("status"))
        self.assertIn("media_player.k", stopped,
                      "a stop racing the play command silences the player")


class TestStoppingStopsTheMusic(unittest.TestCase):
    """The speaker plays the track on its own, so it outlives every task
    the conductor cancels — exactly like a waveform outlives the cue that
    sent it. Stop used to end the cue list and put the lights back while
    the song carried on, which is what pressing Stop at 1am actually
    delivered."""

    def _conductor(self):
        engine = _FakeEngine()
        run = conductor.Conductor.__new__(conductor.Conductor)
        run.engine = engine
        run.clock = ShowClock()
        run._snapshot = {}
        run._end_scene = None
        run._driven = set()
        run._playing_on = None
        run._session_nudge_ms = 0.0
        run._task = run._poller = run._verify = None
        run.state = {}
        run._update_state = lambda **kw: run.state.update(kw)
        run._write_state = lambda **kw: None
        return run

    def test_an_interrupted_run_silences_the_player_it_started(self):
        run = self._conductor()
        run._playing_on = "media_player.kitchen"
        stopped = []
        original = conductor.ha_client.media_stop
        conductor.ha_client.media_stop = lambda e, **kw: stopped.append(e)
        try:
            asyncio.run(run.stop())
        finally:
            conductor.ha_client.media_stop = original
        self.assertEqual(["media_player.kitchen"], stopped)
        self.assertIsNone(run._playing_on, "stopped once, not again")

    def test_a_track_that_ended_by_itself_is_not_stopped(self):
        """_run waits out the track, so natural completion means the song
        is over — a media_stop then would clip the next track a party has
        already started, or stop something else the person began."""
        run = self._conductor()
        run._playing_on = None  # what natural completion leaves behind
        stopped = []
        original = conductor.ha_client.media_stop
        conductor.ha_client.media_stop = lambda e, **kw: stopped.append(e)
        try:
            asyncio.run(run.stop())
        finally:
            conductor.ha_client.media_stop = original
        self.assertEqual([], stopped)

    def test_an_unreachable_player_does_not_keep_the_lights_dancing(self):
        run = self._conductor()
        run._playing_on = "media_player.gone"
        run._driven = {"aa" * 6}

        def boom(entity, **kw):
            raise OSError("no route to host")

        original = conductor.ha_client.media_stop
        conductor.ha_client.media_stop = boom
        try:
            asyncio.run(run.stop())
        finally:
            conductor.ha_client.media_stop = original
        halts = [s for s, d in run.engine.sent
                 if packets.parse_header(d)["type"] == packets.SET_WAVEFORM]
        self.assertEqual(["aa" * 6], halts,
                         "the waveform halt still went out")


class TestTheNudge(unittest.TestCase):
    """The by-ear sync trim, and the sign is the whole trick."""

    def _running(self):
        run = conductor.Conductor.__new__(conductor.Conductor)
        run.engine = _FakeEngine()
        run.clock = ShowClock()
        run.clock.anchor(0.0, 0.0)
        run._session_nudge_ms = 0.0
        run.state = {"active": True, "media_player": "media_player.kitchen"}
        run._update_state = lambda **kw: run.state.update(kw)
        return run

    def test_a_nudge_needs_a_running_show(self):
        run = self._running()
        run.state["active"] = False
        self.assertIn("error", run.nudge(25))

    def test_nudges_accumulate_and_are_clamped(self):
        run = self._running()
        run.nudge(25)
        run.nudge(25)
        self.assertEqual(50.0, run.state["nudge_ms"])
        run.nudge(9999)
        self.assertEqual(250.0, run.state["nudge_ms"],
                         "a wild value is a typo, capped at 200 per press")

    def test_keep_flips_the_sign_into_adjust(self):
        """The clock anchors at play_call + effective_offset, and a nudge
        of +n behaves like an anchor n EARLIER — so keeping it means
        adjust -= n. Getting this backwards would double the error the
        person just corrected, in the other direction."""
        import tempfile
        from stores import calibration as calibration_store
        with tempfile.TemporaryDirectory() as tmp:
            original = calibration_store.CALIBRATION_DIR
            calibration_store.CALIBRATION_DIR = Path(tmp)
            try:
                calibration_store.add_run("media_player.kitchen", 500.0,
                                          method="mic")
                run = self._running()
                run.nudge(40)
                result = run.keep_nudge()
                self.assertTrue(result.get("ok"), result)
                profile = calibration_store.load("media_player.kitchen")
                self.assertEqual(-40.0, profile["adjust_ms"])
                self.assertEqual(460.0, profile["effective_offset_ms"],
                                 "lights 40ms earlier, permanently")
                self.assertEqual(0.0, run._session_nudge_ms,
                                 "kept means moved, not copied — leaving it "
                                 "would apply the trim twice next track")
            finally:
                calibration_store.CALIBRATION_DIR = original

    def test_keep_with_nothing_nudged_says_so(self):
        run = self._running()
        self.assertIn("error", run.keep_nudge())


class TestTheSyncProofPlaysTheMetronome(unittest.TestCase):
    """The Lab's demo button, un-hijacked.

    `load_show_for_track` preferred the compiled show whenever one
    existed, so the moment a track was choreographed the sync-proof
    button quietly started the whole show — a full party out of a button
    labelled as a demo, with no way back to the plain proof short of
    deleting the show it was proving."""

    def test_metronome_wins_even_when_a_show_is_compiled(self):
        import tempfile
        from analyzer import library
        with tempfile.TemporaryDirectory() as tmp:
            original = library.SHOWS_DIR
            library.SHOWS_DIR = Path(tmp)
            try:
                hash_hex = "ab" * 20
                (library.SHOWS_DIR / hash_hex).mkdir(parents=True)
                beats = [round(0.5 * b, 2) for b in range(1, 200)]
                library.save_analysis(hash_hex, {
                    "hash": hash_hex, "bpm": 120.0, "beats": beats,
                    "duration_s": beats[-1] + 3,
                    "file": "/media/music/x.mp3",
                    "tags": {"title": "X", "duration": beats[-1] + 3},
                })
                library.save_show(hash_hex, {"scenes": []}, {
                    "cues": [{"t": 0.0, "ch": "lifx", "serial": "aa" * 6,
                              "payload_b64": ""}],
                    "duration_s": beats[-1] + 3, "tier": "claude",
                })
                devices = {"aa" * 6: {"ip": "10.0.0.9", "rtt": {}}}
                compiled = conductor.load_show_for_track(
                    hash_hex, devices, 7)
                self.assertEqual("claude", compiled["tier"],
                                 "the ordinary start still gets the show")
                demo = conductor.load_show_for_track(
                    hash_hex, devices, 7, metronome=True)
                self.assertEqual("metronome", demo["tier"])
                for show in (compiled, demo):
                    self.assertEqual(hash_hex, show["track_hash"],
                                     "the identity the live playhead "
                                     "follows rides in both")
            finally:
                library.SHOWS_DIR = original
