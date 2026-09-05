#!/usr/bin/env python3
"""Five readings off a printed label, and which of three things they mean.

The derivation is pure, which is the point of it being its own module: the
numbers in here are the ones the owner of the printer actually measured, and
a derivation spread across a request handler could only ever be checked by
printing another label.

Every branch is asserted against the case it must NOT take as well as the one
it must, because the three hypotheses look identical from a photograph — a
label with its printing 4.7mm low is a label with its printing 4.7mm low, and
whether that is the roll, the first label of the job, or a printer that has
stopped finding the sense hole is a question only the arithmetic answers.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import bruh_print_env  # noqa: E402

calibration, stock_store = bruh_print_env.load("calibration", "stores.stock")

# The roll everything in this file was measured on: the 2.25" x 1.25" cryo
# label, 31.75mm along the roll, whose printer starts 4.7mm late.
PRE = 5.0
# What the calibration route reports sending: the label (375 lines), plus the
# 25% headroom an unmeasured gap gets, plus the 59-line pre-skip that is
# charged to the same budget. Taken as the arithmetic rather than as a round
# number, because hypothesis C divides by it — a fixture that used a
# plausible figure instead of the one the route reports would be testing a
# derivation against a job nothing sends.
ESC_L = (469 + 59) / 300 * 25.4
LENGTH = 31.75


def cryo(**changes):
    return stock_store.Stock(id="edcc-082wh", name="Cryo", across_in=2.25,
                             feed_in=1.25, **changes)


def readings(top1, top2, *, bottom1=None, left=0.0, right=None):
    """One set of readings, with the bottom one derived from the length.

    `bottom1` defaults to what a 31.75mm label gives, because in every test
    below the LENGTH is not the variable — the two top readings are, and
    they are what the three hypotheses differ on.
    """
    if bottom1 is None:
        bottom1 = LENGTH - top1
    return calibration.Readings(left=left, top1=top1, bottom1=bottom1,
                                top2=top2, right=right)


def printed(variant="plain", esc_l_mm=ESC_L, pre_skip_mm=PRE):
    return calibration.Printed(pre_skip_mm=pre_skip_mm, esc_l_mm=esc_l_mm,
                               variant=variant)


class TestTheRollStartsLateOnEveryLabel(unittest.TestCase):
    """Hypothesis A: both copies read the same.

    The owner's own numbers. 9.7mm from the leading die cut to the bar, on
    both labels, against a 5mm pre-skip: the printer lays no ink for the
    first 4.7mm of every label on this roll, which is what three prints at
    three different offsets had already shown could not be moved.
    """

    def test_the_measured_case_is_a_dead_band_and_nothing_else(self):
        outcome = calibration.derive(readings(9.7, 9.7), printed(), cryo())
        self.assertEqual("same_every_label", outcome.hypothesis)
        self.assertAlmostEqual(4.7, outcome.calibration.start_mm, places=2)
        self.assertEqual(0.0, outcome.calibration.after_tear_mm)
        self.assertIsNone(outcome.next_variant)
        self.assertIsNone(outcome.calibration.gap_mm,
                          "a roll that is merely late is still finding its "
                          "hole, so there is nothing to say about the gap")
        self.assertIn("4.7mm", outcome.sentence)
        self.assertIn("27.1mm", outcome.sentence,
                      "the sentence says what is left, not just what is lost")

    def test_a_printer_that_starts_on_the_die_cut_stores_nothing_to_correct(self):
        outcome = calibration.derive(readings(5.0, 5.0), printed(), cryo())
        self.assertEqual(0.0, outcome.calibration.start_mm)
        self.assertIn("nothing to correct", outcome.sentence)

    def test_a_reading_inside_the_tolerance_is_zero_rather_than_a_wobble(self):
        """A person reading a millimetre ladder is not accurate to a tenth,
        and storing 0.4mm as a correction would crop a row off every label
        for a number that is the reading rather than the printer."""
        outcome = calibration.derive(readings(5.4, 5.3), printed(), cryo())
        self.assertEqual(0.0, outcome.calibration.start_mm)

    def test_ink_asked_for_before_the_die_cut_is_a_negative_start(self):
        """The other sign, and the reason the pre-skip exists at all: with
        no skip a printer that starts on the die cut and one that would have
        started 2mm before it both print their first row at the die cut, and
        those are different rolls wanting different jobs."""
        outcome = calibration.derive(readings(3.0, 3.0), printed(), cryo())
        self.assertAlmostEqual(-2.0, outcome.calibration.start_mm, places=2)
        self.assertIn("before the die cut", outcome.sentence)
        self.assertIn("whole", outcome.sentence)

    def test_the_reset_variant_coming_out_level_is_what_stores_the_reset(self):
        """The half that is easy to lose: if the reset is what made the
        print right, storing "plain" puts the fault straight back on the
        next ordinary job — and it would look exactly like a calibration
        that did not take."""
        outcome = calibration.derive(readings(5.0, 5.0), printed("reset"),
                                     cryo())
        self.assertEqual("reset", outcome.calibration.job_start)
        self.assertIn("reset", outcome.sentence)

    def test_a_reset_that_changed_nothing_is_not_stored(self):
        """Both copies still 4.7mm late with the reset sent means the reset
        did not do it, and a command that changes nothing is a command not
        worth sending to every job for ever."""
        outcome = calibration.derive(readings(9.7, 9.7), printed("reset"),
                                     cryo())
        self.assertEqual("plain", outcome.calibration.job_start)

    def test_a_dead_band_longer_than_the_label_is_refused(self):
        """Nothing could print. That is a ladder read against the wrong
        edge, not a roll — and storing it would leave a stock whose every
        print is one blank row and a note.

        Driven with a negative bottom reading, which is what it takes: two
        honest readings of one label can never make a band longer than the
        label, because the band is measured from the same edge the length
        is. The route refuses a negative before it gets here, and this is
        the guard behind that — `derive` is public and pure and its
        arithmetic has to hold for whatever reaches it."""
        outcome = calibration.derive(
            readings(36.0, 36.0, bottom1=-6.0), printed(), cryo())
        self.assertIsNone(outcome.calibration)
        self.assertEqual("impossible", outcome.hypothesis)
        self.assertIn("nothing to print on", outcome.sentence)


class TestOnlyTheFirstLabelOfAJob(unittest.TestCase):
    """Hypothesis B: copy 2 is on the die cut and copy 1 is not.

    The manual: an `ESC E` "places the next label beyond the starting print
    position. Therefore, a reverse-feed will be automatically invoked when
    printing on the next label." This is that reverse feed not happening. It
    costs exactly one label per job, and a single number averaged over the
    two copies would be wrong on both.
    """

    def test_the_first_print_asks_for_a_second_and_stores_nothing(self):
        """`ESC @` "sets top-of-form as true", which is the state the reverse
        feed is owed from — a real candidate, and whether a given firmware
        honours it is not answerable from inside a container. So the answer
        is to print again and compare rather than to record a fault that one
        command might not have."""
        outcome = calibration.derive(readings(9.7, 5.0), printed(), cryo())
        self.assertEqual("first_label_only", outcome.hypothesis)
        self.assertIsNone(outcome.calibration)
        self.assertEqual("reset", outcome.next_variant)
        self.assertEqual({"variant": "reset", "why": outcome.sentence},
                         outcome.as_dict()["next"])
        self.assertIn("reverse feed", outcome.sentence)

    def test_the_reset_print_settles_it_either_way(self):
        """If the reset fixed it, both copies come out level and hypothesis A
        stores `job_start: reset`. If it did not, this is what is left: a
        band on the first label of every job and none on the rest."""
        outcome = calibration.derive(readings(9.7, 5.0), printed("reset"),
                                     cryo())
        self.assertIsNotNone(outcome.calibration)
        self.assertEqual(0.0, outcome.calibration.start_mm)
        self.assertAlmostEqual(4.7, outcome.calibration.after_tear_mm,
                               places=2)
        self.assertEqual("plain", outcome.calibration.job_start)
        self.assertIsNone(outcome.next_variant)
        self.assertIn("first label", outcome.sentence)

    def test_a_roll_that_is_late_on_both_is_not_this_hypothesis(self):
        """The case it must not take. Both copies late by the same amount is
        the roll, and charging it to the first label alone would leave every
        label after the first printing into a band it cannot reach."""
        outcome = calibration.derive(readings(9.7, 9.6), printed(), cryo())
        self.assertEqual("same_every_label", outcome.hypothesis)
        self.assertEqual(0.0, outcome.calibration.after_tear_mm)


class TestTheSenseHoleIsNotBeingFound(unittest.TestCase):
    """Hypothesis C: the copies differ by something that is neither.

    Then nothing re-synced the printer's logical counter between the two, so
    it is positioning off the `ESC L` budget alone — and that budget is a
    number this add-on chose. The drift per label is therefore the error in
    it, which makes the roll's real hole-to-hole pitch measurable for the
    first time.
    """

    def test_a_drift_measures_the_pitch_and_therefore_the_gap(self):
        """We fed 44.7mm (375 lines, plus 25%, plus the 5mm pre-skip) and
        the second label came out 1.5mm further along, so the paper's real
        pitch is 43.2mm — and with a 31.75mm label, what is left between two
        of them is the gap."""
        outcome = calibration.derive(readings(9.7, 11.2), printed(), cryo())
        self.assertEqual("not_finding_the_hole", outcome.hypothesis)
        self.assertAlmostEqual(4.7, outcome.calibration.start_mm, places=2)
        self.assertAlmostEqual(ESC_L - 1.5 - LENGTH,
                               outcome.calibration.gap_mm, places=1)
        self.assertIn("isn’t finding the sense hole", outcome.sentence)

    def test_the_gap_it_derives_is_what_the_budget_becomes(self):
        """The whole value of the branch: `ESC L` is defined hole to hole, so
        a measured pitch turns the search budget from a fraction somebody
        chose into arithmetic."""
        outcome = calibration.derive(readings(9.7, 11.2), printed(), cryo())
        protocol, = bruh_print_env.load("dymo.protocol")
        gap_dots = round(outcome.calibration.gap_mm / 25.4 * 300)
        self.assertEqual(375 + gap_dots,
                         protocol.search_length(375, gap_dots))

    def test_an_impossible_gap_is_refused_rather_than_stored(self):
        """A drift bigger than the whole budget would make the pitch shorter
        than the label, which is a roll with negative paper between its
        labels. That is a misread ladder, and storing it would set a search
        budget that ends before the label does — the pre-0.5.0 drift, saved
        deliberately."""
        outcome = calibration.derive(readings(9.7, 25.0), printed(), cryo())
        self.assertIsNone(outcome.calibration)
        self.assertEqual("impossible", outcome.hypothesis)
        self.assertIn("less than no paper", outcome.sentence)

    def test_a_drift_the_other_way_is_still_a_drift(self):
        """Backwards is as diagnostic as forwards: what it says is that the
        budget is longer than the pitch rather than shorter."""
        outcome = calibration.derive(readings(11.2, 9.7), printed(), cryo())
        self.assertEqual("not_finding_the_hole", outcome.hypothesis)
        self.assertAlmostEqual(ESC_L + 1.5 - LENGTH,
                               outcome.calibration.gap_mm, places=1)


class TestWhatTheReadingsSayAboutTheStockItself(unittest.TestCase):
    """The across axis and the length, which every branch records.

    These are measurements of the paper rather than of the printer, and the
    calibration is the one thing in this add-on in a position to take them:
    it has just had both dimensions of the actual roll read off a ladder
    printed across the whole head.
    """

    def test_the_left_edge_is_where_the_paper_sits_on_the_head(self):
        """The one number that absorbed two boxes. `media_across_mm` said
        where a narrow roll's paper sat and `offset_across_mm` shifted
        artwork inside the sheet, and a person whose label printed 7mm to
        the left had no way to tell which was theirs. There is one edge."""
        outcome = calibration.derive(
            readings(9.7, 9.7, left=7.3, right=64.4), printed(), cryo())
        self.assertEqual(7.3, outcome.calibration.across_mm)

    def test_a_length_that_agrees_with_the_catalog_is_not_stored_twice(self):
        """A measurement that merely confirms the number already on the row
        is a second copy of it, and a second copy is what drifts the day
        somebody corrects one of them."""
        outcome = calibration.derive(readings(9.7, 9.7), printed(), cryo())
        self.assertIsNone(outcome.calibration.length_mm)

    def test_a_length_that_disagrees_is_stored_and_said_out_loud(self):
        outcome = calibration.derive(
            readings(9.7, 9.7, bottom1=25.0), printed(), cryo())
        self.assertAlmostEqual(34.7, outcome.calibration.length_mm, places=2)
        self.assertIn("34.7mm along the roll", outcome.sentence)
        self.assertIn("31.8mm", outcome.sentence, "it names the catalog too")

    def test_a_width_that_disagrees_with_the_catalog_is_mentioned(self):
        outcome = calibration.derive(
            readings(9.7, 9.7, left=2.0, right=30.0), printed(), cryo())
        self.assertIn("28.0mm across", outcome.sentence)
        self.assertIn("checking the roll", outcome.sentence.lower())

    def test_a_label_wider_than_the_head_has_no_right_edge_to_read(self):
        """And that is not a failure: the across ladder runs out at the
        head's last dot, so a wider label simply has nothing printed at its
        right edge. The left edge is still the number the axis needs."""
        outcome = calibration.derive(
            readings(9.7, 9.7, left=1.0), printed(), cryo())
        self.assertEqual(1.0, outcome.calibration.across_mm)
        self.assertFalse(outcome.swap_suggested)

    def test_two_measurements_the_wrong_way_round_are_offered_not_applied(self):
        """The commonest way a label comes out rotated with its text off the
        edge, and the calibration has just measured both dimensions of the
        paper. It is offered because a stock row is somebody's and a swap
        made silently is a measurement they cannot find the source of."""
        outcome = calibration.derive(
            readings(9.7, 9.7, bottom1=47.5, left=0.0, right=31.8),
            printed(), cryo())
        self.assertTrue(outcome.swap_suggested)
        self.assertEqual(2.25, cryo().across_in, "nothing was swapped here")

    def test_a_square_stock_is_never_reported_as_transposed(self):
        """Two dimensions that are the same match each other either way
        round, so a suggestion there is noise on every calibration."""
        square = stock_store.Stock(id="s", name="Square", across_in=2.0,
                                   feed_in=2.0)
        outcome = calibration.derive(
            readings(9.7, 9.7, bottom1=41.1, left=0.0, right=50.8),
            printed(), square)
        self.assertFalse(outcome.swap_suggested)


class TestTheOutcomeIsWhatThePanelSends(unittest.TestCase):
    def test_a_stored_outcome_carries_the_whole_calibration(self):
        outcome = calibration.derive(readings(9.7, 9.7), printed(), cryo())
        payload = outcome.as_dict()
        self.assertEqual(
            {"across_mm", "start_mm", "after_tear_mm", "length_mm", "gap_mm",
             "job_start", "ending", "measured_at"},
            set(payload["calibration"]))
        self.assertIsNone(payload["next"])

    def test_a_printer_that_needs_no_correction_still_counts_as_measured(self):
        """Seven default numbers and a roll nobody has asked about are the
        same seven numbers, so without the stamp the panel would go on
        offering the calibration to the printer that least needs it — and a
        roll measured a year and two rolls ago would look freshly checked."""
        outcome = calibration.derive(readings(5.0, 5.0), printed(), cryo(),
                                     now=1_700_000_000.0)
        self.assertEqual(0.0, outcome.calibration.start_mm)
        self.assertEqual(1_700_000_000.0, outcome.calibration.measured_at)
        self.assertTrue(outcome.calibration.measured)

    def test_the_clock_is_the_callers_and_never_read_in_here(self):
        """A pure function that stamps itself is a pure function nobody can
        test twice — the same reason `override_ledger.pattern` takes the
        pass's own `now` one add-on over."""
        first = calibration.derive(readings(9.7, 9.7), printed(), cryo())
        self.assertIsNone(first.calibration.measured_at)
        self.assertEqual(first, calibration.derive(readings(9.7, 9.7),
                                                   printed(), cryo()))

    def test_an_unstored_outcome_says_so_without_a_calibration(self):
        payload = calibration.derive(readings(9.7, 5.0), printed(),
                                     cryo()).as_dict()
        self.assertIsNone(payload["calibration"])
        self.assertEqual("reset", payload["next"]["variant"])

    def test_the_ending_a_roll_already_had_survives_a_calibration(self):
        """It is a decision about tearing labels off rather than a
        measurement, and this has just measured a job that ended in a
        tear-off by definition."""
        held = cryo(calibration=stock_store.Calibration(ending="hold"))
        outcome = calibration.derive(readings(9.7, 9.7), printed(), held)
        self.assertEqual("hold", outcome.calibration.ending)


if __name__ == "__main__":
    unittest.main()
