"""A household that goes to bed after midnight was measured as waking then.

`rhythm.record` filed each person-caused action under its local CALENDAR
date and kept that date's earliest and latest minute, so anything after
midnight became the next date's *first* action and could never be
anybody's *last*. A house that settles at 00:40 and wakes at 07:10 came
out as waking at 00:40 and settling at 22:00 — inverted rather than
imprecise — and every reader inherited it: the morning brief opening at
half past midnight, the bedtime door check running at ten, the overnight
heal targeting an hour when people are still up. The circular median the
module defends a settle at 00:20 with could never see one.

Each case below runs the real `record` → `profile` → reader pipeline,
and the first states the old answer on the same data before asserting
the new one, so the fix is measured against the failure it replaces.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import brief  # noqa: E402
import rhythm  # noqa: E402
import signals  # noqa: E402

UTC = dt.timezone.utc
MONDAY = dt.datetime(2026, 8, 3, tzinfo=UTC)


def at(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


def action(when: dt.datetime, cause: str = "person") -> dict:
    return {"ts": when.timestamp(), "cause": cause, "entity_id": "light.hall"}


def night_owls(days: int = 21, cause: str = "person") -> list[dict]:
    """Up at 07:10, about in the evening, to bed at 00:40 — every day."""
    rows = []
    for d in range(days):
        base = MONDAY + dt.timedelta(days=d)
        rows.append(action(base + dt.timedelta(hours=7, minutes=10), cause))
        rows.append(action(base + dt.timedelta(hours=22), cause))
        rows.append(action(base + dt.timedelta(days=1, minutes=40), cause))
    return rows


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "rhythm.json")

    def profile_of(self, rows, days=22):
        rhythm.record(rows, UTC, (MONDAY + dt.timedelta(days=days)).timestamp(),
                      self.path)
        return rhythm.profile(path=self.path)


class TestASettleAfterMidnightIsASettle(Case):

    def test_the_calendar_rule_inverts_the_night(self):
        """The old arithmetic, on the same actions, stated rather than
        described: a calendar date's min and max."""
        firsts, lasts = {}, {}
        for row in night_owls():
            when = dt.datetime.fromtimestamp(row["ts"], UTC)
            key = when.date()
            minute = when.hour * 60 + when.minute
            firsts[key] = min(firsts.get(key, minute), minute)
            lasts[key] = max(lasts.get(key, minute), minute)
        weekday_firsts = [m for k, m in firsts.items() if k.weekday() < 5]
        self.assertEqual(rhythm.clock(rhythm.circular_median(weekday_firsts)),
                         "00:40")   # "wakes" at 00:40
        self.assertEqual(rhythm.clock(rhythm.circular_median(
            [m for k, m in lasts.items() if k.weekday() < 5])), "22:00")

    def test_the_house_day_measures_it_the_right_way_round(self):
        got = self.profile_of(night_owls())
        self.assertEqual(got[rhythm.WEEKDAY]["wakes"]["at"], "07:10")
        self.assertEqual(got[rhythm.WEEKDAY]["settles"]["at"], "00:40")

    def test_the_brief_opens_in_the_morning_and_not_at_half_past_midnight(self):
        got = self.profile_of(night_owls())
        tuesday = MONDAY + dt.timedelta(days=8)
        wake = rhythm.wake_minute(got, tuesday + dt.timedelta(hours=7))
        long_after = 10 * 86400.0   # nothing sent in the last twelve hours
        self.assertTrue(brief.due(long_after, at(7, 20), wake, 7, 0))
        self.assertFalse(brief.due(long_after, at(0, 50), wake, 7, 0))

    def test_the_settle_read_after_midnight_is_the_evening_before(self):
        """At 00:30 on a Saturday the settle that matters is Friday
        night's, which is a weekday's; the wake still to come is
        Saturday's."""
        rows = []
        for d in range(42):
            base = MONDAY + dt.timedelta(days=d)
            weekend_night = base.weekday() >= 5
            rows.append(action(base + dt.timedelta(hours=8)))
            late = base + dt.timedelta(days=1, minutes=20)
            if weekend_night:
                late += dt.timedelta(hours=1)
            rows.append(action(late))
        got = self.profile_of(rows, days=43)
        self.assertEqual(got[rhythm.WEEKDAY]["settles"]["at"], "00:20")
        self.assertEqual(got[rhythm.WEEKEND]["settles"]["at"], "01:20")
        saturday_half_past = dt.datetime(2026, 8, 8, 0, 30, tzinfo=UTC)
        self.assertEqual(saturday_half_past.weekday(), 5)
        self.assertEqual(rhythm.settle_minute(got, saturday_half_past),
                         at(0, 20))

    def test_the_night_window_spans_the_real_night(self):
        got = self.profile_of(night_owls())
        start, end = signals.night_window(
            got, MONDAY + dt.timedelta(days=9, hours=23))
        self.assertEqual((start, end), (0, 7))

    def test_a_house_that_never_stays_up_late_is_measured_as_before(self):
        rows = []
        for d in range(20):
            base = MONDAY + dt.timedelta(days=d)
            rows.append(action(base + dt.timedelta(hours=6, minutes=50)))
            rows.append(action(base + dt.timedelta(hours=22, minutes=30)))
        got = self.profile_of(rows)
        self.assertEqual(got[rhythm.WEEKDAY]["wakes"]["at"], "06:50")
        self.assertEqual(got[rhythm.WEEKDAY]["settles"]["at"], "22:30")


class TestVoiceIsAPerson(Case):

    def test_a_voice_first_house_has_a_rhythm(self):
        got = self.profile_of(night_owls(cause="voice"))
        self.assertEqual(got[rhythm.WEEKDAY]["wakes"]["at"], "07:10")

    def test_a_wall_switch_still_is_not(self):
        got = self.profile_of(night_owls(cause="unattributed"))
        self.assertIsNone(got[rhythm.WEEKDAY]["wakes"])


class TestAStoreWrittenTheOldWay(Case):
    """Rows the calendar rule recorded across midnight are dropped once,
    on read; rows it recorded correctly are kept."""

    def test_the_inverted_rows_go_and_the_honest_ones_stay(self):
        days = {
            # An ordinary day: 06:50 to 22:30, which both rules agree on.
            "2026-08-03": {"first": at(6, 50), "last": at(22, 30),
                           "dow": 0, "n": 4},
            # Up until 00:40 on the night of the 5th: the calendar rule
            # filed that as the 6th's "first" and left the 5th's "last"
            # without it. Both rows are wrong, and both go.
            "2026-08-05": {"first": at(7, 0), "last": at(23, 10),
                           "dow": 2, "n": 4},
            "2026-08-06": {"first": at(0, 40), "last": at(22, 0),
                           "dow": 3, "n": 4},
        }
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"days": days}, fh)
        got = rhythm.load(self.path)
        self.assertEqual(sorted(got["days"]), ["2026-08-03"])
        self.assertEqual(got["day_start"], rhythm.DAY_START_MIN)

    def test_a_store_written_the_new_way_is_left_alone(self):
        days = {"2026-08-06": {"first": at(0, 40), "last": at(0, 40),
                               "dow": 3, "n": 1}}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"days": days, "day_start": rhythm.DAY_START_MIN}, fh)
        self.assertEqual(sorted(rhythm.load(self.path)["days"]),
                         ["2026-08-06"])

    def test_a_record_writes_the_marker(self):
        rhythm.record(night_owls(days=2), UTC,
                      (MONDAY + dt.timedelta(days=3)).timestamp(), self.path)
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["day_start"],
                             rhythm.DAY_START_MIN)


if __name__ == "__main__":
    unittest.main()
