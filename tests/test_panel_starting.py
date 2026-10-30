#!/usr/bin/env python3
"""The panel binds its port first, and answers "starting" until it is ready.

aiohttp binds only after every ``on_startup`` hook returns, and brAIn's held
fifteen migrations, syncs and the event bus — so Home Assistant's ingress
showed a 502 for the whole of every start. The slow half now runs after the
bind, and a request that needs it is held briefly and then answered: the
page's root with a small page that reloads itself, an API route with a
plain 503 the panel retries.
"""

import asyncio
import importlib
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

pytestmark = pytest.mark.slow

_ENV = {
    "BRAIN_CHAT_TRANSCRIPT": "t.json",
    "BRAIN_CHAT_TRANSCRIPT_DIR": "chat",
    "BRAIN_SETTINGS_FILE": "settings.json",
    "BRAIN_DIR": "insights",
    "BRAIN_SECRETS": "secrets",
    "BRAIN_RUN_SOURCES": "run-sources.jsonl",
    "BRAIN_CHAT_TRASH": "chat-trash",
    "BRAIN_JOURNAL_FILE": "journal.jsonl",
    "BRAIN_USAGE_NUDGE": "usage-nudge",
    "BRAIN_USAGE_FILE": "usage.json",
}


class TestBindFirst(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV}
        for key, leaf in _ENV.items():
            os.environ[key] = os.path.join(self.tmp.name, leaf)
        os.environ["BRAIN_CHAT_WORKDIR"] = self.tmp.name
        for name in ("journal", "usage_store", "settings_store", "run_sources",
                     "chat_session", "server"):
            setattr(self, name, importlib.reload(importlib.import_module(name)))
        # The first piece of the slow half, held until the test lets go.
        self.release = threading.Event()
        self.reached = threading.Event()

        def held():
            self.reached.set()
            self.release.wait(20)

        self.patches = [
            unittest.mock.patch.object(self.server.instructions, "apply_all",
                                       held),
            unittest.mock.patch.object(self.server, "STARTING_WAIT_S", 0.3),
            unittest.mock.patch.object(self.server, "STARTING_PAGE_WAIT_S", 0.1),
        ]
        for p in self.patches:
            p.start()
        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))

    async def asyncTearDown(self):
        self.release.set()
        await self.client.close()
        for p in self.patches:
            p.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        os.environ.pop("BRAIN_CHAT_WORKDIR", None)
        for name in ("journal", "usage_store"):
            importlib.reload(importlib.import_module(name))
        self.tmp.cleanup()

    async def test_the_port_answers_while_the_migrations_are_still_running(self):
        await asyncio.wait_for(self.client.start_server(), 10)
        # The server is up and answering while the slow half is stuck in
        # its very first step — which is what "bound before the
        # migrations" means from outside.
        self.assertTrue(await asyncio.to_thread(self.reached.wait, 5))
        ready = await (await self.client.get("/api/ready")).json()
        self.assertFalse(ready["ready"])

        page = await self.client.get("/")
        self.assertEqual(page.status, 200)
        text = await page.text()
        self.assertIn("brAIn is starting", text)
        self.assertIn("api/ready", text)

        api = await self.client.get("/api/status")
        self.assertEqual(api.status, 503)
        body = await api.json()
        self.assertTrue(body["starting"])

        # The panel's own files are served: the page can load.
        self.assertEqual((await self.client.get("/app.js")).status, 200)

        self.release.set()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15
        while loop.time() < deadline:
            if (await (await self.client.get("/api/ready")).json())["ready"]:
                break
            await asyncio.sleep(0.05)
        self.assertTrue((await (await self.client.get("/api/ready")).json())["ready"])
        page = await self.client.get("/")
        self.assertNotIn("brAIn is starting", await page.text())

    async def test_a_request_during_a_short_start_is_simply_waited_for(self):
        self.patches[1].stop()
        self.patches[1] = unittest.mock.patch.object(
            self.server, "STARTING_WAIT_S", 10)
        self.patches[1].start()
        await self.client.start_server()
        self.assertTrue(await asyncio.to_thread(self.reached.wait, 5))
        asyncio.get_running_loop().call_later(0.3, self.release.set)
        resp = await self.client.get("/api/ready")
        self.assertEqual(resp.status, 200)
        settings = await self.client.get("/api/settings")
        self.assertEqual(settings.status, 200)


if __name__ == "__main__":
    unittest.main()
