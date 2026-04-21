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
    # The module imports rcon_client (our own, co-located) + mcstatus at
    # import-time. Provide dummy placeholders so the tests can import the
    # parse helpers in isolation without opening sockets.
    if "mcstatus" not in sys.modules:
        mod = type(sys)("mcstatus")
        setattr(mod, "JavaServer", object)
        sys.modules["mcstatus"] = mod
    if "rcon_client" not in sys.modules:
        rmod = type(sys)("rcon_client")
        setattr(rmod, "Rcon", object)
        sys.modules["rcon_client"] = rmod
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


class TestMcstatusPlayerSampleFallback(unittest.TestCase):
    """Regression for 1.2.8: Paper can rephrase the `/list` RCON reply
    between minor versions, which makes `_parse_list` return an empty
    player-name array even though players are online. The panel then
    shows a blank player list. mcstatus's status-ping `players.sample`
    carries the names directly and is immune to text-format drift —
    use it as a fallback in write_stats.
    """

    def _capture_write(self, **payload):
        """Run write_stats with the given payload and return the players.json
        body it would have emitted, without touching disk."""
        written = {}

        def fake_atomic_write(path, data):
            written[path.name] = data

        original = stats._atomic_write
        stats._atomic_write = fake_atomic_write
        try:
            stats.write_stats(
                started_at=0.0, reachable=True, last_rcon_ok=True,
                payload=payload,
            )
        finally:
            stats._atomic_write = original
        return written

    def test_uses_rcon_names_when_present(self):
        written = self._capture_write(
            online=2, max=20,
            players=["Alice", "Bob"],
            players_sample=["Alice"],  # stale sample must lose to fresh RCON
        )
        self.assertEqual(written["players.json"]["players"], ["Alice", "Bob"])

    def test_falls_back_to_mcstatus_sample_when_rcon_empty(self):
        written = self._capture_write(
            online=1, max=20,
            players=[],  # regex missed the format
            players_sample=["BRxtreamsnipes"],
        )
        self.assertEqual(written["players.json"]["players"], ["BRxtreamsnipes"])

    def test_both_empty_yields_empty_list(self):
        written = self._capture_write(online=0, max=20, players=[])
        self.assertEqual(written["players.json"]["players"], [])


class TestParseListMissGuard(unittest.TestCase):
    """The RCON probe must not overwrite mcstatus's online/max counts
    with zeros when `/list` parsing misses the format."""

    def test_parse_list_returns_zeros_on_miss(self):
        # `_parse_list` still returns the zeros for backwards compat with
        # callers that rely on the dict shape; the guard lives in _probe_rcon.
        self.assertEqual(
            stats._parse_list("nothing that looks like a list"),
            {"online": 0, "max": 0, "players": []},
        )


if __name__ == "__main__":
    unittest.main()
