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
        ny = None
        try:
            from zoneinfo import ZoneInfo
            ny = ZoneInfo("America/New_York")
        except Exception:  # noqa: BLE001 — a system with no tz database
            pass
        if ny is None:
            # Bound before the try and tested after it, rather than
            # skipping from inside the handler: a name assigned only on
            # the branch that did not raise is one every reader after it
            # has to prove is set.
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
        # ...and the fallback is the shipped default, read off the one
        # constant rather than spelled again here.
        kept = notify_router.worth_sending(self.rows(), "urgent")
        self.assertEqual([r["severity"] for r in kept], ["critical"])
        self.assertEqual(notify_router.DEFAULT_MIN_SEVERITY, "critical")

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
        with open(self.path, encoding="utf-8") as fh:
            raw = fh.read()
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


class TestEveryNamedCheckExists(unittest.TestCase):
    """A key that names a check that does not exist is an urgency nobody
    gets: `check:sys.disk_low` said `now` about a check called
    `sys.disk_space`, so a full disk waited for morning like a tidy-up.
    The same test `shadow_findings` keeps over its own set."""

    def test_every_exact_key_names_a_real_check(self):
        import checks  # noqa: PLC0415
        for source in notify_router.PRODUCER_URGENCY:
            if not source.startswith("check:") or source.endswith("."):
                continue
            self.assertIn(source[len("check:"):], checks.CHECK_IDS, source)

    def test_every_family_prefix_has_a_check_in_it(self):
        import checks  # noqa: PLC0415
        for source in notify_router.PRODUCER_URGENCY:
            if not (source.startswith("check:") and source.endswith(".")):
                continue
            family = source[len("check:"):]
            self.assertTrue(any(c.startswith(family) for c in checks.CHECK_IDS),
                            source)

    def test_a_full_disk_is_now(self):
        self.assertEqual(
            notify_router.urgency_of({"source": "check:sys.disk_space"}), "now")


class TestWhereATapLands(unittest.TestCase):
    """A notification about a finding opens the panel, not Home
    Assistant's front page — but only where the notifier reads the keys,
    and only once the Supervisor has said what this add-on's slug is."""

    def test_a_companion_app_gets_the_panel_under_both_spellings(self):
        self.assertEqual(
            notify_router.open_link("notify.mobile_app_phone", "/hassio/ingress/x"),
            {"url": "/hassio/ingress/x", "clickAction": "/hassio/ingress/x"})

    def test_any_other_notifier_gets_nothing_it_might_misread(self):
        self.assertEqual(notify_router.open_link("notify.telegram", "/x"), {})

    def test_no_slug_is_no_link_never_a_guess(self):
        self.assertEqual(notify_router.open_link("mobile_app_phone", None), {})
        self.assertEqual(notify_router.open_link("mobile_app_phone", ""), {})


class TestTheThreeTiers(unittest.TestCase):
    """How loud a row is allowed to be, and why it is a PAIR.

    Escalating on severity alone wakes a house about a battery three
    weeks from dying; escalating on urgency alone wakes it about every
    sensor that blinked. Only the pair describes the leak-and-freeze
    class this exists for, and everything under the floor is quiet —
    which is not lost, because the row is on the Findings tab either way.
    """

    def row(self, severity, source="check:dev.unavailable"):
        return {"ts": 1, "text": "x", "severity": severity, "source": source}

    def test_critical_and_now_escalates(self):
        self.assertEqual(notify_router.tier_of(self.row("critical")),
                         "escalate")

    def test_critical_but_not_urgent_is_notified_once(self):
        # A battery forecast is the canonical case: as bad as it gets and
        # three weeks away.
        self.assertEqual(
            notify_router.tier_of(
                self.row("critical", "check:forecast.battery")),
            "notify")

    def test_urgent_but_not_critical_is_not_escalated(self):
        self.assertEqual(notify_router.tier_of(self.row("serious")), "quiet")
        self.assertEqual(
            notify_router.tier_of(self.row("serious"), "serious"), "notify")

    def test_under_the_floor_is_quiet_whatever_its_urgency(self):
        for sev in ("info", "warning", "serious"):
            self.assertEqual(notify_router.tier_of(self.row(sev)), "quiet",
                             sev)

    def test_the_shipped_default_makes_a_serious_row_quiet(self):
        # The change this release is about, stated as behaviour rather
        # than as a constant: a dying battery no longer rings a phone
        # unless somebody asks for it back.
        self.assertEqual(
            notify_router.tier_of({"severity": "serious",
                                   "source": "check:forecast.battery"}),
            "quiet")

    def test_an_unlisted_producer_can_never_escalate(self):
        # DEFAULT_URGENCY is `today`, so only the producers explicitly
        # marked `now` can wake a house — a set of lines of code rather
        # than a set of sentences a model wrote.
        for source in ("energy", "", "fix", "check:something.new"):
            self.assertEqual(
                notify_router.tier_of(self.row("critical", source)),
                "notify", source)

    def test_classify_splits_one_batch_three_ways_in_order(self):
        rows = [self.row("critical"), self.row("serious"),
                self.row("critical", "check:forecast.battery")]
        out = notify_router.classify(rows)
        self.assertEqual(set(out), set(notify_router.TIERS))
        self.assertEqual([r["source"] for r in out["escalate"]],
                         ["check:dev.unavailable"])
        self.assertEqual([r["source"] for r in out["notify"]],
                         ["check:forecast.battery"])
        self.assertEqual(len(out["quiet"]), 1)

    def test_classify_keeps_every_row_exactly_once(self):
        rows = [self.row(s, p) for s in
                ("info", "warning", "serious", "critical")
                for p in ("check:dev.unavailable", "check:forecast.battery")]
        out = notify_router.classify(rows)
        self.assertEqual(sum(len(v) for v in out.values()), len(rows))


class TestTheLadder(unittest.TestCase):
    """A reminder that repeats until somebody answers, and then stops.

    Every case here is about one of the two ways this fails: a house
    reminded for ever about a problem it has fixed, or a leak that was
    mentioned once at 3am and never again.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "notify-escalation.json")

    def finding(self, ts=1, text="Water where it should not be"):
        return {"ts": ts, "text": text, "severity": "critical",
                "source": "check:dev.unavailable"}

    def test_every_rung_is_later_than_the_one_before(self):
        # The usage tracker's `test_every_backoff_actually_backs_off`:
        # a ladder whose second step is shorter than its first asks more
        # often the longer a problem stands.
        self.assertEqual(list(notify_router.ESCALATION_S),
                         sorted(notify_router.ESCALATION_S))
        self.assertEqual(len(set(notify_router.ESCALATION_S)),
                         len(notify_router.ESCALATION_S))
        self.assertGreater(notify_router.ESCALATION_S[0], 0)

    def test_the_first_reminder_is_due_one_rung_after_the_announcement(self):
        notify_router.begin_escalation([self.finding()], 1000.0, self.path)
        [row] = notify_router.load_escalations(self.path).values()
        self.assertEqual(row["next_at"], 1000.0 + notify_router.ESCALATION_S[0])
        self.assertEqual(row["sent_at"], [1000])
        self.assertEqual(notify_router.due_escalations(1000.0, self.path), [])

    def test_the_whole_ladder_and_then_it_stops(self):
        notify_router.begin_escalation([self.finding()], 0.0, self.path)
        seen = []
        for rung in notify_router.ESCALATION_S:
            due = notify_router.due_escalations(rung, self.path)
            self.assertEqual([r["ts"] for r in due], [1], rung)
            seen.append(rung)
            notify_router.record_reminder(1, rung, self.path)
        # Three reminders, and then nothing is ever due again.
        self.assertEqual(len(seen), len(notify_router.ESCALATION_S))
        self.assertEqual(notify_router.due_escalations(10 ** 9, self.path), [])
        [row] = notify_router.load_escalations(self.path).values()
        self.assertEqual(row["next_at"], 0)
        self.assertEqual(len(row["sent_at"]),
                         len(notify_router.ESCALATION_S) + 1)

    def test_nothing_is_due_before_its_rung(self):
        notify_router.begin_escalation([self.finding()], 0.0, self.path)
        self.assertEqual(
            notify_router.due_escalations(
                notify_router.ESCALATION_S[0] - 1, self.path), [])

    def test_the_ledger_survives_a_restart_at_the_rung_it_was_on(self):
        # `_resume_backoff`'s reason: a restart is the first thing somebody
        # does when their phone is going off, and a ladder held in memory
        # would start again from the first rung.
        notify_router.begin_escalation([self.finding()], 0.0, self.path)
        notify_router.record_reminder(1, notify_router.ESCALATION_S[0],
                                      self.path)
        # A fresh read is all a restart is, here.
        rows = notify_router.load_escalations(self.path)
        self.assertEqual(rows[1]["next_at"], notify_router.ESCALATION_S[1])
        self.assertEqual(notify_router.next_escalation_at(self.path),
                         notify_router.ESCALATION_S[1])
        self.assertEqual(
            notify_router.due_escalations(notify_router.ESCALATION_S[1] - 1,
                                          self.path), [])
        self.assertEqual(
            [r["ts"] for r in notify_router.due_escalations(
                notify_router.ESCALATION_S[1], self.path)], [1])

    def test_a_row_that_was_answered_stops_being_reminded(self):
        notify_router.begin_escalation(
            [self.finding(1), self.finding(2)], 0.0, self.path)
        gone = notify_router.prune_escalations({2}, self.path)
        self.assertEqual(gone, [1])
        self.assertEqual(list(notify_router.load_escalations(self.path)), [2])
        self.assertEqual(
            [r["ts"] for r in notify_router.due_escalations(10 ** 9, self.path)],
            [2])

    def test_pruning_nothing_leaves_the_ladder_alone(self):
        notify_router.begin_escalation([self.finding()], 0.0, self.path)
        self.assertEqual(notify_router.prune_escalations({1}, self.path), [])
        self.assertEqual(list(notify_router.load_escalations(self.path)), [1])

    def test_starting_a_row_twice_does_not_reset_its_ladder(self):
        notify_router.begin_escalation([self.finding()], 0.0, self.path)
        notify_router.record_reminder(1, notify_router.ESCALATION_S[0],
                                      self.path)
        self.assertEqual(
            notify_router.begin_escalation([self.finding()], 9999.0, self.path),
            0)
        [row] = notify_router.load_escalations(self.path).values()
        self.assertEqual(row["first_at"], 0)
        self.assertEqual(len(row["sent_at"]), 2)

    def test_the_cap_refuses_rather_than_dropping_a_climbing_row(self):
        first = [self.finding(i) for i in
                 range(1, notify_router.ESCALATION_MAX_ROWS + 1)]
        self.assertEqual(
            notify_router.begin_escalation(first, 0.0, self.path),
            notify_router.ESCALATION_MAX_ROWS)
        self.assertEqual(
            notify_router.begin_escalation([self.finding(99999)], 0.0,
                                           self.path), 0)
        rows = notify_router.load_escalations(self.path)
        self.assertEqual(len(rows), notify_router.ESCALATION_MAX_ROWS)
        self.assertIn(1, rows)      # the oldest is still climbing
        self.assertNotIn(99999, rows)

    def test_nothing_due_is_no_wait_at_all(self):
        self.assertEqual(notify_router.next_escalation_at(self.path), 0.0)
        notify_router.begin_escalation([self.finding()], 0.0, self.path)
        for rung in notify_router.ESCALATION_S:
            notify_router.record_reminder(1, rung, self.path)
        self.assertEqual(notify_router.next_escalation_at(self.path), 0.0)

    def test_a_torn_or_wrong_shaped_file_is_an_empty_ladder(self):
        for junk in ('{"1": {"sent_at": [1]},', '[1, 2]', '"nope"',
                     '{"1": 3}', '{"x": {"sent_at": [1]}}',
                     '{"1": {"sent_at": []}}'):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(notify_router.load_escalations(self.path), {},
                             junk)

    def test_a_missing_directory_is_not_a_crash(self):
        notify_router.save_escalations(
            {1: {"ts": 1, "sent_at": [1], "first_at": 1, "next_at": 2}},
            os.path.join(self.dir.name, "no", "e.json"))

    def test_the_row_is_not_a_second_copy_of_the_finding(self):
        notify_router.begin_escalation([{
            "ts": 1, "text": "Short", "severity": "critical",
            "source": "check:dev.unavailable",
            "detail": "x" * 5000, "fix": "y" * 5000,
        }], 100.0, self.path)
        with open(self.path, encoding="utf-8") as fh:
            raw = fh.read()
        self.assertLess(len(raw), 400)
        self.assertNotIn("xxxx", raw)

    def test_the_state_is_readable_from_diagnostics(self):
        notify_router.begin_escalation([self.finding()], 100.0, self.path)
        state = notify_router.escalation_state(self.path)
        self.assertEqual(state["escalating"], 1)
        self.assertEqual(state["escalation_reminders_sent"], 0)
        self.assertEqual(state["escalation_since"], 100)
        self.assertEqual(state["escalation_next_at"],
                         int(100 + notify_router.ESCALATION_S[0]))
        notify_router.record_reminder(1, 100 + notify_router.ESCALATION_S[0],
                                      self.path)
        self.assertEqual(
            notify_router.escalation_state(
                self.path)["escalation_reminders_sent"], 1)


class TestWhatAReminderSays(unittest.TestCase):
    def row(self, sends, first_at=0.0):
        return {"ts": 1, "text": "Water under the sink", "severity": "critical",
                "first_at": first_at, "sent_at": [int(first_at)] * sends}

    def test_it_says_which_repeat_it_is(self):
        _t, body = notify_router.compose_escalation(self.row(2))
        self.assertIn("2nd reminder", body)
        _t, body = notify_router.compose_escalation(self.row(1))
        self.assertIn("1st reminder", body)

    def test_it_says_since_when_in_the_house_s_own_clock(self):
        when = dt.datetime(2026, 3, 4, 3, 10,
                           tzinfo=dt.timezone.utc).timestamp()
        _t, body = notify_router.compose_escalation(self.row(2, when))
        self.assertIn("03:10", body)

    def test_the_last_one_says_it_will_not_ask_again(self):
        last = len(notify_router.ESCALATION_S)
        _t, body = notify_router.compose_escalation(self.row(last))
        self.assertIn("not ask about this again", body)
        _t, body = notify_router.compose_escalation(self.row(last - 1))
        self.assertNotIn("not ask about this again", body)

    def test_it_carries_the_finding_and_is_bounded(self):
        row = self.row(1)
        row["text"] = "z" * 4000
        _title, body = notify_router.compose_escalation(row)
        self.assertLessEqual(len(body), notify_router.MESSAGE_MAX)
        self.assertIn("critical", body)


class TestTheDefaultFloorIsWrittenDownOnce(unittest.TestCase):
    """Three files have to agree, and they are read from disk rather than
    restated: `config.yaml` is what a fresh install gets, `run.sh`'s export
    is the fallback for a Supervisor that cannot be read, and the panel's
    own constant is what an unrecognised value falls back to. A default
    that disagrees with itself is a second answer that wins exactly when
    nobody is looking (`${VAR:-default}`'s rule)."""

    def test_config_run_sh_and_the_panel_all_say_critical(self):
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "brain", "config.yaml"),
                  encoding="utf-8") as f:
            conf = f.read()
        with open(os.path.join(root, "brain", "run.sh"),
                  encoding="utf-8") as f:
            run = f.read()
        in_config = re.search(
            r"^  findings_notify_min_severity:\s*(\S+)\s*$", conf, re.M)
        in_run = re.search(
            r"bashio::config 'findings_notify_min_severity' '([^']*)'", run)
        self.assertIsNotNone(in_config)
        self.assertIsNotNone(in_run)
        self.assertEqual(in_config.group(1), notify_router.DEFAULT_MIN_SEVERITY)
        self.assertEqual(in_run.group(1), notify_router.DEFAULT_MIN_SEVERITY)
        self.assertEqual(notify_router.DEFAULT_MIN_SEVERITY, "critical")

    def test_the_option_s_help_text_names_the_way_back(self):
        # Raising a default silently is how somebody's phone goes quiet
        # with nothing on screen saying why, so the description says both
        # what it now does and the one word that restores the old
        # behaviour.
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "brain", "translations", "en.yaml"),
                  encoding="utf-8") as f:
            text = f.read()
        block = text.split("findings_notify_min_severity:", 1)[1]
        block = block.split("\n  notify_quiet_start:", 1)[0]
        self.assertIn('"critical" (the default)', block)
        self.assertIn('"serious"', block)
