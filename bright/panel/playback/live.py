"""The Manual tab's engine: lights played by hand, against real music.

A show is compiled ahead and played by the conductor; this is the other
kind of evening — a person with a phone, striking bulbs on the floor
plan, dropping the room to black on the breakdown and flashing it back
on the landing. Semi-manual, semi-automated: every press is immediate,
and the loops a press starts keep running on their own until they are
stopped or replaced.

Four kinds of output, all through the compiler's own packet builder
(`compiler._Cues` + `render_actions`), because a second answer to "how
does an action become bytes" is a second answer waiting to drift:

* **taps** — one bulb, struck now, because a finger landed on its dot.
  Two packets, and the whole reason the socket exists: this is the
  feedback that has to arrive while the finger is still down.
* **pads** — one-shot, right now, over everything: drop (to black,
  fast) and flash (a transient pulse to full white that returns to
  whatever colour the bulb was holding — the bulb does the returning,
  so a flash can never strand the room bright).
* **loops** — a struck rhythm, repeated. An event is a moment and the
  bulbs it strikes (`{"t": seconds, "ids": [...]}`) — the person played
  a path through the room and the loop replays exactly that. There is
  no pattern vocabulary on top of it, because there was nothing a
  `chase` could say that a list of taps could not.
* **one-shots** — any catalog effect, fired once for a few seconds at
  the tapped tempo, rendered by `compile_preview` exactly as the
  Effects tab's "run it on the lights" is.

A LIFX bulb runs ONE waveform at a time, so starting a loop stops any
loop that shares a fixture with it — replacement is the gesture, not an
error. Timing lives here rather than in the browser because a phone tab
sleeps, throttles and disconnects; the loop must not.

**Late work is dropped, never queued.** `engine.TokenBucket` runs its
per-bulb token count NEGATIVE on purpose, so every over-budget send
deepens a debt the next caller waits out — which is right for a
compiled show and exactly wrong here, where the next caller is a person
pressing a pad. See `_too_late`.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time

from director import compiler
from director import effects as fx
from lifx import packets

log = logging.getLogger("bright.live")

# A loop period shorter than this is a strobe typed by accident, and one
# longer stops reading as a loop at all.
MIN_PERIOD_S = 0.4
MAX_PERIOD_S = 16.0
MAX_EVENTS = 32

# Strike packets per fixture per second a loop may ask for. Two packets
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

# How far past its moment a scheduled send may be and still be worth
# sending. A loop strike is a beat, so its window is tight; a one-shot
# effect is a gesture whose shape survives being a fifth of a second
# out.
LOOP_LATE_S = 0.15
SHOT_LATE_S = 0.25

# Two presses of the same pad inside this window are one press. A DROP
# is mashed, not clicked.
PAD_COALESCE_S = 0.15

# How close to a whole number of beats "close enough" is, as a fraction
# of the beat. See `snap_period`.
SNAP_TOLERANCE = 0.15


def infer_period(taps_s: list[float]) -> float | None:
    """The tapped tempo, as one strike period: the median gap.

    The median rather than the mean because a tap session usually starts
    with one hesitant gap, and the median simply does not hear it.
    """
    if len(taps_s) < 2:
        return None
    gaps = sorted(b - a for a, b in zip(taps_s, taps_s[1:]))
    return gaps[len(gaps) // 2]


def snap_period(taps_s: list[float], pressed_s: float) -> float:
    """The loop's length: what was pressed, snapped to the tapped beat.

    Nobody presses LOOP frame-perfectly on the repeat, and a loop 40ms
    long in the wrong direction drifts audibly within four bars. So the
    press names the length and the taps name the grid: if the press is
    within `SNAP_TOLERANCE` of a whole number of beats, that whole
    number is what the person meant. Fewer than two taps carries no
    grid, so the press stands as it is.
    """
    pressed_s = float(pressed_s)
    beat = infer_period(list(taps_s))
    if not beat or beat <= 0.0:
        return pressed_s
    whole = round(pressed_s / beat)
    if whole >= 1 and abs(pressed_s - whole * beat) <= SNAP_TOLERANCE * beat:
        return whole * beat
    return pressed_s


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


def loop_cues(cast: list[dict], events: list[dict], period_s: float,
              palette: list, source: int,
              respect_roles: bool = True) -> list[dict]:
    """One period of a played loop, as cues from t=0.

    `cast` is every bulb the session can drive; an event names the ones
    it strikes, so what a loop touches is what was tapped and the rest
    of the room is left alone. Colour is per BULB — the palette indexed
    by a bulb's place in the cast — so a light keeps its colour across
    every strike of every loop it is in, which is what makes a tapped
    path read as a path rather than a flicker.

    Raises ValueError with a person-readable reason — these come straight
    from a phone screen and the refusal is read there.
    """
    if not cast:
        raise ValueError("no reachable mapped bulbs to play")
    period_s = float(period_s)
    if not MIN_PERIOD_S <= period_s <= MAX_PERIOD_S:
        raise ValueError(
            f"loop period {period_s:.2f}s is outside "
            f"{MIN_PERIOD_S}–{MAX_PERIOD_S}s")
    spot_of = {str(f.get("id")): spot for spot, f in enumerate(cast)}
    # moment -> the cast positions struck there. A dict because two
    # events at one instant are one instant, whatever the phone sent.
    struck: dict[float, set[int]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            at = round(max(0.0, float(event.get("t", 0.0))), 3)
        except (TypeError, ValueError):
            continue
        if at >= period_s:
            continue
        # An id that is not in the cast is a bulb that has gone off the
        # map since the tap: skipped, never a refusal — the rest of the
        # rhythm is still what the person played.
        hit = {spot_of[str(i)] for i in (event.get("ids") or [])
               if str(i) in spot_of}
        if hit:
            struck.setdefault(at, set()).update(hit)
    if not struck:
        raise ValueError("no taps inside the loop — tap some lights first")
    if len(struck) > MAX_EVENTS:
        raise ValueError(f"more than {MAX_EVENTS} taps in one loop")

    # Per bulb, in order, because a bulb is what runs the packets and
    # what the rate ceiling is about.
    times_for: dict[int, list[float]] = {}
    for at in sorted(struck):
        for spot in struck[at]:
            times_for.setdefault(spot, []).append(at)
    busiest = max(len(times) for times in times_for.values())
    if busiest * 2 / period_s > MAX_PER_FIXTURE_HZ:
        raise ValueError(
            "that rhythm is faster than one bulb can follow — slow it "
            "down or spread it across more lights")

    manners = {"respect_roles": bool(respect_roles)}
    actions: list[dict] = []
    for spot, times in sorted(times_for.items()):
        fixture = cast[spot]
        hue, sat = fx._colour(palette, spot)
        for index, at in enumerate(times):
            # The decay runs to this BULB's next strike, not the loop's
            # next event: a bulb struck on beats 1 and 3 glows through
            # beat 2 rather than cutting off under somebody else's hit.
            nxt = times[index + 1] if index + 1 < len(times) \
                else times[0] + period_s
            decay_ms = int(min(MAX_DECAY_S,
                               max(MIN_DECAY_S, nxt - at)) * 1000)
            actions.extend(_strike(fixture, at, decay_ms, hue, sat, manners,
                                   "live"))
    out = compiler._Cues(source, {})
    compiler.render_actions(actions, out)
    return sorted(out.cues, key=_send_time)


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


def _send_time(cue: dict) -> float:
    return cue["t"] - cue.get("lead_ms", 0) / 1000.0


class LiveLoops:
    """The running loops and one-shots of a manual session.

    Owned by the panel, driven by the same engine the conductor uses.
    `stop_all` is hooked onto the conductor's stop, so a show or party
    starting — or Stop being pressed anywhere — takes the loops with it:
    a loop that outlived its session would fight whatever came next for
    the same bulbs, forever.
    """

    def __init__(self, engine) -> None:
        self.engine = engine
        # Sends dropped for being late, over the session's life. Read by
        # the tests and the log; nothing acts on it.
        self.skipped = 0
        self._loops: dict[int, dict] = {}
        self._shots: list[asyncio.Task] = []
        self._pads: dict[str, float] = {}
        self._counter = 0

    # -- what the panel renders ---------------------------------------------
    def describe(self) -> list[dict]:
        return [{"id": loop_id, "label": entry["label"],
                 "period_s": entry["period_s"],
                 "strikes": entry["strikes"],
                 "bpm": round(60.0 / entry["period_s"] * entry["strikes"], 1)
                 if entry["strikes"] else None,
                 "lights": entry["names"],
                 # Which dots the panel marks as looping — the bulbs the
                 # loop actually drives, not the cast it chose them from.
                 "ids": entry["ids"]}
                for loop_id, entry in sorted(self._loops.items())]

    # -- loops ---------------------------------------------------------------
    async def start_loop(self, *, cast: list[dict], events: list[dict],
                         period_s: float, palette: list, label: str,
                         respect_roles: bool = True) -> dict:
        cues = loop_cues(cast, events, period_s, palette, self.engine.source,
                         respect_roles)
        # What the loop drives is read back off the cues rather than
        # re-resolved from the events: one resolver, and the answer is
        # then what was rendered rather than what was asked for.
        serials = {cue["serial"] for cue in cues if cue.get("serial")}
        driven = [f for f in cast if f.get("serial") in serials]
        # One waveform per bulb: a new loop REPLACES any loop it shares a
        # light with. That is the gesture — tapping a new beat onto the
        # lamps means the old beat on the lamps is over.
        for loop_id, entry in list(self._loops.items()):
            if entry["serials"] & serials:
                await self.stop_loop(loop_id, halt=False)
        self._counter += 1
        loop_id = self._counter
        entry = {
            "task": asyncio.create_task(self._run_loop(cues, period_s)),
            "serials": serials,
            "label": label,
            "period_s": round(float(period_s), 3),
            "strikes": len({cue["t"] for cue in cues}),
            "ids": [f.get("id") for f in driven],
            "names": [f.get("label") or f.get("id") for f in driven],
        }
        self._loops[loop_id] = entry
        return {"id": loop_id, "period_s": entry["period_s"],
                "strikes": entry["strikes"], "ids": entry["ids"]}

    async def stop_loop(self, loop_id: int, halt: bool = True) -> bool:
        entry = self._loops.pop(loop_id, None)
        if entry is None:
            return False
        entry["task"].cancel()
        try:
            await entry["task"]
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        if halt:
            # End whatever wave is still running on the loop's bulbs —
            # skipped when a replacement is about to hand them new work.
            await self._halt(entry["serials"])
        return True

    async def stop_all(self) -> None:
        for loop_id in list(self._loops):
            await self.stop_loop(loop_id, halt=False)
        for task in self._shots:
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._shots = []
        self._pads = {}

    def _too_late(self, due: float, tolerance: float) -> bool:
        """Is this send past saving? Counted if so, and then dropped.

        Two reasons, and the second is the one this rework exists for. A
        strike sent late lands off the beat, which is worse than a
        strike nobody hears. And `engine.send_governed` takes its delay
        from a `TokenBucket` whose tokens go NEGATIVE by design: every
        over-budget send deepens a debt the NEXT caller waits out. So a
        stalled loop that catches up by sending its backlog does not
        just arrive late — it buys a queue that the pads, the taps and
        every gesture after them stand behind. Dropping is what keeps a
        stall to the beats it stalled through.

        Pads and taps never come through here: they have no scheduled
        moment to be late for, and they are the presses whose latency is
        the whole product.
        """
        late = time.monotonic() - due
        if late <= tolerance:
            return False
        self.skipped += 1
        return True

    async def _run_loop(self, cues: list[dict], period_s: float) -> None:
        anchor = time.monotonic()
        while True:
            for cue in cues:
                due = anchor + _send_time(cue)
                delay = due - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                if self._too_late(due, LOOP_LATE_S):
                    continue
                try:
                    await self._send(cue)
                except Exception as exc:  # noqa: BLE001 — one strike, not the loop
                    log.warning("live cue failed: %s", exc)
            anchor += period_s
            behind = time.monotonic() - anchor
            if behind > period_s:
                # The event loop stalled past a whole period (a suspend, a
                # busy box): re-anchor rather than machine-gunning the
                # missed strikes into the room.
                anchor = time.monotonic()
            else:
                wait = -behind
                if wait > 0:
                    await asyncio.sleep(wait)

    # -- one-shots -----------------------------------------------------------
    def fire(self, cues: list[dict], label: str = "one-shot") -> dict:
        """Send a cue list once, starting now, without owning the session.

        Unlike `conductor.run_cues` this does not stop anything or touch
        the snapshot — it is a gesture INSIDE a manual session, layered
        over whatever the loops are doing. It returns as soon as the task
        exists, because the caller is a socket frame and the person who
        sent it is waiting on light, not on a reply.
        """
        self._shots = [t for t in self._shots if not t.done()]
        task = asyncio.create_task(
            self._run_once(sorted(cues, key=_send_time)))
        self._shots.append(task)
        return {"ok": True, "cues": len(cues), "label": label}

    def fire_pad(self, cues: list[dict], pad: str) -> dict:
        """A pad, at most once per `PAD_COALESCE_S`.

        A drop is mashed — three fingers, or one hand hitting it twice
        on the way down — and every repeat is the same room going to the
        same black. Sending them all costs a packet per bulb per press
        against a ceiling the taps are also spending, so the repeats are
        answered and not sent.
        """
        now = time.monotonic()
        if now - self._pads.get(pad, 0.0) < PAD_COALESCE_S:
            return {"ok": True, "coalesced": True, "label": pad}
        self._pads[pad] = now
        return self.fire(cues, label=pad)

    async def _run_once(self, cues: list[dict]) -> None:
        anchor = time.monotonic()
        for cue in cues:
            due = anchor + _send_time(cue)
            delay = due - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            if self._too_late(due, SHOT_LATE_S):
                continue
            try:
                await self._send(cue)
            except Exception as exc:  # noqa: BLE001 — one cue, not the gesture
                log.warning("live cue failed: %s", exc)

    # -- the wire ------------------------------------------------------------
    async def _send(self, cue: dict) -> None:
        serial = cue["serial"]
        addr = self.engine._addr(serial)
        packet = bytearray(base64.b64decode(cue["payload_b64"]))
        packet[23] = self.engine._next_sequence()
        await self.engine.send_governed(serial, bytes(packet), addr)

    async def _halt(self, serials: set[str]) -> None:
        for serial in sorted(serials):
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
            except Exception as exc:  # noqa: BLE001 — one bulb, not the stop
                log.warning("could not halt %s: %s", serial, exc)
