"""Numbers in sentences a person reads: rounded for reading, unit spaced.

A check's detail used to be an f-string with `:g` or `:.3g` and the unit
pasted straight on, which is how a card came to say "-100.233labels over
28 days … 5.39 times it": a hyphen for a minus sign, three decimals of a
count nobody measures to a thousandth, and a unit glued to its number.
`quantity` is the one implementation, so every server-composed sentence
says "−100 labels" the same way.

Rules, all of them about reading rather than precision — the store keeps
the precise number and the card is not where it is read:

* **Rounded by size.** 100 and up: whole numbers. 1 to 100: one decimal,
  dropped when it is zero. Under 1: two significant figures. A reading
  where the decimals matter (a thermometer) still has its one decimal.
* **A real minus sign** (U+2212), and a plus only when asked for.
* **The unit spaced**, except the units that are written against the
  number in ordinary prose: ``%`` and a bare ``°``.
* **Never raises.** A value that is not a number comes back as its own
  text, because a check's sentence must not take down the pass.

A leaf: the checks, the stores and the server all import it, and a module
they all import may import none of them.
"""

from __future__ import annotations

import math

MINUS = "−"
# Written against the number: "40%", "90°". Everything else — "°C",
# "kWh", "labels", "W" — gets a space.
_TIGHT_UNITS = ("%", "°")


def number(value, *, signed: bool = False) -> str:
    """`value` rounded for reading, with a real minus sign."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value if value is not None else "")
    if math.isnan(x) or math.isinf(x):
        return str(value)
    mag = abs(x)
    if mag >= 100:
        text = f"{round(mag):,}"
    elif mag >= 1:
        text = f"{mag:.1f}"
        if text.endswith(".0"):
            text = text[:-2]
    elif mag == 0:
        text = "0"
    else:
        # Two significant figures, never scientific notation.
        digits = max(2, 1 - int(math.floor(math.log10(mag))))
        text = f"{mag:.{digits}f}".rstrip("0").rstrip(".") or "0"
    if text in ("0", "0.0"):
        return "0"
    if x < 0:
        return MINUS + text
    if signed:
        return "+" + text
    return text


def unit_text(unit) -> str:
    """The unit as it follows a number: '' / '%' / ' kWh'."""
    u = str(unit or "").strip()
    if not u:
        return ""
    if u in _TIGHT_UNITS:
        return u
    return " " + u


def quantity(value, unit="", *, signed: bool = False) -> str:
    """`value` and its unit, read the way a person writes them."""
    return number(value, signed=signed) + unit_text(unit)


def times(value) -> str:
    """'5.4 times', '1 time'."""
    text = number(value)
    return f"{text} {'time' if text == '1' else 'times'}"


__all__ = ["MINUS", "number", "quantity", "times", "unit_text"]
