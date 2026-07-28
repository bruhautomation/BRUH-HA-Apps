#!/usr/bin/env python3
"""Two-way sync between the ⚙ Settings dialog and the Configuration tab (1.8.0).

The panel used to keep its own copy of the generation options in
/data/settings.json, so the sidebar and the add-on's Configuration tab could
show different numbers and the last screen edited silently won. Now the
add-on's own options are the single source of truth, read and written
through the Supervisor.

These tests stand up a fake Supervisor (the real endpoints, the real request
shapes) and assert:
- reads come from the add-on's options, writes land back in them;
- a write is read-modify-write, so options we don't manage (log_level)
  survive;
- pre-1.8.0 local overrides are migrated into the add-on options and then
  dropped, so one value can't be shadowed by a stale copy;
- with no Supervisor everything falls back to the old panel-local behaviour.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "bruh-insights" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import addon_options  # noqa: E402
import settings_store  # noqa: E402
import usage_store  # noqa: E402

# What the add-on's Configuration tab holds when a test starts
SUPERVISOR_OPTIONS = {
    "auto_refresh_hours": 24,
    "history_days": 7,
    "history_keep_runs": 40,
    "history_keep_days": 30,
    "model": "",
    "generation_timeout_minutes": 8,
    "log_level": "info",
}


class FakeSupervisor:
    """Just enough of /addons/self/{info,options} to exercise the real calls."""

    def __init__(self, options: dict):
        self.options = dict(options)
        self.writes: list[dict] = []
        self.reject = False

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/addons/self/info", self._info)
        app.router.add_post("/addons/self/options", self._set)
        return app

    async def _info(self, request: web.Request) -> web.Response:
        assert request.headers.get("Authorization") == "Bearer test-token"
        return web.json_response(
            {"result": "ok", "data": {"slug": "bruh_insights",
                                      "options": dict(self.options)}})

    async def _set(self, request: web.Request) -> web.Response:
        body = await request.json()
        if self.reject:
            return web.json_response(
                {"result": "error", "message": "nope"}, status=400)
        # the real Supervisor REPLACES the stored options wholesale
        self.options = dict(body["options"])
        self.writes.append(dict(self.options))
        return web.json_response({"result": "ok", "data": {}})


class SupervisorMixin:
    """Point addon_options at a fake Supervisor, with stores in a temp dir."""

    supervisor_options = SUPERVISOR_OPTIONS

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sv_server = None
        self.closers = []      # drained by with_supervisor, inside its loop
        base = self.tmp.name
        self._old_stores = (settings_store.SETTINGS_FILE, usage_store.USAGE_FILE,
                            usage_store.LIMITS_FILE)
        settings_store.SETTINGS_FILE = os.path.join(base, "settings.json")
        usage_store.USAGE_FILE = os.path.join(base, "usage.json")
        usage_store.LIMITS_FILE = os.path.join(base, "usage_limits.json")
        self._old_supervisor = (addon_options.SUPERVISOR_URL, addon_options.TOKEN)
        self.supervisor = FakeSupervisor(self.supervisor_options)
        self._reset_cache()

    def tearDown(self):
        (settings_store.SETTINGS_FILE, usage_store.USAGE_FILE,
         usage_store.LIMITS_FILE) = self._old_stores
        (addon_options.SUPERVISOR_URL, addon_options.TOKEN) = self._old_supervisor
        self._reset_cache()
        self.tmp.cleanup()

    @staticmethod
    def _reset_cache():
        addon_options._options = None
        addon_options._read_at = 0.0

    async def _start_supervisor(self) -> TestServer:
        """Bring the fake Supervisor up inside the caller's event loop."""
        self.sv_server = TestServer(self.supervisor.app())
        await self.sv_server.start_server()
        addon_options.SUPERVISOR_URL = str(
            self.sv_server.make_url("")).rstrip("/")
        addon_options.TOKEN = "test-token"
        return self.sv_server

    async def _stop_supervisor(self) -> None:
        if self.sv_server is not None:
            await self.sv_server.close()
            self.sv_server = None

    def with_supervisor(self, body):
        """Run `body()` with the fake Supervisor up, tearing it down after.

        Everything lives in one event loop: aiohttp servers can only be
        closed from the loop that created them.
        """
        async def main():
            await self._start_supervisor()
            try:
                await body()
            finally:
                for close in reversed(self.closers):
                    await close()
                self.closers.clear()
                await self._stop_supervisor()
        asyncio.run(main())


class TestAddonOptions(SupervisorMixin, unittest.TestCase):
    def test_unavailable_without_token(self):
        addon_options.TOKEN = ""
        self.assertFalse(addon_options.available())
        self.assertIsNone(asyncio.run(addon_options.refresh(force=True)))
        self.assertIsNone(addon_options.get("history_days"))

    def test_read_maps_option_names(self):
        async def run():
            self.supervisor.options["auto_refresh_hours"] = 6
            await addon_options.refresh(force=True)
            # settings name → config.yaml option name
            self.assertEqual(addon_options.get("refresh_hours"), 6)
            self.assertEqual(addon_options.get("timeout_minutes"), 8)
            self.assertEqual(addon_options.get("model"), "")
        self.with_supervisor(run)

    def test_write_is_read_modify_write(self):
        async def run():
            merged = await addon_options.write(
                {"history_days": 3, "model": "claude-haiku-4-5"})
            self.assertEqual(self.supervisor.options["history_days"], 3)
            self.assertEqual(self.supervisor.options["model"], "claude-haiku-4-5")
            # untouched options must survive a partial change
            self.assertEqual(self.supervisor.options["log_level"], "info")
            self.assertEqual(self.supervisor.options["auto_refresh_hours"], 24)
            self.assertEqual(merged, self.supervisor.options)
            # the cache reflects the write without another read
            self.assertEqual(addon_options.get("history_days"), 3)
        self.with_supervisor(run)

    def test_write_failure_raises(self):
        async def run():
            self.supervisor.reject = True
            with self.assertRaises(addon_options.OptionsError):
                await addon_options.write({"history_days": 3})
        self.with_supervisor(run)

    def test_refresh_caches_until_forced(self):
        async def run():
            await addon_options.refresh(force=True)
            self.supervisor.options["history_days"] = 12
            await addon_options.refresh()           # within TTL → cached
            self.assertEqual(addon_options.get("history_days"), 7)
            await addon_options.refresh(force=True)  # the poller's call
            self.assertEqual(addon_options.get("history_days"), 12)
        self.with_supervisor(run)


class TestServerSync(SupervisorMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        os.environ["BRUH_INSIGHTS_DIR"] = os.path.join(self.tmp.name, "insights")
        os.environ["BRUH_INSIGHTS_SECRETS"] = os.path.join(self.tmp.name, "secrets")
        os.environ["BRUH_INSIGHTS_SETTINGS_FILE"] = settings_store.SETTINGS_FILE
        os.environ["BRUH_INSIGHTS_USAGE_FILE"] = usage_store.USAGE_FILE
        import server
        self.server = importlib.reload(server)

    async def _client(self) -> TestClient:
        """Start the panel (running its on_startup option sync)."""
        client = TestClient(TestServer(self.server.make_app()))
        await client.start_server()
        self.closers.append(client.close)
        return client

    def test_settings_read_from_addon_options(self):
        async def run():
            self.supervisor.options.update(
                {"auto_refresh_hours": 6, "model": "claude-sonnet-5"})
            client = await self._client()
            data = await (await client.get("/api/settings")).json()
            self.assertTrue(data["options_synced"])
            # fields show the live Configuration-tab values, not blanks
            self.assertEqual(data["settings"]["refresh_hours"], 6)
            self.assertEqual(data["settings"]["model"], "claude-sonnet-5")
            self.assertEqual(self.server.eff_refresh_hours(), 6.0)
            self.assertEqual(self.server.eff_model(), "claude-sonnet-5")
            # and the dropdown has something to offer
            self.assertTrue(any(m["id"] == "claude-opus-5" for m in data["models"]))
        self.with_supervisor(run)

    def test_settings_write_reaches_the_configuration_tab(self):
        async def run():
            client = await self._client()
            resp = await client.put("/api/settings", json={
                "history_days": 3, "model": "haiku", "refresh_hours": 12})
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(self.supervisor.options["history_days"], 3)
            self.assertEqual(self.supervisor.options["model"], "haiku")
            self.assertEqual(self.supervisor.options["auto_refresh_hours"], 12)
            self.assertEqual(self.supervisor.options["log_level"], "info")
            # effective values follow immediately — no restart
            self.assertEqual(self.server.eff_history_days(), 3)
            self.assertEqual(self.server.eff_model(), "haiku")
            self.assertEqual(data["settings"]["history_days"], 3)
            # nothing is left behind locally to shadow the add-on's value
            stored = json.loads(Path(settings_store.SETTINGS_FILE).read_text())
            self.assertIsNone(stored.get("history_days"))
        self.with_supervisor(run)

    def test_clearing_the_model_means_cli_default(self):
        async def run():
            self.supervisor.options["model"] = "claude-opus-5"
            client = await self._client()
            await client.put("/api/settings", json={"model": ""})
            self.assertEqual(self.supervisor.options["model"], "")
            self.assertEqual(self.server.eff_model(), "")
        self.with_supervisor(run)

    def test_panel_only_settings_stay_local(self):
        async def run():
            client = await self._client()
            resp = await client.put("/api/settings", json={
                "plan": "max5", "auto_enabled": False})
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertEqual(data["settings"]["plan"], "max5")
            self.assertFalse(data["settings"]["auto_enabled"])
            # the budget switches are the panel's own — not add-on options
            self.assertNotIn("plan", self.supervisor.options)
            self.assertEqual(settings_store.load()["plan"], "max5")
        self.with_supervisor(run)

    def test_a_refused_write_still_takes_effect(self):
        """If the Supervisor rejects the write the save must not silently do
        nothing — it lands locally and wins until it can be promoted."""
        async def run():
            client = await self._client()
            self.supervisor.reject = True
            resp = await client.put("/api/settings", json={"history_days": 3})
            self.assertEqual(resp.status, 200)
            self.assertEqual(self.server.eff_history_days(), 3)
            self.assertEqual(settings_store.load()["history_days"], 3)
            self.assertEqual(self.supervisor.options["history_days"], 7)
        self.with_supervisor(run)

    def test_invalid_values_never_reach_the_supervisor(self):
        async def run():
            client = await self._client()
            resp = await client.put("/api/settings", json={"history_days": 99})
            self.assertEqual(resp.status, 400)
            self.assertEqual(self.supervisor.writes, [])
        self.with_supervisor(run)

    def test_startup_migrates_pre_1_8_overrides(self):
        async def run():
            settings_store.save({"refresh_hours": 12, "model": "claude-haiku-4-5"})
            client = await self._client()   # on_startup runs _options_sync()
            self.assertEqual(self.supervisor.options["auto_refresh_hours"], 12)
            self.assertEqual(self.supervisor.options["model"], "claude-haiku-4-5")
            # promoted, then dropped locally: exactly one home per value
            stored = settings_store.load()
            self.assertIsNone(stored["refresh_hours"])
            self.assertIsNone(stored["model"])
            self.assertEqual(self.server.eff_refresh_hours(), 12.0)
            data = await (await client.get("/api/settings")).json()
            self.assertEqual(data["settings"]["refresh_hours"], 12)
        self.with_supervisor(run)

    def test_falls_back_to_panel_local_without_supervisor(self):
        async def run():
            addon_options.TOKEN = ""
            client = await self._client()
            resp = await client.put("/api/settings", json={"history_days": 3})
            self.assertEqual(resp.status, 200)
            data = await resp.json()
            self.assertFalse(data["options_synced"])
            self.assertEqual(self.server.eff_history_days(), 3)
            self.assertEqual(settings_store.load()["history_days"], 3)
            self.assertEqual(self.supervisor.writes, [])
        self.with_supervisor(run)


if __name__ == "__main__":
    unittest.main()
