"""The bruh_task_manager integration, loaded for real behind a little Home Assistant.

The entities are the half a person sees in Home Assistant, so they are run
rather than read: the numeric sensors go unavailable when the add-on stops
measuring, and the runaway sensor goes UNKNOWN (never off) with its reason.
`sys.modules` is put back as it was found, so the stubs cannot leak into
another test module.
"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INTEGRATION = REPO / "bruh-task-manager" / "custom_components" / "bruh_task_manager"


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls

    @property
    def available(self):
        return True


class DataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.data = None

    def __class_getitem__(cls, item):
        return cls


class _Names:
    def __getattr__(self, name):
        return name.lower()


def _stubs():
    def mod(name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        return module

    class SensorEntity:
        pass

    class BinarySensorEntity:
        pass

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            pass

    return {
        "homeassistant": mod("homeassistant"),
        "homeassistant.core": mod("homeassistant.core", HomeAssistant=object),
        "homeassistant.const": mod("homeassistant.const", Platform=_Names(), PERCENTAGE="%"),
        "homeassistant.config_entries": mod("homeassistant.config_entries", ConfigEntry=object,
                                            ConfigFlow=ConfigFlow, ConfigFlowResult=dict),
        "homeassistant.helpers": mod("homeassistant.helpers"),
        "homeassistant.helpers.config_validation": mod(
            "homeassistant.helpers.config_validation",
            config_entry_only_config_schema=lambda domain: None),
        "homeassistant.helpers.entity_platform": mod("homeassistant.helpers.entity_platform",
                                                     AddEntitiesCallback=object),
        "homeassistant.helpers.update_coordinator": mod(
            "homeassistant.helpers.update_coordinator",
            CoordinatorEntity=CoordinatorEntity, DataUpdateCoordinator=DataUpdateCoordinator),
        "homeassistant.components": mod("homeassistant.components"),
        "homeassistant.components.sensor": mod("homeassistant.components.sensor",
                                               SensorEntity=SensorEntity,
                                               SensorStateClass=_Names()),
        "homeassistant.components.binary_sensor": mod(
            "homeassistant.components.binary_sensor",
            BinarySensorEntity=BinarySensorEntity, BinarySensorDeviceClass=_Names()),
    }


def load():
    saved = dict(sys.modules)
    sys.modules.update(_stubs())
    package = types.ModuleType("bruh_task_manager")
    package.__path__ = [str(INTEGRATION)]
    sys.modules["bruh_task_manager"] = package
    try:
        names = ("sensor", "binary_sensor", "config_flow")
        mods = {n: importlib.import_module(f"bruh_task_manager.{n}") for n in names}
        importlib.import_module("bruh_task_manager")
        return mods
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


MODS = load()


class Entry:
    entry_id = "e1"


class Coord:
    def __init__(self, data):
        self.data = data


FRESH = {
    "available": True,
    "machine": {"cpu": 41.5, "mem_percent": 62.0, "mem_used": 1, "mem_total": 2,
                "cpus": 4, "load": [1.0, 0.5, 0.2]},
    "busiest": {"name": "Frigate", "slug": "ccab4aaf_frigate", "cpu": 77.0, "memory_mb": 900},
    "top": [{"name": "Frigate"}],
    "runaway": {"threshold": 80, "minutes": 10,
                "apps": [{"name": "Frigate", "slug": "ccab4aaf_frigate", "cpu": 91,
                          "minutes": 12.0}]},
    "level": 1,
}
STALE = {"available": False, "reason": "The add-on has not measured for 9 min; it may be stopped."}


class TestEntities(unittest.TestCase):
    def sensors(self, data):
        s = MODS["sensor"]
        coord = Coord(data)
        return {
            "cpu": s.MachineCpuSensor(coord, Entry(), "cpu"),
            "memory": s.MachineMemorySensor(coord, Entry(), "memory"),
            "busiest": s.BusiestAppSensor(coord, Entry(), "busiest_app"),
            "busiest_cpu": s.BusiestAppCpuSensor(coord, Entry(), "busiest_app_cpu"),
        }

    def test_fresh_readings_are_reported(self):
        e = self.sensors(FRESH)
        self.assertEqual(41.5, e["cpu"].native_value)
        self.assertEqual(62.0, e["memory"].native_value)
        self.assertEqual("Frigate", e["busiest"].native_value)
        self.assertEqual("ccab4aaf_frigate", e["busiest"].extra_state_attributes["slug"])
        self.assertEqual(77.0, e["busiest_cpu"].native_value)
        self.assertTrue(all(x.available for x in e.values()))
        self.assertEqual("e1_cpu", e["cpu"]._attr_unique_id)

    def test_a_stale_mirror_makes_measurements_unavailable(self):
        self.assertFalse(any(x.available for x in self.sensors(STALE).values()))

    def test_runaway_is_on_with_the_slug_an_automation_needs(self):
        b = MODS["binary_sensor"].RunawayBinarySensor(Coord(FRESH), Entry(), "runaway_app")
        self.assertTrue(b.is_on)
        attrs = b.extra_state_attributes
        self.assertEqual("ccab4aaf_frigate", attrs["apps"][0]["slug"])
        self.assertEqual(80, attrs["threshold_percent"])
        self.assertEqual("", attrs["reason"])

    def test_runaway_is_unknown_not_off_when_nothing_is_measuring(self):
        b = MODS["binary_sensor"].RunawayBinarySensor(Coord(STALE), Entry(), "runaway_app")
        self.assertIsNone(b.is_on)
        self.assertIn("may be stopped", b.extra_state_attributes["reason"])

    def test_runaway_is_off_when_measuring_and_calm(self):
        calm = dict(FRESH, runaway={"threshold": 80, "minutes": 10, "apps": []})
        b = MODS["binary_sensor"].RunawayBinarySensor(Coord(calm), Entry(), "runaway_app")
        self.assertFalse(b.is_on)

    def test_stubs_did_not_leak(self):
        self.assertNotIn("bruh_task_manager", sys.modules)
        self.assertNotIn("homeassistant.helpers.update_coordinator",
                         {k for k, v in sys.modules.items()
                          if getattr(v, "DataUpdateCoordinator", None) is DataUpdateCoordinator})


if __name__ == "__main__":
    unittest.main()
