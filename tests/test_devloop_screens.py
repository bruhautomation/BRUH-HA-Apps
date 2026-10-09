#!/usr/bin/env python3
"""The Screens stream: brAIn photographs its own panel, redacted.

The claims it makes, each driven:

  * nothing confidential is on the page when the picture is taken — a
    calendar event, an address, an email, a phone number, a password, a
    key — in the panel's own text, in a field, and inside a chart's
    sandboxed frame; names carry the issue's aliases;
  * pixels that are not text are covered rather than trusted;
  * the layout faults a script can see are measured, in the window's own
    width (a phone zooms a too-wide page out, and innerWidth then lies);
  * the pictures go to the private repository BEFORE the issue that shows
    them, are not sent twice, and a token that cannot write files stops the
    issue rather than filing a page of broken images;
  * the review preview serves exactly the files that would be uploaded,
    and nothing else off this box.

The browser test drives a real Chromium against a real page; it is
skipped where no Chromium is installed.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop  # noqa: E402
import devloop.aliases  # noqa: E402
import devloop.github  # noqa: E402
import devloop.screens  # noqa: E402
import devloop.upstream  # noqa: E402
import test_devloop as base  # noqa: E402

screens = devloop.screens
upstream = devloop.upstream
github = devloop.github
Aliases = devloop.aliases.Aliases

EVENT = "Dentist with Dr Who at noon"


def browser() -> str:
    for path in (os.environ.get("BRAIN_CHROMIUM", ""),
                 "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"):
        if path and os.access(path, os.X_OK):
            return path
    found = screens.find_browser()
    if found:
        return found
    root = Path("/opt/pw-browsers")
    for cand in sorted(root.glob("chromium-*/chrome-linux/chrome")) if root.is_dir() else []:
        return str(cand)
    return ""


class TestRedact(unittest.TestCase):
    def test_a_calendar_event_is_blanked_whole(self):
        out = screens.redact(f"Next: {EVENT}!", confidential=[EVENT])
        self.assertNotIn("Dentist", out)
        self.assertNotIn("Next", out, "the whole string goes, not the match")

    def test_addresses_and_contact_details_are_blanked(self):
        for text, gone in (
                ("We live at 42 Wallaby Way, Sydney", "Wallaby"),
                ("1600 Pennsylvania Avenue NW", "Pennsylvania"),
                ("Springfield, IL 62704", "62704"),
                ("London SW1A 1AA", "SW1A"),
                ("Ottawa K1A 0B1", "K1A"),
                ("mail joe.bloggs@example.com", "bloggs"),
                ("call (555) 123-4567", "123-4567"),
                ("call +44 20 7946 0958", "7946"),
                ("at 51.50735, -0.12776", "51.50735")):
            self.assertNotIn(gone, screens.redact(text), text)

    def test_credentials_are_blanked(self):
        for text, gone in (
                ("password: hunter2", "hunter2"),
                ("api key = xyzzy-plugh", "xyzzy"),
                ("AbCdEf1234567890GhIjKlMnOp", "AbCdEf"),
                ("id 0123456789abcdef0123456789abcdef", "0123456789abcdef"),
                ("Bearer abcdefghijklmnopqrstuvwxyz0123", "abcdefghijklmnop"),
                (base.TOKEN, base.TOKEN[:20])):
            self.assertNotIn(gone, screens.redact(text), text)

    def test_ordinary_words_and_entity_ids_survive(self):
        for text in ("sensor.living_room_temperature_2 reads 21.4°C",
                     "Session about 18% of 5-hour window", "v2.18.10",
                     "Refresh every 24 hours"):
            self.assertEqual(screens.redact(text), text)

    def test_names_carry_the_issues_aliases(self):
        al = Aliases()
        al.learn({"light.kitchen_lamp": {"name": "Kitchen Lamp", "area": "Kitchen"}})
        out = screens.redact("Kitchen Lamp is on in Kitchen", aliases=al)
        self.assertNotIn("Kitchen", out)

    def test_what_cannot_be_judged_is_blanked(self):
        class Broken:
            def apply(self, text):
                raise RuntimeError("no")
        out = screens.redact("Kitchen", aliases=Broken())
        self.assertEqual(set(out), {screens.BLOCK})


class TestWhatIsConfidential(unittest.TestCase):
    def test_read_off_the_house(self):
        states = [
            {"entity_id": "calendar.family", "state": "on", "attributes": {
                "message": EVENT, "description": "Bring the forms",
                "location": "12 Elm Street"}},
            {"entity_id": "zone.home", "state": "0", "attributes": {"friendly_name": "Home"}},
            {"entity_id": "zone.work", "state": "1", "attributes": {"friendly_name": "Acme Works"}},
            {"entity_id": "sensor.pixel_geocoded_location",
             "state": "Somewhere near the river", "attributes": {}},
            {"entity_id": "sensor.x", "state": "7", "attributes": {
                "address": "99 Baker Street, London"}},
            {"entity_id": "light.kitchen", "state": "on", "attributes": {
                "friendly_name": "Kitchen"}},
        ]
        occ = {"occasions": [{"kind": "visit", "text": "Grandma visits Saturday"},
                             {"kind": "weather", "text": "Frost on Tuesday"}]}
        found = screens.confidential_strings(states, occ)
        for must in (EVENT, "Bring the forms", "12 Elm Street", "Acme Works",
                     "Somewhere near the river", "99 Baker Street, London",
                     "Grandma visits Saturday"):
            self.assertIn(must, found)
        for never in ("Home", "Kitchen", "Frost on Tuesday"):
            self.assertNotIn(never, found)
        self.assertEqual(found, sorted(found, key=len, reverse=True))


class TestRows(unittest.TestCase):
    def _result(self):
        return {"shots": [
            {"name": "insights-390-light.png", "screen": "Insights", "width": 390,
             "scheme": "light", "sha": "a" * 64},
            {"name": "insights-1200-light.png", "screen": "Insights", "width": 1200,
             "scheme": "light", "sha": "b" * 64}],
            "problems": [{"screen": "Insights", "width": 390, "scheme": "light",
                          "kind": "off_the_edge", "el": "div (wide)", "text": "x",
                          "detail": "spans 0–700px"}],
            "errors": []}

    def test_one_rolling_issue_per_release(self):
        rows = screens.rows(self._result(), "2.18.10", "1700000000")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], "screens:2.18.10")
        self.assertTrue(rows[0]["ux"])
        self.assertIn("Off the edge", rows[0]["body"])
        self.assertEqual(len(rows[0]["gallery"]), 2)

    def test_no_picture_files_nothing(self):
        self.assertEqual(screens.rows({"shots": [], "problems": []}, "1", "1"), [])

    def test_the_review_route_serves_only_a_kept_picture(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "screens" / "1700000000"
            d.mkdir(parents=True)
            (d / "insights-390-light.png").write_bytes(b"x")
            self.assertIsNotNone(screens.local_file(
                Path(tmp), "1700000000", "insights-390-light.png"))
            for cap, name in (("1700000000", "../../secrets/x.png"),
                              ("..", "insights-390-light.png"),
                              ("1700000000", "insights-390-light.png/"),
                              ("1700000000", "aliases.json")):
                self.assertIsNone(screens.local_file(Path(tmp), cap, name))

    def test_the_uploader_writes_only_the_screens_folder(self):
        url, err = github.put_file(base.TOKEN, "me/reports", "README.md", b"x", "m")
        self.assertEqual(url, "")
        self.assertIn("refused", err)


class TestUpload(base.DevloopCase):
    def _capture(self, payload=b"\x89PNG one"):
        cap = "1700000000"
        d = devloop.DATA_DIR / "screens" / cap
        d.mkdir(parents=True, exist_ok=True)
        (d / "insights-390-light.png").write_bytes(payload)
        import hashlib
        result = {"shots": [{"name": "insights-390-light.png", "screen": "Insights",
                             "width": 390, "scheme": "light",
                             "sha": hashlib.sha256(payload).hexdigest()}],
                  "problems": [], "errors": []}
        upstream.ingest("screens", screens.rows(result, "2.17.0", cap),
                        base.diagnostics(), base.NAMES)

    def test_pictures_go_up_before_the_issue_and_are_linked_in_it(self):
        self.switch_on()
        self._capture()
        upstream.send_due()
        self.assertEqual(list(self.gh.files),
                         ["screens/brain-2.17.0/insights-390-light.png"])
        puts = [i for i, r in enumerate(self.gh.requests) if r[0] == "PUT"]
        posts = [i for i, r in enumerate(self.gh.requests)
                 if r == ("POST", "/repos/me/reports/issues")]
        self.assertLess(puts[0], posts[0])
        body = self.gh.issues[0]["body"]
        self.assertIn("blob/main/screens/brain-2.17.0/insights-390-light.png?raw=true",
                      body)
        self.assertIn({"name": "devloop:ux"}, self.gh.issues[0]["labels"])

    def test_an_unchanged_picture_is_not_sent_again(self):
        self.switch_on()
        self._capture()
        upstream.send_due()
        self._capture()
        upstream.send_due()
        self.assertEqual(sum(1 for r in self.gh.requests if r[0] == "PUT"), 1)

    def test_a_token_that_cannot_write_files_files_nothing(self):
        self.gh.contents_forbidden = True
        self.switch_on()
        self._capture()
        upstream.send_due()
        self.assertEqual(self.gh.issues, [])
        row = next(r for r in upstream.listing() if r["stream"] == "screens")
        self.assertIn("Contents: Read and write", row["error"])

    def test_the_preview_shows_the_local_pictures(self):
        self.switch_on(review=True)
        self._capture()
        row = next(r for r in upstream.listing() if r["stream"] == "screens")
        doc = upstream.preview(row["fp"])
        self.assertEqual(doc["images"][0]["src"],
                         "api/devloop/screen/1700000000/insights-390-light.png")
        self.assertNotIn("?raw=true", doc["body"], "nothing was uploaded yet")

    def test_the_stream_is_in_the_catalog_and_off_by_default(self):
        self.assertIn("screens", devloop.STREAMS)
        self.assertFalse(devloop.DEFAULTS["streams"]["screens"])
        self.assertIn("screens", devloop.AUTOPILOT_HOURS)


PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width">
<style>body{font-family:sans-serif;margin:16px;background:#fff;color:#222}
.wide{width:700px}.faint{color:#ccc}</style></head><body>
<p>Next: %(event)s</p>
<p>We live at 42 Wallaby Way, Sydney</p>
<p>joe.bloggs@example.com (555) 123-4567</p>
<p>AbCdEf1234567890GhIjKlMnOp</p>
<p>Kitchen Lamp is on</p>
<p class=faint>faint words</p>
<div class=wide>too wide</div>
<input type=password value="hunter2"><input value="%(event)s">
<canvas width=100 height=50></canvas>
<iframe sandbox="allow-scripts" srcdoc="<p>Frame: 42 Wallaby Way, %(event)s</p>"></iframe>
<script>function switchView(v){document.body.dataset.view=v}</script>
</body></html>""" % {"event": EVENT}


@pytest.mark.slow
@unittest.skipUnless(browser(), "no Chromium on this machine")
class TestARealBrowser(unittest.TestCase):
    def test_nothing_confidential_is_on_the_page_when_it_is_photographed(self):
        os.environ["BRAIN_CHROMIUM"] = browser()
        seen: list[str] = []

        async def look(cdp, session):
            r = await cdp.call("Runtime.evaluate", {
                "expression": "document.body.innerText + '|' + "
                              "[...document.querySelectorAll('input')].map(i => i.value).join('|')",
                "returnByValue": True}, session)
            seen.append(r["result"]["value"])
            tree = (await cdp.call("Page.getFrameTree", {}, session))["frameTree"]
            for frame in screens._frames(tree):
                w = await cdp.call("Page.createIsolatedWorld", {"frameId": frame["id"]}, session)
                r = await cdp.call("Runtime.evaluate", {
                    "expression": "document.body.innerText",
                    "contextId": w["executionContextId"], "returnByValue": True}, session)
                seen.append("frame:" + str(r["result"].get("value")))

        from aiohttp import web

        async def run(out: Path):
            app = web.Application()
            async def page(_request):
                return web.Response(text=PAGE, content_type="text/html")

            app.router.add_get("/", page)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            al = Aliases()
            al.learn({"light.kitchen_lamp": {"name": "Kitchen Lamp", "area": "Kitchen"}})
            try:
                return await screens.capture(
                    out, confidential=[EVENT], aliases=al, url=f"http://127.0.0.1:{port}/",
                    screens=[("test", "Test", "switchView('x')")],
                    views=[(390, 844, True, "light")])
            finally:
                await runner.cleanup()

        old = screens.AFTER_REDACT
        screens.AFTER_REDACT = look
        tmp = tempfile.mkdtemp()
        try:
            result = asyncio.run(asyncio.wait_for(run(Path(tmp)), 120))
        finally:
            screens.AFTER_REDACT = old
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["shots"]), 1)
        text = "\n".join(seen)
        self.assertTrue(any(s.startswith("frame:") for s in seen), "the frame was not reached")
        for secret in ("Dentist", "Wallaby", "bloggs", "123-4567", "AbCdEf",
                       "hunter2", "Kitchen Lamp"):
            self.assertNotIn(secret, text)
        self.assertIn("not captured", text, "the canvas was not covered")
        kinds = {p["kind"] for p in result["problems"]}
        self.assertIn("off_the_edge", kinds)
        self.assertIn("page_scrolls_sideways", kinds)
        self.assertIn("low_contrast", kinds)


class TestTheDocsSayIt(unittest.TestCase):
    def test_devloop_md_no_longer_says_the_house_takes_none(self):
        text = (BASE_DIR / "brain" / "DEVLOOP.md").read_text()
        self.assertNotIn("The house takes none", text)
        self.assertNotIn("the house never takes screenshots", text)
        self.assertIn("Contents: Read and write", text)
        self.assertIn("**Screens**", text)

    def test_the_image_ships_a_browser_and_fonts(self):
        text = (BASE_DIR / "brain" / "Dockerfile").read_text()
        for pkg in ("chromium", "font-dejavu"):
            self.assertIn(pkg, text)


if __name__ == "__main__":
    unittest.main()
