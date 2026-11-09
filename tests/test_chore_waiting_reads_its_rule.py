#!/usr/bin/env python3
"""`chore.waiting` reads the automation that decides when a plug runs (#772).

A house's dehumidifier, on a plug the house calls "Basement dryer", was
reported as finished and waiting while an automation runs it off the
basement's humidity sensor: the humidity was under the automation's set
point, so standing still was the rule working. The check now looks up the
automations that start the machine (or the plug on the same device), and
the sensor and threshold each one waits on; while every one of them is
waiting on a reading that is not past its threshold, nothing is waiting
for anybody. With no automation it can read, it says what it always did.

The second example is one the report never named: a washing machine an
automation starts when the solar panels export more than 1500 W.
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

from checks import chores  # noqa: E402
import test_appliances  # noqa: E402

NOW = test_appliances.NOW
POWER = "sensor.dishwasher_power"


def started_by(alias, sensor, above, target):
    return {"id": alias.lower().replace(" ", "_"), "alias": alias,
            "triggers": [{"trigger": "numeric_state", "entity_id": sensor,
                          "above": above}],
            "actions": [{"action": "switch.turn_on",
                         "target": {"entity_id": target}}]}


class Base(unittest.TestCase):
    snap = test_appliances.TestTheChore.snap
    shape = test_appliances.TestTheChore.shape
    finished = test_appliances.TestTheChore.finished

    def machine(self, name, plug, sensor, reading, automation=None):
        snap = self.snap(entities={POWER: self.shape(name)},
                         recent=self.finished(60.0))
        snap["entities"][0]["device_id"] = "dev_m"
        snap["entities"].append({"entity_id": plug, "device_id": "dev_m"})
        snap["devices"] = [{"id": "dev_m", "name": name}]
        snap["states"][plug] = {"state": "on", "attributes": {}}
        snap["states"][sensor] = {"state": str(reading), "attributes": {}}
        if automation is not None:
            snap["automations"] = [automation]
        return snap


class TestTheDehumidifierOnAHumidityRule(Base):
    PLUG = "switch.basement_dryer"
    RH = "sensor.basement_humidity"

    def house(self, reading, rule=True):
        return self.machine(
            "Basement dryer", self.PLUG, self.RH, reading,
            started_by("Basement damp", self.RH, 65, self.PLUG)
            if rule else None)

    def test_below_its_set_point_is_the_rule_working(self):
        self.assertEqual(chores.waiting(self.house(58), NOW), [])

    def test_past_its_set_point_it_is_still_said(self):
        self.assertEqual(len(chores.waiting(self.house(72), NOW)), 1)

    def test_no_rule_to_read_keeps_todays_behaviour(self):
        self.assertEqual(len(chores.waiting(self.house(58, rule=False),
                                            NOW)), 1)

    def test_the_trail_says_which_rule_it_waits_on(self):
        snap = {**self.house(58), "_trail": []}
        chores.waiting(snap, NOW)
        said = " ".join(str(r.get("reason") or "") for r in snap["_trail"])
        self.assertIn("Basement damp", said)


class TestAWasherOnASolarRule(Base):
    PLUG = "switch.washer_plug"
    EXPORT = "sensor.grid_export"

    def house(self, reading):
        return self.machine(
            "Washing machine", self.PLUG, self.EXPORT, reading,
            started_by("Wash on sunshine", self.EXPORT, 1500, self.PLUG))

    def test_waiting_for_the_sun_is_not_waiting_for_a_person(self):
        self.assertEqual(chores.waiting(self.house(300), NOW), [])

    def test_exporting_and_still_stopped_is_said(self):
        self.assertEqual(len(chores.waiting(self.house(2400), NOW)), 1)


if __name__ == "__main__":
    unittest.main()
