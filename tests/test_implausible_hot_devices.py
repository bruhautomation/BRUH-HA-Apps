#!/usr/bin/env python3
"""`dev.implausible` and the readings that are a printer's or a computer's.

Report 373: the house marked `dev.implausible` Wrong 3 of 3 — a 3D
printer's nozzle, the same printer's bed, and a computer's processor
temperature, each filed as "a temperature sensor cannot read outside
-40–60 °C". They can; each measures a heater or a chip.

The name gate read only the entity's own words. A Bambu Lab printer's
readings are called "Bed temperature" under a DEVICE named after the
printer ("P1S", made by "Bambu Lab"), so the printer word that makes
`bed` hot was never seen; a non-English name ("Düsentemperatur") has no
English word at all; and a system monitor calls a CPU "Processor
temperature", a word the list did not have. The providing integration is
a fact rather than a guess — every temperature a printer integration or a
system monitor publishes is a heater's or a chip's — so it answers first,
and the device's own names are read beside the entity's.
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import baselines  # noqa: E402
import world_model  # noqa: E402
from checks import devices  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402


def plant(snap, eid, name, value, *, platform="", device=None):
    snap["states"][eid] = {
        "state": str(value), "last_updated": iso(60), "last_changed": iso(60),
        "attributes": {"device_class": "temperature",
                       "unit_of_measurement": "°C",
                       "state_class": "measurement",
                       "friendly_name": name}}
    row = {"entity_id": eid, "platform": platform}
    if device:
        snap["devices"].append(device)
        row["device_id"] = device["id"]
    snap["entities"].append(row)


P1S = {"id": "dev_p1s", "name": "P1S", "manufacturer": "Bambu Lab",
       "model": "P1S"}
NAS = {"id": "dev_nas", "name": "Glances nas", "manufacturer": "Glances",
       "model": ""}
PRUSA = {"id": "dev_prusa", "name": "Workshop", "manufacturer": "Prusa",
         "model": "MK4"}


def implausible_ids(snap):
    return [f["entity_id"] for f in devices.implausible(snap, NOW)]


class TestTheReportedThree(unittest.TestCase):
    def test_a_bambu_bed_whose_printer_word_is_on_the_device(self):
        snap = house()
        plant(snap, "sensor.p1s_bed_temperature", "P1S Bed temperature", 65,
              platform="bambu_lab", device=P1S)
        self.assertEqual(implausible_ids(snap), [])

    def test_a_bambu_bed_from_the_device_alone(self):
        """No printer platform at all (an MQTT bridge): the device's maker
        is the printer word."""
        snap = house()
        plant(snap, "sensor.p1s_bed_temperature", "P1S Bed temperature", 65,
              platform="mqtt", device=P1S)
        self.assertEqual(implausible_ids(snap), [])

    def test_a_nozzle_named_in_another_language(self):
        snap = house()
        plant(snap, "sensor.p1s_dusentemperatur", "P1S Düsentemperatur", 220,
              platform="bambu_lab", device=P1S)
        self.assertEqual(implausible_ids(snap), [])

    def test_a_processor_temperature(self):
        snap = house()
        plant(snap, "sensor.system_monitor_processor_temperature",
              "System Monitor Processor temperature", 85,
              platform="systemmonitor")
        # And by its words alone, with no registry row to read.
        snap["states"]["sensor.processor_temperature"] = {
            "state": "85", "last_updated": iso(60),
            "attributes": {"device_class": "temperature",
                           "unit_of_measurement": "°C",
                           "friendly_name": "Processor temperature"}}
        self.assertEqual(implausible_ids(snap), [])


class TestTwoTheReportDidNotMention(unittest.TestCase):
    def test_a_glances_package_temperature(self):
        snap = house()
        plant(snap, "sensor.nas_package_id_0_temperature",
              "nas Package id 0 temperature", 85, platform="glances",
              device=NAS)
        self.assertEqual(implausible_ids(snap), [])

    def test_an_octoprint_tool_temperature(self):
        snap = house()
        plant(snap, "sensor.octoprint_actual_tool0_temp",
              "OctoPrint actual tool0 temp", 210, platform="octoprint")
        # A Prusa on PrusaLink, its printer word only on the device.
        plant(snap, "sensor.workshop_temp_bed", "Workshop Temp bed", 60.5,
              platform="prusalink", device=PRUSA)
        self.assertEqual(implausible_ids(snap), [])


class TestARoomIsStillARoom(unittest.TestCase):
    def test_a_room_thermometer_at_99_is_still_impossible(self):
        snap = house()
        snap["states"]["sensor.hall_temp"]["state"] = "99"
        self.assertEqual(implausible_ids(snap), ["sensor.hall_temp"])

    def test_a_bedroom_on_an_ordinary_device_is_a_room(self):
        snap = house()
        plant(snap, "sensor.bedroom_temperature", "Bedroom temperature", 99,
              platform="zha",
              device={"id": "dev_b", "name": "Bedroom sensor",
                      "manufacturer": "LUMI", "model": "lumi.weather"})
        self.assertIn("sensor.bedroom_temperature", implausible_ids(snap))

    def test_a_radiator_valve_reads_its_room(self):
        """A device's name is read more narrowly than the entity's: a
        thermostatic radiator valve's temperature is the room's."""
        snap = house()
        plant(snap, "sensor.lounge_temperature", "Lounge temperature", 99,
              platform="zha",
              device={"id": "dev_trv", "name": "Lounge radiator valve",
                      "manufacturer": "Danfoss", "model": "eTRV0100"})
        self.assertIn("sensor.lounge_temperature", implausible_ids(snap))

    def test_a_printer_reading_below_the_cold_floor_is_still_impossible(self):
        """3.8.3's floor: a heater may read far above room air, never
        below the coldest air on earth."""
        snap = house()
        plant(snap, "sensor.p1s_bed_temperature", "P1S Bed temperature", -150,
              platform="bambu_lab", device=P1S)
        self.assertEqual(implausible_ids(snap), ["sensor.p1s_bed_temperature"])


class TestEveryReaderAgrees(unittest.TestCase):
    def snap(self):
        snap = house()
        plant(snap, "sensor.p1s_bed_temperature", "P1S Bed temperature", 65,
              platform="bambu_lab", device=P1S)
        return snap

    def test_the_platform_answers_before_a_reading_of_room_air(self):
        snap = self.snap()
        world = {"sensor.p1s_bed_temperature": {
            "fp": "x", "confidence": 0.9, "priority": 0.0,
            "roles": {**world_model.DEFAULTS, "measures": "room_air"}}}
        self.assertTrue(devices.measures_something_hot(
            "sensor.p1s_bed_temperature", "P1S Bed temperature", world,
            House(snap)))

    def test_base_unusual_reads_the_same_question(self):
        snap = self.snap()
        st = snap["states"]["sensor.p1s_bed_temperature"]
        self.assertFalse(devices.out_of_range(
            st, "sensor.p1s_bed_temperature", None, House(snap)))

    def test_the_nightly_pass_keeps_a_hot_bed_in_its_baseline(self):
        snap = self.snap()
        attrs = snap["states"]["sensor.p1s_bed_temperature"]["attributes"]
        series = [{"start": NOW - i * 3600, "mean": 65.0} for i in range(24)]
        kept, dropped = baselines._without_impossible(
            series, attrs, "sensor.p1s_bed_temperature", devices,
            House({"entities": snap["entities"], "devices": snap["devices"]}))
        self.assertEqual(len(kept), 24)
        self.assertIsNone(dropped)


if __name__ == "__main__":
    unittest.main()
