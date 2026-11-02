"""BRUH Sight: the panel sees the live world, and shows the companion's thoughts.

The owner: *"The vesper experience in minecraft is terrible. It's really
unresponsive and slow and like you can't see what it is doing. It says it
can't see the actual server."* The panel knew the world only through RCON
(six `data get` commands a player, every five seconds) and the region files
the server writes minutes after a change, so a box read where an unsaved
build stood came back empty (#620). BRUH Sight is a plugin inside the server
(`bruh-minecraft-server/sight/`) that answers the panel on loopback with a
token: players as they are this second (and what is under each crosshair),
and blocks as they are now. And — *"Make sure it's not super annoying. It
could be represented over vesper's allay or be shown in an item"* — it shows
the companion's thinking in a bubble only the asking player sees and in a
journal book, never chat.

These drive `panel/sight.py` against a fake plugin on a real loopback
socket (token checked), and the collector, the spyglass, the box reader and
the thought route with the plugin there and not.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADDON = HERE.parent / "bruh-minecraft-server"
PANEL = ADDON / "panel"
sys.path.insert(0, str(HERE))


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, PANEL / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sight = _load("test_bruh_mc_sight", "sight.py")
mcmap = _load("bruh_mc_map", "mcmap.py")
mcworld = _load("bruh_mc_world", "mcworld.py")
spyglass = _load("test_bruh_mc_spyglass_live", "spyglass.py")

TOKEN = "f" * 48
BEN = {"name": "Ben13765", "uuid": "u-1", "dimension": "minecraft:overworld",
       "pos": [10.25, 64.0, -3.5], "yaw": -90.0, "pitch": 12.5, "health": 20.0, "food": 18,
       "gamemode": "survival", "level": 3, "doing": ["sneaking"],
       "looking_at": {"x": 14, "y": 64, "z": -4, "block": "minecraft:oak_door[facing=east]",
                      "face": "west", "distance": 3.6},
       "holding": {"item": "oak_planks", "count": 32},
       "inventory": {"oak_planks": 32, "torch": 12}, "nearby": [], "recent_blocks": [
           {"t": 1, "action": "placed", "block": "minecraft:oak_planks", "x": 13, "y": 64,
            "z": -4}]}


class FakePlugin:
    """The plugin's HTTP side, on a real loopback port."""

    def __init__(self, root: Path):
        self.root = root
        self.asked: list[tuple[str, str, dict | None]] = []
        self.players = [BEN]
        self.unread = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(n) or b"{}")

            def do_GET(self):
                outer.asked.append(("GET", self.path, None))
                if self.headers.get("X-Bruh-Token") != TOKEN:
                    return self._answer(401, {"error": "unauthorized"})
                if self.path == "/v1/state":
                    return self._answer(200, {"t": 1, "worlds": [], "players": outer.players})
                return self._answer(404, {})

            def do_POST(self):
                body = self._body()
                outer.asked.append(("POST", self.path, body))
                if self.headers.get("X-Bruh-Token") != TOKEN:
                    return self._answer(401, {"error": "unauthorized"})
                if self.path == "/v1/blocks":
                    if outer.unread:
                        return self._answer(200, {"unread": outer.unread})
                    box = [body[k] for k in ("x1", "y1", "z1", "x2", "y2", "z2")]
                    n = ((box[3] - box[0] + 1) * (box[4] - box[1] + 1) * (box[5] - box[2] + 1))
                    # Stone everywhere but the cell (x1, y1, z1).
                    return self._answer(200, {"dimension": "minecraft:overworld", "box": box,
                                              "palette": ["minecraft:air", "minecraft:stone"],
                                              "cells": [0] + [1] * (n - 1)})
                if self.path == "/v1/thought":
                    return self._answer(200, {"shown": True})
                if self.path == "/v1/focus":
                    return self._answer(200, {"moved": 1})
                if self.path == "/v1/journal":
                    return self._answer(200, {"given": True})
                return self._answer(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.write_endpoint()

    def write_endpoint(self, token=TOKEN):
        ep = self.root / sight.ENDPOINT
        ep.parent.mkdir(parents=True, exist_ok=True)
        ep.write_text(json.dumps({"host": "127.0.0.1", "port": self.server.server_port,
                                  "token": token}))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class SightCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.plugin = FakePlugin(self.root)
        self.addCleanup(self.plugin.close)
        self.clock = Clock()
        self.sight = sight.Sight(self.root, clock=self.clock)


class TestTheClient(SightCase):
    def test_players_as_they_are_this_second_with_the_token(self):
        live = self.sight.players()
        self.assertEqual(set(live), {"Ben13765"})
        self.assertEqual(live["Ben13765"]["looking_at"]["block"], "minecraft:oak_door[facing=east]")
        self.assertTrue(self.sight.available)

    def test_one_state_answers_every_caller_for_a_moment(self):
        self.sight.players()
        self.sight.player("Ben13765")
        self.assertEqual(len([a for a in self.plugin.asked if a[1] == "/v1/state"]), 1)
        self.clock.t += sight.STATE_FRESH_S + 0.1
        self.sight.players()
        self.assertEqual(len([a for a in self.plugin.asked if a[1] == "/v1/state"]), 2)

    def test_a_wrong_token_is_no_answer_and_backs_off(self):
        self.plugin.write_endpoint(token="nope")
        self.assertIsNone(self.sight.players())
        asked = len(self.plugin.asked)
        self.clock.t += 1
        self.assertIsNone(self.sight.players())
        self.assertEqual(len(self.plugin.asked), asked, "backed off: not asked again at once")
        self.plugin.write_endpoint()
        self.clock.t += sight.BACKOFF_S + 0.1
        self.assertIsNotNone(self.sight.players())

    def test_without_the_plugin_every_call_is_none_and_costs_no_wait(self):
        bare = sight.Sight(self.root / "elsewhere", clock=self.clock)
        self.assertIsNone(bare.players())
        self.assertIsNone(bare.blocks("minecraft:overworld", (0, 0, 0, 1, 1, 1)))
        self.assertIsNone(bare.thought({"player": "Ben13765", "text": "x"}))
        self.assertFalse(bare.available)

    def test_blocks_now_every_cell_air_included(self):
        got = self.sight.blocks("minecraft:overworld", (2, 64, 5, 0, 63, 4))
        self.assertEqual(len(got), 3 * 2 * 2)
        self.assertEqual(got[(0, 63, 4)], "minecraft:air")
        self.assertEqual(got[(2, 64, 5)], "minecraft:stone")

    def test_never_generated_is_said_not_guessed(self):
        self.plugin.unread = {"code": "not_generated", "chunk": [9, 9], "why": "never generated"}
        got = self.sight.blocks("minecraft:overworld", (0, 0, 0, 1, 1, 1))
        self.assertEqual(got["unread"]["code"], "not_generated")

    def test_a_box_beyond_the_plugins_cap_is_not_asked(self):
        self.assertIsNone(self.sight.blocks("minecraft:overworld", (0, -64, 0, 300, 300, 300)))
        self.assertFalse([a for a in self.plugin.asked if a[1] == "/v1/blocks"])

    def test_live_info_is_the_collectors_shape_with_the_extras(self):
        info = sight.live_info(BEN)
        self.assertEqual(info["pos"], [10.2, 64.0, -3.5])
        self.assertEqual((info["yaw"], info["pitch"], info["food"]), (-90.0, 12.5, 18))
        self.assertEqual(info["live"]["holding"], {"item": "oak_planks", "count": 32})
        self.assertNotIn("nearby", info["live"], "an empty list is left out")


class TestTheCollector(SightCase):
    def make(self):
        (self.root / "logs").mkdir(exist_ok=True)
        (self.root / "logs" / "latest.log").write_text("")
        from test_minecraft_world import FakeServer
        self.rcon = FakeServer()
        self.rcon.players = {"Ben13765": {"Pos": "[10.0d, 64.0d, -3.0d]",
                                          "Dimension": '"minecraft:overworld"', "Health": "20.0f",
                                          "foodLevel": "20", "playerGameType": "0",
                                          "Rotation": "[0.0f, 0.0f]"}}
        col = mcworld.WorldCollector(rcon_factory=self.rcon.factory, server_dir=self.root,
                                     out_path=self.root / "world.json", clock=self.clock)
        return col

    def test_live_players_replace_the_rcon_questions_and_the_beat_is_a_second(self):
        col = self.make()
        col.live = lambda: {n: sight.live_info(p) for n, p in (self.sight.players() or {}).items()}
        col.step()
        self.assertFalse([c for c in self.rcon.commands if "data get entity" in c])
        snap = json.loads((self.root / "world.json").read_text())
        self.assertTrue(snap["live"])
        ben = snap["players"][0]
        self.assertEqual((ben["x"], ben["y"], ben["z"]), (10, 64, -4))
        self.assertEqual(ben["looking_at"]["x"], 14)
        self.assertEqual(ben["recent_blocks"][0]["action"], "placed")
        self.assertEqual(col.next_poll - self.clock.t, mcworld.LIVE_INTERVAL)

    def test_without_the_plugin_rcon_is_asked_as_before(self):
        col = self.make()
        col.live = lambda: None
        col.step()
        self.assertTrue([c for c in self.rcon.commands if "data get entity" in c])
        snap = json.loads((self.root / "world.json").read_text())
        self.assertFalse(snap["live"])
        self.assertEqual(col.next_poll - self.clock.t, mcworld.BUSY_INTERVAL)


class TestTheSpyglassSeesLive(unittest.TestCase):
    def test_the_servers_own_ray_no_save_no_region_files(self):
        events, saves = [], []

        class Col:
            sessions = {"Ben13765": 0.0}
            reachable = True
            nicknames = {}
            session = None

        pointer = spyglass.Pointer(Col(), world_dir=lambda: Path("/nowhere"), emit=events.append,
                                   save=lambda: saves.append(1),
                                   live=lambda name: BEN if name == "Ben13765" else None,
                                   clock=lambda: 5.0)
        pointer._point("Ben13765")
        self.assertEqual(saves, [])
        self.assertEqual(events[0]["target"], {"x": 14, "y": 64, "z": -4,
                                               "block": "minecraft:oak_door[facing=east]"})
        self.assertEqual(events[0]["dimension"], "minecraft:overworld")


class TestAnUnknownChunkLayoutIsSaid(unittest.TestCase):
    """#620: every box read as all air. A chunk with no block sections where
    every known layout keeps them is now an answer that says so."""

    def test_no_sections_is_unreadable_not_air(self):
        from test_minecraft_layout import write_region
        from test_minecraft_world import nbt_root
        with tempfile.TemporaryDirectory() as tmp:
            region = Path(tmp) / "region"
            write_region(region, {(0, 0): nbt_root({"DataVersion": ("int", 9999),
                                                    "xPos": ("int", 0)})})
            got = mcmap.box_states(region, 0, 60, 0, 1, 61, 1)
        self.assertIsInstance(got, mcmap.Unread)
        self.assertEqual(got.code, "unreadable")
        self.assertIn("layout", got.why)


class TestTheBodyHoversByTheWork(SightCase):
    """The owner: *"Vesper the ally disappears. It should stay close to what it
    is building if there is a stream of thought over it."* An edit tells the
    plugin where the work is (its job's line, or the player it was beside)."""

    def test_an_edit_sends_where_it_worked(self):
        self.assertIsNotNone(self.sight.focus({"x": 4, "y": 70, "z": -2,
                                                "dimension": "minecraft:overworld",
                                                "key": "j1a2b3c"}))
        sent = [a for a in self.plugin.asked if a[1] == "/v1/focus"][-1][2]
        self.assertEqual((sent["x"], sent["y"], sent["z"], sent["key"]), (4, 70, -2, "j1a2b3c"))

    def test_the_edit_reports_its_focus_and_the_panel_passes_it_on(self):
        companion = (PANEL / "companion.py").read_text()
        self.assertIn("focus=focus)", companion)
        server = (PANEL / "server.py").read_text()
        self.assertIn("_focus_after_edit(act, body)", server)

    def test_the_plugin_keeps_a_body_while_it_works_and_takes_it_away_after(self):
        src = (ADDON / "sight" / "src" / "main" / "java" / "com" / "bruhautomation" / "sight"
               / "Thoughts.java").read_text()
        body = src.split("private Allay spawnBody", 1)[1].split("\n    }\n", 1)[0]
        for call in ("setPersistent(false)", "setAI(false)", "setInvulnerable(true)",
                     "bruh_thought_body"):
            self.assertIn(call, body)
        tick = src.split("private void tick()", 1)[1].split("\n    }\n", 1)[0]
        self.assertIn("removeBody(m);", tick, "no work, no body")
        self.assertIn("p.showEntity(plugin, d);", tick, "shown after it is in the world")


class TestThePluginShips(unittest.TestCase):
    def test_the_image_builds_it_and_run_sh_installs_it_on_paper_only(self):
        docker = (ADDON / "Dockerfile").read_text()
        self.assertIn("AS sight", docker)
        self.assertIn("COPY --from=sight /BruhSight.jar", docker)
        run = (ADDON / "run.sh").read_text()
        self.assertIn("install_sight\n", run.split("main() {", 1)[1])
        body = run.split("install_sight() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("paper|purpur) ;;", body)

    def test_the_plugin_binds_loopback_checks_the_token_and_never_saves_the_bubble(self):
        src = ADDON / "sight" / "src" / "main" / "java" / "com" / "bruhautomation" / "sight"
        main = (src / "BruhSight.java").read_text()
        self.assertIn("InetAddress.getLoopbackAddress()", main)
        self.assertIn("MessageDigest.isEqual", main)
        thoughts = (src / "Thoughts.java").read_text()
        self.assertIn("setPersistent(false)", thoughts)
        self.assertIn("setVisibleByDefault(false)", thoughts)
        self.assertIn("showEntity(plugin", thoughts)
        plugin_yml = (ADDON / "sight" / "src" / "main" / "resources" / "plugin.yml").read_text()
        self.assertIn("main: com.bruhautomation.sight.BruhSight", plugin_yml)


if __name__ == "__main__":
    unittest.main()
