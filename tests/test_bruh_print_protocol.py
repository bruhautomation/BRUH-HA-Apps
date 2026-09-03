#!/usr/bin/env python3
"""The bytes that reach the printer, and the model table that shapes them.

Every assertion here stands for something that would be invisible from the
outside. A wrong roll byte prints on the other roll; a missing form feed
leaves the label uncut; a long feed between copies wastes every other label;
and a status block read optimistically reports "ready" about an open lid.
None of those raises anything.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import bruh_print_env  # noqa: E402

# BRight's panel has a top-level `stores` too, so importing ours by putting
# a directory on sys.path is a collision under `unittest discover`. See
# tests/bruh_print_env.py.
printers, protocol = bruh_print_env.load("dymo.printers", "dymo.protocol")

ESC = 0x1B


class TestCommands(unittest.TestCase):
    def test_roll_select_is_the_twin_turbos_whole_point(self):
        self.assertEqual(bytes([ESC, ord("q"), 1]), protocol.select_roll(1))
        self.assertEqual(bytes([ESC, ord("q"), 2]), protocol.select_roll(2))

    def test_a_roll_that_does_not_exist_is_refused(self):
        """Silently clamping a bad roll to 1 would print the label on the
        left roll and report success about the right one."""
        for bad in (0, 3, -1, "left"):
            with self.subTest(roll=bad), self.assertRaises(protocol.ProtocolError):
                protocol.select_roll(bad)

    def test_label_length_is_big_endian(self):
        self.assertEqual(bytes([ESC, ord("L"), 0x01, 0x77]),
                         protocol.set_label_length(375))

    def test_an_absurd_length_clamps_rather_than_refusing(self):
        """The length is advisory — the printer feeds to the die-cut gap
        anyway — so refusing prints nothing where clamping prints the
        label."""
        self.assertEqual(bytes([ESC, ord("L"), 0xFF, 0xFF]),
                         protocol.set_label_length(999_999))

    def test_bytes_per_line_must_fit_in_one_byte(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.set_bytes_per_line(300)


class TestRaster(unittest.TestCase):
    def test_a_short_line_is_padded_and_a_long_one_is_cut(self):
        self.assertEqual(b"\xff" + b"\x00" * 83,
                         protocol.pack_line(b"\xff", 84))
        self.assertEqual(84, len(protocol.pack_line(b"\xff" * 200, 84)))

    def test_repeated_lines_become_one_byte_each(self):
        """The compression that makes a label cheap: a 1.25" label is 375
        lines of 84 bytes and most of them are the same blank line."""
        blank = b"\x00" * 84
        body = protocol.raster([blank] * 100, 84)
        self.assertEqual(protocol.SYN, body[0])
        self.assertEqual(85 + 99, len(body))
        self.assertEqual(b"\x17" * 99, body[85:])

    def test_a_changed_line_starts_a_new_run(self):
        blank, solid = b"\x00" * 84, b"\xff" * 84
        body = protocol.raster([blank, blank, solid, solid], 84)
        self.assertEqual([protocol.SYN, protocol.ETB], [body[0], body[85]])
        self.assertEqual(protocol.SYN, body[86])

    def test_measured_compression_on_a_real_shaped_label(self):
        """Not a ratio for its own sake: this is the difference between a
        job a LabelWriter takes in one bulk write and one it does not."""
        lines = [b"\x00" * 84] * 300 + [b"\xf0" * 84] * 75
        packed = protocol.raster(lines, 84)
        self.assertLess(len(packed), len(lines) * 85 // 4)


class TestJob(unittest.TestCase):
    def line(self, value=0x00):
        return bytes([value]) * 84

    def test_a_job_ends_with_a_form_feed(self):
        job = protocol.job([self.line()], bytes_per_line=84)
        self.assertTrue(job.endswith(protocol.form_feed()))

    def test_every_copy_but_the_last_gets_the_SHORT_feed(self):
        """A long feed between copies advances a whole label past the head,
        so a run of ten comes out as ten printed and ten blank."""
        job = protocol.job([self.line()], bytes_per_line=84, copies=3)
        self.assertEqual(2, job.count(protocol.short_form_feed()))
        self.assertEqual(1, job.count(protocol.form_feed()))
        self.assertTrue(job.endswith(protocol.form_feed()))

    def test_the_roll_is_selected_once_per_copy(self):
        """Re-sent per copy on purpose: seven bytes to start every label
        from a known state, rather than inheriting whatever a power cycle or
        another process left set."""
        job = protocol.job([self.line()], bytes_per_line=84,
                           roll=protocol.ROLL_RIGHT, copies=4)
        self.assertEqual(4, job.count(protocol.select_roll(2)))

    def test_no_roll_byte_is_sent_when_there_is_no_roll_to_choose(self):
        job = protocol.job([self.line()], bytes_per_line=84, roll=None)
        self.assertNotIn(bytes([ESC, ord("q")]), job)

    def test_an_empty_label_is_refused(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.job([], bytes_per_line=84)


class TestStatus(unittest.TestCase):
    def test_silence_is_not_ready(self):
        """The distinction the whole command exists for: a printer that did
        not answer is not a printer that is fine, and rendering one as the
        other is the panel inventing good news."""
        for quiet in (None, b""):
            with self.subTest(block=quiet):
                status = protocol.parse_status(quiet)
                self.assertFalse(status.answered)
                self.assertFalse(status.ok)
                self.assertEqual("no status reported", status.summary)

    def test_a_clean_answer_is_ready(self):
        status = protocol.parse_status(bytes([0x00] * 32))
        self.assertTrue(status.answered)
        self.assertTrue(status.ok)
        self.assertEqual("ready", status.summary)

    def test_trouble_is_named(self):
        status = protocol.parse_status(bytes([0x0C]))
        self.assertFalse(status.ok)
        self.assertIn("lid open", status.summary)
        self.assertIn("out of labels", status.summary)

    def test_busy_is_not_a_problem(self):
        """Busy is a printer working, so it must not read as a fault — but
        it is still worth saying, because it is why a status came back at
        all."""
        status = protocol.parse_status(bytes([0x01]))
        self.assertTrue(status.ok)
        self.assertIn("busy", status.summary)


class TestModels(unittest.TestCase):
    def test_the_twin_turbo_is_known_to_have_two_rolls(self):
        model, recognised = printers.describe(0x0022)
        self.assertTrue(recognised)
        self.assertTrue(model.twin)
        self.assertEqual(84, model.bytes_per_line)

    def test_an_unknown_dymo_is_driven_rather_than_refused(self):
        """Refusing a printer we would have driven correctly is the worse
        failure: the raster protocol has not changed in twenty years."""
        model, recognised = printers.describe(0xBEEF, "")
        self.assertFalse(recognised)
        self.assertEqual(printers.HEAD_672, model.dots)
        self.assertFalse(model.twin)

    def test_an_unknown_twin_turbo_keeps_its_second_roll(self):
        """Read off the device's own product string, so a Twin Turbo with a
        new product id does not lose a bay to a table written before it."""
        model, recognised = printers.describe(0xBEEF, "LabelWriter 450 Twin Turbo")
        self.assertFalse(recognised)
        self.assertTrue(model.twin)

    def test_an_unknown_xl_gets_the_wide_head(self):
        model, _ = printers.describe(0xBEEF, "DYMO LabelWriter 4XL")
        self.assertEqual(printers.HEAD_1248, model.dots)

    def test_the_550_generation_is_flagged_for_its_media_check(self):
        """It refuses third-party stock at the hardware level. Nothing here
        can work around that, so it has to be said rather than reported as a
        silent no-op."""
        for product in (0x1002, 0x1003, 0x1004):
            with self.subTest(product=product):
                self.assertTrue(printers.MODELS[product].authenticated_media)
        self.assertFalse(printers.MODELS[0x0022].authenticated_media)

    def test_a_printer_is_identified_by_its_serial_not_its_bus_address(self):
        """A saved default has to survive a reboot renumbering the bus."""
        first = printers.Discovered(0x0022, printers.MODELS[0x0022],
                                    serial="S1", bus=1, address=4)
        moved = printers.Discovered(0x0022, printers.MODELS[0x0022],
                                    serial="S1", bus=2, address=9)
        self.assertEqual(first.key, moved.key)

    def test_a_printer_with_no_serial_falls_back_to_where_it_is(self):
        anonymous = printers.Discovered(0x0020, printers.MODELS[0x0020],
                                        bus=1, address=4)
        self.assertIn("@1.4", anonymous.key)


if __name__ == "__main__":
    unittest.main()
