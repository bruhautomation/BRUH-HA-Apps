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
GET  /api/auth               — every credential store, which one is in use,
                               and the last verdict (the ⚙ Claude account
                               section; not polled — read when it opens)
POST /api/auth/token         — save a pasted token / API key
POST /api/auth/logout        — forget the stored credential {shared: bool}
POST /api/auth/share         — publish it to /config for the other add-ons
POST /api/auth/unshare       — withdraw that copy
POST /api/auth/recheck       — verify the credential now, not at the next ageing
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
import appliances
import atomic_write
import automation_writer
import baselines
import brief
import card_tags
import chat_session
import closures
import checks
import cli_commands
import conditions
import conversations
import energy
import engine
import feedback_store
import finding_requests
import findings_store
import fixer
import healing
import health
import hypotheses
import intents
import journal
import knowledge_store
import notify_router
import override_ledger
import onboarding
import playbooks
import prompt_store
import proposals
import rhythm
import routines
import run_sources
import scenes
import schedule_store
import settings_store
import shadow
import terminal_proxy
import thermal
import trials
import undo_store
import usage_store
import user_categories
import weekly
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


def log_safe(text) -> str:
    """A string off the wire, safe to put in a log line.

    A sentence somebody typed reaches the log in three places now — the
    room a scene set is for, the one-off's own title — and a log line is
    read by a person scanning for what went wrong. A newline in it writes
    a second line that looks like brAIn's own, which is how a log stops
    being evidence; the two `replace` calls are literal because that is
    the barrier a scanner can follow, and the printable filter takes the
    control characters a terminal would act on. Capped, because a log
    line is a sentence rather than a payload.
    """
    flat = str(text or "").replace("\r", " ").replace("\n", " ")
    return "".join(ch for ch in flat if ch.isprintable())[:60]


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
# How far back a replay reaches by default. A month is what the recorder
# keeps on a default install, so asking for more usually answers with a
# shorter window and no way to tell; `shadow.MAX_WINDOW_DAYS` is the
# ceiling somebody may ask for by hand.
REPLAY_DAYS = 30
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
    # Buttons, but only where they can be answered and only when the
    # message is about one finding — see `notify_router.actions_for`.
    buttons = notify_router.actions_for(rows, service)
    import ha_data
    try:
        await ha_data.send_notification(
            service, title, body,
            data={"actions": buttons} if buttons else None)
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
# `last_sent` is read back from disk at import: it lived in memory only,
# so a restart set it to zero and the next window sent a second brief on
# the same morning — and restarting is the first thing anybody does after
# changing an option. Same for the weekly, where the duplicate is a whole
# week's material reported twice.
BRIEF_SENT_KEY = "brief_last_sent"
BRIEF_STATE: dict = {"last_sent": schedule_store.get(BRIEF_SENT_KEY),
                     "last_reasons": [], "last_error": ""}
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
        payload = await asyncio.to_thread(_diagnostics_payload)
        verdict = payload.get("health") or {}
    except Exception as exc:  # noqa: BLE001 — the verdict is one reason of
        # several, and not having it is not a reason to skip the morning.
        log.info("brief could not read the health verdict: %s", exc)

    night = await _brief_overnight(now)
    state = brief.state_from(
        await asyncio.to_thread(findings_store.list_all),
        verdict, night, BRIEF_STATE["last_sent"] or (now - 86400),
        await asyncio.to_thread(_healing_brief_lines))

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
                    schedule_store.set(BRIEF_SENT_KEY, now)
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


def _routines_diagnostics() -> dict:
    """What the habit miner has to work with, and what it makes of it.

    A tab with nothing on it looks the same whether the miner found no
    habit or the ledger has been empty since March because the listener
    that fills it stopped — and "I could not look" versus "there was
    nothing" is the distinction every check in this add-on carries.
    """
    try:
        payload = routines.load()
    except Exception as exc:  # noqa: BLE001 — a dev checkout has no store
        return {"error": str(exc)[:120]}
    rows = payload.get("rows") or []
    try:
        tz, _name = baselines.house_timezone()
        found = len(routines.mine(payload, tz))
    except Exception as exc:  # noqa: BLE001
        return {"presses": len(rows), "error": str(exc)[:120]}
    return {
        "presses": len(rows),
        "entities": len({r.get("entity_id") for r in rows if r.get("entity_id")}),
        "automated_keys": len(payload.get("automated") or {}),
        "oldest": min((r.get("ts") or 0) for r in rows) if rows else 0,
        "newest": max((r.get("ts") or 0) for r in rows) if rows else 0,
        "would_propose": found,
        "min_days": routines.MIN_DAYS,
        "min_share": routines.MIN_SHARE,
    }


def _proposals_diagnostics() -> dict:
    try:
        rows = proposals.listing()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    return {**proposals.counts(rows),
            "settled": len(proposals.settled_keys()),
            # A trial with no report behind it is what 1.42.0 shipped, so
            # the two numbers are reported apart: "3 trialling, 0 with a
            # result" is the shape of that failure and is unreadable from
            # a single count.
            "trial_results": sum(1 for r in rows if r.get("trial_result")),
            "trials_due": sum(1 for r in rows if proposals.trial_due(r)),
            # See CONDITIONS_STATE: a pattern brAIn will not act on is
            # reported here rather than as a card nobody can answer.
            "conditions": dict(CONDITIONS_STATE),
            # The one-offs are not proposals and are counted apart: an
            # armed one is waiting on the house rather than on anybody.
            "intents": _intents_diagnostics(),
            # An empty Proposals tab reads the same whether nobody has
            # asked for scenes or every ask was refused.
            "scenes": dict(SCENES_STATE)}


def _intents_diagnostics() -> dict:
    try:
        rows = intents.listing()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    now = time.time()
    return {
        "armed": sum(1 for r in rows if r.get("status") == "armed"),
        "fired": sum(1 for r in rows if r.get("status") == "fired"),
        "refused": sum(1 for r in rows if r.get("status") == "refused"),
        # An armed one-off past its fortnight is the shape of a sentence
        # about something that already happened, and it is a label rather
        # than a deletion — see `intents.expired`.
        "overdue": sum(1 for r in rows if intents.expired(r, now)),
        "queued": intents.pending(),
        "max_armed": intents.MAX_ARMED,
        "ttl_days": intents.INTENT_TTL_DAYS,
    }


# The weekly report. The same poll as the brief's and a different gate:
# the day decides whether it goes at all, and the hour only ever opens
# the window — see `weekly.due`.
WEEKLY_POLL_S = 15 * 60
WEEKLY_FIRST_DELAY_S = 600
WEEKLY_SENT_KEY = "weekly_last_sent"
WEEKLY_STATE: dict = {"last_sent": schedule_store.get(WEEKLY_SENT_KEY),
                      "last_text": "", "last_error": "", "last_state": {}}


def _weekly_enabled() -> tuple[bool, int]:
    """`(on, day index)`. The hour is the brief's, deliberately.

    A third time-of-day option would be a third box saying the same
    thing: `morning_brief_hour` is when brAIn speaks in the morning, and
    the weekly is a morning message. What is genuinely per-report is
    which day.
    """
    opts = addon_options.snapshot() or {}
    on = opts.get("weekly_report")
    if on is None:
        on = os.environ.get("BRAIN_WEEKLY_REPORT", "").lower() in (
            "true", "1", "yes")
    day = opts.get("weekly_report_day")
    if day is None:
        day = os.environ.get("BRAIN_WEEKLY_REPORT_DAY", "")
    return bool(on), weekly.day_index(day or weekly.DEFAULT_DAY)


async def _weekly_energy(now: float) -> dict:
    """The week's meters, or the sentence saying why there are none."""
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            return await energy.week(session, now)
    except Exception as exc:  # noqa: BLE001 — a report without the meters
        # is still a report; one that failed because of them is not.
        log.info("weekly report could not read the meters: %s", exc)
        return {"available": False, "reason": "the meters could not be read"}


async def _weekly_state(now: float) -> dict:
    """Everything the decision and the prompt read. No model."""
    # A week, never longer: an add-on that was off for a fortnight must
    # not send a report headed "this week" about three of them, and a
    # finding still open from before it is already in `open_now` and in
    # the one thing to do.
    since = max(WEEKLY_STATE["last_sent"], now - weekly.WEEK_S)
    power = await _weekly_energy(now)
    rows = await asyncio.to_thread(findings_store.list_all)
    settled = await asyncio.to_thread(findings_store.settled_listing)
    return weekly.gather(rows, settled, power, since, now=now)


async def _send_weekly(now: float) -> str:
    """Gather, decide, and only then ask. Returns what was sent, or ''."""
    state = await _weekly_state(now)
    # Numbers, not the content: `last_state` rides into /api/diagnostics
    # and so into the bundle `brain report` attaches to an issue, and a
    # memory line is a fact about somebody's home rather than a
    # diagnostic. Same rule the closures summary carries.
    lore = dict(state.get("learned") or {})
    lore.pop("added", None)
    WEEKLY_STATE["last_state"] = {
        "energy": state.get("energy") or {},
        "findings": state.get("findings") or {},
        "learned": lore,
        "since": state.get("since"),
    }
    if not weekly.worth_reporting(state):
        # Not an error: a quiet week is the design. Clearing it matters
        # because a stale `last_error` beside a report that never went is
        # read as the reason it never went.
        WEEKLY_STATE["last_error"] = ""
        log.info("weekly report: nothing to report, not sent")
        return ""

    result = await asyncio.to_thread(
        engine.run_analyst, weekly.frame(state), weekly.SYSTEM,
        eff_model(), weekly.TIMEOUT_S, weekly.MAX_TURNS, "weekly")
    if not result.get("ok"):
        WEEKLY_STATE["last_error"] = str(result.get("error") or "no reply")
        log.warning("weekly report failed: %s", WEEKLY_STATE["last_error"])
        return ""

    body = weekly.tidy(result.get("text") or result.get("raw") or "")
    if not body:
        WEEKLY_STATE["last_error"] = "the reply was too short to send"
        log.warning("weekly report: %s", WEEKLY_STATE["last_error"])
        return ""

    WEEKLY_STATE["last_error"] = ""
    WEEKLY_STATE["last_text"] = body
    await _send_notification([{"text": body, "severity": "info"}])
    return body


async def _weekly_loop():
    """Once a week, on the day, at or after the hour this house is up."""
    await asyncio.sleep(WEEKLY_FIRST_DELAY_S)
    while True:
        try:
            on, want_day = _weekly_enabled()
            service, _sev = _findings_notify_target()
            if on and service:
                now = time.time()
                local = _local_now(now)
                _brief_on, fallback = _brief_enabled()
                if weekly.due(now, local.weekday(),
                              local.hour * 60 + local.minute,
                              rhythm.wake_minute(rhythm.profile(), local),
                              fallback, WEEKLY_STATE["last_sent"], want_day):
                    # Stamped before the run, for the brief's reason: a
                    # pass that takes minutes must not let the next tick
                    # start a second one, and a failed report is still
                    # this week's.
                    WEEKLY_STATE["last_sent"] = now
                    schedule_store.set(WEEKLY_SENT_KEY, now)
                    sent = await _send_weekly(now)
                    log.info("weekly report %s", "sent" if sent else "skipped")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a pass
            log.warning("weekly report pass failed: %s", exc)
        await asyncio.sleep(WEEKLY_POLL_S)


def _weekly_diagnostics() -> dict:
    """Whether the report is on, when it last went, and what it last held."""
    on, want_day = _weekly_enabled()
    return {
        "enabled": on,
        "day": weekly.DAYS[want_day],
        "last_sent": int(WEEKLY_STATE["last_sent"]),
        "last_error": WEEKLY_STATE["last_error"],
        "last_chars": len(WEEKLY_STATE["last_text"]),
        "last_state": WEEKLY_STATE["last_state"],
    }


# Answers given somewhere else. A glob of a directory that is nearly
# always empty, often enough that ticking an item off in the To-do app
# makes it disappear from the Findings tab while you are still looking at
# your phone — a list that takes half a minute to notice is a list people
# tick twice.
REQUESTS_POLL_S = 15
REQUESTS_FIRST_DELAY_S = 20
REQUESTS_STATE: dict = {"applied": 0, "missed": 0, "last": 0.0}


async def _apply_finding_requests() -> list[dict]:
    """Drain the request drop, through the tab's own endings.

    Returns one result per request, for the log and for the tests: a
    request naming a finding that is gone is `ok: False`, which is an
    ordinary race — somebody's phone was a few seconds out of date — and
    never a reason to retry or to put the row back.
    """
    requests = await asyncio.to_thread(finding_requests.collect)
    out: list[dict] = []
    for req in requests:
        ts, action = req["ts"], req["action"]
        result = {"ts": ts, "action": action, "via": req.get("via", ""),
                  "ok": False, "why": "no such finding"}
        if action == "snooze":
            until = int(time.time() + req["hours"] * 3600)
            row = await asyncio.to_thread(findings_store.snooze, ts, until)
            result["ok"] = bool(row)
        else:
            finding = await asyncio.to_thread(findings_store.get, ts)
            spec = FINDING_VERBS.get(finding_requests.verb_for(action))
            if finding and spec:
                # No undo token: `undo_store` is the toast's, and there is
                # no toast on a lock screen. By the time somebody un-ticks
                # an item the row it stood for is already gone, so an
                # offer nothing can accept would be worse than none.
                await _end_finding(finding, spec, req.get("note", ""))
                result["ok"] = True
        if result["ok"]:
            result["why"] = ""
            REQUESTS_STATE["applied"] += 1
        else:
            REQUESTS_STATE["missed"] += 1
        REQUESTS_STATE["last"] = time.time()
        log.info("finding %s: %s from %s%s", ts, action,
                 result["via"] or "elsewhere",
                 "" if result["ok"] else f" — {result['why']}")
        out.append(result)
    return out


async def _one_intent(req: dict, now: float) -> dict | None:
    """One sentence into one card. Returns the row it produced, or None.

    Claude writes the config once, with **reading tools only**
    (`run_analyst`, the middle of the three paths): it can search the
    house for the thing the sentence names and it cannot act on it. What
    comes back is checked by `intents.build` before it becomes anything,
    and a refusal is a row on the tab rather than a log line — somebody
    typed a sentence and is waiting for an answer, and *"brAIn will not
    do this, and here is why"* is one.
    """
    sentence = req["sentence"]
    if await asyncio.to_thread(intents.armed_count) >= intents.MAX_ARMED:
        return await asyncio.to_thread(intents.note, {
            "sentence": sentence,
            "refused": (f"you already have {intents.MAX_ARMED} one-offs "
                        "waiting to happen. Remove one and ask again — a "
                        "list of things about to happen is only useful "
                        "while it is short.")}, now)
    try:
        import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

        orientation = await ha_data.collect_orientation(sentence)
    except Exception as exc:  # noqa: BLE001 — a map brAIn could not read
        # is a smaller prompt, never a refused sentence.
        log.info("could not orient the intent run: %s", exc)
        orientation = {}
    started = time.time()
    try:
        result = await asyncio.to_thread(
            engine.run_analyst, intents.prompt(sentence, orientation),
            intents.SYSTEM, eff_model(), intents.TIMEOUT_S,
            intents.MAX_TURNS, "intent")
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc)}
    journal.record("intent", "ok" if result.get("ok") else "error",
                   ok=bool(result.get("ok")),
                   error="" if result.get("ok") else str(result.get("error")),
                   duration_s=time.time() - started)
    answer = intents.parse_answer(result.get("text") or result.get("raw") or "")
    if not result.get("ok") or answer is None:
        return await asyncio.to_thread(intents.note, {
            "sentence": sentence,
            "refused": ("brAIn could not work out an automation from that "
                        "sentence: "
                        + str(result.get("error")
                              or "it did not answer with a config")[:200])},
            now)

    protected = automation_writer.protected_patterns()
    obj = await asyncio.to_thread(
        intents.build, sentence, answer, int(now * 1000), protected)
    if obj.get("refused"):
        return await asyncio.to_thread(intents.note, obj, now)

    import aiohttp  # noqa: PLC0415 — as `_offer_routines` does

    tz, _name = await asyncio.to_thread(baselines.house_timezone)
    try:
        async with aiohttp.ClientSession() as session:
            obj["replay"] = await _replay_config(
                session, obj["config"], now - REPLAY_DAYS * 86400, now, tz)
    except Exception as exc:  # noqa: BLE001 — the replay is the card's
        # sanity check on a trigger that has never fired, not a gate: a
        # recorder that will not answer costs the number, never the
        # sentence somebody typed.
        obj["replay"] = {"refused": True,
                         "error": f"brAIn could not replay it: {exc}"}
    row = await asyncio.to_thread(proposals.add, obj)
    if row is None:
        return await asyncio.to_thread(intents.note, {
            **obj, "refused": ("the Proposals tab is full, or brAIn has "
                               "already offered this exact automation. "
                               "Answer what is on it and ask again.")}, now)
    log.info("one-off intent proposed from %s: %s",
             log_safe(req.get("via") or "the panel"), log_safe(obj["title"]))
    return row


async def _apply_intent_requests() -> int:
    """Drain the intent drop. Returns how many sentences were answered."""
    queued = await asyncio.to_thread(intents.collect)
    now = time.time()
    answered = 0
    for req in queued:
        try:
            if await _one_intent(req, now):
                answered += 1
        except Exception as exc:  # noqa: BLE001 — one bad sentence must
            # not stop the loop that answers the next one.
            log.warning("could not answer an intent: %s", exc)
        now += 0.001                 # so two in one pass get two ids
    return answered


async def _requests_loop():
    """Watch the drop directories. Cheap, and empty nearly every pass."""
    await asyncio.sleep(REQUESTS_FIRST_DELAY_S)
    while True:
        try:
            await _apply_finding_requests()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a pass
            log.warning("finding request pass failed: %s", exc)
        try:
            await _apply_intent_requests()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("intent request pass failed: %s", exc)
        await asyncio.sleep(REQUESTS_POLL_S)


def _appliance_summary() -> dict:
    """How many machines have a measured shape, and how many are chores."""
    try:
        store = appliances.load()
    except Exception as exc:  # noqa: BLE001 — a dev checkout has no store
        return {"error": str(exc)[:120]}
    entities = store.get("entities") or {}
    named = sum(1 for shape in entities.values()
                if checks.chores.kind_of(shape.get("name") or ""))
    return {
        "built_at": store.get("built_at", 0),
        "measured": len(entities),
        "asked": store.get("asked", 0),
        # The gap between the two is the one worth reading: nine
        # profiled sensors and no chores means nothing here is named
        # like a machine somebody has to empty.
        "chore_capable": named,
    }


def _requests_diagnostics() -> dict:
    """What has come in from outside the panel, and what is stuck.

    A queue nobody can see is a queue that silently swallows: "nothing
    has been ticked this week" and "the loop died on Tuesday holding
    four answers" look identical from every other surface.
    """
    return {
        "pending": finding_requests.pending(),
        "applied": REQUESTS_STATE["applied"],
        "missed": REQUESTS_STATE["missed"],
        "last": int(REQUESTS_STATE["last"]),
    }


# The bedtime pass. Same shape as the brief's: a cheap poll, a window
# derived from what this house actually does, and at most one a day.
EVENING_POLL_S = 5 * 60
EVENING_FIRST_DELAY_S = 420
EVENING_STATE: dict = {"last_run": 0.0}


async def _evening_loop():
    """Run the checks once around this house's own bedtime.

    `evening.left_open` can only speak while it is late here, and the
    scheduled pass runs every `checks_interval_hours` from whenever the
    add-on started — so on most houses it would simply never be awake in
    the window. This is what makes the check reachable; it runs the whole
    pass rather than that one check, because the checks are cheap and a
    second route into the store is a second thing to keep true.
    """
    await asyncio.sleep(EVENING_FIRST_DELAY_S)
    while True:
        try:
            now = time.time()
            local = _local_now(now)
            settles = rhythm.settle_minute(rhythm.profile(), local)
            if brief.due(now, local.hour * 60 + local.minute, settles,
                         checks.evening.FALLBACK_HOUR,
                         EVENING_STATE["last_run"], grace_min=30):
                EVENING_STATE["last_run"] = now
                summary = await run_checks("bedtime")
                log.info("bedtime pass: %s ran, %s filed",
                         len(summary.get("ran") or []),
                         summary.get("created", 0))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a pass
            log.warning("bedtime pass failed: %s", exc)
        await asyncio.sleep(EVENING_POLL_S)


# Overnight self-healing. Same shape as the bedtime pass — a cheap poll and
# a window derived from what this house actually does — and one more
# refusal on top of it: this one is OFF unless somebody switched it on.
HEAL_POLL_S = 5 * 60
HEAL_FIRST_DELAY_S = 900
HEAL_STATE: dict = {"last": None, "running": False}


def _healing_enabled() -> bool:
    """The `self_healing` option, live, with run.sh's export as fallback.

    Read exactly the way `findings_notify_service` is, so a Configuration-tab
    edit lands without a restart and an unreachable Supervisor still gets
    the answer somebody set at boot.
    """
    opts = addon_options.snapshot() or {}
    on = opts.get("self_healing")
    if on is None:
        on = os.environ.get("BRAIN_SELF_HEALING", "").lower() in (
            "true", "1", "yes")
    return bool(on)


def _healing_window(now: float) -> tuple[bool, str]:
    """Whether tonight's pass is due, and the sentence for why not."""
    local = _local_now(now)
    start, end = _quiet_hours()
    settles = rhythm.settle_minute(rhythm.profile(), local)
    return healing.window(local, start, end, settles)


async def run_healing(reason: str = "schedule") -> dict:
    """One night's pass: plan against the house, make at most three calls.

    The snapshot is `checks.snapshot.collect` — the same one the checks
    read — because a second fetcher would be a second answer to "what is
    broken here", and the finding this is acting on came out of the
    first one.

    Nothing verifies itself. The next checks pass clears the row or it
    does not, and the morning brief says which: a call returning 200 is
    the Supervisor accepting a request, which is not the same claim.
    """
    if HEAL_STATE["running"]:
        return {"error": "a healing pass is already running"}
    HEAL_STATE["running"] = True
    started = time.time()
    night = healing.night_key(_local_now(started))
    try:
        store = await asyncio.to_thread(healing.load)
        done = healing.attempted_tonight(store, night)
        snapshot = await checks.snapshot.collect(started)
        rows = await asyncio.to_thread(findings_store.list_all, "open")
        patterns = automation_writer.protected_patterns()
        planned = await asyncio.to_thread(
            healing.plan, rows, snapshot, patterns, done,
            healing.MAX_PER_NIGHT, started)

        attempts = list(store["attempts"]) if store.get("night") == night else []
        skips = list(store["skips"]) if store.get("night") == night else []
        for skipped in planned["skips"]:
            skips.append(skipped)
            journal.record("healing", healing.OUTCOME_SKIP, ok=False,
                           error=str(skipped.get("reason") or "")[:200],
                           extra={"ts": skipped.get("ts"),
                                  "source": skipped.get("source")})

        import aiohttp  # noqa: PLC0415 — as `_offer_routines` does

        async with aiohttp.ClientSession() as session:
            for attempt in planned["attempts"]:
                ok, why = await healing.perform(session, attempt)
                row = {k: attempt.get(k) for k in
                       ("ts", "source", "remedy", "target", "label",
                        "sentence", "text")}
                row.update({"ok": ok, "error": why, "at": int(time.time())})
                attempts.append(row)
                # Written after EVERY attempt, not at the end: a restart
                # at three in the morning must not find a pass that made
                # two calls and recorded none of them.
                await asyncio.to_thread(
                    healing.save, {"night": night,
                                   "started_at": int(started),
                                   "attempts": attempts, "skips": skips})
                journal.record(
                    "healing",
                    healing.OUTCOME_OK if ok else healing.OUTCOME_FAIL,
                    ok=ok, error="" if ok else why,
                    extra={"ts": attempt.get("ts"),
                           "remedy": attempt.get("remedy"),
                           "target": str(attempt.get("target") or "")[:60]})
                log.info("healing: %s — %s", attempt.get("sentence"),
                         "done" if ok else f"failed: {why}")

        state = {"night": night, "started_at": int(started),
                 "finished_at": int(time.time()), "reason": reason,
                 "attempts": attempts, "skips": skips}
        await asyncio.to_thread(healing.save, state)
        HEAL_STATE["last"] = state
        log.info("healing pass (%s): %d attempted, %d skipped",
                 reason, len(planned["attempts"]), len(planned["skips"]))
        return state
    except Exception as exc:  # noqa: BLE001 — a bad pass must not take the loop down
        log.warning("healing pass failed: %s", exc)
        journal.record("healing", "error", error=str(exc))
        return {"error": str(exc)[:300], "night": night}
    finally:
        HEAL_STATE["running"] = False


async def _heal_loop():
    """Once a night, inside the window, and only when it is switched on."""
    await asyncio.sleep(HEAL_FIRST_DELAY_S)
    while True:
        try:
            if _healing_enabled():
                now = time.time()
                # The window is asked here and again in the diagnostics,
                # rather than cached between them: a stale "why not" is
                # the failure this whole file is built to avoid, and the
                # question is arithmetic over two numbers.
                due, _why = _healing_window(now)
                if due:
                    night = healing.night_key(_local_now(now))
                    store = await asyncio.to_thread(healing.load)
                    if store.get("night") != night:
                        await run_healing("schedule")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a pass
            log.warning("healing loop failed: %s", exc)
        await asyncio.sleep(HEAL_POLL_S)


def _healing_diagnostics() -> dict:
    """Whether it is on, when it would run, and what last night did.

    A self-healer that has never run looks exactly like one with nothing
    to fix, so the *reason* rides here — including the one refusal
    nothing else could report: no quiet hours and no measured settle
    time, which means brAIn does not know when nobody is looking.
    """
    on = _healing_enabled()
    try:
        store = HEAL_STATE["last"] or healing.load()
    except Exception as exc:  # noqa: BLE001 — a dev checkout has no /data
        return {"enabled": on, "error": str(exc)[:120]}
    # Asked fresh rather than read off the loop's last tick: the dialog is
    # opened when somebody wants to know NOW, and the loop's answer is up
    # to five minutes old and says nothing at all before its first pass.
    reason, due = "", False
    if on:
        try:
            due, reason = _healing_window(time.time())
        except Exception as exc:  # noqa: BLE001 — a dev checkout has no
            # rhythm store, and "I could not work it out" is an answer.
            reason = str(exc)[:120]
    return {
        "enabled": on,
        "max_per_night": healing.MAX_PER_NIGHT,
        "remedies": sorted(healing.REMEDIES),
        "in_window": bool(due),
        # Empty while it is on and inside its window: there is nothing
        # stopping it, and a "reason" beside a working pass is noise —
        # the same rule `budget_state` follows about an excuse next to a
        # number that is fine.
        "reason": "" if (not on or due) else reason,
        "night": store.get("night", ""),
        "last_run": int(store.get("started_at") or 0),
        "attempts": store.get("attempts") or [],
        "skips": store.get("skips") or [],
    }


def _healing_brief_lines() -> list[str]:
    """Last night's healing, as sentences, or nothing at all."""
    if not _healing_enabled():
        return []
    try:
        store = healing.load()
        if not store.get("attempts"):
            return []
        open_ids = {int(f.get("ts") or 0)
                    for f in findings_store.list_all("open")}
        tz, _name = baselines.house_timezone()
        return healing.brief_lines(store, open_ids, tz)
    except Exception as exc:  # noqa: BLE001 — a brief without this is still
        # a brief; one that failed because of it is not.
        log.info("brief could not read the healing store: %s", exc)
        return []


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


# "when the guests leave, turn the porch light off" — the ask bar's third
# verb. A sentence shaped like a moment is not a question about the house
# and never becomes a card: it becomes one automation that runs once and
# switches itself off. Anchored at the start, because "tell me when the
# freezer is unusual" is an intent and "what happens when the freezer
# warms up" is a question, and the difference is which word opens it.
# Literal spaces, like `SCENE_RE`'s and for its reason: `h_generate`
# collapses the question first, and `^\s*` beside `(?:please\s+)?` is two
# adjacent pieces that can both eat the same run of them.
INTENT_RE = re.compile(
    r"^(?:please )?(?:when(?:ever)?|once|as soon as|"
    r"the next time|next time|tell me when|let me know when|"
    r"remind me when)\b",
    re.IGNORECASE)


# "design my evening for the living room" — the ask bar's fourth verb, and
# the narrowest of them. It names a room and asks for four moods, which is
# neither a question about the house nor a thing that happens once, so it
# is matched on the shape of the sentence rather than on a leading word:
# the area is the whole of what this needs, and anything that does not
# name one falls through to the ordinary path.
# Matched against a question whose whitespace `h_generate` has already
# collapsed to single spaces, which is what lets every space in here be a
# literal one. Two adjacent pieces that can both consume the same run of
# spaces is a regex that backtracks polynomially over a line of them —
# CodeQL reads that as a denial of service and it is right: the first cut
# had `(?:\w+\s+){0,2}?` against `[^.?!]*?` against a trailing `\s*`, and
# a question of five hundred spaces is a question somebody can send.
SCENE_RE = re.compile(
    r"^(?:please )?"
    r"(?:design|set up|(?:\w+ ){0,2}?scenes?)\b"
    r"[^.?!]*?\bfor (?:the |my )?(?P<area>[^,.?!]{2,40}?)[.?!]?$",
    re.IGNORECASE)


async def h_generate(request: web.Request) -> web.Response:
    body = await request.json()
    # Collapsed before any pattern sees it: it is what makes every space
    # in `SCENE_RE` a single literal one (see the note there), and it is
    # also what stops a room's name arriving as two lines.
    question = " ".join((body.get("question") or "").split()) or None
    if question:
        if len(question) > 500:
            raise web.HTTPBadRequest(text="question too long")
        scene_match = SCENE_RE.match(question)
        if scene_match:
            area = scene_match.group("area").strip()
            return web.json_response(
                {"queued": [], **await _design_scenes(area)})
        if INTENT_RE.match(question):
            # The same request file the `brain.intent` service writes, so
            # the expensive half — a Claude run, the checks, the card —
            # has one implementation and one place to be wrong.
            queued = await asyncio.to_thread(intents.request, question,
                                             "panel")
            return web.json_response({"queued": [], "intent": queued})
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


def _record_routines(snapshot: dict, now: float) -> int:
    """File the person-caused moves this pass saw, for the habit miner.

    The third and last of these, and the narrowest: only changes a
    *person* caused, only in the domains a time trigger can act on, and
    an automated move kept as one timestamp per key rather than as a row.
    See `routines.py` for why that is not the timeline `actions.py`
    refuses to keep.
    """
    mined = snapshot.get("actions") or {}
    if not mined.get("available"):
        return 0
    try:
        return routines.record(mined.get("actions") or [], now)
    except Exception as exc:  # noqa: BLE001 — accounting must not fail the
        # pass it is accounting for; same rule as `journal.record`.
        log.warning("could not file this pass's routines: %s", exc)
        return 0


async def _offer_routines(now: float) -> int:
    """Turn what the ledger can prove into proposals. Returns how many landed.

    Deliberately after the checks have been applied and deliberately not
    part of them: a proposal is not a finding, it goes to a different
    store and a different tab, and a habit miner that could fail a checks
    pass would be an offer costing a house its list of what is broken.

    Each one is replayed over the same history before it is offered,
    because a suggestion arrives with its evidence or it deserves a no —
    and a replay that refuses is not a reason to withhold the proposal,
    only to show what could not be answered. `proposals.add` dedupes
    against the live rows and the settled ledger, so a habit that is
    still a habit is not offered again every six hours.
    """
    import aiohttp

    try:
        tz, _name = await asyncio.to_thread(baselines.house_timezone)
        # The option is read here rather than in the miner, which stays
        # pure — and it is applied at the producer as well as at the
        # writer, because a card offering something brAIn will refuse to
        # write is a wasted no.
        protected = automation_writer.protected_patterns()
        found = await asyncio.to_thread(routines.mine, None, tz, now, None,
                                        protected)
    except Exception as exc:  # noqa: BLE001 — an offer is optional; the
        # pass that would have made it is not.
        log.warning("could not mine routines: %s", exc)
        return 0
    if not found:
        return 0

    offered = 0
    async with aiohttp.ClientSession() as session:
        for routine in found:
            obj = routines.as_proposal(routine)
            if not obj:
                continue
            # Asked before the replay rather than after: a habit that is
            # still a habit is mined every six hours, and the store would
            # refuse it anyway — this is what stops a producer whose
            # config watches entities paying for a month of history to be
            # told so.
            if await asyncio.to_thread(proposals.knows, obj):
                continue
            obj["replay"] = await _replay_config(
                session, obj["config"], now - REPLAY_DAYS * 86400, now, tz)
            row = await asyncio.to_thread(proposals.add, obj)
            if row:
                offered += 1
    if offered:
        log.info("proposed %d change%s from what you do by hand",
                 offered, "" if offered == 1 else "s")
    return offered


# What the condition miner saw and would not act on, kept for the
# diagnostics bundle. A pattern brAIn can see and will not touch — an
# automation with no id, one that already stands down over those hours —
# is not a card, because every card on the Proposals tab can be answered
# and that one cannot; but "brAIn found nothing" and "brAIn found this and
# named the thing to change" are different reports, and an empty tab reads
# the same either way.
CONDITIONS_STATE: dict = {"refused": [], "seen": 0, "at": 0}


async def _offer_conditions(snapshot: dict, now: float) -> int:
    """Offer the condition each overridden automation lacks. Returns how many.

    The evidence is `override_ledger.pattern`'s and is never re-derived
    here — every floor that makes a band mean something already lives in
    the ledger, and a second answer to "is this a pattern" is the one
    nobody can see.

    Both replays are run, and that pair is the whole case on the card:
    what the automation does over the last thirty days, and what it would
    do with the condition on it. One number on its own is a fact about an
    automation rather than an argument for changing it.
    """
    import aiohttp  # noqa: PLC0415 — as `_offer_routines` does

    try:
        tz, _name = await asyncio.to_thread(baselines.house_timezone)
        protected = automation_writer.protected_patterns()
        found = await asyncio.to_thread(
            conditions.build, snapshot, None, tz, now, protected)
    except Exception as exc:  # noqa: BLE001 — an offer is optional; the
        # pass that would have made it is not.
        log.warning("could not read the overrides for conditions: %s", exc)
        return 0
    CONDITIONS_STATE["seen"] = len(found)
    CONDITIONS_STATE["at"] = int(now)
    CONDITIONS_STATE["refused"] = [
        {"automation": (r.get("automation") or {}).get("alias") or "",
         "why": r["refused"]} for r in found if r.get("refused")]

    offered = 0
    async with aiohttp.ClientSession() as session:
        for obj in found:
            if obj.get("refused") or not obj.get("config"):
                continue
            if await asyncio.to_thread(proposals.knows, obj):
                continue
            before = obj.pop("before_config", None)
            window = (now - REPLAY_DAYS * 86400, now)
            if before:
                obj["replay_before"] = await _replay_config(
                    session, before, window[0], window[1], tz)
            obj["replay"] = await _replay_config(
                session, obj["config"], window[0], window[1], tz)
            if await asyncio.to_thread(proposals.add, obj):
                offered += 1
    if offered:
        log.info("proposed %d condition%s from what you keep undoing",
                 offered, "" if offered == 1 else "s")
    return offered


# The last thing the ask bar can start, and the only producer a person
# addresses by name. It is kept here beside the others because it files
# through the same store and answers to the same rules; what is different
# is that somebody is waiting for it, which is why the refusal is
# synchronous and only the naming run is not.
SCENES_STATE: dict = {"designed": 0, "refused": 0, "last": "", "at": 0}


async def _name_and_offer(obj: dict, area: str) -> None:
    """Ask Claude for four names, then offer the set. Never raises.

    The **one** optional model run in this feature, and it names things.
    Everything about which bulb takes which kelvin is composed from the
    registries, because a model choosing that is a guess wearing a config
    and one nobody can check by looking at the card. A failed run leaves
    the plain names, which are a perfectly good answer.
    """
    try:
        result = await asyncio.to_thread(
            engine.run_claude, scenes.name_prompt(area), scenes.SYSTEM,
            eff_model(), scenes.NAME_TIMEOUT_S, scenes.NAME_MAX_TURNS,
            "scene")
        names = scenes.read_names(result.get("text")
                                  or result.get("raw") or "")
    except Exception as exc:  # noqa: BLE001 — the card renders from the
        # deterministic names, which is why there are some.
        log.info("could not name the %s scenes: %s",
                 log_safe(area), exc)
        names = {}
    if names:
        # Re-composed rather than renamed in place: the name is inside the
        # scene's `name`, which is what the entity id comes from, and
        # patching one of the two would leave a schedule calling a scene
        # that is not there.
        obj = await asyncio.to_thread(
            scenes.build, obj.pop("_snapshot"), area,
            automation_writer.protected_patterns(), names)
        if obj.get("refused"):
            return
    else:
        obj.pop("_snapshot", None)
    if await asyncio.to_thread(proposals.add, obj):
        SCENES_STATE["designed"] += 1
        log.info("proposed four scenes for the %s", log_safe(area))


async def _design_scenes(area: str) -> dict:
    """Compose four scenes for one area. Returns what to tell the person.

    Two phases on purpose. Composing is deterministic and takes one fetch,
    so a **refusal comes back on the request** — *"the box room has one
    light in it"* is an answer somebody should have before they wonder
    whether anything is happening. Naming them is a Claude run, so the
    offer lands on the tab afterwards: a request that waited on a model
    is a request ingress cuts.
    """
    area = str(area or "").strip()[:60]
    SCENES_STATE["last"] = area
    SCENES_STATE["at"] = int(time.time())
    if not area:
        return {"refused": "brAIn could not tell which room that was."}
    try:
        snap = await checks.snapshot.collect_rooms()
    except Exception as exc:  # noqa: BLE001 — "I could not look" is its own
        # answer, and it is about brAIn rather than about the room.
        log.warning("could not read the house for scenes: %s", exc)
        return {"refused": f"brAIn could not read the house just now: {exc}"}

    protected = automation_writer.protected_patterns()
    obj = await asyncio.to_thread(scenes.build, snap, area, protected, None)
    if obj.get("refused"):
        SCENES_STATE["refused"] += 1
        return {"refused": obj["refused"], "area": area}
    if await asyncio.to_thread(proposals.knows, obj):
        return {"refused": (f"brAIn has already offered these four scenes "
                            f"for the {area} — the answer is on the "
                            "Proposals tab."), "area": area}
    obj["_snapshot"] = snap
    asyncio.create_task(_name_and_offer(obj, area))
    return {"scenes": area, "lights": len(obj["scene"]["lights"])}


async def _offer_scene_schedule(snapshot: dict, now: float) -> int:
    """Offer the schedule for any room whose four scenes really exist.

    Read off `scenes.yaml` rather than off the proposals ledger, because
    what makes the schedule sayable is the scenes being *there* — somebody
    who copied the card's YAML in by hand has earned it exactly as much as
    somebody who pressed the button. And it is an ordinary automation, so
    it goes through 1.44.0's path unchanged and can be tried for a week.
    """
    if snapshot.get("scenes") is None:
        return 0                     # scenes.yaml unreadable: not "no scenes"
    try:
        payload = await asyncio.to_thread(rhythm.load)
        tz, _name = await asyncio.to_thread(baselines.house_timezone)
    except Exception as exc:  # noqa: BLE001
        log.info("could not read the rhythm for a scene schedule: %s", exc)
        payload, tz = {}, None

    import datetime as dt  # noqa: PLC0415 — one call, once a pass
    import aiohttp  # noqa: PLC0415 — as `_offer_routines` does

    when = dt.datetime.fromtimestamp(now, tz or dt.timezone.utc)
    wake = rhythm.wake_minute(payload, when) if payload else None
    settle = rhythm.settle_minute(payload, when) if payload else None

    areas = {str(cfg.get("id") or "").split("_")[2]
             for cfg in (snapshot.get("scenes") or [])
             if isinstance(cfg, dict)
             and str(cfg.get("id") or "").startswith(scenes.ID_PREFIX)
             and len(str(cfg.get("id") or "").split("_")) > 3}
    offered = 0
    async with aiohttp.ClientSession() as session:
        for slug in sorted(a for a in areas if a):
            # The area's own name, as the registries have it — the slug in
            # the id is what survives a rename and the name is what a card
            # says.
            house = scenes._house(snapshot)
            name = next((a for a in {house.area_of(e)
                                     for e in (snapshot.get("states") or {})}
                         if a and scenes._slug(a) == slug), slug)
            obj = await asyncio.to_thread(scenes.schedule, snapshot, name,
                                          wake, settle)
            if not obj or await asyncio.to_thread(proposals.knows, obj):
                continue
            # Four `time` triggers replay like any habit's, and the card
            # owes the same line the routine miner's does — "would have
            # fired 28 times last month" is the sanity check on the two
            # measured times. Asked after `knows`, as `_offer_routines`
            # does, so a schedule already answered costs no history.
            obj["replay"] = await _replay_config(
                session, obj["config"], now - REPLAY_DAYS * 86400, now, tz)
            if await asyncio.to_thread(proposals.add, obj):
                offered += 1
    if offered:
        log.info("proposed %d scene schedule%s", offered,
                 "" if offered == 1 else "s")
    return offered


async def _offer_playbooks(snapshot: dict, now: float) -> int:
    """Offer the emergency playbooks this house can have. Returns how many.

    Deterministic all the way through: the registries in the snapshot the
    checks already collected say which detectors exist and which lights,
    thermostats, blinds, valves and water heaters they would act on. No
    model chooses any of that — a model picking which valve closes is a
    guess wearing a config, and one nobody can check afterwards because
    the automation looks the same either way.

    The one optional Claude run is the **paragraph on the card**, and a
    run that fails leaves the deterministic sentence exactly where it
    was. It happens at most once per class per sensor set, because
    `proposals.knows` is asked first — a house whose playbooks are all
    answered costs nothing on every later pass.
    """
    service, _sev = _findings_notify_target()
    try:
        protected = automation_writer.protected_patterns()
        found = await asyncio.to_thread(
            playbooks.build, snapshot, protected, service)
    except Exception as exc:  # noqa: BLE001 — an offer is optional; the
        # pass that would have made it is not.
        log.warning("could not compose playbooks: %s", exc)
        return 0

    offered = 0
    for obj in found:
        if await asyncio.to_thread(proposals.knows, obj):
            continue
        try:
            result = await asyncio.to_thread(
                engine.run_claude, playbooks.describe_prompt(obj),
                playbooks.SYSTEM, eff_model(),
                playbooks.DESCRIBE_TIMEOUT_S, playbooks.DESCRIBE_MAX_TURNS,
                "playbook")
            obj["why"] = playbooks.tidy_description(
                result.get("text") or result.get("raw") or "", obj["why"])
        except Exception as exc:  # noqa: BLE001 — the card renders from the
            # deterministic sentence, which is why there is one.
            log.info("could not describe the %s playbook: %s",
                     (obj.get("playbook") or {}).get("class"), exc)
        if await asyncio.to_thread(proposals.add, obj):
            offered += 1
    if offered:
        log.info("proposed %d emergency playbook%s",
                 offered, "" if offered == 1 else "s")
    return offered


async def _poll_intents(now: float) -> int:
    """Ask Home Assistant whether each armed one-off has fired. Returns how
    many moved.

    `last_triggered` off the automation itself, not "the automation is
    off": somebody switching it off by hand is not it having fired, and
    the difference is the whole of what the card claims. The stamp has to
    be **after** the accept, or an automation sharing a slug with one that
    ran last month reads as done the moment it is armed.

    An entity Core has no state for is left exactly as it is. "I could
    not look" and "it has not happened" are different answers, and only
    the second one belongs on a card.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    rows = [r for r in await asyncio.to_thread(intents.listing)
            if r.get("status") == "armed" and r.get("entity_id")]
    moved = 0
    for row in rows:
        try:
            state = await ha_data.entity_state(row["entity_id"])
        except Exception as exc:  # noqa: BLE001 — one unreadable entity is
            # not a reason to stop asking about the next.
            log.info("could not read %s: %s", row["entity_id"], exc)
            continue
        when = intents.fired_from_state(row, state)
        if when and await asyncio.to_thread(intents.mark_fired, row["ts"], when):
            moved += 1
            log.info("the one-off %s fired",
                     log_safe(row.get("title") or row["ts"]))
    return moved


async def _evaluate_trials(now: float) -> int:
    """Re-grade every running trial against the week so far. Returns how many.

    1.42.0 set `trialling` and a `trial_ends_at` and never looked again,
    so the one step that separates a suggestion from a change reported
    nothing — which from the tab is indistinguishable from a trial that
    is not running. There is no live-event subscription behind this and
    there does not need to be: `shadow.replay` says when the automation
    would have fired over a window the recorder already holds, and
    `routines.load()` says what a person did in it.

    It runs on **every** pass rather than once at the end, because a
    replay costs one history fetch and a card that says *"three days in,
    it would have fired three times and you did the same twice"* is worth
    more than a blank one until Sunday. When the week is up the row stays
    `trialling` with its result attached: ending a trial is a person's
    press, which is the same reason `proposals.record_trial` refuses to.
    """
    import aiohttp  # noqa: PLC0415 — as `_offer_routines` does

    rows = [r for r in await asyncio.to_thread(proposals.listing)
            if r.get("status") == "trialling"]
    if not rows:
        return 0
    tz, _name = await asyncio.to_thread(baselines.house_timezone)
    ledger = await asyncio.to_thread(routines.load)
    person_rows = ledger.get("rows") or []

    graded = 0
    async with aiohttp.ClientSession() as session:
        for row in rows:
            try:
                result = await _trial_result(session, row, person_rows,
                                             now, tz)
            except Exception as exc:  # noqa: BLE001 — a trial is a report;
                # the pass that would have written it is not optional.
                log.warning("could not evaluate the trial on %s: %s",
                            row.get("ts"), exc)
                continue
            if result is None:
                continue
            if await asyncio.to_thread(
                    proposals.record_trial, row["ts"], result):
                graded += 1
    return graded


async def _trial_result(session, row: dict, person_rows: list[dict],
                        now: float, tz) -> dict | None:
    """One trial's report, or None when the row is not one yet.

    The window is the trial's own — from when it started to now, or to
    when it ended, whichever came first. Reading it to `now` past the end
    would go on re-grading a finished week with days it was never
    watching, which is a report that quietly changes after it is read.
    """
    config = row.get("config")
    started = float(row.get("trial_started_at") or 0)
    if not isinstance(config, dict) or not started:
        return None
    end = min(now, float(row.get("trial_ends_at") or now))
    if end <= started:
        return None

    watched = sorted(shadow.entities_watched(config))
    if len(watched) > shadow.MAX_ENTITIES:
        return {"refused": True,
                "error": f"this reads {len(watched)} entities, more than a "
                         "replay can honestly rebuild",
                "window": {"start": int(started), "end": int(end)}}
    history = {}
    if watched:
        history = await shadow.fetch_history(session, watched, started, end)
    return await asyncio.to_thread(
        trials.evaluate, config, history, person_rows, started, end, tz, now)


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
        await asyncio.to_thread(_record_routines, snapshot, started)
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
        # After the findings, and outside them. A proposal is not a
        # finding: different store, different tab, and a habit miner
        # that could fail this pass would cost a house its list of what
        # is broken to make an offer nobody asked for.
        try:
            offered = await _offer_routines(started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer routines: %s", exc)
            offered = 0
        # And the other producer: the automation brAIn would write for a
        # night nobody wants. Same store, same tab, same refusal to
        # enable anything on its own.
        try:
            offered += await _offer_playbooks(snapshot, started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer playbooks: %s", exc)
        # And the third: the condition an automation somebody keeps
        # undoing does not have. The finding already reports the fight;
        # this is the change that ends it.
        try:
            offered += await _offer_conditions(snapshot, started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer conditions: %s", exc)
        # And the fourth: the schedule that walks a room through the four
        # scenes it now has. Only once they really exist — a schedule
        # naming a scene that is not there errors at 07:00 every morning.
        try:
            offered += await _offer_scene_schedule(snapshot, started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer a scene schedule: %s", exc)
        # And the other half of the same lifecycle: a trial that nothing
        # evaluates is a status with no report behind it.
        try:
            graded = await _evaluate_trials(started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not evaluate trials: %s", exc)
            graded = 0
        # And the one-offs: whether the thing somebody was waiting for has
        # happened. Nothing is removed here — a card says it fired and
        # offers to take it out, because an automation that vanished from
        # somebody's file while they were not looking is a file they
        # cannot trust.
        try:
            fired = await _poll_intents(started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not check the armed one-offs: %s", exc)
            fired = 0
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
            "proposed": offered,
            "trials_evaluated": graded,
            "intents_fired": fired,
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
            # The same pass, because it is the same claim about the same
            # house over the same month — and it has already paid for the
            # one /states fetch both halves need.
            shut = await closures.build(session, by_id, started)
            # And the third: one /states fetch, three measurements of the
            # same house over the same nights. This one reads FIVE-MINUTE
            # statistics rather than hourly ones, because a dishwasher's
            # dry phase is twenty minutes and an hour cannot see it —
            # which is more rows per entity than the baselines read, and
            # is bounded by asking only power sensors and only ten days.
            machines = await appliances.build(session, by_id, started)
            # And the fourth. This one needs the registries as well as the
            # states — a room has to be nameable before it is worth
            # measuring, and "which thermometer is outdoors" is largely
            # "the one in no area at all".
            areas, devices, ents = await ha_data._ws_commands(session, [
                {"type": "config/area_registry/list"},
                {"type": "config/device_registry/list"},
                {"type": "config/entity_registry/list"}])
            rooms = await thermal.build(
                session, by_id,
                {"areas": areas or [], "devices": devices or [],
                 "entities": ents or []}, started)
        summary = {"reason": reason, "started_at": int(started),
                   "finished_at": int(time.time()),
                   "duration_s": round(time.time() - started, 1),
                   "measured": len(payload.get("entities") or {}),
                   "asked": payload.get("asked", 0),
                   "closures": len(shut.get("entities") or {}),
                   "appliances": len(machines.get("entities") or {}),
                   "rooms": len(rooms.get("rooms") or {}),
                   "tz": payload.get("tz", ""), "error": ""}
        journal.record("baselines", "ok", duration_s=summary["duration_s"],
                       extra={"measured": summary["measured"],
                              "asked": summary["asked"]})
    except Exception as exc:  # noqa: BLE001 — a bad pass must not take the loop down
        log.warning("baseline pass failed: %s", exc)
        journal.record("baselines", "error", error=str(exc))
        summary = {"reason": reason, "started_at": int(started),
                   "finished_at": int(time.time()), "measured": 0, "asked": 0,
                   "closures": 0, "appliances": 0, "rooms": 0, "tz": "",
                   "error": str(exc)[:300]}
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


async def h_weekly(request: web.Request) -> web.Response:
    """The week's own numbers, and the last report that went out.

    A weekly report delivered once to a phone and then gone is a report
    nobody can re-read, quote or check — so what was sent stays here,
    beside the numbers it was written from.
    """
    now = time.time()
    on, want_day = _weekly_enabled()
    service, _sev = _findings_notify_target()
    state = await _weekly_state(now)
    return web.json_response({
        "enabled": on,
        "day": weekly.DAYS[want_day],
        "notify_service": service,
        "last_sent": int(WEEKLY_STATE["last_sent"]),
        "last_error": WEEKLY_STATE["last_error"],
        "last_text": WEEKLY_STATE["last_text"],
        "worth_reporting": weekly.worth_reporting(state),
        "energy": state.get("energy") or {},
        "findings": state.get("findings") or {},
        "learned": state.get("learned") or {},
        "one_thing": state.get("one_thing"),
    })


async def h_weekly_run(request: web.Request) -> web.Response:
    """Send this week's report now.

    A report that goes out moves the week rather than adding to it — two
    reports about overlapping weeks is how the numbers in them stop
    meaning anything — while one that found nothing leaves the schedule
    alone.
    """
    service, _sev = _findings_notify_target()
    if not service:
        return web.json_response(
            {"error": "no notification service is configured"}, status=409)
    now = time.time()
    # Stamped before the run so a second press cannot start a second
    # pass, and put back when nothing was sent: asking by hand on a
    # Saturday and finding the week empty must not silently cancel the
    # Sunday report that would have had another day's material.
    before = WEEKLY_STATE["last_sent"]
    WEEKLY_STATE["last_sent"] = now
    body = await _send_weekly(now)
    WEEKLY_STATE["last_sent"] = now if body else before
    schedule_store.set(WEEKLY_SENT_KEY, WEEKLY_STATE["last_sent"])
    return web.json_response({
        "sent": bool(body), "text": body,
        "error": WEEKLY_STATE["last_error"],
    })


async def h_appliances(request: web.Request) -> web.Response:
    """What each machine's own history says about it.

    The measurement is universal — every power sensor with an
    appliance's shape gets a profile — while the chore is narrow, so
    this is where somebody checks whether their washing machine was
    measured at all before wondering why no chore ever arrives.
    """
    store = await asyncio.to_thread(appliances.load)
    rows = []
    for eid, shape in sorted((store.get("entities") or {}).items()):
        rows.append({"entity_id": eid, **shape,
                     "chore_kind": checks.chores.kind_of(
                         shape.get("name") or "")})
    return web.json_response({
        "built_at": store.get("built_at", 0),
        "asked": store.get("asked", 0),
        "days": store.get("days", appliances.HISTORY_DAYS),
        "appliances": rows,
    })


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
    _closure_store = closures.load()
    _thermal_store = thermal.load()
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
        # What was mended while the house slept, and — when nothing was —
        # why not. "It is off", "it is not the window yet" and "this house
        # has no measured settle time and no quiet hours" are three
        # different silences, and only the last one needs anything doing.
        "healing": _healing_diagnostics(),
        # The two things that decide when a person hears from brAIn, and
        # both are invisible from outside: a rhythm that never gathered
        # enough days looks exactly like one that did and chose 07:00.
        "rhythm": _rhythm_diagnostics(),
        # The week's own report: whether it is on, which day it goes, and
        # what the last gather actually held. A report that has never
        # sent because nothing was worth reporting reads, from outside,
        # exactly like one whose loop died in March.
        "weekly": _weekly_diagnostics(),
        # Answers given in the To-do app or on a notification, on
        # their way back to the one store that owns them.
        "finding_requests": _requests_diagnostics(),
        # What you do by hand, and what has been offered because of it.
        # An empty Proposals tab reads the same whether the miner found
        # no habit or the ledger has been empty for a month.
        "routines": _routines_diagnostics(),
        "proposals": _proposals_diagnostics(),
        # Numbers, not the buckets: a bug report needs to know whether
        # the house has been watched and when, not 168 fractions for
        # sixty doors.
        "closures": {
            "built_at": _closure_store.get("built_at", 0),
            "measured": len(_closure_store.get("entities") or {}),
            "asked": _closure_store.get("asked", 0),
        },
        # Same rule: the shapes, not the watts. How many machines have a
        # profile is the question a bug report needs — "no chores this
        # week" and "nothing here has a power sensor" look identical
        # from every other surface.
        "appliances": _appliance_summary(),
        # Same rule again, plus the one field that is not a count: with
        # no outdoor sensor there is no thermal model at all, and that is
        # a sentence rather than a zero — "no climate findings" and "no
        # room could be measured against anything" look identical from
        # every other surface, and only one of them is a house that is
        # fine.
        "thermal": {
            "built_at": _thermal_store.get("built_at", 0),
            "measured": len(_thermal_store.get("rooms") or {}),
            "asked": _thermal_store.get("asked", 0),
            "outdoor": _thermal_store.get("outdoor", ""),
            "coldest": _thermal_store.get("coldest"),
            "reason": _thermal_store.get("reason", ""),
        },
        # How many conversations the chat is holding open, how many are
        # answering, and what the cap is. A session the cap stopped and one
        # that crashed leave the same silence otherwise.
        "chat": chat_session.registry().summary(),
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

    payload, fact = await _end_finding(finding, spec, note)
    # Both endings delete the row, which is the point of them and also the
    # reason this exists: they sit next to each other and mean opposite
    # things, so a mis-tap is not hypothetical and there is nothing to put
    # back by hand.
    payload["undo"] = undo_store.record(
        "finding", finding=finding, key=findings_store.normalize(finding["text"]),
        fact=fact, fact_source=spec.get("source", "homeowner"))
    return web.json_response(payload)


async def _end_finding(finding: dict, spec: dict, note: str) -> tuple[dict, str]:
    """Settle a finding and record what it taught. One implementation.

    Both front doors reach this: the tab's own buttons, and a request
    dropped on the shared volume by a tick in the To-do app or a button
    on a notification. A second copy would be the same press teaching
    brAIn two different things depending on where it was made.
    """
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
    return payload, fact


# ---------------------------------------------------------------------------
# Proposals, and the replay behind them
# ---------------------------------------------------------------------------

def _proposals_payload() -> dict:
    rows = proposals.listing()
    now = time.time()
    armed = intents.listing()
    for row in armed:
        # Derived here rather than stored, because "it has been waiting a
        # fortnight" is a fact about the clock and a stored one would be
        # a number that stops being true the moment it is written.
        row["overdue"] = intents.expired(row, now)
    return {"proposals": rows, "counts": proposals.counts(rows),
            # What is waiting to happen, what already has, and the
            # sentences brAIn would not arm. Not proposals — nobody owes
            # an answer on an armed one — so they are counted separately
            # and the badge does not move for them.
            "intents": armed,
            "intent_ttl_days": intents.INTENT_TTL_DAYS,
            "trial_days": proposals.TRIAL_DAYS,
            # So an empty tab can say what "enough times" means rather
            # than leaving somebody to wonder whether it is broken.
            "routine_min_days": routines.MIN_DAYS}


async def h_proposals(request: web.Request) -> web.Response:
    return web.json_response(
        await asyncio.to_thread(_proposals_payload))


async def h_playbook_rehearsal(request: web.Request) -> web.Response:
    """What this playbook would do, against what is true right now.

    It **calls nothing**. Home Assistant's `automation.trigger` would run
    the actions, which is not a rehearsal — it is the emergency — so this
    reads `/states` once and reports each target's state beside the state
    the call would produce.
    """
    ts = int(request.match_info["ts"])
    row = await asyncio.to_thread(proposals.get, ts)
    if row is None or not row.get("playbook"):
        return web.json_response(
            {"error": "that is not a playbook"}, status=404)

    import aiohttp  # noqa: PLC0415 — as `_offer_routines` does

    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`
    try:
        async with aiohttp.ClientSession() as session:
            raw = await ha_data._rest_get(session, "/states", timeout=30)
    except Exception as exc:  # noqa: BLE001 — "I could not ask" and "every
        # light is already on" are different answers, and only one of them
        # is about the house.
        return web.json_response(
            {"error": f"brAIn could not read the current states: {exc}"},
            status=502)
    states = {s["entity_id"]: s for s in (raw or [])
              if isinstance(s, dict) and s.get("entity_id")}
    return web.json_response(
        await asyncio.to_thread(playbooks.rehearsal, row, states))


async def h_scene_areas(request: web.Request) -> web.Response:
    """Every room brAIn could compose scenes for, with its light count.

    The picker's own list. A room with one bulb is never offered and then
    refused: a control that hands somebody a choice its own rule forbids
    is a control that teaches people to distrust it.
    """
    try:
        snap = await checks.snapshot.collect_rooms()
    except Exception as exc:  # noqa: BLE001 — "I could not ask" and "you
        # have no rooms" are different answers, and only one is about the
        # house. `h_ha_entities`' rule, one add-on over.
        return web.json_response(
            {"error": f"brAIn could not read the house: {exc}"}, status=502)
    protected = automation_writer.protected_patterns()
    return web.json_response({
        "areas": await asyncio.to_thread(scenes.areas_with_lights, snap,
                                         protected),
        "min_lights": scenes.MIN_LIGHTS,
    })


async def h_scene_design(request: web.Request) -> web.Response:
    """Design four scenes for one room. The picker's press.

    The same function the ask bar's sentence reaches, because two doors
    into "compose four moods" is two answers to what a mood is.
    """
    body = await _json_body(request)
    out = await _design_scenes(str(body.get("area") or ""))
    return web.json_response(out, status=409 if out.get("refused") else 200)


async def h_proposal_trial(request: web.Request) -> web.Response:
    ts = int(request.match_info["ts"])
    row = await asyncio.to_thread(proposals.start_trial, ts)
    if row is None:
        return web.json_response(
            {"error": "that proposal is not waiting to be tried"}, status=409)
    return web.json_response(
        {"proposal": row, **await asyncio.to_thread(_proposals_payload)})


# How long an accepted automation gets to appear in Home Assistant, and
# how often to ask. A reload is a config re-read rather than a restart —
# it lands in well under a second on a healthy house — so this is a
# ceiling on a failure, not a budget for a success.
ACCEPT_VERIFY_S = 12.0
ACCEPT_POLL_S = 0.4


async def _wait_for_entity(entity_id: str) -> bool:
    """Whether this entity turns up in Core within the ceiling."""
    import ha_data  # noqa: PLC0415 — deferred, so the module still loads
                    # without aiohttp in the tests that do not need it

    deadline = time.monotonic() + ACCEPT_VERIFY_S
    while True:
        if await ha_data.entity_exists(entity_id):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(ACCEPT_POLL_S)


async def _apply_accepted(row: dict) -> tuple[dict | None, str]:
    """Write it, reload, and check it is really there. Or put it back.

    Three claims, and they are not the same one. *The file was written*
    is `automation_writer.apply`. *Home Assistant read it* is the reload.
    *The automation exists* is a state in Core — and that last step is
    what separates this from BRight reporting a `play_media` call that
    was accepted as a speaker making a sound. A `mode:` Core does not
    recognise, a trigger a custom integration owns and has not loaded, a
    read-only `/config`: each of those leaves a file on disk, a reload
    that returns 200, and no automation.

    Any of the three failing puts the file back and reloads again, so a
    yes that could not be honoured leaves nothing behind — neither in
    `automations.yaml` nor on the proposal, which the caller only settles
    once this has come back with something.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    # A proposal that names `edits` changes an automation somebody already
    # has, so it goes through the splice rather than the append: their
    # entry comes back with one thing different and every other byte of
    # the file where it was. Everything after this point is identical,
    # because the three claims are the same three.
    # Which file this yes writes to. A scene proposal carries a LIST of
    # four moods and lands in `scenes.yaml`; everything else is one
    # automation. The five steps below are the same five either way,
    # which is why `apply` takes a target rather than having a twin.
    target = "scenes" if row.get("kind") == "scene" else "automations"
    if row.get("edits"):
        written = await asyncio.to_thread(automation_writer.apply_edit, row)
    else:
        written = await asyncio.to_thread(automation_writer.apply, row,
                                          target=target)
    if not written.get("ok"):
        return None, str(written.get("error")
                         or "brAIn could not write it")

    domain, service = written.get("reload") or ("automation", "reload")
    failure = ""
    try:
        await ha_data.call_core_service(domain, service)
    except Exception as exc:  # noqa: BLE001 — every way this fails is the
        # same answer to the person waiting: it did not take.
        failure = f"Home Assistant would not reload its {domain}s: {exc}"
    if not failure:
        # Every entity the write claimed, not the first: three scenes out
        # of four is a mood missing from a schedule nobody has written
        # yet, and the whole point of the third step is that the file
        # being on disk is not the thing existing.
        for eid in written.get("entity_ids") or [written["entity_id"]]:
            try:
                if not await _wait_for_entity(eid):
                    failure = (
                        f"it was written but {eid} never appeared in Home "
                        "Assistant, so it is not running — check the add-on "
                        "log and Home Assistant's own")
            except Exception as exc:  # noqa: BLE001
                failure = f"brAIn could not check whether {eid} appeared: {exc}"
            if failure:
                break
    if not failure:
        return written, ""

    reverted = await asyncio.to_thread(automation_writer.revert, written)
    try:
        await ha_data.call_core_service(domain, service)
    except Exception as exc:  # noqa: BLE001 — the file is already back;
        # a second failed reload is a log line, not a second error.
        log.warning("could not reload after putting the file back: %s", exc)
    if not reverted.get("ok"):
        failure += (" — and putting automations.yaml back failed: "
                    f"{reverted.get('error')}")
    log.warning("accepting proposal %s failed: %s", row.get("ts"), failure)
    return None, failure


async def _announce_accepted(row: dict, applied: dict) -> None:
    """Say out loud that the house now behaves differently.

    A sibling of `_announce_findings` rather than a finding dressed up as
    one: nothing is wrong, there is no severity to floor it against and
    no button on it that could end anything. A change nobody has read is
    not settled, which is the same argument that keeps a finished fix on
    the Findings list until somebody presses Got it.

    It is sent rather than held — see `notify_router.ACCEPTED_URGENCY`:
    this answers a press made seconds ago, so it is the one message here
    with somebody awake and looking by construction.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    service, _sev = _findings_notify_target()
    if not service:
        return
    title, body = notify_router.compose_accepted(
        str(row.get("title") or ""), str(applied.get("entity_id") or ""))
    try:
        await ha_data.send_notification(service, title, body)
    except Exception as exc:  # noqa: BLE001 — the automation is already
        # running; the notification is the courtesy copy.
        log.warning("accepted-change notification via %s failed: %s",
                    service, exc)


async def h_proposal_decide(request: web.Request) -> web.Response:
    """Accept or decline. The row leaves the list either way.

    A decline's note goes to the memory inbox exactly as a finding's
    "Wrong" does — one implementation of "what a person told us", so an
    answer teaches the same thing whichever list it was given on.

    An accept writes the automation **first** and settles the row only
    once Home Assistant is running it. A yes that could not be honoured
    is not a yes that was recorded: the refusal comes back as a 409 with
    the sentence, and the proposal is exactly where it was.
    """
    ts = int(request.match_info["ts"])
    verb = request.match_info["verb"]
    status = {"accept": "accepted", "decline": "declined"}.get(verb)
    if status is None:
        return web.json_response({"error": "unknown verb"}, status=404)
    body = await _json_body(request)
    note = str(body.get("note") or "")[:proposals.NOTE_MAX]

    applied = None
    if status == "accepted":
        pending = await asyncio.to_thread(proposals.get, ts)
        if pending is None or pending.get("status") not in \
                proposals.OPEN_STATUSES:
            return web.json_response(
                {"error": "that proposal has already been answered"},
                status=409)
        started = time.time()
        applied, why = await _apply_accepted(pending)
        journal.record("proposal", "applied" if applied else "error",
                       ok=bool(applied), error="" if applied else why,
                       duration_s=time.time() - started,
                       extra={"ts": ts})
        if applied is None:
            return web.json_response(
                {"error": why,
                 **await asyncio.to_thread(_proposals_payload)}, status=409)

    row = await asyncio.to_thread(proposals.decide, ts, status, note,
                                  None, applied)
    if row is None:
        return web.json_response(
            {"error": "that proposal has already been answered"}, status=409)
    fact = proposals.memory_line(row, status)
    if fact:
        await _submit_memory(fact, source="homeowner")

    if applied and row.get("kind") == "intent":
        # A proposal is answered and gone; an armed intent is a state of
        # the house, so it moves to a store of its own. Recorded only
        # once the automation is written, reloaded and verified — a row
        # saying the house is holding something, about an automation Core
        # never loaded, is the "the file was written"/"it exists"
        # confusion with a card on top of it.
        await asyncio.to_thread(intents.arm, row, applied)

    payload = {"proposal": row, "learned": fact,
               **await asyncio.to_thread(_proposals_payload)}
    if applied:
        payload["automation"] = applied["automation_id"]
        payload["entity_id"] = applied["entity_id"]
        # The one press in the panel that changes /config, so the one
        # press that owes a way back. Same contract as a finding's
        # ending: a token on the response, and the toast grows an Undo.
        payload["undo"] = undo_store.record(
            "automation", proposal=row, written=applied,
            fact=fact, fact_source="homeowner")
        await _announce_accepted(row, applied)
    return web.json_response(payload)


async def _wait_for_gone(entity_id: str) -> bool:
    """Whether this entity has left Core within the ceiling.

    `_wait_for_entity`'s mirror, and separate rather than a flag on it:
    "it turned up" and "it went away" are the two claims, they are read at
    opposite ends of a press, and one function answering both with a
    boolean argument is a call site nobody can read.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    deadline = time.monotonic() + ACCEPT_VERIFY_S
    while True:
        if not await ha_data.entity_exists(entity_id):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(ACCEPT_POLL_S)


async def h_intent_remove(request: web.Request) -> web.Response:
    """Take a one-off back out of `automations.yaml`.

    The only press that removes an automation, and the reason nothing
    removes one on its own: an automation that vanished from somebody's
    file while they were not looking is a file they cannot trust. So a
    fired intent sits on the tab saying it fired until this is pressed,
    and an intent that never fired is offered the same press with a
    different sentence.

    The same four claims the accept path makes, in reverse: the entry is
    spliced out, Home Assistant reloads, the entity is gone, and only
    then does the row leave the list. Any of them failing puts the file
    back and answers 409 with the sentence.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    ts = int(request.match_info["ts"])
    row = await asyncio.to_thread(intents.get, ts)
    if row is None:
        return web.json_response({"error": "that one-off is not on the list"},
                                 status=404)

    written = None
    if row.get("status") != "refused" and row.get("automation_id"):
        written = await asyncio.to_thread(
            automation_writer.remove, row["automation_id"])
        if not written.get("ok"):
            return web.json_response(
                {"error": str(written.get("error")
                              or "brAIn could not edit automations.yaml"),
                 **await asyncio.to_thread(_proposals_payload)}, status=409)
        failure = ""
        try:
            await ha_data.call_core_service("automation", "reload")
        except Exception as exc:  # noqa: BLE001
            failure = f"Home Assistant would not reload its automations: {exc}"
        if not failure and row.get("entity_id"):
            try:
                if not await _wait_for_gone(row["entity_id"]):
                    failure = (f"{row['entity_id']} is still in Home "
                               "Assistant after the reload, so the "
                               "automation was not really removed")
            except Exception as exc:  # noqa: BLE001
                failure = f"brAIn could not check whether it went: {exc}"
        if failure:
            reverted = await asyncio.to_thread(
                automation_writer.revert, written)
            try:
                await ha_data.call_core_service("automation", "reload")
            except Exception as exc:  # noqa: BLE001 — the file is back;
                # a second failed reload is a log line.
                log.warning("could not reload after putting it back: %s", exc)
            if not reverted.get("ok"):
                failure += (" — and putting automations.yaml back failed: "
                            f"{reverted.get('error')}")
            return web.json_response(
                {"error": failure,
                 **await asyncio.to_thread(_proposals_payload)}, status=409)

    dropped = await asyncio.to_thread(intents.drop, ts)
    payload = {"removed": bool(dropped),
               **await asyncio.to_thread(_proposals_payload)}
    if dropped:
        # The same toast-and-token contract every press that takes a row
        # away owes, and this one reaches /config as well.
        payload["undo"] = undo_store.record(
            "intent", intent=dropped, written=written)
    return web.json_response(payload)


async def _replay_config(session, config: dict, start: float, end: float,
                         tz) -> dict:
    """Replay one automation over recorded history. One implementation.

    Both doors read this — the Replay button and the habit miner offering
    a proposal — because "how often would this have fired" asked two ways
    is two answers waiting to disagree, exactly as `brain findings` goes
    through the API rather than the store files.

    A refusal comes back as a payload (`refused`, and the reason in
    words), never as an exception to the caller and never as an empty
    result: *"it would never have fired"* and *"brAIn cannot replay
    this"* are different answers, and only one of them is about the
    automation.
    """
    try:
        watched = sorted(shadow.entities_watched(config))
        shadow.check_replayable(config)
    except shadow.Refused as exc:
        return {"error": str(exc), "refused": True}
    if len(watched) > shadow.MAX_ENTITIES:
        return {"error": f"this reads {len(watched)} entities, more than a "
                         "replay can honestly rebuild", "refused": True}

    history = {}
    if watched:
        # shadow's own fetch, never ha_data.get_history: that one
        # downsamples into hourly buckets, which throws away the very
        # edges a replay counts.
        history = await shadow.fetch_history(session, watched, start, end)
    try:
        return await asyncio.to_thread(
            shadow.replay, config, history, start, end, tz)
    except shadow.Refused as exc:
        return {"error": str(exc), "refused": True}


async def h_replay(request: web.Request) -> web.Response:
    """What an automation would have done over a window of recorded history."""
    import aiohttp  # noqa: PLC0415 — the module has no other need of it

    body = await _json_body(request)
    config = body.get("config")
    if not isinstance(config, dict):
        return web.json_response({"error": "no automation to replay"},
                                 status=400)
    days = max(1, min(int(body.get("days") or REPLAY_DAYS),
                      shadow.MAX_WINDOW_DAYS))
    now = time.time()
    tz, _name = baselines.house_timezone()
    async with aiohttp.ClientSession() as session:
        result = await _replay_config(
            session, config, now - days * 86400, now, tz)
    return web.json_response(
        result, status=422 if result.get("refused") else 200)


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

    if entry["kind"] == "automation":
        # An accepted proposal is the only undo that reaches outside the
        # panel's own stores, so it reverses in the same order it was
        # made and in reverse: the file first, then the reload, then the
        # row. Putting the proposal back while the automation is still
        # running would offer somebody a change their house is already
        # making.
        import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

        written = entry.get("written") or {}
        reverted = await asyncio.to_thread(automation_writer.revert, written)
        reloaded = True
        domain, service = written.get("reload") or ("automation", "reload")
        try:
            await ha_data.call_core_service(domain, service)
        except Exception as exc:  # noqa: BLE001 — the file is back either
            # way, and saying which half failed is the point.
            reloaded = False
            log.warning("could not reload after undoing an accept: %s", exc)

        def put_back() -> tuple[bool, dict]:
            restored = proposals.reopen(entry["proposal"]) is not None
            if entry.get("fact"):
                _drop_from_inbox(
                    _inbox_id(entry["fact_source"], entry["fact"]))
            return restored, _proposals_payload()

        restored, payload = await asyncio.to_thread(put_back)
        payload["undone"] = bool(restored and reverted.get("ok") and reloaded)
        payload["reverted"] = bool(reverted.get("ok"))
        payload["reloaded"] = reloaded
        payload["restored_proposal"] = restored
        if not reverted.get("ok"):
            payload["error"] = reverted.get("error")
        elif not reloaded:
            payload["error"] = ("automations.yaml is back as it was, but "
                                "Home Assistant would not reload it — the "
                                "automation is still running until it does")
        elif not restored:
            payload["error"] = ("automations.yaml is back as it was, but "
                                "the proposal could not be put back on the "
                                "list")
        return web.json_response(payload)

    if entry["kind"] == "intent":
        # The mirror of an accept's undo: the file first, then the reload,
        # then the row. Putting the card back while the automation is
        # still gone would offer somebody a Remove for something that has
        # already been removed.
        import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

        written = entry.get("written") or {}
        reverted = {"ok": True}
        reloaded = True
        if written:
            reverted = await asyncio.to_thread(
                automation_writer.revert, written)
            try:
                await ha_data.call_core_service("automation", "reload")
            except Exception as exc:  # noqa: BLE001
                reloaded = False
                log.warning("could not reload after undoing a remove: %s", exc)
        restored = await asyncio.to_thread(intents.restore, entry["intent"])
        payload = await asyncio.to_thread(_proposals_payload)
        payload["undone"] = bool(restored and reverted.get("ok") and reloaded)
        payload["reverted"] = bool(reverted.get("ok"))
        payload["reloaded"] = reloaded
        if not reverted.get("ok"):
            payload["error"] = reverted.get("error")
        elif not reloaded:
            payload["error"] = ("automations.yaml is back as it was, but "
                                "Home Assistant would not reload it")
        elif not restored:
            payload["error"] = ("the automation is back, but the one-off "
                                "could not be put back on the list")
        return web.json_response(payload)

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
    # A finding is its own conversation. Landing it in whichever chat
    # happens to be open put "the garage lights" under a half-finished
    # question about the heating, and the reply answered both at once.
    try:
        await session.reset()
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
    """Sign out.

    `shared` is read off the body rather than assumed, and the dialog ticks
    it: leaving the shared copy makes this button a no-op, because
    `engine.get_auth` finds that file on the very next request and reports
    the panel authenticated again — but the file may equally have been
    published from the terminal, and it is the one other add-ons read. So
    the choice is the person's and the consequence of each is on screen.
    """
    body = {}
    if request.can_read_body:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            # A logout with no body is the old shape and still means logout;
            # it must not fail on the parse.
            body = {}
    engine.clear_auth(include_shared=bool(body.get("shared")))
    engine.SETUP_FLOW.cancel()
    AUTH_CHECK.update(state="unchecked", error="", checked_at=0)
    return web.json_response({"cleared": True})


async def h_auth(request: web.Request) -> web.Response:
    """The whole credential picture, for the Claude account section.

    Separate from /api/status because that is polled on a timer by every
    open panel and this is read when a dialog opens: three `os.path.exists`
    and a couple of small reads is nothing once, and something on a poll.
    """
    return web.json_response({
        **engine.auth_overview(),
        "auth_check": AUTH_CHECK,
        "recheck_seconds": AUTH_RECHECK_S,
    })


async def h_auth_share(request: web.Request) -> web.Response:
    """Publish this login to the file the other BRUH add-ons read."""
    result = await asyncio.to_thread(engine.share_auth)
    if not result["shared"]:
        raise web.HTTPConflict(text={
            "not_signed_in": "There is no credential to share — sign in first.",
            "cli_login_cannot_be_shared":
                "Claude Code's own login is a short-lived session token it "
                "refreshes for itself. The shared file has nowhere to record a "
                "refresh, so a copy would stop working within hours and every "
                "add-on reading it would fail with nothing to say why. Sign in "
                "here (or run `ha login` in the Terminal tab) to mint a "
                "long-lived token that can be shared.",
            "unwritable":
                "Could not write to /config/.brain/secrets — check the add-on "
                "log for the reason.",
        }.get(result["reason"], result["reason"]))
    return web.json_response(engine.auth_overview())


async def h_auth_unshare(request: web.Request) -> web.Response:
    removed = await asyncio.to_thread(engine.unshare_auth)
    return web.json_response({**engine.auth_overview(), "removed": removed})


async def h_auth_recheck(request: web.Request) -> web.Response:
    """Verify the stored credential now, rather than at the next 6h ageing.

    The verdict is otherwise only ever re-earned lazily off /api/status, on
    `AUTH_RECHECK_S` — right for an unattended poll and useless to somebody
    who has just fixed their login in the terminal and is looking at a chip
    that still says it failed. This is the one press that costs a real
    `claude -p` turn on purpose, and it is announced because a person asked.
    """
    started = start_auth_check()
    return web.json_response({"started": started, "auth_check": AUTH_CHECK})


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

def _chat_registry() -> "chat_session.SessionRegistry":
    """The registry, told which model a session spawned now should run.

    Same refresh as ``_chat``'s and for the same reason: a conversation
    opened from the rail must run the model the chat is set to, not the one
    the environment named at boot.
    """
    registry = chat_session.registry()
    registry.model = eff_chat_model()
    return registry


def _chat() -> "chat_session.ChatSession":
    """The attached session — the conversation the view is on.

    There are several of them now (see chat_session.SessionRegistry), and
    every route that acts on "the chat" acts on this one: send, stop, the
    model picker, the handoff, the stream. Switching is what changes which
    session that is, and it stops nothing.
    """
    session = _chat_registry().attached()
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
        registry = chat_session.registry()
        if registry.attached() is not session:
            # Attached somewhere else between picking the session and
            # subscribing to it. The `switched` event that would have said
            # so went to the queue this stream does not hold, so it is
            # re-sent here rather than leaving a viewer watching a
            # conversation nobody is in — a narrow race, and the only one
            # whose failure is permanent.
            await send({"type": "switched",
                        "session_id": registry.attached().session_id or ""})
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
    """Start a conversation. Whatever else is open carries on.

    On a chat nobody has typed into this reuses the session that is there
    rather than spending a slot on a second empty process — see
    ``SessionRegistry.new``.
    """
    try:
        return web.json_response(await _chat_registry().new())
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=_refusal(exc))


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
    registry = _chat_registry()
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
    rows = rows[:30]
    # Which of these the panel is holding a process for, joined here and
    # once: the listing is Claude Code's store and the marks are ours, and
    # two surfaces each doing their own join is two chances to disagree
    # about whether a row is answering.
    marks = {row["session_id"]: row for row in registry.live()}
    for row in rows:
        mark = marks.get(row["id"])
        row["live"] = bool(mark and mark["live"])
        row["busy"] = bool(mark and mark["busy"])
        row["needs_ok"] = bool(mark and mark["needs_ok"])
    return web.json_response({
        "conversations": rows,
        "current": session.session_id,
        "sources": await asyncio.to_thread(_conversation_source_counts),
        "sessions": registry.live(),
        "max_sessions": chat_session.max_sessions(),
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
    session = _chat()
    if session.state == "busy":
        # Refused before anything is saved: a choice that half-applies —
        # stored but not running — reads as a picker that lies. The one
        # refusal switching conversations did not take away, and it says
        # which conversation it is about now that there can be several.
        raise web.HTTPConflict(
            reason="this conversation is still being answered — stop it, or "
                   "switch to another chat and pick the model there")
    try:
        settings = settings_store.save({"chat_model": body.get("model")})
    except ValueError:
        # The one thing save() can reject here, said in fixed words rather
        # than echoing exception text into a response (CodeQL reads that as
        # information exposure, and the message is knowable anyway).
        raise web.HTTPBadRequest(text="chat_model must be a string or null")
    try:
        out = await session.set_model(eff_chat_model())
    except RuntimeError as exc:
        # Only raised when a turn started between the busy check above and
        # here — the session's own sentence, which says the same thing.
        raise web.HTTPConflict(reason=_refusal(exc))
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
    toast's Undo can put back exactly what was taken. A conversation that
    something is holding open is refused — not only the attached one:
    deleting the ground a live session stands on either kills it or quietly
    forks it, and now that several may be live at once "the one on screen"
    is no longer the same question as "the ones in use". The refusal names
    the close route, because a refusal with no way to satisfy it is a dead
    end.
    """
    registry = _chat_registry()
    session_id = request.match_info["id"]
    if registry.get(session_id) is not None:
        raise web.HTTPConflict(
            reason="that conversation still has a live session — close it first")
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
    and a conversation with a live session is skipped rather than failing
    the batch — a select-all that refuses outright because one open chat
    was in it teaches people to deselect one row by trial and error. What
    was skipped is reported, so the toast can say it.
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
    registry = _chat_registry()
    deleted, entries, skipped = [], [], []
    for session_id in dict.fromkeys(ids):     # de-duped, order kept
        if registry.get(session_id) is not None:
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
    """Open a conversation: attach to it if it is live, resume it if not.

    The route name and the body's shape are unchanged, and so is what
    ``resumed: false`` means — Claude Code no longer holds this
    conversation and a fresh session opened instead. What changed is that
    this no longer stops anything: a conversation left mid-answer goes on
    answering in its own session, and the only 409 left here is the cap
    (every live chat busy, nothing idle to evict), which says so in those
    words rather than blaming the answer you can still see.
    """
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    session_id = str(body.get("session_id") or "")
    registry = _chat_registry()
    replay = []
    if registry.get(session_id) is None:
        # Only for a conversation we are not already holding: reading a
        # transcript off disk to replay over a session that has the live
        # one in memory is a slower way to show the same thing, minus the
        # notices that explain how it got here.
        replay = await asyncio.to_thread(
            conversations.transcript, chat_session.WORK_DIR, session_id)
    try:
        return web.json_response(await registry.open(session_id, replay))
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=str(exc))
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=_refusal(exc))


async def h_chat_session_close(request: web.Request) -> web.Response:
    """Stop one conversation's process, keeping the conversation.

    The only thing this takes away is a live session; Claude Code still
    holds the conversation and the rail still lists it. It exists because
    deleting a conversation is refused while something is holding it open,
    and a refusal with no way to satisfy it is a dead end.
    """
    closed = await _chat_registry().close(request.match_info["id"])
    return web.json_response({"ok": True, "closed": closed})


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
            "default_model_label": chat_session.pretty_model(default),
            # Which conversations are live, so the rail's marks are right
            # on the first paint rather than on the first thing that
            # happens to move.
            "sessions": chat_session.registry().live(),
            "max_sessions": chat_session.max_sessions()}


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
    app.router.add_get("/api/appliances", h_appliances)
    app.router.add_get("/api/weekly", h_weekly)
    app.router.add_post("/api/weekly/run", h_weekly_run)
    app.router.add_get("/api/activity", h_activity)
    app.router.add_get("/api/activity/entity/{entity_id}", h_activity_entity)
    app.router.add_post("/api/finding/{ts}/fix", h_finding_fix)
    app.router.add_post("/api/finding/{ts}/snooze", h_finding_snooze)
    app.router.add_post("/api/finding/{ts}/discuss", h_finding_discuss)
    # Before the {ts} pattern, which would otherwise swallow it.
    app.router.add_get("/api/proposals", h_proposals)
    app.router.add_get("/api/playbook/{ts}/rehearsal", h_playbook_rehearsal)
    app.router.add_post("/api/proposal/{ts}/trial", h_proposal_trial)
    app.router.add_post("/api/intent/{ts}/remove", h_intent_remove)
    app.router.add_get("/api/scenes/areas", h_scene_areas)
    app.router.add_post("/api/scenes/design", h_scene_design)
    app.router.add_post("/api/proposal/{ts}/{verb}", h_proposal_decide)
    app.router.add_post("/api/replay", h_replay)
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
    app.router.add_get("/api/auth", h_auth)
    app.router.add_post("/api/auth/token", h_auth_token)
    app.router.add_post("/api/auth/logout", h_auth_logout)
    app.router.add_post("/api/auth/share", h_auth_share)
    app.router.add_post("/api/auth/unshare", h_auth_unshare)
    app.router.add_post("/api/auth/recheck", h_auth_recheck)
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
    app.router.add_post("/api/chat/session/{id}/close", h_chat_session_close)

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
        app["evening"] = asyncio.create_task(_evening_loop())
        app["healing"] = asyncio.create_task(_heal_loop())
        app["weekly"] = asyncio.create_task(_weekly_loop())
        app["requests"] = asyncio.create_task(_requests_loop())
        if addon_options.available():
            app["options"] = asyncio.create_task(_options_poller())
        if engine.get_auth():
            start_auth_check()

    async def on_cleanup(app: web.Application) -> None:
        # The chat session is a child process of ours; leaving it running
        # after the panel goes down orphans a Claude that nothing will ever
        # read from again.
        await chat_session.registry().stop_all()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    web.run_app(make_app(), host=BIND_HOST, port=BIND_PORT, print=None,
                access_log_class=QuietAccessLogger)
