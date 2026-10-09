#!/usr/bin/env python3
"""Where a device is, said as a sentence, and said only when it adds something.

The area used to be appended after a sentence had already ended, so a
humidity row read "…its normal variation. in the Basement." and a battery
row "10% as of 8 Oct in the Hall" — and a device named for one room but
assigned to another came out as one name joined to the other. Each case
drives the real check.

And two shapes ``dev.unavailable`` was answered "not a problem" about:
a phone feature not in use, and a device answered about one entity that
came back under another.

Generic fixture names only.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import baseline, devices  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402

# A lowercase word straight after a full stop: a clause hung off a
# sentence that had already ended.
DANGLING = re.compile(r"\.\s+[a-z]")


def _no_dangling(test: unittest.TestCase, detail: str) -> None:
    test.assertIsNone(DANGLING.search(detail), detail)
    test.assertNotRegex(detail, r"\d (as of|on) [^.]* in the ")


def _humid(name: str = "Damp sensor", area: str = "basement") -> dict:
    snap = house()
    eid = "sensor.damp_humidity"
    snap["states"][eid] = {
        "state": "85", "attributes": {
            "friendly_name": name, "device_class": "humidity",
            "unit_of_measurement": "%", "state_class": "measurement"},
        "last_changed": iso(60)}
    snap["entities"].append({"entity_id": eid, "platform": "zha",
                             "area_id": area})
    snap["areas"].append({"area_id": "basement", "name": "Basement"})
    snap["baselines"]["entities"][eid] = {
        "unit": "%", "samples": 672,
        "overall": {"median": 50.0, "spread": 2.0, "n": 672},
        "buckets": {str(h): {"median": 50.0, "spread": 2.0, "n": 4}
                    for h in range(168)}}
    return snap


class TestTheAreaIsASentence(unittest.TestCase):

    def test_an_unusual_reading_says_its_room_in_a_sentence_of_its_own(self):
        detail = baseline.unusual(_humid(), NOW)[0]["detail"]
        _no_dangling(self, detail)
        self.assertTrue(detail.endswith("It is in the Basement."), detail)

    def test_a_name_that_already_says_the_room_is_not_told_it_again(self):
        detail = baseline.unusual(_humid("Basement humidity"), NOW)[0]["detail"]
        _no_dangling(self, detail)
        self.assertNotIn("Basement.", detail)
        self.assertNotIn("It is in", detail)

    def test_a_name_that_says_another_room_says_both_plainly(self):
        detail = baseline.unusual(_humid("Kitchen humidity"), NOW)[0]["detail"]
        _no_dangling(self, detail)
        self.assertIn("It is named for the Kitchen but assigned to the "
                      "Basement.", detail)

    def test_a_low_battery_ends_its_sentence_before_the_room(self):
        snap = house()
        snap["states"]["sensor.back_door_battery"].update(state="10")
        found = devices.battery_low(snap, NOW)
        self.assertEqual(len(found), 1)
        detail = found[0]["detail"]
        _no_dangling(self, detail)
        self.assertRegex(detail, r"^10% as of .+\. It is in the Hall\.$")
        # The text is what the store dedupes on: unchanged.
        self.assertEqual(found[0]["text"], "Back Door sensor battery is low")

    def test_an_unavailable_device_says_its_room_after_the_count(self):
        snap = house()
        snap["states"]["light.kitchen"].update(state="unavailable",
                                               last_changed=iso(3 * DAY))
        detail = devices.unavailable(snap, NOW)[0]["detail"]
        _no_dangling(self, detail)
        self.assertIn(". It is in the Kitchen.", detail)

    def test_no_area_says_nothing_about_one(self):
        detail = baseline.unusual(_humid(area=""), NOW)[0]["detail"]
        self.assertNotIn("It is in", detail)
        self.assertTrue(detail.endswith("variation."), detail)


class TestAPhoneFeatureNotInUse(unittest.TestCase):

    def _phone(self) -> dict:
        snap = house()
        snap["devices"].append({"id": "dev-phone", "name": "Tablet"})
        snap["states"]["sensor.tablet_battery_state"] = {
            "state": "charging", "attributes": {}, "last_changed": iso(60)}
        snap["entities"].append({"entity_id": "sensor.tablet_battery_state",
                                 "platform": "mobile_app",
                                 "device_id": "dev-phone"})
        snap["states"]["sensor.tablet_kiosk_mode"] = {
            "state": "unavailable", "attributes": {"friendly_name": "Kiosk"},
            "last_changed": iso(30 * DAY)}
        snap["entities"].append({"entity_id": "sensor.tablet_kiosk_mode",
                                 "platform": "mobile_app",
                                 "device_id": "dev-phone"})
        return snap

    def test_a_companion_app_sensor_on_a_phone_that_answers_is_not_filed(self):
        self.assertEqual(devices.unavailable(self._phone(), NOW), [])

    def test_a_phone_that_has_gone_away_entirely_is_still_filed(self):
        snap = self._phone()
        snap["states"]["sensor.tablet_battery_state"].update(
            state="unavailable", last_changed=iso(3 * DAY))
        found = devices.unavailable(snap, NOW)
        self.assertEqual([f["text"] for f in found],
                         ["Tablet has been unavailable for more than a day"])

    def test_another_integration_s_feature_on_an_answering_device_still_files(self):
        snap = house()
        _probe = "sensor.hall_probe"
        snap["states"][_probe] = {"state": "unavailable",
                                  "attributes": {"friendly_name": "Probe"},
                                  "last_changed": iso(3 * DAY)}
        snap["entities"].append({"entity_id": _probe, "platform": "zha",
                                 "device_id": "dev-temp-1"})
        self.assertEqual(len(devices.unavailable(snap, NOW)), 1)


class TestADeviceAnsweredAboutOnceStaysAnswered(unittest.TestCase):

    def test_wrong_about_one_entity_of_a_dead_device_covers_the_device(self):
        snap = house()
        snap["states"]["light.kitchen"].update(state="unavailable",
                                               last_changed=iso(3 * DAY))
        # A second entity of the same box, down for longer, now leads.
        snap["states"]["light.kitchen_2"] = {
            "state": "unavailable", "attributes": {},
            "last_changed": iso(4 * DAY)}
        snap["entities"].append({"entity_id": "light.kitchen_2",
                                 "platform": "hue", "device_id": "dev-hue-1"})
        self.assertEqual(len(devices.unavailable(snap, NOW)), 1)
        snap["facts"] = {"light.kitchen": {"dev.unavailable"}}
        self.assertEqual(devices.unavailable(snap, NOW), [])


if __name__ == "__main__":
    unittest.main()
