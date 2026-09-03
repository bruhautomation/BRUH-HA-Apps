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
STATUS_READY = 0x00
_BUSY_BITS = 0x01
_TOP_OF_FORM_BIT = 0x02
_OUT_OF_PAPER_BIT = 0x04
_LID_OPEN_BIT = 0x08


@dataclass(frozen=True)
class Status:
    """What the printer said about itself, and whether it said anything."""

    answered: bool
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
        if not self.answered:
            return "no status reported"
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
        busy=bool(first & _BUSY_BITS),
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


def raster(lines: list[bytes], bytes_per_line: int) -> bytes:
    """The raster body: SYN per changed line, ETB per repeat.

    Compression matters more than it looks. A 1.25" label at 300dpi is 375
    lines of 84 bytes, and on a label that is mostly white the blank runs
    are most of it — a wrap-around cryo label is 3.44" of mostly nothing.
    ETB turns each of those lines into one byte, and the printer expands it.
    """
    out = bytearray()
    previous: bytes | None = None
    for line in lines:
        packed = pack_line(line, bytes_per_line)
        if packed == previous:
            out.append(ETB)
            continue
        out.append(SYN)
        out.extend(packed)
        previous = packed
    return bytes(out)


def job(lines: list[bytes], *, bytes_per_line: int, roll: int | None = None,
        copies: int = 1, label_length_dots: int | None = None) -> bytes:
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
    body = raster(lines, bytes_per_line)
    length = (label_length_dots if label_length_dots is not None
              else len(lines))

    out = bytearray()
    for index in range(copies):
        if roll is not None:
            out.extend(select_roll(roll))
        out.extend(set_dot_tab(0))
        out.extend(set_bytes_per_line(bytes_per_line))
        out.extend(set_label_length(length))
        out.extend(body)
        out.extend(short_form_feed() if index < copies - 1 else form_feed())
    return bytes(out)
