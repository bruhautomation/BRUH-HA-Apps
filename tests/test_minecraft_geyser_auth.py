#!/usr/bin/env python3
"""Behaviour test for the auth-type patcher inside install-bedrock-support.sh.

This reproduces three real situations the user can end up in:

1. Fresh install — Geyser-Spigot/config.yml doesn't exist yet.
2. Default Geyser config — auth-type: online (the bug that said
   "Please log into Xbox to join this server.").
3. Already-patched config — auth-type: floodgate (must be idempotent).

The test carves out the patcher function from the real script and runs it
against a tempdir; all other install steps are stubbed out by substituting
no-op definitions for install_jar + the top-level run. This keeps the test
hermetic and network-free.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "bruh-minecraft-server" / "scripts" / "install-bedrock-support.sh"


def _read_props(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        result[key.strip()] = value.strip()
    return result


def _run_patcher(server_dir: Path, motd: str = "A BRUH Minecraft Server") -> subprocess.CompletedProcess:
    """Execute just the `configure_geyser_for_floodgate` function against
    `${server_dir}/plugins/Geyser-Spigot/config.yml`."""
    source = SCRIPT.read_text()
    wrapper = textwrap.dedent(f"""
        set -euo pipefail
        export MC_SERVER_DIR={server_dir.as_posix()!r}
        export PLUGINS_DIR={(server_dir / "plugins").as_posix()!r}
        export MOTD={motd!r}
        log()  {{ printf '[test] %s\\n' "$*" >&2; }}
        warn() {{ printf '[test] %s\\n' "$*" >&2; }}
        # Bring just the function we want to test into scope
    """)
    # Extract the function body from the real script
    start = source.index("configure_geyser_for_floodgate() {")
    # Find the matching closing brace at column 0
    remaining = source[start:]
    brace = 0
    for i, ch in enumerate(remaining):
        if ch == "{": brace += 1
        elif ch == "}":
            brace -= 1
            if brace == 0:
                body = remaining[: i + 1]
                break
    wrapper += body + "\nconfigure_geyser_for_floodgate\n"
    return subprocess.run(
        ["bash", "-c", wrapper], capture_output=True, text=True, check=False,
    )


class TestGeyserAuthPatch(unittest.TestCase):
    def test_fresh_install_stages_floodgate(self):
        """No config.yml yet -> patcher creates one with auth-type: floodgate."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            (server_dir / "plugins").mkdir()
            proc = _run_patcher(server_dir)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = server_dir / "plugins" / "Geyser-Spigot" / "config.yml"
            self.assertTrue(cfg.exists(), "config.yml should have been created")
            props = _read_props(cfg)
            self.assertEqual(props.get("auth-type"), "floodgate")

    def test_default_online_config_is_patched(self):
        """The bug the user hit. Patcher must convert online -> floodgate."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            # A realistic Geyser default config (trimmed)
            cfg.write_text(textwrap.dedent("""
                bedrock:
                  port: 19132
                  motd1: "Geyser"
                  motd2: "Another Geyser server."
                remote:
                  address: auto
                  port: 25565
                  auth-type: online
                  allow-password-authentication: true
                floodgate-key-file: key.pem
            """).lstrip())
            proc = _run_patcher(server_dir)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            text = cfg.read_text()
            # auth-type + motd1/motd2 are all managed; every other key must survive
            self.assertIn("auth-type: floodgate", text)
            self.assertNotIn("auth-type: online", text)
            self.assertIn("port: 19132", text)
            self.assertIn("allow-password-authentication", text)
            self.assertIn("floodgate-key-file: key.pem", text)

    def test_idempotent_on_already_patched_config(self):
        """Running a second time must be a no-op."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            cfg.write_text("remote:\n  auth-type: floodgate\n")
            before = cfg.read_text()
            proc = _run_patcher(server_dir)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            after = cfg.read_text()
            self.assertEqual(before, after, "patch should be idempotent")

    def test_config_without_auth_type_gets_line_appended(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            cfg.write_text("bedrock:\n  port: 19132\n")
            proc = _run_patcher(server_dir)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            text = cfg.read_text()
            self.assertIn("auth-type: floodgate", text)

    def test_indentation_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            cfg.write_text("remote:\n    auth-type: online\n")
            proc = _run_patcher(server_dir)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            # Four-space indent should be preserved
            self.assertIn("    auth-type: floodgate", cfg.read_text())

    def test_fresh_install_uses_addon_motd(self):
        """Fresh staged config should carry the add-on's motd as motd1."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            (server_dir / "plugins").mkdir()
            proc = _run_patcher(server_dir, motd="BRUH House MC")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            text = (server_dir / "plugins" / "Geyser-Spigot" / "config.yml").read_text()
            self.assertIn('motd1: "BRUH House MC"', text)

    def test_existing_config_motd_patched(self):
        """motd1/motd2 on an existing default config get overwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            cfg.write_text(textwrap.dedent("""
                bedrock:
                  port: 19132
                  motd1: "Geyser"
                  motd2: "Another Geyser server."
                remote:
                  auth-type: online
            """).lstrip())
            proc = _run_patcher(server_dir, motd="BRUH MC")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            text = cfg.read_text()
            self.assertIn('motd1: "BRUH MC"', text)
            self.assertNotIn('motd1: "Geyser"', text)
            self.assertNotIn('Another Geyser server', text)


if __name__ == "__main__":
    unittest.main()
