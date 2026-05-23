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
            # The new managed keys must always be rendered — regression guard
            # for the Xbox-login / "enforce-secure-profile" fix.
            self.assertIn("enforce-secure-profile", props)
            self.assertIn("allow-nether", props)
            self.assertIn("spawn-monsters", props)
            self.assertIn("generate-structures", props)
            self.assertIn("prevent-proxy-connections", props)

    def test_enforce_secure_profile_defaults_false_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, ONLINE_MODE="true")
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["online-mode"], "true")
            self.assertEqual(props["enforce-secure-profile"], "false")

    def test_enforce_secure_profile_respects_opt_in_online(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, ONLINE_MODE="true", ENFORCE_SECURE_PROFILE="true")
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["enforce-secure-profile"], "true")

    def test_enforce_secure_profile_forced_false_in_offline_mode(self):
        # Offline mode users have no signed profile — if we leave the
        # toggle on they are kicked on join. The script must auto-force
        # it false regardless of the raw env value.
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, ONLINE_MODE="false", ENFORCE_SECURE_PROFILE="true")
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["online-mode"], "false")
            self.assertEqual(
                props["enforce-secure-profile"], "false",
                "must auto-force enforce-secure-profile=false when online-mode=false",
            )

    def test_allow_cheats_forces_command_block_and_op_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(
                tmp, ALLOW_CHEATS="true",
                ENABLE_COMMAND_BLOCK="false", OP_PERMISSION_LEVEL="1",
            )
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["enable-command-block"], "true")
            self.assertEqual(props["op-permission-level"], "2")

    def test_allow_cheats_off_respects_raw_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(
                tmp, ALLOW_CHEATS="false",
                ENABLE_COMMAND_BLOCK="false", OP_PERMISSION_LEVEL="4",
            )
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["enable-command-block"], "false")
            self.assertEqual(props["op-permission-level"], "4")

    def test_initial_enabled_packs_defaults_to_vanilla(self):
        # With no override the base game pack must still be enabled — an empty
        # initial-enabled-packs disables vanilla and the server won't generate.
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["initial-enabled-packs"], "vanilla")
            self.assertEqual(props["initial-disabled-packs"], "")

    def test_initial_enabled_packs_enables_experiments(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(
                tmp,
                INITIAL_ENABLED_PACKS="vanilla,minecart_improvements,redstone_experiments",
                INITIAL_DISABLED_PACKS="trade_rebalance",
            )
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(
                props["initial-enabled-packs"],
                "vanilla,minecart_improvements,redstone_experiments",
            )
            self.assertEqual(props["initial-disabled-packs"], "trade_rebalance")

    def test_connection_throttle_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, CONNECTION_THROTTLE_MS="0")
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["connection-throttle"], "0")

    def test_player_idle_timeout_passthrough(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp, PLAYER_IDLE_TIMEOUT_MINUTES="5")
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["player-idle-timeout"], "5")

    def test_resource_pack_keys_pass_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(
                tmp,
                RESOURCE_PACK="https://cdn.example/pack.zip",
                RESOURCE_PACK_SHA1="deadbeef",
                REQUIRE_RESOURCE_PACK="true",
            )
            props = _parse(os.path.join(tmp, "server.properties"))
            self.assertEqual(props["resource-pack"], "https://cdn.example/pack.zip")
            self.assertEqual(props["resource-pack-sha1"], "deadbeef")
            self.assertEqual(props["require-resource-pack"], "true")

    def test_preserves_hand_edited_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            props_path = os.path.join(tmp, "server.properties")
            # Operator hand-edits keys the add-on doesn't know about.
            # (`resource-pack` IS managed now, so pick keys we explicitly
            # don't render — e.g. modded or Paper/Purpur-specific options.)
            with open(props_path, "w") as f:
                f.write("# my custom comment\n")
                f.write("text-filtering-config=https://example.com/filter\n")
                f.write("pause-when-empty-seconds=60\n")
                f.write("motd=OLD\n")  # will be overridden by managed render
            _run(tmp)
            props = _parse(props_path)
            self.assertEqual(
                props["text-filtering-config"], "https://example.com/filter",
                "non-managed key was dropped during re-render",
            )
            self.assertEqual(props["pause-when-empty-seconds"], "60")
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
