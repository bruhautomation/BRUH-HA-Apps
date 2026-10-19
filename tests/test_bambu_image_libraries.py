"""BRUH Bambu Studio's panel runs on the libraries its image has.

The image is Debian bookworm and takes aiohttp and paho-mqtt from apt
(aiohttp 3.8, paho-mqtt 1.6), while this suite runs whatever pip installed,
which is newer. 0.1.0 used `web.AppKey`, added in aiohttp 3.9, so the panel
died on import in the add-on while every test here passed. These tests take
the newer API away and run the panel without it.
"""
from __future__ import annotations

import os
import re
import unittest
import unittest.mock

from aiohttp import web

from tests import bambu_env

ROOT = os.path.join(os.path.dirname(__file__), "..", "bruh-bambu-studio")


class TestThePanelRunsOnBookwormsAiohttp(unittest.TestCase):
    def test_the_image_takes_aiohttp_from_apt(self):
        # If aiohttp ever comes from pip instead, this file's premise moved.
        with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("python3-aiohttp", text)
        self.assertIn("debian:bookworm", text)

    def test_without_appkey_the_panel_still_builds_and_finds_itself(self):
        saved = web.AppKey
        del web.AppKey
        try:
            (server,) = bambu_env.load("server")
            panel = object()
            app = server.build_app(panel, ticker=False)
            request = unittest.mock.Mock(app=app)
            self.assertIs(server._panel(request), panel)
        finally:
            web.AppKey = saved

    def test_nothing_newer_than_aiohttp_38_is_named(self):
        # The APIs 3.9+ added that a panel would plausibly reach for.
        newer = ("AppKey", "ConnectionTimeoutError", "SocketTimeoutError")
        found = []
        for dirpath, _dirs, files in os.walk(os.path.join(ROOT, "panel")):
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        code = line.split("#", 1)[0]
                        for api in newer:
                            if re.search(rf"\bweb\.{api}\(", code) and "hasattr" not in code:
                                found.append(f"{name}:{n} web.{api}")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
