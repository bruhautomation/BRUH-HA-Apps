#!/usr/bin/env python3
"""BRigt's LIFX layer and Lab plumbing.

The packet tests pin serialization byte-for-byte against the packet the
LIFX protocol documentation builds in its own "building a packet" example
(SetColor, green, 1024ms, tagged broadcast) — a vector from the protocol's
author, not from this code, so a serializer bug cannot certify itself.
"""

import asyncio
import os
import struct
import sys
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PANEL_DIR = os.path.join(BASE_DIR, "brigt", "panel")
# Appended, not inserted: brigt's panel shares module names with brAIn's
# (atomic_write, undo_store, server), and the front of sys.path would hand
# every later brain test brigt's copies.
if PANEL_DIR not in sys.path:
    sys.path.append(PANEL_DIR)

from lifx import packets  # noqa: E402
from lifx.engine import LifxEngine, TokenBucket, percentile, rtt_stats  # noqa: E402
import jobs  # noqa: E402


# The documented example: SetColor to all devices, hue 0x5555 (green),
# full saturation and brightness, 3500K, over 1024ms.
DOCUMENTED_SET_COLOR = bytes.fromhex(
    "31000034"                    # size 49, flags: tagged|addressable|1024
    "00000000"                    # source 0
    "0000000000000000"            # target: all devices
    "000000000000" "00" "00"      # reserved, flags2, sequence
    "0000000000000000"            # reserved
    "6600" "0000"                 # type 102, reserved
    "00"                          # payload: reserved
    "5555" "ffff" "ffff" "ac0d"   # HSBK: green, full, full, 3500K
    "00040000"                    # duration 1024ms
)


class TestPacketVectors(unittest.TestCase):
    def test_set_color_matches_the_documented_example(self):
        packet = packets.set_color(
            hue=0x5555, saturation=0xFFFF, brightness=0xFFFF, kelvin=3500,
            duration_ms=1024, tagged=True, source=0, sequence=0)
        self.assertEqual(DOCUMENTED_SET_COLOR.hex(), packet.hex())

    def test_header_parses_back(self):
        target = bytes.fromhex("d073d5123456")
        packet = packets.echo_request(b"ping", target=target,
                                      source=0x42421234, sequence=77)
        self.assertEqual(len(packet), 36 + 64)
        header = packets.parse_header(packet)
        self.assertEqual(packets.ECHO_REQUEST, header["type"])
        self.assertEqual(77, header["sequence"])
        self.assertEqual(0x42421234, header["source"])
        self.assertEqual(target, header["target"])
        self.assertEqual(b"ping", header["payload"][:4])

    def test_alien_datagrams_are_refused(self):
        with self.assertRaises(ValueError):
            packets.parse_header(b"short")
        # Right length, wrong protocol number.
        junk = bytearray(packets.get_service())
        junk[2] = 0x00
        junk[3] = 0x00
        with self.assertRaises(ValueError):
            packets.parse_header(bytes(junk))

    def test_waveform_payload_layout(self):
        packet = packets.set_waveform(
            transient=True, hue=1000, saturation=2000, brightness=3000,
            kelvin=3500, period_ms=500, cycles=16.0, skew_ratio=-100,
            waveform=packets.WAVEFORM_PULSE,
            target=bytes(6), source=1, sequence=1)
        self.assertEqual(len(packet), 36 + 21)
        payload = packets.parse_header(packet)["payload"]
        (_resv, transient, hue, sat, bri, kelvin, period, cycles,
         skew, shape) = struct.unpack("<BBHHHHIfhB", payload)
        self.assertEqual(1, transient)
        self.assertEqual((1000, 2000, 3000, 3500), (hue, sat, bri, kelvin))
        self.assertEqual(500, period)
        self.assertAlmostEqual(16.0, cycles)
        self.assertEqual(-100, skew)
        self.assertEqual(packets.WAVEFORM_PULSE, shape)

    def test_discovery_is_a_tagged_broadcast(self):
        header = packets.parse_header(packets.get_service(source=7))
        self.assertEqual(packets.GET_SERVICE, header["type"])
        self.assertEqual(b"\x00" * 6, header["target"])

    def test_reply_parsers(self):
        service = struct.pack("<BI", 1, 56700)
        self.assertEqual({"service": 1, "port": 56700},
                         packets.parse_state_service(service))
        label = b"Living lamp".ljust(32, b"\x00")
        self.assertEqual("Living lamp", packets.parse_state_label(label))
        version = struct.pack("<III", 1, 27, 0)
        self.assertEqual({"vendor": 1, "product": 27},
                         packets.parse_state_version(version))
        state = struct.pack("<HHHHhH32sQ", 100, 200, 300, 3500, 0, 65535,
                            b"Lamp".ljust(32, b"\x00"), 0)
        parsed = packets.parse_light_state(state)
        self.assertEqual(65535, parsed["power"])
        self.assertEqual("Lamp", parsed["label"])


class TestTokenBucket(unittest.TestCase):
    """The 20/s/device ceiling, proven without spending wall time."""

    def test_burst_is_free_then_the_rate_binds(self):
        clock = [0.0]
        bucket = TokenBucket(rate=20, burst=20, clock=lambda: clock[0])
        delays = [bucket.acquire() for _ in range(25)]
        self.assertEqual([0.0] * 20, delays[:20], "the burst should be free")
        self.assertTrue(all(d > 0 for d in delays[20:]),
                        "past the burst every send owes a wait")
        # Sum of owed delays for 5 extra sends at 20/s is 5 * 50ms.
        self.assertAlmostEqual(0.05 + 0.10 + 0.15 + 0.20 + 0.25,
                               sum(delays[20:]), places=6)

    def test_tokens_refill_with_time(self):
        clock = [0.0]
        bucket = TokenBucket(rate=20, burst=20, clock=lambda: clock[0])
        for _ in range(20):
            bucket.acquire()
        clock[0] = 1.0  # a second later the full burst is back
        self.assertEqual(0.0, bucket.acquire())

    def test_a_sustained_flood_averages_the_ceiling(self):
        clock = [0.0]
        bucket = TokenBucket(rate=20, burst=20, clock=lambda: clock[0])
        sent_at = []
        for _ in range(100):
            delay = bucket.acquire()
            clock[0] += delay  # the caller sleeps what it owes
            sent_at.append(clock[0])
        # 100 sends: 20 burst + 80 paced at 20/s = 4 seconds.
        self.assertAlmostEqual(4.0, sent_at[-1], places=6)


class TestStats(unittest.TestCase):
    def test_percentiles(self):
        samples = [float(v) for v in range(1, 101)]
        self.assertEqual(50.0, percentile(samples, 50))
        self.assertEqual(95.0, percentile(samples, 95))
        self.assertEqual(1.0, percentile(samples, 0))
        self.assertEqual(100.0, percentile(samples, 100))

    def test_rtt_stats_carries_loss(self):
        stats = rtt_stats([10.0, 20.0, 30.0], sent=4)
        self.assertEqual(4, stats["sent"])
        self.assertEqual(3, stats["received"])
        self.assertEqual(0.25, stats["loss"])
        self.assertEqual(20.0, stats["p50_ms"])

    def test_total_loss_reports_no_percentiles(self):
        stats = rtt_stats([], sent=5)
        self.assertEqual(1.0, stats["loss"])
        self.assertNotIn("p50_ms", stats)


class TestEngineDispatch(unittest.TestCase):
    """Reply routing without a socket: feed datagrams straight in."""

    def _engine(self):
        engine = LifxEngine()
        engine.source = 0x42420001
        return engine

    def test_a_matching_reply_resolves_the_future(self):
        async def scenario():
            engine = self._engine()
            future = asyncio.get_running_loop().create_future()
            engine._pending[5] = (packets.ECHO_RESPONSE, future)
            reply = packets.build(packets.ECHO_RESPONSE, b"x" * 64,
                                  target=bytes(6), source=engine.source,
                                  sequence=5)
            engine._on_datagram(reply, ("10.0.0.9", 56700))
            return await asyncio.wait_for(future, 1)

        header = asyncio.run(scenario())
        self.assertEqual(packets.ECHO_RESPONSE, header["type"])

    def test_another_clients_traffic_is_ignored(self):
        async def scenario():
            engine = self._engine()
            future = asyncio.get_running_loop().create_future()
            engine._pending[5] = (packets.ECHO_RESPONSE, future)
            foreign = packets.build(packets.ECHO_RESPONSE, b"x" * 64,
                                    target=bytes(6), source=0xDEAD,
                                    sequence=5)
            engine._on_datagram(foreign, ("10.0.0.9", 56700))
            return future.done()

        self.assertFalse(asyncio.run(scenario()))

    def test_a_wrong_typed_reply_does_not_burn_the_pending_slot(self):
        """An Acknowledgement arriving for a sequence that awaits an echo
        must not consume the future — the real answer is still coming."""
        async def scenario():
            engine = self._engine()
            future = asyncio.get_running_loop().create_future()
            engine._pending[5] = (packets.ECHO_RESPONSE, future)
            ack = packets.build(packets.ACKNOWLEDGEMENT, b"",
                                target=bytes(6), source=engine.source,
                                sequence=5)
            engine._on_datagram(ack, ("10.0.0.9", 56700))
            self.assertFalse(future.done())
            echo = packets.build(packets.ECHO_RESPONSE, b"y" * 64,
                                 target=bytes(6), source=engine.source,
                                 sequence=5)
            engine._on_datagram(echo, ("10.0.0.9", 56700))
            return await asyncio.wait_for(future, 1)

        header = asyncio.run(scenario())
        self.assertEqual(b"y" * 64, header["payload"])


class TestJobs(unittest.TestCase):
    def setUp(self):
        jobs.clear()

    def test_start_await_done(self):
        async def scenario():
            job = jobs.start("probe", self._quick(41))
            self.assertEqual("running", job["status"])
            await job["_task"]
            return jobs.get(job["id"])

        finished = asyncio.run(scenario())
        self.assertEqual("done", finished["status"])
        self.assertEqual(41, finished["result"])
        self.assertNotIn("_task", finished, "internals must not serialize")

    def test_a_second_start_of_the_same_name_is_refused(self):
        async def scenario():
            gate = asyncio.Event()

            async def waits():
                await gate.wait()
                return "first"

            first = jobs.start("probe", waits)
            second = jobs.start("probe", waits)
            gate.set()
            await first["_task"]
            return first, second

        first, second = asyncio.run(scenario())
        self.assertTrue(second.get("already"))
        self.assertEqual(first["id"], second["id"])

    def test_an_error_is_the_jobs_result_not_a_crash(self):
        async def scenario():
            async def explodes():
                raise RuntimeError("bulb on fire")

            job = jobs.start("probe", explodes)
            await job["_task"]
            return jobs.get(job["id"])

        finished = asyncio.run(scenario())
        self.assertEqual("error", finished["status"])
        self.assertIn("bulb on fire", finished["error"])

    @staticmethod
    def _quick(value):
        async def factory():
            return value
        return factory


class _FakeHA:
    """Enough of the Core API for the latency probe: states and a toggle
    whose effect lands only after a configurable number of polls."""

    def __init__(self, initial="off", flips_after_polls=3):
        self.state = initial
        self.flips_after = flips_after_polls
        self._pending = None
        self.calls = []

    def opener(self, request, timeout=None):
        import io
        import json as _json

        url = request.full_url
        self.calls.append((request.get_method(), url))
        if "/services/" in url:
            self._pending = {"target": "off" if self.state == "on" else "on",
                             "polls_left": self.flips_after}
            body = b"[]"
        else:  # a state read
            if self._pending is not None:
                self._pending["polls_left"] -= 1
                if self._pending["polls_left"] <= 0:
                    self.state = self._pending["target"]
                    self._pending = None
            body = _json.dumps({"state": self.state}).encode()

        class _Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Response(body)


class TestHaLatencyProbe(unittest.TestCase):
    def setUp(self):
        import ha_client
        self.ha_client = ha_client
        self._token = ha_client.SUPERVISOR_TOKEN
        ha_client.SUPERVISOR_TOKEN = "test-token"

    def tearDown(self):
        self.ha_client.SUPERVISOR_TOKEN = self._token

    def test_probe_measures_and_comes_home(self):
        fake = _FakeHA(initial="off", flips_after_polls=2)
        clock = [0.0]

        def fake_sleep(seconds):
            clock[0] += seconds

        result = self.ha_client.latency_probe(
            "switch.laser", rounds=4, opener=fake.opener, poll_s=0.05,
            timeout_s=5.0, clock=lambda: clock[0], sleep=fake_sleep)
        self.assertEqual(4, result["rounds"])
        self.assertEqual(4, len(result["samples_ms"]))
        self.assertEqual(0, result["timeouts"])
        self.assertIn("p50_ms", result)
        # Even rounds: the switch ends where it started.
        self.assertEqual("off", fake.state)

    def test_odd_rounds_are_made_even(self):
        fake = _FakeHA(initial="on", flips_after_polls=1)
        clock = [0.0]
        result = self.ha_client.latency_probe(
            "switch.laser", rounds=3, opener=fake.opener, poll_s=0.05,
            timeout_s=5.0, clock=lambda: clock[0],
            sleep=lambda s: clock.__setitem__(0, clock[0] + s))
        self.assertEqual(4, result["rounds"])
        self.assertEqual("on", fake.state)

    def test_only_togglable_domains_are_probed(self):
        result = self.ha_client.latency_probe("media_player.kitchen")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
