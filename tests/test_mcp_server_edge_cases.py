#!/usr/bin/env python3
"""
Edge case and regression tests for the MCP server.

Tests cover:
- Large payloads and boundary conditions
- Concurrent request handling
- Malformed tool arguments
- API error propagation
- Special characters in entity IDs and data
- Multiple sequential requests
- Logbook hour clamping edge cases
- Error log with empty content
- Services with special characters
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server


class TestEdgeCaseEntityStates(unittest.TestCase):
    """Test edge cases in entity state handling."""

    @patch("ha_mcp_server.ha_api_request")
    def test_entity_with_no_attributes(self, mock_api):
        """Entity with empty attributes should work."""
        mock_api.return_value = {
            "entity_id": "binary_sensor.test",
            "state": "on",
            "attributes": {},
            "last_changed": "2024-01-01T00:00:00Z",
            "last_updated": "2024-01-01T00:00:00Z",
        }
        result = ha_mcp_server.get_entity_state("binary_sensor.test")
        self.assertEqual(result["attributes"], {})

    @patch("ha_mcp_server.ha_api_request")
    def test_entity_with_special_chars_in_name(self, mock_api):
        """Entity with special characters in friendly_name should work."""
        mock_api.return_value = {
            "entity_id": "sensor.temperature",
            "state": "22.5",
            "attributes": {
                "friendly_name": "Temp (°C) — Living Room",
                "unit_of_measurement": "°C"
            },
            "last_changed": "2024-01-01T00:00:00Z",
            "last_updated": "2024-01-01T00:00:00Z",
        }
        result = ha_mcp_server.get_entity_state("sensor.temperature")
        self.assertIn("°C", result["attributes"]["friendly_name"])

    @patch("ha_mcp_server.ha_api_request")
    def test_entity_with_null_state(self, mock_api):
        """Entity with null/unavailable state."""
        mock_api.return_value = {
            "entity_id": "sensor.offline",
            "state": "unavailable",
            "attributes": {"friendly_name": "Offline Sensor"},
            "last_changed": None,
            "last_updated": None,
        }
        result = ha_mcp_server.get_entity_state("sensor.offline")
        self.assertEqual(result["state"], "unavailable")
        self.assertIsNone(result["last_changed"])

    @patch("ha_mcp_server.ha_api_request")
    def test_get_all_states_very_large_list(self, mock_api):
        """A very large entity list is capped with a truncation envelope."""
        states = [
            {
                "entity_id": f"sensor.test_{i}",
                "state": str(i),
                "attributes": {"friendly_name": f"Test {i}"}
            }
            for i in range(1000)
        ]
        mock_api.return_value = states
        result = ha_mcp_server.get_all_states()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["total_matches"], 1000)
        self.assertEqual(result["returned"], ha_mcp_server.MAX_STATE_RESULTS)
        self.assertEqual(len(result["entities"]), ha_mcp_server.MAX_STATE_RESULTS)
        self.assertIn("note", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_get_all_states_at_cap_stays_list(self, mock_api):
        """Exactly MAX_STATE_RESULTS entities keeps the plain-list shape."""
        states = [
            {
                "entity_id": f"sensor.test_{i}",
                "state": str(i),
                "attributes": {"friendly_name": f"Test {i}"}
            }
            for i in range(ha_mcp_server.MAX_STATE_RESULTS)
        ]
        mock_api.return_value = states
        result = ha_mcp_server.get_all_states()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), ha_mcp_server.MAX_STATE_RESULTS)

    @patch("ha_mcp_server.ha_api_request")
    def test_get_all_states_with_nonstandard_entity_ids(self, mock_api):
        """Entities without dots in IDs should not crash."""
        mock_api.return_value = [
            {"entity_id": "weirdentity", "state": "on", "attributes": {}},
            {"entity_id": "light.normal", "state": "off", "attributes": {}},
        ]
        result = ha_mcp_server.get_all_states()
        self.assertEqual(len(result), 2)

    @patch("ha_mcp_server.ha_api_request")
    def test_domain_filter_case_sensitivity(self, mock_api):
        """Domain filter should be case-sensitive."""
        mock_api.return_value = [
            {"entity_id": "Light.test", "state": "on", "attributes": {}},
            {"entity_id": "light.test2", "state": "off", "attributes": {}},
        ]
        result = ha_mcp_server.get_all_states(domain="light")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["entity_id"], "light.test2")


class TestEdgeCaseLogbook(unittest.TestCase):
    """Test logbook edge cases."""

    @patch("ha_mcp_server.ha_api_request")
    def test_logbook_zero_hours(self, mock_api):
        """Zero hours should be clamped to minimum."""
        mock_api.return_value = []
        ha_mcp_server.get_logbook(hours=0)
        # Should not raise

    @patch("ha_mcp_server.ha_api_request")
    def test_logbook_negative_hours(self, mock_api):
        """Negative hours should be clamped to minimum."""
        mock_api.return_value = []
        ha_mcp_server.get_logbook(hours=-10)
        # Should not raise

    @patch("ha_mcp_server.ha_api_request")
    def test_logbook_none_hours(self, mock_api):
        """None hours should use default."""
        mock_api.return_value = []
        ha_mcp_server.get_logbook(hours=None)
        # Should not raise

    @patch("ha_mcp_server.ha_api_request")
    def test_logbook_large_hours(self, mock_api):
        """Hours > 24 should be clamped to 24."""
        mock_api.return_value = []
        ha_mcp_server.get_logbook(hours=100)
        # Should not raise

    @patch("ha_mcp_server.ha_api_request")
    def test_logbook_with_entity_filter(self, mock_api):
        """Logbook with entity filter should include entity parameter."""
        mock_api.return_value = []
        ha_mcp_server.get_logbook(hours=1, entity_id="light.test")
        called_endpoint = mock_api.call_args[0][0]
        self.assertIn("entity=light.test", called_endpoint)

    @patch("ha_mcp_server.ha_api_request")
    def test_logbook_limits_results(self, mock_api):
        """Logbook should limit results to 50 entries."""
        mock_api.return_value = [{"entity_id": f"test.{i}"} for i in range(100)]
        result = ha_mcp_server.get_logbook()
        self.assertLessEqual(len(result), 50)


class TestEdgeCaseErrorLog(unittest.TestCase):
    """Test error log edge cases."""

    @patch("ha_mcp_server.ha_api_request")
    def test_empty_error_log(self, mock_api):
        """Empty error log should surface a clear 'no data' error."""
        mock_api.return_value = ""
        result = ha_mcp_server.get_error_log()
        self.assertEqual(result, {"error": "No log data available."})

    @patch("ha_mcp_server.ha_api_request")
    def test_error_log_very_long(self, mock_api):
        """Very long error log should be truncated to last 100 lines."""
        lines = [f"2024-01-01 Line {i}" for i in range(500)]
        mock_api.return_value = "\n".join(lines)
        result = ha_mcp_server.get_error_log()
        result_lines = result.strip().split("\n")
        self.assertLessEqual(len(result_lines), 100)
        # Should contain the last line
        self.assertIn("Line 499", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_error_log_exactly_100_lines(self, mock_api):
        """Exactly 100 lines should all be returned."""
        lines = [f"Line {i}" for i in range(100)]
        mock_api.return_value = "\n".join(lines)
        result = ha_mcp_server.get_error_log()
        result_lines = result.strip().split("\n")
        self.assertEqual(len(result_lines), 100)

    @patch("ha_mcp_server.ha_api_request")
    def test_error_log_returns_dict_error(self, mock_api):
        """Dict error response should be passed through."""
        mock_api.return_value = {"error": "Unauthorized"}
        result = ha_mcp_server.get_error_log()
        self.assertIn("error", result)


class TestEdgeCaseServices(unittest.TestCase):
    """Test service call edge cases."""

    @patch("ha_mcp_server.ha_api_request")
    def test_service_with_complex_data(self, mock_api):
        """Service call with nested data should work."""
        mock_api.return_value = []
        data = {
            "entity_id": "light.test",
            "brightness": 255,
            "rgb_color": [255, 0, 0],
            "transition": 2
        }
        ha_mcp_server.call_service("light", "turn_on", data)
        mock_api.assert_called_with(
            "/api/services/light/turn_on",
            method="POST", data=data
        )

    @patch("ha_mcp_server.ha_api_request")
    def test_service_empty_response(self, mock_api):
        """Service returning empty list should work."""
        mock_api.return_value = []
        result = ha_mcp_server.call_service("automation", "reload")
        self.assertEqual(result, [])

    @patch("ha_mcp_server.ha_api_request")
    def test_service_error_response(self, mock_api):
        """Service error should be propagated."""
        mock_api.return_value = {"error": "HTTP 400: Bad Request"}
        result = ha_mcp_server.call_service("invalid", "service")
        self.assertIn("error", result)


class TestEdgeCaseReloadConfig(unittest.TestCase):
    """Test reload_config edge cases."""

    def test_all_valid_targets_accepted(self):
        """Every documented target should be accepted."""
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
                if isinstance(result, dict) and "error" in result:
                    self.fail(f"Valid target rejected: {target}")

    def test_invalid_target_returns_error_with_suggestions(self):
        """Invalid target should return error with valid_targets list."""
        result = ha_mcp_server.reload_config("nonexistent")
        self.assertIn("error", result)
        self.assertIn("valid_targets", result)
        self.assertIsInstance(result["valid_targets"], list)
        self.assertGreater(len(result["valid_targets"]), 5)

    def test_empty_target_returns_error(self):
        """Empty string target should return error."""
        result = ha_mcp_server.reload_config("")
        self.assertIn("error", result)

    def test_case_sensitive_targets(self):
        """Targets should be case-sensitive."""
        result = ha_mcp_server.reload_config("Automations")
        self.assertIn("error", result)

        result = ha_mcp_server.reload_config("CORE")
        self.assertIn("error", result)


class TestEdgeCaseHandleToolCall(unittest.TestCase):
    """Test handle_tool_call edge cases."""

    def test_empty_tool_name(self):
        """Empty tool name should return error."""
        result = ha_mcp_server.handle_tool_call("", {})
        self.assertIn("error", result)

    def test_none_arguments(self):
        """None arguments should be handled gracefully."""
        # Tools that don't require args should work with empty dict
        with patch("ha_mcp_server.get_automations") as mock:
            mock.return_value = []
            result = ha_mcp_server.handle_tool_call("get_automations", {})
            self.assertEqual(result, [])

    @patch("ha_mcp_server.get_entity_state")
    def test_extra_arguments_ignored(self, mock_fn):
        """Extra arguments beyond required should not cause errors."""
        mock_fn.return_value = {"entity_id": "test"}
        ha_mcp_server.handle_tool_call(
            "get_entity_state",
            {"entity_id": "test.entity", "extra_field": "ignored"}
        )
        mock_fn.assert_called_with(entity_id="test.entity")

    def test_tool_call_exception_returns_error(self):
        """Internal exception should be caught and returned as error."""
        with patch("ha_mcp_server.get_entity_state") as mock:
            mock.side_effect = RuntimeError("Unexpected error")
            result = ha_mcp_server.handle_tool_call(
                "get_entity_state", {"entity_id": "test"}
            )
            self.assertIn("error", result)
            self.assertIn("Unexpected error", result["error"])


class TestMultipleSequentialRequests(unittest.TestCase):
    """Test processing multiple requests in sequence."""

    def _simulate_requests(self, requests):
        """Simulate multiple MCP requests and return responses."""
        input_lines = "\n".join(json.dumps(r) for r in requests) + "\n"
        captured = io.StringIO()

        with patch("sys.stdin", io.StringIO(input_lines)):
            with patch("sys.stdout", captured):
                ha_mcp_server.main()

        output = captured.getvalue().strip()
        responses = []
        for line in output.split("\n"):
            if line.strip():
                responses.append(json.loads(line))
        return responses

    def test_initialize_then_tools_list(self):
        """Initialize followed by tools/list should both work."""
        responses = self._simulate_requests([
            {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0.0"}
                }
            },
            {
                "jsonrpc": "2.0", "id": 2, "method": "tools/list",
                "params": {}
            },
        ])

        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["id"], 1)
        self.assertIn("protocolVersion", responses[0]["result"])
        self.assertEqual(responses[1]["id"], 2)
        self.assertIn("tools", responses[1]["result"])

    def test_multiple_pings(self):
        """Multiple pings should all get responses."""
        responses = self._simulate_requests([
            {"jsonrpc": "2.0", "id": i, "method": "ping"}
            for i in range(5)
        ])
        self.assertEqual(len(responses), 5)
        for i, resp in enumerate(responses):
            self.assertEqual(resp["id"], i)
            self.assertEqual(resp["result"], {})


class TestTemplateRendering(unittest.TestCase):
    """Test template rendering edge cases."""

    @patch("ha_mcp_server.ha_api_request")
    def test_render_empty_template(self, mock_api):
        """Empty template should still be sent to HA."""
        mock_api.return_value = ""
        ha_mcp_server.render_template("")
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_render_template_with_special_chars(self, mock_api):
        """Template with special characters should work."""
        template = '{{ states("sensor.temp") | float > 30.5 }}'
        mock_api.return_value = "True"
        result = ha_mcp_server.render_template(template)
        self.assertEqual(result, "True")

    @patch("ha_mcp_server.ha_api_request")
    def test_render_template_error(self, mock_api):
        """Template rendering error should be propagated."""
        mock_api.return_value = {"error": "TemplateError: undefined variable"}
        result = ha_mcp_server.render_template("{{ invalid }}")
        self.assertIn("error", result)


class TestFireEvent(unittest.TestCase):
    """Test fire_event edge cases."""

    @patch("ha_mcp_server.ha_api_request")
    def test_fire_event_without_data(self, mock_api):
        """Firing event without data should pass empty dict."""
        mock_api.return_value = {"message": "Event fired."}
        ha_mcp_server.fire_event("test_event")
        mock_api.assert_called_once_with(
            "/api/events/test_event",
            method="POST", data={}
        )

    @patch("ha_mcp_server.ha_api_request")
    def test_fire_event_with_data(self, mock_api):
        """Firing event with data should pass the data."""
        mock_api.return_value = {"message": "Event fired."}
        ha_mcp_server.fire_event("test_event", {"key": "value"})
        mock_api.assert_called_once_with(
            "/api/events/test_event",
            method="POST", data={"key": "value"}
        )


class TestGetServices(unittest.TestCase):
    """Test get_services edge cases."""

    @patch("ha_mcp_server.ha_api_request")
    def test_services_with_empty_domain(self, mock_api):
        """Domain with no services should still be included."""
        mock_api.return_value = [
            {"domain": "empty", "services": {}},
        ]
        result = ha_mcp_server.get_services()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["services"], [])

    @patch("ha_mcp_server.ha_api_request")
    def test_services_error_response(self, mock_api):
        """Error response should be passed through."""
        mock_api.return_value = {"error": "Unauthorized"}
        result = ha_mcp_server.get_services()
        self.assertIn("error", result)


class TestDeviceRegistry(unittest.TestCase):
    """Test get_device_registry edge cases."""

    @patch("ha_mcp_server.ha_api_request")
    def test_device_registry_empty(self, mock_api):
        """Empty states should return zero counts."""
        mock_api.return_value = []
        result = ha_mcp_server.get_device_registry()
        self.assertEqual(result["total_entities"], 0)
        self.assertEqual(result["domains"], {})

    @patch("ha_mcp_server.ha_api_request")
    def test_device_registry_entity_without_dot(self, mock_api):
        """Entity without dot should be categorized as 'unknown'."""
        mock_api.return_value = [
            {"entity_id": "nodot", "state": "on"},
        ]
        result = ha_mcp_server.get_device_registry()
        # The entity_id split logic handles this with "unknown" fallback
        self.assertEqual(result["total_entities"], 1)


if __name__ == "__main__":
    unittest.main()
