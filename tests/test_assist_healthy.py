#!/usr/bin/env python3
"""`binary_sensor.brain_assist_healthy` follows whether voice is answering.

A real house showed it `on` while the add-on's Assist was down. What it
read: the pool's `/health`, which the pool's HTTP thread answers `ok`
whether or not the loop that claims Assist's requests is still going
round, and failing that the heartbeat file judged by a stamp INSIDE it —
a corrected clock leaves that stamp in the future and the sensor reads on
for ever. And a classic-listener house never saw it at all: it was
unavailable with no reason, which hides its attributes.

The rule now lives in `assist_health.py`, which imports nothing from Home
Assistant so it is driven here directly, and the entity is driven through
permissive stubs that put `sys.modules` back.
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
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(INTEGRATION_DIR))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import assist_health  # noqa: E402
import health  # noqa: E402

NOW = 1_700_000_000.0
FAST = {"enable_assist_integration": True, "assist_fast_mode": True}
CLASSIC = {"enable_assist_integration": True, "assist_fast_mode": False}


def mirror(options, daemons, problems=()):
    return {"options": options, "daemons": daemons,
            "health": {"state": "failed" if problems else "ok",
                       "problems": list(problems), "stale_after_h": 2.5}}


class TestTheRule(unittest.TestCase):
    def judge(self, **kw):
        kw.setdefault("now", NOW)
        return assist_health.judge(**kw)

    def test_a_pool_that_answers_and_goes_round_is_on(self):
        on, attrs = self.judge(http={"status": "ok", "workers": 0,
                                     "loop_age_s": 12})
        self.assertIs(on, True)
        self.assertEqual(attrs["transport"], "http")

    def test_an_http_answer_from_a_loop_that_stopped_is_off(self):
        # The HTTP thread answers `ok` while the main loop is wedged.
        on, attrs = self.judge(http={"status": "ok", "loop_age_s": 900})
        self.assertIs(on, False)
        self.assertIn("minutes", attrs["reason"])

    def test_a_pool_that_says_stalled_is_off(self):
        on, _ = self.judge(http={"status": "stalled", "loop_age_s": 900})
        self.assertIs(on, False)

    def test_the_heartbeat_is_aged_by_the_file_not_the_stamp_inside(self):
        # A stamp from the future (a clock corrected backwards) used to
        # read as fresh for ever.
        future = {"status": "ok", "ts": NOW + 86400, "workers": 0}
        on, attrs = self.judge(heartbeat=future, heartbeat_age_s=900)
        self.assertIs(on, False)
        self.assertEqual(attrs["transport"], "file")
        on, _ = self.judge(heartbeat=future, heartbeat_age_s=20)
        self.assertIs(on, True)

    def test_the_panel_saying_voice_is_down_turns_it_off(self):
        down = mirror(FAST, {"assist_worker_pool": {"running": False},
                             "assist_listener": {"running": False}},
                      [{"id": "assist", "what": "nothing is listening for voice"}])
        on, attrs = self.judge(heartbeat={"status": "ok"}, heartbeat_age_s=20,
                               mirror=down, mirror_age_h=0.1)
        self.assertIs(on, False)
        self.assertEqual(attrs["reason"], "nothing is listening for voice")

    def test_a_stale_mirror_says_nothing_about_voice(self):
        down = mirror(FAST, {}, [{"id": "assist", "what": "x"}])
        on, _ = self.judge(heartbeat={"status": "ok"}, heartbeat_age_s=20,
                           mirror=down, mirror_age_h=9)
        self.assertIs(on, True)

    def test_a_classic_listener_that_runs_is_on(self):
        m = mirror(CLASSIC, {"assist_listener": {"running": True},
                             "assist_worker_pool": {"running": False}})
        on, attrs = self.judge(mirror=m, mirror_age_h=0.1)
        self.assertIs(on, True)
        self.assertEqual(attrs["transport"], "listener")

    def test_a_classic_listener_that_stopped_is_off(self):
        m = mirror(CLASSIC, {"assist_listener": {"running": False},
                             "assist_worker_pool": {"running": False}})
        on, attrs = self.judge(mirror=m, mirror_age_h=0.1)
        self.assertIs(on, False)
        self.assertTrue(attrs["reason"])

    def test_assist_switched_off_is_unknown_with_the_reason(self):
        m = mirror({"enable_assist_integration": False}, {
            "assist_listener": {"running": False}})
        on, attrs = self.judge(mirror=m, mirror_age_h=0.1)
        self.assertIsNone(on)
        self.assertIn("switched off", attrs["reason"])

    def test_nothing_to_read_is_unknown_with_a_reason_never_on(self):
        on, attrs = self.judge()
        self.assertIsNone(on)
        self.assertTrue(attrs["reason"])

    def test_the_window_is_the_panels(self):
        self.assertEqual(assist_health.HEARTBEAT_FRESH_S,
                         health.POOL_HEARTBEAT_STALE_S)


class _AutoModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


def _import_binary_sensor():
    saved = dict(sys.modules)
    try:
        for name in ("homeassistant", "homeassistant.components",
                     "homeassistant.components.binary_sensor",
                     "homeassistant.config_entries", "homeassistant.core",
                     "homeassistant.helpers",
                     "homeassistant.helpers.device_registry",
                     "homeassistant.helpers.entity_platform"):
            sys.modules[name] = _AutoModule(name)
        sys.modules["homeassistant.components.binary_sensor"]\
            .BinarySensorEntity = type("BinarySensorEntity", (), {})
        sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = \
            lambda **kw: dict(kw)
        pkg = types.ModuleType("brain_assist_cc")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_assist_cc"] = pkg
        return importlib.import_module("brain_assist_cc.binary_sensor")
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


class TestTheEntity(unittest.TestCase):
    """The real entity over real files."""

    @classmethod
    def setUpClass(cls):
        cls.bs = _import_binary_sensor()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".brain" / "cache").mkdir(parents=True)
        root = self.root

        class Config:
            def path(self, *parts):
                return str(root.joinpath(*parts))

        class Hass:
            config = Config()

            async def async_add_executor_job(self, func, *args):
                return func(*args)

        class Bridge:
            answer = None

            async def async_api_health(self):
                return self.answer

        self.bridge = Bridge()
        self.sensor = self.bs.BruhClaudeHealthSensor(None, self.bridge)
        self.sensor.hass = Hass()

    def tearDown(self):
        self.tmp.cleanup()

    def heartbeat(self, age_s):
        path = self.root / ".brain" / "cache" / "pool_status.json"
        path.write_text(json.dumps({"status": "ok", "ts": time.time() + 86400,
                                    "workers": 0}))
        t = time.time() - age_s
        os.utime(path, (t, t))

    def diagnostics(self, payload, age_s=10):
        path = self.root / ".brain" / "diagnostics.json"
        path.write_text(json.dumps(payload))
        t = time.time() - age_s
        os.utime(path, (t, t))

    def test_it_never_hides_behind_unavailable(self):
        asyncio.run(self.sensor.async_update())
        self.assertTrue(self.sensor.available)
        self.assertIsNone(self.sensor._attr_is_on)
        self.assertTrue(self.sensor.extra_state_attributes.get("reason"))

    def test_a_stale_heartbeat_with_a_stamp_from_the_future_is_off(self):
        self.heartbeat(900)
        asyncio.run(self.sensor.async_update())
        self.assertIs(self.sensor._attr_is_on, False)

    def test_the_panels_verdict_turns_it_off(self):
        self.heartbeat(10)
        self.diagnostics(mirror(FAST, {"assist_worker_pool": {"running": True,
                                                              "heartbeat_age_s": 900}},
                                [{"id": "assist_pool",
                                  "what": "the voice worker pool has stopped answering"}]))
        asyncio.run(self.sensor.async_update())
        self.assertIs(self.sensor._attr_is_on, False)
        self.assertIn("stopped answering",
                      self.sensor.extra_state_attributes["reason"])

    def test_a_live_answer_is_on(self):
        self.bridge.answer = {"status": "ok", "workers": 0, "loop_age_s": 5}
        asyncio.run(self.sensor.async_update())
        self.assertIs(self.sensor._attr_is_on, True)
        self.assertEqual(self.sensor.extra_state_attributes["workers"], 0)


class TestThePoolSaysWhenItsLoopStopped(unittest.TestCase):
    """The pool's HTTP thread answered `ok` whatever its main loop was
    doing. `/health` and the heartbeat now carry how long ago that loop
    went round, and `/health` says `stalled` past the window."""

    def setUp(self):
        import importlib.util
        import uuid
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        env = {"BRAIN_SHARED_DIR": str(tmp / "shared"),
               "BRAIN_ASSIST_WORKDIR": str(tmp),
               "BRAIN_ENV_FILE": str(tmp / "brain_env"),
               "BRAIN_JOURNAL_FILE": str(tmp / "journal.jsonl"),
               "BRAIN_USAGE_NUDGE": str(tmp / "usage-nudge")}
        self._env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        spec = importlib.util.spec_from_file_location(
            f"assist_pool_{uuid.uuid4().hex}",
            BASE_DIR / "brain" / "integrations" / "assist-worker-pool.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)
        os.makedirs(self.mod.CACHE_DIR, exist_ok=True)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_a_loop_that_has_not_gone_round_is_stalled(self):
        pool = self.mod.Pool()
        self.assertEqual(self.mod.health_status(pool)["status"], "ok")
        pool.loop_at = time.time() - 900
        got = self.mod.health_status(pool)
        self.assertEqual(got["status"], "stalled")
        self.assertGreaterEqual(got["loop_age_s"], 900)
        self.mod.write_pool_status(pool)
        beat = json.loads(Path(self.mod.POOL_STATUS_FILE).read_text())
        self.assertEqual(beat["status"], "stalled")

    def test_the_pools_window_is_the_sensors(self):
        self.assertEqual(self.mod.LOOP_STALL_S, assist_health.HEARTBEAT_FRESH_S)


if __name__ == "__main__":
    unittest.main()
