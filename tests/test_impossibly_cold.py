#!/usr/bin/env python3
"""A temperature colder than anything in a house can be is a broken sensor.

#337: an outdoor equipment thermometer — named for a part of a heat pump,
so the hot-sensor gate lifted the ambient bound off it — read −150 °F
overnight, slid to −81 °F and jumped to +18 °F at 7am, while the house's
outdoor reference read 54 °F. Nothing called it impossible; the baseline
learned the night as normal, and `base.unusual` filed the morning with
"look for something added near it".

A heater may read far above room air, but nothing in a house reads below
the coldest air on earth, so the cold floor holds for every temperature
that is not cold storage. Readings past it are kept out of the baseline,
the sensor is filed once by `dev.implausible` as likely faulty — while
it reads impossibly and for a while after — and `base.unusual` leaves it
to that row.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import baselines  # noqa: E402
import checks  # noqa: E402
from checks import baseline as base_check  # noqa: E402
from checks import devices  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402

EID = "sensor.heat_pump_compressor_temperature"
HOUR = 3600.0


def coil(state):
    return {"state": str(state), "last_updated": iso(600),
            "last_changed": iso(600),
            "attributes": {"device_class": "temperature",
                           "unit_of_measurement": "°F",
                           "state_class": "measurement",
                           "friendly_name": "Heat pump compressor temperature"}}


def snap_with(state, **over):
    snap = house(**over)
    snap["states"][EID] = coil(state)
    snap["states"]["sensor.outdoor_temperature"] = {
        "state": "54", "last_updated": iso(600),
        "attributes": {"device_class": "temperature",
                       "unit_of_measurement": "°F",
                       "friendly_name": "Outdoor temperature"}}
    snap["thermal"] = {**(snap.get("thermal") or {}),
                       "outdoor": "sensor.outdoor_temperature"}
    return snap


def night_series(start):
    """Two weeks of a plausible 40–60 °F swing, then a night at −150 °F
    sliding to −81 °F."""
    rows = []
    for i in range(14 * 24):
        rows.append({"start": start + i * HOUR,
                     "mean": 50.0 + 10.0 * ((i % 24) / 24.0 - 0.5)})
    for j, v in enumerate((-150.0, -140.0, -120.0, -100.0, -81.0)):
        rows.append({"start": start + (14 * 24 + j) * HOUR, "mean": v})
    return rows


class TestAHeatersGateDoesNotLiftTheColdFloor(unittest.TestCase):
    def test_minus_150_is_impossible_even_on_a_hot_named_sensor(self):
        for value in (-150, -81):
            snap = snap_with(value)
            found = devices.implausible(snap, NOW)
            self.assertEqual([f["entity_id"] for f in found], [EID], value)
            self.assertIn("faulty", found[0]["fix"])

    def test_the_detail_says_what_it_is_outside(self):
        found = devices.implausible(snap_with(-150), NOW)
        self.assertIn("Outdoor temperature reads 54", found[0]["detail"])

    def test_a_hot_sensor_reading_hot_is_still_fine(self):
        self.assertEqual(devices.implausible(snap_with(180), NOW), [])
        self.assertEqual(devices.implausible(snap_with(-10), NOW), [])

    def test_a_freezer_is_cold_storage_not_a_fault(self):
        snap = house()
        snap["states"]["sensor.lab_freezer_temperature"] = {
            "state": "-80", "last_updated": iso(600),
            "attributes": {"device_class": "temperature",
                           "unit_of_measurement": "°C",
                           "friendly_name": "Lab freezer temperature"}}
        self.assertEqual(devices.implausible(snap, NOW), [])

    def test_the_clean_house_is_silent(self):
        self.assertEqual(devices.implausible(house(), NOW), [])


class TestTheNightIsKeptOutOfTheBaseline(unittest.IsolatedAsyncioTestCase):
    async def test_build_drops_impossible_readings_and_says_so(self):
        import tempfile
        start = NOW - 15 * 86400
        rows = night_series(start)

        async def fetch(_session, ids, _now, days=baselines.HISTORY_DAYS):
            return {EID: rows}

        old = baselines.fetch_hourly
        baselines.fetch_hourly = fetch
        try:
            with tempfile.TemporaryDirectory() as tmp:
                payload = await baselines.build(
                    None, {EID: coil(18)}, now=NOW, path=f"{tmp}/b.json")
        finally:
            baselines.fetch_hourly = old
        built = payload["entities"][EID]
        self.assertGreater(built["overall"]["median"], 30.0)
        self.assertEqual(built["impossible"]["count"], 5)
        self.assertEqual(built["impossible"]["lowest"], -150.0)
        self.assertGreater(built["impossible"]["last"], start)


class TestTheMorningAfterIsOneRow(unittest.TestCase):
    def morning(self):
        """+18 °F at 7am, against a baseline that remembers last night."""
        snap = snap_with(18)
        bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
        snap["baselines"] = {
            "built_at": int(NOW - 3600), "tz": "UTC", "days": 28,
            "entities": {EID: {
                "unit": "°F", "samples": 400,
                "overall": {"median": 50.0, "spread": 2.0, "n": 400},
                "buckets": {bucket: {"median": 50.0, "spread": 2.0, "n": 4}},
                "impossible": {"count": 5, "lowest": -150.0,
                               "last": NOW - 3 * HOUR},
            }}}
        return snap

    def test_dev_implausible_files_the_sensor_once(self):
        result = checks.run_all(self.morning(), NOW,
                                only=["dev.implausible", "base.unusual"])
        rows = [f for f in result["findings"] if f["entity_id"] == EID]
        self.assertEqual([f["source"] for f in rows],
                         ["check:dev.implausible"])
        self.assertIn("-150", rows[0]["detail"].replace("−", "-"))

    def test_base_unusual_leaves_it_to_that_row(self):
        self.assertEqual(base_check.unusual(self.morning(), NOW), [])

    def test_a_week_later_the_night_is_forgotten(self):
        snap = self.morning()
        snap["baselines"]["entities"][EID]["impossible"]["last"] = (
            NOW - 8 * 86400)
        self.assertEqual(devices.implausible(snap, NOW), [])


if __name__ == "__main__":
    unittest.main()
