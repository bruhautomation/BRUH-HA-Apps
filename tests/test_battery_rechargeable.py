"""A phone at 9% is not a battery to replace.

`dev.battery_low` filed every `device_class: battery` reading at or under
its threshold as "<device> battery is low — Replace the battery.", and
`forecast.battery` told somebody to "have a replacement ready" for the
same readings. Both are right about a door sensor's coin cell and wrong
about everything that is charged rather than replaced: the companion
app's phone dips under 15% most evenings and is plugged in at bedtime, a
robot vacuum runs itself down and goes back to its dock, a home battery
and a UPS cycle by design. The row cleared the moment each recharged and
came back the next evening — the wrong remedy, filed daily, about
something that was never a fault.

Every case drives the real checks over the clean fixture house, and the
first states what the shipped check answered about the phone before
asserting what it answers now.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

from checks import devices, forecasts  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402


def battery(name: str, level: str) -> dict:
    return {"state": level,
            "attributes": {"device_class": "battery",
                           "unit_of_measurement": "%",
                           "friendly_name": name,
                           "state_class": "measurement"},
            "last_updated": iso(600), "last_reported": iso(600)}


def with_phone(level: str = "9") -> dict:
    snap = house()
    snap["states"]["sensor.pixel_battery_level"] = battery(
        "Pixel Battery level", level)
    snap["entities"].append({"entity_id": "sensor.pixel_battery_level",
                             "platform": "mobile_app",
                             "device_id": "dev-pixel"})
    snap["devices"].append({"id": "dev-pixel", "name": "Pixel"})
    return snap


def shipped_battery_low(snap: dict, now: float) -> list[dict]:
    """The check as it shipped, on the same snapshot: no rechargeable
    rule. Run as the real function with the new helper switched off,
    so the comparison is against the code rather than a description."""
    original = devices.rechargeable
    devices.rechargeable = lambda house_, eid: False
    try:
        return devices.battery_low(snap, now)
    finally:
        devices.rechargeable = original


class TestThePhoneIsCharged(unittest.TestCase):

    def test_the_shipped_check_told_somebody_to_replace_it(self):
        found = shipped_battery_low(with_phone(), NOW)
        rows = [f for f in found
                if f["entity_id"] == "sensor.pixel_battery_level"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["fix"], "Replace the battery.")

    def test_the_check_says_nothing_about_it_now(self):
        self.assertEqual(devices.battery_low(with_phone(), NOW), [])

    def test_a_phone_gone_quiet_is_not_a_flat_cell_either(self):
        snap = with_phone("80")
        snap["states"]["sensor.pixel_battery_level"]["last_reported"] = \
            iso(10 * DAY)
        self.assertTrue(shipped_battery_low(snap, NOW))
        self.assertEqual(devices.battery_low(snap, NOW), [])


class TheDeviceSaysWhatItIs(unittest.TestCase):
    """An integration that covers both kinds is decided by the device."""

    def snap_with(self, sibling: str, sibling_state: dict,
                  platform: str = "xiaomi_miio") -> dict:
        snap = house()
        snap["states"]["sensor.robot_battery"] = battery("Robot battery", "4")
        snap["states"][sibling] = sibling_state
        snap["entities"] += [
            {"entity_id": "sensor.robot_battery", "platform": platform,
             "device_id": "dev-robot"},
            {"entity_id": sibling, "platform": platform,
             "device_id": "dev-robot"}]
        snap["devices"].append({"id": "dev-robot", "name": "Robot"})
        return snap

    def test_a_vacuum_docks(self):
        snap = self.snap_with("vacuum.robot", {"state": "docked",
                                               "attributes": {}})
        self.assertTrue(shipped_battery_low(snap, NOW))
        self.assertEqual(devices.battery_low(snap, NOW), [])

    def test_a_mower_docks(self):
        snap = self.snap_with("lawn_mower.robot", {"state": "docked",
                                                   "attributes": {}})
        self.assertEqual(devices.battery_low(snap, NOW), [])

    def test_a_device_that_reports_charging_is_charged(self):
        snap = self.snap_with(
            "binary_sensor.robot_charging",
            {"state": "off",
             "attributes": {"device_class": "battery_charging"}},
            platform="ring")
        self.assertEqual(devices.battery_low(snap, NOW), [])

    def test_the_same_integration_with_a_water_timer_still_fires(self):
        """A sibling that is neither a vacuum nor a charger says nothing,
        so a cell on AA batteries under the same integration is still a
        cell to replace."""
        snap = self.snap_with("switch.robot_valve", {"state": "off",
                                                     "attributes": {}})
        found = devices.battery_low(snap, NOW)
        self.assertEqual([f["entity_id"] for f in found],
                         ["sensor.robot_battery"])
        self.assertEqual(found[0]["fix"], "Replace the battery.")

    def test_the_registry_class_counts_when_the_state_has_none(self):
        snap = self.snap_with("binary_sensor.robot_charging",
                              {"state": "off", "attributes": {}},
                              platform="ring")
        snap["entities"][-1]["original_device_class"] = "battery_charging"
        self.assertEqual(devices.battery_low(snap, NOW), [])


class TestACoinCellIsStillACoinCell(unittest.TestCase):

    def test_the_zigbee_door_sensor_still_fires(self):
        snap = with_phone()
        snap["states"]["sensor.back_door_battery"]["state"] = "9"
        found = devices.battery_low(snap, NOW)
        self.assertEqual([f["entity_id"] for f in found],
                         ["sensor.back_door_battery"])
        self.assertEqual(found[0]["fix"], "Replace the battery.")

    def test_the_clean_house_is_silent(self):
        self.assertEqual(devices.battery_low(house(), NOW), [])
        self.assertFalse(devices.rechargeable(
            House(house()), "sensor.back_door_battery"))

    def test_an_entity_with_no_registry_row_is_not_assumed_rechargeable(self):
        snap = house()
        snap["states"]["sensor.orphan_battery"] = battery("Orphan", "3")
        self.assertFalse(devices.rechargeable(House(snap),
                                              "sensor.orphan_battery"))
        self.assertEqual([f["entity_id"] for f in
                          devices.battery_low(snap, NOW)],
                         ["sensor.orphan_battery"])


class TestWrongIsHeard(unittest.TestCase):
    """Wrong on a battery row writes an exception fact; the check has to
    read it or it files the same row again in new words."""

    def test_an_exception_stands_the_row_down(self):
        snap = house()
        snap["states"]["sensor.back_door_battery"]["state"] = "9"
        self.assertTrue(devices.battery_low(snap, NOW))
        snap["facts"] = {"sensor.back_door_battery": {"dev.battery_low"}}
        self.assertEqual(devices.battery_low(snap, NOW), [])

    def test_an_exception_for_another_check_does_not(self):
        snap = house()
        snap["states"]["sensor.back_door_battery"]["state"] = "9"
        snap["facts"] = {"sensor.back_door_battery": {"dev.frozen"}}
        self.assertTrue(devices.battery_low(snap, NOW))


class TestTheForecastAgrees(unittest.TestCase):

    def running_down(self, snap: dict, eid: str) -> dict:
        snap = copy.deepcopy(snap)
        snap["states"][eid]["state"] = "12"
        snap["battery_stats"][eid] = [
            {"start": NOW - d * DAY, "mean": 12 + d * 1.5}
            for d in range(30, 0, -1)]
        return snap

    def test_no_replacement_to_have_ready_for_a_phone(self):
        snap = self.running_down(with_phone("12"),
                                 "sensor.pixel_battery_level")
        self.assertEqual(forecasts.battery_runway(snap, NOW), [])

    def test_the_door_sensor_is_still_forecast(self):
        snap = self.running_down(with_phone(), "sensor.back_door_battery")
        found = forecasts.battery_runway(snap, NOW)
        self.assertEqual([f["entity_id"] for f in found],
                         ["sensor.back_door_battery"])


if __name__ == "__main__":
    unittest.main()
