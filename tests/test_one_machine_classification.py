#!/usr/bin/env python3
"""`dev.implausible` and `base.unusual` read ONE answer to "is this a machine".

Report 433: the impossible-readings check was still answered Wrong about a
printer's nozzle, its bed and a computer's processor after 3.8.6 read the
providing integration first. That fix held where the integration said so;
two paths still missed. The model's reading of an entity (`world_model`)
answered BEFORE the device's own evidence, so a printer bed published by a
bridge (MQTT, a template) on a device made by a printer maker was read as
room air whenever the model said so; and a SETPOINT — the temperature the
printer was asked for — was judged as a reading by `dev.implausible` while
`base.unusual` already stood it down. Both checks now ask one
classification: the integration, then the integrations on the same device,
then the device's names, and only then the entity's own words or a model's
reading; and a target is never a reading.
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import world_model  # noqa: E402
from checks import baseline, devices  # noqa: E402
from checks._util import House  # noqa: E402
from test_house_checks import NOW, house, iso  # noqa: E402
from test_implausible_hot_devices import implausible_ids, plant  # noqa: E402

LAB = {"id": "dev_lab_printer", "name": "Garage", "manufacturer": "Bambu Lab",
       "model": "A1"}
BOX = {"id": "dev_box", "name": "Attic server", "manufacturer": "Generic",
       "model": "x86"}


def unit(snap, eid, u):
    snap["states"][eid]["attributes"]["unit_of_measurement"] = u


def room_air(snap, eid):
    snap["world"] = {**(snap.get("world") or {}), eid: {
        "fp": "x", "confidence": 0.95, "priority": 0.0,
        "roles": {**world_model.DEFAULTS, "measures": "room_air"}}}


class TestTheDoneWhen(unittest.TestCase):
    def test_a_bruh_bambu_nozzle_at_220(self):
        snap = house()
        plant(snap, "sensor.garage_nozzle_temperature",
              "Garage Nozzle temperature", 220, platform="bruh_bambu",
              device=LAB)
        self.assertEqual(implausible_ids(snap), [])

    def test_a_nozzle_target_at_220(self):
        snap = house()
        plant(snap, "sensor.garage_nozzle_target_temperature",
              "Garage Nozzle target temperature", 220, platform="bambu_lab",
              device=LAB)
        self.assertEqual(implausible_ids(snap), [])

    def test_a_bed_at_65_reported_in_fahrenheit(self):
        snap = house()
        plant(snap, "sensor.garage_bed_temperature", "Garage Bed temperature",
              149, platform="bruh_bambu", device=LAB)
        unit(snap, "sensor.garage_bed_temperature", "°F")
        self.assertEqual(implausible_ids(snap), [])

    def test_a_system_monitor_processor_at_95(self):
        snap = house()
        plant(snap, "sensor.system_monitor_processor_temperature",
              "System Monitor Processor temperature", 95,
              platform="systemmonitor")
        self.assertEqual(implausible_ids(snap), [])

    def test_a_manifold_probe_that_read_impossible_still_files(self):
        snap = house()
        eid = "sensor.pump_manifold_probe"
        plant(snap, eid, "Pump manifold probe", -31.5, platform="esphome")
        unit(snap, eid, "°F")
        snap["baselines"] = {"entities": {eid: {"impossible": {
            "count": 4, "lowest": -150.0, "highest": -150.0,
            "last": NOW - 3600}}}}
        self.assertEqual(implausible_ids(snap), [eid])


class TestTheDeviceAnswersBeforeAModel(unittest.TestCase):
    def test_a_bridged_bed_on_a_printer_makers_device(self):
        """The issue's case in another shape: an MQTT bridge, and a model
        that read the bed as room air."""
        snap = house()
        eid = "sensor.garage_bed_temperature"
        plant(snap, eid, "Garage Bed temperature", 65, platform="mqtt",
              device=LAB)
        room_air(snap, eid)
        self.assertEqual(implausible_ids(snap), [])
        self.assertTrue(devices.printer_heater(House(snap), eid))

    def test_a_sensor_on_a_device_another_printer_entity_is_on(self):
        """No printer word anywhere on the device; its other entity comes
        from a printer integration, which is the device's own evidence."""
        snap = house()
        dev = {"id": "dev_plain", "name": "Workbench", "manufacturer": "",
               "model": ""}
        plant(snap, "sensor.workbench_plate", "Workbench plate", 70,
              platform="esphome", device=dev)
        snap["entities"].append({"entity_id": "sensor.workbench_status",
                                 "platform": "octoprint",
                                 "device_id": "dev_plain"})
        room_air(snap, "sensor.workbench_plate")
        self.assertEqual(implausible_ids(snap), [])

    def test_a_computer_device_beats_a_model_reading(self):
        snap = house()
        eid = "sensor.attic_server_cpu_temperature"
        plant(snap, eid, "Attic server CPU temperature", 95, platform="mqtt",
              device=BOX)
        room_air(snap, eid)
        self.assertEqual(implausible_ids(snap), [])
        self.assertTrue(devices.computer_temperature(House(snap), eid))

    def test_a_room_on_an_ordinary_device_still_listens_to_the_model(self):
        snap = house()
        eid = "sensor.study_temperature"
        plant(snap, eid, "Study temperature", 99, platform="zha",
              device={"id": "dev_s", "name": "Study sensor",
                      "manufacturer": "LUMI", "model": "weather"})
        room_air(snap, eid)
        self.assertEqual(implausible_ids(snap), [eid])


class TestASetpointIsNotAReading(unittest.TestCase):
    def test_a_target_on_an_ordinary_device(self):
        snap = house()
        eid = "sensor.shed_heater_target_temperature"
        plant(snap, eid, "Shed heater target temperature", 95,
              platform="mqtt",
              device={"id": "dev_h", "name": "Shed heater",
                      "manufacturer": "Generic", "model": ""})
        self.assertEqual(implausible_ids(snap), [])

    def test_a_set_point_written_as_two_words(self):
        snap = house()
        eid = "sensor.loft_set_point"
        plant(snap, eid, "Loft set point", 75, platform="mqtt")
        self.assertEqual(implausible_ids(snap), [])

    def test_both_checks_give_the_same_answer(self):
        snap = house()
        eid = "sensor.shed_heater_target_temperature"
        plant(snap, eid, "Shed heater target temperature", 95,
              platform="mqtt")
        h = House(snap)
        st = snap["states"][eid]
        self.assertTrue(devices.is_setpoint(h, eid, st))
        self.assertEqual(baseline.not_a_house_reading(h, eid, st),
                         "a setpoint somebody chose")

    def test_a_word_inside_another_word_is_not_a_setpoint(self):
        snap = house()
        eid = "sensor.targeted_hall"
        plant(snap, eid, "Targetedhall temperature", 99, platform="zha")
        self.assertFalse(devices.is_setpoint(House(snap), eid,
                                             snap["states"][eid]))
        self.assertIn(eid, implausible_ids(snap))


class TestAnEarlierRecordDoesNotReFile(unittest.TestCase):
    def test_a_record_a_pass_with_no_registry_left(self):
        """A night recorded by a pass that could not read the registries
        took a nozzle's 220 °C for impossible; read with the registries
        now, it is no record."""
        snap = house()
        eid = "sensor.garage_nozzle_temperature"
        plant(snap, eid, "Garage Nozzle temperature", 30,
              platform="bruh_bambu", device=LAB)
        snap["states"][eid]["last_updated"] = iso(120)
        snap["baselines"] = {"entities": {eid: {"impossible": {
            "count": 6, "lowest": 180.0, "highest": 221.0,
            "last": NOW - 3600}}}}
        self.assertEqual(implausible_ids(snap), [])


if __name__ == "__main__":
    unittest.main()
