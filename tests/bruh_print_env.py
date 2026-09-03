"""Importing BRUH Print's panel without inheriting BRight's.

Both panels have a top-level `stores` package, and both are imported by
putting their own `panel/` directory on `sys.path` — which is fine for each
add-on's own process and a collision under `unittest discover`, where one
interpreter loads both. Whichever imports first wins the shared module table,
and the loser gets `ImportError: cannot import name 'history' from 'stores'`
about a module that is perfectly fine.

Same class of bug as `test_power_tools_device_cycles.py`'s, and the same fix:
purge the colliding names, import ours, then **put the table back** so a test
module that imported BRight's first still has it. Our own objects hold direct
references to what they imported, so restoring the table cannot reach them.
"""
from __future__ import annotations

import contextlib
import os
import sys

PANEL = os.path.join(os.path.dirname(__file__), "..", "bruh-print", "panel")

# The names both panels claim. `server` is the big one — every add-on here
# has one — and `stores` is the one that actually bit.
SHARED = ("server", "stores", "render", "dymo", "atomic_write", "panel_port")


@contextlib.contextmanager
def panel_path():
    """Our panel first, and the module table restored on the way out."""
    saved = {name: sys.modules[name] for name in list(sys.modules)
             if name in SHARED or name.split(".", 1)[0] in SHARED}
    for name in saved:
        del sys.modules[name]
    sys.path.insert(0, os.path.abspath(PANEL))
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(os.path.abspath(PANEL))
        for name in [n for n in list(sys.modules)
                     if n in SHARED or n.split(".", 1)[0] in SHARED]:
            del sys.modules[name]
        sys.modules.update(saved)


def load(*names):
    """Import BRUH Print panel modules by name, isolated.

    Returns them in the order asked for, so a caller writes

        protocol, printers = bruh_print_env.load("dymo.protocol",
                                                 "dymo.printers")
    """
    import importlib

    with panel_path():
        return tuple(importlib.import_module(name) for name in names)
