#!/usr/bin/env python3
"""The AMS Lite has no humidity sensor, so nothing may report one for it.

An A1 or A1 mini takes only the AMS Lite, which is open to the room and
carries no humidity or temperature sensor, yet the printer's report still
carries a `humidity` field per unit. Read as a reading, it put a "4/5" chip
on the panel, a number in what brAIn is told about the printer and a value
in Home Assistant. A real AMS (AMS, AMS 2 Pro, AMS HT) on an X1, P1 or H2
keeps its humidity and its temperature.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

protocol, client_mod = bambu_env.load("bambu.protocol", "bambu.client")


def report(**unit):
    base = {"id": "0", "humidity": "4", "temp": "27.5",
            "tray": [{"id": "0", "tray_type": "PLA", "tray_color": "FFFFFFFF"}]}
    base.update(unit)
    return {"print": {"gcode_state": "IDLE", "ams": {"ams": [base], "tray_now": "255"}}}


class TestAmsLite(unittest.TestCase):
    def test_an_a1_reports_no_humidity_and_no_temperature(self):
        for model in ("A1", "A1 mini"):
            with self.subTest(model=model):
                units = protocol.summarise(report(), model=model)["ams_units"]
                self.assertEqual(units, [{"id": 0, "humidity": None, "temp_c": None}])

    def test_a_real_ams_keeps_its_humidity_and_temperature(self):
        for model in ("X1C", "P1S", "H2D", "P2S"):
            with self.subTest(model=model):
                units = protocol.summarise(report(), model=model)["ams_units"]
                self.assertEqual(units, [{"id": 0, "humidity": 4, "temp_c": 27.5}])

    def test_a_report_that_says_ams_lite_is_believed_whatever_the_model(self):
        units = protocol.summarise(report(ams_type="AMS Lite"), model="")["ams_units"]
        self.assertIsNone(units[0]["humidity"])

    def test_the_trays_are_still_read_on_an_ams_lite(self):
        out = protocol.summarise(report(), model="A1")
        self.assertEqual([t["type"] for t in out["ams"]], ["PLA"])

    def test_the_client_knows_its_model_from_the_serial_when_nobody_said(self):
        client = client_mod.PrinterClient("10.0.0.9", "03919A000000001", "abcd1234")
        client.status = report()
        self.assertIsNone(client.summary()["ams_units"][0]["humidity"])
        client = client_mod.PrinterClient("10.0.0.9", "00M09A000000001", "abcd1234", model="X1C")
        client.status = report()
        self.assertEqual(client.summary()["ams_units"][0]["humidity"], 4)

    def test_the_serial_prefixes_are_the_ones_discovery_names_a1_by(self):
        discover, = bambu_env.load("discover")
        lite = {k for k, v in discover.MODEL_BY_PREFIX.items() if v in protocol.AMS_LITE_MODELS}
        self.assertEqual(lite, set(protocol.AMS_LITE_SERIALS))


if __name__ == "__main__":
    unittest.main()
