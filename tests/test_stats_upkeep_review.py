#!/usr/bin/env python3
"""The statistics pass, held to the review of #576.

  * A unit change Core could convert (the old and new units share a class,
    Wh → kWh) is never relabelled unattended: relabelling would make every
    old value mean a thousand times less.
  * Nothing is cleared while Core is still starting, and a sensor the
    registry does not know (a YAML or template sensor with no unique_id)
    is cleared only after it has been missing on two passes hours apart;
    one that comes back is never cleared.
  * The maintainer holds the pass while automatic runs are paused, and a
    pass that failed is tried again after an hour, not on every poll.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import stats_upkeep  # noqa: E402

NOW = 1_800_000_000.0
HOURS = 3600


def units(eid, state_unit, metadata_unit, state_class, metadata_class):
    return {eid: [{"type": "units_changed", "data": {
        "statistic_id": eid, "state_unit": state_unit,
        "state_unit_class": state_class, "metadata_unit": metadata_unit,
        "metadata_unit_class": metadata_class,
        "supported_unit": metadata_unit}}]}


def live(eid, unit):
    return {"entity_id": eid, "state": "1",
            "attributes": {"unit_of_measurement": unit}}


def missing(eid):
    return {eid: [{"type": "no_state", "data": {"statistic_id": eid}}]}


class TestAConvertibleUnitIsNeverRelabelled(unittest.TestCase):
    def test_wh_to_kwh_is_left_with_a_reason(self):
        out = stats_upkeep.plan(
            stats_upkeep.issues_from(units("sensor.meter", "kWh", "Wh",
                                           "energy", "energy")),
            [live("sensor.meter", "kWh")], [], core_state="RUNNING")
        self.assertEqual(out["fix"], [])
        [left] = out["leave"]
        self.assertIn("convert", left["why"])

    def test_units_with_no_shared_class_are_still_fixed(self):
        # "pcs" → "items": nothing converts one into the other, so the
        # statistics can only follow the sensor.
        out = stats_upkeep.plan(
            stats_upkeep.issues_from(units("sensor.stock", "items", "pcs",
                                           None, None)),
            [live("sensor.stock", "items")], [], core_state="RUNNING")
        self.assertEqual(len(out["fix"]), 1)


class TestAnUnregisteredSensorIsClearedOnlyWhenItStaysGone(unittest.TestCase):
    def pass_(self, states, core_state="RUNNING", known=None, now=NOW):
        return stats_upkeep.plan(
            stats_upkeep.issues_from(missing("sensor.yaml_meter")), states, [],
            core_state=core_state, missing=known or {}, now=now)

    def test_nothing_is_cleared_while_core_is_starting(self):
        out = self.pass_([], core_state="NOT_RUNNING")
        self.assertEqual(out["clear"], [])
        # And a sighting while starting is not counted.
        self.assertEqual(out["missing"], {})

    def test_cleared_on_a_second_pass_hours_later(self):
        first = self.pass_([])
        self.assertEqual(first["clear"], [])
        self.assertIn("sensor.yaml_meter", first["missing"])
        soon = self.pass_([], known=first["missing"], now=NOW + 2 * HOURS)
        self.assertEqual(soon["clear"], [])
        later = self.pass_([], known=soon["missing"], now=NOW + 7 * HOURS)
        self.assertEqual([c["statistic_id"] for c in later["clear"]],
                         ["sensor.yaml_meter"])

    def test_one_that_comes_back_is_never_cleared(self):
        first = self.pass_([])
        back = self.pass_([live("sensor.yaml_meter", "W")],
                          known=first["missing"], now=NOW + 7 * HOURS)
        self.assertEqual(back["clear"], [])
        self.assertEqual(back["missing"], {})
        # Gone again: the clock starts over.
        again = self.pass_([], known=back["missing"], now=NOW + 8 * HOURS)
        self.assertEqual(again["clear"], [])

    def test_a_disabled_entity_still_needs_core_running(self):
        issues = stats_upkeep.issues_from(missing("sensor.off"))
        reg = [{"entity_id": "sensor.off", "disabled_by": "user"}]
        self.assertEqual(stats_upkeep.plan(issues, [], reg,
                                           core_state="STARTING")["clear"], [])
        self.assertEqual(len(stats_upkeep.plan(issues, [], reg,
                                               core_state="RUNNING")["clear"]), 1)


class TestTheServerPassAskedCoreIfItWasRunning(unittest.TestCase):
    def setUp(self):
        self.server = importlib.import_module("server")
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (stats_upkeep.STORE, self.server._stats_ws,
                      self.server._stats_states)
        stats_upkeep.STORE = Path(self.tmp.name) / "stats.json"
        self.sent: list[dict] = []
        self.core_state = "NOT_RUNNING"

        async def ws(commands):
            out = []
            for cmd in commands:
                self.sent.append(cmd)
                if cmd["type"] == "recorder/validate_statistics":
                    out.append({"ok": True, "result": missing("sensor.yaml_meter")})
                elif cmd["type"] == "config/entity_registry/list":
                    out.append({"ok": True, "result": []})
                elif cmd["type"] == "get_config":
                    out.append({"ok": True, "result": {"state": self.core_state}})
                else:
                    out.append({"ok": True, "result": None})
            return out

        async def states():
            return []
        self.server._stats_ws = ws
        self.server._stats_states = states

    def tearDown(self):
        (stats_upkeep.STORE, self.server._stats_ws,
         self.server._stats_states) = self.saved
        self.tmp.cleanup()

    def cleared(self):
        return [c for c in self.sent if c["type"] == "recorder/clear_statistics"]

    def test_boot_then_two_running_passes(self):
        asyncio.run(self.server._run_statistics("schedule", now=NOW))
        self.assertIn("get_config", [c["type"] for c in self.sent])
        self.core_state = "RUNNING"
        asyncio.run(self.server._run_statistics("schedule", now=NOW + HOURS))
        self.assertEqual(self.cleared(), [])
        asyncio.run(self.server._run_statistics("schedule", now=NOW + 8 * HOURS))
        self.assertEqual([c["statistic_ids"] for c in self.cleared()],
                         [["sensor.yaml_meter"]])


class TestTheMaintainerSchedule(unittest.TestCase):
    def setUp(self):
        import settings_store
        self.server = importlib.import_module("server")
        self.settings_store = settings_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        s = self.server
        self.saved = (s.schedule_store.STORE, settings_store.SETTINGS_FILE,
                      s._maint_start, stats_upkeep.STORE, dict(s.STATS_STATE),
                      dict(s.MAINT_STATE["statistics"]), s.house_book.STORE)
        s.schedule_store.STORE = str(root / "schedule.json")
        settings_store.SETTINGS_FILE = str(root / "settings.json")
        stats_upkeep.STORE = root / "stats.json"
        s.house_book.STORE = root / "book.json"
        s.STATS_STATE.update(booted=False, tried=0.0)
        self.started: list[str] = []
        s._maint_start = lambda name, factory: self.started.append(name) or True

    def tearDown(self):
        s = self.server
        (s.schedule_store.STORE, self.settings_store.SETTINGS_FILE,
         s._maint_start, stats_upkeep.STORE, state, maint,
         s.house_book.STORE) = self.saved
        s.STATS_STATE.clear()
        s.STATS_STATE.update(state)
        s.MAINT_STATE["statistics"].update(maint)
        self.tmp.cleanup()

    def tick(self, now):
        asyncio.run(self.server._maint_tick(now))

    def test_paused_automatic_runs_hold_the_pass(self):
        self.settings_store.save({"onboarded": True, "auto_enabled": False,
                                  "upgrade_advice_auto": False})
        self.tick(NOW)
        self.assertNotIn("statistics", self.started)
        self.assertIn("paused", self.server.MAINT_STATE["statistics"]["held"])
        self.settings_store.save({"onboarded": True, "auto_enabled": True,
                                  "upgrade_advice_auto": False})
        self.tick(NOW)
        self.assertIn("statistics", self.started)

    def test_a_failed_pass_is_retried_after_an_hour_not_every_poll(self):
        self.settings_store.save({"onboarded": True, "auto_enabled": True,
                                  "upgrade_advice_auto": False})
        self.tick(NOW)
        # The pass failed: it wrote no `last_run`. The next poll —
        self.tick(NOW + self.server.MAINT_POLL_S)
        self.assertEqual(self.started.count("statistics"), 1)
        # — and after the retry wait it is tried again.
        self.tick(NOW + self.server.STATS_RETRY_S + 1)
        self.assertEqual(self.started.count("statistics"), 2)


if __name__ == "__main__":
    unittest.main()
