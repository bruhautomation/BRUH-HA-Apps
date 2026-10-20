"""GardenRX: the add-on's wiring, held from both ends.

The app itself is tested by its own vitest suite (gardenrx/app, run by CI's
"GardenRX app" job). What lives here is the part between the app and Home
Assistant, where two files have to agree and nothing else would notice they
had stopped: the five places a version is written, the one port three files
name, the services the integration registers against the ones it documents,
the sensor kinds the cards look for — and the two pieces of JavaScript that
make ingress work, driven as the processes they are rather than grepped.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "gardenrx"
INTEGRATION = ADDON / "custom_components" / "gardenrx"
CARDS = INTEGRATION / "frontend" / "gardenrx-cards.js"
GATEWAY = ADDON / "gateway"
NODE = shutil.which("node")


def config() -> dict:
    return yaml.safe_load((ADDON / "config.yaml").read_text())


def const_value(name: str):
    tree = ast.parse((INTEGRATION / "const.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise KeyError(name)


class TestOneVersion(unittest.TestCase):
    def test_every_place_a_version_is_written_agrees(self):
        version = config()["version"]
        manifest = json.loads((INTEGRATION / "manifest.json").read_text())["version"]
        package = json.loads((ADDON / "app" / "package.json").read_text())["version"]
        card = re.search(r"^const CARD_VERSION = '([^']+)';", CARDS.read_text(), re.M).group(1)
        self.assertEqual(
            {version},
            {manifest, const_value("VERSION"), package, card},
            "config.yaml, the manifest, const.py, the app's package.json and the card file disagree",
        )

    def test_the_changelog_opens_on_the_shipped_version(self):
        first = re.search(r"^## (\S+)", (ADDON / "CHANGELOG.md").read_text(), re.M).group(1)
        self.assertEqual(config()["version"], first)


class TestOnePort(unittest.TestCase):
    def test_ingress_watchdog_run_sh_and_integration_name_the_same_port(self):
        cfg = config()
        port = cfg["ingress_port"]
        self.assertIn(f"[PORT:{port}]", cfg["watchdog"])
        self.assertIn(f"export GARDENRX_PORT={port}", (ADDON / "run.sh").read_text())
        self.assertEqual(port, const_value("DEFAULT_PORT"))

    def test_nothing_is_published_to_the_lan(self):
        self.assertFalse(config().get("ports"), "GardenRX is reached through ingress and Core only")

    def test_discovery_announces_the_integration_domain(self):
        self.assertEqual(["gardenrx"], config()["discovery"])
        self.assertIn('service: "gardenrx"', (ADDON / "run.sh").read_text())

    def test_the_token_path_is_spelled_the_same_in_both_halves(self):
        self.assertIn('GARDENRX_SHARED="/config/.gardenrx"', (ADDON / "run.sh").read_text())
        self.assertIn('"${GARDENRX_SHARED}/api_token"', (ADDON / "run.sh").read_text())
        self.assertEqual(".gardenrx/api_token", const_value("TOKEN_PATH"))


class TestServices(unittest.TestCase):
    def setUp(self):
        self.services = yaml.safe_load((INTEGRATION / "services.yaml").read_text())
        self.strings = json.loads((INTEGRATION / "strings.json").read_text())

    def test_every_service_is_documented_and_translated(self):
        registered = set(const_value("ACTIONS")) | {"refresh"}
        self.assertEqual(registered, set(self.services))
        self.assertEqual(registered, set(self.strings["services"]))

    def test_every_field_has_a_label(self):
        for service, spec in self.services.items():
            fields = set((spec or {}).get("fields", {}))
            labelled = set(self.strings["services"][service].get("fields", {}))
            self.assertEqual(fields, labelled, service)

    def test_the_translation_file_is_the_strings_file(self):
        self.assertEqual(self.strings, json.loads((INTEGRATION / "translations" / "en.json").read_text()))

    def test_every_action_names_an_action_the_app_has(self):
        app = (ADDON / "app" / "src" / "lib" / "ha" / "actions.ts").read_text()
        block = app.split("export const ACTIONS = {", 1)[1].split("}", 1)[0]
        app_actions = set(re.findall(r"^\s*(\w+):", block, re.M))
        self.assertEqual(set(const_value("ACTIONS").values()), app_actions)

    def test_the_route_has_a_branch_for_every_action(self):
        route = (ADDON / "app" / "src" / "app" / "api" / "ha" / "action" / "route.ts").read_text()
        cases = set(re.findall(r"case '(\w+)':", route))
        self.assertEqual(set(const_value("ACTIONS").values()), cases)


class TestCardsFindTheirSensors(unittest.TestCase):
    def test_every_kind_a_card_reads_is_a_kind_a_sensor_publishes(self):
        card_kinds = set(re.findall(r"static kind = '(\w+)';", CARDS.read_text()))
        sensor_kinds = set(re.findall(r'kind="(\w+)"', (INTEGRATION / "sensor.py").read_text()))
        self.assertTrue(card_kinds)
        self.assertLessEqual(card_kinds, sensor_kinds)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_card_file_parses(self):
        subprocess.run([NODE, "--check", str(CARDS)], check=True)


def run_node(script: str, *args: str, timeout: float = 30) -> str:
    out = subprocess.run(
        [NODE, "--input-type=module", "-e", script, *args],
        capture_output=True, text=True, timeout=timeout,
    )
    if out.returncode != 0:
        raise AssertionError(f"node failed:\n{out.stdout}\n{out.stderr}")
    return out.stdout


@unittest.skipUnless(NODE, "node is not installed")
class TestTheGateway(unittest.TestCase):
    """The Supervisor strips the ingress prefix; the gateway puts it back."""

    def test_the_prefix_goes_back_on_and_is_never_doubled(self):
        out = run_node(
            f"""
            import {{ upstreamPath }} from {json.dumps(str(GATEWAY / 'gateway.mjs'))};
            const B = '/api/hassio_ingress/tok';
            console.log(JSON.stringify([
              upstreamPath('/', B), upstreamPath('/crops?x=1', B), upstreamPath(B + '/crops', B),
              upstreamPath(B, B), upstreamPath('//evil.example/x', B), upstreamPath('/crops', ''),
              upstreamPath(B + 'x/crops', B),
            ]));
            """
        )
        self.assertEqual(
            [
                "/api/hassio_ingress/tok/",
                "/api/hassio_ingress/tok/crops?x=1",
                "/api/hassio_ingress/tok/crops",
                "/api/hassio_ingress/tok",
                None,
                "/crops",
                "/api/hassio_ingress/tok/api/hassio_ingress/tokx/crops",
            ],
            json.loads(out),
        )

    def test_a_request_reaches_the_app_under_its_base_path(self):
        out = run_node(
            f"""
            import http from 'node:http';
            import {{ createGateway }} from {json.dumps(str(GATEWAY / 'gateway.mjs'))};
            const seen = [];
            const app = http.createServer((req, res) => {{
              seen.push([req.method, req.url, req.headers.authorization || null]);
              res.writeHead(200, {{ 'content-type': 'text/plain', connection: 'close' }});
              res.end('hello');
            }});
            await new Promise((r) => app.listen(0, '127.0.0.1', r));
            const gw = createGateway({{ base: '/api/hassio_ingress/tok', upstream: app.address().port }});
            await new Promise((r) => gw.listen(0, '127.0.0.1', r));
            const url = `http://127.0.0.1:${{gw.address().port}}`;
            const a = await fetch(url + '/harvest', {{ headers: {{ authorization: 'Bearer t' }} }});
            const body = await a.text();
            app.close();
            const b = await fetch(url + '/api/health');
            console.log(JSON.stringify({{ seen, body, down: b.status }}));
            gw.close();
            """
        )
        got = json.loads(out)
        self.assertEqual([["GET", "/api/hassio_ingress/tok/harvest", "Bearer t"]], got["seen"])
        self.assertEqual("hello", got["body"])
        self.assertEqual(502, got["down"], "an app that is down is a 502, which the watchdog restarts")


@unittest.skipUnless(NODE, "node is not installed")
class TestPrepareBase(unittest.TestCase):
    """The ingress path is written over the placeholder the image was built with."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        build = self.tmp / "build"
        (build / ".next" / "static").mkdir(parents=True)
        (build / ".next" / "BUILD_ID").write_text("b1")
        (build / ".next" / "static" / "app.js").write_text('var p="/__gardenrx_base_path__/_next";')
        (build / "server.js").write_text('const c={"basePath":"/__gardenrx_base_path__"}')
        (build / "public").mkdir()
        (build / "public" / "photo.jpg").write_bytes(b"\xff\xd8/__gardenrx_base_path__")
        self.build = build

    def prepare(self, base: str):
        return subprocess.run(
            [NODE, str(GATEWAY / "prepare-base.mjs"), str(self.build), str(self.tmp / "run"), base],
            capture_output=True, text=True, timeout=30,
        )

    def test_every_text_file_gets_the_path_and_binaries_are_left_alone(self):
        r = self.prepare("/api/hassio_ingress/AbC_1-x")
        self.assertEqual(0, r.returncode, r.stderr)
        run = self.tmp / "run"
        self.assertEqual('var p="/api/hassio_ingress/AbC_1-x/_next";', (run / ".next/static/app.js").read_text())
        self.assertIn('"basePath":"/api/hassio_ingress/AbC_1-x"', (run / "server.js").read_text())
        self.assertEqual(b"\xff\xd8/__gardenrx_base_path__", (run / "public/photo.jpg").read_bytes())
        self.assertIn("__gardenrx_base_path__", (self.build / "server.js").read_text(), "the pristine build was edited")

    def test_a_second_start_with_the_same_path_copies_nothing(self):
        self.prepare("/api/hassio_ingress/abc")
        (self.tmp / "run" / "server.js").write_text("touched")
        r = self.prepare("/api/hassio_ingress/abc")
        self.assertIn("already", r.stdout)
        self.assertEqual("touched", (self.tmp / "run" / "server.js").read_text())
        self.prepare("/api/hassio_ingress/other")
        self.assertIn("/api/hassio_ingress/other", (self.tmp / "run" / "server.js").read_text())

    def test_a_path_that_is_not_a_path_is_refused(self):
        for bad in ('/x";alert(1)//', "/a/../b", "relative", "/a b", "/a/"):
            with self.subTest(bad=bad):
                r = self.prepare(bad)
                self.assertNotEqual(0, r.returncode)
                self.assertFalse((self.tmp / "run" / "server.js").exists())

    def test_no_supervisor_means_the_root(self):
        self.assertEqual(0, self.prepare("").returncode)
        self.assertIn('"basePath":""', (self.tmp / "run" / "server.js").read_text())


def load_api():
    """`api.py` and `const.py`, without running the package's __init__ —
    they import only aiohttp, which is the point of keeping them apart."""
    pkg = types.ModuleType("gardenrx_cc")
    pkg.__path__ = [str(INTEGRATION)]
    saved = sys.modules.get("gardenrx_cc")
    sys.modules["gardenrx_cc"] = pkg
    try:
        return importlib.import_module("gardenrx_cc.api")
    finally:
        sys.modules.pop("gardenrx_cc.api", None)
        sys.modules.pop("gardenrx_cc.const", None)
        if saved is None:
            sys.modules.pop("gardenrx_cc", None)
        else:
            sys.modules["gardenrx_cc"] = saved


class TestTheIntegrationsClient(unittest.TestCase):
    """The integration's half of the API, against a real HTTP server."""

    def setUp(self):
        self.api = load_api()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.token = self.tmp / "api_token"
        self.token.write_text("t" * 40 + "\n")

    def serve(self, handler):
        from aiohttp import web

        async def run(body):
            app = web.Application()
            app.router.add_route("*", "/{tail:.*}", handler)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            import aiohttp

            async with aiohttp.ClientSession() as session:
                client = self.api.GardenRxClient(session, "127.0.0.1", port, self.token)
                try:
                    return await body(client)
                finally:
                    await runner.cleanup()

        return run

    def test_it_sends_the_token_and_reads_the_summary(self):
        from aiohttp import web

        seen = {}

        async def handler(request):
            seen["auth"] = request.headers.get("Authorization")
            seen["path"] = request.path
            return web.json_response({"version": 1, "harvest": {"total_lb": 2}})

        got = asyncio.run(self.serve(handler)(lambda c: c.summary()))
        self.assertEqual("Bearer " + "t" * 40, seen["auth"])
        self.assertEqual("/api/ha/summary", seen["path"])
        self.assertEqual(2, got["harvest"]["total_lb"])

    def test_a_refusal_arrives_as_the_add_ons_own_sentence(self):
        from aiohttp import web

        async def handler(request):
            body = await request.json()
            self.assertEqual({"action": "log_harvest", "data": {"crop": "kiwi"}}, body)
            return web.json_response({"ok": False, "error": 'No crop is called "kiwi".'}, status=409)

        with self.assertRaisesRegex(self.api.GardenRxError, 'No crop is called "kiwi"'):
            asyncio.run(self.serve(handler)(lambda c: c.action("log_harvest", {"crop": "kiwi"})))

    def test_a_wrong_token_says_what_to_do(self):
        from aiohttp import web

        async def handler(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        with self.assertRaisesRegex(self.api.GardenRxError, "Restart the add-on"):
            asyncio.run(self.serve(handler)(lambda c: c.summary()))

    def test_no_token_file_says_where_it_should_be(self):
        from aiohttp import web

        async def handler(request):  # pragma: no cover - never reached
            return web.json_response({})

        self.token.unlink()
        with self.assertRaisesRegex(self.api.GardenRxError, "Start the GardenRX add-on"):
            asyncio.run(self.serve(handler)(lambda c: c.summary()))

    def test_an_add_on_that_is_down_is_named(self):
        import aiohttp

        async def body():
            async with aiohttp.ClientSession() as session:
                client = self.api.GardenRxClient(session, "127.0.0.1", 1, self.token)
                await client.summary()

        with self.assertRaisesRegex(self.api.GardenRxError, "not answering"):
            asyncio.run(body())


class TestRunSh(unittest.TestCase):
    def test_run_sh_parses(self):
        subprocess.run(["bash", "-n", str(ADDON / "run.sh")], check=True)

    def test_the_app_and_the_gateway_run_unprivileged(self):
        run = (ADDON / "run.sh").read_text()
        self.assertIn("su-exec gardenrx env HOSTNAME=127.0.0.1", run)
        self.assertIn('su-exec gardenrx node "${GARDENRX_HOME}/gateway/gateway.mjs"', run)

    def test_the_app_listens_on_loopback_only(self):
        # Everything from outside comes through the gateway; the app itself
        # answers nothing but 127.0.0.1.
        self.assertIn("HOSTNAME=127.0.0.1", (ADDON / "run.sh").read_text())


if __name__ == "__main__":
    unittest.main()
