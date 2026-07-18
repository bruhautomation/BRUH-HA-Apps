#!/usr/bin/env python3
"""
BRUH Insights ingress panel — aiohttp API + static asset server.

Routes
------
GET  /                       — dashboard HTML
GET  /style.css, /app.js     — static assets
GET  /api/status             — auth state, categories, job states
GET  /api/insights           — all stored insights (with rendered HTML)
POST /api/generate           — queue generation {category} or {question}
POST /api/generate_all       — queue every standard category
POST /api/auth/token         — save a pasted token / API key
POST /api/auth/logout        — forget the stored credential
POST /api/auth/setup/start   — begin guided `claude setup-token` OAuth flow
POST /api/auth/setup/code    — submit the pasted one-time code
GET  /api/auth/setup/status  — poll the guided flow
POST /api/auth/setup/cancel  — abort the guided flow
DELETE /api/insight/{id}     — delete a stored insight (custom cards)

Runs on 0.0.0.0:8099. The HA Supervisor proxies the ingress URL into
/api/hassio_ingress/<token>/...; we therefore use only relative links in the
HTML and let aiohttp serve at /. Generation jobs run through a single-worker
queue so only one Claude invocation is in flight at a time (subscription
rate-limit friendly).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

from aiohttp import web

import categories as cat_mod
import claude_client
from categories import CATEGORIES, SYSTEM_PROMPT, build_prompt, get_category

HERE = Path(__file__).resolve().parent
INSIGHTS_DIR = Path(os.environ.get("BRUH_INSIGHTS_DIR", "/data/insights"))
ADDON_VERSION = os.environ.get("ADDON_VERSION", "dev")
REFRESH_HOURS = float(os.environ.get("BRUH_INSIGHTS_REFRESH_HOURS", "6") or 0)
HISTORY_DAYS = int(os.environ.get("BRUH_INSIGHTS_HISTORY_DAYS", "7") or 7)
MODEL = os.environ.get("BRUH_INSIGHTS_MODEL", "").strip()
TIMEOUT_S = int(float(os.environ.get("BRUH_INSIGHTS_TIMEOUT_MIN", "8") or 8) * 60)
BIND_HOST = "0.0.0.0"
BIND_PORT = 8099
MAX_HTML_BYTES = 400_000
MAX_CUSTOM_KEPT = 12

logging.basicConfig(
    level=getattr(logging, os.environ.get("BRUH_INSIGHTS_LOG_LEVEL", "info").upper(), logging.INFO),
    format="[insights] %(levelname)s %(message)s",
)
log = logging.getLogger("bruh-insights")

# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------
# JOBS[insight_id] = {state, phase, started_at, error, question}
JOBS: dict[str, dict] = {}
QUEUE: asyncio.Queue[str] = asyncio.Queue()
AUTH_CHECK: dict = {"state": "unchecked", "error": "", "checked_at": 0}
LAST_FULL_REFRESH = 0.0


def _job_active(insight_id: str) -> bool:
    return JOBS.get(insight_id, {}).get("state") in ("queued", "collecting", "generating", "parsing")


def _set_job(insight_id: str, **fields) -> None:
    JOBS.setdefault(insight_id, {})[
        "updated_at"
    ] = time.time()
    JOBS[insight_id].update(fields)


# ---------------------------------------------------------------------------
# Insight storage
# ---------------------------------------------------------------------------

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


def _insight_path(insight_id: str) -> Path:
    if not _SAFE_ID.match(insight_id):
        raise web.HTTPBadRequest(text="bad insight id")
    return INSIGHTS_DIR / f"{insight_id}.json"


def load_insights() -> list[dict]:
    """All stored insights: standard categories in canonical order, then custom (newest first)."""
    out: list[dict] = []
    custom: list[dict] = []
    files = {p.stem: p for p in INSIGHTS_DIR.glob("*.json")}
    for cat in CATEGORIES:
        p = files.pop(cat["id"], None)
        if p:
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
    for stem, p in files.items():
        try:
            custom.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    custom.sort(key=lambda i: i.get("generated_at", ""), reverse=True)
    return out + custom


def save_insight(insight: dict) -> None:
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _insight_path(insight["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(insight, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    # keep only the newest N custom insights
    customs = sorted(
        (p for p in INSIGHTS_DIR.glob("custom-*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in customs[MAX_CUSTOM_KEPT:]:
        try:
            old.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Generation worker
# ---------------------------------------------------------------------------

async def _generate(insight_id: str) -> None:
    job = JOBS.get(insight_id, {})
    question = job.get("question")
    category = get_category(insight_id) if question is None else None
    if question is None and category is None:
        _set_job(insight_id, state="error", error="unknown category")
        return
    cat = category or {
        "id": insight_id, "title": "Custom", "icon": "✨",
        "domains": [], "device_classes": [], "history": False, "stats": False,
        "focus": "",
    }
    try:
        _set_job(insight_id, state="collecting", error="")
        import ha_data  # deferred so the module loads without aiohttp in tests
        bundle = await ha_data.collect_bundle(cat, HISTORY_DAYS, question=question)
        n_entities = len(bundle.get("entities", []))
        log.info("bundle for %s: %d entities, %d chars", insight_id, n_entities,
                 len(json.dumps(bundle)))

        _set_job(insight_id, state="generating")
        prompt = build_prompt(cat, bundle, question=question)
        result = await asyncio.to_thread(
            claude_client.run_claude, prompt, SYSTEM_PROMPT, MODEL, TIMEOUT_S,
        )
        if not result["ok"]:
            raise RuntimeError(result["error"] or "generation failed")

        _set_job(insight_id, state="parsing")
        obj = claude_client.extract_json(result["text"])
        if not obj or not isinstance(obj.get("html"), str) or not obj.get("title"):
            raise RuntimeError("Claude returned an unparseable insight (no JSON/html)")
        html = obj["html"]
        if len(html.encode()) > MAX_HTML_BYTES:
            raise RuntimeError("generated visualization too large")
        highlights = obj.get("highlights")
        if not isinstance(highlights, list):
            highlights = []
        insight = {
            "id": insight_id,
            "category": cat["id"] if question is None else "custom",
            "icon": cat.get("icon", "✨"),
            "category_title": cat.get("title", "Custom"),
            "question": question,
            "title": str(obj.get("title", ""))[:120],
            "summary": str(obj.get("summary", ""))[:2000],
            "highlights": highlights[:6],
            "html": html,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "meta": result.get("meta", {}),
        }
        save_insight(insight)
        _set_job(insight_id, state="done", error="")
        log.info("insight %s generated (%s)", insight_id, insight["title"])
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        log.warning("insight %s failed: %s", insight_id, exc)
        _set_job(insight_id, state="error", error=str(exc)[:500])


async def _worker() -> None:
    while True:
        insight_id = await QUEUE.get()
        try:
            await _generate(insight_id)
        finally:
            QUEUE.task_done()


async def _scheduler() -> None:
    """Auto-refresh all categories every REFRESH_HOURS (0 disables)."""
    global LAST_FULL_REFRESH
    if REFRESH_HOURS <= 0:
        return
    # on boot, count existing insights as fresh enough to avoid a thundering start
    LAST_FULL_REFRESH = time.time()
    stored = load_insights()
    if not stored:
        LAST_FULL_REFRESH = 0
    while True:
        await asyncio.sleep(60)
        if not claude_client.get_auth():
            continue
        if time.time() - LAST_FULL_REFRESH < REFRESH_HOURS * 3600:
            continue
        LAST_FULL_REFRESH = time.time()
        log.info("auto-refresh: queueing all categories")
        for cat in CATEGORIES:
            _enqueue(cat["id"])


def _enqueue(insight_id: str, question: str | None = None) -> bool:
    if _job_active(insight_id):
        return False
    _set_job(insight_id, state="queued", error="", question=question,
             started_at=time.time())
    QUEUE.put_nowait(insight_id)
    return True


async def _check_auth_bg() -> None:
    AUTH_CHECK.update(state="checking", error="")
    result = await asyncio.to_thread(claude_client.validate_auth)
    AUTH_CHECK.update(
        state="ok" if result["ok"] else "failed",
        error=result["error"],
        checked_at=time.time(),
    )


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

async def h_index(request: web.Request) -> web.Response:
    html = (HERE / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{VERSION}}", ADDON_VERSION)
    return web.Response(text=html, content_type="text/html")


def _static(name: str, ctype: str):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(
            text=(HERE / name).read_text(encoding="utf-8"), content_type=ctype,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    return handler


async def h_status(request: web.Request) -> web.Response:
    auth = claude_client.get_auth()
    insights = {i["id"]: i.get("generated_at") for i in load_insights()}
    return web.json_response({
        "version": ADDON_VERSION,
        "authenticated": bool(auth),
        "auth_type": auth["type"] if auth else None,
        "auth_check": AUTH_CHECK,
        "model": MODEL or "default",
        "refresh_hours": REFRESH_HOURS,
        "history_days": HISTORY_DAYS,
        "categories": [
            {
                "id": c["id"],
                "title": c["title"],
                "icon": c["icon"],
                "description": c["description"],
                "generated_at": insights.get(c["id"]),
                "job": {k: JOBS.get(c["id"], {}).get(k) for k in ("state", "error")},
            }
            for c in CATEGORIES
        ],
        "jobs": {jid: {"state": j.get("state"), "error": j.get("error")}
                 for jid, j in JOBS.items()},
        "queue_size": QUEUE.qsize(),
    })


async def h_insights(request: web.Request) -> web.Response:
    return web.json_response({"insights": load_insights()})


async def h_generate(request: web.Request) -> web.Response:
    body = await request.json()
    question = (body.get("question") or "").strip() or None
    if question:
        if len(question) > 500:
            raise web.HTTPBadRequest(text="question too long")
        insight_id = f"custom-{int(time.time())}"
        _enqueue(insight_id, question=question)
        return web.json_response({"queued": [insight_id]})
    cat_id = body.get("category", "")
    if not get_category(cat_id):
        raise web.HTTPBadRequest(text="unknown category")
    started = _enqueue(cat_id)
    return web.json_response({"queued": [cat_id] if started else []})


async def h_generate_all(request: web.Request) -> web.Response:
    global LAST_FULL_REFRESH
    LAST_FULL_REFRESH = time.time()
    queued = [c["id"] for c in CATEGORIES if _enqueue(c["id"])]
    return web.json_response({"queued": queued})


async def h_delete_insight(request: web.Request) -> web.Response:
    insight_id = request.match_info["id"]
    path = _insight_path(insight_id)
    try:
        path.unlink()
    except OSError:
        raise web.HTTPNotFound(text="no such insight")
    JOBS.pop(insight_id, None)
    return web.json_response({"deleted": insight_id})


# -- auth -------------------------------------------------------------------

async def h_auth_token(request: web.Request) -> web.Response:
    body = await request.json()
    token = (body.get("token") or "").strip()
    try:
        saved = claude_client.save_auth(token)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    asyncio.create_task(_check_auth_bg())
    return web.json_response({"saved": True, "type": saved["type"]})


async def h_auth_logout(request: web.Request) -> web.Response:
    claude_client.clear_auth()
    claude_client.SETUP_FLOW.cancel()
    AUTH_CHECK.update(state="unchecked", error="", checked_at=0)
    return web.json_response({"cleared": True})


async def h_setup_start(request: web.Request) -> web.Response:
    status = await asyncio.to_thread(claude_client.SETUP_FLOW.start)
    return web.json_response(status)


async def h_setup_code(request: web.Request) -> web.Response:
    body = await request.json()
    code = (body.get("code") or "").strip()
    if not code:
        raise web.HTTPBadRequest(text="empty code")
    status = await asyncio.to_thread(claude_client.SETUP_FLOW.submit_code, code)
    return web.json_response(status)


async def h_setup_status(request: web.Request) -> web.Response:
    status = claude_client.SETUP_FLOW.status()
    if status["phase"] == "done" and AUTH_CHECK["state"] == "unchecked":
        asyncio.create_task(_check_auth_bg())
    return web.json_response(status)


async def h_setup_cancel(request: web.Request) -> web.Response:
    claude_client.SETUP_FLOW.cancel()
    return web.json_response(claude_client.SETUP_FLOW.status())


async def h_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

def make_app() -> web.Application:
    app = web.Application(client_max_size=1024 * 64)
    app.router.add_get("/", h_index)
    app.router.add_get("/style.css", _static("style.css", "text/css"))
    app.router.add_get("/app.js", _static("app.js", "application/javascript"))
    app.router.add_get("/favicon.svg", _static("favicon.svg", "image/svg+xml"))
    app.router.add_get("/api/status", h_status)
    app.router.add_get("/api/insights", h_insights)
    app.router.add_post("/api/generate", h_generate)
    app.router.add_post("/api/generate_all", h_generate_all)
    app.router.add_delete("/api/insight/{id}", h_delete_insight)
    app.router.add_post("/api/auth/token", h_auth_token)
    app.router.add_post("/api/auth/logout", h_auth_logout)
    app.router.add_post("/api/auth/setup/start", h_setup_start)
    app.router.add_post("/api/auth/setup/code", h_setup_code)
    app.router.add_get("/api/auth/setup/status", h_setup_status)
    app.router.add_post("/api/auth/setup/cancel", h_setup_cancel)
    app.router.add_get("/api/health", h_health)

    async def on_startup(app: web.Application) -> None:
        app["worker"] = asyncio.create_task(_worker())
        app["scheduler"] = asyncio.create_task(_scheduler())
        if claude_client.get_auth():
            asyncio.create_task(_check_auth_bg())

    app.on_startup.append(on_startup)
    return app


if __name__ == "__main__":
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    web.run_app(make_app(), host=BIND_HOST, port=BIND_PORT, print=None)
