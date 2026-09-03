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
printers, protocol, usb_link = bruh_print_env.load(
    "dymo.printers", "dymo.protocol", "dymo.usb_link")

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

    def test_every_line_is_sent_whole_by_default(self):
        """The default is one SYN and one full line, every line.

        This is the shape cups-filters' DYMO path has printed with for
        twenty years, and it is the default because the alternative shipped
        and did not print. `ETB`-as-repeat is the one opcode in this file
        written from memory rather than from something unambiguous, and a
        label is mostly blank — so the compressed job was ~370 ETBs and a
        printer that does not read 0x17 that way takes the job, writes
        nothing, and reports success.
        """
        blank = b"\x00" * 84
        body = protocol.raster([blank] * 100, 84)
        self.assertEqual(100 * 85, len(body))
        self.assertNotIn(protocol.ETB, body)
        self.assertEqual([protocol.SYN] * 100,
                         [body[i * 85] for i in range(100)])

    def test_compression_is_available_and_only_when_asked(self):
        blank = b"\x00" * 84
        body = protocol.raster([blank] * 100, 84, compress=True)
        self.assertEqual(protocol.SYN, body[0])
        self.assertEqual(85 + 99, len(body))
        self.assertEqual(b"\x17" * 99, body[85:])

    def test_a_changed_line_starts_a_new_run_when_compressing(self):
        blank, solid = b"\x00" * 84, b"\xff" * 84
        body = protocol.raster([blank, blank, solid, solid], 84, compress=True)
        self.assertEqual([protocol.SYN, protocol.ETB], [body[0], body[85]])
        self.assertEqual(protocol.SYN, body[86])

    def test_the_uncompressed_job_is_a_size_usb_does_not_notice(self):
        """The saving compression buys is real and is not worth a guess: a
        full 1.25" label is 31,886 bytes, which is under 3ms of USB 2.0."""
        lines = [b"\x00" * 84] * 300 + [b"\xf0" * 84] * 75
        self.assertEqual(375 * 85, len(protocol.raster(lines, 84)))
        self.assertLess(len(protocol.raster(lines, 84, compress=True)),
                        len(lines) * 85 // 4)


class TestAJobAPrinterCanActuallyRead(unittest.TestCase):
    """0.2.0 was accepted by a real LabelWriter and printed nothing.

    Every layer said it worked: the bulk write returned its byte count, the
    status read came back, the panel said "Printed 1 on the left roll". What
    went down the wire for a 375-line label was 474 bytes, of which about
    370 were `ETB` — an opcode this file assumed meant "repeat the previous
    line". A printer that does not read it that way gets a valid preamble
    and then 370 bytes it cannot use.

    So the default job is now checked for being *decodable by a reader that
    only knows SYN*, which is the guarantee that was missing.
    """

    # The escape commands this reader knows, and how many argument bytes
    # each takes. Density (c/d/e/g) and quality (h/i) take none — they are
    # the whole command — so a job that sends them still decodes here, and
    # a reader that did not know them would reject a perfectly ordinary
    # job for being unreadable.
    _ARGS = {ord("D"): 1, ord("B"): 1, ord("q"): 1, ord("L"): 2,
             ord("E"): 0, ord("G"): 0, ord("A"): 0,
             ord("c"): 0, ord("d"): 0, ord("e"): 0, ord("g"): 0,
             ord("h"): 0, ord("i"): 0}

    @classmethod
    def _decode(cls, payload: bytes, bytes_per_line: int) -> list[bytes]:
        """Walk a job the way a printer would, knowing only SYN and ESC."""
        lines, i = [], 0
        while i < len(payload):
            byte = payload[i]
            if byte == protocol.ESC:
                letter = payload[i + 1]
                if letter not in cls._ARGS:
                    raise AssertionError(
                        f"byte {i + 1} is ESC 0x{letter:02x} ({chr(letter)!r}), "
                        f"which is not a command this printer knows")
                i += 2 + cls._ARGS[letter]
            elif byte == protocol.SYN:
                lines.append(payload[i + 1:i + 1 + bytes_per_line])
                i += 1 + bytes_per_line
            else:
                raise AssertionError(
                    f"byte {i} is 0x{byte:02x}, which a printer that knows "
                    f"only SYN and the escape commands cannot read")
        return lines

    def test_the_default_job_decodes_to_exactly_the_rows_it_was_given(self):
        rows = [bytes([i % 256]) * 84 for i in range(40)]
        payload = protocol.job(rows, bytes_per_line=84, roll=1,
                               label_length_dots=40)
        self.assertEqual(rows, self._decode(payload, 84))

    def test_a_mostly_blank_label_still_sends_every_row(self):
        """The case that failed: blank rows are most of a label, and they
        are exactly the ones compression replaced."""
        rows = [b"\x00" * 84] * 300 + [b"\xf0" * 84] * 75
        payload = protocol.job(rows, bytes_per_line=84, roll=1,
                               label_length_dots=375)
        self.assertEqual(rows, self._decode(payload, 84))
        self.assertNotIn(protocol.ETB, payload)

    def test_the_compact_mode_is_the_one_that_needs_ETB(self):
        rows = [b"\x00" * 84] * 50
        payload = protocol.job(rows, bytes_per_line=84, compress=True,
                               label_length_dots=50)
        with self.assertRaises(AssertionError):
            self._decode(payload, 84)

    def test_nothing_no_op_rides_in_the_preamble(self):
        """`ESC B 0` is a dot tab of zero — it cannot change the output, and
        a firmware that does not take the command may swallow the byte after
        it and desync the whole job. A no-op in a preamble is pure risk."""
        payload = protocol.job([b"\x00" * 84], bytes_per_line=84, roll=1,
                               label_length_dots=1)
        self.assertNotIn(bytes([protocol.ESC, ord("B")]), payload)


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


class TestHowDarkAndHowSlow(unittest.TestCase):
    """Labels came out light because nothing ever asked them not to.

    With no density and no quality command a LabelWriter runs at its own
    defaults — normal density, text speed — and on ordinary thermal stock
    that is faint. These are the two commands that change it, in the order
    cups-filters has sent them for twenty years, and the whole of the risk
    is that a firmware reads one of them as something else: which is what
    `bare` (neither byte) is the escape route from.
    """

    LINE = b"\xf0" * 84

    def test_the_preamble_opens_with_density_then_quality(self):
        """Order matters only because it is the one known to print. What
        matters here is that both arrive before the geometry: a length set
        and then a mode change is a printer asked to measure in one unit
        and print in another."""
        payload = protocol.job([self.LINE], bytes_per_line=84,
                               label_length_dots=1,
                               density="dark", quality="graphics")
        self.assertTrue(payload.startswith(b"\x1bg\x1bi"), payload[:8])
        self.assertLess(payload.index(b"\x1bi"),
                        payload.index(bytes([ESC, ord("L")])))

    def test_the_roll_still_comes_first(self):
        payload = protocol.job([self.LINE], bytes_per_line=84, roll=1,
                               label_length_dots=1,
                               density="dark", quality="graphics")
        self.assertTrue(payload.startswith(
            protocol.select_roll(1) + b"\x1bg\x1bi"))

    def test_both_are_re_sent_for_every_copy(self):
        """Same reasoning as the roll byte: four bytes to start each label
        from a known state rather than inheriting the last job's."""
        payload = protocol.job([self.LINE], bytes_per_line=84, copies=3,
                               label_length_dots=1,
                               density="dark", quality="graphics")
        self.assertEqual(3, payload.count(b"\x1bg"))
        self.assertEqual(3, payload.count(b"\x1bi"))

    def test_graphics_mode_sends_every_line_twice(self):
        """The printer steps the paper 600 times per inch in this mode and
        the renderer draws 300 — so a label whose rows went once would come
        out half its length, with everything on it squashed."""
        rows = [bytes([i]) * 84 for i in range(10)]
        payload = protocol.job(rows, bytes_per_line=84,
                               label_length_dots=10,
                               density="dark", quality="graphics")
        decoded = TestAJobAPrinterCanActuallyRead._decode(payload, 84)
        self.assertEqual([row for row in rows for _ in (0, 1)], decoded)

    def test_graphics_mode_doubles_the_label_length(self):
        """`ESC L` is counted in the same 600-per-inch steps, so a length
        left at 375 would tell the printer the label is half as long as the
        raster it is about to receive."""
        payload = protocol.job([self.LINE] * 375, bytes_per_line=84,
                               label_length_dots=375,
                               density="dark", quality="graphics")
        self.assertIn(protocol.set_label_length(750), payload)
        self.assertNotIn(protocol.set_label_length(375), payload)

    def test_text_mode_sends_each_line_once_and_the_plain_length(self):
        rows = [bytes([i]) * 84 for i in range(10)]
        payload = protocol.job(rows, bytes_per_line=84,
                               label_length_dots=10,
                               density="normal", quality="text")
        self.assertEqual(rows,
                         TestAJobAPrinterCanActuallyRead._decode(payload, 84))
        self.assertIn(protocol.set_label_length(10), payload)
        self.assertIn(b"\x1bh", payload)

    def test_bare_sends_neither_byte_and_is_the_job_that_always_shipped(self):
        """`bare` is the escape route: the printer at its own defaults, and
        byte-for-byte what this add-on sent before darkness existed. If the
        two ever differ, the mode somebody falls back to is not the one
        that used to work."""
        rows = [bytes([i]) * 84 for i in range(20)]
        bare = protocol.job(rows, bytes_per_line=84, roll=1, copies=2,
                            label_length_dots=20,
                            density=None, quality=None)
        before = protocol.job(rows, bytes_per_line=84, roll=1, copies=2,
                              label_length_dots=20)
        self.assertEqual(before, bare)
        for command in (b"\x1bc", b"\x1bd", b"\x1be", b"\x1bg",
                        b"\x1bh", b"\x1bi"):
            self.assertNotIn(command, bare, command)

    def test_an_unknown_density_or_quality_is_refused(self):
        """Falling through to the printer's default would be a darkness
        setting that silently did nothing — the complaint, restated."""
        for level in ("darkk", "DARK", "", "very dark"):
            with self.subTest(density=level), \
                    self.assertRaises(protocol.ProtocolError):
                protocol.job([self.LINE], bytes_per_line=84, density=level)
        for mode in ("graphic", "TEXT", "photo"):
            with self.subTest(quality=mode), \
                    self.assertRaises(protocol.ProtocolError):
                protocol.job([self.LINE], bytes_per_line=84, quality=mode)

    def test_the_helpers_refuse_the_same_way(self):
        self.assertEqual(b"\x1bc", protocol.set_density("light"))
        self.assertEqual(b"\x1be", protocol.set_density("normal"))
        with self.assertRaises(protocol.ProtocolError):
            protocol.set_density("darker")
        with self.assertRaises(protocol.ProtocolError):
            protocol.set_quality("fast")


class TestWhichAltsettingWePrintThrough(unittest.TestCase):
    """`config[(0, 0)]` — interface 0, altsetting 0 — is what shipped.

    The USB printer class defines two protocols and devices routinely
    expose both as ALTSETTINGS of one interface: `01` unidirectional (bulk
    OUT only) and `02` bidirectional (OUT and IN). Altsetting 0 is very
    often the unidirectional one, so hardcoding it takes the read channel
    away — which is why "Ask the printer" could only ever answer that it
    had nothing to report: there was no endpoint to read from.
    """

    class _Endpoint:
        def __init__(self, address, attributes):
            self.bEndpointAddress = address
            self.bmAttributes = attributes
            self.wMaxPacketSize = 64

    class _Interface:
        def __init__(self, number, alt, endpoints, protocol=2):
            self.bInterfaceNumber = number
            self.bAlternateSetting = alt
            self.bInterfaceClass = 7
            self.bInterfaceProtocol = protocol
            self._endpoints = endpoints

        def __iter__(self):
            return iter(self._endpoints)

    class _Config:
        def __init__(self, interfaces):
            self._interfaces = interfaces

        def __iter__(self):
            return iter(self._interfaces)

        def __getitem__(self, key):
            return self._interfaces[0]

    class _Util:
        """Just the four things `_endpoint` asks of `usb.util`.

        pyusb lives in the add-on image and not in the test environment, and
        depending on it here would test pyusb rather than the choice this
        module makes. The constants are USB's own.
        """
        ENDPOINT_IN, ENDPOINT_OUT, ENDPOINT_TYPE_BULK = 0x80, 0x00, 2

        @staticmethod
        def endpoint_direction(address):
            return address & 0x80

        @staticmethod
        def endpoint_type(attributes):
            return attributes & 0x03

    def _link(self):
        link = usb_link.Link.__new__(usb_link.Link)
        link._usb = type("usb", (), {"util": self._Util})
        return link

    def _printer_class_device(self):
        """What a great many USB printers actually look like."""
        out = self._Endpoint(0x01, 2)   # bulk OUT
        inn = self._Endpoint(0x82, 2)   # bulk IN
        return self._Config([
            self._Interface(0, 0, [out], protocol=1),        # unidirectional
            self._Interface(0, 1, [out, inn], protocol=2),   # bidirectional
        ])

    def test_the_bidirectional_altsetting_wins(self):
        chosen, why = self._link()._pick_interface(self._printer_class_device())
        self.assertEqual(1, chosen.bAlternateSetting,
                         "altsetting 0 is the unidirectional one here")
        self.assertIn("bulk in and out", why)

    def test_a_printer_with_only_one_direction_still_prints(self):
        """Losing status is not a reason to refuse to print."""
        out = self._Endpoint(0x01, 2)
        config = self._Config([self._Interface(0, 0, [out], protocol=1)])
        chosen, why = self._link()._pick_interface(config)
        self.assertEqual(0, chosen.bAlternateSetting)
        self.assertIn("cannot report status", why)

    def test_an_interface_with_no_bulk_out_is_never_chosen(self):
        inn = self._Endpoint(0x82, 2)
        out = self._Endpoint(0x01, 2)
        config = self._Config([
            self._Interface(0, 0, [inn]),          # nothing to print through
            self._Interface(0, 1, [out, inn]),
        ])
        chosen, _ = self._link()._pick_interface(config)
        self.assertEqual(1, chosen.bAlternateSetting)

    def test_the_choice_is_reported_rather_than_made_silently(self):
        """A choice nobody can check is a choice nobody can correct — and
        this one was wrong for two releases without any way to see it."""
        _, why = self._link()._pick_interface(self._printer_class_device())
        self.assertTrue(why.strip())
        self.assertIn("interface 0 altsetting 1", why)


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
                self.assertIn("did not answer", status.summary)

    def test_the_two_silences_do_not_share_a_sentence(self):
        """"No status reported" meant both "the printer stayed quiet" and
        "there is no channel to ask on", so a person read it and went to
        check a printer that was fine.

        Only the first is about the printer. The second is about which USB
        altsetting we are printing through, and it is the one that used to
        be reported as the printer's fault.
        """
        quiet = protocol.Status(answered=False)
        deaf = protocol.Status(answered=False, unreadable=True)
        self.assertNotEqual(quiet.summary, deaf.summary)
        self.assertIn("did not answer", quiet.summary)
        self.assertIn("read-back", deaf.summary)
        self.assertIn("printing is unaffected", deaf.summary)
        # Neither is ever good news.
        self.assertFalse(quiet.ok)
        self.assertFalse(deaf.ok)

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
