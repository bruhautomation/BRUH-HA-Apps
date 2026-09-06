#!/usr/bin/env python3
"""Four coordinates off a printed grid, and the rectangle they name.

The derivation is pure, which is the point of it being its own module: the
numbers in here are the ones the owner of the printer actually measured, and a
derivation spread across a request handler could only ever be checked by
printing another label.

**Every fixture here is a COORDINATE, and that is what this file was rewritten
for.** 0.9.x asked for six signed readings across two labels and had three
hypotheses to tell apart, because it was asking for an offset — how far raster
row 0 is from the die cut, and which way — and an offset is not a thing drawn
on a label. It has to be inferred, and the sign is exactly the part nobody can
see. So the helpers below build the grid coordinates a person would really
read off the paper, and the arithmetic that turns them into a dead band or a
pre-feed lives in the module rather than in a fixture that could disagree with
it.

The one boundary left is asserted from both sides: a label whose top edge is
above the grid reads `y1 = 0` — because that is what a coordinate does at the
end of a scale — and a label whose top edge is on the grid reads the number it
falls at. Nothing else in the file branches.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import bruh_print_env  # noqa: E402

calibration, stock_store = bruh_print_env.load("calibration", "stores.stock")

# The roll everything in this file was measured on: the 2.25" x 1.25" cryo
# label, 31.75mm along the roll, whose printer starts 4.75mm late.
LENGTH = 31.75
OWNER_START = 4.75


def cryo(**changes):
    return stock_store.Stock(id="edcc-082wh", name="Cryo", across_in=2.25,
                             feed_in=1.25, **changes)


def grid(start, length=LENGTH):
    """The two Y coordinates a roll gives when the printer starts `start` late.

    Positive `start` is the measured case and the common one: the grid's own 0
    is `start` past the leading die cut, so the label's top edge is above the
    grid and reads 0, and its bottom edge falls that much short of the label's
    own length. Negative is the other one, where the printing began before the
    die cut and both edges are on the grid.

    Written once, here, so a fixture cannot disagree with the module about
    which side of zero a coordinate came from — the failure the six-reading
    version of this file spent two helpers guarding against.
    """
    if start >= 0:
        return 0.0, length - start
    return -start, -start + length


def readings(y1, y2, *, x1=0.0, x2=None):
    return calibration.Readings(x1=x1, y1=y1, y2=y2, x2=x2)


class TestTheTopEdgeIsACoordinateAndNotACase(unittest.TestCase):
    """The one boundary the grid has, asserted from both sides.

    Nothing can print before the first row the printer lays, so a label whose
    leading edge is above that row has no scale up there to be read against —
    and 0 is both the honest reading and the useful one, because the printable
    area starts at the grid's own origin whatever is above it. A number is the
    other side of the same rule: the die cut fell on the grid, so it has a
    coordinate like anything else on it.
    """

    def test_zero_at_the_top_is_a_reading_and_not_a_missing_one(self):
        out = calibration.derive(readings(*grid(OWNER_START)), cryo(),
                                 now=1.0)
        self.assertIsNotNone(out.calibration)
        self.assertAlmostEqual(out.calibration.start_mm, OWNER_START, places=2)

    def test_a_number_at_the_top_can_only_be_a_printer_starting_early(self):
        out = calibration.derive(readings(*grid(-2.0)), cryo(), now=1.0)
        self.assertAlmostEqual(out.calibration.start_mm, -2.0, places=2)
        self.assertEqual(out.shape, "prints_early")

    def test_nothing_is_derived_from_a_band_that_was_never_printed_in(self):
        """The dead band's size comes from the far edge, never from the top.

        Two rolls that are late by different amounts read the same 0 at the
        top and different numbers at the bottom, and the answer has to follow
        the bottom one. If it ever followed the top, both would derive the
        same start — which is precisely the failure the whole rewrite is
        about.
        """
        shallow = calibration.derive(readings(*grid(1.5)), cryo(), now=1.0)
        deep = calibration.derive(readings(*grid(8.0)), cryo(), now=1.0)
        self.assertAlmostEqual(shallow.calibration.start_mm, 1.5, places=2)
        self.assertAlmostEqual(deep.calibration.start_mm, 8.0, places=2)


class TestTheRectangleIsTheAnswer(unittest.TestCase):
    """Four coordinates in, one printable area out."""

    def test_the_measured_case_is_a_dead_band_and_nothing_else(self):
        out = calibration.derive(readings(*grid(OWNER_START), x1=0.4),
                                 cryo(), now=1.0)
        cal = out.calibration
        self.assertEqual(out.shape, "dead_band")
        self.assertAlmostEqual(cal.start_mm, OWNER_START, places=2)
        self.assertAlmostEqual(cal.across_mm, 0.4, places=2)
        # The two that needed a second printed copy to see. They are not
        # measured any more and they may not be invented either.
        self.assertEqual(cal.after_tear_mm, 0.0)
        self.assertIsNone(cal.gap_mm)
        self.assertEqual(cal.job_start, "plain")
        self.assertIn("4.8mm of each label", out.sentence)

    def test_a_printer_that_starts_on_the_die_cut_stores_nothing_to_correct(self):
        out = calibration.derive(readings(*grid(0.0)), cryo(), now=1.0)
        self.assertEqual(out.shape, "from_the_die_cut")
        self.assertEqual(out.calibration.start_mm, 0.0)
        self.assertIn("prints from the die cut", out.sentence)

    def test_a_reading_inside_the_tolerance_is_zero_rather_than_a_wobble(self):
        """A person against a printed millimetre scale is not accurate to a
        tenth, and 0.4mm saved as a correction crops a row off every label for
        a number that describes the reading rather than the printer."""
        out = calibration.derive(readings(*grid(0.4)), cryo(), now=1.0)
        self.assertEqual(out.calibration.start_mm, 0.0)
        self.assertTrue(out.calibration.measured)

    def test_ink_asked_for_before_the_die_cut_is_a_negative_start(self):
        out = calibration.derive(readings(*grid(-3.0)), cryo(), now=1.0)
        self.assertAlmostEqual(out.calibration.start_mm, -3.0, places=2)
        self.assertIn("before the die cut", out.sentence)

    def test_the_whole_label_is_printable_when_the_printer_starts_early(self):
        stock = cryo(calibration=calibration.derive(
            readings(*grid(-3.0)), cryo(), now=1.0).calibration)
        self.assertEqual(stock.dead_leading_mm(), 0.0)
        self.assertAlmostEqual(stock.printable_feed_mm(), LENGTH, places=2)

    def test_the_dead_band_is_what_the_print_path_lays_out_inside(self):
        stock = cryo(calibration=calibration.derive(
            readings(*grid(OWNER_START)), cryo(), now=1.0).calibration)
        self.assertAlmostEqual(stock.dead_leading_mm(), OWNER_START, places=2)
        self.assertAlmostEqual(stock.printable_feed_mm(),
                               LENGTH - OWNER_START, places=2)


class TestReadingsThatCannotBeARectangle(unittest.TestCase):
    """One outcome stores nothing, and it is the arithmetic not closing.

    0.9.x had two: this, and the first half of a two-print hypothesis. The
    second is gone with the second print — there is one job, one grid and one
    answer — so a refusal here is always a misread grid and always says which
    number to read again.
    """

    def test_a_bottom_edge_at_the_very_first_row_is_refused(self):
        out = calibration.derive(readings(0.0, 0.0), cryo(), now=1.0)
        self.assertIsNone(out.calibration)
        self.assertEqual(out.shape, "impossible")
        self.assertIn("BOTTOM edge", out.sentence)

    def test_a_bottom_edge_above_the_top_one_is_refused(self):
        out = calibration.derive(readings(20.0, 12.0), cryo(), now=1.0)
        self.assertIsNone(out.calibration)
        self.assertIn("not past the top one", out.sentence)

    def test_a_late_start_past_any_registration_fault_blames_the_stock(self):
        """A late start is derived FROM the catalogued length, so past any
        plausible fault the likelier answer is that the roll is not the length
        its row says — and that is what it has to say, rather than storing an
        enormous dead band nothing could print inside."""
        out = calibration.derive(readings(0.0, 10.0), cryo(), now=1.0)
        self.assertIsNone(out.calibration)
        self.assertIn("not 31.8mm long", out.sentence)

    def test_a_top_edge_far_down_the_grid_is_a_scale_read_the_wrong_way(self):
        """On a grid carrying two scales, reading Y off the across one is the
        mistake worth naming — and it lands as a top edge further down the
        sheet than any printer starts early."""
        out = calibration.derive(readings(20.0, 51.75), cryo(), now=1.0)
        self.assertIsNone(out.calibration)
        self.assertIn("running DOWN the label", out.sentence)

    def test_a_label_that_is_not_this_label_is_refused_not_stored(self):
        out = calibration.derive(readings(2.0, 12.0), cryo(), now=1.0)
        self.assertIsNone(out.calibration)
        self.assertIn("a different label", out.sentence)

    def test_a_right_edge_before_the_left_one_is_refused(self):
        out = calibration.derive(
            readings(*grid(OWNER_START), x1=20.0, x2=8.0), cryo(), now=1.0)
        self.assertIsNone(out.calibration)
        self.assertIn("not past the left one", out.sentence)


class TestWhatTheCoordinatesSayAboutTheStockItself(unittest.TestCase):
    """Said rather than acted on, in every case."""

    def test_the_left_edge_is_where_the_paper_sits_on_the_head(self):
        """Stored as it was read. It IS the position of the paper on a
        672-dot head, which is what the old pair of across numbers were
        always one quantity pretending to be two."""
        out = calibration.derive(
            readings(*grid(OWNER_START), x1=20.1), cryo(), now=1.0)
        self.assertAlmostEqual(out.calibration.across_mm, 20.1, places=2)

    def test_a_label_whose_top_edge_is_off_the_grid_measures_no_length(self):
        """Those readings did not measure a length — the top edge is above
        the scale — so `y2 - y1` is how much of the label can carry ink
        rather than how long it is, and reading it back as a length would
        store a roll several millimetres shorter than it really is."""
        out = calibration.derive(readings(*grid(OWNER_START)), cryo(), now=1.0)
        self.assertIsNone(out.calibration.length_mm)

    def test_a_length_that_merely_confirms_the_catalog_is_not_stored(self):
        """A second copy of a number already on the row is what drifts the
        day somebody corrects one."""
        out = calibration.derive(readings(*grid(-2.0)), cryo(), now=1.0)
        self.assertIsNone(out.calibration.length_mm)
        self.assertNotIn("along the roll where the catalog", out.sentence)

    def test_a_length_that_disagrees_is_stored_and_mentioned(self):
        out = calibration.derive(readings(2.0, 2.0 + 28.0), cryo(), now=1.0)
        self.assertAlmostEqual(out.calibration.length_mm, 28.0, places=2)
        self.assertIn("28.0mm along the roll", out.sentence)

    def test_a_width_that_disagrees_with_the_catalog_is_mentioned(self):
        out = calibration.derive(
            readings(*grid(OWNER_START), x1=2.0, x2=52.0), cryo(), now=1.0)
        self.assertIn("50.0mm across", out.sentence)
        self.assertIsNotNone(out.calibration)

    def test_a_label_wider_than_the_head_has_no_right_edge_to_read(self):
        out = calibration.derive(
            readings(*grid(OWNER_START), x1=0.0, x2=None), cryo(), now=1.0)
        self.assertIsNotNone(out.calibration)
        self.assertFalse(out.swap_suggested)
        self.assertNotIn("across where the catalog", out.sentence)

    def test_two_measurements_the_wrong_way_round_are_offered_not_applied(self):
        """The single most common way a label comes out rotated, and the one
        thing the calibration is in a position to notice — it has just
        measured both dimensions of the actual paper."""
        # The row says 1.25" across and 2.25" along; the paper measures the
        # other way round, which is the whole of what makes this reportable.
        rotated = stock_store.Stock(id="x", name="Rotated", across_in=1.25,
                                    feed_in=2.25)
        out = calibration.derive(
            calibration.Readings(x1=1.0, x2=1.0 + 57.15, y1=1.0,
                                 y2=1.0 + 31.75),
            rotated, now=1.0)
        self.assertTrue(out.swap_suggested)
        # Offered, never applied.
        self.assertAlmostEqual(out.calibration.across_mm, 1.0, places=2)

    def test_a_square_stock_is_never_reported_as_transposed(self):
        square = stock_store.Stock(id="s", name="Square", across_in=2.0,
                                   feed_in=2.0)
        out = calibration.derive(
            calibration.Readings(x1=0.0, x2=50.8, y1=0.0, y2=50.8),
            square, now=1.0)
        self.assertFalse(out.swap_suggested)


class TestTheOutcomeIsWhatThePanelSends(unittest.TestCase):
    def test_a_stored_outcome_carries_the_whole_calibration(self):
        out = calibration.derive(readings(*grid(OWNER_START)), cryo(), now=7.0)
        payload = out.as_dict()
        self.assertEqual(payload["shape"], "dead_band")
        self.assertEqual(payload["calibration"]["measured_at"], 7.0)
        self.assertFalse(payload["swap_suggested"])
        # The two-print vocabulary is gone from the wire with the second
        # print: nothing asks the panel to go and do anything else.
        self.assertNotIn("next", payload)
        self.assertNotIn("hypothesis", payload)

    def test_a_printer_that_needs_no_correction_still_counts_as_measured(self):
        """Seven default numbers otherwise read as never measured, and the
        panel would offer the wizard for ever to the person who least needs
        it."""
        out = calibration.derive(readings(*grid(0.0)), cryo(), now=99.0)
        self.assertTrue(out.calibration.measured)

    def test_the_clock_is_the_callers_and_never_read_in_here(self):
        a = calibration.derive(readings(*grid(1.0)), cryo(), now=100.0)
        b = calibration.derive(readings(*grid(1.0)), cryo(), now=200.0)
        self.assertEqual(a.calibration.measured_at, 100.0)
        self.assertEqual(b.calibration.measured_at, 200.0)

    def test_an_unstored_outcome_says_so_without_a_calibration(self):
        out = calibration.derive(readings(0.0, 0.2), cryo(), now=1.0)
        self.assertIsNone(out.as_dict()["calibration"])
        self.assertTrue(out.as_dict()["sentence"])

    def test_the_ending_a_roll_already_had_survives_a_calibration(self):
        """It is a decision about tearing labels off rather than a
        measurement, and this has just measured a job that ended in a
        tear-off by definition."""
        held = cryo(calibration=stock_store.Calibration(ending="hold"))
        out = calibration.derive(readings(*grid(2.0)), held, now=1.0)
        self.assertEqual(out.calibration.ending, "hold")

    def test_a_new_reading_replaces_an_old_calibration_whole(self):
        """Half a rectangle from today beside half an offset from March is a
        roll calibrated by two different readings, which is worse than
        either."""
        old = stock_store.Calibration(after_tear_mm=3.0, gap_mm=2.0,
                                      job_start="reset", start_mm=9.0)
        out = calibration.derive(readings(*grid(1.0)), cryo(calibration=old),
                                 now=1.0)
        self.assertEqual(out.calibration.after_tear_mm, 0.0)
        self.assertIsNone(out.calibration.gap_mm)
        self.assertEqual(out.calibration.job_start, "plain")

    def test_the_readings_are_coordinates_and_carry_no_sign(self):
        """The shape of the wire, asserted because it is the whole change: a
        person types four numbers off a scale that starts at zero, and the
        derivation decides which side of zero the answer is on."""
        fields = calibration.Readings.__dataclass_fields__
        self.assertEqual(set(fields), {"x1", "x2", "y1", "y2"})
        for name in ("top1", "bottom1", "top2", "bottom2", "left", "right"):
            self.assertNotIn(name, fields)
        self.assertFalse(hasattr(calibration, "Printed"))


if __name__ == "__main__":
    unittest.main()
