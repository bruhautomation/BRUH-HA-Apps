#!/usr/bin/env python3
"""Users, through the real admin-gated Power Tools handlers.

What the owner did by hand over raw WebSocket — make somebody an admin or
not (`config/auth/update` group_ids), see which accounts are actually used —
is `brain.set_user_group` and `brain.list_users`, beside the existing
enable/disable/delete. The fake auth below answers the way Core's
`AuthManager` does: `async_get_users`, `async_get_user`,
`async_update_user(user, is_active=, group_ids=)`, users carrying `groups`
of objects with an `id`, `refresh_tokens` keyed by id with `last_used_at`.
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

ADMIN, USERS, READ_ONLY = "system-admin", "system-users", "system-read-only"


class User(types.SimpleNamespace):
    @property
    def is_admin(self):
        return self.is_owner or any(g.id == ADMIN for g in self.groups)


def user(uid, name, group=USERS, *, owner=False, active=True, system=False,
         tokens=(), local_only=False, username=None):
    return User(
        id=uid, name=name, is_owner=owner, is_active=active,
        system_generated=system, local_only=local_only,
        groups=[types.SimpleNamespace(id=group)],
        refresh_tokens={f"t{i}": t for i, t in enumerate(tokens)},
        credentials=[types.SimpleNamespace(data={"username": username})]
        if username else [])


def token(client, last_used=None, kind="normal"):
    return types.SimpleNamespace(client_name=client, client_id=None,
                                 token_type=kind, last_used_at=last_used,
                                 created_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                                 token="SECRET-VALUE")


class Auth:
    def __init__(self, users):
        self.users = {u.id: u for u in users}
        self.updates = []
        self.removed = []

    async def async_get_users(self):
        return list(self.users.values())

    async def async_get_user(self, user_id):
        return self.users.get(user_id)

    async def async_update_user(self, u, **changes):
        self.updates.append((u.id, changes))
        if "is_active" in changes:
            u.is_active = changes["is_active"]
        if "group_ids" in changes:
            u.groups = [types.SimpleNamespace(id=g) for g in changes["group_ids"]]

    async def async_remove_user(self, u):
        self.removed.append(u.id)
        self.users.pop(u.id)


class Services:
    def __init__(self):
        self.handlers = {}

    def async_register(self, domain, name, handler, schema=None, **kw):
        self.handlers[name] = handler

    def has_service(self, domain, name):
        return name in self.handlers


NOW = dt.datetime.now(dt.timezone.utc)


class Case(unittest.TestCase):
    def setUp(self):
        self.pkg = env.load_integration()
        self.hass = types.SimpleNamespace(services=Services(), data={})
        self.hass.auth = Auth([
            user("owner", "Owner", ADMIN, owner=True, username="owner",
                 tokens=[token("Phone", NOW - dt.timedelta(hours=2))]),
            user("pat", "Pat", ADMIN, tokens=[token("Browser",
                                                    NOW - dt.timedelta(days=200))]),
            user("kid", "Kid", USERS, tokens=[token("Tablet", NOW)]),
            user("old", "Old account", USERS),
            user("supervisor", "Supervisor", ADMIN, system=True),
        ])
        self.pkg.power_tools.async_register_power_tools(self.hass)

    def run_tool(self, name, data, user_id="owner"):
        handler = self.hass.services.handlers[name]
        call = types.SimpleNamespace(data=data, context=env.Context(user_id))
        return asyncio.run(handler(call))

    def refused(self, name, data):
        with self.assertRaises(env.ServiceValidationError) as caught:
            self.run_tool(name, data)
        return str(caught.exception)


class TestListUsers(Case):
    def test_it_proves_who_is_unused(self):
        rows = {r["user_id"]: r for r in self.run_tool(
            "list_users", {"unused_for_days": 90})["users"]}
        self.assertNotIn("supervisor", rows)  # system users only on request
        self.assertTrue(rows["owner"]["owner"])
        self.assertTrue(rows["pat"]["admin"])
        self.assertEqual(rows["kid"]["groups"], [USERS])
        self.assertTrue(rows["old"]["never_used"])
        self.assertTrue(rows["old"]["unused"])
        self.assertTrue(rows["pat"]["unused"])
        self.assertFalse(rows["kid"]["unused"])
        self.assertEqual(rows["owner"]["usernames"], ["owner"])
        self.assertEqual(rows["kid"]["refresh_tokens"][0]["client_name"], "Tablet")
        self.assertIsNotNone(rows["kid"]["last_used_at"])
        # A token's value is never part of what is answered.
        self.assertNotIn("SECRET-VALUE", repr(rows))

    def test_system_users_when_asked(self):
        rows = self.run_tool("list_users", {"include_system": True})["users"]
        self.assertIn("supervisor", {r["user_id"] for r in rows})


class TestGroups(Case):
    def test_a_user_is_made_an_admin_and_back(self):
        result = self.run_tool("set_user_group", {"user_id": "kid", "group": "admin"})
        self.assertEqual(result["groups_before"], [USERS])
        self.assertTrue(self.hass.auth.users["kid"].is_admin)
        self.run_tool("set_user_group", {"user_id": "kid", "group": "read_only"})
        self.assertEqual(self.hass.auth.users["kid"].groups[0].id, READ_ONLY)

    def test_a_dry_run_changes_nothing(self):
        self.run_tool("set_user_group",
                      {"user_id": "kid", "group": "admin", "dry_run": True})
        self.assertEqual(self.hass.auth.updates, [])

    def test_an_unknown_group_names_the_choices(self):
        message = self.refused("set_user_group", {"user_id": "kid", "group": "boss"})
        for word in ("group", "admin", "user", "read_only"):
            self.assertIn(word, message)

    def test_the_owner_and_a_system_user_are_never_changed(self):
        self.assertIn("owner", self.refused(
            "set_user_group", {"user_id": "owner", "group": "user"}))
        self.assertIn("system", self.refused(
            "set_user_group", {"user_id": "supervisor", "group": "user"}))
        self.assertEqual(self.hass.auth.updates, [])

    def test_the_last_admin_is_never_demoted(self):
        # With the owner gone from the picture (inactive), Pat is the last
        # person who could administer the house.
        self.hass.auth.users["owner"].is_active = False
        message = self.refused("set_user_group", {"user_id": "pat", "group": "user"})
        self.assertIn("admin", message)
        self.assertEqual(self.hass.auth.updates, [])

    def test_only_an_admin_may_ask(self):
        with self.assertRaises(env.Unauthorized):
            self.run_tool("set_user_group", {"user_id": "kid", "group": "admin"},
                          user_id="kid")


class TestTheSameGuardOnDisableAndDelete(Case):
    def test_disable_and_delete_refuse_the_last_admin(self):
        # A second example the original guards never covered: they stopped
        # the owner and nobody else, so the last real admin could go.
        self.hass.auth.users["owner"].is_active = False
        self.refused("disable_user", {"user_id": ["pat"]})
        self.refused("delete_user", {"user_id": ["pat"], "dry_run": True})
        self.assertEqual(self.hass.auth.updates, [])

    def test_an_ordinary_user_is_disabled_and_the_answer_says_so(self):
        result = self.run_tool("disable_user", {"user_id": ["old"]})
        self.assertFalse(self.hass.auth.users["old"].is_active)
        self.assertEqual(result["users"][0]["user_id"], "old")
        self.run_tool("enable_user", {"user_id": ["old"]})
        self.assertTrue(self.hass.auth.users["old"].is_active)

    def test_delete_is_previewed_then_done(self):
        preview = self.run_tool("delete_user", {"user_id": ["old"], "dry_run": True})
        self.assertTrue(preview["dry_run"])
        self.assertIn("old", self.hass.auth.users)
        self.run_tool("delete_user", {"user_id": ["old"]})
        self.assertEqual(self.hass.auth.removed, ["old"])


if __name__ == "__main__":
    unittest.main()
