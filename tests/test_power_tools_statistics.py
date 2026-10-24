#!/usr/bin/env python3
"""Long-term statistics, corrected through the real admin-gated handlers.

The recorder below answers the way Core's `recorder.statistics` module and
its instance do: `get_metadata(hass, statistic_ids=)` →
`{id: (metadata_id, metadata)}`, `list_statistic_ids(hass)` → rows with
`statistic_id` and `source`, `statistics_during_period(...)` → `{id: [rows]}`
whose `start` is a float timestamp, and an instance whose
`async_adjust_statistics(id, start, adjustment, unit)` adds the adjustment
to the sum of every hour from `start` on (what
`recorder/adjust_sum_statistics` queues) and whose
`async_clear_statistics(ids)` drops them.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402

HOUR = 3600
T0 = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0) \
    - dt.timedelta(hours=10)


class Recorder:
    def __init__(self):
        self.meta = {}
        self.rows = {}
        self.adjusted = []
        self.cleared = []

    def add(self, sid, states, *, has_sum=True, unit="kWh", source="recorder"):
        """A meter: one row per hour; the sum follows the state's increases
        the way the recorder compiles a total_increasing sensor."""
        self.meta[sid] = {"statistic_id": sid, "has_sum": has_sum,
                          "unit_of_measurement": unit, "source": source,
                          "name": None}
        total, rows = 0.0, []
        for i, state in enumerate(states):
            if i:
                total += state - states[i - 1] if state >= states[i - 1] else state
            rows.append({"start": (T0 + dt.timedelta(hours=i)).timestamp(),
                         "state": state, "sum": total})
        self.rows[sid] = rows

    # the statistics module
    def get_metadata(self, hass, *, statistic_ids=None):
        return {s: (1, m) for s, m in self.meta.items()
                if statistic_ids is None or s in statistic_ids}

    def list_statistic_ids(self, hass, statistic_ids=None, statistic_type=None):
        return [dict(m) for m in self.meta.values()]

    def statistics_during_period(self, hass, start, end, ids, period, units, types_):
        return {s: [r for r in self.rows.get(s, []) if r["start"] >= start.timestamp()]
                for s in ids}

    # the instance
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)

    def async_adjust_statistics(self, sid, start, adjustment, unit):
        self.adjusted.append((sid, start, adjustment, unit))
        for row in self.rows[sid]:
            if row["start"] >= start.timestamp():
                row["sum"] += adjustment

    def async_clear_statistics(self, ids):
        self.cleared.extend(ids)


class Services:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, name, handler, schema=None, **kw):
        self.handlers[name] = handler

    def has_service(self, domain, name):
        return name in self.handlers


class Auth:
    async def async_get_user(self, user_id):
        return types.SimpleNamespace(id=user_id, is_admin=user_id == "admin")


class States:
    def __init__(self, ids):
        self.ids = set(ids)

    def get(self, eid):
        return object() if eid in self.ids else None


class Registry:
    def __init__(self, ids):
        self.ids = set(ids)

    def async_get(self, eid):
        return object() if eid in self.ids else None


class Case(unittest.TestCase):
    def setUp(self):
        self.pkg = env.load_integration()
        self.rec = Recorder()
        recorder = types.ModuleType("homeassistant.components.recorder")
        recorder.get_instance = lambda hass: self.rec
        statistics = types.ModuleType("homeassistant.components.recorder.statistics")
        for name in ("get_metadata", "list_statistic_ids", "statistics_during_period"):
            setattr(statistics, name, getattr(self.rec, name))
        recorder.statistics = statistics
        mods = patch.dict(sys.modules, {
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.statistics": statistics})
        mods.start()
        self.addCleanup(mods.stop)
        self.hass = types.SimpleNamespace(
            services=Services(), auth=Auth(), data={},
            states=States({"sensor.grid_import"}),
            registries={"entity": Registry({"sensor.grid_import"})})
        self.pkg.power_tools.async_register_power_tools(self.hass)

    def run_tool(self, name, data, user_id="admin"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data):
        with self.assertRaises(env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)

    def sums(self, sid):
        return [round(r["sum"], 3) for r in self.rec.rows[sid]]


class TestAdjustingASum(Case):
    def setUp(self):
        super().setUp()
        self.rec.add("sensor.grid_import", [10, 11, 12, 13, 14])
        self.rec.add("sensor.lounge_temperature", [20, 21], has_sum=False, unit="°C")

    def test_previewed_by_default_then_applied(self):
        start = (T0 + dt.timedelta(hours=2)).isoformat()
        preview = self.run_tool("adjust_statistic_sum", {
            "statistic_id": "sensor.grid_import", "start_time": start,
            "adjustment": -1.5})
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["hours_changed"], 3)
        self.assertEqual(self.rec.adjusted, [])
        self.run_tool("adjust_statistic_sum", {
            "statistic_id": "sensor.grid_import", "start_time": start,
            "adjustment": -1.5, "dry_run": False})
        self.assertEqual(self.sums("sensor.grid_import"), [0, 1, 0.5, 1.5, 2.5])

    def test_refusals_name_the_field(self):
        start = T0.isoformat()
        self.assertIn("statistic_id", self.refused("adjust_statistic_sum", {
            "statistic_id": "sensor.nothing", "start_time": start, "adjustment": 1}))
        self.assertIn("no sum", self.refused("adjust_statistic_sum", {
            "statistic_id": "sensor.lounge_temperature", "start_time": start,
            "adjustment": 1}))
        self.assertIn("unit", self.refused("adjust_statistic_sum", {
            "statistic_id": "sensor.grid_import", "start_time": start,
            "adjustment": 1, "unit": "Wh"}))
        self.assertIn("start_time", self.refused("adjust_statistic_sum", {
            "statistic_id": "sensor.grid_import", "start_time": "yesterday",
            "adjustment": 1}))


class TestOrphans(Case):
    def setUp(self):
        super().setUp()
        self.rec.add("sensor.grid_import", [1, 2])
        self.rec.add("sensor.old_plug_energy", [1, 2])
        self.rec.add("solar:forecast", [1, 2], source="solar")

    def test_only_an_entity_style_id_with_no_entity_is_an_orphan(self):
        result = self.run_tool("clear_orphaned_statistics", {})
        self.assertEqual([o["statistic_id"] for o in result["orphans"]],
                         ["sensor.old_plug_energy"])
        self.assertEqual(self.rec.cleared, [])
        self.run_tool("clear_orphaned_statistics", {"dry_run": False})
        self.assertEqual(self.rec.cleared, ["sensor.old_plug_energy"])

    def test_naming_one_that_still_has_an_entity_is_refused(self):
        self.assertIn("sensor.grid_import", self.refused(
            "clear_orphaned_statistics", {"statistic_id": ["sensor.grid_import"]}))


class TestHealingSpikes(Case):
    def test_a_counter_glitch_is_taken_out_and_the_states_say_what_it_should_be(self):
        # A meter reading 100, 101, then one garbage hour near 2^30 that the
        # recorder summed, then back to ordinary readings it treats as a
        # reset and keeps adding to.
        states = [100, 101, 2 ** 30 + 101, 2 ** 30 + 102, 2 ** 30 + 103]
        self.rec.add("sensor.grid_import", states)
        preview = self.run_tool("heal_statistic_spikes",
                                {"statistic_id": "sensor.grid_import"})
        self.assertTrue(preview["dry_run"])
        self.assertEqual(len(preview["spikes"]), 1)
        spike = preview["spikes"][0]
        self.assertEqual(spike["start"], (T0 + dt.timedelta(hours=2)).isoformat())
        self.assertEqual(spike["should_be"], 0.0)
        self.assertEqual(self.rec.adjusted, [])
        self.run_tool("heal_statistic_spikes",
                      {"statistic_id": "sensor.grid_import", "dry_run": False})
        self.assertEqual(self.sums("sensor.grid_import"), [0, 1, 1, 2, 3])

    def test_a_bound_finds_a_smaller_spike(self):
        # A second shape: an hour that added 500 kWh to a house that uses one
        # an hour. Its states show a 1 kWh hour, so that is what it keeps.
        self.rec.add("sensor.grid_import", [10, 11, 12, 13])
        self.rec.rows["sensor.grid_import"][2]["sum"] += 499
        self.rec.rows["sensor.grid_import"][3]["sum"] += 499
        self.assertEqual(self.run_tool("heal_statistic_spikes", {
            "statistic_id": "sensor.grid_import"})["spikes"], [])
        result = self.run_tool("heal_statistic_spikes", {
            "statistic_id": "sensor.grid_import", "max_hourly_change": 50,
            "dry_run": False})
        self.assertEqual(result["spikes"][0]["should_be"], 1)
        self.assertEqual(self.sums("sensor.grid_import"), [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
