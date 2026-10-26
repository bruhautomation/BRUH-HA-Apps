"""An alarm about a fault is an alarm that is meant never to go off.

Report 445: `auto.never_fired` filed "has never fired … or delete it" about
an automation that messages somebody when a pump runs too long, draws too
much or too little power or cycles too often, and about one that messages
when a rarely-on binary sensor turns on: 0 confirmed against 2 marked
Wrong. Both are the shape the check already spares for smoke and leaks —
a watch for a value that is wrong, whose only action is a message. Read
off the config, never the name.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

from test_house_checks import DAY, house, iso  # noqa: E402
from test_never_fired_safety import installed, never_fired_ids  # noqa: E402

PUSH = [{"action": "notify.mobile_app_phone",
         "data": {"message": "The well pump needs a look"}}]


def pumped(snap: dict) -> dict:
    snap["states"]["sensor.well_pump_power"] = {
        "state": "0", "attributes": {"device_class": "power",
                                     "unit_of_measurement": "W",
                                     "friendly_name": "Well pump power"},
        "last_changed": iso(DAY)}
    snap["states"]["switch.well_pump"] = {
        "state": "off", "attributes": {"friendly_name": "Well pump"},
        "last_changed": iso(DAY)}
    snap["states"]["binary_sensor.sump_float"] = {
        "state": "off", "attributes": {"friendly_name": "Sump float"},
        "last_changed": iso(80 * DAY)}
    return snap


class TestAFaultWatchIsSpared(unittest.TestCase):
    def test_thresholds_on_a_pump_that_only_message(self):
        snap = pumped(house())
        installed(snap, {
            "id": "pump_fault", "alias": "Well pump fault",
            "triggers": [
                {"trigger": "state", "entity_id": "switch.well_pump",
                 "to": "on", "for": {"minutes": 15}},
                {"trigger": "numeric_state",
                 "entity_id": "sensor.well_pump_power", "above": 1200},
                {"trigger": "numeric_state",
                 "entity_id": "sensor.well_pump_power", "below": 700},
                {"trigger": "template", "value_template":
                 "{{ states('counter.pump_cycles') | int > 50 }}"}],
            "actions": [{"choose": [{"conditions": [], "sequence": PUSH}],
                         "default": [{"action": "persistent_notification.create",
                                      "data": {"message": "Pump fault"}}]}]},
            "automation.well_pump_fault")
        self.assertEqual(never_fired_ids(snap), [])

    def test_a_rarely_on_binary_sensor_that_only_messages(self):
        snap = pumped(house())
        installed(snap, {
            "id": "sump", "alias": "Sump float up",
            "trigger": [{"platform": "state",
                         "entity_id": "binary_sensor.sump_float", "to": "on"}],
            "action": [{"service": "notify.notify",
                        "data": {"message": "Sump float is up"}}]},
            "automation.sump_float_up")
        self.assertEqual(never_fired_ids(snap), [])


class TestAnOrdinaryAutomationStillFiles(unittest.TestCase):
    def test_a_threshold_that_switches_something_files(self):
        snap = pumped(house())
        installed(snap, {
            "id": "pump_off", "alias": "Pump off on overload",
            "triggers": [{"trigger": "numeric_state",
                          "entity_id": "sensor.well_pump_power",
                          "above": 1200}],
            "actions": [{"action": "switch.turn_off",
                         "target": {"entity_id": "switch.well_pump"}}]},
            "automation.pump_off_on_overload")
        self.assertEqual(never_fired_ids(snap),
                         ["automation.pump_off_on_overload"])

    def test_a_state_trigger_that_messages_on_any_change_files(self):
        snap = pumped(house())
        installed(snap, {
            "id": "pump_changed", "alias": "Pump changed",
            "triggers": [{"trigger": "state",
                          "entity_id": "switch.well_pump"}],
            "actions": PUSH}, "automation.pump_changed")
        self.assertEqual(never_fired_ids(snap), ["automation.pump_changed"])

    def test_a_light_on_a_binary_sensor_files(self):
        snap = pumped(house())
        installed(snap, {
            "id": "float_light", "alias": "Float light",
            "triggers": [{"trigger": "state",
                          "entity_id": "binary_sensor.sump_float",
                          "to": "on"}],
            "actions": [{"action": "light.turn_on",
                         "target": {"entity_id": "light.hall"}}]},
            "automation.float_light")
        self.assertEqual(never_fired_ids(snap), ["automation.float_light"])


if __name__ == "__main__":
    unittest.main()
