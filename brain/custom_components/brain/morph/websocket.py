"""The panel's websocket commands.

Reads are file reads of the mirrors the add-on keeps in /config/.morph, so
opening Morph never waits on the add-on. Writes go to the add-on through the
request folder (`bridge.send_request`). Only an ADMIN may write: the
dashboard is shared by the whole household, and a Tell reaches brAIn with
its full grant. Anybody signed in may look and press their own lights.

`morph/subscribe` is what makes a change appear without a reload: a watcher
here stats the mirrors every couple of seconds and tells every open panel
which part moved — the dashboard (brAIn edited it), Morph's state (a
setting, the learning loop), or brAIn's own published files (a case to
place in its room, a new hour of measurements).

brAIn is Morph's mind (docs/design/morph-vision.md §13), and since brAIn
4.0 these commands are brAIn's own integration's: its one list of cases
(`/config/.brain/morph/cases.json`) and its measurements (`feed.json`) are
read here; an answer to a case and a To Do press are REQUESTS dropped into
brAIn's own queue through brAIn's own writer (`..requests.write_morph_request`),
the same queue a phone's button and the To-do app use; and the Ask line hands
its words to brAIn's interpreter by a file in `/config/.brain/morph/asks/`,
answered in `answers/`. `brain/shell` is the shell's: where brAIn's own page
is, and brAIn's switches.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import time
import uuid
from collections.abc import Callable

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from . import words
from .bridge import send_request
from .const import (
    BRAIN_SHARED,
    DASHBOARD,
    DOMAIN,
    ERRORS,
    FEATURES,
    INGRESS,
    MIRROR,
    SHOTS,
    STATE,
    TELLS,
    USAGE,
    VERSION,
    WATCH_SECONDS,
)


WRITE_KINDS = ("save", "save_yaml", "undo_commit", "restore", "history", "tell", "tell_undo",
               "tell_answer", "tell_issue", "settings", "suggestion", "learn_now", "regenerate", "lessons",
               "code_reset", "code_redo", "code_merge_all", "report", "report_withdraw",
               "converse", "habit", "lesson_add")
BRAIN_FILES = ("findings_state.json", "situation.json", "status.json", "morph/cases.json", "morph/feed.json",
               "features.json")
BRAIN_MORPH = BRAIN_SHARED / "morph"
CASE_ID = re.compile(r"^[a-z]{1,3}:[A-Za-z0-9_.:-]{1,64}$")
CASE_ACTIONS = ("reply", "dismiss", "todo", "snooze", "fix", "apply", "undo", "not_applicable")
TODO_ACTIONS = ("done", "drop", "snooze")
ASK_WAIT_S = 40
TELL_ID = re.compile(r"^[a-z0-9-]{4,64}$")
USAGE_KINDS = ("open", "toggle", "slide", "scene", "history", "tell", "undo", "ask", "edit")
MAX_EVENTS = 50
# Home Assistant's websocket takes frames up to 4 MB (aiohttp's default),
# and base64 is a third larger than the bytes, so the panel scales a
# picture down until it fits under this rather than having the frame cut.
MAX_SHOT_BYTES = 2_900_000
MAX_SHOTS = 80
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_ERRORS_PER_HOUR = 120
# brAIn's personality (/config/.brain/personality.json, written by brAIn's
# Settings). Morph only reads it, with brAIn's own caps: what is here was
# meant for every chat turn, so nothing longer is shown either.
PERSONA_FILE = "personality.json"
PERSONA_READ_MAX = 256 * 1024
PERSONA_NAME_MAX = 60
PERSONA_MAX = 32000
PERSONA_GROWTH_TEXT_MAX = 500
PERSONA_GROWTH_MAX = 200
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _read_json(path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _mtime(path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _brain_feed() -> dict:
    """What brAIn has published that Morph draws: its cases (each in the
    room it is about), its To Do list, its measurements for the salience
    list (`feed`, aged by the file's mtime, never by a stamp inside it), the
    situation sentence, and the queue count."""
    findings = _read_json(BRAIN_SHARED / "findings_state.json")
    situation = _read_json(BRAIN_SHARED / "situation.json")
    status = _read_json(BRAIN_SHARED / "status.json")
    cases = _read_json(BRAIN_MORPH / "cases.json")
    feed = _read_json(BRAIN_MORPH / "feed.json")
    return {
        "installed": BRAIN_SHARED.is_dir(),
        "findings": [f for f in (findings.get("findings") or []) if isinstance(f, dict)][:60],
        "cases": [c for c in (cases.get("cases") or []) if isinstance(c, dict)][:120],
        "todo": [t for t in (cases.get("todo") or []) if isinstance(t, dict)][:100],
        "open": cases.get("open"),
        # brAIn's last word on a case a reply just ended (the row went with
        # its thread), and a turn's `tell`: a page change brAIn cannot make.
        "said": [x for x in (cases.get("said") or []) if isinstance(x, dict)][:20],
        "cases_at": cases.get("at"),
        "feed": feed if feed.get("v") else None,
        "feed_mtime": _mtime(BRAIN_MORPH / "feed.json"),
        "situation": {k: situation.get(k) for k in ("sentence", "mode", "at", "reading", "rooms")
                      if k in situation},
        "status": {k: status.get(k) for k in ("state", "label", "sentence", "queue_count")
                   if k in status},
    }


def _clip_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2:]:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip() + "…"


def _personality() -> dict:
    """brAIn's personality as brAIn stored it, or None: an absent, unreadable,
    oversized or empty file is no personality, never an error."""
    path = BRAIN_SHARED / PERSONA_FILE
    out = {"brain": BRAIN_SHARED.is_dir(), "personality": None}
    # Personality switched off in ⚙ › Features: the stored one is kept, and
    # nothing reads it.
    if _read_json(FEATURES).get("personality") is False:
        return out
    try:
        with open(path, "rb") as f:
            raw = f.read(PERSONA_READ_MAX + 1)
        data = json.loads(raw.decode("utf-8")) if len(raw) <= PERSONA_READ_MAX else None
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):
        return out
    name = _clip_words(" ".join(str(data.get("name") or "").split()), PERSONA_NAME_MAX)
    persona = _clip_words(str(data.get("persona") or "").replace("\r\n", "\n").strip(), PERSONA_MAX)
    growth = []
    for row in data.get("growth") if isinstance(data.get("growth"), list) else []:
        row = {"text": row} if isinstance(row, str) else row
        if not isinstance(row, dict):
            continue
        text = _clip_words(str(row.get("text") or "").strip(), PERSONA_GROWTH_TEXT_MAX)
        if not text:
            continue
        day = str(row.get("date") or "")[:10]
        entry = {"date": day if _DAY.match(day) else "", "text": text}
        at = row.get("at")
        if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0:
            entry["at"] = int(at / 1000 if at > 1e12 else at)
        growth.append(entry)
    growth.sort(key=lambda e: (e["date"], e.get("at") or 0))
    growth = growth[-PERSONA_GROWTH_MAX:]
    if not (name or persona or growth):
        return out
    p = {"name": name, "persona": persona, "growth": growth}
    stamp = data.get("updated_at")
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and stamp > 0:
        p["updated_at"] = int(stamp)
    out["personality"] = p
    return out


def _load() -> dict:
    # ``code`` is the stamp of the panel code Home Assistant would serve now
    # and ``integration`` the Morph it is running: the page compares both
    # with what it loaded, which is how it knows a reload would change what
    # is on screen. ``restart`` is whether Home Assistant owes a restart.
    return {"mirror": _read_json(MIRROR), "state": _read_json(STATE), "brain": _brain_feed(),
            "now": time.time(), "code": _code_stamp(), "integration": VERSION,
            "restart": restart_owed(), "features": _features()}


def restart_owed(shared=BRAIN_SHARED) -> bool:
    """Whether Home Assistant must restart to load brAIn's update: the one
    answer the panel's verdict and Repairs give, read off the same two files
    (run.sh's marker, written only when the deployed code differs from the
    loaded code, and the record the integration wrote as it loaded). The
    add-on's version being newer than this integration's is not it: an
    update that changed no integration code moves the version and owes no
    restart."""
    try:
        with open(shared / "restart_required", encoding="utf-8") as f:
            marker = json.load(f)
    except (OSError, ValueError):
        return False  # no marker (or one that cannot be read): the panel's rule
    if not isinstance(marker, dict):
        return False
    loaded = _read_json(shared / "integration_loaded.json")
    wanted, have = str(marker.get("fingerprint") or ""), str(loaded.get("fingerprint") or "")
    if wanted and have:
        return wanted != have
    required, running = str(marker.get("required_version") or ""), str(loaded.get("version") or "")
    return not required or not running or required != running


def _features() -> dict:
    from .switches import read_features
    return read_features(FEATURES)


def _ingress() -> dict:
    """brAIn's own page, as its panel read it off the Supervisor. Only a
    path under /api/hassio_ingress/ is handed on: the shell opens it in a
    frame, and a frame of anything else is not brAIn's page."""
    data = _read_json(INGRESS)
    url = str(data.get("ingress_url") or "")
    if not re.match(r"^/api/hassio_ingress/[A-Za-z0-9_-]{8,128}/$", url):
        url = ""
    slug = str(data.get("slug") or "")
    return {"ingress_url": url, "slug": slug if re.match(r"^[a-z0-9_]{1,64}$", slug) else ""}


def _code_stamp() -> str | None:
    """None when it cannot be read, which offers no reload rather than a
    wrong one."""
    try:
        from . import static
        return static.stamp()
    except Exception:  # noqa: BLE001 — a missing stamp must never fail the load
        return None


@websocket_api.websocket_command({vol.Required("type"): "morph/load"})
@websocket_api.async_response
async def ws_load(hass: HomeAssistant, connection, msg) -> None:
    data = await hass.async_add_executor_job(_load)
    data["admin"] = bool(connection.user and connection.user.is_admin)
    connection.send_result(msg["id"], data)


@websocket_api.websocket_command({vol.Required("type"): "brain/shell"})
@websocket_api.async_response
async def ws_shell(hass: HomeAssistant, connection, msg) -> None:
    """What the shell needs to draw itself: brAIn's switches, whether this
    person may open brAIn's own page (administrators: it is the add-on's
    ingress), and where that page is."""
    admin = bool(connection.user and connection.user.is_admin)
    out = {"admin": admin, "features": await hass.async_add_executor_job(_features)}
    if admin:
        out.update(await hass.async_add_executor_job(_ingress))
    connection.send_result(msg["id"], out)


@websocket_api.websocket_command({vol.Required("type"): "morph/personality"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_personality(hass: HomeAssistant, connection, msg) -> None:
    """brAIn's personality, for the name Morph's words use; Morph keeps none of its own
    and edits nothing here: it is changed in brAIn's ⚙ › Personality."""
    connection.send_result(msg["id"], await hass.async_add_executor_job(_personality))


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


# brAIn's ``claude`` user, who reads the picture (the same uid Morph's
# service hands /config/morph to). Owner-only modes, owned by that user:
# Core writes as root and root can read and prune anything anyway.
BRAIN_UID = 1000


def _hand_to_brain(path, mode: int) -> None:
    os.chmod(path, mode)
    try:
        os.chown(path, BRAIN_UID, BRAIN_UID)
    except OSError:
        pass  # not root (a dev checkout): brAIn cannot open it and works from the card's text, which rides with every Tell


def _write_shot(raw: bytes) -> str:
    """File one PNG under /config/.morph/shots and keep the folder bounded."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    _hand_to_brain(SHOTS, 0o700)
    shot = uuid.uuid4().hex
    scratch = SHOTS / f".{shot}.tmp"
    with open(scratch, "wb") as f:
        f.write(raw)
    _hand_to_brain(scratch, 0o600)
    os.replace(scratch, SHOTS / f"{shot}.png")
    old = sorted(SHOTS.glob("*.png"), key=lambda p: p.stat().st_mtime)
    for path in old[:-MAX_SHOTS]:
        path.unlink(missing_ok=True)
    return shot


@websocket_api.websocket_command({
    vol.Required("type"): "morph/shot",
    vol.Required("png"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_shot(hass: HomeAssistant, connection, msg) -> None:
    """A picture of what somebody held, taken by the panel the moment they
    held it, so brAIn sees what they see before it reads any YAML. Admin
    only, like the Tell it belongs to; a PNG and nothing else."""
    data = msg["png"]
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    if len(data) > MAX_SHOT_BYTES * 4 // 3 + 8:
        connection.send_error(msg["id"], "too_large", "That picture is too large.")
        return
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        connection.send_error(msg["id"], "invalid", "Not a picture.")
        return
    if not raw.startswith(PNG_MAGIC):
        connection.send_error(msg["id"], "invalid", "Not a PNG.")
        return
    try:
        shot = await hass.async_add_executor_job(_write_shot, raw)
    except OSError as exc:
        connection.send_error(msg["id"], "write_failed", f"Could not file the picture: {exc}")
        return
    connection.send_result(msg["id"], {"shot": shot, "bytes": len(raw)})


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
    vol.Required("kind"): vol.In(("card", "layout", "panel", "history", "loaded")),
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
    requests = _brain_requests()
    ok = await hass.async_add_executor_job(
        lambda: requests.write_request(hass, msg["ts"], msg["action"], msg["note"], "morph"))
    connection.send_result(msg["id"], {"ok": bool(ok)})


def _brain_requests():
    """brAIn's own request writer: the same integration, so it is always
    there (imported late, because requests.py is brAIn's and imports
    nothing of Morph's)."""
    from .. import requests
    return requests


@websocket_api.websocket_command({
    vol.Required("type"): "morph/case",
    vol.Required("case"): str,
    vol.Required("action"): vol.In(CASE_ACTIONS),
    vol.Optional("text", default=""): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_case(hass: HomeAssistant, connection, msg) -> None:
    """Answer one of brAIn's cases from where Morph draws it (§14). A reply
    is free words, read by brAIn's interpreter on the `morph` surface; the
    rest are the presses every surface has. One implementation of what an
    answer is: brAIn's queue, through brAIn's own writer."""
    if not CASE_ID.match(msg["case"]):
        connection.send_error(msg["id"], "invalid", "Not a case id")
        return
    req = _brain_requests()
    text = msg["text"].strip()
    refusal = words.reply_refusal(text)
    if refusal:
        connection.send_result(msg["id"], {"ok": False, "error": refusal})
        return
    if msg["action"] == "reply" and not text:
        connection.send_result(msg["id"], {"ok": False, "error": "Say something first."})
        return
    body = {"kind": "morph", "case": msg["case"], "action": msg["action"], "text": text, "via": "morph"}
    ok = await hass.async_add_executor_job(lambda: req.write_morph_request(hass, body))
    connection.send_result(msg["id"], {"ok": bool(ok), **({} if ok else {"error": "brAIn did not take that."})})


@websocket_api.websocket_command({
    vol.Required("type"): "morph/todo",
    vol.Required("action"): vol.In(TODO_ACTIONS),
    vol.Required("id"): int,
    vol.Optional("days", default=7): int,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_todo(hass: HomeAssistant, connection, msg) -> None:
    """A To Do press: tick it off, delete it, or snooze it — brAIn's list,
    the same one Home Assistant's To-do app shows."""
    req = _brain_requests()
    body = {"kind": "todo", "action": msg["action"], "id": int(msg["id"]), "via": "morph"}
    if msg["action"] == "snooze":
        body["days"] = max(1, min(60, int(msg["days"])))
    ok = await hass.async_add_executor_job(lambda: req.write_morph_request(hass, body))
    connection.send_result(msg["id"], {"ok": bool(ok), **({} if ok else {"error": "brAIn did not take that."})})


def _write_ask(ask_id: str, text: str, user_id: str) -> bool:
    asks = BRAIN_MORPH / "asks"
    if not BRAIN_MORPH.is_dir():
        return False
    asks.mkdir(parents=True, exist_ok=True)
    scratch = asks / f".{ask_id}.tmp"
    scratch.write_text(json.dumps({"id": ask_id, "text": text, "ts": time.time(), "user_id": user_id}), encoding="utf-8")
    os.replace(scratch, asks / f"{ask_id}.json")
    return True


def _take_answer(ask_id: str) -> dict | None:
    path = BRAIN_MORPH / "answers" / f"{ask_id}.json"
    data = _read_json(path)
    if not data:
        return None
    try:
        path.unlink()
    except OSError:
        pass  # brAIn tidies its own answers too
    return data


def _withdraw_ask(ask_id: str) -> None:
    try:
        (BRAIN_MORPH / "asks" / f"{ask_id}.json").unlink()
    except OSError:
        pass  # brAIn took it after all; its late answer is dropped unread


@websocket_api.websocket_command({vol.Required("type"): "morph/ask", vol.Required("text"): str})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_ask(hass: HomeAssistant, connection, msg) -> None:
    """Hand Ask's words to brAIn's interpreter (§13.3) and wait for what it
    made of them: done (with a sentence), a conversation, a Tell, or
    `fallback` — no answer, which the panel meets with its old behaviour."""
    import asyncio
    text = msg["text"].strip()
    if not text:
        connection.send_result(msg["id"], {"do": "fallback"})
        return
    if words.too_long(text):
        # Longer than brAIn's interpreter keeps: a conversation takes it
        # whole, where the interpreter would have read a slice of it.
        connection.send_result(msg["id"], {"do": "conversation"})
        return
    ask_id = "a-" + uuid.uuid4().hex[:16]
    user = connection.user.id if connection.user else ""
    try:
        wrote = await hass.async_add_executor_job(_write_ask, ask_id, text, user)
    except OSError:
        wrote = False
    if not wrote:
        connection.send_result(msg["id"], {"do": "fallback"})
        return
    waited = 0.0
    while waited < ASK_WAIT_S:
        await asyncio.sleep(0.4)
        waited += 0.4
        got = await hass.async_add_executor_job(_take_answer, ask_id)
        if got:
            out = {k: got.get(k) for k in ("do", "say", "routes", "tell_text", "undo") if k in got}
            if out.get("do") not in ("done", "conversation", "tell_dashboard", "tell_code", "fallback"):
                out["do"] = "fallback"
            connection.send_result(msg["id"], out)
            return
    await hass.async_add_executor_job(_withdraw_ask, ask_id)
    connection.send_result(msg["id"], {"do": "fallback"})


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
def notify(hass: HomeAssistant, parts) -> None:
    """Tell every open panel which part moved."""
    _notify(hass, parts)


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
    for handler in (ws_load, ws_yaml, ws_request, ws_tell_status, ws_shot, ws_usage, ws_report,
                    ws_finding, ws_case, ws_todo, ws_ask, ws_subscribe, ws_personality, ws_shell):
        websocket_api.async_register_command(hass, handler)
    data["ws"] = True
