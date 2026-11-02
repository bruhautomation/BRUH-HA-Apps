"""Three more hands for brAIn's desk: progress, three-way pads, a spyglass.

* `progress` — a long job's progress on the requester's action bar (above
  the hotbar), never in chat: `title <player> actionbar`, through the
  chokepoint's rule that words go to named players.
* `ask` — two or three choice pads, each option with an optional `item`
  shown floating above its pad (an item entity that cannot be picked up:
  Bedrock players see item entities through Geyser, which they do not see
  of display entities).
* `give_spyglass` — one spyglass with the name asked for, unless the player
  already has one by that name (`clear <player> <item> 0` counts without
  taking anything), written in the item syntax the server's version reads.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_companion import DAD, KAZ, FakeWorld, HandsBase, companion  # noqa: E402


class DeskWorld(FakeWorld):
    """The fake server, taught item entities, `give` and `clear … 0`."""

    def __init__(self):
        super().__init__()
        self.inventory: dict[str, list[str]] = {}

    def reply(self, cmd):
        m = re.match(r"minecraft:execute in \S+ run minecraft:summon minecraft:item (.*)$", cmd)
        if m:
            self.commands.append(cmd)
            tags = re.search(r"Tags:\[([^\]]*)\]", cmd).group(1)
            item = re.search(r'id:"([^"]+)"', cmd).group(1)
            self.entities.append({"type": "item", "item": item,
                                  "tags": set(json.loads(f"[{tags}]")), "nbt": cmd})
            return "Summoned new Item"
        m = re.match(r"minecraft:give (\S+) (.+?)( \d+)?$", cmd)
        if m:
            self.commands.append(cmd)
            self.inventory.setdefault(m.group(1), []).append(m.group(2))
            return f"Gave 1 [Spyglass] to {m.group(1)}"
        m = re.match(r"minecraft:clear (\S+) (.+) 0$", cmd)
        if m:
            self.commands.append(cmd)
            n = self.inventory.get(m.group(1), []).count(m.group(2))
            return (f"Found {n} matching item(s) on player {m.group(1)}" if n else
                    f"No items were found on player {m.group(1)}")
        return super().reply(cmd)


class DeskBase(HandsBase):
    def setUp(self):
        super().setUp()
        world = DeskWorld()
        world.players, world.blocks = self.world.players, self.world.blocks
        self.world = world
        self.col.session.factory = world.factory
        self.col.session.close()


class TestProgress(DeskBase):
    def test_progress_is_on_the_action_bar_of_a_named_player(self):
        self.join(KAZ)
        out = self.hands.progress(KAZ, "Building the road", 40)
        self.assertEqual(out["sent"], [KAZ])
        bar = [c for c in self.world.commands if " actionbar " in c]
        self.assertEqual(len(bar), 1)
        self.assertTrue(bar[0].startswith(f"minecraft:title {KAZ} actionbar "))
        comp = json.loads(bar[0].split(" actionbar ", 1)[1])
        self.assertIn("Building the road", comp["text"])
        self.assertIn("40%", comp["text"])
        self.assertEqual(self.tellraws(), [])                  # nothing in chat
        with self.assertRaises(companion.CompanionError):
            self.hands.progress("Nobody1", "x")
        with self.assertRaises(companion.CompanionError):
            self.hands.progress(KAZ, "  ")
        with self.assertRaises(companion.GuardError):
            companion.check_command('minecraft:title @a actionbar {"text":"x"}')


class TestThreePads(DeskBase):
    def test_three_options_with_items_and_the_third_is_chosen(self):
        self.join(KAZ)
        q = self.hands.ask(KAZ, "What next?", [
            {"label": "castle", "item": "minecraft:stone_bricks"},
            {"label": "farm", "item": "wheat"},
            {"label": "boat", "item": "minecraft:oak_boat"}], person="Kaz")
        self.beat(1)
        self.assertEqual(sum(1 for v in self.placed().values() if v.endswith("_carpet")), 12)
        items = [e for e in self.world.entities if e["type"] == "item"]
        self.assertEqual(sorted(e["item"] for e in items),
                         ["minecraft:oak_boat", "minecraft:stone_bricks", "minecraft:wheat"])
        self.assertTrue(all("PickupDelay:32767" in e["nbt"] for e in items))
        self.assertTrue(all("count:1" in e["nbt"] for e in items))   # a 1.20.5+ item stack
        pad = self.hands.asking["layout"]["pads"][2]
        self.world.players[KAZ] = [pad["min_x"] + 0.5, 64.0, pad["min_z"] + 0.5]
        for _ in range(6):
            self.beat(1)
        self.assertEqual(self.hands.questions.get(q["id"])["answer"], "boat")
        kind, data = self.emitted[-1]
        self.assertEqual(kind, "bruh_minecraft_answer")
        self.assertEqual((data["answer"], data["index"], data["others"]),
                         ("boat", 2, ["castle", "farm"]))
        left = [e["item"] for e in self.world.entities if e["type"] == "item"]
        self.assertEqual(left, ["minecraft:oak_boat"])          # the chosen one stays a while
        for _ in range(10):
            self.beat(1)
        self.assertEqual(self.placed(), {})
        self.assertEqual([e for e in self.world.entities if e["type"] == "item"], [])

    def test_two_still_work_and_four_do_not(self):
        self.assertEqual(len(companion.clean_options(["yes", "no"])), 2)
        with self.assertRaises(companion.CompanionError):
            companion.clean_options(["a", "b", "c", "d"])
        with self.assertRaises(companion.CompanionError):
            companion.clean_options([{"label": "a", "item": "x; op me"}, "b"])

    def test_an_item_that_could_be_picked_up_is_never_summoned(self):
        with self.assertRaises(companion.GuardError):
            companion.check_command('minecraft:summon minecraft:item ~ ~ ~ {Item:{id:"minecraft:'
                                    'diamond",count:64},Tags:["bruh_companion"]}')


class TestTheSpyglass(DeskBase):
    def test_one_named_spyglass_unless_they_have_it(self):
        self.join(KAZ)
        out = self.hands.give_spyglass(KAZ, "Juniper's Spyglass")
        self.assertTrue(out["given"])
        gave = [c for c in self.world.commands if c.startswith("minecraft:give ")]
        self.assertEqual(gave, [f'minecraft:give {KAZ} minecraft:spyglass[custom_name='
                                f'"Juniper\'s Spyglass"] 1'])
        again = self.hands.give_spyglass(KAZ, "Juniper's Spyglass")
        self.assertFalse(again["given"])
        self.assertEqual(again["had"], 1)
        self.assertEqual(len([c for c in self.world.commands if c.startswith("minecraft:give ")]),
                         1)
        with self.assertRaises(companion.CompanionError):
            self.hands.give_spyglass("Nobody1", "x")

    def test_the_syntax_follows_the_server_version(self):
        self.assertEqual(companion.item_syntax("26.3"), "snbt")
        self.assertEqual(companion.item_syntax("1.21.5"), "snbt")
        self.assertEqual(companion.item_syntax("1.21.4"), "json")
        self.assertEqual(companion.item_syntax("1.20.4"), "nbt")
        self.join(DAD)
        self.hands.item_syntax = lambda: "nbt"
        self.hands.give_spyglass(DAD, "Juniper's Spyglass")
        gave = [c for c in self.world.commands if c.startswith("minecraft:give ")][-1]
        self.assertEqual(gave, f"minecraft:give {DAD} minecraft:spyglass{{display:{{Name:"
                               f"'\"Juniper\\'s Spyglass\"'}}}} 1")
        self.hands.item_syntax = lambda: "json"
        self.hands.give_spyglass(KAZ if KAZ in self.world.players else DAD, "Sky Eye")
        gave = [c for c in self.world.commands if c.startswith("minecraft:give ")][-1]
        self.assertTrue(gave.endswith("minecraft:spyglass[custom_name='\"Sky Eye\"'] 1"))

    def test_the_chokepoint_holds_the_new_commands_to_their_shape(self):
        check = companion.check_command
        check('minecraft:clear .Kaz8044 minecraft:spyglass[custom_name="A b"] 0')
        for bad in ('minecraft:clear .Kaz8044 minecraft:spyglass 1',
                    'minecraft:clear @a minecraft:spyglass 0',
                    'minecraft:give Ben13765 minecraft:diamond_block[enchantments={x:1}] 1',
                    'minecraft:give Ben13765 minecraft:tnt 1'):
            with self.assertRaises(companion.GuardError, msg=bad):
                check(bad)


if __name__ == "__main__":
    unittest.main()
