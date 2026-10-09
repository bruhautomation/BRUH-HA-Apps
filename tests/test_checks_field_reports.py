#!/usr/bin/env python3
"""Four checks that were wrong about a real house, each driven at the case.

* `reg.orphan_device` called a HomeKit Bridge device a leftover. That
  integration makes one device per bridge and never gives it entities of
  its own; deleting it breaks the house's HomeKit exposure.
* `auto.dead_ref` called a scene missing when the same automation makes
  it with `scene.create` a step earlier, and read references out of steps
  marked `enabled: false`, which cannot fail.
* `chore.waiting` read a booster fan in a dryer's vent duct as the dryer,
  because its name has "dryer" in it.
* `rhythm` — a house with enough weekdays got no wake time. The spread is
  pinned here as robust to a few odd days while a scattered house still
  gets none.

Generic fixture names only.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rhythm  # noqa: E402
from checks import automations, chores, registry  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402


def _bridge(**over) -> dict:
    dev = {"id": "dev-bridge", "name": "Bridge one", "model": "HomeBridge",
           "manufacturer": "Home Assistant", "config_entries": ["e-bridge"],
           "identifiers": [["homekit", "e-bridge", "homekit.bridge"]]}
    dev.update(over)
    return dev


class TestADeviceWithNoEntitiesByDesign(unittest.TestCase):
    def test_a_homekit_bridge_is_not_a_leftover(self):
        snap = house()
        snap["config_entries"].append(
            {"entry_id": "e-bridge", "domain": "homekit",
             "title": "Bridge one", "state": "loaded", "source": "user"})
        snap["devices"].append(_bridge())
        self.assertEqual(registry.orphan_device(snap, NOW), [])

    def test_the_identifier_alone_is_enough(self):
        # The config entries key may be unavailable on a pass; the
        # device's own identifier still names its integration.
        snap = house()
        snap["config_entries"] = []
        snap["devices"].append(_bridge())
        self.assertEqual(registry.orphan_device(snap, NOW), [])

    def test_the_config_entry_alone_is_enough(self):
        snap = house()
        snap["config_entries"].append(
            {"entry_id": "e-bridge", "domain": "homekit",
             "title": "Bridge one", "state": "loaded", "source": "user"})
        snap["devices"].append(_bridge(identifiers=[]))
        self.assertEqual(registry.orphan_device(snap, NOW), [])

    def test_a_name_is_not_evidence(self):
        # Decided by the integration, never by a word: a leftover from
        # another integration that happens to be called a bridge is still
        # a leftover, and is reported beside a real HomeKit bridge.
        snap = house()
        snap["devices"].append(_bridge())
        snap["devices"].append(
            {"id": "dev-ghost", "name": "Old HomeBridge",
             "model": "HomeBridge", "config_entries": ["e1"],
             "identifiers": [["hue", "ghost"]]})
        found = registry.orphan_device(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Old HomeBridge", found[0]["detail"])
        self.assertNotIn("Bridge one", found[0]["detail"])


class TestASceneTheAutomationMakesItself(unittest.TestCase):
    def _snap(self, steps: list) -> dict:
        snap = house()
        snap["services"] |= {"scene.create", "scene.turn_on"}
        snap["automations"][0]["actions"] = steps
        return snap

    def test_scene_create_then_turn_on_is_not_a_dead_reference(self):
        snap = self._snap([
            {"action": "scene.create",
             "data": {"scene_id": "before_movie",
                      "snapshot_entities": ["light.kitchen"]}},
            {"action": "light.turn_on",
             "target": {"entity_id": "light.kitchen"}},
            {"action": "scene.turn_on",
             "target": {"entity_id": "scene.before_movie"}},
        ])
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_the_legacy_service_key_is_read_too(self):
        snap = self._snap([
            {"service": "scene.create", "data": {"scene_id": "before_movie"}},
            {"service": "scene.turn_on",
             "entity_id": "scene.before_movie"},
        ])
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_a_scene_nothing_creates_is_still_missing(self):
        snap = self._snap([
            {"action": "scene.create", "data": {"scene_id": "something_else"}},
            {"action": "scene.turn_on",
             "target": {"entity_id": "scene.before_movie"}},
        ])
        found = automations.dead_ref(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("scene.before_movie", [e["entity"] for e in found[0]["evidence"]])

    def test_a_disabled_scene_create_creates_nothing(self):
        snap = self._snap([
            {"action": "scene.create", "enabled": False,
             "data": {"scene_id": "before_movie"}},
            {"action": "scene.turn_on",
             "target": {"entity_id": "scene.before_movie"}},
        ])
        found = automations.dead_ref(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("scene.before_movie", [e["entity"] for e in found[0]["evidence"]])


class TestADisabledStepCannotFail(unittest.TestCase):
    def test_a_disabled_action_is_not_read(self):
        snap = house()
        snap["automations"][0]["actions"].append(
            {"action": "light.turn_on", "enabled": False,
             "target": {"entity_id": "light.gone"}})
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_a_disabled_condition_and_trigger_are_not_read(self):
        snap = house()
        cfg = snap["automations"][0]
        cfg["conditions"] = [
            {"condition": "state", "entity_id": "binary_sensor.gone",
             "state": "on", "enabled": False}]
        cfg.setdefault("triggers", []).append(
            {"trigger": "state", "entity_id": "sensor.gone", "enabled": False})
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_everything_inside_a_disabled_block_is_skipped(self):
        snap = house()
        snap["automations"][0]["actions"].append(
            {"enabled": False, "choose": [
                {"conditions": [{"condition": "state",
                                 "entity_id": "sensor.gone", "state": "1"}],
                 "sequence": [{"action": "light.turn_on",
                               "target": {"entity_id": "light.gone"}}]}]})
        self.assertEqual(automations.dead_ref(snap, NOW), [])

    def test_an_enabled_step_is_still_read(self):
        snap = house()
        snap["automations"][0]["actions"].append(
            {"action": "light.turn_on", "enabled": True,
             "target": {"entity_id": "light.gone"}})
        found = automations.dead_ref(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("light.gone", [e["entity"] for e in found[0]["evidence"]])


class TestAFanIsNotTheMachineItServes(unittest.TestCase):
    def test_a_dryer_vent_booster_is_not_a_dryer(self):
        for name in ("Dryer vent booster power", "Dryer booster fan",
                     "Dryer exhaust fan power", "Dryer duct blower",
                     "sensor.dryer_vent_booster_power",
                     "Dishwasher extractor fan", "Washer room vent"):
            self.assertEqual(chores.kind_of(name), "", name)

    def test_the_machines_themselves_still_are(self):
        self.assertEqual(chores.kind_of("Dryer plug power"), "dryer")
        self.assertEqual(chores.kind_of("Tumble dryer"), "dryer")
        self.assertEqual(chores.kind_of("Washing machine / dryer plug"),
                         "washer")
        self.assertEqual(chores.kind_of("Dishwasher power"), "dishwasher")
        # A word INSIDE another word is not the word: "fancy" is no fan.
        self.assertEqual(chores.kind_of("Fancy dryer"), "dryer")

    def test_the_chore_is_not_filed_about_the_fan(self):
        import appliances

        shape = {"name": "Dryer vent booster power", "idle_w": 0.5,
                 "busy_w": 40.0, "threshold_w": 10.0, "settle_min": 10.0,
                 "measured_settle": True, "draws": 12,
                 "typical_run_min": 50.0}
        bucket = appliances.BUCKET_S
        rows, when = [], NOW - (120 + 45 + 60) * 60
        for minutes, watts in ((120, 0.5), (45, 40.0), (60, 0.5)):
            for _ in range(int(minutes * 60 / bucket)):
                rows.append({"start": when, "mean": watts})
                when += bucket
        eid = "sensor.dryer_vent_booster_power"
        snap = {
            "available": {"states": True, "registry": True,
                          "appliances": True},
            "errors": {},
            "states": {eid: {"state": "0.5", "attributes": {
                "friendly_name": shape["name"], "device_class": "power",
                "state_class": "measurement"}}},
            "entities": [{"entity_id": eid, "disabled_by": None}],
            "devices": [], "areas": [],
            "appliances": {"built_at": NOW - 86400,
                           "entities": {eid: shape},
                           "recent": {eid: rows}},
        }
        self.assertEqual(chores.waiting(snap, NOW), [])
        # The same shape named for the machine is the chore.
        shape["name"] = "Dryer plug power"
        snap["states"][eid]["attributes"]["friendly_name"] = shape["name"]
        self.assertEqual(len(chores.waiting(snap, NOW)), 1)


def _rows(minutes: list[int]) -> list[dict]:
    return [{"first": m, "last": m, "dow": 1} for m in minutes]


class TestAWakeTimeIsNotVetoedByAFewOddDays(unittest.TestCase):
    """The spread is a median absolute deviation about the circular
    median, so it measures the middle of the days rather than their
    range: outliers cannot veto the answer, and a house that stirs
    anywhere across the morning still gets none."""

    def test_a_handful_of_odd_days_do_not_veto_it(self):
        usual = [415, 420, 425, 410, 430, 418, 422, 427, 412, 435, 405]
        # A holiday lie-in, a day out, a night up, an early flight, a
        # day nobody was home until the evening, and one more lie-in.
        odd = [600, 1020, 250, 300, 1110, 660]
        shape = rhythm._shape(_rows(usual + odd), "first")
        self.assertIsNotNone(shape)
        self.assertEqual(shape["days"], 17)
        self.assertLess(abs(shape["minute"] - 420), 15)
        self.assertLessEqual(shape["spread_min"], rhythm.MAX_SPREAD_MIN)

    def test_a_bedtime_either_side_of_midnight_still_counts(self):
        usual = [1420, 1430, 5, 15, 1410, 1435, 20, 1425, 10, 1415, 0]
        odd = [120, 180, 1260, 1200, 200, 60]
        shape = rhythm._shape(_rows(usual + odd), "last")
        self.assertIsNotNone(shape)
        self.assertLess(rhythm.circular_distance(shape["minute"], 1435), 30)

    def test_a_house_that_stirs_anywhere_still_has_no_wake_time(self):
        scattered = [300 + 25 * i for i in range(17)]  # 05:00 → 11:40
        self.assertIsNone(rhythm._shape(_rows(scattered), "first"))


if __name__ == "__main__":
    unittest.main()
