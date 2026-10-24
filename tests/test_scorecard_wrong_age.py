#!/usr/bin/env python3
"""A rule's Wrongs age from when they were given, not from when the ledger
was last written.

`reports.faults` lists "[Producer …] ignored N of M times" only while the
newest Wrong is younger than `SCORE_RECENT_S`. A rule with six Wrongs from
one week was still listed two weeks later because something rewrote the
ledger entries under those Wrongs: `_remember_settled` replaces an entry by
key and stamped the replacement with the time of the WRITE, so a re-settle
of a key that was already Wrong (Today's Ignore on a chore, a request
applied again, a migration of an old row) made a fortnight-old answer read
as a Wrong given this morning.

Driven through the real writers into the real scorecard and the real
`faults`, over temporary stores.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store  # noqa: E402
import reports  # noqa: E402

DAY = 86400
T0 = 1_790_000_000
SOURCE = "check:dev.frozen"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "findings-settled.json"
        findings_store.STATE_FILE = root / "findings-state.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def at(self, when):
        return mock.patch.object(findings_store.time, "time", return_value=when)

    def wrong(self, n: int, when: float, source: str = SOURCE) -> None:
        """Six sensors marked Wrong, through the tab's own door."""
        with self.at(when):
            for i in range(n):
                rows = findings_store.add_many([{
                    "text": f"Sensor {i} {source} has read the same value for a week",
                    "severity": "warning", "source": source}])
                ts = rows[0]["ts"] if rows else max(
                    f["ts"] for f in findings_store.list_all())
                findings_store.settle_and_clear(ts, "ignored")

    def producer_rows(self, now: float) -> list[dict]:
        with self.at(now):
            card = findings_store.scorecard()
        diag = {"generated_at": now, "findings": {"scorecard": card}}
        return [r for r in reports.faults(diag)
                if r["where"].startswith("Producer")]


class TestAWrongAgesFromWhenItWasGiven(Case):
    def test_recent_wrongs_are_a_fault(self):
        self.wrong(6, T0)
        self.assertEqual(len(self.producer_rows(T0 + DAY)), 1)

    def test_old_wrongs_alone_are_not(self):
        self.wrong(6, T0)
        self.assertEqual(self.producer_rows(T0 + 20 * DAY), [])

    def test_re_settling_an_answered_key_is_not_a_new_wrong(self):
        self.wrong(6, T0)
        key = findings_store.settled_listing()[0]["key"]
        text = findings_store.settled_listing()[0]["text"]
        # The later rewrite: the same answer recorded again under the same
        # key two weeks on (`remember_answer`, the door Today's Ignore on a
        # chore and every answer for a row that is gone go through).
        with self.at(T0 + 18 * DAY):
            findings_store.remember_answer(key, text, "ignored", source=SOURCE)
        self.assertEqual(len([e for e in findings_store.settled_listing()
                              if e["kind"] == "ignored"]), 6)
        self.assertEqual(self.producer_rows(T0 + 20 * DAY), [])

    def test_a_second_example_another_rule_and_a_migrated_row(self):
        source = "check:auto.conflict"
        self.wrong(5, T0, source)
        # A row that reached the store as `ignored` (an import) is folded
        # in at startup with no settled stamp of its own.
        entry = findings_store.settled_listing()[0]
        with self.at(T0 + 19 * DAY):
            findings_store.merge_settled([dict(entry)])
            findings_store._remember_settled(
                {"text": entry["text"], "source": source}, "ignored")
        self.assertEqual(self.producer_rows(T0 + 20 * DAY), [])

    def test_a_row_migrated_at_startup_keeps_its_own_answer_time(self):
        self.wrong(5, T0)
        import json
        findings_store.FINDINGS_FILE.write_text(json.dumps({"findings": [{
            "ts": T0 - DAY, "text": "Sensor x has read the same value for a week",
            "severity": "warning", "source": SOURCE, "status": "ignored",
            "settled_at": T0}]}), encoding="utf-8")
        with self.at(T0 + 19 * DAY):
            self.assertEqual(findings_store.migrate_settled(), 1)
        self.assertEqual(self.producer_rows(T0 + 20 * DAY), [])

    def test_a_wrong_after_the_key_was_let_back_is_new(self):
        self.wrong(6, T0)
        entry = findings_store.settled_listing()[0]
        findings_store.unsettle(entry["key"])
        with self.at(T0 + 18 * DAY):
            findings_store.remember_answer(entry["key"], entry["text"],
                                           "ignored", source=SOURCE)
        self.assertEqual(len(self.producer_rows(T0 + 20 * DAY)), 1)

    def test_an_answer_that_turned_into_a_wrong_is_new(self):
        with self.at(T0):
            findings_store.remember_answer("k", "Sensor k frozen", "accepted",
                                           source=SOURCE)
        self.wrong(4, T0)
        with self.at(T0 + 18 * DAY):
            findings_store.remember_answer("k", "Sensor k frozen", "ignored",
                                           source=SOURCE)
        self.assertEqual(len(self.producer_rows(T0 + 20 * DAY)), 1)


if __name__ == "__main__":
    unittest.main()
