#!/usr/bin/env python3
"""Which DYMO is plugged in, and what it can do.

The model table names the printers we know, but *matching* is on the vendor
id alone: an unrecognised DYMO still prints, described by the product string
the device itself reports, because the alternative is an add-on that refuses
a printer it would have driven correctly. The raster protocol has been the
same across the whole LabelWriter line for twenty years; what varies is the
head width and whether there are two rolls, and both of those are questions
with a safe answer.

So an unknown model gets the 450's geometry (672 dots / 84 bytes per line,
the width of every 4xx and 5xx model that is not an XL) and `twin: False`.
Guessing narrow prints a label with margin to spare; guessing wide prints
past the head, which on a Twin Turbo means printing onto the second roll's
liner. And guessing `twin: True` would put a roll switch in the panel that
does nothing — a control that lies is worse than a missing one, which is
why the Twin Turbo is also detected from the product string and not only
from the id table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

DYMO_VENDOR_ID = 0x0922

# 672 dots across a 300dpi head is 2.24" of printable width — the LabelWriter
# 4xx/5xx head, and the reason a 2.25" label prints 3 dots narrow rather than
# refusing. The XL models are the exception, at 4.16".
HEAD_672 = 672
HEAD_1248 = 1248

DEFAULT_DPI = 300


@dataclass(frozen=True)
class Model:
    """One known LabelWriter."""

    name: str
    dots: int = HEAD_672
    twin: bool = False
    dpi: int = DEFAULT_DPI
    # Set for the 550 generation, which refuses third-party stock: the
    # printer checks an RFID tag on the roll and will not feed without it.
    # Nothing here can work around that, so the panel says so out loud
    # rather than reporting a silent no-op as a successful print.
    authenticated_media: bool = False

    @property
    def bytes_per_line(self) -> int:
        return self.dots // 8

    @property
    def printable_in(self) -> float:
        return self.dots / self.dpi


# Product ids for the models we can name. Anything else with DYMO's vendor
# id is still driven — see `describe`.
MODELS: dict[int, Model] = {
    0x0019: Model("LabelWriter 400"),
    0x0020: Model("LabelWriter 450"),
    0x0021: Model("LabelWriter 450 Turbo"),
    0x0022: Model("LabelWriter 450 Twin Turbo", twin=True),
    0x0023: Model("LabelWriter 450 DUO Label"),
    0x0028: Model("LabelWriter 4XL", dots=HEAD_1248),
    0x1001: Model("LabelWriter Wireless"),
    0x1002: Model("LabelWriter 550", authenticated_media=True),
    0x1003: Model("LabelWriter 550 Turbo", authenticated_media=True),
    0x1004: Model("LabelWriter 5XL", dots=HEAD_1248,
                  authenticated_media=True),
}

UNKNOWN = Model("LabelWriter (unrecognised model)")

_TWIN_RE = re.compile(r"twin\s*turbo", re.I)
_XL_RE = re.compile(r"\b[45]XL\b", re.I)
_AUTH_RE = re.compile(r"\b5(50|XL)\b", re.I)


@dataclass(frozen=True)
class Discovered:
    """A printer on the USB bus, as the panel talks about it."""

    product_id: int
    model: Model
    serial: str = ""
    bus: int = 0
    address: int = 0
    recognised: bool = True
    # Filled in by usb_link when it could see the device but not claim it.
    claim_error: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """A stable id for a printer across restarts, and across a reboot
        that renumbers the bus.

        The serial is what a person's saved default should follow — a Twin
        Turbo that comes up on a different USB address is still their
        printer. Only a device with no serial at all falls back to its bus
        position, which is the case where "the same printer" is genuinely
        not answerable.
        """
        if self.serial:
            return f"{self.product_id:04x}:{self.serial}"
        return f"{self.product_id:04x}@{self.bus}.{self.address}"

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.model.name,
            "product_id": f"0x{self.product_id:04x}",
            "serial": self.serial,
            "twin": self.model.twin,
            "dots": self.model.dots,
            "bytes_per_line": self.model.bytes_per_line,
            "dpi": self.model.dpi,
            "printable_in": round(self.model.printable_in, 3),
            "recognised": self.recognised,
            "authenticated_media": self.model.authenticated_media,
            "claim_error": self.claim_error,
        }


def describe(product_id: int, product_string: str = "") -> tuple[Model, bool]:
    """The model for a device, and whether we actually recognised it.

    The product string is consulted only for a device the table does not
    know. It is the device's own answer, so a Twin Turbo that ships with a
    new product id keeps its second roll instead of losing it to a table
    written before it existed.
    """
    known = MODELS.get(product_id)
    if known is not None:
        return known, True

    text = (product_string or "").strip()
    name = f"LabelWriter — {text}" if text else UNKNOWN.name
    return Model(
        name=name,
        dots=HEAD_1248 if _XL_RE.search(text) else HEAD_672,
        twin=bool(_TWIN_RE.search(text)),
        authenticated_media=bool(_AUTH_RE.search(text)),
    ), False
