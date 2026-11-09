#!/usr/bin/env python3
"""The verdict log is read and graded once per change, not once per look.

Every first look asked for the graded log (`server._graded_items`), and
every ask re-read the whole of `/data/resident-verdicts.jsonl`, parsed every
line, re-graded every row and re-folded every item — on a log that only
grows, so each look was slower than the one before it, and
`test_resident_two_days` ran into the per-test timeout on CI.

Pinned here, through the real file and the real functions:

  * an unchanged log (and unchanged stores) is graded ONCE however many
    times it is asked for, and the answer is the one a fresh grade gives;
  * an appended row is parsed, graded and folded alone — the lines already
    read are not parsed or graded again — and the next answer carries it,
    including the one way a new row moves an old one (an investigation
    claiming the look that sent it);
  * anything the answer depends on invalidates it: a new row, a log
    rewritten under the same size, a settled answer, a live row, and the
    clock crossing a row's `STOOD_AFTER_S` (the one place `now` enters);
  * a line still being written is not a row, and is read once complete.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import outcomes  # noqa: E402

T0 = 1_700_000_000


def look_row(i: int, **over) -> dict:
    row = {"id": f"r{i}", "at": T0 + i, "stage": "look", "run_id": "look-1",
           "tier": "haiku", "idx": 1, "kind": "check",
           "subject": f"binary_sensor.s{i % 7}",
           "entity": f"binary_sensor.s{i % 7}", "source": "check:dev.frozen",
           "verdict": "ignore" if i % 2 else "watch", "why": "",
           "forced": False, "fallback": False, "finding_ts": T0 + i,
           "key": f"row {i}", "flags": []}
    row.update(over)
    return row


def line(row: dict) -> str:
    return json.dumps(row, separators=(",", ":")) + "\n"


class GradedOnce(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "verdicts.jsonl"
        self.findings: list[dict] = []
        self.settled: list[dict] = []
        for patch in (
                mock.patch.object(outcomes, "VERDICTS_FILE", self.path),
                mock.patch.object(outcomes.findings_store, "list_all",
                                  side_effect=lambda *a: list(self.findings)),
                mock.patch.object(outcomes.findings_store, "settled_listing",
                                  side_effect=lambda: list(self.settled))):
            patch.start()
            self.addCleanup(patch.stop)
        self.path.write_text("".join(line(look_row(i)) for i in range(40)),
                             encoding="utf-8")

    def fresh(self, now: float) -> list[dict]:
        """What a grade with no memory says: the file parsed by hand."""
        rows = [json.loads(x) for x in
                self.path.read_text(encoding="utf-8").splitlines() if x.strip()]
        return outcomes.grade(rows, self.findings, self.settled, now)

    def append(self, *rows: dict) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write("".join(line(r) for r in rows))

    def test_an_unchanged_log_is_graded_once(self):
        now = T0 + 3600
        # A grade is the context, then `_grade_row` once per verdict row.
        with mock.patch.object(outcomes, "_grade_row",
                               wraps=outcomes._grade_row) as g, \
                mock.patch.object(outcomes.json, "loads",
                                  wraps=json.loads) as parsed:
            graded = [outcomes.load_graded(now + k) for k in range(5)]
        self.assertEqual(g.call_count, 40, "the log was graded on every ask")
        self.assertEqual(parsed.call_count, 40,
                         "the log's lines were parsed on every ask")
        with mock.patch.object(outcomes, "_grade_row",
                               wraps=outcomes._grade_row) as g, \
                mock.patch.object(outcomes, "_items",
                                  wraps=outcomes._items) as it:
            answers = [outcomes.graded_items(now + k) for k in range(5)]
        self.assertEqual(g.call_count, 0, "the same log was graded again")
        self.assertEqual(it.call_count, 1, "the items were folded on every ask")
        expected = outcomes.items(self.fresh(now))
        for answer in answers:
            self.assertEqual(answer, expected)
        for answer in graded:
            self.assertEqual(answer, self.fresh(now))

    def test_a_caller_cannot_change_the_next_answer(self):
        first = outcomes.graded_items(T0 + 60)
        first[0]["outcome"] = "scribbled"
        first.clear()
        again = outcomes.graded_items(T0 + 60)
        self.assertEqual(len(again), 40)
        self.assertNotEqual(again[0]["outcome"], "scribbled")
        rows = outcomes.load_rows()
        rows[0]["stage"] = "scribbled"
        self.assertEqual(outcomes.load_rows()[0]["stage"], "look")

    def test_an_appended_row_is_parsed_alone_and_seen(self):
        outcomes.load_rows()
        self.append(look_row(40))
        with mock.patch.object(outcomes.json, "loads",
                               wraps=json.loads) as loads:
            rows = outcomes.load_rows()
        self.assertEqual(loads.call_count, 1,
                         "every line was parsed again for one new row")
        self.assertEqual(len(rows), 41)
        self.assertEqual(rows[-1]["id"], "r40")
        outcomes.graded_items(T0 + 3600)
        self.append(look_row(41))
        with mock.patch.object(outcomes, "_grade_row",
                               wraps=outcomes._grade_row) as g:
            its = outcomes.graded_items(T0 + 3600)
        self.assertEqual(g.call_count, 1,
                         "the rows already graded were graded again")
        self.assertIn("r41", {i["id"] for i in its})
        self.assertEqual(its, outcomes.items(self.fresh(T0 + 3600)))

    def test_a_later_investigation_still_folds_into_the_look_that_sent_it(self):
        """The one way a new row reaches back and moves an old one: a live
        signal's look that SENT it waits, unclaimed, for the investigation
        it sent — and that row arrives on a later look."""
        sent = look_row(50, verdict="investigate", finding_ts=0, key="",
                        subject="sensor.freezer", entity="sensor.freezer",
                        kind="state", at=T0 + 500)
        self.append(sent)
        first = outcomes.graded_items(T0 + 600)
        self.assertIn("v:r50", {i["item"] for i in first})
        self.append({**look_row(51), "stage": "investigate", "verdict": "filed",
                     "subject": "sensor.freezer", "entity": "sensor.freezer",
                     "finding_ts": 0, "case_ts": T0 + 900, "key": "freezer warm",
                     "at": T0 + 900})
        its = outcomes.graded_items(T0 + 1000)
        self.assertEqual(its, outcomes.items(self.fresh(T0 + 1000)))
        folded = [i for i in its if i["item"] == f"row:{T0 + 900}:freezer warm"]
        self.assertEqual(len(folded), 1)
        self.assertEqual([h["stage"] for h in folded[0]["history"]],
                         ["look", "investigate"])
        self.assertNotIn("v:r50", {i["item"] for i in its})
        # A row stamped before the newest one already folded is placed by a
        # fold from scratch, and lands where it would have.
        self.append(look_row(52, at=T0 - 5))
        self.assertEqual(outcomes.graded_items(T0 + 1000),
                         outcomes.items(self.fresh(T0 + 1000)))

    def test_a_rewritten_log_is_read_again(self):
        outcomes.graded_items(T0 + 60)
        # The same size, different rows: the cap's atomic rewrite, or a
        # hand edit — nothing about the old prefix may be trusted.
        text = self.path.read_text(encoding="utf-8").replace('"r1"', '"q1"')
        self.path.write_text(text, encoding="utf-8")
        self.assertIn("q1", {r["id"] for r in outcomes.load_rows()})
        self.assertIn("q1", {i["id"] for i in outcomes.graded_items(T0 + 60)})
        self.path.write_text(line(look_row(99)), encoding="utf-8")
        self.assertEqual([r["id"] for r in outcomes.load_rows()], ["r99"])
        self.assertEqual([i["id"] for i in outcomes.graded_items(T0 + 60)],
                         ["r99"])
        self.path.unlink()
        self.assertEqual(outcomes.load_rows(), [])
        self.assertEqual(outcomes.graded_items(T0 + 60), [])

    def test_the_stores_it_joins_invalidate_it(self):
        now = T0 + 3600
        before = {i["id"]: i["outcome"] for i in outcomes.graded_items(now)}
        self.assertEqual(before["r2"], "cleared")
        # A live row with the same id and key: still pending.
        self.findings.append({"ts": T0 + 2, "text": "row 2",
                              "entity_id": "binary_sensor.s2", "triage": {}})
        mid = {i["id"]: i["outcome"] for i in outcomes.graded_items(now)}
        self.assertEqual(mid["r2"], "pending")
        # Answered.
        self.settled.append({"key": "row 2", "kind": "fixed", "ts": T0 + 100,
                             "note": "done"})
        after = {i["id"]: i for i in outcomes.graded_items(now)}
        self.assertEqual(after["r2"]["outcome"], "confirmed")
        self.assertEqual(after["r2"]["note"], "done")
        self.assertEqual(list(after.values()),
                         outcomes.items(self.fresh(now)))

    def test_the_clock_crossing_stood_is_never_served_stale(self):
        # A passed-over live row nobody has answered: pending, then stood.
        self.findings.append({"ts": T0 + 1, "text": "row 1",
                              "entity_id": "binary_sensor.s1", "triage": {}})
        edge = T0 + 1 + outcomes.STOOD_AFTER_S
        for now in (T0 + 60, edge - 1, edge, edge + 1, edge + 0.5, T0 + 60,
                    edge + 86400):
            got = {i["id"]: i["outcome"] for i in outcomes.graded_items(now)}
            want = {i["id"]: i["outcome"]
                    for i in outcomes.items(self.fresh(now))}
            self.assertEqual(got, want, f"at {now - T0}")
        self.assertEqual(
            {i["id"]: i["outcome"] for i in outcomes.graded_items(edge + 1)}
            ["r1"], "stood")

    def test_a_line_being_written_is_read_once_it_is_whole(self):
        outcomes.load_rows()
        whole = line(look_row(41))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(whole[:25])
        self.assertEqual(len(outcomes.load_rows()), 40)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(whole[25:])
        rows = outcomes.load_rows()
        self.assertEqual(len(rows), 41)
        self.assertEqual(rows[-1]["id"], "r41")


if __name__ == "__main__":
    unittest.main()
