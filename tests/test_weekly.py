"""The weekly report, and the four ways it stops being read.

A report that lists everything, one that arrives every week saying
nothing, one whose "one thing to do" is the one with the best sentence
rather than the most consequence, and one that reports "I could not
look" as good news. Each is a way a working report becomes an ignored
one, and none of them raises anything.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import weekly  # noqa: E402

DAY = 86400.0
NOW = 1_756_800_000.0          # a fixed Wednesday afternoon
SINCE = NOW - 7 * DAY


def finding(ts_offset: float, severity: str = "warning", status: str = "open",
            text: str = "something", **extra) -> dict:
    row = {"ts": NOW + ts_offset, "severity": severity, "status": status,
           "text": text, "snooze_until": 0}
    row.update(extra)
    return row


def settled(ts_offset: float, kind: str = "fixed", title: str = "") -> dict:
    return {"ts": NOW + ts_offset, "kind": kind, "text": "x",
            "key": f"k{ts_offset}{kind}{title}", "source_title": title}


class TestWhatTheWeekHeld(unittest.TestCase):
    def test_still_open_is_named_for_what_it_actually_counts(self):
        # A row raised and settled inside the same week has left the
        # store, so nothing here can count what was "filed" — and the
        # honest fix is to name the number rather than dress it up.
        rows = [finding(-2 * DAY), finding(-30 * DAY), finding(-1 * DAY)]
        got = weekly.week_findings(rows, [], SINCE)
        self.assertEqual(got["still_open"], 2)
        self.assertEqual(got["open_now"], 3)

    def test_an_ending_is_a_label_and_both_labels_are_counted(self):
        ended = [settled(-DAY, "fixed"), settled(-2 * DAY, "fixed"),
                 settled(-3 * DAY, "ignored"), settled(-20 * DAY, "fixed")]
        got = weekly.week_findings([], ended, SINCE)
        self.assertEqual(got["settled"], 3)
        self.assertEqual((got["confirmed"], got["wrong"]), (2, 1))

    def test_who_raised_them_rides_along_capped(self):
        ended = [settled(-DAY, title=f"Check {i % 6}") for i in range(20)]
        got = weekly.week_findings([], ended, SINCE)
        self.assertLessEqual(len(got["by_source"]), weekly.MAX_SETTLED_SOURCES)
        self.assertTrue(all(isinstance(t, str) and isinstance(n, int)
                            for t, n in got["by_source"]))

    def test_a_settled_entry_with_no_producer_scores_nothing(self):
        # A ledger written before that field existed must not become one
        # anonymous producer with everybody's endings under it.
        got = weekly.week_findings([], [settled(-DAY, title="")], SINCE)
        self.assertEqual(got["settled"], 1)
        self.assertEqual(got["by_source"], [])

    def test_rubbish_rows_are_skipped_rather_than_crashing(self):
        got = weekly.week_findings(["x", None, {}], ["y", None, {}], SINCE)
        self.assertEqual(got["still_open"], 0)
        self.assertEqual(got["settled"], 0)


class TestWhatWasLearned(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "memory.log.jsonl")

    def write(self, rows):
        with open(self.path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def test_lines_added_this_week_are_what_was_learned(self):
        self.write([
            {"ts": NOW - 30 * DAY, "added": ["old thing"], "removed": []},
            {"ts": NOW - 2 * DAY, "added": ["the freezer is in the garage"],
             "removed": []},
            {"ts": NOW - DAY, "added": ["bins go out on Tuesday"],
             "removed": ["bins go out on Monday"]},
        ])
        got = weekly.learned(self.path, SINCE)
        self.assertTrue(got["available"])
        self.assertEqual(got["total"], 2)
        self.assertEqual(got["removed"], 1)
        self.assertIn("bins go out on Tuesday", got["added"])
        self.assertNotIn("old thing", got["added"])

    def test_a_correction_is_counted_and_never_quoted(self):
        # Quoting the line that LEFT the document back at somebody as
        # news is worse than saying a correction happened.
        self.write([{"ts": NOW - DAY, "added": [],
                     "removed": ["the dog is called Sam"]}])
        got = weekly.learned(self.path, SINCE)
        self.assertEqual(got["removed"], 1)
        self.assertEqual(got["added"], [])
        self.assertEqual(got["total"], 0)

    def test_a_long_week_is_capped_and_the_count_is_not(self):
        self.write([{"ts": NOW - DAY,
                     "added": [f"fact {i}" for i in range(40)],
                     "removed": []}])
        got = weekly.learned(self.path, SINCE)
        self.assertEqual(got["total"], 40)
        self.assertEqual(len(got["added"]), weekly.MAX_LEARNED)

    def test_a_log_that_cannot_be_read_is_not_a_quiet_week(self):
        # The failure this flag exists for: "I could not look" and
        # "nothing was learned" are different claims, and only the second
        # belongs in a report.
        got = weekly.learned(os.path.join(self.dir.name, "nope"), SINCE)
        self.assertFalse(got["available"])
        self.assertEqual(got["total"], 0)

    def test_a_torn_log_reads_what_it_can(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json\n")
            fh.write(json.dumps({"ts": NOW - DAY, "added": ["kept"]}) + "\n")
            fh.write('"a string"\n')
            fh.write(json.dumps({"added": ["no stamp"]}) + "\n")
            fh.write(json.dumps({"ts": True, "added": ["a bool stamp"]}) + "\n")
        got = weekly.learned(self.path, SINCE)
        self.assertEqual(got["added"], ["kept"])


class TestTheOneThing(unittest.TestCase):
    """Chosen before the model, because a model picks what it can write."""

    def test_the_worst_severity_leads(self):
        rows = [finding(-DAY, "warning", text="a warning"),
                finding(-2 * DAY, "critical", text="the critical one"),
                finding(-3 * DAY, "serious", text="a serious one")]
        self.assertEqual(weekly.one_thing(rows, NOW)["text"], "the critical one")

    def test_within_a_severity_the_longest_open_leads(self):
        rows = [finding(-DAY, "serious", text="new"),
                finding(-20 * DAY, "serious", text="old"),
                finding(-5 * DAY, "serious", text="middling")]
        self.assertEqual(weekly.one_thing(rows, NOW)["text"], "old")

    def test_a_snoozed_row_is_not_the_one_thing_to_do(self):
        rows = [finding(-DAY, "critical", text="snoozed",
                        snooze_until=NOW + DAY),
                finding(-DAY, "warning", text="live")]
        self.assertEqual(weekly.one_thing(rows, NOW)["text"], "live")

    def test_a_row_being_fixed_or_fixed_is_not_a_thing_to_do(self):
        rows = [finding(-DAY, "critical", status="fixing", text="in hand"),
                finding(-DAY, "critical", status="fixed", text="done"),
                finding(-DAY, "info", text="the only open one")]
        self.assertEqual(weekly.one_thing(rows, NOW)["text"],
                         "the only open one")

    def test_nothing_open_is_None_rather_than_a_stretch(self):
        self.assertIsNone(weekly.one_thing([], NOW))
        self.assertIsNone(weekly.one_thing(
            [finding(-DAY, status="fixed")], NOW))

    def test_an_unknown_severity_sorts_last_rather_than_first(self):
        rows = [finding(-40 * DAY, "urgent-ish", text="made up"),
                finding(-DAY, "info", text="known")]
        self.assertEqual(weekly.one_thing(rows, NOW)["text"], "known")


class TestWorthReporting(unittest.TestCase):
    def state(self, **kw):
        base = {"findings": {"still_open": 0, "settled": 0, "open_now": 0},
                "learned": {"available": True, "total": 0},
                "energy": {"available": False, "reason": "none"}}
        base.update(kw)
        return base

    def test_a_week_with_nothing_in_it_sends_nothing(self):
        self.assertFalse(weekly.worth_reporting(self.state()))

    def test_a_finding_raised_or_answered_is_material(self):
        self.assertTrue(weekly.worth_reporting(
            self.state(findings={"still_open": 1, "settled": 0})))
        self.assertTrue(weekly.worth_reporting(
            self.state(findings={"still_open": 0, "settled": 1})))

    def test_something_learned_is_material(self):
        self.assertTrue(weekly.worth_reporting(
            self.state(learned={"available": True, "total": 3})))

    def test_a_meter_reading_is_material_on_its_own(self):
        # This is the one that makes the report weekly rather than
        # occasional: a house that used electricity had a week.
        self.assertTrue(weekly.worth_reporting(self.state(
            energy={"available": True, "energy": {"this": 42.0}})))

    def test_a_meter_that_could_not_be_read_is_not_material(self):
        self.assertFalse(weekly.worth_reporting(self.state(
            energy={"available": True})))
        self.assertFalse(weekly.worth_reporting(self.state(
            energy={"available": False, "energy": {"this": 42.0}})))

    def test_open_findings_from_before_the_week_are_not_this_week(self):
        # Otherwise a house with one permanently open finding gets a
        # report every Sunday saying the same thing, which is the report
        # people mute.
        rows = [finding(-30 * DAY)]
        state = weekly.gather(rows, [], {}, SINCE, memory_path="/nope",
                              now=NOW)
        self.assertFalse(weekly.worth_reporting(state))
        self.assertIsNotNone(state["one_thing"])


class TestTheMessage(unittest.TestCase):
    def test_a_reply_that_is_barely_an_answer_is_not_sent(self):
        self.assertEqual(weekly.tidy("Fine."), "")
        self.assertEqual(weekly.tidy(""), "")
        self.assertEqual(weekly.tidy(None), "")

    def test_a_long_reply_is_capped(self):
        body = weekly.tidy(" ".join(["word"] * 400))
        self.assertLessEqual(len(body.split(" ")), weekly.MAX_WORDS + 1)
        self.assertTrue(body.endswith("…"))

    def test_paragraph_breaks_survive_and_everything_else_collapses(self):
        body = weekly.tidy(
            "The house used  a little   more than last week.\n"
            "It was warm.\n\n"
            "One  door was left open on Tuesday and nothing else came up.")
        self.assertIn("\n\n", body)
        self.assertNotIn("  ", body)
        self.assertEqual(body.count("\n\n"), 1)


class TestTheFrame(unittest.TestCase):
    def frame_for(self, **kw):
        base = {
            "energy": {"available": True, "energy": {
                "this": 84.2, "last": 61.0, "change_pct": 38.0, "days": 7,
                "days_before": 7, "comparable": True, "unit": "kWh"}},
            "findings": {"still_open": 2, "open_now": 5, "settled": 3,
                         "confirmed": 2, "wrong": 1,
                         "by_source": [("Battery runway", 2)]},
            "learned": {"available": True, "total": 2, "removed": 0,
                        "added": ["the freezer is in the garage"]},
            "one_thing": finding(-9 * DAY, "serious", text="the boiler",
                                 detail="since Tuesday", fix="check the pump"),
        }
        base.update(kw)
        return weekly.frame(base)

    def test_it_carries_the_numbers_and_names_the_one_thing(self):
        text = self.frame_for()
        self.assertIn("84.2kWh", text)
        self.assertIn("38.0% more", text)
        self.assertIn("Battery runway", text)
        self.assertIn("the freezer is in the garage", text)
        self.assertIn("the boiler", text)
        self.assertIn("check the pump", text)
        self.assertIn("and no other", text)

    def test_a_move_under_the_floor_is_about_the_same_not_a_percentage(self):
        # A meter drifts and a warm week is a warm week. "1.2% more than
        # last week" every week is a line people learn to skip, and the
        # lines beside it go with it.
        text = self.frame_for(energy={"available": True, "energy": {
            "this": 61.7, "last": 61.0, "change_pct": 1.1, "days": 7,
            "days_before": 7, "comparable": True, "unit": "kWh"}})
        self.assertIn("about the same", text)
        self.assertNotIn("1.1%", text)

    def test_an_unavailable_section_tells_the_model_to_leave_it_out(self):
        text = self.frame_for(energy={"available": False,
                                      "reason": "no energy configuration"})
        self.assertIn("Do not mention energy", text)
        self.assertNotIn("kWh", text)

    def test_an_unreadable_memory_log_is_not_reported_as_nothing_learned(self):
        text = self.frame_for(learned={"available": False, "total": 0})
        self.assertIn("could not be read", text)
        self.assertNotIn("Nothing new was filed", text)

    def test_a_short_window_says_so_instead_of_a_comparison(self):
        text = self.frame_for(energy={"available": True, "energy": {
            "this": 40.0, "last": 0.0, "change_pct": None, "days": 4,
            "days_before": 7, "comparable": False, "unit": "kWh"}})
        self.assertIn("4 of 7 days", text)
        self.assertNotIn("% more", text)

    def test_nothing_open_ends_the_report_rather_than_finding_something(self):
        text = self.frame_for(one_thing=None)
        self.assertIn("nothing open to end on", text)


class TestWhenItGoesOut(unittest.TestCase):
    def test_the_day_is_the_gate(self):
        for weekday in range(7):
            got = weekly.due(NOW, weekday, 9 * 60, None, 7, 0.0, 6)
            self.assertEqual(got, weekday == 6, weekday)

    def test_a_mistyped_day_is_the_default_and_never_monday(self):
        # A "week" one day old is the report nobody can act on, and a
        # typo must not quietly produce one.
        self.assertEqual(weekly.day_index("sunday"), 6)
        self.assertEqual(weekly.day_index("SUNDAY "), 6)
        self.assertEqual(weekly.day_index("wednesday"), 2)
        for bad in ("", None, "sundy", "7", "Sonntag"):
            self.assertEqual(weekly.day_index(bad),
                             weekly.DAYS.index(weekly.DEFAULT_DAY), bad)

    def test_the_hour_only_ever_opens_the_window(self):
        # The whole difference from the brief: a report delivered on
        # Sunday afternoon is still that week's, and skipping a week to
        # protect an hour is the wrong trade.
        self.assertFalse(weekly.due(NOW, 6, 6 * 60 + 59, None, 7, 0.0, 6))
        self.assertTrue(weekly.due(NOW, 6, 7 * 60, None, 7, 0.0, 6))
        self.assertTrue(weekly.due(NOW, 6, 16 * 60, None, 7, 0.0, 6))

    def test_the_measured_hour_beats_the_fallback(self):
        # Measured at 09:20; the 07:00 fallback would already have sent.
        self.assertFalse(weekly.due(NOW, 6, 8 * 60, 560.0, 7, 0.0, 6))
        self.assertTrue(weekly.due(NOW, 6, 9 * 60 + 20, 560.0, 7, 0.0, 6))

    def test_once_a_week_and_a_restart_does_not_send_a_second(self):
        self.assertFalse(weekly.due(NOW, 6, 12 * 60, None, 7, NOW - DAY, 6))
        self.assertFalse(weekly.due(NOW, 6, 12 * 60, None, 7,
                                    NOW - weekly.MIN_GAP_S + 60, 6))
        self.assertTrue(weekly.due(NOW, 6, 12 * 60, None, 7,
                                   NOW - weekly.MIN_GAP_S - 60, 6))

    def test_a_week_missed_entirely_waits_for_the_next_day_rather_than_the_hour(self):
        # It is Monday and last week's never went. Nothing is sent until
        # Sunday: a "weekly" report on a Monday is a report about eight
        # days, and the day is what makes the window mean anything.
        self.assertFalse(weekly.due(NOW, 0, 12 * 60, None, 7,
                                    NOW - 9 * DAY, 6))


class TestGather(unittest.TestCase):
    def test_everything_the_prompt_reads_comes_out_of_one_call(self):
        state = weekly.gather(
            [finding(-DAY, "serious")], [settled(-2 * DAY)],
            {"available": False, "reason": "none"}, SINCE,
            memory_path="/nope", now=NOW)
        self.assertEqual(set(state) >= {"energy", "findings", "learned",
                                        "one_thing", "since", "now"}, True)
        self.assertEqual(state["since"], SINCE)
        self.assertFalse(state["learned"]["available"])


class TestThePanelWiring(unittest.TestCase):
    """The module is tested on its own; the wiring is where mistakes live.

    A `due` that is right and a loop that reads the wrong option, or a
    handler that gathers without stamping the week, are both invisible to
    every case above.
    """

    def setUp(self):
        import importlib
        self.server = importlib.import_module("server")
        self.addon_options = importlib.import_module("addon_options")
        self._snapshot = self.addon_options.snapshot
        self._state = dict(self.server.WEEKLY_STATE)
        for key in ("BRAIN_WEEKLY_REPORT", "BRAIN_WEEKLY_REPORT_DAY"):
            os.environ.pop(key, None)

    def tearDown(self):
        self.addon_options.snapshot = self._snapshot
        self.server.WEEKLY_STATE.clear()
        self.server.WEEKLY_STATE.update(self._state)
        for key in ("BRAIN_WEEKLY_REPORT", "BRAIN_WEEKLY_REPORT_DAY"):
            os.environ.pop(key, None)

    def with_options(self, opts):
        self.addon_options.snapshot = lambda: opts

    def test_the_option_is_read_from_the_configuration_tab(self):
        self.with_options({"weekly_report": True,
                           "weekly_report_day": "wednesday"})
        self.assertEqual(self.server._weekly_enabled(), (True, 2))

    def test_the_env_file_is_the_fallback_when_there_is_no_supervisor(self):
        self.with_options({})
        os.environ["BRAIN_WEEKLY_REPORT"] = "true"
        os.environ["BRAIN_WEEKLY_REPORT_DAY"] = "friday"
        self.assertEqual(self.server._weekly_enabled(), (True, 4))

    def test_off_is_the_default_and_a_missing_day_is_sunday(self):
        self.with_options({})
        self.assertEqual(self.server._weekly_enabled(),
                         (False, weekly.DAYS.index(weekly.DEFAULT_DAY)))

    def test_a_false_option_is_not_overridden_by_a_stale_env_export(self):
        # `run.sh` exports both, so the env is always set; an option that
        # was turned OFF must win over the export that turned it on.
        self.with_options({"weekly_report": False})
        os.environ["BRAIN_WEEKLY_REPORT"] = "true"
        self.assertFalse(self.server._weekly_enabled()[0])

    def test_the_diagnostics_say_which_day_and_when_it_last_went(self):
        self.with_options({"weekly_report": True,
                           "weekly_report_day": "monday"})
        self.server.WEEKLY_STATE["last_sent"] = NOW
        self.server.WEEKLY_STATE["last_text"] = "a report"
        got = self.server._weekly_diagnostics()
        self.assertTrue(got["enabled"])
        self.assertEqual(got["day"], "monday")
        self.assertEqual(got["last_sent"], int(NOW))
        # The text is not repeated into the bundle; its length is enough
        # to tell "sent something" from "sent nothing".
        self.assertEqual(got["last_chars"], len("a report"))
        self.assertNotIn("a report", json.dumps(got))

    def test_a_hand_run_that_found_nothing_does_not_consume_the_week(self):
        # Asking on a Saturday and finding the week empty must not
        # silently cancel the Sunday report, which would have had
        # another day's material.
        import asyncio as aio
        self.with_options({"findings_notify_service": "notify.notify"})
        self.server.WEEKLY_STATE["last_sent"] = 0.0
        sent = []

        async def nothing(now):
            sent.append(now)
            return ""

        old = self.server._send_weekly
        self.server._send_weekly = nothing
        try:
            aio.run(self.server.h_weekly_run(None))
        finally:
            self.server._send_weekly = old
        self.assertEqual(len(sent), 1)
        self.assertEqual(self.server.WEEKLY_STATE["last_sent"], 0.0)

    def test_a_hand_run_that_sent_something_does_consume_the_week(self):
        import asyncio as aio
        self.with_options({"findings_notify_service": "notify.notify"})
        self.server.WEEKLY_STATE["last_sent"] = 0.0

        async def something(now):
            return "a report"

        old = self.server._send_weekly
        self.server._send_weekly = something
        try:
            aio.run(self.server.h_weekly_run(None))
        finally:
            self.server._send_weekly = old
        # Two reports about overlapping weeks make the numbers in both
        # meaningless, so the schedule moves with the hand-run.
        self.assertGreater(self.server.WEEKLY_STATE["last_sent"], 0.0)

    def test_a_hand_run_with_no_notify_service_refuses_rather_than_stamping(self):
        import asyncio as aio
        self.with_options({})
        os.environ.pop("BRAIN_FINDINGS_NOTIFY", None)
        self.server.WEEKLY_STATE["last_sent"] = 0.0
        resp = aio.run(self.server.h_weekly_run(None))
        self.assertEqual(resp.status, 409)
        self.assertEqual(self.server.WEEKLY_STATE["last_sent"], 0.0)

    def test_the_bundle_keeps_the_counts_and_never_the_memory_lines(self):
        # `last_state` rides into /api/diagnostics and so into the bundle
        # `brain report` attaches to an issue. A memory line is a fact
        # about somebody's home, not a diagnostic.
        import asyncio as aio
        self.with_options({})
        self.server.WEEKLY_STATE["last_sent"] = 0.0

        async def state(now):
            return {"energy": {"available": False}, "findings": {"settled": 1},
                    "learned": {"available": True, "total": 2,
                                "added": ["the freezer is in the garage"]},
                    "one_thing": finding(-DAY), "since": SINCE, "now": now}

        engine = __import__("engine")
        old = self.server._weekly_state
        old_run, old_notify = engine.run_analyst, self.server._send_notification

        async def swallow(rows):
            return None

        engine.run_analyst = lambda *a, **k: {"ok": True, "text": "x" * 80}
        self.server._send_notification = swallow
        self.server._weekly_state = state
        try:
            aio.run(self.server._send_weekly(NOW))
        finally:
            self.server._weekly_state = old
            engine.run_analyst = old_run
            self.server._send_notification = old_notify
        bundle = json.dumps(self.server.WEEKLY_STATE["last_state"])
        self.assertIn("\"total\": 2", bundle)
        self.assertNotIn("freezer", bundle)
        self.assertNotIn("one_thing", bundle)

    def test_the_window_is_a_week_however_long_the_gap(self):
        # An add-on that was off for a fortnight must not send a report
        # headed "this week" about three of them. A finding still open
        # from before it is already in `open_now` and in the one thing.
        import asyncio as aio
        self.with_options({})
        self.server.WEEKLY_STATE["last_sent"] = NOW - 40 * DAY
        seen = {}

        async def meters(now):
            return {"available": False, "reason": "none"}

        old = self.server._weekly_energy
        old_gather = weekly.gather
        self.server._weekly_energy = meters

        def spy(rows, settled, power, since, **kw):
            seen["since"] = since
            return old_gather(rows, settled, power, since, **kw)

        weekly.gather = spy
        try:
            aio.run(self.server._weekly_state(NOW))
        finally:
            self.server._weekly_energy = old
            weekly.gather = old_gather
        self.assertAlmostEqual(seen["since"], NOW - weekly.WEEK_S, places=1)

    def test_the_routes_are_mounted(self):
        paths = set()
        app = self.server.make_app()
        for route in app.router.routes():
            info = route.resource.get_info() if route.resource else {}
            paths.add((route.method, info.get("path")))
        self.assertIn(("GET", "/api/weekly"), paths)
        self.assertIn(("POST", "/api/weekly/run"), paths)



class TestARestartIsNotANewWeek(unittest.TestCase):
    """The stamp that says "already sent" has to survive the process.

    It lived in memory only, so a restart set it back to zero and the
    next window sent a second report about the same week — and restarting
    is the first thing anybody does after changing an option, which makes
    that the ordinary case rather than the unlucky one.
    """

    def setUp(self):
        import importlib
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "schedule.json")
        self.store = importlib.import_module("schedule_store")

    def test_a_stamp_read_back_is_the_stamp_written(self):
        self.store.set("weekly_last_sent", NOW, self.path)
        self.assertEqual(self.store.get("weekly_last_sent", self.path), NOW)

    def test_two_keys_share_one_file_without_erasing_each_other(self):
        self.store.set("brief_last_sent", NOW, self.path)
        self.store.set("weekly_last_sent", NOW - DAY, self.path)
        self.assertEqual(self.store.get("brief_last_sent", self.path), NOW)
        self.assertEqual(self.store.get("weekly_last_sent", self.path),
                         NOW - DAY)

    def test_every_failure_reads_as_never_sent(self):
        # The safe direction: a lost stamp costs one duplicate message,
        # where a stamp read as "sent" would silence a real report.
        self.assertEqual(self.store.get("weekly_last_sent", self.path), 0.0)
        for junk in ('{"weekly_last_sent": "soon"}', '{"weekly_last_sent": true}',
                     "[1, 2]", "not json at all", ""):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            self.assertEqual(
                self.store.get("weekly_last_sent", self.path), 0.0, junk)

    def test_a_missing_directory_is_not_a_crash(self):
        # A dev checkout has no /data, and a stamp that could not be
        # written must not fail the message it was recording.
        gone = os.path.join(self.dir.name, "nope", "schedule.json")
        self.store.set("weekly_last_sent", NOW, gone)
        self.assertEqual(self.store.get("weekly_last_sent", gone), 0.0)

    def test_a_restarted_panel_starts_from_the_stamp_on_disk(self):
        import importlib
        self.store.set("weekly_last_sent", NOW, self.path)
        self.store.set("brief_last_sent", NOW - 3600, self.path)
        old = os.environ.get("BRAIN_SCHEDULE_FILE")
        os.environ["BRAIN_SCHEDULE_FILE"] = self.path
        try:
            importlib.reload(self.store)
            server = importlib.reload(importlib.import_module("server"))
            self.assertEqual(server.WEEKLY_STATE["last_sent"], NOW)
            self.assertEqual(server.BRIEF_STATE["last_sent"], NOW - 3600)
            # And that is enough to refuse a second report the same week,
            # which is the whole point of persisting it.
            self.assertFalse(weekly.due(NOW + 3600, 6, 12 * 60, None, 7,
                                        server.WEEKLY_STATE["last_sent"], 6))
        finally:
            if old is None:
                os.environ.pop("BRAIN_SCHEDULE_FILE", None)
            else:
                os.environ["BRAIN_SCHEDULE_FILE"] = old
            importlib.reload(self.store)
            importlib.reload(importlib.import_module("server"))


if __name__ == "__main__":
    unittest.main()
