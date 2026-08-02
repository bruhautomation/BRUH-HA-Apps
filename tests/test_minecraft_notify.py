#!/usr/bin/env python3
"""Behaviour tests for the notify platform.

The NotifyEntity wraps the add-on's file-IPC bridge. We stub `send_request`
and assert the correct RCON command is produced for each case:

- plain message -> /say ...
- message + title -> /tellraw @a <json>
- message clamped to 256 chars + newlines stripped
- empty message -> no command
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PKG_DIR = BASE_DIR / "bruh-minecraft-server" / "custom_components" / "bruh_minecraft"


def _install_ha_stubs() -> tuple[types.ModuleType, list[dict]]:
    """Install Home Assistant stubs sufficient to import notify.py.

    Returns (bridge_module, captured_requests_list).
    The test patches bridge.send_request to record what notify would send.
    """
    captured: list[dict] = []

    # --- voluptuous ---
    if "voluptuous" not in sys.modules:
        sys.modules["voluptuous"] = types.ModuleType("voluptuous")

    # --- homeassistant stubs ---
    for name in (
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.device_registry",
        "homeassistant.components",
        "homeassistant.components.notify",
    ):
        sys.modules.setdefault(name, types.ModuleType(name))

    class _HomeAssistant: pass
    sys.modules["homeassistant.core"].HomeAssistant = _HomeAssistant

    class _ConfigEntry:
        entry_id = "test"
    sys.modules["homeassistant.config_entries"].ConfigEntry = _ConfigEntry


    class _AnyAttrMeta(type):
        def __getattr__(cls, name: str):
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            return name

    class _Generic(metaclass=_AnyAttrMeta):
        def __init__(self, *a, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class _NotifyEntity:
        _attr_supported_features = 0

        def __init__(self, *a, **kw): pass

        def __class_getitem__(cls, item): return cls

    class _NotifyEntityFeature:
        TITLE = 1

    sys.modules["homeassistant.components.notify"].NotifyEntity = _NotifyEntity
    sys.modules["homeassistant.components.notify"].NotifyEntityFeature = _NotifyEntityFeature

    class _DUC:
        def __init__(self, *a, **kw): self.data = None
        def __class_getitem__(cls, item): return cls
    class _CE:
        def __init__(self, coordinator, *a, **kw):
            self.coordinator = coordinator
        def __class_getitem__(cls, item): return cls

    sys.modules["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _DUC
    sys.modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = _CE
    sys.modules["homeassistant.helpers.device_registry"].DeviceInfo = _Generic
    sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = _Generic

    pkg_name = "bruh_mc_notify_test_pkg"
    # Ensure a fresh import tree every call
    for m in list(sys.modules):
        if m.startswith(pkg_name):
            sys.modules.pop(m)
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(PKG_DIR)]
    sys.modules[pkg_name] = pkg

    # Load const + entity + coordinator + bridge + notify
    def _exec(name: str) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{name}", str(PKG_DIR / f"{name}.py"),
        )
        module = importlib.util.module_from_spec(spec)
        module.__package__ = pkg_name
        sys.modules[f"{pkg_name}.{name}"] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    _exec("const")
    bridge = _exec("bridge")
    _exec("coordinator")
    _exec("entity")
    notify = _exec("notify")

    # Replace bridge.send_request with a recorder
    async def _fake_send_request(kind: str, payload: dict, timeout: float = 15.0) -> dict:
        captured.append({"kind": kind, "payload": payload})
        return {"ok": True, "reply": ""}

    bridge.send_request = _fake_send_request
    notify.send_request = _fake_send_request

    return notify, captured


class BaseNotifyTest(unittest.TestCase):
    def setUp(self):
        self.notify_mod, self.captured = _install_ha_stubs()

    def _new_entity(self):
        class DummyCoordinator:
            data = None
        entity = self.notify_mod.BruhMinecraftNotify(DummyCoordinator())
        return entity

    def _send(self, message: str, title: str | None = None):
        asyncio.run(self._new_entity().async_send_message(message, title=title))


class TestNotifyBehaviour(BaseNotifyTest):
    def test_plain_message_uses_say(self):
        self._send("Hello from HA")
        self.assertEqual(len(self.captured), 1)
        self.assertEqual(self.captured[0]["kind"], "command")
        self.assertEqual(self.captured[0]["payload"]["command"], "say Hello from HA")

    def test_newlines_are_stripped_from_say(self):
        self._send("Line 1\nLine 2\r\nLine 3")
        cmd = self.captured[0]["payload"]["command"]
        self.assertNotIn("\n", cmd)
        self.assertNotIn("\r", cmd)
        self.assertTrue(cmd.startswith("say "))

    def test_say_clamps_to_256_chars(self):
        body = "x" * 400
        self._send(body)
        cmd = self.captured[0]["payload"]["command"]
        # "say " + clamped message
        self.assertEqual(len(cmd) - len("say "), 256)

    def test_message_with_title_uses_tellraw(self):
        self._send("The kids are home!", title="BRUH Alert")
        self.assertEqual(len(self.captured), 1)
        cmd = self.captured[0]["payload"]["command"]
        self.assertTrue(cmd.startswith("tellraw @a "))
        payload_json = cmd[len("tellraw @a ") :]
        components = json.loads(payload_json)
        self.assertIsInstance(components, list)
        self.assertEqual(components[0]["text"], "BRUH Alert")
        self.assertTrue(components[0]["bold"])
        # Last component contains the message body
        self.assertIn("The kids are home!", [c.get("text", "") for c in components])

    def test_empty_message_sends_nothing(self):
        self._send("")
        self.assertEqual(self.captured, [])
        self._send("   ")
        self.assertEqual(self.captured, [])

    def test_notify_entity_feature_title_supported(self):
        """notify.send_message must accept a title so automations can pass one."""
        entity = self._new_entity()
        self.assertEqual(
            entity._attr_supported_features,
            self.notify_mod.NotifyEntityFeature.TITLE,
        )


if __name__ == "__main__":
    unittest.main()
