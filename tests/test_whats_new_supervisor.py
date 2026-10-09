#!/usr/bin/env python3
"""What's new is read the way the Supervisor really serves it.

The store's changelog route (`/store/addons/<slug>/changelog`, and the
legacy `/addons/<slug>/changelog` reroute) looks the slug up literally and
does not resolve `self`; asked for `self` it answers **HTTP 200** with the
sentence "Addon self does not exist", because its own frontend cannot show
an error response there. brAIn asked for `/addons/self/changelog`, read that
sentence as the notes, found no versions in it and showed only the link to
GitHub — which is the owner's "it's still dumping me to GitHub".

The fake below answers the way the Supervisor's `api/store.py` does
(`_extract_app` + the changelog handler), not the way the code guessed.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer, make_mocked_request

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import addon_options  # noqa: E402

SLUG = "a0d7b954_brain"

NOTES = """# Changelog

## 2.18.13

### Fixed

- The thing.

## 2.18.12

### Added

- What's new.
"""


class RealShapedSupervisor:
    """`/addons/{app}/info` resolves `self`; the changelog routes do not."""

    def __init__(self, with_changelog: bool = True):
        self.with_changelog = with_changelog
        self.asked: list[str] = []

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/addons/{app}/info", self._info)
        app.router.add_get("/store/addons/{app}/changelog", self._changelog)
        app.router.add_get("/addons/{app}/changelog", self._changelog)
        return app

    async def _info(self, request: web.Request) -> web.Response:
        assert request.headers.get("Authorization") == "Bearer test-token"
        app = request.match_info["app"]
        if app not in ("self", SLUG):
            return web.json_response({"result": "error"}, status=404)
        return web.json_response({"result": "ok",
                                  "data": {"slug": SLUG, "options": {}}})

    async def _changelog(self, request: web.Request) -> web.Response:
        assert request.headers.get("Authorization") == "Bearer test-token"
        app = request.match_info["app"]
        self.asked.append(request.path)
        # The Supervisor's own words, with a 200, exactly as it answers.
        if app != SLUG:
            return web.Response(text=f"Addon {app} does not exist",
                                content_type="text/plain")
        if not self.with_changelog:
            return web.Response(text=f"No changelog found for app {app}!",
                                content_type="text/plain")
        return web.Response(text=NOTES, content_type="text/plain")


class TestWhatsNewAsksByTheRealSlug(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self._old = (addon_options.SUPERVISOR_URL, addon_options.TOKEN,
                     dict(addon_options._info),
                     os.environ.pop("BRAIN_ADDON_SLUG", None))
        addon_options._info.clear()

    def tearDown(self):
        (addon_options.SUPERVISOR_URL, addon_options.TOKEN, info,
         env) = self._old
        addon_options._info.clear()
        addon_options._info.update(info)
        if env is not None:
            os.environ["BRAIN_ADDON_SLUG"] = env

    def _ask(self, sv_fake: RealShapedSupervisor) -> dict:
        async def run():
            sv = TestServer(sv_fake.app())
            await sv.start_server()
            try:
                addon_options.SUPERVISOR_URL = str(sv.make_url("")).rstrip("/")
                addon_options.TOKEN = "test-token"
                resp = await self.server.h_changelog(
                    make_mocked_request("GET", "/api/changelog"))
                return json.loads(resp.body)
            finally:
                await sv.close()
        return asyncio.run(run())

    def test_the_notes_arrive_when_self_is_not_resolved(self):
        fake = RealShapedSupervisor()
        body = self._ask(fake)
        self.assertEqual(body["error"], "")
        self.assertEqual([s["version"] for s in body["sections"]],
                         ["2.18.13", "2.18.12"])
        self.assertIn(f"/store/addons/{SLUG}/changelog", fake.asked)
        self.assertEqual(addon_options._info.get("slug"), SLUG)

    def test_a_200_refusal_is_a_refusal_not_the_notes(self):
        body = self._ask(RealShapedSupervisor(with_changelog=False))
        self.assertEqual(body["sections"], [])
        self.assertIn("No changelog found", body["error"])
        self.assertNotIn("no versions", body["error"])


if __name__ == "__main__":
    unittest.main()
