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
import unittest.mock as mock

ROOT = Path(__file__).resolve().parent.parent
INTEGRATION = ROOT / "brain" / "custom_components" / "brain" / "morph"


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    return mod


def load(shared: Path, name: str = "lovelace"):
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
    saved = {k: sys.modules.get(k) for k in [*stubs, "mpkg", "mpkg.const", f"mpkg.{name}"]}
    try:
        sys.modules.update(stubs)
        pkg = types.ModuleType("mpkg")
        pkg.__path__ = [str(INTEGRATION)]
        sys.modules["mpkg"] = pkg
        sys.modules.pop("mpkg.const", None)
        sys.modules.pop(f"mpkg.{name}", None)
        const = importlib.import_module("mpkg.const")
        const.SHARED = shared
        mod = importlib.import_module(f"mpkg.{name}")
        if name == "lovelace":
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


class Bus:
    def __init__(self):
        self.fired, self.listeners = [], {}

    def async_fire(self, name, data=None):
        self.fired.append(name)
        for fn in self.listeners.get(name, []):
            fn(types.SimpleNamespace(data=data or {}))

    def async_listen(self, name, fn):
        self.listeners.setdefault(name, []).append(fn)
        return lambda: None


class Themes(unittest.TestCase):
    """themes.py: /config/morph/themes added to Home Assistant's themes, a
    change repainting every screen, and Home Assistant's own reload never
    leaving them out."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.th = load(root, "themes")
        self.dir = root / "themes"
        self.dir.mkdir()
        self.hass = types.SimpleNamespace(data={"frontend_themes": {"Theirs": {"primary-color": "red"}}}, bus=Bus())

    def test_the_shipped_themes_read(self):
        shipped = ROOT / "brain" / "morph" / "defaults" / "themes"
        themes, problems = self.th.read_themes(shipped)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(themes), ["Morph", "Morph Dark", "Morph Light", "Morph Medium"])
        self.assertEqual(sorted(themes["Morph"]["modes"]), ["dark", "light"])
        for t in (themes["Morph"]["modes"]["light"], themes["Morph"]["modes"]["dark"], themes["Morph Medium"], themes["Morph Light"], themes["Morph Dark"]):
            for var in ("primary-background-color", "card-background-color", "primary-text-color", "morph-rose"):
                self.assertIn(var, t)

    def test_a_bad_file_is_said_and_the_rest_load(self):
        (self.dir / "a.yaml").write_text("Warm:\n  primary-color: orange\n")
        (self.dir / "b.yaml").write_text("Broken: [\n")
        themes, problems = self.th.read_themes(self.dir)
        self.assertEqual(list(themes), ["Warm"])
        self.assertEqual(len(problems), 1)
        self.assertIn("b.yaml", problems[0])

    def test_added_beside_home_assistants_and_put_back_after_a_reload(self):
        self.hass.bus.async_listen("themes_updated", lambda e: (self.hass.data.setdefault("brain_morph", {}).get("themes_firing") or
                                                                self.th.inject(self.hass, self.hass.data["brain_morph"].get("themes") or {}, fire=False)))
        self.hass.data.setdefault("brain_morph", {})["themes"] = {"Morph": {"primary-color": "blue"}}
        self.th.inject(self.hass, {"Morph": {"primary-color": "blue"}}, fire=True)
        self.assertEqual(sorted(self.hass.data["frontend_themes"]), ["Morph", "Theirs"])
        self.assertEqual(self.hass.bus.fired, ["themes_updated"])
        # frontend.reload_themes: configuration.yaml's themes replace the dict.
        self.hass.data["frontend_themes"].clear()
        self.hass.data["frontend_themes"]["Theirs"] = {"primary-color": "green"}
        self.hass.bus.async_fire("themes_updated")
        self.assertEqual(sorted(self.hass.data["frontend_themes"]), ["Morph", "Theirs"])
        # A theme removed from the folder leaves Home Assistant too, and
        # never takes one of Home Assistant's own with it.
        self.th.inject(self.hass, {}, fire=True)
        self.assertEqual(sorted(self.hass.data["frontend_themes"]), ["Theirs"])


class Types(unittest.TestCase):
    """cardtypes.py: the folder read for the browser, and only code served."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.ct = load(root, "cardtypes")
        self.dir = root / "types"
        self.dir.mkdir()
        self.usage = root / "types-usage.json"
        self.cards = root / "cards"

    def read(self):
        return {r["slug"]: r for r in self.ct.read_all(self.dir, self.usage, self.cards)["types"]}

    def test_a_template_type_is_read_with_its_variables(self):
        (self.dir / "thermo.yaml").write_text(
            "name: Thermostat\nvariables:\n  - name: entity\n    required: true\n    selector: {entity: {}}\n"
            "  - name: type\n  - name: Bad Name\ncard:\n  type: thermostat\n  entity: '[[entity]]'\n")
        self.usage.write_text(json.dumps({"types": {"thermo": [{"dashboard": "default", "where": "Home"}]}}))
        row = self.read()["thermo"]
        self.assertEqual(row["kind"], "template")
        self.assertEqual(row["type"], "custom:morph-type-thermo")
        self.assertEqual([v["name"] for v in row["variables"]], ["entity"])
        self.assertEqual(row["card"]["entity"], "[[entity]]")
        self.assertEqual(len(row["used"]), 1)

    def test_what_is_wrong_with_a_type_is_said(self):
        (self.dir / "nocard.yaml").write_text("name: x\nkind: template\n")
        (self.dir / "nojs.yaml").write_text("name: y\nkind: element\n")
        (self.dir / "broken.yaml").write_text("name: [\n")
        rows = self.read()
        self.assertIn("needs `card:`", rows["nocard"]["error"])
        self.assertIn("types/nojs.js", rows["nojs"]["error"])
        self.assertIn("YAML", rows["broken"]["error"])

    def test_an_element_type_points_at_its_code_by_version(self):
        (self.dir / "pets.yaml").write_text("name: Pets\n")
        (self.dir / "pets.js").write_text("export default class extends HTMLElement {}")
        row = self.read()["pets"]
        self.assertEqual(row["kind"], "element")
        self.assertTrue(row["module"].startswith("/morph_types/pets.js?v="))

    def test_only_a_types_code_is_served(self):
        (self.dir / "pets.yaml").write_text("name: Pets\n")
        (self.dir / "pets.js").write_text("x")
        self.assertEqual(self.ct.module_path("pets.js", self.dir), self.dir / "pets.js")
        for name in ("pets.yaml", "../pets.js", "Pets.js", "missing.js", ".js"):
            self.assertIsNone(self.ct.module_path(name, self.dir), name)


if __name__ == "__main__":
    unittest.main()
