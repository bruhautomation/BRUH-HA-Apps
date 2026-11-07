#!/usr/bin/env python3
"""A first look stopped at its time limit (#721).

"Checking new findings" was stopped at 120s with no sign of what it had not
reviewed. Its batch already went back on the pending list; nothing said how
many, and the next look took the same full batch into the same limit.
Driven on the real loop with the CLI stubbed to time out.
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase, reply  # noqa: E402

TIMED_OUT = {"ok": False, "error": "Claude timed out after 120s", "meta": {}}


def rows_in(prompt: str) -> int:
    return len(re.findall(r"^(\d+)\. ", prompt, re.M))


class TimeoutCase(LoopCase):
    """LoopCase with this issue's three counters put back either side, so
    no other test file's loop starts on a cut batch."""

    KEYS = ("left_unreviewed", "timeouts", "batch_limit")

    def setUp(self):
        super().setUp()
        self._zero()
        self.addCleanup(self._zero)

    def _zero(self):
        for key in self.KEYS:
            self.server.RESIDENT_STATE[key] = 0


class TestALookThatRanOutOfTime(TimeoutCase):

    def fill(self, n: int) -> list[int]:
        return [self.file_check_row(entity_id=f"binary_sensor.door_{i}",
                                    text=f"The door contact {i} has not changed")["ts"]
                for i in range(n)]

    def look(self, now: float) -> dict:
        self.server.RESIDENT_STATE["last_look_at"] = 0.0
        return self.tick(now)

    def test_unreviewed_rows_stay_queued_and_the_next_batch_is_smaller(self):
        srv = self.server
        resident = srv.resident
        filed = self.fill(resident.MAX_BATCH + 4)
        now = time.time()
        self.looks.append(dict(TIMED_OUT))
        self.look(now)
        first = rows_in(self.look_calls[0]["prompt"])
        self.assertEqual(first, resident.MAX_BATCH)
        # Nothing it held was lost: every filed row is still queued.
        queued = {int(s["finding_ts"]) for s in srv.RESIDENT_PENDING
                  if s.get("finding_ts")}
        self.assertEqual(queued, set(filed))
        diag = srv._resident_diagnostics()
        self.assertEqual(diag["left_unreviewed"], first)
        self.assertEqual(diag["timeouts"], 1)

        # The next look resumes from them, with a smaller batch.
        self.looks.append(dict(TIMED_OUT))
        self.look(now + 700)
        second = rows_in(self.look_calls[1]["prompt"])
        self.assertLess(second, first)
        self.assertGreaterEqual(second, resident.MIN_BATCH)

        # Two in a row is something health says, with the count.
        import health
        problems = health._resident_problems(
            {"resident": srv._resident_diagnostics()}, now + 700)
        said = [p for p in problems if p["id"] == "resident:timed_out"]
        self.assertEqual(len(said), 1)
        self.assertIn(f"{second} new finding", said[0]["what"])

        # A look that comes back clears it and grows the batch again.
        self.looks.append(reply([{"id": n, "verdict": "ignore", "why": "fine"}
                                 for n in range(1, resident.MAX_BATCH + 1)]))
        self.look(now + 1400)
        third = rows_in(self.look_calls[2]["prompt"])
        self.assertLessEqual(third, second // 2 + 1)
        diag = srv._resident_diagnostics()
        self.assertEqual(diag["left_unreviewed"], 0)
        self.assertEqual(diag["timeouts"], 0)
        self.assertGreater(resident.next_batch_limit(diag["batch_limit"]), third)

    def test_a_small_batch_that_times_out_is_not_cut(self):
        srv = self.server
        self.fill(3)
        self.looks.append(dict(TIMED_OUT))
        self.look(time.time())
        self.assertEqual(srv.RESIDENT_STATE["left_unreviewed"], 3)
        self.assertEqual(srv.RESIDENT_STATE["batch_limit"], 0)

    def test_a_failure_that_is_not_a_timeout_says_nothing_of_one(self):
        srv = self.server
        self.fill(srv.resident.MAX_BATCH)
        self.looks.append({"ok": False, "error": "no reply", "meta": {}})
        self.look(time.time())
        self.assertEqual(srv.RESIDENT_STATE["left_unreviewed"], 0)
        self.assertEqual(srv.RESIDENT_STATE["batch_limit"], 0)


class TestTheLimitArithmetic(TimeoutCase):

    def test_shrink_and_grow(self):
        res = self.server.resident
        self.assertEqual(res.next_batch_limit(0), res.MAX_BATCH)
        self.assertEqual(res.shrunk_batch_limit(res.MAX_BATCH, 0), res.MAX_BATCH // 2)
        self.assertEqual(res.shrunk_batch_limit(6, 0), 0)
        self.assertEqual(res.shrunk_batch_limit(6, 6), res.MIN_BATCH)
        limit = res.MIN_BATCH
        for _ in range(10):
            limit = res.grown_batch_limit(limit)
        self.assertEqual(limit, 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
