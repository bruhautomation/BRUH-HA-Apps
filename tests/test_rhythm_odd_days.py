"""A house whose usual days agree has a wake time, odd days and all.

After weeks of data a real house still had no wake or settle time, on
weekdays or weekends: the centre was the median of EVERY day and the
spread was measured from it, so a run of odd days — a lie-in, a day
nobody touched anything until the afternoon, a night up — pulled the
centre off the usual mornings and the spread past `MAX_SPREAD_MIN`. The
centre is now found where the days actually cluster, the odd days are
trimmed before the spread is taken, and a house that truly has no usual
time still gets none.
"""
from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import rhythm  # noqa: E402
from circular import circular_spread  # noqa: E402


def at(h: int, m: int = 0) -> int:
    return h * 60 + m


def payload(firsts: list[int], lasts: list[int] | None = None) -> dict:
    lasts = lasts or [at(22, 30)] * len(firsts)
    days = {}
    for i, (first, last) in enumerate(zip(firsts, lasts)):
        days[f"2026-08-{i + 1:02d}"] = {"first": first, "last": last,
                                        "dow": i % 5, "n": 5}
    return {"days": days, "updated_at": 0, "day_start": rhythm.DAY_START_MIN}


# Eight mornings within a quarter of an hour of 06:45, and ten days whose
# first touch was all over the place — mostly late, because a day nobody
# got up early for is a day somebody touched nothing until later.
USUAL = [at(6, 35), at(6, 40), at(6, 42), at(6, 45), at(6, 47), at(6, 50),
         at(6, 52), at(6, 58)]
ODD = [at(4, 20), at(5, 10), at(9, 30), at(10, 15), at(11, 0), at(11, 40),
       at(12, 20), at(13, 0), at(13, 45), at(14, 30)]


class TestOddDaysDoNotVetoTheUsualOnes(unittest.TestCase):
    def test_the_old_arithmetic_refused_this_house(self):
        days = USUAL + ODD
        centre = rhythm.circular_median(days)
        self.assertGreater(circular_spread(days, centre),
                           rhythm.MAX_SPREAD_MIN)

    def test_the_usual_mornings_are_the_wake_time(self):
        got = rhythm.profile(payload(USUAL + ODD))[rhythm.WEEKDAY]["wakes"]
        self.assertIsNotNone(got)
        self.assertTrue(got["at"].startswith("06:4"), got["at"])
        self.assertEqual(got["days"], len(USUAL + ODD))
        self.assertLessEqual(got["spread_min"], 30)
        self.assertEqual(got["confidence"], "low")

    def test_a_settle_either_side_of_midnight_with_odd_nights(self):
        lasts = ([at(23, 40), at(23, 50), at(0, 5), at(0, 15), at(23, 55),
                  at(0, 10), at(23, 45), at(0, 0)]
                 + [at(19, 0), at(20, 10), at(2, 30), at(3, 10), at(18, 30),
                    at(21, 0), at(2, 50), at(19, 40), at(1, 40), at(20, 30)])
        got = rhythm.profile(payload([at(7)] * 18, lasts))[rhythm.WEEKDAY]
        settles = got["settles"]
        self.assertIsNotNone(settles)
        minute = settles["minute"]
        self.assertTrue(minute >= at(23, 30) or minute <= at(0, 30), settles)

    def test_a_house_with_no_usual_time_still_has_none(self):
        # Mornings spread evenly from 05:00 to 11:00.
        days = [at(5) + i * 20 + (i * 7) % 11 for i in range(18)]
        self.assertIsNone(rhythm.profile(payload(days))[rhythm.WEEKDAY]["wakes"])

    def test_random_mornings_are_called_a_usual_time_far_less_often(self):
        # The median absolute deviation of every day called a usual time
        # in about half of houses whose first touch fell anywhere between
        # 05:00 and 11:00. Measured against that, on the same houses.
        rng = random.Random(7)
        old = new = 0
        for _ in range(300):
            days = [rng.randrange(at(5), at(11)) for _ in range(18)]
            centre = rhythm.circular_median(days)
            old += circular_spread(days, centre) <= rhythm.MAX_SPREAD_MIN
            new += rhythm.profile(payload(days))[rhythm.WEEKDAY]["wakes"] is not None
        self.assertGreater(old, 120)
        self.assertLess(new, old / 2)

    def test_two_households_in_one_week_is_not_a_usual_time(self):
        days = [at(6, 0) + i for i in range(9)] + [at(10, 0) + i for i in range(9)]
        self.assertIsNone(rhythm.profile(payload(days))[rhythm.WEEKDAY]["wakes"])

    def test_min_days_still_holds(self):
        got = rhythm.profile(payload(USUAL))[rhythm.WEEKDAY]["wakes"]
        self.assertIsNone(got)

    def test_a_tidy_house_is_high_confidence(self):
        got = rhythm.profile(payload([at(7, 0) + i for i in range(14)]))
        self.assertEqual(got[rhythm.WEEKDAY]["wakes"]["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
