#!/usr/bin/env python3
"""BRUH Print — the ingress panel.

    GET  /api/health                 liveness, polled by the Supervisor watchdog
    GET  /api/state                  everything the UI opens with, in one call
    GET  /api/printers               what is on the USB bus right now
    POST /api/printer/select         remember which one is the default
    GET  /api/printer/status         ask the printer how it is
    POST /api/printer/test           print the ruler
    POST /api/printer/calibrate      print the two calibration labels
    POST /api/printer/check          print the frame that proves the answer
    POST /api/printer/feed           feed the last label out to the tear bar
    GET  /api/stocks                 the label catalog
    POST /api/stock                  add or correct a stock
    POST /api/stock/{id}/swap        the two dimensions, exchanged
    POST /api/stock/{id}/calibration five readings -> what this roll does
    DEL  /api/stock/{id}/calibration forget them and print as shipped
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
    GET  /api/font/{key}/sample.png  what that font looks like, drawn by the renderer

Two rules shape the whole file.

**A print is refused when it cannot be right, and never when it merely might
not be.** The one refusal is a stock/roll mismatch — sending a 2.25"-wide
raster to a 0.56" roll prints across the liner, and a run of fifty does it
fifty times. Everything else that could be wrong (a barcode that will not
fit, a fixed font size that clips, an element type a release retired) comes
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
import calibration  # noqa: E402
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
SHARED = Path(os.environ.get("BRUH_PRINT_SHARED", "/config/.bruh_print"))

BIND_HOST = "0.0.0.0"  # noqa: S104 - ingress reaches the container, not the LAN
DEFAULT_PORT = 8097

# The largest body the panel will read. Everything it accepts is now a JSON
# label document — a few hundred boxes of millimetres and words — so this is
# generous rather than tight, and it is a named number rather than aiohttp's
# 1 MB default because a limit nobody chose is a limit nobody can explain the
# day a template with sixty fields is refused. It was 9 MB while an image
# upload rode the same route; nothing uploads a file any more.
MAX_BODY_BYTES = 2 * 1024 * 1024

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
        self.started = time.time()
        # Discovery is a USB bus walk and the UI asks for state on every tab
        # change, so it is cached for a couple of seconds. Long enough that a
        # click storm costs one walk; short enough that plugging a printer in
        # and looking at the panel shows it.
        self._printers: list[dymo_printers.Discovered] = []
        self._printers_at = 0.0
        self._printers_error = ""
        # Where each bay's paper is sitting: at the tear bar, or still
        # inside the printer. See `at_tear_off`.
        self._at_tear: dict[str, bool] = {}

    # -- what the paper did last -------------------------------------------
    def _tear_key(self, side: str) -> str:
        printer = self.chosen()
        return f"{printer.key if printer else ''}|{side}"

    def at_tear_off(self, side: str) -> bool:
        """Is this bay's paper parked at the tear bar?

        The manual: an `ESC E` "places the next label beyond the starting
        print position. Therefore, a reverse-feed will be automatically
        invoked when printing on the next label." On a printer that does not
        make that reverse feed, the first label of the next job starts late
        by a fixed amount and every label after it does not
        (`Calibration.after_tear_mm`) — so whether the paper is there is a
        fact the print path has to hold, and there is nothing on a
        LabelWriter to ask.

        It is in memory rather than on disk because it is a fact about paper,
        and paper is what somebody changes while the add-on is stopped.
        Unknown reads as **true**: a printer nobody is using has almost
        always just had a label torn off it, and the two ways of being wrong
        are not the same size — charging a band that is not there leaves a
        few blank millimetres at the top of one label, while not charging one
        that is loses ink off it.
        """
        return self._at_tear.get(self._tear_key(side), True)

    def record_ending(self, side: str, ending: str) -> None:
        """What the job that just went out left the paper doing."""
        self._at_tear[self._tear_key(side)] = ending == "tear"

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
            head_dots: int | None = None, stock=None):
    """Parse and draw a label document. Raises with a readable sentence.

    `stock` overrides the catalog lookup, and exactly one thing uses it: the
    calibration label, which has to be drawn to the FULL sheet and so is
    rendered against a copy of the roll with no margin. It is a copy that is
    never saved — the point of the calibration label is to measure the roll
    a person actually has, not to change it.
    """
    try:
        parsed = label_doc.Label.from_dict(document)
    except label_doc.LabelError as exc:
        # LabelError, not ValueError: the message is one this codebase wrote
        # for a person, and catching the base class would put any ValueError
        # raised four frames down inside Pillow on the wire too.
        raise _refuse(exc.args[0] if exc.args else "That label cannot be read.")

    if stock is None:
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
    )


def _label_geometry(stock, cal, model, pre_skip_mm: float = 0.0):
    """The three numbers the wire needs about the paper, in printer dots.

    Rounded here and nowhere else — the same `mm_to_dots` every millimetre in
    this add-on goes through, once, at the print resolution.

    The label length is the STOCK's, never the raster's, and the two differ
    exactly where it matters: a cropped sheet is shorter than the label it
    was cut from and continuous paper has a raster and no label at all.
    `ESC L` is a question about where the next sense hole is, and cropping
    artwork did not move it.

    The lead is signed on purpose and it is the whole of the print path's
    half of the calibration: positive is paper to feed before the first row
    (`ESC f`), negative is rows the printer will not lay and that are cut off
    the front of the sheet instead. One number, two mechanisms, chosen in
    `_send_copies` and nowhere else.
    """
    feed_dots = render_image.mm_to_dots(stock.measured_feed_mm, model.dpi)
    gap_dots = (None if cal.gap_mm is None
                else render_image.mm_to_dots(cal.gap_mm, model.dpi))
    lead_dots = render_image.mm_to_dots(pre_skip_mm - cal.start_mm, model.dpi)
    return feed_dots, gap_dots, lead_dots


async def _send_copies(state: Panel, sheets, *, stock, side: str,
                       cal=None, pre_skip_mm: float = 0.0) -> dict:
    """Pack a page per copy, send them as one job, and say why on a failure.

    A copy is a page rather than a repeat count because two of them can
    differ. The first label of a job is the one that follows a tear-off, and
    on a printer that does not make the reverse feed it owes, that label —
    and only that label — starts late; the calibration job prints two labels
    that carry different numbers. Both were unsayable while a job was a list
    of rows and a count.

    What each page gets is decided by one signed number. Ink asked for before
    the die cut is paper to feed first (`ESC f`); ink asked for inside a band
    the printer will not lay is rows to cut off the front of the sheet, so
    what is sent begins at the first row that can carry ink and ends at the
    die cut. The 0.6.0 offset could express neither: it slid artwork around
    inside a sheet whose own start is the thing in question.
    """
    printer = state.chosen()
    model = printer.model if printer else dymo_printers.UNKNOWN
    roll_code = protocol.ROLL_CODES.get(side) if model.twin else None
    cal = stock.calibration if cal is None else cal

    mode = str(state.settings.get("print_mode", "standard"))
    # `bare` is the one mode that sends neither darkness nor speed nor the
    # dot-tab reset nor the sync run, leaving the printer at its own
    # defaults — which is the whole point of it: it is what somebody tries
    # when a firmware will not take a command, and a mode that still sent
    # four of them would not answer that question. It also drops roll
    # select, which on a Twin Turbo means every label goes to whichever bay
    # the printer last used: a real cost, and the reason it is the last mode
    # to try rather than a safe default.
    bare = mode == "bare"
    quality = None if bare else str(state.settings.get("quality", "graphics"))
    feed_dots, gap_dots, lead_dots = _label_geometry(stock, cal, model,
                                                     pre_skip_mm)

    # Only the first copy is charged the after-tear band, and only when the
    # paper is actually sitting at the tear bar — which is what the previous
    # job's own ending decides. A run of fifty labels has one first label.
    charged = state.at_tear_off(side)
    pages: list[protocol.Page] = []
    # Copies of one label are usually the same object, and packing a 375-row
    # raster is the expensive half of building a job. Keyed on the sheet's
    # identity and its lead, because those two are what decide the bytes.
    built: dict[tuple[int, int], protocol.Page] = {}
    for index, sheet in enumerate(sheets):
        lead = lead_dots
        if index == 0 and charged and cal.after_tear_mm:
            lead = render_image.mm_to_dots(
                pre_skip_mm - cal.start_mm - cal.after_tear_mm, model.dpi)
        key = (id(sheet), lead)
        page = built.get(key)
        if page is None:
            # Where this roll's paper sits under the head and how much of the
            # leading edge it cannot print on, applied on the way to the
            # printer and nowhere else. Both are statements about the
            # machine rather than changes to the label, so the document, the
            # preview and the designer all stay exactly as they were — and
            # the notes, when a page costs ink, go onto the rendered label's
            # own list, which is what every caller already reads after this
            # returns.
            to_print, placement_notes = render_image.for_the_head(
                sheet, across_mm=cal.across_mm, crop_dots=max(0, -lead),
                head_dots=model.dots)
            for note in placement_notes:
                if note not in sheet.notes:
                    sheet.notes.append(note)
            page = protocol.Page(
                render_image.raster_lines(to_print, model.bytes_per_line),
                max(0, lead))
            built[key] = page
        pages.append(page)

    payload = protocol.job_pages(
        pages, bytes_per_line=model.bytes_per_line,
        roll=None if bare else roll_code,
        # Hole to hole is the label plus the gap after it, which is what
        # `ESC L` is defined in. `None` keeps the 25%-with-a-floor headroom
        # that shipped, so a roll nobody has calibrated is untouched.
        gap_dots=gap_dots,
        label_feed_dots=feed_dots,
        continuous=stock.continuous,
        dot_tab=not bare,
        compress=(mode == "compact"),
        density=None if bare else str(state.settings.get("density", "dark")),
        quality=quality,
        job_start=cal.job_start,
        ending=cal.ending,
        sync=not bare)

    try:
        result = await asyncio.to_thread(
            usb_link.send, payload, state.printer_key())
    except (usb_link.UsbUnavailable, usb_link.PrinterNotFound,
            usb_link.PrinterBusy) as exc:
        # These three are the only exceptions usb_link raises, and every one
        # of their messages is composed in `usb_link._explain` for somebody
        # standing at a printer. Echoing them is the point.
        raise PrintRefused(str(exc)) from exc
    # After the write, never before: a job the bus refused did not move any
    # paper, and recording that it did would charge the next job's first
    # label for a tear-off that never happened.
    state.record_ending(side, cal.ending)
    return result


async def _send(state: Panel, rendered, *, stock, side: str,
                copies: int, cal=None, pre_skip_mm: float = 0.0) -> dict:
    """`copies` prints of one rendered label — the ordinary case.

    Every copy shares the same `Rendered`, which is what lets `_send_copies`
    pack the raster once for the whole run.
    """
    return await _send_copies(state, [rendered] * max(1, int(copies)),
                              stock=stock, side=side, cal=cal,
                              pre_skip_mm=pre_skip_mm)


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
    parsed, stock, rendered = await asyncio.to_thread(_render, state, document)
    result = await _send(state, rendered, stock=stock, side=side,
                         copies=1)
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


# The deliberate feed before raster line 0 on the calibration job, and the
# one thing on that label that is not a measurement. It is what makes a
# NEGATIVE start measurable: a printer that lays its first row exactly on the
# die cut and one that was asked for ink 2mm before it both print their first
# row at the die cut, and those two are the difference between "nothing to
# correct" and "this roll needs a pre-skip on every job". Five millimetres
# because the worst late start this add-on has been shown is 4.7mm and the
# reading has to stay positive on a roll that is early by as much again.
CAL_PRE_SKIP_MM = 5.0

# Two copies, because copy 2 is the entire evidence for the hypothesis that
# only the first label of a job is wrong — the reverse feed a tear-off owes
# and does not always make. One copy cannot tell that from a roll that starts
# late on every label, and they want opposite answers.
CAL_COPIES = 2

# The calibration ladders, in millimetres.
#
# **The first version of this label put the copy number and an across ruler in
# the first 14mm of the sheet and started the feed numbers at 15.** That is
# precisely the band the top reading is taken in — the roll this was built for
# lands its first row 9.7mm down — so the first number a person could read was
# 15, and a 4.7mm dead zone would have been typed in as 10. The across ruler's
# own "0 5 10" sat exactly where they would look for it and reads as a feed
# number. An instrument that is unreadable in the one place it is read is
# worse than no instrument, because a wrong reading is stored and printed
# against for ever.
#
# So the layout is now one rule: **the feed ladder owns the sheet**, from row
# 0 to the end, numbered every 5mm including 0, and everything else lives in
# the gaps BETWEEN those numbers — below the band where the reading happens.
CAL_TICK_MM = 0.2           # a feed tick
CAL_BAR_MM = 0.5            # the tick AT raster line 0, heavy so it is the datum
CAL_DIGIT_MM = 2.0          # a feed number: the floor for reading one is 2mm
CAL_NUMBER_STEP_MM = 5      # ...and one every 5mm, starting at 0

# The band that is the measurement: rows 0 to here carry the feed ladder and
# nothing else. It is 11.4 because the number for 10 ends at 11.0 and the
# reading being taken there is the whole point of the label — a person holding
# a die cut against this looks at one place, and the only thing that may be in
# it is the scale they are reading.
CAL_CLEAR_MM = 11.4

# How the feed ladder repeats across the head, and why these two numbers are
# what they are. The label may sit anywhere under a 672-dot head and the
# ladder has to be readable on whatever part of it the paper covers — so a
# number column is repeated, and a window as wide as the paper must always
# contain a WHOLE one. An interval of length `period` always contains a
# multiple of `period`, so the guarantee is `period <= width - column`.
#
# Both numbers are pinned by something measured. The column is 4.5 because
# "100" at 2mm is 4.23mm of ink plus the renderer's own inset, and a 4"
# shipping label's ladder counts past a hundred — at 4.0 every one of those
# numbers came back as a note saying it had been clipped, which is the label
# telling you it cannot be read. The period is then 6.5 because the narrowest
# stock in the catalog is the 0.4375" jewellery label at 11.1mm, and
# `period <= 11.1 - column` is what puts a whole column on it wherever it
# sits. A period of 10 with a column wide enough for two digits satisfies
# neither, and the windows it fails are the ones that look fine on the roll
# you tested with.
CAL_COLUMN_MM = 4.5
CAL_COLUMN_PERIOD_MM = 6.5

# The across ruler, which measures a different axis and must never be read as
# the feed ladder. It is drawn INVERTED — white marks on a solid black band —
# so the difference is visible before anything is read, and it is short enough
# to sit whole in the gap between two feed numbers.
CAL_ACROSS_BAND_MM = 2.5
CAL_ACROSS_TICK_MM = 0.7      # the notched bar: white gaps in black
CAL_ACROSS_DIGIT_MM = 1.8     # what is left, and 21 dots is legible
CAL_ACROSS_NOTCH_MM = 0.3     # one millimetre
CAL_ACROSS_NOTCH5_MM = 0.6    # every fifth, so a numbered one stands out

# Where those bands go: the gap under the feed number 10, then the one under
# 25, then every 30mm of sheet after that. Never above `CAL_CLEAR_MM`, and
# never on a sheet with no room for the first one — a roll too short says so
# in the route's notes rather than getting a band squeezed into a reading.
CAL_ACROSS_TOPS = (11.4, 26.4)
CAL_ACROSS_REPEAT_MM = 30.0

# The copy number, in the gap under 15. Small because it is a label rather
# than a measurement — you need to know which of two labels you are holding,
# and 2.4mm of bold digit in a box says that from across a bench.
#
# It repeats on the LADDER's period and sits inside a number column, for two
# reasons found by rendering it any other way. A mark wider than the column
# crosses the tick dashes beside it, which is ink on a ladder somebody is
# counting; and one repeated every 14mm is missing entirely from about a
# quarter of the positions a 14mm wrap can sit at, which is the same
# arithmetic the column period exists to satisfy. Re-using the period means
# there is one number to keep true rather than two.
CAL_COPY_DIGIT_MM = 2.4
CAL_COPY_TOP_MM = 16.4
CAL_COPY_BOX_MM = 0.2


async def h_printer_calibrate(request: web.Request) -> web.Response:
    """Print the two calibration labels.

    Not the ruler. The ruler answers "which of these two measurements is
    which", and it is drawn inside the stock's own margin — so on a roll
    somebody has given a 5mm margin there is nothing within 5mm of the die
    cut to measure anything against. This answers "what does this printer do
    with this roll", and to do that it is drawn to the FULL PRINT HEAD with
    no margin: the across ladder has to be able to say where paper narrower
    than the head is sitting, and every mark a label-wide sheet makes is
    inside the very thing whose position is the question.

    **None of the roll's own calibration is applied to it**, which is the
    opposite of the rule the ruler follows and is the point. A ladder that
    moved with the numbers it measures reads the same thing however wrong
    they are: print it twice and it says the same thing twice. Left alone it
    is an absolute instrument, and printing it again after saving an answer
    is a check rather than a ritual. What IS applied is the one thing that is
    not a correction — `CAL_PRE_SKIP_MM`, so a start before the die cut has
    somewhere to be measured.

    It deliberately prints outside the media, and the control that offers it
    says so before anybody presses it: where there is no thermal paper the
    heat goes into the liner and, past the web, into the platen roller. Three
    things make it acceptable — it is line work rather than fill, so the dots
    fired off the paper are a small fraction of a pass; it is two labels
    rather than a habit; and the firmware treats it as entirely ordinary, the
    manual being explicit that "the printer does not check for inter-label
    gap when printing. It is the responsibility of the host computer to avoid
    overrunning the label area", which is the machine saying this is the
    host's call to make.
    """
    state = panel(request)
    payload = await body(request)
    stock_id = str(payload.get("stock") or state.settings.get("default_stock"))
    side = str(payload.get("side", "") or "")
    variant = str(payload.get("variant", "plain") or "plain")
    if variant not in protocol.JOB_STARTS:
        return bad(
            f"A calibration print is either {' or '.join(protocol.JOB_STARTS)}"
            f" — the second one opens the job with the printer's own reset. "
            f"There is no {variant!r}.")

    try:
        entry = state.stocks.require(stock_id)
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)

    side, notes = state.resolve_side(entry.id, side)
    printer = state.chosen()
    model = printer.model if printer else dymo_printers.UNKNOWN
    # A copy of the roll drawn to the head with no margin, and never saved:
    # the point of the calibration label is to measure the roll a person
    # actually has, not to change it.
    head = stock_store.replace(
        entry, across_in=model.dots / model.dpi, margin_mm=0.0,
        calibration=stock_store.Calibration(), builtin=False)

    sheets = []
    for copy_no in range(1, CAL_COPIES + 1):
        _, _, rendered = await asyncio.to_thread(
            _render, state, _calibration_label(head, copy_no), stock=head)
        sheets.append(rendered)

    if not across_band_tops(head.feed_mm):
        # The across ruler lives in a gap between two feed numbers, and a
        # label shorter than the first of those gaps has none. Said here
        # rather than left to be noticed: the wizard asks for a left and a
        # right reading, and "there is no ruler on my label" is a person
        # stuck at a question with no answer on the paper.
        notes.append(
            f"This label is {head.feed_mm:.0f}mm along the roll, which is "
            f"too short to carry the across ruler as well as the ladder — so "
            f"it has the ladder only, and the left and right readings cannot "
            f"be taken from it. Everything about where the printing starts "
            f"still can.")

    # A zeroed calibration carrying only the variant, so the job that goes
    # out is this printer's own behaviour and nothing else's: the readings
    # have to be of the machine, not of a correction somebody saved an hour
    # ago.
    fresh = stock_store.Calibration(job_start=variant, ending="tear")
    result = await _send_copies(state, sheets, stock=entry, side=side,
                                cal=fresh, pre_skip_mm=CAL_PRE_SKIP_MM)
    state.consume(side, CAL_COPIES)
    state.mirror_state()

    feed_dots, gap_dots, lead_dots = _label_geometry(
        entry, fresh, model, CAL_PRE_SKIP_MM)
    return ok(printed=CAL_COPIES, copies=CAL_COPIES, side=side,
              stock=entry.id, variant=variant,
              pre_skip_mm=CAL_PRE_SKIP_MM,
              # What the printer was told to search within, reported so the
              # derivation reads the number that was actually sent rather
              # than one it works out for itself. It is the distance the
              # printer feeds when it never finds a hole, which is the whole
              # of how a drift becomes a measured pitch.
              esc_l_mm=round(
                  protocol.budget_dots(feed_dots, gap_dots, max(0, lead_dots))
                  / model.dpi * 25.4, 2),
              notes=notes + [n for sheet in sheets for n in sheet.notes],
              **result)


def _calibration_label(stock, copy_no: int) -> dict:
    """One ladder that owns the sheet, and everything else in its gaps.

    `stock` is a head-wide, zero-margin copy, so (0, 0) in this document is
    head dot 0 and the first row the printer lays. Everything on it is a
    scale away from one of those two edges, which is what makes the readings
    unarguable: the ladder and the thing it measures are printed side by
    side, on the same pass, at the same scale.

    **The feed ladder runs from row 0 to the end and is numbered every 5mm
    from 0.** The reading a person takes is where the leading die cut falls
    on it, and on the roll this was built for that is 9.7mm — so a ladder
    whose first number is 15, with the top of the sheet given over to a copy
    number and an across ruler, is an instrument that cannot be read where it
    is read. Each number is centred on its own tick (the first is clamped to
    the sheet, because half of it would be off the top), which is what makes
    the rule "the first number you can see, less one per short tick above it"
    true rather than approximately true.

    The other two marks live in the gaps between those numbers, which is the
    only place anything else may be:

      * The ACROSS ruler measures the other axis entirely — where the label's
        edges sit on a 672-dot head — so it is drawn as white marks on a
        solid black band. A person looking for a feed number cannot mistake
        it, which the first version's ordinary black ticks and digits could
        not promise.
      * The COPY NUMBER, because two labels out of one job seconds apart are
        otherwise told apart by the order somebody picked them up in.

    Both repeat across the head, because paper narrower than the head sits
    somewhere nobody here knows and a mark it does not cover is not there.
    """
    across_mm, feed_mm = stock.drawable_mm
    columns = _frange(0.0, across_mm - CAL_COLUMN_MM, CAL_COLUMN_PERIOD_MM)
    # Where a tick may be drawn: the part of each period the number column
    # does not own. Numbers and ticks never share a stretch of head, so a
    # digit is never drawn over a line it is meant to name — and rows 0 to
    # `CAL_CLEAR_MM` then carry ink in these two places and nowhere else.
    ticks = [(x + CAL_COLUMN_MM + 0.2,
              min(across_mm, x + CAL_COLUMN_PERIOD_MM)) for x in columns]

    elements: list[dict] = []
    for millimetre in range(0, int(feed_mm) + 1):
        numbered = millimetre % CAL_NUMBER_STEP_MM == 0
        # Row 0 gets the heavy one: it is the datum every feed reading is
        # taken from, and a tick like all the others is a datum somebody
        # counts past.
        weight = CAL_BAR_MM if millimetre == 0 else CAL_TICK_MM
        for first, last in ticks:
            width = (last - first) if numbered else (last - first) / 2
            elements.append({"type": "line", "x_mm": first,
                             "y_mm": millimetre, "w_mm": width,
                             "h_mm": weight,
                             "props": {"stroke_mm": min(width, weight)}})
        if not numbered:
            continue
        top = max(0.0, millimetre - CAL_DIGIT_MM / 2)
        if top + CAL_DIGIT_MM > feed_mm:
            # The tick stays and the digit goes: half a number at the end of
            # the sheet is a number that can be read as another one.
            continue
        for x in columns:
            elements.append(_cal_text(x, top, CAL_COLUMN_MM, CAL_DIGIT_MM,
                                      millimetre, CAL_DIGIT_MM, align="left"))

    for top in across_band_tops(feed_mm):
        elements.extend(_across_band(top, across_mm))

    if CAL_COPY_TOP_MM + CAL_COPY_DIGIT_MM <= feed_mm:
        for x in columns:
            elements.extend(_copy_mark(x, copy_no))

    return {"stock": stock.id, "rotate": 0,
            "name": f"Calibration {copy_no}", "elements": elements}


def across_band_tops(feed_mm: float) -> list[float]:
    """Which gaps between feed numbers carry an across ruler.

    One implementation, because the route has to say when a sheet is too
    short for even the first one — and a label that draws a band the route
    does not know about, or a note about a band the label drew, is two
    answers to where the across reading comes from.
    """
    tops = [top for top in CAL_ACROSS_TOPS
            if top + CAL_ACROSS_BAND_MM <= feed_mm]
    if not tops:
        return []
    nxt = CAL_ACROSS_TOPS[-1] + CAL_ACROSS_REPEAT_MM
    while nxt + CAL_ACROSS_BAND_MM <= feed_mm:
        tops.append(nxt)
        nxt += CAL_ACROSS_REPEAT_MM
    return tops


def _across_band(top: float, across_mm: float) -> list[dict]:
    """A millimetre scale from head dot 0, white on black.

    Inverted because it is the one thing on this label that measures the
    other axis, and the reading it would be confused with — the feed number
    a person takes the top measurement from — is the reading the whole label
    exists for. Black ticks and digits are what the first version had, and
    they sat in the gap where somebody looks for a number.

    Two rows make the band, and neither needs anything the renderer does not
    already do. The ticks are **notches**: a black bar with a white gap at
    every millimetre, which is a white tick drawn out of filled boxes. The
    digits are ordinary inverted text, whose own black grounds abut to make
    the rest of the band — `_draw_text` pastes an inverted plate by its ink,
    so the glyphs leave the paper showing through and come out white.

    Every number owns the 5mm its own tick sits in the middle of, so
    consecutive boxes meet and never overlap; the two at the ends are cut off
    by the sheet, so those digits are pushed against their own tick instead
    of being centred in half a box — a "0" floating a millimetre from the
    head's first dot is a scale reading a millimetre wrong to anybody who
    trusts the digit over the tick.
    """
    out: list[dict] = []
    cut = 0.0
    for millimetre in range(0, int(across_mm) + 1):
        wide = (CAL_ACROSS_NOTCH5_MM if millimetre % 5 == 0
                else CAL_ACROSS_NOTCH_MM)
        start = max(0.0, millimetre - wide / 2)
        if start > cut:
            out.append({"type": "box", "x_mm": cut, "y_mm": top,
                        "w_mm": start - cut, "h_mm": CAL_ACROSS_TICK_MM,
                        "props": {"fill": True, "stroke_mm": 0}})
        cut = max(cut, min(across_mm, millimetre + wide / 2))
    if cut < across_mm:
        out.append({"type": "box", "x_mm": cut, "y_mm": top,
                    "w_mm": across_mm - cut, "h_mm": CAL_ACROSS_TICK_MM,
                    "props": {"fill": True, "stroke_mm": 0}})

    room = 5.0
    digits_top = top + CAL_ACROSS_TICK_MM
    for millimetre in range(0, int(across_mm) + 1, 5):
        left = max(0.0, millimetre - room / 2)
        right = min(across_mm, millimetre + room / 2)
        align = "center"
        if left <= 0.0:
            align = "left"
        elif right >= across_mm:
            align = "right"
        out.append(_cal_text(left, digits_top, max(1.0, right - left),
                             CAL_ACROSS_DIGIT_MM, millimetre,
                             CAL_ACROSS_DIGIT_MM, align=align, invert=True))
    return out


def _copy_mark(x: float, copy_no: int) -> list[dict]:
    """Which of the two labels this is, in a box so it is not a measurement.

    In the gap under the feed number 15, in a number column and never wider
    than one: a box that reaches into the tick stretch beside it is ink drawn
    across a ladder somebody is counting.
    """
    width = CAL_COLUMN_MM
    return [
        {"type": "box", "x_mm": x, "y_mm": CAL_COPY_TOP_MM,
         "w_mm": width, "h_mm": CAL_COPY_DIGIT_MM,
         "props": {"fill": False, "stroke_mm": CAL_COPY_BOX_MM,
                   "radius_mm": 0}},
        _cal_text(x + CAL_COPY_BOX_MM * 2, CAL_COPY_TOP_MM + CAL_COPY_BOX_MM,
                  width - CAL_COPY_BOX_MM * 4,
                  CAL_COPY_DIGIT_MM - CAL_COPY_BOX_MM * 2, copy_no,
                  CAL_COPY_DIGIT_MM - CAL_COPY_BOX_MM * 2),
    ]


def _cal_text(x: float, y: float, width: float, height: float, value,
              size: float, *, align: str = "center",
              invert: bool = False) -> dict:
    """One number on the calibration label, at a stated size.

    `size_mm` is set rather than fitted on purpose: an autofitted digit is
    whatever size its box allows, and two ladders whose numbers came out at
    different sizes are two ladders somebody has to work out the scale of.
    """
    return {"type": "text", "x_mm": x, "y_mm": y, "w_mm": width,
            "h_mm": height,
            "props": {"text": str(value), "font": "sans-bold",
                      "size_mm": size, "align": align, "valign": "top",
                      "wrap": False, "invert": invert}}


def _frange(start: float, stop: float, step: float) -> list[float]:
    """`range` for millimetres, inclusive of anything that fits."""
    out, value = [], start
    while value <= stop + 1e-9:
        out.append(round(value, 3))
        value += step
    return out


async def h_printer_check(request: web.Request) -> web.Response:
    """Print the frame that proves the calibration, through the ordinary path.

    The calibration label is an instrument and is deliberately immune to
    every number it measures; this is the opposite, and it has to be. It goes
    out exactly as a real label does — the same crop, the same pre-skip, the
    same lateral placement — and it draws a one-millimetre frame around the
    whole of what the calibration says is printable. If the answer is right
    the frame reaches all four edges of the label and is complete. If it is
    wrong it is missing a side, and which side says which way.

    That is why there are two prints and not one: a measurement nobody can
    check is a measurement nobody can correct, and the failure being visible
    on the label itself is worth more than any sentence in the panel.
    """
    state = panel(request)
    payload = await body(request)
    stock_id = str(payload.get("stock") or state.settings.get("default_stock"))
    side = str(payload.get("side", "") or "")

    try:
        entry = state.stocks.require(stock_id)
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)

    side, notes = state.resolve_side(entry.id, side)
    # Drawn to the full sheet, because the frame's whole job is to touch the
    # die cut: a margin here would put a millimetre of white where the
    # question is.
    full = stock_store.replace(entry, margin_mm=0.0)
    document = _check_label(full, entry.dead_leading_mm(
        state.at_tear_off(side)))
    _, _, rendered = await asyncio.to_thread(
        _render, state, document, stock=full)
    result = await _send(state, rendered, stock=entry, side=side, copies=1)
    state.consume(side, 1)
    state.mirror_state()
    return ok(printed=1, side=side, stock=entry.id,
              notes=notes + rendered.notes, **result)


CHECK_FRAME_MM = 1.0
CHECK_WORDS = "Should reach every edge"


def _check_label(stock, dead_mm: float) -> dict:
    """A frame around everything this roll can print on, and a line of words.

    The frame starts at the dead band rather than at row 0, because the crop
    on the way to the printer takes those rows off the front of the sheet —
    so a frame drawn from row 0 would have its top edge cut away and the
    check would fail on a calibration that was right. Drawn where the ink can
    land, it comes back whole.
    """
    across_mm, feed_mm = stock.drawable_mm
    top = max(0.0, dead_mm)
    height = max(2.0, feed_mm - top)
    return {"stock": stock.id, "rotate": 0, "name": "Check", "elements": [
        {"type": "box", "x_mm": 0, "y_mm": top,
         "w_mm": across_mm, "h_mm": height,
         "props": {"stroke_mm": CHECK_FRAME_MM, "fill": False,
                   "radius_mm": 0}},
        {"type": "text", "x_mm": CHECK_FRAME_MM * 3,
         "y_mm": top + CHECK_FRAME_MM * 3,
         "w_mm": max(1.0, across_mm - CHECK_FRAME_MM * 6),
         "h_mm": max(1.0, height - CHECK_FRAME_MM * 6),
         "props": {"text": CHECK_WORDS, "font": "sans-bold", "size_mm": 0,
                   "align": "center", "valign": "middle", "wrap": True}},
    ]}


async def h_printer_feed(request: web.Request) -> web.Response:
    """Feed the last label out to where it can be torn off.

    The button `ending: "hold"` needs. A roll whose first label of every job
    is wrong can end its jobs with the short feed instead — which leaves the
    last label inside the printer, "partially inside… and cannot be torn
    off", in the manual's words — and then this is what ends a run. It is the
    one route here that prints nothing and moves paper, so it says so by
    being its own verb rather than a flag on a print.
    """
    state = panel(request)
    payload = await body(request)
    side = str(payload.get("side", "") or loaded.SIDES[0])
    if side not in loaded.SIDES:
        return bad(f"There is no {side!r} roll — a LabelWriter has a left "
                   f"and a right.")
    try:
        result = await asyncio.to_thread(
            usb_link.send, protocol.form_feed(), state.printer_key())
    except (usb_link.UsbUnavailable, usb_link.PrinterNotFound,
            usb_link.PrinterBusy) as exc:
        return bad(str(exc), 503)
    # The paper is at the tear bar now, whatever it was doing before, so the
    # next job's first label is charged the band a missing reverse feed
    # costs — the same bookkeeping a job ending in `ESC E` does.
    state.record_ending(side, "tear")
    return ok(side=side, **result)


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

    # Editing an existing row keeps everything the caller did not name. The
    # Edit dialog shows the measurements, the margin and the count; it does
    # not show the text direction or the roll's own notes, and a Save that
    # blanked them would undo a correction somebody made one control away —
    # the same partial-update rule the registry services follow.
    existing = state.stocks.get(identifier)
    entry = stock_store.Stock(
        id=identifier, name=name, across_in=across, feed_in=feed,
        sku=str(payload.get("sku", existing.sku if existing else "") or ""),
        per_roll=max(0, int(payload.get("per_roll",
                                        existing.per_roll if existing else 0)
                            or 0)),
        margin_mm=max(0.0, float(payload.get(
            "margin_mm",
            existing.margin_mm if existing else stock_store.DEFAULT_MARGIN_MM))),
        notes=str(payload.get("notes", existing.notes if existing else "")
                  or ""),
        turn=existing.turn if existing else None,
        # Same partial-update rule as `turn`: the Edit dialog has no control
        # for the calibration — that is a wizard, because it is two prints
        # and five readings rather than a field — and a Save here that
        # blanked it would undo a measurement made one button away.
        calibration=(existing.calibration if existing
                     else stock_store.Calibration()),
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


def _reading(payload: dict, key: str, *, optional: bool = False):
    """One millimetre off the wire, refused rather than guessed at.

    Every one of these is a distance somebody read off a printed ladder, and
    the derivation branches on differences of less than a millimetre — so a
    field that silently became zero because it arrived as an empty string
    would not be a slightly wrong calibration, it would be a different
    hypothesis. `right` is the one that may legitimately be absent: a label
    wider than the print head runs off it and there is nothing to read.
    """
    raw = payload.get(key, None)
    if raw in (None, ""):
        if optional:
            return None
        raise _refuse(
            f"The calibration needs the {key!r} reading — it is one of the "
            f"five numbers printed on the label, in millimetres.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise _refuse(
            f"{key!r} has to be a number of millimetres — read it off the "
            f"ladder printed on the calibration label.")
    if value != value or abs(value) == float("inf"):
        raise _refuse(f"{key!r} is not a measurement.")
    if abs(value) > MAX_READING_MM:
        raise _refuse(
            f"{value}mm is longer than any label this printer takes, so "
            f"{key!r} is a ladder read on the wrong axis or a decimal point "
            f"in the wrong place.")
    if value < 0:
        # Every one of these is a distance from an edge to something printed
        # on the same label, so none of them can be negative — and a minus
        # sign here is somebody carrying over the old offset's convention,
        # where it meant "the other way". There is no other way now: the
        # derivation decides the sign, from where the two copies landed.
        raise _refuse(
            f"{key!r} is a distance measured from an edge of the label, so "
            f"it cannot be negative. Read it off the ladder printed on the "
            f"calibration label and type what it says.")
    return value


# The longest reading that can be a reading. The 4XL head is 4.16" and the
# longest stock in the catalog is 4"; anything past a foot of paper is not a
# measurement of a label, it is a typo with a unit on it.
MAX_READING_MM = 305.0


async def h_stock_calibration(request: web.Request) -> web.Response:
    """Five readings in; what this roll does, in the roll's own words.

    The panel does no arithmetic on the way in and none on the way out: the
    numbers a person read go straight to `calibration.derive`, which is pure
    and is where all three hypotheses live. That split is the whole reason
    this can be tested with the numbers the owner actually measured — a
    derivation spread across a request handler is one that can only be
    checked by printing.

    Two answers do NOT store anything, and both are the honest kind of
    nothing. The first half of the "only the first label" hypothesis needs a
    second print before it can say which of two firmware behaviours this
    printer has; a set of readings whose arithmetic is impossible is a
    misread ladder. Storing half of either would leave a roll calibrated by a
    guess, which is the thing this replaced.
    """
    state = panel(request)
    try:
        entry = state.stocks.require(request.match_info["stock_id"])
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)

    payload = await body(request)
    readings = payload.get("readings")
    printed = payload.get("printed")
    if not isinstance(readings, dict) or not isinstance(printed, dict):
        return bad(
            "A calibration is the five readings off the label plus what the "
            "calibration print reported it sent — post `readings` and "
            "`printed` together, because a reading means nothing without "
            "the pre-skip it was measured against.")

    variant = str(printed.get("variant", "plain") or "plain")
    if variant not in protocol.JOB_STARTS:
        return bad(f"There is no {variant!r} calibration print.")
    outcome = calibration.derive(
        calibration.Readings(
            left=_reading(readings, "left"),
            top1=_reading(readings, "top1"),
            bottom1=_reading(readings, "bottom1"),
            top2=_reading(readings, "top2"),
            right=_reading(readings, "right", optional=True),
        ),
        calibration.Printed(
            pre_skip_mm=_reading(printed, "pre_skip_mm"),
            esc_l_mm=_reading(printed, "esc_l_mm"),
            variant=variant,
        ),
        entry, now=time.time())

    updated = entry
    if outcome.calibration is not None:
        updated = state.stocks.put(stock_store.replace(
            entry, calibration=outcome.calibration, builtin=False))
        state.mirror_state()
    return ok(outcome.as_dict(), stock=state._stock_row(updated),
              stocks=[state._stock_row(s) for s in state.stocks.all()])


async def h_stock_calibration_clear(request: web.Request) -> web.Response:
    """Forget what was measured and print exactly what shipped.

    Not a reset to a guessed default — to nothing. An uncalibrated roll gets
    byte-for-byte the job this add-on has always sent, which is the promise
    every measurement here is added under and the only thing that makes a
    calibration safe to try.
    """
    state = panel(request)
    try:
        entry = state.stocks.require(request.match_info["stock_id"])
    except stock_store.UnknownStock as exc:
        return bad(exc.detail, 404)
    updated = state.stocks.put(stock_store.replace(
        entry, calibration=stock_store.Calibration(), builtin=False))
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
    # `view: "canvas"` is the designer asking for the label the way it is
    # DRAWN rather than the way it prints: the same sheet turned back by the
    # label's own rotate, so a 90° tube wrap arrives as the long strip the
    # overlay's coordinates describe. Everything else — the Quick tab, the
    # Templates tab, the card — wants the sheet, because that is what comes
    # out of the printer and a preview is for being believed.
    view = str(payload.get("view", "") or "sheet")
    turn = parsed.rotate if view == "canvas" else 0
    png = await asyncio.to_thread(rendered.png, scale, turn=turn)
    return web.Response(
        body=png, content_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Label-View": "canvas" if turn else "sheet",
            "X-Label-Dots": f"{rendered.across_dots}x{rendered.feed_dots}",
            "X-Label-Notes": json.dumps(rendered.notes),
            # The same messages with the element each belongs to, so the
            # designer can outline the box that is wrong instead of printing
            # a sentence under a canvas with six boxes on it. `notes` is
            # unchanged, because five other things read it.
            "X-Label-Problems": json.dumps(rendered.problems),
        })


async def h_print(request: web.Request) -> web.Response:
    state = panel(request)
    payload = await body(request)
    document = payload.get("label") or {}
    copies = max(1, min(500, int(payload.get("copies", 1) or 1)))
    side_wanted = str(payload.get("side", "") or "")

    parsed, entry, rendered = await asyncio.to_thread(_render, state, document)
    side, notes = state.resolve_side(entry.id, side_wanted)
    result = await _send(state, rendered, stock=entry, side=side,
                         copies=copies)

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
    result = await _send(state, rendered, stock=entry, side=side,
                         copies=copies)
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
    result = await _send(state, rendered, stock=entry, side=side,
                         copies=copies)

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
    result = await _send(state, rendered, stock=stock_entry, side=side,
                         copies=copies)

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


# -- fonts ------------------------------------------------------------------
# A day: the sample for a given family and text never changes, and the picker
# asks for one image per font every time it opens.
FONT_SAMPLE_CACHE = "max-age=86400"


async def h_font_sample(request: web.Request) -> web.Response:
    """This font, drawn by the renderer that prints labels.

    A picker whose preview is a CSS font-family shows the browser's idea of
    "Monospace" beside a label that will print in DejaVu Sans Mono — which is
    the exact failure a font preview exists to prevent. So the sample comes
    off `render.image`, and what you pick is what comes out of the printer.
    """
    key = request.match_info["font_key"]
    if key not in fonts.catalog():
        # The key is echoed by NAME only — `_for_log`-clean and quoted by the
        # JSON encoder — because it arrives off the wire and this is a
        # message that goes back over it. The list is what makes the answer
        # useful; the typo is what makes it findable.
        return bad(f"There is no font called {key!r} on this machine. "
                   f"Known: {', '.join(sorted(fonts.catalog()))}.", 404)
    text = str(request.query.get("text", "") or "")[
        :render_image.SAMPLE_MAX_CHARS] or render_image.SAMPLE_TEXT
    png = await asyncio.to_thread(render_image.sample_png, text, key)
    return web.Response(body=png, content_type="image/png",
                        headers={"Cache-Control": FONT_SAMPLE_CACHE})


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
                          client_max_size=MAX_BODY_BYTES)
    app[PANEL_KEY] = state or Panel()

    add = app.router.add_route
    app.router.add_get("/api/health", h_health)
    app.router.add_get("/api/state", h_state)

    app.router.add_get("/api/printers", h_printers)
    app.router.add_post("/api/printer/select", h_printer_select)
    app.router.add_get("/api/printer/status", h_printer_status)
    app.router.add_post("/api/printer/test", h_printer_test)
    app.router.add_post("/api/printer/calibrate", h_printer_calibrate)
    app.router.add_post("/api/printer/check", h_printer_check)
    app.router.add_post("/api/printer/feed", h_printer_feed)
    app.router.add_get("/api/printer/usb", h_printer_usb)

    app.router.add_get("/api/stocks", h_stocks)
    app.router.add_post("/api/stock", h_stock_put)
    app.router.add_post("/api/stock/{stock_id}/swap", h_stock_swap)
    app.router.add_post("/api/stock/{stock_id}/turn", h_stock_turn)
    app.router.add_post("/api/stock/{stock_id}/calibration",
                        h_stock_calibration)
    add("DELETE", "/api/stock/{stock_id}/calibration",
        h_stock_calibration_clear)
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

    app.router.add_get("/api/font/{font_key}/sample.png", h_font_sample)

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
