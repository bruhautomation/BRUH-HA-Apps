#!/usr/bin/env python3
"""Outcomes — the Resident's verdicts, graded against what the household did.

`panel/outcomes.py` keeps the log and does the grading; `server.py` hooks it
into the look, the investigation, the undo, the nightly loop and a replay.
Everything here is driven through those real paths — the real `_resident_tick`
over real stores with only the CLI stubbed (`test_resident_loop`'s fixture,
extended), the real `_end_finding` for an ending, the real facts store for a
judgement, the real capture directory for a replay — because a grading
written down from the same guess as the code is the failure this whole module
exists to end: the Resident's own tests passed for two releases on signal
dicts `signals.make` refused to build.

Three rules are shown refusing what they must refuse rather than described:

  * a judgement can never lower a safety signal below its floor — a quieter
    judgement on a leak sensor is in the prompt, the model answers `ignore`,
    and the verdict on record is still `act`;
  * a run that failed is never a verdict — a failed look writes no row, a
    failed investigation's row grades nothing;
  * nothing about a person's health or whereabouts becomes a judgement —
    the parser drops the sentence and a person scope is never a candidate.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
CORPUS = BASE_DIR / "tests" / "corpus"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import outcomes  # noqa: E402
import resident  # noqa: E402
import signals  # noqa: E402
from test_resident_loop import LoopCase, case_reply, reply  # noqa: E402

DAY = 86400.0


def look_row(**over) -> dict:
    """A verdict row in the shape `record_look` writes, for the pure join."""
    row = {"id": f"r{over.get('at', 0)}-{over.get('idx', 1)}", "at": 1000,
           "stage": "look", "run_id": "look-1", "tier": "haiku", "idx": 1,
           "kind": "check", "subject": "binary_sensor.hall",
           "entity": "binary_sensor.hall", "source": "check:dev.frozen",
           "verdict": "watch", "why": "", "forced": False, "fallback": False,
           "finding_ts": 0, "key": "", "flags": []}
    row.update(over)
    return row


def settled(key: str, kind: str, ts: int, note: str = "") -> dict:
    return {"key": key, "text": key, "kind": kind, "ts": ts, "note": note,
            "source": "check:dev.frozen", "source_title": ""}


# ---------------------------------------------------------------------------
# The join, pure
# ---------------------------------------------------------------------------

class TestTheJoin(unittest.TestCase):
    """`grade` over rows, findings and the settled ledger, with no I/O."""

    def test_a_surfaced_row_is_graded_by_its_ending(self):
        rows = [look_row(finding_ts=11, key="a", verdict="watch"),
                look_row(finding_ts=12, key="b", verdict="investigate",
                         idx=2)]
        graded = outcomes.grade(rows, [], [settled("a", "fixed", 2000),
                                           settled("b", "ignored", 2000,
                                                   "it is a cupboard")], 5000)
        by_key = {g["key"]: g for g in graded}
        self.assertEqual(by_key["a"]["outcome"], "confirmed")
        self.assertIs(by_key["a"]["agree"], True)
        self.assertEqual(by_key["b"]["outcome"], "wrong")
        self.assertIs(by_key["b"]["agree"], False)
        self.assertEqual(by_key["b"]["note"], "it is a cupboard")

    def test_an_ending_older_than_the_verdict_is_not_its_ending(self):
        """A key settled before the verdict is an older answer to an older
        row; reading it as this verdict's grade would be inventing one."""
        graded = outcomes.grade([look_row(finding_ts=11, key="a", at=5000)],
                                [], [settled("a", "ignored", 1000)], 9000)
        self.assertEqual(graded[0]["outcome"], "cleared")
        self.assertIsNone(graded[0]["agree"])

    def test_a_held_row_put_back_by_a_person_was_missed(self):
        rows = [look_row(finding_ts=11, key="a", verdict="ignore")]
        live = [{"ts": 11, "text": "a", "status": "open",
                 "triage": {"verdict": "held", "elevated_by_person": True}}]
        [g] = outcomes.grade(rows, live, [], 5000)
        self.assertEqual(g["class"], "dismissed")
        self.assertEqual(g["outcome"], "put_back")
        self.assertIs(g["agree"], False)

    def test_a_subject_confirmed_within_three_days_of_being_passed_over(self):
        """The ledger records no subject, so the key is mapped to one by
        what the log said about it — and the window is the window."""
        passed = look_row(at=1000, verdict="ignore", kind="state",
                          subject="sensor.freezer", entity="sensor.freezer",
                          source="eventbus")
        later = look_row(at=2000, finding_ts=50, key="freezer warm",
                         subject="sensor.freezer", entity="sensor.freezer",
                         idx=1, id="later")
        soon = outcomes.grade([passed, later], [],
                              [settled("freezer warm", "fixed", 1000 + 3600)],
                              1000 + 5 * DAY)
        self.assertEqual(soon[0]["outcome"], "missed")
        self.assertIs(soon[0]["agree"], False)
        late = outcomes.grade([passed, later], [],
                              [settled("freezer warm", "fixed",
                                       int(1000 + 4 * DAY))], 1000 + 5 * DAY)
        self.assertEqual(late[0]["outcome"], "stood")
        self.assertIsNone(late[0]["agree"])

    def test_pending_cleared_and_stood_are_three_answers(self):
        rows = [look_row(finding_ts=11, key="a", at=1000),        # still live
                look_row(finding_ts=12, key="b", at=1000, idx=2),  # gone
                look_row(at=1000, verdict="ignore", kind="state",
                         subject="light.x", idx=3)]                 # live sig
        live = [{"ts": 11, "text": "a", "status": "open", "triage": {}}]
        graded = outcomes.grade(rows, live, [], 1000 + 4 * DAY)
        self.assertEqual([g["outcome"] for g in graded],
                         ["pending", "cleared", "stood"])
        self.assertEqual([g["agree"] for g in graded], [None, None, None])

    def test_an_undone_fix_is_its_own_outcome(self):
        rows = [look_row(finding_ts=11, key="a", at=1000),
                {"id": "u", "at": 3000, "stage": "undone", "case_ts": 11,
                 "key": "a"}]
        [g] = outcomes.grade(rows, [], [settled("a", "fixed", 2000)], 9000)
        self.assertEqual(g["outcome"], "undone")
        self.assertIsNone(g["agree"])

    def test_a_fallback_verdict_is_never_graded(self):
        """Nobody said `watch` — the reply skipped it — so there is nothing
        to grade, whatever happened next."""
        [g] = outcomes.grade([look_row(finding_ts=11, key="a",
                                       fallback=True, forced=True)],
                             [], [settled("a", "ignored", 2000)], 9000)
        self.assertEqual(g["class"], "unjudged")
        self.assertIsNone(g["agree"])

    def test_one_card_is_one_item_however_many_verdicts_it_had(self):
        """A look elevates a row and an investigation rewrites it: counting
        both is how "4 of 4" becomes "8 of 8"."""
        rows = [look_row(finding_ts=11, key="a", at=1000),
                {**look_row(at=1000, finding_ts=11, case_ts=11, key="a"),
                 "stage": "investigate", "verdict": "refined", "id": "inv"}]
        graded = outcomes.grade(rows, [], [settled("a", "ignored", 2000)],
                                9000)
        its = outcomes.items(graded)
        self.assertEqual(len(its), 1)
        self.assertEqual(its[0]["stage"], "investigate")
        t = outcomes.tallies(its)["entity"]["binary_sensor.hall"]
        self.assertEqual((t["items"], t["wrong"]), (1, 1))

    def test_a_look_that_sent_a_signal_folds_into_its_investigation(self):
        rows = [look_row(at=1000, verdict="investigate", kind="state",
                         subject="sensor.f", entity="sensor.f",
                         source="eventbus"),
                {**look_row(at=1000, case_ts=77, key="f claim",
                            subject="sensor.f", entity="sensor.f",
                            source="eventbus", kind="state"),
                 "stage": "investigate", "verdict": "filed", "id": "inv"}]
        its = outcomes.items(outcomes.grade(
            rows, [], [settled("f claim", "fixed", 2000)], 9000))
        self.assertEqual(len(its), 1)
        self.assertEqual(its[0]["outcome"], "confirmed")

    def test_calibration_is_stated_confidence_against_the_confirmed_rate(self):
        rows = []
        ledger = []
        for i in range(6):
            key = f"k{i}"
            rows.append({**look_row(at=1000 + i, case_ts=100 + i, key=key),
                         "stage": "investigate", "verdict": "filed",
                         "confidence": 0.85, "id": f"i{i}"})
            ledger.append(settled(key, "fixed" if i < 4 else "ignored",
                                  5000))
        table = outcomes.calibration(outcomes.grade(rows, [], ledger, 9000))
        bucket = next(b for b in table if b["from"] == 0.8)
        self.assertEqual((bucket["labelled"], bucket["confirmed"]), (6, 4))
        self.assertAlmostEqual(bucket["rate"], 0.667, places=3)
        line = outcomes.calibration_line(table)
        self.assertIn("80–90% sure", line)
        self.assertIn("67%", line)
        self.assertIn("(4 of 6)", line)

    def test_a_bucket_below_the_floor_says_nothing(self):
        rows = [{**look_row(at=1000, case_ts=100, key="k"),
                 "stage": "investigate", "verdict": "filed",
                 "confidence": 0.95, "id": "i"}]
        table = outcomes.calibration(outcomes.grade(
            rows, [], [settled("k", "fixed", 5000)], 9000))
        self.assertEqual(outcomes.calibration_line(table), "")


# ---------------------------------------------------------------------------
# The log, through the real loop
# ---------------------------------------------------------------------------

class OutcomesLoop(LoopCase):
    """`test_resident_loop`'s fixture, plus a facts store and a capture
    directory of this test's own."""

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        (root / "memory").mkdir(parents=True, exist_ok=True)
        self.point("facts_store", FACTS_FILE=root / "memory" / "facts.json",
                   INGEST_STATE_FILE=root / "memory" / "facts-ingest.json")
        self.point("capture", CAPTURE_DIR=root / "capture")
        srv = self.server
        self.out = srv.outcomes
        self.fs = srv.findings_store
        self.facts = srv.facts_store
        self._env = os.environ.get("BRAIN_ASSIST_LEARNING")
        self._opts = srv.addon_options._options
        srv.addon_options._options = None
        os.environ.pop("BRAIN_ASSIST_LEARNING", None)
        srv.OUTCOMES_STATE.update({"running": False, "last_error": ""})

    def tearDown(self):
        if self._env is None:
            os.environ.pop("BRAIN_ASSIST_LEARNING", None)
        else:
            os.environ["BRAIN_ASSIST_LEARNING"] = self._env
        self.server.addon_options._options = self._opts
        super().tearDown()

    def end(self, ts: int, verb: str, note: str = "") -> None:
        """The real ending: `_end_finding`, the door every button uses."""
        srv = self.server
        finding = self.fs.get(ts)
        asyncio.run(srv._end_finding(finding, srv.FINDING_VERBS[verb], note))

    def file_row(self, text: str, entity: str = "binary_sensor.pantry",
                 source: str = "check:dev.frozen") -> dict:
        import triage
        [row] = self.fs.add_many(triage.gate([{
            "text": text, "detail": "last change 3 Sep", "severity": "warning",
            "entity_id": entity, "source": source,
            "source_title": "Sensors frozen"}]))
        return row

    def fresh_tick(self, now: float) -> dict:
        """A tick that is due for both a sweep and a look."""
        self.server.RESIDENT_STATE["last_look_at"] = 0.0
        self.server.RESIDENT_STATE["last_sweep_at"] = 0.0
        return self.tick(now)


class TestTheLogIsWrittenByTheLoop(OutcomesLoop):
    def test_a_look_writes_one_row_per_signal_with_its_rows_key(self):
        row = self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "a cupboard nobody opens"}],
                                run_id="look-a"))
        self.tick(time.time())
        [logged] = self.out.load_rows()
        self.assertEqual(logged["stage"], "look")
        self.assertEqual(logged["verdict"], "ignore")
        self.assertEqual(logged["finding_ts"], row["ts"])
        self.assertEqual(logged["key"], self.fs.normalize(row["text"]))
        self.assertEqual(logged["run_id"], "look-a")
        self.assertEqual(logged["entity"], "binary_sensor.pantry")
        self.assertEqual(logged["source"], "check:dev.frozen")
        self.assertEqual(logged["tier"], resident.tier_for("first_look"))
        self.assertEqual(logged["why"], "a cupboard nobody opens")

    def test_a_look_that_did_not_come_back_writes_no_verdict(self):
        """A run that failed is never a verdict."""
        self.file_check_row()
        out = self.tick(time.time())    # no reply queued: the run fails
        self.assertTrue(out["looked"])
        self.assertEqual(self.out.load_rows(), [])

    def test_held_then_put_back_is_graded_as_a_wrong_call(self):
        row = self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "nothing"}]))
        self.tick(time.time())
        self.assertEqual(self.fs.get(row["ts"])["status"], "held")
        self.fs.elevate(row["ts"])
        [g] = self.out.load_graded()
        self.assertEqual(g["outcome"], "put_back")
        self.assertIs(g["agree"], False)

    def test_an_ending_grades_the_look_that_surfaced_the_row(self):
        wrong = self.file_row("The pantry contact has not changed in 9 days")
        right = self.file_row("The loft contact has not changed in 9 days",
                              entity="binary_sensor.loft")
        self.looks.append(reply([{"id": 1, "verdict": "watch", "why": "?"},
                                 {"id": 2, "verdict": "watch", "why": "?"}]))
        self.tick(time.time())
        self.end(wrong["ts"], "wrong", "it is a cupboard nobody opens")
        self.end(right["ts"], "done")
        graded = {g["finding_ts"]: g for g in self.out.load_graded()}
        self.assertEqual(graded[wrong["ts"]]["outcome"], "wrong")
        self.assertEqual(graded[wrong["ts"]]["note"],
                         "it is a cupboard nobody opens")
        self.assertIs(graded[wrong["ts"]]["agree"], False)
        self.assertEqual(graded[right["ts"]]["outcome"], "confirmed")
        self.assertIs(graded[right["ts"]]["agree"], True)

    def test_an_investigation_that_files_a_case_is_logged_and_graded(self):
        now = time.time()
        self.server._resident_offer(signals.make(
            "state", "sensor.garage_freezer", now=now, source="eventbus",
            text="Garage freezer -12 → -6", salience=0.6,
            evidence=[signals.evidence_row("sensor.garage_freezer", "-6",
                                           now)]))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "a freezer warming"}]))
        self.investigations.append(case_reply())
        self.fresh_tick(now)
        inv = [r for r in self.out.load_rows() if r["stage"] == "investigate"]
        self.assertEqual(len(inv), 1, self.out.load_rows())
        self.assertEqual(inv[0]["verdict"], "filed")
        self.assertEqual(inv[0]["confidence"], 0.8)
        self.assertEqual(inv[0]["asked"], "a freezer warming")
        case = self.fs.get(inv[0]["case_ts"])
        self.assertEqual(inv[0]["key"], self.fs.normalize(case["text"]))
        self.end(case["ts"], "wrong", "it was defrosting on purpose")
        its = self.out.items(self.out.load_graded())
        self.assertEqual(len(its), 1, "the look that sent it folds in")
        self.assertEqual(its[0]["outcome"], "wrong")

    def test_a_failed_investigation_is_logged_and_grades_nothing(self):
        now = time.time()
        self.server._resident_offer(signals.make(
            "state", "sensor.garage_freezer", now=now, source="eventbus",
            text="Garage freezer -12 → -6", salience=0.6))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "a freezer warming"}]))
        # No investigation queued: the analyst stub answers a failure.
        self.fresh_tick(now)
        inv = [g for g in self.out.load_graded()
               if g["stage"] == "investigate"]
        self.assertEqual([g["verdict"] for g in inv], ["failed"])
        self.assertEqual(inv[0]["class"], "unjudged")
        self.assertIsNone(inv[0]["agree"])

    def test_a_refined_row_later_marked_wrong(self):
        row = self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "worth a look"}]))
        self.investigations.append(case_reply(
            claim="The pantry contact is stuck", stakes="medium",
            evidence=[{"entity": "binary_sensor.pantry", "value": "off",
                       "when": "3 Sep"}]))
        self.fresh_tick(time.time())
        refined = [r for r in self.out.load_rows()
                   if r["stage"] == "investigate"]
        self.assertEqual([r["verdict"] for r in refined], ["refined"])
        self.assertEqual(refined[0]["case_ts"], row["ts"])
        self.end(row["ts"], "wrong", "it is a cupboard")
        its = self.out.items(self.out.load_graded())
        self.assertEqual(len(its), 1)
        self.assertEqual((its[0]["verdict"], its[0]["outcome"]),
                         ("refined", "wrong"))

    def test_the_verdict_log_never_takes_the_loop_down(self):
        """A log that cannot be written is a log with a hole in it, never a
        look that fell over."""
        blocker = Path(self.tmp.name) / "not-a-dir"
        blocker.write_text("x")
        self.point("outcomes", VERDICTS_FILE=blocker / "verdicts.jsonl")
        row = self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "nothing"}]))
        out = self.tick(time.time())
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.fs.get(row["ts"])["status"], "held")


class TestTheLogIsCapped(unittest.TestCase):
    """Capped by rewriting only when well past the cap, and through
    `atomic_write` — the journal's arithmetic, driven."""

    def test_the_oldest_rows_go_and_the_newest_stay(self):
        with tempfile.TemporaryDirectory() as tmp:
            olds = (outcomes.VERDICTS_FILE, outcomes.MAX_ROWS)
            outcomes.VERDICTS_FILE = Path(tmp) / "v.jsonl"
            outcomes.MAX_ROWS = 20
            try:
                for i in range(40):
                    outcomes.note_undone(i, f"row {i}", now=1000 + i)
                rows = outcomes.load_rows()
                self.assertLessEqual(len(rows), 20 + 20 // 4)
                self.assertEqual(rows[-1]["case_ts"], 39)
                self.assertGreater(rows[0]["case_ts"], 0)
            finally:
                outcomes.VERDICTS_FILE, outcomes.MAX_ROWS = olds

    def test_a_result_nobody_wrote_down_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = outcomes.VERDICTS_FILE
            outcomes.VERDICTS_FILE = Path(tmp) / "v.jsonl"
            try:
                self.assertFalse(outcomes.record_investigation(
                    {"subject": "x"}, "maybe"))
                self.assertEqual(outcomes.load_rows(), [])
            finally:
                outcomes.VERDICTS_FILE = old


class TestAnUndoIsRecorded(OutcomesLoop):
    def test_the_unfix_route_writes_the_undone_event(self):
        """Through the real route: `unfix` puts the row back to `open` and
        no store keeps that a person reversed brAIn's change — so the hook
        is the only record, and the join reads it."""
        import actions
        import automation_writer
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        root = Path(self.tmp.name)
        olds = (automation_writer.JOURNAL_DIR, automation_writer.SNAP_DIR,
                automation_writer.INDEX, actions.LEDGER_FILE)
        automation_writer.JOURNAL_DIR = root / "edits"
        automation_writer.SNAP_DIR = root / "edits" / "snapshots"
        automation_writer.INDEX = root / "edits" / "index.jsonl"
        actions.LEDGER_FILE = str(root / "actions.jsonl")
        row = self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "watch", "why": "?"}]))
        self.tick(time.time())
        self.fs.set_fix_window(row["ts"], started=time.time() - 60,
                               ended=time.time() - 30)
        self.fs.set_status(row["ts"], "fixed", result="done")
        app = web.Application()
        app.router.add_post("/api/finding/{ts}/unfix",
                            self.server.h_finding_unfix)

        async def run():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                resp = await client.post(f"/api/finding/{row['ts']}/unfix")
                self.assertEqual(resp.status, 200, await resp.text())
            finally:
                await client.close()

        try:
            asyncio.run(run())
        finally:
            (automation_writer.JOURNAL_DIR, automation_writer.SNAP_DIR,
             automation_writer.INDEX, actions.LEDGER_FILE) = olds
        undone = [r for r in self.out.load_rows() if r["stage"] == "undone"]
        self.assertEqual([r["case_ts"] for r in undone], [row["ts"]])
        graded = [g for g in self.out.load_graded() if g["stage"] == "look"]
        self.assertEqual(graded[0]["outcome"], "undone")


# ---------------------------------------------------------------------------
# Worked examples
# ---------------------------------------------------------------------------

class TestWorkedExamples(OutcomesLoop):
    def test_the_next_look_is_shown_what_the_household_said(self):
        first = self.file_row("The pantry contact has not changed in 9 days")
        self.looks.append(reply([{"id": 1, "verdict": "watch",
                                  "why": "might be stuck"}]))
        self.tick(time.time())
        self.end(first["ts"], "wrong", "it is on a cupboard nobody opens")
        self.file_row("The pantry contact has not changed in 12 days")
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "the cupboard again"}]))
        self.fresh_tick(time.time())
        prompt = self.look_calls[-1]["prompt"]
        self.assertIn("PAST CALLS LIKE THESE", prompt)
        self.assertIn("said it was not a problem", prompt)
        self.assertIn("it is on a cupboard nobody opens", prompt)
        self.assertIn("[wrong call]", prompt)

    def test_an_investigation_is_shown_examples_and_its_calibration(self):
        self.facts.add("When an investigation stated its confidence, at "
                       "80–90% sure, the homeowner agreed 61% of the time "
                       "(11 of 18).", subject=outcomes.CALIBRATION_SUBJECT,
                       source="resident",
                       predicate=outcomes.CALIBRATION_PREDICATE)
        now = time.time()
        self.server._resident_offer(signals.make(
            "state", "sensor.garage_freezer", now=now, source="eventbus",
            text="Garage freezer -12 → -6", salience=0.6))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "a freezer warming"}]))
        self.investigations.append(case_reply())
        self.fresh_tick(now)
        prompt = self.analyst_calls[0]["prompt"]
        self.assertIn("Your own calibration", prompt)
        self.assertIn("61% of the time", prompt)

    def test_same_subject_beats_same_producer_beats_kind_and_domain(self):
        sig = {"kind": "check", "subject": "binary_sensor.pantry",
               "source": "check:dev.frozen"}
        base = {"outcome": "wrong", "agree": False, "kind": "check",
                "at": 100}
        its = [
            {**base, "id": "dom", "item": "a", "subject": "binary_sensor.x",
             "entity": "binary_sensor.x", "source": "check:other"},
            {**base, "id": "src", "item": "b", "subject": "sensor.y",
             "entity": "sensor.y", "source": "check:dev.frozen"},
            {**base, "id": "same", "item": "c",
             "subject": "binary_sensor.pantry",
             "entity": "binary_sensor.pantry", "source": "check:x"},
            {**base, "id": "none", "item": "d", "subject": "light.z",
             "entity": "light.z", "source": "eventbus", "kind": "state"},
        ]
        got = [it["id"] for it in outcomes.similar(sig, 8, its)]
        self.assertEqual(got, ["same", "src", "dom"])

    def test_an_answered_call_outranks_one_nobody_contradicted(self):
        sig = {"kind": "state", "subject": "light.hall", "source": "eventbus"}
        its = [{"id": "s", "item": "s", "subject": "light.hall",
                "outcome": "stood", "agree": None, "at": 900},
               {"id": "w", "item": "w", "subject": "light.hall",
                "outcome": "wrong", "agree": True, "at": 100}]
        self.assertEqual([i["id"] for i in outcomes.similar(sig, 2, its)],
                         ["w", "s"])

    def test_the_block_is_bounded_twice(self):
        its = [{"id": f"i{n}", "item": f"i{n}", "kind": "check",
                "subject": "binary_sensor.pantry", "outcome": "wrong",
                "agree": False, "at": 1000 + n, "verdict": "watch",
                "why": "x" * 200, "note": "y" * 200} for n in range(40)]
        sig = {"kind": "check", "subject": "binary_sensor.pantry"}
        lines = outcomes.examples_for([sig], graded_items=its)
        self.assertLessEqual(len(lines), outcomes.EXAMPLES_K)
        self.assertLessEqual(sum(len(x) + 1 for x in lines),
                             outcomes.EXAMPLES_CHARS)
        block = resident._examples_block(["z" * 500] * 30)
        self.assertLessEqual(len(block) - 2, resident.MAX_EXAMPLES)


# ---------------------------------------------------------------------------
# Reflect, and its guardrails
# ---------------------------------------------------------------------------

def judged_item(subject, outcome, *, kind="state", source="eventbus",
                klass="surfaced", flags=(), ended=2000, note="", why=""):
    agree = {"confirmed": True, "wrong": False}.get(outcome) \
        if klass == "surfaced" else {"wrong": True, "missed": False,
                                     "put_back": False}.get(outcome)
    return {"id": f"{subject}{ended}", "item": f"{subject}{ended}",
            "class": klass, "outcome": outcome, "agree": agree,
            "subject": subject, "entity": subject, "kind": kind,
            "source": source, "flags": list(flags), "ended_at": ended,
            "note": note, "why": why, "at": ended - 100}


class TestCandidates(unittest.TestCase):
    def scopes(self, its):
        return outcomes.tallies(its)

    def test_a_lopsided_record_is_a_quieter_candidate_with_code_counts(self):
        its = [judged_item("binary_sensor.hall_motion", "wrong", ended=2000 + i,
                           note="it's the cat") for i in range(4)]
        [cand] = outcomes.candidates(self.scopes(its))
        self.assertEqual((cand["scope"], cand["direction"]),
                         ("entity", "quieter"))
        self.assertEqual(cand["counts"],
                         "4 of 4 it raised were marked not a problem")
        self.assertIn("it's the cat", cand["notes"])

    def test_no_judgement_may_make_a_safety_protected_or_hot_scope_quieter(self):
        for flag in ("safety", "protected", "hot"):
            with self.subTest(flag):
                its = [judged_item("binary_sensor.kitchen_leak", "wrong",
                                   flags=[flag], ended=2000 + i)
                       for i in range(5)]
                self.assertEqual(outcomes.candidates(self.scopes(its)), [])

    def test_a_safety_check_scope_is_never_quieter(self):
        its = [judged_item("sensor.pipe", "wrong", kind="check",
                           source="check:climate.freeze", ended=2000 + i)
               for i in range(5)]
        cands = outcomes.candidates(self.scopes(its))
        self.assertNotIn("check:climate.freeze",
                         [c["subject"] for c in cands])

    def test_a_person_is_never_a_scope(self):
        its = [judged_item("person.ben", "wrong", kind="presence",
                           ended=2000 + i) for i in range(5)]
        its += [judged_item("device_tracker.phone", "missed",
                            klass="dismissed", ended=2000 + i)
                for i in range(5)]
        self.assertEqual(outcomes.candidates(self.scopes(its)), [])

    def test_a_confirmed_case_after_the_wrongs_ends_the_pattern(self):
        its = [judged_item("binary_sensor.hall_motion", "wrong",
                           ended=2000 + i) for i in range(6)]
        its.append(judged_item("binary_sensor.hall_motion", "confirmed",
                               ended=9000))
        self.assertEqual(outcomes.candidates(self.scopes(its)), [])

    def test_things_passed_over_that_mattered_are_a_louder_candidate(self):
        its = [judged_item("sensor.freezer", "missed", klass="dismissed",
                           ended=2000 + i) for i in range(3)]
        [cand] = outcomes.candidates(self.scopes(its))
        self.assertEqual(cand["direction"], "louder")
        self.assertIn("3 of 3 it passed over turned out to matter",
                      cand["counts"])


class TestParseReflect(unittest.TestCase):
    CANDS = [{"scope": "entity", "subject": "binary_sensor.hall_motion",
              "direction": "quieter", "counts": "4 of 4"},
             {"scope": "check", "subject": "check:dev.frozen",
              "direction": "quieter", "counts": "5 of 6"}]

    def parse(self, lessons):
        return outcomes.parse_reflect({"lessons": lessons}, self.CANDS)

    def test_a_good_lesson_survives(self):
        got = self.parse([{"id": 1, "lesson": "Night motion on the hall "
                                              "landing is the cat."}])
        self.assertEqual(got, {1: "Night motion on the hall landing is the "
                                  "cat"})

    def test_what_a_lesson_may_not_say(self):
        refused = {
            "health": "Ben is ill at night",
            "sleep": "Somebody sleeps badly",
            "whereabouts": "Nobody home at that hour",
            "counts": "Four of 4... 4 of 4 were wrong",
            "percent": "Wrong 80% of the time",
            "foreign id": "It is really sensor.other_thing",
            "long": "x " * 200,
            "empty": "",
        }
        for why, lesson in refused.items():
            with self.subTest(why):
                self.assertEqual(self.parse([{"id": 1, "lesson": lesson}]),
                                 {})

    def test_its_own_scope_may_be_named(self):
        got = self.parse([{"id": 2, "lesson": "dev.frozen misreads the "
                                              "cupboard contacts"}])
        self.assertIn(2, got)

    def test_an_index_outside_the_list_or_repeated_is_dropped(self):
        got = self.parse([{"id": 3, "lesson": "nope"},
                          {"id": 1, "lesson": "the cat"},
                          {"id": 1, "lesson": "a second answer"}])
        self.assertEqual(got, {1: "the cat"})

    def test_an_unreadable_reply_is_no_lessons(self):
        self.assertEqual(outcomes.parse_reflect("not json", self.CANDS), {})
        self.assertEqual(outcomes.parse_reflect({"x": 1}, self.CANDS), {})


class TestTheNightlyPass(OutcomesLoop):
    def plant_wrongs(self, entity="binary_sensor.hall_motion", n=4,
                     note="it's the cat on the landing"):
        """N rows a look surfaced and a person marked wrong, for real."""
        for i in range(n):
            row = self.file_row(f"Hall motion fired at 03:1{i} with nobody "
                                "up", entity=entity)
            self.looks.append(reply([{"id": 1, "verdict": "watch",
                                      "why": "motion at night"}]))
            self.fresh_tick(time.time())
            self.end(row["ts"], "wrong", note)

    def nightly(self):
        return asyncio.run(self.server._outcomes_nightly(time.time(),
                                                         force=True))

    def test_reflect_writes_a_scoped_judgement_with_the_codes_counts(self):
        self.plant_wrongs()
        calls = []
        import engine

        def run_claude(prompt, system, *a, **k):
            calls.append({"prompt": prompt, "system": system, "args": a, **k})
            # Answer the entity's pattern and leave the rule's empty — which
            # number each one got is the prompt's to say, so it is read off
            # the prompt rather than assumed.
            lessons = []
            for line in prompt.splitlines():
                head, _, rest = line.partition(". ")
                if not head.isdigit():
                    continue
                lessons.append({"id": int(head), "lesson": (
                    "Night motion on the hall landing is the cat"
                    if "binary_sensor.hall_motion" in rest else "")})
            return {"ok": True, "error": "", "meta": {"session_id": "refl-1"},
                    "text": json.dumps({"lessons": lessons})}

        engine.run_claude = run_claude
        state = self.nightly()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["job"], "reflect")
        self.assertEqual(calls[0]["schema"], outcomes.REFLECT_SCHEMA)
        self.assertEqual(calls[0]["system"], outcomes.REFLECT_SYSTEM)
        self.assertEqual(calls[0]["args"][3], "resident")
        self.assertIn("it's the cat on the landing", calls[0]["prompt"])
        judged = outcomes.judgement_rows(
            self.facts.with_predicate(outcomes.JUDGEMENT_PREFIX))
        self.assertEqual(len(judged), 1, judged)
        fact = judged[0]
        self.assertEqual(fact["predicate"], "judgement:entity:quieter")
        self.assertEqual(fact["subject"], "binary_sensor.hall_motion")
        self.assertIn("is the cat", fact["text"])
        self.assertIn("4 of 4 it raised were marked not a problem",
                      fact["text"])
        self.assertEqual(fact["run_id"], "refl-1")
        self.assertTrue(fact["expires"])
        self.assertEqual(state["reflect"]["written"], 1)
        self.assertEqual(state["judgements"], 1)

    def test_a_judgement_reaches_the_next_look_through_memory_retrieval(self):
        self.facts.add("Learned from the homeowner's answers (quieter): the "
                       "cupboard contact never moves — 4 of 4 it raised were "
                       "marked not a problem.",
                       subject="check:dev.frozen", source="resident",
                       predicate="judgement:check:quieter", confidence=0.9)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "per the judgement"}]))
        self.tick(time.time())
        self.assertIn("the cupboard contact never moves",
                      self.look_calls[-1]["prompt"])

    def test_no_judgement_lowers_a_safety_signal_below_its_floor(self):
        """The judgement is in the prompt, the model obeys it, and the
        verdict on record is still `act`: the floor is applied after
        anything the model says."""
        self.facts.add("Learned from the homeowner's answers (quieter): the "
                       "kitchen leak sensor trips on the dishwasher — 9 of 9 "
                       "it raised were marked not a problem.",
                       subject="binary_sensor.kitchen_leak",
                       source="resident", predicate="judgement:entity:quieter",
                       confidence=0.9)
        now = time.time()
        self.server.RESIDENT_STATE["last_look_at"] = now - 120
        self.server._resident_offer(signals.from_state_change(
            {"entity_id": "binary_sensor.kitchen_leak",
             "old_state": {"state": "off"},
             "new_state": {"state": "on", "attributes": {
                 "device_class": "moisture",
                 "friendly_name": "Kitchen leak"}}},
            signals.RegistryContext(), now))
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "the judgement says it is nothing"}]))
        self.tick(now)
        self.assertIn("trips on the dishwasher", self.look_calls[-1]["prompt"])
        [row] = self.out.load_rows()
        self.assertEqual(row["verdict"], "act")
        self.assertTrue(row["forced"])
        self.assertIn("safety", row["flags"])

    def test_the_gates_hold_reflect_and_never_the_free_half(self):
        self.plant_wrongs()
        import engine
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": False})

        def boom(*a, **k):
            raise AssertionError("reflect ran with automatic runs paused")

        engine.run_claude = boom
        state = self.nightly()
        self.assertEqual(state["reflect"]["held"],
                         "automatic runs are paused")
        self.assertFalse(state["reflect"]["ran"])
        self.assertTrue(state["joined_at"])
        self.assertEqual(state["summary"]["rows"], 4)

    def test_learning_off_writes_no_judgement(self):
        self.plant_wrongs()
        os.environ["BRAIN_ASSIST_LEARNING"] = "false"
        import engine

        def boom(*a, **k):
            raise AssertionError("reflect ran with learning switched off")

        engine.run_claude = boom
        state = self.nightly()
        self.assertEqual(state["reflect"]["held"], "learning is switched off")
        self.assertEqual(self.facts.with_predicate(outcomes.JUDGEMENT_PREFIX),
                         [])

    def test_a_confirmed_case_on_its_scope_supersedes_a_quieter_judgement(self):
        self.plant_wrongs()
        self.facts.add("Learned from the homeowner's answers (quieter): hall "
                       "motion at night is the cat — 4 of 4.",
                       subject="binary_sensor.hall_motion", source="resident",
                       predicate="judgement:entity:quieter", confidence=0.9,
                       ts=time.time() - 60)
        row = self.file_row("Hall motion at 03:40 and the back door open",
                            entity="binary_sensor.hall_motion")
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "?"}]))
        self.fresh_tick(time.time())
        self.end(row["ts"], "done")
        import engine
        engine.run_claude = lambda *a, **k: {"ok": False, "error": "x",
                                             "meta": {}}
        state = self.nightly()
        self.assertEqual(state["superseded"], 1)
        self.assertEqual(outcomes.judgement_rows(
            self.facts.with_predicate(outcomes.JUDGEMENT_PREFIX)), [])

    def test_a_failed_reflect_run_writes_nothing_and_says_so(self):
        self.plant_wrongs()
        import engine
        engine.run_claude = lambda *a, **k: {"ok": False, "error": "529",
                                             "meta": {}}
        state = self.nightly()
        self.assertEqual(state["reflect"]["ok"], False)
        self.assertIn("529", state["reflect"]["error"])
        self.assertEqual(outcomes.judgement_rows(
            self.facts.with_predicate(outcomes.JUDGEMENT_PREFIX)), [])

    def test_the_calibration_line_is_written_by_code(self):
        rows = []
        for i in range(6):
            key = f"claim {i}"
            rows.append({**look_row(at=int(time.time()) - 100, case_ts=900 + i,
                                    key=key), "stage": "investigate",
                         "verdict": "filed", "confidence": 0.85,
                         "id": f"c{i}"})
        self.out._append(rows)
        for i in range(6):
            self.fs._remember_settled({"text": f"claim {i}"},
                                      "fixed" if i < 3 else "ignored")
        import engine
        engine.run_claude = lambda *a, **k: {"ok": False, "error": "x",
                                             "meta": {}}
        self.nightly()
        [cal] = self.facts.with_predicate(outcomes.CALIBRATION_PREDICATE)
        self.assertIn("50% of the time (3 of 6)", cal["text"])
        self.assertEqual(cal["subject"], outcomes.CALIBRATION_SUBJECT)

    def test_the_join_is_once_a_day(self):
        self.out.save_state({"joined_at": int(time.time()) - 3600})
        got = asyncio.run(self.server._outcomes_nightly(time.time()))
        self.assertIn("skipped", got)

    def test_diagnostics_carry_the_row(self):
        self.plant_wrongs(n=1)
        diag = self.server._outcomes_diagnostics()
        self.assertEqual(diag["log_rows"], 1)
        self.assertIn("reflect", diag)
        payload = self.server._diagnostics_payload()
        self.assertIn("outcomes", payload)


# ---------------------------------------------------------------------------
# First-look capture and replay
# ---------------------------------------------------------------------------

class TestFirstLookCapture(OutcomesLoop):
    def capture_on(self, on=True):
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "capture": on})

    def test_capture_off_writes_nothing(self):
        self.capture_on(False)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "x"}],
                                run_id="look-off"))
        self.tick(time.time())
        self.assertEqual(self.server.capture.first_looks(), [])

    def test_a_captured_look_is_replayable_and_labelled_nightly(self):
        self.capture_on()
        row = self.file_row("The pantry contact has not changed in 9 days "
                            "sk-ant-oat01-ABCDEFGHIJKLMNOPQRSTUVWX")
        self.looks.append(reply([{"id": 1, "verdict": "watch", "why": "x"}],
                                run_id="look-cap"))
        self.tick(time.time())
        [entry] = self.server.capture.first_looks()
        self.assertEqual(entry["kind"], "first_look")
        self.assertEqual(entry["run_id"], "look-cap")
        self.assertEqual(entry["reply"]["verdicts"][0]["verdict"], "watch")
        self.assertIn("memory", entry["inputs"])
        self.assertIn("now_line", entry["inputs"])
        self.assertNotIn("sk-ant-oat01", json.dumps(entry),
                         "redacted on the way in")
        self.end(row["ts"], "wrong")
        import engine
        engine.run_claude = lambda *a, **k: {"ok": False, "error": "x",
                                             "meta": {}}
        state = asyncio.run(self.server._outcomes_nightly(time.time(),
                                                          force=True))
        self.assertEqual(state["captures_labelled"], 1)
        [entry] = self.server.capture.first_looks()
        self.assertEqual(entry["labels"], [{"signal": 1, "outcome": "wrong",
                                            "ceiling": "ignore"}])
        # And the replay rebuilds it with today's builder: the same batch,
        # the same clock, the same memory it was given.
        prompt = outcomes.replay_prompt(entry)
        self.assertIn("The pantry contact has not changed", prompt)
        self.assertIn(entry["inputs"]["now_line"], prompt)


class TestTheReplay(OutcomesLoop):
    def labelled_capture(self, run_id, n=2):
        batch = [signals.make("state", f"light.x{i}", now=1000.0,
                              source="eventbus", text=f"light {i} on")
                 for i in range(n)]
        self.server.capture.record_first_look(
            run_id, batch=batch, inputs={}, reply={"verdicts": [
                {"id": i, "verdict": "watch", "why": ""}
                for i in range(1, n + 1)]}, now=time.time())
        self.server.capture.label_first_look(
            run_id, [{"signal": i, "ceiling": "watch", "outcome": "wrong"}
                     for i in range(1, n + 1)])

    def app(self):
        from aiohttp import web
        app = web.Application()
        app.router.add_get("/api/resident/eval",
                           self.server.h_resident_eval_get)
        app.router.add_post("/api/resident/eval",
                            self.server.h_resident_eval_start)
        app.router.add_get("/api/resident/outcomes",
                           self.server.h_resident_outcomes)
        return app

    def drive(self, body):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            client = TestClient(TestServer(self.app()))
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()

        return asyncio.run(run())

    async def finish(self, client):
        for _ in range(200):
            data = await (await client.get("/api/resident/eval")).json()
            if not data["running"]:
                return data
            await asyncio.sleep(0.02)
        raise AssertionError("the replay never finished")

    def setUp(self):
        super().setUp()
        self.server.EVAL_STATE.update({"starting": False, "report": None,
                                       "error": ""})
        import engine
        self.asked = []

        def run_claude(prompt, system, *a, **k):
            self.asked.append(k)
            return {"ok": True, "error": "", "meta": {"session_id": "r"},
                    "text": json.dumps({"verdicts": [
                        {"id": 1, "verdict": "ignore", "why": ""},
                        {"id": 2, "verdict": "investigate", "why": ""}]})}

        engine.run_claude = run_claude

    def test_with_nothing_labelled_it_says_what_to_do_and_spends_nothing(self):
        async def body(client):
            resp = await client.post("/api/resident/eval", json={})
            self.assertEqual(resp.status, 409)
            self.assertIn("capture", (await resp.json())["error"])

        self.drive(body)
        self.assertEqual(self.asked, [])

    def test_a_replay_reports_agreement_now_and_then(self):
        self.labelled_capture("cap-1")

        async def body(client):
            resp = await client.post("/api/resident/eval", json={"days": 3})
            self.assertEqual(resp.status, 200, await resp.text())
            return await self.finish(client)

        data = self.drive(body)
        total = data["report"]["total"]
        self.assertEqual((total["labels"], total["agreed"]), (2, 1))
        self.assertEqual(total["then_agreement"], 1.0)
        self.assertIn("never automatic", data["report"]["promotion"])
        self.assertEqual(self.asked[0]["job"], resident.JOB_FIRST_LOOK)
        self.assertEqual(self.asked[0]["schema"], resident.FIRST_LOOK_SCHEMA)

    def test_the_spend_cap_is_checked_before_a_run(self):
        self.labelled_capture("cap-1")
        self.labelled_capture("cap-2")
        self.server._record_usage = lambda result, name: {"total": 5000}

        async def body(client):
            resp = await client.post("/api/resident/eval",
                                     json={"max_tokens": 1})
            self.assertEqual(resp.status, 200)
            return await self.finish(client)

        data = self.drive(body)
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(data["report"]["skipped"], 1)

    def test_only_first_look_is_replayable(self):
        async def body(client):
            resp = await client.post("/api/resident/eval",
                                     json={"kind": "analyst"})
            self.assertEqual(resp.status, 400)

        self.drive(body)

    def test_no_credential_no_replay(self):
        import engine
        self.labelled_capture("cap-1")
        engine.get_auth = lambda: None

        async def body(client):
            resp = await client.post("/api/resident/eval", json={})
            self.assertEqual(resp.status, 409)

        self.drive(body)
        self.assertEqual(self.asked, [])

    def test_the_outcomes_route_grades_fresh(self):
        row = self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "watch", "why": "?"}]))
        self.tick(time.time())
        self.end(row["ts"], "wrong", "a cupboard")

        async def body(client):
            return await (await client.get("/api/resident/outcomes")).json()

        data = self.drive(body)
        self.assertEqual(data["by_outcome"]["wrong"], 1)
        self.assertIn("check:dev.frozen", data["tallies"]["source"])
        self.assertNotIn("notes", data["tallies"]["source"]["check:dev.frozen"])


class TestScoringALook(unittest.TestCase):
    def test_floors_ceilings_and_the_safety_count(self):
        leak = signals.from_state_change(
            {"entity_id": "binary_sensor.kitchen_leak",
             "old_state": {"state": "off"},
             "new_state": {"state": "on",
                           "attributes": {"device_class": "moisture"}}},
            signals.RegistryContext(), 1000.0)
        light = signals.make("state", "light.x", now=1000.0, text="on")
        verdicts = resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "ignore", "why": ""},
                          {"id": 2, "verdict": "act", "why": ""}]},
            2, [leak, light])
        got = outcomes.score_look([leak, light], verdicts,
                                  [{"signal": 1, "floor": "act"},
                                   {"signal": 2, "ceiling": "watch"}])
        self.assertEqual((got["agreed"], got["labels"]), (1, 2))
        self.assertEqual((got["safety"], got["safety_held"]), (1, 1))


# ---------------------------------------------------------------------------
# The corpus entry
# ---------------------------------------------------------------------------

class TestTheFirstLookCorpusEntry(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(CORPUS))
        import replay
        self.replay = replay
        self.entry = next(e for e in replay.load_entries()
                          if e["id"] == "first-look-rehearsal")

    def test_every_signal_is_the_shape_make_publishes(self):
        for sig in self.entry["batch"]:
            with self.subTest(sig["subject"]):
                self.assertEqual(set(sig), set(signals.SIGNAL_KEYS))
                self.assertIn(sig["kind"], signals.KINDS)

    def test_the_guard_holds_against_a_model_that_ignores_everything(self):
        got = self.replay.replay_first_look(self.entry, adversary=True)
        self.assertGreater(got["guard_labels"], 0)
        self.assertEqual(got["guard_held"], got["guard_labels"])
        self.assertEqual(got["safety_held"], got["safety"])
        self.assertGreaterEqual(got["safety"], 1)

    def test_the_free_replay_runs_it_without_a_model(self):
        report = self.replay.run([self.entry], checks_only=True)
        row = report["results"][0]
        self.assertTrue(row["adversary"])
        self.assertEqual(report["tokens"], 0)
        self.assertEqual(report["first_look"]["safety_held"],
                         report["first_look"]["safety"])

    def test_the_validator_takes_it_and_refuses_broken_ones(self):
        import test_corpus
        self.assertEqual(test_corpus.validate(self.entry), [])
        self.assertEqual(tuple(test_corpus.LOOK_VERDICTS), resident.VERDICTS)
        broken = {
            "no now": {k: v for k, v in self.entry.items() if k != "now"},
            "label past the batch": {**self.entry, "labels": [
                {"signal": 99, "floor": "watch"}]},
            "no bound": {**self.entry, "labels": [{"signal": 1}]},
            "bound not a verdict": {**self.entry, "labels": [
                {"signal": 1, "floor": "panic"}]},
            "no batch": {**self.entry, "batch": []},
        }
        for why, bad in broken.items():
            with self.subTest(why):
                self.assertTrue(test_corpus.validate(bad))


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

class TestTheCli(unittest.TestCase):
    SCRIPT = SCRIPTS / "brain-eval.sh"

    def block(self, name: str) -> str:
        import re
        src = self.SCRIPT.read_text(encoding="utf-8")
        match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", src, re.M | re.S)
        self.assertIsNotNone(match, f"{name} is gone from brain-eval.sh")
        return match.group(0)

    def run_block(self, name: str, payload: str):
        return subprocess.run(
            ["bash", "-c", "set -u\n" + self.block(name)
             + f"\n{name} \"$1\"\n", "x", payload],
            capture_output=True, text=True, timeout=30)

    def test_the_outcomes_report_prints(self):
        payload = json.dumps({
            "rows": 4, "items": 3,
            "by_outcome": {"wrong": 2, "confirmed": 1},
            "by_stage": {"look": {"agreed": 1, "disagreed": 2}},
            "calibration_line": "When an investigation …",
            "tallies": {"source": {"check:dev.frozen": {
                "items": 3, "confirmed": 1, "wrong": 2, "missed": 0}}},
            "judgements": [{"subject": "binary_sensor.hall",
                            "text": "the cat — 4 of 4"}],
            "candidates": [], "state": {"reflect": {"held": "paused"}}})
        proc = self.run_block("print_outcomes", payload)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("2 wrong", proc.stdout)
        self.assertIn("check:dev.frozen: 1 / 2 / 0 of 3", proc.stdout)
        self.assertIn("the cat — 4 of 4", proc.stdout)
        self.assertIn("Last reflect run held: paused", proc.stdout)

    def test_a_replay_that_left_safety_below_its_floor_fails_loudly(self):
        payload = json.dumps({"running": False, "report": {
            "total": {"batches": 1, "labels": 2, "agreed": 1,
                      "agreement": 0.5, "then_agreement": 1.0,
                      "safety": 1, "safety_held": 0, "tokens": 10},
            "rows": [], "promotion": "never automatic"}})
        proc = self.run_block("print_replay", payload)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("SAFETY SIGNAL", proc.stdout)
        self.assertIn("1/2 (50%)", proc.stdout)

    def test_a_torn_payload_is_an_error_not_a_traceback(self):
        for name in ("print_outcomes", "print_replay"):
            proc = self.run_block(name, "not json")
            self.assertEqual(proc.returncode, 1)
            self.assertNotIn("Traceback", proc.stderr)

    def test_the_dispatcher_routes_eval(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                ["bash", str(SCRIPTS / "brain.sh"), "eval", "help"],
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "BRAIN_SCRIPTS_DIR": str(SCRIPTS),
                     "HOME": tmp})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("brain eval first_look", proc.stdout)
        self.assertIn("never automatic", proc.stdout)

    def test_no_python_dash_c_and_no_pipe_into_a_heredoc(self):
        src = self.SCRIPT.read_text(encoding="utf-8")
        self.assertFalse([ln for ln in src.splitlines()
                          if "python3 -c" in ln and not ln.lstrip().startswith("#")])
        self.assertFalse([ln for ln in src.splitlines()
                          if "|" in ln and "python3 - " in ln])


class TestTheReflectJobIsPlanned(unittest.TestCase):
    def test_reflect_is_the_cheap_tier_and_cannot_step_up(self):
        import model_plan
        tier, _effort, _down, up = model_plan.JOBS["reflect"]
        self.assertEqual(tier, "haiku")
        self.assertFalse(up)
        self.assertEqual(model_plan.resolve("reflect", "generous")[0], "haiku")


if __name__ == "__main__":
    unittest.main()
