#!/usr/bin/env python3
"""Reading a chat: what is the person's, and what costs a process.

Two findings from a walkthrough of a real house, driven through the real
functions rather than described:

* **A turn Claude Code injected is not a turn the person typed.** When a
  backgrounded task finishes, the CLI writes a ``<task-notification>`` into
  the user half of the conversation. The replay turned it into a bubble —
  four kilobytes of raw XML with ``&gt;`` entities and literal ``\\n`` —
  that read as something Ben had said. It is a ``background`` event now, on
  every path into the pane: the CLI's store, the live stream, and a
  scrollback the panel saved before this existed.
* **Opening a chat is reading it.** Every click on an old conversation
  started a Claude process; the stream answered with an error status when
  it had nothing to show. Neither should happen.
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
PANEL = BASE_DIR / "brain" / "panel"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"

sys.path.insert(0, str(PANEL))

# Shaped like the one in the report: one line of XML, the result itself
# JSON-escaped (literal backslash-n), with an entity in it.
NOTIFICATION = (
    "<task-notification>\n<task-id>b7f2</task-id>\n"
    "<status>completed</status>\n"
    "<summary>Agent \"Washing machine power history\" completed</summary>\n"
    "<result>### Findings\\n\\n**Evidence**: draw &gt;= 1500 W for 40 min"
    "\\n\\n```\\nsensor.washer_power\\n```</result>\n"
    "</task-notification>")


class TestTheClassifier(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import conversations
        cls.conv = importlib.reload(conversations)

    def test_a_task_notification_is_a_background_row(self):
        ev = self.conv.injected_event(NOTIFICATION)
        self.assertEqual(ev["type"], "background")
        self.assertEqual(ev["status"], "completed")
        self.assertEqual(ev["summary"],
                         'Agent "Washing machine power history" completed')
        self.assertIn("**Evidence**: draw >= 1500 W", ev["text"])
        self.assertNotIn("&gt;", ev["text"])
        self.assertNotIn("\\n", ev["text"])
        self.assertTrue(ev["text"].startswith("### Findings\n"))

    def test_a_reminder_is_shown_nowhere(self):
        self.assertEqual(self.conv.injected_events(
            "<system-reminder>be brief</system-reminder>"), [])

    def test_what_a_person_typed_is_not_touched(self):
        self.assertIsNone(self.conv.injected_events("turn the hall light on"))
        self.assertIsNone(self.conv.injected_events(
            "why does <task-notification> show up in my chat?"))


class TestTheReplay(unittest.TestCase):
    """`conversations.transcript` over a real file in the CLI's store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        import conversations
        self.conv = importlib.reload(conversations)
        self.conv.CONFIG_DIR = self.tmp.name
        project = (Path(self.tmp.name) / "projects"
                   / re.sub(r"[^A-Za-z0-9]", "-", self.tmp.name))
        project.mkdir(parents=True)
        lines = [
            {"type": "user", "cwd": self.tmp.name,
             "message": {"role": "user", "content": "check the washer"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "Started a background look."}]}},
            {"type": "user", "message": {"role": "user", "content": [
                {"type": "text", "text": NOTIFICATION}]}},
        ]
        (project / "conv-1.jsonl").write_text(
            "\n".join(json.dumps(line) for line in lines) + "\n")
        self.path = project / "conv-1.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_notification_replays_as_a_row_not_a_bubble(self):
        events = self.conv.transcript(self.tmp.name, "conv-1")
        users = [e["text"] for e in events if e["type"] == "user"]
        self.assertEqual(users, ["check the washer"])
        rows = [e for e in events if e["type"] == "background"]
        self.assertEqual(len(rows), 1)
        self.assertIn("Washing machine", rows[0]["summary"])

    def test_it_is_never_a_title(self):
        self.path.write_text("\n".join(json.dumps(line) for line in [
            {"type": "user", "cwd": self.tmp.name,
             "message": {"role": "user", "content": NOTIFICATION}},
            {"type": "user",
             "message": {"role": "user", "content": "the real question"}},
        ]) + "\n")
        self.assertEqual(self.conv.title_of(self.path), "the real question")


class TestTheLiveStream(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import chat_session
        cls.mod = chat_session

    def test_an_injected_user_event_becomes_a_background_row(self):
        for content in (NOTIFICATION,
                        [{"type": "text", "text": NOTIFICATION}]):
            out = self.mod._normalise({"type": "user", "message": {
                "role": "user", "content": content}})
            self.assertEqual([e["type"] for e in out], ["background"])

    def test_tool_results_still_come_through(self):
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}})
        self.assertEqual(out[0]["type"], "tool_result")


class TestAnOldScrollback(unittest.IsolatedAsyncioTestCase):
    """A transcript the panel saved while the replay still made bubbles."""

    async def test_it_is_read_back_reclassified(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["BRAIN_CHAT_TRANSCRIPT_DIR"] = tmp
            try:
                import chat_session
                mod = importlib.reload(chat_session)
                (Path(tmp) / "old-conv.json").write_text(json.dumps({
                    "session_id": "old-conv", "events": [
                        {"type": "user", "text": "check the washer", "seq": 1},
                        {"type": "user", "text": NOTIFICATION, "seq": 2},
                        {"type": "user",
                         "text": "<system-reminder>x</system-reminder>",
                         "seq": 3}]}))
                session = mod.ChatSession("old-conv")
                kinds = [(e["type"], e.get("seq")) for e in session.events]
                self.assertEqual(kinds, [("user", 1), ("background", 2)])
            finally:
                os.environ.pop("BRAIN_CHAT_TRANSCRIPT_DIR", None)
                importlib.reload(chat_session)


class TestOpeningIsReading(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for key, value in {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(self.tmp.name, "t.json"),
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(self.tmp.name, "chat"),
            "BRAIN_CHAT_WORKDIR": self.tmp.name,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_SETTINGS_FILE": os.path.join(self.tmp.name, "settings.json"),
            "BRAIN_DIR": os.path.join(self.tmp.name, "insights"),
            "BRAIN_SECRETS": os.path.join(self.tmp.name, "secrets"),
            "BRAIN_RUN_SOURCES": os.path.join(self.tmp.name, "rs.jsonl"),
            "BRAIN_CHAT_TRASH": os.path.join(self.tmp.name, "chat-trash"),
        }.items():
            os.environ[key] = value
        for key in ("FAKE_CHAT_MODE", "FAKE_CHAT_LOG", "FAKE_CHAT_BROKEN",
                    "FAKE_CHAT_NOPROMPTFLAG"):
            os.environ.pop(key, None)
        for name in ("engine", "settings_store", "run_sources", "conversations",
                     "chat_session", "server"):
            module = importlib.import_module(name)
            setattr(self, name, importlib.reload(module))
        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.chat_session.registry().stop_all()
        await self.client.close()
        self.tmp.cleanup()

    def _fake_conversation(self, session_id, text):
        project = (Path(self.tmp.name) / "projects"
                   / re.sub(r"[^A-Za-z0-9]", "-", self.tmp.name))
        project.mkdir(parents=True, exist_ok=True)
        (project / f"{session_id}.jsonl").write_text(json.dumps({
            "type": "user", "cwd": self.tmp.name,
            "message": {"role": "user", "content": text}}) + "\n")
        self.conversations.CONFIG_DIR = self.tmp.name

    def _live(self):
        return [s for s in self.chat_session.registry().sessions() if s.alive()]

    async def test_opening_an_old_chat_starts_no_process(self):
        self._fake_conversation("old-one", "how warm is the loft")
        resp = await self.client.post(
            "/api/chat/resume", json={"session_id": "old-one", "spawn": False})
        self.assertEqual(resp.status, 200)
        out = await resp.json()
        self.assertFalse(out["spawned"])
        self.assertIsNone(out["resumed"])
        self.assertEqual(self._live(), [], "reading a chat spawned Claude")
        snap = await (await self.client.get("/api/chat/state")).json()
        self.assertEqual(snap["session_id"], "old-one")
        self.assertIn("how warm is the loft",
                      [e.get("text") for e in snap["events"]])

        # …and the first message is what starts it, on the same conversation.
        send = await self.client.post("/api/chat/send", json={"text": "and now?"})
        self.assertEqual(send.status, 200, await send.text())
        self.assertEqual(len(self._live()), 1)

    async def test_without_the_flag_it_still_spawns(self):
        """"Resume now" and every older caller mean the process now."""
        self._fake_conversation("old-two", "something")
        out = await (await self.client.post(
            "/api/chat/resume", json={"session_id": "old-two"})).json()
        self.assertTrue(out["spawned"])
        self.assertEqual(len(self._live()), 1)

    async def test_the_stream_never_answers_with_an_error_status(self):
        """Opening Ask is the first thing that asks for a session. A failure
        there used to be a 5xx the EventSource retried into, once per visit;
        it is an empty snapshot on a working stream now."""
        def broken():
            raise RuntimeError("nothing to attach to yet")

        self.server._chat = broken
        resp = await self.client.get("/api/chat/stream")
        self.assertEqual(resp.status, 200)
        line = await asyncio.wait_for(resp.content.readline(), 5)
        payload = json.loads(line.decode().split("data: ", 1)[1])
        self.assertEqual(payload["type"], "snapshot")
        self.assertEqual(payload["events"], [])
        resp.close()


if __name__ == "__main__":
    unittest.main()
