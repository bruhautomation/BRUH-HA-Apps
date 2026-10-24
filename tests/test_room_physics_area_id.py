#!/usr/bin/env python3
"""`room_physics` finds a room by its area id, its name or an alias, and
lists each area once.

The tool's description says it takes "the area name or id", and it matched
only the display name: asked for `crawl_space` it answered "no measured
room by that name", and its `known_rooms` repeated a room once per
thermometer in it. The panel's thermal route now carries each room's area
id and aliases (off the registry the last checks pass read), and the tool
matches all three.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "panel"))

import ha_mcp_server  # noqa: E402

ROOM = {"k": 0.1, "tau_h": 10.0, "gain": 1.0, "warmest": 20.0,
        "coolest": 15.0}


def store() -> dict:
    return {"outdoor": "sensor.outside", "unit": "°C", "coldest": 2.0,
            "rooms": {
                "sensor.under_floor_a": dict(ROOM, name="Under floor A",
                                             area="Under floor"),
                "sensor.under_floor_b": dict(ROOM, name="Under floor B",
                                             area="Under floor"),
                "sensor.den_temp": dict(ROOM, name="Den temp",
                                        area="Family room"),
            }}


class Case(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self._ctx = dict(server._FACTS_CTX)
        server._FACTS_CTX.update(
            areas={"under_floor": "Under floor", "family_room": "Family room"},
            entity_areas={"sensor.under_floor_a": "under_floor",
                          "sensor.under_floor_b": "under_floor",
                          "sensor.den_temp": "family_room"},
            area_aliases={"family_room": ["Den", "Snug"]})

    def tearDown(self):
        self.server._FACTS_CTX.clear()
        self.server._FACTS_CTX.update(self._ctx)

    def ask(self, area):
        payload = self.server._thermal_payload(store())
        with patch.object(ha_mcp_server, "_panel_get", return_value=payload):
            return ha_mcp_server.room_physics(area)


class TestOneRoomThreeWays(Case):
    def ids(self, area):
        return sorted(r["id"] for r in self.ask(area)["rooms"])

    def test_the_id_the_name_and_an_alias_are_one_answer(self):
        by_name = self.ids("Under floor")
        self.assertEqual(by_name, ["sensor.under_floor_a", "sensor.under_floor_b"])
        self.assertEqual(self.ids("under_floor"), by_name)
        self.assertEqual(self.ids("UNDER_FLOOR"), by_name)

    def test_a_second_room_by_its_alias(self):
        self.assertEqual(self.ids("den"), ["sensor.den_temp"])
        self.assertEqual(self.ids("Snug"), ["sensor.den_temp"])
        self.assertEqual(self.ids("family_room"), ["sensor.den_temp"])

    def test_known_rooms_lists_each_area_once(self):
        out = self.ask("cellar")
        self.assertEqual(out["rooms"], [])
        self.assertEqual(sorted(out["known_rooms"]), ["Family room", "Under floor"])


if __name__ == "__main__":
    unittest.main()
