#!/usr/bin/env python3
"""Behavioral test for setup-server-properties.sh (per-world model, 1.8.0+).

Gameplay settings are PER-WORLD now: this script no longer renders them from
add-on options/env. Instead it:
  * always enforces the INFRA keys (rcon/query/ports),
  * SEEDS gameplay defaults only when a key is absent,
  * PRESERVES any existing gameplay value (panel edits / per-world differences),
  * derives enforce-whitelist from white-list,
  * forces enforce-secure-profile=false when online-mode is off.
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


def _run(server_dir: str, **env_extra: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MC_SERVER_DIR": server_dir, "RCON_PASSWORD": "testpw"}
    env.update(env_extra)
    return subprocess.run(
        ["bash", SCRIPT], env=env, capture_output=True, text=True, check=True,
    )


def _seed(server_dir: str, **props: str) -> None:
    """Pre-write a server.properties (simulating an existing world)."""
    path = os.path.join(server_dir, "server.properties")
    with open(path, "w") as f:
        for k, v in props.items():
            f.write(f"{k}={v}\n")


def _parse(server_dir: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with open(os.path.join(server_dir, "server.properties")) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            result[key] = value
    return result


class TestInfraKeys(unittest.TestCase):
    def test_infra_keys_always_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            props = _parse(tmp)
            self.assertEqual(props["server-port"], "25565")
            self.assertEqual(props["enable-rcon"], "true")
            self.assertEqual(props["rcon.port"], "25575")
            self.assertEqual(props["rcon.password"], "testpw")
            self.assertEqual(props["enable-query"], "true")

    def test_infra_keys_override_existing(self):
        # Even if a world file tried to set an infra key, the add-on wins.
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, **{"enable-rcon": "false", "rcon.port": "9999"})
            _run(tmp)
            props = _parse(tmp)
            self.assertEqual(props["enable-rcon"], "true")
            self.assertEqual(props["rcon.port"], "25575")


class TestSeedDefaults(unittest.TestCase):
    def test_seeds_gameplay_defaults_on_fresh_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            props = _parse(tmp)
            self.assertEqual(props["difficulty"], "normal")
            self.assertEqual(props["gamemode"], "survival")
            self.assertEqual(props["force-gamemode"], "true")
            self.assertEqual(props["max-players"], "20")
            self.assertEqual(props["pvp"], "true")
            self.assertEqual(props["level-name"], "world")
            self.assertEqual(props["initial-enabled-packs"], "vanilla")
            self.assertEqual(props["connection-throttle"], "4000")
            self.assertEqual(props["player-idle-timeout"], "0")


class TestPreserveExisting(unittest.TestCase):
    def test_preserves_per_world_gameplay_values(self):
        # The whole point: a creative world stays creative across boots.
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, gamemode="creative", difficulty="hard",
                  **{"max-players": "8", "view-distance": "16"})
            _run(tmp)
            props = _parse(tmp)
            self.assertEqual(props["gamemode"], "creative")
            self.assertEqual(props["difficulty"], "hard")
            self.assertEqual(props["max-players"], "8")
            self.assertEqual(props["view-distance"], "16")

    def test_preserves_empty_string_value(self):
        # An explicit empty value (e.g. resource-pack=) is preserved, not
        # re-seeded with a default (there is no non-empty default anyway).
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, **{"level-seed": "13579"})
            _run(tmp)
            self.assertEqual(_parse(tmp)["level-seed"], "13579")

    def test_preserves_hand_edited_unknown_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, **{"text-filtering-config": "https://example.com/filter",
                          "pause-when-empty-seconds": "60"})
            _run(tmp)
            props = _parse(tmp)
            self.assertEqual(props["text-filtering-config"], "https://example.com/filter")
            self.assertEqual(props["pause-when-empty-seconds"], "60")


class TestDerivedAndSafety(unittest.TestCase):
    def test_enforce_whitelist_mirrors_white_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, **{"white-list": "true"})
            _run(tmp)
            props = _parse(tmp)
            self.assertEqual(props["white-list"], "true")
            self.assertEqual(props["enforce-whitelist"], "true")

    def test_offline_mode_forces_secure_profile_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, **{"online-mode": "false", "enforce-secure-profile": "true"})
            _run(tmp)
            props = _parse(tmp)
            self.assertEqual(props["online-mode"], "false")
            self.assertEqual(props["enforce-secure-profile"], "false")

    def test_online_mode_respects_secure_profile_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, **{"online-mode": "true", "enforce-secure-profile": "true"})
            _run(tmp)
            self.assertEqual(_parse(tmp)["enforce-secure-profile"], "true")

    def test_hardcore_non_survival_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            _seed(tmp, hardcore="true", gamemode="creative")
            proc = _run(tmp)
            self.assertIn("hardcore=true forces survival", proc.stderr)


class TestFileHygiene(unittest.TestCase):
    def test_file_permissions_are_600(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            mode = stat.S_IMODE(os.stat(os.path.join(tmp, "server.properties")).st_mode)
            self.assertEqual(mode, 0o600, f"expected 0o600, got {oct(mode)}")

    def test_deterministic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            first = _parse(tmp)
            _run(tmp)
            self.assertEqual(first, _parse(tmp))

    def test_no_duplicate_keys_on_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            _run(tmp)
            _run(tmp)
            counts: dict[str, int] = {}
            with open(os.path.join(tmp, "server.properties")) as f:
                for line in f:
                    if not line or line.startswith("#"):
                        continue
                    k = line.partition("=")[0]
                    counts[k] = counts.get(k, 0) + 1
            for k, n in counts.items():
                self.assertEqual(n, 1, f"key '{k}' appears {n} times")


if __name__ == "__main__":
    unittest.main()
