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

What is NOT sent, and why: the density and print-mode opcodes. Their
encodings differ across the 400/450/550 generations, thermal label stock
prints correctly at the printer's own default, and a byte sent to the wrong
generation of firmware is a wedged printer rather than a lighter label. A
guess that is only sometimes right is worse here than not asking.
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
           compress: bool = False) -> bytes:
    """The raster body: a SYN line each, or ETB for a repeat when asked.

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
    for line in lines:
        packed = pack_line(line, bytes_per_line)
        if compress and packed == previous:
            out.append(ETB)
            continue
        out.append(SYN)
        out.extend(packed)
        previous = packed
    return bytes(out)


def job(lines: list[bytes], *, bytes_per_line: int, roll: int | None = None,
        copies: int = 1, label_length_dots: int | None = None,
        compress: bool = False, dot_tab: bool = False) -> bytes:
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
    """
    if not lines:
        raise ProtocolError("nothing to print: the rendered label has no rows")
    copies = max(1, int(copies))
    body = raster(lines, bytes_per_line, compress=compress)
    length = (label_length_dots if label_length_dots is not None
              else len(lines))

    out = bytearray()
    for index in range(copies):
        if roll is not None:
            out.extend(select_roll(roll))
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
