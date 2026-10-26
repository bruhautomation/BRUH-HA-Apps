"""The development loop says only what is new.

Every brAIn update used to reopen every closed report at once, each with
"Back again … after this was closed", because the house reopened on any
version change and every update re-stamps every row a window still holds.
None of those were new evidence, and every run of the cloud loop spent its
first hour closing them again. These tests hold the rules that replace it:

- a report the cloud called noise (not brAIn's, a duplicate, declined) is
  never commented on or reopened;
- a fixed report is reopened only when its fault went away and came back
  after the close, or has gone on for a day on a release first seen after
  the close;
- a row that says when it last happened (Morph's ledger) is seen then;
- a new scorecard closes the one it replaces;
- a producer nobody has marked Wrong for a fortnight is not a fault.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import NAMES, DevloopCase, diagnostics, streams_mod, upstream  # noqa: E402

import reports  # noqa: E402

HOUR = 3600


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class _Case(DevloopCase):
    def close(self, number: int, label: str, at: float):
        self.gh.judge(number, label)
        self.gh.issues[number - 1]["closed_at"] = _iso(at)

    def pass_(self, now: float, version: str = "2.17.0"):
        upstream.sweep(diagnostics(version=version), NAMES, now=now)
        upstream.send_due(now=now)

    def reopened(self) -> list[tuple[int, str]]:
        return [c for c in self.gh.comments if c[1].startswith("Back again")]


class TestAnUpdateIsNotEvidence(_Case):
    def test_a_fixed_report_still_in_its_window_is_not_reopened(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.pass_(t)
        closed = t + 2 * HOUR
        self.close(1, "devloop:fixed", closed)
        # The verdict is read back, then the house updates while the row is
        # still in its window, and keeps seeing it for half a day.
        self.pass_(closed + upstream.VERDICT_INTERVAL_S + 60)
        for h in range(4, 16, 2):
            self.pass_(closed + h * HOUR, version="2.17.1")
        self.assertEqual(self.gh.issues[0]["state"], "closed")
        self.assertEqual(self.reopened(), [])

    def test_a_fixed_report_seen_a_day_on_a_newer_release_is_reopened(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.pass_(t)
        closed = t + 2 * HOUR
        self.close(1, "devloop:fixed", closed)
        self.pass_(closed + upstream.VERDICT_INTERVAL_S + 60)
        start = closed + 3 * HOUR
        for h in range(0, 27, 3):
            self.pass_(start + h * HOUR, version="2.17.1")
        self.assertEqual(self.gh.issues[0]["state"], "open")
        self.assertEqual(len([c for c in self.reopened() if c[0] == 1]), 1)

    def test_a_noise_verdict_is_final(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.pass_(t)
        for n, label in ((1, "devloop:not-brain"), (2, "devloop:duplicate")):
            self.close(n, label, t + HOUR)
        before = len(self.gh.comments)
        self.pass_(t + 2 * HOUR)
        for h in range(3, 80, 4):
            self.pass_(t + h * HOUR, version=f"2.17.{h}")
        self.assertEqual([i["state"] for i in self.gh.issues], ["closed", "closed"])
        self.assertEqual(self.gh.comments[before:], [])

    def test_a_fault_that_went_away_and_came_back_is_reopened_at_once(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.pass_(t)
        keep, self.rows = self.rows, []
        later = t + upstream.CLEAR_AFTER_S + 60
        self.pass_(later)
        self.close(1, "devloop:fixed", later + HOUR)
        self.rows = keep
        self.pass_(later + 2 * HOUR)
        self.assertEqual(self.gh.issues[0]["state"], "open")


class TestARowSaysWhenItHappened(_Case):
    def _morph(self, seen_at: float, now: float, version: str):
        row = {"where": "Morph · Cards", "what": "A card failed to draw",
               "detail": "", "body": "x", "seen_at": seen_at}
        upstream.ingest("morph", [row], diagnostics(version=version), now=now)
        upstream.send_due(now=now)

    def test_a_republished_old_row_is_not_still_happening(self):
        self.switch_on()
        import devloop
        devloop.save_settings({"streams": {"morph": True}})
        t = time.time() - 10 * 24 * HOUR
        self._morph(t, t, "2.17.0")
        for h in range(2, 60, 6):
            self._morph(t, t + h * HOUR, f"2.17.{h}")
        texts = [c[1] for c in self.gh.comments]
        self.assertFalse([x for x in texts if x.startswith("Still happening")], texts)
        self.assertEqual(len([x for x in texts if x.startswith("Not seen since")]), 1)

    def test_the_morph_stream_reads_when_morph_last_saw_it(self):
        path = Path(self.tmp.name) / "outbox.json"
        path.write_text('{"rows": [{"where": "Morph · Cards", "what": "w", '
                        '"last": 1700000000.5}]}', encoding="utf-8")
        self.assertEqual(streams_mod.morph(path)[0]["seen_at"], 1700000000.5)


class TestALiveFaultSaysItsCurrentNumbers(_Case):
    def test_a_still_happening_fault_rewrites_its_body(self):
        self.switch_on()
        t = time.time()
        self.pass_(t)
        self.rows[0]["detail"] = "it is now nineteen rows, held by the gate"
        self.pass_(t + HOUR, version="2.17.1")
        self.assertIn("held by the gate", self.gh.issues[0]["body"])
        self.assertTrue(any(c[1].startswith("Still happening") for c in self.gh.comments))


class TestANewScorecardRetiresTheOld(_Case):
    def _score(self, version):
        rows = [{"source": "check:dev.frozen", "confirmed": 5, "wrong": 2, "total": 7}]
        return streams_mod.scorecard(rows, diagnostics(version=version), version)

    def test_the_previous_release_scorecard_is_closed(self):
        self.switch_on()
        upstream.ingest("scorecard", self._score("2.17.0"), diagnostics())
        upstream.send_due()
        upstream.ingest("scorecard", self._score("2.17.1"),
                        diagnostics(version="2.17.1"))
        upstream.send_due()
        self.assertEqual([i["state"] for i in self.gh.issues], ["closed", "open"])
        self.assertIn((1, "Superseded by #2 (brAIn 2.17.1)."), self.gh.comments)
        # Nothing more is said about it afterwards.
        before = len(self.gh.comments)
        upstream.send_due(now=time.time() + upstream.VERDICT_INTERVAL_S + 1)
        self.assertEqual(self.gh.comments[before:], [])


class TestAQuietRuleIsHistory(unittest.TestCase):
    def _diag(self, last_wrong: float, now: float) -> dict:
        return {"generated_at": now, "findings": {"scorecard": [
            {"source": "check:dev.frozen", "title": "Sensors frozen",
             "wrong": 4, "confirmed": 1, "total": 5, "last_wrong_ts": last_wrong}]}}

    def _producer_rows(self, diag):
        return [r for r in reports.faults(diag) if r["where"].startswith("Producer")]

    def test_a_recent_wrong_is_a_fault(self):
        now = time.time()
        self.assertEqual(len(self._producer_rows(self._diag(now - 86400, now))), 1)

    def test_a_fortnight_with_no_wrong_is_not(self):
        now = time.time()
        old = now - reports.SCORE_RECENT_S - 86400
        self.assertEqual(self._producer_rows(self._diag(old, now)), [])

    def test_the_scorecard_carries_the_newest_wrong(self):
        import findings_store
        rows = [{"source": "check:a", "kind": "ignored", "ts": 100, "text": "x"},
                {"source": "check:a", "kind": "ignored", "ts": 300, "text": "y"},
                {"source": "check:a", "kind": "fixed", "ts": 500, "text": "z"}]
        old = findings_store._load_settled
        findings_store._load_settled = lambda: rows
        try:
            card = findings_store.scorecard()
        finally:
            findings_store._load_settled = old
        self.assertEqual(card[0]["last_wrong_ts"], 300)


class TestARuleIsDatedByItsNewestWrong(_Case):
    """A Wrongs count is a record, not a reading: it is re-read every pass
    and does not fall for a fortnight, so a rule fixed on a release whose
    Wrongs all predate the fix was reopened a day after every update. The
    row is dated by its newest Wrong, through the real fault list."""

    def setUp(self):
        super().setUp()
        upstream.reports.faults = self._faults  # the real rows this time
        self.last_wrong = 0.0

    def _diag(self, version: str) -> dict:
        diag = diagnostics(version=version)
        diag.pop("daemons"), diag.pop("expected_daemons"), diag.pop("journal")
        diag["health"] = {"state": "ok"}
        diag["findings"] = {"scorecard": [
            {"source": "check:dev.frozen", "title": "Sensors frozen",
             "wrong": 4, "confirmed": 1, "total": 5,
             "last_wrong_ts": self.last_wrong}]}
        return diag

    def pass_(self, now: float, version: str = "2.17.0"):
        diag = self._diag(version)
        diag["generated_at"] = now
        upstream.sweep(diag, NAMES, now=now)
        upstream.send_due(now=now)

    def _producer_issue(self) -> int:
        found = [n for n, issue in enumerate(self.gh.issues, 1)
                 if issue["title"].startswith("[Producer")]
        self.assertTrue(found, [i["title"] for i in self.gh.issues])
        return found[0]

    def test_an_unchanged_count_on_a_newer_release_is_not_reopened(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.last_wrong = t - HOUR
        self.pass_(t)
        n = self._producer_issue()
        closed = t + 2 * HOUR
        self.close(n, "devloop:fixed", closed)
        self.pass_(closed + upstream.VERDICT_INTERVAL_S + 60)
        for h in range(3, 40, 3):
            self.pass_(closed + h * HOUR, version="2.17.1")
        self.assertEqual(self.gh.issues[n - 1]["state"], "closed")
        self.assertEqual([c for c in self.reopened() if c[0] == n], [])

    def test_a_new_wrong_after_the_close_reopens_it(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.last_wrong = t - HOUR
        self.pass_(t)
        n = self._producer_issue()
        closed = t + 2 * HOUR
        self.close(n, "devloop:fixed", closed)
        self.pass_(closed + upstream.VERDICT_INTERVAL_S + 60)
        for h in range(3, 80, 6):
            self.pass_(closed + h * HOUR, version="2.17.1")
        self.assertEqual(self.gh.issues[n - 1]["state"], "closed")
        self.last_wrong = closed + 80 * HOUR
        self.pass_(closed + 81 * HOUR, version="2.17.1")
        self.assertEqual(self.gh.issues[n - 1]["state"], "open")


if __name__ == "__main__":
    unittest.main()
