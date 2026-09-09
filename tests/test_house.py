#!/usr/bin/env python3
"""What brAIn has measured, and what it is still waiting for.

Every measurement in this add-on has a floor under it, and every floor
makes a fresh install *silent* — which is indistinguishable from broken
from outside. `progress()` is what each store says about itself, and this
drives all seven through the five states they can be in, then through the
aggregate route and its drill-downs, because a payload nothing has fetched
over a real router is a payload the panel cannot build against.

The states are asserted per store rather than described once, since the
whole point is that "I could not look", "there is nothing here to measure"
and "this has not happened enough times yet" are different answers and
only the third is something waiting.
"""

import asyncio
import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import appliances  # noqa: E402
import baselines  # noqa: E402
import closures  # noqa: E402
import energy  # noqa: E402
import house  # noqa: E402
import override_ledger  # noqa: E402
import rhythm  # noqa: E402
import routines  # noqa: E402
import schedule_store  # noqa: E402
import thermal  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0


# ---------------------------------------------------------------------------
# Fixtures: a house at each stage of being measured
# ---------------------------------------------------------------------------

def rhythm_days(n: int, weekday: bool = True, first: int = 410) -> dict:
    """`n` days of person-caused activity, all of one kind of day."""
    days = {}
    made = 0
    day = dt.date(2024, 1, 1)
    while made < n:
        if (day.weekday() < 5) == weekday:
            days[day.isoformat()] = {
                # A few minutes of scatter, well inside MAX_SPREAD_MIN.
                "first": first + (made % 5) * 3,
                "last": 1360 + (made % 4) * 4,
                "dow": day.weekday(), "n": 3}
            made += 1
        day += dt.timedelta(days=1)
    return {"days": days, "updated_at": int(NOW)}


def baseline_entity(buckets: int = 4) -> dict:
    return {"buckets": {str(h): {"median": 20.0, "spread": 0.5, "n": 5}
                        for h in range(buckets)},
            "overall": {"median": 20.0, "spread": 0.5, "n": 40},
            "unit": "°C", "samples": 40}


def closure_entity(buckets: int) -> dict:
    return {"buckets": {str(h): {"open": 0.02, "hours": 4.0}
                        for h in range(buckets)},
            "overall": 0.02, "changes": 60, "name": "Back door"}


APPLIANCE = {"idle_w": 1.0, "busy_w": 900.0, "threshold_w": 220.0,
             "settle_min": 22.0, "draws": 9, "typical_run_min": 95.0,
             "name": "Dishwasher power"}

ROOM = {"k": 0.11, "tau_h": 9.1, "gain": 2.8, "unit": "°C",
        "warmest": 21.5, "coolest": 15.2, "hours": 400,
        "name": "Bedroom", "area": "Bedroom"}


def routine_rows(days: int) -> dict:
    rows = []
    for i in range(days):
        rows.append({"ts": NOW - i * DAY, "entity_id": "light.porch",
                     "state": "on", "name": "Porch"})
    return {"rows": rows, "automated": {}}


ENERGY_WEEK = {
    "available": True, "reason": "",
    "from": int(NOW - 7 * DAY), "to": int(NOW),
    "energy": {"this": 84.2, "last": 78.0, "days": 7, "days_before": 7,
               "change_pct": 7.9, "comparable": True, "unit": "kWh"},
}


# ---------------------------------------------------------------------------
# Every store answers the same five questions about itself
# ---------------------------------------------------------------------------

class TestEveryStoreReportsItsOwnProgress(unittest.TestCase):
    """The shape is one shape, and the floors are each store's own."""

    def assert_shape(self, p: dict, unit: str, need: int):
        for key in ("state", "have", "need", "unit", "reason", "ready_at",
                    "summary", "updated_at", "detail"):
            self.assertIn(key, p)
        self.assertIn(p["state"], house.STATES)
        self.assertEqual(p["unit"], unit)
        # The floor is the store's own constant, never a number restated
        # in the panel — that is what this asserts by comparing against it.
        self.assertEqual(p["need"], need)
        self.assertIsInstance(p["detail"], dict)

    def test_a_house_nobody_has_measured_says_so_without_promising_nothing(self):
        empty = {
            "rhythm": (rhythm.progress({"days": {}}, now=NOW), "days",
                       rhythm.MIN_DAYS),
            "baselines": (baselines.progress({}, now=NOW), "entities", 1),
            "thermal": (thermal.progress({}, now=NOW), "rooms", 1),
            "closures": (closures.progress({}, now=NOW), "hours",
                         closures.MIN_BUCKETS),
            "appliances": (appliances.progress({}, now=NOW), "machines", 1),
            "habits": (routines.progress({"rows": []}, now=NOW), "days",
                       routines.MIN_DAYS),
            "energy": (energy.progress(None, now=NOW), "days",
                       energy.MIN_DAYS),
        }
        for name, (p, unit, need) in empty.items():
            with self.subTest(name):
                self.assert_shape(p, unit, need)
                self.assertEqual(p["state"], house.NOT_STARTED, name)
                self.assertEqual(p["have"], 0)
                self.assertTrue(p["summary"], "a state with no sentence")

    def test_a_measurement_in_progress_says_how_far_and_when(self):
        partial = [
            ("rhythm", rhythm.progress(rhythm_days(4), now=NOW), 4),
            ("closures", closures.progress(
                {"built_at": int(NOW), "asked": 3, "entities": {}},
                now=NOW), 0),
            ("habits", routines.progress(routine_rows(3), now=NOW), 3),
            ("energy", energy.progress(
                {**ENERGY_WEEK, "energy": {**ENERGY_WEEK["energy"], "days": 3,
                                           "change_pct": None,
                                           "comparable": False}},
                now=NOW), 3),
        ]
        for name, p, have in partial:
            with self.subTest(name):
                self.assertEqual(p["state"], house.COLLECTING, p["summary"])
                self.assertEqual(p["have"], have)
                self.assertIsNotNone(p["ready_at"], "no date to wait for")
                self.assertGreater(p["ready_at"], NOW,
                                   "a date already past is not a wait")
                self.assertIn(str(p["need"]), p["summary"])

    def test_a_measured_house_names_its_numbers(self):
        ready = [
            ("rhythm", rhythm.progress(rhythm_days(12), now=NOW)),
            ("baselines", baselines.progress(
                {"built_at": int(NOW), "entities": {
                    "sensor.a": baseline_entity(),
                    "sensor.b": {"flat": True, "value": 3.0, "samples": 30}}},
                now=NOW)),
            ("thermal", thermal.progress(
                {"built_at": int(NOW), "outdoor": "sensor.out", "unit": "°C",
                 "asked": 2, "coldest": 1.5, "rooms": {"sensor.bed": ROOM}},
                now=NOW)),
            ("closures", closures.progress(
                {"built_at": int(NOW), "asked": 2,
                 "entities": {"binary_sensor.back": closure_entity(30)}},
                now=NOW)),
            ("appliances", appliances.progress(
                {"built_at": int(NOW), "asked": 4,
                 "entities": {"sensor.dw": APPLIANCE}}, now=NOW)),
            ("habits", routines.progress(routine_rows(9), now=NOW)),
            ("energy", energy.progress(ENERGY_WEEK, now=NOW)),
        ]
        for name, p in ready:
            with self.subTest(name):
                self.assertEqual(p["state"], house.READY, p["summary"])
                self.assertGreaterEqual(p["have"], p["need"])
                # Ready is not waiting for anything.
                self.assertIsNone(p["ready_at"])
                self.assertTrue(any(ch.isdigit() for ch in p["summary"]),
                                f"a ready summary with no number: {p['summary']}")

    def test_a_refused_build_is_unavailable_carrying_the_stores_own_reason(self):
        # `baselines.refused` hands back the previous store with `error`
        # beside it — the pass did not measure nothing, it could not look.
        refusals = [
            ("baselines", baselines.progress, "the recorder did not answer"),
            ("thermal", thermal.progress, "the recorder said nothing"),
            ("closures", closures.progress, "no closure batch answered"),
            ("appliances", appliances.progress, "the recorder refused"),
        ]
        for name, fn, reason in refusals:
            with self.subTest(name):
                p = fn({"built_at": int(NOW), "asked": 2, "error": reason},
                       now=NOW)
                self.assertEqual(p["state"], house.UNAVAILABLE)
                self.assertEqual(p["reason"], reason)
                self.assertIn(reason, p["summary"])
                self.assertIsNone(p["ready_at"],
                                  "a refusal is not a wait with a date")

    def test_a_measurement_that_has_stopped_reads_stale_not_ready(self):
        old = NOW - (baselines.STALE_DAYS + 2) * DAY
        stale = [
            ("rhythm", rhythm.progress(
                {**rhythm_days(12), "updated_at": int(old)}, now=NOW)),
            ("baselines", baselines.progress(
                {"built_at": int(old), "entities": {"sensor.a": baseline_entity()}},
                now=NOW)),
            ("thermal", thermal.progress(
                {"built_at": int(old), "outdoor": "sensor.out", "asked": 1,
                 "rooms": {"sensor.bed": ROOM}}, now=NOW)),
            ("closures", closures.progress(
                {"built_at": int(old), "asked": 1,
                 "entities": {"binary_sensor.back": closure_entity(30)}},
                now=NOW)),
            ("appliances", appliances.progress(
                {"built_at": int(old), "asked": 1,
                 "entities": {"sensor.dw": APPLIANCE}}, now=NOW)),
            ("habits", routines.progress(
                {"rows": [{"ts": old, "entity_id": "light.a", "state": "on"}],
                 "automated": {}}, now=NOW)),
        ]
        for name, p in stale:
            with self.subTest(name):
                self.assertEqual(p["state"], house.STALE, p["summary"])
                self.assertTrue(p["reason"])

    def test_a_house_that_cannot_supply_one_is_unavailable_and_not_collecting(self):
        # No outdoor thermometer: every thermal number is a difference from
        # outside, so this can never be measured however long it waits.
        p = thermal.progress({"built_at": int(NOW), "outdoor": "", "rooms": {},
                              "reason": "no outdoor temperature sensor"},
                             now=NOW)
        self.assertEqual(p["state"], house.UNAVAILABLE)
        self.assertIn("outdoor", p["summary"].lower())
        self.assertIsNone(p["ready_at"])

        # And the same shape for a house with no doors and no power sensors.
        for fn in (closures.progress, appliances.progress):
            with self.subTest(fn.__module__):
                q = fn({"built_at": int(NOW), "asked": 0, "entities": {}},
                       now=NOW)
                self.assertEqual(q["state"], house.UNAVAILABLE)
                self.assertIsNone(q["ready_at"])

        # An energy answer HA itself refuses carries HA's own sentence.
        e = energy.progress({"available": False,
                             "reason": "no energy configuration in Home Assistant"},
                            now=NOW)
        self.assertEqual(e["state"], house.UNAVAILABLE)
        self.assertIn("no energy configuration", e["reason"])

    def test_a_wake_time_over_scattered_days_is_refused_rather_than_averaged(self):
        # Ten weekdays that stir anywhere across the morning have no usual
        # time, and more days cannot fix it — so it is not `collecting`.
        days = rhythm_days(12)
        for i, row in enumerate(days["days"].values()):
            row["first"] = 300 + i * 45
        p = rhythm.progress(days, now=NOW)
        self.assertEqual(p["state"], house.UNAVAILABLE)
        self.assertIn(str(int(rhythm.MAX_SPREAD_MIN)), p["reason"])

    def test_the_rhythm_sentence_says_which_half_is_still_short(self):
        p = rhythm.progress(rhythm_days(12), now=NOW)
        self.assertEqual(p["state"], house.READY)
        self.assertIn("weekend", p["summary"].lower())
        self.assertEqual(p["detail"]["weekend_days"], 0)

    def test_the_baseline_count_is_entities_with_a_bucket_not_entities_read(self):
        # A sensor whose month held three readings is measured and answers
        # nothing; counting it would report a house as ready for a question
        # none of its baselines can take.
        p = baselines.progress(
            {"built_at": int(NOW),
             "entities": {"sensor.flat": {"flat": True, "value": 1.0},
                          "sensor.real": baseline_entity()}}, now=NOW)
        self.assertEqual(p["detail"]["measured"], 2)
        self.assertEqual(p["detail"]["with_buckets"], 1)
        self.assertEqual(p["detail"]["flat"], 1)
        self.assertEqual(p["have"], 1)

    def test_a_profiled_machine_that_is_not_a_chore_says_so(self):
        p = appliances.progress(
            {"built_at": int(NOW), "asked": 2,
             "entities": {"sensor.tv": {**APPLIANCE, "name": "Television"}}},
            now=NOW)
        self.assertEqual(p["state"], house.READY)
        self.assertEqual(p["detail"]["chore_capable"], 0)
        self.assertIn("washer", p["summary"])


class TestTheArithmeticThatSaysWhen(unittest.TestCase):
    def test_nothing_left_to_gather_has_no_date(self):
        self.assertIsNone(house.eta(5, 5, 86400.0, NOW))
        self.assertIsNone(house.eta(9, 5, 86400.0, NOW))

    def test_a_unit_that_does_not_accrue_has_no_date(self):
        self.assertIsNone(house.eta(0, 5, 0.0, NOW))

    def test_the_rate_is_the_stores_own(self):
        # A weekday arrives five times in seven, so ten of them is a
        # fortnight and not ten days.
        when = house.eta(0, rhythm.MIN_DAYS, rhythm.PROGRESS_UNIT_S, NOW)
        self.assertAlmostEqual((when - NOW) / DAY, 14.0, places=1)


# ---------------------------------------------------------------------------
# The aggregate and its drill-downs, over the real router
# ---------------------------------------------------------------------------

class HouseServerCase(unittest.TestCase):
    """The panel with every measurement store pointed at a temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        cls.engine = importlib.import_module("engine")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = {}
        for mod, attr, name in (
            (rhythm, "STORE", "rhythm.json"),
            (baselines, "STORE", "baselines.json"),
            (thermal, "STORE", "thermal.json"),
            (closures, "STORE", "closures.json"),
            (appliances, "STORE", "appliances.json"),
            (routines, "STORE", "routines.json"),
            (override_ledger, "STORE", "overrides.json"),
            (schedule_store, "STORE", "schedule.json"),
        ):
            self._olds[(mod, attr)] = getattr(mod, attr)
            setattr(mod, attr, str(tmp / name))
        self._old_auth = self.engine.get_auth
        # No credential: `h_status` must not spawn a real auth check while
        # a test is reading the numbers beside it.
        self.engine.get_auth = lambda: None
        self._old_week = energy.week

        async def no_meters(session, now=None, tz=None):
            return {"available": False,
                    "reason": "no energy configuration in Home Assistant"}

        energy.week = no_meters
        house.forget_energy()
        self.server._TODAY_CACHE.update(at=0.0, state=None)

    def tearDown(self):
        for (mod, attr), value in self._olds.items():
            setattr(mod, attr, value)
        self.engine.get_auth = self._old_auth
        energy.week = self._old_week
        house.forget_energy()
        self.server._TODAY_CACHE.update(at=0.0, state=None)
        self.tmp.cleanup()

    def write(self, mod, payload):
        Path(getattr(mod, "STORE")).write_text(json.dumps(payload))

    def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        return TestClient(TestServer(self.server.make_app()))

    def run_client(self, body):
        async def go():
            client = self._client()
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()
        return asyncio.run(go())


class TestTheAggregate(HouseServerCase):
    def test_a_fresh_install_answers_for_all_seven_and_says_it_is_waiting(self):
        async def body(client):
            resp = await client.get("/api/knowledge/house")
            self.assertEqual(resp.status, 200)
            return await resp.json()

        data = self.run_client(body)
        self.assertEqual(sorted(data["stores"]), sorted(house.STORES))
        self.assertGreater(data["generated_at"], 0)
        for name, row in data["stores"].items():
            with self.subTest(name):
                self.assertIn(row["state"],
                              (house.NOT_STARTED, house.UNAVAILABLE))
                self.assertTrue(row["summary"])
        # The two scheduled messages ride in the same payload.
        for key in ("enabled", "last_sent", "text", "reasons", "error",
                    "fallback_hour", "wake_measured"):
            self.assertIn(key, data["brief"])
        for key in ("enabled", "last_sent", "text", "error", "day"):
            self.assertIn(key, data["weekly"])

    def test_a_measured_house_reads_ready_through_the_route(self):
        self.write(rhythm, rhythm_days(12))
        self.write(baselines, {"built_at": int(time.time()),
                               "entities": {"sensor.a": baseline_entity()}})
        self.write(appliances, {"built_at": int(time.time()), "asked": 2,
                                "entities": {"sensor.dw": APPLIANCE}})

        async def body(client):
            return await (await client.get("/api/knowledge/house")).json()

        stores = self.run_client(body)["stores"]
        self.assertEqual(stores["rhythm"]["state"], house.READY)
        self.assertEqual(stores["baselines"]["state"], house.READY)
        self.assertEqual(stores["appliances"]["state"], house.READY)
        # And the one measurement with no store carries HA's own refusal.
        self.assertEqual(stores["energy"]["state"], house.UNAVAILABLE)
        self.assertIn("energy configuration", stores["energy"]["reason"])

    def test_the_last_brief_survives_a_restart(self):
        # A brief goes to a phone and is gone; the panel is the only place
        # it could be re-read, so it is kept beside the stamp.
        schedule_store.set_text(self.server.BRIEF_TEXT_KEY, "Two things: ...")
        self.server.BRIEF_STATE["last_text"] = schedule_store.get_text(
            self.server.BRIEF_TEXT_KEY)

        async def body(client):
            return await (await client.get("/api/knowledge/house")).json()

        self.assertEqual(self.run_client(body)["brief"]["text"],
                         "Two things: ...")

    def test_a_store_that_raises_costs_its_own_row_and_not_the_payload(self):
        def boom(*a, **k):
            raise RuntimeError("the store is unreadable")

        old = thermal.progress
        thermal.progress = boom
        try:
            async def body(client):
                resp = await client.get("/api/knowledge/house")
                self.assertEqual(resp.status, 200)
                return await resp.json()

            data = self.run_client(body)
        finally:
            thermal.progress = old
        self.assertEqual(data["stores"]["thermal"]["state"], house.UNAVAILABLE)
        self.assertIn("unreadable", data["stores"]["thermal"]["reason"])
        self.assertEqual(data["stores"]["rhythm"]["state"], house.NOT_STARTED)


class TestTheDrillDowns(HouseServerCase):
    def test_every_named_measurement_answers_and_nothing_else_does(self):
        self.write(rhythm, rhythm_days(12))
        self.write(baselines, {"built_at": int(time.time()),
                               "entities": {"sensor.a": baseline_entity()}})
        self.write(thermal, {"built_at": int(time.time()), "outdoor": "sensor.out",
                             "unit": "°C", "coldest": 1.0, "asked": 1,
                             "rooms": {"sensor.bed": ROOM}})
        self.write(closures, {"built_at": int(time.time()), "asked": 1,
                              "entities": {"binary_sensor.back": closure_entity(30)}})
        self.write(appliances, {"built_at": int(time.time()), "asked": 1,
                                "entities": {"sensor.dw": APPLIANCE}})
        self.write(routines, routine_rows(9))

        async def body(client):
            out = {}
            for name in house.STORES:
                resp = await client.get(f"/api/knowledge/house/{name}")
                self.assertEqual(resp.status, 200, name)
                out[name] = await resp.json()
            missing = await client.get("/api/knowledge/house/weather")
            self.assertEqual(missing.status, 404)
            return out

        got = self.run_client(body)

        self.assertEqual(got["rhythm"]["weekday"]["wakes"]["at"][:2], "06")
        self.assertIsNone(got["rhythm"]["weekend"]["wakes"])

        row = got["baselines"][0]
        self.assertEqual(row["entity_id"], "sensor.a")
        self.assertEqual(row["unit"], "°C")
        self.assertFalse(row["flat"])
        self.assertEqual(row["buckets_n"], 4)
        self.assertIsNone(row["trend"])

        self.assertEqual(got["thermal"]["outdoor"], "sensor.out")
        room = got["thermal"]["rooms"][0]
        self.assertEqual(room["id"], "sensor.bed")
        self.assertEqual(room["area"], "Bedroom")
        self.assertAlmostEqual(room["tau_h"], 9.1)
        # Its own coolest to its own warmest, on the coldest night
        # measured — which is `None` for a room that cannot get there at
        # that outdoor temperature, and a number for one that can.
        self.assertIsInstance(room["hours_to_warm"], float)
        self.assertGreater(room["hours_to_warm"], 0.0)

        door = got["closures"][0]
        self.assertEqual(door["entity_id"], "binary_sensor.back")
        self.assertEqual(len(door["buckets"]), 30)
        self.assertAlmostEqual(door["overall"], 0.02)

        machine = got["appliances"]["appliances"][0]
        self.assertEqual(machine["entity_id"], "sensor.dw")
        self.assertEqual(machine["chore_kind"], "dishwasher")
        self.assertIn("now", machine)

        self.assertEqual(got["habits"]["routines"]["presses"], 9)
        self.assertIn("overrides", got["habits"])
        self.assertIn("patterns", got["habits"])

        self.assertFalse(got["energy"]["available"])

    def test_the_appliance_drill_down_says_what_each_machine_is_doing_now(self):
        self.write(appliances, {"built_at": int(time.time()), "asked": 1,
                                "entities": {"sensor.dw": APPLIANCE}})
        now = time.time()
        # A run that ended well past this machine's own measured settle.
        points = []
        for i in range(240):
            when = now - (240 - i) * 300
            watts = 900.0 if 40 <= i <= 60 else 1.0
            points.append({"start": when, "mean": watts})

        async def fetch(session, ids, start, end=None):
            return {"sensor.dw": points}

        old = appliances.fetch
        appliances.fetch = fetch
        try:
            async def body(client):
                return await (await client.get(
                    "/api/knowledge/house/appliances")).json()

            data = self.run_client(body)
        finally:
            appliances.fetch = old
        self.assertEqual(data["appliances"][0]["now"]["state"],
                         appliances.FINISHED)
        self.assertEqual(data["live_error"], "")

    def test_a_recorder_that_refused_is_reported_and_not_read_as_idle(self):
        self.write(appliances, {"built_at": int(time.time()), "asked": 1,
                                "entities": {"sensor.dw": APPLIANCE}})

        async def refuse(session, ids, start, end=None):
            return None

        old = appliances.fetch
        appliances.fetch = refuse
        try:
            async def body(client):
                return await (await client.get(
                    "/api/knowledge/house/appliances")).json()

            data = self.run_client(body)
        finally:
            appliances.fetch = old
        self.assertTrue(data["live_error"])
        self.assertEqual(data["appliances"][0]["now"], {})


class TestWhatBrainDidTodayRidesOnTheStatusPoll(HouseServerCase):
    def test_the_numbers_come_from_the_state_that_already_exists(self):
        finished = int(time.time()) - 3600
        built = int(time.time()) - 7200
        self.write(baselines, {"built_at": built, "entities": {}})
        old_checks = dict(self.server.CHECKS_STATE)
        old_base = dict(self.server.BASELINE_STATE)
        self.server.CHECKS_STATE["last"] = {
            "finished_at": finished, "ran": ["a", "b", "c"],
            "skipped": {"sys.addon_down": "the Supervisor did not answer"},
            "errors": {}, "created": [{"ts": 1}], "cleared": ["x", "y"],
        }
        self.server.CHECKS_STATE["running"] = False
        self.server.BASELINE_STATE["last"] = {"error": ""}
        self.server.BASELINE_STATE["running"] = False
        try:
            async def body(client):
                resp = await client.get("/api/status")
                self.assertEqual(resp.status, 200)
                return await resp.json()

            today = self.run_client(body)["today"]
        finally:
            self.server.CHECKS_STATE.clear()
            self.server.CHECKS_STATE.update(old_checks)
            self.server.BASELINE_STATE.clear()
            self.server.BASELINE_STATE.update(old_base)

        self.assertEqual(today["checks"]["last_at"], finished)
        self.assertEqual(today["checks"]["ran"], 3)
        # "I could not look" is counted apart from "it found nothing".
        self.assertEqual(today["checks"]["skipped"], 1)
        self.assertEqual(today["checks"]["errored"], 0)
        self.assertEqual(today["checks"]["created"], 1)
        self.assertEqual(today["checks"]["cleared"], 2)
        self.assertFalse(today["checks"]["running"])
        self.assertEqual(today["baselines"]["built_at"], built)
        self.assertEqual(today["baselines"]["next_at"],
                         built + self.server.BASELINE_INTERVAL_S)
        for key in ("last_filed_at", "waiting", "running"):
            self.assertIn(key, today["memory"])
        self.assertIn("since_yesterday", today["reports"])
        self.assertIn("landed_runs_24h", today)

    def test_a_pass_that_has_never_run_promises_no_next_time(self):
        old_checks = dict(self.server.CHECKS_STATE)
        self.server.CHECKS_STATE["last"] = None
        try:
            async def body(client):
                return await (await client.get("/api/status")).json()

            today = self.run_client(body)["today"]
        finally:
            self.server.CHECKS_STATE.clear()
            self.server.CHECKS_STATE.update(old_checks)
        self.assertIsNone(today["checks"]["last_at"])
        self.assertIsNone(today["checks"]["next_at"])
        self.assertIsNone(today["baselines"]["built_at"])


class TestTheRoutesThatWent(HouseServerCase):
    def test_the_dead_ones_are_gone_and_unsettle_is_not(self):
        async def body(client):
            for method, path in (
                ("post", "/api/generate_all"),
                ("post", "/api/replay"),
                ("post", "/api/knowledge/question/123/answer"),
                ("post", "/api/knowledge/question/123/dismiss"),
                ("delete", "/api/knowledge/question/123"),
            ):
                resp = await getattr(client, method)(path, json={})
                self.assertEqual(resp.status, 404, f"{method} {path}")
            # The one that stays: a person pressing "let brAIn raise it
            # again" is the only thing that clears a settled key. Asked
            # with no key, so what is proved is the handler running — a
            # 404 here would be the route, and one for a key nothing has
            # settled is the handler doing its job.
            kept = await client.post("/api/findings/unsettle", json={})
            self.assertEqual(kept.status, 400)
            # And the knowledge payload no longer carries a question ledger.
            data = await (await client.get("/api/knowledge")).json()
            self.assertNotIn("questions", data)

        self.run_client(body)


# ---------------------------------------------------------------------------
# The MCP tool, over a real loopback panel
# ---------------------------------------------------------------------------

class _StubPanel(BaseHTTPRequestHandler):
    payload: dict = {}
    seen: list = []

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's name
        type(self).seen.append(self.path)
        body = json.dumps(type(self).payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep the test output readable
        pass


class TestTheModelCanAskWhatHasBeenMeasured(unittest.TestCase):
    """`get_house_model` reads the panel over loopback rather than
    re-implementing seven measurements — `get_activity`'s own reasoning."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
        cls.mcp = importlib.import_module("ha_mcp_server")

    def setUp(self):
        _StubPanel.seen = []
        _StubPanel.payload = {
            "generated_at": int(NOW),
            "stores": {name: {"state": house.COLLECTING, "have": 2, "need": 6,
                              "unit": "days", "summary": f"{name} is coming",
                              "reason": "", "updated_at": int(NOW),
                              "detail": {"a huge": "payload"}}
                       for name in house.STORES},
            "brief": {"enabled": False},
            "weekly": {"enabled": False},
        }
        self.httpd = HTTPServer(("127.0.0.1", 0), _StubPanel)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self._old_url = self.mcp.PANEL_URL
        self.mcp.PANEL_URL = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.mcp.PANEL_URL = self._old_url
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_the_dispatcher_answers_with_every_store_and_no_detail(self):
        out = self.mcp.handle_tool_call("get_house_model", {})
        self.assertEqual(_StubPanel.seen, ["/api/knowledge/house"])
        self.assertEqual(sorted(out["stores"]), sorted(house.STORES))
        row = out["stores"]["rhythm"]
        self.assertEqual(row["state"], house.COLLECTING)
        self.assertEqual(row["summary"], "rhythm is coming")
        # The whole detail of every store is the drill-down's job and
        # would be most of a house in one tool result.
        self.assertNotIn("detail", row)

    def test_a_panel_that_is_not_up_is_reported_as_such(self):
        self.mcp.PANEL_URL = "http://127.0.0.1:1"
        out = self.mcp.handle_tool_call("get_house_model", {})
        self.assertIn("error", out)
        self.assertIn("panel", out["error"])

    def test_the_tool_is_registered_once_and_is_read_only(self):
        names = [t["name"] for t in self.mcp.TOOLS]
        self.assertEqual(names.count("get_house_model"), 1)
        self.assertIn("get_house_model", self.mcp.TOOL_IMPLEMENTATIONS)
        import engine
        self.assertIn(f"{engine.MCP}get_house_model", engine.ANALYST_TOOLS)
        self.assertNotIn(f"{engine.MCP}get_house_model", engine.ANALYST_DENIED)


class TestTheScheduleStoreKeepsWhatWasSaid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "schedule.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_message_survives_beside_its_stamp(self):
        schedule_store.set("brief_last_sent", NOW, self.path)
        schedule_store.set_text("brief_last_text", "Boiler is quiet.", self.path)
        self.assertEqual(schedule_store.get("brief_last_sent", self.path), NOW)
        self.assertEqual(schedule_store.get_text("brief_last_text", self.path),
                         "Boiler is quiet.")

    def test_never_sent_is_how_every_failure_reads(self):
        self.assertEqual(schedule_store.get_text("brief_last_text", self.path), "")
        # A stamp read as text, and text read as a stamp, are both "never"
        # rather than a crash — the store has no schema on purpose.
        schedule_store.set("weekly_last_sent", NOW, self.path)
        self.assertEqual(schedule_store.get_text("weekly_last_sent", self.path), "")
        schedule_store.set_text("weekly_last_text", "x", self.path)
        self.assertEqual(schedule_store.get("weekly_last_text", self.path), 0.0)

    def test_a_message_is_capped_rather_than_archived(self):
        schedule_store.set_text("brief_last_text", "y" * 99_000, self.path)
        self.assertEqual(len(schedule_store.get_text("brief_last_text", self.path)),
                         schedule_store.TEXT_MAX)


if __name__ == "__main__":
    unittest.main()
