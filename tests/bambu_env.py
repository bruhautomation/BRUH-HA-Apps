"""Importing BRUH Bambu Studio's panel without inheriting another add-on's.

Every panel here has a top-level `server` and an `atomic_write`, and each is
imported by putting its own `panel/` on `sys.path` — fine in each add-on's
process, a collision under one test interpreter. `bruh_print_env`'s fix:
purge the colliding names, import ours, then put the module table back.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys

PANEL = os.path.join(os.path.dirname(__file__), "..", "bruh-bambu-studio", "panel")
SHARED = ("server", "atomic_write", "store", "library", "installer", "slicer",
          "studio", "vnc_bridge", "bambu")


def _ours(name: str) -> bool:
    return name in SHARED or name.split(".", 1)[0] in SHARED


@contextlib.contextmanager
def panel_path():
    saved = {n: sys.modules[n] for n in list(sys.modules) if _ours(n)}
    for name in saved:
        del sys.modules[name]
    sys.path.insert(0, os.path.abspath(PANEL))
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(os.path.abspath(PANEL))
        for name in [n for n in list(sys.modules) if _ours(n)]:
            del sys.modules[name]
        sys.modules.update(saved)


def load(*names):
    """Import panel modules by name, isolated, in the order asked for."""
    with panel_path():
        return tuple(importlib.import_module(name) for name in names)
