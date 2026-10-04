#!/usr/bin/env python3
"""Every applied fix is looked at again — and "could not check" is not a pass.

The ledger's own rules are driven over a real file, and the follow-up tick
is driven through the server with Core stubbed at `ha_data` and the model
stubbed at `engine.run_analyst`, because "a regression reopens the case and
cites the intervention" is a claim about the findings store and only a run
into the real store proves it.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import interventions  # noqa: E402

from test_todo_list import PanelCase  # noqa: E402

DAY = 86400


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = interventions.FILE
        interventions.FILE = Path(self.tmp.name) / "interventions.jsonl"

    def tearDown(self):
        interventions.FILE = self._old
        self.tmp.cleanup()

    def applied(self, at, **extra):
        return interventions.record({"id": f"fix-1-{int(at)}",
                                     "applied_at": at, "finding_ts": 1,
                                     "finding_text": "it broke",
                                     "finding_key": "it broke", **extra},
                                    now=at)


class TestTheLedger(LedgerCase):
    def test_looks_come_due_in_order_after_a_day_a_week_and_a_month(self):
        t0 = 1_000_000.0
        row = self.applied(t0)
        self.assertEqual(interventions.due(t0 + DAY - 1), [])
        self.assertEqual([d for _r, d in interventions.due(t0 + DAY)], [1])
        interventions.set_look(row["id"], 1, "held", "ok", t0 + DAY)
        # The week's look is not due until day 7, whatever else is late.
        self.assertEqual(interventions.due(t0 + 2 * DAY), [])
        self.assertEqual([d for _r, d in interventions.due(t0 + 7 * DAY)], [7])

    def test_could_not_check_never_counts_as_success(self):
        t0 = 1_000_000.0
        row = self.applied(t0)
        interventions.set_look(row["id"], 1, "held", "fine", t0 + DAY)
        interventions.set_look(row["id"], 7, "held", "fine", t0 + 7 * DAY)
        out = interventions.set_look(row["id"], 30, "could_not_check",
                                     "unreadable", t0 + 30 * DAY)
        self.assertEqual(out["status"], "could_not_check",
                         "two good looks do not make an unchecked last one held")

    def test_a_verdict_outside_the_vocabulary_is_could_not_check(self):
        row = self.applied(1_000_000.0)
        out = interventions.set_look(row["id"], 30, "probably fine", "x")
        self.assertEqual(out["status"], "could_not_check")

    def test_a_regression_ends_the_watch(self):
        t0 = 1_000_000.0
        row = self.applied(t0)
        out = interventions.set_look(row["id"], 1, "regressed", "back",
                                     t0 + DAY)
        self.assertEqual(out["status"], "regressed")
        self.assertEqual(interventions.due(t0 + 60 * DAY), [])

    def test_a_missing_file_is_none_and_an_unreadable_one_says_so(self):
        self.assertEqual(interventions.read(), {"rows": [], "error": ""})
        interventions.FILE.mkdir()       # a directory cannot be read as text
        self.assertIn("could not read", interventions.read()["error"])

    def test_the_cap_never_cuts_a_row_still_being_watched(self):
        old = interventions.MAX_ROWS
        interventions.MAX_ROWS = 3
        try:
            watched = self.applied(1.0)
            for i in range(2, 6):
                row = self.applied(float(i))
                interventions.set_look(row["id"], 30, "held", "", float(i))
            ids = [r["id"] for r in interventions.read()["rows"]]
            self.assertIn(watched["id"], ids)
            self.assertLessEqual(len(ids), 3)
        finally:
            interventions.MAX_ROWS = old


class TestTheDeterministicJudges(unittest.TestCase):
    def test_a_trace_after_the_fix_held(self):
        verify = {"kind": "trace_within_h", "automation": "automation.x",
                  "hours": 48}
        now = time.time()
        state = {"state": "on", "attributes": {
            "last_triggered": "2026-10-04T10:00:00+00:00"}}
        applied = interventions._stamp("2026-10-04T09:00:00+00:00")
        self.assertEqual(interventions.judge_trace(verify, state, applied,
                                                   now)[0], "held")

    def test_no_trace_inside_the_window_is_not_yet_a_verdict(self):
        verify = {"kind": "trace_within_h", "automation": "automation.x",
                  "hours": 48}
        state = {"state": "on", "attributes": {"last_triggered": None}}
        self.assertEqual(interventions.judge_trace(verify, state, 100.0,
                                                   100.0 + 3600)[0],
                         "could_not_check")
        self.assertEqual(interventions.judge_trace(verify, state, 100.0,
                                                   100.0 + 49 * 3600)[0],
                         "regressed")

    def test_state_is(self):
        verify = {"kind": "state_is", "entity": "switch.x", "state": "on"}
        self.assertEqual(interventions.judge_state(verify, {"state": "on"})[0],
                         "held")
        self.assertEqual(interventions.judge_state(verify, {"state": "off"})[0],
                         "regressed")
        self.assertEqual(interventions.judge_state(verify, None)[0],
                         "could_not_check")
        self.assertEqual(interventions.judge_state(
            verify, {"state": "unavailable"})[0], "could_not_check")

    def test_came_back_is_the_same_key_reopened_or_refiled_after(self):
        row = {"finding_ts": 5, "finding_key": "x broke", "applied_at": 100.0}
        norm = findings_store.normalize
        self.assertIsNone(interventions.came_back(
            row, [{"ts": 5, "text": "x broke", "status": "fixed"}], norm))
        self.assertTrue(interventions.came_back(
            row, [{"ts": 5, "text": "X broke", "status": "open"}], norm))
        self.assertTrue(interventions.came_back(
            row, [{"ts": 200, "text": "x broke", "status": "open"}], norm))
        self.assertIsNone(interventions.came_back(
            row, [{"ts": 50, "text": "x broke", "status": "open"}], norm),
            "an older row under the same key is not this fix coming back")

    def test_an_interval_needs_two_regressions(self):
        rows = [{"finding_key": "k", "applied_at": 0, "regressed_at": 9 * DAY}]
        self.assertIsNone(interventions.interval_days(rows, "k"))
        rows.append({"finding_key": "k", "applied_at": 20 * DAY,
                     "regressed_at": 31 * DAY})
        self.assertEqual(interventions.interval_days(rows, "k"), 10)

    def test_the_followup_reply_is_read_in_a_closed_vocabulary(self):
        self.assertEqual(interventions.parse_followup(
            "", {"verdict": "held", "reason": "ran twice"}),
            ("held", "ran twice"))
        self.assertEqual(interventions.parse_followup(
            '{"verdict": "fine"}')[0], "could_not_check")
        self.assertEqual(interventions.parse_followup("no json")[0],
                         "could_not_check")


class FollowupCase(PanelCase):
    def setUp(self):
        super().setUp()
        import engine
        import ha_data
        self.engine, self.ha_data = engine, ha_data
        self._iv_old = interventions.FILE
        interventions.FILE = Path(self.tmp.name) / "interventions.jsonl"
        self._olds2 = (ha_data.entity_state, engine.run_analyst,
                       engine.get_auth)
        self.states = {}
        self.analyst = []

        async def state(entity_id, timeout=15):
            return self.states.get(entity_id)

        def analyst(prompt, system, *a, **k):
            self.analyst.append((prompt, k.get("job")))
            return {"ok": True, "text": "", "error": "", "meta": {},
                    "data": {"verdict": self.verdict, "reason": "looked"}}

        self.verdict = "held"
        ha_data.entity_state = state
        engine.run_analyst = analyst
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.server.FOLLOWUP_STATE["running"] = False

    def tearDown(self):
        interventions.FILE = self._iv_old
        (self.ha_data.entity_state, self.engine.run_analyst,
         self.engine.get_auth) = self._olds2
        super().tearDown()

    def tick(self, now):
        return asyncio.run(self.server._followup_tick(now))

    def fixed_finding(self, text="the hall automation never fires",
                      source="resident"):
        row, _ = findings_store.add(text, source=source, severity="warning")
        findings_store.set_status(row["ts"], "fixed", "done")
        return row


class TestTheFollowupTick(FollowupCase):
    def test_a_state_verify_is_judged_with_no_model(self):
        row = self.fixed_finding()
        t0 = time.time() - 2 * DAY
        interventions.record({"id": "fix-a", "applied_at": t0,
                              "finding_ts": row["ts"],
                              "finding_text": row["text"],
                              "finding_key": findings_store.normalize(
                                  row["text"]),
                              "verify_by": {"kind": "state_is",
                                            "entity": "switch.pump",
                                            "state": "on"}}, now=t0)
        self.states["switch.pump"] = {"state": "on"}
        self.assertEqual(self.tick(time.time()), 1)
        self.assertEqual(self.analyst, [], "a deterministic look ran a model")
        looked = interventions.get("fix-a")["looks"]["1"]
        self.assertEqual((looked["verdict"], looked["how"]), ("held", "state"))

    def test_a_regression_reopens_the_case_citing_the_intervention(self):
        row = self.fixed_finding()
        t0 = time.time() - 2 * DAY
        interventions.record({"id": "fix-b", "applied_at": t0,
                              "finding_ts": row["ts"],
                              "finding_text": row["text"],
                              "finding_key": findings_store.normalize(
                                  row["text"]),
                              "verify_by": {"kind": "state_is",
                                            "entity": "switch.pump",
                                            "state": "on"}}, now=t0)
        self.states["switch.pump"] = {"state": "off"}
        self.tick(time.time())
        reopened = findings_store.get(row["ts"])
        self.assertEqual(reopened["status"], "open")
        self.assertIn("fix-b", reopened["result"])
        self.assertEqual(interventions.get("fix-b")["status"], "regressed")

    def test_a_look_with_nothing_deterministic_is_a_gated_model_look(self):
        row = self.fixed_finding()
        t0 = time.time() - 2 * DAY
        interventions.record({"id": "fix-c", "applied_at": t0,
                              "finding_ts": row["ts"],
                              "finding_text": row["text"]}, now=t0)
        self.verdict = "held"
        self.tick(time.time())
        self.assertEqual(len(self.analyst), 1)
        self.assertEqual(self.analyst[0][1], "followup")
        self.assertEqual(interventions.get("fix-c")["looks"]["1"]["verdict"],
                         "held")

    def test_a_gated_look_waits_and_then_says_it_could_not_check(self):
        import settings_store
        settings_store.save({"auto_enabled": False})
        row = self.fixed_finding()
        t0 = time.time() - DAY - 60
        interventions.record({"id": "fix-d", "applied_at": t0,
                              "finding_ts": row["ts"],
                              "finding_text": row["text"]}, now=t0)
        self.tick(time.time())
        self.assertEqual(self.analyst, [], "a paused house spent a look")
        self.assertEqual(interventions.get("fix-d")["looks"], {})
        later = t0 + DAY + interventions.LOOK_GRACE_S + 1
        self.tick(later)
        look = interventions.get("fix-d")["looks"]["1"]
        self.assertEqual(look["verdict"], "could_not_check")
        self.assertIn("paused", look["detail"])
        self.assertEqual(self.analyst, [])

    def test_the_problem_coming_back_is_a_regression_before_any_look(self):
        row = self.fixed_finding()
        t0 = time.time() - 3600
        interventions.record({"id": "fix-e", "applied_at": t0,
                              "finding_ts": row["ts"],
                              "finding_text": row["text"],
                              "finding_key": findings_store.normalize(
                                  row["text"])}, now=t0)
        findings_store.set_status(row["ts"], "open", "came back")
        self.tick(time.time())
        self.assertEqual(interventions.get("fix-e")["status"], "regressed")
        self.assertEqual(self.analyst, [])

    def test_a_second_regression_suggests_a_maintenance_interval(self):
        row = self.fixed_finding("the water softener light is on")
        key = findings_store.normalize(row["text"])
        t0 = time.time() - 40 * DAY
        interventions.record({"id": "fix-f1", "applied_at": t0,
                              "finding_ts": row["ts"],
                              "finding_text": row["text"],
                              "finding_key": key}, now=t0)
        interventions.set_look("fix-f1", 1, "regressed", "back",
                               t0 + 10 * DAY)
        t1 = time.time() - 12 * DAY
        interventions.record({"id": "fix-f2", "applied_at": t1,
                              "finding_ts": row["ts"],
                              "finding_text": row["text"],
                              "finding_key": key,
                              "verify_by": {"kind": "state_is",
                                            "entity": "binary_sensor.salt",
                                            "state": "off"}}, now=t1)
        self.states["binary_sensor.salt"] = {"state": "on"}
        self.tick(time.time())
        texts = [f["text"] for f in findings_store.list_all()]
        self.assertTrue(any("keeps coming back" in t for t in texts), texts)
        made = next(f for f in findings_store.list_all()
                    if "keeps coming back" in f["text"])
        # Ten days the first time, twelve the second: about every eleven.
        self.assertIn("every 11 days", made["detail"])


class TestDiagnosticsCarryTheActingRow(FollowupCase):
    def test_the_row_is_in_the_payload(self):
        payload = self.server._diagnostics_payload()
        acting = payload["acting"]
        for key in ("interventions", "followup", "gate", "tripwire"):
            self.assertIn(key, acting)
        self.assertEqual(acting["interventions"]["rows"], 0)


if __name__ == "__main__":
    unittest.main()
