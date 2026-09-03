"""The override ledger: the one thing the action miner keeps.

`actions.py` persists nothing on purpose. This is the deliberate
exception, so the cases here are mostly about the two ways keeping
something can go wrong: counting the same event several times because the
passes that offer it overlap, and reading a shape into a handful of
events that do not have one.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import override_ledger as ledger  # noqa: E402

UTC = dt.timezone.utc
MONDAY = dt.datetime(2026, 8, 3, 8, 10, tzinfo=UTC)


def override(when: dt.datetime, entity="light.hall", by="automation.dusk",
             cause="automation") -> dict:
    return {"ts": when.timestamp(), "entity_id": entity, "by": by,
            "by_name": "Dusk", "by_cause": cause,
            "from_state": "on", "to_state": "off"}


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "overrides.json")
        self.now = dt.datetime(2026, 8, 25, tzinfo=UTC).timestamp()

    def weekday_mornings(self, weeks=3) -> list[dict]:
        return [override(MONDAY + dt.timedelta(weeks=w, days=d))
                for w in range(weeks) for d in range(5)]


class TestKeepingThem(LedgerCase):
    def test_what_a_pass_saw_survives(self):
        self.assertEqual(ledger.record(self.weekday_mornings(1),
                                       self.now, self.path), 5)
        self.assertEqual(len(ledger.load(self.path)), 5)

    def test_the_same_pass_twice_files_nothing_the_second_time(self):
        # The case this store would fail at if it appended what it was
        # given: passes run every few hours over a day-long window, so
        # every override is offered four or five times and one
        # disagreement would be counted as five.
        rows = self.weekday_mornings(1)
        ledger.record(rows, self.now, self.path)
        self.assertEqual(ledger.record(rows, self.now, self.path), 0)
        self.assertEqual(len(ledger.load(self.path)), 5)

    def test_overlapping_windows_file_only_what_is_new(self):
        first = self.weekday_mornings(1)
        ledger.record(first, self.now, self.path)
        later = first[2:] + [override(MONDAY + dt.timedelta(days=5))]
        self.assertEqual(ledger.record(later, self.now, self.path), 1)
        self.assertEqual(len(ledger.load(self.path)), 6)

    def test_only_an_automation_is_kept(self):
        # A script or a scene is something somebody ran on purpose a
        # moment earlier, so putting it back is a change of mind rather
        # than evidence about a standing rule.
        for cause in ("script", "scene", "brain", "person", ""):
            self.assertEqual(
                ledger.record([override(MONDAY, cause=cause)],
                              self.now, self.path), 0, cause)

    def test_a_row_with_no_stamp_or_no_automation_is_skipped(self):
        self.assertEqual(ledger.record([
            {"by_cause": "automation", "by": "automation.x"},
            {"by_cause": "automation", "ts": 1.0, "by": "", "by_name": ""},
        ], self.now, self.path), 0)

    def test_old_rows_age_out(self):
        old = override(MONDAY - dt.timedelta(days=ledger.KEEP_DAYS + 5))
        ledger.record([old] + self.weekday_mornings(1), self.now, self.path)
        kept = ledger.load(self.path)
        self.assertEqual(len(kept), 5)
        self.assertNotIn(int(old["ts"]), [r["ts"] for r in kept])

    def test_the_ledger_is_capped(self):
        many = [override(MONDAY + dt.timedelta(minutes=i))
                for i in range(ledger.MAX_ROWS + 50)]
        ledger.record(many, self.now, self.path)
        self.assertEqual(len(ledger.load(self.path)), ledger.MAX_ROWS)

    def test_a_torn_or_wrong_shaped_file_is_an_empty_ledger(self):
        for junk in ('[{"ts": 1},', '{"ts": 1}', '"nope"'):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(ledger.load(self.path), [], junk)

    def test_a_missing_directory_is_not_a_crash(self):
        ledger.save([{"ts": 1}], os.path.join(self.dir.name, "no", "o.json"))

    def test_grouping_is_by_the_automation(self):
        ledger.record(self.weekday_mornings(1)
                      + [override(MONDAY, by="automation.other")],
                      self.now, self.path)
        grouped = ledger.by_automation(ledger.load(self.path))
        self.assertEqual(sorted(grouped), ["automation.dusk",
                                           "automation.other"])


class TestWhetherThereIsAShape(LedgerCase):
    """Every case passes its own clock. A fixture whose freshness depends
    on the day the suite happens to run is a fixture that rots, and these
    stamps are fixed dates."""

    def soon_after(self, rows) -> float:
        return max(r["ts"] for r in rows) + 3600.0

    """A shape nobody would recognise, reported as one, is worse than
    the bare count: it invites somebody to write a condition around a
    coincidence."""

    def test_three_weeks_of_weekday_mornings_is_a_shape(self):
        rows = self.weekday_mornings(3)
        shape = ledger.pattern(rows, UTC, self.soon_after(rows))
        self.assertEqual(shape["events"], 15)
        self.assertEqual(shape["days"], 15)
        self.assertEqual((shape["from_hour"], shape["to_hour"]), (8, 9))
        self.assertEqual(shape["when_days"], "weekdays")

    def test_too_few_events_is_no_shape(self):
        for n in range(ledger.MIN_EVENTS):
            rows = [override(MONDAY + dt.timedelta(days=d)) for d in range(n)]
            self.assertIsNone(
                ledger.pattern(rows, UTC,
                               self.soon_after(rows) if rows else 0.0), n)

    def test_one_evening_is_not_weeks(self):
        # Four overrides in one evening is one evening. The count says so
        # already; calling it a pattern is the claim that must not be made.
        rows = [override(MONDAY + dt.timedelta(minutes=20 * i))
                for i in range(6)]
        self.assertIsNone(ledger.pattern(rows, UTC, self.soon_after(rows)))

    def test_scattered_hours_get_no_hour(self):
        rows = [override(MONDAY.replace(hour=h) + dt.timedelta(days=d))
                for d, h in enumerate((1, 6, 9, 13, 17, 21))]
        shape = ledger.pattern(rows, UTC, self.soon_after(rows))
        self.assertIsNotNone(shape)
        self.assertNotIn("from_hour", shape)

    def test_a_pattern_that_stopped_is_not_reported(self):
        # The ledger keeps two months so a shape has room to appear, but a
        # rule somebody FIXED goes on having a beautiful shape in the
        # history. A finding that cannot clear for eight weeks after the
        # problem is gone is the list nobody reads.
        rows = self.weekday_mornings(3)
        stale = max(r["ts"] for r in rows) + (
            ledger.RECENT_DAYS + 1) * 86400
        self.assertIsNone(ledger.pattern(rows, UTC, stale))

    def test_a_pattern_still_happening_is(self):
        rows = self.weekday_mornings(3)
        fresh = max(r["ts"] for r in rows) + 2 * 86400
        self.assertIsNotNone(ledger.pattern(rows, UTC, fresh))

    def test_a_week_that_is_not_only_weekdays_gets_no_day_claim(self):
        rows = self.weekday_mornings(1) + [
            override(MONDAY + dt.timedelta(days=5))]
        shape = ledger.pattern(rows, UTC, self.soon_after(rows))
        self.assertNotIn("when_days", shape)


class TestTheHoursItNames(unittest.TestCase):
    """`_band` reports the hours that are OCCUPIED, not the window that
    found them — the bug this class exists for, found by driving it."""

    def test_all_at_one_hour_names_that_hour(self):
        # The first version searched four-hour windows and took whichever
        # start it tried first, so fifteen overrides all at 08:10 came
        # back as "between 05:00 and 09:00" — a condition that would
        # stand the automation down for three hours nothing happens in.
        self.assertEqual(ledger._band([8] * 15), (8, 9, 1.0))

    def test_a_real_spread_keeps_its_width(self):
        self.assertEqual(ledger._band([7, 8, 9] * 4), (7, 10, 1.0))

    def test_it_wraps_midnight(self):
        # 22:00-01:00 is a real bedtime, and a band that could not cross
        # midnight would report the busier half and call it the answer.
        start, end, share = ledger._band([22, 23, 0, 23, 22, 0])
        self.assertEqual((start, end), (22, 1))
        self.assertEqual(share, 1.0)

    def test_a_scattered_day_scores_below_the_bar(self):
        _start, _end, share = ledger._band([1, 6, 9, 13, 17, 21, 23])
        self.assertLess(share, ledger.BAND_SHARE)

    def test_a_stray_does_not_move_the_hour(self):
        start, end, share = ledger._band([19, 19, 19, 19, 3])
        self.assertEqual((start, end), (19, 20))
        self.assertGreaterEqual(share, ledger.BAND_SHARE)

    def test_no_hours_is_no_band(self):
        self.assertIsNone(ledger._band([]))


if __name__ == "__main__":
    unittest.main()
