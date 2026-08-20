#!/usr/bin/env python3
"""BRight add-on coherence and the panel's LAN gate, exercised.

BRight runs `host_network: true` (LIFX discovery is a UDP broadcast), so its
panel port answers the LAN with no Home Assistant login in front of it —
the same shape BRUH Minecraft has, and the same exposure GHSA-gh5m-4m97-c95h
was about. The gate tests here are the ones that make that safe to ship.
"""

import asyncio
import importlib.util
import json
import os
import socket
import unittest
import unittest.mock

import aiohttp
import yaml
from aiohttp import web

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "bright")
MINECRAFT_DIR = os.path.join(BASE_DIR, "bruh-minecraft-server")


def load_config(addon_dir=ADDON_DIR):
    with open(os.path.join(addon_dir, "config.yaml")) as f:
        return yaml.safe_load(f)


class TestBrightManifest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.config = load_config()

    def test_identity(self):
        self.assertEqual("bright", self.config["slug"])
        self.assertEqual("BRight", self.config["name"])

    def test_every_option_has_a_schema_entry(self):
        options = set(self.config["options"])
        schema = set(self.config["schema"])
        self.assertEqual(options, schema,
                         "options and schema disagree — the Supervisor "
                         "refuses unknown keys and ignores unvalidated ones")

    def test_version_matches_integration_manifest(self):
        manifest = os.path.join(ADDON_DIR, "custom_components", "bright",
                                "manifest.json")
        with open(manifest) as f:
            integration_version = json.load(f)["version"]
        self.assertEqual(self.config["version"], integration_version)

    def test_host_network_is_on_for_lifx(self):
        """Discovery is a UDP broadcast; a bridged container never hears
        the replies. Turning this off silently breaks the whole product."""
        self.assertTrue(self.config.get("host_network"))

    def test_the_panel_pins_no_host_port(self):
        """host_network means the ingress port is a REAL host port, so any
        number written into config.yaml is a number somebody's box may
        already have. 8095 was picked to dodge BRUH Minecraft's 8099 and
        collided with something else entirely — `[Errno 98] address in
        use`, on every boot, with no way out. 0 asks the Supervisor for a
        free one instead."""
        self.assertEqual(0, self.config["ingress_port"])

    def test_it_cannot_collide_with_minecraft(self):
        """The add-on most likely to be installed beside this one is the
        other host_network add-on in this repo."""
        minecraft = load_config(MINECRAFT_DIR)
        self.assertNotEqual(self.config["ingress_port"],
                            minecraft["ingress_port"])

    def test_reading_the_assigned_port_back_is_allowed(self):
        """/addons/self/info is how the assigned port comes back, and it
        needs hassio_api. Without it the panel would fall back to a
        hardcoded port the Supervisor is not proxying to."""
        self.assertTrue(self.config.get("hassio_api"))

    def test_role_stays_default(self):
        """host_network already costs a rating point; hassio_role admin
        would cost two more and drop the add-on below 6/6."""
        self.assertEqual("default", self.config.get("hassio_role", "default"))

    def test_music_folder_is_confined_to_media(self):
        """The schema pins the option under /media — the only mount the
        analyzer needs, and a path outside it would quietly read nothing."""
        self.assertIn("^/media", self.config["schema"]["music_folder"])

    def test_discovery_announces_the_bright_domain(self):
        self.assertIn("bright", self.config.get("discovery", []))


class TestBrightPanelIsGated(unittest.TestCase):
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

    def test_nothing_is_public(self):
        """Health was public for the Supervisor watchdog, which polled from
        off-network. That watchdog is gone (the port is no longer ours to
        name in config.yaml) and run.sh polls loopback instead, which the
        gate already trusts — so the exemption has no caller left."""
        self.assertIn("_PUBLIC_PREFIXES: tuple[str, ...] = ()", self.server)


def _load_bright_panel():
    path = os.path.join(ADDON_DIR, "panel", "server.py")
    spec = importlib.util.spec_from_file_location("bright_panel_gate", path)
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


class TestBrightLanGateBehaviour(unittest.TestCase):
    """The gate, exercised rather than grepped — same cases the Minecraft
    gate earns, because it is the same exposure."""

    @classmethod
    def setUpClass(cls):
        cls.panel = _load_bright_panel()

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

    def test_health_is_gated_too(self):
        """Its only caller is run.sh, on loopback."""
        self.assertEqual(403,
                         self._call("/api/health", "192.168.1.50",
                                    method="GET").status)
        self.assertEqual(
            "reached the handler",
            self._call("/api/health", "127.0.0.1", method="GET"))

    def test_static_assets_are_gated_too(self):
        for path in ("/", "/app.js", "/style.css"):
            with self.subTest(path=path):
                self.assertEqual(
                    403, self._call(path, "192.168.1.50", method="GET").status)


class TestTheServicesReportWhatHappened(unittest.TestCase):
    """Grepped rather than run — the integration imports Home Assistant,
    which is not installed here. The shape is what matters and the shape is
    what regressed: three handlers that awaited the bridge and dropped what
    came back, so an automation asking for party mode with nothing analyzed
    got a green tick and a dark room."""

    @classmethod
    def setUpClass(cls):
        path = os.path.join(ADDON_DIR, "custom_components", "bright",
                            "__init__.py")
        with open(path) as handle:
            cls.source = handle.read()

    def test_no_handler_calls_the_bridge_directly(self):
        """Parsed, not grepped: `_forward` calls the bridge and that is the
        point of it, so the question is which functions do."""
        import ast

        tree = ast.parse(self.source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("handle_"):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "send_request"):
                    offenders.append(node.name)
        self.assertEqual([], offenders,
                         "a service handler talks to the bridge itself, so "
                         "whatever came back is dropped")

    def test_every_service_goes_through_the_forwarder(self):
        for service in ("SERVICE_PARTY_MODE", "SERVICE_START_SHOW",
                        "SERVICE_STOP_SHOW"):
            with self.subTest(service=service):
                self.assertIn(f"_forward({service}", self.source)

    def test_a_refusal_becomes_an_error_home_assistant_shows(self):
        self.assertIn("HomeAssistantError", self.source)
        self.assertIn('response.get("ok") is False', self.source)


class TestBridgeContract(unittest.TestCase):
    """The integration's request kinds and the bridge's must agree — a kind
    only one side knows about is a service that always times out."""

    def test_every_service_kind_is_known_to_the_bridge(self):
        const_path = os.path.join(ADDON_DIR, "custom_components", "bright",
                                  "const.py")
        with open(const_path) as f:
            const = f.read()
        with open(os.path.join(ADDON_DIR, "integrations", "ha-bridge.py")) as f:
            bridge = f.read()
        for service in ("party_mode", "start_show", "stop_show"):
            with self.subTest(service=service):
                self.assertIn(f'"{service}"', const)
                self.assertIn(service, bridge)


def _load_panel_port():
    path = os.path.join(ADDON_DIR, "panel", "panel_port.py")
    spec = importlib.util.spec_from_file_location("bright_panel_port", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeSupervisorResponse:
    """What urlopen returns: a context manager whose read() is bytes."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode()


class TestPanelPortResolution(unittest.TestCase):
    """Where the panel's port comes from, in the order that keeps run.sh,
    the panel and the bridge talking about the same one."""

    def setUp(self):
        self.port = _load_panel_port()

    def _env(self, **values):
        return unittest.mock.patch.dict(os.environ, values, clear=True)

    def _supervisor_answers(self, payload):
        """Stand in for urlopen, which is used as a context manager."""
        return unittest.mock.patch.object(
            self.port.urllib.request, "urlopen",
            lambda *a, **k: _FakeSupervisorResponse(payload))

    def test_the_env_run_sh_exported_wins(self):
        with self._env(BRIGHT_PANEL_PORT="8412", SUPERVISOR_TOKEN="t"):
            with unittest.mock.patch.object(
                    self.port.urllib.request, "urlopen",
                    side_effect=AssertionError("asked the Supervisor anyway")):
                self.assertEqual(8412, self.port.resolve())

    def test_the_supervisor_is_asked_when_the_env_is_empty(self):
        with self._env(SUPERVISOR_TOKEN="t"):
            with self._supervisor_answers({"data": {"ingress_port": 8731}}):
                self.assertEqual(8731, self.port.resolve())

    def test_no_token_means_no_request(self):
        """A dev checkout has no Supervisor; asking anyway is a ten-second
        wait on a hostname that does not resolve."""
        with self._env():
            with unittest.mock.patch.object(
                    self.port.urllib.request, "urlopen",
                    side_effect=AssertionError("called with no token")):
                self.assertEqual(self.port.DEFAULT_PORT, self.port.resolve())

    def test_an_unusable_answer_falls_through(self):
        """0 is what config.yaml asks WITH and never what comes back. A
        panel on an ephemeral port is a panel ingress cannot reach, so an
        answer that is not a port is no answer."""
        for answer in (0, None, "", "nope", -1, 70000, {"a": 1}):
            with self.subTest(answer=answer):
                with self._env(SUPERVISOR_TOKEN="t"):
                    with self._supervisor_answers(
                            {"data": {"ingress_port": answer}}):
                        self.assertEqual(self.port.DEFAULT_PORT,
                                         self.port.resolve())

    def test_a_string_port_is_still_a_port(self):
        with self._env(BRIGHT_PANEL_PORT=" 8099 "):
            self.assertEqual(8099, self.port.resolve())

    def test_a_supervisor_that_errors_does_not_take_the_panel_down(self):
        for boom in (OSError("refused"),
                     self.port.urllib.error.URLError("no route"),
                     ValueError("not json")):
            with self.subTest(error=type(boom).__name__):
                with self._env(SUPERVISOR_TOKEN="t"):
                    with unittest.mock.patch.object(
                            self.port.urllib.request, "urlopen",
                            side_effect=boom):
                        self.assertEqual(self.port.DEFAULT_PORT,
                                         self.port.resolve())

    def test_a_body_that_is_not_the_shape_we_expect(self):
        for payload in ({}, {"data": None}, {"data": []}, []):
            with self.subTest(payload=payload):
                with self._env(SUPERVISOR_TOKEN="t"):
                    with self._supervisor_answers(payload):
                        self.assertEqual(self.port.DEFAULT_PORT,
                                         self.port.resolve())


class TestBindSaysWhatWentWrong(unittest.TestCase):
    """The crash this whole arrangement exists to end:

        OSError: [Errno 98] error while attempting to bind on address
        ('0.0.0.0', 8095): address in use

    ...as a traceback, from inside aiohttp, under a log line claiming the
    panel was listening on that port."""

    def setUp(self):
        self.port = _load_panel_port()

    def test_a_free_port_binds(self):
        sock = self.port.bind("127.0.0.1", 0)
        self.addCleanup(sock.close)
        self.assertGreater(sock.getsockname()[1], 0)

    def test_a_held_port_is_a_sentence_naming_it(self):
        held = socket.socket()
        self.addCleanup(held.close)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]

        with self.assertRaises(self.port.PortInUse) as caught:
            self.port.bind("127.0.0.1", taken, attempts=1)

        message = str(caught.exception)
        self.assertIn(str(taken), message)
        self.assertIn("host_network", message.lower())

    def test_it_retries_before_giving_up(self):
        """A watchdog restart can leave the previous panel holding the
        socket for a moment; that case is worth waiting out."""
        held = socket.socket()
        self.addCleanup(held.close)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]

        slept = []
        with unittest.mock.patch.object(self.port.time, "sleep", slept.append):
            with self.assertRaises(self.port.PortInUse):
                self.port.bind("127.0.0.1", taken, attempts=3, delay=2.0)
        self.assertEqual([2.0, 2.0], slept,
                         "waited between the wrong number of attempts")

    def test_a_different_failure_is_not_dressed_up_as_a_busy_port(self):
        """An address that is not this machine's fails with EADDRNOTAVAIL.
        Reporting that as 'something else owns the port' sends people
        hunting for a process that does not exist."""
        try:
            probe = socket.socket()
            probe.bind(("203.0.113.7", 0))
        except OSError:
            probe.close()
        else:
            probe.close()
            self.skipTest("this host will bind anything")
        with self.assertRaises(OSError) as caught:
            self.port.bind("203.0.113.7", 0, attempts=1)
        self.assertNotIsInstance(caught.exception, self.port.PortInUse)


class TestThePanelStartsOrSaysWhyNot(unittest.TestCase):
    """The two ends of the fix, on a real socket: it serves, or it explains."""

    def test_health_answers_on_the_socket_bind_returned(self):
        """Exactly the call run.sh's health watch makes — through the LAN
        gate, from loopback, on a socket panel_port.bind() handed over."""
        panel = _load_bright_panel()
        port_mod = _load_panel_port()

        async def go():
            sock = port_mod.bind("127.0.0.1", 0)
            runner = web.AppRunner(panel.build_app())
            await runner.setup()
            await web.SockSite(runner, sock).start()
            port = sock.getsockname()[1]
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                            f"http://127.0.0.1:{port}/api/health") as response:
                        return response.status, await response.json()
            finally:
                await runner.cleanup()

        status, body = asyncio.run(go())
        self.assertEqual(200, status)
        self.assertTrue(body["ok"])

    def test_a_taken_port_ends_in_a_log_line_not_a_traceback(self):
        """What shipped: aiohttp raised OSError out of main(), under a log
        line that had already claimed the panel was listening."""
        panel = _load_bright_panel()
        held = socket.socket()
        self.addCleanup(held.close)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]

        env = {"BRIGHT_PANEL_PORT": str(taken)}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with unittest.mock.patch.object(panel, "BIND_HOST", "127.0.0.1"):
                with unittest.mock.patch.object(
                        panel.panel_port.time, "sleep", lambda _: None):
                    with unittest.mock.patch.object(
                            panel.web, "run_app",
                            side_effect=AssertionError("served anyway")):
                        with self.assertLogs("bright.panel", level="INFO") as logs:
                            with self.assertRaises(SystemExit) as caught:
                                panel.main()

        self.assertEqual(1, caught.exception.code)
        self.assertIn(str(taken), "\n".join(logs.output))
        self.assertNotIn("listening on", "\n".join(logs.output))


class TestOnePortForEveryone(unittest.TestCase):
    """run.sh logs it, the panel binds it, the bridge posts to it. A second
    copy of the number is a bridge posting into nothing."""

    def _code_lines(self, *parts):
        with open(os.path.join(ADDON_DIR, *parts)) as f:
            for number, line in enumerate(f, 1):
                bare = line.strip()
                if bare and not bare.startswith("#"):
                    yield number, bare

    def test_the_port_literal_lives_in_one_module(self):
        for parts in (("run.sh",),
                      ("panel", "server.py"),
                      ("integrations", "ha-bridge.py")):
            with self.subTest(file="/".join(parts)):
                for number, line in self._code_lines(*parts):
                    self.assertNotIn(
                        "8095", line,
                        f"{'/'.join(parts)}:{number} pins the panel port; "
                        f"panel_port.py is where that number lives")

    def test_run_sh_exports_the_port_it_resolved(self):
        with open(os.path.join(ADDON_DIR, "run.sh")) as f:
            run_sh = f.read()
        self.assertIn("import panel_port", run_sh)
        self.assertIn("export BRIGHT_PANEL_PORT", run_sh)
        self.assertIn("echo \"export BRIGHT_PANEL_PORT=", run_sh,
                      "the port never reaches a with-contenv child")

    def test_the_panel_binds_what_it_resolved(self):
        with open(os.path.join(ADDON_DIR, "panel", "server.py")) as f:
            server = f.read()
        self.assertIn("panel_port.resolve()", server)
        self.assertIn("panel_port.bind(", server)
        self.assertIn("sock=sock", server)

    def test_the_health_watch_polls_the_resolved_port(self):
        with open(os.path.join(ADDON_DIR, "run.sh")) as f:
            run_sh = f.read()
        self.assertIn("127.0.0.1:${PANEL_PORT}/api/health", run_sh)


if __name__ == "__main__":
    unittest.main()
