#!/usr/bin/env python3
"""`base.unusual` against a band built mostly from last month's weather.

The band is the median and spread for this hour of the week over four
weeks of statistics. At a season turn three of those four weeks are the
old season: a house had a room reading 70.2 °F reported "far outside" a
usual 87.7–105 °F while the last ten days had all been 68–74 °F. The
nightly build now carries how far the entity's last week sat from its own
hour-of-the-week medians (`recent`), and a reading in line with that
recent behaviour is not reported. A reading outside BOTH still is.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import baselines  # noqa: E402
from checks import baseline  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402

UTC = dt.timezone.utc
HOUR = 3600.0


def _rows(old: float, new: float, new_days: int = 7, days: int = 28,
          wobble: float = 1.5, now: float = NOW) -> list[dict]:
    """Hourly means: `old` for most of the month, `new` for the last week."""
    rows = []
    start = int(now // HOUR) * HOUR - days * 86400
    for i in range(days * 24):
        t = start + i * HOUR
        level = new if t >= now - new_days * 86400 else old
        # a daily shape, so the buckets are not all one number
        hour = int((t // HOUR) % 24)
        rows.append({"start": t, "mean": level + wobble * (hour % 6 - 2.5) / 2.5})
    return rows


class TestTheStoreCarriesTheRecentShift(unittest.TestCase):
    def test_a_season_turn_is_measured_as_an_offset(self):
        rows = _rows(96.0, 71.0)
        built = baselines.build_buckets(rows, UTC)
        recent = baselines.recent_shift(rows, built, UTC, NOW)
        self.assertIsNotNone(recent)
        self.assertLess(recent["offset"], -20.0)
        self.assertGreater(recent["offset"], -30.0)
        self.assertGreater(recent["n"], 100)

    def test_a_steady_month_has_no_offset(self):
        rows = _rows(70.0, 70.0)
        built = baselines.build_buckets(rows, UTC)
        recent = baselines.recent_shift(rows, built, UTC, NOW)
        self.assertLess(abs(recent["offset"]), 0.5)

    def test_too_little_recent_history_says_nothing(self):
        rows = _rows(70.0, 70.0)[:-24 * 6]  # the last six days missing
        built = baselines.build_buckets(rows, UTC)
        self.assertIsNone(baselines.recent_shift(rows, built, UTC, NOW))


def _snap(value: float, recent: dict | None) -> dict:
    snap = house()
    eid = "sensor.loft_temperature"
    snap["states"][eid] = {
        "state": str(value), "attributes": {
            "friendly_name": "Loft temperature", "device_class": "temperature",
            "unit_of_measurement": "°F", "state_class": "measurement"},
        "last_changed": iso(60)}
    snap["entities"].append({"entity_id": eid, "platform": "zha"})
    entry = {"unit": "°F", "samples": 672,
             "overall": {"median": 96.0, "spread": 4.0, "n": 672},
             "buckets": {str(h): {"median": 96.0, "spread": 2.2, "n": 4}
                         for h in range(168)}}
    if recent is not None:
        entry["recent"] = recent
    snap["baselines"]["entities"][eid] = entry
    return snap


SEASON = {"offset": -25.0, "spread": 1.5, "n": 168, "days": 7.0}


class TestTheCheckReadsTheRecentShift(unittest.TestCase):
    def test_a_reading_in_line_with_the_last_week_is_not_reported(self):
        self.assertEqual(baseline.unusual(_snap(70.2, SEASON), NOW), [])

    def test_a_reading_outside_the_band_AND_the_last_week_still_reports(self):
        # the last week sat ~25 below the band; this is 60 below it
        found = baseline.unusual(_snap(36.0, SEASON), NOW)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["entity_id"], "sensor.loft_temperature")

    def test_a_reading_the_other_way_from_the_shift_still_reports(self):
        # the season went down; a reading far ABOVE the band is not it
        found = baseline.unusual(_snap(125.0, SEASON), NOW)
        self.assertEqual(len(found), 1)

    def test_an_older_store_with_no_recent_figure_reports_as_before(self):
        found = baseline.unusual(_snap(70.2, None), NOW)
        self.assertEqual(len(found), 1)

    def test_a_steady_last_week_changes_nothing(self):
        steady = {"offset": 0.3, "spread": 1.5, "n": 168, "days": 7.0}
        self.assertEqual(len(baseline.unusual(_snap(70.2, steady), NOW)), 1)

    def test_a_malformed_recent_figure_is_ignored(self):
        for junk in ({"offset": "x"}, {"offset": float("nan"), "spread": 1},
                     "nope", {"spread": 1.0}):
            self.assertEqual(len(baseline.unusual(_snap(70.2, junk), NOW)), 1,
                             junk)


if __name__ == "__main__":
    unittest.main()
