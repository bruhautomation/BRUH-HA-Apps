#!/usr/bin/env python3
"""The tripwire, panel side: made on a press, read by the MCP server from a
file, and a trip files a security case by code.

The MCP half (any acting call on a tripwire is refused before every other
guard and reported) is `tests/test_change_contract.py`; this is the half
the report lands in, and the file both halves agree on.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import cases  # noqa: E402
import findings_store  # noqa: E402
import notify_router  # noqa: E402
import security  # noqa: E402
import settings_store  # noqa: E402

from test_todo_list import PanelCase  # noqa: E402

MCP = BASE_DIR / "brain" / "ha-mcp-server" / "ha_mcp_server.py"
TOKEN = "input_boolean.brain_honeytoken"


class TripwireCase(PanelCase):
    def setUp(self):
        super().setUp()
        self._sec_mods = {id(m): m for m in (security, self.server.security)}
        self._sec_old = {k: m.HONEYTOKEN_FILE for k, m in self._sec_mods.items()}
        for m in self._sec_mods.values():
            m.HONEYTOKEN_FILE = Path(self.tmp.name) / "brain" / "honey.json"
        security.HONEYTOKEN_FILE.parent.mkdir(parents=True)
        self.announced = []

        async def announce(rows):
            self.announced.extend(rows)

        async def fallback(row):
            self.announced.append(row)

        self._ann_old = (self.server._announce_findings,
                         self.server._safety_fallback_notice)
        self.server._announce_findings = announce
        self.server._safety_fallback_notice = fallback

    def tearDown(self):
        for k, m in self._sec_mods.items():
            m.HONEYTOKEN_FILE = self._sec_old[k]
        (self.server._announce_findings,
         self.server._safety_fallback_notice) = self._ann_old
        super().tearDown()

    def made(self):
        security.HONEYTOKEN_FILE.write_text(json.dumps(
            {"entities": [TOKEN], "created": [{"entity_id": TOKEN,
                                               "item_id": "brain_honeytoken"}]}))


class TestATripFilesASecurityCase(TripwireCase):
    def test_the_report_files_a_case_by_code_and_announces_it(self):
        self.made()

        async def body(client):
            res = await client.post("/api/security/tripwire", json={
                "entity": TOKEN, "call": "input_boolean.turn_on",
                "channel": "chat", "run_id": "abc-123"})
            return res.status, await res.json()

        status, payload = self.drive(body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["filed"])
        row = findings_store.get(payload["ts"])
        self.assertEqual(row["source"], "security")
        self.assertEqual(row["severity"], "critical")
        self.assertEqual(row["status"], "open",
                         "a tripwire is shown, never held by triage")
        self.assertEqual(row["run_id"], "abc-123")
        self.assertIn("chat", row["detail"])
        self.assertEqual([r["ts"] for r in self.announced], [payload["ts"]])

    def test_a_report_about_anything_else_is_refused(self):
        async def body(client):
            res = await client.post("/api/security/tripwire",
                                    json={"entity": "light.kitchen"})
            return res.status

        self.assertEqual(self.drive(body), 400)
        self.assertEqual(findings_store.list_all(), [])

    def test_a_person_named_tripwire_counts(self):
        settings_store.save({"honeytoken_entities": ["switch.decoy"]})
        self.assertIn("switch.decoy", security.honeytoken_ids())

    def test_security_cannot_be_muted_and_is_urgent(self):
        self.assertIn("security", cases.UNMUTABLE_SOURCES)
        self.assertEqual(notify_router.PRODUCER_URGENCY.get("security"), "now")


class TestMakingTheTripwire(TripwireCase):
    def setUp(self):
        super().setUp()
        import ha_data
        self.ha_data = ha_data
        self._ws_old = ha_data._ws_calls
        self.created = []

        async def ws(session, commands, **k):
            self.created.append(commands)
            # Core mints the id from the NAME, `_2` and all, when the slug
            # is taken — so the test answers with a collided one.
            return [{"ok": True, "error": "",
                     "result": {"id": "brain_honeytoken_2",
                                "name": commands[0]["name"]}}]

        ha_data._ws_calls = ws

    def tearDown(self):
        self.ha_data._ws_calls = self._ws_old
        super().tearDown()

    def test_the_minted_id_is_read_back_and_written_for_the_mcp_server(self):
        async def body(client):
            res = await client.post("/api/security/honeytoken")
            return res.status, await res.json()

        status, payload = self.drive(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["entities"], ["input_boolean.brain_honeytoken_2"])
        on_disk = json.loads(security.HONEYTOKEN_FILE.read_text())
        self.assertEqual(on_disk["entities"],
                         ["input_boolean.brain_honeytoken_2"])
        self.assertEqual(self.created[0][0]["type"], "input_boolean/create")

    def test_a_second_press_does_not_make_another(self):
        self.made()

        async def body(client):
            res = await client.post("/api/security/honeytoken")
            return await res.json()

        payload = self.drive(body)
        self.assertFalse(payload["created"])
        self.assertEqual(self.created, [])


class TestBothHalvesReadOneFile(unittest.TestCase):
    def test_the_default_path_is_spelled_the_same_in_both(self):
        saved = os.environ.pop("BRAIN_HONEYTOKEN_FILE", None)
        try:
            spec = importlib.util.spec_from_file_location("mcp_honey", MCP)
            mcp = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mcp)
            sec_spec = importlib.util.spec_from_file_location(
                "security_fresh", BASE_DIR / "brain" / "panel" / "security.py")
            sec = importlib.util.module_from_spec(sec_spec)
            sec_spec.loader.exec_module(sec)
        finally:
            if saved is not None:
                os.environ["BRAIN_HONEYTOKEN_FILE"] = saved
        self.assertEqual(str(mcp.HONEYTOKEN_FILE), str(sec.HONEYTOKEN_FILE))

    def test_the_mcp_server_reads_what_the_panel_writes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "honey.json"
            old = security.HONEYTOKEN_FILE
            security.HONEYTOKEN_FILE = path
            try:
                security.publish([{"entity_id": TOKEN}])
            finally:
                security.HONEYTOKEN_FILE = old
            spec = importlib.util.spec_from_file_location("mcp_honey2", MCP)
            mcp = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mcp)
            mcp.HONEYTOKEN_FILE = str(path)
            self.assertIn(TOKEN, mcp._honeytokens())

    def test_an_empty_boot_writes_no_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            old = security.HONEYTOKEN_FILE
            security.HONEYTOKEN_FILE = Path(tmp) / "honey.json"
            old_settings = settings_store.SETTINGS_FILE
            settings_store.SETTINGS_FILE = os.path.join(tmp, "s.json")
            try:
                self.assertEqual(security.publish(), [])
                self.assertFalse(security.HONEYTOKEN_FILE.exists())
            finally:
                security.HONEYTOKEN_FILE = old
                settings_store.SETTINGS_FILE = old_settings


if __name__ == "__main__":
    unittest.main()
