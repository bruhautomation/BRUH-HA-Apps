#!/usr/bin/env python3
"""Two simulated days of a busy house, on the real attention loop.

A house with a hundred and fifty chatty entities (a fifth of them
protected, so every change is a hot signal), a checks pass every six hours
filing eight rows, and the Resident on its real timers and real caps
(`triage.MAX_PER_DAY`, `HOT_LOOKS_PER_DAY`, the ledger, the batch reserve).
Only the CLI is stubbed, and every look and investigation it is asked for
succeeds. The clock is simulated for the stores as well as the loop, so a
row's filing stamp and the loop's `now` are one clock.

What is measured is the one claim the fault row makes: how long a row a
rule filed waits before a look gives it a verdict. Every filed row must
have one within two looks of being filed.
"""

import asyncio
import json
import re
import sys
import time as real_time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase  # noqa: E402


class SimClock:
    """`time`, with `time()` answering the simulation's clock."""

    def __init__(self, now: float):
        self.now = float(now)

    def time(self) -> float:
        return self.now

    def __getattr__(self, name):
        return getattr(real_time, name)


ENTITIES = 150
PROTECTED_EVERY = 5          # one in five is protected: its changes are hot
CHECKS_EVERY_S = 6 * 3600
ROWS_PER_PASS = 8
STEP = 120
CHATTER_EVERY = 2            # each entity changes every four minutes
DAYS = 2


class TwoDays(LoopCase):

    def setUp(self):
        super().setUp()
        import engine
        srv = self.server
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))
        # Midnight-aligned start, so both days are whole house days.
        start = real_time.mktime(real_time.strptime("2026-03-02", "%Y-%m-%d"))
        self.clock = SimClock(start)
        for name in ("findings_store", "triage", "outcomes", "resident",
                     "decision_trail"):
            for mod in self.copies(name):
                self._restore.append((mod, "time", mod.time))
                mod.time = self.clock
        self._restore.append((srv, "time", srv.time))
        srv.time = self.clock
        self.looks_run = 0
        self.investigations_run = 0
        # The verdict a look gives, per row: filed rows are mostly watched
        # (looked into), some ignored, live state changes mostly ignored.
        verdicts = ("watch", "investigate", "ignore", "watch")

        def run_claude(prompt, system, *a, **k):
            self.looks_run += 1
            ids = [int(m) for m in re.findall(r"^(\d+)\. ", prompt, re.M)]
            return {"ok": True, "error": "",
                    "text": json.dumps({"verdicts": [
                        {"id": i, "verdict": verdicts[i % len(verdicts)],
                         "why": "looked at it"} for i in ids]}),
                    "meta": {"session_id": f"look-{self.looks_run}"}}

        def run_analyst(prompt, system, *a, **k):
            # Every investigation succeeds and makes no claim — the row is
            # then shown with the look's reason.
            self.investigations_run += 1
            return {"ok": True, "error": "",
                    "text": json.dumps({"claim": "", "detail": "",
                                        "evidence": [], "stakes": "low",
                                        "confidence": 0.3, "kind": "problem",
                                        "actions": [], "dismiss": False}),
                    "meta": {"session_id": f"inv-{self.investigations_run}"}}

        engine.run_claude = run_claude
        engine.run_analyst = run_analyst
        # The worked examples read the whole verdict log on every look, and
        # two days of looks make that the slowest thing here by far; what
        # they say has no bearing on whether a row is looked at.
        self._restore.append((srv, "_outcome_examples", srv._outcome_examples))
        srv._outcome_examples = lambda *a, **k: []
        self.filed: dict[int, float] = {}       # ts -> when filed (sim)
        # Every store read runs inline rather than on a worker thread: two
        # days of ticks are thousands of them, and the thread hand-offs
        # were most of this test's wall clock while changing no answer.

        async def inline(fn, *args, **kwargs):
            return fn(*args, **kwargs)
        self._restore.append((srv.asyncio, "to_thread", srv.asyncio.to_thread))
        srv.asyncio.to_thread = inline

    def checks_pass(self, n: int) -> None:
        srv = self.server
        rows = srv.findings_store.add_many(srv.triage.gate([{
            "text": f"Sensor {n}-{i} has been unavailable for an hour",
            "detail": "since this morning", "severity": "warning",
            "entity_id": f"sensor.pass_{n}_{i}",
            "source": "check:dev.unavailable",
            "source_title": "Devices that stopped answering"}
            for i in range(ROWS_PER_PASS)]))
        for row in rows:
            self.filed[int(row["ts"])] = self.clock.now
        srv._offer_findings(rows, self.clock.now)

    def chatter(self) -> None:
        srv = self.server
        now = self.clock.now
        tick = int(now // STEP)
        for e in range(ENTITIES):
            # Each entity reports every few minutes, staggered.
            if (tick + e) % CHATTER_EVERY:
                continue
            protected = e % PROTECTED_EVERY == 0
            domain = "lock" if protected else "sensor"
            srv._resident_offer(srv.signals.make(
                "state", f"{domain}.chatty_{e}", now=now, hot=protected,
                source="eventbus", protected=protected,
                salience=0.5 if protected else 0.2,
                text=f"{domain} {e} changed at {int(now)}"))

    def run_days(self) -> dict:
        return asyncio.run(self._run_days())

    async def _run_days(self) -> dict:
        srv = self.server
        start = self.clock.now
        verdict_at: dict[int, float] = {}
        looks_at: list[float] = []
        pass_no = 0
        for step in range(0, DAYS * 86400, STEP):
            self.clock.now = start + step
            if step % CHECKS_EVERY_S == 600:
                self.checks_pass(pass_no)
                pass_no += 1
            self.chatter()
            before = self.looks_run
            await srv._resident_tick(self.clock.now)
            if self.looks_run > before:
                looks_at.append(self.clock.now)
            for row in srv.findings_store.list_all():
                ts = int(row["ts"])
                if ts in self.filed and ts not in verdict_at:
                    rec = row.get("triage") or {}
                    if rec.get("verdict") and rec.get("verdict") != "untriaged":
                        verdict_at[ts] = self.clock.now
        return {"verdict_at": verdict_at, "looks_at": looks_at}

    def test_every_filed_row_gets_a_verdict_within_two_looks(self):
        out = self.run_days()
        verdict_at, looks_at = out["verdict_at"], out["looks_at"]
        self.assertEqual(len(self.filed), ROWS_PER_PASS * DAYS * 4)
        waits = []
        for ts, filed in self.filed.items():
            got = verdict_at.get(ts)
            later = [t for t in looks_at if t >= filed]
            self.assertIsNotNone(
                got, f"a row filed at +{(filed - looks_at[0]) / 3600:.1f} h "
                "never had a verdict, though every look succeeded")
            waits.append(got - filed)
            # Within two looks of being filed.
            self.assertLessEqual(
                got, later[1] if len(later) > 1 else later[0],
                f"a row waited {(got - filed) / 60:.0f} min "
                f"({len([t for t in later if t <= got])} looks) for a verdict")
        self.assertLess(max(waits), 2 * 3600,
                        f"the oldest wait was {max(waits) / 3600:.1f} h")
        # And the fault row's own count agrees: nothing is waiting at the end.
        srv = self.server
        self.assertEqual(
            srv._waiting_rows(srv.findings_store.list_all()), [])


if __name__ == "__main__":
    unittest.main()


class TestAFiledRowIsNeverTooOldForALook(LoopCase):
    """The pending list drops a signal older than a day (a moment that
    already happened). A filed row's signal is stamped when it is OFFERED,
    so a row silence showed days ago and a restart left behind still
    reaches the next look — pinned, because the day-old drop reading the
    filing instead would leave it waiting for good."""

    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))

    def test_a_row_filed_two_days_ago_still_reaches_a_look(self):
        import engine
        srv = self.server
        row = self.file_check_row()
        now = float(row["ts"]) + 2 * 86400
        # Shown unjudged long ago, then the panel restarted.
        srv.findings_store.record_triage(
            {row["ts"]: ("untriaged", srv.triage.UNJUDGED)}, "", now - 86400)
        seen = []

        def run_claude(prompt, system, *a, **k):
            ids = [int(m) for m in re.findall(r"^(\d+)\. ", prompt, re.M)]
            seen.append(prompt)
            return {"ok": True, "error": "", "text": json.dumps({
                "verdicts": [{"id": i, "verdict": "ignore",
                              "why": "already answered"} for i in ids]}),
                "meta": {"session_id": "look"}}
        engine.run_claude = run_claude
        asyncio.run(srv._resident_tick(now))
        self.assertTrue(seen, "the row two days old was never looked at")
        fresh = srv.findings_store.get(row["ts"])
        self.assertNotEqual(fresh["triage"]["verdict"], "untriaged")


class TestHotLooksLeaveTheTimerItsLooks(unittest.TestCase):

    def test_a_day_of_hot_pull_forwards_never_takes_the_timers_looks(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                               / "brain" / "panel"))
        import triage
        interval = 600
        runs, last = 0, -10 ** 9
        for minute in range(24 * 60):
            now = minute * 60
            left = triage.timer_looks_left(86400 - now, interval)
            due = now - last >= interval
            hot = triage.hot_look_allowed(runs, left)
            if due or hot:
                self.assertLess(runs, triage.MAX_PER_DAY,
                                f"the day's looks ran out at {minute // 60}:"
                                f"{minute % 60:02d}")
                runs += 1
                last = now
        self.assertLessEqual(runs, triage.MAX_PER_DAY)
