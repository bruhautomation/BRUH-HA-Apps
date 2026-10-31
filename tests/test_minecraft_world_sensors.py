#!/usr/bin/env python3
"""The world in Home Assistant: bruh_minecraft's world sensors and services.

`worldview.py` turns the add-on's world.json into sensor states and
attributes; these hold what each says, that the attributes stay small
(the recorder warns past 16 KB), that a stopped add-on's files read as a
server that is down, and that the world/build services reach the panel
through the bridge.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PKG_DIR = REPO / "bruh-minecraft-server" / "custom_components" / "bruh_minecraft"
BRIDGE_PY = REPO / "bruh-minecraft-server" / "integrations" / "ha-bridge.py"


def _plain(name: str, filename: str):
    """A module of the integration that imports nothing from Home Assistant."""
    spec = importlib.util.spec_from_file_location(name, PKG_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


worldview = _plain("bruh_mc_worldview_test", "worldview.py")

NOW = 1_761_900_000


def world(**over):
    base = {
        "updated_at": NOW, "reachable": True, "online": 2,
        "time": {"daytime": 13000, "day": 41, "hour": 19, "clock": "19:00", "phase": "sunset"},
        "weather": {"state": "rain", "source": "server", "as_of": NOW},
        "players": [
            {"name": "Alex", "dimension": "minecraft:overworld", "x": 100, "y": 64, "z": -20,
             "near": "Watchtower", "gamemode": "survival", "health": 18.5, "food": 17},
            {"name": ".KidPlays", "dimension": "minecraft:the_nether", "x": -8, "y": 70, "z": 4,
             "near": None, "gamemode": "creative", "health": 20.0, "food": 20},
        ],
        "feed": [{"t": NOW - i, "kind": "chat", "player": "Alex", "text": f"Alex: {i}"}
                 for i in range(50)],
        "last_seen": {f"P{i}": NOW - i for i in range(20)},
        "last_save": NOW - 60, "last_backup": NOW - 3600,
        "builds": {"current": {"id": "20261031-abcdef", "title": "Watchtower", "part": "curiosity",
                               "status": "building", "progress": 40, "started_at": NOW - 600},
                   "recent": [{"id": f"20261030-00000{i}", "title": f"Wall {i}", "status": "done",
                               "progress": 100, "finished_at": NOW - i, "image": "/local/minecraft/x.png"}
                              for i in range(9)],
                   "queued": 2},
    }
    base.update(over)
    return base


class TestWhatEachSensorSays(unittest.TestCase):
    def test_time_day_and_weather(self):
        w = world()
        self.assertEqual(worldview.time_state(w), "sunset")
        self.assertEqual(worldview.time_attrs(w), {"hour": 19, "clock": "19:00", "day": 41})
        self.assertEqual(worldview.day_state(w), 41)
        self.assertEqual(worldview.weather_state(w), "rain")
        self.assertEqual(worldview.weather_attrs(w)["source"], "the server")

    def test_players_say_where(self):
        details = worldview.players_attrs(world())["details"]
        self.assertEqual(details[0]["where"], "Overworld · near Watchtower")
        self.assertEqual(details[1]["where"], "Nether · -8, 70, 4")
        self.assertEqual(details[1]["name"], ".KidPlays")
        self.assertEqual(details[1]["gamemode"], "creative")

    def test_the_feed_and_vesper(self):
        w = world()
        self.assertEqual(worldview.feed_state(w), "Alex: 0")
        self.assertEqual(worldview.building_state(w), "Watchtower")
        attrs = worldview.building_attrs(w)
        self.assertEqual((attrs["progress"], attrs["part"], attrs["queued"]), (40, "curiosity", 2))
        self.assertEqual(worldview.building_state(world(builds={"current": None})), "idle")
        self.assertEqual(worldview.last_save(w).timestamp(), NOW - 60)
        self.assertIsNone(worldview.last_backup(world(last_backup=None)))

    def test_attributes_stay_small(self):
        big = world(players=[{"name": f"Player{i}", "x": i, "y": 64, "z": i,
                              "dimension": "minecraft:overworld", "near": "N" * 500}
                             for i in range(80)],
                    feed=[{"t": NOW, "kind": "chat", "player": "A", "text": "x" * 5000}] * 200,
                    last_seen={f"P{i}" * 30: NOW for i in range(500)})
        big["builds"]["recent"] = [{"title": "T" * 5000, "notes": "n" * 9000}] * 50
        for fn in (worldview.players_attrs, worldview.feed_attrs, worldview.building_attrs,
                   worldview.time_attrs, worldview.weather_attrs):
            size = len(json.dumps(fn(big), default=str))
            self.assertLess(size, 12_000, f"{fn.__name__} is {size} bytes")
        self.assertLessEqual(len(worldview.feed_state(big)), 255)
        self.assertEqual(len(worldview.feed_attrs(big)["events"]), worldview.MAX_EVENTS)
        self.assertEqual(len(worldview.players_attrs(big)["details"]), worldview.MAX_PLAYERS)
        self.assertEqual(len(worldview.building_attrs(big)["recent"]), worldview.MAX_RECENT_JOBS)

    def test_an_empty_world_is_quiet(self):
        empty = {}
        self.assertIsNone(worldview.time_state(empty))
        self.assertEqual(worldview.time_attrs(empty), {})
        self.assertIsNone(worldview.feed_state(empty))
        self.assertEqual(worldview.building_state(empty), "idle")


class TestTheCatalog(unittest.TestCase):
    def test_the_world_sensors_are_declared_and_named(self):
        text = (PKG_DIR / "sensor.py").read_text()
        strings = json.loads((PKG_DIR / "strings.json").read_text())["entity"]["sensor"]
        for key in ("world_time", "world_day", "world_weather", "world_feed",
                    "last_save", "last_backup", "vesper_building"):
            self.assertIn(f'key="{key}"', text)
            self.assertIn(key, strings)
        # No sensor of the world says TPS or latency; those stay the server's.
        self.assertIn("_unrecorded_attributes", text)


# ---------------------------------------------------------------------------
# Staleness, through the real coordinator module
# ---------------------------------------------------------------------------
def _load_coordinator():
    mods = {}
    for name in ("homeassistant", "homeassistant.core", "homeassistant.helpers",
                 "homeassistant.helpers.update_coordinator"):
        mods[name] = types.ModuleType(name)
    mods["homeassistant.core"].HomeAssistant = object

    class _Coord:
        def __init__(self, *a, **kw):
            pass

        def __class_getitem__(cls, item):
            return cls

    mods["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = _Coord
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    pkg = "bruh_mc_world_coord_test"
    try:
        parent = types.ModuleType(pkg)
        parent.__path__ = [str(PKG_DIR)]
        sys.modules[pkg] = parent
        out = {}
        for sub in ("const", "coordinator"):
            spec = importlib.util.spec_from_file_location(f"{pkg}.{sub}", PKG_DIR / f"{sub}.py")
            m = importlib.util.module_from_spec(spec)
            m.__package__ = pkg
            sys.modules[f"{pkg}.{sub}"] = m
            spec.loader.exec_module(m)
            out[sub] = m
        return out["coordinator"]
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class TestAStoppedAddOnReadsAsDown(unittest.TestCase):
    def setUp(self):
        self.coord = _load_coordinator()

    def test_old_files_say_nobody_is_on(self):
        data = {"stats": {"updated_at": NOW - 600, "reachable": True, "online": 3,
                          "players": ["A", "B", "C"]},
                "world": world(updated_at=NOW - 600)}
        out = self.coord.stale(data, NOW)
        self.assertFalse(out["stats"]["reachable"])
        self.assertEqual(out["stats"]["online"], 0)
        self.assertEqual(out["world"]["players"], [])
        self.assertFalse(out["world"]["reachable"])
        # The feed and Vesper's log are history and stay.
        self.assertEqual(len(out["world"]["feed"]), 50)

    def test_fresh_files_and_old_add_ons_are_left_alone(self):
        data = {"stats": {"updated_at": NOW - 10, "reachable": True, "online": 3}}
        self.assertTrue(self.coord.stale(data, NOW)["stats"]["reachable"])
        data = {"stats": {"reachable": True, "online": 3}}      # no updated_at
        self.assertEqual(self.coord.stale(data, NOW)["stats"]["online"], 3)


# ---------------------------------------------------------------------------
# The services, through the bridge, to the panel
# ---------------------------------------------------------------------------
class TestTheServices(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_minecraft_services import Call, FakeServices, load_integration
        self.Call = Call
        self.mod = load_integration()
        self.sent = []
        self.answer = {"ok": True, "job": {"id": "20261031-abcdef", "title": "Tower"}}

        async def fake_send(kind, payload, timeout=15.0):
            self.sent.append((kind, payload))
            return self.answer

        self.mod.send_request = fake_send
        hass = types.SimpleNamespace(services=FakeServices())
        self.mod._register_services(hass)
        self.handlers = hass.services.handlers

    def call(self, name, **data):
        handler, response = self.handlers[name]
        return asyncio.run(handler(self.Call(data))), response

    def test_world_and_builds_are_asked_and_answered(self):
        out, response = self.call("get_world")
        self.assertEqual(response, "only")
        self.assertEqual(self.sent[-1], ("world", {}))
        self.assertNotIn("ok", out)
        self.call("list_builds", status="done")
        self.assertEqual(self.sent[-1], ("builds_list", {"status": "done"}))
        out, _ = self.call("save_build", title="Tower", status="building")
        self.assertEqual(out["job"]["title"], "Tower")
        self.assertEqual(self.sent[-1][0], "build_save")
        self.call("delete_build", id="20261031-abcdef")
        self.assertEqual(self.sent[-1], ("build_delete", {"id": "20261031-abcdef"}))

    def test_a_new_job_without_a_title_is_refused_before_anything_is_sent(self):
        before = len(self.sent)
        with self.assertRaises(Exception):
            self.call("save_build", status="building")
        self.assertEqual(len(self.sent), before)


class TestTheBridgeCarriesItToThePanel(unittest.TestCase):
    def setUp(self):
        rcon = types.ModuleType("rcon_client")
        rcon.Rcon = object
        self._saved = sys.modules.get("rcon_client")
        sys.modules["rcon_client"] = rcon
        spec = importlib.util.spec_from_file_location("bruh_mc_bridge_world", BRIDGE_PY)
        self.bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bridge)
        self.calls = []
        self.bridge._panel = lambda method, path, body=None, timeout=150: (
            self.calls.append((method, path, body)) or {"ok": True})

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop("rcon_client", None)
        else:
            sys.modules["rcon_client"] = self._saved

    def run_(self, kind, payload):
        return asyncio.run(self.bridge.handle({"kind": kind, "payload": payload}))

    def test_routes(self):
        self.run_("world", {})
        self.run_("builds_list", {"status": "done", "limit": 5})
        self.run_("build_save", {"title": "Tower", "junk": 1})
        self.run_("build_save", {"id": "20261031-abcdef", "progress": 50})
        self.run_("build_delete", {"id": "20261031-abcdef"})
        self.assertEqual(self.calls, [
            ("GET", "/api/world", None),
            ("GET", "/api/builds?status=done&limit=5", None),
            ("POST", "/api/builds", {"title": "Tower"}),
            ("PATCH", "/api/builds/20261031-abcdef", {"progress": 50}),
            ("DELETE", "/api/builds/20261031-abcdef", None),
        ])

    def test_a_bad_id_never_reaches_a_path(self):
        out = self.run_("build_delete", {"id": "../../api/stop"})
        self.assertFalse(out["ok"])
        self.assertEqual(self.calls, [])

    def test_world_json_is_mirrored(self):
        self.assertIn("world.json", self.bridge.MIRROR_FILES)


class TestTheWorldCard(unittest.TestCase):
    """The Morph card is words about the world and nothing to press."""

    CARD = PKG_DIR / "frontend" / "bruh-minecraft-world.js"

    def test_the_card_ships_and_reaches_morph(self):
        card = self.CARD.read_text()
        self.assertIn("customElements.define('morph-minecraft-world'", card)
        self.assertNotRegex(card, r"(?m)^\s*import ", "a card may import nothing")
        run_sh = (REPO / "bruh-minecraft-server" / "run.sh").read_text()
        self.assertIn("/config/morph/cards/bruh-minecraft-world.js", run_sh)
        self.assertIn("install_world_card", run_sh.split("main() {", 1)[-1])
        self.assertIn("chown minecraft:minecraft /config/www/minecraft", run_sh)

    def test_no_tps_latency_buttons_or_hover_text(self):
        code = self.CARD.read_text().split("*/", 1)[1]    # past the header comment
        self.assertNotRegex(code, r"(?i)\btps\b|latency")
        self.assertNotIn("<button", code)
        self.assertNotIn("title=", code)
        self.assertNotIn("position: fixed", code)
        self.assertNotIn("callService", code)


if __name__ == "__main__":
    unittest.main()
