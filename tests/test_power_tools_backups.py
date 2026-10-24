#!/usr/bin/env python3
"""Backups, through the real admin-gated Power Tools handlers.

The backup manager below answers in the shape of Core 2025's
`homeassistant/components/backup/manager.py`: `hass.data["backup"]` is the
manager, `async_get_backups()` returns `(backups by id, errors by agent)`,
each backup carries `backup_id`, `name`, `date` (an ISO string),
`agents` ({agent: status with `size`, `protected`}), `database_included`,
`homeassistant_included` and `with_automatic_settings`, and
`async_delete_backup(id)` answers the agents that failed.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)


def backup(bid, name, days_old, *, automatic=False, partial=False, size=100):
    return types.SimpleNamespace(
        backup_id=bid, name=name,
        date=(NOW - dt.timedelta(days=days_old)).isoformat(),
        agents={"hassio.local": types.SimpleNamespace(size=size, protected=False)},
        database_included=not partial, homeassistant_included=True,
        with_automatic_settings=automatic, extra_metadata={})


class Manager:
    def __init__(self, backups):
        self.backups = {b.backup_id: b for b in backups}
        self.deleted = []

    async def async_get_backups(self):
        return dict(self.backups), {}

    async def async_delete_backup(self, backup_id):
        self.deleted.append(backup_id)
        self.backups.pop(backup_id)
        return {}


class Services:
    def __init__(self, present=()):
        self.handlers = {}
        self.present = set(present)
        self.calls = []

    def async_register(self, domain, name, handler, schema=None, **kw):
        self.handlers[name] = handler

    def has_service(self, domain, name):
        if domain == "brain":
            return name in self.handlers
        return (domain, name) in self.present

    async def async_call(self, domain, service, data=None, blocking=False, **kw):
        self.calls.append((domain, service, dict(data or {})))
        return None


class Auth:
    async def async_get_user(self, user_id):
        return types.SimpleNamespace(id=user_id, is_admin=user_id == "admin")


class Case(unittest.TestCase):
    PRESENT = (("hassio", "backup_full"), ("hassio", "backup_partial"))

    def setUp(self):
        self.pkg = env.load_integration()
        self.manager = Manager([
            backup("a1", "Automatic backup 1", 1, automatic=True),
            backup("a2", "Automatic backup 2", 8, automatic=True),
            backup("a3", "Automatic backup 3", 15, automatic=True),
            backup("m1", "Before the update", 40),
            backup("p1", "Just the config", 60, partial=True),
        ])
        self.hass = types.SimpleNamespace(services=Services(self.PRESENT),
                                          data={"backup": self.manager},
                                          auth=Auth())
        self.pkg.power_tools.async_register_power_tools(self.hass)

    def run_tool(self, name, data, user_id="admin"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data):
        with self.assertRaises(env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)


class TestListing(Case):
    def test_newest_first_with_what_a_filter_needs(self):
        rows = self.run_tool("list_backups", {})["backups"]
        self.assertEqual([r["backup_id"] for r in rows], ["a1", "a2", "a3", "m1", "p1"])
        self.assertTrue(rows[0]["automatic"])
        self.assertTrue(rows[-1]["partial"])
        self.assertEqual(rows[0]["size"], 100)

    def test_a_core_with_no_manager_says_so(self):
        self.hass.data.pop("backup")
        with self.assertRaises(env.HomeAssistantError) as caught:
            self.run_tool("list_backups", {})
        self.assertIn("2025.1", str(caught.exception))


class TestDeleting(Case):
    def test_old_automatic_ones_are_previewed_by_default(self):
        result = self.run_tool("delete_backups",
                               {"kind": "automatic", "older_than_days": 7})
        self.assertTrue(result["dry_run"])
        self.assertEqual([r["backup_id"] for r in result["delete"]], ["a2", "a3"])
        self.assertEqual(self.manager.deleted, [])

    def test_keep_newest_keeps_the_newest_of_what_matched(self):
        result = self.run_tool("delete_backups", {
            "kind": "automatic", "keep_newest": 1, "dry_run": False})
        self.assertEqual(self.manager.deleted, ["a2", "a3"])
        self.assertEqual(result["deleted"], 2)
        self.assertEqual([r["backup_id"] for r in result["kept_by_keep_newest"]], ["a1"])

    def test_name_match_and_explicit_ids(self):
        result = self.run_tool("delete_backups", {"name_contains": "UPDATE"})
        self.assertEqual([r["backup_id"] for r in result["delete"]], ["m1"])
        self.assertIn("nope", self.refused("delete_backups", {"backup_id": ["nope"]}))

    def test_a_call_with_no_filter_is_refused(self):
        message = self.refused("delete_backups", {"dry_run": False})
        for field in ("backup_id", "older_than_days", "name_contains", "kind"):
            self.assertIn(field, message)

    def test_every_backup_is_never_deleted(self):
        message = self.refused("delete_backups",
                               {"older_than_days": 0, "dry_run": False})
        self.assertIn("keep_newest", message)
        self.assertEqual(self.manager.deleted, [])

    def test_a_bad_kind_names_the_choices(self):
        self.assertIn("automatic", self.refused("delete_backups", {"kind": "old"}))


class TestCreating(Case):
    def test_full_and_partial_through_the_supervisor(self):
        self.run_tool("create_backup", {"name": "Before the change", "password": "pw"})
        self.run_tool("create_backup", {"partial": True, "homeassistant": True,
                                        "addons": ["core_mosquitto"]})
        self.assertEqual(self.hass.services.calls[0][:2], ("hassio", "backup_full"))
        self.assertEqual(self.hass.services.calls[0][2]["name"], "Before the change")
        self.assertEqual(self.hass.services.calls[1][:2], ("hassio", "backup_partial"))
        self.assertEqual(self.hass.services.calls[1][2]["addons"], ["core_mosquitto"])


class TestCreatingWithoutTheSupervisor(Case):
    PRESENT = (("backup", "create_automatic"),)

    def test_a_full_backup_uses_the_backup_integration(self):
        result = self.run_tool("create_backup", {})
        self.assertEqual(result["service"], "backup.create_automatic")

    def test_a_partial_one_says_it_needs_the_supervisor(self):
        self.assertIn("Supervisor", self.refused("create_backup", {"partial": True}))
        self.assertEqual(self.hass.services.calls, [])


if __name__ == "__main__":
    unittest.main()
