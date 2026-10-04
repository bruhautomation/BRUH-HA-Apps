#!/usr/bin/env python3
"""A fault healed every night is filed WITH the logs read.

`healing` already stopped healing a target after `CHRONIC_HEALS` nights and
filed "this keeps happening". What it filed named the log to go and read;
this reads it, when the finding is filed, so the card carries the lines
that say why. The add-on log is fetched from a real aiohttp server playing
the Supervisor (the request's headers are part of the claim), Home
Assistant's own log through `ha_data._ws_commands`, and the server's heal
pass is driven into the real findings store.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import healing  # noqa: E402

from test_acting_followups import TestTheServerFilesTheChronicFinding  # noqa: E402

ADDON = {"remedy": "addon.start", "target": "core_mosquitto",
         "label": "Mosquitto", "sentence": "started the Mosquitto add-on"}
LOG = ("\x1b[32m[info] starting\x1b[0m\n"
       "[info] listening on 1883\n"
       "\x1b[31m[error] Out of memory: killed\x1b[0m\n"
       "[warning] token sk-ant-oat01-AAAABBBBCCCCDDDDEEEEFFFFGGGG leaked\n"
       "[info] bye\n")


class TestTheExcerpt(unittest.TestCase):
    def test_trouble_lines_colours_stripped_tokens_scrubbed(self):
        lines = healing.log_excerpt(LOG)
        self.assertEqual(lines[0], "[error] Out of memory: killed")
        self.assertNotIn("\x1b", "".join(lines))
        self.assertNotIn("sk-ant-oat01-AAAA", "".join(lines))
        self.assertNotIn("listening on 1883", "".join(lines))

    def test_with_no_trouble_it_is_the_last_lines(self):
        self.assertEqual(healing.log_excerpt("a\nb\nc"), ["a", "b", "c"])

    def test_the_finding_quotes_them_or_says_it_could_not_read(self):
        heals = [1_700_000_000, 1_700_100_000, 1_700_200_000]
        row = healing.chronic_finding(ADDON, heals, dt.timezone.utc,
                                      ["[error] boom"], "the Mosquitto log")
        self.assertIn("«[error] boom»", row["detail"])
        self.assertEqual(row["text"], "Mosquitto keeps stopping",
                         "the log stays out of the text the store dedupes on")
        row = healing.chronic_finding(ADDON, heals, dt.timezone.utc, [],
                                      "could not read the log (500)")
        self.assertIn("brAIn could not read the log", row["detail"])


class TestReadingTheLogs(unittest.IsolatedAsyncioTestCase):
    async def test_the_addon_log_is_asked_of_the_supervisor(self):
        from aiohttp import ClientSession, web
        from aiohttp.test_utils import TestServer

        seen = {}

        async def logs(request):
            seen["path"] = request.path
            seen["auth"] = request.headers.get("Authorization")
            seen["accept"] = request.headers.get("Accept")
            return web.Response(text=LOG)

        app = web.Application()
        app.router.add_get("/addons/{slug}/logs", logs)
        server = TestServer(app)
        await server.start_server()
        old = healing.SUPERVISOR_API
        healing.SUPERVISOR_API = str(server.make_url("")).rstrip("/")
        try:
            async with ClientSession() as session:
                lines, where = await healing.read_logs(session, ADDON)
        finally:
            healing.SUPERVISOR_API = old
            await server.close()
        self.assertEqual(seen["path"], "/addons/core_mosquitto/logs")
        self.assertTrue(seen["auth"].startswith("Bearer"))
        self.assertEqual(seen["accept"], "text/plain")
        self.assertIn("[error] Out of memory: killed", lines)
        self.assertIn("Mosquitto", where)

    async def test_an_integrations_log_is_filtered_to_it(self):
        import ha_data
        old = ha_data._ws_commands

        async def ws(session, commands):
            assert commands == [{"type": "system_log/list"}]
            return [[
                {"name": "homeassistant.components.mqtt", "level": "ERROR",
                 "message": ["broker refused"], "source": ["mqtt/client.py"]},
                {"name": "homeassistant.components.hue", "level": "ERROR",
                 "message": ["bridge gone"], "source": ["hue/bridge.py"]},
            ]]

        ha_data._ws_commands = ws
        try:
            lines, where = await healing.read_logs(None, {
                "remedy": "entry.reload", "integration": "mqtt",
                "target": "e1", "label": "MQTT"})
        finally:
            ha_data._ws_commands = old
        self.assertEqual(lines, ["ERROR: homeassistant.components.mqtt: "
                                 "broker refused"])
        self.assertIn("mqtt", where)

    async def test_a_log_nobody_could_read_is_an_answer(self):
        import ha_data
        old = ha_data._ws_commands

        async def ws(session, commands):
            raise RuntimeError("socket closed")

        ha_data._ws_commands = ws
        try:
            lines, where = await healing.read_logs(None, {
                "remedy": "zwave.ping", "target": "sensor.node"})
        finally:
            ha_data._ws_commands = old
        self.assertEqual(lines, [])
        self.assertTrue(where.startswith("could not read"))


class TestTheHealPassFilesTheLogs(TestTheServerFilesTheChronicFinding):
    # Only the case this file adds; the parent's own run in their module.
    test_a_heal_records_how_many_this_is = None
    test_a_chronic_target_is_filed_and_not_called = None

    async def test_the_chronic_finding_carries_the_lines(self):
        old = healing.read_logs

        async def read(session, candidate):
            self.assertEqual(candidate["target"], "core_mosquitto")
            return ["[error] Out of memory: killed"], "the Mosquitto log"

        healing.read_logs = read
        try:
            self.seed(9, 5, 1)
            await self.server.run_healing("test")
        finally:
            healing.read_logs = old
        rows = json.loads(findings_store.FINDINGS_FILE.read_text())["findings"]
        filed = [r for r in rows if r.get("source") == healing.CHRONIC_SOURCE]
        self.assertEqual(len(filed), 1)
        self.assertIn("«[error] Out of memory: killed»", filed[0]["detail"])
        self.assertEqual(self.calls, [], "a chronic target is not healed")


if __name__ == "__main__":
    unittest.main()
