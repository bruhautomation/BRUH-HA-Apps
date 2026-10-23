#!/usr/bin/env python3
"""BRUH Bambu Studio's Studio tab on a touch screen (`panel/touchscreen.js`).

The gestures themselves are driven in a browser by
`tests/manual/measure-bambu-studio-mobile.mjs`; what is held here is the
part a browser run against stubs cannot see: that the panel really serves
the script, that the page loads it before the code that calls it, and that
it reaches noVNC and the websocket by relative paths under ingress.
"""
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_panel import RouteTest  # noqa: E402

PANEL = Path(__file__).resolve().parent.parent / "bruh-bambu-studio" / "panel"


class TestTheTouchScreenIsServed(RouteTest):
    def test_the_route_serves_the_script(self):
        async def go():
            resp = await self.http.get("/touchscreen.js")
            return resp.status, resp.headers.get("Content-Type", ""), await resp.text()
        status, kind, body = self.loop.run_until_complete(go())
        self.assertEqual(status, 200)
        self.assertIn("javascript", kind)
        self.assertEqual(body, (PANEL / "touchscreen.js").read_text())


class TestTheTouchScreenIsWired(unittest.TestCase):
    def setUp(self):
        self.page = (PANEL / "index.html").read_text()
        self.js = (PANEL / "touchscreen.js").read_text()

    def test_it_loads_before_the_code_that_calls_it(self):
        self.assertLess(self.page.index('src="touchscreen.js"'), self.page.index('src="app.js"'))

    def test_every_url_is_relative(self):
        """Ingress mounts the panel under a prefix."""
        self.assertEqual(re.findall(r'(?:import|URL)\(\s*["`]/', self.js), [])
        self.assertIn('new URL("novnc/core/", location.href)', self.js)
        # The websocket keeps the page's own directory, so the ingress prefix.
        self.assertIn("location.pathname.replace(/[^/]*$/, \"\")", self.js)
        self.assertIn("websockify", self.js)

    def test_it_only_drives_noVNC_through_what_it_publishes(self):
        """sendKey and DOM events on the canvas; never a private method."""
        self.assertIsNone(re.search(r"\brfb\._|ts\.rfb\._", self.js))

    def test_the_controls_it_binds_are_on_the_page(self):
        for ident in set(re.findall(r'q\("#(\w+)', self.js)):
            self.assertIn(f'id="{ident}"', self.page, ident)

    def test_the_text_box_is_sixteen_pixels(self):
        css = (PANEL / "style.css").read_text()
        rule = re.search(r"#tsType\s*\{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        self.assertIn("font-size: 16px", rule.group(1))


if __name__ == "__main__":
    unittest.main()
