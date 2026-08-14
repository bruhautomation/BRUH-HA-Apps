#!/usr/bin/env python3
"""The findings mirror, read from the Home Assistant side.

The add-on republishes /config/.brain/findings_state.json on every change
(tests/test_findings.py pins that half); this file pins the consumer — the
integration's ``FindingsWatcher`` — because its one job is subtle in the
same way LearningWatcher's is: fire a ``brain_finding`` event for each NEW
finding and for nothing else. A watcher that replays the open list on every
HA restart turns "brAIn found something" automations into a 3am alarm test.

``findings.py`` only imports ``homeassistant.core`` and its own ``const``,
so it is imported here through a stub package that skips the integration's
heavyweight ``__init__``.
"""

import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"

# A dummy parent package pointing at the integration directory: importing
# `brain_cc.findings` then resolves `.const` without ever executing the real
# package __init__ (which imports the whole HA helper surface).
if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
if "homeassistant.core" not in sys.modules:
    core = types.ModuleType("homeassistant.core")

    class _HomeAssistant:
        pass

    core.HomeAssistant = _HomeAssistant
    sys.modules["homeassistant.core"] = core

_pkg = types.ModuleType("brain_cc")
_pkg.__path__ = [str(INTEGRATION_DIR)]
sys.modules.setdefault("brain_cc", _pkg)
findings = importlib.import_module("brain_cc.findings")


class _Bus:
    def __init__(self):
        self.fired: list[tuple[str, dict]] = []

    def async_fire(self, event: str, data: dict) -> None:
        self.fired.append((event, data))


class _Config:
    def __init__(self, base: str):
        self._base = base

    def path(self, *parts: str) -> str:
        return str(Path(self._base, *parts))


class _Hass:
    def __init__(self, base: str):
        self.config = _Config(base)
        self.bus = _Bus()

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class WatcherCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hass = _Hass(self.tmp.name)
        self.state_path = Path(self.tmp.name) / ".brain" / "findings_state.json"
        self.state_path.parent.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rows, open_count=None):
        self.state_path.write_text(json.dumps({
            "ts": 1700000000,
            "open": len(rows) if open_count is None else open_count,
            "by_severity": {},
            "findings": rows,
        }), encoding="utf-8")

    def _poll(self, watcher):
        asyncio.run(watcher.async_poll())


class TestReadState(WatcherCase):
    def test_missing_file_is_none(self):
        self.state_path.unlink(missing_ok=True)
        self.assertIsNone(findings.read_findings_state(self.hass))

    def test_garbage_is_none_not_a_crash(self):
        self.state_path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(findings.read_findings_state(self.hass))

    def test_rows_without_text_are_dropped(self):
        self._write([{"ts": 1, "text": "Real"}, {"ts": 2}, "junk"])
        state = findings.read_findings_state(self.hass)
        self.assertEqual([f["text"] for f in state["findings"]], ["Real"])


class TestFindingsWatcher(WatcherCase):
    def test_prime_adopts_without_announcing(self):
        """An HA restart must not replay the open list onto the bus."""
        self._write([{"ts": 1, "text": "Old problem", "severity": "serious"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])

    def test_new_finding_fires_once(self):
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()

        self._write([
            {"ts": 2, "text": "Hall battery dead", "severity": "critical",
             "entity_id": "sensor.hall_battery", "fixable": False,
             "source_title": "Device Health"},
            {"ts": 1, "text": "Old", "severity": "warning"},
        ])
        self._poll(watcher)
        self.assertEqual(len(self.hass.bus.fired), 1)
        event, data = self.hass.bus.fired[0]
        self.assertEqual(event, "brain_finding")
        self.assertEqual(data["finding"], "Hall battery dead")
        self.assertEqual(data["severity"], "critical")
        self.assertEqual(data["entity_id"], "sensor.hall_battery")
        self.assertFalse(data["fixable"])
        # the logbook line reads as a sentence
        self.assertIn("Hall battery dead", data["message"])

        # same content again: nothing new, nothing fired
        self._poll(watcher)
        self.assertEqual(len(self.hass.bus.fired), 1)

    def test_a_settled_finding_leaves_the_watermark_quietly(self):
        """Ids leave the mirror when settled; the watcher forgets them
        without firing anything — the add-on's settled ledger is what stops
        the same problem re-entering the list under the same text."""
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._write([])
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])

    def test_unreadable_state_changes_nothing(self):
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self.state_path.write_text("{torn", encoding="utf-8")
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])
        # ...and the watermark survives, so recovery doesn't replay history
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])


if __name__ == "__main__":
    unittest.main()
