"""The weekly report's one thing, chosen across the week — and the rank beside it.

`weekly.one_thing` ranks by severity and age; `synthesis` asks the
`synthesis` job to choose across the week, under four rules: it may only
name a row it was shown, a critical row is never passed over, every way of
not running is the rank's pick, and the rank's pick is journaled beside
the choice so the job's worth is a number rather than an impression.

The module is driven on its own, and the wiring is driven through the real
`_send_weekly` over a real findings store and a real journal, with the CLI
stubbed at `engine.run_claude` / `engine.run_analyst` and nowhere else.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PANEL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "brain", "panel")
sys.path.insert(0, PANEL)

import synthesis  # noqa: E402

NOW = 1_756_800_000.0
DAY = 86400.0


def row(ts: float, severity: str = "warning", text: str = "something",
        status: str = "open", **extra) -> dict:
    out = {"ts": ts, "severity": severity, "text": text, "status": status,
           "snooze_until": 0}
    out.update(extra)
    return out


class TestTheCandidates(unittest.TestCase):
    def test_the_first_candidate_is_the_ranks_own_pick(self):
        import weekly
        rows = [row(NOW - DAY, "warning", "a"), row(NOW - 9 * DAY, "serious", "b"),
                row(NOW - 2 * DAY, "serious", "c")]
        cands = synthesis.candidates(rows, NOW)
        self.assertEqual(cands[0]["text"], weekly.one_thing(rows, NOW)["text"])
        self.assertEqual([c["text"] for c in cands], ["b", "c", "a"])

    def test_a_critical_row_means_only_critical_rows_are_offered(self):
        rows = [row(NOW - DAY, "critical", "freezer"),
                row(NOW - 3 * DAY, "warning", "dashboard"),
                row(NOW - 2 * DAY, "critical", "leak")]
        cands = synthesis.candidates(rows, NOW)
        self.assertEqual({c["text"] for c in cands}, {"freezer", "leak"})

    def test_a_snoozed_or_settled_row_is_not_a_candidate(self):
        rows = [row(NOW - DAY, text="live"),
                row(NOW - DAY + 1, text="sleeping", snooze_until=NOW + DAY),
                row(NOW - DAY + 2, text="fixing", status="fixing")]
        self.assertEqual([c["text"] for c in synthesis.candidates(rows, NOW)],
                         ["live"])

    def test_the_list_is_capped_and_the_cap_never_cuts_the_baseline(self):
        rows = [row(NOW - i * 60, "warning", f"w{i}") for i in range(30)]
        rows.append(row(NOW - DAY, "serious", "top"))
        cands = synthesis.candidates(rows, NOW)
        self.assertEqual(len(cands), synthesis.MAX_CANDIDATES)
        self.assertEqual(cands[0]["text"], "top")

    def test_one_candidate_is_not_a_choice(self):
        self.assertFalse(synthesis.worth_asking([row(NOW)]))
        self.assertTrue(synthesis.worth_asking([row(NOW), row(NOW - 1)]))


class TestReadingTheAnswer(unittest.TestCase):
    def setUp(self):
        self.cands = [row(NOW - 5, text="a"), row(NOW - 9, text="b")]

    def test_a_row_it_was_shown_is_an_answer(self):
        got = synthesis.parse({"ts": int(NOW - 9), "why": "  both share the hub  "},
                              self.cands)
        self.assertEqual(got[0]["text"], "b")
        self.assertEqual(got[1], "both share the hub")

    def test_a_row_it_was_not_shown_is_no_answer(self):
        self.assertIsNone(synthesis.parse({"ts": 123, "why": "x"}, self.cands))
        self.assertIsNone(synthesis.parse({"why": "x"}, self.cands))
        self.assertIsNone(synthesis.parse("b", self.cands))
        self.assertIsNone(synthesis.parse(None, self.cands))

    def test_the_decision_records_both_halves_of_the_comparison(self):
        base = self.cands[0]
        chose = synthesis.decision(base, (self.cands[1], "why"))
        self.assertEqual(chose["extra"], {"baseline": int(NOW - 5),
                                          "pick": int(NOW - 9),
                                          "agreed": False,
                                          "chosen_by": "synthesis"})
        fell = synthesis.decision(base, None, "automatic runs are paused")
        self.assertEqual(fell["pick"], base)
        self.assertTrue(fell["extra"]["agreed"])
        self.assertEqual(fell["extra"]["chosen_by"], "severity")
        self.assertEqual(fell["extra"]["reason"], "automatic runs are paused")

    def test_agreement_counts_only_weeks_the_synthesis_chose(self):
        rows = [
            {"source": "weekly_pick", "extra": {"chosen_by": "synthesis", "agreed": True}},
            {"source": "weekly_pick", "extra": {"chosen_by": "synthesis", "agreed": False}},
            {"source": "weekly_pick", "extra": {"chosen_by": "severity", "agreed": True,
                                                "reason": "paused"}},
            {"source": "card", "extra": {"chosen_by": "synthesis"}},
        ]
        got = synthesis.agreement(rows)
        self.assertEqual((got["weeks"], got["synthesised"], got["agreed"],
                          got["differed"]), (3, 2, 1, 1))
        self.assertEqual(got["last"]["reason"], "paused")


class TestTheWeeklyReportEndsOnThePick(unittest.TestCase):
    """`_send_weekly`, driven: the store, the journal and the prompt are real."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        import engine
        import journal
        import settings_store
        import usage_store
        srv = self.server
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.fs = srv.findings_store
        self._restore = []

        def point(mod, **attrs):
            for k, v in attrs.items():
                self._restore.append((mod, k, getattr(mod, k)))
                setattr(mod, k, v)

        for mod in {id(m): m for m in (srv.findings_store, sys.modules.get("findings_store"))
                    if m is not None}.values():
            point(mod, FINDINGS_FILE=root / "findings.json", INBOX_DIR=root / "inbox",
                  SETTLED_FILE=root / "settled.json",
                  STATE_FILE=root / "config" / ".brain" / "state.json")
        point(settings_store, SETTINGS_FILE=str(root / "settings.json"))
        point(journal, JOURNAL_FILE=str(root / "journal.jsonl"))
        point(usage_store, USAGE_FILE=str(root / "usage.json"),
              LIMITS_FILE=str(root / "limits.json"))
        point(engine, run_claude=self.run_claude, run_analyst=self.run_analyst,
              get_auth=lambda: {"type": "oauth", "value": "x"})

        async def meters(now):
            return {"available": False, "reason": "none"}

        async def house(now=None):
            return ""

        async def swallow(rows, *_args, **_kwargs):
            self.notified.extend(rows or [])

        point(srv, _weekly_energy=meters, _house_prompt_block=house,
              _memory_block=lambda **k: "", _send_notification=swallow)
        point(srv.weekly, MEMORY_LOG=str(root / "nope.log"))
        self._state = dict(srv.WEEKLY_STATE)
        srv.WEEKLY_STATE.update({"last_sent": 0.0, "last_pick": {}})
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "budget_percent": 100})
        self.picks: list = []
        self.claude_calls: list[dict] = []
        self.analyst_calls: list[dict] = []
        self.notified: list = []

    def tearDown(self):
        for mod, k, v in reversed(self._restore):
            setattr(mod, k, v)
        self.server.WEEKLY_STATE.clear()
        self.server.WEEKLY_STATE.update(self._state)
        self.tmp.cleanup()

    # -- stubs -----------------------------------------------------------
    def run_claude(self, prompt, system, *a, **k):
        self.claude_calls.append({"prompt": prompt, "system": system, **k})
        return self.picks.pop(0) if self.picks else {"ok": False, "error": "no reply"}

    def run_analyst(self, prompt, system, *a, **k):
        self.analyst_calls.append({"prompt": prompt, "system": system, **k})
        return {"ok": True, "text": "This week the house " + "x" * 80}

    # -- helpers ---------------------------------------------------------
    def file(self, *rows):
        made = self.fs.add_many([dict(r) for r in rows])
        return sorted(made, key=lambda r: r["ts"])

    def journal_picks(self):
        import journal
        return [r for r in journal.tail(0) if r.get("source") == "weekly_pick"]

    def send(self, pressed=False):
        return asyncio.run(self.server._send_weekly(time.time(), pressed=pressed))

    # -- cases -----------------------------------------------------------
    def test_the_synthesis_choice_is_what_the_report_is_told_to_end_on(self):
        old, new = self.file(
            {"text": "The hall sensor is serious", "severity": "serious"},
            {"text": "Three plugs share one flaky hub", "severity": "warning"})
        self.picks.append({"ok": True, "data": {
            "ts": int(new["ts"]), "why": "the three plug rows share one hub"}})
        body = self.send()
        self.assertTrue(body)
        self.assertEqual(len(self.claude_calls), 1)
        call = self.claude_calls[0]
        self.assertEqual(call["job"], "synthesis")
        self.assertEqual(call["schema"], synthesis.SCHEMA)
        # Both rows were offered, by id, to choose between.
        self.assertIn(f"id {int(old['ts'])}", call["prompt"])
        self.assertIn(f"id {int(new['ts'])}", call["prompt"])
        frame = self.analyst_calls[0]["prompt"]
        tail = frame.split("write about THIS one and no other:")[1]
        self.assertIn("Three plugs share one flaky hub", tail)
        self.assertNotIn("The hall sensor is serious", tail)
        self.assertIn("Chosen because: the three plug rows share one hub", tail)
        [line] = self.journal_picks()
        self.assertEqual(line["outcome"], "ok")
        self.assertEqual(line["extra"], {"baseline": int(old["ts"]),
                                         "pick": int(new["ts"]),
                                         "agreed": False,
                                         "chosen_by": "synthesis"})
        diag = self.server._weekly_diagnostics()
        self.assertEqual(diag["pick"]["differed"], 1)
        self.assertEqual(diag["last_pick"]["chosen_by"], "synthesis")

    def test_a_paused_house_spends_nothing_on_choosing_and_the_rank_decides(self):
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": False})
        old, _new = self.file({"text": "Serious one", "severity": "serious"},
                              {"text": "Warning one", "severity": "warning"})
        self.send()
        self.assertEqual(self.claude_calls, [])
        tail = self.analyst_calls[0]["prompt"].split("and no other:")[1]
        self.assertIn("Serious one", tail)
        self.assertNotIn("Chosen because", tail)
        [line] = self.journal_picks()
        self.assertEqual(line["outcome"], "fallback")
        self.assertTrue(line["ok"])
        self.assertEqual(line["extra"]["chosen_by"], "severity")
        self.assertEqual(line["extra"]["pick"], int(old["ts"]))
        self.assertIn("paused", line["extra"]["reason"])

    def test_a_press_needs_only_a_credential(self):
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": False})
        _old, new = self.file({"text": "Serious one", "severity": "serious"},
                              {"text": "Warning one", "severity": "warning"})
        self.picks.append({"ok": True, "data": {"ts": int(new["ts"]), "why": "w"}})
        self.send(pressed=True)
        self.assertEqual(len(self.claude_calls), 1)
        self.assertEqual(self.journal_picks()[0]["extra"]["chosen_by"], "synthesis")

    def test_a_failed_run_or_an_invented_row_is_the_ranks_pick(self):
        old, _new = self.file({"text": "Serious one", "severity": "serious"},
                              {"text": "Warning one", "severity": "warning"})
        self.picks.append({"ok": False, "error": "529 Overloaded"})
        self.send()
        self.picks.append({"ok": True, "data": {"ts": 42, "why": "made up"}})
        self.server.WEEKLY_STATE["last_sent"] = 0.0
        self.send()
        lines = self.journal_picks()
        self.assertEqual([ln["extra"]["chosen_by"] for ln in lines],
                         ["severity", "severity"])
        self.assertIn("synthesis run failed", lines[0]["extra"]["reason"])
        self.assertIn("named no problem", lines[1]["extra"]["reason"])
        for call in self.analyst_calls:
            self.assertIn("Serious one", call["prompt"].split("and no other:")[1])

    def test_one_open_problem_is_not_a_choice_and_costs_nothing(self):
        self.file({"text": "The only one", "severity": "warning"})
        self.send()
        self.assertEqual(self.claude_calls, [])
        self.assertEqual(self.journal_picks()[0]["extra"]["chosen_by"], "severity")

    def test_a_critical_row_is_never_passed_over_for_a_lesser_one(self):
        self.file({"text": "The freezer has stopped", "severity": "critical"},
                  {"text": "A dashboard card is broken", "severity": "warning"})
        self.send()
        # One critical row is one candidate: nothing to choose, nothing spent,
        # and the warning never reached a prompt that could prefer it.
        self.assertEqual(self.claude_calls, [])
        self.assertIn("The freezer has stopped",
                      self.analyst_calls[0]["prompt"].split("and no other:")[1])

    def test_a_quiet_week_chooses_nothing(self):
        # Nothing to report: no pick is journaled and no run is made.
        self.send()
        self.assertEqual(self.claude_calls, [])
        self.assertEqual(self.analyst_calls, [])
        self.assertEqual(self.journal_picks(), [])

    def test_the_bundle_carries_the_pick_ids_and_never_the_sentence(self):
        _old, new = self.file({"text": "Serious one", "severity": "serious"},
                              {"text": "Warning one", "severity": "warning"})
        self.picks.append({"ok": True, "data": {"ts": int(new["ts"]),
                                                "why": "the porch freezer note"}})
        self.send()
        bundle = json.dumps(self.server._weekly_diagnostics())
        self.assertNotIn("porch freezer", bundle)
        self.assertNotIn("Warning one", bundle)


class TestTheSchedulerNeverPressesTheDeepReview(unittest.TestCase):
    def test_the_synthesis_job_is_on_the_plan_and_may_be_scheduled(self):
        import model_plan
        self.assertIn("synthesis", model_plan.JOBS)
        self.assertNotIn("synthesis", model_plan.PRESS_ONLY)


if __name__ == "__main__":
    unittest.main()
