"""The LIFX LAN engine: one UDP socket, discovery, probes, governed sends.

Design
------
One asyncio datagram endpoint on an ephemeral port serves everything —
replies come back to the socket that asked, so nothing needs to own
56700. Requests that expect a reply register a future keyed by the
sequence number stamped into the packet; the protocol's `datagram_received`
resolves it. Everything else is fire-and-forget, which is the playback
engine's whole posture.

The rate governor is a token bucket per device at the documented ceiling
(20 messages/second/device). Probes pace themselves and bypass it; scene
and demo sends go through it, so a compiler bug cannot flood a bulb.
"""
from __future__ import annotations

import asyncio
import math
import os
import socket
import time
from pathlib import Path
from typing import Any, Callable

from . import packets

# The panel directory is on sys.path (server.py's own directory, and the
# tests add it the same way), so the shared store writer imports flat.
import atomic_write

LIFX_PORT = packets.LIFX_PORT
DEVICES_FILE = Path(os.environ.get("BRIGHT_STATE", "/data")) / "lifx-devices.json"

# The LIFX-documented per-device ceiling.
MAX_MSGS_PER_SECOND = 20.0


class TokenBucket:
    """Per-device send budget. `acquire()` returns how long to wait.

    Pure arithmetic over an injectable clock so the tests can prove the
    ceiling without spending wall time.
    """

    def __init__(self, rate: float = MAX_MSGS_PER_SECOND,
                 burst: float = MAX_MSGS_PER_SECOND,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.rate = float(rate)
        self.burst = float(burst)
        self._clock = clock
        self._tokens = self.burst
        self._stamp = clock()

    def acquire(self) -> float:
        """Take one token; the return value is the delay (seconds) the
        caller owes before actually sending. 0.0 means send now.

        Tokens go negative on purpose: each over-budget acquire deepens the
        debt, so ten callers arriving in the same instant are told 50, 100,
        150…ms — not ten copies of 50ms that all land together.
        """
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._stamp) * self.rate)
        self._stamp = now
        self._tokens -= 1.0
        if self._tokens >= 0.0:
            return 0.0
        return -self._tokens / self.rate


def percentile(samples: list[float], pct: float) -> float:
    """Nearest-rank percentile (rank = ceil(P/100 x N), 1-based).
    Callers guarantee a non-empty list."""
    ordered = sorted(samples)
    rank = math.ceil(pct / 100.0 * len(ordered))
    return ordered[max(0, min(len(ordered) - 1, rank - 1))]


def rtt_stats(samples_ms: list[float], sent: int) -> dict:
    """The shape every probe result takes."""
    received = len(samples_ms)
    stats = {
        "sent": sent,
        "received": received,
        "loss": round(1.0 - received / sent, 4) if sent else 0.0,
    }
    if samples_ms:
        stats.update(
            min_ms=round(min(samples_ms), 2),
            p50_ms=round(percentile(samples_ms, 50), 2),
            p95_ms=round(percentile(samples_ms, 95), 2),
            max_ms=round(max(samples_ms), 2),
        )
    return stats


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, engine: "LifxEngine") -> None:
        self.engine = engine

    def datagram_received(self, data: bytes, addr) -> None:
        self.engine._on_datagram(data, addr)


class LifxEngine:
    """Owns the socket, the device registry and the pending-reply table."""

    def __init__(self) -> None:
        # A stable-ish nonzero source id tells our replies apart from other
        # clients on the same network segment.
        self.source = (os.getpid() & 0xFFFF) | 0x42420000
        self._sequence = 0
        self._transport: asyncio.DatagramTransport | None = None
        self._pending: dict[int, tuple[int, asyncio.Future]] = {}
        self._discovered: dict[str, dict] = {}
        self._discovering: asyncio.Event | None = None
        self._buckets: dict[str, TokenBucket] = {}
        self.devices: dict[str, dict] = self._load_devices()

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        # INADDR_ANY by default ("" is Python's spelling of it), and
        # deliberately: discovery is a LAN broadcast and the bulbs' replies
        # arrive on whichever interface faces them — this add-on runs
        # host_network for exactly that. Nothing listens here in the
        # service sense (only LIFX datagrams matching our own source id
        # are ever acted on); BRIGHT_LIFX_BIND pins a specific interface
        # address on a multi-homed host.
        sock.bind((os.environ.get("BRIGHT_LIFX_BIND", ""), 0))
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _Protocol(self), sock=sock)

    def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    # -- plumbing ----------------------------------------------------------
    def _next_sequence(self) -> int:
        self._sequence = (self._sequence + 1) & 0xFF
        return self._sequence

    def _on_datagram(self, data: bytes, addr) -> None:
        try:
            header = packets.parse_header(data)
        except ValueError:
            return  # not ours; the port hears whatever the LAN says
        if header["source"] != self.source:
            return
        if header["type"] == packets.STATE_SERVICE and self._discovering:
            info = packets.parse_state_service(header["payload"])
            if info["service"] == 1:  # UDP
                serial = header["target"].hex()
                self._discovered.setdefault(serial, {
                    "serial": serial,
                    "ip": addr[0],
                    "port": info["port"],
                })
            return
        pending = self._pending.pop(header["sequence"], None)
        if pending is None:
            return
        expect_type, future = pending
        if header["type"] != expect_type:
            # Wrong answer for that sequence — put it back for the right one.
            self._pending[header["sequence"]] = pending
            return
        if not future.done():
            future.set_result(header)

    def send(self, data: bytes, addr) -> None:
        if self._transport is None:
            raise RuntimeError("engine not started")
        self._transport.sendto(data, addr)

    async def send_governed(self, serial: str, data: bytes, addr) -> None:
        """A send that can never exceed the per-device ceiling."""
        bucket = self._buckets.setdefault(serial, TokenBucket())
        delay = bucket.acquire()
        if delay > 0:
            await asyncio.sleep(delay)
        self.send(data, addr)

    async def request(self, addr, packet: bytes, sequence: int,
                      expect_type: int, timeout: float = 1.0) -> dict | None:
        """Send and await the matching reply, or None on timeout."""
        future = asyncio.get_running_loop().create_future()
        self._pending[sequence] = (expect_type, future)
        self.send(packet, addr)
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(sequence, None)
            return None

    # -- device registry ---------------------------------------------------
    def _load_devices(self) -> dict[str, dict]:
        try:
            import json
            return {d["serial"]: d for d in
                    json.loads(DEVICES_FILE.read_text()).get("devices", [])}
        except (OSError, ValueError, KeyError):
            return {}

    def _save_devices(self) -> None:
        try:
            atomic_write.write_json(
                DEVICES_FILE,
                {"devices": sorted(self.devices.values(),
                                   key=lambda d: d.get("label") or d["serial"]),
                 "updated_at": time.time()},
                indent=2)
        except OSError:
            pass  # the registry is a cache; discovery rebuilds it

    def _addr(self, serial: str) -> tuple[str, int]:
        device = self.devices.get(serial)
        if not device:
            raise KeyError(f"unknown device {serial}; run discovery first")
        return (device["ip"], device.get("port") or LIFX_PORT)

    # -- operations ---------------------------------------------------------
    async def discover(self, timeout: float = 3.0,
                       broadcast: str = "255.255.255.255") -> list[dict]:
        """GetService broadcast, then label/version/color per responder."""
        await self.start()
        self._discovered = {}
        self._discovering = asyncio.Event()
        try:
            # Three spaced broadcasts: UDP broadcast is lossy by nature and
            # discovery is the one moment we cannot retry per-device.
            for _ in range(3):
                self.send(packets.get_service(source=self.source,
                                              sequence=self._next_sequence()),
                          (broadcast, LIFX_PORT))
                await asyncio.sleep(timeout / 3)
        finally:
            self._discovering = None

        found = list(self._discovered.values())
        for entry in found:
            addr = (entry["ip"], entry.get("port") or LIFX_PORT)
            target = bytes.fromhex(entry["serial"])
            hdr = dict(target=target, source=self.source)
            label = await self.request(
                addr, packets.get_label(sequence=self._next_sequence(), **hdr),
                self._sequence, packets.STATE_LABEL)
            version = await self.request(
                addr, packets.get_version(sequence=self._next_sequence(), **hdr),
                self._sequence, packets.STATE_VERSION)
            color = await self.request(
                addr, packets.get_color(sequence=self._next_sequence(), **hdr),
                self._sequence, packets.LIGHT_STATE)
            if label:
                entry["label"] = packets.parse_state_label(label["payload"])
            if version:
                entry.update(packets.parse_state_version(version["payload"]))
            if color:
                state = packets.parse_light_state(color["payload"])
                entry["power"] = state["power"]
                entry.setdefault("label", state["label"])
            entry["seen_at"] = time.time()
            # Keep anything a previous probe learned (rtt stats).
            previous = self.devices.get(entry["serial"], {})
            self.devices[entry["serial"]] = {**previous, **entry}
        self._save_devices()
        return sorted(self.devices.values(),
                      key=lambda d: d.get("label") or d["serial"])

    async def echo_probe(self, serial: str, count: int = 20,
                         gap: float = 0.06) -> dict:
        """Per-device RTT and loss, measured with EchoRequest.

        Self-paced under the ceiling (60ms gap ≈ 16/s), invisible on the
        bulb, and each echo carries a unique blob so a late reply cannot
        masquerade as the next one's answer.
        """
        await self.start()
        addr = self._addr(serial)
        target = bytes.fromhex(serial)
        samples: list[float] = []
        for i in range(count):
            blob = os.urandom(16) + i.to_bytes(4, "little")
            sequence = self._next_sequence()
            started = time.monotonic()
            reply = await self.request(
                addr,
                packets.echo_request(blob, target=target, source=self.source,
                                     sequence=sequence),
                sequence, packets.ECHO_RESPONSE, timeout=1.0)
            if reply and reply["payload"][:20] == blob:
                samples.append((time.monotonic() - started) * 1000.0)
            if i + 1 < count:
                await asyncio.sleep(gap)
        stats = rtt_stats(samples, count)
        device = self.devices.get(serial)
        if device is not None:
            device["rtt"] = {**stats, "measured_at": time.time()}
            self._save_devices()
        return stats

    async def rate_ramp(self, serial: str,
                        rates: tuple[int, ...] = (5, 10, 15, 20, 25, 30),
                        seconds_per_rate: float = 2.0) -> list[dict]:
        """What does this bulb actually sustain? Echo bursts at each rate,
        stopping early once loss goes past 25% — the point is the knee,
        not the wreckage past it."""
        await self.start()
        addr = self._addr(serial)
        target = bytes.fromhex(serial)
        results = []
        for rate in rates:
            count = max(1, int(rate * seconds_per_rate))
            gap = 1.0 / rate
            samples: list[float] = []
            for i in range(count):
                blob = os.urandom(16) + i.to_bytes(4, "little")
                sequence = self._next_sequence()
                started = time.monotonic()
                reply = await self.request(
                    addr,
                    packets.echo_request(blob, target=target,
                                         source=self.source,
                                         sequence=sequence),
                    sequence, packets.ECHO_RESPONSE,
                    timeout=min(1.0, gap * 4))
                if reply and reply["payload"][:20] == blob:
                    samples.append((time.monotonic() - started) * 1000.0)
                await asyncio.sleep(max(0.0, gap - (time.monotonic() - started)))
            stats = rtt_stats(samples, count)
            results.append({"rate_hz": rate, **stats})
            if stats["loss"] > 0.25:
                break
        return results

    async def waveform_demo(self, serial: str, bpm: float, seconds: float,
                            hue_deg: float = 200.0, saturation: float = 1.0,
                            brightness: float = 0.8) -> dict:
        """One SetWaveform datagram = `seconds` of beat-locked pulsing run
        ON the bulb. This is the sync trick made visible: whatever the
        network does after this send, the pulse keeps time."""
        await self.start()
        addr = self._addr(serial)
        target = bytes.fromhex(serial)
        period_ms = int(60000.0 / max(1.0, bpm))
        cycles = max(1.0, seconds * bpm / 60.0)
        packet = packets.set_waveform(
            transient=True,
            hue=int(hue_deg / 360.0 * 65535) & 0xFFFF,
            saturation=int(saturation * 65535),
            brightness=int(brightness * 65535),
            kelvin=3500,
            period_ms=period_ms,
            cycles=cycles,
            waveform=packets.WAVEFORM_SINE,
            target=target,
            source=self.source,
            sequence=self._next_sequence(),
        )
        # Sent twice, 30ms apart: fire-and-forget UDP with no retransmit,
        # and the message is idempotent — a duplicate restarts a pulse
        # nobody can see restarting.
        await self.send_governed(serial, packet, addr)
        await asyncio.sleep(0.03)
        await self.send_governed(serial, packet, addr)
        return {"period_ms": period_ms, "cycles": cycles}


def stats_for_report(devices: dict[str, dict]) -> list[dict[str, Any]]:
    """The device rows the Lab report renders."""
    rows = []
    for device in devices.values():
        rows.append({
            "serial": device.get("serial"),
            "label": device.get("label"),
            "ip": device.get("ip"),
            "product": device.get("product"),
            "rtt": device.get("rtt"),
        })
    return sorted(rows, key=lambda r: r.get("label") or r.get("serial") or "")
