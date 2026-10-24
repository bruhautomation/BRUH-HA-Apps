"""brAIn's LLM API is one API per house, however many entries there are.

Every extra brain config entry (a persona agent, an insight job) runs
`async_setup_entry`, and Home Assistant starts them together after a
restart. The account-wide block — the learning and findings watchers, the
notification-action listener and the LLM API — was guarded by a flag that
was SET only after an `await`, so every entry read "nobody has claimed it
yet" before any of them had: each one registered the API and all but the
first logged "API brain_measurements is already registered". These tests
drive the real `async_setup_entry` for several entries at once, through a
fake executor that yields the way Home Assistant's does.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain_ha_env as env  # noqa: E402


class FakeServices:
    def __init__(self):
        self.registered = set()

    def has_service(self, domain, service):
        # The domain services are someone else's test; claim they exist so
        # the setup does not register forty handlers against a fake.
        return True

    def async_remove(self, domain, service):
        self.registered.discard((domain, service))

    async def async_call(self, *args, **kwargs):
        return None


class FakeBus:
    def __init__(self):
        self.listeners = []

    def async_listen(self, event, handler):
        self.listeners.append(event)

        def _unsub():
            self.listeners.remove(event)
        return _unsub


class FakeConfigEntries:
    def __init__(self, hass):
        self.hass = hass
        self.entries = {}

    async def async_forward_entry_setups(self, entry, platforms):
        await asyncio.sleep(0)

    async def async_unload_platforms(self, entry, platforms):
        await asyncio.sleep(0)
        return True

    def async_get_entry(self, entry_id):
        return self.entries.get(entry_id)

    async def async_reload(self, entry_id):
        return None


class FakeHass:
    def __init__(self, base):
        self.data = {}
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(str(base), *parts))
        self.services = FakeServices()
        self.bus = FakeBus()
        self.config_entries = FakeConfigEntries(self)

    async def async_add_executor_job(self, fn, *args):
        # Home Assistant's executor hands control back to the loop while the
        # job runs; a fake that did not would hide every check-then-await.
        await asyncio.sleep(0)
        return fn(*args)

    def async_create_task(self, coro):
        coro.close()


class FakeEntry:
    def __init__(self, entry_id, data=None):
        self.entry_id = entry_id
        self.data = data or {}
        self.options = {}
        self.version = 3
        self._on_unload = []

    def async_on_unload(self, func):
        self._on_unload.append(func)

    def add_update_listener(self, listener):
        return lambda: None

    def unload(self):
        for func in reversed(self._on_unload):
            func()
        self._on_unload.clear()


class Case(unittest.TestCase):
    def setUp(self):
        self.pkg = env.load_integration(llm=True)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, ".brain"), exist_ok=True)
        self.hass = FakeHass(self.tmp.name)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)

    def run_(self, coro):
        return self.loop.run_until_complete(coro)

    def entries(self, n):
        out = [FakeEntry(f"entry{i}") for i in range(n)]
        for e in out:
            self.hass.config_entries.entries[e.entry_id] = e
        return out

    def setup_all(self, entries):
        async def go():
            return await asyncio.gather(
                *(self.pkg.async_setup_entry(self.hass, e) for e in entries))
        return self.run_(go())

    def unload(self, entry):
        ok = self.run_(self.pkg.async_unload_entry(self.hass, entry))
        entry.unload()
        return ok

    def apis(self):
        return [a.id for a in self.hass.__dict__.get("llm_apis", {}).values()]


class TestARestartWithSeveralEntries(Case):
    def test_the_api_is_registered_once_and_nothing_warns(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("brain_test_marker").debug("start")
            self.setup_all(self.entries(4))
        self.assertEqual(self.apis(), [self.pkg.llm_api.API_ID])
        warned = [r for r in logs.output if "already registered" in r
                  or "could not register" in r]
        self.assertEqual(warned, [])

    def test_the_account_wide_watchers_are_started_once(self):
        # The same race started a learning and a findings watcher per entry,
        # each firing its own copy of every event onto the bus.
        self.setup_all(self.entries(3))
        self.assertEqual(self.hass.bus.listeners.count(
            self.pkg.EVENT_MOBILE_ACTION), 1)


class TestUnloading(Case):
    def test_the_api_stays_while_any_entry_is_loaded_and_leaves_with_the_last(self):
        entries = self.entries(3)
        self.setup_all(entries)
        # The first entry is the one that claimed the account-wide block;
        # unloading it must not take the API from the two still loaded.
        for entry in entries[:-1]:
            self.assertTrue(self.unload(entry))
            self.assertEqual(self.apis(), [self.pkg.llm_api.API_ID])
        self.assertTrue(self.unload(entries[-1]))
        self.assertEqual(self.apis(), [])

    def test_a_reload_of_every_entry_registers_it_again_without_a_warning(self):
        entries = self.entries(2)
        self.setup_all(entries)
        for entry in entries:
            self.unload(entry)
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("brain_test_marker").debug("start")
            self.setup_all(entries)
        self.assertEqual(self.apis(), [self.pkg.llm_api.API_ID])
        self.assertFalse([r for r in logs.output if "already registered" in r])


if __name__ == "__main__":
    unittest.main()
