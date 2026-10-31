#!/usr/bin/env python3
"""The 1.17.7 companion card and its routes are gone (#592/#593).

The add-on's Dashboard had a card named after one house's persona, with a
family list, a bedtime switch and daily limits, behind `/api/<old name>`
routes and `<old name>_*` services. Those decisions are brAIn's now (⚙ ›
Minecraft), and the card is the Companion's (tests/
test_minecraft_companion_card.py). These hold that nothing of the old one
is left for a page, a bookmark or an automation to reach.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "bruh-minecraft-server"
PANEL = ADDON / "panel"
OLD = "ves" + "per"          # spelled apart: this file is not the add-on, but greps meet it


class TestTheOldCardIsGone(unittest.TestCase):
    def test_no_old_ids_classes_or_routes_on_the_page(self):
        for name in ("index.html", "app.js", "style.css"):
            text = (PANEL / name).read_text()
            self.assertNotRegex(text, re.compile(OLD, re.I), name)

    def test_the_old_routes_and_services_are_not_registered(self):
        server = (PANEL / "server.py").read_text()
        self.assertNotIn(f"/api/{OLD}", server)
        services = json.loads((ADDON / "custom_components" / "bruh_minecraft" /
                               "strings.json").read_text())["services"]
        self.assertEqual([s for s in services if OLD in s], [])
        for gone in ("set_family", f"{OLD}_engine", f"get_{OLD}"):
            self.assertNotIn(gone, services)
        bridge = (ADDON / "integrations" / "ha-bridge.py").read_text()
        self.assertNotRegex(bridge, re.compile(OLD, re.I))

    def test_the_family_and_limits_moved_to_brain(self):
        html = (REPO / "brain" / "panel" / "index.html").read_text()
        self.assertIn('id="setsecMinecraft"', html)
        self.assertIn("⚙ › Minecraft", (PANEL / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
