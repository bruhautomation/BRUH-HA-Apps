#!/usr/bin/env python3
"""A new brAIn agent starts with the administration services denied.

Every way an agent is created — the first-run setup, Supervisor discovery
and "add agent" — wrote no deny-list at all, so the curated high-risk
patterns were offered in a multi-select and applied to nobody. The MCP
server now refuses entity-less administration on a "Voice assistant" level
agent by itself (tests/test_mcp_chokepoint.py); this is the other half, the
one that reaches an agent somebody sets to "Whole house", and the half a
person can see and change.

The real flow is driven: config_flow.py imports Home Assistant's config
entry and selector surface and voluptuous, none of it installed here, so it
is imported behind stubs that implement exactly the flow methods it calls —
`async_create_entry` and `async_show_form` hand back what they were given —
and `sys.modules` is put back afterwards (test_power_tools_device_cycles'
rule: a shared module table is not this file's to leave changed).
"""

import asyncio
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

INTEGRATION_DIR = (Path(__file__).resolve().parent.parent
                   / "brain" / "custom_components" / "brain")


class _AutoModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


class _Marker:
    """vol.Optional / vol.Required: the key and its default, readable back."""

    def __init__(self, key, default=None, **_kw):
        self.key = key
        self.default = default


class _Flow:
    def __init_subclass__(cls, domain=None, **kw):
        super().__init_subclass__(**kw)

    async def async_set_unique_id(self, unique_id):
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self):
        return None

    def _async_current_entries(self):
        return []

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id, data_schema=None, errors=None,
                        description_placeholders=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}


def _import_config_flow():
    saved = dict(sys.modules)
    try:
        vol = types.ModuleType("voluptuous")
        vol.Optional = vol.Required = _Marker
        vol.Schema = lambda fields: fields
        vol.In = lambda values: ("in", values)
        vol.All = lambda *parts: parts
        vol.Range = lambda **bounds: bounds
        sys.modules["voluptuous"] = vol
        for name in ("homeassistant", "homeassistant.helpers",
                     "homeassistant.helpers.selector"):
            sys.modules[name] = _AutoModule(name)
        entries = types.ModuleType("homeassistant.config_entries")
        entries.ConfigFlow = _Flow
        entries.OptionsFlow = type("OptionsFlow", (), {})
        entries.ConfigEntry = type("ConfigEntry", (), {})
        sys.modules["homeassistant.config_entries"] = entries
        hassio = types.ModuleType("homeassistant.helpers.service_info.hassio")
        hassio.HassioServiceInfo = type("HassioServiceInfo", (), {})
        sys.modules["homeassistant.helpers.service_info"] = types.ModuleType(
            "homeassistant.helpers.service_info")
        sys.modules["homeassistant.helpers.service_info.hassio"] = hassio
        pkg = types.ModuleType("brain_cc")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_cc"] = pkg
        for stale in [m for m in sys.modules if m.startswith("brain_cc.")]:
            del sys.modules[stale]
        return importlib.import_module("brain_cc.config_flow")
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


class _Hass:
    def __init__(self, shared):
        self.config = types.SimpleNamespace(path=lambda *p: shared)
        self.services = types.SimpleNamespace(async_services=lambda: {})

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class TestANewAgentDeniesAdministration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cf = _import_config_flow()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def flow(self):
        flow = self.cf.BruhClaudeConfigFlow()
        flow.hass = _Hass(self.tmp.name)
        return flow

    def run_step(self, coro):
        return asyncio.run(coro)

    def test_the_seed_is_administration_and_nothing_people_ask_voice_for(self):
        seed = set(self.cf.NEW_AGENT_DENIED_SERVICES)
        for admin in ("homeassistant.restart", "hassio.host_shutdown",
                      "update.install", "brain.*", "shell_command.*"):
            self.assertIn(admin, seed)
        # "Open the blinds" and "run the goodnight script" stay possible; a
        # new agent that refused them would teach people to clear the list.
        for everyday in ("cover.open_cover", "script.*", "lock.unlock"):
            self.assertNotIn(everyday, seed)
        self.assertTrue(seed <= set(self.cf.CURATED_DENY_PATTERNS),
                        "every seeded pattern is one the form already offers")

    def test_the_first_agent_is_created_with_it(self):
        got = self.run_step(self.flow().async_step_first_setup({"name": "brAIn"}))
        self.assertEqual(got["type"], "create_entry")
        self.assertEqual(got["data"]["denied_services"],
                         self.cf.NEW_AGENT_DENIED_SERVICES)

    def test_a_discovered_agent_is_created_with_it(self):
        got = self.run_step(self.flow().async_step_hassio_confirm({}))
        self.assertEqual(got["type"], "create_entry")
        self.assertEqual(got["data"]["denied_services"],
                         self.cf.NEW_AGENT_DENIED_SERVICES)

    def test_an_added_agent_sees_it_ticked_and_can_untick_it(self):
        form = self.run_step(self.flow().async_step_add_agent(None))
        marker = next(k for k in form["data_schema"]
                      if getattr(k, "key", None) == "denied_services")
        self.assertEqual(marker.default, self.cf.NEW_AGENT_DENIED_SERVICES)
        # What the person submits is what is stored — an empty list included.
        got = self.run_step(self.flow().async_step_add_agent(
            {"name": "Owner", "access": "admin", "denied_services": []}))
        self.assertEqual(got["data"]["denied_services"], [])

    def test_the_seed_is_a_copy_not_the_constant(self):
        got = self.run_step(self.flow().async_step_first_setup({"name": "brAIn"}))
        got["data"]["denied_services"].append("light.*")
        self.assertNotIn("light.*", self.cf.NEW_AGENT_DENIED_SERVICES)


if __name__ == "__main__":
    unittest.main()
