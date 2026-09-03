#!/usr/bin/env python3
"""BRUH Print — the ingress panel.

    GET  /api/health                 liveness, polled by the Supervisor watchdog
    GET  /api/state                  everything the UI opens with, in one call
    GET  /api/printers               what is on the USB bus right now
    POST /api/printer/select         remember which one is the default
    GET  /api/printer/status         ask the printer how it is
    POST /api/printer/test           print the ruler
    GET  /api/stocks                 the label catalog
    POST /api/stock                  add or correct a stock
    POST /api/stock/{id}/swap        the two dimensions, exchanged
    DEL  /api/stock/{id}             delete a custom stock / hide a built-in
    POST /api/roll/{side}            say what is in a bay
    DEL  /api/roll/{side}            say a bay is empty
    POST /api/preview                a label document -> a PNG of the label
    POST /api/print                  a label document -> a printed label
    POST /api/quick                  a word -> a label, fitted, previewed or printed
    GET  /api/templates              saved labels with holes in them
    POST /api/template               save one
    DEL  /api/template/{id}          delete one
    POST /api/template/{id}/preview  fill it in and draw it
    POST /api/template/{id}/print    fill it in and print it
    GET  /api/history                what was printed
    POST /api/history/{id}/reprint   print exactly that again
    GET/POST/DEL /api/assets         images a label may use

Two rules shape the whole file.

**A print is refused when it cannot be right, and never when it merely might
not be.** The one refusal is a stock/roll mismatch — sending a 2.25"-wide
raster to a 0.56" roll prints across the liner, and a run of fifty does it
fifty times. Everything else that could be wrong (a barcode that will not
fit, an image that could not be read, a fixed font size that clips) comes
back as a *note* beside a label that still prints, because a label with one
element missing is usually still the label somebody wanted and a refusal is
always a person unable to work.

**Rendering never runs on the event loop.** Pillow is CPU-bound and a 4"
label supersampled 4× is tens of milliseconds; on a Pi with the Lovelace card
polling, doing that inline is a panel that stutters. Every render and every
USB write goes through `asyncio.to_thread`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

PANEL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PANEL_DIR))

import atomic_write  # noqa: E402
from dymo import printers as dymo_printers  # noqa: E402
from dymo import protocol, usb_link  # noqa: E402
from render import fonts, image as render_image, quick  # noqa: E402
from render import label as label_doc  # noqa: E402
from stores import history, loaded, settings, stock as stock_store  # noqa: E402
from stores import templates as template_store  # noqa: E402

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
DATA = Path(os.environ.get("BRUH_PRINT_DATA", "/data"))
ASSETS = DATA / "assets"
SHARED = Path(os.environ.get("BRUH_PRINT_SHARED", "/config/.bruh_print"))

BIND_HOST = "0.0.0.0"  # noqa: S104 - ingress reaches the container, not the LAN
DEFAULT_PORT = 8097

# An uploaded image is decoded by Pillow, which is a decoder taking bytes
# from a browser; 8 MB is more than any logo and small enough that a
# malformed file cannot be a memory problem before it is a decode problem.
MAX_ASSET_BYTES = 8 * 1024 * 1024
ALLOWED_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

log = logging.getLogger("bruh_print.panel")

# A typed key rather than the string "panel": aiohttp warns about bare
# string keys because two components can collide on one, and the app here
# is shared with whatever middleware gets added later.
PANEL_KEY: web.AppKey["Panel"] = web.AppKey("panel")


class PrintRefused(web.HTTPConflict):
    """A job we will not send, with the sentence saying why.

    409 rather than 400: the request is well-formed and would be accepted on
    a different day — the roll is what is wrong, not the label. The bridge
    reads the body's `error` and hands it to the automation trace, so the
    status code is only ever the envelope.
    """

    def __init__(self, message: str, **extra):
        super().__init__(
            text=json.dumps({"ok": False, "error": message, **extra}),
            content_type="application/json")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
class Panel:
    """Everything the panel owns, constructed once."""

    def __init__(self, data: Path = DATA):
        self.data = data
        self.stocks = stock_store.StockStore(data / "stocks.json")
        self.rolls = loaded.LoadedStore(data / "rolls.json")
        self.templates = template_store.TemplateStore(data / "templates.json")
        self.history = history.HistoryStore(data / "history.json")
        self.settings = settings.SettingsStore(data / "settings.json")
        self.assets = data / "assets"
        self.assets.mkdir(parents=True, exist_ok=True)
        self.started = time.time()
        # Discovery is a USB bus walk and the UI asks for state on every tab
        # change, so it is cached for a couple of seconds. Long enough that a
        # click storm costs one walk; short enough that plugging a printer in
        # and looking at the panel shows it.
        self._printers: list[dymo_printers.Discovered] = []
        self._printers_at = 0.0
        self._printers_error = ""

    # -- printers ----------------------------------------------------------
    def discover(self, *, force: bool = False) -> list[dymo_printers.Discovered]:
        if not force and time.time() - self._printers_at < 2.0:
            return self._printers
        try:
            self._printers = usb_link.discover()
            self._printers_error = ""
        except usb_link.UsbUnavailable as exc:
            self._printers = []
            self._printers_error = str(exc)
        except OSError as exc:
            self._printers = []
            # An OSError from the bus walk is the one place a message this
            # codebase did not write is shown, and it earns it: the errno
            # text ("Permission denied", "No such device") IS the diagnostic,
            # and there is nothing else to say. Clamped, because the panel
            # renders it on a card.
            self._printers_error = (
                f"The USB bus could not be read: {exc}"[:200])
        self._printers_at = time.time()
        return self._printers

    def chosen(self) -> dymo_printers.Discovered | None:
        """The printer a job will go to, which is not always the saved one.

        A saved default that is not plugged in falls through to whatever IS,
        rather than failing — one printer in the house is the overwhelming
        case, and refusing to print because the USB address changed after a
        reboot would be the panel enforcing bookkeeping. The *print* path
        still passes the saved key down to usb_link when there is more than
        one candidate, which is where being specific actually matters.
        """
        found = self.discover()
        if not found:
            return None
        wanted = self.settings.get("printer", "")
        if wanted:
            match = next((p for p in found if p.key == wanted), None)
            if match is not None:
                return match
            if len(found) > 1:
                return None
        return found[0]

    def printer_key(self) -> str | None:
        """The key to hand usb_link, or None for "the only one there".

        None when a single printer is attached, even if a different one is
        saved: pinning a key that is not present turns "print" into "the
        saved printer is not plugged in", and the person can see there is
        one printer and one panel.
        """
        found = self.discover()
        if len(found) <= 1:
            return None
        return self.settings.get("printer", "") or None

    # -- rolls -------------------------------------------------------------
    def resolve_side(self, stock_id: str, requested: str = "") -> tuple[str, list[str]]:
        """Which bay this label prints on, and anything worth saying about it.

        The rules, in order, and each one is here because the alternative
        prints on the wrong roll:

        1. An explicit side is honoured — but checked. Somebody asking for
           the right roll while the left one holds this stock has almost
           certainly just swapped them.
        2. Otherwise the bay holding this stock wins.
        3. Otherwise the left bay, which on a single-roll printer is the
           only bay and on a Twin Turbo is the one the panel calls first.
        """
        notes: list[str] = []
        holding = self.rolls.side_for(stock_id)
        enforce = bool(self.settings.get("enforce_stock", True))

        if requested:
            if requested not in loaded.SIDES:
                raise PrintRefused(
                    f"There is no {requested!r} roll — a LabelWriter has a "
                    f"left and a right.")
            roll = self.rolls.get(requested)
            if roll.stock and roll.stock != stock_id:
                have = self.stocks.get(roll.stock)
                want = self.stocks.get(stock_id)
                message = (
                    f"The {requested} roll holds "
                    f"{have.name if have else roll.stock} "
                    f"({have.as_dict()['label'] if have else '?'}) and this "
                    f"label is for {want.name if want else stock_id} "
                    f"({want.as_dict()['label'] if want else '?'}).")
                if enforce:
                    raise PrintRefused(
                        message + " Change the roll, or tell BRUH Print what "
                        "is in it on the Printer tab — printing this as-is "
                        "would run across the liner.",
                        mismatch={"side": requested, "loaded": roll.stock,
                                  "wanted": stock_id})
                notes.append(message + " Printing anyway (stock checking is "
                                       "off in Settings).")
            elif not roll.stock:
                notes.append(
                    f"BRUH Print does not know what is in the {requested} "
                    f"roll. Set it on the Printer tab and it can stop you "
                    f"printing the wrong label on it.")
            return requested, notes

        if holding:
            return holding, notes

        occupied = [r for r in self.rolls.all() if r.stock]
        if occupied and enforce:
            want = self.stocks.get(stock_id)
            have = ", ".join(
                f"{r.side}: {(self.stocks.get(r.stock) or r).name if self.stocks.get(r.stock) else r.stock}"
                for r in occupied)
            raise PrintRefused(
                f"Neither roll holds {want.name if want else stock_id}. "
                f"Loaded: {have}. Load it, or update the Printer tab.",
                mismatch={"wanted": stock_id})

        if not occupied:
            notes.append(
                "BRUH Print does not know what is loaded, so it cannot check "
                "this label against the roll. Set it on the Printer tab.")
        return loaded.SIDES[0], notes

    def consume(self, side: str, count: int) -> None:
        """Take printed labels off the roll's estimate, if it is kept.

        One place to ask, because five call sites asking is five chances for
        a new print path to keep counting a number the panel has stopped
        showing — and a hidden count that goes on moving is worse than no
        count, since turning tracking back on reveals a number that has been
        quietly wrong for a month.
        """
        if not self.settings.get("track_remaining", True):
            return
        self.rolls.consume(side, count)

    def _stock_row(self, entry) -> dict:
        """A stock, plus which bay holds it."""
        row = entry.as_dict()
        side = self.rolls.side_for(entry.id)
        row["loaded"] = side is not None
        row["loaded_side"] = side or ""
        return row

    # -- mirror ------------------------------------------------------------
    def state_payload(self) -> dict:
        printer = self.chosen()
        found = self.discover()
        return {
            "ok": True,
            "version": os.environ.get("ADDON_VERSION", "dev"),
            "uptime_s": round(time.time() - self.started),
            "usb_available": usb_link.available(),
            "printers": [p.as_dict() for p in found],
            "printer": printer.as_dict() if printer else None,
            "printer_error": self._printers_error,
            "ambiguous": bool(len(found) > 1 and not self.settings.get("printer")),
            "rolls": [r.as_dict() for r in self.rolls.all()],
            # `loaded` rides on the stock rather than being worked out in the
            # panel from the roll list, because every picker outside the
            # Printer tab offers exactly the loaded ones and three copies of
            # that join is three chances to disagree about what is in the
            # printer.
            "stocks": [self._stock_row(s) for s in self.stocks.all()],
            "templates": [t.as_dict() for t in self.templates.all()],
            "settings": self.settings.all(),
            "fonts": list(fonts.catalog().values()),
            "catalog": label_doc.catalog_payload(),
            "assets": self.asset_list(),
            "history": [e.as_dict() for e in self.history.all(30)],
        }

    def mirror_state(self) -> None:
        """Publish the bits Home Assistant can act on into /config.

        /data is invisible to Core, so the integration reads this file. It is
        derived and never read back, and it is written on every state change
        rather than on a timer — a sensor that lags the panel by a poll
        interval is a sensor that disagrees with the screen somebody is
        looking at.

        The publish is skipped when /config does not exist so a dev checkout
        does not grow a stray one, and an OSError is a warning and never a
        lost print: the label is already out of the printer by the time this
        runs.
        """
        if not SHARED.parent.exists():
            return
        printer = self.chosen()
        payload = {
            "updated_at": time.time(),
            "version": os.environ.get("ADDON_VERSION", "dev"),
            "printer": printer.as_dict() if printer else None,
            "printer_count": len(self.discover()),
            "printer_error": self._printers_error,
            "rolls": {r.side: r.as_dict() for r in self.rolls.all()},
            "stocks": {s.id: {"name": s.name, "label": s.as_dict()["label"]}
                       for s in self.stocks.all()},
            "templates": [
                {"id": t.id, "name": t.name, "icon": t.icon,
                 "fields": [f.as_dict() for f in t.fields],
                 "stock": t.label.get("stock", ""), "copies": t.copies}
                for t in self.templates.all()],
            "last_print": (self.history.all(1)[0].as_dict()
                           if self.history.all(1) else None),
            "printed_today": sum(
                e.copies for e in self.history.all(history.MAX_ENTRIES)
                if e.at >= time.time() - 86400),
        }
        try:
            SHARED.mkdir(parents=True, exist_ok=True)
            # The one file here another process reads: Home Assistant Core,
            # for the integration's sensors. It takes the umask's default
            # like every other store rather than naming a mode — the same
            # arrangement brAIn's mirrors use, and the reason a literal is
            # wrong is that it would override a umask an operator set on
            # purpose. It carries no credential (printer names, roll counts,
            # template names), so the default being readable is fine; a
            # deployment that narrows the umask far enough to hide it from
            # Core would see the integration's entities go to "add-on
            # stopped", which the binary sensor's `reason` then says.
            atomic_write.write_json(SHARED / "state.json", payload)
        except OSError as exc:
            log.warning("Could not mirror state to %s: %s", SHARED, exc)

    # -- assets ------------------------------------------------------------
    def asset_list(self) -> list[dict]:
        out = []
        for path in sorted(self.assets.glob("*")):
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            out.append({"name": path.name, "bytes": size})
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ok(payload: dict | None = None, **extra) -> web.Response:
    body = {"ok": True}
    body.update(payload or {})
    body.update(extra)
    return web.json_response(body)


def bad(message: str, status: int = 400, **extra) -> web.Response:
    return web.json_response(
        {"ok": False, "error": message, **extra}, status=status)


async def body(request: web.Request) -> dict:
    """The request's JSON object, or a 400 that does not quote the parser.

    The decoder's message names a line and a column of the body it was
    handed, which is useful and is not ours to hand back: it is text from a
    library, about input, echoed to whoever sent it. It goes to the log,
    where the person debugging an automation can read it, and the caller
    gets the sentence that tells them what to change.
    """
    try:
        payload = await request.json()
    except (ValueError, TypeError) as exc:
        log.warning("Malformed JSON body on %s: %s",
                    _for_log(request.path), _for_log(exc, 200))
        raise web.HTTPBadRequest(
            text=json.dumps({
                "ok": False,
                "error": "That request body was not valid JSON. The add-on "
                         "log has the parser's own message, with the line it "
                         "stopped on.",
            }),
            content_type="application/json") from exc
    return payload if isinstance(payload, dict) else {}


def panel(request: web.Request) -> Panel:
    return request.app[PANEL_KEY]


def _refuse(message: str) -> web.HTTPBadRequest:
    """A 400 whose body is a sentence this codebase wrote."""
    return web.HTTPBadRequest(
        text=json.dumps({"ok": False, "error": message}),
        content_type="application/json")


# Everything else a control character does to a log is cosmetic; CR and LF
# are the two that end a line, and a forged line in an add-on log is a
# forged line in whatever a person pastes into an issue. Paths, template
# names and a decoder's message quoting the body all arrive from the wire.
_LOG_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _for_log(value: object, limit: int = 120) -> str:
    """A value from the wire, safe to put in a log line.

    The two `replace` calls are not redundant against the regex below —
    they are the part that matters, written so it is unmistakable which
    characters are the hazard. The regex then takes the rest, which corrupt
    a line rather than forging one, and the slice keeps a long path from
    pushing everything else off the end of it.
    """
    text = str(value).replace("\r", "?").replace("\n", "?")
    return _LOG_CONTROL.sub("?", text)[:limit]


def _render(state: Panel, document: dict, *, dpi: int | None = None,
            head_dots: int | None = None):
    """Parse and draw a label document. Raises with a readable sentence."""
    try:
        parsed = label_doc.Label.from_dict(document)
    except label_doc.LabelError as exc:
        # LabelError, not ValueError: the message is one this codebase wrote
        # for a person, and catching the base class would put any ValueError
        # raised four frames down inside Pillow on the wire too.
        raise _refuse(exc.args[0] if exc.args else "That label cannot be read.")

    try:
        stock = state.stocks.require(parsed.stock)
    except stock_store.UnknownStock as exc:
        raise _refuse(exc.detail)

    printer = state.chosen()
    model = printer.model if printer else dymo_printers.UNKNOWN
    return parsed, stock, render_image.render(
        parsed, stock,
        dpi=dpi or model.dpi,
        max_across_dots=head_dots or model.dots,
        assets=state.assets,
    )


async def _send(state: Panel, rendered, *, side: str, copies: int) -> dict:
    """Pack, send, and turn any USB failure into a sentence."""
    printer = state.chosen()
    model = printer.model if printer else dymo_printers.UNKNOWN
    roll_code = protocol.ROLL_CODES.get(side) if model.twin else None

    lines = render_image.raster_lines(rendered, model.bytes_per_line)
    # `bare` drops roll select: on a Twin Turbo that means every label goes
    # to whichever bay the printer last used, which is a real cost and the
    # reason it is the last mode to try rather than a safe default.
    mode = str(state.settings.get("print_mode", "standard"))
    payload = protocol.job(
        lines, bytes_per_line=model.bytes_per_line,
        roll=None if mode == "bare" else roll_code,
        copies=copies, label_length_dots=rendered.feed_dots,
        compress=(mode == "compact"))

    try:
        return await asyncio.to_thread(
            usb_link.send, payload, state.printer_key())
    except (usb_link.UsbUnavailable, usb_link.PrinterNotFound,
            usb_link.PrinterBusy) as exc:
        # These three are the only exceptions usb_link raises, and every one
        # of their messages is composed in `usb_link._explain` for somebody
        # standing at a printer. Echoing them is the point.
        raise PrintRefused(str(exc)) from exc


def _title(document: dict) -> str:
    """A name for the history row, taken from the label's own first words.

    Falling back to the first text element rather than to "Label" because a
    history of twenty rows all called "Label" is a history nobody reads, and
    the label's own biggest words are what a person recognises it by.
    """
    name = str(document.get("name", "") or "").strip()
    if name:
        return name[:80]
    for element in document.get("elements") or []:
        if element.get("type") == "text":
            text = str((element.get("props") or {}).get("text", "") or "")
            text = " ".join(text.split())
            if text:
                return text[:80]
    return "(untitled)"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
async def h_health(request: web.Request) -> web.Response:
    """Liveness only. Deliberately does NOT touch USB.

    A health check that walks the bus is a health check that reports a
    printer being unplugged as the add-on being broken, and the watchdog
    would restart a perfectly good panel because somebody took the
    LabelWriter to another bench.
    """
    return ok(uptime_s=round(time.time() - panel(request).started))


async def h_state(request: web.Request) -> web.Response:
    return web.json_response(panel(request).state_payload())


async def h_printers(request: web.Request) -> web.Response:
    state = panel(request)
    found = await asyncio.to_thread(state.discover, force=True)
    return ok(printers=[p.as_dict() for p in found],
              error=state._printers_error,
              usb_available=usb_link.available())


async def h_printer_select(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    key = str(payload.get("printer", "") or "")
    if key and not any(p.key == key for p in state.discover(force=True)):
        return bad(f"No printer with the id {key} is plugged in.", 404)
    state.settings.update({"printer": key})
    state.mirror_state()
    return ok(settings=state.settings.all(),
              printer=(state.chosen().as_dict() if state.chosen() else None))


async def h_printer_status(request: web.Request) -> web.Response:
    state = panel(request)
    try:
        result = await asyncio.to_thread(usb_link.probe, state.printer_key())
    except (usb_link.UsbUnavailable, usb_link.PrinterNotFound,
            usb_link.PrinterBusy) as exc:
        # Authored in usb_link._explain — see the note in `_send`.
        return bad(str(exc), 503)
    return ok(result)


async def h_printer_usb(request: web.Request) -> web.Response:
    """What the USB device looks like — descriptors, not guesses."""
    state = panel(request)
    try:
        report = await asyncio.to_thread(usb_link.describe, state.printer_key())
    except (usb_link.UsbUnavailable, usb_link.PrinterNotFound,
            usb_link.PrinterBusy) as exc:
        return bad(str(exc), 503)
    return ok(**report)


async def h_printer_test(request: web.Request) -> web.Response:
    """Print the ruler.

    Which is not a decorative self-test: it is the only way to answer the
    question the panel genuinely cannot ("is this stock's width really its
    first number?"), because a LabelWriter never reports what it printed on.
    The ruler is ticks at every 5mm across the head and a scale down the
    feed, so holding it against the label tells you both dimensions and
    whether they are the way round the catalog thinks.
    """
    state = panel(request)
    payload = await body(request)
    stock_id = str(payload.get("stock") or state.settings.get("default_stock"))
    side = str(payload.get("side", "") or "")

    try:
        stock = state.stocks.require(stock_id)
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)

    side, notes = state.resolve_side(stock.id, side)
    document = _ruler_label(stock)
    parsed, stock, rendered = _render(state, document)
    result = await _send(state, rendered, side=side, copies=1)
    state.consume(side, 1)
    state.mirror_state()
    return ok(printed=1, side=side, notes=notes + rendered.notes, **result)


def _ruler_label(stock) -> dict:
    """A measuring label: ticks across the head, a scale down the feed."""
    across_mm, feed_mm = stock.drawable_mm
    elements: list[dict] = [{
        "type": "text", "x_mm": 0, "y_mm": 0,
        "w_mm": across_mm, "h_mm": min(4.0, feed_mm / 3),
        "props": {"text": f'{stock.across_in}" × {stock.feed_in}"',
                  "font": "sans-bold", "size_mm": 0, "align": "left",
                  "valign": "top"},
    }]
    top = min(4.0, feed_mm / 3) + 1
    for millimetre in range(0, int(across_mm) + 1, 5):
        tall = 3.0 if millimetre % 10 == 0 else 1.6
        elements.append({
            "type": "line", "x_mm": millimetre, "y_mm": top,
            "w_mm": 0.3, "h_mm": min(tall, feed_mm - top),
            "props": {"stroke_mm": 0.3},
        })
    for millimetre in range(0, int(feed_mm) + 1, 5):
        wide = 3.0 if millimetre % 10 == 0 else 1.6
        elements.append({
            "type": "line", "x_mm": 0, "y_mm": millimetre,
            "w_mm": min(wide, across_mm), "h_mm": 0.3,
            "props": {"stroke_mm": 0.3},
        })
    elements.append({
        "type": "box", "x_mm": 0, "y_mm": 0,
        "w_mm": across_mm, "h_mm": feed_mm,
        "props": {"stroke_mm": 0.3, "fill": False, "radius_mm": 0},
    })
    return {"stock": stock.id, "rotate": 0, "name": "Ruler",
            "elements": elements}


# -- stocks -----------------------------------------------------------------
async def h_stocks(request: web.Request) -> web.Response:
    return ok(stocks=[s.as_dict() for s in panel(request).stocks.all()])


async def h_stock_put(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    identifier = str(payload.get("id", "") or "").strip().lower()
    name = str(payload.get("name", "") or "").strip()
    if not name:
        return bad("A label stock needs a name.")
    if not identifier:
        identifier = "".join(
            c if c.isalnum() else "-" for c in name.lower()).strip("-")[:40]
    try:
        across = float(payload.get("across_in"))
        feed = float(payload.get("feed_in"))
    except (TypeError, ValueError):
        return bad("Both measurements have to be numbers, in inches.")
    if across <= 0:
        return bad("The across-the-head measurement has to be more than zero "
                   "— that is the dimension the print head covers.")
    if feed < 0:
        return bad("The feed measurement cannot be negative. Use 0 for "
                   "continuous stock with no die-cut length.")

    entry = stock_store.Stock(
        id=identifier, name=name, across_in=across, feed_in=feed,
        sku=str(payload.get("sku", "") or ""),
        per_roll=max(0, int(payload.get("per_roll", 0) or 0)),
        margin_mm=max(0.0, float(payload.get("margin_mm",
                                             stock_store.DEFAULT_MARGIN_MM))),
        notes=str(payload.get("notes", "") or ""),
    )
    state.stocks.put(entry)
    state.mirror_state()
    return ok(stock=entry.as_dict(),
              stocks=[state._stock_row(s) for s in state.stocks.all()])


async def h_stock_swap(request: web.Request) -> web.Response:
    state = panel(request)
    try:
        entry = state.stocks.require(request.match_info["stock_id"])
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)
    swapped = state.stocks.put(entry.swapped())
    state.mirror_state()
    return ok(stock=swapped.as_dict(),
              stocks=[state._stock_row(s) for s in state.stocks.all()])


async def h_stock_turn(request: web.Request) -> web.Response:
    """Set (or clear) which way artwork sits on this stock.

    `turn: null` puts it back to being derived from the shape, which is a
    different state from `turn: 0` — one is "nobody has said", the other is
    "somebody said across", and they diverge the moment the stock is
    swapped or its measurements corrected.
    """
    state = panel(request)
    try:
        entry = state.stocks.require(request.match_info["stock_id"])
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)
    payload = await body(request)
    raw = payload.get("turn", None)
    if raw in (None, "", "auto"):
        turn = None
    else:
        try:
            turn = int(raw)
        except (TypeError, ValueError):
            return bad("A turn is a number of degrees.")
        if turn not in label_doc.ROTATIONS:
            allowed = ", ".join(f"{r}°" for r in label_doc.ROTATIONS)
            return bad(f"A label can be turned {allowed} — not {turn}°.")
    updated = state.stocks.put(
        stock_store.replace(entry, turn=turn, builtin=False))
    state.mirror_state()
    return ok(stock=state._stock_row(updated),
              stocks=[state._stock_row(s) for s in state.stocks.all()])


async def h_stock_delete(request: web.Request) -> web.Response:
    state = panel(request)
    stock_id = request.match_info["stock_id"]
    in_use = [r.side for r in state.rolls.all() if r.stock == stock_id]
    if in_use:
        return bad(
            f"That stock is loaded in the {' and '.join(in_use)} roll. "
            f"Unload it first, or the panel would be checking labels against "
            f"a stock it no longer has.", 409)
    state.stocks.remove(stock_id)
    state.mirror_state()
    return ok(stocks=[state._stock_row(s) for s in state.stocks.all()])


async def h_stock_restore(request: web.Request) -> web.Response:
    state = panel(request)
    state.stocks.restore(request.match_info["stock_id"])
    state.mirror_state()
    return ok(stocks=[state._stock_row(s) for s in state.stocks.all()])


# -- rolls ------------------------------------------------------------------
async def h_roll_set(request: web.Request) -> web.Response:
    state = panel(request)
    side = request.match_info["side"]
    payload = await body(request)
    stock_id = str(payload.get("stock", "") or "")
    try:
        entry = state.stocks.require(stock_id)
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)
    count = payload.get("remaining")
    if count in (None, ""):
        count = entry.per_roll
    try:
        roll = state.rolls.load_roll(
            side, entry.id, count=int(count),
            note=str(payload.get("note", "") or ""))
    except loaded.UnknownSide as exc:
        return bad(exc.detail, 404)
    state.mirror_state()
    return ok(roll=roll.as_dict(),
              rolls=[r.as_dict() for r in state.rolls.all()])


async def h_roll_clear(request: web.Request) -> web.Response:
    state = panel(request)
    try:
        state.rolls.unload(request.match_info["side"])
    except loaded.UnknownSide as exc:
        return bad(exc.detail, 404)
    state.mirror_state()
    return ok(rolls=[r.as_dict() for r in state.rolls.all()])


# -- rendering and printing -------------------------------------------------
async def h_preview(request: web.Request) -> web.Response:
    """A PNG of the label exactly as it will print.

    Exactly as it will print: same renderer, same threshold, same head width,
    same clipping. The scale is nearest-neighbour so a dot stays a dot — a
    smoothed preview shows soft edges the printer cannot make, and the
    preview's whole value is being believed.
    """
    state = panel(request)
    payload = await body(request)
    scale = max(1, min(8, int(payload.get("scale",
                                          state.settings.get("preview_scale", 2)))))
    document = payload.get("label") or payload
    parsed, entry, rendered = await asyncio.to_thread(_render, state, document)
    png = await asyncio.to_thread(rendered.png, scale)
    return web.Response(
        body=png, content_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Label-Dots": f"{rendered.across_dots}x{rendered.feed_dots}",
            "X-Label-Notes": json.dumps(rendered.notes),
        })


async def h_print(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    document = payload.get("label") or {}
    copies = max(1, min(500, int(payload.get("copies", 1) or 1)))
    side_wanted = str(payload.get("side", "") or "")

    parsed, entry, rendered = await asyncio.to_thread(_render, state, document)
    side, notes = state.resolve_side(entry.id, side_wanted)
    result = await _send(state, rendered, side=side, copies=copies)

    state.consume(side, copies)
    record = state.history.add(
        stock=entry.id, side=side, copies=copies, title=_title(document),
        label=parsed.as_dict(), source=str(payload.get("source", "panel")),
        template=str(payload.get("template", "") or ""),
        printer=(state.chosen().key if state.chosen() else ""))
    state.mirror_state()
    return ok(printed=copies, side=side, entry=record.as_dict(),
              notes=notes + rendered.notes, **result)


async def h_quick(request: web.Request) -> web.Response:
    """A word in, a label out — previewed or printed in one call.

    One route for both because the quick path is one thought: you type, you
    look, you print. Splitting it into a preview endpoint and a print
    endpoint would make the panel fit the text twice and risk the two
    disagreeing, which on this path is the label coming out at a size other
    than the one on screen.
    """
    state = panel(request)
    payload = await body(request)
    text = str(payload.get("text", "") or "")
    stock_id = str(payload.get("stock") or state.settings.get("default_stock"))

    try:
        entry = state.stocks.require(stock_id)
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)

    rotate = payload.get("rotate")
    if rotate is None:
        # The stock's own answer, not a global switch. Which way text sits
        # on a label is a property of the label — a cryo wrap reads along
        # the roll and an address label reads across it, always — so it is
        # remembered per stock and corrected once, rather than being a
        # question on every print or one setting covering stocks that
        # disagree with each other.
        rotate = entry.natural_turn

    try:
        fitted = await asyncio.to_thread(
            quick.fit, text, entry,
            font=str(payload.get("font") or state.settings.get("default_font")),
            rotate=int(rotate),
            uppercase=bool(payload.get("uppercase",
                                       state.settings.get("quick_uppercase"))),
            max_mm=(float(payload["max_mm"]) if payload.get("max_mm") else None),
        )
    except ValueError as exc:
        # quick.fit raises exactly one, and its text is written for a person
        # ("There is nothing to print — type a word first.").
        return bad(str(exc))

    document = fitted.label.as_dict()
    parsed, entry, rendered = await asyncio.to_thread(_render, state, document)

    if not payload.get("print"):
        scale = max(1, min(8, int(payload.get("scale", 2))))
        png = await asyncio.to_thread(rendered.png, scale)
        import base64  # noqa: PLC0415
        return ok(label=document, fit=fitted.as_dict(),
                  notes=rendered.notes,
                  png="data:image/png;base64,"
                      + base64.b64encode(png).decode())

    copies = max(1, min(500, int(payload.get("copies", 1) or 1)))
    side, notes = state.resolve_side(entry.id, str(payload.get("side", "") or ""))
    result = await _send(state, rendered, side=side, copies=copies)
    state.consume(side, copies)
    record = state.history.add(
        stock=entry.id, side=side, copies=copies, title=" ".join(fitted.lines),
        label=document, source=str(payload.get("source", "quick")),
        printer=(state.chosen().key if state.chosen() else ""))
    state.mirror_state()
    return ok(printed=copies, side=side, label=document, fit=fitted.as_dict(),
              entry=record.as_dict(), notes=notes + rendered.notes, **result)


# -- templates --------------------------------------------------------------
async def h_templates(request: web.Request) -> web.Response:
    return ok(templates=[t.as_dict() for t in panel(request).templates.all()])


async def h_template_put(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    name = str(payload.get("name", "") or "").strip()
    if not name:
        return bad("A template needs a name — it is what you pick it by, and "
                   "what an automation calls it.")
    document = payload.get("label") or {}
    try:
        parsed = label_doc.Label.from_dict(document)
    except label_doc.LabelError as exc:
        return bad(exc.args[0] if exc.args else "That label cannot be read.")

    declared = {f.get("key"): f for f in (payload.get("fields") or [])
                if isinstance(f, dict) and f.get("key")}
    # The fields are taken from the LABEL, not from what the client sent:
    # the placeholders in the document are the truth about what this template
    # needs, and a declared field that no longer appears is a box on the form
    # that fills nothing.
    found = template_store.placeholders(parsed.as_dict())
    builtin = set(template_store.builtin_now())
    fields = [
        template_store.Field(
            key=key,
            label=str(declared.get(key, {}).get("label", "") or ""),
            default=str(declared.get(key, {}).get("default", "") or ""),
            hint=str(declared.get(key, {}).get("hint", "") or ""),
            multiline=bool(declared.get(key, {}).get("multiline", False)),
        )
        for key in found if key not in builtin
    ]

    entry = template_store.Template(
        id=str(payload.get("id", "") or ""),
        name=name,
        label=parsed.as_dict(),
        fields=fields,
        description=str(payload.get("description", "") or ""),
        icon=str(payload.get("icon", "") or "mdi:label"),
        copies=max(1, int(payload.get("copies", 1) or 1)),
        pinned=bool(payload.get("pinned", False)),
    )
    saved = state.templates.put(entry)
    state.mirror_state()
    return ok(template=saved.as_dict(),
              templates=[t.as_dict() for t in state.templates.all()])


async def h_template_delete(request: web.Request) -> web.Response:
    state = panel(request)
    if not state.templates.remove(request.match_info["template_id"]):
        return bad("That template is already gone.", 404)
    state.mirror_state()
    return ok(templates=[t.as_dict() for t in state.templates.all()])


def _fill(state: Panel, template, payload: dict) -> tuple[dict, list[str]]:
    values = payload.get("fields") or {}
    if not isinstance(values, dict):
        values = {}
    defaults = {f.key: f.default for f in template.fields if f.default}
    merged = {**defaults, **{k: v for k, v in values.items() if v not in (None, "")}}
    return template_store.apply_fields(template.label, merged)


async def h_template_preview(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    try:
        template = state.templates.resolve(request.match_info["template_id"])
    except template_store.UnknownTemplate as exc:
        return bad(exc.detail, 404)
    document, missing = _fill(state, template, payload)
    parsed, entry, rendered = await asyncio.to_thread(_render, state, document)
    scale = max(1, min(8, int(payload.get("scale", 2))))
    png = await asyncio.to_thread(rendered.png, scale)
    import base64  # noqa: PLC0415
    return ok(label=document, missing=missing, notes=rendered.notes,
              png="data:image/png;base64," + base64.b64encode(png).decode())


async def h_template_print(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    try:
        template = state.templates.resolve(request.match_info["template_id"])
    except template_store.UnknownTemplate as exc:
        return bad(exc.detail, 404)

    document, missing = _fill(state, template, payload)
    if missing and payload.get("require_fields", True):
        # A blank field is a refusal here and a warning in the designer, and
        # that difference is the point: the designer has a person looking at
        # the preview, and this call is usually an automation that will
        # otherwise print fifty labels with a hole in them.
        return bad(
            f"{template.name} still needs: {', '.join(missing)}.",
            422, missing=missing)

    copies = max(1, min(500, int(payload.get("copies", template.copies) or 1)))
    parsed, entry, rendered = await asyncio.to_thread(_render, state, document)
    side, notes = state.resolve_side(entry.id, str(payload.get("side", "") or ""))
    result = await _send(state, rendered, side=side, copies=copies)

    state.consume(side, copies)
    state.templates.used(template.id)
    record = state.history.add(
        stock=entry.id, side=side, copies=copies,
        title=_title(document) or template.name, label=parsed.as_dict(),
        source=str(payload.get("source", "template")), template=template.name,
        printer=(state.chosen().key if state.chosen() else ""))
    state.mirror_state()
    return ok(printed=copies, side=side, entry=record.as_dict(),
              missing=missing, notes=notes + rendered.notes, **result)


# -- history ----------------------------------------------------------------
async def h_history(request: web.Request) -> web.Response:
    limit = int(request.query.get("limit", 50) or 50)
    return ok(history=[e.as_dict()
                       for e in panel(request).history.all(limit)])


async def h_reprint(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    entry = state.history.get(request.match_info["entry_id"])
    if entry is None:
        return bad("That print is no longer in the history.", 404)

    copies = max(1, min(500, int(payload.get("copies", entry.copies) or 1)))
    parsed, stock_entry, rendered = await asyncio.to_thread(
        _render, state, entry.label)
    side, notes = state.resolve_side(
        stock_entry.id, str(payload.get("side", "") or entry.side))
    result = await _send(state, rendered, side=side, copies=copies)

    state.consume(side, copies)
    record = state.history.add(
        stock=stock_entry.id, side=side, copies=copies, title=entry.title,
        label=entry.label, source="reprint", template=entry.template,
        printer=(state.chosen().key if state.chosen() else ""))
    state.mirror_state()
    return ok(printed=copies, side=side, entry=record.as_dict(),
              notes=notes + rendered.notes, **result)


async def h_history_clear(request: web.Request) -> web.Response:
    state = panel(request)
    state.history.clear()
    state.mirror_state()
    return ok(history=[])


# -- assets -----------------------------------------------------------------
async def h_asset_upload(request: web.Request) -> web.Response:
    state = panel(request)
    reader = await request.multipart()
    saved: list[str] = []
    while True:
        part = await reader.next()
        if part is None:
            break
        if not getattr(part, "filename", None):
            continue
        name = Path(part.filename).name
        if Path(name).suffix.lower() not in ALLOWED_ASSET_SUFFIXES:
            return bad(
                f"“{name}” is not an image BRUH Print can read. PNG, JPEG, "
                f"GIF, BMP and WebP work.")
        blob = bytearray()
        while True:
            chunk = await part.read_chunk()
            if not chunk:
                break
            blob.extend(chunk)
            if len(blob) > MAX_ASSET_BYTES:
                return bad(
                    f"“{name}” is over {MAX_ASSET_BYTES // (1024 * 1024)}MB. "
                    f"A label is at most 1248 dots across — a large image "
                    f"buys nothing the printer can show.", 413)
        atomic_write.write_bytes(state.assets / name, bytes(blob))
        saved.append(name)
    if not saved:
        return bad("No file arrived with that upload.")
    return ok(saved=saved, assets=state.asset_list())


async def h_asset_get(request: web.Request) -> web.Response:
    state = panel(request)
    name = Path(request.match_info["name"]).name
    path = (state.assets / name).resolve()
    if path.parent != state.assets.resolve() or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "max-age=60"})


async def h_asset_delete(request: web.Request) -> web.Response:
    state = panel(request)
    name = Path(request.match_info["name"]).name
    path = (state.assets / name).resolve()
    if path.parent == state.assets.resolve():
        path.unlink(missing_ok=True)
    return ok(assets=state.asset_list())


# -- settings ---------------------------------------------------------------
async def h_settings_get(request: web.Request) -> web.Response:
    return ok(settings=panel(request).settings.all())


async def h_settings_put(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    updated = state.settings.update(payload.get("settings") or payload)
    state.mirror_state()
    return ok(settings=updated)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
class QuietAccessLogger(AbstractAccessLogger):
    """Successful polls are not news.

    The Lovelace card and the panel both poll `/api/state`, so at the default
    level a working install writes a line every couple of seconds and the
    add-on log becomes useless for the one thing it is for. Failures always
    log, and `log_level: debug` turns everything back on.

    It subclasses `AbstractAccessLogger` because `run_app` type-checks the
    class it is handed, and the version that shipped did not — it was a
    plain class with a duck-typed `log`, which every test instantiated
    directly and therefore never type-checked. The add-on started, wrote
    "listening on 0.0.0.0:8097", and died on the next line with

        TypeError: access_log_class must be subclass of
        aiohttp.abc.AbstractAccessLogger

    The base class also owns `__init__`, taking (logger, log_format) — which
    is what `run_app` passes and what a test has to pass too.
    """

    QUIET = ("/api/state", "/api/health", "/api/printers")

    def log(self, request, response, time_taken):  # noqa: D102
        status = getattr(response, "status", 0)
        path = getattr(request, "path", "")
        # The prefix test is on the REAL path and the log line carries the
        # cleaned one: sanitising first would let a crafted path match a
        # quiet prefix it does not have, which is a request that goes
        # unlogged rather than a forged line — quieter, and worse.
        quiet = status < 400 and any(path.startswith(p) for p in self.QUIET)
        method = _for_log(getattr(request, "method", "?"), 8)
        if quiet:
            self.logger.debug("%s %s %s", method, _for_log(path), status)
            return
        level = logging.WARNING if status >= 400 else logging.INFO
        self.logger.log(level, "%s %s %s (%.0fms)", method, _for_log(path),
                      status, time_taken * 1000)


def _asset(name: str, content_type: str):
    """One of the panel's own files, by name.

    The name is a literal at every call site — never anything off the wire —
    which is what makes this safe where serving a directory was not.
    """
    path = PANEL_DIR / name

    async def handler(_request: web.Request) -> web.FileResponse:
        return web.FileResponse(path, headers={"Content-Type": content_type})

    return handler


@web.middleware
async def json_errors(request: web.Request, handler):
    """Every failure leaves as JSON with a sentence in it.

    An aiohttp HTTPException renders as an HTML page by default, and an HTML
    page reaching the bridge is an automation trace saying `<!DOCTYPE html>`.
    A raised `PrintRefused` already carries its JSON body, which is why the
    content type is checked rather than the class.
    """
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if exc.content_type == "application/json":
            raise
        return web.json_response(
            {"ok": False, "error": exc.reason or "request failed"},
            status=exc.status)
    except Exception:  # noqa: BLE001 - the panel must not 500 silently
        # The traceback goes to the log and the exception's text does not go
        # to the caller: an unexpected error is by definition one whose
        # message nobody here wrote, so it may name a path, a library
        # internal or a value from somewhere else entirely.
        log.exception("Unhandled error on %s", _for_log(request.path))
        return web.json_response(
            {"ok": False,
             "error": "BRUH Print hit an unexpected error. The add-on log "
                      "has the traceback — it is the one thing worth "
                      "attaching to a bug report."},
            status=500)


def build_app(state: Panel | None = None) -> web.Application:
    app = web.Application(middlewares=[json_errors],
                          client_max_size=MAX_ASSET_BYTES + 1024 * 1024)
    app[PANEL_KEY] = state or Panel()

    add = app.router.add_route
    app.router.add_get("/api/health", h_health)
    app.router.add_get("/api/state", h_state)

    app.router.add_get("/api/printers", h_printers)
    app.router.add_post("/api/printer/select", h_printer_select)
    app.router.add_get("/api/printer/status", h_printer_status)
    app.router.add_post("/api/printer/test", h_printer_test)
    app.router.add_get("/api/printer/usb", h_printer_usb)

    app.router.add_get("/api/stocks", h_stocks)
    app.router.add_post("/api/stock", h_stock_put)
    app.router.add_post("/api/stock/{stock_id}/swap", h_stock_swap)
    app.router.add_post("/api/stock/{stock_id}/turn", h_stock_turn)
    app.router.add_post("/api/stock/{stock_id}/restore", h_stock_restore)
    add("DELETE", "/api/stock/{stock_id}", h_stock_delete)

    app.router.add_post("/api/roll/{side}", h_roll_set)
    add("DELETE", "/api/roll/{side}", h_roll_clear)

    app.router.add_post("/api/preview", h_preview)
    app.router.add_post("/api/print", h_print)
    app.router.add_post("/api/quick", h_quick)

    app.router.add_get("/api/templates", h_templates)
    app.router.add_post("/api/template", h_template_put)
    add("DELETE", "/api/template/{template_id}", h_template_delete)
    app.router.add_post("/api/template/{template_id}/preview",
                        h_template_preview)
    app.router.add_post("/api/template/{template_id}/print", h_template_print)

    app.router.add_get("/api/history", h_history)
    add("DELETE", "/api/history", h_history_clear)
    app.router.add_post("/api/history/{entry_id}/reprint", h_reprint)

    app.router.add_post("/api/assets", h_asset_upload)
    app.router.add_get("/api/assets/{name}", h_asset_get)
    add("DELETE", "/api/assets/{name}", h_asset_delete)

    app.router.add_get("/api/settings", h_settings_get)
    app.router.add_post("/api/settings", h_settings_put)

    # The UI last, so a static file can never shadow an API route.
    #
    # Four named routes rather than `add_static(PANEL_DIR)`, which served the
    # whole panel directory: `GET /static/server.py` answered 200 with this
    # file, and so did every module under `stores/` and `dymo/`. Nothing in
    # there is a secret — this add-on holds no credential — but an add-on
    # serving its own source tree is a mistake waiting to become one, and
    # naming the four files that ARE assets costs three lines.
    app.router.add_get("/", _asset("index.html", "text/html"))
    app.router.add_get("/index.html", _asset("index.html", "text/html"))
    app.router.add_get("/style.css", _asset("style.css", "text/css"))
    app.router.add_get("/app.js", _asset("app.js", "application/javascript"))
    app.router.add_get("/favicon.svg", _asset("favicon.svg", "image/svg+xml"))
    return app


def main() -> None:
    level = os.environ.get("BRUH_PRINT_LOG_LEVEL", "info").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="[panel %(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S")

    port = int(os.environ.get("BRUH_PRINT_PANEL_PORT", DEFAULT_PORT))
    state = Panel()
    state.mirror_state()

    # "Listening" is said by the callback `run_app` invokes once every site
    # is actually up, not by a line above the call that runs whether it works
    # or not. v0.1.0 logged "listening on 0.0.0.0:8097" immediately above the
    # traceback proving it was not — which is BRight's `panel_port` lesson
    # word for word, repeated in a new add-on: a log that claims a thing
    # before doing it is a log that sends whoever reads it past the failure.
    log.info("Starting the BRUH Print panel on %s:%s", BIND_HOST, port)
    web.run_app(build_app(state), host=BIND_HOST, port=port,
                access_log_class=QuietAccessLogger,
                access_log=logging.getLogger("bruh_print.access"),
                print=lambda *_args: log.info(
                    "BRUH Print panel listening on %s:%s", BIND_HOST, port))


if __name__ == "__main__":
    main()
