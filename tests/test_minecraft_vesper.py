#!/usr/bin/env python3
"""Vesper in the game (#572): the engine in bruh-minecraft-server/panel/vesper.py.

Driven through the real WorldCollector against a fake Paper server that
keeps a block map and the entities Vesper summons, and answers RCON the way
the server does ("Test passed", "Changed the block at …", "Summoned new
Allay"). Covered: nothing is sent while nobody is on; a child's join
summons Vesper (tagged) and the greeting cleans itself up; choice pads are
built only on clear natural ground and outside protected zones and builds,
standing on one for two seconds answers, the answer lands in memory and the
pads go; undo puts back only what still holds Vesper's blocks; bedtime,
budgets, cooldowns and the session cap; the command chokepoint; Bedrock's
dotted names; the panel's routes, including renaming to "Vesper World".
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import AioHTTPTestCase

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "bruh-minecraft-server" / "panel"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PANEL / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mcworld = _load("test_vesper_mc_world", "mcworld.py")
vesper = _load("test_vesper_engine", "vesper.py")

KAZ = ".Kaz8044"     # a Bedrock player through Geyser: the dot is part of the name
LEV = ".Lev6398"
DAD = "Ben13765"
COLLECTOR_ASKS = ("minecraft:list", "minecraft:time", "minecraft:execute if predicate",
                  "minecraft:data get")
GROUND_Y = 63         # grass at y=63, players stand at y=64


class FakeWorld:
    """A Paper server's answers, from a block map and a list of entities."""

    def __init__(self):
        self.players: dict[str, list[float]] = {}
        self.blocks: dict[tuple[str, int, int, int], str] = {}
        self.entities: list[dict] = []
        self.commands: list[str] = []
        self.up = True

    # -- the world ------------------------------------------------------------
    def block(self, dim: str, x: int, y: int, z: int) -> str:
        if (dim, x, y, z) in self.blocks:
            return self.blocks[(dim, x, y, z)]
        return "minecraft:grass_block" if y <= GROUND_Y else "minecraft:air"

    @staticmethod
    def matches(block: str, want: str) -> bool:
        tags = {"#minecraft:dirt": {"minecraft:grass_block", "minecraft:dirt"},
                "#minecraft:sand": {"minecraft:sand"},
                "#minecraft:base_stone_overworld": {"minecraft:stone"}}
        if want.startswith("#"):
            return block in tags.get(want, set())
        return block == want

    def engine_commands(self) -> list[str]:
        return [c for c in self.commands if not c.startswith(COLLECTOR_ASKS)]

    # -- RCON -----------------------------------------------------------------
    def reply(self, cmd: str) -> str:
        self.commands.append(cmd)
        if cmd == "minecraft:list":
            names = list(self.players)
            return f"There are {len(names)} of a max of 20 players online: " + ", ".join(names)
        if cmd.startswith("minecraft:time query"):
            return "The time is 1000"
        if cmd.startswith("minecraft:execute if predicate"):
            return "Test failed"
        if cmd.startswith("minecraft:data get entity "):
            name, path = cmd[len("minecraft:data get entity "):].rsplit(" ", 1)
            name = json.loads(name) if name.startswith('"') else name
            pos = self.players.get(name)
            if pos is None:
                return "No entity was found"
            value = {"Pos": f"[{pos[0]}d, {pos[1]}d, {pos[2]}d]",
                     "Dimension": '"minecraft:overworld"', "Health": "20.0f",
                     "foodLevel": "20", "playerGameType": "0"}[path]
            return f"{name} has the following entity data: {value}"
        dim = "minecraft:overworld"
        m = re.match(r"minecraft:execute in (\S+) (.*)$", cmd)
        rest = cmd
        if m:
            dim, rest = m.group(1), m.group(2)
        m = re.match(r"if block (-?\d+) (-?\d+) (-?\d+) (\S+)$", rest)
        if m:
            x, y, z = (int(v) for v in m.groups()[:3])
            return "Test passed" if self.matches(self.block(dim, x, y, z), m.group(4)) else "Test failed"
        m = re.match(r"if entity @a\[name=([^,]+),x=(-?\d+),y=(-?\d+),z=(-?\d+),dx=(\d+),dy=(\d+),dz=(\d+)\]$",
                     rest)
        if m:
            name = m.group(1)
            x, y, z, dx, dy, dz = (int(v) for v in m.groups()[1:])
            pos = self.players.get(name)
            inside = pos is not None and (x <= pos[0] < x + dx + 1 and y <= pos[1] < y + dy + 1
                                          and z <= pos[2] < z + dz + 1)
            return "Test passed" if inside else "Test failed"
        m = re.match(r"run minecraft:setblock (-?\d+) (-?\d+) (-?\d+) (\S+)( keep)?$", rest)
        if m:
            x, y, z = (int(v) for v in m.groups()[:3])
            if m.group(5) and self.block(dim, x, y, z) != "minecraft:air":
                return "Could not set the block"
            self.blocks[(dim, x, y, z)] = m.group(4)
            return f"Changed the block at {x}, {y}, {z}"
        if "summon minecraft:allay " in cmd:
            tags = re.search(r"Tags:\[([^\]]*)\]", cmd).group(1)
            self.entities.append({"type": "allay", "tags": set(json.loads(f"[{tags}]")),
                                  "nbt": cmd})
            return "Summoned new Allay"
        m = re.match(r"minecraft:kill @e\[(.*)\]$", cmd)
        if m:
            conds = m.group(1).split(",")
            before = len(self.entities)
            self.entities = [e for e in self.entities if not all(
                (c[4:] in e["tags"]) if not c.startswith("tag=!") else (c[5:] not in e["tags"])
                for c in conds if c.startswith("tag="))]
            gone = before - len(self.entities)
            return f"Killed {gone} entities" if gone else "No entity was found"
        return "ok"

    def factory(self):
        world = self

        class Conn:
            def connect(self):
                if not world.up:
                    raise ConnectionRefusedError("refused")

            def command(self, cmd):
                return world.reply(cmd)

            def close(self):
                pass

        return Conn()


class Clock:
    def __init__(self, t=1_761_900_000.0):
        self.t = t

    def __call__(self):
        return self.t


class EngineBase(unittest.TestCase):
    limits = {"actions": 120, "events": 40}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.server_dir = self.root / "server"
        (self.server_dir / "logs").mkdir(parents=True)
        self.log = self.server_dir / "logs" / "latest.log"
        self.log.write_text("[09:00:00] [Server thread/INFO]: Starting minecraft server\n")
        self.world = FakeWorld()
        self.clock = Clock()
        self.col = mcworld.WorldCollector(
            rcon_factory=self.world.factory, server_dir=self.server_dir,
            out_path=self.root / "world.json", clock=self.clock)
        self.on = True
        self.bed: bool | None = False
        self.emitted: list[tuple[str, dict]] = []
        self.snapshots: list[str] = []
        self.engine = vesper.Engine(
            self.col, enabled=lambda: self.on, bedtime=lambda rule: self.bed,
            emit=lambda kind, data: self.emitted.append((kind, data)),
            snapshot=self._snapshot, limits=lambda: dict(self.limits), clock=self.clock)
        self.engine.configure(on=True, bedtime_entity="input_boolean.kids_bedtime")
        self.engine.roster.save([
            {"person": "Kaz", "role": "child", "players": [KAZ]},
            {"person": "Lev", "role": "child", "players": [LEV]},
            {"person": "Dad", "role": "reader", "players": [DAD]}])
        self.snapshot_answer = None

    def _snapshot(self):
        self.snapshots.append("snap")
        return self.snapshot_answer

    def log_line(self, text: str) -> None:
        with open(self.log, "a") as f:
            f.write(f"[09:00:01] [Server thread/INFO]: {text}\n")

    def join(self, name: str, pos=(0.5, 64.0, 0.5)) -> None:
        self.world.players[name] = list(pos)
        self.log_line(f"{name} joined the game")
        self.beat(0)

    def leave(self, name: str) -> None:
        self.world.players.pop(name, None)
        self.log_line(f"{name} left the game")
        self.beat(0)

    def beat(self, seconds: float = 2.0) -> None:
        self.clock.t += seconds
        self.col.step()
        self.engine.step()

    def placed(self) -> dict:
        return {k: v for k, v in self.world.blocks.items() if v != "minecraft:air"}


# ---------------------------------------------------------------------------
# Quiet when nobody is on
# ---------------------------------------------------------------------------
class TestNothingRunsOffline(EngineBase):
    def test_nobody_online_sends_nothing_however_long(self):
        self.engine.ask("Kaz", "Do you want a castle?")
        for _ in range(40):
            self.beat(30)
        self.assertEqual(self.world.engine_commands(), [])
        self.assertEqual(self.emitted, [])
        self.assertEqual(self.engine.state, "idle")

    def test_switched_off_sends_nothing_with_a_child_on(self):
        self.engine.configure(on=False)
        self.join(KAZ)
        for _ in range(10):
            self.beat()
        self.assertEqual(self.world.engine_commands(), [])
        self.assertEqual(self.world.entities, [])

    def test_everyone_leaving_winds_down_then_goes_quiet(self):
        self.join(KAZ)
        self.assertEqual(len(self.world.entities), 1)
        self.leave(KAZ)
        self.assertEqual(self.world.entities, [])
        sent = len(self.world.engine_commands())
        for _ in range(20):
            self.beat(30)
        self.assertEqual(len(self.world.engine_commands()), sent)

    def test_off_until_switched_on_and_asking_while_off_is_refused(self):
        fresh = vesper.Engine(mcworld.WorldCollector(
            rcon_factory=self.world.factory, server_dir=self.root / "other",
            out_path=self.root / "other.json", clock=self.clock), clock=self.clock)
        self.assertFalse(fresh.enabled())
        self.assertEqual(fresh.settings()["daily_actions"], vesper.DAILY_ACTIONS)
        self.engine.configure(on=False)
        with self.assertRaises(vesper.VesperError):
            self.engine.ask("Kaz", "Castle?")

    def test_switching_off_mid_greeting_takes_vesper_away(self):
        self.join(KAZ)
        self.assertEqual(len(self.world.entities), 1)
        self.engine.configure(on=False)
        self.assertEqual(self.world.entities, [])

    def test_settings_are_checked(self):
        with self.assertRaises(vesper.VesperError):
            self.engine.configure(bedtime_entity="the kids' door")
        with self.assertRaises(vesper.VesperError):
            self.engine.configure(daily_actions="lots")
        self.engine.configure(bedtime_entity="binary_sensor.boys_door=off", daily_actions=5)
        self.assertEqual(self.engine.settings()["bedtime_entity"], "binary_sensor.boys_door=off")
        self.assertEqual(self.engine.settings()["daily_actions"], 5)
        own = vesper.Engine(self.col, clock=self.clock)       # the budget read from the settings
        self.assertEqual(own.budget.view()["actions_limit"], 5)


# ---------------------------------------------------------------------------
# M2: the greeting
# ---------------------------------------------------------------------------
class TestTheGreeting(EngineBase):
    def test_a_child_joining_brings_vesper_with_a_chime_and_a_wave(self):
        self.join(KAZ)
        self.assertEqual(len(self.world.entities), 1)
        body = self.world.entities[0]
        self.assertIn("vesper", body["tags"])
        self.assertIn(self.engine.epoch, body["tags"])
        self.assertIn("Invulnerable:1b", body["nbt"])
        self.assertIn("NoAI:1b", body["nbt"])
        self.assertIn("CustomName:", body["nbt"])
        sent = self.world.engine_commands()
        summon = next(c for c in sent if "summon" in c)
        self.assertTrue(summon.startswith(f"minecraft:execute at {KAZ} rotated ~ 0 run"), summon)
        self.assertEqual(sum("note_block.chime" in c for c in sent), 3)
        self.assertTrue(any("particle minecraft:happy_villager" in c for c in sent))
        act = self.engine.actions.list(1)[0]
        self.assertEqual((act["kind"], act["person"], act["status"]), ("greet", "Kaz", "active"))
        self.beat(1)
        self.assertTrue(any("tp @s ~ ~0.5 ~" in c for c in self.world.engine_commands()))
        # The moment went to Home Assistant for brAIn, with nobody else's news in it.
        kind, data = self.emitted[0]
        self.assertEqual(kind, "bruh_minecraft_moment")
        self.assertEqual((data["kind"], data["person"], data["role"]), ("join", "Kaz", "child"))
        self.assertNotIn("Lev", json.dumps(data))

    def test_the_greeting_cleans_itself_up(self):
        self.join(KAZ)
        tag = self.engine.actions.list(1)[0]["tag"]
        self.beat(vesper.GREETING_LIFETIME + 1)
        self.assertEqual(self.world.entities, [])
        self.assertIn(f"minecraft:kill @e[tag={tag}]", self.world.commands)
        self.assertEqual(self.engine.actions.list(1)[0]["status"], "done")
        self.assertEqual(self.engine.live, {})

    def test_a_child_leaving_takes_vesper_with_them(self):
        self.join(KAZ)
        self.leave(KAZ)
        self.assertEqual(self.world.entities, [])

    def test_strays_from_an_earlier_run_are_swept_by_tag(self):
        self.world.entities.append({"type": "allay", "tags": {"vesper", "vesper_eold"}, "nbt": ""})
        self.join(KAZ)
        self.assertEqual([e for e in self.world.entities if "vesper_eold" in e["tags"]], [])
        self.assertEqual(len(self.world.entities), 1)     # this run's greeting

    def test_a_reader_and_a_guest_get_no_body(self):
        self.join(DAD)
        self.join("Stranger1")
        self.assertEqual(self.world.entities, [])

    def test_no_second_greeting_within_the_cooldown(self):
        self.join(KAZ)
        self.leave(KAZ)
        self.clock.t += 60
        self.join(KAZ)
        self.assertEqual(self.world.entities, [])
        self.clock.t += vesper.GREET_COOLDOWN
        self.leave(KAZ)
        self.join(KAZ)
        self.assertEqual(len(self.world.entities), 1)

    def test_an_old_server_gets_the_name_as_a_json_string(self):
        self.engine.modern = lambda: False
        self.join(KAZ)
        self.assertIn("CustomName:'{\"text\": \"Vesper\"", self.world.entities[0]["nbt"])
        self.assertTrue(vesper.modern_text("26.3"))
        self.assertTrue(vesper.modern_text("1.21.5"))
        self.assertFalse(vesper.modern_text("1.21.4"))


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------
class TestGuardrails(EngineBase):
    def test_bedtime_says_goodnight_once_and_stops(self):
        self.join(KAZ)
        self.assertEqual(len(self.world.entities), 1)
        self.engine.ask("Kaz", "Castle?")
        self.bed = True
        self.beat()
        self.assertEqual(self.world.entities, [])
        sent = self.world.engine_commands()
        self.assertTrue(any(c.startswith(f"minecraft:title {KAZ} title") and "Goodnight" in c
                            for c in sent))
        count = len(sent)
        for _ in range(20):
            self.beat()
        self.assertEqual(len(self.world.engine_commands()), count)
        self.assertEqual(self.placed(), {})
        self.assertEqual(self.engine.state, "bedtime")

    def test_an_unreadable_bedtime_switch_holds_everything_new(self):
        self.bed = None
        self.join(KAZ)
        self.engine.ask("Kaz", "Castle?")
        for _ in range(5):
            self.beat()
        self.assertEqual(self.world.entities, [])
        self.assertEqual(self.placed(), {})
        self.assertEqual(self.engine.state, "waiting")

    def test_the_days_budget_stops_vesper(self):
        self.limits = {"actions": 1, "events": 40}
        self.join(KAZ)
        self.join(LEV)
        self.assertEqual(len(self.world.entities), 1)
        self.assertEqual(self.engine.budget.view()["actions"], 1)
        self.assertIn("budget", self.engine.can_act(LEV))

    def test_the_events_budget_and_moment_cooldowns(self):
        self.limits = {"actions": 120, "events": 1}
        self.join(KAZ)
        self.join(LEV)
        self.assertEqual(len(self.emitted), 1)
        self.limits = {"actions": 120, "events": 40}
        m1 = self.engine.moment("death", KAZ, 0.6)
        m2 = self.engine.moment("death", KAZ, 0.6)
        self.assertIsNotNone(m1)
        self.assertIsNone(m2)
        self.clock.t += vesper.MOMENT_COOLDOWN + 1
        self.assertIsNotNone(self.engine.moment("death", KAZ, 0.6))

    def test_a_session_has_a_cap(self):
        self.join(KAZ)
        self.engine.session_acts[KAZ] = vesper.SESSION_CAP
        self.assertIn("enough", self.engine.can_act(KAZ))

    def test_one_childs_news_never_reaches_another(self):
        self.join(LEV)
        self.assertFalse(self.engine.tell(LEV, "Kaz built a tower today!"))
        self.assertFalse(self.engine.tell(LEV, "kaz8044 is in the nether"))
        self.assertTrue(self.engine.tell(LEV, "You found a cave!"))
        self.assertTrue(self.engine.tell(KAZ, "Kaz, well done"))
        sent = [c for c in self.world.engine_commands() if "tellraw" in c]
        self.assertEqual(len(sent), 2)

    def test_the_chokepoint(self):
        check = vesper.check_command
        bad = [
            "minecraft:summon minecraft:zombie ~ ~ ~",
            'minecraft:execute at x run minecraft:summon minecraft:creeper ~ ~ ~ {Tags:["vesper"]}',
            "minecraft:summon minecraft:allay ~ ~ ~ {}",
            "minecraft:playsound minecraft:entity.wither.spawn master .Kaz ~ ~ ~ 0.5 1",
            "minecraft:playsound minecraft:block.note_block.chime master .Kaz ~ ~ ~ 1.0 1",
            "minecraft:playsound minecraft:block.note_block.chime master @a ~ ~ ~ 0.5 1",
            "minecraft:kill @a", "minecraft:kill @e[type=allay]",
            "minecraft:tellraw @a {}", "minecraft:title @a title {}",
            "minecraft:execute as .Kaz run minecraft:tp @s 0 0 0",
            "minecraft:setblock 0 64 0 minecraft:stone",
            "minecraft:execute in minecraft:overworld run minecraft:fill 0 0 0 9 9 9 minecraft:air",
            "minecraft:give .Kaz minecraft:tnt 1", "minecraft:give .Kaz minecraft:cake 64",
            "minecraft:op .Kaz", "minecraft:gamerule doDaylightCycle false",
            "minecraft:tellraw .Kaz {}\nop .Kaz",
        ]
        for cmd in bad:
            with self.subTest(cmd=cmd), self.assertRaises(vesper.GuardError):
                check(cmd)
        with self.assertRaises(vesper.GuardError):
            check("minecraft:execute in minecraft:overworld run minecraft:setblock 0 64 0 "
                  "minecraft:tnt keep", placing=True)
        check("minecraft:execute in minecraft:overworld run minecraft:setblock 0 64 0 "
              "minecraft:lime_carpet keep", placing=True)
        check("minecraft:give .Kaz minecraft:cake 1")
        check("minecraft:kill @e[tag=vesper,tag=!vesper_eabc]")
        # A message is not mistaken for a command chain by the words in it.
        check('minecraft:tellraw .Kaz {"text":"we run and run"}')


# ---------------------------------------------------------------------------
# M3: choice pads
# ---------------------------------------------------------------------------
class TestChoicePads(EngineBase):
    def ask_and_pose(self, options=None):
        self.join(KAZ)
        self.beat(vesper.GREETING_LIFETIME + 1)           # the greeting comes and goes
        q = self.engine.ask("Kaz", "Should we build a castle or a farm?", options)
        self.beat()
        return self.engine.questions.get(q["id"])

    def pad_cells(self, i):
        return self.engine.asking["layout"]["pads"][i]

    def test_pads_are_built_beside_the_child_on_natural_ground(self):
        q = self.ask_and_pose()
        self.assertEqual(q["status"], "open")
        blocks = self.placed()
        self.assertEqual(sum(b == "minecraft:lime_carpet" for b in blocks.values()), 4)
        self.assertEqual(sum(b == "minecraft:red_carpet" for b in blocks.values()), 4)
        self.assertEqual(sum(b == "minecraft:oak_fence" for b in blocks.values()), 2)
        self.assertEqual(sum(b in ("minecraft:lime_wool", "minecraft:red_wool")
                             for b in blocks.values()), 2)
        for (_, x, y, z), b in blocks.items():
            if b.endswith("carpet"):
                self.assertEqual(y, GROUND_Y + 1)
        act = self.engine.actions.get(q["action"])
        self.assertEqual(len(act["cells"]), 12)
        self.assertTrue(all(c["before"] == "minecraft:air" and c["placed"] for c in act["cells"]))
        self.assertTrue(all(" keep" in c for c in self.world.commands if "setblock" in c))

    def test_standing_on_a_pad_for_two_seconds_answers(self):
        q = self.ask_and_pose([{"label": "castle", "picture": "stone_bricks"},
                               {"label": "farm", "picture": "hay_block", "gift": "wheat_seeds",
                                "gift_count": 8}])
        pad = self.pad_cells(1)
        self.world.players[KAZ] = [pad["min_x"] + 1.0, GROUND_Y + 1.0625, pad["min_z"] + 1.0]
        self.beat(0.5)
        self.assertEqual(self.engine.questions.get(q["id"])["status"], "open")
        self.beat(1.0)
        self.assertEqual(self.engine.questions.get(q["id"])["status"], "open")
        self.beat(1.0)
        got = self.engine.questions.get(q["id"])
        self.assertEqual((got["status"], got["answer"]), ("answered", "farm"))
        self.assertIn(f"minecraft:give {KAZ} minecraft:wheat_seeds 8", self.world.commands)
        mem = self.engine.memory.get("Kaz")
        self.assertEqual(mem["answers"][-1]["answer"], "farm")
        self.assertEqual(mem["likes"], {"farm": 1})
        self.assertEqual(mem["dislikes"], {"castle": 1})
        # The result: the castle picture is gone, the farm one stays a moment.
        blocks = set(self.placed().values())
        self.assertNotIn("minecraft:stone_bricks", blocks)
        self.assertIn("minecraft:hay_block", blocks)
        self.assertTrue(any(k == "bruh_minecraft_moment" and d["kind"] == "answered"
                            and d["answer"] == "farm" for k, d in self.emitted))
        self.beat(vesper.RESULT_LINGER + 1)
        self.assertEqual(self.placed(), {})
        self.assertEqual(self.world.entities, [])
        self.assertIsNone(self.engine.asking)
        self.assertTrue(any(e.get("kind") == "vesper" and "chose farm" in e["text"]
                            for e in self.col.feed))

    def test_stepping_off_before_two_seconds_is_not_an_answer(self):
        q = self.ask_and_pose()
        pad = self.pad_cells(0)
        on = [pad["min_x"] + 0.5, GROUND_Y + 1.0625, pad["min_z"] + 0.5]
        self.world.players[KAZ] = on
        self.beat(0.5)
        self.world.players[KAZ] = [0.5, 64.0, 0.5]
        self.beat(1.5)
        self.world.players[KAZ] = on
        self.beat(1.5)
        self.assertEqual(self.engine.questions.get(q["id"])["status"], "open")
        self.beat(2.0)
        self.assertEqual(self.engine.questions.get(q["id"])["answer"], "yes")

    def test_nobody_answering_takes_the_pads_away(self):
        q = self.ask_and_pose()
        self.beat(vesper.QUESTION_TIMEOUT + 1)
        self.assertEqual(self.engine.questions.get(q["id"])["status"], "expired")
        self.assertEqual(self.placed(), {})

    def test_leaving_mid_question_takes_the_pads_and_asks_again_next_time(self):
        q = self.ask_and_pose()
        self.leave(KAZ)
        self.assertEqual(self.placed(), {})
        self.assertEqual(self.engine.questions.get(q["id"])["status"], "queued")

    def test_no_pads_over_a_protected_zone(self):
        self.engine.zones.save({"name": "Kaz's house", "x": 0, "z": 0, "radius": 10,
                                "protect": True})
        q = self.ask_and_pose()
        self.assertEqual(q["status"], "queued")
        self.assertIn("Kaz's house", q["note"])
        self.assertEqual(self.placed(), {})
        self.assertFalse([c for c in self.world.commands if "setblock" in c])

    def test_no_pads_over_a_build_in_the_log(self):
        self.col.builds.create({"title": "Lev's tower", "by": "Lev",
                                "bounds": {"x1": -8, "z1": -8, "x2": 8, "z2": 8}})
        q = self.ask_and_pose()
        self.assertIn("Lev's tower", q["note"])
        self.assertEqual(self.placed(), {})

    def test_no_pads_on_somebodys_floor(self):
        # Planks under every candidate spot: a floor somebody laid, not terrain.
        for x in range(-6, 7):
            for z in range(-6, 7):
                self.world.blocks[("minecraft:overworld", x, GROUND_Y, z)] = "minecraft:oak_planks"
        q = self.ask_and_pose()
        self.assertEqual(q["status"], "queued")
        self.assertEqual(self.placed(), {k: v for k, v in self.world.blocks.items()
                                         if v == "minecraft:oak_planks"})

    def test_a_cell_that_is_not_air_moves_the_pads_elsewhere(self):
        self.world.blocks[("minecraft:overworld", 2, 64, 2)] = "minecraft:torch"
        q = self.ask_and_pose()
        self.assertEqual(q["status"], "open")
        self.assertEqual(self.world.blocks[("minecraft:overworld", 2, 64, 2)], "minecraft:torch")

    def test_a_question_by_person_and_by_dotted_name(self):
        self.join(KAZ)
        by_person = self.engine.ask("kaz", "Castle?")
        by_name = self.engine.ask("Kaz8044", "Farm?")
        self.assertEqual(by_person["player"], KAZ)
        self.assertEqual(by_name["person"], "Kaz")
        with self.assertRaises(vesper.VesperError):
            self.engine.ask("Kaz", "x", [{"label": "a", "picture": "tnt"}, {"label": "b"}])
        with self.assertRaises(vesper.VesperError):
            self.engine.ask("Kaz", "x", ["only one"])


# ---------------------------------------------------------------------------
# Undo, and the hands
# ---------------------------------------------------------------------------
class TestUndo(EngineBase):
    def test_undo_puts_back_the_pads_and_cancels_the_question(self):
        self.join(KAZ)
        self.beat(vesper.GREETING_LIFETIME + 1)
        q = self.engine.ask("Kaz", "Castle?")
        self.beat()
        aid = self.engine.questions.get(q["id"])["action"]
        self.assertEqual(len(self.placed()), 12)
        result = self.engine.undo(aid)
        self.assertEqual((result["restored"], result["changed"]), (12, 0))
        self.assertEqual(self.placed(), {})
        self.assertEqual(self.world.entities, [])
        self.assertEqual(self.engine.questions.get(q["id"])["status"], "cancelled")
        self.assertEqual(self.engine.actions.get(aid)["status"], "undone")
        again = self.engine.undo(aid)
        self.assertEqual(again["restored"], 0)

    def test_undo_leaves_a_block_a_child_changed_since(self):
        self.join(KAZ)
        self.beat(vesper.GREETING_LIFETIME + 1)
        q = self.engine.ask("Kaz", "Castle?")
        self.beat()
        act = self.engine.actions.get(self.engine.questions.get(q["id"])["action"])
        c = act["cells"][0]
        self.world.blocks[("minecraft:overworld", c["x"], c["y"], c["z"])] = "minecraft:diamond_block"
        result = self.engine.undo(act["id"])
        self.assertEqual((result["restored"], result["changed"]), (11, 1))
        self.assertEqual(self.placed(), {("minecraft:overworld", c["x"], c["y"], c["z"]):
                                         "minecraft:diamond_block"})

    def test_undo_of_a_greeting_removes_vesper(self):
        self.join(KAZ)
        aid = self.engine.actions.list(1)[0]["id"]
        self.engine.undo(aid)
        self.assertEqual(self.world.entities, [])
        self.assertEqual(self.engine.live, {})

    def test_undo_while_nobody_is_on_loads_the_chunk_for_it(self):
        self.join(KAZ)
        act = self.engine.actions.start("gift", {"player": KAZ, "person": "Kaz"}, "A flower")
        why = self.engine.place_blocks(act, [{"x": 40, "y": 64, "z": 40,
                                              "block": "minecraft:poppy", "ground": True}],
                                       "minecraft:overworld")
        self.assertEqual(why, "")
        self.world.players.clear()
        self.col.sessions.clear()
        self.engine.undo(act["id"])
        self.assertTrue(any("forceload add 40 40" in c for c in self.world.commands))
        self.assertTrue(any("forceload remove" in c for c in self.world.commands))
        self.assertEqual(self.placed(), {})

    def test_a_large_change_is_snapshotted_first_and_refused_if_that_fails(self):
        self.join(KAZ)
        cells = [{"x": 100 + i, "y": 64, "z": 100, "block": "minecraft:oak_planks"}
                 for i in range(vesper.LARGE_CHANGE)]
        act = self.engine.actions.start("build", {"player": KAZ, "person": "Kaz"}, "A path")
        self.snapshot_answer = "disk full"
        why = self.engine.place_blocks(act, cells, "minecraft:overworld")
        self.assertIn("snapshot", why)
        self.assertEqual(self.placed(), {})
        self.snapshot_answer = None
        self.assertEqual(self.engine.place_blocks(act, cells, "minecraft:overworld"), "")
        self.assertEqual(self.snapshots, ["snap", "snap"])
        self.assertEqual(len(self.placed()), vesper.LARGE_CHANGE)

    def test_bad_ids(self):
        with self.assertRaises(vesper.VesperError):
            self.engine.undo("../../etc")
        with self.assertRaises(KeyError):
            self.engine.undo("20261031-abcdef")


# ---------------------------------------------------------------------------
# Senses, attention and memory
# ---------------------------------------------------------------------------
class TestAttentionAndMemory(EngineBase):
    def test_dotted_and_plain_names_are_the_same_person(self):
        who = self.engine.roster.who("kaz8044")
        self.assertEqual((who["person"], who["role"]), ("Kaz", "child"))
        self.assertEqual(self.engine.roster.who("Stranger")["role"], "guest")
        self.assertEqual(vesper.quote_name(KAZ), KAZ)

    def test_memory_follows_a_person_across_sessions(self):
        self.join(KAZ)
        self.beat(60)
        self.leave(KAZ)
        self.clock.t += vesper.GREET_COOLDOWN + 1
        self.join(KAZ)
        mem = self.engine.memory.get("Kaz")
        self.assertEqual(mem["sessions"], 2)
        self.assertGreaterEqual(mem["seconds"], 60)
        self.assertEqual(mem["players"], [KAZ])
        self.assertEqual(mem["moments"]["join"], 2)

    def test_idle_for_a_minute_is_a_moment(self):
        self.join(KAZ)
        for _ in range(35):
            self.beat(2)
        kinds = [d["kind"] for k, d in self.emitted]
        self.assertIn("idle", kinds)
        self.assertEqual(kinds.count("idle"), 1)

    def test_a_parent_saying_vesper_in_chat_is_heard(self):
        self.join(DAD)
        self.log_line(f"<{DAD}> Vesper, can you build Kaz a bridge?")
        self.beat()
        asked = [d for k, d in self.emitted if d["kind"] == "asked"]
        self.assertEqual(len(asked), 1)
        self.assertIn("bridge", asked[0]["said"])
        self.assertTrue(any(c.startswith(f"minecraft:tellraw {DAD}") for c in self.world.commands))

    def test_a_favourite_place_is_noticed(self):
        (self.server_dir / ".bruh-world").mkdir(exist_ok=True)
        self.engine.zones.save({"name": "the pond", "x": 200, "z": 200, "radius": 20,
                                "kind": "vesper"})
        self.join(KAZ)
        for _ in range(4):
            self.world.players[KAZ] = [200.5, 64.0, 200.5]
            self.beat(6)
            self.world.players[KAZ] = [0.5, 64.0, 0.5]
            self.beat(6)
            self.engine.cooldowns.clear()
        self.assertGreaterEqual(self.engine.memory.get("Kaz")["places"]["the pond"], 4)
        self.assertIn("favourite_place", [d["kind"] for k, d in self.emitted])

    def test_the_days_journal_sums_each_person(self):
        self.join(KAZ)
        self.log_line(f"{KAZ} fell from a high place")
        self.beat()
        day = self.col.journal.day_of(self.clock())
        summary = self.col.journal.summary(day, dict(self.col.sessions),
                                           lambda n: self.engine.roster.who(n)["person"])
        self.assertEqual(summary["people"]["Kaz"]["deaths"], 1)
        self.assertEqual(summary["people"]["Kaz"]["players"], [KAZ])
        self.assertGreaterEqual(summary["people"]["Kaz"]["vesper"], 1)

    def test_the_world_snapshot_carries_vesper(self):
        self.col.extra = lambda: {"vesper": self.engine.brief()}
        self.join(KAZ)
        snap = self.col.snapshot()
        self.assertEqual(snap["vesper"]["state"], "acting")
        self.assertEqual(snap["vesper"]["last_action"]["kind"], "greet")

    def test_the_roster_is_checked(self):
        for bad in ([{"person": "", "players": ["x"]}], [{"person": "A", "players": []}],
                    [{"person": "A", "role": "boss", "players": ["a"]}],
                    [{"person": "A", "players": ["a b"]}],
                    [{"person": "A", "players": [".Kaz"]}, {"person": "B", "players": ["kaz"]}]):
            with self.subTest(bad=bad), self.assertRaises(vesper.VesperError):
                self.engine.roster.save(bad)


# ---------------------------------------------------------------------------
# The card's status line: what Vesper is doing, or why it is not
# ---------------------------------------------------------------------------
class TestTheHeadline(EngineBase):
    def head(self):
        return self.engine.status()["headline"]

    def test_an_empty_family_is_said_before_anything_else(self):
        self.engine.roster.save([])
        h = self.head()
        self.assertEqual(h["code"], "no_family")
        self.assertIn("nobody is on the family list", h["text"])
        self.assertIn("add your family below", h["text"])

    def test_off_says_off_and_what_to_do(self):
        self.engine.configure(on=False)
        self.assertEqual(self.head()["code"], "off")
        self.assertTrue(self.head()["text"].startswith("Off."))
        self.engine.roster.save([])
        self.assertIn("Add your family", self.head()["text"])

    def test_waiting_for_someone_and_a_stranger_is_named(self):
        self.assertEqual(self.head()["code"], "waiting_join")
        self.world.players["Stranger1"] = [0.5, 64.0, 0.5]
        self.beat(0)
        h = self.head()
        self.assertEqual(h["code"], "waiting_join")
        self.assertIn("Stranger1", h["text"])
        self.assertIn("not on the family list", h["text"])

    def test_someone_in_the_game_and_the_online_list(self):
        self.join(KAZ)
        status = self.engine.status()
        self.assertIn(status["headline"]["code"], ("ready", "acting"))
        self.assertIn("Kaz", status["headline"]["text"])
        self.assertEqual(status["online"], [{"person": "Kaz", "role": "child", "player": KAZ}])

    def test_bedtime_and_an_unreadable_switch(self):
        self.bed = True
        self.join(KAZ)
        self.assertEqual(self.head()["code"], "bedtime")
        self.bed = None
        self.beat()
        h = self.head()
        self.assertEqual(h["code"], "waiting")
        self.assertIn("input_boolean.kids_bedtime", h["text"])

    def test_todays_limit(self):
        self.limits = {"actions": 0, "events": 40}
        self.assertEqual(self.head()["code"], "limit")
        self.assertIn("Today's limit reached", self.head()["text"])


# ---------------------------------------------------------------------------
# The panel's routes
# ---------------------------------------------------------------------------
def _load_panel(root: Path):
    rcon_mod = type(sys)("rcon_client")

    class _FakeRcon:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def connect(self): pass
        def close(self): pass
        def command(self, *a, **kw): return "ok"

    rcon_mod.Rcon = _FakeRcon
    sys.modules["rcon_client"] = rcon_mod
    os.environ["BRUH_MC_SCRIPTS_DIR"] = "/nonexistent/for-tests"
    os.environ["MC_SERVER_DIR"] = str(root / "server")
    os.environ["MC_BACKUP_DIR"] = str(root / "backups")
    os.environ["MC_PANEL_STATE"] = str(root / "state")
    os.environ["MC_CONSOLE_LOG"] = str(root / "state" / "console.log")
    os.environ["MC_WWW_DIR"] = str(root / "www")
    os.environ["MC_WORLDS_DIR"] = str(root / "worlds")
    spec = importlib.util.spec_from_file_location("panel_server_vesper", PANEL / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestThePanelRoutes(AioHTTPTestCase):
    async def get_application(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for d in ("server", "backups", "state", "worlds/TEST2"):
            (self.root / d).mkdir(parents=True)
        (self.root / "server" / "server.properties").write_text("level-name=world\n")
        (self.root / "worlds" / "TEST2" / "server.properties").write_text(
            "motd=A BRUH Minecraft\nlevel-name=TEST2\n")
        self.panel = _load_panel(self.root)
        for key in ("MC_WWW_DIR", "MC_WORLDS_DIR"):
            self.addCleanup(os.environ.pop, key, None)
        return self.panel.build_app()

    async def test_engine_state_family_ask_and_undo(self):
        r = await self.client.post("/api/vesper/ask", json={"player": "x", "text": "?"})
        self.assertEqual(r.status, 400)
        self.assertIn("switched off", (await r.json())["error"])
        r = await self.client.post("/api/vesper/engine", json={
            "on": True, "bedtime_entity": "input_boolean.kids_bedtime"})
        self.assertEqual(r.status, 200, await r.text())
        r = await self.client.put("/api/vesper/family", json={"people": [
            {"person": "Kaz", "role": "child", "players": [KAZ]}]})
        self.assertEqual(r.status, 200, await r.text())
        r = await self.client.put("/api/vesper/family", json={"people": [{"person": "X"}]})
        self.assertEqual(r.status, 400)
        r = await self.client.post("/api/vesper/ask", json={
            "player": "Kaz", "text": "Castle or farm?", "options": ["castle", "farm"]})
        self.assertEqual(r.status, 201, await r.text())
        body = await r.json()
        self.assertIn("next time", body["note"])
        r = await self.client.get("/api/vesper")
        state = await r.json()
        self.assertTrue(state["enabled"])
        self.assertEqual(state["questions"][0]["options"][1]["label"], "farm")
        self.assertEqual(state["family"][0]["players"], [KAZ])
        r = await self.client.post("/api/vesper/actions/20261031-abcdef/undo")
        self.assertEqual(r.status, 404)
        r = await self.client.post("/api/vesper/actions/nonsense/undo")
        self.assertEqual(r.status, 404)
        r = await self.client.post("/api/vesper/engine", json={"on": False})
        self.assertFalse((await r.json())["enabled"])
        r = await self.client.post("/api/vesper/engine", json={"on": "yes"})
        self.assertEqual(r.status, 400)
        r = await self.client.post("/api/vesper/engine", json={"bedtime_entity": "door"})
        self.assertEqual(r.status, 400)
        r = await self.client.post("/api/vesper/zones", json={"name": "Spawn town", "x": 0,
                                                                "z": 0, "radius": 40})
        self.assertTrue((await r.json())["zone"]["protect"])
        r = await self.client.delete("/api/vesper/zones/Spawn%20town")
        self.assertEqual((await r.json())["zones"], [])
        r = await self.client.get("/api/world")
        self.assertIn("vesper", await r.json())
        self.assertEqual(state["headline"]["code"], "waiting_join")
        self.assertEqual(state["online"], [])

    async def test_the_bedtime_list_is_home_assistants_on_off_entities(self):
        def core(method, path, body=None, timeout=3):
            self.assertEqual((method, path), ("GET", "/states"))
            return {"result": [
                {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
                {"entity_id": "binary_sensor.boys_door", "state": "off",
                 "attributes": {"friendly_name": "Boys' door"}},
                {"entity_id": "input_boolean.kids_bedtime", "state": "off",
                 "attributes": {"friendly_name": "Kids bedtime"}},
                {"entity_id": "switch.fan", "state": "on", "attributes": {}},
                "junk"]}
        self.panel._core_api = core
        r = await self.client.get("/api/vesper/entities")
        body = await r.json()
        self.assertTrue(body["reachable"])
        self.assertEqual([e["entity_id"] for e in body["entities"]],
                         ["input_boolean.kids_bedtime", "binary_sensor.boys_door", "switch.fan"])
        self.assertEqual(body["entities"][1]["name"], "Boys' door")

        def down(*a, **k):
            raise OSError("Home Assistant is restarting")
        self.panel._core_api = down
        body = await (await self.client.get("/api/vesper/entities")).json()
        self.assertEqual(body, {"entities": [], "reachable": False})
        self.panel._core_api = lambda *a, **k: None    # no Supervisor token
        body = await (await self.client.get("/api/vesper/entities")).json()
        self.assertFalse(body["reachable"])

    async def test_renaming_to_vesper_world_keeps_a_safe_folder_and_shows_the_name(self):
        calls = []

        async def manager(*args):
            calls.append(args)
            if args[0] == "active":
                return 0, "TEST2\n"
            if args[0] == "rename":
                (self.root / "worlds" / args[1]).rename(self.root / "worlds" / args[2])
            return 0, ""

        async def nothing(*a, **k):
            return None

        async def gone(timeout=90.0):
            return True

        async def rcon(cmd):
            return "ok"

        self.panel._run_world_manager = manager
        self.panel._persist_option = nothing
        self.panel._supervisor_restart_self = nothing
        self.panel._wait_for_jvm_exit = gone
        self.panel._rcon_command = rcon
        self.panel.MC_WORLDS_DIR = self.root / "worlds"
        self.panel.MC_PANEL_STATE = self.root / "state"
        r = await self.client.post("/api/world/rename", json={"name": "Vesper World"})
        self.assertEqual(r.status, 200, await r.text())
        body = await r.json()
        self.assertEqual((body["folder"], body["display_name"]), ("Vesper_World", "Vesper World"))
        self.assertIn(("rename", "TEST2", "Vesper_World"), calls)
        props = (self.root / "worlds" / "Vesper_World" / "server.properties").read_text()
        self.assertIn("motd=Vesper World", props)
        self.assertIn("level-name=TEST2", props)
        self.assertNotIn("A BRUH Minecraft", props)
        r = await self.client.post("/api/world/rename", json={"name": "!!!"})
        self.assertEqual(r.status, 400)

    def test_folder_names_and_bedtime_rules(self):
        f = self.panel.world_folder_name
        self.assertEqual(f("Vesper World"), "Vesper_World")
        self.assertEqual(f("  Kaz & Lev's World!! "), "Kaz_Lev_s_World")
        self.assertEqual(f("../etc"), "etc")
        self.assertEqual(len(f("x" * 80)), 32)
        rule = self.panel.bedtime_rule
        self.assertEqual(rule("input_boolean.bedtime"), ("input_boolean.bedtime", "on"))
        self.assertEqual(rule("binary_sensor.boys_door=off"), ("binary_sensor.boys_door", "off"))
        self.assertIsNone(rule(""))
        self.assertIsNone(rule("not an entity"))


if __name__ == "__main__":
    unittest.main()
