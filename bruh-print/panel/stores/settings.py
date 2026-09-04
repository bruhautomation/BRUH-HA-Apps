#!/usr/bin/env python3
"""Panel preferences — the choices that are not add-on options.

The split is on who owns the answer. `config.yaml` holds what the *install*
is (which log level, whether the integration is deployed): things a person
sets once, in Home Assistant's own add-on form, and that need a restart to
take effect anyway. This file holds what the *panel* is doing right now —
which printer is the default, which stock a new label starts on, whether the
last-used template reopens — and those must change without a restart,
because a restart to change the default roll is a restart nobody performs.

Every key has a default here and `get` never raises: a settings file that
has been hand-edited into nonsense must not stop the panel serving, because
the panel is the only way to fix it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import atomic_write

DEFAULTS: dict[str, Any] = {
    # "" means "whatever is plugged in", which is the right default for the
    # overwhelmingly common one-printer house and degrades correctly when a
    # second appears — it prints on the first, and the panel says which.
    "printer": "",
    "default_stock": "edcc-082wh",
    "default_font": "sans-bold",
    # Refusing is the default and it is the safe one: printing a 2.25"
    # raster onto a 0.56" roll wastes labels a run at a time, and the fix is
    # one press either way. Turning it off is for somebody who reloads rolls
    # faster than they update the panel and would rather we not ask.
    "enforce_stock": True,
    # What the printer is sent, for the one thing this add-on cannot test
    # from here: whether a given firmware takes every command in the
    # preamble. "standard" is the shape cups-filters' DYMO path has printed
    # with for twenty years — a SYN line per row, no compression. The other
    # two exist because a printer that stays silent is otherwise a guessing
    # game played one release at a time.
    #   standard — recommended, and what everything is tested against
    #   compact  — adds ETB run-compression; a fraction of the bytes, and
    #              the opcode this add-on is least sure of
    #   bare     — drops roll select and the dot-tab reset too, which
    #              costs the Twin Turbo its second bay and leaves the left
    #              margin wherever the last driver to touch this printer
    #              set it; the last thing to try
    "print_mode": "standard",
    # How dark, and how slowly. Both are commands the printer takes in the
    # standard and compact modes and neither is sent in `bare`.
    #   Dark, because light labels were the complaint: a LabelWriter with
    #   no density command runs at `normal`, and on ordinary thermal stock
    #   that reads as faint. Nothing here is per-job — a person who wants
    #   dark labels wants them on every label.
    "density": "dark",
    #   Graphics is the slow 300x600 mode. The head dwells twice as long
    #   over every line, which is darker as well as more accurate for
    #   barcodes, and the fast text mode is one menu item away for anybody
    #   printing runs where the seconds matter.
    "quality": "graphics",
    "quick_uppercase": False,
    # Counting down from a number somebody typed is an estimate dressed as
    # a gauge: nothing on a LabelWriter reports a roll's real level, so the
    # count is only ever as good as the last time it was set. Some people
    # want it and keep it honest; some want the printer to just print. Off
    # hides every bar and estimate and stops the decrement — a number that
    # is not shown must not go on being kept, or turning tracking back on
    # reveals a count that has been quietly wrong for a month.
    "track_remaining": True,
    "preview_scale": 2,
    "confirm_over_copies": 10,
    "notify_service": "",
}

# The three settings whose value is one of a fixed few, and the only ones
# where "a string" is not enough: `density: "darkk"` would be stored, read
# back into the panel's picker as nothing, and quietly print at whatever
# the last good value was — a setting somebody believes they changed. The
# protocol refuses an unknown density outright, so a stored typo is also a
# print that fails rather than one that is merely wrong.
CHOICES: dict[str, tuple[str, ...]] = {
    "print_mode": ("standard", "compact", "bare"),
    "density": ("light", "medium", "normal", "dark"),
    "quality": ("text", "graphics"),
}


@dataclass
class SettingsStore:
    path: Path
    _values: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.load()

    def load(self) -> None:
        raw = atomic_write.read_json(self.path, {})
        self._values = raw if isinstance(raw, dict) else {}

    def save(self) -> None:
        atomic_write.write_json(self.path, self._values)

    def all(self) -> dict:
        return {**DEFAULTS, **self._values}

    def get(self, key: str, default: Any = None) -> Any:
        return self.all().get(key, DEFAULTS.get(key, default))

    def update(self, values: dict) -> dict:
        """Only known keys, and only values of the default's own type.

        An unknown key is dropped rather than stored: this file is read by
        the panel and by the HA bridge, and a typo'd key that persists is a
        setting somebody believes they changed. The type check is the same
        argument — `confirm_over_copies: "ten"` would compare against an int
        somewhere far from here — and so is `CHOICES`, for the keys where
        the set of legal strings is short and fixed.
        """
        for key, value in (values or {}).items():
            if key not in DEFAULTS:
                continue
            default = DEFAULTS[key]
            if isinstance(default, bool):
                self._values[key] = bool(value)
            elif isinstance(default, int):
                try:
                    self._values[key] = int(value)
                except (TypeError, ValueError):
                    continue
            elif key in CHOICES:
                text = str(value)
                if text not in CHOICES[key]:
                    continue
                self._values[key] = text
            else:
                self._values[key] = str(value)
        self.save()
        return self.all()
