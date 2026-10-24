#!/usr/bin/env python3
"""A person's device trackers, changed through the real admin-gated handlers.

`brain.remove_device_tracker_from_person` answered a bare "HTTP 400: Bad
Request" when it was called the way `person/list` names a person — by its
`person_id` — because the service had no field for one: the schema refused
an unknown key and a missing `entity_id` before the handler ever ran, and a
schema refusal over REST is a 400 with nothing in it. A person can now be
named by entity (`person.x`), by the id `person/list` shows, or by name, and
every refusal is a ServiceValidationError whose sentence names the field
that is wrong.

The person storage below answers the way Core's does
(`homeassistant/components/person`): `hass.data["person"]` is the YAML
collection, the storage collection and the entity component; a storage
item is a dict with `id`, `name`, `user_id`, `device_trackers`; an update
merges and raises on an unknown id; a YAML person's entity is not editable.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402


class ItemNotFound(Exception):
    pass


class StorageCollection:
    def __init__(self):
        self.data: dict[str, dict] = {}
        self.updates: list[tuple] = []

    async def async_update_item(self, item_id, updates):
        if item_id not in self.data:
            raise ItemNotFound(item_id)
        self.updates.append((item_id, dict(updates)))
        self.data[item_id] = {**self.data[item_id], **updates}
        return self.data[item_id]

    async def async_delete_item(self, item_id):
        self.data.pop(item_id)


class PersonEntity:
    def __init__(self, entity_id, config, editable):
        self.entity_id = entity_id
        self._config = config
        self.editable = editable

    @property
    def name(self):
        return self._config.get("name")

    @property
    def device_trackers(self):
        return list(self._config.get("device_trackers") or [])


class EntityComponent:
    def __init__(self):
        self.entities: list[PersonEntity] = []

    def get_entity(self, entity_id):
        return next((e for e in self.entities if e.entity_id == entity_id), None)


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


ADMIN = types.SimpleNamespace(id="admin", is_admin=True, name="Admin")
GUEST = types.SimpleNamespace(id="guest", is_admin=False, name="Tablet")


class Hass:
    def __init__(self):
        self.services = Services()
        self.auth = Auth({"admin": ADMIN, "guest": GUEST})
        self.storage = StorageCollection()
        self.component = EntityComponent()
        self.data = {"person": (object(), self.storage, self.component)}

    def add_person(self, entity_id, item_id, name, trackers, *, yaml=False):
        config = {"id": item_id, "name": name, "user_id": None,
                  "device_trackers": list(trackers)}
        if not yaml:
            self.storage.data[item_id] = config
        self.component.entities.append(
            PersonEntity(entity_id, config if not yaml else dict(config), not yaml))


class Case(unittest.TestCase):
    def setUp(self):
        self.pkg = env.load_integration()
        self.hass = Hass()
        self.pkg.power_tools.async_register_power_tools(self.hass)
        self.hass.add_person("person.alex", "a1b2c3", "Alex",
                             ["device_tracker.phone_a", "device_tracker.watch_a",
                              "device_tracker.router_a"])
        self.hass.add_person("person.sam", "d4e5f6", "Sam",
                             ["device_tracker.phone_s"])
        self.hass.add_person("person.guest", "yaml1", "Visitor",
                             ["device_tracker.phone_v"], yaml=True)

    def run_tool(self, name, data, user_id="admin"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data):
        with self.assertRaises(env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)

    def trackers(self, item_id):
        return self.hass.storage.data[item_id]["device_trackers"]


class TestRemovingTrackers(Case):
    def test_a_person_named_by_the_id_person_list_shows(self):
        # The call that came back as a bare 400.
        result = self.run_tool("remove_device_tracker_from_person", {
            "person_id": "a1b2c3",
            "device_tracker": ["device_tracker.phone_a", "device_tracker.watch_a",
                               "device_tracker.router_a"]})
        self.assertEqual(self.trackers("a1b2c3"), [])
        self.assertEqual(result["person"], "Alex")
        self.assertEqual(sorted(result["removed"]), [
            "device_tracker.phone_a", "device_tracker.router_a",
            "device_tracker.watch_a"])
        self.assertEqual(result["device_trackers"], [])

    def test_a_person_named_by_entity_and_by_name(self):
        self.run_tool("remove_device_tracker_from_person", {
            "entity_id": "person.alex", "device_tracker": "device_tracker.phone_a"})
        self.run_tool("remove_device_tracker_from_person", {
            "person": "alex", "device_tracker": ["device_tracker.watch_a"]})
        self.assertEqual(self.trackers("a1b2c3"), ["device_tracker.router_a"])

    def test_a_tracker_the_person_does_not_have_is_said_not_ignored(self):
        result = self.run_tool("remove_device_tracker_from_person", {
            "person_id": "a1b2c3",
            "device_tracker": ["device_tracker.phone_a", "device_tracker.phone_s"]})
        self.assertEqual(result["not_tracked"], ["device_tracker.phone_s"])
        message = self.refused("remove_device_tracker_from_person", {
            "person_id": "d4e5f6", "device_tracker": ["device_tracker.phone_a"]})
        self.assertIn("device_tracker", message)
        self.assertIn("device_tracker.phone_s", message)  # what Sam has

    def test_no_person_named_says_which_fields_name_one(self):
        message = self.refused("remove_device_tracker_from_person", {
            "device_tracker": ["device_tracker.phone_a"]})
        for field in ("entity_id", "person_id", "person"):
            self.assertIn(field, message)

    def test_an_unknown_person_id_lists_the_people_there_are(self):
        message = self.refused("remove_device_tracker_from_person", {
            "person_id": "nope", "device_tracker": ["device_tracker.phone_a"]})
        self.assertIn("person_id", message)
        self.assertIn("a1b2c3", message)
        self.assertIn("Alex", message)

    def test_an_entity_in_the_wrong_field_is_named(self):
        message = self.refused("remove_device_tracker_from_person", {
            "entity_id": "device_tracker.phone_a",
            "device_tracker": ["device_tracker.phone_a"]})
        self.assertIn("entity_id", message)
        self.assertIn("person.", message)
        message = self.refused("remove_device_tracker_from_person", {
            "person_id": "person.alex",
            "device_tracker": ["device_tracker.phone_a"]})
        self.assertIn("person_id", message)

    def test_a_missing_or_wrong_tracker_list_is_named(self):
        message = self.refused("remove_device_tracker_from_person", {
            "person_id": "a1b2c3"})
        self.assertIn("device_tracker", message)
        message = self.refused("remove_device_tracker_from_person", {
            "person_id": "a1b2c3", "device_tracker": ["sensor.phone_battery"]})
        self.assertIn("sensor.phone_battery", message)

    def test_two_fields_that_name_different_people_are_refused(self):
        message = self.refused("remove_device_tracker_from_person", {
            "entity_id": "person.sam", "person_id": "a1b2c3",
            "device_tracker": ["device_tracker.phone_a"]})
        self.assertIn("Sam", message)
        self.assertIn("Alex", message)

    def test_a_yaml_person_says_where_to_change_it(self):
        message = self.refused("remove_device_tracker_from_person", {
            "entity_id": "person.guest", "device_tracker": ["device_tracker.phone_v"]})
        self.assertIn("YAML", message)

    def test_only_an_admin(self):
        with self.assertRaises(env.Unauthorized):
            self.run_tool("remove_device_tracker_from_person", {
                "person_id": "a1b2c3", "device_tracker": ["device_tracker.phone_a"]},
                user_id="guest")
        self.assertEqual(len(self.trackers("a1b2c3")), 3)


class TestAddingTrackers(Case):
    def test_the_add_twin_takes_the_same_names(self):
        result = self.run_tool("add_device_tracker_to_person", {
            "person": "Sam", "device_tracker": ["device_tracker.tablet_s",
                                                "device_tracker.phone_s"]})
        self.assertEqual(self.trackers("d4e5f6"),
                         ["device_tracker.phone_s", "device_tracker.tablet_s"])
        self.assertEqual(result["added"], ["device_tracker.tablet_s"])
        self.assertEqual(result["already_tracked"], ["device_tracker.phone_s"])

    def test_the_add_twin_refuses_in_words(self):
        message = self.refused("add_device_tracker_to_person", {
            "person_id": "d4e5f6", "device_tracker": ["light.hall"]})
        self.assertIn("device_tracker", message)
        message = self.refused("add_device_tracker_to_person", {
            "person": "Nobody", "device_tracker": ["device_tracker.tablet_s"]})
        self.assertIn("person", message)


class TestRenameAndDeleteTakeTheSameNames(Case):
    def test_rename_by_person_id(self):
        self.run_tool("rename_person", {"person_id": "d4e5f6", "name": "Samuel"})
        self.assertEqual(self.hass.storage.data["d4e5f6"]["name"], "Samuel")

    def test_delete_by_name_is_a_dry_run_first(self):
        result = self.run_tool("delete_person", {"person": "Sam", "dry_run": True})
        self.assertTrue(result["dry_run"])
        self.assertIn("d4e5f6", self.hass.storage.data)


if __name__ == "__main__":
    unittest.main()
