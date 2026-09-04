"""Two numbers about a room, and every way of getting them wrong.

`thermal.py` measures how fast a room falls towards outdoors and how fast
anything can put the heat back, from a month of hourly statistics. Every
case here is one of the ways that measurement is confidently wrong — the
sun warming a room the fit thinks is cooling, a month of weather that
never moved, a freezer wearing a temperature device class, a Fahrenheit
reference against a Celsius room — plus the two checks that read it, each
asserted silent on a healthy house before it is asserted to find a
planted one.

The recovery tests are written the way the appliance ones are: build a
room whose physics is *known*, run the real fitter over it, and check the
number that comes back is the one that went in. A test that only asserts
"a number came back" is a test of the plumbing.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import checks  # noqa: E402
import thermal  # noqa: E402

# `checks.thermal` rather than `from checks import thermal`: this module
# already imports the package for the catalog, and CodeQL is right that
# one module reached two ways is one name that can mean two things.
thermal_check = checks.thermal

NOW = 1_800_000_000.0
UTC = dt.timezone.utc
# A Wednesday midnight, so the night window lands where the sim puts it.
START = dt.datetime(2026, 1, 7, 0, 0, tzinfo=UTC).timestamp()


# ---------------------------------------------------------------------------
# A house whose physics is known
# ---------------------------------------------------------------------------

def simulate(k: float = 0.10, gain: float = 1.5, days: int = 28,
             heat_hours: tuple[int, ...] = (6, 7, 8, 17, 18, 19, 20, 21),
             outdoor_swing: float = 5.0, start_in: float = 19.0,
             noise: float = 0.05, sun: float = 0.0,
             seed: int = 7) -> tuple[list[dict], list[dict]]:
    """`(room_rows, outdoor_rows)` for a room obeying `dT/dt = h - k·Δ`.

    `sun` adds a gain in the afternoon only, which is the confounder the
    night gate exists for: it is invisible to a night-only fit and would
    wreck an all-day one.
    """
    rng = random.Random(seed)
    room, out = [], []
    inside = start_in
    for i in range(days * 24):
        ts = START + i * 3600
        hour = dt.datetime.fromtimestamp(ts, UTC).hour
        outside = (6.0
                   + outdoor_swing * math.sin(i / 24.0 * 2 * math.pi)
                   + 4.0 * math.sin(i / (24 * 7.0) * 2 * math.pi)
                   + rng.gauss(0, 0.6))
        room.append({"start": ts, "mean": round(inside, 3)})
        out.append({"start": ts, "mean": round(outside, 3)})
        added = gain if hour in heat_hours else 0.0
        if sun and 11 <= hour < 16:
            added += sun
        inside += added - k * (inside - outside) + rng.gauss(0, noise)
    return room, out


class TestTheNumbersComeBack(unittest.TestCase):
    """The fit recovers the physics that was put in."""

    def test_the_loss_rate_is_the_one_the_room_was_built_with(self):
        room, out = simulate(k=0.10)
        built = thermal.build_room(room, out, UTC, "°C")
        self.assertIsNotNone(built)
        self.assertAlmostEqual(built["k"], 0.10, delta=0.015)
        self.assertAlmostEqual(built["tau_h"], 10.0, delta=1.5)

    def test_a_well_insulated_room_and_a_leaky_one_are_told_apart(self):
        tight = thermal.build_room(*simulate(k=0.03), UTC, "°C")
        leaky = thermal.build_room(*simulate(k=0.25), UTC, "°C")
        self.assertIsNotNone(tight)
        self.assertIsNotNone(leaky)
        self.assertGreater(leaky["k"], tight["k"] * 5)

    def test_the_gain_is_what_the_heating_was_seen_to_add(self):
        room, out = simulate(k=0.10, gain=1.5)
        built = thermal.build_room(room, out, UTC, "°C")
        self.assertAlmostEqual(built["gain"], 1.5, delta=0.25)

    def test_a_room_nothing_heats_reports_no_gain_rather_than_a_small_one(self):
        room, out = simulate(k=0.10, gain=0.0, heat_hours=())
        built = thermal.build_room(room, out, UTC, "°C")
        self.assertIsNotNone(built)
        self.assertIsNone(built.get("gain"))

    def test_the_warmest_hour_is_recorded_beside_the_model(self):
        room, out = simulate()
        built = thermal.build_room(room, out, UTC, "°C")
        self.assertAlmostEqual(built["warmest"],
                               max(r["mean"] for r in room), places=2)
        self.assertAlmostEqual(built["coolest"],
                               min(r["mean"] for r in room), places=2)


class TestTheSunIsTheConfounder(unittest.TestCase):
    """The gate that would otherwise be wrong in every south-facing room."""

    def test_an_afternoon_of_sun_does_not_move_the_night_fit(self):
        plain = thermal.build_room(*simulate(k=0.10, sun=0.0), UTC, "°C")
        sunny = thermal.build_room(*simulate(k=0.10, sun=1.2), UTC, "°C")
        self.assertAlmostEqual(sunny["k"], plain["k"], delta=0.02)

    def test_the_same_fit_without_the_night_gate_reports_a_different_room(self):
        """The measurement the gate exists to prevent, run on purpose."""
        room, out = simulate(k=0.10, sun=1.2)
        rooms = thermal._hourly_map(room)
        outs = thermal._hourly_map(out)
        all_day = thermal.fit_loss(
            thermal._pairs(rooms, outs, UTC, night_only=False))
        night = thermal.fit_loss(
            thermal._pairs(rooms, outs, UTC, night_only=True))
        self.assertIsNotNone(night)
        # Either the all-day fit lands somewhere else entirely or it is
        # refused; what it may not do is quietly agree.
        if all_day is not None:
            self.assertGreater(abs(all_day["k"] - 0.10), 0.02)

    def test_only_the_deep_night_hours_are_paired(self):
        rooms = {int(START + h * 3600): 20.0 for h in range(24)}
        outs = dict(rooms)
        pairs = thermal._pairs(rooms, outs, UTC, night_only=True)
        self.assertEqual(len(pairs), thermal.NIGHT_TO - thermal.NIGHT_FROM)


class TestAFitIsNotAMeasurementUntilItIsGraded(unittest.TestCase):

    def test_a_month_of_weather_that_never_moved_answers_nothing(self):
        room, out = simulate(k=0.10, outdoor_swing=0.2)
        # Flatten what is left, so the delta span is under the floor.
        for r in out:
            r["mean"] = 6.0
        for r in room:
            r["mean"] = 19.0
        self.assertIsNone(thermal.build_room(room, out, UTC, "°C"))

    def test_the_span_floor_is_what_refuses_it(self):
        points = [(10.0, -1.0)] * 40
        self.assertIsNone(thermal.fit_loss(points))
        wide = [(10.0 + i * 0.5, -(10.0 + i * 0.5) * 0.1) for i in range(40)]
        self.assertIsNotNone(thermal.fit_loss(wide))

    def test_a_fortnight_of_nights_is_the_floor(self):
        few = [(10.0 + i, -(10.0 + i) * 0.1)
               for i in range(thermal.MIN_POINTS - 1)]
        self.assertIsNone(thermal.fit_loss(few))

    def test_noise_that_swamps_the_slope_is_no_slope(self):
        rng = random.Random(3)
        points = [(10.0 + i * 0.3, -0.001 * (10.0 + i * 0.3) + rng.gauss(0, 5))
                  for i in range(200)]
        self.assertIsNone(thermal.fit_loss(points))

    def test_a_room_that_warms_as_it_gets_colder_outside_is_not_a_room(self):
        points = [(10.0 + i * 0.4, 0.1 * (10.0 + i * 0.4)) for i in range(60)]
        self.assertIsNone(thermal.fit_loss(points))

    def test_a_time_constant_outside_a_building_is_refused(self):
        fast = [(10.0 + i * 0.4, -3.0 * (10.0 + i * 0.4)) for i in range(60)]
        self.assertIsNone(thermal.fit_loss(fast))
        glacial = [(10.0 + i * 0.4, -0.001 * (10.0 + i * 0.4))
                   for i in range(60)]
        self.assertIsNone(thermal.fit_loss(glacial))

    def test_a_gap_in_the_recorder_is_skipped_and_never_bridged(self):
        rooms = {int(START + 1 * 3600): 20.0, int(START + 5 * 3600): 16.0}
        outs = {int(START + 1 * 3600): 5.0, int(START + 5 * 3600): 5.0}
        self.assertEqual(thermal._pairs(rooms, outs, UTC, night_only=True), [])


class TestNotEveryThermometerIsARoom(unittest.TestCase):

    def test_a_freezer_is_not_a_room(self):
        room, out = simulate(k=0.05, gain=0.0, heat_hours=(), start_in=-18.0)
        for r in room:
            r["mean"] = -18.0 + (r["mean"] - room[0]["mean"]) * 0.01
        self.assertIsNone(thermal.build_room(room, out, UTC, "°C"))

    def test_the_band_is_the_unit_it_is_asked_about(self):
        self.assertTrue(thermal.in_room_band(20.0, "°C"))
        self.assertFalse(thermal.in_room_band(20.0, "°F"))
        self.assertTrue(thermal.in_room_band(68.0, "°F"))
        self.assertFalse(thermal.in_room_band(-18.0, "°C"))

    def test_a_unit_that_is_not_a_temperature_is_no_unit(self):
        self.assertEqual(thermal.normalise_unit("°C"), "°C")
        self.assertEqual(thermal.normalise_unit("f"), "°F")
        self.assertEqual(thermal.normalise_unit("K"), "")
        self.assertEqual(thermal.normalise_unit(None), "")


def state(name: str, value: str, unit: str = "°C",
          device_class: str = "temperature", **attrs) -> dict:
    base = {"friendly_name": name, "state_class": "measurement"}
    if device_class:
        base["device_class"] = device_class
    if unit:
        base["unit_of_measurement"] = unit
    base.update(attrs)
    return {"state": value, "attributes": base}


class TestWhichSensorIsOutside(unittest.TestCase):

    def test_a_sensor_that_says_it_is_outside_wins(self):
        states = {"sensor.a": state("Hall", "20"),
                  "sensor.b": state("Outside temperature", "4")}
        self.assertEqual(thermal.pick_outdoor(states, {"sensor.a": "Hall"}),
                         ("sensor.b", "°C"))

    def test_a_thermometer_in_no_area_is_the_fallback(self):
        states = {"sensor.a": state("Hall", "20"),
                  "sensor.weather": state("Temperature", "4")}
        self.assertEqual(
            thermal.pick_outdoor(states, {"sensor.a": "Hall"}),
            ("sensor.weather", "°C"))

    def test_a_house_with_no_reference_gets_no_model_and_says_so(self):
        states = {"sensor.a": state("Hall", "20")}
        self.assertEqual(thermal.pick_outdoor(states, {"sensor.a": "Hall"}),
                         ("", ""))

    def test_the_reference_is_recorded_so_it_can_be_corrected(self):
        payload = asyncio.run(_build({
            "sensor.garden": state("Garden temperature", "4"),
            "sensor.hall": state("Hall", "20")},
            {"sensor.hall": "Hall"}, rows={}))
        self.assertEqual(payload["outdoor"], "sensor.garden")


class TestIndoorsAndOutdoorsAgreeAboutADegree(unittest.TestCase):

    def test_a_fahrenheit_room_against_a_celsius_reference_is_refused(self):
        states = {"sensor.garden": state("Outside", "40", unit="°F"),
                  "sensor.hall": state("Hall", "20", unit="°C")}
        outdoor, unit = thermal.pick_outdoor(states, {"sensor.hall": "Hall"})
        self.assertEqual(unit, "°F")
        self.assertEqual(
            thermal.room_candidates(states, outdoor, unit,
                                    {"sensor.hall": "Hall"}), [])

    def test_a_matching_pair_is_kept(self):
        states = {"sensor.garden": state("Outside", "40", unit="°F"),
                  "sensor.hall": state("Hall", "68", unit="°F")}
        outdoor, unit = thermal.pick_outdoor(states, {"sensor.hall": "Hall"})
        self.assertEqual(
            thermal.room_candidates(states, outdoor, unit,
                                    {"sensor.hall": "Hall"}),
            ["sensor.hall"])

    def test_a_thermometer_with_no_area_cannot_name_a_room(self):
        states = {"sensor.garden": state("Outside", "4"),
                  "sensor.shed": state("Shed", "9")}
        outdoor, unit = thermal.pick_outdoor(states, {})
        self.assertEqual(thermal.room_candidates(states, outdoor, unit, {}), [])


class TestWhatTheNumbersAnswer(unittest.TestCase):

    def setUp(self):
        self.entry = {"k": 0.1, "gain": 2.0}

    def test_a_room_coasts_towards_outside_and_never_past_it(self):
        self.assertAlmostEqual(thermal.coast(self.entry, 20.0, 0.0, 0.0), 20.0)
        self.assertLess(thermal.coast(self.entry, 20.0, 0.0, 10.0), 20.0)
        self.assertGreater(thermal.coast(self.entry, 20.0, 0.0, 1000.0), -0.001)

    def test_a_room_never_falls_below_what_is_outside_it(self):
        self.assertIsNone(thermal.hours_to_fall(self.entry, 20.0, 6.0, 5.0))
        self.assertAlmostEqual(
            thermal.hours_to_fall(self.entry, 20.0, 0.0, 10.0),
            math.log(2.0) / 0.1, places=4)

    def test_a_room_already_there_is_there_now(self):
        self.assertEqual(thermal.hours_to_fall(self.entry, 4.0, 0.0, 5.0), 0.0)
        self.assertEqual(thermal.hours_to_warm(self.entry, 21.0, 0.0, 20.0),
                         0.0)

    def test_the_ceiling_is_where_the_gain_and_the_loss_balance(self):
        self.assertAlmostEqual(thermal.ceiling(self.entry, 0.0), 20.0)
        self.assertAlmostEqual(thermal.ceiling(self.entry, -5.0), 15.0)

    def test_a_target_above_the_ceiling_is_a_different_answer_from_a_slow_one(self):
        self.assertIsNone(thermal.hours_to_warm(self.entry, 10.0, 0.0, 25.0))
        self.assertIsNotNone(thermal.hours_to_warm(self.entry, 10.0, 0.0, 18.0))

    def test_half_a_model_answers_nothing_rather_than_guessing(self):
        self.assertIsNone(thermal.ceiling({"k": 0.1}, 0.0))
        self.assertIsNone(thermal.coast({}, 20.0, 0.0, 1.0))
        self.assertIsNone(thermal.hours_to_fall({}, 20.0, 0.0, 10.0))


async def _build(states: dict, areas: dict, rows: dict,
                 path: str | None = None) -> dict:
    """Drive the real `build` with the statistics fetch stubbed out."""
    registries = {
        "areas": [{"area_id": a.lower().replace(" ", "_"), "name": a}
                  for a in sorted(set(areas.values()))],
        "devices": [],
        "entities": [{"entity_id": e, "area_id": a.lower().replace(" ", "_")}
                     for e, a in sorted(areas.items())],
    }
    original = thermal.fetch_hourly

    async def fake(session, ids, now, days=thermal.HISTORY_DAYS):
        return {i: rows.get(i, []) for i in ids}

    thermal.fetch_hourly = fake
    try:
        return await thermal.build(None, states, registries, NOW, path)
    finally:
        thermal.fetch_hourly = original


class TestTheStoreSaysWhyWhenItIsEmpty(unittest.TestCase):
    """"No rooms" and "nothing to measure them against" are different."""

    def test_no_outdoor_sensor_is_a_sentence_not_a_zero(self):
        payload = asyncio.run(_build(
            {"sensor.hall": state("Hall", "20")}, {"sensor.hall": "Hall"}, {}))
        self.assertEqual(payload["rooms"], {})
        self.assertIn("outdoor", payload["reason"])

    def test_no_indoor_sensor_names_the_unit_it_wanted(self):
        payload = asyncio.run(_build(
            {"sensor.garden": state("Outside", "4")}, {}, {}))
        self.assertEqual(payload["rooms"], {})
        self.assertIn("°C", payload["reason"])

    def test_a_month_that_could_not_be_fitted_says_so(self):
        payload = asyncio.run(_build(
            {"sensor.garden": state("Outside", "4"),
             "sensor.hall": state("Hall", "20")},
            {"sensor.hall": "Hall"},
            {"sensor.garden": [{"start": START, "mean": 4.0}],
             "sensor.hall": [{"start": START, "mean": 20.0}]}))
        self.assertEqual(payload["rooms"], {})
        self.assertTrue(payload["reason"])

    def test_a_measured_house_records_the_coldest_it_saw(self):
        room, out = simulate()
        payload = asyncio.run(_build(
            {"sensor.garden": state("Outside", "4"),
             "sensor.hall": state("Hall", "20")},
            {"sensor.hall": "Hall"},
            {"sensor.garden": out, "sensor.hall": room}))
        self.assertIn("sensor.hall", payload["rooms"])
        self.assertEqual(payload["rooms"]["sensor.hall"]["area"], "Hall")
        self.assertAlmostEqual(payload["coldest"],
                               min(r["mean"] for r in out), places=2)
        self.assertEqual(payload["reason"], "")

    def test_a_missing_store_reads_as_unmeasured_never_as_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = thermal.load(os.path.join(tmp, "nope.json"))
        self.assertEqual(store["rooms"], {})
        self.assertEqual(store["built_at"], 0)
        self.assertTrue(thermal.is_stale(store, NOW))

    def test_what_is_written_is_what_is_read_back(self):
        room, out = simulate()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "thermal.json")
            asyncio.run(_build(
                {"sensor.garden": state("Outside", "4"),
                 "sensor.hall": state("Hall", "20")},
                {"sensor.hall": "Hall"},
                {"sensor.garden": out, "sensor.hall": room}, path))
            with open(path, encoding="utf-8") as fh:
                on_disk = json.load(fh)
            self.assertEqual(thermal.load(path), on_disk)
        self.assertIn("sensor.hall", on_disk["rooms"])


class TestTheAreaMapIsHomeAssistantsOwnRule(unittest.TestCase):

    def test_an_entity_inherits_its_devices_area(self):
        got = thermal.area_map({
            "areas": [{"area_id": "hall", "name": "Hall"}],
            "devices": [{"id": "d1", "area_id": "hall"}],
            "entities": [{"entity_id": "sensor.a", "device_id": "d1"}]})
        self.assertEqual(got, {"sensor.a": "Hall"})

    def test_its_own_area_wins_over_its_devices(self):
        got = thermal.area_map({
            "areas": [{"area_id": "hall", "name": "Hall"},
                      {"area_id": "loft", "name": "Loft"}],
            "devices": [{"id": "d1", "area_id": "hall"}],
            "entities": [{"entity_id": "sensor.a", "device_id": "d1",
                          "area_id": "loft"}]})
        self.assertEqual(got, {"sensor.a": "Loft"})

    def test_no_registries_is_an_empty_map_rather_than_a_crash(self):
        self.assertEqual(thermal.area_map(None), {})
        self.assertEqual(thermal.area_map({}), {})


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def room(k: float = 0.08, gain: float = 1.8, warmest: float = 22.4,
         area: str = "Hall", unit: str = "°C") -> dict:
    return {"name": f"{area} Temperature", "area": area, "unit": unit,
            "k": k, "tau_h": round(1.0 / k, 2), "gain": gain,
            "warmest": warmest, "coolest": warmest - 4.5, "hours": 660,
            "points": 100, "fit": 8.0}


def snap(rooms: dict, coldest: float = 1.0, target: float | None = 21.0,
         hvac: str = "heat", unit: str = "°C") -> dict:
    states: dict = {}
    entities = []
    areas = []
    seen = set()
    for eid, entry in rooms.items():
        area = entry.get("area") or "Hall"
        aid = area.lower().replace(" ", "_")
        if aid not in seen:
            seen.add(aid)
            areas.append({"area_id": aid, "name": area})
            if target is not None:
                cid = f"climate.{aid}"
                states[cid] = {"state": hvac, "attributes": {
                    "friendly_name": f"{area} thermostat",
                    "temperature": target}}
                entities.append({"entity_id": cid, "area_id": aid})
        states[eid] = state(entry["name"], str(entry["warmest"]), unit=unit)
        entities.append({"entity_id": eid, "area_id": aid})
    return {
        "now": NOW,
        "available": {"states": True, "registry": True, "thermal": True},
        "states": states, "entities": entities, "devices": [], "areas": areas,
        "services": set(),
        "thermal": {"built_at": int(NOW - 86400), "tz": "UTC", "days": 28,
                    "outdoor": "sensor.garden", "unit": unit,
                    "coldest": coldest, "asked": len(rooms), "rooms": rooms},
    }


def four(**over) -> dict:
    rooms = {
        "sensor.hall_temp": room(area="Hall"),
        "sensor.lounge_temp": room(k=0.075, gain=2.0, warmest=22.8,
                                   area="Lounge"),
        "sensor.kitchen_temp": room(k=0.09, gain=2.2, warmest=23.1,
                                    area="Kitchen"),
        "sensor.study_temp": room(k=0.085, gain=1.9, warmest=22.0,
                                  area="Study"),
    }
    rooms.update(over)
    return rooms


class TestUnderheated(unittest.TestCase):

    def test_a_healthy_house_says_nothing(self):
        self.assertEqual(thermal_check.underheated(snap(four()), NOW), [])

    def test_a_room_that_never_reaches_its_setpoint_is_reported(self):
        cold = room(k=0.30, gain=1.2, warmest=17.8, area="Study")
        found = thermal_check.underheated(
            snap(four(**{"sensor.study_temp": cold})), NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Study", found[0]["text"])
        self.assertIn("17.8", found[0]["detail"])
        self.assertEqual(found[0]["entity_id"], "sensor.study_temp")

    def test_a_room_that_has_been_at_its_setpoint_is_never_reported(self):
        """The evidence half, which is what keeps this off healthy houses.

        The arithmetic alone says this room cannot reach 21 — its gain is
        small and its loss is large. It has been at 21.4 all the same,
        because a thermostat that switches off at its setpoint never lets
        a room show what it could have done.
        """
        seen = room(k=0.30, gain=1.2, warmest=21.4, area="Study")
        self.assertIsNotNone(
            thermal_check.underheated_rooms(snap(four())) or [])
        self.assertEqual(thermal_check.underheated(
            snap(four(**{"sensor.study_temp": seen})), NOW), [])

    def test_a_mild_month_answers_nothing_rather_than_extrapolating(self):
        cold = room(k=0.30, gain=1.2, warmest=17.8, area="Study")
        mild = snap(four(**{"sensor.study_temp": cold}), coldest=14.0)
        self.assertEqual(thermal_check.underheated(mild, NOW), [])

    def test_a_room_nothing_asks_anything_of_is_not_underheated(self):
        cold = room(k=0.30, gain=1.2, warmest=17.8, area="Study")
        none = snap(four(**{"sensor.study_temp": cold}), target=None)
        self.assertEqual(thermal_check.underheated(none, NOW), [])

    def test_a_thermostat_that_is_off_is_asking_for_nothing(self):
        cold = room(k=0.30, gain=1.2, warmest=17.8, area="Study")
        off = snap(four(**{"sensor.study_temp": cold}), hvac="off")
        self.assertEqual(thermal_check.underheated(off, NOW), [])

    def test_half_a_model_reports_nothing(self):
        half = room(area="Study")
        half.pop("gain")
        half["warmest"] = 17.8
        self.assertEqual(thermal_check.underheated(
            snap(four(**{"sensor.study_temp": half})), NOW), [])

    def test_past_the_cap_it_is_the_measurement_not_the_house(self):
        rooms = {eid: room(k=0.30, gain=1.2, warmest=17.0,
                           area=entry["area"])
                 for eid, entry in four().items()}
        self.assertEqual(thermal_check.underheated(snap(rooms), NOW), [])

    def test_a_fahrenheit_house_gets_a_fahrenheit_margin(self):
        rooms = four()
        for entry in rooms.values():
            entry["unit"] = "°F"
            entry["warmest"] = 71.0
        # 71 °F is 1 °F under a 72 °F setpoint, which is inside the
        # margin: in Celsius the same gap would be over half of it.
        self.assertEqual(
            thermal_check.underheated(snap(rooms, coldest=30.0, target=72.0,
                                           unit="°F"), NOW), [])


class TestHeatLoss(unittest.TestCase):

    def test_a_healthy_house_says_nothing(self):
        self.assertEqual(thermal_check.heat_loss(snap(four()), NOW), [])

    def test_the_one_draughty_room_is_reported(self):
        leaky = room(k=0.25, gain=2.0, warmest=22.5, area="Study")
        found = thermal_check.heat_loss(
            snap(four(**{"sensor.study_temp": leaky})), NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Study", found[0]["text"])
        self.assertEqual(found[0]["entity_id"], "sensor.study_temp")
        self.assertIn("4.0 hours", found[0]["detail"])

    def test_a_house_with_too_few_rooms_has_no_rest_of_the_house(self):
        rooms = {"sensor.hall_temp": room(area="Hall"),
                 "sensor.study_temp": room(k=0.25, area="Study")}
        self.assertEqual(thermal_check.heat_loss(snap(rooms), NOW), [])

    def test_twice_a_very_slow_house_is_still_a_good_room(self):
        rooms = {eid: room(k=0.012, gain=1.8, area=e["area"])
                 for eid, e in four().items()}
        rooms["sensor.study_temp"] = room(k=0.03, gain=1.8, area="Study")
        # 0.03 is well over twice the median, and a room that takes 33
        # hours to fall half way to outside is not draughty.
        self.assertEqual(thermal_check.heat_loss(snap(rooms), NOW), [])

    def test_a_whole_cold_house_is_the_measurement_not_a_room(self):
        rooms = four()
        for eid in ("sensor.study_temp", "sensor.kitchen_temp",
                    "sensor.lounge_temp"):
            rooms[eid] = room(k=0.30, gain=2.0,
                              area=rooms[eid]["area"])
        self.assertEqual(thermal_check.heat_loss(snap(rooms), NOW), [])

    def test_a_room_the_other_check_claims_is_not_reported_twice(self):
        """One room, one fix. The two checks share `underheated_rooms`."""
        both = room(k=0.30, gain=1.2, warmest=17.8, area="Study")
        house = snap(four(**{"sensor.study_temp": both}))
        under = thermal_check.underheated(house, NOW)
        loss = thermal_check.heat_loss(house, NOW)
        self.assertEqual(len(under), 1)
        self.assertEqual(loss, [])
        # And with nothing asking for a temperature, the same room is the
        # heat-loss finding instead — never neither, and never both.
        alone = snap(four(**{"sensor.study_temp": both}), target=None)
        self.assertEqual(thermal_check.underheated(alone, NOW), [])
        self.assertEqual(len(thermal_check.heat_loss(alone, NOW)), 1)


class TestTheChecksAreRegistered(unittest.TestCase):

    def test_both_are_in_the_catalog_under_a_named_group(self):
        ids = {c["id"] for c in checks.CHECKS}
        self.assertIn("climate.underheated", ids)
        self.assertIn("climate.heat_loss", ids)
        self.assertEqual(checks.title_for("climate.underheated"),
                         "Climate check")

    def test_neither_runs_without_the_store(self):
        house = snap(four())
        house["available"]["thermal"] = False
        result = checks.run_all(house, NOW, only=["climate.underheated",
                                                  "climate.heat_loss"])
        self.assertEqual(result["ran"], [])
        self.assertEqual(len(result["skipped"]), 2)


if __name__ == "__main__":
    unittest.main()
