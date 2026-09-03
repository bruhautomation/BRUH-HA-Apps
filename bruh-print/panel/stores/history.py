#!/usr/bin/env python3
"""What was printed, so it can be printed again.

An index, not a queue: capped, never drained. The reason is the one thing
people actually want from a label printer's history — the vial came out of
the freezer with a torn label and they need *that* label again, not a
similar one. So each entry carries the fully-resolved label document, fields
already substituted, and reprinting is a render of exactly those bytes.

Two things are deliberately not here. There is no "failed" list — a job that
did not reach the printer never became a label, and an entry for it would
put a Reprint button on something that was never printed. And nothing is
ever edited in place: a reprint is a NEW entry, because "printed twice" is a
fact about the roll and the estimate depends on it.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import atomic_write

# 200 entries at a few kilobytes each is a file a Pi rewrites without
# noticing, and it is more history than anyone scrolls. The cap is on
# entries rather than bytes because an entry with a big embedded image is
# still one label, and dropping it early would make the history depend on
# what was on the labels rather than on how many there were.
MAX_ENTRIES = 200


@dataclass
class Entry:
    id: str
    at: float
    stock: str
    side: str
    copies: int
    title: str
    label: dict
    source: str = "panel"
    template: str = ""
    printer: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class HistoryStore:
    path: Path
    _items: list[Entry] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.load()

    def load(self) -> None:
        raw = atomic_write.read_json(self.path, {}) or {}
        self._items = []
        for item in raw.get("entries", []):
            known = {k: v for k, v in item.items()
                     if k in Entry.__dataclass_fields__}
            try:
                self._items.append(Entry(**known))
            except TypeError:
                continue

    def save(self) -> None:
        atomic_write.write_json(
            self.path, {"entries": [e.as_dict() for e in self._items]})

    def add(self, *, stock: str, side: str, copies: int, title: str,
            label: dict, source: str = "panel", template: str = "",
            printer: str = "") -> Entry:
        entry = Entry(
            id=uuid.uuid4().hex[:12], at=time.time(), stock=stock, side=side,
            copies=max(1, int(copies)), title=title or "(untitled)",
            label=label, source=source, template=template, printer=printer)
        self._items.insert(0, entry)
        del self._items[MAX_ENTRIES:]
        self.save()
        return entry

    def all(self, limit: int = 50) -> list[Entry]:
        return self._items[:max(1, limit)]

    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self._items if e.id == entry_id), None)

    def clear(self) -> None:
        self._items = []
        self.save()

    def counts_since(self, since: float) -> dict[str, int]:
        """Labels printed per roll side since a timestamp.

        Per *side* rather than per stock, because the question this answers
        is "how much of that roll have I used", and a roll is a bay.
        """
        out: dict[str, int] = {}
        for entry in self._items:
            if entry.at < since:
                continue
            out[entry.side] = out.get(entry.side, 0) + entry.copies
        return out
