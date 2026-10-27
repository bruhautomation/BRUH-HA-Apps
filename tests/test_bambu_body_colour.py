#!/usr/bin/env python3
"""A body's colour, chosen by the person on the Design tab's key.

The colour a body is drawn in is the colour it is meant to print in: the
plan offers the AMS tray closest to it, a print started without naming a
tray takes that tray, and Open in Bambu Studio names a filament of that
colour. So a colour picked from the dot on a body's pill is stored on the
part (`body_colours`), wins over the script's COLORS wherever a body's colour
is read (`parts.body_colours`, `server._body_colours`), is told to brAIn on
its next turn so the next version's COLORS carries it, and stands down the
moment brAIn writes a different colour for that body itself.
"""
import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import test_bambu_design_printing as printing  # noqa: E402

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

# The modules the printing tests patch, not a second load of them.
server, parts, designer = printing.server, printing.parts, printing.designer


class TestTheColourAPersonChose(printing.PrintTest):
    def setUp(self):
        super().setUp()
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.http = TestClient(TestServer(server.build_app(self.panel, ticker=False)), loop=self.loop)
        self.loop.run_until_complete(self.http.start_server())
        self.addCleanup(lambda: self.loop.run_until_complete(self.http.close()))

    def call(self, method, path, **kw):
        async def go():
            resp = await self.http.request(method, path, **kw)
            return resp.status, await resp.json()
        return self.loop.run_until_complete(go())

    def choose(self, part, colours):
        return self.call("POST", f"/api/design/parts/{part['id']}", json={"body_colours": colours})

    def test_a_chosen_colour_is_stored_and_moves_the_tray_offered(self):
        part = self.part()
        status, body = self.choose(part, {"Cube": "#ffffff"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["part"]["body_colours"]["Cube"]["colour"], "#FFFFFF")
        # The script said #111111 when the person chose; that is what it overrode.
        self.assertEqual(body["part"]["body_colours"]["Cube"]["over"], "#111111")
        status, plan = self.call("GET", f"/api/design/parts/{part['id']}/plan")
        self.assertEqual(status, 200, plan)
        self.assertEqual({b["name"]: (b["colour"], b["recommended_slot"]) for b in plan["bodies"]},
                         {"Cube": ("#FFFFFF", 0), "Logo": ("#FFFFFF", 0)})

    def test_a_print_with_no_tray_named_takes_the_chosen_colour(self):
        part = self.part()
        # The script's black cube would take the black tray (AMS 2); chosen
        # white, it shares the white tray with the logo: one filament.
        self.choose(part, {"Cube": "#FFFFFF"})
        server.start_design_print(self.panel, part["id"], slots={"Logo": 0})
        self.wait_sent()
        self.assertEqual(self.sent[0]["body"]["ams_mapping"], [0])

    def test_null_puts_the_scripts_colour_back(self):
        part = self.part()
        self.choose(part, {"Cube": "#FFFFFF"})
        status, body = self.choose(part, {"Cube": None})
        self.assertEqual(status, 200, body)
        self.assertNotIn("Cube", body["part"].get("body_colours") or {})
        self.assertEqual(server._body_colours(parts.load(part["id"]), part["versions"][0], ["Cube"]),
                         {"Cube": "#111111"})

    def test_what_is_not_a_colour_or_a_name_is_refused(self):
        part = self.part()
        for bad in ({"Cube": "blue-ish"}, {"Cube": 12}, {"": "#FFFFFF"}, {"x" * 81: "#FFFFFF"},
                    ["Cube"], "Cube"):
            with self.subTest(bad=bad):
                status, _ = self.choose(part, bad)
                self.assertEqual(status, 400)
        self.assertFalse(parts.load(part["id"]).get("body_colours"))


class TestBrainHearsOfIt(printing.PrintTest):
    def test_the_next_turn_is_told_the_colours_chosen(self):
        part = self.part()
        parts.set_body_colour(part, "Logo", "#E0569B")
        prompt = designer._turn_prompt(part, "make it taller")
        self.assertIn("Logo", prompt)
        self.assertIn("#E0569B", prompt)
        self.assertIn("COLORS", prompt)

    def test_a_colour_brain_changes_itself_ends_the_choice(self):
        part = self.part()
        parts.set_body_colour(part, "Cube", "#FFFFFF")
        parts.set_body_colour(part, "Logo", "#E0569B")
        # brAIn's next version keeps Logo as it was and makes the cube blue.
        parts.settle_body_colours(part, {"Cube": "#1E9FE0", "Logo": "#FFFFFF"})
        self.assertNotIn("Cube", part["body_colours"])
        self.assertEqual(part["body_colours"]["Logo"]["colour"], "#E0569B")
        # Writing the chosen colour into COLORS is brAIn adopting it: the
        # choice has done its job and the script carries it from now on.
        parts.settle_body_colours(part, {"Logo": "#E0569B"})
        self.assertNotIn("Logo", part["body_colours"])


if __name__ == "__main__":
    unittest.main()
