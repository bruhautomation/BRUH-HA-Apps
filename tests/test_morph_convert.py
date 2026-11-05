"""Morph's own dashboard as a Home Assistant dashboard (brain/morph/service/convert.py).

A floor is a tab of Home Assistant's own sections view (so HA's editor,
sizes and sections all work on it) with the room rail switched on as the
view's `morph:` options, a room a section with its name as a heading (and
its title-row switch on that heading), a group label a smaller heading,
every Morph card kind its Home Assistant card with the same entity, name,
icon, colour, buttons and opened card as keys HA's editor edits and a width
the house set as `grid_options`, a hosted Lovelace card copied as it was;
and what cannot come along is said, never dropped in silence. A 5.0
dashboard's Morph views become sections views once (`migrate`).
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
                           {"entity": "light.countertop", "span": 2, "icon": "mdi:led-strip",
                            "options": {"detail": {"type": "history-graph", "entities": ["light.countertop"]}}}]},
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

    def test_floors_are_home_assistants_sections_views_in_morphs_theme(self):
        views = self.cfg["views"]
        self.assertEqual([v["title"] for v in views], ["First floor", "Yard"])
        self.assertEqual([v["path"] for v in views], ["first-floor", "yard"])
        self.assertTrue(all(v["type"] == "sections" for v in views))
        self.assertTrue(all(v["morph"] == {"rail": True, "order": False, "fold": False} for v in views))
        self.assertTrue(all(v["theme"] == "Morph Medium" for v in views))
        self.assertEqual(self.cfg["title"], "Home")

    def test_a_light_or_dark_dashboard_keeps_its_look_whatever_a_profile_says(self):
        for theme, want in (("dark", "Morph Dark"), ("light", "Morph Light"), ("auto", "Morph"), ("medium", "Morph Medium")):
            dash, _ = self.env.store.normalize({**DASH, "theme": theme})
            cfg, _ = self.env.convert.to_lovelace(dash)
            self.assertEqual(cfg["views"][0]["theme"], want, theme)

    def test_the_fixed_themes_are_the_two_modes_of_morph_exactly(self):
        import yaml
        from pathlib import Path
        d = Path(__file__).resolve().parent.parent / "brain/morph/defaults/themes"
        both = yaml.safe_load((d / "morph.yaml").read_text())["Morph"]
        fixed = yaml.safe_load((d / "morph-fixed.yaml").read_text())
        base = {k: v for k, v in both.items() if k != "modes"}
        self.assertEqual(fixed["Morph Light"], {**base, **both["modes"]["light"]})
        self.assertEqual(fixed["Morph Dark"], {**base, **both["modes"]["dark"]})

    def test_a_room_is_a_section_with_its_cards_as_home_assistant_cards(self):
        top, kitchen = self.cfg["views"][0]["sections"]
        self.assertEqual([c["type"] for c in top["cards"]], ["custom:morph-ask-card", "custom:morph-scenes-card"])
        self.assertEqual(top["cards"][1]["entities"], ["scene.evening"])
        cards = kitchen["cards"]
        # The title-row switch rides on the room's heading, as Morph drew it.
        self.assertEqual(cards[0], {"type": "heading", "heading": "Kitchen", "entities": [
            {"entity": "input_boolean.pause", "tap_action": {"action": "toggle"}}]})
        self.assertEqual(cards[1], {"type": "custom:morph-cases-card", "area": "kitchen"})
        self.assertEqual(cards[2], {"type": "custom:morph-light-group-card", "entity": "light.kitchen_cans", "name": "Cans"})
        # Every key a plain one HA's visual editor edits; the house's width
        # is HA's grid size.
        self.assertEqual(cards[3], {"type": "custom:morph-light-card", "entity": "light.countertop", "icon": "mdi:led-strip",
                                    "detail": {"type": "history-graph", "entities": ["light.countertop"]},
                                    "grid_options": {"columns": 6}})
        self.assertEqual(cards[4], {"type": "heading", "heading": "Comfort · summer", "heading_style": "subtitle"})
        self.assertEqual(cards[5], {"type": "custom:morph-climate-card", "entity": "climate.downstairs", "actions": ["script.boost"]})
        self.assertEqual(cards[6], {"type": "custom:mushroom-chips-card", "chips": [{"type": "weather"}]})
        self.assertFalse([c for c in cards if "options" in c])

    def test_every_kind_it_writes_is_one_morph_cards_defines(self):
        from pathlib import Path
        js = (Path(__file__).resolve().parent.parent / "brain/custom_components/brain/morph/frontend/morph-cards.js").read_text()
        for kind in self.env.convert.KINDS:
            self.assertIn(f"  {kind}: {{ name:", js, kind)

    def test_what_did_not_come_along_is_said(self):
        text = " ".join(self.report)
        self.assertIn("Attic: hidden in Morph", text)
        self.assertIn("Coming up", text)
        yard = self.cfg["views"][1]["sections"][0]["cards"]
        self.assertEqual(yard[1], {"type": "custom:morph-note-card", "text": "Gate code 1234"})
        self.assertEqual(yard[2], {"type": "custom:morph-list-card", "entities": ["binary_sensor.gate"]})

    def test_a_kind_from_the_houses_own_code_is_its_own_card_not_an_entity_strip(self):
        # store.normalize keeps a kind an ACTIVE copy of cards.js adds
        # (morphcode.card_types), which is the form handed here.
        dash = {"floors": [{"title": "F", "sections": [{"title": "R", "groups": [{"cards": [
            {"type": "pool", "entity": "sensor.pool", "id": "c1"}]}]}]}]}
        every = lambda cfg: [c for sec in cfg["views"][0]["sections"] for c in sec["cards"]]  # noqa: E731
        cfg, report = self.env.convert.to_lovelace(dash, house=("pool",))
        self.assertIn({"type": "custom:morph-pool-card", "entity": "sensor.pool"}, every(cfg))
        self.assertFalse([r for r in report if "pool" in r])
        cfg, report = self.env.convert.to_lovelace(dash)
        self.assertIn({"type": "custom:morph-entity-card", "entity": "sensor.pool"}, every(cfg))

    def test_a_morph_view_becomes_a_sections_view_once_keeping_its_switches(self):
        old = {"title": "Home", "views": [
            {"title": "A", "type": "custom:morph-view", "sections": [{"type": "grid", "cards": []}]},
            {"title": "B", "type": "custom:morph-view", "morph": {"order": True}, "sections": []},
            {"title": "C", "type": "masonry", "cards": []}]}
        new, n = self.env.convert.migrate(old)
        self.assertEqual(n, 2)
        self.assertEqual([v["type"] for v in new["views"]], ["sections", "sections", "masonry"])
        self.assertEqual(new["views"][0]["morph"], {"rail": True, "order": False, "fold": False})
        self.assertEqual(new["views"][1]["morph"], {"rail": True, "order": True, "fold": False})
        self.assertEqual(new["views"][0]["sections"], old["views"][0]["sections"])
        self.assertEqual(self.env.convert.migrate(new), (new, 0))

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
