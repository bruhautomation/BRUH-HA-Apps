#!/usr/bin/env python3
"""The chat's photograph of a Morph card has its history, and an opened card is open.

Report 681: `screenshot_panel` photographed Morph's cards before their
history had come back, so every chart (a room's temperature lines, a
sparkline) was empty although the same question put to Home Assistant
answers with real points; and `press: "open"` on a custom card that opens
itself on a hold left it folded. The claims, each driven against Morph's
real modules, the real harness routes and the real capture:

  * the history and statistics reads the harness may ask are answered, and
    the capture waits (bounded) for the ones still in flight, also after it
    unfolded a room whose cards only then asked;
  * a hold on a hosted custom card reaches the card's own code, so a card
    that opens on hold is photographed open;
  * a write the card tries on the way is still refused, and a question that
    never comes back does not hold the picture past the bound.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock as mock
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import devloop.screen_targets as st  # noqa: E402
import devloop.screens as screens  # noqa: E402
from test_devloop_screens import browser, warm_up  # noqa: E402

FRONTEND = BASE_DIR / "brain/custom_components/brain/morph/frontend"
READ_HISTORY = ("history/history_during_period", "recorder/statistics_during_period",
                "logbook/get_events")

# The page text of a tile, and whether its charts drew a line with points.
PROBE = """(() => {
  const p = document.querySelector('morph-panel');
  const R = p && p.shadowRoot;
  const out = {};
  for (const t of R ? R.querySelectorAll('[data-tile]') : []) {
    const id = t.getAttribute('data-tile');
    const hosted = t.querySelector('[data-ll]');
    const inner = hosted && hosted.firstElementChild && hosted.firstElementChild.firstElementChild;
    out[id] = {text: t.textContent, html: t.innerHTML,
               hostedText: inner ? ((inner.shadowRoot || inner).textContent || '') : '',
               h: Math.round(t.getBoundingClientRect().height)};
  }
  return out;
})()"""


class Page:
    """Morph's own code on a made-up house, photographed the way the tool does."""

    def __init__(self, dash, states, answer, focuses, cards=None, modules=None, settings=None,
                 view=(1200, 800, False, "light")):
        self.view = view
        self.dash, self.states, self.answer = dash, states, answer
        self.focuses, self.cards, self.modules = focuses, cards, modules or []
        self.settings = settings or {}
        self.asked: list[dict] = []
        self.seen: list[dict] = []
        self.result = None
        self.seconds = 0.0
        self.looked_after = 0.0

    def run(self):
        import server  # noqa: PLC0415
        os.environ["BRAIN_CHROMIUM"] = browser()
        warm_up(os.environ["BRAIN_CHROMIUM"])
        load = {"mirror": {"revision": "r1", "dashboard": self.dash, "problems": [],
                           "card_modules": self.modules},
                "state": {"settings": self.settings}, "brain": {}, "admin": True,
                "now": 1.7e9, "code": "", "integration": "x"}

        async def fake(session, commands, **kw):
            msg = commands[0]
            self.asked.append(msg)
            kind = msg["type"]
            if kind == "get_states":
                return [{"ok": True, "result": self.states}]
            if kind == "morph/load":
                return [{"ok": True, "result": load}]
            if kind in READ_HISTORY:
                return [await self.answer(msg)]
            return [{"ok": True, "result": {} if kind == "get_config" else []}]

        began_at = [0.0]

        async def look(cdp, session):
            r = await cdp.call("Runtime.evaluate", {"expression": PROBE,
                                                    "returnByValue": True}, session)
            self.seen.append(r["result"]["value"])
            self.looked_after = time.monotonic() - began_at[0]

        from aiohttp import web  # noqa: PLC0415

        async def go(out: Path):
            app = web.Application()
            app.router.add_get("/devloop/harness/morph/{name}", server.h_harness_morph)
            app.router.add_get("/devloop/harness/morph_cards/{name}",
                               server.h_harness_morph_cards)
            app.router.add_get("/morph_cards/{name}", server.h_harness_morph_cards)
            app.router.add_get("/devloop/harness/ws", server.h_harness_ws)
            app.router.add_get("/devloop/harness/{name}", server.h_harness_page)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            target = st.harness_targets(f"http://127.0.0.1:{port}/", {"Morph": "1"})[0]
            scr = target["screens"][0]
            target["screens"] = [{**scr, "focus": f} for f in self.focuses]
            try:
                return await screens.capture(
                    out, confidential=[], aliases=None, own=False, targets=[target],
                    views=[self.view])
            finally:
                await runner.cleanup()

        old = screens.AFTER_REDACT
        screens.AFTER_REDACT = look
        tmp, empty = tempfile.mkdtemp(), tempfile.mkdtemp()
        cards = self.cards or empty
        began = time.monotonic()
        began_at[0] = began
        try:
            with mock.patch("ha_data._ws_calls", fake), \
                 mock.patch.object(st, "MORPH_FRONTEND", str(FRONTEND)), \
                 mock.patch.object(st, "MORPH_CARDS", str(cards)), \
                 mock.patch.object(st, "MORPH_CODE_DIR", empty), \
                 mock.patch.object(st, "MORPH_CODE_STATE", os.path.join(empty, "code.json")):
                self.result = asyncio.run(asyncio.wait_for(go(Path(tmp)), 240))
        finally:
            self.seconds = time.monotonic() - began
            screens.AFTER_REDACT = old
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(empty, ignore_errors=True)
        return self


def temps(cid):
    return {"id": cid, "type": "readings", "name": "Temperatures",
            "entities": ["sensor.den_temperature", "sensor.loft_temperature"]}


def house():
    def sensor(eid, name, v):
        return {"entity_id": eid, "state": v, "attributes": {
            "friendly_name": name, "unit_of_measurement": "°C", "device_class": "temperature"}}
    return [sensor("sensor.den_temperature", "Den temperature", "21.5"),
            sensor("sensor.loft_temperature", "Loft temperature", "19.0")]


async def points(msg, delay=0.0):
    """What Home Assistant answers a statistics question with, after `delay`."""
    await asyncio.sleep(delay)
    now = int(time.time() * 1000)
    rows = {eid: [{"start": now - (24 - i) * 3600_000, "mean": base + (i % 5) * 0.4}
                  for i in range(24)]
            for eid, base in (("sensor.den_temperature", 20.0),
                              ("sensor.loft_temperature", 18.0))}
    return {"ok": True, "result": {k: v for k, v in rows.items()
                                   if k in (msg.get("statistic_ids") or [])}}


def drawn_lines(tile):
    return tile["html"].count("<polyline points=") + tile["html"].count("<path d=\"M")


@pytest.mark.slow
class TestAChartIsPhotographedWithItsLines(unittest.TestCase):
    def dash(self, folded_room):
        return {"title": "Home", "floors": [{"id": "f_home", "title": "Home", "sections": [
            {"id": "s_up", "title": "Upstairs", "color": "sand", "width": 3, "groups": [
                {"cards": [temps("c_temps")]}]},
            {"id": "s_far", "title": "Far room", "color": "teal", "width": 2, "groups": [
                {"cards": [{"id": "c_note", "type": "note", "text": "NOTE"}]}]}]}]}

    def test_a_chart_that_answers_late_is_waited_for(self):
        async def late(msg):
            return await points(msg, delay=2.5)

        page = Page(self.dash(False), house(), late,
                    [{"id": "c_temps", "press": ""}],
                    settings={"fold_rooms": False}).run()
        self.assertEqual(page.result["errors"], [])
        self.assertTrue(any(m["type"] == "recorder/statistics_during_period"
                            for m in page.asked), page.asked)
        tile = page.seen[-1]["c_temps"]
        self.assertGreaterEqual(drawn_lines(tile), 2, tile["text"])
        self.assertNotIn("Reading the day", tile["text"])

    def test_a_chart_in_a_room_the_capture_unfolds_is_waited_for_too(self):
        async def late(msg):
            return await points(msg, delay=2.0)

        # The room is folded when the page is drawn: its cards ask for their
        # history only once the capture has unfolded it.
        dash = {"title": "Home", "floors": [{"id": "f_home", "title": "Home", "sections": [
            {"id": "s_up", "title": "Upstairs", "color": "sand", "width": 3, "groups": [
                {"cards": [temps("c_temps"), {"id": "c_lamp", "type": "note", "text": "x"}]}]}]},
            {"id": "f_down", "title": "Downstairs", "sections": [
                {"id": "s_hall", "title": "Hall", "color": "teal", "width": 3, "groups": [
                    {"cards": [temps("c_hall_temps")]}]}]}]}
        page = Page(dash, house(), late, [{"id": "c_hall_temps", "press": ""}]).run()
        self.assertEqual(page.result["errors"], [])
        tile = page.seen[-1].get("c_hall_temps")
        self.assertIsNotNone(tile, list(page.seen[-1]))
        self.assertGreaterEqual(drawn_lines(tile), 2, tile["text"])

    def test_a_question_that_never_comes_back_does_not_hold_the_picture(self):
        async def never(msg):
            await asyncio.sleep(40)
            return {"ok": True, "result": {}}

        page = Page(self.dash(False), house(), never, [{"id": "c_temps", "press": ""}],
                    settings={"fold_rooms": False}).run()
        self.assertEqual(len(page.result["shots"]), 1)
        # The picture was taken at the bound, not when the question gave up.
        self.assertLess(page.looked_after, 30, page.looked_after)

    def test_a_card_that_asks_to_write_is_still_refused(self):
        cards = Path(tempfile.mkdtemp())
        (cards / "x-writer.js").write_text(
            "customElements.define('x-writer', class extends HTMLElement {\n"
            "  setConfig() {}\n"
            "  set hass(h) { h.callWS({type: 'config/entity_registry/remove',"
            " entity_id: 'light.x'}).catch((e) => { this.textContent = 'REFUSED'; });\n"
            "    h.callService('light', 'turn_on', {}).catch(() => {}); } });\n",
            encoding="utf-8")
        dash = {"title": "Home", "floors": [{"id": "f_home", "title": "Home", "sections": [
            {"id": "s_up", "title": "Upstairs", "color": "sand", "width": 3, "groups": [
                {"cards": [{"id": "c_writer", "type": "lovelace",
                            "card": {"type": "custom:x-writer"}}]}]}]}]}

        async def ok(msg):
            return await points(msg)

        try:
            page = Page(dash, house(), ok, [{"id": "c_writer", "press": ""}],
                        cards=cards, modules=[{"name": "x-writer.js", "v": 1}],
                        settings={"fold_rooms": False}).run()
        finally:
            shutil.rmtree(cards, ignore_errors=True)
        self.assertNotIn("config/entity_registry/remove", [m["type"] for m in page.asked])
        self.assertIn("REFUSED", page.seen[-1]["c_writer"]["hostedText"])


HOLD_CARD = """\
customElements.define('x-holdcard', class extends HTMLElement {
  setConfig(c) { this.c = c; this.attachShadow({mode: 'open'}); this.draw(false); }
  set hass(h) { this._h = h; }
  draw(open) {
    this.shadowRoot.innerHTML = '<div id=b style="height:' + (open ? 300 : 60)
      + 'px;background:#9cf;touch-action:none">' + (open ? 'HOLD CARD OPEN' : 'hold card folded')
      + '</div>';
    const b = this.shadowRoot.getElementById('b');
    let t = null;
    b.addEventListener('pointerdown', () => { t = setTimeout(() => { t = null; this.draw(true); }, 450); });
    b.addEventListener('pointerup', () => { if (t) { clearTimeout(t); t = null; } });
  }
});
"""

# The way Home Assistant's own action handler listens on a phone: touch
# events only (a device that has touch ignores the mouse), a hold of half a
# second, and a tap on the touch end. Cards built on it never see a mouse.
TOUCH_CARD = """\
customElements.define('x-touchcard', class extends HTMLElement {
  setConfig(c) { this.c = c; this.attachShadow({mode: 'open'}); this.draw('folded'); }
  set hass(h) { this._h = h; }
  draw(state) {
    this.shadowRoot.innerHTML = '<div id=b style="height:' + (state === 'open' ? 300 : 60)
      + 'px;background:#9cf">touch card ' + state + '</div>';
    const b = this.shadowRoot.getElementById('b');
    let t = null; let held = false;
    b.addEventListener('touchstart', () => { held = false;
      t = setTimeout(() => { t = null; held = true; this.draw('open'); }, 500); });
    b.addEventListener('touchend', () => {
      if (t) { clearTimeout(t); t = null; if (!held) this.draw('tapped'); } });
  }
});
"""


@pytest.mark.slow
class TestAPressOpensACustomCard(unittest.TestCase):
    def run_press(self, press, room_folded, tag="x-holdcard", code=HOLD_CARD,
                  view=(1200, 800, False, "light")):
        cards = Path(tempfile.mkdtemp())
        (cards / f"{tag}.js").write_text(code, encoding="utf-8")
        dash = {"title": "Home", "floors": [{"id": "f_home", "title": "Home", "sections": [
            {"id": "s_up", "title": "Upstairs", "color": "sand", "width": 3, "groups": [
                {"cards": [{"id": "c_hold", "type": "lovelace",
                            "card": {"type": f"custom:{tag}"}}]}]}]}]}

        async def ok(msg):
            return await points(msg)

        try:
            return Page(dash, house(), ok, [{"id": "c_hold", "press": press}],
                        cards=cards, modules=[{"name": f"{tag}.js", "v": 1}],
                        settings={} if room_folded else {"fold_rooms": False},
                        view=view).run()
        finally:
            shutil.rmtree(cards, ignore_errors=True)

    def test_open_on_a_card_that_opens_on_hold_photographs_it_open(self):
        page = self.run_press("open", False)
        self.assertEqual(page.result["errors"], [])
        self.assertIn("HOLD CARD OPEN", page.seen[-1]["c_hold"]["hostedText"])

    def test_open_in_a_folded_room_too(self):
        page = self.run_press("open", True)
        self.assertEqual(page.result["errors"], [])
        self.assertIn("HOLD CARD OPEN", page.seen[-1]["c_hold"]["hostedText"])

    def test_without_a_press_the_card_stays_folded(self):
        page = self.run_press("", False)
        self.assertIn("hold card folded", page.seen[-1]["c_hold"]["hostedText"])

    # On a phone view the browser has touch, and a card built on Home
    # Assistant's action handler listens to touch only: the picture's press
    # has to be a finger there, not a mouse.
    PHONE = (390, 844, True, "dark")

    def test_a_hold_on_a_phone_reaches_a_card_that_listens_to_touch(self):
        page = self.run_press("open", False, "x-touchcard", TOUCH_CARD, self.PHONE)
        self.assertEqual(page.result["errors"], [])
        self.assertIn("touch card open", page.seen[-1]["c_hold"]["hostedText"])

    def test_a_tap_on_a_phone_reaches_it_too(self):
        page = self.run_press("tap", False, "x-touchcard", TOUCH_CARD, self.PHONE)
        self.assertIn("touch card tapped", page.seen[-1]["c_hold"]["hostedText"])

    def test_a_hold_on_a_phone_still_opens_a_card_that_listens_to_pointers(self):
        page = self.run_press("open", True, view=self.PHONE)
        self.assertIn("HOLD CARD OPEN", page.seen[-1]["c_hold"]["hostedText"])

    def test_a_hold_on_a_phone_opens_one_of_morphs_own_cards(self):
        dash = {"title": "Home", "floors": [{"id": "f_home", "title": "Home", "sections": [
            {"id": "s_up", "title": "Upstairs", "color": "sand", "width": 3, "groups": [
                {"cards": [{"id": "c_den", "type": "sensor",
                            "entity": "sensor.den_temperature"}]}]}]}]}

        async def ok(msg):
            return await points(msg)

        shut = Page(dash, house(), ok, [{"id": "c_den", "press": ""}],
                    settings={"fold_rooms": False}, view=self.PHONE).run()
        held = Page(dash, house(), ok, [{"id": "c_den", "press": "open"}],
                    settings={"fold_rooms": False}, view=self.PHONE).run()
        self.assertGreater(held.seen[-1]["c_den"]["h"], shut.seen[-1]["c_den"]["h"] + 50)


if __name__ == "__main__":
    unittest.main()
