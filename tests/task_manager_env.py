"""Importing BRUH Task Manager's panel without inheriting another add-on's.

Every panel here is imported by putting its own `panel/` on `sys.path`, and
several share module names (`server` above all), so one interpreter running
the whole suite would hand whichever was imported first to everybody. Same
fix as `bruh_print_env`: purge the names, import ours, put the table back.
Our modules keep direct references to what they imported, so restoring the
table cannot reach them.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys

PANEL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..",
                                     "bruh-task-manager", "panel"))
TESTS = os.path.abspath(os.path.dirname(__file__))

SHARED = ("server", "apps", "settings", "procs", "policy", "ending",
          "machine", "runaway")


@contextlib.contextmanager
def panel_path():
    saved = {name: sys.modules[name] for name in list(sys.modules)
             if name.split(".", 1)[0] in SHARED}
    for name in saved:
        del sys.modules[name]
    sys.path.insert(0, PANEL)
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(PANEL)
        for name in [n for n in list(sys.modules) if n.split(".", 1)[0] in SHARED]:
            del sys.modules[name]
        sys.modules.update(saved)


def load(*names):
    """Import panel modules by name, isolated; returned in the order asked."""
    with panel_path():
        return tuple(importlib.import_module(name) for name in names)


def fake():
    """The fake machine and Supervisor (tests/task_manager_fake.py)."""
    if TESTS not in sys.path:
        sys.path.insert(0, TESTS)
    return importlib.import_module("task_manager_fake")
