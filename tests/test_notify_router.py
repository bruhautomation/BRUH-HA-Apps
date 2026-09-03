"""The notification router: whether a finding reaches a phone, and when.

Every case here is written against the way the thing it guards actually
fails. A quiet window that crosses midnight is the normal case and the
one a naive comparison gets backwards; a held finding that was fixed
overnight is the one delivery that teaches somebody these messages are
not about anything; and "urgency" is only worth having if it is not just
severity spelled differently.
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

import notify_router  # noqa: E402


class TestReadingTheOption(unittest.TestCase):
    def test_the_shapes_people_type(self):
        for text, want in (("22", 22), ("22:00", 22), ("07:30", 7),
                           ("0", 0), ("23", 23), (" 6 ", 6)):
            self.assertEqual(notify_router.parse_hour(text), want, text)

    def test_unset_and_rubbish_are_both_none(self):
        for text in ("", None, "  ", "late", "24", "-1", "99:00", "x:00"):
            self.assertIsNone(notify_router.parse_hour(text), repr(text))


class TestTheQuietWindow(unittest.TestCase):
    """The half of this that a plain `start <= h < end` gets wrong."""

    def at(self, hour: int) -> float:
        return dt.datetime(2026, 3, 4, hour, 30,
                           tzinfo=dt.timezone.utc).timestamp()

    def test_a_window_that_crosses_midnight(self):
        # 22:00 -> 07:00 is what people actually set, and it is the case
        # an ordinary range comparison answers backwards at every hour.
        for hour in (22, 23, 0, 3, 6):
            self.assertTrue(
                notify_router.in_quiet_hours(self.at(hour), 22, 7),
                f"{hour}:30 should be quiet")
        for hour in (7, 9, 13, 21):
            self.assertFalse(
                notify_router.in_quiet_hours(self.at(hour), 22, 7),
                f"{hour}:30 should not be quiet")

    def test_a_window_inside_one_day(self):
        for hour in (9, 12, 16):
            self.assertTrue(notify_router.in_quiet_hours(self.at(hour), 9, 17))
        for hour in (8, 17, 23):
            self.assertFalse(notify_router.in_quiet_hours(self.at(hour), 9, 17))

    def test_unset_is_no_quiet_hours(self):
        self.assertFalse(notify_router.in_quiet_hours(self.at(3), None, 7))
        self.assertFalse(notify_router.in_quiet_hours(self.at(3), 22, None))

    def test_the_same_hour_twice_is_not_a_permanent_silence(self):
        # Somebody has set both boxes to 22 by accident. Reading that as
        # "never notify" is a notifier that has silently switched itself
        # off; reading it as "no quiet hours" is the recoverable answer.
        for hour in (0, 12, 22, 23):
            self.assertFalse(
                notify_router.in_quiet_hours(self.at(hour), 22, 22))

    def test_the_timezone_actually_moves_the_window(self):
        # The test that fails if the argument were ignored, which is the
        # shape this bug takes: 02:30 UTC is 21:30 in New York, outside a
        # 22->7 window that it is squarely inside in UTC.
        try:
            from zoneinfo import ZoneInfo
            ny = ZoneInfo("America/New_York")
        except Exception:  # noqa: BLE001 — a system with no tz database
            self.skipTest("no zoneinfo data on this system")
        when = self.at(2)
        self.assertTrue(notify_router.in_quiet_hours(when, 22, 7))
        self.assertFalse(notify_router.in_quiet_hours(when, 22, 7, ny))

    def test_when_the_quiet_ends(self):
        when = self.at(2)
        ends = notify_router.quiet_ends_at(when, 7)
        self.assertEqual(
            dt.datetime.fromtimestamp(ends, dt.timezone.utc).hour, 7)
        self.assertTrue(0 < ends - when < 5 * 3600)

    def test_the_end_is_tomorrow_when_it_has_already_passed_today(self):
        # 23:30 with the window ending at 07:00: the next 07:00 is the
        # one tomorrow, and an implementation that took today's would
        # hand the flush loop a negative wait and send immediately.
        ends = notify_router.quiet_ends_at(self.at(23), 7)
        self.assertGreater(ends - self.at(23), 6 * 3600)


class TestHowSoon(unittest.TestCase):
    def test_urgency_is_not_severity_spelled_differently(self):
        # The whole reason this axis exists: a critical row that can wait
        # three weeks, and an info row that cannot wait until morning.
        battery = {"source": "check:forecast.battery", "severity": "critical"}
        offline = {"source": "check:dev.unavailable", "severity": "info"}
        self.assertEqual(notify_router.urgency_of(battery), "whenever")
        self.assertEqual(notify_router.urgency_of(offline), "now")

    def test_a_family_is_matched_by_its_prefix(self):
        for source in ("check:forecast.decline", "check:base.unusual",
                       "check:reg.no_area", "check:auto.forgotten_off"):
            self.assertEqual(notify_router.urgency_of({"source": source}),
                             "whenever", source)

    def test_a_named_check_beats_its_family(self):
        self.assertEqual(
            notify_router.urgency_of({"source": "check:dev.implausible"}),
            "now")

    def test_an_unlisted_producer_is_the_default(self):
        for source in ("energy", "", "fix", "check:something.new"):
            self.assertEqual(notify_router.urgency_of({"source": source}),
                             notify_router.DEFAULT_URGENCY, source)

    def test_every_declared_urgency_is_one_this_module_knows(self):
        for source, level in notify_router.PRODUCER_URGENCY.items():
            self.assertIn(level, notify_router.URGENCY, source)
        self.assertIn(notify_router.DEFAULT_URGENCY, notify_router.URGENCY)


class TestTheSeverityFloor(unittest.TestCase):
    def rows(self):
        return [{"severity": s, "text": s} for s in
                ("info", "warning", "serious", "critical")]

    def test_the_floor_is_inclusive(self):
        kept = notify_router.worth_sending(self.rows(), "serious")
        self.assertEqual([r["severity"] for r in kept],
                         ["serious", "critical"])

    def test_an_unknown_floor_falls_back_rather_than_letting_everything_out(self):
        kept = notify_router.worth_sending(self.rows(), "urgent")
        self.assertEqual([r["severity"] for r in kept],
                         ["serious", "critical"])

    def test_a_row_with_a_nonsense_severity_is_treated_as_a_warning(self):
        kept = notify_router.worth_sending(
            [{"severity": "spicy", "text": "x"}], "info")
        self.assertEqual(len(kept), 1)
        kept = notify_router.worth_sending(
            [{"severity": "spicy", "text": "x"}], "serious")
        self.assertEqual(kept, [])


class TestTheHoldQueue(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "notify-queue.json")

    def finding(self, ts, text="Something", severity="warning"):
        return {"ts": ts, "text": text, "severity": severity}

    def test_held_rows_survive_a_restart(self):
        notify_router.hold([self.finding(1), self.finding(2)], 100.0,
                           self.path)
        self.assertEqual(len(notify_router.load_queue(self.path)), 2)

    def test_the_same_finding_twice_is_one_line(self):
        # The sweeps re-file, and being handed the same sentence twice in
        # one digest is how a digest stops being read.
        notify_router.hold([self.finding(1)], 100.0, self.path)
        notify_router.hold([self.finding(1)], 200.0, self.path)
        self.assertEqual(len(notify_router.load_queue(self.path)), 1)

    def test_taking_the_queue_empties_it(self):
        notify_router.hold([self.finding(1)], 100.0, self.path)
        self.assertEqual(len(notify_router.take_queue({1}, self.path)), 1)
        self.assertEqual(notify_router.load_queue(self.path), [])

    def test_a_finding_fixed_overnight_is_never_announced(self):
        # The delivery that would teach somebody these messages are not
        # about anything: a problem that went away at four in the morning
        # arriving as news at seven.
        notify_router.hold([self.finding(1, "Gone"), self.finding(2, "Still")],
                           100.0, self.path)
        out = notify_router.take_queue({2}, self.path)
        self.assertEqual([r["ts"] for r in out], [2])

    def test_an_unreadable_store_sends_everything_rather_than_nothing(self):
        # Not knowing whether a problem is over is not evidence that it is.
        notify_router.hold([self.finding(1), self.finding(2)], 100.0,
                           self.path)
        self.assertEqual(len(notify_router.take_queue(None, self.path)), 2)

    def test_the_queue_is_capped(self):
        notify_router.hold(
            [self.finding(i) for i in range(notify_router.QUEUE_MAX + 40)],
            100.0, self.path)
        self.assertEqual(len(notify_router.load_queue(self.path)),
                         notify_router.QUEUE_MAX)

    def test_a_torn_file_is_an_empty_queue_rather_than_a_crash(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('[{"ts": 1},')
        self.assertEqual(notify_router.load_queue(self.path), [])

    def test_a_file_holding_the_wrong_shape_is_an_empty_queue(self):
        for junk in ('{"ts": 1}', '"nope"', '[1, 2, 3]'):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(notify_router.load_queue(self.path), [],
                             junk)

    def test_a_missing_directory_is_not_a_crash(self):
        # A dev checkout has no /data, and the panel must still run.
        notify_router.save_queue([{"ts": 1}],
                                 os.path.join(self.dir.name, "no", "q.json"))

    def test_the_row_is_not_a_second_copy_of_the_finding(self):
        notify_router.hold([{
            "ts": 1, "text": "Short", "severity": "warning",
            "detail": "x" * 5000, "fix": "y" * 5000, "html": "z" * 5000,
        }], 100.0, self.path)
        raw = open(self.path, encoding="utf-8").read()
        self.assertLess(len(raw), 400)
        self.assertNotIn("xxxx", raw)
        self.assertEqual(json.loads(raw)[0]["ts"], 1)


class TestTheMessage(unittest.TestCase):
    def rows(self, n):
        return [{"ts": i, "text": f"Problem {i}", "severity": "warning"}
                for i in range(n)]

    def test_one_row_and_many_read_as_english(self):
        self.assertIn("a problem", notify_router.compose(self.rows(1))[0])
        self.assertIn("3 problems", notify_router.compose(self.rows(3))[0])

    def test_a_held_digest_says_it_was_held(self):
        title, _body = notify_router.compose(self.rows(2), held=True)
        self.assertIn("held", title.lower())

    def test_a_long_list_is_counted_rather_than_truncated(self):
        # A list that simply stops reads as the whole of what happened.
        n = notify_router.LINES_MAX + 7
        _title, body = notify_router.compose(self.rows(n))
        self.assertIn("7 more", body)
        self.assertIn("Problem 0", body)

    def test_the_body_is_bounded(self):
        rows = [{"ts": i, "text": "x" * 400, "severity": "warning"}
                for i in range(30)]
        _title, body = notify_router.compose(rows)
        self.assertLessEqual(len(body), notify_router.MESSAGE_MAX)


if __name__ == "__main__":
    unittest.main()
