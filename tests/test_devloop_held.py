#!/usr/bin/env python3
"""A report marked to send that has not gone yet says why, and what ends it.

⚙ › Developer › Help develop brAIn listed such a row as "will be sent",
which the owner read as brAIn stalling: Send already sends at once, so a
row that is still `ready` afterwards has been HELD — almost always by the
day's cap on new issues (Daily limits), otherwise by a send that failed.
The payload now carries what the panel needs to say which (`held`: the
cap, how many new issues today, whether that is all of them and when the
first frees up), the Send route's answer carries `capped`, and the panel's
words for a held row name the cap and its two remedies rather than
promising a send.

GitHub is the same loopback fake `test_devloop` uses, so a send is a real
send and the cap is the real `send_due`'s.
"""
from __future__ import annotations

import asyncio
import importlib
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop  # noqa: E402
import devloop.github  # noqa: E402
import devloop.upstream  # noqa: E402

from test_devloop import NAMES, TOKEN, FakeGitHub, diagnostics  # noqa: E402

github = devloop.github
upstream = devloop.upstream


class HeldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API,
                     dict(upstream.STATE))
        devloop.DATA_DIR = base / "devloop"
        devloop.TOKEN_FILE = base / "secrets" / "devloop_github_token"
        self.gh = FakeGitHub()
        github.API = self.gh.url
        upstream.STATE.update(last_sweep=0.0, last_send=0.0, error="",
                              running=False)
        self._faults = upstream.reports.faults
        rows = [{"where": "Runs", "what": "card ended timeout 3 times",
                 "detail": "it timed out"},
                {"where": "Daemons", "what": "not running: automation_listener",
                 "detail": "it stopped"}]
        upstream.reports.faults = lambda diag: [dict(r) for r in rows]
        devloop.save_settings({"enabled": True, "repo": "me/reports",
                               "review": True, "max_issues_per_day": 1})
        devloop.save_token(TOKEN)
        self.server = importlib.import_module("server")

    def tearDown(self):
        upstream.reports.faults = self._faults
        (devloop.DATA_DIR, devloop.TOKEN_FILE, github.API, state) = self._old
        upstream.STATE.clear()
        upstream.STATE.update(state)
        self.gh.close()
        self.tmp.cleanup()

    def _client(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        app = web.Application()
        app.router.add_get("/api/devloop", self.server.h_devloop_get)
        app.router.add_post("/api/devloop/item/{fp}/{verb}",
                            self.server.h_devloop_item_verb)
        return TestClient(TestServer(app))


class TestAHeldReportSaysWhy(HeldCase):
    def test_the_payload_says_the_cap_is_full_and_when_it_frees(self):
        t = time.time()
        upstream.sweep(diagnostics(), NAMES, now=t)
        fps = [r["fp"] for r in upstream.listing() if r["state"] == "pending"]
        self.assertEqual(len(fps), 2)

        async def go():
            async with self._client() as c:
                r = await c.post(f"/api/devloop/item/{fps[0]}/send")
                first = await r.json()
                r = await c.post(f"/api/devloop/item/{fps[1]}/send")
                second = await r.json()
                return first, second

        first, second = asyncio.run(go())
        self.assertEqual(first.get("sent"), 1)
        self.assertEqual(len(self.gh.issues), 1)
        # The second press was accepted and HELD by the day's cap, and the
        # answer says so in a field the toast can read.
        self.assertEqual(second.get("capped"), 1)
        held_row = [r for r in second["queue"] if r["fp"] == fps[1]][0]
        self.assertEqual(held_row["state"], "ready")
        held = second["held"]
        self.assertEqual(held["limit"], 1)
        self.assertEqual(held["today"], 1)
        self.assertTrue(held["full"])
        self.assertGreater(held["frees_at"], t + 86400 - 60)
        self.assertLess(held["frees_at"], t + 86400 + 60)

    def test_an_empty_day_is_not_full(self):
        held = self.server._devloop_payload()["held"]
        self.assertEqual((held["limit"], held["today"], held["full"]), (1, 0, False))
        self.assertFalse(held["frees_at"])


class TestThePanelWords(unittest.TestCase):
    def setUp(self):
        self.app = (PANEL_DIR / "app.js").read_text(encoding="utf-8")

    def test_will_be_sent_is_gone(self):
        self.assertNotIn("will be sent", self.app)

    def test_a_held_row_names_the_cap_and_its_remedies(self):
        fn = re.search(r"function devHeldReason\((.*?)\n\}\n", self.app, re.S)
        self.assertIsNotNone(fn, "devHeldReason is the one place a held row is worded")
        body = fn.group(1)
        self.assertIn("Daily limits", body)
        self.assertIn("held.full", body)
        self.assertIn("capped", body)


if __name__ == "__main__":
    unittest.main()
