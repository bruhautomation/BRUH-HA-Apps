#!/usr/bin/env python3
"""A discussion asks before it changes anything, and agreement becomes a plan.

The Discuss button said *without changing anything*, and the only thing
that held it was a sentence in the opening prompt — while the project's
allow-list pre-approved every Home Assistant call, the shell and the file
editor for the chat process that conversation runs in. A person saying "go
on then" got the change made on the spot: no plan on the card, no fix
window, no Undo, and the finding still open unless somebody also pressed a
resolution.

So three claims, and each is driven rather than read:

* **The process asks.** A conversation about a finding is spawned with the
  chat's own ``--settings`` carrying ``permissions.ask`` for every acting
  tool, which the CLI evaluates ahead of the project's allow rules — and a
  CLI that refuses ``--settings`` gets the same list as
  ``--disallowedTools`` instead, because a discussion that cannot ask may
  not act. Checked on the argv the fake CLI records, since "the subject
  reached the session" and "the rules reached the process" are different
  claims and only the second decides what a turn may do.
* **The subject survives.** It is kept in the transcript's meta, so a
  discussion reopened after a restart comes back asking, not pre-approved.
* **Agreement is a plan.** The conversation offers a ``plan`` resolution;
  its press is the card's own Fix it carrying the agreed change as the
  read-only plan run's brief, so what follows is plan -> Apply -> Undo.
"""

import asyncio
import importlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
MCP_DIR = BASE_DIR / "brain" / "ha-mcp-server"
HOOK = BASE_DIR / "brain" / "scripts" / "brain-chat-context.py"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"

sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings_store  # noqa: E402

from test_fix_plan import FixCase  # noqa: E402

_ENV = ("FAKE_CHAT_MODE", "FAKE_CHAT_DELAY", "FAKE_CHAT_LOG", "FAKE_CHAT_BROKEN",
        "FAKE_CHAT_NOPROMPTFLAG", "FAKE_CHAT_REFUSE")


def read_argvs(log: Path) -> list[list[str]]:
    try:
        return [json.loads(line) for line in log.read_text().splitlines()
                if line.strip()]
    except OSError:
        return []


def settings_of(argv: list[str]) -> dict:
    if "--settings" not in argv:
        return {}
    return json.loads(argv[argv.index("--settings") + 1])


class ChatCase(unittest.IsolatedAsyncioTestCase):
    """The real registry over the fake CLI, every spawn's argv recorded."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = self.tmp.name
        os.environ["BRAIN_CHAT_TRANSCRIPT"] = os.path.join(tmp, "t.json")
        os.environ["BRAIN_CHAT_TRANSCRIPT_DIR"] = os.path.join(tmp, "chat")
        os.environ["BRAIN_SETTINGS_FILE"] = os.path.join(tmp, "settings.json")
        os.environ["BRAIN_CHAT_WORKDIR"] = tmp
        os.environ["BRAIN_CLAUDE_BIN"] = str(FAKE)
        # A hook script that does not exist: the default path is
        # /opt/scripts, and the tests that want one name it.
        os.environ["BRAIN_CHAT_CONTEXT_HOOK"] = os.path.join(tmp, "no-hook.py")
        for key in _ENV:
            os.environ.pop(key, None)
        os.environ["FAKE_CHAT_MODE"] = "ok"
        self.log = Path(tmp) / "argv.jsonl"
        os.environ["FAKE_CHAT_LOG"] = str(self.log)
        for name in ("engine", "settings_store", "chat_session"):
            setattr(self, name, importlib.reload(importlib.import_module(name)))
        self.reg = self.chat_session.SessionRegistry()

    async def asyncTearDown(self):
        await self.reg.stop_all()
        for key in _ENV + ("BRAIN_CHAT_CONTEXT_HOOK",):
            os.environ.pop(key, None)
        self.chat_session.PROMPT_PROVIDER = None
        self.tmp.cleanup()

    async def spawns(self, count, timeout=6.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            argvs = read_argvs(self.log)
            if len(argvs) >= count:
                return argvs
            await asyncio.sleep(0.05)
        raise self.failureException(
            f"expected {count} spawn(s), saw {read_argvs(self.log)}")

    async def until(self, check, timeout=8.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if check():
                return
            await asyncio.sleep(0.05)
        self.fail("timed out waiting")


class TestADiscussionAsksBeforeItActs(ChatCase):
    async def test_a_discussion_is_spawned_asking_for_every_acting_tool(self):
        await self.reg.new(finding_ts=1234)
        session = self.reg.attached()
        self.assertEqual(session.finding_ts, 1234)
        argv = (await self.spawns(1))[-1]
        ask = settings_of(argv).get("permissions", {}).get("ask", [])
        mcp = self.engine.MCP
        for tool in (f"{mcp}call_service", f"{mcp}control_lock",
                     f"{mcp}control_light", f"{mcp}run_script",
                     "Bash", "Write", "Edit", "MultiEdit"):
            self.assertIn(tool, ask, tool)
        # What a discussion is FOR stays free: reading, and offering the
        # endings it reached.
        for tool in (f"{mcp}offer_resolutions", f"{mcp}get_entity_state",
                     f"{mcp}get_history", "Read", "Grep"):
            self.assertNotIn(tool, ask, tool)

    async def test_every_tool_the_analyst_may_not_touch_asks_unless_it_only_reads(self):
        """The list is derived from `ANALYST_DENIED`, which `test_security`
        already holds against the MCP server's own tool names — so a new
        acting tool joins it by being added there, not by somebody
        remembering this file."""
        free = self.chat_session._DISCUSS_FREE
        for tool in self.engine.ANALYST_DENIED:
            if tool in free:
                continue
            self.assertIn(tool, self.chat_session.DISCUSS_ASK, tool)
        # And the free ones really are reads or the offer itself.
        for tool in free:
            self.assertTrue(tool.endswith(("offer_resolutions", "render_template",
                                           "get_camera_snapshot"))
                            or tool in ("WebFetch", "WebSearch"), tool)

    async def test_an_ordinary_chat_asks_nothing_extra(self):
        await self.reg.new()
        argv = (await self.spawns(1))[-1]
        self.assertNotIn("permissions", settings_of(argv))
        self.assertNotIn("--disallowedTools", argv)

    async def test_a_cli_that_refuses_settings_forbids_rather_than_asks(self):
        """Failing closed costs a discussion its changes, which the `plan`
        resolution makes anyway; failing open would be the read-only
        promise kept by a sentence again."""
        os.environ["FAKE_CHAT_REFUSE"] = "--settings"
        await self.reg.new(finding_ts=55)
        session = self.reg.attached()
        argvs = await self.spawns(2)
        self.assertIn("--settings", argvs[0])
        retry = argvs[1]
        self.assertNotIn("--settings", retry)
        self.assertIn("--disallowedTools", retry)
        denied = retry[retry.index("--disallowedTools") + 1].split(",")
        self.assertEqual(sorted(denied), sorted(self.chat_session.DISCUSS_ASK))
        await self.until(session.alive)
        await session.send("is it really a problem?")
        await self.until(lambda: session.state != "busy" and any(
            e.get("type") == "text" for e in session.events))

    async def test_a_chat_that_becomes_a_discussion_is_respawned_into_the_rules(self):
        """A process carries the argv it was started with. A conversation
        made a discussion while its process was live would otherwise go on
        acting unasked until something else restarted it."""
        await self.reg.new()
        session = self.reg.attached()
        await session.send("hello")
        await self.until(lambda: session.state != "busy" and session.session_id)
        self.assertNotIn("permissions", settings_of((await self.spawns(1))[-1]))
        session.about(808)
        await session.send("now about that finding")
        argv = (await self.spawns(2))[-1]
        self.assertIn("--resume", argv)
        self.assertIn(f"{self.engine.MCP}call_service",
                      settings_of(argv)["permissions"]["ask"])

    async def test_the_subject_survives_a_reload_and_a_resume(self):
        await self.reg.new(finding_ts=4242)
        session = self.reg.attached()
        await session.send("tell me about it")
        await self.until(lambda: session.state != "busy" and session.session_id
                         and any(e.get("type") == "text" for e in session.events))
        sid = session.session_id
        await self.reg.stop_all()
        kept = json.loads(self.chat_session.transcript_path(sid).read_text())
        self.assertEqual(kept["meta"]["finding_ts"], 4242)

        # A panel restarted and the conversation reopened from the rail.
        fresh = self.chat_session.SessionRegistry()
        try:
            await fresh.open(sid, [])
            reopened = fresh.get(sid)
            self.assertEqual(reopened.finding_ts, 4242)
            argv = read_argvs(self.log)[-1]
            self.assertIn("--resume", argv)
            self.assertIn("Bash", settings_of(argv)["permissions"]["ask"])
        finally:
            await fresh.stop_all()

    async def test_a_subject_that_is_not_a_timestamp_is_not_kept(self):
        clean = self.chat_session._clean_meta
        for bad in (True, -3, "12", 0, 1.5):
            self.assertNotIn("finding_ts", clean({"finding_ts": bad}), bad)
        self.assertEqual(clean({"finding_ts": 9})["finding_ts"], 9)


class TestTheChatIsPrimed(ChatCase):
    async def test_the_system_prompt_rides_the_argv(self):
        self.chat_session.PROMPT_PROVIDER = lambda s: "You are brAIn, here."
        await self.reg.new()
        argv = (await self.spawns(1))[-1]
        self.assertEqual(argv[argv.index("--append-system-prompt") + 1],
                         "You are brAIn, here.")

    async def test_a_prompt_that_cannot_be_composed_is_a_chat_that_still_starts(self):
        def broken(session):
            raise RuntimeError("the stores are on fire")
        self.chat_session.PROMPT_PROVIDER = broken
        await self.reg.new()
        session = self.reg.attached()
        argv = (await self.spawns(1))[-1]
        self.assertNotIn("--append-system-prompt", argv)
        await self.until(session.alive)

    async def test_a_cli_that_refuses_the_prompt_flag_keeps_the_chat(self):
        os.environ["FAKE_CHAT_REFUSE"] = "--append-system-prompt"
        self.chat_session.PROMPT_PROVIDER = lambda s: "You are brAIn."
        await self.reg.new()
        session = self.reg.attached()
        argvs = await self.spawns(2)
        self.assertIn("--append-system-prompt", argvs[0])
        self.assertNotIn("--append-system-prompt", argvs[1])
        await self.until(session.alive)

    async def test_the_hook_is_named_only_when_its_script_is_there(self):
        """Exit 2 from a `UserPromptSubmit` hook BLOCKS the message, and
        Python exits 2 by itself for a script that is not there — so a
        missing hook named in settings would refuse everything typed."""
        await self.reg.new()
        self.assertNotIn("hooks", settings_of((await self.spawns(1))[-1]))
        await self.reg.stop_all()

        self.chat_session.CONTEXT_HOOK = str(HOOK)
        reg = self.chat_session.SessionRegistry()
        try:
            await reg.new()
            argv = (await self.spawns(2))[-1]
            hook = settings_of(argv)["hooks"]["UserPromptSubmit"][0]["hooks"][0]
            self.assertEqual(hook["type"], "command")
            self.assertEqual(hook["command"], f"python3 {HOOK}")
            self.assertLessEqual(hook["timeout"], 10)
        finally:
            await reg.stop_all()


class TestTheDiscussPromptCarriesTheInvestigation(unittest.TestCase):
    """The Resident's case was read from scratch again by the chat — paid
    for twice — because the opener dropped its evidence, its confidence,
    its actions and the run that wrote it."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        cls.conversations = importlib.import_module("conversations")
        cls.engine = importlib.import_module("engine")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                      findings_store.STATE_FILE, self.conversations.CONFIG_DIR,
                      self.engine.CLAUDE_HOME)
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.SETTLED_FILE = tmp / "settled.json"
        findings_store.STATE_FILE = tmp / "nowhere" / ".brain" / "s.json"
        self.conversations.CONFIG_DIR = str(tmp / "claude")
        self.engine.CLAUDE_HOME = str(tmp / "home")

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, self.conversations.CONFIG_DIR,
         self.engine.CLAUDE_HOME) = self._olds
        self.tmp.cleanup()

    def _run_transcript(self, run_id, said):
        project = (Path(self.conversations.CONFIG_DIR) / "projects"
                   / re.sub(r"[^A-Za-z0-9]", "-", self.engine.CLAUDE_HOME))
        project.mkdir(parents=True, exist_ok=True)
        lines = [{"type": "user", "cwd": self.engine.CLAUDE_HOME,
                  "message": {"role": "user", "content": "investigate this"}}]
        for text in said:
            lines.append({"type": "assistant", "message": {
                "role": "assistant", "content": [{"type": "text", "text": text}]}})
        (project / f"{run_id}.jsonl").write_text(
            "\n".join(json.dumps(line) for line in lines) + "\n")

    def _case(self):
        return findings_store.add_case({
            "text": "The garage freezer is drifting warm",
            "claim": "The garage freezer is drifting warm",
            "detail": "It has risen 4 degrees over a week.",
            "kind": "problem", "severity": "warning",
            "confidence": 0.86, "stakes": "high",
            "evidence": [{"entity": "sensor.garage_freezer", "value": "-14.2 °C",
                          "when": "this morning"},
                         {"entity": "switch.garage_freezer_plug", "value": "on"}],
            "actions": [{"label": "Check the door seal", "shape": "notify",
                         "consent": False},
                        {"label": "Notify me if it passes -10", "shape": "write_automation",
                         "consent": True, "detail": "a one-off automation"}],
        }, run_id="inv-run-1")

    def test_the_opener_carries_what_the_case_already_knows(self):
        self._run_transcript("inv-run-1", [
            "Looking at the freezer history first.",
            "The compressor runs longer each night, which points at the seal.",
            '{"claim": "json the row already holds"}'])
        row = findings_store.get(self._case()["ts"])
        prompt = self.server._discuss_prompt(row)
        self.assertTrue(prompt.startswith(
            "Discussing: The garage freezer is drifting warm"))
        self.assertIn("How sure brAIn was: confident", prompt)
        self.assertIn("How much it matters if right: a lot", prompt)
        self.assertIn("- sensor.garage_freezer: -14.2 °C (this morning)", prompt)
        self.assertIn("- Check the door seal (brAIn could do it)", prompt)
        self.assertIn("would ask me first", prompt)
        self.assertIn("The run that raised this is inv-run-1", prompt)
        self.assertIn("points at the seal", prompt)
        # The closing JSON is the row itself, not something to repeat.
        self.assertNotIn("json the row already holds", prompt)
        # A case names no single entity, so the ones it read stand in.
        self.assertIn("Entities it read: sensor.garage_freezer", prompt)
        # Start from what was read, rather than paying to read it again.
        self.assertIn("Start from what was already read", prompt)
        # And the conversation is told how a change it agrees becomes one.
        self.assertIn("`plan` option", prompt)
        self.assertIn("asks me first", prompt)

    def test_a_run_that_cannot_be_read_is_a_shorter_prompt_not_a_refusal(self):
        row = findings_store.get(self._case()["ts"])
        prompt = self.server._discuss_prompt(row)
        self.assertIn("The run that raised this is inv-run-1.", prompt)

    def test_a_check_row_with_no_evidence_is_told_to_look(self):
        entry, _ = findings_store.add("Porch light never comes on",
                                      entity_id="light.porch",
                                      source="check:auto.dead_ref")
        prompt = self.server._discuss_prompt(findings_store.get(entry["ts"]))
        self.assertIn("Entity: light.porch", prompt)
        self.assertIn("Check the current state and the history", prompt)
        self.assertNotIn("What the investigation read", prompt)

    def test_a_reply_from_a_phone_is_told_the_case_but_offered_nothing(self):
        row = findings_store.get(self._case()["ts"])
        prompt = self.server._discuss_prompt(row, offer=False)
        self.assertIn("sensor.garage_freezer", prompt)
        self.assertNotIn("offer_resolutions", prompt)


class TestAgreementBecomesAPlan(FixCase):
    """The `plan` resolution's press is `/fix` with the label as the brief."""

    def test_the_agreed_change_is_the_plan_runs_brief(self):
        row = self.file_finding()
        agreed = "Add a condition so the hall light stays off after 23:00"

        async def body(client):
            res = await client.post(f"/api/finding/{row['ts']}/fix",
                                    json={"change": agreed})
            self.assertEqual(res.status, 200)
            await self.work(client)
            first = self.analyst_prompt
            # A plain Fix it afterwards is a plan with no brief: the job
            # dict outlives its run, and a brief left on it would be
            # handed to a press that never agreed to anything.
            res = await client.post(f"/api/finding/{row['ts']}/fix")
            self.assertEqual(res.status, 200)
            await self.work(client)
            return first, self.analyst_prompt

        first, second = self.drive(body)
        self.assertIn("WHAT THE HOMEOWNER AGREED TO", first)
        self.assertIn(agreed, first)
        self.assertNotIn("WHAT THE HOMEOWNER AGREED TO", second)
        # Still the read-only run, still a plan on the card.
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(findings_store.get(row["ts"])["status"], "planned")

    def test_a_brief_is_bounded_and_flattened(self):
        row = self.file_finding()

        async def body(client):
            await client.post(f"/api/finding/{row['ts']}/fix",
                              json={"change": "line one\n\nline two " + "x" * 2000})
            await self.work(client)

        self.drive(body)
        brief = self.analyst_prompt.split("WHAT THE HOMEOWNER AGREED TO", 1)[1]
        self.assertIn("line one line two", brief)
        self.assertLess(len(brief), self.server.PLAN_CHANGE_MAX + 400)


class TestTheOfferAcceptsAPlan(unittest.TestCase):
    """The MCP tool and the panel's reader agree on the new kind."""

    def setUp(self):
        self.saved = dict(sys.modules)
        sys.path.insert(0, str(MCP_DIR))
        sys.modules.pop("ha_mcp_server", None)
        import ha_mcp_server  # noqa: PLC0415
        self.mcp = ha_mcp_server
        self.chat = importlib.import_module("chat_session")

    def tearDown(self):
        sys.path.remove(str(MCP_DIR))
        sys.modules.clear()
        sys.modules.update(self.saved)

    def test_a_plan_option_is_offered_with_a_sentence_sized_label(self):
        label = ("Add a condition to the porch automation so it only runs "
                 "after sunset, and drop the 06:00 trigger. " * 3).strip()
        self.assertGreater(len(label), 90)
        options = [{"label": label, "kind": "plan"},
                   {"label": "It is fine as it is", "kind": "wrong"}]
        answer = self.mcp.offer_resolutions(options)
        self.assertNotIn("error", answer, answer)
        parsed = self.chat.resolution_offer("offer_resolutions",
                                            {"options": options})
        self.assertEqual(parsed[0]["verb"], "plan")
        self.assertEqual(parsed[0]["label"], label)

    def test_fix_is_still_not_offerable(self):
        answer = self.mcp.offer_resolutions([{"label": "Do it", "kind": "fix"}])
        self.assertIn("error", answer)


if __name__ == "__main__":
    unittest.main()
