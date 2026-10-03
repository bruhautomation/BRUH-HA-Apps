#!/usr/bin/env python3
"""Reading why an automation did what it did — live, by its config id.

`get_automation_trace` read `.storage/trace.saved_traces`, which Core writes
only when it shuts down, so no run since the last restart was ever visible;
it looked the file up by ENTITY id, where Core keys a trace by the
automation's CONFIG id — a millisecond timestamp for anything made in the UI
— so even the saved runs reported "No stored traces"; and nothing returned
an automation's definition at all, while the unattended runs that debug
automations have no file access to read automations.yaml.

The fixtures below are Core's own shapes, read off its source
(`trace/models.py` `as_short_dict` / `as_extended_dict`,
`helpers/trace.py` `TraceElement.as_dict`, `automation/trace.py` adding
`trigger`): a `trace/list` row is the short dict, `trace/get` answers the
extended one, and every step is a list of elements under its path.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402

UI_ID = "1712345678901"
STATE = {
    "entity_id": "automation.hall_lights",
    "state": "on",
    "attributes": {"id": UI_ID, "friendly_name": "Hall lights",
                   "last_triggered": "2026-10-03T07:01:02.000001+00:00",
                   "mode": "single", "current": 0},
}


def short(run_id, start, **extra):
    row = {"last_step": "action/0", "run_id": run_id, "state": "stopped",
           "script_execution": "finished",
           "timestamp": {"start": start, "finish": start},
           "domain": "automation", "item_id": UI_ID,
           "trigger": "state of binary_sensor.hall_motion"}
    row.update(extra)
    return row


LIST = [
    short("aaa", "2026-10-03T06:00:00+00:00"),
    short("ccc", "2026-10-03T07:01:02+00:00", last_step="condition/0",
          script_execution="failed_conditions"),
    short("bbb", "2026-10-03T06:30:00+00:00", error="Entity not found"),
    short("nnn", "2026-10-03T07:05:00+00:00", not_triggered=True,
          last_step="trigger/0", script_execution=None, state="stopped"),
]
EXTENDED = {
    **short("ccc", "2026-10-03T07:01:02+00:00", last_step="condition/0",
            script_execution="failed_conditions"),
    "trace": {
        "trigger/0": [{
            "path": "trigger/0", "timestamp": "2026-10-03T07:01:02+00:00",
            "changed_variables": {
                "this": {"entity_id": "automation.hall_lights", "state": "on",
                         "attributes": {"id": UI_ID}},
                "trigger": {"platform": "state", "entity_id": "binary_sensor.hall_motion",
                            "to_state": {"state": "on"}}}}],
        "condition/0": [{
            "path": "condition/0", "timestamp": "2026-10-03T07:01:02+00:00",
            "result": {"result": False}}],
        "condition/0/entity_id/0": [{
            "path": "condition/0/entity_id/0",
            "timestamp": "2026-10-03T07:01:02+00:00",
            "result": {"result": False, "state": "on", "wanted_state": "off"}}],
    },
    "config": {"id": UI_ID, "alias": "Hall lights", "triggers": [], "actions": []},
    "blueprint_inputs": None,
    "context": {"id": "01J9", "parent_id": None, "user_id": "abc123"},
}


class FakeCore:
    def __init__(self):
        self.ws = []
        self.rest = []
        self.listing = list(LIST)

    def command(self, payload, timeout=15):
        self.ws.append(payload)
        if payload["type"] == "trace/list":
            if payload.get("item_id") != UI_ID:
                return []
            return self.listing
        if payload["type"] == "trace/get":
            if payload["run_id"] != "ccc":
                return {"error": "{'code': 'not_found'}"}
            return EXTENDED
        if payload["type"] == "automation/config":
            return {"config": EXTENDED["config"]}
        if payload["type"] == "script/config":
            return {"config": {"sequence": [], "alias": "Goodnight"}}
        if payload["type"] == "search/related":
            return {"entity": ["light.hall", "binary_sensor.hall_motion"],
                    "area": ["hall"], "device": ["dev-hall"]}
        raise AssertionError(payload)

    def api(self, endpoint, method="GET", data=None, accept=None):
        self.rest.append(endpoint)
        if endpoint == "/api/states/automation.hall_lights":
            return STATE
        if endpoint == "/api/states/automation.no_id":
            return {"entity_id": "automation.no_id", "state": "on",
                    "attributes": {"friendly_name": "No id"}}
        if endpoint == "/api/states/script.goodnight":
            return {"entity_id": "script.goodnight", "state": "off", "attributes": {}}
        if endpoint == "/api/states":
            return [STATE, {"entity_id": "light.x", "attributes": {}}]
        if endpoint.startswith("/api/config/automation/config/"):
            return EXTENDED["config"] if endpoint.endswith(UI_ID) else \
                {"error": "HTTP 404: Not Found"}
        return {"error": "HTTP 404: Not Found"}


class Case(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        for p in (patch.object(m, "_ws_command", self.core.command),
                  patch.object(m, "ha_api_request", self.core.api),
                  patch.object(m, "EXPOSED_ONLY", False)):
            p.start()
            self.addCleanup(p.stop)


class TestTracesAreLiveAndKeyedByConfigId(Case):
    def test_the_entity_is_looked_up_by_its_config_id(self):
        got = m.get_automation_trace("automation.hall_lights")
        self.assertNotIn("error", got)
        lists = [p for p in self.core.ws if p["type"] == "trace/list"]
        self.assertEqual(lists, [{"type": "trace/list", "domain": "automation",
                                  "item_id": UI_ID}])
        self.assertEqual(got["id"], UI_ID)

    def test_runs_are_newest_first_and_not_triggered_ones_are_counted(self):
        got = m.get_automation_trace("automation.hall_lights")
        self.assertEqual([r["run_id"] for r in got["runs"]], ["ccc", "bbb", "aaa"])
        self.assertEqual(got["not_triggered"], 1)
        self.assertEqual(got["runs"][1]["error"], "Entity not found")

    def test_the_newest_run_is_unwrapped_step_by_step(self):
        got = m.get_automation_trace("automation.hall_lights")
        run = got["run"]
        self.assertEqual(run["run_id"], "ccc")
        self.assertEqual(run["script_execution"], "failed_conditions")
        self.assertEqual(run["steps"]["condition/0/entity_id/0"][0]["result"],
                         {"result": False, "state": "on", "wanted_state": "off"})
        trigger_vars = run["steps"]["trigger/0"][0]["changed_variables"]
        self.assertIn("trigger", trigger_vars)
        self.assertNotIn("this", trigger_vars, "the automation's own state, repeated")
        self.assertNotIn("config", run, "the definition is get_automation_config's")
        self.assertEqual(run["started_by_user"], "abc123")

    def test_a_bare_config_id_works_too(self):
        got = m.get_automation_trace(UI_ID)
        self.assertEqual(got["entity_id"], "automation.hall_lights")
        self.assertEqual(got["run"]["run_id"], "ccc")

    def test_a_named_run_is_fetched(self):
        got = m.get_automation_trace("automation.hall_lights", run_id="nope")
        self.assertIn("could not be read", got["error"])
        self.assertEqual(self.core.ws[-1]["run_id"], "nope")

    def test_an_automation_with_no_id_says_why_it_has_no_traces(self):
        got = m.get_automation_trace("automation.no_id")
        self.assertIn("no id:", got["error"])
        self.assertEqual([p for p in self.core.ws if p["type"] == "trace/list"], [])

    def test_no_runs_is_said_rather_than_read_as_an_error(self):
        self.core.listing = []
        got = m.get_automation_trace("automation.hall_lights")
        self.assertNotIn("error", got)
        self.assertEqual(got["runs"], [])
        self.assertIn("holds no traces", got["note"])

    def test_a_script_is_traced_by_its_object_id(self):
        m.get_automation_trace("script.goodnight")
        lists = [p for p in self.core.ws if p["type"] == "trace/list"]
        self.assertEqual(lists[-1], {"type": "trace/list", "domain": "script",
                                     "item_id": "goodnight"})

    def test_a_trace_too_large_keeps_its_steps_and_drops_the_variables(self):
        big = dict(EXTENDED)
        big["trace"] = dict(EXTENDED["trace"])
        big["trace"]["trigger/0"] = [{
            "path": "trigger/0", "timestamp": "t",
            "changed_variables": {"trigger": {"blob": "x" * (m.MAX_TRACE_BYTES + 10)}}}]
        with patch.object(m, "_ws_command",
                          lambda p, timeout=15: LIST if p["type"] == "trace/list" else big):
            got = m.get_automation_trace("automation.hall_lights")
        self.assertIn("steps", got["run"])
        self.assertNotIn("changed_variables", got["run"]["steps"]["trigger/0"][0])
        self.assertIn("changed variables were left out", got["note"])

    def test_the_shutdown_file_is_never_opened(self):
        with patch("builtins.open", side_effect=AssertionError("opened a file")):
            got = m.get_automation_trace("automation.hall_lights")
        self.assertEqual(got["run"]["run_id"], "ccc")


class TestTheDefinitionIsReadable(Case):
    def test_by_entity_id_over_the_websocket(self):
        got = m.get_automation_config("automation.hall_lights")
        self.assertEqual(got["config"]["id"], UI_ID)
        self.assertEqual(self.core.ws[-1], {"type": "automation/config",
                                            "entity_id": "automation.hall_lights"})
        got = m.get_automation_config("script.goodnight")
        self.assertEqual(got["config"]["alias"], "Goodnight")

    def test_by_config_id_through_the_editor_endpoint(self):
        got = m.get_automation_config(UI_ID)
        self.assertEqual(got["config"]["alias"], "Hall lights")
        self.assertEqual(self.core.rest[-1], f"/api/config/automation/config/{UI_ID}")
        got = m.get_automation_config("not_in_the_file")
        self.assertIn("Pass its entity id", got["error"])

    def test_get_automations_shows_the_id_that_unlocks_both(self):
        rows = m.get_automations()
        self.assertEqual(rows, [{"entity_id": "automation.hall_lights", "id": UI_ID,
                                 "state": "on", "friendly_name": "Hall lights",
                                 "last_triggered": STATE["attributes"]["last_triggered"]}])


class TestSearchRelated(Case):
    def test_it_asks_core_and_hands_back_the_lists(self):
        got = m.search_related("script", "script.goodnight")
        self.assertEqual(self.core.ws[-1], {"type": "search/related",
                                            "item_type": "script",
                                            "item_id": "script.goodnight"})
        self.assertEqual(got["related"]["entity"],
                         ["binary_sensor.hall_motion", "light.hall"])

    def test_an_unknown_item_type_is_refused_before_asking(self):
        got = m.search_related("planet", "earth")
        self.assertIn("item_type must be one of", got["error"])
        self.assertEqual(self.core.ws, [])


class TestTheyAreReadsAndVoiceCannotReachThem(unittest.TestCase):
    def test_the_analyst_may_use_them_and_voice_may_not(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))
        import engine  # noqa: PLC0415
        for name in ("get_automation_config", "search_related"):
            self.assertIn(f"{engine.MCP}{name}", engine.ANALYST_TOOLS)
            self.assertIn(name, m.VOICE_REFUSED_TOOLS)
        with patch.object(m, "EXPOSED_ONLY", True):
            got = m.handle_tool_call("search_related",
                                     {"item_type": "entity", "item_id": "lock.x"})
        self.assertIn("whole house", got["error"])


if __name__ == "__main__":
    unittest.main()
