#!/usr/bin/env python3
"""A condition that fails on purpose is not a condition that never passes.

An automation that wakes every minute (or when Home Assistant starts) and
acts only while one switch is on fails its condition on nearly every run by
design: it is an interlock, a guard re-checked on a clock. `auto.condition_
never_passes` read that as an automation that cannot act, was marked Wrong
every time, and the rule was muted for every automation in the house, real
problems included. The check stands down for a polled guard — a
`time_pattern` or Home Assistant start trigger whose condition only tests
one entity's state or a time window — and still reports a never-passing
condition on an ordinary trigger.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from checks import automations  # noqa: E402
from test_house_checks import DAY, NOW, core_run, house, iso  # noqa: E402


def stuck(config: dict) -> dict:
    snap = house()
    snap["automations"] = [dict(config, id="morning-1", alias="Morning lights")]
    snap["states"]["automation.morning"]["attributes"]["last_triggered"] = \
        iso(30 * DAY)
    snap["traces"]["automation.morning-1"] = [
        core_run(str(i), "failed_conditions", i * 60, last_step=None)
        for i in range(5)]
    return snap


ACT = [{"action": "switch.turn_off", "target": {"entity_id": "switch.heater"}}]


class TestAPolledGuardIsNotAFault(unittest.TestCase):
    def found(self, config):
        return automations.condition_never_passes(stuck(config), NOW)

    def test_every_minute_while_a_switch_is_on(self):
        self.assertEqual(self.found({
            "triggers": [{"trigger": "time_pattern", "minutes": "/1"},
                         {"trigger": "homeassistant", "event": "start"}],
            "conditions": [{"condition": "state", "entity_id": "switch.pump",
                            "state": "on"}],
            "actions": ACT}), [])

    def test_the_legacy_spelling_too(self):
        self.assertEqual(self.found({
            "trigger": [{"platform": "time_pattern", "minutes": "/5"}],
            "condition": {"condition": "state", "entity_id": ["switch.pump"],
                          "state": "on"},
            "action": ACT}), [])

    def test_a_start_event_with_a_time_window(self):
        self.assertEqual(self.found({
            "triggers": [{"trigger": "event", "event_type": "homeassistant_start"}],
            "conditions": [{"condition": "time", "after": "22:00:00",
                            "before": "06:00:00"}],
            "actions": ACT}), [])


class TestARealOneStillIs(unittest.TestCase):
    def found(self, config):
        return automations.condition_never_passes(stuck(config), NOW)

    def test_an_ordinary_trigger(self):
        self.assertEqual(len(self.found({
            "triggers": [{"trigger": "state", "entity_id": "binary_sensor.door",
                          "to": "on"}],
            "conditions": [{"condition": "state", "entity_id": "switch.pump",
                            "state": "on"}],
            "actions": ACT})), 1)

    def test_a_poll_whose_condition_tests_more_than_one_thing(self):
        self.assertEqual(len(self.found({
            "triggers": [{"trigger": "time_pattern", "minutes": "/1"}],
            "conditions": [{"condition": "state", "entity_id": "switch.pump",
                            "state": "on"},
                           {"condition": "numeric_state",
                            "entity_id": "sensor.tank", "above": 90}],
            "actions": ACT})), 1)

    def test_a_poll_with_a_template_condition(self):
        self.assertEqual(len(self.found({
            "triggers": [{"trigger": "time_pattern", "minutes": "/1"}],
            "conditions": [{"condition": "template",
                            "value_template": "{{ false }}"}],
            "actions": ACT})), 1)


if __name__ == "__main__":
    unittest.main()
