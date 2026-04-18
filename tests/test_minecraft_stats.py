#!/usr/bin/env python3
"""Unit test stats-collector.py's RCON output parsers.

The `list` and `tps` reply formats are stable and well-documented, but RCON
replies include Minecraft §-color codes. Regression-proof the regexes against
real-world example replies.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_SCRIPTS = os.path.join(BASE_DIR, "bruh-minecraft-server", "scripts")


def _load_stats_module():
    # The module imports mcrcon + mcstatus at import-time. Provide dummy
    # placeholders so the tests can import the parse helpers in isolation.
    for name in ("mcrcon", "mcstatus"):
        if name not in sys.modules:
            mod = type(sys)(name)
            setattr(mod, "MCRcon", object)
            setattr(mod, "JavaServer", object)
            sys.modules[name] = mod
    spec = importlib.util.spec_from_file_location(
        "stats_collector", os.path.join(ADDON_SCRIPTS, "stats-collector.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


stats = _load_stats_module()


class TestParseList(unittest.TestCase):
    def test_empty_server(self):
        reply = "There are 0 of a max of 20 players online: "
        self.assertEqual(
            stats._parse_list(reply),
            {"online": 0, "max": 20, "players": []},
        )

    def test_empty_server_alt_punctuation(self):
        # Some server versions omit the colon when the list is empty
        reply = "There are 0 of a max of 20 players online"
        self.assertEqual(
            stats._parse_list(reply),
            {"online": 0, "max": 20, "players": []},
        )

    def test_vanilla_1_21_reply(self):
        reply = "There are 3 of a max of 20 players online: BruhBob, Alice, Charlie"
        out = stats._parse_list(reply)
        self.assertEqual(out["online"], 3)
        self.assertEqual(out["max"], 20)
        self.assertEqual(out["players"], ["BruhBob", "Alice", "Charlie"])

    def test_paper_reply_with_color_codes(self):
        # Paper's reply for `/list` sprinkles §-codes for colors
        reply = "§7There are §f2§7 of a max of §f20§7 players online: §fBruhBob, Alice"
        out = stats._parse_list(reply)
        self.assertEqual(out["online"], 2)
        self.assertEqual(out["max"], 20)
        self.assertEqual(out["players"], ["BruhBob", "Alice"])

    def test_paper_newer_format(self):
        reply = "There are 1 of a max 20 players online: Steve"
        out = stats._parse_list(reply)
        self.assertEqual(out["online"], 1)
        self.assertEqual(out["max"], 20)
        self.assertEqual(out["players"], ["Steve"])

    def test_malformed_returns_zero(self):
        self.assertEqual(
            stats._parse_list("some unrelated text"),
            {"online": 0, "max": 0, "players": []},
        )


class TestParseTps(unittest.TestCase):
    def test_paper_reply(self):
        reply = "TPS from last 1m, 5m, 15m: §a20.00, §a19.91, §a20.00"
        self.assertEqual(stats._parse_tps(reply), [20.0, 19.91, 20.0])

    def test_purpur_reply_no_color(self):
        reply = "TPS from last 1m, 5m, 15m: 18.10, 17.55, 20.00"
        self.assertEqual(stats._parse_tps(reply), [18.1, 17.55, 20.0])

    def test_missing_tps_returns_none(self):
        self.assertIsNone(stats._parse_tps("unknown command"))


if __name__ == "__main__":
    unittest.main()
