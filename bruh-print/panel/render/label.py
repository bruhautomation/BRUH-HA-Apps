#!/usr/bin/env python3
"""A label is a stock, an orientation, and a list of elements.

Everything is in **millimetres**, measured from the top-left of the drawable
area — not in dots, and not in fractions of the label. Dots would tie every
saved label to the 300dpi head it was designed on; fractions would make
"12pt text" mean something different on every stock. Millimetres survive
both, and they are what a person holding a ruler against a label is already
thinking in.

Elements are clamped, never rejected. A box dragged off the edge of a 0.56"
cryo label is somebody's finger on a phone, not a reason to refuse to print;
a size of 0 is a template field nobody filled in. The one thing that IS
refused is an element type we do not know, because rendering it as nothing
would be a label silently missing its barcode.

A type we RETIRED is the other case and it may not refuse — see `RETIRED`.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

# Every element type, with the fields the panel builds its form from. The UI
# is generated from this — adding a type is this table plus one draw
# function in image.py, and nothing in app.js.
CATALOG: dict[str, dict[str, Any]] = {
    "text": {
        "name": "Text",
        "icon": "T",
        "help": "Words. Leave the size at 0 and it grows to fill its box.",
        "fields": {
            "text": {"type": "string", "default": "", "label": "Text"},
            "font": {"type": "font", "default": "sans-bold", "label": "Font"},
            "size_mm": {"type": "number", "default": 0, "min": 0, "max": 60,
                        "label": "Height (mm)",
                        "help": "0 = fit the box automatically"},
            "align": {"type": "choice", "default": "center",
                      "choices": ["left", "center", "right"],
                      "label": "Align"},
            "valign": {"type": "choice", "default": "middle",
                       "choices": ["top", "middle", "bottom"],
                       "label": "Vertical"},
            "wrap": {"type": "bool", "default": True, "label": "Wrap"},
            "line_spacing": {"type": "number", "default": 1.1, "min": 0.6,
                             "max": 2.5, "label": "Line spacing"},
            "rotate": {"type": "choice", "default": 0,
                       "choices": [0, 90, 180, 270], "label": "Rotate"},
            "invert": {"type": "bool", "default": False,
                       "label": "Reverse", "help": "White on black"},
        },
    },
    "barcode": {
        "name": "Barcode",
        "icon": "|||",
        "help": "Code 128. Digits pack two per symbol, so lot numbers stay "
                "narrow.",
        "fields": {
            "data": {"type": "string", "default": "", "label": "Data"},
            "hri": {"type": "bool", "default": True,
                    "label": "Show the text", "help": "Printed underneath"},
            "hri_font": {"type": "font", "default": "mono",
                         "label": "Text font"},
            "hri_mm": {"type": "number", "default": 2.5, "min": 1, "max": 12,
                       "label": "Text height (mm)"},
            "quiet": {"type": "number", "default": 10, "min": 0, "max": 20,
                      "label": "Quiet zone (modules)"},
            "rotate": {"type": "choice", "default": 0,
                       "choices": [0, 90, 180, 270], "label": "Rotate"},
        },
    },
    "qr": {
        "name": "QR code",
        "icon": "▣",
        "help": "A URL, an id, or anything long. Stays square.",
        "fields": {
            "data": {"type": "string", "default": "", "label": "Data"},
            "ec": {"type": "choice", "default": "M",
                   "choices": ["L", "M", "Q", "H"],
                   "label": "Error correction",
                   "help": "Higher survives more damage and is bigger"},
            "border": {"type": "number", "default": 2, "min": 0, "max": 6,
                       "label": "Quiet zone (modules)"},
        },
    },
    "box": {
        "name": "Box",
        "icon": "▭",
        "help": "An outline or a filled block.",
        "fields": {
            "stroke_mm": {"type": "number", "default": 0.4, "min": 0,
                          "max": 5, "label": "Line width (mm)"},
            "fill": {"type": "bool", "default": False, "label": "Filled"},
            "radius_mm": {"type": "number", "default": 0, "min": 0, "max": 10,
                          "label": "Corner radius (mm)"},
        },
    },
    "line": {
        "name": "Line",
        "icon": "—",
        "help": "A rule. Drag it thin and wide, or thin and tall.",
        "fields": {
            "stroke_mm": {"type": "number", "default": 0.4, "min": 0.1,
                          "max": 5, "label": "Thickness (mm)"},
        },
    },
}

# Types that were in the catalog once and are not any more.
#
# A retired type and an unknown type are two different claims and only the
# second may refuse. "hologram" means this document came from a BRUH Print
# newer than this one and there is no telling what is missing, so opening it
# would be a label silently short of its barcode. "image" means WE took the
# type away — we know exactly what is lost, and refusing the whole document
# over it would make the rest of somebody's label unopenable on our account,
# for a box that could never hold a picture in the first place. So it is
# dropped, the reason goes on the label's notes, and everything else opens.
RETIRED: dict[str, str] = {
    "image": "This label had an image box on it. BRUH Print does not have "
             "image elements any more — there was never a way to get a "
             "picture into one — so that box is gone and the rest of the "
             "label is as it was.",
}

ROTATIONS = (0, 90, 180, 270)


class LabelError(ValueError):
    """A label document that cannot be read, with a sentence for a person.

    A distinct type because the PANEL echoes this one's text to the caller
    and nothing else's. Every message raised here is written for somebody
    holding a printer — "there is no element called 'hologram'", "this label
    does not say which stock it is for" — and echoing a bare `ValueError`
    instead would mean the day Pillow or the stdlib raises one from four
    frames down, its text goes out over HTTP too. The scanner is right that
    the pattern is the problem rather than any one message.
    """


def _num(value: Any, default: float) -> float:
    """A finite float, or the default.

    NaN and the infinities both have to go: a label file is typed by hand or
    written by an automation, and either can produce one — `w_mm: 1e999`
    parses to `inf` and turns into a canvas size no allocator will serve.
    `math.isfinite` covers both, where the earlier `out == out` was a NaN
    test written as a comparison of identical values, which reads as a typo
    and only ever caught half of it.
    """
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if math.isfinite(out) else float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass
class Element:
    """One thing on a label. `props` are the type's own fields."""

    type: str
    x_mm: float = 0.0
    y_mm: float = 0.0
    w_mm: float = 10.0
    h_mm: float = 5.0
    props: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "Element":
        kind = str(raw.get("type", "")).strip()
        if kind not in CATALOG:
            known = ", ".join(sorted(CATALOG))
            raise LabelError(
                f"There is no label element called {kind!r}. This label was "
                f"probably saved by a newer BRUH Print. Known types: {known}.")
        spec = CATALOG[kind]["fields"]
        props = {}
        given = raw.get("props") or {}
        for name, meta in spec.items():
            value = given.get(name, meta["default"])
            if meta["type"] == "number":
                value = _clamp(_num(value, meta["default"]),
                               _num(meta.get("min", -1e6), -1e6),
                               _num(meta.get("max", 1e6), 1e6))
            elif meta["type"] == "bool":
                value = bool(value)
            elif meta["type"] == "choice" and value not in meta["choices"]:
                value = meta["default"]
            else:
                value = value if value is not None else meta["default"]
            props[name] = value
        return cls(
            type=kind,
            x_mm=_num(raw.get("x_mm"), 0.0),
            y_mm=_num(raw.get("y_mm"), 0.0),
            w_mm=max(0.0, _num(raw.get("w_mm"), 10.0)),
            h_mm=max(0.0, _num(raw.get("h_mm"), 5.0)),
            props=props,
        )

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Label:
    """A complete label: which stock, which way round, and what is on it."""

    stock: str
    rotate: int = 0
    elements: list[Element] = field(default_factory=list)
    name: str = ""
    invert: bool = False
    # What reading the document had to say about it — a retired element that
    # was dropped, today. Deliberately not in `as_dict`: it describes the
    # READ, not the label, and saving it would bake a one-off sentence into
    # the file and re-report it on every open afterwards.
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict) -> "Label":
        stock = str(raw.get("stock", "")).strip()
        if not stock:
            raise LabelError(
                "This label does not say which stock it is for. Pick one in "
                "the designer — a label's size is the stock's size, so there "
                "is nothing to render without it.")
        rotate = raw.get("rotate", 0)
        try:
            rotate = int(rotate) % 360
        except (TypeError, ValueError):
            rotate = 0
        if rotate not in ROTATIONS:
            rotate = min(ROTATIONS, key=lambda r: abs(r - rotate))
        # The retired filter is here rather than in `Element.from_dict`
        # because an element cannot say "drop me" — it returns an Element or
        # it raises, and raising is the answer reserved for a type we do not
        # know.
        elements: list[Element] = []
        notes: list[str] = []
        for item in (raw.get("elements") or []):
            kind = str((item or {}).get("type", "")).strip()
            if kind in RETIRED:
                if RETIRED[kind] not in notes:
                    notes.append(RETIRED[kind])
                continue
            elements.append(Element.from_dict(item))
        return cls(
            stock=stock,
            rotate=rotate,
            name=str(raw.get("name", "") or ""),
            invert=bool(raw.get("invert", False)),
            elements=elements,
            notes=notes,
        )

    def as_dict(self) -> dict:
        return {
            "stock": self.stock,
            "rotate": self.rotate,
            "name": self.name,
            "invert": self.invert,
            "elements": [e.as_dict() for e in self.elements],
        }

    def canvas_mm(self, across_mm: float, feed_mm: float) -> tuple[float, float]:
        """The design canvas, which is the label turned the way you drew it.

        At 90 or 270 the canvas is the label on its side — which is the
        whole reason the setting exists: a 0.56 × 3.44 cryo wrap is designed
        as a long thin strip 3.44 across, and printed as 0.56 across.
        """
        if self.rotate in (90, 270):
            return feed_mm, across_mm
        return across_mm, feed_mm


def catalog_payload() -> dict:
    """What the panel builds its element forms from."""
    return {
        "elements": CATALOG,
        "rotations": list(ROTATIONS),
    }
