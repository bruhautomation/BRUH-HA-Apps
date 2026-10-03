#!/usr/bin/env python3
"""Discuss and Adopt go through the session registry, like everything else.

Both used to act on the ATTACHED session directly, which was right when
there was one chat process and wrong the moment there could be several:

* **Discuss** called ``reset()`` on whatever was on screen, which stopped
  its process whatever it was doing. Pressing Discuss while a chat was
  mid-answer threw the answer and its approval card away with no warning —
  the one thing holding several conversations exists to prevent. It opens
  through ``registry.new()`` now, which leaves a busy session answering in
  the background.
* **Adopt** resumed "the newest of your conversations" on the attached
  object. A background chat still answering IS the newest by construction,
  so switching back from the classic terminal resumed it a SECOND time
  beside the session already holding it — two ``claude --resume`` processes
  appending to one conversation, two rows under one id, and the cap
  skipped. It asks the registry now, leaves out what another slot holds,
  and takes the handoff record over the transcripts' times.

Everything here drives the real registry over the fake CLI, and the routes
over a real client: the parts that break are lifecycle.
"""

import asyncio
import importlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"

sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402

_ENV = ("FAKE_CHAT_MODE", "FAKE_CHAT_DELAY", "FAKE_CHAT_LOG", "FAKE_CHAT_BROKEN",
        "FAKE_CHAT_NOPROMPTFLAG", "FAKE_CHAT_REFUSE")


class TestWhichConversationTheTerminalWasOn(unittest.TestCase):
    """`pick_adopted` is pure over three answers, so it is driven directly."""

    @classmethod
    def setUpClass(cls):
        cls.chat = importlib.import_module("chat_session")

    def rows(self, *pairs):
        """Newest first, the way `conversations.listing` hands them over."""
        out = [{"id": sid, "title": sid, "modified": when} for sid, when in pairs]
        return sorted(out, key=lambda r: r["modified"], reverse=True)

    def test_a_conversation_another_slot_holds_is_never_the_terminals(self):
        """The background chat still answering is the newest by
        construction, and taking it opened it twice."""
        rows = self.rows(("bg-chat", 300), ("terminal-one", 200))
        self.assertEqual(self.chat.pick_adopted(rows, {}, set())["id"], "bg-chat")
        self.assertEqual(
            self.chat.pick_adopted(rows, {}, {"bg-chat"})["id"], "terminal-one")

    def test_with_nothing_written_since_the_handoff_it_is_the_handed_one(self):
        rows = self.rows(("newer-but-older-than-handoff", 150), ("handed", 100))
        handoff = {"session_id": "handed", "ts": 200}
        self.assertEqual(self.chat.pick_adopted(rows, handoff, set())["id"],
                         "handed")

    def test_what_the_terminal_wrote_since_the_handoff_wins(self):
        """The handed conversation continued, or a new one started there —
        either way it is what the terminal has been doing since."""
        rows = self.rows(("started-in-terminal", 260), ("handed", 100))
        handoff = {"session_id": "handed", "ts": 200}
        self.assertEqual(self.chat.pick_adopted(rows, handoff, set())["id"],
                         "started-in-terminal")

    def test_without_a_handoff_the_newest_is_the_only_evidence(self):
        rows = self.rows(("a", 10), ("b", 20))
        self.assertEqual(self.chat.pick_adopted(rows, {}, set())["id"], "b")

    def test_nothing_left_is_nothing_to_adopt(self):
        rows = self.rows(("bg", 10))
        self.assertIsNone(self.chat.pick_adopted(rows, {}, {"bg"}))
        self.assertIsNone(self.chat.pick_adopted([], {}, set()))


class TestTheHandoffRecord(unittest.TestCase):
    """The file is the terminal's instruction, and it deletes it when it
    takes it up — so the panel keeps its own copy."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chat = importlib.import_module("chat_session")
        self._old = (self.chat.HANDOFF_FILE, dict(self.chat._LAST_HANDOFF))
        self.chat.HANDOFF_FILE = os.path.join(self.tmp.name, "handoff.json")
        self.chat._LAST_HANDOFF.clear()

    def tearDown(self):
        self.chat.HANDOFF_FILE = self._old[0]
        self.chat._LAST_HANDOFF.clear()
        self.chat._LAST_HANDOFF.update(self._old[1])
        self.tmp.cleanup()

    def test_a_consumed_file_still_leaves_the_panels_copy(self):
        self.chat._open_in_terminal("aaaa-1111")
        record = self.chat.read_handoff()
        self.assertEqual(record["session_id"], "aaaa-1111")
        os.remove(self.chat.HANDOFF_FILE)       # brain-terminal-start took it
        self.assertEqual(self.chat.read_handoff()["session_id"], "aaaa-1111")

    def test_a_record_that_is_not_an_id_names_nothing(self):
        Path(self.chat.HANDOFF_FILE).write_text(
            json.dumps({"session_id": "../../etc/passwd", "ts": 5}))
        self.assertEqual(self.chat.read_handoff(), {})
        Path(self.chat.HANDOFF_FILE).write_text("not json")
        self.assertEqual(self.chat.read_handoff(), {})


class RouteCase(unittest.IsolatedAsyncioTestCase):
    """The panel's routes over the fake CLI, with the stores in a temp dir."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = self.tmp.name
        for key, value in {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(tmp, "t.json"),
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(tmp, "chat"),
            "BRAIN_CHAT_WORKDIR": tmp,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_SETTINGS_FILE": os.path.join(tmp, "settings.json"),
            "BRAIN_DIR": os.path.join(tmp, "insights"),
            "BRAIN_SECRETS": os.path.join(tmp, "secrets"),
            "BRAIN_RUN_SOURCES": os.path.join(tmp, "run-sources.jsonl"),
            "BRAIN_CHAT_TRASH": os.path.join(tmp, "chat-trash"),
            "BRAIN_TERMINAL_HANDOFF": os.path.join(tmp, "handoff.json"),
            "BRAIN_CHAT_CONTEXT_HOOK": os.path.join(tmp, "no-hook.py"),
        }.items():
            os.environ[key] = value
        for key in _ENV:
            os.environ.pop(key, None)
        os.environ["FAKE_CHAT_MODE"] = "ok"
        for name in ("engine", "settings_store", "run_sources", "conversations",
                     "chat_session", "server"):
            setattr(self, name, importlib.reload(importlib.import_module(name)))
        self.chat_session._LAST_HANDOFF.clear()
        self.conversations.CONFIG_DIR = tmp
        self._olds = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                      findings_store.STATE_FILE, findings_store.INBOX_DIR)
        findings_store.FINDINGS_FILE = Path(tmp) / "findings.json"
        findings_store.SETTLED_FILE = Path(tmp) / "settled.json"
        findings_store.STATE_FILE = Path(tmp) / "nowhere" / ".brain" / "s.json"
        findings_store.INBOX_DIR = Path(tmp) / "findings-inbox"

        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.chat_session.registry().stop_all()
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, findings_store.INBOX_DIR) = self._olds
        for key in _ENV + ("BRAIN_TERMINAL_HANDOFF", "BRAIN_CHAT_CONTEXT_HOOK"):
            os.environ.pop(key, None)
        self.chat_session._LAST_HANDOFF.clear()
        self.tmp.cleanup()

    def registry(self):
        return self.chat_session.registry()

    async def until(self, check, timeout=8.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if check():
                return
            await asyncio.sleep(0.05)
        self.fail("timed out waiting")

    def conversation(self, session_id, *said, when=None):
        """A transcript in Claude Code's own store, as the terminal would
        leave one; ``when`` sets its last activity."""
        project = (Path(self.tmp.name) / "projects"
                   / re.sub(r"[^A-Za-z0-9]", "-", self.tmp.name))
        project.mkdir(parents=True, exist_ok=True)
        path = project / f"{session_id}.jsonl"
        path.write_text("".join(json.dumps({
            "type": "user", "cwd": self.tmp.name,
            "message": {"role": "user", "content": text}}) + "\n"
            for text in said) + "x" * 300 + "\n", encoding="utf-8")
        if when is not None:
            os.utime(path, (when, when))
        return path


class TestDiscussLeavesABusyChatAnswering(RouteCase):
    async def test_discuss_opens_beside_an_answer_rather_than_over_it(self):
        os.environ["FAKE_CHAT_MODE"] = "slow"
        os.environ["FAKE_CHAT_DELAY"] = "2.5"
        busy = self.registry().attached()
        await busy.send("a long question about the heating")
        await self.until(lambda: busy.state == "busy")

        entry, _ = findings_store.add("Porch light never comes on",
                                      entity_id="light.porch",
                                      source="check:auto.dead_ref")
        os.environ["FAKE_CHAT_MODE"] = "ok"
        res = await self.client.post(f"/api/finding/{entry['ts']}/discuss")
        self.assertEqual(res.status, 200)

        discussion = self.registry().attached()
        self.assertIsNot(discussion, busy)
        self.assertEqual(discussion.finding_ts, entry["ts"])
        # The answer being written was not killed to make room.
        self.assertTrue(busy.alive())
        self.assertEqual(busy.state, "busy")
        self.assertIn(busy, self.registry().sessions())
        # And it finishes, in its own transcript.
        await self.until(lambda: busy.state != "busy", timeout=10)
        self.assertTrue(any(e.get("type") == "text" for e in busy.events))
        # The discussion's opener reached its own process.
        self.assertTrue(any(e.get("type") == "user"
                            and "Porch light never comes on" in e.get("text", "")
                            for e in discussion.events))

    async def test_an_empty_chat_on_screen_is_reused_rather_than_spending_a_slot(self):
        before = self.registry().attached()
        entry, _ = findings_store.add("Freezer drifting warm",
                                      source="check:base.unusual")
        res = await self.client.post(f"/api/finding/{entry['ts']}/discuss")
        self.assertEqual(res.status, 200)
        self.assertIs(self.registry().attached(), before)
        self.assertEqual(before.finding_ts, entry["ts"])


class TestAdoptAsksTheRegistry(RouteCase):
    async def test_a_background_chat_is_not_opened_a_second_time(self):
        now = time.time()
        self.conversation("bg-chat", "the heating question")
        await self.registry().open("bg-chat", [])
        await self.registry().new()          # a fresh chat is now on screen
        # The background chat is the most recently written conversation —
        # it is still answering — and the terminal's is older.
        self.conversation("bg-chat", "the heating question", when=now)
        self.conversation("terminal-one", "what the terminal was doing",
                          when=now - 60)

        out = await (await self.client.post("/api/chat/adopt")).json()
        self.assertTrue(out["adopted"])
        self.assertEqual(out["session_id"], "terminal-one")
        ids = [s.session_id for s in self.registry().sessions()]
        self.assertEqual(ids.count("bg-chat"), 1, ids)
        self.assertEqual(self.registry().attached().session_id, "terminal-one")

    async def test_the_handoff_record_beats_a_newer_conversation(self):
        """The newest file is evidence; the record of what was handed over
        is the fact."""
        now = time.time()
        self.conversation("handed", "the chat handed this over", when=now - 300)
        self.conversation("something-else", "a later chat, before the handoff",
                          when=now - 120)
        self.chat_session._LAST_HANDOFF.update(
            {"session_id": "handed", "ts": int(now - 60)})
        out = await (await self.client.post("/api/chat/adopt")).json()
        self.assertTrue(out["adopted"])
        self.assertEqual(out["session_id"], "handed")

    async def test_the_round_trip_shows_what_the_terminal_said(self):
        """Chat -> terminal -> chat on ONE conversation: the id matches the
        one on screen, which used to read as nothing to take up, and the
        pane went on showing the scrollback from before the handoff."""
        now = time.time()
        self.conversation("round-trip", "asked in the chat", when=now - 600)
        await self.registry().open(
            "round-trip", [{"type": "user", "text": "asked in the chat"}])
        out = await (await self.client.post("/api/chat/handoff")).json()
        self.assertEqual(out["session_id"], "round-trip")
        session = self.registry().attached()
        await self.until(lambda: not session.alive())
        # The terminal carried it on.
        self.conversation("round-trip", "asked in the chat",
                          "asked in the terminal", when=now + 5)

        out = await (await self.client.post("/api/chat/adopt")).json()
        self.assertTrue(out["adopted"])
        self.assertEqual(out["session_id"], "round-trip")
        said = [e.get("text") for e in self.registry().attached().events
                if e.get("type") == "user"]
        self.assertIn("asked in the terminal", said)

    async def test_the_cap_is_the_one_refusal_left(self):
        """Every live chat busy and the cap reached: there is nothing to
        pause, and the refusal says so in the cap's own words."""
        self.settings_store.save({"chat_max_sessions": 1})
        os.environ["FAKE_CHAT_MODE"] = "slow"
        os.environ["FAKE_CHAT_DELAY"] = "3"
        busy = self.registry().attached()
        await busy.send("long")
        await self.until(lambda: busy.state == "busy")
        self.conversation("terminal-one", "what the terminal was doing",
                          when=time.time())
        res = await self.client.post("/api/chat/adopt")
        self.assertEqual(res.status, 409)
        self.assertTrue(busy.alive())


if __name__ == "__main__":
    unittest.main()
