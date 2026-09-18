#!/usr/bin/env python3
"""Tests for the 2.5.0 MCP additions: camera vision, history, statistics,
the schema-driven dispatcher contract, and image content envelopes."""

import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server

try:
    from PIL import Image
except ImportError:  # Pillow is optional; the test that needs it skips
    Image = None


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

    @unittest.skipIf(Image is None, "Pillow not installed")
    @patch("ha_mcp_server.ha_api_request_raw")
    def test_downscales_with_pillow(self, mock_raw):
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


class TestGetWeatherForecast(unittest.TestCase):
    def test_rejects_non_weather_entity(self):
        result = ha_mcp_server.get_weather_forecast("sensor.outdoor")
        self.assertIn("error", result)

    @patch("ha_mcp_server._ws_command")
    def test_forecast_trimmed_and_shaped(self, mock_ws):
        mock_ws.return_value = {
            "context": {"id": "x"},
            "response": {
                "weather.home": {
                    "forecast": [
                        {"datetime": "2026-06-12T00:00:00Z", "condition": "sunny",
                         "temperature": 90, "templow": 73,
                         "precipitation": 0.0, "precipitation_probability": 0,
                         "wind_bearing": 220, "uv_index": 7},
                        {"datetime": "2026-06-13T00:00:00Z", "condition": "rainy",
                         "temperature": 81, "templow": 70,
                         "precipitation": 0.4, "precipitation_probability": 80},
                    ]
                }
            },
        }
        result = ha_mcp_server.get_weather_forecast("weather.home")
        payload = mock_ws.call_args[0][0]
        self.assertEqual(payload["service"], "get_forecasts")
        self.assertTrue(payload["return_response"])
        self.assertEqual(payload["service_data"], {"type": "daily"})
        self.assertEqual(len(result["forecast"]), 2)
        day_one = result["forecast"][0]
        self.assertEqual(day_one["condition"], "sunny")
        # noisy fields are dropped, zero-values kept
        self.assertNotIn("wind_bearing", day_one)
        self.assertNotIn("uv_index", day_one)
        self.assertEqual(day_one["precipitation"], 0.0)

    @patch("ha_mcp_server._ws_command")
    def test_invalid_type_defaults_to_daily(self, mock_ws):
        mock_ws.return_value = {"response": {"weather.home": {"forecast": [
            {"datetime": "t0", "temperature": 20}
        ]}}}
        result = ha_mcp_server.get_weather_forecast("weather.home", "fortnightly")
        self.assertEqual(result["type"], "daily")
        first_call = mock_ws.call_args_list[0][0][0]
        self.assertEqual(first_call["service_data"]["type"], "daily")

    @patch("ha_mcp_server._ws_command")
    def test_falls_back_to_supported_type(self, mock_ws):
        """An hourly-only entity (e.g. weather.krdu) must not hard-error on
        the daily default — the tool falls back to what the entity supports."""
        def per_type(cmd, **kwargs):
            if cmd["service_data"]["type"] == "hourly":
                return {"response": {"weather.krdu": {"forecast": [
                    {"datetime": "t0", "temperature": 20}
                ]}}}
            return {"error": "Weather entity does not support daily forecast"}

        mock_ws.side_effect = per_type
        result = ha_mcp_server.get_weather_forecast("weather.krdu")
        self.assertEqual(result["type"], "hourly")
        self.assertIn("note", result)
        self.assertNotIn("error", result)

    @patch("ha_mcp_server._ws_command")
    def test_hourly_capped_at_24(self, mock_ws):
        mock_ws.return_value = {"response": {"weather.home": {"forecast": [
            {"datetime": f"t{i}", "temperature": i} for i in range(72)
        ]}}}
        result = ha_mcp_server.get_weather_forecast("weather.home", "hourly")
        self.assertEqual(len(result["forecast"]), 24)

    @patch("ha_mcp_server._ws_command")
    def test_ws_error_passthrough(self, mock_ws):
        mock_ws.return_value = {"error": "WebSocket auth failed"}
        result = ha_mcp_server.get_weather_forecast("weather.home")
        self.assertIn("error", result)


class TestServiceDenyList(unittest.TestCase):
    """Per-agent service deny-list enforced at the call_service chokepoint."""

    def setUp(self):
        self._saved = ha_mcp_server.DENIED_SERVICES

    def tearDown(self):
        ha_mcp_server.DENIED_SERVICES = self._saved

    def test_pattern_matching(self):
        ha_mcp_server.DENIED_SERVICES = ["lock.unlock", "alarm_control_panel.*"]
        self.assertTrue(ha_mcp_server._service_denied("lock", "unlock"))
        self.assertFalse(ha_mcp_server._service_denied("lock", "lock"))
        self.assertTrue(ha_mcp_server._service_denied("alarm_control_panel", "alarm_disarm"))
        self.assertTrue(ha_mcp_server._service_denied("ALARM_CONTROL_PANEL", "alarm_arm_away"))
        self.assertFalse(ha_mcp_server._service_denied("light", "turn_on"))

    def test_wildcard_all(self):
        ha_mcp_server.DENIED_SERVICES = ["*"]
        self.assertTrue(ha_mcp_server._service_denied("light", "turn_on"))

    @patch("ha_mcp_server.ha_api_request")
    def test_call_service_blocks_denied(self, mock_api):
        ha_mcp_server.DENIED_SERVICES = ["lock.unlock"]
        result = ha_mcp_server.call_service("lock", "unlock", {"entity_id": "lock.front"})
        self.assertIn("error", result)
        self.assertIn("not permitted", result["error"])
        mock_api.assert_not_called()  # never hit the HA API

    @patch("ha_mcp_server.ha_api_request")
    def test_call_service_allows_others(self, mock_api):
        ha_mcp_server.DENIED_SERVICES = ["lock.unlock"]
        mock_api.return_value = {"ok": True}
        ha_mcp_server.call_service("light", "turn_on", {"entity_id": "light.x"})
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_control_tool_routes_through_deny(self, mock_api):
        """control_lock(unlock) must be blocked by a lock.unlock deny —
        proving the chokepoint covers the dedicated control_* tools."""
        ha_mcp_server.DENIED_SERVICES = ["lock.*"]
        result = ha_mcp_server.control_lock("lock.front", "unlock")
        self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_meta_service_cannot_bypass_an_entity_denial(self, mock_api):
        """homeassistant.turn_on forwards to the target entity's own domain
        service, so a cover.open_cover denial has to catch the same action
        wearing the meta-service's name — this was the bypass."""
        ha_mcp_server.DENIED_SERVICES = ["cover.open_cover"]
        for service, payload in (
            ("turn_on", {"entity_id": "cover.garage_door"}),
            ("turn_on", {"entity_id": ["light.x", "cover.garage_door"]}),
            ("toggle", {"target": {"entity_id": "cover.garage_door"}}),
            ("turn_on", {"entity_id": "light.x, cover.garage_door"}),
        ):
            result = ha_mcp_server.call_service(
                "homeassistant", service, payload)
            self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_meta_service_on_unrestricted_entities_still_works(self, mock_api):
        ha_mcp_server.DENIED_SERVICES = ["cover.open_cover"]
        mock_api.return_value = {"ok": True}
        ha_mcp_server.call_service(
            "homeassistant", "turn_on",
            {"entity_id": ["light.x", "switch.y"]})
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_meta_service_with_unresolvable_targets_fails_closed(self, mock_api):
        """Area/device/label targets and the no-target/"all" forms resolve
        to entities inside HA where the deny-list cannot see them — a
        restricted channel refuses rather than guesses."""
        ha_mcp_server.DENIED_SERVICES = ["cover.open_cover"]
        for payload in (
            {"area_id": "garage"},
            {"target": {"device_id": "abc123"}},
            {"entity_id": "all"},
            {},
            None,
        ):
            result = ha_mcp_server.call_service(
                "homeassistant", "turn_off", payload)
            self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_meta_service_untouched_without_restrictions(self, mock_api):
        ha_mcp_server.DENIED_SERVICES = []
        mock_api.return_value = {"ok": True}
        ha_mcp_server.call_service("homeassistant", "turn_off",
                                   {"entity_id": "light.x"})
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_fire_event_is_refused_on_a_restricted_channel(self, mock_api):
        """An event can trigger any automation — including one doing exactly
        what the deny-list forbids — and event names match no service
        pattern, so a restricted channel gets no events at all."""
        ha_mcp_server.DENIED_SERVICES = ["lock.unlock"]
        result = ha_mcp_server.fire_event("custom_event", {"x": 1})
        self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_fire_event_still_works_unrestricted(self, mock_api):
        ha_mcp_server.DENIED_SERVICES = []
        mock_api.return_value = {"ok": True}
        ha_mcp_server.fire_event("custom_event")
        mock_api.assert_called_once()


class TestThePanelsOwnListAndVerdict(unittest.TestCase):
    """`get_findings` and `get_health` read the panel over loopback — one
    implementation, one answer — and trim the page of JSON each answers
    with to what a run can act on. A panel that is not up is reported as
    such, never as a house with nothing wrong or an add-on that is fine."""

    FINDINGS = {
        "open": 2,
        "findings": [
            {"ts": 1, "severity": "serious", "text": "Hose Reel is unavailable",
             "detail": "Since 16 Sep", "fix": "Power-cycle the Tuya hub",
             "fix_by": "triage", "entity_id": "valve.hose_reel",
             "source_title": "Device check", "status": "open",
             "fixable": False, "run_id": "abc", "snoozed_until": 0,
             "triage": {"verdict": "elevated", "reason": "the hub is down",
                        "run_id": "r1"}},
            {"ts": 2, "severity": "warning", "text": "A cupboard contact",
             "status": "held", "triage": {"verdict": "held",
                                          "reason": "nobody opens it"}},
            {"ts": 3, "severity": "info", "text": "Being fixed",
             "status": "fixing"},
        ],
        "hypotheses": [{"ts": 9, "claim": "The garage is heated"}],
        "settled": [{"key": "secret bookkeeping"}],
    }

    @patch("ha_mcp_server._panel_get")
    def test_open_is_the_list_a_person_sees(self, panel):
        panel.return_value = self.FINDINGS
        out = ha_mcp_server.get_findings()
        panel.assert_called_once_with("/api/findings")
        self.assertEqual(out["open"], 2)
        self.assertEqual([f["ts"] for f in out["findings"]], [1, 3])
        first = out["findings"][0]
        self.assertEqual(first["fix"], "Power-cycle the Tuya hub")
        self.assertEqual(first["looked"], "the hub is down")
        # Bookkeeping stays behind: no run id, no snooze stamp, no ledger.
        self.assertNotIn("run_id", first)
        self.assertNotIn("snoozed_until", first)
        self.assertNotIn("settled", out)
        self.assertEqual(out["hypotheses"], [{"ts": 9, "claim": "The garage is heated"}])

    @patch("ha_mcp_server._panel_get")
    def test_held_is_what_a_look_decided_not_to_show(self, panel):
        panel.return_value = self.FINDINGS
        out = ha_mcp_server.get_findings(status="held")
        self.assertEqual([f["ts"] for f in out["findings"]], [2])
        self.assertEqual(len(ha_mcp_server.get_findings(status="all")["findings"]), 3)
        self.assertIn("error", ha_mcp_server.get_findings(status="everything"))

    @patch("ha_mcp_server._panel_get")
    def test_a_panel_that_is_down_is_not_a_quiet_house(self, panel):
        panel.return_value = {"error": "the brAIn panel did not answer: refused"}
        self.assertIn("error", ha_mcp_server.get_findings())
        self.assertIn("error", ha_mcp_server.get_health())

    @patch("ha_mcp_server._panel_get")
    def test_health_is_the_verdict_and_the_switch(self, panel):
        panel.return_value = {
            "health": {"state": "degraded", "reason": "usage figures are "
                       "not being reported", "fix": "Press the pill",
                       "problems": [{"id": "usage", "state": "degraded",
                                     "reason": "r", "fix": "f", "noise": 1}]},
            "auth": {"state": "ok"},
            "usage": {"source": "estimate", "limits": {"code": "http_401"}},
            "daemons": {"ttyd": {"running": True},
                        "usage_tracker": {"running": False}},
            "versions": {"addon": "1.60.0"},
            "journal_tail": [{"huge": "payload"}] * 30,
            "faults": [{"where": "Usage figures", "what": "x"}],
        }
        out = ha_mcp_server.get_health()
        panel.assert_called_once_with("/api/diagnostics")
        self.assertEqual(out["state"], "degraded")
        self.assertEqual(out["fix"], "Press the pill")
        self.assertEqual(out["problems"], [{"id": "usage", "state": "degraded",
                                            "reason": "r", "fix": "f"}])
        self.assertEqual(out["signed_in"], "ok")
        self.assertEqual(out["usage"]["limits"]["code"], "http_401")
        self.assertEqual(out["daemons"], {"ttyd": True, "usage_tracker": False})
        self.assertNotIn("journal_tail", out)

    def test_both_are_read_only_tools_the_analyst_may_use(self):
        import importlib
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))
        try:
            engine = importlib.import_module("engine")
        finally:
            sys.path.pop(0)
        for name in ("get_findings", "get_health"):
            self.assertIn(name, ha_mcp_server.TOOL_IMPLEMENTATIONS)
            self.assertIn(f"{engine.MCP}{name}", engine.ANALYST_TOOLS)
            self.assertNotIn(f"{engine.MCP}{name}", engine.ANALYST_DENIED)
