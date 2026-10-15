"""Load Morph's service modules against a scratch /config and /data.

Morph's service is a directory of flat modules (``paths``, ``store``,
``brain``…) that import each other by bare name and read their paths from
the environment at import time. So a test points the environment at a
temporary tree, imports the modules fresh, and puts ``sys.modules`` and
``sys.path`` back afterwards: several of those bare names are common enough
that another add-on's tests could hold a module under the same one.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

SERVICE = Path(__file__).resolve().parent.parent / "morph" / "service"
FRONTEND = SERVICE.parent / "custom_components" / "morph" / "frontend"
MODULES = ("paths", "morphcode", "store", "gitrepo", "generator", "brain", "settings",
           "tell", "converse", "learning", "devloop", "ha", "morphd")


class MorphEnv:
    """``with MorphEnv() as env: env.store.normalize(...)``"""

    def __init__(self, **options: str):
        self.options = options

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.root = root
        self.morph_dir = root / "config" / "morph"
        self.shared = root / "config" / ".morph"
        self.data = root / "data"
        self.brain_shared = root / "config" / ".brain"
        for d in (self.morph_dir, self.shared, self.data):
            d.mkdir(parents=True)
        # Morph's own panel modules, as Home Assistant serves them; a copy,
        # so a test can play an update by changing one.
        self.shipped = root / "config" / "custom_components" / "morph" / "frontend"
        shutil.copytree(FRONTEND, self.shipped)
        env = {
            "MORPH_DIR": str(self.morph_dir),
            "MORPH_SHARED": str(self.shared),
            "MORPH_DATA": str(self.data),
            "MORPH_BRAIN_SHARED": str(self.brain_shared),
            "MORPH_BRAIN_UID": str(os.getuid()),
            "MORPH_SHIPPED": str(self.shipped),
            "GIT_CONFIG_GLOBAL": str(root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        env.update(self.options)
        self._env = mock.patch.dict(os.environ, env)
        self._env.start()
        self._saved = {n: sys.modules.pop(n) for n in MODULES if n in sys.modules}
        sys.path.insert(0, str(SERVICE))
        for name in MODULES:
            if name == "morphd":
                continue
            setattr(self, name, importlib.import_module(name))
        return self

    def brain_on(self) -> None:
        """brAIn's automation listener made its task folder."""
        (self.brain_shared / "tasks").mkdir(parents=True, exist_ok=True)
        (self.brain_shared / "task_results").mkdir(parents=True, exist_ok=True)

    def __exit__(self, *exc):
        for name in MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(self._saved)
        try:
            sys.path.remove(str(SERVICE))
        except ValueError:
            pass  # a test removed it already; there is nothing left to undo
        self._env.stop()
        self._tmp.cleanup()
        return False
