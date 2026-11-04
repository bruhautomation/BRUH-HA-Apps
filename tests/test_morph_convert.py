"""Morph's own dashboard as a Home Assistant dashboard (brain/morph/service/convert.py).

A floor is a tab laid out by Morph's view, a room a section with its name as
a heading, a group label a smaller heading, every Morph card kind its
Home Assistant card with the same entity, name, colour and options, a
hosted Lovelace card copied as it was; and what cannot come along is said,
never dropped in silence.
"""
from __future__ import annotations

import unittest

from morph_env import MorphEnv

DASH = {
    "title": "Home", "theme": "medium", "scenes": ["scene.evening"],
    "floors": [
        {"title": "First floor", "sections": [
            {"title": "Kitchen", "area": "kitchen", "groups": [
                {"cards": [{"type": "light_group", "entity": "light.kitchen_cans", "name": "Cans"},
                           {"entity": "light.countertop"}]},
                {"label": "Comfort", "note": "summer", "cards": [
                    {"type": "climate", "entity": "climate.downstairs", "options": {"actions": ["script.boost"]}},
                    {"type": "switch", "entity": "input_boolean.pause", "options": {"header": True}}]},
                {"cards": [{"type": "custom:mushroom-chips-card", "chips": [{"type": "weather"}]}]}]},
            {"title": "Attic", "hidden": True, "cards": [{"entity": "sensor.attic"}]}]},
        {"title": "Yard", "sections": [
            {"title": "Porch", "cards": [{"type": "note", "text": "Gate code 1234"},
                                        {"type": "list", "entities": ["binary_sensor.gate"]}]}]},
    ],
}


class Convert(unittest.TestCase):
    def setUp(self):
        self.env = MorphEnv().__enter__()
        self.addCleanup(self.env.__exit__, None, None, None)
        dash, problems = self.env.store.normalize(DASH)
        self.assertEqual(problems, [])
        self.cfg, self.report = self.env.convert.to_lovelace(dash)

    def test_floors_are_tabs_laid_out_by_morphs_view_in_morphs_theme(self):
        views = self.cfg["views"]
        self.assertEqual([v["title"] for v in views], ["First floor", "Yard"])
        self.assertEqual([v["path"] for v in views], ["first-floor", "yard"])
        self.assertTrue(all(v["type"] == "custom:morph-view" for v in views))
        self.assertTrue(all(v["theme"] == "Morph Medium" for v in views))
        self.assertEqual(self.cfg["title"], "Home")

    def test_a_room_is_a_section_with_its_cards_as_home_assistant_cards(self):
        top, kitchen = self.cfg["views"][0]["sections"]
        self.assertEqual([c["type"] for c in top["cards"]], ["custom:morph-ask-card", "custom:morph-scenes-card"])
        self.assertEqual(top["cards"][1]["entities"], ["scene.evening"])
        cards = kitchen["cards"]
        self.assertEqual(cards[0], {"type": "heading", "heading": "Kitchen"})
        self.assertEqual(cards[1], {"type": "custom:morph-cases-card", "area": "kitchen"})
        self.assertEqual(cards[2], {"type": "custom:morph-light-group-card", "entity": "light.kitchen_cans", "name": "Cans"})
        self.assertEqual(cards[3], {"type": "custom:morph-light-card", "entity": "light.countertop"})
        self.assertEqual(cards[4], {"type": "heading", "heading": "Comfort · summer", "heading_style": "subtitle"})
        self.assertEqual(cards[5], {"type": "custom:morph-climate-card", "entity": "climate.downstairs", "actions": ["script.boost"]})
        self.assertEqual(cards[6], {"type": "custom:morph-switch-card", "entity": "input_boolean.pause"})
        self.assertEqual(cards[7], {"type": "custom:mushroom-chips-card", "chips": [{"type": "weather"}]})

    def test_every_kind_it_writes_is_one_morph_cards_defines(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parent.parent / "brain/custom_components/brain/morph/frontend/morph-cards.js").read_text()
        for kind in self.env.convert.KINDS:
            self.assertIn(f"  {kind}: {{ name:", js, kind)

    def test_what_did_not_come_along_is_said(self):
        text = " ".join(self.report)
        self.assertIn("Attic: hidden in Morph", text)
        self.assertIn("title row is an ordinary switch card", text)
        self.assertIn("Coming up", text)
        yard = self.cfg["views"][1]["sections"][0]["cards"]
        self.assertEqual(yard[1], {"type": "custom:morph-note-card", "text": "Gate code 1234"})
        self.assertEqual(yard[2], {"type": "custom:morph-list-card", "entities": ["binary_sensor.gate"]})

    def test_the_service_answers_convert_and_refuses_an_empty_dashboard(self):
        import asyncio
        import importlib
        import sys
        sys.modules.pop("morphd", None)
        morphd = importlib.import_module("morphd")
        self.env.store.write(DASH)
        out = asyncio.run(morphd.handle("convert", {}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["url_path"], "morph-home")
        self.assertEqual(out["config"]["views"][0]["title"], "First floor")
        self.env.store.write({"floors": []})
        self.assertFalse(asyncio.run(morphd.handle("convert", {}))["ok"])
        sys.modules.pop("morphd", None)


if __name__ == "__main__":
    unittest.main()
