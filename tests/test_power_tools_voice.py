#!/usr/bin/env python3
"""No Power Tool is reachable from a voice-level agent.

Every brain.* service administers Home Assistant: users, backups, recorder
statistics, integration options, Z-Wave nodes, Thread networks. brAIn
reaches them through the MCP server's `call_service`, so the voice level's
service rule (`_voice_service_refusal`) is what keeps them from the kitchen
satellite, with `_exposure_refusal` refusing a device, area, label or floor
target outright — the two refusals `call_service` asks in turn. This drives
them over EVERY service in the catalog with the
arguments a call would really carry — none, a person, a user, a device, a
group — so a Power Tool added later is covered by having been added.
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "brain" / "ha-mcp-server"))
import ha_mcp_server  # noqa: E402


def power_tools() -> list[str]:
    source = (BASE / "brain" / "custom_components" / "brain" / "power_tools.py").read_text()
    return [n.args[0].value for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "PowerTool" and n.args
            and isinstance(n.args[0], ast.Constant)]


PAYLOADS = (
    {},
    {"user_id": "abc", "group": "admin"},
    {"entity_id": "person.alex", "device_tracker": ["device_tracker.phone"]},
    {"entity_id": "light.kitchen_group", "add": ["light.hall"]},
    {"device_id": "d1"},
    {"statistic_id": "sensor.grid_import", "adjustment": 1},
    {"config_entry_id": "e1", "options": {"x": 1}},
    {"entity_id": ["automation.morning"], "scope": "automation"},
)


class TestVoiceReachesNoPowerTool(unittest.TestCase):
    def setUp(self):
        self._old = ha_mcp_server.EXPOSED_ONLY
        ha_mcp_server.EXPOSED_ONLY = True
        self.addCleanup(setattr, ha_mcp_server, "EXPOSED_ONLY", self._old)

    def test_every_power_tool_is_refused_on_voice(self):
        tools = power_tools()
        self.assertIn("set_user_group", tools)
        self.assertIn("delete_backups", tools)
        for service in tools:
            for payload in PAYLOADS:
                with self.subTest(service=service, payload=payload):
                    refused = (ha_mcp_server._voice_service_refusal(
                        "brain", service, payload)
                        or ha_mcp_server._exposure_refusal(payload))
                    self.assertIsNotNone(refused)

    def test_brain_is_on_no_voice_allow_list(self):
        self.assertNotIn("brain", ha_mcp_server.VOICE_UNTARGETED)
        self.assertNotIn("brain", ha_mcp_server.VOICE_CROSS_DOMAIN)


class TestVoiceMayShopButNeverBuy(unittest.TestCase):
    """BRUH Browser by voice: start a cart errand and ask how it went, never
    buy and never stop one. Refused before anything reaches the add-on, and
    not shown to a voice turn at all."""

    def setUp(self):
        self._old = ha_mcp_server.EXPOSED_ONLY
        ha_mcp_server.EXPOSED_ONLY = True
        self.addCleanup(setattr, ha_mcp_server, "EXPOSED_ONLY", self._old)
        self.calls = []
        original = ha_mcp_server._browser_request

        def record(method, path, body=None, timeout=20):
            self.calls.append((method, path, body))
            return {"task": {"id": "abc123", "state": "queued"}}

        ha_mcp_server._browser_request = record
        self.addCleanup(setattr, ha_mcp_server, "_browser_request", original)

    def test_buying_and_stopping_are_refused_before_the_add_on_is_asked(self):
        for name, args in (("browser_purchase", {"cart_task": "abc123", "total": 3.0,
                                                 "items": [{"name": "oat milk", "quantity": 1}]}),
                           ("browser_stop", {})):
            with self.subTest(tool=name):
                answer = ha_mcp_server.handle_tool_call(name, args)
                self.assertIn("error", answer)
        self.assertEqual(self.calls, [])

    def test_a_cart_errand_and_its_status_reach_the_add_on(self):
        ha_mcp_server.handle_tool_call("browser_task", {"errand": "add oat milk"})
        ha_mcp_server.handle_tool_call("browser_status", {})
        self.assertEqual([c[0] for c in self.calls], ["POST", "GET"])
        self.assertIs(self.calls[0][2]["purchase"], False)

    def test_voice_is_not_shown_the_buying_tools(self):
        names = {t["name"] for t in ha_mcp_server.tools_for_channel()}
        self.assertIn("browser_task", names)
        self.assertEqual({"browser_purchase", "browser_stop"} & names, set())


if __name__ == "__main__":
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    unittest.main()
