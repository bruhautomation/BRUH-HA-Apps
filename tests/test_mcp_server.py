#!/usr/bin/env python3
"""
Comprehensive tests for the Home Assistant MCP Server.

Tests cover:
- MCP protocol compliance (initialize, tools/list, tools/call, ping)
- Tool implementations with mocked HA API responses
- Error handling (HTTP errors, network errors, malformed input)
- Edge cases (empty states, missing fields, large payloads)
- JSON-RPC compliance
"""

import json
import os
import sys
import io
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError

# Add the MCP server directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bruh-claude-terminal", "ha-mcp-server"))

import ha_mcp_server


class TestHaApiRequest(unittest.TestCase):
    """Test the core API request function."""

    @patch("ha_mcp_server.urllib.request.urlopen")
    def test_get_request_success(self, mock_urlopen):
        """Test successful GET request."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"result": "ok"}).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = ha_mcp_server.ha_api_request("/api/config")
        self.assertEqual(result, {"result": "ok"})

    @patch("ha_mcp_server.urllib.request.urlopen")
    def test_plain_text_response(self, mock_urlopen):
        """Test handling of plain text response (e.g., error_log)."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"2024-01-01 ERROR something broke\n2024-01-01 WARNING something else"
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = ha_mcp_server.ha_api_request("/api/error_log")
        self.assertIsInstance(result, str)
        self.assertIn("ERROR", result)

    @patch("ha_mcp_server.urllib.request.urlopen")
    def test_http_error_handling(self, mock_urlopen):
        """Test HTTP error is properly caught and returned."""
        mock_urlopen.side_effect = HTTPError(
            url="http://test", code=404, msg="Not Found",
            hdrs=MagicMock(), fp=io.BytesIO(b"not found")
        )

        result = ha_mcp_server.ha_api_request("/api/states/nonexistent")
        self.assertIn("error", result)
        self.assertIn("404", result["error"])

    @patch("ha_mcp_server.urllib.request.urlopen")
    def test_network_error_handling(self, mock_urlopen):
        """Test network error is properly caught."""
        mock_urlopen.side_effect = URLError("Connection refused")

        result = ha_mcp_server.ha_api_request("/api/config")
        self.assertIn("error", result)

    @patch("ha_mcp_server.urllib.request.urlopen")
    def test_timeout_handling(self, mock_urlopen):
        """Test timeout error handling."""
        mock_urlopen.side_effect = TimeoutError("Request timed out")

        result = ha_mcp_server.ha_api_request("/api/config")
        self.assertIn("error", result)

    def test_endpoint_url_construction_api(self):
        """Test URL construction for /api/ endpoints."""
        with patch("ha_mcp_server.urllib.request.urlopen") as mock:
            mock_response = MagicMock()
            mock_response.read.return_value = b'"{}"'
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock.return_value = mock_response

            ha_mcp_server.ha_api_request("/api/states")

            called_url = mock.call_args[0][0].full_url
            self.assertIn("/states", called_url)

    def test_endpoint_url_construction_supervisor(self):
        """Test URL construction for supervisor endpoints."""
        with patch("ha_mcp_server.urllib.request.urlopen") as mock:
            mock_response = MagicMock()
            mock_response.read.return_value = b'"{}"'
            mock_response.__enter__ = lambda s: s
            mock_response.__exit__ = MagicMock(return_value=False)
            mock.return_value = mock_response

            ha_mcp_server.ha_api_request("/core/info")

            called_url = mock.call_args[0][0].full_url
            self.assertIn("/core/info", called_url)

    @patch("ha_mcp_server.urllib.request.urlopen")
    def test_post_request_with_data(self, mock_urlopen):
        """Test POST request sends correct data."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'[]'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        ha_mcp_server.ha_api_request(
            "/api/services/light/turn_on",
            method="POST",
            data={"entity_id": "light.test"}
        )

        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.method, "POST")
        sent_data = json.loads(req.data.decode())
        self.assertEqual(sent_data["entity_id"], "light.test")


class TestToolImplementations(unittest.TestCase):
    """Test individual tool implementations."""

    @patch("ha_mcp_server.ha_api_request")
    def test_get_entity_state(self, mock_api):
        """Test getting a single entity state."""
        mock_api.return_value = {
            "entity_id": "light.living_room",
            "state": "on",
            "attributes": {"brightness": 255, "friendly_name": "Living Room Light"},
            "last_changed": "2024-01-01T00:00:00Z",
            "last_updated": "2024-01-01T00:00:00Z",
        }

        result = ha_mcp_server.get_entity_state("light.living_room")
        self.assertEqual(result["entity_id"], "light.living_room")
        self.assertEqual(result["state"], "on")
        self.assertEqual(result["attributes"]["brightness"], 255)

    @patch("ha_mcp_server.ha_api_request")
    def test_get_entity_state_error(self, mock_api):
        """Test error response for missing entity."""
        mock_api.return_value = {"error": "HTTP 404: Not Found"}

        result = ha_mcp_server.get_entity_state("light.nonexistent")
        self.assertIn("error", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_get_all_states(self, mock_api):
        """Test getting all entity states."""
        mock_api.return_value = [
            {"entity_id": "light.a", "state": "on", "attributes": {"friendly_name": "A"}},
            {"entity_id": "sensor.b", "state": "22", "attributes": {"friendly_name": "B"}},
            {"entity_id": "light.c", "state": "off", "attributes": {"friendly_name": "C"}},
        ]

        result = ha_mcp_server.get_all_states()
        self.assertEqual(len(result), 3)

    @patch("ha_mcp_server.ha_api_request")
    def test_get_all_states_domain_filter(self, mock_api):
        """Test filtering states by domain."""
        mock_api.return_value = [
            {"entity_id": "light.a", "state": "on", "attributes": {"friendly_name": "A"}},
            {"entity_id": "sensor.b", "state": "22", "attributes": {"friendly_name": "B"}},
            {"entity_id": "light.c", "state": "off", "attributes": {"friendly_name": "C"}},
        ]

        result = ha_mcp_server.get_all_states(domain="light")
        self.assertEqual(len(result), 2)
        for entity in result:
            self.assertTrue(entity["entity_id"].startswith("light."))

    @patch("ha_mcp_server.ha_api_request")
    def test_get_all_states_empty(self, mock_api):
        """Test empty state list."""
        mock_api.return_value = []

        result = ha_mcp_server.get_all_states()
        self.assertEqual(result, [])

    @patch("ha_mcp_server.ha_api_request")
    def test_get_all_states_error_response(self, mock_api):
        """Test error response from API."""
        mock_api.return_value = {"error": "Unauthorized"}

        result = ha_mcp_server.get_all_states()
        self.assertIn("error", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_call_service(self, mock_api):
        """Test calling a HA service."""
        mock_api.return_value = [{"entity_id": "light.test", "state": "on"}]

        result = ha_mcp_server.call_service("light", "turn_on", {"entity_id": "light.test"})
        mock_api.assert_called_with("/api/services/light/turn_on", method="POST", data={"entity_id": "light.test"})

    @patch("ha_mcp_server.ha_api_request")
    def test_call_service_no_data(self, mock_api):
        """Test calling a service without data."""
        mock_api.return_value = []

        ha_mcp_server.call_service("automation", "reload")
        mock_api.assert_called_with("/api/services/automation/reload", method="POST", data={})

    @patch("ha_mcp_server.ha_api_request")
    def test_get_automations(self, mock_api):
        """Test getting automations list."""
        mock_api.return_value = [
            {
                "entity_id": "automation.test",
                "state": "on",
                "attributes": {
                    "friendly_name": "Test Automation",
                    "last_triggered": "2024-01-01T00:00:00Z"
                },
            },
            {"entity_id": "light.not_automation", "state": "on", "attributes": {}},
        ]

        result = ha_mcp_server.get_automations()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["entity_id"], "automation.test")
        self.assertEqual(result[0]["friendly_name"], "Test Automation")

    @patch("ha_mcp_server.ha_api_request")
    def test_get_config(self, mock_api):
        """Test getting HA config."""
        mock_api.return_value = {
            "version": "2024.1.0",
            "location_name": "Home",
            "time_zone": "US/Eastern",
        }

        result = ha_mcp_server.get_config()
        self.assertEqual(result["version"], "2024.1.0")

    @patch("ha_mcp_server.ha_api_request")
    def test_get_services(self, mock_api):
        """Test getting services list."""
        mock_api.return_value = [
            {"domain": "light", "services": {"turn_on": {}, "turn_off": {}, "toggle": {}}},
            {"domain": "switch", "services": {"turn_on": {}, "turn_off": {}}},
        ]

        result = ha_mcp_server.get_services()
        self.assertEqual(len(result), 2)
        self.assertIn("turn_on", result[0]["services"])

    @patch("ha_mcp_server.ha_api_request")
    def test_get_device_registry(self, mock_api):
        """Test getting device registry."""
        mock_api.return_value = [
            {"entity_id": "light.a", "state": "on"},
            {"entity_id": "light.b", "state": "off"},
            {"entity_id": "sensor.c", "state": "22"},
        ]

        result = ha_mcp_server.get_device_registry()
        self.assertEqual(result["total_entities"], 3)
        self.assertIn("light", result["domains"])
        self.assertEqual(result["domains"]["light"], 2)

    @patch("ha_mcp_server.ha_api_request")
    def test_get_error_log(self, mock_api):
        """Test getting error log."""
        log_lines = "\n".join([f"Line {i}" for i in range(200)])
        mock_api.return_value = log_lines

        result = ha_mcp_server.get_error_log()
        self.assertIsInstance(result, str)
        # Should return last 100 lines
        lines = result.strip().split("\n")
        self.assertLessEqual(len(lines), 100)

    @patch("ha_mcp_server.ha_api_request")
    def test_render_template(self, mock_api):
        """Test rendering a template."""
        mock_api.return_value = "22.5"

        result = ha_mcp_server.render_template('{{ states("sensor.temperature") }}')
        self.assertEqual(result, "22.5")

    @patch("ha_mcp_server.ha_api_request")
    def test_fire_event(self, mock_api):
        """Test firing an event."""
        mock_api.return_value = {"message": "Event fired."}

        result = ha_mcp_server.fire_event("custom_event", {"key": "value"})
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_get_supervisor_info(self, mock_api):
        """Test getting supervisor info."""
        mock_api.side_effect = [
            {"data": {"version": "2024.1.0", "operating_system": "HAOS"}},
            {"data": {"addons": [{"name": "a"}, {"name": "b"}]}},
            {"data": {"hostname": "homeassistant", "operating_system": "HAOS"}},
        ]

        result = ha_mcp_server.get_supervisor_info()
        self.assertEqual(result["addons_count"], 2)

    def test_reload_config_valid_targets(self):
        """Test reload_config accepts all documented targets."""
        valid_targets = [
            "automations", "scripts", "scenes", "groups",
            "input_booleans", "input_numbers", "input_selects",
            "input_texts", "input_datetimes", "timers", "counters",
            "core", "all"
        ]

        for target in valid_targets:
            with patch("ha_mcp_server.call_service") as mock_svc:
                mock_svc.return_value = []
                result = ha_mcp_server.reload_config(target)
                # Should not return an error
                if isinstance(result, dict) and "error" in result:
                    self.fail(f"reload_config failed for valid target: {target}")

    def test_reload_config_invalid_target(self):
        """Test reload_config rejects invalid targets."""
        result = ha_mcp_server.reload_config("invalid_target")
        self.assertIn("error", result)
        self.assertIn("valid_targets", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_get_logbook_clamps_hours(self, mock_api):
        """Test that logbook hours are clamped."""
        mock_api.return_value = []

        # Should not error with extreme values
        ha_mcp_server.get_logbook(hours=100)
        ha_mcp_server.get_logbook(hours=-5)
        ha_mcp_server.get_logbook(hours=0)


class TestHandleToolCall(unittest.TestCase):
    """Test the tool call routing function."""

    @patch("ha_mcp_server.get_entity_state")
    def test_routes_get_entity_state(self, mock_fn):
        """Test routing to get_entity_state."""
        mock_fn.return_value = {"entity_id": "test"}
        result = ha_mcp_server.handle_tool_call("get_entity_state", {"entity_id": "light.test"})
        mock_fn.assert_called_with("light.test")

    @patch("ha_mcp_server.get_all_states")
    def test_routes_get_all_states(self, mock_fn):
        """Test routing to get_all_states with optional domain."""
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("get_all_states", {"domain": "light"})
        mock_fn.assert_called_with("light")

    @patch("ha_mcp_server.get_all_states")
    def test_routes_get_all_states_no_domain(self, mock_fn):
        """Test routing to get_all_states without domain."""
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("get_all_states", {})
        mock_fn.assert_called_with(None)

    def test_unknown_tool_returns_error(self):
        """Test that unknown tool name returns error."""
        result = ha_mcp_server.handle_tool_call("nonexistent_tool", {})
        self.assertIn("error", result)

    def test_missing_required_argument(self):
        """Test that missing required argument is caught."""
        result = ha_mcp_server.handle_tool_call("get_entity_state", {})
        self.assertIn("error", result)

    @patch("ha_mcp_server.call_service")
    def test_routes_call_service(self, mock_fn):
        """Test routing to call_service."""
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("call_service", {
            "domain": "light", "service": "turn_on", "data": {"entity_id": "light.test"}
        })
        mock_fn.assert_called_with("light", "turn_on", {"entity_id": "light.test"})


class TestMCPProtocol(unittest.TestCase):
    """Test MCP protocol compliance."""

    def _simulate_request(self, request_dict):
        """Simulate a single MCP request and capture the response."""
        input_line = json.dumps(request_dict) + "\n"
        captured_output = io.StringIO()

        with patch("sys.stdin", io.StringIO(input_line)):
            with patch("sys.stdout", captured_output):
                ha_mcp_server.main()

        output = captured_output.getvalue().strip()
        if output:
            return json.loads(output)
        return None

    def test_initialize(self):
        """Test MCP initialize handshake."""
        response = self._simulate_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0.0"}
            }
        })

        self.assertIsNotNone(response)
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        self.assertIn("protocolVersion", response["result"])
        self.assertIn("capabilities", response["result"])
        self.assertIn("tools", response["result"]["capabilities"])
        self.assertIn("serverInfo", response["result"])

    def test_tools_list(self):
        """Test tools/list returns all tools."""
        response = self._simulate_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        })

        self.assertIsNotNone(response)
        tools = response["result"]["tools"]
        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        # Verify each tool has required fields
        for tool in tools:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertIn("inputSchema", tool)
            self.assertIn("type", tool["inputSchema"])

        # Verify all expected tools are present
        tool_names = {t["name"] for t in tools}
        expected_tools = {
            # Core tools
            "get_entity_state", "get_all_states", "call_service",
            "get_service_details",
            # Domain-specific device control
            "control_light", "control_climate", "control_media_player",
            "control_cover", "control_fan", "control_switch",
            "control_lock", "control_alarm", "control_vacuum",
            "send_notification", "activate_scene", "run_script",
            # System tools
            "get_automations", "get_automation_trace", "get_ha_config",
            "get_services", "get_device_registry", "get_areas", "get_logbook",
            "get_error_log", "render_template", "fire_event",
            "get_supervisor_info", "reload_config",
        }
        self.assertEqual(tool_names, expected_tools)

    def test_ping(self):
        """Test ping response."""
        response = self._simulate_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "ping",
            "params": {}
        })

        self.assertIsNotNone(response)
        self.assertEqual(response["id"], 3)
        self.assertEqual(response["result"], {})

    def test_resources_list(self):
        """Test resources/list returns empty list."""
        response = self._simulate_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/list",
            "params": {}
        })

        self.assertIsNotNone(response)
        self.assertEqual(response["result"]["resources"], [])

    def test_prompts_list(self):
        """Test prompts/list returns empty list."""
        response = self._simulate_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "prompts/list",
            "params": {}
        })

        self.assertIsNotNone(response)
        self.assertEqual(response["result"]["prompts"], [])

    @patch("ha_mcp_server.ha_api_request")
    def test_tools_call(self, mock_api):
        """Test tools/call invocation."""
        mock_api.return_value = {
            "entity_id": "light.test",
            "state": "on",
            "attributes": {},
            "last_changed": "2024-01-01T00:00:00Z",
            "last_updated": "2024-01-01T00:00:00Z",
        }

        response = self._simulate_request({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "get_entity_state",
                "arguments": {"entity_id": "light.test"}
            }
        })

        self.assertIsNotNone(response)
        self.assertIn("content", response["result"])
        content = response["result"]["content"]
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["type"], "text")
        # The text should be valid JSON
        parsed = json.loads(content[0]["text"])
        self.assertEqual(parsed["entity_id"], "light.test")

    def test_unknown_method(self):
        """Test unknown method returns error."""
        response = self._simulate_request({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "unknown/method",
            "params": {}
        })

        self.assertIsNotNone(response)
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_malformed_json(self):
        """Test malformed JSON input."""
        captured_output = io.StringIO()

        with patch("sys.stdin", io.StringIO("not valid json\n")):
            with patch("sys.stdout", captured_output):
                ha_mcp_server.main()

        output = captured_output.getvalue().strip()
        if output:
            response = json.loads(output)
            self.assertIn("error", response)
            self.assertEqual(response["error"]["code"], -32700)

    def test_empty_lines_ignored(self):
        """Test that empty lines don't cause errors."""
        captured_output = io.StringIO()
        input_data = "\n\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n\n"

        with patch("sys.stdin", io.StringIO(input_data)):
            with patch("sys.stdout", captured_output):
                ha_mcp_server.main()

        output = captured_output.getvalue().strip()
        self.assertNotEqual(output, "")

    def test_notification_no_response(self):
        """Test that notifications (no id) don't produce a response for non-error cases."""
        response = self._simulate_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        # notifications/initialized should not send a response
        self.assertIsNone(response)


class TestToolSchemas(unittest.TestCase):
    """Test that tool schemas are valid JSON Schema."""

    def test_all_schemas_have_type_object(self):
        """Every tool's inputSchema should have type: object."""
        for tool in ha_mcp_server.TOOLS:
            self.assertEqual(
                tool["inputSchema"]["type"], "object",
                f"Tool {tool['name']} inputSchema type should be 'object'"
            )

    def test_required_fields_exist_in_properties(self):
        """Required fields should be defined in properties."""
        for tool in ha_mcp_server.TOOLS:
            required = tool["inputSchema"].get("required", [])
            properties = tool["inputSchema"].get("properties", {})
            for field in required:
                self.assertIn(
                    field, properties,
                    f"Tool {tool['name']}: required field '{field}' not in properties"
                )

    def test_no_duplicate_tool_names(self):
        """Tool names should be unique."""
        names = [t["name"] for t in ha_mcp_server.TOOLS]
        self.assertEqual(len(names), len(set(names)), "Duplicate tool names found")

    def test_all_tools_have_descriptions(self):
        """Every tool should have a non-empty description."""
        for tool in ha_mcp_server.TOOLS:
            self.assertTrue(
                len(tool["description"]) > 10,
                f"Tool {tool['name']} has too short a description"
            )


class TestSendResponse(unittest.TestCase):
    """Test response formatting."""

    def test_send_response_format(self):
        """Test that responses are valid JSON-RPC."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            ha_mcp_server.send_response(42, {"key": "value"})

        output = json.loads(captured.getvalue().strip())
        self.assertEqual(output["jsonrpc"], "2.0")
        self.assertEqual(output["id"], 42)
        self.assertEqual(output["result"]["key"], "value")

    def test_send_error_format(self):
        """Test that errors are valid JSON-RPC."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            ha_mcp_server.send_error(42, -32600, "Invalid Request")

        output = json.loads(captured.getvalue().strip())
        self.assertEqual(output["jsonrpc"], "2.0")
        self.assertEqual(output["id"], 42)
        self.assertEqual(output["error"]["code"], -32600)
        self.assertEqual(output["error"]["message"], "Invalid Request")

    def test_send_response_null_id(self):
        """Test response with null ID."""
        captured = io.StringIO()
        with patch("sys.stdout", captured):
            ha_mcp_server.send_response(None, {})

        output = json.loads(captured.getvalue().strip())
        self.assertIsNone(output["id"])


class TestGetAreas(unittest.TestCase):
    """Tests for the get_areas tool (area registry via the template engine)."""

    @patch("ha_mcp_server.ha_api_request")
    def test_areas_parsed_list(self, mock_api):
        """ha_api_request auto-parses the `| tojson` array → list."""
        mock_api.return_value = [
            {"area_id": "kitchen", "name": "Kitchen",
             "entities": ["light.kitchen", "switch.kettle"]},
            {"area_id": "bedroom", "name": "Bedroom",
             "entities": ["light.bedroom"]},
        ]
        result = ha_mcp_server.get_areas()
        self.assertEqual(result["area_count"], 2)
        self.assertEqual(result["areas"][0]["name"], "Kitchen")
        # It must hit the template endpoint, not invent a REST path.
        endpoint = mock_api.call_args[0][0]
        self.assertIn("/api/template", endpoint)

    @patch("ha_mcp_server.ha_api_request")
    def test_areas_string_payload(self, mock_api):
        """If the template comes back as a raw JSON string, it's parsed."""
        mock_api.return_value = '[{"area_id": "office", "name": "Office", "entities": []}]'
        result = ha_mcp_server.get_areas()
        self.assertEqual(result["area_count"], 1)
        self.assertEqual(result["areas"][0]["area_id"], "office")

    @patch("ha_mcp_server.ha_api_request")
    def test_areas_api_error_passthrough(self, mock_api):
        """An API error dict is passed straight through (sets isError)."""
        mock_api.return_value = {"error": "HTTP 401: Unauthorized"}
        result = ha_mcp_server.get_areas()
        self.assertIn("error", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_areas_unparseable_string(self, mock_api):
        """Garbage template output reports an error instead of crashing."""
        mock_api.return_value = "Template error: areas() is undefined"
        result = ha_mcp_server.get_areas()
        self.assertIn("error", result)
        self.assertIn("raw", result)

    @patch("ha_mcp_server.get_areas")
    def test_dispatch_routes_get_areas(self, mock_get_areas):
        """tools/call must route get_areas to the implementation."""
        mock_get_areas.return_value = {"area_count": 0, "areas": []}
        result = ha_mcp_server.handle_tool_call("get_areas", {})
        mock_get_areas.assert_called_once()
        self.assertEqual(result["area_count"], 0)


if __name__ == "__main__":
    unittest.main()
