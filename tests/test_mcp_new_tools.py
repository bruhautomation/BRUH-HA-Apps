#!/usr/bin/env python3
"""Tests for the 2.5.0 MCP additions: camera vision, history, statistics,
the schema-driven dispatcher contract, and image content envelopes."""

import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bruh-claude-terminal", "ha-mcp-server"))

import ha_mcp_server


class TestRegistryConsistency(unittest.TestCase):
    """The registry is the contract: schemas, implementations, and specs
    must always agree — this is what makes adding tools safe."""

    def test_every_tool_has_schema_and_implementation(self):
        schema_names = {t["name"] for t in ha_mcp_server.TOOLS}
        impl_names = set(ha_mcp_server.TOOL_IMPLEMENTATIONS)
        self.assertEqual(schema_names, impl_names)

    def test_every_implementation_function_exists(self):
        for fn_name in ha_mcp_server.TOOL_IMPLEMENTATIONS.values():
            self.assertTrue(
                callable(getattr(ha_mcp_server, fn_name, None)),
                f"missing implementation function: {fn_name}",
            )

    def test_schema_required_args_are_enforced(self):
        for schema in ha_mcp_server.TOOLS:
            required = schema.get("inputSchema", {}).get("required", [])
            if not required:
                continue
            result = ha_mcp_server.handle_tool_call(schema["name"], {})
            self.assertIn("error", result, f"{schema['name']} accepted empty args")
            self.assertIn("Missing required", result["error"])


class TestCameraSnapshot(unittest.TestCase):
    def test_rejects_non_camera_entity(self):
        result = ha_mcp_server.get_camera_snapshot("light.test")
        self.assertIn("error", result)

    @patch("ha_mcp_server.ha_api_request_raw")
    def test_returns_image_envelope(self, mock_raw):
        mock_raw.return_value = b"\xff\xd8\xff fake jpeg bytes"
        with patch.object(ha_mcp_server, "_PIL_AVAILABLE", False):
            result = ha_mcp_server.get_camera_snapshot("camera.driveway")
        self.assertIn("_mcp_image", result)
        self.assertEqual(result["_mcp_image"]["mimeType"], "image/jpeg")
        self.assertEqual(result["entity_id"], "camera.driveway")
        import base64
        self.assertEqual(
            base64.b64decode(result["_mcp_image"]["data"]),
            b"\xff\xd8\xff fake jpeg bytes",
        )

    @patch("ha_mcp_server.ha_api_request_raw")
    def test_empty_image_is_error(self, mock_raw):
        mock_raw.return_value = b""
        result = ha_mcp_server.get_camera_snapshot("camera.driveway")
        self.assertIn("error", result)

    @patch("ha_mcp_server.ha_api_request_raw")
    def test_oversized_image_is_error(self, mock_raw):
        mock_raw.return_value = b"x" * (2 * 1024 * 1024)
        with patch.object(ha_mcp_server, "_PIL_AVAILABLE", False):
            result = ha_mcp_server.get_camera_snapshot("camera.driveway")
        self.assertIn("error", result)
        self.assertIn("too large", result["error"])

    @patch("ha_mcp_server.ha_api_request_raw")
    def test_downscales_with_pillow(self, mock_raw):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        big = Image.new("RGB", (2000, 1500), color=(120, 30, 30))
        buf = io.BytesIO()
        big.save(buf, format="JPEG")
        mock_raw.return_value = buf.getvalue()

        result = ha_mcp_server.get_camera_snapshot("camera.driveway", max_dim=640)
        self.assertIn("_mcp_image", result)
        import base64
        out = Image.open(io.BytesIO(base64.b64decode(result["_mcp_image"]["data"])))
        self.assertLessEqual(max(out.size), 640)

    @patch("ha_mcp_server.ha_api_request_raw")
    def test_dispatch_routes_camera(self, mock_raw):
        mock_raw.return_value = b"\xff\xd8\xff tiny"
        with patch.object(ha_mcp_server, "_PIL_AVAILABLE", False):
            result = ha_mcp_server.handle_tool_call(
                "get_camera_snapshot", {"entity_id": "camera.front"}
            )
        self.assertIn("_mcp_image", result)


class TestImageEnvelope(unittest.TestCase):
    def test_text_results_unchanged(self):
        resp = ha_mcp_server.build_tool_response({"state": "on"})
        self.assertEqual(resp["content"][0]["type"], "text")
        self.assertNotIn("isError", resp)

    def test_error_results_flagged(self):
        resp = ha_mcp_server.build_tool_response({"error": "nope"})
        self.assertTrue(resp["isError"])

    def test_image_envelope_becomes_image_block(self):
        resp = ha_mcp_server.build_tool_response({
            "_mcp_image": {"data": "QUJD", "mimeType": "image/jpeg"},
            "entity_id": "camera.x",
        })
        self.assertEqual(resp["content"][0]["type"], "image")
        self.assertEqual(resp["content"][0]["data"], "QUJD")
        self.assertEqual(resp["content"][0]["mimeType"], "image/jpeg")
        # metadata rides along as a text block
        self.assertEqual(resp["content"][1]["type"], "text")
        self.assertIn("camera.x", resp["content"][1]["text"])
        self.assertNotIn("isError", resp)


class TestGetHistory(unittest.TestCase):
    @patch("ha_mcp_server.ha_api_request")
    def test_numeric_history_summary(self, mock_api):
        mock_api.return_value = [[
            {"state": "20.5", "last_changed": "2026-06-10T01:00:00Z"},
            {"state": "18.0", "last_changed": "2026-06-10T03:00:00Z"},
            {"state": "23.1", "last_changed": "2026-06-10T09:00:00Z"},
        ]]
        result = ha_mcp_server.get_history("sensor.outdoor_temp", hours=12)
        self.assertEqual(result["change_count"], 3)
        self.assertEqual(result["min"], 18.0)
        self.assertEqual(result["max"], 23.1)
        self.assertEqual(result["last"], "23.1")
        endpoint = mock_api.call_args[0][0]
        self.assertIn("filter_entity_id=sensor.outdoor_temp", endpoint)

    @patch("ha_mcp_server.ha_api_request")
    def test_hours_clamped(self, mock_api):
        mock_api.return_value = [[]]
        result = ha_mcp_server.get_history("sensor.x", hours=99999)
        self.assertEqual(result["hours"], 168)
        result = ha_mcp_server.get_history("sensor.x", hours="garbage")
        self.assertEqual(result["hours"], 24)

    @patch("ha_mcp_server.ha_api_request")
    def test_empty_history(self, mock_api):
        mock_api.return_value = []
        result = ha_mcp_server.get_history("sensor.x")
        self.assertEqual(result["changes"], [])
        self.assertIn("note", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_long_history_downsampled(self, mock_api):
        mock_api.return_value = [[
            {"state": str(i), "last_changed": f"t{i}"} for i in range(500)
        ]]
        result = ha_mcp_server.get_history("sensor.x")
        self.assertEqual(result["change_count"], 500)
        self.assertLessEqual(len(result["changes"]), 110)
        self.assertEqual(result["min"], 0.0)
        self.assertEqual(result["max"], 499.0)
        # the final point always survives downsampling
        self.assertEqual(result["changes"][-1]["state"], "499")

    @patch("ha_mcp_server.ha_api_request")
    def test_api_error_passthrough(self, mock_api):
        mock_api.return_value = {"error": "HTTP 500: boom"}
        result = ha_mcp_server.get_history("sensor.x")
        self.assertIn("error", result)


class TestGetStatistics(unittest.TestCase):
    @patch("ha_mcp_server._ws_command")
    def test_statistics_summary(self, mock_ws):
        mock_ws.return_value = {
            "sensor.outdoor_temp": [
                {"start": "2026-06-09T00:00:00Z", "mean": 21.0, "min": 15.0, "max": 28.0},
                {"start": "2026-06-10T00:00:00Z", "mean": 22.5, "min": 17.0, "max": 30.0},
            ]
        }
        result = ha_mcp_server.get_statistics("sensor.outdoor_temp", period="day", days=2)
        self.assertEqual(len(result["stats"]), 2)
        self.assertEqual(result["stats"][1]["max"], 30.0)
        payload = mock_ws.call_args[0][0]
        self.assertEqual(payload["type"], "recorder/statistics_during_period")
        self.assertEqual(payload["statistic_ids"], ["sensor.outdoor_temp"])
        self.assertEqual(payload["period"], "day")

    @patch("ha_mcp_server._ws_command")
    def test_invalid_period_defaults_to_hour(self, mock_ws):
        mock_ws.return_value = {}
        result = ha_mcp_server.get_statistics("sensor.x", period="fortnight")
        self.assertEqual(result["period"], "hour")

    @patch("ha_mcp_server._ws_command")
    def test_no_stats_note(self, mock_ws):
        mock_ws.return_value = {}
        result = ha_mcp_server.get_statistics("sensor.x")
        self.assertEqual(result["stats"], [])
        self.assertIn("state_class", result["note"])

    @patch("ha_mcp_server._ws_command")
    def test_ws_error_passthrough(self, mock_ws):
        mock_ws.return_value = {"error": "WebSocket auth failed"}
        result = ha_mcp_server.get_statistics("sensor.x")
        self.assertIn("error", result)

    @patch("ha_mcp_server._ws_command")
    def test_ws_exception_becomes_error(self, mock_ws):
        mock_ws.side_effect = OSError("connection refused")
        result = ha_mcp_server.get_statistics("sensor.x")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
