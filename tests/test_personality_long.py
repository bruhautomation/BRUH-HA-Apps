"""A long persona (16,000+ characters) is kept whole everywhere it passes.

The persona was capped at 4000 in brAIn's store and again in Morph's
websocket, so a long one migrated from the old Morph app was cut mid-sentence
with a trailing ellipsis, and Settings showed it cut. One ceiling now, and the
two modules (which cannot import each other) are held equal by a test.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import personality  # noqa: E402
from test_morph_usage_and_names import _Connection, _Hass, _load_websocket  # noqa: E402

SENTENCE = "She greets everyone by name and never repeats herself twice. "
LONG = (SENTENCE * 300)[:16_000].rstrip() + " The end."
assert len(LONG) >= 16_000


class TestLongPersona(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        (Path(self.tmp.name) / ".brain").mkdir()
        self.file = str(Path(self.tmp.name) / ".brain" / "personality.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalise_and_save_keep_it_whole(self):
        self.assertEqual(personality.normalise({"persona": LONG})["persona"], LONG)
        personality.save("Juniper", LONG, path=self.file)
        self.assertEqual(personality.load(self.file)["persona"], LONG)
        self.assertEqual(personality.save_refusal("Juniper", LONG, path=self.file), "")

    def test_it_still_has_a_ceiling(self):
        self.assertTrue(personality.save_refusal("x", "y" * (personality.PERSONA_MAX + 1)))

    def test_migrate_and_repair_keep_it_whole(self):
        src = Path(self.tmp.name) / "personality.js"
        src.write_text('export const PERSONA = { name: "Wren", description: '
                       + json.dumps(LONG) + " };\nexport const GROWTH = [];\n", encoding="utf-8")
        self.assertIn("moved", personality.migrate_from_morph(str(src), self.file))
        self.assertIn(LONG, personality.load(self.file)["persona"])
        self.assertNotIn("…", personality.load(self.file)["persona"])
        # a poorer earlier import is repaired to the whole text, not a cut one
        personality.save("Wren", SENTENCE.strip(), path=self.file)
        personality.repair_from_morph(str(src), self.file)
        self.assertNotIn("…", personality.load(self.file)["persona"])

    def test_the_prompt_carries_it_whole(self):
        block = personality.prompt_block({"name": "J", "persona": LONG, "growth": []})
        self.assertIn(LONG, block)

    def test_morphs_websocket_shows_it_whole(self):
        ws = _load_websocket()
        brain = Path(self.tmp.name) / ".brain"
        (brain / "personality.json").write_text(
            json.dumps({"name": "J", "persona": LONG, "growth": []}), encoding="utf-8")
        conn = _Connection()
        with unittest.mock.patch.object(ws, "BRAIN_SHARED", brain):
            asyncio.run(ws.ws_personality(_Hass(), conn, {"id": 1, "type": "morph/personality"}))
        self.assertEqual(conn.results[-1][1]["personality"]["persona"], LONG)

    def test_the_two_ceilings_are_one_number_and_the_textarea_agrees(self):
        ws = _load_websocket()
        self.assertEqual(ws.PERSONA_MAX, personality.PERSONA_MAX)
        html = (ROOT / "brain" / "panel" / "index.html").read_text(encoding="utf-8")
        line = next(ln for ln in html.splitlines() if 'id="persText"' in ln)
        self.assertIn(f'maxlength="{personality.PERSONA_MAX}"', line)


if __name__ == "__main__":
    unittest.main()
