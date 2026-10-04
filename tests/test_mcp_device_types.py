#!/usr/bin/env python3
"""The chat's and the terminal's way to change what a device shows as.

`set_device_class`, `show_switch_as`, `stop_showing_switch_as` and
`set_sensor_display` are each one brain.* Power Tool called with response
data through `call_service`, so every guard on that chokepoint stands in
front of them: an agent's blocked services, `protected_entities`, and the
voice level (a brain service acting on another domain's entity). Driven
through the real dispatcher (`handle_tool_call`, which is what a model's
tool call reaches) with Home Assistant faked at the WebSocket, so what is
under test is what reaches Core.

And the registry tool reports what a device is shown as: Core's entity
listing (`as_partial_dict`) carries no device class, so a narrowed list is
read again through `config/entity_registry/get_entries`, whose rows are
`extended_dict` — shapes copied from Core's `helpers/entity_registry.py`.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402

TOOLS = ("set_device_class", "show_switch_as", "stop_showing_switch_as",
         "set_sensor_display")


class FakeCore:
    """Answers the WebSocket the way Core does."""

    def __init__(self):
        self.calls = []
        self.answers = {}
        self.registry_rows = []
        self.extended = {}

    def __call__(self, payload, timeout=15):
        if payload["type"] == "config/entity_registry/list":
            self.calls.append(("list", None))
            return list(self.registry_rows)
        if payload["type"] == "config/entity_registry/get_entries":
            self.calls.append(("get_entries", list(payload["entity_ids"])))
            if self.extended is None:
                return {"error": "{'code': 'unknown_command', 'message': 'Unknown command.'}"}
            return {eid: self.extended.get(eid) for eid in payload["entity_ids"]}
        assert payload["type"] == "call_service", payload
        assert payload["return_response"] is True
        key = (payload["domain"], payload["service"])
        self.calls.append((key, payload["service_data"]))
        if key in self.answers:
            return self.answers[key]
        return {"response": {"ok": True}}

    def services(self):
        return [c for c in self.calls if isinstance(c[0], tuple)]


class Base(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        saved = {k: getattr(m, k) for k in ("DENIED_SERVICES", "PROTECTED_ENTITIES",
                                            "EXPOSED_ONLY")}
        self.addCleanup(lambda: [setattr(m, k, v) for k, v in saved.items()])
        m.DENIED_SERVICES = []
        m.PROTECTED_ENTITIES = []
        m.EXPOSED_ONLY = False
        self.exposed = set()
        for p in (patch.object(m, "_ws_command", self.core),
                  patch.object(m, "record_action", lambda *a, **k: None),
                  patch.object(m, "_exposure", lambda: {"exposed": set(self.exposed)}),
                  patch.object(m, "_entity_exposed",
                               lambda eid: (not m.EXPOSED_ONLY) or eid in self.exposed)):
            p.start()
            self.addCleanup(p.stop)

    def tool(self, name, **args):
        return m.handle_tool_call(name, args)


class TestWhatReachesCore(Base):

    def test_set_device_class_is_the_power_tool_with_its_response(self):
        self.core.answers[("brain", "set_device_class")] = {"response": {"entities": [
            {"entity_id": "binary_sensor.back_door", "device_class": "door",
             "original_device_class": "opening"}]}}
        got = self.tool("set_device_class", entity_id="binary_sensor.back_door",
                        device_class=" Door ")
        self.assertEqual(self.core.services(), [(
            ("brain", "set_device_class"),
            {"entity_id": ["binary_sensor.back_door"], "device_class": "door"})])
        self.assertEqual(got["entities"][0]["original_device_class"], "opening")

    def test_several_entities_ride_one_call(self):
        self.tool("set_device_class", entity_id="binary_sensor.a, binary_sensor.b",
                  device_class="window")
        self.assertEqual(self.core.services()[0][1]["entity_id"],
                         ["binary_sensor.a", "binary_sensor.b"])

    def test_an_empty_class_asks_for_the_integrations_own(self):
        self.tool("set_device_class", entity_id="cover.garage", device_class="")
        self.assertEqual(self.core.services()[0][1], {"entity_id": ["cover.garage"]})

    def test_leaving_the_class_out_is_not_read_as_a_reset(self):
        """A model that forgot the argument must not wipe an override."""
        got = self.tool("set_device_class", entity_id="cover.garage")
        self.assertIn("Missing required argument", got["error"])
        self.assertEqual(self.core.calls, [])

    def test_something_that_is_not_an_entity_never_leaves(self):
        got = self.tool("set_device_class", entity_id="the back door",
                        device_class="door")
        self.assertIn("is not an entity id", got["error"])
        self.assertEqual(self.core.calls, [])

    def test_show_switch_as_and_its_undo(self):
        self.core.answers[("brain", "show_switch_as")] = {"response": {
            "entity_id": "fan.fan_plug", "switch_entity_id": "switch.fan_plug"}}
        got = self.tool("show_switch_as", entity_id="switch.fan_plug",
                        target_domain="Fan")
        self.assertEqual(got["entity_id"], "fan.fan_plug")
        self.tool("show_switch_as", entity_id="switch.gate", target_domain="cover",
                  invert="true")
        self.tool("stop_showing_switch_as", entity_id="fan.fan_plug")
        self.tool("stop_showing_switch_as", entity_id="fan.fan_plug", dry_run=True)
        self.assertEqual([c[1] for c in self.core.services()], [
            {"entity_id": "switch.fan_plug", "target_domain": "fan"},
            {"entity_id": "switch.gate", "target_domain": "cover", "invert": True},
            {"entity_id": "fan.fan_plug", "dry_run": False},
            {"entity_id": "fan.fan_plug", "dry_run": True}])

    def test_a_target_that_is_an_entity_id_is_caught_before_core(self):
        got = self.tool("show_switch_as", entity_id="switch.fan_plug",
                        target_domain="fan.fan_plug")
        self.assertIn("cover, fan, light, lock, siren or valve", got["error"])
        self.assertEqual(self.core.calls, [])

    def test_sensor_display_spells_put_it_back_as_minus_one_and_empty(self):
        self.tool("set_sensor_display", entity_id="sensor.lounge",
                  display_precision=-1, unit_of_measurement="")
        self.tool("set_sensor_display", entity_id="sensor.lounge", display_precision=2)
        self.assertEqual([c[1] for c in self.core.services()], [
            {"entity_id": ["sensor.lounge"], "display_precision": None,
             "unit_of_measurement": None},
            {"entity_id": ["sensor.lounge"], "display_precision": 2}])

    def test_sensor_display_with_nothing_named_asks_rather_than_calls(self):
        got = self.tool("set_sensor_display", entity_id="sensor.lounge")
        self.assertIn("Name display_precision", got["error"])
        self.assertEqual(self.core.calls, [])


class TestTheChokepointStandsInFront(Base):

    def test_a_protected_entity_is_refused_before_core(self):
        m.PROTECTED_ENTITIES = ["binary_sensor.front_door", "switch.*"]
        for name, args in (
                ("set_device_class", {"entity_id": "binary_sensor.front_door",
                                      "device_class": "window"}),
                ("set_device_class", {"entity_id": "binary_sensor.ok, binary_sensor.front_door",
                                      "device_class": "window"}),
                ("show_switch_as", {"entity_id": "switch.boiler", "target_domain": "light"}),
                ("stop_showing_switch_as", {"entity_id": "switch.boiler"})):
            got = self.tool(name, **args)
            self.assertIn("protected", got["error"].lower(), (name, args))
        self.assertEqual(self.core.calls, [])

    def test_an_agent_blocking_brain_services_blocks_these(self):
        m.DENIED_SERVICES = ["brain.*"]
        for name, args in (
                ("set_device_class", {"entity_id": "cover.garage", "device_class": "gate"}),
                ("show_switch_as", {"entity_id": "switch.fan_plug", "target_domain": "fan"}),
                ("set_sensor_display", {"entity_id": "sensor.x", "display_precision": 1})):
            got = self.tool(name, **args)
            self.assertIn("not permitted for this assistant", got["error"], name)
        self.assertEqual(self.core.calls, [])

    def test_the_voice_level_refuses_them_at_the_service_rule(self):
        """An exposed entity passes the exposure gate; a brain service
        acting on another domain's entity is what refuses it."""
        m.EXPOSED_ONLY = True
        self.exposed = {"binary_sensor.back_door", "switch.fan_plug", "fan.fan_plug",
                        "sensor.lounge"}
        for name, args, domain in (
                ("set_device_class", {"entity_id": "binary_sensor.back_door",
                                      "device_class": "door"}, "binary_sensor"),
                ("show_switch_as", {"entity_id": "switch.fan_plug",
                                    "target_domain": "fan"}, "switch"),
                ("stop_showing_switch_as", {"entity_id": "fan.fan_plug"}, "fan"),
                ("set_sensor_display", {"entity_id": "sensor.lounge",
                                        "display_precision": 1}, "sensor")):
            got = self.tool(name, **args)
            self.assertIn(f"through a brain service rather than one of {domain}'s own",
                          got["error"], name)
            self.assertIn("Whole house", got["error"], name)
        self.assertEqual(self.core.calls, [])

    def test_on_voice_an_unexposed_entity_is_refused_first(self):
        m.EXPOSED_ONLY = True
        got = self.tool("set_device_class", entity_id="binary_sensor.back_door",
                        device_class="door")
        self.assertIn("binary_sensor.back_door", got["error"])
        self.assertNotIn("through a brain service", got["error"])
        self.assertEqual(self.core.calls, [])

    def test_a_voice_process_is_not_offered_them(self):
        m.EXPOSED_ONLY = True
        offered = {t["name"] for t in m.tools_for_channel()}
        for name in TOOLS:
            self.assertNotIn(name, offered)
        m.EXPOSED_ONLY = False
        offered = {t["name"] for t in m.tools_for_channel()}
        for name in TOOLS:
            self.assertIn(name, offered)


class TestARefusalIsTheSentence(Base):

    def test_a_validation_error_comes_back_as_the_power_tools_own_words(self):
        """Core puts 'Validation error: ' in front and `_ws_command` hands
        the error dict back as its repr."""
        sentence = ('"garage" is not a binary_sensor device class. Choose one of: '
                    "door, window — or leave device_class empty to give back the "
                    "integration's own.")
        self.core.answers[("brain", "set_device_class")] = {"error": str({
            "code": "service_validation_error",
            "message": f"Validation error: {sentence}",
            "translation_key": None, "translation_placeholders": None,
            "translation_domain": None})}
        got = self.tool("set_device_class", entity_id="binary_sensor.back_door",
                        device_class="garage")
        self.assertEqual(got, {"error": sentence})

    def test_an_integration_that_predates_the_tool_says_restart(self):
        self.core.answers[("brain", "show_switch_as")] = {"error": str({
            "code": "not_found", "message": "Service brain.show_switch_as not found."})}
        got = self.tool("show_switch_as", entity_id="switch.fan_plug", target_domain="fan")
        self.assertIn("restart Home Assistant", got["error"])

    def test_an_entity_not_found_is_not_mistaken_for_a_missing_service(self):
        self.core.answers[("brain", "stop_showing_switch_as")] = {"error": str({
            "code": "service_validation_error",
            "message": "Validation error: Entity not found: switch.gone"})}
        got = self.tool("stop_showing_switch_as", entity_id="switch.gone")
        self.assertEqual(got, {"error": "Entity not found: switch.gone"})


def _partial(entity_id, **kw):
    """A row as `config/entity_registry/list` sends it (`as_partial_dict`):
    no device_class, no original_device_class."""
    row = {"area_id": None, "categories": {}, "config_entry_id": None,
           "device_id": None, "disabled_by": None, "entity_category": None,
           "entity_id": entity_id, "has_entity_name": False, "hidden_by": None,
           "icon": None, "id": "x", "labels": [], "name": None, "options": {},
           "original_name": entity_id, "platform": "zha", "translation_key": None,
           "unique_id": "u"}
    row.update(kw)
    return row


class TestTheRegistrySaysWhatADeviceIsShownAs(Base):

    def setUp(self):
        super().setUp()
        self.core.registry_rows = [
            _partial("binary_sensor.back_door"),
            _partial("light.lamp_plug", platform="switch_as_x", options={
                "switch_as_x": {"entity_id": "switch.lamp_plug", "invert": False}}),
            _partial("switch.lamp_plug", hidden_by="integration"),
            _partial("sensor.lounge", options={"sensor": {
                "display_precision": 2, "unit_of_measurement": "°F"}}),
        ]
        self.core.extended = {
            "binary_sensor.back_door": {"device_class": "door",
                                        "original_device_class": "opening"},
            "light.lamp_plug": {"device_class": None, "original_device_class": None},
            "switch.lamp_plug": {"device_class": None, "original_device_class": "outlet"},
            "sensor.lounge": {"device_class": None,
                              "original_device_class": "temperature"},
        }

    def rows(self, **kw):
        got = self.tool("get_registry", registry="entities", **kw)
        return got, {i["entity_id"]: i for i in got["items"]}

    def test_the_override_and_the_original_are_both_there(self):
        got, rows = self.rows()
        self.assertEqual(rows["binary_sensor.back_door"]["device_class"], "door")
        self.assertEqual(rows["binary_sensor.back_door"]["original_device_class"], "opening")
        self.assertNotIn("device_class", rows["switch.lamp_plug"])
        self.assertEqual(rows["switch.lamp_plug"]["original_device_class"], "outlet")
        self.assertEqual(rows["light.lamp_plug"]["shows_switch"], "switch.lamp_plug")
        self.assertEqual(rows["sensor.lounge"]["display_precision"], 2)
        self.assertEqual(rows["sensor.lounge"]["display_unit"], "°F")
        self.assertNotIn("note", got)
        self.assertEqual(self.core.calls[-1], ("get_entries", [
            "binary_sensor.back_door", "light.lamp_plug", "switch.lamp_plug",
            "sensor.lounge"]))

    def test_the_second_read_covers_only_what_the_filter_kept(self):
        got, rows = self.rows(name_filter="back_door")
        self.assertEqual(list(rows), ["binary_sensor.back_door"])
        self.assertEqual(self.core.calls[-1], ("get_entries", ["binary_sensor.back_door"]))

    def test_a_whole_house_listing_says_how_to_get_them(self):
        self.core.registry_rows = [_partial(f"light.l{i}") for i in range(150)]
        got, rows = self.rows()
        self.assertIn("100 entities or fewer", got["note"])
        self.assertNotIn("get_entries", [c[0] for c in self.core.calls])

    def test_a_core_that_will_not_answer_leaves_the_list_and_says_so(self):
        self.core.extended = None
        got, rows = self.rows()
        self.assertIn("could not be read", got["note"])
        self.assertEqual(len(rows), 4)
        self.assertNotIn("device_class", rows["binary_sensor.back_door"])


class TestTheAnalystMayNotUseThem(unittest.TestCase):
    """An unattended run reads; these rewrite the registry."""

    def test_they_are_denied_by_name(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))
        import engine  # noqa: PLC0415
        for name in TOOLS:
            self.assertIn(f"{engine.MCP}{name}", engine.ANALYST_DENIED, name)
            self.assertNotIn(f"{engine.MCP}{name}", engine.ANALYST_TOOLS, name)


if __name__ == "__main__":
    unittest.main()
