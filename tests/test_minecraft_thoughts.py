"""brAIn shows what it is thinking in the game, where it is not in the way.

The owner: *"I want the add on to be able to represent Vesper when it's
thinking so you can see the stream of thought, what it's working on, etc. The
chat is generally terrible and communicating this"* — and then: *"Make sure
it's not super annoying. It could be represented over vesper's allay or be
shown in an item the player can use."*

So the faculty and the MCP server tell BRUH Minecraft's `companion_thought`
each step (a bubble only the player it works for sees, over the allay when it
is near, and the journal book), never chat:

* a quick answer is a "thinking" line the add-on shows only once it lasts,
  cleared when the answer is said;
* a job is its own line, with its progress, ending done or failed;
* each game tool a run calls is a step in a few words (the MCP server, from
  BRAIN_THOUGHT_TO / BRAIN_THOUGHT_KEY the listener sets on the game's two
  channels), sent straight over the WebSocket so History is not a list of
  thoughts, and `minecraft_world think` is the run's own words;
* everyone on the family list gets "<persona>'s Thoughts" on join;
* ⚙ › Minecraft's "Show what it is thinking" off sends none of it.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "brain" / "ha-mcp-server"))

from test_brain_minecraft_faculty import DAD  # noqa: E402
from test_minecraft_desk import DeskCase  # noqa: E402

import ha_mcp_server as m  # noqa: E402
from test_mcp_bruh_addons import Base  # noqa: E402


class TestTheFacultyThinksOutLoud(DeskCase):
    def thoughts(self):
        return self.addon.of("companion_thought")

    def test_a_quick_answer_is_a_thinking_line_then_cleared_and_never_chat(self):
        self.join(DAD)
        self.chat(DAD, "what's this?")
        got = self.thoughts()
        self.assertEqual([(t["state"], t["key"]) for t in got],
                         [("thinking", "talk"), ("clear", "talk")])
        self.assertEqual(got[0]["player"], DAD)
        self.assertEqual(self.lines_to(DAD)[-1], "Sure!")
        self.assertNotIn("thinking", " ".join(self.lines_to(DAD)).lower())

    def test_the_run_is_told_who_its_steps_are_shown_to(self):
        self.join(DAD)
        self.chat(DAD, "hello")
        self.assertEqual(self.brain.of("quick")[0]["thought"], {"player": DAD, "key": "talk"})

    def test_a_job_is_its_own_line_with_progress_and_an_end(self):
        self.join(DAD)
        self.brain.quick.append({"reply": "On it.", "job": {"title": "a couch", "brief": "x"}})
        self.chat(DAD, "build a couch")
        job = self.jobs()[-1]
        mine = [t for t in self.thoughts() if t["key"] == job["id"]]
        self.assertEqual(mine[0]["state"], "working")
        self.assertEqual(mine[0]["title"], "a couch")
        self.assertEqual(mine[-1]["state"], "done")
        self.assertEqual(self.brain.of("work")[0]["thought"], {"player": DAD, "key": job["id"]})

    def test_progress_goes_to_the_jobs_line(self):
        self.join(DAD)
        self.brain.holds["work"] = __import__("asyncio").Event()
        self.brain.quick.append({"reply": "On it.", "job": {"title": "a tower", "brief": "x"}})
        self.clock.t += 10
        self.fire("chat", player=DAD, name=DAD, text="build a tower", verified=True)
        self.wait_until(lambda: any(j["status"] == "running" for j in self.jobs()))
        job = self.jobs()[-1]
        self.job_service(action="progress", job=job["id"], text="walls up", percent=40)
        last = [t for t in self.thoughts() if t["key"] == job["id"]][-1]
        self.assertEqual((last["text"], last["percent"]), ("walls up", 40))
        self.assertFalse(self.addon.of("companion_progress"), "the bubble, not the action bar")
        self.brain.holds["work"].set()
        self.settle()

    def test_the_journal_on_join(self):
        self.join(DAD)
        given = self.addon.of("give_journal")
        self.assertEqual(len(given), 1)
        self.assertEqual(given[0]["player"], DAD)
        self.assertTrue(given[0]["name"].endswith("'s Thoughts"))

    def test_an_add_on_without_the_service_is_said_once_in_the_log(self):
        self.addon.refuse.add("companion_thought")
        self.join(DAD)
        with self.assertLogs(level="WARNING") as logs:
            self.chat(DAD, "hello")
            self.chat(DAD, "hello again")
        said = [r for r in logs.output if "restart Home Assistant" in r]
        self.assertEqual(len(said), 1)
        self.assertEqual(self.lines_to(DAD)[-1], "Sure!", "the answer still comes")

    def test_switched_off_there_is_no_bubble_no_journal_no_steps(self):
        self.write_settings(**{**self.settings, "thoughts": False})
        self.join(DAD)
        self.chat(DAD, "hello")
        self.assertFalse(self.thoughts())
        self.assertFalse(self.addon.of("give_journal"))
        self.assertNotIn("thought", self.brain.of("quick")[0])


class TestTheMcpServerShowsEachStep(Base):
    def env(self, **extra):
        values = {"BRAIN_CHANNEL": "minecraft", "BRAIN_THOUGHT_TO": "Ben13765",
                  "BRAIN_THOUGHT_KEY": "talk", **extra}
        p = patch.dict(os.environ, values)
        p.start()
        self.addCleanup(p.stop)

    def sent(self):
        return [d for (svc, d) in self.core.calls if svc == ("bruh_minecraft", "companion_thought")]

    def test_steps_in_words_a_child_can_read(self):
        self.assertEqual(m.thought_step("minecraft_world", {"action": "look", "player": "Ben"}),
                         "looking at the blocks around Ben")
        self.assertEqual(m.thought_step("minecraft_world", {
            "action": "edit", "value": "a couch",
            "fills": [{"x1": 0, "y1": 0, "z1": 0, "x2": 2, "y2": 0, "z2": 1}],
            "blocks": [{"x": 5, "y": 5, "z": 5}]}), "placing 7 blocks for a couch")
        self.assertEqual(m.thought_step("minecraft_world", {"action": "atlas", "value": "barn"}),
                         "searching the map for barn")
        self.assertIsNone(m.thought_step("minecraft_world", {"action": "say"}))
        self.assertIsNone(m.thought_step("minecraft_job", {"action": "progress"}))

    def test_a_tool_call_on_the_game_channel_is_shown_without_a_ledger_row(self):
        self.env()
        ledger = []
        with patch.object(m, "record_action", lambda *a, **k: ledger.append(a)), \
                patch.object(m, "minecraft_status", lambda **k: {"ok": True}):
            m.handle_tool_call("minecraft_status", {})
            worker = m._THOUGHTS["worker"]
            if worker is not None:
                worker.join(5)
        self.assertEqual(self.sent(), [{"player": "Ben13765", "key": "talk", "state": "working",
                                        "text": "checking who's where"}])
        self.assertEqual(ledger, [])

    def test_nothing_is_shown_off_the_game_channels(self):
        self.env(BRAIN_CHANNEL="chat")
        with patch.object(m, "minecraft_status", lambda **k: {"ok": True}):
            m.handle_tool_call("minecraft_status", {})
        self.assertEqual(self.sent(), [])
        self.assertFalse(m._mc_thought("hello", wait=True))

    def test_think_is_the_runs_own_words(self):
        self.env(BRAIN_THOUGHT_KEY="j1a2b3c")
        got = m.minecraft_world("think", value="the roof first, then the windows")
        self.assertTrue(got["shown"], got)
        self.assertEqual(self.sent()[-1]["text"], "the roof first, then the windows")
        self.assertEqual(self.sent()[-1]["key"], "j1a2b3c")

    def test_think_with_nobody_to_show_says_so(self):
        self.env(BRAIN_THOUGHT_TO="")
        got = m.minecraft_world("think", value="hmm")
        self.assertFalse(got["shown"])
        self.assertIn("note", got)


if __name__ == "__main__":
    unittest.main()
