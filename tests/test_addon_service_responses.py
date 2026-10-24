#!/usr/bin/env python3
"""Every add-on service brAIn calls is registered to answer.

brAIn's MCP server calls each BRUH add-on's services with
`return_response=True` (`ha_mcp_server._addon_call`), so it can repeat
the add-on's own sentence to the person. Core refuses that call outright
for a service registered without response support — before the add-on is
ever asked — which is how `bright_show` failed on every channel and
`minecraft_server` restart/stop failed in chat, while the MCP tests passed
against a fake Core that accepted any service with a response.

So the two halves are read from the code that ships: the (domain, service)
pairs `_addon_call` is handed, by AST, and what each integration really
registers, by running its own `_register_services` against a fake `hass`.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MCP = REPO / "brain" / "ha-mcp-server" / "ha_mcp_server.py"
INTEGRATIONS = {
    "bruh_minecraft": REPO / "bruh-minecraft-server" / "custom_components" / "bruh_minecraft",
    "bright": REPO / "bright" / "custom_components" / "bright",
    "bruh_print": REPO / "bruh-print" / "custom_components" / "bruh_print",
    "bruh_bambu": REPO / "bruh-bambu-studio" / "custom_components" / "bruh_bambu",
    "gardenrx": REPO / "gardenrx" / "custom_components" / "gardenrx",
}
RESPONDS = ("optional", "only")


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any()


class _Any(metaclass=_Meta):
    """Accepts any construction, call, attribute or subscript."""

    def __init__(self, *a, **kw):
        pass

    def __call__(self, *a, **kw):
        return a[0] if a else self

    def __getattr__(self, name):
        return _Any()

    def __class_getitem__(cls, item):
        return cls

    def __getitem__(self, item):
        return _Any()


class _Module(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


def _stubs() -> dict:
    names = ("voluptuous", "homeassistant", "homeassistant.config_entries",
             "homeassistant.const", "homeassistant.core", "homeassistant.exceptions",
             "homeassistant.helpers", "homeassistant.helpers.config_validation",
             "homeassistant.helpers.update_coordinator",
             "homeassistant.helpers.issue_registry", "homeassistant.helpers.event",
             "homeassistant.helpers.entity_platform", "homeassistant.components",
             "homeassistant.components.sensor", "homeassistant.data_entry_flow",
             "homeassistant.helpers.device_registry", "homeassistant.helpers.entity",
             "homeassistant.helpers.aiohttp_client")
    mods = {name: _Module(name) for name in names}
    mods["homeassistant.core"].SupportsResponse = types.SimpleNamespace(
        NONE=None, OPTIONAL="optional", ONLY="only")

    class HomeAssistantError(Exception):
        pass

    mods["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    mods["homeassistant.exceptions"].ServiceValidationError = HomeAssistantError
    mods["homeassistant.core"].callback = lambda f: f
    return mods


def registered(domain: str) -> dict:
    """{service: supports_response} as the integration registers them."""
    stubs = _stubs()
    saved = {k: sys.modules.get(k) for k in stubs}
    pkg = f"_responses_{domain}"
    sys.modules.update(stubs)
    try:
        for mod in [m for m in sys.modules if m.startswith(pkg)]:
            sys.modules.pop(mod)
        folder = INTEGRATIONS[domain]
        spec = importlib.util.spec_from_file_location(
            pkg, folder / "__init__.py", submodule_search_locations=[str(folder)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[pkg] = module
        spec.loader.exec_module(module)
        seen: dict = {}

        class Services:
            def async_register(self, dom, name, handler, schema=None,
                               supports_response=None):
                seen[name] = (supports_response, handler)

            def has_service(self, dom, name):
                return name in seen

        module._register_services(types.SimpleNamespace(
            services=Services(), data={}, bus=_Any(), loop=None))
        return seen
    finally:
        # Other test modules install partial homeassistant stubs, and the
        # first to load wins a shared table: put back what was there.
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def called_by_brain() -> set:
    """(domain, service) for every `_addon_call` with literal arguments."""
    pairs = set()
    tree = ast.parse(MCP.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_addon_call"
                and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)):
            domain = node.args[0].value
            service = node.args[1]
            if isinstance(service, ast.Constant):
                pairs.add((domain, service.value))
    # The two calls whose service is picked from a table.
    for name in ("MC_ADMIN_ACTIONS",):
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == name for t in node.targets)):
                for value in ast.literal_eval(node.value).values():
                    pairs.add(("bruh_minecraft", value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef) and node.name == "minecraft_server"):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict) and any(
                        isinstance(k, ast.Constant) and k.value == "restart"
                        for k in sub.keys):
                    for v in sub.values:
                        pairs.add(("bruh_minecraft", v.value))
    return pairs


class TestEveryCallIsAnswerable(unittest.TestCase):
    def test_brain_calls_the_services_it_thinks_it_does(self):
        pairs = called_by_brain()
        # The two that failed in the field are in the set being checked,
        # or the test below would pass by having nothing to look at.
        for want in (("bright", "start_party"), ("bright", "stop_show"),
                     ("bruh_minecraft", "restart_server"),
                     ("bruh_minecraft", "stop_server"), ("bruh_print", "print_text")):
            self.assertIn(want, pairs)

    def test_every_service_brain_calls_answers_with_a_response(self):
        services = {domain: registered(domain) for domain in INTEGRATIONS}
        for domain, service in sorted(called_by_brain()):
            with self.subTest(service=f"{domain}.{service}"):
                self.assertIn(service, services[domain],
                              f"{domain}.{service} is not registered at all")
                self.assertIn(services[domain][service][0], RESPONDS,
                              f"{domain}.{service} is registered without response "
                              "support, so brAIn's return_response call is refused")

    def test_bright_actions_hand_back_the_add_ons_answer(self):
        stubs = _stubs()
        seen = registered("bright")
        handler = seen["start_party"][1]
        module = sys.modules.get("_responses_bright")
        answer = {"ok": True, "status": "running", "tracks": 12}

        async def fake_forward(kind, data):
            return answer

        saved = {k: sys.modules.get(k) for k in stubs}
        sys.modules.update(stubs)
        try:
            handler.__globals__["_forward"] = fake_forward
            got = asyncio.run(handler(types.SimpleNamespace(data={"party": "Friday"})))
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.assertIsNotNone(module)
        self.assertEqual(got, {"status": "running", "tracks": 12})


if __name__ == "__main__":
    unittest.main()
