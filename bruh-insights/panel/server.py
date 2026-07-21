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
GET  /api/insight/{id}/history       — past runs of a category (no html)
GET  /api/insight/{id}/history/{ts}  — one stored past run in full
DELETE /api/insight/{id}/history/{ts} — remove one past run
GET  /api/prompts            — per-category prompt/override listing
PUT  /api/prompt/{id}        — set focus/enabled/refresh_hours override
DELETE /api/prompt/{id}      — reset a category to shipped defaults
POST /api/user_category      — create a user-defined recurring insight
PUT  /api/user_category/{id} — edit a user-defined insight
DELETE /api/user_category/{id} — delete one (definition + insight + history)
GET  /api/insight/{id}/feedback      — standing feedback for a category
POST /api/insight/{id}/feedback      — add feedback (steers future runs)
DELETE /api/insight/{id}/feedback/{ts} — drop one feedback entry
GET  /api/card_info          — dashboard-card server port/token + HA URLs
GET  /api/questions          — open analyst questions across insights
POST /api/questions/answer   — answer one (forwards to bruh_claude, if installed)
GET  /api/knowledge          — learned facts + question ledger + shared memory.md
POST /api/knowledge/fact     — add a fact by hand {text}
DELETE /api/knowledge/fact/{ts}            — forget one fact
POST /api/knowledge/question/{ts}/answer   — answer an open question {answer}
POST /api/knowledge/question/{ts}/dismiss  — retire a question unanswered
DELETE /api/knowledge/question/{ts}        — forget a question (askable again)

Runs on 0.0.0.0:8099. The HA Supervisor proxies the ingress URL into
/api/hassio_ingress/<token>/...; we therefore use only relative links in the
HTML and let aiohttp serve at /. Generation jobs run through a single-worker
queue so only one Claude invocation is in flight at a time (subscription
rate-limit friendly).

A second, token-protected mini server on :8100 (the "card server") serves
each stored insight's self-contained HTML so HA dashboard webpage cards can
embed live insights. The port is unexposed by default; users map it in the
add-on's network settings when they want dashboard cards.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from aiohttp import web

import categories as cat_mod
import claude_client
import feedback_store
import knowledge_store
import prompt_store
import user_categories
from categories import CATEGORIES, SYSTEM_PROMPT, build_prompt, get_category

HERE = Path(__file__).resolve().parent
INSIGHTS_DIR = Path(os.environ.get("BRUH_INSIGHTS_DIR", "/data/insights"))
ADDON_VERSION = os.environ.get("ADDON_VERSION", "dev")
REFRESH_HOURS = float(os.environ.get("BRUH_INSIGHTS_REFRESH_HOURS", "6") or 0)
HISTORY_DAYS = int(os.environ.get("BRUH_INSIGHTS_HISTORY_DAYS", "7") or 7)
# Dated per-run copies of each category insight (0 for either disables history)
HISTORY_KEEP_RUNS = int(os.environ.get("BRUH_INSIGHTS_HISTORY_KEEP_RUNS", "40") or 40)
HISTORY_KEEP_DAYS = int(os.environ.get("BRUH_INSIGHTS_HISTORY_KEEP_DAYS", "30") or 30)
# Fallback drop-box for learned facts when the bruh_claude integration
# isn't installed — the BRUH Terminal add-on ingests it from /share
MEMORY_INBOX_DIR = Path(os.environ.get(
    "BRUH_INSIGHTS_MEMORY_INBOX", "/share/bruh_claude/memory-inbox"))
# The BRUH Terminal integration's consolidated memory file (read-only view
# for the knowledge panel; same default as ha_data.MEMORY_FILE)
SHARED_MEMORY_FILE = Path(os.environ.get(
    "BRUH_MEMORY_FILE", "/config/.bruh_claude/memory/memory.md"))
MODEL = os.environ.get("BRUH_INSIGHTS_MODEL", "").strip()
TIMEOUT_S = int(float(os.environ.get("BRUH_INSIGHTS_TIMEOUT_MIN", "8") or 8) * 60)
BIND_HOST = "0.0.0.0"
BIND_PORT = 8099
# Dashboard-card mini server (HTML for HA webpage cards); token-protected.
CARD_PORT = int(os.environ.get("BRUH_INSIGHTS_CARD_PORT", "8100") or 8100)
CARD_TOKEN_FILE = Path(
    os.environ.get("BRUH_INSIGHTS_SECRETS", "/data/secrets")) / "card_token"
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
# `generated_at` with ':' → '-' (filesystem-safe); strict so it can be
# safely joined into a path
_STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$")


def _insight_path(insight_id: str) -> Path:
    if not _SAFE_ID.match(insight_id):
        raise web.HTTPBadRequest(text="bad insight id")
    return INSIGHTS_DIR / f"{insight_id}.json"


def _history_dir(insight_id: str) -> Path:
    if not _SAFE_ID.match(insight_id):
        raise web.HTTPBadRequest(text="bad insight id")
    return INSIGHTS_DIR / "history" / insight_id


def all_categories() -> list[dict]:
    """Shipped categories followed by user-defined ones (creation order)."""
    return CATEGORIES + user_categories.load()


def resolve_category(cat_id: str) -> dict | None:
    """Effective category for generation: shipped (with overrides) or user-defined."""
    if get_category(cat_id):
        return prompt_store.effective_category(cat_id)
    return user_categories.get(cat_id)


def load_insights() -> list[dict]:
    """All stored insights: standard categories in canonical order, then
    user-defined insights (creation order), then custom asks (newest first)."""
    out: list[dict] = []
    custom: list[dict] = []
    files = {p.stem: p for p in INSIGHTS_DIR.glob("*.json")}
    for cat in all_categories():
        p = files.pop(cat["id"], None)
        if p:
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
    for stem, p in files.items():
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # leftovers are ad-hoc Ask cards; orphaned user-* files (definition
        # deleted mid-write) are skipped rather than shown as ghost cards
        if isinstance(obj, dict) and obj.get("id") and not stem.startswith("user-"):
            custom.append(obj)
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
    _write_history_copy(insight)


def _write_history_copy(insight: dict) -> None:
    """Dated copy under history/<id>/<stamp>.json so past runs stay browsable.

    Custom question cards are excluded, and load_insights() never sees the
    history/ subdir (its glob is non-recursive). Setting either keep option
    to 0 disables history entirely.
    """
    if insight["id"].startswith("custom-"):
        return
    if HISTORY_KEEP_RUNS <= 0 or HISTORY_KEEP_DAYS <= 0:
        return
    stamp = str(insight.get("generated_at", "")).replace(":", "-")
    if not _STAMP_RE.match(stamp):
        return
    hdir = _history_dir(insight["id"])
    try:
        hdir.mkdir(parents=True, exist_ok=True)
        tmp = hdir / f"{stamp}.tmp"
        tmp.write_text(json.dumps(insight, ensure_ascii=False), encoding="utf-8")
        tmp.replace(hdir / f"{stamp}.json")
    except OSError as exc:
        log.warning("could not store history run for %s: %s", insight["id"], exc)
        return
    _prune_history(hdir)


def _prune_history(hdir: Path) -> None:
    """Keep at most HISTORY_KEEP_RUNS files, none older than HISTORY_KEEP_DAYS
    (age judged by the filename stamp — lexicographic order matches time)."""
    files = sorted(hdir.glob("*.json"), key=lambda p: p.name, reverse=True)
    cutoff = time.strftime(
        "%Y-%m-%dT%H-%M-%S", time.localtime(time.time() - HISTORY_KEEP_DAYS * 86400))
    for i, path in enumerate(files):
        if i < HISTORY_KEEP_RUNS and path.stem >= cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Memory hand-off (bruh_claude integration, /share inbox fallback)
# ---------------------------------------------------------------------------

async def _call_ha_service(service: str, data: dict) -> bool:
    """Call a bruh_claude.<service> HA service; False when it isn't there.

    The integration ships with the BRUH Terminal add-on and may simply not
    be installed — every failure here is expected and non-fatal.
    """
    try:
        import ha_data  # deferred so the module loads without aiohttp in tests
        await ha_data.call_service(service, data)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort hand-off
        log.debug("bruh_claude.%s unavailable: %s", service, exc)
        return False


def _write_memory_inbox(fact: str) -> None:
    """Fallback: append the fact as JSONL to the shared /share inbox.

    Best-effort only — if /share isn't writable, log and drop silently;
    memory hand-off must never break an insight run.
    """
    try:
        MEMORY_INBOX_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"ts": int(time.time()), "source": "insights", "fact": fact,
             "confidence": "medium"},
            ensure_ascii=False,
        )
        path = MEMORY_INBOX_DIR / f"{int(time.time())}-insights.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        log.debug("memory inbox write failed: %s", exc)


async def _submit_memory(fact: str) -> None:
    if not await _call_ha_service(
            "add_memory", {"fact": fact, "source": "insights", "confidence": "medium"}):
        await asyncio.to_thread(_write_memory_inbox, fact)


async def _submit_answer(question: str, answer: str) -> None:
    if not await _call_ha_service(
            "answer_question", {"question": question, "answer": answer, "source": "insights"}):
        await asyncio.to_thread(_write_memory_inbox, f"Q: {question} → A: {answer}")


# ---------------------------------------------------------------------------
# Generation worker
# ---------------------------------------------------------------------------

def _clean_strings(value, max_items: int, max_chars: int) -> list[str]:
    """Sanitize a model-returned string array: strings only, trimmed, capped."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item:
            out.append(item[:max_chars])
        if len(out) >= max_items:
            break
    return out


async def _generate(insight_id: str) -> None:
    job = JOBS.get(insight_id, {})
    question = job.get("question")
    category = resolve_category(insight_id) if question is None else None
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
        feedback = [] if question is not None else [
            f["text"] for f in feedback_store.list_feedback(insight_id)]
        # Continuity: what the analyst already knows, and what this card
        # said last time — so runs build on each other instead of looping.
        knowledge = knowledge_store.prompt_block()
        previous = None
        if question is None:
            try:
                prev = json.loads(_insight_path(insight_id).read_text(encoding="utf-8"))
                previous = {k: prev.get(k) for k in
                            ("generated_at", "title", "summary", "highlights", "findings")}
            except (OSError, ValueError):
                pass
        prompt = build_prompt(cat, bundle, question=question, feedback=feedback,
                              knowledge=knowledge, previous=previous)
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
        # Backstop against re-asking: drop any question equivalent to one
        # already in the knowledge store (whatever its status), then record
        # the genuinely new ones so THEY are never asked twice either.
        questions = []
        for q in _clean_strings(obj.get("questions"), 2, 300):
            entry = knowledge_store.record_question(q, cat["id"])
            if (entry is None or entry.get("status") != "open"
                    or int(entry.get("asked_count") or 1) > 1):
                log.info("dropping re-asked question: %s", q)
                continue
            questions.append(q)
        findings = _clean_strings(obj.get("findings"), 3, 500)
        tags: list[str] = []
        for tag in _clean_strings(obj.get("tags"), 4, 24):
            tag = tag.lower().strip("#- ")
            if tag and tag not in tags:
                tags.append(tag)
        insight = {
            "id": insight_id,
            "category": cat["id"] if question is None else "custom",
            "icon": cat.get("icon", "✨"),
            "category_title": cat.get("title", "Custom"),
            "question": question,
            "title": str(obj.get("title", ""))[:120],
            "summary": str(obj.get("summary", ""))[:2000],
            "highlights": highlights[:6],
            "questions": questions,
            "findings": findings,
            "tags": tags,
            "focus_used": cat.get("focus", "") if question is None else "",
            "html": html,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "meta": result.get("meta", {}),
        }
        save_insight(insight)
        # Learn the durable findings: store NEW ones in our own knowledge
        # base (dedup by content) and hand those on to the home's shared
        # memory. Already-known "findings" are silently swallowed — the
        # model was told not to repeat them, this enforces it.
        for fact in findings:
            _, created = knowledge_store.add_fact(
                fact, source="insights", category=cat["id"])
            if created:
                await _submit_memory(fact)
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


def _refresh_due(eff: dict, generated_at: str, now: float) -> bool:
    """True when a category's stored insight is older than its effective
    interval (per-category refresh_hours override, else global REFRESH_HOURS;
    0 disables). A missing or unparseable timestamp counts as ancient, so
    first boot generates every enabled category."""
    if not eff.get("enabled", True):
        return False
    hours = eff.get("refresh_hours")
    if hours is None:
        hours = REFRESH_HOURS
    if hours <= 0:
        return False
    if not generated_at:
        return True
    try:
        age = now - time.mktime(time.strptime(generated_at[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return True
    return age >= hours * 3600


async def _scheduler() -> None:
    """Per-category auto-refresh: each tick, queue any enabled category whose
    stored insight has outlived its effective refresh interval."""
    while True:
        await asyncio.sleep(60)
        if not claude_client.get_auth():
            continue
        stored = {i["id"]: i.get("generated_at", "") for i in load_insights()}
        now = time.time()
        for cat in all_categories():
            eff = resolve_category(cat["id"]) or cat
            if _refresh_due(eff, stored.get(cat["id"], ""), now) and _enqueue(cat["id"]):
                log.info("auto-refresh: queued %s", cat["id"])


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


def _category_status(c: dict, insights: dict) -> dict:
    if c.get("user"):
        return {
            "id": c["id"],
            "title": c["title"],
            "icon": c["icon"],
            "description": c["description"],
            "generated_at": insights.get(c["id"]),
            "focus": c["focus"],
            "default_focus": c["focus"],
            "focus_overridden": False,
            "enabled": c.get("enabled", True),
            "refresh_hours": c.get("refresh_hours"),
            "user": True,
            "job": {k: JOBS.get(c["id"], {}).get(k) for k in ("state", "error")},
        }
    eff = prompt_store.effective_category(c["id"]) or c
    return {
        "id": c["id"],
        "title": c["title"],
        "icon": c["icon"],
        "description": c["description"],
        "generated_at": insights.get(c["id"]),
        "focus": eff.get("focus", c["focus"]),
        "default_focus": c["focus"],
        "focus_overridden": "focus" in eff.get("overridden", []),
        "enabled": eff.get("enabled", True),
        "refresh_hours": eff.get("refresh_hours"),
        "job": {k: JOBS.get(c["id"], {}).get(k) for k in ("state", "error")},
    }


async def h_status(request: web.Request) -> web.Response:
    auth = claude_client.get_auth()
    insights = {i["id"]: i.get("generated_at") for i in load_insights()}
    return web.json_response({
        "version": ADDON_VERSION,
        "authenticated": bool(auth),
        "auth_type": auth["type"] if auth else None,
        "auth_source": auth.get("source") if auth else None,
        "auth_check": AUTH_CHECK,
        "model": MODEL or "default",
        "refresh_hours": REFRESH_HOURS,
        "history_days": HISTORY_DAYS,
        "categories": [_category_status(c, insights) for c in all_categories()],
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
    if not resolve_category(cat_id):
        raise web.HTTPBadRequest(text="unknown category")
    started = _enqueue(cat_id)
    return web.json_response({"queued": [cat_id] if started else []})


async def h_generate_all(request: web.Request) -> web.Response:
    queued = []
    for c in all_categories():
        eff = resolve_category(c["id"]) or c
        if not eff.get("enabled", True):
            continue
        if _enqueue(c["id"]):
            queued.append(c["id"])
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


# -- insight history --------------------------------------------------------

def _history_run_path(request: web.Request) -> Path:
    hdir = _history_dir(request.match_info["id"])
    ts = request.match_info["ts"]
    if not _STAMP_RE.match(ts):
        raise web.HTTPBadRequest(text="bad timestamp")
    return hdir / f"{ts}.json"


async def h_history_list(request: web.Request) -> web.Response:
    hdir = _history_dir(request.match_info["id"])
    runs = []
    for path in sorted(hdir.glob("*.json"), key=lambda p: p.name, reverse=True):
        if not _STAMP_RE.match(path.stem):
            continue
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        runs.append({
            "ts": path.stem,
            "generated_at": obj.get("generated_at"),
            "title": obj.get("title"),
        })
    return web.json_response({"runs": runs})


async def h_history_get(request: web.Request) -> web.Response:
    path = _history_run_path(request)
    try:
        return web.json_response(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text="no such run")


async def h_history_delete(request: web.Request) -> web.Response:
    path = _history_run_path(request)
    try:
        path.unlink()
    except OSError:
        raise web.HTTPNotFound(text="no such run")
    return web.json_response({"deleted": request.match_info["ts"]})


# -- prompt overrides -------------------------------------------------------

def _prompt_record(cat_id: str) -> dict:
    c = get_category(cat_id)
    eff = prompt_store.effective_category(cat_id)
    return {
        "id": cat_id,
        "title": c["title"],
        "default_focus": c["focus"],
        "focus": eff["focus"],
        "overridden": eff["overridden"],
        "enabled": eff["enabled"],
        "refresh_hours": eff["refresh_hours"],
    }


async def h_prompts(request: web.Request) -> web.Response:
    return web.json_response({"prompts": [_prompt_record(c["id"]) for c in CATEGORIES]})


async def h_prompt_put(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    cat = get_category(cat_id)
    if not cat:
        raise web.HTTPBadRequest(text="unknown category")
    body = await request.json()
    fields: dict = {}
    if "focus" in body:
        focus = body["focus"]
        if not isinstance(focus, str):
            raise web.HTTPBadRequest(text="focus must be a string")
        focus = focus.strip()[:4000]
        # empty or identical-to-default focus clears the override
        fields["focus"] = focus if focus and focus != cat["focus"] else None
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise web.HTTPBadRequest(text="enabled must be a boolean")
        # enabled is the default — only a disable is worth storing
        fields["enabled"] = None if body["enabled"] else False
    if "refresh_hours" in body:
        hours = body["refresh_hours"]
        if hours is not None and (
                not isinstance(hours, int) or isinstance(hours, bool)
                or not 0 <= hours <= 168):
            raise web.HTTPBadRequest(text="refresh_hours must be an integer 0-168 or null")
        fields["refresh_hours"] = hours
    prompt_store.save_override(cat_id, fields)
    return web.json_response(_prompt_record(cat_id))


async def h_prompt_delete(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    if not get_category(cat_id):
        raise web.HTTPBadRequest(text="unknown category")
    prompt_store.reset_override(cat_id)
    return web.json_response(_prompt_record(cat_id))


# -- user-defined insights --------------------------------------------------

async def h_user_category_create(request: web.Request) -> web.Response:
    body = await request.json()
    try:
        cat = user_categories.create(body if isinstance(body, dict) else {})
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    if body.get("generate_now", True) and cat.get("enabled", True):
        _enqueue(cat["id"])
    return web.json_response(cat)


async def h_user_category_put(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    body = await request.json()
    try:
        cat = user_categories.update(cat_id, body if isinstance(body, dict) else {})
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    if cat is None:
        raise web.HTTPNotFound(text="no such insight")
    return web.json_response(cat)


async def h_user_category_delete(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    if not user_categories.delete(cat_id):
        raise web.HTTPNotFound(text="no such insight")
    # drop everything that belonged to it: insight, history runs, feedback
    try:
        _insight_path(cat_id).unlink()
    except OSError:
        pass
    shutil.rmtree(_history_dir(cat_id), ignore_errors=True)
    feedback_store.clear(cat_id)
    JOBS.pop(cat_id, None)
    return web.json_response({"deleted": cat_id})


# -- insight feedback ---------------------------------------------------------

def _feedback_category(cat_id: str) -> dict:
    cat = get_category(cat_id) or user_categories.get(cat_id)
    if not cat:
        raise web.HTTPBadRequest(text="feedback works on recurring insights only")
    return cat


async def h_feedback_list(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    _feedback_category(cat_id)
    return web.json_response({"feedback": feedback_store.list_feedback(cat_id)})


async def h_feedback_add(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    cat = _feedback_category(cat_id)
    body = await request.json()
    try:
        entry = feedback_store.add_feedback(cat_id, body.get("feedback"))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    # feedback is durable knowledge about this home's preferences — remember it
    fact = f'Homeowner feedback on the "{cat["title"]}" insight card: {entry["text"]}'
    knowledge_store.add_fact(fact, source="feedback", category=cat_id)
    await _submit_memory(fact)
    return web.json_response(
        {"added": entry, "feedback": feedback_store.list_feedback(cat_id)})


async def h_feedback_delete(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    _feedback_category(cat_id)
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad feedback id")
    if not feedback_store.remove_feedback(cat_id, ts):
        raise web.HTTPNotFound(text="no such feedback entry")
    return web.json_response({"feedback": feedback_store.list_feedback(cat_id)})


# -- dashboard card server ----------------------------------------------------
# A separate mini HTTP app on CARD_PORT serving ONLY stored insight HTML,
# guarded by a per-install random token. The HA dashboard "Webpage" (iframe)
# card can't ride the ingress session, so this is the bridge: the user maps
# the port in the add-on network settings and pastes YAML the panel offers.

def get_card_token() -> str:
    try:
        token = CARD_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(token) >= 16:
            return token
    except OSError:
        pass
    token = secrets.token_hex(16)
    CARD_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    CARD_TOKEN_FILE.write_text(token, encoding="utf-8")
    try:
        CARD_TOKEN_FILE.chmod(0o600)
    except OSError:
        pass
    return token


# reload periodically so a dashboard card tracks regenerated insights
_CARD_RELOAD_SNIPPET = (
    '\n<script>setTimeout(function(){location.reload();},900000);</script>'
)


async def h_card(request: web.Request) -> web.Response:
    token = request.query.get("token", "")
    if not secrets.compare_digest(token, get_card_token()):
        raise web.HTTPUnauthorized(text="bad or missing token")
    path = _insight_path(request.match_info["id"])
    try:
        insight = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text="no such insight")
    html = insight.get("html")
    if not isinstance(html, str) or not html:
        raise web.HTTPNotFound(text="insight has no visualization")
    return web.Response(
        text=html + _CARD_RELOAD_SNIPPET,
        content_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


def make_card_app() -> web.Application:
    app = web.Application(client_max_size=1024)
    app.router.add_get("/card/{id}", h_card)
    return app


_HA_URLS_CACHE: dict = {"ts": 0.0, "urls": {}}


async def _ha_urls() -> dict:
    """internal_url/external_url from HA core config (best-effort, cached)."""
    if time.time() - _HA_URLS_CACHE["ts"] < 300:
        return _HA_URLS_CACHE["urls"]
    urls: dict = {}
    try:
        import aiohttp

        import ha_data
        async with aiohttp.ClientSession() as session:
            cfg = await ha_data._rest_get(session, "/config", timeout=10)
        urls = {
            "internal_url": cfg.get("internal_url"),
            "external_url": cfg.get("external_url"),
        }
    except Exception as exc:  # noqa: BLE001 — cosmetic; YAML falls back to a template host
        log.debug("could not fetch HA urls: %s", exc)
    _HA_URLS_CACHE.update(ts=time.time(), urls=urls)
    return urls


async def h_card_info(request: web.Request) -> web.Response:
    urls = await _ha_urls()
    return web.json_response({
        "port": CARD_PORT,
        "token": get_card_token(),
        "internal_url": urls.get("internal_url"),
        "external_url": urls.get("external_url"),
    })


# -- analyst questions ------------------------------------------------------

async def h_questions(request: web.Request) -> web.Response:
    out = []
    for ins in load_insights():
        for q in ins.get("questions") or []:
            if isinstance(q, str) and q.strip():
                out.append({
                    "insight_id": ins["id"],
                    "category_title": ins.get("category_title", ""),
                    "question": q,
                })
    return web.json_response({"questions": out})


async def h_answer_question(request: web.Request) -> web.Response:
    body = await request.json()
    insight_id = str(body.get("insight_id") or "")
    question = str(body.get("question") or "").strip()
    answer = str(body.get("answer") or "").strip()
    if not question or not answer:
        raise web.HTTPBadRequest(text="question and answer required")
    if len(answer) > 1000:
        raise web.HTTPBadRequest(text="answer too long")
    path = _insight_path(insight_id)
    try:
        insight = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text="no such insight")
    questions = [q for q in (insight.get("questions") or []) if isinstance(q, str)]
    if question not in questions:
        raise web.HTTPNotFound(text="no such open question")
    # the answer is durable knowledge: retire the question locally and keep
    # the Q→A as a fact every future run sees
    knowledge_store.answer_question(question, answer)
    knowledge_store.add_fact(f"Q: {question} → A: {answer}",
                             source="homeowner", category=insight.get("category", ""))
    await _submit_answer(question, answer)
    # answered — stop surfacing it
    insight["questions"] = [q for q in questions if q != question]
    save_insight(insight)
    return web.json_response({"answered": True, "remaining": len(insight["questions"])})


# -- knowledge (the analyst's viewable memory) ------------------------------

def _retire_question_everywhere(text: str) -> None:
    """Remove a question string from every stored insight card so the UI
    stops surfacing it once it's answered or dismissed in the store."""
    for ins in load_insights():
        qs = [q for q in (ins.get("questions") or []) if isinstance(q, str)]
        kept = [q for q in qs
                if knowledge_store.normalize(q) != knowledge_store.normalize(text)]
        if len(kept) != len(qs):
            ins["questions"] = kept
            save_insight(ins)


async def h_knowledge(request: web.Request) -> web.Response:
    """Everything the analyst has learned, in one payload for the panel."""
    memory_text = ""
    try:
        memory_text = SHARED_MEMORY_FILE.read_text(
            encoding="utf-8", errors="replace")[:20_000]
    except OSError:
        pass
    return web.json_response({
        "facts": knowledge_store.list_facts(),
        "questions": knowledge_store.list_questions(),
        "shared_memory": memory_text,
    })


async def h_knowledge_fact_add(request: web.Request) -> web.Response:
    body = await request.json()
    text = str(body.get("text") or "").strip()
    if not text:
        raise web.HTTPBadRequest(text="fact text required")
    if len(text) > knowledge_store.MAX_TEXT_CHARS:
        raise web.HTTPBadRequest(
            text=f"fact too long (max {knowledge_store.MAX_TEXT_CHARS} chars)")
    entry, created = knowledge_store.add_fact(text, source="user")
    if created:
        await _submit_memory(text)
    return web.json_response({"added": created, "fact": entry})


async def h_knowledge_fact_delete(request: web.Request) -> web.Response:
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad fact id")
    if not knowledge_store.remove_fact(ts):
        raise web.HTTPNotFound(text="no such fact")
    return web.json_response({"deleted": ts})


async def h_knowledge_answer(request: web.Request) -> web.Response:
    """Answer an open question from the knowledge panel (by ts)."""
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad question id")
    body = await request.json()
    answer = str(body.get("answer") or "").strip()
    if not answer:
        raise web.HTTPBadRequest(text="answer required")
    if len(answer) > 1000:
        raise web.HTTPBadRequest(text="answer too long")
    match = next((q for q in knowledge_store.list_questions() if q["ts"] == ts), None)
    if match is None:
        raise web.HTTPNotFound(text="no such question")
    knowledge_store.answer_question(match["text"], answer)
    knowledge_store.add_fact(f"Q: {match['text']} → A: {answer}",
                             source="homeowner", category=match.get("category", ""))
    await _submit_answer(match["text"], answer)
    _retire_question_everywhere(match["text"])
    return web.json_response({"answered": True})


async def h_knowledge_dismiss(request: web.Request) -> web.Response:
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad question id")
    match = next((q for q in knowledge_store.list_questions() if q["ts"] == ts), None)
    if match is None or not knowledge_store.dismiss_question(ts):
        raise web.HTTPNotFound(text="no such question")
    _retire_question_everywhere(match["text"])
    return web.json_response({"dismissed": ts})


async def h_knowledge_question_delete(request: web.Request) -> web.Response:
    """Forget a question entirely — it becomes askable again."""
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad question id")
    if not knowledge_store.remove_question(ts):
        raise web.HTTPNotFound(text="no such question")
    return web.json_response({"deleted": ts})


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
    app.router.add_get("/api/insight/{id}/history", h_history_list)
    app.router.add_get("/api/insight/{id}/history/{ts}", h_history_get)
    app.router.add_delete("/api/insight/{id}/history/{ts}", h_history_delete)
    app.router.add_get("/api/prompts", h_prompts)
    app.router.add_put("/api/prompt/{id}", h_prompt_put)
    app.router.add_delete("/api/prompt/{id}", h_prompt_delete)
    app.router.add_post("/api/user_category", h_user_category_create)
    app.router.add_put("/api/user_category/{id}", h_user_category_put)
    app.router.add_delete("/api/user_category/{id}", h_user_category_delete)
    app.router.add_get("/api/insight/{id}/feedback", h_feedback_list)
    app.router.add_post("/api/insight/{id}/feedback", h_feedback_add)
    app.router.add_delete("/api/insight/{id}/feedback/{ts}", h_feedback_delete)
    app.router.add_get("/api/card_info", h_card_info)
    app.router.add_get("/api/questions", h_questions)
    app.router.add_post("/api/questions/answer", h_answer_question)
    app.router.add_get("/api/knowledge", h_knowledge)
    app.router.add_post("/api/knowledge/fact", h_knowledge_fact_add)
    app.router.add_delete("/api/knowledge/fact/{ts}", h_knowledge_fact_delete)
    app.router.add_post("/api/knowledge/question/{ts}/answer", h_knowledge_answer)
    app.router.add_post("/api/knowledge/question/{ts}/dismiss", h_knowledge_dismiss)
    app.router.add_delete("/api/knowledge/question/{ts}", h_knowledge_question_delete)
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
        # dashboard-card mini server (best-effort — panel works without it)
        try:
            runner = web.AppRunner(make_card_app())
            await runner.setup()
            await web.TCPSite(runner, BIND_HOST, CARD_PORT).start()
            app["card_runner"] = runner
            log.info("card server listening on %s:%d", BIND_HOST, CARD_PORT)
        except OSError as exc:
            log.warning("card server failed to start on port %d: %s", CARD_PORT, exc)

    async def on_cleanup(app: web.Application) -> None:
        runner = app.get("card_runner")
        if runner:
            await runner.cleanup()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    web.run_app(make_app(), host=BIND_HOST, port=BIND_PORT, print=None)
