"""The outdoor reference is chosen on evidence, and a person can overrule it.

Every room's heat-loss rate is measured against ONE outdoor thermometer,
and `thermal.pick_outdoor` took the alphabetically first sensor whose
name held any outdoor word — "ambient" and "garden" included — whatever
area it was in. So a heat pump's outdoor-coil sensor sorted ahead of the
real outdoor thermometer, an outdoor pool's water temperature could win,
and an indoor "Ambient" reading was eligible; nothing checked the choice
and nothing could change it, and a wrong one corrupts every room's `k`
and through it `climate.window`, `climate.freeze` and `climate.preheat`.

Each case drives the real `rank_outdoor`/`choose_outdoor` and the real
nightly `build`, and the first states the old rule's answer on the same
house before asserting the new one.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import settings_store  # noqa: E402
import thermal  # noqa: E402
from test_thermal import START, _build, simulate, state  # noqa: E402


def the_old_rule(states: dict, areas: dict) -> str:
    """`pick_outdoor` as it shipped: named first, alphabetically, else the
    first unplaced — stated so the new answer is measured against it."""
    named, unplaced = [], []
    for eid, st, _unit in thermal._temperature_sensors(states):
        if thermal.is_derived(eid, st):
            continue
        if thermal._looks_outdoor(eid, st):
            named.append(eid)
        elif not areas.get(eid):
            unplaced.append(eid)
    return (named or unplaced or [""])[0]


class TestTheAlphabetDoesNotChoose(unittest.TestCase):

    def house(self) -> dict:
        return {
            "sensor.heat_pump_outdoor_coil_temperature":
                state("Heat pump outdoor coil", "-6"),
            "sensor.outdoor_pool_temperature": state("Outdoor pool", "18"),
            "sensor.outdoor_temperature": state("Outdoor temperature", "4"),
            "sensor.lounge": state("Lounge", "20"),
        }

    def test_the_old_rule_picked_the_coil(self):
        self.assertEqual(the_old_rule(self.house(), {"sensor.lounge": "Lounge"}),
                         "sensor.heat_pump_outdoor_coil_temperature")

    def test_the_air_wins(self):
        self.assertEqual(
            thermal.pick_outdoor(self.house(), {"sensor.lounge": "Lounge"}),
            ("sensor.outdoor_temperature", "°C"))

    def test_the_reasons_are_sentences(self):
        chosen = thermal.choose_outdoor(self.house(), {"sensor.lounge": "Lounge"})
        self.assertEqual(chosen["source"], "ranked")
        self.assertIn("named as outdoors", chosen["why"])
        coil = next(c for c in chosen["candidates"]
                    if c["entity_id"].startswith("sensor.heat_pump"))
        self.assertIn("machine or of water", " ".join(coil["reasons"]))


class TestAnIndoorAreaRulesItOut(unittest.TestCase):

    def test_an_ambient_sensor_in_the_lounge_is_never_the_reference(self):
        states = {"sensor.ac_ambient": state("AC ambient temperature", "21"),
                  "sensor.hall": state("Hall", "20")}
        areas = {"sensor.ac_ambient": "Lounge", "sensor.hall": "Hall"}
        self.assertEqual(the_old_rule(states, areas), "sensor.ac_ambient")
        self.assertEqual(thermal.pick_outdoor(states, areas), ("", ""))
        listed = thermal.choose_outdoor(states, areas)["candidates"]
        self.assertIn("indoors", listed[0]["ruled_out"])

    def test_an_area_called_the_garden_is_outdoors(self):
        states = {"sensor.t1": state("Thermometer 1", "4"),
                  "sensor.hall": state("Hall", "20")}
        areas = {"sensor.t1": "Back garden", "sensor.hall": "Hall"}
        self.assertEqual(thermal.pick_outdoor(states, areas),
                         ("sensor.t1", "°C"))
        # And a thermometer in the garden is not a room either.
        self.assertEqual(
            thermal.room_candidates(states, "", "°C", areas), ["sensor.hall"])


class TestTheWeatherEntityNeedsNoWords(unittest.TestCase):
    """Reading what a weather entity reads is evidence in any language."""

    def test_the_sensor_that_tracks_the_forecast_wins(self):
        states = {
            "sensor.capteur_1": state("Capteur 1", "19"),
            "sensor.capteur_2": state("Capteur 2", "5.4"),
            "weather.maison": {"state": "cloudy", "attributes": {
                "temperature": 5.0, "temperature_unit": "°C"}},
        }
        self.assertEqual(the_old_rule(states, {}), "sensor.capteur_1")
        chosen = thermal.choose_outdoor(states, {})
        self.assertEqual(chosen["entity_id"], "sensor.capteur_2")
        self.assertIn("weather.maison", chosen["why"])

    def test_units_are_converted_before_they_are_compared(self):
        states = {
            "sensor.a": state("A", "41", unit="°F"),   # 5 °C
            "weather.home": {"state": "sunny", "attributes": {
                "temperature": 5.0, "temperature_unit": "°C"}},
        }
        chosen = thermal.choose_outdoor(states, {})
        self.assertIn("within", chosen["why"])

    def test_the_weather_integrations_own_sensor_is_preferred(self):
        states = {
            "sensor.a_reading": state("A reading", "7"),
            "sensor.owm_temperature": state("Temperature", "7"),
            "weather.owm": {"state": "rainy", "attributes": {
                "temperature": 7.0, "temperature_unit": "°C"}},
        }
        entities = [{"entity_id": "sensor.owm_temperature",
                     "platform": "openweathermap"},
                    {"entity_id": "weather.owm", "platform": "openweathermap"},
                    {"entity_id": "sensor.a_reading", "platform": "zha"}]
        chosen = thermal.choose_outdoor(states, {}, entities)
        self.assertEqual(chosen["entity_id"], "sensor.owm_temperature")
        self.assertIn("openweathermap", chosen["why"])


def daily(swing: float, base: float = 6.0, days: int = 28) -> list[dict]:
    return [{"start": START + i * 3600,
             "mean": base + swing / 2 * math.sin(i / 24.0 * 2 * math.pi)}
            for i in range(days * 24)]


class TestTheMonthsSwingIsTheLastWord(unittest.TestCase):

    def test_air_swings_and_a_thermometer_in_a_wall_does_not(self):
        """Two sensors nothing on their states tells apart; the month does."""
        room, out = simulate()
        states = {"sensor.a_sensor": state("Sensor A", "6"),
                  "sensor.b_sensor": state("Sensor B", "6"),
                  "sensor.hall": state("Hall", "20")}
        self.assertEqual(thermal.pick_outdoor(states, {"sensor.hall": "Hall"}),
                         ("sensor.a_sensor", "°C"))   # a tie, by id
        payload = asyncio.run(_build(states, {"sensor.hall": "Hall"}, {
            "sensor.a_sensor": daily(0.3),    # alphabetically first, flat
            "sensor.b_sensor": out,           # the real outside air
            "sensor.hall": room}))
        self.assertEqual(payload["outdoor"], "sensor.b_sensor")
        self.assertIn("swings", payload["outdoor_why"])
        self.assertEqual(payload["outdoor_source"], "ranked")
        self.assertIn("sensor.hall", payload["rooms"])

    def test_too_little_history_says_nothing_about_a_swing(self):
        self.assertIsNone(thermal.daily_swing(daily(5.0, days=2), thermal.dt.timezone.utc))


class TestAPersonCanChooseIt(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.settings = os.path.join(self.dir.name, "settings.json")
        patch = unittest.mock.patch.object(settings_store, "SETTINGS_FILE", self.settings)
        patch.start()
        self.addCleanup(patch.stop)

    def states(self) -> dict:
        return {"sensor.outside": state("Outside", "4"),
                "sensor.shed": state("Shed", "9"),
                "sensor.hall": state("Hall", "20")}

    def test_the_choice_is_what_every_room_is_measured_against(self):
        settings_store.save({"thermal_outdoor": "sensor.shed"})
        room, out = simulate()
        payload = asyncio.run(_build(self.states(), {"sensor.hall": "Hall"}, {
            "sensor.shed": out, "sensor.outside": daily(0.1),
            "sensor.hall": room}))
        self.assertEqual(payload["outdoor"], "sensor.shed")
        self.assertEqual(payload["outdoor_source"], "chosen")
        self.assertIn("settings", payload["outdoor_why"])

    def test_a_choice_that_is_not_a_thermometer_is_said_and_ignored(self):
        settings_store.save({"thermal_outdoor": "sensor.gone"})
        chosen = thermal.choose_outdoor(self.states(), {"sensor.hall": "Hall"},
                                        override="sensor.gone")
        self.assertEqual(chosen["entity_id"], "sensor.outside")
        self.assertIn("sensor.gone", chosen["why"])

    def test_the_setting_takes_an_entity_id_and_nothing_else(self):
        with self.assertRaises(ValueError):
            settings_store.save({"thermal_outdoor": "the garden one"})
        self.assertIsNone(settings_store.save({"thermal_outdoor": ""})
                          ["thermal_outdoor"])
        self.assertIsNone(settings_store.load()["thermal_outdoor"])
        with open(self.settings, "w", encoding="utf-8") as fh:
            json.dump({"thermal_outdoor": "not an id"}, fh)
        self.assertIsNone(settings_store.load()["thermal_outdoor"])


class TestTheTabIsToldWhy(unittest.TestCase):

    def test_the_payload_carries_the_reference_its_reasons_and_the_choice(self):
        import server  # noqa: PLC0415 — the route's own shaping

        store = {"outdoor": "sensor.outside", "unit": "°C", "rooms": {},
                 "outdoor_source": "ranked",
                 "outdoor_why": "Outside (sensor.outside) is named as outdoors.",
                 "outdoor_candidates": [{"entity_id": "sensor.outside",
                                         "name": "Outside", "unit": "°C",
                                         "score": 3, "reasons": [],
                                         "ruled_out": "", "eligible": True}]}
        got = server._thermal_payload(store)
        self.assertEqual(got["outdoor_why"], store["outdoor_why"])
        self.assertEqual(got["outdoor_candidates"][0]["entity_id"],
                         "sensor.outside")
        self.assertIn("outdoor_choice", got)


if __name__ == "__main__":
    unittest.main()
