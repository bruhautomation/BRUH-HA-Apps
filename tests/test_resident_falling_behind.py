#!/usr/bin/env python3
"""A Resident whose stepped-up allowance is spent keeps looking, and its
queue holds things to look at rather than copies of them (#661, #665).

Two health rows were honest about a Resident that had fallen behind:
"brAIn has not looked at the house for N hour(s)" with the reason "the
sonnet allowance for today is spent (32 of 32 on the generous thinking
setting)", and "brAIn's queue of things to look at is nearly full (429 of
500)". The causes, each reproduced here before it is fixed:

  * **The `generous` dial steps the first look up to Sonnet, and the look
    was then held by the Sonnet allowance.** A look every ten minutes is
    144 a day against an allowance of 32, so from early morning nothing
    looked at the house at all — the ledger's own rule is that the cheap
    tier is never stopped by a counter, and the stepped-up look broke it.
    A look whose stepped tier is spent now runs on its planned tier; a
    typed model the allowance bounds falls back the same way. And a look
    on the tier investigations are paid from leaves them their share.

  * **The pending list folded repeats only once it was over its cap**, so
    a chatty subject that changed every ten minutes put one row per change
    on it, and a day of held looks filled it toward the cap with copies of
    a few subjects. Live signals are now folded by kind and subject as
    they arrive: one thing to look at, its repeats counted.

  * **A filed row a person settled while it waited stayed on the list**
    until a look reached it. The minute sweep now drops such a row, and
    every drop says why (`dropped_why`).
"""

import asyncio
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase, reply  # noqa: E402


class Trailed(LoopCase):
    """LoopCase with the decision trail in this test's own directory."""

    def setUp(self):
        super().setUp()
        self.point("decision_trail",
                   TRAIL_FILE=str(Path(self.tmp.name) / "decisions.jsonl"))


class Budget(Trailed):

    def use(self, thinking: str = "normal", model: str = "") -> None:
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "thinking": thinking})
        srv = self.server
        old = srv.eff_model
        srv.eff_model = lambda: model
        self.addCleanup(setattr, srv, "eff_model", old)

    def spend(self, tier: str, runs: int, now: float) -> None:
        for _ in range(runs):
            self.server.LEDGER.record(self.server.resident.JOB_FIRST_LOOK,
                                      0, now, tier=tier)

    def look_model(self) -> str:
        [call] = self.look_calls
        return call["args"][0]


class TestLooksGoOnWhenTheSteppedUpAllowanceIsSpent(Budget):

    def test_generous_looks_go_on_after_the_sonnet_allowance(self):
        """The issue's own case: 32 of 32 on the generous setting."""
        srv = self.server
        res = srv.resident
        self.use("generous")
        now = time.time()
        self.spend("sonnet", res.SONNET_PER_DAY["generous"], now)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "a cupboard nobody opens"}]))
        out = self.tick(now)
        self.assertTrue(out.get("looked"), out)
        self.assertEqual(self.look_model(), "haiku")
        self.assertEqual(srv.RESIDENT_STATE["held_since"], 0.0)

        import health
        diag = {"resident": srv._resident_diagnostics()}
        self.assertNotIn("resident:held",
                         [p["id"] for p in health.problems(
                             diag, {}, now + 6 * 3600)])

    def test_a_typed_opus_model_falls_back_once_its_allowance_is_spent(self):
        """A second door to the same hold: a typed model the ledger bounds."""
        res = self.server.resident
        self.use("normal", model="claude-opus-5-5")
        now = time.time()
        self.spend("opus", res.OPUS_PER_DAY["normal"], now)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "no"}]))
        out = self.tick(now)
        self.assertTrue(out.get("looked"), out)
        self.assertEqual(self.look_model(), "haiku")
        self.assertEqual(self.look_calls[0].get("effort"), "low")

    def test_the_stepped_tier_is_used_while_it_lasts(self):
        res = self.server.resident
        self.use("generous")
        now = time.time()
        self.spend("sonnet", res.SONNET_PER_DAY["generous"] - 1, now)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "no"}]))
        self.assertTrue(self.tick(now).get("looked"))
        # The engine plans the stepped tier itself: no model is handed down.
        self.assertEqual(self.look_model(), "")

    def test_looks_on_the_investigations_tier_leave_them_their_share(self):
        """A typed Sonnet puts looks and investigations on one allowance,
        and looks every ten minutes spent all of it by breakfast."""
        res = self.server.resident
        self.use("normal", model="sonnet")
        now = time.time()
        cap = res.SONNET_PER_DAY["normal"]
        self.spend("sonnet", cap // 2, now)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "no"}]))
        self.assertTrue(self.tick(now).get("looked"))
        self.assertEqual(self.look_model(), "haiku")
        ok, _why = self.server.LEDGER.allows("sonnet", "normal", now=now)
        self.assertTrue(ok, "the look spent the investigations' allowance")


class TestTheLedgerKeepsAReserve(unittest.TestCase):

    def test_a_reserve_lowers_the_cap_and_says_so(self):
        import tempfile
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                               / "brain" / "panel"))
        import resident
        with tempfile.TemporaryDirectory() as tmp:
            led = resident.Ledger(Path(tmp) / "ledger.json")
            now = 1_800_000_000.0
            for _ in range(8):
                led.record("first_look", 0, now, tier="sonnet")
            ok, why = led.allows("sonnet", "normal", now=now, reserve=8)
            self.assertFalse(ok)
            self.assertIn("8 of 8", why)
            self.assertTrue(led.allows("sonnet", "normal", now=now)[0])
            self.assertEqual(led.cap("sonnet", "normal"), 16)
            self.assertIsNone(led.cap("haiku", "normal"))


class TestTheQueueHoldsThingsNotCopies(Trailed):

    def offer(self, subject: str, at: float, **over) -> None:
        srv = self.server
        srv._resident_offer(srv.signals.make(
            "state", subject, now=at, source="eventbus",
            text=f"{subject} changed", salience=0.3, **over))

    def test_a_burst_about_one_subject_is_one_row(self):
        srv = self.server
        now = time.time()
        for i in range(300):
            self.offer("lock.side_gate", now - 300 + i)
        srv._resident_absorb(now)
        self.assertEqual(srv.RESIDENT_STATE["queue_len"], 1)
        [sig] = srv.RESIDENT_PENDING
        self.assertEqual(sig["repeats"], 300)

    def test_changes_hours_apart_while_looks_are_held_do_not_fill_it(self):
        """Ten minutes apart is past the look's own fold window, so this is
        the shape a held day had: one row per change per subject."""
        srv = self.server
        now = time.time()
        for minute in range(0, 6 * 60, 10):
            at = now - 6 * 3600 + minute * 60
            self.offer("cover.study_blind", at)
            self.offer("climate.attic", at, hot=True)
            srv._resident_absorb(at)
        self.assertEqual(srv.RESIDENT_STATE["queue_len"], 2)
        attic = [s for s in srv.RESIDENT_PENDING
                 if s["subject"] == "climate.attic"]
        self.assertTrue(attic[0]["hot"])
        self.assertEqual(attic[0]["repeats"], 36)

    def test_filed_rows_are_never_folded_together(self):
        srv = self.server
        now = time.time()
        a = self.file_check_row()
        b = self.file_check_row(text="The pantry contact reports no battery",
                                source="check:dev.battery")
        srv._offer_findings([a, b], now)
        srv._resident_absorb(now)
        self.assertEqual(sorted(s.get("finding_ts") for s in
                                srv.RESIDENT_PENDING),
                         sorted([a["ts"], b["ts"]]))


class TestStaleEntriesLeaveWithAReason(Trailed):

    def setUp(self):
        super().setUp()
        self.server.RESIDENT_STATE["dropped_why"] = {}
        # No look is due: these tests are about the list, not the look.
        self.server.RESIDENT_STATE["last_look_at"] = time.time() + 3600

    def test_a_row_settled_while_it_waited_is_dropped_as_resolved(self):
        srv = self.server
        now = time.time()
        keep = self.file_check_row()
        gone = self.file_check_row(text="The porch light reports no power",
                                   entity_id="light.porch")
        self.tick(now)
        self.assertEqual(sorted(s.get("finding_ts") for s in
                                srv.RESIDENT_PENDING),
                         sorted([keep["ts"], gone["ts"]]))
        srv.findings_store.remove(gone["ts"])
        self.tick(now + srv.RESIDENT_SWEEP_S)
        self.assertEqual([s.get("finding_ts") for s in srv.RESIDENT_PENDING],
                         [keep["ts"]])
        self.assertEqual(srv.RESIDENT_STATE["dropped_why"].get("resolved"), 1)

    def test_a_row_a_person_marked_fixed_is_dropped_too(self):
        srv = self.server
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        srv.findings_store.set_status(row["ts"], "fixed")
        self.tick(now + srv.RESIDENT_SWEEP_S)
        self.assertEqual(srv.RESIDENT_PENDING, [])
        self.assertEqual(srv.RESIDENT_STATE["dropped_why"].get("resolved"), 1)

    def test_a_day_old_signal_goes_before_the_cap_takes_a_fresh_one(self):
        srv = self.server
        now = time.time()
        old_max = srv.RESIDENT_QUEUE_MAX
        srv.RESIDENT_QUEUE_MAX = 3
        try:
            srv._resident_offer(srv.signals.make(
                "state", "sensor.loft", now=now - srv.RESIDENT_SIGNAL_TTL_S - 60,
                source="eventbus", text="old", salience=0.9))
            for i in range(3):
                srv._resident_offer(srv.signals.make(
                    "state", f"sensor.room_{i}", now=now, source="eventbus",
                    text="fresh", salience=0.1))
            asyncio.run(asyncio.sleep(0))
            srv._resident_absorb(now)
        finally:
            srv.RESIDENT_QUEUE_MAX = old_max
        self.assertEqual(sorted(s["subject"] for s in srv.RESIDENT_PENDING),
                         ["sensor.room_0", "sensor.room_1", "sensor.room_2"])
        self.assertEqual(srv.RESIDENT_STATE["dropped_why"], {"stale": 1})


if __name__ == "__main__":
    unittest.main()
