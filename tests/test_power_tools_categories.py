#!/usr/bin/env python3
"""Categories — the groupings on the automation, script, scene and helper
lists — through the real admin-gated handlers. Nothing is create-only: a
category can be made, renamed, given an icon, deleted, and things put in
and taken out of it.

The category registry below answers as Core's
`helpers/category_registry.py` does: keyword-only scope and category_id,
`async_create` refusing a name already used in the scope with ValueError,
`async_list_categories(scope=)`, and entity registry entries carrying a
`categories` mapping of scope to category id.
"""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402


class CategoryRegistry:
    def __init__(self):
        self.cats: dict[str, dict] = {}
        self.n = 0

    def async_create(self, *, scope, name, icon=None):
        if any(c.name == name for c in self.cats.get(scope, {}).values()):
            raise ValueError(f"The name '{name}' is already in use")
        self.n += 1
        entry = types.SimpleNamespace(category_id=f"c{self.n}", name=name, icon=icon)
        self.cats.setdefault(scope, {})[entry.category_id] = entry
        return entry

    def async_get_category(self, *, scope, category_id):
        return self.cats.get(scope, {}).get(category_id)

    def async_list_categories(self, *, scope):
        return list(self.cats.get(scope, {}).values())

    def async_update(self, *, scope, category_id, **changes):
        entry = self.cats[scope][category_id]
        for k, v in changes.items():
            setattr(entry, k, v)
        return entry

    def async_delete(self, *, scope, category_id):
        del self.cats[scope][category_id]


class EntityRegistry:
    def __init__(self, ids):
        self.entities = {e: types.SimpleNamespace(entity_id=e, categories={}) for e in ids}

    def async_get(self, eid):
        return self.entities.get(eid)

    def async_update_entity(self, eid, **changes):
        for k, v in changes.items():
            setattr(self.entities[eid], k, v)


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
        self.cr = CategoryRegistry()
        mod = types.ModuleType("homeassistant.helpers.category_registry")
        mod.async_get = lambda hass: self.cr
        mods = patch.dict(sys.modules, {"homeassistant.helpers.category_registry": mod})
        mods.start()
        self.addCleanup(mods.stop)
        self.er = EntityRegistry(["automation.morning", "automation.night",
                                  "script.bedtime"])
        self.hass = types.SimpleNamespace(services=Services(), auth=Auth(), data={},
                                          registries={"entity": self.er})
        self.pkg.power_tools.async_register_power_tools(self.hass)

    def run_tool(self, name, data, user_id="admin"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data):
        with self.assertRaises(env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)


class TestCategories(Case):
    def test_made_used_renamed_and_deleted(self):
        cid = self.run_tool("create_category", {"scope": "automation",
                                                "name": "Lighting"})["category_id"]
        self.run_tool("set_entity_category", {"entity_id": ["automation.morning"],
                                              "scope": "automation", "category_id": cid})
        self.assertEqual(self.er.entities["automation.morning"].categories,
                         {"automation": cid})
        self.run_tool("update_category", {"scope": "automation", "category_id": cid,
                                          "name": "Lights"})
        self.assertEqual(self.cr.cats["automation"][cid].name, "Lights")
        preview = self.run_tool("delete_category", {"scope": "automation",
                                                    "category_id": cid, "dry_run": True})
        self.assertEqual(preview["uncategorised"], ["automation.morning"])
        self.assertIn(cid, self.cr.cats["automation"])
        self.run_tool("delete_category", {"scope": "automation", "category_id": cid})
        self.assertNotIn(cid, self.cr.cats["automation"])

    def test_taken_out_of_a_category(self):
        cid = self.run_tool("create_category", {"scope": "script",
                                                "name": "Night"})["category_id"]
        self.run_tool("set_entity_category", {"entity_id": "script.bedtime",
                                              "scope": "script", "category_id": cid})
        self.run_tool("set_entity_category", {"entity_id": "script.bedtime",
                                              "scope": "script", "category_id": ""})
        self.assertEqual(self.er.entities["script.bedtime"].categories, {})

    def test_refusals_name_what_is_wrong(self):
        self.assertIn("scope", self.refused("create_category",
                                            {"scope": "lights", "name": "X"}))
        self.run_tool("create_category", {"scope": "automation", "name": "Lighting"})
        self.assertIn("already", self.refused("create_category",
                                              {"scope": "automation", "name": "Lighting"}))
        self.assertIn("Lighting", self.refused("update_category", {
            "scope": "automation", "category_id": "nope", "name": "Y"}))
        self.assertIn("not a automation", self.refused("set_entity_category", {
            "entity_id": ["script.bedtime"], "scope": "automation", "category_id": "c1"}))


if __name__ == "__main__":
    unittest.main()
