#!/usr/bin/env python3
"""Turning a label into dots.

The renderer's failures are all silent-and-plausible: a barcode whose module
width is fractional still looks like a barcode, an autofit that only tries
one arrangement still produces a label, and text drawn with anti-aliasing
still comes out — just a dot fatter than it should be, on every stem. So
these drive the real renderer and measure the pixels rather than asserting
that a function was called.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import bruh_print_env  # noqa: E402

barcode, render_image, label_doc, quick, stock_store = bruh_print_env.load(
    "render.barcode", "render.image", "render.label", "render.quick",
    "stores.stock")


def store():
    return stock_store.StockStore(Path(tempfile.mkdtemp()) / "stocks.json")


def ink_columns(rendered):
    """Which dot columns carry ink, read out of the packed raster."""
    lines = render_image.raster_lines(rendered, rendered.across_dots // 8)
    columns = set()
    for line in lines:
        for index, byte in enumerate(line):
            for bit in range(8):
                if byte & (1 << (7 - bit)):
                    columns.add(index * 8 + bit)
    return columns


class TestCode128(unittest.TestCase):
    def test_a_digit_run_switches_to_set_c(self):
        """Set C encodes two digits per symbol, which is what fits a 16
        character lot number on a 0.56" label at all."""
        values = barcode.code128_values("1234567890123456")
        self.assertEqual(105, values[0])
        self.assertLess(len(values), 16)

    def test_an_odd_digit_tail_leaves_set_c(self):
        """Encoding the last digit of an odd run as half a pair is the
        classic way to make a barcode that scans as the wrong number."""
        values = barcode.code128_values("12345")
        self.assertIn(100, values, "never dropped back to set B for the 5")

    def test_short_runs_stay_in_set_b(self):
        """Each switch costs a symbol, so switching for two digits makes the
        barcode longer rather than shorter."""
        self.assertEqual(104, barcode.code128_values("A1B2")[0])

    def test_the_checksum_is_the_weighted_sum(self):
        values = barcode.code128_values("A")
        self.assertEqual([104, 33, 34, 106], values)

    def test_non_ascii_is_refused_with_a_way_out(self):
        with self.assertRaises(barcode.BarcodeError) as caught:
            barcode.code128_values("naïve")
        self.assertIn("QR", str(caught.exception))

    def test_the_quiet_zone_is_part_of_the_symbol(self):
        """Ten modules each side. A scanner that cannot see them will not
        decode, which on a label crowded to its edge is the difference
        between a barcode and a picture of one."""
        modules = barcode.code128_modules("A", quiet_modules=10)
        self.assertEqual([False] * 10, modules[:10])
        self.assertEqual([False] * 10, modules[-10:])


class TestRendering(unittest.TestCase):
    def setUp(self):
        self.stocks = store()

    def render(self, document, stock_id="edcc-082wh", **kwargs):
        stock = self.stocks.require(stock_id)
        return render_image.render(label_doc.Label.from_dict(document), stock,
                                   **kwargs)

    def test_the_output_is_pure_black_and_white(self):
        """A thermal head has no grey. An anti-aliased 50% pixel is a black
        one, so a hairline comes out solid and every barcode bar comes out a
        dot wider than the scanner expects."""
        rendered = self.render({"stock": "edcc-082wh", "elements": [
            {"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 40, "h_mm": 20,
             "props": {"text": "Spare keys"}}]})
        self.assertEqual("1", rendered.image.mode)
        levels = set(rendered.image.convert("L").tobytes())
        self.assertTrue(levels <= {0, 255},
                        f"the label carries grey: {sorted(levels - {0, 255})}")

    def test_a_label_wider_than_the_head_is_clipped_and_says_so(self):
        """Scaling to fit would shrink every element half a percent, which
        makes a barcode's module width fractional — the one thing that must
        not happen."""
        rendered = self.render({"stock": "edcc-082wh", "elements": []})
        self.assertEqual(672, rendered.across_dots)
        self.assertTrue(any("print head" in note for note in rendered.notes))

    def test_rotating_the_canvas_swaps_the_printed_dimensions(self):
        """A 0.56 x 3.44 tube wrap is designed as a long strip and printed
        as a narrow one; the SHEET is always across-the-head by feed."""
        flat = self.render({"stock": "ed1f-060wh", "elements": []},
                           stock_id="ed1f-060wh")
        turned = self.render({"stock": "ed1f-060wh", "rotate": 90,
                              "elements": []}, stock_id="ed1f-060wh")
        self.assertEqual((flat.across_dots, flat.feed_dots),
                         (turned.across_dots, turned.feed_dots))

    def test_rotation_actually_moves_the_ink(self):
        """The sheet size is the same either way, so the only proof the
        rotation happened is where the ink landed."""
        upright = self.render({"stock": "ed1f-060wh", "elements": [
            {"type": "text", "x_mm": 0, "y_mm": 0, "w_mm": 10, "h_mm": 8,
             "props": {"text": "AB", "size_mm": 3}}]}, stock_id="ed1f-060wh")
        turned = self.render({"stock": "ed1f-060wh", "rotate": 90, "elements": [
            {"type": "text", "x_mm": 0, "y_mm": 0, "w_mm": 10, "h_mm": 8,
             "props": {"text": "AB", "size_mm": 3}}]}, stock_id="ed1f-060wh")
        self.assertNotEqual(ink_columns(upright), ink_columns(turned))

    def test_ink_is_one_and_paper_is_zero(self):
        """PIL packs mode "1" with white as a set bit, which is the inverse
        of what the head wants. Flipped once, in raster_lines; done
        per-element it is one element printed as its own negative."""
        blank = self.render({"stock": "edcc-082wh", "elements": []})
        self.assertEqual(set(), ink_columns(blank))
        filled = self.render({"stock": "edcc-082wh", "elements": [
            {"type": "box", "x_mm": 0, "y_mm": 0, "w_mm": 50, "h_mm": 28,
             "props": {"fill": True}}]})
        self.assertGreater(len(ink_columns(filled)), 500)

    def test_a_barcode_that_cannot_fit_says_so_rather_than_lying(self):
        """A symbol squeezed below one dot per module is unreadable, and an
        unreadable barcode looks exactly like a readable one."""
        rendered = self.render({"stock": "edcc-082wh", "elements": [
            {"type": "barcode", "x_mm": 1, "y_mm": 1, "w_mm": 6, "h_mm": 10,
             "props": {"data": "A-VERY-LONG-LOT-NUMBER-1234567890"}}]})
        self.assertTrue(any("modules" in note for note in rendered.notes))

    def test_a_fixed_size_that_does_not_fit_is_reported_never_shrunk(self):
        """The person set the height on purpose, probably to match another
        element; quietly changing it is how two labels that should look
        identical do not."""
        rendered = self.render({"stock": "edcc-082wh", "elements": [
            {"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 10, "h_mm": 4,
             "props": {"text": "A very long line indeed", "size_mm": 12}}]})
        self.assertTrue(any("does not fit" in note for note in rendered.notes))

    def test_an_element_dragged_off_the_label_is_clamped_not_refused(self):
        """A box half off a 0.56" label is a finger on a phone. Printing the
        part that fits beats printing nothing."""
        rendered = self.render({"stock": "edcc-082wh", "elements": [
            {"type": "box", "x_mm": 400, "y_mm": 400, "w_mm": 90, "h_mm": 90,
             "props": {"fill": True}}]})
        self.assertEqual([], [n for n in rendered.notes if "could not" in n])

    def test_an_unknown_element_type_is_refused(self):
        """Rendering it as nothing would be a label silently missing its
        barcode."""
        with self.assertRaises(ValueError):
            label_doc.Label.from_dict(
                {"stock": "edcc-082wh",
                 "elements": [{"type": "hologram", "props": {}}]})

    def test_a_retired_element_is_dropped_and_the_label_still_opens(self):
        """The other half of the same rule, and it may not refuse.

        `image` left the catalog in 0.8.0. Refusing a document that holds
        one — which is what leaving it out of CATALOG alone would do — would
        make the rest of somebody's saved label unopenable and unprintable
        over a box that could never have held a picture: there was never an
        upload control to put one in it. So the box goes, the text stays,
        and the reason rides out on the notes every print already reads
        back.
        """
        document = {"stock": "edcc-082wh", "elements": [
            {"type": "image", "x_mm": 1, "y_mm": 1, "w_mm": 10, "h_mm": 10,
             "props": {"asset": "logo.png"}},
            {"type": "text", "x_mm": 1, "y_mm": 12, "w_mm": 40, "h_mm": 10,
             "props": {"text": "Spare keys"}}]}
        parsed = label_doc.Label.from_dict(document)
        self.assertEqual(["text"], [e.type for e in parsed.elements])
        self.assertTrue(parsed.notes, "the drop happened silently")

        # A note nothing carries out is a drop nobody hears about, so the
        # render is driven too rather than trusting the label object.
        rendered = render_image.render(parsed, self.stocks.require("edcc-082wh"))
        self.assertTrue(any("image" in note for note in rendered.notes),
                        rendered.notes)
        self.assertIn("Spare keys",
                      [e.props.get("text") for e in parsed.elements])

    def test_continuous_stock_takes_its_length_from_the_artwork(self):
        rendered = self.render({"stock": "continuous-2-25", "elements": [
            {"type": "text", "x_mm": 0, "y_mm": 0, "w_mm": 50, "h_mm": 40,
             "props": {"text": "Long"}}]}, stock_id="continuous-2-25")
        self.assertGreater(rendered.feed_dots, 400)
        self.assertTrue(any("Continuous" in note for note in rendered.notes))


class TestTextFitsItsInk(unittest.TestCase):
    """Text was fitted and placed by the LINE BOX, which is neither edge.

    Two measurements were wrong in the same direction and the complaint was
    both of them at once — "labels are kind of falling off edges". Vertically
    a line box reserves room for the ascenders and descenders of glyphs a
    given word may not contain (DejaVu's is ~1.29em against a cap height of
    0.73em), so a word fitted to it filled about 60% of the height it was
    given. Horizontally the width came from `textlength`, the ADVANCE — where
    the next glyph would start — so a "W" or a "j" put ink outside the box on
    either end, and on a quick label the box is the whole drawable area.

    Measured on this fixture, a 40 × 12mm box on the 2.25 × 1.25 cryo stock:
    "Rice" filled **0.599** of the box's height before and **0.958** after.
    """

    def setUp(self):
        self.stocks = store()
        self.cryo = self.stocks.require("edcc-082wh")
        self.margin = render_image.mm_to_dots(self.cryo.margin_mm, 300)

    def ink_box(self, rendered):
        """(left, right, top, bottom) of every black dot on the sheet."""
        image = rendered.image.convert("L")
        pixels = image.load()
        rows = [y for y in range(image.height)
                if any(pixels[x, y] == 0 for x in range(image.width))]
        columns = [x for x in range(image.width)
                   if any(pixels[x, y] == 0 for y in range(image.height))]
        self.assertTrue(rows and columns, "nothing was drawn at all")
        return columns[0], columns[-1], rows[0], rows[-1]

    def render(self, document, stock_id="edcc-082wh", **kwargs):
        stock = self.stocks.require(stock_id)
        return render_image.render(label_doc.Label.from_dict(document), stock,
                                   **kwargs)

    def test_a_fitted_word_fills_the_height_it_was_given(self):
        rendered = self.render({"stock": "edcc-082wh", "elements": [
            {"type": "text", "x_mm": 2, "y_mm": 2, "w_mm": 40, "h_mm": 12,
             "props": {"text": "Rice"}}]})
        _, _, top, bottom = self.ink_box(rendered)
        box_height = render_image.mm_to_dots(12, 300)
        filled = (bottom - top + 1) / box_height
        self.assertGreater(
            filled, 0.70,
            f"the word fills {filled:.0%} of its box; the line-box "
            f"measurement this replaced filled 60%")

    def test_a_quick_label_keeps_off_the_drawable_edge(self):
        """The complaint, in one measurement: on the quick path the text box
        IS the drawable area, so a measurement that ran to the advance width
        put the last glyph's ink on the die cut."""
        fitted = quick.fit("Freezer", self.cryo)
        rendered = render_image.render(fitted.label, self.cryo)
        left, right, top, bottom = self.ink_box(rendered)
        self.assertGreater(left, self.margin, "ink on the left margin")
        self.assertLess(right, rendered.across_dots - self.margin - 1,
                        "ink on the right margin")
        self.assertGreater(top, self.margin, "ink on the top margin")
        self.assertLess(bottom, rendered.feed_dots - self.margin - 1,
                        "ink on the bottom margin")

    def test_descenders_and_overhangs_stay_inside_their_box_at_any_turn(self):
        """"Wj", "Ay" and "fgj" are the shapes that hang past their advance
        and below their baseline. A rotation swaps which edge that is, so all
        four are asserted rather than the one that happens to be tested."""
        left_mm, top_mm, width_mm, height_mm = 5, 3, 30, 15
        box = (self.margin + render_image.mm_to_dots(left_mm, 300),
               self.margin + render_image.mm_to_dots(top_mm, 300),
               render_image.mm_to_dots(width_mm, 300),
               render_image.mm_to_dots(height_mm, 300))
        for text in ("Wj", "Ay", "fgj"):
            for turn in (0, 90, 180, 270):
                with self.subTest(text=text, turn=turn):
                    rendered = self.render(
                        {"stock": "edcc-082wh", "elements": [
                            {"type": "text", "x_mm": left_mm, "y_mm": top_mm,
                             "w_mm": width_mm, "h_mm": height_mm,
                             "props": {"text": text, "rotate": turn}}]})
                    left, right, top, bottom = self.ink_box(rendered)
                    self.assertGreaterEqual(left, box[0])
                    self.assertLess(right, box[0] + box[2])
                    self.assertGreaterEqual(top, box[1])
                    self.assertLess(bottom, box[1] + box[3])

    def test_an_autofitted_word_is_centred_by_its_ink(self):
        """Centring on the advance width leaves the block visibly left of
        centre — six dots on this box, which is the trailing side bearing of
        the last glyph and nothing else."""
        rendered = self.render({"stock": "edcc-082wh", "elements": [
            {"type": "text", "x_mm": 2, "y_mm": 2, "w_mm": 40, "h_mm": 12,
             "props": {"text": "Jam", "align": "center",
                       "valign": "middle"}}]})
        left, right, top, bottom = self.ink_box(rendered)
        box_x = self.margin + render_image.mm_to_dots(2, 300)
        box_y = self.margin + render_image.mm_to_dots(2, 300)
        centre_x = box_x + render_image.mm_to_dots(40, 300) / 2
        centre_y = box_y + render_image.mm_to_dots(12, 300) / 2
        self.assertLessEqual(abs((left + right) / 2 - centre_x), 2)
        self.assertLessEqual(abs((top + bottom) / 2 - centre_y), 2)

    def test_the_inset_is_at_least_a_dot_and_scales_with_the_box(self):
        """A proportion alone disappears on a 0.56" strip and a fixed number
        of dots eats a small label."""
        self.assertEqual(1, render_image.text_inset(10, 10))
        self.assertEqual(3, render_image.text_inset(472, 142))


class TestTheMarginIsThePrintersNotYours(unittest.TestCase):
    def test_the_default_is_two_millimetres(self):
        """One was measured against the wrong thing: a LabelWriter's
        registration wanders either way as the roll unwinds, so 1mm was text
        on the die cut every other label."""
        self.assertEqual(2.0, stock_store.DEFAULT_MARGIN_MM)
        self.assertEqual(2.0, store().require("edcc-082wh").margin_mm)

    def test_a_stock_that_saved_its_own_margin_keeps_it(self):
        """The whole point of an override: a correction made against the old
        default is not undone by the default moving."""
        stocks = store()
        stocks.put(stock_store.replace(stocks.require("edcc-082wh"),
                                       margin_mm=0.5))
        self.assertEqual(0.5, stocks.require("edcc-082wh").margin_mm)


class TestBarcodeGeometry(unittest.TestCase):
    """The one thing that decides whether a small barcode scans."""

    def test_every_bar_is_a_whole_number_of_dots(self):
        """A fractional module width rounds each bar independently, so five
        1.4-dot bars come out 1, 1, 2, 1, 2 and the scanner reads the wrong
        widths."""
        stocks = store()
        stock = stocks.require("edcc-082wh")
        document = label_doc.Label.from_dict({"stock": "edcc-082wh", "elements": [
            {"type": "barcode", "x_mm": 2, "y_mm": 2, "w_mm": 50, "h_mm": 20,
             "props": {"data": "LOT-2026-0093", "hri": False, "quiet": 10}}]})
        rendered = render_image.render(document, stock)
        lines = render_image.raster_lines(rendered, 84)

        # Take a line through the bars and measure every run.
        row = lines[len(lines) // 3]
        bits = [(row[i // 8] >> (7 - i % 8)) & 1 for i in range(672)]
        runs, current, length = [], bits[0], 0
        for bit in bits:
            if bit == current:
                length += 1
            else:
                runs.append(length)
                current, length = bit, 1
        runs.append(length)
        inner = runs[1:-1]          # drop the paper either side of the symbol
        self.assertTrue(inner, "no bars were drawn at all")
        unit = min(inner)
        for run in inner:
            self.assertEqual(0, run % unit,
                             f"a run of {run} dots is not a whole number of "
                             f"{unit}-dot modules — this barcode will not scan")


class TestAutofit(unittest.TestCase):
    def setUp(self):
        self.stocks = store()
        self.cryo = self.stocks.require("edcc-082wh")

    def test_it_chooses_the_arrangement_not_just_the_size(self):
        """Two words are bigger stacked than side by side on a 2.25 x 1.25
        label. Trying only one arrangement is what makes an autofit label
        look like it did not try."""
        self.assertEqual(["Spare", "keys"], quick.fit("Spare keys", self.cryo).lines)

    def test_a_short_string_stays_on_one_line(self):
        self.assertEqual(["9912"], quick.fit("9912", self.cryo).lines)

    def test_more_text_comes_out_smaller(self):
        small = quick.fit("Tris-HCl pH 8.0 500 mM", self.cryo).size_mm
        large = quick.fit("9912", self.cryo).size_mm
        self.assertLess(small, large)

    def test_a_tie_prefers_the_flatter_layout(self):
        """`_arrangements` yields fewest-lines first and the comparison is
        strictly greater, so a layout that is no bigger stacked stays flat."""
        self.assertEqual(1, len(quick.fit("AB", self.cryo).lines))

    def test_the_cap_stops_a_single_character_being_silly(self):
        capped = quick.fit("9", self.cryo, max_mm=6)
        self.assertLessEqual(capped.size_mm, 6.01)

    def test_nothing_to_print_is_refused(self):
        for empty in ("", "   ", "\n"):
            with self.subTest(text=empty), self.assertRaises(ValueError):
                quick.fit(empty, self.cryo)

    def test_it_returns_a_real_label_the_designer_can_open(self):
        """A quick print that rendered its own way would be a second
        renderer to keep in step with the first."""
        fitted = quick.fit("Spare keys", self.cryo)
        rendered = render_image.render(fitted.label, self.cryo)
        self.assertGreater(len(ink_columns(rendered)), 40)

    def test_many_words_do_not_blow_up_the_search(self):
        """The exhaustive search is 2^(n-1); above the ceiling it falls back
        to a greedy layout per line count rather than trying a million."""
        fitted = quick.fit(" ".join(["word"] * 20), self.cryo)
        self.assertGreater(len(fitted.lines), 1)


class TestNumbersFromTheWire(unittest.TestCase):
    """A label document is typed by hand or written by an automation, and
    either can produce a number no canvas can be made from."""

    def test_nan_and_the_infinities_both_fall_back(self):
        """`w_mm: 1e999` parses to `inf`, and an infinite canvas is not a
        slow render — it is an allocation nothing serves. The earlier guard
        was `out == out`, which is a NaN test written as a comparison of
        identical values: it read as a typo and caught only half of this."""
        for bad in ("nan", "inf", "-inf", "1e999", float("nan")):
            with self.subTest(value=bad):
                self.assertEqual(7.0, label_doc._num(bad, 7.0))

    def test_an_ordinary_number_is_untouched(self):
        for good, want in ((3, 3.0), ("2.5", 2.5), (-1, -1.0), (0, 0.0)):
            with self.subTest(value=good):
                self.assertEqual(want, label_doc._num(good, 99.0))

    def test_a_label_refuses_with_its_own_error_type(self):
        """The panel echoes this type's message and nothing else's, so a
        ValueError raised four frames down inside Pillow never reaches the
        wire."""
        with self.assertRaises(label_doc.LabelError):
            label_doc.Label.from_dict({"elements": []})
        with self.assertRaises(label_doc.LabelError):
            label_doc.Label.from_dict(
                {"stock": "x", "elements": [{"type": "hologram"}]})


if __name__ == "__main__":
    unittest.main()


class TestWhereThePrintingStarts(unittest.TestCase):
    """The print offset, driven on the bitmap it moves.

    This is the one part of the label pipeline that cannot be checked by
    reading it: everything above the wire was *measured* correct on this
    exact stock — a 672 x 375 raster with its ink inset exactly 24 dots on
    all four sides — while the printed label came out 4.7mm low. So the
    tests below build a real label, shift a real raster, and count the dot
    rows the ink actually moved.
    """

    # The roll the misregistration was measured on, with the 5.2mm border
    # its owner had typed in by hand to compensate for it.
    def stock(self, **changes):
        return stock_store.Stock(
            id="edcc-082wh", name="Chemical-Resistant Cryo Labels",
            across_in=2.25, feed_in=1.25, margin_mm=5.2, **changes)

    def rendered(self, entry=None, text="Rice"):
        entry = entry or self.stock()
        label = label_doc.Label.from_dict({"stock": entry.id, "elements": [
            {"type": "text", "x_mm": 0, "y_mm": 0, "w_mm": 40, "h_mm": 12,
             "props": {"text": text, "font": "sans-bold", "size_mm": 0}}]})
        return render_image.render(label, entry)

    def test_the_measured_case_moves_the_ink_up_and_loses_nothing(self):
        """The report, reproduced. The printer began laying ink 4.7mm after
        the leading edge — top margin 9.9mm against a bottom of 0.3mm on a
        label whose renderer was symmetric to the dot — so the correction is
        4.7mm back toward the edge that comes out first.

        4.7mm at 300 dpi is 55.5 dot lines, which is why the diagnosis said
        "about 55": the shift rounds to 56, and 56 lines is 4.74mm. That is
        four hundredths of a millimetre of rounding on a number somebody
        read off a printed label with a ruler.
        """
        before = self.rendered()
        self.assertEqual((672, 375), before.image.size)
        box = render_image._ink_box(before.image)
        moved, note = render_image.offset_raster(before, feed_mm=-4.7)
        shifted = render_image._ink_box(moved.image)

        rows = shifted[1] - box[1]
        self.assertEqual(-56, rows)
        self.assertEqual(-56, shifted[3] - box[3], "the ink was scaled, not moved")
        self.assertAlmostEqual(-4.7, rows / 300 * 25.4, delta=0.05)
        self.assertEqual(box[0], shifted[0], "a feed offset moved it sideways")
        self.assertIsNone(note, "4.7mm of blank border is not worth a note")

    def test_the_sheet_stays_exactly_one_label(self):
        """What moves off one edge is gone and what moves on at the other is
        paper — which is the whole reason this is a raster shift rather than
        the printer's own `ESC f` skip, whose tail runs into the gap where
        nothing checks."""
        before = self.rendered()
        moved, _ = render_image.offset_raster(before, feed_mm=-4.7,
                                              across_mm=2.0)
        self.assertEqual(before.image.size, moved.image.size)
        self.assertEqual(before.feed_dots, moved.feed_dots)
        self.assertEqual(before.across_dots, moved.across_dots)

    def test_an_across_offset_moves_columns_and_not_rows(self):
        before = self.rendered()
        box = render_image._ink_box(before.image)
        moved, note = render_image.offset_raster(before, across_mm=-2.0)
        shifted = render_image._ink_box(moved.image)
        self.assertEqual(round(-2.0 / 25.4 * 300), shifted[0] - box[0])
        self.assertEqual(box[1], shifted[1])
        self.assertIsNone(note)

    def test_no_offset_is_the_same_object(self):
        """Nothing is rendered twice for a roll nobody has calibrated, which
        is every roll by default."""
        before = self.rendered()
        moved, note = render_image.offset_raster(before)
        self.assertIs(before, moved)
        self.assertIsNone(note)

    def test_a_shift_that_costs_ink_says_so_and_still_prints(self):
        """The standing rule: the stock/roll mismatch is the only refusal,
        and everything else is a note beside a label that still comes out.
        The note has to name the amount, the edge and the control."""
        before = self.rendered()
        box = render_image._ink_box(before.image)
        # Enough to take a measurable bite out of the ink itself, not just
        # the border: the ink starts 82 dot lines down a 375-line sheet.
        over_mm = (box[1] + 30) / 300 * 25.4
        moved, note = render_image.offset_raster(before, feed_mm=-over_mm)
        self.assertIsNotNone(note)
        self.assertIn("2.5mm past the leading edge", note)
        self.assertIn("Where the printing starts", note)
        self.assertIn("back toward the edge that comes out first", note)
        # And it really did print: the rest of the word is still there.
        self.assertIsNotNone(render_image._ink_box(moved.image))

    def test_the_note_is_about_lost_ink_and_not_about_a_non_zero_shift(self):
        """A correction normally slides blank border off one edge and blank
        border on at the other. A note on every print is a note nobody reads
        by the second roll, so the test is on the ink."""
        before = self.rendered()
        for feed in (-4.7, -3.0, 1.0, 4.0):
            _, note = render_image.offset_raster(before, feed_mm=feed)
            self.assertIsNone(note, f"{feed}mm of border produced a note")

    def test_ink_off_the_trailing_and_right_edges_is_reported_too(self):
        before = self.rendered()
        box = render_image._ink_box(before.image)
        down = (before.image.height - box[3] + 40) / 300 * 25.4
        right = (before.image.width - box[2] + 40) / 300 * 25.4
        _, note = render_image.offset_raster(before, feed_mm=down,
                                             across_mm=right)
        self.assertIn("past the trailing edge", note)
        self.assertIn("past the right edge", note)
        self.assertIn("to the right", note)

    def test_a_note_never_carries_a_signed_number(self):
        """Nobody knows which way "+" goes on a label printer, so a note
        saying "offset -6.4mm" is a note somebody has to work out the
        convention for before they can act on it."""
        before = self.rendered()
        _, note = render_image.offset_raster(before, feed_mm=-20.0)
        self.assertNotIn("-20", note)
        self.assertIn("20.0mm back toward", note)

    def test_a_blank_label_is_never_reported_as_losing_ink(self):
        entry = self.stock()
        label = label_doc.Label.from_dict({"stock": entry.id, "elements": []})
        blank = render_image.render(label, entry)
        _, note = render_image.offset_raster(blank, feed_mm=-20.0)
        self.assertIsNone(note)

    def test_the_note_reaches_the_list_the_caller_already_reads(self):
        """`_send` shifts a local copy and appends to the ORIGINAL's notes,
        because every handler reads `rendered.notes` after the print has
        gone out. If the two objects did not share that list the note would
        be composed, attached to a throwaway, and never seen."""
        before = self.rendered()
        moved, _ = render_image.offset_raster(before, feed_mm=-4.7)
        self.assertIs(before.notes, moved.notes)
        self.assertIs(before.problems, moved.problems)


def wire_columns(rendered, bytes_per_line=84):
    """Which dot columns of the PRINT HEAD carry ink, off the wire.

    The head, not the sheet: `ink_columns` above packs a rendered label into
    its own width, which is the right question for a 2.25" stock whose
    raster is the whole head and the wrong one for anything narrower. This
    packs the way `_send` does — through `raster_lines` and then through
    `protocol.pack_line`, which is what pads a short line — so what comes
    back is the dot columns the head is actually told to fire.
    """
    protocol, = bruh_print_env.load("dymo.protocol")
    lines = render_image.raster_lines(rendered, bytes_per_line)
    columns = set()
    for line in lines:
        packed = protocol.pack_line(line, bytes_per_line)
        for index, byte in enumerate(packed):
            for bit in range(8):
                if byte & (1 << (7 - bit)):
                    columns.add(index * 8 + bit)
    return columns


class TestWhereThePaperSitsUnderTheHead(unittest.TestCase):
    """The reported case, driven rather than described.

    A solid-fill label on the 0.56" x 3.44" cryo wrap came out inked across
    the LEFT HALF of its width and blank across the right — measured off the
    photograph at 335px of ink in a 687px label, 49%, starting 0.7mm in from
    one edge and stopping dead at the halfway point. The 2.25" stock does
    not show it at all.

    The reason is structural and it is in this file's own packing: a rendered
    sheet always lands flush against head dot 0, because `pack_line` pads a
    short line on the right. On the 2.25" stock that is invisible — the
    raster is 672 dots and covers the whole 672-dot head. On the wrap the
    raster is 168 dots, a quarter of it, and nothing anywhere in the driver
    knew where the paper sits under the other three quarters.

    So every assertion below is on the dot columns of the HEAD, read out of
    the packed bytes.
    """

    HEAD = 672
    BYTES = 84

    def wrap(self, across_in=0.56):
        """The roll from the report."""
        return stock_store.Stock(
            id="ed1f-060wh", name="Cryogenic Labels",
            across_in=across_in, feed_in=3.44)

    def filled(self, entry):
        """A solid-fill label, which is what was printed: it inks every
        column of the sheet, so the columns that carry ink ARE the columns
        the head was told to fire."""
        label = label_doc.Label.from_dict({"stock": entry.id, "elements": [
            {"type": "box", "x_mm": 0, "y_mm": 0, "w_mm": 500, "h_mm": 500,
             "props": {"fill": True, "stroke_mm": 0}}]})
        return render_image.render(label, entry, max_across_dots=self.HEAD)

    def test_the_reported_case_the_whole_raster_is_in_the_first_168_dots(self):
        """The reported state, reproduced on the wire: with nothing
        measured, a 0.56" sheet is 168 dots and every one of them is at the
        dot-0 end of a 672-dot head, whatever the paper is doing. This is
        also the default, so it is the job every unmeasured roll still
        gets — the bug and the promise are the same bytes."""
        rendered = self.filled(self.wrap())
        self.assertEqual(168, rendered.image.width)
        columns = wire_columns(rendered, self.BYTES)
        # The 2mm border is the renderer's and is correct; what matters is
        # that every inked column is inside the head's first 168, which is a
        # quarter of the head, wherever the paper actually is.
        margin = render_image.mm_to_dots(stock_store.DEFAULT_MARGIN_MM, 300)
        self.assertEqual(24, margin)
        self.assertEqual(margin, min(columns))
        self.assertEqual(167 - margin, max(columns))
        self.assertFalse([c for c in columns if c > 167],
                         "nothing is asked of the head past dot 167")

    def test_a_measured_position_puts_the_sheet_where_it_was_asked(self):
        """7.3mm in is 86 dots, which is what 49% of a 168-dot sheet
        overlapping the head's first 168 dots works out at. The sheet moves
        whole and it moves by exactly that."""
        rendered = self.filled(self.wrap())
        before = wire_columns(rendered, self.BYTES)
        placed, note = render_image.place_on_head(rendered, across_mm=7.3,
                                                  head_dots=self.HEAD)
        after = wire_columns(placed, self.BYTES)
        shift = render_image.mm_to_dots(7.3, 300)
        self.assertEqual(86, shift)
        self.assertEqual({c + shift for c in before}, after)
        self.assertEqual(len(before), len(after), "ink was lost or invented")
        self.assertIsNone(note, "blank border moving along the head is not news")

    def test_the_sheet_becomes_the_head_and_the_label_keeps_its_size(self):
        rendered = self.filled(self.wrap())
        placed, _ = render_image.place_on_head(rendered, across_mm=7.3,
                                               head_dots=self.HEAD)
        self.assertEqual(self.HEAD, placed.image.width)
        self.assertEqual(rendered.image.height, placed.image.height)
        self.assertEqual(rendered.across_dots, placed.across_dots)
        self.assertEqual(rendered.feed_dots, placed.feed_dots)

    def test_nothing_measured_is_the_same_object_and_the_same_bytes(self):
        """0.0 is the only honest default, so a roll nobody has measured has
        to get the job it always got — which on the wire it does anyway,
        because `pack_line` pads to the head. Asserted both ways: the object
        is untouched AND the columns are identical."""
        rendered = self.filled(self.wrap())
        placed, note = render_image.place_on_head(rendered, head_dots=self.HEAD)
        self.assertIs(rendered, placed)
        self.assertIsNone(note)
        self.assertEqual(wire_columns(rendered, self.BYTES),
                         wire_columns(placed, self.BYTES))

    def test_ink_pushed_past_the_last_dot_is_reported_not_vanished(self):
        """`pack_line` truncated a long line silently and said in its own
        docstring that this was safe because the renderer never draws past
        the printable width. A lateral position is exactly what can push it
        there, so the loss is measured on the ink and said out loud."""
        entry = self.wrap(across_in=2.25)
        rendered = self.filled(entry)
        placed, note = render_image.place_on_head(rendered, across_mm=10.0,
                                                  head_dots=self.HEAD)
        self.assertIsNotNone(note)
        self.assertIn("past the head’s last dot", note)
        self.assertIn("10.0mm in from the print head", note)
        self.assertIn("did not print", note)
        # And it still printed: what fits is on the head.
        columns = wire_columns(placed, self.BYTES)
        self.assertTrue(columns)
        self.assertLessEqual(max(columns), self.HEAD - 1)

    def test_a_blank_label_never_reports_losing_ink(self):
        entry = self.wrap()
        blank = render_image.render(
            label_doc.Label.from_dict({"stock": entry.id, "elements": []}),
            entry)
        _, note = render_image.place_on_head(blank, across_mm=50.0,
                                             head_dots=self.HEAD)
        self.assertIsNone(note)

    def test_the_note_reaches_the_list_the_caller_already_reads(self):
        rendered = self.filled(self.wrap())
        placed, _ = render_image.place_on_head(rendered, across_mm=7.3,
                                               head_dots=self.HEAD)
        self.assertIs(rendered.notes, placed.notes)
        self.assertIs(rendered.problems, placed.problems)


class TestTheTwoAcrossQuantitiesMeetExactlyOnce(unittest.TestCase):
    """`for_the_head` is the one place the offset and the media position
    are combined, and the ORDER is what makes them two things.

    The offset moves artwork inside a sheet that is one label long, so what
    it pushes off is ink off the LABEL. The media position moves that
    finished label along the head, so what it pushes off is ink onto no
    paper at all. Two edges, two sentences, one line on the wire — and
    adding the two millimetre figures together and shifting once would give
    the wrong answer to both.
    """

    HEAD = 672
    BYTES = 84

    def wrap(self):
        return stock_store.Stock(id="ed1f-060wh", name="Cryogenic Labels",
                                 across_in=0.56, feed_in=3.44)

    def rendered(self):
        entry = self.wrap()
        label = label_doc.Label.from_dict({"stock": entry.id, "elements": [
            {"type": "box", "x_mm": 2, "y_mm": 2, "w_mm": 6, "h_mm": 40,
             "props": {"fill": True, "stroke_mm": 0}}]})
        return render_image.render(label, entry, max_across_dots=self.HEAD)

    def test_both_reach_the_wire_and_they_do_not_cancel(self):
        before = min(wire_columns(self.rendered(), self.BYTES))
        placed, notes = render_image.for_the_head(
            self.rendered(), across_mm=-1.0, media_across_mm=7.3,
            head_dots=self.HEAD)
        after = min(wire_columns(placed, self.BYTES))
        self.assertEqual([], notes)
        self.assertEqual(render_image.mm_to_dots(7.3, 300)
                         - render_image.mm_to_dots(1.0, 300),
                         after - before)

    def test_neither_alone_is_the_default_and_the_default_is_untouched(self):
        rendered = self.rendered()
        placed, notes = render_image.for_the_head(rendered,
                                                  head_dots=self.HEAD)
        self.assertIs(rendered, placed)
        self.assertEqual([], notes)

    def test_the_offset_still_clips_at_the_LABEL_and_says_so(self):
        """The half that must not change: the sheet is one label and stays
        one label, so an offset that pushes ink off it loses that ink even
        though there is head to spare beside it. Anything else and the
        offset would silently become a second media position."""
        placed, notes = render_image.for_the_head(
            self.rendered(), across_mm=8.0, media_across_mm=0.0,
            head_dots=self.HEAD)
        self.assertEqual(1, len(notes), notes)
        self.assertIn("past the right edge", notes[0])
        self.assertIn("Where the printing starts", notes[0])
        self.assertLessEqual(max(wire_columns(placed, self.BYTES)), 167)

    def test_two_failures_are_two_sentences(self):
        """A shift that costs ink off the label AND a position that pushes
        what is left past the head are different losses at different edges,
        and one merged sentence would name neither."""
        _, notes = render_image.for_the_head(
            self.rendered(), across_mm=8.0, media_across_mm=56.0,
            head_dots=self.HEAD)
        self.assertEqual(2, len(notes), notes)
        self.assertIn("past the right edge", notes[0])
        self.assertIn("past the head’s last dot", notes[1])
