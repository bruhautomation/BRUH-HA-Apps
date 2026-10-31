"""BRUH Minecraft's companion hands (panel/companion.py), and the lane to them.

The add-on decides nothing about a companion any more (#592/#593): it says
what it is told under the name it is given, brings a body for a moment,
puts out choice pads and builds small things — each held next to the world
by `check_command`, the guarded placement and Undo — and it tells Home
Assistant what happens in the game as plain events. These tests drive the
real module against a fake Paper server (block map, entities, RCON replies)
and the real panel routes, and hold the two rules that make it neutral:
without brAIn there is no companion and nothing about one in the log, and
the add-on ships no persona name.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import AioHTTPTestCase

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "bruh-minecraft-server"
PANEL = ADDON / "panel"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PANEL / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mcworld = _load("test_companion_mc_world", "mcworld.py")
companion = _load("test_companion_hands", "companion.py")
legacy = companion.legacy

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


class HandsBase(unittest.TestCase):
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
        self.emitted: list[tuple[str, dict]] = []
        self.snapshots: list[str] = []
        self.snapshot_answer = None
        self.hands = companion.Companion(
            self.col, emit=lambda kind, data: self.emitted.append((kind, data)),
            snapshot=self._snapshot, clock=self.clock)
        self.hands.set_identity(name="Juniper", colour_="aqua", active=True, by="brAIn")

    def _snapshot(self):
        self.snapshots.append("snap")
        return self.snapshot_answer

    def log_line(self, text: str, thread: str = "Server thread") -> None:
        with open(self.log, "a") as f:
            f.write(f"[09:00:01] [{thread}/INFO]: {text}\n")

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
        self.hands.step()

    def placed(self) -> dict:
        return {k: v for k, v in self.world.blocks.items() if v != "minecraft:air"}

    def tellraws(self) -> list[str]:
        return [c for c in self.world.commands if "tellraw" in c]


class TestQuietWithNobodyOn(HandsBase):
    def test_nothing_is_sent_while_nobody_is_on(self):
        for _ in range(20):
            self.beat(30)
        self.assertEqual(self.world.engine_commands(), [])
        with self.assertRaises(companion.CompanionError):
            self.hands.say("everyone", "hello")

    def test_strays_from_an_earlier_run_and_the_old_engine_are_swept(self):
        self.join(KAZ)
        kills = [c for c in self.world.commands if c.startswith("minecraft:kill")]
        self.assertIn(f"minecraft:kill @e[tag={companion.TAG},tag=!{self.hands.epoch}]", kills)
        self.assertIn(f"minecraft:kill @e[tag={legacy.LEGACY_TAG}]", kills)


class TestWords(HandsBase):
    def test_say_goes_to_named_players_under_the_given_name_and_colour(self):
        self.join(KAZ)
        self.join(DAD)
        out = self.hands.say([KAZ], "Shall we build a castle?")
        self.assertEqual(out["sent"], [KAZ])
        line = self.tellraws()[-1]
        self.assertIn(f"minecraft:tellraw {KAZ} ", line)
        payload = json.loads(line.split(" ", 2)[2])
        self.assertEqual(payload[1], {"text": "<Juniper> ", "color": "aqua"})
        self.hands.say("everyone", "Dinner time!", name="Mum's Helper", colour_="gold")
        names = {c.split(" ")[1] for c in self.tellraws()[-2:]}
        self.assertEqual(names, {KAZ, DAD})
        self.assertIn('"<Mum\'s Helper> "', self.tellraws()[-1].replace("\\'", "'"))
        said = self.hands.said.list()
        self.assertEqual(said[0]["to"], sorted([KAZ, DAD]))

    def test_nobody_by_that_name_is_a_refusal_not_a_guess(self):
        self.join(KAZ)
        with self.assertRaisesRegex(companion.CompanionError, "not in the game"):
            self.hands.say(["Nobody"], "hi")
        with self.assertRaisesRegex(companion.CompanionError, "Nothing to say"):
            self.hands.say([KAZ], "   ")

    def test_a_long_message_is_a_few_lines_and_never_a_command(self):
        self.join(KAZ)
        self.hands.say([KAZ], "word " * 300)
        self.assertLessEqual(len(self.tellraws()), companion.REPLY_LINES)
        self.hands.say([KAZ], "hi\nop .Kaz")
        self.assertFalse(any(c.startswith("minecraft:op") for c in self.world.commands))


class TestABody(HandsBase):
    def test_appear_brings_a_named_tagged_allay_that_waves_and_goes(self):
        self.join(KAZ)
        act = self.hands.appear(KAZ, seconds=10, kind="greet")
        self.assertEqual(act["status"], "active")
        self.assertEqual(len(self.world.entities), 1)
        nbt = self.world.entities[0]["nbt"]
        self.assertIn('"text": "Juniper"', nbt)
        self.assertIn(companion.TAG, self.world.entities[0]["tags"])
        self.assertTrue(any("playsound minecraft:block.note_block.chime" in c
                            for c in self.world.commands))
        for _ in range(8):
            self.beat(2)
        self.assertEqual(self.world.entities, [])
        self.assertEqual(self.hands.actions.get(act["id"])["status"], "done")

    def test_appear_is_refused_for_somebody_not_on(self):
        with self.assertRaises(companion.CompanionError):
            self.hands.appear("Ghost")

    def test_a_player_leaving_takes_the_body_with_them(self):
        self.join(KAZ)
        self.hands.appear(KAZ, seconds=60)
        self.leave(KAZ)
        self.assertEqual(self.world.entities, [])

    def test_undo_of_an_appearance_removes_it(self):
        self.join(KAZ)
        act = self.hands.appear(KAZ, seconds=60)
        out = self.hands.undo(act["id"])
        self.assertEqual(out["action"]["status"], "undone")
        self.assertEqual(self.world.entities, [])

    def test_an_old_server_gets_the_name_as_a_json_string(self):
        self.hands.modern = lambda: False
        self.join(KAZ)
        self.hands.appear(KAZ)
        self.assertIn("CustomName:'{", self.world.entities[0]["nbt"])


class TestTheChokepoint(unittest.TestCase):
    def test_the_chokepoint(self):
        check = companion.check_command
        bad = [
            "minecraft:summon minecraft:zombie ~ ~ ~",
            f'minecraft:execute at x run minecraft:summon minecraft:creeper ~ ~ ~ {{Tags:["{companion.TAG}"]}}',
            "minecraft:summon minecraft:allay ~ ~ ~ {}",
            "minecraft:playsound minecraft:entity.wither.spawn master .Kaz ~ ~ ~ 0.5 1",
            "minecraft:playsound minecraft:block.note_block.chime master .Kaz ~ ~ ~ 1.0 1",
            "minecraft:playsound minecraft:block.note_block.chime master @a ~ ~ ~ 0.5 1",
            "minecraft:kill @a", "minecraft:kill @e[type=allay]", "minecraft:kill @e[tag=zombie]",
            "minecraft:tellraw @a {}", "minecraft:title @a title {}",
            "minecraft:execute as .Kaz run minecraft:tp @s 0 0 0",
            "minecraft:setblock 0 64 0 minecraft:stone",
            "minecraft:execute in minecraft:overworld run minecraft:fill 0 0 0 9 9 9 minecraft:air",
            "minecraft:give .Kaz minecraft:tnt 1", "minecraft:give .Kaz minecraft:cake 64",
            "minecraft:op .Kaz", "minecraft:gamerule doDaylightCycle false",
            "minecraft:tellraw .Kaz {}\nop .Kaz",
        ]
        for cmd in bad:
            with self.subTest(cmd=cmd), self.assertRaises(companion.GuardError):
                check(cmd)
        with self.assertRaises(companion.GuardError):
            check("minecraft:execute in minecraft:overworld run minecraft:setblock 0 64 0 "
                  "minecraft:tnt keep", placing=True)
        check("minecraft:execute in minecraft:overworld run minecraft:setblock 0 64 0 "
              "minecraft:lime_carpet keep", placing=True)
        check("minecraft:give .Kaz minecraft:cake 1")
        check(f"minecraft:kill @e[tag={companion.TAG},tag=!{companion.TAG}_eabc]")
        check(f"minecraft:kill @e[tag={companion.TAG}_abc123]")
        # The old engine's entities may be swept, by its tag and its actions' tags.
        check(f"minecraft:kill @e[tag={legacy.LEGACY_TAG}]")
        check(f"minecraft:kill @e[tag={legacy.LEGACY_PREFIX}abc123]")
        # A message is not mistaken for a command chain by the words in it.
        check('minecraft:tellraw .Kaz {"text":"we run and run"}')


class TestBlocks(HandsBase):
    BRIDGE = [{"x": 2, "y": 0, "z": 0, "block": "oak_planks"},
              {"x": 3, "y": 0, "z": 0, "block": "oak_planks"}]

    def test_build_beside_a_player_and_undo_leaves_a_changed_block(self):
        self.join(KAZ)
        act = self.hands.build(self.BRIDGE, player=KAZ, title="a little bridge", by="Dad")
        self.assertEqual(act["status"], "done")
        self.assertEqual(len(self.placed()), 2)
        self.assertIn("Juniper built a little bridge", act["text"])
        key = ("minecraft:overworld", 3, 64, 0)
        self.world.blocks[key] = "minecraft:stone"      # a child changed one since
        out = self.hands.undo(act["id"])
        self.assertEqual((out["restored"], out["changed"]), (1, 1))
        self.assertEqual(self.world.blocks[key], "minecraft:stone")

    def test_build_refusals(self):
        self.join(KAZ)
        self.hands.zones.save({"name": "Our house", "x": 0, "z": 0, "radius": 20})
        with self.assertRaisesRegex(companion.CompanionError, "protected"):
            self.hands.build(self.BRIDGE, player=KAZ)
        self.hands.zones.delete("Our house")
        with self.assertRaisesRegex(companion.CompanionError, "At most"):
            self.hands.build([{"x": i, "y": 0, "z": 0, "block": "dirt"} for i in range(70)],
                             player=KAZ)
        with self.assertRaisesRegex(companion.CompanionError, "does not use"):
            self.hands.build([{"x": 2, "y": 0, "z": 0, "block": "tnt"}], player=KAZ)
        with self.assertRaisesRegex(companion.CompanionError, "standing"):
            self.hands.build([{"x": 0, "y": 0, "z": 0, "block": "dirt"}], player=KAZ)
        with self.assertRaisesRegex(companion.CompanionError, "near somebody"):
            self.hands.build([{"x": 900, "y": 64, "z": 900, "block": "dirt"}])

    def test_a_large_change_is_snapshotted_first_and_refused_if_that_fails(self):
        self.join(KAZ)
        cells = [{"x": 2 + i % 8, "y": i // 64, "z": 2 + (i // 8) % 8, "block": "dirt"}
                 for i in range(64)]
        self.snapshot_answer = "the disk is full"
        with self.assertRaisesRegex(companion.CompanionError, "snapshot"):
            self.hands.build(cells, player=KAZ)
        self.assertEqual(self.snapshots, ["snap"])
        self.assertEqual(self.placed(), {})

    def test_undo_last_and_bad_ids(self):
        self.join(KAZ)
        self.hands.build(self.BRIDGE, player=KAZ)
        self.assertEqual(self.hands.undo_last()["action"]["status"], "undone")
        self.assertIsNone(self.hands.undo_last())
        with self.assertRaises(companion.CompanionError):
            self.hands.undo("nonsense")
        with self.assertRaises(KeyError):
            self.hands.undo("20261031-abcdef")


class TestChoicePads(HandsBase):
    def test_standing_on_a_pad_answers_and_tells_home_assistant(self):
        self.join(KAZ)
        q = self.hands.ask(KAZ, "Castle or farm?", ["castle", "farm"], by="brAIn", person="Kaz")
        self.beat(1)
        self.assertEqual(self.hands.questions.get(q["id"])["status"], "open")
        self.assertEqual(sum(1 for v in self.placed().values() if v.endswith("_carpet")), 8)
        pad = self.hands.asking["layout"]["pads"][0]
        self.world.players[KAZ] = [pad["min_x"] + 0.5, 64.0, pad["min_z"] + 0.5]
        for _ in range(6):
            self.beat(1)
        answered = self.hands.questions.get(q["id"])
        self.assertEqual(answered["answer"], "castle")
        kind, data = self.emitted[-1]
        self.assertEqual(kind, "bruh_minecraft_answer")
        self.assertEqual((data["player"], data["answer"], data["other"]), (KAZ, "castle", "farm"))
        for _ in range(10):
            self.beat(1)
        self.assertEqual(self.placed(), {})

    def test_a_question_waits_for_its_player(self):
        q = self.hands.ask(LEV, "Snow or sea?")
        self.assertEqual(q["status"], "queued")
        self.beat(5)
        self.assertEqual(self.placed(), {})
        with self.assertRaises(companion.CompanionError):
            self.hands.ask("not a name!", "?")


def _load_panel(root: Path):
    rcon_mod = type(sys)("rcon_client")

    class _FakeRcon:
        def __init__(self, *a, **kw): pass
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
    os.environ["MC_CHANGELOG"] = str(ADDON / "CHANGELOG.md")
    spec = importlib.util.spec_from_file_location("panel_server_companion", PANEL / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PanelCase(AioHTTPTestCase):
    async def get_application(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for d in ("server", "backups", "state", "worlds/TEST2"):
            (self.root / d).mkdir(parents=True)
        (self.root / "server" / "server.properties").write_text("level-name=world\n")
        self.panel = _load_panel(self.root)
        for key in ("MC_WWW_DIR", "MC_WORLDS_DIR", "MC_CHANGELOG"):
            self.addCleanup(os.environ.pop, key, None)
        self.panel._BRAIN.update(at=-1e12, present=None)
        return self.panel.build_app()


class TestThePanelWithoutBrain(PanelCase):
    async def test_no_brain_no_companion_and_one_line_why(self):
        with mock.patch.object(self.panel, "_core_api", return_value={"result": [
                {"domain": "light"}, {"domain": "bruh_minecraft"}]}):
            r = await self.client.get("/api/companion")
        body = await r.json()
        self.assertIs(body["brain"], False)
        self.assertFalse(body["headline"]["show"])
        self.assertEqual(body["headline"]["text"],
                         "Install brAIn to have a companion play in the world.")

    async def test_events_without_home_assistant_say_nothing(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": ""}), \
                self.assertNoLogs(level=logging.DEBUG):
            sender = self.panel._EventSender()
            sender.fire("bruh_minecraft_chat", {"player": "x"})
            name, data = sender.queue.get_nowait()
            self.assertIsNone(self.panel._core_api("POST", f"/events/{name}", data))

    async def test_an_unreachable_home_assistant_drops_the_event_quietly(self):
        def boom(name, data):
            raise OSError("no route")
        sender = self.panel._EventSender(post=boom)
        with self.assertNoLogs(level=logging.DEBUG):
            sender.fire("bruh_minecraft_join", {"player": "x"})
            name, data = sender.queue.get_nowait()
            try:
                sender.post(name, data)
            except OSError:
                sender.dropped += 1
        self.assertEqual(sender.dropped, 1)


class TestThePanelWithBrain(PanelCase):
    async def test_the_card_carries_who_brain_says_it_is(self):
        with mock.patch.object(self.panel, "_core_api", return_value={"result": [
                {"domain": "brain"}]}):
            r = await self.client.post("/api/companion/identity", json={
                "name": "Juniper", "colour": "aqua", "active": True, "by": "brAIn",
                "model": "haiku"})
            self.assertEqual(r.status, 200, await r.text())
            r = await self.client.get("/api/companion")
        body = await r.json()
        self.assertTrue(body["brain"])
        self.assertTrue(body["headline"]["show"])
        self.assertIn("Juniper", body["headline"]["text"])
        self.assertEqual(body["identity"]["model"], "haiku")
        r = await self.client.post("/api/companion/identity", json={"active": "yes"})
        self.assertEqual(r.status, 400)

    async def test_the_routes_answer_with_the_reason(self):
        r = await self.client.post("/api/companion/say", json={"to": "x", "message": "hi"})
        self.assertEqual(r.status, 400)
        self.assertIn("Nobody is in the game", (await r.json())["error"])
        r = await self.client.post("/api/companion/build", json={"blocks": []})
        self.assertEqual(r.status, 400)
        r = await self.client.post("/api/companion/ask", json={
            "player": KAZ, "question": "Castle or farm?", "options": ["castle", "farm"],
            "person": "Kaz"})
        self.assertEqual(r.status, 201, await r.text())
        self.assertIn("next time", (await r.json())["note"])
        r = await self.client.post("/api/companion/actions/last/undo")
        self.assertEqual(r.status, 404)
        r = await self.client.post("/api/companion/actions/nonsense/undo")
        self.assertEqual(r.status, 404)
        r = await self.client.post("/api/companion/zones", json={"name": "Spawn town", "x": 0,
                                                                   "z": 0, "radius": 40})
        self.assertTrue((await r.json())["zone"]["protect"])
        r = await self.client.delete("/api/companion/zones/Spawn%20town")
        self.assertEqual((await r.json())["zones"], [])
        r = await self.client.get("/api/companion/legacy")
        self.assertIsNone((await r.json())["legacy"])
        r = await self.client.get("/api/world")
        self.assertIn("companion", await r.json())


class TestTheChangelogRoute(PanelCase):
    """#594: the header's link opens CHANGELOG.md in the panel, newest first."""

    async def test_newest_first_from_the_file_in_the_image(self):
        r = await self.client.get("/api/changelog")
        self.assertEqual(r.status, 200, await r.text())
        body = await r.json()
        versions = [x["version"] for x in body["releases"]]
        self.assertEqual(versions[0], "1.17.8")
        as_tuples = [tuple(int(n) for n in v.split(".")) for v in versions]
        self.assertEqual(as_tuples, sorted(as_tuples, reverse=True))
        self.assertIn("### Added", body["releases"][0]["body"])

    async def test_the_order_is_the_versions_not_the_files(self):
        text = "# Changelog\n\n## 1.2.0\n- b\n\n## 1.10.0\n- c\n\n## 1.9.1\n- a\n"
        self.assertEqual([r["version"] for r in self.panel.changelog_releases(text)],
                         ["1.10.0", "1.9.1", "1.2.0"])

    async def test_a_missing_file_is_said(self):
        self.panel.CHANGELOG_PATH = self.root / "missing.md"
        r = await self.client.get("/api/changelog")
        self.assertEqual(r.status, 404)
        self.assertIn("not in this image", (await r.json())["error"])


class TestTheGameEvents(unittest.TestCase):
    """The lane out: each collector event as a neutral Home Assistant event."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls._tmp = tmp
        root = Path(tmp.name)
        for d in ("server", "backups", "state", "worlds"):
            (root / d).mkdir(parents=True)
        cls.panel = _load_panel(root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()
        for key in ("MC_WWW_DIR", "MC_WORLDS_DIR", "MC_CHANGELOG"):
            os.environ.pop(key, None)

    def test_every_game_happening_is_an_event_with_no_persona(self):
        ev = self.panel.game_event
        verified = lambda p: (p == DAD, "" if p == DAD else "online-mode is off")  # noqa: E731
        name, data = ev({"t": 100, "kind": "chat", "player": DAD, "shown": "Dad",
                         "said": "juniper, are you here?", "text": "Dad: juniper, are you here?"},
                        verified, "world")
        self.assertEqual(name, "bruh_minecraft_chat")
        self.assertEqual((data["player"], data["name"], data["text"]),
                         (DAD, "Dad", "juniper, are you here?"))
        self.assertIs(data["verified"], True)
        self.assertEqual(data["time"], "1970-01-01T00:01:40+00:00")
        name, data = ev({"t": 1, "kind": "join", "player": KAZ}, verified, "world")
        self.assertEqual((name, data["verified"], data["why_unverified"]),
                         ("bruh_minecraft_join", False, "online-mode is off"))
        self.assertEqual(ev({"kind": "leave", "player": KAZ, "seconds": 60})[1]["seconds"], 60)
        self.assertEqual(ev({"kind": "death", "player": KAZ, "text": "fell"})[0],
                         "bruh_minecraft_death")
        self.assertEqual(ev({"kind": "advancement", "player": KAZ, "what": "Stone Age"})[1]["what"],
                         "Stone Age")
        self.assertEqual(ev({"kind": "place", "player": KAZ, "place": "Village"})[1]["place"],
                         "Village")
        for kind in ("save", "server", "build", "companion"):
            self.assertIsNone(ev({"kind": kind}), kind)

    def test_every_chat_line_becomes_one_event_with_no_cap(self):
        fired = []
        sender = self.panel._EventSender(post=lambda n, d: fired.append((n, d)))
        for i in range(200):
            out = self.panel.game_event({"kind": "chat", "player": DAD, "said": f"line {i}"})
            sender.fire(*out)
        while not sender.queue.empty():
            sender.post(*sender.queue.get_nowait())
        self.assertEqual(len(fired), 200)
        self.assertEqual(fired[-1][1]["text"], "line 199")


if __name__ == "__main__":
    unittest.main()
