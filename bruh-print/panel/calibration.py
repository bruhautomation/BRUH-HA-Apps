#!/usr/bin/env python3
"""Four coordinates off a printed grid, and the rectangle they name.

**The question is where the printable area is, and 0.9.x asked it as an
offset.** That was the whole trouble, and it went unnoticed through a
rewrite that was otherwise about the right things. 0.6.0 to 0.8.x answered a
misaligned label by adding a box to type a millimetre into, until there were
four with four signs and four meanings; 0.9.0 replaced them with one measured
`Calibration` and 0.9.1 rewrote the instructions for reading it. Both of those
were improvements and neither touched the shape of the question, which was:
*how far is raster row 0 from the die cut, and which way?*

A distance-and-a-direction is a hard thing to read off a piece of paper, and
it is hard for a reason that no amount of better wording could reach. It is
not a thing that is drawn on the label. It has to be **inferred** — from
which end of a ladder was cut, from whether a heavy bar is on the paper, from
one copy compared against another — and the sign is exactly the part that
cannot be seen. That is why 0.9.0 had three hypotheses (a dead band on every
label, a band on the first label of a job, a printer not finding the sense
hole at all) and why they are identical from a photograph: they are three
different offsets, and an offset is not a mark.

**A rectangle is a mark.** Print a numbered grid over the whole area the
printer can reach — the full width of the head, and further down the roll
than one label — and the label lies on it. Where its four edges fall on that
grid is not inferred from anything: it is read, the way a coordinate is read
off graph paper, and it needs no sign because a coordinate has none. Four
numbers, one shape, no hypotheses:

    X1, X2   where the label's left and right edges fall on the across scale
    Y1, Y2   where its leading and trailing die cuts fall on the feed scale

and the printable area of a label on this printer, in the printer's own
axes, is that rectangle. Everything the print path needs is arithmetic on it
and nothing else: `across_mm` is X1, the length is Y2 − Y1, and where the
printing starts relative to the die cut is Y1 — signed by which side of zero
it lands on rather than by anything a person has to decide.

**The one thing the grid cannot show, and why it costs nothing.** Nothing can
print before row 0, so a printer that starts *late* has its label's leading
edge above the grid entirely and Y1 is not readable there. The answer is that
0 is the honest reading and also the useful one: the printable area starts at
the first row that can carry ink, which is the grid's own 0, and a label is
laid out from there. How much of the label is lost above it — the dead band —
is `catalog length − (Y2 − Y1)`, derived and reported rather than measured,
and it is a number nobody has to act on because there is nothing to be done
about it. 0.9.x asked for that band directly and could not have it: it is the
one region of the label with nothing printed in it.

So the reading never branches. Y1 is a coordinate on a scale that starts at
0, and *it is 0 when the label starts above the scale* — which is not a
special case to be explained, it is what reading a coordinate off a scale
does at the end of the scale.

**What this deliberately stops measuring**, because the honesty is the point:
`after_tear_mm` (a first label of a job that starts later than the rest) and
`gap_mm` (the hole-to-hole pitch, knowable only when the printer is not
finding the hole) both needed two printed copies compared against each other.
Neither has ever been confirmed on a real printer — `gap_mm` was plumbed
correctly, changed the bytes and moved nothing, which is the measurement that
proved this printer *does* find the sense hole — and chasing them is what made
the wizard ask six numbers across two labels with two of them read from the
opposite end. Both fields stay on `Calibration`: a roll calibrated under 0.9.x
keeps whatever it measured and the print path is unchanged. Nothing here sets
them any more.

Everything is pure: four readings and a stock in, an outcome out, no store
and no printer. That is what lets the arithmetic be driven with the numbers
the owner actually measured rather than with a story about them.
"""
from __future__ import annotations

from dataclasses import dataclass

from stores.stock import Calibration

# How far a coordinate may sit from zero and still be read as zero.
#
# It decides one thing only and it is a much smaller thing than 0.9.x's
# tolerance decided: whether the label's leading edge is on the grid or above
# it. Below this, Y1 is "the label starts at or before the first row the
# printer lays" and the printable area begins at the grid's own origin;
# above it, the die cut cut the grid and the number it cut it at is where
# the printing starts. A person reading a printed millimetre scale is honest
# to a few tenths, so this is generous to the reading and still nowhere near
# the millimetre at which the two answers differ in any way anybody can see.
TOL_MM = 0.7

# How far the measured WIDTH may differ from the catalog before it is worth
# mentioning. The catalog carries a roll's nominal size and real die cuts are
# within a few tenths of it, so a millimetre is comfortably outside the
# measurement and comfortably inside "somebody has the wrong roll loaded".
CATALOG_TOL_MM = 1.0

# And how close the two measurements have to be to the catalog's OTHER
# dimension before this says they look transposed. Wider than the tolerance
# above on purpose: it is a suggestion about somebody's stock row rather than
# a correction to it, and a suggestion that only fires on a perfect match is
# a suggestion nobody ever sees.
SWAP_TOL_MM = 1.5

# The furthest a printer may be said to start late before the number stops
# being about a printer. Top-of-form registration is a fraction of an inch —
# DYMO's own PPD declares 1.5mm unprintable at each feed end and the worst
# this add-on has been shown is 4.7mm — so twelve is comfortably past any
# registration fault and comfortably short of a roll that is simply not the
# length the catalog says. It matters because a late start is derived FROM
# the catalogued length: a roll whose real label is shorter than its stock
# row claims would otherwise come back as an enormous dead band, with nothing
# in the arithmetic to say the stock was wrong instead.
MAX_LATE_MM = 12.0

# And the same bound the other way. An early start is directly measured — Y1
# is on the grid — so this is not protecting the arithmetic from anything; it
# is catching a Y1 read off the wrong scale, which on a grid with two of them
# is the one mistake worth naming. A printer that begins a centimetre before
# the die cut would be laying most of the previous label's tail.
MAX_EARLY_MM = 12.0

# How far a measured label length may differ from the catalog before the
# reading is more likely to be of a different label than of this one. Half
# the catalog is deliberately loose: a real disagreement of a few millimetres
# is news worth storing (that is what `length_mm` is for), and only something
# that is not this stock at all should be refused.
LENGTH_SANITY = 0.5


@dataclass(frozen=True)
class Readings:
    """Where the label's four edges fall on the printed grid, in millimetres.

    Coordinates, not distances — which is the whole of the change. Every one
    is read the way a point is read off graph paper: find the edge, follow it
    to the scale, say what the scale says. None of them is a measurement of a
    gap between two things and none of them carries a direction, so there is
    nothing for a person to get the wrong way round.

    `x1` / `x2` — the across scale, which runs from head dot 0 across the
    whole print head. `x2` is optional because a label wider than the head
    runs off the end of the scale and there is nothing out there to read;
    `x1` is not, because the across axis is built on it.

    `y1` / `y2` — the feed scale, which runs from the first row the printer
    lays down the sheet. `y1` is **0 when the label's leading edge is above
    the scale**, which is what a printer starting after the die cut looks
    like: it lays no ink up there, so the scale does not reach and 0 is both
    the honest reading and the useful one. See the module docstring.
    """

    x1: float
    y1: float
    y2: float
    x2: float | None = None


@dataclass(frozen=True)
class Outcome:
    """What to store, what to say, and what the readings looked like.

    `calibration` is `None` for exactly one case now — readings whose
    arithmetic is impossible — where 0.9.x had two. The other one was the
    first half of a two-print hypothesis, and it is gone with the second
    print: there is one job, one grid and one answer.

    `sentence` is what a person is shown, and it names what the printer does
    in plain words rather than reporting the numbers back at them.

    `shape` names which of the three readings this was, for the tests and the
    panel and for nothing a person sees. It replaces 0.9.x's `hypothesis`,
    which was the right word for a thing being guessed at and is the wrong
    one for a rectangle that was measured.

    `swap_suggested` is never acted on here. The two measurements looking
    transposed is evidence about somebody's stock row, and quietly swapping a
    roll's dimensions because of one reading is exactly the sort of helpful
    correction that loses a measurement they made with a ruler.
    """

    calibration: Calibration | None
    sentence: str
    shape: str
    swap_suggested: bool = False

    def as_dict(self) -> dict:
        return {
            "calibration": (self.calibration.as_dict()
                            if self.calibration else None),
            "sentence": self.sentence,
            "shape": self.shape,
            "swap_suggested": self.swap_suggested,
        }


HOLD_SIDES = ("leading", "trailing", "left", "right")


def _clamp_holds(asked, stock) -> tuple[dict, dict]:
    """The four asked-for bands, floored and capped against their own axis.

    Returns what will be stored and what was asked for, so the caller can
    say which sides were cut down. Capping matters because
    `printable_box`'s own floor would absorb an over-long band silently —
    the canvas would come back a millimetre tall with nothing anywhere
    saying why — and it is per AXIS because the two bands on one axis
    share the label between them: 20mm held at each end of a 31.75mm label
    is not two separate over-asks, it is one pair that does not fit.
    """
    asked = {side: max(0.0, float((asked or {}).get(side) or 0.0))
             for side in HOLD_SIDES}
    held = dict(asked)
    for a, b, span in (("leading", "trailing", stock.feed_mm),
                       ("left", "right", stock.across_mm)):
        room = max(0.0, span - 1.0)
        total = held[a] + held[b]
        if total > room and total > 0:
            # Scaled rather than truncated, so a pair asked for evenly stays
            # even — the commonest reason to set two at once is to centre
            # something, and cutting only the second would silently move it.
            held[a] = round(held[a] * room / total, 2)
            held[b] = round(held[b] * room / total, 2)
    return {k: round(v, 2) for k, v in held.items()}, asked


def derive(readings: Readings, stock, *, holds=None,
           hold: float | None = None, now: float | None = None) -> Outcome:
    """Four coordinates and a stock, in; what this roll does, out.

    The order is the order the numbers are checked in and not the order they
    are read in: the two feed coordinates decide everything about where the
    printing starts, and the two across ones only ever set one field and add
    a note. A refusal short-circuits, because a sentence about a rectangle
    whose own arithmetic does not close is a sentence about nothing.

    `holds` is the four inputs here that are not read off a label, and they
    are a separate argument for exactly that reason: they are how much of
    each edge to leave blank because somebody said so, and they are carried
    onto the `Calibration` untouched rather than derived from anything. They
    are not readings and must never be confused with them — the four
    coordinates say where the PAPER is, which is a fact this can check, and
    these say where to print on it, which is a preference it may not.

    `hold` is 0.11.0's single trailing band, kept because a panel served
    before this update still sends it under that name. It is read only when
    `holds` is absent, so the newer field always wins where both arrive.

    `now` is the clock the caller is already holding, not one read in here.
    It is the only other thing on a `Calibration` that is not derived from a
    label, and it is passed rather than taken so this stays a function the
    same readings can be handed twice.
    """
    catalog = stock.feed_mm
    start, length, refusal = _feed_axis(readings.y1, readings.y2, catalog)
    if refusal:
        return Outcome(None, refusal, "impossible")

    width, refusal = _across_axis(readings.x1, readings.x2)
    if refusal:
        return Outcome(None, refusal, "impossible")

    # One test, so the note and the stored field can never disagree about
    # whether the label is the length its row says. A measurement that merely
    # confirms the catalog is a second copy of a number already on the row,
    # and a second copy is what drifts the day somebody corrects one.
    stored_length = (length if length is not None
                     and abs(length - catalog) > CATALOG_TOL_MM else None)
    if holds is None and hold is not None:
        holds = {"trailing": hold}
    held, asked = _clamp_holds(holds, stock)
    notes = _catalog_notes(stock, width, stored_length)
    notes.extend(_hold_notes(held, asked))
    swap = _looks_transposed(stock, width, length or catalog)
    cal = Calibration(
        across_mm=round(readings.x1, 2),
        hold_leading_mm=held["leading"],
        hold_trailing_mm=held["trailing"],
        hold_left_mm=held["left"],
        hold_right_mm=held["right"],
        # Inside the tolerance is stored as nothing at all rather than as the
        # tenths that were read. A person against a millimetre scale is not
        # accurate to a tenth, and 0.4mm saved as a correction crops a row
        # off every label for a number that describes the reading rather than
        # the printer — while `measured_at` still reports the roll as lined
        # up, which is the honest half of it.
        start_mm=0.0 if abs(start) <= TOL_MM else round(start, 2),
        # Both of the two-print fields keep their defaults rather than
        # carrying anything over from a previous calibration of this roll.
        # A new measurement replaces the old one whole: half a rectangle
        # from today beside half an offset from March is a roll calibrated
        # by two different readings, which is worse than either.
        after_tear_mm=0.0,
        length_mm=None if stored_length is None else round(stored_length, 2),
        gap_mm=None,
        job_start="plain",
        # Not derived from anything and left as the roll had it. It is a
        # decision about tearing labels off rather than a measurement, and
        # this has just measured a job that ended in a tear-off by
        # definition.
        ending=stock.calibration.ending,
        measured_at=now,
    )
    return Outcome(cal,
                   " ".join([_headline(start, length or catalog),
                             *notes]),
                   _shape(start), swap_suggested=swap)


def _feed_axis(y1: float, y2: float, catalog: float):
    """The two feed coordinates -> (start, measured length or None, refusal).

    `start` keeps 0.9.x's sign convention because the print path is unchanged
    and it is the right one: **positive is a band the printer will not put
    ink in** and the artwork is laid out inside what is left, **negative is
    ink asked for before the die cut** and `ESC f` feeds that far first. What
    changed is that nobody reads the sign any more — it falls out of which
    side of the grid's own zero the leading die cut landed on.

    The length is measured only where both die cuts are on the grid, which is
    exactly where `y1` is not zero. With `y1` at zero the leading edge is
    somewhere above the scale and `y2 - y1` is how much of the label can
    carry ink rather than how long the label is; reading it back as a length
    would store a roll several millimetres shorter than it really is and
    every `ESC L` after it would be built on that.
    """
    if y2 <= 0.5:
        return 0.0, None, (
            f"The bottom edge reads {y2:.1f}mm, which would put the end of "
            f"the label on the very first row the printer laid. Y2 is the "
            f"grid number where the label's BOTTOM edge falls — read it "
            f"again from the last number you can see down there.")
    if y2 <= y1 + 0.5:
        return 0.0, None, (
            f"The bottom edge ({y2:.1f}mm) is not past the top one "
            f"({y1:.1f}mm), and both are read off the same scale running "
            f"down the label — so the bottom one is always the larger. Read "
            f"them again in that order.")

    if y1 > TOL_MM:
        # The die cut fell on the grid, so both edges are on it: the label's
        # own length is measurable here and nowhere else, and where the
        # printing starts is simply where the grid says the label does.
        if y1 > MAX_EARLY_MM:
            return 0.0, None, (
                f"That would have the printer laying ink {y1:.1f}mm before "
                f"the label even begins, which is most of the label before "
                f"it onto the floor. Check that Y1 came off the scale "
                f"running DOWN the label rather than the one across it — "
                f"and if you are trying to leave a margin at the top rather "
                f"than saying where the paper is, Y1 is the paper's own edge "
                f"and the margin belongs to the stock.")
        length = y2 - y1
        if abs(length - catalog) > catalog * LENGTH_SANITY:
            return 0.0, None, (
                f"Those two put the label at {length:.1f}mm along the roll "
                f"where this stock says {catalog:.1f}mm. That is not a "
                f"registration fault, it is a different label — check the "
                f"roll in the printer is the one this stock describes, and "
                f"that both numbers came off the scale running down it. "
                f"These two are where the PAPER's edges fall; the area to "
                f"print inside is \u201ckeep clear at the bottom\u201d.")
        return -y1, length, ""

    # Zero, which is the reading at the end of the scale: the leading edge is
    # at or above the first row the printer lays. What is measurable is how
    # much of the label the grid reached, and the rest is the catalog's.
    late = catalog - y2
    if late > MAX_LATE_MM:
        return 0.0, None, (
            f"That would make the printer start {late:.1f}mm into every "
            f"label, which is further than any top-of-form fault goes. The "
            f"far likelier answer is that this roll is not {catalog:.1f}mm "
            f"long — check the stock's own measurements, and that the roll "
            f"in the printer is the one this stock describes. If you are "
            f"trying to make the printable area SHORTER on purpose, Y2 is "
            f"where the paper's bottom edge really falls and the box that "
            f"does it is \u201ckeep clear at the bottom\u201d.")
    return max(0.0, late), None, ""


def _across_axis(x1: float, x2: float | None):
    """The two across coordinates -> (measured width or None, refusal).

    One refusal and one derived number. The left edge is stored as it was
    read — it IS where the paper sits on the head — and the width is only
    ever used to say something about the stock row.
    """
    if x2 is None:
        return None, ""
    if x2 <= x1 + 0.5:
        return None, (
            f"The right edge ({x2:.1f}mm) is not past the left one "
            f"({x1:.1f}mm), and both are read off the same scale running "
            f"across the label — so the right one is always the larger. "
            f"Read them again in that order, or leave X2 empty if the scale "
            f"stops before the label's right-hand edge.")
    return x2 - x1, ""


def _shape(start: float) -> str:
    """Which of the three readings this was, in one word for the tests."""
    if abs(start) <= TOL_MM:
        return "from_the_die_cut"
    return "dead_band" if start > 0 else "prints_early"


def _headline(start: float, length: float) -> str:
    """What the printer does with this roll, in the roll's own words.

    The held bands are not part of what the printer does and are
    deliberately not in this sentence: they get their own, from
    `_hold_notes`, because a band the machine refuses and a band a person
    reserved are two different facts and reading them as one is how somebody
    concludes their printer is worse than it is.
    """
    if abs(start) <= TOL_MM:
        return ("This printer prints from the die cut on this roll, so there "
                "is nothing to correct.")
    if start > 0:
        return (
            f"On this roll the printer can’t put ink on the first "
            f"{start:.1f}mm of each label, on every label — so labels are "
            f"laid out inside the {length - start:.1f}mm that is left, and "
            f"anything drawn in that band is reported rather than silently "
            f"lost.")
    return (
        f"On this roll the printing would start {abs(start):.1f}mm before "
        f"the die cut, so every job now feeds that far first and the whole "
        f"{length:.1f}mm label is printable.")


# What each held side is called in a sentence a person reads. The keys are
# the printer's own axes and these are the words for them on a label held
# the way the wizard says to hold it.
HOLD_WORDS = {"leading": "top", "trailing": "bottom",
              "left": "left", "right": "right"}


def _hold_notes(held: dict, asked: dict) -> list[str]:
    """What the reserved bands do, and which of them were cut down to fit.

    Two sentences at most and usually none. The first says what was
    reserved — worth saying every time, because these are the only numbers
    on the roll that nothing measured and a person coming back in a month
    has no way to tell them from ones the grid produced. The second only
    appears when an ask was cut down, which is the case a silent floor would
    hide: a pair longer than the label reaches `printable_box`'s own floor
    and comes out as a one-millimetre canvas with nothing anywhere saying
    why.

    One sentence for all four rather than one each, because four notes about
    four boxes somebody has just filled in is a wall of text confirming what
    they typed.
    """
    kept = [(side, held[side]) for side in HOLD_SIDES if held[side] > 0]
    cut = [side for side in HOLD_SIDES if asked[side] - held[side] > 0.05]
    notes = []
    if kept:
        where = ", ".join(f"{value:.1f}mm at the {HOLD_WORDS[side]}"
                          for side, value in kept)
        notes.append(
            f"Held clear because you asked for it, not because the printer "
            f"can’t reach it: {where}. Labels are laid out inside what is "
            f"left, and the check label’s frame comes in to meet it.")
    elif any(asked[side] > 0 for side in HOLD_SIDES):
        # An ask that rounded away to nothing still has to say so, or the
        # boxes appear to have been ignored.
        notes.append("The bands asked for are smaller than a tenth of a "
                     "millimetre, so nothing is held back.")
    if cut:
        # Both numbers, per side: what was typed and what it became. A note
        # that only reports the new value leaves somebody re-typing the same
        # 99 to find out why it did not take, which is the guard refusing
        # without changing the next attempt — and the pair is also the only
        # way to see that a PAIR was scaled rather than one side truncated.
        where = " and ".join(
            f"{asked[side]:.1f}mm at the {HOLD_WORDS[side]} came down to "
            f"{held[side]:.1f}mm" for side in cut)
        notes.append(
            f"More was asked for than this label has room for, so {where} — "
            f"what is left is a millimetre to print on.")
    return notes


def _catalog_notes(stock, width, length) -> list[str]:
    """What the readings say about the stock row itself.

    Said rather than acted on. A roll that measures 3mm narrower than the
    catalog is either a stock row somebody typed from the wrong box or a
    different roll in the printer, and both of those are answered by a person
    looking at the paper — not by this quietly rewriting their catalog to
    match one reading.
    """
    notes: list[str] = []
    if width is not None and abs(width - stock.across_mm) > CATALOG_TOL_MM:
        notes.append(
            f"The label measures {width:.1f}mm across where the catalog says "
            f"{stock.across_mm:.1f}mm — worth checking the roll is the one "
            f"this stock describes.")
    # `length` here is the STORED one, so it is None both where the readings
    # measured no length at all — every roll whose leading edge was above the
    # scale — and where the one they measured agrees with the row. Saying
    # nothing in the first case is the only honest thing: those readings did
    # not measure a length, so they cannot disagree with one.
    if length is not None:
        notes.append(
            f"It measures {length:.1f}mm along the roll where the catalog "
            f"says {stock.feed_mm:.1f}mm, so the measured length is what the "
            f"printer is told from now on.")
    return notes


def _looks_transposed(stock, width, length) -> bool:
    """Do the two measurements match the catalog's two, the other way round?

    The single most common way a label comes out rotated with its text off
    the edge, and the one thing the calibration is in a position to notice:
    it has just measured both dimensions of the actual paper. It is offered
    and never applied — `swapped()` is one press, and a stock row is
    somebody's.
    """
    if width is None:
        return False
    return (abs(width - stock.feed_mm) <= SWAP_TOL_MM
            and abs(length - stock.across_mm) <= SWAP_TOL_MM
            and abs(stock.across_mm - stock.feed_mm) > SWAP_TOL_MM)
