#!/usr/bin/env python3
"""What the MCP server's history and logbook tools put on the wire.

`get_history` asked Core's `/history/period/<start>` with no `end_time`, and
Core's default for a missing one is start plus ONE DAY — so a request for
three days came back as the day that ended two days ago, labelled as the
last three days, its `last`, `min` and `max` describing that old day. The
panel's `ha_data.history_params` learned this from the closures store; the
MCP copy never did, and its tests could not see it because they mocked the
request function and asserted on a substring of the endpoint — a fake that
accepts what it is handed cannot see a parameter that is not there.

So these stand up a real HTTP server, point the real `ha_api_request` at
it, and read the query string Core would have received. The logbook tool
had the mirror-image bug: it kept the FIRST fifty rows of a window Core
answers oldest first, which is the part of "what just happened" nobody
asked about.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402


class FakeCore:
    """A real socket answering the two REST paths, remembering what it got."""

    def __init__(self):
        self.requests = []
        self.history = [[]]
        self.logbook = []
        core = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 — http.server's name
                core.requests.append(self.path)
                if self.path.startswith("/api/history/period/"):
                    body = core.history
                elif self.path.startswith("/api/logbook/"):
                    body = core.logbook
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}/api"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def last(self):
        path, _, query = self.requests[-1].partition("?")
        return urllib.parse.unquote(path), urllib.parse.parse_qs(
            query, keep_blank_values=True)


class Case(unittest.TestCase):
    def setUp(self):
        self.core = FakeCore()
        self.addCleanup(self.core.close)
        for p in (patch.object(m, "HA_BASE_URL", self.core.base),
                  patch.object(m, "EXPOSED_ONLY", False)):
            p.start()
            self.addCleanup(p.stop)


def parse(stamp):
    return datetime.fromisoformat(stamp)


class TestHistoryRunsToNow(Case):
    def test_end_time_is_sent_and_is_now(self):
        before = datetime.now(timezone.utc)
        m.get_history("sensor.outdoor_temp", hours=72)
        after = datetime.now(timezone.utc)
        path, query = self.core.last()
        self.assertIn("end_time", query, "the bug: Core then answers start + 1 day")
        end = parse(query["end_time"][0])
        self.assertLessEqual(before - timedelta(seconds=1), end)
        self.assertLessEqual(end, after + timedelta(seconds=1))
        start = parse(path.rsplit("/", 1)[1])
        self.assertAlmostEqual((end - start).total_seconds(), 72 * 3600, delta=2)

    def test_the_flags_and_the_id_arrive_as_core_reads_them(self):
        m.get_history("sensor.outdoor_temp")
        _path, query = self.core.last()
        self.assertEqual(query["filter_entity_id"], ["sensor.outdoor_temp"])
        # Valueless in Core's API; an empty value reads as present.
        self.assertEqual(query["minimal_response"], [""])
        self.assertEqual(query["no_attributes"], [""])
        # A "+00:00" pasted into a query would arrive as a space.
        self.assertTrue(query["end_time"][0].endswith("+00:00"))

    def test_an_id_that_is_not_an_id_is_never_sent(self):
        for bad in ("sensor.x&end_time=2000-01-01", "sensor.x,lock.y",
                    "Sensor.X", "nonsense"):
            with self.subTest(bad=bad):
                got = m.get_history(bad)
                self.assertIn("not an entity id", got["error"])
        self.assertEqual(self.core.requests, [])

    def test_the_summary_is_read_off_what_came_back(self):
        self.core.history = [[
            {"state": "20.5", "last_changed": "2026-10-01T01:00:00+00:00"},
            {"state": "unavailable", "last_changed": "2026-10-02T03:00:00+00:00"},
            {"state": "23.1", "last_changed": "2026-10-03T09:00:00+00:00"},
        ]]
        got = m.get_history("sensor.outdoor_temp", hours=72)
        self.assertEqual(got["hours"], 72)
        self.assertEqual((got["min"], got["max"], got["last"]), (20.5, 23.1, "23.1"))


class TestTheLogbookIsTheNewest(Case):
    def rows(self, n):
        base = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)
        return [{
            "when": (base + timedelta(seconds=i)).isoformat(),
            "entity_id": "binary_sensor.hall_motion", "name": "Hall motion",
            "state": "on" if i % 2 else "off",
            "context_id": "01J9X" + str(i), "context_user_id": None,
            "context_event_type": "state_changed",
            "context_entity_id": "automation.hall" if i == n - 1 else None,
            "context_entity_id_name": "Hall lights" if i == n - 1 else None,
        } for i in range(n)]

    def test_a_busy_window_keeps_its_end_not_its_start(self):
        self.core.logbook = self.rows(120)
        got = m.get_logbook(hours=1)
        self.assertEqual((got["total"], got["returned"]), (120, 50))
        self.assertEqual(got["order"], "newest first")
        self.assertEqual(got["entries"][0]["when"], self.core.logbook[-1]["when"])
        self.assertEqual(got["entries"][-1]["when"], self.core.logbook[70]["when"])
        self.assertIn("70 oldest", got["note"])

    def test_rows_are_trimmed_to_what_a_reader_uses(self):
        self.core.logbook = self.rows(3)
        newest = m.get_logbook()["entries"][0]
        self.assertEqual(set(newest), {"when", "entity_id", "name", "state",
                                       "by", "by_name"})
        self.assertEqual((newest["by"], newest["by_name"]),
                         ("automation.hall", "Hall lights"))
        self.assertNotIn("context_id", m.get_logbook()["entries"][1])

    def test_the_window_and_the_entity_are_encoded_params(self):
        m.get_logbook(hours=2, entity_id="light.hall")
        path, query = self.core.last()
        self.assertEqual(query["entity"], ["light.hall"])
        start = parse(path.rsplit("/", 1)[1])
        end = parse(query["end_time"][0])
        self.assertAlmostEqual((end - start).total_seconds(), 7200, delta=2)

    def test_an_entity_that_is_not_an_id_is_refused_not_pasted(self):
        got = m.get_logbook(entity_id="light.hall&period=99")
        self.assertIn("not an entity id", got["error"])
        self.assertEqual(self.core.requests, [])


class TestStatisticsSaySoWhenTheyAreCut(unittest.TestCase):
    def test_a_long_hourly_window_is_cut_out_loud_and_rounded(self):
        rows = [{"start": 1_700_000_000_000 + i * 3_600_000,
                 "mean": 21.437916666666667 + i, "min": 0.000123456,
                 "max": 30.0, "sum": 12345.678912}
                for i in range(720)]
        with patch.object(m, "_ws_command", return_value={"sensor.t": rows}), \
                patch.object(m, "EXPOSED_ONLY", False):
            got = m.get_statistics("sensor.t", period="hour", days=30)
        self.assertEqual(len(got["stats"]), m.MAX_STAT_ROWS)
        self.assertIn("520 are not shown", got["note"])
        self.assertIn("'day'", got["note"])
        last = got["stats"][-1]
        self.assertEqual(last["mean"], round(21.437916666666667 + 719, 3))
        self.assertEqual(last["sum"], 12345.679)
        self.assertEqual(last["min"], 0.000123)

    def test_a_window_that_fits_has_no_note(self):
        with patch.object(m, "_ws_command", return_value={"sensor.t": [
                {"start": 1_700_000_000_000, "mean": 1.5}]}), \
                patch.object(m, "EXPOSED_ONLY", False):
            got = m.get_statistics("sensor.t", period="day", days=1)
        self.assertNotIn("note", got)
        self.assertEqual(got["stats"][0]["mean"], 1.5)


if __name__ == "__main__":
    unittest.main()
