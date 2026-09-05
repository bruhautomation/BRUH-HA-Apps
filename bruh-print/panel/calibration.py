#!/usr/bin/env python3
"""Five numbers off a printed label, and what they mean.

This is the whole of "stop adding knobs". Every release from 0.6.0 to 0.8.x
answered a misaligned label by adding a box to type a millimetre into, and by
0.8.4 there were four of them with four different signs, four different
meanings and no way to tell which one a given symptom belonged to. The person
using it printed, measured, typed, printed again, and said so. They were
right, and the reason is not that four is too many — it is that a correction
somebody guesses is a guess whatever it is called, and the printer had
already answered every question that mattered on a piece of paper nobody was
reading properly.

So: one job prints two labels. A person reads six numbers off them with the
label's own printed ladders. This module turns those into a `Calibration`, and
there is exactly one branch per HYPOTHESIS —
not per symptom, because the symptoms of the three are identical from a
photograph and only the arithmetic separates them:

  **A — the roll starts late, every label.** Both copies read the same. The
  printer's top of form on this stock sits a few millimetres past the die
  cut, there is no command that moves it, and the honest answer is to know
  where the printable part starts and lay labels out inside it.

  **B — the FIRST label of a job starts late.** Copy 2 reads zero and copy 1
  does not. The manual says an `ESC E` "places the next label beyond the
  starting print position. Therefore, a reverse-feed will be automatically
  invoked when printing on the next label" — so this is that reverse feed not
  happening, and it costs exactly one label per job. It is the one hypothesis
  that takes a second print to settle, because `ESC @` ("sets top-of-form as
  true") is a plausible fix and whether a given firmware makes it work is not
  answerable from inside a container.

  **C — the sense hole is not being found at all.** The two copies differ by
  something that is neither zero nor the whole of the offset. Then the
  printer is positioning off the `ESC L` budget rather than off the hole, the
  difference between the copies IS the error in that budget, and the roll's
  real hole-to-hole pitch falls out of it.

**The two signs are not read the same way, and the first cut of this got that
backwards.** Nothing printed can land before the point where the printer
begins, so a printer that starts LATE leaves a blank band at the top of the
label with the ladder's own 0 and its heavy bar at the bottom of it — and
there is nothing in that band to measure the band with. A late start is
therefore read at the OTHER end: the trailing die cut falls on the ladder at
the label's length less the late start, and the label's length is a number the
catalog already holds. A printer that starts EARLY is the readable one: its
first rows land before the leading die cut, so the die cut cuts the ladder and
the number it cuts it at IS the distance.

A 5mm pre-skip was added to the calibration job on the theory that it made a
negative start measurable. It did the opposite. Feeding 5mm before row 0 puts
the ladder's 0 five millimetres further down a label whose top is already
blank, so the reading a person takes at the top is 0 in both signs and the one
number that distinguished them was the one nothing printed. It is gone, and
`top` is now a **sign flag** as much as a measurement: 0 means "the 0 and its
bar are there with blank label above them", which is the late-or-exact case,
and anything else is the early one.

Everything here is pure: readings in, an outcome out, no store and no
printer. That is what lets the three branches be tested with the numbers the
owner actually measured rather than with a story about them.
"""
from __future__ import annotations

from dataclasses import dataclass

from stores.stock import Calibration

# How far two readings may differ and still be the same reading. A person is
# holding a label against a printed millimetre ladder, so the honest
# resolution is well under a millimetre and nowhere near two — and this
# number decides WHICH HYPOTHESIS a roll gets, so it is the difference
# between "your printer starts late" and "your printer cannot find the hole".
# Too tight and an ordinary reading error is reported as a drift; too loose
# and a real one-label-per-job fault is averaged into a band that is wrong on
# every label.
TOL_MM = 0.7

# How far the measured WIDTH may differ from the catalog before it is worth
# mentioning. The catalog carries a roll's nominal size and real die cuts are
# within a few tenths of it, so a millimetre is comfortably outside the
# measurement and comfortably inside "somebody has the wrong roll loaded".
# The length has no such tolerance and does not need one — see `_calibration`.
CATALOG_TOL_MM = 1.0

# And how close the two measurements have to be to the catalog's OTHER
# dimension before this says they look transposed. Wider than the tolerance
# above on purpose: it is a suggestion about somebody's stock rather than a
# correction to it, and a suggestion that only fires on a perfect match is a
# suggestion nobody ever sees.
SWAP_TOL_MM = 1.5


# How far past the last number on the ladder a bottom reading has to stay
# before it can be believed as a die cut rather than as the ladder simply
# running out. The calibration sheet is exactly one catalog label long, so on
# an EARLY-starting printer its tail stops short of the trailing die cut by
# however early it started — and the last mark a person can see there is the
# end of the ladder, which is not an edge.
LADDER_END_MM = 0.5

# The furthest a printer may be said to start late before the number stops
# being about a printer. Top-of-form registration is a fraction of an inch —
# DYMO's own PPD declares 1.5mm unprintable at each feed end and the worst
# this add-on has been shown is 4.7mm — so twelve is comfortably past any
# registration fault and comfortably short of a roll that is simply not the
# length the catalog says. It matters because the late branch derives the
# start FROM the catalogued length: a roll whose real label is shorter than
# its stock row says would otherwise come back as an enormous dead band, with
# nothing in the arithmetic to say the stock was wrong instead.
MAX_LATE_MM = 12.0


@dataclass(frozen=True)
class Readings:
    """What a person read off the two printed calibration labels.

    Every one of them is a distance in millimetres and every one is read
    against something printed on the same label, which is the only kind of
    reading that cannot be wrong about its own scale.

    `left` / `right` — where the label's two edges fall on the across ladder,
    which is drawn from head dot 0 right across the print head. `right` is
    optional because a label wider than the head runs off it and there is
    nothing to read; `left` is not, because it is the number the whole across
    axis is built on.

    `top1` / `top2` — the ladder value at each copy's LEADING die cut, which
    is **0 whenever the ladder's own 0 and its heavy bar are printed with
    blank label above them**. That is not a special case to be tidied away:
    nothing can print before where the printer begins, so a late start leaves
    a band with nothing in it and 0 is the only honest reading of a blank. A
    number here means the die cut cut the ladder, which only a printer
    starting BEFORE the die cut can do — so `top` is the sign as much as it is
    a distance.

    `bottom1` / `bottom2` — the ladder value at each copy's TRAILING die cut.
    This is the one that carries a late start, measured against the label's
    own length: the second reading per copy is why there are six of these
    rather than five, and asking for it on copy 2 as well is what lets the
    two copies be compared at all in the case the roll is actually in.
    """

    left: float
    top1: float
    bottom1: float
    top2: float
    bottom2: float
    right: float | None = None


@dataclass(frozen=True)
class Printed:
    """What the calibration job actually sent, so the readings mean something.

    `esc_l_mm` is the search budget that went out, in millimetres, and it is
    read by hypothesis C as the distance the printer fed when it did not find
    a hole. It comes from `protocol.budget_dots` rather than being
    recomputed, because "what the printer was told" is a fact with one
    source.

    `variant` is which of the two job openings was used. It is carried
    because the answer to hypothesis B is *the variant that worked*, and a
    derivation that did not know which one it was looking at would store the
    wrong one half the time.

    There is no pre-skip here and there is not meant to be. The job feeds
    nothing before row 0: a skip moves the ladder's own datum down a label
    whose top is blank either way, which is a millimetre added to every
    reading and no new information in any of them.
    """

    esc_l_mm: float
    variant: str = "plain"


@dataclass(frozen=True)
class Outcome:
    """What to store, what to say, and what to do next.

    `calibration` is `None` for the two cases that are not an answer: the
    first half of hypothesis B, where a second print is needed before
    anything can be stored, and a set of readings whose arithmetic is
    impossible. Storing a half-answer in either case would leave a roll
    calibrated by a guess, which is the thing this whole rewrite is against.

    `sentence` is what a person is shown, and it names the hypothesis in
    plain words rather than reporting the numbers back at them.

    `swap_suggested` is never acted on here. The two measurements looking
    transposed is evidence about somebody's stock row, and quietly swapping a
    roll's dimensions because of one reading is exactly the sort of helpful
    correction that loses a measurement they made with a ruler.
    """

    calibration: Calibration | None
    sentence: str
    hypothesis: str
    next_variant: str | None = None
    swap_suggested: bool = False

    def as_dict(self) -> dict:
        return {
            "calibration": (self.calibration.as_dict()
                            if self.calibration else None),
            "sentence": self.sentence,
            "hypothesis": self.hypothesis,
            "next": ({"variant": self.next_variant, "why": self.sentence}
                     if self.next_variant else None),
            "swap_suggested": self.swap_suggested,
        }


def derive(readings: Readings, printed: Printed, stock, *,
           now: float | None = None) -> Outcome:
    """The three hypotheses, decided by arithmetic and nothing else.

    Each copy is reduced to one signed start by `_one_copy`, and only then are
    the two compared — because the comparison is the same three-way test
    whichever sign each copy came out of, and folding the sign rules into it
    would be two different questions answered in one branch.

    `now` is the clock the caller is already holding, not one read in here.
    It is the only thing on a `Calibration` that is not measured off a label,
    and it is passed rather than taken so this stays a function two readings
    can be handed twice — the same reason `override_ledger.pattern` takes the
    pass's own `now` one add-on over.
    """
    catalog = stock.feed_mm
    start_1, length_1, refused = _one_copy(readings.top1, readings.bottom1,
                                           catalog, 1)
    if refused:
        return Outcome(None, refused, "impossible")
    start_2, length_2, refused = _one_copy(readings.top2, readings.bottom2,
                                           catalog, 2)
    if refused:
        return Outcome(None, refused, "impossible")

    # A measured length where either copy could give one, and the catalog
    # where neither could. The two are kept apart because only the first may
    # be STORED — `length_mm` is what the print path is told from then on,
    # and writing the catalog back into it would be a second copy of a number
    # already on the row.
    measured = length_1 if length_1 is not None else length_2
    length = catalog if measured is None else measured
    across = (None if readings.right is None
              else readings.right - readings.left)

    notes = _catalog_notes(stock, across, measured)
    swap = _looks_transposed(stock, across, measured or catalog)

    if abs(start_1 - start_2) <= TOL_MM:
        return _same_every_label(readings, printed, stock,
                                 (start_1 + start_2) / 2.0, length, measured,
                                 notes, swap, now)
    if abs(start_2) <= TOL_MM and start_1 > TOL_MM:
        return _first_label_only(printed, start_1, start_2, length, measured,
                                 stock, readings, notes, swap, now)
    return _not_finding_the_hole(readings, printed, stock, start_1, start_2,
                                 length, measured, notes, swap, now)


def _one_copy(top: float, bottom: float, catalog: float, which: int):
    """One copy's two readings -> (start, measured length or None, refusal).

    **The two signs come from different references and that is the whole of
    this function.** An EARLY start is the readable one: the leading die cut
    falls on the ladder at the distance the printing began before it, so the
    top reading *is* the start, negated. A LATE start prints nothing in the
    band it is being asked about, so `top` is 0 and the only reference left is
    the far end — the trailing die cut against the label's own catalogued
    length.

    The length is measured only where BOTH die cuts landed on the ladder,
    which is the early case and only while the ladder had not already run out.
    The sheet is one catalog label long, so on a roll that starts early the
    ladder stops short of the trailing die cut by exactly how early — and the
    last mark down there is then the end of the ladder rather than an edge.
    `None` is what that says, and it is a different answer from a length that
    happens to match: the check label is what confirms a late roll's length,
    because a ladder that never reached the edge cannot.
    """
    if bottom <= 0.5:
        return 0.0, None, (
            f"The bottom reading on label {which} is {bottom:.1f}mm, which "
            f"would put the trailing edge of the label on the very first "
            f"line the printer laid. It is the ladder number where the "
            f"BOTTOM edge of the label falls — read it again from the last "
            f"number you can see down there.")

    if top > TOL_MM:
        # Early: the die cut cut the ladder, and the number it cut it at is
        # the distance. Both edges are on the ladder, so the label's own
        # length is measurable here and nowhere else.
        if bottom <= top:
            return 0.0, None, (
                f"On label {which} the bottom reading ({bottom:.1f}mm) is not "
                f"past the top one ({top:.1f}mm), and both are read off the "
                f"same ladder running down the label — so the bottom one is "
                f"always the larger. Read them again in that order.")
        length = (bottom - top if bottom + LADDER_END_MM < catalog else None)
        return -top, length, ""

    # Late or exact. `max` rather than a signed answer: `top == 0` means
    # nothing was cut off the leading edge, so the printing cannot have begun
    # before it — a negative here is a reading a few tenths long, or a roll
    # longer than the catalog says, and neither is a printer starting early.
    late = catalog - bottom
    if late > MAX_LATE_MM:
        return 0.0, None, (
            f"That would make the printer start {late:.1f}mm into every "
            f"label, which is further than any top-of-form fault goes. The "
            f"far likelier answer is that this roll is not {catalog:.1f}mm "
            f"long — check the stock's own measurements, and that the roll "
            f"in the printer is the one this stock describes.")
    return max(0.0, late), None, ""


# ---------------------------------------------------------------------------
# A — the same on every label
# ---------------------------------------------------------------------------
def _same_every_label(readings, printed, stock, start, length, measured,
                      notes, swap, now) -> Outcome:
    """Both copies read the same, so whatever it is, it is the roll's."""
    if start >= length - 1.0:
        return Outcome(
            None,
            f"That reading says the printer lays no ink for the first "
            f"{start:.1f}mm of a label that is only {length:.1f}mm long, "
            f"which would leave nothing to print on. Check that the bottom "
            f"measurement is the ladder number where the label's own trailing "
            f"edge falls, and print the calibration again.",
            "impossible")

    # The reset variant coming out even AND on the die cut is the one place
    # `ESC @` earns its place in every future job: it is what made this
    # print right, so storing "plain" would put the fault back tomorrow. A
    # reset that came out even and still late fixed nothing, and a command
    # that changes nothing is a command not worth sending — which is why
    # this asks about the RESULT and not about the variant.
    fixed = printed.variant == "reset" and abs(start) <= TOL_MM
    # Inside the tolerance is stored as nothing at all rather than as the
    # tenths that were read. A person against a millimetre ladder is not
    # accurate to a tenth, and 0.4mm saved as a correction crops a row off
    # every label for a number that describes the reading rather than the
    # printer — while `measured` then reports the roll as calibrated, which
    # is the honest half of it.
    cal = _calibration(readings, stock, measured, now,
                       start=0.0 if abs(start) <= TOL_MM else start,
                       job_start="reset" if fixed else "plain")

    if abs(start) <= TOL_MM:
        head = ("This printer prints from the die cut on this roll, so there "
                "is nothing to correct.")
        if fixed:
            head = ("With the reset sent at the start of a job this printer "
                    "prints from the die cut on this roll, so every job will "
                    "send it from now on.")
    elif start > 0:
        head = (
            f"On this roll the printer can’t put ink on the first "
            f"{start:.1f}mm of each label, on every label — so labels are "
            f"laid out inside the {length - start:.1f}mm that is left, and "
            f"anything drawn in that band is reported rather than silently "
            f"lost.")
    else:
        head = (
            f"On this roll the printing would start {abs(start):.1f}mm "
            f"before the die cut, so every job now feeds that far first and "
            f"the whole {length:.1f}mm label is printable.")
    return Outcome(cal, " ".join([head, *notes]), "same_every_label",
                   swap_suggested=swap)


# ---------------------------------------------------------------------------
# B — only the first label of a job
# ---------------------------------------------------------------------------
def _first_label_only(printed, start_1, start_2, length, measured, stock,
                      readings, notes, swap, now) -> Outcome:
    """Copy 2 is on the die cut and copy 1 is not: the reverse feed is missing.

    The first print of a pair cannot settle this, and that is the whole
    reason the plain branch stores nothing. `ESC @` is a real candidate —
    the manual's own words for it are "sets top-of-form as true", which is
    the state the reverse feed after a tear-off is owed from — and whether a
    given firmware honours it is not knowable from here. So the answer is to
    print again with it and compare, rather than to record a fault that a
    single command might not have.
    """
    if printed.variant != "reset":
        return Outcome(
            None,
            f"The first label started {start_1:.1f}mm later than the second, "
            f"and the second is on the die cut. That is the reverse feed a "
            f"tear-off owes the next label not happening — it costs one "
            f"label per job and nothing after it. Print the calibration "
            f"again with the reset, which is the one command that sets "
            f"top-of-form true, and read the same numbers: if the first "
            f"label comes out level, every job will send it.",
            "first_label_only", next_variant="reset")

    cal = _calibration(readings, stock, measured, now, start=start_2,
                       after_tear=start_1 - start_2, job_start="plain")
    head = (
        f"The reset did not fix it, so this printer simply starts the first "
        f"label of a job {start_1 - start_2:.1f}mm late and every label "
        f"after it on the die cut. BRUH Print now leaves that band clear on "
        f"the first label of each job and uses the whole of the rest.")
    return Outcome(cal, " ".join([head, *notes]), "first_label_only",
                   swap_suggested=swap)


# ---------------------------------------------------------------------------
# C — the sense hole is not being found
# ---------------------------------------------------------------------------
def _not_finding_the_hole(readings, printed, stock, start_1, start_2, length,
                          measured, notes, swap, now) -> Outcome:
    """The copies differ by something that is neither zero nor everything.

    Then the printer is not re-syncing on the hole between the two, so it is
    positioning off the `ESC L` budget alone — and the budget is a number we
    chose. The drift per label is therefore the error in it: we fed
    `esc_l_mm` and the paper should have advanced by one pitch, so the pitch
    is what we fed less what it came out wrong by. Take the label off that
    and what is left is the die-cut gap, which is the quantity `ESC L` is
    actually defined in.
    """
    drift = start_2 - start_1
    pitch = printed.esc_l_mm - drift
    gap = pitch - length
    if gap < 0:
        return Outcome(
            None,
            f"Those readings work out to a gap between labels of "
            f"{gap:.1f}mm, which is less than no paper at all — the two "
            f"labels drifted by {drift:.1f}mm, which would make the roll’s "
            f"hole-to-hole pitch {pitch:.1f}mm against a label "
            f"{length:.1f}mm long. Check the two bottom measurements: they "
            f"are the ladder number at each copy's own trailing edge.",
            "impossible")

    cal = _calibration(readings, stock, measured, now, start=start_1,
                       gap=gap, job_start="plain")
    head = (
        f"The printer isn’t finding the sense hole on this roll — the second "
        f"label started {drift:.1f}mm further along than the first — so it "
        f"is counting the label length instead. The gap between labels "
        f"measures {gap:.1f}mm, and the search is now that arithmetic rather "
        f"than the guess it has been.")
    return Outcome(cal, " ".join([head, *notes]), "not_finding_the_hole",
                   swap_suggested=swap)


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------
def _calibration(readings, stock, measured, now, *, start, after_tear=0.0,
                 gap=None, job_start="plain") -> Calibration:
    """One place the seven stored numbers are assembled.

    `measured` is the length the readings actually established, or `None`
    where they could not — which is every late-starting roll, because the
    late branch derives the start FROM the catalogued length and reading the
    length back out of it would be the same number twice. `length_mm` is then
    stored only where a real measurement disagrees with the catalog, because
    one that merely confirms the number already on the row is a second copy
    of it, and a second copy is what drifts the day somebody corrects one.

    `ending` is not derived from anything and stays as the roll had it. It is
    a decision about tearing labels off rather than a measurement, and this
    function has just measured a job that ended in a tear-off by definition.
    """
    return Calibration(
        across_mm=round(readings.left, 2),
        start_mm=round(start, 2),
        after_tear_mm=round(after_tear, 2),
        # Stored whenever there is one, with no "does it agree with the
        # catalog" test — and that is not laziness, it is arithmetic. A
        # measurable length needs BOTH die cuts on a ladder one catalog label
        # long, so it is always shorter than the catalog by at least how
        # early the printer started plus the ladder's own end. It can never
        # merely confirm the row; if it exists at all, it is news.
        length_mm=None if measured is None else round(measured, 2),
        gap_mm=None if gap is None else round(gap, 2),
        job_start=job_start,
        ending=stock.calibration.ending,
        measured_at=now,
    )


def _catalog_notes(stock, across, length) -> list[str]:
    """What the readings say about the stock row itself.

    Said rather than acted on. A roll that measures 3mm narrower than the
    catalog is either a stock row somebody typed from the wrong box or a
    different roll in the printer, and both of those are answered by a person
    looking at the paper — not by this quietly rewriting their catalog to
    match one measurement.
    """
    notes: list[str] = []
    if across is not None and abs(across - stock.across_mm) > CATALOG_TOL_MM:
        notes.append(
            f"The label measures {across:.1f}mm across where the catalog "
            f"says {stock.across_mm:.1f}mm — worth checking the roll is the "
            f"one this stock describes.")
    # `length` is None on every roll whose start was read against the catalog
    # rather than off both die cuts, and saying nothing is the only honest
    # thing there: the reading did not measure a length, so it cannot
    # disagree with one. Where there IS one it always disagrees — see
    # `_calibration` — so there is no tolerance to apply here either.
    if length is not None:
        notes.append(
            f"It measures {length:.1f}mm along the roll where the catalog "
            f"says {stock.feed_mm:.1f}mm, so the measured length is what "
            f"the printer is told from now on.")
    return notes


def _looks_transposed(stock, across, length) -> bool:
    """Do the two measurements match the catalog's two, the other way round?

    The single most common way a label comes out rotated with its text off
    the edge, and the one thing the calibration is in a position to notice:
    it has just measured both dimensions of the actual paper. It is offered
    and never applied — `swapped()` is one press, and a stock row is
    somebody's.
    """
    if across is None:
        return False
    return (abs(across - stock.feed_mm) <= SWAP_TOL_MM
            and abs(length - stock.across_mm) <= SWAP_TOL_MM
            and abs(stock.across_mm - stock.feed_mm) > SWAP_TOL_MM)
