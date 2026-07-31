#!/usr/bin/env python3
"""
brAIn ingress panel — aiohttp API + static asset server.

Routes
------
GET  /                       — dashboard HTML
GET  /style.css, /app.js     — static assets
GET  /api/status             — auth state, categories, job states, settings, usage
GET  /api/settings           — runtime settings + budget state + plans + the
                               add-on Configuration-tab defaults
PUT  /api/settings           — update {auto_enabled, plan, budget_percent,
                               refresh_hours, history_days, history_keep_runs,
                               history_keep_days, model, timeout_minutes}
                               (null = fall back to the add-on configuration)
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
PUT  /api/insight/{id}       — rename an ad-hoc Ask card {name, icon}
DELETE /api/card/{id}        — delete ANY card (shipped / user / ad-hoc): the
                               one the ✕ button calls
PUT  /api/card/{id}/tags     — replace a card's visible tags {tags: [...]}
GET  /api/findings           — the work list: what brAIn thinks is broken
POST /api/finding/{ts}/fix   — go fix it (the one tool-enabled Claude run)
POST /api/finding/{ts}/ignore — not a problem here; never raise it again
POST /api/finding/{ts}/done  — you fixed it yourself
POST /api/finding/{ts}/reopen — back onto the list
POST /api/finding/{ts}/snooze — remind me later; NOT a decision, so the
                                status is untouched and it comes back
POST /api/finding/{ts}/discuss — open it as a conversation in the chat
DELETE /api/finding/{ts}     — forget it (unlike ignore, it can return)
POST /api/memory/consolidate — file the inbox into memory.md now
GET  /api/insight/{id}/history       — past runs of a category (no html)
GET  /api/insight/{id}/history/{ts}  — one stored past run in full
DELETE /api/insight/{id}/history/{ts} — remove one past run
GET  /api/prompts            — per-category prompt/override listing
PUT  /api/prompt/{id}        — set title/icon/focus/enabled/hidden/refresh_hours
DELETE /api/prompt/{id}      — reset a category to shipped defaults (also
                               un-hides it)
POST /api/user_category      — create a user-defined recurring insight
PUT  /api/user_category/{id} — edit a user-defined insight
DELETE /api/user_category/{id} — delete one (definition + insight + history)
GET  /api/insight/{id}/feedback      — standing feedback for a category
POST /api/insight/{id}/feedback      — add feedback (steers future runs)
DELETE /api/insight/{id}/feedback/{ts} — drop one feedback entry
GET  /api/card_info          — dashboard-card /local mirror paths; also (re)syncs
                               the mirror
GET  /api/questions          — open analyst questions across insights
POST /api/questions/answer   — answer one (forwards to brain, if installed)
GET  /api/knowledge          — learned facts + question ledger + shared memory.md
POST /api/knowledge/fact     — teach a fact {text}; Claude merges it into memory.md
                               (its only home — never duplicated into the ledger)
DELETE /api/knowledge/fact/{ts}            — forget one fact
POST /api/knowledge/question/{ts}/answer   — answer an open question {answer}
POST /api/knowledge/question/{ts}/dismiss  — retire a question unanswered
DELETE /api/knowledge/question/{ts}        — forget a question (askable again)
POST /api/questions/dismiss  — dismiss from a card {insight_id, question} ("not relevant")
PUT  /api/memory             — save a manual edit of the memory file {text}

Runs on 0.0.0.0:8099. The HA Supervisor proxies the ingress URL into
/api/hassio_ingress/<token>/...; we therefore use only relative links in the
HTML and let aiohttp serve at /. Generation jobs run through a single-worker
queue so only one Claude invocation is in flight at a time (subscription
rate-limit friendly).

Dashboard cards are served by HA itself via a /local mirror: insight HTML is
copied to /config/www/brain/ (created on first use of the ▦ dialog,
kept in sync on save/delete), so Webpage cards are same-origin and work on
HTTP and HTTPS/Nabu Casa dashboards alike. File names embed a per-install
random token to keep the unauthenticated /local URLs unguessable.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from aiohttp import web

import addon_options
import card_tags
import categories as cat_mod
import chat_session
import cli_commands
import conversations
import engine
import feedback_store
import findings_store
import fixer
import hypotheses
import knowledge_store
import onboarding
import prompt_store
import settings_store
import terminal_proxy
import usage_store
import user_categories
from categories import CATEGORIES, SYSTEM_PROMPT, build_prompt, get_category

HERE = Path(__file__).resolve().parent
INSIGHTS_DIR = Path(os.environ.get("BRAIN_DIR", "/data/insights"))
ADDON_VERSION = os.environ.get("ADDON_VERSION", "dev")
REFRESH_HOURS = float(os.environ.get("BRAIN_REFRESH_HOURS", "24") or 0)
HISTORY_DAYS = int(os.environ.get("BRAIN_HISTORY_DAYS", "7") or 7)
# Dated per-run copies of each category insight (0 for either disables history)
HISTORY_KEEP_RUNS = int(os.environ.get("BRAIN_HISTORY_KEEP_RUNS", "40") or 40)
HISTORY_KEEP_DAYS = int(os.environ.get("BRAIN_HISTORY_KEEP_DAYS", "30") or 30)
# Candidate facts wait here for the consolidator. Same directory the
# terminal, voice reflection, and study sessions write to — one queue.
MEMORY_INBOX_DIR = Path(os.environ.get(
    "BRAIN_MEMORY_INBOX", "/config/.brain/memory/inbox"))
# The home's consolidated memory document — the same file `brain memory`
# reads in the terminal and the consolidator owns. Viewable and editable
# from the Memory tab; the panel queues changes rather than writing here
# directly, so the consolidator stays the single writer.
SHARED_MEMORY_FILE = Path(os.environ.get(
    "BRAIN_MEMORY_FILE", "/config/.brain/memory/memory.md"))
MAX_MEMORY_CHARS = 100_000
# Touched by the consolidator at the end of every successful pass (including
# a pass that found the inbox already empty). Its mtime is therefore the line
# between "discovered, still queued" and "discovered, now in the document" —
# which is what lets the Memory tab's discovery list drain without the panel
# having to track filing itself, and without caring whether the pass was run
# by the daemon, the CLI, or the button.
MEMORY_MARKER_FILE = Path(os.environ.get(
    "BRAIN_MEMORY_MARKER", "/config/.brain/memory/.last_consolidated"))

# Same skeleton `brain memory` starts from, so the CLI and the panel
# agree on the document's shape.
MEMORY_TEMPLATE = """# Home Memory

<!-- This file is user-editable — add, correct, or delete anything. -->

## Preferences

## Entity nicknames

## Household patterns

## Device notes
"""

# Whether the consolidator has pending work, surfaced to the panel so the
# Memory tab can say "queued" rather than pretending an edit landed
# instantly. The merge itself happens in the consolidator, not here.
MEMORY_STATE: dict = {"merging": False, "error": ""}
# Used to age a queue that has never been consolidated: on a fresh
# install "no marker" means "not yet", not "wedged".
_process_start = time.time()

# The consolidator's lock, which is also the only honest answer to "is a
# pass running right now". MEMORY_STATE only knows about passes this panel
# started; the daemon's own — daily, or early once the inbox passes 20 facts
# — used to happen entirely in silence, so the Memory tab could sit there
# showing a queue that was in fact being emptied as you watched.
MEMORY_DIR = Path(os.environ.get("BRAIN_MEMORY_DIR", "/config/.brain/memory"))
CONSOLIDATE_LOCK = MEMORY_DIR / ".consolidate.lock"


def _consolidation_running() -> bool:
    """True while any consolidator holds the lock.

    A *shared* lock is enough to ask the question and is the important
    detail: taking an exclusive one, even for a moment, would make this
    read-only status check something a real pass could block on.
    """
    try:
        fd = os.open(CONSOLIDATE_LOCK, os.O_RDONLY)
    except OSError:
        return False          # no lock file yet: nothing has ever run
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True           # somebody holds it exclusively
    finally:
        os.close(fd)

MODEL = os.environ.get("BRAIN_MODEL", "").strip()
TIMEOUT_S = int(float(os.environ.get("BRAIN_TIMEOUT_MIN", "8") or 8) * 60)

# The memory consolidator, run on demand from the Memory tab's "File into
# memory now". Normally a daemon on its own cadence (daily, or early once the
# inbox passes 20 pending facts) — this is the same pass, triggered by hand.
CONSOLIDATE_SCRIPT = os.environ.get(
    "BRAIN_CONSOLIDATE_SCRIPT", "/opt/scripts/brain-memory-consolidate.sh")
CONSOLIDATE_TIMEOUT_S = int(os.environ.get("BRAIN_CONSOLIDATE_TIMEOUT", "300"))
# The consolidator's "someone else holds the lock" exit code. It is not a
# failure of the pass, but it is not a filing either — reporting it as
# success is what made the button claim it had filed facts it hadn't.
CONSOLIDATE_BUSY_RC = 75

# One "Fix it" run. Wall-clock is the real guard, not turns: an agentic run
# that gets truncated mid-edit leaves the house half-changed.
FIX_MAX_TURNS = int(os.environ.get("BRAIN_FIX_MAX_TURNS", str(fixer.DEFAULT_MAX_TURNS)))
FIX_TIMEOUT_S = int(os.environ.get("BRAIN_FIX_TIMEOUT", "900"))
FIX_JOB_PREFIX = "fix-"

# ---------------------------------------------------------------------------
# Effective options
# ---------------------------------------------------------------------------
# ONE value per option, wherever you edit it. The add-on's own options (the
# Configuration tab) are the source of truth: the panel reads them live from
# the Supervisor and writes back to them, so a change in the ⚙ dialog shows
# up on the Configuration tab and vice versa — no restart, no drift.
#
# Precedence, highest first:
#   1. a local override in settings_store — which now only exists when the
#      panel could NOT reach the Supervisor, since a successful write clears
#      it. It wins so a save always takes effect; the next startup promotes
#      it into the add-on's options (see _options_sync)
#   2. the add-on's options, read live from the Supervisor (the normal case)
#   3. the env-derived constants above, captured from the options at startup


def _opt(name: str, fallback):
    val = settings_store.load().get(name)
    if val is None:
        val = addon_options.get(name)
    return fallback if val is None else val


def eff_refresh_hours() -> float:
    return float(_opt("refresh_hours", REFRESH_HOURS))


def eff_history_days() -> int:
    return int(_opt("history_days", HISTORY_DAYS))


def eff_keep_runs() -> int:
    return int(_opt("history_keep_runs", HISTORY_KEEP_RUNS))


def eff_keep_days() -> int:
    return int(_opt("history_keep_days", HISTORY_KEEP_DAYS))


def eff_model() -> str:
    return str(_opt("model", MODEL))


def eff_timeout_s() -> int:
    return int(_opt("timeout_minutes", TIMEOUT_S / 60) * 60)


def startup_options() -> dict:
    """The option values this process started with (from the environment).

    Also what an emptied ⚙ field reverts to.
    """
    return {
        "refresh_hours": int(REFRESH_HOURS),
        "history_days": HISTORY_DAYS,
        "history_keep_runs": HISTORY_KEEP_RUNS,
        "history_keep_days": HISTORY_KEEP_DAYS,
        "model": MODEL,
        "timeout_minutes": TIMEOUT_S // 60,
    }


def addon_defaults() -> dict:
    """The add-on's Configuration-tab values, live from the Supervisor.

    Falls back to the startup values when the Supervisor can't be reached.
    """
    startup = startup_options()
    opts = addon_options.snapshot()
    if opts is None:
        return startup
    live = {}
    for name, value in startup.items():
        current = opts.get(addon_options.OPTION_KEYS[name])
        live[name] = value if current is None else current
    return live


def effective_options() -> dict:
    """What generation actually uses right now — never None, never blank.

    This is what the ⚙ dialog renders in its fields: with add-on options in
    play every field has a real value, so nothing shows as an empty box
    whose meaning you have to guess.
    """
    return {
        "refresh_hours": int(eff_refresh_hours()),
        "history_days": eff_history_days(),
        "history_keep_runs": eff_keep_runs(),
        "history_keep_days": eff_keep_days(),
        "model": eff_model(),
        "timeout_minutes": eff_timeout_s() // 60,
    }


BIND_HOST = "0.0.0.0"
BIND_PORT = 8099
# Per-install secret embedded in /local card-mirror file names.
CARD_TOKEN_FILE = Path(
    os.environ.get("BRAIN_SECRETS", "/data/secrets")) / "card_token"
MAX_HTML_BYTES = 400_000
MAX_CUSTOM_KEPT = 12

logging.basicConfig(
    level=getattr(logging, os.environ.get("BRAIN_LOG_LEVEL", "info").upper(), logging.INFO),
    format="[insights] %(levelname)s %(message)s",
)
log = logging.getLogger("brain")

# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------
# JOBS[insight_id] = {state, phase, started_at, error, question}
JOBS: dict[str, dict] = {}
QUEUE: asyncio.Queue[str] = asyncio.Queue()
AUTH_CHECK: dict = {"state": "unchecked", "error": "", "checked_at": 0}


ACTIVE_STATES = ("queued", "collecting", "generating", "parsing", "fixing")


def _job_active(job_id: str) -> bool:
    return JOBS.get(job_id, {}).get("state") in ACTIVE_STATES


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
    """The cards this home actually has, in creation order.

    Empty until onboarding finishes. A fresh install ships NO cards: brAIn
    studies the home first and then proposes cards grounded in what it
    found, because a generic card about a house it has never looked at is
    noise on every run.

    Shipped cards the user removed are left out everywhere this feeds —
    the dashboard, "Refresh all", and the scheduler — so a removed card is
    as gone as a deleted one, minus the part where its definition ships in
    the code and can be restored.
    """
    if not onboarding.is_onboarded():
        return []
    return prompt_store.visible_categories() + user_categories.load()


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
        # deleted mid-write) and files belonging to a removed shipped card
        # are skipped rather than shown as ghost cards
        if (isinstance(obj, dict) and obj.get("id")
                and not stem.startswith("user-") and not get_category(stem)):
            custom.append(obj)
    custom.sort(key=lambda i: i.get("generated_at", ""), reverse=True)
    return out + custom


def save_insight(insight: dict) -> None:
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _insight_path(insight["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(insight, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    _mirror_card(insight)  # keep the /local dashboard-card copy fresh
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
    if eff_keep_runs() <= 0 or eff_keep_days() <= 0:
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
    """Keep at most eff_keep_runs() files, none older than eff_keep_days()
    (age judged by the filename stamp — lexicographic order matches time)."""
    keep_runs, keep_days = eff_keep_runs(), eff_keep_days()
    files = sorted(hdir.glob("*.json"), key=lambda p: p.name, reverse=True)
    cutoff = time.strftime(
        "%Y-%m-%dT%H-%M-%S", time.localtime(time.time() - keep_days * 86400))
    for i, path in enumerate(files):
        if i < keep_runs and path.stem >= cutoff:
            continue
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Memory hand-off (brain integration, /share inbox fallback)
# ---------------------------------------------------------------------------

async def _call_ha_service(service: str, data: dict) -> bool:
    """Call a brain.<service> HA service; False when it isn't there.

    The integration ships with the brAIn add-on and may simply not
    be installed — every failure here is expected and non-fatal.
    """
    try:
        import ha_data  # deferred so the module loads without aiohttp in tests
        await ha_data.call_service(service, data)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort hand-off
        log.debug("brain.%s unavailable: %s", service, exc)
        return False


async def _submit_memory(fact: str, source: str = "insights") -> None:
    await asyncio.to_thread(_queue_memory_fact, fact, source)


async def _submit_answer(question: str, answer: str) -> None:
    """An answered question is durable knowledge — but what gets remembered
    is the ANSWER as a plain statement, not the Q/A pair. Storing
    "Q: ... -> A: ..." is what made the old memory unreadable."""
    await asyncio.to_thread(
        _queue_memory_fact, f"{question.rstrip('?')}: {answer}", "homeowner", "high")


# ---------------------------------------------------------------------------
# Generation worker
# ---------------------------------------------------------------------------

def _record_usage(result: dict, insight_id: str) -> None:
    """Book a finished Claude invocation's tokens against the session budget
    (best-effort — usage accounting must never break a run)."""
    try:
        tokens = usage_store.tokens_from_meta(result.get("meta") or {})
        usage_store.record_run(tokens, insight_id)
    except Exception as exc:  # noqa: BLE001
        log.debug("usage recording failed: %s", exc)


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


def _model_findings(value, max_items: int = 3) -> list[dict]:
    """The model's ``findings`` array, ready for ``findings_store.add_many``.

    Only the shape the store can't be expected to know about is handled
    here — a list, capped, tolerating a bare string per finding (a model
    that drops to the simpler form should still get its problem onto the
    work list). Every field's validation belongs to the store, which owns
    the constants and applies them to the study-session path too.
    """
    if not isinstance(value, list):
        return []
    out: list[dict] = []
    for item in value[:max_items]:
        if isinstance(item, str):
            item = {"text": item}
        if isinstance(item, dict):
            out.append(item)
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
        bundle = await ha_data.collect_bundle(cat, eff_history_days(), question=question)
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
                            ("generated_at", "title", "summary", "highlights", "learned")}
            except (OSError, ValueError):
                pass
        prompt = build_prompt(cat, bundle, question=question, feedback=feedback,
                              hypothesis_budget=hypotheses.budget(),
                              knowledge=knowledge, previous=previous,
                              findings=findings_store.prompt_block())
        result = await asyncio.to_thread(
            engine.run_claude, prompt, SYSTEM_PROMPT, eff_model(),
            eff_timeout_s(),
        )
        _record_usage(result, insight_id)
        if not result["ok"]:
            raise RuntimeError(result["error"] or "generation failed")

        _set_job(insight_id, state="parsing")
        obj = engine.extract_json(result["text"])
        if not obj or not isinstance(obj.get("html"), str) or not obj.get("title"):
            raise RuntimeError("Claude returned an unparseable insight (no JSON/html)")
        html = obj["html"]
        if len(html.encode()) > MAX_HTML_BYTES:
            raise RuntimeError("generated visualization too large")
        highlights = obj.get("highlights")
        if not isinstance(highlights, list):
            highlights = []
        # Hypotheses, not open questions. propose() enforces the cap and the
        # never-twice rule in code — the prompt states the budget, but a model
        # that ignores it must not be able to grow the queue anyway. Anything
        # it declines is dropped rather than shown, so the card never displays
        # a guess the queue didn't accept.
        questions = []
        for claim in _clean_strings(obj.get("hypotheses"), 3, 300):
            if hypotheses.propose(claim, cat["id"]) is None:
                log.info("dropping hypothesis (known, or queue full): %s", claim)
                continue
            questions.append(claim)
        learned = _clean_strings(obj.get("learned"), 3, 500)
        # Findings are a work list, not part of the card: what this run
        # reported lives in the store, which is the one place that knows
        # whether it has since been fixed or dismissed. Storing a copy on
        # the card would be a snapshot guaranteed to go stale.
        filed = findings_store.add_many([
            {**f, "source": cat["id"], "source_title": cat.get("title", "Insight")}
            for f in _model_findings(obj.get("findings"))])
        tags = card_tags.clean_tags(_clean_strings(obj.get("tags"), 4, 24))
        insight = {
            "id": insight_id,
            "category": cat["id"] if question is None else "custom",
            "icon": cat.get("icon", "✨"),
            "category_title": cat.get("title", "Custom"),
            "question": question,
            "title": str(obj.get("title", ""))[:120],
            # concise contract: summaries are 1-2 sentences — a long one is
            # a model miss, so a hard cap keeps cards scannable regardless
            "summary": str(obj.get("summary", ""))[:600],
            "highlights": highlights[:6],
            "questions": questions,
            "learned": learned,
            "tags": tags,
            "focus_used": cat.get("focus", "") if question is None else "",
            "html": html,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "meta": result.get("meta", {}),
        }
        save_insight(insight)
        # Learn the durable discoveries: store NEW ones in our own knowledge
        # base (dedup by content) and hand those on to the home's shared
        # memory. Already-known ones are silently swallowed — the model was
        # told not to repeat them, this enforces it.
        for fact in learned:
            _, created = knowledge_store.add_fact(
                fact, source="insights", category=cat["id"])
            if created:
                await _submit_memory(fact)
        _set_job(insight_id, state="done", error="")
        log.info("insight %s generated (%s)%s", insight_id, insight["title"],
                 f", {len(filed)} new finding(s)" if filed else "")
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        log.warning("insight %s failed: %s", insight_id, exc)
        _set_job(insight_id, state="error", error=str(exc)[:500])


# ---------------------------------------------------------------------------
# Fix worker — the one path that lets Claude change the house
# ---------------------------------------------------------------------------

async def _run_fix(job_id: str) -> None:
    """Fix one finding, agentically, because somebody pressed Fix on it.

    Shares the generation queue on purpose: one Claude invocation at a time
    across the whole add-on is what keeps a subscription's rate limit
    intact, and a fix run is far too expensive to let race a card refresh.
    """
    job = JOBS.get(job_id, {})
    ts = int(job.get("finding_ts") or 0)
    finding = findings_store.get(ts)
    if finding is None:
        _set_job(job_id, state="error", error="that finding is gone")
        return
    try:
        # the route already claimed it on disk — this is the in-memory half
        _set_job(job_id, state="fixing", error="")
        memory = await asyncio.to_thread(_read_shared_memory)
        prompt = fixer.build_prompt(finding, memory=memory)
        result = await asyncio.to_thread(
            engine.run_agent, prompt, fixer.FIX_SYSTEM, eff_model(),
            FIX_TIMEOUT_S, FIX_MAX_TURNS)
        _record_usage(result, job_id)
        if not result["ok"]:
            raise RuntimeError(result["error"] or "the fix run failed")

        parsed = fixer.parse_result(result["text"])
        if parsed["needs_you"]:
            status = "needs_you"
        elif parsed["ok"]:
            status = "fixed"
        else:
            status = "failed"
        findings_store.set_status(ts, status, result=fixer.result_text(parsed),
                                  changed=parsed["changed"])
        # A change to the house is durable knowledge about it — the next
        # analysis must not rediscover a problem brAIn itself resolved.
        if status == "fixed" and parsed["changed"]:
            await _submit_memory(
                f"brAIn fixed this on {time.strftime('%Y-%m-%d')}: "
                f"{finding['text']} — {'; '.join(parsed['changed'])}",
                source="fix")
        # Anything it noticed on the way in becomes its own finding rather
        # than an edit it was not asked to make.
        findings_store.add_many([
            {"text": extra, "source": "fix",
             "source_title": f"Noticed while fixing “{finding['text']}”"}
            for extra in parsed["also_found"]])
        _set_job(job_id, state="done", error="")
        log.info("finding %s → %s", ts, status)
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        log.warning("fix for finding %s failed: %s", ts, exc)
        findings_store.set_status(
            ts, "failed",
            result=f"The fix run did not complete: {str(exc)[:400]}")
        _set_job(job_id, state="error", error=str(exc)[:500])


async def _worker() -> None:
    while True:
        job_id = await QUEUE.get()
        try:
            if JOBS.get(job_id, {}).get("kind") == "fix":
                await _run_fix(job_id)
            else:
                await _generate(job_id)
        finally:
            QUEUE.task_done()


def _parse_generated_at(generated_at: str) -> float | None:
    try:
        return time.mktime(time.strptime(generated_at[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return None


def _schedule_due(times: list[str], generated_at: str, now: float) -> bool:
    """Fixed daily run times ("HH:MM", local): due when the most recent
    scheduled instant has passed and the stored insight predates it."""
    lt = time.localtime(now)
    passed: list[float] = []
    for t in times:
        try:
            hh, mm = t.split(":")
            hh, mm = int(hh), int(mm)
        except ValueError:
            continue
        # today's and yesterday's occurrence; mktime normalizes day-1
        for day_off in (0, -1):
            stamp = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + day_off,
                                 hh, mm, 0, 0, 0, -1))
            if stamp <= now:
                passed.append(stamp)
    if not passed:
        return False
    last_scheduled = max(passed)
    gen = _parse_generated_at(generated_at) if generated_at else None
    return gen is None or gen < last_scheduled


def _refresh_due(eff: dict, generated_at: str, now: float) -> bool:
    """True when a category's stored insight should regenerate.

    A non-empty per-category schedule (fixed daily times) takes precedence;
    otherwise the age-based interval applies (per-category refresh_hours
    override, else global REFRESH_HOURS; 0 disables). A missing or
    unparseable timestamp counts as ancient, so first boot generates every
    enabled category."""
    if not eff.get("enabled", True):
        return False
    schedule = eff.get("schedule")
    if isinstance(schedule, list) and schedule:
        return _schedule_due(schedule, generated_at, now)
    hours = eff.get("refresh_hours")
    if hours is None:
        hours = eff_refresh_hours()
    if hours <= 0:
        return False
    if not generated_at:
        return True
    gen = _parse_generated_at(generated_at)
    if gen is None:
        return True
    return now - gen >= hours * 3600


async def _scheduler() -> None:
    """Per-category auto-refresh: each tick, queue any enabled category whose
    stored insight has outlived its effective refresh interval (or whose
    scheduled run time has passed). Respects the ⚙ master switch and the
    session token budget — manual generation is never gated here."""
    budget_logged = False
    while True:
        await asyncio.sleep(60)
        # Fold in what the CLI side found. This belongs on the tick rather
        # than on the Findings tab's own request: study sessions are the
        # other producer, and the badge that tells you to go look is served
        # by /api/status. Sweeping only on tab open made that circular — the
        # badge couldn't count a finding until you'd already visited.
        try:
            swept = await asyncio.to_thread(findings_store.sweep_inbox)
            if swept:
                log.info("swept %d finding(s) from study sessions", swept)
        except Exception as exc:  # never let this kill the loop
            log.debug("findings sweep failed: %s", exc)
        if not engine.get_auth():
            continue
        settings = settings_store.load()
        if not settings["auto_enabled"]:
            continue
        # Nothing is scheduled before onboarding: there are no cards, and
        # generating one would be the canned-defaults behaviour this
        # replaced.
        if not settings.get("onboarded"):
            continue
        budget = usage_store.budget_state(settings)
        if budget["blocked"]:
            if not budget_logged:
                log.info(
                    "auto-refresh paused: session usage %.0f%% ≥ budget %d%% (%s)",
                    budget["used_percent"], budget["budget_percent"],
                    budget["source"])
                budget_logged = True
            continue
        budget_logged = False
        stored = {i["id"]: i.get("generated_at", "") for i in load_insights()}
        now = time.time()
        for cat in all_categories():
            eff = resolve_category(cat["id"]) or cat
            if _refresh_due(eff, stored.get(cat["id"], ""), now) and _enqueue(cat["id"]):
                log.info("auto-refresh: queued %s", cat["id"])


def _enqueue(job_id: str, question: str | None = None, **fields) -> bool:
    """Queue one unit of Claude work. ``fields`` carries per-kind state
    (``kind="fix"`` plus its ``finding_ts``); everything else is a card."""
    if _job_active(job_id):
        return False
    _set_job(job_id, state="queued", error="", question=question,
             started_at=time.time(), kind=fields.pop("kind", "insight"), **fields)
    QUEUE.put_nowait(job_id)
    return True


OPTIONS_POLL_SECONDS = 15


async def _options_sync() -> None:
    """Adopt the add-on's own options as the single source of truth.

    One-time migration: any override the ⚙ dialog stored back when the panel
    kept its own copy is promoted into the add-on's options (it was the
    winning value, so behaviour doesn't change) and then dropped locally.
    After that there is exactly one place each option lives, and editing it
    on the Configuration tab or in the panel is the same edit.
    """
    if not addon_options.available():
        log.info("no Supervisor API — generation options stay panel-local")
        return
    if await addon_options.refresh(force=True) is None:
        log.warning("could not read add-on options — using panel-local values")
        return
    overrides = settings_store.option_overrides()
    if overrides:
        try:
            await addon_options.write(
                {k: ("" if k == "model" and v is None else v)
                 for k, v in overrides.items()})
        except addon_options.OptionsError as exc:
            log.warning("could not migrate panel settings into add-on "
                        "options (%s) — keeping them panel-local", exc)
            return
        settings_store.clear_option_overrides()
        log.info("migrated %d panel setting(s) into the add-on's options: %s",
                 len(overrides), ", ".join(sorted(overrides)))
    log.info("generation options synced with the add-on Configuration tab")


async def _options_poller() -> None:
    """Pick up Configuration-tab edits without waiting for a restart."""
    while True:
        await asyncio.sleep(OPTIONS_POLL_SECONDS)
        try:
            await addon_options.refresh(force=True)
        except Exception as exc:  # never let a transient blip kill the loop
            log.debug("add-on options poll failed: %s", exc)


async def _check_auth_bg() -> None:
    AUTH_CHECK.update(state="checking", error="")
    result = await asyncio.to_thread(engine.validate_auth)
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
            "schedule": c.get("schedule"),
            "user": True,
            "job": {k: JOBS.get(c["id"], {}).get(k) for k in ("state", "error")},
        }
    eff = prompt_store.effective_category(c["id"]) or c
    return {
        "id": c["id"],
        "title": eff.get("title", c["title"]),
        "icon": eff.get("icon", c["icon"]),
        "default_title": c["title"],
        "default_icon": c["icon"],
        "description": c["description"],
        "generated_at": insights.get(c["id"]),
        "focus": eff.get("focus", c["focus"]),
        "default_focus": c["focus"],
        "focus_overridden": "focus" in eff.get("overridden", []),
        "renamed": bool({"title", "icon"} & set(eff.get("overridden", []))),
        "enabled": eff.get("enabled", True),
        "refresh_hours": eff.get("refresh_hours"),
        "schedule": eff.get("schedule"),
        "job": {k: JOBS.get(c["id"], {}).get(k) for k in ("state", "error")},
    }


async def h_status(request: web.Request) -> web.Response:
    auth = engine.get_auth()
    insights = {i["id"]: i.get("generated_at") for i in load_insights()}
    settings = settings_store.load()
    return web.json_response({
        "version": ADDON_VERSION,
        "authenticated": bool(auth),
        "auth_type": auth["type"] if auth else None,
        "auth_source": auth.get("source") if auth else None,
        "auth_check": AUTH_CHECK,
        "model": eff_model() or "default",
        "refresh_hours": eff_refresh_hours(),
        "history_days": eff_history_days(),
        "settings": settings,
        "usage": usage_store.budget_state(settings),
        "categories": [_category_status(c, insights) for c in all_categories()],
        # the Findings tab's badge: problems still waiting on a decision
        "findings_open": findings_store.open_count(),
        # `question` lets the panel label an ad-hoc "Ask" card (and retry it)
        # while it's still generating, before any insight exists to read.
        "jobs": {jid: {k: j.get(k) for k in ("state", "error", "question")}
                 for jid, j in JOBS.items()},
        "queue_size": QUEUE.qsize(),
    })


async def h_insights(request: web.Request) -> web.Response:
    # Tags are resolved at read time, not stored: a hand-edited tag is a diff
    # against whatever the latest run wrote, so a new run's new tag still
    # appears while the one you threw away stays gone.
    def listing() -> list[dict]:
        insights = load_insights()
        # one read of the edits file for the whole list, not one per card
        edits = card_tags.load_edits()
        for ins in insights:
            ins["tags"] = card_tags.effective_tags(ins, edits)
        return insights

    return web.json_response({"insights": await asyncio.to_thread(listing)})


# "learn about the boiler", "study my energy use" — the ask bar's second verb.
# A study session is a different thing from a question (minutes not seconds,
# tools not a snapshot, memory not a card), but making people find a second
# input for it just meant nobody ever ran one.
LEARN_RE = re.compile(
    r"^\s*(?:go\s+|please\s+)?(?:learn|study|research|figure\s+out)\b"
    r"(?:\s+(?:about|more\s+about|up\s+on|on))?\s*",
    re.IGNORECASE)


async def h_generate(request: web.Request) -> web.Response:
    body = await request.json()
    question = (body.get("question") or "").strip() or None
    if question:
        if len(question) > 500:
            raise web.HTTPBadRequest(text="question too long")
        match = LEARN_RE.match(question)
        if match:
            topic = question[match.end():].strip().rstrip("?.!")
            queued = await asyncio.to_thread(onboarding.request_study, topic)
            return web.json_response({"queued": [], "learning": queued})
        # Second-resolution ids collide when two questions are asked in the
        # same second — step past any live job so neither ask is swallowed.
        stamp = int(time.time())
        while _job_active(f"custom-{stamp}"):
            stamp += 1
        insight_id = f"custom-{stamp}"
        _enqueue(insight_id, question=question)
        return web.json_response({"queued": [insight_id]})
    cat_id = body.get("category", "")
    if not resolve_category(cat_id) or prompt_store.is_hidden(cat_id):
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
    _unmirror_card(insight_id)
    JOBS.pop(insight_id, None)
    return web.json_response({"deleted": insight_id})


async def h_rename_insight(request: web.Request) -> web.Response:
    """Rename a stored insight's card label / icon (ad-hoc Ask cards).

    Category cards take their name from the category, so those are renamed
    through /api/prompt/{id} or /api/user_category/{id} instead — this is
    the one path for cards that have no definition behind them.
    """
    insight_id = request.match_info["id"]
    path = _insight_path(insight_id)
    try:
        insight = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text="no such insight")
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    if "name" in body:
        name = str(body.get("name") or "").strip()[:prompt_store.MAX_TITLE]
        if not name:
            raise web.HTTPBadRequest(text="name required")
        insight["category_title"] = name
    if "icon" in body:
        insight["icon"] = (str(body.get("icon") or "").strip()[:prompt_store.MAX_ICON]
                           or "✨")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(insight, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return web.json_response({
        "id": insight_id,
        "name": insight.get("category_title", ""),
        "icon": insight.get("icon", "✨"),
    })


def _purge_card_data(card_id: str) -> None:
    """Erase everything stored for one card: insight, past runs, feedback."""
    try:
        _insight_path(card_id).unlink()
    except OSError:
        pass
    _unmirror_card(card_id)
    shutil.rmtree(_history_dir(card_id), ignore_errors=True)
    feedback_store.clear(card_id)
    card_tags.forget(card_id)
    JOBS.pop(card_id, None)


async def h_delete_card(request: web.Request) -> web.Response:
    """Delete any card, whatever kind it is — one endpoint for one ✕ button.

    Deleted means deleted. A shipped card's definition lives in the code and
    can't be erased, so it is marked hidden — but that is an implementation
    detail, not an offer: the panel no longer keeps a graveyard of removed
    cards to restore from. Every home gets the cards brAIn proposed for
    *that* home, and the way to get one back is to ask for it again.
    """
    card_id = request.match_info["id"]
    if get_category(card_id):
        prompt_store.save_override(card_id, {"hidden": True})
        await asyncio.to_thread(_purge_card_data, card_id)
        return web.json_response({"deleted": card_id})
    if user_categories.get(card_id):
        user_categories.delete(card_id)
        await asyncio.to_thread(_purge_card_data, card_id)
        return web.json_response({"deleted": card_id})
    # an ad-hoc Ask that failed (or is still running) has no stored insight
    # yet — its card is the job, so clearing the job clears the card
    if not _insight_path(card_id).exists() and card_id not in JOBS:
        raise web.HTTPNotFound(text="no such card")
    await asyncio.to_thread(_purge_card_data, card_id)
    return web.json_response({"deleted": card_id})


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
        "title": eff["title"],
        "icon": eff["icon"],
        "default_title": c["title"],
        "default_icon": c["icon"],
        "default_focus": c["focus"],
        "focus": eff["focus"],
        "overridden": eff["overridden"],
        "enabled": eff["enabled"],
        "hidden": eff["hidden"],
        "refresh_hours": eff["refresh_hours"],
        "schedule": eff["schedule"],
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
    # title/icon: a shipped card can be renamed like any other; blanking the
    # field (or typing the shipped name back) drops the override
    if "title" in body:
        title = body["title"]
        if not isinstance(title, str):
            raise web.HTTPBadRequest(text="title must be a string")
        title = title.strip()[:prompt_store.MAX_TITLE]
        fields["title"] = title if title and title != cat["title"] else None
    if "icon" in body:
        icon = body["icon"]
        if not isinstance(icon, str):
            raise web.HTTPBadRequest(text="icon must be a string")
        icon = icon.strip()[:prompt_store.MAX_ICON]
        fields["icon"] = icon if icon and icon != cat["icon"] else None
    if "hidden" in body:
        if not isinstance(body["hidden"], bool):
            raise web.HTTPBadRequest(text="hidden must be a boolean")
        # visible is the default — only a removal is worth storing
        fields["hidden"] = True if body["hidden"] else None
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
    if "schedule" in body:
        try:
            fields["schedule"] = settings_store.clean_schedule(body["schedule"])
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
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
    await asyncio.to_thread(_purge_card_data, cat_id)
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


# -- dashboard cards ----------------------------------------------------------
# Cards are served by Home Assistant itself via the /local mirror below. The
# per-install random token is embedded in the mirror file names, keeping the
# unauthenticated /local URLs unguessable.

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


# -- /local card mirror -------------------------------------------------------
# The mirror writes each stored insight's HTML into /config/www/brain/,
# where Home Assistant ITSELF serves it at /local/… — same origin as every
# dashboard, so the card works over HTTP, HTTPS, and Nabu Casa alike. Opt-in
# by first use: the folder is only created the first time the ▦ dialog is
# opened; from then on save/delete keep it in sync. File names embed the
# per-install card token (HA serves /local without auth).

WWW_CARD_DIR = Path(os.environ.get(
    "BRAIN_WWW_DIR", "/config/www/brain"))


def _card_file_name(insight_id: str) -> str:
    return f"{insight_id}-{get_card_token()}.html"


def _mirror_card(insight: dict) -> None:
    """Best-effort mirror of one insight; a no-op until the dir exists."""
    if not WWW_CARD_DIR.is_dir():
        return
    html = insight.get("html")
    insight_id = str(insight.get("id") or "")
    if not isinstance(html, str) or not html or not _SAFE_ID.match(insight_id):
        return
    try:
        path = WWW_CARD_DIR / _card_file_name(insight_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(html + _CARD_RELOAD_SNIPPET, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.debug("card mirror write failed: %s", exc)


def _unmirror_card(insight_id: str) -> None:
    if not WWW_CARD_DIR.is_dir():
        return
    try:
        (WWW_CARD_DIR / _card_file_name(insight_id)).unlink(missing_ok=True)
    except OSError:
        pass


def _sync_card_mirrors() -> bool:
    """Create the mirror dir and bring it in line with the stored insights
    (runs when the ▦ dialog opens). False when /config/www isn't writable —
    the dialog then explains cards are unavailable."""
    try:
        WWW_CARD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.debug("cannot create card mirror dir: %s", exc)
        return False
    insights = [i for i in load_insights()
                if isinstance(i.get("html"), str) and i["html"]]
    keep = {_card_file_name(i["id"]) for i in insights}
    try:
        for stale in WWW_CARD_DIR.glob("*.html"):
            if stale.name not in keep:
                stale.unlink()
    except OSError:
        pass
    for ins in insights:
        _mirror_card(ins)
    return True


async def h_card_info(request: web.Request) -> web.Response:
    www_ok = await asyncio.to_thread(_sync_card_mirrors)
    return web.json_response({
        "www_cards": www_ok,
        "local_dir": f"/local/{WWW_CARD_DIR.name}",
        "local_suffix": f"-{get_card_token()}.html",
    })


# -- findings: what's broken, and what brAIn did about it -------------------

def _finding_ts(request: web.Request) -> int:
    try:
        return int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad finding id")


def _finding_or_404(request: web.Request) -> dict:
    finding = findings_store.get(_finding_ts(request))
    if finding is None:
        raise web.HTTPNotFound(text="no such finding")
    return finding


async def h_findings(request: web.Request) -> web.Response:
    # The scheduler owns ingestion; sweeping here too is only about latency,
    # so opening the tab right after a study session finishes doesn't wait
    # out the tick. Both are idempotent, and an empty inbox costs one glob.
    def listing() -> dict:
        findings_store.sweep_inbox()
        return findings_store.listing()

    return web.json_response(await asyncio.to_thread(listing))


# The lifecycle buttons: each is one status transition and the same reply.
# Keeping them as one handler means adding a verb is a line here rather than
# a handler, a route, and two docstrings that can disagree with each other.
FINDING_VERBS = {
    # "Not a problem here." Sticky: dismissed findings are fed back into
    # every future analysis, so it is never raised again rather than
    # re-dismissed weekly.
    "ignore": ("ignored", ""),
    # "I handled it myself" — the ending for anything needing hands.
    "done": ("fixed", "Marked done by you."),
    "reopen": ("open", ""),
}


async def h_finding_verb(request: web.Request) -> web.Response:
    verb = request.match_info["verb"]
    if verb not in FINDING_VERBS:
        raise web.HTTPNotFound(text="no such action")
    finding = _finding_or_404(request)
    status, result = FINDING_VERBS[verb]

    def settle() -> dict:
        findings_store.set_status(finding["ts"], status, result=result)
        return findings_store.listing()

    payload = await asyncio.to_thread(settle)
    if verb == "done":
        # resolving it yourself is durable knowledge about this home
        await _submit_memory(
            f"Resolved on {time.strftime('%Y-%m-%d')}: {finding['text']}",
            source="homeowner")
    return web.json_response(payload)


# "Remind me later" in the words people actually use. The list is short on
# purpose: this is a snooze, not a calendar.
SNOOZE_CHOICES = {
    "hour": 3600,
    "tomorrow": 86400,
    "week": 7 * 86400,
    "month": 30 * 86400,
}


async def h_finding_snooze(request: web.Request) -> web.Response:
    """Take a finding off the list for a while — without settling it.

    Kept apart from the ignore verb on purpose. Dismissing is permanent and
    is fed back into every future analysis so the same non-problem is never
    raised again; using that for "not right now" would quietly throw away a
    real problem you meant to come back to.
    """
    finding = _finding_or_404(request)
    body = await request.json() if request.can_read_body else {}
    choice = str((body or {}).get("for") or "tomorrow")
    if choice == "now":
        until = 0                      # bring it back immediately
    elif choice in SNOOZE_CHOICES:
        until = int(time.time()) + SNOOZE_CHOICES[choice]
    else:
        raise web.HTTPBadRequest(
            text=f"snooze for one of: now, {', '.join(SNOOZE_CHOICES)}")

    def settle() -> dict:
        findings_store.snooze(finding["ts"], until)
        return findings_store.listing()

    return web.json_response(await asyncio.to_thread(settle))


# What the chat is handed when you press Discuss. It says "look, don't
# touch": the discussion is for understanding the thing, and Fix it is still
# the only button that authorises a change — which stays on screen while you
# talk, so agreeing to it is one press away rather than a trip back.
DISCUSS_PROMPT = """I want to talk about something you flagged as broken in my home.

**{text}**
{detail}{fix}{entity}
Severity: {severity}

Look into it and tell me what is actually going on — check the current state
and the history before you answer, and say plainly whether you think it is
really a problem here. Do not change anything yet; I will decide."""


async def h_finding_discuss(request: web.Request) -> web.Response:
    """Open this finding as a conversation in the chat terminal."""
    finding = _finding_or_404(request)
    prompt = DISCUSS_PROMPT.format(
        text=finding["text"],
        detail=f"\n{finding['detail']}\n" if finding["detail"] else "\n",
        fix=f"\nWhat you suggested: {finding['fix']}\n" if finding["fix"] else "",
        entity=f"\nEntity: {finding['entity_id']}\n" if finding["entity_id"] else "",
        severity=finding["severity"],
    )
    session = _chat()
    try:
        await session.send(prompt)
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=str(exc))
    return web.json_response({"ok": True, "finding": finding})


async def h_finding_fix(request: web.Request) -> web.Response:
    """"Yes, go fix this." Queues the one tool-enabled run in the panel."""
    finding = _finding_or_404(request)
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    job_id = f"{FIX_JOB_PREFIX}{finding['ts']}"
    # The in-memory job is the authority on "a fix is running" — it is what
    # actually knows. The stored status is the copy the browser renders, and
    # any left behind by a dead process is reconciled at startup.
    if finding["status"] == "fixing" or not _enqueue(
            job_id, kind="fix", finding_ts=finding["ts"]):
        raise web.HTTPConflict(text="already being fixed")

    def claim() -> dict:
        findings_store.set_status(finding["ts"], "fixing", result="")
        return findings_store.listing()

    return web.json_response(await asyncio.to_thread(claim))


async def h_finding_delete(request: web.Request) -> web.Response:
    """Forget it entirely — unlike Ignore, it can be reported again."""
    finding = _finding_or_404(request)

    def forget() -> dict:
        findings_store.remove(finding["ts"])
        return findings_store.listing()

    return web.json_response(await asyncio.to_thread(forget))


# -- card tags --------------------------------------------------------------

async def h_card_tags_put(request: web.Request) -> web.Response:
    """Replace one card's visible tags. Stored as a diff — see card_tags."""
    card_id = request.match_info["id"]
    try:
        insight = json.loads(_insight_path(card_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text="no such card")
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("tags"), list):
        raise web.HTTPBadRequest(text="tags must be a list of strings")
    tags = await asyncio.to_thread(card_tags.set_tags, card_id, insight, body["tags"])
    return web.json_response({"id": card_id, "tags": tags})


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

    # Cards carry the claim's text, not its id, so resolve it in the queue
    # and settle it there too. Without this the card looked answered while
    # the guess stayed open in Memory until it expired a fortnight later.
    pending = hypotheses.find_open(question)
    if pending:
        hypotheses.confirm(pending["ts"])

    knowledge_store.add_fact(f"{question.rstrip('?')}: {answer}",
                             source="homeowner", category=insight.get("category", ""))
    await _submit_answer(question, answer)
    _retire_question_everywhere(question)
    return web.json_response({"answered": True})


async def h_dismiss_question_card(request: web.Request) -> web.Response:
    """"Not relevant" from an insight card: retire the question everywhere
    and mark it dismissed in the ledger so the analyst learns it was a
    dead end and never asks it (or close variants) again."""
    body = await request.json()
    insight_id = str(body.get("insight_id") or "")
    question = str(body.get("question") or "").strip()
    if not question:
        raise web.HTTPBadRequest(text="question required")
    path = _insight_path(insight_id)
    try:
        insight = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text="no such insight")
    questions = [q for q in (insight.get("questions") or []) if isinstance(q, str)]
    if question not in questions:
        raise web.HTTPNotFound(text="no such open question")
    # Same as the confirm path: the card only knows the text, so look the
    # claim up in the queue and reject it there.
    pending = hypotheses.find_open(question)
    if pending:
        hypotheses.reject(pending["ts"])

    entry = knowledge_store.record_question(question, insight.get("category", ""))
    if entry and entry.get("status") != "answered":
        knowledge_store.dismiss_question(entry["ts"])
    _retire_question_everywhere(question)
    return web.json_response({"dismissed": True})


# -- knowledge (the analyst's viewable memory) ------------------------------

def _read_shared_memory() -> str:
    try:
        return SHARED_MEMORY_FILE.read_text(
            encoding="utf-8", errors="replace")[:MAX_MEMORY_CHARS]
    except OSError:
        return ""


def _write_shared_memory(text: str) -> None:
    SHARED_MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SHARED_MEMORY_FILE.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(SHARED_MEMORY_FILE)


def _queue_memory_fact(fact: str, source: str = "panel",
                      confidence: str = "medium") -> None:
    """Append a candidate fact to the memory inbox.

    The panel does NOT write memory.md. One writer owns that document —
    the consolidator — which is what lets the terminal, voice, insights,
    and study sessions all feed the same memory without a lock between
    them. Everything here is a queue.
    """
    try:
        MEMORY_INBOX_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"ts": int(time.time()), "source": source, "fact": fact,
             "confidence": confidence},
            ensure_ascii=False,
        )
        path = MEMORY_INBOX_DIR / f"{int(time.time())}-{source}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        # A failed hand-off must never break an insight run.
        log.debug("memory inbox write failed: %s", exc)


def _queue_memory_removal(text: str) -> None:
    """Ask the consolidator to drop a line (and its rewordings)."""
    _queue_memory_fact(f"FORGET: {text}", source="panel-forget", confidence="high")



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


# -- onboarding: learn the home, then propose cards worth having ------------

async def h_onboarding(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(onboarding.state))


async def h_onboarding_learn(request: web.Request) -> web.Response:
    """Queue the opening syllabus. Returns immediately — study sessions run
    for minutes on the CLI side, and the panel polls progress."""
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    result = await asyncio.to_thread(onboarding.start_learning)
    return web.json_response(result)


async def h_onboarding_recommend(request: web.Request) -> web.Response:
    """One tool-free pass over the memory document plus a home snapshot."""
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")

    import ha_data  # deferred so the module loads without aiohttp in tests

    memory = await asyncio.to_thread(_read_shared_memory)
    # Any category works as a bundle shape here — we want the home, not a
    # topic — so borrow the broadest one available.
    shape = {"id": "onboarding", "title": "Home overview",
             "focus": "A broad survey of this home."}
    try:
        bundle = await ha_data.collect_bundle(shape, eff_history_days())
    except Exception as exc:  # noqa: BLE001 — report, don't 500
        raise web.HTTPBadGateway(text=f"could not read Home Assistant: {exc}")

    prompt = onboarding.build_prompt(memory, bundle)
    result = await asyncio.to_thread(
        engine.run_claude, prompt, onboarding.RECOMMEND_SYSTEM, eff_model(),
        TIMEOUT_S, 4)
    _record_usage(result, "onboarding")
    if not result["ok"]:
        raise web.HTTPBadGateway(text=result.get("error") or "recommendation failed")
    try:
        parsed = onboarding.parse_recommendations(result["text"])
    except ValueError as exc:
        raise web.HTTPBadGateway(text=str(exc))
    return web.json_response(await asyncio.to_thread(
        onboarding.save_recommendations, parsed))


async def h_onboarding_accept(request: web.Request) -> web.Response:
    body = await request.json()
    picked = body.get("accept")
    if not isinstance(picked, list):
        raise web.HTTPBadRequest(text="accept must be a list of indexes")
    created = await asyncio.to_thread(onboarding.accept, picked)
    return web.json_response({"created": created, "onboarded": True})


async def h_onboarding_skip(request: web.Request) -> web.Response:
    await asyncio.to_thread(onboarding.skip)
    return web.json_response({"onboarded": True})


async def h_onboarding_reset(request: web.Request) -> web.Response:
    await asyncio.to_thread(onboarding.reset)
    return web.json_response({"onboarded": False})


def _inbox_pending() -> int:
    """Facts waiting for the consolidator — the count the Memory tab's
    "File into memory now" button puts on itself, so pressing it is an
    informed choice rather than a hopeful one."""
    total = 0
    try:
        for path in MEMORY_INBOX_DIR.glob("*.jsonl"):
            try:
                total += sum(1 for line in path.read_text(
                    encoding="utf-8", errors="replace").splitlines() if line.strip())
            except OSError:
                continue
    except OSError:
        return 0
    return total


def _last_consolidated() -> int:
    """When the consolidator last completed a pass (epoch seconds, 0 = never).

    The panel does not track which discoveries have been filed — the marker
    the consolidator touches already says it, for every caller of the
    consolidator rather than just the button.
    """
    try:
        return int(MEMORY_MARKER_FILE.stat().st_mtime)
    except OSError:
        return 0


def _facts_with_filing() -> list[dict]:
    """Discovered facts, each flagged with whether it is in the document yet.

    A fact is queued to the memory inbox the moment it is discovered, so any
    fact older than the last consolidation has been folded into memory.md.
    Filed ones stop being a queue and become history — the Memory tab shows
    them separately, so the list above the button is only what is actually
    still waiting.
    """
    cutoff = _last_consolidated()
    facts = knowledge_store.list_facts()
    for f in facts:
        f["filed"] = bool(cutoff) and f["ts"] <= cutoff
    return facts


def _memory_state() -> dict:
    """What the Memory tab needs to know about consolidation right now.

    Two different things get called "merging" and the tab should say which:
    a pass that is *running* (the lock is held, by the daemon or by the
    button) and one that is merely *queued* (you added a fact and the next
    scheduled pass will pick it up). Reporting only the second is what made
    a background pass look like nothing happening.
    """
    running = _consolidation_running()
    state = dict(MEMORY_STATE)
    state["running"] = running
    # The button's own flag stays authoritative for "you asked for this" —
    # the lock cannot tell us who started a pass.
    state["by"] = "you" if state.get("merging") else "schedule"
    state["merging"] = bool(state.get("merging") or running)
    state["stale_hours"] = _consolidation_stale_hours()
    return state


# The consolidator runs daily, so a queue that has been waiting appreciably
# longer than that is a consolidator that is not running — not a busy one.
STALE_AFTER_H = 26


def _consolidation_stale_hours() -> float:
    """How long facts have been queued with nothing filing them, or 0.

    This exists because the failure it surfaces hid for weeks. The lock was
    calling `flock -w`, which BusyBox — Alpine's flock, which is what this
    add-on runs on — rejects with the same exit status as "the lock is
    held". So every pass reported contention, did nothing, and said so only
    in the add-on log. The document went stale, the queue grew, and every
    screen a user looks at said everything was fine.

    Nothing here can detect that specific cause, and it should not try to:
    what it detects is the symptom common to every cause, which is facts
    waiting and no pass landing.
    """
    try:
        pending = _inbox_pending()
    except Exception:  # noqa: BLE001 - a status field must never raise
        return 0.0
    if not pending:
        return 0.0
    try:
        last = (MEMORY_DIR / ".last_consolidated").stat().st_mtime
    except OSError:
        # Never consolidated. Only news once there has been time to.
        last = _process_start
    hours = (time.time() - last) / 3600.0
    return round(hours, 1) if hours >= STALE_AFTER_H else 0.0


async def h_knowledge(request: web.Request) -> web.Response:
    """Everything the analyst has learned, in one payload for the panel."""
    return web.json_response({
        "facts": await asyncio.to_thread(_facts_with_filing),
        "questions": knowledge_store.list_questions(),
        "hypotheses": hypotheses.list_all("open"),
        "hypothesis_budget": hypotheses.budget(),
        "shared_memory": _read_shared_memory(),
        "memory_state": await asyncio.to_thread(_memory_state),
        "inbox_pending": await asyncio.to_thread(_inbox_pending),
    })


def _consolidate_now() -> tuple[bool, str]:
    """Run one consolidation pass, synchronously, in a thread.

    The daemon does this daily (or early past 20 pending facts). The button
    exists because "I just taught it something, put it in the document"
    should not mean waiting until tomorrow. Same script, same checks — the
    consolidator stays the only writer of memory.md either way.
    """
    if not os.path.isfile(CONSOLIDATE_SCRIPT):
        return False, "the consolidator isn't installed in this image"
    try:
        proc = subprocess.run(
            ["bash", CONSOLIDATE_SCRIPT, "--once"],
            capture_output=True, text=True, timeout=CONSOLIDATE_TIMEOUT_S,
            env={**os.environ, "HOME": engine.CLAUDE_HOME},
        )
    except subprocess.TimeoutExpired:
        return False, f"consolidation passed its {CONSOLIDATE_TIMEOUT_S}s limit"
    except OSError as exc:
        return False, f"could not run the consolidator: {exc}"
    if proc.returncode == CONSOLIDATE_BUSY_RC:
        return False, ("another consolidation is already running — "
                       "give it a moment and press it again")
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()
        return False, (tail[-1][:300] if tail else
                       f"the consolidator exited {proc.returncode}")
    return True, ""


async def h_memory_consolidate(request: web.Request) -> web.Response:
    """Fold the inbox into memory.md now, rather than at the next pass.

    What we report is what the queue actually did, not what we asked it to
    do: the consolidator leaves the inbox pending on every failure it can
    detect, and some of those failures still exit 0. Counting the queue
    either side of the pass is the only honest measure of "filed".
    """
    before = await asyncio.to_thread(_inbox_pending)
    MEMORY_STATE.update(merging=True, error="")
    try:
        ok, error = await asyncio.to_thread(_consolidate_now)
    finally:
        MEMORY_STATE.update(merging=False)
    after = await asyncio.to_thread(_inbox_pending)
    drained = max(0, before - after)
    if ok and before and not drained:
        ok, error = False, (
            "the consolidator finished but the queue didn't move — see the "
            "add-on log's [brain-memory] lines for why it kept the facts")
    MEMORY_STATE.update(error="" if ok else error)
    if not ok:
        raise web.HTTPBadGateway(text=error or "consolidation failed")
    return web.json_response({
        "consolidated": drained,
        "shared_memory": await asyncio.to_thread(_read_shared_memory),
        "inbox_pending": after,
    })


async def h_hypothesis_confirm(request: web.Request) -> web.Response:
    """Yes. The claim is the durable part, so it is queued as a plain memory
    fact and the guess itself is settled — no Q/A pair is kept anywhere."""
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad hypothesis id")
    settled = hypotheses.confirm(ts)
    if not settled:
        raise web.HTTPNotFound(text="no such open hypothesis")
    await _submit_memory(settled["text"], source="confirmed")
    _retire_question_everywhere(settled["text"])
    return web.json_response({"confirmed": ts, "budget": hypotheses.budget()})


async def h_hypothesis_reject(request: web.Request) -> web.Response:
    """No. Recorded as a dead end so the same line of inquiry is not
    revisited — that is the one part of the queue worth showing the model."""
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad hypothesis id")
    settled = hypotheses.reject(ts)
    if not settled:
        raise web.HTTPNotFound(text="no such open hypothesis")
    entry = knowledge_store.record_question(settled["text"])
    if entry:
        knowledge_store.dismiss_question(entry["ts"])
    _retire_question_everywhere(settled["text"])
    return web.json_response({"rejected": ts, "budget": hypotheses.budget()})


async def h_knowledge_fact_add(request: web.Request) -> web.Response:
    """Teach a fact from the panel. A taught fact's home is the memory
    DOCUMENT — Claude merges it into memory.md, so it shows up exactly once,
    in the markdown. It is deliberately NOT stored in the facts ledger (that
    stays reserved for what the analyst discovered on its own); the merge
    task guarantees the fact lands in the document even when Claude is
    unreachable."""
    body = await request.json()
    text = str(body.get("text") or "").strip()
    if not text:
        raise web.HTTPBadRequest(text="fact text required")
    if len(text) > knowledge_store.MAX_TEXT_CHARS:
        raise web.HTTPBadRequest(
            text=f"fact too long (max {knowledge_store.MAX_TEXT_CHARS} chars)")
    key = knowledge_store.normalize(text)
    # Re-add guard: the same wording already sits in the document.
    if key and key in knowledge_store.normalize(_read_shared_memory()):
        return web.json_response({"added": False, "queued": False})
    await _submit_memory(text, source="panel")
    return web.json_response({"added": True, "queued": True})


async def h_memory_put(request: web.Request) -> web.Response:
    """Save a manual edit of the memory file from the panel."""
    body = await request.json()
    text = body.get("text")
    if not isinstance(text, str):
        raise web.HTTPBadRequest(text="text must be a string")
    if len(text) > MAX_MEMORY_CHARS:
        raise web.HTTPBadRequest(text=f"memory too large (max {MAX_MEMORY_CHARS} chars)")
    try:
        await asyncio.to_thread(_write_shared_memory, text)
    except OSError as exc:
        raise web.HTTPInternalServerError(text=f"could not write memory file: {exc}")
    return web.json_response({"saved": True})


async def h_knowledge_fact_delete(request: web.Request) -> web.Response:
    """Forget a fact: queue its removal from the memory document.

    The panel never edits memory.md itself — it asks the consolidator to,
    which is what keeps a single writer on that file."""
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad fact id")
    text = next((f["text"] for f in knowledge_store.list_facts()
                 if f["ts"] == ts), "")
    if not knowledge_store.remove_fact(ts):
        raise web.HTTPNotFound(text="no such fact")
    queued = bool(text)
    if queued:
        await asyncio.to_thread(_queue_memory_removal, text)
    return web.json_response({"deleted": ts, "queued": queued})


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
    knowledge_store.add_fact(f"{match['text'].rstrip('?')}: {answer}",
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


# -- runtime settings (⚙ dialog) --------------------------------------------

def _settings_payload(settings: dict) -> dict:
    """The ⚙ dialog's view: panel settings + the live effective options."""
    return {
        "settings": {**settings, **effective_options()},
        "usage": usage_store.budget_state(settings),
        "addon_defaults": addon_defaults(),
        "options_synced": addon_options.snapshot() is not None,
        "models": engine.MODEL_CHOICES,
    }


async def h_settings_get(request: web.Request) -> web.Response:
    await addon_options.refresh()
    payload = _settings_payload(settings_store.load())
    payload["plans"] = [
        {"id": p, "label": usage_store.PLAN_LABELS[p],
         "session_tokens": usage_store.PLAN_SESSION_TOKENS[p]}
        for p in settings_store.PLANS
    ]
    return web.json_response(payload)


async def h_settings_put(request: web.Request) -> web.Response:
    """Save panel settings and/or add-on options.

    Option fields are written to the add-on's own options through the
    Supervisor, so the Configuration tab shows the same value the panel
    does. Without a Supervisor (or if it refuses the write) they fall back
    to the local override store and the panel keeps working.
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="settings must be an object")
    options = {k: v for k, v in body.items() if settings_store.is_option(k)}
    panel = {k: v for k, v in body.items() if k not in options}
    try:
        clean_options = {k: settings_store.clean_option(k, v)
                         for k, v in options.items()}
        settings = settings_store.save(panel) if panel else settings_store.load()
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))

    if clean_options:
        wrote_addon = False
        if addon_options.available():
            # An option has no "unset" state on the Configuration tab, so an
            # emptied number field means "back to the value the add-on
            # started with" rather than leaving a null behind. An emptied
            # model is different: "" is its real value (= let the CLI pick).
            startup = startup_options()
            resolved = {}
            for key, value in clean_options.items():
                if key == "model":
                    resolved[key] = value or ""
                else:
                    resolved[key] = startup[key] if value is None else value
            try:
                await addon_options.write(resolved)
                wrote_addon = True
            except addon_options.OptionsError as exc:
                log.warning("could not write add-on options (%s) — "
                            "storing locally instead", exc)
        try:
            # Local store: authoritative only without a Supervisor. After a
            # successful add-on write we clear these so one value can't be
            # shadowed by a stale override.
            settings = settings_store.save(
                dict.fromkeys(clean_options) if wrote_addon else clean_options)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc))
    return web.json_response(_settings_payload(settings))


# -- auth -------------------------------------------------------------------

async def h_auth_token(request: web.Request) -> web.Response:
    body = await request.json()
    token = (body.get("token") or "").strip()
    try:
        saved = engine.save_auth(token)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc))
    asyncio.create_task(_check_auth_bg())
    return web.json_response({"saved": True, "type": saved["type"]})


async def h_auth_logout(request: web.Request) -> web.Response:
    engine.clear_auth()
    engine.SETUP_FLOW.cancel()
    AUTH_CHECK.update(state="unchecked", error="", checked_at=0)
    return web.json_response({"cleared": True})


async def h_setup_start(request: web.Request) -> web.Response:
    status = await asyncio.to_thread(engine.SETUP_FLOW.start)
    return web.json_response(status)


async def h_setup_code(request: web.Request) -> web.Response:
    body = await request.json()
    code = (body.get("code") or "").strip()
    if not code:
        raise web.HTTPBadRequest(text="empty code")
    status = await asyncio.to_thread(engine.SETUP_FLOW.submit_code, code)
    return web.json_response(status)


async def h_setup_status(request: web.Request) -> web.Response:
    status = engine.SETUP_FLOW.status()
    if status["phase"] == "done" and AUTH_CHECK["state"] == "unchecked":
        asyncio.create_task(_check_auth_bg())
    return web.json_response(status)


async def h_setup_cancel(request: web.Request) -> web.Response:
    engine.SETUP_FLOW.cancel()
    return web.json_response(engine.SETUP_FLOW.status())


async def h_health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# The chat terminal
#
# Same Claude Code, same credential, same /config working directory and
# therefore the same settings.local.json permissions as the listeners — what
# differs is only that its output is rendered as DOM instead of drawn into a
# character grid. See chat_session.py.
# ---------------------------------------------------------------------------

def _chat() -> "chat_session.ChatSession":
    session = chat_session.session()
    # Resolved per call rather than at startup: the model is editable from
    # ⚙ Settings and from the Configuration tab, and a chat session started
    # before an edit should not keep the old one for as long as it lives.
    session.model = eff_model()
    return session


async def h_chat_stream(request: web.Request) -> web.StreamResponse:
    """Server-sent events: a snapshot, then everything as it happens.

    The snapshot is the first frame rather than a separate GET so there is
    no window between "what the transcript was" and "what happened next" —
    a reconnect that has to stitch two requests together is a reconnect that
    drops an event eventually.
    """
    session = _chat()
    resp = web.StreamResponse(headers={
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        # Ingress puts nginx in front of us; without this it buffers the
        # stream and the page sits blank until the turn is over.
        "X-Accel-Buffering": "no",
    })
    await resp.prepare(request)
    queue = session.subscribe()

    async def send(payload: dict) -> None:
        await resp.write(b"data: " + json.dumps(payload).encode() + b"\n\n")

    try:
        await send(_chat_snapshot(session))
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                # A comment frame: proves the connection to both ends and
                # keeps any intermediary from reaping an idle stream.
                await resp.write(b": ping\n\n")
                continue
            await send(event)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        session.unsubscribe(queue)
    return resp


async def h_chat_send(request: web.Request) -> web.Response:
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    try:
        return web.json_response(await _chat().send(body.get("text") or ""))
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=str(exc))
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=str(exc))


async def h_chat_stop(request: web.Request) -> web.Response:
    return web.json_response(await _chat().interrupt())


async def h_chat_new(request: web.Request) -> web.Response:
    return web.json_response(await _chat().reset())


async def h_chat_handoff(request: web.Request) -> web.Response:
    """Stop the chat session and hand it to the classic terminal."""
    return web.json_response(await _chat().handoff())


async def h_chat_conversations(request: web.Request) -> web.Response:
    """Every conversation in this project directory, whichever face made it.

    Read straight out of Claude Code's own store, so a session started in
    the terminal is listed here beside one started in the chat — that is
    what "interchangeable" has to mean to be worth saying.
    """
    session = _chat()
    return web.json_response({
        "conversations": await asyncio.to_thread(
            conversations.listing, chat_session.WORK_DIR, 30, session.session_id),
        "current": session.session_id,
    })


async def h_chat_resume(request: web.Request) -> web.Response:
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    session_id = str(body.get("session_id") or "")
    session = _chat()
    replay = await asyncio.to_thread(
        conversations.transcript, chat_session.WORK_DIR, session_id)
    try:
        return web.json_response(await session.resume(session_id, replay))
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=str(exc))


def _chat_snapshot(session: "chat_session.ChatSession") -> dict:
    """The session's own snapshot, plus what the composer needs to offer.

    The `brain`/`ha` command list rides along here rather than on its own
    endpoint because it is wanted at exactly the moment the snapshot is —
    when the chat opens — and it is cached, so it costs nothing to include.
    """
    return {**session.snapshot(), "cli": cli_commands.listing()}


async def h_chat_state(request: web.Request) -> web.Response:
    """The snapshot on its own, for a client whose stream is not up yet."""
    return web.json_response(_chat_snapshot(_chat()))


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

def make_app() -> web.Application:
    # 256 KiB: leaves room for a full memory-file edit (MAX_MEMORY_CHARS
    # plus JSON escaping) — everything else is far smaller
    app = web.Application(client_max_size=1024 * 256)
    app.router.add_get("/", h_index)
    app.router.add_get("/style.css", _static("style.css", "text/css"))
    app.router.add_get("/app.js", _static("app.js", "application/javascript"))
    app.router.add_get("/docs.js", _static("docs.js", "application/javascript"))
    app.router.add_get("/favicon.svg", _static("favicon.svg", "image/svg+xml"))
    app.router.add_get("/api/status", h_status)
    app.router.add_get("/api/settings", h_settings_get)
    app.router.add_put("/api/settings", h_settings_put)
    app.router.add_get("/api/insights", h_insights)
    app.router.add_post("/api/generate", h_generate)
    app.router.add_post("/api/generate_all", h_generate_all)
    app.router.add_delete("/api/insight/{id}", h_delete_insight)
    app.router.add_put("/api/insight/{id}", h_rename_insight)
    app.router.add_delete("/api/card/{id}", h_delete_card)
    app.router.add_put("/api/card/{id}/tags", h_card_tags_put)
    app.router.add_get("/api/findings", h_findings)
    app.router.add_post("/api/finding/{ts}/fix", h_finding_fix)
    app.router.add_post("/api/finding/{ts}/snooze", h_finding_snooze)
    app.router.add_post("/api/finding/{ts}/discuss", h_finding_discuss)
    app.router.add_post("/api/finding/{ts}/{verb}", h_finding_verb)
    app.router.add_delete("/api/finding/{ts}", h_finding_delete)
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
    app.router.add_post("/api/questions/dismiss", h_dismiss_question_card)
    app.router.add_get("/api/onboarding", h_onboarding)
    app.router.add_post("/api/onboarding/learn", h_onboarding_learn)
    app.router.add_post("/api/onboarding/recommend", h_onboarding_recommend)
    app.router.add_post("/api/onboarding/accept", h_onboarding_accept)
    app.router.add_post("/api/onboarding/skip", h_onboarding_skip)
    app.router.add_post("/api/onboarding/reset", h_onboarding_reset)
    app.router.add_get("/api/knowledge", h_knowledge)
    app.router.add_post("/api/hypothesis/{ts}/confirm", h_hypothesis_confirm)
    app.router.add_post("/api/hypothesis/{ts}/reject", h_hypothesis_reject)
    app.router.add_put("/api/memory", h_memory_put)
    app.router.add_post("/api/memory/consolidate", h_memory_consolidate)
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
    app.router.add_get("/api/chat/stream", h_chat_stream)
    app.router.add_get("/api/chat/state", h_chat_state)
    app.router.add_post("/api/chat/send", h_chat_send)
    app.router.add_post("/api/chat/stop", h_chat_stop)
    app.router.add_post("/api/chat/new", h_chat_new)
    app.router.add_post("/api/chat/handoff", h_chat_handoff)
    app.router.add_get("/api/chat/conversations", h_chat_conversations)
    app.router.add_post("/api/chat/resume", h_chat_resume)

    # The terminal tab: /terminal/ is reverse-proxied through to ttyd
    # so the whole add-on lives behind one ingress port.
    terminal_proxy.setup(app)

    async def on_startup(app: web.Application) -> None:
        # Startup is the one moment we know nothing is in flight, so it is
        # the only place a fix orphaned by a restart can be told apart from
        # one that is genuinely still running.
        orphaned = await asyncio.to_thread(
            findings_store.reconcile_running,
            "brAIn restarted while this fix was running, so it could not "
            "report what it did. Check the entity before trying again.")
        if orphaned:
            log.warning("%d fix run(s) were interrupted by a restart", orphaned)
        await _options_sync()
        app["worker"] = asyncio.create_task(_worker())
        app["scheduler"] = asyncio.create_task(_scheduler())
        if addon_options.available():
            app["options"] = asyncio.create_task(_options_poller())
        if engine.get_auth():
            asyncio.create_task(_check_auth_bg())

    async def on_cleanup(app: web.Application) -> None:
        # The chat session is a child process of ours; leaving it running
        # after the panel goes down orphans a Claude that nothing will ever
        # read from again.
        await chat_session.session().stop()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    web.run_app(make_app(), host=BIND_HOST, port=BIND_PORT, print=None)
