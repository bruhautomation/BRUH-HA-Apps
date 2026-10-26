"""Which entities reach the voice assistants and each HomeKit Bridge.

`assistant_exposure` reads Settings → Voice assistants → Expose for every
assistant the house has and each HomeKit Bridge's filter and accessory
count; `set_assistant_exposure` changes them in bulk — the expose command
for the assistants, the bridge's own options flow for HomeKit, read form by
form and aborted when it cannot be finished. Driven through the real
dispatcher with Home Assistant faked at the WebSocket and the REST API, in
the shapes Core answers with (`homeassistant/exposed_entities.py`,
`homekit/config_flow.py`, `homekit/diagnostics.py`).

And the one security rule on top: exposing a lock, an alarm or a garage
door to an assistant is refused by the action gate unless the person's own
words name it — before "Let brAIn act without asking" is asked.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "brain", "ha-mcp-server"))
sys.path.insert(0, os.path.join(HERE, "..", "brain", "panel"))

import ha_mcp_server as m  # noqa: E402


def state(eid, value="on", **attrs):
    return {"entity_id": eid, "state": value, "attributes": attrs}


class FakeCore:
    def __init__(self):
        self.ws_calls = []
        self.rest_calls = []
        self.states = [
            state("light.porch", friendly_name="Porch light"),
            state("light.study", friendly_name="Study lamp"),
            state("light.attic", "unavailable", friendly_name="Attic light"),
            state("switch.kettle", friendly_name="Kettle"),
            state("lock.side_gate", "locked", friendly_name="Side gate lock"),
            state("sensor.porch_temp", "12", device_class="temperature"),
        ]
        self.registry = [{"entity_id": s["entity_id"]} for s in self.states]
        self.exposed = {"light.porch": {"conversation": True},
                        "light.attic": {"conversation": True},
                        "light.gone": {"conversation": True},
                        "light.study": {"conversation": False}}
        self.expose_new = False
        self.cloud = []
        self.bridges = [{"entry_id": "hk1", "title": "Garden Bridge",
                         "state": "loaded", "disabled_by": None}]
        self.options = {"mode": "bridge", "filter": {
            "include_domains": ["light"], "include_entities": ["switch.old_fan"],
            "exclude_domains": [], "exclude_entities": []}}
        self.accessories = [{"aid": 1}] + [{"aid": i} for i in range(2, 4)]
        self.flow_forms = None
        self.flow_posts = []
        self.deleted = []

    # WebSocket
    def ws(self, payload, timeout=15):
        self.ws_calls.append(payload)
        kind = payload["type"]
        if kind == "homeassistant/expose_entity/list":
            return {"exposed_entities": dict(self.exposed)}
        if kind == "homeassistant/expose_new_entities/get":
            return {"expose_new": self.expose_new}
        if kind == "config/entity_registry/list":
            return list(self.registry)
        if kind == "config_entries/get":
            return list(self.bridges if payload["domain"] == "homekit" else self.cloud)
        if kind == "homeassistant/expose_entity":
            return None
        raise AssertionError(payload)

    # REST
    def rest(self, endpoint, method="GET", data=None, accept=None):
        self.rest_calls.append((method, endpoint, data))
        if endpoint == "/api/states":
            return list(self.states)
        if endpoint.startswith("/api/diagnostics/config_entry/"):
            if self.options is None:
                return {"error": "HTTP 404"}
            return {"data": {"config-entry": {"title": "Garden Bridge",
                                              "options": self.options},
                             "accessories": self.accessories}}
        if endpoint == "/api/config/config_entries/options/flow":
            self.flow_step = 0
            return {"flow_id": "f1", **self.flow_forms[0]}
        if endpoint == "/api/config/config_entries/options/flow/f1":
            if method == "DELETE":
                self.deleted.append("f1")
                return {}
            self.flow_posts.append(data)
            self.flow_step += 1
            return {"flow_id": "f1", **self.flow_forms[self.flow_step]}
        raise AssertionError(endpoint)


def homekit_forms(mode="include", domains=("light",), entities=()):
    return [
        {"type": "form", "step_id": "init", "data_schema": [
            {"name": "mode", "default": "bridge", "required": True},
            {"name": "include_exclude_mode", "default": mode, "required": True},
            {"name": "domains", "default": list(domains), "required": True}]},
        {"type": "form", "step_id": mode, "data_schema": [
            {"name": "entities", "default": list(entities), "required": False}]},
        {"type": "create_entry"},
    ]


class Base(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        saved = {k: getattr(m, k) for k in ("DENIED_SERVICES", "PROTECTED_ENTITIES",
                                            "EXPOSED_ONLY")}
        self.addCleanup(lambda: [setattr(m, k, v) for k, v in saved.items()])
        m.DENIED_SERVICES = []
        m.PROTECTED_ENTITIES = []
        m.EXPOSED_ONLY = False
        self.recorded = []
        for p in (patch.object(m, "_ws_command", self.core.ws),
                  patch.object(m, "ha_api_request", self.core.rest),
                  patch.object(m, "_honeytokens", lambda: frozenset()),
                  patch.object(m, "record_action",
                               lambda *a, **k: self.recorded.append(a))):
            p.start()
            self.addCleanup(p.stop)

    def tool(self, name, **args):
        return m.handle_tool_call(name, args)


class TestWhatReachesWhat(Base):
    def test_assist_lists_what_is_missing_and_what_is_stale(self):
        out = self.tool("assistant_exposure")
        [assist] = out["assistants"]
        self.assertEqual(assist["assistant"], "conversation")
        missing = {r["entity_id"]: r for r in assist["missing"]}
        self.assertIn("light.study", missing, "turned off for Assist")
        self.assertIn("switch.kettle", missing, "not exposed by default")
        self.assertTrue(missing["lock.side_gate"].get("security"))
        self.assertNotIn("light.attic", missing, "unavailable is not in use")
        self.assertNotIn("sensor.porch_temp", missing, "not controllable")
        stale = {r["entity_id"]: r["why"] for r in assist["stale"]}
        self.assertEqual(stale, {"light.attic": "unavailable",
                                 "light.gone": "no longer exists"})

    def test_the_cloud_assistants_appear_with_home_assistant_cloud(self):
        self.core.cloud = [{"entry_id": "c1"}]
        names = [a["assistant"] for a in self.tool("assistant_exposure")["assistants"]]
        self.assertEqual(names, ["conversation", "cloud.alexa", "cloud.google_assistant"])

    def test_a_bridge_counts_its_accessories_and_lists_what_it_leaves_out(self):
        [bridge] = self.tool("assistant_exposure")["homekit"]
        self.assertEqual(bridge["accessories"], 2)
        self.assertEqual(bridge["counted"], "by the bridge")
        self.assertNotIn("warning", bridge)
        self.assertIn("switch.kettle", bridge["missing"])
        self.assertNotIn("light.porch", bridge["missing"])
        self.assertEqual(bridge["stale"],
                         [{"entity_id": "switch.old_fan", "why": "no longer exists"}])

    def test_a_bridge_near_homekits_limit_says_so(self):
        self.core.accessories = [{"aid": i} for i in range(1, 147)]
        [bridge] = self.tool("assistant_exposure")["homekit"]
        self.assertEqual(bridge["accessories"], 145)
        self.assertIn("5 left", bridge["warning"])
        self.core.accessories = [{"aid": i} for i in range(1, 160)]
        [bridge] = self.tool("assistant_exposure")["homekit"]
        self.assertIn("over the limit", bridge["warning"])

    def test_a_bridge_whose_settings_cannot_be_read_says_so(self):
        self.core.options = None
        [bridge] = self.tool("assistant_exposure")["homekit"]
        self.assertIn("could not be read", bridge["note"])
        self.assertNotIn("missing", bridge)


class TestChangingIt(Base):
    def test_exposure_is_one_bulk_command(self):
        out = self.tool("set_assistant_exposure",
                        entity_ids=["switch.kettle", "light.study"], expose=True,
                        assistants=["conversation", "cloud.alexa"])
        self.assertTrue(out["ok"], out)
        [sent] = [c for c in self.core.ws_calls
                  if c["type"] == "homeassistant/expose_entity"]
        self.assertEqual(sent, {"type": "homeassistant/expose_entity",
                                "assistants": ["conversation", "cloud.alexa"],
                                "entity_ids": ["switch.kettle", "light.study"],
                                "should_expose": True})
        self.assertTrue(self.recorded, "the change is on the action ledger")

    def test_a_protected_entity_is_refused_and_nothing_is_sent(self):
        m.PROTECTED_ENTITIES = ["switch.kettle"]
        out = self.tool("set_assistant_exposure", entity_ids=["switch.kettle"],
                        expose=True)
        self.assertIn("protected", out["error"])
        self.assertFalse([c for c in self.core.ws_calls
                          if c["type"] == "homeassistant/expose_entity"])

    def test_an_unknown_assistant_is_refused(self):
        out = self.tool("set_assistant_exposure", entity_ids=["light.study"],
                        expose=True, assistants=["siri"])
        self.assertIn("not an assistant", out["error"])

    def test_leaving_one_light_out_of_a_bridge_lists_the_rest(self):
        self.core.flow_forms = homekit_forms(domains=("light",))
        out = self.tool("set_assistant_exposure",
                        homekit_remove_entity_ids=["light.study"],
                        homekit_add_entity_ids=["switch.kettle"])
        self.assertTrue(out["ok"], out)
        init, include = self.core.flow_posts
        self.assertEqual(init["mode"], "bridge", "the bridge's own mode is kept")
        self.assertEqual(init["domains"], ["light", "switch"])
        self.assertEqual(include["entities"],
                         ["light.attic", "light.porch", "switch.kettle"])
        self.assertEqual(self.core.deleted, [], "a finished flow is not aborted")

    def test_adding_a_light_the_bridge_already_takes_narrows_nothing(self):
        self.core.flow_forms = homekit_forms(domains=("light",))
        self.tool("set_assistant_exposure", homekit_add_entity_ids=["light.study"])
        self.assertEqual(self.core.flow_posts[1]["entities"], [])

    def test_exclude_mode_takes_it_off_the_exclusions(self):
        self.core.flow_forms = homekit_forms(mode="exclude", domains=("light",),
                                             entities=("light.study",))
        self.tool("set_assistant_exposure", homekit_add_entity_ids=["light.study"],
                  homekit_remove_entity_ids=["light.porch"])
        self.assertEqual(self.core.flow_posts[1]["entities"], ["light.porch"])

    def test_a_form_brain_cannot_fill_is_aborted(self):
        forms = homekit_forms()
        forms[1]["data_schema"].append({"name": "devices", "required": True})
        self.core.flow_forms = forms
        out = self.tool("set_assistant_exposure", homekit_add_entity_ids=["switch.kettle"])
        self.assertIn("devices", out["error"])
        self.assertEqual(self.core.deleted, ["f1"])

    def test_voice_may_not_read_or_change_it(self):
        m.EXPOSED_ONLY = True
        for name in ("assistant_exposure", "set_assistant_exposure"):
            self.assertIn("error", self.tool(name, entity_ids=["light.porch"],
                                             expose=True))
        self.assertEqual(self.core.ws_calls, [])


class TestTheListsAgree(unittest.TestCase):
    def test_the_reading_tool_is_the_analysts_and_the_acting_one_is_gated(self):
        import consequence
        import engine
        mcp = "mcp__home-assistant__"
        self.assertIn(f"{mcp}assistant_exposure", engine.ANALYST_TOOLS)
        self.assertIn(f"{mcp}set_assistant_exposure", engine.ANALYST_DENIED)
        self.assertIn("set_assistant_exposure", consequence.GATED_MCP)
        self.assertIn("set_assistant_exposure", m.CONTRACT_REFUSED_TOOLS)
        self.assertIn("set_assistant_exposure", m.VOICE_REFUSED_TOOLS)


class TestALockNobodyNamedIsNotExposed(unittest.TestCase):
    def setUp(self):
        import gate
        self.gate = gate
        self.states = {"lock.side_gate": state("lock.side_gate", "locked",
                                               friendly_name="Side gate lock"),
                       "cover.garage": state("cover.garage", "closed",
                                             friendly_name="Big door",
                                             device_class="garage"),
                       "light.porch": state("light.porch")}

    def floor(self, args, words):
        return self.gate.exposure_floor({"tool": "set_assistant_exposure"},
                                        args, words, self.states)

    def test_an_unnamed_lock_or_garage_door_is_refused(self):
        for eid in ("lock.side_gate", "cover.garage"):
            verdict = self.floor({"entity_ids": [eid], "expose": True},
                                 ["make everything work with Alexa"])
            self.assertEqual(verdict[0], "deny", eid)
        verdict = self.floor({"homekit_add_entity_ids": ["lock.side_gate"]}, [])
        self.assertEqual(verdict[0], "deny")

    def test_named_by_its_name_it_is_left_to_the_rest_of_the_gate(self):
        self.assertIsNone(self.floor({"entity_ids": ["lock.side_gate"],
                                      "expose": True},
                                     ["Add the side gate lock to Alexa"]))
        self.assertIsNone(self.floor({"entity_ids": ["cover.garage"],
                                      "expose": True}, ["expose the big door"]))

    def test_hiding_one_and_exposing_a_light_are_not_this_rules(self):
        self.assertIsNone(self.floor({"entity_ids": ["lock.side_gate"],
                                      "expose": False}, []))
        self.assertIsNone(self.floor({"entity_ids": ["light.porch"],
                                      "expose": True}, []))

    def test_the_switch_does_not_reach_past_it(self):
        import consequence
        import server

        async def view(*_a, **_k):
            return consequence.View(states=dict(self.states))

        body = {"tool": "mcp__home-assistant__set_assistant_exposure",
                "input": {"entity_ids": ["lock.side_gate"], "expose": True},
                "channel": "chat", "words": ["sort out alexa"],
                "session_id": "s-exposure"}
        with patch.object(server, "_gate_view", view), \
                patch.object(server, "yolo_mode", lambda: False), \
                patch.object(server, "eff_skip_permissions", lambda: True):
            out = asyncio.run(server._gate_decide(body))
        self.assertEqual(out["decision"], "deny", out)


if __name__ == "__main__":
    unittest.main()
