#!/usr/bin/env python3
"""Tests for BRUH Power Tools: the registry-management services added to the
bruh_claude integration (power_tools.py) and their MCP-side counterparts
(get_registry, call_service return_response).

The integration module imports homeassistant, which isn't installed here, so
integration-side checks are static (AST/regex + metadata files) — the same
strategy as test_integration_python.py. The MCP server is imported directly.
"""

import ast
import json
import os
import re
import sys
import unittest
from unittest.mock import patch

import yaml

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
INTEGRATION_DIR = os.path.join(
    BASE_DIR, "bruh-claude-terminal", "custom_components", "bruh_claude"
)

sys.path.insert(
    0, os.path.join(BASE_DIR, "bruh-claude-terminal", "ha-mcp-server")
)
import ha_mcp_server  # noqa: E402


def _power_tool_services():
    """Extract the registered service names from power_tools.py via AST."""
    source = open(os.path.join(INTEGRATION_DIR, "power_tools.py")).read()
    tree = ast.parse(source)
    services = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "PowerTool"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            services.append(node.args[0].value)
    return services


PRE_EXISTING_SERVICES = {
    "send_prompt", "run_task", "clear_conversation", "run_insight",
    "add_memory", "answer_question",
}


class TestPowerToolCatalog(unittest.TestCase):
    """The catalog is the contract: code, services.yaml, strings, and icons
    must always agree on the set of services."""

    @classmethod
    def setUpClass(cls):
        cls.services = _power_tool_services()
        with open(os.path.join(INTEGRATION_DIR, "services.yaml")) as f:
            cls.services_yaml = yaml.safe_load(f)
        with open(os.path.join(INTEGRATION_DIR, "strings.json")) as f:
            cls.strings = json.load(f)
        with open(os.path.join(INTEGRATION_DIR, "icons.json")) as f:
            cls.icons = json.load(f)

    def test_catalog_is_nonempty_and_unique(self):
        self.assertGreaterEqual(len(self.services), 30)
        self.assertEqual(len(self.services), len(set(self.services)))

    def test_expected_capability_groups_present(self):
        services = set(self.services)
        for expected in (
            "create_area", "rename_area", "create_floor", "create_label",
            "add_label", "rename_entity", "change_entity_id",
            "delete_orphaned_entities", "disable_device", "rename_device",
            "reload_integration", "create_zone",
            "add_device_tracker_to_person", "create_repair_issue",
        ):
            self.assertIn(expected, services)

    def test_every_service_in_services_yaml(self):
        for service in self.services:
            self.assertIn(service, self.services_yaml)
            entry = self.services_yaml[service]
            self.assertIn("name", entry, service)
            self.assertIn("description", entry, service)

    def test_every_service_in_strings_and_icons(self):
        for service in self.services:
            self.assertIn(service, self.strings["services"], service)
            self.assertIn(service, self.icons["services"], service)

    def test_services_yaml_fields_match_strings_fields(self):
        for service in self.services:
            yaml_fields = set(self.services_yaml[service].get("fields", {}))
            strings_fields = set(
                self.strings["services"][service].get("fields", {})
            )
            self.assertEqual(yaml_fields, strings_fields, service)

    def test_no_stray_bruh_services_outside_catalog(self):
        """Everything in services.yaml is either a pre-existing service or a
        power tool — no orphaned metadata."""
        expected = PRE_EXISTING_SERVICES | set(self.services)
        self.assertEqual(set(self.services_yaml), expected)

    def test_user_issue_translation_exists(self):
        """create_repair_issue renders through the user_issue translation."""
        issue = self.strings["issues"]["user_issue"]
        self.assertEqual(issue["title"], "{title}")
        self.assertIn("confirm", issue["fix_flow"]["step"])


class TestInitWiring(unittest.TestCase):
    """__init__.py must register the power tools and tear them down."""

    @classmethod
    def setUpClass(cls):
        cls.source = open(os.path.join(INTEGRATION_DIR, "__init__.py")).read()

    def test_imports_power_tools(self):
        self.assertIn(
            "from .power_tools import POWER_TOOL_SERVICES, "
            "async_register_power_tools",
            self.source,
        )

    def test_registers_power_tools(self):
        self.assertIn("async_register_power_tools(hass)", self.source)

    def test_unload_tears_down_power_tools(self):
        self.assertIn("*POWER_TOOL_SERVICES,", self.source)


class TestPowerToolsModuleShape(unittest.TestCase):
    """Static safety checks on power_tools.py itself."""

    @classmethod
    def setUpClass(cls):
        cls.source = open(
            os.path.join(INTEGRATION_DIR, "power_tools.py")
        ).read()

    def test_admin_gate_present(self):
        """Every handler goes through the admin gate wrapper."""
        self.assertIn("def _admin_gated", self.source)
        self.assertIn("Unauthorized(context=call.context)", self.source)
        self.assertIn("_admin_gated(hass, tool)", self.source)

    def test_orphan_cleanup_defaults_to_dry_run(self):
        self.assertIn('call.data.get("dry_run", True)', self.source)
        self.assertIn('vol.Optional("dry_run", default=True)', self.source)

    def test_spook_attribution_present(self):
        """Vendored MIT code keeps its attribution."""
        self.assertIn("github.com/frenck/spook", self.source)
        self.assertIn("MIT License", self.source)


class TestMcpGetRegistry(unittest.TestCase):
    """get_registry trims and filters WebSocket registry listings."""

    def test_unknown_registry_is_an_error(self):
        result = ha_mcp_server.get_registry("bogus")
        self.assertIn("error", result)

    def test_areas_trimmed_and_counted(self):
        rows = [
            {"area_id": "kitchen", "name": "Kitchen", "floor_id": None,
             "icon": None, "aliases": [], "labels": [], "picture": "x.png"},
            {"area_id": "office", "name": "Office", "floor_id": "first",
             "icon": "mdi:desk", "aliases": ["study"], "labels": []},
        ]
        with patch.object(ha_mcp_server, "_ws_command", return_value=rows):
            result = ha_mcp_server.get_registry("areas")
        self.assertEqual(result["count"], 2)
        self.assertNotIn("picture", result["items"][0])
        self.assertEqual(result["items"][1]["floor_id"], "first")

    def test_name_filter_matches_any_text_field(self):
        rows = [
            {"area_id": "kitchen", "name": "Kitchen"},
            {"area_id": "office", "name": "Office"},
        ]
        with patch.object(ha_mcp_server, "_ws_command", return_value=rows):
            result = ha_mcp_server.get_registry("areas", name_filter="off")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["area_id"], "office")

    def test_devices_and_integrations_renamed_ids(self):
        with patch.object(
            ha_mcp_server, "_ws_command",
            return_value=[{"id": "d1", "name": "Hub", "name_by_user": None}],
        ):
            result = ha_mcp_server.get_registry("devices")
        self.assertEqual(result["items"][0]["device_id"], "d1")
        with patch.object(
            ha_mcp_server, "_ws_command",
            return_value=[{"entry_id": "c1", "domain": "hue",
                           "title": "Hue", "state": "loaded"}],
        ):
            result = ha_mcp_server.get_registry("integrations")
        self.assertEqual(result["items"][0]["config_entry_id"], "c1")

    def test_truncation_note_over_cap(self):
        rows = [{"area_id": f"a{i}", "name": f"Area {i}"} for i in range(350)]
        with patch.object(ha_mcp_server, "_ws_command", return_value=rows):
            result = ha_mcp_server.get_registry("areas")
        self.assertEqual(result["count"], 350)
        self.assertEqual(len(result["items"]), ha_mcp_server.MAX_REGISTRY_RESULTS)
        self.assertIn("note", result)


class TestMcpCallServiceResponse(unittest.TestCase):
    """call_service with return_response routes over the WebSocket API."""

    def test_return_response_uses_websocket(self):
        with patch.object(
            ha_mcp_server, "_ws_command",
            return_value={"response": {"area_id": "guest_room"}},
        ) as ws:
            result = ha_mcp_server.call_service(
                "bruh_claude", "create_area",
                {"name": "Guest Room"}, return_response=True,
            )
        payload = ws.call_args[0][0]
        self.assertEqual(payload["type"], "call_service")
        self.assertTrue(payload["return_response"])
        self.assertEqual(result["response"]["area_id"], "guest_room")

    def test_deny_list_still_applies(self):
        with patch.object(
            ha_mcp_server, "DENIED_SERVICES", ["bruh_claude.*"]
        ):
            result = ha_mcp_server.call_service(
                "bruh_claude", "delete_area",
                {"area_id": "kitchen"}, return_response=True,
            )
        self.assertIn("error", result)

    def test_default_path_still_rest(self):
        with patch.object(
            ha_mcp_server, "ha_api_request", return_value=[]
        ) as rest, patch.object(ha_mcp_server, "_ws_command") as ws:
            ha_mcp_server.call_service("light", "turn_on",
                                       {"entity_id": "light.x"})
        rest.assert_called_once()
        ws.assert_not_called()


if __name__ == "__main__":
    unittest.main()
