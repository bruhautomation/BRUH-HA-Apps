#!/usr/bin/env python3
"""A 0% battery on a device that is plainly running is not a dying battery.

Reported from a house (devloop #254): `dev.battery_low` filed "battery reads
0%" for a mains-powered energy monitor whose power sensor was reporting live
watts. `_never_above_zero` already covers such a device once a week of
statistics exists; a live, moving power or energy reading beside the battery
on the same device is evidence the same afternoon.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from checks import devices  # noqa: E402

NOW = time.time()


def _iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def snap(*, with_power=True, power_changed_ago=60.0, power_state="412.0"):
    recent = _iso(NOW - 600)
    states = {
        "sensor.meter_battery": {
            "state": "0", "last_changed": recent, "last_updated": recent,
            "last_reported": recent,
            "attributes": {"device_class": "battery",
                           "unit_of_measurement": "%",
                           "friendly_name": "Energy meter battery"}},
    }
    entities = [{"entity_id": "sensor.meter_battery", "device_id": "meter",
                 "platform": "zwave_js", "entity_category": "diagnostic"}]
    if with_power:
        changed = _iso(NOW - power_changed_ago)
        states["sensor.meter_power"] = {
            "state": power_state, "last_changed": changed,
            "last_updated": changed, "last_reported": changed,
            "attributes": {"device_class": "power",
                           "unit_of_measurement": "W",
                           "friendly_name": "Energy meter power"}}
        entities.append({"entity_id": "sensor.meter_power",
                         "device_id": "meter", "platform": "zwave_js"})
    return {"states": states, "entities": entities,
            "devices": [{"id": "meter", "name": "Energy meter"}],
            "areas": [], "_trail": []}


class TestAZeroBatteryBesideLiveWatts(unittest.TestCase):
    def test_a_live_power_reading_files_nothing(self):
        self.assertEqual(devices.battery_low(snap(), NOW), [])

    def test_a_real_flat_battery_still_files(self):
        rows = devices.battery_low(snap(with_power=False), NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn("mains", rows[0]["fix"].lower())
        self.assertNotIn("sensor.", rows[0]["fix"])

    def test_a_power_sensor_that_stopped_moving_is_no_evidence(self):
        rows = devices.battery_low(
            snap(power_changed_ago=5 * 86400), NOW)
        self.assertEqual(len(rows), 1)

    def test_an_unavailable_power_sensor_is_no_evidence(self):
        rows = devices.battery_low(snap(power_state="unavailable"), NOW)
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
