#!/usr/bin/env python3
"""What an A1's report says that is not a measurement is not shown as one.

An A1 has no chamber sensor (its report still carries a chamber temperature,
a room-ish number) and its AMS Lite cannot measure what is left on a spool
(every tray reports 100). Both must read as unknown. noVNC's page also asks
for its package.json, which the distro's copy lacks: the panel answers it.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402
from test_bambu_panel import RouteTest  # noqa: E402

protocol, = bambu_env.load("bambu.protocol")


def report(chamber="5", remain=100):
    return {"print": {"gcode_state": "IDLE", "chamber_temper": chamber,
                      "ams": {"ams": [{"id": "0", "tray": [
                          {"id": "0", "tray_type": "PLA", "remain": remain}]}], "tray_now": "255"},
                      "vt_tray": {"tray_type": "PETG", "remain": 55}}}


class TestWhatAnA1CannotMeasure(unittest.TestCase):
    def test_no_chamber_temperature_for_an_a1(self):
        for model in ("A1", "A1 mini"):
            self.assertIsNone(protocol.summarise(report(), model=model)["chamber_c"], model)
        self.assertEqual(protocol.summarise(report(), model="X1C")["chamber_c"], 5.0)

    def test_an_ams_lite_tray_has_no_remaining_figure(self):
        lite = protocol.summarise(report(), model="A1")
        self.assertIsNone(lite["ams"][0]["remaining"])
        real = protocol.summarise(report(), model="X1C")
        self.assertEqual(real["ams"][0]["remaining"], 100)

    def test_the_external_spool_is_left_alone(self):
        self.assertEqual(protocol.summarise(report(), model="A1")["external_spool"]["remaining"], 55)


class TestNoVncPackageJson(RouteTest):
    def test_the_page_asks_for_package_json_and_gets_an_answer(self):
        async def go():
            resp = await self.http.request("GET", "/novnc/package.json")
            return resp.status
        self.assertEqual(self.loop.run_until_complete(go()), 200)
