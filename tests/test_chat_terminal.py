#!/usr/bin/env python3
"""The chat terminal: the second face of the Terminal tab.

Two things are worth testing and they are quite different:

* **The normaliser.** Everything that knows Claude Code's stream-json wire
  shape lives in ``chat_session._normalise``; if it drifts, the panel draws
  nothing and there is no error anywhere. These tests are pure and fast.
* **The session.** A real subprocess (``tests/fake_claude_chat.py``) driven
  through the real API, because the parts that break in practice — a turn
  that never ends, a CLI that dies mid-answer, "new chat" that keeps
  resuming the old one — are all lifecycle, not parsing.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"

sys.path.insert(0, str(PANEL))


class TestNormalise(unittest.TestCase):
    """The wire shape → the six event types the panel knows how to draw."""

    @classmethod
    def setUpClass(cls):
        import chat_session
        cls.mod = chat_session

    def test_text_deltas_are_live_only(self):
        """The assistant event that follows carries the same text whole, so
        keeping the deltas too would double every answer on the next reload."""
        out = self.mod._normalise({
            "type": "stream_event",
            "event": {"delta": {"type": "text_delta", "text": "hi"}}})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "text_delta")
        self.assertFalse(out[0]["_keep"])

    def test_an_assistant_message_can_carry_three_kinds_of_block(self):
        out = self.mod._normalise({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "t1", "name": "Read",
             "input": {"file_path": "/config/x.yaml"}},
        ]}})
        self.assertEqual([e["type"] for e in out],
                         ["thinking", "text", "tool"])
        self.assertEqual(out[2]["name"], "Read")
        # The chip shows the thing the call was aimed at, not a JSON blob.
        self.assertEqual(out[2]["summary"], "/config/x.yaml")
        self.assertIn("file_path", out[2]["input"])

    def test_a_user_event_from_the_cli_is_a_tool_result(self):
        """Not something the person typed — the CLI feeds results back as
        user messages, and rendering those as user turns would put words in
        their mouth."""
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": [{"type": "text", "text": "file contents"}]},
        ]}})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "tool_result")
        self.assertEqual(out[0]["id"], "t1")
        self.assertTrue(out[0]["ok"])
        self.assertEqual(out[0]["text"], "file contents")

    def test_a_failed_tool_result_is_marked_failed(self):
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
             "content": "boom"},
        ]}})
        self.assertFalse(out[0]["ok"])
        self.assertEqual(out[0]["text"], "boom")

    def test_an_error_result_becomes_a_notice_in_words(self):
        out = self.mod._normalise({
            "type": "result", "is_error": True, "subtype": "error_max_turns"})
        self.assertEqual(out[0]["type"], "notice")
        self.assertEqual(out[0]["level"], "error")
        self.assertIn("turn limit", out[0]["text"])

    def test_a_successful_result_is_a_footnote_not_a_transcript_entry(self):
        out = self.mod._normalise({
            "type": "result", "is_error": False, "duration_ms": 1234,
            "num_turns": 2, "total_cost_usd": 0.01})
        self.assertEqual(out[0]["type"], "result")
        self.assertFalse(out[0]["_keep"])
        self.assertEqual(out[0]["duration_ms"], 1234)

    def test_unknown_events_are_dropped_rather_than_rendered_raw(self):
        for event in ({"type": "system", "subtype": "init"},
                      {"type": "control_response"},
                      {"type": "something_new"}):
            self.assertEqual(self.mod._normalise(event), [])

    def test_a_giant_tool_result_is_clipped(self):
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "x" * 99999},
        ]}})
        self.assertLess(len(out[0]["text"]), self.mod.MAX_RESULT_CHARS + 100)
        self.assertIn("truncated", out[0]["text"])

    def test_the_chip_summary_falls_back_to_any_string_argument(self):
        self.assertEqual(
            self.mod.tool_summary("Weird", {"thing": "a value"}), "a value")
        self.assertEqual(self.mod.tool_summary("Weird", {}), "")
        self.assertEqual(self.mod.tool_summary("Weird", None), "")

    def test_the_chip_summary_is_one_line(self):
        summary = self.mod.tool_summary("Bash", {"command": "ls\n# and more"})
        self.assertEqual(summary, "ls")


class ChatSessionCase(unittest.IsolatedAsyncioTestCase):
    """The lifecycle, against a real subprocess."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BRAIN_CHAT_TRANSCRIPT"] = os.path.join(self.tmp.name, "t.json")
        os.environ["BRAIN_CHAT_WORKDIR"] = self.tmp.name
        os.environ["BRAIN_CLAUDE_BIN"] = str(FAKE)
        # Explicit rather than popped: several tests below set a failure
        # mode, and "whatever the last test left" is not a fixture.
        os.environ["FAKE_CHAT_MODE"] = "ok"
        os.environ.pop("FAKE_CHAT_LOG", None)
        import engine
        importlib.reload(engine)
        import chat_session
        self.mod = importlib.reload(chat_session)
        self.session = self.mod.ChatSession()

    async def asyncTearDown(self):
        await self.session.stop()
        self.tmp.cleanup()

    async def _invocations(self, log, count, timeout=5.0):
        """The argv of each spawn so far, once there are ``count`` of them.

        create_subprocess_exec returns as soon as the child is forked, not
        once it has run — so reading the log straight after a restart races
        the child's first write and passes or fails by scheduling luck.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        lines = []
        while loop.time() < deadline:
            try:
                lines = [json.loads(l) for l in open(log) if l.strip()]
            except OSError:
                lines = []
            if len(lines) >= count:
                return lines
            await asyncio.sleep(0.05)
        self.fail(f"only {len(lines)} of {count} spawns were logged")

    async def _drain(self, until, timeout=10.0):
        """Collect events until ``until(events)`` is true, or give up."""
        queue = self.session.subscribe()
        got = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while loop.time() < deadline:
                remaining = deadline - loop.time()
                try:
                    got.append(await asyncio.wait_for(queue.get(), remaining))
                except asyncio.TimeoutError:
                    break
                if until(got):
                    return got
        finally:
            self.session.unsubscribe(queue)
        return got

    async def test_a_turn_produces_the_events_the_panel_draws(self):
        await self.session.start()
        self.assertTrue(self.session.alive())
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "state" and e.get("state") == "ready"
                            for e in evs[1:])))
        await asyncio.sleep(0.05)
        await self.session.send("why is the porch light off")
        events = await task
        kinds = [e["type"] for e in events]
        for expected in ("text_delta", "thinking", "text", "tool",
                         "tool_result", "result"):
            self.assertIn(expected, kinds, f"no {expected} in {kinds}")
        tool = next(e for e in events if e["type"] == "tool")
        self.assertEqual(tool["name"], "Read")
        result = next(e for e in events if e["type"] == "tool_result")
        self.assertEqual(result["id"], tool["id"])

    async def test_the_transcript_survives_a_restart_but_the_deltas_dont(self):
        await self.session.start()
        await self.session.send("hello")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        await self.session.stop()

        reloaded = self.mod.ChatSession()
        kinds = [e["type"] for e in reloaded.events]
        self.assertIn("user", kinds)
        self.assertIn("text", kinds)
        self.assertNotIn("text_delta", kinds, "a reload would repeat every answer")
        self.assertNotIn("result", kinds, "run stats are about a run, not the record")
        self.assertEqual(reloaded.session_id, self.session.session_id)

    async def test_a_new_chat_does_not_resume_the_old_one(self):
        """Keeping the resume id would make "New chat" mean "same
        conversation, blank screen" — the one thing it must not mean."""
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        await self.session.start()
        await self.session.send("first")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        self.assertTrue(self.session.session_id)

        await self.session.reset()
        self.assertEqual(self.session.events, [])
        self.assertIsNone(self.session.session_id)
        invocations = await self._invocations(log, 2)
        self.assertNotIn("--resume", invocations[-1])

    async def test_a_second_turn_while_busy_is_refused(self):
        os.environ["FAKE_CHAT_MODE"] = "hang"
        await self.session.start()
        await self.session.send("one")
        await asyncio.sleep(0.3)
        self.assertEqual(self.session.state, "busy")
        with self.assertRaises(RuntimeError):
            await self.session.send("two")

    async def test_a_current_cli_is_stopped_by_asking(self):
        """When the control request is answered, nothing is killed and the
        session carries straight on."""
        os.environ["FAKE_CHAT_MODE"] = "hang"
        self.mod.INTERRUPT_GRACE = 3.0
        await self.session.start()
        proc = self.session.proc
        await self.session.send("hang please")
        await asyncio.sleep(0.3)
        out = await self.session.interrupt()
        self.assertEqual(out["method"], "interrupt")
        self.assertIs(self.session.proc, proc, "it killed a session that answered")
        self.assertEqual(self.session.state, "ready")

    async def test_an_older_cli_is_stopped_by_killing_and_resuming(self):
        """The polite interrupt is what a current CLI answers; an older one
        ignores it silently, which is indistinguishable from thinking. So
        the fallback is unconditional and the conversation survives it,
        because the CLI is the thing that persisted it."""
        os.environ["FAKE_CHAT_MODE"] = "deaf"
        self.mod.INTERRUPT_GRACE = 0.4
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        await self.session.start()
        await self.session.send("hang please")
        await asyncio.sleep(0.3)
        out = await self.session.interrupt()
        self.assertEqual(out["method"], "restart")
        self.assertTrue(self.session.alive())
        invocations = await self._invocations(log, 2)
        self.assertIn("--resume", invocations[-1],
                      "the restart threw the conversation away")

    async def test_a_crash_mid_turn_reports_instead_of_hanging(self):
        os.environ["FAKE_CHAT_MODE"] = "crash"
        await self.session.start()
        events = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "state" and e.get("state") == "error"
                            for e in evs),
            timeout=6))
        await asyncio.sleep(0.05)
        await self.session.send("boom")
        got = await events
        self.assertTrue(any(e.get("state") == "error" for e in got),
                        "a dead session left the page waiting forever")

    async def test_an_error_envelope_is_shown_as_a_notice(self):
        os.environ["FAKE_CHAT_MODE"] = "error"
        await self.session.start()
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "notice" for e in evs)))
        await asyncio.sleep(0.05)
        await self.session.send("hit the cap")
        got = await task
        notice = next(e for e in got if e["type"] == "notice")
        self.assertIn("turn limit", notice["text"])

    async def test_the_session_reports_what_the_cli_says_about_itself(self):
        """The model, the version, and two facts that are load-bearing: the
        working directory (which is what `claude --resume` keys conversations
        by) and whether an API key is paying."""
        await self.session.start()
        await asyncio.sleep(0.4)
        info = self.session.info
        self.assertEqual(info["model"], "claude-sonnet-5")
        self.assertEqual(info["cwd"], self.tmp.name)
        self.assertEqual(info["api_key_source"], "none")
        self.assertEqual(self.session.snapshot()["info"], info)

    async def test_the_command_list_is_the_clis_own(self):
        """A hardcoded list is wrong the first time someone drops a command
        into /config/.claude/commands. The CLI announces its own."""
        await self.session.start()
        await asyncio.sleep(0.4)
        names = [c["name"] for c in self.session.commands]
        self.assertIn("compact", names)
        self.assertIn("model", names)
        self.assertNotIn("__internal", names, "internal plumbing is not a command")
        self.assertEqual(names, sorted(names))
        model = next(c for c in self.session.commands if c["name"] == "model")
        self.assertEqual(model["hint"], "[model]")
        self.assertTrue(model["description"])

    async def test_a_slash_command_is_sent_as_an_ordinary_message(self):
        """They are not a client-side feature to reimplement — the CLI
        executes them itself when they arrive as text."""
        await self.session.start()
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "text" for e in evs)))
        await asyncio.sleep(0.05)
        await self.session.send("/compact")
        got = await task
        user = next(e for e in got if e["type"] == "user")
        self.assertEqual(user["text"], "/compact")

    async def test_handing_off_releases_the_session_and_names_it(self):
        """While the panel holds the conversation open, the terminal is being
        asked to resume something still in use."""
        await self.session.start()
        await self.session.send("hello")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        sid = self.session.session_id
        self.assertTrue(sid)
        out = await self.session.handoff()
        self.assertEqual(out["session_id"], sid)
        self.assertEqual(out["command"], f"claude --resume {sid}")
        self.assertFalse(self.session.alive(), "the session is still held open")
        # The transcript is untouched — this is a handover, not a reset.
        self.assertTrue(self.session.events)

    async def test_an_empty_message_is_refused(self):
        with self.assertRaises(ValueError):
            await self.session.send("   ")

    async def test_a_subscriber_that_stopped_reading_is_dropped_not_grown(self):
        """A suspended phone must not grow a queue until the add-on runs out
        of memory; it reconnects to a snapshot instead."""
        queue = self.session.subscribe()
        for _ in range(queue.maxsize + 5):
            self.session._emit({"type": "notice", "text": "x"}, keep=False)
        self.assertNotIn(queue, self.session._subs)

    async def test_the_transcript_is_capped(self):
        self.mod.MAX_EVENTS = 10
        for i in range(40):
            self.session._emit({"type": "notice", "text": str(i)})
        self.assertEqual(len(self.session.events), 10)
        self.assertEqual(self.session.events[-1]["text"], "39")


class TestChatRoutes(unittest.IsolatedAsyncioTestCase):
    """The API the panel actually calls, including the SSE stream."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for key, value in {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(self.tmp.name, "t.json"),
            "BRAIN_CHAT_WORKDIR": self.tmp.name,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_SETTINGS_FILE": os.path.join(self.tmp.name, "settings.json"),
            "BRAIN_DIR": os.path.join(self.tmp.name, "insights"),
            "BRAIN_SECRETS": os.path.join(self.tmp.name, "secrets"),
        }.items():
            os.environ[key] = value
        os.environ.pop("FAKE_CHAT_MODE", None)
        for name in ("engine", "settings_store", "chat_session", "server"):
            module = importlib.import_module(name)
            setattr(self, name, importlib.reload(module))

        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_the_stream_opens_with_a_snapshot(self):
        """One request, not two: a client that has to stitch "what the
        transcript was" onto "what happened next" drops an event eventually."""
        resp = await self.client.get("/api/chat/stream")
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
        line = await asyncio.wait_for(resp.content.readline(), 5)
        payload = json.loads(line.decode().split("data: ", 1)[1])
        self.assertEqual(payload["type"], "snapshot")
        self.assertIn("state", payload)
        self.assertEqual(payload["events"], [])
        resp.close()

    async def test_a_message_streams_back_as_events(self):
        resp = await self.client.get("/api/chat/stream")
        await asyncio.wait_for(resp.content.readline(), 5)   # snapshot
        await asyncio.wait_for(resp.content.readline(), 5)   # blank

        send = await self.client.post("/api/chat/send", json={"text": "hello"})
        self.assertEqual(send.status, 200)

        kinds = set()
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            line = await asyncio.wait_for(resp.content.readline(), 5)
            text = line.decode()
            if not text.startswith("data: "):
                continue
            event = json.loads(text[6:])
            kinds.add(event.get("type"))
            # "ready" fires twice — once when the session spins up and again
            # when the turn lands. Only the second one ends this loop.
            if ("user" in kinds and event.get("type") == "state"
                    and event.get("state") == "ready"):
                break
        resp.close()
        for expected in ("user", "text", "tool", "tool_result"):
            self.assertIn(expected, kinds, f"no {expected} in {sorted(kinds)}")

    async def test_an_empty_message_is_a_400(self):
        resp = await self.client.post("/api/chat/send", json={"text": " "})
        self.assertEqual(resp.status, 400)

    async def test_the_snapshot_carries_the_session_facts(self):
        """A viewer who connects after startup would otherwise never see the
        model, the project directory or the command list — the CLI announces
        them once and does not repeat itself."""
        resp = await self.client.post("/api/chat/send", json={"text": "hi"})
        self.assertEqual(resp.status, 200)
        await asyncio.sleep(0.6)
        snap = await (await self.client.get("/api/chat/state")).json()
        self.assertEqual(snap["info"]["api_key_source"], "none")
        self.assertTrue(snap["info"]["model"])
        self.assertIn("compact", [c["name"] for c in snap["commands"]])
        self.assertTrue(snap["session_id"])

    async def test_handoff_stops_the_session_and_returns_the_command(self):
        await self.client.post("/api/chat/send", json={"text": "hi"})
        await asyncio.sleep(0.6)
        out = await (await self.client.post("/api/chat/handoff")).json()
        self.assertTrue(out["session_id"])
        self.assertTrue(out["command"].startswith("claude --resume "))
        self.assertEqual((await (await self.client.get("/api/chat/state")).json())["state"],
                         "idle")

    async def test_the_terminal_ui_setting_round_trips(self):
        resp = await self.client.get("/api/settings")
        self.assertEqual((await resp.json())["settings"]["terminal_ui"], "chat")
        resp = await self.client.put("/api/settings", json={"terminal_ui": "classic"})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["settings"]["terminal_ui"], "classic")
        resp = await self.client.get("/api/status")
        self.assertEqual((await resp.json())["settings"]["terminal_ui"], "classic")
        resp = await self.client.put("/api/settings", json={"terminal_ui": "vim"})
        self.assertEqual(resp.status, 400)


if __name__ == "__main__":
    unittest.main()
