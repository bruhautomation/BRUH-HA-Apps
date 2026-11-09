#!/usr/bin/env python3
"""The integration's services, driven through the add-on's bridge into a
real panel.

The bridge is what every service call goes through — `print_label` in
brAIn, an automation, the Lovelace card — and it maps a service onto one of
the panel's routes. A route that answers 200 without printing is the worst
mapping it can make: the call succeeds, the caller reads `printed: 0` with
nothing to say why, and no label comes out (#783, where `print_text` was
pointed at the Quick tab's PREVIEW). So these tests stand the panel up for
real and ask the printer, not the mapping, whether a label was sent.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from test_bruh_print_panel import PanelCase  # noqa: E402

BRIDGE = (Path(__file__).resolve().parent.parent / "bruh-print"
          / "integrations" / "ha-bridge.py")


def load_bridge(name):
    spec = importlib.util.spec_from_file_location(name, BRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BridgeCase(PanelCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bridge = load_bridge(f"bruh_print_bridge_{id(self)}")
        self.bridge.PANEL_URL = str(self.client.make_url("")).rstrip("/")

    async def call(self, kind, payload=None):
        return await self.bridge.handle({"kind": kind, "payload": payload or {}})


class TestEveryPrintServicePrints(BridgeCase):
    async def test_print_text_prints_on_the_loaded_stock(self):
        """#783: "print three labels … lesson 16, 17 and 20" came back
        `printed: 0` three times and nothing printed."""
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        answer = await self.call("print_text", {"text": "Lesson 16"})
        self.assertNotEqual(False, answer.get("ok"), answer)
        self.assertGreaterEqual(answer.get("printed", 0), 1, answer)
        self.assertEqual("left", answer.get("side"))
        self.assertEqual(1, len(self.sent), "no job reached the printer")
        status = await self.call("get_status")
        self.assertEqual("Lesson 16", status["recent"][0]["title"])

    async def test_copies_and_a_named_stock_are_honoured(self):
        """A second shape of the same call: a stock named, several copies."""
        await self.post("/api/roll/right", {"stock": "edcc-082wh"})
        answer = await self.call(
            "print_text", {"text": "Spare keys", "stock": "edcc-082wh",
                           "copies": 2})
        self.assertEqual(2, answer.get("printed"), answer)
        self.assertEqual("right", answer.get("side"))
        self.assertEqual(1, len(self.sent))


class TestANothingPrintedAlwaysSaysWhy(BridgeCase):
    """Whatever the route, an answer with nothing printed carries a reason:
    `{"printed": 0, "notes": []}` is a caller told nothing happened and
    nothing about why, which is how #783 went unexplained."""

    PRINTS = ("print_text", "print_template", "print_label", "reprint",
              "print_test")

    async def test_every_print_kind_explains_a_zero(self):
        self.assertTrue(set(self.PRINTS) <= set(self.bridge.ROUTES))
        self.bridge._forward = lambda method, path, payload: {"ok": True}
        for kind in self.PRINTS:
            with self.subTest(kind=kind):
                answer = await self.call(kind, {"text": "x", "template": "t",
                                                "entry": "e", "label": {}})
                self.assertEqual(0, answer.get("printed", 0))
                self.assertTrue(answer.get("notes"), answer)

    async def test_notes_about_the_label_do_not_stand_in_for_the_reason(self):
        """A preview carries the label's own notes (a clipped column), and
        those said nothing about why no label came out."""
        self.bridge._forward = lambda method, path, payload: {
            "ok": True, "notes": ["3 dot columns are clipped."]}
        answer = await self.call("print_text", {"text": "x"})
        self.assertIn("Nothing was printed", answer["notes"][0])
        self.assertEqual("3 dot columns are clipped.", answer["notes"][1])

    async def test_a_label_that_printed_gets_no_extra_note(self):
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        answer = await self.call("print_text", {"text": "Chili"})
        self.assertFalse(any("nothing" in n.lower() for n in answer["notes"]),
                         answer["notes"])


class TestANumberedTemplateTakesItsNumber(BridgeCase):
    """#784: "I have a label template called lessons. Can you please print
    lesson 29?" The template's text was a fixed `Lesson 16`, so it had no
    fields to give, and the `lesson` field brAIn sent was dropped without a
    word — the label that came out was lesson 16."""

    def template(self, name, text, data=None):
        elements = [{"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 40,
                     "h_mm": 12, "props": {"text": text}}]
        if data is not None:
            elements.append({"type": "qr", "x_mm": 42, "y_mm": 1, "w_mm": 12,
                             "h_mm": 12, "props": {"data": data}})
        return {"name": name, "label": {"stock": "edcc-082wh",
                                        "elements": elements}}

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})

    async def fields_of(self, name):
        status = await self.call("get_status")
        return next(t["fields"] for t in status["templates"] if t["name"] == name)

    async def test_the_number_is_a_field_and_prints_what_is_asked(self):
        await self.post("/api/template", self.template("Lessons", "Lesson 16"))
        self.assertEqual(["number"], await self.fields_of("Lessons"))
        answer = await self.call("print_template", {
            "template": "Lessons", "fields": {"number": "29"}})
        self.assertEqual(1, answer.get("printed"), answer)
        status = await self.call("get_status")
        self.assertEqual("Lesson 29", status["recent"][0]["title"])

    async def test_left_alone_it_prints_the_number_it_was_saved_with(self):
        await self.post("/api/template", self.template("Lessons", "Lesson 16"))
        answer = await self.call("print_template", {"template": "Lessons"})
        self.assertEqual(1, answer.get("printed"), answer)
        status = await self.call("get_status")
        self.assertEqual("Lesson 16", status["recent"][0]["title"])

    async def test_the_same_number_in_a_code_changes_with_it(self):
        """A second shape the issue never had: the number is in the text
        AND in the QR code beside it, and both are the same fact."""
        await self.post("/api/template",
                        self.template("Drawer", "Freezer drawer 2", data="2"))
        self.assertEqual(["number"], await self.fields_of("Drawer"))
        _, body = await self.post("/api/template/Drawer/preview",
                                  {"fields": {"number": "5"}})
        props = [e["props"] for e in body["label"]["elements"]]
        self.assertEqual("Freezer drawer 5", props[0]["text"])
        self.assertEqual("5", props[1]["data"])

    async def test_two_different_numbers_are_not_guessed_between(self):
        await self.post("/api/template", self.template("Box", "Box 3 of 12"))
        self.assertEqual([], await self.fields_of("Box"))

    async def test_a_template_with_its_own_fields_is_left_as_it_was(self):
        await self.post("/api/template",
                        self.template("Bag", "Bag 4 {{contents}}"))
        self.assertEqual(["contents"], await self.fields_of("Bag"))


class TestAFieldTheTemplateDoesNotHaveIsSaid(BridgeCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})

    async def save(self, name, text):
        await self.post("/api/template", {"name": name, "label": {
            "stock": "edcc-082wh", "elements": [
                {"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 40,
                 "h_mm": 12, "props": {"text": text}}]}})

    async def test_an_unknown_field_is_refused_with_the_ones_it_takes(self):
        await self.save("Lessons", "Lesson 16")
        answer = await self.call("print_template", {
            "template": "Lessons", "fields": {"lesson": "29"}})
        self.assertIs(False, answer.get("ok"), answer)
        self.assertIn("lesson", answer["error"])
        self.assertIn("number", answer["error"])
        self.assertEqual([], self.sent)

    async def test_the_same_for_a_template_with_placeholders(self):
        await self.save("Freezer bag", "{{contents}}")
        answer = await self.call("print_template", {
            "template": "Freezer bag",
            "fields": {"contents": "Chili", "colour": "red"}})
        self.assertIs(False, answer.get("ok"), answer)
        self.assertIn("colour", answer["error"])
        self.assertEqual([], self.sent)

    async def test_the_date_is_always_a_field(self):
        await self.save("Freezer bag", "{{contents}} {{date}}")
        answer = await self.call("print_template", {
            "template": "Freezer bag",
            "fields": {"contents": "Chili", "date": "2026-11-09"}})
        self.assertEqual(1, answer.get("printed"), answer)

    async def test_with_fields_not_required_it_is_a_note(self):
        await self.save("Freezer bag", "{{contents}}")
        status, body = await self.post("/api/template/Freezer bag/print", {
            "fields": {"contents": "Chili", "colour": "red"},
            "require_fields": False})
        self.assertEqual(200, status, body)
        self.assertTrue(any("colour" in n for n in body["notes"]), body["notes"])


if __name__ == "__main__":
    unittest.main()
