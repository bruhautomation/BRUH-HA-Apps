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
