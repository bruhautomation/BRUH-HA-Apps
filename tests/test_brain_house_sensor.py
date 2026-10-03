#!/usr/bin/env python3
"""`sensor.brain_house`: never unavailable, and a stale reading is `unknown`.

Two halves. `house_state.read` is the whole decision and imports nothing
from Home Assistant, so it is driven directly over files the add-on's own
`situation.publish` wrote — the writer and the reader are different
processes, and a shape written down twice is a shape that drifts. Then the
real `BrainHouseSensor` is imported behind permissive stubs and updated
against a fake `hass`, because a reader that works and an entity that
forgets to call it are different claims.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(PANEL_DIR))

import situation  # noqa: E402


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"house_state_under_test_{name}", INTEGRATION_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


house_state = _load("house_state")


class _AutoModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


def _import_sensor():
    """`sensor.py` behind stubs, with `sys.modules` put back as found."""
    saved = dict(sys.modules)
    try:
        for name in ("homeassistant", "homeassistant.components",
                     "homeassistant.components.sensor",
                     "homeassistant.config_entries", "homeassistant.const",
                     "homeassistant.core", "homeassistant.helpers",
                     "homeassistant.helpers.issue_registry",
                     "homeassistant.helpers.device_registry",
                     "homeassistant.helpers.entity_platform",
                     "homeassistant.helpers.dispatcher"):
            sys.modules[name] = _AutoModule(name)
        # A real base class: a MagicMock instance cannot be subclassed.
        sys.modules["homeassistant.components.sensor"].SensorEntity = type(
            "SensorEntity", (), {})
        sys.modules["homeassistant.core"].callback = lambda func: func
        pkg = types.ModuleType("brain_house_cc")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_house_cc"] = pkg
        return importlib.import_module("brain_house_cc.sensor")
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


class TestTheReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        self.path = self.root / "config" / ".brain" / "situation.json"

    def tearDown(self):
        self.tmp.cleanup()

    def publish(self, **read):
        body = {"house_mode": "away", "sentence": "Nobody is home.",
                "sentence_stale": False, "rooms_in_use": [],
                "unusual_together": [], "because": "both phones out",
                "reason": "", "source": "model", "generated_at": 1,
                "stale_after_s": situation.MIRROR_STALE_S,
                "occasions": ["Mum staying (Fri 9 Oct – Sun 11 Oct)"], **read}
        self.assertTrue(situation.publish(body, self.path))

    def test_a_fresh_reading_is_the_mode(self):
        self.publish()
        state, attrs = house_state.read(str(self.path))
        self.assertEqual(state, "away")
        self.assertEqual(attrs["sentence"], "Nobody is home.")
        self.assertEqual(attrs["because"], "both phones out")
        self.assertEqual(attrs["coming_up"],
                         ["Mum staying (Fri 9 Oct – Sun 11 Oct)"])

    def test_a_stale_file_is_unknown_never_the_last_mode(self):
        self.publish()
        old = time.time() - situation.MIRROR_STALE_S - 120
        os.utime(self.path, (old, old))
        state, attrs = house_state.read(str(self.path))
        self.assertEqual(state, "unknown")
        self.assertIn("not running", attrs["reason"])
        self.assertTrue(attrs["sentence_stale"])

    def test_the_window_comes_out_of_the_file(self):
        self.publish(stale_after_s=60)
        old = time.time() - 120
        os.utime(self.path, (old, old))
        self.assertEqual(house_state.read(str(self.path))[0], "unknown")

    def test_a_stamp_in_the_future_cannot_keep_it_fresh(self):
        """The age is the file's mtime and never a stamp inside it."""
        self.publish(generated_at=int(time.time() + 86400))
        old = time.time() - situation.MIRROR_STALE_S - 120
        os.utime(self.path, (old, old))
        self.assertEqual(house_state.read(str(self.path))[0], "unknown")

    def test_nothing_published_and_garbage_are_unknown_with_a_reason(self):
        state, attrs = house_state.read(str(self.path))
        self.assertEqual(state, "unknown")
        self.assertIn("not published", attrs["reason"])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("[1, 2]")
        self.assertEqual(house_state.read(str(self.path))[0], "unknown")
        self.publish(house_mode="partying")
        self.assertEqual(house_state.read(str(self.path))[0], "unknown")

    def test_the_add_ons_own_vocabulary_is_the_sensors(self):
        self.assertEqual(tuple(house_state.MODES), tuple(situation.MODES))
        self.assertEqual(house_state.SITUATION_FILENAME,
                         situation.MIRROR.name)


class TestTheEntity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sensor = _import_sensor()

    def test_it_reads_the_mirror_and_never_goes_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".brain").mkdir()

            class Config:
                def path(self, *parts):
                    return str(root.joinpath(*parts))

            class Hass:
                config = Config()

                async def async_add_executor_job(self, func, *args):
                    return func(*args)

            entity = self.sensor.BrainHouseSensor(None)
            entity.hass = Hass()
            asyncio.run(entity.async_update())
            self.assertEqual(entity._attr_native_value, "unknown")
            self.assertIn("reason", entity.extra_state_attributes)
            self.assertFalse(hasattr(entity, "available")
                             and entity.available is False)
            (root / ".brain" / "situation.json").write_text(json.dumps({
                "house_mode": "home", "sentence": "The lounge TV is on.",
                "stale_after_s": 1200}))
            asyncio.run(entity.async_update())
            self.assertEqual(entity._attr_native_value, "home")
            self.assertEqual(entity.extra_state_attributes["sentence"],
                             "The lounge TV is on.")
            self.assertEqual(entity._attr_unique_id, "brain_house")

    def test_setup_adds_it(self):
        """The registration is one line in a function this suite cannot
        call without the integration's whole package; it is read, and the
        class above is what is driven."""
        import ast
        tree = ast.parse((INTEGRATION_DIR / "sensor.py").read_text())
        setup = next(n for n in tree.body
                     if isinstance(n, ast.AsyncFunctionDef)
                     and n.name == "async_setup_entry")
        names = {n.func.id for n in ast.walk(setup)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("BrainHouseSensor", names)


if __name__ == "__main__":
    unittest.main()
