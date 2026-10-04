#!/usr/bin/env python3
"""What a device shows as: the device class override and switch_as_x.

Home Assistant's entity dialog has one "Show as" control and three
mechanisms behind it, and the brain Power Tools hold the one implementation
of each: a device class override in the entity registry (a binary sensor
as a door, a cover as a garage), the switch_as_x helper (a smart plug's
switch as a light or a fan, with its undo), and a sensor's display options.

Driven through the real handlers — `async_register_power_tools` and the
admin-gated wrapper it registers, loaded behind tests/brain_ha_env.py —
against a registry and a config-entries manager that answer the way Core's
do, because what the code under test BRANCHES on (the form the switch_as_x
flow returns, the options its entity carries, which entry a uuid names) is
exactly what a mock that says yes to everything would hide. The flow's
answers are copied off Core's own `switch_as_x/config_flow.py` and
`entity.py`: a `user` form whose schema is markers over selectors, an entry
whose options are the user input, an entity whose unique_id is the entry
id and whose registry options carry `switch_as_x.entity_id`, and a removal
that unhides the switch.
"""

from __future__ import annotations

import asyncio
import enum
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402


# ---------------------------------------------------------------------------
# Core's device classes, as the running core would hand them over
# ---------------------------------------------------------------------------


class BinarySensorDeviceClass(enum.StrEnum):
    DOOR = "door"
    GARAGE_DOOR = "garage_door"
    MOISTURE = "moisture"
    MOTION = "motion"
    OPENING = "opening"
    WINDOW = "window"


class CoverDeviceClass(enum.StrEnum):
    BLIND = "blind"
    GARAGE = "garage"
    SHUTTER = "shutter"


class SwitchDeviceClass(enum.StrEnum):
    OUTLET = "outlet"
    SWITCH = "switch"


def _component(name, **attrs):
    module = types.ModuleType(f"homeassistant.components.{name}")
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


CORE_COMPONENTS = {
    "homeassistant.components.binary_sensor":
        _component("binary_sensor", BinarySensorDeviceClass=BinarySensorDeviceClass),
    "homeassistant.components.cover":
        _component("cover", CoverDeviceClass=CoverDeviceClass),
    "homeassistant.components.switch":
        _component("switch", SwitchDeviceClass=SwitchDeviceClass),
    "homeassistant.components.sensor.const": _component(
        "sensor.const",
        UNIT_CONVERTERS={"temperature": types.SimpleNamespace(
            VALID_UNITS={"°C", "°F", "K"})}),
}


# ---------------------------------------------------------------------------
# The entity registry
# ---------------------------------------------------------------------------


class Entry(types.SimpleNamespace):
    pass


class EntityRegistry:
    """The slice of er.EntityRegistry the device-type tools use. `async_get`
    takes an entity id only, which is the 2023 registry's shape — the code
    must not lean on the uuid lookup a newer core added."""

    def __init__(self):
        self.entities: dict[str, Entry] = {}
        self.writes: list[tuple] = []

    def add(self, entity_id, **kw):
        kw.setdefault("platform", "zha")
        kw.setdefault("device_class", None)
        kw.setdefault("original_device_class", None)
        kw.setdefault("options", {})
        kw.setdefault("hidden_by", None)
        kw.setdefault("config_entry_id", None)
        kw.setdefault("unique_id", uuid.uuid4().hex)
        entry = Entry(entity_id=entity_id, id=uuid.uuid4().hex, **kw)
        self.entities[entity_id] = entry
        return entry

    def async_get(self, entity_id):
        return self.entities.get(entity_id)

    def async_get_entity_id(self, domain, platform, unique_id):
        for entry in self.entities.values():
            if (entry.entity_id.split(".", 1)[0] == domain
                    and entry.platform == platform
                    and entry.unique_id == unique_id):
                return entry.entity_id
        return None

    def async_update_entity(self, entity_id, **changes):
        self.writes.append(("update", entity_id, dict(changes)))
        entry = self.entities[entity_id]
        for key, value in changes.items():
            setattr(entry, key, value)
        return entry

    def async_update_entity_options(self, entity_id, domain, options):
        """Core's rule: the domain's options are replaced whole, and None
        removes the domain's key."""
        self.writes.append(("options", entity_id, domain, options))
        entry = self.entities[entity_id]
        new = {k: v for k, v in entry.options.items() if k != domain}
        if options is not None:
            new[domain] = options
        entry.options = new
        return entry

    def remove_for_config_entry(self, entry_id):
        for eid in [e for e, ent in self.entities.items()
                    if ent.config_entry_id == entry_id]:
            del self.entities[eid]


# ---------------------------------------------------------------------------
# Config entries, and the switch_as_x helper's own flows
# ---------------------------------------------------------------------------


class Marker:
    """voluptuous's and probatio's markers both keep the field name here."""

    def __init__(self, schema):
        self.schema = schema


class Schema:
    def __init__(self, fields):
        self.schema = fields


class Selector:
    def __init__(self, **config):
        self.config = config


TARGETS = ["cover", "fan", "light", "lock", "siren", "valve"]


class ConfigEntry(types.SimpleNamespace):
    pass


class FlowError(Exception):
    """What a data_schema refusing user_input surfaces as from Core."""


class SwitchAsXFlows:
    """`hass.config_entries.flow`, answering as switch_as_x's
    SchemaConfigFlowHandler does: a `user` form, then an entry."""

    def __init__(self, manager, *, invert=True, legacy_options=False,
                 outcome="create_entry"):
        self.manager = manager
        self.invert = invert
        self.legacy_options = legacy_options
        self.outcome = outcome
        self.inits: list = []
        self.configured: list = []
        self.aborted: list = []
        self._n = 0

    def _schema(self):
        options = ([{"value": t, "label": t.title()} for t in TARGETS]
                   if self.legacy_options else list(TARGETS))
        fields = {Marker("entity_id"): Selector(domain="switch")}
        if self.invert:
            fields[Marker("invert")] = Selector()
        fields[Marker("target_domain")] = Selector(
            options=options, translation_key="target_domain")
        return Schema(fields)

    async def async_init(self, handler, *, context=None, data=None):
        self.inits.append((handler, context))
        self._n += 1
        return {"type": "form", "flow_id": f"flow{self._n}", "handler": handler,
                "step_id": "user", "data_schema": self._schema(), "errors": None}

    async def async_configure(self, flow_id, user_input=None):
        self.configured.append((flow_id, dict(user_input or {})))
        if self.outcome == "abort":
            return {"type": "abort", "flow_id": flow_id, "reason": "already_configured"}
        if self.outcome == "form_errors":
            return {"type": "form", "flow_id": flow_id, "errors": {"base": "unknown"}}
        registry = self.manager.hass.registries["entity"]
        switch_id = user_input["entity_id"]
        if switch_id.split(".", 1)[0] != "switch":
            raise FlowError("Entity is not a switch")
        if user_input["target_domain"] not in TARGETS:
            raise FlowError("value must be one of the options")
        if "invert" in user_input and not self.invert:
            raise FlowError("extra keys not allowed @ data['invert']")
        options = {"entity_id": switch_id,
                   "target_domain": user_input["target_domain"]}
        if self.invert:
            options["invert"] = bool(user_input.get("invert", False))
        entry = self.manager.add(options)
        # async_config_entry_title: hide the wrapped switch if registered.
        switch = registry.async_get(switch_id)
        if switch is not None and not switch.hidden_by:
            registry.async_update_entity(switch_id, hidden_by="integration")
        # Setup: the wrapper entity, unique_id = the entry id.
        object_id = switch_id.split(".", 1)[1]
        registry.add(f"{options['target_domain']}.{object_id}",
                     platform="switch_as_x", unique_id=entry.entry_id,
                     config_entry_id=entry.entry_id,
                     options={"switch_as_x": {"entity_id": switch_id,
                                              "invert": options.get("invert", False)}})
        return {"type": "create_entry", "flow_id": flow_id, "result": entry,
                "title": object_id, "options": options}

    def async_abort(self, flow_id):
        self.aborted.append(flow_id)


class SwitchAsXOptions:
    """`hass.config_entries.options`: the helper's own invert form."""

    def __init__(self, manager):
        self.manager = manager
        self.configured: list = []

    async def async_init(self, entry_id, **kw):
        return {"type": "form", "flow_id": f"opt-{entry_id}",
                "data_schema": Schema({Marker("invert"): Selector()})}

    async def async_configure(self, flow_id, user_input=None):
        self.configured.append((flow_id, dict(user_input or {})))
        entry = self.manager.async_get_entry(flow_id[len("opt-"):])
        entry.options = {**entry.options, "invert": bool(user_input["invert"])}
        registry = self.manager.hass.registries["entity"]
        for ent in registry.entities.values():
            if ent.config_entry_id == entry.entry_id:
                ent.options = {"switch_as_x": {**ent.options["switch_as_x"],
                                               "invert": entry.options["invert"]}}
        return {"type": "create_entry", "flow_id": flow_id}

    def async_abort(self, flow_id):
        pass


class ConfigEntries:
    def __init__(self, hass, **flow_kw):
        self.hass = hass
        self.entries: dict[str, ConfigEntry] = {}
        self.removed: list[str] = []
        self.flow = SwitchAsXFlows(self, **flow_kw)
        self.options = SwitchAsXOptions(self)

    def add(self, options, entry_id=None):
        entry = ConfigEntry(entry_id=entry_id or uuid.uuid4().hex,
                            domain="switch_as_x", options=dict(options),
                            title="")
        self.entries[entry.entry_id] = entry
        return entry

    def async_entries(self, domain=None):
        return [e for e in self.entries.values()
                if domain is None or e.domain == domain]

    def async_get_entry(self, entry_id):
        return self.entries.get(entry_id)

    async def async_remove(self, entry_id):
        """Core removes the entry's entities; switch_as_x's own
        async_remove_entry unhides the switch it wrapped."""
        self.removed.append(entry_id)
        entry = self.entries.pop(entry_id)
        registry = self.hass.registries["entity"]
        ref = entry.options.get("entity_id")
        switch_id = ref if "." in str(ref) else next(
            (e.entity_id for e in registry.entities.values() if e.id == ref), None)
        switch = registry.async_get(switch_id) if switch_id else None
        if switch is not None and switch.hidden_by == "integration":
            registry.async_update_entity(switch_id, hidden_by=None)
        registry.remove_for_config_entry(entry_id)
        return {"require_restart": False}


# ---------------------------------------------------------------------------
# The rest of hass
# ---------------------------------------------------------------------------


class States:
    def __init__(self):
        self.states: dict[str, object] = {}

    def set(self, entity_id, state="on"):
        self.states[entity_id] = types.SimpleNamespace(entity_id=entity_id, state=state)

    def get(self, entity_id):
        return self.states.get(entity_id)

    def async_all(self, domain=None):
        return [s for e, s in self.states.items()
                if domain is None or e.split(".", 1)[0] == domain]


class Services:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, name, handler, schema=None, **kw):
        self.handlers[name] = handler

    def has_service(self, domain, name):
        return name in self.handlers


class Auth:
    def __init__(self, users):
        self.users = users

    async def async_get_user(self, user_id):
        return self.users.get(user_id)


ADMIN = types.SimpleNamespace(id="admin", is_admin=True, name="Ben")
GUEST = types.SimpleNamespace(id="guest", is_admin=False, name="Wall tablet")


class Hass:
    def __init__(self, **flow_kw):
        self.registries = {"entity": EntityRegistry()}
        self.states = States()
        self.services = Services()
        self.auth = Auth({"admin": ADMIN, "guest": GUEST})
        self.data = {}
        self.config_entries = ConfigEntries(self, **flow_kw)

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


# ---------------------------------------------------------------------------
# The case
# ---------------------------------------------------------------------------


class Case(unittest.TestCase):
    FLOW = {}

    def setUp(self):
        self.pkg = env.load_integration()
        self.pt = self.pkg.power_tools
        self.hass = Hass(**self.FLOW)
        self.er = self.hass.registries["entity"]
        self.flows = self.hass.config_entries.flow
        self.pt.async_register_power_tools(self.hass)
        modules = patch.dict(sys.modules, CORE_COMPONENTS)
        modules.start()
        self.addCleanup(modules.stop)
        # The house: a contact sensor, a garage cover, a smart plug running a
        # fan, a lamp's plug, a ceiling fan, a light, a thermometer.
        self.er.add("binary_sensor.back_door", original_device_class="opening")
        self.er.add("cover.garage", original_device_class="garage")
        self.er.add("switch.fan_plug", original_device_class="outlet")
        self.er.add("switch.lamp_plug")
        self.er.add("fan.ceiling", platform="tuya")
        self.er.add("light.hall")
        self.er.add("sensor.lounge_temperature", original_device_class="temperature",
                    options={"sensor": {"suggested_display_precision": 1}})
        self.er.add("number.boiler_flow")
        for eid in list(self.er.entities):
            self.hass.states.set(eid)

    def run_tool(self, name, data, user_id="admin"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data, exc=None):
        with self.assertRaises(exc or env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)

    def wrap(self, switch_id, target, invert=None):
        data = {"entity_id": switch_id, "target_domain": target}
        if invert is not None:
            data["invert"] = invert
        return self.run_tool("show_switch_as", data)


# ---------------------------------------------------------------------------
# The device class override
# ---------------------------------------------------------------------------


class TestShowingAnEntityAsAnotherKind(Case):

    def test_a_contact_sensor_is_shown_as_a_door(self):
        got = self.run_tool("set_device_class", {
            "entity_id": ["binary_sensor.back_door"], "device_class": "door"})
        self.assertEqual(self.er.writes,
                         [("update", "binary_sensor.back_door", {"device_class": "door"})])
        self.assertEqual(got["entities"], [{
            "entity_id": "binary_sensor.back_door", "device_class": "door",
            "override": "door", "original_device_class": "opening",
            "previous": "opening"}])

    def test_case_and_spaces_are_not_a_different_class(self):
        self.run_tool("set_device_class", {
            "entity_id": ["cover.garage"], "device_class": "  Shutter "})
        self.assertEqual(self.er.async_get("cover.garage").device_class, "shutter")

    def test_a_switch_is_shown_as_an_outlet_with_its_own_class(self):
        self.run_tool("set_device_class", {
            "entity_id": ["switch.lamp_plug"], "device_class": "outlet"})
        self.assertEqual(self.er.async_get("switch.lamp_plug").device_class, "outlet")

    def test_empty_gives_back_the_integrations_own(self):
        self.er.async_get("binary_sensor.back_door").device_class = "window"
        for empty in ({}, {"device_class": None}, {"device_class": ""}):
            self.er.writes.clear()
            got = self.run_tool("set_device_class",
                                {"entity_id": ["binary_sensor.back_door"], **empty})
            self.assertEqual(self.er.writes, [
                ("update", "binary_sensor.back_door", {"device_class": None})], empty)
            self.assertEqual(got["entities"][0]["device_class"], "opening")
            self.assertIsNone(got["entities"][0]["override"])

    def test_choosing_what_the_integration_reports_stores_no_override(self):
        """Following the integration, so a later change upstream lands."""
        self.run_tool("set_device_class", {
            "entity_id": ["binary_sensor.back_door"], "device_class": "opening"})
        self.assertEqual(self.er.writes, [
            ("update", "binary_sensor.back_door", {"device_class": None})])

    def test_a_class_the_domain_does_not_have_is_refused_with_the_choices(self):
        why = self.refused("set_device_class", {
            "entity_id": ["binary_sensor.back_door"], "device_class": "garage"})
        self.assertIn('"garage" is not a binary_sensor device class', why)
        self.assertIn("door, garage_door, moisture, motion, opening, window", why)
        self.assertEqual(self.er.writes, [])

    def test_every_entity_is_checked_before_any_is_changed(self):
        self.refused("set_device_class", {
            "entity_id": ["binary_sensor.back_door", "light.hall"],
            "device_class": "door"})
        self.assertEqual(self.er.writes, [])

    def test_a_core_that_will_not_say_is_refused_rather_than_written_unchecked(self):
        """humidifier is in the table and its module is not here: the
        executor import fails, which is a core that cannot say."""
        self.er.add("humidifier.bedroom")
        why = self.refused("set_device_class", {
            "entity_id": ["humidifier.bedroom"], "device_class": "dehumidifier"},
            env.HomeAssistantError)
        self.assertIn("will not write an unchecked one", why)
        self.assertEqual(self.er.writes, [])

    def test_a_sensors_class_is_refused_because_statistics_hang_off_it(self):
        why = self.refused("set_device_class", {
            "entity_id": ["sensor.lounge_temperature"], "device_class": "humidity"})
        self.assertIn("long-term statistics", why)
        self.assertIn("brain.set_sensor_display", why)
        why = self.refused("set_device_class", {
            "entity_id": ["number.boiler_flow"], "device_class": "temperature"})
        self.assertIn("decides the unit", why)
        self.assertEqual(self.er.writes, [])

    def test_a_fan_cannot_be_shown_as_a_light_and_is_told_why(self):
        why = self.refused("set_device_class", {
            "entity_id": ["fan.ceiling"], "device_class": "light"})
        self.assertIn("only a switch can be shown as another kind of device", why)
        self.assertIn("brain.show_switch_as", why)
        why = self.refused("set_device_class", {
            "entity_id": ["light.hall"], "device_class": "fan"})
        self.assertIn("A light has no device classes", why)

    def test_a_switch_already_shown_as_a_light_says_how_to_change_it(self):
        self.wrap("switch.lamp_plug", "light")
        why = self.refused("set_device_class", {
            "entity_id": ["light.lamp_plug"], "device_class": "outlet"})
        self.assertIn("light.lamp_plug is switch.lamp_plug shown as a light", why)
        self.assertIn("brain.stop_showing_switch_as", why)

    def test_an_entity_with_no_registry_entry_says_where_to_set_it(self):
        self.hass.states.set("binary_sensor.yaml_door")
        why = self.refused("set_device_class", {
            "entity_id": ["binary_sensor.yaml_door"], "device_class": "door"})
        self.assertIn("has no unique ID", why)
        self.assertIn("customize", why)
        why = self.refused("set_device_class", {
            "entity_id": ["binary_sensor.nowhere"], "device_class": "door"})
        self.assertEqual(why, "Entity not found: binary_sensor.nowhere")

    def test_only_an_admin_may_change_it(self):
        with self.assertRaises(env.Unauthorized):
            self.run_tool("set_device_class", {
                "entity_id": ["binary_sensor.back_door"], "device_class": "door"},
                user_id="guest")
        self.assertEqual(self.er.writes, [])


# ---------------------------------------------------------------------------
# switch_as_x: a switch shown as a light, a fan…, and back
# ---------------------------------------------------------------------------


class TestShowingASwitchAsSomethingElse(Case):

    def test_a_plug_running_a_fan_is_shown_as_a_fan(self):
        got = self.wrap("switch.fan_plug", "fan")
        self.assertEqual(self.flows.inits, [("switch_as_x", {"source": "user"})])
        self.assertEqual(self.flows.configured, [
            ("flow1", {"entity_id": "switch.fan_plug", "target_domain": "fan"})])
        self.assertEqual(got["entity_id"], "fan.fan_plug")
        self.assertEqual(got["switch_entity_id"], "switch.fan_plug")
        self.assertEqual(got["target_domain"], "fan")
        self.assertIn(got["config_entry_id"], self.hass.config_entries.entries)
        self.assertEqual(self.er.async_get("switch.fan_plug").hidden_by, "integration")
        self.assertNotIn("note", got)

    def test_the_wrapper_is_the_way_in_too(self):
        """Handing it the light it already shows as means its switch."""
        self.wrap("switch.lamp_plug", "light")
        got = self.wrap("light.lamp_plug", "fan")
        self.assertEqual(got["switch_entity_id"], "switch.lamp_plug")
        self.assertEqual(got["entity_id"], "fan.lamp_plug")

    def test_the_same_type_again_is_already_done(self):
        first = self.wrap("switch.fan_plug", "fan")
        again = self.wrap("switch.fan_plug", "fan")
        self.assertTrue(again["already"])
        self.assertEqual(again["entity_id"], first["entity_id"])
        self.assertEqual(len(self.flows.inits), 1, "a second helper was started")

    def test_another_type_moves_it_and_the_old_one_goes_first(self):
        """The dialog's order, for its reason: removing the old helper
        unhides the switch, so a new one made first would be left wrapping
        a visible switch."""
        old = self.wrap("switch.lamp_plug", "light")
        got = self.wrap("switch.lamp_plug", "fan")
        self.assertEqual(self.hass.config_entries.removed, [old["config_entry_id"]])
        self.assertEqual(got["replaced"], [{
            "entity_id": "light.lamp_plug", "target_domain": "light",
            "config_entry_id": old["config_entry_id"]}])
        self.assertIsNone(self.er.async_get("light.lamp_plug"))
        self.assertEqual(self.er.async_get("switch.lamp_plug").hidden_by, "integration")

    def test_moving_it_names_the_automations_that_used_the_old_entity(self):
        self.wrap("switch.lamp_plug", "light")
        self.hass.states.set("automation.lamp_at_dusk")
        automation = types.ModuleType("homeassistant.components.automation")
        automation.entities_in_automation = lambda hass, eid: (
            ["light.lamp_plug"] if eid == "automation.lamp_at_dusk" else [])
        with patch.dict(sys.modules, {"homeassistant.components.automation": automation}):
            got = self.wrap("switch.lamp_plug", "fan")
        self.assertEqual(got["references_to_replaced"], ["automation.lamp_at_dusk"])
        self.assertIn("point them at fan.lamp_plug", got["note"])

    def test_a_type_this_core_does_not_offer_is_refused_with_its_list(self):
        why = self.refused("show_switch_as", {
            "entity_id": "switch.fan_plug", "target_domain": "climate"})
        self.assertIn("cover, fan, light, lock, siren, valve — not climate", why)
        self.assertEqual(self.flows.configured, [])
        self.assertEqual(self.flows.aborted, ["flow1"], "the started flow was left open")

    def test_a_2023_form_listing_options_as_value_label_pairs_is_read(self):
        self.flows.legacy_options = True
        why = self.refused("show_switch_as", {
            "entity_id": "switch.fan_plug", "target_domain": "climate"})
        self.assertIn("cover, fan, light, lock, siren, valve — not climate", why)
        self.assertEqual(self.wrap("switch.fan_plug", "fan")["entity_id"], "fan.fan_plug")

    def test_only_a_switch_can_be_shown_as_something_else(self):
        why = self.refused("show_switch_as", {
            "entity_id": "fan.ceiling", "target_domain": "light"})
        self.assertIn("a fan cannot be shown as a light", why)
        self.assertIn("plug's switch", why)
        why = self.refused("show_switch_as", {
            "entity_id": "binary_sensor.back_door", "target_domain": "light"})
        self.assertIn("change it with brain.set_device_class", why)
        self.assertIn("door, garage_door", why)
        why = self.refused("show_switch_as", {
            "entity_id": "sensor.lounge_temperature", "target_domain": "light"})
        self.assertIn("brain.set_sensor_display", why)
        self.assertEqual(self.flows.inits, [])

    def test_showing_it_as_a_switch_is_the_undo(self):
        why = self.refused("show_switch_as", {
            "entity_id": "switch.fan_plug", "target_domain": "switch"})
        self.assertIn("brain.stop_showing_switch_as", why)

    def test_a_switch_that_is_not_there_is_not_wrapped(self):
        why = self.refused("show_switch_as", {
            "entity_id": "switch.gone", "target_domain": "light"})
        self.assertEqual(why, "Entity not found: switch.gone")
        self.assertEqual(self.flows.inits, [])

    def test_invert_is_passed_where_it_means_something(self):
        got = self.wrap("switch.lamp_plug", "cover", invert=True)
        self.assertEqual(self.flows.configured[-1][1], {
            "entity_id": "switch.lamp_plug", "target_domain": "cover", "invert": True})
        self.assertTrue(got["invert"])
        self.assertTrue(self.hass.config_entries.entries[got["config_entry_id"]]
                        .options["invert"])

    def test_invert_on_a_light_is_refused_because_core_ignores_it(self):
        why = self.refused("show_switch_as", {
            "entity_id": "switch.lamp_plug", "target_domain": "light", "invert": True})
        self.assertIn("ignores it on a light", why)
        self.assertEqual(self.flows.inits, [])

    def test_flipping_invert_uses_the_helpers_own_options_flow(self):
        first = self.wrap("switch.lamp_plug", "valve")
        got = self.wrap("switch.lamp_plug", "valve", invert=True)
        self.assertEqual(got["changed"], "invert")
        self.assertEqual(got["entity_id"], first["entity_id"])
        self.assertEqual(self.hass.config_entries.options.configured, [
            (f"opt-{first['config_entry_id']}", {"invert": True})])
        self.assertEqual(len(self.flows.inits), 1, "the entity was recreated")
        self.assertTrue(self.er.async_get("valve.lamp_plug")
                        .options["switch_as_x"]["invert"])


class TestACoreWithoutInvert(Case):
    """switch_as_x gained invert in 2024.2. The form says whether it is
    there, and that is what is read — never the version number."""

    FLOW = {"invert": False}

    def test_asking_for_invert_is_refused_in_a_sentence(self):
        why = self.refused("show_switch_as", {
            "entity_id": "switch.lamp_plug", "target_domain": "cover", "invert": True})
        self.assertIn("has no invert option", why)
        self.assertEqual(self.flows.configured, [])

    def test_invert_off_is_what_it_does_anyway_so_it_is_not_sent(self):
        got = self.wrap("switch.lamp_plug", "cover", invert=False)
        self.assertEqual(self.flows.configured[-1][1], {
            "entity_id": "switch.lamp_plug", "target_domain": "cover"})
        self.assertEqual(got["entity_id"], "cover.lamp_plug")
        self.assertNotIn("invert", got)

    def test_flipping_invert_on_a_helper_without_it_is_refused(self):
        self.wrap("switch.lamp_plug", "lock")
        why = self.refused("show_switch_as", {
            "entity_id": "switch.lamp_plug", "target_domain": "lock", "invert": True})
        self.assertIn("has no invert option", why)
        self.assertEqual(self.hass.config_entries.options.configured, [])


class TestAFlowThatDoesNotFinish(Case):

    def test_an_abort_is_said_and_the_switch_is_left_a_switch(self):
        self.flows.outcome = "abort"
        why = self.refused("show_switch_as", {
            "entity_id": "switch.fan_plug", "target_domain": "fan"},
            env.HomeAssistantError)
        self.assertIn("did not create the fan (already_configured)", why)
        self.assertIsNone(self.er.async_get("switch.fan_plug").hidden_by)

    def test_a_form_back_with_errors_is_aborted_rather_than_left_open(self):
        self.flows.outcome = "form_errors"
        self.refused("show_switch_as", {
            "entity_id": "switch.fan_plug", "target_domain": "fan"},
            env.HomeAssistantError)
        self.assertEqual(self.flows.aborted, ["flow1"])

    def test_a_failure_after_the_old_helper_went_says_the_switch_is_back(self):
        self.wrap("switch.lamp_plug", "light")
        self.flows.outcome = "abort"
        why = self.refused("show_switch_as", {
            "entity_id": "switch.lamp_plug", "target_domain": "fan"},
            env.HomeAssistantError)
        self.assertIn("The old one (light.lamp_plug) was removed, so "
                      "switch.lamp_plug shows as a switch again.", why)
        self.assertIsNone(self.er.async_get("switch.lamp_plug").hidden_by)


class TestStoppingShowingASwitchAsSomethingElse(Case):

    def test_the_wrapper_or_the_switch_both_undo_it(self):
        for handle in ("fan.fan_plug", "switch.fan_plug"):
            made = self.wrap("switch.fan_plug", "fan")
            got = self.run_tool("stop_showing_switch_as",
                                {"entity_id": handle, "dry_run": False})
            self.assertEqual(got["switch_entity_id"], "switch.fan_plug", handle)
            self.assertEqual(got["removed_entity_ids"], ["fan.fan_plug"])
            self.assertEqual(got["config_entry_ids"], [made["config_entry_id"]])
            self.assertIsNone(self.er.async_get("fan.fan_plug"))
            self.assertIsNone(self.er.async_get("switch.fan_plug").hidden_by)
            self.assertEqual(self.hass.config_entries.async_entries("switch_as_x"), [])

    def test_a_round_trip_puts_the_house_back(self):
        before = dict(vars(self.er.async_get("switch.fan_plug")))
        self.wrap("switch.fan_plug", "fan")
        self.run_tool("stop_showing_switch_as",
                      {"entity_id": "switch.fan_plug", "dry_run": False})
        self.assertEqual(dict(vars(self.er.async_get("switch.fan_plug"))), before)
        self.assertEqual(sorted(self.er.entities), sorted([
            "binary_sensor.back_door", "cover.garage", "switch.fan_plug",
            "switch.lamp_plug", "fan.ceiling", "light.hall",
            "sensor.lounge_temperature", "number.boiler_flow"]))

    def test_a_dry_run_changes_nothing_and_says_what_uses_it(self):
        self.wrap("switch.fan_plug", "fan")
        self.hass.states.set("automation.fan_at_night")
        automation = types.ModuleType("homeassistant.components.automation")
        automation.entities_in_automation = lambda hass, eid: ["fan.fan_plug"]
        with patch.dict(sys.modules, {"homeassistant.components.automation": automation}):
            got = self.run_tool("stop_showing_switch_as",
                                {"entity_id": "fan.fan_plug", "dry_run": True})
        self.assertTrue(got["dry_run"])
        self.assertEqual(got["references_to_removed"], ["automation.fan_at_night"])
        self.assertIn("point them back at switch.fan_plug", got["note"])
        self.assertIsNotNone(self.er.async_get("fan.fan_plug"))
        self.assertEqual(self.hass.config_entries.removed, [])

    def test_an_entry_that_names_the_switch_by_its_registry_id_is_found(self):
        """switch_as_x rewrites its stored source to the registry uuid when
        the switch is renamed, and a 2023 registry's async_get takes an
        entity id only."""
        switch = self.er.async_get("switch.lamp_plug")
        entry = self.hass.config_entries.add(
            {"entity_id": switch.id, "target_domain": "light", "invert": False})
        self.er.add("light.lamp_plug", platform="switch_as_x",
                    unique_id=entry.entry_id, config_entry_id=entry.entry_id,
                    options={})
        got = self.run_tool("stop_showing_switch_as",
                            {"entity_id": "light.lamp_plug", "dry_run": True})
        self.assertEqual(got["switch_entity_id"], "switch.lamp_plug")
        got = self.wrap("switch.lamp_plug", "light")
        self.assertTrue(got["already"])

    def test_a_switch_that_is_not_shown_as_anything_has_nothing_to_undo(self):
        why = self.refused("stop_showing_switch_as",
                           {"entity_id": "switch.lamp_plug", "dry_run": False})
        self.assertIn("nothing to undo", why)

    def test_an_ordinary_fan_is_not_a_switch_in_disguise(self):
        why = self.refused("stop_showing_switch_as",
                           {"entity_id": "fan.ceiling", "dry_run": False})
        self.assertIn("fan.ceiling is a fan from the tuya integration", why)

    def test_a_wrapper_whose_helper_is_gone_points_at_the_orphan_cleanup(self):
        self.er.add("light.leftover", platform="switch_as_x",
                    config_entry_id="gone", options={"switch_as_x": {
                        "entity_id": "switch.lamp_plug"}})
        why = self.refused("stop_showing_switch_as",
                           {"entity_id": "light.leftover", "dry_run": False})
        self.assertIn("brain.delete_orphaned_entities", why)


# ---------------------------------------------------------------------------
# A sensor's display
# ---------------------------------------------------------------------------


class TestASensorsDisplay(Case):

    def test_precision_is_set_and_the_rest_of_the_options_kept(self):
        got = self.run_tool("set_sensor_display", {
            "entity_id": ["sensor.lounge_temperature"], "display_precision": 2})
        self.assertEqual(self.er.async_get("sensor.lounge_temperature").options, {
            "sensor": {"suggested_display_precision": 1, "display_precision": 2}})
        self.assertEqual(got["entities"], [
            {"entity_id": "sensor.lounge_temperature", "display_precision": 2}])

    def test_a_unit_the_sensor_converts_to_is_set(self):
        self.run_tool("set_sensor_display", {
            "entity_id": ["sensor.lounge_temperature"], "unit_of_measurement": "°F"})
        self.assertEqual(self.er.async_get("sensor.lounge_temperature")
                         .options["sensor"]["unit_of_measurement"], "°F")

    def test_a_unit_it_cannot_convert_to_is_refused_with_the_list(self):
        why = self.refused("set_sensor_display", {
            "entity_id": ["sensor.lounge_temperature"], "unit_of_measurement": "kWh"})
        self.assertIn("Choose one of: K, °C, °F", why)
        self.assertEqual(self.er.writes, [])

    def test_a_sensor_with_no_converter_keeps_its_unit(self):
        self.er.add("sensor.rainfall")
        why = self.refused("set_sensor_display", {
            "entity_id": ["sensor.rainfall"], "unit_of_measurement": "mm"})
        self.assertIn("this one's is not set", why)
        self.assertIn("display precision can still be changed", why)

    def test_null_puts_back_the_integrations_own(self):
        self.run_tool("set_sensor_display", {
            "entity_id": ["sensor.lounge_temperature"], "display_precision": 3,
            "unit_of_measurement": "K"})
        self.run_tool("set_sensor_display", {
            "entity_id": ["sensor.lounge_temperature"], "display_precision": None})
        self.assertEqual(self.er.async_get("sensor.lounge_temperature").options, {
            "sensor": {"suggested_display_precision": 1, "unit_of_measurement": "K"}})

    def test_nothing_named_is_a_question_not_a_write(self):
        why = self.refused("set_sensor_display",
                           {"entity_id": ["sensor.lounge_temperature"]})
        self.assertIn("Nothing to update", why)

    def test_it_is_a_sensors_setting(self):
        why = self.refused("set_sensor_display", {
            "entity_id": ["binary_sensor.back_door"], "display_precision": 1})
        self.assertIn("brain.set_device_class", why)
        self.assertEqual(self.er.writes, [])


class TestTheCatalog(unittest.TestCase):
    """Nothing is create-only: a helper brAIn makes has a service that
    takes it away again, registered beside it."""

    def test_the_helper_has_its_undo(self):
        pkg = env.load_integration()
        services = set(pkg.power_tools.POWER_TOOL_SERVICES)
        self.assertIn("show_switch_as", services)
        self.assertIn("stop_showing_switch_as", services)
        tools = {t.service: t for t in pkg.power_tools.POWER_TOOLS}
        for name in ("set_device_class", "show_switch_as",
                     "stop_showing_switch_as", "set_sensor_display"):
            self.assertTrue(tools[name].has_response, name)


if __name__ == "__main__":
    unittest.main()
