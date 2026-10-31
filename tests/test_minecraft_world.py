#!/usr/bin/env python3
"""BRUH Minecraft's world-activity layer (panel/mcworld.py, panel/mcmap.py).

The owner (#573) wanted to know what is going on in the world and what
is being built, not TPS. These drive the real collector against canned
RCON answers (a Paper server, a Bedrock player through Geyser whose name
starts with a dot, a server that is down), real Paper log lines, the
journal and the build log on disk, the panel's /api/world and /api/builds
routes, and the top-down renderer on a tiny region file built here.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import os
import struct
import sys
import tempfile
import time
import unittest
import zlib
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


mcworld = _load("test_bruh_mc_world", "mcworld.py")
mcmap = _load("test_bruh_mc_map", "mcmap.py")


# ---------------------------------------------------------------------------
# A Paper server, answered from a table
# ---------------------------------------------------------------------------
class FakeServer:
    """What a Paper 1.21 server answers over RCON, from a few facts."""

    def __init__(self):
        self.up = True
        self.players = {
            "Alex": {"Pos": "[100.5d, 64.0d, -20.25d]", "Dimension": '"minecraft:overworld"',
                     "Health": "18.5f", "foodLevel": "17", "playerGameType": "0"},
            ".KidPlays": {"Pos": "[-8.0d, 70.0d, 3.9d]", "Dimension": '"minecraft:the_nether"',
                          "Health": "20.0f", "foodLevel": "20", "playerGameType": "1"},
        }
        self.daytime = 13000
        self.day = 41
        self.raining = True
        self.thundering = False
        self.predicates = True
        self.commands: list[str] = []
        self.connections = 0

    def reply(self, cmd: str) -> str:
        self.commands.append(cmd)
        if cmd == "minecraft:list":
            names = list(self.players)
            return (f"There are {len(names)} of a max of 20 players online: "
                    + ", ".join("§a" + n + "§r" for n in names))
        if cmd == "minecraft:time query daytime":
            return f"The time is {self.daytime}"
        if cmd == "minecraft:time query day":
            return f"The time is {self.day}"
        if cmd.startswith("minecraft:execute if predicate"):
            if not self.predicates:
                return "Unknown or incomplete command, see below for error"
            on = self.thundering if "thundering" in cmd else self.raining
            return "Test passed" if on else "Test failed"
        if cmd.startswith("minecraft:data get entity "):
            rest = cmd[len("minecraft:data get entity "):]
            name, path = rest.rsplit(" ", 1)
            name = json.loads(name) if name.startswith('"') else name
            p = self.players.get(name)
            if not p:
                return "No entity was found"
            return f"{name} has the following entity data: {p[path]}"
        return "Unknown or incomplete command"

    def factory(self):
        server = self

        class Conn:
            def connect(self):
                if not server.up:
                    raise ConnectionRefusedError("refused")
                server.connections += 1

            def command(self, cmd):
                if not server.up:
                    raise ConnectionResetError("gone")
                return server.reply(cmd)

            def close(self):
                pass

        return Conn()


class Clock:
    def __init__(self, t=1_761_900_000.0):
        self.t = t

    def __call__(self):
        return self.t


class CollectorBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.server_dir = self.root / "server"
        (self.server_dir / "logs").mkdir(parents=True)
        self.log = self.server_dir / "logs" / "latest.log"
        self.log.write_text("[09:00:00] [Server thread/INFO]: Starting minecraft server\n")
        self.server = FakeServer()
        self.clock = Clock()
        self.col = mcworld.WorldCollector(
            rcon_factory=self.server.factory, server_dir=self.server_dir,
            out_path=self.root / "world.json", clock=self.clock)

    def append(self, *lines):
        with open(self.log, "a") as f:
            for line in lines:
                f.write(line + "\n")


class TestTheCollectorAsksTheServer(CollectorBase):
    def test_players_their_whereabouts_time_and_weather(self):
        self.col.step()
        snap = json.loads((self.root / "world.json").read_text())
        self.assertTrue(snap["reachable"])
        self.assertEqual(snap["online"], 2)
        by = {p["name"]: p for p in snap["players"]}
        self.assertEqual(set(by), {"Alex", ".KidPlays"})   # colour codes gone
        self.assertEqual((by["Alex"]["x"], by["Alex"]["y"], by["Alex"]["z"]), (100, 64, -20))
        self.assertEqual(by["Alex"]["dimension"], "minecraft:overworld")
        self.assertEqual(by["Alex"]["health"], 18.5)
        self.assertEqual(by["Alex"]["food"], 17)
        self.assertEqual(by["Alex"]["gamemode"], "survival")
        self.assertEqual(by[".KidPlays"]["dimension"], "minecraft:the_nether")
        self.assertEqual(by[".KidPlays"]["gamemode"], "creative")
        self.assertEqual(snap["time"]["day"], 41)
        self.assertEqual(snap["time"]["phase"], "sunset")
        self.assertEqual(snap["time"]["clock"], "19:00")
        self.assertEqual(snap["weather"]["state"], "rain")
        self.assertEqual(snap["weather"]["source"], "server")

    def test_a_bedrock_name_with_a_leading_dot_is_asked_for_unquoted(self):
        self.col.step()
        self.assertIn("minecraft:data get entity .KidPlays Pos", self.server.commands)
        # A `*` Floodgate prefix is not a bare word to Brigadier: quoted.
        self.assertEqual(mcworld.quote_name("*KidPlays"), '"*KidPlays"')
        self.assertEqual(mcworld.quote_name(".KidPlays"), ".KidPlays")

    def test_one_connection_while_people_are_on(self):
        for _ in range(4):
            self.col.step()
            self.clock.t += mcworld.BUSY_INTERVAL
        self.assertEqual(self.server.connections, 1)

    def test_nobody_on_is_one_cheap_poll_a_minute(self):
        self.server.players = {}
        self.col.step()
        asked = len(self.server.commands)
        self.assertLessEqual(asked, 5)
        for _ in range(10):
            self.clock.t += mcworld.LOG_INTERVAL
            self.col.step()
        self.assertEqual(len(self.server.commands), asked, "polled again inside the minute")
        self.clock.t += mcworld.IDLE_INTERVAL
        self.col.step()
        self.assertGreater(len(self.server.commands), asked)
        self.assertFalse(any("data get" in c for c in self.server.commands))

    def test_a_join_in_the_log_is_polled_at_once(self):
        self.server.players = {}
        self.col.step()
        self.server.players = {"Alex": FakeServer().players["Alex"]}
        self.append("[10:00:00] [Server thread/INFO]: Alex joined the game")
        self.clock.t += mcworld.LOG_INTERVAL
        self.col.step()
        snap = self.col.snapshot()
        self.assertEqual([p["name"] for p in snap["players"]], ["Alex"])
        self.assertEqual(snap["feed"][0]["text"], "Alex joined")

    def test_a_server_that_is_down(self):
        self.server.up = False
        self.col.step()
        snap = self.col.snapshot()
        self.assertFalse(snap["reachable"])
        self.assertEqual(snap["online"], 0)
        self.assertEqual(snap["players"], [])
        self.assertIsNone(snap["time"])

    def test_people_on_then_the_server_goes_down(self):
        self.col.step()
        self.server.up = False
        self.clock.t += mcworld.BUSY_INTERVAL
        self.col.step()
        snap = self.col.snapshot()
        self.assertEqual(snap["players"], [])
        self.assertIn("Alex", snap["last_seen"])

    def test_weather_falls_back_to_the_save_when_the_server_cannot_say(self):
        self.server.predicates = False
        level = self.server_dir / "world" / "level.dat"
        level.parent.mkdir()
        level.write_bytes(gzip.compress(nbt_root({"Data": ("compound", {
            "raining": ("byte", 1), "thundering": ("byte", 1),
            "SpawnX": ("int", 0), "SpawnZ": ("int", 0)})})))
        col = mcworld.WorldCollector(
            rcon_factory=self.server.factory, server_dir=self.server_dir,
            out_path=self.root / "w2.json", clock=self.clock, read_nbt=mcmap.read_nbt_file)
        col.step()
        self.assertEqual(col.snapshot()["weather"]["state"], "thunder")
        self.assertEqual(col.snapshot()["weather"]["source"], "save")
        # And it says where people are by the places it knows: spawn.
        by = {p["name"]: p for p in col.snapshot()["players"]}
        self.assertIsNone(by["Alex"]["near"])      # 100 blocks out
        self.server.players["Alex"]["Pos"] = "[10.0d, 64.0d, 5.0d]"
        self.clock.t += mcworld.BUSY_INTERVAL
        col.step()
        self.assertEqual({p["name"]: p for p in col.snapshot()["players"]}["Alex"]["near"], "spawn")

    def test_clock_and_phase(self):
        self.assertEqual(mcworld.clock_of(0), (6, 0))
        self.assertEqual(mcworld.clock_of(18000), (0, 0))
        self.assertEqual(mcworld.clock_of(6500), (12, 30))
        self.assertEqual([mcworld.phase_of(t) for t in (100, 12500, 18000, 23000)],
                         ["day", "sunset", "night", "sunrise"])


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------
PAPER_LOG = """\
[18:02:11] [Server thread/INFO]: Done (6.214s)! For help, type "help"
[18:03:40] [User Authenticator #0/INFO]: UUID of player .KidPlays is 00000000-0000-0000-0009-01f8e1a2b3c4
[18:03:41] [Server thread/INFO]: .KidPlays[/192.168.1.42:51234] logged in with entity id 211 at ([world]10.5, 64.0, 3.5)
[18:03:41] [Server thread/INFO]: .KidPlays joined the game
[18:04:02] [Async Chat Thread - #0/INFO]: <.KidPlays> look at my house
[18:04:30] [Server thread/INFO]: [Not Secure] <Alex> nice!
[18:05:12] [Server thread/INFO]: .KidPlays has made the advancement [Stone Age]
[18:06:00] [Server thread/INFO]: .KidPlays was slain by Zombie
[18:06:30] [Server thread/INFO]: Alex fell from a high place
[18:07:00] [Server thread/INFO]: Alex has completed the challenge [Monster Hunter]
[18:07:30] [Server thread/WARN]: .KidPlays moved too quickly! 12.3,0.0,4.1
[18:08:00] [Server thread/INFO]: Named entity Wolf['Rex'/312, l='ServerLevel[world]', x=1.5, y=64.0, z=2.5] died: Rex was slain by Zombie
[18:09:00] [Server thread/INFO]: Saved the game
[18:10:00] [Server thread/INFO]: .KidPlays lost connection: Disconnected
[18:10:00] [Server thread/INFO]: .KidPlays left the game
[18:11:00] [Server thread/INFO]: Stopping server
"""


class TestTheLog(unittest.TestCase):
    def kinds(self, text, known=frozenset()):
        out = []
        for line in text.splitlines():
            ev = mcworld.parse_log_line(line, known)
            if ev:
                out.append((ev["kind"], ev["player"], ev["text"]))
        return out

    def test_a_real_paper_log(self):
        self.assertEqual(self.kinds(PAPER_LOG), [
            ("server", None, "The server started"),
            ("join", ".KidPlays", ".KidPlays joined"),
            ("chat", ".KidPlays", ".KidPlays: look at my house"),
            ("chat", "Alex", "Alex: nice!"),
            ("advancement", ".KidPlays", ".KidPlays made the advancement Stone Age"),
            ("death", ".KidPlays", ".KidPlays was slain by Zombie"),
            ("death", "Alex", "Alex fell from a high place"),
            ("advancement", "Alex", "Alex completed the challenge Monster Hunter"),
            ("save", None, "The world was saved"),
            ("leave", ".KidPlays", ".KidPlays left"),
            ("server", None, "The server is stopping"),
        ])

    def test_the_console_format_reads_the_same(self):
        self.assertEqual(self.kinds("[18:03:41 INFO]: .KidPlays joined the game"),
                         [("join", ".KidPlays", ".KidPlays joined")])

    def test_a_death_has_to_be_somebody_known_when_names_are_known(self):
        line = "[18:06:00] [Server thread/INFO]: Plugin fell over while loading"
        self.assertEqual(self.kinds(line, frozenset({"Alex"})), [])

    def test_the_tail_follows_a_new_log_after_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "latest.log"
            log.write_text("[1:00:00] old\n")
            tail = mcworld.LogTail([log])
            self.assertEqual(tail.read(), [])          # starts at the end
            with open(log, "a") as f:
                f.write("one\ntw")
            self.assertEqual(tail.read(), ["one"])     # half a line waits
            with open(log, "a") as f:
                f.write("o\n")
            self.assertEqual(tail.read(), ["two"])
            os.replace(log, Path(tmp) / "old.log")
            log.write_text("fresh\n")
            self.assertEqual(tail.read(), ["fresh"])


class TestFeedAndJournal(CollectorBase):
    def test_sessions_feed_last_seen_and_the_days_journal(self):
        self.server.players = {}
        self.col.step()
        self.append("[18:03:41] [Server thread/INFO]: .KidPlays joined the game")
        self.server.players = {".KidPlays": FakeServer().players[".KidPlays"]}
        self.clock.t += 2
        self.col.step()
        self.clock.t += 1500
        self.append("[18:04:02] [Async Chat Thread - #0/INFO]: <.KidPlays> look at my house",
                    "[18:06:00] [Server thread/INFO]: .KidPlays was slain by Zombie",
                    "[18:10:00] [Server thread/INFO]: .KidPlays left the game")
        self.server.players = {}
        self.col.step()
        snap = self.col.snapshot()
        self.assertEqual([e["kind"] for e in snap["feed"]], ["leave", "death", "chat", "join"])
        self.assertEqual(snap["feed"][0]["text"], ".KidPlays left after 25 min")
        self.assertEqual(snap["last_seen"][".KidPlays"], int(self.clock.t))
        day = mcworld.Journal.day_of(self.clock.t)
        lines = (self.server_dir / ".bruh-world" / "journal" / f"{day}.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(x)["kind"] for x in lines], ["join", "chat", "death", "leave"])
        summary = self.col.journal.summary(day)
        self.assertEqual(summary["players"], {".KidPlays": 1500})
        self.assertEqual(summary["counts"]["death"], 1)
        # A new collector (the panel restarted) has the feed back.
        again = mcworld.WorldCollector(rcon_factory=self.server.factory,
                                       server_dir=self.server_dir,
                                       out_path=self.root / "w.json", clock=self.clock)
        self.assertEqual([e["kind"] for e in again.snapshot()["feed"]],
                         ["leave", "death", "chat", "join"])
        self.assertIn(".KidPlays", again.snapshot()["last_seen"])

    def test_the_feed_keeps_the_last_fifty(self):
        for i in range(70):
            self.col.record({"kind": "chat", "player": "Alex", "text": f"Alex: {i}"})
        feed = self.col.snapshot()["feed"]
        self.assertEqual(len(feed), mcworld.FEED_SIZE)
        self.assertEqual(feed[0]["text"], "Alex: 69")

    def test_a_player_gone_from_the_list_without_a_leave_line_is_closed(self):
        self.col.step()
        self.server.players.pop("Alex")
        for _ in range(2):
            self.clock.t += mcworld.BUSY_INTERVAL
            self.col.step()
        self.assertNotIn("Alex", self.col.sessions)
        self.assertEqual(self.col.snapshot()["feed"][0]["kind"], "leave")


# ---------------------------------------------------------------------------
# The build log
# ---------------------------------------------------------------------------
class TestTheBuildLog(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.log = mcworld.BuildLog(Path(tmp.name) / "builds.json", self.clock)

    def test_create_update_list_delete(self):
        a = self.log.create({"title": "Watchtower", "part": "curiosity",
                             "bounds": {"x1": 0, "z1": 0, "x2": 8.4, "z2": 8, "y1": 60, "y2": 90}})
        self.assertEqual(a["status"], "queued")
        self.assertEqual(a["bounds"]["dimension"], "minecraft:overworld")
        self.assertEqual(a["bounds"]["x2"], 8)
        self.clock.t += 10
        b = self.log.create({"title": "Bridge", "status": "building", "progress": 30})
        self.assertEqual(b["started_at"], int(self.clock.t))
        self.assertEqual([j["title"] for j in self.log.list()], ["Bridge", "Watchtower"])
        self.assertEqual(self.log.current()["id"], b["id"])
        self.clock.t += 100
        done = self.log.update(b["id"], {"status": "done"})
        self.assertEqual(done["progress"], 100)
        self.assertEqual(done["finished_at"], int(self.clock.t))
        self.assertIsNone(self.log.current())
        self.assertEqual([j["title"] for j in self.log.list(status="done")], ["Bridge"])
        self.assertTrue(self.log.delete(a["id"]))
        self.assertFalse(self.log.delete(a["id"]))
        self.assertIsNone(self.log.update("nope", {"title": "x"}))

    def test_what_is_refused(self):
        for bad in ({}, {"title": " "}, {"title": "x", "status": "maybe"},
                    {"title": "x", "progress": "lots"},
                    {"title": "x", "bounds": {"x1": 0}},
                    {"title": "x", "bounds": {"x1": 0, "z1": 0, "x2": 1, "z2": 1,
                                              "dimension": "../../etc"}}):
            with self.assertRaises(mcworld.BuildError, msg=bad):
                self.log.create(bad)


# ---------------------------------------------------------------------------
# The renderer, on a region file made here
# ---------------------------------------------------------------------------
def _tag(kind, value):
    if kind == "byte":
        return 1, struct.pack(">b", value)
    if kind == "int":
        return 3, struct.pack(">i", value)
    if kind == "string":
        b = value.encode()
        return 8, struct.pack(">H", len(b)) + b
    if kind == "longs":
        return 12, struct.pack(">i", len(value)) + b"".join(struct.pack(">Q", v) for v in value)
    if kind == "list":
        inner_kind, items = value
        encoded = [_tag(inner_kind, v) for v in items]
        tid = encoded[0][0] if encoded else 0
        return 9, struct.pack(">bi", tid, len(items)) + b"".join(e[1] for e in encoded)
    if kind == "compound":
        body = b""
        for name, (k, v) in value.items():
            tid, payload = _tag(k, v)
            nb = name.encode()
            body += struct.pack(">bH", tid, len(nb)) + nb + payload
        return 10, body + b"\x00"
    raise ValueError(kind)


def nbt_root(fields):
    _, body = _tag("compound", fields)
    return b"\x0a\x00\x00" + body


def section(y, palette, blocks):
    """A 1.18+ section; `blocks` maps (x, y, z) local to a palette index."""
    bits = max(4, (len(palette) - 1).bit_length())
    per = 64 // bits
    longs = [0] * ((4096 + per - 1) // per)
    for (x, ly, z), v in blocks.items():
        idx = (ly * 16 + z) * 16 + x
        longs[idx // per] |= v << ((idx % per) * bits)
    states = {"palette": ("list", ("compound", [{"Name": ("string", n)} for n in palette]))}
    if len(palette) > 1:
        states["data"] = ("longs", longs)
    return {"Y": ("byte", y), "block_states": ("compound", states)}


def region_with(chunks):
    """An .mca holding {(cx, cz): chunk NBT bytes}, zlib-compressed."""
    header = bytearray(8192)
    body = b""
    sector = 2
    for (cx, cz), nbt in chunks.items():
        data = zlib.compress(nbt)
        blob = struct.pack(">I", len(data) + 1) + b"\x02" + data
        blob += b"\x00" * (-len(blob) % 4096)
        i = 4 * ((cx & 31) + (cz & 31) * 32)
        header[i:i + 3] = sector.to_bytes(3, "big")
        header[i + 3] = len(blob) // 4096
        body += blob
        sector += len(blob) // 4096
    return bytes(header) + body


class TestTheRenderer(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.world = Path(tmp.name) / "world"
        (self.world / "region").mkdir(parents=True)
        # Chunk (0,0): grass at y=64 everywhere; a 3x3 red wool tower to y=70
        # at x 4..6, z 4..6; water at x=0. Section 4 holds y 64..79.
        blocks = {}
        for x in range(16):
            for z in range(16):
                blocks[(x, 0, z)] = 2 if x == 0 else 1
        for x in range(4, 7):
            for z in range(4, 7):
                for y in range(1, 7):
                    blocks[(x, y, z)] = 3
        sec = section(4, ["minecraft:air", "minecraft:grass_block", "minecraft:water",
                          "minecraft:red_wool"], blocks)
        root = nbt_root({"DataVersion": ("int", 3953),
                         "sections": ("list", ("compound", [sec, section(5, ["minecraft:air"], {})]))})
        (self.world / "region" / "r.0.0.mca").write_bytes(region_with({(0, 0): root}))

    def test_reads_the_top_block_of_each_column(self):
        rows = mcmap.top_blocks(self.world / "region", 0, 0, 7, 7)
        self.assertEqual(rows[5][5], ("red_wool", 70))
        self.assertEqual(rows[1][1], ("grass_block", 64))
        self.assertEqual(rows[1][0], ("water", 64))

    def test_draws_a_png_of_the_box(self):
        out = self.world.parent / "www" / "job.png"
        result = mcmap.render_bounds(self.world, {"x1": 0, "z1": 0, "x2": 15, "z2": 15,
                                                  "dimension": "minecraft:overworld"}, out)
        self.assertEqual(result["columns"], 256)
        png = out.read_bytes()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        w, h = struct.unpack(">II", png[16:24])
        self.assertEqual((w, h), (16 * 8, 16 * 8))
        # The tower's colour is in the picture.
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        stride = 1 + w * 4
        y, x = 5 * 8, 5 * 8
        px = raw[y * stride + 1 + x * 4: y * stride + 1 + x * 4 + 4]
        self.assertEqual(tuple(px), (*mcmap.DYES["red"], 255))
        self.assertEqual(mcmap.colour("minecraft:red_wool"), mcmap.DYES["red"])

    def test_a_box_with_nothing_saved_says_so(self):
        out = self.world.parent / "none.png"
        result = mcmap.render_bounds(self.world, {"x1": 500, "z1": 500, "x2": 510, "z2": 510}, out)
        self.assertIn("error", result)
        self.assertFalse(out.exists())
        self.assertIn("error", mcmap.render_bounds(self.world, {"x1": 1}, out))


# ---------------------------------------------------------------------------
# The panel's routes
# ---------------------------------------------------------------------------
def _load_panel(server_dir: Path, backup_dir: Path, state_dir: Path, www: Path):
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
    os.environ["MC_SERVER_DIR"] = str(server_dir)
    os.environ["MC_BACKUP_DIR"] = str(backup_dir)
    os.environ["MC_PANEL_STATE"] = str(state_dir)
    os.environ["MC_CONSOLE_LOG"] = str(state_dir / "console.log")
    os.environ["MC_WWW_DIR"] = str(www)
    spec = importlib.util.spec_from_file_location("panel_server_world", PANEL / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestThePanelRoutes(AioHTTPTestCase):
    async def get_application(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.server_dir = root / "server"
        self.server_dir.mkdir()
        (root / "backups").mkdir()
        (root / "state").mkdir()
        self.www = root / "www"
        (self.server_dir / "server.properties").write_text("level-name=world\n")
        self.panel = _load_panel(self.server_dir, root / "backups", root / "state", self.www)
        self.addCleanup(lambda: os.environ.pop("MC_WWW_DIR", None))
        return self.panel.build_app()

    async def test_build_log_crud_over_http(self):
        r = await self.client.post("/api/builds", json={"title": "Watchtower", "part": "curiosity"})
        self.assertEqual(r.status, 201)
        job = (await r.json())["job"]
        r = await self.client.patch(f"/api/builds/{job['id']}", json={"status": "building", "progress": 40})
        self.assertEqual((await r.json())["job"]["progress"], 40)
        r = await self.client.get("/api/builds")
        body = await r.json()
        self.assertEqual(body["current"]["id"], job["id"])
        self.assertEqual([j["title"] for j in body["jobs"]], ["Watchtower"])
        r = await self.client.post(f"/api/builds/{job['id']}", json={"status": "nope"})
        self.assertEqual(r.status, 400)
        self.assertIn("status", (await r.json())["error"])
        r = await self.client.get("/api/world")
        world = await r.json()
        self.assertEqual(world["builds"]["current"]["title"], "Watchtower")
        # A job that names nobody is brAIn's (the add-on names no persona).
        self.assertEqual(world["feed"][0]["text"], "brAIn started building Watchtower")
        r = await self.client.delete(f"/api/builds/{job['id']}")
        self.assertEqual(r.status, 200)
        r = await self.client.get(f"/api/builds/{job['id']}")
        self.assertEqual(r.status, 404)
        r = await self.client.get("/api/builds/../../etc")
        self.assertEqual(r.status, 404)

    async def test_render_writes_the_picture_and_links_it(self):
        world = self.server_dir / "world"
        TestTheRenderer.setUp(self)              # builds a region under self.world
        import shutil
        shutil.copytree(self.world, world)
        r = await self.client.post("/api/builds", json={
            "title": "Tower", "bounds": {"x1": 0, "z1": 0, "x2": 7, "z2": 7}})
        job = (await r.json())["job"]
        r = await self.client.post(f"/api/builds/{job['id']}/render")
        self.assertEqual(r.status, 200, await r.text())
        body = await r.json()
        self.assertTrue((self.www / f"{job['id']}.png").is_file())
        self.assertTrue(body["job"]["image"].startswith(f"/local/minecraft/{job['id']}.png?v="))
        r = await self.client.post("/api/builds", json={"title": "No box"})
        other = (await r.json())["job"]
        r = await self.client.post(f"/api/builds/{other['id']}/render")
        self.assertEqual(r.status, 409)

    async def test_journal_route(self):
        r = await self.client.get("/api/world/journal")
        self.assertEqual(await r.json(), {"days": []})
        r = await self.client.get("/api/world/journal?day=nonsense")
        self.assertEqual(r.status, 400)
        day = time.strftime("%Y-%m-%d")
        r = await self.client.get(f"/api/world/journal?day={day}")
        self.assertEqual((await r.json())["events"], [])


if __name__ == "__main__":
    unittest.main()
