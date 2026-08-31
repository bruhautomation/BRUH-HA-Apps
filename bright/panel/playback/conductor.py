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
from director.effects import peak_shift
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
    _restorer: "asyncio.Task | None" = None
    # Awaited at the top of stop(), before anything else. The Manual
    # tab's loops hang here: they run on their own tasks outside the
    # conductor, and a loop that survived a stop — or a show starting,
    # which stops first — would fight the new run for its own bulbs
    # forever.
    before_stop = None

    def __init__(self, engine) -> None:
        self.engine = engine
        self.clock = ShowClock()
        self._task: asyncio.Task | None = None
        self._poller: asyncio.Task | None = None
        self._verify: asyncio.Task | None = None
        self._restorer: asyncio.Task | None = None
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
        # The track currently playing inside a party, as its own task, so
        # a skip can end one song without ending the evening. `_party_jump`
        # is how the loop tells a skip from a stop: skip() sets it before
        # cancelling, and a cancellation with no jump is the party ending.
        self._track_task: asyncio.Task | None = None
        self._party_jump: int | None = None
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
                        track_hash: str = "",
                        scene_on_end: bool = True) -> None:
        """One track, start to restored lights. Awaited inline by the party
        loop; wrapped in a task by single-show start().

        `scene_on_end=False` is the party's per-track case: an end scene
        belongs to the END of the run, and a track finishing naturally
        inside a party is not that — the good-night scene used to fire
        between every two songs of the evening it was configured to end.
        """
        await self.engine.start()
        await self._take_snapshot(cues)
        play_call = time.monotonic()
        # Claimed BEFORE the command goes out, not after it returns: the
        # play call runs in a thread, so a stop() racing it cancels this
        # coroutine without stopping the thread — the command still
        # reaches Core and the speaker still starts, and with nothing in
        # `_playing_on` the stop had nothing to silence. A claim on a
        # play that then fails is withdrawn below; a stray media_stop to
        # a player that never started is harmless where a song playing
        # through its own stop is not.
        self._playing_on = media_player
        result = await asyncio.to_thread(
            ha_client.play_media, media_player, media_content_id)
        if isinstance(result, dict) and result.get("error"):
            self._playing_on = None
            raise RuntimeError(result["error"])
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
            await self._run(sorted(cues, key=self._send_time), duration_s,
                            scene_on_end=scene_on_end)
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
        # Active from the moment the request is accepted, the way
        # start_party already is. `_play_one` refines this to "playing"
        # only after the snapshot round and the play command — seconds,
        # with a slow bulb in the room — and a panel that polls in that
        # window used to see `active: false` and hide the Stop button for
        # exactly the seconds someone most wants it.
        self._update_state(status="starting", active=True, track=title,
                           track_hash=track_hash, media_player=media_player,
                           cues_total=len(cues))
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
        # `active` goes false WITH the error, or the Stop button stays
        # rendered over a dead run and nudge/skip/autosync keep accepting
        # against it.
        self._update_state(status="error", error=str(error),
                           active=False, lights_busy=False)
        # Held, not fire-and-forget: an orphan restore racing the next
        # start() would fire the old snapshot's colours into the middle
        # of the new show. stop() cancels it with everything else.
        self._restorer = asyncio.get_running_loop().create_task(
            self._restore())

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
            # A while over an index rather than a for over the queue,
            # because the queue has transport controls now: a skip moves
            # the index, and "previous" on the first track replays it —
            # the clamp, not a refusal, because the button was pressed to
            # hear a song again and the first track has no earlier answer.
            index = 0
            while index < len(queue):
                hash_hex = queue[index]
                self._party_jump = None
                show = await asyncio.to_thread(loader, hash_hex)
                if not show or not show.get("cues") \
                        or not show.get("media_content_id"):
                    index += 1
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
                                   queue_left=len(queue) - index,
                                   queue_pos=index + 1,
                                   queue_total=len(queue))
                track = asyncio.create_task(self._play_one(
                    filter_cues(show["cues"], allow),
                    media_player=media_player,
                    media_content_id=show["media_content_id"],
                    title=show["title"],
                    duration_s=show["duration_s"],
                    offset_ms=self._calibrated_offset(media_player)
                              or offset_ms,
                    status="party",
                    track_hash=show.get("track_hash", ""),
                    scene_on_end=False))
                self._track_task = track
                try:
                    await track
                except asyncio.CancelledError:
                    # `cancelling()` asks whether the PARTY task has a
                    # cancel of its own pending — the tell between "the
                    # track was skipped" and "stop() cancelled the party
                    # while a skip was in flight". Without it, a stop that
                    # raced a skip would be read as the skip, swallowed,
                    # and the evening would play on through its own stop.
                    me = asyncio.current_task()
                    stopping = getattr(me, "cancelling", lambda: 0)() > 0
                    if self._party_jump is None or stopping:
                        # The party itself is ending. Awaiting a task from
                        # a cancelled coroutine does not cancel the task,
                        # so the track has to be taken down by hand or it
                        # plays on past its own party.
                        track.cancel()
                        try:
                            await track
                        except (asyncio.CancelledError, Exception):  # noqa: BLE001
                            pass
                        raise
                    # A skip: quiet what the interrupted track leaves
                    # behind, then let the loop move the index.
                    await self._skip_silence()
                except Exception as exc:  # noqa: BLE001 — next track, not the night
                    log.warning("party: %s failed: %s", show.get("title"), exc)
                finally:
                    self._track_task = None
                jumped = self._party_jump is not None
                step = self._party_jump if jumped else 1
                self._party_jump = None
                index = max(0, index + step)
                if index < len(queue):
                    # A shorter breath on a skip: somebody is at the
                    # controls and waiting.
                    await asyncio.sleep(0.3 if jumped else 1.5)
            # The evening ending naturally is the moment the end scene
            # was named for. Each track restored the snapshot as it
            # finished (scene_on_end=False keeps the scene out of the
            # between-songs restores); this is the run-level ending.
            if self._end_scene:
                await self._restore()
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

    async def _restore(self, *, use_scene: bool = True) -> None:
        if self._end_scene and use_scene:
            # Consumed on use, success or failure: a scene that has been
            # fired (or tried) for this run's ending must not fire again
            # on a later bare stop of a show that never asked for one —
            # the stale good-night scene used to outlive its party.
            entity, self._end_scene = self._end_scene, None
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

    async def _skip_silence(self) -> None:
        """What an interrupted track leaves behind: the song the speaker is
        still playing on its own, and any waveform still running on a bulb.
        The same pair stop() quiets, minus the restore — the party goes on
        and the next track takes the room from wherever this one left it,
        exactly as a natural transition would.
        """
        if self._verify is not None and not self._verify.done():
            self._verify.cancel()
            self._verify = None
        if self._playing_on:
            entity, self._playing_on = self._playing_on, None
            try:
                result = await asyncio.to_thread(ha_client.media_stop, entity)
            except Exception as exc:  # noqa: BLE001 — one speaker, not the skip
                result = {"error": str(exc)}
            if isinstance(result, dict) and result.get("error"):
                log.warning("could not stop the music on %s (%s)",
                            playback_check.flat(entity),
                            playback_check.flat(result["error"]))
        await self._halt_waveforms()

    def skip(self, step: int) -> dict:
        """Jump the running party to the next (+1) or previous (-1) track.

        Only a party — a single show has no queue to move through, and the
        Stop button is its whole transport. The current track's task is
        cancelled and `_party_jump` is what tells the loop this was a
        request, not the end of the evening.
        """
        if self.state.get("status") != "party" or not self.state.get("active"):
            return {"error": "no party is running to skip"}
        if self._track_task is None or self._track_task.done():
            return {"error": "between tracks — give it a second"}
        self._party_jump = 1 if int(step) >= 0 else -1
        self._track_task.cancel()
        return {"ok": True, "step": self._party_jump}

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

    def apply_sync(self, ms: float) -> dict:
        """A measured correction (auto-sync's), applied whole.

        Same books as nudge — it lands in `_session_nudge_ms`, so "Keep
        this trim" folds a measurement into the calibration exactly as it
        folds a by-ear one. The clamps differ because the sources do: a
        nudge is a human guess and ±200 catches typos, while a measurement
        is bounded by autosync's own search margin. Small corrections slew
        (invisible); one bigger than the slew can honestly deliver steps,
        because a room that far out is already visibly wrong and one jump
        beats twenty seconds of deliberate wrongness.
        """
        if not self.state.get("active") or not self.clock.anchored:
            return {"error": "nothing is running to sync"}
        ms = max(-2000.0, min(2000.0, float(ms)))
        if abs(ms) <= 150.0:
            self.clock.add_drift(ms / 1000.0)
        else:
            self.clock.step_drift(ms / 1000.0)
        self._session_nudge_ms = round(self._session_nudge_ms + ms, 1)
        self._update_state(nudge_ms=self._session_nudge_ms)
        return {"ok": True, "nudge_ms": self._session_nudge_ms,
                "applied_ms": round(ms, 1)}

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
        if self.before_stop is not None:
            try:
                await self.before_stop()
            except Exception as exc:  # noqa: BLE001 — the stop still happens
                log.warning("live loops did not stop cleanly: %s", exc)
        for task in (self._task, self._poller, self._verify, self._restorer):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._task = self._poller = self._verify = self._restorer = None
        self._track_task = None
        self._party_jump = None
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

    async def _run(self, cues: list[dict], duration_s: float,
                   *, scene_on_end: bool = True) -> None:
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
            await self._restore(use_scene=scene_on_end)
            # Not mid-party: a party track ending is not the run ending,
            # and resetting to the idle base here is what used to hide
            # every Stop button, the trim readout and the live picture
            # for the seconds between songs — while nudge/skip/autosync
            # all refused because `active` had gone false. The party loop
            # writes the real idle state once the evening is over.
            # (getattr, like the class-level defaults above: a test may
            # drive _run on a conductor that never wrote a state.)
            if getattr(self, "state", {}).get("status") != "party":
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

    async def start_manual(self, *, serials: list[str],
                           media_player: str | None = None,
                           media_content_id: str | None = None,
                           title: str = "Manual session",
                           track_hash: str = "") -> dict:
        """A session with no cue list: the Manual tab's ground.

        Snapshot the named bulbs, optionally start the music, and hold —
        every light change comes from live gestures, dispatched outside
        the conductor. What the conductor owns is the CONTRACT around
        them: the snapshot taken before anything is touched, the music
        claimed so stop() can silence it, and the state every Stop
        button and sensor follows. No calibration is required because
        there are no cues to sync — the person's own hands are the
        clock.
        """
        await self.stop(restore=True)
        self.set_end_scene(None)
        await self.engine.start()
        await self._snapshot_serials(set(serials))
        warning = None
        if media_player and media_content_id:
            # Claimed before the command, same as _play_one and for the
            # same race. A music failure is a warning, not a refusal:
            # performing to music something else is playing (or none) is
            # half the point of a manual session.
            self._playing_on = media_player
            play_call = time.monotonic()
            try:
                result = await asyncio.to_thread(
                    ha_client.play_media, media_player, media_content_id)
            except Exception as exc:  # noqa: BLE001 — the session still starts
                result = {"error": str(exc)}
            if isinstance(result, dict) and result.get("error"):
                self._playing_on = None
                warning = f"the music could not start: {result['error']}"
            else:
                # The clock is what the Manual transport reads bars off,
                # so a session playing a track has to anchor it exactly
                # as a show does. Calibration stays optional here —
                # there are no compiled cues to sync — and an
                # uncalibrated speaker anchors at the play command,
                # which is the same grid a few tens of milliseconds out
                # rather than no grid at all.
                self.clock.anchor(
                    play_call,
                    (self._calibrated_offset(media_player) or 0.0) / 1000.0)
        self._write_state()
        self._update_state(status="manual", active=True, lights_busy=True,
                           track=title, track_hash=track_hash,
                           media_player=media_player or "",
                           **({"playback_warning": warning} if warning
                              else {}))
        return {"ok": True, "snapshotted": len(self._snapshot),
                **({"warning": warning} if warning else {})}

    # -- snapshot / restore ----------------------------------------------------
    async def _take_snapshot(self, cues: list[dict]) -> None:
        """What every LIFX fixture in the show looks like before we touch
        it, so stop puts the room back instead of leaving party colors."""
        serials = {cue["serial"] for cue in cues if cue.get("ch") == "lifx"}
        await self._snapshot_serials(serials)

    async def _snapshot_serials(self, serials: set[str]) -> None:
        self._snapshot = {}
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
    """The test show: beat pulses plus a whole-room flash on every drop,
    straight from the analysis — no director involved.

    One SetWaveform per fixture every 8 beats (the bulb runs the beats in
    between), phase-anchored at the send moment — steady state is well
    under 1 msg/s/device against the 20/s ceiling. Each drop the analyzer
    found gets the same shape the real choreography gives it — every bulb
    dark just before, every bulb full-on at the moment itself, back to the
    base a breath later — so this one run answers both questions a show
    depends on: does the pulse land ON the beat, and does the flash land
    ON the drop. If either misses here, no choreography was going to fix
    it; if the flash lands somewhere the music does nothing, the analyzer
    misheard the drop, which is a different repair (re-analyze) from a
    calibration that is off (nudge)."""
    beats = analysis.get("beats") or []
    if len(beats) < 8:
        return []
    intervals = sorted(b - a for a, b in zip(beats, beats[1:]))
    period_ms = int(intervals[len(intervals) // 2] * 1000)
    drops = [float(d.get("t", 0)) for d in (analysis.get("drops") or [])
             if isinstance(d, dict)]
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
        # A sine waveform starts at the bulb's CURRENT level and is
        # brightest half a period in — anchoring it ON the beat put the
        # peak on the off-beat, in the one show whose whole job is the
        # beat. Same fix as the compiled `pulse` effect: start the wave
        # `peak_shift` ahead, and drop an anchor whose lead-in would land
        # before t=0 rather than clamping it back onto the off-beat.
        lead_s = peak_shift("sine", period_ms / 1000.0)
        for start in beats[::8]:
            if start - lead_s < 0:
                continue
            pulse = packets.set_waveform(
                transient=True,
                hue=int(200 / 360 * 65535), saturation=int(0.9 * 65535),
                brightness=int(0.9 * 65535), kelvin=3500,
                period_ms=period_ms, cycles=8.0,
                waveform=packets.WAVEFORM_SINE,
                target=bytes.fromhex(serial), source=source)
            cues.append({"t": round(start - lead_s, 4), "ch": "lifx",
                         "serial": serial, "lead_ms": lead_ms,
                         "payload_b64": base64.b64encode(pulse).decode(),
                         "desc": "beat pulse x8"})
        for at in drops:
            # Dark first, with no fade — the attack is the test. The
            # flash is a cold white so it cannot be mistaken for a beat
            # pulse, and the base is re-sent afterwards so the next
            # 8-beat waveform starts from the colour it expects.
            dark = packets.set_color(
                hue=0, saturation=0, brightness=0, kelvin=3500,
                duration_ms=120, target=bytes.fromhex(serial), source=source)
            cues.append({"t": round(max(0.0, at - 0.4), 4), "ch": "lifx",
                         "serial": serial, "lead_ms": lead_ms,
                         "payload_b64": base64.b64encode(dark).decode(),
                         "desc": "drop blackout"})
            flash = packets.set_color(
                hue=0, saturation=0, brightness=65535, kelvin=4000,
                duration_ms=0, target=bytes.fromhex(serial), source=source)
            cues.append({"t": round(at, 4), "ch": "lifx", "serial": serial,
                         "lead_ms": lead_ms,
                         "payload_b64": base64.b64encode(flash).decode(),
                         "desc": "drop flash"})
            cues.append({"t": round(at + 0.8, 4), "ch": "lifx",
                         "serial": serial, "lead_ms": lead_ms,
                         "payload_b64": base64.b64encode(base).decode(),
                         "desc": "back to base"})
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
                        source: int, *, metronome: bool = False,
                        version: str | None = None) -> dict | None:
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
    compiled = None if metronome else library.load_show(hash_hex, version)
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
