#!/usr/bin/env python3
"""A house whose weekdays differ has a wake time per weekday, not none.

A real house: 26 weekdays recorded (10 needed) and no wake or settle time,
because Mondays and Wednesdays start at half past five and Tuesdays and
Thursdays at half past eight and Fridays at ten — spread wider than `MAX_SPREAD_MIN` taken
together, so the brief fell back to 07:00. A consistent Tuesday is a
Tuesday: the days are split by day of the week, each one measured on its
own floor, and `wake_minute` answers for the day it is asked about. A
house that stirs anywhere still has no time at all.
"""
from __future__ import annotations

import datetime as dt
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import brief  # noqa: E402
import house  # noqa: E402
import rhythm  # noqa: E402

NOW = 1_800_000_000.0


def at(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


def weekdays(n: int, first_of) -> dict:
    days, made, day = {}, 0, dt.date(2024, 1, 1)
    while made < n:
        if day.weekday() < 5:
            days[day.isoformat()] = {"first": first_of(day.weekday(), made),
                                     "last": at(22, 30) + made % 3,
                                     "dow": day.weekday(), "n": 4}
            made += 1
        day += dt.timedelta(days=1)
    return {"days": days, "updated_at": int(NOW)}


def by_weekday(dow: int, i: int) -> int:
    # Mon and Wed early, Tue and Thu late, Fri later still: no one time.
    base = {0: at(5, 30), 2: at(5, 30), 1: at(8, 30), 3: at(8, 30),
            4: at(10, 0)}[dow]
    return base + (i % 3) * 4


class TestEachWeekdayIsItsOwnDay(unittest.TestCase):
    def setUp(self):
        self.payload = weekdays(26, by_weekday)

    def test_together_they_have_no_single_time(self):
        # The shape the house reported: the weekday half alone is refused.
        prof = rhythm.profile(self.payload)
        self.assertIsNone(prof[rhythm.WEEKDAY]["wakes"])

    def test_each_weekday_is_measured_on_its_own(self):
        prof = rhythm.profile(self.payload)
        tuesday = dt.datetime(2024, 3, 5, 5, 0)       # a Tuesday
        monday = dt.datetime(2024, 3, 4, 5, 0)
        self.assertAlmostEqual(rhythm.wake_minute(prof, tuesday), at(8, 34),
                               delta=6)
        self.assertAlmostEqual(rhythm.wake_minute(prof, monday), at(5, 34),
                               delta=6)

    def test_the_rhythm_is_not_unavailable(self):
        p = rhythm.progress(self.payload, now=NOW)
        self.assertNotEqual(p["state"], house.UNAVAILABLE)
        self.assertEqual(p["state"], house.READY)
        self.assertIn("Tue", p["summary"])
        self.assertIn("08:3", p["summary"])

    def test_the_brief_uses_that_days_time(self):
        prof = rhythm.profile(self.payload)
        tuesday = dt.datetime(2024, 3, 5, 8, 40)
        wake = rhythm.wake_minute(prof, tuesday)
        # Ten past the Tuesday wake: the window is open, where the 07:00
        # fallback closed at 07:45.
        self.assertTrue(brief.due(NOW, at(8, 40), wake, 7, 0.0))
        self.assertFalse(brief.due(NOW, at(8, 40), None, 7, 0.0))


class TestARandomHouseStillHasNone(unittest.TestCase):
    def test_mornings_anywhere_are_no_time_on_any_day(self):
        rng = random.Random(11)
        answered = 0
        for _ in range(100):
            payload = weekdays(26, lambda d, i: rng.randrange(at(5), at(11)))
            prof = rhythm.profile(payload)
            answered += any(
                rhythm.wake_minute(prof, dt.datetime(2024, 3, 4 + d, 5))
                is not None for d in range(5))
        self.assertLess(answered, 10)

    def test_a_random_house_reads_unavailable(self):
        rng = random.Random(3)
        payload = weekdays(26, lambda d, i: rng.randrange(at(5), at(11)))
        self.assertEqual(rhythm.progress(payload, now=NOW)["state"],
                         house.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
