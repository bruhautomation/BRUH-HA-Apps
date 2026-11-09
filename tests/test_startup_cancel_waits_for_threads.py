#!/usr/bin/env python3
"""A panel stopped before its start finished leaves no thread writing.

`on_cleanup` cancels a start that is still running. The start's steps are
file work done in threads, and cancelling the coroutine that awaits a
thread returns at once while the thread carries on — so a panel closed a
second after it bound came back from cleanup with `instructions.apply_all`
(or the mirror, or the prompt) still writing into its directories, and
whatever removed them next raced it. That was a CI failure in
`test_ask_routing` ("OSError: [Errno 39] Directory not empty") whenever
the runner was slow enough for a test to finish before the start did.

The step here is held open in its thread past the moment cleanup cancels
it, and cleanup has to come back only after that step is over.
"""

import asyncio
import importlib
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

pytestmark = pytest.mark.slow

_ENV = ("BRAIN_CHAT_TRANSCRIPT", "BRAIN_CHAT_TRANSCRIPT_DIR",
        "BRAIN_CHAT_WORKDIR", "BRAIN_SETTINGS_FILE", "BRAIN_DIR",
        "BRAIN_SECRETS", "BRAIN_RUN_SOURCES", "BRAIN_CHAT_TRASH",
        "BRAIN_TERMINAL_HANDOFF", "BRAIN_JOURNAL_FILE", "BRAIN_USAGE_FILE",
        "BRAIN_MEMINFO")


class TestCleanupWaitsForTheStartsThread(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = self.tmp.name
        self._saved_env = {k: os.environ.get(k) for k in _ENV}
        for key, value in {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(tmp, "t.json"),
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(tmp, "chat"),
            "BRAIN_CHAT_WORKDIR": tmp,
            "BRAIN_SETTINGS_FILE": os.path.join(tmp, "settings.json"),
            "BRAIN_DIR": os.path.join(tmp, "insights"),
            "BRAIN_SECRETS": os.path.join(tmp, "secrets"),
            "BRAIN_RUN_SOURCES": os.path.join(tmp, "run-sources.jsonl"),
            "BRAIN_CHAT_TRASH": os.path.join(tmp, "chat-trash"),
            "BRAIN_TERMINAL_HANDOFF": os.path.join(tmp, "handoff.json"),
            "BRAIN_JOURNAL_FILE": os.path.join(tmp, "journal.jsonl"),
            "BRAIN_USAGE_FILE": os.path.join(tmp, "usage.json"),
            "BRAIN_MEMINFO": os.path.join(tmp, "no-meminfo"),
        }.items():
            os.environ[key] = value
        for name in ("journal", "usage_store", "settings_store", "run_sources",
                     "conversations"):
            importlib.reload(importlib.import_module(name))
        self.chat_session = importlib.reload(importlib.import_module("chat_session"))
        self.server = importlib.reload(importlib.import_module("server"))
        self.instructions = importlib.import_module("instructions")
        self._real_apply_all = self.instructions.apply_all
        self.entered = threading.Event()
        self.finished = threading.Event()

        def slow_step():
            # The first step of the start, held long enough that cleanup
            # arrives while it is still in its thread.
            self.entered.set()
            try:
                time.sleep(0.5)
            finally:
                self.finished.set()

        self.instructions.apply_all = slow_step

    async def asyncTearDown(self):
        # Whatever the outcome, nothing of this test may still be running
        # when its directory goes (the very race this file is about).
        await asyncio.to_thread(self.finished.wait, 10)
        self.instructions.apply_all = self._real_apply_all
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for name in ("journal", "usage_store"):
            importlib.reload(importlib.import_module(name))
        self.tmp.cleanup()

    async def test_closing_mid_start_returns_after_the_step_in_its_thread(self):
        from aiohttp.test_utils import TestClient, TestServer
        client = TestClient(TestServer(self.server.make_app()))
        await client.start_server()
        app = client.server.app
        self.assertTrue(await asyncio.to_thread(self.entered.wait, 10),
                        "the start never reached its first step")
        await client.close()
        await self.chat_session.registry().stop_all()
        self.assertTrue(self.finished.is_set(),
                        "cleanup came back while the start's thread was "
                        "still running")
        self.assertTrue(app["tasks"]["startup"].done())

    async def test_the_cancel_still_lands(self):
        """Waited out, not run to the end: the start stops at that step."""
        reached = []
        real_export = self.instructions.export_builtins
        self.instructions.export_builtins = lambda: reached.append(1)
        try:
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            app = client.server.app
            self.assertTrue(await asyncio.to_thread(self.entered.wait, 10))
            await client.close()
            await self.chat_session.registry().stop_all()
            self.assertTrue(app["tasks"]["startup"].cancelled())
            self.assertEqual(reached, [], "the start ran on past its cancel")
        finally:
            self.instructions.export_builtins = real_export


if __name__ == "__main__":
    unittest.main()
