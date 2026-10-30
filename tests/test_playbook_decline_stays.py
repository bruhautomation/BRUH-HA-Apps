#!/usr/bin/env python3
"""A declined emergency playbook stays declined.

`proposals.key_for` hashes a playbook's whole config, and the config lists
every light, thermostat and blind in the house, so any one of them coming
or going made a new key and the declined playbook was offered again (nine
declines of one). It is the same playbook while its class and the
detectors that trigger it are the same — and a decline recorded under an
older build's key, which carries only the title, still stands. Camera
audio detection ("smoke alarm heard") is not a detector.

The second example is the water-leak playbook, which the report never
mentioned.
"""
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import playbooks  # noqa: E402
from test_playbooks import by_class, house, st  # noqa: E402
from test_proposals import ProposalCase  # noqa: E402


def playbook(snap, name):
    return by_class(playbooks.build(snap, []))[name]


def changed_house():
    snap = house()
    snap["states"]["light.loft"] = st("off", friendly_name="Loft")
    snap["states"]["climate.loft"] = st("heat", friendly_name="Loft rad",
                                        hvac_action="idle")
    snap["states"]["cover.study_curtain"] = st(
        "closed", device_class="curtain", friendly_name="Study curtain")
    snap["states"]["valve.garden_tap"] = st("open", friendly_name="Garden tap")
    del snap["states"]["light.kitchen"]
    return snap


class TestADeclinedPlaybookStaysDeclined(ProposalCase):
    def decline(self, obj):
        row = self.p.add(obj)
        self.assertIsNotNone(row)
        self.assertIsNotNone(self.p.decide(row["ts"], "declined", "no"))

    def test_changing_what_it_acts_on_does_not_bring_it_back(self):
        for name in ("smoke", "leak"):
            before = playbook(house(), name)
            after = playbook(changed_house(), name)
            self.assertNotEqual(self.p.key_for(before), self.p.key_for(after),
                                "the premise: the config hash did move")
            self.decline(before)
            self.assertTrue(self.p.knows(after), name)
            self.assertIsNone(self.p.add(after), name)

    def test_a_new_detector_is_still_a_new_offer(self):
        before = playbook(house(), "smoke")
        self.decline(before)
        more = changed_house()
        more["states"]["binary_sensor.loft_smoke"] = st(
            "off", device_class="smoke", friendly_name="Loft smoke")
        self.assertFalse(self.p.knows(playbook(more, "smoke")))

    def test_a_decline_under_an_older_key_still_stands(self):
        # What an older build wrote: the config's hash, the title, no class.
        self.p._write_settled([{
            "key": "0123456789abcdef", "kind": "playbook",
            "title": "Emergency playbook: smoke or carbon monoxide",
            "status": "declined", "note": "", "source": "playbook",
            "settled_at": 1}])
        self.assertTrue(self.p.knows(playbook(changed_house(), "smoke")))
        self.assertFalse(self.p.knows(playbook(changed_house(), "leak")))

    def test_a_live_card_of_the_same_class_is_not_offered_twice(self):
        self.assertIsNotNone(self.p.add(playbook(house(), "smoke")))
        self.assertIsNone(self.p.add(playbook(changed_house(), "smoke")))


class TestACameraHearingAnAlarmIsNotADetector(unittest.TestCase):
    def only_camera_house(self, platform, with_camera_sibling=False):
        snap = house()
        del snap["states"]["binary_sensor.hall_smoke"]
        snap["states"]["binary_sensor.porch_cam_alarm_detected"] = st(
            "off", device_class="carbon_monoxide",
            friendly_name="Porch cam CO alarm detected")
        snap["entities"] = list(snap["entities"]) + [
            {"entity_id": "binary_sensor.porch_cam_alarm_detected",
             "platform": platform, "device_id": "dev-cam"}]
        if with_camera_sibling:
            snap["states"]["camera.porch"] = st("idle")
            snap["entities"].append({"entity_id": "camera.porch",
                                     "platform": platform,
                                     "device_id": "dev-cam"})
        return snap

    def test_a_camera_integration_s_sensor_does_not_make_a_playbook(self):
        for platform in ("unifiprotect", "reolink"):
            self.assertNotIn("smoke", by_class(
                playbooks.build(self.only_camera_house(platform), [])))

    def test_a_sensor_on_a_cameras_device_does_not_either(self):
        snap = self.only_camera_house("some_new_vendor", True)
        self.assertNotIn("smoke", by_class(playbooks.build(snap, [])))

    def test_a_real_detector_beside_a_camera_is_the_only_one_listed(self):
        snap = self.only_camera_house("unifiprotect")
        snap["states"]["binary_sensor.hall_smoke"] = st(
            "off", device_class="smoke", friendly_name="Hall smoke")
        smoke = by_class(playbooks.build(snap, []))["smoke"]
        self.assertEqual([s["entity_id"] for s in smoke["playbook"]["sensors"]],
                         ["binary_sensor.hall_smoke"])


if __name__ == "__main__":
    unittest.main()
