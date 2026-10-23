#!/usr/bin/env python3
"""Two ways a baseline's spread came out far too narrow, from real houses.

#349 — a small counter that resets to 0 every evening and climbs 1–4
overnight. Most of its hourly means are exactly 1, and the ones that are
not are hours it stepped in partway through (1.02, 0.98…), so the MAD was
zero and the step size measured off those near-1 means was 0.02. A
reading of 2 came out "50 spreads" from its normal and filed a finding.
A reading that only ever takes whole values cannot move by less than one
of them, so its spread is at least its smallest step.

#335 — an hour of the week whose few samples happened to agree had a
spread of 0.55 while the hours either side of it had 7.7 and 9.6, so
almost any reading looked far out at that hour, when the same reading was
1.78 spreads from its overall normal. An hour whose spread is far below
its neighbours' borrows theirs before comparing.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import baselines  # noqa: E402
from checks import baseline as check  # noqa: E402

MONDAY = dt.datetime(2026, 1, 5, 0, 0, tzinfo=dt.timezone.utc).timestamp()
HOUR = 3600.0


def counter_series():
    """323 hourly means, as the house's counter wrote them: mostly exactly
    1, a run of hours it stepped in partway (just over or under 1), and
    the whole values it rests on overnight and after the evening reset."""
    values = []
    for i in range(323):
        k = i % 13
        if k < 7:
            values.append(1.0)
        elif k < 11:
            values.append([1.0167, 0.9833, 1.025, 1.0083][k - 7])
        elif k == 11:
            values.append(0.0)
        else:
            values.append([2.0, 3.0, 4.0][(i // 13) % 3])
    return [{"start": MONDAY + i * HOUR, "mean": v}
            for i, v in enumerate(values)]


def house(eid, unit, value, built, now):
    return {
        "now": now,
        "states": {eid: {"state": str(value),
                         "attributes": {"state_class": "measurement",
                                        "unit_of_measurement": unit},
                         "last_changed": "", "last_updated": ""}},
        "entities": [{"entity_id": eid, "platform": "template"}],
        "devices": [], "areas": [],
        "baselines": {"built_at": int(now - 3600), "tz": "UTC", "days": 28,
                      "entities": {eid: {**built, "unit": unit}}},
    }


class TestAWholeNumberCounterIsMeasuredInWholeSteps(unittest.TestCase):
    def test_the_overall_spread_is_at_least_one_step(self):
        built = baselines.build_buckets(counter_series(), dt.timezone.utc)
        self.assertEqual(built["overall"]["median"], 1.0)
        self.assertGreaterEqual(built["overall"]["spread"], 1.0)

    def test_every_hour_is_at_least_one_step_wide(self):
        built = baselines.build_buckets(counter_series(), dt.timezone.utc)
        for key, bucket in built["buckets"].items():
            self.assertGreaterEqual(bucket["spread"], 1.0, key)

    def test_a_reading_of_two_raises_nothing(self):
        built = baselines.build_buckets(counter_series(), dt.timezone.utc)
        # Asked about at an hour it has no bucket for, as the house was:
        # the answer came from all 323 readings.
        built["buckets"] = {}
        now = MONDAY + 30 * 24 * HOUR + 3 * HOUR
        found = baselines.deviation(2.0, built, 3)
        self.assertEqual(found["source"], "overall")
        self.assertLessEqual(abs(found["sigmas"]), 1.0)
        self.assertEqual(check.unusual(
            house("sensor.night_count", "", 2, built, now), now), [])

    def test_a_reading_with_an_ordinary_wobble_is_not_a_count(self):
        values = [20.0 + ((i * 7919) % 11 - 5) / 10 for i in range(28 * 24)]
        built = baselines.build_buckets(
            [{"start": MONDAY + i * HOUR, "mean": v}
             for i, v in enumerate(values)], dt.timezone.utc)
        self.assertLess(built["overall"]["spread"], 1.0)


class TestAThinHourBorrowsItsNeighboursSpread(unittest.TestCase):
    def setUp(self):
        self.now = MONDAY + 30 * 24 * HOUR + 10 * HOUR
        self.hour = baselines.hour_of_week(self.now, dt.timezone.utc)

    def built(self, own=0.55, before=7.7, after=9.6):
        h = self.hour
        buckets = {str(h): {"median": 60.0, "spread": own, "n": 4}}
        if before is not None:
            buckets[str((h - 1) % 168)] = {"median": 62.0, "spread": before,
                                           "n": 4}
        if after is not None:
            buckets[str((h + 1) % 168)] = {"median": 63.0, "spread": after,
                                           "n": 3}
        return {"buckets": buckets, "samples": 600,
                "overall": {"median": 64.0, "spread": 6.0, "n": 600}}

    def test_the_reported_shape_files_nothing(self):
        built = self.built()
        # 74.7 is 1.78 spreads from its overall normal, and 26.7 of the
        # thin hour's own spreads.
        found = baselines.deviation(74.7, built, self.hour)
        self.assertLess(abs(found["sigmas"]), check.UNUSUAL_SPREADS)
        self.assertEqual(check.unusual(
            house("sensor.attic_humidity", "%", 74.7, built, self.now),
            self.now), [])

    def test_an_hour_with_no_neighbours_borrows_the_overall(self):
        built = self.built(before=None, after=None)
        found = baselines.deviation(74.7, built, self.hour)
        self.assertLess(abs(found["sigmas"]), check.UNUSUAL_SPREADS)

    def test_an_hour_as_wide_as_its_neighbours_keeps_its_own(self):
        built = self.built(own=8.0)
        found = baselines.deviation(74.7, built, self.hour)
        self.assertEqual(found["spread"], 8.0)

    def test_far_outside_even_the_borrowed_spread_is_still_reported(self):
        built = self.built()
        found = check.unusual(
            house("sensor.attic_humidity", "%", 140, built, self.now),
            self.now)
        self.assertEqual([f["entity_id"] for f in found],
                         ["sensor.attic_humidity"])


if __name__ == "__main__":
    unittest.main()
