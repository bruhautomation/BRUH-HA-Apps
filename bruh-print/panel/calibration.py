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

So: one job prints two labels with a deliberate 5mm pre-skip. A person reads
five numbers off them with the label's own printed ladders. This module turns
those into a `Calibration`, and there is exactly one branch per HYPOTHESIS —
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

# How far a measurement may differ from the catalog before it is worth
# mentioning. The catalog carries a roll's nominal size and real die cuts are
# within a few tenths of it, so a millimetre is comfortably outside the
# measurement and comfortably inside "somebody has the wrong roll loaded".
CATALOG_TOL_MM = 1.0

# And how close the two measurements have to be to the catalog's OTHER
# dimension before this says they look transposed. Wider than the tolerance
# above on purpose: it is a suggestion about somebody's stock rather than a
# correction to it, and a suggestion that only fires on a perfect match is a
# suggestion nobody ever sees.
SWAP_TOL_MM = 1.5


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

    `top1` — from the leading die cut of copy 1 to the heavy bar, which is
    raster line 0. `bottom1` — from that bar to the trailing die cut, read
    off the feed ladder. The two together are the label's length, which is
    why both are asked for: the length is a measurement here rather than a
    catalog number, and a roll that is not what the catalog says is one of
    the things this is for.

    `top2` — the same as `top1`, on copy 2. It is the entire evidence for
    hypothesis B, and asking for it is why the calibration job prints twice.
    """

    left: float
    top1: float
    bottom1: float
    top2: float
    right: float | None = None


@dataclass(frozen=True)
class Printed:
    """What the calibration job actually sent, so the readings mean something.

    `pre_skip_mm` is the deliberate feed before raster line 0. It is what
    makes a NEGATIVE start measurable: without it a printer starting exactly
    on the die cut and one asked for ink 2mm before it both print their first
    row at the die cut, and the two are the difference between "nothing to
    correct" and "this roll needs a pre-skip on every job".

    `esc_l_mm` is the search budget that went out, in millimetres, and it is
    read by hypothesis C as the distance the printer fed when it did not find
    a hole. It comes from `protocol.budget_dots` rather than being
    recomputed, because "what the printer was told" is a fact with one
    source.

    `variant` is which of the two job openings was used. It is carried
    because the answer to hypothesis B is *the variant that worked*, and a
    derivation that did not know which one it was looking at would store the
    wrong one half the time.
    """

    pre_skip_mm: float
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

    `now` is the clock the caller is already holding, not one read in here.
    It is the only thing on a `Calibration` that is not measured off a label,
    and it is passed rather than taken so this stays a function two readings
    can be handed twice — the same reason `override_ledger.pattern` takes the
    pass's own `now` one add-on over.
    """
    pre = float(printed.pre_skip_mm)
    start_1 = readings.top1 - pre
    start_2 = readings.top2 - pre
    length = readings.bottom1 + readings.top1
    across = (None if readings.right is None
              else readings.right - readings.left)

    # A label whose two die cuts are in the wrong order, or on top of each
    # other, is a misread ladder rather than a roll — and every branch below
    # divides the label into a dead band and what is left, which needs a
    # label to divide.
    if length <= 1.0:
        return Outcome(
            None,
            f"Those two readings make this label {length:.1f}mm long, which "
            f"cannot be right — the top measurement is from the leading edge "
            f"down to the thick bar, and the bottom one is from that bar to "
            f"the next edge. Read them again and keep them in that order.",
            "impossible")

    notes = _catalog_notes(stock, across, length)
    swap = _looks_transposed(stock, across, length)

    if abs(start_1 - start_2) <= TOL_MM:
        return _same_every_label(readings, printed, stock,
                                 (start_1 + start_2) / 2.0, length,
                                 notes, swap, now)
    if abs(start_2) <= TOL_MM and start_1 > TOL_MM:
        return _first_label_only(printed, start_1, start_2, length, stock,
                                 readings, notes, swap, now)
    return _not_finding_the_hole(readings, printed, stock, start_1, start_2,
                                 length, notes, swap, now)


# ---------------------------------------------------------------------------
# A — the same on every label
# ---------------------------------------------------------------------------
def _same_every_label(readings, printed, stock, start, length, notes,
                      swap, now) -> Outcome:
    """Both copies read the same, so whatever it is, it is the roll's."""
    if start >= length - 1.0:
        return Outcome(
            None,
            f"That reading says the printer lays no ink for the first "
            f"{start:.1f}mm of a label that is only {length:.1f}mm long, "
            f"which would leave nothing to print on. Check that the top "
            f"measurement is to the thick bar and not to something else on "
            f"the label, and print the calibration again.",
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
    cal = _calibration(readings, stock, length, now,
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
def _first_label_only(printed, start_1, start_2, length, stock, readings,
                      notes, swap, now) -> Outcome:
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

    cal = _calibration(readings, stock, length, now, start=start_2,
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
                          notes, swap, now) -> Outcome:
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
            f"{length:.1f}mm long. Check the two top measurements: they are "
            f"both from a leading die cut to the thick bar, on their own "
            f"copy.",
            "impossible")

    cal = _calibration(readings, stock, length, now, start=start_1, gap=gap,
                       job_start="plain")
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
def _calibration(readings, stock, length, now, *, start, after_tear=0.0,
                 gap=None, job_start="plain") -> Calibration:
    """One place the seven stored numbers are assembled.

    `length_mm` is stored only when it disagrees with the catalog, because a
    measurement that merely confirms the number already on the stock row is a
    second copy of it — and a second copy is what drifts the day somebody
    corrects one of them.

    `ending` is not derived from anything and stays as the roll had it. It is
    a decision about tearing labels off rather than a measurement, and this
    function has just measured a job that ended in a tear-off by definition.
    """
    catalog = stock.feed_mm
    return Calibration(
        across_mm=round(readings.left, 2),
        start_mm=round(start, 2),
        after_tear_mm=round(after_tear, 2),
        length_mm=(round(length, 2)
                   if abs(length - catalog) > CATALOG_TOL_MM else None),
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
    if abs(length - stock.feed_mm) > CATALOG_TOL_MM:
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
