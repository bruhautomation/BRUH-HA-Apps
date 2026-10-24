#!/usr/bin/env python3
"""A broken probe is not the season, and the trail says which it was.

A temperature probe swinging every day between a room's reading and a value
no thermometer can read was let through `base.unusual` six times as "in line
with where the last 7 days have been at this hour — the season or the
weather", while `dev.implausible` filed the same sensor as faulty the same
night. The hourly MEAN of an hour that dipped to −150 °F is a possible
number, so the nightly pass kept those hours, built the recent level out of
them, and the drift guard excused the probe with its own broken week. And
the trail recorded that excuse as `cap` — "a check gave up: too many at
once" — which is a different reason altogether.

Driven through the real nightly build (statistics fetch stubbed) into the
real checks.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import baselines  # noqa: E402
import decision_trail  # noqa: E402
from checks import baseline as band  # noqa: E402
from checks import devices  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402
from test_unusual_recent_season import SEASON, _snap  # noqa: E402

HOUR = 3600.0
PROBE = "sensor.garage_probe_temperature"


def probe_rows():
    """A month at about 60 °F, then a week at 75 °F in which one hour a day
    dipped to −150 °F and back: every hourly mean is possible, every one of
    those hours' minimum is not."""
    rows = []
    start = int(NOW // HOUR) * HOUR - 28 * 86400
    for i in range(28 * 24):
        t = start + i * HOUR
        if t < NOW - 7 * 86400:
            rows.append({"start": t, "mean": 60.0 + (i % 3) * 0.3,
                         "min": 59.5, "max": 61.0})
        elif int((t // HOUR) % 24) == 3:
            rows.append({"start": t, "mean": 40.0, "min": -150.0,
                         "max": 76.0})
        else:
            rows.append({"start": t, "mean": 75.0 + (i % 3) * 0.3,
                         "min": 74.5, "max": 76.0})
    return rows


def probe_state(value):
    return {"state": str(value), "last_changed": iso(60),
            "last_updated": iso(60),
            "attributes": {"friendly_name": "Garage probe temperature",
                           "device_class": "temperature",
                           "unit_of_measurement": "°F",
                           "state_class": "measurement"}}


def build_store():
    states = {PROBE: probe_state(75.2)}
    original = baselines.fetch_hourly

    async def fake(session, ids, now, days=baselines.HISTORY_DAYS):
        return {i: probe_rows() for i in ids if i == PROBE}

    baselines.fetch_hourly = fake
    try:
        with tempfile.TemporaryDirectory() as tmp:
            return asyncio.run(baselines.build(
                None, states, NOW, path=os.path.join(tmp, "b.json"),
                ranges=devices,
                house=House({"entities": [{"entity_id": PROBE,
                                           "platform": "zha"}],
                             "devices": []})))
    finally:
        baselines.fetch_hourly = original


class TestTheBrokenHoursAreLeftOut(unittest.TestCase):
    def setUp(self):
        self.entry = build_store()["entities"][PROBE]

    def test_an_hour_whose_minimum_was_impossible_is_recorded(self):
        seen = self.entry.get("impossible") or {}
        self.assertEqual(seen.get("count"), 7)
        self.assertEqual(seen.get("lowest"), -150.0)
        self.assertGreater(seen.get("last") or 0, NOW - 86400 * 2)

    def test_the_recent_level_is_not_built_from_them(self):
        recent = self.entry.get("recent") or {}
        # A week of hourly readings less the seven broken hours.
        self.assertEqual(recent.get("n"), 7 * 24 - 7)


class TestTheDriftGuardDoesNotExcuseAFaultySensor(unittest.TestCase):
    def snap(self):
        snap = house()
        snap["_trail"] = []
        snap["states"][PROBE] = probe_state(75.2)
        snap["entities"].append({"entity_id": PROBE, "platform": "zha"})
        snap["baselines"]["entities"] = {PROBE: build_store()["entities"][PROBE]}
        return snap

    def test_unusual_says_nothing_and_the_trail_names_the_fault(self):
        snap = self.snap()
        self.assertEqual(band.unusual(snap, NOW), [])
        kinds = [w["kind"] for w in snap["_trail"] if w["subject"] == PROBE]
        self.assertEqual(kinds, ["claimed"])
        self.assertIn("faulty", snap["_trail"][0]["reason"])

    def test_implausible_files_it(self):
        snap = self.snap()
        self.assertEqual(
            [r["entity_id"] for r in devices.implausible(snap, NOW)], [PROBE])

    def test_a_reading_impossible_right_now_is_claimed_too(self):
        snap = self.snap()
        snap["states"][PROBE] = probe_state(-150)
        self.assertEqual(band.unusual(snap, NOW), [])
        self.assertEqual([w["kind"] for w in snap["_trail"]], ["claimed"])


class TestEachStandDownSaysItsOwnReason(unittest.TestCase):
    def kinds(self, snap):
        return [w["kind"] for w in snap["_trail"]]

    def test_in_line_with_the_last_week_is_drift(self):
        snap = _snap(70.2, SEASON)
        snap["_trail"] = []
        self.assertEqual(band.unusual(snap, NOW), [])
        self.assertEqual(self.kinds(snap), ["drift"])

    def test_several_of_one_kind_moving_together_is_drift(self):
        snap = house()
        snap["_trail"] = []
        bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
        for i in range(3):
            eid = f"sensor.room_{i}_humidity"
            snap["states"][eid] = {
                "state": "20", "last_changed": iso(60),
                "attributes": {"friendly_name": f"Room {i} humidity",
                               "device_class": "humidity",
                               "unit_of_measurement": "%",
                               "state_class": "measurement"}}
            snap["entities"].append({"entity_id": eid, "platform": "zha"})
            snap["baselines"]["entities"][eid] = {
                "unit": "%", "samples": 672,
                "overall": {"median": 50.0, "spread": 1.0, "n": 672},
                "buckets": {bucket: {"median": 50.0, "spread": 1.0, "n": 4}}}
        self.assertEqual(band.unusual(snap, NOW), [])
        self.assertEqual(set(self.kinds(snap)), {"drift"})

    def test_only_a_limit_that_fired_is_a_cap(self):
        snap = house()
        snap["_trail"] = []
        bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
        # Different kinds, so nothing moved together: only the cap is left.
        kinds = [("temperature", "°C", "40"), ("humidity", "%", "95"),
                 ("pressure", "hPa", "1080"), ("carbon_dioxide", "ppm", "3000"),
                 ("power", "W", "5000")]
        for klass, unit, value in kinds:
            eid = f"sensor.attic_{klass}"
            snap["states"][eid] = {
                "state": value, "last_changed": iso(60),
                "attributes": {"friendly_name": f"Attic {klass}",
                               "device_class": klass,
                               "unit_of_measurement": unit,
                               "state_class": "measurement"}}
            snap["entities"].append({"entity_id": eid, "platform": "zha"})
            median = float(value) / 2
            snap["baselines"]["entities"][eid] = {
                "unit": unit, "samples": 672,
                "overall": {"median": median, "spread": 1.0, "n": 672},
                "buckets": {bucket: {"median": median, "spread": 1.0,
                                     "n": 4}}}
        self.assertGreater(len(kinds), band.MAX_ROWS)
        self.assertEqual(band.unusual(snap, NOW), [])
        self.assertEqual(set(self.kinds(snap)), {"cap"})


class TestTheVocabularySaysWhatDriftMeans(unittest.TestCase):
    def test_drift_is_a_kind_with_its_own_meaning(self):
        for kind in ("drift", "claimed", "explained"):
            self.assertIn(kind, decision_trail.KINDS)
            self.assertNotEqual(decision_trail.KINDS[kind],
                                decision_trail.KINDS["cap"])
            self.assertIn(kind, decision_trail.FOLD_KINDS)

    def test_the_trail_reads_a_drift_row_back_with_its_meaning(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = decision_trail.TRAIL_FILE
            decision_trail.TRAIL_FILE = os.path.join(tmp, "d.jsonl")
            decision_trail._RECENT.clear()
            try:
                decision_trail.note("drift", "sensor.loft", "the season",
                                    check="base.unusual", now=NOW)
                got = decision_trail.for_subject("sensor.loft")
            finally:
                decision_trail.TRAIL_FILE = old
        self.assertEqual(got["rows"][0]["kind"], "drift")
        self.assertIn("season", got["rows"][0]["meaning"])


if __name__ == "__main__":
    unittest.main()
