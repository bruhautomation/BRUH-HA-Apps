#!/usr/bin/env python3
"""Reading Claude Code's own conversation store.

This is what makes the chat pane and the classic terminal interchangeable
rather than merely adjacent: the CLI files every conversation under
``~/.claude/projects/<escaped working directory>/``, so the panel can list
what exists — whichever face made it — and replay one into the chat.

Both the directory name and "which entry is the title" are inference rather
than published contract, so the tests pin the inference *and* the soft
failures: a wrong directory name falls back to asking the transcripts where
they ran, and a conversation whose title cannot be found is still listed.
"""

import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))


def entry(**kw):
    return json.dumps(kw) + "\n"


def user_entry(text, **kw):
    return entry(type="user", message={"role": "user", "content": text}, **kw)


def assistant_entry(blocks, **kw):
    return entry(type="assistant", message={"role": "assistant", "content": blocks}, **kw)


class ConversationsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["CLAUDE_CONFIG_DIR"] = self.tmp.name
        import conversations
        self.mod = importlib.reload(conversations)
        self.cwd = "/config"
        self.project = Path(self.tmp.name) / "projects" / "-config"
        self.project.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, session_id, lines, age_s=0):
        path = self.project / f"{session_id}.jsonl"
        path.write_text("".join(lines))
        if age_s:
            when = time.time() - age_s
            os.utime(path, (when, when))
        return path

    # -- the directory ---------------------------------------------------

    def test_the_project_directory_is_the_escaped_working_directory(self):
        self.assertEqual(self.mod.project_dir("/config"), self.project)

    def test_a_wrong_guess_falls_back_to_asking_the_transcripts(self):
        """The escaping rule is derived, not published. If it ever changes,
        the transcripts still say which directory they ran in — better than
        an empty list and a shrug."""
        odd = Path(self.tmp.name) / "projects" / "some-other-name"
        odd.mkdir()
        (odd / "s1.jsonl").write_text(
            entry(type="system", cwd="/somewhere/else") + "x" * 300)
        self.assertIsNone(self.mod.project_dir("/somewhere/nope"))
        self.assertEqual(self.mod.project_dir("/somewhere/else"), odd)

    def test_no_store_at_all_is_an_empty_list_not_a_crash(self):
        self.mod.CONFIG_DIR = "/nonexistent/nowhere"
        self.assertEqual(self.mod.listing("/config"), [])
        self.assertEqual(self.mod.transcript("/config", "abc"), [])

    # -- the listing -----------------------------------------------------

    def test_conversations_are_listed_newest_first_with_their_opening_line(self):
        self._write("aaa", [user_entry("why is the porch light off"),
                            "x" * 300 + "\n"], age_s=7200)
        self._write("bbb", [user_entry("rename the garage switches"),
                            "x" * 300 + "\n"], age_s=60)
        rows = self.mod.listing(self.cwd)
        self.assertEqual([r["id"] for r in rows], ["bbb", "aaa"])
        self.assertEqual(rows[0]["title"], "rename the garage switches")
        self.assertEqual(rows[0]["age"], "just now")
        self.assertEqual(rows[1]["age"], "2 h ago")

    def test_the_current_conversation_is_not_offered_as_somewhere_to_go(self):
        self._write("aaa", [user_entry("one"), "x" * 300 + "\n"])
        self._write("bbb", [user_entry("two"), "x" * 300 + "\n"])
        rows = self.mod.listing(self.cwd, exclude="bbb")
        self.assertEqual([r["id"] for r in rows], ["aaa"])

    def test_an_empty_session_file_is_not_offered(self):
        """A session opened and never used is a dead end to resume into."""
        self._write("empty", [entry(type="system", subtype="init")])
        self.assertEqual(self.mod.listing(self.cwd), [])

    def test_injected_entries_are_not_mistaken_for_the_opening_line(self):
        """The file carries interruptions, tool results and system notices
        as `user` entries. Any of those as a title is a conversation nobody
        recognises."""
        self._write("aaa", [
            user_entry("<system-reminder>be nice</system-reminder>"),
            user_entry("[Request interrupted by user for tool use]"),
            entry(type="user", isMeta=True,
                  message={"role": "user", "content": "meta"}),
            user_entry("the actual question"),
            "x" * 300 + "\n",
        ])
        self.assertEqual(self.mod.listing(self.cwd)[0]["title"],
                         "the actual question")

    def test_a_conversation_with_no_findable_title_is_still_listed(self):
        self._write("aaa", [assistant_entry([{"type": "text", "text": "hi"}]),
                            "x" * 300 + "\n"])
        rows = self.mod.listing(self.cwd)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "(no opening message)")

    # -- the replay ------------------------------------------------------

    def test_a_stored_conversation_replays_into_chat_events(self):
        """The CLI's stored messages are the same shapes it streams, so they
        render through exactly the same path as a live turn."""
        self._write("aaa", [
            user_entry("why is the porch light off"),
            assistant_entry([
                {"type": "thinking", "thinking": "checking the automation"},
                {"type": "text", "text": "Looking at `automations.yaml`."},
                {"type": "tool_use", "id": "t1", "name": "Read",
                 "input": {"file_path": "/config/automations.yaml"}},
            ]),
            entry(type="user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": "- id: porch"}]}]}),
            assistant_entry([{"type": "text", "text": "Its trigger never fires."}]),
        ])
        events = self.mod.transcript(self.cwd, "aaa")
        self.assertEqual([e["type"] for e in events],
                         ["user", "thinking", "text", "tool", "tool_result", "text"])
        self.assertEqual(events[0]["text"], "why is the porch light off")
        self.assertEqual(events[3]["name"], "Read")
        self.assertEqual(events[3]["summary"], "/config/automations.yaml")
        self.assertEqual(events[4]["id"], "t1")
        self.assertTrue(events[4]["ok"])

    def test_sidechains_are_left_out_of_the_replay(self):
        """A subagent's conversation is not this conversation."""
        self._write("aaa", [
            user_entry("do the thing"),
            user_entry("subagent chatter", isSidechain=True),
            assistant_entry([{"type": "text", "text": "done"}], isSidechain=True),
        ])
        events = self.mod.transcript(self.cwd, "aaa")
        self.assertEqual([e["type"] for e in events], ["user"])

    def test_the_replay_is_capped_to_the_newest_events(self):
        """A month-long session is a 10 MB file. What the pane needs is a
        scrollback — the CLI still holds the context."""
        lines = [user_entry(f"message {i}") for i in range(500)]
        self._write("aaa", lines)
        events = self.mod.transcript(self.cwd, "aaa", limit=25)
        self.assertEqual(len(events), 25)
        self.assertEqual(events[-1]["text"], "message 499")

    def test_a_session_id_cannot_climb_out_of_the_directory(self):
        outside = Path(self.tmp.name) / "secret.jsonl"
        outside.write_text(user_entry("not yours"))
        for bad in ("../secret", "/etc/passwd", "a/../../secret", ""):
            self.assertEqual(self.mod.transcript(self.cwd, bad), [], bad)

    def test_a_giant_message_is_clipped(self):
        self._write("aaa", [user_entry("x" * 99999)])
        events = self.mod.transcript(self.cwd, "aaa")
        self.assertLess(len(events[0]["text"]), self.mod.MAX_TEXT + 100)
        self.assertIn("truncated", events[0]["text"])


if __name__ == "__main__":
    unittest.main()
