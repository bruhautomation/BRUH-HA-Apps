"""The gardenrx integration, loaded for real behind just enough Home Assistant.

What the code branches on is a real class here (the error it raises, the
response flag it registers with, the coordinator it reads); what it merely
imports is an auto-module. `sys.modules` is put back as it was found, so the
stubs cannot leak into another test module's (brain_ha_env's rule).
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import enum
import importlib
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INTEGRATION = REPO / "gardenrx" / "custom_components" / "gardenrx"


class HomeAssistantError(Exception):
    pass


class SupportsResponse(enum.Enum):
    NONE = "none"
    OPTIONAL = "optional"
    ONLY = "only"


class UpdateFailed(Exception):
    pass


class DataUpdateCoordinator:
    def __init__(self, hass, logger, name=None, update_interval=None):
        self.hass = hass
        self.data = None
        self.refreshes = 0

    def __class_getitem__(cls, item):
        return cls

    async def async_request_refresh(self):
        self.refreshes += 1


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __class_getitem__(cls, item):
        return cls


class SensorEntity:
    pass


@dataclasses.dataclass(frozen=True, kw_only=True)
class SensorEntityDescription:
    """Home Assistant's is a frozen keyword-only dataclass, and the
    integration subclasses it as one — a plain class here would accept what
    the real one refuses."""
    key: str
    translation_key: str | None = None
    native_unit_of_measurement: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    suggested_display_precision: int | None = None


class _Enum:
    def __getattr__(self, name):
        return name.lower()


class _Auto(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: (a[0] if a else None)


class Services:
    def __init__(self):
        self.registered = {}

    def has_service(self, domain, name):
        return (domain, name) in self.registered

    def async_register(self, domain, name, handler, schema=None, supports_response=None):
        self.registered[(domain, name)] = (handler, schema, supports_response)

    def async_remove(self, domain, name):
        self.registered.pop((domain, name), None)


def load():
    names = [
        "homeassistant", "homeassistant.core", "homeassistant.exceptions", "homeassistant.const",
        "homeassistant.config_entries", "homeassistant.helpers", "homeassistant.helpers.config_validation",
        "homeassistant.helpers.aiohttp_client", "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.entity", "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.device_registry", "homeassistant.components",
        "homeassistant.components.sensor", "voluptuous",
    ]
    saved = {n: sys.modules.get(n) for n in names + ["gardenrx_it"]}
    for n in names:
        sys.modules[n] = _Auto(n)
    m = sys.modules
    for n in names:  # `from homeassistant.helpers import config_validation` reads the attribute
        parent, _, child = n.rpartition(".")
        if parent:
            setattr(m[parent], child, m[n])
    m["homeassistant.core"].SupportsResponse = SupportsResponse
    m["homeassistant.core"].HomeAssistant = object
    m["homeassistant.core"].ServiceCall = object
    m["homeassistant.core"].ServiceResponse = dict
    m["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    m["homeassistant.const"].Platform = _Enum()
    m["homeassistant.config_entries"].ConfigEntry = object
    m["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = DataUpdateCoordinator
    m["homeassistant.helpers.update_coordinator"].UpdateFailed = UpdateFailed
    m["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntity
    m["homeassistant.helpers.entity"].DeviceInfo = dict
    m["homeassistant.helpers.device_registry"].DeviceEntryType = _Enum()
    m["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object
    sensor = m["homeassistant.components.sensor"]
    sensor.SensorEntity = SensorEntity
    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.SensorDeviceClass = _Enum()
    sensor.SensorStateClass = _Enum()
    m["homeassistant.helpers.config_validation"].config_entry_only_config_schema = lambda d: None
    pkg = types.ModuleType("gardenrx_it")
    pkg.__path__ = [str(INTEGRATION)]
    sys.modules["gardenrx_it"] = pkg
    try:
        init = importlib.util.spec_from_file_location("gardenrx_it", INTEGRATION / "__init__.py",
                                                      submodule_search_locations=[str(INTEGRATION)])
        module = importlib.util.module_from_spec(init)
        sys.modules["gardenrx_it"] = module
        init.loader.exec_module(module)
        sensor_mod = importlib.import_module("gardenrx_it.sensor")
        api = importlib.import_module("gardenrx_it.api")
        return module, sensor_mod, api
    finally:
        for n in list(sys.modules):
            if n.startswith("gardenrx_it"):
                sys.modules.pop(n, None)
        for n, v in saved.items():
            if v is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = v


SUMMARY = {
    "harvest": {"year": 2026, "total_lb": 12.5, "total_value": 40.0, "picks": 3,
                "by_crop": [{"crop": "Apples", "lb": 12.5}], "recent": [{"id": 7}], "units": ["lb"]},
    "crops": [{"id": 1, "name": "Apples", "varieties": []}],
    "phi": {"active_count": 1, "crops": [{"crop": "Apples", "days_left": 3}]},
    "sprays": {"last": {"date": "2026-07-15", "days_ago": 2, "products": ["Captan"], "crops": ["Apples"]},
               "this_year": 4, "recent": [], "queued": [{"id": 3}]},
    "inventory": {"items": [{"product": "Captan", "low": True}], "low_count": 1},
}


class FakeClient:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def action(self, action, data):
        self.calls.append((action, data))
        if self.error:
            raise self.error
        return {"ok": True, "id": 9}


class TestTheIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.init, cls.sensor, cls.api = load()

    def hass_with(self, client):
        coordinator = self.init.GardenRxCoordinator(None, client)
        hass = types.SimpleNamespace(services=Services(), data={"gardenrx": {"entry": coordinator}})
        self.init._register_services(hass)
        return hass, coordinator

    def call(self, hass, service, data):
        handler, schema, response = hass.services.registered[("gardenrx", service)]
        return asyncio.run(handler(types.SimpleNamespace(data=data)))

    def test_every_action_is_registered_with_a_response(self):
        hass, _ = self.hass_with(FakeClient())
        for service in ("log_harvest", "delete_harvest", "complete_queued_spray", "delete_queued_spray"):
            self.assertIs(SupportsResponse.OPTIONAL, hass.services.registered[("gardenrx", service)][2])
        self.assertIn(("gardenrx", "refresh"), hass.services.registered)

    def test_a_service_hands_back_the_add_ons_answer_and_refreshes(self):
        client = FakeClient()
        hass, coordinator = self.hass_with(client)
        got = self.call(hass, "log_harvest", {"crop": "Apples", "weight": 2.0, "date": dt.date(2026, 7, 1)})
        self.assertEqual({"ok": True, "id": 9}, got)
        self.assertEqual([("log_harvest", {"crop": "Apples", "weight": 2.0, "date": "2026-07-01"})], client.calls)
        self.assertEqual(1, coordinator.refreshes)

    def test_a_refusal_is_an_error_with_the_add_ons_sentence(self):
        client = FakeClient(error=self.api.GardenRxError('No crop is called "kiwi".'))
        hass, coordinator = self.hass_with(client)
        with self.assertRaisesRegex(HomeAssistantError, 'No crop is called "kiwi"'):
            self.call(hass, "log_harvest", {"crop": "kiwi", "weight": 1.0})
        self.assertEqual(0, coordinator.refreshes)

    def test_not_set_up_is_said(self):
        hass, _ = self.hass_with(FakeClient())
        hass.data = {"gardenrx": {}}
        with self.assertRaisesRegex(HomeAssistantError, "not set up"):
            self.call(hass, "delete_harvest", {"id": 1})

    def test_every_lever_the_panel_has_is_a_service_that_answers(self):
        """The owner's ask: log a spray, queue one, adjust stock, add a crop or
        a variety, keep a dated note and read the harvests back, all from
        Home Assistant, each answering with the record it made or changed."""
        hass, _ = self.hass_with(FakeClient())
        for service in ("log_spray", "queue_spray", "adjust_inventory", "add_crop",
                        "add_variety", "log_note"):
            self.assertIs(SupportsResponse.OPTIONAL, hass.services.registered[("gardenrx", service)][2],
                          service)
        # Reading the harvests back is only an answer, so it is response-only.
        self.assertIs(SupportsResponse.ONLY, hass.services.registered[("gardenrx", "get_harvests")][2])

    def test_a_read_does_not_ask_for_a_refresh_and_a_write_does(self):
        client = FakeClient()
        hass, coordinator = self.hass_with(client)
        self.call(hass, "get_harvests", {"crop": "Apples", "start": dt.date(2026, 7, 1),
                                         "end": dt.date(2026, 7, 31)})
        self.assertEqual([("get_harvests", {"crop": "Apples", "start": "2026-07-01", "end": "2026-07-31"})],
                         client.calls)
        self.assertEqual(0, coordinator.refreshes)
        self.call(hass, "queue_spray", {"crop": ["Apples"], "product": ["Captan"],
                                        "planned_date": dt.date(2026, 7, 20)})
        self.assertEqual(("queue_spray", {"crop": ["Apples"], "product": ["Captan"], "planned_date": "2026-07-20"}),
                         client.calls[-1])
        self.assertEqual(1, coordinator.refreshes)

    def test_a_new_lever_refuses_with_the_add_ons_sentence(self):
        client = FakeClient(error=self.api.GardenRxError('No crop is called "tomatos".'))
        hass, coordinator = self.hass_with(client)
        with self.assertRaisesRegex(HomeAssistantError, 'No crop is called "tomatos"'):
            self.call(hass, "add_variety", {"crop": "tomatos", "name": "Sungold"})
        with self.assertRaisesRegex(HomeAssistantError, 'No crop is called "tomatos"'):
            self.call(hass, "get_harvests", {"crop": "tomatos"})
        self.assertEqual(0, coordinator.refreshes)

    def test_each_sensor_reads_its_part_of_the_summary(self):
        coordinator = self.init.GardenRxCoordinator(None, FakeClient())
        coordinator.data = SUMMARY
        entry = types.SimpleNamespace(entry_id="e")
        sensors = {d.key: self.sensor.GardenRxSensor(coordinator, entry, d) for d in self.sensor.SENSORS}
        self.assertEqual(12.5, sensors["harvest_season"].native_value)
        self.assertEqual(40.0, sensors["harvest_value"].native_value)
        self.assertEqual(dt.date(2026, 7, 15), sensors["last_spray"].native_value)
        self.assertEqual(1, sensors["queued_sprays"].native_value)
        self.assertEqual(1, sensors["pre_harvest_intervals"].native_value)
        self.assertEqual(1, sensors["low_stock"].native_value)
        attrs = sensors["harvest_season"].extra_state_attributes
        self.assertEqual("harvest", attrs["gardenrx"])
        self.assertEqual(SUMMARY["crops"], attrs["crops"])
        self.assertEqual("sprays", sensors["last_spray"].extra_state_attributes["gardenrx"])
        self.assertEqual([{"id": 3}], sensors["last_spray"].extra_state_attributes["queued"])
        self.assertEqual("inventory", sensors["low_stock"].extra_state_attributes["gardenrx"])

    def test_no_data_yet_is_no_value_rather_than_a_crash(self):
        coordinator = self.init.GardenRxCoordinator(None, FakeClient())
        entry = types.SimpleNamespace(entry_id="e")
        for d in self.sensor.SENSORS:
            s = self.sensor.GardenRxSensor(coordinator, entry, d)
            self.assertIn(s.native_value, (None, 0))
            self.assertEqual(d.kind, s.extra_state_attributes["gardenrx"])

    def test_the_long_lists_stay_out_of_the_recorder(self):
        unrecorded = self.sensor.GardenRxSensor._unrecorded_attributes
        for big in ("by_crop", "recent", "crops", "queued", "phi", "items"):
            self.assertIn(big, unrecorded)


if __name__ == "__main__":
    unittest.main()
