#!/usr/bin/env python3
"""A card's times are the house's wall clock, as its prompt says they are.

Every card prompt tells the model the times in its data are the home's
local time. Core answers history in UTC with an offset and statistics in
UTC epoch milliseconds, and the bundle sliced the offset off
(`last_changed[:19]`) or built UTC on purpose — so a door that opened at
18:42 in New York reached the card as 23:42, every "today" was a UTC day,
and nothing on screen could say why. Driven through the real
`get_history` and `get_statistics` with Core faked at the one call each
makes, in a house whose zone is not UTC.
"""
import asyncio
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))

import ha_data  # noqa: E402


class _InNewYork(unittest.TestCase):
    def setUp(self):
        saved = os.environ.get("TZ")

        def restore():
            if saved is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = saved
            time.tzset()

        self.addCleanup(restore)
        os.environ["TZ"] = "America/New_York"
        time.tzset()


class TestLocalIso(_InNewYork):
    def test_a_utc_stamp_becomes_the_house_clock(self):
        self.assertEqual(ha_data.local_iso("2026-01-15T23:42:10.123+00:00"),
                         "2026-01-15T18:42:10")
        self.assertEqual(ha_data.local_iso("2026-01-15T23:42:10Z", 13), "2026-01-15T18")

    def test_epoch_milliseconds_and_seconds(self):
        stamp = 1768520530  # 2026-01-15T23:42:10Z
        self.assertEqual(ha_data.local_iso(stamp * 1000, 16), "2026-01-15T18:42")
        self.assertEqual(ha_data.local_iso(stamp, 16), "2026-01-15T18:42")

    def test_what_it_cannot_read_is_kept_not_dropped(self):
        self.assertEqual(ha_data.local_iso("2026-01-15T23:42:10"), "2026-01-15T23:42:10")
        self.assertEqual(ha_data.local_iso("garbage-value-here", 7), "garbage")


class TestTheBundleIsLocal(_InNewYork):
    def test_history_changes_are_on_the_house_clock(self):
        raw = [[{"entity_id": "binary_sensor.back_door", "state": "on",
                 "last_changed": "2026-01-15T23:42:10.5+00:00"},
                {"entity_id": "binary_sensor.back_door", "state": "off",
                 "last_changed": "2026-01-16T00:05:00+00:00"}]]

        async def fake_get(*a, **kw):
            return raw

        with patch.object(ha_data, "_rest_get", fake_get):
            got = asyncio.run(ha_data.get_history(
                None, ["binary_sensor.back_door"],
                ha_data.dt.datetime(2026, 1, 15, tzinfo=ha_data.dt.timezone.utc)))
        self.assertEqual(got["binary_sensor.back_door"],
                         [["2026-01-15T18:42:10", "on"], ["2026-01-15T19:05:00", "off"]])

    def test_hourly_buckets_are_local_hours(self):
        raw = [[{"entity_id": "sensor.freezer", "state": str(v),
                 "last_changed": f"2026-01-16T0{h}:10:00+00:00"}
                for h, v in ((1, -18), (1, -17), (2, -16), (3, -15))]]

        async def fake_get(*a, **kw):
            return raw

        with patch.object(ha_data, "_rest_get", fake_get):
            got = asyncio.run(ha_data.get_history(
                None, ["sensor.freezer"],
                ha_data.dt.datetime(2026, 1, 15, tzinfo=ha_data.dt.timezone.utc)))
        self.assertEqual([row[0] for row in got["sensor.freezer"]],
                         ["2026-01-15T20", "2026-01-15T21", "2026-01-15T22"])

    def test_statistics_rows_are_local_hours(self):
        start = 1768521600000  # 2026-01-16T00:00Z

        async def fake_ws(session, commands):
            return [{"sensor.energy": [
                {"start": start, "sum": 10.0},
                {"start": start + 3_600_000, "sum": 11.5}]}]

        with patch.object(ha_data, "_ws_commands", fake_ws):
            got = asyncio.run(ha_data.get_statistics(
                None, ["sensor.energy"],
                ha_data.dt.datetime(2026, 1, 15, tzinfo=ha_data.dt.timezone.utc)))
        self.assertEqual(got["sensor.energy"], [["2026-01-15T20", 1.5]])


if __name__ == "__main__":
    unittest.main()
