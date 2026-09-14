#!/usr/bin/env python3
"""`brain doctor --deep` — the stages, their refusals, and their cleanup.

Every test here drives the real stage function. A deep run's whole value is
that it does the thing rather than describing it, so a test that asserted
the source mentioned a timeout would be the `pop`-line failure with the
subject changed.

What each class holds, and the mutation that breaks it:

  the report shape      make a skipped stage count as a pass -> a report
                        that says every face works on a house where the
                        listener is off
  preconditions         run a stage whose precondition failed -> eight
                        identical auth failures instead of one
  snapshot_claude       accept a reply the extractor cannot read -> the
                        card path's own "unparseable" goes unreported
  analyst_tools         accept `call_service: ran` -> an unattended run is
                        allowed to change the house and the check says ok
  automation_task       treat an unclaimed file as a slow answer -> the
                        report blames the model when nothing is listening
  memory                skip the FORGET pass -> a self-test writes into
                        somebody's memory and leaves it there
  findings_undo         skip the cleanup -> a synthetic finding on the
                        Findings tab and a key in the settled ledger
  fixer_dry             ignore protected_entities -> a self-test renames an
                        entity the configuration said not to touch
  the chat stage        evict to make room -> a check closes somebody's
                        conversation to prove the chat works
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
FAKE_CHAT = Path(__file__).resolve().parent / "fake_claude_chat.py"
sys.path.insert(0, str(PANEL))


def envelope(text: str, ok: bool = True) -> dict:
    return {"ok": ok, "text": text, "error": "" if ok else text,
            "meta": {"num_turns": 1}}


class FakeHooks:
    """Hooks that record rather than act, for the stages that do not act.

    The three stages whose hooks matter — memory, findings and the fixer —
    are driven against the real panel implementations in their own classes
    below; this is what the other five get so a test can say what came back
    from Home Assistant without standing one up.
    """

    def __init__(self, **over):
        self.ws_calls: list[list[dict]] = []
        self.ws_replies: list = []
        self.usage: list = []
        self.queued: list[tuple[str, str]] = []
        self.dropped: list[tuple[str, str]] = []
        self.pending = 0
        self.memory = ""
        self.consolidate_result = (True, "")
        self.model = ""
        self.options = {}
        for key, value in over.items():
            setattr(self, key, value)

    # -- the panel's own operations --------------------------------------
    async def end_finding(self, finding, spec, note):
        return {}, ""

    async def undo_finding(self, entry):
        return True, {}

    def queue_memory(self, fact, source="doctor"):
        self.queued.append((source, fact))
        self.pending += 1

    def drop_memory(self, source, fact):
        self.dropped.append((source, fact))
        return True

    def inbox_pending(self):
        return self.pending

    def memory_text(self):
        return self.memory

    def consolidate(self):
        return self.consolidate_result

    def record_usage(self, result, run_id):
        self.usage.append(run_id)
        return {"total": 0}

    async def ws(self, commands):
        self.ws_calls.append(commands)
        if callable(self.ws_replies):
            return self.ws_replies(commands)
        return list(self.ws_replies) or [None] * len(commands)


def hooks(**over):
    import doctor
    fake = FakeHooks(**over)
    return doctor.Hooks(
        end_finding=fake.end_finding, undo_finding=fake.undo_finding,
        queue_memory=fake.queue_memory, drop_memory=fake.drop_memory,
        inbox_pending=fake.inbox_pending, memory_text=fake.memory_text,
        consolidate=fake.consolidate, record_usage=fake.record_usage,
        ws=fake.ws, model=fake.model, options=fake.options), fake


class DoctorCase(unittest.IsolatedAsyncioTestCase):
    """A fresh /data and a fresh module per test."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        os.environ["BRAIN_DOCTOR_DEEP_FILE"] = os.path.join(base, "deep.json")
        os.environ["BRAIN_SHARED_DIR"] = os.path.join(base, "shared")
        os.environ["BRAIN_FINDINGS_FILE"] = os.path.join(base, "findings.json")
        os.environ["BRAIN_FINDINGS_SETTLED"] = os.path.join(base, "settled.json")
        os.environ["BRAIN_FINDINGS_STATE"] = os.path.join(base, "state.json")
        os.environ["BRAIN_FINDINGS_INBOX"] = os.path.join(base, "finbox")
        os.environ["BRAIN_JOURNAL_FILE"] = os.path.join(base, "journal.jsonl")
        os.environ["BRAIN_EDIT_JOURNAL"] = os.path.join(base, "edits")
        os.environ["BRAIN_PROTECTED_ENTITIES"] = ""
        import journal
        importlib.reload(journal)
        import findings_store
        self.findings = importlib.reload(findings_store)
        import doctor
        self.doctor = importlib.reload(doctor)

    async def asyncTearDown(self):
        self.tmp.cleanup()


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

class TestTheReport(DoctorCase):
    async def test_every_stage_is_reported_not_just_the_first_break(self):
        """A failure must not stop the walk: "the chat works and the
        listener does not" is the answer, and the first break hides it."""
        d = self.doctor
        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = self._stage(d._fail("no"))
        h, _ = hooks()
        out = await d.run_deep(h)
        self.assertEqual(len(out["stages"]), len(d.STAGE_NAMES))
        self.assertEqual(out["verdict"], "failed")
        self.assertEqual(out["failed_stage"], "snapshot_claude")

    async def test_a_skipped_stage_is_not_a_pass(self):
        """Optional is not broken — and it is not working either."""
        d = self.doctor
        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = self._stage(d._skip("it is off"))
        out = await d.run_deep(hooks()[0])
        self.assertEqual(out["counts"], {"ok": 0, "failed": 0,
                                         "skipped": len(d.STAGE_NAMES)})
        self.assertEqual(out["verdict"], "skipped")

    async def test_a_stage_that_raises_is_the_stages_failure_not_the_runs(self):
        d = self.doctor

        async def boom(_hooks):
            raise RuntimeError("kaboom")

        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = self._stage(d._ok("fine"))
        d.RUNNERS["chat"] = boom
        out = await d.run_deep(hooks()[0])
        chat = [s for s in out["stages"] if s["name"] == "chat"][0]
        self.assertEqual(chat["state"], "failed")
        self.assertIn("kaboom", chat["sentence"])
        self.assertEqual(out["counts"]["ok"], len(d.STAGE_NAMES) - 1)

    async def test_progress_is_called_after_every_stage(self):
        """The CLI prints each line as it lands rather than a wall at the
        end, which is only possible if the runner says so as it goes."""
        d = self.doctor
        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = self._stage(d._ok("fine"))
        seen = []
        await d.run_deep(hooks()[0], progress=lambda p: seen.append(len(p["stages"])))
        self.assertEqual(seen, list(range(1, len(d.STAGE_NAMES) + 1)))

    async def test_only_runs_the_named_stages(self):
        d = self.doctor
        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = self._stage(d._ok("fine"))
        out = await d.run_deep(hooks()[0], only=["findings_undo"])
        self.assertEqual([s["name"] for s in out["stages"]], ["findings_undo"])

    async def test_every_stage_is_journaled(self):
        import journal
        d = self.doctor
        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = self._stage(d._ok("fine"))
        await d.run_deep(hooks()[0])
        rows = [r for r in journal.tail(0) if r.get("source") == "doctor"]
        self.assertEqual(len(rows), len(d.STAGE_NAMES))
        self.assertEqual({r["extra"]["stage"] for r in rows},
                         set(d.STAGE_NAMES))

    async def test_the_summary_is_three_facts_and_not_the_transcript(self):
        d = self.doctor
        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = self._stage(d._ok("fine"))
        d.RUNNERS["memory"] = self._stage(d._fail("nope"))
        out = await d.run_deep(hooks()[0])
        d.save(out)
        summary = d.summary()
        self.assertEqual(summary["verdict"], "failed")
        self.assertEqual(summary["failed_stage"], "memory")
        self.assertNotIn("stages", summary)

    async def test_no_run_yet_is_an_empty_summary_not_a_verdict(self):
        self.assertEqual(self.doctor.summary(),
                         {"ran_at": 0, "verdict": "", "failed_stage": ""})

    @staticmethod
    def _stage(result):
        async def run(_hooks):
            return dict(result)
        return run


class TestPreconditions(DoctorCase):
    async def test_a_stage_whose_precondition_failed_is_skipped_with_the_reason(self):
        d = self.doctor
        ran = []

        def marker(name, result):
            async def run(_hooks):
                ran.append(name)
                return dict(result)
            return run

        for name in d.STAGE_NAMES:
            d.RUNNERS[name] = marker(name, d._ok("fine"))
        d.RUNNERS["snapshot_claude"] = marker("snapshot_claude", d._fail("dead"))
        out = await d.run_deep(hooks()[0])
        by = {s["name"]: s for s in out["stages"]}
        self.assertEqual(by["analyst_tools"]["state"], "skipped")
        self.assertIn("snapshot_claude", by["analyst_tools"]["sentence"])
        self.assertEqual(by["memory"]["state"], "skipped")
        # The fixer needs the analyst, which was itself skipped.
        self.assertEqual(by["fixer_dry"]["state"], "skipped")
        self.assertNotIn("analyst_tools", ran)
        self.assertNotIn("fixer_dry", ran)
        # And the ones that stand on their own still ran.
        self.assertIn("chat", ran)
        self.assertIn("findings_undo", ran)


# ---------------------------------------------------------------------------
# snapshot_claude and analyst_tools
# ---------------------------------------------------------------------------

class TestSnapshotStage(DoctorCase):
    async def one(self, result):
        import engine
        h, fake = hooks()
        old = engine.run_claude
        engine.run_claude = lambda *a, **k: result
        try:
            return await self.doctor.stage_snapshot_claude(h), fake
        finally:
            engine.run_claude = old

    async def test_the_happy_path(self):
        out, fake = await self.one(envelope('{"doctor": "ok"}'))
        self.assertEqual(out["state"], "ok")
        self.assertEqual(fake.usage, ["doctor-snapshot"])

    async def test_a_reply_the_extractor_cannot_read_is_a_failure(self):
        out, _ = await self.one(envelope("Sure! Here you go."))
        self.assertEqual(out["state"], "failed")
        self.assertIn("unparseable", out["sentence"])

    async def test_the_wrong_json_is_a_failure_too(self):
        out, _ = await self.one(envelope('{"doctor": "fine"}'))
        self.assertEqual(out["state"], "failed")

    async def test_a_timeout_is_reported_as_a_timeout_and_never_as_auth(self):
        out, _ = await self.one(
            {"ok": False, "text": "", "meta": {},
             "error": "Claude timed out after 120s"})
        self.assertEqual(out["state"], "failed")
        self.assertIn("passed its limit", out["sentence"])
        self.assertNotIn("authenticate", out["sentence"])

    async def test_a_dead_credential_names_where_to_sign_in(self):
        out, _ = await self.one(
            {"ok": False, "text": "", "meta": {},
             "error": "OAuth token expired: 401"})
        self.assertIn("Claude account", out["sentence"])

    async def test_a_missing_cli_says_so(self):
        out, _ = await self.one(
            {"ok": False, "text": "", "meta": {},
             "error": "claude CLI not found"})
        self.assertIn("not in this image", out["sentence"])


class TestAnalystStage(DoctorCase):
    async def one(self, result):
        import engine
        h, fake = hooks()
        old = engine.run_analyst
        seen = {}

        def run(prompt, system, *a, **k):
            seen["prompt"] = prompt
            seen["args"] = a
            return result

        engine.run_analyst = run
        try:
            return await self.doctor.stage_analyst_tools(h), seen
        finally:
            engine.run_analyst = old

    async def test_a_read_that_worked_and_a_call_that_was_refused(self):
        out, seen = await self.one(
            envelope('{"areas": 7, "call_service": "refused"}'))
        self.assertEqual(out["state"], "ok")
        self.assertIn("7 areas", out["sentence"])
        self.assertIn("get_areas", seen["prompt"])
        self.assertIn("call_service", seen["prompt"])
        # It claims its own source, so the Chats rail does not offer it.
        self.assertIn("doctor", seen["args"])

    async def test_an_acting_tool_that_RAN_is_the_loudest_failure_here(self):
        out, _ = await self.one(envelope('{"areas": 7, "call_service": "ran"}'))
        self.assertEqual(out["state"], "failed")
        self.assertIn("deny list", out["sentence"])

    async def test_no_areas_means_mcp_is_not_reaching_the_model(self):
        out, _ = await self.one(
            envelope('{"areas": null, "call_service": "refused"}'))
        self.assertEqual(out["state"], "failed")
        self.assertIn("MCP server", out["sentence"])

    async def test_an_unreadable_reply_says_nothing_can_be_said(self):
        out, _ = await self.one(envelope("I called get_areas and got 7."))
        self.assertEqual(out["state"], "failed")
        self.assertIn("nothing can be said", out["sentence"])


# ---------------------------------------------------------------------------
# The automation bridge
# ---------------------------------------------------------------------------

class TestAutomationTaskStage(DoctorCase):
    async def test_it_is_skipped_when_the_integration_is_off(self):
        h, _ = hooks(options={"enable_automation_integration": False})
        out = await self.doctor.stage_automation_task(h)
        self.assertEqual(out["state"], "skipped")
        self.assertIn("enable_automation_integration", out["sentence"])

    async def test_no_task_folder_is_a_listener_that_never_started(self):
        h, _ = hooks()
        out = await self.doctor.stage_automation_task(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("never started", out["sentence"])

    async def test_an_unclaimed_task_names_the_listener_not_the_model(self):
        """director_check's rule: the claim is a rename, so an untouched
        file is proof rather than a slow answer."""
        d = self.doctor
        d.TASKS_DIR.mkdir(parents=True)
        d.CLAIM_GRACE_S = 0.4
        h, _ = hooks()
        out = await d.stage_automation_task(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("Nothing claimed", out["sentence"])
        self.assertIn("renaming", out["sentence"])
        # And it left nothing behind for a listener to pick up later.
        self.assertEqual(list(d.TASKS_DIR.glob("*.json")), [])

    async def test_claimed_and_never_answered_is_a_different_sentence(self):
        d = self.doctor
        d.TASKS_DIR.mkdir(parents=True)
        d.CLAIM_GRACE_S = 5
        d.TIMEOUTS["automation_task"] = 1
        h, _ = hooks()
        task = asyncio.create_task(d.stage_automation_task(h))
        await self._claim(d, answer=None)
        out = await task
        self.assertEqual(out["state"], "failed")
        self.assertIn("took the task and nothing came back", out["sentence"])

    async def test_the_happy_path_reads_the_result_file(self):
        d = self.doctor
        d.TASKS_DIR.mkdir(parents=True)
        d.CLAIM_GRACE_S = 5
        h, _ = hooks()
        task = asyncio.create_task(d.stage_automation_task(h))
        await self._claim(d, answer={"status": "completed", "result": "READY"})
        out = await task
        self.assertEqual(out["state"], "ok")
        self.assertIn("READY", out["detail"])
        # Neither folder keeps the stage's own file. (The `.work.` name our
        # stand-in listener renamed it to is the listener's to delete, and
        # the real one does.)
        self.assertEqual(list(d.TASKS_DIR.glob("*.json")), [])
        self.assertEqual(list(d.TASK_RESULTS_DIR.glob("*")), [])

    async def test_the_task_file_is_the_bridges_own_shape(self):
        d = self.doctor
        d.TASKS_DIR.mkdir(parents=True)
        d.CLAIM_GRACE_S = 5
        h, _ = hooks()
        task = asyncio.create_task(d.stage_automation_task(h))
        written = await self._claim(
            d, answer={"status": "completed", "result": "READY"})
        out = await task
        self.assertEqual(out["state"], "ok")
        self.assertEqual(set(written) & {"id", "prompt", "ts", "timeout"},
                         {"id", "prompt", "ts", "timeout"})
        self.assertIsInstance(written["timeout"], int)

    async def _claim(self, d, answer):
        """Stand in for the listener: rename the file, then answer."""
        for _ in range(100):
            found = list(d.TASKS_DIR.glob("*.json"))
            if found:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("the stage never wrote a task")
        path = found[0]
        body = json.loads(path.read_text())
        path.rename(path.with_suffix(".work.1"))
        if answer is not None:
            d.TASK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            (d.TASK_RESULTS_DIR / f"{body['id']}.json").write_text(
                json.dumps({"id": body["id"], **answer}))
        return body


# ---------------------------------------------------------------------------
# Assist
# ---------------------------------------------------------------------------

class TestAssistStage(DoctorCase):
    REGISTRY = [
        {"entity_id": "conversation.home_assistant", "platform": "conversation"},
        {"entity_id": "conversation.brain_agent", "platform": "brain"},
    ]

    async def test_it_is_skipped_when_assist_is_off(self):
        h, _ = hooks(options={"enable_assist_integration": False})
        out = await self.doctor.stage_assist(h)
        self.assertEqual(out["state"], "skipped")
        self.assertIn("enable_assist_integration", out["sentence"])

    async def test_no_conversation_entity_is_a_failure_naming_the_integration(self):
        h, _ = hooks(ws_replies=lambda cmds: [[]])
        out = await self.doctor.stage_assist(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("Devices & services", out["sentence"])

    async def test_the_agent_is_read_from_the_registry_never_guessed(self):
        """A renamed device moves the entity id, and a hardcoded one would
        report a working Assist as broken."""
        rows = [{"entity_id": "conversation.upstairs_helper", "platform": "brain"}]
        asked = {}

        def reply(cmds):
            if cmds[0]["type"] == "config/entity_registry/list":
                return [rows]
            asked.update(cmds[0])
            return [{"response": {"speech": {"plain": {"speech": "OK"}}}}]

        h, _ = hooks(ws_replies=reply)
        out = await self.doctor.stage_assist(h)
        self.assertEqual(out["state"], "ok")
        self.assertEqual(asked["agent_id"], "conversation.upstairs_helper")
        self.assertEqual(asked["type"], "conversation/process")

    async def test_a_refused_call_is_a_failure(self):
        def reply(cmds):
            if cmds[0]["type"] == "config/entity_registry/list":
                return [self.REGISTRY]
            return [None]

        h, _ = hooks(ws_replies=reply)
        out = await self.doctor.stage_assist(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("refused the conversation call", out["sentence"])

    async def test_an_answer_with_nothing_to_say_is_a_failure(self):
        def reply(cmds):
            if cmds[0]["type"] == "config/entity_registry/list":
                return [self.REGISTRY]
            return [{"response": {"speech": {"plain": {"speech": ""}}}}]

        h, _ = hooks(ws_replies=reply)
        out = await self.doctor.stage_assist(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("nothing to say", out["sentence"])


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

class TestMemoryStage(DoctorCase):
    """The queue is counted either side, and the marker is taken out again."""

    def _hooks(self, *, lands=True, forgets=True, drains=True,
               consolidate=(True, "")):
        d = self.doctor
        state = {"pending": 0, "doc": ""}
        passes = []

        def queue(fact, source="doctor"):
            state["pending"] += 1
            state.setdefault("queued", []).append(fact)

        def drop(source, fact):
            state.setdefault("dropped", []).append(fact)
            state["pending"] = max(0, state["pending"] - 1)
            return True

        def consolidate_now():
            passes.append(list(state.get("queued") or []))
            queued = state.get("queued") or []
            state["queued"] = []
            if consolidate[0]:
                for fact in queued:
                    if fact.startswith("FORGET:"):
                        if forgets:
                            state["doc"] = ""
                    elif lands:
                        state["doc"] += fact + "\n"
                # `drains` is the whole discrimination this stage rests
                # on. The real consolidator archives the inbox only after
                # memory.md has been written, so a queue that emptied is
                # proof the pass ran; one that did not is the pass
                # keeping the facts. A fake that always emptied it made
                # those two cases render as one.
                if drains:
                    state["pending"] = 0
                else:
                    state["queued"] = list(queued)
            return consolidate

        h, fake = hooks()
        h.queue_memory = queue
        h.drop_memory = drop
        h.inbox_pending = lambda: state["pending"]
        h.memory_text = lambda: state["doc"]
        h.consolidate = consolidate_now
        return d, h, state, passes

    async def test_the_happy_path_files_then_removes(self):
        d, h, state, passes = self._hooks()
        out = await d.stage_memory(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertEqual(len(passes), 2, "one pass in, one pass out")
        self.assertTrue(passes[1][0].startswith("FORGET:"))
        self.assertNotIn(d.MEMORY_FACT_PREFIX, state["doc"])

    async def test_a_consolidator_that_kept_the_facts_is_a_failure(self):
        """The queue did not move: the pass did not file, and that is a
        fault. The marker goes back out with it — it is still in the inbox,
        and the next ordinary pass would file this check's own probe into
        somebody's memory with nothing left to remove it."""
        d, h, state, _ = self._hooks(lands=False, drains=False)
        out = await d.stage_memory(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("queue did not move", out["sentence"])
        self.assertIn(d.MEMORY_FACT_PREFIX,
                      " ".join(state.get("dropped") or []))

    async def test_a_pass_that_dropped_the_probe_is_a_skip_not_a_failure(self):
        """The reported bug. A drained queue is the one thing that PROVES
        the pipeline ran — the consolidator archives the inbox only after
        memory.md is written — so the line not surviving is the model's
        editorial judgement, which the consolidator's own log calls "a
        judgement, not a failure". Reporting it as "a pass consumed it
        without writing it down" is the sentence for a broken memory
        pipeline, said about a memory system that is working."""
        d, h, state, _ = self._hooks(lands=False, drains=True)
        out = await d.stage_memory(h)
        self.assertEqual(out["state"], "skipped", out["sentence"])
        self.assertNotIn("consumed it without writing it down",
                         out["sentence"])
        self.assertIn("judgement", out["sentence"])

    async def test_the_probe_does_not_describe_itself_as_transient(self):
        """The consolidator's prompt says "NEVER include ... transient
        device states", so a probe that says its subject is removed again
        straight away is a line a working pass is told to drop. The check
        cannot be graded on a line it asked to have dropped."""
        d = self.doctor
        probe = f"{d.MEMORY_FACT_PREFIX} {d.MEMORY_FACT_SUFFIX}".lower()
        for tell in ("removed again", "ignore this", "straight away",
                     "temporary", "delete"):
            self.assertNotIn(tell, probe)

    async def test_a_consolidator_that_would_not_run_takes_the_fact_back(self):
        d, h, state, _ = self._hooks(consolidate=(False, "it exploded"))
        out = await d.stage_memory(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("did not file the queue", out["sentence"])
        self.assertTrue(state.get("dropped"), "the fact was left in the queue")

    async def test_a_marker_that_cannot_be_removed_is_the_loudest_line(self):
        """A self-test that writes into memory and leaves it there has done
        more harm than the check was worth."""
        d, h, state, _ = self._hooks(forgets=False)
        out = await d.stage_memory(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("could not be taken out again", out["sentence"])
        self.assertIn("Memory tab", out["sentence"])

    async def test_a_fact_that_never_reached_the_inbox_is_a_failure(self):
        h, _ = hooks()
        h.queue_memory = lambda fact, source="doctor": None
        h.inbox_pending = lambda: 0
        out = await self.doctor.stage_memory(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("did not reach the memory inbox", out["sentence"])


# ---------------------------------------------------------------------------
# Findings and undo — against the panel's own implementations
# ---------------------------------------------------------------------------

class TestFindingsStage(DoctorCase):
    """Driven through `server._end_finding` and `server._undo_finding`.

    Those are the functions the tab's buttons and the To-do app's ticks go
    through. A stub here would prove the stub; what makes this stage worth
    having is that it exercises the real ending.
    """

    async def asyncSetUp(self):
        await super().asyncSetUp()
        base = self.tmp.name
        os.environ["BRAIN_MEMORY_DIR"] = os.path.join(base, "memory")
        os.environ["BRAIN_MEMORY_INBOX"] = os.path.join(base, "memory", "inbox")
        os.environ["BRAIN_MEMORY_FILE"] = os.path.join(base, "memory", "memory.md")
        os.environ["BRAIN_DIR"] = os.path.join(base, "insights")
        os.environ["BRAIN_SETTINGS_FILE"] = os.path.join(base, "settings.json")
        os.environ["BRAIN_KNOWLEDGE_FILE"] = os.path.join(base, "knowledge.json")
        os.environ["BRAIN_DIAGNOSTICS_FILE"] = os.path.join(base, "diag.json")
        import hypotheses
        importlib.reload(hypotheses)
        import knowledge_store
        importlib.reload(knowledge_store)
        import server
        self.server = importlib.reload(server)

    def _hooks(self):
        h, fake = hooks()
        h.end_finding = self.server._end_finding
        h.undo_finding = lambda entry: asyncio.to_thread(
            self.server._undo_finding, entry)
        h.drop_memory = lambda source, fact: self.server._drop_from_inbox(
            self.server._inbox_id(source, fact))
        return h

    async def test_the_round_trip_leaves_nothing_behind(self):
        out = await self.doctor.stage_findings_undo(self._hooks())
        self.assertEqual(out["state"], "ok", out["sentence"])
        rows = self.findings.list_all()
        self.assertEqual(
            [r for r in rows
             if r["text"].startswith(self.doctor.FINDING_TEXT_PREFIX)], [])
        self.assertEqual(
            [e for e in self.findings.settled_listing()
             if self.doctor.FINDING_TEXT_PREFIX in str(e.get("text", ""))
             or self.doctor.FINDING_TEXT_PREFIX in str(e.get("key", ""))], [])
        self.assertEqual(self.server._inbox_pending(), 0,
                         "the memory line the ending queued is gone")

    async def test_the_ending_really_did_settle_and_the_undo_really_unsettled(self):
        """Not a claim about the stage: a claim about the store, made by
        watching the ledger from the outside while the stage runs."""
        seen = []
        original = self.server._end_finding

        async def watched(finding, spec, note):
            payload, fact = await original(finding, spec, note)
            seen.append([e.get("key") for e in self.findings.settled_listing()])
            return payload, fact

        h = self._hooks()
        h.end_finding = watched
        out = await self.doctor.stage_findings_undo(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertEqual(len(seen), 2, "ended, undone, then ended again")
        self.assertTrue(seen[0], "the first ending reached the ledger")

    async def test_a_store_that_will_not_take_a_row_is_a_failure(self):
        self.findings.add = lambda text, **f: (None, False)
        out = await self.doctor.stage_findings_undo(self._hooks())
        self.assertEqual(out["state"], "failed")
        self.assertIn("would not take a new row", out["sentence"])

    async def test_an_undo_that_does_not_restore_is_a_failure_and_still_cleans_up(self):
        h = self._hooks()

        async def broken(entry):
            return False, {}

        h.undo_finding = broken
        out = await self.doctor.stage_findings_undo(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("did not put the row back", out["sentence"])
        # Cleanup runs in a finally, so a mid-stage failure leaves nothing.
        self.assertEqual(
            [r for r in self.findings.list_all()
             if r["text"].startswith(self.doctor.FINDING_TEXT_PREFIX)], [])
        self.assertEqual(self.findings.settled_listing(), [])

    async def test_an_ending_that_leaves_the_row_behind_is_a_failure(self):
        h = self._hooks()

        async def noop(finding, spec, note):
            return {}, ""

        h.end_finding = noop
        out = await self.doctor.stage_findings_undo(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("did not remove its row", out["sentence"])


# ---------------------------------------------------------------------------
# The fixer
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """`homeassistant.util.slugify`, near enough for an id.

    The point is not the exact algorithm — it is that a storage
    collection's id is a function of the NAME, which is what this file
    used to assume it was not.
    """
    out = "".join(c.lower() if c.isalnum() else "_" for c in name)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def _mint(name: str, taken) -> str:
    """`collection.IDManager.generate_id`: the slug while it is free."""
    base = _slug(name)
    seen = {item["id"] for item in taken}
    candidate, n = base, 1
    while candidate in seen:
        n += 1
        candidate = f"{base}_{n}"
    return candidate


class TestFixerStage(DoctorCase):
    """Driven against a fake that mints ids the way Core does.

    The fake this replaces answered `input_boolean/create` by appending a
    row whose `entity_id` was `doctor.FIXER_HELPER` — it wrote down the
    same guess the code did, so the suite could not see that the helper
    Core really created was `input_boolean.brain_deep_check` while the
    stage spent ten seconds polling for `input_boolean.brain_test_doctor`
    and then blamed the Supervisor token. A collection's id comes from the
    name, so the fake derives it from the name.
    """

    def _core(self, existing=()):
        items: list[dict] = []
        for name in existing:
            items.append({"id": _mint(name, items), "name": name})

        def reply(cmds):
            kind = cmds[0]["type"]
            if kind == "input_boolean/list":
                return [[dict(item) for item in items]]
            if kind == "input_boolean/create":
                item = {"id": _mint(cmds[0]["name"], items),
                        "name": cmds[0]["name"]}
                items.append(item)
                return [dict(item)]
            if kind == "input_boolean/delete":
                wanted = cmds[0]["input_boolean_id"]
                for i, item in enumerate(items):
                    if item["id"] == wanted:
                        items.pop(i)
                        break
                # Core answers a successful delete with `result: null`.
                return [None]
            if kind == "config/entity_registry/list":
                return [[{"entity_id": f"input_boolean.{item['id']}",
                          "name": item["name"]} for item in items]]
            return [None]
        return reply, items

    def _renamer(self, items, to=None):
        """A `run_agent` that does what the fix run is asked to do."""
        def run_agent(prompt, *a, **k):
            self.prompts.append(prompt)
            for item in items:
                if item["name"] == self.doctor.FIXER_HELPER_NAME:
                    item["name"] = (self.doctor.FIXER_RENAMED
                                    if to is None else to)
            return envelope("Renamed it.")
        return run_agent

    def setUp(self):
        super().setUp()
        self.prompts = []

    def _with_agent(self, run_agent):
        import engine
        old = engine.run_agent
        engine.run_agent = run_agent
        self.addCleanup(lambda: setattr(engine, "run_agent", old))

    # -- the bug ---------------------------------------------------------

    async def test_the_name_mints_the_id_the_stage_looks_for(self):
        """Core derives the entity id from the name, so the two constants
        are one fact: `FIXER_HELPER_NAME` has to slugify to the object id
        part of `FIXER_HELPER`. It did not, and every deep check created a
        helper, polled for a different one and reported that Home
        Assistant would not create it."""
        d = self.doctor
        self.assertEqual(f"input_boolean.{_slug(d.FIXER_HELPER_NAME)}",
                         d.FIXER_HELPER)

    async def test_the_minted_id_is_under_the_prefix_so_litter_is_visible(self):
        """`rehearsal.leftovers` and the sweep both scan for `PREFIX`, so a
        helper whose slug lands outside it is litter nothing can see —
        which is what `brain_deep_check` was."""
        d = self.doctor
        self.assertIn(d.PREFIX, _slug(d.FIXER_HELPER_NAME))

    async def test_a_deep_check_leaves_no_helper_behind(self):
        reply, items = self._core()
        h, _ = hooks(ws_replies=reply)
        self._with_agent(self._renamer(items))
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertEqual(items, [], "the helper was deleted afterwards")

    async def test_helpers_an_earlier_broken_run_left_are_cleared(self):
        """The shipped bug created one per run and could delete none of
        them. They carry the name brAIn gave them, which is the only
        handle on an item whose own slug is not ours to predict."""
        reply, items = self._core(existing=[
            "brAIn deep check", "brAIn deep check", "brAIn deep check (renamed)"])
        h, _ = hooks(ws_replies=reply)
        self._with_agent(self._renamer(items))
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertEqual(items, [])
        self.assertIn("3 helper(s)", out["detail"])

    async def test_the_sweep_counts_what_went_not_what_it_asked_for(self):
        """`_delete_helper` swallows a refusal by design, so the list of
        what was asked for is not the list of what went — and the number
        goes on the report."""
        reply, items = self._core(existing=["brAIn deep check"])

        def stubborn(cmds):
            if cmds[0]["type"] == "input_boolean/delete" \
                    and cmds[0]["input_boolean_id"] == "brain_deep_check":
                return [None]          # accepted, and nothing happens
            return reply(cmds)

        h, _ = hooks(ws_replies=stubborn)
        self._with_agent(self._renamer(items))
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertNotIn("helper(s)", out["detail"])
        self.assertEqual([i["name"] for i in items], ["brAIn deep check"])

    async def test_somebody_elses_helpers_are_left_alone(self):
        reply, items = self._core(existing=["Kitchen holiday mode"])
        h, _ = hooks(ws_replies=reply)
        self._with_agent(self._renamer(items))
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertEqual([i["name"] for i in items], ["Kitchen holiday mode"])
        self.assertNotIn("helper(s)", out["detail"])

    async def test_a_taken_slug_is_read_back_and_not_assumed(self):
        """`generate_id` appends `_2` when the slug is taken, and the item
        id and the entity's object id part company from there. A helper of
        somebody else's under that slug is not one the sweep may remove,
        so the collision is real and everything downstream — the prompt,
        the verification, the delete — has to key on what came back."""
        reply, items = self._core(existing=["brain test doctor"])
        h, fake = hooks(ws_replies=reply)
        self._with_agent(self._renamer(items))
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertIn("input_boolean.brain_test_doctor_2", self.prompts[0])
        deletes = [c[0]["input_boolean_id"] for c in fake.ws_calls
                   if c[0]["type"] == "input_boolean/delete"]
        self.assertEqual(deletes, ["brain_test_doctor_2"])
        self.assertEqual([i["name"] for i in items], ["brain test doctor"])

    # -- the stage's own answers -----------------------------------------

    async def test_a_protected_helper_is_a_skip_and_not_a_failure(self):
        """The list doing its job is not a fault."""
        reply, _ = self._core()
        h, _ = hooks(ws_replies=reply,
                     options={"protected_entities": ["input_boolean.*"]})
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "skipped")
        self.assertIn("protected_entities", out["sentence"])

    async def test_the_sweep_leaves_a_protected_leftover_alone(self):
        """The stage asks about `FIXER_HELPER`, and the leftovers carry ids
        an older build chose — so a list naming one of those would fall
        through the gap between two spellings of nearly the same entity,
        into an unattended delete."""
        reply, items = self._core(existing=["brAIn deep check"])
        h, _ = hooks(ws_replies=reply, options={
            "protected_entities": ["input_boolean.brain_deep_check"]})
        self._with_agent(self._renamer(items))
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        self.assertEqual([i["name"] for i in items], ["brAIn deep check"])
        self.assertNotIn("helper(s)", out["detail"])

    async def test_a_run_that_changed_nothing_is_a_failure(self):
        reply, items = self._core()
        h, _ = hooks(ws_replies=reply)
        self._with_agent(self._renamer(items, to=self.doctor.FIXER_HELPER_NAME))
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("did not change", out["sentence"])
        self.assertEqual(items, [], "and the helper still went away")

    async def test_a_helper_that_cannot_be_created_is_a_failure(self):
        h, _ = hooks(ws_replies=lambda cmds: [[] if cmds[0]["type"].endswith("list")
                                              else None])
        out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("could not create", out["sentence"])
        self.assertIn("refused input_boolean/create", out["detail"])

    async def test_a_helper_that_never_registers_is_taken_back_out(self):
        """The one path that does not reach the stage's `finally`, and so
        the one that would leave a helper behind."""
        made = []

        def reply(cmds):
            kind = cmds[0]["type"]
            if kind == "input_boolean/create":
                return [{"id": "brain_test_doctor", "name": cmds[0]["name"]}]
            if kind == "input_boolean/delete":
                made.append(cmds[0]["input_boolean_id"])
            return [[]]

        h, _ = hooks(ws_replies=reply)
        with unittest.mock.patch("asyncio.sleep", new=_nosleep):
            out = await self.doctor.stage_fixer_dry(h)
        self.assertEqual(out["state"], "failed")
        self.assertIn("entity registry", out["detail"])
        self.assertEqual(made, ["brain_test_doctor"])


async def _nosleep(_seconds):
    return None


# ---------------------------------------------------------------------------
# The chat, against a real subprocess
# ---------------------------------------------------------------------------

class TestChatStage(DoctorCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        base = self.tmp.name
        os.environ["BRAIN_CHAT_TRANSCRIPT_DIR"] = os.path.join(base, "chat")
        os.environ["BRAIN_CHAT_WORKDIR"] = base
        os.environ["BRAIN_SETTINGS_FILE"] = os.path.join(base, "settings.json")
        os.environ["BRAIN_CLAUDE_BIN"] = str(FAKE_CHAT)
        os.environ["FAKE_CHAT_MODE"] = "ok"
        import engine
        importlib.reload(engine)
        import chat_session
        self.chat = importlib.reload(chat_session)
        self.doctor = importlib.reload(self.doctor)

    async def asyncTearDown(self):
        await self.chat.registry().stop_all()
        for key in ("FAKE_CHAT_MODE", "BRAIN_CLAUDE_BIN"):
            os.environ.pop(key, None)
        await super().asyncTearDown()

    async def test_a_real_turn_and_no_transcript_left_behind(self):
        h, _ = hooks()
        out = await self.doctor.stage_chat(h)
        self.assertEqual(out["state"], "ok", out["sentence"])
        left = list(Path(self.chat.TRANSCRIPT_DIR).glob("*.json")) \
            if os.path.isdir(self.chat.TRANSCRIPT_DIR) else []
        self.assertEqual(left, [], "the probe left a conversation behind")

    async def test_it_never_joins_the_registry(self):
        """Nothing on screen may move, and no live conversation may be
        evicted, because a check that closed somebody's chat to prove the
        chat works is exactly wrong."""
        before = len(self.chat.registry().sessions())
        await self.doctor.stage_chat(hooks()[0])
        self.assertEqual(len(self.chat.registry().sessions()), before)

    async def test_a_full_registry_is_a_skip_carrying_the_caps_sentence(self):
        os.environ["BRAIN_SETTINGS_FILE"] = os.path.join(
            self.tmp.name, "cap.json")
        import settings_store
        importlib.reload(settings_store)
        settings_store.save({"chat_max_sessions": 1})
        registry = self.chat.registry()
        await registry.new()
        try:
            out = await self.doctor.stage_chat(hooks()[0])
        finally:
            await registry.stop_all()
        self.assertEqual(out["state"], "skipped")
        self.assertIn("chat_max_sessions", out["sentence"])
        self.assertIn("will not close", out["sentence"])

    async def test_a_turn_that_never_ends_is_a_timeout_not_a_crash(self):
        os.environ["FAKE_CHAT_MODE"] = "hang"
        self.doctor.TIMEOUTS["chat"] = 1
        out = await self.doctor.stage_chat(hooks()[0])
        self.assertEqual(out["state"], "failed")
        self.assertIn("did not finish a turn", out["sentence"])

    async def test_an_error_envelope_is_a_failure_and_does_not_wait_it_out(self):
        """A failed turn emits an error NOTICE and no `result` at all, so a
        loop waiting only for `result` reports a one-second failure as a
        timeout — which is what this did before, for the full 180s."""
        os.environ["FAKE_CHAT_MODE"] = "error"
        began = time.monotonic()
        out = await self.doctor.stage_chat(hooks()[0])
        self.assertEqual(out["state"], "failed")
        self.assertNotIn("did not finish a turn", out["sentence"])
        self.assertLess(time.monotonic() - began, 20,
                        "it waited out the chat budget instead of reading "
                        "the error")


# ---------------------------------------------------------------------------
# The panel's side: the job, the 409, and the diagnostics key
# ---------------------------------------------------------------------------

class TestTheRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        for key, value in {
            "BRAIN_DOCTOR_DEEP_FILE": os.path.join(base, "deep.json"),
            "BRAIN_FINDINGS_FILE": os.path.join(base, "findings.json"),
            "BRAIN_FINDINGS_SETTLED": os.path.join(base, "settled.json"),
            "BRAIN_FINDINGS_STATE": os.path.join(base, "state.json"),
            "BRAIN_FINDINGS_INBOX": os.path.join(base, "finbox"),
            "BRAIN_JOURNAL_FILE": os.path.join(base, "journal.jsonl"),
            "BRAIN_MEMORY_DIR": os.path.join(base, "memory"),
            "BRAIN_MEMORY_INBOX": os.path.join(base, "memory", "inbox"),
            "BRAIN_MEMORY_FILE": os.path.join(base, "memory", "memory.md"),
            "BRAIN_DIR": os.path.join(base, "insights"),
            "BRAIN_SETTINGS_FILE": os.path.join(base, "settings.json"),
            "BRAIN_KNOWLEDGE_FILE": os.path.join(base, "knowledge.json"),
            "BRAIN_DIAGNOSTICS_FILE": os.path.join(base, "diag.json"),
        }.items():
            os.environ[key] = value
        import doctor
        importlib.reload(doctor)
        import server
        self.server = importlib.reload(server)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def _request(self):
        class R:
            match_info: dict = {}
        return R()

    async def test_a_second_start_gets_the_live_run_and_a_409(self):
        self.server.DOCTOR_STATE["running"] = True
        self.server.DOCTOR_STATE["kind"] = "deep"
        try:
            resp = await self.server.h_doctor_deep_start(self._request())
        finally:
            self.server.DOCTOR_STATE.update(running=False, kind="")
        self.assertEqual(resp.status, 409)
        body = json.loads(resp.text)
        self.assertEqual(body["job"], "doctor-deep")
        self.assertIn("already running", body["error"])

    async def test_starting_one_queues_a_doctor_job(self):
        resp = await self.server.h_doctor_deep_start(self._request())
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.server.JOBS["doctor-deep"]["kind"], "doctor")
        self.assertEqual(self.server.QUEUE.get_nowait(), "doctor-deep")

    async def test_the_get_carries_the_catalog_so_the_ui_can_draw_the_list(self):
        import doctor
        resp = await self.server.h_doctor_deep_get(self._request())
        body = json.loads(resp.text)
        self.assertEqual([s["name"] for s in body["stage_catalog"]],
                         doctor.STAGE_NAMES)
        self.assertFalse(body["running"])

    async def test_diagnostics_carries_the_last_verdict(self):
        import doctor
        doctor.save({"finished_at": 123, "verdict": "failed",
                     "failed_stage": "memory", "counts": {"ok": 7}})
        payload = await asyncio.to_thread(self.server._diagnostics_payload)
        self.assertEqual(payload["doctor_deep"]["verdict"], "failed")
        self.assertEqual(payload["doctor_deep"]["failed_stage"], "memory")

    async def test_the_worker_dispatches_a_doctor_job(self):
        """The generation queue is the serializer: one Claude invocation in
        flight across the whole add-on, deep runs included."""
        ran = []

        async def fake(job_id):
            ran.append(job_id)

        self.server._run_doctor_deep = fake
        self.server._set_job("doctor-deep", kind="doctor", state="queued")
        self.server.QUEUE.put_nowait("doctor-deep")
        worker = asyncio.create_task(self.server._worker())
        await self.server.QUEUE.join()
        worker.cancel()
        self.assertEqual(ran, ["doctor-deep"])


class TestTheCliReportBlocks(unittest.TestCase):
    """`brain doctor --deep`'s own printing, lifted out and driven.

    The same treatment `test_doctor_json` gives `ha-selftest.sh`'s report
    block, and it exists because the first cut of these was written as
    `python3 -c '...'`: shell single quotes leave no way to put a `"`
    inside an f-string expression except a backslash, and a backslash in
    one is a SyntaxError before Python 3.12. It would have parsed on the
    image and nowhere else. The second cut moved the script into a
    heredoc — which is stdin, so the payload had to stop being piped and
    become an argument, and a pipe into a heredoc reads as empty rather
    than as an error.
    """

    SCRIPT = (BASE_DIR / "brain" / "scripts" / "brain-doctor-deep.sh")

    def block(self, *names: str) -> str:
        src = self.SCRIPT.read_text(encoding="utf-8")
        out = []
        for name in names:
            match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", src,
                              re.M | re.S)
            self.assertIsNotNone(match, f"{name} is gone from the script")
            out.append(match.group(0))
        return "".join(out)

    def run_sh(self, names, body) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", "set -u\n" + self.block(*names) + "\n" + body],
            capture_output=True, text=True, timeout=30)

    PAYLOAD = json.dumps({
        "stages": [
            {"name": "chat", "title": "Chat session", "state": "ok",
             "seconds": 3.2, "sentence": "it worked", "detail": "reply: OK"},
            {"name": "memory", "title": "Memory", "state": "failed",
             "seconds": 9, "sentence": "the queue did not move"},
            {"name": "assist", "title": "Assist", "state": "skipped",
             "seconds": 0, "sentence": "the integration is off"},
        ],
        "last": {"counts": {"ok": 6, "failed": 1, "skipped": 1},
                 "verdict": "failed", "failed_stage": "memory"},
    })

    def test_the_stage_printer_prints_only_what_is_new(self):
        proc = self.run_sh(
            ["print_new_stages"],
            f"n=$(print_new_stages 0 '{self.PAYLOAD}'); echo \"count=$n\"\n"
            f"print_new_stages 2 '{self.PAYLOAD}' > /dev/null\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("count=3", proc.stdout)
        self.assertIn("Chat session", proc.stderr)
        self.assertIn("the queue did not move", proc.stderr)
        # The second call started at 2, so only Assist came out again.
        self.assertEqual(proc.stderr.count("Chat session"), 1)

    def test_a_torn_payload_carries_the_count_rather_than_crashing(self):
        proc = self.run_sh(["print_new_stages"],
                           "print_new_stages 4 'not json'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "4")

    def test_the_verdict_exits_non_zero_on_a_failed_stage(self):
        proc = self.run_sh(["print_verdict"],
                           f"print_verdict '{self.PAYLOAD}'\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("6 passed, 1 failed, 1 skipped", proc.stdout)
        self.assertIn("First failure: memory", proc.stdout)

    def test_a_clean_verdict_exits_zero(self):
        payload = json.dumps({"last": {"counts": {"ok": 8, "failed": 0,
                                                  "skipped": 0},
                                       "verdict": "ok"}})
        proc = self.run_sh(["print_verdict"], f"print_verdict '{payload}'\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("First failure", proc.stdout)

    def test_the_consent_offer_names_every_id_and_what_cannot_be_rehearsed(self):
        plan = json.dumps({
            "plan": [{"id": "brain_test_dead_ref", "what": "an automation",
                      "proves": "auto.dead_ref"}],
            "not_rehearsable": [{"check": "dev.frozen",
                                 "why": "needs a week of statistics"}]})
        proc = self.run_sh(["print_plan"], f"print_plan '{plan}'\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("brain_test_dead_ref", proc.stdout)
        self.assertIn("an automation", proc.stdout)
        self.assertIn("dev.frozen cannot be rehearsed", proc.stdout)

    def test_the_score_prints_both_numbers_and_fails_on_a_bad_cleanup(self):
        payload = json.dumps({"last": {
            "checks": {"planted": 2, "found": 1, "extra": 1,
                       "rows": [{"verdict": "found", "id": "a",
                                 "check": "auto.dead_ref"}]},
            "analyst": {"ran": True, "found": 1, "planted": 2,
                        "recall": 0.5, "precision": 1.0, "model": "m"},
            "cleanup": {"ok": False, "sentence": "SOMETHING WAS LEFT BEHIND"}}})
        proc = self.run_sh(["print_score"], f"print_score '' '{payload}'\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("1 of 2 planted defects found", proc.stdout)
        self.assertIn("recall 50%, precision 100%", proc.stdout)
        self.assertIn("SOMETHING WAS LEFT BEHIND", proc.stdout)

    def test_json_mode_prints_no_prose_and_still_carries_the_code(self):
        payload = json.dumps({"last": {"checks": {}, "analyst": {},
                                       "cleanup": {"ok": True,
                                                   "sentence": "removed"}}})
        proc = self.run_sh(["print_score"],
                           f"print_score --json '{payload}'\n")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_nothing_in_the_script_uses_python3_dash_c(self):
        """A `python3 -c '…'` here cannot contain a `\"` inside an f-string
        expression without a backslash, and that is a SyntaxError before
        3.12 — code that only parses on the interpreter the image happens
        to ship."""
        src = self.SCRIPT.read_text(encoding="utf-8")
        offenders = [line for line in src.splitlines()
                     if "python3 -c" in line and not line.lstrip().startswith("#")]
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_heredoc_python_is_also_piped_into(self):
        """A heredoc IS stdin, so a pipe into one arrives empty — and
        empty reads as "no stages yet" rather than as an error."""
        src = self.SCRIPT.read_text(encoding="utf-8")
        offenders = [line for line in src.splitlines()
                     if "|" in line and "python3 - " in line]
        self.assertEqual(offenders, [], "\n".join(offenders))


class TestTheSourceIsClaimed(unittest.TestCase):
    def test_doctor_is_a_known_run_source(self):
        """Or every probe shows up in the Chats rail as a conversation
        somebody had — and `engine._run_cli` silently drops the claim."""
        import run_sources
        self.assertTrue(run_sources.known("doctor"))
        self.assertIn("doctor", run_sources.ENGINE_SOURCES)


if __name__ == "__main__":
    unittest.main()
