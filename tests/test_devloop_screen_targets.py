#!/usr/bin/env python3
"""Screens of every BRUH add-on: reached, guarded, redacted and filed.

The claims, each driven:

  * an add-on's panel is opened where the Supervisor says it is — its own
    address on the hassio network, the host's gateway on the host network,
    GardenRX under its ingress path — and an answer that does not say
    where is no URL rather than a guess;
  * an add-on that is not installed, not running or unreadable is named
    with why, and Morph (no panel of its own) is drawn in the harness;
  * the write guard lets reads through and nothing else: a POST is failed
    in the browser unless it is a named read, GardenRX's data route only
    for a select, and a real Chromium against a real server proves no
    write and no WebSocket reaches the server;
  * text inside shadow DOM (every Lovelace card, all of Morph) is redacted
    and its canvases covered, exactly as the page's own;
  * the harness proxy asks Core only what reads, and only from loopback;
  * each add-on's pictures are its own rolling issue, labelled for its
    directory, stored under its own folder in the reports repository.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop  # noqa: E402
import devloop.harness  # noqa: E402
import devloop.screen_targets as st  # noqa: E402
import devloop.screens as screens  # noqa: E402
import devloop.upstream as upstream  # noqa: E402
from test_devloop_screens import browser, warm_up  # noqa: E402

TOKEN = "/api/hassio_ingress/abcdefghijklmnop"


def info(**kw):
    base = {"ingress": True, "ingress_port": 8097, "ip_address": "172.30.33.5",
            "state": "started", "version": "0.4.1", "host_network": False,
            "ingress_entry": TOKEN}
    base.update(kw)
    return base


class TestWhereAPanelIs(unittest.TestCase):
    def test_a_bridged_add_on_is_opened_at_its_own_address(self):
        self.assertEqual(st.panel_url(info()), "http://172.30.33.5:8097/")

    def test_a_host_network_add_on_is_opened_at_the_gateway(self):
        self.assertEqual(st.panel_url(info(host_network=True, ingress_port=40123)),
                         f"http://{st.HOST_GATEWAY}:40123/")

    def test_gardenrx_is_opened_under_its_ingress_path(self):
        self.assertEqual(st.panel_url(info(ingress_port=8101), prefix=True),
                         f"http://172.30.33.5:8101{TOKEN}/")

    def test_an_answer_that_does_not_say_where_is_no_url(self):
        for bad in (info(ingress=False), info(ingress_port=0), info(ingress_port="x"),
                    info(ip_address=""), info(ip_address="evil.com/x?y"),
                    info(ip_address="a b")):
            self.assertEqual(st.panel_url(bad), "", bad)
        self.assertEqual(st.panel_url(info(ingress_entry="/etc/passwd"), prefix=True), "")


def fake_get(addons, infos, fail=()):
    def get(path, text=False):
        if path == "/addons":
            return {"addons": addons}
        slug = path.split("/")[2]
        if slug in fail:
            raise OSError("refused")
        return infos[slug]
    return get


class TestLocate(unittest.TestCase):
    def test_every_add_on_is_a_target_or_a_reason(self):
        addons = [{"slug": "abc_gardenrx", "name": "GardenRX"},
                  {"slug": "abc_bruh-print", "name": "BRUH Print"},
                  {"slug": "abc_bright", "name": "BRight"},
                  {"slug": "abc_morph", "name": "Morph"},
                  {"slug": "abc_bruh_minecraft_server", "name": "BRUH Minecraft"}]
        infos = {"abc_gardenrx": info(ingress_port=8101),
                 "abc_bruh-print": info(),
                 "abc_bright": info(state="stopped"),
                 "abc_morph": info(version="1.2.0")}
        out = st.locate(fake_get(addons, infos, fail=("abc_bruh_minecraft_server",)))
        products = {t["product"]: t for t in out["targets"]}
        self.assertEqual(set(products), {"GardenRX", "BRUH Print"})
        self.assertTrue(products["GardenRX"]["url"].endswith(TOKEN + "/"))
        self.assertTrue(all(t["guard"] for t in out["targets"]))
        self.assertIn("stopped", out["unreached"]["BRight"])
        self.assertIn("could not read", out["unreached"]["BRUH Minecraft"])
        self.assertEqual(out["unreached"]["BRUH Bambu Studio"], "not installed")
        self.assertNotIn("Morph", out["unreached"])
        self.assertEqual(out["versions"]["Morph"], "1.2.0")
        gr = products["GardenRX"]["screens"]
        self.assertEqual(gr[1]["url"], f"http://172.30.33.5:8101{TOKEN}/crops")
        print_screens = products["BRUH Print"]["screens"]
        self.assertIn('data-view="design"', print_screens[1]["script"])
        for t in out["targets"]:
            for s in t["screens"]:
                self.assertTrue(screens.SHOT_RE.match(f"{s['slug']}-1200-light.png"), s["slug"])

    def test_a_supervisor_that_will_not_answer_is_one_sentence(self):
        def get(path, text=False):
            raise OSError("down")
        out = st.locate(get)
        self.assertEqual(out["targets"], [])
        self.assertEqual(set(out["unreached"]), set(st.siblings.PRODUCTS))

    def test_the_harness_draws_only_what_is_installed(self):
        got = st.harness_targets("http://127.0.0.1:8099/", {"Morph": "1", "BRUH Print": "2"})
        self.assertEqual({t["product"] for t in got}, {"Morph", "BRUH Print"})
        for t in got:
            self.assertTrue(t["url"].startswith("http://127.0.0.1:8099/devloop/harness/"))
            self.assertTrue(t["guard"])

    def test_every_catalog_panel_is_an_add_on_and_every_harness_page_exists(self):
        keys = {s["key"] for s in st.siblings.CATALOG}
        self.assertLessEqual(set(st.PANELS), keys)
        for key, _slug, _label, name in st.HARNESS:
            self.assertIn(key, keys)
            self.assertIsNotNone(devloop.harness.page(name), name)

    def test_the_tabs_named_are_the_panels_own(self):
        """A selector that names no button is a screen that is never seen."""
        dirs = {s["key"]: s["dir"] for s in st.siblings.CATALOG}
        for key, panel in st.PANELS.items():
            html = (BASE_DIR / dirs[key] / "panel" / "index.html")
            for _slug, _label, how in panel["screens"]:
                if how[0] != "click":
                    continue
                attr = how[1].split("[", 1)[1].rstrip("]")
                self.assertIn(attr, html.read_text(), f"{key}: {how[1]}")

    def test_the_gardenrx_routes_named_are_pages(self):
        app = BASE_DIR / "gardenrx" / "app" / "src" / "app"
        for _slug, _label, how in st.PANELS["gardenrx"]["screens"]:
            page = app / how[1].strip("/") / "page.tsx"
            self.assertTrue(page.exists(), page)


class TestTheWriteGuard(unittest.TestCase):
    def test_reads_go_and_writes_do_not(self):
        self.assertTrue(screens.request_allowed("GET", "http://x/api/print", None, []))
        self.assertTrue(screens.request_allowed("head", "http://x/", None, []))
        self.assertFalse(screens.request_allowed("POST", "http://x/api/print", "{}", []))
        self.assertFalse(screens.request_allowed("DELETE", "http://x/a", None, []))

    def test_a_named_read_goes(self):
        reads = st.PANELS["bruh-print"]["reads"]
        self.assertTrue(screens.request_allowed("POST", "http://x/api/preview", "{}", reads))
        self.assertTrue(screens.request_allowed(
            "POST", "http://x/api/template/abc/preview", "{}", reads))
        self.assertFalse(screens.request_allowed("POST", "http://x/api/print", "{}", reads))
        self.assertFalse(screens.request_allowed(
            "POST", "http://x/api/template/abc/print", "{}", reads))

    def test_gardenrx_data_goes_only_for_a_select(self):
        reads = st.PANELS["gardenrx"]["reads"]
        url = f"http://x{TOKEN}/api/db"
        self.assertTrue(screens.request_allowed(
            "POST", url, json.dumps({"table": "crops", "action": "select"}), reads))
        for action in ("insert", "update", "upsert", "delete"):
            self.assertFalse(screens.request_allowed(
                "POST", url, json.dumps({"table": "crops", "action": action}), reads))
        self.assertFalse(screens.request_allowed("POST", url, "not json", reads))
        self.assertFalse(screens.request_allowed("POST", url, None, reads))


class TestTheHarnessOnlyReads(unittest.TestCase):
    def test_reads_are_allowed_and_nothing_else(self):
        for kind in ("get_states", "morph/load", "history/history_during_period"):
            self.assertEqual(st.allowed_ws({"type": kind}), "", kind)
        for msg in ({"type": "morph/request", "kind": "save"}, {"type": "morph/usage"},
                    {"type": "call_service", "domain": "light", "service": "turn_on"},
                    {"type": "call_service", "domain": "weather",
                     "service": "get_forecasts"},
                    {"type": "auth/long_lived_access_token"}, "x", None):
            self.assertNotEqual(st.allowed_ws(msg), "", msg)
        self.assertEqual(st.allowed_ws({"type": "call_service", "domain": "weather",
                                        "service": "get_forecasts",
                                        "return_response": True}), "")

    def test_a_page_refuses_every_write(self):
        page = devloop.harness.page("print-card")
        self.assertIn("callService: refuse", page)
        self.assertIn("read-only", page)
        self.assertIsNone(devloop.harness.page("../etc"))
        self.assertIn("/morph/morph-panel.js", devloop.harness.page("morph"))

    def test_files_are_served_by_name_only(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "engine.js").write_text("x")
            (tmp.parent / "outside.js").write_text("x")
            self.assertEqual(st.module_file(str(tmp), "engine.js"), str(tmp / "engine.js"))
            for bad in ("../outside.js", "/etc/passwd", "engine.py", ".hidden.js", ""):
                self.assertEqual(st.module_file(str(tmp), bad), "", bad)
            self.assertEqual(st.card_file("../../secrets.yaml"), "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            (tmp.parent / "outside.js").unlink(missing_ok=True)


class TestTheHarnessRoutes(unittest.TestCase):
    """The proxy and the page, driven through the real handlers."""

    @classmethod
    def setUpClass(cls):
        import server  # noqa: PLC0415
        cls.server = server

    def _client(self):
        from aiohttp import web  # noqa: PLC0415
        app = web.Application()
        app.router.add_get("/devloop/harness/ws", self.server.h_harness_ws)
        app.router.add_get("/devloop/harness/{name}", self.server.h_harness_page)
        return app

    def _run(self, fn):
        from aiohttp.test_utils import TestClient, TestServer  # noqa: PLC0415

        async def go():
            async with TestClient(TestServer(self._client())) as client:
                return await fn(client)
        return asyncio.run(go())

    def test_a_write_never_reaches_core(self):
        asked = []

        async def fake(session, commands, **kw):
            asked.append(commands)
            return [{"ok": True, "result": [{"entity_id": "light.a"}]}]

        async def go(client):
            r1 = await client.get("/devloop/harness/ws", params={
                "msg": json.dumps({"type": "call_service", "domain": "lock",
                                   "service": "unlock"})})
            r2 = await client.get("/devloop/harness/ws", params={
                "msg": json.dumps({"id": 9, "type": "get_states"})})
            return r1.status, await r1.json(), r2.status, await r2.json()

        with mock.patch("ha_data._ws_calls", fake):
            s1, b1, s2, b2 = self._run(go)
        self.assertEqual(s1, 403)
        self.assertIn("only reads", b1["error"])
        self.assertEqual(s2, 200)
        self.assertEqual(b2["result"], [{"entity_id": "light.a"}])
        self.assertEqual(asked, [[{"type": "get_states"}]], "only the read was asked")

    def test_only_loopback_may_ask(self):
        async def go(client):
            r = await client.get("/devloop/harness/print-card")
            return r.status
        with mock.patch("ownership.from_loopback", lambda request: False):
            self.assertEqual(self._run(go), 403)
        self.assertEqual(self._run(go), 200)


class TestOneIssuePerAddOn(unittest.TestCase):
    def _result(self):
        shot = lambda product, name, screen: {  # noqa: E731
            "name": name, "screen": screen, "width": 390, "scheme": "light",
            "sha": "a" * 64, "product": product, "held": ["POST /api/print"] if product != "brAIn" else []}
        return {"shots": [shot("brAIn", "insights-390-light.png", "Insights"),
                          shot("GardenRX", "gardenrx-crops-390-light.png", "GardenRX › Crops"),
                          shot("Morph", "morph-dashboard-390-light.png", "Morph › Dashboard")],
                "problems": [{"screen": "GardenRX › Crops", "width": 390, "scheme": "light",
                              "kind": "off_the_edge", "el": "table", "text": "",
                              "detail": "spans", "product": "GardenRX"}],
                "errors": [{"product": "GardenRX", "text": "GardenRX › Tank: timeout"}]}

    def test_each_add_on_gets_its_own_rolling_issue(self):
        rows = screens.rows(self._result(), "3.4.0", "1700000000",
                            versions={"GardenRX": "0.3.1", "Morph": "1.0.9"},
                            unreached={"BRight": "it is stopped"})
        by = {r.get("product", "brAIn"): r for r in rows}
        self.assertEqual(set(by), {"brAIn", "GardenRX", "Morph"})
        self.assertEqual(by["brAIn"]["key"], "screens:3.4.0")
        self.assertNotIn("product", by["brAIn"])
        self.assertIn("BRight: it is stopped", by["brAIn"]["body"])
        g = by["GardenRX"]
        self.assertEqual(g["product_version"], "0.3.1")
        self.assertIn("UI audit on GardenRX 0.3.1: 1 measured problem", g["what"])
        self.assertIn("`POST /api/print`", g["body"])
        self.assertIn("GardenRX › Tank: timeout", g["body"])
        self.assertNotIn("Off the edge", by["brAIn"]["body"])
        self.assertIn("preview page", by["Morph"]["body"])
        self.assertTrue(all(r["ux"] for r in rows))

    def test_pictures_go_under_the_add_ons_own_folder(self):
        self.assertEqual(screens.repo_path("3.4.0", "x-390-light.png"),
                         "screens/brain-3.4.0/x-390-light.png")
        self.assertEqual(screens.repo_path("0.3.1", "x-390-light.png", "BRUH Print"),
                         "screens/bruh-print-0.3.1/x-390-light.png")

    def test_an_add_ons_screens_are_labelled_for_its_directory(self):
        entry = {"stream": "screens", "product": "GardenRX"}
        self.assertEqual(upstream._addon_labels(entry), ["devloop:gardenrx"])
        self.assertEqual(upstream._addon_labels({"stream": "screens"}), [])


SHADOW_PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width"></head>
<body><x-card></x-card><p>light text</p>
<script>
customElements.define('x-card', class extends HTMLElement { connectedCallback() {
  const r = this.attachShadow({mode: 'open'});
  r.innerHTML = '<div>Next: %(event)s</div><input value="%(event)s"><canvas width=80 height=40></canvas>';
}});
fetch('/api/write', {method: 'POST', body: '{}'}).catch(() => {});
fetch('/api/preview', {method: 'POST', body: '{}'}).catch(() => {});
fetch('/api/read').catch(() => {});
try { new WebSocket('ws://' + location.host + '/ws'); } catch (e) {}
</script></body></html>"""


@pytest.mark.slow
@unittest.skipUnless(browser(), "no Chromium on this machine")
class TestARealBrowserWithTheGuardOn(unittest.TestCase):
    def test_no_write_reaches_the_server_and_shadow_text_is_redacted(self):
        from test_devloop_screens import EVENT  # noqa: PLC0415
        os.environ["BRAIN_CHROMIUM"] = browser()
        warm_up(os.environ["BRAIN_CHROMIUM"])
        hits: list[str] = []
        seen: list[str] = []

        async def look(cdp, session):
            r = await cdp.call("Runtime.evaluate", {"expression": (
                "(() => { const c = document.querySelector('x-card').shadowRoot;"
                " return c.textContent + '|' + c.querySelector('input').value + '|' +"
                " document.querySelectorAll('[data-brain-cover]').length; })()"),
                "returnByValue": True}, session)
            seen.append(r["result"]["value"])

        from aiohttp import web  # noqa: PLC0415

        async def run(out: Path):
            app = web.Application()

            async def page(_r):
                return web.Response(text=SHADOW_PAGE % {"event": EVENT},
                                    content_type="text/html")

            async def any_(request):
                hits.append(f"{request.method} {request.path}")
                return web.json_response({})

            app.router.add_get("/", page)
            app.router.add_route("*", "/api/{x}", any_)
            app.router.add_get("/ws", any_)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            url = f"http://127.0.0.1:{port}/"
            target = {"key": "bruh-print", "product": "BRUH Print", "url": url,
                      "guard": True, "reads": st.PANELS["bruh-print"]["reads"],
                      "screens": [{"slug": "bruh-print-quick", "label": "BRUH Print › Quick",
                                   "url": url, "script": ""}]}
            try:
                return await screens.capture(
                    out, confidential=[EVENT], aliases=None, own=False, targets=[target],
                    views=[(390, 844, True, "light")])
            finally:
                await runner.cleanup()

        old = screens.AFTER_REDACT
        screens.AFTER_REDACT = look
        tmp = tempfile.mkdtemp()
        try:
            result = asyncio.run(asyncio.wait_for(run(Path(tmp)), 120))
        finally:
            screens.AFTER_REDACT = old
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["shots"]), 1)
        self.assertEqual(result["shots"][0]["product"], "BRUH Print")
        self.assertNotIn("POST /api/write", hits)
        self.assertIn("POST /api/preview", hits, "a named read must go through")
        self.assertIn("GET /api/read", hits)
        self.assertFalse(any(h.endswith("/ws") for h in hits), "the WebSocket was not blocked")
        self.assertIn("POST /api/write", result["shots"][0]["held"])
        text = "\n".join(seen)
        self.assertNotIn("Dentist", text)
        self.assertGreaterEqual(int(text.rsplit("|", 1)[1]), 1,
                                f"the shadow canvas was not covered: {text}")


class TestTheChatCanLook(unittest.TestCase):
    def test_the_tool_is_a_read_and_refused_on_voice(self):
        sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
        import engine  # noqa: PLC0415
        import ha_mcp_server  # noqa: PLC0415
        self.assertIn("screenshot_panel", ha_mcp_server.TOOL_IMPLEMENTATIONS)
        self.assertIn("screenshot_panel", ha_mcp_server.VOICE_REFUSED_TOOLS)
        self.assertIn(f"{engine.MCP}screenshot_panel", engine.ANALYST_TOOLS)

    def test_a_picture_comes_back_as_an_image(self):
        sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
        import ha_mcp_server  # noqa: PLC0415
        import base64  # noqa: PLC0415
        png = base64.b64encode(b"\x89PNG small").decode()
        with mock.patch.object(ha_mcp_server, "_panel_send",
                               return_value={"png": png, "addon": "GardenRX",
                                             "screen": "GardenRX › Crops", "problems": []}) as send:
            got = ha_mcp_server.screenshot_panel("GardenRX", "crops", 390, "dark")
        self.assertEqual(got["_mcp_image"], {"data": png, "mimeType": "image/png"})
        self.assertEqual(got["screen"], "GardenRX › Crops")
        self.assertEqual(send.call_args[0][1], "/api/devloop/screenshot")
        with mock.patch.object(ha_mcp_server, "_panel_send",
                               return_value={"error": "nope"}):
            self.assertEqual(ha_mcp_server.screenshot_panel("x"), {"error": "nope"})


if __name__ == "__main__":
    unittest.main()


def _morph_fixture() -> dict | None:
    """The house Morph's own measures use, as JSON, or None without node."""
    import subprocess  # noqa: PLC0415
    node = shutil.which("node")
    if not node:
        return None
    script = ("import('./tests/manual/morph-fixture.mjs').then((m) => console.log(JSON.stringify("
              "{states: m.house(), dash: m.dashboard(), state: m.state(), brain: m.brainFeed()})))")
    try:
        out = subprocess.run([node, "-e", script], cwd=BASE_DIR, capture_output=True,
                             text=True, timeout=60, check=True).stdout
        return json.loads(out)
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


@pytest.mark.slow
@unittest.skipUnless(browser(), "no Chromium on this machine")
class TestTheHarnessDrawsTheRealCode(unittest.TestCase):
    """Morph's own modules and BRUH Print's own card, served by the real
    harness routes and photographed by the real capture: the picture is of
    the code, not a stand-in."""

    def test_morph_and_the_print_card_draw(self):
        fixture = _morph_fixture()
        if fixture is None:
            self.skipTest("no node to build Morph's fixture house")
        import server  # noqa: PLC0415
        os.environ["BRAIN_CHROMIUM"] = browser()
        warm_up(os.environ["BRAIN_CHROMIUM"])
        states = list(fixture["states"].values())
        load = {"mirror": {"revision": "r1", "dashboard": fixture["dash"], "problems": [],
                           "card_modules": []},
                "state": fixture["state"], "brain": fixture["brain"], "admin": True,
                "now": 1.7e9, "code": "", "integration": "x"}
        asked: list[str] = []

        async def fake(session, commands, **kw):
            kind = commands[0]["type"]
            asked.append(kind)
            if kind == "get_states":
                return [{"ok": True, "result": states}]
            if kind == "morph/load":
                return [{"ok": True, "result": load}]
            return [{"ok": True, "result": {} if kind == "get_config" else []}]

        seen: dict[str, str] = {}

        async def look(cdp, session):
            r = await cdp.call("Runtime.evaluate", {"expression": (
                "(() => { const p = document.querySelector('morph-panel, bruh-print-card');"
                " if (!p) return 'none'; const r = p.shadowRoot;"
                " return p.tagName + ':' + (r ? r.textContent.length : 0); })()"),
                "returnByValue": True}, session)
            seen[str(len(seen))] = r["result"]["value"]

        from aiohttp import web  # noqa: PLC0415

        async def run(out: Path):
            app = web.Application()
            app.router.add_get("/devloop/harness/js/{name}", server.h_harness_js)
            app.router.add_get("/devloop/harness/morph/{name}", server.h_harness_morph)
            app.router.add_get("/devloop/harness/ws", server.h_harness_ws)
            app.router.add_get("/devloop/harness/{name}", server.h_harness_page)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            targets = st.harness_targets(f"http://127.0.0.1:{port}/",
                                         {"Morph": "1", "BRUH Print": "1"})
            try:
                return await screens.capture(
                    out, confidential=[], aliases=None, own=False, targets=targets,
                    views=[(1200, 800, False, "dark")])
            finally:
                await runner.cleanup()

        old = screens.AFTER_REDACT
        screens.AFTER_REDACT = look
        tmp = tempfile.mkdtemp()
        card = BASE_DIR / "bruh-print" / "lovelace" / "bruh-print-card.js"
        try:
            with mock.patch("ha_data._ws_calls", fake), \
                 mock.patch.object(st, "MORPH_FRONTEND",
                                   str(BASE_DIR / "morph/custom_components/morph/frontend")), \
                 mock.patch.dict(st.CARD_FILES, {"bruh-print-card.js": (str(card),)}):
                result = asyncio.run(asyncio.wait_for(run(Path(tmp)), 180))
        finally:
            screens.AFTER_REDACT = old
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(result["errors"], [])
        self.assertEqual({s["product"] for s in result["shots"]}, {"Morph", "BRUH Print"})
        drawn = sorted(seen.values())
        self.assertTrue(any(v.startswith("MORPH-PANEL:") and int(v.split(":")[1]) > 200
                            for v in drawn), drawn)
        self.assertTrue(any(v.startswith("BRUH-PRINT-CARD:") and int(v.split(":")[1]) > 20
                            for v in drawn), drawn)
        self.assertIn("morph/load", asked)
        self.assertTrue(set(asked) <= st.READ_COMMANDS, asked)
