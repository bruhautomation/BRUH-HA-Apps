"""The companion knows what it may do for each person, this minute (#675).

The owner: *"I'm getting stuff like <the house's name> can't trigger lights
from the chat, but then it actually does. Make sure <it> understands its
capabilities depending on what's enabled. It could be different per user."*

The paragraph every game run is told about what it may do was a fixed text
per scope: a trusted grown-up's run said "a house change may wait for a
person's approval" whatever the switch said, and a job's worker had no word
on linking the game to the house (one gave up asking for "a link from the
game to the house"). It is now built for each run from the person's row
("Can ask for anything"), the switch the panel publishes (`house.json`:
"Let brAIn act without asking", YOLO mode), the run's channel and a child's
bedtime — one function, `minecraft_rules.capabilities`, for the chat line's
run and the worker's alike.

And a second thing answering as the companion — an automation that speaks
in the game under its name, or hands the game's chat to a voice assistant —
is a finding (`auto.second_responder`), because two answers under one name
is exactly "it can't … but then it does".
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "brain" / "panel"))

from test_brain_minecraft_faculty import DAD, KAZ, MUM, mc  # noqa: E402
from test_minecraft_desk import DeskCase  # noqa: E402

import minecraft_companion as mcp  # noqa: E402
from checks import automations as auto  # noqa: E402

rules = mc.rules
OUTSIDE = rules.CANNED["outside"]
PEOPLE = [
    {"person": "Dad", "role": "reader", "players": [DAD], "trusted": True},
    {"person": "Mum", "role": "reader", "players": [MUM]},
    {"person": "Kaz", "role": "child", "players": [KAZ]},
]
LIGHTS = "turn on the kitchen lights"


class CapsCase(DeskCase):
    settings = {"enabled": True, "people": PEOPLE, "saved_at": 1, "greet": False,
                "spyglass": False}

    def house(self, acts, yolo=False):
        (self.shared / "minecraft" / "house.json").write_text(
            json.dumps({"acts": acts, "yolo": yolo}))

    def last_quick(self):
        return self.brain.of("quick")[-1]


class TestOneAnswerThatDoesIt(CapsCase):
    def test_house_control_on_and_acting_is_told_to_do_it_and_answers_once(self):
        self.house(True)
        self.join(DAD)
        self.chat(DAD, LIGHTS)
        turn = self.last_quick()
        self.assertEqual(turn["tools"], mc.TRUSTED_TOOLS)
        prompt = turn["prompt"]
        self.assertIn("happens the moment you call it", prompt)
        self.assertIn("Never say you cannot reach the house", prompt)
        self.assertNotIn("may wait for a person's approval", prompt)
        self.assertNotIn(OUTSIDE, prompt)
        # One run, one line in the game.
        self.assertEqual(len(self.brain.of("quick")), 1)
        self.assertEqual(self.lines_to(DAD), ["Sure!"])

    def test_house_control_off_gets_one_plain_line_naming_a_parent(self):
        self.house(True)
        self.join(MUM)
        self.chat(MUM, LIGHTS)
        turn = self.last_quick()
        self.assertEqual(turn["tools"], mc.TALK_TOOLS)
        self.assertIn("is off for Mum", turn["prompt"])
        self.assertIn(f"Reply exactly “{OUTSIDE}”", turn["prompt"])
        self.assertIn("A parent can turn on", OUTSIDE)
        self.assertNotIn("happens the moment", turn["prompt"])
        self.assertNotIn("approv", turn["prompt"].lower())

    def test_a_child_is_told_the_house_is_never_theirs_and_bedtime_when_it_is(self):
        self.write_settings(**{**self.settings, "bedtime_entity": "input_boolean.bed"})
        self.states["input_boolean.bed"] = "off"
        self.join(KAZ)
        self.chat(KAZ, LIGHTS)
        self.assertIn("Kaz is a child", self.last_quick()["prompt"])
        self.assertNotIn("bedtime now", self.last_quick()["prompt"])
        caps = rules.capabilities({"person": "Kaz", "role": "child"}, trusted=False,
                                  bedtime=True)
        self.assertIn("It is Kaz's bedtime now", caps)


class TestTheTextFollowsTheToggles(CapsCase):
    def test_the_switch_moving_changes_the_paragraph(self):
        self.join(DAD)
        self.house(True)
        self.chat(DAD, LIGHTS)
        acting = self.last_quick()["prompt"]
        self.house(False)
        self.chat(DAD, LIGHTS)
        asking = self.last_quick()["prompt"]
        self.assertIn("happens the moment you call it", acting)
        self.assertIn("has NOT happened yet", asking)
        self.assertIn("never that it is done", asking)
        self.assertNotIn("happens the moment", asking)
        self.house(True, yolo=True)
        self.chat(DAD, LIGHTS)
        self.assertIn("YOLO mode is on", self.last_quick()["prompt"])

    def test_a_persons_toggle_moving_changes_their_scope_and_paragraph(self):
        self.house(True)
        self.join(DAD)
        self.chat(DAD, LIGHTS)
        self.assertEqual(self.last_quick()["tools"], mc.TRUSTED_TOOLS)
        off = [dict(p, trusted=False) if p["person"] == "Dad" else p for p in PEOPLE]
        self.write_settings(**{**self.settings, "people": off})
        self.chat(DAD, LIGHTS)
        turn = self.last_quick()
        self.assertEqual(turn["tools"], mc.TALK_TOOLS)
        self.assertIn("is off for Dad", turn["prompt"])
        self.assertIn(OUTSIDE, turn["prompt"])
        # And on again for Mum: her paragraph moves the other way.
        on = [dict(p, trusted=True) if p["person"] == "Mum" else p for p in PEOPLE]
        self.write_settings(**{**self.settings, "people": on})
        self.join(MUM)
        self.chat(MUM, LIGHTS)
        self.assertEqual(self.last_quick()["tools"], mc.TRUSTED_TOOLS)
        self.assertIn("House control is on for them", self.last_quick()["prompt"])

    def test_without_a_published_switch_it_says_a_change_may_wait(self):
        self.join(DAD)
        self.chat(DAD, LIGHTS)
        self.assertIn("may wait for a person's approval", self.last_quick()["prompt"])


class TestTheWorkerGetsTheSameParagraph(CapsCase):
    def test_chat_and_worker_carry_the_same_block(self):
        for acts in (True, False):
            with self.subTest(acts=acts):
                self.house(acts)
                self.join(DAD)
                self.brain.quick.append({"reply": "On it.", "job": {
                    "title": f"a light switch {acts}", "brief": "a lever that turns on the porch light"}})
                self.chat(DAD, "make a lever that turns on the porch light")
                block = rules.capabilities(
                    {"person": "Dad", "role": "reader", "trusted": True}, trusted=True,
                    house={"acts": acts, "yolo": False})
                quick, work = self.last_quick(), self.brain.of("work")[-1]
                self.assertEqual(work["tools"], mc.TRUSTED_TOOLS)
                self.assertIn(block, quick["prompt"])
                self.assertIn(block, work["prompt"])
                # The worker knows the link is its to make.
                self.assertIn("bruh_minecraft_chat", work["prompt"])

    def test_a_guarded_worker_says_the_parent_line_too(self):
        self.join(MUM)
        self.brain.quick.append({"reply": "On it.", "job": {"title": "a lamp", "brief": "x"}})
        self.chat(MUM, "make a lever for the lights")
        self.assertIn(OUTSIDE, self.brain.of("work")[-1]["prompt"])


class TestThePanelPublishesTheSwitch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.shared = Path(self.tmp.name)

    def test_written_beside_the_settings_and_only_when_it_moved(self):
        self.assertFalse(mcp.publish_house(True, False, str(self.shared)))   # no folder
        (self.shared / "minecraft").mkdir()
        (self.shared / "minecraft" / "settings.json").write_text("{}")
        self.assertTrue(mcp.publish_house(True, False, str(self.shared)))
        self.assertFalse(mcp.publish_house(True, False, str(self.shared)))
        self.assertEqual(rules.house_access(str(self.shared)), {"acts": True, "yolo": False})
        self.assertTrue(mcp.publish_house(False, False, str(self.shared)))
        self.assertEqual(rules.house_access(str(self.shared))["acts"], False)

    def test_the_servers_permission_publish_carries_it(self):
        src = (HERE.parent / "brain" / "panel" / "server.py").read_text(encoding="utf-8")
        body = src.split("def _publish_permission_mode() -> None:", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_publish_minecraft_house()", body)


# ---------------------------------------------------------------------------
# A second thing answering as the companion
# ---------------------------------------------------------------------------
def _snap(automations, scripts=None, name="Juniper"):
    return {"automations": automations, "scripts": scripts or {}, "states": {},
            "entities": [], "devices": [], "areas": [], "assistant_name": name}


FORWARD = {"id": "mc_assist", "alias": "Minecraft chat to Assist",
           "triggers": [{"trigger": "event", "event_type": "bruh_minecraft_chat"}],
           "actions": [{"action": "conversation.process",
                        "data": {"text": "{{ trigger.event.data.text }}"}},
                       {"action": "bruh_minecraft.rcon_command",
                        "data": {"command": "say {{ response }}"}}]}
TELLRAW = {"id": "mc_hello", "alias": "Say hello in game",
           "triggers": [{"trigger": "state", "entity_id": "sensor.mc_players"}],
           "actions": [{"action": "bruh_minecraft.rcon_command", "data": {
               "command": 'tellraw @a {"text":"<Juniper> welcome back!"}'}}]}
HARMLESS = {"id": "mc_wash", "alias": "Tell the game the wash is done",
            "triggers": [{"trigger": "state", "entity_id": "sensor.washer"}],
            "actions": [{"action": "bruh_minecraft.rcon_command",
                         "data": {"command": "say The washing is done"}}]}


class TestASecondResponderIsAFinding(unittest.TestCase):
    def test_an_automation_forwarding_the_games_chat_is_named(self):
        rows = auto.second_responder(_snap([FORWARD]), 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "Two things answer as Juniper in the game: "
                                          "Automation 'Minecraft chat to Assist'")
        self.assertIn("voice assistant", rows[0]["detail"])

    def test_a_tellraw_under_the_companions_name_is_named_and_a_script_too(self):
        rows = auto.second_responder(_snap([TELLRAW], {"greet": {
            "alias": "Greet", "sequence": [{"action": "bruh_minecraft.companion_say",
                                            "data": {"message": "hi"}}]}}), 0)
        self.assertEqual([r["text"].split(": ", 1)[1] for r in rows],
                         ["Automation 'Say hello in game'", "Script 'Greet'"])

    def test_a_line_that_is_not_the_companion_and_a_switched_off_step_are_left(self):
        off = json.loads(json.dumps(FORWARD))
        for step in off["actions"]:
            step["enabled"] = False
        self.assertEqual(auto.second_responder(_snap([HARMLESS, off]), 0), [])

    def test_it_is_in_the_catalog(self):
        import checks
        self.assertIn("auto.second_responder", checks.CHECK_IDS)
        self.assertNotIn("auto.second_responder", checks.SHADOW)


if __name__ == "__main__":
    unittest.main()
