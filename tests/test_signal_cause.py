#!/usr/bin/env python3
"""A change a scene, an automation or a script made says so (#259).

The look filed cases that lights had turned off unexpectedly when a scene
had turned them off. A state change carries a context id and Home Assistant
gives the scene's own state change, and every light it then sets, that same
id — the logbook's first rule for "what caused this". The bus remembers the
runner a context belongs to for a short while, and a signal for a change in
that context says which scene, automation or script made it, in the row the
look reads. Nothing is dropped: the change is still offered, with its cause.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import eventbus  # noqa: E402
import signals  # noqa: E402

NOW = 1_789_800_000.0


def event(entity_id, to, was, context_id, name=None, user_id=None):
    attrs = {"friendly_name": name} if name else {}
    ctx = {"id": context_id, "user_id": user_id, "parent_id": None}
    return {
        "event_type": "state_changed",
        "context": ctx,
        "data": {
            "entity_id": entity_id,
            "old_state": {"entity_id": entity_id, "state": was,
                          "attributes": attrs},
            "new_state": {"entity_id": entity_id, "state": to,
                          "attributes": attrs, "context": ctx},
        },
    }


class Bus(unittest.TestCase):
    def setUp(self):
        self.signals = []
        self.clock = [NOW]
        self.bus = eventbus.EventBus(
            self.signals.append, clock=lambda: self.clock[0],
            known_ids=lambda: {"light.kitchen", "light.hall"})

    def test_a_light_a_scene_turned_off_says_the_scene_did(self):
        self.bus._handle(event("scene.goodnight", "2026-10-19T22:00:00",
                               "2026-10-18T22:00:00", "C1", "Goodnight"))
        self.bus._handle(event("light.kitchen", "off", "on", "C1",
                               "Kitchen"))
        self.assertEqual(len(self.signals), 1)
        text = self.signals[0]["text"]
        self.assertIn("Kitchen on → off", text)
        self.assertIn("the scene Goodnight", text)

    def test_an_automation_and_a_script_say_so_too(self):
        self.bus._handle(event("automation.lights_out", "on", "on", "C2",
                               "Lights out"))
        self.bus._handle(event("light.kitchen", "off", "on", "C2", "Kitchen"))
        self.bus._handle(event("script.wind_down", "on", "off", "C3",
                               "Wind down"))
        self.bus._handle(event("light.hall", "off", "on", "C3", "Hall"))
        texts = [s["text"] for s in self.signals]
        self.assertIn("the automation Lights out", texts[0])
        self.assertIn("the script Wind down", texts[1])

    def test_a_change_in_another_context_carries_no_cause(self):
        self.bus._handle(event("scene.goodnight", "x", "y", "C1", "Goodnight"))
        self.bus._handle(event("light.kitchen", "off", "on", "C9", "Kitchen"))
        self.assertNotIn("scene", self.signals[0]["text"])

    def test_the_memory_is_short(self):
        self.bus._handle(event("scene.goodnight", "x", "y", "C1", "Goodnight"))
        self.clock[0] = NOW + eventbus.CAUSE_TTL_S + 1
        self.bus._handle(event("light.kitchen", "off", "on", "C1", "Kitchen"))
        self.assertNotIn("scene", self.signals[0]["text"])


class Builder(unittest.TestCase):
    def test_the_builder_states_a_cause_it_is_handed(self):
        ctx = signals.RegistryContext(known=frozenset({"light.kitchen"}))
        sig = signals.from_state_change(
            event("light.kitchen", "off", "on", "C1", "Kitchen")["data"],
            ctx, NOW, cause={"entity_id": "scene.goodnight",
                             "name": "Goodnight"})
        self.assertIn("set by the scene Goodnight", sig["text"])
        plain = signals.from_state_change(
            event("light.kitchen", "off", "on", "C1", "Kitchen")["data"],
            ctx, NOW)
        self.assertEqual(plain["text"], "Kitchen on → off")


if __name__ == "__main__":
    unittest.main()
