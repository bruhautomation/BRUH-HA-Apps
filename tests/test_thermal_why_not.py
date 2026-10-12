"""A room brAIn considered and could not measure says why.

A real house had one room of nine measured, and the store said nothing
about the other eight; asking for one of them by name answered only "no
measured room by that name" while that room had a thermometer of its own.
The nightly build now records, per room it considered, the reason it was
left out, and the route the `room_physics` tool reads carries that reason
on a row of its own, so the tool's answer for that room is the reason.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import thermal  # noqa: E402
from test_thermal import START, _build, simulate, state  # noqa: E402


def built() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        return asyncio.run(_build(*house(), path=os.path.join(tmp, "t.json")))


def house():
    room, out = simulate()
    flat_room = [{"start": START + i * 3600, "mean": 20.0}
                 for i in range(28 * 24)]
    states = {
        "sensor.garden": state("Outside", "4"),
        "sensor.hall": state("Hall", "20"),
        "sensor.study": state("Study", "20"),
        "sensor.attic": state("Attic", "20"),
        "sensor.cellar": state("Cellar", "68", unit="°F"),
    }
    areas = {"sensor.hall": "Hall", "sensor.study": "Study",
             "sensor.attic": "Attic", "sensor.cellar": "Cellar"}
    rows = {"sensor.garden": out, "sensor.hall": room,
            "sensor.study": room[:24 * 3],       # three days: too few nights
            "sensor.attic": flat_room}           # never moved: no fit
    return states, areas, rows


class TestTheStoreSaysWhyEachRoomWasLeftOut(unittest.TestCase):
    def setUp(self):
        self.payload = built()

    def test_the_measured_room_is_measured(self):
        self.assertIn("sensor.hall", self.payload["rooms"])
        self.assertNotIn("sensor.hall", self.payload.get("unmeasured", {}))

    def test_each_other_room_carries_its_reason(self):
        left = self.payload.get("unmeasured") or {}
        self.assertEqual(sorted(left),
                         ["sensor.attic", "sensor.cellar", "sensor.study"])
        self.assertIn("night", left["sensor.study"]["reason"])
        self.assertIn("°F", left["sensor.cellar"]["reason"])
        self.assertTrue(left["sensor.attic"]["reason"])
        self.assertEqual(left["sensor.study"]["area"], "Study")
        self.assertEqual(left["sensor.study"]["name"], "Study")

    def test_progress_carries_the_reasons(self):
        got = thermal.progress(self.payload, now=self.payload["built_at"])
        self.assertIn("sensor.study", got["detail"]["unmeasured"])


class TestTheRouteAndTheToolSayIt(unittest.TestCase):
    def test_the_tool_answers_a_considered_room_with_its_reason(self):
        import ha_mcp_server
        import server

        got = server._thermal_payload(built())
        study = [r for r in got["rooms"] if r["id"] == "sensor.study"]
        self.assertEqual(len(study), 1)
        self.assertFalse(study[0]["measured"])
        self.assertIsNone(study[0]["k"])
        measured = [r for r in got["rooms"] if r.get("measured")]
        self.assertEqual([r["id"] for r in measured], ["sensor.hall"])
        with patch.object(ha_mcp_server, "_panel_get", return_value=got):
            out = ha_mcp_server.room_physics("Study")
        self.assertEqual(len(out["rooms"]), 1)
        self.assertIn("night", out["rooms"][0]["why_not_measured"])


if __name__ == "__main__":
    unittest.main()
