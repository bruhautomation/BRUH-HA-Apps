"""The Manual tab's engine: lights played by hand, on the song's own grid.

A show is compiled ahead and played by the conductor; this is the other
kind of evening — a person with a phone, striking bulbs on the floor
plan, dropping the room to black on the breakdown and flashing it back
on the landing.

It is built like a DAW, because that is the instrument this is:

* **the transport** (`playback/transport.py`) is the clock everything is
  measured against — bars and beats, either from the analyzed track the
  conductor is playing or from a tapped tempo.
* **a clip** is a pattern of taps that is `bars` long. Recording starts
  on the next BAR LINE, never on the press; taps land on quantized beat
  offsets; after `bars` bars it loops. Every repetition is re-derived
  from the transport, so a loop stays with music whose tempo breathes.
* **pads** are one-shot and immediate: drop (to black, fast) and flash
  (a transient pulse to full white that returns to whatever colour the
  bulb was holding — the bulb does the returning, so a flash can never
  strand the room bright).
* **one-shots** are any catalog effect, fired once for a few seconds and
  rendered by `compile_preview` exactly as the Effects tab's "run it on
  the lights" is.

Three things the previous version got wrong, and the reasons they are
worth a paragraph each:

**A bulb that is off shows nothing, and says nothing about it.** LIFX
accepts every colour and every waveform while powered down and displays
none of them, so a manual session in a dark room was a person tapping
dots at a dark room with every packet sent successfully.
`LiveClips.power_room` is the fix and `packets.set_light_power` — which
had no callers at all until now — is what it sends.

**Latency stacked.** Dispatch went through `engine.send_governed`, whose
`TokenBucket.acquire` deliberately drives tokens NEGATIVE so successive
callers are told 50, 100, 150ms — and those sleeps queue in order. A busy
bar bought a queue that the pads, the taps and every gesture after them
stood behind. Everything here goes through `engine.send_live`, which
never awaits: it takes a token or it drops the packet.

**Late work is dropped, never queued** (`_too_late`). A strike sent late
lands off the beat, which is worse than a strike nobody hears.

A LIFX bulb runs ONE waveform at a time, which is why a strike is two
packets (a set to the peak with no fade, then a saw decay the bulb runs
itself) and why stopping a clip halts its bulbs.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field

from director import compiler
from director import effects as fx
from lifx import packets
from playback.transport import Transport

log = logging.getLogger("bright.live")

# Clip lengths, in bars. Powers of two because a pattern that is three
# bars long against a four-bar phrase is a mistake nobody makes on
# purpose, and the phone draws these as four buttons.
CLIP_BARS = (1, 2, 4, 8)
# Quantize divisions, in beats: quarter, eighth, sixteenth, and off.
QUANTIZE_CHOICES = (1.0, 0.5, 0.25, 0.0)
MAX_CLIPS = 8
MAX_EVENTS = 32

# Two taps closer than this are one event with both bulbs in it — a
# thirty-second note, well under anything a hand plays deliberately.
MERGE_BEATS = 1.0 / 32.0

# Strike packets per fixture per second a clip may ask for. Two packets
# per strike (the set and the decay wave) against the bulbs' 20/s
# ceiling, with room left for pads and one-shots landing on top.
MAX_PER_FIXTURE_HZ = 12.0

STRIKE_PEAK = 1.0
STRIKE_FLOOR = 0.08
# The decay wave spans the gap to the next strike, clamped: shorter than
# 120ms is invisible, longer than 4s is a light that looks stuck.
MIN_DECAY_S = 0.12
MAX_DECAY_S = 4.0
# A tap has no next strike to decay into, so it gets a length: long
# enough to read as a hit from across the room, short enough that
# tapping four dots in a bar does not smear them into one glow.
TAP_DECAY_MS = 350

FLASH_MS = 420
DROP_FADE_MS = 80

# What "the room is live" looks like before anybody has played anything:
# dim, so a strike has somewhere visible to come from, and low enough
# that a session started at 1am is not a light switch.
BASE_LEVEL = 0.12
BASE_FADE_MS = 400

# How far past its moment a scheduled send may be and still be worth
# sending. A clip strike is a beat, so its window is tight; a one-shot
# effect is a gesture whose shape survives being a fifth of a second out.
LOOP_LATE_S = 0.15
SHOT_LATE_S = 0.25

# Two presses of the same pad inside this window are one press. A DROP
# is mashed, not clicked.
PAD_COALESCE_S = 0.15


def _strike(fixture: dict, at: float, decay_ms: int, hue: float, sat: float,
            manners: dict, label: str) -> list[dict]:
    """The compiled `hit` effect's exact shape, as two actions.

    A set to the peak with no fade (the attack — a fade still in flight
    would start the decay from somewhere between the two levels and lose
    exactly the attack), then a saw travelling to the floor: the bulb
    runs the envelope, so this costs two packets however long it lasts.
    """
    peak = fx._cap(fixture, STRIKE_PEAK, manners)
    floor = fx._cap(fixture, min(STRIKE_FLOOR, peak), manners)
    return [fx._set(fixture, at, hue, sat, peak, 0, f"{label} strike"),
            fx._wave(fixture, at, hue, sat, floor, decay_ms, 1.0, "saw",
                     0.5, f"{label} decay")]


def tap_cues(fixture: dict, palette_index: int, palette: list, source: int,
             respect_roles: bool = True) -> list[dict]:
    """One bulb, struck now: the answer to a finger landing on a dot.

    Two packets, deliberately — this is the cheapest thing the session
    sends and the one whose latency a person can feel, so it renders the
    strike and nothing else.
    """
    hue, sat = fx._colour(palette, palette_index)
    manners = {"respect_roles": bool(respect_roles)}
    out = compiler._Cues(source, {})
    compiler.render_actions(
        _strike(fixture, 0.0, TAP_DECAY_MS, hue, sat, manners, "live tap"),
        out)
    return sorted(out.cues, key=_send_time)


def pad_cues(cast: list[dict], pad: str, source: int) -> list[dict]:
    """The two panic buttons, as immediate cues.

    Drop is a fast fade to black — a `set`, so it holds until something
    else speaks. Flash is a transient pulse waveform to full white: the
    BULB returns itself to whatever it was holding, so a flash cannot
    strand the room bright however the connection behaves afterwards.
    """
    if not cast:
        raise ValueError("no lights selected — tick at least one")
    out = compiler._Cues(source, {})
    if pad == "drop":
        for fixture in cast:
            out.set_color(fixture, 0.0, 0.0, 0.0, 0.0, DROP_FADE_MS,
                          "live drop", resend=True)
        return out.cues
    if pad == "flash":
        actions = [fx._wave(fixture, 0.0, 0.0, 0.0, 1.0, FLASH_MS, 1.0,
                            "pulse", 0.7, "live flash")
                   for fixture in cast]
        compiler.render_actions(actions, out)
        return out.cues
    raise ValueError(f"unknown pad {pad!r}")


def power_cues(cast: list[dict], palette: list, source: int,
               respect_roles: bool = True) -> list[dict]:
    """The dim base a session starts from, one cue per bulb.

    Sent right after the power packets and for the same reason: a bulb
    that is on but sitting at whatever the last show left it at is a room
    that answers the first strike with no visible change. Each bulb takes
    its own palette colour, the same one its strikes will use, so the
    floor plan and the room already agree before anything is played.
    """
    manners = {"respect_roles": bool(respect_roles)}
    out = compiler._Cues(source, {})
    for spot, fixture in enumerate(cast):
        hue, sat = fx._colour(palette, spot)
        out.set_color(fixture, 0.0, hue, sat,
                      fx._cap(fixture, BASE_LEVEL, manners), BASE_FADE_MS,
                      "live base", resend=False)
    return out.cues


def _send_time(cue: dict) -> float:
    return cue["t"] - cue.get("lead_ms", 0) / 1000.0


@dataclass
class Clip:
    """A pattern of taps, `bars` long, locked to the transport's grid."""

    id: int
    bars: int
    quantize: float
    state: str = "armed"          # armed | recording | looping
    start_bar: int = 0
    cycle: int = 0
    muted: bool = False
    rec_enabled: bool = True
    events: list[dict] = field(default_factory=list)

    def length_beats(self, transport: Transport) -> float:
        return float(self.bars * transport.bar_beats)

    def ids(self) -> list[str]:
        """Every bulb this clip drives, in the order it first strikes
        them — what the panel marks on the floor plan."""
        seen: list[str] = []
        for event in sorted(self.events, key=lambda e: e["beat"]):
            for fixture_id in event["ids"]:
                if fixture_id not in seen:
                    seen.append(fixture_id)
        return seen


class LiveClips:
    """The clips, pads and one-shots of a manual session.

    Owned by the panel, driven by the same engine the conductor uses.
    `stop_all` is hooked onto the conductor's stop, so a show or party
    starting — or Stop being pressed anywhere — takes the clips with it:
    a clip that outlived its session would fight whatever came next for
    the same bulbs, forever.
    """

    def __init__(self, engine, *, transport: Transport | None = None) -> None:
        self.engine = engine
        self.transport = transport or Transport()
        # Sends dropped for being late, over the session's life. Read by
        # the tests and the log; nothing acts on it.
        self.skipped = 0
        self.cast: list[dict] = []
        self.palette: list = []
        self.respect_roles = True
        # Called whenever a clip changes in a way the phone has to see —
        # including the transitions it did not ask for (armed →
        # recording → looping), because a status that only refreshes on
        # a press is a status that is wrong exactly while it matters.
        self.on_change = None
        self._spot: dict[str, int] = {}
        self._clips: dict[int, Clip] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._shots: list[asyncio.Task] = []
        self._pads: dict[str, float] = {}
        self._counter = 0

    # -- the session ---------------------------------------------------------
    def begin(self, *, cast: list[dict], palette: list,
              respect_roles: bool = True) -> int:
        """Take the room. Returns how many bulbs were powered on."""
        self.cast = list(cast)
        self.palette = list(palette)
        self.respect_roles = bool(respect_roles)
        self._spot = {str(f.get("id")): spot
                      for spot, f in enumerate(self.cast)}
        return self.power_room()

    def power_room(self) -> int:
        """Power every bulb of the cast on, then set the dim base.

        This is the whole of bug (1): a powered-off LIFX bulb accepts
        colour and waveform packets and displays nothing, so every
        gesture of a session started in a dark room was sent, accepted
        and invisible.
        """
        serials = [f["serial"] for f in self.cast if f.get("serial")]
        lit = self.engine.power_on(serials)
        for cue in power_cues(self.cast, self.palette, self.engine.source,
                              self.respect_roles):
            self._send(cue, priority=True)
        return lit

    # -- what the panel renders ---------------------------------------------
    def describe(self) -> list[dict]:
        """Every clip, with enough for the phone to draw the pattern AND
        run its own playhead — never a network message per strike."""
        now = time.monotonic()
        rows = []
        for clip_id, clip in sorted(self._clips.items()):
            rows.append({
                "id": clip_id,
                "bars": clip.bars,
                "quantize": clip.quantize,
                "state": clip.state,
                "muted": clip.muted,
                "rec_enabled": clip.rec_enabled,
                "start_bar": clip.start_bar,
                "length_beats": clip.length_beats(self.transport),
                "cycle": clip.cycle,
                "cycle_phase": self._cycle_phase(clip, now),
                "events": [{"beat": event["beat"], "ids": list(event["ids"])}
                           for event in sorted(clip.events,
                                               key=lambda e: e["beat"])],
                "ids": clip.ids(),
                "lights": [self._label(i) for i in clip.ids()],
            })
        return rows

    def _label(self, fixture_id: str) -> str:
        spot = self._spot.get(fixture_id)
        if spot is None:
            return fixture_id
        fixture = self.cast[spot]
        return fixture.get("label") or fixture.get("id") or fixture_id

    def _cycle_phase(self, clip: Clip, now: float) -> float:
        if clip.state == "armed" or not self.transport.ready:
            return 0.0
        start = self._cycle_start(clip, clip.cycle)
        end = self._cycle_start(clip, clip.cycle + 1)
        if end <= start:
            return 0.0
        return round(min(1.0, max(0.0, (now - start) / (end - start))), 4)

    # -- the grid a clip runs on ---------------------------------------------
    def _cycle_start(self, clip: Clip, cycle: int) -> float:
        """The monotonic instant cycle `cycle` of this clip begins.

        Asked of the TRANSPORT every time, never accumulated from a
        period. That is the whole anti-drift claim: each repetition is
        re-derived from the song's own bar lines, so a tempo that
        breathes carries the loop with it instead of leaving it behind.
        """
        return self.transport.bar_time(clip.start_bar + cycle * clip.bars)

    def _event_time(self, clip: Clip, cycle: int, event: dict) -> float:
        """When one event of one cycle is due — through the beats array
        in track mode, so a beat that arrives early is answered early."""
        return self.transport.beat_time(clip.start_bar + cycle * clip.bars,
                                        event["beat"])

    # -- clips ---------------------------------------------------------------
    def arm_clip(self, bars: int = 1, quantize: float = 1.0) -> dict:
        """Arm a clip. It starts recording on the next bar line.

        Raises ValueError with a person-readable reason — these come
        straight from a phone screen and the refusal is read there.
        """
        if not self.transport.ready:
            raise ValueError("no tempo yet — tap the tempo, or start a "
                             "session on an analyzed track")
        if len(self._clips) >= MAX_CLIPS:
            raise ValueError(f"that is {MAX_CLIPS} clips — clear one first")
        bars = int(bars) if int(bars) in CLIP_BARS else 1
        quantize = (float(quantize) if float(quantize) in QUANTIZE_CHOICES
                    else 1.0)
        self._counter += 1
        clip = Clip(id=self._counter, bars=bars, quantize=quantize)
        # Arming a clip is arming it for recording, and record-enable is
        # exclusive: two clips taking the same tap is a tap recorded
        # twice, which nobody asks for and nobody can see happening.
        for other in self._clips.values():
            other.rec_enabled = False
        self._clips[clip.id] = clip
        self._tasks[clip.id] = asyncio.create_task(self._run_clip(clip))
        self._changed()
        return {"id": clip.id, "bars": bars, "quantize": quantize,
                "state": clip.state}

    def add_clip(self, bars: int, quantize: float,
                 events: list[dict]) -> dict:
        """A clip that is already played, looping from the next bar.

        The HTTP fallback's door: a POST carries a whole rhythm rather
        than a live take, and it must reach exactly the same clip model
        as the socket's — a second scheduler for the same thing is a
        second thing to drift.
        """
        started = self.arm_clip(bars, quantize)
        clip = self._clips[started["id"]]
        length = clip.length_beats(self.transport)
        for event in events or []:
            ids = [str(i) for i in (event.get("ids") or [])
                   if str(i) in self._spot]
            if not ids:
                continue
            beat = self.transport.quantize_beats(
                float(event.get("beat", 0.0)), clip.quantize) % length
            self._merge(clip, beat, ids)
        return {**started, "events": len(clip.events)}

    def clip(self, clip_id: int) -> Clip | None:
        return self._clips.get(int(clip_id))

    def recording_clip(self) -> Clip | None:
        """Where a tap gets recorded: the take if one is running, and the
        record-enabled loop otherwise (which is what overdub is)."""
        for clip in self._clips.values():
            if clip.state == "recording":
                return clip
        for clip in self._clips.values():
            if clip.state == "looping" and clip.rec_enabled:
                return clip
        return None

    def record(self, fixture_id: str) -> str | None:
        """Put a tap into whatever is listening. None, or the refusal."""
        clip = self.recording_clip()
        if clip is None:
            return None
        return self.add_tap(clip.id, fixture_id)

    def add_tap(self, clip_id: int, fixture_id: str) -> str | None:
        """One tap into one clip, at its quantized offset in the cycle."""
        clip = self._clips.get(int(clip_id))
        fixture_id = str(fixture_id)
        if clip is None or clip.state == "armed":
            return None
        if fixture_id not in self._spot:
            return f"no bulb {fixture_id!r} in this session"
        length = clip.length_beats(self.transport)
        at = self.transport.beats_since(
            clip.start_bar + clip.cycle * clip.bars)
        # A tap a hair before the loop point belongs to the TOP of the
        # loop, not to a beat past its end — which is what makes tapping
        # on the downbeat work at all, and is what every DAW does.
        at = self.transport.quantize_beats(at, clip.quantize) % length
        existing = self._nearest(clip, at)
        if existing is None and len(clip.events) >= MAX_EVENTS:
            return f"that clip already holds {MAX_EVENTS} taps"
        if existing is None:
            crowding = self._too_fast(clip, fixture_id, length)
            if crowding:
                return crowding
        self._merge(clip, at, [fixture_id])
        self._changed()
        return None

    def _nearest(self, clip: Clip, at: float) -> dict | None:
        for event in clip.events:
            if abs(event["beat"] - at) <= MERGE_BEATS:
                return event
        return None

    def _merge(self, clip: Clip, at: float, ids: list[str]) -> None:
        event = self._nearest(clip, at)
        if event is None:
            clip.events.append({"beat": round(at, 4), "ids": list(ids)})
            return
        for fixture_id in ids:
            if fixture_id not in event["ids"]:
                event["ids"].append(fixture_id)

    def _too_fast(self, clip: Clip, fixture_id: str,
                  length: float) -> str | None:
        """One bulb, two packets a strike, against the LIFX ceiling."""
        strikes = 1 + sum(1 for event in clip.events
                          if fixture_id in event["ids"])
        seconds = max(0.05, length * self.transport.beat_s)
        if strikes * 2 / seconds > MAX_PER_FIXTURE_HZ:
            return ("that is faster than one bulb can follow — spread it "
                    "across more lights or make the clip longer")
        return None

    def set_muted(self, clip_id: int, muted: bool) -> bool:
        clip = self._clips.get(int(clip_id))
        if clip is None:
            return False
        clip.muted = bool(muted)
        self._changed()
        return True

    def set_rec_enabled(self, clip_id: int, enabled: bool) -> bool:
        clip = self._clips.get(int(clip_id))
        if clip is None:
            return False
        if enabled:
            for other in self._clips.values():
                other.rec_enabled = False
        clip.rec_enabled = bool(enabled)
        self._changed()
        return True

    def clear_clip(self, clip_id: int) -> bool:
        """Empty the pattern and keep the clip: its bars, its place in
        the bar grid and its record-enable are what somebody set up."""
        clip = self._clips.get(int(clip_id))
        if clip is None:
            return False
        clip.events = []
        self._changed()
        return True

    async def delete_clip(self, clip_id: int, halt: bool = True) -> bool:
        clip = self._clips.pop(int(clip_id), None)
        if clip is None:
            return False
        await self._cancel(self._tasks.pop(clip.id, None))
        if halt:
            self._halt(self._serials_of(clip))
        self._changed()
        return True

    async def stop_all(self) -> None:
        for clip_id in list(self._clips):
            await self.delete_clip(clip_id, halt=False)
        for task in self._shots:
            await self._cancel(task)
        self._shots = []
        self._pads = {}
        self.transport.unbind()

    @staticmethod
    async def _cancel(task: asyncio.Task | None) -> None:
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    def _serials_of(self, clip: Clip) -> set[str]:
        serials = set()
        for fixture_id in clip.ids():
            spot = self._spot.get(fixture_id)
            if spot is not None:
                serial = self.cast[spot].get("serial")
                if serial:
                    serials.add(serial)
        return serials

    def _changed(self) -> None:
        if self.on_change is None:
            return
        try:
            self.on_change()
        except Exception as exc:  # noqa: BLE001 — a listener, not the clip
            log.warning("live listener failed: %s", exc)

    # -- the clip loop -------------------------------------------------------
    async def _run_clip(self, clip: Clip) -> None:
        """One task per clip: count in, record a take, then loop it.

        Every cycle asks the transport where it starts and when each of
        its events is due. Nothing accumulates a period, because a period
        added to itself is a loop that leaves the music — which is what
        the old free-running loops did, and what a person hears as "the
        loop doesn't stay with the song".
        """
        try:
            start = self.transport.next_bar_time()
            await self._sleep_until(start)
            # The bar line, not the press. A take that began where the
            # finger landed would put the clip's own "1" halfway through
            # a bar, and every repeat of it after that.
            clip.start_bar = self.transport.bar_at(start)
            clip.state = "recording"
            clip.cycle = 0
            self._changed()
            # The take sends nothing: every tap in it already struck its
            # own bulb the instant the finger landed.
            await self._sleep_until(self._cycle_start(clip, 1))
            clip.state = "looping"
            self._changed()
            cycle = 1
            while True:
                cycle = self._catch_up(clip, cycle)
                clip.cycle = cycle
                for event in sorted(clip.events, key=lambda e: e["beat"]):
                    due = self._event_time(clip, cycle, event)
                    await self._sleep_until(due)
                    if clip.muted or self._too_late(due, LOOP_LATE_S):
                        continue
                    self._play(clip, event)
                await self._sleep_until(self._cycle_start(clip, cycle + 1))
                cycle += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — one clip, not the session
            log.warning("clip %s stopped: %s", clip.id, exc)
            clip.state = "looping"
            self._changed()

    def _catch_up(self, clip: Clip, cycle: int) -> int:
        """Where the transport says we are, when it is not where we left.

        A suspend, a busy box or a tempo that moved a long way can put a
        whole cycle in the past; playing them back to catch up would
        machine-gun the missed strikes into the room. Skipping to the
        current cycle is what keeps a stall to the bars it stalled
        through.
        """
        elapsed = self.transport.bar_at() - clip.start_bar
        if elapsed < cycle * clip.bars:
            return cycle
        return max(cycle, int(elapsed // clip.bars))

    def _play(self, clip: Clip, event: dict) -> None:
        manners = {"respect_roles": self.respect_roles}
        actions: list[dict] = []
        for fixture_id in event["ids"]:
            spot = self._spot.get(fixture_id)
            if spot is None:
                # A bulb that has gone off the map since the tap: skipped,
                # never a refusal — the rest of the rhythm is still what
                # the person played.
                continue
            hue, sat = fx._colour(self.palette, spot)
            actions.extend(_strike(
                self.cast[spot], 0.0, self._decay_ms(clip, event, fixture_id),
                hue, sat, manners, "clip"))
        if not actions:
            return
        out = compiler._Cues(self.engine.source, {})
        compiler.render_actions(actions, out)
        for cue in out.cues:
            self._send(cue)

    def _decay_ms(self, clip: Clip, event: dict, fixture_id: str) -> int:
        """The strike runs to THIS bulb's next strike, not the clip's
        next event: a bulb struck on beats 1 and 3 glows through beat 2
        rather than cutting off under somebody else's hit."""
        length = clip.length_beats(self.transport)
        mine = sorted(other["beat"] for other in clip.events
                      if fixture_id in other["ids"])
        here = event["beat"]
        after = [beat for beat in mine if beat > here]
        gap = (after[0] - here) if after else (mine[0] + length - here
                                              if mine else length)
        seconds = gap * self.transport.beat_s
        return int(min(MAX_DECAY_S, max(MIN_DECAY_S, seconds)) * 1000)

    async def _sleep_until(self, when: float) -> None:
        delay = when - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    def _too_late(self, due: float, tolerance: float) -> bool:
        """Is this send past saving? Counted if so, and then dropped.

        A strike sent late lands off the beat, which is worse than a
        strike nobody hears — and a backlog sent to catch up is a backlog
        every gesture after it stands behind.

        Pads and taps never come through here: they have no scheduled
        moment to be late for, and they are the presses whose latency is
        the whole product.
        """
        late = time.monotonic() - due
        if late <= tolerance:
            return False
        self.skipped += 1
        return True

    # -- taps, pads and one-shots -------------------------------------------
    def tap(self, fixture_id: str) -> str | None:
        """A finger on a dot: strike it now, and record it if something
        is listening. None, or the refusal to show."""
        fixture_id = str(fixture_id)
        spot = self._spot.get(fixture_id)
        if spot is None:
            return f"no reachable bulb {fixture_id!r} on the map"
        for cue in tap_cues(self.cast[spot], spot, self.palette,
                            self.engine.source, self.respect_roles):
            self._send(cue)
        return self.record(fixture_id)

    def fire(self, cues: list[dict], label: str = "one-shot") -> dict:
        """Send a cue list once, starting now, without owning the session.

        Unlike `conductor.run_cues` this does not stop anything or touch
        the snapshot — it is a gesture INSIDE a manual session, layered
        over whatever the clips are doing. It returns as soon as the task
        exists, because the caller is a socket frame and the person who
        sent it is waiting on light, not on a reply.
        """
        self._shots = [t for t in self._shots if not t.done()]
        task = asyncio.create_task(
            self._run_once(sorted(cues, key=_send_time)))
        self._shots.append(task)
        return {"ok": True, "cues": len(cues), "label": label}

    def fire_pad(self, cues: list[dict], pad: str) -> dict:
        """A pad, at most once per `PAD_COALESCE_S`, straight to the wire.

        A drop is mashed — three fingers, or one hand hitting it twice on
        the way down — and every repeat is the same room going to the
        same black. Sending them all costs a packet per bulb per press
        against a ceiling the taps are also spending, so the repeats are
        answered and not sent. What does go, goes with `priority`: the
        one gesture that must never be the packet the bucket dropped.
        """
        now = time.monotonic()
        if now - self._pads.get(pad, 0.0) < PAD_COALESCE_S:
            return {"ok": True, "coalesced": True, "label": pad}
        self._pads[pad] = now
        for cue in cues:
            self._send(cue, priority=True)
        return {"ok": True, "cues": len(cues), "label": pad}

    async def _run_once(self, cues: list[dict]) -> None:
        anchor = time.monotonic()
        for cue in cues:
            due = anchor + _send_time(cue)
            await self._sleep_until(due)
            if self._too_late(due, SHOT_LATE_S):
                continue
            self._send(cue)

    # -- the wire ------------------------------------------------------------
    def _send(self, cue: dict, *, priority: bool = False) -> bool:
        serial = cue.get("serial")
        if not serial:
            return False
        try:
            addr = self.engine._addr(serial)
        except KeyError:
            return False
        packet = bytearray(base64.b64decode(cue["payload_b64"]))
        packet[23] = self.engine._next_sequence()
        return self.engine.send_live(serial, bytes(packet), addr,
                                     priority=priority)

    def _halt(self, serials: set[str]) -> None:
        """End whatever wave is still running on these bulbs.

        Priority, always: a halt that the bucket dropped is a bulb left
        strobing after the clip that started it is gone.
        """
        for serial in sorted(serials):
            try:
                addr = self.engine._addr(serial)
            except KeyError:
                continue
            self.engine.send_live(
                serial,
                packets.halt_waveform(
                    target=bytes.fromhex(serial), source=self.engine.source,
                    sequence=self.engine._next_sequence()),
                addr, priority=True)
