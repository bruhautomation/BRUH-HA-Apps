"""The companion checks a block quietly, and links a button to the house (#761, #777).

`execute if block … run say ok` put "[Rcon] ok" in every player's chat
1,300 times in one build (#761): the companion was checking its own work and
nobody had told it that `minecraft_world look` reads the blocks, or that a
bare `execute if block` answers "Test passed"/"Test failed" to the caller.
And asked for a lever that turns the real lights on (#777), it wrote a
Skript listener; BRUH Minecraft 1.19.7 fires `bruh_minecraft_signal`
{name, data} when a command block runs `say bruh:signal <name> [data]`, which
an ordinary Home Assistant automation triggers on.

Driven here: every game run's rules say how to check a block and never
`run say`; a trusted grown-up's run (the one with the console and the house)
is told the signal recipe — one name per button, an unrenamed command block,
the event an automation triggers on; a child's run is not offered a link to
the house; and `minecraft_world`'s own description carries only the quiet
check, because tools/list serves it to the game channel a child's run uses.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "brain" / "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402
from test_brain_minecraft_faculty import DAD, KAZ, mc  # noqa: E402
from test_minecraft_desk import DeskCase  # noqa: E402

GROWN_UP = {"person": "Dad", "player": DAD, "role": "reader", "trusted": True}
CHILD = {"person": "Kaz", "player": KAZ, "role": "child"}


class TestTheRules(DeskCase):
    def head(self, who, tools):
        return self.c._rules_head(who, "Juniper", tools)

    def test_every_game_run_checks_with_look_and_never_run_say(self):
        for who, tools in ((GROWN_UP, mc.TRUSTED_TOOLS), (CHILD, mc.TALK_TOOLS),
                           (GROWN_UP, mc.TALK_TOOLS)):
            head = self.head(who, tools)
            self.assertIn("minecraft_world look", head)
            self.assertIn("never", head.split("run say")[0][-200:].lower(), tools)

    def test_the_trusted_run_may_test_a_block_bare(self):
        head = self.head(GROWN_UP, mc.TRUSTED_TOOLS)
        self.assertIn("execute if block", head)
        self.assertIn("Test passed", head)
        self.assertIn("Test failed", head)

    def test_the_trusted_run_is_told_the_signal_recipe(self):
        head = self.head(GROWN_UP, mc.TRUSTED_TOOLS)
        for words in ("say bruh:signal <name> [data]", "bruh_minecraft_signal",
                      "automation", "one name per button", "unrenamed command block"):
            self.assertIn(words, head)

    def test_only_the_trusted_head_carries_the_signal(self):
        self.assertIn("bruh:signal", self.head(GROWN_UP, mc.TRUSTED_TOOLS))
        tool = next(t for t in m.TOOLS if t["name"] == "minecraft_world")
        self.assertNotIn("bruh:signal", tool["description"])

    def test_a_childs_run_is_offered_no_link_to_the_house(self):
        for who in (CHILD, GROWN_UP):
            head = self.head(who, mc.TALK_TOOLS)
            self.assertNotIn("bruh:signal", head)
            self.assertNotIn("execute if block", head)


class TestTheToolSaysSo(unittest.TestCase):
    """`minecraft_world`'s description is served on every non-voice channel,
    the game channel a child's guarded run uses among them, so the house
    link lives only in the trusted run's head and never in the tool."""

    def description(self):
        return next(t for t in m.TOOLS if t["name"] == "minecraft_world")["description"]

    def test_the_description_names_the_quiet_check_but_not_the_signal(self):
        text = self.description()
        self.assertNotIn("bruh:signal", text)
        self.assertNotIn("bruh_minecraft_signal", text)
        self.assertIn("run say", text)
        self.assertIn("dimension", text)

    def test_the_game_channels_tool_list_offers_no_signal(self):
        env = {"BRAIN_CHANNEL": m.MINECRAFT_CHANNEL, "BRAIN_GAME_PLAYER": KAZ}
        with patch.dict(os.environ, env), \
                patch.object(m, "_absent_addon_tools", return_value=set()):
            tools = m.tools_for_channel()
        self.assertIn("minecraft_world", [t["name"] for t in tools])
        self.assertNotIn("bruh:signal", json.dumps(tools))

    def test_voice_sees_none_of_it(self):
        voice = m.VOICE_TOOL_VARIANTS["minecraft_world"]["description"]
        self.assertNotIn("bruh:signal", voice)

if __name__ == "__main__":
    unittest.main()
