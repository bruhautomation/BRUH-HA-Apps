#!/usr/bin/env python3
"""`base.unusual` and `forecast.decline` spend their row cap on houses.

Both checks say nothing at all past their row cap, so every reading that
is not a measurement of the house — a weather integration's forecast, a
print job's progress, a runtime counter that resets at midnight, a
setpoint somebody typed, the grid's carbon intensity, brAIn's own
sensors — was a row the cap counted. A handful of them standing beside
one real fault was enough to take the real fault down with them. These
drive the real checks over a snapshot carrying exactly that.
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

# (entity id, friendly name, platform, extra attributes). Generic names;
# each is one of the kinds the check has no business reading.
NOT_THE_HOUSE = [
    ("sensor.sky_cloud_cover", "Cloud cover", "astroweather",
     {"unit_of_measurement": "%"}),
    ("sensor.printer_progress", "Printer print progress", "",
     {"unit_of_measurement": "%"}),
    ("sensor.printer_bed", "Bed", "octoprint",
     {"unit_of_measurement": "°C", "device_class": "temperature"}),
    ("sensor.pump_runtime_today", "Pump runtime today", "",
     {"unit_of_measurement": "%"}),
    ("sensor.time_at_home", "Time at home", "",
     {"unit_of_measurement": "h"}),
    ("sensor.hall_target_temperature", "Hall target temperature", "",
     {"unit_of_measurement": "°C", "device_class": "temperature"}),
    ("sensor.grid_intensity", "Grid intensity", "",
     {"unit_of_measurement": "gCO2eq/kWh"}),
    ("sensor.brain_session", "Session used", "brain",
     {"unit_of_measurement": "%"}),
]
REAL = ("sensor.freezer", "Freezer", "", {
    "unit_of_measurement": "°C", "device_class": "temperature"})


def snapshot(rows, *, trend=None):
    bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
    states, registry, store = {}, [], {}
    for eid, name, platform, attrs in rows:
        states[eid] = {"state": "40", "attributes": {
            "state_class": "measurement", "friendly_name": name, **attrs},
            "last_changed": "", "last_updated": ""}
        registry.append({"entity_id": eid, "name": name,
                         "platform": platform})
        entry = {"unit": attrs.get("unit_of_measurement", ""),
                 "samples": 672,
                 "overall": {"median": 20.0, "spread": 0.5, "n": 672},
                 "buckets": {bucket: {"median": 20.0, "spread": 0.5,
                                      "n": 4}}}
        if trend:
            entry["trend"] = dict(trend)
        store[eid] = entry
    return {"now": NOW, "states": states, "entities": registry,
            "devices": [], "areas": [],
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": store}}


DRIFT = {"per_day": 0.4, "move": 12.0, "days": 28.0, "noise": 0.4,
         "spreads": 20.0, "consistent": True, "points": 672}


class TestTheCapIsSpentOnTheHouse(unittest.TestCase):

    def test_the_fixture_is_past_both_caps(self):
        """Without the exclusions the cap is what decides, so the test is
        only worth having while the non-house rows alone overflow it."""
        self.assertGreater(len(NOT_THE_HOUSE), band.MAX_ROWS)
        self.assertGreater(len(NOT_THE_HOUSE), forecasts.DECLINE_MAX_ROWS)

    def test_unusual_still_finds_the_real_fault(self):
        found = band.unusual(snapshot([REAL, *NOT_THE_HOUSE]), NOW)
        self.assertEqual([r["entity_id"] for r in found], ["sensor.freezer"])

    def test_decline_still_finds_the_real_drift(self):
        # One thermometer only: two of a class drifting together is
        # still allowed, and the printer bed and target are temperatures.
        found = forecasts.decline(
            snapshot([REAL, *NOT_THE_HOUSE], trend=DRIFT), NOW)
        self.assertEqual([r["entity_id"] for r in found], ["sensor.freezer"])

    def test_each_kind_is_refused_on_its_own(self):
        for row in NOT_THE_HOUSE:
            with self.subTest(row=row[0]):
                self.assertEqual(band.unusual(snapshot([row]), NOW), [])
                self.assertEqual(
                    forecasts.decline(snapshot([row], trend=DRIFT), NOW), [])

    def test_the_reason_is_said(self):
        from checks._util import House  # noqa: PLC0415
        snap = snapshot(NOT_THE_HOUSE)
        house = House(snap)
        for eid, *_ in NOT_THE_HOUSE:
            with self.subTest(eid=eid):
                self.assertTrue(band.not_a_house_reading(
                    house, eid, snap["states"][eid]))

    def test_a_real_reading_is_still_a_reading(self):
        from checks._util import House  # noqa: PLC0415
        snap = snapshot([REAL])
        self.assertEqual(band.not_a_house_reading(
            House(snap), "sensor.freezer", snap["states"]["sensor.freezer"]),
            "")


if __name__ == "__main__":
    unittest.main()
