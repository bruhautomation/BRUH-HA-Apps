"""The panel-routes fixture the safety tests share (was in test_todo_list.py)."""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import findings_store  # noqa: E402
import todo_store  # noqa: E402


class PanelCase(unittest.TestCase):
    """The routes, over a real client. `test_panel_edits`' harness."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        import engine
        import settings_store
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = (
            findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
            findings_store.STATE_FILE, findings_store.INBOX_DIR,
            todo_store.TODO_FILE, todo_store.STATE_FILE,
            self.server.INSIGHTS_DIR, self.server.MEMORY_INBOX_DIR,
            self.server.CARD_TOKEN_FILE, self.server.WWW_CARD_DIR,
            settings_store.SETTINGS_FILE, engine.run_claude,
        )
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.SETTLED_FILE = tmp / "settled.json"
        findings_store.STATE_FILE = tmp / "nowhere" / ".brain" / "s.json"
        findings_store.INBOX_DIR = tmp / "findings-inbox"
        todo_store.TODO_FILE = tmp / "todo.json"
        todo_store.STATE_FILE = tmp / "nowhere" / ".brain" / "todo.json"
        self.server.INSIGHTS_DIR = tmp
        self.server.MEMORY_INBOX_DIR = tmp / "memory-inbox"
        self.server.CARD_TOKEN_FILE = tmp / "secrets" / "card_token"
        self.server.WWW_CARD_DIR = tmp / "www" / "brain"
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        settings_store.save({"onboarded": True})
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": "OK", "error": "", "meta": {}}
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        import engine
        import settings_store
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, findings_store.INBOX_DIR,
         todo_store.TODO_FILE, todo_store.STATE_FILE,
         self.server.INSIGHTS_DIR, self.server.MEMORY_INBOX_DIR,
         self.server.CARD_TOKEN_FILE, self.server.WWW_CARD_DIR,
         settings_store.SETTINGS_FILE, engine.run_claude) = self._olds
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def file_finding(self, text="the hall sensor is stuck"):
        entry, _created = findings_store.add(
            text, severity="warning", detail="last seen 3 Sep",
            fix="Re-pair it", entity_id="binary_sensor.hall",
            source="check:devices", source_title="Device checks")
        return entry

    def queued_memory(self) -> list[str]:
        """Every line waiting in the memory inbox, as plain text."""
        out = []
        for path in sorted(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")):
            for line in path.read_text().splitlines():
                if line.strip():
                    out.append(json.loads(line).get("fact", ""))
        return out

    def drive(self, body):
        """Run one coroutine against a live client."""
        async def run():
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()
        return asyncio.run(run())

