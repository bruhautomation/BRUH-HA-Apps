"""Morph shows brAIn's personality and keeps none of its own.

A household's personality used to live in a copy of a frontend module under
/config/morph/frontend/personality.js, read only by that copy. It is brAIn's
now, in /config/.brain/personality.json, and Morph's Settings reads it there
through `morph/personality`: whatever brAIn saved is what Morph shows the next
time Settings opens, and a house without brAIn is told where it lives.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from test_morph_usage_and_names import _Connection, _Hass, _load_websocket

INTEGRATION = Path(__file__).resolve().parent.parent / "brain" / "custom_components" / "brain" / "morph"
FRONTEND = INTEGRATION / "frontend"
PANEL_JS = FRONTEND / "morph-panel.js"

SAVED = {"name": "Juniper", "persona": "Warm, brief, a little dry.\nNever says “as an AI”.",
         "growth": [{"date": "2026-09-02", "at": 1788300000, "text": "Learned the dog is called Biscuit."},
                    {"date": "2026-08-01", "text": "Stopped saying good morning at noon."}],
         "updated_at": 1788300000}


class TestTheCommandReadsBrainsFile(unittest.TestCase):

    def setUp(self):
        self.ws = _load_websocket()
        self.tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self.tmp.name) / ".brain"

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self):
        conn = _Connection()
        with unittest.mock.patch.object(self.ws, "BRAIN_SHARED", self.brain):
            asyncio.run(self.ws.ws_personality(_Hass(), conn, {"id": 3, "type": "morph/personality"}))
        return conn.results[-1][1]

    def write(self, data):
        self.brain.mkdir(parents=True, exist_ok=True)
        text = data if isinstance(data, str) else json.dumps(data)
        (self.brain / "personality.json").write_text(text, encoding="utf-8")

    def test_what_brain_saved_is_what_morph_is_handed(self):
        self.write(SAVED)
        got = self.ask()
        self.assertTrue(got["brain"])
        p = got["personality"]
        self.assertEqual("Juniper", p["name"])
        self.assertEqual(SAVED["persona"], p["persona"])
        self.assertEqual(["2026-08-01", "2026-09-02"], [g["date"] for g in p["growth"]])
        self.assertEqual(1788300000, p["updated_at"])

    def test_an_edit_in_brain_is_read_the_next_time(self):
        self.write(SAVED)
        self.ask()
        self.write({**SAVED, "name": "Fern", "persona": "Plain."})
        p = self.ask()["personality"]
        self.assertEqual(("Fern", "Plain."), (p["name"], p["persona"]))

    def test_no_file_is_nothing_and_says_whether_brain_is_there(self):
        self.assertEqual({"brain": False, "personality": None}, self.ask())
        self.brain.mkdir(parents=True)
        self.assertEqual({"brain": True, "personality": None}, self.ask())

    def test_a_file_that_sets_nothing_is_nothing(self):
        self.write({"name": " ", "persona": "", "growth": []})
        self.assertIsNone(self.ask()["personality"])

    def test_a_broken_or_strange_file_is_nothing_never_an_error(self):
        for bad in ("{not json", "[1, 2]", json.dumps({"name": "x" * 10, "persona": "y"}) + " " * 300_000):
            self.write(bad)
            self.assertIsNone(self.ask()["personality"], bad[:20])

    def test_every_field_is_capped_and_growth_keeps_only_entries_with_words(self):
        self.write({"name": "N" * 500, "persona": "P" * 9000,
                    "growth": [{"text": "G" * 900, "date": "2026-01-01"}, {"text": ""}, 7, "plain words"]
                    + [{"text": f"entry {i}"} for i in range(300)]})
        p = self.ask()["personality"]
        self.assertLessEqual(len(p["name"]), self.ws.PERSONA_NAME_MAX)
        self.assertLessEqual(len(p["persona"]), self.ws.PERSONA_MAX)
        self.assertLessEqual(len(p["growth"]), self.ws.PERSONA_GROWTH_MAX)
        self.assertTrue(all(g["text"] and len(g["text"]) <= self.ws.PERSONA_GROWTH_TEXT_MAX for g in p["growth"]))

    def test_it_is_admin_gated_and_registered(self):
        src = (INTEGRATION / "websocket.py").read_text()
        block = src[src.index('"morph/personality"') - 200: src.index("async def ws_personality")]
        self.assertIn("@websocket_api.require_admin", block)
        reg = src[src.index("def async_register"):]
        self.assertIn("ws_personality", reg)


class TestMorphKeepsNoPersonalityOfItsOwn(unittest.TestCase):

    def test_the_name_is_read_through_the_command_and_the_switches(self):
        # Morph's Settings page went into brAIn's ⚙ in 4.0; Morph still
        # reads the name, off brAIn's switches first (`features.name`).
        js = PANEL_JS.read_text()
        self.assertIn("type: 'morph/personality'", js)
        self.assertIn("loadPersona", js)
        self.assertIn("f.name", js)
        self.assertNotIn("<h2>Personality</h2>", js)

    def test_no_shipped_module_holds_or_imports_a_personality(self):
        self.assertFalse((FRONTEND / "personality.js").exists())
        for f in FRONTEND.glob("*.js"):
            self.assertNotRegex(f.read_text(), r"personality\.js(?!on)", f.name)
            self.assertNotRegex(f.read_text(), r"\b(PERSONA|GROWTH)\s*=", f.name)

    def test_switched_off_it_is_not_handed_on(self):
        ws = _load_websocket()
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / ".brain"
            brain.mkdir()
            (brain / "personality.json").write_text(json.dumps(SAVED), encoding="utf-8")
            (brain / "features.json").write_text(json.dumps({"personality": False}), encoding="utf-8")
            conn = _Connection()
            with unittest.mock.patch.object(ws, "BRAIN_SHARED", brain), \
                    unittest.mock.patch.object(ws, "FEATURES", brain / "features.json"):
                asyncio.run(ws.ws_personality(_Hass(), conn, {"id": 3, "type": "morph/personality"}))
            self.assertIsNone(conn.results[-1][1]["personality"])


if __name__ == "__main__":
    unittest.main()
