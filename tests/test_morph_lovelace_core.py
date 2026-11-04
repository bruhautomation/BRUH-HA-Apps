"""The Core half of Morph on Home Assistant dashboards
(custom_components/brain/morph/lovelace.py), driven against a stand-in for
Home Assistant's Lovelace storage: the mirror it writes, the configs it
saves for the service, the switch an administrator throws, and a YAML-mode
dashboard it refuses. Its config hash and the service's are held equal,
because the two halves compare them.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "brain" / "custom_components" / "brain" / "morph"


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    return mod


def load(shared: Path):
    """lovelace.py with just enough Home Assistant under it."""
    ident = lambda *a, **k: (lambda f: f) if not (len(a) == 1 and callable(a[0])) else a[0]  # noqa: E731
    ws = _stub("homeassistant.components.websocket_api", websocket_command=lambda schema: (lambda f: f),
               async_response=lambda f: f, require_admin=lambda f: f, async_register_command=lambda *a: None)
    stubs = {
        "voluptuous": _stub("voluptuous", Required=lambda k, **kw: k, Optional=lambda k, **kw: k),
        "homeassistant": _stub("homeassistant"),
        "homeassistant.components": _stub("homeassistant.components", websocket_api=ws),
        "homeassistant.components.websocket_api": ws,
        "homeassistant.core": _stub("homeassistant.core", HomeAssistant=object, callback=ident),
        "homeassistant.helpers": _stub("homeassistant.helpers"),
        "homeassistant.helpers.event": _stub("homeassistant.helpers.event",
                                             async_track_time_interval=lambda *a, **k: (lambda: None)),
    }
    saved = {k: sys.modules.get(k) for k in [*stubs, "mpkg", "mpkg.const", "mpkg.lovelace"]}
    try:
        sys.modules.update(stubs)
        pkg = types.ModuleType("mpkg")
        pkg.__path__ = [str(INTEGRATION)]
        sys.modules["mpkg"] = pkg
        sys.modules.pop("mpkg.const", None)
        sys.modules.pop("mpkg.lovelace", None)
        const = importlib.import_module("mpkg.const")
        const.SHARED = shared
        mod = importlib.import_module("mpkg.lovelace")
        mod.LL_DIR = shared / "lovelace"
        mod.APPLY_DIR = shared / "lovelace-apply"
        mod.MORPHED = mod.LL_DIR / "morphed.json"
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class Board:
    def __init__(self, cfg, mode="storage"):
        self.cfg, self.mode, self.saved = cfg, mode, []
        self.config = {"title": "Upstairs"} if cfg else None

    async def async_load(self, force):
        if self.cfg is None:
            raise LookupError("no config")
        return self.cfg

    async def async_save(self, cfg):
        self.saved.append(cfg)
        self.cfg = cfg


class Hass:
    def __init__(self, boards):
        self.data = {"lovelace": types.SimpleNamespace(dashboards=boards)}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class Core(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.shared = Path(self.tmp.name)
        self.ll = load(self.shared)
        self.cfg = {"views": [{"title": "Home", "cards": [{"type": "tile", "entity": "light.a"}]}]}
        self.boards = {None: Board(self.cfg), "upstairs": Board({"views": []}), "yamlboard": Board({"views": []}, "yaml")}
        self.hass = Hass(self.boards)

    def run_(self, coro):
        return asyncio.run(coro)

    def test_morphing_a_dashboard_lists_it_and_mirrors_it(self):
        out = self.run_(self.ll.set_morphed(self.hass, "default", True))
        self.assertEqual(out, {"ok": True, "morphed": True})
        self.assertEqual(self.ll.read_morphed(), ["default"])
        row = json.loads((self.shared / "lovelace" / "default.json").read_text())
        self.assertEqual(row["config"], self.cfg)
        self.assertEqual(row["hash"], self.ll.config_hash(self.cfg))
        rows = {d["key"]: d for d in self.ll.describe(self.hass)}
        self.assertTrue(rows["default"]["morphed"])
        self.assertFalse(rows["upstairs"]["morphed"])
        self.assertEqual(rows["upstairs"]["title"], "Upstairs")

    def test_a_yaml_dashboard_cannot_be_morphed(self):
        out = self.run_(self.ll.set_morphed(self.hass, "yamlboard", True))
        self.assertFalse(out["ok"])
        self.assertIn("YAML", out["error"])
        self.assertEqual(self.ll.read_morphed(), [])

    def test_apply_saves_through_home_assistant_and_only_a_morphed_one(self):
        self.run_(self.ll.set_morphed(self.hass, "default", True))
        new = {"views": [{"title": "Home", "cards": []}]}
        (self.shared / "lovelace-apply").mkdir()
        (self.shared / "lovelace-apply" / "default.json").write_text(json.dumps({"key": "default", "config": new}))
        (self.shared / "lovelace-apply" / "upstairs.json").write_text(json.dumps({"key": "upstairs", "config": new}))
        done = self.run_(self.ll.apply_pending(self.hass))
        self.assertEqual(done, ["default"])
        self.assertEqual(self.boards[None].saved, [new])
        self.assertEqual(self.boards["upstairs"].saved, [])
        self.assertEqual(list((self.shared / "lovelace-apply").glob("*.json")), [])
        self.assertEqual(json.loads((self.shared / "lovelace" / "default.json").read_text())["config"], new)

    def test_a_dashboard_with_nothing_stored_mirrors_as_none(self):
        self.boards["fresh-one"] = Board(None)
        self.run_(self.ll.set_morphed(self.hass, "fresh-one", True))
        row = json.loads((self.shared / "lovelace" / "fresh-one.json").read_text())
        self.assertIsNone(row["config"])

    def test_both_halves_hash_alike(self):
        with mock.patch.dict(sys.modules):
            from morph_env import MorphEnv
            with MorphEnv() as env:
                cfg = {"b": [1, "é"], "a": {"z": None}}
                self.assertEqual(env.lovelace.config_hash(cfg), self.ll.config_hash(cfg))


if __name__ == "__main__":
    unittest.main()
