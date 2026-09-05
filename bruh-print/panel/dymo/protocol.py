#!/usr/bin/env python3
"""The bytes a DYMO LabelWriter actually wants.

A LabelWriter is not a page printer with a driver in front of it. It takes a
short escape-command preamble and then one raster line at a time, each line
being `bytes_per_line` bytes of 1-bit pixels laid across the print head, and a
form feed at the end to cut the label loose. That is the whole protocol, and
it is why this add-on speaks USB directly instead of standing CUPS up inside
a container: the entire "driver" is this file.

Command set (LabelWriter 400/450 series technical reference). Only the
commands whose meaning is unambiguous are here, deliberately:

    ESC B n         Set dot tab — how many BYTES of blank the printer puts
                    at the start of every line before our data begins.
                    Always 0 here, and sent rather than assumed: the manual
                    is explicit that the dot tab is state the printer holds
                    "until changed by a new command sequence or reset by a
                    power-on reset", so not sending it does not mean zero,
                    it means whatever DYMO Connect or another driver last
                    set. A printer shared with DYMO's own software is the
                    ordinary case, and an inherited dot tab of 4 is every
                    label shifted 32 dots to the right.
    ESC D n         Set bytes per line. Every SYN line after this must be
                    exactly n bytes, padding included. The manual pairs it
                    with the dot tab — a line that starts n bytes in has to
                    send n fewer — which is why the two go together, and
                    why 0 and 84 are one statement about the head rather
                    than two commands.
    ESC L n1 n2     Set label length, big-endian, in dot lines FROM SENSE
                    HOLE TO SENSE HOLE. Not the height of the raster, and
                    not advisory: it is "the maximum distance the printer
                    should travel while searching for the top-of-form hole
                    or mark", and "print lines and lines fed both count
                    towards this total". So sending the artwork's own
                    height spends the whole allowance on the artwork and
                    ends the search exactly where the label does — before
                    the hole, which is in the gap after it. See
                    `search_length`. The top half of the range is a
                    different mode entirely: see `continuous_form`.
    ESC q n         Roll select, and its parameter is an ASCII DIGIT — not
                    the number it stands for. The reference, verbatim:

                        <esc> q n Select Roll (Twin Turbo printer Only)
                        1B 71 ? n specifies the roll to print on, where:
                         30 (ASCII '0') = Automatic selection
                         31 (ASCII '1') = Left roll
                         32 (ASCII '2') = Right roll

                    It spells ASCII out for this one command where every
                    other parameter it documents is plainly binary (`ESC D
                    n`, "1 <= n <= 84"; `ESC B n`, "valid values are 0-83"),
                    which is the author saying so. This add-on shipped
                    `0x01`/`0x02` — written from memory, the third byte in
                    this file to be, after the `ETB` compression that
                    shipped a printer which could not print and the `ESC L`
                    that was sent as the raster's height. If a firmware does
                    not recognise `0x01` as a roll selector then roll select
                    is a no-op, every label goes to whichever bay was last
                    used, and on a Twin Turbo with two different stocks in
                    it that is a label printed on the wrong-size liner.

                    The Twin Turbo's whole reason for existing, and a no-op
                    the single-roll models ignore rather than fault on. It
                    is still gated on the model's own capability flag (see
                    printers.py), because sending it to a printer with one
                    roll and calling that "printing on the left" would be a
                    lie the panel repeats.
    ESC E           Form feed. Advances to the next label and is what makes
                    the printed one tearable.
    ESC G           Short form feed. Advances just past the print head, so
                    consecutive labels do not each waste one. Used between
                    copies; the last copy always gets the long feed.
    ESC A           Status request. The printer answers with a status block
                    (see `Status`).
    ESC f 1 n       Skip "n" lines. Documented, unambiguous, and deliberately
                    NOT sent: it is the printer's own feed-direction print
                    position, and it only moves paper forward. The
                    misregistration this add-on was actually shown is a
                    printer starting LATE, whose correction is a negative
                    skip. See `render.image.offset_raster` for the whole of
                    that reasoning, and for why the across axis does not use
                    `ESC B` for the same job either. Named here so nobody has
                    to rediscover it in the manual and wonder whether it was
                    missed.

    SYN (0x16)      One raster line follows, `bytes_per_line` bytes of it.
    ETB (0x17)      Repeat the previous line. Every label this add-on prints
                    has long runs of identical blank lines, and a run of
                    ETBs is one byte each where SYN is 85.

    ESC c/d/e/g    Print density: light, medium, normal, dark. `normal` is
                    what the printer does with no command at all.
    ESC h           Text Speed Mode: 300x300 dpi, and the printer's default.
    ESC i           Barcode and Graphics Mode: 300x600 dpi, slower, and the
                    reference calls out "greater positional and sizing
                    accuracy". The head dwells twice as long over each inch
                    of paper, which is also why it prints darker. In this
                    mode the printer steps the paper 600 times per inch, so
                    a 300 dpi raster has to send EACH LINE TWICE, and the
                    `ESC L` length is in those same steps and doubles with
                    it — otherwise the label comes out half its length.
                    (cups-filters duplicates nothing: CUPS rasterises at
                    whichever vertical resolution the PPD's `300x600dpi`
                    option asked for, so every line it has is already a
                    600 dpi line. We render at 300 and repeat.)

Density and quality ARE sent, in the standard and compact modes, because
labels coming out light was the complaint and the printer's own default is
the fast mode at normal density. The encodings above are the 400/450
generation's — the same bytes cups-filters' `rastertolabel.c` has sent, in
this order (density, quality, `ESC L`, `ESC D`, the lines, `ESC E`), for
twenty years. What has not changed is the reason for caution: the 550
generation's command set differs (and it refuses third-party stock anyway),
and a byte a firmware reads as something else is a wedged printer rather
than a lighter label. That is what the **bare** print mode is for — it sends
neither, leaving the printer at its own defaults — and it is the escape
route from a guess this add-on cannot test from inside a container.
"""
from __future__ import annotations

from dataclasses import dataclass

ESC = 0x1B
SYN = 0x16
ETB = 0x17

# The panel's names for the two bays. These are this add-on's own numbering
# and they are NOT what goes on the wire — see `ROLL_WIRE`. Keeping them is
# deliberate: `1` and `2` are what the settings file, the history rows and
# every caller above this module already say, and translating once, here, is
# how a corrected wire byte reaches a printer without anything else knowing
# it changed.
ROLL_LEFT = 1
ROLL_RIGHT = 2

ROLL_NAMES = {ROLL_LEFT: "left", ROLL_RIGHT: "right"}
ROLL_CODES = {"left": ROLL_LEFT, "right": ROLL_RIGHT}

# What `ESC q` actually takes: ASCII '1' and ASCII '2'. See the command
# table at the top of this file for the manual's own wording and for what
# sending 0x01 instead most likely did.
ROLL_WIRE = {ROLL_LEFT: 0x31, ROLL_RIGHT: 0x32}

# ASCII '0' — automatic selection, the third value the manual documents and
# the one nothing here uses, on purpose: "in Automatic Selection mode, the
# printer assumes that both rolls have the same media, and it will toggle
# back and forth as rolls become empty." This add-on's whole design is that
# the panel knows which stock is in which bay, so a printer choosing a bay
# for itself would print a 2.25" raster onto a 0.56" roll — the one thing
# the stock check exists to prevent. Named so nobody has to rediscover it,
# and unwired for the reason on this line.
ROLL_WIRE_AUTO = 0x30


class ProtocolError(ValueError):
    """A job that cannot be turned into bytes at all."""


def _esc(letter: str, *args: int) -> bytes:
    return bytes([ESC, ord(letter), *args])


def set_dot_tab(tabs: int = 0) -> bytes:
    """Where on the head a line starts, in bytes of 8 dots.

    Zero is the only value this add-on sends — the renderer draws the whole
    label and the margin is part of the artwork — but sending it is not the
    same as leaving it out. The dot tab is a variable inside the printer,
    kept until something changes it or the printer is power-cycled, so a
    preamble that omits it inherits whatever the last driver to talk to that
    printer set. That is the horizontal half of "the alignment is off".

    0-83 is the manual's own range for an 84-byte head. A value outside it
    is refused rather than masked, because `n & 0xFF` turns a mistake into a
    left margin nobody asked for.
    """
    tabs = int(tabs)
    if not 0 <= tabs <= 83:
        raise ProtocolError(f"dot tab must be 0..83 bytes, got {tabs}")
    return _esc("B", tabs)


def set_bytes_per_line(count: int) -> bytes:
    if not 1 <= count <= 255:
        raise ProtocolError(f"bytes per line must be 1..255, got {count}")
    return _esc("D", count)


# The top half of ESC L's two-byte range is not a length: "any negative
# value (0x8000 - 0xFFFF) will place the printer in continuous feed mode",
# which changes what a form feed does. So a positive length clamps at
# 0x7FFF — 32,767 dot lines, or nine feet of label — and NOT at 0xFFFF,
# which is what the old clamp did: an absurd feed measurement typed into a
# stock would have put the printer into a mode nobody asked for.
MAX_LENGTH = 0x7FFF

# The continuous-form flag itself: -1 as a signed 16-bit integer. Any value
# in 0x8000-0xFFFF selects the mode; -1 is the one that cannot be read back
# as a plausible length by anything downstream.
CONTINUOUS_LENGTH = 0xFFFF


def set_label_length(dots: int) -> bytes:
    """The top-of-form search budget, in dot lines, clamped rather than
    refused.

    Clamped because this number is a maximum the printer searches within,
    not a measurement it prints to: on die-cut stock the sense hole re-syncs
    the counter long before the budget runs out, so an over-long value costs
    nothing and refusing would print nothing.
    """
    dots = max(0, min(MAX_LENGTH, int(dots)))
    return _esc("L", (dots >> 8) & 0xFF, dots & 0xFF)


def continuous_form() -> bytes:
    """Put the printer into continuous-feed mode.

    There are no sense holes on continuous stock, so a search budget is
    meaningless there and a positive one is actively wrong: the printer
    would hunt for a hole that does not exist. The manual gives this its own
    mechanism — "when the label length variable is set to any negative 2
    byte integer value (0x8000-0xFFFF), it allows for the use of continuous
    form paper. In the continuous form mode, the Form Feed command (<esc> E)
    is changed to feed enough dot lines to allow for the last line of print
    data to extend past the printer tear-bar" — which is exactly what a
    continuous label wants at the end of a job, and which this add-on had
    never sent while shipping a continuous stock in the catalog.
    """
    return _esc("L", (CONTINUOUS_LENGTH >> 8) & 0xFF, CONTINUOUS_LENGTH & 0xFF)


# How much further than the label the top-of-form search may run. The gap
# between two die-cut labels is not something the catalog knows — it varies
# by stock and nothing here can measure it — so the headroom is a fraction
# of the label with a floor under it: a quarter of a label is more than any
# DYMO die-cut gap, and the floor is what a short stock needs when a quarter
# of it is not (a 1.75" spine label is 525 dots; a 0.5" one is 150).
#
# Generous is the safe direction, and that is the manual's own advice: "for
# normal labels with top-of-form marks, the actual distance fed is adjusted
# once the top-of-form mark is detected. As a result this command is usually
# set to a value slightly longer than the true label length." The printer's
# own power-up value is 3058 — 10.2" — for the same reason.
LENGTH_HEADROOM = 0.25
MIN_HEADROOM_DOTS = 60  # 0.2" at 300 dpi


def search_length(feed_dots: int, gap_dots: int | None = None) -> int:
    """The ESC L value for a die-cut label `feed_dots` lines long.

    `feed_dots` is the label; the answer is the label plus room to reach the
    hole in the gap after it. The two must not be the same number, and for
    the life of this add-on they were: `job` was handed the rendered
    raster's own height, which for a 2.25" x 1.25" label is exactly 375
    lines of 300ths — so the printer spent its entire search allowance on
    the 375 lines it was printing and stopped looking at the instant the
    artwork ended. The sense hole is further on than that, always, so the
    hole was never found, the logical counter was never re-synced, and each
    label started fractionally further along the roll than the one before.
    That is a systematic drift down a roll rather than a one-off, which is
    what makes it visible on a printed ruler.

    `gap_dots` is the die-cut gap, when somebody has measured theirs, and it
    is the quantity this command is actually defined in: hole to hole is the
    label plus the gap after it, so a measured gap makes the answer a
    measurement rather than a fraction. `None` is "nobody has measured it"
    and keeps the headroom below — which is not a fallback that happens to
    agree, it is the shipped behaviour untouched, so a house that never
    opens this control gets byte-for-byte the job it always got.

    **Zero is a real value and must not be read as unset.** "Wind it down to
    nothing and watch what the leading edge does" is the whole experiment
    this argument exists for; `${VAR:-default}` cannot express the
    difference between an empty answer and a zero one, and this is the same
    trap in a different language. Hence `is None` and never a falsy test.

    A gap of zero makes the budget exactly the label, which is precisely the
    shape that shipped before 0.5.0 and drifted down the roll. It is allowed
    anyway, and reported rather than refused: the caller that sets it is
    running an experiment, and a control that refuses the one setting the
    experiment needs is not an instrument. The report lives with the printed
    label, in `server._send`, where a person can read it.
    """
    feed = max(1, int(feed_dots))
    if gap_dots is None:
        return feed + max(MIN_HEADROOM_DOTS, round(feed * LENGTH_HEADROOM))
    return feed + max(0, int(gap_dots))


def select_roll(roll: int) -> bytes:
    """`ROLL_LEFT` or `ROLL_RIGHT` — translated to the ASCII digit the
    printer wants on its way out.

    Refused rather than clamped: silently taking a bad roll to be the left
    one would print the label on the left roll and report success about the
    right.
    """
    if roll not in ROLL_WIRE:
        raise ProtocolError(
            f"roll must be {ROLL_LEFT} (left) or {ROLL_RIGHT} (right), "
            f"got {roll!r}")
    return _esc("q", ROLL_WIRE[roll])


# Density and quality are the two commands that change how DARK a label
# comes out, and in practice they are a pair: the slow mode is darker than
# the fast one at the same density, because the head spends twice as long
# over every line.
DENSITIES = {
    "light": _esc("c"),
    "medium": _esc("d"),
    "normal": _esc("e"),
    "dark": _esc("g"),
}
QUALITIES = {
    # 300x300 dpi, fast, the printer's own default.
    "text": _esc("h"),
    # 300x600 dpi. Slower, darker, and every raster line has to be sent
    # twice — see `raster`'s `line_repeat` and `job`'s doubled length.
    "graphics": _esc("i"),
}

# How many times one 300 dpi line is sent in each mode. Named rather than a
# bare 2 in `job`, because the repeated lines and the doubled label length
# are the same fact and must not drift apart.
LINE_REPEAT = {"text": 1, "graphics": 2}


def set_density(level: str) -> bytes:
    """One of light/medium/normal/dark, refused rather than guessed.

    A typo falling through to the printer's default would be a darkness
    setting that silently did nothing — which is exactly the complaint this
    command exists to answer.
    """
    try:
        return DENSITIES[str(level)]
    except KeyError:
        raise ProtocolError(
            f"density must be one of {', '.join(DENSITIES)}, "
            f"got {level!r}") from None


def set_quality(mode: str) -> bytes:
    """`text` (fast, 300x300) or `graphics` (slow, 300x600, darker)."""
    try:
        return QUALITIES[str(mode)]
    except KeyError:
        raise ProtocolError(
            f"quality must be one of {', '.join(QUALITIES)}, "
            f"got {mode!r}") from None


def form_feed() -> bytes:
    return _esc("E")


def short_form_feed() -> bytes:
    return _esc("G")


def status_request() -> bytes:
    return _esc("A")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
#
# The 450 series answers ESC A with a 32-byte block. Only three bits of it
# are worth reporting to a person, and the block's length varies by
# generation, so every field is read defensively: a short or absent block
# means "the printer did not say", never "everything is fine". That
# distinction is the whole value of asking — a panel that renders silence as
# ready is a panel that says "ready" about an open lid.
# Bit 0x02 is top-of-form, and it is deliberately not read: it says where
# the paper is, not whether anything is wrong, and a status summary that
# recites it would put a word in front of a person that means nothing to
# them. Only the three that change what they should do are parsed.
_BUSY_BIT = 0x01
_OUT_OF_PAPER_BIT = 0x04
_LID_OPEN_BIT = 0x08


@dataclass(frozen=True)
class Status:
    """What the printer said about itself, and whether it said anything."""

    answered: bool
    # There was nothing to ask WITH — no bulk IN endpoint on the interface
    # we print through — as opposed to a question that went out and got no
    # reply. A different sentence, because only the second is about the
    # printer; the first sends somebody to go and check hardware that is
    # fine.
    unreadable: bool = False
    busy: bool = False
    out_of_labels: bool = False
    lid_open: bool = False
    raw: bytes = b""

    @property
    def ok(self) -> bool:
        """True only when the printer answered AND reported nothing wrong."""
        return self.answered and not (self.out_of_labels or self.lid_open)

    @property
    def summary(self) -> str:
        """One sentence, and the two silences are not the same sentence.

        "No status reported" was both of them, which is why it was useless:
        a person reads it and goes to check the printer, when half the time
        the printer is fine and the add-on simply has no channel to ask on.
        """
        if self.unreadable:
            return ("no read-back channel on this printer, so it cannot be "
                    "asked — printing is unaffected")
        if not self.answered:
            return "asked, but the printer did not answer"
        problems = []
        if self.lid_open:
            problems.append("lid open")
        if self.out_of_labels:
            problems.append("out of labels")
        if self.busy:
            problems.append("busy")
        return ", ".join(problems) if problems else "ready"


def parse_status(block: bytes | None) -> Status:
    if not block:
        return Status(answered=False)
    first = block[0]
    return Status(
        answered=True,
        busy=bool(first & _BUSY_BIT),
        out_of_labels=bool(first & _OUT_OF_PAPER_BIT),
        lid_open=bool(first & _LID_OPEN_BIT),
        raw=bytes(block),
    )


# ---------------------------------------------------------------------------
# Raster
# ---------------------------------------------------------------------------
def pack_line(bits: bytes, bytes_per_line: int) -> bytes:
    """One line's pixels, padded on the right or truncated to the head.

    **Padding on the right is where the printing starts, and for one release
    that was a decision nothing knew it was making.** A short line lands
    flush against head dot 0 and the rest of the head is blank — invisible
    and correct for a 2.25" stock, whose 672-dot raster is the whole head,
    and half a label for a 0.56" wrap whose 168 dots are a quarter of it and
    whose paper does not sit at the dot-0 end. Where the paper *does* sit is
    `stores.stock.media_across_mm`, and `render.image.place_on_head` is what
    puts the sheet there, before anything reaches this function.

    Truncation used to be justified here by "the renderer is handed the
    printable dot width and never draws past it". That was true of the
    renderer and it was never the whole guarantee: it stopped being true the
    moment a sheet could be laid somewhere other than dot 0, because a
    lateral position is precisely a way to push ink past the last dot. So
    the guarantee now belongs to `place_on_head`, which crops at the head
    and REPORTS the ink it lost, in millimetres, naming the edge. What is
    left here is a backstop against a bug upstream — a line arriving too
    long is not a wide label — and it is deliberately not a policy: the
    place a person is told about lost ink is the note beside their label,
    not a raster row nobody can see.
    """
    if len(bits) >= bytes_per_line:
        return bytes(bits[:bytes_per_line])
    return bytes(bits) + b"\x00" * (bytes_per_line - len(bits))


def raster(lines: list[bytes], bytes_per_line: int, *,
           compress: bool = False, line_repeat: int = 1) -> bytes:
    """The raster body: a SYN line each, or ETB for a repeat when asked.

    `line_repeat` is 2 in the printer's graphics mode and nothing else: the
    paper steps 600 times per inch there while the renderer draws 300, so
    each row has to be sent twice or the label comes out half its length.
    It repeats the PACKED line rather than the source row, so padding and
    truncation still happen exactly once per row.

    **Compression is off by default, and that is the whole of a bug that
    shipped.** `ETB` as "repeat the previous line" is the one opcode in this
    file written from memory rather than from something unambiguous, and a
    label is mostly blank — so a 375-line label came out as 474 bytes, of
    which about 370 were ETB. A printer that does not read 0x17 that way
    gets a valid preamble followed by 370 bytes of nothing it recognises,
    and prints nothing at all: the job is accepted, the write succeeds, the
    panel says "printed", and no label appears. Which is exactly what
    happened on the first real printer this add-on ever met.

    Uncompressed is what cups-filters' DYMO path has sent for twenty years:
    one SYN and one full line, every line. It costs 31,886 bytes for that
    same label, which over USB 2.0 is under three milliseconds. That is not
    a saving worth a guess.
    """
    out = bytearray()
    previous: bytes | None = None
    repeat = max(1, int(line_repeat))
    for line in lines:
        packed = pack_line(line, bytes_per_line)
        for _ in range(repeat):
            if compress and packed == previous:
                out.append(ETB)
                continue
            out.append(SYN)
            out.extend(packed)
            previous = packed
    return bytes(out)


def job(lines: list[bytes], *, bytes_per_line: int, roll: int | None = None,
        copies: int = 1, label_feed_dots: int | None = None,
        gap_dots: int | None = None,
        continuous: bool = False, compress: bool = False,
        dot_tab: bool = True, density: str | None = None,
        quality: str | None = None) -> bytes:
    """A complete print job: preamble, raster, feed — repeated per copy.

    The preamble is re-sent for every copy rather than once for the job. It
    costs seven bytes and it buys the case that actually happens: a printer
    that was power-cycled, or a job interleaved behind another process's,
    starts each label from a known state instead of inheriting whatever the
    last one left set.

    Every copy but the last gets the SHORT feed. A long feed between copies
    advances a whole label past the head, so a run of ten came out as ten
    printed and ten blank — which reads as the printer wasting half the roll,
    because it is.

    `label_feed_dots` is the LABEL — the die-cut length of the stock, which
    for everything but continuous paper is also the height of the raster —
    and never the ESC L value itself. `search_length` turns one into the
    other, because the two are different quantities and passing the first
    where the second belonged is what made every label drift down the roll.
    `continuous=True` is the separate mode for stock with no die cut at all:
    the length field becomes the continuous-form flag and this argument is
    not read.

    `gap_dots` is the die-cut gap on this roll, when somebody has measured
    it, and `None` — the default and what every caller sends until somebody
    does — keeps the headroom `search_length` has always applied. It rides
    beside `label_feed_dots` because the two are one measurement of the same
    paper, hole to hole.

    `dot_tab` sends `ESC B 0` and is on by default, because the dot tab is
    the printer's state and not ours: a job that does not set it starts
    wherever the last driver left it. `bare` turns it off along with
    everything else, which is what `bare` is for.

    `density` and `quality` are both optional and both `None` in the `bare`
    print mode, which is the one arrangement that leaves the printer at its
    own defaults. `quality="graphics"` is the slow, darker 300x600 mode, and
    it changes the body as well as the preamble: every line goes twice and
    the label length doubles with it, because both are counted in the
    printer's 600-per-inch steps.
    """
    if not lines:
        raise ProtocolError("nothing to print: the rendered label has no rows")
    copies = max(1, int(copies))
    # Validate before rendering the body: a typo'd density must not cost a
    # megabyte of raster before it is refused.
    density_bytes = set_density(density) if density is not None else b""
    quality_bytes = set_quality(quality) if quality is not None else b""
    repeat = LINE_REPEAT.get(quality or "text", 1)
    body = raster(lines, bytes_per_line, compress=compress,
                  line_repeat=repeat)
    if continuous:
        length_bytes = continuous_form()
    else:
        feed = label_feed_dots if label_feed_dots is not None else len(lines)
        # The headroom is worked out in 300 dpi lines and then scaled with
        # the raster, because the label and the budget spent on it are one
        # fact counted in whatever steps the printer is taking — the same
        # reason `LINE_REPEAT` is named rather than written as a bare 2.
        length_bytes = set_label_length(
            search_length(feed, gap_dots) * repeat)

    out = bytearray()
    for index in range(copies):
        if roll is not None:
            out.extend(select_roll(roll))
        # Density then quality then the geometry, which is the order the
        # long-standing cups-filters DYMO path sends them in.
        out.extend(density_bytes)
        out.extend(quality_bytes)
        # Length before the pair that describes a line, which is the order
        # the long-standing cups-filters DYMO path uses for the two commands
        # it sends. Almost certainly irrelevant, and matching a shape that is
        # known to print costs nothing.
        out.extend(length_bytes)
        # `ESC B 0` was left out on the grounds that it is "a no-op by
        # construction — the renderer already knows where the left edge is".
        # That reasoning is wrong, and wrong in the way that only shows up on
        # somebody else's printer: the dot tab is a variable held INSIDE the
        # printer "until changed by a new command sequence or reset by a
        # power-on reset", so it is zero only if nothing has ever set it.
        # DYMO Connect, another driver or an earlier job can each leave it
        # set, and every label we print then starts that many bytes — eight
        # dots each — to the right, silently, with nothing on this side able
        # to see it. A printer shared with DYMO's own software is the
        # ordinary case, not an exotic one.
        #
        # It sits beside the bytes-per-line because the manual pairs them: a
        # line that starts n bytes in must send n fewer, so 0 with 84 is one
        # statement about the whole head rather than two commands. `bare`
        # drops it with everything else, which is the escape route from a
        # firmware that will not take the command at all.
        if dot_tab:
            out.extend(set_dot_tab(0))
        out.extend(set_bytes_per_line(bytes_per_line))
        out.extend(body)
        out.extend(short_form_feed() if index < copies - 1 else form_feed())
    return bytes(out)
