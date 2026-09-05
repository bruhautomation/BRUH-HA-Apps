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
        self.assertTrue(self.sent[-1].startswith(
            protocol.select_roll(protocol.ROLL_RIGHT)))

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
                    payload.startswith(bytes([0x1B, ord("q"), wire])),
                    payload[:6])
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


class TestWhereThePrintingStarts(PanelCase):
    """The offset, through the routes and out onto the wire.

    Everything above the wire was measured correct on this exact roll before
    any of it was written — the raster is 672 x 375 with its ink inset 24
    dots on all four sides — and the label still came out 4.7mm low. So what
    is asserted here is the thing nothing else could see: that the raster
    which reaches the printer is the one that moved, and that the label, the
    document and the preview are untouched.
    """

    async def loaded(self, margin_mm=5.2):
        """The roll from the report: a 2.25" x 1.25" cryo label whose owner
        had typed a 5.2mm border in by hand, because the panel offered them
        nothing else to do about a printer starting late."""
        await self.post("/api/stock", {
            "id": "edcc-082wh", "name": "Chemical-Resistant Cryo Labels",
            "across_in": 2.25, "feed_in": 1.25, "margin_mm": margin_mm})
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})

    def raster_rows(self, payload):
        """The SYN lines out of a job, the way a printer reads them."""
        rows, index = [], 0
        while index < len(payload):
            byte = payload[index]
            if byte == protocol.ESC:
                letter = chr(payload[index + 1])
                index += 2 + {"L": 2, "B": 1, "D": 1, "q": 1}.get(letter, 0)
                if letter == "f":  # not sent, and this proves it
                    raise AssertionError("ESC f reached the printer")
            elif byte == protocol.SYN:
                rows.append(payload[index + 1:index + 85])
                index += 85
            else:
                raise AssertionError(f"byte {byte:#x} at {index}")
        return rows

    def first_inked(self, payload):
        for number, row in enumerate(self.raster_rows(payload)):
            if any(row):
                return number
        raise AssertionError("nothing in this job has any ink in it")

    async def print_once(self):
        status, body = await self.post(
            "/api/print", {"label": self.label(text="Rice")})
        self.assertEqual(200, status, body)
        return body, self.sent[-1]

    async def test_the_raster_that_reaches_the_printer_is_the_one_that_moved(self):
        """4.7mm is 56 dot lines at 300 dpi, and the default quality is the
        300x600 graphics mode, where every raster row goes twice — so the
        wire moves 112 lines for a 56-line shift. The doubling and the
        offset are one fact and they must not drift apart."""
        await self.loaded()
        _, before = await self.print_once()
        _, updated = await self.post("/api/stock/edcc-082wh/offset",
                                     {"offset_feed_mm": -4.7})
        _, after = await self.print_once()

        repeat = protocol.LINE_REPEAT["graphics"]
        self.assertEqual(56, (self.first_inked(before)
                              - self.first_inked(after)) // repeat)
        self.assertEqual(112, self.first_inked(before) - self.first_inked(after))
        self.assertEqual(len(self.raster_rows(before)),
                         len(self.raster_rows(after)),
                         "the job grew or shrank — the sheet is one label")
        self.assertEqual(-4.7, updated["stock"]["offset_feed_mm"])

    async def test_the_length_budget_is_unchanged_by_an_offset(self):
        """ESC L is about reaching the sense hole, which does not move
        because the artwork did."""
        await self.loaded()
        _, before = await self.print_once()
        await self.post("/api/stock/edcc-082wh/offset", {"offset_feed_mm": -4.7})
        _, after = await self.print_once()
        marker = bytes([protocol.ESC, ord("L")])
        self.assertEqual(before[before.index(marker):before.index(marker) + 4],
                         after[after.index(marker):after.index(marker) + 4])

    async def test_an_across_offset_moves_the_bits_within_a_line(self):
        await self.loaded()
        _, before = await self.print_once()
        await self.post("/api/stock/edcc-082wh/offset",
                        {"offset_across_mm": -2.0})
        _, after = await self.print_once()
        rows_before = [r for r in self.raster_rows(before) if any(r)]
        rows_after = [r for r in self.raster_rows(after) if any(r)]
        self.assertEqual(len(rows_before), len(rows_after))
        left = lambda row: next(  # noqa: E731
            i * 8 + b for i, byte in enumerate(row) for b in range(8)
            if byte & (1 << (7 - b)))
        self.assertEqual(round(2.0 / 25.4 * 300),
                         left(rows_before[0]) - left(rows_after[0]))

    async def test_a_default_roll_is_byte_for_byte_what_it_always_was(self):
        """0.0 on both axes is the only honest default — nothing in a
        container can measure a print head — so a house that has never
        opened this dialog must get exactly the job it got before."""
        await self.loaded()
        _, before = await self.print_once()
        await self.post("/api/stock/edcc-082wh/offset",
                        {"offset_feed_mm": 0, "offset_across_mm": 0})
        _, after = await self.print_once()
        self.assertEqual(before, after)

    async def test_the_offset_is_not_part_of_the_label(self):
        """It is a correction to where the machine puts the paper. A preview
        that drew it would be showing somebody their printer's registration
        as if it were their own layout — and the design canvas is where
        boxes get dragged against it."""
        await self.loaded()
        first = await self.client.post("/api/preview",
                                       json={"label": self.label(text="Rice")})
        png_before = await first.read()
        await self.post("/api/stock/edcc-082wh/offset", {"offset_feed_mm": -4.7})
        second = await self.client.post("/api/preview",
                                        json={"label": self.label(text="Rice")})
        self.assertEqual(png_before, await second.read())

    async def test_a_shift_that_costs_ink_prints_and_says_so(self):
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset",
                        {"offset_feed_mm": -20.0})
        body, payload = await self.print_once()
        self.assertEqual(1, body["printed"])
        self.assertTrue(any("past the leading edge" in note
                            for note in body["notes"]), body["notes"])
        self.assertTrue(any("Where the printing starts" in note
                            for note in body["notes"]))

    async def test_an_offset_past_an_inch_is_refused_with_a_sentence(self):
        """Refused rather than clamped: a clamp would print something other
        than what the box says, on a control whose entire purpose is that
        the two agree."""
        await self.loaded()
        status, body = await self.post("/api/stock/edcc-082wh/offset",
                                       {"offset_feed_mm": 40})
        self.assertEqual(400, status)
        self.assertIn("inch", body["error"])
        _, state = await self.get("/api/stocks")
        entry = next(s for s in state["stocks"] if s["id"] == "edcc-082wh")
        self.assertEqual(0.0, entry["offset_feed_mm"])

    async def test_an_offset_that_is_not_a_number_is_refused(self):
        await self.loaded()
        status, body = await self.post("/api/stock/edcc-082wh/offset",
                                       {"offset_feed_mm": "a bit"})
        self.assertEqual(400, status)
        self.assertIn("millimetres", body["error"])

    async def test_naming_one_axis_leaves_the_other_alone(self):
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset",
                        {"offset_feed_mm": -4.7, "offset_across_mm": -1.2})
        _, body = await self.post("/api/stock/edcc-082wh/offset",
                                  {"offset_feed_mm": -5.0})
        self.assertEqual(-5.0, body["stock"]["offset_feed_mm"])
        self.assertEqual(-1.2, body["stock"]["offset_across_mm"])

    async def test_editing_the_stock_does_not_blank_the_offset(self):
        """Same partial-update rule as `turn`: the Edit dialog has no
        control for this, and a Save there that reset it would undo a
        measurement made one button away."""
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset", {"offset_feed_mm": -4.7})
        _, body = await self.post("/api/stock", {
            "id": "edcc-082wh", "name": "Chemical-Resistant Cryo Labels",
            "across_in": 2.25, "feed_in": 1.25, "margin_mm": 2.0})
        self.assertEqual(-4.7, body["stock"]["offset_feed_mm"])

    async def test_the_offset_survives_a_swap(self):
        """A swap fixes which of the catalog's two numbers is which. The
        offsets are in the printer's axes, which do not move when it does —
        and a swap is not a reason to throw away a ruler measurement."""
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset", {"offset_feed_mm": -4.7})
        _, body = await self.post("/api/stock/edcc-082wh/swap", {})
        self.assertEqual(-4.7, body["stock"]["offset_feed_mm"])

    async def test_it_rides_in_the_state_the_panel_opens_with(self):
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset", {"offset_feed_mm": -4.7})
        _, body = await self.get("/api/state")
        entry = next(s for s in body["stocks"] if s["id"] == "edcc-082wh")
        self.assertEqual(-4.7, entry["offset_feed_mm"])
        self.assertEqual(0.0, entry["offset_across_mm"])


class TestTheCalibrationLabel(PanelCase):
    """The label you measure the offset with.

    The ruler cannot do this job and that is structural, not a wording
    problem: it is drawn inside the stock's own border, so on the roll in
    the report — which carried 5.2mm of it — there was nothing within 5mm of
    the die cut to hold a ruler against.
    """

    async def loaded(self, margin_mm=5.2):
        await self.post("/api/stock", {
            "id": "edcc-082wh", "name": "Chemical-Resistant Cryo Labels",
            "across_in": 2.25, "feed_in": 1.25, "margin_mm": margin_mm})
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})

    def render(self, document, entry):
        render_image, label_doc = bruh_print_env.load("render.image",
                                                      "render.label")
        return render_image.render(label_doc.Label.from_dict(document), entry)

    def ink_box(self, rendered):
        render_image, = bruh_print_env.load("render.image")
        return render_image._ink_box(rendered.image)

    def test_it_is_drawn_to_the_sheet_and_the_ruler_is_not(self):
        """The one difference that matters, asserted as a difference: the
        calibration label's ink starts at row 0 and column 0 of the sheet,
        and the ruler's starts a border in."""
        stock_store, = bruh_print_env.load("stores.stock")
        entry = stock_store.Stock(id="edcc-082wh", name="Cryo",
                                  across_in=2.25, feed_in=1.25, margin_mm=5.2)
        full = stock_store.replace(entry, margin_mm=0.0)

        calibration = self.ink_box(
            self.render(server._calibration_label(full), full))
        self.assertEqual((0, 0), calibration[:2])

        ruler = self.ink_box(self.render(server._ruler_label(entry), entry))
        border = round(5.2 / 25.4 * 300)
        self.assertGreaterEqual(ruler[0], border - 1)
        self.assertGreaterEqual(ruler[1], border - 1)

    def test_the_ticks_are_one_millimetre_apart_from_the_corner(self):
        """A scale that is not where it claims to be is worse than no scale:
        somebody reads it, types the number, and the label moves the wrong
        way. So the ticks are counted at the dot rows they should be at."""
        stock_store, = bruh_print_env.load("stores.stock")
        full = stock_store.Stock(id="c", name="c", across_in=2.25,
                                 feed_in=1.25, margin_mm=0.0)
        image = self.render(server._calibration_label(full), full).image
        pixels = image.convert("L").load()
        for millimetre in (1, 2, 3, 5, 10):
            row = round(millimetre / 25.4 * 300)
            column = round(millimetre / 25.4 * 300)
            self.assertTrue(pixels[0, row] < 128,
                            f"no feed tick at {millimetre}mm")
            self.assertTrue(pixels[column, 0] < 128,
                            f"no across tick at {millimetre}mm")

    def test_it_fits_a_narrow_wrap_without_a_complaint(self):
        """0.56" across is 14mm, which is not room for numbers beside a
        ladder — so it draws the ladder and drops the numbers rather than
        drawing a digit crammed into a tick."""
        stock_store, = bruh_print_env.load("stores.stock")
        full = stock_store.Stock(id="w", name="w", across_in=0.56,
                                 feed_in=3.44, margin_mm=0.0)
        drawn = self.render(server._calibration_label(full), full)
        self.assertEqual([], drawn.notes)
        self.assertEqual((0, 0), self.ink_box(drawn)[:2])

    def test_no_two_numbers_are_printed_over_each_other(self):
        """The two ladders meet at the corner, so their first numbers want
        the same few square millimetres — and the first cut drew both, which
        put a "5" on top of a "5" on the one label whose whole job is being
        read to the millimetre. The digit is dropped where it would collide
        and the 1mm ticks carry that stretch, so this walks the real document
        rather than the picture: two boxes that overlap are the bug whether
        or not the glyphs inside them happen to touch."""
        stock_store, = bruh_print_env.load("stores.stock")
        for across_in, feed_in in ((2.25, 1.25), (2.3125, 4.0), (1.125, 3.5)):
            full = stock_store.Stock(id="c", name="c", across_in=across_in,
                                     feed_in=feed_in, margin_mm=0.0)
            boxes = [
                (e["x_mm"], e["y_mm"], e["x_mm"] + e["w_mm"],
                 e["y_mm"] + e["h_mm"])
                for e in server._calibration_label(full)["elements"]
                if e["type"] == "text"
            ]
            for one in range(len(boxes)):
                for two in range(one + 1, len(boxes)):
                    ax0, ay0, ax1, ay1 = boxes[one]
                    bx0, by0, bx1, by1 = boxes[two]
                    overlaps = (ax0 < bx1 and bx0 < ax1
                                and ay0 < by1 and by0 < ay1)
                    self.assertFalse(
                        overlaps,
                        f'{across_in}" x {feed_in}": {boxes[one]} overlaps '
                        f'{boxes[two]}')

    async def test_printing_it_goes_through_the_ordinary_print_path(self):
        """Which is what makes printing it again the check on a correction:
        the offset is applied to it exactly as it is to every other label."""
        await self.loaded()
        status, body = await self.post("/api/printer/calibrate", {})
        self.assertEqual(200, status, body)
        self.assertEqual(1, body["printed"])
        self.assertEqual("left", body["side"])
        first = self.sent[-1]

        await self.post("/api/stock/edcc-082wh/offset", {"offset_feed_mm": -4.7})
        await self.post("/api/printer/calibrate", {})
        self.assertNotEqual(first, self.sent[-1],
                            "the offset did not reach the calibration label, "
                            "so printing it again cannot check anything")

    async def test_it_never_saves_the_zero_margin_copy_it_draws_with(self):
        """It renders against a borderless copy of the roll. Saving that
        would silently take somebody's measured border away, on the one
        press that is supposed to be safe to try."""
        await self.loaded()
        await self.post("/api/printer/calibrate", {})
        _, body = await self.get("/api/stocks")
        entry = next(s for s in body["stocks"] if s["id"] == "edcc-082wh")
        self.assertEqual(5.2, entry["margin_mm"])

    async def test_an_unknown_stock_is_a_404_and_not_a_blank_label(self):
        status, body = await self.post("/api/printer/calibrate",
                                       {"stock": "nothing-like-that"})
        self.assertEqual(404, status)
        self.assertIn("nothing-like-that", body["error"])


class TestWhereThePaperSitsUnderTheHead(PanelCase):
    """The narrow-roll half of "where the printing starts", end to end.

    The report: a solid-fill label on the 0.56" x 3.44" cryo wrap, inked
    across 335px of a 687px label — 49% of its width, from one edge, ending
    dead at the halfway point — and no value of the 0.6.0 across offset
    changed anything. It could not: that offset moves artwork inside a sheet
    that is 168 dots wide, and the sheet itself always began at head dot 0.

    So what is asserted here is the dot columns of the head, off the payload
    that would have been written.
    """

    HEAD_BYTES = 84

    async def loaded(self):
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})

    def wrap_label(self):
        """Solid fill, which is what was printed: every column of the sheet
        carries ink, so the inked columns are the columns of the head."""
        return {"stock": "ed1f-060wh", "rotate": 0, "elements": [
            {"type": "box", "x_mm": 0, "y_mm": 0, "w_mm": 500, "h_mm": 500,
             "props": {"fill": True, "stroke_mm": 0}}]}

    def head_columns(self, payload):
        """Which head dots a job asks for, walking the wire the way a
        printer does."""
        columns = set()
        index = 0
        while index < len(payload):
            byte = payload[index]
            if byte == protocol.ESC:
                letter = chr(payload[index + 1])
                index += 2 + {"L": 2, "B": 1, "D": 1, "q": 1}.get(letter, 0)
            elif byte == protocol.SYN:
                row = payload[index + 1:index + 1 + self.HEAD_BYTES]
                for position, value in enumerate(row):
                    for bit in range(8):
                        if value & (1 << (7 - bit)):
                            columns.add(position * 8 + bit)
                index += 1 + self.HEAD_BYTES
            else:
                raise AssertionError(f"byte {byte:#x} at {index}")
        return columns

    async def print_wrap(self):
        status, body = await self.post("/api/print",
                                       {"label": self.wrap_label()})
        self.assertEqual(200, status, body)
        return body, self.sent[-1]

    async def test_the_reported_case_lands_on_head_dots_0_to_167(self):
        """Reproduced through the real routes before anything is asked of
        the new control: with nothing measured, the whole 168-dot sheet is
        against the head's first dot and the other 504 dots are never asked
        for. On a roll whose paper is not there, that is the half-inked
        label in the photograph."""
        await self.loaded()
        _, payload = await self.print_wrap()
        columns = self.head_columns(payload)
        self.assertEqual(24, min(columns), "the renderer's 2mm border")
        self.assertEqual(143, max(columns))
        self.assertFalse([c for c in columns if c > 167])

    async def test_a_measured_position_moves_it_along_the_head(self):
        await self.loaded()
        _, before = await self.print_wrap()
        status, saved = await self.post("/api/stock/ed1f-060wh/offset",
                                        {"media_across_mm": 7.3})
        self.assertEqual(200, status, saved)
        self.assertEqual(7.3, saved["stock"]["media_across_mm"])
        _, after = await self.print_wrap()

        shift = 86  # 7.3mm at 300 dpi, rounded once
        self.assertEqual({c + shift for c in self.head_columns(before)},
                         self.head_columns(after))
        self.assertEqual(110, min(self.head_columns(after)))

    async def test_the_across_offset_still_cannot_do_this_job(self):
        """The half that explains "I try and try and it doesn't do
        anything": an across offset shifts artwork inside a 168-dot sheet,
        so on a solid fill it moves nothing the head can see — the sheet is
        already full, and what leaves one edge is simply lost."""
        await self.loaded()
        _, before = await self.print_wrap()
        await self.post("/api/stock/ed1f-060wh/offset",
                        {"offset_across_mm": 4.0})
        _, after = await self.print_wrap()
        self.assertLessEqual(max(self.head_columns(after)), 167,
                             "an across offset reached past the sheet")
        self.assertEqual(min(self.head_columns(before)) + 47,
                         min(self.head_columns(after)),
                         "it moved ink within the label, and only there")

    async def test_a_roll_nobody_measured_prints_the_job_it_always_did(self):
        """0.0 is the only honest default — nothing in a container can see a
        print head — so this must be byte-for-byte identical."""
        await self.loaded()
        _, before = await self.print_wrap()
        await self.post("/api/stock/ed1f-060wh/offset",
                        {"media_across_mm": 0})
        _, after = await self.print_wrap()
        self.assertEqual(before, after)

    async def test_a_position_that_costs_ink_prints_and_says_so(self):
        """The standing rule: the stock/roll mismatch is the only refusal.
        A position that pushes the label past the head's last dot still
        prints what fits, with a note naming the amount and the edge."""
        await self.loaded()
        await self.post("/api/stock/ed1f-060wh/offset",
                        {"media_across_mm": 50.0})
        body, payload = await self.print_wrap()
        note = " ".join(body["notes"])
        self.assertIn("past the head’s last dot", note)
        self.assertIn("50.0mm in from the print head", note)
        self.assertLessEqual(max(self.head_columns(payload)), 671)

    async def test_a_negative_position_is_refused_with_a_sentence(self):
        """Paper cannot begin before the head's first dot, and a minus here
        is somebody reading it as an offset — which is the one confusion
        this control has to avoid."""
        await self.loaded()
        status, body = await self.post("/api/stock/ed1f-060wh/offset",
                                       {"media_across_mm": -7.3})
        self.assertEqual(400, status)
        self.assertIn("cannot be negative", body["error"])
        _, state = await self.get("/api/stocks")
        entry = next(s for s in state["stocks"] if s["id"] == "ed1f-060wh")
        self.assertEqual(0.0, entry["media_across_mm"])

    async def test_a_position_past_the_head_is_refused_and_names_the_head(self):
        await self.loaded()
        status, body = await self.post("/api/stock/ed1f-060wh/offset",
                                       {"media_across_mm": 90})
        self.assertEqual(400, status)
        self.assertIn("56.9mm wide", body["error"])

    async def test_the_two_quantities_are_saved_apart(self):
        """They are typed in different boxes and they clip against different
        edges; a Save that wrote one into the other would be the whole bug
        again, silently."""
        await self.loaded()
        await self.post("/api/stock/ed1f-060wh/offset",
                        {"media_across_mm": 7.3, "offset_across_mm": -0.4})
        _, body = await self.get("/api/stocks")
        entry = next(s for s in body["stocks"] if s["id"] == "ed1f-060wh")
        self.assertEqual(7.3, entry["media_across_mm"])
        self.assertEqual(-0.4, entry["offset_across_mm"])

    async def test_editing_the_stock_does_not_blank_the_position(self):
        await self.loaded()
        await self.post("/api/stock/ed1f-060wh/offset",
                        {"media_across_mm": 7.3})
        _, body = await self.post("/api/stock", {
            "id": "ed1f-060wh", "name": "Cryogenic Labels",
            "across_in": 0.56, "feed_in": 3.44})
        self.assertEqual(7.3, body["stock"]["media_across_mm"])

    async def test_the_position_is_not_part_of_the_label(self):
        """It is a correction to the machine, so the preview is untouched —
        the same rule the offsets follow. A preview that moved with it would
        be showing somebody their printer's geometry as their layout."""
        await self.loaded()
        response = await self.client.post("/api/preview",
                                          json={"label": self.wrap_label()})
        before = await response.read()
        await self.post("/api/stock/ed1f-060wh/offset",
                        {"media_across_mm": 7.3})
        response = await self.client.post("/api/preview",
                                          json={"label": self.wrap_label()})
        self.assertEqual(before, await response.read())


class TestTheScaleAcrossTheHead(PanelCase):
    """The instrument for the number above.

    Neither of the other two labels can answer this and that is structural,
    not a wording problem: both are drawn to the stock's own sheet, which on
    a 0.56" wrap is 168 dots, so every mark they make is inside the very
    thing whose position is in question.
    """

    HEAD_BYTES = 84

    WRAP = {"stock": "ed1f-060wh"}

    async def loaded(self):
        await self.post("/api/roll/left", {"stock": "ed1f-060wh"})

    def columns(self, payload):
        return TestWhereThePaperSitsUnderTheHead.head_columns(self, payload)

    async def test_it_prints_right_across_the_head(self):
        await self.loaded()
        status, body = await self.post("/api/printer/head-scale", self.WRAP)
        self.assertEqual(200, status, body)
        self.assertEqual(1, body["printed"])
        self.assertEqual("left", body["side"])
        self.assertEqual(56.9, body["head_mm"])

        columns = self.columns(self.sent[-1])
        self.assertEqual(0, min(columns), "it does not start at head dot 0")
        self.assertEqual(671, max(columns), "it stops short of the head")

    async def test_it_is_numbered_often_enough_to_read_from_a_fragment(self):
        """The whole design. The person holding it sees a strip of paper
        with part of a ruler on it and no view of where that ruler began, so
        a bare ladder is unreadable — there is nothing to count from. Every
        5mm carries a digit, which is two or three of them on 14mm of wrap
        wherever the paper turns out to sit."""
        entry = self.panel.stocks.require("ed1f-060wh")
        head = server.stock_store.replace(entry, across_in=672 / 300,
                                          margin_mm=0.0)
        document = server._head_scale_label(head)
        numbers = [e for e in document["elements"] if e["type"] == "text"]
        self.assertEqual([str(m) for m in range(0, 57, 5)],
                         [e["props"]["text"] for e in numbers])
        for one in range(len(numbers)):
            for two in range(one + 1, len(numbers)):
                a, b = numbers[one], numbers[two]
                self.assertFalse(
                    a["x_mm"] < b["x_mm"] + b["w_mm"]
                    and b["x_mm"] < a["x_mm"] + a["w_mm"],
                    f"{a['props']['text']} overlaps {b['props']['text']}")

    async def test_neither_across_correction_is_applied_to_it(self):
        """It is an absolute instrument or it is nothing: a scale that moved
        with the number it measures reads the same thing however wrong that
        number is, so printing it again could never check anything."""
        await self.loaded()
        await self.post("/api/printer/head-scale", self.WRAP)
        first = self.sent[-1]
        await self.post("/api/stock/ed1f-060wh/offset",
                        {"media_across_mm": 7.3, "offset_across_mm": -2.0})
        await self.post("/api/printer/head-scale", self.WRAP)
        self.assertEqual(first, self.sent[-1])

    async def test_the_feed_offset_still_reaches_it(self):
        """Which is the other half of the same rule: a feed offset moves the
        scale along the roll and cannot disturb an across reading, so
        leaving it off would be printing this one label somewhere the rest
        of the roll is not."""
        await self.loaded()
        await self.post("/api/printer/head-scale", self.WRAP)
        first = self.sent[-1]
        await self.post("/api/stock/ed1f-060wh/offset", {"offset_feed_mm": -4.0})
        await self.post("/api/printer/head-scale", self.WRAP)
        self.assertNotEqual(first, self.sent[-1])

    async def test_it_never_saves_the_head_wide_copy_it_draws_with(self):
        """It renders against a copy of the roll whose width is the print
        head's. Saving that would turn somebody's 0.56" wrap into a 2.24"
        one on the press that is meant to be safe to try."""
        await self.loaded()
        await self.post("/api/printer/head-scale", self.WRAP)
        _, body = await self.get("/api/stocks")
        entry = next(s for s in body["stocks"] if s["id"] == "ed1f-060wh")
        self.assertEqual(0.56, entry["across_in"])
        self.assertEqual(2.0, entry["margin_mm"])

    async def test_an_unknown_stock_is_a_404(self):
        status, body = await self.post("/api/printer/head-scale",
                                       {"stock": "nothing-like-that"})
        self.assertEqual(404, status)
        self.assertIn("nothing-like-that", body["error"])


class TestTheGapBetweenLabels(PanelCase):
    """`ESC L` is defined hole to hole, and this is the half of it nobody
    could measure from inside a container.

    The reporter set the feed offset to 0, then -8mm, then -4mm on the 2.25"
    roll and photographed each. Everything moved exactly as the offset
    predicts, and the dead band at the LEADING edge did not move at all —
    ~4mm every time. So the printer begins laying ink about 4mm past the
    leading edge and `offset_raster` structurally cannot touch that: it
    moves artwork within a sheet that is one label long.

    Whose fault the late start is remains open, and deliberately so. Either
    it is the printer's top of form, or it is our own over-feed: the search
    budget is the label plus 25%, 469 dot lines for a 375-line label, against
    a hole-to-hole pitch nearer 394. What is built is the instrument to
    settle it, not a guess at the answer.
    """

    async def loaded(self):
        await self.post("/api/roll/left", {"stock": "edcc-082wh"})

    def length(self, payload):
        marker = bytes([protocol.ESC, ord("L")])
        index = payload.index(marker)
        return (payload[index + 2] << 8) | payload[index + 3]

    async def print_once(self):
        status, body = await self.post("/api/print",
                                       {"label": self.label(text="Rice")})
        self.assertEqual(200, status, body)
        return body, self.sent[-1]

    async def test_unmeasured_is_byte_for_byte_the_job_that_shipped(self):
        """The promise the whole control is built under. 375 lines plus 25%
        is 469, doubled by the default graphics mode to 938 — which is what
        main sends today, and what a house that never opens this gets."""
        await self.loaded()
        _, payload = await self.print_once()
        self.assertEqual(938, self.length(payload))
        _, entry = await self.get("/api/stocks")
        row = next(s for s in entry["stocks"] if s["id"] == "edcc-082wh")
        self.assertIsNone(row["gap_mm"])

    async def test_a_measured_gap_makes_the_budget_arithmetic(self):
        """1.5mm is 18 dot lines, so the budget is 375 + 18 = 393, doubled
        to 786 by the graphics mode. Not 469-plus-anything: a measurement
        replaces the guess."""
        await self.loaded()
        status, saved = await self.post("/api/stock/edcc-082wh/offset",
                                        {"gap_mm": 1.5})
        self.assertEqual(200, status, saved)
        self.assertEqual(1.5, saved["stock"]["gap_mm"])
        _, payload = await self.print_once()
        self.assertEqual(786, self.length(payload))

    async def test_it_is_the_same_number_in_the_faster_line_mode(self):
        """The repeat and the length are one fact, and a gap is counted in
        the printer's steps like everything else."""
        await self.loaded()
        await self.post("/api/settings", {"quality": "text"})
        await self.post("/api/stock/edcc-082wh/offset", {"gap_mm": 1.5})
        _, payload = await self.print_once()
        self.assertEqual(393, self.length(payload))

    async def test_zero_is_settable_and_means_zero(self):
        """"Wind it down to nothing and watch the leading edge" is the
        experiment this exists for, so zero has to survive the wire. A falsy
        test anywhere on this path would hand it the unset default, the
        experiment would show no change, and the wrong conclusion would be
        drawn from a control that never applied."""
        await self.loaded()
        _, saved = await self.post("/api/stock/edcc-082wh/offset",
                                   {"gap_mm": 0})
        self.assertEqual(0.0, saved["stock"]["gap_mm"])
        _, payload = await self.print_once()
        self.assertEqual(375 * protocol.LINE_REPEAT["graphics"],
                         self.length(payload))

    async def test_zero_says_out_loud_what_it_has_done(self):
        """It is the shape that shipped before 0.5.0 and drifted down the
        roll. Reported every print rather than refused: refusing would take
        away the one setting the experiment needs, and a diagnostic left
        switched on is exactly the thing worth saying on every label."""
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset", {"gap_mm": 0})
        body, _ = await self.print_once()
        note = " ".join(body["notes"])
        self.assertIn("set to 0.0mm", note)
        self.assertIn("stops looking for the sense hole", note)
        self.assertIn("drift", note)

    async def test_a_measured_gap_is_silent(self):
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset", {"gap_mm": 1.5})
        body, _ = await self.print_once()
        # The one note this stock always carries is the renderer's, about
        # 2.25" of label on a 2.24" head. A measured gap adds nothing to it.
        self.assertEqual(1, len(body["notes"]), body["notes"])
        self.assertIn("the outer 3 dot columns", body["notes"][0])

    async def test_empty_clears_it_back_to_unmeasured(self):
        """Three states, not two: absent keeps, empty clears, a number sets.
        Clearing has to give back the exact job that shipped, or the control
        is a one-way door."""
        await self.loaded()
        _, before = await self.print_once()
        await self.post("/api/stock/edcc-082wh/offset", {"gap_mm": 1.5})
        _, saved = await self.post("/api/stock/edcc-082wh/offset",
                                   {"gap_mm": None})
        self.assertIsNone(saved["stock"]["gap_mm"])
        _, after = await self.print_once()
        self.assertEqual(before, after)

    async def test_a_payload_that_never_mentions_it_keeps_it(self):
        """Which is what a panel served before 0.7.0 posts. The same
        partial-update rule the Edit dialog follows."""
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset", {"gap_mm": 1.5})
        _, body = await self.post("/api/stock/edcc-082wh/offset",
                                  {"offset_feed_mm": -4.0})
        self.assertEqual(1.5, body["stock"]["gap_mm"])
        self.assertEqual(-4.0, body["stock"]["offset_feed_mm"])

    async def test_a_negative_gap_is_refused(self):
        await self.loaded()
        status, body = await self.post("/api/stock/edcc-082wh/offset",
                                       {"gap_mm": -2})
        self.assertEqual(400, status)
        self.assertIn("cannot be negative", body["error"])

    async def test_a_gap_wider_than_any_die_cut_is_refused(self):
        """A number bigger than an inch is a label typed into the gap box,
        and a budget built on it would search most of a foot of paper."""
        await self.loaded()
        status, body = await self.post("/api/stock/edcc-082wh/offset",
                                       {"gap_mm": 40})
        self.assertEqual(400, status)
        self.assertIn("BETWEEN two labels", body["error"])

    async def test_it_survives_an_edit_of_the_stock(self):
        await self.loaded()
        await self.post("/api/stock/edcc-082wh/offset", {"gap_mm": 1.5})
        _, body = await self.post("/api/stock", {
            "id": "edcc-082wh", "name": "Chemical-Resistant Cryo Labels",
            "across_in": 2.25, "feed_in": 1.25})
        self.assertEqual(1.5, body["stock"]["gap_mm"])
