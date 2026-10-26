#!/usr/bin/env python3
"""The chat can photograph one card, wherever it is on the page.

`screenshot_panel` offered Morph as one screen, always scrolled to the top
and cropped at a fixed height measured from it — so a card further down a
dashboard could never be in the picture, and nothing could open one to see
how it looks opened. A screen may now name a card or section by its id
(``morph-dashboard#<id>``, or ``element``): the capture scrolls it into
view, crops the picture to it, and can tap it or hold it open first. An id
the page does not have is a sentence, not an exception, and every guard the
page capture has — redaction before the picture, the write guard, no
sockets — holds on this path too.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop.screens as screens  # noqa: E402
from test_devloop_screens import EVENT, browser, warm_up  # noqa: E402


class TestNamingACard(unittest.TestCase):
    def test_a_screen_can_name_a_card_after_a_hash(self):
        self.assertEqual(screens.parse_focus("morph-dashboard#c_lamp", "", ""),
                         ("morph-dashboard", {"id": "c_lamp", "press": ""}, ""))

    def test_the_element_field_names_it_too_and_press_rides_along(self):
        self.assertEqual(screens.parse_focus("dashboard", "s_hall", "open"),
                         ("dashboard", {"id": "s_hall", "press": "open"}, ""))

    def test_no_card_is_the_whole_screen(self):
        self.assertEqual(screens.parse_focus("crops", "", ""), ("crops", None, ""))

    def test_an_id_that_is_not_an_id_is_a_sentence(self):
        screen, focus, why = screens.parse_focus("morph-dashboard#a b<script>", "", "")
        self.assertIsNone(focus)
        self.assertIn("card", why)

    def test_an_unknown_press_is_a_sentence(self):
        _, focus, why = screens.parse_focus("morph-dashboard#c_lamp", "", "smash")
        self.assertIsNone(focus)
        self.assertIn("tap", why)

    def test_the_tool_offers_the_card_and_the_press(self):
        sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
        import ha_mcp_server  # noqa: PLC0415
        tool = next(t for t in ha_mcp_server.TOOLS if t["name"] == "screenshot_panel")
        props = tool["inputSchema"]["properties"]
        self.assertIn("element", props)
        self.assertEqual(set(props["press"]["enum"]), {"tap", "open"})


class TestTheRoute(unittest.TestCase):
    """The panel route the chat's tool asks: the card reaches the capture,
    and a card the page does not have is a 404 with a sentence."""

    def ask(self, body, capture_result):
        import unittest.mock as mock  # noqa: PLC0415

        from aiohttp.test_utils import make_mocked_request  # noqa: PLC0415

        import server  # noqa: PLC0415
        seen = {}

        async def capture(out, **kw):
            seen.update(kw)
            return capture_result

        async def catalog():
            return {"targets": [{"key": "morph", "product": "Morph", "url": "http://x/",
                                 "guard": True, "reads": [], "screens": [
                                     {"slug": "morph-dashboard", "label": "Morph › Dashboard",
                                      "url": "http://x/", "script": ""}]}],
                    "versions": {}, "unreached": {}}

        async def states(*_a, **_k):
            return []

        async def json_body(_r):
            return body

        req = make_mocked_request("POST", "/api/devloop/screenshot")
        with mock.patch.object(server.ownership, "from_loopback", return_value=True), \
             mock.patch.object(server.devloop.screens, "find_browser", return_value="/x"), \
             mock.patch.object(server.devloop.screens, "capture", capture), \
             mock.patch.object(server, "_screen_catalog", catalog), \
             mock.patch.object(server, "_json_body", json_body), \
             mock.patch("ha_data._rest_get", states):
            resp = asyncio.run(server.h_devloop_screenshot(req))
        import json as _json  # noqa: PLC0415
        return resp.status, _json.loads(resp.body), seen

    def test_the_card_and_the_press_reach_the_capture(self):
        status, _body, seen = self.ask(
            {"addon": "Morph", "screen": "morph-dashboard#c_lamp", "press": "open"},
            {"shots": [], "errors": [{"missing": True, "text": "no card c_lamp"}]})
        scr = seen["targets"][0]["screens"][0]
        self.assertEqual(scr["focus"], {"id": "c_lamp", "press": "open"})
        self.assertEqual(status, 404)

    def test_a_missing_card_is_a_sentence(self):
        status, body, _ = self.ask(
            {"addon": "Morph", "screen": "dashboard", "element": "c_nowhere"},
            {"shots": [], "errors": [{"missing": True,
                                      "text": "Morph › Dashboard has no card or section "
                                              "called 'c_nowhere' on screen"}]})
        self.assertEqual(status, 404)
        self.assertIn("c_nowhere", body["error"])

    def test_a_bad_id_is_refused_before_anything_runs(self):
        status, body, seen = self.ask(
            {"addon": "Morph", "screen": "morph-dashboard#<x>"}, {"shots": [], "errors": []})
        self.assertEqual(status, 400)
        self.assertEqual(seen, {})


# A long page: the card is far below any fixed crop from the top, inside a
# shadow root (as all of Morph is). Holding it opens it (taller, and with a
# confidential line in it); a press also tries a write and a socket.
FAR_PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{margin:0} .spacer{height:5200px;background:#eee}</style></head>
<body><div class="spacer">top</div><x-board></x-board><div class="spacer"></div>
<script>
customElements.define('x-board', class extends HTMLElement { connectedCallback() {
  const r = this.attachShadow({mode: 'open'});
  r.innerHTML = '<style>.tile{width:300px;height:180px;background:#9cf;margin:20px}'
    + '.tile.open{height:420px;background:#fc9}</style>'
    + '<section data-sec="s_far"><div class="tile" data-tile="c_far">FAR CARD</div></section>';
  const t = r.querySelector('.tile');
  let down = 0;
  t.addEventListener('pointerdown', () => { down = performance.now(); });
  t.addEventListener('pointerup', () => {
    if (performance.now() - down > 450) {
      t.classList.add('open'); t.innerHTML = '<b>OPENED</b><p>Next: %(event)s</p>';
    } else { t.textContent = 'TAPPED'; }
    fetch('/api/write', {method: 'POST', body: '{}'}).catch(() => {});
    try { new WebSocket('ws://' + location.host + '/ws'); } catch (e) {}
  });
}});
</script></body></html>"""


def png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    return struct.unpack(">II", head[16:24])


@pytest.mark.slow
@unittest.skipUnless(browser(), "no Chromium on this machine")
class TestOneCardInARealBrowser(unittest.TestCase):
    def capture(self, focus):
        os.environ["BRAIN_CHROMIUM"] = browser()
        warm_up(os.environ["BRAIN_CHROMIUM"])
        hits: list[str] = []
        seen: list[str] = []

        async def look(cdp, session):
            r = await cdp.call("Runtime.evaluate", {"expression": (
                "document.querySelector('x-board').shadowRoot.textContent"),
                "returnByValue": True}, session)
            seen.append(r["result"]["value"])

        from aiohttp import web  # noqa: PLC0415

        async def run(out: Path):
            app = web.Application()

            async def page(_r):
                return web.Response(text=FAR_PAGE % {"event": EVENT}, content_type="text/html")

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
            target = {"key": "morph", "product": "Morph", "url": url, "guard": True,
                      "reads": [], "screens": [{"slug": "morph-dashboard",
                                                "label": "Morph › Dashboard", "url": url,
                                                "script": "", "focus": focus}]}
            try:
                return await screens.capture(out, confidential=[EVENT], aliases=None,
                                             own=False, targets=[target],
                                             views=[(390, 844, True, "light")])
            finally:
                await runner.cleanup()

        old = screens.AFTER_REDACT
        screens.AFTER_REDACT = look
        tmp = Path(tempfile.mkdtemp())
        try:
            result = asyncio.run(asyncio.wait_for(run(tmp), 120))
            sizes = [png_size(tmp / s["name"]) for s in result["shots"]]
        finally:
            screens.AFTER_REDACT = old
            shutil.rmtree(tmp, ignore_errors=True)
        return result, sizes, hits, seen

    def test_a_card_far_down_the_page_is_the_picture(self):
        result, sizes, _hits, seen = self.capture({"id": "c_far", "press": ""})
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(sizes), 1)
        w, h = sizes[0]
        # The card, with a little room round it — not the top of the page.
        self.assertLess(h, 260, sizes)
        self.assertGreaterEqual(h, 180, sizes)
        self.assertLessEqual(w, 340, sizes)
        self.assertIn("FAR CARD", " ".join(seen))

    def test_held_open_it_is_photographed_opened_redacted_and_guarded(self):
        result, sizes, hits, seen = self.capture({"id": "c_far", "press": "open"})
        self.assertEqual(result["errors"], [])
        w, h = sizes[0]
        self.assertGreaterEqual(h, 420, sizes)
        text = " ".join(seen)
        self.assertIn("OPENED", text)
        self.assertNotIn("Dentist", text)
        self.assertNotIn("POST /api/write", hits)
        self.assertFalse(any(x.endswith("/ws") for x in hits))
        self.assertIn("POST /api/write", result["shots"][0]["held"])

    def test_a_section_is_found_by_its_id(self):
        result, sizes, _h, _s = self.capture({"id": "s_far", "press": ""})
        self.assertEqual(result["errors"], [])
        self.assertLess(sizes[0][1], 300)

    def test_an_id_the_page_does_not_have_is_a_sentence(self):
        result, sizes, _h, _s = self.capture({"id": "c_nowhere", "press": ""})
        self.assertEqual(sizes, [])
        self.assertEqual(len(result["errors"]), 1)
        err = result["errors"][0]
        self.assertTrue(err.get("missing"))
        self.assertIn("c_nowhere", err["text"])


if __name__ == "__main__":
    unittest.main()
