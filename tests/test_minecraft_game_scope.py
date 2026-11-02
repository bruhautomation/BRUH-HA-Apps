#!/usr/bin/env python3
"""Every verified family member gets the game scope, edits and jobs included.

docs/design/minecraft-companion.md §3: *"Every family member, child or
grown-up, verified, gets the game scope (`minecraft`): the game tools,
including `edit` (undoable) and shapes. `edit` is no longer refused on that
channel. Voice still may not edit."* — and §2's `minecraft_job` tool, on
every game scope and never voice. The words-only `minecraft_talk` scope a
child's line used to run under is gone.

Held in the same four places the game scope always was, each driven here:
the listener's `task_tool_flags`, the MCP server's tool and chokepoint, the
action gate, and the engine's lists.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "brain" / "ha-mcp-server"))
sys.path.insert(0, str(REPO / "brain" / "panel"))

import engine  # noqa: E402
import ha_mcp_server as m  # noqa: E402
from test_action_gate import PFX, GateCase  # noqa: E402
from test_mcp_bruh_addons import Base, FakeCore  # noqa: E402
from test_task_tool_scope import LISTENER, flags_for  # noqa: E402

MCP = "mcp__home-assistant__"
FAMILY = [{"person": "Steve", "role": "child", "players": ["Steve"]},
          {"person": "Dad", "role": "reader", "players": ["DadCraft42"]}]


class JobCore(FakeCore):
    def __call__(self, payload, timeout=15):
        if payload.get("type") == "call_service":
            key = (payload["domain"], payload["service"])
            data = payload.get("service_data") or {}
            if key == ("bruh_minecraft", "companion_edit"):
                self.calls.append((key, data))
                return {"response": {"action": {"id": "e-77", "text": "Juniper made a tree"},
                                     "changed": 900}}
            if key == ("bruh_minecraft", "atlas"):
                self.calls.append((key, data))
                return {"response": {"here": {"room": "r7", "room_name": "the kitchen"},
                                     "buildings": [{"id": "b1", "name": "the farmhouse"}]}}
            if key == ("bruh_minecraft", "room"):
                self.calls.append((key, data))
                return {"response": {"room": {"id": "r7", "name": "the kitchen",
                                              "floor_y": 64}}}
            if key == ("brain", "minecraft_job"):
                self.calls.append((key, data))
                return {"response": {"ok": True, "messages": ["red roof"], "stop": False}}
        return super().__call__(payload, timeout)


class GameBase(Base):
    def setUp(self):
        super().setUp()
        self.core.__class__ = JobCore
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "minecraft").mkdir()
        (root / "minecraft" / "settings.json").write_text(json.dumps({
            "enabled": True, "saved_at": 1, "people": FAMILY}))
        (root / "personality.json").write_text(json.dumps({"name": "Juniper"}))
        p = patch.object(m, "MC_SHARED_DIR", str(root))
        p.start()
        self.addCleanup(p.stop)

    def channel(self, word):
        p = patch.dict(os.environ, {"BRAIN_CHANNEL": word})
        p.start()
        self.addCleanup(p.stop)

    def sent(self, service, domain="bruh_minecraft"):
        return [d for k, d in self.core.calls if k == (domain, service)]


class TestEditOnTheGameChannel(GameBase):
    def setUp(self):
        super().setUp()
        self.channel("minecraft")

    def test_edit_with_shapes_and_a_job_reaches_the_add_on_and_the_job(self):
        shapes = [{"kind": "line", "block": "oak_log", "from": [0, 64, 0], "to": [0, 72, 0],
                   "radius": 1.5, "radius_end": 0.5},
                  {"kind": "blob", "block": "oak_leaves", "center": [0, 73, 0], "radius": 4,
                   "density": 0.7, "seed": 3}]
        got = m.minecraft_world("edit", "a tree", shapes=shapes, job="ja1b2c3")
        self.assertTrue(got["done"], got)
        data = self.sent("companion_edit")[-1]
        self.assertEqual((data["shapes"], data["job"]), (shapes, "ja1b2c3"))
        self.assertEqual(self.sent("minecraft_job", "brain")[-1],
                         {"action": "edit", "job": "ja1b2c3", "edit": "e-77"})

    def test_an_edit_without_a_job_records_nothing_on_one(self):
        m.minecraft_world("edit", "a bed", blocks=[{"x": 0, "y": 64, "z": 0,
                                                    "block": "red_bed"}])
        self.assertEqual(self.sent("minecraft_job", "brain"), [])
        self.assertNotIn("job", self.sent("companion_edit")[-1])

    def test_the_chokepoint_lets_the_games_services_through_and_nothing_else(self):
        for service in ("companion_edit", "atlas", "room", "label_place"):
            self.assertIsNone(m._minecraft_chat_refusal("bruh_minecraft", service), service)
        self.assertIsNone(m._minecraft_chat_refusal("brain", "minecraft_job"))
        for domain, service in (("bruh_minecraft", "rcon_command"), ("light", "turn_on"),
                                ("brain", "run_task"), ("bruh_minecraft", "give")):
            self.assertIn("error", m._minecraft_chat_refusal(domain, service))

    def test_atlas_room_and_label_are_one_service_each(self):
        got = m.minecraft_world("atlas", "", player="Dad")
        self.assertEqual(got["here"]["room_name"],          # the family's words
                         {"untrusted": True, "text": "the kitchen"})
        self.assertEqual(self.sent("atlas")[-1], {"player": "DadCraft42"})
        m.minecraft_world("atlas", "Ben's room")
        self.assertEqual(self.sent("atlas")[-1], {"query": "Ben's room"})
        got = m.minecraft_world("room", "r7")
        self.assertEqual(self.sent("room")[-1], {"room": "r7"})
        self.assertEqual(got["room"]["name"]["text"], "the kitchen")
        m.minecraft_world("room", "", player="Steve")
        self.assertEqual(self.sent("room")[-1], {"player": "Steve"})
        m.minecraft_world("label", "Ben's room", options={"room": "r7"}, player="Dad")
        self.assertEqual(self.sent("label_place")[-1],
                         {"room": "r7", "name": "Ben's room", "by": "Dad"})

    def test_the_tool_offers_them(self):
        tool = next(t for t in m.TOOLS if t["name"] == "minecraft_world")
        props = tool["inputSchema"]["properties"]
        for action in ("edit", "atlas", "room", "label"):
            self.assertIn(action, props["action"]["enum"])
        self.assertIn("shapes", props)
        self.assertIn("job", props)
        self.assertNotIn("never on a guarded game request", tool["description"])


class TestTheJobTool(GameBase):
    def test_it_calls_the_faculty_and_answers_what_it_said(self):
        self.channel("minecraft")
        got = m.minecraft_job("progress", job="ja1b2c3", text="walls up", percent=40)
        self.assertTrue(got["ok"])
        self.assertEqual(self.sent("minecraft_job", "brain")[-1],
                         {"action": "progress", "job": "ja1b2c3", "text": "walls up",
                          "percent": 40})
        got = m.minecraft_job("inbox", job="ja1b2c3")
        self.assertEqual(got["messages"][0]["text"], "red roof")     # tagged untrusted
        self.assertTrue(got["messages"][0]["untrusted"])
        m.minecraft_job("list")
        self.assertEqual(self.sent("minecraft_job", "brain")[-1], {"action": "list"})
        self.assertIn("error", m.minecraft_job("dance"))

    def test_voice_never_has_it(self):
        self.voice()
        self.assertIn("Voice assistant", m.minecraft_job("list")["error"])
        self.assertIn("minecraft_job", m.VOICE_HIDDEN_TOOLS)
        self.assertNotIn("minecraft_job", [t["name"] for t in m.tools_for_channel()])
        self.assertIn("minecraft_job", m.CONTRACT_REFUSED_TOOLS)

    def test_voice_still_may_not_edit(self):
        self.voice()
        self.assertIn("Voice assistant", m.minecraft_world("edit", "x")["error"])


class TestTheListsHoldIt(unittest.TestCase):
    def test_every_game_scope_has_the_job_tool_and_the_game_tool(self):
        self.assertIn(MCP + "minecraft_job", engine.MINECRAFT_CHAT_TOOLS)
        self.assertIn(MCP + "minecraft_job", engine.ANALYST_DENIED)
        for mode in ("minecraft", "minecraft_trusted"):
            rc, flags = flags_for(mode)
            self.assertEqual(rc, 0, flags)
            allow = dict(zip(flags[::2], flags[1::2]))["--allowedTools"].split(",")
            for tool in ("minecraft_job", "minecraft_world"):
                self.assertIn(MCP + tool, allow, (mode, tool))

    def test_the_words_only_scope_is_gone_everywhere(self):
        rc, flags = flags_for("minecraft_talk")
        self.assertNotEqual(rc, 0)
        self.assertNotIn("minecraft_talk", LISTENER.read_text(encoding="utf-8"))
        for rel in ("brain/panel/gate.py", "brain/panel/engine.py",
                    "brain/custom_components/brain/minecraft.py",
                    "brain/ha-mcp-server/ha_mcp_server.py"):
            self.assertNotIn("minecraft_talk", (REPO / rel).read_text(encoding="utf-8"), rel)


class TestTheGateOnTheGameChannel(GateCase):
    def test_edit_atlas_room_label_and_the_job_tool_pass_without_a_card(self):
        for tool, args in ((PFX + "minecraft_world", {"action": "edit", "value": "a tree"}),
                           (PFX + "minecraft_world", {"action": "atlas", "value": ""}),
                           (PFX + "minecraft_world", {"action": "room", "value": "r7"}),
                           (PFX + "minecraft_world", {"action": "label", "value": "x"}),
                           (PFX + "minecraft_job", {"action": "progress", "job": "ja1b2c3"})):
            out = self.ask(tool, args, ["build a tree"], channel="minecraft")
            self.assertEqual((out["decision"], out["path"]), ("allow", "minecraft_chat"),
                             (tool, args))
        self.assertEqual(self.model_calls, [])

    def test_rename_and_the_house_are_still_refused(self):
        for tool, args in ((PFX + "minecraft_world", {"action": "rename", "value": "x"}),
                           (PFX + "call_service", {"domain": "light", "service": "turn_on",
                                                   "data": {"entity_id": "light.k1"}})):
            out = self.ask(tool, args, ["please"], channel="minecraft")
            self.assertEqual(out["decision"], "deny", tool)


if __name__ == "__main__":
    unittest.main()
