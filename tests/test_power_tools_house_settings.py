#!/usr/bin/env python3
"""Z-Wave nodes, the energy dashboard, Home Assistant's own addresses and
Thread — Power Tools for what the owner did by hand over raw WebSocket,
driven through the real admin-gated handlers.

Each fake answers in the shape of the Core module it stands for:
`zwave_js.helpers.async_get_node_from_device_id` (a node whose
`client.driver.controller` has `async_remove_failed_node` and
`async_rebuild_node_routes`, `status` a NodeStatus whose name is
`dead`/`alive`), `energy.data.async_get_manager` (a manager with `data`
and `async_update`), `hass.config.async_update(internal_url=,
external_url=)`, and `thread.dataset_store` (`async_get_store`, a store with
`datasets` and `preferred_dataset`, `async_set_preferred_dataset`).
"""

from __future__ import annotations

import asyncio
import enum
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402


class NodeStatus(enum.IntEnum):
    UNKNOWN = 0
    ASLEEP = 1
    AWAKE = 2
    DEAD = 3
    ALIVE = 4


class Controller:
    def __init__(self):
        self.removed = []
        self.rebuilt = []

    async def async_remove_failed_node(self, node):
        self.removed.append(node.node_id)

    async def async_rebuild_node_routes(self, node):
        self.rebuilt.append(node.node_id)
        return True


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


class Registry:
    def __init__(self, items):
        self.items = items

    def async_get(self, key):
        return self.items.get(key)


class Config:
    def __init__(self):
        self.internal_url = None
        self.external_url = "https://old.example.com"
        self.updates = []

    async def async_update(self, **changes):
        self.updates.append(changes)
        for k, v in changes.items():
            setattr(self, k, v)


class EnergyManager:
    def __init__(self):
        self.data = {"energy_sources": [], "device_consumption": []}
        self.updates = []

    async def async_update(self, update):
        self.updates.append(update)
        self.data = {**self.data, **update}


class ThreadStore:
    def __init__(self):
        entry = lambda name, ch: types.SimpleNamespace(  # noqa: E731
            network_name=name, extended_pan_id="ab" * 8, pan_id="1234", channel=ch,
            source="Google", created=None, tlv="0e080000SECRETNETWORKKEY")
        self.datasets = {"D1": entry("home-net", 15), "D2": entry("old-net", 20)}
        self.preferred_dataset = "D2"


class Case(unittest.TestCase):
    def setUp(self):
        self.pkg = env.load_integration()
        self.controller = Controller()
        client = types.SimpleNamespace(driver=types.SimpleNamespace(controller=self.controller))
        nodes = {
            "dev_dead": types.SimpleNamespace(node_id=7, status=NodeStatus.DEAD, client=client),
            "dev_ok": types.SimpleNamespace(node_id=8, status=NodeStatus.ALIVE, client=client),
        }

        def node_for(hass, device_id):
            if device_id not in nodes:
                raise ValueError(f"Device {device_id} is not a Z-Wave device")
            return nodes[device_id]

        helpers = types.ModuleType("homeassistant.components.zwave_js.helpers")
        helpers.async_get_node_from_device_id = node_for
        self.energy = EnergyManager()
        energy_data = types.ModuleType("homeassistant.components.energy.data")

        async def get_manager(hass):
            return self.energy
        energy_data.async_get_manager = get_manager
        recorder = types.ModuleType("homeassistant.components.recorder")
        recorder.get_instance = lambda hass: types.SimpleNamespace(
            async_add_executor_job=self._run)
        statistics = types.ModuleType("homeassistant.components.recorder.statistics")
        statistics.get_metadata = lambda hass, statistic_ids=None: {
            s: (1, {"statistic_id": s}) for s in (statistic_ids or ())
            if s in {"sensor.grid_import", "sensor.grid_export", "sensor.dryer_energy"}}
        self.thread = ThreadStore()
        dataset_store = types.ModuleType("homeassistant.components.thread.dataset_store")

        async def get_store(hass):
            return self.thread

        async def set_preferred(hass, dataset_id):
            self.thread.preferred_dataset = dataset_id
        dataset_store.async_get_store = get_store
        dataset_store.async_set_preferred_dataset = set_preferred
        thread = types.ModuleType("homeassistant.components.thread")
        thread.dataset_store = dataset_store
        energy = types.ModuleType("homeassistant.components.energy")
        energy.data = energy_data
        mods = patch.dict(sys.modules, {
            "homeassistant.components.zwave_js": types.ModuleType("zwave_js"),
            "homeassistant.components.zwave_js.helpers": helpers,
            "homeassistant.components.energy": energy,
            "homeassistant.components.energy.data": energy_data,
            "homeassistant.components.recorder": recorder,
            "homeassistant.components.recorder.statistics": statistics,
            "homeassistant.components.thread": thread,
            "homeassistant.components.thread.dataset_store": dataset_store,
        })
        mods.start()
        self.addCleanup(mods.stop)
        recorder.statistics = statistics
        self.hass = types.SimpleNamespace(
            services=Services(), auth=Auth(), data={}, config=Config(),
            registries={
                "device": Registry({
                    "dev_dead": types.SimpleNamespace(id="dev_dead", name="Hall sensor",
                                                      name_by_user=None),
                    "dev_ok": types.SimpleNamespace(id="dev_ok", name="Lamp plug",
                                                    name_by_user=None),
                    "dev_hue": types.SimpleNamespace(id="dev_hue", name="Bulb",
                                                     name_by_user=None)}),
                "entity": Registry({"sensor.hall_motion": types.SimpleNamespace(
                    device_id="dev_dead")})})
        self.pkg.power_tools.async_register_power_tools(self.hass)

    async def _run(self, fn, *args):
        return fn(*args)

    def run_tool(self, name, data, user_id="admin"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data):
        with self.assertRaises(env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)


class TestZWave(Case):
    def test_a_dead_node_is_previewed_then_removed_and_named_by_its_entity(self):
        preview = self.run_tool("zwave_remove_failed_node", {"entity_id": "sensor.hall_motion"})
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["name"], "Hall sensor")
        self.assertEqual(self.controller.removed, [])
        self.run_tool("zwave_remove_failed_node", {"device_id": "dev_dead", "dry_run": False})
        self.assertEqual(self.controller.removed, [7])

    def test_a_working_node_is_never_removed_this_way(self):
        message = self.refused("zwave_remove_failed_node",
                               {"device_id": "dev_ok", "dry_run": False})
        self.assertIn("alive", message)
        self.assertEqual(self.controller.removed, [])

    def test_routes_are_rebuilt_and_a_non_zwave_device_is_named(self):
        self.assertTrue(self.run_tool("zwave_rebuild_node_routes",
                                      {"device_id": "dev_ok"})["rebuilt"])
        self.assertEqual(self.controller.rebuilt, [8])
        self.assertIn("Bulb", self.refused("zwave_rebuild_node_routes",
                                           {"device_id": "dev_hue"}))
        self.assertIn("device_id", self.refused("zwave_rebuild_node_routes", {}))


class TestEnergy(Case):
    SOURCES = [{"type": "grid",
                "flow_from": [{"stat_energy_from": "sensor.grid_import"}],
                "flow_to": [{"stat_energy_to": "sensor.grid_export"}]}]

    def test_prefs_are_read_and_a_save_is_previewed_first(self):
        self.assertTrue(self.run_tool("get_energy_prefs", {})["configured"])
        preview = self.run_tool("save_energy_prefs", {"energy_sources": self.SOURCES})
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["statistics"], ["sensor.grid_export", "sensor.grid_import"])
        self.assertEqual(self.energy.updates, [])
        self.run_tool("save_energy_prefs", {
            "device_consumption": [{"stat_consumption": "sensor.dryer_energy"}],
            "dry_run": False})
        self.assertEqual(self.energy.data["device_consumption"],
                         [{"stat_consumption": "sensor.dryer_energy"}])

    def test_a_statistic_nobody_keeps_is_refused_by_name(self):
        message = self.refused("save_energy_prefs", {
            "device_consumption": [{"stat_consumption": "sensor.ghost_plug"}],
            "dry_run": False})
        self.assertIn("sensor.ghost_plug", message)
        self.assertEqual(self.energy.updates, [])


class TestCoreUrls(Case):
    def test_addresses_are_set_and_cleared(self):
        result = self.run_tool("set_core_urls", {
            "internal_url": "http://192.168.1.10:8123/", "external_url": ""})
        self.assertEqual(self.hass.config.internal_url, "http://192.168.1.10:8123")
        self.assertIsNone(self.hass.config.external_url)
        self.assertEqual(result["before"]["external_url"], "https://old.example.com")

    def test_a_bad_address_names_the_field(self):
        for bad in ("home.example.com", "ftp://x", "https://x.example.com/lovelace"):
            self.assertIn("internal_url", self.refused("set_core_urls",
                                                       {"internal_url": bad}))
        self.assertEqual(self.hass.config.updates, [])


class TestThread(Case):
    def test_datasets_are_listed_without_the_network_key(self):
        result = self.run_tool("list_thread_datasets", {})
        self.assertEqual(result["preferred"], "D2")
        self.assertEqual({r["network_name"] for r in result["datasets"]},
                         {"home-net", "old-net"})
        self.assertNotIn("SECRETNETWORKKEY", repr(result))

    def test_the_preferred_one_is_set_and_an_unknown_one_named(self):
        self.run_tool("set_preferred_thread_dataset", {"dataset_id": "D1"})
        self.assertEqual(self.thread.preferred_dataset, "D1")
        self.assertIn("home-net", self.refused("set_preferred_thread_dataset",
                                               {"dataset_id": "D9"}))


if __name__ == "__main__":
    unittest.main()
