#!/usr/bin/env python3
"""The chat can photograph any card of Morph's Home page, and knows it can.

The owner asked brAIn to look at the assistant's tile on Home, and the
screenshot tool answered "no card or section called 'c_ov_vesper'": the
harness drew Morph from its shipped modules only (never the house's copies
in use, which is what the Home tab runs), not as the shell's Home tab, and
a room the salience list had folded to a line drew no tiles at all — so a
card in it could not be found, and its section matched only its title line.
And `screenshot_panel` with no arguments listed brAIn's own screens and
never said Morph was there, so the chat concluded it could not photograph
cards. The claims, each driven:

  * the harness serves the house's copy of a module while code.json says it
    is in use, and Morph's own otherwise — the same choice the panel's
    static view makes;
  * the harness draws Morph as brAIn's Home tab (``shell``);
  * a card in a folded room is unfolded and found by its ``data-tile``, by
    the id dashboard.yaml gave it without its ``c_`` too, and a folded
    section photographed by its id carries its tiles;
  * the tool's own listing, with nothing asked, names Morph and its screen,
    and the tool's description says Morph is an ``addon`` to name.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop.harness  # noqa: E402
import devloop.screen_targets as st  # noqa: E402
import devloop.screens as screens  # noqa: E402
from test_devloop_screens import browser, warm_up  # noqa: E402

FRONTEND = BASE_DIR / "brain/custom_components/brain/morph/frontend"


class TestTheHarnessServesWhatHomeRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.shipped = self.tmp / "shipped"
        self.copies = self.tmp / "copies"
        self.shipped.mkdir()
        self.copies.mkdir()
        (self.shipped / "cards.js").write_text("// shipped")
        (self.shipped / "boot.js").write_text("// shipped boot")
        (self.copies / "cards.js").write_text("// the house's copy")
        (self.copies / "boot.js").write_text("// a copied loader")
        self.state = self.tmp / "code.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pick(self, name):
        with mock.patch.object(st, "MORPH_FRONTEND", str(self.shipped)), \
             mock.patch.object(st, "MORPH_CODE_DIR", str(self.copies)), \
             mock.patch.object(st, "MORPH_CODE_STATE", str(self.state)):
            return st.morph_module(name)

    def test_a_copy_in_use_is_what_is_served(self):
        self.state.write_text(json.dumps({"files": [{"name": "cards.js", "status": "active"}]}))
        self.assertEqual(self.pick("cards.js"), str(self.copies / "cards.js"))

    def test_a_paused_copy_or_no_state_is_morphs_own(self):
        self.assertEqual(self.pick("cards.js"), str(self.shipped / "cards.js"))
        self.state.write_text(json.dumps({"files": [{"name": "cards.js", "status": "paused"}]}))
        self.assertEqual(self.pick("cards.js"), str(self.shipped / "cards.js"))
        self.state.write_text("not json")
        self.assertEqual(self.pick("cards.js"), str(self.shipped / "cards.js"))

    def test_the_loader_is_never_a_copy(self):
        self.state.write_text(json.dumps({"files": [{"name": "boot.js", "status": "active"}]}))
        self.assertEqual(self.pick("boot.js"), str(self.shipped / "boot.js"))

    def test_morph_is_drawn_as_brains_home_tab(self):
        page = devloop.harness.page("morph")
        self.assertIn("el.shell = true", page)
        self.assertIn("__harnessReveal", page)


class TestTheToolSaysMorphIsThere(unittest.TestCase):
    def ask(self, body):
        from aiohttp.test_utils import make_mocked_request  # noqa: PLC0415

        import server  # noqa: PLC0415

        async def catalog():
            return {"targets": [{"key": "morph", "product": "Morph", "url": "http://x/",
                                 "guard": True, "reads": [], "screens": [
                                     {"slug": "morph-dashboard", "label": "Morph › Dashboard",
                                      "url": "http://x/", "script": ""}]}],
                    "versions": {"Morph": "4"}, "unreached": {}}

        async def json_body(_r):
            return body

        req = make_mocked_request("POST", "/api/devloop/screenshot")
        with mock.patch.object(server.ownership, "from_loopback", return_value=True), \
             mock.patch.object(server.devloop.screens, "find_browser", return_value="/x"), \
             mock.patch.object(server, "_screen_catalog", catalog), \
             mock.patch.object(server, "_json_body", json_body):
            resp = asyncio.run(server.h_devloop_screenshot(req))
        return resp.status, json.loads(resp.body)

    def test_the_default_listing_names_morph_and_its_screen(self):
        status, body = self.ask({})
        self.assertEqual(status, 200)
        self.assertEqual(body["addon"], "brAIn")
        others = {a["addon"]: a["screens"] for a in body["addons"]}
        self.assertIn("Morph", others)
        self.assertIn("morph-dashboard", others["Morph"])

    def test_the_description_names_morph_as_an_addon(self):
        sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
        import ha_mcp_server  # noqa: PLC0415
        tool = next(t for t in ha_mcp_server.TOOLS if t["name"] == "screenshot_panel")
        self.assertIn('addon "Morph"', tool["description"])
        self.assertIn("Morph", tool["inputSchema"]["properties"]["addon"]["description"])


def _note(cid, text):
    return {"id": cid, "type": "note", "text": text}


# Not skipped where there is no Chromium: the add-on ships one and CI has
# one, and a claim proved nowhere is not proved. BRAIN_CHROMIUM names it.
@pytest.mark.slow
class TestAFoldedTileIsFound(unittest.TestCase):
    """Morph's real modules, served by the real harness routes and captured
    by the real capture, on a house whose overview rooms are folded."""

    def capture(self, focuses):
        import server  # noqa: PLC0415
        os.environ["BRAIN_CHROMIUM"] = browser()
        warm_up(os.environ["BRAIN_CHROMIUM"])
        dash = {"title": "Home", "floors": [
            {"id": "f_overview", "title": "Overview", "sections": [
                {"id": "s_ov_vesper", "title": "Vesper", "color": "violet", "width": 2,
                 "groups": [{"cards": [_note("c_ov_vesper", "VESPER TILE")]}]},
                {"id": "s_ov_now", "title": "Now", "color": "sand", "width": 2,
                 "groups": [{"cards": [_note("c_ov_now", "NOW TILE")]}]}]},
            {"id": "f_down", "title": "Downstairs", "sections": [
                {"id": "s_hall", "title": "Hall", "color": "teal", "width": 2,
                 "groups": [{"cards": [{"id": "c_hall", "type": "light",
                                        "entity": "light.hall"}]}]}]}]}
        load = {"mirror": {"revision": "r1", "dashboard": dash, "problems": [],
                           "card_modules": []},
                "state": {}, "brain": {}, "admin": True,
                "now": 1.7e9, "code": "", "integration": "x"}
        states = [{"entity_id": "light.hall", "state": "off",
                   "attributes": {"friendly_name": "Hall"}}]

        async def fake(session, commands, **kw):
            kind = commands[0]["type"]
            if kind == "get_states":
                return [{"ok": True, "result": states}]
            if kind == "morph/load":
                return [{"ok": True, "result": load}]
            return [{"ok": True, "result": {} if kind == "get_config" else []}]

        seen: list[str] = []

        async def look(cdp, session):
            r = await cdp.call("Runtime.evaluate", {"expression": (
                "(() => { const p = document.querySelector('morph-panel');"
                " return p && p.shadowRoot ? p.shadowRoot.textContent : ''; })()"),
                "returnByValue": True}, session)
            seen.append(r["result"]["value"])

        from aiohttp import web  # noqa: PLC0415

        async def run(out: Path):
            app = web.Application()
            app.router.add_get("/devloop/harness/morph/{name}", server.h_harness_morph)
            app.router.add_get("/devloop/harness/ws", server.h_harness_ws)
            app.router.add_get("/devloop/harness/{name}", server.h_harness_page)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            target = st.harness_targets(f"http://127.0.0.1:{port}/", {"Morph": "1"})[0]
            scr = target["screens"][0]
            target["screens"] = [{**scr, "focus": f} for f in focuses]
            try:
                return await screens.capture(
                    out, confidential=[], aliases=None, own=False, targets=[target],
                    views=[(1200, 800, False, "light")])
            finally:
                await runner.cleanup()

        old = screens.AFTER_REDACT
        screens.AFTER_REDACT = look
        tmp = tempfile.mkdtemp()
        empty = tempfile.mkdtemp()
        try:
            with mock.patch("ha_data._ws_calls", fake), \
                 mock.patch.object(st, "MORPH_FRONTEND", str(FRONTEND)), \
                 mock.patch.object(st, "MORPH_CODE_DIR", empty), \
                 mock.patch.object(st, "MORPH_CODE_STATE", os.path.join(empty, "code.json")):
                result = asyncio.run(asyncio.wait_for(run(Path(tmp)), 180))
        finally:
            screens.AFTER_REDACT = old
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(empty, ignore_errors=True)
        return result, seen

    def test_a_tile_in_a_folded_room_is_photographed(self):
        result, seen = self.capture([{"id": "c_ov_vesper", "press": ""},
                                     {"id": "ov_now", "press": ""},
                                     {"id": "s_ov_vesper", "press": ""}])
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["shots"]), 3)
        self.assertIn("VESPER TILE", seen[0])
        self.assertIn("NOW TILE", seen[1])
        self.assertIn("VESPER TILE", seen[2])


if __name__ == "__main__":
    unittest.main()
