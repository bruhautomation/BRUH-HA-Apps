"""`auto.overridden` is about a rule a person disagrees with. An automation
whose every trigger is a press (a wall switch, a remote) is somebody's hand
with a rule in between, so undoing what it did is the person changing their
mind, not the rule being wrong for the house."""

import sys
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

from checks import automations as auto  # noqa: E402

NOW = 1_789_800_000.0
EID = "automation.wall_switch"


def house(trigger):
    cfg = {"id": "3001", "alias": "Wall switch", "triggers": [trigger],
           "actions": [{"action": "light.turn_on",
                        "target": {"entity_id": "light.room"}}]}
    overrides = [{"ts": NOW - i * 3600, "entity_id": "light.room",
                  "name": "light.room", "from_state": "on",
                  "to_state": "off", "by": EID, "by_name": "Wall switch",
                  "by_cause": "automation", "person": "Ben", "after_s": 60}
                 for i in range(auto.OVERRIDE_MIN + 1)]
    return {
        "now": NOW,
        "states": {"light.room": {"state": "off", "attributes": {}},
                   "event.switch_scene": {"state": "x", "attributes": {}},
                   "sensor.hall": {"state": "1", "attributes": {}},
                   EID: {"state": "on", "attributes": {"id": "3001"}}},
        "entities": [{"entity_id": EID, "platform": "automation",
                      "unique_id": "3001"}],
        "devices": [], "areas": [], "automations": [cfg],
        "actions": {"available": True, "overrides": overrides, "moves": {}},
        "available": {}, "errors": {},
    }


class TestOverriddenAndPresses(unittest.TestCase):
    def test_a_press_triggered_rule_is_not_a_rule_being_undone(self):
        for trig in ({"trigger": "state", "entity_id": "event.switch_scene"},
                     {"trigger": "event",
                      "event_type": "zwave_js_value_notification"}):
            self.assertEqual(auto.overridden(house(trig), NOW), [], trig)

    def test_a_rule_that_is_not_a_press_still_speaks(self):
        found = auto.overridden(
            house({"trigger": "state", "entity_id": "sensor.hall"}), NOW)
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()
