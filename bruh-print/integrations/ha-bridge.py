#!/usr/bin/env python3
"""Watches /config/.bruh_print/requests/ for JSON request files written by the
companion HA integration, forwards them to the panel, and writes a response
file back to /config/.bruh_print/responses/<id>.json.

Everything is forwarded rather than handled. The panel owns the printer — the
one-job-at-a-time lock, the roll bookkeeping, the history — and a second
process that could also open the USB endpoint would be a second answer to
"what is printing", which on a shared bulk endpoint is one label with another
label's raster in the middle of it.

The panel's own sentence is what comes back. A refusal here is usually the
useful kind ("the left roll holds Cryogenic Labels and this label is for
Chemical-Resistant Cryo Labels"), and reporting it as `panel answered HTTP
409` — which is what dropping the body does — turns a fixable mistake into a
mystery in an automation trace.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SHARED = Path(os.environ.get("BRUH_PRINT_SHARED", "/config/.bruh_print"))
REQ_DIR = SHARED / "requests"
RES_DIR = SHARED / "responses"

PANEL_URL = f"http://127.0.0.1:{os.environ.get('BRUH_PRINT_PANEL_PORT', '8097')}"

POLL_INTERVAL = 0.4

# Request kind -> (method, path builder). A kind not in here is refused by
# name rather than forwarded blindly: an unknown path would come back as the
# panel's 404 page, which says nothing about which service was miscalled.
ROUTES: dict[str, Any] = {
    "print_text": lambda p: ("POST", "/api/quick"),
    "print_template": lambda p: (
        "POST", f"/api/template/{_seg(p.get('template', ''))}/print"),
    "print_label": lambda p: ("POST", "/api/print"),
    "reprint": lambda p: (
        "POST", f"/api/history/{_seg(p.get('entry', ''))}/reprint"),
    "set_roll": lambda p: ("POST", f"/api/roll/{_seg(p.get('side', 'left'))}"),
    # Kept under its old name and pointed at the check label, which is
    # what "print one and look at it" now means: the ruler it used to
    # print was millimetre ticks inside the stock's own margin, and
    # both questions it answered — which measurement is which, and is
    # the printing where it should be — are answered by lining the roll
    # up and printing the frame. Renaming the service would turn an
    # automation written last week into a validation error, which is a
    # worse failure than a service whose name is one release behind
    # what it prints.
    "print_test": lambda p: ("POST", "/api/printer/check"),
    # The one read: what is loaded, what can be printed on it, and which
    # templates exist — so a voice request ("print a freezer label that
    # says chili") can name a stock and a template that are really there
    # instead of guessing and meeting the stock refusal.
    "get_status": lambda p: ("GET", "/api/state"),
}

# A print job can take a while — a run of 200 labels is 200 form feeds and
# the printer takes them at its own pace — so the forward waits longer than
# an ordinary API call would. The integration's own timeout is longer again,
# because a timeout here still leaves the labels coming out.
TIMEOUT = 120


def _seg(value: object) -> str:
    """One path segment, quoted. A template name goes in a URL and template
    names are typed by people: a slash in one would otherwise reach a
    different route entirely."""
    return urllib.parse.quote(str(value or ""), safe="")


def _log(message: str) -> None:
    print(f"[ha-bridge {time.strftime('%H:%M:%S')}] {message}", flush=True)


def _write_response(request_id: str, payload: dict) -> None:
    # The scratch name embeds the response's own id — unique per request, so
    # two writers can never pick the same scratch file and lose one's bytes
    # into a name the other has already renamed away.
    tmp = RES_DIR / f".{request_id}.tmp"
    tmp.write_text(json.dumps(payload))
    tmp.replace(RES_DIR / f"{request_id}.json")


def summarise_state(state: dict) -> dict:
    """The panel's state trimmed to what a caller deciding what to print needs.

    The full payload carries the font catalog, the element catalog and
    thirty history rows; handed to a model or an automation that is a page
    of JSON to read past for three facts.
    """
    printer = state.get("printer") or {}
    stocks = state.get("stocks") or []
    return {
        "ok": True,
        "printer": printer.get("name") or printer.get("model") or "",
        "printer_error": state.get("printer_error") or "",
        "rolls": [{"side": r.get("side"), "stock": r.get("stock"),
                   "remaining": r.get("remaining")}
                  for r in state.get("rolls") or [] if isinstance(r, dict)],
        "loaded_stocks": [{"id": s.get("id"), "name": s.get("name"),
                           "side": s.get("loaded_side")}
                          for s in stocks if isinstance(s, dict) and s.get("loaded")],
        "templates": [{"name": t.get("name"),
                       "fields": [f.get("key") for f in t.get("fields") or []
                                  if isinstance(f, dict)],
                       "stock": t.get("stock")}
                      for t in state.get("templates") or [] if isinstance(t, dict)],
        "recent": [{"id": h.get("id"), "title": h.get("title") or "",
                    "stock": h.get("stock"), "at": h.get("at")}
                   for h in (state.get("history") or [])[:5] if isinstance(h, dict)],
    }


def _forward(method: str, path: str, payload: dict) -> dict:
    body = json.dumps(payload).encode() if method != "GET" else None
    request = urllib.request.Request(
        f"{PANEL_URL}{path}", data=body, method=method,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = str(json.loads(exc.read().decode() or "{}").get("error", ""))
        except (ValueError, OSError, UnicodeDecodeError):
            detail = ""
        if detail:
            return {"ok": False, "error": detail}
        if exc.code == 404:
            return {"ok": False,
                    "error": f"BRUH Print's panel has no {path} route — is "
                             f"the add-on up to date?"}
        return {"ok": False,
                "error": f"The panel answered HTTP {exc.code} with no reason "
                         f"in it."}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "error": f"The panel is not answering: {exc}"}


async def handle(request: dict) -> dict:
    kind = str(request.get("kind", ""))
    payload = request.get("payload") or {}
    route = ROUTES.get(kind)
    if route is None:
        return {"ok": False,
                "error": f"BRUH Print does not know how to do {kind!r}. "
                         f"Known: {', '.join(sorted(ROUTES))}."}
    method, path = route(payload)
    if kind == "get_status":
        answer = await asyncio.to_thread(_forward, method, path, {})
        return answer if answer.get("ok") is False else summarise_state(answer)
    # Every service call is a print somebody asked for out loud, so it is
    # tagged as such: the history's `source` column is how you tell a label
    # you printed from one an automation printed at 3am.
    payload = {**payload, "source": f"ha:{kind}"}
    return await asyncio.to_thread(_forward, method, path, payload)


async def request_loop() -> None:
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    RES_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            for path in sorted(REQ_DIR.glob("*.json")):
                try:
                    request = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    path.unlink(missing_ok=True)
                    continue
                # Unlinked before the work, not after: a request that makes
                # the bridge fall over must not be retried forever on every
                # poll, printing a label each time it nearly works.
                path.unlink(missing_ok=True)
                request_id = str(request.get("id", ""))
                if not request_id:
                    continue
                response = await handle(request)
                _write_response(request_id, response)
                _log(f"{request.get('kind')} -> ok={response.get('ok')}")
        except OSError as exc:
            _log(f"request loop error: {exc}")
        await asyncio.sleep(POLL_INTERVAL)


async def main() -> None:
    _log(f"BRUH Print HA bridge starting, panel at {PANEL_URL}")
    await request_loop()


if __name__ == "__main__":
    asyncio.run(main())
