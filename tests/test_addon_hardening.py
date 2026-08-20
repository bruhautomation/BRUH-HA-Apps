#!/usr/bin/env python3
"""
Tests for the add-on hardening contract.

Every assertion here stands for something that was once wrong and is
cheap to make wrong again by editing one line of YAML:

- The brAIn terminal port shipped published and passwordless, so anyone on
  the LAN had a root shell with /config and a signed-in Claude.
- The Minecraft panel binds 0.0.0.0 under `host_network: true`, so its
  management API answered the LAN too.
- `apparmor: false` disabled the Supervisor's sandbox on Minecraft.
- Credentials in /data ride into unencrypted Home Assistant backups
  unless `backup_exclude` says otherwise.
- Option translations drift the moment someone adds an option, and the
  drift is invisible — the UI just shows the raw key.
"""

import asyncio
import importlib.util
import os
import sys
import unittest

import yaml

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDONS = {
    "brain": os.path.join(BASE_DIR, "brain"),
    "bruh_minecraft_server": os.path.join(BASE_DIR, "bruh-minecraft-server"),
    "brigt": os.path.join(BASE_DIR, "brigt"),
}


def load_config(addon_dir):
    with open(os.path.join(addon_dir, "config.yaml"), "r") as f:
        return yaml.safe_load(f)


def load_translations(addon_dir):
    path = os.path.join(addon_dir, "translations", "en.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


class TestAppArmor(unittest.TestCase):
    """Both add-ons ship a profile, and neither disables the sandbox."""

    def test_every_addon_ships_a_profile(self):
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                self.assertTrue(
                    os.path.isfile(os.path.join(addon_dir, "apparmor.txt")),
                    f"{slug} has no apparmor.txt — the Supervisor drops a "
                    f"point of security rating and runs it unsandboxed",
                )

    def test_apparmor_is_never_disabled(self):
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                self.assertIsNot(
                    load_config(addon_dir).get("apparmor", True), False,
                    f"{slug} sets apparmor: false",
                )

    def test_profile_name_matches_the_slug(self):
        """The Supervisor loads the profile under the add-on's slug."""
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                with open(os.path.join(addon_dir, "apparmor.txt")) as f:
                    body = f.read()
                self.assertIn(
                    f"profile {slug} ", body,
                    f"{slug}'s apparmor.txt does not declare `profile {slug}`",
                )

    def test_host_escape_primitives_are_denied(self):
        """A profile that allows these is a profile not worth having.

        These four are the load-bearing ones: without them a container
        can mount the host filesystem, load a kernel module, or grant
        itself the capability to do either.
        """
        required_denials = [
            "deny mount",
            "deny /sys/module/** wklx",
            "deny capability sys_admin",
            "deny capability sys_module",
        ]
        for slug, addon_dir in ADDONS.items():
            with open(os.path.join(addon_dir, "apparmor.txt")) as f:
                body = f.read()
            for rule in required_denials:
                with self.subTest(addon=slug, rule=rule):
                    self.assertIn(rule, body,
                                  f"{slug}'s profile is missing `{rule}`")

    def test_the_docker_socket_is_denied(self):
        """A writable docker.sock is root on the host by another name."""
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                with open(os.path.join(addon_dir, "apparmor.txt")) as f:
                    body = f.read()
                self.assertIn("deny /var/run/docker.sock rwklx", body)


class TestTerminalPortIsNotOpen(unittest.TestCase):
    """ttyd is a shell; it does not answer the LAN for free."""

    @classmethod
    def setUpClass(cls):
        cls.config = load_config(ADDONS["brain"])
        with open(os.path.join(ADDONS["brain"], "run.sh")) as f:
            cls.run_sh = f.read()

    def test_terminal_port_is_not_published_by_default(self):
        self.assertIsNone(
            self.config["ports"]["7681/tcp"],
            "7681 is published by default — a passwordless shell on the LAN "
            "for anyone who installs the add-on",
        )

    def test_ttyd_is_started_with_a_credential(self):
        self.assertIn(
            "--credential", self.run_sh,
            "ttyd is started without --credential; publishing the port then "
            "means publishing an unauthenticated shell",
        )

    def test_the_credential_is_generated_not_hardcoded(self):
        self.assertIn("/dev/urandom", self.run_sh)
        self.assertNotRegex(
            self.run_sh, r'--credential\s+"?[A-Za-z0-9]+:[A-Za-z0-9]{4,}"?\s*\\',
            "a literal password in run.sh is the same password on every install",
        )

    def test_the_panel_carries_the_credential_upstream(self):
        """Ingress users must not meet a login prompt for a password they
        have never been shown."""
        with open(os.path.join(ADDONS["brain"], "panel", "terminal_proxy.py")) as f:
            proxy = f.read()
        self.assertIn("terminal-credential", proxy)
        self.assertIn("Basic ", proxy)

    def test_the_proxy_does_not_trust_a_client_supplied_credential(self):
        with open(os.path.join(ADDONS["brain"], "panel", "terminal_proxy.py")) as f:
            proxy = f.read()
        self.assertIn(
            'headers.pop("Authorization", None)', proxy,
            "the proxy must drop the client's Authorization header before "
            "adding its own, or a browser can present its own credential",
        )


class TestMinecraftPanelIsGated(unittest.TestCase):
    """host_network: true puts the panel on the LAN. Only HA may drive it."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDONS["bruh_minecraft_server"],
                               "panel", "server.py")) as f:
            cls.server = f.read()

    def test_the_gate_exists_and_is_installed(self):
        self.assertIn("_lan_gate", self.server)
        self.assertIn("middlewares=[_lan_gate]", self.server)

    def test_the_gate_does_not_trust_forwarded_headers(self):
        """X-Forwarded-For is client-controlled on a direct connection, so
        reading it would let a LAN caller claim to be the Supervisor. The
        gate reads the socket's own peer address instead. (The string may
        appear in a comment saying exactly this — what must not appear is
        a read of the header.)"""
        for forged in ("X-Forwarded-For\"", "X-Forwarded-For'",
                       "X-Real-IP\"", "X-Real-IP'"):
            self.assertNotIn(
                forged, self.server,
                "the gate reads a client-settable header",
            )
        self.assertIn("peername", self.server)

    def test_only_health_and_packs_are_public(self):
        self.assertIn('_PUBLIC_PREFIXES = ("/pack/", "/api/health")', self.server)


def _load_mc_panel():
    """Import the Minecraft panel far enough to exercise its middleware.

    The module imports an RCON client at load time; the gate does not care,
    so a stub is enough to get the module in.
    """
    rcon_mod = type(sys)("rcon_client")

    class _FakeRcon:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def command(self, *a, **kw): return "ok"

    rcon_mod.Rcon = _FakeRcon
    sys.modules["rcon_client"] = rcon_mod
    os.environ.setdefault("BRUH_MC_SCRIPTS_DIR", "/nonexistent/for-tests")

    path = os.path.join(ADDONS["bruh_minecraft_server"], "panel", "server.py")
    spec = importlib.util.spec_from_file_location("mc_panel_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeTransport:
    def __init__(self, host):
        self._host = host

    def get_extra_info(self, name):
        return (self._host, 12345) if name == "peername" else None


class _FakeRequest:
    """Just enough request for the gate: a path, a method, a peer."""

    def __init__(self, path, host, method="POST"):
        self.path = path
        self.method = method
        self.transport = _FakeTransport(host)


class TestLanGateBehaviour(unittest.TestCase):
    """The gate, exercised rather than grepped.

    Reading the source proves the middleware is installed; only calling it
    proves it says no to the right callers.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = _load_mc_panel()

    def _call(self, path, host, method="POST"):
        async def handler(_):
            return "reached the handler"

        return asyncio.run(
            self.panel._lan_gate(_FakeRequest(path, host, method), handler))

    def test_the_supervisor_gets_through(self):
        self.assertEqual("reached the handler",
                         self._call("/api/command", "172.30.32.2"))

    def test_loopback_gets_through(self):
        self.assertEqual("reached the handler",
                         self._call("/api/command", "127.0.0.1"))

    def test_a_lan_caller_is_refused(self):
        for host in ("192.168.1.50", "10.0.0.7", "172.16.4.4", "100.64.1.1"):
            with self.subTest(host=host):
                response = self._call("/api/command", host)
                self.assertEqual(403, response.status,
                                 f"{host} reached the RCON endpoint")

    def test_an_address_just_outside_the_bridge_is_refused(self):
        """172.30.32.0/23 ends at 172.30.33.255. Off-by-one here would hand
        the next subnet the whole management API."""
        self.assertEqual(403, self._call("/api/command", "172.30.34.1").status)
        self.assertEqual("reached the handler",
                         self._call("/api/command", "172.30.33.255"))

    def test_ipv4_mapped_ipv6_is_resolved_before_matching(self):
        """A dual-stack listener reports LAN callers as ::ffff:192.168.x.x;
        failing to unwrap that would let them through as 'not an address'."""
        self.assertEqual(403, self._call("/api/command",
                                         "::ffff:192.168.1.50").status)
        self.assertEqual("reached the handler",
                         self._call("/api/command", "::ffff:172.30.32.2"))

    def test_an_unknown_peer_is_refused(self):
        self.assertEqual(403, self._call("/api/command", None).status)
        self.assertEqual(403, self._call("/api/command", "not-an-ip").status)

    def test_the_resource_pack_stays_public(self):
        """Minecraft clients on the LAN must be able to fetch it."""
        self.assertEqual(
            "reached the handler",
            self._call("/pack/world.zip", "192.168.1.50", method="GET"))

    def test_health_stays_public(self):
        self.assertEqual(
            "reached the handler",
            self._call("/api/health", "192.168.1.50", method="GET"))

    def test_static_assets_are_gated_too(self):
        """The panel's own JS tells a reader what the API looks like."""
        for path in ("/", "/app.js", "/style.css"):
            with self.subTest(path=path):
                self.assertEqual(
                    403, self._call(path, "192.168.1.50", method="GET").status)

    def test_a_public_prefix_cannot_be_used_as_a_path_prefix_bypass(self):
        """`/pack/` is a prefix match, so anything that starts with it must
        still be a pack — not a traversal back into the API."""
        response = self._call("/api/command/../pack/x", "192.168.1.50")
        self.assertEqual(403, response.status)


class TestBackupsExcludeCredentials(unittest.TestCase):
    """HA backups are unencrypted unless the user opts in."""

    def test_brain_excludes_the_claude_credential(self):
        excludes = load_config(ADDONS["brain"])["backup_exclude"]
        self.assertIn(".config/claude/**", excludes)
        self.assertIn("terminal-credential", excludes)

    def test_minecraft_excludes_the_rcon_secret(self):
        excludes = load_config(ADDONS["bruh_minecraft_server"])["backup_exclude"]
        self.assertIn("panel/rcon.secret", excludes)


class TestWatchdog(unittest.TestCase):
    """A hung panel is a dead add-on that still reads as started."""

    def test_every_addon_has_a_watchdog(self):
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                self.assertIn("watchdog", load_config(addon_dir))

    def test_the_watchdog_target_is_a_real_route(self):
        """Both watchdogs poll /api/health; both panels must serve it."""
        panels = {
            "brain": os.path.join(ADDONS["brain"], "panel", "server.py"),
            "bruh_minecraft_server": os.path.join(
                ADDONS["bruh_minecraft_server"], "panel", "server.py"),
            "brigt": os.path.join(ADDONS["brigt"], "panel", "server.py"),
        }
        for slug, path in panels.items():
            with self.subTest(addon=slug):
                config = load_config(ADDONS[slug])
                self.assertIn("/api/health", config["watchdog"])
                with open(path) as f:
                    self.assertIn('add_get("/api/health"', f.read())


class TestOptionTranslations(unittest.TestCase):
    """Every option gets a name and a sentence, or the UI shows the raw key."""

    def test_every_option_is_translated(self):
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                options = load_config(addon_dir)["options"]
                translated = load_translations(addon_dir)["configuration"]
                missing = sorted(set(options) - set(translated))
                self.assertEqual(
                    [], missing,
                    f"{slug}: options with no label — Home Assistant will "
                    f"render the raw key: {missing}",
                )

    def test_no_translation_describes_an_option_that_is_gone(self):
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                options = load_config(addon_dir)["options"]
                translated = load_translations(addon_dir)["configuration"]
                stale = sorted(set(translated) - set(options))
                self.assertEqual([], stale, f"{slug}: stale entries: {stale}")

    def test_every_entry_has_both_a_name_and_a_description(self):
        for slug, addon_dir in ADDONS.items():
            translated = load_translations(addon_dir)["configuration"]
            for key, entry in translated.items():
                with self.subTest(addon=slug, option=key):
                    self.assertTrue(entry.get("name"), f"{key} has no name")
                    self.assertTrue(entry.get("description"),
                                    f"{key} has no description")

    def test_every_published_port_is_described(self):
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                config = load_config(addon_dir)
                ports = config.get("ports") or {}
                network = load_translations(addon_dir).get("network") or {}
                missing = sorted(set(ports) - set(network))
                self.assertEqual([], missing, f"{slug}: undescribed ports: {missing}")


class TestIntegrationManifests(unittest.TestCase):
    """hassfest's manifest rules, checked here so a break is local.

    Each of these cost a CI round when the hassfest job was first added,
    and each is a one-line edit away from coming back.
    """

    MANIFESTS = {
        "brain": os.path.join(
            ADDONS["brain"], "custom_components", "brain", "manifest.json"),
        "bruh_minecraft": os.path.join(
            ADDONS["bruh_minecraft_server"], "custom_components",
            "bruh_minecraft", "manifest.json"),
        "brigt": os.path.join(
            ADDONS["brigt"], "custom_components", "brigt", "manifest.json"),
    }

    def _load(self, path):
        import json
        with open(path) as f:
            return json.load(f)

    def test_keys_are_domain_then_name_then_alphabetical(self):
        for slug, path in self.MANIFESTS.items():
            with self.subTest(integration=slug):
                keys = list(self._load(path))
                self.assertEqual(
                    ["domain", "name"], keys[:2],
                    "hassfest wants domain and name first",
                )
                self.assertEqual(
                    sorted(keys[2:]), keys[2:],
                    "hassfest wants the remaining keys alphabetical",
                )

    def test_no_unknown_keys(self):
        """`discovery` lived here for a while and did nothing.

        Supervisor discovery is config.yaml plus the config flow's hassio
        step; a manifest key named after it just fails validation.
        """
        allowed = {
            "domain", "name", "after_dependencies", "codeowners",
            "config_flow", "dependencies", "documentation", "integration_type",
            "iot_class", "issue_tracker", "loggers", "quality_scale",
            "requirements", "single_config_entry", "version",
        }
        for slug, path in self.MANIFESTS.items():
            with self.subTest(integration=slug):
                unknown = sorted(set(self._load(path)) - allowed)
                self.assertEqual([], unknown, f"{slug}: unknown keys {unknown}")

    def test_lazily_imported_components_are_declared(self):
        """power_tools imports these inside service handlers, so they are
        after_dependencies — but undeclared they are a hassfest error and,
        at runtime, a load-order gamble."""
        manifest = self._load(self.MANIFESTS["brain"])
        after = manifest.get("after_dependencies", [])
        for component in ("blueprint", "recorder"):
            with self.subTest(component=component):
                self.assertIn(component, after)


class TestSecurityRating(unittest.TestCase):
    """The Supervisor's own arithmetic, so a regression is visible here
    rather than in the store weeks later.

    Base 5; ingress +2, auth_api +1 (superseded by ingress), an apparmor
    profile +1, `apparmor: false` -1, host_network -1, hassio_role manager
    -1 / admin -2, host_pid or full_access -2, docker_api forces 1.
    Clamped to 1..6.
    """

    @staticmethod
    def rating(config, has_profile):
        if config.get("docker_api"):
            return 1
        score = 5
        if config.get("ingress"):
            score += 2
        elif config.get("auth_api"):
            score += 1
        if has_profile and config.get("apparmor", True) is not False:
            score += 1
        if config.get("apparmor", True) is False:
            score -= 1
        if config.get("host_network"):
            score -= 1
        role = config.get("hassio_role", "default")
        if role == "manager":
            score -= 1
        elif role == "admin":
            score -= 2
        if config.get("host_pid") or config.get("full_access"):
            score -= 2
        return max(1, min(6, score))

    def test_both_addons_rate_six(self):
        for slug, addon_dir in ADDONS.items():
            with self.subTest(addon=slug):
                config = load_config(addon_dir)
                has_profile = os.path.isfile(
                    os.path.join(addon_dir, "apparmor.txt"))
                self.assertEqual(
                    6, self.rating(config, has_profile),
                    f"{slug} no longer rates 6/6 in the add-on store",
                )


if __name__ == "__main__":
    unittest.main()
