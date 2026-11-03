#!/usr/bin/env python3
"""`bruh_addon_status` says when an add-on's log could not be read.

Five BRUH add-ons on one house had no log the Supervisor would return, and
the chat's `bruh_addon_status` reported `log_errors: []` for each — which
reads as "no errors" (#657). The route now says what reading the log came
to (`log`: read, empty, or unreadable with the reason), and an unreadable
one has no error list at all rather than an empty one.
"""

import asyncio
import json
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))


def obs(slug, name, *, log="", log_error=""):
    return {"spec": {"name": name, "domain": slug, "key": slug, "dir": slug},
            "slug": slug, "info": {"version": "1.0", "state": "started"},
            "log": log, "log_error": log_error, "system_log": [], "outbox": []}


COLLECTED = {"error": "", "unread": [], "addons": [
    obs("a_print", "BRUH Print", log_error="could not read the log: HTTP Error 500"),
    obs("a_bright", "BRight", log=json.dumps(
        {"result": "error", "message": "Cannot determine the log's start"})),
    obs("a_garden", "GardenRX", log="2026-01-01 12:00:00 INFO started\n"),
    obs("a_tasks", "BRUH Task Manager", log=""),
]}


class TestTheRouteSaysSo(unittest.TestCase):
    def call(self):
        import server

        async def fake():
            return COLLECTED

        request = unittest.mock.Mock()
        request.query = {}
        with unittest.mock.patch.object(server, "_bruh_addons", fake):
            resp = asyncio.run(server.h_bruh_addons(request))
        return {r["addon"]: r for r in json.loads(resp.text)["addons"]}

    def test_an_unreadable_log_is_said_and_has_no_error_list(self):
        rows = self.call()
        for name in ("BRUH Print", "BRight"):
            with self.subTest(name):
                self.assertTrue(rows[name]["log"].startswith("unreadable"))
                self.assertIsNone(rows[name]["log_errors"])
        self.assertIn("Cannot determine", rows["BRight"]["log"])

    def test_a_read_log_and_an_empty_one_are_told_apart(self):
        rows = self.call()
        self.assertEqual(rows["GardenRX"]["log"], "read")
        self.assertEqual(rows["GardenRX"]["log_errors"], [])
        self.assertEqual(rows["BRUH Task Manager"]["log"], "empty")


if __name__ == "__main__":
    unittest.main()
