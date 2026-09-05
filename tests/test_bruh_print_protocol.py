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
    def test_the_roll_byte_is_an_ASCII_DIGIT_not_the_number(self):
        """The manual, verbatim: "31 (ASCII '1') = Left roll", "32 (ASCII
        '2') = Right roll" — and it spells ASCII out for this one command
        where every other parameter it documents is plainly binary.

        This add-on sent `0x01`/`0x02`, written from memory. A firmware that
        does not read those as roll selectors ignores the command, and every
        label then goes to whichever bay was used last: on a Twin Turbo with
        two different stocks loaded, that is a label printed on the wrong
        size of liner.
        """
        self.assertEqual(bytes([ESC, ord("q"), 0x31]),
                         protocol.select_roll(protocol.ROLL_LEFT))
        self.assertEqual(bytes([ESC, ord("q"), 0x32]),
                         protocol.select_roll(protocol.ROLL_RIGHT))
        self.assertEqual(b"\x1bq1", protocol.select_roll(protocol.ROLL_LEFT))

    def test_the_binary_values_that_shipped_are_gone(self):
        """Pinned as their own assertion because the panel's own names for
        the bays are still 1 and 2 — the translation happens at the wire,
        so a regression here is one character in one dict and nothing above
        `protocol.py` would notice."""
        for roll in (protocol.ROLL_LEFT, protocol.ROLL_RIGHT):
            with self.subTest(roll=roll):
                self.assertNotIn(bytes([ESC, ord("q"), roll]),
                                 protocol.select_roll(roll))

    def test_automatic_selection_is_documented_and_unwired(self):
        """The manual's third value, ASCII '0': "the printer assumes that
        both rolls have the same media, and it will toggle back and forth as
        rolls become empty" — which on this machine would print a 2.25"
        raster onto a 0.56" roll. It is a named constant so nobody has to
        rediscover it, and nothing may reach it through the panel's own
        vocabulary."""
        self.assertEqual(0x30, protocol.ROLL_WIRE_AUTO)
        self.assertNotIn(protocol.ROLL_WIRE_AUTO, protocol.ROLL_WIRE.values())
        self.assertNotIn(protocol.ROLL_WIRE_AUTO, protocol.ROLL_NAMES)

    def test_a_roll_that_does_not_exist_is_refused(self):
        """Silently clamping a bad roll to 1 would print the label on the
        left roll and report success about the right one."""
        for bad in (0, 3, -1, "left", 0x31):
            with self.subTest(roll=bad), self.assertRaises(protocol.ProtocolError):
                protocol.select_roll(bad)

    def test_label_length_is_big_endian(self):
        self.assertEqual(bytes([ESC, ord("L"), 0x01, 0x77]),
                         protocol.set_label_length(375))

    def test_an_absurd_length_clamps_to_the_longest_LABEL(self):
        """It clamps at 0x7FFF and not at 0xFFFF, which is what it used to
        do — and 0xFFFF is not a very long label, it is the continuous-form
        flag. A stock with a mistyped feed measurement would have put the
        printer into a different mode, where a form feed stops meaning
        "find the next hole"."""
        self.assertEqual(bytes([ESC, ord("L"), 0x7F, 0xFF]),
                         protocol.set_label_length(999_999))
        self.assertNotEqual(protocol.continuous_form(),
                            protocol.set_label_length(999_999))

    def test_the_continuous_flag_is_a_negative_two_byte_value(self):
        """The manual's own mechanism for paper with no sense holes: "any
        negative 2 byte integer value (0x8000-0xFFFF)"."""
        self.assertEqual(bytes([ESC, ord("L"), 0xFF, 0xFF]),
                         protocol.continuous_form())
        self.assertGreaterEqual(protocol.CONTINUOUS_LENGTH, 0x8000)

    def test_the_dot_tab_is_refused_outside_the_head(self):
        """0-83 is the manual's range for an 84-byte head. Masking a bad
        value with & 0xFF would turn a mistake into a left margin."""
        self.assertEqual(bytes([ESC, ord("B"), 0]), protocol.set_dot_tab(0))
        for bad in (-1, 84, 300):
            with self.subTest(tab=bad), \
                    self.assertRaises(protocol.ProtocolError):
                protocol.set_dot_tab(bad)

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
                               label_feed_dots=40)
        self.assertEqual(rows, self._decode(payload, 84))

    def test_a_mostly_blank_label_still_sends_every_row(self):
        """The case that failed: blank rows are most of a label, and they
        are exactly the ones compression replaced."""
        rows = [b"\x00" * 84] * 300 + [b"\xf0" * 84] * 75
        payload = protocol.job(rows, bytes_per_line=84, roll=1,
                               label_feed_dots=375)
        self.assertEqual(rows, self._decode(payload, 84))
        self.assertNotIn(protocol.ETB, payload)

    def test_the_compact_mode_is_the_one_that_needs_ETB(self):
        rows = [b"\x00" * 84] * 50
        payload = protocol.job(rows, bytes_per_line=84, compress=True,
                               label_feed_dots=50)
        with self.assertRaises(AssertionError):
            self._decode(payload, 84)

    def test_the_dot_tab_rides_in_the_preamble_and_still_decodes(self):
        """`ESC B 0` is now sent — see TestTheDotTabIsPrinterState for why —
        and the reason it was left out was that a firmware which does not
        take the command may swallow the byte after it. That risk is real
        and it is what `bare` answers; what this asserts is the other half,
        that a job carrying it is still a job a printer can walk."""
        payload = protocol.job([b"\x00" * 84], bytes_per_line=84, roll=1,
                               label_feed_dots=1)
        self.assertIn(bytes([protocol.ESC, ord("B"), 0]), payload)
        self.assertEqual([b"\x00" * 84], self._decode(payload, 84))


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

    def test_the_roll_byte_a_job_carries_is_the_ASCII_digit(self):
        """Asserted on a finished job as well as on the helper, because the
        helper is not what a printer reads."""
        for roll, wire in ((protocol.ROLL_LEFT, 0x31),
                           (protocol.ROLL_RIGHT, 0x32)):
            with self.subTest(roll=roll):
                job = protocol.job([self.line()], bytes_per_line=84,
                                   roll=roll, label_feed_dots=375)
                self.assertTrue(job.startswith(bytes([ESC, ord("q"), wire])),
                                job[:6])
                self.assertNotIn(bytes([ESC, ord("q"), roll]), job)

    def test_no_roll_byte_is_sent_when_there_is_no_roll_to_choose(self):
        job = protocol.job([self.line()], bytes_per_line=84, roll=None)
        self.assertNotIn(bytes([ESC, ord("q")]), job)

    def test_an_empty_label_is_refused(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.job([], bytes_per_line=84)


class TestTheLengthIsASearchBudget(unittest.TestCase):
    """`ESC L` is not the height of the raster, and sending it as one is
    what "the alignment is off on the labels" was.

    The 450 series technical reference, on this command: n1/n2 are the
    "number of dot lines from sense hole to sense hole"; the command
    "indicates the maximum distance the printer should travel while
    searching for the top-of-form hole or mark"; and — the sentence that
    matters — "print lines and lines fed both count towards this total".
    The printer "does not compare the label length variables sent by the
    host with the actual length of the currently loaded label stock", it
    only uses them "to maintain the logical position counter".

    So a job that declares 375 and then prints 375 lines has spent its
    entire allowance on its own artwork. The search stops at the instant
    the label ends; the sense hole is in the gap after that, so it is never
    reached, the counter is never re-synced, and every label starts a
    little further along the roll than the last. That is a drift down a
    roll rather than a one-off, which is exactly what a printed ruler held
    against the stock shows.
    """

    LABEL = 375           # a 2.25" x 1.25" cryo label, at 300 dpi
    LINE = b"\xf0" * 84

    def _length(self, payload: bytes) -> int:
        """The ESC L value out of a finished job, read off the wire.

        Read rather than recomputed: the point of every assertion here is
        the number the printer receives, and a helper that re-derived it
        would only ever agree with the code that wrote it.
        """
        marker = bytes([protocol.ESC, ord("L")])
        index = payload.index(marker)
        return (payload[index + 2] << 8) | payload[index + 3]

    def test_the_budget_is_larger_than_the_raster_it_has_to_pay_for(self):
        payload = protocol.job([self.LINE] * self.LABEL, bytes_per_line=84,
                               label_feed_dots=self.LABEL)
        printed = len(TestAJobAPrinterCanActuallyRead._decode(payload, 84))
        self.assertEqual(self.LABEL, printed)
        sent = self._length(payload)
        self.assertGreater(sent, printed)
        self.assertGreaterEqual(sent - printed, protocol.MIN_HEADROOM_DOTS)
        # Pinned as a number so a change to the headroom is a change
        # somebody made on purpose: 375 + 25% is 469 dot lines, 1.56", and
        # the gap between two die-cut labels is nothing like that wide.
        self.assertEqual(469, sent)

    def test_the_value_that_shipped_left_nothing_to_reach_the_hole_with(self):
        """The old line was `label_length_dots=rendered.feed_dots`, which
        on this stock is 375 — the exact number of dot lines the job goes
        on to print. Reproduced as the arithmetic rather than described,
        because "it was slightly short" and "it was short by the whole of
        it" are different bugs and only the second explains a drift that
        grows down a roll."""
        payload = protocol.job([self.LINE] * self.LABEL, bytes_per_line=84,
                               label_feed_dots=self.LABEL)
        printed = len(TestAJobAPrinterCanActuallyRead._decode(payload, 84))
        # The old recipe, rebuilt out of the job it was taken from: the
        # ESC L value WAS the height of the raster being sent.
        was = protocol.set_label_length(printed)
        self.assertEqual(printed, (was[2] << 8) | was[3])
        self.assertEqual(0, ((was[2] << 8) | was[3]) - printed,
                         "the whole budget went on the artwork")
        self.assertEqual(94, self._length(payload) - printed)

    def test_a_short_stock_gets_the_floor_and_a_long_one_the_fraction(self):
        """A quarter of a 0.5" library label is 37 dot lines, which is
        about one die-cut gap and no headroom at all; a quarter of a 4"
        shipping label is 300, which is plenty. Both directions are the
        same rule with a floor under it."""
        self.assertEqual(150 + protocol.MIN_HEADROOM_DOTS,
                         protocol.search_length(150))
        self.assertEqual(1200 + 300, protocol.search_length(1200))

    def test_it_scales_with_graphics_mode_exactly_as_the_line_count_does(self):
        """The 300x600 mode steps the paper twice per rendered row, so the
        raster doubles — and the budget is counted in those same steps. The
        two are one fact: a budget that did not double would be short by
        half a label in the mode this add-on prints in by default."""
        rows = [self.LINE] * self.LABEL
        text = self._length(protocol.job(rows, bytes_per_line=84,
                                         label_feed_dots=self.LABEL,
                                         quality="text"))
        payload = protocol.job(rows, bytes_per_line=84,
                               label_feed_dots=self.LABEL,
                               quality="graphics")
        graphics = self._length(payload)
        self.assertEqual(text * protocol.LINE_REPEAT["graphics"], graphics)
        printed = len(TestAJobAPrinterCanActuallyRead._decode(payload, 84))
        self.assertEqual(self.LABEL * 2, printed)
        self.assertGreater(graphics, printed)

    def test_continuous_stock_takes_the_negative_continuous_form_value(self):
        """There are no sense holes on continuous paper, so a search budget
        is meaningless and a positive one sends the printer hunting for
        something that is not there. The manual gives the mode its own
        mechanism, and this add-on shipped a continuous stock in the
        catalog without ever sending it."""
        payload = protocol.job([self.LINE] * 40, bytes_per_line=84,
                               continuous=True, label_feed_dots=self.LABEL)
        self.assertIn(protocol.continuous_form(), payload)
        self.assertEqual(protocol.CONTINUOUS_LENGTH, self._length(payload))
        self.assertGreaterEqual(self._length(payload), 0x8000)

    def test_a_die_cut_label_is_never_put_into_continuous_mode(self):
        """Including the one that used to do it by accident: the old clamp
        was 0xFFFF, so a mistyped feed measurement reached the printer as
        the continuous-form flag."""
        for feed in (1, 40, self.LABEL, 1200, 99_999):
            with self.subTest(feed=feed):
                payload = protocol.job([self.LINE], bytes_per_line=84,
                                       label_feed_dots=feed)
                self.assertLess(self._length(payload), 0x8000)

    def test_the_length_is_sent_once_per_copy_like_the_rest(self):
        payload = protocol.job([self.LINE], bytes_per_line=84, copies=3,
                               label_feed_dots=self.LABEL)
        self.assertEqual(3, payload.count(
            protocol.set_label_length(protocol.search_length(self.LABEL))))


class TestAMeasuredGapReplacesTheGuessedHeadroom(unittest.TestCase):
    """`ESC L` is defined hole to hole, and a measured gap is what makes it
    a measurement.

    The 25% headroom with a 60-dot floor is a fraction somebody chose,
    generous on the manual's own advice. It is also a candidate for the dead
    band a reporter measured at the LEADING edge of every label on this
    roll: 469 dot lines against a hole-to-hole pitch nearer 394 is 75 lines
    of over-feed, 6.4mm, on the order of the ~4mm observed. Nothing in a
    container can tell whether that is the printer's top of form or ours, so
    what is built is the instrument: type the gap you measured and the
    budget becomes label-plus-gap.

    Every assertion here is on the two bytes that reach the printer, in both
    line modes, because that is the only place the answer exists.
    """

    LABEL = 375           # a 2.25" x 1.25" cryo label, at 300 dpi
    LINE = b"\xf0" * 84

    def _length(self, payload: bytes) -> int:
        marker = bytes([protocol.ESC, ord("L")])
        index = payload.index(marker)
        return (payload[index + 2] << 8) | payload[index + 3]

    def _job(self, **kwargs) -> bytes:
        return protocol.job([self.LINE] * self.LABEL, bytes_per_line=84,
                            label_feed_dots=self.LABEL, **kwargs)

    def test_unset_is_byte_for_byte_the_job_that_shipped(self):
        """The rule this whole control is built under: a house that never
        opens it must get exactly the printer it had. Asserted as the whole
        payload rather than the length bytes, because "the same budget" and
        "the same job" are different claims and only the second is the
        promise."""
        self.assertEqual(self._job(), self._job(gap_dots=None))
        self.assertEqual(469, self._length(self._job(gap_dots=None)))

    def test_a_measured_gap_is_the_label_plus_the_gap_and_nothing_else(self):
        """1.5mm at 300 dpi is 18 dot lines, so the budget is 393 — not the
        469 the fraction gives, and not 469 plus anything. A measured
        quantity replaces the guess rather than adjusting it."""
        self.assertEqual(375 + 18, self._length(self._job(gap_dots=18)))
        self.assertEqual(375 + 60, self._length(self._job(gap_dots=60)))

    def test_zero_is_a_setting_and_not_the_absence_of_one(self):
        """The experiment is "wind it down to nothing and watch the leading
        edge", so zero has to reach the wire as zero. A falsy test here
        would hand it the 469 the unset case gets, the experiment would
        produce no change, and the wrong conclusion would be drawn from a
        control that was never applied — which is `${VAR:-default}` in
        Python."""
        self.assertEqual(self.LABEL, self._length(self._job(gap_dots=0)))
        self.assertNotEqual(self._length(self._job(gap_dots=0)),
                            self._length(self._job(gap_dots=None)))

    def test_zero_reproduces_the_shape_that_shipped_before_0_5_0(self):
        """Which is why it is reported rather than refused: it is a real
        state, it is the state the experiment needs, and it is also the bug
        that made every label drift. The budget equals the lines printed."""
        payload = self._job(gap_dots=0)
        printed = len(TestAJobAPrinterCanActuallyRead._decode(payload, 84))
        self.assertEqual(printed, self._length(payload))

    def test_it_scales_with_graphics_mode_exactly_as_the_lines_do(self):
        """The repeat and the length are one fact. A gap measured in 300ths
        of an inch has to double along with the raster, or the label comes
        out with a budget half as long as the paper it describes."""
        text = self._job(gap_dots=18, quality="text")
        graphics = self._job(gap_dots=18, quality="graphics")
        self.assertEqual(393, self._length(text))
        self.assertEqual(393 * protocol.LINE_REPEAT["graphics"],
                         self._length(graphics))
        self.assertEqual(786, self._length(graphics))

    def test_an_absurd_gap_still_cannot_reach_continuous_feed(self):
        """0x8000-0xFFFF is a MODE, not a length, and a number typed into a
        box may never put a printer into continuous feed. The clamp is at
        0x7FFF and a gap goes through it like every other length."""
        payload = self._job(gap_dots=90000)
        self.assertEqual(protocol.MAX_LENGTH, self._length(payload))
        self.assertLess(self._length(payload), 0x8000)

    def test_continuous_stock_ignores_a_gap_entirely(self):
        """There are no sense holes on continuous paper, so there is no
        hole-to-hole distance for a gap to be part of."""
        payload = self._job(gap_dots=18, continuous=True)
        self.assertEqual(protocol.CONTINUOUS_LENGTH, self._length(payload))

    def test_the_helper_answers_the_same_way_the_job_does(self):
        """Driven both ways round because `search_length` is what a reader
        checks and `job` is what a printer gets, and the one that matters is
        the second."""
        self.assertEqual(469, protocol.search_length(375))
        self.assertEqual(469, protocol.search_length(375, None))
        self.assertEqual(393, protocol.search_length(375, 18))
        self.assertEqual(375, protocol.search_length(375, 0))


class TestTheDotTabIsPrinterState(unittest.TestCase):
    """`ESC B 0` was left out as "a no-op by construction", and it is not.

    The manual: "both the dot tab variable and the bytes-per-line variable
    are held by the control electronics until they are changed by a new
    command sequence or are reset to default values by a power-on reset or
    a software reset command." The variable lives in the printer, not in
    our renderer — so omitting the command does not mean zero, it means
    whatever DYMO Connect, another driver or an earlier job last set. Each
    unit is a byte, eight dots, 1/37th of an inch of left margin, applied
    to every line of every label and visible from here as nothing at all.
    """

    LINE = b"\xf0" * 84

    def test_the_preamble_states_the_dot_tab_rather_than_inheriting_it(self):
        payload = protocol.job([self.LINE], bytes_per_line=84,
                               label_feed_dots=375)
        self.assertIn(bytes([protocol.ESC, ord("B"), 0]), payload)

    def test_it_sits_with_the_bytes_per_line_it_has_to_agree_with(self):
        """The manual pairs them — "if the host computer modifies the
        starting byte, the number of bytes per line must be adjusted
        downward by a corresponding amount" — so 0 and 84 are one statement
        about the head, and they are sent together rather than a preamble
        apart."""
        payload = protocol.job([self.LINE], bytes_per_line=84,
                               label_feed_dots=375)
        tab = payload.index(bytes([protocol.ESC, ord("B"), 0]))
        per_line = payload.index(protocol.set_bytes_per_line(84))
        self.assertEqual(tab + 3, per_line)

    def test_it_is_re_sent_for_every_copy(self):
        """Same reasoning as the roll byte and the density: three bytes to
        start each label from a known state rather than trusting that
        nothing came between them."""
        payload = protocol.job([self.LINE], bytes_per_line=84, copies=4,
                               label_feed_dots=375)
        self.assertEqual(4, payload.count(bytes([protocol.ESC, ord("B"), 0])))

    def test_bare_leaves_it_alone(self):
        """`bare` exists for a firmware that will not take a command in the
        preamble, and that has to include this one — otherwise the mode
        somebody falls back to is not the minimum it claims to be."""
        payload = protocol.job([self.LINE], bytes_per_line=84,
                               label_feed_dots=375, dot_tab=False)
        self.assertNotIn(bytes([protocol.ESC, ord("B")]), payload)


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
                               label_feed_dots=1,
                               density="dark", quality="graphics")
        self.assertTrue(payload.startswith(b"\x1bg\x1bi"), payload[:8])
        self.assertLess(payload.index(b"\x1bi"),
                        payload.index(bytes([ESC, ord("L")])))

    def test_the_roll_still_comes_first(self):
        payload = protocol.job([self.LINE], bytes_per_line=84, roll=1,
                               label_feed_dots=1,
                               density="dark", quality="graphics")
        self.assertTrue(payload.startswith(
            protocol.select_roll(1) + b"\x1bg\x1bi"))

    def test_both_are_re_sent_for_every_copy(self):
        """Same reasoning as the roll byte: four bytes to start each label
        from a known state rather than inheriting the last job's."""
        payload = protocol.job([self.LINE], bytes_per_line=84, copies=3,
                               label_feed_dots=1,
                               density="dark", quality="graphics")
        self.assertEqual(3, payload.count(b"\x1bg"))
        self.assertEqual(3, payload.count(b"\x1bi"))

    def test_graphics_mode_sends_every_line_twice(self):
        """The printer steps the paper 600 times per inch in this mode and
        the renderer draws 300 — so a label whose rows went once would come
        out half its length, with everything on it squashed."""
        rows = [bytes([i]) * 84 for i in range(10)]
        payload = protocol.job(rows, bytes_per_line=84,
                               label_feed_dots=10,
                               density="dark", quality="graphics")
        decoded = TestAJobAPrinterCanActuallyRead._decode(payload, 84)
        self.assertEqual([row for row in rows for _ in (0, 1)], decoded)

    def test_graphics_mode_doubles_the_label_length(self):
        """`ESC L` is counted in the same 600-per-inch steps, so a length
        left at its 300 dpi value would tell the printer the label is half
        as long as the raster it is about to receive."""
        payload = protocol.job([self.LINE] * 375, bytes_per_line=84,
                               label_feed_dots=375,
                               density="dark", quality="graphics")
        budget = protocol.search_length(375)
        self.assertIn(protocol.set_label_length(budget * 2), payload)
        self.assertNotIn(protocol.set_label_length(budget), payload)

    def test_text_mode_sends_each_line_once_and_the_unscaled_length(self):
        rows = [bytes([i]) * 84 for i in range(10)]
        payload = protocol.job(rows, bytes_per_line=84,
                               label_feed_dots=10,
                               density="normal", quality="text")
        self.assertEqual(rows,
                         TestAJobAPrinterCanActuallyRead._decode(payload, 84))
        self.assertIn(protocol.set_label_length(protocol.search_length(10)),
                      payload)
        self.assertIn(b"\x1bh", payload)

    def test_bare_sends_nothing_but_the_geometry(self):
        """`bare` is the escape route from a firmware that will not take one
        of these commands, so it has to be the minimum: roll, length, bytes
        per line, the rows, the feed. Written out as the literal preamble
        rather than as a list of things it must not contain, because a
        command added later would pass the second and fail the first — and
        the whole value of this mode is knowing exactly what it sends."""
        rows = [bytes([i]) * 84 for i in range(20)]
        bare = protocol.job(rows, bytes_per_line=84, roll=1, copies=1,
                            label_feed_dots=20,
                            density=None, quality=None, dot_tab=False)
        self.assertTrue(bare.startswith(
            protocol.select_roll(1)
            + protocol.set_label_length(protocol.search_length(20))
            + protocol.set_bytes_per_line(84)
            + bytes([protocol.SYN])), bare[:16])
        for command in (b"\x1bc", b"\x1bd", b"\x1be", b"\x1bg",
                        b"\x1bh", b"\x1bi", b"\x1bB"):
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
