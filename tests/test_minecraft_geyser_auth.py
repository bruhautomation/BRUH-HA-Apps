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
import re
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


def _run_patcher(
    server_dir: Path,
    motd: str = "A BRUH Minecraft Server",
    *,
    geyser_auth_type: str | None = None,
    online_mode: str = "true",
) -> subprocess.CompletedProcess:
    """Execute just the `configure_geyser_for_floodgate` function against
    `${server_dir}/plugins/Geyser-Spigot/config.yml`."""
    source = SCRIPT.read_text()
    env_bits = [
        f"export MC_SERVER_DIR={server_dir.as_posix()!r}",
        f"export PLUGINS_DIR={(server_dir / 'plugins').as_posix()!r}",
        f"export MOTD={motd!r}",
        f"export ONLINE_MODE={online_mode!r}",
    ]
    if geyser_auth_type is not None:
        env_bits.append(f"export GEYSER_AUTH_TYPE={geyser_auth_type!r}")
    wrapper = textwrap.dedent("""
        set -euo pipefail
        {env}
        log()  {{ printf '[test] %s\\n' "$*" >&2; }}
        warn() {{ printf '[test] %s\\n' "$*" >&2; }}
        # Bring the functions we want to test into scope
    """).format(env="\n        ".join(env_bits))
    # Extract the function bodies from the real script. configure_geyser
    # reads $AUTH_TYPE which is normally set by the top-level of the real
    # script, so we export it here too for the test harness.
    bodies: list[str] = []
    for func in ("resolve_auth_type", "configure_geyser"):
        start = source.index(f"{func}() {{")
        remaining = source[start:]
        brace = 0
        for i, ch in enumerate(remaining):
            if ch == "{": brace += 1
            elif ch == "}":
                brace -= 1
                if brace == 0:
                    bodies.append(remaining[: i + 1])
                    break
    wrapper += "\n".join(bodies) + "\nAUTH_TYPE=$(resolve_auth_type); export AUTH_TYPE\nconfigure_geyser\n"
    return subprocess.run(
        ["bash", "-c", wrapper], capture_output=True, text=True, check=False,
    )


def _run_full_script(
    server_dir: Path,
    *,
    geyser_auth_type: str | None = None,
    online_mode: str = "true",
    seed_floodgate_jar: bool = False,
) -> subprocess.CompletedProcess:
    """Run the real install-bedrock-support.sh with a stubbed install_jar
    (so we don't hit the network). This exercises the top-level branches
    that decide whether to install Floodgate, which is the critical path
    for the Xbox-login kick — just patching Geyser's config isn't enough
    if Floodgate is still loaded."""
    (server_dir / "plugins").mkdir(exist_ok=True)
    if seed_floodgate_jar:
        (server_dir / "plugins" / "floodgate-spigot.jar").write_bytes(b"MZfake")
    env = {
        **os.environ,
        "MC_SERVER_DIR": str(server_dir),
        "SERVER_TYPE": "paper",
        "MOTD": "test",
        "ONLINE_MODE": online_mode,
    }
    if geyser_auth_type is not None:
        env["GEYSER_AUTH_TYPE"] = geyser_auth_type
    # Replace the real install_jar with a no-network stub: just `touch` the
    # destination file so downstream assertions can verify the jar "landed".
    # A regex swap against the source keeps the rest of the script intact.
    source = SCRIPT.read_text()
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
    if patched == source:
        raise RuntimeError("failed to stub install_jar in install-bedrock-support.sh")
    proc = subprocess.run(
        ["bash", "-c", patched],
        env=env, capture_output=True, text=True, check=False,
    )
    return proc


class TestFloodgateSkipWhenOffline(unittest.TestCase):
    """Regression guards for the 1.2.2 fix. When auth-type resolves to
    `offline`, Floodgate MUST NOT end up in plugins/ — Geyser defers auth
    to Floodgate whenever the jar is loaded, which re-introduces the
    "Please log into Xbox to join this server." kick even though we set
    auth-type: offline in config.yml."""

    def test_offline_mode_skips_floodgate_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = _run_full_script(
                server_dir, geyser_auth_type="offline", online_mode="false",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            floodgate_jars = list((server_dir / "plugins").glob("floodgate-*.jar"))
            self.assertEqual(
                floodgate_jars, [],
                f"Floodgate must NOT be installed in offline mode; found {floodgate_jars}",
            )
            geyser_jar = server_dir / "plugins" / "Geyser-Spigot.jar"
            self.assertTrue(geyser_jar.exists(), "Geyser must still be installed")

    def test_offline_mode_removes_existing_floodgate_jar(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = _run_full_script(
                server_dir, geyser_auth_type="offline", online_mode="false",
                seed_floodgate_jar=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            floodgate_jars = list((server_dir / "plugins").glob("floodgate-*.jar"))
            self.assertEqual(
                floodgate_jars, [],
                "existing floodgate-spigot.jar should be removed when switching to offline",
            )

    def test_floodgate_mode_still_installs_floodgate(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = _run_full_script(
                server_dir, geyser_auth_type="floodgate", online_mode="true",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            floodgate_jar = server_dir / "plugins" / "floodgate-spigot.jar"
            self.assertTrue(
                floodgate_jar.exists(),
                "Floodgate must be installed when auth-type is floodgate",
            )

    def test_auto_mode_offline_skips_floodgate(self):
        """auto + online_mode=false -> resolves to offline -> skip Floodgate."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = _run_full_script(
                server_dir, geyser_auth_type="auto", online_mode="false",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            floodgate_jars = list((server_dir / "plugins").glob("floodgate-*.jar"))
            self.assertEqual(floodgate_jars, [])

    def test_offline_mode_writes_auth_type_offline_to_config(self):
        """Sanity: we still patch the Geyser config in offline mode even
        though we skip Floodgate — auth-type must be rendered."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            proc = _run_full_script(
                server_dir, geyser_auth_type="offline", online_mode="false",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = server_dir / "plugins" / "Geyser-Spigot" / "config.yml"
            self.assertTrue(cfg.exists(), "Geyser config should still be staged")
            self.assertIn("auth-type: offline", cfg.read_text())


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

    def test_auto_picks_offline_when_online_mode_is_off(self):
        """Java `online_mode: false` + `geyser_auth_type: auto` must resolve
        to `offline` on the Geyser side — otherwise Bedrock clients still
        hit "Please log into Xbox to join this server." even though the
        Java server accepts cracked logins."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            (server_dir / "plugins").mkdir()
            proc = _run_patcher(
                server_dir, geyser_auth_type="auto", online_mode="false",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = server_dir / "plugins" / "Geyser-Spigot" / "config.yml"
            self.assertIn("auth-type: offline", cfg.read_text())

    def test_auto_picks_floodgate_when_online_mode_is_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            (server_dir / "plugins").mkdir()
            proc = _run_patcher(
                server_dir, geyser_auth_type="auto", online_mode="true",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = server_dir / "plugins" / "Geyser-Spigot" / "config.yml"
            self.assertIn("auth-type: floodgate", cfg.read_text())

    def test_explicit_offline_wins_over_online_mode(self):
        """Explicit geyser_auth_type: offline should be honoured even when
        Java is running in online-mode — it's the user's decision."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            (server_dir / "plugins").mkdir()
            proc = _run_patcher(
                server_dir, geyser_auth_type="offline", online_mode="true",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cfg = server_dir / "plugins" / "Geyser-Spigot" / "config.yml"
            self.assertIn("auth-type: offline", cfg.read_text())

    def test_explicit_online_mode_patches_from_floodgate(self):
        """Existing config on floodgate + requested online should flip to online."""
        with tempfile.TemporaryDirectory() as tmp:
            server_dir = Path(tmp)
            plugin_dir = server_dir / "plugins" / "Geyser-Spigot"
            plugin_dir.mkdir(parents=True)
            cfg = plugin_dir / "config.yml"
            cfg.write_text("remote:\n  auth-type: floodgate\n")
            proc = _run_patcher(server_dir, geyser_auth_type="online")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("auth-type: online", cfg.read_text())
            self.assertNotIn("auth-type: floodgate", cfg.read_text())

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
