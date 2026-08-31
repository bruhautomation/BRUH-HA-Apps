#!/usr/bin/env python3
"""A via_device chain that points back at itself.

`brain.disable_device` walks `via_device_id` up to the hub a device hangs
off, so that disabling the last live child disables the lonely parent too.
Nothing in Home Assistant makes that chain acyclic — `via_device_id` is
whatever id an integration reported — and `alexa_media` reports every
device as its OWN via_device. Walked by recursion, that chain has no end:
the service raised RecursionError on each of seven Echo/Wyze/Ecobee devices
after writing some of the disables, which is the worst place for a registry
walk to stop.

These tests reproduce the old recursion failing before pinning the shipped
walk, because a guard measured against a demonstrated failure is worth more
than one measured against a described one. power_tools.py imports the whole
Home Assistant helper surface plus voluptuous, none of it installed here, so
the module is imported through permissive stubs — the walks under test touch
only the registry object handed to them.
"""

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"


class _AutoModule(types.ModuleType):
    """A module whose every attribute exists. Enough to get power_tools
    imported: the schemas it builds at import time are never called here."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


def _import_power_tools():
    """Import power_tools behind permissive stubs, leaving sys.modules as it
    was found.

    Several other test modules install their own partial `homeassistant`
    stubs, and whichever runs first wins a shared sys.modules — which is how
    this file first failed only under `unittest discover`, on
    `cannot import name 'ServiceCall'`. So the stubs go in, the module comes
    out, and the table is put back exactly as it was: no other test can
    starve this import, and this import cannot hand another test a mock
    where it installed a class.
    """
    saved = dict(sys.modules)
    try:
        for name in (
            "voluptuous",
            "homeassistant",
            "homeassistant.config_entries",
            "homeassistant.core",
            "homeassistant.exceptions",
            "homeassistant.helpers",
            "homeassistant.helpers.area_registry",
            "homeassistant.helpers.config_validation",
            "homeassistant.helpers.device_registry",
            "homeassistant.helpers.entity_registry",
            "homeassistant.helpers.floor_registry",
            "homeassistant.helpers.issue_registry",
            "homeassistant.helpers.label_registry",
        ):
            sys.modules[name] = _AutoModule(name)
        # `@callback` is HA's own marker decorator and hands back the
        # function it is given; a MagicMock in its place would replace every
        # function in the module with a mock.
        sys.modules["homeassistant.core"].callback = lambda func: func
        # A stand-in parent package pointing at the integration directory, so
        # `.const` resolves without executing the real package __init__.
        pkg = types.ModuleType("brain_cc")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_cc"] = pkg
        for stale in [m for m in sys.modules if m.startswith("brain_cc.")]:
            del sys.modules[stale]
        return importlib.import_module("brain_cc.power_tools")
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


power_tools = _import_power_tools()

DISABLED_BY_USER = power_tools.dr.DeviceEntryDisabler.USER


class _Device:
    def __init__(self, device_id, via_device_id=None, disabled_by=None):
        self.id = device_id
        self.via_device_id = via_device_id
        self.disabled_by = disabled_by


class _Registry:
    """The slice of dr.DeviceRegistry the two walks use."""

    def __init__(self, devices):
        self.devices = {d.id: d for d in devices}
        self.writes: list[tuple[str, object]] = []

    def async_get(self, device_id):
        return self.devices.get(device_id)

    def async_update_device(self, device_id, **changes):
        device = self.devices[device_id]
        for key, value in changes.items():
            setattr(device, key, value)
        self.writes.append((device_id, changes.get("disabled_by")))
        return device


def _alexa_media_household():
    """Seven devices, each its own via_device — the reported registry."""
    return _Registry(
        [_Device(f"echo_{i}", via_device_id=f"echo_{i}") for i in range(7)]
    )


# The implementations as they shipped before the cycle guard, kept here so
# the failure is demonstrated rather than asserted about.


def _old_disable(registry, device_id):
    device = registry.async_get(device_id)
    if device is None:
        return
    if device.disabled_by is None:
        registry.async_update_device(device_id, disabled_by=DISABLED_BY_USER)
    if device.via_device_id is None:
        return
    if all(
        child.id == device_id or child.disabled_by is not None
        for child in registry.devices.values()
        if child.via_device_id == device.via_device_id
    ):
        _old_disable(registry, device.via_device_id)


def _old_enable(registry, device_id):
    device = registry.async_get(device_id)
    if device is None:
        return
    if device.via_device_id is not None:
        _old_enable(registry, device.via_device_id)
    registry.async_update_device(device_id, disabled_by=None)


class TestTheOldRecursionActuallyFailed(unittest.TestCase):
    def test_disable_blew_the_stack_on_a_self_referential_device(self):
        registry = _alexa_media_household()
        with self.assertRaises(RecursionError):
            _old_disable(registry, "echo_0")

    def test_enable_blew_the_stack_too(self):
        registry = _alexa_media_household()
        with self.assertRaises(RecursionError):
            _old_enable(registry, "echo_0")


class TestDisableSurvivesACycle(unittest.TestCase):
    def test_a_device_that_is_its_own_via_device_is_simply_disabled(self):
        registry = _alexa_media_household()
        for device_id in sorted(registry.devices):
            power_tools._disable_device_and_parent_if_needed(
                registry, device_id
            )
        self.assertEqual(
            {d.disabled_by for d in registry.devices.values()},
            {DISABLED_BY_USER},
        )

    def test_a_self_referential_device_is_written_once(self):
        registry = _Registry([_Device("echo", via_device_id="echo")])
        power_tools._disable_device_and_parent_if_needed(registry, "echo")
        self.assertEqual(registry.writes, [("echo", DISABLED_BY_USER)])

    def test_a_two_device_loop_disables_both_and_stops(self):
        registry = _Registry(
            [
                _Device("a", via_device_id="b"),
                _Device("b", via_device_id="a"),
            ]
        )
        power_tools._disable_device_and_parent_if_needed(registry, "a")
        self.assertEqual(
            [w[0] for w in registry.writes], ["a", "b"]
        )
        self.assertTrue(
            all(d.disabled_by is not None for d in registry.devices.values())
        )


class TestDisableStillClimbsARealChain(unittest.TestCase):
    """The cycle guard must not cost the behaviour the walk exists for."""

    def test_the_last_live_child_takes_its_lonely_hub_with_it(self):
        registry = _Registry(
            [
                _Device("hub", via_device_id="bridge"),
                _Device("bridge"),
                _Device("bulb", via_device_id="hub"),
            ]
        )
        power_tools._disable_device_and_parent_if_needed(registry, "bulb")
        self.assertEqual(
            [w[0] for w in registry.writes], ["bulb", "hub", "bridge"]
        )

    def test_a_hub_with_an_enabled_sibling_left_stays_enabled(self):
        registry = _Registry(
            [
                _Device("hub"),
                _Device("bulb_a", via_device_id="hub"),
                _Device("bulb_b", via_device_id="hub"),
            ]
        )
        power_tools._disable_device_and_parent_if_needed(registry, "bulb_a")
        self.assertEqual([w[0] for w in registry.writes], ["bulb_a"])
        self.assertIsNone(registry.devices["hub"].disabled_by)

    def test_an_already_disabled_device_is_not_written_again(self):
        registry = _Registry(
            [
                _Device("hub"),
                _Device("bulb", via_device_id="hub",
                        disabled_by=DISABLED_BY_USER),
            ]
        )
        power_tools._disable_device_and_parent_if_needed(registry, "bulb")
        self.assertEqual([w[0] for w in registry.writes], ["hub"])

    def test_a_via_parent_the_registry_has_lost_ends_the_walk(self):
        registry = _Registry([_Device("bulb", via_device_id="ghost")])
        power_tools._disable_device_and_parent_if_needed(registry, "bulb")
        self.assertEqual([w[0] for w in registry.writes], ["bulb"])


class TestEnableSurvivesACycle(unittest.TestCase):
    def test_a_self_referential_device_is_enabled_once(self):
        registry = _Registry(
            [_Device("echo", via_device_id="echo",
                     disabled_by=DISABLED_BY_USER)]
        )
        power_tools._enable_device_and_parents(registry, "echo")
        self.assertEqual(registry.writes, [("echo", None)])
        self.assertIsNone(registry.devices["echo"].disabled_by)

    def test_a_two_device_loop_enables_both(self):
        registry = _Registry(
            [
                _Device("a", via_device_id="b",
                        disabled_by=DISABLED_BY_USER),
                _Device("b", via_device_id="a",
                        disabled_by=DISABLED_BY_USER),
            ]
        )
        power_tools._enable_device_and_parents(registry, "a")
        self.assertTrue(
            all(d.disabled_by is None for d in registry.devices.values())
        )


class TestEnableStillEnablesParentsFirst(unittest.TestCase):
    def test_the_chain_is_written_root_first(self):
        """A child enabled under a still-disabled parent is a moment HA can
        observe, and it is the order the recursion produced."""
        registry = _Registry(
            [
                _Device("bridge", disabled_by=DISABLED_BY_USER),
                _Device("hub", via_device_id="bridge",
                        disabled_by=DISABLED_BY_USER),
                _Device("bulb", via_device_id="hub",
                        disabled_by=DISABLED_BY_USER),
            ]
        )
        power_tools._enable_device_and_parents(registry, "bulb")
        self.assertEqual(
            [w[0] for w in registry.writes], ["bridge", "hub", "bulb"]
        )

    def test_a_missing_parent_does_not_stop_the_device_being_enabled(self):
        registry = _Registry(
            [_Device("bulb", via_device_id="ghost",
                     disabled_by=DISABLED_BY_USER)]
        )
        power_tools._enable_device_and_parents(registry, "bulb")
        self.assertEqual([w[0] for w in registry.writes], ["bulb"])


class TestTheChainWalkIsBounded(unittest.TestCase):
    def test_every_id_appears_at_most_once(self):
        registry = _Registry(
            [
                _Device("a", via_device_id="b"),
                _Device("b", via_device_id="c"),
                _Device("c", via_device_id="a"),
            ]
        )
        chain = power_tools._via_device_chain(registry, "a")
        self.assertEqual(chain, ["a", "b", "c"])

    def test_a_self_reference_is_a_chain_of_one(self):
        registry = _Registry([_Device("echo", via_device_id="echo")])
        self.assertEqual(
            power_tools._via_device_chain(registry, "echo"), ["echo"]
        )


class TestNoDeviceWalkRecursesAnyMore(unittest.TestCase):
    """A new walk over via_device_id must not reintroduce the shape. The
    registry is somebody else's data; recursion over it is a stack depth
    chosen by an integration."""

    def test_power_tools_has_no_self_calling_via_device_walk(self):
        import ast

        source = (INTEGRATION_DIR / "power_tools.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        for func in ast.walk(tree):
            if not isinstance(func, ast.FunctionDef):
                continue
            body = ast.dump(func)
            if "via_device_id" not in body:
                continue
            calls = {
                node.func.id
                for node in ast.walk(func)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
            }
            self.assertNotIn(
                func.name,
                calls,
                f"{func.name} recurses while walking via_device_id",
            )


if __name__ == "__main__":
    unittest.main()
