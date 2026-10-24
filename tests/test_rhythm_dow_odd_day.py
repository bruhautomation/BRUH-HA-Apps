#!/usr/bin/env python3
"""A day of the week keeps its time through one odd day.

A house with 36 days recorded had no wake or settle at all: its weekdays
together spread wider than `MAX_SPREAD_MIN`, and every day of the week
measured on its own was refused too, because the per-day floor required
EVERY one of its four or five days within half an hour — so one bank
holiday Monday or one late Thursday took that day's answer away, and with
five weeks of data nearly every day had one. The brief stayed on 07:00.
A day of the week now keeps its time when one odd day in five sits far
away (further than `MAX_SPREAD_MIN`) and the rest agree within the same
half hour as before; a house that stirs anywhere still has no time.
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
import rhythm  # noqa: E402
import signals  # noqa: E402

NOW = 1_800_000_000.0


def at(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


BASE = {0: at(6, 0), 1: at(8, 30), 2: at(6, 0), 3: at(8, 30), 4: at(10, 0),
        5: at(9, 30), 6: at(11, 0)}
LATE = {0: at(22, 0), 1: at(23, 30), 2: at(22, 0), 3: at(23, 30),
        4: at(0, 30), 5: at(1, 0), 6: at(22, 30)}


def house_days(n: int) -> dict:
    """``n`` days, each day of the week its own time, and in the first
    week every day an odd one (a holiday week)."""
    days, day = {}, dt.date(2024, 1, 1)
    for i in range(n):
        dow = day.weekday()
        odd = i < 7
        days[day.isoformat()] = {
            "first": (BASE[dow] + 240) % 1440 if odd else BASE[dow] + (i % 3) * 4,
            "last": (LATE[dow] - 200) % 1440 if odd else (LATE[dow] + (i % 3) * 3) % 1440,
            "dow": dow, "n": 4}
        day += dt.timedelta(days=1)
    return {"days": days, "updated_at": int(NOW)}


class TestEveryDayOfTheWeekIsMeasured(unittest.TestCase):
    def setUp(self):
        self.prof = rhythm.profile(house_days(36))

    def test_the_halves_are_refused(self):
        self.assertIsNone(self.prof[rhythm.WEEKDAY]["wakes"])

    def test_by_dow_is_filled_for_every_day(self):
        by_dow = self.prof[rhythm.BY_DOW]
        self.assertEqual(sorted(by_dow), [str(d) for d in range(7)])
        for dow in range(7):
            with self.subTest(dow=dow):
                self.assertAlmostEqual(by_dow[str(dow)]["wakes"]["minute"],
                                       BASE[dow] + 4, delta=6)
                self.assertIsNotNone(by_dow[str(dow)]["settles"])

    def test_wake_and_settle_use_that_days_time(self):
        tuesday = dt.datetime(2024, 3, 5, 9, 0)
        self.assertAlmostEqual(rhythm.wake_minute(self.prof, tuesday),
                               at(8, 34), delta=6)
        # A Friday night's settle is after midnight; at 00:10 on Saturday it
        # is still Friday's house day.
        saturday_small_hours = dt.datetime(2024, 3, 9, 0, 10)
        self.assertAlmostEqual(
            rhythm.settle_minute(self.prof, saturday_small_hours), at(0, 33),
            delta=6)

    def test_the_brief_opens_at_that_days_wake(self):
        wake = rhythm.wake_minute(self.prof, dt.datetime(2024, 3, 5, 8, 40))
        self.assertTrue(brief.due(NOW, at(8, 40), wake, 7, 0.0))

    def test_the_night_window_follows_too(self):
        # Tuesday: settles about 23:30, wakes about 08:30.
        start, end = signals.night_window(self.prof, dt.datetime(2024, 3, 5, 12))
        self.assertEqual((start, end), (23, 8))
        self.assertNotEqual((start, end),
                            (signals.NIGHT_START_H, signals.NIGHT_END_H))


class TestARandomHouseStillHasNone(unittest.TestCase):
    def test_mornings_anywhere(self):
        rng = random.Random(29)
        answered = 0
        for _ in range(200):
            days, day = {}, dt.date(2024, 1, 1)
            for _i in range(36):
                days[day.isoformat()] = {"first": rng.randrange(at(5), at(11)),
                                         "last": at(22), "dow": day.weekday(),
                                         "n": 4}
                day += dt.timedelta(days=1)
            prof = rhythm.profile({"days": days, "updated_at": int(NOW)})
            answered += sum(
                1 for d in range(7)
                if ((prof[rhythm.BY_DOW].get(str(d)) or {}).get("wakes")))
        # Fewer than one day in twenty-five, over 1400 days of the week.
        self.assertLess(answered, 1400 // 25)


if __name__ == "__main__":
    unittest.main()
