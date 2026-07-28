#!/usr/bin/env python3
"""Tests for scripts/cleanup-plugins.py — the duplicate-plugin quarantiner.

Builds real .jar files (just zip archives with a paper-plugin.yml or
plugin.yml inside) in a temp directory, then runs the script as a
subprocess against that directory and asserts which jars ended up in
.quarantine/ and which stayed in plugins/.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import zipfile
from pathlib import Path

ADDON_DIR = Path(__file__).parent.parent / "bruh-minecraft-server"
SCRIPT = ADDON_DIR / "scripts" / "cleanup-plugins.py"


def _make_jar(path: Path, name: str, version: str, *, descriptor: str = "plugin.yml",
              api_version: str | None = "1.21") -> None:
    """Create a fake plugin jar containing just the required descriptor."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        name: {name}
        version: {version}
        main: com.example.{name}
    """)
    if api_version is not None:
        content += f"api-version: '{api_version}'\n"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(descriptor, content)


def _run_cleanup(plugins_dir: Path,
                 server_version: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PLUGINS_DIR": str(plugins_dir)}
    if server_version is not None:
        meta = plugins_dir.parent / ".server-meta.json"
        meta.write_text(
            '{"server_type": "paper", "version": "%s", "build": "1"}'
            % server_version
        )
        env["SERVER_META"] = str(meta)
    else:
        # Point at a nonexistent file so a real /config on the test host
        # can never leak into the run.
        env["SERVER_META"] = str(plugins_dir.parent / "no-such-meta.json")
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestNoDuplicates(unittest.TestCase):
    def test_unique_plugins_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "EssentialsX-2.21.2.jar", "Essentials", "2.21.2")
            _make_jar(plugins / "LuckPerms-Bukkit-5.5.17.jar", "LuckPerms", "5.5.17")
            _make_jar(plugins / "ViaVersion.jar", "ViaVersion", "5.9.2")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("No duplicate plugin jars found", proc.stderr)

            # Nothing moved
            kept = sorted(p.name for p in plugins.iterdir() if p.is_file())
            self.assertEqual(kept, [
                "EssentialsX-2.21.2.jar",
                "LuckPerms-Bukkit-5.5.17.jar",
                "ViaVersion.jar",
            ])
            self.assertFalse((plugins / ".quarantine").exists())


class TestPreReleaseLosesToStable(unittest.TestCase):
    def test_pre_release_filename_quarantined(self):
        """The exact case the user hit: -pre vs stable, both same version."""
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "multiverse-core-5.6.2-pre.jar",
                      "Multiverse-Core", "5.6.2-pre")
            _make_jar(plugins / "multiverse-core-5.6.2.jar",
                      "Multiverse-Core", "5.6.2")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("multiverse-core-5.6.2.jar", proc.stderr)  # kept
            self.assertIn("multiverse-core-5.6.2-pre.jar", proc.stderr)  # quarantined
            # 1.9.0: the final summary names which plugins had dups so the
            # boot log makes it obvious what got cleaned up.
            self.assertRegex(
                proc.stderr,
                r"Quarantined \d+ duplicate jar\(s\) for: .*[Mm]ultiverse-[Cc]ore",
            )

            # The stable jar stays
            self.assertTrue((plugins / "multiverse-core-5.6.2.jar").is_file())
            # The pre-release jar moves
            self.assertFalse((plugins / "multiverse-core-5.6.2-pre.jar").is_file())
            self.assertTrue(
                (plugins / ".quarantine" / "multiverse-core-5.6.2-pre.jar").is_file()
            )

    def test_snapshot_loses_to_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "ViaVersion-5.9.2-SNAPSHOT.jar",
                      "ViaVersion", "5.9.2-SNAPSHOT")
            _make_jar(plugins / "ViaVersion-5.9.2.jar",
                      "ViaVersion", "5.9.2")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((plugins / "ViaVersion-5.9.2.jar").is_file())
            self.assertFalse((plugins / "ViaVersion-5.9.2-SNAPSHOT.jar").is_file())


class TestHigherSemverWins(unittest.TestCase):
    def test_higher_patch_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "EssentialsX-2.20.1.jar", "Essentials", "2.20.1")
            _make_jar(plugins / "EssentialsX-2.21.2.jar", "Essentials", "2.21.2")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((plugins / "EssentialsX-2.21.2.jar").is_file())
            self.assertFalse((plugins / "EssentialsX-2.20.1.jar").is_file())

    def test_two_digit_minor_compared_numerically(self):
        # Regression for the same string-vs-numeric semver bug we hit on
        # the Paper API: lexicographic ordering says "1.21.10" < "1.21.9"
        # which would (wrongly) keep the older jar.
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "Plugin-1.21.9.jar", "Plugin", "1.21.9")
            _make_jar(plugins / "Plugin-1.21.10.jar", "Plugin", "1.21.10")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((plugins / "Plugin-1.21.10.jar").is_file())
            self.assertFalse((plugins / "Plugin-1.21.9.jar").is_file())


class TestPaperPluginYmlSupported(unittest.TestCase):
    """Modern plugins use paper-plugin.yml instead of plugin.yml."""
    def test_paper_plugin_yml_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "modern-1.0.jar", "Modern", "1.0",
                      descriptor="paper-plugin.yml")
            _make_jar(plugins / "modern-2.0.jar", "Modern", "2.0",
                      descriptor="paper-plugin.yml")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((plugins / "modern-2.0.jar").is_file())
            self.assertFalse((plugins / "modern-1.0.jar").is_file())


class TestNonPluginJarsIgnored(unittest.TestCase):
    def test_jar_without_plugin_descriptor_left_alone(self):
        """A library jar in plugins/ (e.g. shaded dependency) shouldn't be touched."""
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            # Empty zip — no plugin.yml at all
            with zipfile.ZipFile(plugins / "kotlin-stdlib.jar", "w") as zf:
                zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
            # And a corrupt jar
            (plugins / "broken.jar").write_bytes(b"not a zip")

            _make_jar(plugins / "real.jar", "RealPlugin", "1.0")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            # All three files still there
            self.assertTrue((plugins / "kotlin-stdlib.jar").is_file())
            self.assertTrue((plugins / "broken.jar").is_file())
            self.assertTrue((plugins / "real.jar").is_file())


class TestQuarantineManifest(unittest.TestCase):
    def test_manifest_records_each_quarantine(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "old.jar", "Plugin", "1.0")
            _make_jar(plugins / "new.jar", "Plugin", "2.0")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)

            manifest = plugins / ".quarantine" / "QUARANTINE.md"
            self.assertTrue(manifest.is_file())
            text = manifest.read_text()
            self.assertIn("Plugin", text)
            self.assertIn("old.jar", text)
            self.assertIn("kept `new.jar`", text)


class TestEmptyAndMissingPluginsDir(unittest.TestCase):
    def test_missing_dir_is_a_noop(self):
        # The plugins folder might not exist on first boot — exit cleanly.
        with tempfile.TemporaryDirectory() as tmp:
            non_existent = Path(tmp) / "does-not-exist"
            proc = _run_cleanup(non_existent)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("doesn't exist yet", proc.stderr)

    def test_empty_dir_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run_cleanup(Path(tmp))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("No duplicate plugin jars found", proc.stderr)


class TestThreeWayDuplicate(unittest.TestCase):
    """A real-world failure mode: install ran during pre-release, then
    again during RC, then again post-stable. All three jars stick around."""
    def test_three_jars_kept_winner_quarantines_other_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            _make_jar(plugins / "Plugin-2.0.0-pre1.jar", "Plugin", "2.0.0-pre1")
            _make_jar(plugins / "Plugin-2.0.0-rc1.jar", "Plugin", "2.0.0-rc1")
            _make_jar(plugins / "Plugin-2.0.0.jar", "Plugin", "2.0.0")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((plugins / "Plugin-2.0.0.jar").is_file())
            self.assertFalse((plugins / "Plugin-2.0.0-pre1.jar").is_file())
            self.assertFalse((plugins / "Plugin-2.0.0-rc1.jar").is_file())
            quarantined = sorted(
                p.name for p in (plugins / ".quarantine").iterdir()
                if p.suffix == ".jar"
            )
            self.assertEqual(quarantined, [
                "Plugin-2.0.0-pre1.jar",
                "Plugin-2.0.0-rc1.jar",
            ])


class TestMtimeTiebreaker(unittest.TestCase):
    """Same plugin name, same version, two filenames — newer mtime wins."""
    def test_newer_mtime_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp)
            old = plugins / "old-name.jar"
            new = plugins / "new-name.jar"
            _make_jar(old, "SamePlugin", "1.0.0")
            time.sleep(0.05)
            _make_jar(new, "SamePlugin", "1.0.0")
            # Make sure mtime difference is real
            os.utime(old, (time.time() - 3600, time.time() - 3600))

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(new.is_file())
            self.assertFalse(old.is_file())


class TestApiVersionQuarantine(unittest.TestCase):
    """Jars whose api-version targets a newer MC than the server runs can
    never load (Paper: "Unsupported API version") — quarantine them with a
    manifest note instead of letting Paper stack-trace on every boot."""

    def test_newer_api_version_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            bad = plugins / "worldedit-bukkit-7.4.4-beta-01.jar"
            _make_jar(bad, "WorldEdit", "7.4.4-beta-01", api_version="1.21.4")

            proc = _run_cleanup(plugins, server_version="1.20.1")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(bad.is_file())
            self.assertTrue((plugins / ".quarantine" / bad.name).is_file())
            self.assertIn("api-version 1.21.4", proc.stderr)
            manifest = (plugins / ".quarantine" / "QUARANTINE.md").read_text()
            self.assertIn("targets Minecraft 1.21.4", manifest)
            self.assertIn("server runs 1.20.1", manifest)

    def test_old_api_version_left_alone(self):
        # EssentialsX declares api-version 1.8 — loads fine on any modern
        # server (just logs a warning); must NOT be quarantined.
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            jar = plugins / "EssentialsX-2.22.0.jar"
            _make_jar(jar, "Essentials", "2.22.0", api_version="1.8")

            proc = _run_cleanup(plugins, server_version="1.20.1")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(jar.is_file())

    def test_equal_and_two_part_api_versions_ok(self):
        # api-version "1.20" on a 1.20.1 server is compatible (Paper pads).
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            jar = plugins / "Plugin.jar"
            _make_jar(jar, "SomePlugin", "1.0.0", api_version="1.20")

            proc = _run_cleanup(plugins, server_version="1.20.1")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(jar.is_file())

    def test_no_server_meta_skips_compat_pass(self):
        # Without .server-meta.json we can't judge compatibility — leave
        # everything alone rather than guessing.
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            jar = plugins / "Future.jar"
            _make_jar(jar, "Future", "1.0.0", api_version="1.99")

            proc = _run_cleanup(plugins)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(jar.is_file())

    def test_missing_api_version_left_alone(self):
        # Legacy Bukkit plugins declare no api-version; they load.
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            jar = plugins / "Legacy.jar"
            _make_jar(jar, "Legacy", "1.0.0", api_version=None)

            proc = _run_cleanup(plugins, server_version="1.20.1")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(jar.is_file())

    def test_incompatible_dup_does_not_beat_compatible_copy(self):
        # The incompatible jar has HIGHER semver — without the compat pass
        # running first, duplicate grouping would keep it and quarantine
        # the working copy. Assert the compatible jar survives.
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            good = plugins / "worldedit-bukkit-7.3.1.jar"
            bad = plugins / "worldedit-bukkit-7.4.4.jar"
            _make_jar(good, "WorldEdit", "7.3.1", api_version="1.20")
            _make_jar(bad, "WorldEdit", "7.4.4", api_version="1.21.4")

            proc = _run_cleanup(plugins, server_version="1.20.1")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(good.is_file())
            self.assertFalse(bad.is_file())


if __name__ == "__main__":
    unittest.main()
