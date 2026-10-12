"""A washer whose meter is offline is not a house with no washer.

`select` dropped every power sensor that was unavailable right now, so a
house whose washer and dryer plugs were offline had them read by nothing,
and the summary said the machines it did measure were "none of them named
as a washer, dryer or dishwasher" — a sentence about the names that was
really about the plugs. A chore machine whose meter is offline is still
read from its history, keeps the profile an earlier pass measured when its
history no longer holds enough, and is counted and said in words.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import appliances  # noqa: E402
from test_appliances import NOW, FakeWS, a_week, series  # noqa: E402

ATTRS = {"device_class": "power", "state_class": "measurement"}


def states():
    return {
        "sensor.washer_power": {
            "state": "unavailable",
            "attributes": {**ATTRS, "friendly_name": "Washer power"}},
        "sensor.dryer_power": {
            "state": "unavailable",
            "attributes": {**ATTRS, "friendly_name": "Dryer power"}},
        "sensor.fridge_power": {
            "state": "3", "attributes": {**ATTRS, "friendly_name": "Fridge"}},
        "sensor.boiler_power": {
            "state": "0.6", "attributes": {**ATTRS, "friendly_name": "Boiler"}},
    }


class TestAnOfflineChoreMeter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "appliances.json")

    def run_build(self, rows, st=None):
        import ha_data
        fake = FakeWS(rows)
        real = ha_data._ws_commands
        ha_data._ws_commands = fake
        try:
            return asyncio.run(appliances.build(None, st or states(), NOW,
                                                self.path))
        finally:
            ha_data._ws_commands = real

    def test_select_keeps_a_named_machine_that_is_offline(self):
        chosen = appliances.select(states())
        self.assertIn("sensor.washer_power", chosen["ids"])
        self.assertIn("sensor.dryer_power", chosen["ids"])
        self.assertEqual(sorted(chosen["offline"]),
                         ["sensor.dryer_power", "sensor.washer_power"])

    def test_its_history_still_gives_it_a_profile(self):
        got = self.run_build({"sensor.washer_power": a_week(),
                              "sensor.boiler_power": a_week()})
        self.assertIn("sensor.washer_power", got["entities"])
        self.assertTrue(got["entities"]["sensor.washer_power"].get("offline"))

    def test_a_profile_from_earlier_history_is_kept(self):
        first = self.run_build({"sensor.washer_power": a_week(),
                                "sensor.boiler_power": a_week()})
        self.assertIn("sensor.washer_power", first["entities"])
        # Tonight the recorder holds too little for it to be measured again.
        got = self.run_build({"sensor.washer_power": series([(60, 0.0)], 3600),
                              "sensor.boiler_power": a_week()})
        self.assertIn("sensor.washer_power", got["entities"])
        self.assertTrue(got["entities"]["sensor.washer_power"].get("offline"))

    def test_the_summary_says_the_meters_are_offline(self):
        got = self.run_build({"sensor.boiler_power": a_week()})
        said = appliances.progress(got, now=NOW)["summary"]
        self.assertNotIn("none of them named as a washer", said)
        self.assertIn("2 washer, dryer or dishwasher meters are offline", said)

    def test_a_house_with_no_named_machine_still_says_so(self):
        st = states()
        del st["sensor.washer_power"], st["sensor.dryer_power"]
        got = self.run_build({"sensor.boiler_power": a_week()}, st)
        said = appliances.progress(got, now=NOW)["summary"]
        self.assertIn("none of them named as a washer", said)


if __name__ == "__main__":
    unittest.main()
