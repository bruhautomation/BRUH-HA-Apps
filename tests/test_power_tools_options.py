#!/usr/bin/env python3
"""An integration's options, and a group helper's members, changed through
the integration's own options flow — driven through the real admin-gated
handlers.

The options manager below answers the way Core's does for a
`SchemaOptionsFlowHandler` (the group helper's, `group/config_flow.py`): a
form whose step is the group type, a data_schema of markers carrying the
field names (Required/Optional), validation that refuses a missing
required field, and `create_entry` that replaces the entry's options. A
second integration answers with a second form, and a third with a menu,
which is what a flow of more than one step looks like from outside.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402


class Required:
    def __init__(self, schema, default=None):
        self.schema = schema
        if default is not None:
            self.default = lambda: default


class Optional(Required):
    pass


class Schema:
    def __init__(self, fields):
        self.schema = fields


class FlowError(Exception):
    pass


class Entry(types.SimpleNamespace):
    pass


class Options:
    def __init__(self, manager):
        self.manager = manager
        self.configured = []
        self.aborted = []

    def _form(self, entry):
        if entry.domain == "group":
            fields = {Required("entities"): None,
                      Required("hide_members", default=False): None}
            if entry.options["group_type"] == "light":
                fields[Required("all", default=False)] = None
            return {"type": "form", "flow_id": f"o-{entry.entry_id}",
                    "step_id": entry.options["group_type"],
                    "data_schema": Schema(fields)}
        if entry.domain == "weather_api":
            return {"type": "form", "flow_id": f"o-{entry.entry_id}", "step_id": "init",
                    "data_schema": Schema({Optional("scan_interval"): None,
                                           Optional("api_key"): None})}
        if entry.domain == "two_step":
            return {"type": "form", "flow_id": f"o-{entry.entry_id}", "step_id": "init",
                    "data_schema": Schema({Required("mode"): None})}
        if entry.domain == "menu_one":
            return {"type": "menu", "flow_id": f"o-{entry.entry_id}",
                    "menu_options": ["devices", "advanced"]}
        raise FlowError("Handler does not support options")

    async def async_init(self, entry_id, **kw):
        return self._form(self.manager.entries[entry_id])

    async def async_configure(self, flow_id, user_input=None):
        entry = self.manager.entries[flow_id[2:]]
        self.configured.append((flow_id, dict(user_input)))
        form = self._form(entry)
        for key in form["data_schema"].schema:
            if isinstance(key, Required) and not isinstance(key, Optional) \
                    and key.schema not in user_input:
                raise FlowError(f"required key not provided @ data['{key.schema}']")
        if entry.domain == "two_step":
            return {"type": "form", "flow_id": flow_id, "step_id": "details",
                    "data_schema": Schema({Required("port"): None})}
        keep = {"group_type": entry.options.get("group_type"),
                "name": entry.options.get("name")} if entry.domain == "group" else {}
        entry.options = {**{k: v for k, v in keep.items() if v}, **user_input}
        return {"type": "create_entry", "flow_id": flow_id}

    def async_abort(self, flow_id):
        self.aborted.append(flow_id)


class ConfigEntries:
    def __init__(self):
        self.entries = {}
        self.options = Options(self)

    def add(self, entry_id, domain, options, title=""):
        self.entries[entry_id] = Entry(entry_id=entry_id, domain=domain,
                                       options=dict(options), title=title)

    def async_get_entry(self, entry_id):
        return self.entries.get(entry_id)


class Registry:
    def __init__(self):
        self.entities = {}

    def add(self, eid, entry_id=None):
        self.entities[eid] = types.SimpleNamespace(entity_id=eid,
                                                   config_entry_id=entry_id)

    def async_get(self, eid):
        return self.entities.get(eid)


class States:
    def __init__(self, ids):
        self.ids = set(ids)

    def get(self, eid):
        return object() if eid in self.ids else None


class Services:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, name, handler, schema=None, **kw):
        self.handlers[name] = handler

    def has_service(self, domain, name):
        return name in self.handlers


class Auth:
    async def async_get_user(self, user_id):
        return types.SimpleNamespace(id=user_id, is_admin=user_id == "admin")


class Case(unittest.TestCase):
    def setUp(self):
        self.pkg = env.load_integration()
        reg = Registry()
        lights = ["light.kitchen_a", "light.kitchen_b", "light.hall"]
        for eid in lights + ["switch.kettle"]:
            reg.add(eid)
        reg.add("light.kitchen_group", "grp1")
        reg.add("light.porch_yaml_group")
        ce = ConfigEntries()
        ce.add("grp1", "group", {"group_type": "light", "name": "Kitchen",
                                 "entities": ["light.kitchen_a"], "hide_members": True,
                                 "all": False})
        ce.add("w1", "weather_api", {"scan_interval": 600, "api_key": "abc123"},
               title="Weather")
        ce.add("t1", "two_step", {"mode": "a"}, title="Two step")
        ce.add("m1", "menu_one", {}, title="Menu one")
        self.ce = ce
        self.hass = types.SimpleNamespace(
            services=Services(), auth=Auth(), data={}, config_entries=ce,
            registries={"entity": reg}, states=States(lights + ["switch.kettle"]))
        self.pkg.power_tools.async_register_power_tools(self.hass)

    def run_tool(self, name, data, user_id="admin"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data, exc=None):
        with self.assertRaises(exc or env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)


class TestGroupMembers(Case):
    def test_members_are_added_through_the_groups_own_form(self):
        result = self.run_tool("set_group_members", {
            "entity_id": "light.kitchen_group", "add": ["light.kitchen_b"]})
        self.assertEqual(result["added"], ["light.kitchen_b"])
        options = self.ce.entries["grp1"].options
        self.assertEqual(options["entities"], ["light.kitchen_a", "light.kitchen_b"])
        # Every other field on the form carried over as it stood.
        self.assertTrue(options["hide_members"])
        self.assertEqual(options["name"], "Kitchen")

    def test_set_and_remove(self):
        self.run_tool("set_group_members", {
            "entity_id": "light.kitchen_group",
            "entities": ["light.kitchen_a", "light.hall"]})
        self.run_tool("set_group_members", {
            "entity_id": "light.kitchen_group", "remove": "light.kitchen_a"})
        self.assertEqual(self.ce.entries["grp1"].options["entities"], ["light.hall"])

    def test_a_dry_run_submits_nothing(self):
        result = self.run_tool("set_group_members", {
            "entity_id": "light.kitchen_group", "add": ["light.hall"], "dry_run": True})
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.ce.options.configured, [])
        self.assertEqual(self.ce.options.aborted, ["o-grp1"])

    def test_refusals_say_why(self):
        self.assertIn("light", self.refused("set_group_members", {
            "entity_id": "light.kitchen_group", "add": ["switch.kettle"]}))
        self.assertIn("YAML", self.refused("set_group_members", {
            "entity_id": "light.porch_yaml_group", "add": ["light.hall"]}))
        self.assertIn("not in the group", self.refused("set_group_members", {
            "entity_id": "light.kitchen_group", "remove": ["light.hall"]}))
        self.assertIn("light.ghost", self.refused("set_group_members", {
            "entity_id": "light.kitchen_group", "add": ["light.ghost"]}))
        self.assertIn("at least one", self.refused("set_group_members", {
            "entity_id": "light.kitchen_group", "remove": ["light.kitchen_a"]}))


class TestIntegrationOptions(Case):
    def test_one_field_changes_and_the_rest_stays(self):
        result = self.run_tool("set_integration_options", {
            "config_entry_id": "w1", "options": {"scan_interval": 60}})
        self.assertEqual(self.ce.entries["w1"].options,
                         {"scan_interval": 60, "api_key": "abc123"})
        self.assertEqual(result["before"], {"scan_interval": 600})
        self.assertEqual(sorted(result["fields"]), ["api_key", "scan_interval"])

    def test_a_dry_run_names_the_fields_and_never_shows_a_secret(self):
        result = self.run_tool("set_integration_options", {
            "config_entry_id": "w1", "options": {"api_key": "new"}, "dry_run": True})
        self.assertEqual(result["after"], {"api_key": "**redacted**"})
        self.assertNotIn("abc123", repr(result))
        self.assertEqual(self.ce.options.configured, [])

    def test_a_field_the_form_does_not_have_is_named_with_the_ones_it_has(self):
        message = self.refused("set_integration_options", {
            "config_entry_id": "w1", "options": {"interval": 60}})
        self.assertIn("interval", message)
        self.assertIn("scan_interval", message)

    def test_a_second_step_is_refused_and_the_flow_aborted(self):
        message = self.refused("set_integration_options", {
            "config_entry_id": "t1", "options": {"mode": "b"}})
        self.assertIn("second step", message)
        self.assertIn("port", message)
        self.assertEqual(self.ce.entries["t1"].options, {"mode": "a"})
        self.assertIn("o-t1", self.ce.options.aborted)

    def test_a_menu_is_refused_naming_it(self):
        message = self.refused("set_integration_options", {
            "config_entry_id": "m1", "options": {"x": 1}})
        self.assertIn("menu", message)
        self.assertIn("advanced", message)

    def test_an_unknown_entry_and_one_with_no_options(self):
        self.assertIn("config_entry_id", self.refused("set_integration_options", {
            "config_entry_id": "zzz", "options": {"a": 1}}))
        self.ce.add("n1", "no_options", {})
        self.assertIn("no options", self.refused("set_integration_options", {
            "config_entry_id": "n1", "options": {"a": 1}}))


if __name__ == "__main__":
    unittest.main()
