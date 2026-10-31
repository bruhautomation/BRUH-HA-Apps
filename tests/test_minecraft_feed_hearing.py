"""#588: a server script that rewrites chat and join lines must not leave
the world deaf.

The house's `core.sk` set the chat format to the nickname ("&b%nick%&f:
[message]"), the join message to "Dad is here" and the display name to
"Dad". The console then logged "[Not Secure] Dad: …, are you here?" and
"System chat: Dad is here", the panel read neither, the feed stayed empty
and nothing said so. Done when: with a nickname chat format, the line still
shows in the feed and reaches Home Assistant as a chat event tied to the
player — and when the log cannot be heard, the panel and the sensors say so.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "bruh-minecraft-server" / "panel"
INTEGRATION = REPO / "bruh-minecraft-server" / "custom_components" / "bruh_minecraft"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mcworld = _load("test_hearing_mcworld", PANEL / "mcworld.py")
worldview = _load("test_hearing_worldview", INTEGRATION / "worldview.py")

DAD = "BenMC13765"
KAZ = ".Kaz8044"


def line(msg: str, thread: str = "Server thread") -> str:
    return f"[09:56:01] [{thread}/INFO]: {msg}"


class TestTheShapesALineCanTake(unittest.TestCase):
    def test_nickname_and_rank_formats_are_chat(self):
        cases = [
            (line("[Not Secure] Dad: Juniper, are you here?"), "Dad", "Juniper, are you here?"),
            (line("<Dad> hi"), "Dad", "hi"),
            (line("[Not Secure] <Dad> hi"), "Dad", "hi"),
            (line("[Admin] ~Dad » build me a bridge", "Async Chat Thread - #0"), "Dad",
             "build me a bridge"),
            (line("Dad: hello", "Async Chat Thread - #2"), "Dad", "hello"),
            ("[09:56:01 INFO]: [Not Secure] Dad: on the console too", "Dad", "on the console too"),
        ]
        for raw, who, said in cases:
            with self.subTest(raw=raw):
                ev = mcworld.parse_log_line(raw)
                self.assertEqual((ev["kind"], ev["player"], ev["said"]), ("chat", who, said))

    def test_a_plugins_line_with_a_colon_is_not_somebody_talking(self):
        for raw in (line("Loading: 12 worlds"), line("Preparing spawn area: 84%"),
                    line("Steve lost connection: Disconnected")):
            self.assertIsNone(mcworld.parse_log_line(raw, {"Steve"}), raw)
        # …unless the name is somebody playing.
        ev = mcworld.parse_log_line(line("Steve: hi"), {"Steve"})
        self.assertEqual(ev["player"], "Steve")

    def test_system_chat(self):
        ev = mcworld.parse_log_line(line("System chat: Kaz joined the game"))
        self.assertEqual((ev["kind"], ev["player"]), ("join", "Kaz"))
        self.assertIsNone(mcworld.parse_log_line(line("System chat: Dad is here")))


class Session:
    def __init__(self, world):
        self.world = world

    def command(self, cmd):
        if cmd == "minecraft:list":
            names = list(self.world)
            return f"There are {len(names)} of a max of 20 players online: " + ", ".join(names)
        if cmd.startswith(("minecraft:time query", "time query")):
            return "The time is 1000"
        if cmd.startswith("minecraft:data get entity "):
            name, path = cmd[len("minecraft:data get entity "):].rsplit(" ", 1)
            pos = self.world.get(name.strip('"'))
            value = {"Pos": f"[{pos[0]}d, {pos[1]}d, {pos[2]}d]",
                     "Dimension": '"minecraft:overworld"', "Health": "20.0f",
                     "foodLevel": "20", "playerGameType": "0"}[path]
            return f"{name} has the following entity data: {value}"
        return "Test failed"

    def close(self):
        pass


class Clock:
    def __init__(self):
        self.t = 1_761_900_000.0

    def __call__(self):
        return self.t


class CollectorCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        server = root / "server"
        (server / "logs").mkdir(parents=True)
        self.log = server / "logs" / "latest.log"
        self.log.write_text(line("Starting minecraft server") + "\n")
        self.clock = Clock()
        self.col = mcworld.WorldCollector(rcon_factory=lambda: None, server_dir=server,
                                          out_path=root / "world.json", clock=self.clock)
        self.players: dict[str, list[float]] = {}
        self.col.session = Session(self.players)
        self.heard: list[dict] = []
        self.col.on_event = self.heard.append
        self.beat(0)            # the panel's first look: nobody on

    def say(self, raw: str) -> None:
        with open(self.log, "a") as f:
            f.write(raw + "\n")

    def beat(self, seconds: float = 6.0) -> None:
        # Every beat here is also a poll, as the collector's own timer makes
        # one every few seconds while somebody is on (and within a minute
        # when nobody is, which is how a join with no log line is found).
        self.clock.t += seconds
        self.col.next_poll = 0.0
        self.col.step()


class TestTheHouseThatRewroteItsChat(CollectorCase):
    def test_a_nickname_line_reaches_the_feed_tied_to_the_player(self):
        # The script's join message is not the vanilla line: `list` sees him.
        self.players[DAD] = [0.5, 64.0, 0.5]
        self.say(line("System chat: Dad is here"))
        self.beat()
        joins = [e for e in self.heard if e["kind"] == "join"]
        self.assertEqual([(e["player"], e.get("via")) for e in joins], [(DAD, "list")])
        self.say(line("[Not Secure] Dad: Juniper, are you here?"))
        self.beat()
        chat = [e for e in self.heard if e["kind"] == "chat"][-1]
        self.assertEqual((chat["player"], chat["shown"], chat["said"]),
                         (DAD, "Dad", "Juniper, are you here?"))
        feed = self.col.snapshot()["feed"]
        self.assertEqual(feed[0]["kind"], "chat")
        self.assertEqual(feed[0]["player"], DAD)

    def test_a_nickname_once_tied_is_kept_when_more_people_are_on(self):
        self.players[DAD] = [0.5, 64.0, 0.5]
        self.beat()
        self.say(line("[Not Secure] Dad: one"))
        self.beat()
        self.players[KAZ] = [4.5, 64.0, 0.5]
        self.beat()
        self.say(line("[Not Secure] Dad: two"))
        self.beat()
        chat = [e for e in self.heard if e["kind"] == "chat"]
        self.assertEqual([c["player"] for c in chat], [DAD, DAD])

    def test_a_name_that_could_be_anybody_stays_unmatched_for_the_companion(self):
        self.players[DAD] = [0.5, 64.0, 0.5]
        self.players[KAZ] = [4.5, 64.0, 0.5]
        self.beat()
        self.say(line("[Not Secure] Pirate Captain: arr"))
        self.beat()
        chat = [e for e in self.heard if e["kind"] == "chat"][-1]
        self.assertIsNone(chat["player"])
        self.assertEqual(chat["shown"], "Pirate Captain")
        self.assertTrue(chat["unmatched"])

    def test_the_vanilla_join_after_list_saw_them_is_not_counted_twice(self):
        self.players[KAZ] = [0.5, 64.0, 0.5]
        self.beat()
        self.say(line(f"{KAZ} joined the game"))
        self.beat()
        self.assertEqual(len([e for e in self.heard if e["kind"] == "join"]), 1)
        self.assertTrue(self.col.listening()["ok"])

    def test_walking_into_a_named_place_is_an_event_and_not_the_feed(self):
        (self.col.data_dir).mkdir(parents=True, exist_ok=True)
        (self.col.data_dir / "places.json").write_text(
            '[{"name": "Village", "x": 300, "z": 0, "radius": 30}]')
        self.players[KAZ] = [0.5, 64.0, 0.5]
        self.beat()
        self.players[KAZ] = [300.5, 64.0, 0.5]
        self.beat()
        places = [e for e in self.heard if e["kind"] == "place"]
        self.assertEqual([(e["player"], e["place"]) for e in places], [(KAZ, "Village")])
        self.assertFalse(any(e["kind"] == "place" for e in self.col.snapshot()["feed"]))


class TestTheFeedSaysWhenItIsDeaf(CollectorCase):
    def test_joins_the_log_never_announced_raise_a_warning(self):
        self.players[DAD] = [0.5, 64.0, 0.5]
        self.say(line("System chat: Dad is here"))
        self.beat()
        self.assertTrue(self.col.listening()["ok"])           # not yet: a grace
        self.beat(mcworld.JOIN_GRACE)
        heard = self.col.listening()
        self.assertFalse(heard["ok"])
        self.assertEqual(heard["code"], "joins_unheard")
        self.assertIn(DAD, heard["why"])
        snap = self.col.snapshot()
        self.assertFalse(snap["listening"]["ok"])
        # Home Assistant's feed sensor carries it for brAIn and automations.
        attrs = worldview.feed_attrs(snap)
        self.assertIs(attrs["listening"], False)
        self.assertIn("join line", attrs["listening_problem"])

    def test_a_log_that_says_nothing_while_people_play(self):
        self.players[KAZ] = [0.5, 64.0, 0.5]
        self.say(line(f"{KAZ} joined the game"))
        self.beat()
        self.assertTrue(self.col.listening()["ok"])
        self.clock.t += mcworld.LOG_SILENT + 1
        self.assertEqual(self.col.listening()["code"], "log_silent")

    def test_nobody_on_is_never_a_warning(self):
        self.beat(mcworld.LOG_SILENT * 3)
        self.assertTrue(self.col.listening()["ok"])


class TestThePanelHeadlineSaysIt(unittest.TestCase):
    def test_the_card_leads_with_a_deaf_feed(self):
        # companion_headline lives in server.py (driven in
        # test_minecraft_companion's panel tests); here, that the page says it.
        src = (PANEL / "server.py").read_text()
        self.assertIn('return {"code": "deaf", "show": True, "warning": True,', src)
        js = (PANEL / "app.js").read_text()
        self.assertIn("function renderListening(world)", js)
        html = (PANEL / "index.html").read_text()
        self.assertIn('id="feed-warning"', html)


if __name__ == "__main__":
    unittest.main()
