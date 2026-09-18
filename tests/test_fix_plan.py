#!/usr/bin/env python3
"""Plan first, then fix — and an undo that outlives the toast.

Pressing "Fix it" used to send a tool-enabled Claude run at a real house on
the press, with nothing on screen first about which entity, which file or
which automation was about to move; and afterwards the only way back was
`brain undo` in a terminal. Four claims hold the replacement, and they are
in four different places:

* **the plan is read-only by construction** — the press runs
  ``engine.run_analyst`` and never ``engine.run_agent``, which is asserted
  by making ``run_agent`` fail the test if anything calls it, because a
  prompt saying "change nothing" is a promise a model keeps where a tool
  list is one the CLI keeps;
* **the press is the consent** — Apply refuses without a plan, and refuses
  a plan that said software should not make this change, so the rule is not
  held by the card alone;
* **Cancel keeps the plan**, because it cost a Claude run and reading it
  again must not cost a second one;
* **the undo reverses files and LISTS service calls**, driven end to end
  through the REAL writers: the journal line is written by
  ``scripts/brain-edit-snapshot.py``'s own ``main`` off a real PreToolUse
  payload, and the ledger row by ``ha_mcp_server.record_action``. Those two
  writers are different processes running as different users and neither can
  import the panel, so writing their shapes down here a second time would
  prove only that this file agrees with itself.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
MCP_DIR = BASE_DIR / "brain" / "ha-mcp-server"
HOOK = BASE_DIR / "brain" / "scripts" / "brain-edit-snapshot.py"

sys.path.insert(0, str(PANEL_DIR))

import actions  # noqa: E402
import automation_writer  # noqa: E402
import engine  # noqa: E402
import findings_store  # noqa: E402
import fixer  # noqa: E402
import unfix  # noqa: E402

# The panel harness, imported rather than copied: a second setUp that has to
# stay in step with the first is the drift this repo keeps writing down.
from test_todo_list import PanelCase  # noqa: E402

PLAN = {
    "can_fix": True,
    "needs_you": False,
    "steps": ["Edit /config/automations.yaml: point 'Hall lights' at "
              "binary_sensor.hall rather than binary_sensor.hall_old"],
    "risk": "The automation will not fire between the edit and the reload.",
    "summary": "Its trigger entity was renamed, so it can never fire.",
}


def journal_an_edit(path: Path, *, existed: bool = True) -> None:
    """Write one journal line the way the PreToolUse hook really writes it.

    Drives ``brain-edit-snapshot.py``'s own ``main`` over a real Write
    payload rather than composing the line here, because the hook and the
    reverter are two processes that agree by contract: a shape written down
    twice is a shape that drifts, and only one side would be under test.

    ``WATCH_ROOTS`` is the one thing pointed somewhere else — it names
    ``/config`` as a literal, and a test house is a temp directory.
    """
    spec = importlib.util.spec_from_file_location("brain_edit_snapshot", HOOK)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    hook.JOURNAL_DIR = automation_writer.JOURNAL_DIR
    hook.SNAP_DIR = automation_writer.SNAP_DIR
    hook.INDEX = automation_writer.INDEX
    hook.WATCH_ROOTS = (str(automation_writer.CONFIG_DIR),)
    hook.JOURNAL_DIR.mkdir(parents=True, exist_ok=True)

    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": str(path), "content": "whatever"},
    })
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(payload)
    try:
        assert hook.main() == 0
    finally:
        sys.stdin = old_stdin
    # The hook records whether there was a file to put back, and the two
    # undos differ on exactly that — so the caller says which case it meant
    # and this is where the claim is checked, rather than in the assertion
    # the case is really about.
    line = json.loads(hook.INDEX.read_text(encoding="utf-8").splitlines()[-1])
    assert line["existed"] is existed, line


def record_a_call(ledger: Path, domain: str, service: str, data: dict) -> None:
    """Append one ledger row through the MCP server's own writer."""
    saved = dict(sys.modules)
    sys.path.insert(0, str(MCP_DIR))
    os.environ["BRAIN_ACTION_LEDGER"] = str(ledger)
    try:
        sys.modules.pop("ha_mcp_server", None)
        import ha_mcp_server  # noqa: PLC0415
        ha_mcp_server.ACTION_LEDGER = str(ledger)
        ha_mcp_server.record_action(domain, service, data)
    finally:
        sys.path.remove(str(MCP_DIR))
        os.environ.pop("BRAIN_ACTION_LEDGER", None)
        sys.modules.clear()
        sys.modules.update(saved)


class FixCase(PanelCase):
    """The panel, with a credential, and both Claude paths accounted for."""

    def setUp(self):
        super().setUp()
        tmp = Path(self.tmp.name)
        self._fix_olds = (engine.get_auth, engine.run_analyst, engine.run_agent,
                          automation_writer.CONFIG_DIR,
                          automation_writer.JOURNAL_DIR,
                          automation_writer.SNAP_DIR, automation_writer.INDEX,
                          actions.LEDGER_FILE)
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        # Nothing here may reach a real Claude. `run_agent` FAILS the test
        # unless a case opts into it: the plan path not touching it is the
        # claim, and a stub that quietly answered would hide a call.
        self.agent_calls = []
        engine.run_analyst = lambda *a, **k: self._analyst(*a, **k)
        engine.run_agent = lambda *a, **k: self._agent(*a, **k)
        self.analyst_reply = json.dumps(PLAN)
        self.agent_reply = json.dumps(
            {"ok": True, "summary": "Trigger corrected.",
             "changed": ["automation.hall — trigger corrected"],
             "verified": "Reloaded automations."})
        self.agent_allowed = False

        # A config tree and a journal beside it, both where the real ones
        # would be relative to each other.
        self.config = tmp / "config"
        self.config.mkdir(parents=True, exist_ok=True)
        automation_writer.CONFIG_DIR = str(self.config)
        automation_writer.JOURNAL_DIR = tmp / "edits"
        automation_writer.SNAP_DIR = automation_writer.JOURNAL_DIR / "snapshots"
        automation_writer.INDEX = automation_writer.JOURNAL_DIR / "index.jsonl"
        self.ledger = tmp / "actions.jsonl"
        actions.LEDGER_FILE = str(self.ledger)

    def tearDown(self):
        (engine.get_auth, engine.run_analyst, engine.run_agent,
         automation_writer.CONFIG_DIR, automation_writer.JOURNAL_DIR,
         automation_writer.SNAP_DIR, automation_writer.INDEX,
         actions.LEDGER_FILE) = self._fix_olds
        super().tearDown()

    # -- the two Claude paths ------------------------------------------
    def _analyst(self, prompt, system, *a, **k):
        self.analyst_prompt = prompt
        self.analyst_system = system
        return {"ok": True, "text": self.analyst_reply, "error": "", "meta": {}}

    def _agent(self, prompt, system, *a, **k):
        self.agent_calls.append(prompt)
        if not self.agent_allowed:
            raise AssertionError(
                "the plan path ran the TOOL-ENABLED Claude: it must never "
                "reach engine.run_agent")
        return {"ok": True, "text": self.agent_reply, "error": "", "meta": {}}

    # -- driving -------------------------------------------------------
    def work(self, client):
        """Run whatever the routes queued, on the panel's own worker."""
        async def drain():
            worker = asyncio.ensure_future(self.server._worker())
            await self.server.QUEUE.join()
            worker.cancel()
        return drain()

    def press(self, ts, verb, client):
        return client.post(f"/api/finding/{ts}/{verb}")


class TestPressingFixBuysAPlan(FixCase):
    def test_the_press_plans_and_changes_nothing(self):
        row = self.file_finding()

        async def body(client):
            answer = await self.press(row["ts"], "fix", client)
            self.assertEqual(answer.status, 200)
            data = await answer.json()
            # Claimed on disk before the run, so the card says what is
            # happening rather than looking untouched.
            self.assertEqual(data["findings"][0]["status"], "planning")
            await self.work(client)
            return None

        self.drive(body)
        entry = findings_store.get(row["ts"])
        self.assertEqual(entry["status"], "planned")
        self.assertEqual(entry["plan"]["steps"], PLAN["steps"])
        self.assertEqual(entry["plan"]["risk"], PLAN["risk"])
        self.assertTrue(entry["plan"]["can_fix"])
        self.assertEqual(self.agent_calls, [],
                         "the plan must not reach the tool-enabled run")
        # And it is the plan contract that was sent, not the fix's.
        self.assertEqual(self.analyst_system, fixer.PLAN_SYSTEM)

    def test_the_plan_run_is_the_readonly_one(self):
        """`run_analyst` holds reading tools and `run_agent` holds the rest.

        Asserted at the call rather than by reading the prompt: what the
        run may do is decided by which function is called, and the prompt
        is only what it is asked to do with it.
        """
        row = self.file_finding()
        seen = []
        engine.run_analyst = lambda *a, **k: (
            seen.append("analyst"),
            {"ok": True, "text": json.dumps(PLAN), "error": "", "meta": {}})[1]

        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)

        self.drive(body)
        self.assertEqual(seen, ["analyst"])

    def test_a_second_press_while_it_is_looking_is_refused(self):
        row = self.file_finding()

        async def body(client):
            first = await self.press(row["ts"], "fix", client)
            self.assertEqual(first.status, 200)
            again = await self.press(row["ts"], "fix", client)
            self.assertEqual(again.status, 409)
            await self.work(client)

        self.drive(body)

    def test_a_run_that_failed_puts_the_row_back_rather_than_wedging_it(self):
        """A finding stuck in `planning` is one no button is offered on."""
        row = self.file_finding()
        engine.run_analyst = lambda *a, **k: {
            "ok": False, "text": "", "error": "claude timed out", "meta": {}}

        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)

        self.drive(body)
        entry = findings_store.get(row["ts"])
        self.assertEqual(entry["status"], "open")
        self.assertIn("claude timed out", entry["result"])

    def test_an_unreadable_plan_is_not_permission(self):
        row = self.file_finding()
        self.analyst_reply = "I had a look and it all seems fine really"

        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)
            answer = await self.press(row["ts"], "apply", client)
            # No steps, so nothing to approve and nothing to send.
            self.assertEqual(answer.status, 409)

        self.drive(body)
        entry = findings_store.get(row["ts"])
        self.assertEqual(entry["status"], "planned")
        self.assertFalse(entry["plan"]["can_fix"])
        self.assertEqual(entry["plan"]["steps"], [])
        self.assertEqual(self.agent_calls, [])


class TestApplyAndCancel(FixCase):
    def plan_it(self, row):
        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)
        self.drive(body)

    def test_apply_sends_the_approved_plan_to_the_agent(self):
        row = self.file_finding()
        self.plan_it(row)
        self.agent_allowed = True

        async def body(client):
            answer = await self.press(row["ts"], "apply", client)
            self.assertEqual(answer.status, 200)
            data = await answer.json()
            self.assertEqual(data["findings"][0]["status"], "fixing")
            await self.work(client)

        self.drive(body)
        self.assertEqual(len(self.agent_calls), 1)
        prompt = self.agent_calls[0]
        self.assertIn(PLAN["steps"][0], prompt)
        self.assertIn("do exactly these steps and nothing else", prompt)
        self.assertEqual(findings_store.get(row["ts"])["status"], "fixed")

    def test_apply_without_a_plan_is_refused(self):
        row = self.file_finding()

        async def body(client):
            answer = await self.press(row["ts"], "apply", client)
            self.assertEqual(answer.status, 409)

        self.drive(body)
        self.assertEqual(self.agent_calls, [])

    def test_a_plan_that_needs_you_offers_nothing_to_apply(self):
        row = self.file_finding()
        self.analyst_reply = json.dumps({
            "can_fix": True, "needs_you": True,
            "steps": ["Replace the CR2032"],
            "summary": "That sensor's battery is flat."})
        self.plan_it(row)

        entry = findings_store.get(row["ts"])
        self.assertTrue(entry["plan"]["needs_you"])
        self.assertFalse(entry["plan"]["can_fix"])
        # The steps are dropped with the refusal: a list of changes under
        # "brAIn cannot do this" reads as a plan somebody can approve.
        self.assertEqual(entry["plan"]["steps"], [])

        async def body(client):
            answer = await self.press(row["ts"], "apply", client)
            self.assertEqual(answer.status, 409)

        self.drive(body)
        self.assertEqual(self.agent_calls, [])

    def test_cancel_returns_to_open_and_keeps_the_plan(self):
        row = self.file_finding()
        self.plan_it(row)

        async def body(client):
            answer = await self.press(row["ts"], "cancel", client)
            self.assertEqual(answer.status, 200)

        self.drive(body)
        entry = findings_store.get(row["ts"])
        self.assertEqual(entry["status"], "open")
        self.assertEqual(entry["plan"]["steps"], PLAN["steps"],
                         "the plan cost a run; reading it again must not")

    def test_cancelling_twice_is_refused_rather_than_silently_reopening(self):
        row = self.file_finding()
        self.plan_it(row)

        async def body(client):
            self.assertEqual((await self.press(row["ts"], "cancel", client)).status, 200)
            self.assertEqual((await self.press(row["ts"], "cancel", client)).status, 409)

        self.drive(body)


class TestUndoingAFix(FixCase):
    """The durable undo, over the journal and the ledger the fix really writes."""

    def fixed_row(self, started, ended, files=1, calls=1):
        row = self.file_finding()
        findings_store.set_status(row["ts"], "fixed", result="Done.")
        findings_store.set_fix_window(row["ts"], started, None)
        findings_store.set_fix_window(row["ts"], None, ended,
                                      files=files, calls=calls)
        return findings_store.get(row["ts"])

    def test_it_puts_a_journalled_edit_back_and_reloads(self):
        target = self.config / "automations.yaml"
        target.write_text("- id: brain_before\n", encoding="utf-8")
        started = __import__("time").time() - 5
        journal_an_edit(target)
        target.write_text("- id: brain_after\n", encoding="utf-8")
        ended = __import__("time").time() + 5
        row = self.fixed_row(started, ended)

        reloads = []

        async def body(client):
            import ha_data
            old = ha_data.call_core_service

            async def fake(domain, service, data=None):
                reloads.append((domain, service))
                return {}

            ha_data.call_core_service = fake
            try:
                answer = await self.press(row["ts"], "unfix", client)
                self.assertEqual(answer.status, 200)
            finally:
                ha_data.call_core_service = old

        self.drive(body)
        self.assertEqual(target.read_text(), "- id: brain_before\n")
        self.assertEqual(reloads, [("automation", "reload")])
        entry = findings_store.get(row["ts"])
        self.assertEqual(entry["status"], "open")
        self.assertIn("automations.yaml", entry["result"])

    def test_a_file_the_fix_CREATED_is_removed_again(self):
        target = self.config / "packages" / "brain_new.yaml"
        target.parent.mkdir(parents=True, exist_ok=True)
        started = __import__("time").time() - 5
        journal_an_edit(target, existed=False)
        target.write_text("whatever: 1\n", encoding="utf-8")
        ended = __import__("time").time() + 5
        row = self.fixed_row(started, ended)

        async def body(client):
            answer = await self.press(row["ts"], "unfix", client)
            self.assertEqual(answer.status, 200)

        self.drive(body)
        self.assertFalse(target.exists(),
                         "an edit that created a file is undone by removing it")

    def test_service_calls_are_listed_and_never_reversed(self):
        started = __import__("time").time() - 5
        record_a_call(self.ledger, "light", "turn_off",
                      {"entity_id": "light.hall"})
        ended = __import__("time").time() + 5
        row = self.fixed_row(started, ended, files=0, calls=1)

        called = []

        async def body(client):
            import ha_data
            old = ha_data.call_core_service

            async def fake(domain, service, data=None):
                called.append((domain, service))
                return {}

            ha_data.call_core_service = fake
            try:
                await self.press(row["ts"], "unfix", client)
            finally:
                ha_data.call_core_service = old

        self.drive(body)
        result = findings_store.get(row["ts"])["result"]
        self.assertIn("light.turn_off on light.hall", result)
        self.assertIn("NOT reversed", result)
        self.assertEqual(called, [],
                         "an undo must not call a service to 'reverse' one")

    def test_an_empty_window_says_so_rather_than_claiming_a_success(self):
        now = __import__("time").time()
        row = self.fixed_row(now - 5, now, files=0, calls=0)

        async def body(client):
            answer = await self.press(row["ts"], "unfix", client)
            self.assertEqual(answer.status, 200)

        self.drive(body)
        entry = findings_store.get(row["ts"])
        self.assertEqual(entry["status"], "open")
        self.assertIn("nothing to put back", entry["result"])

    def test_it_corrects_the_memory_line_the_fix_wrote(self):
        """The fix queued "brAIn fixed this on …" when it finished, and an
        undo makes that false — in the queue or in the document."""
        now = __import__("time").time()
        row = self.fixed_row(now - 5, now, files=0, calls=0)
        findings_store.set_status(row["ts"], "fixed", result="Done.",
                                  changed=["automation.hall — trigger fixed"])

        async def body(client):
            await self.press(row["ts"], "unfix", client)

        self.drive(body)
        lines = self.queued_memory()
        self.assertTrue(any("undid its own fix" in line for line in lines),
                        lines)

    def test_a_fix_that_changed_nothing_leaves_memory_alone(self):
        """No claim was made, so there is nothing to correct."""
        now = __import__("time").time()
        row = self.fixed_row(now - 5, now, files=0, calls=0)

        async def body(client):
            await self.press(row["ts"], "unfix", client)

        self.drive(body)
        self.assertEqual(self.queued_memory(), [])

    def test_a_fix_from_before_the_window_says_it_cannot_tell(self):
        """An add-on updated while a fixed row sat on the tab. Answering
        "nothing to put back" would put the row back to open while the
        change stands, which is the wrong half of `clear_resolved`'s
        distinction with somebody's house on the other side of it."""
        row = self.file_finding()
        findings_store.set_status(row["ts"], "fixed", result="Done.")

        async def body(client):
            answer = await self.press(row["ts"], "unfix", client)
            self.assertEqual(answer.status, 409)
            self.assertIn("did not record", await answer.text())

        self.drive(body)
        self.assertEqual(findings_store.get(row["ts"])["status"], "fixed")

    def test_it_is_refused_on_a_row_brain_never_changed(self):
        row = self.file_finding()

        async def body(client):
            answer = await self.press(row["ts"], "unfix", client)
            self.assertEqual(answer.status, 409)

        self.drive(body)

    def test_the_panels_own_writes_are_not_the_fixs_to_undo(self):
        """The journal is shared. An accepted proposal landing in the same
        minute is a different press with its own undo, so keying on the
        hook's tool names is what keeps this button about the fix."""
        target = self.config / "automations.yaml"
        target.write_text("- id: mine\n", encoding="utf-8")
        started = __import__("time").time() - 5
        automation_writer.snapshot(target)          # tool: "brain-panel"
        target.write_text("- id: theirs\n", encoding="utf-8")
        ended = __import__("time").time() + 5

        self.assertEqual(unfix.journal_entries(started, ended), [])


class TestWhatTheFixRecords(FixCase):
    def test_the_window_and_the_counts_are_stamped_on_the_row(self):
        """The two numbers the card reads before offering the undo."""
        row = self.file_finding()
        self.analyst_reply = json.dumps(PLAN)

        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)
            self.agent_allowed = True
            await self.press(row["ts"], "apply", client)
            await self.work(client)

        self.drive(body)
        entry = findings_store.get(row["ts"])
        self.assertEqual(entry["status"], "fixed")
        self.assertGreater(entry["fix_started"], 0)
        self.assertGreaterEqual(entry["fix_ended"], entry["fix_started"])
        # Nothing was journalled or called by the stub, and the honest
        # answer to that is zero rather than an absent key.
        self.assertEqual(entry["fix_files"], 0)
        self.assertEqual(entry["fix_calls"], 0)

    def test_a_retry_replaces_the_window_rather_than_widening_it(self):
        row = self.file_finding()
        findings_store.set_fix_window(row["ts"], 100.0, None)
        findings_store.set_fix_window(row["ts"], None, 200.0, files=3, calls=4)
        after = findings_store.set_fix_window(row["ts"], 900.0, None)
        self.assertEqual(after["fix_started"], 900.0)
        self.assertEqual(after["fix_ended"], 0)
        self.assertEqual(after["fix_files"], 0)
        self.assertEqual(after["fix_calls"], 0)


class TestTheStatusTablesAgree(unittest.TestCase):
    """Two new words, and every table that has to have an opinion on them."""

    def test_both_are_statuses_and_neither_is_a_producers(self):
        for status in ("planning", "planned"):
            self.assertIn(status, findings_store.STATUSES, status)
            self.assertNotIn(status, findings_store.PRE_STATUSES, status)

    def test_a_planned_row_is_live_and_waiting_on_you(self):
        # It is a decision — Apply or Cancel — which is exactly what the
        # badge counts.
        self.assertIn("planned", findings_store.LIVE_STATUSES)
        self.assertIn("planned", findings_store.UNSETTLED_STATUSES)

    def test_a_run_in_flight_is_live_and_is_not_a_decision(self):
        self.assertIn("planning", findings_store.LIVE_STATUSES)
        self.assertNotIn("planning", findings_store.UNSETTLED_STATUSES)

    def test_a_planned_row_clears_when_the_check_stops_reporting_it(self):
        """A plan is a sentence about a problem: with the problem gone the
        plan is about nothing, so the row goes the way an open one does."""
        self.assertIn("planned", findings_store.CLEARABLE)

    def test_a_run_in_flight_is_never_cleared_out_from_under_itself(self):
        self.assertNotIn("planning", findings_store.CLEARABLE)
        self.assertNotIn("planning", findings_store.MUTE_CLEARS)
        self.assertNotIn("planned", findings_store.MUTE_CLEARS)


class TestClearingAPlannedRow(unittest.TestCase):
    """The table above says it may; this drives the store to prove it does."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.SETTLED_FILE = tmp / "settled.json"
        findings_store.STATE_FILE = tmp / "nowhere" / ".brain" / "s.json"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def test_the_check_going_quiet_takes_the_planned_row_with_it(self):
        entry, _ = findings_store.add("the hall sensor is stuck",
                                      source="check:devices")
        findings_store.set_plan(entry["ts"], PLAN)
        self.assertEqual(findings_store.get(entry["ts"])["status"], "planned")

        gone = findings_store.clear_resolved({"check:devices"}, set())
        self.assertEqual([g["ts"] for g in gone], [entry["ts"]])
        self.assertIsNone(findings_store.get(entry["ts"]))

    def test_a_plan_arriving_after_the_row_moved_on_is_dropped(self):
        """`record_triage`'s rule: a verdict that took four minutes must not
        drag back a finding somebody settled in the meantime."""
        entry, _ = findings_store.add("the hall sensor is stuck")
        findings_store.set_status(entry["ts"], "fixed")
        self.assertIsNone(findings_store.set_plan(entry["ts"], PLAN))
        self.assertEqual(findings_store.get(entry["ts"])["status"], "fixed")


class TestThePlanContract(unittest.TestCase):
    """`fixer` is pure, so these are the cheap half of the same claims."""

    def test_a_refusal_carries_no_steps(self):
        plan = fixer.parse_plan(json.dumps(
            {"can_fix": False, "steps": ["do the thing"], "summary": "no"}))
        self.assertFalse(plan["can_fix"])
        self.assertEqual(plan["steps"], [])

    def test_no_steps_is_not_something_to_apply(self):
        plan = fixer.parse_plan(json.dumps({"can_fix": True, "steps": []}))
        self.assertFalse(plan["can_fix"])

    def test_an_unreadable_reply_carries_its_tail(self):
        plan = fixer.parse_plan("well anyway I had a look at it")
        self.assertFalse(plan["can_fix"])
        self.assertIn("had a look at it", plan["summary"])

    def test_the_fix_prompt_carries_the_plan_and_the_refusal_to_improvise(self):
        prompt = fixer.build_prompt({"text": "X"}, plan=PLAN)
        self.assertIn(PLAN["steps"][0], prompt)
        self.assertIn(PLAN["risk"], prompt)
        self.assertIn("Do not substitute a different change", prompt)

    def test_no_plan_leaves_the_prompt_the_fix_it_always_was(self):
        self.assertNotIn("THE PLAN", fixer.build_prompt({"text": "X"}))

    def test_both_runs_are_given_the_same_evidence(self):
        finding = {"text": "X", "detail": "since 3 Sep",
                   "entity_id": "binary_sensor.hall", "fix": "Re-pair it"}
        plan_prompt = fixer.build_plan_prompt(finding)
        fix_prompt = fixer.build_prompt(finding, plan=PLAN)
        for fact in ("since 3 Sep", "binary_sensor.hall", "Re-pair it"):
            self.assertIn(fact, plan_prompt, fact)
            self.assertIn(fact, fix_prompt, fact)

    def test_the_plan_prompt_says_out_loud_that_nothing_is_changing(self):
        self.assertIn("Change NOTHING on this run",
                      fixer.build_plan_prompt({"text": "X"}))


class TestTheListingInTheTerminal(unittest.TestCase):
    """`brain findings`' own printing, lifted out of the script and driven.

    The CLI can now start a plan, so it has to be able to show one — a
    press that opens a decision on a surface that cannot render it is the
    "a button that exists only in prose" rule with the prose in the wrong
    terminal. And nothing had ever executed this block, which is the exact
    history `tests/test_cli_report_blocks.py` was written about: its
    payload rides in an environment variable and the script is the
    heredoc, so this runs it the way the image does.
    """

    SCRIPT = BASE_DIR / "brain" / "scripts" / "brain-findings.sh"

    def print_it(self, payload: dict) -> str:
        src = self.SCRIPT.read_text(encoding="utf-8")
        start = src.index("PYEOF'\n") + len("PYEOF'\n")
        block = src[start:src.index("\nPYEOF\n", start)]
        import subprocess  # noqa: PLC0415 — one caller, one import
        env = dict(os.environ, BRAIN_FINDINGS_JSON=json.dumps(payload))
        proc = subprocess.run([sys.executable, "-c", block], env=env,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        return proc.stdout

    def row(self, **over):
        base = {"ts": 1700000000, "text": "Hall lights can never fire",
                "detail": "", "fix": "", "severity": "warning",
                "status": "planned", "snoozed_until": 0, "plan": PLAN,
                "fix_files": 0, "fix_calls": 0}
        base.update(over)
        return {"findings": [base], "hypotheses": []}

    def test_a_planned_row_prints_the_steps_and_how_to_answer(self):
        out = self.print_it(self.row())
        self.assertIn(PLAN["steps"][0][:40], out)
        self.assertIn(PLAN["risk"], out)
        self.assertIn("brain findings apply 1700000000", out)
        self.assertIn("brain findings cancel 1700000000", out)

    def test_a_refused_plan_offers_no_apply(self):
        out = self.print_it(self.row(plan={
            "can_fix": False, "needs_you": True, "steps": [], "risk": "",
            "summary": "The CR2032 has to be replaced by hand."}))
        self.assertIn("will not make this change itself", out)
        self.assertNotIn("findings apply", out)

    def test_a_fixed_row_says_what_it_changed_before_the_undo(self):
        out = self.print_it(self.row(status="fixed", plan={},
                                     fix_files=2, fix_calls=3))
        self.assertIn("2 file(s)", out)
        self.assertIn("3 service call(s)", out)
        self.assertIn("undo", out)

    def test_a_row_being_looked_at_says_nothing_has_changed(self):
        out = self.print_it(self.row(status="planning", plan={}))
        self.assertIn("nothing yet", out)


class TestTheRevertersContainment(unittest.TestCase):
    """`unfix` reuses `automation_writer.revert`, which had to widen to a
    tree — so the tree has to be a real one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "config"
        (self.root / "packages").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_nested_file_is_in_the_config_folder(self):
        self.assertTrue(automation_writer.in_config_tree(
            self.root / "packages" / "heating.yaml", str(self.root)))

    def test_a_path_that_climbs_out_is_not(self):
        self.assertFalse(automation_writer.in_config_tree(
            self.root / ".." / "etc" / "passwd", str(self.root)))
        self.assertFalse(automation_writer.in_config_tree(
            Path("/etc/passwd"), str(self.root)))

    def test_the_folder_itself_is_not_a_file_in_it(self):
        self.assertFalse(automation_writer.in_config_tree(
            self.root, str(self.root)))

    def test_a_sibling_with_a_shared_prefix_is_not_inside(self):
        self.assertFalse(automation_writer.in_config_tree(
            Path(str(self.root) + "-backup") / "x.yaml", str(self.root)))


if __name__ == "__main__":
    unittest.main()
