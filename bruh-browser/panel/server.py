#!/usr/bin/env python3
"""BRUH Browser's panel: the ingress target, brAIn's errand API, Chrome's keeper.

* It is the SIDEBAR: Chrome runs on a virtual screen (Xvfb), x11vnc reads it
  on loopback, and this serves noVNC and bridges its websocket (`vnc_bridge`)
  — with the setup steps and the errand in progress above it.
* It is brAIn's ERRAND API: `POST /api/tasks`, `GET /api/tasks/<id>`,
  `POST /api/tasks/<id>/stop`, `POST /api/tasks/<id>/answer`,
  `GET /api/browsers`, `POST /api/browsers/default`, with the bearer token run.sh writes to
  `/config/.bruh_browser/api_token`. Errands run one at a time
  (`tasks.Errands`) through the runner seam (`runner.run_task`).
* It KEEPS CHROME RUNNING (`browser.Chrome`) and opens the sign-in window.

**Who may ask what.** The port is on the add-ons' network, where every other
add-on can reach it, so nothing here trusts the network: a request from the
Supervisor's ingress proxy (172.30.32.2, which Home Assistant authenticated,
admin-only) or loopback reaches everything; any other peer reaches only the
errand and browser routes, only with the token, and never Continue (a person
handled the login, so a person presses it), never "I've done it" on an
answer, never Buy this or Don't buy (a person with the cart in front of them
presses those), and never says which Chrome is this add-on's own. The screen
and its websocket are ingress-only: the live browser is signed in to the
household's shops.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
import os
import sys
import time
from pathlib import Path

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import browsers as browser_choice  # noqa: E402
import profiles as shopping  # noqa: E402
import runner  # noqa: E402
import setup_state  # noqa: E402
import tasks as errands  # noqa: E402
import vnc_bridge  # noqa: E402
from browser import Chrome  # noqa: E402

log = logging.getLogger("bruh_browser")

PANEL_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
NOVNC_DIR = Path(os.environ.get("BROWSER_NOVNC_DIR", "/usr/share/novnc"))
DATA = Path(os.environ.get("BROWSER_DATA", "/data"))
TOKEN_FILE = Path(os.environ.get("BROWSER_TOKEN_FILE", "/config/.bruh_browser/api_token"))
BIND_HOST = "0.0.0.0"
PORT = int(os.environ.get("BROWSER_PANEL_PORT", "8105"))
TICK_S = 3
# The Supervisor's ingress proxy, and this container itself.
INGRESS_PEERS = frozenset(
    p.strip() for p in os.environ.get(
        "BROWSER_INGRESS_PEERS", "172.30.32.2,127.0.0.1,::1").split(",") if p.strip())
TOKEN_ROUTES = ("/api/tasks", "/api/browsers", "/api/profiles")
# What only a person on the panel's page may press, token or no token.
PANEL_ONLY = ("/continue", "/buy", "/decline", "/api/browsers/own",
              "/api/profiles/remove", "/api/profiles/clear")

# Debian bookworm's aiohttp (3.8) has no web.AppKey; a newer one warns
# about a plain string key. BRUH Bambu Studio's answer, copied.
STATE_KEY = web.AppKey("state", dict) if hasattr(web, "AppKey") else "bruh_browser"


def options() -> dict:
    def num(name, default, kind=int):
        try:
            return kind(os.environ.get(name, default))
        except ValueError:
            return kind(default)
    model = os.environ.get("BROWSER_MODEL", "sonnet")
    return {"model": model if model in ("sonnet", "opus", "haiku") else "sonnet",
            "max_turns": num("BROWSER_MAX_TURNS", "80"),
            "timeout_minutes": num("BROWSER_TIMEOUT_MINUTES", "30"),
            "tolerance_percent": num("BROWSER_TOLERANCE_PERCENT", "0", float)}


def run_config() -> runner.RunConfig:
    opts = options()
    try:
        prompt = (PANEL_DIR / "system_prompt.md").read_text(encoding="utf-8")
    except OSError:
        prompt = ""
    return runner.RunConfig(
        claude_bin=os.environ.get("BROWSER_CLAUDE_BIN", "claude"),
        model=opts["model"], max_turns=opts["max_turns"],
        timeout_s=opts["timeout_minutes"] * 60, system_prompt=prompt,
        hook=str(PANEL_DIR / "purchase_hook.py"),
        run_dir=DATA / "run", cwd=Path(os.environ.get("HOME", "/data/home")) / "errands")


# ---------------------------------------------------------------- token

_TOKEN = {"mtime": None, "value": None}


def expected_token() -> str | None:
    try:
        mtime = TOKEN_FILE.stat().st_mtime
        if _TOKEN["mtime"] != mtime:
            value = TOKEN_FILE.read_text(encoding="utf-8").strip()
            _TOKEN.update(mtime=mtime, value=value if len(value) >= 32 else None)
    except OSError:
        _TOKEN.update(mtime=None, value=None)
    return _TOKEN["value"]


def token_ok(header: str) -> bool:
    want = expected_token()
    if not want or not header.startswith("Bearer "):
        return False
    return hmac.compare_digest(header[7:].strip().encode(), want.encode())


def _err(message: str, status: int = 400) -> web.Response:
    return web.json_response({"error": message}, status=status)


@web.middleware
async def guard(request, handler):
    path = request.path
    if path == "/api/health":
        return await handler(request)
    if request.remote in INGRESS_PEERS:
        return await handler(request)
    header = request.headers.get("Authorization", "")
    if (path.startswith(TOKEN_ROUTES) and not path.endswith(PANEL_ONLY)
            and token_ok(header)):
        return await handler(request)
    if header and not token_ok(header):
        return _err("That is not BRUH Browser's token.", 401)
    if header and path.endswith(PANEL_ONLY):
        return _err("A person presses that on BRUH Browser's page in the sidebar.", 403)
    if header:
        return _err("The token reaches the errand routes only; the rest is the sidebar's.", 403)
    return _err("BRUH Browser answers Home Assistant's sidebar and brAIn only.", 403)


@web.middleware
async def json_errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:  # noqa: BLE001 - one bad route must not take the panel down
        log.exception("Unhandled error on %s", request.path)
        return _err("Something went wrong inside the panel; the add-on log has the details.", 500)


# ---------------------------------------------------------------- routes

def _asset(name: str, content_type: str):
    async def handler(_request):
        return web.FileResponse(PANEL_DIR / name, headers={
            "Content-Type": content_type, "Cache-Control": "no-cache"})
    return handler


async def h_health(_request):
    return web.json_response({"ok": True})


async def h_novnc_package(_request):
    """noVNC's page reads its version from package.json, which Debian's copy
    leaves out: answer it, or every load logs a 404."""
    own = NOVNC_DIR / "package.json"
    if own.is_file():
        return web.FileResponse(own)
    return web.json_response({"name": "@novnc/novnc", "version": ""})


def _errands(request) -> errands.Errands:
    return request.app[STATE_KEY]["errands"]


def _chrome(request) -> Chrome:
    return request.app[STATE_KEY]["chrome"]


def _browsers(request):
    return _errands(request).browsers


def _by_person(request) -> bool:
    return request.remote in INGRESS_PEERS


async def h_state(request):
    errs = _errands(request)
    chrome = _chrome(request)
    steps = await asyncio.to_thread(setup_state.steps, errs.last_test(),
                                    errs.last_blocked())
    picks = errs.browsers.view() if errs.browsers is not None else None
    return web.json_response({
        "browsers": picks,
        "profiles": errs.profiles.view() if errs.profiles is not None else [],
        "version": os.environ.get("ADDON_VERSION", "dev"),
        "chrome": chrome.state(),
        "setup": steps,
        "ready": all(s["status"] == "done" for s in steps),
        "current": errs.current(),
        "history": errs.listing(12),
        "options": options(),
        "approval_window_minutes": errands.APPROVAL_WINDOW_S // 60,
    })


async def _body(request) -> dict:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


async def h_task_create(request):
    body = await _body(request)
    purchase = body.get("purchase") is True
    source = str(body.get("source") or ("panel" if _by_person(request) else "brain"))
    target = None
    picks = _browsers(request)
    wanted = str(body.get("browser") or "").strip()
    if wanted and not purchase and picks is not None:
        if not picks.view()["browsers"]:
            await asyncio.to_thread(picks.refresh)
        target, why = picks.resolve(wanted)
        if target is None:
            return _err(why, 409)
        if body.get("make_default") is True:
            picks.set_default(target)
    task, why = _errands(request).create(
        str(body.get("prompt") or ""), purchase=purchase, source=source,
        approval=body.get("approval"), browser=target)
    if not task:
        return _err(why, 409)
    return web.json_response({"task": task}, status=201)


async def h_task_list(request):
    return web.json_response({"tasks": _errands(request).listing(20)})


async def h_task_current(request):
    return web.json_response({"task": _errands(request).current()})


async def h_task_get(request):
    task = _errands(request).get(request.match_info["id"])
    if not task:
        return _err("There is no such errand.", 404)
    return web.json_response({"task": task})


async def h_task_stop(request):
    task, why = _errands(request).stop(request.match_info["id"])
    if not task:
        return _err(why, 404)
    return web.json_response({"task": task})


async def h_task_continue(request):
    task, why = _errands(request).resume(request.match_info["id"])
    if not task:
        return _err(why, 409)
    return web.json_response({"task": task})


async def h_task_answer(request):
    """The answer to a paused errand's question. Words come from the page or
    from brAIn; "I've done it" (carry_on) only from the page, because only a
    person at the live browser has done it."""
    body = await _body(request)
    carry_on = body.get("carry_on") is True
    if carry_on and not _by_person(request):
        return _err("A person presses that on BRUH Browser's page, after doing it "
                    "in the live browser.", 403)
    task, why = _errands(request).answer(
        request.match_info["id"], str(body.get("answer") or ""), carry_on=carry_on,
        by="panel" if _by_person(request) else "brain")
    if not task:
        return _err(why, 409)
    return web.json_response({"task": task})


async def h_task_buy(request):
    """Buy this, from the page (PANEL_ONLY): the same approval check as
    brAIn's purchase — this add-on's finished cart, under the window, never
    bought or declined, and the total the person was shown."""
    body = await _body(request)
    task, why = _errands(request).create(
        "", purchase=True, source="panel",
        approval={"cart_task": request.match_info["id"], "total": body.get("total")})
    if not task:
        return _err(why, 409)
    return web.json_response({"task": task}, status=201)


async def h_task_decline(request):
    task, why = _errands(request).decline(request.match_info["id"])
    if not task:
        return _err(why, 409)
    return web.json_response({"task": task})


async def h_browsers(request):
    picks = _browsers(request)
    if picks is None:
        return _err("Browser choice is not available.", 503)
    if request.query.get("refresh") == "1":
        if _errands(request).busy():
            return web.json_response({**picks.view(), "busy": True})
        return web.json_response(await asyncio.to_thread(picks.refresh))
    return web.json_response(await asyncio.to_thread(
        picks.view if _errands(request).busy() else picks.fresh))


async def h_browsers_default(request):
    picks = _browsers(request)
    if picks is None:
        return _err("Browser choice is not available.", 503)
    body = await _body(request)
    view, why = picks.set_default(str(body.get("browser") or ""))
    return _err(why, 409) if why else web.json_response(view)


async def h_browsers_own(request):
    picks = _browsers(request)
    if picks is None:
        return _err("Browser choice is not available.", 503)
    body = await _body(request)
    view, why = picks.set_own(str(body.get("browser") or ""))
    return _err(why, 409) if why else web.json_response(view)


async def h_profiles(request):
    store = _errands(request).profiles
    return web.json_response({"profiles": store.view() if store is not None else []})


async def h_profile_remove(request):
    store = _errands(request).profiles
    body = await _body(request)
    if store is None:
        return _err("Shopping profiles are not available.", 503)
    row, why = store.remove(str(body.get("store") or ""), str(body.get("kind") or ""),
                            str(body.get("key") or ""))
    return _err(why, 409) if why else web.json_response({"profile": row})


async def h_profile_clear(request):
    store = _errands(request).profiles
    body = await _body(request)
    if store is None:
        return _err("Shopping profiles are not available.", 503)
    done, why = store.clear(str(body.get("store") or ""))
    return web.json_response({"ok": True}) if done else _err(why, 409)


async def h_setup_open(request):
    body = await _body(request)
    why = _chrome(request).open_page(str(body.get("page") or ""))
    return _err(why, 409) if why else web.json_response({"ok": True})


async def h_setup_terminal(request):
    why = _chrome(request).open_terminal()
    return _err(why, 409) if why else web.json_response({"ok": True})


async def h_setup_test(request):
    task, why = _errands(request).create("", kind="test", source="panel")
    if not task:
        return _err(why, 409)
    return web.json_response({"task": task}, status=201)


def _for_log(text, limit: int = 200) -> str:
    return "".join(c if c.isprintable() and c.isascii() else "?" for c in str(text))[:limit]


class QuietAccessLogger(AbstractAccessLogger):
    """Successful polls are not news; failures always log."""

    QUIET = ("/api/state", "/api/health", "/api/tasks", "/websockify", "/novnc/")

    def log(self, request, response, time_taken):  # noqa: D102
        status = getattr(response, "status", 0)
        path = getattr(request, "path", "")
        method = _for_log(getattr(request, "method", "?"), 8)
        if status < 400 and any(path.startswith(p) for p in self.QUIET):
            self.logger.debug("%s %s %s", method, _for_log(path), status)
            return
        level = logging.WARNING if status >= 400 else logging.INFO
        self.logger.log(level, "%s %s %s (%.0fms)", method, _for_log(path),
                        status, time_taken * 1000)


async def _ticker(app):
    chrome = app[STATE_KEY]["chrome"]

    async def loop():
        while True:
            try:
                await asyncio.to_thread(chrome.tick)
            except Exception:  # noqa: BLE001 - the timer must outlive one bad tick
                log.exception("Chrome tick failed")
            await asyncio.sleep(TICK_S)

    task = asyncio.create_task(loop())
    yield
    task.cancel()


def make_errands(chrome: Chrome, store: Path | None = None, run=None) -> errands.Errands:
    def before_run():
        if chrome.close_terminal():
            log.info("Closed the sign-in window before an errand")
        for _ in range(20):
            if chrome.running():
                return None
            time.sleep(1)
        tail = " ".join(chrome.state().get("log_tail") or [])[-300:]
        return ("Chrome is not running, so the errand could not start."
                + (f" Its last words: {tail}" if tail else ""))

    def default_run(task, progress, stop):
        return runner.run_task(task, run_config(), progress, stop)

    def claude_env():
        return {k: v for k, v in os.environ.items() if k not in runner.STRIPPED_ENV}

    picks = browser_choice.Browsers(
        DATA / "browsers.json", os.environ.get("BROWSER_CLAUDE_BIN", "claude"), claude_env)
    return errands.Errands(store or DATA / "tasks.json", run or default_run,
                           options, before_run=before_run, browsers=picks,
                           profiles=shopping.Profiles(
                               (store.parent if store else DATA) / "profiles.json"))


def build_app(chrome: Chrome | None = None, errs: errands.Errands | None = None, *,
              ticker: bool = True) -> web.Application:
    app = web.Application(middlewares=[guard, json_errors], client_max_size=1 << 20)
    chrome = chrome or Chrome()
    app[STATE_KEY] = {"chrome": chrome, "errands": errs or make_errands(chrome)}
    r = app.router
    r.add_get("/", _asset("index.html", "text/html"))
    r.add_get("/app.js", _asset("app.js", "application/javascript"))
    r.add_get("/style.css", _asset("style.css", "text/css"))
    r.add_get("/favicon.svg", _asset("favicon.svg", "image/svg+xml"))
    r.add_get("/websockify", vnc_bridge.handle)
    r.add_get("/novnc/package.json", h_novnc_package)
    if NOVNC_DIR.is_dir():
        r.add_static("/novnc/", NOVNC_DIR)
    r.add_get("/api/health", h_health)
    r.add_get("/api/state", h_state)
    r.add_post("/api/setup/open", h_setup_open)
    r.add_post("/api/setup/terminal", h_setup_terminal)
    r.add_post("/api/setup/test", h_setup_test)
    r.add_get("/api/tasks", h_task_list)
    r.add_post("/api/tasks", h_task_create)
    r.add_get("/api/tasks/current", h_task_current)
    r.add_get("/api/tasks/{id}", h_task_get)
    r.add_post("/api/tasks/{id}/stop", h_task_stop)
    r.add_post("/api/tasks/{id}/continue", h_task_continue)
    r.add_post("/api/tasks/{id}/answer", h_task_answer)
    r.add_post("/api/tasks/{id}/buy", h_task_buy)
    r.add_post("/api/tasks/{id}/decline", h_task_decline)
    r.add_get("/api/browsers", h_browsers)
    r.add_post("/api/browsers/default", h_browsers_default)
    r.add_post("/api/browsers/own", h_browsers_own)
    r.add_get("/api/profiles", h_profiles)
    r.add_post("/api/profiles/remove", h_profile_remove)
    r.add_post("/api/profiles/clear", h_profile_clear)
    if ticker:
        app.cleanup_ctx.append(_ticker)
    return app


def main() -> None:
    level = os.environ.get("BROWSER_LOG_LEVEL", "info").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="[panel %(asctime)s] %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    chrome = Chrome()
    errs = make_errands(chrome)
    errs.start()
    log.info("Starting the BRUH Browser panel on %s:%s (model %s)", BIND_HOST, PORT,
             options()["model"])
    web.run_app(build_app(chrome, errs), host=BIND_HOST, port=PORT,
                access_log_class=QuietAccessLogger,
                access_log=logging.getLogger("bruh_browser.access"),
                print=lambda *_a: log.info("Panel listening on %s:%s", BIND_HOST, PORT))


if __name__ == "__main__":
    main()
