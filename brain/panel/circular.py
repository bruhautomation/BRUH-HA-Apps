"""Clock arithmetic that does not break at midnight.

Times of day live on a circle, and every straight-line statistic gets
them wrong at exactly the hour a house goes to bed: half past eleven and
half past midnight are an hour apart and their straight median is noon.
`rhythm.py` had this arithmetic first and `habits.py` borrowed it — and
that borrow closed a ring, because `rhythm` reads `house` for its
progress sentence, `house` reads `routines` for the same, and `routines`
delegates its grading to `habits`. An import ring is not a crash; it is
a module whose answer depends on which of its neighbours somebody
happened to import first, which CodeQL reports and nobody can reproduce
on purpose.

So the four functions live here, in a module that imports nothing of the
panel's, and `rhythm` re-exports them under the names every caller and
every test already uses. One implementation, one place, no ring. The
median is the standard library's rather than `baselines.median`: the two
answer identically, and `baselines` reads `house` for its own progress
sentence, so borrowing it would close the ring one module over.
"""
from __future__ import annotations

import statistics

# A day with nothing on it is a day nobody was home; it is not a 00:00.
MINUTES_PER_DAY = 1440


def circular_median(minutes: list[int]) -> float | None:
    """The middle of a set of times of day, measured around the clock.

    A straight median puts 23:40 and 00:20 at noon, which is not a small
    error — it is the answer pointing at the opposite side of the day.
    The arc that holds every sample most tightly is found first, the
    median is taken inside it, and the result is rotated back.
    """
    if not minutes:
        return None
    best = None
    for offset in sorted(set(minutes)):
        rotated = sorted((m - offset) % MINUTES_PER_DAY for m in minutes)
        span = rotated[-1] - rotated[0]
        if best is None or span < best[0]:
            best = (span, offset, rotated)
    _span, offset, rotated = best
    return (statistics.median([float(v) for v in rotated])
            + offset) % MINUTES_PER_DAY


def circular_distance(a: float, b: float) -> float:
    """How far apart two times of day are, the short way round.

    Never more than twelve hours: 23:50 is twenty minutes from 00:10, not
    twenty-three hours and forty. Lifted out of `circular_spread` so that
    "how far is this press from its usual time" has one implementation —
    `manual_ledger.off_pattern` asks it of a single press, where a second
    copy of the modular arithmetic is the drift this file exists to
    prevent one of.
    """
    d = abs(a - b) % MINUTES_PER_DAY
    return min(d, MINUTES_PER_DAY - d)


def circular_spread(minutes: list[int], centre: float) -> float:
    """How far these times stray from their centre, the short way round."""
    if not minutes:
        return 0.0
    return statistics.median([circular_distance(m, centre) for m in minutes])


def clock(minutes: float | None) -> str:
    """`437.0` as `07:17`. Empty for nothing, never as `00:00`."""
    if minutes is None:
        return ""
    total = int(round(minutes)) % MINUTES_PER_DAY
    return f"{total // 60:02d}:{total % 60:02d}"


__all__ = ["MINUTES_PER_DAY", "circular_distance", "circular_median",
           "circular_spread", "clock"]
