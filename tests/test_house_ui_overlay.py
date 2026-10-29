#!/usr/bin/env python3
"""The house's own layer over brAIn's page (`panel/house_ui.py`).

The owner was promised that YOLO lets brAIn change brAIn's own page, and it
could not: the chat and the terminal run as the `claude` user and the page is
`/opt/panel`, root's and baked into the image, so an edit either failed or
was wiped by the next update. Morph has a house copy; brAIn's page had
nothing. The answer is ADDITIVE and never touches a shipped file: two
optional files in `/config/.brain/ui/` — `house.css`, linked after
`style.css`, and `house.js`, loaded after `app.js` by the shipped
`house-layer.js` in its own script — which survive an update because they
are the house's, and are undone with `brain undo` because every edit under
`/config` is snapshotted.

These drive the real `/` and the real file routes over a live client:
what is linked and where, what is served, what is refused (a link, a file
past the cap), the safe mode (`?nohouse=1`), and that the diagnostics payload
names the files and their sizes without a byte of what they say.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import house_ui  # noqa: E402

from test_todo_list import PanelCase  # noqa: E402

CSS = "/* SENTINEL-CSS */ .topbar { background: hotpink; }\n"
JS = "// SENTINEL-JS\nwindow.__houseRan = true;\n"


class HouseLayerCase(PanelCase):
    def setUp(self):
        super().setUp()
        self.house = tempfile.TemporaryDirectory()
        self.dir = Path(self.house.name) / "ui"
        self._old_dir = house_ui.HOUSE_DIR
        house_ui.HOUSE_DIR = self.dir

    def tearDown(self):
        house_ui.HOUSE_DIR = self._old_dir
        self.house.cleanup()
        super().tearDown()

    def put(self, name: str, text: str) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def page(self, query: str = "") -> str:
        async def body(client):
            res = await client.get("/" + query)
            self.assertEqual(res.status, 200)
            return await res.text()
        return self.drive(body)

    def fetch(self, path: str) -> tuple[int, str, str]:
        async def body(client):
            res = await client.get(path)
            return res.status, res.headers.get("Content-Type", ""), await res.text()
        return self.drive(body)

    @staticmethod
    def meta(html: str) -> dict:
        m = re.search(r'<meta name="brain-house" content="([^"]*)">', html)
        assert m, "the page carries no brain-house meta"
        import html as _h
        return json.loads(_h.unescape(m.group(1)))


class TestNothingThere(HouseLayerCase):
    def test_a_house_with_no_files_gets_the_shipped_page_and_the_loader(self):
        html = self.page()
        self.assertNotIn("house.css", html)
        self.assertNotIn("<!--brain:house-->", html, "the placeholder leaked")
        self.assertEqual(self.meta(html)["files"], [])
        # The loader is shipped and always comes after app.js.
        self.assertLess(html.index('src="app.js'), html.index('src="house-layer.js'))
        status, _ctype, _ = self.fetch("/house.css")
        self.assertEqual(status, 404)

    def test_the_loader_is_served(self):
        status, ctype, text = self.fetch("/house-layer.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", ctype)
        self.assertIn("brain-house", text)


class TestTheLayer(HouseLayerCase):
    def test_house_css_is_linked_after_style_css_and_served(self):
        self.put("house.css", CSS)
        html = self.page()
        self.assertIn('href="house.css?v=', html)
        self.assertLess(html.index('href="style.css'), html.index('href="house.css'))
        status, ctype, text = self.fetch("/house.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ctype)
        self.assertEqual(text, CSS)

    def test_house_js_is_never_a_plain_script_tag_but_is_listed_and_served(self):
        self.put("house.js", JS)
        html = self.page()
        # Loaded by house-layer.js in its own guarded script, never inline
        # in the page where a throw would sit beside the shipped scripts.
        self.assertNotIn('src="house.js', html)
        self.assertNotIn("SENTINEL-JS", html)
        files = {f["name"]: f for f in self.meta(html)["files"]}
        self.assertEqual(files["house.js"]["state"], "ok")
        self.assertEqual(files["house.js"]["bytes"], len(JS.encode()))
        status, ctype, text = self.fetch("/house.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", ctype)
        self.assertEqual(text, JS)

    def test_nohouse_skips_both_and_says_it_is_off(self):
        self.put("house.css", CSS)
        self.put("house.js", JS)
        html = self.page("?nohouse=1")
        self.assertNotIn('href="house.css', html)
        meta = self.meta(html)
        self.assertTrue(meta["off"])
        # Still named, so the notice can say what was skipped.
        self.assertEqual(sorted(f["name"] for f in meta["files"]),
                         ["house.css", "house.js"])

    def test_a_file_past_the_cap_is_neither_linked_nor_served(self):
        self.put("house.css", "a{}" + " " * house_ui.MAX_BYTES)
        html = self.page()
        self.assertNotIn('href="house.css', html)
        files = {f["name"]: f for f in self.meta(html)["files"]}
        self.assertEqual(files["house.css"]["state"], "too_big")
        status, _ctype, _ = self.fetch("/house.css")
        self.assertEqual(status, 404)

    def test_a_link_is_refused_not_followed(self):
        secret = Path(self.house.name) / "secrets.yaml"
        secret.write_text("password: SENTINEL-SECRET\n")
        self.dir.mkdir(parents=True, exist_ok=True)
        os.symlink(secret, self.dir / "house.js")
        html = self.page()
        files = {f["name"]: f for f in self.meta(html)["files"]}
        self.assertEqual(files["house.js"]["state"], "refused")
        status, _ctype, text = self.fetch("/house.js")
        self.assertEqual(status, 404)
        self.assertNotIn("SENTINEL-SECRET", text)

    def test_no_other_name_in_the_folder_is_served(self):
        self.put("other.js", JS)
        status, _ctype, _ = self.fetch("/house.js")
        self.assertEqual(status, 404)
        self.assertNotIn("other.js", self.page())


class TestDiagnostics(HouseLayerCase):
    def test_names_and_sizes_never_contents(self):
        self.put("house.css", CSS)
        self.put("house.js", JS)
        payload = self.server._diagnostics_payload()
        rows = {r["name"]: r for r in payload["house_ui"]["files"]}
        self.assertEqual(rows["house.css"]["bytes"], len(CSS.encode()))
        self.assertEqual(rows["house.js"]["bytes"], len(JS.encode()))
        dumped = json.dumps(payload)
        self.assertNotIn("SENTINEL", dumped)
        self.assertNotIn("hotpink", dumped)


class TestSessionsAreTold(unittest.TestCase):
    """A session that is not told keeps saying it cannot change the page."""

    def test_the_generated_context_names_the_layer_and_undo(self):
        text = (BASE_DIR / "brain" / "scripts" / "ha-context-gen.sh").read_text()
        self.assertIn("/config/.brain/ui/house.css", text)
        self.assertIn("/config/.brain/ui/house.js", text)
        self.assertIn("nohouse=1", text)
        self.assertIn("brain undo", text)

    def test_the_shell_carries_safe_mode_into_its_frame(self):
        shell = (BASE_DIR / "brain" / "custom_components" / "brain" / "morph"
                 / "frontend" / "shell.js").read_text()
        self.assertIn("nohouse", shell)


if __name__ == "__main__":
    unittest.main()
