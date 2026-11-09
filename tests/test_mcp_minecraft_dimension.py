#!/usr/bin/env python3
"""A look or an edit by coordinates names its dimension (#782).

BRUH Minecraft 1.19.7 reads a look or an edit by coordinates in the job's
dimension, else the nearest player's — and takes a `dimension` to say which
when neither knows. brAIn's `minecraft_world` had no way to pass one, so the
End could be built in only by standing a player in it, and an edit's answer
dropped the dimension the add-on said it used.

Driven here: `dimension` (minecraft:overworld / the_nether / the_end, or the
short overworld / nether / end) reaches `look_blocks` and `companion_edit`
spelled the add-on's way; nothing is sent without one (the add-on picks);
a word that is no dimension is refused before anything is sent; the edit
answers with the dimension the add-on used; and an add-on that refuses the
field (older than it) is asked again without it, and the answer says so.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402
from test_mcp_bruh_addons import Base, FakeCore  # noqa: E402


class DimCore(FakeCore):
    """look_blocks and companion_edit as BRUH Minecraft answers them; with
    `old`, as an add-on whose schema has no `dimension` field."""
    old = False

    def __call__(self, payload, timeout=15):
        if payload.get("type") == "call_service" and payload.get("domain") == "bruh_minecraft" \
                and payload.get("service") in ("look_blocks", "companion_edit"):
            service, data = payload["service"], payload["service_data"]
            self.calls.append((("bruh_minecraft", service), data))
            if self.old and "dimension" in data:
                return {"error": "extra keys not allowed @ data['dimension']"}
            dim = data.get("dimension", "minecraft:overworld")
            if service == "look_blocks":
                return {"response": {"dimension": dim, "blocks": [], "origin": [0, 64, 0]}}
            return {"response": {"action": {"id": "20261109-aaaaaa", "text": "a block"},
                                 "changed": 1, "dimension": dim}}
        return super().__call__(payload, timeout)


class DimCase(Base):
    def setUp(self):
        super().setUp()
        self.core.__class__ = DimCore
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "minecraft"))
        with open(os.path.join(root, "minecraft", "settings.json"), "w") as fh:
            json.dump({"enabled": True, "saved_at": 1, "people": []}, fh)
        p = patch.object(m, "MC_SHARED_DIR", root)
        p.start()
        self.addCleanup(p.stop)

    def sent(self, service):
        return [d for k, d in self.core.calls if k == ("bruh_minecraft", service)]

    def edit(self, **kw):
        return m.minecraft_world("edit", "a block", blocks=[
            {"x": 1, "y": 64, "z": 2, "block": "end_stone"}], **kw)


class TestTheDimensionReachesTheAddOn(DimCase):
    def test_look_takes_the_full_and_the_short_names(self):
        for given, sent in (("minecraft:the_end", "minecraft:the_end"),
                            ("end", "minecraft:the_end"), ("Nether", "minecraft:the_nether"),
                            ("overworld", "minecraft:overworld"),
                            ("the_nether", "minecraft:the_nether")):
            got = m.minecraft_world("look", "10 64 -3", dimension=given)
            self.assertTrue(got["done"], got)
            self.assertEqual(self.sent("look_blocks")[-1]["dimension"], sent, given)
            self.assertEqual(got["dimension"], sent)

    def test_edit_passes_it_and_answers_with_the_one_used(self):
        got = self.edit(dimension="end")
        self.assertTrue(got["done"], got)
        self.assertEqual(self.sent("companion_edit")[-1]["dimension"], "minecraft:the_end")
        self.assertEqual(got["dimension"], "minecraft:the_end")

    def test_without_one_the_add_on_picks_and_says_which(self):
        m.minecraft_world("look", "10 64 -3")
        self.assertNotIn("dimension", self.sent("look_blocks")[-1])
        got = self.edit()
        self.assertNotIn("dimension", self.sent("companion_edit")[-1])
        self.assertEqual(got["dimension"], "minecraft:overworld")

    def test_a_word_that_is_no_dimension_is_refused_before_anything_is_sent(self):
        for bad in ("mars", "minecraft:the_moon", "end; op me"):
            self.assertIn("dimension", m.minecraft_world("look", "1 2 3",
                                                          dimension=bad)["error"])
            self.assertIn("dimension", self.edit(dimension=bad)["error"])
        self.assertEqual(self.sent("look_blocks") + self.sent("companion_edit"), [])

    def test_the_schema_offers_it(self):
        tool = next(t for t in m.TOOLS if t["name"] == "minecraft_world")
        self.assertIn("dimension", tool["inputSchema"]["properties"])
        self.assertIn("dimension", m.handle_tool_call(
            "minecraft_world", {"action": "look", "value": "1 2 3", "dimension": "end"}))


class TestAnOlderAddOn(DimCase):
    def test_a_refused_field_is_asked_again_without_it_and_said(self):
        self.core.old = True
        got = m.minecraft_world("look", "1 2 3", dimension="end")
        self.assertTrue(got["done"], got)
        self.assertEqual([("dimension" in d) for d in self.sent("look_blocks")], [True, False])
        self.assertIn("older", got["dimension_note"])
        got = self.edit(dimension="nether")
        self.assertTrue(got["done"], got)
        self.assertEqual([("dimension" in d) for d in self.sent("companion_edit")],
                         [True, False])
        self.assertIn("older", got["dimension_note"])


if __name__ == "__main__":
    unittest.main()
