#!/usr/bin/env python3
"""The panel's routes, driven through a real aiohttp server.

The stores and the renderer are real; only the USB write is stood in for,
because there is no bus here. That line is drawn deliberately at the bulk
endpoint: everything above it — which roll a job goes to, whether it is
refused, what the history records, what the raster bytes say — is the code
that ships, and the roll-select byte is asserted on the payload that would
have been written.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import bruh_print_env  # noqa: E402

dymo_printers, protocol, usb_link, server = bruh_print_env.load(
    "dymo.printers", "dymo.protocol", "dymo.usb_link", "server")


class PanelCase(unittest.IsolatedAsyncioTestCase):
    """One panel, one stand-in Twin Turbo, one recorded print."""

    TWIN = True

    async def asyncSetUp(self):
        self.data = Path(tempfile.mkdtemp())
        # A shared folder whose PARENT does not exist, so the mirror is
        # skipped exactly as it is on a dev checkout with no /config.
        server.SHARED = Path(tempfile.mkdtemp()) / "no-config" / ".bruh_print"

        self.sent = []
        self._real_send = usb_link.send
        usb_link.send = self._record

        self.panel = server.Panel(self.data)
        product = 0x0022 if self.TWIN else 0x0020
        self.printer = dymo_printers.Discovered(
            product, dymo_printers.MODELS[product], serial="S1")
        self.panel.discover = lambda force=False: [self.printer]

        self.client = TestClient(TestServer(server.build_app(self.panel)))
        await self.client.start_server()

    async def asyncTearDown(self):
        usb_link.send = self._real_send
        await self.client.close()

    def _record(self, payload, key=None):
        self.sent.append(payload)
        return {"bytes": len(payload), "printer": {}, "status": "ready",
                "status_ok": True, "status_answered": True}

    # -- helpers ----------------------------------------------------------
    async def get(self, path):
        response = await self.client.get(path)
        return response.status, await response.json()

    async def post(self, path, payload=None):
        response = await self.client.post(path, json=payload or {})
        return response.status, await response.json()

    def label(self, stock="edcc-082wh", text="X"):
        return {"stock": stock, "elements": [
            {"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 40, "h_mm": 20,
             "props": {"text": text}}]}


class TestHealthAndState(PanelCase):
    async def test_health_never_touches_usb(self):
        """A health check that walks the bus reports a printer being
        unplugged as the add-on being broken, and the watchdog restarts a
        perfectly good panel because somebody moved the LabelWriter."""
        def explode(*_args, **_kwargs):
            raise AssertionError("/api/health touched the USB bus")
        self.panel.discover = explode
        status, body = await self.get("/api/health")
        self.assertEqual(200, status)
        self.assertTrue(body["ok"])

    async def test_state_carries_everything_the_ui_opens_with(self):
        status, body = await self.get("/api/state")
        self.assertEqual(200, status)
        for key in ("printer", "rolls", "stocks", "templates", "settings",
                    "fonts", "catalog", "history"):
            self.assertIn(key, body)

    async def test_the_two_rolls_on_the_machine_are_in_the_catalog(self):
        _, body = await self.get("/api/stocks")
        skus = {s["sku"] for s in body["stocks"]}
        self.assertIn("EDCC-082WH", skus)
        self.assertIn("ED1F-060WH", skus)


class TestRollRouting(PanelCase):
    async def test_a_job_goes_to_the_bay_holding_its_stock(self):
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        await self.post("/api/roll/right", {"stock": "edcc-082wh"})
        status, body = await self.post("/api/print", {"label": self.label()})
        self.assertEqual(200, status)
        self.assertEqual("right", body["side"])

    async def test_the_roll_select_byte_reaches_the_printer(self):
        """The Twin Turbo's whole point. Asserted on the bytes rather than
        on the response, because the response would say "right" either
        way."""
        await self.post("/api/roll/right", {"stock": "edcc-082wh"})
        await self.post("/api/print", {"label": self.label()})
        self.assertTrue(self.sent[-1].startswith(
            protocol.select_roll(protocol.ROLL_RIGHT)))

    async def test_a_mismatched_roll_is_refused_with_both_names_in_it(self):
        """The refusal is the feature: without it a run of fifty prints a
        2.25" raster across a 0.56" liner fifty times, with no error
        anywhere."""
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        status, body = await self.post(
            "/api/print", {"label": self.label(), "side": "left"})
        self.assertEqual(409, status)
        self.assertIn("Cryogenic Labels", body["error"])
        self.assertIn("Chemical-Resistant", body["error"])
        self.assertEqual([], self.sent, "it printed anyway")

    async def test_no_roll_holds_it_and_something_is_loaded_is_a_refusal(self):
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        status, _ = await self.post("/api/print", {"label": self.label()})
        self.assertEqual(409, status)

    async def test_an_unknown_printer_state_prints_with_a_warning(self):
        """Nothing loaded is not knowing, and refusing everything until
        somebody fills a form in is a panel that cannot print on day one."""
        status, body = await self.post("/api/print", {"label": self.label()})
        self.assertEqual(200, status)
        self.assertEqual("left", body["side"])
        self.assertTrue(any("does not know" in n for n in body["notes"]))

    async def test_stock_checking_can_be_turned_off(self):
        await self.post("/api/settings", {"enforce_stock": False})
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        status, body = await self.post(
            "/api/print", {"label": self.label(), "side": "left"})
        self.assertEqual(200, status)
        self.assertTrue(any("Printing anyway" in n for n in body["notes"]))

    async def test_a_bay_that_does_not_exist_is_refused(self):
        status, _ = await self.post(
            "/api/print", {"label": self.label(), "side": "middle"})
        self.assertEqual(409, status)


class TestSingleRollPrinter(PanelCase):
    TWIN = False

    async def test_no_roll_byte_is_sent_to_a_printer_with_one_roll(self):
        """Sending it and calling that "printing on the left" would be the
        panel repeating a lie about what it did."""
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})
        await self.post("/api/print", {"label": self.label()})
        self.assertNotIn(bytes([0x1B, ord("q")]), self.sent[-1])


class TestPrinting(PanelCase):
    async def test_copies_reach_the_printer_and_the_estimate(self):
        await self.post("/api/roll/left",
                        {"stock": "edcc-082wh", "remaining": 100})
        status, body = await self.post(
            "/api/print", {"label": self.label(), "copies": 5})
        self.assertEqual(200, status)
        self.assertEqual(5, body["printed"])
        self.assertEqual(4, self.sent[-1].count(protocol.short_form_feed()))
        _, state = await self.get("/api/state")
        left = next(r for r in state["rolls"] if r["side"] == "left")
        self.assertEqual(95, left["remaining"])

    async def test_the_estimate_never_goes_negative(self):
        """A negative count is the panel reporting a state that cannot
        exist; the estimate is already the soft number here."""
        await self.post("/api/roll/left",
                        {"stock": "edcc-082wh", "remaining": 2})
        await self.post("/api/print", {"label": self.label(), "copies": 50})
        _, state = await self.get("/api/state")
        left = next(r for r in state["rolls"] if r["side"] == "left")
        self.assertEqual(0, left["remaining"])

    async def test_a_usb_failure_comes_back_as_a_sentence(self):
        def refuse(*_args, **_kwargs):
            raise usb_link.PrinterBusy("The lid is open.")
        usb_link.send = refuse
        status, body = await self.post("/api/print", {"label": self.label()})
        self.assertEqual(409, status)
        self.assertEqual("The lid is open.", body["error"])

    async def test_a_failed_print_is_not_written_to_the_history(self):
        """A row with a Reprint button on something that never became a
        label."""
        def refuse(*_args, **_kwargs):
            raise usb_link.PrinterNotFound("Not plugged in.")
        usb_link.send = refuse
        await self.post("/api/print", {"label": self.label()})
        _, body = await self.get("/api/history")
        self.assertEqual([], body["history"])

    async def test_reprint_sends_the_same_bytes(self):
        """The vial came out of the freezer with a torn label; they need
        THAT label, not a similar one."""
        await self.post("/api/print", {"label": self.label(text="Sample 9912")})
        first = self.sent[-1]
        _, history = await self.get("/api/history")
        entry = history["history"][0]
        status, _ = await self.post(f"/api/history/{entry['id']}/reprint")
        self.assertEqual(200, status)
        self.assertEqual(first, self.sent[-1])

    async def test_a_reprint_is_a_new_row_not_an_edit(self):
        """"Printed twice" is a fact about the roll, and the estimate
        depends on it."""
        await self.post("/api/print", {"label": self.label()})
        _, history = await self.get("/api/history")
        await self.post(f"/api/history/{history['history'][0]['id']}/reprint")
        _, after = await self.get("/api/history")
        self.assertEqual(2, len(after["history"]))
        self.assertEqual("reprint", after["history"][0]["source"])

    async def test_the_preview_is_the_same_render_as_the_print(self):
        response = await self.client.post(
            "/api/preview", json={"label": self.label()})
        self.assertEqual(200, response.status)
        self.assertEqual("image/png", response.content_type)
        self.assertEqual("672x375", response.headers["X-Label-Dots"])
        self.assertIsInstance(
            json.loads(response.headers["X-Label-Notes"]), list)

    async def test_nothing_is_printed_by_a_preview(self):
        await self.client.post("/api/preview", json={"label": self.label()})
        self.assertEqual([], self.sent)


class TestQuick(PanelCase):
    async def test_a_word_previews_without_printing(self):
        status, body = await self.post("/api/quick", {"text": "Buffer A"})
        self.assertEqual(200, status)
        self.assertTrue(body["png"].startswith("data:image/png;base64,"))
        self.assertEqual(["Buffer", "A"], body["fit"]["lines"])
        self.assertEqual([], self.sent)

    async def test_the_same_call_prints_when_asked(self):
        status, body = await self.post(
            "/api/quick", {"text": "Buffer A", "print": True})
        self.assertEqual(200, status)
        self.assertEqual(1, body["printed"])
        self.assertEqual(1, len(self.sent))

    async def test_narrow_stock_turns_the_text_along_the_roll(self):
        """A wrap-around vial label reads along the tube. Not guessing means
        the cryo wrap's first quick print is always wrong."""
        _, body = await self.post("/api/quick",
                                  {"text": "HEK293T", "stock": "ed1f-060wh"})
        self.assertEqual(90, body["label"]["rotate"])

    async def test_the_guess_can_be_overridden(self):
        _, body = await self.post(
            "/api/quick",
            {"text": "HEK293T", "stock": "ed1f-060wh", "rotate": 0})
        self.assertEqual(0, body["label"]["rotate"])

    async def test_an_unknown_stock_is_a_404_that_names_what_is_known(self):
        status, body = await self.post(
            "/api/quick", {"text": "x", "stock": "not-a-stock"})
        self.assertEqual(404, status)
        self.assertIn("edcc-082wh", body["error"])


class TestTemplates(PanelCase):
    TEMPLATE = {
        "name": "Cryo vial",
        "label": {"stock": "edcc-082wh", "elements": [
            {"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 40, "h_mm": 12,
             "props": {"text": "{{sample}} — {{date}}"}},
            {"type": "barcode", "x_mm": 1, "y_mm": 14, "w_mm": 50, "h_mm": 12,
             "props": {"data": "{{sample}}"}}]},
    }

    async def save(self):
        _, body = await self.post("/api/template", self.TEMPLATE)
        return body["template"]

    async def test_fields_come_from_the_label_not_from_the_request(self):
        """The placeholders in the document are the truth about what a
        template needs; a declared field that no longer appears is a box on
        the form that fills nothing."""
        template = await self.save()
        self.assertEqual(["sample"], [f["key"] for f in template["fields"]])

    async def test_date_fills_itself_in(self):
        template = await self.save()
        status, body = await self.post(
            f"/api/template/{template['id']}/print", {"fields": {"sample": "9912"}})
        self.assertEqual(200, status)
        self.assertEqual([], body["missing"])

    async def test_an_empty_field_refuses_rather_than_printing_a_gap(self):
        """The panel warns and this refuses, deliberately: the panel has
        somebody looking at the preview, and this call is usually an
        automation about to print fifty labels with a hole in them."""
        template = await self.save()
        status, body = await self.post(f"/api/template/{template['id']}/print")
        self.assertEqual(422, status)
        self.assertEqual(["sample"], body["missing"])
        self.assertEqual([], self.sent)

    async def test_a_template_can_be_printed_by_name(self):
        """The name is what an automation types, and it is not
        case-sensitive because nobody remembers the capitals."""
        await self.save()
        status, _ = await self.post(
            "/api/template/cryo vial/print", {"fields": {"sample": "9912"}})
        self.assertEqual(200, status)

    async def test_an_unknown_template_names_the_ones_that_exist(self):
        await self.save()
        status, body = await self.post("/api/template/Nope/print")
        self.assertEqual(404, status)
        self.assertIn("Cryo vial", body["error"])

    async def test_the_preview_reports_what_is_still_empty(self):
        template = await self.save()
        _, body = await self.post(f"/api/template/{template['id']}/preview")
        self.assertEqual(["sample"], body["missing"])
        self.assertTrue(body["png"].startswith("data:image/png"))

    async def test_a_placeholder_never_reaches_the_label(self):
        """A label that prints its own template syntax is worse than one
        with a gap — the gap is obvious and the braces look deliberate."""
        template = await self.save()
        _, body = await self.post(f"/api/template/{template['id']}/preview")
        text = body["label"]["elements"][0]["props"]["text"]
        self.assertNotIn("{{", text)


class TestStocks(PanelCase):
    async def test_swapping_a_stock_exchanges_its_measurements(self):
        """The fix for the single most common label failure: a label that
        comes out sideways has its two numbers the wrong way round."""
        _, body = await self.post("/api/stock/ed1f-060wh/swap")
        swapped = next(s for s in body["stocks"] if s["id"] == "ed1f-060wh")
        self.assertEqual(3.44, swapped["across_in"])
        self.assertEqual(0.56, swapped["feed_in"])

    async def test_an_edited_builtin_survives_a_reload(self):
        """A future release correcting a built-in must not undo somebody's
        own measurement."""
        await self.post("/api/stock/ed1f-060wh/swap")
        reloaded = server.Panel(self.data)
        self.assertEqual(3.44, reloaded.stocks.require("ed1f-060wh").across_in)

    async def test_a_stock_that_is_loaded_cannot_be_deleted(self):
        """The panel would be checking labels against a stock it no longer
        has."""
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})
        response = await self.client.delete("/api/stock/edcc-082wh")
        self.assertEqual(409, response.status)

    async def test_a_stock_needs_a_positive_width_across_the_head(self):
        status, body = await self.post(
            "/api/stock", {"name": "Bad", "across_in": 0, "feed_in": 2})
        self.assertEqual(400, status)
        self.assertIn("across", body["error"])

    async def test_the_ruler_prints_something_measurable(self):
        status, body = await self.post("/api/printer/test", {})
        self.assertEqual(200, status)
        self.assertEqual(1, len(self.sent))
        self.assertTrue(self.sent[0].endswith(protocol.form_feed()))


class TestFailureShapes(PanelCase):
    async def test_every_error_is_json_with_a_sentence_in_it(self):
        """An aiohttp HTTPException renders as an HTML page by default, and
        an HTML page reaching the bridge is an automation trace that says
        <!DOCTYPE html>."""
        response = await self.client.post("/api/template/nope/print", json={})
        self.assertEqual("application/json", response.content_type)
        self.assertIn("error", await response.json())

    async def test_a_body_that_is_not_json_says_so(self):
        response = await self.client.post(
            "/api/print", data="not json",
            headers={"Content-Type": "application/json"})
        self.assertEqual(400, response.status)
        body = await response.json()
        self.assertIn("not JSON", body["error"])

    async def test_a_label_with_no_stock_says_which_field_is_missing(self):
        status, body = await self.post("/api/print", {"label": {"elements": []}})
        self.assertEqual(400, status)
        self.assertIn("stock", body["error"])


class TestMirror(unittest.TestCase):
    """The file Home Assistant actually reads."""

    def setUp(self):
        self.data = Path(tempfile.mkdtemp())
        self.shared = Path(tempfile.mkdtemp()) / ".bruh_print"
        self._real = server.SHARED
        server.SHARED = self.shared

    def tearDown(self):
        server.SHARED = self._real

    def test_it_publishes_what_the_sensors_need(self):
        panel = server.Panel(self.data)
        panel.discover = lambda force=False: []
        panel.rolls.load_roll("left", "edcc-082wh", count=1000)
        panel.mirror_state()
        payload = json.loads((self.shared / "state.json").read_text())
        self.assertEqual("edcc-082wh", payload["rolls"]["left"]["stock"])
        self.assertIn("edcc-082wh", payload["stocks"])
        self.assertIn("printed_today", payload)

    def test_a_dev_checkout_with_no_config_grows_no_stray_folder(self):
        server.SHARED = Path(tempfile.mkdtemp()) / "no-config" / ".bruh_print"
        panel = server.Panel(self.data)
        panel.discover = lambda force=False: []
        panel.mirror_state()
        self.assertFalse(server.SHARED.exists())


if __name__ == "__main__":
    unittest.main()
