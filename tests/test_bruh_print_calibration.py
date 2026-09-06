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
# The stock's own blank border, on all four sides. It is inside the printable
# box now — `printable_box` is the ONE rectangle and the margin is one of its
# four insets — so every "how much of this label can carry ink" number below
# is a label less its dead band, its held bands AND this. 0.11.0's answer left
# the margin out, which made the designer's canvas and this number two
# different areas with one name.
MARGIN = 2.0


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
        # The whole label less its own border, and nothing else: a pre-feed
        # gives the printer the paper back, so there is no dead band left in
        # the box.
        self.assertAlmostEqual(stock.printable_feed_mm(),
                               LENGTH - 2 * MARGIN, places=2)

    def test_the_dead_band_is_what_the_print_path_lays_out_inside(self):
        stock = cryo(calibration=calibration.derive(
            readings(*grid(OWNER_START)), cryo(), now=1.0).calibration)
        self.assertAlmostEqual(stock.dead_leading_mm(), OWNER_START, places=2)
        self.assertAlmostEqual(stock.printable_feed_mm(),
                               LENGTH - OWNER_START - 2 * MARGIN, places=2)


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


class TestAnAreaSomebodyChoseRatherThanMeasured(unittest.TestCase):
    """The four bands held clear, which are the only numbers here that
    nothing on the label says.

    The reason the first one existed is still the clearest case: the printer
    starts where it starts, so a roll with a 4.75mm dead band prints inside
    4.75 -> 31.75 and the blank edges come out uneven however carefully the
    artwork is centred — and the only way anybody had to shorten the
    printable area was to type a Y2 that was not where the paper ended, which
    is a lie the arithmetic reads as a worse registration fault.

    0.11.0 shipped that one alone, at the bottom, on the argument that a band
    held at the TOP only pushes artwork further from the middle. That is true
    of the feed axis and it answers the wrong question: a person setting a
    border is saying where on the label the printing goes, not compensating
    for a machine, and the across axis has no dead band to compensate for at
    all. So there are four, they are checked per AXIS because the two on one
    share the label between them, and `margin_mm` remains the even border
    that this is deliberately not.
    """

    def test_nothing_held_back_is_the_calibration_that_shipped(self):
        """The promise every measurement here is added under: a roll that
        asks for nothing gets byte-for-byte what it got before."""
        out = calibration.derive(readings(*grid(OWNER_START)), cryo(), now=1.0)
        self.assertEqual(out.calibration.hold_trailing_mm, 0.0)
        held = calibration.derive(readings(*grid(OWNER_START)), cryo(),
                                  hold=0.0, now=1.0)
        self.assertEqual(out.calibration, held.calibration)

    def test_the_blank_edges_can_be_made_to_match(self):
        """The case the whole field is for, in the numbers it is for.

        4.75mm the printer will not reach at the top; ask for 4.75mm at the
        bottom and what is left is centred on the paper.
        """
        out = calibration.derive(readings(*grid(OWNER_START)), cryo(),
                                 hold=OWNER_START, now=1.0)
        entry = stock_store.replace(cryo(), calibration=out.calibration)
        self.assertAlmostEqual(entry.dead_leading_mm(), OWNER_START, places=2)
        self.assertAlmostEqual(entry.hold_trailing_mm(), OWNER_START, places=2)
        # Read off the box itself rather than rebuilt from three numbers:
        # `top` is where the box starts and `bottom` is what is left under
        # it, and the whole reason the box exists is that those two are one
        # answer. Both carry the stock's own margin, which is why they can
        # match at all — the margin is even by definition and what this
        # field evens out is the dead band above it.
        _, top, _, height = entry.printable_box()
        bottom = entry.feed_mm - top - height
        self.assertAlmostEqual(top, bottom, places=2,
                               msg="the two blank edges do not match")
        self.assertAlmostEqual(height, LENGTH - 2 * OWNER_START - 2 * MARGIN,
                               places=2)

    def test_the_printable_area_can_be_shorter_than_the_paper_allows(self):
        """Said plainly because it is what was asked for and refused: a
        person may choose an area smaller than the one the printer can reach,
        for no reason the arithmetic is entitled to ask about."""
        entry = cryo()
        for hold in (1.0, 5.0, 12.0, 20.0):
            with self.subTest(hold=hold):
                out = calibration.derive(readings(*grid(0.0)), entry,
                                         hold=hold, now=1.0)
                self.assertIsNotNone(out.calibration, "a chosen area refused")
                got = stock_store.replace(entry, calibration=out.calibration)
                self.assertAlmostEqual(got.printable_feed_mm(),
                                       LENGTH - hold - 2 * MARGIN, places=2)

    def test_a_hold_longer_than_the_label_is_cut_down_and_says_so(self):
        """`printable_feed_mm`'s floor would absorb this silently, which is
        the shape of guard that leaves somebody wondering why nothing
        changed."""
        out = calibration.derive(readings(*grid(0.0)), cryo(), hold=99.0,
                                 now=1.0)
        self.assertIsNotNone(out.calibration)
        self.assertLess(out.calibration.hold_trailing_mm, LENGTH)
        # Both numbers: what was typed and what it became. A note carrying
        # only the new value leaves somebody re-typing the same 99 to find
        # out why it did not take.
        self.assertIn("99", out.sentence)
        self.assertIn("more was asked for", out.sentence.lower())
        self.assertIn(f"{out.calibration.hold_trailing_mm:.1f}mm",
                      out.sentence)

    def test_it_is_not_reported_as_something_the_printer_does(self):
        """A band the machine refuses and a band a person reserved are two
        different facts, and reading them as one is how somebody concludes
        their printer is worse than it is."""
        out = calibration.derive(readings(*grid(0.0)), cryo(),
                                 hold=OWNER_START, now=1.0)
        self.assertIn("because you asked for it", out.sentence)
        self.assertIn("not because the printer", out.sentence)
        # And the headline still reports the printer honestly: this roll
        # prints from the die cut, whatever was held back below.
        self.assertIn("prints from the die cut", out.sentence)

    def test_a_negative_hold_is_nothing_rather_than_extra_paper(self):
        out = calibration.derive(readings(*grid(0.0)), cryo(), hold=-5.0,
                                 now=1.0)
        self.assertEqual(out.calibration.hold_trailing_mm, 0.0)

    def test_the_refusals_name_the_box_that_does_what_was_wanted(self):
        """A guard that refuses has to change the next attempt. Typing a
        short Y2 to shrink the area is exactly what somebody tries, and the
        old refusal answered it by talking about their stock row."""
        # Y2 far short of the label: reads as a printer starting 16mm in.
        out = calibration.derive(readings(0.0, LENGTH - 16.0), cryo(), now=1.0)
        self.assertIsNone(out.calibration)
        self.assertIn("keep clear at the bottom", out.sentence)
        # Both coordinates on the grid but describing a much shorter label.
        short = calibration.derive(readings(3.0, 15.0), cryo(), now=1.0)
        self.assertIsNone(short.calibration)
        self.assertIn("keep clear at the bottom", short.sentence)

    def test_why_this_is_a_field_and_not_a_relaxed_guard(self):
        """The refusal was the VISIBLE half of what typing a short Y2 did,
        and the quiet half is worse.

        A Y2 pulled in by 5mm is read as a printer that starts 5mm further
        into the label — which is what the coordinate means — so `start_mm`
        grows, the crop on the way out grows with it, and the artwork is
        drawn from a row the printer lays 5mm earlier than the document
        thinks. The area comes out the right SIZE in the wrong PLACE, on
        every label, with nothing on screen saying so. Relaxing the bound
        would have made that reachable for the cases it still catches
        instead of fixing it, which is why the choice got a field of its own
        and the readings kept their meaning.
        """
        entry = cryo()
        honest = calibration.derive(readings(*grid(OWNER_START)), entry,
                                    now=1.0)
        pulled_in = calibration.derive(readings(0.0, LENGTH - OWNER_START - 5.0),
                                       entry, now=1.0)
        # Both store. The second reports a dead band 5mm deeper than the one
        # the printer really has, and the crop follows it.
        self.assertAlmostEqual(pulled_in.calibration.start_mm,
                               honest.calibration.start_mm + 5.0, places=2)
        # The field says the same thing about the area and nothing at all
        # about where the printing starts, which is the whole difference.
        held = calibration.derive(readings(*grid(OWNER_START)), entry,
                                  hold=5.0, now=1.0)
        self.assertAlmostEqual(held.calibration.start_mm,
                               honest.calibration.start_mm, places=2)
        for out in (pulled_in, held):
            got = stock_store.replace(entry, calibration=out.calibration)
            self.assertAlmostEqual(
                got.printable_feed_mm(),
                LENGTH - OWNER_START - 5.0 - 2 * MARGIN, places=2)

    def test_each_of_the_four_comes_off_its_own_edge_of_the_box(self):
        """One band per side, and each takes it off the edge it names.

        Driven through the box rather than through four field reads, because
        a field stored under the right name and subtracted from the wrong
        edge is exactly the mistake four numbers invite, and it is invisible
        until somebody prints one.
        """
        entry = cryo()
        left, top, width, height = entry.printable_box()
        # Per side: what the box should be once that one band is held. A
        # NEAR band moves the corner and shrinks the box, because both are
        # the same 3mm read from opposite ends; a FAR one only shrinks it.
        # Written out rather than computed, so a wrong sign in the store
        # cannot be reproduced by a wrong sign here.
        expect = {
            "leading": (left, top + 3.0, width, height - 3.0),
            "trailing": (left, top, width, height - 3.0),
            "left": (left + 3.0, top, width - 3.0, height),
            "right": (left, top, width - 3.0, height),
        }
        for side, want in expect.items():
            with self.subTest(side=side):
                out = calibration.derive(readings(*grid(0.0)), entry,
                                         holds={side: 3.0}, now=1.0)
                got = stock_store.replace(
                    entry, calibration=out.calibration).printable_box()
                for index, (a, b) in enumerate(zip(want, got)):
                    self.assertAlmostEqual(
                        a, b, places=2,
                        msg=f"{side} put index {index} at {b}, not {a}")

    def test_a_pair_that_does_not_fit_is_scaled_rather_than_truncated(self):
        """20mm at each end of a 31.75mm label is one pair that does not fit,
        not two separate over-asks — and the commonest reason to set two at
        once is to centre something, which truncating only the second would
        silently undo."""
        out = calibration.derive(readings(*grid(0.0)), cryo(),
                                 holds={"leading": 20.0, "trailing": 20.0},
                                 now=1.0)
        cal = out.calibration
        self.assertAlmostEqual(cal.hold_leading_mm, cal.hold_trailing_mm,
                               places=2, msg="an even pair came back uneven")
        self.assertGreater(cal.hold_leading_mm, 0.0)
        entry = stock_store.replace(cryo(), calibration=cal)
        self.assertGreaterEqual(entry.printable_feed_mm(), 0.0)
        self.assertIn("20.0mm", out.sentence)

    def test_the_two_axes_are_capped_apart(self):
        """A wide label has room across it that it does not have down it, so
        a band that fits on one axis must not be cut down by the other's
        arithmetic. Checked on the cryo label, which is 57.2mm across and
        31.75mm down."""
        out = calibration.derive(readings(*grid(0.0)), cryo(),
                                 holds={"left": 20.0, "right": 20.0,
                                        "leading": 20.0, "trailing": 20.0},
                                 now=1.0)
        cal = out.calibration
        self.assertAlmostEqual(cal.hold_left_mm, 20.0, places=2,
                               msg="the across pair fits and was cut anyway")
        self.assertAlmostEqual(cal.hold_right_mm, 20.0, places=2)
        self.assertLess(cal.hold_leading_mm, 20.0)

    def test_the_sentence_names_every_side_that_is_held(self):
        """One clause for the four, and it says which edges. Four separate
        notes about four boxes somebody has just filled in is a wall of text
        confirming what they typed."""
        out = calibration.derive(readings(*grid(0.0)), cryo(),
                                 holds={"leading": 2.0, "left": 3.0},
                                 now=1.0)
        for word in ("top", "left"):
            self.assertIn(f"at the {word}", out.sentence)
        for word in ("at the bottom", "at the right"):
            self.assertNotIn(word, out.sentence)

    def test_a_swap_drops_it_because_the_feed_axis_is_a_different_edge(self):
        """It is a choice rather than a measurement and still cannot survive:
        the swap has just changed which physical dimension the feed axis
        is."""
        out = calibration.derive(readings(*grid(OWNER_START)), cryo(),
                                 hold=OWNER_START, now=1.0)
        entry = stock_store.replace(cryo(), calibration=out.calibration)
        self.assertEqual(entry.swapped().calibration.hold_trailing_mm, 0.0)

    def test_a_roll_that_only_holds_a_band_still_reads_as_calibrated(self):
        """`measured` is what decides whether the panel goes on offering the
        wizard, and a roll whose printer needs no correction but whose owner
        asked for a band has been answered."""
        cal = stock_store.Calibration(hold_trailing_mm=3.0)
        self.assertTrue(cal.measured)


class TestTheStoredAnswerCanBeShownBackAsReadings(unittest.TestCase):
    """The prefill the panel does, driven through the real derivation.

    The panel reconstructs three of the four coordinates from what is stored
    so a return visit is a nudge rather than a re-measurement, and the claim
    that makes it safe is that re-applying them changes nothing. It is
    asserted here rather than described in `app.js`, because a comment cannot
    fail.
    """

    @staticmethod
    def shown(entry):
        """`calStoredReadings` in `app.js`, in Python. Deliberately a second
        implementation: the point is that the ARITHMETIC round-trips, and a
        test that called the panel's own copy could only agree with it."""
        cal = entry.calibration
        catalog = entry.feed_mm
        length = catalog if cal.length_mm is None else cal.length_mm
        start = cal.start_mm
        y1 = -start if start < 0 else 0.0
        y2 = (y1 + length) if start < 0 else max(0.0, catalog - start)
        tenth = lambda value: round(value * 10) / 10  # noqa: E731
        return tenth(cal.across_mm), tenth(y1), tenth(y2)

    def apply(self, entry, hold=0.0):
        x1, y1, y2 = self.shown(entry)
        out = calibration.derive(readings(y1, y2, x1=x1), entry, hold=hold,
                                 now=2.0)
        self.assertIsNotNone(out.calibration,
                             f"the shown readings were refused: {out.sentence}")
        return stock_store.replace(entry, calibration=out.calibration)

    def test_applying_what_is_shown_changes_nothing(self):
        """Four times over, for every shape a roll can be in. A prefill that
        moved the answer by looking at it would be worse than an empty form,
        because the drift would be invisible and would compound."""
        for name, typed in (("late", grid(OWNER_START)),
                            ("early", grid(-3.0)),
                            ("from the die cut", grid(0.0))):
            with self.subTest(roll=name):
                first = calibration.derive(readings(*typed), cryo(), now=1.0)
                entry = stock_store.replace(cryo(),
                                            calibration=first.calibration)
                seen = [entry.calibration.start_mm]
                for _ in range(4):
                    entry = self.apply(entry)
                    seen.append(entry.calibration.start_mm)
                self.assertEqual(len(set(seen)), 1,
                                 f"re-applying walked start_mm: {seen}")

    def test_the_band_is_carried_and_not_re_derived(self):
        """It is not one of the four, so it rides beside them — and a return
        visit that dropped it would silently give the label back its bottom
        edge."""
        first = calibration.derive(readings(*grid(OWNER_START)), cryo(),
                                   hold=OWNER_START, now=1.0)
        entry = stock_store.replace(cryo(), calibration=first.calibration)
        again = self.apply(entry, hold=entry.calibration.hold_trailing_mm)
        self.assertAlmostEqual(again.calibration.hold_trailing_mm,
                               OWNER_START, places=2)
        self.assertAlmostEqual(again.calibration.start_mm,
                               entry.calibration.start_mm, places=2)

    def test_the_right_edge_is_the_one_that_cannot_come_back(self):
        """Not an oversight: X2 sets nothing on a `Calibration`. It is read
        to say whether the roll measures what its stock row claims, which is
        a sentence rather than a stored number — so an empty box is the
        honest answer and the panel says so."""
        out = calibration.derive(readings(*grid(OWNER_START), x1=0.0, x2=57.0),
                                 cryo(), now=1.0)
        stored = out.calibration.as_dict()
        self.assertNotIn("x2", stored)
        for value in stored.values():
            self.assertNotEqual(value, 57.0)
            self.assertNotEqual(value, 57.15)


if __name__ == "__main__":
    unittest.main()
