#!/usr/bin/env python3
"""Tests for the BRUH Insights settings/budget/schedule features (1.6.0).

Covers:
- settings_store: defaults, validation, persistence, schedule cleaning
- usage_store: run recording, rolling window, plan estimates, real-account
  utilization override, budget blocking
- server: schedule-due logic, per-category schedule overrides, the
  /api/settings routes, and status payload wiring
"""

import asyncio
import datetime
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "bruh-insights" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import settings_store  # noqa: E402
import usage_store  # noqa: E402
import prompt_store  # noqa: E402
import user_categories  # noqa: E402


class TempStoresMixin:
    """Redirect every store file into a fresh temp dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self._old = (settings_store.SETTINGS_FILE, usage_store.USAGE_FILE,
                     usage_store.LIMITS_FILE, prompt_store.OVERRIDES_FILE,
                     user_categories.USER_CATS_FILE)
        settings_store.SETTINGS_FILE = os.path.join(base, "settings.json")
        usage_store.USAGE_FILE = os.path.join(base, "usage.json")
        usage_store.LIMITS_FILE = os.path.join(base, "usage_limits.json")
        prompt_store.OVERRIDES_FILE = os.path.join(base, "prompt_overrides.json")
        user_categories.USER_CATS_FILE = os.path.join(base, "user_categories.json")

    def tearDown(self):
        (settings_store.SETTINGS_FILE, usage_store.USAGE_FILE,
         usage_store.LIMITS_FILE, prompt_store.OVERRIDES_FILE,
         user_categories.USER_CATS_FILE) = self._old
        self.tmp.cleanup()


class TestSettingsStore(TempStoresMixin, unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(settings_store.load(), settings_store.DEFAULTS)

    def test_save_and_merge(self):
        settings_store.save({"plan": "max5"})
        settings_store.save({"budget_percent": 40, "auto_enabled": False})
        s = settings_store.load()
        self.assertEqual(s["plan"], "max5")
        self.assertEqual(s["budget_percent"], 40)
        self.assertFalse(s["auto_enabled"])

    def test_validation(self):
        for bad in ({"plan": "ultra"}, {"budget_percent": 3},
                    {"budget_percent": 101}, {"budget_percent": True},
                    {"auto_enabled": "yes"}, {"bogus": 1}):
            with self.assertRaises(ValueError):
                settings_store.save(bad)

    def test_corrupt_file_tolerated(self):
        Path(settings_store.SETTINGS_FILE).write_text("{nope")
        self.assertEqual(settings_store.load(), settings_store.DEFAULTS)

    def test_clean_schedule(self):
        self.assertEqual(
            settings_store.clean_schedule(["19:00", "7:30", "07:30"]),
            ["07:30", "19:00"])
        self.assertIsNone(settings_store.clean_schedule(None))
        self.assertIsNone(settings_store.clean_schedule([]))
        for bad in ("07:00", ["24:00"], ["7pm"], [7], ["07:00"] * 0 + ["1:2"]):
            with self.assertRaises(ValueError):
                settings_store.clean_schedule(bad)
        with self.assertRaises(ValueError):
            settings_store.clean_schedule(
                [f"0{i}:00" for i in range(settings_store.MAX_SCHEDULE_TIMES + 1)])


class TestUsageStore(TempStoresMixin, unittest.TestCase):
    def test_window_and_pruning(self):
        now = time.time()
        usage_store.record_run(10_000, "energy", now=now - 3600)
        usage_store.record_run(5_000, "climate", now=now - 6 * 3600)  # outside 5h
        usage_store.record_run(0, "noop", now=now)  # ignored
        self.assertEqual(usage_store.window_tokens(now=now), 10_000)
        # the 6h-old run survives (24h retention) but is outside the window
        runs = json.loads(Path(usage_store.USAGE_FILE).read_text())["runs"]
        self.assertEqual(len(runs), 2)

    def test_tokens_from_meta_excludes_cache_reads(self):
        meta = {"usage": {"input_tokens": 100, "output_tokens": 50,
                          "cache_creation_input_tokens": 25,
                          "cache_read_input_tokens": 9999}}
        self.assertEqual(usage_store.tokens_from_meta(meta), 175)
        self.assertEqual(usage_store.tokens_from_meta({}), 0)
        self.assertEqual(usage_store.tokens_from_meta({"usage": "x"}), 0)

    def test_budget_estimate_blocks(self):
        now = time.time()
        usage_store.record_run(100_000, "energy", now=now - 60)
        st = usage_store.budget_state({"plan": "pro", "budget_percent": 25}, now=now)
        self.assertEqual(st["source"], "estimate")
        self.assertTrue(st["blocked"])  # 100k of 300k ≈ 33% ≥ 25%
        st = usage_store.budget_state({"plan": "max20", "budget_percent": 25}, now=now)
        self.assertFalse(st["blocked"])  # 100k of 6M ≈ 1.7%

    def test_real_utilization_wins(self):
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        resets = now_dt + datetime.timedelta(hours=2)
        Path(usage_store.LIMITS_FILE).write_text(json.dumps(
            {"updated_at": now_dt.isoformat(),
             "five_hour": {"utilization": 91,
                           "resets_at": resets.isoformat()}}))
        st = usage_store.budget_state({"plan": "max20", "budget_percent": 90})
        self.assertEqual(st["source"], "account")
        self.assertTrue(st["blocked"])
        self.assertEqual(st["resets_at"], int(resets.timestamp()))

    def test_estimate_resets_when_oldest_run_ages_out(self):
        now = time.time()
        usage_store.record_run(10_000, "energy", now=now - 4000)
        usage_store.record_run(10_000, "climate", now=now - 100)
        st = usage_store.budget_state({"plan": "pro", "budget_percent": 50}, now=now)
        self.assertEqual(st["source"], "estimate")
        self.assertEqual(
            st["resets_at"],
            int((now - 4000) + usage_store.SESSION_HOURS * 3600))

    def test_no_reset_time_without_runs_or_tracker(self):
        st = usage_store.budget_state({"plan": "pro", "budget_percent": 50})
        self.assertIsNone(st["resets_at"])

    def test_stale_or_error_limits_ignored(self):
        Path(usage_store.LIMITS_FILE).write_text(json.dumps(
            {"updated_at": "2020-01-01T00:00:00+00:00",
             "five_hour": {"utilization": 91}}))
        self.assertIsNone(usage_store.real_session_utilization())
        Path(usage_store.LIMITS_FILE).write_text(json.dumps(
            {"error": "no_oauth_token"}))
        self.assertIsNone(usage_store.real_session_utilization())


class TestScheduleOverrides(TempStoresMixin, unittest.TestCase):
    def test_prompt_store_schedule_roundtrip(self):
        prompt_store.save_override("energy", {"schedule": ["07:00", "19:00"]})
        eff = prompt_store.effective_category("energy")
        self.assertEqual(eff["schedule"], ["07:00", "19:00"])
        self.assertIn("schedule", eff["overridden"])
        prompt_store.save_override("energy", {"schedule": None})
        eff = prompt_store.effective_category("energy")
        self.assertIsNone(eff["schedule"])
        self.assertNotIn("schedule", eff["overridden"])

    def test_user_category_schedule(self):
        cat = user_categories.create(
            {"title": "T", "focus": "F", "schedule": ["6:15"]})
        self.assertEqual(cat["schedule"], ["06:15"])
        cat = user_categories.update(cat["id"], {"schedule": None})
        self.assertIsNone(cat["schedule"])
        with self.assertRaises(ValueError):
            user_categories.create(
                {"title": "T2", "focus": "F", "schedule": ["25:00"]})


class TestServerScheduling(TempStoresMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        os.environ["BRUH_INSIGHTS_DIR"] = os.path.join(self.tmp.name, "insights")
        os.environ["BRUH_INSIGHTS_SECRETS"] = os.path.join(self.tmp.name, "secrets")
        os.environ["BRUH_INSIGHTS_SETTINGS_FILE"] = settings_store.SETTINGS_FILE
        os.environ["BRUH_INSIGHTS_USAGE_FILE"] = usage_store.USAGE_FILE
        import server
        self.server = importlib.reload(server)

    @staticmethod
    def _iso(epoch):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))

    @staticmethod
    def _hhmm(epoch):
        return time.strftime("%H:%M", time.localtime(epoch))

    def test_schedule_due(self):
        now = time.time()
        past = self._hhmm(now - 1800)
        future = self._hhmm(now + 1800)
        gen_before = self._iso(now - 7200)
        gen_after = self._iso(now - 60)
        self.assertTrue(self.server._schedule_due([past], gen_before, now))
        self.assertFalse(self.server._schedule_due([past], gen_after, now))
        # a future-today time still has yesterday's occurrence behind us
        self.assertTrue(self.server._schedule_due([future], "", now))
        self.assertTrue(self.server._schedule_due([past], "not-a-date", now))

    def test_refresh_due_schedule_beats_interval(self):
        now = time.time()
        past = self._hhmm(now - 1800)
        gen_recent = self._iso(now - 60)
        # interval alone says "not due", the passed schedule time says "due"
        self.assertFalse(self.server._refresh_due(
            {"enabled": True, "refresh_hours": 24}, gen_recent, now))
        self.assertTrue(self.server._refresh_due(
            {"enabled": True, "refresh_hours": 24, "schedule": [past]},
            self._iso(now - 7200), now))
        self.assertFalse(self.server._refresh_due(
            {"enabled": False, "schedule": [past]}, "", now))

    def test_settings_routes(self):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            app = self.server.make_app()
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                resp = await client.get("/api/settings")
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertIn("settings", data)
                self.assertIn("usage", data)
                self.assertEqual(len(data["plans"]), 3)

                resp = await client.put("/api/settings", json={
                    "auto_enabled": False, "plan": "max5", "budget_percent": 50})
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertFalse(data["settings"]["auto_enabled"])
                self.assertEqual(data["settings"]["plan"], "max5")

                resp = await client.put("/api/settings", json={"plan": "nope"})
                self.assertEqual(resp.status, 400)

                # status carries settings + usage for the panel chip
                resp = await client.get("/api/status")
                data = await resp.json()
                self.assertFalse(data["settings"]["auto_enabled"])
                self.assertIn("used_percent", data["usage"])

                # per-category schedule via the prompt endpoint
                resp = await client.put("/api/prompt/energy", json={
                    "schedule": ["7:00", "19:00"]})
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data["schedule"], ["07:00", "19:00"])
                resp = await client.put("/api/prompt/energy", json={
                    "schedule": ["25:99"]})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/prompt/energy", json={
                    "schedule": None})
                self.assertEqual(resp.status, 200)
                self.assertIsNone((await resp.json())["schedule"])
            finally:
                await client.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
