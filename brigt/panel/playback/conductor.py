"""The conductor: one show at a time, from a cue list and a clock.

At show time nothing thinks. Cues were compiled earlier (each carrying its
own lead time), the clock was anchored at play-command + calibrated
offset, and this loop just sleeps to the next cue's send moment and puts
bytes on the wire. LIFX cues go out our own UDP socket; HA cues (the aux
lights) go through Core with their lead already accounting for how slow
that path measured.

The metronome show lives here too: beat pulses straight from a track's
analysis, no director involved. It exists to prove sync end-to-end before
any choreography does — if the metronome misses the beat, no show script
was going to fix it.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from pathlib import Path
from typing import Any

import atomic_write
import ha_client
import playback_check
from analyzer import library
from lifx import packets
from playback.clock import ShowClock
from playback.drift import DriftEstimator
from stores import calibration as calibration_store

log = logging.getLogger("brigt.conductor")

STATE_FILE = Path(os.environ.get("BRIGT_STATE", "/data")) / "state.json"

POSITION_POLL_S = 5.0
DEFAULT_LIFX_LEAD_S = 0.005


class Conductor:
    """Owns the current run. One at a time — a second `start` stops the
    first, because two shows on one set of lights is neither."""

    def __init__(self, engine) -> None:
        self.engine = engine
        self.clock = ShowClock()
        self._task: asyncio.Task | None = None
        self._poller: asyncio.Task | None = None
        self._verify: asyncio.Task | None = None
        self._snapshot: dict[str, dict] = {}
        self.state: dict[str, Any] = {"status": "idle"}
        self._write_state()

    # -- state the bridge mirrors to HA -------------------------------------
    def _write_state(self, **extra) -> None:
        self.state = {"status": "idle", **extra} if extra else {"status": "idle"}
        try:
            atomic_write.write_json(STATE_FILE, self.state)
        except OSError:
            log.warning("could not persist show state")

    def _update_state(self, **fields) -> None:
        self.state.update(fields)
        try:
            atomic_write.write_json(STATE_FILE, self.state)
        except OSError:
            pass  # the state file is a mirror; the run itself is unaffected

    # -- lifecycle -----------------------------------------------------------
    async def _play_one(self, cues: list[dict], *, media_player: str,
                        media_content_id: str, title: str,
                        duration_s: float, offset_ms: float,
                        status: str = "playing") -> None:
        """One track, start to restored lights. Awaited inline by the party
        loop; wrapped in a task by single-show start()."""
        await self.engine.start()
        await self._take_snapshot(cues)
        play_call = time.monotonic()
        result = await asyncio.to_thread(
            ha_client.play_media, media_player, media_content_id)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"])
        self.clock.anchor(play_call, offset_ms / 1000.0)
        self._update_state(status=status, track=title,
                           media_player=media_player, position_s=0.0)
        # Home Assistant accepting the command is not the speaker playing:
        # it resolves the media, signs a URL and hands it over, and the
        # speaker fetches it afterwards, on its own, over the network. The
        # show cannot wait to find out — the clock was anchored at the play
        # command — but a room that stays silent while the panel says
        # "Running" is exactly the failure this watches for.
        if self._verify is not None and not self._verify.done():
            self._verify.cancel()
        self._verify = asyncio.create_task(self._verify_playing(media_player))
        profile = calibration_store.load(media_player)
        if (profile.get("position_attr") or {}).get("reliable"):
            self._poller = asyncio.create_task(self._poll_position(media_player))
        try:
            await self._run(sorted(cues, key=self._send_time), duration_s)
        finally:
            if self._poller is not None:
                self._poller.cancel()
                self._poller = None

    async def _verify_playing(self, media_player: str) -> None:
        try:
            step = await playback_check.wait_for_playing(media_player)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a watcher must not end a show
            # Flattened, like everything else logged from outside: an
            # exception's text is whatever raised it, and a newline in a
            # logged value is that value writing its own log lines.
            log.warning("could not check whether %s started: %s",
                        playback_check.flat(media_player),
                        playback_check.flat(exc))
            return
        if step["ok"]:
            return
        log.warning("%s", playback_check.flat(step["detail"]))
        self._update_state(playback_warning=step["detail"])

    @staticmethod
    def _calibrated_offset(media_player: str) -> float | None:
        return calibration_store.load(media_player).get("effective_offset_ms")

    async def start(self, cues: list[dict], *, media_player: str,
                    media_content_id: str, title: str,
                    duration_s: float) -> dict:
        await self.stop(restore=True)
        offset_ms = self._calibrated_offset(media_player)
        if offset_ms is None:
            return {"ok": False,
                    "error": f"{media_player} has never been calibrated — "
                             "run the Calibrate tab first"}
        self._write_state()
        self._task = asyncio.create_task(self._play_one(
            cues, media_player=media_player,
            media_content_id=media_content_id, title=title,
            duration_s=duration_s, offset_ms=offset_ms))
        self._task.add_done_callback(self._show_ended)
        return {"ok": True, "offset_ms": offset_ms, "cues": len(cues)}

    def _show_ended(self, task: asyncio.Task) -> None:
        """A show that could not start has to say so somewhere.

        `start()` answers the request the moment the task exists — a show
        runs for minutes and a request cannot — so everything that fails
        afterwards fails out of sight. A play command the media player
        refuses raises in `_play_one` before the cue loop is ever reached,
        and the panel went on reporting "Running: 412 cues" over a dark
        room: the only trace was asyncio's own "Task exception was never
        retrieved", logged whenever the task was garbage collected.

        The state file is what the panel polls and what the HA sensor
        reads, so the error goes there. Restoring is the other half of an
        ending nobody watched — the snapshot was taken before the play
        command, and without this the lights keep whatever the last cue
        left them at.
        """
        if task.cancelled():
            return
        error = task.exception()
        if error is None:
            return
        log.error("show stopped: %s", error)
        self._update_state(status="error", error=str(error))
        asyncio.get_running_loop().create_task(self._restore_snapshot())

    async def start_party(self, queue: list[str], *, media_player: str,
                          loader, preparer=None) -> dict:
        """The autonomous evening: a queue of track hashes, each played
        with its own show and its own anchor. `loader(hash)` returns the
        playable show; `preparer(hash)` (optional, blocking — run in a
        thread) compiles the NEXT track's show while the current one
        plays, so a Claude-designed show is ready by the time it's needed.
        """
        await self.stop(restore=True)
        offset_ms = self._calibrated_offset(media_player)
        if offset_ms is None:
            return {"ok": False,
                    "error": f"{media_player} has never been calibrated — "
                             "run the Calibrate tab first"}
        if not queue:
            return {"ok": False, "error": "no analyzed tracks to play"}

        async def _party() -> None:
            for index, hash_hex in enumerate(queue):
                show = await asyncio.to_thread(loader, hash_hex)
                if not show or not show.get("cues") \
                        or not show.get("media_content_id"):
                    continue
                if preparer is not None and index + 1 < len(queue):
                    # Fire-and-forget: a failed prepare means that track
                    # simply plays its floor show.
                    asyncio.create_task(
                        asyncio.to_thread(preparer, queue[index + 1]))
                self._update_state(status="party", queue_left=len(queue) - index)
                try:
                    await self._play_one(
                        show["cues"], media_player=media_player,
                        media_content_id=show["media_content_id"],
                        title=show["title"],
                        duration_s=show["duration_s"],
                        offset_ms=self._calibrated_offset(media_player)
                                  or offset_ms,
                        status="party")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — next track, not the night
                    log.warning("party: %s failed: %s", show.get("title"), exc)
                await asyncio.sleep(1.5)  # breath between tracks
            self._write_state()

        self._write_state()
        self._update_state(status="party", queue_left=len(queue))
        self._task = asyncio.create_task(_party())
        return {"ok": True, "queue": len(queue), "offset_ms": offset_ms}

    async def stop(self, restore: bool = True) -> dict:
        for task in (self._task, self._poller, self._verify):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = self._poller = self._verify = None
        if restore and self._snapshot:
            await self._restore_snapshot()
        self._write_state()
        return {"ok": True}

    # -- the loop ------------------------------------------------------------
    @staticmethod
    def _send_time(cue: dict) -> float:
        return cue["t"] - cue.get("lead_ms", 0) / 1000.0

    async def _run(self, cues: list[dict], duration_s: float) -> None:
        try:
            for cue in cues:
                wait = self.clock.sleep_needed(self._send_time(cue))
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    await self._dispatch(cue)
                except Exception as exc:  # noqa: BLE001 — one cue, not the show
                    log.warning("cue at %.2fs failed: %s", cue["t"], exc)
                self._update_state(position_s=round(max(0.0, self.clock.now()), 1))
            # Let the track play out, then put the room back.
            tail = self.clock.sleep_needed(duration_s)
            if tail > 0:
                await asyncio.sleep(tail)
            await self._restore_snapshot()
            self._write_state()
        except asyncio.CancelledError:
            raise

    async def _dispatch(self, cue: dict) -> None:
        if cue.get("ch") == "lifx":
            serial = cue["serial"]
            addr = self.engine._addr(serial)
            payload = base64.b64decode(cue["payload_b64"])
            # Stamp the live sequence number into the pre-built packet.
            packet = bytearray(payload)
            packet[23] = self.engine._next_sequence()
            await self.engine.send_governed(serial, bytes(packet), addr)
            if cue.get("resend"):
                # Scene-level cues are idempotent; a duplicate 30ms later
                # survives the loss fire-and-forget can't see.
                await asyncio.sleep(0.03)
                packet[23] = self.engine._next_sequence()
                await self.engine.send_governed(serial, bytes(packet), addr)
        elif cue.get("ch") == "ha":
            domain, service = cue["service"].split(".", 1)
            await asyncio.to_thread(
                ha_client.call_service, domain, service, cue.get("data") or {})

    async def _poll_position(self, media_player: str) -> None:
        estimator = DriftEstimator()
        while True:
            await asyncio.sleep(POSITION_POLL_S)
            snapshot = await asyncio.to_thread(
                ha_client.position_snapshot, media_player)
            position = snapshot.get("media_position")
            if not isinstance(position, (int, float)):
                continue
            try:
                correction = estimator.report(float(position), self.clock.now())
            except RuntimeError:
                continue
            if correction is not None:
                log.info("drift correction: %.0fms", correction * 1000)
                self.clock.add_drift(correction)

    # -- snapshot / restore ----------------------------------------------------
    async def _take_snapshot(self, cues: list[dict]) -> None:
        """What every LIFX fixture in the show looks like before we touch
        it, so stop puts the room back instead of leaving party colors."""
        self._snapshot = {}
        serials = {cue["serial"] for cue in cues if cue.get("ch") == "lifx"}
        for serial in serials:
            try:
                addr = self.engine._addr(serial)
            except KeyError:
                continue
            reply = await self.engine.request(
                addr,
                packets.get_color(target=bytes.fromhex(serial),
                                  source=self.engine.source,
                                  sequence=self.engine._next_sequence()),
                self.engine._sequence, packets.LIGHT_STATE)
            if reply:
                self._snapshot[serial] = packets.parse_light_state(reply["payload"])

    async def _restore_snapshot(self) -> None:
        for serial, state in self._snapshot.items():
            try:
                addr = self.engine._addr(serial)
            except KeyError:
                continue
            packet = packets.set_color(
                state["hue"], state["saturation"], state["brightness"],
                state["kelvin"], 800,
                target=bytes.fromhex(serial), source=self.engine.source,
                sequence=self.engine._next_sequence())
            await self.engine.send_governed(serial, packet, addr)
        self._snapshot = {}


# ---------------------------------------------------------------------------
# The metronome show — sync, proven before choreography exists
# ---------------------------------------------------------------------------
def metronome_cues(analysis: dict, devices: dict[str, dict],
                   source: int) -> list[dict]:
    """Beat pulses for every known bulb, straight from the analysis.

    One SetWaveform per fixture every 8 beats (the bulb runs the beats in
    between), phase-anchored at the send moment — steady state is well
    under 1 msg/s/device against the 20/s ceiling.
    """
    beats = analysis.get("beats") or []
    if len(beats) < 8:
        return []
    intervals = sorted(b - a for a, b in zip(beats, beats[1:]))
    period_ms = int(intervals[len(intervals) // 2] * 1000)
    cues: list[dict] = []
    for serial, device in devices.items():
        lead_ms = ((device.get("rtt") or {}).get("p50_ms") or
                   DEFAULT_LIFX_LEAD_S * 2000) / 2.0
        # A dim warm base so pulses have somewhere visible to come from.
        base = packets.set_color(
            hue=int(30 / 360 * 65535), saturation=int(0.35 * 65535),
            brightness=int(0.25 * 65535), kelvin=2700, duration_ms=400,
            target=bytes.fromhex(serial), source=source)
        cues.append({"t": 0.0, "ch": "lifx", "serial": serial,
                     "lead_ms": lead_ms, "resend": True,
                     "payload_b64": base64.b64encode(base).decode(),
                     "desc": "base"})
        for start in beats[::8]:
            pulse = packets.set_waveform(
                transient=True,
                hue=int(200 / 360 * 65535), saturation=int(0.9 * 65535),
                brightness=int(0.9 * 65535), kelvin=3500,
                period_ms=period_ms, cycles=8.0,
                waveform=packets.WAVEFORM_SINE,
                target=bytes.fromhex(serial), source=source)
            cues.append({"t": round(start, 4), "ch": "lifx", "serial": serial,
                         "lead_ms": lead_ms,
                         "payload_b64": base64.b64encode(pulse).decode(),
                         "desc": "beat pulse x8"})
    return cues


def media_content_id_for(analysis: dict, media_root: str = "/media") -> str | None:
    """The media-source URI HA players accept for a local file."""
    file = analysis.get("file") or ""
    if not file.startswith(media_root + "/"):
        return None
    relative = file[len(media_root) + 1:]
    return f"media-source://media_source/local/{relative}"


def peak_rate_per_device(cues: list[dict]) -> float:
    """Worst messages-per-second any single device sees — the compiler-
    side check that the 20/s ceiling cannot be hit at runtime."""
    worst = 0.0
    by_device: dict[str, list[float]] = {}
    for cue in cues:
        if cue.get("ch") == "lifx":
            sends = 2 if cue.get("resend") else 1
            by_device.setdefault(cue["serial"], []).extend(
                [cue["t"]] * sends)
    for times in by_device.values():
        times.sort()
        for i in range(len(times)):
            j = i
            while j + 1 < len(times) and times[j + 1] - times[i] < 1.0:
                j += 1
            worst = max(worst, float(j - i + 1))
    return worst


def load_show_for_track(hash_hex: str, devices: dict[str, dict],
                        source: int) -> dict | None:
    """A compiled show when the director has made one; the metronome show
    otherwise, so 'start_show' always has something honest to play."""
    analysis = library.load_analysis(hash_hex)
    if analysis is None:
        return None
    title = (analysis.get("tags") or {}).get("title") or hash_hex[:8]
    duration = (float((analysis.get("tags") or {}).get("duration") or 0)
                or (analysis["beats"][-1] + 5 if analysis.get("beats") else 60))
    compiled = library.load_show(hash_hex)
    if compiled and compiled.get("cues"):
        return {
            "cues": compiled["cues"],
            "title": title,
            "duration_s": float(compiled.get("duration_s") or duration),
            "media_content_id": media_content_id_for(analysis),
            "tier": compiled.get("tier"),
        }
    return {
        "cues": metronome_cues(analysis, devices, source),
        "title": title,
        "duration_s": duration,
        "media_content_id": media_content_id_for(analysis),
        "tier": "metronome",
    }
