"""A button, a lever or a command block can tell Home Assistant something
(#777): `bruh_minecraft_signal`, with no Skript.

What the house wanted: an in-game button that turns on real lights. What
there was: a command block's `say` (or `execute as <player> run say`)
never fired `bruh_minecraft_chat` — only "<name> text" lines do — so
linking a build to the house needed a hand-written Skript.

So: a command block runs `say bruh:signal <name> [data]`. The server logs
it as "[@] bruh:signal porch_lights on" (`@` is a command block's own
name), the collector reads that line (panel/mcworld.py), and the panel
fires `bruh_minecraft_signal` with {name, data}. Least privilege:

  * only the `@` sender counts — a command block nobody renamed. A player
    typing the same words in chat is "<Steve> [@] bruh:signal …", a
    player's (or the console's) `/say` is "[Steve] …" or "[Server] …", and
    `execute as <player> run say` speaks as the player: none of them fire
    it. So a signal is as trusted as a command block, which only an
    operator can place or change;
  * the event says nothing about who pressed what, and carries no
    authority: a listener decides what a name means;
  * a repeating command block saying the same thing every tick is one
    signal a second, not twenty, and none of it fills the feed or the
    journal.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_companion import HandsBase, mcworld  # noqa: E402

PKG = HERE.parent / "bruh-minecraft-server" / "custom_components" / "bruh_minecraft"
DOCS = HERE.parent / "bruh-minecraft-server" / "DOCS.md"


def line(msg: str) -> str:
    return f"[09:00:01] [Server thread/INFO]: {msg}"


class TestTheLine(unittest.TestCase):
    def test_a_command_blocks_say_is_a_signal(self):
        for msg in ("[@] bruh:signal porch_lights on",
                    "[Not Secure] [@] bruh:signal porch_lights on"):
            ev = mcworld.parse_log_line(line(msg))
            self.assertEqual((ev["kind"], ev["name"], ev["data"]),
                             ("signal", "porch_lights", "on"), msg)
            self.assertIsNone(ev["player"])

    def test_data_is_optional_and_the_name_is_a_plain_word(self):
        ev = mcworld.parse_log_line(line("[@] bruh:signal Doorbell"))
        self.assertEqual((ev["name"], ev["data"]), ("doorbell", ""))
        self.assertIsNone(mcworld.parse_log_line(line("[@] bruh:signal porch-lights! on")))
        self.assertIsNone(mcworld.parse_log_line(line("[@] bruh:signal")))

    def test_nobody_else_can_say_it(self):
        for msg in ("<Steve> [@] bruh:signal porch_lights on",
                    "[Not Secure] <Steve> [@] bruh:signal porch_lights on",
                    "[Steve] bruh:signal porch_lights on",
                    "[Server] bruh:signal porch_lights on",
                    "[Porch Button] bruh:signal porch_lights on",
                    "Steve: [@] bruh:signal porch_lights on",
                    "* Steve [@] bruh:signal porch_lights on",
                    "bruh:signal porch_lights on"):
            ev = mcworld.parse_log_line(line(msg), known={"Steve"})
            self.assertFalse(ev and ev.get("kind") == "signal", msg)


class TestTheCollector(HandsBase):
    def setUp(self):
        super().setUp()
        self.heard: list[dict] = []
        self.col.on_event = self.heard.append

    def signals(self):
        return [e for e in self.heard if e.get("kind") == "signal"]

    def test_it_reaches_the_listener_and_not_the_feed(self):
        self.log_line("[@] bruh:signal porch_lights on")
        self.beat(0)
        self.assertEqual([(e["name"], e["data"]) for e in self.signals()],
                         [("porch_lights", "on")])
        self.assertFalse([e for e in self.col.feed if e.get("kind") == "signal"])

    def test_a_repeating_command_block_is_one_signal_a_second(self):
        for _ in range(20):
            self.log_line("[@] bruh:signal porch_lights on")
        self.beat(0)
        self.assertEqual(len(self.signals()), 1)
        self.log_line("[@] bruh:signal porch_lights off")
        self.beat(0)
        self.assertEqual(len(self.signals()), 2)
        self.beat(1.5)
        self.log_line("[@] bruh:signal porch_lights on")
        self.beat(0)
        self.assertEqual(len(self.signals()), 3)


class TestTheEvent(unittest.TestCase):
    def test_signal_is_a_game_event_with_its_fields(self):
        from test_minecraft_companion import _load_panel
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for d in ("server", "backups", "state", "worlds"):
                (root / d).mkdir(parents=True)
            panel = _load_panel(root)
            self.assertIn("signal", panel.GAME_EVENTS)
            name, data = panel.game_event(
                {"t": 5, "kind": "signal", "player": None, "name": "porch_lights",
                 "data": "on"}, lambda p: (True, ""), "world")
            self.assertEqual(name, "bruh_minecraft_signal")
            self.assertEqual({k: data[k] for k in ("name", "data", "world", "t")},
                             {"name": "porch_lights", "data": "on", "world": "world", "t": 5})
            self.assertNotIn("verified", data)
            self.assertNotIn("player", data)

    def test_the_integration_and_the_docs_name_it(self):
        self.assertRegex((PKG / "const.py").read_text(), r'GAME_EVENTS = \([^)]*"signal"')
        docs = DOCS.read_text()
        self.assertIn("bruh_minecraft_signal", docs)
        self.assertIn("say bruh:signal", docs)
        for strings in (PKG / "strings.json", PKG / "translations" / "en.json"):
            self.assertIn("bruh_minecraft_signal", strings.read_text(), strings)


if __name__ == "__main__":
    unittest.main()
