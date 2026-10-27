#!/usr/bin/env python3
"""A machine's own reading is not judged against its band while it runs.

A house marked `base.unusual` Wrong about a 3D printer's nozzle and bed:
430 °F and 150 °F during a print against an hour-of-the-week band centred
near room temperature. The printer was handled (its heaters are judged by
`base.heater_idle`), but the class was not: ANY sensor on a device whose
own status entity speaks the job vocabulary (`chores.machine_status` — a
dishwasher's operation state, a washer's, a kettle's) moves with the job,
and one band built over every hour cannot tell a wash from a fault.

So `base.unusual` stands down for a reading while the machine it belongs
to says it is working, and compares it as before while the machine says
idle or finished, or when the status cannot be read. Driven through the
real check with a dishwasher — a machine the report never named — whose
water temperature is not a power reading, so the cycling-machine rule
(`chores.cycling_machine`, power and energy only) does not cover it.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import baselines  # noqa: E402
import corrections  # noqa: E402
from checks import baseline as band  # noqa: E402

NOW = dt.datetime(2026, 1, 5, 10, 0, tzinfo=dt.timezone.utc).timestamp()
DISHWASHER = {"id": "dev_dishwasher", "name": "Kitchen dishwasher",
              "manufacturer": "Bosch", "model": "SMV4"}
WATER = "sensor.kitchen_dishwasher_water_temperature"
STATE = "sensor.kitchen_dishwasher_operation_state"


def iso(seconds_ago: float) -> str:
    return dt.datetime.fromtimestamp(NOW - seconds_ago,
                                     tz=dt.timezone.utc).isoformat()


def dishwasher(word: str, *, water: float = 55.0) -> dict:
    """A dishwasher device: its operation state (Home Connect's enum) and a
    water temperature whose band was built mostly while it sat at rest."""
    snap = {"now": NOW, "states": {}, "entities": [], "devices": [DISHWASHER],
            "areas": [], "_trail": [],
            "corrections": {"entity": {}, "area": {}, "check": {},
                            "never": {"checks": sorted(
                                corrections.NEVER_CHECKS)}},
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": {}}}
    snap["states"][STATE] = {
        "state": word, "last_changed": iso(7200), "last_updated": iso(7200),
        "attributes": {"friendly_name": "Kitchen dishwasher Operation state",
                       "options": ["ready", "run", "finished"]}}
    snap["states"][WATER] = {
        "state": str(water), "last_changed": iso(600),
        "last_updated": iso(60),
        "attributes": {"device_class": "temperature",
                       "state_class": "measurement",
                       "unit_of_measurement": "°C",
                       "friendly_name": "Kitchen dishwasher Water temperature"}}
    for eid in (STATE, WATER):
        snap["entities"].append({"entity_id": eid, "platform": "home_connect",
                                 "device_id": DISHWASHER["id"]})
    bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
    snap["baselines"]["entities"][WATER] = {
        "unit": "°C", "samples": 672,
        "overall": {"median": 21.0, "spread": 0.5, "n": 672},
        "buckets": {bucket: {"median": 21.0, "spread": 0.5, "n": 4}}}
    return snap


def unusual_ids(snap: dict) -> list[str]:
    return [r["entity_id"] for r in band.unusual(snap, NOW)]


class TestWhileTheMachineRunsItsReadingIsNotNews(unittest.TestCase):
    def test_hot_water_while_the_dishwasher_runs_raises_nothing(self):
        self.assertEqual(unusual_ids(dishwasher("run")), [])

    def test_the_stand_down_is_written_on_the_trail(self):
        snap = dishwasher("BSH.Common.EnumType.OperationState.Run")
        self.assertEqual(unusual_ids(snap), [])
        said = [w for w in snap["_trail"]
                if w.get("subject") == WATER and w.get("check") == "base.unusual"]
        self.assertTrue(said, snap["_trail"])
        self.assertIn("running", said[0]["reason"])


class TestAtRestTheSameReadingStillRaises(unittest.TestCase):
    def test_hot_water_while_finished(self):
        self.assertEqual(unusual_ids(dishwasher("finished")), [WATER])

    def test_hot_water_while_ready(self):
        self.assertEqual(unusual_ids(dishwasher("ready")), [WATER])

    def test_a_status_that_cannot_be_read_stands_nothing_down(self):
        self.assertEqual(unusual_ids(dishwasher("unavailable")), [WATER])


if __name__ == "__main__":
    unittest.main()
