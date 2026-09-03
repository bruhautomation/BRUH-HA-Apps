#!/usr/bin/env python3
"""Boot the real BRUH Print panel against a scratch /data, on loopback.

The panel is the whole product and most of what is worth checking about it
is geometry — does the bar fit, is a control reachable with a thumb, does the
design canvas fit its pane. None of that is a question a server can answer,
so this stands the real `server.py` up with a Twin Turbo in place of a bus
and lets Playwright drive it.

    python3 tests/manual/bruh_print_demo_panel.py /tmp/bruh-print-demo
    node tests/manual/measure-print-panel.mjs

The ONLY thing stood in for is the USB bulk write. Everything above it — the
stores, the renderer, the roll routing, the refusals — is the code that
ships, which is what makes a measurement of this panel a measurement of the
panel. A demo that faked the renderer would be measuring its own fixture.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "bruh-print" / "panel"
DEMO = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bruh-print-demo")
PORT = int(os.environ.get("DEMO_PORT", "8097"))

DEMO.mkdir(parents=True, exist_ok=True)
os.environ["BRUH_PRINT_DATA"] = str(DEMO)
# A shared folder whose parent does not exist, so the state mirror is skipped
# exactly as it is on a dev checkout with no /config.
os.environ["BRUH_PRINT_SHARED"] = str(DEMO / "no-config" / ".bruh_print")

sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from dymo import printers, usb_link  # noqa: E402

import server  # noqa: E402


def fake_send(payload, key=None):
    print(f"[demo] would write {len(payload)} bytes to the printer", flush=True)
    return {"bytes": len(payload), "printer": {}, "status": "ready",
            "status_ok": True, "status_answered": True}


def fake_probe(key=None):
    return {"printer": {}, "status": "ready", "status_ok": True,
            "status_answered": True}


usb_link.send = fake_send
usb_link.probe = fake_probe

panel = server.Panel(DEMO)
TWIN = printers.Discovered(0x0022, printers.MODELS[0x0022],
                           serial="01010112345600")
panel.discover = lambda force=False: [TWIN]

# Both bays filled, because an empty printer is the one state where half the
# panel is a prompt to go and fill a form in — and the measures are about the
# working screens.
panel.rolls.load_roll("left", "edcc-082wh", count=1000)
panel.rolls.load_roll("right", "ed1f-060wh", count=350)

# One saved template and one printed label, so the Templates and History tabs
# have something in them to measure.
from stores import templates as template_store  # noqa: E402

if not panel.templates.all():
    panel.templates.put(template_store.Template(
        id="", name="Cryo vial", icon="mdi:test-tube",
        description="Wraps a 2ml tube",
        label={"stock": "ed1f-060wh", "rotate": 90, "elements": [
            {"type": "text", "x_mm": 1, "y_mm": 0.5, "w_mm": 48, "h_mm": 10,
             "props": {"text": "{{sample}}", "font": "sans-bold",
                       "size_mm": 0, "align": "left", "valign": "middle",
                       "wrap": True, "line_spacing": 1.1, "rotate": 0,
                       "invert": False}},
            {"type": "barcode", "x_mm": 50, "y_mm": 1, "w_mm": 33, "h_mm": 10,
             "props": {"data": "{{sample}}", "hri": False, "hri_font": "mono",
                       "hri_mm": 2.5, "quiet": 10, "rotate": 0}}]},
        fields=[template_store.Field(key="sample", label="Sample id")]))

if not panel.history.all():
    panel.history.add(stock="edcc-082wh", side="left", copies=2,
                      title="Buffer A pH 7.4", label={
                          "stock": "edcc-082wh", "rotate": 0, "elements": [
                              {"type": "text", "x_mm": 0, "y_mm": 0,
                               "w_mm": 55, "h_mm": 29,
                               "props": {"text": "Buffer A pH 7.4",
                                         "font": "sans-bold", "size_mm": 0,
                                         "align": "center", "valign": "middle",
                                         "wrap": False, "line_spacing": 1.05,
                                         "rotate": 0, "invert": False}}]})

print(f"[demo] BRUH Print panel on http://127.0.0.1:{PORT}", flush=True)
web.run_app(server.build_app(panel), host="127.0.0.1", port=PORT, print=None)
