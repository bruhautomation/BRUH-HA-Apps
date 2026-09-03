#!/usr/bin/env python3
"""Code 128 and QR, as bar widths rather than as an image.

Both encoders return *modules* — a list of bar/space widths for Code 128, a
matrix of booleans for QR — and the renderer turns those into pixels itself.
That split is deliberate and it is the same rule the rest of this add-on
follows: one rendering, one consumer. A barcode library that draws its own
PNG draws it at its own DPI with its own quiet zone and its own anti-
aliasing, and anti-aliasing is fatal here — a thermal head is one bit per
dot, so a grey edge pixel becomes a black one and every bar comes out a dot
wide. Rendering the modules ourselves means every bar is an exact whole
number of printer dots, which is the only way a scanner reads a small label.

Code 128 is written out rather than pulled in because the encoder is the
easy half and the *mode switching* is the half that matters: an auto-
switching encoder that drops into set C for a run of digits is what fits a
16-character lot number onto a 0.56" cryo label at all.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Code 128
# ---------------------------------------------------------------------------
# One entry per symbol value 0..106, each a run of six bar/space widths
# starting with a bar. This is the standard table; the checksum and the stop
# pattern's extra bar are what people get wrong, and both are below.
_PATTERNS = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213",
    "122312", "132212", "221213", "221312", "231212", "112232", "122132",
    "122231", "113222", "123122", "123221", "223211", "221132", "221231",
    "213212", "223112", "312131", "311222", "321122", "321221", "312212",
    "322112", "322211", "212123", "212321", "232121", "111323", "131123",
    "131321", "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121", "313121",
    "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114",
    "413111", "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141", "214121",
    "412121", "111143", "111341", "131141", "114113", "114311", "411113",
    "411311", "113141", "114131", "311141", "411131", "211412", "211214",
    "211232", "2331112",
]

_START_A, _START_B, _START_C = 103, 104, 105
_CODE_A, _CODE_B, _CODE_C = 101, 100, 99
_STOP = 106



class BarcodeError(ValueError):
    """Data that cannot be encoded in the chosen symbology."""


def _value_b(char: str) -> int:
    """Set B covers ASCII 32..127 as values 0..95."""
    code = ord(char)
    if not 32 <= code <= 127:
        raise BarcodeError(
            f"Code 128 cannot carry {char!r} — it encodes printable ASCII "
            f"only. Use a QR code for anything else.")
    return code - 32


def _digit_run(data: str, start: int) -> int:
    """How many digits run from `start`."""
    length = 0
    while start + length < len(data) and data[start + length].isdigit():
        length += 1
    return length


def code128_values(data: str) -> list[int]:
    """Symbol values for `data`, switching between sets B and C.

    Only B and C: set A exists for control characters, which no label
    carries, and supporting a third set would double the switching logic to
    encode data nobody prints. A run of digits goes to C when it pays —
    four or more mid-string, six or more at the start, because each switch
    costs a symbol and switching for a two-digit run makes the barcode
    longer, not shorter.
    """
    if not data:
        raise BarcodeError("A barcode needs something to encode.")

    values: list[int] = []
    index = 0
    run = _digit_run(data, 0)
    if run >= 6 or (run >= 2 and run == len(data)):
        mode = "C"
        values.append(_START_C)
    else:
        mode = "B"
        values.append(_START_B)

    while index < len(data):
        run = _digit_run(data, index)
        if mode == "C":
            # Set C encodes digit PAIRS, so an odd tail has to leave one
            # digit behind for set B — dropping into C with an odd run and
            # encoding the last digit as half a pair is the classic way to
            # produce a barcode that scans as the wrong number.
            usable = run - (run % 2)
            if usable >= 2:
                for offset in range(0, usable, 2):
                    values.append(int(data[index + offset:index + offset + 2]))
                index += usable
                continue
            values.append(_CODE_B)
            mode = "B"
            continue

        if run >= 6 or (run >= 4 and index + run == len(data)):
            if run % 2:
                values.append(_value_b(data[index]))
                index += 1
                continue
            values.append(_CODE_C)
            mode = "C"
            continue

        values.append(_value_b(data[index]))
        index += 1

    checksum = values[0]
    for position, value in enumerate(values[1:], start=1):
        checksum += position * value
    values.append(checksum % 103)
    values.append(_STOP)
    return values


def code128(data: str, *, quiet_modules: int = 10) -> list[int]:
    """Bar/space widths in modules, starting with a bar.

    The leading and trailing quiet zones are part of the symbol, not
    decoration: the spec asks for ten modules and a scanner that cannot see
    them will not decode, which on a label crowded up to its edge is the
    difference between a barcode and a picture of one. They are returned as
    widths (an even-indexed *space* is impossible, so the quiet zone is
    prepended as a zero-width bar followed by the space).
    """
    widths: list[int] = [0, max(0, quiet_modules)]
    for value in code128_values(data):
        widths.extend(int(c) for c in _PATTERNS[value])
    widths.append(max(0, quiet_modules))
    return widths


def code128_modules(data: str, *, quiet_modules: int = 10) -> list[bool]:
    """The symbol expanded to one boolean per module — True is ink."""
    out: list[bool] = []
    ink = True
    for width in code128(data, quiet_modules=quiet_modules):
        out.extend([ink] * width)
        ink = not ink
    return out


# ---------------------------------------------------------------------------
# QR
# ---------------------------------------------------------------------------
def qr_matrix(data: str, *, error_correction: str = "M",
              border: int = 2) -> list[list[bool]]:
    """A square matrix of booleans, True where the code is dark.

    Error correction defaults to M rather than L because these labels go on
    tubes that go into liquid nitrogen and come out frosted — the extra
    modules are cheap and the recovery is the entire point. The border is 2
    rather than the spec's 4 for the opposite reason: on a 0.56" label four
    quiet modules is most of the height, and every scanner in practice reads
    2 when the label around it is white anyway.
    """
    try:
        import qrcode  # noqa: PLC0415
        from qrcode.constants import (  # noqa: PLC0415
            ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M,
            ERROR_CORRECT_Q,
        )
    except ImportError as exc:  # pragma: no cover - depends on the image
        raise BarcodeError(
            "QR support needs the qrcode library, which is missing from this "
            "container.") from exc

    levels = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M,
              "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
    if not data:
        raise BarcodeError("A QR code needs something to encode.")

    code = qrcode.QRCode(
        version=None,
        error_correction=levels.get(error_correction.upper(), ERROR_CORRECT_M),
        box_size=1,
        border=max(0, border),
    )
    code.add_data(data)
    code.make(fit=True)
    return [[bool(cell) for cell in row] for row in code.get_matrix()]


SYMBOLOGIES = {
    "code128": "Code 128 — the general-purpose linear barcode. Printable "
               "ASCII; digits pack two to a symbol, so lot numbers stay "
               "short.",
    "qr": "QR — holds a URL, a JSON blob or a long id, and survives being "
          "half-frosted.",
}
