"""`base.unusual`'s advice fits what the entity is.

A humidity or temperature reading cannot have been "running, off, or set
differently from usual", and the fix said it could: "Check <name> in the
<room>: whether it was running, off, or set differently". For a reading of
a room's air the fix names what drives it — a machine in the same room —
and the outdoor reading when the snapshot holds one, and never puts a
machine's verbs on a sensor. `text`, the dedupe key, does not move.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import baseline  # noqa: E402
import test_checks_seven_house_reports as seven  # noqa: E402
from test_house_checks import DAY, NOW, iso  # noqa: E402

FORBIDDEN = "whether it was running, off, or set differently"


def humid() -> dict:
    return seven.TestTheFixNamesWhatIsNearby._humid(None)


def add(snap, eid, name, area="basement", state="off", **attrs):
    snap["states"][eid] = {"state": state,
                           "attributes": {"friendly_name": name, **attrs},
                           "last_changed": iso(DAY)}
    snap["entities"].append({"entity_id": eid, "platform": "zha",
                             "area_id": area})


class TestTheFixFitsAReadingOfTheRoomsAir(unittest.TestCase):
    def fix(self, snap) -> dict:
        found = baseline.unusual(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["text"],
                         "Basement humidity is reading far outside its usual range")
        return found[0]

    def test_a_machine_in_the_room_is_named_without_a_machines_verbs_on_the_reading(self):
        snap = humid()
        add(snap, "switch.basement_dehumidifier", "Dehumidifier")
        row = self.fix(snap)
        self.assertIn("Dehumidifier", row["fix"])
        self.assertNotIn(FORBIDDEN, row["fix"])

    def test_a_sensor_is_never_told_it_was_running_or_off(self):
        snap = humid()
        add(snap, "sensor.basement_fan_temperature", "Basement fan temperature",
            state="18", device_class="temperature", unit_of_measurement="°C")
        row = self.fix(snap)
        self.assertNotIn(FORBIDDEN, row["fix"])
        self.assertNotIn("Check Basement fan temperature", row["fix"])

    def test_the_outdoor_humidity_is_named_when_the_snapshot_has_it(self):
        snap = humid()
        snap["states"]["weather.home"] = {
            "state": "rainy", "attributes": {"friendly_name": "Home",
                                             "humidity": 93,
                                             "temperature": 8.0}}
        row = self.fix(snap)
        self.assertIn("93%", row["fix"])
        self.assertIn("outside", row["fix"].lower())
        self.assertNotIn(FORBIDDEN, row["fix"])

    def test_a_temperature_names_the_outdoor_thermometer(self):
        snap = humid()
        eid = "sensor.basement_humidity"
        snap["states"][eid]["attributes"].update(
            {"device_class": "temperature", "unit_of_measurement": "°C",
             "friendly_name": "Basement humidity"})
        snap["states"][eid]["state"] = "35"
        snap["baselines"]["entities"][eid]["unit"] = "°C"
        snap["states"]["sensor.garden_temp"] = {
            "state": "4.5", "attributes": {"friendly_name": "Garden temperature",
                                           "device_class": "temperature",
                                           "unit_of_measurement": "°C"}}
        snap["thermal"] = {"outdoor": "sensor.garden_temp", "rooms": {}}
        add(snap, "climate.basement", "Basement heating", state="heat")
        row = self.fix(snap)
        self.assertIn("Basement heating", row["fix"])
        self.assertIn("Garden temperature", row["fix"])
        self.assertNotIn(FORBIDDEN, row["fix"])


if __name__ == "__main__":
    unittest.main()
