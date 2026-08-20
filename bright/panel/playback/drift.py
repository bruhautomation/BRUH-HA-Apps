"""Drift: is the room where the clock thinks it is?

Fed from the media player's own position reports — but only when the
calibration wizard proved this player's `media_position` trustworthy, and
even then smoothed and bounded. A wrong correction is worse than none:
open-loop drift over a four-minute track on a monotonic clock is
milliseconds, while one bad position report could yank the show seconds.
"""
from __future__ import annotations

# Ignore corrections smaller than this — inside measurement noise.
DEADBAND_S = 0.060
# A report this far out is a lie (a paused player, a stale attribute, a
# different track), not a drift.
MAX_PLAUSIBLE_S = 1.5
# EMA weight for each new report.
ALPHA = 0.4


class DriftEstimator:
    def __init__(self) -> None:
        self._error = 0.0
        self._reports = 0

    def report(self, player_position_s: float, show_time_s: float) -> float | None:
        """One position report against the clock. Returns a correction to
        apply (seconds), or None when nothing should change."""
        error = player_position_s - show_time_s
        if abs(error) > MAX_PLAUSIBLE_S:
            return None
        self._reports += 1
        self._error = error if self._reports == 1 else (
            ALPHA * error + (1 - ALPHA) * self._error)
        if self._reports < 2:  # never act on a single report
            return None
        if abs(self._error) < DEADBAND_S:
            return None
        correction = self._error
        # The clock will slew there; consider it handled.
        self._error = 0.0
        return correction
