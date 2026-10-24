#!/usr/bin/env python3
"""A device unavailable all week is reported even when Core restarted.

Home Assistant re-stamps `last_changed` on every entity when it starts, so
a device that went offline on Monday and has stayed offline through two
restarts reads, from its live state, as unavailable for an hour.
`dev.unavailable` measured "for more than a day" off that stamp alone and
said nothing about a fan controller whose every entity had been gone for
the whole week the recorder held. The checks pass now asks the recorder,
for the entities that are unavailable and look young, when the current
stretch of being unavailable began; the check ages a row from that.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import devices, snapshot  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402

RESTART = 2 * 3600          # Core started two hours ago


def row(eid: str, state: str, seconds_ago: float) -> dict:
    return {"entity_id": eid, "state": state, "last_changed": iso(seconds_ago)}


def fan_controller(snap: dict, *, n: int = 3) -> list[str]:
    ids = []
    for i in range(n):
        eid = f"fan.controller_{i}" if i == 0 else f"sensor.controller_{i}"
        snap["states"][eid] = {"state": "unavailable",
                               "attributes": {"friendly_name": f"Controller {i}"},
                               "last_changed": iso(RESTART)}
        snap["entities"].append({"entity_id": eid, "platform": "esphome",
                                 "device_id": "dev-fan",
                                 "config_entry_id": "e-esphome"})
        ids.append(eid)
    snap["devices"].append({"id": "dev-fan", "name": "Fan controller"})
    return ids


class TestTheStretchIsReadFromHistory(unittest.TestCase):
    def test_a_device_gone_all_week_across_restarts_is_reported(self):
        snap = house()
        ids = fan_controller(snap)
        snap["unavailable_since"] = {eid: iso(7 * DAY) for eid in ids}
        found = [f for f in devices.unavailable(snap, NOW)
                 if f["entity_id"] in ids]
        self.assertEqual(len(found), 1)
        self.assertIn("Fan controller", found[0]["text"])
        self.assertEqual(found[0]["severity"], "serious")

    def test_without_the_history_it_stays_quiet(self):
        snap = house()
        ids = fan_controller(snap)
        found = [f for f in devices.unavailable(snap, NOW)
                 if f["entity_id"] in ids]
        self.assertEqual(found, [])

    def test_a_second_example_a_loose_entity(self):
        snap = house()
        eid = "switch.garden_pump"
        snap["states"][eid] = {"state": "unavailable",
                               "attributes": {"friendly_name": "Garden pump"},
                               "last_changed": iso(RESTART)}
        snap["unavailable_since"] = {eid: iso(3 * DAY)}
        found = [f for f in devices.unavailable(snap, NOW)
                 if f["entity_id"] == eid]
        self.assertEqual(len(found), 1)

    def test_a_device_that_was_fine_before_the_restart_is_not(self):
        snap = house()
        ids = fan_controller(snap)
        hist = {eid: [row(eid, "on", 5 * DAY), row(eid, "unavailable", RESTART)]
                for eid in ids}
        snap["unavailable_since"] = {
            eid: devices.unavailable_since(rows) for eid, rows in hist.items()}
        found = [f for f in devices.unavailable(snap, NOW)
                 if f["entity_id"] in ids]
        self.assertEqual(found, [])


class TestTheStretch(unittest.TestCase):
    def test_the_earliest_unbroken_unavailable_row(self):
        eid = "fan.x"
        rows = [row(eid, "on", 9 * DAY), row(eid, "unavailable", 6 * DAY),
                row(eid, "unavailable", 3 * DAY), row(eid, "unavailable", RESTART)]
        self.assertEqual(devices.unavailable_since(rows), iso(6 * DAY))

    def test_a_reading_breaks_it(self):
        eid = "fan.x"
        rows = [row(eid, "unavailable", 6 * DAY), row(eid, "on", 3 * DAY),
                row(eid, "unavailable", RESTART)]
        self.assertEqual(devices.unavailable_since(rows), iso(RESTART))

    def test_unknown_is_not_unavailable(self):
        # A button reads "unknown" until pressed; a week of that is not a
        # week of the device being gone.
        eid = "button.x"
        rows = [row(eid, "unknown", 6 * DAY), row(eid, "unavailable", RESTART)]
        self.assertEqual(devices.unavailable_since(rows), iso(RESTART))

    def test_nothing_recorded_is_no_answer(self):
        self.assertIsNone(devices.unavailable_since([]))


class TestTheSnapshotAsksOnlyWhatItNeeds(unittest.TestCase):
    def test_candidates(self):
        snap = house()
        ids = fan_controller(snap)
        snap["states"]["sensor.old"] = {"state": "unavailable", "attributes": {},
                                        "last_changed": iso(3 * DAY)}
        snap["states"]["sensor.orphan"] = {"state": "unavailable",
                                           "attributes": {"restored": True},
                                           "last_changed": iso(RESTART)}
        got = devices.unavailable_candidates(snap["states"], NOW)
        self.assertEqual(sorted(got), sorted(ids))

    def test_the_fetch(self):
        snap = house()
        ids = fan_controller(snap)
        seen = {}

        async def fake_get(_session, path, timeout=30, params=None):
            seen["params"] = params
            return [[row(eid, "unavailable", 7 * DAY), row(eid, "unavailable", RESTART)]
                    for eid in ids]

        with mock.patch("ha_data._rest_get", fake_get):
            got = asyncio.run(snapshot._unavailable_history(
                None, snap["states"], NOW))
        self.assertEqual(got, {eid: iso(7 * DAY) for eid in ids})
        self.assertIn("end_time", seen["params"])

    def test_nothing_to_ask_costs_no_request(self):
        async def fake_get(*_a, **_k):
            raise AssertionError("asked")
        with mock.patch("ha_data._rest_get", fake_get):
            self.assertEqual(asyncio.run(snapshot._unavailable_history(
                None, house()["states"], NOW)), {})


if __name__ == "__main__":
    unittest.main()
