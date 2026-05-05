"""Behaviour tests for the popular-plugins one-click installer (1.4.0).

Verifies:
  * config.yaml + run.sh + popular-plugins.sh stay in sync (same set of
    curated plugins, same naming).
  * Disabled plugins are skipped without any network calls.
  * Enabled plugins resolve a URL via a stubbed Modrinth API and hand it
    to install-plugin.sh.
  * A plugin whose Modrinth lookup fails doesn't abort the loop or fail
    the add-on boot — it logs a warning and other plugins still install.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
ADDON_DIR = BASE_DIR / "bruh-minecraft-server"
SCRIPT = ADDON_DIR / "scripts" / "popular-plugins.sh"
RUN_SH = ADDON_DIR / "run.sh"
CONFIG = ADDON_DIR / "config.yaml"

# The canonical curated set. If you're adding/removing a plugin, update
# all three: config.yaml options + schema, run.sh export loop, and
# popular-plugins.sh PLUGIN_SLUGS map. This test enforces that.
EXPECTED_PLUGINS = {
    "essentialsx",
    "essentialsx_chat",
    "luckperms",
    "worldedit",
    "worldguard",
    "coreprotect",
    "multiverse_core",
    "griefprevention",
    "mcmmo",
    "chestsort",
    "veinminer",
    "spark",
}


class TestCuratedSetParity(unittest.TestCase):
    """The curated plugin set must match across config.yaml, run.sh, and
    popular-plugins.sh — otherwise a checkbox in the UI does nothing or
    a script tries to install something the schema rejects."""

    @classmethod
    def setUpClass(cls):
        cls.config = CONFIG.read_text()
        cls.run_sh = RUN_SH.read_text()
        cls.script = SCRIPT.read_text()

    def _options_in_config(self):
        return set(re.findall(r"^\s*install_([a-z_]+):\s*false\b", self.config, re.MULTILINE))

    def _schema_in_config(self):
        return set(re.findall(r"^\s*install_([a-z_]+):\s*bool\b", self.config, re.MULTILINE))

    def _exports_in_run_sh(self):
        # Find the for-loop body that builds INSTALL_<NAME> env vars.
        match = re.search(
            r"for popular in (.+?); do",
            self.run_sh, re.DOTALL,
        )
        self.assertIsNotNone(match, "popular plugin export loop missing from run.sh")
        names = match.group(1).split()
        # Strip line continuations and stray backslashes
        return {n.strip() for n in names if n.strip() and n.strip() != "\\"}

    def _slugs_in_script(self):
        return set(re.findall(r"\[([a-z_]+)\]=\"[a-z0-9-]+\"", self.script))

    def test_config_options_match_expected(self):
        self.assertEqual(self._options_in_config(), EXPECTED_PLUGINS)

    def test_config_schema_match_expected(self):
        self.assertEqual(self._schema_in_config(), EXPECTED_PLUGINS)

    def test_run_sh_exports_match_expected(self):
        self.assertEqual(self._exports_in_run_sh(), EXPECTED_PLUGINS)

    def test_script_slugs_match_expected(self):
        self.assertEqual(self._slugs_in_script(), EXPECTED_PLUGINS)

    def test_run_sh_calls_install_popular_plugins(self):
        # In main(), install_popular_plugins must be called between
        # install_plugins and install_bedrock_support.
        match = re.search(
            r"install_plugins\s*\n\s*install_popular_plugins\s*\n\s*install_bedrock_support",
            self.run_sh,
        )
        self.assertIsNotNone(
            match,
            "install_popular_plugins must be called between install_plugins "
            "and install_bedrock_support in main()",
        )


class TestPopularPluginsScript(unittest.TestCase):
    """End-to-end: run popular-plugins.sh with a stub `curl` (Modrinth) and
    a stub `install-plugin.sh` so we can assert which URLs got installed
    without touching the network."""

    def _run_with_stubs(self, env_overrides: dict[str, str], modrinth_responses: dict[str, str]):
        """Run popular-plugins.sh with:
        - INSTALL_<NAME> env vars from `env_overrides` (rest default to false).
        - A fake `curl` on PATH that returns canned JSON for each project URL,
          based on `modrinth_responses` keyed by Modrinth slug.
        - A fake `install-plugin.sh` that just records the URL it received.
        Returns (proc, install_log_path)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Fake install-plugin.sh — just append the URL to a log file.
            install_log = tmp_path / "install-log.txt"
            scripts_dir = tmp_path / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "install-plugin.sh").write_text(
                f'#!/bin/bash\necho "$1" >> "{install_log}"\n'
            )
            (scripts_dir / "install-plugin.sh").chmod(0o755)

            # Fake curl — switch on the URL passed to it. Modrinth lookups
            # use https://api.modrinth.com/v2/project/<slug>/version.
            curl_dir = tmp_path / "bin"
            curl_dir.mkdir()
            curl_script = ['#!/bin/bash', 'url=""', 'for arg in "$@"; do',
                           '  case "$arg" in https://*) url="$arg";; esac',
                           'done']
            for slug, response in modrinth_responses.items():
                # Match the slug in the URL, write the response, exit 0
                escaped = response.replace("'", r"'\''")
                curl_script.append(
                    f'if [[ "$url" == *"/v2/project/{slug}/"* ]]; then '
                    f"printf '%s' '{escaped}'; exit 0; fi"
                )
            # Anything else: pretend the project doesn't exist (HTTP 404).
            curl_script.append('exit 22')  # curl HTTP error exit code
            (curl_dir / "curl").write_text("\n".join(curl_script) + "\n")
            (curl_dir / "curl").chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{curl_dir}:{os.environ.get('PATH', '')}",
                "SCRIPTS_DIR": str(scripts_dir),
                **env_overrides,
            }
            proc = subprocess.run(
                ["bash", str(SCRIPT)],
                env=env, capture_output=True, text=True, check=False,
            )
            installed_urls = (
                install_log.read_text().splitlines()
                if install_log.exists() else []
            )
            return proc, installed_urls

    def test_no_plugins_enabled_no_installs(self):
        proc, urls = self._run_with_stubs(env_overrides={}, modrinth_responses={})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(urls, [], "no INSTALL_* enabled — nothing should install")

    def test_single_plugin_enabled_resolves_and_installs(self):
        # Modrinth response shape: list of versions; each has loaders[] and files[].
        response = (
            '[{"loaders":["paper","spigot"],'
            '"files":[{"url":"https://cdn.modrinth.com/data/EssentialsX-2.20.1.jar"}]}]'
        )
        proc, urls = self._run_with_stubs(
            env_overrides={"INSTALL_ESSENTIALSX": "true"},
            modrinth_responses={"essentialsx": response},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(urls, ["https://cdn.modrinth.com/data/EssentialsX-2.20.1.jar"])

    def test_unsupported_loader_is_skipped(self):
        # Plugin only ships for Forge/Fabric -> no paper-family build available.
        response = (
            '[{"loaders":["forge"],'
            '"files":[{"url":"https://cdn.modrinth.com/data/Forge-only.jar"}]}]'
        )
        proc, urls = self._run_with_stubs(
            env_overrides={"INSTALL_ESSENTIALSX": "true"},
            modrinth_responses={"essentialsx": response},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(urls, [])
        self.assertIn("Could not resolve", proc.stderr)

    def test_one_plugin_failure_does_not_abort_others(self):
        good = (
            '[{"loaders":["paper"],'
            '"files":[{"url":"https://cdn.modrinth.com/data/Spark.jar"}]}]'
        )
        # luckperms intentionally has NO Modrinth response -> 404 from stub curl
        proc, urls = self._run_with_stubs(
            env_overrides={
                "INSTALL_LUCKPERMS": "true",  # will fail to resolve
                "INSTALL_SPARK": "true",      # will succeed
            },
            modrinth_responses={"spark": good},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(urls, ["https://cdn.modrinth.com/data/Spark.jar"])
        self.assertIn("luckperms", proc.stderr)

    def test_disabled_plugins_make_no_network_calls(self):
        # No env overrides at all. Stub curl would be called if any lookup
        # happened. We verify by NOT giving any modrinth_responses; the
        # stub returns 22 for unknown URLs, so any call would be visible.
        proc, urls = self._run_with_stubs(env_overrides={}, modrinth_responses={})
        # Confirm no resolution lines in the log
        self.assertNotIn("Resolving", proc.stderr)
        self.assertEqual(urls, [])


if __name__ == "__main__":
    unittest.main()
