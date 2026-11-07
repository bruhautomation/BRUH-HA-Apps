#!/usr/bin/env python3
"""A reading on a machine is learned and judged by what the machine was doing.

A house had a 3D printer's bed filed as far outside its usual range: the
band was built over every hour, printing and idle alike, so an hour the
printer usually prints had a usual of 45 °C and an idle bed at room
temperature was "far below" it — and a status published as an on/off
`running` sensor, not a word, was never read at all, so a print read as a
fault. Both are the class `base.unusual` already stood down for while a job
status said working (`tests/test_running_machine_readings.py`), done half:

* a `binary_sensor` of class `running` on the device is a status too
  (`chores.machine_status`), on is working and off is idle;
* the nightly pass splits a sensor's hours by its device's status and keeps
  a band for each (`baselines.build`'s `by_state`), and the check judges a
  reading against the band of the state the machine is in now.

So a print-time reading raises nothing, an idle bed at room temperature
raises nothing, and a hot bed on an idle printer still does. Driven with a
printer nothing names as one (no printer integration or word: only its
status says it prints) and, second, a dishwasher whose only status is a
`running` binary sensor.
"""

import asyncio
import datetime as dt
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import baselines  # noqa: E402
import corrections  # noqa: E402
from checks import baseline as band  # noqa: E402
from checks import chores  # noqa: E402
from checks._util import House  # noqa: E402

NOW = dt.datetime(2026, 1, 5, 10, 0, tzinfo=dt.timezone.utc).timestamp()
BUCKET = str(baselines.hour_of_week(NOW, dt.timezone.utc))
WORKSHOP = {"id": "dev_workshop", "name": "Workshop machine",
            "manufacturer": "Homebuilt", "model": "Mk2"}
BED = "sensor.workshop_machine_bed_temperature"
STATUS = "sensor.workshop_machine_print_status"
DISHWASHER = {"id": "dev_dw", "name": "Kitchen dishwasher",
              "manufacturer": "Bosch", "model": "SMV4"}
WATER = "sensor.kitchen_dishwasher_water_temperature"
RUNNING = "binary_sensor.kitchen_dishwasher_running"


def iso(seconds_ago: float) -> str:
    return dt.datetime.fromtimestamp(NOW - seconds_ago,
                                     tz=dt.timezone.utc).isoformat()


def snapshot(device, status, status_state, status_attrs, reading, value,
             baseline, platform="mqtt"):
    snap = {"now": NOW, "states": {}, "entities": [], "devices": [device],
            "areas": [], "_trail": [],
            "corrections": {"entity": {}, "area": {}, "check": {},
                            "never": {"checks": sorted(
                                corrections.NEVER_CHECKS)}},
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": {reading: baseline}}}
    snap["states"][status] = {
        "state": status_state, "last_changed": iso(7200),
        "last_updated": iso(7200), "attributes": status_attrs}
    snap["states"][reading] = {
        "state": str(value), "last_changed": iso(600),
        "last_updated": iso(60),
        "attributes": {"device_class": "temperature",
                       "state_class": "measurement",
                       "unit_of_measurement": "°C",
                       "friendly_name": "Bed temperature"}}
    for eid in (status, reading):
        snap["entities"].append({"entity_id": eid, "platform": platform,
                                 "device_id": device["id"]})
    return snap


def mixed(median, spread=1.0):
    return {"median": median, "spread": spread, "n": 4}


def printer(word, bed, by_state=True):
    """Hours this printer usually prints, so the mixed band's usual is hot."""
    baseline = {"unit": "°C", "samples": 672,
                "overall": {"median": 40.0, "spread": 2.0, "n": 672},
                "buckets": {BUCKET: mixed(45.0, 1.0)}}
    if by_state:
        baseline["status"] = STATUS
        baseline["by_state"] = {
            "working": {"overall": {"median": 45.0, "spread": 1.0, "n": 300},
                        "buckets": {BUCKET: mixed(45.0)}, "samples": 300},
            "idle": {"overall": {"median": 21.0, "spread": 0.5, "n": 372},
                     "buckets": {}, "samples": 372}}
    return snapshot(WORKSHOP, STATUS, word,
                    {"friendly_name": "Print status",
                     "options": ["idle", "printing", "finished"]},
                    BED, bed, baseline)


def dishwasher(on, water):
    baseline = {"unit": "°C", "samples": 672,
                "overall": {"median": 21.0, "spread": 0.5, "n": 672},
                "buckets": {BUCKET: mixed(21.0, 0.5)}}
    return snapshot(DISHWASHER, RUNNING, "on" if on else "off",
                    {"device_class": "running",
                     "friendly_name": "Kitchen dishwasher Running"},
                    WATER, water, baseline, platform="home_connect")


def filed(snap):
    return [r["entity_id"] for r in band.unusual(snap, NOW)]


class TestARunningSensorIsAStatus(unittest.TestCase):
    def test_on_is_working_off_is_idle(self):
        self.assertEqual(chores.machine_status(
            House(dishwasher(True, 55.0)), WATER)[0], "working")
        self.assertEqual(chores.machine_status(
            House(dishwasher(False, 21.0)), WATER)[0], "idle")
        self.assertEqual(chores.status_entity(
            House(dishwasher(False, 21.0)), WATER), RUNNING)

    def test_hot_water_mid_wash_raises_nothing(self):
        self.assertEqual(filed(dishwasher(True, 55.0)), [])

    def test_hot_water_with_the_dishwasher_off_still_does(self):
        self.assertEqual(filed(dishwasher(False, 55.0)), [WATER])


class TestEachStateIsJudgedByItsOwnBand(unittest.TestCase):
    def test_a_print_time_reading_raises_nothing(self):
        self.assertEqual(filed(printer("printing", 45.5)), [])

    def test_an_idle_bed_at_room_temperature_raises_nothing(self):
        # Against the mixed band this hour's usual is 45 °C.
        self.assertEqual(filed(printer("idle", 21.0, by_state=False)), [BED])
        self.assertEqual(filed(printer("idle", 21.0)), [])

    def test_a_hot_bed_on_an_idle_printer_still_raises(self):
        snap = printer("idle", 45.0)
        rows = band.unusual(snap, NOW)
        self.assertEqual([r["entity_id"] for r in rows], [BED])
        self.assertIn("not running", rows[0]["detail"])

    def test_a_runaway_heater_mid_print_is_judged_by_the_print_band(self):
        self.assertEqual(filed(printer("printing", 58.0)), [BED])


class TestTheNightlyPassLearnsEachState(unittest.TestCase):
    def test_hours_are_split_by_what_the_status_said(self):
        start = NOW - 28 * 86400
        rows, history = [], []
        for hour in range(28 * 24):
            ts = start + hour * 3600
            printing = hour % 24 in (18, 19, 20)
            wobble = 1 if (hour // 24) % 2 else -1
            rows.append({"start": ts, "mean": (60.0 + 0.5 * wobble) if printing
                         else (21.0 + 0.3 * wobble)})
            history.append({"state": "printing" if printing else "idle",
                            "last_changed": dt.datetime.fromtimestamp(
                                ts, tz=dt.timezone.utc).isoformat()})
        states = {
            BED: {"state": "21", "attributes": {
                "device_class": "temperature", "state_class": "measurement",
                "unit_of_measurement": "°C"}},
            STATUS: {"state": "idle", "attributes": {
                "friendly_name": "Print status",
                "options": ["idle", "printing", "finished"]}}}
        house = House({"states": states, "devices": [WORKSHOP],
                       "entities": [{"entity_id": e, "platform": "mqtt",
                                     "device_id": WORKSHOP["id"]}
                                    for e in (BED, STATUS)]})
        asked = {}

        async def hourly(session, ids, now, days=baselines.HISTORY_DAYS):
            return {BED: rows}

        async def statuses(session, ids, now, days=baselines.HISTORY_DAYS):
            asked["ids"] = list(ids)
            return {STATUS: history}

        olds = (baselines.fetch_hourly, baselines.fetch_status_history,
                baselines.house_timezone)
        baselines.fetch_hourly = hourly
        baselines.fetch_status_history = statuses
        baselines.house_timezone = lambda path=None: (dt.timezone.utc, "UTC")
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                payload = asyncio.run(baselines.build(
                    None, states, NOW, path=f"{tmp}/b.json", house=house,
                    machines=chores))
        finally:
            (baselines.fetch_hourly, baselines.fetch_status_history,
             baselines.house_timezone) = olds
        self.assertEqual(asked["ids"], [STATUS])
        built = payload["entities"][BED]
        self.assertEqual(built["status"], STATUS)
        self.assertEqual(built["by_state"]["working"]["overall"]["median"],
                         60.0)
        self.assertEqual(built["by_state"]["idle"]["overall"]["median"], 21.0)


if __name__ == "__main__":
    unittest.main()
