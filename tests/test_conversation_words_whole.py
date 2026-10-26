#!/usr/bin/env python3
"""A conversation's own words are never cut for the screen.

A request another BRUH add-on hands brAIn is long — a dashboard change
request carries the dashboard and a picture's description before the
person's own words, which come LAST — and the chat cut every user turn and
every reply at 4,000 characters for display. So the one sentence that was
the point of the conversation was never on screen, and a reply longer than
a page stopped mid-thought under a note saying Claude had the rest.

What a person said and what Claude said back are drawn whole, in the live
chat and in the replay; long ones are folded behind a press in the panel.
Tool inputs and results keep their display clip: they are working, not the
conversation, and a 10 MB log in a browser is still a cost.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import chat_session  # noqa: E402

# An invented change request: a long frame, the person's words at the end.
FRAME = "\n".join(f"line {i}: the dashboard as it stands, card c_{i} in room r_{i % 9}"
                  for i in range(460))
REQUEST = "Asked: “make the hallway card show the lamp and the door together”"
OPENER = FRAME + "\n\nTHE REQUEST\n" + REQUEST
REPLY = " ".join(f"step{i:04d} done" for i in range(2600))          # ~26,000 chars
THOUGHT = " ".join(f"consider{i:04d}" for i in range(1500))         # ~19,000 chars


def _entry(**kw):
    return json.dumps(kw) + "\n"


class TestTheReplayKeepsSpeechWhole(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        import conversations
        self.mod = importlib.reload(conversations)
        project = Path(self.tmp.name) / "projects" / "-config"
        project.mkdir(parents=True)
        (project / "aaa.jsonl").write_text(
            _entry(type="user", message={"role": "user", "content": OPENER})
            + _entry(type="assistant", message={"role": "assistant", "content": [
                {"type": "thinking", "thinking": THOUGHT},
                {"type": "text", "text": REPLY},
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "/x", "pad": "y" * 20000}}]})
            + _entry(type="user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "z" * 30000}]}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_opening_request_is_whole_and_ends_with_the_persons_words(self):
        self.assertGreater(len(OPENER), 26000)
        events = self.mod.transcript("/config", "aaa")
        user = next(e for e in events if e["type"] == "user")
        self.assertEqual(user["text"], OPENER)
        self.assertTrue(user["text"].endswith(REQUEST))

    def test_a_reply_and_its_thinking_are_whole(self):
        events = self.mod.transcript("/config", "aaa")
        self.assertEqual(next(e for e in events if e["type"] == "text")["text"], REPLY)
        self.assertEqual(next(e for e in events if e["type"] == "thinking")["text"], THOUGHT)

    def test_tool_traffic_keeps_its_display_clip(self):
        events = self.mod.transcript("/config", "aaa")
        tool = next(e for e in events if e["type"] == "tool")
        result = next(e for e in events if e["type"] == "tool_result")
        self.assertIn("display truncated", tool["input"])
        self.assertIn("display truncated", result["text"])


class TestTheLiveChatKeepsSpeechWhole(unittest.TestCase):
    def test_an_answer_and_its_thinking_are_whole(self):
        out = chat_session._normalise({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": THOUGHT},
            {"type": "text", "text": REPLY * 2}]}})
        self.assertEqual(out[0]["text"], THOUGHT)
        self.assertEqual(out[1]["text"], REPLY * 2)

    def test_a_tool_result_is_still_clipped(self):
        out = chat_session._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "w " * 20000}]}})
        self.assertIn("display truncated", out[0]["text"])


if __name__ == "__main__":
    unittest.main()
