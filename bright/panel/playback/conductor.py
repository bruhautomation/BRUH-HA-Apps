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
import media_source
import playback_check
from analyzer import library
from lifx import packets
from playback.clock import ShowClock
from playback.drift import DriftEstimator
from stores import calibration as calibration_store

log = logging.getLogger("bright.conductor")

STATE_FILE = Path(os.environ.get("BRIGHT_STATE", "/data")) / "state.json"

POSITION_POLL_S = 5.0
DEFAULT_LIFX_LEAD_S = 0.005


class Conductor:
    """Owns the current run. One at a time — a second `start` stops the
    first, because two shows on one set of lights is neither."""

    # Declared on the class as well as set in __init__: "no end scene" is
    # the meaning of an unset one, and a default that only exists inside
    # __init__ makes that true of a fully built conductor and of nothing
    # else.
    _end_scene: str | None = None

    # Same reasoning, and it is load-bearing on the very first stop: a
    # conductor that has never run still has to answer `stop()` without
    # raising, and a set that only exists once a show has taken a snapshot
    # is not a set a stop path can read.
    _driven: set[str] = frozenset()  # type: ignore[assignment]
    _playing_on: str | None = None

    def __init__(self, engine) -> None:
        self.engine = engine
        self.clock = ShowClock()
        self._task: asyncio.Task | None = None
        self._poller: asyncio.Task | None = None
        self._verify: asyncio.Task | None = None
        self._snapshot: dict[str, dict] = {}
        self._end_scene: str | None = None
        self._driven: set[str] = set()
        # The player a play command was sent to, while its track is still
        # meant to be playing. Cleared on natural completion — the track
        # ended by itself and there is nothing left to silence — so stop()
        # only quiets a speaker this run actually started and interrupted.
        self._playing_on: str | None = None
        # By-ear trim, in milliseconds, accumulated across the run.
        # Positive = the lights fire earlier. It rides into every new
        # track's anchor so a party stays in tune once dialed, and it is
        # what "Keep" folds into the player's calibration.
        self._session_nudge_ms = 0.0
        self.state: dict[str, Any] = {"status": "idle"}
        self._write_state()

    # -- state the bridge mirrors to HA -------------------------------------
    def _write_state(self, **extra) -> None:
        # `active` is what the panel hides its Stop button on, and what the
        # integration's binary sensor reports. It is written here, beside
        # the status, so "idle" can never arrive still claiming to be
        # running — the two used to be a status string and a guess.
        base = {"status": "idle", "active": False, "lights_busy": False,
                "cues_sent": 0, "cues_total": 0}
        self.state = {**base, **extra}
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
                        status: str = "playing",
                        track_hash: str = "") -> None:
        """One track, start to restored lights. Awaited inline by the party
        loop; wrapped in a task by single-show start()."""
        await self.engine.start()
        await self._take_snapshot(cues)
        play_call = time.monotonic()
        result = await asyncio.to_thread(
            ha_client.play_media, media_player, media_content_id)
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"])
        self._playing_on = media_player
        # The session nudge is baked into the anchor rather than slewed in
        # afterwards: a new track must start already in tune, and the slew
        # (8ms per second, chosen so a mid-track correction is invisible)
        # would spend the first seconds of every song drifting back to
        # where the last one had been dialed.
        self.clock.anchor(play_call,
                          (offset_ms - self._session_nudge_ms) / 1000.0)
        # `track` is the title, for a person; `track_hash` is the identity,
        # for anything that has to decide whether the show it is looking at
        # is the one that is running. Two tracks can share a title.
        self._update_state(status=status, track=title, active=True,
                           track_hash=track_hash,
                           lights_busy=True, cues_total=len(cues),
                           cues_sent=0, media_player=media_player,
                           position_s=0.0)
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
            # Natural completion: _run waited out the track, so the song is
            # over and there is nothing to silence. Only an INTERRUPTED run
            # leaves this set, which is what lets stop() tell the two apart.
            self._playing_on = None
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
                    duration_s: float, end_scene: str | None = None,
                    track_hash: str = "") -> dict:
        await self.stop(restore=True)
        self.set_end_scene(end_scene)
        offset_ms = self._calibrated_offset(media_player)
        if offset_ms is None:
            return {"ok": False,
                    "error": f"{media_player} has never been calibrated — "
                             "run the Calibrate tab first"}
        self._write_state()
        self._task = asyncio.create_task(self._play_one(
            cues, media_player=media_player,
            media_content_id=media_content_id, title=title,
            duration_s=duration_s, offset_ms=offset_ms,
            track_hash=track_hash))
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
        asyncio.get_running_loop().create_task(self._restore())

    async def start_party(self, queue: list[str], *, media_player: str,
                          loader, preparer=None, name: str | None = None,
                          end_scene: str | None = None,
                          allow: set[str] | None = None) -> dict:
        """The autonomous evening: a queue of track hashes, each played
        with its own show and its own anchor. `loader(hash)` returns the
        playable show; `preparer(hash)` (optional, blocking — run in a
        thread) compiles the NEXT track's show while the current one
        plays, so a Claude-designed show is ready by the time it's needed.
        """
        await self.stop(restore=True)
        self.set_end_scene(end_scene)
        offset_ms = self._calibrated_offset(media_player)
        if offset_ms is None:
            return {"ok": False,
                    "error": f"{media_player} has never been calibrated — "
                             "run the Calibrate tab first"}
        if not queue:
            return {"ok": False, "error": "no analyzed tracks to play"}

        def _titles(hashes: list[str]) -> list[str]:
            """Names for the queue's next few tracks — what the Party tab
            renders as "up next". Titles rather than hashes, because a
            party screen is read across a room; capped, because "and 31
            more" is what the count is for."""
            names = []
            for upcoming in hashes[:5]:
                analysis = library.load_analysis(upcoming)
                names.append(((analysis or {}).get("tags") or {})
                             .get("title") or upcoming[:8])
            return names

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
                up_next = await asyncio.to_thread(_titles, queue[index + 1:])
                self._update_state(status="party", active=True,
                                   party=name, up_next=up_next,
                                   allow=sorted(allow) if allow else [],
                                   queue_left=len(queue) - index)
                try:
                    await self._play_one(
                        filter_cues(show["cues"], allow),
                        media_player=media_player,
                        media_content_id=show["media_content_id"],
                        title=show["title"],
                        duration_s=show["duration_s"],
                        offset_ms=self._calibrated_offset(media_player)
                                  or offset_ms,
                        status="party",
                        track_hash=show.get("track_hash", ""))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 — next track, not the night
                    log.warning("party: %s failed: %s", show.get("title"), exc)
                await asyncio.sleep(1.5)  # breath between tracks
            self._write_state()

        self._write_state()
        self._update_state(status="party", active=True, party=name,
                           queue_left=len(queue))
        self._task = asyncio.create_task(_party())
        return {"ok": True, "queue": len(queue), "offset_ms": offset_ms,
                "party": name}

    async def run_cues(self, cues: list[dict], *, duration_s: float,
                       label: str) -> dict:
        """A cue list with no music behind it — the Effects tab's "run it
        on the real lights".

        Same loop, same snapshot-and-restore, anchored at now instead of
        at a play command. A preview on a screen is a drawing of what an
        effect should do; this is the effect, on the bulbs in the room,
        which is the only place some of these questions get answered.
        """
        await self.stop(restore=True)
        self.set_end_scene(None)
        if not cues:
            return {"ok": False, "error": "that effect drives no lights — "
                                          "check its selection"}
        await self.engine.start()
        await self._take_snapshot(cues)
        self.clock.anchor(time.monotonic(), 0.0)
        self._write_state()
        self._update_state(status="preview", active=True, lights_busy=True,
                           track=label, cues_total=len(cues), cues_sent=0)
        self._task = asyncio.create_task(
            self._run(sorted(cues, key=self._send_time), duration_s))
        self._task.add_done_callback(self._show_ended)
        return {"ok": True, "cues": len(cues), "duration_s": duration_s}

    def set_end_scene(self, entity_id: str | None) -> None:
        """The scene to call instead of restoring, for the run in progress.

        Restoring puts every light back exactly as the show found it,
        which is right when the show interrupted an evening and wrong
        when it *was* the evening: at 1am nobody wants the lounge back at
        4pm's brightness. A party that names a scene gets that scene, and
        the snapshot is dropped rather than applied afterwards — two
        answers to "put the room back" would fight, and the configured
        one wins.
        """
        self._end_scene = entity_id or None

    async def _halt_waveforms(self) -> None:
        """End every routine still running on a bulb of this show.

        First, on every path out of a show, and deliberately before the
        room is put back: a waveform is executed by the bulb, so it
        outlives the cue list, the conductor and the add-on itself. The
        old stop sent `SetColor` to the bulbs it had snapshotted, which
        neither ends the routine nor reaches a bulb that never answered —
        and when a party named an end scene, `_restore` returned before
        sending a single LIFX packet, so the strobing simply continued
        through the scene and past it.

        Failures are per-bulb and never fatal: one unreachable light must
        not leave the rest of the room dancing.
        """
        for serial in sorted(self._driven):
            try:
                addr = self.engine._addr(serial)
            except KeyError:
                continue
            try:
                await self.engine.send_governed(
                    serial,
                    packets.halt_waveform(
                        target=bytes.fromhex(serial),
                        source=self.engine.source,
                        sequence=self.engine._next_sequence()),
                    addr)
            except Exception as exc:  # noqa: BLE001 — one bulb, not the room
                log.warning("could not stop the effect on %s (%s)",
                            playback_check.flat(serial),
                            playback_check.flat(exc))
        self._driven = set()

    async def _restore(self) -> None:
        if self._end_scene:
            entity = self._end_scene
            try:
                await asyncio.to_thread(ha_client.call_service, "scene",
                                        "turn_on", {"entity_id": entity})
                self._snapshot = {}
                self._update_state(ended_with_scene=entity)
                return
            except Exception as exc:  # noqa: BLE001 — fall back to restoring
                # A scene that cannot be called must not leave the room in
                # party colours: the snapshot is still here, so use it and
                # say what happened.
                #
                # Both values are flattened, like everything else this
                # module logs from outside itself: the entity id arrives on
                # the wire (a party's `end_scene`, or the one a stop_show
                # call named) and the exception's text is whatever raised
                # it, so a newline in either is that caller writing its own
                # log lines.
                log.warning("end scene %s failed (%s); restoring the "
                            "lights instead", playback_check.flat(entity),
                            playback_check.flat(exc))
        await self._restore_snapshot()

    def nudge(self, ms: float) -> dict:
        """Bend the running show by `ms` — the by-ear sync trim.

        Positive means the lights fire earlier. Applied as clock drift, so
        it slews in over a couple of seconds instead of stepping — a step
        is a visible stutter in every light at once, and the whole point
        of a nudge is that you are watching. Clamped per press: ±200ms is
        far past anything an ear asks for in one go, and a wild value is a
        typo, not a request.
        """
        if not self.state.get("active") or not self.clock.anchored:
            return {"error": "nothing is running to nudge"}
        ms = max(-200.0, min(200.0, float(ms)))
        self.clock.add_drift(ms / 1000.0)
        self._session_nudge_ms = round(self._session_nudge_ms + ms, 1)
        self._update_state(nudge_ms=self._session_nudge_ms)
        return {"ok": True, "nudge_ms": self._session_nudge_ms}

    def keep_nudge(self) -> dict:
        """Fold the session's trim into the player's calibration.

        The clock anchors at `play_call + effective_offset`, and a nudge
        of +n behaves like an anchor n earlier — so keeping it means
        `adjust -= n`, and the sign is the whole trick. The session trim
        zeroes afterwards: it now lives in the calibration, and leaving it
        would apply it twice on the next track.
        """
        entity = self.state.get("media_player")
        if not self._session_nudge_ms or not entity:
            return {"error": "nothing has been nudged"}
        profile = calibration_store.load(entity)
        updated = calibration_store.set_adjust(
            entity,
            float(profile.get("adjust_ms") or 0.0) - self._session_nudge_ms)
        self._session_nudge_ms = 0.0
        self._update_state(nudge_ms=0.0)
        return {"ok": True, "entity_id": entity,
                "effective_offset_ms": updated.get("effective_offset_ms")}

    async def stop(self, restore: bool = True) -> dict:
        for task in (self._task, self._poller, self._verify):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = self._poller = self._verify = None
        self._session_nudge_ms = 0.0
        # The music first, and unconditionally — same reasoning as the
        # waveforms below. The speaker fetched the track and plays it on
        # its own, so it outlives every task cancelled above; a "stopped"
        # party with the song still going is what pressing Stop at 1am
        # actually delivered. Best-effort: a player that cannot be reached
        # must not keep the lights dancing.
        if self._playing_on:
            entity, self._playing_on = self._playing_on, None
            try:
                result = await asyncio.to_thread(ha_client.media_stop, entity)
            except Exception as exc:  # noqa: BLE001 — one speaker, not the stop
                result = {"error": str(exc)}
            # ha_client answers failures as {"error": ...} rather than
            # raising, so the except above alone was dead code and a
            # failed stop was SILENT — the one failure this feature exists
            # to end, recurring with no trace. An answer that is dropped
            # is a success nobody earned.
            if isinstance(result, dict) and result.get("error"):
                log.warning("could not stop the music on %s (%s)",
                            playback_check.flat(entity),
                            playback_check.flat(result["error"]))
                self._update_state(playback_warning=f"the music on {entity} "
                                   f"could not be stopped: {result['error']}")
        # Unconditional, and not part of `restore`: "put the room back" is a
        # choice a caller gets to decline, but "stop" is not a request to
        # keep strobing more quietly. A bulb left running its routine is the
        # one thing every stop path has to undo.
        await self._halt_waveforms()
        if restore and (self._snapshot or self._end_scene):
            await self._restore()
        self._write_state()
        return {"ok": True}

    # -- the loop ------------------------------------------------------------
    @staticmethod
    def _send_time(cue: dict) -> float:
        return cue["t"] - cue.get("lead_ms", 0) / 1000.0

    async def _run(self, cues: list[dict], duration_s: float) -> None:
        try:
            for index, cue in enumerate(cues):
                wait = self.clock.sleep_needed(self._send_time(cue))
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    await self._dispatch(cue)
                except Exception as exc:  # noqa: BLE001 — one cue, not the show
                    log.warning("cue at %.2fs failed: %s", cue["t"], exc)
                self._update_state(cues_sent=index + 1,
                                   position_s=round(max(0.0, self.clock.now()), 1))
            # The cue list is spent: the lights are holding whatever the
            # last cue left them at until the track ends. That is not the
            # same as running, and a Stop button is a different offer in
            # each case — which is what `lights_busy` is for.
            self._update_state(lights_busy=False)
            # Let the track play out, then put the room back.
            tail = self.clock.sleep_needed(duration_s)
            if tail > 0:
                await asyncio.sleep(tail)
            await self._restore()
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
        # Kept separately from the snapshot, and this is the distinction the
        # old code did not draw: a bulb that does not answer GetColor gets no
        # snapshot entry, but it is still a bulb this show is about to hand a
        # waveform to. Stopping has to reach it whether or not it introduced
        # itself.
        self._driven = set(serials)
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
    """The media-source URI HA players accept for a local file.

    The source id comes from `media_source.current_id()` rather than the
    `local` that used to be written here: `local` is only Core's DEFAULT
    name for its local media source, and an install that sets `media_dirs`
    renames it — which Core answers with `Unknown source directory` for
    every id BRight builds, so nothing plays at all.
    """
    file = analysis.get("file") or ""
    if not file.startswith(media_root + "/"):
        return None
    relative = file[len(media_root) + 1:]
    return media_source.build(media_source.current_id(), relative)


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


def filter_cues(cues: list[dict], allow: set[str] | None) -> list[dict]:
    """Only the cues for lights this run is allowed to touch.

    A party can name the lights it may use, and everything else stays out
    of it — the bedroom does not join in because the show was compiled
    from the whole map. Filtering here rather than at compile time is
    deliberate: one compiled show serves every party, and a show cached
    per fixture-subset would be a cache keyed on something nobody can
    see. `None` means no restriction, which is the usual case.
    """
    if not allow:
        return cues
    return [cue for cue in cues
            if (cue.get("serial") or cue.get("data", {}).get("entity_id")
                or "") in allow
            or f"lifx-{cue.get('serial', '')}" in allow]


def load_show_for_track(hash_hex: str, devices: dict[str, dict],
                        source: int, *, metronome: bool = False) -> dict | None:
    """A compiled show when the director has made one; the metronome show
    otherwise, so 'start_show' always has something honest to play.

    `metronome=True` forces the plain beat pulses even when a compiled
    show exists. The Lab's sync proof is the caller: its whole job is to
    demonstrate that the clock, the offset and the bulbs agree, and the
    moment a show was compiled for the chosen track its button quietly
    started playing the entire choreography instead — a full party out of
    a button labelled as a demo, and no way to run the plain proof again
    without deleting the show it was proving.

    `track_hash` rides in both branches because it is the identity the
    run state carries — the editor's live playhead follows the room by
    matching it, and a show without it is a show the panel cannot tell is
    the one on screen.
    """
    analysis = library.load_analysis(hash_hex)
    if analysis is None:
        return None
    title = (analysis.get("tags") or {}).get("title") or hash_hex[:8]
    # duration_of, never the tag: a lying VBR header parked the queue.
    duration = library.duration_of(analysis) or 60.0
    compiled = None if metronome else library.load_show(hash_hex)
    if compiled and compiled.get("cues"):
        baked = float(compiled.get("duration_s") or duration)
        # A show compiled before the duration heal has the header's lie
        # baked in, and _run sleeps out the tail after the last cue — so
        # trusting it parks the party for the phantom minutes on every
        # already-compiled VBR track. When the baked figure runs far past
        # the healed one, the heal wins; a minute of tolerance is a real
        # outro, a multiple is a lying header.
        if duration and baked > duration + 60.0:
            baked = duration
        return {
            "cues": compiled["cues"],
            "title": title,
            "track_hash": hash_hex,
            "duration_s": baked,
            "media_content_id": media_content_id_for(analysis),
            "tier": compiled.get("tier"),
        }
    return {
        "cues": metronome_cues(analysis, devices, source),
        "title": title,
        "track_hash": hash_hex,
        "duration_s": duration,
        "media_content_id": media_content_id_for(analysis),
        "tier": "metronome",
    }
