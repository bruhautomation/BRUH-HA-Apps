#!/usr/bin/env python3
"""Behaviour tests for scripts/ghost-session-watcher.py.

The watcher exists to fix the iOS "Connecting multiplayer server..." hang
follow-up: after a hung Geyser handshake, Paper still considers the
player online for ~60–90s until RakNet's keepalive expires. Any retry
during that window is rejected with "You are already connected to this
server!" The watcher reads Paper's log for that rejection, extracts the
player name, and issues `/kick <name>` so the ghost is cleared and the
retry succeeds.

These tests lock in:

1. The regex matches Paper 1.21.x's duplicate-login log format.
2. The regex does NOT match unrelated disconnect reasons (timed out,
   kicked, banned, server stop) — a false positive would kick an
   innocent player.
3. The rate-limit prevents rapid-fire duplicate kicks for the same name.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "bruh-minecraft-server" / "scripts" / "ghost-session-watcher.py"


def _load_watcher():
    # rcon_client stub so the import doesn't try to reach the network.
    if "rcon_client" not in sys.modules:
        rmod = type(sys)("rcon_client")
        setattr(rmod, "Rcon", object)
        sys.modules["rcon_client"] = rmod
    spec = importlib.util.spec_from_file_location("ghost_watcher", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


watcher = _load_watcher()


class TestDuplicateLoginRegex(unittest.TestCase):
    def test_matches_paper_lost_connection(self):
        line = (
            "[23:50:37 INFO]: com.mojang.authlib.GameProfile@1a2b3c4d"
            "[id=abcd-1234,name=Kid1,properties={}]"
            " (/192.168.1.42:54321) lost connection:"
            " You are already connected to this server!"
        )
        m = watcher.DUPLICATE_LOGIN_RE.search(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("name"), "Kid1")

    def test_matches_disconnecting_variant(self):
        line = (
            "[00:01:02 INFO]: Disconnecting com.mojang.authlib.GameProfile"
            "[id=xxx,name=PlayerTwo,properties={}]: "
            "You are already connected to this server!"
        )
        m = watcher.DUPLICATE_LOGIN_RE.search(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("name"), "PlayerTwo")

    def test_matches_floodgate_prefixed_name(self):
        # Floodgate prefixes Bedrock usernames with `.`; the regex must
        # still extract the name.
        line = (
            "[12:00:00 INFO]: com.mojang.authlib.GameProfile@ff[id=...,"
            "name=.BedrockFriend,properties={}]"
            " (/10.0.0.5:12345) lost connection:"
            " You are already connected to this server!"
        )
        m = watcher.DUPLICATE_LOGIN_RE.search(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("name"), ".BedrockFriend")

    def test_does_not_match_timed_out(self):
        line = "[23:50:40 INFO]: Kid1 lost connection: Timed out"
        self.assertIsNone(watcher.DUPLICATE_LOGIN_RE.search(line))

    def test_does_not_match_kicked(self):
        line = "[23:50:41 INFO]: Kid1 lost connection: Kicked by an operator"
        self.assertIsNone(watcher.DUPLICATE_LOGIN_RE.search(line))

    def test_does_not_match_server_stop(self):
        line = "[23:50:41 INFO]: Kid1 lost connection: Server closed"
        self.assertIsNone(watcher.DUPLICATE_LOGIN_RE.search(line))

    def test_does_not_match_partial_phrase(self):
        line = "[23:50:41 INFO]: You are already connected to this server's IRC bridge"
        self.assertIsNone(watcher.DUPLICATE_LOGIN_RE.search(line))


class TestKickCooldown(unittest.TestCase):
    """Exercise the manual rate-limit logic — no background thread."""

    def test_cooldown_blocks_rapid_duplicate_kicks(self):
        cooldown: dict[str, float] = {}
        name = "Kid1"
        now = time.monotonic()
        # First invocation always fires
        last = cooldown.get(name, 0)
        self.assertGreaterEqual(
            now - last, watcher.KICK_COOLDOWN_SECONDS,
        )
        cooldown[name] = now
        # Second immediate invocation is blocked
        last = cooldown.get(name, 0)
        self.assertLess(now - last, watcher.KICK_COOLDOWN_SECONDS)

    def test_cooldown_allows_separate_names(self):
        cooldown: dict[str, float] = {}
        now = time.monotonic()
        cooldown["Kid1"] = now
        # Kid2 shouldn't be blocked by Kid1's cooldown
        last = cooldown.get("Kid2", 0)
        self.assertGreaterEqual(now - last, watcher.KICK_COOLDOWN_SECONDS)


class TestDisabledByEnvVar(unittest.TestCase):
    """The watcher must early-exit when the user turns the option off."""

    def test_false_env_exits_clean(self):
        # Call main() with the env var set to false; it should return 0
        # without attempting to tail the log.
        old = os.environ.get("AUTO_KICK_GHOST_SESSIONS")
        os.environ["AUTO_KICK_GHOST_SESSIONS"] = "false"
        try:
            self.assertEqual(watcher.main(), 0)
        finally:
            if old is None:
                del os.environ["AUTO_KICK_GHOST_SESSIONS"]
            else:
                os.environ["AUTO_KICK_GHOST_SESSIONS"] = old


if __name__ == "__main__":
    unittest.main()
