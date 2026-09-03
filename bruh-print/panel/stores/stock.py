#!/usr/bin/env python3
"""What a roll of labels is, and which rolls this house has.

A label stock is two measurements and a name, and the two measurements are
not interchangeable: `across_in` is the dimension that lies across the print
head, `feed_in` is the one that travels past it. Getting them the wrong way
round is the single most common way a label comes out rotated 90 degrees
with the text running off the edge, and it is not something the printer can
tell you — a LabelWriter feeds to the next die-cut gap and has no idea what
shape the label it just printed was.

So the catalog stores both explicitly, `swap()` is one press in the panel,
and a stock a person edited is theirs: the built-ins seed the list and are
never re-imposed over an edit (`builtin: true` marks where a row came from,
and an edited built-in is saved as an override, so a future release adding a
correction cannot silently undo somebody's measurement).

The two rolls seeded from what is actually on the machine:

  EDCC-082WH  Chemical-Resistant Cryo Labels   2.25" x 1.25"   1000/roll
  ED1F-060WH  Cryogenic Labels                 0.56" x 3.44"   350/roll

Both are read off the roll cores, in the vendor's own `size:` order. That
order is the vendor's, not the printer's, which is exactly why `across_in`
is a separate field and not just "the first number" — the 2.25 x 1.25 sits
across the head at 2.25", while the 0.56 x 3.44 cryo wrap goes round a tube
and feeds at 3.44". Both are checked by printing the ruler from the Printer
tab, which is the only way to be sure and takes one label.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# panel/ is on sys.path (server.py puts it there, and so do the tests), so
# cross-package modules are imported flat — the same contract every panel
# module in this repo uses.
import atomic_write

MM_PER_IN = 25.4

# A margin the printer physically cannot reach. The 450's head does not start
# at the very edge of the liner, and thermal stock curls at the die cut, so
# artwork drawn into the last half-millimetre either does not appear or
# appears smeared. It is a default, per-stock overridable, and it is applied
# to the drawable area rather than to the label size — a person measuring
# their label with a ruler should get the number on the roll.
DEFAULT_MARGIN_MM = 1.0


class UnknownStock(KeyError):
    """A stock id nothing in the catalog answers to.

    Its `detail` is what the panel shows. A `KeyError`'s own `str()` wraps
    the message in quotes — which is why the panel used to `.strip('"')`,
    and which is the sort of thing that gets copied into the next handler
    and then forgotten.
    """

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class Stock:
    """One kind of label."""

    id: str
    name: str
    across_in: float
    feed_in: float
    sku: str = ""
    per_roll: int = 0
    margin_mm: float = DEFAULT_MARGIN_MM
    notes: str = ""
    builtin: bool = False
    # Which way artwork sits on THIS stock, remembered per stock rather than
    # decided per print. A wrap-around cryo label is 0.56" across and 3.44"
    # along, and its text runs along the roll; a 2.25 × 1.25 address label
    # reads the ordinary way round. That is a property of the label, not of
    # the job, and asking about it on every print is asking a question whose
    # answer never changes. `None` means "work it out from the shape", which
    # is right for a stock nobody has corrected; a number is somebody having
    # corrected it, and survives.
    turn: int | None = None

    # -- derived -----------------------------------------------------------
    @property
    def across_mm(self) -> float:
        return self.across_in * MM_PER_IN

    @property
    def feed_mm(self) -> float:
        return self.feed_in * MM_PER_IN

    @property
    def drawable_mm(self) -> tuple[float, float]:
        """(width, height) in mm of the area artwork may occupy.

        Width is across the head. Never negative: a stock narrower than
        twice the margin is a stock somebody mistyped, and returning a
        negative canvas would raise somewhere far away from the field they
        got wrong.
        """
        margin = max(0.0, self.margin_mm)
        return (max(1.0, self.across_mm - 2 * margin),
                max(1.0, self.feed_mm - 2 * margin))

    @property
    def natural_turn(self) -> int:
        """The rotation artwork takes on this stock unless told otherwise.

        A stock much longer than it is wide is a wrap-around label and its
        text runs along the roll. 1.6 rather than 1.0 because a stock only
        slightly taller than it is wide (a 2 × 3 shelf label) reads the
        ordinary way round, and guessing 90° there is worse than not
        guessing at all.
        """
        if self.turn is not None:
            return self.turn
        return 90 if self.feed_in > self.across_in * 1.6 else 0

    def dots(self, dpi: int = 300) -> tuple[int, int]:
        """(across, feed) in printer dots."""
        return (max(1, round(self.across_in * dpi)),
                max(1, round(self.feed_in * dpi)))

    def swapped(self) -> "Stock":
        """The same stock with its two dimensions exchanged.

        Editing rather than adding, because it is the same physical roll —
        a second row for the transposed version is two rows a person has to
        choose between with no way to tell which is right.
        """
        return Stock(**{**asdict(self), "across_in": self.feed_in,
                        "feed_in": self.across_in, "builtin": False,
                        # Deliberately not carried over: the shape is what
                        # `natural_turn` reads, so a derived turn has to be
                        # re-derived from the new shape. Keeping the old
                        # answer is how a swap fixes the width and leaves
                        # the text lying the way it was wrong before.
                        "turn": None})

    def as_dict(self) -> dict:
        data = asdict(self)
        data["across_mm"] = round(self.across_mm, 2)
        data["feed_mm"] = round(self.feed_mm, 2)
        width, height = self.drawable_mm
        data["drawable_mm"] = [round(width, 2), round(height, 2)]
        data["label"] = f'{self.across_in}" × {self.feed_in}"'
        data["turn"] = self.natural_turn
        data["turn_set"] = self.turn is not None
        return data


def replace(entry: Stock, **changes) -> Stock:
    """A copy of `entry` with fields changed.

    `dataclasses.replace` would do, except a builtin edited into a custom
    row has to flip `builtin` too, and every caller forgetting that is a row
    that silently reverts on the next release.
    """
    return Stock(**{**asdict(entry), **changes})


def _builtin(**kwargs) -> Stock:
    return Stock(builtin=True, **kwargs)


# The rolls this add-on ships knowing about. The two cryo ones are the
# machine's own; the DYMO part numbers are the stock most LabelWriters have
# in them, and they are here so the first run of the panel is a list to pick
# from rather than a form to fill in.
BUILTIN: list[Stock] = [
    _builtin(
        id="edcc-082wh", sku="EDCC-082WH",
        name="Chemical-Resistant Cryo Labels",
        across_in=2.25, feed_in=1.25, per_roll=1000,
        notes="Solvent- and cryo-resistant face stock. 2.25\" is a hair over "
              "the 450's 2.24\" printable width, so the outermost three dot "
              "columns are the printer's margin rather than yours.",
    ),
    _builtin(
        id="ed1f-060wh", sku="ED1F-060WH",
        name="Cryogenic Labels",
        across_in=0.56, feed_in=3.44, per_roll=350,
        notes="Wrap-around tube label: the long dimension goes round the "
              "tube or a cable. Text almost always wants rotating 90°, "
              "which is what this stock's Turn setting already says.",
    ),
    _builtin(id="dymo-30252", sku="30252", name="Address",
             across_in=1.125, feed_in=3.5, per_roll=350),
    _builtin(id="dymo-30336", sku="30336", name="Multipurpose (small)",
             across_in=1.0, feed_in=2.125, per_roll=500),
    _builtin(id="dymo-30330", sku="30330", name="Return address",
             across_in=0.75, feed_in=2.0, per_roll=500),
    _builtin(id="dymo-30256", sku="30256", name="Shipping",
             across_in=2.3125, feed_in=4.0, per_roll=300),
    _builtin(id="dymo-30323", sku="30323", name="Shipping (large)",
             across_in=2.125, feed_in=4.0, per_roll=220),
    _builtin(id="dymo-30346", sku="30346", name="Library / spine",
             across_in=0.5, feed_in=1.75, per_roll=500),
    _builtin(id="dymo-30299", sku="30299", name="Jewellery / barbell",
             across_in=0.4375, feed_in=2.1875, per_roll=1500),
    _builtin(id="continuous-2-25", sku="", name="Continuous tape (2.25\")",
             across_in=2.25, feed_in=0.0, per_roll=0,
             notes="Continuous stock has no die-cut length. Set the length "
                   "you want on the label itself; feed_in 0 means 'as long "
                   "as the artwork'."),
]


@dataclass
class StockStore:
    """The catalog, built-ins plus whatever this house added or corrected."""

    path: Path
    _custom: dict[str, Stock] = field(default_factory=dict)
    _hidden: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        self._custom = {}
        self._hidden = set()
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        for item in raw.get("stocks", []):
            try:
                stock = Stock(**{k: v for k, v in item.items()
                                 if k in Stock.__dataclass_fields__})
            except TypeError:
                continue
            self._custom[stock.id] = stock
        self._hidden = set(raw.get("hidden", []))

    def save(self) -> None:
        atomic_write.write_json(self.path, {
            "stocks": [asdict(s) for s in self._custom.values()],
            "hidden": sorted(self._hidden),
        })

    # -- reads -------------------------------------------------------------
    def all(self) -> list[Stock]:
        """Built-ins first, overridden where this house has corrected one.

        An override keeps the built-in's position in the list, because the
        list is something people learn the shape of — a corrected roll
        jumping to the bottom is a roll they then hunt for.
        """
        out: list[Stock] = []
        for stock in BUILTIN:
            if stock.id in self._hidden:
                continue
            out.append(self._custom.get(stock.id, stock))
        builtin_ids = {s.id for s in BUILTIN}
        out.extend(s for sid, s in sorted(self._custom.items())
                   if sid not in builtin_ids)
        return out

    def get(self, stock_id: str) -> Stock | None:
        return next((s for s in self.all() if s.id == stock_id), None)

    def require(self, stock_id: str) -> Stock:
        stock = self.get(stock_id)
        if stock is None:
            known = ", ".join(s.id for s in self.all()[:6])
            raise UnknownStock(
                f"No label stock called {stock_id!r}. Known: {known}…")
        return stock

    # -- writes ------------------------------------------------------------
    def put(self, stock: Stock) -> Stock:
        stock.builtin = False
        self._custom[stock.id] = stock
        self._hidden.discard(stock.id)
        self.save()
        return stock

    def remove(self, stock_id: str) -> None:
        """Delete a custom stock; hide a built-in.

        Built-ins live in the code, so 'delete' cannot mean delete — it means
        stop offering it, and it stays reversible because the definition is
        still there.
        """
        if stock_id in self._custom:
            del self._custom[stock_id]
        if any(s.id == stock_id for s in BUILTIN):
            self._hidden.add(stock_id)
        self.save()

    def restore(self, stock_id: str) -> None:
        self._hidden.discard(stock_id)
        self._custom.pop(stock_id, None)
        self.save()
