#!/usr/bin/env python3
"""The panel's routes, driven through a real aiohttp server.

The stores and the renderer are real; only the USB write is stood in for,
because there is no bus here. That line is drawn deliberately at the bulk
endpoint: everything above it — which roll a job goes to, whether it is
refused, what the history records, what the raster bytes say — is the code
that ships, and the roll-select byte is asserted on the payload that would
have been written.
"""
import io
import json
import logging
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

PANEL_DIR = (Path(__file__).resolve().parent.parent
             / "bruh-print" / "panel")

from aiohttp.test_utils import (  # noqa: E402
    TestClient, TestServer, make_mocked_request,
)

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
        # After the sync run that opens every document, and before anything
        # about a label: the bay is the document's and the geometry is the
        # page's, which is DYMO's own driver's split.
        self.assertTrue(self.sent[-1].startswith(
            protocol.sync_run() + protocol.select_roll(protocol.ROLL_RIGHT)))

    async def test_the_byte_on_the_wire_is_the_manuals_ASCII_digit(self):
        """`ESC q` takes ASCII '1'/'2', which is what the reference spells
        out for this one command; the add-on sent `0x01`/`0x02` from memory.
        A printer that does not take those ignores the command and prints on
        whichever bay it used last — which, on this machine, means a 2.25"
        raster on a 0.56" wrap. Asserted as the literal byte rather than
        through `select_roll`, because a helper compared against itself
        would agree either way."""
        for side, wire, stale in (("left", 0x31, protocol.ROLL_LEFT),
                                  ("right", 0x32, protocol.ROLL_RIGHT)):
            with self.subTest(side=side):
                await self.post(f"/api/roll/{side}", {"stock": "edcc-082wh"})
                await self.post("/api/print",
                                {"label": self.label(), "side": side})
                payload = self.sent[-1]
                self.assertTrue(
                    payload.startswith(
                        protocol.sync_run() + bytes([0x1B, ord("q"), wire])),
                    payload[protocol.SYNC_ESCAPES:][:6])
                self.assertNotIn(bytes([0x1B, ord("q"), stale]), payload)

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
        """The box came out of the loft with a torn label; they need
        THAT label, not a similar one."""
        await self.post("/api/print", {"label": self.label(text="Winter coats")})
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
        status, body = await self.post("/api/quick", {"text": "Spare keys"})
        self.assertEqual(200, status)
        self.assertTrue(body["png"].startswith("data:image/png;base64,"))
        self.assertEqual(["Spare", "keys"], body["fit"]["lines"])
        self.assertEqual([], self.sent)

    async def test_the_same_call_prints_when_asked(self):
        status, body = await self.post(
            "/api/quick", {"text": "Spare keys", "print": True})
        self.assertEqual(200, status)
        self.assertEqual(1, body["printed"])
        self.assertEqual(1, len(self.sent))

    async def test_narrow_stock_turns_the_text_along_the_roll(self):
        """A wrap-around label reads along the tube or cable it wraps.
        Not guessing means
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
        "name": "Freezer bag",
        "label": {"stock": "edcc-082wh", "elements": [
            {"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 40, "h_mm": 12,
             "props": {"text": "{{contents}} — {{date}}"}},
            {"type": "barcode", "x_mm": 1, "y_mm": 14, "w_mm": 50, "h_mm": 12,
             "props": {"data": "{{contents}}"}}]},
    }

    async def save(self):
        _, body = await self.post("/api/template", self.TEMPLATE)
        return body["template"]

    async def test_fields_come_from_the_label_not_from_the_request(self):
        """The placeholders in the document are the truth about what a
        template needs; a declared field that no longer appears is a box on
        the form that fills nothing."""
        template = await self.save()
        self.assertEqual(["contents"], [f["key"] for f in template["fields"]])

    async def test_date_fills_itself_in(self):
        template = await self.save()
        status, body = await self.post(
            f"/api/template/{template['id']}/print", {"fields": {"contents": "Chili"}})
        self.assertEqual(200, status)
        self.assertEqual([], body["missing"])

    async def test_an_empty_field_refuses_rather_than_printing_a_gap(self):
        """The panel warns and this refuses, deliberately: the panel has
        somebody looking at the preview, and this call is usually an
        automation about to print fifty labels with a hole in them."""
        template = await self.save()
        status, body = await self.post(f"/api/template/{template['id']}/print")
        self.assertEqual(422, status)
        self.assertEqual(["contents"], body["missing"])
        self.assertEqual([], self.sent)

    async def test_a_template_can_be_printed_by_name(self):
        """The name is what an automation types, and it is not
        case-sensitive because nobody remembers the capitals."""
        await self.save()
        status, _ = await self.post(
            "/api/template/freezer bag/print", {"fields": {"contents": "Chili"}})
        self.assertEqual(200, status)

    async def test_an_unknown_template_names_the_ones_that_exist(self):
        await self.save()
        status, body = await self.post("/api/template/Nope/print")
        self.assertEqual(404, status)
        self.assertIn("Freezer bag", body["error"])

    async def test_the_preview_reports_what_is_still_empty(self):
        template = await self.save()
        _, body = await self.post(f"/api/template/{template['id']}/preview")
        self.assertEqual(["contents"], body["missing"])
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
    async def test_an_unexpected_error_does_not_carry_its_own_text_out(self):
        """An unexpected error is by definition one whose message nobody here
        wrote, so it may name a path, a library internal, or a value from
        somewhere else entirely. The traceback goes to the log.

        The middleware is driven directly rather than through a route: the
        router is frozen once the server is up, and a handler that raises is
        not something a request can be made to produce on purpose. Same
        reason `_settle` is a named function in brAIn's terminal bridge.
        """
        boom = "a-secret-looking-internal-detail"

        async def explode(_request):
            raise RuntimeError(boom)

        request = make_mocked_request("GET", "/api/anything")
        with self.assertLogs("bruh_print.panel", level="ERROR"):
            response = await server.json_errors(request, explode)
        self.assertEqual(500, response.status)
        body = json.loads(response.text)
        self.assertNotIn(boom, body["error"])
        self.assertIn("add-on log", body["error"])

    async def test_a_control_character_cannot_forge_a_log_line(self):
        """A forged line in an add-on log is a forged line in whatever a
        person pastes into an issue — and everything reaching a log line
        here (a path, a template name, a decoder quoting the body) came off
        the wire."""
        self.assertEqual("a?b", server._for_log("a\nb"))
        self.assertEqual("a?b", server._for_log("a\rb"))
        self.assertEqual("a??b", server._for_log("a\r\nb"))
        self.assertEqual("a?b", server._for_log("a\x00b"))
        self.assertEqual(120, len(server._for_log("x" * 400)))

    async def test_a_forged_path_does_not_reach_the_access_log(self):
        """The access logger writes a path on every non-quiet request — the
        line that runs most often, and the one left raw when the middleware
        above it was fixed."""
        records = []

        class Sink:
            def debug(self, fmt, *args):
                records.append(fmt % args)

            def log(self, _level, fmt, *args):
                records.append(fmt % args)

        logger = server.QuietAccessLogger(Sink(), "%r %s")
        request = make_mocked_request("GET", "/api/print")
        response = type("Response", (), {"status": 500})()
        with unittest.mock.patch.object(
                type(request), "path",
                property(lambda _self: "/api/x\nFAKE LINE")):
            logger.log(request, response, 0.01)
        self.assertTrue(records)
        self.assertNotIn("\n", records[-1])
        self.assertIn("FAKE LINE", records[-1])

    async def test_every_error_is_json_with_a_sentence_in_it(self):
        """An aiohttp HTTPException renders as an HTML page by default, and
        an HTML page reaching the bridge is an automation trace that says
        <!DOCTYPE html>."""
        response = await self.client.post("/api/template/nope/print", json={})
        self.assertEqual("application/json", response.content_type)
        self.assertIn("error", await response.json())

    async def test_a_body_that_is_not_json_says_so_without_quoting_the_parser(self):
        """The decoder's own message names a line and a column of the body it
        was handed — useful, and not ours to hand back to whoever sent it. It
        goes to the log; the caller gets the sentence that says what to do."""
        response = await self.client.post(
            "/api/print", data="not json",
            headers={"Content-Type": "application/json"})
        self.assertEqual(400, response.status)
        body = await response.json()
        self.assertIn("not valid JSON", body["error"])
        self.assertNotIn("line 1", body["error"])

    async def test_a_label_with_no_stock_says_which_field_is_missing(self):
        status, body = await self.post("/api/print", {"label": {"elements": []}})
        self.assertEqual(400, status)
        self.assertIn("stock", body["error"])


class TestItCanActuallyStart(unittest.IsolatedAsyncioTestCase):
    """The one path `build_app` does not cover: how `main` serves it.

    v0.1.0 started, logged "listening on 0.0.0.0:8097", and died on the next
    line — `run_app` type-checks `access_log_class` and `QuietAccessLogger`
    was a plain class with a duck-typed `log`. Every test instantiated it
    directly and the demo panel called `run_app` without it, so nothing in
    CI ever handed it to aiohttp. A panel that passes every route test and
    cannot start is the failure this class is for.
    """

    async def test_aiohttp_accepts_the_access_logger(self):
        """Runs aiohttp's own check rather than a restatement of it.

        The check is in `Application._make_handler`, which `AppRunner.setup`
        reaches and `AppRunner.__init__` does not — so a synchronous
        construction passes against the broken code and proves nothing.
        `setup()` builds the server without binding a port; the failure here
        is the exact TypeError the add-on died on.
        """
        from aiohttp import web as aiohttp_web  # noqa: PLC0415

        data = Path(tempfile.mkdtemp())
        panel = server.Panel(data)
        panel.discover = lambda force=False: []
        runner = aiohttp_web.AppRunner(server.build_app(panel),
                                       access_log_class=server.QuietAccessLogger)
        await runner.setup()
        await runner.cleanup()

    async def test_it_is_constructed_the_way_aiohttp_constructs_it(self):
        """(logger, log_format) — `AbstractAccessLogger.__init__` takes both
        and `log_format` has no default, so a one-argument construction in a
        test is a construction aiohttp never makes."""
        from aiohttp.abc import AbstractAccessLogger  # noqa: PLC0415

        self.assertTrue(issubclass(server.QuietAccessLogger,
                                   AbstractAccessLogger))
        logger = server.QuietAccessLogger(logging.getLogger("t"), "%r %s")
        self.assertIs(logging.getLogger("t"), logger.logger)


class TestItWorksUnderIngress(PanelCase):
    """Ingress mounts the panel under /api/hassio_ingress/<token>/.

    Serving at "/" is the one arrangement in which an absolute asset URL
    works, and it is the arrangement every test and the demo panel used —
    so 0.1.1 shipped a panel that rendered as unstyled HTML with all five
    views stacked, and CI was green at three widths.
    """

    PREFIX = "/api/hassio_ingress/01JJRqzH5o3TtVgngV7GNA3w"

    async def _under_prefix(self):
        from aiohttp import web as aiohttp_web  # noqa: PLC0415

        root = aiohttp_web.Application()
        root.add_subapp(self.PREFIX + "/", server.build_app(self.panel))
        client = TestClient(TestServer(root))
        await client.start_server()
        self.addAsyncCleanup(client.close)
        return client

    async def test_the_pages_own_assets_resolve_where_ingress_serves_them(self):
        """Fetched by the URL a browser would build from the page's markup,
        rather than by one this test composed — that is the whole failure."""
        import re  # noqa: PLC0415

        client = await self._under_prefix()
        page = await (await client.get(self.PREFIX + "/")).text()

        refs = re.findall(r'(?:href|src)="([^"]+)"', page)
        assets = [r for r in refs
                  if r.endswith((".css", ".js", ".svg"))]
        self.assertTrue(assets, "the page references no assets at all")
        for ref in assets:
            with self.subTest(asset=ref):
                self.assertFalse(
                    ref.startswith("/"),
                    f"{ref} is absolute; under ingress it asks Home "
                    f"Assistant's root, not this panel")
                response = await client.get(f"{self.PREFIX}/{ref}")
                self.assertEqual(200, response.status)

    async def test_the_api_answers_under_the_prefix(self):
        client = await self._under_prefix()
        self.assertEqual(200, (await client.get(self.PREFIX + "/api/state")).status)
        self.assertEqual(200, (await client.get(self.PREFIX + "/api/health")).status)

    async def test_the_javascript_never_fetches_an_absolute_path(self):
        """Twenty-odd call sites, so the rule is checked rather than each
        one: `api()` strips the leading slash, and nothing bypasses it."""
        import re  # noqa: PLC0415

        panel_dir = Path(__file__).resolve().parent.parent / "bruh-print" / "panel"
        source = (panel_dir / "app.js").read_text()
        absolute = re.findall(r"""fetch\(\s*['"`]/[^'"`]*""", source)
        self.assertEqual([], absolute)


class TestItDoesNotServeItsOwnSource(PanelCase):
    """`add_static("/static/", PANEL_DIR)` served the whole panel directory.

    Nothing in it is a secret — this add-on holds no credential — and the
    panel is admin-only behind ingress. It is still not something to serve,
    and the fix (four named routes) is the same edit that fixed the ingress
    paths, so the guard belongs beside it.
    """

    async def test_the_panels_modules_are_not_reachable(self):
        for path in ("/static/server.py", "/server.py",
                     "/static/stores/stock.py", "/static/dymo/protocol.py"):
            with self.subTest(path=path):
                self.assertEqual(404, (await self.client.get(path)).status)

    async def test_the_four_assets_are(self):
        for path in ("/", "/style.css", "/app.js", "/favicon.svg"):
            with self.subTest(path=path):
                self.assertEqual(200, (await self.client.get(path)).status)


class TestYouPickTheLabelNotTheRoll(PanelCase):
    """Which bay a label prints on is not a question anybody wants asked.

    The add-on knows which roll holds which stock. Two ways to say where a
    label goes is one way to contradict the other, so the roll picker is
    gone from the Quick tab, the designer, the templates, the card and the
    print services — naming the stock has already named the bay.
    """

    async def test_a_print_that_names_no_side_lands_on_the_right_roll(self):
        state = self.panel
        state.rolls.load_roll("left", "edcc-082wh", count=100)
        state.rolls.load_roll("right", "ed1f-060wh", count=100)

        for stock, expect in (("edcc-082wh", "left"), ("ed1f-060wh", "right")):
            with self.subTest(stock=stock):
                response = await self.client.post("/api/quick", json={
                    "text": "x", "stock": stock, "print": True})
                body = await response.json()
                self.assertEqual(200, response.status, body)
                self.assertEqual(expect, body["side"])

    async def test_the_panel_never_sends_a_side(self):
        """Twenty call sites; the rule is checked rather than each one."""
        source = (PANEL_DIR / "app.js").read_text()
        self.assertNotIn("quickSide", source)
        self.assertNotIn("designSide", source)
        self.assertNotIn("side: side.value", source)

    async def test_the_card_sends_a_stock_and_never_a_side(self):
        card = (PANEL_DIR.parent / "lovelace" / "bruh-print-card.js").read_text()
        self.assertNotIn("data.side", card)
        self.assertIn("_selectedStock", card)


class TestOnlyWhatIsLoadedCanBePicked(PanelCase):
    """The Printer tab is where the catalog lives; nowhere else offers it.

    Offering fourteen stocks on the Quick tab when two are in the printer
    makes the commonest first action a choice between twelve wrong answers
    and then a refusal for picking one.
    """

    async def test_a_stock_says_whether_it_is_loaded_and_where(self):
        self.panel.rolls.load_roll("left", "edcc-082wh", count=100)
        body = await (await self.client.get("/api/state")).json()
        rows = {s["id"]: s for s in body["stocks"]}
        self.assertTrue(rows["edcc-082wh"]["loaded"])
        self.assertEqual("left", rows["edcc-082wh"]["loaded_side"])
        self.assertFalse(rows["dymo-30252"]["loaded"])
        self.assertEqual("", rows["dymo-30252"]["loaded_side"])

    async def test_an_empty_printer_falls_back_to_the_whole_catalog(self):
        """An empty picker is a panel that looks broken, and somebody who
        has not filled the Printer tab in yet still wants to print."""
        source = (PANEL_DIR / "app.js").read_text()
        self.assertIn("return on.length ? on : S.stocks;", source)


class TestEachStockRemembersItsOwnTurn(PanelCase):
    """Which way text sits on a label is the label's property, not the job's.

    A wrap-around cryo label reads along the roll and an address label reads
    across it — always, for that stock. Asking on every print is asking a
    question whose answer never changes.
    """

    async def test_the_shape_decides_when_nobody_has_said(self):
        body = await (await self.client.get("/api/state")).json()
        rows = {s["id"]: s for s in body["stocks"]}
        self.assertEqual(0, rows["edcc-082wh"]["turn"], "2.25 × 1.25 reads across")
        self.assertEqual(90, rows["ed1f-060wh"]["turn"], "0.56 × 3.44 reads along")
        for row in rows.values():
            self.assertFalse(row["turn_set"], "nothing is overridden out of the box")

    async def test_a_quick_print_takes_the_stock_s_turn(self):
        self.panel.rolls.load_roll("right", "ed1f-060wh", count=100)
        body = await (await self.client.post("/api/quick", json={
            "text": "Vial 12", "stock": "ed1f-060wh"})).json()
        self.assertEqual(90, body["label"]["rotate"])

    async def test_an_override_sticks_and_can_be_taken_back(self):
        response = await self.client.post(
            "/api/stock/edcc-082wh/turn", json={"turn": 90})
        body = await response.json()
        self.assertEqual(90, body["stock"]["turn"])
        self.assertTrue(body["stock"]["turn_set"])

        body = await (await self.client.post(
            "/api/stock/edcc-082wh/turn", json={"turn": None})).json()
        self.assertEqual(0, body["stock"]["turn"])
        self.assertFalse(body["stock"]["turn_set"],
                         "back to being derived, not frozen at 0")

    async def test_a_turn_that_is_not_a_quarter_is_refused(self):
        response = await self.client.post(
            "/api/stock/edcc-082wh/turn", json={"turn": 45})
        self.assertEqual(400, response.status)
        self.assertIn("45", (await response.json())["error"])

    async def test_swapping_re_derives_the_turn(self):
        """The shape is what `natural_turn` reads, so a derived turn has to
        be re-derived — keeping the old answer is a swap that fixes the
        width and leaves the text lying the way it was wrong before."""
        before = await (await self.client.get("/api/state")).json()
        row = next(s for s in before["stocks"] if s["id"] == "ed1f-060wh")
        self.assertEqual(90, row["turn"])
        after = await (await self.client.post(
            "/api/stock/ed1f-060wh/swap", json={})).json()
        self.assertEqual(0, after["stock"]["turn"],
                         "3.44 × 0.56 is a wide stock and reads across")


class TestTheRemainingCountIsOptional(PanelCase):
    """A number you can see and cannot correct is a number you stop reading,
    and a number kept while hidden is one that goes quietly wrong."""

    async def test_the_count_can_be_set_by_hand(self):
        self.panel.rolls.load_roll("left", "edcc-082wh", count=1000)
        body = await (await self.client.post(
            "/api/roll/left", json={"stock": "edcc-082wh", "remaining": 42})).json()
        self.assertEqual(42, body["roll"]["remaining"])

    async def test_printing_stops_counting_when_tracking_is_off(self):
        self.panel.rolls.load_roll("left", "edcc-082wh", count=100)
        await self.client.post("/api/settings", json={"track_remaining": False})
        await self.client.post("/api/quick", json={
            "text": "x", "stock": "edcc-082wh", "copies": 5, "print": True})
        self.assertEqual(100, self.panel.rolls.get("left").remaining)

        await self.client.post("/api/settings", json={"track_remaining": True})
        await self.client.post("/api/quick", json={
            "text": "x", "stock": "edcc-082wh", "copies": 5, "print": True})
        self.assertEqual(95, self.panel.rolls.get("left").remaining)

    async def test_every_print_path_asks_the_same_gate(self):
        """Five call sites asking separately is five chances for a new print
        path to keep counting a number the panel has stopped showing."""
        source = (PANEL_DIR / "server.py").read_text()
        self.assertNotIn("state.rolls.consume(", source)
        self.assertIn("def consume(self, side: str, count: int)", source)


class TestTheFontPickerShowsTheFont(PanelCase):
    """A <select> of family names shows the one thing a font choice is not
    about. Every sample is drawn by the label renderer, so what a person
    picks is what the printer draws — a CSS font-family preview would be the
    browser's idea of "Monospace" beside a label printed in DejaVu Sans
    Mono, which is the failure a preview exists to prevent.
    """

    async def test_a_known_font_answers_with_a_png(self):
        response = await self.client.get("/api/font/mono/sample.png")
        self.assertEqual(200, response.status)
        self.assertEqual("image/png", response.content_type)
        body = await response.read()
        self.assertTrue(body.startswith(b"\x89PNG"), "not a PNG at all")
        self.assertIn("max-age", response.headers.get("Cache-Control", ""))

    async def test_the_sample_text_can_be_asked_for(self):
        plain = await (await self.client.get("/api/font/mono/sample.png")).read()
        asked = await (await self.client.get(
            "/api/font/mono/sample.png?text=Chest%20freezer")).read()
        self.assertNotEqual(plain, asked, "the text argument did nothing")

    async def test_an_unknown_font_is_a_404_in_the_panel_s_own_words(self):
        response = await self.client.get("/api/font/comic-sans/sample.png")
        self.assertEqual(404, response.status)
        body = await response.json()
        self.assertIn("comic-sans", body["error"])
        self.assertIn("mono", body["error"], "it does not say what there is")

    async def test_the_error_never_carries_the_text_argument(self):
        """The key is the typo worth naming; the text is a string somebody
        else's automation put in a query. Echoing it back is how an error
        message becomes a place to put things."""
        response = await self.client.get(
            "/api/font/nope/sample.png?text=%3Cscript%3Ealert(1)%3C/script%3E")
        self.assertEqual(404, response.status)
        raw = await response.text()
        self.assertNotIn("alert(1)", raw)
        self.assertNotIn("<script>", raw)


class TestAPreviewSaysWhichBoxIsWrong(PanelCase):
    """`notes` is a sentence under a canvas with six identical boxes on it.

    The designer can draw a red outline instead — but only if it is told
    which element each message belongs to, which is what `problems` carries.
    `notes` is unchanged, because five other things read it.
    """

    async def test_a_barcode_too_wide_for_its_box_names_its_index(self):
        document = {"stock": "edcc-082wh", "elements": [
            {"type": "text", "x_mm": 1, "y_mm": 1, "w_mm": 30, "h_mm": 8,
             "props": {"text": "Chest freezer"}},
            {"type": "barcode", "x_mm": 1, "y_mm": 12, "w_mm": 5, "h_mm": 8,
             "props": {"data": "A-VERY-LONG-LOT-NUMBER-1234567890"}}]}
        response = await self.client.post("/api/preview",
                                          json={"label": document})
        self.assertEqual(200, response.status)
        problems = json.loads(response.headers["X-Label-Problems"])
        self.assertEqual([1], [p["index"] for p in problems])
        self.assertIn("modules", problems[0]["message"])
        # Unchanged for everything that already reads it.
        notes = json.loads(response.headers["X-Label-Notes"])
        self.assertTrue(any("modules" in note for note in notes))

    async def test_a_clean_label_reports_none(self):
        """A label whose only note is about the stock being wider than the
        head has no element to blame, and blaming one would be worse than
        saying nothing."""
        response = await self.client.post(
            "/api/preview", json={"label": self.label()})
        self.assertEqual([], json.loads(response.headers["X-Label-Problems"]))


class TestEditingAStockKeepsWhatTheDialogDoesNotShow(PanelCase):
    """The Edit dialog shows the measurements, the margin and the count.

    It does not show the text direction, and a Save that blanked it would
    undo a correction made one control away on the same row.
    """

    async def test_the_text_direction_survives_a_save(self):
        await self.client.post("/api/stock/edcc-082wh/turn", json={"turn": 90})
        await self.client.post("/api/stock", json={
            "id": "edcc-082wh", "name": "Chemical-Resistant Cryo Labels",
            "across_in": 2.25, "feed_in": 1.25, "margin_mm": 3.0,
            "per_roll": 1000})
        rows = {s["id"]: s for s in
                (await (await self.client.get("/api/stocks")).json())["stocks"]}
        self.assertEqual(90, rows["edcc-082wh"]["turn"])
        self.assertTrue(rows["edcc-082wh"]["turn_set"])
        self.assertEqual(3.0, rows["edcc-082wh"]["margin_mm"])

    async def test_a_new_stock_takes_the_default_margin(self):
        await self.client.post("/api/stock", json={
            "name": "Storage box lids", "across_in": 2.0, "feed_in": 1.0})
        rows = {s["id"]: s for s in
                (await (await self.client.get("/api/stocks")).json())["stocks"]}
        self.assertEqual(2.0, rows["storage-box-lids"]["margin_mm"])


class TestOneSettingForWhichWayTheTextSits(PanelCase):
    """It was asked in three places — the Quick tab, the design bar and the
    Printer tab — which is three controls that can disagree about a property
    of the roll. Two of them are gone and the third is a sentence."""

    async def test_the_two_pickers_are_gone_from_the_page(self):
        page = (PANEL_DIR / "index.html").read_text()
        self.assertNotIn('id="quickRotate"', page)
        self.assertNotIn('id="designRotate"', page)
        self.assertIn('id="quickTurnLine"', page)
        self.assertIn('id="designTurnLine"', page)

    async def test_the_quick_tab_never_sends_a_turn(self):
        """The server takes the stock's own answer when none is sent, which
        is what makes a quick print unable to contradict the Printer tab."""
        source = (PANEL_DIR / "app.js").read_text()
        self.assertNotIn("quickRotate", source)
        self.assertNotIn("rotate: Number(rotate)", source)


class TestDarkByDefault(PanelCase):
    """Labels printed light because nothing ever told the printer not to.

    A LabelWriter with no density and no quality command in the preamble
    runs at its own defaults — normal density, text speed — and on ordinary
    thermal stock that comes out faint. Asserted on the bytes that would
    have been written, because the response says "Printed 1" either way.
    """

    async def test_a_default_print_carries_dark_and_the_slow_mode(self):
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})
        status, _ = await self.post("/api/print", {"label": self.label()})
        self.assertEqual(200, status)
        self.assertIn(protocol.set_density("dark"), self.sent[-1])
        self.assertIn(protocol.set_quality("graphics"), self.sent[-1])

    async def test_bare_mode_sends_neither(self):
        """`bare` is what somebody tries when the printer takes a job and
        prints nothing, so it has to drop these two as well — a mode that
        still sent them would not answer the question it is asked."""
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})
        await self.post("/api/settings", {"print_mode": "bare"})
        await self.post("/api/print", {"label": self.label()})
        for command in (b"\x1bc", b"\x1bd", b"\x1be", b"\x1bg",
                        b"\x1bh", b"\x1bi"):
            self.assertNotIn(command, self.sent[-1], command)

    async def test_a_chosen_darkness_reaches_the_printer(self):
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})
        await self.post("/api/settings", {"density": "light",
                                          "quality": "text"})
        await self.post("/api/print", {"label": self.label()})
        self.assertIn(protocol.set_density("light"), self.sent[-1])
        self.assertIn(protocol.set_quality("text"), self.sent[-1])
        self.assertNotIn(protocol.set_quality("graphics"), self.sent[-1])

    async def test_a_typo_is_not_stored(self):
        """A stored typo is a setting somebody believes they changed — and
        here it is worse than inert: the protocol refuses an unknown
        density, so it would turn every print into a failure."""
        status, _ = await self.post("/api/settings", {"density": "darkk"})
        self.assertEqual(200, status)
        _, body = await self.get("/api/settings")
        self.assertEqual("dark", body["settings"]["density"])

        await self.post("/api/settings", {"quality": "photo"})
        _, body = await self.get("/api/settings")
        self.assertEqual("graphics", body["settings"]["quality"])


class TestTheBytesThatDecideAlignment(PanelCase):
    """"The alignment is off on the labels" — including on a printed ruler,
    whose artwork measures symmetric to the dot.

    Nothing above the wire could be wrong, so the two things asserted here
    are the two the wire got wrong: what `ESC L` meant, and the dot tab that
    was never sent. Both are invisible from the response — the panel says
    "Printed 1 on the left roll" either way — so they are asserted on the
    payload that would have reached the printer.
    """

    # The cryo stock this house prints on: 2.25" x 1.25" at 300 dpi is 375
    # dot lines of label, and the default quality is the 300x600 graphics
    # mode, so the raster is 750 lines and the budget is counted in those
    # same steps.
    LABEL_LINES = 375

    def _length(self, payload: bytes) -> int:
        marker = bytes([protocol.ESC, ord("L")])
        index = payload.index(marker)
        return (payload[index + 2] << 8) | payload[index + 3]

    async def _print(self, stock="edcc-082wh", **settings):
        await self.post("/api/roll/left", {"stock": stock})
        if settings:
            await self.post("/api/settings", settings)
        status, body = await self.post(
            "/api/print", {"label": self.label(stock=stock)})
        self.assertEqual(200, status, body)
        return self.sent[-1]

    async def test_the_length_sent_is_the_search_budget_not_the_raster(self):
        """The old value was the rendered raster's own height, so the
        top-of-form search ran out at the exact line the artwork ended on —
        before the sense hole, which is in the gap after the label. Every
        label then starts a fraction further along than the last, which is
        a misalignment that grows down a roll rather than a constant one."""
        payload = await self._print()
        repeat = protocol.LINE_REPEAT["graphics"]
        printed = self.LABEL_LINES * repeat
        sent = self._length(payload)
        self.assertEqual(
            protocol.search_length(self.LABEL_LINES) * repeat, sent)
        self.assertEqual(938, sent)
        self.assertGreater(sent, printed)
        self.assertNotEqual(printed, sent)

    async def test_the_dot_tab_is_stated_rather_than_inherited(self):
        """It is state inside the printer, kept until something changes it
        — so a preamble that omits it starts wherever DYMO Connect or
        another driver left it, on every line of every label."""
        payload = await self._print()
        self.assertIn(bytes([protocol.ESC, ord("B"), 0]), payload)

    async def test_bare_still_sends_the_geometry_and_nothing_else(self):
        payload = await self._print(print_mode="bare")
        self.assertNotIn(bytes([protocol.ESC, ord("B")]), payload)
        self.assertIn(protocol.set_bytes_per_line(84), payload)
        self.assertEqual(
            protocol.search_length(self.LABEL_LINES), self._length(payload))

    async def test_the_fast_mode_sends_the_unscaled_budget(self):
        """The budget is counted in the printer's own steps, so it scales
        with the raster and not with the label."""
        payload = await self._print(quality="text")
        self.assertEqual(
            protocol.search_length(self.LABEL_LINES), self._length(payload))

    async def test_continuous_stock_goes_into_continuous_feed_mode(self):
        """A stock with no die cut has no sense holes, so a positive length
        sends the printer looking for something that is not on the paper.
        The catalog has shipped `continuous-2-25` since the first release
        and this command has never gone with it."""
        payload = await self._print(stock="continuous-2-25")
        self.assertIn(protocol.continuous_form(), payload)
        self.assertGreaterEqual(self._length(payload), 0x8000)

    async def test_a_die_cut_stock_never_takes_that_value(self):
        payload = await self._print(stock="ed1f-060wh")
        self.assertLess(self._length(payload), 0x8000)
        # 3.44" of label at 300 dpi, doubled by the graphics mode, plus the
        # headroom that reaches the hole.
        self.assertEqual(protocol.search_length(1032) * 2,
                         self._length(payload))


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


class TestTheDesignerSeesTheCanvasNotTheSheet(PanelCase):
    """A label drawn at 90° is designed as the strip it reads as.

    `render` turns the canvas by -rotate on its way to the sheet, so the
    printed sheet of a 0.56" × 3.44" tube wrap is a tall strip with its words
    on their side. That is the right picture on the Quick tab and the wrong
    one under a drag overlay whose coordinates are the canvas's: the box being
    held and the ink it described sat in two different places, which made a
    wrap-around label undesignable — and every new label on a wrap stock
    takes 90° automatically now. `view: "canvas"` hands back the same bitmap
    turned back the way it was drawn; nothing else changes.
    """

    async def _size(self, payload):
        from PIL import Image  # noqa: PLC0415
        response = await self.client.post("/api/preview", json=payload)
        self.assertEqual(200, response.status)
        body = await response.read()
        image = Image.open(io.BytesIO(body))
        return image.size, response.headers.get("X-Label-View")

    async def test_the_sheet_is_the_default_and_the_canvas_is_asked_for(self):
        label = self.label(stock="ed1f-060wh", text="Freezer")
        label["rotate"] = 90
        (sheet_w, sheet_h), view = await self._size({"label": label})
        self.assertEqual("sheet", view)
        self.assertGreater(sheet_h, sheet_w, "a tube wrap comes off the roll tall")

        (canvas_w, canvas_h), view = await self._size(
            {"label": label, "view": "canvas"})
        self.assertEqual("canvas", view)
        self.assertGreater(canvas_w, canvas_h, "and is designed as a long strip")
        # The same bitmap, turned — not a second render.
        self.assertEqual((sheet_h, sheet_w), (canvas_w, canvas_h))

    async def test_an_unturned_label_is_the_same_picture_either_way(self):
        label = self.label(text="Pantry")
        sheet, _ = await self._size({"label": label})
        canvas, view = await self._size({"label": label, "view": "canvas"})
        self.assertEqual(sheet, canvas)
        self.assertEqual("sheet", view, "nothing was turned, and the header says so")


class CalibrationCase(PanelCase):
    """Shared plumbing for the four classes below.

    Everything here walks the payload that would have been written, because
    that is the only place the answer exists: the panel says "Printed 1 on
    the left roll" whether the label came out where it was asked for or 5mm
    down the roll.
    """

    HEAD_BYTES = 84

    async def loaded(self, stock="edcc-082wh", **changes):
        if changes:
            await self.post("/api/stock", {
                "id": stock, "name": "Chemical-Resistant Cryo Labels",
                "across_in": 2.25, "feed_in": 1.25, **changes})
        await self.post("/api/roll/left", {"stock": stock})

    async def calibrate(self, stock="edcc-082wh", **calibration):
        """Save a calibration the way the wizard does, without the printing.

        Through the real route and the real derivation: a test that reached
        into the store would be testing a shape rather than the thing the
        panel does with five numbers.
        """
        entry = self.panel.stocks.require(stock)
        self.panel.stocks.put(server.stock_store.replace(
            entry, calibration=server.stock_store.Calibration(**calibration),
            builtin=False))

    def rows(self, payload):
        """The SYN lines out of a job, the way a printer reads them."""
        out, index = [], 0
        while index < len(payload):
            byte = payload[index]
            if byte == protocol.ESC:
                letter = chr(payload[index + 1])
                if payload[index + 1] == protocol.ESC:
                    index += 1
                    continue
                index += 2 + {"L": 2, "B": 1, "D": 1, "q": 1,
                              "f": 2}.get(letter, 0)
            elif byte == protocol.SYN:
                out.append(payload[index + 1:index + 1 + self.HEAD_BYTES])
                index += 1 + self.HEAD_BYTES
            else:
                raise AssertionError(f"byte {byte:#x} at {index}")
        return out

    def skips(self, payload):
        """Every `ESC f 1 n` in a job, in order, as line counts."""
        out, index = [], 0
        marker = bytes([protocol.ESC, ord("f")])
        while True:
            index = payload.find(marker, index)
            if index < 0:
                return out
            self.assertEqual(0x01, payload[index + 2],
                             "the manual requires the 1 prior to the value")
            out.append(payload[index + 3])
            index += 4

    def first_inked(self, payload):
        for number, row in enumerate(self.rows(payload)):
            if any(row):
                return number
        raise AssertionError("nothing in this job has any ink in it")

    def columns(self, payload):
        """Which head dots a job asks for."""
        found = set()
        for row in self.rows(payload):
            packed = protocol.pack_line(row, self.HEAD_BYTES)
            for position, value in enumerate(packed):
                for bit in range(8):
                    if value & (1 << (7 - bit)):
                        found.add(position * 8 + bit)
        return found

    def length(self, payload):
        marker = bytes([protocol.ESC, ord("L")])
        index = payload.index(marker)
        return (payload[index + 2] << 8) | payload[index + 3]

    async def print_once(self, **extra):
        status, body = await self.post(
            "/api/print", {"label": self.label(text="Rice"), **extra})
        self.assertEqual(200, status, body)
        return body, self.sent[-1]


class TestTheDeadBandAtTheLeadingEdge(CalibrationCase):
    """A printer that starts late, and what the print path does about it.

    The measured case: on this roll the printer lays no ink for the first
    4.7mm of every label. 0.6.0 answered it with a raster shift and three
    prints proved the shift could not reach it — everything on the label
    moved and the band did not. What reaches the printer now is a SHORTER
    sheet: the rows that would land in the band are cut off the front, so
    the first row sent is the first row the printer can lay and everything
    else stays where the document put it.
    """

    async def test_the_sheet_that_reaches_the_printer_is_the_one_that_was_cut(self):
        """4.7mm is 56 dot lines at 300 dpi, and the default quality is the
        300x600 graphics mode where every raster row goes twice — so the
        wire loses 112 lines for a 56-line band. The doubling and the crop
        are one fact and they must not drift apart."""
        await self.loaded()
        _, before = await self.print_once()
        await self.calibrate(start_mm=4.7)
        _, after = await self.print_once()

        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual(56 * repeat,
                         len(self.rows(before)) - len(self.rows(after)))
        self.assertEqual(56 * repeat,
                         self.first_inked(before) - self.first_inked(after))
        self.assertEqual([], self.skips(after),
                         "a printer that starts late cannot be fed forwards")

    async def test_the_ink_does_not_move_relative_to_the_paper(self):
        """The whole point of a crop rather than a shift. Row 82 of the
        sheet was drawn for 82 lines in; the printer starts 56 lines in and
        is handed the sheet from row 56, so that ink still lands 82 lines
        down the label. A shift would have moved it to 26."""
        await self.loaded()
        _, before = await self.print_once()
        await self.calibrate(start_mm=4.7)
        _, after = await self.print_once()
        dead = 56 * protocol.LINE_REPEAT["graphics"]
        self.assertEqual(self.first_inked(before),
                         dead + self.first_inked(after))

    async def test_the_length_budget_is_unchanged_by_a_crop(self):
        """`ESC L` is about reaching the sense hole, which did not move
        because the raster got shorter. It is the STOCK's length and never
        the height of what is sent."""
        await self.loaded()
        _, before = await self.print_once()
        await self.calibrate(start_mm=4.7)
        _, after = await self.print_once()
        self.assertEqual(938, self.length(before))
        self.assertEqual(938, self.length(after))

    async def test_ink_asked_for_before_the_die_cut_is_fed_instead(self):
        """The other sign, and the one the printer can answer: `ESC f 1 n`
        feeds that far first and the whole label is printable. It was
        documented in this add-on as deliberately unused, which was right
        about what it cannot do and wrong to conclude it had no job."""
        await self.loaded()
        await self.calibrate(start_mm=-2.0)
        _, payload = await self.print_once()
        # 2mm is 24 lines at 300 dpi, doubled by the graphics mode.
        self.assertEqual([48], self.skips(payload))
        self.assertEqual(375 * protocol.LINE_REPEAT["graphics"],
                         len(self.rows(payload)), "nothing was cropped")

    async def test_a_roll_nobody_calibrated_prints_what_it_always_did(self):
        """The promise every measurement in this add-on is added under, and
        the one that makes a calibration safe to try."""
        await self.loaded()
        _, before = await self.print_once()
        await self.calibrate()
        _, after = await self.print_once()
        self.assertEqual(before, after)
        self.assertEqual([], self.skips(after))

    async def test_a_crop_that_costs_ink_prints_and_says_so(self):
        await self.loaded()
        await self.calibrate(start_mm=20.0)
        body, _ = await self.print_once()
        self.assertEqual(1, body["printed"])
        note = " ".join(body["notes"])
        self.assertIn("20.0mm into every label", note)
        self.assertIn("did not print", note)

    async def test_the_calibration_is_not_part_of_the_label(self):
        """It is a correction to where the machine puts the paper. A preview
        that drew it would be showing somebody their printer's registration
        as if it were their own layout — and the design canvas is where
        boxes get dragged against it."""
        await self.loaded()
        first = await self.client.post("/api/preview",
                                       json={"label": self.label(text="Rice")})
        before = await first.read()
        await self.calibrate(start_mm=4.7, across_mm=7.3)
        second = await self.client.post("/api/preview",
                                        json={"label": self.label(text="Rice")})
        self.assertEqual(before, await second.read())


class TestTheFirstLabelOfAJob(CalibrationCase):
    """`after_tear_mm`: the band that is only on the first copy.

    The manual says an `ESC E` "places the next label beyond the starting
    print position. Therefore, a reverse-feed will be automatically invoked
    when printing on the next label." A printer that does not make that
    reverse feed loses a fixed amount off the first label of every job and
    nothing off the rest — which no single number can express, and which is
    why a job is a list of pages rather than rows and a count.
    """

    async def test_only_the_first_copy_is_charged(self):
        await self.loaded()
        await self.calibrate(after_tear_mm=4.7)
        _, payload = await self.print_once(copies=3)
        pages = self._pages(payload)
        self.assertEqual(3, len(pages))
        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual(56 * repeat, len(pages[1]) - len(pages[0]))
        self.assertEqual(len(pages[1]), len(pages[2]))

    async def test_a_job_after_a_hold_does_not_pay_it(self):
        """`ending: "hold"` leaves the label inside the printer, so there is
        no tear-off and no reverse feed owed — which is the whole reason
        that ending exists on a roll with this fault."""
        await self.loaded()
        await self.calibrate(after_tear_mm=4.7, ending="hold")
        await self.print_once()
        _, second = await self.print_once()
        pages = self._pages(second)
        self.assertEqual(375 * protocol.LINE_REPEAT["graphics"],
                         len(pages[0]),
                         "the first label of the second job was charged")
        self.assertTrue(second.endswith(protocol.short_form_feed()))
        self.assertNotIn(protocol.form_feed(), second)

    async def test_a_job_after_a_tear_off_pays_it_again(self):
        """Which is what makes it per-job rather than per-panel-start: every
        ordinary job ends at the tear bar, so every ordinary job's first
        label is the one that follows one."""
        await self.loaded()
        await self.calibrate(after_tear_mm=4.7)
        await self.print_once()
        _, second = await self.print_once()
        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual((375 - 56) * repeat, len(self._pages(second)[0]))

    async def test_the_feed_button_puts_the_paper_back_at_the_tear_bar(self):
        """A roll running with `hold` ends its runs by hand, and after that
        the next job's first label is charged again. The bookkeeping has to
        follow the paper, not the setting."""
        await self.loaded()
        await self.calibrate(after_tear_mm=4.7, ending="hold")
        await self.print_once()
        status, body = await self.post("/api/printer/feed", {})
        self.assertEqual(200, status, body)
        self.assertEqual(protocol.form_feed(), self.sent[-1])
        _, after = await self.print_once()
        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual((375 - 56) * repeat, len(self._pages(after)[0]))

    def _pages(self, payload):
        """The rows of each page, split on the feeds between them."""
        pages, current, index = [], [], 0
        while index < len(payload):
            byte = payload[index]
            if byte == protocol.ESC:
                letter = chr(payload[index + 1])
                if payload[index + 1] == protocol.ESC:
                    index += 1
                    continue
                index += 2 + {"L": 2, "B": 1, "D": 1, "q": 1,
                              "f": 2}.get(letter, 0)
                if letter in ("G", "E"):
                    pages.append(current)
                    current = []
            elif byte == protocol.SYN:
                current.append(payload[index + 1:index + 1 + self.HEAD_BYTES])
                index += 1 + self.HEAD_BYTES
            else:
                raise AssertionError(f"byte {byte:#x} at {index}")
        return pages


class TestWhereThePaperSitsUnderTheHead(CalibrationCase):
    """The across half, which is now one number instead of two.

    The report: a solid-fill label on the 0.56" x 3.44" cryo wrap, inked
    across 335px of a 687px label — 49% of its width, from one edge, ending
    dead at the halfway point — and no value of the 0.6.0 across offset
    changed anything. It could not: that offset moved artwork inside a sheet
    that is 168 dots wide, and the sheet itself always began at head dot 0.
    """

    def wrap_label(self):
        """Solid fill, which is what was printed: every column of the sheet
        carries ink, so the inked columns are the columns of the head."""
        return {"stock": "ed1f-060wh", "rotate": 0, "elements": [
            {"type": "box", "x_mm": 0, "y_mm": 0, "w_mm": 500, "h_mm": 500,
             "props": {"fill": True, "stroke_mm": 0}}]}

    async def print_wrap(self):
        status, body = await self.post("/api/print",
                                       {"label": self.wrap_label()})
        self.assertEqual(200, status, body)
        return body, self.sent[-1]

    async def test_the_reported_case_lands_on_head_dots_0_to_167(self):
        """Reproduced through the real routes before anything is asked of
        the calibration: with nothing measured, the whole 168-dot sheet is
        against the head's first dot and the other 504 dots are never asked
        for. On a roll whose paper is not there, that is the half-inked
        label in the photograph."""
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        _, payload = await self.print_wrap()
        columns = self.columns(payload)
        self.assertEqual(24, min(columns), "the renderer's 2mm border")
        self.assertEqual(143, max(columns))
        self.assertFalse([c for c in columns if c > 167])

    async def test_a_measured_edge_moves_the_whole_sheet_along_the_head(self):
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        _, before = await self.print_wrap()
        await self.calibrate("ed1f-060wh", across_mm=7.3)
        _, after = await self.print_wrap()
        shift = 86  # 7.3mm at 300 dpi, rounded once
        self.assertEqual({c + shift for c in self.columns(before)},
                         self.columns(after))
        self.assertEqual(110, min(self.columns(after)))

    async def test_a_position_that_costs_ink_prints_and_says_so(self):
        """The standing rule: the stock/roll mismatch is the only refusal.
        A position that pushes the label past the head's last dot still
        prints what fits, with a note naming the amount and the edge."""
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        await self.calibrate("ed1f-060wh", across_mm=50.0)
        body, payload = await self.print_wrap()
        note = " ".join(body["notes"])
        self.assertIn("past the head’s last dot", note)
        self.assertIn("50.0mm in from the print head", note)
        self.assertLessEqual(max(self.columns(payload)), 671)

    async def test_the_two_boxes_that_could_not_be_told_apart_are_gone(self):
        """`media_across_mm` said where a narrow roll's paper sat and
        `offset_across_mm` shifted artwork inside the sheet. There is one
        left edge on a roll, and a person whose label printed 7mm to the
        left had no way of knowing which box was theirs."""
        _, body = await self.get("/api/stocks")
        row = next(s for s in body["stocks"] if s["id"] == "ed1f-060wh")
        self.assertNotIn("media_across_mm", row)
        self.assertNotIn("offset_across_mm", row)
        self.assertNotIn("offset_feed_mm", row)
        self.assertIn("across_mm", row["calibration"])


class TestTheCalibrationPrint(CalibrationCase):
    """The two labels a person reads, and what the route reports sending.

    The ruler cannot do this job and neither could the 0.7.0 calibration
    label: both are drawn to the stock's own sheet, which on a 0.56" wrap is
    168 dots, so every mark they make is inside the very thing whose
    position is in question. This one is drawn to the whole head.
    """

    async def test_it_prints_two_labels_and_says_what_it_sent(self):
        """The derivation divides by both numbers, so a report that left
        either out would leave the readings meaning nothing — a top
        measurement without the pre-skip it was taken against is not a
        distance from anything."""
        await self.loaded()
        status, body = await self.post("/api/printer/calibrate", {})
        self.assertEqual(200, status, body)
        self.assertEqual(2, body["printed"])
        self.assertEqual(2, body["copies"])
        self.assertEqual("left", body["side"])
        self.assertEqual(5.0, body["pre_skip_mm"])
        self.assertEqual("plain", body["variant"])
        # 375 lines plus 25% plus the 59-line pre-skip, in millimetres.
        self.assertAlmostEqual(
            protocol.budget_dots(375, None, 59) / 300 * 25.4,
            body["esc_l_mm"], places=1)

    async def test_the_two_copies_carry_different_ink(self):
        """Which is the whole reason a job is a list of pages: copy 2 is the
        entire evidence for the hypothesis that only the first label of a
        job is wrong, and telling the two apart by the order somebody picked
        them up is not evidence."""
        await self.loaded()
        await self.post("/api/printer/calibrate", {})
        payload = self.sent[-1]
        self.assertEqual(1, payload.count(protocol.short_form_feed()))
        self.assertTrue(payload.endswith(protocol.form_feed()))
        halves = payload.split(protocol.short_form_feed())
        self.assertNotEqual(halves[0][-2000:], halves[1][-2000:])

    async def test_the_deliberate_pre_skip_is_on_the_wire_and_in_the_budget(self):
        """"Print lines and lines fed both count towards this total", so a
        budget that ignored the skip would end the search 5mm short of the
        hole — the pre-0.5.0 drift, reintroduced by the one job whose whole
        purpose is measuring where the printing starts."""
        await self.loaded()
        await self.post("/api/printer/calibrate", {})
        payload = self.sent[-1]
        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual([59 * repeat, 59 * repeat], self.skips(payload))
        self.assertEqual(protocol.budget_dots(375, None, 59) * repeat,
                         self.length(payload))

    async def test_none_of_the_roll_s_own_calibration_reaches_it(self):
        """It is an absolute instrument or it is nothing: a ladder that
        moved with the numbers it measures reads the same thing however
        wrong they are, so printing it again could never check anything."""
        await self.loaded()
        await self.post("/api/printer/calibrate", {})
        first = self.sent[-1]
        await self.calibrate(start_mm=4.7, across_mm=7.3, after_tear_mm=2.0)
        await self.post("/api/printer/calibrate", {})
        self.assertEqual(first, self.sent[-1])

    async def test_the_reset_variant_is_the_one_command_that_differs(self):
        await self.loaded()
        await self.post("/api/printer/calibrate", {"variant": "plain"})
        plain = self.sent[-1]
        _, body = await self.post("/api/printer/calibrate",
                                  {"variant": "reset"})
        reset = self.sent[-1]
        self.assertEqual("reset", body["variant"])
        self.assertNotIn(b"\x1b@", plain)
        self.assertIn(b"\x1b@", reset)
        self.assertEqual(len(plain) + 2, len(reset))

    async def test_a_variant_nobody_has_is_refused(self):
        await self.loaded()
        status, body = await self.post("/api/printer/calibrate",
                                       {"variant": "hold"})
        self.assertEqual(400, status)
        self.assertIn("hold", body["error"])
        self.assertEqual([], self.sent)

    async def test_it_is_drawn_across_the_whole_head(self):
        """672 dots, whatever is loaded. The across ladder has to be able to
        say where paper narrower than the head is sitting, and a ladder
        drawn on that paper cannot."""
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})
        status, body = await self.post("/api/printer/calibrate",
                                       {"stock": "ed1f-060wh"})
        self.assertEqual(200, status, body)
        columns = self.columns(self.sent[-1])
        self.assertEqual(0, min(columns), "it does not start at head dot 0")
        self.assertEqual(671, max(columns), "it stops short of the head")

    async def test_it_never_saves_the_head_wide_copy_it_draws_with(self):
        """It renders against a copy of the roll whose width is the print
        head's and whose margin is zero. Saving that would turn somebody's
        0.56" wrap into a 2.24" one on the press that is meant to be safe to
        try."""
        await self.loaded(margin_mm=5.2)
        await self.post("/api/printer/calibrate", {})
        _, body = await self.get("/api/stocks")
        row = next(s for s in body["stocks"] if s["id"] == "edcc-082wh")
        self.assertEqual(2.25, row["across_in"])
        self.assertEqual(5.2, row["margin_mm"])

    async def test_an_unknown_stock_is_a_404_and_not_a_blank_label(self):
        status, body = await self.post("/api/printer/calibrate",
                                       {"stock": "nothing-like-that"})
        self.assertEqual(404, status)
        self.assertIn("nothing-like-that", body["error"])


class TestTheCalibrationLabelItself(unittest.TestCase):
    """The artwork, driven rather than looked at.

    Every assertion here is about a reading being possible, and the reason
    they are this specific is that the first version of this label passed a
    weaker set. It put the copy number and an across ruler in the first 14mm
    of the sheet and started the feed numbers at 15 — and the reading the
    label exists for is taken in exactly that band: the roll it was built for
    lands its first row 9.7mm down. The first number a person could read was
    15, so a 4.7mm dead zone would have been typed in as 10, and the across
    ruler's own "0 5 10" sat where they would look for it and reads as a feed
    number. A ladder that is not readable where it is read is worse than no
    ladder, because a wrong reading is stored and printed against for ever.
    """

    CLEAR_MM = 11.4

    def head(self, across_in=2.25, feed_in=1.25):
        stock_store, = bruh_print_env.load("stores.stock")
        entry = stock_store.Stock(id="c", name="c", across_in=across_in,
                                  feed_in=feed_in)
        return stock_store.replace(entry, across_in=672 / 300, margin_mm=0.0)

    def rendered(self, stock, copy_no=1):
        render_image, label_doc = bruh_print_env.load("render.image",
                                                      "render.label")
        document = server._calibration_label(stock, copy_no)
        return render_image.render(label_doc.Label.from_dict(document), stock,
                                   max_across_dots=672)

    def periods(self, across_mm=56.9):
        """(number column, tick stretch) per period, in millimetres.

        Read off the same two constants the label is built from rather than
        off the document, because these are what the WINDOW guarantee is
        about — a test that recovered them from the elements would agree with
        whatever the label happened to draw.
        """
        out = []
        x = 0.0
        while x <= across_mm - server.CAL_COLUMN_MM + 1e-9:
            out.append(((x, x + server.CAL_COLUMN_MM),
                        (x + server.CAL_COLUMN_MM + 0.2,
                         min(across_mm, x + server.CAL_COLUMN_PERIOD_MM))))
            x += server.CAL_COLUMN_PERIOD_MM
        return out

    def feed_numbers(self, document):
        """The ladder's own numbers: a text box exactly a column wide."""
        return [e for e in document["elements"]
                if e["type"] == "text" and e["w_mm"] == server.CAL_COLUMN_MM]

    # -- the band the reading is taken in ---------------------------------
    def test_there_is_a_tick_at_raster_line_zero(self):
        """The datum every feed measurement is taken from. A ladder whose
        first mark is one line down puts every reading on the roll a line
        out, invisibly."""
        image = self.rendered(self.head()).image
        pixels = image.convert("L").load()
        for _column, (first, last) in self.periods():
            middle = round((first + last) / 2 / 25.4 * 300)
            self.assertTrue(pixels[middle, 0] < 128,
                            f"no tick at row 0 near head dot {middle}")

    def test_the_ladder_is_numbered_from_zero_every_five_millimetres(self):
        """Including 0, 5 and 10 — the three that live in the band where the
        top reading is taken, and the three the first version did not draw.
        The wizard's rule is "the first number you can see, less one per
        short tick above it", which is true only if the numbers really do
        start at the datum."""
        document = server._calibration_label(self.head(), 1)
        values = sorted({int(e["props"]["text"])
                         for e in self.feed_numbers(document)})
        self.assertEqual([0, 5, 10, 15, 20, 25, 30], values)

    def test_the_first_three_numbers_are_inside_the_reading_band(self):
        """0, 5 and 10 have to be whole and above 12.5mm, because that is
        where a die cut falls on the roll this was built for (9.7mm) and on
        any roll whose printer starts anywhere near it."""
        document = server._calibration_label(self.head(), 1)
        for value in (0, 5, 10):
            boxes = [e for e in self.feed_numbers(document)
                     if e["props"]["text"] == str(value)]
            self.assertTrue(boxes, f"the ladder has no {value}")
            for box in boxes:
                self.assertGreaterEqual(box["y_mm"], 0.0)
                self.assertLessEqual(box["y_mm"] + box["h_mm"], 12.5,
                                     f"{value} is drawn below the band it is "
                                     f"read in")

    def test_every_number_is_centred_on_its_own_tick(self):
        """Or the rule for counting the short ticks between two numbers is
        off by half a digit, which on a 1mm ladder is half a millimetre of
        dead zone typed in wrong. The 0 is the one exception and it is
        clamped rather than centred, because half of it would be off the top
        of the sheet — the tick at row 0 is what it names."""
        document = server._calibration_label(self.head(), 1)
        for box in self.feed_numbers(document):
            value = int(box["props"]["text"])
            middle = box["y_mm"] + box["h_mm"] / 2
            if value == 0:
                self.assertEqual(0.0, box["y_mm"])
                continue
            self.assertAlmostEqual(value, middle, places=6,
                                   msg=f"{value} is not centred on its tick")

    def test_the_reading_band_carries_the_ladder_and_nothing_else(self):
        """Rows 0 to 11.4 are the measurement. Asserted on the document —
        every element that reaches into the band is a feed tick or a feed
        number — because that is the rule, and then on the ink, because the
        rule is only worth what the renderer does with it."""
        document = server._calibration_label(self.head(), 1)
        for element in document["elements"]:
            if element["y_mm"] >= self.CLEAR_MM:
                continue
            if element["type"] == "line":
                continue
            self.assertEqual("text", element["type"], element)
            self.assertEqual(server.CAL_COLUMN_MM, element["w_mm"],
                             f"{element['props']['text']!r} is in the reading "
                             f"band and is not a ladder number")
            self.assertEqual(0, int(element["props"]["text"]) % 5)

    def test_no_ink_reaches_the_gutters_of_the_reading_band(self):
        """The other half, measured on the bitmap: between a number column
        and its tick stretch there is 0.2mm that belongs to neither, and past
        the last period there is the tail. A full-width rule at row 0, an
        across band an inch too high, a caption — anything that is not the
        ladder — lands in one of them."""
        render_image, = bruh_print_env.load("render.image")
        image = self.rendered(self.head()).image
        pixels = image.convert("L").load()
        rows = round(self.CLEAR_MM / 25.4 * 300)

        forbidden: list[tuple[int, int]] = []
        periods = self.periods()
        for (_c0, column_end), (tick_start, _t1) in periods:
            forbidden.append((render_image.mm_to_dots(column_end, 300),
                              render_image.mm_to_dots(tick_start, 300)))
        forbidden.append((render_image.mm_to_dots(periods[-1][1][1], 300),
                          image.width))

        for start, stop in forbidden:
            for x in range(max(0, start), min(image.width, stop)):
                for y in range(rows):
                    self.assertFalse(
                        pixels[x, y] < 128,
                        f"ink at ({x}, {y}) is outside the ladder, inside the "
                        f"band the top reading is taken in")

    # -- the window guarantee ---------------------------------------------
    def test_every_window_the_width_of_a_label_carries_a_number_column(self):
        """The design constraint the whole layout is built on. A 0.56" wrap
        is 14mm of a 57mm head and may sit anywhere along it, so a person
        holding one sees a fragment of the ladder with no view of where it
        began — and a bare run of ticks has nothing to count from.

        An interval as long as the column period always contains a multiple
        of it, so a whole column fits in any window at least `period +
        column` wide. Asserted by walking every position at tenth-millimetre
        steps rather than by restating the arithmetic, because the arithmetic
        is what was wrong the first time round."""
        columns = [column for column, _ticks in self.periods()]
        self.assertGreater(len(columns), 5)
        for step in range(0, int((56.9 - 12.0) * 10) + 1):
            start = step / 10
            self.assertTrue(
                any(start <= left and right <= start + 12.0
                    for left, right in columns),
                f"a 12mm label at {start}mm carries no whole number column")

    def test_the_first_three_numbers_survive_every_window_as_well(self):
        """The window guarantee is about a column; the reading is about the
        three numbers inside it. Both have to hold at once, or a wrap sitting
        at 3.2mm shows a ladder with nothing to count from in the only band
        that matters."""
        document = server._calibration_label(self.head(), 1)
        for value in (0, 5, 10):
            boxes = [(e["x_mm"], e["x_mm"] + e["w_mm"])
                     for e in self.feed_numbers(document)
                     if e["props"]["text"] == str(value)]
            for step in range(0, int((56.9 - 12.0) * 10) + 1):
                start = step / 10
                self.assertTrue(
                    any(start <= left and right <= start + 12.0
                        for left, right in boxes),
                    f"a 12mm label at {start}mm cannot read {value}")

    def test_it_holds_for_the_narrowest_stock_in_the_catalog(self):
        """0.4375" is 11.1mm — under the 12mm the layout is stated for, and
        in the catalog, so it is the one that decides whether the period is
        7mm or 10."""
        columns = [column for column, _ticks in self.periods()]
        for step in range(0, int((56.9 - 11.1) * 10) + 1):
            start = step / 10
            self.assertTrue(
                any(start <= left and right <= start + 11.1
                    for left, right in columns),
                f"an 11.1mm label at {start}mm carries no whole column")

    # -- the across ruler --------------------------------------------------
    def across_digits(self, document):
        """The inverted ones. That is what makes them unmistakable, and it
        is also the only thing that tells them from a feed number in the
        document — which is the point."""
        return [e for e in document["elements"]
                if e["type"] == "text" and e["props"].get("invert")]

    def test_the_across_ruler_is_drawn_inverted(self):
        """White marks on a solid black band, because it measures the other
        axis entirely and the reading it would be confused with is the one
        the label exists for. The first version drew it in ordinary black
        ticks and digits, in the gap where somebody looks for a number."""
        document = server._calibration_label(self.head(), 1)
        digits = self.across_digits(document)
        self.assertTrue(digits)
        self.assertEqual([str(m) for m in range(0, 57, 5)],
                         [e["props"]["text"] for e in digits[:12]])
        # And the band under them is solid: filled boxes with a white notch
        # at every millimetre, which is a white tick made of black ones.
        bars = [e for e in document["elements"]
                if e["type"] == "box" and e["props"].get("fill")]
        self.assertGreater(len(bars), 40)

    def test_the_across_band_never_shares_a_row_with_a_feed_number(self):
        """It lives in the gap between two of them. A band that overlapped
        one would be white-on-black ink through a number somebody is reading
        to the millimetre — and worse, it would be in the band the top
        reading is taken in if it crept up far enough."""
        document = server._calibration_label(self.head(0.56, 3.44), 1)
        numbers = [(e["y_mm"], e["y_mm"] + e["h_mm"])
                   for e in self.feed_numbers(document)]
        for digit in self.across_digits(document):
            band = (digit["y_mm"] - server.CAL_ACROSS_TICK_MM,
                    digit["y_mm"] + digit["h_mm"])
            self.assertGreaterEqual(band[0], self.CLEAR_MM,
                                    "an across band reaches into the reading")
            for top, bottom in numbers:
                self.assertFalse(band[0] < bottom and top < band[1],
                                 f"the across band {band} overlaps the feed "
                                 f"number at {top}")

    def test_the_across_ruler_is_measured_from_head_dot_zero(self):
        """It reads where the paper is, so its own zero has to be the head's
        — a ruler starting at the sheet's margin would report the margin."""
        document = server._calibration_label(self.head(), 1)
        zeros = [e for e in self.across_digits(document)
                 if e["props"]["text"] == "0"]
        self.assertTrue(zeros)
        self.assertTrue(all(e["x_mm"] <= 0.01 for e in zeros), zeros)

    def test_a_sheet_too_short_for_a_band_gets_none_and_the_route_says_so(self):
        """A label shorter than the first gap has no across ruler at all,
        which is a thing the wizard has to know: it asks for a left and a
        right reading, and "there is no ruler on my label" is a person stuck
        at a question with no answer on the paper."""
        self.assertEqual([], server.across_band_tops(12.0))
        self.assertEqual([11.4], server.across_band_tops(20.0))
        self.assertEqual([11.4, 26.4], server.across_band_tops(31.75))
        self.assertEqual([11.4, 26.4, 56.4], server.across_band_tops(87.0))
        short = self.head(2.25, 0.5)
        self.assertEqual([], self.across_digits(
            server._calibration_label(short, 1)))

    # -- the copy number ---------------------------------------------------
    def test_the_copy_number_is_boxed_in_a_gap_and_repeats(self):
        """Two labels out of one job seconds apart are otherwise told apart
        by the order somebody picked them up in. It is in a box so it is not
        read as a measurement, in the gap under 15 so it is not in one, and
        on the ladder's own period so a narrow roll cannot miss it."""
        first = server._calibration_label(self.head(), 1)
        second = server._calibration_label(self.head(), 2)
        ones = [e for e in first["elements"] if e["type"] == "text"
                and e["props"]["text"] == "1"
                and e["y_mm"] >= server.CAL_COPY_TOP_MM]
        twos = [e for e in second["elements"] if e["type"] == "text"
                and e["props"]["text"] == "2"
                and e["y_mm"] >= server.CAL_COPY_TOP_MM]
        self.assertEqual(len(ones), len(twos))
        self.assertEqual(len(self.periods()), len(ones))
        for element in ones:
            self.assertGreaterEqual(element["y_mm"], self.CLEAR_MM)

    def test_the_copy_box_never_crosses_a_tick(self):
        """It is drawn in a number column and is never wider than one: a box
        that reached into the tick stretch beside it would be ink across a
        ladder somebody is counting."""
        document = server._calibration_label(self.head(), 1)
        boxes = [e for e in document["elements"]
                 if e["type"] == "box" and not e["props"].get("fill")]
        self.assertTrue(boxes)
        columns = [column for column, _ticks in self.periods()]
        for box in boxes:
            span = (box["x_mm"], box["x_mm"] + box["w_mm"])
            self.assertTrue(
                any(left - 1e-9 <= span[0] and span[1] <= right + 1e-9
                    for left, right in columns),
                f"the copy box {span} reaches outside its column")

    # -- and the rules the first version already had -----------------------
    def test_no_number_is_printed_on_top_of_another(self):
        """Two ladders and two number columns meet on one label, and the
        first cut of the 0.7.0 label printed a "5" over a "5" on the one
        label whose whole job is being read to the millimetre. Walked on the
        real document rather than on the picture: two boxes that overlap are
        the bug whether or not the glyphs inside them happen to touch."""
        for across_in, feed_in in ((2.25, 1.25), (0.56, 3.44), (2.3125, 4.0)):
            document = server._calibration_label(
                self.head(across_in, feed_in), 1)
            boxes = [(e["x_mm"], e["y_mm"], e["x_mm"] + e["w_mm"],
                      e["y_mm"] + e["h_mm"])
                     for e in document["elements"] if e["type"] == "text"]
            for one in range(len(boxes)):
                for two in range(one + 1, len(boxes)):
                    ax0, ay0, ax1, ay1 = boxes[one]
                    bx0, by0, bx1, by1 = boxes[two]
                    self.assertFalse(
                        ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1,
                        f'{across_in}" x {feed_in}": {boxes[one]} overlaps '
                        f'{boxes[two]}')

    def test_a_number_is_big_enough_to_be_read_as_the_number_it_is(self):
        """2mm for anything on the feed ladder, which is what a person reads
        a millimetre off. The across ruler's digits are smaller because the
        whole band has to fit in the gap between two feed numbers — and they
        are white on black, which is the compensation as well as the reason
        they cannot be confused with one."""
        document = server._calibration_label(self.head(), 1)
        inverted = {id(e) for e in self.across_digits(document)}
        for element in document["elements"]:
            if element["type"] != "text":
                continue
            size = element["props"]["size_mm"]
            if id(element) in inverted:
                self.assertGreaterEqual(size, 1.5)
            else:
                self.assertGreaterEqual(size, 2.0)

    def test_it_draws_without_a_complaint_on_every_stock_in_the_catalog(self):
        """Including the narrow wrap, where 0.7.0's version had to drop its
        numbers entirely — that label was drawn to the stock's own sheet, and
        this one is drawn to the head, so the paper's width decides what is
        VISIBLE rather than what is drawn."""
        stock_store, = bruh_print_env.load("stores.stock")
        for entry in stock_store.BUILTIN:
            if entry.continuous:
                continue
            with self.subTest(stock=entry.id):
                drawn = self.rendered(
                    self.head(entry.across_in, entry.feed_in))
                self.assertEqual([], drawn.notes)


class TestSavingWhatWasRead(CalibrationCase):
    """The route between the five readings and the store.

    The panel does no arithmetic: `calibration.derive` is pure and is tested
    on its own with the numbers the owner measured. What is asserted here is
    that the readings reach it, that what comes back is stored, and that the
    two answers which are not answers store nothing.
    """

    OWNER = {"left": 0.0, "right": 57.0, "top1": 9.7, "bottom1": 22.05,
             "top2": 9.7}
    SENT = {"pre_skip_mm": 5.0, "esc_l_mm": 44.7, "variant": "plain"}

    async def save(self, **changes):
        payload = {"readings": {**self.OWNER, **changes.pop("readings", {})},
                   "printed": {**self.SENT, **changes.pop("printed", {})}}
        return await self.post("/api/stock/edcc-082wh/calibration", payload)

    async def test_the_measured_case_is_stored_and_reaches_the_wire(self):
        await self.loaded()
        status, body = await self.save()
        self.assertEqual(200, status, body)
        self.assertAlmostEqual(4.7, body["calibration"]["start_mm"], places=1)
        self.assertIn("4.7mm", body["sentence"])
        self.assertIsNone(body["next"])
        _, payload = await self.print_once()
        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual((375 - 56) * repeat, len(self.rows(payload)))

    async def test_the_first_label_hypothesis_stores_nothing_and_asks_again(self):
        """The one answer that is not an answer. `ESC @` is a real candidate
        and whether a firmware honours it is not knowable from here, so the
        route says print again rather than recording a fault one command
        might not have."""
        await self.loaded()
        _, body = await self.save(readings={"top2": 5.0})
        self.assertIsNone(body["calibration"])
        self.assertEqual("reset", body["next"]["variant"])
        _, stocks = await self.get("/api/stocks")
        row = next(s for s in stocks["stocks"] if s["id"] == "edcc-082wh")
        self.assertEqual(0.0, row["calibration"]["start_mm"])

    async def test_a_reading_that_is_not_a_number_is_refused(self):
        await self.loaded()
        status, body = await self.save(readings={"top1": "about 9"})
        self.assertEqual(400, status)
        self.assertIn("millimetres", body["error"])

    async def test_a_missing_reading_is_refused_by_name(self):
        """Not defaulted to zero: every branch turns on differences of less
        than a millimetre, so a field that quietly became zero would not be
        a slightly wrong calibration, it would be a different hypothesis."""
        await self.loaded()
        status, body = await self.post(
            "/api/stock/edcc-082wh/calibration",
            {"readings": {k: v for k, v in self.OWNER.items() if k != "top2"},
             "printed": self.SENT})
        self.assertEqual(400, status)
        self.assertIn("top2", body["error"])

    async def test_a_negative_reading_is_refused(self):
        """Every one is a distance from an edge of the label. A minus sign
        here is somebody carrying over the old offset's convention, where it
        meant "the other way" — there is no other way now, and the
        derivation decides the sign from where the two copies landed."""
        await self.loaded()
        status, body = await self.save(readings={"top1": -4.7})
        self.assertEqual(400, status)
        self.assertIn("cannot be negative", body["error"])

    async def test_a_label_wider_than_the_head_may_omit_the_right_edge(self):
        """Not a failure: the across ladder runs out at the head's last dot,
        so a wider label has nothing printed at its right edge to read."""
        await self.loaded()
        status, body = await self.save(readings={"right": ""})
        self.assertEqual(200, status, body)
        self.assertIsNotNone(body["calibration"])

    async def test_the_readings_and_what_was_printed_go_together(self):
        """A top measurement without the pre-skip it was taken against is
        not a distance from anything, so half a payload is refused rather
        than assumed."""
        await self.loaded()
        status, body = await self.post("/api/stock/edcc-082wh/calibration",
                                       {"readings": self.OWNER})
        self.assertEqual(400, status)
        self.assertIn("pre-skip", body["error"])

    async def test_it_rides_in_the_state_the_panel_opens_with(self):
        await self.loaded()
        await self.save()
        _, body = await self.get("/api/state")
        row = next(s for s in body["stocks"] if s["id"] == "edcc-082wh")
        self.assertAlmostEqual(4.7, row["calibration"]["start_mm"], places=1)
        self.assertTrue(row["calibrated"])
        self.assertAlmostEqual(27.05, row["printable_feed_mm"], places=1)

    async def test_clearing_it_gives_back_the_job_that_shipped(self):
        """A calibration is safe to try only if it is safe to undo, and the
        undo is to nothing rather than to a guessed default."""
        await self.loaded()
        _, before = await self.print_once()
        await self.save()
        _, after = await self.print_once()
        self.assertNotEqual(before, after)
        response = await self.client.delete("/api/stock/edcc-082wh/calibration")
        self.assertEqual(200, response.status)
        _, cleared = await self.print_once()
        self.assertEqual(before, cleared)

    async def test_editing_the_stock_does_not_blank_it(self):
        """Same partial-update rule as `turn`: the Edit dialog has no
        control for a calibration — it is two prints and five readings — and
        a Save there that reset it would undo a measurement made one button
        away."""
        await self.loaded()
        await self.save()
        _, body = await self.post("/api/stock", {
            "id": "edcc-082wh", "name": "Chemical-Resistant Cryo Labels",
            "across_in": 2.25, "feed_in": 1.25, "margin_mm": 2.0})
        self.assertAlmostEqual(4.7, body["stock"]["calibration"]["start_mm"],
                               places=1)


class TestTheCheckPrint(CalibrationCase):
    """The frame that proves the answer, through the ordinary print path.

    The calibration label is an instrument and is immune to every number it
    measures. This is the opposite and has to be: it goes out exactly as a
    real label does, so a frame that comes back whole is the calibration
    being right and a missing side says which way it is wrong.
    """

    async def test_it_frames_what_the_calibration_says_is_printable(self):
        """The frame is drawn at the printable rectangle, which starts at the
        dead band and not at row 0 — so the crop on the way to the printer
        takes the blank rows in front of it and the frame's top edge lands on
        the first row the printer can lay. A frame drawn from row 0 would
        have had its own top edge cropped away, and the check would fail on
        a calibration that was right."""
        await self.loaded()
        await self.calibrate(start_mm=4.7)

        entry = self.panel.stocks.require("edcc-082wh")
        full = server.stock_store.replace(entry, margin_mm=0.0)
        document = server._check_label(full, entry.dead_leading_mm())
        frame = next(e for e in document["elements"] if e["type"] == "box")
        self.assertAlmostEqual(4.7, frame["y_mm"], places=2)
        self.assertAlmostEqual(31.75, frame["y_mm"] + frame["h_mm"], places=1)

        status, body = await self.post("/api/printer/check", {})
        self.assertEqual(200, status, body)
        self.assertEqual(1, body["printed"])
        rows = self.rows(self.sent[-1])
        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual((375 - 56) * repeat, len(rows))
        self.assertTrue(any(rows[0]), "nothing on the first printable row")
        self.assertTrue(any(rows[-1]), "nothing on the last row")
        # And it is a frame rather than a band: the rows between its edges
        # carry the two uprights and the words, not a solid rule.
        middle = rows[len(rows) // 2]
        self.assertTrue(any(middle))
        self.assertLess(sum(bin(b).count("1") for b in middle),
                        sum(bin(b).count("1") for b in rows[0]))

    async def test_it_goes_through_the_same_path_as_a_real_label(self):
        """Which is what makes it a proof rather than a picture: the crop,
        the placement and the feed are the ones every other label gets."""
        await self.loaded()
        await self.post("/api/printer/check", {})
        first = self.sent[-1]
        await self.calibrate(start_mm=4.7, across_mm=3.0)
        await self.post("/api/printer/check", {})
        self.assertNotEqual(first, self.sent[-1])

    async def test_an_uncalibrated_roll_frames_the_whole_label(self):
        await self.loaded()
        await self.post("/api/printer/check", {})
        rows = self.rows(self.sent[-1])
        self.assertEqual(375 * protocol.LINE_REPEAT["graphics"], len(rows))
        self.assertTrue(any(rows[0]))
        self.assertTrue(any(rows[-1]))

    async def test_an_unknown_stock_is_a_404(self):
        status, body = await self.post("/api/printer/check",
                                       {"stock": "nothing-like-that"})
        self.assertEqual(404, status)
        self.assertIn("nothing-like-that", body["error"])


class TestTheStoreRemembersWhatWasMeasured(unittest.TestCase):
    """The model, including the four fields it replaced.

    A stock saved by 0.6.0 through 0.8.x carries somebody's ruler
    measurements at the top level, and dropping them would silently
    un-calibrate a roll that was working.
    """

    def setUp(self):
        self.stock_store, = bruh_print_env.load("stores.stock")
        self.path = Path(tempfile.mkdtemp()) / "stocks.json"

    def store(self, rows):
        self.path.write_text(json.dumps({"stocks": rows, "hidden": []}))
        return self.stock_store.StockStore(self.path)

    def test_the_four_old_fields_become_the_one_calibration(self):
        """The two across numbers were always one edge, so they add; and a
        correction that moved artwork 4.7mm back toward the leading edge was
        describing a printer that started 4.7mm late, so the start is the
        offset's negation."""
        entry = self.store([{
            "id": "edcc-082wh", "name": "Cryo", "across_in": 2.25,
            "feed_in": 1.25, "offset_feed_mm": -4.7,
            "offset_across_mm": -0.4, "media_across_mm": 7.3,
            "gap_mm": 1.5,
        }]).require("edcc-082wh")
        self.assertAlmostEqual(4.7, entry.calibration.start_mm, places=2)
        self.assertAlmostEqual(6.9, entry.calibration.across_mm, places=2)
        self.assertEqual(1.5, entry.calibration.gap_mm)
        self.assertEqual(0.0, entry.calibration.after_tear_mm)

    def test_a_row_from_before_any_of_them_loads_uncalibrated(self):
        entry = self.store([{"id": "x", "name": "X", "across_in": 2.0,
                             "feed_in": 1.0}]).require("x")
        self.assertFalse(entry.calibration.measured)
        self.assertIsNone(entry.calibration.gap_mm)

    def test_a_row_of_nonsense_does_not_take_the_catalog_with_it(self):
        """This runs over a file another release wrote. A stock that fails
        to load is a roll that vanishes out of the catalog with the panel
        reporting nothing at all."""
        store = self.store([
            {"id": "x", "name": "X", "across_in": 2.0, "feed_in": 1.0,
             "offset_feed_mm": "a bit", "media_across_mm": None,
             "gap_mm": "nope"},
            "not even a row",
        ])
        entry = store.require("x")
        self.assertEqual(0.0, entry.calibration.start_mm)
        self.assertEqual(0.0, entry.calibration.across_mm)
        self.assertIsNone(entry.calibration.gap_mm)

    def test_only_the_new_shape_is_written_back(self):
        """Carrying the old keys along "just in case" is how two writers end
        up disagreeing about which of them a reader believes."""
        store = self.store([{
            "id": "x", "name": "X", "across_in": 2.0, "feed_in": 1.0,
            "offset_feed_mm": -4.7, "media_across_mm": 7.3}])
        store.put(store.require("x"))
        raw = json.loads(self.path.read_text())["stocks"][0]
        self.assertNotIn("offset_feed_mm", raw)
        self.assertNotIn("media_across_mm", raw)
        self.assertAlmostEqual(4.7, raw["calibration"]["start_mm"], places=2)

    def test_a_roll_with_nothing_to_correct_is_still_a_roll_somebody_read(self):
        """Seven default numbers is what a perfect printer measures, and it
        is also what a roll nobody has touched holds. The stamp is what tells
        them apart, and the panel keeps offering the calibration for ever
        without it."""
        entry = self.stock_store.Stock(
            id="x", name="X", across_in=2.25, feed_in=1.25,
            calibration=self.stock_store.Calibration(
                measured_at=1_700_000_000.0))
        self.assertTrue(entry.calibration.measured)
        self.assertTrue(entry.as_dict()["calibrated"])
        self.assertFalse(self.stock_store.Stock(
            id="y", name="Y", across_in=2.25,
            feed_in=1.25).as_dict()["calibrated"])

    def test_a_calibration_from_before_the_stamp_still_reads_as_measured(self):
        """A roll calibrated by 0.6.0 through 0.8.x carries numbers and no
        stamp, and those numbers are still somebody's measurement."""
        entry = self.store([{
            "id": "x", "name": "X", "across_in": 2.25, "feed_in": 1.25,
            "offset_feed_mm": -4.7}]).require("x")
        self.assertIsNone(entry.calibration.measured_at)
        self.assertTrue(entry.calibration.measured)

    def test_a_swap_keeps_the_across_edge_and_drops_the_rest(self):
        """Where the paper's left edge sits is a fact about the liner, and
        exchanging which catalog number is called "across" does not slide
        the roll along the head. The other four were read off one printed
        label, against a sheet drawn to the shape the swap has just declared
        wrong."""
        entry = self.stock_store.Stock(
            id="x", name="X", across_in=2.25, feed_in=1.25,
            calibration=self.stock_store.Calibration(
                across_mm=7.3, start_mm=4.7, after_tear_mm=2.0,
                length_mm=34.0, gap_mm=1.5, job_start="reset",
                measured_at=1_700_000_000.0))
        swapped = entry.swapped()
        self.assertEqual(7.3, swapped.calibration.across_mm)
        self.assertIsNone(swapped.calibration.measured_at,
                          "a roll holding a stamp and four zeroed "
                          "measurements reads as calibrated for ever")
        self.assertEqual("reset", swapped.calibration.job_start)
        self.assertEqual(0.0, swapped.calibration.start_mm)
        self.assertEqual(0.0, swapped.calibration.after_tear_mm)
        self.assertIsNone(swapped.calibration.length_mm)
        self.assertIsNone(swapped.calibration.gap_mm)

    def test_the_helpers_the_three_readers_share(self):
        """The renderer, the designer and the send path each need "how much
        of this label can I use", and three answers to that is three chances
        for a box to be laid into a band the printer will not reach."""
        entry = self.stock_store.Stock(
            id="x", name="X", across_in=2.25, feed_in=1.25,
            calibration=self.stock_store.Calibration(start_mm=4.7,
                                                     after_tear_mm=2.0))
        self.assertAlmostEqual(4.7, entry.dead_leading_mm(), places=2)
        self.assertAlmostEqual(6.7, entry.dead_leading_mm(True), places=2)
        self.assertAlmostEqual(31.75 - 4.7, entry.printable_feed_mm(),
                               places=2)
        self.assertAlmostEqual(31.75 - 6.7, entry.printable_feed_mm(True),
                               places=2)

    def test_ink_before_the_die_cut_leaves_the_whole_label_printable(self):
        """A negative start is a pre-skip rather than a dead band, so there
        is nothing to take off the label — and `dead_leading_mm` says zero
        rather than a negative, which would make the printable length longer
        than the paper."""
        entry = self.stock_store.Stock(
            id="x", name="X", across_in=2.25, feed_in=1.25,
            calibration=self.stock_store.Calibration(start_mm=-2.0))
        self.assertEqual(0.0, entry.dead_leading_mm())
        self.assertAlmostEqual(31.75, entry.printable_feed_mm(), places=2)

    def test_a_measured_length_is_what_the_printer_is_told(self):
        entry = self.stock_store.Stock(
            id="x", name="X", across_in=2.25, feed_in=1.25,
            calibration=self.stock_store.Calibration(length_mm=34.0))
        self.assertEqual(34.0, entry.measured_feed_mm)
        self.assertEqual(31.75, self.stock_store.Stock(
            id="x", name="X", across_in=2.25, feed_in=1.25).measured_feed_mm)
