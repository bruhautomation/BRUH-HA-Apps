#!/usr/bin/env python3
"""`edit_dashboard`: brAIn changes part of any dashboard by path.

The fetch-edit-save round trip (get_dashboard, then brain.update_dashboard
with the whole config) works and stays the one write path; what it cost
was a whole dashboard re-sent to move one card or switch one key, and a
model that re-types a 40-card dashboard to change a width is a model that
drops a card on the way. These drive the real tool against a stand-in for
Home Assistant's socket and services: ops apply in order or not at all,
each failure names the op, the save goes through brain.update_dashboard
(backups, rails) and nothing else, and dry_run saves nothing.
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))

CFG = {"title": "Home", "views": [
    {"title": "Home", "path": "home", "type": "sections", "sections": [
        {"type": "grid", "cards": [{"type": "heading", "heading": "Kitchen"},
                                   {"type": "custom:morph-light-card", "entity": "light.kitchen"},
                                   {"type": "tile", "entity": "light.pantry"}]},
        {"type": "grid", "cards": [{"type": "heading", "heading": "Hall"}]}]}]}


class EditDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mcp = importlib.import_module("ha_mcp_server")

    def setUp(self):
        self.saved = []
        self.configs = {None: CFG, "spare": None}
        real_ws, real_call = self.mcp._ws_command, self.mcp.call_service
        self.addCleanup(setattr, self.mcp, "_ws_command", real_ws)
        self.addCleanup(setattr, self.mcp, "call_service", real_call)

        def ws(message, timeout=None):
            got = self.configs.get(message.get("url_path"), "missing")
            return {"error": "config_not_found"} if got in (None, "missing") else got

        def call(domain, service, data=None, return_response=False):
            self.saved.append((domain, service, data))
            return {"response": {"url_path": data["url_path"], "views": len(data["config"]["views"])}}

        self.mcp._ws_command = ws
        self.mcp.call_service = call

    def cards(self, cfg, s=0):
        return cfg["views"][0]["sections"][s]["cards"]

    def test_a_card_is_resized_moved_and_added_in_one_save(self):
        got = self.mcp.edit_dashboard(ops=[
            {"op": "set", "path": "views/0/sections/0/cards/1/grid_options", "value": {"columns": 12, "rows": 2}},
            {"op": "move", "path": "views/0/sections/0/cards/2", "to": "views/0/sections/1/cards/-"},
            {"op": "add", "path": ["views", 0, "sections", 1, "cards", 1], "value": {"type": "tile", "entity": "lock.front"}},
            {"op": "set", "path": "views/0/morph", "value": {"rail": True}},
        ])
        self.assertNotIn("error", got)
        self.assertEqual(len(self.saved), 1)
        domain, service, data = self.saved[0]
        self.assertEqual((domain, service, data["url_path"]), ("brain", "update_dashboard", "default"))
        new = data["config"]
        self.assertEqual(self.cards(new)[1]["grid_options"], {"columns": 12, "rows": 2})
        self.assertEqual([c.get("entity") for c in self.cards(new, 1)], [None, "lock.front", "light.pantry"])
        self.assertEqual(len(self.cards(new)), 2)
        self.assertEqual(new["views"][0]["morph"], {"rail": True})
        self.assertEqual(len(got["changed"]), 4)
        # The config it was handed is untouched: ops work on a copy.
        self.assertEqual(len(self.cards(CFG)), 3)

    def test_one_bad_op_saves_nothing_and_names_itself(self):
        got = self.mcp.edit_dashboard(ops=[
            {"op": "remove", "path": "views/0/sections/0/cards/1"},
            {"op": "set", "path": "views/0/sections/7/cards/0", "value": {}},
        ])
        self.assertIn("op 2", got["error"])
        self.assertIn("sections/7", got["error"])
        self.assertEqual(self.saved, [])

    def test_dry_run_says_what_and_saves_nothing(self):
        got = self.mcp.edit_dashboard(ops=[{"op": "remove", "path": "views/0/sections/1"}], dry_run=True)
        self.assertTrue(got["dry_run"])
        self.assertEqual(got["would"], ["removed views/0/sections/1"])
        self.assertEqual(len(got["config"]["views"][0]["sections"]), 1)
        self.assertEqual(self.saved, [])

    def test_a_result_with_no_views_is_refused(self):
        got = self.mcp.edit_dashboard(ops=[{"op": "remove", "path": "views"}])
        self.assertIn("views", got["error"])
        self.assertEqual(self.saved, [])

    def test_an_unsaved_dashboard_needs_take_control(self):
        got = self.mcp.edit_dashboard(url_path="spare", ops=[{"op": "set", "path": "title", "value": "Spare"}])
        self.assertIn("take_control", got["error"])
        self.assertEqual(self.saved, [])
        got = self.mcp.edit_dashboard(url_path="spare", take_control=True, ops=[
            {"op": "add", "path": "views/0/sections/-", "value": {"type": "grid", "cards": []}}])
        self.assertNotIn("error", got)
        self.assertTrue(self.saved[0][2]["take_control"])
        self.assertEqual(self.saved[0][2]["url_path"], "spare")

    def test_it_is_an_acting_tool_everywhere_acting_tools_are_listed(self):
        m = self.mcp
        self.assertIn("edit_dashboard", {t["name"] for t in m.TOOLS})
        self.assertIn("edit_dashboard", m.CONTRACT_REFUSED_TOOLS)
        self.assertIn("edit_dashboard", m.VOICE_REFUSED_TOOLS)
        for path in ("brain/scripts/brain-action-gate.py", "brain/panel/consequence.py", "brain/panel/engine.py"):
            self.assertIn("edit_dashboard", (BASE_DIR / path).read_text(), path)


class DashboardInfoService(unittest.TestCase):
    """brain.update_dashboard_info is declared everywhere a service is."""

    def test_declared_in_services_strings_and_icons(self):
        import json

        import yaml
        comp = BASE_DIR / "brain" / "custom_components" / "brain"
        services = yaml.safe_load((comp / "services.yaml").read_text())
        self.assertEqual(set(services["update_dashboard_info"]["fields"]),
                         {"url_path", "title", "icon", "show_in_sidebar", "require_admin", "dry_run"})
        for f in ("strings.json", "translations/en.json"):
            self.assertIn("update_dashboard_info", json.loads((comp / f).read_text())["services"], f)
        self.assertIn("update_dashboard_info", json.loads((comp / "icons.json").read_text())["services"])
        self.assertIn('PowerTool("update_dashboard_info"', (comp / "power_tools.py").read_text())


if __name__ == "__main__":
    unittest.main()
