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

import datetime as dt
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

    @staticmethod
    def _iso(age_s):
        """An entry timestamp the way the CLI writes one, age_s ago."""
        when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=age_s)
        return when.isoformat().replace("+00:00", "Z")

    def test_browsing_a_conversation_does_not_bump_it_to_the_top(self):
        """The CLI touches a session file's mtime the moment it is resumed —
        before a word is exchanged (verified on 2.1.234) — and the panel
        resumes a conversation just to LOOK at it. Ordered by mtime, merely
        browsing old conversations shuffled them all to the top stamped
        "just now"; a row's place and age come from its newest stamped
        entry instead. The untimestamped housekeeping lines the CLI closes
        every file with (`last-prompt`, `mode`) are skipped, not trusted."""
        self._write("new", [user_entry("fresh talk", timestamp=self._iso(60)),
                            "x" * 300 + "\n"])
        # Written second, so its mtime is the newest in the directory — the
        # shape a just-browsed old conversation has.
        self._write("old", [user_entry("ancient history",
                                       timestamp=self._iso(7200)),
                            entry(type="last-prompt"),
                            entry(type="mode"),
                            "x" * 300 + "\n"])
        rows = self.mod.listing(self.cwd)
        self.assertEqual([r["id"] for r in rows], ["new", "old"])
        self.assertEqual(rows[0]["age"], "just now")
        self.assertEqual(rows[1]["age"], "2 h ago")

    def test_a_transcript_with_no_stamped_entries_still_has_a_time(self):
        """Not every line carries a timestamp; a file whose tail offers none
        falls back to its mtime rather than to no answer."""
        self._write("aaa", [user_entry("undated"), "x" * 300 + "\n"],
                    age_s=7200)
        self.assertEqual(self.mod.listing(self.cwd)[0]["age"], "2 h ago")

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
        scrollback — the CLI still holds the context. Talk is kept ahead of
        tool calls, but more talk than the budget is still trimmed to the
        newest rather than kept whole for being talk."""
        lines = [user_entry(f"message {i}") for i in range(500)]
        self._write("aaa", lines)
        events = self.mod.transcript(self.cwd, "aaa", limit=25)
        self.assertEqual(len(events), 25)
        self.assertEqual(events[-1]["text"], "message 499")

    def _tool_turn(self, n):
        """One working exchange: a call, its result, a sentence about it."""
        return [
            assistant_entry([{"type": "tool_use", "id": f"t{n}", "name": "Read",
                              "input": {"file_path": f"/config/{n}.yaml"}}]),
            entry(type="user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{n}",
                 "content": "ok"}]}),
        ]

    def test_the_budget_is_spent_on_the_conversation_not_the_tool_chatter(self):
        """The bug behind "not all the messages come over".

        Measured on a real transcript, 92% of replay events were tool calls
        and their results — so a flat "newest N" window carried 3 of the 17
        things the person had said. Switching faces showed the last few
        minutes of tool chatter and almost none of the conversation.
        """
        lines = []
        for i in range(60):
            lines.append(user_entry(f"question {i}"))
            for n in range(10):
                lines += self._tool_turn(f"{i}-{n}")
            lines.append(assistant_entry([{"type": "text", "text": f"answer {i}"}]))
        self._write("aaa", lines)

        events = self.mod.transcript(self.cwd, "aaa", limit=400)
        self.assertLessEqual(len(events), 400)
        said = [e["text"] for e in events if e["type"] == "user"]
        replied = [e["text"] for e in events if e["type"] == "text"]
        # every word either party said survives — that is the conversation
        self.assertEqual(len(said), 60)
        self.assertEqual(said[0], "question 0")
        self.assertEqual(len(replied), 60)
        # ...and the leftover budget still buys the most recent tool calls
        self.assertTrue([e for e in events if e["type"] == "tool"])

    def test_a_trimmed_replay_never_leaves_half_a_tool_call(self):
        """A call with no result renders as a spinner that never stops, and a
        result with no call renders as nothing while still costing a slot."""
        lines = []
        for n in range(200):
            lines += self._tool_turn(n)
        self._write("aaa", lines)

        events = self.mod.transcript(self.cwd, "aaa", limit=51)
        calls = {e["id"] for e in events if e["type"] == "tool"}
        results = {e["id"] for e in events if e["type"] == "tool_result"}
        self.assertEqual(calls, results)
        self.assertTrue(calls)

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


class DeleteCase(ConversationsCase):
    """The one mutation this module offers: a person removing a whole
    conversation, as a move into our trash — never a write into the CLI's
    files — so the toast's Undo can put back exactly what was taken."""

    def setUp(self):
        super().setUp()
        self.mod.TRASH_DIR = os.path.join(self.tmp.name, "trash")

    def test_delete_moves_the_file_and_restore_moves_it_back(self):
        # Padded past the listing's empty-session floor, like a real one.
        path = self._write("goner", [user_entry("delete me"), "x" * 300 + "\n"])
        entry = self.mod.delete(self.cwd, "goner")
        self.assertEqual(entry["id"], "goner")
        self.assertFalse(path.exists())
        self.assertTrue(Path(entry["trash"]).is_file())
        self.assertNotIn("goner", [c["id"] for c in self.mod.listing(self.cwd)])

        self.assertTrue(self.mod.restore_deleted(entry))
        self.assertTrue(path.is_file())
        self.assertIn("delete me",
                      [c["title"] for c in self.mod.listing(self.cwd)])

    def test_deleting_nothing_says_so_instead_of_pretending(self):
        self.assertIsNone(self.mod.delete(self.cwd, "never-existed"))

    def test_a_delete_id_cannot_climb_out_of_the_directory(self):
        outside = Path(self.tmp.name) / "secret.jsonl"
        outside.write_text(user_entry("not yours"))
        for bad in ("../secret", "/etc/passwd", "a/../../secret", ""):
            self.assertIsNone(self.mod.delete(self.cwd, bad), bad)
        self.assertTrue(outside.is_file())

    def test_restore_refuses_to_overwrite(self):
        """Session ids are UUIDs, so an occupied path means something else
        went wrong — and losing it to an Undo would compound the mistake."""
        path = self._write("goner", [user_entry("the original")])
        entry = self.mod.delete(self.cwd, "goner")
        path.write_text(user_entry("something newer"))
        self.assertFalse(self.mod.restore_deleted(entry))
        self.assertIn("something newer", path.read_text())

    def test_restore_after_the_trash_was_pruned_reports_failure(self):
        entry = {"id": "gone", "path": str(self.project / "gone.jsonl"),
                 "trash": os.path.join(self.mod.TRASH_DIR, "gone.jsonl")}
        self.assertFalse(self.mod.restore_deleted(entry))

    def test_the_trash_is_a_grace_period_not_an_archive(self):
        """Expired entries go, and the cap holds even against a deletion
        spree — the delete button must not quietly keep what it promised
        to remove."""
        self._write("old-one", [user_entry("long gone")])
        self.mod.delete(self.cwd, "old-one")
        stale = Path(self.mod.TRASH_DIR) / "old-one.jsonl"
        when = time.time() - self.mod.TRASH_TTL_S - 60
        os.utime(stale, (when, when))

        for n in range(self.mod.TRASH_MAX + 5):
            self._write(f"s{n}", [user_entry(f"conversation {n}")])
            self.assertIsNotNone(self.mod.delete(self.cwd, f"s{n}"))

        remaining = list(Path(self.mod.TRASH_DIR).glob("*.jsonl"))
        self.assertNotIn(stale, remaining, "an expired entry survived")
        self.assertLessEqual(len(remaining), self.mod.TRASH_MAX)


if __name__ == "__main__":
    unittest.main()
