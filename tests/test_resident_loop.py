#!/usr/bin/env python3
"""The Resident loop, driven for real with only the CLI stubbed.

`resident.py` holds the prompts and the budget and spawns nothing, and
`tests/test_resident.py` drives those on their own. What is left — and what
this file is about — is the half that lives in `server.py`: which producers
reach the queue, when a look happens, what each of the four verdicts does to
the stores underneath, and what a press on a case fires.

Every assertion is against a real store. `engine.run_claude` and
`engine.run_analyst` are the only fakes, and both RECORD their kwargs,
because "the job reached the table" and "the job reached the process" are
different claims and only the second decides what Anthropic is asked for —
`test_model_plan`'s rule, one caller over.

Two things are reproduced before they are asserted, because each is a rule
that only means something if the thing it stops can be shown happening:

  * a gate. No credential, paused, or the budget spent — the batch WAITS and
    nothing is spawned, and the signals are still there to be looked at on
    the pass after the gate lifts.
  * `act` on a safety signal. It files a case and notifies; it calls
    NOTHING. The stub that would have carried a service call is rigged to
    fail the test if it is ever reached.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

# Imported for the names; every one of them is REBOUND in `setUpClass` to
# the copy the panel itself holds — see the note there. `cases` is not
# imported: nothing here reads it by name, and the copy the feed uses is
# reached as `cls.server.cases` where `point()` needs it.
import findings_store  # noqa: E402
import hypotheses  # noqa: E402
import proposals  # noqa: E402
import resident  # noqa: E402
import signals  # noqa: E402
import todo_store  # noqa: E402
import triage  # noqa: E402


def reply(verdicts: list[dict], run_id: str = "look-1") -> dict:
    """What a first look answers with, in the CLI's envelope."""
    return {"ok": True, "error": "", "text": json.dumps({"verdicts": verdicts}),
            "meta": {"session_id": run_id}}


def case_reply(**over) -> dict:
    body = {
        "claim": "The garage freezer has drifted six degrees in a month",
        "detail": "Its own statistics walk upward and no other freezer does.",
        "kind": "problem", "confidence": 0.8, "stakes": "high",
        "fix": "Check the door seal.",
        "evidence": [{"entity": "sensor.garage_freezer", "value": "-12.4",
                      "when": "15 Sep 08:10"}],
        "actions": [], "escalate": False, **over}
    return {"ok": True, "error": "", "text": json.dumps(body),
            "meta": {"session_id": "inv-1"}}


class LoopCase(unittest.TestCase):
    """`_resident_tick` driven over real stores, with the CLI stubbed."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        # The panel's OWN module objects, not whatever `sys.modules` holds
        # by the time this file is collected. Several test modules pop a
        # store out of `sys.modules` and re-import it against their own
        # temporary directory, so by the time this one runs there can be
        # THREE live copies of `proposals`: the one this file imported, the
        # one `server` holds, and the one `cases` holds — and they are not
        # the same object, which was measured rather than assumed. Writing
        # through one and reading through another is a test that passes
        # alone and fails under the suite, which is exactly what happened.
        # CLAUDE.md's `atomic_write` rule, one import graph over: patch the
        # copy the code under test actually reads, and here that means all
        # of them.
        global findings_store, hypotheses, proposals, todo_store
        global resident, signals, triage
        findings_store = cls.server.findings_store
        hypotheses = cls.server.hypotheses
        proposals = cls.server.proposals
        todo_store = cls.server.todo_store
        resident = cls.server.resident
        signals = cls.server.signals
        triage = cls.server.triage

    @classmethod
    def copies(cls, name: str) -> list:
        """Every live module object under this name that the panel reads."""
        out, seen = [], set()
        for holder in (cls.server, cls.server.cases, sys.modules):
            mod = (sys.modules.get(name) if holder is sys.modules
                   else getattr(holder, name, None))
            if mod is not None and id(mod) not in seen:
                seen.add(id(mod))
                out.append(mod)
        return out

    def point(self, name: str, **paths) -> None:
        """Point every copy of `name` at this test's own directory, and put
        each one back afterwards."""
        for mod in self.copies(name):
            for attr, value in paths.items():
                self._restore.append((mod, attr, getattr(mod, attr)))
                setattr(mod, attr, value)

    def setUp(self):
        import engine
        import settings_store
        import undo_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        srv = self.server
        self._restore: list[tuple] = []
        self._old = {
            "settings": settings_store.SETTINGS_FILE,
            "engine": (engine.run_claude, engine.run_analyst, engine.get_auth),
            "server": (srv.LEDGER, srv._house_prompt_block,
                       srv._read_shared_memory, srv._announce_findings,
                       srv._record_usage, srv.MEMORY_INBOX_DIR,
                       srv.EVENT_BUS),
        }
        (root / "inbox").mkdir(parents=True, exist_ok=True)
        # Pointed under a "config" that does not exist, so the mirrors are
        # skipped exactly as they are on a dev checkout.
        self.point("findings_store",
                   FINDINGS_FILE=root / "findings.json",
                   INBOX_DIR=root / "inbox",
                   SETTLED_FILE=root / "findings-settled.json",
                   STATE_FILE=root / "config" / ".brain" / "state.json")
        self.point("hypotheses", HYPOTHESES_FILE=root / "hypotheses.jsonl")
        self.point("proposals",
                   STORE=root / "proposals.json",
                   SETTLED_FILE=root / "proposals-settled.json",
                   SHARED=root / "config" / ".brain" / "proposals.json")
        self.point("todo_store",
                   TODO_FILE=root / "todo.json",
                   STATE_FILE=root / "config" / ".brain" / "todo.json")
        self.point("cases", SNOOZE_FILE=root / "cases-snooze.json")
        self.point("resident", WATCH_FILE=root / "resident-watch.json")
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        settings_store.save({"onboarded": True, "auto_enabled": True})
        srv.LEDGER = resident.Ledger(root / "resident-ledger.json")
        srv.MEMORY_INBOX_DIR = root / "memory-inbox"
        srv.EVENT_BUS = None
        undo_store.clear() if hasattr(undo_store, "clear") else None

        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks: list[dict] = []
        self.investigations: list[dict] = []
        self.look_calls: list[dict] = []
        self.analyst_calls: list[dict] = []

        def run_claude(prompt, system, *a, **k):
            self.look_calls.append({"prompt": prompt, "system": system,
                                    "args": a, **k})
            return self.looks.pop(0) if self.looks else {
                "ok": False, "error": "no reply", "meta": {}}

        def run_analyst(prompt, system, *a, **k):
            self.analyst_calls.append({"prompt": prompt, "system": system,
                                       "args": a, **k})
            return self.investigations.pop(0) if self.investigations else {
                "ok": False, "error": "no reply", "meta": {}}

        engine.run_claude = run_claude
        engine.run_analyst = run_analyst
        srv._read_shared_memory = lambda: ""
        srv._record_usage = lambda result, name: {"total": 1234}
        self.announced: list[dict] = []

        async def house(now=None):
            return ""

        async def announce(rows):
            self.announced.extend(rows or [])

        srv._house_prompt_block = house
        srv._announce_findings = announce
        srv.RESIDENT_PENDING.clear()
        srv.RESIDENT_INFLIGHT.clear()
        srv.RESIDENT_QUEUE = asyncio.Queue()
        srv.SAFETY_SUBJECTS.clear()
        srv._KNOWN_ENTITIES.update({"at": 0.0, "ids": frozenset()})
        srv._SIGNAL_CTX.update({"at": 0.0, "ctx": signals.EMPTY_CONTEXT})
        for key, value in (("running", False), ("last_look_at", 0.0),
                           ("last_sweep_at", 0.0),
                           ("queue_len", 0), ("waiting", 0),
                           ("hot_pending", 0), ("dropped", 0),
                           ("duplicates", 0), ("last_error", ""),
                           ("investigations_waiting", 0),
                           ("last_investigation_at", 0.0)):
            srv.RESIDENT_STATE[key] = value
        srv.TRIAGE_STATE.update({"running": False, "day": "", "runs": 0})

    def tearDown(self):
        import engine
        import settings_store
        srv = self.server
        for mod, attr, value in reversed(self._restore):
            setattr(mod, attr, value)
        settings_store.SETTINGS_FILE = self._old["settings"]
        (engine.run_claude, engine.run_analyst,
         engine.get_auth) = self._old["engine"]
        (srv.LEDGER, srv._house_prompt_block, srv._read_shared_memory,
         srv._announce_findings, srv._record_usage, srv.MEMORY_INBOX_DIR,
         srv.EVENT_BUS) = self._old["server"]
        srv.RESIDENT_PENDING.clear()
        srv.RESIDENT_INFLIGHT.clear()
        srv.TRIAGE_STATE.update({"running": False, "day": "", "runs": 0})
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def file_check_row(self, **fields) -> dict:
        """One finding, filed the way every producer files: waiting."""
        [row] = findings_store.add_many(triage.gate([{
            "text": "The pantry contact has not changed in nine days",
            "detail": "last change 3 Sep", "severity": "warning",
            "entity_id": "binary_sensor.pantry",
            "source": "check:dev.frozen", "source_title": "Sensors frozen",
            **fields}]))
        return row

    def tick(self, now: float | None = None) -> dict:
        return asyncio.run(self.server._resident_tick(
            now if now is not None else time.time()))

    def statuses(self) -> dict[int, str]:
        return {f["ts"]: f["status"] for f in findings_store.list_all()}


# ---------------------------------------------------------------------------
# When a look happens
# ---------------------------------------------------------------------------

class TestWhenTheLookHappens(LoopCase):
    """Hot means *now*; everything else means *on the timer*.

    A signal is only ever allowed to cause one thing by itself, and this is
    it. The cold case is the one worth pinning, because a loop that looked
    at every tick would spend the cheap tier's whole argument.
    """

    def test_a_cold_batch_waits_for_the_timer(self):
        now = time.time()
        self.server.RESIDENT_STATE["last_look_at"] = now - 30
        self.server._resident_offer(signals.from_time(
            "checks pass", now, text="a pass ran"))
        out = self.tick(now)
        self.assertFalse(out["looked"])
        self.assertEqual(self.look_calls, [])
        # And it is still there to be looked at when the timer comes round.
        self.assertEqual(self.server.RESIDENT_STATE["queue_len"], 1)

    def test_a_hot_signal_looks_immediately(self):
        now = time.time()
        # Well inside the ordinary interval, and past the floor a burst of
        # hot signals is held to.
        self.server.RESIDENT_STATE["last_look_at"] = now - 90
        self.server._resident_offer(signals.make(
            "state", "binary_sensor.kitchen_leak", now=now, hot=True,
            source="eventbus", text="Kitchen leak off → on", salience=0.9))
        self.looks.append(reply([{"id": 1, "verdict": "watch",
                                  "why": "waiting for a second reading"}]))
        out = self.tick(now)
        self.assertTrue(out["looked"], out)
        self.assertEqual(len(self.look_calls), 1)

    def test_a_hot_signal_inside_the_floor_still_waits(self):
        """`MIN_LOOK_SPACING_S` is what stops a house producing hot signals
        in a burst looking once per leak sensor."""
        now = time.time()
        self.server.RESIDENT_STATE["last_look_at"] = now - 5
        self.server._resident_offer(signals.make(
            "state", "binary_sensor.kitchen_leak", now=now, hot=True,
            source="eventbus", text="tripped", salience=0.9))
        self.assertFalse(self.tick(now)["looked"])
        self.assertEqual(self.look_calls, [])

    def test_the_look_is_the_cheap_job_with_no_tools(self):
        """The job name is what decides the tier, and `run_claude` is what
        decides that nothing can be looked up — a look, not a search."""
        now = time.time()
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "it is a cupboard nobody opens"}]))
        self.tick(now)
        [call] = self.look_calls
        self.assertEqual(call["job"], resident.JOB_FIRST_LOOK)
        self.assertEqual(call["schema"], resident.FIRST_LOOK_SCHEMA)
        self.assertEqual(call["system"], resident.FIRST_LOOK_SYSTEM)
        # `a` is what follows (prompt, system): model, timeout, turns, source.
        self.assertEqual(call["args"][1], resident.TIMEOUT_S)
        self.assertEqual(call["args"][2], resident.MAX_TURNS)
        self.assertEqual(call["args"][3], "resident")


# ---------------------------------------------------------------------------
# The gates
# ---------------------------------------------------------------------------

class TestAGateHoldsAndLosesNothing(LoopCase):
    """Three gates, one rule: no run is spawned and no signal is lost.

    This is the opposite of what `_triage_findings` does with the same three
    — that one surfaced the whole queue — and deliberately: triage was about
    to hide a row, this is about to look at one, and `triage.STALE_S` is
    what makes the wait bounded.
    """

    def assert_held(self, why: str):
        now = time.time()
        row = self.file_check_row()
        out = self.tick(now)
        self.assertFalse(out["looked"])
        self.assertIn(why, out.get("held", ""))
        self.assertEqual(self.look_calls, [], "a gate spawned a run")
        # Nothing lost: the signal is still queued and the row is still
        # waiting rather than having been hidden or surfaced.
        self.assertEqual(self.server.RESIDENT_STATE["queue_len"], 1)
        self.assertEqual(self.statuses()[row["ts"]], "triaging")

    def test_no_credential(self):
        import engine
        engine.get_auth = lambda: None
        self.assert_held("credential")

    def test_paused(self):
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": False})
        self.assert_held("paused")

    def test_the_budget_is_spent(self):
        import usage_store
        old = usage_store.budget_state
        usage_store.budget_state = lambda settings: {"blocked": True}
        try:
            self.assert_held("budget")
        finally:
            usage_store.budget_state = old

    def test_the_batch_is_looked_at_on_the_pass_after_the_gate_lifts(self):
        import engine
        engine.get_auth = lambda: None
        self.file_check_row()
        self.tick()
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "worth a look at its history"}]))
        self.investigations.append(case_reply())
        out = self.tick()
        self.assertTrue(out["looked"], out)

    def test_a_row_left_waiting_past_the_hour_is_shown_as_it_is(self):
        """The promise that makes holding a batch honest: a queue that
        stopped draining is still shown, carrying the sentence that says
        nothing looked at it."""
        import engine
        engine.get_auth = lambda: None
        now = time.time()
        row = self.file_check_row()
        self.tick(now)
        self.assertEqual(self.statuses()[row["ts"]], "triaging")
        self.tick(now + triage.STALE_S + 60)
        fresh = findings_store.get(row["ts"])
        self.assertEqual(fresh["status"], "open")
        self.assertEqual(fresh["triage"]["verdict"], "untriaged")
        self.assertEqual(fresh["triage"]["reason"], triage.UNJUDGED)


# ---------------------------------------------------------------------------
# The four verdicts
# ---------------------------------------------------------------------------

class TestWhatTheVerdictsDo(LoopCase):

    def test_ignore_holds_a_check_row_exactly_as_triage_held_it(self):
        row = self.file_check_row()
        self.looks.append(reply([{
            "id": 1, "verdict": "ignore",
            "why": "its history shows it moved twice last month — it is a "
                   "cupboard, not a stuck sensor"}]))
        self.tick()
        held = findings_store.get(row["ts"])
        self.assertEqual(held["status"], "held")
        self.assertEqual(held["triage"]["verdict"], "held")
        self.assertIn("cupboard", held["triage"]["reason"])
        self.assertEqual(held["triage"]["run_id"], "look-1")
        # …and so the Looked-at filter and its one press keep working.
        self.assertIsNotNone(findings_store.elevate(row["ts"]))

    def test_ignore_on_a_signal_no_rule_filed_drops_it_and_counts_it(self):
        now = time.time()
        self.server._resident_offer(signals.make(
            "state", "light.porch", now=now, source="eventbus",
            text="Porch light off → on", salience=0.2))
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "somebody pressed a switch"}]))
        out = self.tick(now)
        self.assertEqual(out["verdicts"]["ignore"], 1)
        self.assertEqual(findings_store.list_all(), [])
        self.assertEqual(resident.watched(), {})

    def test_watch_watches_and_elevates_the_row(self):
        """A watch says *keep an eye on this*, which is not a reason to hide
        a row a rule filed — silence surfaces."""
        row = self.file_check_row()
        self.looks.append(reply([{
            "id": 1, "verdict": "watch",
            "why": "one reading is not enough to say it is stuck"}]))
        self.tick()
        shown = findings_store.get(row["ts"])
        self.assertEqual(shown["status"], "open")
        self.assertEqual(shown["triage"]["verdict"], "elevated")
        self.assertIn("binary_sensor.pantry", resident.watched())

    def test_investigate_spawns_one_analyst_run_and_files_a_case(self):
        row = self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "its history would settle this"}]))
        self.investigations.append(case_reply(
            evidence=[{"entity": "binary_sensor.pantry", "value": "off",
                       "when": "3 Sep"}]))
        out = self.tick()
        self.assertEqual(out["investigated"], 1)
        [call] = self.analyst_calls
        self.assertEqual(call["job"], resident.JOB_INVESTIGATE)
        self.assertEqual(call["schema"], resident.CASE_SCHEMA)
        self.assertEqual(call["system"], resident.INVESTIGATE_SYSTEM)
        self.assertEqual(call["args"][1], resident.INVESTIGATE_TIMEOUT_S)
        self.assertEqual(call["args"][3], "resident")
        # The row a rule filed is elevated, and the case is a row of its own
        # filed under the Resident so the scorecard grades it.
        self.assertEqual(findings_store.get(row["ts"])["status"], "open")
        filed = [f for f in findings_store.list_all()
                 if f["source"] == findings_store.RESIDENT_SOURCE]
        self.assertEqual(len(filed), 1, findings_store.list_all())
        self.assertEqual(filed[0]["status"], "open")
        self.assertEqual(filed[0]["claim"], case_reply()["text"]
                         and json.loads(case_reply()["text"])["claim"])
        # And the signal that started it rides in the evidence, because the
        # run was handed that line rather than reading it off the house.
        self.assertTrue(any("pantry" in (e.get("entity") or "")
                            for e in filed[0]["evidence"]))

    def test_a_duplicate_claim_is_counted_and_not_filed_twice(self):
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "worth a look"}]))
        self.investigations.append(case_reply(
            evidence=[{"entity": "binary_sensor.pantry", "value": "off",
                       "when": "3 Sep"}]))
        self.tick()
        before = len(findings_store.list_all())

        # The same claim again, from a second look over a second signal.
        # Handed over the way a checks pass hands its own rows over, rather
        # than waiting for the minute the store sweep runs on.
        self.server.RESIDENT_STATE["last_look_at"] = 0.0
        second = self.file_check_row(
            text="The pantry contact is still not moving",
            source="check:dev.frozen")
        self.server._offer_findings([second], time.time())
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "still worth a look"}], "look-2"))
        self.investigations.append(case_reply(
            evidence=[{"entity": "binary_sensor.pantry", "value": "off",
                       "when": "4 Sep"}]))
        self.tick()
        self.assertEqual(len(findings_store.list_all()), before + 1,
                         "the duplicate claim was filed as a second case")
        self.assertEqual(self.server.RESIDENT_STATE["duplicates"], 1)

    def test_act_on_a_safety_signal_files_a_case_notifies_and_calls_nothing(self):
        now = time.time()
        # The bus admits the event first, which is what records the class:
        # a signal carries no device class on purpose.
        self.server._note_safety("state_changed", {
            "entity_id": "binary_sensor.kitchen_leak",
            "new_state": {"state": "on",
                          "attributes": {"device_class": "moisture",
                                         "friendly_name": "Kitchen leak"}}})
        sig = signals.from_state_change(
            {"entity_id": "binary_sensor.kitchen_leak",
             "old_state": {"state": "off"},
             "new_state": {"state": "on",
                           "attributes": {"device_class": "moisture",
                                          "friendly_name": "Kitchen leak"}}},
            signals.EMPTY_CONTEXT, now)
        self.assertTrue(sig["hot"])
        self.server._resident_offer(sig)
        self.looks.append(reply([{"id": 1, "verdict": "act",
                                  "why": "water is running now"}]))
        out = self.tick(now)

        self.assertEqual(out["verdicts"]["act"], 1)
        [row] = findings_store.list_all()
        self.assertEqual(row["severity"], "critical")
        self.assertEqual(row["stakes"], "high")
        self.assertEqual(row["source"], findings_store.RESIDENT_SOURCE)
        self.assertEqual([a["shape"] for a in row["actions"]], ["notify"])
        self.assertFalse(row["actions"][0]["consent"])
        self.assertEqual([r["ts"] for r in self.announced], [row["ts"]])
        # NOTHING went to the house. The one path that could is the analyst
        # run, and the verdict must not have reached it either.
        self.assertEqual(self.analyst_calls, [],
                         "a safety verdict spawned a run at the house")

    def test_act_on_anything_else_is_an_investigation(self):
        """`act` is only ever a notification about a tripped safety sensor.
        Everything else it is said about is the next tier's question."""
        now = time.time()
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "act",
                                  "why": "this needs doing today"}]))
        self.investigations.append(case_reply(
            evidence=[{"entity": "binary_sensor.pantry", "value": "off",
                       "when": "3 Sep"}]))
        out = self.tick(now)
        self.assertEqual(out["investigated"], 1)
        self.assertEqual(len(self.analyst_calls), 1)

    def test_a_run_that_failed_shows_every_filed_row_saying_nothing_looked(self):
        row = self.file_check_row()
        self.looks.append({"ok": False, "error": "timed out", "meta": {}})
        self.tick()
        fresh = findings_store.get(row["ts"])
        self.assertEqual(fresh["status"], "open")
        self.assertEqual(fresh["triage"]["reason"], triage.RUN_FAILED)


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------

class TestTheLedgerRations(LoopCase):

    def test_a_ledger_past_its_sonnet_allowance_queues_rather_than_runs(self):
        import model_plan
        cap = resident.SONNET_PER_DAY[model_plan.DEFAULT_THINKING]
        now = time.time()
        for _ in range(cap):
            self.server.LEDGER.record(resident.JOB_INVESTIGATE, 0, now)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "worth a look"}]))
        out = self.tick(now)
        self.assertEqual(out["investigated"], 0)
        self.assertEqual(self.analyst_calls, [])
        # Queued, not dropped: an allowance that is spent is a reason to
        # wait, never a reason to decide a signal was worth nothing.
        self.assertEqual(self.server.RESIDENT_STATE["investigations_waiting"], 1)
        self.assertEqual(self.server.RESIDENT_STATE["queue_len"], 1)

    def test_the_cheap_tier_is_never_stopped_by_the_ledger(self):
        now = time.time()
        for _ in range(200):
            self.server.LEDGER.record(resident.JOB_FIRST_LOOK, 0, now)
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore",
                                  "why": "nothing in it"}]))
        self.assertTrue(self.tick(now)["looked"])

    def test_every_job_the_loop_names_is_in_the_plan(self):
        """An unknown job lands on the table's fallback tier silently, and
        `ESCALATE_JOB` is a constant rather than a literal — so the grep
        `test_model_plan` runs over `job="…"` cannot see it and this is
        what does."""
        import model_plan
        for job in (resident.JOB_FIRST_LOOK, resident.JOB_INVESTIGATE,
                    self.server.ESCALATE_JOB):
            self.assertIn(job, model_plan.JOBS, job)
        # …and the escalation really is a step UP, or a case the first run
        # was unsure about would be re-run by something no better at it.
        order = list(model_plan.TIERS)
        self.assertGreater(
            order.index(resident.tier_for(self.server.ESCALATE_JOB)),
            order.index(resident.tier_for(resident.JOB_INVESTIGATE)))

    def test_an_escalation_past_the_allowance_leaves_the_case_saying_so(self):
        """A claim worth filing is worth filing at the confidence it has —
        and the card says it was not looked at again, because a case that
        quietly skipped its second opinion reads like one that had it."""
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "worth a look"}]))
        self.investigations.append(case_reply(
            confidence=0.3, stakes="high", escalate=True,
            evidence=[{"entity": "binary_sensor.pantry", "value": "off",
                       "when": "3 Sep"}]))
        # `light` buys no top-tier runs at all, so the allowance is spent by
        # construction rather than by a loop that spends money to prove it.
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "thinking": "light"})
        self.tick()
        self.assertEqual(len(self.analyst_calls), 1,
                         "the escalation ran past its allowance")
        [filed] = [f for f in findings_store.list_all()
                   if f["source"] == findings_store.RESIDENT_SOURCE]
        self.assertIn("did not look again", filed["detail"])

    def test_the_look_is_charged_to_the_ledger(self):
        self.file_check_row()
        self.looks.append(reply([{"id": 1, "verdict": "ignore", "why": "no"}]))
        self.tick()
        summary = self.server.LEDGER.summary()
        self.assertEqual(summary["looked"], 1)
        self.assertEqual(summary["acted"], 0)

    def test_a_day_that_has_spent_its_looks_waits_for_tomorrow(self):
        now = time.time()
        self.server.TRIAGE_STATE.update(
            {"day": time.strftime("%Y-%m-%d", time.localtime(now)),
             "runs": triage.MAX_PER_DAY})
        self.file_check_row()
        out = self.tick(now)
        self.assertFalse(out["looked"])
        self.assertEqual(self.look_calls, [])


# ---------------------------------------------------------------------------
# The producers
# ---------------------------------------------------------------------------

class TestWhatReachesTheQueue(LoopCase):

    def test_every_producers_rows_reach_the_look_not_just_the_checks_pass(self):
        """The drain reads the QUEUE. A study session's row and a tab
        fetch's both land in `awaiting_triage`, and neither runs a pass."""
        rows = [self.file_check_row(text=f"row {i}", entity_id=f"sensor.s{i}")
                for i in range(3)]
        self.looks.append(reply([
            {"id": i, "verdict": "ignore", "why": "nothing in it"}
            for i in range(1, 4)]))
        self.tick()
        for row in rows:
            self.assertEqual(findings_store.get(row["ts"])["status"], "held")

    def test_a_row_is_offered_once_however_many_producers_hand_it_over(self):
        now = time.time()
        # Not due for a look, so the batch is still on the pending list to
        # be counted rather than having been spent on one.
        self.server.RESIDENT_STATE["last_look_at"] = now
        row = self.file_check_row()
        # The pass that filed it hands it over…
        self.server._offer_findings([row], now)
        # …and the tick sweeps `awaiting_triage` as well.
        asyncio.run(self.server._resident_pass(now))
        seen = [s.get("finding_ts") for s in self.server.RESIDENT_PENDING]
        self.assertEqual(seen.count(row["ts"]), 1, seen)

    def test_a_climate_row_rides_as_a_thermal_signal(self):
        """The three measurement stores have adapters of their own and the
        difference is the WEIGHT, which is the kind."""
        now = time.time()
        row = self.file_check_row(
            text="The nursery will be at freezing by 04:00",
            source="check:climate.freeze", entity_id="sensor.nursery_temp")
        self.server._offer_findings([row], now)
        [sig] = self.server.RESIDENT_PENDING
        self.assertEqual(sig["kind"], "thermal")

    def test_the_cap_drops_the_least_salient_and_counts_it(self):
        now = time.time()
        srv = self.server
        old = srv.RESIDENT_QUEUE_MAX
        srv.RESIDENT_QUEUE_MAX = 3
        try:
            for i in range(5):
                srv._resident_offer(signals.make(
                    "state", f"sensor.s{i}", now=now, source="eventbus",
                    text=f"s{i}", salience=0.1 * (i + 1)))
            srv._resident_absorb(now)
            kept = sorted(s["subject"] for s in srv.RESIDENT_PENDING)
            self.assertEqual(kept, ["sensor.s2", "sensor.s3", "sensor.s4"])
            self.assertEqual(srv.RESIDENT_STATE["dropped"], 2)
        finally:
            srv.RESIDENT_QUEUE_MAX = old

    def test_a_hot_signal_is_never_the_one_the_cap_drops(self):
        now = time.time()
        srv = self.server
        old = srv.RESIDENT_QUEUE_MAX
        srv.RESIDENT_QUEUE_MAX = 2
        try:
            srv._resident_offer(signals.make(
                "state", "binary_sensor.leak", now=now, hot=True,
                source="eventbus", text="tripped", salience=0.05))
            for i in range(4):
                srv._resident_offer(signals.make(
                    "state", f"sensor.s{i}", now=now, source="eventbus",
                    text=f"s{i}", salience=0.9))
            srv._resident_absorb(now)
            self.assertIn("binary_sensor.leak",
                          [s["subject"] for s in srv.RESIDENT_PENDING])
        finally:
            srv.RESIDENT_QUEUE_MAX = old


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

class RouteCase(LoopCase):
    """The two routes, over a real aiohttp client and the real stores."""

    def client(self):
        from aiohttp.test_utils import TestClient, TestServer
        return TestClient(TestServer(self.server.make_app()))

    def get(self, path: str):
        async def run():
            client = self.client()
            await client.start_server()
            try:
                resp = await client.get(path)
                return resp.status, await resp.json()
            finally:
                await client.close()
        return asyncio.run(run())

    def post(self, path: str, body: dict | None = None):
        async def run():
            client = self.client()
            await client.start_server()
            try:
                resp = await client.post(
                    path, data=json.dumps(body or {}),
                    headers={"Content-Type": "application/json"})
                text = await resp.text()
                try:
                    return resp.status, json.loads(text)
                except ValueError:
                    return resp.status, {"text": text}
            finally:
                await client.close()
        return asyncio.run(run())


class TestTheCasesRoute(RouteCase):

    def test_it_returns_a_case_of_each_kind_present(self):
        findings_store.add_many([{
            "text": "The hall sensor has not reported since Tuesday",
            "severity": "serious", "source": "check:dev.unavailable"}])
        hypotheses.propose("The garage fridge runs all night", "fridge")
        proposals.add({"kind": "routine", "source": "routines",
                       "title": "Turn the porch light off at 23:10",
                       "why": "You do it by hand most evenings.",
                       "config": {"trigger": [{"platform": "time"}]}})
        todo_store.add("Replace the hall sensor battery", severity="warning",
                       origin="hand")
        status, payload = self.get("/api/cases")
        self.assertEqual(status, 200)
        kinds = sorted({c["kind"] for c in payload["cases"]})
        # Never the chore: accepted work is the To-do tab's, with its own
        # count, and on this feed it read as a finding with no way onto
        # the list.
        self.assertEqual(kinds, ["opportunity", "problem", "question"])
        self.assertEqual(payload["open"], 3)
        # …and the three things the feed's foot line is built from.
        for key in ("ledger", "resident", "eventbus", "watching"):
            self.assertIn(key, payload)
        self.assertIn("looked", payload["ledger"])
        # Every case carries the rare verbs it can still take, so the panel
        # does not need to know a hypothesis is a different store.
        self.assertTrue(all("overflow" in c for c in payload["cases"]))


class TestEachPressFiresOneExistingEnding(RouteCase):
    """One hook per press, and it is the door that surface already used.

    Asserted on the real stores rather than on a recorder: what makes a
    second implementation dangerous is that it teaches brAIn something
    different, and the only place that is visible is the ledger, the
    document and the row.
    """

    def memory_lines(self) -> list[str]:
        """Every fact queued for the consolidator, as it was written.

        The inbox is JSONL and the key is `fact` — read from the real files
        rather than from a spy on `_submit_memory`, because what the ending
        TEACHES is the half a second implementation would get wrong.
        """
        out = []
        for path in sorted(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")):
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        out.append(json.loads(line)["fact"])
            except (OSError, ValueError, KeyError):
                continue
        return out

    def test_do_it_on_a_problem_moves_it_to_the_to_do_list(self):
        [row] = findings_store.add_many([{
            "text": "Back door battery is dead", "severity": "warning",
            "source": "check:dev.battery", "source_title": "Batteries"}])
        status, payload = self.post(f"/api/case/f:{row['ts']}/do")
        self.assertEqual(status, 200, payload)
        # The row is gone, the key is settled as ACCEPTED, the chore exists…
        self.assertIsNone(findings_store.get(row["ts"]))
        [entry] = findings_store.settled_listing()
        self.assertEqual(entry["kind"], "accepted")
        self.assertEqual([i["text"] for i in todo_store.listing()["items"]],
                         ["Back door battery is dead"])
        # …and NO memory line, because nothing is true of the house when you
        # put something on a list.
        self.assertEqual(self.memory_lines(), [])
        self.assertTrue(payload.get("undo"))
        # The answer carries every list the press moved — the feed, the
        # findings tab's list and the to-do counts — in ONE read. A feed
        # that arrived without the findings list it is rendered beside
        # left the row just moved to be drawn off the panel's stale copy,
        # as an old-style card under the case that had just gone.
        self.assertEqual(payload["cases"], [])
        self.assertEqual(payload["findings"], [])
        self.assertEqual(payload["todo"]["open"], 1)
        self.assertEqual(payload["open"], 0)

    def test_wrong_on_a_problem_settles_it_and_teaches_the_reason(self):
        [row] = findings_store.add_many([{
            "text": "The pantry contact is stuck", "severity": "warning",
            "source": "check:dev.frozen"}])
        status, payload = self.post(
            f"/api/case/f:{row['ts']}/wrong",
            {"note": "that is a cupboard nobody opens"})
        self.assertEqual(status, 200, payload)
        self.assertIsNone(findings_store.get(row["ts"]))
        [entry] = findings_store.settled_listing()
        self.assertEqual(entry["kind"], "ignored")
        self.assertTrue(any("cupboard" in line for line in self.memory_lines()),
                        self.memory_lines())

    def test_do_it_on_a_question_confirms_the_guess(self):
        guess = hypotheses.propose("The garage fridge runs all night", "fridge")
        status, payload = self.post(f"/api/case/h:{guess['ts']}/do")
        self.assertEqual(status, 200, payload)
        self.assertEqual(hypotheses.list_all("open"), [])
        self.assertIn("The garage fridge runs all night", self.memory_lines())

    def test_wrong_on_a_question_rejects_it_with_the_reason(self):
        guess = hypotheses.propose("The garage fridge runs all night", "fridge")
        status, payload = self.post(f"/api/case/h:{guess['ts']}/wrong",
                                    {"note": "it is a beer fridge"})
        self.assertEqual(status, 200, payload)
        self.assertEqual(hypotheses.list_all("open"), [])
        self.assertTrue(any("beer fridge" in line for line in self.memory_lines()))

    def test_wrong_on_an_opportunity_declines_it(self):
        row = proposals.add({
            "kind": "routine", "source": "routines",
            "title": "Turn the porch light off at 23:10",
            "why": "You do it by hand most evenings.",
            "config": {"trigger": [{"platform": "time"}]}})
        status, payload = self.post(f"/api/case/p:{row['ts']}/wrong",
                                    {"note": "we sit out there in summer"})
        self.assertEqual(status, 200, payload)
        # The row leaves the list, exactly as the Proposals tab's own
        # Decline leaves it, and the key is remembered so the miner does
        # not re-offer the same change next week.
        self.assertIsNone(proposals.get(row["ts"]))
        self.assertTrue(any("summer" in line for line in self.memory_lines()),
                        self.memory_lines())

    def test_do_it_on_a_chore_writes_the_line_the_move_did_not(self):
        item = todo_store.add("Replace the hall sensor battery",
                              severity="warning", origin="hand")
        status, payload = self.post(f"/api/case/t:{item['id']}/do")
        self.assertEqual(status, 200, payload)
        self.assertEqual(todo_store.listing()["items"], [])
        self.assertTrue(any("Replace the hall sensor battery" in line
                            for line in self.memory_lines()))

    def test_wrong_on_a_chore_takes_it_off_undone(self):
        item = todo_store.add("Replace the hall sensor battery",
                              severity="warning", origin="hand")
        status, payload = self.post(f"/api/case/t:{item['id']}/wrong")
        self.assertEqual(status, 200, payload)
        self.assertEqual(todo_store.listing()["items"], [])
        self.assertEqual(self.memory_lines(), [],
                         "dropping a chore undone taught memory something")

    def test_not_now_takes_nothing_away(self):
        [row] = findings_store.add_many([{
            "text": "The disk is 91% full", "severity": "warning",
            "source": "check:sys.disk_low"}])
        status, payload = self.post(f"/api/case/f:{row['ts']}/not_now")
        self.assertEqual(status, 200, payload)
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertEqual(self.memory_lines(), [])
        self.assertGreater(payload["snoozed_until"], time.time())
        # Nothing was taken away, so nothing is offered back.
        self.assertIsNone(payload.get("undo"))

    def test_a_case_that_is_not_there_is_a_404(self):
        status, _ = self.post("/api/case/f:12345/do")
        self.assertEqual(status, 404)

    def test_something_already_answered_cannot_be_answered_again(self):
        """A finished chore is a RECORD, not a decision. It has been
        answered once already, its one verb is *Put it back* and that lives
        in the overflow — so the three endings are a 409 rather than a
        silent second ending on the same thing."""
        item = todo_store.add("Replace the hall sensor battery",
                              severity="warning", origin="hand")
        todo_store.complete(item["id"])
        status, body = self.post(f"/api/case/t:{item['id']}/do")
        self.assertEqual(status, 409, body)
        self.assertEqual(self.memory_lines(), [])
        # …and the sentence says why rather than reading as a missing row.
        self.assertIn("chore", str(body).lower())

    def test_a_change_takes_got_it_and_writes_no_second_memory_line(self):
        """A change is news to read: brAIn wrote what it changed into
        memory when it made the change, so this press is only *I have read
        it* and `ack` is the ending that says so."""
        [row] = findings_store.add_many([{
            "text": "brAIn pointed the hall automation at the new sensor",
            "severity": "warning", "source": "check:auto.dead_ref"}])
        findings_store.set_status(row["ts"], "fixed")
        status, payload = self.post(f"/api/case/f:{row['ts']}/do")
        self.assertEqual(status, 200, payload)
        self.assertIsNone(findings_store.get(row["ts"]))
        [entry] = findings_store.settled_listing()
        self.assertEqual(entry["kind"], "fixed")
        self.assertEqual(self.memory_lines(), [])


class TestDiagnosticsCarriesTheLoop(RouteCase):

    def test_the_payload_names_the_resident_and_the_bus(self):
        payload = self.server._diagnostics_payload()
        self.assertIn("resident", payload)
        self.assertIn("eventbus", payload)
        for key in ("queue_len", "waiting", "ledger", "watching",
                    "look_interval_s"):
            self.assertIn(key, payload["resident"])
        # With no bus built, the reason says so rather than reading as a
        # socket that is merely quiet.
        self.assertFalse(payload["eventbus"]["connected"])
        self.assertTrue(payload["eventbus"]["idle_reason"])


if __name__ == "__main__":
    unittest.main()
