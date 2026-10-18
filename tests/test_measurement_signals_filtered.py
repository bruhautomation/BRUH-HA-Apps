#!/usr/bin/env python3
"""A reading `base.unusual` would never file is not handed to the look either.

Reported from a house (devloop #300): `base.unusual` asks `should_report`
and drops what is not a reading of the house, but `server._measurement_signals`
offered EVERY out-of-band baseline reading to the Resident with none of
those filters and its raw entity id in the sentence — so a sensor the owner
had called normal, a phone's pressure in inHg and a heater's resistance in
Ω came back through the look. Driven through the real function with only
the band arithmetic and the hand-off stubbed.
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

NOW = 1_800_000_000.0


def _sensor(name, unit, klass=None):
    attrs = {"friendly_name": name, "unit_of_measurement": unit,
             "state_class": "measurement"}
    if klass:
        attrs["device_class"] = klass
    return {"state": "80", "attributes": attrs}


ROOM = "sensor.lounge_humidity"


def snapshot():
    states = {
        ROOM: _sensor("Lounge humidity", "%", "humidity"),
        "sensor.cupboard_humidity": _sensor("Cupboard humidity", "%",
                                            "humidity"),
        "sensor.phone_pressure": _sensor("Phone pressure", "inHg",
                                         "pressure"),
        "sensor.kiln_resistance": _sensor("Kiln element resistance", "Ω"),
        "sensor.heat_pump_coil": _sensor("Heat pump coil temperature", "°C",
                                         "temperature"),
    }
    entities = [{"entity_id": e, "platform": "zha"} for e in states]
    entities[2]["platform"] = "mobile_app"
    return {
        "states": states, "entities": entities, "devices": [], "areas": [],
        "baselines": {"entities": {e: {"unit": states[e]["attributes"][
            "unit_of_measurement"]} for e in states}},
        "corrections": {"entity": {"sensor.cupboard_humidity": {
            "base.unusual": {"text": "it is always damp", "until": ""}}},
            "area": {}, "check": {},
            "never": {"checks": [], "domains": [], "classes": [],
                      "protected": []}},
        "_trail": [],
    }


class TestTheLookIsOfferedWhatTheCheckWouldFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        s = self.server
        self.offered = []
        self._olds = (s._resident_offer_many, s.baselines.deviation,
                      s._signal_context)
        s.baselines.deviation = lambda value, baseline, bucket: {
            "value": value, "sigmas": 12.0, "median": 40.0, "spread": 1.0,
            "source": "hour"}
        s._signal_context = lambda: None

        def capture(rows, adapter, now, ctx):
            self.offered.extend(rows)
            return len(rows)

        s._resident_offer_many = capture

    def tearDown(self):
        s = self.server
        (s._resident_offer_many, s.baselines.deviation,
         s._signal_context) = self._olds

    def test_only_the_room_reading_is_offered_and_by_name(self):
        self.server._measurement_signals(snapshot(), NOW)
        self.assertEqual([r["entity_id"] for r in self.offered], [ROOM])
        text = self.offered[0]["text"]
        self.assertIn("Lounge humidity", text)
        self.assertNotIn(ROOM, text)


class TestNotAHouseReading(unittest.TestCase):
    def test_electrical_and_machine_readings_are_not_the_house(self):
        from checks import baseline
        from checks._util import House
        snap = snapshot()
        house = House(snap)
        for eid in ("sensor.kiln_resistance", "sensor.heat_pump_coil"):
            self.assertTrue(baseline.not_a_house_reading(
                house, eid, snap["states"][eid]), eid)
        self.assertFalse(baseline.not_a_house_reading(
            house, ROOM, snap["states"][ROOM]))


if __name__ == "__main__":
    unittest.main()
