#!/usr/bin/env python3
"""What the MCP server costs a conversation before it has done anything.

Every channel — voice included — was sent all 84 tool schemas (about 52 KB)
on every turn, when about forty of them always refuse on a voice-level
agent; every result was `indent=2`, a fifth to a third larger than it needs
to be; `get_device_registry` returned per-domain entity counts under a name
that promised the device registry; and with Claude Code deferring MCP tools
behind tool search by default, a voice worker told to act in its FIRST
response had to spend a ToolSearch turn loading the control schema first,
with no server instructions to search by.

The voice half is driven as the process it is: the server is started with
the environment the worker pool gives it and spoken to over stdin, because
"EXPOSED_ONLY was set on the module in a test" and "the voice process
offers this list" are different claims and only the second is what a
satellite pays for.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SERVER_DIR = Path(__file__).resolve().parent.parent / "brain" / "ha-mcp-server"
sys.path.insert(0, str(SERVER_DIR))

import ha_mcp_server as m  # noqa: E402


def talk(env_extra, *requests):
    """Start the server like Claude Code does and read its answers."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("BRAIN_") and k != "CLAUDE_CODE_SESSION_ID"}
    env.update(env_extra)
    lines = "".join(json.dumps(r) + "\n" for r in requests)
    proc = subprocess.run([sys.executable, str(SERVER_DIR / "ha_mcp_server.py")],
                          input=lines, capture_output=True, text=True,
                          env=env, timeout=60)
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()], \
        proc.stdout


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "1"}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


class TestAVoiceProcessIsOfferedWhatVoiceMayUse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (cls.voice_init, cls.voice_list), cls.voice_raw = talk(
            {"BRAIN_EXPOSED_ONLY": "1", "BRAIN_ASSIST_ACCESS": "voice"}, INIT, LIST)
        (cls.full_init, cls.full_list), cls.full_raw = talk({}, INIT, LIST)

    def names(self, response):
        return {t["name"] for t in response["result"]["tools"]}

    def test_the_whole_house_channel_is_offered_everything(self):
        self.assertEqual(self.names(self.full_list), set(m.TOOL_IMPLEMENTATIONS))

    def test_voice_is_not_offered_what_it_would_be_refused(self):
        voice = self.names(self.voice_list)
        for name in ("get_registry", "get_activity", "fire_event", "reload_config",
                     "esphome_install", "music_assistant_play", "minecraft_command",
                     "minecraft_server", "get_automation_config", "search_related",
                     "offer_resolutions", "get_entity_counts"):
            self.assertNotIn(name, voice, name)
        for name in ("control_light", "call_service", "activate_scene", "run_script",
                     "get_entity_state", "remember_fact", "minecraft_teleport",
                     "print_label", "bright_show", "get_history"):
            self.assertIn(name, voice, name)
        self.assertLess(len(self.voice_raw), 0.6 * len(self.full_raw))

    def test_every_tool_hidden_from_voice_is_still_refused_if_called(self):
        """The list is the saving; the dispatcher is still the gate."""
        hidden = set(self.names(self.full_list)) - self.names(self.voice_list)
        self.assertTrue(hidden)
        reached = []

        def tripwire(*_a, **_k):
            reached.append(_a)
            raise AssertionError("a hidden tool reached Home Assistant")
        with patch.object(m, "EXPOSED_ONLY", True), \
                patch.object(m, "ha_api_request", tripwire), \
                patch.object(m, "_ws_command", tripwire), \
                patch.object(m, "_panel_get", tripwire), \
                patch.object(m, "_panel_send", tripwire):
            for name in sorted(hidden):
                required = m._TOOL_SPECS[name][1]
                got = m.handle_tool_call(name, {k: "x" for k in required})
                self.assertIn("error", got, name)
        self.assertEqual(reached, [])

    def test_the_instructions_say_how_to_choose_and_fit_the_channel(self):
        full = self.full_init["result"]["instructions"]
        voice = self.voice_init["result"]["instructions"]
        for tool in ("get_all_states", "explain_change", "get_automation_trace",
                     "recall"):
            self.assertIn(tool, full)
        self.assertIn("first response", voice)
        self.assertIn("exposes to Assist", voice)
        self.assertLess(len(voice), len(full))
        self.assertLess(len(full), 1200, "these ride every turn")

    def test_the_tools_voice_acts_with_are_never_deferred(self):
        tools = {t["name"]: t for t in self.voice_list["result"]["tools"]}
        for name in m.ALWAYS_LOAD_TOOLS:
            self.assertEqual(tools[name]["_meta"], {"anthropic/alwaysLoad": True}, name)
        self.assertNotIn("_meta", tools["get_history"])
        self.assertNotIn("_meta", tools["remember_fact"])

    def test_the_wire_carries_no_padding(self):
        self.assertNotIn("\n  ", self.full_raw)
        self.assertNotIn('", "', self.full_raw)


class TestResultsAreCompact(unittest.TestCase):
    def test_a_result_round_trips_without_indentation(self):
        result = [{"entity_id": f"sensor.t{i}", "state": "21.4"} for i in range(3)]
        text = m.build_tool_response(result)["content"][0]["text"]
        self.assertEqual(json.loads(text), result)
        self.assertNotIn("\n", text)
        self.assertNotIn(": ", text)
        self.assertLess(len(text), len(json.dumps(result, indent=2)) * 0.8)

    def test_the_dashboard_cap_is_measured_the_way_it_is_sent(self):
        """Measured on one encoding and emitted in a fatter one, the cap let
        a payload through that was larger on the wire than the cap."""
        config = {"views": [{"title": "v", "cards": [{"type": "markdown",
                                                      "content": "x" * 50}] * 200}]}
        with patch.object(m, "_ws_command", return_value=config), \
                patch.object(m, "MAX_DASHBOARD_BYTES", len(m._compact(
                    {**m._dashboard_named(None, config), "config": config})) + 10):
            got = m.get_dashboard()
        self.assertIn("config", got)
        self.assertLessEqual(len(m._compact(got)), m.MAX_DASHBOARD_BYTES)


class TestTheMisleadingNameIsGone(unittest.TestCase):
    def test_entity_counts_says_what_it_is(self):
        with patch.object(m, "ha_api_request", return_value=[
                {"entity_id": "light.a"}, {"entity_id": "light.b"},
                {"entity_id": "sensor.c"}]):
            got = m.handle_tool_call("get_entity_counts", {})
        self.assertEqual(got, {"total_entities": 3, "domains": {"light": 2, "sensor": 1}})

    def test_the_old_name_is_still_answered_and_listed_nowhere(self):
        self.assertNotIn("get_device_registry", {t["name"] for t in m.TOOLS})
        with patch.object(m, "ha_api_request", return_value=[{"entity_id": "light.a"}]):
            got = m.handle_tool_call("get_device_registry", {})
        self.assertEqual(got["total_entities"], 1)
        with patch.object(m, "EXPOSED_ONLY", True):
            got = m.handle_tool_call("get_device_registry", {})
        self.assertIn("whole house", got["error"])


if __name__ == "__main__":
    unittest.main()
