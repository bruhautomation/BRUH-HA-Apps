"""The panel's websocket commands.

Reads are file reads of the mirrors the add-on keeps in /config/.morph, so
opening Morph never waits on the add-on. Writes go to the add-on through the
request folder (`bridge.send_request`). Only an ADMIN may write: the
dashboard is shared by the whole household, and a Tell reaches brAIn with
its full grant. Anybody signed in may look and press their own lights.

`morph/subscribe` is what makes a change appear without a reload: a watcher
here stats the mirrors every couple of seconds and tells every open panel
which part moved — the dashboard (brAIn edited it), Morph's state (a
suggestion, a setting, the learning loop), or brAIn's own published files
(a new finding to place in its room).
"""
from __future__ import annotations

import importlib
import json
import re
import time
from collections.abc import Callable

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .bridge import send_request
from .const import (
    BRAIN_SHARED,
    DASHBOARD,
    DOMAIN,
    ERRORS,
    MIRROR,
    STATE,
    TELLS,
    USAGE,
    WATCH_SECONDS,
)


WRITE_KINDS = ("save", "save_yaml", "undo_commit", "restore", "history", "tell", "tell_undo",
               "settings", "suggestion", "learn_now", "regenerate", "lessons")
BRAIN_FILES = ("findings_state.json", "situation.json", "status.json")
TELL_ID = re.compile(r"^[a-z0-9-]{4,64}$")
USAGE_KINDS = ("open", "toggle", "slide", "scene", "history", "tell", "undo", "ask", "edit")
MAX_EVENTS = 50
MAX_ERRORS_PER_HOUR = 120


def _read_json(path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _brain_feed() -> dict:
    """What brAIn has published that Morph places on the dashboard: findings
    (as notes in the room they are about), the situation sentence (the
    story's first line), and the queue count."""
    findings = _read_json(BRAIN_SHARED / "findings_state.json")
    situation = _read_json(BRAIN_SHARED / "situation.json")
    status = _read_json(BRAIN_SHARED / "status.json")
    return {
        "installed": BRAIN_SHARED.is_dir(),
        "findings": [f for f in (findings.get("findings") or []) if isinstance(f, dict)][:60],
        "situation": {k: situation.get(k) for k in ("sentence", "mode", "at", "reading", "rooms")
                      if k in situation},
        "status": {k: status.get(k) for k in ("state", "label", "sentence", "queue_count")
                   if k in status},
    }


def _load() -> dict:
    return {"mirror": _read_json(MIRROR), "state": _read_json(STATE), "brain": _brain_feed(),
            "now": time.time()}


@websocket_api.websocket_command({vol.Required("type"): "morph/load"})
@websocket_api.async_response
async def ws_load(hass: HomeAssistant, connection, msg) -> None:
    data = await hass.async_add_executor_job(_load)
    data["admin"] = bool(connection.user and connection.user.is_admin)
    connection.send_result(msg["id"], data)


@websocket_api.websocket_command({vol.Required("type"): "morph/yaml"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_yaml(hass: HomeAssistant, connection, msg) -> None:
    def _read() -> str:
        try:
            return DASHBOARD.read_text(encoding="utf-8")
        except OSError:
            return ""
    connection.send_result(msg["id"], {"text": await hass.async_add_executor_job(_read)})


@websocket_api.websocket_command({
    vol.Required("type"): "morph/request",
    vol.Required("kind"): vol.In(WRITE_KINDS),
    vol.Optional("payload", default={}): dict,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_request(hass: HomeAssistant, connection, msg) -> None:
    out = await send_request(msg["kind"], msg["payload"])
    connection.send_result(msg["id"], out)
    _notify(hass, ("mirror", "state"))


@websocket_api.websocket_command({vol.Required("type"): "morph/tell_status",
                                  vol.Required("tell"): str})
@websocket_api.async_response
async def ws_tell_status(hass: HomeAssistant, connection, msg) -> None:
    tid = msg["tell"]
    if not TELL_ID.match(tid):
        connection.send_error(msg["id"], "invalid", "Not a request id")
        return
    data = await hass.async_add_executor_job(_read_json, TELLS / f"{tid}.json")
    connection.send_result(msg["id"], data or {"phase": "missing"})


def _append(path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _clean_event(e: dict, now: float) -> dict | None:
    if not isinstance(e, dict) or e.get("kind") not in USAGE_KINDS:
        return None
    lt = time.localtime(now)
    row = {"ts": now, "kind": e["kind"], "hour": lt.tm_hour, "weekday": lt.tm_wday}
    for key in ("card", "section", "floor", "entity", "detail"):
        val = e.get(key)
        if isinstance(val, str) and val:
            row[key] = val[:80]
    return row


@websocket_api.websocket_command({vol.Required("type"): "morph/usage",
                                  vol.Required("events"): list})
@websocket_api.async_response
async def ws_usage(hass: HomeAssistant, connection, msg) -> None:
    """How the dashboard is used — the learning loop's evidence. Ids and
    counts only; nothing a person typed is in it."""
    now = time.time()
    rows = [r for r in (_clean_event(e, now) for e in msg["events"][:MAX_EVENTS]) if r]
    if rows:
        await hass.async_add_executor_job(_append, USAGE, rows)
    connection.send_result(msg["id"], {"ok": True, "kept": len(rows)})


@websocket_api.websocket_command({
    vol.Required("type"): "morph/report",
    vol.Required("kind"): vol.In(("card", "layout", "panel", "history")),
    vol.Required("message"): str,
    vol.Optional("detail", default=""): str,
    vol.Optional("card_type", default=""): str,
})
@websocket_api.async_response
async def ws_report(hass: HomeAssistant, connection, msg) -> None:
    """A fault the panel saw in itself — a card that threw, two sections
    overlapping. Rate-limited, because a card that throws on every state
    change would otherwise write a line per state change."""
    data = hass.data.setdefault(DOMAIN, {})
    window = [t for t in data.get("report_times", []) if t > time.time() - 3600]
    if len(window) >= MAX_ERRORS_PER_HOUR:
        connection.send_result(msg["id"], {"ok": False})
        return
    window.append(time.time())
    data["report_times"] = window
    row = {"ts": time.time(), "kind": msg["kind"], "message": msg["message"][:300],
           "detail": msg["detail"][:2000], "card_type": msg["card_type"][:60]}
    await hass.async_add_executor_job(_append, ERRORS, [row])
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({
    vol.Required("type"): "morph/finding",
    vol.Required("ts"): int,
    vol.Required("action"): str,
    vol.Optional("note", default=""): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_finding(hass: HomeAssistant, connection, msg) -> None:
    """Answer one of brAIn's findings from where Morph shows it, through
    brAIn's own request writer — one implementation of what an answer is,
    whichever surface it came from."""
    try:
        requests = importlib.import_module("custom_components.brain.requests")
    except ImportError:
        connection.send_error(msg["id"], "no_brain", "brAIn's integration is not loaded.")
        return
    ok = await hass.async_add_executor_job(
        lambda: requests.write_request(hass, msg["ts"], msg["action"], msg["note"], "morph"))
    connection.send_result(msg["id"], {"ok": bool(ok)})


@websocket_api.websocket_command({vol.Required("type"): "morph/subscribe"})
@callback
def ws_subscribe(hass: HomeAssistant, connection, msg) -> None:
    subs = hass.data.setdefault(DOMAIN, {}).setdefault("subs", {})
    key = (id(connection), msg["id"])
    subs[key] = (connection, msg["id"])

    @callback
    def _unsub() -> None:
        subs.pop(key, None)

    connection.subscriptions[msg["id"]] = _unsub
    connection.send_result(msg["id"])


@callback
def _notify(hass: HomeAssistant, parts) -> None:
    for connection, mid in list(hass.data.get(DOMAIN, {}).get("subs", {}).values()):
        connection.send_message(websocket_api.event_message(mid, {"parts": list(parts)}))


def _mtimes() -> dict:
    out = {}
    for name, path in (("mirror", MIRROR), ("state", STATE)):
        try:
            out[name] = path.stat().st_mtime
        except OSError:
            out[name] = 0
    stamp = 0.0
    for name in BRAIN_FILES:
        try:
            stamp = max(stamp, (BRAIN_SHARED / name).stat().st_mtime)
        except OSError:
            pass  # brAIn not installed: nothing to watch in that file
    out["brain"] = stamp
    return out


def start_watcher(hass: HomeAssistant) -> Callable[[], None]:
    data = hass.data.setdefault(DOMAIN, {})
    data["mtimes"] = {}

    async def _tick(_now=None) -> None:
        if not data.get("subs"):
            return
        now = await hass.async_add_executor_job(_mtimes)
        last = data.get("mtimes") or {}
        moved = [k for k, v in now.items() if last and v != last.get(k)]
        data["mtimes"] = now
        if moved:
            _notify(hass, moved)

    from datetime import timedelta
    return async_track_time_interval(hass, _tick, timedelta(seconds=WATCH_SECONDS))


@callback
def async_register(hass: HomeAssistant) -> None:
    data = hass.data.setdefault(DOMAIN, {})
    if data.get("ws"):
        return
    for handler in (ws_load, ws_yaml, ws_request, ws_tell_status, ws_usage, ws_report,
                    ws_finding, ws_subscribe):
        websocket_api.async_register_command(hass, handler)
    data["ws"] = True
