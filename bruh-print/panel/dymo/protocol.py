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

    ESC B n         Set dot tab — how many bytes of blank to skip at the
                    start of every line. Always 0 here; the renderer already
                    knows where the label's left edge is and a second
                    opinion about the margin is a second answer.
    ESC D n         Set bytes per line. Every SYN line after this must be
                    exactly n bytes, padding included.
    ESC L n1 n2     Set label length in dots, big-endian. Advisory — the
                    printer feeds to the next die-cut gap regardless — but
                    it is what stops a long job being cut short on
                    continuous stock.
    ESC q n         Roll select: 1 = left, 2 = right. The Twin Turbo's whole
                    reason for existing, and a no-op the single-roll models
                    ignore rather than fault on. It is still gated on the
                    model's own capability flag (see printers.py), because
                    sending it to a printer with one roll and calling that
                    "printing on the left" would be a lie the panel repeats.
    ESC E           Form feed. Advances to the next label and is what makes
                    the printed one tearable.
    ESC G           Short form feed. Advances just past the print head, so
                    consecutive labels do not each waste one. Used between
                    copies; the last copy always gets the long feed.
    ESC A           Status request. The printer answers with a status block
                    (see `Status`).

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

ROLL_LEFT = 1
ROLL_RIGHT = 2

ROLL_NAMES = {ROLL_LEFT: "left", ROLL_RIGHT: "right"}
ROLL_CODES = {"left": ROLL_LEFT, "right": ROLL_RIGHT}


class ProtocolError(ValueError):
    """A job that cannot be turned into bytes at all."""


def _esc(letter: str, *args: int) -> bytes:
    return bytes([ESC, ord(letter), *args])


def set_dot_tab(tabs: int = 0) -> bytes:
    return _esc("B", tabs & 0xFF)


def set_bytes_per_line(count: int) -> bytes:
    if not 1 <= count <= 255:
        raise ProtocolError(f"bytes per line must be 1..255, got {count}")
    return _esc("D", count)


def set_label_length(dots: int) -> bytes:
    """Label length in dots, clamped rather than refused.

    A length that overflows two bytes is a label over 18 feet long, which is
    not a job anybody typed on purpose — but the length is advisory and the
    printer feeds to the die-cut gap anyway, so clamping prints the label and
    refusing prints nothing.
    """
    dots = max(0, min(0xFFFF, int(dots)))
    return _esc("L", (dots >> 8) & 0xFF, dots & 0xFF)


def select_roll(roll: int) -> bytes:
    if roll not in ROLL_NAMES:
        raise ProtocolError(
            f"roll must be {ROLL_LEFT} (left) or {ROLL_RIGHT} (right), "
            f"got {roll!r}")
    return _esc("q", roll)


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
    """One line's pixels, padded or truncated to the head's width.

    Truncation is silent on purpose and the renderer is what stops it
    mattering: it is handed the printable dot width from the model table and
    never draws past it, so a line arriving too long here means a bug
    upstream, not a wide label. Padding is the ordinary case — a label
    narrower than the head is most labels.
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
        copies: int = 1, label_length_dots: int | None = None,
        compress: bool = False, dot_tab: bool = False,
        density: str | None = None, quality: str | None = None) -> bytes:
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

    `density` and `quality` are both optional and both `None` in the `bare`
    print mode, which is the one arrangement that leaves the printer at its
    own defaults. `quality="graphics"` is the slow, darker 300x600 mode, and
    it changes the body as well as the preamble: every line goes twice and
    the label length doubles, because both are counted in the printer's
    600-per-inch steps.
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
    length = (label_length_dots if label_length_dots is not None
              else len(lines)) * repeat

    out = bytearray()
    for index in range(copies):
        if roll is not None:
            out.extend(select_roll(roll))
        # Density then quality then the geometry, which is the order the
        # long-standing cups-filters DYMO path sends them in.
        out.extend(density_bytes)
        out.extend(quality_bytes)
        # `ESC B 0` is a no-op by construction — the renderer already knows
        # where the left edge is, so the dot tab is always zero — and a
        # no-op is pure risk in a preamble: a firmware that does not take
        # this command may swallow the byte after it and desync everything
        # that follows. Off unless somebody turns it on.
        if dot_tab:
            out.extend(set_dot_tab(0))
        # Length before bytes-per-line, which is the order the long-standing
        # cups-filters DYMO path uses. Almost certainly irrelevant, and
        # matching a shape that is known to print costs nothing.
        out.extend(set_label_length(length))
        out.extend(set_bytes_per_line(bytes_per_line))
        out.extend(body)
        out.extend(short_form_feed() if index < copies - 1 else form_feed())
    return bytes(out)
