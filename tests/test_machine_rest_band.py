#!/usr/bin/env python3
"""A machine's reading gets a band built from its hours at rest.

A house marked `base.unusual` Wrong four times about a 3D printer's nozzle
and bed (normal while printing, room temperature when idle): one
hour-of-the-week band over every hour learns WHEN somebody prints, so a
printer that prints most evenings has an evening band near its print
temperature, and the same heater at room temperature on an evening off
reads as "far outside its usual". The class is any reading on a device
that says whether it is running — a job status, or an on/off running
state — so the nightly pass builds the band from the machine's hours at
rest (`baselines.split_by_phase`), the check stands down while the machine
works and when its state cannot be read, and a reading at rest is judged
against what it reads at rest.

Driven with an oven the report never named, whose "Running" is a
`binary_sensor` of class `running` on the same device: a cavity at baking
temperature while it runs raises nothing, the cavity at room temperature
in the hour it usually bakes raises nothing, and the cavity hot with the
oven long since off still raises.
"""

import asyncio
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import baselines  # noqa: E402
import corrections  # noqa: E402
from checks import baseline as band  # noqa: E402
from checks import chores  # noqa: E402
from checks._util import House  # noqa: E402

# A Monday, 18:30 UTC: the oven bakes from 18:00 to 19:00 every day.
NOW = dt.datetime(2026, 1, 5, 18, 30, tzinfo=dt.timezone.utc).timestamp()
DAY = 86400
OVEN = {"id": "dev_oven", "name": "Kitchen oven", "manufacturer": "Neff",
        "model": "B57"}
CAVITY = "sensor.kitchen_oven_cavity_temperature"
RUNNING = "binary_sensor.kitchen_oven_running"


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat()


def states(cavity: float, running: str, *, changed: float) -> dict:
    return {
        CAVITY: {"entity_id": CAVITY, "state": str(cavity),
                 "last_changed": iso(NOW - 60), "last_updated": iso(NOW - 60),
                 "attributes": {"device_class": "temperature",
                                "state_class": "measurement",
                                "unit_of_measurement": "°C",
                                "friendly_name": "Kitchen oven Cavity "
                                                 "temperature"}},
        RUNNING: {"entity_id": RUNNING, "state": running,
                  "last_changed": iso(changed), "last_updated": iso(changed),
                  "attributes": {"device_class": "running",
                                 "friendly_name": "Kitchen oven Running"}},
    }


ENTITIES = [{"entity_id": e, "platform": "home_connect",
             "device_id": OVEN["id"]} for e in (CAVITY, RUNNING)]


def hourly() -> list[dict]:
    """28 days of hourly means: 200 °C in the 18:00 hour, room otherwise."""
    rows = []
    start = int((NOW - 28 * DAY) // 3600 * 3600)
    for ts in range(start, int(NOW // 3600 * 3600), 3600):
        hour = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).hour
        value = 200.0 + (ts // 3600) % 3 if hour == 18 else (
            21.0 + ((ts // 3600) % 3) * 0.3)
        rows.append({"start": float(ts), "mean": value})
    return rows


def running_history() -> list[dict]:
    rows = [{"entity_id": RUNNING, "state": "off",
             "last_changed": iso(NOW - 29 * DAY)}]
    for day in range(28, 0, -1):
        base = (NOW - day * DAY) // DAY * DAY
        rows.append({"state": "on", "last_changed": iso(base + 18 * 3600)})
        rows.append({"state": "off", "last_changed": iso(base + 19 * 3600)})
    return rows


class _Built(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: [os.remove(os.path.join(tmp, f))
                                 for f in os.listdir(tmp)]
                        and os.rmdir(tmp))
        old = (baselines.TZ_CACHE, baselines.fetch_hourly,
               baselines.fetch_status_history)

        def put_back():
            (baselines.TZ_CACHE, baselines.fetch_hourly,
             baselines.fetch_status_history) = old
        self.addCleanup(put_back)
        baselines.TZ_CACHE = os.path.join(tmp, "no-tz")
        self.asked = []

        async def fetch_hourly(_session, ids, _now, days=28):
            return {CAVITY: hourly()} if CAVITY in ids else {}

        async def fetch_status_history(_session, ids, _now, days=28):
            self.asked.append(list(ids))
            return {RUNNING: running_history()}

        baselines.fetch_hourly = fetch_hourly
        baselines.fetch_status_history = fetch_status_history
        live = states(21.0, "off", changed=NOW - 3 * 3600)
        house = House({"states": live, "entities": ENTITIES,
                       "devices": [OVEN]})
        self.payload = asyncio.run(baselines.build(
            None, live, NOW, path=os.path.join(tmp, "b.json"),
            entities=ENTITIES, house=house, machine=chores))
        self.built = self.payload["entities"][CAVITY]

    def judge(self, cavity: float, running: str, changed: float) -> list:
        snap = {"now": NOW, "states": states(cavity, running, changed=changed),
                "entities": ENTITIES, "devices": [OVEN], "areas": [],
                "_trail": [],
                "corrections": {"entity": {}, "area": {}, "check": {},
                                "never": {"checks": sorted(
                                    corrections.NEVER_CHECKS)}},
                "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                              "days": 28,
                              "entities": {CAVITY: self.built}}}
        self.trail = snap["_trail"]
        return [r["entity_id"] for r in band.unusual(snap, NOW)]


class TestTheBandIsBuiltFromTheHoursAtRest(unittest.TestCase):
    def test_a_running_state_is_the_machines_status(self):
        house = House({"states": states(200.0, "on", changed=NOW - 900),
                       "entities": ENTITIES, "devices": [OVEN]})
        self.assertEqual(chores.status_entity(house, CAVITY), RUNNING)
        self.assertEqual(chores.machine_status(house, CAVITY)[0], "working")
        house = House({"states": states(21.0, "off", changed=NOW - 7200),
                       "entities": ENTITIES, "devices": [OVEN]})
        self.assertEqual(chores.machine_status(house, CAVITY)[0], "idle")

    def test_an_hour_it_worked_in_is_set_aside(self):
        rows = [{"start": 0.0, "mean": 21.0}, {"start": 3600.0, "mean": 200.0},
                {"start": 7200.0, "mean": 90.0},
                {"start": 14400.0, "mean": 21.0}]
        timeline = [(-9000.0, "idle"), (3600.0, "working"), (6000.0, "idle")]
        rest, working = baselines.split_by_phase(rows, timeline)
        # The hour after it stopped is still cooling: neither.
        self.assertEqual([r["start"] for r in rest], [0.0, 14400.0])
        self.assertEqual(working, 1)

    def test_an_hour_the_history_does_not_cover_is_neither(self):
        rest, working = baselines.split_by_phase(
            [{"start": 0.0, "mean": 21.0}], [(1800.0, "idle")])
        self.assertEqual((rest, working), ([], 0))


class TestTheNightlyPassAndTheCheck(_Built):
    def test_the_pass_asks_for_the_status_and_keeps_only_rest_hours(self):
        self.assertEqual(self.asked, [[RUNNING]])
        self.assertEqual(self.built["by_state"]["status"], RUNNING)
        self.assertGreater(self.built["by_state"]["working_hours"], 20)
        self.assertLess(self.built["overall"]["median"], 30)

    def test_baking_while_it_runs_raises_nothing(self):
        self.assertEqual(self.judge(205.0, "on", NOW - 1800), [])

    def test_room_temperature_in_the_hour_it_usually_bakes_raises_nothing(self):
        self.assertEqual(self.judge(21.0, "off", NOW - 3 * 3600), [])

    def test_hot_long_after_it_stopped_still_raises(self):
        self.assertEqual(self.judge(180.0, "off", NOW - 3 * 3600), [CAVITY])

    def test_a_running_state_that_cannot_be_read_stands_down(self):
        self.assertEqual(self.judge(180.0, "unavailable", NOW - 3 * 3600), [])
        said = [w for w in self.trail if w.get("subject") == CAVITY]
        self.assertTrue(said and "at rest" in said[0]["reason"], self.trail)


if __name__ == "__main__":
    unittest.main()
