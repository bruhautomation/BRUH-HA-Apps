"""The Usage tracker diagnostic sensor says what is wrong in words.

Its state is the tracker's own vocabulary (`http_429`,
`oauth_token_awaiting_refresh`, `oauth_token_lacks_usage_scope`…), which is
right for an automation and wrong for somebody reading a device page: a raw
code in the UI is a code they then go and search for. Home Assistant's
answer is an ENUM sensor with a `translation_key` — the stored state stays
the code, and the frontend shows the translation — which is what
`BrainStatusSensor` already does.

Three things this holds:

  * the VALUES do not move: every code the tracker can write is an option,
    read out of the tracker and `usage_store` rather than written down a
    second time here;
  * a code the vocabulary does not know is `other`, with the raw code kept
    in the `code` attribute — an enum state outside `options` is an error
    in Home Assistant, and a sensor whose job is to be readable when the
    others are not must not fail to write;
  * a core with no ENUM device class gets the raw code exactly as before.

The platform imports Home Assistant at module level, so it is loaded
behind stubs (`test_numbers_agree`'s arrangement), with `sys.modules` put
back as it was found.
"""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import re
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CC = REPO / "brain" / "custom_components" / "brain"
TRACKER = REPO / "brain" / "scripts" / "usage-limits-tracker.py"
USAGE_STORE = REPO / "brain" / "panel" / "usage_store.py"


class _AutoModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


def _import_sensor(with_enum: bool):
    """`sensor.py` behind permissive stubs, `sys.modules` put back after."""
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
        sensor_mod = sys.modules["homeassistant.components.sensor"]
        sensor_mod.SensorEntity = type("SensorEntity", (), {})
        classes = {"TIMESTAMP": "timestamp"}
        if with_enum:
            classes["ENUM"] = "enum"
        sensor_mod.SensorDeviceClass = type("SensorDeviceClass", (), classes)
        sys.modules["homeassistant.core"].callback = lambda func: func
        sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = \
            lambda **kw: dict(kw)
        pkg_name = f"brain_tracker_cc_{'enum' if with_enum else 'old'}"
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(CC)]
        sys.modules[pkg_name] = pkg
        return importlib.import_module(f"{pkg_name}.sensor")
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    saved = dict(sys.modules)
    try:
        sys.path.insert(0, str(path.parent))
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
        sys.modules.clear()
        sys.modules.update(saved)
    return module


def tracker_vocabulary() -> set[str]:
    """Every status the tracker and the panel's reader can write or report.

    Read off the two modules that own it: the tracker's named tables and
    the literal codes its failure paths return, and `usage_store`'s
    `NEEDS_NOTHING` and the two codes `limits_problem` answers with. The
    sensor's own three (`ok`, `stale`, `not_running`) are added by the
    test, because they are the sensor's and nobody else's.
    """
    tracker = _load(TRACKER, "usage_tracker_vocab")
    codes: set[str] = set()
    codes.update(tracker.AUTH_PROBLEMS)
    codes.update(tracker.ERROR_DETAIL)
    codes.update(tracker.CREDENTIAL_REFUSALS)
    codes.update(tracker.API_ERROR_CODES.values())
    codes.update(tracker.MASKED_BY_REFRESH)
    codes.add(tracker.SCOPE_ERROR)
    codes.add(tracker.REFRESH_PENDING)
    src = TRACKER.read_text()
    # `return None, "network_error"`, `error or "tracker_error"`,
    # `success, error = False, "tracker_error"`, `return "no_oauth_token"`.
    for pattern in (r'return None, "([a-z0-9_]+)"',
                    r'error or "([a-z0-9_]+)"',
                    r'False, "([a-z0-9_]+)"',
                    r'return "([a-z0-9_]+)"\s*$'):
        codes.update(re.findall(pattern, src, flags=re.M))
    store_src = USAGE_STORE.read_text()
    tree_codes = re.findall(r'\{"code": "([a-z_]+)"\}', store_src)
    codes.update(tree_codes)
    store = _load(USAGE_STORE, "usage_store_vocab")
    codes.update(store.NEEDS_NOTHING)
    codes.update(store.STUCK_AFTER)
    return codes


class FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _iso(seconds_ago: float = 0) -> str:
    return datetime.fromtimestamp(time.time() - seconds_ago,
                                  timezone.utc).isoformat()


class TheVocabulary(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sensor = _import_sensor(with_enum=True)

    def test_the_vocabulary_read_off_the_tracker_is_not_empty(self):
        codes = tracker_vocabulary()
        for code in ("http_429", "oauth_token_awaiting_refresh",
                     "oauth_token_lacks_usage_scope", "network_error",
                     "no_oauth_token", "api_key_has_no_usage_limits",
                     "http_401", "http_403", "invalid_response",
                     "tracker_error", "not_running", "stale"):
            self.assertIn(code, codes)

    def test_every_code_the_tracker_can_write_is_an_option(self):
        options = set(self.sensor.USAGE_TRACKER_STATES)
        wanted = tracker_vocabulary() | {"ok", "stale", "not_running"}
        self.assertEqual(wanted - options, set())

    def test_there_is_a_word_for_a_code_nobody_listed(self):
        self.assertIn("other", self.sensor.USAGE_TRACKER_STATES)

    def test_every_option_has_words_in_both_string_files(self):
        for path in (CC / "strings.json", CC / "translations" / "en.json"):
            data = json.loads(path.read_text())
            entry = data["entity"]["sensor"]["usage_tracker"]
            states = entry["state"]
            self.assertEqual(set(states), set(self.sensor.USAGE_TRACKER_STATES),
                             path.name)
            for code, words in states.items():
                self.assertTrue(words.strip(), f"{path.name}: {code}")
                self.assertNotEqual(words, code,
                                    f"{path.name}: {code} is not in words")
            self.assertEqual(entry["name"], "Usage tracker")

    def test_the_two_string_files_agree(self):
        a = json.loads((CC / "strings.json").read_text())["entity"]
        b = json.loads((CC / "translations" / "en.json").read_text())["entity"]
        self.assertEqual(a, b)


class TheSensor(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "usage_limits.json"

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, with_enum=True):
        sensor = _import_sensor(with_enum=with_enum)
        entity = sensor.BrainUsageTrackerSensor(None, str(self.path))
        entity.hass = FakeHass()
        return sensor, entity

    def read(self, entity, payload):
        if payload is not None:
            self.path.write_text(json.dumps(payload))
        asyncio.run(entity.async_update())
        return entity._attr_native_value, entity.extra_state_attributes

    def test_it_is_an_enum_with_a_translation_key(self):
        sensor, entity = self.make()
        self.assertEqual(entity._attr_device_class, "enum")
        self.assertEqual(entity._attr_options,
                         list(sensor.USAGE_TRACKER_STATES))
        self.assertEqual(entity._attr_translation_key, "usage_tracker")
        # The name stays what it was, so nobody's entity id moves.
        self.assertEqual(entity._attr_name, "Usage tracker")
        self.assertEqual(entity._attr_unique_id, "brain_usage_tracker_status")

    def test_the_values_do_not_move(self):
        _sensor, entity = self.make()
        for code in ("http_429", "oauth_token_awaiting_refresh",
                     "oauth_token_lacks_usage_scope", "network_error"):
            state, attrs = self.read(entity, {"error": code,
                                              "updated_at": _iso()})
            self.assertEqual(state, code)
            self.assertEqual(attrs["code"], code)
        state, attrs = self.read(entity, {"updated_at": _iso(),
                                          "five_hour": {}})
        self.assertEqual(state, "ok")
        state, attrs = self.read(entity, {"updated_at": _iso(5 * 3600),
                                          "last_error": "http_429"})
        self.assertEqual(state, "http_429")
        state, attrs = self.read(entity, {"updated_at": _iso(5 * 3600)})
        self.assertEqual(state, "stale")

    def test_no_file_is_not_running(self):
        _sensor, entity = self.make()
        state, attrs = self.read(entity, None)
        self.assertEqual(state, "not_running")
        self.assertEqual(attrs["code"], "not_running")
        self.assertIn("detail", attrs)

    def test_a_code_nobody_listed_is_other_and_keeps_its_code(self):
        sensor, entity = self.make()
        for code in ("http_418", "{'type': 'weird'}", "brand_new_reason"):
            state, attrs = self.read(entity, {"error": code,
                                              "updated_at": _iso()})
            self.assertEqual(state, "other", code)
            self.assertIn(state, entity._attr_options)
            self.assertEqual(attrs["code"], code)
        # A stale reading with an unlisted reason, too.
        state, attrs = self.read(entity, {"updated_at": _iso(5 * 3600),
                                          "last_error": "http_418"})
        self.assertEqual(state, "other")
        self.assertEqual(attrs["code"], "http_418")

    def test_a_core_without_enum_gets_the_raw_code_as_before(self):
        _sensor, entity = self.make(with_enum=False)
        self.assertIsNone(getattr(entity, "_attr_options", None))
        state, attrs = self.read(entity, {"error": "http_418",
                                          "updated_at": _iso()})
        self.assertEqual(state, "http_418")
        state, _ = self.read(entity, {"error": "http_429",
                                      "updated_at": _iso()})
        self.assertEqual(state, "http_429")


if __name__ == "__main__":
    unittest.main()
