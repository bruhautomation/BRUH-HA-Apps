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

import datetime as _dt
import math
import os
import re
import time

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


def quantity(value, unit="", *, signed: bool = False,
             delta: bool | None = None) -> str:
    """`value` and its unit, read the way a person writes them.

    A temperature is said in the house's own unit (`house_unit`, #1332):
    a check reads each sensor in whatever unit it reports, and a °C
    thermometer in a °F house is converted here, where every sentence a
    check writes says its figures. ``delta`` is a difference (a rise, a
    margin, a rate), converted without the offset; a signed figure is one
    unless the caller says otherwise."""
    value, unit = in_house_unit(value, unit,
                                delta=signed if delta is None else delta)
    return number(value, signed=signed) + unit_text(unit)


# ---------------------------------------------------------------------------
# The house's own temperature unit and date style (#1332)
# ---------------------------------------------------------------------------
#
# Home Assistant's unit system, cached by run.sh off the same /api/config
# read that gives the timezone. Absent (an older start, a test), nothing is
# converted: a figure stays in the unit it was read in, which is honest.
TEMPERATURE_UNIT_FILE = os.environ.get(
    "BRAIN_TEMPERATURE_UNIT_FILE",
    "/config/.brain/cache/ha_temperature_unit")
_UNIT_CACHE: dict = {"at": 0.0, "unit": ""}
_UNIT_TTL_S = 300.0


def temperature_unit(unit) -> str:
    """'°C' / '°F' for a temperature unit however it is spelled, else ''."""
    u = str(unit or "").strip().lower().replace(" ", "")
    if u in ("°c", "c", "℃", "celsius", "degc"):
        return "°C"
    if u in ("°f", "f", "℉", "fahrenheit", "degf"):
        return "°F"
    return ""


def house_unit() -> str:
    """The house's temperature unit, '°C' or '°F', or '' when not known."""
    now = time.monotonic()
    if _UNIT_CACHE["at"] and now - _UNIT_CACHE["at"] < _UNIT_TTL_S:
        return _UNIT_CACHE["unit"]
    try:
        with open(TEMPERATURE_UNIT_FILE, "r", encoding="utf-8") as fh:
            unit = temperature_unit(fh.read())
    except OSError:
        unit = ""
    _UNIT_CACHE.update(at=now, unit=unit)
    return unit


def in_house_unit(value, unit, *, delta: bool = False):
    """``(value, unit)`` in the house's temperature unit. Anything that is
    not a temperature, or a house whose unit is not known, comes back as
    it was; so does a value that is not a number."""
    have = temperature_unit(unit)
    want = house_unit() if have else ""
    if not have or not want or have == want:
        return value, unit
    try:
        x = float(value)
    except (TypeError, ValueError):
        return value, unit
    if math.isnan(x) or math.isinf(x):
        return value, unit
    if want == "°F":
        x = x * 1.8 if delta else x * 1.8 + 32.0
    else:
        x = x / 1.8 if delta else (x - 32.0) / 1.8
    return x, want


def temperature(value, unit, *, delta: bool = False, whole: bool = False,
                signed: bool = False) -> str:
    """A temperature in the house's unit: '41 °F', '5 °C', '−3 °C'.
    ``whole`` rounds to whole degrees, which a forecast is read in."""
    value, unit = in_house_unit(value, unit, delta=delta)
    if whole:
        try:
            value = round(float(value))
        except (TypeError, ValueError):
            pass
    return number(value, signed=signed) + unit_text(unit)


def reading(value, unit) -> str:
    """A sensor's reading as anything brAIn writes or hands a model quotes
    it (#1471): a number in the house's unit WITH the unit it is in, read
    off the entity's own `unit_of_measurement` (`quantity`), so a figure from a
    °F probe is never a bare figure a reader takes for °C. A state that is
    not a number is said as it is, and a reading with no unit stays bare —
    nothing is guessed."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value if value is not None else "")
    if math.isnan(x) or math.isinf(x):
        return str(value)
    return quantity(x, unit)


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
          "Oct", "Nov", "Dec")


def day(ts, tz=None, now: float | None = None) -> str:
    """The one short date a person reads: '22 Nov', with the year only
    when it is not this year ('22 Nov 2025'). In ``tz`` when given, else
    the process's local zone (run.sh sets it to the house's). English
    month names, never the reader's locale order ('Nov 22')."""
    try:
        when = float(ts)
    except (TypeError, ValueError):
        return ""
    if not when:
        return ""
    if when > 1e11:
        when /= 1000.0
    try:
        d = _dt.datetime.fromtimestamp(when, tz) if tz is not None else \
            _dt.datetime.fromtimestamp(when)
        ref = _dt.datetime.fromtimestamp(
            time.time() if now is None else now, d.tzinfo)
    except (OverflowError, OSError, ValueError):
        return ""
    said = f"{d.day} {MONTHS[d.month - 1]}"
    return said if d.year == ref.year else f"{said} {d.year}"


# An ISO date in a sentence ("2026-11-22", "2026-11-22T08:10:00Z"): a
# format, never a word. A time with it is kept as the house's clock time
# ("22 Nov 08:10"), moved into the local zone when the stamp names its own.
_ISO_DATE_RE = re.compile(
    r"(?<![\w.-])(\d{4}-\d{2}-\d{2})"
    r"(?:[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)(Z|[+-]\d{2}:?\d{2})?)?"
    r"(?![\w-])")


def said_dates(text, now: float | None = None) -> str:
    """``text`` with every ISO date said the one short way (`day`)."""
    if not isinstance(text, str) or "-" not in text:
        return text
    this_year = _dt.datetime.fromtimestamp(
        time.time() if now is None else now).year

    def one(m: re.Match) -> str:
        date, clock, zone = m.group(1), m.group(2), m.group(3)
        try:
            d = _dt.datetime.fromisoformat(
                date + (f"T{clock}" if clock else "")
                + ("+00:00" if zone == "Z" else (zone or "")))
        except ValueError:
            return m.group(0)
        if d.tzinfo is not None:
            d = d.astimezone()
        said = f"{d.day} {MONTHS[d.month - 1]}"
        if d.year != this_year:
            said += f" {d.year}"
        return f"{said} {d:%H:%M}" if clock else said

    return _ISO_DATE_RE.sub(one, text)


def times(value) -> str:
    """'5.4 times', '1 time'."""
    text = number(value)
    return f"{text} {'time' if text == '1' else 'times'}"


def count(n: int, one: str, many: str = "") -> str:
    """'1 hour', '2 hours': a whole count with its noun agreeing."""
    n = int(n)
    return f"{n} {one if n == 1 else (many or one + 's')}"


def span(seconds) -> str:
    """A length of time as a person says it: minutes up to two hours, whole
    hours up to two days, then days. "230 minutes" and "226 hours" are both
    arithmetic the reader has to redo."""
    try:
        sec = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return "a while"
    if sec < 7200:
        return count(max(1, int(sec // 60)), "minute")
    if sec < 2 * 86400:
        return count(int(sec // 3600), "hour")
    return count(int(sec // 86400), "day")


def ago_minutes(minutes) -> str:
    """'5 minutes ago', '3 hours ago', '9 days ago' (see `span`)."""
    try:
        m = max(0, int(minutes))
    except (TypeError, ValueError):
        return "a while ago"
    return span(m * 60) + " ago"


__all__ = ["MINUS", "ago_minutes", "count", "day", "house_unit",
           "in_house_unit", "number", "quantity", "said_dates", "span",
           "temperature", "temperature_unit", "times", "unit_text"]
