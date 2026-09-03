"""The house's own clock, and the brief that is timed by it.

Two failures shape everything here. A median of times of day taken on a
straight number line puts a bedtime either side of midnight at **noon** —
not a small error, the opposite side of the day — and that is asserted
against the arithmetic that produces it rather than described. And a
brief that arrives every morning saying "all quiet" is the message people
mute, so the decision to send is made before any model is asked and is
tested as the deterministic thing it is.
"""
from __future__ import annotations

import datetime as dt
import os
import statistics
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import brief  # noqa: E402
import rhythm  # noqa: E402

UTC = dt.timezone.utc


def at(hour: int, minute: int = 0) -> int:
    return hour * 60 + minute


class TestTheClockDoesNotBreakAtMidnight(unittest.TestCase):
    def test_a_bedtime_either_side_of_midnight(self):
        # Four times inside forty minutes of midnight. A plain median puts
        # them at NOON — the failure this arithmetic exists for, measured
        # here rather than argued.
        night = [at(23, 40), at(23, 50), at(0, 10), at(0, 20)]
        self.assertEqual(rhythm.clock(statistics.median(night)), "12:00")
        self.assertEqual(rhythm.clock(rhythm.circular_median(night)), "00:00")

    def test_the_spread_goes_the_short_way_round(self):
        # 23:50 is twenty minutes from 00:10, not twenty-three hours and
        # forty. A spread that took the long way would fail every house
        # that goes to bed near midnight out of MAX_SPREAD_MIN.
        night = [at(23, 50), at(0, 10)]
        centre = rhythm.circular_median(night)
        self.assertLessEqual(rhythm.circular_spread(night, centre), 20.0)

    def test_an_ordinary_morning_is_unremarkable(self):
        morning = [at(7, 10), at(6, 55), at(7, 30), at(7), at(6, 40)]
        self.assertEqual(rhythm.clock(rhythm.circular_median(morning)),
                         "07:00")

    def test_nothing_has_no_middle(self):
        self.assertIsNone(rhythm.circular_median([]))

    def test_the_clock_renders_rather_than_reporting_zero(self):
        self.assertEqual(rhythm.clock(None), "")
        self.assertEqual(rhythm.clock(0), "00:00")
        self.assertEqual(rhythm.clock(rhythm.MINUTES_PER_DAY + 65), "01:05")


class RhythmCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "rhythm.json")
        self.monday = dt.datetime(2026, 8, 3, tzinfo=UTC)

    def day(self, offset: int, *times: tuple[int, int], cause="person"):
        base = self.monday + dt.timedelta(days=offset)
        return [{"ts": (base + dt.timedelta(hours=h, minutes=m)).timestamp(),
                 "cause": cause, "entity_id": "light.hall"}
                for h, m in times]

    def fortnight(self, wake=(7, 5), settle=(22, 40), days=14):
        rows = []
        for d in range(days):
            rows += self.day(d, wake, settle)
        return rows

    def now_after(self, days=15) -> float:
        return (self.monday + dt.timedelta(days=days)).timestamp()


class TestWhatItKeeps(RhythmCase):
    def test_two_numbers_a_day_and_no_timeline(self):
        rhythm.record(self.fortnight(days=3), UTC, self.now_after(4),
                      self.path)
        days = rhythm.load(self.path)["days"]
        self.assertEqual(len(days), 3)
        for row in days.values():
            self.assertEqual(sorted(row), ["dow", "first", "last", "n"])

    def test_a_day_is_widened_never_replaced(self):
        # Passes overlap, so a window starting at 04:00 sees a later
        # "first" than the pass that saw midnight. Taking the newest would
        # walk the wake time forwards all morning.
        rhythm.record(self.day(0, (7, 0), (22, 0)), UTC,
                      self.now_after(1), self.path)
        rhythm.record(self.day(0, (9, 0), (21, 0)), UTC,
                      self.now_after(1), self.path)
        row = next(iter(rhythm.load(self.path)["days"].values()))
        self.assertEqual(row["first"], at(7))
        self.assertEqual(row["last"], at(22))

    def test_only_a_person_wakes_a_house(self):
        # A motion sensor fires for a cat and for the heating; an
        # automation turns a light on at dawn. Neither is somebody
        # getting up, and counting them would put every house's wake time
        # at whenever its earliest automation runs.
        for cause in ("automation", "script", "scene", "brain",
                      "unattributed", ""):
            rhythm.record(self.day(0, (4, 0), cause=cause), UTC,
                          self.now_after(1), self.path)
        self.assertEqual(rhythm.load(self.path)["days"], {})

    def test_rubbish_rows_are_skipped_rather_than_crashing(self):
        rhythm.record([{"cause": "person"},
                       {"cause": "person", "ts": None},
                       {"cause": "person", "ts": True},
                       "nope"], UTC, self.now_after(1), self.path)
        self.assertEqual(rhythm.load(self.path)["days"], {})

    def test_old_days_age_out(self):
        old = self.monday - dt.timedelta(days=rhythm.KEEP_DAYS + 5)
        rhythm.record(
            [{"ts": old.timestamp(), "cause": "person",
              "entity_id": "light.hall"}] + self.fortnight(days=2),
            UTC, self.now_after(3), self.path)
        self.assertEqual(len(rhythm.load(self.path)["days"]), 2)

    def test_a_torn_file_is_an_empty_store(self):
        for junk in ('{"days":', '[1,2]', '{"days": 3}'):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(rhythm.load(self.path), {"days": {}}, junk)

    def test_a_missing_directory_is_not_a_crash(self):
        rhythm.save({"days": {}},
                    os.path.join(self.dir.name, "no", "rhythm.json"))


class TestWhatItWillNotSay(RhythmCase):
    """Every floor asserted against the answer it refuses to give."""

    def test_a_fortnight_answers_and_less_does_not(self):
        for days in (3, rhythm.MIN_DAYS - 1):
            with tempfile.TemporaryDirectory() as d:
                path = os.path.join(d, "r.json")
                rhythm.record(self.fortnight(days=days), UTC,
                              self.now_after(days + 1), path)
                shape = rhythm.profile(path=path)[rhythm.WEEKDAY]["wakes"]
                self.assertIsNone(shape, f"{days} days")

        rhythm.record(self.fortnight(days=20), UTC, self.now_after(21),
                      self.path)
        shape = rhythm.profile(path=self.path)[rhythm.WEEKDAY]["wakes"]
        self.assertIsNotNone(shape)
        self.assertEqual(shape["at"], "07:05")

    def test_weekdays_and_weekends_are_different_houses(self):
        # Six weeks, because a weekend accrues two days a week: the
        # weekend half needs about five weeks to clear MIN_DAYS where the
        # weekday half clears it in two. That is the floor doing its job,
        # not a bug, and it is worth a test saying so.
        rows = []
        for d in range(42):
            weekend = (self.monday + dt.timedelta(days=d)).weekday() >= 5
            rows += self.day(d, (10, 0) if weekend else (7, 0), (22, 0))
        rhythm.record(rows, UTC, self.now_after(43), self.path)
        got = rhythm.profile(path=self.path)
        self.assertEqual(got[rhythm.WEEKDAY]["wakes"]["at"], "07:00")
        self.assertEqual(got[rhythm.WEEKEND]["wakes"]["at"], "10:00")

    def test_a_house_with_no_usual_time_is_told_so(self):
        # Stirring anywhere between 05:00 and 11:00 is not a wake time,
        # and a median of it would be a confident number over data that
        # holds none.
        rows = []
        for d in range(20):
            rows += self.day(d, (5 + (d * 3) % 7, (d * 17) % 60), (22, 0))
        rhythm.record(rows, UTC, self.now_after(21), self.path)
        self.assertIsNone(
            rhythm.profile(path=self.path)[rhythm.WEEKDAY]["wakes"])

    def test_a_settle_time_around_midnight_survives_the_whole_pipeline(self):
        rows = []
        for d in range(20):
            base = self.monday + dt.timedelta(days=d)
            late = base + dt.timedelta(hours=23, minutes=45 + (d % 5))
            rows.append({"ts": late.timestamp(), "cause": "person",
                         "entity_id": "light.hall"})
            rows += self.day(d, (7, 0))
        rhythm.record(rows, UTC, self.now_after(21), self.path)
        settles = rhythm.profile(path=self.path)[rhythm.WEEKDAY]["settles"]
        self.assertIsNotNone(settles)
        self.assertTrue(settles["at"].startswith("23:4"), settles["at"])

    def test_a_missing_half_reads_as_not_measured(self):
        got = rhythm.profile(path=self.path)
        self.assertIsNone(got[rhythm.WEEKDAY]["wakes"])
        self.assertIsNone(rhythm.wake_minute(got, self.monday))
        self.assertIsNone(rhythm.settle_minute(got, self.monday))


class TestWhetherToSendOneAtAll(unittest.TestCase):
    """The decision that happens BEFORE any Claude turn."""

    def finding(self, text="X", severity="warning", ts=100.0):
        return {"text": text, "severity": severity, "ts": ts}

    def test_a_quiet_morning_says_nothing(self):
        state = brief.state_from([], {"state": "ok"}, {}, since=50.0)
        self.assertEqual(brief.worth_saying(state), [])

    def test_a_finding_filed_overnight_is_worth_saying(self):
        state = brief.state_from([self.finding(ts=100.0)], {"state": "ok"},
                                 {}, since=50.0)
        self.assertTrue(brief.worth_saying(state))

    def test_a_finding_from_before_the_last_brief_is_not(self):
        # Otherwise every morning re-reports the same thing, which is the
        # message people mute.
        state = brief.state_from([self.finding(ts=10.0)], {"state": "ok"},
                                 {}, since=50.0)
        self.assertEqual(brief.worth_saying(state), [])

    def test_the_worst_finding_leads(self):
        state = brief.state_from(
            [self.finding("nit", "info", 110.0),
             self.finding("boiler", "critical", 100.0)],
            {"state": "ok"}, {}, since=50.0)
        self.assertIn("boiler", brief.worth_saying(state)[0])

    def test_brain_being_broken_is_worth_saying(self):
        for state_name in ("degraded", "failed"):
            state = brief.state_from(
                [], {"state": state_name, "reason": "the listener died"},
                {}, since=50.0)
            reasons = brief.worth_saying(state)
            self.assertTrue(reasons, state_name)
            self.assertIn("listener died", reasons[0])

    def test_a_quiet_night_is_not_a_spike(self):
        state = brief.state_from([], {"state": "ok"},
                                 {"counts": {"person": 4}}, since=50.0)
        self.assertEqual(brief.worth_saying(state), [])


class TestTheMessageItself(unittest.TestCase):
    def test_a_long_reply_is_capped(self):
        body = brief.tidy(" ".join(["word"] * 200))
        self.assertLessEqual(len(body.split(" ")), brief.MAX_WORDS + 1)
        self.assertTrue(body.endswith("…"))

    def test_a_four_word_reply_is_not_a_brief(self):
        # Sending that is worse than the silence it replaced.
        self.assertEqual(brief.tidy("All good today."), "")
        self.assertEqual(brief.tidy(""), "")
        self.assertEqual(brief.tidy(None), "")

    def test_it_is_one_paragraph(self):
        body = brief.tidy("The freezer is warming.\n\nAlso the front door "
                          "battery is nearly out and needs changing soon.")
        self.assertNotIn("\n", body)

    def test_the_frame_carries_the_reasons_and_asks_for_prose(self):
        frame = brief.frame(["the freezer is at -12"],
                            {"overnight": {"counts": {"person": 3}},
                             "woke_at": "07:05"})
        self.assertIn("the freezer is at -12", frame)
        self.assertIn("07:05", frame)
        self.assertIn("person: 3", frame)


class TestWhenItGoesOut(unittest.TestCase):
    NOW = 1_700_000_000.0

    def test_the_measured_wake_beats_the_fallback(self):
        self.assertTrue(brief.due(self.NOW, at(9, 10), at(9), 7, 0))
        self.assertFalse(brief.due(self.NOW, at(7, 5), at(9), 7, 0))

    def test_the_fallback_carries_a_house_never_measured(self):
        self.assertTrue(brief.due(self.NOW, at(7, 5), None, 7, 0))

    def test_a_restart_at_lunchtime_does_not_deliver_breakfast(self):
        self.assertFalse(brief.due(self.NOW, at(12), None, 7, 0))

    def test_once_a_day(self):
        self.assertFalse(
            brief.due(self.NOW, at(7, 5), None, 7, self.NOW - 3600))
        self.assertTrue(
            brief.due(self.NOW, at(7, 5), None, 7, self.NOW - 30 * 3600))

    def test_the_window_opens_at_the_hour_and_not_before(self):
        self.assertFalse(brief.due(self.NOW, at(6, 59), None, 7, 0))
        self.assertTrue(brief.due(self.NOW, at(7, 0), None, 7, 0))


if __name__ == "__main__":
    unittest.main()
