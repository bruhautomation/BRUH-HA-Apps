#!/usr/bin/env python3
"""Tests for BRUH Power Tools: the registry-management services added to the
brain integration (power_tools.py) and their MCP-side counterparts
(get_registry, call_service return_response).

The integration module imports homeassistant, which isn't installed here, so
integration-side checks are static (AST/regex + metadata files) — the same
strategy as test_integration_python.py. The MCP server is imported directly.
"""

import ast
import json
import os
import sys
import unittest
from unittest.mock import patch

import yaml

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
INTEGRATION_DIR = os.path.join(
    BASE_DIR, "brain", "custom_components", "brain"
)

sys.path.insert(
    0, os.path.join(BASE_DIR, "brain", "ha-mcp-server")
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


# brAIn's own services, as distinct from the Power Tools catalog below.
PRE_EXISTING_SERVICES = {
    "send_prompt", "run_task", "clear_conversation", "run_insight",
    "add_memory", "answer_question", "study",
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
            "import_blueprint", "import_statistics",
            "enable_user", "disable_user", "find_orphaned_references",
            "create_helper", "delete_helper", "update_zone",
            "set_entity_aliases", "set_entity_icon",
            "create_dashboard", "delete_dashboard",
            "add_dashboard_resource", "remove_dashboard_resource",
            "create_person", "delete_person",
            "create_user", "delete_user",
            # Every registry object you can create, you can also change and
            # remove. Labels were create-only, and a device could be renamed
            # and disabled but never deleted.
            "rename_label", "update_label", "set_area_icon", "update_floor",
            "delete_device", "delete_orphaned_devices", "delete_integration",
            "rename_person",
        ):
            self.assertIn(expected, services)

    def test_everything_creatable_is_also_renamable(self):
        """A registry object you can name at creation and never rename again
        is a typo you live with. Areas, floors, labels, devices, entities and
        people all take the same verb."""
        services = set(self.services)
        for thing in ("area", "floor", "label", "device", "entity", "person"):
            self.assertIn(f"rename_{thing}", services)

    def test_registries_have_a_delete_for_everything_they_create(self):
        services = set(self.services)
        for thing in ("area", "floor", "label", "device", "zone", "person",
                      "helper", "user", "dashboard"):
            self.assertIn(f"delete_{thing}", services)

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

    def test_orphan_cleanup_supports_scoped_deletion(self):
        """The entity_id filter must re-verify orphan status: requested
        entities are intersected with the live orphan list, and live
        entities are reported as skipped rather than deleted."""
        self.assertIn('requested = call.data.get("entity_id")', self.source)
        self.assertIn("skipped = sorted(requested_set - set(orphaned))", self.source)
        self.assertIn('result["skipped_not_orphaned"] = skipped', self.source)

    def test_partial_updates_never_blank_unnamed_fields(self):
        """An update handler that reads every field with call.data.get()
        wipes whatever the caller didn't mention — icon and description come
        back as None. Only keys actually present may be passed through, and
        naming none of them is an error rather than a silent no-op."""
        self.assertIn("def _partial_update", self.source)
        self.assertIn("changes = {f: call.data[f] for f in fields if f in call.data}",
                      self.source)
        self.assertIn("Nothing to update", self.source)
        for handler in ("_update_floor", "_update_label"):
            body = self.source[self.source.index(f"async def {handler}("):]
            body = body[:body.index("\n\nasync def ")]
            self.assertIn("_partial_update(call", body, handler)

    def test_device_deletion_reports_what_would_come_back(self):
        """Deleting a device a live integration still provides looks like it
        failed: the device reappears on the next reload. The preview names
        the config entries that would recreate it, so that is visible before
        the delete rather than after."""
        self.assertIn('"live_config_entries": live', self.source)
        self.assertIn("hass.config_entries.async_get_entry(entry_id) is not None",
                      self.source)

    def test_orphan_device_cleanup_defaults_to_dry_run(self):
        """Same default as the entity cleanup it mirrors — a bulk delete
        that runs on the first call is a bulk delete nobody previewed."""
        body = self.source[self.source.index("async def _delete_orphaned_devices("):]
        body = body[:body.index("\n\n\n")]
        self.assertIn('dry_run = call.data.get("dry_run", True)', body)
        self.assertIn('result["skipped_not_orphaned"] = skipped', body)

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

    def test_users_registry_trimmed_and_protected_fields_kept(self):
        rows = [
            {"id": "u1", "name": "Ben", "username": "ben", "is_owner": True,
             "is_active": True, "system_generated": False,
             "credentials": [{"type": "homeassistant"}]},
        ]
        with patch.object(ha_mcp_server, "_ws_command", return_value=rows):
            result = ha_mcp_server.get_registry("users")
        item = result["items"][0]
        self.assertEqual(item["user_id"], "u1")
        self.assertTrue(item["is_owner"])
        self.assertNotIn("credentials", item)

    def test_truncation_note_over_cap(self):
        rows = [{"area_id": f"a{i}", "name": f"Area {i}"} for i in range(350)]
        with patch.object(ha_mcp_server, "_ws_command", return_value=rows):
            result = ha_mcp_server.get_registry("areas")
        self.assertEqual(result["count"], 350)
        self.assertEqual(len(result["items"]), ha_mcp_server.MAX_REGISTRY_RESULTS)
        self.assertIn("note", result)


class TestMcpDashboardTools(unittest.TestCase):
    """list_dashboards / get_dashboard: the read half of dashboard editing."""

    def test_list_dashboards_trims_and_notes_default(self):
        rows = [
            {"url_path": "lights", "title": "Lights", "mode": "storage",
             "id": "abc123", "require_admin": False},
        ]
        with patch.object(ha_mcp_server, "_ws_command", return_value=rows):
            result = ha_mcp_server.list_dashboards()
        self.assertEqual(result["count"], 1)
        self.assertNotIn("id", result["dashboards"][0])
        self.assertIn("default dashboard", result["note"])

    def test_get_dashboard_returns_config(self):
        config = {"views": [{"title": "Home", "cards": []}]}
        with patch.object(ha_mcp_server, "_ws_command", return_value=config) as ws:
            result = ha_mcp_server.get_dashboard("lights")
        self.assertEqual(ws.call_args[0][0]["url_path"], "lights")
        self.assertEqual(result["config"], config)

    def test_get_dashboard_default_uses_null_url_path(self):
        with patch.object(
            ha_mcp_server, "_ws_command", return_value={"views": []}
        ) as ws:
            ha_mcp_server.get_dashboard()
        self.assertIsNone(ws.call_args[0][0]["url_path"])

    def test_get_dashboard_summarizes_when_too_large(self):
        big = {"views": [
            {"title": "Home", "cards": [{"x": "y" * 5000}] * 50},
        ]}
        with patch.object(ha_mcp_server, "_ws_command", return_value=big):
            result = ha_mcp_server.get_dashboard("big")
        self.assertNotIn("config", result)
        self.assertEqual(result["views"][0]["cards"], 50)

    def test_get_dashboard_unsaved_config_hint(self):
        err = {"error": "{'code': 'config_not_found', 'message': '...'}"}
        with patch.object(ha_mcp_server, "_ws_command", return_value=err):
            result = ha_mcp_server.get_dashboard("fresh")
        self.assertIn("auto-generated", result["note"])


class TestDashboardServices(unittest.TestCase):
    """Static checks on the dashboard power tools."""

    @classmethod
    def setUpClass(cls):
        cls.source = open(
            os.path.join(INTEGRATION_DIR, "power_tools.py")
        ).read()
        cls.run_sh = open(
            os.path.join(BASE_DIR, "brain", "run.sh")
        ).read()

    def test_update_backs_up_before_saving(self):
        """The backup write must appear before async_save in the update
        handler, and restore must exist as its counterpart."""
        handler = self.source.split("async def _update_dashboard")[1].split(
            "async def _restore_dashboard"
        )[0]
        self.assertLess(
            handler.index("_save_dashboard_backup"),
            handler.index("dashboard.async_save"),
        )
        self.assertIn("async def _restore_dashboard", self.source)

    def test_yaml_dashboards_refused(self):
        self.assertIn('"storage"', self.source)
        self.assertIn("YAML-mode", self.source)

    def test_backup_restore_rejects_foreign_names(self):
        self.assertIn("not _is_backup_of(slug, name)", self.source)

    def test_backup_matcher_is_slug_exact(self):
        """A bare slug- prefix match lets dashboards with a shared name
        prefix (docs-shots vs docs-shots-v2) restore/prune each other's
        backups — the matcher must require the exact timestamp shape."""
        matcher = self.source.split("def _is_backup_of")[1].split("\n\n\n")[0]
        self.assertIn(r"\d{8}-\d{6}", matcher)

    def test_user_lifecycle_guards(self):
        """delete_user must guard owners/system accounts, and create_user
        must roll back the half-created user if login creation fails."""
        delete_handler = self.source.split("async def _delete_user")[1].split(
            "\n\n\n"
        )[0]
        self.assertIn("is_owner", delete_handler)
        self.assertIn("system_generated", delete_handler)
        create_handler = self.source.split("async def _create_user")[1].split(
            "async def _delete_user"
        )[0]
        self.assertIn("await hass.auth.async_remove_user(user)", create_handler)
        self.assertIn('bool(username) != bool(password)', create_handler)

    def test_delete_dashboard_backs_up_first(self):
        handler = self.source.split("async def _delete_dashboard")[1].split(
            "RESOURCE_TYPES"
        )[0]
        self.assertLess(
            handler.index("_save_dashboard_backup"),
            handler.index("collection.async_delete_item"),
        )

    def test_helper_domains_complete(self):
        for domain in ("input_boolean", "input_number", "input_select",
                       "input_text", "input_datetime", "counter", "timer",
                       "schedule"):
            self.assertIn(f'"{domain}"', self.source)

class TestMcpCallServiceResponse(unittest.TestCase):
    """call_service with return_response routes over the WebSocket API."""

    def test_return_response_uses_websocket(self):
        with patch.object(
            ha_mcp_server, "_ws_command",
            return_value={"response": {"area_id": "guest_room"}},
        ) as ws:
            result = ha_mcp_server.call_service(
                "brain", "create_area",
                {"name": "Guest Room"}, return_response=True,
            )
        payload = ws.call_args[0][0]
        self.assertEqual(payload["type"], "call_service")
        self.assertTrue(payload["return_response"])
        self.assertEqual(result["response"]["area_id"], "guest_room")

    def test_deny_list_still_applies(self):
        with patch.object(
            ha_mcp_server, "DENIED_SERVICES", ["brain.*"]
        ):
            result = ha_mcp_server.call_service(
                "brain", "delete_area",
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
