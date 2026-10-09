#!/usr/bin/env python3
"""Seven things the house checks got wrong about a real house.

Each case drives the real check against the shape that was reported,
then asserts the healthy neighbour of that shape is still reported —
a fix that silences the check outright is not a fix.

1. ``dev.unavailable`` filed a light group AND each of its member lights
   when they all went at once: three serious rows for one fault, and the
   group's row pointing at the group helper rather than the members.
2. ``dev.unavailable`` was answered "not a problem" four times out of
   four: an integration that did not set up (``sys.entry_failed``'s row),
   an entity somebody hid, and a device whose one diagnostic entity was
   unavailable while the device itself answered.
3. ``dev.frozen`` called a battery's 0.1 V-resolution voltage stuck.
4. ``base.unusual`` reported space weather against the hour of the week.
5. ``base.unusual``'s fix was one template on every row.
6. ``sys.entry_failed`` pasted an HTML error page into a sentence, with no
   way to tell whose error was whose.
7. The thermal model said "ready" about one room measured against a
   forecast model while the house's own outdoor sensor was unavailable.

Generic fixture names only.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import thermal  # noqa: E402
from checks import baseline, devices, system  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402

LONG_AGO = 3 * DAY


def _gone(snap: dict, eid: str, **attrs) -> None:
    snap["states"][eid] = {"state": "unavailable", "attributes": attrs,
                           "last_changed": iso(LONG_AGO)}


# ---------------------------------------------------------------------------
# 1. A group whose members are all down is the members' fault
# ---------------------------------------------------------------------------

class TestAGroupIsNotItsOwnFault(unittest.TestCase):

    def _lounge(self) -> dict:
        snap = house()
        for i in (1, 2):
            eid = f"light.lounge_lamp_{i}"
            _gone(snap, eid, friendly_name=f"Lounge lamp {i}")
            snap["entities"].append({"entity_id": eid, "platform": "zha",
                                     "device_id": f"dev-lamp-{i}"})
            snap["devices"].append({"id": f"dev-lamp-{i}",
                                    "name": f"Lounge lamp {i}"})
        snap["entities"].append({"entity_id": "light.lounge_lamps",
                                 "platform": "group",
                                 "config_entry_id": "e-group"})
        return snap

    def test_a_group_whose_members_are_all_down_files_no_row_of_its_own(self):
        snap = self._lounge()
        _gone(snap, "light.lounge_lamps", friendly_name="Lounge lamps",
              entity_id=["light.lounge_lamp_1", "light.lounge_lamp_2"])
        found = devices.unavailable(snap, NOW)
        self.assertEqual(sorted(f["entity_id"] for f in found),
                         ["light.lounge_lamp_1", "light.lounge_lamp_2"])

    def test_an_unavailable_group_carries_no_member_list_and_is_still_folded(self):
        """Core drops a group's `entity_id` attribute while it is
        unavailable, so the members cannot always be read off the state."""
        snap = self._lounge()
        _gone(snap, "light.lounge_lamps", friendly_name="Lounge lamps")
        found = devices.unavailable(snap, NOW)
        self.assertNotIn("light.lounge_lamps",
                         [f["entity_id"] for f in found])

    def test_a_group_whose_members_are_fine_is_still_reported(self):
        snap = self._lounge()
        for i in (1, 2):
            snap["states"][f"light.lounge_lamp_{i}"]["state"] = "on"
        _gone(snap, "light.lounge_lamps", friendly_name="Lounge lamps",
              entity_id=["light.lounge_lamp_1", "light.lounge_old"])
        found = devices.unavailable(snap, NOW)
        self.assertEqual([f["entity_id"] for f in found], ["light.lounge_lamps"])
        # And the fix is about the members, not about batteries.
        self.assertIn("light.lounge_old", found[0]["fix"])
        self.assertNotIn("reload its integration", found[0]["fix"])


# ---------------------------------------------------------------------------
# 2. What else made the homeowner say "not a problem"
# ---------------------------------------------------------------------------

class TestUnavailableOnAHealthyHouse(unittest.TestCase):

    def test_an_integration_that_did_not_set_up_is_sys_entry_failed_s_row(self):
        snap = house()
        _gone(snap, "sensor.porch_temp", friendly_name="Porch temperature")
        snap["entities"].append({"entity_id": "sensor.porch_temp",
                                 "platform": "netatmo",
                                 "config_entry_id": "e-net",
                                 "device_id": "dev-porch"})
        snap["devices"].append({"id": "dev-porch", "name": "Porch station"})
        snap["config_entries"].append(
            {"entry_id": "e-net", "domain": "netatmo", "title": "Netatmo",
             "state": "setup_retry", "source": "user"})
        self.assertEqual(devices.unavailable(snap, NOW), [])
        # Loaded, the same entity is a device that went away.
        snap["config_entries"][-1]["state"] = "loaded"
        self.assertEqual(len(devices.unavailable(snap, NOW)), 1)

    def test_an_entity_somebody_hid_is_not_reported(self):
        snap = house()
        _gone(snap, "light.kitchen")
        for row in snap["entities"]:
            if row["entity_id"] == "light.kitchen":
                row["hidden_by"] = "user"
        self.assertEqual(devices.unavailable(snap, NOW), [])

    def test_a_diagnostic_entity_on_a_device_that_answers_is_not_the_device(self):
        snap = house()
        _gone(snap, "sensor.hall_climate_cloud", friendly_name="Cloud")
        snap["entities"].append({"entity_id": "sensor.hall_climate_cloud",
                                 "platform": "zha", "device_id": "dev-temp-1",
                                 "entity_category": "diagnostic"})
        self.assertEqual(devices.unavailable(snap, NOW), [])

    def test_one_primary_entity_down_on_a_device_that_answers_is_named(self):
        snap = house()
        _gone(snap, "sensor.hall_probe", friendly_name="Hall probe")
        snap["entities"].append({"entity_id": "sensor.hall_probe",
                                 "platform": "zha", "device_id": "dev-temp-1"})
        found = devices.unavailable(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Hall probe", found[0]["text"])
        self.assertNotIn("batteries", found[0]["fix"])

    def test_a_whole_device_gone_is_still_reported_as_the_device(self):
        snap = house()
        _gone(snap, "light.kitchen")
        found = devices.unavailable(snap, NOW)
        self.assertEqual(found[0]["text"],
                         "Hue bulb has been unavailable for more than a day")


# ---------------------------------------------------------------------------
# 3. A battery's voltage sits still
# ---------------------------------------------------------------------------

def _week(value: float) -> list[dict]:
    return [{"start": NOW - d * DAY, "mean": value, "min": value,
             "max": value} for d in range(7)]


class TestABatteryVoltageIsNotFrozen(unittest.TestCase):

    def _gateway(self) -> dict:
        snap = house()
        snap["devices"].append({"id": "dev-gw", "name": "Gateway"})
        for i in (1, 2):
            eid = f"sensor.leak_{i}_voltage"
            snap["states"][eid] = {
                "state": "1.3",
                "attributes": {"friendly_name": f"Leak {i} voltage",
                               "device_class": "voltage",
                               "unit_of_measurement": "V",
                               "state_class": "measurement"},
                "last_changed": iso(20 * DAY)}
            snap["entities"].append({"entity_id": eid, "platform": "gw",
                                     "device_id": "dev-gw"})
            snap["stats"][eid] = _week(1.3)
        return snap

    def test_neither_sibling_is_filed(self):
        found = devices.frozen(self._gateway(), NOW)
        self.assertEqual([f["entity_id"] for f in found], [])

    def test_a_mains_voltage_stuck_for_a_week_is_still_filed(self):
        snap = house()
        snap["states"]["sensor.mains_voltage"] = {
            "state": "231.4",
            "attributes": {"friendly_name": "Mains voltage",
                           "device_class": "voltage",
                           "unit_of_measurement": "V",
                           "state_class": "measurement"},
            "last_changed": iso(20 * DAY)}
        snap["stats"]["sensor.mains_voltage"] = _week(231.4)
        found = devices.frozen(snap, NOW)
        self.assertEqual([f["entity_id"] for f in found],
                         ["sensor.mains_voltage"])

    def test_a_voltage_named_for_a_battery_is_skipped_whatever_it_reads(self):
        snap = house()
        snap["states"]["sensor.ups_battery_voltage"] = {
            "state": "26.8",
            "attributes": {"friendly_name": "UPS battery voltage",
                           "device_class": "voltage",
                           "unit_of_measurement": "V",
                           "state_class": "measurement"},
            "last_changed": iso(20 * DAY)}
        snap["stats"]["sensor.ups_battery_voltage"] = _week(26.8)
        self.assertEqual(devices.frozen(snap, NOW), [])


# ---------------------------------------------------------------------------
# 4. Space weather is not the house
# ---------------------------------------------------------------------------

def _unusual_house(eid: str, platform: str, value: str, **reg) -> dict:
    snap = house()
    snap["states"][eid] = {
        "state": value,
        "attributes": {"friendly_name": "Solar flux", "state_class": "measurement",
                       "unit_of_measurement": "sfu"},
        "last_changed": iso(60)}
    snap["entities"].append({"entity_id": eid, "platform": platform, **reg})
    snap["baselines"]["entities"][eid] = {
        "unit": "sfu", "samples": 672,
        "overall": {"median": 100.0, "spread": 2.0, "n": 672},
        "buckets": {str(h): {"median": 100.0, "spread": 2.0, "n": 4}
                    for h in range(168)}}
    return snap


class TestSpaceWeatherIsOutside(unittest.TestCase):

    def test_noaa_space_weather_is_not_a_house_reading(self):
        snap = _unusual_house("sensor.solar_flux", "noaa_space_weather", "180")
        self.assertEqual(baseline.unusual(snap, NOW), [])

    def test_an_entity_labelled_weather_is_not_a_house_reading(self):
        snap = _unusual_house("sensor.solar_flux", "rest", "180",
                              labels=["weather"])
        self.assertEqual(baseline.unusual(snap, NOW), [])

    def test_the_same_reading_from_a_house_integration_is_reported(self):
        snap = _unusual_house("sensor.solar_flux", "rest", "180")
        self.assertEqual(len(baseline.unusual(snap, NOW)), 1)


# ---------------------------------------------------------------------------
# 5. The fix names what in the room could have moved it
# ---------------------------------------------------------------------------

class TestTheFixNamesWhatIsNearby(unittest.TestCase):

    def _humid(self) -> dict:
        snap = house()
        eid = "sensor.basement_humidity"
        snap["states"][eid] = {
            "state": "85", "attributes": {
                "friendly_name": "Basement humidity", "device_class": "humidity",
                "unit_of_measurement": "%", "state_class": "measurement"},
            "last_changed": iso(60)}
        snap["entities"].append({"entity_id": eid, "platform": "zha",
                                 "area_id": "basement"})
        snap["areas"].append({"area_id": "basement", "name": "Basement"})
        snap["baselines"]["entities"][eid] = {
            "unit": "%", "samples": 672,
            "overall": {"median": 50.0, "spread": 2.0, "n": 672},
            "buckets": {str(h): {"median": 50.0, "spread": 2.0, "n": 4}
                        for h in range(168)}}
        return snap

    def test_a_dehumidifier_in_the_same_room_is_named(self):
        snap = self._humid()
        snap["states"]["switch.basement_dehumidifier"] = {
            "state": "off", "attributes": {"friendly_name": "Dehumidifier"},
            "last_changed": iso(DAY)}
        snap["entities"].append({"entity_id": "switch.basement_dehumidifier",
                                 "platform": "tplink", "area_id": "basement"})
        found = baseline.unusual(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Dehumidifier", found[0]["fix"])
        self.assertEqual(found[0]["text"],
                         "Basement humidity is reading far outside its usual range")

    def test_with_nothing_related_in_the_room_the_fix_is_the_generic_one(self):
        found = baseline.unusual(self._humid(), NOW)
        self.assertIn("Look at what it is measuring", found[0]["fix"])
        self.assertNotIn("Dehumidifier", found[0]["fix"])

    def test_a_thermometer_in_another_room_is_not_named(self):
        snap = self._humid()
        snap["states"]["switch.kitchen_dehumidifier"] = {
            "state": "off", "attributes": {"friendly_name": "Kitchen dehumidifier"},
            "last_changed": iso(DAY)}
        snap["entities"].append({"entity_id": "switch.kitchen_dehumidifier",
                                 "platform": "tplink", "area_id": "kitchen"})
        found = baseline.unusual(snap, NOW)
        self.assertNotIn("Kitchen dehumidifier", found[0]["fix"])


# ---------------------------------------------------------------------------
# 6. An integration's error is a sentence, and it says whose it is
# ---------------------------------------------------------------------------

class TestEntryFailedSaysWhoseErrorItIs(unittest.TestCase):

    def test_an_html_error_page_becomes_its_status_and_errors_are_paired(self):
        snap = house(config_entries=[
            {"entry_id": "a1", "domain": "cloudthing", "title": "Cloud thing",
             "state": "setup_retry", "source": "user",
             "reason": "Error on retrieving data: <!doctype html><html><head>"
                       "<meta charset=utf-8><title>403</titl"},
            {"entry_id": "a2", "domain": "hub", "title": "Garage hub",
             "state": "setup_error", "source": "user",
             "reason": "Connection refused"},
        ])
        found = system.entry_failed(snap, NOW)
        detail = found[0]["detail"]
        self.assertNotIn("<", detail)
        self.assertIn("Cloud thing (cloudthing): Error on retrieving data: "
                      "HTTP 403", detail)
        self.assertIn("Garage hub (hub): Connection refused", detail)

    def test_reason_cleaning(self):
        clean = system.clean_reason
        self.assertEqual(clean("<html><body><h1>Bad Gateway</h1></body>"),
                         "an HTML error page")
        self.assertEqual(clean("Timeout <b>talking</b> to it"),
                         "Timeout talking to it")
        self.assertEqual(clean("plain words"), "plain words")


# ---------------------------------------------------------------------------
# 7. A thermal model against a forecast says so
# ---------------------------------------------------------------------------

def _temp(name: str, value: str) -> dict:
    return {"state": value, "attributes": {
        "friendly_name": name, "device_class": "temperature",
        "unit_of_measurement": "°C", "state_class": "measurement"}}


class TestTheThermalModelSaysWhatItIsMeasuredAgainst(unittest.TestCase):

    def _house(self):
        states = {
            "sensor.astroweather_2m_temperature": _temp("2m temperature", "6"),
            "sensor.station_outdoor_temperature":
                _temp("Station outdoor temperature", "unavailable"),
            "weather.astroweather": {"state": "cloudy", "attributes": {
                "temperature": 6.0, "temperature_unit": "°C"}},
        }
        entities = [
            {"entity_id": "sensor.astroweather_2m_temperature",
             "platform": "astroweather"},
            {"entity_id": "weather.astroweather", "platform": "astroweather"},
            {"entity_id": "sensor.station_outdoor_temperature",
             "platform": "ecowitt"},
        ]
        return states, entities

    def test_the_why_says_it_is_a_model_and_the_station_is_unavailable(self):
        states, entities = self._house()
        chosen = thermal.choose_outdoor(states, {}, entities)
        self.assertEqual(chosen["entity_id"],
                         "sensor.astroweather_2m_temperature")
        self.assertTrue(chosen["modelled"])
        self.assertIn("forecast", chosen["why"])
        self.assertEqual(chosen["unavailable"],
                         ["sensor.station_outdoor_temperature"])
        self.assertIn("sensor.station_outdoor_temperature", chosen["why"])

    def test_a_measured_reference_carries_no_caveat(self):
        states = {"sensor.outside": _temp("Outside", "4")}
        chosen = thermal.choose_outdoor(states, {})
        self.assertFalse(chosen["modelled"])
        self.assertEqual(chosen["unavailable"], [])
        self.assertNotIn("forecast", chosen["why"])

    def test_the_build_records_it(self):
        from test_thermal import simulate  # noqa: PLC0415

        states, entities = self._house()
        states["sensor.bedroom"] = _temp("Bedroom", "19")
        states["sensor.study"] = _temp("Study", "19")
        room, out = simulate()
        registries = {
            "areas": [{"area_id": "bedroom", "name": "Bedroom"},
                      {"area_id": "study", "name": "Study"}],
            "devices": [],
            "entities": entities + [
                {"entity_id": "sensor.bedroom", "area_id": "bedroom"},
                {"entity_id": "sensor.study", "area_id": "study"}]}
        rows = {"sensor.astroweather_2m_temperature": out,
                "sensor.bedroom": room}
        original = thermal.fetch_hourly

        async def fake(session, ids, now, days=thermal.HISTORY_DAYS):
            return {i: rows.get(i, []) for i in ids}

        thermal.fetch_hourly = fake
        try:
            payload = asyncio.run(thermal.build(None, states, registries,
                                                NOW, "/nonexistent/t.json"))
        finally:
            thermal.fetch_hourly = original
        self.assertTrue(payload["outdoor_modelled"])
        self.assertEqual(payload["outdoor_unavailable"],
                         ["sensor.station_outdoor_temperature"])
        self.assertIn("forecast", payload["outdoor_why"])
        progress = thermal.progress(payload, now=NOW)
        self.assertIn("1 of 2 rooms", progress["summary"])
        self.assertIn("forecast", progress["summary"])
        self.assertIn("unavailable", progress["summary"])


if __name__ == "__main__":
    unittest.main()
