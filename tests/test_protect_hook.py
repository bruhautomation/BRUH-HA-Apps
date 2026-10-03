"""`protected_entities` on the two routes around the MCP chokepoint.

A shell service call and a YAML edit never meet `call_service`, so the
terminal, the chat and a Fix it run could reach a protected lock by
either. `brain-protect-hook.py` is the PreToolUse hook that stands there,
driven here as the process Claude Code runs: a payload on stdin, the
decision on stdout. The exit status is always 0 — a refusal is a decision
printed, never a crash.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "brain" / "scripts" / "brain-protect-hook.py"


def run_hook(payload, protected: str = "lock.front_door, alarm_control_panel.*",
             raw: str | None = None) -> tuple[int, dict | None]:
    env = dict(os.environ, BRAIN_PROTECTED_ENTITIES=protected)
    proc = subprocess.run([sys.executable, str(HOOK)],
                          input=raw if raw is not None else json.dumps(payload),
                          env=env, capture_output=True, text=True, timeout=30)
    out = proc.stdout.strip()
    return proc.returncode, (json.loads(out) if out else None)


def denied(decision) -> bool:
    return bool(decision) and \
        decision["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestAShellServiceCall(unittest.TestCase):
    def test_every_route_to_a_service_is_refused_while_the_list_is_set(self):
        commands = [
            "ha service call lock.unlock --data '{\"entity_id\":\"lock.front_door\"}'",
            "ha-service call light.turn_on --data '{\"area_id\":\"hall\"}'",
            "/opt/scripts/ha-service.sh call script.bedtime",
            "curl -s -X POST -H \"Authorization: Bearer $SUPERVISOR_TOKEN\" "
            "http://supervisor/core/api/services/lock/unlock -d '{}'",
            "python3 -c 'import websocket; ws.connect(\"ws://supervisor/core/websocket\");"
            " ws.send({\"type\": \"call_service\"})'",
        ]
        for command in commands:
            with self.subTest(command=command[:40]):
                code, decision = run_hook({"tool_name": "Bash",
                                           "tool_input": {"command": command}})
                self.assertEqual(code, 0)
                self.assertTrue(denied(decision), command)
                reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("call_service tool", reason)

    def test_reading_is_not_calling(self):
        for command in ("ha service list light",
                        "curl -s http://supervisor/core/api/services",
                        "ha entity get lock.front_door",
                        "grep -r call_service /config/custom_components"):
            with self.subTest(command=command):
                self.assertIsNone(run_hook({"tool_name": "Bash",
                                            "tool_input": {"command": command}})[1])

    def test_an_empty_list_protects_nothing_and_says_nothing(self):
        code, decision = run_hook(
            {"tool_name": "Bash",
             "tool_input": {"command": "ha service call lock.unlock"}},
            protected="")
        self.assertEqual((code, decision), (0, None))


class TestAYamlEdit(unittest.TestCase):
    def test_an_edit_that_names_a_protected_entity_is_refused(self):
        payloads = [
            {"tool_name": "Write", "tool_input": {
                "file_path": "/config/automations.yaml",
                "content": "- id: x\n  actions:\n    - action: lock.unlock\n"
                           "      target:\n        entity_id: lock.front_door\n"}},
            {"tool_name": "Edit", "tool_input": {
                "file_path": "/config/scripts.yaml",
                "old_string": "light.hall", "new_string": "lock.front_door"}},
            {"tool_name": "MultiEdit", "tool_input": {
                "file_path": "/config/packages/alarm.yml",
                "edits": [{"old_string": "a", "new_string": "b"},
                          {"old_string": "c",
                           "new_string": "entity_id: alarm_control_panel.house"}]}},
        ]
        for payload in payloads:
            with self.subTest(tool=payload["tool_name"]):
                code, decision = run_hook(payload)
                self.assertEqual(code, 0)
                self.assertTrue(denied(decision))
                reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
                self.assertIn("protected_entities", reason)

    def test_what_it_does_not_cover_passes(self):
        payloads = [
            # Another entity in the same domain as an exact entry.
            {"tool_name": "Edit", "tool_input": {
                "file_path": "/config/automations.yaml",
                "old_string": "a", "new_string": "entity_id: lock.back_gate"}},
            # Not YAML: the list guards what brAIn writes into Home
            # Assistant's configuration, not every file that mentions a name.
            {"tool_name": "Write", "tool_input": {
                "file_path": "/config/notes.md", "content": "lock.front_door"}},
            # A longer id that merely starts with a protected one.
            {"tool_name": "Write", "tool_input": {
                "file_path": "/config/a.yaml",
                "content": "sensor.lock_front_door_battery: 1\n"}},
            {"tool_name": "Read", "tool_input": {"file_path": "/config/a.yaml"}},
        ]
        for payload in payloads:
            with self.subTest(payload=json.dumps(payload)[:60]):
                self.assertIsNone(run_hook(payload)[1])

    def test_a_star_protects_everything_it_can_name(self):
        code, decision = run_hook(
            {"tool_name": "Edit", "tool_input": {
                "file_path": "/config/automations.yaml",
                "old_string": "a", "new_string": "entity_id: light.hall"}},
            protected="*")
        self.assertTrue(denied(decision))


class TestItNeverCostsTheCallOverABug(unittest.TestCase):
    def test_a_payload_it_cannot_read_allows(self):
        for raw in ("", "not json", "[]", '{"tool_name": "Bash"}',
                    '{"tool_name": "Edit", "tool_input": "nope"}'):
            with self.subTest(raw=raw):
                self.assertEqual(run_hook(None, raw=raw), (0, None))


if __name__ == "__main__":
    unittest.main()
