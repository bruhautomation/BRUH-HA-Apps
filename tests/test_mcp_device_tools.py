#!/usr/bin/env python3
"""
Tests for the domain-specific device control MCP tools.

Tests cover:
- control_light: turn on/off, brightness, RGB color, color temp, effects
- control_climate: temperature, HVAC mode, fan mode, presets
- control_media_player: play/pause, volume, source, media playback
- control_cover: open/close, position, tilt
- control_fan: speed, preset mode, direction, oscillation
- control_switch: on/off/toggle for switches
- control_lock: lock/unlock with codes
- control_alarm: arm/disarm with codes
- control_vacuum: start/stop/return home
- send_notification: persistent and targeted notifications
- activate_scene: scene activation with transition
- run_script: script execution with variables
- get_service_details: dynamic schema lookup
- handle_tool_call routing for all new tools
"""

import json
import os
import sys
import unittest
from unittest.mock import patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bruh-claude-terminal", "ha-mcp-server"))

import ha_mcp_server


class TestControlLight(unittest.TestCase):
    """Test the control_light tool."""

    @patch("ha_mcp_server.call_service")
    def test_turn_on_basic(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.living_room", "turn_on")
        mock_svc.assert_called_once_with("light", "turn_on", {"entity_id": "light.living_room"})

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_brightness(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.living_room", "turn_on", brightness=128)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["brightness"], 128)

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_brightness_pct(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.living_room", "turn_on", brightness_pct=50)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["brightness_pct"], 50)

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_rgb_color(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.strip", "turn_on", rgb_color=[255, 0, 0])
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["rgb_color"], [255, 0, 0])

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_hs_color(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.strip", "turn_on", hs_color=[240, 100])
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["hs_color"], [240, 100])

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_xy_color(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.strip", "turn_on", xy_color=[0.3, 0.5])
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["xy_color"], [0.3, 0.5])

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_color_temp_kelvin(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.lamp", "turn_on", color_temp_kelvin=4000)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["color_temp_kelvin"], 4000)

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_color_name(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.lamp", "turn_on", color_name="red")
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["color_name"], "red")

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_effect(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.strip", "turn_on", effect="colorloop")
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["effect"], "colorloop")

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_transition(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.lamp", "turn_on", transition=2.5)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["transition"], 2.5)

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_flash(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.lamp", "turn_on", flash="short")
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["flash"], "short")

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_white(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.rgbw", "turn_on", white=200)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["white"], 200)

    @patch("ha_mcp_server.call_service")
    def test_turn_on_multiple_params(self, mock_svc):
        """Turn on with brightness + color + transition combined."""
        mock_svc.return_value = []
        ha_mcp_server.control_light(
            "light.strip", "turn_on",
            brightness=200, rgb_color=[0, 255, 0], transition=1
        )
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["brightness"], 200)
        self.assertEqual(data["rgb_color"], [0, 255, 0])
        self.assertEqual(data["transition"], 1)

    @patch("ha_mcp_server.call_service")
    def test_turn_off(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.lamp", "turn_off")
        mock_svc.assert_called_once_with("light", "turn_off", {"entity_id": "light.lamp"})

    @patch("ha_mcp_server.call_service")
    def test_turn_off_with_transition(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.lamp", "turn_off", transition=5)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["transition"], 5)

    @patch("ha_mcp_server.call_service")
    def test_toggle(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_light("light.lamp", "toggle")
        mock_svc.assert_called_once_with("light", "toggle", {"entity_id": "light.lamp"})


class TestControlClimate(unittest.TestCase):
    """Test the control_climate tool."""

    @patch("ha_mcp_server.call_service")
    def test_set_temperature(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.thermostat", "set_temperature", temperature=72)
        mock_svc.assert_called_once_with("climate", "set_temperature", {
            "entity_id": "climate.thermostat", "temperature": 72
        })

    @patch("ha_mcp_server.call_service")
    def test_set_temperature_range(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate(
            "climate.thermostat", "set_temperature",
            target_temp_high=78, target_temp_low=68
        )
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["target_temp_high"], 78)
        self.assertEqual(data["target_temp_low"], 68)

    @patch("ha_mcp_server.call_service")
    def test_set_hvac_mode(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.thermostat", "set_hvac_mode", hvac_mode="cool")
        mock_svc.assert_called_once_with("climate", "set_hvac_mode", {
            "entity_id": "climate.thermostat", "hvac_mode": "cool"
        })

    @patch("ha_mcp_server.call_service")
    def test_set_fan_mode(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.thermostat", "set_fan_mode", fan_mode="auto")
        mock_svc.assert_called_once_with("climate", "set_fan_mode", {
            "entity_id": "climate.thermostat", "fan_mode": "auto"
        })

    @patch("ha_mcp_server.call_service")
    def test_set_preset_mode(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.thermostat", "set_preset_mode", preset_mode="away")
        mock_svc.assert_called_once_with("climate", "set_preset_mode", {
            "entity_id": "climate.thermostat", "preset_mode": "away"
        })

    @patch("ha_mcp_server.call_service")
    def test_set_humidity(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.thermostat", "set_humidity", humidity=45)
        mock_svc.assert_called_once_with("climate", "set_humidity", {
            "entity_id": "climate.thermostat", "humidity": 45
        })

    @patch("ha_mcp_server.call_service")
    def test_set_swing_mode(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.ac", "set_swing_mode", swing_mode="vertical")
        mock_svc.assert_called_once_with("climate", "set_swing_mode", {
            "entity_id": "climate.ac", "swing_mode": "vertical"
        })

    @patch("ha_mcp_server.call_service")
    def test_turn_on(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.thermostat", "turn_on")
        mock_svc.assert_called_once_with("climate", "turn_on", {"entity_id": "climate.thermostat"})

    @patch("ha_mcp_server.call_service")
    def test_turn_off(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_climate("climate.thermostat", "turn_off")
        mock_svc.assert_called_once_with("climate", "turn_off", {"entity_id": "climate.thermostat"})


class TestControlMediaPlayer(unittest.TestCase):
    """Test the control_media_player tool."""

    @patch("ha_mcp_server.call_service")
    def test_play(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "play")
        mock_svc.assert_called_once_with("media_player", "media_play", {"entity_id": "media_player.sonos"})

    @patch("ha_mcp_server.call_service")
    def test_pause(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "pause")
        mock_svc.assert_called_once_with("media_player", "media_pause", {"entity_id": "media_player.sonos"})

    @patch("ha_mcp_server.call_service")
    def test_stop(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "stop")
        mock_svc.assert_called_once_with("media_player", "media_stop", {"entity_id": "media_player.sonos"})

    @patch("ha_mcp_server.call_service")
    def test_next_track(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "next")
        mock_svc.assert_called_once_with("media_player", "media_next_track", {"entity_id": "media_player.sonos"})

    @patch("ha_mcp_server.call_service")
    def test_set_volume(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "set_volume", volume_level=0.5)
        mock_svc.assert_called_once_with("media_player", "volume_set", {
            "entity_id": "media_player.sonos", "volume_level": 0.5
        })

    @patch("ha_mcp_server.call_service")
    def test_select_source(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.tv", "select_source", source="HDMI 1")
        mock_svc.assert_called_once_with("media_player", "select_source", {
            "entity_id": "media_player.tv", "source": "HDMI 1"
        })

    @patch("ha_mcp_server.call_service")
    def test_play_media(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player(
            "media_player.sonos", "play_media",
            media_content_id="spotify:track:123", media_content_type="music"
        )
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["media_content_id"], "spotify:track:123")
        self.assertEqual(data["media_content_type"], "music")

    @patch("ha_mcp_server.call_service")
    def test_volume_mute(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "volume_mute")
        data = mock_svc.call_args[0][2]
        self.assertTrue(data["is_volume_muted"])

    @patch("ha_mcp_server.call_service")
    def test_volume_unmute(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "volume_unmute")
        data = mock_svc.call_args[0][2]
        self.assertFalse(data["is_volume_muted"])

    @patch("ha_mcp_server.call_service")
    def test_set_shuffle(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "set_shuffle", shuffle=True)
        mock_svc.assert_called_once_with("media_player", "shuffle_set", {
            "entity_id": "media_player.sonos", "shuffle": True
        })

    @patch("ha_mcp_server.call_service")
    def test_set_repeat(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_media_player("media_player.sonos", "set_repeat", repeat="all")
        mock_svc.assert_called_once_with("media_player", "repeat_set", {
            "entity_id": "media_player.sonos", "repeat": "all"
        })

    def test_unknown_action_returns_error(self):
        result = ha_mcp_server.control_media_player("media_player.test", "nonexistent")
        self.assertIn("error", result)


class TestControlCover(unittest.TestCase):
    """Test the control_cover tool."""

    @patch("ha_mcp_server.call_service")
    def test_open(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_cover("cover.garage", "open")
        mock_svc.assert_called_once_with("cover", "open_cover", {"entity_id": "cover.garage"})

    @patch("ha_mcp_server.call_service")
    def test_close(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_cover("cover.garage", "close")
        mock_svc.assert_called_once_with("cover", "close_cover", {"entity_id": "cover.garage"})

    @patch("ha_mcp_server.call_service")
    def test_stop(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_cover("cover.blinds", "stop")
        mock_svc.assert_called_once_with("cover", "stop_cover", {"entity_id": "cover.blinds"})

    @patch("ha_mcp_server.call_service")
    def test_set_position(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_cover("cover.blinds", "set_position", position=50)
        mock_svc.assert_called_once_with("cover", "set_cover_position", {
            "entity_id": "cover.blinds", "position": 50
        })

    @patch("ha_mcp_server.call_service")
    def test_set_tilt(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_cover("cover.blinds", "set_tilt", tilt_position=75)
        mock_svc.assert_called_once_with("cover", "set_cover_tilt_position", {
            "entity_id": "cover.blinds", "tilt_position": 75
        })

    def test_unknown_action_returns_error(self):
        result = ha_mcp_server.control_cover("cover.test", "nonexistent")
        self.assertIn("error", result)


class TestControlFan(unittest.TestCase):
    """Test the control_fan tool."""

    @patch("ha_mcp_server.call_service")
    def test_turn_on(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_fan("fan.bedroom", "turn_on")
        mock_svc.assert_called_once_with("fan", "turn_on", {"entity_id": "fan.bedroom"})

    @patch("ha_mcp_server.call_service")
    def test_turn_on_with_speed(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_fan("fan.bedroom", "turn_on", percentage=75)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["percentage"], 75)

    @patch("ha_mcp_server.call_service")
    def test_set_percentage(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_fan("fan.bedroom", "set_percentage", percentage=50)
        mock_svc.assert_called_once_with("fan", "set_percentage", {
            "entity_id": "fan.bedroom", "percentage": 50
        })

    @patch("ha_mcp_server.call_service")
    def test_set_direction(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_fan("fan.ceiling", "set_direction", direction="reverse")
        mock_svc.assert_called_once_with("fan", "set_direction", {
            "entity_id": "fan.ceiling", "direction": "reverse"
        })

    @patch("ha_mcp_server.call_service")
    def test_oscillate(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_fan("fan.desk", "oscillate", oscillating=True)
        mock_svc.assert_called_once_with("fan", "oscillate", {
            "entity_id": "fan.desk", "oscillating": True
        })

    def test_unknown_action_returns_error(self):
        result = ha_mcp_server.control_fan("fan.test", "nonexistent")
        self.assertIn("error", result)


class TestControlSwitch(unittest.TestCase):
    """Test the control_switch tool."""

    @patch("ha_mcp_server.call_service")
    def test_turn_on_switch(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_switch("switch.heater", "turn_on")
        mock_svc.assert_called_once_with("switch", "turn_on", {"entity_id": "switch.heater"})

    @patch("ha_mcp_server.call_service")
    def test_toggle_input_boolean(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_switch("input_boolean.guest_mode", "toggle")
        mock_svc.assert_called_once_with("input_boolean", "toggle", {"entity_id": "input_boolean.guest_mode"})

    def test_unknown_action_returns_error(self):
        result = ha_mcp_server.control_switch("switch.test", "nonexistent")
        self.assertIn("error", result)


class TestControlLock(unittest.TestCase):
    """Test the control_lock tool."""

    @patch("ha_mcp_server.call_service")
    def test_lock(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_lock("lock.front_door", "lock")
        mock_svc.assert_called_once_with("lock", "lock", {"entity_id": "lock.front_door"})

    @patch("ha_mcp_server.call_service")
    def test_unlock_with_code(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_lock("lock.front_door", "unlock", code="1234")
        mock_svc.assert_called_once_with("lock", "unlock", {
            "entity_id": "lock.front_door", "code": "1234"
        })

    def test_unknown_action_returns_error(self):
        result = ha_mcp_server.control_lock("lock.test", "nonexistent")
        self.assertIn("error", result)


class TestControlAlarm(unittest.TestCase):
    """Test the control_alarm tool."""

    @patch("ha_mcp_server.call_service")
    def test_arm_away(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_alarm("alarm_control_panel.home", "arm_away", code="1234")
        mock_svc.assert_called_once_with("alarm_control_panel", "alarm_arm_away", {
            "entity_id": "alarm_control_panel.home", "code": "1234"
        })

    @patch("ha_mcp_server.call_service")
    def test_disarm(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_alarm("alarm_control_panel.home", "disarm", code="1234")
        mock_svc.assert_called_once_with("alarm_control_panel", "alarm_disarm", {
            "entity_id": "alarm_control_panel.home", "code": "1234"
        })

    @patch("ha_mcp_server.call_service")
    def test_arm_home_no_code(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_alarm("alarm_control_panel.home", "arm_home")
        mock_svc.assert_called_once_with("alarm_control_panel", "alarm_arm_home", {
            "entity_id": "alarm_control_panel.home"
        })

    def test_unknown_action_returns_error(self):
        result = ha_mcp_server.control_alarm("alarm_control_panel.test", "nonexistent")
        self.assertIn("error", result)


class TestControlVacuum(unittest.TestCase):
    """Test the control_vacuum tool."""

    @patch("ha_mcp_server.call_service")
    def test_start(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_vacuum("vacuum.roborock", "start")
        mock_svc.assert_called_once_with("vacuum", "start", {"entity_id": "vacuum.roborock"})

    @patch("ha_mcp_server.call_service")
    def test_return_home(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_vacuum("vacuum.roborock", "return_home")
        mock_svc.assert_called_once_with("vacuum", "return_to_base", {"entity_id": "vacuum.roborock"})

    @patch("ha_mcp_server.call_service")
    def test_send_command(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_vacuum("vacuum.roborock", "send_command", command="app_goto_target", params={"x": 100, "y": 200})
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["command"], "app_goto_target")
        self.assertEqual(data["params"], {"x": 100, "y": 200})

    @patch("ha_mcp_server.call_service")
    def test_set_fan_speed(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.control_vacuum("vacuum.roborock", "set_fan_speed", command="turbo")
        mock_svc.assert_called_once_with("vacuum", "set_fan_speed", {
            "entity_id": "vacuum.roborock", "fan_speed": "turbo"
        })

    def test_unknown_action_returns_error(self):
        result = ha_mcp_server.control_vacuum("vacuum.test", "nonexistent")
        self.assertIn("error", result)


class TestSendNotification(unittest.TestCase):
    """Test the send_notification tool."""

    @patch("ha_mcp_server.call_service")
    def test_persistent_notification(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.send_notification("Hello!")
        mock_svc.assert_called_once_with("persistent_notification", "create", {"message": "Hello!"})

    @patch("ha_mcp_server.call_service")
    def test_persistent_with_title(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.send_notification("Test body", title="Test Title")
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["message"], "Test body")
        self.assertEqual(data["title"], "Test Title")
        self.assertEqual(data["notification_id"], "test_title")

    @patch("ha_mcp_server.call_service")
    def test_targeted_notification(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.send_notification("Hello!", target="mobile_app_phone")
        mock_svc.assert_called_once_with("notify", "mobile_app_phone", {"message": "Hello!"})

    @patch("ha_mcp_server.call_service")
    def test_with_extra_data(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.send_notification("Photo!", target="mobile_app_phone", data={"image": "/local/cam.jpg"})
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["data"]["image"], "/local/cam.jpg")


class TestActivateScene(unittest.TestCase):
    """Test the activate_scene tool."""

    @patch("ha_mcp_server.call_service")
    def test_basic_activation(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.activate_scene("scene.movie_night")
        mock_svc.assert_called_once_with("scene", "turn_on", {"entity_id": "scene.movie_night"})

    @patch("ha_mcp_server.call_service")
    def test_with_transition(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.activate_scene("scene.relax", transition=3)
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["transition"], 3)


class TestRunScript(unittest.TestCase):
    """Test the run_script tool."""

    @patch("ha_mcp_server.call_service")
    def test_basic_run(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.run_script("script.morning_routine")
        mock_svc.assert_called_once_with("script", "turn_on", {"entity_id": "script.morning_routine"})

    @patch("ha_mcp_server.call_service")
    def test_with_variables(self, mock_svc):
        mock_svc.return_value = []
        ha_mcp_server.run_script("script.set_room", variables={"room": "bedroom", "brightness": 80})
        data = mock_svc.call_args[0][2]
        self.assertEqual(data["variables"]["room"], "bedroom")


class TestGetServiceDetails(unittest.TestCase):
    """Test the get_service_details tool."""

    @patch("ha_mcp_server.ha_api_request")
    def test_returns_matching_domain(self, mock_api):
        mock_api.return_value = [
            {"domain": "light", "services": {"turn_on": {"fields": {"brightness": {}}}}},
            {"domain": "switch", "services": {"turn_on": {}}},
        ]
        result = ha_mcp_server.get_service_details("light")
        self.assertEqual(result["domain"], "light")
        self.assertIn("turn_on", result["services"])

    @patch("ha_mcp_server.ha_api_request")
    def test_returns_error_for_missing_domain(self, mock_api):
        mock_api.return_value = [
            {"domain": "light", "services": {}},
        ]
        result = ha_mcp_server.get_service_details("nonexistent")
        self.assertIn("error", result)

    @patch("ha_mcp_server.ha_api_request")
    def test_api_error_passed_through(self, mock_api):
        mock_api.return_value = {"error": "Unauthorized"}
        result = ha_mcp_server.get_service_details("light")
        self.assertIn("error", result)


class TestHandleToolCallRouting(unittest.TestCase):
    """Test that handle_tool_call correctly routes to all new tools."""

    @patch("ha_mcp_server.control_light")
    def test_routes_control_light(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_light", {
            "entity_id": "light.test", "action": "turn_on", "brightness": 128
        })
        mock_fn.assert_called_once()
        kwargs = {k: v for k, v in zip(mock_fn.call_args[1].keys(), mock_fn.call_args[1].values())} if mock_fn.call_args[1] else {}
        # Check it was called with the right entity
        args = mock_fn.call_args
        self.assertEqual(args[1]["entity_id"], "light.test")
        self.assertEqual(args[1]["action"], "turn_on")
        self.assertEqual(args[1]["brightness"], 128)

    @patch("ha_mcp_server.control_climate")
    def test_routes_control_climate(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_climate", {
            "entity_id": "climate.test", "action": "set_temperature", "temperature": 72
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.control_media_player")
    def test_routes_control_media_player(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_media_player", {
            "entity_id": "media_player.test", "action": "play"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.control_cover")
    def test_routes_control_cover(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_cover", {
            "entity_id": "cover.test", "action": "open"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.control_fan")
    def test_routes_control_fan(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_fan", {
            "entity_id": "fan.test", "action": "turn_on"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.control_switch")
    def test_routes_control_switch(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_switch", {
            "entity_id": "switch.test", "action": "toggle"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.control_lock")
    def test_routes_control_lock(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_lock", {
            "entity_id": "lock.test", "action": "lock"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.control_alarm")
    def test_routes_control_alarm(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_alarm", {
            "entity_id": "alarm_control_panel.test", "action": "arm_away"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.control_vacuum")
    def test_routes_control_vacuum(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("control_vacuum", {
            "entity_id": "vacuum.test", "action": "start"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.send_notification")
    def test_routes_send_notification(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("send_notification", {
            "message": "Hello!", "title": "Test"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.activate_scene")
    def test_routes_activate_scene(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("activate_scene", {
            "entity_id": "scene.test"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.run_script")
    def test_routes_run_script(self, mock_fn):
        mock_fn.return_value = []
        ha_mcp_server.handle_tool_call("run_script", {
            "entity_id": "script.test"
        })
        mock_fn.assert_called_once()

    @patch("ha_mcp_server.get_service_details")
    def test_routes_get_service_details(self, mock_fn):
        mock_fn.return_value = {"domain": "light"}
        ha_mcp_server.handle_tool_call("get_service_details", {"domain": "light"})
        mock_fn.assert_called_once_with(domain="light")


if __name__ == "__main__":
    unittest.main()
