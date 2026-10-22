#!/usr/bin/env python3
"""YOLO mode: the owner's opt-in to no restrictions at all.

One panel setting, off by default, published as a flag file the processes
that cannot import the panel read (the MCP server and both PreToolUse
hooks). Each half is driven for real: the setting through the settings
store, the gate through `/api/gate`, the MCP chokepoint through
`call_service`, both hooks as the subprocesses they are, and a plan
through the panel's own worker until it has been applied with nobody
pressing Apply.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import ha_mcp_server  # noqa: E402
import settings_store  # noqa: E402

from test_action_gate import GateCase, PFX  # noqa: E402
from test_fix_plan import FixCase  # noqa: E402

SCRIPTS = BASE_DIR / "brain" / "scripts"
DEFAULT = "/config/.brain/yolo"


class TestTheSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._file = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        settings_store.SETTINGS_FILE = self._file
        self.tmp.cleanup()

    def test_it_is_off_by_default_and_saves_as_a_boolean(self):
        self.assertIs(settings_store.load()["yolo_mode"], False)
        settings_store.save({"yolo_mode": True})
        self.assertIs(settings_store.load()["yolo_mode"], True)
        with self.assertRaises(ValueError):
            settings_store.save({"yolo_mode": "yes"})


class TestTheFileIsSpelledOnce(unittest.TestCase):
    def test_every_reader_has_the_same_default(self):
        for path in (BASE_DIR / "brain" / "panel" / "server.py",
                     BASE_DIR / "brain" / "ha-mcp-server" / "ha_mcp_server.py",
                     SCRIPTS / "brain-protect-hook.py",
                     SCRIPTS / "brain-action-gate.py",
                     SCRIPTS / "ha-context-gen.sh"):
            text = path.read_text()
            self.assertIn("BRAIN_YOLO_FILE", text, path.name)
            self.assertIn(DEFAULT, text, path.name)


class TestTheGateStandsDown(GateCase):
    def test_off_a_task_channel_still_answers_to_the_model(self):
        out = self.ask(PFX + "control_switch",
                       {"entity_id": "switch.freezer", "action": "off"},
                       ["tidy up the kitchen"], channel="task")
        self.assertNotEqual(out["path"], "yolo")

    def test_on_every_channel_allows_before_the_floors(self):
        self.server.settings_store.save({"yolo_mode": True})
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "lock.*"
        for channel in ("task", "chat", "voice", ""):
            out = self.ask(PFX + "control_lock",
                           {"entity_id": "lock.back", "action": "unlock"},
                           ["open the back door"], channel=channel)
            self.assertEqual((out["decision"], out["path"]),
                             ("allow", "yolo"), channel)
        self.assertEqual(self.model_calls, [])

    def test_turning_it_off_bites_at_once(self):
        args = {"entity_id": "switch.freezer", "action": "off"}
        self.server.settings_store.save({"yolo_mode": True})
        self.assertEqual(self.ask(PFX + "control_switch", args, ["x"],
                                  channel="task")["path"], "yolo")
        self.server.settings_store.save({"yolo_mode": False})
        self.assertNotEqual(self.ask(PFX + "control_switch", args, ["x"],
                                     channel="task")["path"], "yolo")


class YoloFileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.flag = Path(self.tmp.name) / "yolo"

    def tearDown(self):
        self.tmp.cleanup()

    def on(self, text="on\n"):
        self.flag.write_text(text)


class TestTheChokepointStandsDown(YoloFileCase):
    def setUp(self):
        super().setUp()
        self._old = (ha_mcp_server.YOLO_FILE, ha_mcp_server.PROTECTED_ENTITIES,
                     ha_mcp_server.DENIED_SERVICES)
        ha_mcp_server.YOLO_FILE = str(self.flag)
        ha_mcp_server.PROTECTED_ENTITIES = ["lock.front_door"]
        ha_mcp_server.DENIED_SERVICES = []

    def tearDown(self):
        (ha_mcp_server.YOLO_FILE, ha_mcp_server.PROTECTED_ENTITIES,
         ha_mcp_server.DENIED_SERVICES) = self._old
        super().tearDown()

    @patch("ha_mcp_server.ha_api_request")
    def test_a_protected_entity_is_refused_while_it_is_off(self, api):
        out = ha_mcp_server.call_service("lock", "unlock",
                                         {"entity_id": "lock.front_door"})
        self.assertIn("protected", out.get("error", ""))

    @patch("ha_mcp_server.ha_api_request")
    def test_and_reached_while_it_is_on(self, api):
        api.return_value = {"ok": True}
        self.on()
        out = ha_mcp_server.call_service("lock", "unlock",
                                         {"entity_id": "lock.front_door"})
        self.assertNotIn("error", out)
        posts = [c for c in api.call_args_list
                 if str(c.args[0]).startswith("/api/services/")]
        self.assertEqual(len(posts), 1)

    @patch("ha_mcp_server.ha_api_request")
    def test_fire_event_is_allowed_while_it_is_on(self, api):
        self.assertIn("error", ha_mcp_server.fire_event("x"))
        api.return_value = {"message": "ok"}
        self.on()
        self.assertNotIn("error", ha_mcp_server.fire_event("x") or {})

    def test_anything_but_on_is_off(self):
        for text in ("", "off", "yes", "ON please"):
            self.on(text)
            self.assertFalse(ha_mcp_server.yolo_mode(), text)
        self.on(" on \n")
        self.assertTrue(ha_mcp_server.yolo_mode())


class TestTheHooksStandDown(YoloFileCase):
    def run_hook(self, name, payload, env):
        full = dict(os.environ, BRAIN_YOLO_FILE=str(self.flag), **env)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / name)], input=json.dumps(payload),
            capture_output=True, text=True, env=full, timeout=30)

    def test_the_protect_hook_refuses_only_while_it_is_off(self):
        payload = {"tool_name": "Bash",
                   "tool_input": {"command": "ha service call lock.unlock"}}
        env = {"BRAIN_PROTECTED_ENTITIES": "lock.front_door"}
        self.assertIn("deny", self.run_hook("brain-protect-hook.py",
                                            payload, env).stdout)
        self.on()
        self.assertEqual(self.run_hook("brain-protect-hook.py", payload,
                                       env).stdout.strip(), "")

    def test_the_action_gate_hook_is_silent_while_it_is_on(self):
        payload = {"tool_name": PFX + "control_lock",
                   "tool_input": {"entity_id": "lock.x", "action": "unlock"}}
        # A task channel with no panel to ask: refused while off…
        env = {"BRAIN_CHANNEL": "task",
               "BRAIN_PANEL_URL": "http://127.0.0.1:9"}
        self.assertIn("deny", self.run_hook("brain-action-gate.py",
                                            payload, env).stdout)
        # …and nothing printed (nothing gated) while on.
        self.on()
        self.assertEqual(self.run_hook("brain-action-gate.py", payload,
                                       env).stdout.strip(), "")


class TestAPlanAppliesItself(FixCase):
    def test_nobody_presses_apply(self):
        settings_store.save({"yolo_mode": True})
        self.agent_allowed = True
        row = self.file_finding()

        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)

        self.drive(body)
        self.assertEqual(len(self.agent_calls), 1)
        self.assertEqual(findings_store.get(row["ts"])["status"], "fixed")

    def test_off_the_plan_waits_for_the_press(self):
        row = self.file_finding()

        async def body(client):
            await self.press(row["ts"], "fix", client)
            await self.work(client)

        self.drive(body)
        self.assertEqual(self.agent_calls, [])
        self.assertEqual(findings_store.get(row["ts"])["status"], "planned")


class TestThePromptSaysSo(unittest.TestCase):
    def test_the_chat_prompt_names_yolo_only_while_it_is_on(self):
        import server  # noqa: PLC0415
        with patch.object(server, "yolo_mode", return_value=False):
            self.assertNotIn("YOLO", server._chat_system_prompt(None))
        with patch.object(server, "yolo_mode", return_value=True):
            text = server._chat_system_prompt(None)
        self.assertIn("YOLO mode is ON", text)
        self.assertTrue(re.search(r"never wait for a person's approval", text,
                                  re.I))


if __name__ == "__main__":
    unittest.main()
