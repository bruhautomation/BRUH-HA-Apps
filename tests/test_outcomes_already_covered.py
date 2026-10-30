#!/usr/bin/env python3
"""A row the look set aside because an open card already covers it is not a
miss when that card turns out to be real (#547, #548, #549).

The nightly join filed "the look was too quiet about X" for two network
checks and a light: every row it passed over had turned out to matter. But
the look had passed over each one *because* an open card already carried the
same problem, and the household's answer to each row was that it had been
rolled into that card — which was then confirmed. The look said "this is the
other card's problem", the household said the same, and the join read that
as the look missing something.

The examples here are invented, and none of them is the report's own: a
garage door that keeps dropping off the network beside an open "the mesh is
unstable" card, and a freezer probe that nothing covered.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import outcomes  # noqa: E402
import resident  # noqa: E402

DAY = 86400


def look(**over) -> dict:
    row = {"id": f"r{over.get('at', 1000)}-{over.get('idx', 1)}", "at": 1000,
           "stage": "look", "run_id": "look-1", "tier": "haiku", "idx": 1,
           "kind": "check", "subject": "cover.garage_door",
           "entity": "cover.garage_door", "source": "check:net.unreachable",
           "verdict": "ignore", "why": "", "forced": False,
           "fallback": False, "finding_ts": 0, "key": "", "flags": []}
    row.update(over)
    return row


def settled(key: str, kind: str, ts: int, note: str = "") -> dict:
    return {"key": key, "text": key, "kind": kind, "ts": ts, "note": note,
            "source": "check:net.unreachable", "source_title": ""}


def covered_rows(n: int, *, structured: bool = True):
    """``n`` rows the look set aside as the open mesh card's problem, each
    then answered as rolled into that card."""
    rows, ledger = [], []
    for i in range(n):
        at = 1000 + i * DAY
        key = f"garage door unreachable {i}"
        extra = {"already": "duplicate"} if structured else {}
        rows.append(look(id=f"c{i}", at=at, finding_ts=100 + i, key=key,
                         why="The door's drops are the mesh trouble already "
                             "an open card for you.", **extra))
        ledger.append(settled(key, "fixed", at + 3600,
                              "Folded into the mesh card."))
    # The card they were folded into, confirmed: the same subject, so the
    # subject-confirmed window would otherwise read every row as missed.
    rows.append(look(id="mesh", at=1000 + n * DAY, verdict="investigate",
                     finding_ts=900, key="mesh unstable", idx=9))
    ledger.append(settled("mesh unstable", "fixed", 1000 + n * DAY + 600))
    return rows, ledger


class TestCoveredIsAgreement(unittest.TestCase):

    def _louder(self, rows, ledger, now):
        graded = outcomes.grade(rows, [], ledger, now)
        scopes = outcomes.tallies(outcomes.items(graded))
        return graded, [c for c in outcomes.candidates(scopes)
                        if c["direction"] == "louder"]

    def test_set_aside_as_another_cards_problem_then_folded_is_not_missed(self):
        rows, ledger = covered_rows(3)
        graded, louder = self._louder(rows, ledger, 10 * DAY)
        passed = [g for g in graded if g["class"] == "dismissed"]
        self.assertEqual(len(passed), 3)
        for g in passed:
            self.assertIsNot(g["agree"], False, g)
            self.assertNotEqual(g["outcome"], "missed")
        self.assertEqual(louder, [], "a look that was right three times "
                                     "must not be told to be louder")
        t = outcomes.tallies(outcomes.items(graded))["source"][
            "check:net.unreachable"]
        self.assertEqual(t["missed"], 0)

    def test_a_row_written_before_the_word_was_kept_reads_its_reason(self):
        """Rows already in a house's log carry the reason and not the word;
        the reason is the same one `parse_first_look` turns into the word."""
        rows, ledger = covered_rows(3, structured=False)
        _, louder = self._louder(rows, ledger, 10 * DAY)
        self.assertEqual(louder, [])

    def test_a_genuine_miss_still_counts(self):
        """Passed over as nothing, then confirmed as its own case: louder."""
        rows, ledger = [], []
        for i in range(3):
            at = 1000 + i * DAY
            rows.append(look(id=f"m{i}", at=at, kind="state",
                             subject="sensor.freezer_probe",
                             entity="sensor.freezer_probe",
                             source="eventbus",
                             why="A brief bump; the freezer recovers."))
            rows.append(look(id=f"case{i}", at=at + 600, verdict="investigate",
                             kind="state", subject="sensor.freezer_probe",
                             entity="sensor.freezer_probe",
                             source="eventbus", finding_ts=500 + i,
                             key=f"freezer warm {i}"))
            ledger.append(settled(f"freezer warm {i}", "fixed", at + 7200))
        graded, louder = self._louder(rows, ledger, 10 * DAY)
        missed = [g for g in graded if g["outcome"] == "missed"]
        self.assertEqual(len(missed), 3)
        self.assertTrue(all(g["agree"] is False for g in missed))
        self.assertIn("sensor.freezer_probe",
                      [c["subject"] for c in louder])

    def test_a_covered_row_a_person_put_back_is_still_a_miss(self):
        """The household pulling the held row back out says it was its own
        problem after all — that is the look being wrong."""
        rows = [look(finding_ts=11, key="k", already="duplicate",
                     why="Already an open card for you.")]
        live = [{"ts": 11, "text": "k", "status": "open",
                 "triage": {"verdict": "held", "elevated_by_person": True}}]
        [g] = outcomes.grade(rows, live, [], 5000)
        self.assertEqual(g["outcome"], "put_back")
        self.assertIs(g["agree"], False)


class TestTheWordIsRecorded(unittest.TestCase):
    """`record_look` keeps the look's `already` word on the row, so the join
    reads a structured answer rather than re-reading the prose."""

    def test_record_look_keeps_already(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verdicts.jsonl"
            with mock.patch.object(outcomes, "VERDICTS_FILE", path), \
                    mock.patch.object(outcomes.findings_store, "list_all",
                                      return_value=[]), \
                    mock.patch.object(resident, "tier_for",
                                      return_value="haiku"):
                batch = [{"kind": "check", "subject": "cover.garage_door",
                          "source": "check:net.unreachable"},
                         {"kind": "check", "subject": "sensor.freezer_probe",
                          "source": "check:dev.frozen"}]
                verdicts = {1: {"verdict": "ignore", "why": "x",
                                "already": "duplicate", "forced": False},
                            2: {"verdict": "ignore", "why": "y",
                                "forced": False}}
                self.assertEqual(outcomes.record_look(batch, verdicts, "r",
                                                      5000), 2)
                rows = outcomes.load_rows()
        self.assertEqual([r.get("already") for r in rows], ["duplicate", ""])


if __name__ == "__main__":
    unittest.main()
