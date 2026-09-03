#!/usr/bin/env python3
"""BRUH Print's own shape: the manifest, the scripts, the card.

Everything here is a one-line edit away from being wrong in a way nothing
else notices — a `usb: true` deleted from config.yaml, a run.sh that exports
an option under a name nothing reads, a card that imports something the
browser cannot fetch.
"""
import ast
import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON = BASE_DIR / "bruh-print"
PANEL = ADDON / "panel"
INTEGRATION = ADDON / "custom_components" / "bruh_print"
CARD = ADDON / "lovelace" / "bruh-print-card.js"


def config():
    return yaml.safe_load((ADDON / "config.yaml").read_text())


def integration_const():
    """The integration's const.py, imported for real.

    It is the one module in `custom_components/bruh_print` that imports
    nothing from Home Assistant, which is what makes this possible at all —
    `homeassistant` is not installed in CI, so everything else here can only
    be parsed.
    """
    path = INTEGRATION / "const.py"
    spec = importlib.util.spec_from_file_location("bruh_print_const", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestManifest(unittest.TestCase):
    def test_usb_access_is_declared(self):
        """The one permission this add-on exists for. Without it the panel
        starts, the UI works, and no printer is ever found."""
        self.assertTrue(config().get("usb"))

    def test_it_does_not_ask_for_host_networking(self):
        """BRight needs it for LIFX discovery and pays a security point for
        it. A LabelWriter is on USB; asking for the LAN here would be asking
        for something this add-on has no use for."""
        self.assertFalse(config().get("host_network", False))

    def test_no_port_is_published(self):
        """Ingress reaches the container; a published port answers the LAN
        with no Home Assistant login in front of it."""
        self.assertNotIn("ports", config())

    def test_the_ingress_port_is_pinned_and_the_watchdog_names_it(self):
        """Pinned is right HERE and would be wrong in BRight: with no host
        networking the port lives inside the container's own namespace and
        cannot collide with anything on the host."""
        data = config()
        self.assertEqual(8097, data["ingress_port"])
        self.assertIn("8097", data["watchdog"])

    def test_the_image_name_follows_the_folder(self):
        """build.yml names the image after the matrix entry, which is the
        directory it builds."""
        self.assertEqual("ghcr.io/bruhautomation/{arch}-bruh-print",
                         config()["image"])

    def test_the_version_matches_the_changelog(self):
        version = config()["version"]
        changelog = (ADDON / "CHANGELOG.md").read_text()
        self.assertIn(f"## {version}", changelog,
                      f"CHANGELOG.md has no entry for {version}")


class TestBuildWiring(unittest.TestCase):
    """An add-on the CI does not build is an add-on nobody can install."""

    def test_the_build_matrix_includes_it(self):
        workflow = (BASE_DIR / ".github" / "workflows" / "build.yml").read_text()
        self.assertIn("bruh-print", workflow)
        self.assertIn('- "bruh-print/**"', workflow)

    def test_the_dockerfile_installs_what_the_panel_imports(self):
        dockerfile = (ADDON / "Dockerfile").read_text()
        for package in ("libusb", "py3-pillow", "py3-aiohttp", "font-dejavu"):
            with self.subTest(package=package):
                self.assertIn(package, dockerfile)
        for package in ("pyusb", "qrcode"):
            with self.subTest(package=package):
                self.assertIn(package, dockerfile)

    def test_it_ships_no_cups(self):
        """The whole reason panel/dymo/ exists. A print server inside the
        container would add a spooler, a PPD and a filter chain to produce
        the same bytes.

        Comments are stripped before looking: the Dockerfile SAYS "there is
        no cups here", and a test that reads the prose rather than the
        packages passes on a file that says one thing and installs another.
        """
        lines = [line.split("#", 1)[0].lower()
                 for line in (ADDON / "Dockerfile").read_text().splitlines()]
        installed = "\n".join(lines)
        for unwanted in ("cups", "ghostscript", "foomatic"):
            with self.subTest(package=unwanted):
                self.assertNotIn(unwanted, installed)


class TestRunScript(unittest.TestCase):
    def setUp(self):
        self.run_sh = (ADDON / "run.sh").read_text()

    def test_it_parses(self):
        subprocess.run(["bash", "-n", str(ADDON / "run.sh")], check=True)

    def test_every_option_reaches_something_that_reads_it(self):
        """An option read into a local name and never exported is a setting
        that silently keeps its default forever — see the brAIn notes on
        MAX_TURNS for the version of this that shipped."""
        for option in config()["options"]:
            with self.subTest(option=option):
                self.assertIn(f"bashio::config '{option}'", self.run_sh)

    def test_the_panel_reads_the_names_run_sh_exports(self):
        """The two halves have to agree, and nothing at runtime says so."""
        server = (PANEL / "server.py").read_text()
        for name in ("BRUH_PRINT_PANEL_PORT", "BRUH_PRINT_LOG_LEVEL",
                     "BRUH_PRINT_DATA", "BRUH_PRINT_SHARED"):
            with self.subTest(variable=name):
                self.assertRegex(self.run_sh, rf"export {name}=",
                                 f"run.sh never exports {name}")
                self.assertIn(name, server)

    def test_the_env_file_is_written_before_anything_sources_it(self):
        """`load_config` writes /data/.bruh_print_env and everything that
        reads it starts after. Reading it before it exists is a process that
        keeps its fallback for its whole life."""
        order = [self.run_sh.index(f"    {name}\n") for name in
                 ("load_config", "prepare_filesystem", "start_ha_bridge",
                  "start_panel")]
        self.assertEqual(sorted(order), order,
                         "main() no longer loads config before it starts "
                         "anything that reads it")

    def test_the_bridge_drops_privileges_and_the_panel_says_why_it_cannot(self):
        """The bridge reads files written from outside this container, so it
        runs at UID 1000. The panel opens /dev/bus/usb, whose nodes carry the
        HOST's root:root ownership because there is no udev in here — so it
        cannot, and the reason is written down rather than left as an
        apparent oversight for somebody to "fix" into a printer that stops
        working."""
        self.assertIn("su-exec bruhprint python3 -u", self.run_sh,
                      "the bridge no longer drops privileges")
        panel_note = self.run_sh.split("start_panel() {")[0]
        self.assertIn("/dev/bus/usb", panel_note,
                      "run.sh no longer explains why the panel is root")

    def test_nothing_tells_a_person_to_enable_a_setting_that_does_not_exist(self):
        """`usb: true` is a manifest permission the Supervisor applies when
        it builds the container. There is no switch in the Configuration tab
        and there never was — but the README, DOCS, the startup warning and
        the panel's own "cannot open the printer" message all told people to
        go and find one, which is the worst kind of wrong documentation:
        confidently specific about a place to look that does not exist.
        """
        claims = ("usb access is on", "turn usb access on",
                  "enable usb access", "after enabling it",
                  "only grants on a restart")
        files = [ADDON / "README.md", ADDON / "DOCS.md", ADDON / "run.sh",
                 PANEL / "dymo" / "usb_link.py"]
        for path in files:
            body = path.read_text().lower()
            for claim in claims:
                with self.subTest(file=path.name, claim=claim):
                    self.assertNotIn(claim, body)

    def test_it_reports_what_is_on_the_usb_bus_at_startup(self):
        """"BRUH Print cannot see my printer" has three causes that look
        identical from the panel. One line at boot tells them apart."""
        self.assertIn("/dev/bus/usb", self.run_sh)
        self.assertIn("report_usb", self.run_sh)


class TestIntegration(unittest.TestCase):
    def test_every_python_file_parses(self):
        for path in sorted(INTEGRATION.glob("*.py")):
            with self.subTest(module=path.name):
                ast.parse(path.read_text())

    def test_every_service_the_bridge_routes_is_declared(self):
        """A service registered with no route forwards into a 404; a route
        with no service is dead code."""
        bridge = (ADDON / "integrations" / "ha-bridge.py").read_text()
        routed = set(re.findall(r'^\s+"(\w+)": lambda', bridge, re.M))
        declared = set(yaml.safe_load((INTEGRATION / "services.yaml").read_text()))
        self.assertEqual(declared, routed,
                         "services.yaml and the bridge's routing table "
                         "disagree about what this integration can do")

    def test_every_service_is_registered_in_python(self):
        init = (INTEGRATION / "__init__.py").read_text()
        for name in yaml.safe_load((INTEGRATION / "services.yaml").read_text()):
            with self.subTest(service=name):
                self.assertIn(f'"{name}"', init + (INTEGRATION / "const.py").read_text())

    def test_every_service_has_strings(self):
        """A service with no strings entry shows its raw key in the UI."""
        strings = json.loads((INTEGRATION / "strings.json").read_text())
        declared = set(yaml.safe_load((INTEGRATION / "services.yaml").read_text()))
        self.assertEqual(declared, set(strings["services"]))

    def test_the_translations_are_the_strings(self):
        """They drift the moment one is edited and the other is not."""
        self.assertEqual(
            json.loads((INTEGRATION / "strings.json").read_text()),
            json.loads((INTEGRATION / "translations" / "en.json").read_text()))

    def test_the_brand_folder_is_beside_the_manifest(self):
        """HA 2026.3.0+ serves this itself and prefers it over the CDN; a
        bare custom_components/<domain>/icon.png is read by nothing."""
        for name in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png"):
            with self.subTest(asset=name):
                self.assertTrue((INTEGRATION / "brand" / name).is_file())


class TestLovelaceCard(unittest.TestCase):
    def setUp(self):
        self.card = CARD.read_text()

    def test_it_parses_as_a_module(self):
        subprocess.run(["node", "--check", str(CARD)], check=True)

    def test_it_fetches_nothing(self):
        """A card that imports LitElement off a CDN breaks the day the CDN
        is unreachable, which on a Home Assistant box is an ordinary
        Tuesday. It also cannot ship inside an add-on image if it needs a
        bundler."""
        self.assertNotIn("import ", self.card.split("/*", 1)[0] + "\n")
        for forbidden in ("unpkg.com", "cdn.jsdelivr", "https://cdn"):
            with self.subTest(source=forbidden):
                self.assertNotIn(forbidden, self.card)

    def test_it_never_talks_to_the_add_on_directly(self):
        """It runs in whoever's browser is looking at the dashboard, which
        may be a phone on mobile data — it has no route to the ingress port
        and no business having one."""
        self.assertNotIn("8097", self.card)
        self.assertNotIn("/api/print", self.card)

    def test_it_registers_itself_with_the_card_picker(self):
        self.assertIn("window.customCards", self.card)
        self.assertIn("customElements.define('bruh-print-card'", self.card)

    def test_it_only_calls_services_this_integration_has(self):
        declared = set(yaml.safe_load((INTEGRATION / "services.yaml").read_text()))
        called = set(re.findall(r"_call\('(\w+)'", self.card))
        self.assertTrue(called, "the card calls no services at all")
        self.assertTrue(called <= declared,
                        f"the card calls {called - declared}, which the "
                        f"integration does not provide")

    def test_run_sh_installs_it_where_core_can_serve_it(self):
        run_sh = (ADDON / "run.sh").read_text()
        self.assertIn("/config/www/bruh_print", run_sh)
        const = (INTEGRATION / "const.py").read_text()
        self.assertIn("/local/bruh_print/bruh-print-card.js", const)

    def test_the_integration_checks_the_file_before_registering_it(self):
        """Registering a URL that 404s puts a red error in everybody's
        browser console on every page load, about a feature they turned
        off."""
        init = (INTEGRATION / "__init__.py").read_text()
        self.assertIn("CARD_FILE", init)
        self.assertIn("is_file", init)

    def test_the_card_version_is_the_add_on_version(self):
        """The banner the card prints into the browser console is how
        anybody tells which card they are actually being served. A version
        that stopped being bumped is a banner that lies about exactly the
        thing somebody opened the console to find out."""
        version = config()["version"]
        self.assertIn(f"CARD_VERSION = '{version}'", self.card)

    def test_the_registered_url_carries_a_content_hash(self):
        """Core serves /local with a 31-day cache header, so a card updated
        in place reaches a browser that already has one exactly never.

        This drives the real helper over two files rather than reading the
        source, because what matters is that the URL *changes when the bytes
        change* — a hash of the version string would pass any grep and fail
        the day somebody forgets to bump it."""
        const = integration_const()
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "one.js"
            two = Path(tmp) / "two.js"
            one.write_text("const CARD_VERSION = '0.2.2';")
            two.write_text("const CARD_VERSION = '0.3.0';")
            first = const.card_url(one)
            second = const.card_url(two)
        prefix = const.CARD_URL + "?v="
        self.assertTrue(first.startswith(prefix), first)
        self.assertTrue(second.startswith(prefix), second)
        self.assertNotEqual(first, second,
                            "two different cards got the same URL, so an "
                            "update reaches nobody who has the old one")

    def test_the_same_bytes_get_the_same_url(self):
        """A restart copies the card in whether or not it changed. If the URL
        moved every time, every restart would re-download it for everybody —
        which is the cache working exactly as intended, thrown away."""
        const = integration_const()
        with tempfile.TemporaryDirectory() as tmp:
            one = Path(tmp) / "one.js"
            two = Path(tmp) / "two.js"
            one.write_text("same bytes\n")
            two.write_text("same bytes\n")
            self.assertEqual(const.card_url(one), const.card_url(two))

    def test_the_integration_registers_the_hashed_url(self):
        """A source-level check, and only ever *in addition* to driving
        `card_url` above: `homeassistant` is not installed here, so there is
        no way to call `_register_card` and watch what it hands the
        frontend. What this can still see is that the bare CARD_URL is not
        what goes in — registering that is the whole bug."""
        init = (INTEGRATION / "__init__.py").read_text()
        self.assertIn("card_url(CARD_FILE)", init)
        self.assertNotIn("add_extra_js_url(hass, CARD_URL)", init)

    def test_the_integration_keeps_looking_for_a_card_that_is_not_there_yet(self):
        """Core can set the entry up before the add-on has copied the card
        in — a first install, or an add-on update while Core was already
        running. Giving up there means no card until Core restarts.

        Source-level for the same reason as above; the pure half of this is
        `card_url`, and the retry is all Home Assistant's own scheduling."""
        init = (INTEGRATION / "__init__.py").read_text()
        self.assertIn("async_call_later", init)
        tree = ast.parse(init)
        unload = [n for n in tree.body
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "async_unload_entry"]
        self.assertEqual(1, len(unload), "no async_unload_entry to check")
        called = {n.func.id for n in ast.walk(unload[0])
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_cancel_card_retry", called,
                      "a retry that outlives the entry fires into a "
                      "half-unloaded integration")


class TestPanelUI(unittest.TestCase):
    def test_the_javascript_parses(self):
        subprocess.run(["node", "--check", str(PANEL / "app.js")], check=True)

    def test_the_stylesheet_balances(self):
        css = (PANEL / "style.css").read_text()
        self.assertEqual(css.count("{"), css.count("}"))

    def test_the_touch_floor_is_the_last_block_in_the_stylesheet(self):
        """Equal specificity is settled by order, so anywhere but the end a
        control declared further down keeps its desktop size on a phone —
        which is what left every `.btn.tiny` at 32px."""
        css = (PANEL / "style.css").read_text()
        self.assertGreater(css.index("@media (pointer: coarse)"),
                           css.rindex(".btn.tiny { min-height: 32px"))

    def test_hidden_is_forced(self):
        """`hidden` is a UA rule at the lowest specificity, so any class rule
        with a display beats it — which left an empty black toast across the
        bottom of the panel."""
        css = (PANEL / "style.css").read_text()
        self.assertIn("[hidden] { display: none !important; }", css)

    def test_the_favicon_is_the_lockup_not_the_bare_gable(self):
        """The roof is the family mark: it says BRUH and says nothing about
        which add-on you are looking at."""
        favicon = (PANEL / "favicon.svg").read_text()
        self.assertIn("M159.55,176c0-23.95", favicon)

    def test_the_panel_serves_named_assets_and_not_a_directory(self):
        """This test used to assert `add_static("/static/", PANEL_DIR)` —
        it pinned the bug in place rather than a behaviour, which is what a
        test of an implementation line does. Serving that directory answered
        `GET /static/server.py` with the panel's own source. The routes are
        named now, and `test_bruh_print_panel.TestItDoesNotServeItsOwnSource`
        drives them rather than reading for them."""
        server = (PANEL / "server.py").read_text()
        # Comments stripped before looking: the file SAYS why add_static is
        # gone, and a test that reads the prose passes on a file that says
        # one thing and routes another. Same trap as the "no CUPS" check.
        code = "\n".join(line.split("#", 1)[0]
                         for line in server.splitlines())
        self.assertNotIn("add_static(", code)
        for asset in ("style.css", "app.js", "favicon.svg"):
            with self.subTest(asset=asset):
                self.assertIn(f'_asset("{asset}"', server)
        self.assertIn('add_get("/api/health"', server)

    def test_the_page_asks_for_its_assets_relatively(self):
        """Ingress mounts the panel under a prefix, so an absolute asset URL
        is a request to Home Assistant's own root — which is what 0.1.1 did,
        and it rendered as unstyled HTML with every view stacked."""
        page = (PANEL / "index.html").read_text()
        for bad in ('href="/', 'src="/'):
            with self.subTest(pattern=bad):
                self.assertNotIn(bad, page)


if __name__ == "__main__":
    unittest.main()
