"""The atlas: what is where in the whole world, from its region files.

The owner: *"It needs to be omniscient in the server, understanding the
entire build, what stuff is where, and if I say build a couch in this room,
it can infer everything it needs to."* BRUH Minecraft indexes the world in
the background (panel/atlas.py): a summary per chunk, re-read only when the
region header says the chunk changed, and from those the buildings, their
rooms (enclosed air, with the floor, the free floor cells, doors, windows,
light, furniture and a guessed kind), the roads between them, and labels
(signs, and names a person gives).

These build a tiny world here: a small house with two rooms, a door between
them, a window, a bed in one room and a sign in the other, and a path
outside.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_companion_edit import section_with_states  # noqa: E402
from test_minecraft_layout import TS, chunk_nbt, write_region  # noqa: E402
from test_minecraft_world import PANEL  # noqa: E402


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PANEL / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


atlas = _load("test_bruh_mc_atlas", "atlas.py")
OW = "minecraft:overworld"

PALETTE = [
    ("minecraft:air", None), ("minecraft:stone", None), ("minecraft:oak_planks", None),
    ("minecraft:oak_door", {"facing": "east", "half": "lower", "hinge": "left", "open": "false"}),
    ("minecraft:oak_door", {"facing": "east", "half": "upper", "hinge": "left", "open": "false"}),
    ("minecraft:red_bed", {"facing": "east", "occupied": "false", "part": "foot"}),
    ("minecraft:red_bed", {"facing": "east", "occupied": "false", "part": "head"}),
    ("minecraft:glass", None),
    ("minecraft:oak_wall_sign", {"facing": "south", "waterlogged": "false"}),
    ("minecraft:torch", None),
    ("minecraft:dirt_path", None),
    ("minecraft:chest", {"facing": "north", "type": "single", "waterlogged": "false"}),
]
P = {name if props is None else f"{name}:{i}": i for i, (name, props) in enumerate(PALETTE)}


def house() -> dict:
    """{(x, y, z): palette index} — a house at x 2..12, z 2..8: a plank floor
    at y 64, walls y 65..67, a ceiling at 68; an inside wall at x 7 with a
    door at (7, 65, 5); room A (x 3..6) has a bed, room B (x 8..11) a sign,
    a torch and a chest; a glass window in the west wall; a path at z 10."""
    b = {}
    for x in range(16):
        for z in range(16):
            b[(x, 63, z)] = P["minecraft:stone"]
    for x in range(2, 13):
        for z in range(2, 9):
            b[(x, 64, z)] = P["minecraft:oak_planks"]
            b[(x, 68, z)] = P["minecraft:oak_planks"]
            for y in (65, 66, 67):
                if x in (2, 7, 12) or z in (2, 8):
                    b[(x, y, z)] = P["minecraft:oak_planks"]
    b[(7, 65, 5)] = P["minecraft:oak_door:3"]
    b[(7, 66, 5)] = P["minecraft:oak_door:4"]
    b[(2, 66, 5)] = P["minecraft:glass"]
    b[(4, 65, 4)] = P["minecraft:red_bed:5"]
    b[(5, 65, 4)] = P["minecraft:red_bed:6"]
    b[(10, 66, 3)] = P["minecraft:oak_wall_sign:8"]
    b[(11, 65, 7)] = P["minecraft:torch"]
    b[(11, 65, 3)] = P["minecraft:chest:11"]
    for x in range(2, 15):
        b[(x, 63, 10)] = P["minecraft:dirt_path"]
    return b


def house_chunk(extra: dict | None = None) -> bytes:
    blocks = house()
    blocks.update(extra or {})
    by_section: dict = {}
    for (x, y, z), v in blocks.items():
        by_section.setdefault(y >> 4, {})[(x, y & 15, z)] = v
    sections = [section_with_states(sy, PALETTE, cells) for sy, cells in by_section.items()]
    sign = {"id": ("string", "minecraft:sign"), "x": ("int", 10), "y": ("int", 66),
            "z": ("int", 3), "front_text": ("compound", {"messages": ("list", ("string", [
                '{"text":"Ben\'s"}', '"workshop"', '""', '""']))})}
    bed = {"id": ("string", "minecraft:bed"), "x": ("int", 5), "y": ("int", 65), "z": ("int", 4)}
    chest = {"id": ("string", "minecraft:chest"), "x": ("int", 11), "y": ("int", 65),
             "z": ("int", 3)}
    return chunk_nbt(sections, [sign, bed, chest])


class AtlasBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.world = self.root / "server" / "world"
        self.region = self.world / "dimensions" / "minecraft" / "overworld" / "region"
        write_region(self.region, {(0, 0): house_chunk()})
        self.players: list[dict] = []
        self.data = self.root / "server" / ".bruh-world"
        self.atlas = self.make()

    def make(self):
        return atlas.Atlas(lambda: self.world, self.data, players=lambda: self.players,
                           places=lambda: [])

    def index(self, a=None) -> int:
        a = a or self.atlas
        done = 0
        for _ in range(20):
            done += a.step(budget=5.0)
            if not a.pending():
                break
        return done


class TestTheIndex(AtlasBase):
    def test_a_chunk_is_read_once_and_again_only_when_it_changes(self):
        self.assertEqual(self.index(), 1)
        self.assertEqual(self.index(), 0)                    # nothing changed
        later = self.make()                                  # a restart reads the cache
        self.assertEqual(self.index(later), 0)
        summary = later.summary(OW, 0, 0)
        self.assertEqual(summary["ts"], TS)
        self.assertGreater(summary["counts"]["oak_planks"], 100)
        self.assertNotIn("stone", summary["counts"])          # terrain is not "placed"
        self.assertTrue(any(t["id"] == "sign" and t["text"] == "Ben's workshop"
                            for t in summary["things"]))
        self.assertTrue((self.data / "atlas").is_dir())
        # The server writes the chunk again: its header timestamp moves.
        write_region(self.region, {(0, 0): house_chunk()}, ts=TS + 60)
        import os
        os.utime(self.region / "r.0.0.mca", (TS + 60, TS + 60))
        later.last_scan = -1e12
        self.assertEqual(self.index(later), 1)

    def test_work_per_pass_is_bounded(self):
        write_region(self.region, {(cx, 0): house_chunk() for cx in range(6)})
        first = self.atlas.step(budget=0.0)
        self.assertEqual(first, 1)                            # one chunk, then out of time
        self.assertGreater(self.atlas.pending(), 0)


class TestBuildingsAndRooms(AtlasBase):
    def setUp(self):
        super().setUp()
        self.index()

    def test_the_house_its_two_rooms_and_the_bedroom(self):
        got = self.atlas.query(x=7, z=5)
        self.assertEqual(len(got["buildings"]), 1)
        b = got["buildings"][0]
        self.assertEqual((b["box"]["x1"], b["box"]["z1"], b["box"]["x2"], b["box"]["z2"]),
                         (2, 2, 12, 8))
        self.assertEqual(len(b["rooms"]), 2)
        a = self.atlas.room(x=4, y=65, z=6)["room"]
        self.assertEqual(a["kind"], "bedroom")
        self.assertEqual(a["floor_y"], 65)
        self.assertEqual(a["floor_area"], 20)
        self.assertEqual(a["free_count"], 18)                 # 20 less the bed's two
        self.assertNotIn([4, 65, 4], a["free_floor"])
        self.assertIn([3, 65, 3], a["free_floor"])
        self.assertIn([7, 65, 5], a["doors"])
        self.assertEqual(a["windows"], [[2, 66, 5]])
        self.assertIn("oak_planks", a["palette"]["floor"])
        self.assertIn("red_bed", a["furniture"])
        # The other room: named by its sign, lit by its torch, with a chest.
        bee = self.atlas.room(x=9, y=65, z=6)["room"]
        self.assertEqual(bee["name"], "Ben's workshop")
        self.assertIn([7, 65, 5], bee["doors"])
        self.assertEqual(bee["light"]["sources"], 1)
        self.assertIn("chest", bee["furniture"])
        self.assertEqual(bee["free_count"], 17)   # less the torch, the chest, under the sign

    def test_a_road_outside_and_where_a_player_is(self):
        got = self.atlas.query(x=7, z=5)
        self.assertEqual(len(got["roads"]), 1)
        self.assertEqual(got["roads"][0]["material"], "dirt_path")
        self.assertEqual(got["roads"][0]["connects"], [got["buildings"][0]["id"]])
        self.players.append({"name": "Ben13765", "dimension": OW, "pos": [4.5, 65.0, 6.5]})
        here = self.atlas.query(player="ben13765")["here"]
        self.assertEqual(here["room"]["kind"], "bedroom")
        self.assertEqual(here["building"]["id"], got["buildings"][0]["id"])
        # The snapshot's cheap lookup, once the rooms are known.
        self.assertEqual(self.atlas.here(OW, 4.5, 65.0, 6.5)["room"]["kind"], "bedroom")
        self.assertIsNone(self.atlas.here(OW, 40, 65, 40)["building"])

    def test_a_label_names_the_room_and_survives_a_restart(self):
        out = self.atlas.label("Ben's room", by="Dad", x=4, y=65, z=6)
        self.assertEqual(out["label"]["target"], "room")
        self.assertEqual(self.atlas.room(x=4, y=65, z=6)["room"]["name"], "Ben's room")
        later = self.make()
        self.index(later)
        room = later.room(x=4, y=65, z=6)["room"]
        self.assertEqual(room["name"], "Ben's room")
        self.assertEqual(room["kind"], "bedroom")             # the guess stays
        found = later.query(x=7, z=5, query="ben")["matches"]
        self.assertEqual({m["name"] for m in found}, {"Ben's room", "Ben's workshop"})
        # Naming the building by its id, then again: the newer name wins.
        bid = later.query(x=7, z=5)["buildings"][0]["id"]
        later.label("The cabin", building=bid)
        later.label("Our cabin", building=bid)
        self.assertEqual(later.query(x=7, z=5)["buildings"][0]["name"], "Our cabin")
        labels = json.loads(next((self.data / "atlas").rglob("labels.json")).read_text())
        self.assertEqual(len(labels["labels"]), 2)

    def test_a_room_by_its_id_and_nothing_there(self):
        rid = self.atlas.room(x=4, y=65, z=6)["room"]["id"]
        self.assertEqual(self.atlas.room(room=rid)["room"]["kind"], "bedroom")
        with self.assertRaises(atlas.AtlasError):
            self.atlas.room(x=40, y=65, z=40)
        with self.assertRaises(atlas.AtlasError):
            self.atlas.room(room="r:overworld:not:an:id")


class TestTheSnapshotKnowsWhereEveryoneIs(unittest.TestCase):
    def test_players_carry_facing_room_and_building(self):
        from test_minecraft_companion import FakeWorld, mcworld

        class World(FakeWorld):
            def reply(self, cmd):
                if cmd.endswith(" Rotation"):
                    self.commands.append(cmd)
                    return "Ben13765 has the following entity data: [91.5f, -12.25f]"
                return super().reply(cmd)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            world = World()
            world.players["Ben13765"] = [4.5, 65.0, 6.5]
            col = mcworld.WorldCollector(rcon_factory=world.factory, server_dir=root,
                                         out_path=root / "world.json")
            col.where = lambda dim, pos: {"building": {"id": "b:overworld:2:2", "name": "x"},
                                          "room": {"id": "r", "name": "the bedroom",
                                                   "kind": "bedroom"}}
            col.step()
            p = col.snapshot()["players"][0]
            self.assertEqual((p["yaw"], p["pitch"]), (91.5, -12.2))
            self.assertEqual(p["room"]["kind"], "bedroom")
            self.assertEqual(p["building"]["id"], "b:overworld:2:2")


import test_minecraft_companion as _hands  # noqa: E402


class TestThePanelRoutes(_hands.PanelCase):
    async def test_the_new_routes_answer_in_words(self):
        r = await self.client.post("/api/atlas", json={})
        self.assertEqual(r.status, 400)
        self.assertIn("Give a player", (await r.json())["error"])
        r = await self.client.post("/api/atlas/room", json={"room": "nope"})
        self.assertEqual(r.status, 400)
        self.assertIn("not a room id", (await r.json())["error"])
        r = await self.client.post("/api/atlas/labels", json={"x": 1, "y": 64, "z": 1})
        self.assertEqual(r.status, 400)
        self.assertIn("called", (await r.json())["error"])
        r = await self.client.post("/api/companion/progress", json={"to": "Kaz", "text": "t"})
        self.assertEqual(r.status, 400)
        self.assertIn("not in the game", (await r.json())["error"])
        r = await self.client.post("/api/companion/spyglass", json={"player": "Kaz",
                                                                   "name": "S"})
        self.assertEqual(r.status, 400)
        r = await self.client.post("/api/companion/jobs/bad!/undo")
        self.assertEqual(r.status, 400)
        self.assertIn("not a job id", (await r.json())["error"])
        r = await self.client.post("/api/companion/jobs/job-1/undo")
        self.assertEqual((await r.json())["undone"], [])
        # The world's atlas answers for a world with nothing saved yet.
        r = await self.client.post("/api/atlas", json={"x": 0, "z": 0})
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())["buildings"], [])


if __name__ == "__main__":
    unittest.main()
