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
#
# Two millimetres rather than one, because one was measured against the wrong
# thing. A LabelWriter's registration wanders by a fraction of a millimetre
# each way as the roll unwinds, and on a 2.25" stock the head is already three
# dot columns narrower than the label — so a margin of 1mm was, in practice,
# text touching the die cut on one side of every other label. This is a
# DEFAULT: a stock somebody added or corrected saved its own `margin_mm` and
# keeps it, which is the point of the override and also means a correction
# made against the old default survives this change. The Edit dialog on the
# Printer tab is where a roll that wants more or less says so.
DEFAULT_MARGIN_MM = 2.0

# There is deliberately no bound named here on how far the printing may be
# found to start from where it was asked for. 0.6.0 through 0.8.x had one —
# an inch — because those numbers were TYPED, and the bound was there to
# catch a decimal point in the wrong place. Nothing is typed any more: every
# number on a `Calibration` is derived from readings the route has already
# bounded, and `calibration.derive` refuses the two shapes that are actually
# impossible (a dead band longer than the label, a gap of less than no
# paper). A second bound here would be a second opinion about somebody's
# measurement, in a file that has never seen the label.


@dataclass
class Calibration:
    """What this printer does with this roll, measured rather than typed.

    0.6.0 shipped a signed feed offset, 0.7.0 a lateral media position and a
    die-cut gap beside it, and 0.8.x had four numbers on one dialog with four
    different meanings and four different signs. The owner printed the
    calibration label, read it, typed a number, printed again, and said: stop
    adding knobs. They were right, and not only about the count — the four
    could not answer the question between them. Three offsets (0, −8, −4) on
    the 2.25" roll moved everything on the label except the dead band at the
    leading edge, which stayed ~4mm throughout: proof that a raster shift
    cannot touch where the printer BEGINS, because the sheet it shifts within
    starts wherever the printer decided to start it.

    So this is not a set of corrections. It is what the printer was measured
    doing, and the print path is what works out the correction: five numbers
    a person reads off one printed label, plus two switches for the two
    firmware behaviours that are not measurable at all.

    **Every field is in the printer's axes and none of them is a nudge.**

    `across_mm` — where the label's LEFT edge sits on the print head, from
    head dot 0. It absorbs both of the old across numbers, which were always
    one quantity pretending to be two: `media_across_mm` said where a narrow
    roll's paper sat and `offset_across_mm` shifted artwork inside the sheet,
    and a person with a label printing 7mm to the left had no way to tell
    which of the two boxes was theirs. There is one edge, and this is where
    it is.

    `start_mm` — SIGNED, and the field the whole rewrite is for. Where raster
    line 0 lands relative to the die cut, on every label. Positive is the
    measured case: the printer lays no ink for the first `start_mm` of every
    label, so that band is unprintable and the artwork has to be laid out
    inside what is left (`printable_feed_mm`). Negative is the other one: ink
    would be asked for before the die cut, which `ESC f` can fix by feeding
    that far first, and the whole label is printable.

    `after_tear_mm` — how much LATER still the first copy of a job starts
    when the paper is sitting at the tear bar. The manual says an `ESC E`
    "places the next label beyond the starting print position. Therefore, a
    reverse-feed will be automatically invoked when printing on the next
    label"; a printer that does not make that reverse feed loses exactly this
    much off the first label of every job and nothing off the rest. It is 0.0
    on any printer that does, which is most of them — and it exists because
    "copy 1 is wrong and copy 2 is right" is a shape a single number cannot
    hold, so a roll with it would otherwise be calibrated wrong twice over.

    `length_mm` — the die-cut length as the calibration measured it, or
    `None` for "trust the catalog". Only stored when it disagrees with the
    catalog by more than a millimetre, because a measurement that merely
    confirms the number already on the row is a second copy of it that can
    drift.

    `gap_mm` — the measured hole-to-hole pitch minus the label, which is what
    `ESC L` is defined in. `None` keeps the 25%-with-a-floor headroom that
    every uncalibrated roll gets, byte for byte. It is derived rather than
    typed and no UI shows it: it is only knowable when the printer is NOT
    finding the sense hole, and that is a diagnosis the derivation makes.

    `job_start` / `ending` — the two that are not measurements. Whether a job
    opens with `ESC @` and whether it ends at the tear bar are firmware
    behaviours, and which one a given roll wants is answered by printing
    twice and comparing, not by measuring once.

    `measured_at` — when somebody last read a label, and the field that makes
    "this printer needs no correction" a different state from "nobody has
    asked". They are the same seven numbers otherwise, and a panel that could
    not tell them apart would offer the calibration for ever on the printer
    that least needs it, while a roll that was measured a year and two rolls
    ago would look freshly checked. Same distinction `usual_open` returning
    `None` keeps one add-on over, and the reason `derive` takes its `now`
    rather than reading the clock: a pure function that stamps itself is a
    pure function nobody can test twice.

    **`None` and `0.0` stay different states in both fields that have them.**
    Unset means nobody has measured it and the shipped behaviour is kept
    exactly; zero is a real answer with real consequences. That is
    `${VAR:-default}`'s trap in another language and every reader here tests
    `is None`.
    """

    across_mm: float = 0.0
    start_mm: float = 0.0
    after_tear_mm: float = 0.0
    length_mm: float | None = None
    gap_mm: float | None = None
    job_start: str = "plain"
    ending: str = "tear"
    measured_at: float | None = None

    @property
    def measured(self) -> bool:
        """Has anybody read a calibration label for this roll?

        The stamp first, because a printer that needs no correction saves
        seven default numbers and would otherwise read as never measured —
        which is the one answer that would keep offering the calibration to
        the person who least needs it. The rest of the test is for a roll
        calibrated before the stamp existed, whose numbers are still theirs.
        """
        return bool(self.measured_at
                    or self.across_mm or self.start_mm or self.after_tear_mm
                    or self.length_mm is not None or self.gap_mm is not None
                    or self.job_start != "plain" or self.ending != "tear")

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw, legacy: dict | None = None) -> "Calibration":
        """One calibration off disk, whichever shape it was written in.

        A stock saved by 0.6.0 through 0.8.x carries `offset_feed_mm`,
        `offset_across_mm`, `media_across_mm` and `gap_mm` at the top level,
        and those are somebody's ruler measurements: dropping them would
        silently un-calibrate a roll that was working. The map is the one the
        rewrite is built on — the two across numbers were always one edge, so
        they add; and a correction that moved the artwork 4.7mm back toward
        the leading edge was describing a printer that started 4.7mm late, so
        `start_mm` is the offset's negation.

        Nothing here may raise. This runs over a file another release wrote,
        and a stock that fails to load is a roll that vanishes out of the
        catalog with the panel reporting nothing at all.
        """
        if isinstance(raw, dict):
            return cls(
                across_mm=_number(raw.get("across_mm"), 0.0),
                start_mm=_number(raw.get("start_mm"), 0.0),
                after_tear_mm=_number(raw.get("after_tear_mm"), 0.0),
                length_mm=_optional(raw.get("length_mm")),
                gap_mm=_optional(raw.get("gap_mm")),
                job_start=_choice(raw.get("job_start"), JOB_STARTS, "plain"),
                ending=_choice(raw.get("ending"), ENDINGS, "tear"),
                measured_at=_optional(raw.get("measured_at")),
            )
        old = legacy or {}
        return cls(
            across_mm=(_number(old.get("media_across_mm"), 0.0)
                       + _number(old.get("offset_across_mm"), 0.0)),
            start_mm=-_number(old.get("offset_feed_mm"), 0.0),
            gap_mm=_optional(old.get("gap_mm")),
        )


JOB_STARTS = ("plain", "reset")
ENDINGS = ("tear", "hold")


def _number(value, fallback: float) -> float:
    """A float off disk, or the fallback. Never a raise — see `from_dict`."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    # NaN survives `float()` and then poisons every sum it reaches, so a
    # label would be shifted by a distance nothing can compare against.
    return result if result == result and abs(result) != float("inf") else fallback


def _optional(value) -> float | None:
    """A float, or `None` — and the two are not the same answer."""
    if value is None or value == "":
        return None
    result = _number(value, float("nan"))
    return None if result != result else result


def _choice(value, allowed: tuple[str, ...], fallback: str) -> str:
    return str(value) if value in allowed else fallback


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

    # What this printer was measured doing with this roll — see
    # `Calibration`, which is where all of it is explained. It lives on the
    # STOCK rather than on the printer or on the label because registration
    # on a die-cut roll is dominated by where the sense holes are punched
    # relative to the die cut, and where the paper sits under the head by how
    # wide the liner is: both are properties of the roll. A house with two
    # rolls in a Twin Turbo genuinely has two answers, and they are not each
    # other's.
    calibration: "Calibration" = field(default_factory=lambda: Calibration())

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
    def continuous(self) -> bool:
        """No die cut, so no sense holes and no label length.

        `feed_in == 0` is how a stock says it is continuous — the renderer
        already reads it that way (`dots()` floors at 1, and `render` takes
        a feed of one dot as "as long as the artwork") — and the print path
        needs the same fact under a name, because ESC L means something
        entirely different here: a positive length would send the printer
        hunting for a top-of-form hole that does not exist on this paper.
        """
        return self.feed_in <= 0

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

    @property
    def measured_feed_mm(self) -> float:
        """How long a label on this roll really is.

        The calibration's own measurement where there is one, the catalog
        otherwise. `ESC L` is built on this rather than on the height of the
        raster, because the two are different quantities: one is the paper
        and the other is what we chose to draw on it, and a continuous stock
        has the second and not the first.
        """
        if self.calibration.length_mm is not None:
            return max(0.0, self.calibration.length_mm)
        return self.feed_mm

    def dead_leading_mm(self, first_after_tear: bool = False) -> float:
        """How much of this label the printer will not put ink on.

        Positive only. A negative `start_mm` is a printer asked for ink
        before the die cut, which is not a dead band — it is a pre-skip, and
        `printable_feed_mm` is the whole label there.

        `first_after_tear` is the copy that follows an `ESC E`, which is the
        first copy of a job on a roll whose `ending` is "tear". One helper
        for the renderer, the designer and the send path, because three
        answers to "how much of this label can I use" is three chances for
        the designer to lay artwork into a band the printer will not reach.
        """
        cal = self.calibration
        extra = cal.after_tear_mm if first_after_tear else 0.0
        return max(0.0, cal.start_mm + extra)

    def printable_feed_mm(self, first_after_tear: bool = False) -> float:
        """How much of this label's length can carry ink.

        Floored at a millimetre rather than allowed to go negative: a dead
        band longer than the label is a calibration read off the wrong label
        or a roll nothing can print on, and a negative canvas would raise
        somewhere a long way from either.
        """
        return max(1.0, self.measured_feed_mm
                   - self.dead_leading_mm(first_after_tear))

    def dots(self, dpi: int = 300) -> tuple[int, int]:
        """(across, feed) in printer dots."""
        return (max(1, round(self.across_in * dpi)),
                max(1, round(self.feed_in * dpi)))

    def swapped(self) -> "Stock":
        """The same stock with its two dimensions exchanged.

        Editing rather than adding, because it is the same physical roll —
        a second row for the transposed version is two rows a person has to
        choose between with no way to tell which is right.

        **`across_mm` survives and the feed-direction measurements do not.**
        Where the paper's left edge sits under the head is a fact about the
        liner, and exchanging which of the catalog's two numbers is called
        "across" does not slide the roll along the head. The other four were
        all read off ONE printed calibration label, against a sheet drawn to
        the shape the swap has just declared wrong — so `start_mm`,
        `after_tear_mm`, `length_mm` and `gap_mm` are measurements of a label
        that was the wrong way round, and keeping them would be a swap that
        fixes the width and leaves the printing starting in the wrong place
        for a reason nobody could find. Printing the calibration label again
        is one press, and it is the only honest answer.

        `measured_at` goes with them, which is what makes the panel ask for
        that press: a roll left holding a stamp over four zeroed measurements
        would read as calibrated for ever, and a verdict nothing re-earns is
        a verdict nothing can correct.
        """
        cal = self.calibration
        return replace(
            self, across_in=self.feed_in, feed_in=self.across_in,
            builtin=False,
            # Deliberately not carried over: the shape is what
            # `natural_turn` reads, so a derived turn has to be re-derived
            # from the new shape. Keeping the old answer is how a swap fixes
            # the width and leaves the text lying the way it was wrong
            # before.
            turn=None,
            calibration=Calibration(across_mm=cal.across_mm,
                                    job_start=cal.job_start,
                                    ending=cal.ending))

    def as_dict(self) -> dict:
        data = asdict(self)
        data["across_mm"] = round(self.across_mm, 2)
        data["feed_mm"] = round(self.feed_mm, 2)
        width, height = self.drawable_mm
        data["drawable_mm"] = [round(width, 2), round(height, 2)]
        data["label"] = f'{self.across_in}" × {self.feed_in}"'
        data["turn"] = self.natural_turn
        data["turn_set"] = self.turn is not None
        # What the wizard and the designer read: the dead band the printer
        # will not reach, and what is left of the label. Derived here so the
        # panel cannot answer it a second way — the designer laying a box
        # inside the printable part and the send path cropping to it have to
        # agree to the dot.
        data["calibrated"] = self.calibration.measured
        data["dead_leading_mm"] = round(self.dead_leading_mm(), 2)
        data["printable_feed_mm"] = round(self.printable_feed_mm(), 2)
        data["first_label_dead_mm"] = round(self.dead_leading_mm(True), 2)
        return data


def replace(entry: Stock, **changes) -> Stock:
    """A copy of `entry` with fields changed.

    `dataclasses.replace` would do, except a builtin edited into a custom
    row has to flip `builtin` too, and every caller forgetting that is a row
    that silently reverts on the next release.

    `asdict` recurses, so the calibration comes back as a plain dict and
    handing that to `Stock(...)` would make `entry.calibration.start_mm`
    raise on a copy of a stock nobody edited. It is rebuilt rather than
    deep-copied because a `Calibration` a caller passed in is theirs.
    """
    data = {**asdict(entry), **changes}
    cal = data.get("calibration")
    if isinstance(cal, dict):
        data["calibration"] = Calibration.from_dict(cal)
    return Stock(**data)


def _builtin(**kwargs) -> Stock:
    return Stock(builtin=True, **kwargs)


def _from_stored(item: dict) -> Stock:
    """One row off disk, in whichever release's shape it was written.

    The four pre-0.9 fields are mapped in `Calibration.from_dict` and the
    rest is the ordinary field filter. What is written back is only ever the
    new shape: carrying the old keys along "just in case" is how two writers
    end up disagreeing about which of them a reader believes.
    """
    fields = {key: value for key, value in item.items()
              if key in Stock.__dataclass_fields__ and key != "calibration"}
    fields["calibration"] = Calibration.from_dict(
        item.get("calibration"), legacy=item)
    return Stock(**fields)


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
            if not isinstance(item, dict):
                continue
            try:
                stock = _from_stored(item)
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
