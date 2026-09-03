#!/usr/bin/env python3
"""What is physically in the printer right now.

This is the piece a print server normally does not have and a label printer
cannot live without. A LabelWriter has no idea what stock is loaded — it
feeds to the next die-cut gap and prints whatever raster it is handed — so
"print this on the left roll" is only meaningful if something remembers that
the left roll is the 2.25 × 1.25 cryo stock and the right one is the 0.56 ×
3.44 wrap. That something is this file.

Getting it wrong is not a cosmetic failure. Sending a 2.25"-wide raster to
the 0.56" roll prints across the liner and through the gaps; a run of 50
does it 50 times. So the panel never silently prints a label whose stock
disagrees with the loaded roll — it refuses and names both, and the person
either changes the roll or tells us it changed. A confirmation that says
"the left roll now holds X" is one press; a ruined roll is not.

`changed_at` is here because a roll runs out, and the count only means
anything relative to when it was last set. `remaining` is decremented by
print jobs and is explicitly an *estimate* everywhere it is shown: nothing
on a LabelWriter reports a roll's true level, so a number presented as fact
would be a number people stop trusting the first time it is wrong.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import atomic_write

# The Twin Turbo's two bays, and the name a single-roll printer's one bay
# goes by. A single-roll model is "left" so that every label, template and
# automation written on a Twin Turbo keeps working if the printer is
# replaced with a 450 — the roll simply stops being a choice.
SIDES = ("left", "right")


class UnknownSide(KeyError):
    """A bay name that is not one of the two. `detail` is what to show."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass
class Roll:
    """One bay of the printer."""

    side: str
    stock: str = ""
    remaining: int = 0
    changed_at: float = 0.0
    note: str = ""

    def as_dict(self) -> dict:
        data = asdict(self)
        data["loaded"] = bool(self.stock)
        return data


@dataclass
class LoadedStore:
    path: Path
    _rolls: dict[str, Roll] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.load()

    def load(self) -> None:
        raw = atomic_write.read_json(self.path, {}) or {}
        self._rolls = {}
        for side in SIDES:
            item = raw.get(side) or {}
            self._rolls[side] = Roll(
                side=side,
                stock=str(item.get("stock", "") or ""),
                remaining=max(0, int(item.get("remaining", 0) or 0)),
                changed_at=float(item.get("changed_at", 0) or 0),
                note=str(item.get("note", "") or ""),
            )

    def save(self) -> None:
        atomic_write.write_json(
            self.path, {side: asdict(roll) for side, roll in self._rolls.items()})

    # -- reads -------------------------------------------------------------
    def all(self) -> list[Roll]:
        return [self._rolls[side] for side in SIDES]

    def get(self, side: str) -> Roll:
        if side not in self._rolls:
            raise UnknownSide(
                f"A printer has a {SIDES[0]} and a {SIDES[1]} roll; there is "
                f"no {side!r}.")
        return self._rolls[side]

    def side_for(self, stock_id: str) -> str | None:
        """Which bay holds this stock, if any.

        Left wins a tie. Somebody who has loaded the same stock in both bays
        does not care which one prints, and picking deterministically is
        what makes a second copy land on the same roll as the first.
        """
        return next((side for side in SIDES
                     if self._rolls[side].stock == stock_id), None)

    # -- writes ------------------------------------------------------------
    def load_roll(self, side: str, stock_id: str, *, count: int = 0,
                  note: str = "") -> Roll:
        roll = self.get(side)
        roll.stock = stock_id
        roll.remaining = max(0, int(count))
        roll.changed_at = time.time()
        roll.note = note
        self.save()
        return roll

    def unload(self, side: str) -> Roll:
        roll = self.get(side)
        roll.stock = ""
        roll.remaining = 0
        roll.changed_at = time.time()
        roll.note = ""
        self.save()
        return roll

    def consume(self, side: str, count: int) -> None:
        """Take printed labels off the estimate, and never below zero.

        Never below zero because a negative count would be the panel
        reporting a state that cannot exist, and the estimate is already the
        soft number here — a roll that reads 0 while still feeding is a
        person who under-counted when they loaded it, which is fine and
        self-correcting the next time they set it.
        """
        roll = self._rolls.get(side)
        if roll is None or not roll.remaining:
            return
        roll.remaining = max(0, roll.remaining - max(0, int(count)))
        self.save()


class RollMismatch(ValueError):
    """A job whose stock is not the stock in the bay it would print on."""
