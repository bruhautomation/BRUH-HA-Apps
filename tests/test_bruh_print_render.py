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

    def test_an_image_element_cannot_escape_its_folder(self):
        """A label file is data from outside, even when the outside is the
        person's own laptop."""
        assets = Path(tempfile.mkdtemp())
        rendered = self.render(
            {"stock": "edcc-082wh", "elements": [
                {"type": "image", "x_mm": 1, "y_mm": 1, "w_mm": 10, "h_mm": 10,
                 "props": {"asset": "../../etc/passwd"}}]},
            assets=assets)
        self.assertTrue(any("not in this label" in note
                            for note in rendered.notes))

    def test_continuous_stock_takes_its_length_from_the_artwork(self):
        rendered = self.render({"stock": "continuous-2-25", "elements": [
            {"type": "text", "x_mm": 0, "y_mm": 0, "w_mm": 50, "h_mm": 40,
             "props": {"text": "Long"}}]}, stock_id="continuous-2-25")
        self.assertGreater(rendered.feed_dots, 400)
        self.assertTrue(any("Continuous" in note for note in rendered.notes))


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
