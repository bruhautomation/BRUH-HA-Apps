"""The shape of when somebody does something — one arithmetic, three ledgers.

Three modules keep evidence about what a person does by hand, and every
one of them had to answer the same question about it: *is there a shape
here, what is it, and does it still hold?* `routines.py` answered it to
decide whether to build a time trigger, `override_ledger.py` to decide
whether "you undo this every weekday morning" was sayable, and
`manual_ledger.py` to decide whether a press was odd enough to be worth
a question. Three answers to one question is the drift a second copy
always produces, and it had already started: the same circular median
was written out three times, the day floor meant "separate days" in two
of them and "distinct events" in a third, and only one of the three
counted a **denominator** at all.

So the ledgers stay — the files are somebody's, the on-disk shapes are
somebody's, and `record`/`load`/`save`/`progress` all belong to the
module that owns the data. What moved here is the derivation, and
nothing else. Each of the three keeps its own floors, its own
vocabulary and its own refusals; what it no longer keeps is its own
arithmetic.

Five things are load-bearing, and every one of them arrived as a bug in
one of the three.

**A count is not evidence without a denominator.** A press that happened
four times is a habit or a coincidence depending entirely on how many
days it could have happened on, and `auto.overridden` shipped without
that number. `share` is `days / eligible_days`, always.

**The denominator is counted in the shape that was CLAIMED, and an
unclaimed shape is graded against every day.** A weekday habit graded
against every day in the window reports five days in seven as 71% and
refuses a habit that never misses — so a caller claiming `weekdays`
gets weekdays in the denominator. But an *observed* label is a
description of what happened rather than a claim about it, and letting
it narrow the denominator would let every set of presses define its own:
ten weekday presses would observe "weekdays", be graded against
weekdays, and come out at 100% by construction. So `shape=None` is
graded against the calendar.

**Days, never presses.** Six presses in one evening is one evening, and
a floor counted in events is a floor that a single busy Tuesday clears.

**The median is CIRCULAR, and so is everything measured against it.**
Half past midnight and half past eleven are forty minutes apart, and a
straight median of them is noon — not a small error but the opposite
side of the day. `rhythm.py` had this first and the arithmetic is its,
imported rather than copied, which is the rule this module exists to
apply one level up — it lives in `circular.py` now, a leaf both modules
read, because `rhythm` reads `house`, `house` reads the ledgers and the
ledgers read this file: the borrow closed an import ring. The join over
the three ledgers (`habit_of`) is `habit_lookup.py` for the same reason,
since a module the ledgers import may not import the ledgers back.

**And a shape has to still be happening.** A sixty-day ledger goes on
holding a beautiful March for a habit somebody stopped in March, and a
producer that could not tell reports it for eight weeks after it ended.
`still_happening` is measured off the last stamp against the pass's own
`now`, and it is a **field** rather than a refusal: `routines.mine`
drops a stale group before it grades anything, where `pattern` and
`shape` refuse on the graded answer, and a module that forced one of
those orders on the other two would be deciding something that is not
its to decide.

Nothing here decides anything — the same split `baselines.py`,
`closures.py` and `thermal.py` keep, and the reason the three ledgers
still own their own floors. This answers *what is the shape*; what a
shape is worth is the producer's, and whether it is true is a person's.
"""
from __future__ import annotations

import datetime as dt
import time

import circular

EVERY_DAY = "every day"
WEEKDAYS = "weekdays"
WEEKENDS = "weekends"
SHAPES = (EVERY_DAY, WEEKDAYS, WEEKENDS)

DAY_S = 86400.0

# How much of the day a set of presses has to fall inside before the hour
# is worth naming, and how much of them have to be in it. These are the
# defaults `override_ledger` was written with; it passes its own.
BAND_HOURS = 4

# What `share` has to reach before a sentence says "every" rather than
# "most". Prose thresholds, deliberately not floors: nothing is refused
# here, the only thing that changes is the word.
SAYS_EVERY = 0.9
SAYS_NEARLY_EVERY = 0.7


# ---------------------------------------------------------------------------
# Which days a shape claims
# ---------------------------------------------------------------------------

def in_shape(day, shape: str) -> bool:
    """Does this day (a date or a datetime) fall inside this shape?

    One function over both, because the eligible-day count walks dates
    and the filter walks stamps, and two readings of "is this a weekend"
    is exactly the kind of second copy this module exists to remove.
    """
    weekend = day.weekday() >= 5
    return (shape == EVERY_DAY
            or (shape == WEEKDAYS and not weekend)
            or (shape == WEEKENDS and weekend))


def eligible_days(shape: str, first: float, last: float, tz) -> int:
    """How many days a routine of this shape COULD have happened on.

    The denominator. Counted in local dates rather than in 86,400-second
    blocks, because a press that drifts an hour later each day is still
    one press a day and a divisor counting whole days from the first
    stamp would lose one of them to the drift.
    """
    start = dt.datetime.fromtimestamp(first, tz).date()
    end = dt.datetime.fromtimestamp(last, tz).date()
    n, day = 0, start
    while day <= end:
        if in_shape(day, shape):
            n += 1
        day += dt.timedelta(days=1)
    return n


def observed_shape(whens: list) -> str:
    """Which days these presses actually fell on.

    A description and never a claim — see the header. All on weekdays is
    `weekdays`, all at weekends is `weekends`, and anything mixed is
    `every day`, which each caller renders in its own words (`any day`
    in the manual ledger, nothing at all in the override ledger, because
    a mixed week is not a claim either of them makes).
    """
    if not whens:
        return EVERY_DAY
    weekend = sum(1 for w in whens if w.weekday() >= 5)
    if weekend == 0:
        return WEEKDAYS
    if weekend == len(whens):
        return WEEKENDS
    return EVERY_DAY


# ---------------------------------------------------------------------------
# When of the day
# ---------------------------------------------------------------------------

def band(hours: list[int], *, band_hours: int = BAND_HOURS,
         band_share: float | None = None) -> tuple[int, int, float] | None:
    """The tightest hours that hold most of these, as `(start, end, share)`.

    Two things this must not do, and the second was found by driving it.

    It **wraps midnight**, because "late evening" is 22:00–01:00 in a
    great many households and a window that could not cross it would
    report the busier half and call that the answer.

    And it reports the hours that are actually **occupied**, not the
    search window that found them. Fifteen overrides all at 08:10 fit
    inside a four-hour window starting at 05:00 just as well as one
    starting at 08:00, and the first version took whichever start it
    tried first: it said *"almost always between 05:00 and 09:00"* about
    something that only ever happens at ten past eight. That is not a
    slightly loose answer — it is a condition somebody would write, which
    would stand the automation down for three hours nothing happens in.
    So the window is only the search, and what comes back is the span
    from the first occupied hour in it to the last.

    `band_share` is optional and gates rather than describes: handed one,
    a band that does not hold that share comes back as `None` instead of
    as a weak answer. Left out, the band is returned whatever it holds,
    which is what a caller wanting to report the share itself needs.
    """
    if not hours:
        return None
    best = None
    for start in range(24):
        offsets = sorted((h - start) % 24 for h in hours
                         if (h - start) % 24 < band_hours)
        if not offsets:
            continue
        # More of them is better; a tie goes to the tighter span, which
        # is what stops a window being reported instead of the hours.
        rank = (len(offsets), -(offsets[-1] - offsets[0]))
        if best is None or rank > best[0]:
            best = (rank, start, offsets)
    if best is None:
        return None
    _rank, start, offsets = best
    out = ((start + offsets[0]) % 24,
           (start + offsets[-1] + 1) % 24,
           len(offsets) / len(hours))
    if band_share is not None and out[2] < band_share:
        return None
    return out


# ---------------------------------------------------------------------------
# The one grading
# ---------------------------------------------------------------------------

def _stamps(values) -> list[float]:
    out = []
    for raw in values or []:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        out.append(float(raw))
    return out


def grade(stamps: list[float], tz=None, now: float | None = None, *,
          min_days: int, min_share: float = 0.0,
          max_spread_min: float | None = None,
          recent_days: float | None = None,
          shape: str | None = None,
          band_hours: int | None = None,
          band_share: float | None = None) -> dict | None:
    """Does this set of stamps hold up as a shape of this kind?

    `None` rather than a weak answer, the rule all three ledgers already
    kept: a set of times nobody would recognise as a pattern, reported as
    if it were one, invites somebody to write a condition around a
    coincidence — and each of the three then spends something on it (a
    proposal, a finding, a Claude run).

    Every floor is the caller's. A time trigger is wrong if it fires at
    the wrong end of an hour and a *question* is answerable about "most
    evenings", so `manual_ledger` is looser than `routines` on purpose;
    what they share is the arithmetic, not the bar.

    `max_spread_min` and `min_share` left out mean *no such floor*, which
    is how `override_ledger.pattern` — which reports a band rather than a
    time and has never had either — asks this question.
    """
    tz = tz or dt.timezone.utc
    now = time.time() if now is None else now
    kept = []
    for ts in _stamps(stamps):
        when = dt.datetime.fromtimestamp(ts, tz)
        if shape and not in_shape(when, shape):
            continue
        kept.append((ts, when))
    if not kept:
        return None

    whens = [w for _ts, w in kept]
    days = {w.date() for w in whens}
    if len(days) < min_days:
        return None

    minutes = [w.hour * 60 + w.minute for w in whens]
    centre = circular.circular_median(minutes)
    if centre is None:
        return None
    spread = circular.circular_spread(minutes, centre)
    if max_spread_min is not None and spread > max_spread_min:
        return None

    first = min(ts for ts, _w in kept)
    last = max(ts for ts, _w in kept)
    # Claimed, never observed — see the header. An observed label used as
    # its own denominator scores every set of presses at 100%.
    eligible = eligible_days(shape or EVERY_DAY, first, last, tz)
    if eligible <= 0:
        return None
    share = len(days) / eligible
    if share < min_share:
        return None

    return {
        "shape": shape or observed_shape(whens),
        "days": len(days),
        "eligible_days": eligible,
        "share": round(share, 3),
        "median_minute": centre,
        "at": circular.clock(centre),
        "spread_min": round(spread, 1),
        "band": band([w.hour for w in whens], band_hours=band_hours,
                     band_share=band_share) if band_hours else None,
        "first": first,
        "last": last,
        # A field and not a refusal. See the header: the three callers
        # apply it at three different points in their own passes, and
        # only they know which.
        "still_happening": (recent_days is None
                            or (now - last) <= recent_days * DAY_S),
        "stamps": len(kept),
    }


def best_shape(stamps: list[float], tz=None, now: float | None = None,
               **floors) -> dict | None:
    """The narrowest true claim about which days these fall on.

    `every day` only when BOTH halves of the week hold up on their own.
    A habit on ten weekdays and one Sunday clears a whole-window share
    comfortably — ten days out of fourteen — and calling it `every day`
    builds a trigger that fires on two mornings it was never wanted on.
    So the broad claim has to be earned twice, once on each half, and
    what a not-quite-daily habit falls back to is the narrower true
    statement rather than the wider convenient one.

    This is deliberately **not** "whichever shape scores highest". That
    reading is the bug: `every day` is graded against every day in the
    window, which is the loosest denominator available, so the one sloppy
    Sunday that makes the claim wrong is also what makes it win.

    The cost is worth naming: a genuinely daily habit reads as
    `weekdays` for its first three weeks, because six weekend days take
    that long to accrue. That is the same floor `rhythm` pays for
    measuring weekends apart, and it is the cheaper mistake — a routine
    that misses two days a week is a smaller wrong than one that fires
    on two mornings somebody is asleep.
    """
    week = grade(stamps, tz, now, shape=WEEKDAYS, **floors)
    end = grade(stamps, tz, now, shape=WEEKENDS, **floors)
    if week and end:
        # Both halves hold up on their own — at the SAME time. A habit at
        # 07:00 on weekdays and 10:00 at weekends is two clean shapes,
        # and the merged set does not refuse it: the spread is a median
        # deviation, so fifteen weekday presses hide six weekend ones
        # completely and `every day at 07:00` comes out with a spread of
        # zero. That is the trigger this function exists to refuse — a
        # daily 07:00 in a house that sleeps until ten on Sundays — so
        # the halves have to agree on the hour before the union is asked,
        # and a refusal either way falls back to the narrower true claim.
        limit = floors.get("max_spread_min")
        # Both rounded, because that is the minute each half would be
        # reported at and a comparison against a figure nobody is shown
        # can refuse a pair that agrees on the clock.
        apart = circular.circular_spread([round(end["median_minute"])],
                                       round(week["median_minute"]))
        if limit is None or apart <= limit:
            daily = grade(stamps, tz, now, shape=EVERY_DAY, **floors)
            if daily:
                return daily
        return week if week["days"] >= end["days"] else end
    return week or end


# ---------------------------------------------------------------------------
# One press against its own shape
# ---------------------------------------------------------------------------

def odd_press(stamp: float, stamps_excluding_it: list[float], tz=None, *,
              spreads: float, floor_min: float, min_days: int,
              shape: dict | None = None, now: float | None = None,
              **floors) -> dict | None:
    """Is this press far enough outside its subject's own shape to be news?

    Two rules, and both of them are about what the press is measured
    against rather than about the distance.

    **The press is excluded from the shape it is judged against.** A
    press included in its own baseline drags the centre toward itself,
    which is how the oddest thing in the house comes out ordinary — so
    what arrives here is everything *but* it.

    **And the subject has to already HAVE a shape**, which is what
    `min_days` is: asked of a subject with none, the first press on a
    newly installed device is the strangest event in the house every
    time something is fitted.

    The distance is measured the short way round, because 23:50 is twenty
    minutes from 00:10 and a straight subtraction makes every late
    evening the oddest press ever recorded.

    A caller judging several presses against one history hands the graded
    `shape` in rather than letting this re-derive it per press: it is the
    same history every time, and the answer must not depend on which
    press asked for it.
    """
    tz = tz or dt.timezone.utc
    if shape is None:
        shape = grade(stamps_excluding_it, tz, now, min_days=min_days,
                      **floors)
    if not shape or shape["days"] < min_days:
        return None
    allowance = max(floor_min, shape["spread_min"] * spreads)
    when = dt.datetime.fromtimestamp(float(stamp), tz)
    minute = when.hour * 60 + when.minute
    away = circular.circular_distance(minute, round(shape["median_minute"]))
    if away <= allowance:
        return None
    return {
        "minute": minute,
        "at": circular.clock(minute),
        "away_min": round(away),
        "allowance_min": round(allowance),
        "usually_at": shape["at"],
        "usually_spread_min": shape["spread_min"],
        "shape": shape,
    }


# ---------------------------------------------------------------------------
# One entity, one answer
# ---------------------------------------------------------------------------

_VERBS = {
    "on": "switch {name} on",
    "off": "switch {name} off",
    "open": "open {name}",
    "closed": "close {name}",
    "playing": "start {name} playing",
    "paused": "pause {name}",
}


def _part_of_day(minute: float) -> str:
    hour = int(round(minute)) // 60 % 24
    if 5 <= hour < 12:
        return "mornings"
    if 12 <= hour < 17:
        return "afternoons"
    if 17 <= hour < 22:
        return "evenings"
    return "nights"


def _how_often(share: float) -> str:
    if share >= SAYS_EVERY:
        return "every"
    if share >= SAYS_NEARLY_EVERY:
        return "nearly every"
    return "most"


def _how_long(first: float, last: float) -> str:
    """How long this has been going on, in the coarsest unit that is true.

    Weeks past a fortnight, days below it, and nothing at all for a shape
    that spans less than two days — because "and have for 1 day" is a
    sentence that makes the claim sound smaller than the evidence.
    """
    span = max(0.0, (last - first) / DAY_S)
    if span >= 14:
        return f"{int(span // 7)} weeks"
    if span >= 2:
        return f"{int(round(span))} days"
    return ""


def sentence_for(name: str, state: str, shape: dict | None,
                 overrides: list[dict] | None = None,
                 automated: bool = False) -> str:
    """What this entity's habit is, in the words a person would use.

    Deterministic and nowhere near a model: this is a sentence about
    numbers that are already measured, and a Claude run to phrase one is
    a run spent on something arithmetic already knows. Every clause is
    something the shape says — the frequency is the share, the time is
    the median, the span is the first and last stamp — so a sentence and
    the numbers beside it cannot disagree.
    """
    name = name or "it"
    parts = []
    if shape:
        template = _VERBS.get(state) or "set {name} to " + (
            str(state or "that").replace("{", "").replace("}", ""))
        verb = template.format(name=name)
        when = {WEEKDAYS: "weekday ", WEEKENDS: "weekend "}.get(
            shape.get("shape") or EVERY_DAY, "")
        said = ("You {verb} {often} {when}{part} around {at}".format(
            verb=verb, often=_how_often(float(shape.get("share") or 0.0)),
            when=when, part=_part_of_day(shape.get("median_minute") or 0),
            at=shape.get("at") or ""))
        span = _how_long(float(shape.get("first") or 0.0),
                         float(shape.get("last") or 0.0))
        if span:
            said += f", and have for {span}"
        if not shape.get("still_happening", True):
            said += " — though not lately"
        parts.append(said + ".")
    else:
        parts.append(f"Nothing you do to {name} by hand has a shape yet.")

    for row in overrides or []:
        by = row.get("name") or row.get("automation") or "an automation"
        said = "You put {by} back {n} times on {d} separate days".format(
            by=by, n=row.get("events") or 0, d=row.get("days") or 0)
        hours = row.get("band")
        if hours:
            said += ", mostly between {:02d}:00 and {:02d}:00".format(
                hours[0], hours[1])
        parts.append(said + ".")

    if automated:
        parts.append("Something in Home Assistant already does this.")
    return " ".join(parts)


__all__ = [
    "BAND_HOURS", "DAY_S", "EVERY_DAY", "SAYS_EVERY", "SAYS_NEARLY_EVERY",
    "SHAPES", "WEEKDAYS", "WEEKENDS", "band", "best_shape", "eligible_days",
    "grade", "in_shape", "observed_shape", "odd_press",
    "sentence_for",
]
