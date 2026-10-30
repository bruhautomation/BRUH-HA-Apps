"""BRUH Cooking: the add-on's wiring, held from both ends.

The integration is tested against a real Home Assistant by its own suite
(bruh-cooking/tests, run by CI's "BRUH Cooking integration" job) and the
sidebar panel by its vitest suite. What lives here is the part between the
add-on and everything else, where two files have to agree and nothing else
would notice they had stopped: the version written in three places, the
discovery name, the services the integration registers against the ones it
documents, the rename from `breville_cooking`, and the one rule this add-on
adds — it refuses to run without brAIn — driven through the real jq filter.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "bruh-cooking"
INTEGRATION = ADDON / "custom_components" / "bruh_cooking"
JQ = shutil.which("jq")


def config() -> dict:
    return yaml.safe_load((ADDON / "config.yaml").read_text())


def brain_filter() -> str:
    match = re.search(r"^BRAIN_FILTER='(.*)'$", (ADDON / "run.sh").read_text(), re.M)
    assert match, "run.sh has no BRAIN_FILTER"
    return match.group(1)


class TestOneVersion(unittest.TestCase):
    def test_every_place_a_version_is_written_agrees(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual(config()["version"], manifest["version"])

    def test_the_changelog_opens_on_the_shipped_version(self):
        first = re.search(r"^## (\S+)", (ADDON / "CHANGELOG.md").read_text(), re.M)
        self.assertEqual(first.group(1), config()["version"])


class TestTheRename(unittest.TestCase):
    """bruh_cooking, everywhere: a leftover breville_cooking would collide
    with the HACS original, or send the panel to a websocket command
    nothing answers."""

    def test_nothing_still_says_breville_cooking(self):
        for path in [*INTEGRATION.rglob("*"), *(ADDON / "frontend" / "src").rglob("*")]:
            if path.is_file() and path.suffix in (".py", ".json", ".yaml", ".ts", ".js"):
                with self.subTest(path=str(path.relative_to(REPO))):
                    self.assertNotIn("breville_cooking", path.read_text(encoding="utf-8"))

    def test_the_panel_bundle_speaks_to_this_domain(self):
        bundle = (INTEGRATION / "frontend" / "bruh-cooking-panel.js").read_text(encoding="utf-8")
        for command in ("subscribe", "apply_preset", "save_preset", "delete_preset"):
            self.assertIn(f"bruh_cooking/panel/{command}", bundle)

    def test_the_manifest_names_the_add_on(self):
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())
        self.assertEqual((manifest["domain"], manifest["name"]), ("bruh_cooking", "BRUH Cooking"))
        self.assertIn("bruhautomation/BRUH-HA-Apps", manifest["documentation"])


class TestDiscovery(unittest.TestCase):
    def test_the_add_on_announces_the_integration_domain(self):
        self.assertEqual(config()["discovery"], ["bruh_cooking"])
        self.assertIn('service: "bruh_cooking"', (ADDON / "run.sh").read_text())

    def test_the_integration_answers_the_announcement(self):
        self.assertIn("async def async_step_hassio", (INTEGRATION / "config_flow.py").read_text())


class TestServices(unittest.TestCase):
    def test_every_service_is_documented_and_translated(self):
        documented = set(yaml.safe_load((INTEGRATION / "services.yaml").read_text()))
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        self.assertEqual(documented, set(strings["services"]))
        self.assertEqual(documented, {"start_cook", "get_status", "get_presets", "start",
                                      "stop", "continue_cook"})
        for service, spec in yaml.safe_load((INTEGRATION / "services.yaml").read_text()).items():
            for field in (spec or {}).get("fields", {}):
                with self.subTest(service=service, field=field):
                    self.assertIn(field, strings["services"][service]["fields"])

    def test_the_english_translation_is_the_strings_file(self):
        self.assertEqual(json.loads((INTEGRATION / "strings.json").read_text()),
                         json.loads((INTEGRATION / "translations" / "en.json").read_text()))

    def test_every_refusal_has_words(self):
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        source = "".join(p.read_text() for p in INTEGRATION.glob("*.py"))
        for key in set(re.findall(r'translation_key="([a-z_]+)"', source)):
            if key in ("oven_mode", "convection", "level", "brand"):
                continue
            with self.subTest(key=key):
                self.assertIn(key, strings["exceptions"])


class TestOptions(unittest.TestCase):
    def test_every_option_is_translated(self):
        labels = yaml.safe_load((ADDON / "translations" / "en.yaml").read_text())["configuration"]
        self.assertEqual(set(config()["options"]), set(labels))

    def test_nothing_is_published_and_no_panel_is_added(self):
        cfg = config()
        self.assertNotIn("ports", cfg)
        self.assertFalse(cfg.get("ingress", False))
        self.assertFalse(cfg.get("host_network", False))


@unittest.skipUnless(JQ, "jq is not installed")
class TestBrainIsRequired(unittest.TestCase):
    """The add-on's own rule: no brAIn, no BRUH Cooking. Found by its slug
    tail AND its name, as brAIn's devloop finds the BRUH add-ons."""

    def state(self, addons) -> str:
        info = json.dumps({"result": "ok", "data": {"addons": addons}})
        out = subprocess.run([JQ, "-r", brain_filter()], input=info, capture_output=True,
                             text=True, check=True)
        return out.stdout.strip()

    def test_brain_installed_is_found_with_its_state(self):
        self.assertEqual(self.state([
            {"slug": "a1b2c3d4_brain", "name": "brAIn", "state": "started"},
            {"slug": "a1b2c3d4_bruh-cooking", "name": "BRUH Cooking", "state": "started"},
        ]), "started")
        self.assertEqual(self.state([{"slug": "local_brain", "name": "brAIn",
                                      "state": "stopped"}]), "stopped")

    def test_no_brain_is_nothing(self):
        self.assertEqual(self.state([]), "")
        self.assertEqual(self.state([{"slug": "x_bruh-cooking", "name": "BRUH Cooking"}]), "")

    def test_a_strangers_brain_is_not_brain(self):
        self.assertEqual(self.state([{"slug": "x_brain", "name": "Big Brain"}]), "")
        self.assertEqual(self.state([{"slug": "x_mybrain", "name": "brAIn"}]), "")

    def test_absent_stops_the_add_on_and_unknown_does_not(self):
        run = (ADDON / "run.sh").read_text()
        absent = run[run.index("        absent)"):run.index(";;", run.index("        absent)"))]
        self.assertIn("exit 1", absent)
        unknown = run[run.index("        unknown)"):run.index(";;", run.index("        unknown)"))]
        self.assertNotIn("exit", unknown)


class TestRunSh(unittest.TestCase):
    def test_run_sh_parses(self):
        subprocess.run(["bash", "-n", str(ADDON / "run.sh")], check=True)

    def test_run_sh_deploys_the_integration_it_ships(self):
        run = (ADDON / "run.sh").read_text()
        self.assertIn('INTEGRATION="bruh_cooking"', run)
        dockerfile = (ADDON / "Dockerfile").read_text()
        self.assertIn("COPY custom_components/ /opt/bruh-cooking/custom_components/", dockerfile)
        self.assertIn('COOKING_HOME="/opt/bruh-cooking"', run)


if __name__ == "__main__":
    unittest.main()
