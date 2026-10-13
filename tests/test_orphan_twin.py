#!/usr/bin/env python3
"""`reg.orphan_device` and a device's second registry entry.

A house had "Shelly EM3 (Septic Pump)" listed as a device with no
entities while its power meter worked — under a second registry entry for
the same Shelly, re-created after a reconfigure. The card's advice was
Delete, and on the Devices page the two same-named entries look alike.
The row has to say which one is the leftover, and that deleting it leaves
the readings alone.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import registry  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

MAC = "c4:5b:be:01:02:03"
ID_RE = re.compile(r"\b[a-z_]+\.[a-z0-9_]+\b")


def _twins(empty: dict | None = None, live: dict | None = None) -> dict:
    snap = house()
    live_dev = {"id": "dev-shelly-new", "name": "Shelly EM3 (Septic Pump)",
                "config_entries": ["e1"],
                "connections": [["mac", MAC]]}
    live_dev.update(live or {})
    empty_dev = {"id": "dev-shelly-old", "name": "Shelly EM3 (Septic Pump)",
                 "config_entries": ["e1"],
                 "connections": [["mac", MAC]]}
    empty_dev.update(empty or {})
    snap["devices"] += [live_dev, empty_dev]
    snap["entities"].append({"entity_id": "sensor.septic_pump_power",
                             "device_id": "dev-shelly-new",
                             "platform": "shelly"})
    snap["states"]["sensor.septic_pump_power"] = {
        "entity_id": "sensor.septic_pump_power", "state": "412",
        "attributes": {"friendly_name": "Septic pump power"},
        "last_changed": "2026-10-01T00:00:00+00:00"}
    return snap


class TestASecondEntryForAWorkingDevice(unittest.TestCase):
    def _row(self, snap):
        found = registry.orphan_device(snap, NOW)
        self.assertEqual(len(found), 1)
        return found[0]

    def test_a_same_named_twin_is_said_to_be_the_leftover(self):
        row = self._row(_twins())
        prose = row["detail"] + " " + row["fix"]
        self.assertIn("Shelly EM3 (Septic Pump)", row["detail"])
        self.assertRegex(prose.lower(), r"second entry")
        self.assertRegex(prose.lower(), r"leaves? (its|the) readings")

    def test_the_name_match_ignores_case(self):
        row = self._row(_twins(empty={"name": "shelly em3 (septic pump)",
                                      "connections": []}))
        self.assertRegex(row["detail"].lower(), r"second entry")

    def test_a_shared_mac_is_a_twin_whatever_the_name(self):
        row = self._row(_twins(empty={"name": "shellyem3-C45BBE010203"}))
        self.assertRegex(row["detail"].lower(), r"second entry")
        # named by the entry that has the readings, never by its MAC
        self.assertIn("Shelly EM3 (Septic Pump)", row["detail"])
        self.assertNotIn(MAC, row["detail"] + row["fix"])
        self.assertNotIn(MAC.upper(), row["detail"] + row["fix"])

    def test_no_ids_or_macs_in_the_prose(self):
        row = self._row(_twins())
        for part in (row["detail"], row["fix"]):
            self.assertIsNone(ID_RE.search(part), part)
            self.assertNotIn(MAC, part)

    def test_the_dedupe_key_does_not_move(self):
        self.assertEqual(self._row(_twins())["text"],
                         "Some devices are left in the registry with no entities")

    def test_a_plain_leftover_carries_no_twin_sentence(self):
        snap = house()
        snap["devices"].append({"id": "dev-ghost", "name": "Old thermostat"})
        row = self._row(snap)
        self.assertNotIn("second entry", row["detail"].lower())

    def test_two_empty_twins_are_not_each_others_readings(self):
        # neither entry has entities: nothing has readings, so no claim
        snap = house()
        snap["devices"] += [
            {"id": "a", "name": "Old plug", "connections": [["mac", MAC]]},
            {"id": "b", "name": "Old plug", "connections": [["mac", MAC]]}]
        row = self._row(snap)
        self.assertNotIn("second entry", row["detail"].lower())


if __name__ == "__main__":
    unittest.main()
