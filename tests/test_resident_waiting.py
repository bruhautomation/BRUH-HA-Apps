#!/usr/bin/env python3
"""Why findings still waited for a look for days on a house where looks ran.

The fault report kept saying "N findings are still waiting for a look",
oldest hundreds of hours, on a day the first look ran ~140 times without a
failure. The two earlier fixes (when the wait is measured from, and offering
a row a failed look showed) were right and did not reach it, because the
rows that waited were never in a batch at all. Driven here against the real
loop with only the CLI stubbed:

  * **The pending list's cap dropped FILED rows to keep live duplicates.**
    Every state change of a protected entity is a hot signal, and the
    pending list holds each raw one until a look folds them by subject. A
    chatty protected entity — one change a second — puts several hundred
    copies of one signal on the list between two looks once the hot looks
    for the day are spent (they are then ten minutes apart), and past
    `RESIDENT_QUEUE_MAX` the cap took the least salient NON-hot signal: the
    rows a rule filed. Each minute the sweep offered them again and the
    same tick's cap dropped them again, so the oldest, least salient rows
    never reached a look while every fresh one (higher salience) did.

  * **The batch reserve was filled by salience, newest first.** A row
    already past `triage.SHOW_AFTER_S` lost to every fresher row the same
    way on every look — "nothing loses the same lottery twice" was true of
    `awaiting_triage`'s order and undone by the re-rank.

  * **A row the look had judged and sent to be investigated still counted
    as waiting for a look** for as long as the investigation ran.
"""

import asyncio
import json
import re
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase  # noqa: E402


def answer_every_row(verdict: str):
    """A first look that answers every numbered row with ``verdict``."""
    def run_claude(prompt, system, *a, **k):
        ids = [int(m) for m in re.findall(r"^(\d+)\. ", prompt, re.M)]
        return {"ok": True, "error": "",
                "text": json.dumps({"verdicts": [
                    {"id": i, "verdict": verdict, "why": "looked"}
                    for i in ids]}),
                "meta": {"session_id": "look"}}
    return run_claude


class Waiting(LoopCase):
    """LoopCase with the decision trail in this test's own directory."""

    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))


class Day(Waiting):
    """A stretch of a busy day, minute by minute, on the real loop."""

    STEP = 60

    def setUp(self):
        super().setUp()
        import engine
        srv = self.server
        engine.run_claude = answer_every_row("watch")
        # Investigations are parked all day (the ledger's allowance spent):
        # the looked-into rows are shown with the look's reason.
        first = srv._resident_tier(srv.resident.JOB_FIRST_LOOK, "balanced")
        ledger = srv.LEDGER
        real = ledger.allows

        def allows(tier, *a, **k):
            return real(tier, *a, **k) if tier == first else (
                False, "today's allowance is spent")
        ledger.allows = allows

    def spend_hot_looks(self, now: float) -> None:
        """The day's hot pull-forwards are gone: looks are on the timer."""
        srv = self.server
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        if srv.TRIAGE_STATE.get("day") != day:
            srv.TRIAGE_STATE.update({"day": day, "runs": 0})
        srv.TRIAGE_STATE["runs"] = max(int(srv.TRIAGE_STATE.get("runs") or 0),
                                       srv.triage.HOT_LOOKS_PER_DAY)

    def file(self, text: str, severity: str, entity: str) -> dict:
        srv = self.server
        [row] = srv.findings_store.add_many(srv.triage.gate([{
            "text": text, "detail": "since Tuesday", "severity": severity,
            "entity_id": entity, "source": "check:dev.frozen",
            "source_title": "Sensors frozen"}]))
        return row

    def waited_for_look(self, ts: int) -> bool:
        srv = self.server
        rows = srv.findings_store.list_all()
        return ts in {f["ts"] for f in srv._waiting_rows(rows)}


class TestAChattyProtectedEntityCannotPushFiledRowsOut(Day):

    def test_an_old_row_is_looked_at_through_a_flood_of_one_entity(self):
        srv = self.server
        start = time.time()
        old = None
        hours = 3
        for step in range(0, hours * 3600, self.STEP):
            now = start + step
            if step == 300:
                # Filed once the flood is under way, as a checks pass would.
                old = self.file(
                    "The cellar contact has not changed in nine days",
                    "info", "binary_sensor.cellar")
            self.spend_hot_looks(now)
            # One protected entity reporting a new value every second.
            for i in range(self.STEP):
                srv._resident_offer(srv.signals.make(
                    "state", "lock.front_door", now=now + i, hot=True,
                    source="eventbus", protected=True, salience=0.5,
                    text=f"Front door battery {step + i}"))
            # A checks pass every hour files something fresh.
            if step % 3600 == 0:
                self.file(f"The hall sensor has been unavailable ({step})",
                          "warning", f"sensor.hall_{step}")
            asyncio.run(srv._resident_tick(now))
        self.assertFalse(
            self.waited_for_look(old["ts"]),
            "a row a rule filed was still waiting for a look after "
            f"{hours} h of looks every ten minutes")
        fresh = srv.findings_store.get(old["ts"])
        self.assertNotEqual(fresh["triage"].get("verdict"), "untriaged")

    def test_the_cap_drops_a_live_copy_before_a_filed_row(self):
        srv = self.server
        now = time.time()
        old = srv.RESIDENT_QUEUE_MAX
        srv.RESIDENT_QUEUE_MAX = 5
        try:
            row = self.file("The cellar contact has not changed in nine days",
                            "info", "binary_sensor.cellar")
            srv._offer_findings([row], now)
            for i in range(20):
                srv._resident_offer(srv.signals.make(
                    "state", "lock.front_door", now=now + i, hot=True,
                    source="eventbus", protected=True, salience=0.9,
                    text=f"change {i}"))
            srv._resident_absorb(now + 30)
            self.assertIn(row["ts"], [s.get("finding_ts")
                                      for s in srv.RESIDENT_PENDING])
            self.assertLessEqual(len(srv.RESIDENT_PENDING),
                                 srv.RESIDENT_QUEUE_MAX)
        finally:
            srv.RESIDENT_QUEUE_MAX = old


class TestAnOverdueRowIsFirstInTheReserve(Waiting):

    def test_a_row_past_the_show_threshold_beats_fresher_rows(self):
        srv = self.server
        now = time.time()
        overdue = srv.triage.SHOW_AFTER_S + 60
        hot = [srv.signals.make("state", f"lock.d{i}", now=now, hot=True,
                                source="eventbus", text=f"d{i}",
                                salience=0.6) for i in range(30)]
        fresh = [{**srv.signals.make("check", f"sensor.f{i}", now=now,
                                     text=f"f{i}", salience=0.5),
                  "finding_ts": 2000 + i, "waiting_since": int(now) - 30}
                 for i in range(20)]
        old = {**srv.signals.make("check", "sensor.old", now=now,
                                  text="old", salience=0.1),
               "finding_ts": 1000, "waiting_since": int(now - overdue)}
        got = srv.signals.batch(hot + fresh + [old], 30, filed_reserve=15,
                                overdue_before=now - srv.triage.SHOW_AFTER_S)
        self.assertIn(1000, [s.get("finding_ts") for s in got["batch"]])
        # Without a cutoff the order is salience's, exactly as before.
        plain = srv.signals.batch(hot + fresh + [old], 30, filed_reserve=15)
        self.assertNotIn(1000, [s.get("finding_ts") for s in plain["batch"]])

    def test_the_offer_carries_when_the_row_started_waiting(self):
        srv = self.server
        now = time.time()
        row = self.file_check_row()
        srv._offer_findings([row], now)
        [sig] = [s for s in srv.RESIDENT_PENDING
                 if s.get("finding_ts") == row["ts"]]
        self.assertEqual(sig["waiting_since"],
                         srv.findings_store.waiting_since(row))


class TestARowTheLookJudgedIsNotWaitingForALook(Waiting):

    def test_not_counted_while_its_investigation_runs(self):
        import engine
        srv = self.server
        now = time.time()
        row = self.file_check_row()
        engine.run_claude = answer_every_row("investigate")
        seen = []

        def run_analyst(prompt, system, *a, **k):
            rows = srv.findings_store.list_all()
            seen.append(row["ts"] in {f["ts"] for f in srv._waiting_rows(rows)})
            return {"ok": False, "error": "no answer", "meta": {}}
        engine.run_analyst = run_analyst
        out = self.tick(now)
        self.assertTrue(out.get("looked"), out)
        self.assertEqual(seen, [False],
                         "a row the look had judged was counted as waiting "
                         "for a look while it was being investigated")
        # And once the investigation came back empty it is shown, as before.
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")
        self.assertFalse(srv._waiting_rows(srv.findings_store.list_all()))


if __name__ == "__main__":
    unittest.main()
