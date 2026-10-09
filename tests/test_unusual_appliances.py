#!/usr/bin/env python3
"""A machine that cycles is judged by its own on/off shape, not an hourly mean.

A dehumidifier's power sensor that runs ~700 W for about three hours most
mornings was filed by `base.unusual` as "218,300 times its normal
variation" against a usual 0.07 W — the hour-of-the-week band averages a
bimodal draw into a number it is never at. `appliances.py` already holds a
measured profile for exactly that sensor (idle, busy, threshold), and it is
the authority on a cycling machine. So both checks that share `eligible`
stand down for an entity the appliance store has a profile for, read off
the snapshot the pass already holds.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import baselines  # noqa: E402
from checks import baseline as band  # noqa: E402
from checks import forecasts  # noqa: E402

NOW = dt.datetime(2026, 1, 5, 10, 0, tzinfo=dt.timezone.utc).timestamp()
DEHUM = "sensor.dehumidifier_power"


def snapshot(*, profiled: bool, trend: dict | None = None) -> dict:
    bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
    states = {DEHUM: {"state": "702.4", "attributes": {
        "state_class": "measurement", "device_class": "power",
        "unit_of_measurement": "W", "friendly_name": "Dehumidifier power"},
        "last_changed": "", "last_updated": ""}}
    entry = {"unit": "W", "samples": 672,
             "overall": {"median": 0.4, "spread": 0.07, "n": 672},
             "buckets": {bucket: {"median": 0.4, "spread": 0.07, "n": 4}}}
    if trend:
        entry["trend"] = dict(trend)
    snap = {"now": NOW, "states": states,
            "entities": [{"entity_id": DEHUM, "name": "Dehumidifier power",
                          "platform": "shelly"}],
            "devices": [], "areas": [],
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": {DEHUM: entry}},
            "appliances": {"built_at": int(NOW - 3600), "entities": {},
                           "recent": {}}}
    if profiled:
        snap["appliances"]["entities"][DEHUM] = {
            "name": "Dehumidifier power", "idle_w": 0.4, "busy_w": 700.0,
            "threshold_w": 175.3, "settle_min": 10.0, "runs": 12,
            "built_at": int(NOW - 3600)}
    return snap


class TestAProfiledMachineIsNotUnusual(unittest.TestCase):
    def test_an_unprofiled_power_sensor_at_700w_is_still_reported(self):
        rows = band.unusual(snapshot(profiled=False), NOW)
        self.assertEqual([r["entity_id"] for r in rows], [DEHUM])

    def test_a_profiled_one_at_its_running_level_is_not(self):
        self.assertEqual(band.unusual(snapshot(profiled=True), NOW), [])

    def test_a_snapshot_with_no_appliance_store_reports_as_before(self):
        snap = snapshot(profiled=False)
        snap.pop("appliances")
        self.assertEqual([r["entity_id"] for r in band.unusual(snap, NOW)],
                         [DEHUM])

    def test_the_reason_is_named(self):
        from checks._util import House
        snap = snapshot(profiled=True)
        house = House(snap)
        why = band.not_a_house_reading(house, DEHUM, snap["states"][DEHUM])
        self.assertIn("appliance", why)

    def test_the_drift_check_shares_the_rule(self):
        drift = {"per_day": 20.0, "move": 600.0, "days": 28.0, "noise": 5.0,
                 "spreads": 40.0, "consistent": True, "points": 672}
        self.assertTrue(forecasts.decline(
            snapshot(profiled=False, trend=drift), NOW))
        self.assertEqual(forecasts.decline(
            snapshot(profiled=True, trend=drift), NOW), [])


if __name__ == "__main__":
    unittest.main()
