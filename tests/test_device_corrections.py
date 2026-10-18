#!/usr/bin/env python3
"""A correction about one entity of a device reaches its siblings.

Reported from a house (devloop #146, #253): `dev.frozen` stood at 0
confirmed against 6 Wrong, and the reasons were a dead battery the owner
will not replace, "normal for this sensor", a device not in use. Every
correction was written under the entity the row was filed under, and
`House.withheld_by` read per entity, room and rule — never per DEVICE —
so a Wrong on the battery row of a sensor did not reach the temperature
reading on the same box, and the next pass filed it again.

Driven through the real checks over a snapshot built the way the
collector builds one.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from checks import devices  # noqa: E402
from checks._util import House  # noqa: E402

NOW = time.time()
DAY = 86400


def _iso(ts: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def _never():
    return {"checks": ["climate.freeze", "safety.tripped"],
            "domains": ["alarm_control_panel", "lock"],
            "classes": ["carbon_monoxide", "gas", "moisture", "safety",
                        "smoke"],
            "protected": []}


def house_snap(*, rules=None, battery="40", porch_temp="21.5",
               smoke_state="off", facts=None):
    """Two devices: a porch sensor (battery, temperature, smoke) and a shed one."""
    old = _iso(NOW - 3 * DAY)
    states = {
        "sensor.porch_battery": {
            "state": battery, "last_changed": old, "last_updated": old,
            "attributes": {"device_class": "battery",
                           "unit_of_measurement": "%",
                           "friendly_name": "Porch sensor battery"}},
        "sensor.porch_temperature": {
            "state": porch_temp, "last_changed": old, "last_updated": old,
            "attributes": {"device_class": "temperature",
                           "unit_of_measurement": "°C",
                           "friendly_name": "Porch temperature"}},
        "binary_sensor.porch_smoke": {
            "state": smoke_state, "last_changed": old, "last_updated": old,
            "attributes": {"device_class": "smoke",
                           "friendly_name": "Porch smoke"}},
        "sensor.shed_temperature": {
            "state": "12.0", "last_changed": old, "last_updated": old,
            "attributes": {"device_class": "temperature",
                           "unit_of_measurement": "°C",
                           "friendly_name": "Shed temperature"}},
    }
    entities = [
        {"entity_id": "sensor.porch_battery", "device_id": "porch",
         "entity_category": "diagnostic", "platform": "zha"},
        {"entity_id": "sensor.porch_temperature", "device_id": "porch",
         "platform": "zha"},
        {"entity_id": "binary_sensor.porch_smoke", "device_id": "porch",
         "platform": "zha"},
        {"entity_id": "sensor.shed_temperature", "device_id": "shed",
         "platform": "zha"},
    ]
    devices_ = [{"id": "porch", "name": "Porch sensor"},
                {"id": "shed", "name": "Shed sensor"}]
    week = [{"min": 21.5, "max": 21.5}] * 7
    snap = {"states": states, "entities": entities, "devices": devices_,
            "areas": [], "_trail": [],
            "stats": {"sensor.porch_temperature": week,
                      "sensor.shed_temperature": [{"min": 12.0,
                                                   "max": 12.0}] * 7}}
    if facts is not None:
        snap["facts"] = facts
    else:
        snap["corrections"] = {"entity": rules or {}, "area": {}, "check": {},
                               "never": _never()}
    return snap


def wrong(check):
    return {"sensor.porch_battery": {check: {"text": "battery is dead, "
                                             "not replacing it",
                                             "until": "", "id": "f1"}}}


class TestADeviceAnswerReachesItsSiblings(unittest.TestCase):
    def test_a_battery_wrong_silences_frozen_on_the_same_device(self):
        snap = house_snap(rules=wrong("dev.battery_low"))
        named = {r["entity_id"] for r in devices.frozen(snap, NOW)}
        self.assertNotIn("sensor.porch_temperature", named)
        self.assertIn("sensor.shed_temperature", named,
                      "an unrelated device must still report")

    def test_a_battery_wrong_silences_unavailable_on_the_same_device(self):
        snap = house_snap(rules=wrong("dev.battery_low"),
                          porch_temp="unavailable")
        snap["states"]["sensor.shed_temperature"]["state"] = "unavailable"
        rows = devices.unavailable(snap, NOW)
        named = {r["entity_id"] for r in rows}
        self.assertNotIn("sensor.porch_temperature", named)
        self.assertIn("sensor.shed_temperature", named)

    def test_a_safety_sibling_is_never_covered(self):
        snap = house_snap(rules=wrong("dev.battery_low"),
                          porch_temp="unavailable",
                          smoke_state="unavailable")
        named = {r["entity_id"] for r in devices.unavailable(snap, NOW)}
        self.assertIn("binary_sensor.porch_smoke", named)
        self.assertNotIn("sensor.porch_temperature", named)

    def test_a_star_rule_covers_the_device(self):
        snap = house_snap(rules=wrong("*"))
        house = House(snap)
        self.assertFalse(house.should_report("sensor.porch_temperature",
                                             "dev.frozen"))
        self.assertTrue(house.should_report("sensor.shed_temperature",
                                            "dev.frozen"))

    def test_an_unrelated_rule_on_a_sibling_covers_nothing(self):
        snap = house_snap(rules=wrong("base.unusual"))
        named = {r["entity_id"] for r in devices.frozen(snap, NOW)}
        self.assertIn("sensor.porch_temperature", named)

    def test_the_old_exception_map_reaches_siblings_too(self):
        snap = house_snap(facts={"sensor.porch_battery": ["dev.battery_low"]})
        named = {r["entity_id"] for r in devices.frozen(snap, NOW)}
        self.assertNotIn("sensor.porch_temperature", named)
        self.assertIn("sensor.shed_temperature", named)


class TestADeadBatteryOwnsItsDevice(unittest.TestCase):
    def test_frozen_stands_down_beside_a_flat_battery(self):
        snap = house_snap(battery="0")
        named = {r["entity_id"] for r in devices.frozen(snap, NOW)}
        self.assertNotIn("sensor.porch_temperature", named)
        self.assertIn("sensor.shed_temperature", named)

    def test_a_healthy_battery_leaves_frozen_alone(self):
        snap = house_snap(battery="80")
        named = {r["entity_id"] for r in devices.frozen(snap, NOW)}
        self.assertIn("sensor.porch_temperature", named)


if __name__ == "__main__":
    unittest.main()
