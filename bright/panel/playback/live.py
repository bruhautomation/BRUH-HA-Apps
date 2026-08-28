"""The Manual tab's engine: lights played by hand, against real music.

A show is compiled ahead and played by the conductor; this is the other
kind of evening — a person with a phone, tapping the beat into one set of
lights, dropping the room to black on the breakdown and flashing it back
on the landing. Semi-manual, semi-automated: every press is immediate,
and the loops a press starts keep running on their own until they are
stopped or replaced.

Three kinds of output, all through the compiler's own packet builder
(`compiler._Cues` + `render_actions`), because a second answer to "how
does an action become bytes" is a second answer waiting to drift:

* **pads** — one-shot, right now: drop (everything to black, fast) and
  flash (a transient pulse to full white that returns to whatever colour
  the bulb was holding — the bulb does the returning, so a flash can
  never strand the room bright).
* **loops** — a tapped rhythm, repeated: the phone records tap moments,
  the server turns one period of them into strike cues (the same
  set-to-peak-then-saw-decay shape the compiled `hit` effect uses) and a
  task replays the period forever. `chase` walks the strikes across the
  selection in map order — a tapped melody travelling through the room —
  and `pulse` lands every strike on every selected light.
* **one-shots** — any catalog effect, fired once for a few seconds at
  the tapped tempo, rendered by `compile_preview` exactly as the Effects
  tab's "run it on the lights" is.

A LIFX bulb runs ONE waveform at a time, so starting a loop stops any
loop that shares a fixture with it — replacement is the gesture, not an
error. Timing lives here rather than in the browser because a phone tab
sleeps, throttles and disconnects; the loop must not.
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

FLASH_MS = 420
DROP_FADE_MS = 80


def infer_period(taps_s: list[float]) -> float | None:
    """The tapped tempo, as one strike period: the median gap.

    The median rather than the mean because a tap session usually starts
    with one hesitant gap, and the median simply does not hear it.
    """
    if len(taps_s) < 2:
        return None
    gaps = sorted(b - a for a, b in zip(taps_s, taps_s[1:]))
    return gaps[len(gaps) // 2]


def loop_cues(cast: list[dict], events: list[float], period_s: float,
              style: str, palette: list, source: int,
              respect_roles: bool = True) -> list[dict]:
    """One period of a tapped loop, as cues from t=0.

    Raises ValueError with a person-readable reason — these come straight
    from a phone screen and the refusal is read there.
    """
    if not cast:
        raise ValueError("no lights selected — tick at least one")
    period_s = float(period_s)
    if not MIN_PERIOD_S <= period_s <= MAX_PERIOD_S:
        raise ValueError(
            f"loop period {period_s:.2f}s is outside "
            f"{MIN_PERIOD_S}–{MAX_PERIOD_S}s")
    cleaned = sorted({round(max(0.0, float(t)), 3) for t in events
                      if float(t) < period_s})
    if not cleaned:
        raise ValueError("no taps inside the loop")
    if len(cleaned) > MAX_EVENTS:
        raise ValueError(f"more than {MAX_EVENTS} taps in one loop")
    strikes_per_fixture = (len(cleaned) if style != "chase"
                           else -(-len(cleaned) // len(cast)))
    rate = strikes_per_fixture * 2 / period_s
    if rate > MAX_PER_FIXTURE_HZ:
        raise ValueError(
            "that rhythm is faster than the bulbs can follow — slow it "
            "down or spread it across more lights (chase)")

    manners = {"respect_roles": bool(respect_roles)}
    actions: list[dict] = []
    for index, at in enumerate(cleaned):
        nxt = cleaned[index + 1] if index + 1 < len(cleaned) \
            else cleaned[0] + period_s
        decay_ms = int(min(MAX_DECAY_S, max(MIN_DECAY_S, nxt - at)) * 1000)
        targets = [cast[index % len(cast)]] if style == "chase" else cast
        for spot, fixture in enumerate(targets):
            # A chase colours by STEP so the pattern travels through the
            # palette as it travels through the room; a pulse colours by
            # fixture so the room holds one look per light.
            hue, sat = fx._colour(palette, index if style == "chase"
                                  else spot)
            peak = fx._cap(fixture, STRIKE_PEAK, manners)
            floor = fx._cap(fixture, min(STRIKE_FLOOR, peak), manners)
            # The compiled `hit` effect's exact shape: a set to the peak
            # with no fade (the attack), then a saw travelling to the
            # floor (the decay) — the bulb runs the envelope.
            actions.append(fx._set(fixture, at, hue, sat, peak, 0,
                                   "live strike"))
            actions.append(fx._wave(fixture, at, hue, sat, floor, decay_ms,
                                    1.0, "saw", 0.5, "live decay"))
    out = compiler._Cues(source, {})
    compiler.render_actions(actions, out)
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
        self._loops: dict[int, dict] = {}
        self._shots: list[asyncio.Task] = []
        self._counter = 0

    # -- what the panel renders ---------------------------------------------
    def describe(self) -> list[dict]:
        return [{"id": loop_id, "label": entry["label"],
                 "style": entry["style"],
                 "period_s": entry["period_s"],
                 "strikes": entry["strikes"],
                 "bpm": round(60.0 / entry["period_s"] * entry["strikes"], 1)
                 if entry["strikes"] else None,
                 "lights": entry["names"]}
                for loop_id, entry in sorted(self._loops.items())]

    # -- loops ---------------------------------------------------------------
    async def start_loop(self, *, cast: list[dict], events: list[float],
                         period_s: float, style: str, palette: list,
                         label: str, respect_roles: bool = True) -> dict:
        cues = loop_cues(cast, events, period_s, style, palette,
                         self.engine.source, respect_roles)
        serials = {f["serial"] for f in cast if f.get("serial")}
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
            "style": style,
            "period_s": round(float(period_s), 3),
            "strikes": len({c["t"] for c in cues}),
            "names": [f.get("label") or f.get("id") for f in cast],
        }
        self._loops[loop_id] = entry
        return {"id": loop_id, "period_s": entry["period_s"],
                "strikes": entry["strikes"]}

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

    async def _run_loop(self, cues: list[dict], period_s: float) -> None:
        anchor = time.monotonic()
        while True:
            for cue in cues:
                delay = anchor + _send_time(cue) - time.monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
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
        over whatever the loops are doing.
        """
        self._shots = [t for t in self._shots if not t.done()]
        task = asyncio.create_task(
            self._run_once(sorted(cues, key=_send_time)))
        self._shots.append(task)
        return {"ok": True, "cues": len(cues), "label": label}

    async def _run_once(self, cues: list[dict]) -> None:
        anchor = time.monotonic()
        for cue in cues:
            delay = anchor + _send_time(cue) - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
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
