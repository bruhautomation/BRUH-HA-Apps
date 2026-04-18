#!/usr/bin/env python3
"""Behavioral test for setup-server-properties.sh.

Runs the actual script against a tempdir and verifies:
* All managed keys are rendered from environment variables
* Pre-existing, hand-edited, non-managed keys are preserved across reruns
* File is created with 600 permissions
* The rendered file is deterministic (sorted keys, same input → same output)
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
SCRIPT = os.path.join(
    BASE_DIR, "bruh-minecraft-server", "scripts", "setup-server-properties.sh",
)


def _run(server_dir: str, **overrides: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "MC_SERVER_DIR": server_dir,
        "MOTD": "Test MOTD",
        "DIFFICULTY": "hard",
        "GAMEMODE": "creative",
        "MAX_PLAYERS": "42",
        "VIEW_DISTANCE": "16",
        "SIM_DISTANCE": "12",
        "ONLINE_MODE": "true",
        "PVP": "false",
        "HARDCORE": "false",
        "ALLOW_FLIGHT": "true",
        "WHITE_LIST": "true",
        "SPAWN_PROTECTION": "0",
        "LEVEL_NAME": "mycity",
        "LEVEL_SEED": "12345",
        "LEVEL_TYPE": "minecraft:flat",
        "ENABLE_COMMAND_BLOCK": "true",
        "OP_PERMISSION_LEVEL": "2",
        "RCON_PASSWORD": "testpw",
    }
    env.update(overrides)
    return subprocess.run(
        ["bash", SCRIPT], env=env, capture_output=True, text=True, check=True,
    )


def _parse(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            result[key] = value
    return result


class TestSetupServerProperties(unittest.TestCase):
    def test_renders_all_managed_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["motd"], "Test MOTD")
            self.assertEqual(props["difficulty"], "hard")
            self.assertEqual(props["gamemode"], "creative")
            self.assertEqual(props["max-players"], "42")
            self.assertEqual(props["view-distance"], "16")
            self.assertEqual(props["simulation-distance"], "12")
            self.assertEqual(props["white-list"], "true")
            self.assertEqual(props["level-name"], "mycity")
            self.assertEqual(props["level-seed"], "12345")
            self.assertEqual(props["enable-rcon"], "true")
            self.assertEqual(props["rcon.port"], "25575")
            self.assertEqual(props["rcon.password"], "testpw")
            self.assertEqual(props["server-port"], "25565")

    def test_preserves_hand_edited_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            props_path = os.path.join(tmp, "server.properties")
            # Operator hand-edits a key the UI doesn't know about
            with open(props_path, "w") as f:
                f.write("# my custom comment\n")
                f.write("resource-pack=https://example.com/pack.zip\n")
                f.write("resource-pack-sha1=deadbeef\n")
                f.write("motd=OLD\n")  # will be overridden by managed render
            _run(tmp)
            props = _parse(props_path)
            self.assertEqual(
                props["resource-pack"], "https://example.com/pack.zip",
                "non-managed key was dropped during re-render",
            )
            self.assertEqual(props["resource-pack-sha1"], "deadbeef")
            self.assertEqual(props["motd"], "Test MOTD", "managed key should win")

    def test_file_permissions_are_600(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            path = os.path.join(tmp, "server.properties")
            mode = stat.S_IMODE(os.stat(path).st_mode)
            # 0o600 = user rw only; world/group can't read RCON password
            self.assertEqual(mode, 0o600, f"expected 0o600, got {oct(mode)}")

    def test_deterministic_output(self):
        # Running twice with the same env should produce the same key-set.
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            first = _parse(os.path.join(tmp, "server.properties"))
            _run(tmp)
            second = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(first, second)

    def test_second_run_does_not_duplicate_keys(self):
        # Catches the most common bug: repeated renders appending instead of replacing.
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            _run(tmp, MOTD="Second run")
            path = os.path.join(tmp, "server.properties")
            # Count how many times each key appears — must be exactly once
            counts: dict[str, int] = {}
            with open(path) as f:
                for line in f:
                    if not line or line.startswith("#"):
                        continue
                    k = line.partition("=")[0]
                    counts[k] = counts.get(k, 0) + 1
            for k, n in counts.items():
                self.assertEqual(n, 1, f"key '{k}' appears {n} times after rerender")


if __name__ == "__main__":
    unittest.main()
