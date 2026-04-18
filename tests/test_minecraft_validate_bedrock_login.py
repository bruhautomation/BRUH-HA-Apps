#!/usr/bin/env python3
"""Behaviour tests for the `validate-bedrock-login` patcher.

Until 1.2.2 we chased the "Please log into Xbox to join this server."
kick through `remote.auth-type` and Floodgate presence. The actual gate
turned out to be `advanced.bedrock.validate-bedrock-login` inside
Geyser's `LoginEncryptionUtils.encryptConnectionWithCert()` — it
validates the Bedrock client's signed Xbox Live JWT chain *before* any
auth-type logic runs. 1.2.3 ships `scripts/patch-geyser-config.py` to
flip that key and this file locks its behaviour in.

The script must:

1. Flip an existing `validate-bedrock-login:` line in place, preserving
   indentation + surrounding comments.
2. If `advanced.bedrock:` exists but the key doesn't, insert the key
   underneath it at the correct nested indent.
3. If neither the key nor the parent section exists, append a fresh
   `advanced:` → `bedrock:` → `validate-bedrock-login:` block at EOF.
4. Restore the secure default (true) in online / floodgate modes.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "bruh-minecraft-server" / "scripts" / "patch-geyser-config.py"


def _run(cfg: Path, key: str, value: str, section: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(cfg), key, value, section],
        capture_output=True, text=True, check=False,
    )


def _load(cfg: Path) -> dict:
    return yaml.safe_load(cfg.read_text())


class TestPatchGeyserConfig(unittest.TestCase):
    def test_flips_existing_nested_key_to_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yml"
            cfg.write_text(textwrap.dedent("""
                bedrock:
                  port: 19132
                remote:
                  auth-type: offline
                advanced:
                  bedrock:
                    validate-bedrock-login: true
                    some-other-key: hello
            """).lstrip())
            proc = _run(cfg, "validate-bedrock-login", "false", "advanced.bedrock")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = _load(cfg)
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], False)
            # Other keys survive
            self.assertEqual(data["advanced"]["bedrock"]["some-other-key"], "hello")
            self.assertEqual(data["remote"]["auth-type"], "offline")

    def test_preserves_comments_around_existing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yml"
            cfg.write_text(textwrap.dedent("""
                # top comment
                advanced:
                  bedrock:
                    # Default true — disable only for LAN/offline setups.
                    validate-bedrock-login: true
                    # trailing comment
            """).lstrip())
            proc = _run(cfg, "validate-bedrock-login", "false", "advanced.bedrock")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            text = cfg.read_text()
            self.assertIn("# top comment", text)
            self.assertIn("# Default true — disable only for LAN/offline setups.", text)
            self.assertIn("# trailing comment", text)
            self.assertIn("validate-bedrock-login: false", text)
            self.assertNotIn("validate-bedrock-login: true", text)

    def test_inserts_key_when_missing_under_existing_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yml"
            cfg.write_text(textwrap.dedent("""
                remote:
                  auth-type: offline
                advanced:
                  bedrock:
                    some-other-key: hello
            """).lstrip())
            proc = _run(cfg, "validate-bedrock-login", "false", "advanced.bedrock")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = _load(cfg)
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], False)
            self.assertEqual(data["advanced"]["bedrock"]["some-other-key"], "hello")

    def test_appends_full_section_when_nothing_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yml"
            cfg.write_text("remote:\n  auth-type: offline\n")
            proc = _run(cfg, "validate-bedrock-login", "false", "advanced.bedrock")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = _load(cfg)
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], False)
            self.assertEqual(data["remote"]["auth-type"], "offline")

    def test_idempotent_when_already_at_target_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yml"
            cfg.write_text("advanced:\n  bedrock:\n    validate-bedrock-login: false\n")
            before = cfg.read_text()
            proc = _run(cfg, "validate-bedrock-login", "false", "advanced.bedrock")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(cfg.read_text(), before, "no-op edit must not rewrite the file")

    def test_restore_to_true_for_online_mode(self):
        """Online / floodgate modes should RESTORE the secure default."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yml"
            cfg.write_text("advanced:\n  bedrock:\n    validate-bedrock-login: false\n")
            proc = _run(cfg, "validate-bedrock-login", "true", "advanced.bedrock")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = _load(cfg)
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], True)

    def test_realistic_geyser_config_round_trip(self):
        """Full-ish Geyser config to catch whitespace/comment edge cases."""
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.yml"
            cfg.write_text(textwrap.dedent("""
                bedrock:
                  address: 0.0.0.0
                  port: 19132
                  motd1: "Geyser"
                  motd2: "Another Geyser server."
                  server-name: "Geyser"
                remote:
                  address: auto
                  port: 25565
                  auth-type: offline
                  allow-password-authentication: true
                saved-user-logins: []
                advanced:
                  max-players: 100
                  bedrock:
                    validate-bedrock-login: true
                    enable-proxy-protocol: false
                # tail
            """).lstrip())
            proc = _run(cfg, "validate-bedrock-login", "false", "advanced.bedrock")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = _load(cfg)
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], False)
            self.assertEqual(data["remote"]["auth-type"], "offline")
            self.assertEqual(data["advanced"]["max-players"], 100)
            self.assertIs(data["advanced"]["bedrock"]["enable-proxy-protocol"], False)


class TestInstallerIntegration(unittest.TestCase):
    """End-to-end: run the real install-bedrock-support.sh with stubbed
    install_jar and verify that after a fresh / existing-config run the
    Geyser config ends up with validate-bedrock-login set to the right
    value for each auth-type."""

    def _run_installer(
        self,
        server_dir: Path,
        *,
        geyser_auth_type: str,
        online_mode: str,
    ) -> subprocess.CompletedProcess:
        import re
        installer = BASE_DIR / "bruh-minecraft-server" / "scripts" / "install-bedrock-support.sh"
        source = installer.read_text()
        # Stub install_jar so we don't curl anything.
        stub_body = (
            "install_jar() {\n"
            "    local filename=\"$3\"\n"
            "    : > \"${DEST_DIR}/${filename}\"\n"
            "}\n"
        )
        patched = re.sub(
            r"^install_jar\(\)\s*\{.*?^\}\s*$",
            stub_body,
            source,
            count=1,
            flags=re.DOTALL | re.MULTILINE,
        )
        env = {
            **os.environ,
            "MC_SERVER_DIR": str(server_dir),
            "SERVER_TYPE": "paper",
            "MOTD": "test",
            "ONLINE_MODE": online_mode,
            "GEYSER_AUTH_TYPE": geyser_auth_type,
            # Point the installer at the real scripts dir so it finds
            # patch-geyser-config.py even when launched via `bash -c`.
            "BRUH_MC_SCRIPTS_DIR": str(SCRIPT.parent),
        }
        return subprocess.run(
            ["bash", "-c", patched],
            env=env, capture_output=True, text=True, check=False,
        )

    def test_offline_fresh_install_writes_validate_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            (server_dir / "plugins").mkdir()
            proc = self._run_installer(
                server_dir, geyser_auth_type="offline", online_mode="false",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = server_dir / "plugins" / "Geyser-Spigot" / "config.yml"
            data = yaml.safe_load(cfg.read_text())
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], False)
            self.assertEqual(data["remote"]["auth-type"], "offline")

    def test_floodgate_fresh_install_keeps_validate_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            (server_dir / "plugins").mkdir()
            proc = self._run_installer(
                server_dir, geyser_auth_type="floodgate", online_mode="true",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = server_dir / "plugins" / "Geyser-Spigot" / "config.yml"
            data = yaml.safe_load(cfg.read_text())
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], True)
            self.assertEqual(data["remote"]["auth-type"], "floodgate")

    def test_offline_patches_existing_real_sized_config(self):
        """The real-world case: an already-rendered 13KB Geyser config from
        an earlier boot. The patcher must flip the key in place."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            cfg.write_text(textwrap.dedent("""
                bedrock:
                  address: 0.0.0.0
                  port: 19132
                  motd1: "Geyser"
                  motd2: "Another Geyser server."
                remote:
                  address: auto
                  port: 25565
                  auth-type: offline
                saved-user-logins: []
                advanced:
                  bedrock:
                    validate-bedrock-login: true
            """).lstrip())
            proc = self._run_installer(
                server_dir, geyser_auth_type="offline", online_mode="false",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = yaml.safe_load(cfg.read_text())
            self.assertIs(
                data["advanced"]["bedrock"]["validate-bedrock-login"], False,
                "this is the exact failure users hit in 1.2.2: the patcher "
                "must flip validate-bedrock-login: true -> false",
            )

    def test_switching_back_to_floodgate_restores_validate_true(self):
        """Regression guard: if a user flips geyser_auth_type offline -> floodgate,
        we must restore the secure default instead of leaving the bypass enabled."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            cfg.write_text(textwrap.dedent("""
                remote:
                  auth-type: offline
                advanced:
                  bedrock:
                    validate-bedrock-login: false
            """).lstrip())
            proc = self._run_installer(
                server_dir, geyser_auth_type="floodgate", online_mode="true",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = yaml.safe_load(cfg.read_text())
            self.assertIs(data["advanced"]["bedrock"]["validate-bedrock-login"], True)


if __name__ == "__main__":
    unittest.main()
