"""The baseline cap is spent on sensors something can measure and read.

`baselines.candidates` took every entity carrying any `state_class`,
sorted the ids and kept the first 400 — BEFORE any test of whether a
baseline could be built for it or read off it. A `total_increasing`
meter has no `mean` statistic, so it comes back with nothing to bucket;
a diagnostic or config sensor is one every reader skips. On a big house
those rows took the slots alphabetically, so `sensor.upstairs_*` and
`sensor.water_*` were never asked about, `base.unusual`,
`forecast.decline` and the preheat check were blind to them, and nothing
anywhere said so.

The same pass carried two smaller faults, fixed here too: the
whole-history fallback said "from 650 weeks of readings" (its count is
hourly readings, not weeks), and the floor under a reported move was half
a unit whatever the unit — 0.5 W and 0.5 lx as readily as half a degree.

Each case drives the real `select`, `build`, `progress`, the checks and
the nightly pass, and the first states the old rule's answer on the same
house before asserting the new one.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import baselines  # noqa: E402
import test_baselines  # noqa: E402  — the nightly pass's own harness

NOW = 1_756_800_000.0


def sensor(state_class: str, value: str = "1") -> dict:
    return {"state": value, "attributes": {"state_class": state_class}}


def the_old_rule(states: dict) -> list[str]:
    """`candidates` as it shipped: any state class, sorted, capped."""
    return sorted(eid for eid, st in states.items()
                  if (st.get("attributes") or {}).get("state_class")
                  and st.get("state") not in ("unavailable", "unknown", None)
                  )[:baselines.MAX_ENTITIES]


def big_house() -> tuple[dict, list[dict]]:
    """Four hundred energy meters and thirty signal strengths that sort
    ahead of the two sensors anybody would want a baseline for."""
    states, registry = {}, []
    for i in range(baselines.MAX_ENTITIES):
        states[f"sensor.a_meter_{i:03d}_energy"] = sensor("total_increasing")
    for i in range(30):
        eid = f"sensor.b_plug_{i:02d}_signal"
        states[eid] = sensor("measurement", "-60")
        registry.append({"entity_id": eid, "entity_category": "diagnostic"})
    states["sensor.c_daily_cost"] = sensor("total")
    states["sensor.upstairs_temperature"] = sensor("measurement", "20")
    states["sensor.water_flow"] = sensor("measurement", "0")
    registry.append({"entity_id": "sensor.upstairs_temperature"})
    return states, registry


class TestTheCapIsSpentAfterTheFilter(unittest.TestCase):

    def test_the_old_rule_never_asked_about_upstairs(self):
        states, _registry = big_house()
        asked = the_old_rule(states)
        self.assertEqual(len(asked), baselines.MAX_ENTITIES)
        self.assertNotIn("sensor.upstairs_temperature", asked)
        self.assertNotIn("sensor.water_flow", asked)

    def test_every_slot_goes_to_a_sensor_a_reader_can_use(self):
        states, registry = big_house()
        chosen = baselines.select(states, registry)
        self.assertEqual(chosen["ids"], ["sensor.upstairs_temperature",
                                         "sensor.water_flow"])
        self.assertEqual(chosen["skipped"],
                         {"not_measurement": baselines.MAX_ENTITIES + 1,
                          "background": 30})
        self.assertEqual(chosen["cut"], [])
        self.assertTrue(chosen["categories_read"])
        self.assertEqual(baselines.candidates(states, registry), chosen["ids"])

    def test_a_config_entity_is_background_too(self):
        states = {"sensor.boost_level": sensor("measurement", "3")}
        registry = [{"entity_id": "sensor.boost_level",
                     "entity_category": "config"}]
        self.assertEqual(baselines.candidates(states, registry), [])

    def test_with_no_registry_the_state_class_still_filters(self):
        """A registry that did not answer costs the category filter and
        nothing else, and the store says which it was."""
        states, _registry = big_house()
        chosen = baselines.select(states, None)
        self.assertIn("sensor.upstairs_temperature", chosen["ids"])
        self.assertIn("sensor.b_plug_00_signal", chosen["ids"])
        self.assertNotIn("sensor.a_meter_000_energy", chosen["ids"])
        self.assertFalse(chosen["categories_read"])

    def test_the_readers_judge_exactly_what_is_measured(self):
        """The filter is the readers' own rule moved ahead of the cap, so
        it may not drop a sensor `checks/baseline.eligible` would read."""
        from checks import baseline as band  # noqa: PLC0415
        self.assertEqual(baselines.BASELINE_STATE_CLASSES,
                         band.MEASURED_CLASSES)
        self.assertEqual(baselines.BACKGROUND_CATEGORIES,
                         band.BACKGROUND_CATEGORIES)


class TestTheCutIsWrittenDownAndSaid(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "baselines.json")
        self.states = {f"sensor.s{i:04d}": sensor("measurement")
                       for i in range(baselines.MAX_ENTITIES + 25)}

    def build(self) -> dict:
        import ha_data  # noqa: PLC0415

        async def ws(session, commands):
            return [{}]
        real = ha_data._ws_commands
        ha_data._ws_commands = ws
        try:
            return asyncio.run(baselines.build(None, self.states, NOW,
                                               self.path, entities=[]))
        finally:
            ha_data._ws_commands = real

    def test_the_store_carries_the_count_and_a_sample(self):
        payload = self.build()
        self.assertEqual(payload["asked"], baselines.MAX_ENTITIES)
        self.assertEqual(payload["eligible"], baselines.MAX_ENTITIES + 25)
        self.assertEqual(payload["cut_count"], 25)
        self.assertEqual(len(payload["cut"]), baselines.CUT_SAMPLE)
        self.assertEqual(payload["cut"][0], f"sensor.s{baselines.MAX_ENTITIES:04d}")
        self.assertEqual(baselines.load(self.path)["cut_count"], 25)

    def test_progress_says_it(self):
        payload = self.build()
        said = baselines.progress(payload, now=NOW + 60)
        self.assertEqual(said["detail"]["cut"], 25)
        self.assertIn("25 more sensors were past the nightly cap",
                      said["summary"])

    def test_a_house_under_the_cap_says_nothing_about_one(self):
        self.states = {"sensor.one": sensor("measurement")}
        said = baselines.progress(self.build(), now=NOW + 60)
        self.assertEqual(said["detail"]["cut"], 0)
        self.assertNotIn("cap", said["summary"])


class TestTheNightlyPassHandsItTheRegistry(unittest.IsolatedAsyncioTestCase):
    """The registries were fetched after the baselines, for thermal alone;
    they come first now, once, for both — and a registry that did not
    answer still costs thermal its pass and the baselines nothing."""

    Harness = test_baselines.TestTheNightlyPassIsFourAttempts
    asyncSetUp = Harness.asyncSetUp
    asyncTearDown = Harness.asyncTearDown
    _fake = Harness._fake

    def recording(self, seen: dict):
        async def build(session, states, *args, **kwargs):
            seen.update(kwargs)
            self.calls.append("baselines")
            return {"entities": {}, "asked": 0}
        return build

    def quiet_others(self):
        self.mods[1].build = self._fake("closures", {"entities": {}})
        self.mods[2].build = self._fake("appliances", {"entities": {}})
        self.mods[3].build = self._fake("thermal", {"rooms": {}})

    async def test_the_entity_registry_reaches_the_baselines(self):
        seen: dict = {}
        baselines.build = self.recording(seen)
        self.quiet_others()
        self.registries = [[{"area_id": "hall", "name": "Hall"}], [],
                           [{"entity_id": "sensor.rssi",
                             "entity_category": "diagnostic"}]]
        summary = await self.server.build_baselines("test")
        self.assertEqual(seen["entities"][0]["entity_id"], "sensor.rssi")
        self.assertTrue(summary["builders"]["thermal"]["ok"])

    async def test_no_registry_measures_without_the_category_filter(self):
        seen: dict = {}
        baselines.build = self.recording(seen)
        self.quiet_others()
        self.registries = [None, None, None]
        summary = await self.server.build_baselines("test")
        self.assertIsNone(seen["entities"])
        self.assertTrue(summary["builders"]["baselines"]["ok"])
        self.assertFalse(summary["builders"]["thermal"]["ok"])

    async def test_a_registry_fetch_that_raised_is_named_on_thermal(self):
        seen: dict = {}
        baselines.build = self.recording(seen)
        self.quiet_others()

        async def boom(session, commands):
            raise RuntimeError("socket closed")
        self.ha_data._ws_commands = boom
        summary = await self.server.build_baselines("test")
        self.assertIsNone(seen["entities"])
        self.assertTrue(summary["builders"]["baselines"]["ok"])
        self.assertIn("socket closed", summary["builders"]["thermal"]["error"])


def band_house(value: str, unit: str, overall: bool = False) -> dict:
    """One baselined sensor, with its hour's bucket or only its history."""
    now = test_baselines.MONDAY + 10 * test_baselines.HOUR
    bucket = str(baselines.hour_of_week(now, dt.timezone.utc))
    entry = {"unit": unit, "samples": 650,
             "overall": {"median": 20.0, "spread": 0.05, "n": 650},
             "buckets": {} if overall else
             {bucket: {"median": 20.0, "spread": 0.05, "n": 4}}}
    return {
        "now": now,
        "states": {"sensor.reading": {
            "state": value,
            "attributes": {"state_class": "measurement",
                           "unit_of_measurement": unit},
            "last_changed": "", "last_updated": ""}},
        "entities": [{"entity_id": "sensor.reading", "name": "Reading"}],
        "devices": [], "areas": [],
        "baselines": {"built_at": int(now - 3600), "tz": "UTC", "days": 28,
                      "entities": {"sensor.reading": entry}},
    }


class TestTheSentenceCountsWhatItCounted(unittest.TestCase):

    def setUp(self):
        from checks import baseline as band  # noqa: PLC0415
        self.band = band

    def unusual(self, snap):
        return self.band.unusual(snap, snap["now"])

    def test_the_whole_history_is_hourly_readings_and_not_weeks(self):
        found = self.unusual(band_house("21.5", "°C", overall=True))
        self.assertEqual(len(found), 1)
        detail = found[0]["detail"]
        self.assertNotIn("650 weeks", detail)
        self.assertIn("650 hourly readings", detail)
        self.assertNotIn("for this hour of the week (", detail)

    def test_an_hour_bucket_still_counts_weeks(self):
        found = self.unusual(band_house("21.5", "°C"))
        self.assertIn("for this hour of the week (from 4 weeks of readings)",
                      found[0]["detail"])


class TestTheFloorIsInTheReadingsOwnUnit(unittest.TestCase):

    def setUp(self):
        from checks import baseline as band  # noqa: PLC0415
        from checks import forecasts  # noqa: PLC0415
        self.band = band
        self.forecasts = forecasts

    def unusual(self, snap):
        return self.band.unusual(snap, snap["now"])

    def test_a_watt_is_not_a_degree(self):
        """Twenty spreads of a tight band, a move of 1 W: the old floor of
        half a unit let it through."""
        snap = band_house("21", "W")
        self.assertGreaterEqual(1.0, self.band.MIN_ABSOLUTE_MOVE)
        self.assertEqual(self.unusual(snap), [])
        self.assertEqual(len(self.unusual(band_house("80", "W"))), 1)

    def test_a_degree_is_still_half_a_degree(self):
        self.assertEqual(self.band.min_move("°C"), 0.5)
        self.assertEqual(len(self.unusual(band_house("21", "°C"))), 1)

    def test_an_unlisted_unit_keeps_the_old_floor(self):
        self.assertEqual(self.band.min_move("pH"), self.band.MIN_ABSOLUTE_MOVE)
        self.assertEqual(self.band.min_move(None), self.band.MIN_ABSOLUTE_MOVE)

    def test_the_drift_check_reads_the_same_floor(self):
        snap = band_house("20", "W")
        snap["baselines"]["entities"]["sensor.reading"]["trend"] = {
            "per_day": 0.1, "move": 3.0, "days": 28.0, "noise": 0.1,
            "spreads": 30.0, "consistent": True}
        self.assertEqual(self.forecasts.decline(snap, snap["now"]), [])
        snap["baselines"]["entities"]["sensor.reading"]["trend"]["move"] = 60.0
        self.assertEqual(len(self.forecasts.decline(snap, snap["now"])), 1)


if __name__ == "__main__":
    unittest.main()
