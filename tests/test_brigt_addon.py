#!/usr/bin/env python3
"""BRigt add-on coherence and the panel's LAN gate, exercised.

BRigt runs `host_network: true` (LIFX discovery is a UDP broadcast), so its
panel port answers the LAN with no Home Assistant login in front of it —
the same shape BRUH Minecraft has, and the same exposure GHSA-gh5m-4m97-c95h
was about. The gate tests here are the ones that make that safe to ship.
"""

import asyncio
import importlib.util
import json
import os
import unittest

import yaml

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "brigt")
MINECRAFT_DIR = os.path.join(BASE_DIR, "bruh-minecraft-server")


def load_config(addon_dir=ADDON_DIR):
    with open(os.path.join(addon_dir, "config.yaml")) as f:
        return yaml.safe_load(f)


class TestBrigtManifest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def test_identity(self):
        self.assertEqual("brigt", self.config["slug"])
        self.assertEqual("BRigt", self.config["name"])

    def test_every_option_has_a_schema_entry(self):
        options = set(self.config["options"])
        schema = set(self.config["schema"])
        self.assertEqual(options, schema,
                         "options and schema disagree — the Supervisor "
                         "refuses unknown keys and ignores unvalidated ones")

    def test_version_matches_integration_manifest(self):
        manifest = os.path.join(ADDON_DIR, "custom_components", "brigt",
                                "manifest.json")
        with open(manifest) as f:
            integration_version = json.load(f)["version"]
        self.assertEqual(self.config["version"], integration_version)

    def test_host_network_is_on_for_lifx(self):
        """Discovery is a UDP broadcast; a bridged container never hears
        the replies. Turning this off silently breaks the whole product."""
        self.assertTrue(self.config.get("host_network"))

    def test_the_panel_port_is_not_minecrafts(self):
        """Both add-ons run host_network, so their ingress ports are REAL
        host ports. Two add-ons racing for one port is one add-on that
        fails to start — on the machine of exactly the person who runs
        both."""
        minecraft = load_config(MINECRAFT_DIR)
        self.assertNotEqual(self.config["ingress_port"],
                            minecraft["ingress_port"])

    def test_role_stays_default(self):
        """host_network already costs a rating point; hassio_role admin
        would cost two more and drop the add-on below 6/6."""
        self.assertEqual("default", self.config.get("hassio_role", "default"))

    def test_music_folder_is_confined_to_media(self):
        """The schema pins the option under /media — the only mount the
        analyzer needs, and a path outside it would quietly read nothing."""
        self.assertIn("^/media", self.config["schema"]["music_folder"])

    def test_discovery_announces_the_brigt_domain(self):
        self.assertIn("brigt", self.config.get("discovery", []))


class TestBrigtPanelIsGated(unittest.TestCase):
    """The gate greps: no client-settable header is read, and only health
    is public."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "panel", "server.py")) as f:
            cls.server = f.read()

    def test_the_gate_exists_and_is_installed(self):
        self.assertIn("_lan_gate", self.server)
        self.assertIn("middlewares=[_lan_gate]", self.server)

    def test_the_gate_does_not_trust_forwarded_headers(self):
        for forged in ("X-Forwarded-For\"", "X-Forwarded-For'",
                       "X-Real-IP\"", "X-Real-IP'"):
            self.assertNotIn(forged, self.server,
                             "the gate reads a client-settable header")
        self.assertIn("peername", self.server)

    def test_only_health_is_public(self):
        self.assertIn('_PUBLIC_PREFIXES = ("/api/health",)', self.server)


def _load_brigt_panel():
    path = os.path.join(ADDON_DIR, "panel", "server.py")
    spec = importlib.util.spec_from_file_location("brigt_panel_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeTransport:
    def __init__(self, host):
        self._host = host

    def get_extra_info(self, name):
        return (self._host, 12345) if name == "peername" else None


class _FakeRequest:
    def __init__(self, path, host, method="POST"):
        self.path = path
        self.method = method
        self.transport = _FakeTransport(host)


class TestBrigtLanGateBehaviour(unittest.TestCase):
    """The gate, exercised rather than grepped — same cases the Minecraft
    gate earns, because it is the same exposure."""

    @classmethod
    def setUpClass(cls):
        cls.panel = _load_brigt_panel()

    def _call(self, path, host, method="POST"):
        async def handler(_):
            return "reached the handler"

        return asyncio.run(
            self.panel._lan_gate(_FakeRequest(path, host, method), handler))

    def test_the_supervisor_gets_through(self):
        self.assertEqual("reached the handler",
                         self._call("/api/status", "172.30.32.2"))

    def test_loopback_gets_through(self):
        self.assertEqual("reached the handler",
                         self._call("/api/status", "127.0.0.1"))

    def test_a_lan_caller_is_refused(self):
        for host in ("192.168.1.50", "10.0.0.7", "172.16.4.4", "100.64.1.1"):
            with self.subTest(host=host):
                response = self._call("/api/status", host)
                self.assertEqual(403, response.status,
                                 f"{host} reached the panel API")

    def test_an_address_just_outside_the_bridge_is_refused(self):
        self.assertEqual(403, self._call("/api/status", "172.30.34.1").status)
        self.assertEqual("reached the handler",
                         self._call("/api/status", "172.30.33.255"))

    def test_ipv4_mapped_ipv6_is_resolved_before_matching(self):
        self.assertEqual(403, self._call("/api/status",
                                         "::ffff:192.168.1.50").status)
        self.assertEqual("reached the handler",
                         self._call("/api/status", "::ffff:172.30.32.2"))

    def test_an_unknown_peer_is_refused(self):
        self.assertEqual(403, self._call("/api/status", None).status)
        self.assertEqual(403, self._call("/api/status", "not-an-ip").status)

    def test_health_stays_public(self):
        self.assertEqual(
            "reached the handler",
            self._call("/api/health", "192.168.1.50", method="GET"))

    def test_static_assets_are_gated_too(self):
        for path in ("/", "/app.js", "/style.css"):
            with self.subTest(path=path):
                self.assertEqual(
                    403, self._call(path, "192.168.1.50", method="GET").status)


class TestBridgeContract(unittest.TestCase):
    """The integration's request kinds and the bridge's must agree — a kind
    only one side knows about is a service that always times out."""

    def test_every_service_kind_is_known_to_the_bridge(self):
        const_path = os.path.join(ADDON_DIR, "custom_components", "brigt",
                                  "const.py")
        with open(const_path) as f:
            const = f.read()
        with open(os.path.join(ADDON_DIR, "integrations", "ha-bridge.py")) as f:
            bridge = f.read()
        for service in ("party_mode", "start_show", "stop_show"):
            with self.subTest(service=service):
                self.assertIn(f'"{service}"', const)
                self.assertIn(service, bridge)


if __name__ == "__main__":
    unittest.main()
