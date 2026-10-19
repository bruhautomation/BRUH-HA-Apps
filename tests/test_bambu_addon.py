#!/usr/bin/env python3
"""BRUH Bambu Studio's wiring: what the store, the build and the Supervisor read."""
import json
import re
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON = BASE_DIR / "bruh-bambu-studio"


def config():
    return yaml.safe_load((ADDON / "config.yaml").read_text())


class TestManifest(unittest.TestCase):
    def test_it_is_experimental_and_so_are_its_siblings(self):
        for addon in ("bruh-bambu-studio", "bruh-minecraft-server", "bright", "morph"):
            with self.subTest(addon=addon):
                self.assertEqual(
                    yaml.safe_load((BASE_DIR / addon / "config.yaml").read_text())["stage"],
                    "experimental")

    def test_amd64_only_because_bambu_studio_is(self):
        """Bambu Lab ships Bambu Studio for Linux on x86-64 alone; an aarch64
        entry would install on a Pi and then have no slicer to download."""
        self.assertEqual(config()["arch"], ["amd64"])
        build = yaml.safe_load((ADDON / "build.yaml").read_text())
        self.assertEqual(list(build["build_from"]), ["amd64"])

    def test_the_image_follows_the_folder(self):
        self.assertEqual(config()["image"], "ghcr.io/bruhautomation/{arch}-bruh-bambu-studio")

    def test_versions_agree(self):
        version = config()["version"]
        manifest = json.loads((ADDON / "custom_components" / "bruh_bambu" / "manifest.json").read_text())
        self.assertEqual(manifest["version"], version)
        self.assertIn(f"## {version}", (ADDON / "CHANGELOG.md").read_text())

    def test_access_codes_and_the_slicer_stay_out_of_backups(self):
        excluded = config()["backup_exclude"]
        self.assertIn("secrets/**", excluded)
        self.assertIn("bambu-studio/**", excluded)

    def test_nothing_is_published_and_the_screen_is_loopback_only(self):
        self.assertFalse(config().get("ports"))
        self.assertFalse(config().get("host_network"))
        run_sh = (ADDON / "run.sh").read_text()
        self.assertIn("x11vnc -display :1 -localhost", run_sh)
        self.assertIn("-nolisten tcp", run_sh)
        self.assertIn("-nopw", run_sh)  # behind ingress only; see the comment above it


class TestBuild(unittest.TestCase):
    def test_the_build_matrix_builds_amd64_only(self):
        workflow = (BASE_DIR / ".github" / "workflows" / "build.yml").read_text()
        self.assertIn('- "bruh-bambu-studio/**"', workflow)
        self.assertRegex(workflow, r"addon: \[[^\]]*bruh-bambu-studio")
        self.assertRegex(workflow, r"- addon: bruh-bambu-studio\n\s+arch: aarch64")

    def test_the_dockerfile_is_debian_and_installs_what_the_panel_imports(self):
        dockerfile = (ADDON / "Dockerfile").read_text()
        self.assertIn("amd64-base-debian:bookworm", dockerfile)
        for package in ("xvfb", "x11vnc", "openbox", "novnc", "python3-aiohttp",
                        "python3-paho-mqtt", "libwebkit2gtk-4.0-37", "libgl1-mesa-dri"):
            with self.subTest(package=package):
                self.assertIn(package, dockerfile)

    def test_the_cad_stack_and_the_viewer_ship_in_the_image(self):
        dockerfile = (ADDON / "Dockerfile").read_text()
        self.assertIn("python3 -m venv /opt/cad", dockerfile)
        self.assertRegex(dockerfile, r"cadquery==\d")
        self.assertIn("three@${THREE_VERSION}", dockerfile)
        self.assertIn("COPY cad/ /opt/bruh-bambu/cad/", dockerfile)
        self.assertIn("COPY lovelace/ /opt/bruh-bambu/lovelace/", dockerfile)

    def test_the_card_goes_to_lovelace_and_to_morph(self):
        run_sh = (ADDON / "run.sh").read_text()
        self.assertIn("/config/www/bruh_bambu/bruh-bambu-card.js", run_sh)
        self.assertIn("/config/morph/cards/bruh-bambu-printer.js", run_sh)
        card = (ADDON / "lovelace" / "bruh-bambu-card.js").read_text()
        for name in ("bruh-bambu-card", "morph-bambu-printer"):
            self.assertIn(f"customElements.define('{name}'", card)
        self.assertNotRegex(card, r"^\s*import ", "a card may import nothing")

    def test_the_appimage_is_extracted_never_mounted(self):
        """FUSE would need `mount`, which the AppArmor profile denies."""
        self.assertIn("--appimage-extract", (ADDON / "panel" / "installer.py").read_text())
        self.assertIn("deny mount", (ADDON / "apparmor.txt").read_text())

    def test_every_panel_url_is_relative(self):
        """Ingress mounts the panel under a prefix; an absolute URL is a
        request to Home Assistant's own root."""
        page = (ADDON / "panel" / "index.html").read_text()
        self.assertEqual(re.findall(r'(?:src|href)="/', page), [])
        for name in ("app.js", "design.js"):
            script = (ADDON / "panel" / name).read_text()
            self.assertEqual(re.findall(r'api\(["`]/', script), [], name)
            self.assertEqual(re.findall(r'fetch\(["`]/', script), [], name)


class TestServicesDocumented(unittest.TestCase):
    def test_every_registered_service_is_described(self):
        services = yaml.safe_load((ADDON / "custom_components" / "bruh_bambu" / "services.yaml").read_text())
        strings = json.loads((ADDON / "custom_components" / "bruh_bambu" / "strings.json").read_text())
        translations = json.loads((ADDON / "custom_components" / "bruh_bambu" / "translations" / "en.json").read_text())
        source = (ADDON / "custom_components" / "bruh_bambu" / "const.py").read_text()
        names = set(re.findall(r'^SERVICE_\w+ = "(\w+)"', source, re.M))
        self.assertEqual(names, set(services))
        self.assertEqual(names, set(strings["services"]))
        self.assertEqual(strings, translations)
        bridge = (ADDON / "integrations" / "ha-bridge.py").read_text()
        for name in names:
            with self.subTest(service=name):
                self.assertIn(f'"{name}":', bridge)


if __name__ == "__main__":
    unittest.main()
