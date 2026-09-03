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
    "quick_uppercase": False,
    "quick_rotate_narrow": True,
    "preview_scale": 2,
    "confirm_over_copies": 10,
    "notify_service": "",
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
        somewhere far from here.
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
            else:
                self._values[key] = str(value)
        self.save()
        return self.all()
