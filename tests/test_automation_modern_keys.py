#!/usr/bin/env python3
"""Every automation brAIn writes uses Home Assistant's current keys.

Two automations written on request came out as `trigger:` / `- platform:`
/ `condition:` / `action:` — the spelling Home Assistant replaced in
2024.10 with `triggers:` / `- trigger:` / `conditions:` / `actions:`. Every
producer that composes a config now writes the new words, the writer
respells a legacy config before it appends it (a model's answer may still
arrive in the old words), a person's own entry is never respelled, every
reader takes both, and a proposal's identity did not move with the
spelling — or every declined proposal would be offered again.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import automation_keys  # noqa: E402
import playbooks  # noqa: E402
import proposals  # noqa: E402
import routines  # noqa: E402
import scenes  # noqa: E402
import shadow  # noqa: E402
import test_authoring  # noqa: E402
import test_intents  # noqa: E402
import test_playbooks  # noqa: E402
import test_scenes  # noqa: E402
from checks import automations as auto_checks  # noqa: E402
from test_automation_writer import EXISTING, WriterCase, proposal  # noqa: E402

LEGACY = {"trigger", "condition", "action"}


def assert_modern(case: unittest.TestCase, config: dict) -> None:
    case.assertFalse(LEGACY & set(config), config)
    case.assertIn("triggers", config)
    case.assertIn("actions", config)
    triggers = config["triggers"]
    for trig in triggers if isinstance(triggers, list) else [triggers]:
        case.assertNotIn("platform", trig, trig)
        case.assertIn("trigger", trig, trig)


class TestEveryProducerWritesTheNewWords(unittest.TestCase):
    def test_a_routine(self):
        config = routines.to_config({"entity_id": "light.hall", "state": "on",
                                     "minute": 18 * 60 + 40,
                                     "when_days": "weekdays"})
        assert_modern(self, config)
        self.assertIn("conditions", config)

    def test_the_playbooks(self):
        made = test_playbooks.by_class(playbooks.build(test_playbooks.house()))
        self.assertTrue(made)
        for name, row in made.items():
            with self.subTest(playbook=name):
                assert_modern(self, row["config"])

    def test_the_scene_schedule(self):
        names = {m: f"{scenes.DEFAULT_NAMES[m]} — Living room"
                 for m in scenes.MOODS}
        written = [{"id": f"{scenes.ID_PREFIX}living_room_{m}", "name": names[m]}
                   for m in scenes.MOODS]
        snap = test_scenes.house(test_scenes.LOUNGE, written)
        obj = scenes.schedule(snap, "Living room", 7 * 60, 22 * 60)
        assert_modern(self, obj["config"])


class TestAModelsLegacyAnswerIsRespelled(test_intents.IntentCase):
    def test_a_one_off(self):
        row = self.build()
        assert_modern(self, row["config"])


class TestAStandingRule(test_authoring.AuthoringCase):
    def test_a_rule(self):
        row = self.build()
        assert_modern(self, row["config"])


class TestTheWriterRespellsBeforeSaving(WriterCase):
    def test_a_legacy_proposal_goes_down_in_the_new_words(self):
        self.house()
        out = self.apply(proposal())
        self.assertTrue(out["ok"], out)
        rows = self.yaml_rows()
        assert_modern(self, rows[-1])
        self.assertEqual(list(rows[-1])[3:7],
                         ["triggers", "conditions", "actions", "mode"])

    def test_the_persons_own_entry_is_untouched(self):
        self.house()
        self.apply(proposal())
        text = (self.config / "automations.yaml").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(EXISTING))

    def test_the_entry_for_a_second_example(self):
        row = proposal()
        row["config"] = {"trigger": {"platform": "sun", "event": "sunset"},
                         "action": [{"service": "light.turn_on"}]}
        entry = self.w.entry_for(row, 1_700_000_000)
        assert_modern(self, entry)


class TestAnEditKeepsThePersonsSpelling(unittest.TestCase):
    """The condition miner edits somebody's own automation: the condition
    it adds goes under the spelling that entry already uses."""

    def test_both_spellings(self):
        import conditions
        cond = {"condition": "time", "after": "09:00:00"}
        old = {"id": "1", "trigger": [], "action": []}
        new = {"id": "1", "triggers": [], "actions": []}
        self.assertIn("condition", conditions.with_condition(old, cond))
        self.assertNotIn("conditions", conditions.with_condition(old, cond))
        self.assertIn("conditions", conditions.with_condition(new, cond))
        self.assertNotIn("condition", conditions.with_condition(new, cond))


class TestTheSpellingFollowsTheRunningCore(WriterCase):
    """The plural keys load only on Home Assistant 2024.10 and later; an
    older Core refuses the whole automations.yaml over one entry spelled
    that way. The writer reads the version the checks pass recorded."""

    def written(self, version):
        self.w.CORE_VERSION["version"] = ""
        if version:
            self.w.note_core_version(version)
        self.house()
        out = self.apply(proposal())
        self.assertTrue(out["ok"], out)
        return self.yaml_rows()[-1]

    def test_a_current_core_gets_the_new_words(self):
        assert_modern(self, self.written("2026.8.1"))
        assert_modern(self, self.written("2024.10.0"))

    def test_an_older_core_gets_the_old_ones(self):
        entry = self.written("2024.9.3")
        self.assertFalse({"triggers", "conditions", "actions"} & set(entry))
        self.assertEqual(entry["trigger"], [{"platform": "time", "at": "18:40:00"}])
        self.assertIn("condition", entry)
        self.assertIn("action", entry)

    def test_an_unknown_version_gets_the_new_words(self):
        assert_modern(self, self.written(""))
        assert_modern(self, self.written("not a version"))

    def test_the_panel_records_the_version_off_the_checks_snapshot(self):
        import server
        self.w.CORE_VERSION["version"] = ""
        server.automation_writer.CORE_VERSION["version"] = ""
        server._note_registry({"supervisor": {"core": {"version": "2024.6.4"}}})
        self.assertEqual(server.automation_writer.CORE_VERSION["version"],
                         "2024.6.4")
        self.assertFalse(server.automation_writer.modern_keys_ok())
        server.automation_writer.CORE_VERSION["version"] = ""


class TestTheIdentityDidNotMove(unittest.TestCase):
    def test_a_respelled_proposal_hashes_as_it_did(self):
        old = proposal()["config"]
        new = automation_keys.modern(old)
        self.assertNotEqual(old, new)
        self.assertEqual(proposals.key_for({"kind": "automation", "config": old}),
                         proposals.key_for({"kind": "automation", "config": new}))

    def test_the_round_trip(self):
        old = proposal()["config"]
        self.assertEqual(automation_keys.legacy(automation_keys.modern(old)), old)


class TestEveryReaderTakesBoth(unittest.TestCase):
    def configs(self):
        old = {"trigger": [{"platform": "state", "entity_id": "binary_sensor.door",
                            "to": "on"}],
               "condition": [{"condition": "state", "entity_id": "sun.sun",
                              "state": "below_horizon"}],
               "action": [{"service": "light.turn_on",
                           "target": {"entity_id": "light.porch"}}]}
        return old, automation_keys.modern(old)

    def test_shadow(self):
        old, new = self.configs()
        for config in (old, new):
            with self.subTest(keys=sorted(config)):
                shadow.check_replayable(config)
                self.assertEqual(shadow.entities_watched(config),
                                 shadow.entities_watched(old))
                self.assertEqual(shadow.would_do(config), shadow.would_do(old))

    def test_the_checks(self):
        old, new = self.configs()
        self.assertEqual(
            [auto_checks._trigger_kind(t) for t in auto_checks._triggers(new)],
            [auto_checks._trigger_kind(t) for t in auto_checks._triggers(old)])
        from checks._util import House
        house = House(test_playbooks.house())
        self.assertEqual(
            [auto_checks._watched(house, t) for t in auto_checks._triggers(new)],
            [auto_checks._watched(house, t) for t in auto_checks._triggers(old)])
        # The interlock rule reads both too (`_polled_guard`).
        poll_old = {"trigger": [{"platform": "time_pattern", "minutes": "/1"}],
                    "condition": [{"condition": "state",
                                   "entity_id": "switch.pump", "state": "on"}]}
        self.assertTrue(auto_checks._polled_guard(poll_old))
        self.assertTrue(auto_checks._polled_guard(
            automation_keys.modern(poll_old)))


if __name__ == "__main__":
    unittest.main()
