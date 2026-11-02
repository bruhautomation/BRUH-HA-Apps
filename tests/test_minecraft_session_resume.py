#!/usr/bin/env python3
"""A player's game lines resume one CLI session, on the game's own channel.

The Minecraft companion's quick runs (docs/design/minecraft-companion.md
§2) keep a CLI session per player and resume it while they talk, so "make
it taller" means the tower from a minute ago. Until now only a
`kind: conversation` task resumed, and it did so by becoming the chat
(`BRAIN_CHANNEL=chat`) — which a game line must never be: the MCP server and
the action gate hold the `minecraft` channel to the game world.

Driven through the REAL `process_task` over the fake CLI
(`test_morph_contracts_listener`' harness), and the bridge's half — the
`session_id` it writes and the one it reads back — through the real
`bridge.py`.

Mutations each test names:

  only conversations resume   drop the game scopes from the session read ->
                              no `--resume` in the argv
  it becomes the chat         export BRAIN_CHANNEL=chat for it -> the argv
                              log says `chat`
  a lost session fails        drop the fresh start -> the result is failed
  the session is not said     drop the game scopes from the result's extra ->
                              no `session_id` in the result
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_morph_contracts_listener import ConversationCase  # noqa: E402
from test_task_failures import INTEGRATION_DIR  # noqa: E402
import test_task_tool_scope  # noqa: E402

SID = "55555555-5555-5555-5555-555555555555"


class TestAGameLineResumesItsSession(ConversationCase):
    def game(self, tools="minecraft", **task):
        return self.run_conversation({"kind": "task", "tools": tools, **task})

    def test_a_game_line_resumes_on_the_games_channel(self):
        result = self.game(session_id=SID)
        self.assertEqual(result["status"], "completed", result)
        call = self.calls()[0]
        self.assertEqual(call[call.index("--resume") + 1], SID)
        log = self.argv_log.read_text().splitlines()
        self.assertIn("ENV BRAIN_CHANNEL=minecraft", log)
        self.assertNotIn("ENV BRAIN_CHANNEL=chat", log)
        self.assertEqual(result["session_id"], SID)
        self.assertIs(result["resumed"], True)

    def test_the_first_line_names_the_session_it_started(self):
        result = self.game()
        self.assertNotIn("--resume", self.calls()[0])
        self.assertEqual(result["session_id"], "22222222-2222-2222-2222-222222222222")

    def test_a_lost_session_starts_fresh_without_a_sentence_in_the_reply(self):
        result = self.run_conversation({"kind": "task", "tools": "minecraft",
                                        "session_id": SID}, FAKE_RESUME_MISSING=SID)
        self.assertEqual(result["status"], "completed", result)
        self.assertIs(result["resumed"], False)
        self.assertNotIn("could not pick up", result["result"])
        self.assertEqual(len(self.calls()), 2)
        self.assertNotIn("--resume", self.calls()[1])

    def test_a_trusted_line_resumes_on_its_own_channel(self):
        self.game(tools="minecraft_trusted", session_id=SID)
        call = self.calls()[0]
        self.assertEqual(call[call.index("--resume") + 1], SID)
        self.assertIn("ENV BRAIN_CHANNEL=minecraft_trusted",
                      self.argv_log.read_text().splitlines())

    def test_any_other_task_never_resumes(self):
        self.run_conversation({"kind": "task", "tools": "read_only", "session_id": SID})
        self.assertNotIn("--resume", self.calls()[0])

    def test_a_session_id_that_is_not_one_is_never_an_argument(self):
        self.game(session_id="x; rm -rf /")
        self.assertNotIn("--resume", self.calls()[0])


def _task(**kw):
    """What the bridge puts on disk (test_task_tool_scope's reader)."""
    return test_task_tool_scope.TestTheBridgeWritesIt._task(None, **kw)


class TestTheBridgeCarriesIt(unittest.TestCase):
    def test_the_session_rides_in_the_task_file_only_when_it_is_one(self):
        self.assertEqual(_task(session_id=SID)["session_id"], SID)
        self.assertNotIn("session_id", _task())
        self.assertNotIn("session_id", _task(session_id="x; rm -rf /"))

    def test_the_result_hands_the_session_back(self):
        src = (INTEGRATION_DIR / "bridge.py").read_text(encoding="utf-8")
        reader = src.split("def _read_json_and_remove", 1)[1]
        self.assertIn('"session_id": str(data.get("session_id") or "")', reader)
        self.assertIn("session_id: str | None = None", src.split("async def async_send_task_full",
                                                                 1)[1][:800])


if __name__ == "__main__":
    unittest.main()
