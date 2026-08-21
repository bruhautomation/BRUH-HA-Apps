"""The show clock: where in the track the ROOM is, right now.

Anchored once per track: the moment the play command went out, plus the
speaker's calibrated output latency. Monotonic time only — wall clocks
step and slew under NTP, and a show that hiccups because the OS adjusted
the clock is a show debugged at the worst possible moment.

Drift correction slews, never steps. A step is a visible stutter in every
light at once; a few milliseconds per second of slew is invisible and
converges on any real drift long before a track ends.
"""
from __future__ import annotations

import time
from typing import Callable

# How fast the clock may bend toward a drift correction: 8ms of correction
# per second of playback. Sized so the largest plausible mid-track error
# (~150ms) is gone in ~20 seconds without anything visibly lurching.
MAX_SLEW_S_PER_S = 0.008


class ShowClock:
    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._anchor: float | None = None
        self._drift = 0.0            # applied correction, seconds
        self._drift_target = 0.0     # requested correction, seconds
        self._drift_stamp = 0.0

    def anchor(self, play_call_monotonic: float, output_latency_s: float) -> None:
        """Track time 0 = when sound actually starts coming out."""
        self._anchor = play_call_monotonic + output_latency_s
        self._drift = 0.0
        self._drift_target = 0.0
        self._drift_stamp = self._monotonic()

    @property
    def anchored(self) -> bool:
        return self._anchor is not None

    def _applied_drift(self, now: float) -> float:
        if self._drift == self._drift_target:
            return self._drift
        budget = (now - self._drift_stamp) * MAX_SLEW_S_PER_S
        delta = self._drift_target - self._drift
        if abs(delta) <= budget:
            return self._drift_target
        return self._drift + (budget if delta > 0 else -budget)

    def now(self) -> float:
        """Seconds into the track, drift-corrected. Negative while the
        speaker is still swallowing its buffer."""
        if self._anchor is None:
            raise RuntimeError("clock not anchored")
        now = self._monotonic()
        return (now - self._anchor) + self._applied_drift(now)

    def add_drift(self, correction_s: float) -> None:
        """Ask the clock to bend by `correction_s` (positive = the room is
        further into the track than we thought). Applied gradually."""
        now = self._monotonic()
        self._drift = self._applied_drift(now)
        self._drift_stamp = now
        self._drift_target = self._drift + correction_s

    def step_drift(self, correction_s: float) -> None:
        """Apply a correction at once, no slew.

        For a MEASURED error too large for the slew to be honest about: at
        8ms/s an 800ms correction would spend a hundred seconds arriving,
        which is most of a song out of sync on purpose. Past the point
        where the room is visibly wrong, one clean jump is less noticeable
        than a long, deliberate drift through every wrong value between.
        """
        now = self._monotonic()
        self._drift = self._applied_drift(now) + correction_s
        self._drift_target = self._drift
        self._drift_stamp = now

    def sleep_needed(self, until_show_time: float) -> float:
        """Seconds of real time until the show reaches `until_show_time`."""
        return max(0.0, until_show_time - self.now())
