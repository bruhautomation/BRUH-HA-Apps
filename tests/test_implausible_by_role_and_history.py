#!/usr/bin/env python3
"""`dev.implausible` takes a sensor's range from what it is and what it has
read, not from its device class alone.

A computer's processor temperature (a system-monitor-style sensor) was
filed as "impossible" — and was marked Wrong — because the check judged it
by the ambient range of `device_class: temperature` whenever none of its
known names matched: an integration spelled `system_monitor` rather than
`systemmonitor`, a reading a model took for room air, or a sensor whose
name says nothing about the machine at all. Three classes of fix:

- the providing integration is read however it is spelled, and an
  integration whose own name says cpu or processor is a computer's;
- a reading's OBSERVED history: a sensor that has read warmer than any
  room every hour of the week and above the ambient ceiling on some of
  them measures something hot — a rack, a chip, a boiler — and its
  ceiling is lifted. A room thermometer that spiked today, or one stuck
  at one value, still files;
- the nightly baseline pass reads the same history, so it learns that
  sensor's hot hours rather than throwing them away as impossible.
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import baselines  # noqa: E402
import world_model  # noqa: E402
from checks import baseline, devices  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402
from test_implausible_hot_devices import implausible_ids, plant  # noqa: E402

GENERIC = {"id": "dev_rack", "name": "Rack sensor", "manufacturer": "Espressif",
           "model": "ESP32"}


def room_air(snap, eid):
    snap["world"] = {**(snap.get("world") or {}), eid: {
        "fp": "x", "confidence": 0.95, "priority": 0.0,
        "roles": {**world_model.DEFAULTS, "measures": "room_air"}}}


def week(snap, eid, days):
    """Daily statistics, newest last: ``days`` is ``[(min, max), ...]``."""
    snap.setdefault("stats", {})[eid] = [
        {"start": NOW - (len(days) - i) * 86400, "mean": (lo + hi) / 2,
         "min": lo, "max": hi} for i, (lo, hi) in enumerate(days)]


CPU_WEEK = [(44, 79), (46, 83), (45, 77), (47, 88), (43, 81), (45, 80),
            (46, 84)]


class TestTheIntegrationHoweverItIsSpelled(unittest.TestCase):
    def test_a_system_monitor_sensor_a_model_read_as_room_air(self):
        snap = house()
        eid = "sensor.system_monitor_temperature"
        plant(snap, eid, "System Monitor Temperature", 82,
              platform="system_monitor")
        room_air(snap, eid)
        self.assertEqual(implausible_ids(snap), [])
        self.assertTrue(devices.computer_temperature(House(snap), eid))
        # And base.unusual leaves it to its load, through the same answer.
        self.assertIn("computer", baseline.not_a_house_reading(
            House(snap), eid, snap["states"][eid]))

    def test_an_integration_named_for_the_processor(self):
        snap = house()
        eid = "sensor.pi_soc"
        plant(snap, eid, "Pi", 71, platform="rpi_cpu_temp")
        room_air(snap, eid)
        self.assertEqual(implausible_ids(snap), [])


class TestWhatTheSensorHasRead(unittest.TestCase):
    def test_a_rack_probe_that_has_always_read_hot(self):
        """No word on it says machine; a week of readings does."""
        snap = house()
        eid = "sensor.rack_sensor_temperature_2"
        plant(snap, eid, "Rack sensor Temperature 2", 86, platform="esphome",
              device=GENERIC)
        week(snap, eid, CPU_WEEK)
        self.assertEqual(implausible_ids(snap), [])

    def test_a_room_thermometer_that_spiked_today_still_files(self):
        snap = house()
        eid = "sensor.study_temperature"
        plant(snap, eid, "Study temperature", 99, platform="zha")
        week(snap, eid, [(18, 22), (18, 23), (19, 22), (18, 22), (18, 23),
                         (19, 22), (19, 99)])
        self.assertEqual(implausible_ids(snap), [eid])

    def test_a_probe_stuck_at_its_power_on_value_still_files(self):
        """A DS18B20 reads 85 °C when it fails; a week of 85 is not hot."""
        snap = house()
        eid = "sensor.loft_temperature"
        plant(snap, eid, "Loft temperature", 85, platform="esphome")
        week(snap, eid, [(85, 85)] * 7)
        self.assertEqual(implausible_ids(snap), [eid])

    def test_two_days_is_not_a_history(self):
        snap = house()
        eid = "sensor.rack_sensor_temperature_2"
        plant(snap, eid, "Rack sensor Temperature 2", 86, platform="esphome",
              device=GENERIC)
        week(snap, eid, CPU_WEEK[:2])
        self.assertEqual(implausible_ids(snap), [eid])

    def test_the_cold_floor_holds_whatever_the_history(self):
        snap = house()
        eid = "sensor.rack_sensor_temperature_2"
        plant(snap, eid, "Rack sensor Temperature 2", -120,
              platform="esphome", device=GENERIC)
        week(snap, eid, CPU_WEEK)
        self.assertEqual(implausible_ids(snap), [eid])


class TestTheNightlyPassReadsTheSameHistory(unittest.TestCase):
    def attrs(self):
        return {"device_class": "temperature", "unit_of_measurement": "°C",
                "friendly_name": "Rack sensor Temperature 2"}

    def test_a_hot_series_is_learned_not_dropped(self):
        series = [{"start": NOW - i * 3600, "mean": 50.0 + (i % 24),
                   "min": 45.0 + (i % 24), "max": 55.0 + (i % 24)}
                  for i in range(24 * 7)]
        kept, dropped = baselines._without_impossible(
            series, self.attrs(), "sensor.rack_sensor_temperature_2",
            devices, House({"entities": [], "devices": []}))
        self.assertEqual(len(kept), len(series))
        self.assertIsNone(dropped)

    def test_a_room_series_with_a_broken_night_still_drops_it(self):
        series = [{"start": NOW - i * 3600, "mean": 21.0, "min": 20.0,
                   "max": 22.0} for i in range(24 * 7)]
        series[5] = {"start": NOW - 5 * 3600, "mean": 95.0, "min": 90.0,
                     "max": 99.0}
        kept, dropped = baselines._without_impossible(
            series, self.attrs(), "sensor.study_temperature", devices,
            House({"entities": [], "devices": []}))
        self.assertEqual(len(kept), len(series) - 1)
        self.assertEqual(dropped["count"], 1)


if __name__ == "__main__":
    unittest.main()
