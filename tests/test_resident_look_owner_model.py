#!/usr/bin/env python3
"""A first look the owner's model option promoted is charged to the tier it
was planned on, so the Sonnet allowance cannot stop it (#630).

With the add-on's model option set to Sonnet every first look (planned on
the cheap tier, which the ledger never stops) ran on Sonnet and was charged
to Sonnet: the investigations' allowance was gone by the small hours, and
from then on the looks stepped down or held and investigations parked for
the rest of the day. Driven on the real loop with the CLI stubbed.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase, reply  # noqa: E402


class TestTheOwnersModelDoesNotSpendTheAllowance(LoopCase):

    def setUp(self):
        super().setUp()
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "model": "sonnet", "thinking": "normal"})

    def test_a_look_runs_after_the_sonnet_allowance_is_spent(self):
        srv = self.server
        resident = srv.resident
        now = time.time()
        cap = resident.SONNET_PER_DAY["normal"]
        for _ in range(cap):
            srv.LEDGER.record(resident.JOB_INVESTIGATE, 10, now, tier="sonnet")
        self.assertFalse(srv.LEDGER.allows("sonnet", "normal", now=now)[0])
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "fine"}]))
        out = self.tick(now)
        self.assertTrue(out.get("looked"), out)
        self.assertEqual(len(self.look_calls), 1)
        # Stepped down (the investigations spent the allowance), never held,
        # and charged to the tier it was planned on.
        tiers = srv.LEDGER.today(now)["tiers"]
        self.assertEqual(tiers["sonnet"]["runs"], cap)
        self.assertEqual(tiers["haiku"]["runs"], 1)

    def test_promoted_looks_leave_the_investigations_their_allowance(self):
        srv = self.server
        resident = srv.resident
        now = time.time()
        for i in range(30):
            self.file_check_row(entity_id=f"binary_sensor.pantry_{i}",
                                text=f"The pantry contact {i} has not changed")
            envelope = reply([{"id": n, "verdict": "ignore", "why": "fine"}
                              for n in range(1, resident.MAX_BATCH + 1)])
            envelope["meta"]["model"] = "claude-sonnet-4-6"
            self.looks.append(envelope)
            srv.RESIDENT_STATE["last_look_at"] = 0.0
            self.tick(now + i * 700)
        self.assertGreaterEqual(len(self.look_calls), 10)
        # Every look ran on the owner's model: nothing stepped it down.
        self.assertEqual({c["args"][0] for c in self.look_calls}, {"sonnet"})
        self.assertEqual(srv.LEDGER.spent("sonnet", now + 30 * 700), 0)
        self.assertTrue(srv.LEDGER.allows("sonnet", "normal",
                                          now=now + 30 * 700)[0])


if __name__ == "__main__":
    import unittest
    unittest.main()
