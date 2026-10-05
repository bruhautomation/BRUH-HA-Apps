"""History that stops before the live state is a hole, not a quiet device.

A real house's recorder answered a thermostat's 24-hour window with 156
rows and its 48-hour window with ONE — the longer the window, the earlier
the data ended — and brAIn filed "silent since Oct 1", a 56-hour Ecobee
outage and "0 W all week" off the hole. The live state is the one reading
that says a window is missing its end, so every place history is fetched
compares the two (`ha_data.history_cutoffs`) and stands down for an
entity whose history stops well before its own last change.

The fetches are driven against a real aiohttp server answering in Core's
own `/history/period` shape, because what is being checked is what the
callers do with what comes back over the wire.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import closures  # noqa: E402
import ha_data  # noqa: E402
from checks import snapshot  # noqa: E402

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 4, 13, 55, tzinfo=UTC)


def iso(when: dt.datetime) -> str:
    return when.isoformat()


def ago(**kw) -> dt.datetime:
    return NOW - dt.timedelta(**kw)


# The thermostat as the walkthrough found it: history ends on Oct 1 at the
# restart, while the live state last changed at 11:11 today.
CUT = [
    {"entity_id": "climate.downstairs", "state": "heat_cool",
     "last_changed": iso(ago(days=3, hours=4, minutes=41))},
]
WHOLE = [
    {"entity_id": "sensor.hall_temp", "state": "21.0",
     "last_changed": iso(ago(days=4))},
    {"state": "21.5", "last_changed": iso(ago(hours=5))},
    {"state": "21.4", "last_changed": iso(ago(minutes=50))},
]
LIVE = {
    "climate.downstairs": {"entity_id": "climate.downstairs",
                           "state": "heat_cool", "attributes": {},
                           "last_changed": iso(ago(hours=2, minutes=43))},
    "sensor.hall_temp": {"entity_id": "sensor.hall_temp", "state": "21.4",
                         "attributes": {"unit_of_measurement": "°C"},
                         "last_changed": iso(ago(minutes=50))},
}


class TestTheRule(unittest.TestCase):

    def test_history_that_ends_days_before_the_live_change_is_cut(self):
        cut = ha_data.history_cutoffs(
            {"climate.downstairs": CUT, "sensor.hall_temp": WHOLE},
            LIVE, NOW)
        self.assertEqual(set(cut), {"climate.downstairs"})
        row = cut["climate.downstairs"]
        self.assertLess(row["history_ends"], row["live_changed"])

    def test_a_change_after_the_window_is_not_asked_about(self):
        # A window that ended three days ago never covered today's change.
        self.assertEqual(ha_data.history_cutoffs(
            {"climate.downstairs": CUT}, LIVE, ago(days=3).timestamp()), {})

    def test_an_entity_with_no_rows_is_not_judged(self):
        # A recorder `exclude` answers with nothing, on purpose.
        self.assertEqual(ha_data.history_cutoffs(
            {"climate.downstairs": []}, LIVE, NOW), {})

    def test_a_short_gap_is_the_recorder_committing_not_missing(self):
        rows = [{"entity_id": "sensor.hall_temp", "state": "21",
                 "last_changed": iso(ago(minutes=80))}]
        self.assertEqual(ha_data.history_cutoffs(
            {"sensor.hall_temp": rows}, LIVE, NOW), {})


class _Core(unittest.IsolatedAsyncioTestCase):
    """A Core whose `/history/period` answers the walkthrough's shape."""

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        async def history(request):
            ids = request.query.get("filter_entity_id", "").split(",")
            series = {"climate.downstairs": CUT, "sensor.hall_temp": WHOLE,
                      "binary_sensor.lev_door_open": self.door,
                      "binary_sensor.back_door": self.back_door}
            return web.json_response([series[i] for i in ids if i in series])

        self.door = [{"entity_id": "binary_sensor.lev_door_open",
                      "state": "off", "last_changed": iso(ago(days=3))}]
        self.back_door = [
            {"entity_id": "binary_sensor.back_door", "state": "off",
             "last_changed": iso(ago(days=27))},
            {"state": "on", "last_changed": iso(ago(hours=3))},
            {"state": "off", "last_changed": iso(ago(hours=2))},
        ]
        app = web.Application()
        app.router.add_get("/history/period/{stamp}", history)
        self.server = TestServer(app)
        self.client = TestClient(self.server)
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self._core = ha_data.CORE_API
        ha_data.CORE_API = str(self.server.make_url("")).rstrip("/")

    async def asyncTearDown(self):
        ha_data.CORE_API = self._core


class TestTheFetchesStandDown(_Core):

    async def test_get_history_leaves_out_a_series_with_its_end_missing(self):
        cut: dict = {}
        hist = await ha_data.get_history(
            self.client.session, ["climate.downstairs", "sensor.hall_temp"],
            ago(days=4), NOW, live=LIVE, cutoffs=cut)
        self.assertIn("sensor.hall_temp", hist)
        self.assertNotIn("climate.downstairs", hist)
        self.assertEqual(set(cut), {"climate.downstairs"})

        # Without the live states nothing is judged — the old behaviour,
        # which is what every caller that has no states still gets.
        hist = await ha_data.get_history(
            self.client.session, ["climate.downstairs"], ago(days=4), NOW)
        self.assertIn("climate.downstairs", hist)

    async def test_the_checks_snapshot_probe_finds_the_recorder_cut_short(self):
        states = {
            **LIVE,
            "binary_sensor.lev_door_open": {
                "state": "off", "attributes": {},
                "last_changed": iso(ago(hours=6))},
        }
        probe = await snapshot._history_probe(
            self.client.session, states, NOW.timestamp())
        self.assertEqual(probe["probed"], 3)
        self.assertEqual(set(probe["cut"]),
                         {"climate.downstairs", "binary_sensor.lev_door_open"})

    async def test_closures_do_not_measure_a_door_off_a_hole(self):
        states = {
            "binary_sensor.lev_door_open": {
                "state": "off", "attributes": {"device_class": "door"},
                "last_changed": iso(ago(hours=6))},
            "binary_sensor.back_door": {
                "state": "off", "attributes": {"device_class": "door"},
                "last_changed": iso(ago(hours=2))},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "closures.json")
            payload = await closures.build(
                self.client.session, states, NOW.timestamp(), path)
            self.assertEqual(payload.get("history_incomplete"),
                             ["binary_sensor.lev_door_open"])
            self.assertNotIn("binary_sensor.lev_door_open",
                             payload["entities"])
            self.assertIn("binary_sensor.back_door", payload["entities"])
            self.assertEqual(json.loads(Path(path).read_text())
                             ["history_incomplete"],
                             ["binary_sensor.lev_door_open"])


class TestWhichEntitiesAreProbed(unittest.TestCase):

    def test_recent_real_devices_only_newest_first_and_capped(self):
        now = NOW.timestamp()
        states = {
            "light.a": {"state": "on", "last_changed": iso(ago(hours=3))},
            "light.b": {"state": "on", "last_changed": iso(ago(hours=1))},
            # Too fresh: the recorder may not have committed it.
            "light.c": {"state": "on", "last_changed": iso(ago(minutes=5))},
            # Outside the window.
            "light.d": {"state": "on", "last_changed": iso(ago(days=9))},
            # Software, not a device.
            "automation.x": {"state": "on", "last_changed": iso(ago(hours=2))},
            "sensor.down": {"state": "unavailable",
                            "last_changed": iso(ago(hours=2))},
        }
        self.assertEqual(snapshot.probe_candidates(states, now),
                         ["light.b", "light.a"])
        self.assertEqual(snapshot.probe_candidates(states, now, cap=1),
                         ["light.b"])


if __name__ == "__main__":
    unittest.main()
