#!/usr/bin/env python3
"""What BRUH Bambu Studio says to a Bambu printer, and how it reads the reply.

The shapes are the printer's own (`device/<serial>/request` and `/report`),
so each command is asserted as the JSON a printer reads, and each report as
a delta merged into the status a P1 or A1 actually builds up — the last
report alone is a printer whose nozzle temperature disappears the moment its
bed warms up.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

protocol, = bambu_env.load("bambu.protocol")


class TestCommands(unittest.TestCase):
    def test_each_request_carries_the_sequence_id_the_printer_echoes(self):
        body = json.loads(protocol.request(protocol.simple("pause"), 42))
        self.assertEqual(body, {"print": {"command": "pause", "param": "",
                                          "sequence_id": "42"}})

    def test_pause_resume_stop_and_nothing_else_are_simple(self):
        for word in ("pause", "resume", "stop"):
            self.assertEqual(protocol.simple(word)["print"]["command"], word)
        with self.assertRaises(ValueError):
            protocol.simple("home")

    def test_speed_takes_the_names_bambu_studio_shows(self):
        self.assertEqual(protocol.speed("sport")["print"],
                         {"command": "print_speed", "param": "3"})
        self.assertEqual(protocol.speed("1")["print"]["param"], "1")
        with self.assertRaises(ValueError):
            protocol.speed("warp")

    def test_the_light_is_the_chamber_light(self):
        system = protocol.light(True)["system"]
        self.assertEqual((system["command"], system["led_node"], system["led_mode"]),
                         ("ledctrl", "chamber_light", "on"))
        self.assertEqual(protocol.light(False)["system"]["led_mode"], "off")

    def test_gcode_is_checked_before_it_reaches_a_hot_end(self):
        self.assertEqual(protocol.gcode("g28\nM104 S200")["print"]["param"],
                         "G28\nM104 S200\n")
        for bad in ("", "rm -rf /", "M104 S200; ok\nhello", "\n".join(["G28"] * 40),
                    "G1 X10 ©"):
            with self.subTest(bad=bad[:20]), self.assertRaises(ValueError):
                protocol.gcode(bad)

    def test_a_temperature_out_of_range_is_refused_not_clamped(self):
        self.assertEqual(protocol.temperature("bed", 60)["print"]["param"], "M140 S60\n")
        self.assertEqual(protocol.temperature("nozzle", "215.4")["print"]["param"],
                         "M104 S215\n")
        for target, value in (("bed", 600), ("nozzle", 400), ("bed", -1),
                              ("chamber", 40), ("bed", "hot")):
            with self.subTest(target=target, value=value), self.assertRaises(ValueError):
                protocol.temperature(target, value)

    def test_a_print_names_the_plate_inside_the_archive_and_the_archive_as_url(self):
        body = protocol.project_file("benchy.gcode.3mf", 2, use_ams=True,
                                     ams_mapping=[0, 3], timelapse=False,
                                     bed_leveling=True, flow_cali=False,
                                     vibration_cali=True)["print"]
        self.assertEqual(body["command"], "project_file")
        self.assertEqual(body["param"], "Metadata/plate_2.gcode")
        self.assertEqual(body["url"], "file:///sdcard/benchy.gcode.3mf")
        self.assertEqual(body["subtask_name"], "benchy")
        self.assertEqual(body["ams_mapping"], [0, 3])
        self.assertIs(body["use_ams"], True)
        self.assertEqual(protocol.project_file("x.3mf", 0, use_ams=False, ams_mapping=None,
                                               timelapse=False, bed_leveling=False,
                                               flow_cali=False, vibration_cali=False)
                         ["print"]["param"], "Metadata/plate_1.gcode")


class TestReports(unittest.TestCase):
    FULL = {"print": {"gcode_state": "RUNNING", "mc_percent": 41,
                      "mc_remaining_time": 75, "layer_num": 80, "total_layer_num": 200,
                      "subtask_name": "benchy", "nozzle_temper": 219.6,
                      "nozzle_target_temper": 220, "bed_temper": 55.1,
                      "bed_target_temper": 55, "spd_lvl": 2,
                      "lights_report": [{"node": "chamber_light", "mode": "on"}],
                      "ams": {"ams": [{"id": "0", "tray": [
                          {"id": "0", "tray_type": "PLA", "tray_color": "FF0000FF", "remain": 80},
                          {"id": "1"}]}]},
                      "hms": [{"attr": 1, "code": 2}]}}

    def test_a_full_report_reads_as_what_a_person_wants(self):
        out = protocol.summarise(self.FULL)
        self.assertEqual(out["state"], "running")
        self.assertTrue(out["printing"])
        self.assertEqual((out["progress"], out["remaining_min"]), (41, 75))
        self.assertEqual((out["nozzle_c"], out["bed_target_c"]), (219.6, 55.0))
        self.assertEqual(out["speed"], "standard")
        self.assertIs(out["chamber_light"], True)
        self.assertEqual(out["ams"], [{"slot": 0, "type": "PLA", "name": None,
                                       "colour": "#FF0000", "remaining": 80,
                                       "nozzle_min_c": None, "nozzle_max_c": None}])
        self.assertEqual(out["hms_count"], 1)

    def test_a_delta_keeps_everything_it_did_not_mention(self):
        status = json.loads(json.dumps(self.FULL))
        protocol.deep_merge(status, {"print": {"bed_temper": 60.0, "mc_percent": 42}})
        out = protocol.summarise(status)
        self.assertEqual((out["bed_c"], out["progress"], out["nozzle_c"]), (60.0, 42, 219.6))

    def test_nothing_reported_is_none_never_zero(self):
        out = protocol.summarise({})
        self.assertIsNone(out["state"])
        self.assertIsNone(out["nozzle_c"])
        self.assertIsNone(out["progress"])
        self.assertFalse(out["printing"])

    def test_a_state_we_have_not_heard_of_is_passed_through(self):
        self.assertEqual(protocol.summarise({"print": {"gcode_state": "CALIBRATING"}})
                         ["state"], "calibrating")


if __name__ == "__main__":
    unittest.main()
