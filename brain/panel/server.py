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
GET  /api/findings           — the decision list: what brAIn thinks is broken,
                               plus the guesses it wants confirmed
POST /api/finding/{ts}/fix   — go fix it (the one tool-enabled Claude run)
POST /api/finding/{ts}/wrong  — you've got this wrong / not a problem here,
                                optionally {note}: WHY, in your words, which
                                is handed to the analyst and the consolidator
                                rather than acted on literally
                                (/ignore is the old name for the same thing)
POST /api/finding/{ts}/done  — you fixed it yourself
POST /api/finding/{ts}/ack   — you've read what brAIn's fix changed
                                (all three END it: memory line, then the
                                 row is deleted — see findings_store)
POST /api/finding/{ts}/reopen — put a pre-ledger dismissal back on the list
POST /api/finding/{ts}/snooze — remind me later; NOT a decision, so the
                                status is untouched and it comes back
POST /api/finding/{ts}/discuss — open it as a conversation in the chat
POST /api/findings/unsettle  — {key}: let brAIn raise an answered one again
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
POST /api/hypothesis/{ts}/confirm — yes, that's right: it becomes a memory line
POST /api/hypothesis/{ts}/reject  — no, optionally {note}: why it's wrong
                               (both answer with the Findings payload, because
                                that is the one list they are shown in)
GET  /api/knowledge          — learned facts + question ledger + shared memory.md
POST /api/knowledge/fact     — teach a fact {text}; Claude merges it into memory.md
                               (its only home — never duplicated into the ledger)
POST /api/knowledge/question/{ts}/answer   — answer an open question {answer}
POST /api/knowledge/question/{ts}/dismiss  — retire a question unanswered
DELETE /api/knowledge/question/{ts}        — forget a question (askable again)
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
import hashlib
import json
import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

import actions
import addon_options
import atomic_write
import baselines
import brief
import card_tags
import chat_session
import checks
import cli_commands
import conversations
import engine
import feedback_store
import findings_store
import fixer
import health
import hypotheses
import journal
import knowledge_store
import notify_router
import override_ledger
import onboarding
import prompt_store
import rhythm
import run_sources
import settings_store
import terminal_proxy
import undo_store
import usage_store
import user_categories
from categories import (ANALYST_SYSTEM, CATEGORIES, SYSTEM_PROMPT, build_orientation_prompt,
                        build_prompt, get_category)

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
# How much of the filing queue the Memory tab is sent, and how long one
# queued fact may be on screen. The list is capped and the COUNT is not:
# a truncated list that also truncated its own count would be the same
# disagreement this list was rebuilt to end, in a subtler place.
INBOX_LIST_MAX = 100
MAX_INBOX_TEXT = 500
# Touched by the consolidator at the end of every successful pass (including
# a pass that found the inbox already empty). Its mtime says when memory.md
# last moved — which is what tells a stale error apart from a live one. It
# used to carry more than that: the Memory tab derived its "still waiting"
# list by keeping ledger facts newer than this mtime, which is a guess at
# the queue rather than the queue. It reads the inbox now.
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
MEMORY_STATE: dict = {"merging": False, "error": "", "filed": 0, "done_at": 0}
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
# The consolidator stamps this when a pass starts and removes it when the pass
# ends. Read only while the lock is held, so one left behind by a killed pass
# is never shown as a pass in flight.
CONSOLIDATE_RUNNING_MARKER = MEMORY_DIR / ".consolidating"


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


def _consolidation_running_for() -> int:
    """How long the pass now running has been going (seconds, 0 = unknown).

    So the tab can count up instead of promising a duration. "This takes a
    few minutes" was the honest shape of the answer and still left you unable
    to tell a slow pass from a stuck one, which is the only thing you
    actually want to know while watching it.

    Elapsed rather than a start timestamp: the marker's mtime is on the
    add-on's clock and the tab renders on the browser's, and an ingress panel
    is often open on a phone whose clock is minutes off. Subtracting here
    means the two clocks never have to agree.
    """
    try:
        started = CONSOLIDATE_RUNNING_MARKER.stat().st_mtime
    except OSError:
        return 0
    return max(0, int(time.time() - started))


MODEL = os.environ.get("BRAIN_MODEL", "").strip()
TIMEOUT_S = int(float(os.environ.get("BRAIN_TIMEOUT_MIN", "8") or 8) * 60)

# The memory consolidator, run on demand from the Memory tab's "File into
# memory now". Normally a daemon on its own cadence (daily, or early once the
# inbox passes 20 pending facts) — this is the same pass, triggered by hand.
CONSOLIDATE_SCRIPT = os.environ.get(
    "BRAIN_CONSOLIDATE_SCRIPT", "/opt/scripts/brain-memory-consolidate.sh")
# Longer than anything the pass can legitimately spend: its own Claude call
# (480s by default) plus the wait for a lock the daemon may be holding. A
# ceiling below that turned a slow pass into a killed one — and the request
# carrying it into a five-minute POST that ended in a 502.
CONSOLIDATE_TIMEOUT_S = int(os.environ.get("BRAIN_CONSOLIDATE_TIMEOUT", "1200"))
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


def eff_chat_model() -> str:
    """The chat terminal's model: its own choice, else the global one.

    A panel setting rather than an add-on option, because it is chosen from
    inside the chat for the chat — the insight runs and the listeners keep
    following the Configuration tab.
    """
    return str(settings_store.load().get("chat_model") or "") or eff_model()


def eff_gather_mode() -> str:
    return settings_store.load().get("gather_mode", "search")




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
# Characters per token, for the ONE number that has to exist before the run
# does: what a prompt is about to cost. Approximate by nature — the real
# count comes back in the result envelope and is what everything downstream
# reports — so anywhere this is shown it is prefixed with "~".
CHARS_PER_TOKEN = 4
# Turns a searching run may take. Generous rather than tight, for the reason
# the docs give about every other cap here: a run that hits its limit stops
# mid-thought and produces nothing, so you pay for every token and get no
# card — which makes a tight cap the most expensive setting there is. Twelve
# is room for a handful of searches, a couple of history pulls, and the write.
ANALYST_MAX_TURNS = 12

logging.basicConfig(
    level=getattr(logging, os.environ.get("BRAIN_LOG_LEVEL", "info").upper(), logging.INFO),
    format="[insights] %(levelname)s %(message)s",
)
log = logging.getLogger("brain")


class QuietAccessLogger(AbstractAccessLogger):
    """The add-on log is where you look when something is wrong.

    An open panel polls: status every 20s, the knowledge payload while a
    consolidation runs, findings, the chat stream. Logging a line for each
    put a request every two seconds into the add-on log — thousands of
    identical 200s that pushed the one line explaining a failure off the
    top of the page. Nobody has ever debugged brAIn from its access log,
    and everybody has had to scroll past it.

    So: nothing is logged for a routine poll that succeeded. Anything that
    failed is logged, at warning, because that is the shape of the thing
    you came looking for. ``log_level: debug`` in the add-on options gets
    every request back, with its timing — one switch for "tell me
    everything", rather than an option of its own for each thing that is
    noisy.
    """

    # Endpoints the panel asks for on a timer. Everything else — a POST, a
    # delete, a page load — is a thing somebody did, and gets a line.
    POLLED = ("/api/status", "/api/knowledge", "/api/memory/state",
              "/api/insights", "/api/findings", "/api/onboarding",
              "/api/auth/setup/status", "/api/chat/")

    def log(self, request, response, time):
        status = response.status
        if status >= 400:
            self.logger.warning('%s %s -> %s', request.method, request.path, status)
            return
        if VERBOSE_ACCESS_LOG:
            self.logger.info('%s %s -> %s (%.3fs)',
                             request.method, request.path, status, time)
            return
        if request.method == "GET" and request.path.startswith(self.POLLED):
            return
        self.logger.info('%s %s -> %s', request.method, request.path, status)


VERBOSE_ACCESS_LOG = os.environ.get("BRAIN_ACCESS_LOG", "").lower() in (
    "1", "true", "yes", "on")

# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------
# JOBS[insight_id] = {state, phase, started_at, error, question}
JOBS: dict[str, dict] = {}
QUEUE: asyncio.Queue[str] = asyncio.Queue()
# The house checks (panel/checks): whether a pass is in flight, and the
# summary of the last one — which is what /api/checks, `brain check list`
# and the diagnostics bundle read.
CHECKS_STATE: dict = {"running": False, "last": None}
CHECKS_FIRST_DELAY_S = 120
CHECKS_TICK_S = 300
# The diagnostics mirror, for the integration's Download-diagnostics button.
# /data is invisible to Home Assistant, so the panel publishes to the shared
# volume — same reasoning as the findings mirror, same skip rule for a dev
# checkout whose /config does not exist.
DIAGNOSTICS_FILE = Path(os.environ.get(
    "BRAIN_DIAGNOSTICS_FILE", "/config/.brain/diagnostics.json"))
DIAGNOSTICS_PUBLISH_S = 3600
DIAG_STATE: dict = {"published_at": 0.0}
_CLI_VERSION: dict = {"value": None}
AUTH_CHECK: dict = {"state": "unchecked", "error": "", "checked_at": 0,
                    "running": False}
# How old a settled auth verdict may get before it is re-earned.
#
# The check used to run at startup, after a credential was saved, and after
# the guided sign-in — and never again. So a credential that died on a
# Tuesday afternoon was reported by nothing: /api/status went on serving
# `state: "ok"` from a check made days earlier, the chip stayed hidden
# because a working login is not news, and the first real symptom was voice
# and automations failing while the terminal carried on working off a
# different store. A verdict nothing re-earns is the same failure the usage
# tracker had — a reading nothing can correct.
#
# It is re-earned lazily off /api/status rather than on a timer, because
# `validate_auth` is a real `claude -p` call and an unattended timer would
# spend account tokens forever on a question nobody is asking. The panel
# polls status while it is open, so the check costs one tiny turn per
# interval while somebody is looking and nothing at all when they are not.
# Six hours because a credential dies on the scale of hours, not minutes.
#
# A *failed* verdict ages out too: somebody who fixes their login in the
# terminal should not have to restart the add-on for the panel to notice.
AUTH_RECHECK_S = int(os.environ.get("BRAIN_AUTH_RECHECK_S", 6 * 3600))


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


def _under(base: Path, *parts: str) -> Path:
    """Join `parts` under `base` and prove the result stayed there.

    Every caller has already matched its id against `_SAFE_ID` or
    `_STAMP_RE`, neither of which can produce a separator or a dot
    segment — so this second lock never fires in practice. It is here
    because containment is then a property of the path being returned
    rather than of a regex somewhere further up the call stack: a reader
    (and a static analyser) can see the guarantee at the point the path
    is built, without going to find the pattern that made it true.
    """
    root = base.resolve()
    path = (root / Path(*parts)).resolve()
    if path != root and root not in path.parents:
        raise web.HTTPBadRequest(text="bad path")
    return path


def _insight_path(insight_id: str) -> Path:
    if not _SAFE_ID.match(insight_id):
        raise web.HTTPBadRequest(text="bad insight id")
    return _under(INSIGHTS_DIR, f"{insight_id}.json")


def _history_dir(insight_id: str) -> Path:
    if not _SAFE_ID.match(insight_id):
        raise web.HTTPBadRequest(text="bad insight id")
    return _under(INSIGHTS_DIR, "history", insight_id)


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
                # A file mid-write, or one that is not valid JSON, is left out of this
                # listing and picked up by the next one.
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
    path = _insight_path(insight["id"])
    atomic_write.write_json(path, insight)
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
            # Trimming is opportunistic; a file that will not delete is retried the
            # next time a card is saved.
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
        atomic_write.write_json(hdir / f"{stamp}.json", insight)
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
            # A run that will not delete is retried on the next prune.
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

def _tok(n: int) -> str:
    """A token count as a person would say it: 41231 -> "41.2k"."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(int(n))


def _record_usage(result: dict, insight_id: str) -> dict:
    """Book a finished Claude invocation's tokens against the session budget,
    and say out loud what it cost.

    Every Claude run the panel makes lands here, which is why the log line
    lives here rather than in each of the three callers. The add-on used to
    log the size of the data it collected and then never mention the price
    of the run it spent that data on — so the only visible evidence a card
    was expensive was the usage pill moving, after the fact, with nothing
    on screen attributing it. Best-effort throughout: usage accounting must
    never break the run it is accounting for.
    """
    try:
        cost = usage_store.split_from_meta(result.get("meta") or {})
        usage_store.record_run(cost["total"], insight_id)
        if cost["total"]:
            log.info("%s cost %s tokens (%s in + %s out; %s read from cache, free) "
                     "— 5-hour window now %s", insight_id, _tok(cost["total"]),
                     _tok(cost["input"]), _tok(cost["output"]), _tok(cost["cached"]),
                     _tok(usage_store.window_tokens()))
        return cost
    except Exception as exc:  # noqa: BLE001
        log.debug("usage recording failed: %s", exc)
        return usage_store.split_from_meta({})


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


def _findings_notify_target() -> tuple[str, str]:
    """Where new findings should be pushed, and from what severity up.

    The add-on option is the source of truth (live via the options poller,
    so a Configuration-tab edit lands without a restart); the environment
    variables are the fallback run.sh exports for the same options, which is
    what keeps this working when the Supervisor is unreachable.
    """
    opts = addon_options.snapshot() or {}
    service = str(opts.get("findings_notify_service")
                  or os.environ.get("BRAIN_FINDINGS_NOTIFY", "")).strip()
    severity = str(opts.get("findings_notify_min_severity")
                   or os.environ.get("BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY",
                                     "")).strip().lower()
    if severity not in findings_store.SEVERITIES:
        severity = "serious"
    return service, severity


# The flush loop is a clock-watcher rather than a poller: it sleeps until
# the quiet window closes. The ceiling is what makes a Configuration-tab
# edit land without a restart — a loop that had committed to a nine-hour
# sleep would honour last night's bedtime all of today.
NOTIFY_FLUSH_POLL_S = 15 * 60
NOTIFY_FLUSH_FIRST_DELAY_S = 120


def _quiet_hours() -> tuple[int | None, int | None]:
    """The hours between which only an urgent finding may ring a phone."""
    opts = addon_options.snapshot() or {}
    start = notify_router.parse_hour(
        opts.get("notify_quiet_start")
        if opts.get("notify_quiet_start") is not None
        else os.environ.get("BRAIN_NOTIFY_QUIET_START", ""))
    end = notify_router.parse_hour(
        opts.get("notify_quiet_end")
        if opts.get("notify_quiet_end") is not None
        else os.environ.get("BRAIN_NOTIFY_QUIET_END", ""))
    return start, end


async def _send_notification(rows: list[dict], held: bool = False) -> bool:
    """Deliver one message. A failure is a log line, never an exception.

    The finding is already safe on the list before this is called, so a
    bad service name must not be able to fail the run that filed it.
    """
    service, _sev = _findings_notify_target()
    if not service or not rows:
        return False
    title, body = notify_router.compose(rows, held=held)
    import ha_data
    try:
        await ha_data.send_notification(service, title, body)
    except Exception as exc:  # noqa: BLE001 — a bad target can't fail the run
        log.warning("findings notification via %s failed: %s", service, exc)
        return False
    log.info("notified %s of %d finding(s)%s", service, len(rows),
             " held overnight" if held else "")
    return True


async def _flush_held_findings() -> int:
    """Send whatever the quiet hours held, as one message. Returns the count.

    Anything settled or cleared while it waited is dropped rather than
    announced: a problem that went away at four in the morning is not
    news at seven, and being told about one is what teaches somebody
    these messages are not about anything.
    """
    try:
        live = {int(f.get("ts") or 0) for f in findings_store.list_all()}
    except Exception as exc:  # noqa: BLE001 — an unreadable store is not
        # evidence that a problem is over, so everything held goes out.
        log.info("could not read the findings store before a flush: %s", exc)
        live = None
    rows = notify_router.take_queue(live)
    if not rows:
        return 0
    await _send_notification(rows, held=True)
    return len(rows)


def _notify_diagnostics() -> dict:
    """What the router is holding, and what window it is holding it for."""
    start, end = _quiet_hours()
    queued = notify_router.load_queue()
    _tz, tz_name = baselines.house_timezone()
    oldest = min((int(r.get("held_at") or 0) for r in queued), default=0)
    service, severity = _findings_notify_target()
    return {
        "service": bool(service),
        "min_severity": severity,
        "quiet_start": start,
        "quiet_end": end,
        "tz": tz_name,
        "quiet_now": notify_router.in_quiet_hours(
            time.time(), start, end, _tz),
        "held": len(queued),
        "held_since": oldest,
    }


# The brief is checked for often and sent at most once a day; the loop is
# cheap because `brief.due` is arithmetic and `worth_saying` reads what is
# already in memory. Nothing asks Claude until both have said yes.
BRIEF_POLL_S = 5 * 60
BRIEF_FIRST_DELAY_S = 300
BRIEF_STATE: dict = {"last_sent": 0.0, "last_reasons": [], "last_error": ""}
# What "overnight" means for the summary that rides in the prompt.
BRIEF_NIGHT_HOURS = 12


def _local_now(now: float):
    """`now` on the house's own clock. One implementation, one answer."""
    import datetime  # noqa: PLC0415 — the module has no other need of it

    tz, _name = baselines.house_timezone()
    return datetime.datetime.fromtimestamp(now, tz)


def _brief_enabled() -> tuple[bool, int]:
    opts = addon_options.snapshot() or {}
    on = opts.get("morning_brief")
    if on is None:
        on = os.environ.get("BRAIN_MORNING_BRIEF", "").lower() in (
            "true", "1", "yes")
    hour = notify_router.parse_hour(
        opts.get("morning_brief_hour")
        if opts.get("morning_brief_hour") is not None
        else os.environ.get("BRAIN_MORNING_BRIEF_HOUR", ""))
    return bool(on), 7 if hour is None else hour


async def _brief_overnight(now: float) -> dict:
    """What the night looked like, as counts. One logbook fetch, once a day."""
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            mined = await actions.collect(
                session, now - BRIEF_NIGHT_HOURS * 3600, now,
                await checks.snapshot._users(session))
    except Exception as exc:  # noqa: BLE001 — a brief without the night is
        # still a brief; a brief that failed because of it is not.
        log.info("brief could not read the night: %s", exc)
        return {}
    if not mined.get("available"):
        return {}
    counts = mined.get("counts") or {}
    out = {"counts": counts}
    # "More than usual" needs a usual. Without one this says nothing
    # rather than picking a number, which is the same rule the baselines
    # and the override pattern carry.
    unattributed = int(counts.get("unattributed") or 0)
    total = sum(int(v or 0) for v in counts.values())
    if total >= 20 and unattributed > total * 0.6:
        out["unattributed_spike"] = unattributed
    return out


async def _send_brief(now: float) -> str:
    """Gather, decide, and only then ask. Returns what was sent, or ''."""
    verdict = {}
    try:
        payload = await _diagnostics_payload()
        verdict = payload.get("health") or {}
    except Exception as exc:  # noqa: BLE001 — the verdict is one reason of
        # several, and not having it is not a reason to skip the morning.
        log.info("brief could not read the health verdict: %s", exc)

    night = await _brief_overnight(now)
    state = brief.state_from(
        await asyncio.to_thread(findings_store.list_all),
        verdict, night, BRIEF_STATE["last_sent"] or (now - 86400))

    reasons = brief.worth_saying(state)
    BRIEF_STATE["last_reasons"] = reasons
    if not reasons:
        # The whole point. "All quiet" every morning is the message people
        # mute, and it would cost a Claude turn to produce.
        log.info("morning brief: nothing worth saying, not sent")
        return ""

    local = _local_now(now)
    state["woke_at"] = rhythm.clock(
        rhythm.wake_minute(rhythm.profile(), local))

    result = await asyncio.to_thread(
        engine.run_analyst, brief.frame(reasons, state), brief.SYSTEM,
        eff_model(), brief.TIMEOUT_S, brief.MAX_TURNS,
        "brief")
    if not result.get("ok"):
        BRIEF_STATE["last_error"] = str(result.get("error") or "no reply")
        log.warning("morning brief failed: %s", BRIEF_STATE["last_error"])
        return ""

    body = brief.tidy(result.get("text") or result.get("raw") or "")
    if not body:
        BRIEF_STATE["last_error"] = "the reply was too short to send"
        log.warning("morning brief: %s", BRIEF_STATE["last_error"])
        return ""

    BRIEF_STATE["last_error"] = ""
    await _send_notification([{"text": body, "severity": "info"}])
    return body


async def _brief_loop():
    """Wake often, send at most once, and only when there is something to say."""
    await asyncio.sleep(BRIEF_FIRST_DELAY_S)
    while True:
        try:
            on, fallback = _brief_enabled()
            service, _sev = _findings_notify_target()
            if on and service:
                now = time.time()
                local = _local_now(now)
                if brief.due(now, local.hour * 60 + local.minute,
                             rhythm.wake_minute(rhythm.profile(), local),
                             fallback, BRIEF_STATE["last_sent"]):
                    # Stamped before the run, not after: a pass that takes
                    # three minutes must not let the next tick start a
                    # second one, and a failed brief is still this
                    # morning's — retrying it all morning is worse.
                    BRIEF_STATE["last_sent"] = now
                    sent = await _send_brief(now)
                    log.info("morning brief %s",
                             "sent" if sent else "skipped")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a pass
            log.warning("morning brief pass failed: %s", exc)
        await asyncio.sleep(BRIEF_POLL_S)


def _rhythm_diagnostics() -> dict:
    """When this house is measured to stir, and what the brief did with it."""
    try:
        measured = rhythm.profile()
    except Exception as exc:  # noqa: BLE001 — a dev checkout has no store
        return {"error": str(exc)[:120]}
    on, fallback = _brief_enabled()
    return {
        "days": measured.get("days", 0),
        "weekday": measured.get(rhythm.WEEKDAY, {}),
        "weekend": measured.get(rhythm.WEEKEND, {}),
        "brief_enabled": on,
        "brief_fallback_hour": fallback,
        "brief_last_sent": int(BRIEF_STATE["last_sent"]),
        "brief_last_reasons": len(BRIEF_STATE["last_reasons"]),
        "brief_last_error": BRIEF_STATE["last_error"],
    }


async def _notify_flush_loop():
    """Wake at the end of each quiet window and send what it held.

    The wait is recomputed every pass rather than slept once: the option
    can be edited from the Configuration tab without a restart, and a
    loop that had already committed to a 9-hour sleep would honour the
    old bedtime until tomorrow.
    """
    await asyncio.sleep(NOTIFY_FLUSH_FIRST_DELAY_S)
    while True:
        try:
            start, end = _quiet_hours()
            now = time.time()
            if start is None or end is None:
                # No quiet hours: anything left in the queue is from
                # before somebody turned them off, and has waited enough.
                if notify_router.load_queue():
                    await _flush_held_findings()
                await asyncio.sleep(NOTIFY_FLUSH_POLL_S)
                continue
            tz, _name = baselines.house_timezone()
            if not notify_router.in_quiet_hours(now, start, end, tz):
                if notify_router.load_queue():
                    await _flush_held_findings()
                await asyncio.sleep(NOTIFY_FLUSH_POLL_S)
                continue
            wait = notify_router.quiet_ends_at(now, end, tz) - now
            await asyncio.sleep(max(60.0, min(wait, NOTIFY_FLUSH_POLL_S)))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a bad pass
            log.warning("notification flush pass failed: %s", exc)
            await asyncio.sleep(NOTIFY_FLUSH_POLL_S)


async def _announce_findings(created: list[dict]) -> None:
    """Push newly-created findings out, or hold them until morning.

    Only ever handed the CREATED list — add_many dedupes against every
    status and the settled ledger, so a re-reported problem cannot ring the
    phone twice, and there is nothing to announce at startup because a
    replayed store creates nothing.

    Inside quiet hours the split is by `notify_router.urgency_of`, which
    is a different axis from severity: a `critical` battery forecast is
    three weeks away and a `warning` about a boiler that has stopped
    answering is now. The severity floor is applied FIRST, so a row
    nobody wanted notifying about is not held either — otherwise it would
    simply arrive in the morning digest instead.

    A failed delivery is a log line, never an error: the finding is already
    safe on the list, and the notification is the courtesy copy.
    """
    service, min_severity = _findings_notify_target()
    if not service or not created:
        return
    worthy = notify_router.worth_sending(created, min_severity)
    if not worthy:
        return

    start, end = _quiet_hours()
    tz, _name = baselines.house_timezone()
    if not notify_router.in_quiet_hours(time.time(), start, end, tz):
        await _send_notification(worthy)
        return

    # Inside the quiet window only the urgent get through, and the rest
    # are HELD rather than dropped: they are on the Findings tab either
    # way, and a notifier that silently decides some problems were not
    # worth mentioning is one nobody can reason about.
    urgent = [f for f in worthy if notify_router.urgency_of(f) == "now"]
    later = [f for f in worthy if notify_router.urgency_of(f) != "now"]
    if urgent:
        await _send_notification(urgent)
    if later:
        depth = notify_router.hold(later, time.time())
        log.info("held %d finding(s) until quiet hours end (%d waiting)",
                 len(later), depth)


async def _search_run(insight_id: str, cat: dict, framing: dict):
    """Give Claude a map of the home and read-only tools, and let it look.

    The cheap path, and the only one that can afford history on a typed
    question. The map is a few hundred characters — domain counts, area
    counts, a handful of anchors — where the snapshot is tens of thousands,
    so what a run costs finally tracks what it actually needed rather than
    being the same number whatever was asked.

    Returns ``(result, cost)``, or ``(None, None)`` when the map itself
    could not be collected — the caller then runs the snapshot path, which
    is the floor under every mode.
    """
    import ha_data
    try:
        orientation = await ha_data.collect_orientation(question=framing["question"])
    except Exception as exc:  # noqa: BLE001 — a failed map is a fallback, not an error
        log.warning("%s: could not collect the orientation map (%s)", insight_id, exc)
        return None, None
    prompt = build_orientation_prompt(cat, orientation, **framing)
    # `entities` is what the run has been GIVEN, and a search run is given
    # none — the spinner says "searching" rather than claiming a number the
    # snapshot path would have meant literally.
    _set_job(insight_id, state="searching", prompt_chars=len(prompt), entities=0)
    log.info("map for %s: %d entities exist across %d domains, %d prompt chars "
             "(~%s tokens in) — searching", insight_id,
             orientation.get("entity_count", 0), len(orientation.get("domains") or {}),
             len(prompt), _tok(len(prompt) // CHARS_PER_TOKEN))
    result = await asyncio.to_thread(
        engine.run_analyst, prompt, ANALYST_SYSTEM, eff_model(),
        eff_timeout_s(), ANALYST_MAX_TURNS, "card",
    )
    return result, _record_usage(result, insight_id)


async def _snapshot_run(insight_id: str, cat: dict, framing: dict):
    """Post the whole slimmed home in one turn, with no tools at all.

    Deterministic by construction: one prompt, one answer, nothing the model
    can decide to go and read. That is why it is the fallback — a search run
    depends on tools resolving and on the model choosing to stop, and a card
    must still appear when either of those goes wrong.
    """
    import ha_data
    bundle = await ha_data.collect_bundle(
        cat, eff_history_days(), question=framing["question"])
    n_entities = len(bundle.get("entities", []))
    prompt = build_prompt(cat, bundle, **framing)
    # What this run is about to cost, before it costs it. The bundle is the
    # bulk of the prompt but never all of it — memory, the findings block
    # and the previous run ride along — so the bundle's size was an answer
    # to a question nobody asked. The job carries the number too, because a
    # generation is minutes of spinner and "how much of my home did it just
    # send" is the one thing worth knowing during it.
    _set_job(insight_id, state="generating",
             prompt_chars=len(prompt), entities=n_entities)
    log.info("snapshot for %s: %d entities, %d bundle chars, %d prompt chars "
             "(~%s tokens in)", insight_id, n_entities, len(json.dumps(bundle)),
             len(prompt), _tok(len(prompt) // CHARS_PER_TOKEN))
    result = await asyncio.to_thread(
        engine.run_claude, prompt, SYSTEM_PROMPT, eff_model(), eff_timeout_s(),
        source="card",
    )
    return result, _record_usage(result, insight_id)


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
                # No previous run to diff against — which is what a first generation
                # for this card looks like.
                pass
        framing = dict(question=question, feedback=feedback,
                       hypothesis_budget=hypotheses.budget(),
                       knowledge=knowledge, previous=previous,
                       findings=findings_store.prompt_block())

        result = cost = None
        if eff_gather_mode() == "search":
            result, cost = await _search_run(insight_id, cat, framing)
        if result is None or not result["ok"]:
            # The snapshot path is the floor, not a mode: whatever the setting
            # says, a failed search must still produce a card. It costs more
            # than the search did — which is why the fallback is logged rather
            # than silent, and why a run that keeps falling back is a run
            # worth reading the log about.
            if result is not None:
                log.warning("%s: search run failed (%s) — falling back to the "
                            "full snapshot", insight_id,
                            result.get("error") or "no result")
                journal.record("insight", "fallback",
                               error=result.get("error") or "no result",
                               extra={"id": insight_id, "from": "search",
                                      "to": "snapshot"})
            result, cost = await _snapshot_run(insight_id, cat, framing)
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
        # that ignores it must not be able to grow the queue anyway.
        #
        # The queue is where they stay. A card used to carry a copy of every
        # claim it raised and render yes/no under the chart, which put the
        # same three decisions on the card, in the Memory tab and nowhere
        # that counted them — three surfaces, one of which you had to
        # scroll a visualization to find. They are decisions, and decisions
        # are the Findings tab's job; the card reports, and that is all.
        accepted = 0
        for claim in _clean_strings(obj.get("hypotheses"), 3, 300):
            if hypotheses.propose(claim, cat["id"]) is None:
                log.info("dropping hypothesis (known, or queue full): %s", claim)
                continue
            accepted += 1
        learned = _clean_strings(obj.get("learned"), 3, 500)
        # Findings are a work list, not part of the card: what this run
        # reported lives in the store, which is the one place that knows
        # whether it has since been fixed or dismissed. Storing a copy on
        # the card would be a snapshot guaranteed to go stale.
        filed = findings_store.add_many([
            {**f, "source": cat["id"], "source_title": cat.get("title", "Insight")}
            for f in _model_findings(obj.get("findings"))])
        await _announce_findings(filed)
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
            "learned": learned,
            "tags": tags,
            "focus_used": cat.get("focus", "") if question is None else "",
            "html": html,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # `cost` is derived once, here, and stored — not recomputed in the
            # panel from `usage`. Which fields count against a session window
            # (and that a cache read does not) is a rule usage_store owns; a
            # second copy of it in JavaScript is a second answer waiting to
            # drift from the one the budget actually uses.
            "meta": {**result.get("meta", {}), "cost": cost},
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
        log.info("insight %s generated (%s)%s%s", insight_id, insight["title"],
                 f", {len(filed)} new finding(s)" if filed else "",
                 f", {accepted} hypothesis(es) queued" if accepted else "")
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        log.warning("insight %s failed: %s", insight_id, exc)
        journal.record("insight", journal.classify({"ok": False, "error": str(exc)}),
                       error=str(exc), extra={"id": insight_id})
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
            FIX_TIMEOUT_S, FIX_MAX_TURNS, "fix")
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
        noticed = findings_store.add_many([
            {"text": extra, "source": "fix",
             "source_title": f"Noticed while fixing “{finding['text']}”"}
            for extra in parsed["also_found"]])
        await _announce_findings(noticed)
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


# Why the scheduler is not scheduling, when it is not. Every gate already
# has a control surface (the auth chip, the paused chip, the pill's budget
# dot) — this is the READBACK, so "why did my cards stop updating" is a
# field in /api/status instead of one log line printed once. `checked_at`
# doubles as proof the loop itself is alive.
AUTO_STATE: dict = {"gate": None, "detail": "", "checked_at": 0.0}


def _set_gate(gate: str | None, detail: str = "") -> None:
    AUTO_STATE.update(gate=gate, detail=detail, checked_at=time.time())


def _next_due(eff: dict, generated_at: str, now: float) -> float | None:
    """When auto-refresh will next regenerate this category, epoch seconds.

    None means never (disabled, or interval 0 = manual only); a value at or
    before `now` means it is due and will queue on the next tick — the two
    read differently on a card and must not be conflated. Mirrors
    _refresh_due exactly: this is the same arithmetic asked "when" instead
    of "now?", and any drift between them makes the foot lie about the
    scheduler.
    """
    if not eff.get("enabled", True):
        return None
    schedule = eff.get("schedule")
    if isinstance(schedule, list) and schedule:
        if _schedule_due(schedule, generated_at, now):
            return now
        lt = time.localtime(now)
        future: list[float] = []
        for t in schedule:
            try:
                hh, mm = t.split(":")
                hh, mm = int(hh), int(mm)
            except ValueError:
                continue
            for day_off in (0, 1):
                stamp = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + day_off,
                                     hh, mm, 0, 0, 0, -1))
                if stamp > now:
                    future.append(stamp)
        return min(future) if future else None
    hours = eff.get("refresh_hours")
    if hours is None:
        hours = eff_refresh_hours()
    if hours <= 0:
        return None
    gen = _parse_generated_at(generated_at) if generated_at else None
    if gen is None:
        return now
    return max(now, gen + hours * 3600)


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
                log.info("swept %d finding(s) from study sessions", len(swept))
                await _announce_findings(swept)
        except Exception as exc:  # never let this kill the loop
            log.debug("findings sweep failed: %s", exc)
        if not engine.get_auth():
            _set_gate("no_auth")
            continue
        settings = settings_store.load()
        if not settings["auto_enabled"]:
            _set_gate("paused")
            continue
        # Nothing is scheduled before onboarding: there are no cards, and
        # generating one would be the canned-defaults behaviour this
        # replaced.
        if not settings.get("onboarded"):
            _set_gate("not_onboarded")
            continue
        budget = usage_store.budget_state(settings)
        if budget["blocked"]:
            _set_gate("budget",
                      f"session usage {budget['used_percent']:.0f}% ≥ "
                      f"budget {budget['budget_percent']}%")
            if not budget_logged:
                log.info(
                    "auto-refresh paused: session usage %.0f%% ≥ budget %d%% (%s)",
                    budget["used_percent"], budget["budget_percent"],
                    budget["source"])
                budget_logged = True
            continue
        budget_logged = False
        _set_gate(None)
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
    try:
        result = await asyncio.to_thread(engine.validate_auth)
        AUTH_CHECK.update(
            state="ok" if result["ok"] else "failed",
            error=result["error"],
            checked_at=time.time(),
        )
    finally:
        # The guard below is only a guard while this is honest about
        # finishing — including when validate_auth raises.
        AUTH_CHECK["running"] = False


def start_auth_check(announce: bool = True) -> bool:
    """Begin a verification, unless one is already running. True if started.

    `running` is flipped **here**, synchronously, rather than inside the
    coroutine. `asyncio.create_task` only schedules — nothing in it runs
    until the loop yields — so a guard reading state its own task has not
    set yet is no guard at all, and two callers in one tick both spawn a
    real `claude -p`. That was already reachable through the polled
    `h_setup_status`, and `/api/status` is polled far harder.

    `announce` is what separates a check somebody asked for from one that
    is merely due. A sign-in is a moment with a person in front of it and
    "Verifying Claude…" is the answer to what they just did; a six-hourly
    re-verification is not news, and a chip appearing unbidden in the top
    bar — shifting its layout — while somebody reads a card is the "a
    status chip that is permanently green does not belong there" rule with
    the timing changed. An unannounced check leaves the previous verdict
    standing until it has a new one, which is also the more honest answer:
    the last thing we actually established is the best we know.
    """
    if AUTH_CHECK.get("running"):
        return False
    AUTH_CHECK["running"] = True
    if announce:
        AUTH_CHECK.update(state="checking", error="")
    asyncio.create_task(_check_auth_bg())
    return True


def _auth_verdict_is_stale(now: float | None = None) -> bool:
    """True when the last verdict is old enough to be worth re-earning.

    An unchecked or in-flight state is not stale — the first has no verdict
    to age and the second is already earning one.
    """
    if AUTH_CHECK["state"] not in ("ok", "failed") or AUTH_CHECK.get("running"):
        return False
    now = time.time() if now is None else now
    return now - (AUTH_CHECK["checked_at"] or 0) >= AUTH_RECHECK_S


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
    now = time.time()
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
            "next_due": _next_due(c, insights.get(c["id"]) or "", now),
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
        # When the scheduler will come for this card — the readback of
        # _refresh_due, so the foot can say "next 7am" instead of leaving
        # "why did this stop updating" to the add-on log.
        "next_due": _next_due(eff, insights.get(c["id"]) or "", now),
        "job": {k: JOBS.get(c["id"], {}).get(k) for k in ("state", "error")},
    }


async def h_status(request: web.Request) -> web.Response:
    auth = engine.get_auth()
    # Re-earn a verdict that has gone stale. Lazy on purpose — see
    # AUTH_RECHECK_S: this is the one path a person looking at the panel
    # already drives, so the cost lands where somebody is asking and
    # nowhere else. `start_auth_check` is the guard against the poll
    # spawning a second check over an unfinished one.
    if auth and _auth_verdict_is_stale():
        start_auth_check(announce=False)
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
        # Why auto-refresh is idle, when it is — the same gates the chips
        # and the pill's dot report, readable as one field.
        "auto": dict(AUTO_STATE),
        "categories": [_category_status(c, insights) for c in all_categories()],
        # The Findings tab's badge: everything still waiting on a decision —
        # problems to settle and guesses to confirm, which are one list now.
        # Counted here rather than off _findings_payload() because /api/status
        # polls on a timer and open_count() reads raw entries without shaping
        # 200 findings to throw all but the length away.
        "findings_open": findings_store.open_count() + hypotheses.open_count(),
        # `question` lets the panel label an ad-hoc "Ask" card (and retry it)
        # while it's still generating, before any insight exists to read.
        # `prompt_chars`/`entities` are what the run is spending, carried so
        # a card can say it while the spinner is still turning.
        "jobs": {jid: {k: j.get(k) for k in
                       ("state", "error", "question", "prompt_chars", "entities")}
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
    atomic_write.write_json(path, insight)
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
        # A card with no stored insight is already in the state a purge wants.
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
    return _under(hdir, f"{ts}.json")


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
        # No token file yet: one is minted below.
        pass
    token = secrets.token_hex(16)
    CARD_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    CARD_TOKEN_FILE.write_text(token, encoding="utf-8")
    try:
        CARD_TOKEN_FILE.chmod(0o600)
    except OSError:
        # A token file whose mode will not set is still only reachable from
        # inside the container.
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


def _card_mirror_path(insight_id: str) -> Path | None:
    """Where one card's mirrored HTML lives, or None if the id isn't one.

    The mirror directory is under `/config/www`, which Home Assistant
    serves — so unlike the rest of the insight store, a name that escaped
    the directory would land somewhere the world can fetch. Both callers
    are best-effort and neither wants an exception, hence None rather
    than the `HTTPBadRequest` `_under` raises for a request handler.
    """
    if not _SAFE_ID.match(insight_id):
        return None
    try:
        return _under(WWW_CARD_DIR, _card_file_name(insight_id))
    except web.HTTPBadRequest:
        return None


def _mirror_card(insight: dict) -> None:
    """Best-effort mirror of one insight; a no-op until the dir exists."""
    if not WWW_CARD_DIR.is_dir():
        return
    html = insight.get("html")
    insight_id = str(insight.get("id") or "")
    path = _card_mirror_path(insight_id)
    if not isinstance(html, str) or not html or path is None:
        return
    try:
        atomic_write.write_text(path, html + _CARD_RELOAD_SNIPPET)
    except OSError as exc:
        log.debug("card mirror write failed: %s", exc)


def _unmirror_card(insight_id: str) -> None:
    if not WWW_CARD_DIR.is_dir():
        return
    path = _card_mirror_path(insight_id)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Best effort: the mirror is a copy, and a card whose stale HTML
        # outlives it shows up as a 404 on a dashboard, not as lost data.
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
        # A mirror that will not delete is swept again on the next sync.
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


# ---------------------------------------------------------------------------
# House checks — findings that cost nothing (panel/checks)
# ---------------------------------------------------------------------------

def eff_checks_interval_hours() -> float:
    """The `checks_interval_hours` option: live from the Supervisor when it
    can be read, the run.sh export otherwise. 0 means "never on a timer"."""
    snap = addon_options.snapshot() or {}
    raw = snap.get("checks_interval_hours",
                   os.environ.get("BRAIN_CHECKS_INTERVAL_HOURS", "6"))
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 6.0


def _record_overrides(snapshot: dict, now: float) -> int:
    """Keep the overrides this pass saw. Never fails the pass that saw them.

    `actions.py` persists nothing on purpose, and this is the deliberate
    exception: overrides are a handful of rows a week, and *"you undo
    this every weekday morning"* is a sentence about weeks that one day
    of logbook cannot produce. See `override_ledger`'s own docstring for
    why that is a narrower claim than the timeline this does not keep.
    """
    mined = snapshot.get("actions") or {}
    if not mined.get("available"):
        # "I could not look" is not "nothing happened" — the same rule
        # `clear_resolved` follows about a check that could not run.
        return 0
    try:
        return override_ledger.record(mined.get("overrides") or [], now)
    except Exception as exc:  # noqa: BLE001 — accounting must not fail
        # the pass it is accounting for; same rule as `journal.record`.
        log.warning("could not file this pass's overrides: %s", exc)
        return 0


def _record_rhythm(snapshot: dict, now: float) -> int:
    """File the first and last person-caused minute of each day this pass saw.

    Same shape and the same reason as `_record_overrides`: the window is
    a day and the question is about a fortnight, so somebody has to keep
    the two numbers a day reduces to. Two per day is not a timeline.
    """
    mined = snapshot.get("actions") or {}
    if not mined.get("available"):
        return 0
    try:
        tz, _name = baselines.house_timezone()
        return rhythm.record(mined.get("actions") or [], tz, now)
    except Exception as exc:  # noqa: BLE001 — accounting must not fail the
        # pass it is accounting for; same rule as `journal.record`.
        log.warning("could not file this pass's rhythm: %s", exc)
        return 0


async def run_checks(reason: str = "schedule") -> dict:
    """One pass of every house check, applied to the findings store.

    Three moves after the checks run, in this order: file what is new
    (``add_many`` dedupes against everything ever reported, so a re-report
    is silent), refresh the details of what is already on the list (the
    text is stable, the number in the detail is not), then clear open rows
    that a check which RAN no longer reports. Only checks that ran may
    clear — a check whose data could not be fetched said nothing, and
    nothing is not "the problem went away".

    A second caller while a pass is in flight gets the last summary back
    with an error rather than a second pass: two passes racing would file
    and clear against each other.
    """
    if CHECKS_STATE["running"]:
        return {"error": "a checks pass is already running",
                **(CHECKS_STATE["last"] or {})}
    CHECKS_STATE["running"] = True
    started = time.time()
    try:
        snapshot = await checks.snapshot.collect(started)
        # Filed BEFORE the checks run, so this pass's own overrides count
        # toward the pattern the check is about to read. The ledger is
        # deduped on the event, which is what makes that safe: passes run
        # every few hours over a day-long window, so the same override is
        # offered four or five times and only the first one lands.
        await asyncio.to_thread(_record_overrides, snapshot, started)
        await asyncio.to_thread(_record_rhythm, snapshot, started)
        result = checks.run_all(snapshot, started)

        def apply() -> tuple[list[dict], int, list[dict]]:
            created = findings_store.add_many(result["findings"])
            refreshed = findings_store.refresh_details(result["findings"])
            cleared = findings_store.clear_resolved(
                {checks.source_for(c) for c in result["ran"]},
                {findings_store.normalize(f["text"]) for f in result["findings"]})
            return created, refreshed, cleared

        created, refreshed, cleared = await asyncio.to_thread(apply)
        await _announce_findings(created)
        summary = {
            "reason": reason,
            "started_at": int(started),
            "finished_at": int(time.time()),
            "duration_s": round(time.time() - started, 1),
            "ran": result["ran"],
            "skipped": result["skipped"],
            "errors": result["errors"],
            "per_check": result["per_check"],
            "found": len(result["findings"]),
            "created": created,
            "refreshed": refreshed,
            "cleared": cleared,
            "snapshot_errors": snapshot.get("errors") or {},
        }
        journal.record(
            "checks", "ok" if not result["errors"] else "error",
            duration_s=summary["duration_s"],
            error="; ".join(f"{k}: {v}" for k, v in result["errors"].items()),
            extra={"ran": len(result["ran"]), "found": summary["found"],
                   "created": len(created), "cleared": len(cleared)})
        log.info("house checks (%s): %d ran, %d found, %d new, %d refreshed, "
                 "%d cleared%s", reason, len(result["ran"]), summary["found"],
                 len(created), refreshed, len(cleared),
                 (" — skipped " + ", ".join(result["skipped"]))
                 if result["skipped"] else "")
    except Exception as exc:  # noqa: BLE001 — a bad pass must not take the loop down
        log.warning("house checks failed: %s", exc)
        journal.record("checks", "error", error=str(exc))
        summary = {"reason": reason, "started_at": int(started),
                   "finished_at": int(time.time()), "error": str(exc)[:300],
                   "ran": [], "created": [], "cleared": [], "refreshed": 0,
                   "skipped": {}, "errors": {}, "per_check": {}, "found": 0,
                   "snapshot_errors": {}}
    finally:
        CHECKS_STATE["running"] = False
    CHECKS_STATE["last"] = summary
    await asyncio.to_thread(publish_diagnostics)
    return summary


async def _checks_loop() -> None:
    """Run the checks on the option's interval, and keep the diagnostics
    mirror fresh in between.

    The first pass waits for the panel to settle rather than racing the
    startup sequence for the recorder. After that the loop ticks every
    few minutes and asks whether a pass is due, so a manual run resets the
    clock and a Configuration-tab edit to the interval lands without a
    restart. An interval of 0 is "not on a timer": `brain check` and the
    tab's button still run one.
    """
    await asyncio.sleep(CHECKS_FIRST_DELAY_S)
    while True:
        try:
            hours = eff_checks_interval_hours()
            last = CHECKS_STATE["last"]
            due = hours > 0 and (
                not last or time.time() - last.get("finished_at", 0) >= hours * 3600)
            if due and not CHECKS_STATE["running"]:
                await run_checks("schedule")
            elif time.time() - DIAG_STATE["published_at"] >= DIAGNOSTICS_PUBLISH_S:
                await asyncio.to_thread(publish_diagnostics)
        except Exception as exc:  # noqa: BLE001 — never let this kill the loop
            log.debug("checks loop: %s", exc)
        await asyncio.sleep(CHECKS_TICK_S)


# Nightly. A baseline describes weeks, so measuring it more often buys
# nothing and costs a statistics query over every numeric sensor in the
# house; measuring it less often lets it describe a house that has
# changed. `base.stale` is what reports this loop having stopped.
BASELINE_INTERVAL_S = 24 * 3600
BASELINE_FIRST_DELAY_S = 300
BASELINE_STATE: dict = {"running": False, "last": None}


async def build_baselines(reason: str = "schedule") -> dict:
    """Measure what is normal in this house, and write the store.

    Separate from the checks pass on purpose: this reads hourly
    statistics for a month over every numeric sensor, which is minutes of
    recorder work, and the answer changes over weeks. The checks pass
    only ever *reads* what this leaves.
    """
    if BASELINE_STATE["running"]:
        return {"error": "a baseline pass is already running",
                **(BASELINE_STATE["last"] or {})}
    BASELINE_STATE["running"] = True
    started = time.time()
    try:
        import aiohttp

        import ha_data  # deferred so the module loads without aiohttp in tests
        async with aiohttp.ClientSession() as session:
            states = await ha_data._rest_get(session, "/states", timeout=60)
            by_id = {s["entity_id"]: s for s in (states or [])
                     if isinstance(s, dict) and s.get("entity_id")}
            payload = await baselines.build(session, by_id, started)
        summary = {"reason": reason, "started_at": int(started),
                   "finished_at": int(time.time()),
                   "duration_s": round(time.time() - started, 1),
                   "measured": len(payload.get("entities") or {}),
                   "asked": payload.get("asked", 0),
                   "tz": payload.get("tz", ""), "error": ""}
        journal.record("baselines", "ok", duration_s=summary["duration_s"],
                       extra={"measured": summary["measured"],
                              "asked": summary["asked"]})
    except Exception as exc:  # noqa: BLE001 — a bad pass must not take the loop down
        log.warning("baseline pass failed: %s", exc)
        journal.record("baselines", "error", error=str(exc))
        summary = {"reason": reason, "started_at": int(started),
                   "finished_at": int(time.time()), "measured": 0, "asked": 0,
                   "tz": "", "error": str(exc)[:300]}
    finally:
        BASELINE_STATE["running"] = False
    BASELINE_STATE["last"] = summary
    return summary


async def _baseline_loop() -> None:
    """Rebuild the baselines nightly, starting once the panel has settled."""
    await asyncio.sleep(BASELINE_FIRST_DELAY_S)
    while True:
        try:
            store = await asyncio.to_thread(baselines.load)
            age = baselines.age_days(store)
            # A store that has never been written has no age, and that is
            # the case this loop exists for: the first pass on a fresh
            # install, not a rebuild.
            if age is None or age * 86400 >= BASELINE_INTERVAL_S:
                await build_baselines("schedule")
        except Exception as exc:  # noqa: BLE001
            log.debug("baseline loop: %s", exc)
        await asyncio.sleep(3600)


async def h_baselines(request: web.Request) -> web.Response:
    """What brAIn thinks is normal, as numbers rather than as a verdict."""
    store = await asyncio.to_thread(baselines.load)
    entity_id = (request.query.get("entity_id") or "").strip()
    payload = {
        "built_at": store.get("built_at", 0),
        "tz": store.get("tz", ""),
        "days": store.get("days", baselines.HISTORY_DAYS),
        "measured": len(store.get("entities") or {}),
        "stale": baselines.is_stale(store) if store.get("built_at") else True,
        "running": BASELINE_STATE["running"],
        "last": BASELINE_STATE["last"],
    }
    if entity_id:
        if not actions.is_entity_id(entity_id):
            return web.json_response({"error": "not an entity id", **payload},
                                     status=400)
        payload["entity_id"] = entity_id
        payload["baseline"] = (store.get("entities") or {}).get(entity_id)
    return web.json_response(payload)


async def h_baselines_run(request: web.Request) -> web.Response:
    summary = await build_baselines("manual")
    status = 409 if summary.get("error", "").startswith("a baseline pass") else 200
    return web.json_response(summary, status=status)


async def h_checks(request: web.Request) -> web.Response:
    return web.json_response({
        "catalog": [{"id": c["id"], "title": c["title"],
                     "group": checks.title_for(c["id"])} for c in checks.CHECKS],
        "last": CHECKS_STATE["last"],
        "running": CHECKS_STATE["running"],
        "interval_hours": eff_checks_interval_hours(),
    })


async def h_checks_run(request: web.Request) -> web.Response:
    summary = await run_checks("manual")
    status = 409 if summary.get("error") == "a checks pass is already running" else 200
    return web.json_response(summary, status=status)


# ---------------------------------------------------------------------------
# Activity — what changed, and what changed it
# ---------------------------------------------------------------------------

# How LONG a window may be, which is not how far back it may reach. A
# logbook fetch is unfiltered — a week of a busy house is tens of
# megabytes of JSON through a Pi — so the window stays short and `end` is
# what reaches back, which is also how the tab pages a day at a time.
ACTIVITY_MAX_HOURS = 48
ACTIVITY_DEFAULT_HOURS = 24


def _activity_window(request: web.Request) -> tuple[float, float]:
    """The window a request asked for, as (start, end) epoch seconds.

    ``end`` lets the tab page backwards through days without the client
    and the server disagreeing about where a day begins — the browser
    knows the viewer's timezone and the panel does not.
    """
    now = time.time()
    try:
        hours = float(request.query.get("hours") or ACTIVITY_DEFAULT_HOURS)
    except ValueError:
        hours = ACTIVITY_DEFAULT_HOURS
    hours = max(1.0, min(ACTIVITY_MAX_HOURS, hours))
    try:
        end = float(request.query.get("end") or now)
    except ValueError:
        end = now
    end = min(end, now)
    return end - hours * 3600, end


async def _activity(start: float, end: float, entity_id: str = "") -> dict:
    import aiohttp
    async with aiohttp.ClientSession() as session:
        users = await checks.snapshot._users(session)
        return await actions.collect(session, start, end, users, entity_id)


async def h_activity(request: web.Request) -> web.Response:
    """A window of the house's own history, with a cause on every row.

    Fetched per request and never cached: this is a question somebody is
    asking now, the answer changes every few seconds, and a cache would be
    a second copy of the logbook to keep true.
    """
    start, end = _activity_window(request)
    try:
        mined = await _activity(start, end)
    except Exception as exc:  # noqa: BLE001 — a failed look is an answer
        log.warning("activity fetch failed: %s", exc)
        return web.json_response({"available": False, "error": str(exc)[:200],
                                  "actions": [], "overrides": [],
                                  "counts": {}, "start": start, "end": end})
    cause = (request.query.get("cause") or "").strip()
    if cause and cause in actions.CAUSES:
        mined = dict(mined)
        mined["actions"] = [a for a in mined["actions"] if a["cause"] == cause]
    limit = 400
    try:
        limit = max(1, min(2000, int(request.query.get("limit") or limit)))
    except ValueError:
        # A typed limit is a preference, not a request. Refusing the whole
        # window over an unparseable one would be a blank tab.
        pass
    rows = sorted(mined["actions"], key=lambda a: a["ts"], reverse=True)
    mined = dict(mined)
    # The count is of everything in the window; the list is capped. Two
    # numbers that disagree quietly is what the memory queue's list and
    # count were, so the cap is reported rather than applied silently.
    mined["total"] = len(rows)
    mined["actions"] = rows[:limit]
    mined["causes"] = list(actions.CAUSES)
    # The window that was actually used, not the one that was asked for: a
    # request for a week gets two days, and a caller echoing its own
    # argument would report a window it never had.
    mined["hours"] = _window_hours(mined["start"], mined["end"])
    return web.json_response(mined)


async def h_activity_entity(request: web.Request) -> web.Response:
    """Why one entity is the way it is: its recent changes and their causes.

    The deterministic half of "why did that happen". What is left — whether
    the automation that did it was right to — is a question for the model,
    and it answers it from this rather than from a state with no cause on
    it.
    """
    entity_id = request.match_info["entity_id"]
    # Validated at the edge, before it can reach a URL this process asks
    # Core for. An id that is not an entity id is not a house this cannot
    # read — it is a request that was never answerable.
    if not actions.is_entity_id(entity_id):
        return web.json_response(
            {"error": "not an entity id", "entity_id": entity_id[:64],
             "changes": [], "available": False}, status=400)
    start, end = _activity_window(request)
    try:
        # Filtered at the logbook rather than after it: this is a per-row
        # press on a list that may be hundreds of rows long, and re-reading
        # the whole window for one entity is the difference between a tap
        # and a wait on the hardware most of these run on.
        mined = await _activity(start, end, entity_id)
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"available": False, "error": str(exc)[:200],
                                  "entity_id": entity_id, "changes": []})
    return web.json_response({
        "available": mined["available"],
        "error": mined.get("error") or "",
        "entity_id": entity_id,
        "start": start, "end": end,
        "changes": actions.explain(mined["actions"], entity_id),
    })


def _window_hours(start: float, end: float) -> float:
    return round((end - start) / 3600.0, 2)


# ---------------------------------------------------------------------------
# Diagnostics — what a bug report needs, in one payload
# ---------------------------------------------------------------------------

def _cli_version() -> str:
    """`claude --version`, probed once per process."""
    if _CLI_VERSION["value"] is None:
        try:
            out = subprocess.run(["claude", "--version"], capture_output=True,
                                 text=True, timeout=15)
            _CLI_VERSION["value"] = (out.stdout or out.stderr or "").strip().splitlines()[0][:80] \
                if (out.stdout or out.stderr) else "unknown"
        except (OSError, subprocess.SubprocessError, IndexError):
            _CLI_VERSION["value"] = "unknown"
    return _CLI_VERSION["value"]


_OPTION_SECRET_WORDS = ("token", "password", "secret", "api_key", "credential")


def _diagnostics_payload() -> dict:
    """Versions, options, the journal's last day, the stores' shapes, the
    last checks pass, the daemon roll-call and the auth verdict.

    No prompts, no replies, no entity states — the shape of what happened,
    never the house itself. Error strings pass through journal.scrub. The
    same payload is served on /api/diagnostics, written to the shared
    volume for the integration's Download-diagnostics button, and bundled
    by `brain report`, so there is one answer to "what state is brAIn in".
    """
    settings = settings_store.load()
    options = addon_options.snapshot() or {}
    safe_options = {k: v for k, v in options.items()
                    if not any(w in k for w in _OPTION_SECRET_WORDS)}
    listing = findings_store.listing()
    rows = listing.get("findings") or []
    by_status: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for f in rows:
        by_status[f.get("status", "?")] = by_status.get(f.get("status", "?"), 0) + 1
        by_severity[f.get("severity", "?")] = by_severity.get(f.get("severity", "?"), 0) + 1
    try:
        memory_bytes = SHARED_MEMORY_FILE.stat().st_size
    except OSError:
        memory_bytes = 0
    try:
        usage = usage_store.budget_state(settings)
    except Exception:  # noqa: BLE001 — a diagnostics payload must not fail on one reader
        usage = {}
    _baseline_store = baselines.load()
    payload = {
        "generated_at": int(time.time()),
        "versions": {
            "addon": os.environ.get("ADDON_VERSION", "dev"),
            "claude_cli": _cli_version(),
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "options": safe_options,
        "settings": {k: settings.get(k) for k in (
            "auto_enabled", "plan", "budget_percent", "gather_mode",
            "terminal_ui", "onboarded", "chat_model")},
        "auth": {
            "state": AUTH_CHECK.get("state"),
            "checked_at": AUTH_CHECK.get("checked_at"),
            "error": journal.scrub(AUTH_CHECK.get("error") or ""),
        },
        "journal": journal.summary(24),
        "journal_tail": journal.tail(30),
        "findings": {
            "open": listing.get("open", 0),
            "by_status": by_status,
            "by_severity": by_severity,
            "settled": len(findings_store.settled_listing()),
            "scorecard": findings_store.scorecard(),
        },
        "memory": {
            "document_bytes": memory_bytes,
            "hypotheses_open": len(hypotheses.list_all("open")),
        },
        "checks": CHECKS_STATE["last"],
        # Numbers, not the buckets: a bug report needs to know whether the
        # house has been measured and when, not a month of hourly medians
        # for four hundred sensors.
        "baselines": {
            "built_at": _baseline_store.get("built_at", 0),
            "measured": len(_baseline_store.get("entities") or {}),
            "tz": _baseline_store.get("tz", ""),
            "stale": (baselines.is_stale(_baseline_store)
                      if _baseline_store.get("built_at") else True),
            "last": BASELINE_STATE["last"],
        },
        # A hold queue nobody can see is a queue that silently swallows.
        # The count and the oldest stamp are what tell "quiet hours are
        # working" apart from "the flush loop has died holding four
        # findings since Tuesday" — which is the failure this file exists
        # to make visible from outside.
        "notify": _notify_diagnostics(),
        # The two things that decide when a person hears from brAIn, and
        # both are invisible from outside: a rhythm that never gathered
        # enough days looks exactly like one that did and chose 07:00.
        "rhythm": _rhythm_diagnostics(),
        "daemons": _daemon_rollcall(),
        "usage": {k: usage.get(k) for k in ("source", "used_percent", "limits")},
    }
    # Derived last, from everything above it. The verdict is part of the
    # payload rather than a route of its own so that the panel, the mirror,
    # the integration's sensor and `brain report` cannot disagree about
    # whether brAIn is working — which is exactly the kind of drift a second
    # copy of a rule produces.
    payload["health"] = health.verdict(payload, safe_options)
    return payload


def publish_diagnostics() -> None:
    """Write the payload to the shared volume. Skipped on a dev checkout
    (no /config), logged and swallowed otherwise: the mirror is derived."""
    DIAG_STATE["published_at"] = time.time()
    if not DIAGNOSTICS_FILE.parent.parent.exists():
        return
    try:
        DIAGNOSTICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(DIAGNOSTICS_FILE, _diagnostics_payload())
    except Exception as exc:  # noqa: BLE001
        log.debug("diagnostics mirror write failed: %s", exc)


async def h_diagnostics(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_diagnostics_payload))


def _findings_payload() -> dict:
    """What the Findings tab reads — and the ONLY thing it reads.

    There is one list of things waiting on a person, and this is it. A
    finding is something brAIn thinks is broken; a hypothesis is something
    it thinks is true and wants confirmed. They are different kinds of
    knowledge (see findings_store's header) and they are still stored apart,
    but they are the same *job* — a decision only the homeowner can make —
    and splitting that job across two tabs meant neither list was ever
    empty and neither badge meant "you're done".

    So the open count spans both: it is the answer to "how much is waiting
    on me", which is the only question a badge on a work list can be asked.
    """
    payload = findings_store.listing()
    open_claims = hypotheses.list_all("open")
    payload["hypotheses"] = open_claims
    payload["open"] += len(open_claims)
    # How right each producer has been, from the endings people gave. It
    # rides this payload rather than its own route because it is read in
    # exactly one place — a line under the filter chips — and a number
    # about the list belongs with the list.
    payload["scorecard"] = findings_store.scorecard()
    return payload


async def h_findings(request: web.Request) -> web.Response:
    # The scheduler owns ingestion; sweeping here too is only about latency,
    # so opening the tab right after a study session finishes doesn't wait
    # out the tick. Both are idempotent, and an empty inbox costs one glob.
    def listing() -> tuple[list[dict], dict]:
        return findings_store.sweep_inbox(), _findings_payload()

    swept, payload = await asyncio.to_thread(listing)
    # The tab is open in front of somebody, but the phone still gets the
    # courtesy copy: whoever configured the notify target may not be the
    # person looking, and add_many's dedup means this can't ring twice.
    await _announce_findings(swept)
    return web.json_response(payload)


# The lifecycle buttons. Three of them END a finding, and ending one is the
# same three moves every time: write the answer into memory, remember the
# key so the analyst never raises it again, delete the row. Keeping that in
# one table means the three endings cannot drift into three behaviours.
#
# `memory` is what the home now knows, phrased as a fact rather than as an
# event on a list — `memory.md` is read by a model that has never seen this
# tab. An empty one means the answer is already in memory (the fixer wrote
# it when it made the change) and saying it twice would be the duplicate.
#
# `noted` is the same ending when the homeowner typed a reason, and it is
# deliberately not the same sentence — nor is it the same KIND of thing at
# every ending, which is why `source` is per-verb rather than "a note means
# a correction". Waving a report off is evidence that brAIn has misread the
# house, and the durable part is what they said about the house rather than
# the report; saying how you fixed something corrects nothing, and is simply
# more of the fact you were already recording.
FINDING_VERBS = {
    # "You've got this wrong", or "that's normal here" — the same ending
    # either way, because both mean *stop reporting this*. The optional note
    # is why, in the homeowner's words, and it is the half that teaches.
    "wrong": {"kind": "ignored",
              "memory": "Not a problem in this home: {text}",
              "noted": 'brAIn reported: "{text}". The homeowner says that is '
                       "not a problem here, because: {note}",
              "source": "correction"},
    # "I already handled it myself" — the ending for anything needing hands,
    # and the one where what you did is worth more than that you did it. "I
    # fixed it" leaves brAIn knowing a problem is over; "replaced the CR2032,
    # it's a 3-monthly job on that sensor" leaves it knowing the house.
    "done": {"kind": "fixed",
             "memory": "Fixed by the homeowner on {date}: {text}",
             "noted": "Fixed by the homeowner on {date}: {text}. They said: "
                      "{note}",
             "source": "homeowner"},
    # "I've read what brAIn changed" — the ending for an automated fix,
    # which already wrote its own memory line when it made the change.
    "ack": {"kind": "fixed", "memory": ""},
    # Not an ending: puts a legacy row (dismissed before the ledger existed,
    # and still on disk) back on the list.
    "reopen": {"status": "open"},
}
# What it used to be called, kept because a panel served before an update
# is still open in somebody's browser and its buttons must not 404.
FINDING_VERBS["ignore"] = FINDING_VERBS["wrong"]


async def _json_body(request: web.Request) -> dict:
    """The request body as a dict, or {} — never a crash.

    A JSON array or string parses fine and is truthy, so the old
    `(body or {}).get(...)` raised AttributeError on it — malformed client
    input surfacing as an unhandled 500 instead of being ignored like an
    absent body.
    """
    if not request.can_read_body:
        return {}
    try:
        body = await request.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


async def h_finding_verb(request: web.Request) -> web.Response:
    verb = request.match_info["verb"]
    spec = FINDING_VERBS.get(verb)
    if spec is None:
        raise web.HTTPNotFound(text="no such action")
    finding = _finding_or_404(request)
    body = await _json_body(request)
    note = str((body or {}).get("note") or "").strip()[:findings_store.MAX_NOTE]

    if "status" in spec:
        def move() -> dict:
            findings_store.set_status(finding["ts"], spec["status"])
            return _findings_payload()

        return web.json_response(await asyncio.to_thread(move))

    def settle() -> dict:
        findings_store.settle_and_clear(finding["ts"], spec["kind"], note=note)
        return _findings_payload()

    payload = await asyncio.to_thread(settle)
    # A note only changes the sentence for endings that have a second one to
    # offer. "Got it" plus a comment is still "Got it": falling back to
    # `memory` is what stops a note silently costing the memory line.
    template = spec["noted"] if note and spec.get("noted") else spec["memory"]
    fact = ""
    if template:
        fact = template.format(text=finding["text"], note=note,
                               date=time.strftime("%Y-%m-%d"))
        await _submit_memory(fact, source=spec.get("source", "homeowner"))
    # Both endings delete the row, which is the point of them and also the
    # reason this exists: they sit next to each other and mean opposite
    # things, so a mis-tap is not hypothetical and there is nothing to put
    # back by hand.
    payload["undo"] = undo_store.record(
        "finding", finding=finding, key=findings_store.normalize(finding["text"]),
        fact=fact, fact_source=spec.get("source", "homeowner"))
    return web.json_response(payload)


async def h_undo(request: web.Request) -> web.Response:
    """Put back what the last press took away.

    Everything reversed here happened within the last few minutes and has
    not been consolidated yet, which is what makes it reversible: the memory
    line is still a line in the inbox, the settled key is still only
    suppressing future runs, and the row's id is still free. Once a
    consolidation has run the fact is in the document and this stops being
    able to help — which is why the token expires, rather than pretending.

    Not offered for Fix it: that starts a Claude run against the actual
    house, and an "undo" that only took the card back would be a lie about
    what it undid. Not offered for Remind me later either — it did not take
    anything away, and it already has "Bring it back now".
    """
    entry = undo_store.take(request.match_info["token"])
    if entry is None:
        raise web.HTTPNotFound(text="that's expired — nothing to undo")

    if entry["kind"] == "conversation":
        # A deleted conversation is a file in the trash, and putting it
        # back is a move — none of the findings machinery below applies.
        restored = await asyncio.to_thread(
            conversations.restore_deleted, entry)
        return web.json_response({"undone": restored,
                                  "restored_conversation": entry["id"]})

    if entry["kind"] == "conversations":
        # A batch delete's Undo: every row goes back, each by the same move
        # the single restore makes. Partial success is reported as such —
        # "undone" only when the whole batch made it, because "Put back"
        # over a half-restored list is a lie about the other half.
        def restore_all() -> int:
            return sum(1 for e in entry["entries"]
                       if conversations.restore_deleted(e))
        count = await asyncio.to_thread(restore_all)
        return web.json_response({
            "undone": count == len(entry["entries"]),
            "restored_conversation": count > 0,
            "restored_count": count,
            "restore_total": len(entry["entries"]),
        })

    def reverse() -> tuple[bool, dict]:
        if entry["kind"] == "finding":
            # The row may have been re-reported in the meantime, in which
            # case the list already holds a newer version of it and putting
            # this one back would throw away whatever has happened since.
            restored = findings_store.restore(entry["finding"]) is not None
            if entry.get("key"):
                findings_store.unsettle(entry["key"])
        else:
            restored = hypotheses.reopen(entry["ts"]) is not None
            # A rejected guess also went into the ask-history as a dead end.
            # Leaving that behind would put the claim back on the list and
            # make it un-proposable for ever after.
            for q in knowledge_store.list_questions():
                if (entry.get("question")
                        and knowledge_store.normalize(q["text"])
                        == knowledge_store.normalize(entry["question"])):
                    knowledge_store.remove_question(q["ts"])
        # The memory line has not been consolidated (the token is younger
        # than any pass), so it is still a line in the inbox and comes out
        # the same way a queued fact does from the Memory tab.
        if entry.get("fact"):
            _drop_from_inbox(_inbox_id(entry["fact_source"], entry["fact"]))
        return restored, _findings_payload()

    restored, payload = await asyncio.to_thread(reverse)
    payload["undone"] = restored
    return web.json_response(payload)


async def h_finding_unsettle(request: web.Request) -> web.Response:
    """Let brAIn raise an answered problem again.

    The row is long gone, so there is nothing to put back — what this undoes
    is the suppression, and the next analysis is free to find it again if it
    is still there. That is the honest version of "I changed my mind": if it
    really has stopped being true, nothing comes back.
    """
    body = await _json_body(request)
    key = str((body or {}).get("key") or "").strip()
    if not key:
        raise web.HTTPBadRequest(text="which one?")

    def undo() -> tuple[bool, dict]:
        ok = findings_store.unsettle(key)
        return ok, _findings_payload()

    ok, payload = await asyncio.to_thread(undo)
    if not ok:
        raise web.HTTPNotFound(text="nothing settled under that")
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
    body = await _json_body(request)
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
        return _findings_payload()

    return web.json_response(await asyncio.to_thread(settle))


# What the chat is handed when you press Discuss. It says "look, don't
# touch": the discussion is for understanding the thing, and Fix it is still
# the only button that authorises a change — which stays on screen while you
# talk, so agreeing to it is one press away rather than a trip back.
# The first line is load-bearing twice over: it is what the chat bubble
# leads with, and — because a conversation's title is its first genuine
# user message — it is what the Chats rail calls the conversation. The old
# opener ("I want to talk about something you flagged…") titled every
# discussion identically, so a rail of three discussions was three copies
# of the same sentence with the finding buried mid-message.
DISCUSS_PROMPT = """Discussing: {text}
{detail}{fix}{entity}
Severity: {severity}

You flagged this as broken in my home. Look into it and tell me what is
actually going on — check the current state and the history before you
answer, and say plainly whether you think it is really a problem here.
Do not change anything yet; I will decide."""


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
        return _findings_payload()

    return web.json_response(await asyncio.to_thread(claim))


async def h_finding_delete(request: web.Request) -> web.Response:
    """Forget it entirely — unlike Wrong, it can be reported again."""
    finding = _finding_or_404(request)

    def forget() -> dict:
        findings_store.remove(finding["ts"])
        return _findings_payload()

    payload = await asyncio.to_thread(forget)
    # No key and no fact: Dismiss teaches nothing, so there is nothing to
    # unteach — only the row to put back.
    payload["undo"] = undo_store.record("finding", finding=finding,
                                        fact="", fact_source="")
    return web.json_response(payload)


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


# -- knowledge (the analyst's viewable memory) ------------------------------

def _read_shared_memory() -> str:
    try:
        return SHARED_MEMORY_FILE.read_text(
            encoding="utf-8", errors="replace")[:MAX_MEMORY_CHARS]
    except OSError:
        return ""


def _write_shared_memory(text: str) -> None:
    atomic_write.write_text(SHARED_MEMORY_FILE, text)


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


# `FORGET:` lines are still a thing the consolidator understands — `brain
# memory forget` writes them from the terminal — but the panel no longer
# does. Its ✕ acts on the filing queue, where the fact has not reached the
# document yet and there is nothing to strike from it; a line already in
# memory.md is edited out of memory.md, in the editor beside the queue.


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
        # `exc` is whatever the bundle collector hit, so its text is not
        # ours and is not written for anyone to read. The log gets it; the
        # response gets the one sentence that tells the user what to do.
        log.warning("onboarding bundle failed: %s", exc, exc_info=True)
        raise web.HTTPBadGateway(text="could not read Home Assistant")

    prompt = onboarding.build_prompt(memory, bundle)
    # Claimed as a card run: it proposes the card set, and "everything
    # brAIn sent to Claude about the house" should include it.
    result = await asyncio.to_thread(
        engine.run_claude, prompt, onboarding.RECOMMEND_SYSTEM, eff_model(),
        TIMEOUT_S, 4, "card")
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


def _last_consolidated() -> int:
    """When the consolidator last completed a pass (epoch seconds, 0 = never)."""
    try:
        return int(MEMORY_MARKER_FILE.stat().st_mtime)
    except OSError:
        return 0


def _inbox_id(source: str, fact: str) -> str:
    """A stable id for one queued line, derived from what it says.

    The inbox is append-only JSONL written by half a dozen callers, none of
    which stamps an id, and `ts` is not unique — an insight run queues three
    facts inside the same second. Content is what identifies a line here:
    two lines that say the same thing from the same source ARE the same
    fact, and deleting one should take both.
    """
    return hashlib.sha256(
        f"{source}\x00{fact}".encode("utf-8", "replace")).hexdigest()[:16]


def _inbox_lines() -> list[tuple[Path, dict]]:
    """Every queued line with the file it came from, oldest file first."""
    out: list[tuple[Path, dict]] = []
    try:
        paths = sorted(MEMORY_INBOX_DIR.glob("*.jsonl"))
    except OSError:
        return out
    for path in paths:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                # A torn line is not a fact. It must not take the tab down,
                # and it must not be counted as something waiting either.
                continue
            if isinstance(obj, dict) and str(obj.get("fact") or "").strip():
                out.append((path, obj))
    return out


def _inbox_items(limit: int = INBOX_LIST_MAX) -> list[dict]:
    """What is actually waiting for the consolidator, newest last.

    This is THE queue — the same lines the consolidator will read, not a
    reconstruction of them. The Memory tab used to derive its list from the
    facts ledger instead, keeping anything whose `ts` postdated the last
    consolidation, which is a different population entirely: the ledger only
    holds what the ANALYST discovered, while the inbox holds that plus
    corrections, confirmed guesses, facts taught from the panel, voice,
    study sessions and anything another add-on dropped in /share. So the
    count said nine and the list showed four, and neither was wrong — they
    were answers to different questions.
    """
    seen: set[str] = set()
    items: list[dict] = []
    for _path, obj in _inbox_lines():
        fact = str(obj["fact"]).strip()
        source = str(obj.get("source") or "")
        key = _inbox_id(source, fact)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "id": key,
            "ts": int(obj.get("ts") or 0),
            "source": source,
            "text": fact[:MAX_INBOX_TEXT],
            "confidence": str(obj.get("confidence") or ""),
        })
    return items[-limit:]


def _inbox_pending() -> int:
    """How many DISTINCT facts are waiting — the number beside the button.

    Distinct, because that is what the list shows and the two have to agree:
    a fact queued twice (a study session re-filing what an insight run
    already queued) is one thing waiting, not two.
    """
    return len({_inbox_id(str(o.get("source") or ""), str(o["fact"]).strip())
                for _p, o in _inbox_lines()})


def _drop_from_inbox(item_id: str) -> bool:
    """Take a fact out of the queue before it reaches the document.

    Nothing is queued for removal afterwards: an inbox line has by
    definition never been filed (the consolidator archives what it consumes),
    so there is nothing in memory.md to forget. That is the difference from
    deleting a fact the document already holds.
    """
    kept: dict[Path, list[dict]] = {}
    dropped: set[Path] = set()
    for path, obj in _inbox_lines():
        if _inbox_id(str(obj.get("source") or ""),
                     str(obj["fact"]).strip()) == item_id:
            dropped.add(path)
        else:
            kept.setdefault(path, []).append(obj)
    if not dropped:
        return False
    # Only the files that actually held it are rewritten. Rewriting the rest
    # would drop any torn line they carry, which _inbox_lines skips over —
    # tidying a file we had no reason to touch is not this function's job.
    for path in dropped:
        lines = kept.get(path, [])
        try:
            if lines:
                atomic_write.write_lines(path, lines)
            else:
                path.unlink()
        except OSError as exc:
            # Best effort: a line we could not remove is filed at the next
            # pass, which is the old behaviour and not a data loss.
            log.debug("inbox rewrite failed for %s: %s", path, exc)
    return True


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
    # Only meaningful while a pass is actually in flight; a marker left by a
    # killed one would otherwise read as a pass running since last Tuesday.
    state["running_for"] = _consolidation_running_for() if running else 0
    state["stale_hours"] = _consolidation_stale_hours()
    # A failure we remember is only news until something else succeeds. The
    # daemon's passes never touch MEMORY_STATE — it only knows about ours —
    # so without this the tab would keep showing the reason one pass failed
    # long after the next one had quietly filed everything.
    if state.get("error") and _last_consolidated() > int(state.get("done_at") or 0):
        state["error"] = ""
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
    """Everything the analyst has learned, in one payload for the panel.

    `hypotheses` is still here and is still the open queue — the Memory tab
    no longer renders it (guesses to confirm are decisions, and decisions
    live on the Findings tab), but the budget is what the prompt builder
    asks for and the list is what `brain memory hypotheses` prints.
    """
    def queue() -> tuple[list[dict], int]:
        # One read for the list and its count, so the two cannot disagree —
        # which is exactly how "9 things waiting" came to sit above 4 cards.
        return _inbox_items(), _inbox_pending()

    inbox, pending = await asyncio.to_thread(queue)
    return web.json_response({
        "inbox": inbox,
        "questions": knowledge_store.list_questions(),
        "hypotheses": hypotheses.list_all("open"),
        "hypothesis_budget": hypotheses.budget(),
        "shared_memory": _read_shared_memory(),
        "memory_state": await asyncio.to_thread(_memory_state),
        "inbox_pending": pending,
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
        proc = subprocess.Popen(
            ["bash", CONSOLIDATE_SCRIPT, "--once"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            env={**os.environ, "HOME": engine.CLAUDE_HOME},
        )
    except OSError as exc:
        return False, f"could not run the consolidator: {exc}"

    # The pass's own [brain-memory] lines go to the add-on log as they are
    # written, exactly like the daemon's. They used to be captured into a
    # local variable and dropped on the floor unless the script exited
    # non-zero — while the failure the panel reported told you to go read
    # them in a log they had never reached. A pass can run for minutes, so
    # this streams rather than collecting: "consolidating 45 fact(s)..."
    # is worth having while it happens, not after.
    timed_out = threading.Event()

    def _kill() -> None:
        timed_out.set()
        proc.kill()

    killer = threading.Timer(CONSOLIDATE_TIMEOUT_S, _kill)
    killer.start()
    tail: list[str] = []
    try:
        for raw in proc.stdout or ():
            line = raw.rstrip()
            if not line:
                continue
            log.info("%s", line)
            tail.append(line)
            del tail[:-20]
        rc = proc.wait()
    finally:
        killer.cancel()
        if proc.stdout:
            proc.stdout.close()

    if timed_out.is_set():
        return False, f"consolidation passed its {CONSOLIDATE_TIMEOUT_S}s limit"
    if rc == CONSOLIDATE_BUSY_RC:
        return False, ("another consolidation is already running — "
                       + "give it a moment and press it again")
    if rc != 0:
        return False, (tail[-1][:300] if tail else
                       f"the consolidator exited {rc}")
    return True, ""


async def h_memory_state(request: web.Request) -> web.Response:
    """Just "is a pass running, and how did the last one go".

    The Memory tab polls while a pass is in flight, and it used to poll
    /api/knowledge — 19 KB of facts, hypotheses and the whole memory
    document, every 2.5 seconds, to find out whether a flag had flipped.
    This is the flag. The document is re-read once, when it changes.
    """
    return web.json_response({
        "memory_state": await asyncio.to_thread(_memory_state),
        "inbox_pending": await asyncio.to_thread(_inbox_pending),
    })


async def _consolidate_task() -> None:
    """One pass, in the background, reporting through MEMORY_STATE.

    What we report is what the queue actually did, not what we asked it to
    do: the consolidator leaves the inbox pending on every failure it can
    detect, and some of those failures still exit 0. Counting the queue
    either side of the pass is the only honest measure of "filed".
    """
    before = await asyncio.to_thread(_inbox_pending)
    try:
        ok, error = await asyncio.to_thread(_consolidate_now)
        after = await asyncio.to_thread(_inbox_pending)
        drained = max(0, before - after)
        if ok and before and not drained:
            ok, error = False, (
                "the consolidator finished but the queue didn't move — see "
                + "the add-on log's [brain-memory] lines for why it kept "
                + "the facts")
        if not ok:
            log.warning("consolidation failed: %s", error)
        MEMORY_STATE.update(error="" if ok else (error or "consolidation failed"),
                            filed=drained)
    except Exception as exc:                       # never leave it "merging"
        log.exception("consolidation crashed")
        MEMORY_STATE.update(error=str(exc), filed=0)
    finally:
        MEMORY_STATE.update(merging=False, done_at=int(time.time()))


async def h_memory_consolidate(request: web.Request) -> web.Response:
    """Fold the inbox into memory.md now, rather than at the next pass.

    Started, not awaited. A pass rewrites the whole document with a Claude
    call behind it and can legitimately run for minutes; holding the POST
    open for that meant the button's request timed out (a 502 in the log,
    an unexplained "could not file it" on screen) while the pass it started
    carried on invisibly. The tab already knows how to render a pass in
    flight — ``memory_state.running`` is the lock itself — so the honest
    answer here is "it's going", and the result arrives the same way the
    daemon's own passes do.
    """
    if MEMORY_STATE.get("merging") or await asyncio.to_thread(_consolidation_running):
        return web.json_response({"started": False, "running": True,
                                  "inbox_pending": await asyncio.to_thread(_inbox_pending)})
    MEMORY_STATE.update(merging=True, error="", filed=0)
    task = asyncio.create_task(_consolidate_task())
    request.app.setdefault("consolidations", set()).add(task)
    task.add_done_callback(lambda t: request.app["consolidations"].discard(t))
    return web.json_response({
        "started": True, "running": True,
        "inbox_pending": await asyncio.to_thread(_inbox_pending),
    })


# Both answers come back with the whole Findings payload, like every button
# on that tab: the guesses live in the same list now, and a reply that only
# said "confirmed" would leave the list to be re-fetched to find out what it
# looks like afterwards.

async def h_hypothesis_confirm(request: web.Request) -> web.Response:
    """Yes. The claim is the durable part, so it is queued as a plain memory
    fact and the guess itself is settled — no Q/A pair is kept anywhere."""
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad hypothesis id")
    settled = await asyncio.to_thread(hypotheses.confirm, ts)
    if not settled:
        raise web.HTTPNotFound(text="no such open hypothesis")
    await _submit_memory(settled["text"], source="confirmed")
    payload = await asyncio.to_thread(_findings_payload)
    payload["undo"] = undo_store.record("hypothesis", ts=ts,
                                        fact=settled["text"],
                                        fact_source="confirmed")
    return web.json_response(payload)


async def h_hypothesis_reject(request: web.Request) -> web.Response:
    """No. Recorded as a dead end so the same line of inquiry is not
    revisited — that is the one part of the queue worth showing the model.

    The optional note is the same offer the Findings cards make, for the
    same reason: "no" retires one guess, and "no, that fridge is a beer
    fridge and it cycles all night" is a fact about the house that retires
    the next three. It goes to the consolidator as a correction, which is
    what decides whether there is anything durable in it.
    """
    try:
        ts = int(request.match_info["ts"])
    except ValueError:
        raise web.HTTPBadRequest(text="bad hypothesis id")
    body = await _json_body(request)
    note = str((body or {}).get("note") or "").strip()[:findings_store.MAX_NOTE]

    def settle() -> dict | None:
        done = hypotheses.reject(ts, note=note)
        if done:
            entry = knowledge_store.record_question(done["text"])
            if entry:
                knowledge_store.dismiss_question(entry["ts"])
        return done

    settled = await asyncio.to_thread(settle)
    if not settled:
        raise web.HTTPNotFound(text="no such open hypothesis")
    fact = ""
    if note:
        fact = (f'brAIn guessed: "{settled["text"]}". The homeowner says that '
                f"is wrong, because: {note}")
        await _submit_memory(fact, source="correction")
    payload = await asyncio.to_thread(_findings_payload)
    # `question` is the ledger entry reject() also wrote, so undo can retire
    # the dead-end record too rather than leaving the claim un-askable.
    payload["undo"] = undo_store.record("hypothesis", ts=ts, fact=fact,
                                        fact_source="correction",
                                        question=settled["text"])
    return web.json_response(payload)


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
        # An OSError's text carries the errno and the path it was writing,
        # which says where the add-on keeps its files and nothing the user
        # can act on. The log is the right place for both.
        log.warning("memory write failed: %s", exc)
        raise web.HTTPInternalServerError(text="could not write memory file")
    return web.json_response({"saved": True})


# What an export IS: the durable knowledge, portable. The memory document,
# the findings work list, the settled ledger and the facts ledger are the
# four things a rebuilt or second install cannot rediscover cheaply — the
# rest (inbox, hypotheses, questions) is in-flight dialogue state that will
# regenerate, and exporting state that import ignores just invites people
# to expect it back.
EXPORT_VERSION = 1


def _export_payload() -> dict:
    return {
        "brain_export": EXPORT_VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "memory_md": _read_shared_memory(),
        "findings": findings_store.list_all(),
        "settled": findings_store.settled_listing(),
        "knowledge_facts": knowledge_store.list_facts(),
    }


async def h_memory_export(request: web.Request) -> web.Response:
    """Everything brAIn has learned about this home, as one portable file."""
    payload = await asyncio.to_thread(_export_payload)
    stamp = time.strftime("%Y-%m-%d")
    return web.json_response(payload, headers={
        "Content-Disposition":
            f'attachment; filename="brain-export-{stamp}.json"',
    })


async def h_memory_import(request: web.Request) -> web.Response:
    """Fold an exported file back in — a migration, not a sync.

    The ledgers MERGE (existing entries always win, so an answer given on
    this install is never undone by an import), while the memory document
    REPLACES — there is no honest textual merge of two markdown documents,
    so it is written only when the local one is effectively empty or the
    caller explicitly said replace. Everything reported back by count, so
    the CLI can say what actually happened rather than "imported".
    """
    body = await request.json()
    if not isinstance(body, dict) or "brain_export" not in body:
        raise web.HTTPBadRequest(
            text="not a brAIn export (missing brain_export marker)")
    if int(body.get("brain_export") or 0) > EXPORT_VERSION:
        raise web.HTTPBadRequest(
            text="this export is from a newer brAIn — update the add-on first")
    memory_md = body.get("memory_md")
    if memory_md is not None and not isinstance(memory_md, str):
        raise web.HTTPBadRequest(text="memory_md must be a string")
    if memory_md and len(memory_md) > MAX_MEMORY_CHARS:
        raise web.HTTPBadRequest(
            text=f"memory too large (max {MAX_MEMORY_CHARS} chars)")
    replace = bool(body.get("replace_memory"))

    def fold() -> dict:
        result = {"memory": "kept"}
        if memory_md and memory_md.strip():
            # "Effectively empty" covers the fresh-install template case a
            # migration actually is; anything with content needs the flag.
            if replace or not _read_shared_memory().strip():
                _write_shared_memory(memory_md)
                result["memory"] = "replaced"
        rows = body.get("findings")
        settled = body.get("settled")
        facts = body.get("knowledge_facts")
        result["findings"] = findings_store.merge_rows(
            rows if isinstance(rows, list) else [])
        result["settled"] = findings_store.merge_settled(
            settled if isinstance(settled, list) else [])
        added = 0
        for fact in (facts if isinstance(facts, list) else []):
            if not isinstance(fact, dict):
                continue
            _, created = knowledge_store.add_fact(
                str(fact.get("text") or ""),
                source=str(fact.get("source") or "import"),
                category=str(fact.get("category") or ""))
            added += int(created)
        result["knowledge_facts"] = added
        return result

    result = await asyncio.to_thread(fold)
    log.info("import: memory %s, %d finding(s), %d settled, %d fact(s)",
             result["memory"], result["findings"], result["settled"],
             result["knowledge_facts"])
    return web.json_response(result)


async def h_inbox_delete(request: web.Request) -> web.Response:
    """Drop a fact from the filing queue before it reaches the document.

    Nothing is queued for removal afterwards, and that is the whole point of
    acting on the queue rather than on the ledger: a line still in the inbox
    has never been filed, so there is nothing in memory.md to forget. The
    old ✕ deleted a ledger entry and asked the consolidator to strike the
    text from a document that, more often than not, had never held it.
    """
    item_id = request.match_info["id"]

    def drop() -> tuple[bool, list[dict], int]:
        ok = _drop_from_inbox(item_id)
        return ok, _inbox_items(), _inbox_pending()

    ok, inbox, pending = await asyncio.to_thread(drop)
    if not ok:
        raise web.HTTPNotFound(text="nothing waiting under that")
    return web.json_response({"deleted": item_id, "inbox": inbox,
                              "inbox_pending": pending})


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
    """The ⚙ dialog's view: panel settings + the live effective options.

    ``model_label`` is here for the chat, not the dialog: ⚙ is reachable
    from the Terminal tab, and the model picker's Default row names the
    global model this saves. Without it that row kept whatever the stream's
    opening snapshot said — so the row that was highlighted as *current*
    named a model the server had already been told to stop using, which is
    indistinguishable from a setting that did not save.
    """
    options = effective_options()
    return {
        "settings": {**settings, **options},
        "model_label": chat_session.pretty_model(options["model"]),
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
    start_auth_check()
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
        start_auth_check()
    return web.json_response(status)


async def h_setup_cancel(request: web.Request) -> web.Response:
    engine.SETUP_FLOW.cancel()
    return web.json_response(engine.SETUP_FLOW.status())


# The background processes run.sh starts, by the substring that identifies
# each in /proc/*/cmdline. The panel is the foreground process and the
# watchdog target, so "the panel is up" is implied by any answer at all —
# these are the siblings whose death is otherwise invisible: the add-on
# still shows "started", every tab still renders, and the first symptom is
# a queue quietly not draining days later.
DAEMON_MARKS = {
    "ttyd": "ttyd",
    "usage_tracker": "usage-limits-tracker.py",
    "memory_consolidator": "brain-memory-consolidate.sh",
    "study_watcher": "brain-study-watcher.sh",
    "assist_worker_pool": "assist-worker-pool.py",
    "assist_listener": "assist-listener.sh",
    "automation_listener": "automation-listener.sh",
}


def _daemon_rollcall() -> dict:
    """Which background processes are actually alive right now.

    A /proc scan rather than pidfiles: run.sh restarts pieces, shells wrap
    scripts, and a pidfile is one more thing to go stale — where the
    process table is simply true. Descriptive, not judgemental: several of
    these are optional (a disabled terminal has no ttyd, classic assist
    mode has no pool), so "running: false" is a fact for `brain doctor` to
    interpret against the config, not an alarm by itself.
    """
    found: set[str] = set()
    try:
        for entry in os.scandir("/proc"):
            if not entry.name.isdigit():
                continue
            try:
                with open(f"/proc/{entry.name}/cmdline", "rb") as fh:
                    cmdline = fh.read().replace(b"\0", b" ").decode(
                        "utf-8", errors="replace")
            except OSError:
                continue
            for name, mark in DAEMON_MARKS.items():
                if mark in cmdline:
                    found.add(name)
    except OSError:
        return {}
    out: dict = {name: {"running": name in found} for name in DAEMON_MARKS}
    # The consolidator's heartbeat: when a pass last landed. A running
    # process that never lands a pass is the failure the stale-queue check
    # exists for, and this is the same number, readable from one place.
    try:
        age_h = (time.time()
                 - (MEMORY_DIR / ".last_consolidated").stat().st_mtime) / 3600
        out["memory_consolidator"]["last_pass_hours_ago"] = round(age_h, 1)
    except OSError:
        # No marker file means no pass has ever landed — a real state on a
        # fresh install, reported by the field's absence rather than a fake
        # number.
        pass
    return out


async def h_health(request: web.Request) -> web.Response:
    """Liveness for the watchdog, readiness for whoever asks nicely.

    `ok` is the panel answering and NOTHING else — the Supervisor restarts
    the add-on when this endpoint fails, so folding a dead sibling into it
    would turn "the study watcher crashed" into a restart loop. The
    roll-call rides along for `brain doctor` and anyone curious.
    """
    payload: dict = {"ok": True}
    try:
        payload["daemons"] = await asyncio.to_thread(_daemon_rollcall)
    except Exception as exc:  # noqa: BLE001 — liveness must never depend on it
        log.debug("daemon roll-call failed: %s", exc)
    return web.json_response(payload)


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
    # ⚙ Settings, from the Configuration tab and from the chat's own model
    # picker, and a chat session started before an edit should not keep the
    # old one for as long as it lives.
    session.model = eff_chat_model()
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
            if event.get("event") == "__overflow__":
                # This stream fell behind and the session dropped it. End
                # the response so the EventSource reconnects to a fresh
                # snapshot, rather than idling on a queue nothing feeds.
                break
            await send(event)
    except (ConnectionResetError, asyncio.CancelledError):
        # The viewer closed the tab, or the task was cancelled. Either way
        # there is no longer anyone to send to.
        pass
    finally:
        session.unsubscribe(queue)
    return resp


def _refusal(exc: Exception) -> str:
    """An exception message fit for an HTTP reason line.

    A session error can carry a stderr tail, and a reason is a status-line
    fragment: aiohttp (rightly) refuses newlines in one, so passing the
    message through unwhitened turned "the session died" into a 500 about
    carriage returns. One line, bounded, or the refusal cannot be sent.
    """
    return " ".join(str(exc).split())[:300] or "refused"


async def h_chat_send(request: web.Request) -> web.Response:
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    try:
        return web.json_response(await _chat().send(body.get("text") or ""))
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=_refusal(exc))
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=_refusal(exc))


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

    "Whichever face" turned out to include faces that are not a person.
    Voice, the automation listener and the memory consolidator all drive
    the same CLI from /config, so on a house that uses them the rail filled
    with machine prompts — forty copies of the consolidator's opening line
    with your own chats somewhere underneath. Each row now says whose it
    is, and ``?source=`` picks which to show; the default is yours, because
    the rail is a list of your conversations.
    """
    session = _chat()
    wanted = request.query.get("source", "you")
    if wanted in ("", "all"):
        config_sources: tuple | None = None
        engine_sources: tuple = tuple(sorted(run_sources.ENGINE_SOURCES))
    else:
        picked = [s for s in wanted.split(",")
                  if s == "you" or run_sources.known(s)] or ["you"]
        config_sources = tuple(
            s for s in picked if s not in run_sources.ENGINE_SOURCES)
        engine_sources = tuple(
            s for s in picked if s in run_sources.ENGINE_SOURCES)
    # The open conversation is listed too — the panel marks it as "where
    # you are" rather than offering it. Hiding it made the row you had just
    # opened vanish from the rail, which read as the conversation being
    # lost; a list that silently omits the current item makes you wonder
    # where it went.
    rows: list[dict] = []
    if config_sources is None or config_sources:
        rows += await asyncio.to_thread(
            conversations.listing, chat_session.WORK_DIR, 30, config_sources)
    if engine_sources:
        # Card and fix runs live in the engine's own project directory (it
        # runs from CLAUDE_HOME), and they are records, not places to go:
        # `view_only` is what tells the panel to open a reader instead of
        # resuming. Unclaimed ids there belong to nobody — see listing().
        rows += [
            {**row, "view_only": True}
            for row in await asyncio.to_thread(
                conversations.listing, engine.CLAUDE_HOME, 30,
                engine_sources, "")
        ]
        rows.sort(key=lambda r: r["modified"], reverse=True)
    return web.json_response({
        "conversations": rows[:30],
        "current": session.session_id,
        "sources": await asyncio.to_thread(_conversation_source_counts),
    })


def _conversation_source_counts() -> list[dict]:
    """What the filter offers, and how much is behind each choice.

    Only faces that have actually run here are offered: a house with no
    voice assistant should not be given a Voice filter that is empty
    forever, and one that has never had a fix run should not be told the
    concept exists.
    """
    counts = conversations.source_counts(chat_session.WORK_DIR)
    # The engine's directory holds the card and fix runs; its unclaimed
    # rows count toward nobody (the "" default), so an auth self-check
    # never inflates a chip.
    for key, n in conversations.source_counts(
            engine.CLAUDE_HOME, default_source="").items():
        counts[key] = counts.get(key, 0) + n
    # "Chats" leads because it is the default and the odd one out — it is
    # the absence of a claim, not a source. Just "Chats", not "Your chats":
    # under a rail already headed CHATS the possessive answered a question
    # nobody asked, and the blurb carries whose they are. The machine faces
    # follow in alphabetical order, so the row of chips reads as a list
    # rather than as an order somebody would have to already understand.
    out = [{"id": "you", "label": "Chats",
            "blurb": "conversations you started — in this chat "
                     "or the classic terminal",
            "count": counts.get("you", 0)}]
    for key, meta in sorted(run_sources.SOURCES.items(),
                            key=lambda kv: kv[1]["label"].lower()):
        if counts.get(key):
            out.append({"id": key, "label": meta["label"],
                        "blurb": meta["blurb"], "count": counts[key]})
    return out


async def h_chat_adopt(request: web.Request) -> web.Response:
    """Take up whatever the classic terminal was last doing.

    The other half of the handoff, and the reason the switch is a switch
    rather than two separate rooms. Going the other way is easy — we own the
    chat's process, so we can stop it and tell the terminal which id to
    resume. Coming back, there is nothing to ask: the tmux Claude is not
    ours, it has no API, and it will not tell us what it is in the middle of.

    What it does leave behind is its transcript, which Claude Code writes as
    it goes. The most recently written conversation in this project
    directory IS what the terminal was last doing, so that is what we pick
    up — by resuming it, which starts our own process from that history.
    The terminal's Claude is left completely alone: it is somebody's shell
    and killing it is not ours to do.

    Refused mid-turn, because adopting stops the chat's process and losing
    an answer being written is worse than making you wait for it.

    "Most recently written" has to mean most recent conversation *of
    yours*. The consolidator, voice and the automation listener all write
    transcripts into this same directory on their own schedule, so on a
    busy house the newest file was routinely a machine's — and switching
    back from the terminal adopted the memory consolidator's prompt instead
    of what you had been doing.
    """
    session = _chat()
    if session.state == "busy":
        raise web.HTTPConflict(reason="finish or stop the current answer first")
    recent = await asyncio.to_thread(
        conversations.listing, chat_session.WORK_DIR, 1, ("you",))
    newest = recent[0] if recent else None
    if newest is None or newest["id"] == session.session_id:
        # Already the same conversation (or there is nothing to take up):
        # switching is then just a change of renderer, which is the point.
        return web.json_response({"ok": True, "adopted": False,
                                  "session_id": session.session_id})
    replay = await asyncio.to_thread(
        conversations.transcript, chat_session.WORK_DIR, newest["id"])
    try:
        await session.resume(newest["id"], replay)
    except RuntimeError:
        # A turn started between the busy check above and here — the same
        # refusal, in the same words.
        raise web.HTTPConflict(reason="finish or stop the current answer first")
    return web.json_response({"ok": True, "adopted": True,
                              "session_id": newest["id"],
                              "title": newest["title"]})


async def h_chat_model(request: web.Request) -> web.Response:
    """Pick the chat's model, from the chat.

    Stores the choice as the panel's ``chat_model`` (empty = follow the
    global model option) and applies it to the live session, which means a
    restart — the model is an argv flag — with ``--resume`` carrying the
    conversation across, the same way stopping an old CLI already does.
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    session = chat_session.session()
    if session.state == "busy":
        # Refused before anything is saved: a choice that half-applies —
        # stored but not running — reads as a picker that lies.
        raise web.HTTPConflict(reason="finish or stop the current answer first")
    try:
        settings = settings_store.save({"chat_model": body.get("model")})
    except ValueError:
        # The one thing save() can reject here, said in fixed words rather
        # than echoing exception text into a response (CodeQL reads that as
        # information exposure, and the message is knowable anyway).
        raise web.HTTPBadRequest(text="chat_model must be a string or null")
    try:
        out = await session.set_model(eff_chat_model())
    except RuntimeError:
        # Only raised when a turn started between the busy check above and
        # here — the same refusal, in the same words.
        raise web.HTTPConflict(reason="finish or stop the current answer first")
    out["chat_model"] = settings.get("chat_model") or ""
    return web.json_response(out)


async def h_chat_permission(request: web.Request) -> web.Response:
    """Answer the approval the turn is waiting on.

    The chat's version of the TUI's permission prompt: the CLI asked over
    its control channel, the panel drew a card, and this is the card's
    button. The id must match the pending request — an answer to a question
    that has been withdrawn, timed out or already answered is refused
    rather than guessed about.
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    # A question card's answers ride along: question text → answer string,
    # exactly what respond_permission folds into updatedInput. Anything
    # that is not a flat object of strings is refused here, before it can
    # become a schema failure inside the CLI.
    answers = body.get("answers")
    if answers is not None:
        if not isinstance(answers, dict) or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in answers.items()):
            raise web.HTTPBadRequest(
                text="answers must map question text to an answer string")
    session = _chat()
    try:
        return web.json_response(await session.respond_permission(
            str(body.get("id") or ""), bool(body.get("allow")),
            answers=answers))
    except ValueError as exc:
        # Fixed words, not the exception's text — CodeQL reads echoed
        # exception text as information exposure, and both messages are
        # knowable anyway.
        if "answer the questions" in str(exc):
            raise web.HTTPBadRequest(text="answer the questions first")
        raise web.HTTPNotFound(text="that request is no longer waiting")
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=_refusal(exc))


async def h_chat_conversation_delete(request: web.Request) -> web.Response:
    """Delete one conversation from the list — with an Undo, not a shrug.

    The file is moved into a trash directory rather than unlinked, so the
    toast's Undo can put back exactly what was taken. The conversation that
    is currently open is refused: deleting the ground the live session is
    standing on either kills it or quietly forks it, and "start a new chat
    first" is a better answer than either.
    """
    session = _chat()
    session_id = request.match_info["id"]
    if session.session_id == session_id:
        raise web.HTTPConflict(
            reason="that's the conversation that's open — start a new chat first")
    entry = await asyncio.to_thread(
        conversations.delete, chat_session.WORK_DIR, session_id)
    if entry is None:
        raise web.HTTPNotFound(text="no such conversation")
    return web.json_response({
        "deleted": session_id,
        "undo": undo_store.record("conversation", **entry),
    })


async def h_chat_conversations_delete(request: web.Request) -> web.Response:
    """Delete several conversations in one press — one Undo for the lot.

    The single-delete's rules apply per row: each file moves to the trash,
    and the conversation that is currently open is skipped rather than
    failing the batch — a select-all that refuses outright because the open
    chat was in it teaches people to deselect one row by trial and error.
    What was skipped is reported, so the toast can say it.
    """
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get("ids"), list):
        raise web.HTTPBadRequest(text="expected {ids: [...]}")
    ids = [str(i) for i in body["ids"] if isinstance(i, str) and i]
    if not ids:
        raise web.HTTPBadRequest(text="nothing selected")
    if len(ids) > conversations.TRASH_MAX:
        # The trash is the undo, and it caps at TRASH_MAX: accepting more
        # than fits would silently make the oldest of THIS batch
        # unrestorable while the toast still offers to restore it.
        raise web.HTTPBadRequest(
            text=f"at most {conversations.TRASH_MAX} at a time")
    session = _chat()
    deleted, entries, skipped = [], [], []
    for session_id in dict.fromkeys(ids):     # de-duped, order kept
        if session.session_id == session_id:
            skipped.append(session_id)
            continue
        entry = await asyncio.to_thread(
            conversations.delete, chat_session.WORK_DIR, session_id)
        if entry is None:
            skipped.append(session_id)
            continue
        deleted.append(session_id)
        entries.append(entry)
    payload: dict = {"deleted": deleted, "skipped": skipped}
    if entries:
        payload["undo"] = undo_store.record("conversations", entries=entries)
    return web.json_response(payload)


async def h_chat_conversation_view(request: web.Request) -> web.Response:
    """One card or fix run, replayed to be read — never resumed.

    These transcripts live in the engine's project directory (insight and
    fix runs execute from CLAUDE_HOME), and they are records: their turns
    ran under the analyst's read-only scoping or the fixer's, with the card
    contract as their brief, and continuing that under the chat's
    permissions would change the conversation's rules mid-thread. So the
    panel opens a reader instead — the same replay pipeline the resume path
    uses, minus the process.
    """
    session_id = request.match_info["id"]
    events = await asyncio.to_thread(
        conversations.transcript, engine.CLAUDE_HOME, session_id)
    if not events:
        raise web.HTTPNotFound(text="no such run")
    return web.json_response({"id": session_id, "events": events})


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
    except RuntimeError as exc:
        # Mid-answer: switching would kill the answer being written, the
        # same refusal adopt and the model picker already make.
        raise web.HTTPConflict(reason=_refusal(exc))


def _chat_snapshot(session: "chat_session.ChatSession") -> dict:
    """The session's own snapshot, plus what the composer needs to offer.

    The `brain`/`ha` command list rides along here rather than on its own
    endpoint because it is wanted at exactly the moment the snapshot is —
    when the chat opens — and it is cached, so it costs nothing to include.
    So does what the model picker needs: the same static choices ⚙ offers,
    the stored chat override, and the global model it defers to — asking
    /api/settings for those would drag a Supervisor round-trip into opening
    a popover. The global model rides down named as well as identified,
    because the picker's Default row prints the name and the parser that
    produces one lives here.
    """
    settings = settings_store.load()
    default = eff_model()
    return {**session.snapshot(), "cli": cli_commands.listing(),
            "models": engine.MODEL_CHOICES,
            "chat_model": settings.get("chat_model") or "",
            "default_model": default,
            "default_model_label": chat_session.pretty_model(default)}


async def h_chat_state(request: web.Request) -> web.Response:
    """The snapshot on its own, for a client whose stream is not up yet."""
    return web.json_response(_chat_snapshot(_chat()))


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

def make_app() -> web.Application:
    # 1 MiB: leaves room for a full memory-file edit (MAX_MEMORY_CHARS plus
    # JSON escaping) and for /api/memory/import, whose payload is a whole
    # export — the document plus every ledger. Everything else is far
    # smaller.
    app = web.Application(client_max_size=1024 * 1024)
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
    app.router.add_get("/api/checks", h_checks)
    app.router.add_post("/api/checks/run", h_checks_run)
    app.router.add_get("/api/diagnostics", h_diagnostics)
    app.router.add_get("/api/baselines", h_baselines)
    app.router.add_post("/api/baselines/run", h_baselines_run)
    app.router.add_get("/api/activity", h_activity)
    app.router.add_get("/api/activity/entity/{entity_id}", h_activity_entity)
    app.router.add_post("/api/finding/{ts}/fix", h_finding_fix)
    app.router.add_post("/api/finding/{ts}/snooze", h_finding_snooze)
    app.router.add_post("/api/finding/{ts}/discuss", h_finding_discuss)
    # Before the {ts} pattern, which would otherwise swallow it.
    app.router.add_post("/api/findings/unsettle", h_finding_unsettle)
    app.router.add_post("/api/undo/{token}", h_undo)
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
    app.router.add_get("/api/memory/state", h_memory_state)
    app.router.add_get("/api/memory/export", h_memory_export)
    app.router.add_post("/api/memory/import", h_memory_import)
    app.router.add_post("/api/knowledge/fact", h_knowledge_fact_add)
    app.router.add_delete("/api/memory/inbox/{id}", h_inbox_delete)
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
    app.router.add_post("/api/chat/adopt", h_chat_adopt)
    app.router.add_post("/api/chat/resume", h_chat_resume)
    app.router.add_post("/api/chat/model", h_chat_model)
    app.router.add_post("/api/chat/permission", h_chat_permission)
    app.router.add_post("/api/chat/conversations/delete",
                        h_chat_conversations_delete)
    app.router.add_post("/api/chat/conversation/{id}/delete",
                        h_chat_conversation_delete)
    app.router.add_get("/api/chat/conversation/{id}/view",
                       h_chat_conversation_view)

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
        # Dismissals made before the settled ledger existed live as rows in
        # a status the tab no longer shows; move them somewhere visible.
        migrated = await asyncio.to_thread(findings_store.migrate_settled)
        if migrated:
            log.info("moved %d dismissed finding(s) into the settled ledger",
                     migrated)
        # Republish the shared-volume mirror so the integration's findings
        # sensor reads the current list, not the one from the last change.
        await asyncio.to_thread(findings_store.publish_state)
        # Transcripts from before the pool's reflection pass and one-shot
        # voice fallback claimed their ids sat in the person's own Chats
        # list. Label the backlog once, by our own shipped prompt openers
        # (marker-guarded).
        relabelled = await asyncio.to_thread(
            conversations.backfill_sources, chat_session.WORK_DIR)
        if relabelled:
            log.info("labelled %d machine conversation(s) from before their "
                     "callers claimed session ids", relabelled)
        await _options_sync()
        app["worker"] = asyncio.create_task(_worker())
        app["scheduler"] = asyncio.create_task(_scheduler())
        app["checks"] = asyncio.create_task(_checks_loop())
        app["baselines"] = asyncio.create_task(_baseline_loop())
        app["notify_flush"] = asyncio.create_task(_notify_flush_loop())
        app["brief"] = asyncio.create_task(_brief_loop())
        if addon_options.available():
            app["options"] = asyncio.create_task(_options_poller())
        if engine.get_auth():
            start_auth_check()

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
    web.run_app(make_app(), host=BIND_HOST, port=BIND_PORT, print=None,
                access_log_class=QuietAccessLogger)
