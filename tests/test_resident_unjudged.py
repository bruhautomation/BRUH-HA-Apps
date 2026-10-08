#!/usr/bin/env python3
"""Why rows a rule filed ended up on the list as if nothing had looked.

Reported from a real house: twelve of fourteen open findings carried
`triage.UNJUDGED` — "Nothing finished looking at this one" — including rows
from the rules the scorecard says are most often wrong. "Silence surfaces"
is right and is kept: a row nothing could look at is still shown. What was
wrong is that the silence was PERMANENT, and that it was reached in steady
state rather than only when a look genuinely could not run.

Four causes, each reproduced against the real loop before it is asserted:

  * a verdict that arrived after the stale sweep had shown a row was
    dropped (`record_triage` touched `triaging` rows only), so the card
    said nothing had looked for the rest of its life even though a look
    had answered about it;
  * a look that failed showed its filed rows under `RUN_FAILED` and never
    offered them again, so the next look — minutes later — could not
    correct the marker;
  * a batch was filled hot-first, so a busy house's hot state changes
    (every change to a protected entity is hot) took every slot and a
    filed row waited past the hour;
  * hot signals cut the interval to a minute and so could spend the
    day's whole look allowance by mid-morning, leaving every row filed
    after it to the stale sweep.
"""

import asyncio
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase, reply  # noqa: E402


class TestALateLookCorrectsWhatSilenceShowed(LoopCase):

    def test_a_verdict_after_the_stale_sweep_reaches_the_row(self):
        import engine
        srv = self.server
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        later = now + srv.triage.STALE_S + 60
        self.tick(later)
        shown = srv.findings_store.get(row["ts"])
        self.assertEqual(shown["triage"]["reason"], srv.triage.UNJUDGED)
        # The gate lifts and the look answers about this very row.
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{
            "id": 1, "verdict": "ignore",
            "why": "its history shows it moved twice last month"}]))
        out = self.tick(later + srv.RESIDENT_LOOK_S + 1)
        self.assertTrue(out["looked"], out)
        fresh = srv.findings_store.get(row["ts"])
        # The verdict is recorded, and the row stays where it is: a row
        # already on screen never vanishes into a run.
        self.assertEqual(fresh["status"], "open")
        self.assertEqual(fresh["triage"]["verdict"], "held")
        self.assertIn("moved twice", fresh["triage"]["reason"])

    def test_an_elevating_verdict_replaces_the_unjudged_sentence(self):
        import engine
        srv = self.server
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        later = now + srv.triage.STALE_S + 60
        self.tick(later)
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{"id": 1, "verdict": "watch",
                                  "why": "one reading is not enough"}]))
        self.tick(later + srv.RESIDENT_LOOK_S + 1)
        fresh = srv.findings_store.get(row["ts"])
        self.assertEqual(fresh["status"], "open")
        self.assertEqual(fresh["triage"]["verdict"], "elevated")
        self.assertIn("one reading", fresh["triage"]["reason"])

    def test_a_row_a_person_put_back_is_never_taken_off_again(self):
        srv = self.server
        row = self.file_check_row()
        srv.findings_store.record_triage(
            {row["ts"]: ("held", "a cupboard")}, "look-0")
        srv.findings_store.elevate(row["ts"])
        moved = srv.findings_store.record_triage(
            {row["ts"]: ("held", "still a cupboard")}, "look-1")
        self.assertEqual(moved, [])
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")

    def test_an_unjudged_row_is_offered_again_after_a_restart(self):
        srv = self.server
        now = time.time()
        row = self.file_check_row()
        srv.findings_store.record_triage(
            {row["ts"]: ("untriaged", srv.triage.UNJUDGED)}, "", now)
        srv.RESIDENT_PENDING.clear()
        srv.RESIDENT_STATE["last_look_at"] = now   # not due: count it
        asyncio.run(srv._resident_pass(now))
        self.assertIn(row["ts"], [s.get("finding_ts")
                                  for s in srv.RESIDENT_PENDING])


class TestAFailedLookIsNotTheLastWord(LoopCase):

    def test_the_next_look_judges_what_a_failed_one_showed(self):
        srv = self.server
        now = time.time()
        row = self.file_check_row()
        out = self.tick(now)      # no reply queued: the run fails
        self.assertFalse(out.get("ok", True))
        self.assertEqual(srv.findings_store.get(row["ts"])["triage"]["reason"],
                         srv.triage.RUN_FAILED)
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "it is a cupboard nobody opens"}]))
        out = self.tick(now + srv.RESIDENT_LOOK_S + 1)
        self.assertTrue(out["looked"], out)
        fresh = srv.findings_store.get(row["ts"])
        self.assertEqual(fresh["status"], "open")
        self.assertEqual(fresh["triage"]["verdict"], "held")
        self.assertIn("cupboard", fresh["triage"]["reason"])


class TestARowIsAnnouncedOnce(LoopCase):
    """A row a late verdict reaches is already open and already announced;
    handing it to the notifier again rang the phone on every look."""

    def announced_ts(self, ts):
        return [r["ts"] for r in self.announced].count(ts)

    def test_a_row_that_keeps_failing_is_announced_once(self):
        srv = self.server
        now = time.time()
        row = self.file_check_row()
        for i in range(3):          # no reply queued: every look fails
            self.tick(now + i * (srv.RESIDENT_LOOK_S + 1))
        self.assertEqual(len(self.look_calls), 3)
        self.assertEqual(self.announced_ts(row["ts"]), 1)

    def test_a_late_verdict_does_not_announce_the_row_again(self):
        import engine
        srv = self.server
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        later = now + srv.triage.STALE_S + 60
        self.tick(later)
        self.assertEqual(self.announced_ts(row["ts"]), 1)
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "worth a look at its history"}]))
        self.tick(later + srv.RESIDENT_LOOK_S + 1)
        self.assertEqual(self.announced_ts(row["ts"]), 1)
        self.assertEqual(srv.findings_store.get(row["ts"])["triage"]["verdict"],
                         "elevated")

    def test_an_untriaged_verdict_on_an_untriaged_row_is_no_change(self):
        srv = self.server
        row = self.file_check_row()
        srv.findings_store.record_triage(
            {row["ts"]: ("untriaged", srv.triage.UNJUDGED)}, "", 1.0)
        again = srv.findings_store.record_triage(
            {row["ts"]: ("untriaged", srv.triage.RUN_FAILED)}, "", 2.0)
        self.assertEqual(again, [])
        self.assertEqual(srv.findings_store.get(row["ts"])["triage"]["reason"],
                         srv.triage.UNJUDGED)

    def test_a_late_verdict_is_written_but_not_returned_as_moved(self):
        srv = self.server
        row = self.file_check_row()
        srv.findings_store.record_triage(
            {row["ts"]: ("untriaged", srv.triage.UNJUDGED)}, "", 1.0)
        moved = srv.findings_store.record_triage(
            {row["ts"]: ("held", "a cupboard")}, "look-2", 2.0)
        self.assertEqual(moved, [])
        fresh = srv.findings_store.get(row["ts"])
        self.assertEqual((fresh["status"], fresh["triage"]["verdict"]),
                         ("open", "held"))


class TestFiledRowsAreNotStarved(LoopCase):

    def test_hot_state_changes_cannot_take_every_slot(self):
        srv = self.server
        now = time.time()
        for i in range(srv.resident.MAX_BATCH + 10):
            srv._resident_offer(srv.signals.make(
                "state", f"lock.door_{i}", now=now, hot=True,
                source="eventbus", text=f"Door {i} locked → unlocked",
                salience=0.6, protected=True))
        self.file_check_row()
        self.looks.append(reply([]))
        self.tick(now)
        [call] = self.look_calls
        self.assertIn("pantry contact", call["prompt"])

    def test_a_tripped_safety_sensor_still_goes_first(self):
        srv = self.server
        now = time.time()
        rows = [srv.signals.make(
            "state", f"lock.door_{i}", now=now, hot=True, source="eventbus",
            text=f"d{i}", salience=0.6) for i in range(40)]
        rows.append(srv.signals.make(
            "state", "binary_sensor.leak", now=now, hot=True, safety=True,
            source="eventbus", text="leak", salience=0.05))
        filed = [{**srv.signals.make("check", f"sensor.s{i}", now=now,
                                     text=f"s{i}", salience=0.1),
                  "finding_ts": 1000 + i} for i in range(40)]
        got = srv.signals.batch(rows + filed, 30, filed_reserve=15)
        self.assertEqual(got["batch"][0]["subject"], "binary_sensor.leak")
        self.assertEqual(sum(1 for s in got["batch"] if s.get("finding_ts")),
                         15)

    def test_the_queue_cap_never_drops_a_filed_row(self):
        srv = self.server
        now = time.time()
        old = srv.RESIDENT_QUEUE_MAX
        srv.RESIDENT_QUEUE_MAX = 3
        try:
            row = self.file_check_row(severity="info")
            srv._offer_findings([row], now)
            for i in range(6):
                srv._resident_offer(srv.signals.make(
                    "state", f"sensor.s{i}", now=now, source="eventbus",
                    text=f"s{i}", salience=0.9))
            srv._resident_absorb(now)
            self.assertIn(row["ts"], [s.get("finding_ts")
                                      for s in srv.RESIDENT_PENDING])
        finally:
            srv.RESIDENT_QUEUE_MAX = old


class TestHotSignalsLeaveLooksForTheRest(LoopCase):

    def test_past_the_hot_share_a_hot_signal_waits_for_the_timer(self):
        srv = self.server
        now = time.time()
        srv.TRIAGE_STATE.update({
            "day": time.strftime("%Y-%m-%d", time.localtime(now)),
            "runs": srv.triage.HOT_LOOKS_PER_DAY})
        srv.RESIDENT_STATE["last_look_at"] = now - 90
        srv._resident_offer(srv.signals.make(
            "state", "lock.front", now=now, hot=True, source="eventbus",
            text="Front door locked → unlocked", salience=0.6,
            protected=True))
        out = self.tick(now)
        self.assertFalse(out["looked"], out)
        self.assertEqual(self.look_calls, [])

    def test_a_tripped_safety_sensor_is_not_held_by_the_share(self):
        srv = self.server
        now = time.time()
        srv.TRIAGE_STATE.update({
            "day": time.strftime("%Y-%m-%d", time.localtime(now)),
            "runs": srv.triage.HOT_LOOKS_PER_DAY})
        srv.RESIDENT_STATE["last_look_at"] = now - 90
        srv._resident_offer(srv.signals.make(
            "state", "binary_sensor.leak", now=now, hot=True, safety=True,
            source="eventbus", text="Kitchen leak off → on", salience=0.9))
        self.looks.append(reply([{"id": 1, "verdict": "watch",
                                  "why": "waiting for a second reading"}]))
        self.assertTrue(self.tick(now)["looked"])

    def test_the_share_leaves_room_under_the_cap(self):
        srv = self.server
        self.assertLess(srv.triage.HOT_LOOKS_PER_DAY, srv.triage.MAX_PER_DAY)


if __name__ == "__main__":
    unittest.main()
