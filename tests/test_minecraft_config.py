#!/usr/bin/env python3
"""Static validation of bruh-minecraft-server configuration files.

Covers:
* config.yaml — required keys, schema / options consistency, port sanity
* build.yaml — multi-arch base images, label correctness
* Dockerfile — no s6-overlay bypass, Java 21 installed, non-root user created
* manifest.json, strings.json, translations/en.json — shape and cross-refs
* services.yaml ↔ __init__.py service registration parity
* icon.png / logo.png — valid PNG with sane dimensions
"""
from __future__ import annotations

import json
import os
import re
import struct
import unittest

import yaml

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "bruh-minecraft-server")
INTEG_DIR = os.path.join(ADDON_DIR, "custom_components", "bruh_minecraft")


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------
class TestConfigYaml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "config.yaml")) as f:
            cls.cfg = yaml.safe_load(f)

    def test_required_keys(self):
        for k in ("name", "version", "slug", "arch", "startup", "init"):
            self.assertIn(k, self.cfg, f"config.yaml missing '{k}'")

    def test_slug(self):
        self.assertEqual(self.cfg["slug"], "bruh_minecraft_server")
        self.assertRegex(self.cfg["slug"], r"^[a-z][a-z0-9_]*$")

    def test_version_is_semver(self):
        self.assertRegex(self.cfg["version"], r"^\d+\.\d+\.\d+$")

    def test_supported_architectures(self):
        archs = set(self.cfg["arch"])
        self.assertTrue({"amd64", "aarch64"}.issubset(archs))

    def test_ingress_settings(self):
        self.assertTrue(self.cfg["ingress"])
        self.assertEqual(self.cfg["ingress_port"], 8099)
        self.assertTrue(self.cfg["panel_admin"])

    def test_startup_is_services(self):
        # Long-running add-on
        self.assertEqual(self.cfg["startup"], "services")

    def test_minecraft_port_exposed(self):
        ports = self.cfg["ports"]
        self.assertIn("25565/tcp", ports)
        self.assertEqual(ports["25565/tcp"], 25565)

    def test_ingress_port_not_in_ports(self):
        # 8099 should only be reachable via HA's ingress proxy, not exposed to the host
        self.assertNotIn("8099/tcp", self.cfg.get("ports", {}))

    def test_eula_default_is_false(self):
        # Safety: must not implicitly accept the Minecraft EULA for the user
        self.assertFalse(self.cfg["options"]["eula"])

    def test_options_match_schema(self):
        opts = set(self.cfg["options"].keys())
        schema = set(self.cfg["schema"].keys())
        # Every default option must have a schema entry.
        missing = opts - schema
        self.assertFalse(missing, f"options without schema: {missing}")
        # Every required schema key must have a default (so the form can render).
        extras = {k for k in (schema - opts)}
        self.assertFalse(extras, f"schema keys without defaults: {extras}")

    def test_server_type_enum(self):
        rule = self.cfg["schema"]["server_type"]
        # Must include the six server types the downloader supports
        for typ in ("paper", "purpur", "vanilla", "fabric", "forge", "folia"):
            self.assertIn(typ, rule)

    def test_memory_bounds(self):
        rule = self.cfg["schema"]["memory_mb"]
        self.assertEqual(rule, "int(512,65536)")
        self.assertGreaterEqual(self.cfg["options"]["memory_mb"], 512)

    def test_minecraft_version_regex_accepts_presets(self):
        rule = self.cfg["schema"]["minecraft_version"]
        self.assertTrue(rule.startswith("match("))
        pattern = rule[len("match(") : -1]
        rx = re.compile(pattern)
        for ok in ("LATEST", "SNAPSHOT", "1.21.3", "1.20", "1.21.5-pre1"):
            self.assertTrue(rx.fullmatch(ok), f"version '{ok}' should match")
        for bad in ("badversion", "1..2", "1.2.3.4.5"):
            self.assertFalse(rx.fullmatch(bad), f"version '{bad}' should not match")

    def test_discovery_registered(self):
        self.assertIn("bruh_minecraft", self.cfg.get("discovery", []))

    def test_volume_maps_minimum(self):
        maps = set(self.cfg["map"])
        # /config must be RW so we can persist worlds and custom_components
        self.assertIn("config:rw", maps)


# ---------------------------------------------------------------------------
# build.yaml
# ---------------------------------------------------------------------------
class TestBuildYaml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "build.yaml")) as f:
            cls.cfg = yaml.safe_load(f)

    def test_base_images(self):
        self.assertIn("ghcr.io/home-assistant/amd64-base:3.19", self.cfg["build_from"]["amd64"])
        self.assertIn("ghcr.io/home-assistant/aarch64-base:3.19", self.cfg["build_from"]["aarch64"])

    def test_labels(self):
        labels = self.cfg["labels"]
        self.assertIn("BRUH Minecraft", labels["org.opencontainers.image.title"])
        self.assertEqual(labels["org.opencontainers.image.licenses"], "MIT")


# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------
class TestDockerfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = _read(os.path.join(ADDON_DIR, "Dockerfile"))

    def test_from_build_arg(self):
        self.assertRegex(self.text, r"^\s*ARG BUILD_FROM", msg="Missing ARG BUILD_FROM")
        self.assertRegex(self.text, r"FROM \$\{?BUILD_FROM\}?")

    def test_no_entrypoint_override(self):
        """Overriding ENTRYPOINT bypasses s6-overlay and breaks bashio.

        This is the bug that caused the initial startup error
        'unable to envdir /run/s6/container_environment'.
        """
        # Look for uncommented ENTRYPOINT directive
        for line in self.text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertFalse(
                stripped.startswith("ENTRYPOINT"),
                msg=f"Dockerfile must not set ENTRYPOINT (would bypass s6-overlay): {stripped!r}",
            )

    def test_cmd_runs_run_sh(self):
        self.assertIn('CMD ["/run.sh"]', self.text)

    def test_java_21(self):
        self.assertIn("openjdk21-jre-headless", self.text)

    def test_non_root_user(self):
        # A dedicated non-root user must exist; the JVM should never run as root
        self.assertRegex(self.text, r"adduser -D .*-u 1000.*minecraft")

    def test_python_libs_for_panel_and_rcon(self):
        for lib in ("mcrcon", "mcstatus", "aiofiles"):
            self.assertIn(lib, self.text, f"pip package {lib} not installed")

    def test_runtime_paths_env(self):
        for var in ("MC_SERVER_DIR", "MC_BACKUP_DIR", "MC_PANEL_STATE"):
            self.assertIn(var, self.text)


# ---------------------------------------------------------------------------
# Custom integration — manifest.json
# ---------------------------------------------------------------------------
class TestManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(INTEG_DIR, "manifest.json")) as f:
            cls.manifest = json.load(f)

    def test_required_keys(self):
        for k in ("domain", "name", "version", "config_flow", "documentation", "iot_class"):
            self.assertIn(k, self.manifest, f"manifest missing {k}")

    def test_domain_matches_package_dir(self):
        self.assertEqual(self.manifest["domain"], "bruh_minecraft")

    def test_iot_class(self):
        self.assertEqual(self.manifest["iot_class"], "local_polling")

    def test_config_flow(self):
        self.assertTrue(self.manifest["config_flow"])

    def test_discovery_registered(self):
        self.assertIn("bruh_minecraft", self.manifest.get("discovery", []))


# ---------------------------------------------------------------------------
# strings.json, translations
# ---------------------------------------------------------------------------
class TestStringsAndTranslations(unittest.TestCase):
    def test_strings_json_is_valid(self):
        with open(os.path.join(INTEG_DIR, "strings.json")) as f:
            data = json.load(f)
        self.assertIn("config", data)
        self.assertIn("user", data["config"]["step"])
        self.assertIn("confirm", data["config"]["step"])

    def test_translations_en_json_is_valid(self):
        with open(os.path.join(INTEG_DIR, "translations/en.json")) as f:
            data = json.load(f)
        self.assertIn("config", data)

    def test_all_services_documented_in_strings(self):
        # Every service registered in __init__.py should have a strings entry
        with open(os.path.join(INTEG_DIR, "strings.json")) as f:
            strings = json.load(f)
        documented = set(strings.get("services", {}).keys())
        from_services_yaml = yaml.safe_load(_read(os.path.join(INTEG_DIR, "services.yaml")))
        services = set(from_services_yaml.keys())
        missing_strings = services - documented
        self.assertFalse(missing_strings, f"services without strings: {missing_strings}")


# ---------------------------------------------------------------------------
# services.yaml vs __init__.py registration
# ---------------------------------------------------------------------------
class TestServiceRegistration(unittest.TestCase):
    def test_every_registered_service_is_in_services_yaml(self):
        from_services_yaml = set(
            yaml.safe_load(_read(os.path.join(INTEG_DIR, "services.yaml"))).keys()
        )
        init_src = _read(os.path.join(INTEG_DIR, "__init__.py"))
        registered = set(re.findall(r"SERVICE_[A-Z_]+", init_src))
        # Map SERVICE_FOO constants -> literal in const.py
        const_src = _read(os.path.join(INTEG_DIR, "const.py"))
        literal_by_name: dict[str, str] = {}
        for name in registered:
            m = re.search(rf'{name}\s*=\s*"([^"]+)"', const_src)
            if m:
                literal_by_name[name] = m.group(1)
        for name, lit in literal_by_name.items():
            self.assertIn(lit, from_services_yaml, f"{name} ({lit}) not documented in services.yaml")


# ---------------------------------------------------------------------------
# Icon / logo PNG validation
# ---------------------------------------------------------------------------
class TestIcons(unittest.TestCase):
    @staticmethod
    def _png_dims(path: str) -> tuple[int, int]:
        with open(path, "rb") as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                raise AssertionError(f"{path} is not a PNG")
            f.read(4)  # length
            if f.read(4) != b"IHDR":
                raise AssertionError(f"{path} missing IHDR")
            w, h = struct.unpack(">II", f.read(8))
            return w, h

    def test_icon_png_valid(self):
        w, h = self._png_dims(os.path.join(ADDON_DIR, "icon.png"))
        self.assertGreaterEqual(w, 128)
        self.assertEqual(w, h, "icon.png should be square")

    def test_logo_png_valid(self):
        w, h = self._png_dims(os.path.join(ADDON_DIR, "logo.png"))
        self.assertGreaterEqual(w, 512)
        self.assertGreater(w, h, "logo.png should be wider than tall")


# ---------------------------------------------------------------------------
# Repository listing
# ---------------------------------------------------------------------------
class TestRepositoryListing(unittest.TestCase):
    def test_addon_referenced_in_top_readme(self):
        readme = _read(os.path.join(BASE_DIR, "README.md"))
        self.assertIn("BRUH Minecraft Server", readme)
        self.assertIn("bruh-minecraft-server/", readme)


if __name__ == "__main__":
    unittest.main()
