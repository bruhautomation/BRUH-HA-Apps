"""The Manual tab's clock: what bar it is, and when the next one starts.

A DAW has one transport and everything else is measured against it —
clips do not run on periods of their own, they run on bars, and a bar is
a thing the song decides. Manual mode's loops used to free-run from the
instant a button was pressed, so a rhythm played over music drifted out
of it within a few bars however carefully it was tapped: nothing in the
system knew how long a bar was.

Two sources answer the same questions, because a manual session has two
kinds of evening in it:

* **track** — BRight is playing an analyzed track through the conductor,
  so the beats and the downbeats are already known in track seconds and
  `ShowClock` maps them onto monotonic time, drift-corrected and
  anchored at the speaker's own output latency. This is the accurate
  one, and it is the only one that follows a tempo that breathes: a beat
  is looked up in the analyzer's array by index, not multiplied out of
  an average.
* **tapped** — no track, or music something else is playing. A few taps
  give a tempo and the last one gives the phase; `mark_downbeat` is the
  DJ move, tapping once on the "1" to re-phase without re-tempoing.

Bars are numbered from the session, 1-based, and the numbering only ever
goes forward: a tempo change re-anchors on the CURRENT bar rather than
re-deriving bar 1, because a clip stores the bar its cycle aligns to and
renumbering underneath it would move every clip in the session.

Nothing here sleeps, sends or holds state about lights. It answers
questions about time, and `live.py` schedules against it.
"""
from __future__ import annotations

import statistics
import time
from typing import Callable

# 3/4 and 4/4 are the two a light show is ever asked for; anything else is
# a typo, and a bar of 7 would silently reshape every clip in the session.
BAR_BEATS_CHOICES = (3, 4)

# A tempo outside this is not a tempo somebody tapped. Clamped rather than
# refused: the taps are a measurement and the edges are the answer.
MIN_BPM = 40.0
MAX_BPM = 300.0

# Taps kept for the tempo estimate. Eight is two bars of 4/4 — long
# enough to median out one clumsy tap, short enough to follow somebody
# correcting themselves rather than averaging the correction away.
TAP_WINDOW = 8

# Below three taps there are fewer than two gaps, and one gap is a guess.
MIN_TAPS = 3

# Taps further apart than this belong to two different attempts at
# tapping a tempo, not to one.
TAP_RESET_S = 3.0

# Slack for "is this instant on that bar line". Bar lines are computed,
# handed out and asked about again, and floating point loses the last
# bit somewhere in between.
EPS = 1e-6


def median_gap(times: list[float]) -> float | None:
    """The beat, as the median gap. The median rather than the mean
    because a tap session starts with one hesitant gap and the median
    simply does not hear it."""
    if len(times) < 2:
        return None
    gaps = [b - a for a, b in zip(times, times[1:]) if b > a]
    if not gaps:
        return None
    return float(statistics.median(gaps))


class Transport:
    """One grid, two sources, one set of answers."""

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic
                 ) -> None:
        self._mono = monotonic
        self.kind: str | None = None
        self.bar_beats = 4
        # -- track source
        self._beats: list[float] = []
        self._downbeats: list[float] = []
        self._clock = None
        self._bar_base = 0          # index in _downbeats of bar `_bar_origin`
        # -- tapped source
        self._taps: list[float] = []
        self._anchor: float | None = None   # monotonic of `_bar_origin`'s "1"
        # -- shared
        self._bar_origin = 1
        self._beat_s = 0.5
        self._bpm = 120.0

    # -- binding -------------------------------------------------------------
    def bind_track(self, analysis: dict, clock, *, bar_beats: int | None = None
                   ) -> bool:
        """Lock to a track the conductor is playing. False if it cannot.

        A track with no beats, or a clock that was never anchored, has no
        grid to offer — and a transport that pretended otherwise would
        hand every clip a bar line derived from nothing. The caller falls
        back to tapped mode, which is honest about being a guess.
        """
        beats = sorted(float(b) for b in (analysis or {}).get("beats") or []
                       if isinstance(b, (int, float)))
        if len(beats) < 4 or clock is None or not clock.anchored:
            return False
        self.set_bar_beats(bar_beats or self.bar_beats)
        downbeats = sorted(
            float(d) for d in (analysis or {}).get("downbeats") or []
            if isinstance(d, (int, float)))
        # No downbeats is a track the analyzer could not phrase, not a
        # track with no bars: every `bar_beats`-th beat is the honest
        # fallback and it is what the beat grid already implies.
        self._downbeats = downbeats or beats[::self.bar_beats]
        self._beats = beats
        self._clock = clock
        gap = median_gap(beats)
        self._beat_s = gap or self._beat_s
        bpm = (analysis or {}).get("bpm")
        self._bpm = (float(bpm) if isinstance(bpm, (int, float)) and bpm
                     else 60.0 / self._beat_s)
        # Bar 1 is the bar the session STARTS INSIDE, not the next one:
        # numbering from the following downbeat would leave the first
        # seconds of every session in "bar 0".
        now = clock.now()
        self._bar_base = max(
            0, sum(1 for d in self._downbeats if d <= now) - 1)
        self._bar_origin = 1
        self.kind = "track"
        self._taps = []
        return True

    def unbind(self) -> None:
        self.kind = None
        self._clock = None
        self._beats = []
        self._downbeats = []
        self._taps = []
        self._anchor = None
        self._bar_origin = 1

    def set_bar_beats(self, beats: int) -> None:
        beats = int(beats)
        if beats not in BAR_BEATS_CHOICES:
            return
        if beats == self.bar_beats:
            return
        # Re-anchor before the bar length changes, or every existing
        # clip's `start_bar` starts pointing at a different moment. Track
        # mode takes its bar lines from the analyzer's downbeats, which a
        # time signature typed here does not move.
        if self.kind == "tapped" and self.ready:
            self._rebase()
        self.bar_beats = beats

    @property
    def ready(self) -> bool:
        if self.kind == "track":
            return bool(self._beats and self._downbeats
                        and self._clock is not None)
        if self.kind == "tapped":
            return self._anchor is not None
        return False

    @property
    def bpm(self) -> float:
        return round(self._bpm, 2)

    @property
    def beat_s(self) -> float:
        return self._beat_s

    # -- the tapped source ---------------------------------------------------
    def tap(self) -> dict:
        """One tap of the tempo. Three of them are a grid."""
        now = self._mono()
        if self._taps and now - self._taps[-1] > TAP_RESET_S:
            # A long silence is somebody starting again, not a very slow
            # bar: keeping the old taps would median the two attempts
            # together and answer with a tempo nobody played.
            self._taps = []
        self._taps.append(now)
        self._taps = self._taps[-TAP_WINDOW:]
        if len(self._taps) < MIN_TAPS:
            return self.sync_payload()
        gap = median_gap(self._taps)
        if gap:
            self._set_beat_s(gap, phase_at=now)
        return self.sync_payload()

    def set_tempo(self, bpm: float) -> dict:
        """A typed tempo. The phase it already has is kept."""
        bpm = max(MIN_BPM, min(MAX_BPM, float(bpm)))
        self._set_beat_s(60.0 / bpm, phase_at=None)
        return self.sync_payload()

    def mark_downbeat(self) -> dict:
        """Now is a "1". The tempo does not move.

        This is the tap that fixes a grid whose speed is right and whose
        phase is half a beat out — the one gesture a tempo tap cannot
        make, because every tempo tap also moves the tempo.
        """
        now = self._mono()
        if self.kind != "tapped":
            self._to_tapped()
        # The bar starting here takes the NEXT number, so bar numbering
        # never goes backwards under a clip that stored one.
        self._bar_origin = self._bar_number_at(now) + 1
        self._anchor = now
        return self.sync_payload()

    def _to_tapped(self) -> None:
        """Leave the track grid for a tapped one, keeping what is known."""
        now = self._mono()
        if self.ready:
            self._bar_origin = self._bar_number_at(now)
            self._anchor = self.bar_time(self._bar_origin)
        else:
            self._bar_origin = 1
            self._anchor = now
        self.kind = "tapped"
        self._clock = None

    def _set_beat_s(self, beat_s: float, *, phase_at: float | None) -> None:
        beat_s = max(60.0 / MAX_BPM, min(60.0 / MIN_BPM, float(beat_s)))
        if self.kind != "tapped":
            self._to_tapped()
        self._rebase()
        self._beat_s = beat_s
        self._bpm = 60.0 / beat_s
        if phase_at is not None and self._anchor is not None:
            # The most recent tap is a beat boundary: slide the anchor by
            # the sub-beat error rather than re-numbering the bars.
            bar_len = beat_s * self.bar_beats
            offset = (phase_at - self._anchor) % beat_s
            if offset > beat_s / 2.0:
                offset -= beat_s
            self._anchor += offset
            if self._anchor > phase_at:
                self._anchor -= bar_len

    def _rebase(self) -> None:
        """Pin the current bar where it is, so a grid change moves what
        comes NEXT and never what a clip has already aligned to."""
        if not self.ready:
            return
        now = self._mono()
        number = self._bar_number_at(now)
        start = self.bar_time(number)
        self._bar_origin = number
        self._anchor = start

    # -- position ------------------------------------------------------------
    def _track_now(self) -> float:
        return float(self._clock.now())

    def _mono_of(self, track_s: float) -> float:
        """The monotonic instant of a track second, re-derived every time.

        Never cached: the clock slews under drift correction, so an
        offset taken once is an offset that is wrong by however much the
        conductor has since corrected.
        """
        return self._mono() + (float(track_s) - self._track_now())

    def _downbeat_second(self, number: int) -> float:
        """Track second of bar `number`'s downbeat, extrapolating past the
        end of the array rather than refusing."""
        index = self._bar_base + (int(number) - self._bar_origin)
        if index < 0:
            return self._downbeats[0] + index * self.bar_beats * self._beat_s
        if index < len(self._downbeats):
            return self._downbeats[index]
        over = index - (len(self._downbeats) - 1)
        return self._downbeats[-1] + over * self.bar_beats * self._beat_s

    def bar_time(self, bar_index: int) -> float:
        """Monotonic instant of that bar's downbeat."""
        if self.kind == "track":
            return self._mono_of(self._downbeat_second(bar_index))
        anchor = self._anchor if self._anchor is not None else self._mono()
        return anchor + ((int(bar_index) - self._bar_origin)
                         * self.bar_beats * self._beat_s)

    def bar_at(self, when: float | None = None) -> int:
        """Which bar a monotonic instant falls inside (default: now)."""
        return self._bar_number_at(
            self._mono() if when is None else float(when))

    def _bar_number_at(self, when: float) -> int:
        """Which bar the monotonic instant `when` falls inside.

        `EPS` is not decoration: a caller asks this about a bar line it
        was just handed by `bar_time`, and floating point routinely makes
        that instant a fraction of a nanosecond EARLY — which without the
        tolerance answers with the previous bar and starts a clip one bar
        behind where it was armed.
        """
        if not self.ready:
            return self._bar_origin
        if self.kind == "track":
            at = self._track_now() + (when - self._mono()) + EPS
            count = sum(1 for i, d in enumerate(self._downbeats)
                        if i >= self._bar_base and d <= at)
            if count:
                return self._bar_origin + count - 1
            # Before bar 1's downbeat — the session started mid-bar and
            # the analyzer's phrasing puts us behind it.
            return self._bar_origin
        bar_len = self.bar_beats * self._beat_s
        elapsed = when - (self._anchor or when) + EPS
        return self._bar_origin + int(elapsed // bar_len)

    def next_bar_time(self, after: float | None = None) -> float:
        """The next bar line strictly after `after` (default: now)."""
        after = self._mono() if after is None else float(after)
        number = self._bar_number_at(after) + 1
        # One step is enough for a well-formed grid; the loop is what
        # covers a downbeats array with a gap in it, which a real track
        # analysis occasionally has.
        for _ in range(8):
            when = self.bar_time(number)
            if when > after:
                return when
            number += 1
        return self.bar_time(number)

    def _beat_index_of_bar(self, bar_index: int) -> int:
        """Where that bar's downbeat sits in the BEATS array.

        The array is what a clip's events are placed against, so the
        conversion has to go through it — multiplying an average beat by
        an offset is exactly the drift this transport exists to end.
        """
        second = self._downbeat_second(bar_index)
        best, distance = 0, None
        for index, beat in enumerate(self._beats):
            gap = abs(beat - second)
            if distance is None or gap < distance:
                best, distance = index, gap
            elif beat > second:
                break
        return best

    def beat_second(self, bar_index: int, offset_beats: float) -> float:
        """Track second of `offset_beats` after that bar's downbeat.

        Whole beats come out of the beats array by index — so a song that
        breathes is followed exactly — and only a fraction of a beat, or
        an offset past the end of the array, is multiplied out.
        """
        offset = float(offset_beats)
        whole = int(offset // 1)
        frac = offset - whole
        index = self._beat_index_of_bar(bar_index) + whole
        beats = self._beats
        if 0 <= index < len(beats):
            span = (beats[index + 1] - beats[index]
                    if index + 1 < len(beats) else self._beat_s)
            return beats[index] + frac * span
        if index < 0:
            return beats[0] + (index + frac) * self._beat_s
        over = index - (len(beats) - 1)
        return beats[-1] + (over + frac) * self._beat_s

    def beat_time(self, bar_index: int, offset_beats: float) -> float:
        """Monotonic instant of a beat offset inside a bar."""
        if self.kind == "track":
            return self._mono_of(self.beat_second(bar_index, offset_beats))
        return self.bar_time(bar_index) + float(offset_beats) * self._beat_s

    def beats_since(self, bar_index: int, when: float | None = None) -> float:
        """How many beats have passed since that bar's downbeat.

        The inverse of `beat_time`, and it walks the same array for the
        same reason: a tap recorded as "2.5 beats in" against an average
        would land somewhere else when it is played back against the
        song's own beats.
        """
        when = self._mono() if when is None else float(when)
        if self.kind != "track":
            return (when - self.bar_time(bar_index)) / self._beat_s
        at = self._track_now() + (when - self._mono())
        start = self._beat_index_of_bar(bar_index)
        beats = self._beats
        index = start
        while index + 1 < len(beats) and beats[index + 1] <= at:
            index += 1
        span = (beats[index + 1] - beats[index]
                if index + 1 < len(beats) else self._beat_s)
        if at < beats[start]:
            return (at - beats[start]) / self._beat_s
        return (index - start) + (at - beats[index]) / span

    def position(self) -> dict:
        """Where the transport is, as a phone renders it."""
        if not self.ready:
            return {"bar": 0, "beat": 0, "beat_phase": 0.0,
                    "bar_phase": 0.0, "bpm": self.bpm}
        now = self._mono()
        bar = self._bar_number_at(now)
        start = self.bar_time(bar)
        length = max(1e-6, self.bar_time(bar + 1) - start)
        bar_phase = min(1.0, max(0.0, (now - start) / length))
        into = self.beats_since(bar, now)
        into = min(float(self.bar_beats), max(0.0, into))
        beat = min(self.bar_beats, int(into) + 1)
        return {"bar": bar, "beat": beat,
                "beat_phase": round(into - int(into), 4),
                "bar_phase": round(bar_phase, 4), "bpm": self.bpm}

    # -- quantize ------------------------------------------------------------
    def quantize_beats(self, offset_beats: float, division: float) -> float:
        """Snap an offset to the nearest multiple of `division` beats.

        0 (or None) is no quantize, and it is a real setting rather than
        an oversight: a swung or hand-placed pattern is the reason
        somebody turns it off.
        """
        offset = float(offset_beats)
        if not division:
            return offset
        division = abs(float(division))
        return round(offset / division) * division

    # -- what the phone extrapolates from ------------------------------------
    def sync_payload(self) -> dict:
        """Everything a phone needs to run its own playhead for a while.

        Sent on a bind, a tempo change and a slow heartbeat — never per
        beat. A socket frame per beat would be the v1 mistake in a new
        place: the phone can add `beat_s` to `server_now` far more
        reliably than a wifi link can deliver sixteen frames a second.
        """
        position = self.position()
        return {
            "kind": self.kind,
            "ready": self.ready,
            "bpm": self.bpm,
            "beat_s": round(self._beat_s, 5),
            "bar_beats": self.bar_beats,
            "bar": position["bar"],
            "beat": position["beat"],
            "bar_phase": position["bar_phase"],
            "taps": len(self._taps),
            "server_now": self._mono(),
            "next_bar_at": self.next_bar_time() if self.ready else None,
        }
