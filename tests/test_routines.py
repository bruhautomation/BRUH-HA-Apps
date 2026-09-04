"""The habit miner, and the five floors that keep it quiet on a house with no habit.

Every rule here is asserted against the case it must NOT fire on before
it is asserted against the one it must find — the same discipline
`tests/test_house_checks.py` applies to every check, and for the same
reason: a proposal that arrives on a house where nothing is habitual is
how the whole tab gets closed, and it costs nothing to be wrong in the
other direction.

The one that took driving rather than reading is the denominator. Four
presses at about six o'clock is a habit if they were the last four
weekdays and a coincidence if they were spread over two months, and a
miner that counted events would report both identically — which is
exactly the finding `auto.overridden` shipped as.
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

import routines  # noqa: E402

UTC = dt.timezone.utc
# A Monday, so a "weekday" fixture can be written by counting forward.
MONDAY = dt.datetime(2026, 3, 2, 0, 0, tzinfo=UTC)


def when(day_offset: int, hour: int, minute: int = 0) -> float:
    return (MONDAY + dt.timedelta(days=day_offset,
                                  hours=hour, minutes=minute)).timestamp()


def press(day_offset: int, hour: int, minute: int = 0,
          entity_id: str = "light.hall", state: str = "on") -> dict:
    return {"ts": int(when(day_offset, hour, minute)),
            "entity_id": entity_id, "state": state, "name": "Hall lamp"}


def weekdays(n: int, hour: int = 18, minute: int = 40, jitter=None,
             **kw) -> list[dict]:
    """`n` consecutive weekday presses, skipping Saturdays and Sundays."""
    out, day = [], 0
    jitter = list(jitter or [])
    while len(out) < n:
        if (MONDAY + dt.timedelta(days=day)).weekday() < 5:
            off = jitter[len(out) % len(jitter)] if jitter else 0
            out.append(press(day, hour, minute + off, **kw))
        day += 1
    return out


def ledger(rows, automated=None) -> dict:
    return {"rows": rows, "automated": automated or {}}


def after(rows) -> float:
    """A moment just after the last press, so nothing is stale."""
    return max(r["ts"] for r in rows) + 3600


class TestItFindsAHabit(unittest.TestCase):
    def test_the_plain_case(self):
        rows = weekdays(10)
        found = routines.mine(ledger(rows), UTC, after(rows))
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual(row["entity_id"], "light.hall")
        self.assertEqual(row["state"], "on")
        self.assertEqual(row["when_days"], "weekdays")
        self.assertEqual(row["at"], "18:40")
        self.assertEqual(row["days"], 10)

    def test_a_few_minutes_either_side_is_still_one_time(self):
        rows = weekdays(10, jitter=[-6, 0, 5, -3, 2])
        found = routines.mine(ledger(rows), UTC, after(rows))
        self.assertEqual(len(found), 1)
        self.assertLess(found[0]["spread_min"], routines.MAX_SPREAD_MIN)

    def test_the_evidence_is_the_numbers(self):
        rows = weekdays(10)
        row = routines.mine(ledger(rows), UTC, after(rows))[0]
        why = routines.why_for(row)
        self.assertIn("10 of the last", why)
        self.assertIn("weekday days", why)
        self.assertIn("18:40", why)


class TestTheFloorsThatKeepItQuiet(unittest.TestCase):
    def test_too_few_days_says_nothing(self):
        rows = weekdays(routines.MIN_DAYS - 1)
        self.assertEqual(routines.mine(ledger(rows), UTC, after(rows)), [])

    def test_many_presses_on_one_day_is_one_day(self):
        # Twelve presses, all on the Monday. A miner counting events
        # would call this the strongest habit in the house.
        rows = [press(0, 18, m) for m in range(0, 12)]
        self.assertEqual(routines.mine(ledger(rows), UTC, after(rows)), [])

    def test_scattered_times_are_not_a_time(self):
        # Ten weekdays, but anywhere between four and nine in the evening.
        rows = weekdays(10, hour=16, jitter=[0, 60, 120, 180, 240])
        self.assertEqual(routines.mine(ledger(rows), UTC, after(rows)), [])

    def test_the_same_count_over_a_longer_window_is_a_coincidence(self):
        # THE denominator test. Eight presses at 18:40 either way — the
        # first eight on consecutive weekdays, the second eight one a
        # week apart. Same events, same time, same spread; only the days
        # they could have happened on differ, and a miner without a
        # denominator cannot tell them apart.
        tight = weekdays(8)
        self.assertEqual(len(routines.mine(ledger(tight), UTC,
                                           after(tight))), 1)
        spread = [press(i * 7, 18, 40) for i in range(8)]
        self.assertEqual(routines.mine(ledger(spread), UTC, after(spread)), [])

    def test_a_habit_that_stopped_is_not_a_habit(self):
        rows = weekdays(10)
        stale = max(r["ts"] for r in rows) + (routines.RECENT_DAYS + 1) * 86400
        self.assertEqual(routines.mine(ledger(rows), UTC, stale), [])

    def test_something_already_doing_it_stands_it_down(self):
        rows = weekdays(10)
        now = after(rows)
        key = "light.hall|on"
        self.assertEqual(len(routines.mine(ledger(rows), UTC, now)), 1)
        self.assertEqual(
            routines.mine(ledger(rows, {key: now - 3600}), UTC, now), [])

    def test_an_automation_that_stopped_months_ago_does_not(self):
        # The tally is "does something already do this", not "did it
        # ever": a rule somebody deleted must not suppress the habit
        # that replaced it for ever.
        rows = weekdays(10)
        now = after(rows)
        old = now - (routines.RECENT_DAYS + 5) * 86400
        self.assertEqual(
            len(routines.mine(ledger(rows, {"light.hall|on": old}), UTC, now)),
            1)

    def test_a_pass_offers_a_handful_at_most(self):
        rows = []
        for i in range(routines.MAX_ROUTINES + 3):
            rows += weekdays(10, entity_id=f"light.room{i}")
        found = routines.mine(ledger(rows), UTC, after(rows))
        self.assertEqual(len(found), routines.MAX_ROUTINES)

    def test_the_cap_takes_the_same_ones_every_time(self):
        # Sorted before capping. An arbitrary set that changed every
        # pass would offer, withdraw and re-offer the same habits.
        rows = []
        for i in range(routines.MAX_ROUTINES + 3):
            rows += weekdays(10 + i, entity_id=f"light.room{i}")
        first = routines.mine(ledger(rows), UTC, after(rows))
        again = routines.mine(ledger(list(reversed(rows))), UTC, after(rows))
        self.assertEqual([r["entity_id"] for r in first],
                         [r["entity_id"] for r in again])


class TestWhichDaysItClaims(unittest.TestCase):
    def test_weekdays_only(self):
        rows = weekdays(10)
        self.assertEqual(
            routines.mine(ledger(rows), UTC, after(rows))[0]["when_days"],
            "weekdays")

    def test_every_day_needs_both_halves_of_the_week(self):
        # Three weeks, because six weekend days is what MIN_DAYS asks of
        # the weekend half on its own.
        rows = [press(d, 18, 40) for d in range(21)]
        row = routines.mine(ledger(rows), UTC, after(rows))[0]
        self.assertEqual(row["when_days"], "every day")

    def test_a_daily_habit_reads_as_weekdays_until_the_weekends_accrue(self):
        # The documented cost of measuring the halves apart, asserted
        # rather than described: it is the cheaper mistake, because a
        # routine that misses two days a week is a smaller wrong than
        # one that fires on two mornings somebody is asleep.
        rows = [press(d, 18, 40) for d in range(12)]
        row = routines.mine(ledger(rows), UTC, after(rows))[0]
        self.assertEqual(row["when_days"], "weekdays")

    def test_a_weekday_habit_is_graded_against_weekdays(self):
        # Ten consecutive weekdays is fourteen calendar days. Graded
        # against all fourteen the share is 0.71 and this would be
        # refused; graded against the ten weekdays in them it is 1.0.
        rows = weekdays(10)
        row = routines.mine(ledger(rows), UTC, after(rows))[0]
        self.assertEqual(row["eligible_days"], 10)
        self.assertEqual(row["share"], 1.0)

    def test_one_stray_sunday_does_not_drag_the_time(self):
        # A weekday habit at 18:40 with a single 09:00 Sunday. Averaged
        # over everything the trigger lands an hour and a half early;
        # measured over the days the shape claims, it does not move.
        rows = weekdays(10) + [press(6, 9, 0)]
        row = routines.mine(ledger(rows), UTC, after(rows))[0]
        self.assertEqual(row["when_days"], "weekdays")
        self.assertEqual(row["at"], "18:40")


class TestTheAutomationItWouldWrite(unittest.TestCase):
    def setUp(self):
        rows = weekdays(10)
        self.routine = routines.mine(ledger(rows), UTC, after(rows))[0]

    def test_it_is_a_time_trigger_and_a_weekday_condition(self):
        config = routines.to_config(self.routine)
        self.assertEqual(config["trigger"],
                         [{"platform": "time", "at": "18:40:00"}])
        self.assertEqual(config["condition"],
                         [{"condition": "time", "weekday": routines.WEEKDAYS}])
        self.assertEqual(config["action"],
                         [{"service": "light.turn_on",
                           "target": {"entity_id": "light.hall"}}])

    def test_the_config_carries_no_prose(self):
        # `proposals.key_for` hashes the config, so a title in it would
        # re-offer a declined proposal the day somebody renames the lamp.
        config = routines.to_config(self.routine)
        self.assertNotIn("alias", config)
        self.assertNotIn("Hall lamp", json.dumps(config))

    def test_a_minute_of_drift_does_not_re_offer(self):
        import proposals  # noqa: PLC0415 — the store, only for its key

        drifted = dict(self.routine, minute=self.routine["minute"] + 1,
                       at="18:41")
        self.assertEqual(
            proposals.key_for(routines.as_proposal(self.routine)),
            proposals.key_for(routines.as_proposal(drifted)))

    def test_an_action_it_cannot_name_is_not_proposed(self):
        # A climate entity's state is its hvac mode and there is no
        # honest service to derive from it. A proposal whose automation
        # would not run is worse than no proposal.
        odd = dict(self.routine, entity_id="climate.hall", state="heat")
        self.assertIsNone(routines.service_for("climate.hall", "heat"))
        self.assertIsNone(routines.to_config(odd))
        self.assertIsNone(routines.as_proposal(odd))

    def test_the_title_says_what_it_would_do(self):
        title = routines.title_for(self.routine)
        self.assertIn("Hall lamp", title)
        self.assertIn("18:40", title)
        self.assertIn("weekdays", title)


class TestTheLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "routines.json")
        self.addCleanup(self.dir.cleanup)

    def action(self, ts, cause="person", entity_id="light.hall", state="on"):
        return {"ts": int(ts), "entity_id": entity_id, "state": state,
                "name": "Hall lamp", "cause": cause}

    def test_only_a_person_becomes_a_row(self):
        now = when(1, 12)
        routines.record([
            self.action(when(0, 18)),
            self.action(when(0, 19), cause="automation"),
            self.action(when(0, 20), cause="unattributed"),
            self.action(when(0, 21), cause="voice"),
        ], now, self.path)
        payload = routines.load(self.path)
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["ts"], int(when(0, 18)))

    def test_an_automated_move_is_a_timestamp_not_a_row(self):
        now = when(1, 12)
        routines.record([self.action(when(0, 19), cause="automation")],
                        now, self.path)
        payload = routines.load(self.path)
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["automated"]["light.hall|on"],
                         int(when(0, 19)))

    def test_overlapping_passes_file_one_press_once(self):
        # The checks pass runs every six hours over a day-long window, so
        # the same press arrives four or five times. A ledger that
        # appended what it was given would report one habit as five.
        now = when(1, 12)
        rows = [self.action(when(0, 18))]
        self.assertEqual(routines.record(rows, now, self.path), 1)
        self.assertEqual(routines.record(rows, now, self.path), 0)
        self.assertEqual(len(routines.load(self.path)["rows"]), 1)

    def test_a_domain_a_time_trigger_cannot_act_on_is_not_kept(self):
        now = when(1, 12)
        routines.record([self.action(when(0, 18), entity_id="sensor.temp",
                                     state="19.5")], now, self.path)
        self.assertEqual(routines.load(self.path)["rows"], [])

    def test_a_reading_that_is_not_there_is_not_a_habit(self):
        now = when(1, 12)
        routines.record([self.action(when(0, 18), state="unavailable"),
                         self.action(when(0, 19), state="unknown")],
                        now, self.path)
        self.assertEqual(routines.load(self.path)["rows"], [])

    def test_old_rows_and_old_tallies_both_go(self):
        old = when(0, 18)
        now = old + (routines.KEEP_DAYS + 2) * 86400
        routines.record([self.action(old),
                         self.action(old + 60, cause="automation",
                                     entity_id="light.other")],
                        old + 3600, self.path)
        routines.record([], now, self.path)
        payload = routines.load(self.path)
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["automated"], {})

    def test_every_way_of_failing_reads_as_no_evidence(self):
        for junk in ("", "not json", "[]", '{"rows": "nope"}'):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write(junk)
            payload = routines.load(self.path)
            self.assertEqual(payload["rows"], [], junk)
            self.assertEqual(payload["automated"], {}, junk)
        os.unlink(self.path)
        self.assertEqual(routines.load(self.path)["rows"], [])

    def test_a_ledger_it_cannot_write_does_not_fail_the_pass(self):
        missing = os.path.join(self.dir.name, "nope", "routines.json")
        routines.record([self.action(when(0, 18))], when(1, 12), missing)
        self.assertFalse(os.path.exists(missing))


if __name__ == "__main__":
    unittest.main()


class TestTwoCleanHalvesAtDifferentHours(unittest.TestCase):
    def test_both_halves_holding_up_is_never_no_habit(self):
        # 07:00 every weekday and 10:00 every weekend day: each half is a
        # clean shape on its own, and the merged set has a three-hour
        # spread `every day` refuses. `_best_shape` used to return that
        # refusal, so a habit with the best evidence in the ledger was the
        # one that was dropped. The fallback is the narrower true claim.
        rows = [press(d, 7 if (MONDAY + dt.timedelta(days=d)).weekday() < 5
                      else 10, 0)
                for d in range(21)]
        found = routines.mine(ledger(rows), UTC, after(rows))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["when_days"], "weekdays")
