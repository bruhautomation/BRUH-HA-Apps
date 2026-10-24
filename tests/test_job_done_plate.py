#!/usr/bin/env python3
"""The finished print clears itself when BRUH Bambu Studio sees the plate
cleared.

`chore.job_done` said "brAIn cannot see that you have taken the print off,
because the status says the same thing either way", and for a printer
status alone that is true. BRUH Bambu Studio's failure detection
publishes a "Plate clear" binary sensor per printer (platform
`bruh_bambu`, translation key `plate_clear`): off while a print is on the
plate, on once it has been taken off. When the house has one for the
printer — on the same device, or on the device that carries the same
serial number — the chore reads it: an occupied plate is the chore, said
without the "cannot see"; a clear plate is no chore, so the row clears on
the next pass. Without the add-on nothing changes. Nothing is imported
from the other add-on: the entity is read off the snapshot.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
from checks import chores  # noqa: E402
from test_job_status_chore import EID, NOW, iso, printer_house  # noqa: E402

PLATE = "binary_sensor.workshop_printer_plate_clear"


def with_plate(state: str | None, *, same_device: bool = True,
               changed_min: float = 10.0) -> dict:
    snap = printer_house()
    snap["devices"] = [{"id": "dev-printer", "name": "Workshop printer",
                        "serial_number": "01P00A000000001"}]
    for e in snap["entities"]:
        if e["entity_id"] == EID:
            e.update(device_id="dev-printer", platform="bambu_lab")
    plate_device = "dev-printer"
    if not same_device:
        plate_device = "dev-bruh"
        snap["devices"].append({"id": "dev-bruh", "name": "Workshop printer",
                                "serial_number": "01P00A000000001"})
    if state is not None:
        snap["states"][PLATE] = {
            "state": state, "last_changed": iso(changed_min * 60),
            "attributes": {"friendly_name": "Workshop printer Plate clear"}}
        snap["entities"].append({
            "entity_id": PLATE, "platform": "bruh_bambu",
            "device_id": plate_device, "translation_key": "plate_clear",
            "unique_id": "entry1_printer1_plate_clear", "disabled_by": None})
    return snap


class TestThePlateDecides(unittest.TestCase):
    def test_an_occupied_plate_is_the_chore_and_says_it_will_clear(self):
        got = chores.job_done(with_plate("off"), NOW)
        self.assertEqual(len(got), 1)
        self.assertNotIn("cannot see", got[0]["fix"])
        self.assertIn("plate", got[0]["fix"].lower())

    def test_a_clear_plate_is_no_chore(self):
        self.assertEqual(chores.job_done(with_plate("on"), NOW), [])

    def test_the_row_clears_when_the_plate_goes_clear(self):
        before = checks.run_all(with_plate("off"), NOW, only=["chore.job_done"])
        self.assertEqual(len(before["findings"]), 1)
        after = checks.run_all(with_plate("on"), NOW, only=["chore.job_done"])
        self.assertEqual(after["findings"], [])
        self.assertIn("chore.job_done", after["ran"])

    def test_a_plate_on_the_add_ons_own_device_matched_by_serial(self):
        self.assertEqual(chores.job_done(with_plate("on", same_device=False),
                                         NOW), [])
        got = chores.job_done(with_plate("off", same_device=False), NOW)
        self.assertNotIn("cannot see", got[0]["fix"])

    def test_a_plate_nobody_can_read_is_the_old_chore(self):
        for state in ("unknown", "unavailable"):
            with self.subTest(state=state):
                got = chores.job_done(with_plate(state), NOW)
                self.assertEqual(len(got), 1)
                self.assertIn("cannot see", got[0]["fix"])

    def test_without_the_add_on_nothing_changes(self):
        got = chores.job_done(with_plate(None), NOW)
        self.assertEqual(len(got), 1)
        self.assertIn("cannot see", got[0]["fix"])

    def test_a_plate_cleared_before_this_print_finished_is_not_this_print(self):
        # Cleared two hours ago, the print finished forty minutes ago and the
        # plate has not been seen since: the reading is from before.
        got = chores.job_done(with_plate("on", changed_min=120.0), NOW)
        self.assertEqual(len(got), 1)


if __name__ == "__main__":
    unittest.main()
