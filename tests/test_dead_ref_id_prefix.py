#!/usr/bin/env python3
"""A prefix an automation builds ids from is not an entity it refers to.

#336: an automation building `'switch.pump_zone_' ~ n` — the prefix kept
in a `{% set %}` or a `variables:` value, and stripped again with
`regex_replace` — was reported as referring to a missing
`switch.pump_zone_`. The token-by-token skips only caught a prefix glued
on in the same expression; the class is that Home Assistant never names an
entity whose object id ends (or starts) with `_` or holds `__`, so such a
token is a piece of an id wherever it appears, and the first argument of
a regex filter is a pattern, not an id.
"""

import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import checks  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

automations = checks.automations
House = checks._util.House


def automation_house(actions, variables=None):
    snap = house()
    config = {"id": "water-1", "alias": "Water the zones",
              "trigger": [{"platform": "time", "at": "06:00:00"}],
              "action": actions}
    if variables:
        config["variables"] = variables
    snap["automations"] = [config]
    snap["states"]["automation.water_the_zones"] = {
        "state": "on", "attributes": {"friendly_name": "Water the zones",
                                      "id": "water-1"}}
    snap["entities"].append({"entity_id": "automation.water_the_zones",
                             "platform": "automation", "unique_id": "water-1"})
    return snap


class TestAnIdPrefixIsNotMissing(unittest.TestCase):
    def test_the_reported_shapes_file_nothing(self):
        for actions, variables in (
                ([{"action": "switch.turn_on", "target": {"entity_id":
                   "{% set p = 'switch.pump_zone_' %}{{ p ~ n }}"}}], None),
                ([{"action": "switch.turn_on", "target": {"entity_id":
                   "{{ prefix ~ n }}"}}], {"prefix": "switch.pump_zone_"}),
                ([{"variables": {"zone": "{{ trigger.entity_id | "
                                 "regex_replace('switch.pump_zone_', '') }}"}}],
                 None),
                ([{"action": "light.turn_on", "target": {"entity_id":
                   "{{ \"light.\" + room + \"_lamp\" }}"}}], None),
                ([{"condition": "template", "value_template":
                   "{{ trigger.entity_id is match('light.hall') }}"}], None),
                ([{"action": "light.turn_on", "target": {"entity_id":
                   "{{ states.light | map(attribute='entity_id') | "
                   "select('search', 'light.hall') | list }}"}}], None)):
            with self.subTest(actions=actions, variables=variables):
                self.assertEqual(automations.dead_ref(
                    automation_house(actions, variables), NOW), [])

    def test_ha_never_names_an_entity_like_that(self):
        refs = House(house()).entity_refs({"a": [
            "switch.pump_zone_", "switch._hidden", "switch.pump__zone",
            "switch.pump_zone_1"]})
        self.assertEqual(refs, {"switch.pump_zone_1"})

    def test_a_whole_missing_id_is_still_reported(self):
        found = automations.dead_ref(automation_house(
            [{"action": "switch.turn_on",
              "target": {"entity_id": "switch.pump_zone_9"}}]), NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("switch.pump_zone_9",
                      [e["entity"] for e in found[0]["evidence"]])


if __name__ == "__main__":
    unittest.main()
