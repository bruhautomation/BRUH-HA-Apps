"""An alarm automation that has never fired is an alarm that has never gone off.

`auto.never_fired` files *"has never fired … or delete it if it is no
longer wanted"* for any enabled automation thirty days old whose trigger
has not happened once — which is the defining property of a healthy smoke,
leak or CO response. brAIn's own emergency playbooks are exactly that, so
thirty days after somebody accepted the smoke playbook, brAIn suggested
deleting it. The playbooks here are built by the real `playbooks.build`
and written by the real `automation_writer.entry_for`, because what is
exempted has to be what brAIn actually puts in somebody's file.

And `auto.trigger_unavailable` read a trigger's top-level `entity_id`
only, so a trigger written the way HA 2026.7's editor writes one —
`trigger: light.turned_on` with the entity under `target:` — was never
checked at all.
"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import automation_writer  # noqa: E402
import checks  # noqa: E402
import playbooks  # noqa: E402
from test_house_checks import DAY, NOW, house, iso  # noqa: E402

automations = checks.automations


def detectors(snap: dict) -> dict:
    """The fixture house, with a smoke detector and a leak sensor fitted."""
    snap["states"]["binary_sensor.hall_smoke"] = {
        "state": "off", "attributes": {"device_class": "smoke",
                                       "friendly_name": "Hall smoke"},
        "last_changed": iso(40 * DAY)}
    snap["states"]["binary_sensor.sink_leak"] = {
        "state": "off", "attributes": {"device_class": "moisture",
                                       "friendly_name": "Sink leak"},
        "last_changed": iso(40 * DAY)}
    # The leak playbook is proposed only where it has something to shut.
    snap["states"]["valve.water_main"] = {
        "state": "open", "attributes": {"friendly_name": "Water main"}}
    snap["entities"] += [
        {"entity_id": "binary_sensor.hall_smoke", "platform": "zha",
         "id": "6a1b2c3d4e5f", "area_id": "hall"},
        {"entity_id": "binary_sensor.sink_leak", "platform": "zha",
         "id": "77aa88bb99cc", "area_id": "kitchen"},
    ]
    return snap


def installed(snap: dict, config: dict, entity_id: str,
              age_days: float = 90) -> None:
    """An automation that is in the file, registered, on, and never ran."""
    snap["automations"].append(config)
    snap["entities"].append({"entity_id": entity_id, "platform": "automation",
                             "unique_id": config["id"],
                             "created_at": NOW - age_days * DAY})
    snap["states"][entity_id] = {
        "state": "on",
        "attributes": {"friendly_name": config.get("alias") or entity_id,
                       "id": config["id"], "last_triggered": None},
        "last_changed": iso(age_days * DAY)}


def never_fired_ids(snap: dict) -> list[str]:
    return [f["entity_id"] for f in automations.never_fired(snap, NOW)]


class TestBrainsOwnPlaybooksAreNotDeadWood(unittest.TestCase):

    def test_an_accepted_playbook_a_month_old_is_not_offered_for_deletion(self):
        snap = detectors(house())
        rows = playbooks.build(snap, [], "notify.mobile_app_phone")
        built = {r["config"]["id"] for r in rows}
        self.assertIn("brain_playbook_smoke", built)
        self.assertIn("brain_playbook_leak", built)
        self.assertIn("brain_playbook_freeze", built)
        for i, row in enumerate(rows):
            entry = automation_writer.entry_for(row, NOW)
            installed(snap, entry, f"automation.playbook_{i}")
        self.assertEqual(never_fired_ids(snap), [])

    def test_the_prefix_is_the_writers(self):
        self.assertEqual(automations.BRAIN_PREFIX,
                         automation_writer.ID_PREFIX)


class TestSomebodysOwnAlarmIsNotDeadWoodEither(unittest.TestCase):

    def test_a_leak_response_watching_a_moisture_sensor(self):
        snap = detectors(house())
        installed(snap, {"id": "leak_1", "alias": "Leak: shut the valve",
                         "triggers": [{"trigger": "state",
                                       "entity_id": "binary_sensor.sink_leak",
                                       "to": "on"}],
                         "actions": []}, "automation.leak_shut_the_valve")
        self.assertEqual(never_fired_ids(snap), [])

    def test_a_device_trigger_names_the_alarm_by_type(self):
        # What HA's editor writes when a detector is picked off a list:
        # the entity by its REGISTRY id, and the condition by `type`.
        snap = detectors(house())
        installed(snap, {"id": "smoke_1", "alias": "Smoke: wake everyone",
                         "triggers": [{"trigger": "device",
                                       "device_id": "dev-x",
                                       "domain": "binary_sensor",
                                       "entity_id": "6a1b2c3d4e5f",
                                       "type": "smoke"}],
                         "actions": []}, "automation.smoke_wake")
        self.assertEqual(never_fired_ids(snap), [])

    def test_a_registry_id_resolves_to_the_detector_it_names(self):
        snap = detectors(house())
        installed(snap, {"id": "smoke_2", "alias": "Smoke, by state",
                         "triggers": [{"trigger": "device",
                                       "device_id": "dev-x",
                                       "domain": "binary_sensor",
                                       "entity_id": "6a1b2c3d4e5f",
                                       "type": "turned_on"}],
                         "actions": []}, "automation.smoke_by_state")
        self.assertEqual(never_fired_ids(snap), [])

    def test_a_purpose_specific_trigger_with_a_target(self):
        snap = detectors(house())
        installed(snap, {"id": "leak_2", "alias": "Leak, new editor",
                         "triggers": [{"trigger": "moisture.detected",
                                       "target": {"entity_id":
                                                  ["binary_sensor.sink_leak"]}}],
                         "actions": []}, "automation.leak_new_editor")
        self.assertEqual(never_fired_ids(snap), [])

    def test_an_alarm_panel_going_off(self):
        snap = house()
        snap["states"]["alarm_control_panel.house"] = {
            "state": "armed_away", "attributes": {}}
        installed(snap, {"id": "alarm_1", "alias": "Alarm: lights",
                         "triggers": [{"trigger": "state",
                                       "entity_id": "alarm_control_panel.house",
                                       "to": "triggered"}],
                         "actions": []}, "automation.alarm_lights")
        self.assertEqual(never_fired_ids(snap), [])


class TestTheFloorStillWorks(unittest.TestCase):
    """The exemptions are about what an automation is FOR; an ordinary
    rule whose trigger has not happened in a month is still the finding."""

    def test_a_motion_rule_that_never_fired_is_still_reported(self):
        snap = house()
        snap["states"]["binary_sensor.hall_motion"] = {
            "state": "off", "attributes": {"device_class": "motion"}}
        installed(snap, {"id": "motion_1", "alias": "Hall light",
                         "triggers": [{"trigger": "state",
                                       "entity_id": "binary_sensor.hall_motion",
                                       "to": "on"}],
                         "actions": []}, "automation.hall_light")
        self.assertEqual(never_fired_ids(snap), ["automation.hall_light"])

    def test_an_id_that_merely_contains_brain_is_not_brains(self):
        snap = house()
        installed(snap, {"id": "my_brain_thing", "alias": "Mine",
                         "triggers": [{"trigger": "time", "at": "07:00"}],
                         "actions": []}, "automation.mine")
        self.assertEqual(never_fired_ids(snap), ["automation.mine"])

    def test_the_clean_house_is_still_silent(self):
        self.assertEqual(automations.never_fired(house(), NOW), [])


class TestATriggerUnderTarget(unittest.TestCase):
    """`auto.trigger_unavailable` reads `target: {entity_id}` too."""

    def dead_light(self, snap: dict) -> dict:
        snap["states"]["light.porch"] = {
            "state": "unavailable", "attributes": {},
            "last_changed": iso(5 * DAY)}
        return snap

    def test_a_purpose_specific_trigger_on_a_dead_entity_is_found(self):
        snap = self.dead_light(house())
        cfg = copy.deepcopy(snap["automations"][0])
        cfg["triggers"] = [{"trigger": "light.turned_on",
                            "target": {"entity_id": "light.porch"},
                            "options": {"behavior": "each"}}]
        snap["automations"] = [cfg]
        found = automations.trigger_unavailable(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("light.porch", [e["entity"] for e in found[0]["evidence"]])

    def test_an_area_target_says_nothing(self):
        # "Every light in the kitchen" with one of them down is still an
        # automation that fires; and nothing here can expand an area.
        snap = self.dead_light(house())
        cfg = copy.deepcopy(snap["automations"][0])
        cfg["triggers"] = [{"trigger": "light.turned_on",
                            "target": {"area_id": "kitchen"}}]
        snap["automations"] = [cfg]
        self.assertEqual(automations.trigger_unavailable(snap, NOW), [])

    def test_the_old_spelling_is_still_read(self):
        snap = self.dead_light(house())
        cfg = copy.deepcopy(snap["automations"][0])
        cfg["trigger"] = [{"platform": "state", "entity_id": "light.porch"}]
        cfg.pop("triggers", None)
        snap["automations"] = [cfg]
        self.assertEqual(len(automations.trigger_unavailable(snap, NOW)), 1)


if __name__ == "__main__":
    unittest.main()
