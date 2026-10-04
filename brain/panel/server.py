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
GET  /api/auth               — every credential store, which one is in use,
                               and the last verdict (the ⚙ Claude account
                               section; not polled — read when it opens)
POST /api/auth/token         — save a pasted token / API key
POST /api/auth/logout        — forget the stored credential {shared: bool}
POST /api/auth/share         — publish it to /config for the other add-ons
POST /api/auth/unshare       — withdraw that copy
POST /api/auth/recheck       — verify the credential now, not at the next ageing
POST /api/auth/setup/start   — begin a guided sign-in {mode: account|token}
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
POST /api/finding/{ts}/fix   — press Fix it: a READ-ONLY run works out what
                               it would change, and the steps come back on the
                               card. It changes nothing (see fixer.PLAN_SYSTEM)
POST /api/finding/{ts}/apply — yes, do exactly that: the one tool-enabled
                               Claude run, carrying the plan that was shown
POST /api/finding/{ts}/cancel — no: back to open, the plan kept on the row so
                               it can be read again without paying for it
POST /api/finding/{ts}/unfix — put back what the fix changed: every file it
                               journalled, reloaded; the service calls it made
                               are LISTED and never reversed (see unfix.py)
POST /api/finding/{ts}/wrong  — you've got this wrong / not a problem here,
                                optionally {note}: WHY, in your words, which
                                is handed to the analyst and the consolidator
                                rather than acted on literally
                                (/ignore is the old name for the same thing)
POST /api/finding/{ts}/todo  — it's real and you'll do it: off this list,
                                onto the to-do list, key settled so nothing
                                raises it again while it waits
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

GET  /api/todo               — the work you have accepted, open and done
POST /api/todo               — add one by hand
POST /api/todo/{id}/done     — done: the memory line the move did not write
POST /api/todo/{id}/reopen   — back on the list; the fact stays written
DELETE /api/todo/{id}        — off the list undone, and the problem back in
                                play if it came from a finding
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
GET  /api/knowledge          — the memory queue + hypotheses + shared memory.md
GET  /api/knowledge/house    — every measurement's own progress, in one payload
GET  /api/knowledge/house/{name}  — one measurement in full (rhythm, baselines,
                               thermal, closures, appliances, habits, energy)
POST /api/knowledge/fact     — teach a fact {text}; Claude merges it into memory.md
                               (its only home — never duplicated into the ledger)
PUT  /api/memory             — save a manual edit of the memory file {text}

Runs on 0.0.0.0:8099. The HA Supervisor proxies the ingress URL into
/api/hassio_ingress/<token>/...; we therefore use only relative links in the
HTML and let aiohttp serve at /. Generation jobs run through a single-worker
queue, and every Claude run the server starts — that worker's and every
other — takes a seat on the bounded, prioritised run queue (`run_queue`):
safety, then a person's press, then scheduled work, with one seat always
kept free of scheduled work. That queue, not the worker, is what keeps
the subscription's rate limit and the box's memory safe.

Dashboard cards are served by HA itself via a /local mirror: insight HTML is
copied to /config/www/brain/ (created on first use of the ▦ dialog,
kept in sync on save/delete), so Webpage cards are same-origin and work on
HTTP and HTTPS/Nabu Casa dashboards alike. File names embed a per-install
random token to keep the unauthenticated /local URLs unguessable.
"""
from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import contextlib
import fcntl
import functools
import hashlib
import json
import logging
import os
import platform
import re
import secrets
import shutil
import html as html_lib
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
import capture
import card_tags
import cases
from checks._util import House
import chat_session
import closures
import checks
import cli_commands
import conditions
import conversations
import curiosity
import doctor
import energy
import engine
import facts_store
import episodes
import esphome
import eventbus
import feedback_store
import finding_requests
import findings_store
import fixer
import healing
import health
import house
import habit_lookup
import hypotheses
import ideas
import authoring
import intents
import journal
import knowledge_store
import manual_ledger
import milestones
import model_plan
import music_assistant
import notify_router
import override_ledger
import onboarding
import outcomes
import ownership
import playbooks
import prompt_store
import proposals
import rehearsal
import reports
import resident
import rhythm
import routines
import run_queue
import run_sources
import scenes
import schedule_store
import settings_store
import shadow
import shadow_findings
import signals
import terminal_proxy
import thermal
import todo_store
import triage
import trials
import undo_store
import unfix
import usage_store
import user_categories
import weekly
# Home Assistant's own maintainer: names and rooms, the house book, the
# overnight health check and the upgrade advisor.
import house_book
import sre
import tidy
import upgrades
# Understanding the house: what each entity is, what it is doing now, and
# what is coming up.
import occasions
import situation
import world_model
# `_CARD_CONTRACT` and `_previous_block` are reached into deliberately, by
# the prompt preview, which reports the size of every block a run is sent:
# a second copy of the contract or of the previous-run renderer here would
# make the preview a picture of something other than what is sent. Same
# statement as the public names rather than a bare `import categories`
# beside it — one module imported two ways is a CodeQL alert and, more to
# the point, two spellings of one dependency.
from categories import (ANALYST_SYSTEM, CARD_SCHEMA, CATEGORIES, SYSTEM_PROMPT,
                        _CARD_CONTRACT, _previous_block,
                        build_orientation_prompt, build_prompt,
                        document_lines, get_category, house_block,
                        inject_styles, memory_excerpt, stores_for)

HERE = Path(__file__).resolve().parent
INSIGHTS_DIR = Path(os.environ.get("BRAIN_DIR", "/data/insights"))
ADDON_VERSION = os.environ.get("ADDON_VERSION", "dev")
REFRESH_HOURS = float(os.environ.get("BRAIN_REFRESH_HOURS", "24") or 0)
HISTORY_DAYS = int(os.environ.get("BRAIN_HISTORY_DAYS", "7") or 7)
# Dated per-run copies of each category insight (0 for either disables history)
HISTORY_KEEP_RUNS = int(os.environ.get("BRAIN_HISTORY_KEEP_RUNS", "40") or 40)
HISTORY_KEEP_DAYS = int(os.environ.get("BRAIN_HISTORY_KEEP_DAYS", "30") or 30)


def insights_enabled() -> bool:
    """The `enable_insights` option, as run.sh exports it.

    Read at call time the way `terminal_proxy._enabled` reads its twin,
    so a test can drive the scheduler either way without reloading the
    module. run.sh exported this for two releases and nothing read it:
    the option switched off a face in the docs and nowhere else.
    """
    return os.environ.get("BRAIN_ENABLE_INSIGHTS", "true").lower() != "false"
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

# The read-only look that now happens first. Cheaper than the fix in both
# budgets because it reads the house and writes a paragraph, where the fix
# has to make the change and then prove it took — and a person is waiting
# in front of this one, which the fix cannot say.
PLAN_MAX_TURNS = int(os.environ.get("BRAIN_PLAN_MAX_TURNS",
                                    str(fixer.DEFAULT_PLAN_MAX_TURNS)))
PLAN_TIMEOUT_S = int(os.environ.get("BRAIN_PLAN_TIMEOUT", "300"))
PLAN_JOB_PREFIX = "plan-"

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


def _answer(result: dict) -> dict | None:
    """The object a run answered with: the CLI's validated one first.

    A run that carried a `--json-schema` comes back with `data` — the
    object the CLI checked against the schema before it was sent — and
    that wins over anything parsed out of the text, because a reply the
    CLI validated cannot be a fenced block with a comma missing. A run
    on a CLI too old for the flag has no `data`, and the text is what it
    always was.
    """
    data = result.get("data")
    if isinstance(data, dict):
        return data
    return engine.extract_json(result.get("text") or result.get("raw") or "")


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
# How many entities one card may keep live. A visualization that wants a
# dozen is a dashboard, which the contract already forbids; the cap is
# here as well because the contract is advice and this is the thing that
# decides what the panel will fetch on a timer.
MAX_LIVE_ENTITIES = 12
# How often a card on screen asks for them. Slower than the house changes
# and far slower than a person can read: this is a card being current, not
# a live feed, and every visible card pays for it on every tick.
LIVE_POLL_S = 15
MAX_CUSTOM_KEPT = 12
# Characters per token, for the ONE number that has to exist before the run
# does: what a prompt is about to cost. Approximate by nature — the real
# count comes back in the result envelope and is what everything downstream
# reports — so anywhere this is shown it is prefixed with "~".
CHARS_PER_TOKEN = 4
# The runaway guard on a searching run — not a budget. The timeout is what
# bounds a card; this only ends a run that has stopped converging, and a run
# that trips it is landed (engine._run_cli) rather than thrown away, so the
# number is large and nobody is asked about it.
ANALYST_MAX_TURNS = 40

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


def _rebind_queue() -> None:
    """Give the running loop its own work queue, carrying anything waiting.

    An `asyncio.Queue` binds to the loop that first awaits it, and this
    one is a module global — so a process that builds a second app in a
    second loop hands its worker a queue it can never read from. Called
    once from `on_startup`, where the loop is the app's own.

    Whatever was already queued is carried across rather than dropped:
    in the add-on there is never anything (nothing enqueues before the
    app is up), and losing a job to a tidy-up would be the wrong way for
    a housekeeping call to be wrong.
    """
    global QUEUE
    waiting = []
    while True:
        try:
            waiting.append(QUEUE.get_nowait())
        except asyncio.QueueEmpty:
            break
    QUEUE = asyncio.Queue()
    for job_id in waiting:
        QUEUE.put_nowait(job_id)


def _rebind_resident_queue() -> None:
    """`_rebind_queue`'s rule, one queue over.

    An `asyncio.Queue` belongs to whichever loop first touches it, and this
    one is a module global that a producer may have filled before any loop
    ran. In the add-on that is one loop and the distinction never arises;
    anywhere that builds a second app (a test, the demo panel) the first
    `get_nowait` raises "bound to a different event loop" into a task
    nobody awaits. Rebinding costs one object and keeps what was queued.
    """
    global RESIDENT_QUEUE
    waiting = []
    while True:
        try:
            waiting.append(RESIDENT_QUEUE.get_nowait())
        except asyncio.QueueEmpty:
            break
    RESIDENT_QUEUE = asyncio.Queue()
    for signal in waiting:
        RESIDENT_QUEUE.put_nowait(signal)


# The house checks (panel/checks): whether a pass is in flight, and the
# summary of the last one — which is what /api/checks, `brain check list`
# and the diagnostics bundle read.
CHECKS_STATE: dict = {"running": False, "last": None}
# Whether a triage drain is in flight. A dict for `CHECKS_STATE`'s reason
# rather than a module-level flag rebound through `global`: the two are
# the same guard three lines apart in `run_checks`, and one of them
# spelled differently is the drift a second idiom always produces.
# `day`/`runs` are the per-day runaway guard (`triage.MAX_PER_DAY`):
# counted per local day and reset with it. In memory on purpose — it is a
# guard against a loop and not a budget, and a restart that forgets it
# costs at most one more day's worth of runs, where a guard that survived
# a restart would need a store nothing else reads.
TRIAGE_STATE: dict = {"running": False, "day": "", "runs": 0}


def _triage_runs_today(now: float) -> int:
    """How many triage runs this local day has spent, rolling the day."""
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    if TRIAGE_STATE.get("day") != day:
        TRIAGE_STATE["day"] = day
        TRIAGE_STATE["runs"] = 0
    return int(TRIAGE_STATE.get("runs") or 0)


# ---------------------------------------------------------------------------
# The Resident — the attention loop
# ---------------------------------------------------------------------------
#
# Everything else scheduled in this file is a rule that decides what a
# household is told. This is the inversion the 2.0 plan is written for: the
# rules become senses, a cheap look decides what is worth anybody's
# attention, and only what survives that buys a stronger run. Three pieces
# live here and none of them judges anything — `signals` shapes what
# happened, `resident` holds the prompts and the budget, `cases` is what a
# person reads.
#
# The queue is the HAND-OFF and the pending list is the batch being built.
# `eventbus` calls `_resident_offer` from inside a socket pump, where
# anything that blocks blocks the read, so the producer side is one
# `put_nowait` and nothing else; the cap, the dedupe and the ranking all
# happen on the tick, off that path.
RESIDENT_STATE: dict = {
    "running": False,        # a look or an investigation is in flight
    "last_look_at": 0.0,
    "last_investigation_at": 0.0,
    "last_sweep_at": 0.0,      # when the findings queue was last read
    "queue_len": 0,          # signals waiting to be looked at
    "waiting": 0,            # what did not fit the last batch
    "hot_pending": 0,        # …of which are hot, and so are not left waiting
    "investigations_waiting": 0,
    "dropped": 0,            # signals the cap took, counted rather than quiet
    "duplicates": 0,         # cases the store already held
    "last_error": "",
}
# What producers hand signals to. A module global bound to whichever loop
# touches it first, so it is rebound at startup beside `QUEUE` for the same
# reason: a second app (a test, the demo panel) would otherwise get
# "bound to a different event loop" out of a task nobody awaits.
RESIDENT_QUEUE: asyncio.Queue = asyncio.Queue()
# The batch being built. Separate from the queue because the cap is applied
# by salience, which needs the whole set in one place — and because the
# queue's own `get()` would block the tick on an empty house.
RESIDENT_PENDING: list[dict] = []
# The finding ids inside the batch a look is judging right now. A producer
# that files while a look is in flight would otherwise offer a row that is
# already being judged — harmless (`record_triage` only touches a row still
# in `triaging`) and still a wasted line of a batch.
RESIDENT_INFLIGHT: set[int] = set()
# Investigations a look decided on that the ledger could not pay for yet,
# with the look's reason. Parked here rather than put back on the pending
# list: back there they were re-judged by a fresh paid look every minute
# while hot, with no memory of the verdict, and a hot one could spend the
# day's whole look allowance asking the same question while Haiku went on
# answering it the same way. The next allowance drains this with no new
# look; capped, oldest dropped and counted.
RESIDENT_PARKED: list[tuple[dict, str, int]] = []
RESIDENT_PARKED_MAX = 50
# The budget, per local day, per tier. On disk: a restart is the first thing
# anybody does after changing an option, and an in-memory count makes
# "twice a day" mean "twice per restart".
#
# The day is the HOUSE's: the reader is handed over rather than a zone,
# because this is built at import and a zone read then is UTC for the life
# of the process — the midnight-UTC day the class exists not to keep.
LEDGER = resident.Ledger(tz=lambda: baselines.house_timezone()[0])


def _resident_tier(job: str, thinking: str) -> str:
    """The tier a Resident run of `job` is about to be charged to.

    The plan as the dial and a typed model actually move it, never the
    table's tier: `resident.tier_for` answers what a job is PLANNED at,
    and a ledger asked about that let `generous` run investigations on
    Opus against the Sonnet allowance, and a typed Opus run first looks
    on Opus against nothing at all.
    """
    return model_plan.run_tier(job, thinking, eff_model())


def _ran_tier(result: dict, job: str) -> str:
    """The tier a finished run RAN on, read off the model the engine sent."""
    sent = (result.get("meta") or {}).get("model") if isinstance(result, dict) else ""
    return model_plan.tier_of(sent or "") or resident.tier_for(job)
# The subscription. Built in `on_startup`, because it needs a loop.
EVENT_BUS: eventbus.EventBus | None = None

# How often a look happens with nothing hot in the queue. Ten minutes is
# the plan's suggested floor and the one number worth measuring on real
# houses before it becomes a default, so it is an env var rather than an
# option: nothing on the Configuration tab should ask somebody to choose it.
RESIDENT_LOOK_S = max(60, int(os.environ.get("BRAIN_RESIDENT_LOOK_S", "600")))
# …and the floor a HOT signal may cut it to. Hot means "look now rather
# than on the timer", which is the one thing a signal is allowed to cause
# by itself — so a house producing hot signals in a burst still looks once
# a minute rather than once per leak sensor.
MIN_LOOK_SPACING_S = 60
# How often the loop wakes to ask. Short, because the whole point of a hot
# signal is that it does not wait out the interval; a tick with an empty
# queue is one `qsize()` and a comparison.
RESIDENT_TICK_S = 5
# …and how often that tick READS THE STORE. The queue of rows nothing has
# looked at, and the sweep for ones left past the hour, are two full loads
# of the findings file, and doing them twelve times a minute on a Pi with
# an SD card under it is the cost this loop's short tick was not meant to
# buy. A minute is far inside `triage.STALE_S` and far inside the look's
# own interval; what the five-second tick is FOR is a hot signal off the
# event bus, and that arrives on the queue rather than through a file.
RESIDENT_SWEEP_S = 60
# The first tick waits for the panel to settle, `_checks_loop`'s rule: the
# startup sequence is already racing the recorder, and the queue is empty
# until something has produced a signal anyway.
RESIDENT_FIRST_DELAY_S = 90
# How many signals may wait. Past it the cap drops the least salient
# non-hot one — the oldest of those where several tie — and counts it,
# because a queue that silently discards is one nobody can trust.
RESIDENT_QUEUE_MAX = 500
# The job a case the first investigation was unsure about is re-run under.
# A JOB name and never a tier, because `model_plan` owns which tier a job
# costs and `resident.tier_for` is how the budget asks — a second answer to
# that written here is the release where the attention loop quietly reaches
# the top tier.
ESCALATE_JOB = "synthesis"
# How many investigations one look may start. Each is a Sonnet run with
# tools, so this is the runaway guard and the ledger is the budget; the
# surplus stays queued and says so rather than being dropped.
MAX_INVESTIGATIONS_PER_LOOK = 2
# How long a signal may wait in the pending list before it is dropped as a
# fact about a house that has moved on. A day: the look runs every ten
# minutes, so anything still here is something a gate held, and a week-old
# door opening is not evidence about this afternoon.
RESIDENT_SIGNAL_TTL_S = 86400
# Safety sensors the bus has seen TRIP, and when. The device class lives on
# the event's own attributes and a signal deliberately carries neither a
# class nor a verdict, so this is where the one fact the `act` verdict needs
# is kept — recorded at the moment the bus admitted the event, never
# re-fetched, because a fetch inside the attention loop is the thing this
# whole design is trying to stop doing. Bounded and pruned: it is an index
# of what is tripped now, not a history.
SAFETY_SUBJECTS: dict[str, float] = {}
SAFETY_SUBJECT_TTL_S = 6 * 3600
# The producer every safety case files under, whoever filed it — the lane
# or a Resident `act`. Its own source rather than `resident` so the
# notifier can give it `now` (`notify_router.PRODUCER_URGENCY`) and so
# "Stop raising these" can be refused for it by name: a mute on the rule
# that reports leaks is not a thing this panel offers.
SAFETY_SOURCE = "safety"
MAX_SAFETY_SUBJECTS = 200


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
# Problem reports (panel/reports.py) are written off whichever thread noticed
# the problem: `journal.record` is synchronous and is called from the event
# loop as well as from request threads, and a report fetches the add-on log
# with a five-second budget. One worker keeps the files in order, and the
# diagnostics a report abridges are computed on that thread, never on the
# loop. `file_incident` never raises, so a fire-and-forget future is safe.
_REPORT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="brain-reports")


def _report_async(fn, *args, **kwargs) -> None:
    """Run one `reports.*` producer on the reports thread."""
    kwargs.setdefault("diagnostics", _diagnostics_payload)
    try:
        _REPORT_EXECUTOR.submit(fn, *args, **kwargs)
    except RuntimeError:
        # The interpreter is shutting down; a report about that is one
        # nobody could read.
        pass


def _journal_report_listener(row: dict) -> None:
    """Every failed run of any kind files a problem report — hooked on the
    journal rather than at each caller, so a new run path is covered by
    having recorded itself."""
    if isinstance(row, dict) and row.get("outcome") in reports.FAILURE_OUTCOMES:
        _report_async(reports.file_run_failure, row)


def _journal_usage_listener(row: dict) -> None:
    """A finished run tells the usage tracker to ask again.

    Hooked on the journal for the same reason the report writer is: every
    Claude run of every kind already records itself here, so voice, the
    chat, a card, a fix, study and the consolidator are covered by having
    done so rather than by six callers remembering to.

    The account's figure moves when a run spends tokens and at no other
    time, so this is the moment one request is worth making — and it is
    also the only moment the credential is certainly usable, because the
    CLI mints the next access token from the refresh token as part of a
    run and nothing else on the box can. A checks pass or a baseline build
    with no model behind it is not a nudge (`journal.is_claude_run`), and
    the tracker spaces the requests out itself: this says what happened,
    not how often to ask.

    Synchronous on purpose — it is one `open` and a close, where the
    report writer's five-second log fetch is what needed a thread.
    """
    if journal.is_claude_run(row):
        usage_store.nudge()


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


ACTIVE_STATES = ("queued", "collecting", "generating", "parsing", "planning",
                 "fixing")


# A job that has ENDED, as opposed to one that is merely not in
# `ACTIVE_STATES` — "searching" is neither, and a run in flight must never
# be prunable because of a word the list has not been told about. What is
# swept is what said it was finished.
FINISHED_STATES = ("done", "error")

# The ledger is unbounded by construction: `JOBS[id]` is written for every
# card, every `fix:{ts}`, every `plan:{ts}`, every milestone and every deep
# check, and only a card's own id is ever reused. A card job is keyed on the
# card, so there are as many of those as there are cards; a fix or a plan is
# keyed on a finding's TIMESTAMP, so a house that settles a few findings a
# day grows this dict for ever and the only thing that empties it is a
# restart. Two bounds, because they answer different failures: the age is
# what keeps a long-running panel's ledger to the jobs somebody might still
# be looking at, and the cap is what stops a burst outrunning the age.
JOB_TTL_S = float(os.environ.get("BRAIN_JOB_TTL_S", 6 * 3600))
MAX_JOBS = int(os.environ.get("BRAIN_MAX_JOBS", 200))


def _job_active(job_id: str) -> bool:
    return JOBS.get(job_id, {}).get("state") in ACTIVE_STATES


def _prune_jobs(now: float | None = None) -> int:
    """Forget finished jobs. Returns how many were dropped.

    **A running job is never taken**, whatever the cap says: the record is
    how `/api/status` reports a spinner and how the worker finds its own
    `kind`, so evicting one live would be a card that generates into
    nothing. The cap therefore bounds what has FINISHED, and a panel with
    200 jobs in flight is a panel with a different problem.

    Oldest first, by the `updated_at` `_set_job` already stamps, so what
    goes is what nobody has looked at for longest.
    """
    now = time.time() if now is None else now
    finished = sorted(
        (float(job.get("updated_at") or 0), job_id)
        for job_id, job in JOBS.items()
        if job.get("state") in FINISHED_STATES)
    drop = [job_id for stamp, job_id in finished if now - stamp >= JOB_TTL_S]
    over = len(JOBS) - len(drop) - MAX_JOBS
    if over > 0:
        drop += [job_id for _stamp, job_id in finished
                 if job_id not in drop][:over]
    for job_id in drop:
        JOBS.pop(job_id, None)
    return len(drop)


def _set_job(insight_id: str, **fields) -> None:
    JOBS.setdefault(insight_id, {})[
        "updated_at"
    ] = time.time()
    JOBS[insight_id].update(fields)
    # Swept where a job ENDS rather than on a timer, because that is the one
    # moment the dict is known to have grown something prunable — and the
    # entry just written is the freshest thing in it, so neither bound can
    # take the answer somebody is about to read.
    if fields.get("state") in FINISHED_STATES:
        _prune_jobs()


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
            continue
        # An asked card has history and refinements now, and a trimmed
        # card's leftovers are data about a card nothing can open.
        _unmirror_card(old.stem)
        shutil.rmtree(_history_dir(old.stem), ignore_errors=True)
        feedback_store.clear(old.stem)
    _write_history_copy(insight)


def _write_history_copy(insight: dict) -> None:
    """Dated copy under history/<id>/<stamp>.json so past runs stay browsable.

    Asked cards keep history too: once a card can be refined, the version
    it replaced is the one thing somebody may want back. load_insights()
    never sees the history/ subdir (its glob is non-recursive). Setting
    either keep option to 0 disables history entirely.
    """
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


async def _submit_memory(fact: str, source: str = "insights", **about) -> None:
    """Queue a fact off the loop. ``about`` is `_queue_memory_fact`'s
    keywords — the subject a writer knows, the run that taught it."""
    await asyncio.to_thread(
        lambda: _queue_memory_fact(fact, source, **about))


# What a run is told the house is like, and how much of the document that
# costs. Until 2.2 every reader took `memory_excerpt` — the top 2 KB of
# the document, whatever the run was about — and the card bundle took the
# WHOLE document, which on a house with a real memory sent thirty
# kilobytes of standing facts to a run about one room. The facts store
# is what makes a smaller answer honest: the core facts (the house, the
# people) plus the facts about the entities and areas THIS run is
# reading, with the document's head behind them for the nicknames the
# consolidator keeps there. A fresh install has no facts, and falls back
# to exactly the excerpt it always got.
MEMORY_HEAD_CHARS = 800


def _memory_block(*, entities=(), areas=(), domains=(), query: str = "",
                  head_chars: int = MEMORY_HEAD_CHARS) -> str:
    """The retrieval block for these subjects, over the document's head.

    The entities' own rooms are added here, once, for every caller: a
    fact about a room is filed `area:<id>`, and a run about the lounge
    thermometer that was never handed the lounge never saw it.
    """
    facts = ""
    areas = list(areas or ()) + [a for a in _areas_of(entities)
                                 if a not in (areas or ())]
    try:
        facts = facts_store.retrieval_block(
            entities=entities, areas=areas, domains=domains, query=query)
    except Exception as exc:  # noqa: BLE001 — a store that will not read
        log.debug("facts retrieval failed: %s", exc)   # costs the excerpt
    document = _read_shared_memory()
    if not facts:
        return memory_excerpt(document)
    head = memory_excerpt(document, limit=head_chars)
    if head:
        # One header. The excerpt's own is the same sentence the block
        # opens with, so the document's lines ride under the block's.
        head = head.split("\n", 1)[1] if "\n" in head else ""
    return facts + ("\n" + head if head else "")


# ---------------------------------------------------------------------------
# Generation worker
# ---------------------------------------------------------------------------

def _tok(n: int) -> str:
    """A token count as a person would say it: 41231 -> "41.2k"."""
    return f"{n / 1000:.1f}k" if n >= 1000 else str(int(n))


# The engine's three runners. A run made through `_claude` with one of these
# is told whether a person asked for it, which is the one thing that lets a
# typed model reach a job a timer may not run on it (`model_plan`).
def _engine_runners() -> tuple:
    return (engine.run_claude, engine.run_analyst, engine.run_agent)


async def _claude(fn, *args, priority: int = run_queue.SCHEDULED, **kwargs):
    """Run one engine call on the Claude run queue, in its turn.

    Every `engine.run_*` the server makes goes through here rather than
    `asyncio.to_thread`: the default thread pool is where every store read
    runs, and minutes-long Claude processes sharing it with them — fourteen
    call sites, no limit and no order — is what let a Done pressed in Home
    Assistant wait behind two investigations and a Reply. See `run_queue`.
    `priority` is SAFETY, PRESS or SCHEDULED; a press is also `pressed`
    to the engine.
    """
    if fn in _engine_runners() and "pressed" not in kwargs:
        kwargs["pressed"] = priority == run_queue.PRESS
    return await run_queue.run(fn, *args, priority=priority, **kwargs)


def _job_priority(job_id: str) -> int:
    """A queued job's priority: the scheduler's own runs say why they are
    here (`because`), and everything else got here because somebody
    pressed something — `_because_of`'s two kinds."""
    job = JOBS.get(job_id) or {}
    if job.get("kind") in ("fix", "plan", "doctor", "rehearse", "sweep"):
        return run_queue.PRESS
    return run_queue.SCHEDULED if str(job.get("because") or "").strip() \
        else run_queue.PRESS


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


def _clean_entity_ids(value, max_items: int) -> list[str]:
    """A model-returned list of entity ids: real ids only, deduped, capped.

    `ha_data.is_entity_id` is the authority rather than a pattern written
    again here — the same reason `history_params` drops an id that is not
    one instead of escaping it. An id that is not an id names nothing, so
    keeping it would only cost a lookup on a made-up string.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if ha_data.is_entity_id(item) and item not in out:
            out.append(item)
        if len(out) >= max_items:
            break
    return out


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

    A third source sits under both: what somebody chose in onboarding's
    first step. `addon_options.write` knows only the six generation
    options, so that choice cannot reach the Configuration tab — and a
    choice that reached nothing would be a screen that does not work.
    It is read LAST of the three, so a Configuration-tab entry always
    wins the moment there is one.
    """
    opts = addon_options.snapshot() or {}
    service = str(opts.get("findings_notify_service")
                  or os.environ.get("BRAIN_FINDINGS_NOTIFY", "")
                  or settings_store.load().get("findings_notify_service")
                  or "").strip()
    severity = str(opts.get("findings_notify_min_severity")
                   or os.environ.get("BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY",
                                     "")).strip().lower()
    if severity not in findings_store.SEVERITIES:
        severity = notify_router.DEFAULT_MIN_SEVERITY
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
    stored = settings_store.load()

    def _hours(key: str, env: str):
        # The panel's own copy is the last resort — see
        # `_findings_notify_target` for why there is one at all.
        if opts.get(key) is not None:
            return notify_router.parse_hour(opts[key])
        hour = notify_router.parse_hour(os.environ.get(env, ""))
        return hour if hour is not None \
            else notify_router.parse_hour(stored.get(key) or "")

    return _hours("notify_quiet_start", "BRAIN_NOTIFY_QUIET_START"), \
        _hours("notify_quiet_end", "BRAIN_NOTIFY_QUIET_END")


async def _send_notification(rows: list[dict], held: bool = False,
                             message: tuple[str, str] | None = None) -> bool:
    """Deliver one message. A failure is a log line, never an exception.

    The finding is already safe on the list before this is called, so a
    bad service name must not be able to fail the run that filed it.
    """
    service, _sev = _findings_notify_target()
    if not service or not rows:
        return False
    # A reminder composes its own sentence (which repeat, since when) and
    # otherwise rides this path unchanged: the buttons, the panel link and
    # the failure reporting are the same three questions either way.
    title, body = message or notify_router.compose(rows, held=held)
    # Buttons, but only where they can be answered and only when the
    # message is about one finding — see `notify_router.actions_for`.
    buttons = notify_router.actions_for(rows, service)
    # And where a tap lands: the panel, rather than Home Assistant's front
    # page with the row three taps away. Only where the notifier reads the
    # keys (`open_link`), and only once the Supervisor has said what this
    # add-on's slug is — a made-up path opens the wrong add-on or nothing.
    data = {**({"actions": buttons} if buttons else {}),
            **notify_router.open_link(service, addon_options.panel_path())}
    import ha_data
    try:
        await ha_data.send_notification(
            service, title, body, data=data or None)
    except Exception as exc:  # noqa: BLE001 — a bad target can't fail the run
        log.warning("findings notification via %s failed: %s", service, exc)
        NOTIFY_LAST.update(error=str(exc)[:200], at=int(time.time()),
                           service=service)
        _report_async(reports.notify_failure, service, str(exc),
                      context=f"{len(rows)} finding(s)"
                      + (", held overnight" if held else ""))
        return False
    NOTIFY_LAST.update(error="", at=int(time.time()), service=service)
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


# The last delivery's outcome, cleared by the next one that works: a stale
# error beside a working notifier is the "a reading nothing can correct"
# failure the usage sensors already paid for.
NOTIFY_LAST: dict = {"error": "", "at": 0, "service": ""}


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
        # And what the ladder is holding. A queue nobody can see is a
        # queue that silently swallows, and this one can fail in two
        # directions — a house reminded about nothing, or not reminded
        # about a leak — so both ends are on the payload.
        **notify_router.escalation_state(),
        # What happened to the last message that went out. A delivery that
        # failed already files an incident, which is the right producer —
        # but a notifier that cannot deliver is the answer to "what is
        # wrong right now" and that question is asked of this payload, so
        # the fact has to be IN it. A failure whose only trace is a log
        # line scrolls off, and its whole symptom is silence on a phone.
        "last_error": str(NOTIFY_LAST.get("error") or "")[:200],
        "last_error_at": int(NOTIFY_LAST.get("at") or 0),
        "last_service": str(NOTIFY_LAST.get("service") or ""),
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
# And what it said. A brief delivered once to a phone and then gone is a
# message nobody can re-read or check, and the panel is the one place it
# could be kept — so it is kept beside the stamp, for the stamp's reason:
# a restart is the ordinary case, not the unlucky one.
BRIEF_TEXT_KEY = "brief_last_text"
BRIEF_STATE: dict = {"last_sent": schedule_store.get(BRIEF_SENT_KEY),
                     "last_text": schedule_store.get_text(BRIEF_TEXT_KEY),
                     "last_reasons": [], "last_error": "",
                     # When the morning window last became a signal. In
                     # memory only: a lost stamp costs one extra line in
                     # one batch, where persisting it would be a second
                     # store for a fact the loop re-derives every minute.
                     "signalled": 0.0}
# What "overnight" means for the summary that rides in the prompt.
BRIEF_NIGHT_HOURS = 12


def _local_now(now: float):
    """`now` on the house's own clock. One implementation, one answer."""
    import datetime  # noqa: PLC0415 — the module has no other need of it

    tz, _name = baselines.house_timezone()
    return datetime.datetime.fromtimestamp(now, tz)


def _now_line(now: float) -> str:
    """The house's clock as a model reads it: weekday, date, time, zone.

    A prompt full of "3 h ago" says nothing about whether it is three in
    the afternoon or three in the morning, and that is most of what makes
    a door opening worth a look.
    """
    local = _local_now(now)
    _tz, name = baselines.house_timezone()
    return f"{local:%A} {local.day} {local:%B %Y}, {local:%H:%M} ({name})"


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
    """The night's attributed changes and the house's states this morning.

    One logbook fetch and one states fetch, once a day. Neither is ever
    reported as a count — "31 changes with no recorded cause" is the
    logbook read aloud and nobody can act on it. The actions are read for
    one thing (whether a light still on was switched on by an automation,
    which means it is on on purpose) and the states are what
    `brief.morning_facts` reads for a door open at an odd hour or a light
    left on all night.
    """
    import aiohttp
    import ha_data  # noqa: PLC0415 — deferred, as every route that needs it

    out: dict = {}
    try:
        async with aiohttp.ClientSession() as session:
            try:
                mined = await actions.collect(
                    session, now - BRIEF_NIGHT_HOURS * 3600, now,
                    await checks.snapshot._users(session))
                if mined.get("available"):
                    out["actions"] = mined.get("actions") or []
            except Exception as exc:  # noqa: BLE001 — a brief without the
                # night is still a brief; one that failed because of it is not.
                log.info("brief could not read the night: %s", exc)
            try:
                states = await ha_data._rest_get(session, "/states")
                if isinstance(states, list):
                    out["states"] = states
            except Exception as exc:  # noqa: BLE001 — same reason
                log.info("brief could not read the states: %s", exc)
    except Exception as exc:  # noqa: BLE001
        log.info("brief could not reach Home Assistant: %s", exc)
    return out


def _brief_morning(now: float, night: dict) -> dict:
    """`brief.morning_facts` over what `_brief_overnight` fetched."""
    if not night.get("states"):
        return {}
    try:
        tz, _name = baselines.house_timezone()
        bucket = baselines.hour_of_week(now, tz)
    except Exception:  # noqa: BLE001 — no clock is no closures answer
        tz, bucket = None, None
    try:
        store = closures.load()
    except Exception:  # noqa: BLE001 — an unreadable store answers nothing
        store = {}

    def clock(ts: float) -> str:
        return _local_now(ts).strftime("%H:%M")

    try:
        return brief.morning_facts(
            night.get("states") or [], night.get("actions") or [], now,
            closures_store=store, bucket=bucket, clock=clock)
    except Exception as exc:  # noqa: BLE001 — a reason lost, not the brief
        log.info("brief could not read this morning: %s", exc)
        return {}


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
        await asyncio.to_thread(findings_store.list_all, "live"),
        verdict, {}, BRIEF_STATE["last_sent"] or (now - 86400),
        await asyncio.to_thread(_healing_brief_lines),
        morning=_brief_morning(now, night), now=now)

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
    # The brief reads no memory and no measurements today, which is how
    # it can say the hall is cold in a house whose hall is always cold.
    # Both are handed in rather than fetched there: `brief.py` owns no
    # store, and a second answer to what this house is like is the drift
    # `_CARD_CONTRACT` is shared to avoid.
    state["house"] = await _house_prompt_block(now)
    state["memory"] = await asyncio.to_thread(_memory_block)

    result = await _claude(
        engine.run_analyst, brief.frame(reasons, state), brief.SYSTEM,
        eff_model(), brief.TIMEOUT_S, brief.MAX_TURNS,
        "brief", job="brief")
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
    BRIEF_STATE["last_text"] = body
    schedule_store.set_text(BRIEF_TEXT_KEY, body)
    await _send_notification([{"text": body, "severity": "info"}])
    return body


async def _brief_loop():
    """Wake often, send at most once, and only when there is something to say."""
    await asyncio.sleep(BRIEF_FIRST_DELAY_S)
    while True:
        try:
            on, fallback = _brief_enabled()
            service, _sev = _findings_notify_target()
            now = time.time()
            local = _local_now(now)
            due = brief.due(now, local.hour * 60 + local.minute,
                            rhythm.wake_minute(rhythm.profile(), local),
                            fallback, BRIEF_STATE["last_sent"])
            # The window is a signal whether or not a brief goes out. This
            # house waking up is a moment the look should read beside
            # whatever happened overnight, and gating it on an option
            # about phones would make the Resident's morning depend on
            # whether somebody wanted a push notification.
            if due and now - float(BRIEF_STATE.get("signalled") or 0) > 3600:
                BRIEF_STATE["signalled"] = now
                _resident_offer(signals.from_time(
                    "morning", now, text="this house is up for the day"))
            if on and service and due:
                # Stamped before the run, not after: a pass that takes
                # three minutes must not let the next tick start a
                # second one, and a failed brief is still this
                # morning's — retrying it all morning is worse.
                BRIEF_STATE["last_sent"] = now
                schedule_store.set(BRIEF_SENT_KEY, now)
                sent = await _send_brief(now)
                log.info("morning brief %s", "sent" if sent else "skipped")
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


def _curiosity_diagnostics() -> dict:
    """What brAIn is curious about, what it has asked, and what it learned.

    Pure over the two stores, and every failure reads as a sentence
    rather than taking the payload down: six sections and a note about
    the seventh is a screen somebody can read, where a 500 is not
    (`house.py`'s rule).
    """
    try:
        on = _curiosity_enabled()
        tz, _name = baselines.house_timezone()
        now = time.time()
        ledger = manual_ledger.load()
        store = curiosity.load()
        found = manual_ledger.candidates(ledger, tz, now)
        ranked = curiosity.worth_asking(found, store, now, tz)
        return {
            "enabled": on,
            "evidence": manual_ledger.progress(ledger, now),
            "manual_actions": len(ledger.get("rows") or []),
            "budget": {"per_day": curiosity.MAX_PER_DAY,
                       "per_week": curiosity.MAX_PER_WEEK,
                       **curiosity.spent(store, now, tz)},
            # Empty when there is room; a sentence when there is not.
            "holding": curiosity.budget_reason(store, now, tz),
            "counts": curiosity.counts(store),
            # Capped, and the count beside it, so an over-long queue says
            # what it is not showing rather than disagreeing more quietly
            # (the memory queue's rule).
            "curious_about": ranked[:8],
            "curious_total": len(ranked),
            "learned": curiosity.recent(store, 8),
        }
    except Exception as exc:  # noqa: BLE001 — a section that took the
        # report down would be worse than the section being a sentence.
        return {"error": str(exc)[:200]}


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
WEEKLY_TEXT_KEY = "weekly_last_text"
WEEKLY_STATE: dict = {"last_sent": schedule_store.get(WEEKLY_SENT_KEY),
                      "last_text": schedule_store.get_text(WEEKLY_TEXT_KEY),
                      "last_error": "", "last_state": {}}


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
    # The rows somebody can see, which is what "still open" means in a
    # message to them. Unfiltered, the count took in `held` rows — the ones
    # triage looked at and chose NOT to show — and `triaging` ones nothing
    # has judged yet, so the report called rows brAIn had kept off the
    # list "still open", and a week whose only material was held rows
    # could spend a run saying so. The brief has always read "live".
    rows = await asyncio.to_thread(findings_store.list_all, "live")
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
    # Same two blocks the brief gets, and for the same reason: the
    # numbers above are what happened this week, and these are what this
    # house is like. Added after `last_state` is taken, because that
    # rides into /api/diagnostics and a memory excerpt is a fact about
    # somebody's home rather than a diagnostic.
    state["house"] = await _house_prompt_block(now)
    state["memory"] = await asyncio.to_thread(_memory_block)
    if not weekly.worth_reporting(state):
        # Not an error: a quiet week is the design. Clearing it matters
        # because a stale `last_error` beside a report that never went is
        # read as the reason it never went.
        WEEKLY_STATE["last_error"] = ""
        log.info("weekly report: nothing to report, not sent")
        return ""

    result = await _claude(
        engine.run_analyst, weekly.frame(state), weekly.SYSTEM,
        eff_model(), weekly.TIMEOUT_S, weekly.MAX_TURNS, "weekly",
        job="weekly")
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
    schedule_store.set_text(WEEKLY_TEXT_KEY, body)
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
# A checks pass asked for from outside the panel. `starting` is flipped
# synchronously for `start_auth_check`'s reason — `create_task` only
# schedules, so two requests in one drain would both read a guard their
# own task has not set yet — and it is a SECOND flag rather than
# `CHECKS_STATE["running"]` because `run_checks` owns that one and is also
# called by the loop, and one function setting another's guard is how the
# two callers stop agreeing about what is in flight.
CHECKS_REQUEST_STATE: dict = {"starting": False, "asked": 0, "last": 0.0}


async def _apply_finding_requests() -> list[dict]:
    """Drain the request drop, through the tab's own endings.

    Returns one result per request, for the log and for the tests: a
    request naming a finding that is gone is `ok: False`, which is an
    ordinary race — somebody's phone was a few seconds out of date — and
    never a reason to retry or to put the row back.

    A `checks` request is the one kind here that is not an ending, so it
    is collected rather than applied in the loop and the pass is started
    **after** every answer in the drain has landed: a pass that ran first
    would re-file what the answers in the same burst had just settled.
    """
    requests = await asyncio.to_thread(finding_requests.collect)
    # A person answered. It is the highest base weight in the signals
    # table and deliberately not hot — somebody typing an answer is not an
    # emergency — and what it must not do is sit behind a hundred sensors,
    # which is what the weight is for.
    _resident_offer_many(requests, signals.from_reply, time.time())
    out: list[dict] = []
    asked: list[dict] = []
    for req in requests:
        if req.get("kind") == finding_requests.CHECKS_KIND:
            asked.append(req)
            continue
        if req.get("kind") == "todo":
            out.append(await _apply_todo_request(req))
            continue
        if req.get("kind") == finding_requests.HYPOTHESIS_KIND:
            out.append(await _apply_hypothesis_request(req))
            continue
        ts, action = req["ts"], req["action"]
        result = {"ts": ts, "action": action, "via": req.get("via", ""),
                  "ok": False, "why": "no such finding"}
        if action == "snooze":
            until = await asyncio.to_thread(_request_snooze_until, ts,
                                            req.get("hours"))
            row = await asyncio.to_thread(findings_store.snooze, ts, until)
            result["ok"] = bool(row)
        elif action == "reply":
            finding = await asyncio.to_thread(findings_store.get, ts)
            if finding:
                # Started, never awaited: a reply is a Claude run of up to
                # REPLY_TIMEOUT_S, and an ending given in the same burst —
                # or the next one, fifteen seconds on — must not wait for it.
                ok, why = _start_reply(finding, req.get("note", ""))
                result["ok"] = ok
                if not ok:
                    result["why"] = why
        elif action == "todo":
            # The feed's own *Add to to-do*, from a Repairs dialog or a
            # notification button: the same move the tab makes, through
            # the same door, so the item, the settled key and the missing
            # memory line are exactly what the panel's press produces.
            finding = await asyncio.to_thread(findings_store.get, ts)
            if finding:
                try:
                    await _move_finding_to_todo(finding, req.get("note", ""))
                    result["ok"] = True
                except web.HTTPException as exc:
                    result["why"] = exc.text or "the to-do list refused it"
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
    if asked:
        out.append(_start_requested_checks(asked))
    return out


def _request_snooze_until(ts: int, hours: float | None) -> int:
    """When a snooze asked for from Home Assistant should end.

    One that names its hours gets them — Repairs' "Remind me tomorrow"
    says 24 on the button. One that does not is a Dismiss, and a Dismiss
    is the feed's own press: it buys what the feed would have bought for
    this case (`cases.snooze_until`, keyed on how much it matters), so a
    phone and the panel cannot disagree about when a card comes back.
    """
    now = time.time()
    if hours:
        return int(now + float(hours) * 3600)
    case = cases.get(f"f:{int(ts)}", now)
    if case is None:
        return int(now + finding_requests.SNOOZE_DEFAULT_H * 3600)
    return cases.snooze_until(case, now)


def _start_requested_checks(asked: list[dict]) -> dict:
    """Start one pass for however many asked for it in this drain.

    **Coalescing is load-bearing rather than tidy.** The pass is started
    and not awaited — a run reads the whole house and is minutes of work,
    where this loop has to be back in fifteen seconds for the next answer
    somebody gives from their phone, which is `h_baselines_run`'s clock —
    and `create_task` only schedules, so two tasks made in one tick would
    both pass `run_checks`' own guard before either had set it.

    A pass already in flight means the request is **consumed and logged**,
    never queued: a second pass over the same house a minute later finds
    the same things, and the one running is about to answer the question
    that was asked.
    """
    via = ", ".join(sorted({r.get("via") or "elsewhere" for r in asked}))
    result = {"kind": "checks", "asked": len(asked), "via": via,
              "ok": False, "why": "a checks pass is already running"}
    CHECKS_REQUEST_STATE["asked"] += len(asked)
    CHECKS_REQUEST_STATE["last"] = time.time()
    if CHECKS_STATE["running"] or CHECKS_REQUEST_STATE["starting"]:
        log.info("checks asked for by %s — a pass is already running", via)
        REQUESTS_STATE["missed"] += 1
        return result
    CHECKS_REQUEST_STATE["starting"] = True

    async def run_it() -> None:
        try:
            await run_checks("service")
        finally:
            CHECKS_REQUEST_STATE["starting"] = False

    asyncio.create_task(run_it())
    REQUESTS_STATE["applied"] += 1
    REQUESTS_STATE["last"] = time.time()
    log.info("running the house checks — asked for by %s", via)
    return {**result, "ok": True, "why": ""}


async def _apply_hypothesis_request(req: dict) -> dict:
    """An answer to one of brAIn's guesses, given in Home Assistant.

    Through `_answer_hypothesis`, the code the Findings tab's own Yes and
    No run, so `brain.answer_question` closes the guess exactly as a press
    would: a yes files the claim as memory, a no records the dead end and
    files the reason as a correction. A guess that is no longer open — it
    expired, or somebody answered it on the tab a moment earlier — is the
    ordinary race every request here allows for, and is dropped and
    logged rather than retried.

    The undo token `_answer_hypothesis` records is never handed to
    anybody: there is no toast on an automation, and it lapses on its own.
    """
    ts, action = req["ts"], req["action"]
    result = {"kind": finding_requests.HYPOTHESIS_KIND, "ts": ts,
              "action": action, "via": req.get("via", ""),
              "ok": False, "why": "no such open guess"}
    payload = await _answer_hypothesis(ts, action, req.get("note", ""))
    if payload is not None:
        result["ok"], result["why"] = True, ""
        REQUESTS_STATE["applied"] += 1
    else:
        REQUESTS_STATE["missed"] += 1
    REQUESTS_STATE["last"] = time.time()
    log.info("guess %s: %s from %s%s", ts, action,
             result["via"] or "elsewhere",
             "" if result["ok"] else f" — {result['why']}")
    return result


async def _apply_todo_request(req: dict) -> dict:
    """One request about the to-do list, applied through the tab's own code.

    `h_todo_done`'s three steps are not repeated here — the store, the
    ledger upgrade and the memory line are what "done" means, and a second
    implementation would be a tick in the To-do app teaching brAIn
    something different from the identical press on the tab. What is
    absent on purpose is the undo token: `undo_store` is the toast's, and
    there is no toast on a lock screen.
    """
    action = req["action"]
    result = {"kind": "todo", "id": req.get("id", 0), "action": action,
              "via": req.get("via", ""), "ok": False, "why": "no such item"}

    if action == "add":
        item = await asyncio.to_thread(
            todo_store.add, req["text"], origin="hand")
        result["ok"] = item is not None
        if item is None:
            result["why"] = "the list is full"
        else:
            result["id"] = item["id"]
    elif action == "done":
        item = await asyncio.to_thread(todo_store.get, req["id"])
        if item:
            await _complete_todo(item, req.get("note", ""))
            result["ok"] = True
    elif action == "drop":
        def drop() -> bool:
            removed = todo_store.remove(req["id"])
            if removed and removed.get("finding_key"):
                findings_store.unsettle(removed["finding_key"])
            return removed is not None

        result["ok"] = await asyncio.to_thread(drop)

    if result["ok"]:
        result["why"] = ""
        REQUESTS_STATE["applied"] += 1
    else:
        REQUESTS_STATE["missed"] += 1
    REQUESTS_STATE["last"] = time.time()
    log.info("to-do %s %s from %s%s", action, result["id"],
             result["via"] or "elsewhere",
             "" if result["ok"] else f" — {result['why']}")
    return result


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
    try:
        import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

        orientation = await ha_data.collect_orientation(sentence)
    except Exception as exc:  # noqa: BLE001 — a map brAIn could not read
        # is a smaller prompt, never a refused sentence.
        log.info("could not orient the intent run: %s", exc)
        orientation = {}
    # One run answers both kinds of sentence. The model decides `once`
    # and the caller routes on it: a one-off is armed through `intents`
    # exactly as before, a standing rule is offered through `authoring`
    # — simulated over the month and graded against the person ledger
    # before it is a card. `authoring.SYSTEM` is the prompt because it
    # is the one that asks the question; the one-off's own prompt
    # presumed the answer.
    started = time.time()
    try:
        result = await _claude(
            engine.run_analyst, authoring.prompt(sentence, orientation),
            authoring.SYSTEM, eff_model(), intents.TIMEOUT_S,
            intents.MAX_TURNS, "intent", job="automation",
            schema=authoring.SCHEMA, priority=run_queue.PRESS)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc)}
    journal.record("intent", "ok" if result.get("ok") else "error",
                   ok=bool(result.get("ok")),
                   error="" if result.get("ok") else str(result.get("error")),
                   duration_s=time.time() - started)
    answer = intents.parse_answer(result.get("text") or result.get("raw") or "",
                                  result.get("data"))
    if not result.get("ok") or answer is None:
        return await asyncio.to_thread(intents.note, {
            "sentence": sentence,
            "refused": ("brAIn could not work out an automation from that "
                        "sentence: "
                        + str(result.get("error")
                              or "it did not answer with a config")[:200])},
            now)

    standing = answer.get("once") is False and not answer.get("error")
    if not standing and \
            await asyncio.to_thread(intents.armed_count) >= intents.MAX_ARMED:
        return await asyncio.to_thread(intents.note, {
            "sentence": sentence,
            "refused": (f"you already have {intents.MAX_ARMED} one-offs "
                        "waiting to happen. Remove one and ask again — a "
                        "list of things about to happen is only useful "
                        "while it is short.")}, now)

    protected = automation_writer.protected_patterns()
    builder = authoring.build if standing else intents.build
    obj = await asyncio.to_thread(
        builder, sentence, answer, int(now * 1000), protected)
    if obj.get("refused"):
        return await asyncio.to_thread(intents.note, obj, now)

    import aiohttp  # noqa: PLC0415 — as `_offer_routines` does

    tz, _name = await asyncio.to_thread(baselines.house_timezone)
    try:
        async with aiohttp.ClientSession() as session:
            obj["replay"] = await _replay_config(
                session, obj["config"], now - REPLAY_DAYS * 86400, now, tz)
            if standing:
                obj["spoken"]["against_you"] = await _grade_against_you(
                    session, obj["config"], now, tz)
    except Exception as exc:  # noqa: BLE001 — the replay is the card's
        # sanity check on a trigger that has never fired, not a gate: a
        # recorder that will not answer costs the number, never the
        # sentence somebody typed.
        obj["replay"] = {"refused": True,
                         "error": f"brAIn could not replay it: {exc}"}
    if standing:
        obj["spoken"]["case"] = authoring.case_line(
            obj.get("replay"), obj["spoken"].get("against_you"), REPLAY_DAYS)
    row = await asyncio.to_thread(proposals.add, obj)
    if row is None:
        return await asyncio.to_thread(intents.note, {
            **obj, "refused": ("the Proposals tab is full, or brAIn has "
                               "already offered this exact automation. "
                               "Answer what is on it and ask again.")}, now)
    log.info("%s proposed from %s: %s",
             "standing automation" if standing else "one-off intent",
             log_safe(req.get("via") or "the panel"), log_safe(obj["title"]))
    return row


async def _grade_against_you(session, config: dict, now: float, tz) -> dict:
    """The fortnight's firings graded against the person ledger.

    `h_simulate`'s second half, lifted so the card and the tool cannot
    disagree about what "you did the same" means: a replay over
    `authoring.GRADE_DAYS`, the history the trigger watches, and
    `trials.evaluate` over `routines.load()`'s rows. A grade that cannot
    be made is carried as a refusal, never as zeros — `trials._refused`'s
    own shape, which `authoring.case_line` reads.
    """
    start = now - authoring.GRADE_DAYS * 86400
    watched = sorted(shadow.entities_watched(config))
    history = await shadow.fetch_history(session, watched, start, now) \
        if watched else {}
    rows = (await asyncio.to_thread(routines.load)).get("rows") or []
    return await asyncio.to_thread(
        trials.evaluate, config, history, rows, start, now, tz, now)


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
        # And what the nightly cap left unread, by count and by a sample of
        # names: a washer the pass never read is a silence nothing else
        # on any surface could explain.
        "eligible": store.get("eligible", store.get("asked", 0)),
        "cut": store.get("cut_count", 0),
        "cut_sample": list(store.get("cut") or []),
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
        # `brain.check` and the Run-checks button land here too, and a
        # pass that was asked for and never ran leaves the same silence
        # as one nobody asked for.
        "checks_asked": CHECKS_REQUEST_STATE["asked"],
        "checks_asked_last": int(CHECKS_REQUEST_STATE["last"]),
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
                # The moment itself, as a signal. `from_time` is the one
                # adapter that cannot answer None: a scheduled moment
                # happened whether or not anything else did, and the look
                # reading "it is bedtime here" beside a door that is open
                # is the difference between a reading and a reason.
                _resident_offer(signals.from_time(
                    "bedtime", now,
                    text="this house has settled for the night"))
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
        history = dict(store.get("history") or {})
        planned = await asyncio.to_thread(
            healing.plan, rows, snapshot, patterns, done,
            healing.MAX_PER_NIGHT, started, history)

        attempts = list(store["attempts"]) if store.get("night") == night else []
        skips = list(store["skips"]) if store.get("night") == night else []
        # A target that keeps needing the same heal stops being healed and
        # becomes a finding (`healing.plan`'s `chronic`). Filed through the
        # gate every producer files through, so it is looked at before it
        # is shown, and deduped on its text, so a target that stays chronic
        # night after night is one row.
        chronic = planned.get("chronic") or []
        if chronic:
            tz, _tzname = await asyncio.to_thread(baselines.house_timezone)
            rows_for = [healing.chronic_finding(c, c.get("heals") or [], tz)
                        for c in chronic]
            # A direct call inside the thunk, so the sweep that holds every
            # producer to the gate (`test_triage`) can see this one too.
            await asyncio.to_thread(
                lambda: findings_store.add_many(triage.gate(rows_for)))
            log.info("healing: %d target(s) keep coming back — stopped and "
                     "filed", len(chronic))
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
                at = int(time.time())
                row.update({"ok": ok, "error": why, "at": at})
                if ok:
                    row["times"] = healing.record_heal(history, row, at)
                attempts.append(row)
                # Written after EVERY attempt, not at the end: a restart
                # at three in the morning must not find a pass that made
                # two calls and recorded none of them.
                await asyncio.to_thread(
                    healing.save, {"night": night,
                                   "started_at": int(started),
                                   "attempts": attempts, "skips": skips,
                                   "history": history})
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
                 "attempts": attempts, "skips": skips, "history": history,
                 "chronic": [{"target": c.get("target"),
                              "remedy": c.get("remedy"),
                              "heals": len(c.get("heals") or [])}
                             for c in chronic]}
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


# A reminder that is due in ten minutes must not wait out a nine-hour
# night, and a loop woken every thirty seconds to find nothing climbing is
# a poll. The floor is what stops a stamp in the past spinning the loop.
ESCALATION_MIN_WAIT_S = 30


async def _escalation_tick() -> int:
    """Send the reminders that have come due, and forget the rows that ended.

    The live store is read on **every** tick and the ledger's own copy
    never is: fixed, dismissed, snoozed, moved to the to-do list and
    cleared by the check that filed it are five endings and all of them
    mean stop, and only the store knows which have happened. A snoozed
    row is deliberately in that set — "remind me later" is somebody
    answering, and going on reminding them is the notifier arguing.

    **A store that could not be read holds the reminder rather than
    sending it**, which is the opposite of what the hold queue does with
    the same uncertainty and is deliberate: a held row is announced once
    and never again, so a wrong send there costs one message, where a
    ladder that cannot tell whether a problem is over would go on ringing
    three times about one somebody fixed an hour ago. A reminder deferred
    costs a pass, and the pass is minutes away.
    """
    try:
        now = time.time()
        rows_live = {int(f.get("ts") or 0): f
                     for f in findings_store.list_all("open")
                     if not findings_store.is_snoozed(f, now)}
        live = set(rows_live)
    except Exception as exc:  # noqa: BLE001 — see the docstring: not knowing
        # whether a problem is over is not a licence to ask again.
        log.info("could not read the findings store before a reminder: %s", exc)
        return 0
    dropped = notify_router.prune_escalations(live)
    if dropped:
        log.info("stopped escalating %d finding(s) that were answered",
                 len(dropped))
    due = notify_router.due_escalations(now)
    if not due:
        return 0
    tz, _name = baselines.house_timezone()
    sent = 0
    for row in due:
        message = notify_router.compose_escalation(row, tz)
        # The buttons are the card's own answers, read off the LIVE row
        # rather than the ledger's slim copy: a battery's reminder offers
        # "Replaced it" because its card does, and the ledger row carries
        # neither the check that raised it nor whether hands are needed.
        target = rows_live.get(int(row.get("ts") or 0), row)
        await _send_notification([target], message=message)
        notify_router.record_reminder(int(row.get("ts") or 0), time.time())
        sent += 1
    return sent


async def _notify_flush_loop():
    """Wake at the end of each quiet window and send what it held.

    The wait is recomputed every pass rather than slept once: the option
    can be edited from the Configuration tab without a restart, and a
    loop that had already committed to a 9-hour sleep would honour the
    old bedtime until tomorrow. It is also where the escalation ladder
    ticks — one loop, because "is anything waiting to be said" has one
    answer and a second loop would be a second clock to keep true.
    """
    await asyncio.sleep(NOTIFY_FLUSH_FIRST_DELAY_S)
    while True:
        try:
            await _escalation_tick()
            start, end = _quiet_hours()
            now = time.time()
            wait = float(NOTIFY_FLUSH_POLL_S)
            if start is None or end is None:
                # No quiet hours: anything left in the queue is from
                # before somebody turned them off, and has waited enough.
                if notify_router.load_queue():
                    await _flush_held_findings()
            else:
                tz, _name = baselines.house_timezone()
                if not notify_router.in_quiet_hours(now, start, end, tz):
                    if notify_router.load_queue():
                        await _flush_held_findings()
                else:
                    wait = max(60.0, min(
                        notify_router.quiet_ends_at(now, end, tz) - now,
                        float(NOTIFY_FLUSH_POLL_S)))
            due_at = notify_router.next_escalation_at()
            if due_at:
                wait = max(ESCALATION_MIN_WAIT_S,
                           min(wait, due_at - time.time()))
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a bad pass
            log.warning("notification flush pass failed: %s", exc)
            _report_async(reports.notify_failure,
                          _findings_notify_target()[0], str(exc),
                          context="quiet-hours flush pass")
            await asyncio.sleep(NOTIFY_FLUSH_POLL_S)


async def _announce_findings(created: list[dict]) -> None:
    """Push newly-created findings out, or hold them until morning.

    Only ever handed the CREATED list — add_many dedupes against every
    status and the settled ledger, so a re-reported problem cannot ring the
    phone twice, and there is nothing to announce at startup because a
    replayed store creates nothing.

    Three tiers, decided per row by `notify_router.tier_of`. **Escalate**
    is `critical` severity and a `now` producer — a leak, a freeze, a hub
    that has stopped answering — and it goes out immediately whatever the
    hour, and then asks again on a ladder until somebody answers it.
    **Notify** is everything else above the floor: once, held through the
    night unless it is urgent, which is exactly what every release before
    this one did with the whole set. **Quiet** is below the floor, and it
    is not lost — the row is on the Findings tab, in `todo.brain` and in
    Home Assistant's own Repairs, which are places somebody looks rather
    than places that interrupt.

    Inside quiet hours the notify tier splits by
    `notify_router.urgency_of`, which is a different axis from severity: a
    `critical` battery forecast is three weeks away and a `warning` about
    a boiler that has stopped answering is now. The severity floor is
    applied FIRST, so a row nobody wanted notifying about is not held
    either — otherwise it would simply arrive in the morning digest
    instead.

    A failed delivery is a log line, never an error: the finding is already
    safe on the list, and the notification is the courtesy copy.
    """
    service, min_severity = _findings_notify_target()
    if not service or not created:
        return
    tiers = notify_router.classify(created, min_severity)
    escalating, once = tiers["escalate"], tiers["notify"]
    if not escalating and not once:
        return

    now = time.time()
    if escalating:
        # Quiet hours do not hold these and are not meant to: the window
        # protects a bedroom from a battery three weeks from dying, and
        # a freeze warning at 3am is when it is wanted.
        await _send_notification(escalating)
        started = notify_router.begin_escalation(escalating, now)
        log.info("escalating %d of %d critical finding(s)",
                 started, len(escalating))

    if not once:
        return
    start, end = _quiet_hours()
    tz, _name = baselines.house_timezone()
    if not notify_router.in_quiet_hours(now, start, end, tz):
        await _send_notification(once)
        return

    # Inside the quiet window only the urgent get through, and the rest
    # are HELD rather than dropped: they are on the Findings tab either
    # way, and a notifier that silently decides some problems were not
    # worth mentioning is one nobody can reason about.
    urgent = [f for f in once if notify_router.urgency_of(f) == "now"]
    later = [f for f in once if notify_router.urgency_of(f) != "now"]
    if urgent:
        await _send_notification(urgent)
    if later:
        depth = notify_router.hold(later, now)
        log.info("held %d finding(s) until quiet hours end (%d waiting)",
                 len(later), depth)


async def _search_run(insight_id: str, cat: dict, framing: dict):
    """Give Claude a map of the home and read-only tools, and let it look.

    The cheap path, and the only one that can afford history on a typed
    question. The map is a few hundred characters — domain counts, area
    counts, a handful of anchors — where the snapshot is tens of thousands,
    so what a run costs finally tracks what it actually needed rather than
    being the same number whatever was asked.

    Returns ``(result, cost, sent)``, or ``(None, None, None)`` when the map
    itself could not be collected — the caller then runs the snapshot path,
    which is the floor under every mode. ``sent`` is what the analyst was
    given, handed back rather than re-collected: `capture` files exactly the
    payload this run used, and a second fetch would file a different house.
    """
    import ha_data
    try:
        # The card's domains go in so memory retrieval can find the facts
        # about its kind of device — and the question's words, which
        # `collect_orientation` passes on as the retrieval query.
        orientation = await ha_data.collect_orientation(
            question=framing["question"], domains=cat.get("domains") or ())
    except Exception as exc:  # noqa: BLE001 — a failed map is a fallback, not an error
        log.warning("%s: could not collect the orientation map (%s)", insight_id, exc)
        return None, None, None
    prompt = build_orientation_prompt(cat, orientation, **framing)
    # `entities` is what the run has been GIVEN, and a search run is given
    # none — the spinner says "searching" rather than claiming a number the
    # snapshot path would have meant literally.
    _set_job(insight_id, state="searching", prompt_chars=len(prompt), entities=0)
    log.info("map for %s: %d entities exist across %d domains, %d prompt chars "
             "(~%s tokens in) — searching", insight_id,
             orientation.get("entity_count", 0), len(orientation.get("domains") or {}),
             len(prompt), _tok(len(prompt) // CHARS_PER_TOKEN))
    result = await _claude(
        engine.run_analyst, prompt, ANALYST_SYSTEM, eff_model(),
        eff_timeout_s(), ANALYST_MAX_TURNS, "card",
        job="card", schema=CARD_SCHEMA, priority=_job_priority(insight_id),
    )
    return result, _record_usage(result, insight_id), {
        "gather_mode": "search", "bundle": orientation,
        "prompt_chars": len(prompt)}


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
    result = await _claude(
        engine.run_claude, prompt, SYSTEM_PROMPT, eff_model(), eff_timeout_s(),
        source="card", job="card", schema=CARD_SCHEMA,
        priority=_job_priority(insight_id),
    )
    return result, _record_usage(result, insight_id), {
        "gather_mode": "snapshot", "bundle": bundle, "prompt_chars": len(prompt)}


# ---------------------------------------------------------------------------
# What brAIn measured, on its way into a prompt
# ---------------------------------------------------------------------------

async def _house_snapshot(now: float | None = None) -> dict:
    """`house.snapshot()` with the energy figures fetched.

    One helper because four callers need the same payload — the analyst's
    house block, the brief's, the weekly report's and the milestone
    table — and `house.energy_week` caches for an hour, so asking four
    times in a pass costs one statistics query at most.
    """
    import aiohttp  # noqa: PLC0415 — the module has no other need of it

    now = time.time() if now is None else now
    try:
        async with aiohttp.ClientSession() as session:
            week = await house.energy_week(session, now)
    except Exception as exc:  # noqa: BLE001 — one section, not the payload
        # Same rule the aggregate route follows: six measurements and a
        # sentence about the seventh is an answer; a failure here is not
        # a reason for a card to lose the other six.
        log.info("could not read the week's energy for the house block: %s", exc)
        week = None
    return await asyncio.to_thread(house.snapshot, now, week)


async def _current_inputs(cat_id: str, eff: dict) -> dict | None:
    """This card's input fingerprint, right now. None when it cannot be read.

    None rather than a partial answer: `_inputs_change` treats a missing
    fingerprint as "moved", so a card that could not be measured refreshes
    on the interval alone — which is the old behaviour, and the safe
    direction for a gate that cannot see.
    """
    try:
        # Without this card's own rows: see `findings_store.prompt_block`.
        findings_text = await asyncio.to_thread(
            findings_store.prompt_block, (cat_id,))
        snap = await _house_snapshot()
        return await asyncio.to_thread(
            _card_inputs, cat_id, eff, findings_text, snap)
    except Exception as exc:  # noqa: BLE001 — accounting, not the run
        log.debug("could not fingerprint %s after its run: %s", cat_id, exc)
        return None


def _because_of(job: dict, question: str | None) -> str:
    """Why this run happened, in one short phrase.

    The scheduler puts its own sentence on the job when it queues one;
    everything else got here because a person pressed something, and
    those two are the only kinds there are.
    """
    said = str((job or {}).get("because") or "").strip()
    if said:
        return said[:200]
    refine = " ".join(str((job or {}).get("refine") or "").split())
    if refine:
        clipped = refine if len(refine) <= 80 else refine[:79].rstrip() + "…"
        return f"you asked for a change: “{clipped}”"
    return "you asked" if question is not None else "you pressed Generate"


async def _house_prompt_block(now: float | None = None) -> str:
    """The 2 KB block, or "" when nothing has been measured yet."""
    try:
        snap = await _house_snapshot(now)
    except Exception as exc:  # noqa: BLE001 — a prompt section, not the run
        log.info("could not build the house block: %s", exc)
        return ""
    return house_block(snap)


# ---------------------------------------------------------------------------
# What a card says this house is missing, offered as an automation
# ---------------------------------------------------------------------------
#
# A card could say "the patio light should come on when the back door opens
# after dark" only as prose in its summary, which nothing parses — so the
# improvement the Automations focus and the milestone frame explicitly ask
# for was a dead end, and acting on it meant retyping it into the ask bar.
# The contract has an `opportunities` field now: the sentence the homeowner
# would say to ask for it, and the entities it names. Each one is handed to
# the ask bar's own third verb (`intents.request`), so it is drafted,
# replayed over the recorder, graded against what this household did and
# offered on the Proposals tab exactly as a typed sentence is — one
# implementation of "a rule from a sentence", whichever surface had it.
#
# It is an UNATTENDED producer — a card refreshes on a schedule and the
# authoring run behind each sentence is a Claude run nobody pressed — so it
# answers to the three gates every scheduled run does (`_resident_gate`),
# is capped per card and per day, and never re-offers what the same card
# offered on its previous run. A sentence it did not queue keeps the reason
# on the card, and the card's ⋯ offers to put it in the ask bar instead.
MAX_CARD_OPPORTUNITIES = 2
MAX_CARD_OPPORTUNITY_CHARS = 300
MAX_CARD_OPPORTUNITY_ENTITIES = 8
# A runaway guard, not a budget (`triage.MAX_PER_DAY`'s kind): nine cards
# refreshing on one evening must not become eighteen authoring runs.
CARD_OPPORTUNITIES_PER_DAY = 4
CARD_OPPS_STATE: dict = {"day": "", "count": 0}


def _opportunity_key(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower()).split())


def _card_opportunities(raw) -> list[dict]:
    """The model's ``opportunities``, cleaned: a sentence each, real
    entity ids only, deduped, capped. Anything else is dropped."""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text") or "").split())
        text = text[:MAX_CARD_OPPORTUNITY_CHARS]
        key = _opportunity_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"text": text, "entities": _clean_entity_ids(
            item.get("entities"), MAX_CARD_OPPORTUNITY_ENTITIES)})
        if len(out) >= MAX_CARD_OPPORTUNITIES:
            break
    return out


def _opportunity_sentence(text: str) -> str:
    """The card's sentence in the shape the ask bar's third verb reads, or
    "" for one that is a question rather than a rule."""
    text = str(text or "").strip()
    if not text or INTENT_QUESTION_RE.match(text) or text.endswith("?"):
        return ""
    if INTENT_RE.match(text):
        return text
    lowered = text[:1].lower() + text[1:] if text[1:2].islower() else text
    return f"From now on, {lowered}"


async def _offer_card_opportunities(insight_id: str, found: list[dict],
                                    previous=None) -> list[dict]:
    """Queue what this card says the house is missing, behind the gates.

    Returns the card's own record of each: its sentence, its entities,
    whether it was queued, and the reason when it was not — so the card
    can say "offered on Proposals" or "not offered: automatic runs are
    paused" rather than going quiet. Never raises: a card that wrote
    itself must not fail over the automations it suggested.
    """
    if not found:
        return []
    before = {_opportunity_key(o.get("text")) for o in previous or []
              if isinstance(o, dict) and o.get("queued")}
    try:
        why = _resident_gate(settings_store.load())
    except Exception as exc:  # noqa: BLE001 — "I could not tell" holds
        why = f"brAIn could not read its own settings ({exc})"
    day = time.strftime("%Y-%m-%d")
    if CARD_OPPS_STATE["day"] != day:
        CARD_OPPS_STATE.update(day=day, count=0)
    out: list[dict] = []
    for opp in found:
        sentence = _opportunity_sentence(opp.get("text"))
        # `sentence` rides on the row because the card's ⋯ puts it in the
        # ask bar, and the ask bar routes on its opening words: the panel
        # must be handed the shape that routes, not a second copy of the
        # rule that makes it.
        row = {**opp, "sentence": sentence, "queued": False, "why": ""}
        if _opportunity_key(opp.get("text")) in before:
            # Offered when this card last ran; whatever was answered on
            # Proposals then is the answer, and asking again would spend
            # an authoring run to be told so.
            row.update(queued=True, why="offered on an earlier run")
        elif not sentence:
            row["why"] = "it reads as a question rather than a rule"
        elif why:
            row["why"] = why
        elif CARD_OPPS_STATE["count"] >= CARD_OPPORTUNITIES_PER_DAY:
            row["why"] = ("brAIn has already offered "
                          f"{CARD_OPPORTUNITIES_PER_DAY} automations from "
                          "cards today")
        else:
            try:
                queued = await asyncio.to_thread(
                    intents.request, sentence, f"card:{insight_id}"[:32])
            except Exception as exc:  # noqa: BLE001
                queued = ""
                row["why"] = f"it could not be queued ({exc})"
            if queued:
                CARD_OPPS_STATE["count"] += 1
                row["queued"] = True
                log.info("card %s offered an automation: %s",
                         log_safe(insight_id), log_safe(sentence))
        out.append(row)
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

        # Standing changes asked for on THIS card, whichever kind it is: an
        # asked card that has been refined keeps what it was told on every
        # later regenerate, exactly as a category card keeps its feedback.
        feedback = [f["text"] for f in feedback_store.list_feedback(insight_id)]
        # One press of Refine: the change this run exists to make.
        refine = str(job.get("refine") or "").strip()[:feedback_store.MAX_CHARS]
        # Continuity: what the analyst already knows, and what this card
        # said last time — so runs build on each other instead of looping.
        # An asked card has a last time too once it exists: regenerating or
        # refining one revises it rather than starting from nothing.
        knowledge = knowledge_store.prompt_block()
        previous = None
        previous_opportunities = []
        if question is None or refine or _insight_path(insight_id).exists():
            try:
                prev = json.loads(_insight_path(insight_id).read_text(encoding="utf-8"))
                previous = {k: prev.get(k) for k in
                            ("generated_at", "title", "summary", "highlights", "learned")}
                previous_opportunities = prev.get("opportunities") or []
            except (OSError, ValueError):
                # No previous run to diff against — which is what a first generation
                # for this card looks like.
                pass
        framing = dict(question=question, feedback=feedback,
                       hypothesis_budget=hypotheses.budget(),
                       knowledge=knowledge, previous=previous,
                       findings=findings_store.prompt_block(),
                       # What brAIn measured. Its own budget (HOUSE_CHARS),
                       # taken from nothing else, and empty on a house
                       # where nothing is ready yet.
                       house=await _house_prompt_block(),
                       refine=refine or None)

        result = cost = sent = None
        if eff_gather_mode() == "search":
            result, cost, sent = await _search_run(insight_id, cat, framing)
        if result is not None and _no_fallback(result):
            # The snapshot is the floor under a search that could not FIND
            # its answer — tools that misbehaved, turns that ran out. It
            # is no floor under a search the account or the service
            # refused: a rejected credential, a usage limit and an
            # overloaded API refuse the snapshot exactly the same way, so
            # running it bought a second refusal at the snapshot's price
            # and held the queue for both.
            raise RuntimeError(result.get("error") or "the search run failed")
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
            result, cost, sent = await _snapshot_run(insight_id, cat, framing)
        if not result["ok"]:
            raise RuntimeError(result["error"] or "generation failed")

        _set_job(insight_id, state="parsing")
        obj = _answer(result)
        if not obj or not isinstance(obj.get("html"), str) or not obj.get("title"):
            raise RuntimeError("Claude returned an unparseable insight (no JSON/html)")
        # The design system is a stylesheet the card is written against,
        # injected once here rather than re-sent as hex in every prompt.
        html = inject_styles(obj["html"])
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
        # The run id is Claude Code's own session id for this invocation —
        # already minted, already claimed in `run_sources`, already on the
        # journal line. Carrying it onto the row is what lets an ENDING be
        # joined back to the prompt that earned it, which is the label half
        # of the corpus. A run whose CLI returned no session id simply has
        # no id here, and nothing downstream pretends otherwise.
        run_id = capture.run_id_from(result.get("meta") or {})
        model_findings = _model_findings(obj.get("findings"))
        # Gated like every other producer. This run read the house — and
        # it was asked to write a card, not to decide whether what it
        # noticed on the way past belongs on a list of decisions, which
        # are two different jobs and only one of them has been done here.
        # Nothing is announced from this call site any more: a `triaging`
        # row must not ring a phone, and the drain announces what it puts
        # on the list.
        filed = findings_store.add_many(triage.gate([
            {**f, "source": cat["id"], "source_title": cat.get("title", "Insight"),
             "run_id": run_id}
            for f in model_findings]))
        tags = card_tags.clean_tags(_clean_strings(obj.get("tags"), 4, 24))
        opportunities = await _offer_card_opportunities(
            insight_id, _card_opportunities(obj.get("opportunities")),
            previous_opportunities)
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
            # The entities whose CURRENT state the visualization wants,
            # so a card about something happening now stops being frozen
            # at the moment it was generated. Validated here and kept on
            # the card, which is what makes it the ONLY thing the live
            # route will serve for this card: the list is fixed when the
            # card is written, so a stored `html` cannot later ask the
            # panel for an entity its author never declared.
            "live": _clean_entity_ids(obj.get("live"), MAX_LIVE_ENTITIES),
            # What it says this house is missing, and whether each was
            # offered on Proposals (see `_offer_card_opportunities`).
            "opportunities": opportunities,
            "html": html,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # Why this run happened, in the words the person who reads
            # the card would use. A card that cannot say why it is here
            # is a card that reads as a timer going off — which for two
            # releases is exactly what it was.
            "made_because": _because_of(job, question),
            # `cost` is derived once, here, and stored — not recomputed in the
            # panel from `usage`. Which fields count against a session window
            # (and that a cache read does not) is a rule usage_store owns; a
            # second copy of it in JavaScript is a second answer waiting to
            # drift from the one the budget actually uses.
            "meta": {**result.get("meta", {}), "cost": cost},
        }
        # Learn the durable discoveries: store NEW ones in our own knowledge
        # base (dedup by content) and hand those on to the home's shared
        # memory. Already-known ones are silently swallowed — the model was
        # told not to repeat them, this enforces it.
        learned_now = 0
        for fact in learned:
            _, created = knowledge_store.add_fact(
                fact, source="insights", category=cat["id"])
            if created:
                # With the run that learned it, so "See the run" on the
                # Knowledge tab opens the card's own conversation.
                await _submit_memory(fact, run_id=run_id or "")
                learned_now += 1
        # What the next run will be compared against. Taken AFTER the run
        # rather than before it: the question the gate asks is "has
        # anything moved since this card was made", and a fingerprint
        # from before a run that itself filed findings would answer it
        # about the wrong instant. And after this card's own learned facts
        # have reached the facts store, for the same reason: they are what
        # the run said, not something that happened to the house since.
        if question is None:
            if learned_now:
                await asyncio.to_thread(_ingest_facts)
            fingerprint = await _current_inputs(cat["id"], cat)
            if fingerprint:
                insight["inputs_fingerprint"] = fingerprint
        save_insight(insight)
        # What was sent, what came back, and — later, when somebody ends one
        # of the findings above — what they made of it. Off unless somebody
        # switched it on in ⚙, redacted on the way in, and never leaving
        # /data until a person exports it.
        if settings_store.load().get("capture") and run_id and sent:
            await asyncio.to_thread(
                capture.record, run_id,
                source="ask" if question is not None else "card",
                category=insight["category"], question=question or "",
                model=str(result.get("meta", {}).get("model")
                          or eff_model() or ""),
                gather_mode=sent["gather_mode"],
                prompt_chars=sent["prompt_chars"], bundle=sent["bundle"],
                # The card's findings and what it learned, plus the fields a
                # person reads. Never the `html`: that is a rendered
                # visualization of up to 200 KB, and what a corpus scores is
                # the findings.
                reply={"title": insight["title"], "summary": insight["summary"],
                       "highlights": insight["highlights"], "learned": learned,
                       "findings": model_findings,
                       "hypotheses": _clean_strings(obj.get("hypotheses"), 3, 300),
                       "tags": tags, "html_bytes": len(html.encode())},
                tokens=cost or {})
        CARD_FAILURES.pop(insight_id, None)
        _set_job(insight_id, state="done", error="")
        log.info("insight %s generated (%s)%s%s", insight_id, insight["title"],
                 f", {len(filed)} new finding(s)" if filed else "",
                 f", {accepted} hypothesis(es) queued" if accepted else "")
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        log.warning("insight %s failed: %s", insight_id, exc)
        journal.record("insight", journal.classify({"ok": False, "error": str(exc)}),
                       error=str(exc), extra={"id": insight_id})
        # The scheduler backs off from this card until a run succeeds.
        _note_card_failure(insight_id, str(exc))
        _set_job(insight_id, state="error", error=str(exc)[:500])


def _no_fallback(result: dict) -> bool:
    """Did a search run fail in a way the snapshot would fail too?"""
    if result.get("ok"):
        return False
    if engine.overloaded(result):
        return True
    return journal.classify(result) in ("auth", "rate_limited")


# ---------------------------------------------------------------------------
# Fix workers — the plan, and the one path that lets Claude change the house
# ---------------------------------------------------------------------------

# The brief a plan run is handed when a conversation agreed the change.
PLAN_CHANGE_MAX = 600
PLAN_AGREED = (
    "WHAT THE HOMEOWNER AGREED TO, in a conversation with you about this "
    "finding — plan exactly this change, or say plainly why it cannot or "
    "should not be made:\n{change}")


async def _run_plan(job_id: str) -> None:
    """Work out what fixing one finding WOULD change, and change nothing.

    This is what pressing Fix it now buys, and the split is the whole
    point: a tool-enabled run at somebody's house used to start on the
    press, with nothing on screen first about which entity, which file or
    which automation was about to move. So the press buys a sentence, and
    the change waits for a second one.

    It is `run_analyst` and never `run_agent` — read-only by construction
    rather than by instruction, because a prompt that says "change
    nothing" is a promise a model keeps and a tool list is a promise the
    CLI keeps. It claims the `fix` run source like the run it precedes,
    since the Chats rail reads them as one face. It rides the generation
    queue, and the run itself takes a PRESS seat on the Claude run queue
    (`run_queue`) — the bound across every run the panel makes, which is
    what protects a subscription's rate limit now that the generation
    worker is no longer the only thing that spawns one.

    Every ending leaves the row somewhere a person can act: a plan that
    parsed lands on the card as `planned`, and a run that failed puts the
    row back to `open` with the reason, because a finding wedged in
    `planning` is one no button is offered on.
    """
    job = JOBS.get(job_id, {})
    ts = int(job.get("finding_ts") or 0)
    finding = findings_store.get(ts)
    if finding is None:
        _set_job(job_id, state="error", error="that finding is gone")
        return
    try:
        # the route already claimed it on disk — this is the in-memory half
        _set_job(job_id, state="planning", error="")
        memory = await asyncio.to_thread(_read_shared_memory)
        change = str(job.get("change") or "").strip()
        prompt = fixer.build_plan_prompt(
            finding, memory=memory,
            protected=automation_writer.protected_patterns(),
            context=(PLAN_AGREED.format(change=change) if change else ""))
        result = await _claude(
            engine.run_analyst, prompt, fixer.PLAN_SYSTEM, eff_model(),
            PLAN_TIMEOUT_S, PLAN_MAX_TURNS, "fix",
            job="fix_plan", schema=fixer.PLAN_SCHEMA, priority=run_queue.PRESS)
        _record_usage(result, job_id)
        if not result["ok"]:
            raise RuntimeError(result["error"] or "the plan run failed")

        plan = fixer.parse_plan(result["text"], result.get("data"))
        row = await asyncio.to_thread(findings_store.set_plan, ts, plan)
        if row is None:
            # The finding was settled, or somebody pressed Cancel, while
            # the run was out. `record_triage`'s rule: a verdict arriving
            # late about a row that has moved on must not drag it back.
            _set_job(job_id, state="done", error="")
            log.info("plan for finding %s arrived after the row moved on", ts)
            return
        _set_job(job_id, state="done", error="")
        log.info("finding %s planned: %s", ts,
                 f"{len(plan['steps'])} step(s)" if plan["can_fix"]
                 else "brAIn would not make this change itself")
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        # No journal line here: `engine._run_cli` already records every `-p`
        # run whatever happened to it, and a second one would count this
        # failure twice — `_run_fix`'s arrangement, for its reason.
        log.warning("planning finding %s failed: %s", ts, exc)
        # Best-effort, and that is load-bearing: this is the error path,
        # and a store write that raised here (a full or read-only /data —
        # `atomic_write` re-raises the OSError) used to escape it and take
        # the generation worker down with it. The job still says why.
        try:
            await asyncio.to_thread(
                findings_store.set_status, ts, "open",
                f"brAIn could not work out what to change: {str(exc)[:400]}")
        except Exception as store_exc:  # noqa: BLE001 — see above
            log.warning("could not put finding %s back to open: %s",
                        ts, store_exc)
        _set_job(job_id, state="error", error=str(exc)[:500])


def _close_fix_window(ts: int, started: float, ended: float) -> None:
    """Stamp the end of a fix run and what it changed, in one write.

    Blocking on purpose — it reads two files — so it is called through a
    thread like every other store write on this path. It never raises: a
    count that could not be taken is a card that says nothing about what
    the run touched, where a raise here would report a fix that worked as
    one that failed.
    """
    try:
        files = len(unfix.journal_entries(started, ended))
        calls = len(unfix.service_calls(started, ended))
    except Exception as exc:  # noqa: BLE001 — accounting, not the fix
        log.debug("could not count what the fix changed: %s", exc)
        files = calls = None
    findings_store.set_fix_window(ts, None, ended, files=files, calls=calls)


async def _run_fix(job_id: str) -> None:
    """Fix one finding, agentically, because somebody pressed Apply on a plan.

    It rides the generation queue, and its run takes a PRESS seat on the
    Claude run queue (`run_queue`): there is no longer one invocation at a
    time across the add-on — the Resident, triage, a Reply and the brief
    all spawn runs of their own — so the bound and the order live there,
    and a press is never queued behind scheduled work.

    The run is told to carry out the steps a person read rather than to
    work out its own — and the window it ran in is stamped on the row
    either side of it, because the edit journal and the action ledger are
    both append-only files in epoch seconds, so "what did this fix change"
    is answerable only as "what they recorded between these two instants"
    (`unfix.py`). The start goes to disk BEFORE the run, so a panel that
    dies mid-fix still leaves a window somebody can ask about.
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
        # The protected list rides in the prompt because this is the one
        # Claude path with a shell and a file editor, and neither of
        # those passes the MCP chokepoint the list is enforced at. Read
        # through `automation_writer.protected_patterns`, which is the
        # single reader of the option — a second parse would be a second
        # answer to "is this entity protected".
        prompt = fixer.build_prompt(
            finding, memory=memory,
            protected=automation_writer.protected_patterns(),
            plan=finding.get("plan") or {})
        started = time.time()
        await asyncio.to_thread(findings_store.set_fix_window, ts,
                                started, None)
        result = await _claude(
            engine.run_agent, prompt, fixer.FIX_SYSTEM, eff_model(),
            FIX_TIMEOUT_S, FIX_MAX_TURNS, "fix",
            job="fix_apply", schema=fixer.RESULT_SCHEMA,
            priority=run_queue.PRESS)
        # Counted here and stored, rather than on every fetch of the tab:
        # see `findings_store.set_fix_window`. This is also the last moment
        # at which the count is certainly about this run and nothing else.
        await asyncio.to_thread(_close_fix_window, ts, started, time.time())
        _record_usage(result, job_id)
        if not result["ok"]:
            raise RuntimeError(result["error"] or "the fix run failed")

        parsed = fixer.parse_result(result["text"], result.get("data"))
        if parsed["needs_you"]:
            status = "needs_you"
        elif parsed["ok"]:
            status = "fixed"
        else:
            status = "failed"
        findings_store.set_status(ts, status, result=fixer.result_text(parsed),
                                  changed=parsed["changed"])
        if status == "fixed":
            # The run's own reading of what it did is not the check that
            # filed the row: that check is asked again once the change has
            # had a moment to land, and a fault it still sees reopens the
            # row as having come back (`_verify_fix`).
            _spawn_fix_verification(ts)
        # A change to the house is durable knowledge about it — the next
        # analysis must not rediscover a problem brAIn itself resolved.
        if status == "fixed" and parsed["changed"]:
            subjects = _finding_subjects(finding)
            await _submit_memory(
                f"brAIn fixed this on {time.strftime('%Y-%m-%d')}: "
                f"{finding['text']} — {'; '.join(parsed['changed'])}",
                source="fix", subject=subjects[0] if subjects else "",
                subjects=subjects[1:],
                run_id=capture.run_id_from(result.get("meta") or {}))
        # Anything it noticed on the way in becomes its own finding rather
        # than an edit it was not asked to make — and goes through triage
        # like every other producer's, because "I saw this while I was in
        # there" is the most side-channel of all the side channels.
        also = findings_store.add_many(triage.gate([
            {"text": extra, "source": "fix",
             "source_title": f"Noticed while fixing “{finding['text']}”"}
            for extra in parsed["also_found"]]))
        if also:
            log.info("the fix run also filed %d finding(s) for triage",
                     len(also))
        _set_job(job_id, state="done", error="")
        log.info("finding %s → %s", ts, status)
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        log.warning("fix for finding %s failed: %s", ts, exc)
        # Close the window on the way out too. A run that timed out may
        # have edited a file before it died, and a window with no end is
        # a question nothing can answer afterwards — the row will say
        # `failed` rather than offering the Undo, but what the run touched
        # is still bounded on disk for `brain undo` and for a report.
        # Both best-effort, for `_run_plan`'s reason: a store write that
        # raises on the error path is what used to kill the worker.
        try:
            findings_store.set_fix_window(ts, None, time.time())
            findings_store.set_status(
                ts, "failed",
                result=f"The fix run did not complete: {str(exc)[:400]}")
        except Exception as store_exc:  # noqa: BLE001 — see above
            log.warning("could not record the failed fix on finding %s: %s",
                        ts, store_exc)
        _set_job(job_id, state="error", error=str(exc)[:500])


# How long after a fix the check that filed the row is asked again. Past
# `findings_store.FIX_SETTLE_S` on purpose: a row is only called back once
# the change has had its settling moment.
FIX_VERIFY_DELAY_S = 180
_FIX_VERIFICATIONS: set = set()


def _spawn_fix_verification(ts: int) -> None:
    """Ask the originating check again, later, without holding anything up.

    Kept in a set so the task is not collected mid-sleep (the loop holds
    only a weak reference to a task), and dropped from it when done.
    """
    async def later() -> None:
        try:
            await asyncio.sleep(FIX_VERIFY_DELAY_S)
            await _verify_fix(ts)
        except asyncio.CancelledError:
            # The panel is shutting down; the next scheduled pass of the
            # same check is the verification this one would have been.
            pass
        except Exception as exc:  # noqa: BLE001 — a verification, not the fix
            log.debug("could not verify the fix for %s: %s", ts, exc)
    try:
        task = asyncio.get_running_loop().create_task(later())
    except RuntimeError:
        return              # no loop: a caller outside the panel's own
    _FIX_VERIFICATIONS.add(task)
    task.add_done_callback(_FIX_VERIFICATIONS.discard)


async def _verify_fix(ts: int) -> dict:
    """Run the check that filed a row brAIn just fixed, and believe it.

    What makes `fixed` a claim about the house rather than about a run.
    Only a house check's row can be verified this way — a model's report
    has no rule to re-run — and only a check that RAN may answer: a
    snapshot key that would not fetch is "I could not look", which leaves
    the row exactly as the fix left it. The answer goes through
    `clear_resolved`, the same door the scheduled pass and "Check again"
    use, so the reopen (`findings_store._came_back`) and the answer's
    lapse are one rule with three callers rather than three rules.
    """
    finding = await asyncio.to_thread(findings_store.get, ts)
    if finding is None or finding.get("status") != "fixed":
        return {"checked": False, "why": "the row moved on"}
    source = str(finding.get("source") or "")
    check_id = source[6:] if source.startswith("check:") else ""
    if (not check_id or checks.get_check(check_id) is None
            or checks.is_shadow(check_id)):
        return {"checked": False, "why": "not a house check's row"}
    if CHECKS_STATE["running"]:
        # That pass is about to answer the same question.
        return {"checked": False, "why": "a checks pass is running"}
    started = time.time()
    snapshot = await checks.snapshot.collect(started)
    result = checks.run_all(snapshot, started, only=[check_id])
    if check_id not in result["ran"]:
        return {"checked": False,
                "why": (result["skipped"].get(check_id)
                        or result["errors"].get(check_id)
                        or "it could not run")}
    keys = {findings_store.normalize(f["text"]) for f in result["findings"]}
    await asyncio.to_thread(findings_store.clear_resolved,
                            {checks.source_for(check_id)}, keys)
    still = findings_store.normalize(finding.get("text", "")) in keys
    if still:
        log.info("finding %s came back: %s still reports it after the fix",
                 ts, check_id)
    return {"checked": True, "came_back": still}


# ---------------------------------------------------------------------------
# Milestone cards — the day a measurement first has an answer
# ---------------------------------------------------------------------------

def _milestone_payloads() -> dict:
    """Each measurement's own file, for the predicates that need the rows.

    The aggregate carries counts; three of the seven ask something the
    counts cannot answer (which closures have a full day of watching,
    what each room's time constant is, what each machine idles at), and
    a store that will not load is an empty payload rather than a failed
    pass — its predicate then reads it as not ready, which is the honest
    answer to "I could not look".
    """
    loaders = {"rhythm": rhythm.load, "baselines": baselines.load,
               "thermal": thermal.load, "closures": closures.load,
               "appliances": appliances.load, "habits": routines.load}
    out = {}
    for name, load in loaders.items():
        try:
            out[name] = load()
        except Exception as exc:  # noqa: BLE001 — one store, not the pass
            log.debug("milestones: could not read %s: %s", name, exc)
            out[name] = {}
    return out


def _milestone_job_id(mile_id: str) -> str:
    return f"milestone-{mile_id}"


async def _offer_milestones(now: float) -> int:
    """Queue a card for every milestone that has just become true.

    Runs in the checks pass, after the nightly build has had its chance
    to write the stores — the same place every other producer is called,
    because "what has become knowable" is a question about the same
    snapshot the checks just read.
    """
    # A milestone card is a Claude run, so it answers to the same three
    # gates scheduled generation does. Checked BEFORE the table is
    # evaluated, and nothing is settled by a pass that could not run: a
    # milestone is armed until a card exists, so a paused house simply
    # gets the card on the pass after it is unpaused.
    settings = settings_store.load()
    if not engine.get_auth() or not settings["auto_enabled"]:
        return 0
    if usage_store.budget_state(settings)["blocked"]:
        return 0
    snapshot = await _house_snapshot(now)
    payloads = await asyncio.to_thread(_milestone_payloads)
    due = await asyncio.to_thread(milestones.due, snapshot, payloads, now)
    queued = 0
    for entry in due:
        if _enqueue(_milestone_job_id(entry["id"]), kind="milestone",
                    milestone=entry["id"], prompt=entry["prompt"],
                    mark=entry["mark"], because=entry["made_because"],
                    title=entry["title"]):
            queued += 1
            log.info("milestone: queued a card for %s (%s)",
                     entry["id"], entry["made_because"])
    return queued


async def _run_milestone(job_id: str) -> None:
    """One milestone card: the store's numbers, one analyst turn, one file.

    It shares the generation queue like a fix run, and its run takes a
    SCHEDULED seat on the Claude run queue (`run_queue`), which is the
    bound across every run the panel makes — and it uses `run_analyst`
    (reading tools only) for the reason every unattended run does.
    """
    job = JOBS.get(job_id, {})
    mile_id = str(job.get("milestone") or "")
    entry = milestones.get(mile_id)
    if entry is None:
        _set_job(job_id, state="error", error="unknown milestone")
        return
    try:
        _set_job(job_id, state="generating", error="")
        result = await _claude(
            engine.run_analyst, job.get("prompt") or "", ANALYST_SYSTEM,
            eff_model(), eff_timeout_s(), ANALYST_MAX_TURNS, "card",
            job="milestone", schema=CARD_SCHEMA)
        _record_usage(result, job_id)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "generation failed")
        obj = _answer(result)
        if not obj or not obj.get("title"):
            raise RuntimeError("Claude returned an unparseable card")
        card = await asyncio.to_thread(
            milestones.save_card, mile_id, obj, job.get("mark") or {},
            str(job.get("because") or ""))
        # What the run says it learned, through the same door a card's
        # `learned` goes: the knowledge ledger (so nothing is announced
        # twice) and then the memory inbox. A milestone is the moment a
        # measurement first has an answer, and the sentence the model
        # wrote about that answer was requested by the contract and
        # dropped on the floor. Its findings stay dropped on purpose —
        # the milestone frame tells it never to turn this into a problem
        # report.
        run_id = capture.run_id_from(result.get("meta") or {})
        for fact in _clean_strings(obj.get("learned"), 3, 500):
            _, created = await asyncio.to_thread(
                knowledge_store.add_fact, fact, "insights",
                f"milestone:{mile_id}")
            if created:
                await _submit_memory(fact, run_id=run_id or "")
        _set_job(job_id, state="done", error="")
        log.info("milestone card written: %s (%s)", mile_id, card["title"])
    except Exception as exc:  # noqa: BLE001 — job errors surface in the UI
        # Deliberately NOT settled: a milestone whose card failed is a
        # milestone nobody has been told about, and the next pass should
        # try again. The settled key is written by `save_card`, which is
        # to say by success and nothing else.
        log.warning("milestone %s failed: %s", mile_id, exc)
        journal.record("insight", journal.classify({"ok": False, "error": str(exc)}),
                       error=str(exc), extra={"id": job_id})
        _set_job(job_id, state="error", error=str(exc)[:500])


# ---------------------------------------------------------------------------
# The panel's own loops, and whether each is still going
# ---------------------------------------------------------------------------
# Every long-lived task the panel starts is created through `_supervise`,
# which hangs a done-callback on it: a loop that raised, or returned, is a
# loop that has stopped for good, and the only trace it used to leave was
# an unretrieved-exception line at some later garbage collection — while
# `/api/status` went on saying "queued" about cards nothing would ever
# generate and the health verdict said ok. The worker and the loops that
# beat (`_beat`) also say when they last went round, so one that is alive
# and stuck is told apart from one that is fine. Read by
# `_loop_health` into `/api/diagnostics`, where `health.problems` turns a
# dead or stalled one into a state and a sentence.
LOOPS: dict[str, dict] = {}
# The job the generation worker is on, and since when. An idle worker
# blocks on its queue for hours and that is health; one on the same job for
# hours longer than any run is allowed is a worker that is stuck.
WORKER_STATE: dict = {"job": None, "since": 0.0}


def _supervise(name: str, coro, stall_after_s: float | None = None):
    """Start one long-lived loop, and find out if it ever stops."""
    now = time.time()
    task = asyncio.create_task(coro)
    LOOPS[name] = {"started_at": now, "beat_at": now, "alive": True,
                   "stall_after_s": stall_after_s, "error": "",
                   "task": task}
    task.add_done_callback(functools.partial(_loop_ended, name))
    return task


def _loop_ended(name: str, task: asyncio.Task) -> None:
    """A supervised loop finished. Cancelled is a shutdown; anything else is
    a loop that is never coming back, and it is said at warning with its
    reason rather than left to an unretrieved-exception line."""
    row = LOOPS.get(name)
    if row is None or row.get("task") is not task:
        # A loop from an earlier app ending after a new one took its name.
        return
    row["alive"] = False
    row["ended_at"] = time.time()
    if task.cancelled():
        row["stopped"] = True
        return
    exc = task.exception()
    if exc is not None:
        row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        log.warning("the %s loop died: %s", name, row["error"],
                    exc_info=(type(exc), exc, exc.__traceback__))
    else:
        row["error"] = "it returned, and it is meant to run for ever"
        log.warning("the %s loop stopped: %s", name, row["error"])


def _beat(name: str) -> None:
    """A supervised loop went round. Cheap on purpose: one dict write."""
    row = LOOPS.get(name)
    if row is not None:
        row["beat_at"] = time.time()


def _worker_busy_limit_s() -> float:
    """Longer than any job the worker runs may legitimately take.

    A card is a search and then possibly a snapshot, each on the
    generation timeout; a fix is its own timeout and its plan before it.
    Twice the longest of those, plus room for the checks around them, is
    a job that is not coming back.
    """
    try:
        gen = float(eff_timeout_s())
    except Exception:  # noqa: BLE001 — a diagnostics read, not a run
        gen = 480.0
    return 2 * max(2 * gen, FIX_TIMEOUT_S + PLAN_TIMEOUT_S) + 600


def _loop_health(now: float | None = None) -> dict:
    """Every supervised loop: alive or not, when it last went round, and
    (for the worker) what it is on. The numbers `health.problems` reads."""
    now = time.time() if now is None else now
    out: dict = {}
    for name, row in list(LOOPS.items()):
        task = row.get("task")
        if task is not None and task.get_loop().is_closed():
            # A loop from an app whose event loop has gone — a test, the
            # demo panel's first boot — says nothing about this one.
            continue
        entry = {
            "alive": bool(row.get("alive")),
            "stopped": bool(row.get("stopped")),
            "error": journal.scrub(row.get("error") or ""),
            "beat_age_s": int(now - float(row.get("beat_at") or now)),
            "stall_after_s": row.get("stall_after_s"),
        }
        if name == "worker":
            since = float(WORKER_STATE.get("since") or 0)
            entry["busy_s"] = int(now - since) if since else 0
            entry["busy_limit_s"] = int(_worker_busy_limit_s())
            entry["queued"] = QUEUE.qsize()
        out[name] = entry
    return out


async def _dispatch(job_id: str) -> None:
    kind = JOBS.get(job_id, {}).get("kind")
    if kind == "fix":
        await _run_fix(job_id)
    elif kind == "plan":
        await _run_plan(job_id)
    elif kind == "milestone":
        await _run_milestone(job_id)
    elif kind == "doctor":
        await _run_doctor_deep(job_id)
    elif kind == "rehearse":
        await _run_rehearsal(job_id)
    elif kind == "sweep":
        await _run_sweep(job_id)
    else:
        await _generate(job_id)


async def _worker() -> None:
    """The generation queue's one consumer, which must outlive its jobs.

    It had no `except`, so a handler that raised past its own error state
    ended the loop — and `_run_fix` and `_run_plan` write the findings
    store from inside their except blocks, where `atomic_write` re-raises
    an OSError: a full or read-only /data during one failed fix killed the
    worker for good, and cards, fixes and plans then queued for ever while
    `/api/status` said "queued" and health said ok. Now a handler that
    raises costs its own job and nothing else: the job is marked errored
    with the reason, the log says so at warning, and the next job runs.
    """
    while True:
        job_id = await QUEUE.get()
        WORKER_STATE.update(job=job_id, since=time.time())
        _beat("worker")
        try:
            await _dispatch(job_id)
        except Exception as exc:  # noqa: BLE001 — one job, never the worker
            log.warning("the %s job %s failed outside its own handling: %s",
                        JOBS.get(job_id, {}).get("kind") or "insight",
                        job_id, exc, exc_info=True)
            try:
                _set_job(job_id, state="error",
                         error=f"brAIn could not finish this: {exc}"[:500])
            except Exception:  # noqa: BLE001 — bookkeeping on the way out
                log.debug("could not mark %s errored", job_id, exc_info=True)
        finally:
            QUEUE.task_done()
            WORKER_STATE.update(job=None, since=0.0)
            _beat("worker")
            # `_set_job` sweeps every ordinary ending; this covers the one
            # that is not ordinary — a handler that raised past its own
            # error state — so nothing can leave a row behind by failing in
            # a way nobody wrote down.
            try:
                _prune_jobs()
            except Exception:  # noqa: BLE001 — a prune is housekeeping
                log.debug("could not prune finished jobs", exc_info=True)


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
    # Two things that are not a clock. `never` means nothing is
    # scheduled; a HOLD means the floor has passed and the scheduler is
    # waiting for something the card reads to move, which has no date —
    # so the honest answer is "not on a clock", with the hold's own
    # sentence beside it in the payload rather than a time that will
    # keep arriving and keep not happening.
    if eff_refresh_mode() == "never" or REFRESH_HOLDS.get(eff.get("id")):
        return None
    # A failing card's next run is its backoff's end at the earliest —
    # the same question `_refresh_due` asks first, asked "when".
    backoff = _card_backoff_until(str(eff.get("id") or ""))
    if backoff > now:
        due = _next_due({**eff, "id": ""}, generated_at, backoff)
        return None if due is None else max(due, backoff)
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


# ---------------------------------------------------------------------------
# What a card is a function of, and whether any of it has moved
# ---------------------------------------------------------------------------
# A card used to regenerate because a clock said so, which on a quiet
# house means a full-price Claude run producing the same card it produced
# yesterday — and a dashboard that changes on a timer rather than because
# something happened is one people stop reading, since nothing on it is
# ever news.
#
# So the interval is the FLOOR and the second condition is that something
# the card reads has actually changed since the stored run. Five inputs,
# hashed separately so the answer can say WHICH one moved — a card whose
# foot says "3 more findings on the list" is telling you why it is there,
# where "inputs changed" is a mechanism talking about itself.
#
# `findings` is the whole prompt block rather than a per-domain slice:
# there is no per-domain view of a finding, and inventing one here would
# be a second answer to "what is this finding about" living beside
# `findings_store`'s own. The cost is that a new finding anywhere lets
# every card past the floor, which is the conservative direction.
CARD_INPUT_PARTS = ("findings", "memory", "stores", "feedback", "focus")


def _sha1(text: str) -> str:
    import hashlib  # noqa: PLC0415 — one caller, and not on the hot path

    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:16]


def _memory_stamp(domains=()) -> str:
    """What this card would be TOLD about the house — as a digest.

    It used to be memory.md's mtime and size, and the consolidator rewrites
    the document on every pass that had anything queued — including the
    card's OWN learned facts — so the stamp moved daily whatever the
    document now said, and the gate was a 24-hour timer with extra steps.
    So: the facts store's retrieval for this card's domains (the set of
    facts, by id — `facts_store.retrieval_fingerprint`), and where the
    store has nothing to retrieve, the document's content, which is what
    the run is handed instead. A digest either way; nothing of the house
    leaves this function.
    """
    try:
        facts = facts_store.retrieval_fingerprint(domains=domains)
    except Exception:  # noqa: BLE001 — the document is the floor
        facts = ""
    if facts:
        return "facts:" + facts
    try:
        text = SHARED_MEMORY_FILE.read_text(encoding="utf-8")
    except OSError:
        # A missing document is a state, and a stable one: "none" is not
        # the same string as any real stamp, so writing the first fact
        # counts as a change.
        return "none"
    return "doc:" + _sha1("\n".join(document_lines(text)))


def _store_stamp(cat_id: str, snapshot: dict | None) -> str:
    """What this card's measurements SAY, never when they were last built.

    It hashed each store's `updated_at`, which is a build stamp: baselines,
    closures, appliances and thermal are rebuilt every night and rhythm is
    re-stamped on every checks pass, so a card past its floor had always
    "moved" — on a rebuild that changed nothing. Now a ready store is its
    state and the sentence the prompt's house block reads
    (`house_block`), and any other store is its state alone, because the
    prompt reads nothing else of it.
    """
    wanted = stores_for(cat_id)
    stores = (snapshot or {}).get("stores") or {}
    rows = {}
    for name, entry in sorted(stores.items()):
        if not isinstance(entry, dict) or (wanted is not None
                                           and name not in wanted):
            continue
        state = entry.get("state")
        rows[name] = ([state, " ".join(str(entry.get("summary") or "").split())]
                      if state == "ready" else [state])
    return json.dumps(rows, sort_keys=True)


def _card_inputs(cat_id: str, eff: dict, findings_text: str,
                 snapshot: dict | None, now: float | None = None) -> dict:
    """Everything the next run of this card would read, as a fingerprint.

    `findings_text` and `snapshot` are passed in rather than fetched,
    because the scheduler asks this of every category on one tick and
    both are whole-house reads: computing them per card would be the
    same answer fetched nine times.
    """
    feedback = [] if cat_id.startswith("custom-") else [
        f["text"] for f in feedback_store.list_feedback(cat_id)]
    parts = {
        "findings": _sha1(findings_text or ""),
        "memory": _memory_stamp(eff.get("domains") or ()),
        "stores": _sha1(_store_stamp(cat_id, snapshot)),
        "feedback": _sha1("\n".join(feedback)),
        "focus": _sha1(str(eff.get("focus") or "")),
    }
    return {
        "parts": parts,
        "hash": _sha1(json.dumps(parts, sort_keys=True)),
        # One number the sentence can be built from. Not part of the
        # hash — it is derived from the same text the `findings` part
        # already covers, and counting it twice would let a re-worded
        # finding read as a new one. The live rows another producer filed,
        # for the `findings` part's own reason.
        "open_findings": len([
            f for f in findings_store.list_all("live")
            if f.get("source") != cat_id]),
        "at": int(time.time() if now is None else now),
    }


def _inputs_change(stored: dict | None, current: dict) -> dict:
    """Has anything moved, and what would you tell somebody it was.

    A card with no stored fingerprint has moved by definition: it was
    made before this existed, or it has never been made, and both mean
    the next run is the first that can be compared against anything.
    """
    if not isinstance(stored, dict) or not stored.get("parts"):
        return {"moved": True, "why": "first run since inputs were tracked",
                "fingerprint": current}
    was, now_parts = stored["parts"], current["parts"]
    if was == now_parts:
        return {"moved": False, "why": "nothing it reads has changed",
                "fingerprint": current}
    changed = [p for p in CARD_INPUT_PARTS if was.get(p) != now_parts.get(p)]
    reasons = []
    if "findings" in changed:
        delta = int(current.get("open_findings") or 0) - \
            int(stored.get("open_findings") or 0)
        reasons.append(f"{delta} more finding(s) on the list" if delta > 0
                       else "the findings list changed")
    if "memory" in changed:
        reasons.append("memory was updated")
    if "stores" in changed:
        reasons.append("a measurement was rebuilt")
    if "feedback" in changed:
        reasons.append("your feedback changed")
    if "focus" in changed:
        reasons.append("its focus was rewritten")
    return {"moved": True, "why": "; ".join(reasons) or "inputs changed",
            "fingerprint": current}


# A card whose last scheduled run FAILED, per category id: how many times
# in a row, when, and how. A failing card used to be due again on the very
# next tick — no stamp, no backoff — so a card that fails fast failed every
# minute and one that fails slowly (an eight-minute search timeout, then
# the snapshot fallback) held the generation queue sixteen minutes in every
# seventeen, both spending each session window's budget until every other
# automatic run, the Resident included, paused behind it. So a scheduled
# run backs off exponentially from its last failure; a press is never held
# by this (`_refresh_due` is the scheduler's question, not the button's),
# and the first success clears it. In memory on purpose: a restart is a
# person acting, and the thing they most often did first is fix the cause.
CARD_FAILURES: dict[str, dict] = {}
CARD_BACKOFF_BASE_S = 15 * 60
CARD_BACKOFF_MAX_S = 12 * 3600


def _card_backoff_until(card_id: str) -> float:
    """When a failing card may next be run by the scheduler, or 0.0."""
    row = CARD_FAILURES.get(card_id)
    if not row:
        return 0.0
    count = max(1, int(row.get("count") or 1))
    wait = min(CARD_BACKOFF_BASE_S * 2 ** (count - 1), CARD_BACKOFF_MAX_S)
    return float(row.get("at") or 0) + wait


def _note_card_failure(card_id: str, error: str, now: float | None = None) -> None:
    now = time.time() if now is None else now
    row = CARD_FAILURES.get(card_id) or {"count": 0}
    CARD_FAILURES[card_id] = {
        "count": int(row.get("count") or 0) + 1, "at": now,
        "outcome": journal.classify({"ok": False, "error": error}),
        "error": journal.scrub(error)[:200]}


# The account said "not now". Every scheduled card run waits this out
# rather than asking again on the next tick: a usage limit is a window that
# resets, and a card queued into it spends nothing and answers nothing —
# but it does write a failure, ask again a minute later, and keep the
# window from ever looking quiet. It escalates 30 min, 1 h, 2 h, 4 h across
# a streak, and the first Claude run of any kind that succeeds ends it,
# because that is the account answering again. Fed by the journal (every
# run records itself there), so the chat or voice meeting the limit holds
# the cards too.
RATE_LIMIT_STATE: dict = {"until": 0.0, "streak": 0, "detail": ""}
RATE_LIMIT_PAUSE_S = 30 * 60
RATE_LIMIT_MAX_S = 4 * 3600


def _journal_rate_listener(row: dict) -> None:
    # Only rows a model actually ran for: `_generate` writes a second,
    # summary row about the same failure, and counting both would make
    # every limit a streak of two.
    if not isinstance(row, dict) or not journal.is_claude_run(row):
        return
    if row.get("outcome") == "rate_limited":
        streak = int(RATE_LIMIT_STATE.get("streak") or 0) + 1
        wait = min(RATE_LIMIT_PAUSE_S * 2 ** (streak - 1), RATE_LIMIT_MAX_S)
        RATE_LIMIT_STATE.update(
            streak=streak, until=float(row.get("ts") or time.time()) + wait,
            detail=str(row.get("error") or "")[:160])
    elif row.get("ok") and journal.is_claude_run(row):
        RATE_LIMIT_STATE.update(streak=0, until=0.0, detail="")


def _book_shell_usage(row: dict) -> None:
    """A shell run's tokens, into the ledger the budget estimate and the
    usage popover's breakdown read — the same `record_run` every panel run
    passes through, under the row's own time."""
    tokens = row.get("tokens")
    if isinstance(tokens, int) and tokens > 0:
        usage_store.record_run(tokens, str(row.get("source") or "shell"),
                               now=float(row.get("ts") or time.time()))


# What an in-process row meets on `journal.record`, less the nudge the
# command line already sent from the process that ran the model.
_SHELL_HANDLERS = (_book_shell_usage, _journal_report_listener,
                   _journal_rate_listener)


# Why the scheduler last held a card back, per category id. In memory
# and written by the tick, because computing a fingerprint for nine
# categories on every /api/status poll would be nine whole-house reads
# for an answer that changes when the house does. It is a READBACK of
# what the scheduler decided, which is exactly what "why did this card
# stop updating" is asking.
REFRESH_HOLDS: dict[str, dict] = {}


def eff_refresh_mode() -> str:
    mode = settings_store.load().get("refresh_mode")
    return mode if mode in settings_store.REFRESH_MODES else "changed"


def _refresh_due(eff: dict, generated_at: str, now: float,
                 change=None, mode: str | None = None) -> bool:
    """True when a category's stored insight should regenerate.

    Two conditions, and the first is a floor. A non-empty per-category
    schedule (fixed daily times) takes precedence; otherwise the age-based
    interval applies (per-category refresh_hours override, else global
    REFRESH_HOURS; 0 disables). A missing or unparseable timestamp counts
    as ancient, so first boot generates every enabled category.

    The second is `refresh_mode` (see settings_store.REFRESH_MODES): in
    the default `changed`, the floor having passed is not enough — one of
    the five things the card reads has to have moved too. `change` is
    that answer and may be a CALLABLE, evaluated only once the floor has
    passed: on most ticks no card has aged out, and computing a
    fingerprint for one that has not is a whole-house read for a question
    nobody asked.
    """
    if not eff.get("enabled", True):
        return False
    mode = mode or eff_refresh_mode()
    if mode == "never":
        return False
    # A card that failed last time waits out its backoff before the
    # scheduler tries it again (see CARD_FAILURES). Asked first, because
    # it is the cheapest question and the one that is about the run
    # rather than about the card.
    if now < _card_backoff_until(str(eff.get("id") or "")):
        return False
    schedule = eff.get("schedule")
    if isinstance(schedule, list) and schedule:
        if not _schedule_due(schedule, generated_at, now):
            return False
    else:
        hours = eff.get("refresh_hours")
        if hours is None:
            hours = eff_refresh_hours()
        if hours <= 0:
            return False
        gen = _parse_generated_at(generated_at) if generated_at else None
        if gen is not None and now - gen < hours * 3600:
            return False
    if mode == "always" or change is None:
        return True
    if callable(change):
        change = change()
    return bool((change or {}).get("moved"))


async def _scheduler() -> None:
    """Per-category auto-refresh: each tick, queue any enabled category whose
    stored insight has outlived its effective refresh interval (or whose
    scheduled run time has passed). Respects the ⚙ master switch and the
    session token budget — manual generation is never gated here."""
    budget_logged = False
    while True:
        await asyncio.sleep(60)
        _beat("scheduler")
        # Fold in what the CLI side found. This belongs on the tick rather
        # than on the Findings tab's own request: study sessions are the
        # other producer, and the badge that tells you to go look is served
        # by /api/status. Sweeping only on tab open made that circular — the
        # badge couldn't count a finding until you'd already visited.
        try:
            swept = await asyncio.to_thread(findings_store.sweep_inbox,
                                            triage.gate)
            if swept:
                log.info("swept %d finding(s) from study sessions", len(swept))
        except Exception as exc:  # never let this kill the loop
            log.debug("findings sweep failed: %s", exc)
        # And the memory inbox into the facts store — a READER of that
        # queue, never a second drain of it (the consolidator goes on
        # moving what it files). Every writer already goes through the
        # inbox, which is what makes one sweep cover voice, the chat, the
        # terminal, study, a correction and another add-on's line alike.
        await asyncio.to_thread(_ingest_facts)
        # The shell half's runs — study, the consolidator, the automation
        # listener, the memory extractor — wrote their journal rows from
        # their own processes, where none of the panel's listeners are.
        # They are booked here, through the same listeners, before any gate:
        # a failed consolidation is a report whatever the insights face says.
        try:
            await asyncio.to_thread(journal.book_shell_rows, _SHELL_HANDLERS)
        except Exception as exc:  # noqa: BLE001 — bookkeeping, never the tick
            log.debug("booking shell runs failed: %s", exc)
        # Home Assistant's UI editors save automations.yaml, scripts.yaml
        # and scenes.yaml as root, and the Supervisor makes a new add-on's
        # /addon_configs folder root's; hand them back to the claude user
        # about once a minute so the next edit never meets a permission
        # error. `maybe_sweep` gates itself and never raises.
        await asyncio.to_thread(ownership.maybe_sweep)
        # The drain that used to live here is the Resident's first look
        # now (`_resident_loop`), which reads the same `awaiting_triage()`
        # queue on its own five-second tick — so a row a study session just
        # filed reaches a judgement in seconds rather than at the top of
        # the next minute, and the one run that judges it also judges the
        # state changes and the overrides beside it. `_triage_findings` is
        # still here and still callable; what changed is that nothing
        # schedules it.
        # The face is off: nothing is queued, ever. Checked before the
        # auth gate on purpose — a switched-off face is the answer to "why
        # are my cards not updating" whatever the sign-in says.
        if not insights_enabled():
            _set_gate("insights_off")
            continue
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
        if time.time() < float(RATE_LIMIT_STATE.get("until") or 0):
            _set_gate("rate_limited",
                      "the account's usage limit said wait; cards resume at "
                      + time.strftime("%H:%M", time.localtime(
                          RATE_LIMIT_STATE["until"])))
            continue
        _set_gate(None)
        # The weekly top-up, past every gate above on purpose: proposing
        # cards for a house whose insights are switched off, whose
        # account is not connected or whose budget is spent is the rule
        # this loop already keeps for every other scheduled run. The
        # press skips the budget and this does not — "automatic
        # insights pause; asking by hand always runs" is one promise with
        # two halves, and `h_ideas_run` is the other.
        try:
            if ideas.due() and _start_ideas():
                log.info("ideas: weekly top-up started")
        except Exception as exc:  # noqa: BLE001 — a top-up must never
            # take the refresh loop down with it.
            log.debug("ideas top-up did not start: %s", exc)
        cards = {i["id"]: i for i in load_insights()}
        now = time.time()
        mode = eff_refresh_mode()
        # Fetched once per tick, not once per card: both are whole-house
        # reads and nine categories asking separately would be the same
        # answer nine times. Lazy, because on most ticks no card has
        # aged out and neither is needed at all.
        shared: dict = {}

        async def _inputs_for(cat_id: str, eff: dict) -> dict:
            if "house" not in shared:
                shared["house"] = await _house_snapshot(now)
            # Per card rather than shared: each one leaves its OWN rows
            # out, or a card's findings promoted by the Resident read as
            # news to the card that filed them (`prompt_block`).
            findings_text = await asyncio.to_thread(
                findings_store.prompt_block, (cat_id,))
            return await asyncio.to_thread(
                _card_inputs, cat_id, eff, findings_text,
                shared["house"], now)

        for cat in all_categories():
            eff = resolve_category(cat["id"]) or cat
            stored = cards.get(cat["id"]) or {}
            if not _refresh_due(eff, stored.get("generated_at", ""), now,
                                mode=mode):
                continue
            change = {"moved": True, "why": "on its refresh interval",
                      "fingerprint": None}
            if mode == "changed":
                try:
                    change = _inputs_change(
                        stored.get("inputs_fingerprint"),
                        await _inputs_for(cat["id"], eff))
                except Exception as exc:  # noqa: BLE001 — a gate that cannot
                    # read its inputs must not become a card that never
                    # refreshes: "I could not tell" falls through to the
                    # old behaviour, which is the interval alone.
                    log.debug("could not fingerprint %s: %s", cat["id"], exc)
                    change = {"moved": True,
                              "why": "its inputs could not be read",
                              "fingerprint": None}
            if not change["moved"]:
                REFRESH_HOLDS[cat["id"]] = {
                    "why": change["why"], "at": int(now)}
                continue
            REFRESH_HOLDS.pop(cat["id"], None)
            if _enqueue(cat["id"], because=change["why"]):
                log.info("auto-refresh: queued %s (%s)",
                         cat["id"], change["why"])


def _enqueue(job_id: str, question: str | None = None, **fields) -> bool:
    """Queue one unit of Claude work. ``fields`` carries per-kind state
    (``kind="fix"`` plus its ``finding_ts``); everything else is a card."""
    if _job_active(job_id):
        return False
    # A job dict outlives the run it described (`_set_job` merges), so the
    # per-run reasons are reset here: a refine note, or the scheduler's
    # sentence, left over from last time would otherwise be told to the
    # next plain Regenerate and written onto the card as why it happened.
    fields.setdefault("refine", "")
    fields.setdefault("because", "")
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
        result = await _claude(engine.validate_auth, priority=run_queue.PRESS)
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

def _read_json(path: Path) -> dict | None:
    """One stored JSON object, or None for "there is nothing readable here".

    A file that is missing and one that is half-written are the same answer
    to every caller here — a 404 — and both are what the handlers already
    did with `except (OSError, ValueError)`. It is a named function so the
    read can be handed whole to `asyncio.to_thread`: `open` and `json.loads`
    are the blocking halves, and splitting them across the loop would put
    one of them back on it.
    """
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


# The five files the panel serves as itself, held in memory once they have
# been read. They are baked into the image and cannot change under a running
# add-on, and a `read_text` in a coroutine is a disk read on the event loop —
# 300 KB of app.js on every hard refresh, on a Pi, while a checks pass is
# using the same disk. Cached against the file's own mtime and size so a
# developer editing them still sees the edit, and a miss is read off the
# loop; a hit costs a `stat`, which is the one thing here small enough to
# leave where it is.
STATIC_FILES = ("index.html", "style.css", "app.js", "docs.js", "favicon.svg")
_STATIC_CACHE: dict[str, tuple[tuple[int, int], str]] = {}


def _read_static(name: str) -> str:
    """One panel asset, from memory if it is the same file we last read."""
    if name not in STATIC_FILES:          # never a name off the wire
        raise web.HTTPNotFound(text="no such file")
    path = HERE / name
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    cached = _STATIC_CACHE.get(name)
    if cached is not None and stamp is not None and cached[0] == stamp:
        return cached[1]
    text = path.read_text(encoding="utf-8")
    if stamp is not None:
        _STATIC_CACHE[name] = (stamp, text)
    return text


def _warm_static() -> None:
    """Read the panel's own files once, at startup, off the loop."""
    for name in STATIC_FILES:
        try:
            _read_static(name)
        except OSError as exc:
            # A missing asset is a 404 at request time, which is a much
            # better place to notice it than a panel that will not start.
            log.warning("could not pre-read %s: %s", name, exc)


async def h_index(request: web.Request) -> web.Response:
    html = await asyncio.to_thread(_read_static, "index.html")
    html = html.replace("{{VERSION}}", ADDON_VERSION)
    return web.Response(text=html, content_type="text/html")


def _static(name: str, ctype: str):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(
            text=await asyncio.to_thread(_read_static, name), content_type=ctype,
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
            "refresh_hold": REFRESH_HOLDS.get(c["id"]),
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
        # Why the scheduler is waiting rather than when: with
        # `refresh_mode: changed` a card past its interval sits until
        # something it reads moves, and a `next_due` in the past would
        # keep promising a run that is not coming.
        "refresh_hold": REFRESH_HOLDS.get(c["id"]),
        "job": {k: JOBS.get(c["id"], {}).get(k) for k in ("state", "error")},
    }


# What brAIn did last and what it will do next, for the one poll every
# viewer already makes. Cached briefly because it reads four files and
# `/api/status` is a timer: none of these numbers moves inside twenty
# seconds, and a status poll that re-parses the run journal per viewer is
# the "refresh everything" button with a shorter interval.
TODAY_TTL_S = 20.0
_TODAY_CACHE: dict = {"at": 0.0, "state": None}


def _today_state(now: float | None = None) -> dict:
    """The last pass of each scheduled thing, and when the next one is due.

    Every number here is read from state that already exists — the checks
    summary, the baseline summary, the consolidator's marker, the reports
    directory and the run journal — because a second tally kept beside
    them would be a second answer to "did the checks run".
    """
    now = time.time() if now is None else now
    last = CHECKS_STATE["last"] or {}
    hours = eff_checks_interval_hours()
    finished = int(last.get("finished_at") or 0)
    built = int((baselines.load() or {}).get("built_at") or 0)
    try:
        recent = len([r for r in reports.list_reports()
                      if (r.get("ts") or 0) >= now - 86400])
    except Exception as exc:  # noqa: BLE001 — one number, not the payload
        log.debug("could not count reports: %s", exc)
        recent = 0
    return {
        "checks": {
            "last_at": finished or None,
            "ran": len(last.get("ran") or []),
            # A check that could not look did not find nothing, so the two
            # are counted apart here exactly as `clear_resolved` keeps them
            # apart: "12 ran, 3 skipped" and "15 ran" are different reports
            # of the same quiet house.
            "skipped": len(last.get("skipped") or {}),
            "errored": len(last.get("errors") or {}),
            "created": len(last.get("created") or []),
            "cleared": len(last.get("cleared") or []),
            # An interval of 0 is "not on a timer" — a date invented for
            # one would be a promise nothing is going to keep.
            "next_at": int(finished + hours * 3600)
            if finished and hours > 0 else None,
            "running": bool(CHECKS_STATE["running"]),
        },
        "baselines": {
            "built_at": built or None,
            "next_at": int(built + BASELINE_INTERVAL_S) if built else None,
            "running": bool(BASELINE_STATE["running"]),
            "error": str((BASELINE_STATE["last"] or {}).get("error") or ""),
        },
        "memory": {
            "last_filed_at": _last_consolidated() or None,
            "waiting": _inbox_pending(),
            "running": _consolidation_running(),
        },
        "reports": {"since_yesterday": recent},
        # Every Claude run and every checks pass that reached the journal.
        # It is what tells a quiet add-on from a stopped one.
        "landed_runs_24h": journal.summary(24.0, now).get("runs", 0),
    }


async def _today(now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if (_TODAY_CACHE["state"] is not None
            and now - float(_TODAY_CACHE["at"] or 0) < TODAY_TTL_S):
        return _TODAY_CACHE["state"]
    state = await asyncio.to_thread(_today_state, now)
    _TODAY_CACHE.update(at=now, state=state)
    return state


# `generated_at` per stored card, keyed on the file's own (mtime, size).
# `/api/status` is polled every few seconds by every viewer while a job
# runs, and it used to answer by JSON-parsing every stored card — up to
# 400 KB of HTML each — to read one timestamp out of each. A save rewrites
# the file and moves its mtime, which is the invalidation.
_GENERATED_AT_CACHE: dict[str, tuple[tuple[int, int], str | None]] = {}


def _generated_at(card_id: str) -> str | None:
    path = _insight_path(card_id)
    try:
        st = path.stat()
    except OSError:
        _GENERATED_AT_CACHE.pop(card_id, None)
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _GENERATED_AT_CACHE.get(card_id)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    obj = _read_json(path)
    value = obj.get("generated_at") if obj else None
    _GENERATED_AT_CACHE[card_id] = (stamp, value)
    return value


def _status_payload() -> tuple[dict | None, dict]:
    """Everything `/api/status` reads off disk, in one call off the loop.

    The credential stores, the settings file, the usage files, every
    category definition, a timestamp per card and four stores for the
    badge — synchronous reads all, and on an SD card each one is time the
    event loop is not serving the chat's stream or the terminal proxy.
    """
    auth = engine.get_auth()
    cats = all_categories()
    insights = {c["id"]: _generated_at(c["id"]) for c in cats}
    settings = settings_store.load()
    return auth, {
        "settings": settings,
        "usage": usage_store.budget_state(settings),
        "model": eff_model() or "default",
        "refresh_hours": eff_refresh_hours(),
        "history_days": eff_history_days(),
        "categories": [_category_status(c, insights) for c in cats],
        "findings_open": cases.open_count(),
    }


async def h_status(request: web.Request) -> web.Response:
    auth, read = await asyncio.to_thread(_status_payload)
    # Re-earn a verdict that has gone stale. Lazy on purpose — see
    # AUTH_RECHECK_S: this is the one path a person looking at the panel
    # already drives, so the cost lands where somebody is asking and
    # nowhere else. `start_auth_check` is the guard against the poll
    # spawning a second check over an unfinished one — and it stays on
    # the loop, because it flips its guard synchronously.
    if auth and _auth_verdict_is_stale():
        start_auth_check(announce=False)
    settings = read["settings"]
    return web.json_response({
        "version": ADDON_VERSION,
        "authenticated": bool(auth),
        "auth_type": auth["type"] if auth else None,
        "auth_source": auth.get("source") if auth else None,
        "auth_check": AUTH_CHECK,
        "model": read["model"],
        "refresh_hours": read["refresh_hours"],
        "history_days": read["history_days"],
        "settings": settings,
        "usage": read["usage"],
        # Why auto-refresh is idle, when it is — the same gates the chips
        # and the pill's dot report, readable as one field.
        "auto": dict(AUTO_STATE),
        # `enable_insights` off hides the Insights and Proposals tabs.
        "insights_enabled": insights_enabled(),
        "categories": read["categories"],
        # The Findings tab's badge: everything still waiting on a decision —
        # problems to settle and guesses to confirm, which are one list now.
        # Counted here rather than off _findings_payload() because /api/status
        # polls on a timer and open_count() reads raw entries without shaping
        # 200 findings to throw all but the length away.
        # What the badge counts, and it is the CASE count: one badge over
        # the four stores, because "how much is waiting on me" has one
        # answer and a second derivation in the panel is the one that
        # disagrees while somebody is looking. `cases.open_count` is that
        # derivation, and it spans the proposals and the accepted chores
        # the old sum did not.
        "findings_open": read["findings_open"],
        # What brAIn did last and what it will do next. On the poll every
        # viewer already makes, because "is this thing working" is asked
        # of the top bar and not of a tab.
        "today": await _today(),
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
            # The heading an asked card carries in place of "Custom". A
            # category card is headed by its category, which the panel
            # reads live off the definition so a rename shows at once.
            if str(ins.get("id") or "").startswith("custom-"):
                ins["eyebrow"] = card_tags.eyebrow(ins, ins["tags"])
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
    r"remind me when|every time|each time|any time|always|from now on)\b",
    re.IGNORECASE)

# ...and the half of that opener which is a QUESTION. "when did the boiler
# last run?" starts with the same word as "when the guests leave, turn the
# porch light off", so `INTENT_RE` alone sent it down the one-off path,
# where it spent a Claude run to produce a refusal card instead of
# answering. The signal is one word further along: an **auxiliary verb
# straight after the opener** ("when *did* …", "once *was* …") is somebody
# asking, and an instruction never has one there — "when the guests leave"
# and "tell me when the dishwasher is done" both put a noun phrase next.
# Cheaper and more honest than trailing-`?` detection, which nobody types
# on a phone.
INTENT_QUESTION_RE = re.compile(
    r"^(?:please )?(?:when(?:ever)?|once)\s+"
    r"(?:did|do|does|was|were|is|are|will|would|should|can|could|has|"
    r"have|had|am)\b",
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
        if INTENT_RE.match(question) and not INTENT_QUESTION_RE.match(question):
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
    # Regenerating an asked card in place. It used to be re-asked, which
    # made a SECOND card and left the first where it was — two copies of
    # one answer, and the refinements on the first one lost to the second.
    card_id = str(body.get("id") or "")
    if card_id.startswith("custom-"):
        stored = await asyncio.to_thread(_read_json, _insight_path(card_id))
        asked = (stored or {}).get("question") or " ".join(
            str(body.get("question") or "").split())
        if not asked:
            raise web.HTTPNotFound(text="no such card")
        started = _enqueue(card_id, question=str(asked)[:500])
        return web.json_response({"queued": [card_id] if started else []})
    cat_id = body.get("category", "")
    if not resolve_category(cat_id) or prompt_store.is_hidden(cat_id):
        raise web.HTTPBadRequest(text="unknown category")
    started = _enqueue(cat_id)
    return web.json_response({"queued": [cat_id] if started else []})


async def h_insight_refine(request: web.Request) -> web.Response:
    """Regenerate one card with a change the homeowner asked for.

    The whole of editing a card by saying what should be different: the
    sentence goes to the run as the reason it exists, beside the card as
    it stands, so what comes back is THAT card changed rather than a new
    answer to the old question. `remember` (the default) also keeps it as
    standing feedback on the card, so the next scheduled or pressed run
    does not quietly undo it — one store for both kinds of card, because
    "things I have told this card" is one list whoever made the card.
    """
    card_id = request.match_info["id"]
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    note = " ".join(str(body.get("note") or "").split())
    if not note:
        raise web.HTTPBadRequest(text="say what should change")
    if len(note) > feedback_store.MAX_CHARS:
        raise web.HTTPBadRequest(
            text=f"keep it under {feedback_store.MAX_CHARS} characters")
    remember = body.get("remember", True) is not False
    question = None
    if card_id.startswith("custom-"):
        stored = await asyncio.to_thread(_read_json, _insight_path(card_id))
        if stored is None or not stored.get("question"):
            raise web.HTTPNotFound(text="no such card")
        question = str(stored["question"])[:500]
    elif not resolve_category(card_id) or prompt_store.is_hidden(card_id):
        raise web.HTTPNotFound(text="no such card")
    if _job_active(card_id):
        raise web.HTTPConflict(
            text="This card is already being generated — refine it once "
                 "that run has finished.")
    card = _feedback_category(card_id)
    if remember:
        entry = await asyncio.to_thread(
            feedback_store.add_feedback, card_id, note)
        fact = (f'Homeowner feedback on the "{card["title"]}" insight card: '
                f'{entry["text"]}')
        knowledge_store.add_fact(fact, source="feedback", category=card_id)
        await _submit_memory(fact)
    _enqueue(card_id, question=question, refine=note)
    return web.json_response({
        "queued": [card_id], "remembered": remember,
        "feedback": feedback_store.list_feedback(card_id)})


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
    insight = await asyncio.to_thread(_read_json, path)
    if insight is None:
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
    await asyncio.to_thread(atomic_write.write_json, path, insight)
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


# ---------------------------------------------------------------------------
# A card that is about NOW, and is not frozen at the moment it was made
# ---------------------------------------------------------------------------
#
# An insight card is one Claude run rendered to a self-contained HTML
# document, and the document is written once. That is right for most
# cards — "last week's energy" does not change — and wrong for the ones
# people most want on a dashboard: a door that is open, a machine that is
# running, a room being held at a temperature. Those read as current and
# are not, which is the half of issue #300 that says "pull real time data
# from HA without it being a static card".
#
# The entity list is the card's OWN, fixed when the card was written
# (`_clean_entity_ids` at generation). This route will serve nothing
# else, and that is the whole security argument: the frame is a
# sandboxed `srcdoc` running model-authored script, and a route that took
# entity ids from the caller would let that script read any entity in the
# house through the panel's credential. It cannot ask for one its author
# did not declare, and its author is the run a person asked for.
#
# What comes back is deliberately small — state, unit, device class,
# friendly name, and `attributes` — because the visualization already has
# its shape and needs only the numbers. `last_changed` rides along because
# "on since 6:42" is the commonest thing such a card says.
async def h_insight_live(request: web.Request) -> web.Response:
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    insight_id = request.match_info["id"]
    try:
        card = json.loads(_insight_path(insight_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise web.HTTPNotFound(text="no such card") from None
    wanted = _clean_entity_ids(card.get("live"), MAX_LIVE_ENTITIES)
    if not wanted:
        # Not an error: most cards are about a period that has ended and
        # declare nothing. The panel reads the empty list and stops asking.
        return web.json_response({"states": {}, "poll_s": 0})

    rows = await ha_data.entity_states(wanted)
    out: dict[str, dict] = {}
    for eid, row in rows.items():
        attrs = row.get("attributes") or {}
        out[eid] = {
            "state": row.get("state"),
            "name": attrs.get("friendly_name") or eid,
            "unit": attrs.get("unit_of_measurement") or "",
            "device_class": attrs.get("device_class") or "",
            "last_changed": row.get("last_changed") or "",
            "attributes": attrs,
        }
    return web.json_response({"states": out, "poll_s": LIVE_POLL_S})


async def h_history_list(request: web.Request) -> web.Response:
    hdir = _history_dir(request.match_info["id"])

    def listing() -> list[dict]:
        runs = []
        for path in sorted(hdir.glob("*.json"), key=lambda p: p.name,
                           reverse=True):
            if not _STAMP_RE.match(path.stem):
                continue
            obj = _read_json(path)
            if obj is None:
                continue
            runs.append({
                "ts": path.stem,
                "generated_at": obj.get("generated_at"),
                "title": obj.get("title"),
            })
        return runs

    # A directory walk and one read per past run — a card with thirty of
    # them is thirty opens, and every one of them was on the event loop.
    return web.json_response({"runs": await asyncio.to_thread(listing)})


async def h_history_get(request: web.Request) -> web.Response:
    obj = await asyncio.to_thread(_read_json, _history_run_path(request))
    if obj is None:
        raise web.HTTPNotFound(text="no such run")
    return web.json_response(obj)


async def h_history_delete(request: web.Request) -> web.Response:
    path = _history_run_path(request)

    def remove() -> bool:
        try:
            path.unlink()
        except OSError:
            return False
        return True

    if not await asyncio.to_thread(remove):
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
    # One read of the overrides file per category, and there are a dozen
    # categories — off the loop, as one call rather than a dozen hops.
    records = await asyncio.to_thread(
        lambda: [_prompt_record(c["id"]) for c in CATEGORIES])
    return web.json_response({"prompts": records})


# ---------------------------------------------------------------------------
# What this card is actually asked — the whole of it
# ---------------------------------------------------------------------------
#
# The Edit dialog's box was labelled "Analysis focus (the prompt for this
# category)", and it is one paragraph of a dozen blocks. Everything else
# that shapes a card — the output contract, the homeowner's standing
# feedback, what brAIn has measured, what is already on the work list,
# what this card said last time, the hypothesis budget, the data itself —
# was assembled at run time and shown nowhere. So a card that kept coming
# back wrong could only be argued with by guessing, which is issue #300:
# "Cannot see prompt, unable to iteratively rework card layout."
#
# Two decisions worth writing down.
#
# **It is rebuilt, never replayed.** Storing the prompt that produced the
# card on screen and showing that back was the obvious design and it is
# the wrong one: half those blocks are live (the findings block, memory's
# mtime, the measurement stores, the previous run), so a stored copy
# starts drifting the moment it is written and what somebody would be
# editing against is a house that has moved on. What a person iterating
# needs is *what will be sent if I press Regenerate now*, and that is a
# thing this can answer exactly, because it calls the same builders the
# run calls. The snapshot path's bundle is genuinely expensive to
# collect, so `sections` carries each block's size and the data section
# is summarised rather than pasted — a hundred kilobytes of entity rows
# is not something anybody reads, and its SIZE is the fact people
# actually want from it.
#
# **The editable part stays the focus.** Offering the assembled text as a
# textarea would freeze those live blocks at whatever they said the day
# it was saved: the card would stop seeing new findings and go on citing
# a measurement from March, with nothing on screen to say so. The honest
# split is to show the whole thing and let you edit the part that is
# yours — the focus, and the standing feedback, both of which already
# reach every future run.
async def _prompt_preview(cat: dict, mode: str) -> dict:
    """The prompt this card would be sent right now, block by block."""
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    cat_id = cat["id"]
    feedback = [f["text"] for f in feedback_store.list_feedback(cat_id)]
    previous = None
    try:
        prev = json.loads(_insight_path(cat_id).read_text(encoding="utf-8"))
        previous = {k: prev.get(k) for k in
                    ("generated_at", "title", "summary", "highlights", "learned")}
    except (OSError, ValueError):
        # No previous run to show, which is what a card that has never
        # been generated looks like — the same silence `_generate` keeps
        # for the same reason. The preview then reports that block as 0
        # chars, which is the true answer for this card today.
        pass
    framing = dict(question=None, feedback=feedback,
                   hypothesis_budget=hypotheses.budget(),
                   knowledge=knowledge_store.prompt_block(),
                   previous=previous,
                   findings=findings_store.prompt_block(),
                   house=await _house_prompt_block())

    # The named blocks, in the order `_framing` puts them, each with what
    # it is FOR — because "why is this in my prompt" is the question a
    # person reading it has, and the size is the other half of the answer.
    sections = [
        {"name": "Analysis focus", "chars": len(cat.get("focus") or ""),
         "what": "What you typed in this dialog.", "yours": True},
        {"name": "Your feedback", "chars": sum(len(f) for f in feedback),
         "what": f"{len(feedback)} standing instruction(s) from the 💬 button "
                 "on this card. Every future run honours them.", "yours": True},
        {"name": "What brAIn has measured", "chars": len(framing["house"] or ""),
         "what": "Baselines, rhythms, room heat loss — so the card checks a "
                 "reading against normal before calling it unusual."},
        {"name": "Dead ends", "chars": len(framing["knowledge"] or ""),
         "what": "Guesses you rejected, so they are not re-asked."},
        {"name": "The work list", "chars": len(framing["findings"] or ""),
         "what": "What is already filed, and what you marked Wrong and why."},
        {"name": "Last run of this card",
         "chars": len(_previous_block(previous)) if previous else 0,
         "what": "So it advances the story instead of regenerating it."},
        {"name": "Output contract", "chars": len(_CARD_CONTRACT),
         "what": "The card's shape, the design system, the analysis rules. "
                 "Shared by both paths so they cannot drift."},
    ]

    if mode == "search":
        # The same arguments `_search_run` passes, or the preview would
        # show a memory block the run never sees.
        orientation = await ha_data.collect_orientation(
            question=framing.get("question"), domains=cat.get("domains") or ())
        prompt = build_orientation_prompt(cat, orientation, **framing)
        system = ANALYST_SYSTEM
        data_note = (f"A MAP of the home — {orientation.get('entity_count', 0)} "
                     f"entities across {len(orientation.get('domains') or {})} "
                     "domains, named by count rather than listed. The run then "
                     "fetches what it needs with read-only tools.")
        data_chars = len(json.dumps(orientation))
    else:
        bundle = await ha_data.collect_bundle(cat, eff_history_days(),
                                              question=None)
        prompt = build_prompt(cat, bundle, **framing)
        system = SYSTEM_PROMPT
        data_note = (f"The whole home in one go — {len(bundle.get('entities') or [])} "
                     "entities, posted with the prompt. No tools.")
        data_chars = len(json.dumps(bundle))
    sections.append({"name": "The data", "chars": data_chars, "what": data_note})

    return {
        "id": cat_id, "mode": mode, "system": system, "prompt": prompt,
        "sections": sections,
        "chars": len(prompt) + len(system),
        # The one number people actually act on. `~` everywhere it is
        # shown, because it is a character estimate and not a count.
        "tokens": (len(prompt) + len(system)) // CHARS_PER_TOKEN,
        "model": eff_model(),
    }


async def h_prompt_preview(request: web.Request) -> web.Response:
    cat_id = request.match_info["id"]
    # `resolve_category`, which is what `_generate` calls — never
    # `get_category`, which answers with the SHIPPED definition and
    # ignores every override. A preview that showed the shipped focus
    # back to somebody who had rewritten it would be the exact failure
    # this route exists to end, one layer further in: a prompt on screen
    # that is not the prompt being sent.
    cat = resolve_category(cat_id)
    if not cat:
        raise web.HTTPBadRequest(text="unknown category")
    mode = request.query.get("mode") or eff_gather_mode()
    if mode not in ("search", "snapshot"):
        raise web.HTTPBadRequest(text="mode is search or snapshot")
    try:
        return web.json_response(await _prompt_preview(cat, mode))
    except Exception as exc:  # noqa: BLE001 — a preview that cannot reach
        # Core is a sentence, not a 500.
        #
        # The sentence carries no exception text and the log line carries
        # no path parameter, and both are CodeQL findings this route
        # shipped with. The response one is real: everything else here
        # fails with a message somebody typed, and an exception's `str`
        # is the one string on this path that can carry a traceback's
        # contents out to a browser. The log one is defence in depth —
        # `cat_id` has already matched a real category by this line, so
        # it cannot be arbitrary — but `cat["id"]` is the canonical id
        # rather than whatever spelling arrived in the URL, which is the
        # better thing to log regardless of who is reading it.
        log.warning("could not preview the prompt for %s: %s", cat["id"], exc)
        raise web.HTTPBadGateway(
            text="Could not build the preview — brAIn could not reach Home "
                 "Assistant for the data this card would be sent. The "
                 "add-on log says which call failed.") from exc


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
    """The card a piece of feedback is about, named the way a person would.

    A recurring card is its category. An asked card has no category, and
    since Refine it has standing changes all the same — so it answers with
    the stored card's own label, which is what the memory line quotes.
    """
    cat = get_category(cat_id) or user_categories.get(cat_id)
    if cat:
        return cat
    if cat_id.startswith("custom-"):
        stored = _read_json(_insight_path(cat_id))
        if stored is not None:
            return {"id": cat_id,
                    "title": _asked_card_name(stored),
                    "icon": stored.get("icon") or "✨"}
    raise web.HTTPBadRequest(text="no such card")


def _asked_card_name(insight: dict) -> str:
    """What an asked card is called: its hand-given label, else its title.

    `category_title` is "Custom" on every asked card nobody renamed, which
    is the word the card no longer shows anywhere.
    """
    named = str(insight.get("category_title") or "").strip()
    if named and named != "Custom":
        return named
    return str(insight.get("title") or "an asked question")[:120]


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

    def remove() -> tuple[bool, list]:
        # Read back inside the same hop: two would be two trips off the loop
        # for one answer, and the list is what the tab repaints from.
        removed = feedback_store.remove_feedback(cat_id, ts)
        return removed, feedback_store.list_feedback(cat_id)

    removed, feedback = await asyncio.to_thread(remove)
    if not removed:
        raise web.HTTPNotFound(text="no such feedback entry")
    return web.json_response({"feedback": feedback})


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


def _card_file_name(insight_id: str, whole: bool = False) -> str:
    """The chart-only mirror, or (`whole`) the card with its numbers.

    Two files rather than a query string on one: the chart-only name is
    what every dashboard card made before 2.8 points at, so it keeps
    serving exactly what it always did.
    """
    return f"{insight_id}-{get_card_token()}{'.card' if whole else ''}.html"


def _card_mirror_path(insight_id: str, whole: bool = False) -> Path | None:
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
        return _under(WWW_CARD_DIR, _card_file_name(insight_id, whole))
    except web.HTTPBadRequest:
        return None


def _card_eyebrow(insight: dict) -> str:
    """The line over the title, for a page that has no category list."""
    if str(insight.get("id") or "").startswith("custom-"):
        return card_tags.eyebrow(insight)
    return str(insight.get("category_title") or "")


# The whole card as a page of its own, for a dashboard. It is the card's
# face and nothing else — no menu, no history, no token count — with the
# visualization in a sandboxed frame of its own exactly as the panel shows
# it, because the visualization is model-authored script and must not run
# with this page's origin (which is Home Assistant's).
_WHOLE_CARD_CSS = """
:root{color-scheme:light dark;--ink:#0a1622;--ink2:#33506a;--ink3:#5b7185;--tile:#eef4f9}
@media (prefers-color-scheme: dark){:root{--ink:#ffffff;--ink2:#b9ccdd;--ink3:#8ea5b8;--tile:#15293f}}
html,body{margin:0;background:transparent;color:var(--ink);
font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
.c{padding:14px 16px 12px;display:flex;flex-direction:column;gap:10px}
.eb{font-size:12px;font-weight:600;color:var(--ink3);white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
h1{margin:2px 0 0;font-size:17px;line-height:1.25}
.s{margin:0;font-size:14px;line-height:1.5;color:var(--ink2)}
.s b{color:var(--ink)}
.h{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}
.t{background:var(--tile);border-radius:10px;padding:8px 11px}
.t .l{font-size:11.5px;color:var(--ink3)}
.t .v{font-size:16px;font-weight:700;margin-top:2px}
.t .d{font-size:11.5px;color:var(--ink2);margin-top:1px}
iframe{display:block;width:100%;height:320px;border:0;background:transparent}
.f{font-size:11px;color:var(--ink3)}
"""

_WHOLE_CARD_SIZE = (
    '<script>(function(){var f=document.getElementById("v");'
    'window.addEventListener("message",function(ev){var d=ev.data;'
    'if(ev.source!==f.contentWindow||!d||d.type!=="bruh-size"||!d.h)return;'
    'f.style.height=Math.min(Math.max(d.h,80),2000)+"px";});})();</script>'
)

_WHOLE_CARD_FRAME_SIZE = (
    '<script>(function(){var last=0;function post(){var b=document.body;'
    'if(!b)return;var h=Math.ceil(Math.max(b.offsetHeight,'
    'b.getBoundingClientRect().height));if(h>0&&Math.abs(h-last)>2){last=h;'
    'parent.postMessage({type:"bruh-size",h:h},"*");}}'
    'try{new ResizeObserver(post).observe(document.body);}catch(e){}'
    'window.addEventListener("load",post);setTimeout(post,400);'
    'setTimeout(post,1200);})();</script>'
)


def _lead_split(summary: str) -> tuple[str, str]:
    """The summary's first sentence and the rest, when there is a rest."""
    match = re.match(r"^(.{3,160}?[.!?])\s+(\S.*)$", summary, re.DOTALL)
    return (match.group(1), match.group(2)) if match else ("", summary)


def _whole_card_page(insight: dict) -> str:
    esc = html_lib.escape
    lead, rest = _lead_split(str(insight.get("summary") or ""))
    summary = (f"<b>{esc(lead)}</b> {esc(rest)}" if lead else esc(rest))
    tiles = []
    for h in insight.get("highlights") or []:
        if not isinstance(h, dict) or not h.get("label"):
            continue
        delta = (f'<div class="d">{esc(str(h["delta"]))}</div>'
                 if h.get("delta") else "")
        tiles.append(
            f'<div class="t"><div class="l">{esc(str(h["label"]))}</div>'
            f'<div class="v">{esc(str(h.get("value", "—")))}</div>{delta}</div>')
    when = str(insight.get("generated_at") or "").replace("T", " ")[:16]
    viz = str(insight.get("html") or "") + _WHOLE_CARD_FRAME_SIZE
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{esc(str(insight.get('title') or 'Insight'))}</title>"
        f"<style>{_WHOLE_CARD_CSS}</style></head><body><div class=\"c\">"
        f"<div><div class=\"eb\">{esc(_card_eyebrow(insight))}</div>"
        f"<h1>{esc(str(insight.get('title') or ''))}</h1></div>"
        f"<p class=\"s\">{summary}</p>"
        + (f'<div class="h">{"".join(tiles)}</div>' if tiles else "")
        + f'<iframe id="v" sandbox="allow-scripts" title="Visualization" '
        f'srcdoc="{esc(viz, quote=True)}"></iframe>'
        f'<div class="f">brAIn · analysed {esc(when)}</div>'
        "</div>" + _WHOLE_CARD_SIZE + _CARD_RELOAD_SNIPPET + "</body></html>"
    )


def _mirror_card(insight: dict) -> None:
    """Best-effort mirror of one insight; a no-op until the dir exists."""
    if not WWW_CARD_DIR.is_dir():
        return
    html = insight.get("html")
    insight_id = str(insight.get("id") or "")
    path = _card_mirror_path(insight_id)
    whole = _card_mirror_path(insight_id, whole=True)
    if not isinstance(html, str) or not html or path is None or whole is None:
        return
    try:
        atomic_write.write_text(path, html + _CARD_RELOAD_SNIPPET)
        atomic_write.write_text(whole, _whole_card_page(insight))
    except OSError as exc:
        log.debug("card mirror write failed: %s", exc)


def _unmirror_card(insight_id: str) -> None:
    if not WWW_CARD_DIR.is_dir():
        return
    for whole in (False, True):
        path = _card_mirror_path(insight_id, whole)
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
    keep = ({_card_file_name(i["id"]) for i in insights}
            | {_card_file_name(i["id"], whole=True) for i in insights})
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


# ---------------------------------------------------------------------------
# Home Assistant's own maintainer — tidy, the upgrade advisor, the overnight
# health check, the house book and the access review
# ---------------------------------------------------------------------------
# Every one of these is a run brAIn spends on Home Assistant ITSELF rather
# than on what the house is doing, and they share one shape, so they share
# one in-flight state. A press STARTS a run and never awaits it — each is
# minutes of work and ingress will not hold a request that long
# (`h_baselines_run`'s clock) — the flag is flipped synchronously
# (`start_auth_check`'s rule: `create_task` only schedules, so two presses in
# one tick would both pass a guard their own task had not set yet), and the
# page reads the outcome back off its GET. A pressed run answers to the
# credential only; a scheduled one to the three gates every scheduled run
# answers to (`_resident_gate`), and a gate that holds says so in
# diagnostics, because "it did not run" and "it ran and found nothing" are
# different silences.

MAINT_JOBS = ("tidy", "upgrades", "sre", "book", "access")
MAINT_STATE: dict = {
    name: {"running": False, "started_at": 0.0, "finished_at": 0.0,
           "last_error": "", "last_note": "", "held": "", "subject": ""}
    for name in MAINT_JOBS}
# Held so the loop cannot collect a task nobody awaits.
_MAINT_TASKS: set = set()
MAINT_POLL_S = 600
MAINT_FIRST_DELAY_S = 900
# The overnight pass runs in the first poll after this local hour, once a
# night; the weekly ones once every seven days.
SRE_HOUR = 3
SRE_STAMP_KEY = "sre_last"
ACCESS_STAMP_KEY = "access_last"
ACCESS_TEXT_KEY = "access_review"
# When the scheduled review was last STARTED. The stamp above is written
# only by a review that landed, so without this one a review failing for
# a reason that does not clear (a CLI too old for the schema, an account
# that will not answer) was re-run on every poll — a paid run every ten
# minutes for ever. A guard that refuses has to change the next attempt.
ACCESS_TRIED_KEY = "access_tried"
ACCESS_RETRY_S = 6 * 3600
MAINT_WEEK_S = 7 * 86400
# The last checks pass's view of who can reach the house, kept so the
# weekly review needs no snapshot of its own — `_note_registry`'s
# arrangement, one hook over.
ACCESS_DIGEST: dict = {"digest": None, "at": 0.0}


def _note_access(snapshot: dict, now: float) -> None:
    """Called by `run_checks` with the snapshot it already fetched."""
    try:
        ACCESS_DIGEST["digest"] = checks.security.review_digest(snapshot, now)
        ACCESS_DIGEST["at"] = now
    except Exception as exc:  # noqa: BLE001 — a digest must not fail a pass
        log.debug("could not keep the access digest: %s", exc)


def _maint_start(name: str, factory) -> bool:
    """Start one maintainer run unless one is in flight. True if started."""
    state = MAINT_STATE[name]
    if state["running"]:
        return False
    state["running"] = True
    state["started_at"] = time.time()
    state["last_error"] = ""

    async def run() -> None:
        try:
            await factory()
        except Exception as exc:  # noqa: BLE001 — a run's failure is a sentence
            state["last_error"] = str(exc)[:300] or type(exc).__name__
            log.warning("%s run failed: %s", name, state["last_error"])
        finally:
            state["running"] = False
            state["finished_at"] = time.time()

    task = asyncio.create_task(run())
    _MAINT_TASKS.add(task)
    task.add_done_callback(_MAINT_TASKS.discard)
    return True


def _maint_pressed_refusal() -> str:
    """Why a PRESS may not spend a run right now, or ''. The budget is not
    asked: asking by hand always runs."""
    return "" if engine.get_auth() else (
        "brAIn has no Claude sign-in yet — sign in under ⚙ first.")


def _run_id(result: dict) -> str:
    return str((result.get("meta") or {}).get("session_id") or "")[:64]


def _maint_status(name: str) -> dict:
    s = MAINT_STATE[name]
    return {"running": s["running"], "last_error": s["last_error"],
            "last_note": s["last_note"], "held": s["held"],
            "finished_at": int(s["finished_at"]), "subject": s["subject"]}


# -- tidy: names, rooms and aliases -------------------------------------------

async def _run_tidy() -> None:
    snap = await checks.snapshot.collect_rooms(time.time())
    dig = tidy.digest(snap)
    if not dig["entities"] and not dig["devices"]:
        await asyncio.to_thread(tidy.save_proposal, {"rows": []})
        MAINT_STATE["tidy"]["last_note"] = ("Nothing here needs a new name, a "
                                            "room or an alias.")
        return
    result = await _claude(
        engine.run_claude, tidy.frame(dig), tidy.SYSTEM, "", tidy.TIMEOUT_S,
        4, "maintenance", job="tidy", schema=tidy.SCHEMA)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "no reply"))
    answer = _answer(result)
    if answer is None:
        raise RuntimeError("the reply could not be read")
    parsed = tidy.parse(answer, dig, snap, automation_writer.protected_patterns())
    await asyncio.to_thread(tidy.save_proposal, parsed, run_id=_run_id(result))
    MAINT_STATE["tidy"]["last_note"] = (
        f"{len(parsed['rows'])} suggestion(s) to review"
        + (f", {len(parsed['refused'])} refused" if parsed["refused"] else ""))


def _tidy_payload() -> dict:
    data = tidy.load()
    return {**_maint_status("tidy"), "proposal": data["proposal"],
            "batches": tidy.undoable(data["batches"], time.time()),
            "undo_days": tidy.UNDO_DAYS, "unreadable": data["unreadable"]}


async def h_tidy(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_tidy_payload))


async def h_tidy_run(request: web.Request) -> web.Response:
    excuse = _maint_pressed_refusal()
    if excuse:
        raise web.HTTPBadRequest(text=excuse)
    started = _maint_start("tidy", _run_tidy)
    return web.json_response({**await asyncio.to_thread(_tidy_payload),
                              "started": started})


async def h_tidy_apply(request: web.Request) -> web.Response:
    import aiohttp  # noqa: PLC0415 — deferred, as every Core call here is
    body = await _json_body(request)
    ids = [str(i) for i in (body.get("ids") or []) if isinstance(i, str)][:tidy.MAX_ROWS]
    async with aiohttp.ClientSession() as session:
        result = await tidy.apply(session, ids)
    if not result["applied"]:
        raise web.HTTPConflict(text=result["error"] or (
            "Home Assistant took none of it: "
            + "; ".join(f"{s['subject']}: {s['why']}" for s in result["skipped"])))
    log.info("tidy: applied %d change(s), %d skipped", len(result["applied"]),
             len(result["skipped"]))
    return web.json_response({**await asyncio.to_thread(_tidy_payload),
                              "result": result})


async def h_tidy_discard(request: web.Request) -> web.Response:
    await asyncio.to_thread(tidy.discard)
    return web.json_response(await asyncio.to_thread(_tidy_payload))


async def h_tidy_undo(request: web.Request) -> web.Response:
    import aiohttp  # noqa: PLC0415
    batch_id = request.match_info["batch"]
    if not re.fullmatch(r"b\d{1,20}", batch_id):
        raise web.HTTPNotFound(text="no such batch")
    async with aiohttp.ClientSession() as session:
        result = await tidy.undo(session, batch_id)
    if result["error"]:
        raise web.HTTPConflict(text=result["error"])
    return web.json_response({**await asyncio.to_thread(_tidy_payload),
                              "result": result})


# -- the upgrade advisor ------------------------------------------------------

async def _pending_updates() -> list[dict] | None:
    """What is waiting, read live — or None when Core would not answer,
    which the page says rather than reading as "you are up to date"."""
    import aiohttp  # noqa: PLC0415
    import ha_data  # noqa: PLC0415
    try:
        async with aiohttp.ClientSession() as session:
            raw = await ha_data._rest_get(session, "/states", timeout=30)
    except Exception as exc:  # noqa: BLE001
        log.debug("could not read the update entities: %s", exc)
        return None
    return upgrades.pending(raw if isinstance(raw, list) else [])


def _advise_run(prompt: str, system: str, schema: dict) -> dict:
    """The upgrade advisor's one Claude call: no tools at all, so a run
    reading release notes cannot be talked by them into reaching anything
    — and nothing here could install the update if it were."""
    return engine.run_claude(prompt, system, "", upgrades.TIMEOUT_S, 4,
                             "maintenance", job="upgrade_advice",
                             schema=schema)


async def _run_advice(update: dict) -> None:
    import aiohttp  # noqa: PLC0415

    async def run(prompt: str, system: str, schema: dict) -> dict:
        return await _claude(_advise_run, prompt, system, schema)

    async with aiohttp.ClientSession() as session:
        verdict = await upgrades.advise(session, update, run)
    await asyncio.to_thread(upgrades.remember, verdict)
    MAINT_STATE["upgrades"]["last_note"] = (
        f"{update['title']}: {upgrades.VERDICT_WORDS[verdict['verdict']]}")


async def h_upgrades(request: web.Request) -> web.Response:
    updates = await _pending_updates()
    payload = _maint_status("upgrades")
    if updates is None:
        return web.json_response({**payload, "updates": [], "readable": False})
    rows = await asyncio.to_thread(upgrades.listing, updates)
    return web.json_response({**payload, "updates": rows, "readable": True})


async def h_upgrades_advise(request: web.Request) -> web.Response:
    excuse = _maint_pressed_refusal()
    if excuse:
        raise web.HTTPBadRequest(text=excuse)
    body = await _json_body(request)
    entity_id = str(body.get("entity_id") or "")
    updates = await _pending_updates()
    if updates is None:
        raise web.HTTPConflict(text="Home Assistant did not answer for its "
                                    "update entities, so there is nothing to check.")
    update = next((u for u in updates if u["entity_id"] == entity_id), None)
    if update is None:
        raise web.HTTPNotFound(text="that update is not waiting any more")
    started = _maint_start("upgrades", lambda: _run_advice(update))
    if started:
        MAINT_STATE["upgrades"]["subject"] = entity_id
    return web.json_response({**_maint_status("upgrades"), "started": started})


# -- the overnight health check (SRE) -----------------------------------------

async def _run_sre(reason: str = "schedule") -> None:
    import aiohttp  # noqa: PLC0415
    now = time.time()
    async with aiohttp.ClientSession() as session:
        collected = await sre.collect(session)
    dig = sre.digest(collected, now)
    state = await asyncio.to_thread(sre.load)
    summary = {"at": int(now), "reason": reason,
               "records": len(dig["records"]), "available": dig["available"],
               "ran": False, "causes": 0, "filed": 0, "cleared": 0,
               "refused": 0, "invented": 0, "note": ""}
    if not dig["available"].get("log"):
        # "I could not look" at the log is not a healthy night: nothing is
        # judged and nothing is cleared.
        summary["note"] = ("the system log could not be read, so nothing was "
                           "judged and nothing was cleared")
        state["last"] = summary
        await asyncio.to_thread(sre.save, state)
        MAINT_STATE["sre"]["last_note"] = summary["note"]
        return
    rows: list[dict] = []
    if sre.worth_a_run(dig):
        result = await _claude(
            engine.run_claude, sre.frame(dig), sre.SYSTEM, "", sre.TIMEOUT_S,
            4, "maintenance", job="sre", schema=sre.SCHEMA)
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "no reply"))
        answer = _answer(result)
        if answer is None:
            raise RuntimeError("the reply could not be read")
        parsed = sre.parse_causes(answer, dig)
        rows = sre.rows(parsed["causes"], dig, state, now)
        summary.update(ran=True, causes=len(parsed["causes"]),
                       refused=parsed["refused"], invented=parsed["invented"],
                       run_id=_run_id(result))
    else:
        summary["note"] = "nothing in the log or the mesh worth a run"

    def apply() -> tuple[list[dict], list[dict]]:
        # Filed as waiting to be looked at, like every producer's rows.
        created = findings_store.add_many(triage.gate(rows))
        findings_store.refresh_details(rows)
        open_rows = [f for f in findings_store.list_all()
                     if f.get("source") == sre.SOURCE]
        keep = ({findings_store.normalize(r["text"]) for r in rows}
                | sre.keep_keys(open_rows, state, dig["available"]))
        cleared = findings_store.clear_resolved({sre.SOURCE}, keep)
        return created, cleared

    created, cleared = await asyncio.to_thread(apply)
    summary.update(filed=len(created), cleared=len(cleared))
    state["last"] = summary
    await asyncio.to_thread(sre.save, state)
    if created:
        _offer_findings(created, now)
    MAINT_STATE["sre"]["last_note"] = (
        f"{summary['records']} record(s) read, {summary['causes']} cause(s), "
        f"{len(created)} new, {len(cleared)} cleared")
    journal.record("sre", "ok", extra={"records": summary["records"],
                                       "causes": summary["causes"],
                                       "filed": len(created)})


def _sre_payload() -> dict:
    return {**_maint_status("sre"), "last": sre.load().get("last")}


async def h_sre(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_sre_payload))


async def h_sre_run(request: web.Request) -> web.Response:
    excuse = _maint_pressed_refusal()
    if excuse:
        raise web.HTTPBadRequest(text=excuse)
    started = _maint_start("sre", lambda: _run_sre("pressed"))
    return web.json_response({**await asyncio.to_thread(_sre_payload),
                              "started": started})


# -- the house book -----------------------------------------------------------

async def _book_snapshot() -> dict:
    snap = await checks.snapshot.collect_rooms(time.time())
    cfg = checks.snapshot.load_configs()
    snap["scripts"] = cfg.get("scripts") or {}
    return snap


async def _run_book(reason: str = "pressed", snap: dict | None = None) -> None:
    now = time.time()
    snap = snap if snap is not None else await _book_snapshot()
    dig = house_book.digest(snap)
    fp = house_book.fingerprint(snap)
    result = await _claude(
        engine.run_claude, house_book.frame(dig), house_book.SYSTEM, "",
        house_book.TIMEOUT_S, 4, "maintenance", job="house_book",
        schema=house_book.SCHEMA)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "no reply"))
    answer = _answer(result)
    if answer is None:
        raise RuntimeError("the reply could not be read")
    parsed = house_book.parse(answer, dig)

    def store() -> list[dict]:
        state = house_book.load()
        state["book"] = {"at": int(now), "reason": reason,
                         "sections": parsed["sections"],
                         "uncited": parsed["uncited"],
                         "redacted": parsed["redacted"],
                         "run_id": _run_id(result)}
        state["fingerprint"] = fp
        state["opted_in"] = True
        state["held"] = ""
        state["last_error"] = ""
        open_count = sum(1 for f in findings_store.list_all()
                         if f.get("source") == house_book.SOURCE)
        rows = house_book.question_rows(parsed["questions"],
                                        state.get("asked") or [], open_count)
        for row in rows:
            state.setdefault("asked", []).append(row.pop("_subject"))
        created = findings_store.add_many(triage.gate(rows))
        # A published book is kept current: the person already chose to
        # put it on the URL, and a stale copy there is the one they shared.
        if state.get("published"):
            try:
                state["published"] = {
                    "at": int(now),
                    "path": house_book.publish(state["book"], WWW_CARD_DIR)}
            except OSError as exc:
                log.warning("could not republish the house book: %s", exc)
        house_book.save(state)
        return created

    created = await asyncio.to_thread(store)
    if created:
        _offer_findings(created, now)
    MAINT_STATE["book"]["last_note"] = (
        f"{sum(len(s['entries']) for s in parsed['sections'])} entries"
        + (f", {parsed['uncited']} dropped for citing nothing"
           if parsed["uncited"] else "")
        + (f", {len(created)} question(s) filed" if created else ""))


def _book_payload() -> dict:
    state = house_book.load()
    return {**_maint_status("book"), "book": state.get("book"),
            "published": state.get("published"),
            "opted_in": bool(state.get("opted_in")),
            "held": state.get("held") or MAINT_STATE["book"]["held"],
            "unreadable": bool(state.get("unreadable"))}


async def h_book(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_book_payload))


async def h_book_run(request: web.Request) -> web.Response:
    excuse = _maint_pressed_refusal()
    if excuse:
        raise web.HTTPBadRequest(text=excuse)
    started = _maint_start("book", lambda: _run_book("pressed"))
    return web.json_response({**await asyncio.to_thread(_book_payload),
                              "started": started})


async def h_book_publish(request: web.Request) -> web.Response:
    def publish() -> dict:
        state = house_book.load()
        if not state.get("book"):
            raise web.HTTPConflict(text="There is no house book to publish yet.")
        try:
            path = house_book.publish(state["book"], WWW_CARD_DIR)
        except OSError as exc:
            raise web.HTTPConflict(
                text=f"brAIn could not write to /config/www ({exc}).") from exc
        state["published"] = {"at": int(time.time()), "path": path}
        house_book.save(state)
        return _book_payload()

    return web.json_response(await asyncio.to_thread(publish))


async def h_book_revoke(request: web.Request) -> web.Response:
    def revoke() -> dict:
        removed = house_book.revoke(WWW_CARD_DIR)
        state = house_book.load()
        state["published"] = None
        house_book.save(state)
        return {**_book_payload(), "removed": removed}

    return web.json_response(await asyncio.to_thread(revoke))


async def h_book_answer(request: web.Request) -> web.Response:
    """A gap question answered. The answer is required — "where is the
    stopcock" with nothing typed is not an answer — and it goes through
    the one door every ending uses, so the memory line, the settled key
    and the capture label are what any other Yes would have written."""
    finding = _finding_or_404(request)
    if finding.get("source") != house_book.SOURCE:
        raise web.HTTPConflict(text="that is not a house book question")
    body = await _json_body(request)
    note = str(body.get("note") or "").strip()[:findings_store.MAX_NOTE]
    if not note:
        raise web.HTTPBadRequest(text="Type the answer first.")
    payload, _fact = await _end_finding(finding, FINDING_VERBS["confirm"],
                                        house_book.redact_text(note))
    return web.json_response({**payload, **await asyncio.to_thread(
        _cases_payload, time.time())})


# -- the access review --------------------------------------------------------

async def _run_access(reason: str = "pressed") -> None:
    digest = ACCESS_DIGEST["digest"]
    if digest is None:
        snap = await checks.snapshot.collect(time.time())
        _note_access(snap, time.time())
        digest = ACCESS_DIGEST["digest"]
    open_rows = [f["text"] for f in findings_store.list_all()
                 if str(f.get("source") or "").startswith("check:sec.")]
    prompt = ("DIGEST:\n" + json.dumps(digest, ensure_ascii=False, default=str)
              + "\n\nOPEN SECURITY FINDINGS:\n"
              + json.dumps(open_rows, ensure_ascii=False))
    result = await _claude(
        engine.run_claude, prompt, checks.security.REVIEW_SYSTEM, "", 180, 4,
        "maintenance", job="access_review",
        schema=checks.security.REVIEW_SCHEMA)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "no reply"))
    sentence = checks.security.review_sentence(_answer(result))
    if not sentence:
        raise RuntimeError("the review came back too short to show")
    await asyncio.to_thread(schedule_store.set_text, ACCESS_TEXT_KEY, sentence)
    await asyncio.to_thread(schedule_store.set, ACCESS_STAMP_KEY, time.time())
    MAINT_STATE["access"]["last_note"] = reason


def _access_payload() -> dict:
    return {**_maint_status("access"),
            "sentence": schedule_store.get_text(ACCESS_TEXT_KEY),
            "at": int(schedule_store.get(ACCESS_STAMP_KEY)),
            "open": sum(1 for f in findings_store.list_all()
                        if str(f.get("source") or "").startswith("check:sec."))}


async def h_access(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_access_payload))


async def h_access_run(request: web.Request) -> web.Response:
    excuse = _maint_pressed_refusal()
    if excuse:
        raise web.HTTPBadRequest(text=excuse)
    started = _maint_start("access", lambda: _run_access("pressed"))
    return web.json_response({**await asyncio.to_thread(_access_payload),
                              "started": started})


# -- the schedule: overnight, and weekly --------------------------------------

async def _maint_tick(now: float) -> list[str]:
    """One pass of the maintainer's schedule. Returns what it started."""
    started: list[str] = []
    settings = await asyncio.to_thread(settings_store.load)
    local = _local_now(now)
    excuse = _resident_gate(settings)

    # The overnight health check: once a night, after SRE_HOUR.
    last = await asyncio.to_thread(schedule_store.get, SRE_STAMP_KEY)
    in_window = SRE_HOUR <= local.hour < SRE_HOUR + 3
    done_tonight = bool(last) and _local_now(last).date() == local.date()
    if in_window and not done_tonight:
        if excuse:
            MAINT_STATE["sre"]["held"] = excuse
        elif _maint_start("sre", lambda: _run_sre("schedule")):
            MAINT_STATE["sre"]["held"] = ""
            await asyncio.to_thread(schedule_store.set, SRE_STAMP_KEY, now)
            started.append("sre")

    # The access review: weekly, off the last checks pass's digest.
    last = await asyncio.to_thread(schedule_store.get, ACCESS_STAMP_KEY)
    tried = await asyncio.to_thread(schedule_store.get, ACCESS_TRIED_KEY)
    if (ACCESS_DIGEST["digest"] is not None and now - last >= MAINT_WEEK_S
            and now - tried >= ACCESS_RETRY_S):
        if excuse:
            MAINT_STATE["access"]["held"] = excuse
        elif _maint_start("access", lambda: _run_access("schedule")):
            MAINT_STATE["access"]["held"] = ""
            await asyncio.to_thread(schedule_store.set, ACCESS_TRIED_KEY, now)
            started.append("access")

    # The house book: weekly, only once somebody has asked for one, and
    # only when what it reads has moved.
    state = await asyncio.to_thread(house_book.load)
    if state.get("opted_in") and now - float(state.get("last_weekly") or 0) >= MAINT_WEEK_S:
        snap = await _book_snapshot()
        fp = await asyncio.to_thread(house_book.fingerprint, snap)
        changed, why = house_book.moved(state.get("fingerprint"), fp)
        state["last_weekly"] = int(now)
        if not changed:
            state["held"] = why
            MAINT_STATE["book"]["held"] = why
        elif excuse:
            state["held"] = excuse
            MAINT_STATE["book"]["held"] = excuse
        elif _maint_start("book", lambda: _run_book("weekly: " + why, snap)):
            state["held"] = ""
            started.append("book")
        await asyncio.to_thread(house_book.save, state)
    return started


async def _maint_loop() -> None:
    await asyncio.sleep(MAINT_FIRST_DELAY_S)
    while True:
        try:
            started = await _maint_tick(time.time())
            if started:
                log.info("maintainer: started %s", ", ".join(started))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — the loop outlives a pass
            log.warning("maintainer pass failed: %s", exc)
        await asyncio.sleep(MAINT_POLL_S)


def _maintainer_diagnostics() -> dict:
    """Whether each of the five has run, is held, or failed — a scheduled
    run nobody can see is one that silently stopped."""
    out = {name: _maint_status(name) for name in MAINT_JOBS}
    try:
        data = tidy.load()
        out["tidy"]["pending_rows"] = len((data["proposal"] or {}).get("rows") or [])
        out["tidy"]["undoable_batches"] = len(tidy.undoable(data["batches"], time.time()))
        out["upgrades"]["verdicts"] = len(upgrades.load()["verdicts"])
        out["sre"]["last"] = sre.load().get("last")
        book = house_book.load()
        out["book"].update(
            opted_in=bool(book.get("opted_in")),
            built_at=int((book.get("book") or {}).get("at") or 0),
            uncited=int((book.get("book") or {}).get("uncited") or 0),
            published=bool(book.get("published")))
        out["access"]["digest_at"] = int(ACCESS_DIGEST["at"])
        out["access"]["reviewed_at"] = int(schedule_store.get(ACCESS_STAMP_KEY))
    except Exception as exc:  # noqa: BLE001 — diagnostics must not fail on one reader
        out["error"] = str(exc)[:200]
    return out


def _maint_routes(app: web.Application) -> None:
    app.router.add_get("/api/tidy", h_tidy)
    app.router.add_post("/api/tidy/run", h_tidy_run)
    app.router.add_post("/api/tidy/apply", h_tidy_apply)
    app.router.add_post("/api/tidy/discard", h_tidy_discard)
    app.router.add_post("/api/tidy/undo/{batch}", h_tidy_undo)
    app.router.add_get("/api/upgrades", h_upgrades)
    app.router.add_post("/api/upgrades/advise", h_upgrades_advise)
    app.router.add_get("/api/sre", h_sre)
    app.router.add_post("/api/sre/run", h_sre_run)
    app.router.add_get("/api/house_book", h_book)
    app.router.add_post("/api/house_book/run", h_book_run)
    app.router.add_post("/api/house_book/publish", h_book_publish)
    app.router.add_post("/api/house_book/revoke", h_book_revoke)
    app.router.add_post("/api/house_book/question/{ts}/answer", h_book_answer)
    app.router.add_get("/api/access", h_access)
    app.router.add_post("/api/access/run", h_access_run)


# -- a card on a dashboard, put there by brAIn --------------------------------
# The ▦ dialog used to end at "here is some YAML, go and paste it into the
# card editor" — four steps in another app for something brAIn can do in
# one. So it lists the dashboards and views Home Assistant has, and adds
# the card to the one picked. Only a dashboard stored in the UI can be
# written: a YAML-mode one is somebody's file, and an auto-generated one
# has no config to add to until somebody takes control of it — both come
# back with the sentence that says which, and the YAML stays offered for
# them.

def _view_rows(config) -> list[dict]:
    views = (config or {}).get("views") if isinstance(config, dict) else None
    out = []
    for i, view in enumerate(views if isinstance(views, list) else []):
        if not isinstance(view, dict):
            continue
        title = str(view.get("title") or view.get("path") or f"View {i + 1}")
        out.append({"index": i, "title": title[:80],
                    "sections": view.get("type") == "sections"})
    return out


def _unwritable_reason(row: dict, call: dict) -> str:
    if str(row.get("mode") or "storage") == "yaml":
        return "This dashboard is written in YAML — copy the YAML below into it."
    if not call.get("ok"):
        err = str(call.get("error") or "")
        if "not found" in err.lower() or "no config" in err.lower():
            return ("Home Assistant builds this dashboard automatically, so "
                    "there is nothing to add a card to yet. Open it, choose "
                    "⋮ → Edit dashboard → Take control, then try again.")
        return f"Home Assistant would not read this dashboard ({err or 'no answer'})."
    config = call.get("result")
    if isinstance(config, dict) and config.get("strategy"):
        return ("This dashboard is generated by a strategy. Take control of "
                "it in Home Assistant first, then try again.")
    return ""


async def _dashboards() -> list[dict]:
    import aiohttp  # noqa: PLC0415 — deferred, as every Core call here is
    import ha_data  # noqa: PLC0415
    async with aiohttp.ClientSession() as session:
        listed = await ha_data._ws_calls(
            session, [{"type": "lovelace/dashboards/list"}])
        rows = listed[0]["result"] if listed and listed[0]["ok"] else []
        dashboards = [{"url_path": None, "title": "Overview", "mode": "storage"}]
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get("url_path"):
                dashboards.append({"url_path": str(row["url_path"]),
                                   "title": str(row.get("title")
                                                or row["url_path"]),
                                   "mode": str(row.get("mode") or "storage")})
        calls = await ha_data._ws_calls(session, [
            {"type": "lovelace/config", "url_path": d["url_path"]}
            for d in dashboards])
    out = []
    for dash, call in zip(dashboards, calls):
        reason = _unwritable_reason(dash, call)
        out.append({
            "url_path": dash["url_path"], "title": dash["title"][:80],
            "editable": not reason, "reason": reason,
            "views": _view_rows(call.get("result")) if not reason else []})
    return out


async def h_dashboards(request: web.Request) -> web.Response:
    try:
        rows = await _dashboards()
    except Exception as exc:  # noqa: BLE001 — a listing, reported as such
        log.info("could not list dashboards: %s", exc)
        return web.json_response(
            {"dashboards": [], "error": "brAIn could not reach Home Assistant "
             "to list its dashboards."})
    return web.json_response({"dashboards": rows})


def _dashboard_card(insight: dict, whole: bool, aspect) -> dict:
    """The Webpage card that shows one insight, as Home Assistant stores it."""
    url = (f"/local/{WWW_CARD_DIR.name}/"
           f"{_card_file_name(insight['id'], whole=whole)}")
    try:
        ratio = int(float(aspect))
    except (TypeError, ValueError):
        ratio = 90 if whole else 60
    ratio = min(max(ratio, 25), 300)
    title = " ".join(str(insight.get("title") or "Insight").split())[:80]
    card = {"type": "iframe", "url": url, "aspect_ratio": f"{ratio}%"}
    if not whole:
        card["title"] = title
    return card


_VIEW_GONE = ("That view is no longer on the dashboard — reopen Share to "
              "pick again.")


def _place_card(config: dict, index: int, card: dict) -> str:
    """Add `card` to view `index` of a stored dashboard config, in place.

    A sections view holds its cards in sections, so the card arrives as a
    section of its own rather than being dropped into somebody's grid
    between two cards they arranged. A classic view takes it at the end.
    Answers with the view's title.
    """
    views = config.get("views")
    if not isinstance(views, list) or not (0 <= index < len(views)) \
            or not isinstance(views[index], dict):
        raise ValueError(_VIEW_GONE)
    view = views[index]
    if view.get("type") == "sections":
        sections = view.get("sections")
        if not isinstance(sections, list):
            sections = view["sections"] = []
        sections.append({"type": "grid", "cards": [card]})
    else:
        cards = view.get("cards")
        if not isinstance(cards, list):
            cards = view["cards"] = []
        cards.append(card)
    return str(view.get("title") or view.get("path") or f"View {index + 1}")


async def h_card_to_dashboard(request: web.Request) -> web.Response:
    insight_id = request.match_info["id"]
    insight = await asyncio.to_thread(_read_json, _insight_path(insight_id))
    if insight is None or not insight.get("html"):
        raise web.HTTPNotFound(text="no such card")
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected an object")
    url_path = body.get("url_path") or None
    if url_path is not None and not re.match(r"^[a-z0-9][a-z0-9_-]{0,63}$",
                                             str(url_path)):
        raise web.HTTPBadRequest(text="bad dashboard")
    try:
        index = int(body.get("view", 0))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="bad view")
    whole = body.get("show", "card") != "chart"
    if not await asyncio.to_thread(_sync_card_mirrors):
        raise web.HTTPConflict(
            text="brAIn could not write to /config/www, so Home Assistant has "
                 "nothing to show on a dashboard. Check the /config mount.")
    card = _dashboard_card(insight, whole, body.get("aspect"))
    import aiohttp  # noqa: PLC0415 — deferred, as every Core call here is
    import ha_data  # noqa: PLC0415
    async with aiohttp.ClientSession() as session:
        got = (await ha_data._ws_calls(
            session, [{"type": "lovelace/config", "url_path": url_path}]))[0]
        reason = _unwritable_reason({"mode": "storage"}, got)
        if reason:
            raise web.HTTPConflict(text=reason)
        config = got["result"]
        try:
            view_title = _place_card(config, index, card)
        except ValueError:
            raise web.HTTPConflict(text=_VIEW_GONE)
        saved = (await ha_data._ws_calls(session, [
            {"type": "lovelace/config/save", "url_path": url_path,
             "config": config}]))[0]
    if not saved["ok"]:
        raise web.HTTPConflict(
            text=f"Home Assistant would not save the dashboard "
                 f"({saved['error'] or 'no answer'}).")
    # Three strings that arrived from outside this process — a route
    # parameter, a request body and somebody's dashboard config — each
    # flattened to one line before it reaches the log.
    log.info("card %s added to dashboard %s, view %s",
             *(str(v).replace("\r", " ").replace("\n", " ")[:80]
               for v in (insight_id, url_path or "(default)", view_title)))
    return web.json_response({"added": True, "view": view_title,
                              "url_path": url_path, "card": card})


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


def _record_manual(snapshot: dict, now: float) -> int:
    """File the manual actions this pass saw, for the curiosity miner.

    The fourth of these and the widest in domain but the narrowest in
    claim: only what a *person* or a *voice command* caused, only on the
    domains where reaching for a control is a decision, and never on the
    ones `manual_ledger.EXCLUDED` refuses to be curious about. Same shape
    and the same reason as `_record_overrides`: the window is a day and
    the question is about a fortnight.
    """
    mined = snapshot.get("actions") or {}
    if not mined.get("available"):
        # "I could not look" is not "nobody did anything" — `clear_resolved`'s
        # rule, and here it is the difference between a quiet house and a
        # logbook that 404'd.
        return 0
    try:
        return manual_ledger.record(mined.get("actions") or [], now)
    except Exception as exc:  # noqa: BLE001 — accounting must not fail the
        # pass it is accounting for; same rule as `journal.record`.
        log.warning("could not file this pass's manual actions: %s", exc)
        return 0


async def _triage_findings(now: float) -> list[dict]:
    """Look at the rows nothing has looked at yet, and move them.

    Returns the rows that are on the list afterwards — the ones a run
    elevated plus the ones nothing could judge — because that is exactly
    the set `_announce_findings` is owed and deriving it a second time
    from the store would be a second answer to the same question.

    **It reads what is WAITING, not what a caller just filed.** Five
    producers gate now (`triage.gate`) and one of them is a tab fetch
    that must not spend a Claude run, so a drain that could only judge
    its own caller's rows would leave that producer's findings to the
    stale sweep an hour later. Taking the queue from the store instead
    makes the drain callable from anywhere: whoever runs next picks up
    whatever is there.

    **Every failure surfaces.** No credential, the automatic switch off,
    the budget spent, the run failed, the reply unparseable, a row the
    reply did not mention: each of those ends with the finding on the tab
    carrying an `untriaged` verdict. A triage that could not look must
    never be able to hide a problem, which is `clear_resolved`'s rule
    moved one step earlier. What does NOT surface immediately is the
    surplus past `MAX_BATCH` — it is at the front of the next drain a
    minute later, and the stale sweep is the promise that a queue which
    stopped draining is still shown.

    The stale sweep is here rather than in a loop of its own for the same
    reason, and `STALE_S` is best read as **the longest a finding may be
    invisible**: a queue that is draining clears in minutes, so a row that
    has waited an hour waited it because nothing was coming back — a panel
    that died mid-judgement, or one that was off. It surfaces saying so
    rather than taking its turn, because it has already been invisible for
    the hour and another minute is not what it is owed.

    Two drains at once would spend two runs on one queue and race over
    the same rows, so the flag is set SYNCHRONOUSLY before the first
    await — `start_auth_check`'s rule, for its reason: `create_task` and
    `await` both only schedule, and a guard reading a state its own call
    has not set yet is no guard. A caller that loses is not an error and
    files nothing: its rows are in the queue the winner is draining, or
    in the one the next minute drains.
    """
    if TRIAGE_STATE["running"]:
        return []
    TRIAGE_STATE["running"] = True
    try:
        return await _triage_drain(now)
    finally:
        TRIAGE_STATE["running"] = False


async def _triage_drain(now: float) -> list[dict]:
    """`_triage_findings` with the in-flight guard already held."""
    # Anything left waiting past the hour, whether or not this drain has
    # a batch of its own. Promoted first, so a row that has already waited
    # that long does not queue behind rows filed since.
    stale = await asyncio.to_thread(findings_store.stale_triaging,
                                    now - triage.STALE_S)
    surfaced: list[dict] = []
    if stale:
        log.warning("triage: %d finding(s) were left unjudged and are being "
                    "shown as they are", len(stale))
        surfaced += await asyncio.to_thread(
            findings_store.record_triage,
            {ts: ("untriaged", triage.UNJUDGED) for ts in stale},
            "", now)

    # Oldest first, and everything that is waiting rather than everything
    # this caller filed. The stale rows above have already left the queue
    # by the time it is read, so they cannot be judged twice.
    pending = await asyncio.to_thread(findings_store.awaiting_triage)
    if not pending:
        return surfaced

    # What does not fit waits for the next drain. Surfacing it unjudged
    # would spend the cap on exactly the rows this exists to catch, and
    # on the busiest houses first; waiting is only silence if nothing
    # comes back, and `STALE_S` is what says something does.
    batch = pending[:triage.MAX_BATCH]

    # One clock up from `MAX_BATCH`: a day that has spent `MAX_PER_DAY`
    # runs waits for tomorrow rather than surfacing unjudged, for the
    # same reason, and `STALE_S` is still the promise that a queue which
    # stopped draining is shown. Said once per day, or a busy house logs
    # the same line every minute until midnight.
    if _triage_runs_today(now) >= triage.MAX_PER_DAY:
        if not TRIAGE_STATE.get("capped_said"):
            TRIAGE_STATE["capped_said"] = True
            log.warning("triage has spent its %d runs for today; %d rows wait "
                        "for tomorrow's drain", triage.MAX_PER_DAY, len(pending))
        return surfaced
    TRIAGE_STATE["capped_said"] = False

    # The three gates every scheduled Claude run answers to (`_ask_why`'s
    # rule): a credential, the automatic switch, and the usage budget.
    # Failing one is not a reason to hide anything — it is a reason to
    # show everything, which is what the sentence on the card says.
    settings = settings_store.load()
    if not engine.get_auth():
        excuse = triage.NO_CREDENTIAL
    elif not settings["auto_enabled"]:
        excuse = triage.PAUSED
    elif usage_store.budget_state(settings)["blocked"]:
        excuse = triage.NO_BUDGET
    else:
        excuse = ""
    if excuse:
        # Over the WHOLE queue rather than this batch: the cap is what one
        # run may read, and a gate that answered before any run started
        # has nothing to ration. Rationing it would leave the rest waiting
        # on a drain that will give the identical answer next minute.
        return surfaced + await asyncio.to_thread(
            findings_store.record_triage,
            {int(f["ts"]): ("untriaged", excuse) for f in pending}, "", now)

    prompt = triage.frame(
        batch,
        house=await _house_prompt_block(now),
        # The load-bearing half. "That contact is on a cupboard nobody
        # opens" is exactly the kind of thing a homeowner has already
        # said once, and a triage run that cannot read it re-litigates
        # every correction they have ever made.
        memory=await asyncio.to_thread(
            _memory_block,
            entities=[r.get("entity_id") for r in batch if r.get("entity_id")]),
    )
    TRIAGE_STATE["runs"] = _triage_runs_today(now) + 1
    try:
        result = await _claude(
            engine.run_analyst, prompt, triage.SYSTEM, eff_model(),
            triage.TIMEOUT_S, triage.MAX_TURNS, "triage",
            job="triage", schema=triage.SCHEMA)
    except Exception as exc:  # noqa: BLE001 — the findings are already
        # filed; what is at stake here is only whether anything looked.
        log.warning("a triage run failed: %s", exc)
        result = {"ok": False, "error": str(exc)}
    run_id = str((result.get("meta") or {}).get("session_id") or "")
    if not result.get("ok"):
        return surfaced + await asyncio.to_thread(
            findings_store.record_triage,
            {int(f["ts"]): ("untriaged", triage.RUN_FAILED)
             for f in batch}, run_id, now)

    verdicts = triage.parse(_answer(result), len(batch))
    decided: dict[int, tuple[str, str]] = {}
    for i, row in enumerate(batch, 1):
        ts = int(row["ts"])
        if i in verdicts:
            decided[ts] = verdicts[i]
        else:
            # A row the reply skipped. The default is the finding, not
            # the silence: "it was not mentioned" is not "it is not real".
            decided[ts] = ("untriaged", triage.NOT_MENTIONED)
    moved = await asyncio.to_thread(
        findings_store.record_triage, decided, run_id, now)
    held = [f for f in moved if f["status"] == "held"]
    # No journal line of its own: `engine._run_cli` already writes one per
    # invocation under the source it was given, and a second row for the
    # same run is two answers to "how many triage runs happened".
    log.info("triage: %d looked at, %d held back, %d shown, %d still waiting",
             len(batch), len(held), len(moved) - len(held),
             max(len(pending) - len(batch), 0))
    return surfaced + [f for f in moved if f["status"] != "held"]


# ---------------------------------------------------------------------------
# The Resident — signals in, one cheap look, a case
# ---------------------------------------------------------------------------
#
# Three rules, and every function below is written against them.
#
# **Nothing here changes a house.** The strongest thing a verdict can buy is
# a CASE — a claim in front of a person with the endings on it — and `act`
# means file one and say so on a phone. Today's plan → consent → apply path
# stays the only route from a model to somebody's `/config`, which is the
# hardening this add-on's trustworthiness rests on and which a loop that
# could call a service unattended would throw away in one release.
#
# **A gate holds the batch; it never drops it.** No credential, the
# automatic switch off, the usage window spent: each means no run is
# spawned and the signals WAIT, bounded by `RESIDENT_QUEUE_MAX`. What keeps
# that honest for a row a rule filed is `triage.STALE_S` — a finding left
# waiting past the hour surfaces carrying the sentence that says nothing
# looked at it. Waiting is only silence if nothing comes back.
#
# **Silence surfaces.** `resident.parse_first_look` answers for every index
# whatever came back, and a `check` signal only ever leaves `triaging` for
# `held` when a reply that parsed said `ignore` about that row. A skipped
# row, an unreadable reply and a run that failed all end with the finding
# on the list carrying the reason.


def _resident_offer(signal: dict | None) -> bool:
    """Hand one signal to the Resident. Never blocks and never raises.

    Called from inside the event bus's socket pump, where anything that
    waits stops the read — so the producer side is one `put_nowait` onto an
    unbounded queue and nothing else. The cap, the dedupe and the ranking
    are the tick's, because all three need the whole set in one place and
    none of them may run per event on the loop that also drives the chat
    stream and the terminal proxy.
    """
    if not isinstance(signal, dict) or signal.get("kind") not in signals.KINDS:
        return False
    try:
        RESIDENT_QUEUE.put_nowait(signal)
    except asyncio.QueueFull:  # pragma: no cover — the queue is unbounded
        return False
    return True


def _resident_offer_many(rows, adapter, *args) -> int:
    """`adapter` over each row, onto the queue. Returns how many landed.

    Every adapter answers None for a row it has nothing to say about, which
    is the whole filter — so the count is what was offered rather than what
    was handed in, and the difference is the adapter doing its job. A row
    that makes an adapter raise is logged and skipped: a producer's bad row
    must not take down the pass that found it, which is `journal.record`'s
    rule one loop over.
    """
    offered = 0
    for row in rows or []:
        try:
            signal = adapter(row, *args)
        except Exception as exc:  # noqa: BLE001 — see the docstring
            log.debug("could not build a signal from a row: %s", exc)
            continue
        if _resident_offer(signal):
            offered += 1
    return offered


# Which adapter a findings row goes through, by the producer that filed it.
#
# A row is a row, and `from_finding` takes any of them — but the three
# measurement stores have adapters of their own and the difference is the
# WEIGHT, which is the kind: a room that will be at freezing by morning
# outranks a tidy-up (`thermal` 0.24 against `check` 0.20) and a dishwasher
# waiting to be emptied is below both (`appliance` 0.10), which is the same
# judgement `notify_router` already makes about the same producers. Reading
# them all as `check` would flatten that and leave the ordering to severity
# alone, which is the axis this table exists to be separate from.
_FINDING_ADAPTERS = (
    ("check:climate.", signals.from_thermal),
    ("check:chore.", signals.from_appliance),
    ("check:base.", signals.from_baseline),
)


def _signal_for_finding(row: dict, now: float,
                        ctx: signals.RegistryContext) -> dict | None:
    """One findings row as a signal, through whichever adapter fits it."""
    source = str(row.get("source") or "")
    for prefix, adapter in _FINDING_ADAPTERS:
        if source.startswith(prefix):
            return adapter(row, now, ctx)
    return signals.from_finding(row, now, ctx)


def _pending_finding_ts() -> set[int]:
    """The findings already waiting for a look, by row id.

    Two producers offer a check row — the pass that filed it and the sweep
    of `awaiting_triage()` on every tick — so the same finding arrives
    twice by construction. It is deduped on the ROW rather than by
    `signals.dedupe`, which folds by `(kind, subject)` and would take two
    different rules' rows about one sensor for one signal, leaving the
    other to the stale sweep an hour later: a row nobody is shown is the
    one outcome this loop must not produce.
    """
    return {int(s["finding_ts"]) for s in RESIDENT_PENDING
            if s.get("finding_ts")} | set(RESIDENT_INFLIGHT)


def _offer_findings(rows: list[dict], now: float) -> int:
    """Rows a producer filed, as signals — each offered exactly once.

    `finding_ts` is carried BESIDE the published signal keys rather than on
    them: `signals.SIGNAL_KEYS` is a closed set on purpose, and a check
    signal's subject is an entity id or a check id (`from_finding` says so),
    so the row's own id has nowhere else to ride. It is what
    `record_triage` keys the verdict on, and reading it back out of a
    subject string would be a second answer to "which row is this".
    """
    have = _pending_finding_ts()
    ctx = _signal_context()
    offered = 0
    for row in rows or []:
        ts = int(row.get("ts") or 0)
        if not ts or ts in have:
            continue
        try:
            signal = _signal_for_finding(row, now, ctx)
        except Exception as exc:  # noqa: BLE001 — `_resident_offer_many`'s rule
            log.debug("could not build a signal from finding %s: %s", ts, exc)
            continue
        if signal is None:
            continue
        RESIDENT_PENDING.append({**signal, "finding_ts": ts})
        have.add(ts)
        offered += 1
    return offered


# How far outside its own measured band a reading has to be before it is
# worth a LINE IN A BATCH, which is a much lower bar than being worth a
# card: `checks/baseline.unusual` needs six spreads (nine off the whole
# history) and files a finding, and everything under that is dropped by a
# floor nobody can argue with. Those are exactly the readings the first
# look exists to judge — "three spreads on the freezer" is a sentence a
# model can weigh against what the house has said about that freezer, and
# a threshold cannot.
MEASURED_SPREADS = 3.0
# …and how many of them one pass may offer. Past a handful the measurement
# has stopped describing the house (a heating season starting, a meter
# replaced), which is `base.unusual`'s own `MAX_ROWS` argument one floor
# down: fifty signals about a shifted baseline is a batch spent on the
# measurement rather than on the home.
MAX_MEASURED_SIGNALS = 6


def _measurement_signals(snapshot: dict, now: float) -> int:
    """Readings outside their band that no rule filed anything about.

    **Never a fetch.** Everything here is arithmetic over the baseline
    store and the states the checks pass has already collected, which is
    what makes it free — a measurement pass that went and asked the
    recorder would be minutes of work inside the attention loop, which is
    the thing this whole design exists to stop doing.

    The thermal and appliance stores have no sub-threshold answer to offer
    the same way: what `climate.window` and `chore.waiting` read is a live
    five-minute series the pass fetched *for those checks*, and a second
    reading of it here would be a second floor over the same numbers. Their
    rows reach the look as the findings they already are, through
    `_FINDING_ADAPTERS`, weighted as the measurements they are.
    """
    store = snapshot.get("baselines") or {}
    entities = store.get("entities") or {}
    states = snapshot.get("states") or {}
    if not entities or not states:
        return 0
    try:
        tz, _name = baselines.house_timezone()
        bucket = baselines.hour_of_week(now, tz)
    except Exception as exc:  # noqa: BLE001 — a signal is optional
        log.debug("could not bucket the baselines: %s", exc)
        return 0
    ctx = _signal_context()
    hits: list[tuple[float, dict]] = []
    for eid, baseline in entities.items():
        st = states.get(eid) or {}
        try:
            value = float(st.get("state"))
        except (TypeError, ValueError):
            continue
        found = baselines.deviation(value, baseline, bucket)
        if not found or abs(found["sigmas"]) < MEASURED_SPREADS:
            continue
        unit = baseline.get("unit") or ""
        hits.append((abs(found["sigmas"]), {
            "entity_id": eid,
            "text": (f"{eid} is reading {found['value']:g}{unit}, "
                     f"{abs(found['sigmas']):.1f} spreads from its usual "
                     f"{found['median']:g}{unit}"),
            "value": found["value"],
            "deviation": round(found["sigmas"], 2),
            "source": f"baseline:{found['source']}",
            "ts": now,
        }))
    if not hits or len(hits) > MAX_MEASURED_SIGNALS:
        return 0
    hits.sort(key=lambda h: -h[0])
    return _resident_offer_many([row for _s, row in hits],
                                signals.from_baseline, now, ctx)


def _note_safety(event_type: str, data: dict) -> None:
    """Remember that a leak, smoke, CO or gas sensor has tripped, and file it.

    The event bus's raw hook. Two jobs, and the second is the one that
    matters.

    **It keeps the index the `act` verdict reads** — `SAFETY_SUBJECTS`, what
    is tripped NOW, recorded at the moment the bus admitted the event and
    pruned, because a fetch inside the attention loop is the thing this
    design exists to avoid.

    **And a TRANSITION into a tripped state starts the safety lane**
    (`_safety_trip`), which files a critical case and notifies with no
    model, no credential, no budget and no day cap in the way. Before this
    a tripped leak sensor reached a phone only if a Haiku look ran, parsed
    and answered exactly `act` — and the real floor was `watch`, because
    the never-ignore guard matched words in the signal's kind and a bus
    signal's kind is `state`. A model may add context to a leak afterwards;
    it may not decide whether anybody hears about it. A transition OUT is
    the sensor saying it is over, which `_safety_clear` writes on the card
    and uses to stop the reminders.

    Synchronous and never awaits: it runs inside the bus's socket pump, so
    the lane is a task scheduled onto the loop that pump is already on.
    """
    if event_type != "state_changed" or not isinstance(data, dict):
        return
    entity = str(data.get("entity_id") or "").strip()
    new_state = data.get("new_state")
    if not entity or not isinstance(new_state, dict):
        return
    attrs = new_state.get("attributes")
    attrs = attrs if isinstance(attrs, dict) else {}
    klass = signals.RegistryContext.safety_class(attrs)
    if not klass:
        return
    now = time.time()
    tripped = _is_tripped(new_state)
    old_state = data.get("old_state")
    was = _is_tripped(old_state) if isinstance(old_state, dict) else False
    if tripped:
        SAFETY_SUBJECTS[entity] = now
    else:
        # A leak detector going dry is the sensor saying it is over, so the
        # subject stops being one rather than ageing out — the opposite
        # direction to every other index in this file, and for the same
        # reason that made the trip hot in the first place.
        SAFETY_SUBJECTS.pop(entity, None)
    for old, at in list(SAFETY_SUBJECTS.items()):
        if now - at > SAFETY_SUBJECT_TTL_S:
            SAFETY_SUBJECTS.pop(old, None)
    while len(SAFETY_SUBJECTS) > MAX_SAFETY_SUBJECTS:
        SAFETY_SUBJECTS.pop(min(SAFETY_SUBJECTS, key=SAFETY_SUBJECTS.get), None)
    if tripped and not was:
        _schedule_safety(_safety_trip(entity, klass, new_state, now))
    elif was and not tripped:
        _schedule_safety(_safety_clear(entity, new_state, now))


def _is_tripped(state: dict | None) -> bool:
    return isinstance(state, dict) and str(state.get("state") or "").strip(
        ).lower() in signals.HOT_SAFETY_STATES


# The lane's tasks, held so the loop cannot collect one mid-flight — a bare
# `create_task` is only weakly referenced, and a leak whose case was
# garbage-collected before it was filed is the failure this lane exists for.
_SAFETY_TASKS: set = set()


def _schedule_safety(coro) -> None:
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        # No running loop: a test driving the hook alone, or a pump being
        # torn down. The coroutine is closed rather than leaked; the index
        # above is still written, which is what a test of the hook reads.
        coro.close()
        return
    _SAFETY_TASKS.add(task)
    task.add_done_callback(_SAFETY_TASKS.discard)


# One case per TRIP, not per sensor. A detector that chatters on and off
# inside this window is one event — a leak cable that is wet and wicking
# reports `on`/`off` for minutes — and a second card about it is noise
# that teaches somebody to swipe the third one away. Past the window, a
# new trip is a new case, whatever happened to the last one: a person who
# dismissed Tuesday's leak has not dismissed Friday's.
SAFETY_DEBOUNCE_S = 300
# Entity → {"at": when the trip was filed, "ts": the case's id}. In memory:
# losing it on a restart costs at most one extra card for a sensor that is
# still chattering, and the other direction (a stamp read off disk wrongly
# suppressing a real trip) is the one this lane may not have.
SAFETY_TRIPS: dict[str, dict] = {}
SAFETY_STATE: dict = {"filed": 0, "repeats": 0, "cleared": 0,
                      "fallback": 0, "last_at": 0, "last_error": ""}
SAFETY_LABELS = {"moisture": "Water leak", "smoke": "Smoke",
                 "carbon_monoxide": "Carbon monoxide", "gas": "Gas"}
SAFETY_FIX = ("Go and look. brAIn does not act on smoke, water or gas on its "
              "own — a playbook you accepted on the Proposals tab is what "
              "closes a valve.")


def _safety_case_row(entity: str, klass: str, state: dict,
                     when: float) -> dict:
    """The case one trip files, written deterministically.

    The TEXT carries the local date and time, which is what makes each trip
    its own row: the store dedupes by normalised text against every status
    and the settled ledger, so a fixed sentence ("Friendly → on") made the
    second leak on the same sensor a duplicate of the first for ever, and a
    dismissal of Tuesday's leak silently swallowed every later one.
    """
    attrs = state.get("attributes") if isinstance(state.get("attributes"),
                                                  dict) else {}
    name = str(attrs.get("friendly_name") or entity).strip()[:80]
    local = _local_now(when)
    # Spelled out rather than `%-d`, which glibc understands and musl —
    # the image's libc — does not promise to.
    stamp = f"{local:%a} {local.day} {local:%b}, {local:%H:%M}"
    label = SAFETY_LABELS.get(klass, "Safety sensor tripped")
    text = f"{label} detected by {name} ({stamp})"
    return {
        "text": text,
        "claim": text,
        "detail": (f"{name} reported {state.get('state')} at {stamp}. This "
                   "was sent the moment the sensor tripped, without waiting "
                   "for anything to look at it."),
        "kind": "problem",
        "severity": "critical",
        "stakes": "high",
        "confidence": 1.0,
        "entity_id": entity,
        "fixable": False,
        "source": SAFETY_SOURCE,
        "source_title": "Safety sensors",
        "evidence": [{"entity": entity, "value": str(state.get("state") or ""),
                      "when": stamp}],
        "actions": [dict(SAFETY_ACTION)],
        "fix": SAFETY_FIX,
    }


async def _safety_trip(entity: str, klass: str, state: dict,
                       when: float) -> dict | None:
    """File and announce one trip. Never raises; returns the case or None.

    No gate is asked, deliberately: a credential, the automatic switch and
    the usage budget all exist to stop brAIn SPENDING, and this spends
    nothing. Escalation is `notify_router.tier_of`'s — `critical` with the
    `safety` producer's `now` urgency — so it goes through quiet hours and
    climbs the reminder ladder like every other escalating row. With no
    notify service configured it still reaches Home Assistant, as a
    persistent notification, because "nobody configured a phone" is not a
    reason for a leak to be reported to nobody.
    """
    try:
        prior = SAFETY_TRIPS.get(entity)
        if prior and when - float(prior.get("at") or 0) < SAFETY_DEBOUNCE_S:
            row = await asyncio.to_thread(findings_store.get,
                                          int(prior.get("ts") or 0))
            if row is not None:
                SAFETY_STATE["repeats"] += 1
                return None
        filed = await asyncio.to_thread(
            findings_store.add_case,
            _safety_case_row(entity, klass, state, when), when=when)
        if filed is None:
            SAFETY_STATE["repeats"] += 1
            return None
        SAFETY_TRIPS[entity] = {"at": when, "ts": int(filed["ts"])}
        SAFETY_STATE["filed"] += 1
        SAFETY_STATE["last_at"] = int(when)
        log.warning("safety lane: %s", filed["text"])
        service, _sev = _findings_notify_target()
        if service:
            await _announce_findings([filed])
        else:
            await _safety_fallback_notice(filed)
        return filed
    except Exception as exc:  # noqa: BLE001 — never let a pump task raise
        SAFETY_STATE["last_error"] = str(exc)[:200]
        log.warning("safety lane failed for %s: %s", entity, exc)
        return None


async def _safety_fallback_notice(filed: dict) -> None:
    """Home Assistant's own notification, for a house with no notify target."""
    import ha_data
    try:
        await ha_data.call_core_service(
            "persistent_notification", "create",
            {"title": "brAIn: " + str(filed.get("text") or "")[:120],
             "message": (str(filed.get("detail") or "") + "\n\n"
                         + SAFETY_FIX),
             "notification_id": f"brain_safety_{int(filed.get('ts') or 0)}"},
            timeout=15)
        SAFETY_STATE["fallback"] += 1
    except Exception as exc:  # noqa: BLE001 — the case is on the list
        SAFETY_STATE["last_error"] = str(exc)[:200]
        log.warning("safety lane: could not create a persistent "
                    "notification: %s", exc)


async def _safety_clear(entity: str, state: dict, when: float) -> bool:
    """The sensor reported clear: say so on the card and stop the ladder.

    The case is NOT cleared, which is the one place this lane parts from
    `clear_resolved`: a leak that dried by itself still came from
    somewhere, and a smoke alarm that stopped is not evidence there was no
    smoke — somebody still owes it a look. What stops is the reminders,
    because a phone told three more times about a sensor that says it is
    over is being argued with.
    """
    try:
        trip = SAFETY_TRIPS.get(entity) or {}
        ts = int(trip.get("ts") or 0)
        if not ts:
            return False
        stamp = f"{_local_now(when):%H:%M}"
        row = await asyncio.to_thread(
            findings_store.annotate, ts,
            f"The sensor reported {state.get('state') or 'clear'} at {stamp}.")
        await asyncio.to_thread(notify_router.stop_escalation, ts)
        if row is not None:
            SAFETY_STATE["cleared"] += 1
        return row is not None
    except Exception as exc:  # noqa: BLE001 — see `_safety_trip`
        SAFETY_STATE["last_error"] = str(exc)[:200]
        log.debug("safety lane clear for %s failed: %s", entity, exc)
        return False


def _safety_case_for(signal: dict) -> int:
    """The id of the live case the lane filed for this signal's trip, or 0."""
    trip = SAFETY_TRIPS.get(str((signal or {}).get("subject") or "")) or {}
    ts = int(trip.get("ts") or 0)
    if not ts:
        return 0
    try:
        return ts if findings_store.get(ts) is not None else 0
    except Exception:  # noqa: BLE001
        return 0


def _is_safety_signal(signal: dict) -> bool:
    """Whether this signal is about a safety sensor that is tripped now."""
    return str(signal.get("subject") or "") in SAFETY_SUBJECTS


_KNOWN_ENTITIES: dict = {"at": 0.0, "ids": frozenset()}
_SIGNAL_CTX: dict = {"at": 0.0, "ctx": signals.EMPTY_CONTEXT}
# Entity ids as Home Assistant writes them, for READING the memory document
# rather than for validating anything: `ha_data.is_entity_id` is the
# authority wherever an id is acted on, and nothing here acts on one.
_MEMORY_ENTITY_RE = re.compile(r"\b[a-z_]{3,}\.[a-z0-9_]{2,}\b")


def _known_entity_ids() -> frozenset[str]:
    """The entity ids brAIn already holds a fact about.

    A callable rather than a set because the answer changes while the bus
    runs — a fact filed this afternoon is what makes this evening's state
    change worth a line in a batch — and a listener holding a snapshot from
    boot would be deaf to every one of them.

    Read off the memory document and the facts ledger, which is where those
    facts are, and cached for the bus's own context interval: this walks a
    32 KB file and a JSON store, and the bus asks once every five minutes.
    Every way of failing answers with what it had, because "I could not
    look" is not "brAIn knows nothing about this house" — and the cost of
    the wrong answer here is one state change that did not become a line.
    """
    now = time.time()
    if now - float(_KNOWN_ENTITIES["at"]) < eventbus.CTX_REFRESH_S:
        return _KNOWN_ENTITIES["ids"] | _world_known_ids()
    text = ""
    try:
        text = _read_shared_memory()
    except Exception as exc:  # noqa: BLE001
        log.debug("could not read memory for the known-entity set: %s", exc)
    try:
        text += "\n" + "\n".join(
            str(f.get("text") or "") for f in knowledge_store.list_facts())
    except Exception as exc:  # noqa: BLE001
        log.debug("could not read the facts ledger: %s", exc)
    if not text.strip():
        return _KNOWN_ENTITIES["ids"] | _world_known_ids()
    _KNOWN_ENTITIES["ids"] = frozenset(_MEMORY_ENTITY_RE.findall(text.lower()))
    _KNOWN_ENTITIES["at"] = now
    # And the entities a confident `world_model` reading ranked as worth
    # watching: a water valve nobody has written a fact about yet is still
    # the thing a leak night is about.
    return _KNOWN_ENTITIES["ids"] | _world_known_ids()


def _signal_context() -> signals.RegistryContext:
    """What the adapters ask about an entity, rebuilt on the bus's interval.

    The same object the event bus builds for itself, for the producers that
    are not the bus: a checks pass and an override both want to know
    whether an entity is protected and whether brAIn holds a fact about it,
    and two answers to "may brAIn touch this" is the one that acts being
    wrong. The protected list is parsed by `automation_writer` and never by
    a second matcher here, which is `eventbus._refresh_context`'s rule.
    """
    now = time.time()
    if now - float(_SIGNAL_CTX["at"]) < eventbus.CTX_REFRESH_S:
        return _SIGNAL_CTX["ctx"]
    try:
        patterns = automation_writer.protected_patterns()
    except Exception as exc:  # noqa: BLE001 — "I could not look" is not
        # "nothing is protected": the previous context stands.
        log.debug("could not read the protected list: %s", exc)
        return _SIGNAL_CTX["ctx"]
    _SIGNAL_CTX["ctx"] = signals.RegistryContext(
        patterns, _known_entity_ids(), built_at=now,
        added_safety=_world_safety_roles())
    _SIGNAL_CTX["at"] = now
    return _SIGNAL_CTX["ctx"]


def _signal_entities(signal: dict) -> list[str]:
    """The entity ids one signal is about: its subject and its evidence."""
    out: list[str] = []
    subject = str((signal or {}).get("subject") or "")
    if subject:
        out.append(subject)
    for row in (signal or {}).get("evidence") or []:
        # `entity` is what `signals.evidence_row` writes; `entity_id` is
        # read too for a row built by hand. It read only `entity_id`, so
        # every evidence entity was missing from the memory retrieval an
        # investigation was handed.
        eid = (row.get("entity") or row.get("entity_id")) if isinstance(
            row, dict) else row
        if isinstance(eid, str) and eid and eid not in out:
            out.append(eid)
    return out


# The registry the facts tagger reads: the entity ids and area names the
# last checks pass saw. Refreshed from the snapshot that pass already
# fetched, never fetched for the tagger's own sake — it runs on the
# minute over every queued line, and a registry read per minute is a
# request nobody asked for.
_FACTS_CTX: dict = {"entities": frozenset(), "areas": {},
                    "entity_areas": {}, "at": 0.0}
# How old the registry the facts store reads may be before "this entity is
# not in the house" stops being a claim it can make. Two checks passes at
# the default interval: a registry read once and never again is a list
# that was true on a Tuesday.
FACTS_REGISTRY_FRESH_S = 13 * 3600

# What every entity the last checks pass saw is CALLED, and where it is:
# `{entity_id: {"name": ..., "area": ...}}`. The feed reads it so a card
# says "Laundry Room Countertop" rather than `light.laundry_room_countertop`
# — a check's own sentence already uses the friendly name, but a Resident
# claim, a fix and every evidence row name the id, and an id is a thing a
# person has to translate before they can read the card. Refreshed from
# the snapshot that pass already fetched, `_FACTS_CTX`'s rule: never a
# registry read for the feed's own sake.
_NAMES: dict[str, dict] = {}
# Entity ids in prose. The same shape `ha_data.ENTITY_ID_RE` accepts,
# bounded so `e.g.` and a version number do not read as one.
_ENTITY_IN_TEXT_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")


def _note_registry(snapshot: dict) -> None:
    try:
        states = snapshot.get("states") or {}
        areas = {a["area_id"]: a.get("name") or a["area_id"]
                 for a in (snapshot.get("areas") or []) if a.get("area_id")}
        # Which room each entity is in, by area ID — the key a fact about a
        # room is filed under (`area:<id>`). A run is handed entities and
        # asks for the facts about them, and "the lounge gets cold in the
        # afternoon" is a fact about the lounge thermometer's room that no
        # caller could reach: none of them passed an area, ever.
        devices = {d["id"]: d.get("area_id") for d in
                   (snapshot.get("devices") or []) if d.get("id")}
        entity_areas: dict[str, str] = {}
        for row in snapshot.get("entities") or []:
            eid = row.get("entity_id")
            if not eid:
                continue
            area = row.get("area_id") or devices.get(row.get("device_id") or "")
            if area:
                entity_areas[eid] = area
        _FACTS_CTX.update(entities=frozenset(states), areas=areas,
                          entity_areas=entity_areas, at=time.time())
    except Exception as exc:  # noqa: BLE001
        log.debug("facts registry note failed: %s", exc)
    try:
        house = House(snapshot)
        names = {}
        for eid in set(house.states) | set(house.registry):
            names[eid] = {"name": house.name(eid), "area": house.area_of(eid)}
        _NAMES.clear()
        _NAMES.update(names)
    except Exception as exc:  # noqa: BLE001
        log.debug("names note failed: %s", exc)
    _note_world(snapshot)


def _entity_names_in(*texts: str) -> dict[str, dict]:
    """The names for every known entity id mentioned in these strings."""
    out: dict[str, dict] = {}
    for text in texts:
        for m in _ENTITY_IN_TEXT_RE.finditer(str(text or "")):
            eid = m.group(0)
            row = _NAMES.get(eid)
            if row is not None:
                out[eid] = row
    return out


def _ingest_facts() -> int:
    try:
        created = facts_store.ingest_inbox(
            MEMORY_INBOX_DIR, MEMORY_INBOX_DIR / "processed",
            known_entities=_FACTS_CTX["entities"], areas=_FACTS_CTX["areas"])
    except Exception as exc:  # noqa: BLE001
        log.debug("facts ingest failed: %s", exc)
        return 0
    _reconcile_facts()
    return created


def _reconcile_facts(force: bool = False) -> dict:
    """Make the facts store answer to the document and the registry.

    On the minute, beside the ingest, and straight after the panel's own
    editor saves — the store is what most runs read, and every way a
    person corrects memory (an edit, `brain memory forget`, `clear`,
    `undo`) changes the document. A document that would not read is
    passed as None, which skips the curation half rather than reading
    every fact as gone (`facts_store.reconcile`).
    """
    try:
        document = SHARED_MEMORY_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        document = ""
    except OSError:
        document = None
    fresh = (bool(_FACTS_CTX["entities"])
             and time.time() - float(_FACTS_CTX["at"]) < FACTS_REGISTRY_FRESH_S)
    try:
        return facts_store.reconcile(
            document, MEMORY_INBOX_DIR,
            known_entities=_FACTS_CTX["entities"], registry_fresh=fresh,
            force=force)
    except Exception as exc:  # noqa: BLE001 — accounting, not a run
        log.debug("facts reconcile failed: %s", exc)
        return {}


def _areas_of(entities) -> list[str]:
    """The rooms these entities are in, by area id, from the last pass."""
    where = _FACTS_CTX.get("entity_areas") or {}
    out: list[str] = []
    for eid in entities or ():
        area = where.get(str(eid or ""))
        if area and area not in out:
            out.append(area)
    return out


def _finding_subjects(finding: dict, limit: int = 4) -> list[str]:
    """What a finding is about, as the facts store's subjects.

    The row's own entity first — a check knows exactly which one — then
    the entities a case says it read, because a Resident row carries no
    `entity_id` (its claim is written for a person, in friendly names)
    and its evidence is the only machine-readable answer to "about what".
    Only strings shaped like an entity id: an evidence row names what was
    read, and a sentence there is not a subject.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    out: list[str] = []
    eid = str(finding.get("entity_id") or "").strip()
    if ha_data.is_entity_id(eid):
        out.append(eid)
    for row in finding.get("evidence") or []:
        if not isinstance(row, dict):
            continue
        ent = str(row.get("entity") or "").strip()
        if ent not in out and ha_data.is_entity_id(ent):
            out.append(ent)
        if len(out) >= limit:
            break
    return out


def _open_case_rows(limit: int = 12, exclude=None) -> list[str]:
    """What is already in front of the homeowner, as lines for a prompt.

    The commonest reason a signal is worth nothing is that the house is
    already saying it, so both prompts read this — and it is the CASE list
    rather than the findings list, because a proposal and a guess are just
    as much "already said" as a problem is.

    ``exclude`` is the claims to leave out: an investigation sent to look
    at a row must not be told that row is something it may not claim.
    """
    drop = {str(e) for e in (exclude or ()) if e}
    try:
        # Every kind, chores included: an accepted chore is off the feed and
        # is still something the house has already said.
        rows = cases.list_cases("open", kinds=cases.KINDS)
    except Exception as exc:  # noqa: BLE001 — a prompt section, not the run
        log.debug("could not list the open cases: %s", exc)
        return []
    rows = [c for c in rows if c.get("claim") not in drop]
    return [f"[{c['kind']}] {c['claim']}"[:160] for c in rows[:limit]]


def _resident_absorb(now: float) -> None:
    """Drain the queue into the pending list, and hold it to its cap.

    The cap drops the LEAST SALIENT non-hot signal, oldest first among
    equals, and counts what it took. Hot is spared because hot is what
    makes a look happen at all — a cap that could drop the reason for the
    look would be the cap answering the question the look was called to
    answer — and a pending list that is nothing but hot signals is a house
    with one fault rather than five hundred, so past the cap there the
    least salient goes anyway and the count says so.
    """
    while True:
        try:
            RESIDENT_PENDING.append(RESIDENT_QUEUE.get_nowait())
        except asyncio.QueueEmpty:
            break
    # A signal is evidence about a moment, and a day-old moment is not
    # evidence about this afternoon. Dropped rather than judged, because
    # the look's whole answer would be "this already happened" — and
    # counted, because a queue that silently discards is one nobody can
    # trust, which is `eventbus.stats`' rule one tier up.
    stale = [s for s in RESIDENT_PENDING
             if now - float(s.get("seen_at") or now) > RESIDENT_SIGNAL_TTL_S]
    for row in stale:
        RESIDENT_PENDING.remove(row)
        RESIDENT_STATE["dropped"] += 1
    while len(RESIDENT_PENDING) > RESIDENT_QUEUE_MAX:
        cool = [s for s in RESIDENT_PENDING if not s.get("hot")]
        victim = min(cool or RESIDENT_PENDING,
                     key=lambda s: (float(s.get("salience") or 0.0),
                                    -float(s.get("seen_at") or 0.0)))
        RESIDENT_PENDING.remove(victim)
        RESIDENT_STATE["dropped"] += 1
    RESIDENT_STATE["queue_len"] = len(RESIDENT_PENDING)
    RESIDENT_STATE["hot_pending"] = sum(
        1 for s in RESIDENT_PENDING if s.get("hot"))


def _resident_gate(settings: dict) -> str:
    """Why no run may be spawned right now, or "".

    The three gates every scheduled Claude run answers to (`_ask_why`'s
    rule). Failing one HOLDS the batch rather than surfacing it, which is
    the opposite of what `_triage_findings` did with the same three — and
    deliberately: triage was about to hide a row, where this is about to
    look at one and the row is on `triaging` either way. `triage.STALE_S`
    is what makes the wait bounded, and the sweep at the top of every pass
    is what makes it visible.
    """
    if not engine.get_auth():
        return "there is no Claude credential"
    if not settings.get("auto_enabled"):
        return "automatic runs are paused"
    try:
        if usage_store.budget_state(settings)["blocked"]:
            return "the session usage budget is spent"
    except Exception as exc:  # noqa: BLE001 — a budget that cannot be read
        # must not stop the cheap tier: `budget_state` already falls back
        # to an estimate, and a look is the half the plan spends freely.
        log.debug("could not read the budget: %s", exc)
    return ""


async def _resident_stale_sweep(now: float) -> list[dict]:
    """Rows left mid-look past the hour, shown as they are.

    The one thing this loop must not be able to do is leave a problem
    nobody is ever shown, and a gate that holds a batch is exactly how that
    would happen: the rows stay `triaging`, the queue grows, and nothing
    says so. `triage.STALE_S` is best read here as the longest a finding
    may be invisible, and the sentence on the card is `triage.UNJUDGED`
    rather than one this file invented — one vocabulary, because six copies
    is six chances for one of them to stop saying that nothing looked.
    """
    stale = await asyncio.to_thread(findings_store.stale_triaging,
                                    now - triage.STALE_S)
    if not stale:
        return []
    log.warning("the Resident left %d finding(s) unjudged for over %ds; they "
                "are being shown as they were filed", len(stale),
                int(triage.STALE_S))
    return await asyncio.to_thread(
        findings_store.record_triage,
        {ts: ("untriaged", triage.UNJUDGED) for ts in stale}, "", now)


async def _resident_tick(now: float) -> dict:
    """One pass of the attention loop. Returns what it did, for a test.

    Factored out of the loop so it can be driven directly, and guarded
    SYNCHRONOUSLY before the first await — `start_auth_check`'s rule, for
    its reason: `create_task` and `await` both only schedule, so two ticks
    in one turn would each read a flag their own call has not set yet and
    both spawn a run over the same batch.
    """
    if RESIDENT_STATE["running"]:
        return {"skipped": "a look is already in flight"}
    RESIDENT_STATE["running"] = True
    try:
        return await _resident_pass(now)
    except Exception as exc:  # noqa: BLE001 — the loop outlives a pass, and
        # a pass that fell over must not stop the house being watched.
        RESIDENT_STATE["last_error"] = str(exc)[:200]
        log.warning("the Resident's pass failed: %s", exc)
        return {"error": str(exc)[:200]}
    finally:
        RESIDENT_STATE["running"] = False


async def _resident_pass(now: float) -> dict:
    """`_resident_tick` with the in-flight guard already held."""
    surfaced: list[dict] = []
    if now - float(RESIDENT_STATE["last_sweep_at"] or 0.0) >= RESIDENT_SWEEP_S:
        RESIDENT_STATE["last_sweep_at"] = now
        surfaced = await _resident_stale_sweep(now)
        if surfaced:
            await _announce_findings(
                [f for f in surfaced if f["status"] != "held"])
        # Every producer's rows, not just the pass that filed them — the
        # study inbox, a chat's side channel and a tab fetch all file
        # through the gate and none of them runs a checks pass, so a drain
        # that could only read its own caller's rows would leave theirs
        # waiting for hours. `awaiting_triage` is oldest first, which is
        # what makes the batch cap honest: a row that did not fit is at the
        # front of the next one. `run_checks` hands its own rows over the
        # moment it files them, so a pass does not wait on this minute.
        waiting = await asyncio.to_thread(findings_store.awaiting_triage)
        _offer_findings(waiting, now)
    _resident_absorb(now)
    out = {"looked": False, "surfaced": len(surfaced),
           "queue": len(RESIDENT_PENDING)}

    since = now - float(RESIDENT_STATE["last_look_at"] or 0.0)
    hot = RESIDENT_STATE["hot_pending"] > 0
    # The timer, or a hot signal that has waited out the floor. `hot` is
    # the one thing a signal may cause by itself, and `MIN_LOOK_SPACING_S`
    # is what stops a house producing them in a burst looking once per
    # leak sensor.
    look_due = bool(RESIDENT_PENDING) and (
        since >= RESIDENT_LOOK_S or (hot and since >= MIN_LOOK_SPACING_S))
    if not look_due and not RESIDENT_PARKED:
        return out

    settings = await asyncio.to_thread(settings_store.load)
    excuse = _resident_gate(settings)
    if excuse:
        # The batch waits. Said once per reason rather than every tick, or
        # a paused house writes the same line twelve times a minute.
        if RESIDENT_STATE.get("last_error") != excuse:
            RESIDENT_STATE["last_error"] = excuse
            log.info("the Resident is holding %d signal(s): %s",
                     len(RESIDENT_PENDING), excuse)
        return {**out, "held": excuse}
    RESIDENT_STATE["last_error"] = ""

    thinking = str(settings.get("thinking") or model_plan.DEFAULT_THINKING)
    if RESIDENT_PARKED:
        drained = await _resident_investigations([], now, settings, thinking)
        out["parked_ran"] = drained["ran"]
    if not look_due:
        return out

    # One clock up from the batch cap, and it is `triage.MAX_PER_DAY`
    # because the first look IS what triage was: a day that has spent its
    # runs waits for tomorrow, and the stale sweep above is the promise
    # that the rows are still shown. A tripped safety sensor is not held
    # by it — the lane has already filed and sent that one, so what a look
    # adds is context, and a day of looks spent on something else must not
    # be the reason a leak's context waits until midnight.
    safety_waiting = any(sig.get("safety") and sig.get("hot")
                         for sig in RESIDENT_PENDING)
    if _triage_runs_today(now) >= triage.MAX_PER_DAY and not safety_waiting:
        if not TRIAGE_STATE.get("capped_said"):
            TRIAGE_STATE["capped_said"] = True
            log.warning("the Resident has spent its %d looks for today; %d "
                        "signal(s) wait for tomorrow", triage.MAX_PER_DAY,
                        len(RESIDENT_PENDING))
        return {**out, "held": "the day's looks are spent"}
    TRIAGE_STATE["capped_said"] = False

    allowed, why = LEDGER.allows(
        _resident_tier(resident.JOB_FIRST_LOOK, thinking), thinking, now=now)
    if not allowed:
        return {**out, "held": why}
    return await _resident_look(now, settings, thinking, len(surfaced))


async def _resident_look(now: float, settings: dict, thinking: str,
                         surfaced: int) -> dict:
    """One first look: build the batch, spend one cheap run, act on it."""
    # Deduped, EXCEPT for the rows a rule filed. `signals.dedupe` folds by
    # `(kind, subject)`, and two different checks about one sensor are two
    # rows the store already deduped by text — folding them here would
    # judge one and leave the other to the stale sweep an hour later.
    filed = [s for s in RESIDENT_PENDING if s.get("finding_ts")]
    live = signals.dedupe([s for s in RESIDENT_PENDING
                           if not s.get("finding_ts")])
    # A watched subject re-enters the look on NEW EVIDENCE and never on the
    # clock — `curiosity.RETRY_EVENTS`' rule, because a timer buys the
    # identical answer over the identical data on somebody else's money.
    # What a watch holds back leaves the pending list: it has been judged,
    # and keeping it would re-offer it on every tick for a fortnight.
    #
    # A row a rule FILED is exempt: it is already on the list in `triaging`,
    # and withholding it only left it there until the stale sweep surfaced
    # it an hour later under `triage.UNJUDGED` — "nothing looked at this",
    # about a subject a look had deliberately decided to watch. What a
    # watch holds back is COUNTED onto the watch (`note_withheld`), which is
    # what lets three separate nights re-open it.
    ready, watched_off = list(filed), []
    for row in live:
        (ready if resident.rejudge_due(row, now) else watched_off).append(row)
    if watched_off:
        await asyncio.to_thread(resident.note_withheld, watched_off, now)
    picked = signals.batch(ready, resident.MAX_BATCH)
    batch = picked["batch"]
    taken = {id(row) for row in batch}
    RESIDENT_PENDING.clear()
    # What did not fit WAITS, exactly as triage's surplus does: the next
    # look is minutes away, `rank` means nothing loses the same lottery
    # twice, and `waiting` is what makes a queue that stopped draining
    # visible rather than quiet.
    RESIDENT_PENDING.extend(row for row in ready if id(row) not in taken)
    RESIDENT_INFLIGHT.clear()
    RESIDENT_INFLIGHT.update(int(s["finding_ts"]) for s in batch
                             if s.get("finding_ts"))
    RESIDENT_STATE["waiting"] = picked["waiting"]
    RESIDENT_STATE["queue_len"] = len(RESIDENT_PENDING)
    RESIDENT_STATE["hot_pending"] = sum(
        1 for s in RESIDENT_PENDING if s.get("hot"))
    if not batch:
        RESIDENT_INFLIGHT.clear()
        return {"looked": False, "queue": len(RESIDENT_PENDING),
                "watched": len(watched_off), "surfaced": surfaced}

    notes = []
    for sig in batch:
        note = await asyncio.to_thread(
            resident.watch_note, str(sig.get("subject") or ""))
        if note:
            notes.append(note)
    look_inputs: dict = {}   # what the prompt was built from, for a capture
    prompt = resident.first_look_prompt(
        # `numbered=False`: `first_look_prompt` lays the rows out in its own
        # numbered list, and two numbers on one row is a reply that means
        # two different signals depending on which one it counted.
        signals.prompt_rows(batch, now, numbered=False),
        # The load-bearing half. "That contact is on a cupboard nobody
        # opens" is exactly the kind of thing a homeowner has already said
        # once, and a look that cannot read it re-litigates every
        # correction they have ever made. Retrieved for the batch's own
        # subjects, so a look at twelve signals reads the facts about
        # those twelve and not the head of a document about the house.
        await asyncio.to_thread(
            _memory_block, entities=outcomes.scope_subjects(batch)),
        await asyncio.to_thread(_open_case_rows),
        now_line=_now_line(now), watch_notes=notes,
        examples=await asyncio.to_thread(_outcome_examples, batch, now),
        situation_line=await asyncio.to_thread(_situation_line, now),
        inputs=look_inputs)
    TRIAGE_STATE["runs"] = _triage_runs_today(now) + 1
    RESIDENT_STATE["last_look_at"] = now
    try:
        # No tools: this is a LOOK, not a search. What it is asked is
        # whether a signal deserves another thought, which is answerable
        # from a sentence — and a cheap tier that could reach for history
        # would stop being the cheap tier.
        result = await _claude(
            engine.run_claude, prompt, resident.FIRST_LOOK_SYSTEM, eff_model(),
            resident.TIMEOUT_S, resident.MAX_TURNS, "resident",
            job=resident.JOB_FIRST_LOOK, schema=resident.FIRST_LOOK_SCHEMA,
            # A batch holding a hot signal — a leak, smoke, a safety device
            # — takes the seat a press would, ahead of every card refresh.
            priority=(run_queue.SAFETY if any(s.get("hot") for s in batch)
                      else run_queue.SCHEDULED))
    except Exception as exc:  # noqa: BLE001 — the signals are already in
        # hand; what is at stake is only whether anything looked at them.
        log.warning("a first look failed: %s", exc)
        result = {"ok": False, "error": str(exc), "meta": {}}
    run_id = str((result.get("meta") or {}).get("session_id") or "")
    cost = await asyncio.to_thread(_record_usage, result, "resident-look")
    LEDGER.record(resident.JOB_FIRST_LOOK, int(cost.get("total") or 0), now,
                  tier=_ran_tier(result, resident.JOB_FIRST_LOOK))

    if not result.get("ok"):
        return await _resident_run_failed(batch, run_id, now, surfaced)
    await asyncio.to_thread(_capture_look, settings, run_id, batch,
                            look_inputs, result, cost, now)
    verdicts = resident.parse_first_look(_answer(result), len(batch), batch)
    return await _resident_apply(batch, verdicts, run_id, now, settings,
                                 thinking, surfaced, len(watched_off))


async def _resident_run_failed(batch: list[dict], run_id: str, now: float,
                               surfaced: int) -> dict:
    """A look that did not come back. Every filed row is shown as it is.

    `triage.RUN_FAILED` rather than a sentence this file wrote, because a
    row a rule filed is in the triage lifecycle whatever judged it and one
    vocabulary is what stops "nothing looked at this" being said two ways
    on two cards. Nothing a rule filed is re-queued — it is on the list
    now, which is louder than waiting — and everything else goes back,
    because a failed run is not a verdict about it and dropping it is the
    one thing this loop must not do.
    """
    decided = {int(s["finding_ts"]): ("untriaged", triage.RUN_FAILED)
               for s in batch if s.get("finding_ts")}
    moved = await asyncio.to_thread(
        findings_store.record_triage, decided, run_id, now) if decided else []
    if moved:
        await _announce_findings([f for f in moved if f["status"] != "held"])
    RESIDENT_PENDING.extend(s for s in batch if not s.get("finding_ts"))
    RESIDENT_INFLIGHT.clear()
    RESIDENT_STATE["queue_len"] = len(RESIDENT_PENDING)
    return {"looked": True, "ok": False, "shown": len(moved),
            "surfaced": surfaced + len(moved)}


async def _resident_apply(batch: list[dict], verdicts: dict[int, dict],
                          run_id: str, now: float, settings: dict,
                          thinking: str, surfaced: int, watched: int) -> dict:
    """What the four verdicts do.

    `ignore` is the only one that may take a filed row off a screen, and it
    may only do it by SAYING so about that row in a reply that parsed —
    which `parse_first_look` guarantees by answering for every index. Every
    other verdict elevates a filed row, because a row somebody may still
    have to act on is the safe direction and "I am watching this" is not a
    reason to hide it.
    """
    await asyncio.to_thread(outcomes.record_look, batch, verdicts, run_id, now)
    decided: dict[int, tuple[str, str]] = {}
    counts = {word: 0 for word in resident.VERDICTS}
    # `(signal, why, row it refines or 0)`: the look's reason travels with
    # the signal, because the investigation was sent to answer it.
    to_investigate: list[tuple[dict, str, int]] = []
    requeue: list[dict] = []
    filed_cases = 0
    for i, signal in enumerate(batch, 1):
        answer = verdicts.get(i) or {"verdict": "watch",
                                     "why": resident.SKIPPED,
                                     "forced": True, "fallback": True}
        verdict, why = answer["verdict"], answer["why"]
        counts[verdict] += 1
        ts = int(signal.get("finding_ts") or 0)
        if verdict == "ignore":
            if ts:
                decided[ts] = ("held", why)
            continue
        if ts:
            decided[ts] = ("elevated", why)
        if verdict == "watch":
            if answer.get("fallback"):
                # Nobody said "watch" — the reply skipped this one or could
                # not be read. Persisting a watch from that muted the
                # subject for a fortnight on the strength of nothing; a
                # live signal goes back for the next look instead, and a
                # filed row is already on the list.
                if not ts:
                    requeue.append(signal)
                continue
            await asyncio.to_thread(resident.watch, signal, why, now)
            continue
        safety = bool(signal.get("safety")) or _is_safety_signal(signal)
        lane_ts = _safety_case_for(signal) if safety else 0
        if verdict == "act" and signal.get("hot") and safety:
            if lane_ts:
                # The lane filed and sent this trip before any look ran;
                # the look's `act` agrees with it, and what is left worth a
                # run is context ON that card — an investigation that
                # refines the lane's row rather than a second card.
                to_investigate.append((signal, why, lane_ts))
                continue
            # A trip the lane could not see as a trip (already `on` when
            # the panel started): the same case, through the other door.
            if await _file_safety_case(signal, why, run_id, now):
                filed_cases += 1
            continue
        # `investigate`, and every `act` that is not a tripped safety
        # sensor: the honest answer to "something is wrong now" on anything
        # else is to go and find out what, which is the next tier. A filed
        # row is what the investigation REFINES, never what it files beside.
        to_investigate.append((signal, why, ts or lane_ts))
    if requeue:
        RESIDENT_PENDING.extend(requeue)

    moved = await asyncio.to_thread(
        findings_store.record_triage, decided, run_id, now) if decided else []
    shown = [f for f in moved if f["status"] != "held"]
    if shown:
        await _announce_findings(shown)
    RESIDENT_INFLIGHT.clear()

    investigated = await _resident_investigations(
        to_investigate, now, settings, thinking)
    log.info("first look: %d signal(s) — %d ignored, %d watched, %d to "
             "investigate, %d acted on; %d finding(s) shown, %d held",
             len(batch), counts["ignore"], counts["watch"],
             counts["investigate"], counts["act"], len(shown),
             len(moved) - len(shown))
    return {"looked": True, "ok": True, "batch": len(batch),
            "verdicts": counts, "shown": len(shown),
            "held": len(moved) - len(shown), "watched": watched,
            "cases": filed_cases + investigated["filed"],
            "investigated": investigated["ran"],
            "surfaced": surfaced + len(shown)}


# What a case filed straight off a hot safety signal says it wants done.
# `consent: False` because the action IS the notification and brAIn has
# already sent it — an action row that asked permission to do what it has
# done is a button that means nothing. Nothing else on this path has a
# shape: a leak is not a thing software may turn a valve off about without
# being asked, which is `playbooks.py`'s own first rule.
SAFETY_ACTION = {"label": "Tell me now", "shape": "notify", "consent": False,
                 "detail": "brAIn sent this the moment the sensor tripped, "
                           "whatever the hour."}


async def _file_safety_case(signal: dict, why: str, run_id: str,
                            now: float) -> bool:
    """A tripped safety sensor the LOOK reached first, as a case, announced.

    The lane (`_safety_trip`) normally got there before any look ran, and
    then this files nothing: one trip is one card, and the look's verdict
    is already what the lane did. It still exists for the trip the lane
    could not see as a trip — a sensor that was already `on` when the
    panel started, so the bus never saw it change — and it files the same
    shape under the same source, so the notifier, the mute refusal and the
    feed cannot tell which door it came through.
    """
    if _safety_case_for(signal):
        RESIDENT_STATE["duplicates"] += 1
        return False
    local = _local_now(now)
    base = str(signal.get("text") or signal.get("subject") or "").strip()
    text = (f"{base} ({local:%a} {local.day} {local:%b}, "
            f"{local:%H:%M})")[:findings_store.MAX_TEXT]
    row = {
        "text": text,
        "claim": text,
        "detail": why,
        "kind": "problem",
        # `critical` and `high` together are what `notify_router.tier_of`
        # reads as *escalate*: pushed through quiet hours and repeated on a
        # ladder, which is the one delivery a leak at three in the morning
        # is owed.
        "severity": "critical",
        "stakes": "high",
        "confidence": 1.0,
        "entity_id": signal.get("subject") or "",
        "fixable": False,
        "source": SAFETY_SOURCE,
        "source_title": "Safety sensors",
        "evidence": _case_evidence(signal),
        "actions": [dict(SAFETY_ACTION)],
        "fix": SAFETY_FIX,
    }
    filed = await asyncio.to_thread(
        findings_store.add_case, row, run_id=run_id, when=now)
    if filed is None:
        RESIDENT_STATE["duplicates"] += 1
        return False
    subject = str(signal.get("subject") or "")
    if subject:
        SAFETY_TRIPS[subject] = {"at": now, "ts": int(filed["ts"])}
    service, _sev = _findings_notify_target()
    if service:
        await _announce_findings([filed])
    else:
        await _safety_fallback_notice(filed)
    log.warning("the Resident filed a safety case: %s", filed["text"])
    return True


def _case_evidence(signal: dict) -> list[dict]:
    """The signal's own observations, in the shape a case stores them.

    `when` is a string on a case and a float on a signal, so it is rendered
    here rather than left for `_clean_evidence` to stringify an epoch into
    a number nobody can read.
    """
    out = []
    for row in (signal.get("evidence") or [])[:findings_store.MAX_EVIDENCE]:
        if not isinstance(row, dict):
            continue
        when = float(row.get("when") or signal.get("seen_at") or 0.0)
        out.append({
            "entity": str(row.get("entity") or ""),
            "value": str(row.get("value") or ""),
            "when": time.strftime("%Y-%m-%d %H:%M",
                                  time.localtime(when)) if when else "",
        })
    return out


async def _resident_investigations(queued: list[tuple[dict, str, int]],
                                   now: float, settings: dict,
                                   thinking: str) -> dict:
    """Spend at most `MAX_INVESTIGATIONS_PER_LOOK` Sonnet runs, or none.

    Parked work first — investigations an earlier look decided on and the
    ledger could not pay for — then this look's. What does not run is
    PARKED (`RESIDENT_PARKED`), never put back on the pending list: back
    there it was re-judged by a fresh paid look every minute while hot,
    with no memory of the verdict, and a hot one could spend the day's
    whole look allowance asking a question whose answer was already
    "investigate". An allowance that is spent is a reason to wait, never a
    reason to decide a signal was worth nothing; `investigations_waiting`
    says so on the diagnostics screen.
    """
    work = list(RESIDENT_PARKED) + list(queued)
    RESIDENT_PARKED.clear()
    ran, filed = 0, 0
    held: list[tuple[dict, str, int]] = []
    for item in work:
        signal, why, refines = item
        if ran >= MAX_INVESTIGATIONS_PER_LOOK:
            held.append(item)
            continue
        allowed, reason = LEDGER.allows(
            _resident_tier(resident.JOB_INVESTIGATE, thinking), thinking, now=now)
        if not allowed:
            RESIDENT_STATE["last_error"] = reason
            held.append(item)
            continue
        ran += 1
        try:
            if await _resident_investigate(signal, now, thinking, why=why,
                                           refines=refines):
                filed += 1
        except Exception as exc:  # noqa: BLE001 — one investigation that
            # fell over must not cost the rest of the batch its verdicts.
            log.warning("an investigation failed: %s", exc)
            RESIDENT_STATE["last_error"] = str(exc)[:200]
    if len(held) > RESIDENT_PARKED_MAX:
        RESIDENT_STATE["dropped"] += len(held) - RESIDENT_PARKED_MAX
        held = held[-RESIDENT_PARKED_MAX:]
    RESIDENT_PARKED.extend(held)
    RESIDENT_STATE["investigations_waiting"] = len(RESIDENT_PARKED)
    RESIDENT_STATE["queue_len"] = len(RESIDENT_PENDING)
    return {"ran": ran, "filed": filed}


async def _resident_investigate(signal: dict, now: float, thinking: str,
                                *, why: str = "", refines: int = 0) -> bool:
    """One signal, read properly. Returns whether a case was filed or a row
    was rewritten.

    `run_analyst` and not `run_agent`: this runs unattended, so it gets
    tools that only READ — asserted from both ends in `engine`, because
    `--allowedTools` governs what runs without a prompt and a headless run
    cannot be prompted. Nothing an investigation says may change a house;
    what it produces is a claim with the endings on it.

    ``refines`` is the row this signal came from — a check's finding, or
    the safety lane's card — and the run REWRITES it (`findings_store.
    refine`) or, saying so, holds it back (`hold_after_look`). It is kept
    out of the open-cases list it is shown, because a run told that the
    one thing it was sent to look at is a thing it may not claim could
    only abstain or file a sibling card.
    """
    RESIDENT_STATE["last_investigation_at"] = now
    refining = (await asyncio.to_thread(findings_store.get, refines)
                if refines else None)
    exclude = {str((refining or {}).get(k) or "") for k in ("claim", "text")}
    rows = signals.prompt_rows([signal], now, numbered=False)
    prompt = resident.investigate_prompt(
        signal,
        await asyncio.to_thread(_memory_block, entities=_signal_entities(
            signal) + outcomes.scope_subjects([signal])),
        await _house_prompt_block(now),
        await asyncio.to_thread(_open_case_rows, exclude=exclude),
        signal_row=rows[0] if rows else "", why=why, refining=refining,
        now_line=_now_line(now),
        examples=await asyncio.to_thread(_outcome_examples, [signal], now,
                                         investigating=True),
        situation_line=await asyncio.to_thread(_situation_line, now))
    result = await _claude(
        engine.run_analyst, prompt, resident.INVESTIGATE_SYSTEM, eff_model(),
        resident.INVESTIGATE_TIMEOUT_S, resident.INVESTIGATE_MAX_TURNS,
        "resident", job=resident.JOB_INVESTIGATE, schema=resident.CASE_SCHEMA,
        priority=(run_queue.SAFETY if signal.get("hot")
                  else run_queue.SCHEDULED))
    run_id = str((result.get("meta") or {}).get("session_id") or "")
    cost = await asyncio.to_thread(_record_usage, result, "resident-investigate")
    LEDGER.record(resident.JOB_INVESTIGATE, int(cost.get("total") or 0), now,
                  tier=_ran_tier(result, resident.JOB_INVESTIGATE))
    if not result.get("ok"):
        log.info("an investigation of %s came back empty: %s",
                 signal.get("subject"), result.get("error") or "no answer")
        await _outcome(signal, "failed", run_id, now, why, refines)
        return False

    answer = _answer(result)
    if refining is not None:
        dismissal = resident.parse_dismissal(answer)
        if dismissal:
            held = await asyncio.to_thread(findings_store.hold_after_look,
                                           refines, dismissal, run_id, now)
            log.info("an investigation found nothing in %s%s",
                     refining.get("text"),
                     "" if held else " (the row had moved on; left as it is)")
            await _outcome(signal, "held" if held else "moved_on", run_id,
                           now, why, refines, row=held, said=dismissal)
            return False

    # What the run actually read. `parse_case` refuses a case whose
    # evidence names anything else — WHOLE, rather than trimming the row,
    # because the claim was reasoned from it and dropping the row leaves
    # the conclusion wearing the evidence that survived. None when the
    # transcript could not be read, which checks nothing: "I could not
    # look" must not throw a real investigation away.
    read = await asyncio.to_thread(_entities_read, result)
    if read is not None:
        read |= set(_signal_entities(signal))
    case = resident.parse_case(answer, read_entities=read)
    if case is None:
        if read is not None and resident.parse_case(answer) is not None:
            RESIDENT_STATE["refused"] = RESIDENT_STATE.get("refused", 0) + 1
            log.warning("an investigation of %s cited evidence it never read; "
                        "its case was refused", signal.get("subject"))
            await _outcome(signal, "refused", run_id, now, why, refines)
        else:
            log.info("the investigation of %s made no claim",
                     signal.get("subject"))
            await _outcome(signal, "no_claim", run_id, now, why, refines)
        return False

    if case.get("escalate"):
        case = await _resident_escalate(case, signal, now, thinking, read,
                                        why=why, refining=refining)
        if case is None:
            log.info("a stronger look withdrew the case about %s",
                     signal.get("subject"))
            await _outcome(signal, "withdrawn", run_id, now, why, refines,
                           escalated=True)
            return False
    # The signal that started it, folded in — because "what made brAIn look"
    # is evidence about the claim and the run has no way to cite it: it was
    # handed the line rather than reading it off the house.
    case["evidence"] = (case.get("evidence") or []) + _case_evidence(signal)
    case_run = str(case.pop("_run_id", "") or run_id)
    case["run_id"] = case.get("run_id") or case_run
    case["investigation"] = {"run_id": case_run}

    if refining is not None:
        row = await asyncio.to_thread(findings_store.refine, refines, case,
                                      case_run, now)
        if row is None:
            log.info("the row an investigation refined had moved on")
            await _outcome(signal, "moved_on", case_run, now, why, refines)
            return False
        log.info("the Resident rewrote a row after looking: %s",
                 row.get("claim") or row.get("text"))
        await _outcome(signal, "refined", case_run, now, why, refines,
                       row=row, case=case, escalated=case_run != run_id)
        return True

    filed = await asyncio.to_thread(
        findings_store.add_case, case, run_id=case_run, when=now)
    if filed is None:
        # The store already holds this claim, in any status or in the
        # settled ledger. Counted rather than filed twice, which is what
        # makes a re-report silent and a dismissal permanent.
        RESIDENT_STATE["duplicates"] += 1
        log.info("an investigation reached a claim the house already holds")
        await _outcome(signal, "duplicate", case_run, now, why, refines,
                       case=case)
        return False
    await _announce_findings([filed])
    log.info("the Resident filed a %s case: %s", filed.get("kind", "problem"),
             filed["text"])
    await _outcome(signal, "filed", case_run, now, why, refines, row=filed,
                   case=case, escalated=case_run != run_id)
    return True


def _entities_read(result: dict) -> set[str] | None:
    """Every entity id the run's TOOL TRAFFIC mentions, or None.

    `parse_case`'s guard is against an INVENTED reading, and the honest
    test is whether the id appears in what the run sent to its tools or got
    back from them. It read the run's final reply text instead — the one
    place the answer under test is written — so a CLI that echoed its JSON
    made every cited id "read" (the guard did nothing), and one answering
    with validated `structured_output` and a sentence of prose read no
    neighbour at all (the guard threw real cases away, logged as "made no
    claim"). The transcript is the engine store's own JSONL, named by the
    session id the run claimed. None when it cannot be found or read.
    """
    session_id = str((result.get("meta") or {}).get("session_id") or "")
    if not session_id:
        return None
    traffic = conversations.tool_traffic(engine.CLAUDE_HOME, session_id)
    if traffic is None:
        return None
    return set(_MEMORY_ENTITY_RE.findall(traffic.lower()))


async def _resident_escalate(case: dict, signal: dict, now: float,
                             thinking: str, read: set[str] | None, *,
                             why: str = "",
                             refining: dict | None = None) -> dict | None:
    """One stronger run at a case the first one was unsure about.

    `parse_case` only ever sets `escalate` where the run said so AND its
    confidence is under `ESCALATE_CONFIDENCE` AND the stakes are high —
    a run that is unsure about something that does not matter should have
    said `watch`. Past the allowance the case STANDS and its detail says
    it was not escalated, because a claim that was worth filing is worth
    filing at the confidence it has.

    The stronger run is handed the first case and its uncertainty — it was
    handed the same prompt with none of it, which is a re-roll rather than
    a second opinion — and **its no-claim is honoured**: a deliberate empty
    claim returns None and nothing is filed. It used to fall back to the
    unsure case, so the one answer an escalation exists to be able to give
    ("no, that is not right") was the one it could not.
    """
    allowed, reason = LEDGER.allows(_resident_tier(ESCALATE_JOB, thinking),
                                    thinking, now=now)
    if not allowed:
        case["detail"] = (case.get("detail", "") + "\n\nbrAIn was unsure "
                          f"about this and did not look again: {reason}."
                          ).strip()
        return case
    exclude = {str((refining or {}).get(k) or "") for k in ("claim", "text")}
    rows = signals.prompt_rows([signal], now, numbered=False)
    result = await _claude(
        engine.run_analyst,
        resident.investigate_prompt(
            signal,
            await asyncio.to_thread(_memory_block,
                                    entities=_signal_entities(signal)),
            await _house_prompt_block(now),
            await asyncio.to_thread(_open_case_rows, exclude=exclude),
            signal_row=rows[0] if rows else "", why=why, refining=refining,
            prior_case=case, now_line=_now_line(now),
            examples=await asyncio.to_thread(_outcome_examples, [signal], now,
                                             investigating=True),
            situation_line=await asyncio.to_thread(_situation_line, now)),
        resident.INVESTIGATE_SYSTEM, eff_model(),
        resident.INVESTIGATE_TIMEOUT_S, resident.INVESTIGATE_MAX_TURNS,
        "resident", job=ESCALATE_JOB, schema=resident.CASE_SCHEMA,
        priority=(run_queue.SAFETY if signal.get("hot")
                  else run_queue.SCHEDULED))
    cost = await asyncio.to_thread(_record_usage, result, "resident-escalate")
    LEDGER.record(ESCALATE_JOB, int(cost.get("total") or 0), now,
                  tier=_ran_tier(result, ESCALATE_JOB))
    if not result.get("ok"):
        return case
    answer = _answer(result)
    if isinstance(answer, dict) and not str(answer.get("claim") or "").strip():
        return None
    stronger_read = await asyncio.to_thread(_entities_read, result)
    if read is None or stronger_read is None:
        both = None
    else:
        both = read | stronger_read
    stronger = resident.parse_case(answer, read_entities=both)
    if stronger is None:
        return case
    stronger["_run_id"] = str((result.get("meta") or {}).get("session_id")
                              or "")
    return stronger


async def _resident_loop() -> None:
    """Watch the house. The one loop in this file that is event-driven.

    The tick is short because a hot signal must not wait out an interval,
    and a tick with an empty queue is one `qsize()` and a comparison. The
    watch list is expired here rather than on a timer of its own for
    `_triage_drain`'s reason: one loop, one place a queue is answered for.
    """
    await asyncio.sleep(RESIDENT_FIRST_DELAY_S)
    expired_at = 0.0
    while True:
        try:
            now = time.time()
            if now - expired_at >= 3600:
                expired_at = now
                gone = await asyncio.to_thread(resident.expire, now)
                if gone:
                    log.info("stopped watching %d subject(s) nothing came "
                             "back about", gone)
                aged = await asyncio.to_thread(findings_store.expire_cases,
                                               now)
                if aged:
                    log.info("took %d Resident case(s) nobody answered off "
                             "the list", len(aged))
            await _resident_tick(now)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — never let this kill the loop
            log.debug("resident loop: %s", exc)
        await asyncio.sleep(RESIDENT_TICK_S)


def _resident_diagnostics() -> dict:
    """What the loop is doing, for `/api/diagnostics` and the feed's foot.

    Three things that look identical from every other surface and are not:
    a house with nothing happening, a queue that stopped draining, and a
    loop that is holding everything because a gate said no. Each has its
    own number here.
    """
    return {
        **{k: v for k, v in RESIDENT_STATE.items()},
        # The lane in front of all of it, because "no leak was ever filed"
        # and "the lane is broken" read the same from every other screen.
        "safety": dict(SAFETY_STATE),
        "parked": len(RESIDENT_PARKED),
        "look_interval_s": RESIDENT_LOOK_S,
        "queue_max": RESIDENT_QUEUE_MAX,
        "watching": len(resident.watched()),
        "ledger": LEDGER.summary(),
        "looks_today": _triage_runs_today(time.time()),
        "looks_per_day": triage.MAX_PER_DAY,
    }


# ---------------------------------------------------------------------------
# Outcomes — what the Resident decided, and what the household did next
# ---------------------------------------------------------------------------
#
# `outcomes.py` holds the log, the join and the rules; what lives here is
# the four places it touches the running panel: a line per investigation
# result, the worked examples a prompt is handed, the nightly pass that
# grades and reflects, and the replay a person presses for. Every one of
# them is best-effort in the direction that keeps the loop running — a
# verdict log that could not be written, an example block that could not
# be built and a reflect run that failed all leave the Resident exactly as
# it was, because the accounting must never be what stops the house being
# watched.

# The reflect run is a cheap look at a handful of numbered patterns.
REFLECT_TIMEOUT_S = 180
REFLECT_MAX_TURNS = 4
# A judgement already standing is re-asked about weekly at most: the
# counts on it go stale slowly, and re-asking nightly would spend a run to
# write the same sentence.
REFLECT_REFRESH_S = 7 * 86400
# The replay's spend cap when the request names none. A first look is a
# few thousand tokens; this is a few dozen of them, and a measurement that
# can quietly spend an account's window is one nobody runs twice.
EVAL_DEFAULT_TOKENS = 60_000
EVAL_MAX_TOKENS = 500_000
EVAL_DEFAULT_BATCHES = 20
EVAL_MAX_BATCHES = 100
EVAL_DEFAULT_DAYS = 14

OUTCOMES_STATE: dict = {"last_error": "", "running": False}
EVAL_STATE: dict = {"starting": False, "started_at": 0.0, "report": None,
                    "error": ""}


async def _outcome(signal: dict, result: str, run_id: str, now: float,
                   why: str = "", refines: int = 0, *, row: dict | None = None,
                   case: dict | None = None, said: str = "",
                   escalated: bool = False) -> None:
    """One line in the verdict log for what an investigation came to.

    ``why`` is the look's reason for sending it (what to look FOR) and
    ``said`` the investigation's own sentence where it gave one rather
    than a case. Never raises: `record_investigation` swallows its own
    failures, and this is awaited on the investigation's success path.
    """
    await asyncio.to_thread(
        outcomes.record_investigation, signal, result, run_id=run_id,
        now=now, why=said or str((case or {}).get("claim") or ""),
        asked=why, refines=refines, row=row, case=case, escalated=escalated)


def _outcome_examples(batch: list[dict], now: float, *,
                      investigating: bool = False) -> list[str]:
    """Past calls like these, with what the household did — for a prompt.

    An investigation gets fewer, and the calibration sentence above them:
    it is the one run that states a confidence, so it is the one run the
    record of how that confidence has held up is about. Never raises — an
    empty list is the prompt as it was before this existed.
    """
    try:
        tz, _name = baselines.house_timezone()
    except Exception:  # noqa: BLE001 — a clock we cannot read is UTC
        tz = None
    try:
        if investigating:
            lines = outcomes.examples_for(
                batch, now, k=outcomes.INVESTIGATE_EXAMPLES_K,
                limit_chars=outcomes.INVESTIGATE_EXAMPLES_CHARS, tz=tz)
            note = outcomes.calibration_note(facts_store.with_predicate(
                outcomes.CALIBRATION_PREDICATE, now))
            return ([f"Your own calibration: {note}"] if note else []) + lines
        return outcomes.examples_for(batch, now, tz=tz)
    except Exception as exc:  # noqa: BLE001
        log.debug("could not build the worked examples: %s", exc)
        return []


def _capture_look(settings: dict, run_id: str, batch: list[dict],
                  inputs: dict, result: dict, cost: dict, now: float) -> None:
    """Keep this look for the replay, when capture is switched on.

    The same switch as an analyst capture and the same file shape rules —
    off by default, redacted on the way in, capped — because a first look
    is as much a floor plan as a card bundle is. Never raises.
    """
    if not settings.get("capture"):
        return
    try:
        capture.record_first_look(
            capture.run_id_from(result.get("meta") or {}) or run_id,
            batch=batch, inputs=inputs, reply=_answer(result) or {},
            model=str((result.get("meta") or {}).get("model") or eff_model()),
            tokens=cost, now=now)
    except Exception as exc:  # noqa: BLE001
        log.debug("could not capture the first look: %s", exc)


def _learning_on() -> bool:
    """The `learning` option: may brAIn file what it works out? Live from
    the Supervisor, the run.sh export otherwise — `_curiosity_enabled`'s
    shape. A judgement is something brAIn learned, so it answers to it."""
    snap = addon_options.snapshot() or {}
    value = snap.get("learning")
    if value is None:
        raw = os.environ.get("BRAIN_ASSIST_LEARNING", "true").strip().lower()
        return raw not in ("false", "0", "no", "")
    return bool(value)


def _label_first_look_captures(graded: list[dict]) -> int:
    """Label every captured first look by what the household did next."""
    labelled = 0
    for entry in capture.first_looks():
        run_id = str(entry.get("run_id") or "")
        labels = outcomes.look_labels(graded, run_id)
        if labels and capture.label_first_look(run_id, labels):
            labelled += 1
    return labelled


def _supersede_judgements(graded: list[dict], now: float) -> int:
    """Drop the quieter judgements a later confirmed case contradicted."""
    standing = outcomes.judgement_rows(
        facts_store.with_predicate(outcomes.JUDGEMENT_PREFIX, now))
    gone = 0
    for fact in outcomes.superseded(standing, graded):
        if facts_store.forget(str(fact.get("id") or "")):
            gone += 1
            log.info("a judgement no longer holds and was dropped: %s",
                     log_safe(fact.get("text")))
    return gone


def _write_calibration(line: str, now: float) -> bool:
    """The calibration sentence, replacing the last one — or removing it
    when no bucket has earned one any more, because a stale reliability
    figure is a figure a prompt goes on believing."""
    standing = facts_store.with_predicate(outcomes.CALIBRATION_PREDICATE, now)
    if any(f.get("text") == line for f in standing) and line:
        return False
    for fact in standing:
        facts_store.forget(str(fact.get("id") or ""))
    if not line:
        return bool(standing)
    facts_store.add(line, subject=outcomes.CALIBRATION_SUBJECT,
                    source="resident", confidence=outcomes.JUDGEMENT_CONFIDENCE,
                    predicate=outcomes.CALIBRATION_PREDICATE, ts=now)
    return True


def _fresh_candidates(cands: list[dict], now: float) -> list[dict]:
    """The candidates no standing judgement already answers this week."""
    standing = outcomes.judgement_rows(
        facts_store.with_predicate(outcomes.JUDGEMENT_PREFIX, now))
    out = []
    for cand in cands:
        same = [f for f in standing
                if f.get("subject") == cand["subject"]
                and f.get("predicate") == outcomes.predicate_for(cand)
                and now - float(f.get("ts") or 0) < REFLECT_REFRESH_S]
        if not same:
            out.append(cand)
    return out


async def _reflect(cands: list[dict], now: float) -> dict:
    """One cheap run writing what the lopsided patterns teach.

    The arithmetic decided WHICH scopes (`outcomes.candidates`); the model
    only says what each means, and `parse_reflect` checks every sentence
    before it becomes a fact. A run that failed writes nothing and says so
    — the standing judgements are left as they were, because a failed run
    is never a verdict.
    """
    result = await _claude(
        engine.run_claude, outcomes.reflect_prompt(cands),
        outcomes.REFLECT_SYSTEM, eff_model(), REFLECT_TIMEOUT_S,
        REFLECT_MAX_TURNS, "resident", job="reflect",
        schema=outcomes.REFLECT_SCHEMA)
    cost = await asyncio.to_thread(_record_usage, result, "resident-reflect")
    LEDGER.record("reflect", int(cost.get("total") or 0), now,
                  tier=_ran_tier(result, "reflect"))
    run_id = str((result.get("meta") or {}).get("session_id") or "")
    if not result.get("ok"):
        return {"ran": True, "ok": False, "candidates": len(cands),
                "error": str(result.get("error") or "no answer")[:200]}
    lessons = outcomes.parse_reflect(_answer(result), cands)

    def write() -> int:
        expires = time.strftime(
            "%Y-%m-%d", time.localtime(
                now + outcomes.JUDGEMENT_TTL_DAYS * 86400))
        standing = outcomes.judgement_rows(
            facts_store.with_predicate(outcomes.JUDGEMENT_PREFIX, now))
        written = 0
        for idx, lesson in sorted(lessons.items()):
            cand = cands[idx - 1]
            # One judgement per scope: whatever stood about this subject
            # is replaced, in either direction, by what the record says now.
            for fact in standing:
                if (fact.get("subject") == cand["subject"]
                        and fact.get("predicate") !=
                        outcomes.CALIBRATION_PREDICATE):
                    facts_store.forget(str(fact.get("id") or ""))
            row, _created = facts_store.add(
                outcomes.judgement_text(cand, lesson),
                subject=cand["subject"], source="resident",
                confidence=outcomes.JUDGEMENT_CONFIDENCE, run_id=run_id,
                predicate=outcomes.predicate_for(cand), expires=expires,
                ts=now)
            written += 1 if row else 0
        return written

    written = await asyncio.to_thread(write)
    log.info("reflect: %d pattern(s), %d judgement(s) written, %d refused "
             "or left empty", len(cands), written, len(cands) - written)
    return {"ran": True, "ok": True, "candidates": len(cands),
            "written": written, "refused": len(cands) - len(lessons),
            "run_id": run_id}


async def _outcomes_nightly(now: float, *, force: bool = False) -> dict:
    """Grade the night's verdicts, keep what holds, and reflect on it.

    Deterministic first and free: the join, the superseding of any
    judgement a confirmed case has contradicted, the calibration sentence
    and the labels on captured looks all happen whatever the gates say,
    because none of them spends anything. Only the reflect run answers to
    the three gates every scheduled Claude run answers to — and to
    `learning`, because a judgement is something brAIn learned.
    """
    state = await asyncio.to_thread(outcomes.load_state)
    if not force and not outcomes.join_due(now, state):
        return {"skipped": "the join ran less than a day ago"}
    graded = await asyncio.to_thread(outcomes.load_graded, now)
    rep = await asyncio.to_thread(outcomes.report, graded)
    writable = facts_store.writable()
    removed = (await asyncio.to_thread(_supersede_judgements, graded, now)
               if writable else 0)
    if writable and _learning_on():
        await asyncio.to_thread(_write_calibration,
                                rep.get("calibration_line") or "", now)
    labelled = await asyncio.to_thread(_label_first_look_captures, graded)
    cands = outcomes.candidates(outcomes.tallies(outcomes.items(graded)))
    fresh = await asyncio.to_thread(_fresh_candidates, cands, now) \
        if writable else []
    settings = await asyncio.to_thread(settings_store.load)
    reflect: dict = {"at": int(now), "ran": False,
                     "candidates": len(cands), "fresh": len(fresh)}
    excuse = ("" if writable else
              "the facts store is not writable on this install")
    if not excuse and not _learning_on():
        excuse = "learning is switched off"
    excuse = excuse or _resident_gate(settings)
    if excuse:
        reflect["held"] = excuse
    elif fresh:
        try:
            reflect.update(await _reflect(fresh, now))
        except Exception as exc:  # noqa: BLE001 — the join above stands
            reflect.update({"ran": True, "ok": False,
                            "error": str(exc)[:200]})
    standing = await asyncio.to_thread(
        facts_store.with_predicate, outcomes.JUDGEMENT_PREFIX, now)
    state.update({
        "joined_at": int(now),
        "summary": {k: rep[k] for k in ("rows", "by_outcome", "by_stage")},
        "items": rep["items"],
        "calibration_line": rep.get("calibration_line") or "",
        "superseded": removed,
        "captures_labelled": labelled,
        "judgements": len(outcomes.judgement_rows(standing)),
        "reflect": reflect,
    })
    await asyncio.to_thread(outcomes.save_state, state)
    log.info("outcomes: %d verdict(s) graded, %d judgement(s) standing, %d "
             "superseded%s", rep["rows"], state["judgements"], removed,
             f"; reflect held: {reflect['held']}" if reflect.get("held")
             else "")
    return state


async def _outcomes_tick(now: float) -> None:
    """`_outcomes_nightly` for a loop: never raises, never overlaps."""
    if OUTCOMES_STATE["running"]:
        return
    OUTCOMES_STATE["running"] = True
    try:
        await _outcomes_nightly(now)
        OUTCOMES_STATE["last_error"] = ""
    except Exception as exc:  # noqa: BLE001 — the loop outlives a pass
        OUTCOMES_STATE["last_error"] = str(exc)[:200]
        log.warning("the outcomes pass failed: %s", exc)
    finally:
        OUTCOMES_STATE["running"] = False


def _outcomes_diagnostics() -> dict:
    """The row in `/api/diagnostics`: is the log written, when did the join
    last run, and what did reflect do. Counts only — never a verdict's
    sentence or a homeowner's note."""
    try:
        out = outcomes.diagnostics()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}
    out["last_error"] = OUTCOMES_STATE["last_error"]
    out["eval"] = {"running": bool(EVAL_STATE["starting"]),
                   "last": ((EVAL_STATE["report"] or {}).get("total")
                            if EVAL_STATE["report"] else None)}
    return out


async def h_resident_outcomes(request: web.Request) -> web.Response:
    """What the Resident decided and what came of it, graded now.

    Computed fresh on every request — it is a deterministic join over three
    small files, and a person looking at it wants this afternoon's Wrong in
    it rather than last night's. `?nightly=1` also runs the nightly pass
    now (the free half, plus a reflect run if the gates allow), which is
    how somebody checks a judgement without waiting for the small hours.
    """
    now = time.time()
    if request.query.get("nightly") in ("1", "true", "yes"):
        if OUTCOMES_STATE["running"]:
            return web.json_response(
                {"error": "the outcomes pass is already running"}, status=409)
        OUTCOMES_STATE["running"] = True
        try:
            await _outcomes_nightly(now, force=True)
        finally:
            OUTCOMES_STATE["running"] = False

    def build() -> dict:
        graded = outcomes.load_graded(now)
        rep = outcomes.report(graded, full=True)
        rep["candidates"] = [
            {k: c[k] for k in ("scope", "subject", "direction", "counts")}
            for c in outcomes.candidates(
                outcomes.tallies(outcomes.items(graded)))]
        rep["judgements"] = [
            {k: f.get(k) for k in ("id", "subject", "predicate", "text", "ts",
                                    "expires", "run_id")}
            for f in facts_store.with_predicate(outcomes.JUDGEMENT_PREFIX,
                                                now)]
        rep["state"] = outcomes.load_state()
        return rep

    return web.json_response(await asyncio.to_thread(build))


def _eval_ask(prompt: str) -> tuple[dict | None, int]:
    """One replayed look through the real runner, under `replay`.

    Called from `_run_eval`'s own thread and so takes no `run_queue` seat,
    `doctor.py`'s arrangement: a pressed, spend-capped replay is not the
    unattended traffic that bound exists for."""
    result = engine.run_claude(
        prompt, resident.FIRST_LOOK_SYSTEM, eff_model(), resident.TIMEOUT_S,
        resident.MAX_TURNS, "replay", job=resident.JOB_FIRST_LOOK,
        schema=resident.FIRST_LOOK_SCHEMA)
    cost = _record_usage(result, "eval-first-look")
    if not result.get("ok"):
        return None, int(cost.get("total") or 0)
    return _answer(result) or {}, int(cost.get("total") or 0)


def _run_eval(entries: list[dict], max_tokens: int, max_batches: int,
              days: int, now: float) -> dict:
    """Replay labelled batches against today's prompt, under a spend cap.

    The cap is checked BEFORE each run (`replay.py`'s rule: a cap that
    stops once it has been passed has already spent the run that passed
    it), and what it stopped is counted rather than dropped. The report
    carries the captured verdicts' own agreement beside the replayed one,
    because a number without the number it is compared against is not
    evidence for a change — and nothing here changes anything: promotion
    is a person reading this and editing a prompt.
    """
    rows: list[dict] = []
    spent, skipped = 0, 0
    for entry in entries:
        if len(rows) >= max_batches or spent >= max_tokens:
            skipped += 1
            continue
        row = outcomes.replay_look(entry, _eval_ask)
        spent += int(row.get("tokens") or 0)
        rows.append(row)
    return {"generated_at": int(now), "kind": "first_look", "days": days,
            "max_tokens": max_tokens, "rows": rows, "skipped": skipped,
            "total": outcomes.summarise_replay(rows),
            "promotion": "never automatic: a changed prompt ships when a "
                         "person reads this number and decides it should"}


async def h_resident_eval_get(request: web.Request) -> web.Response:
    return web.json_response({
        "running": bool(EVAL_STATE["starting"]),
        "started_at": int(EVAL_STATE["started_at"] or 0) or None,
        "error": EVAL_STATE["error"], "report": EVAL_STATE["report"]})


async def h_resident_eval_start(request: web.Request) -> web.Response:
    """`brain eval first_look`: replay captured looks against today's prompt.

    A press, never a timer — it spends real runs — so it skips the usage
    budget and nothing else that matters: a credential is required, the
    spend is capped, and it STARTS rather than awaits, because twenty runs
    are minutes and ingress will not hold a request that long
    (`h_baselines_run`'s clock). The outcome is read back off GET.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — an empty body is the defaults
        body = {}
    body = body if isinstance(body, dict) else {}
    kind = str(body.get("kind") or "first_look")
    if kind != "first_look":
        return web.json_response(
            {"error": f"there is no replay for {kind!r}; the one there is "
                      "is first_look"}, status=400)

    def clamp(name: str, default: int, top: int) -> int:
        try:
            value = int(body.get(name) or default)
        except (TypeError, ValueError):
            value = default
        return max(1, min(top, value))

    max_tokens = clamp("max_tokens", EVAL_DEFAULT_TOKENS, EVAL_MAX_TOKENS)
    max_batches = clamp("max_batches", EVAL_DEFAULT_BATCHES, EVAL_MAX_BATCHES)
    days = clamp("days", EVAL_DEFAULT_DAYS, 365)
    if EVAL_STATE["starting"]:
        return web.json_response(
            {"running": True, "error": "a replay is already running"},
            status=409)
    if not engine.get_auth():
        return web.json_response(
            {"error": "there is no Claude credential, so nothing can be "
                      "replayed"}, status=409)
    now = time.time()
    entries = [e for e in await asyncio.to_thread(
        capture.first_looks, now - days * 86400) if e.get("labels")]
    if not entries:
        return web.json_response(
            {"error": f"no captured first look from the last {days} days "
                      "carries a label yet — switch capture on under ⚙ → "
                      "Diagnostics and let the household answer a few cards; "
                      "the nightly pass labels them"}, status=409)
    # Flipped synchronously, `start_auth_check`'s rule: two presses in one
    # tick must not both pass a guard their own task has not set yet.
    EVAL_STATE.update({"starting": True, "started_at": now, "error": ""})

    async def run_it() -> None:
        try:
            EVAL_STATE["report"] = await asyncio.to_thread(
                _run_eval, entries, max_tokens, max_batches, days, now)
        except Exception as exc:  # noqa: BLE001
            EVAL_STATE["error"] = str(exc)[:200]
            log.warning("the first-look replay failed: %s", exc)
        finally:
            EVAL_STATE["starting"] = False

    asyncio.create_task(run_it())
    return web.json_response({"running": True, "batches": len(entries),
                              "max_tokens": max_tokens,
                              "max_batches": max_batches, "days": days})


async def _ask_why(now: float, reason: str = "schedule") -> int:
    """Spend at most one Claude run working out why somebody did something.

    The decision is made before anything is spawned and it is arithmetic
    (`curiosity.worth_asking`), so a pass with nothing to be curious
    about costs one read of a JSON file. What a run produces goes to a
    store that already exists — a fact to the memory inbox, a guess to
    the hypothesis queue — because a new kind of knowledge would be a
    fourth store and this is not a fourth kind. It is the *why* behind
    the first one.

    Deliberately outside the findings, like every other producer here: an
    explanation is not a finding, and a curiosity run that could fail a
    checks pass would cost a house its list of what is broken to answer
    a question nobody had asked yet.
    """
    if not _curiosity_enabled():
        return 0
    # A scheduled Claude run answers to the three gates every scheduled
    # Claude run answers to, `_offer_milestones`' rule: a credential, the
    # automatic switch, and the usage budget. Without them a house whose
    # session window has passed its cap — the state whose whole promise is
    # that the rest of the account is yours — would go on spending one run
    # a day on a question nobody asked. The *pressed* route deliberately
    # skips the budget, because "asking a question by hand always runs" is
    # the other half of that promise.
    settings = settings_store.load()
    if not engine.get_auth() or not settings["auto_enabled"]:
        return 0
    if usage_store.budget_state(settings)["blocked"]:
        return 0
    # A guess a full queue turned away earlier is re-proposed for nothing
    # the moment there is room — before anything new is paid for.
    await asyncio.to_thread(_repropose_deferred, now)
    # And nothing is spent while the queue is full. A guess is one of the
    # three answers a run can give, and the one that needs a slot: a run
    # that answered "guess" into a full queue used to pay for the
    # reasoning, throw the guess away and close the subject for good,
    # which is the outcome worse than not asking. The other two producers
    # of guesses already asked (`brain-learn.sh`, the analyst's budget).
    if hypotheses.budget() <= 0:
        return 0
    try:
        tz, _name = await asyncio.to_thread(baselines.house_timezone)
        ledger = await asyncio.to_thread(manual_ledger.load)
        found = await asyncio.to_thread(
            manual_ledger.candidates, ledger, tz, now)
        picked = await asyncio.to_thread(curiosity.ready, found, None, now, tz)
    except Exception as exc:  # noqa: BLE001 — a question is optional; the
        # pass that would have asked it is not.
        log.warning("could not decide what to be curious about: %s", exc)
        return 0
    if not picked:
        return 0

    asked = 0
    for candidate in picked:
        subject = candidate["subject"]
        # Settled BEFORE the run. A run that crashes having spent the
        # money must not leave the identical question to be asked again
        # in six hours for ever — `_brief_loop`'s stamp, for the same
        # reason and with more at stake.
        await asyncio.to_thread(curiosity.mark_asked, candidate, now)
        asked += 1
        try:
            filed, error = await _run_curiosity(candidate, ledger, tz, now)
        except Exception as exc:  # noqa: BLE001
            log.warning("a curiosity run failed: %s", exc)
            await asyncio.to_thread(curiosity.record_answer, subject, None,
                                    "", str(exc)[:200], now)
            continue
        log.info("curiosity (%s): %s — %s", reason, candidate.get("why"),
                 filed or error or "nothing filed")
    return asked


async def _run_curiosity(candidate: dict, ledger: dict, tz,
                         now: float) -> tuple[str, str]:
    """One asking, end to end. Returns `(what was filed, error)`."""
    rows = manual_ledger.by_subject(ledger.get("rows") or []).get(
        candidate["subject"], [])
    prompt = curiosity.frame(
        candidate,
        house=await _house_prompt_block(now),
        # The load-bearing half: without it a run happily rediscovers
        # something the document already says and spends a question
        # asking somebody to confirm what they told brAIn once.
        memory=await asyncio.to_thread(
            _memory_block,
            entities=[r.get("entity_id") for r in rows if r.get("entity_id")]),
        recent=list(reversed(rows)),
    )
    result = await _claude(
        engine.run_analyst, prompt, curiosity.SYSTEM, eff_model(),
        curiosity.TIMEOUT_S, curiosity.MAX_TURNS, "curiosity",
        job="curiosity", schema=curiosity.SCHEMA)
    if not result.get("ok"):
        error = str(result.get("error") or "no reply")
        await asyncio.to_thread(curiosity.record_answer, candidate["subject"],
                                None, "", error, now)
        return "", error

    answer = curiosity.parse(_answer(result))
    if answer is None:
        await asyncio.to_thread(
            curiosity.record_answer, candidate["subject"], None, "",
            "the reply was not the shape the contract asked for", now)
        return "", "unparseable"

    filed = await asyncio.to_thread(
        _file_curiosity, candidate, answer,
        capture.run_id_from(result.get("meta") or {}))
    await asyncio.to_thread(curiosity.record_answer, candidate["subject"],
                            answer, filed, "", now)
    return filed, ""


def _repropose_deferred(now: float) -> int:
    """Put guesses a full queue turned away onto it, while there is room.

    Free: the run that wrote them has already been paid for, and the claim
    is on the entry (`curiosity.record_answer` keeps `because` and `ask`).
    Never raises — this sits in front of a scheduled run and an empty
    answer here must not stop it.
    """
    moved = 0
    try:
        for entry in curiosity.deferred():
            if hypotheses.budget() <= 0:
                break
            if _propose_curiosity(entry, entry):
                curiosity.mark_reproposed(entry["subject"], now)
                moved += 1
    except Exception as exc:  # noqa: BLE001
        log.debug("could not re-propose a deferred guess: %s", exc)
    return moved


def _propose_curiosity(candidate: dict, answer: dict) -> dict | None:
    """One guess onto the hypothesis queue, carrying what it is about.

    The claim reads as it always has — the reason and the question
    together, because a question with no reasoning under it is one nobody
    can answer well — and `fact` is the reason alone, which is what a yes
    files: "the sprinklers run at seven because the lawn is in full sun
    until six", not the same sentence with a question mark on the end.
    """
    name = candidate.get("name") or candidate.get("entity_id") or ""
    claim = f"{answer['because']} — {answer['ask']}"
    return hypotheses.propose(
        claim[:hypotheses.MAX_TEXT_CHARS], topic=f"why: {name}",
        subject=str(candidate.get("entity_id") or ""),
        fact=str(answer.get("because") or ""))


def _file_curiosity(candidate: dict, answer: dict, run_id: str = "") -> str:
    """Put one answer where it belongs, and say where that was.

    Three answers, three places that already exist, and no new surface:

    * **explained** — a durable fact, queued to the memory inbox. Never
      to `memory.md`: one writer owns that document, which is what lets
      the terminal, voice, insights and study sessions all feed the same
      memory without a lock between them.
    * **guess** — a hypothesis, which is exactly what that queue is for:
      a claim brAIn believes and wants confirmed, capped at three open,
      expiring in a fortnight, riding down `/api/findings` as work
      waiting on a person, and becoming a plain memory line the moment
      somebody ticks it. The reason travels in the claim, because a
      question with no reasoning under it is one nobody can answer well.
    * **unknown** — nothing. A run that could not tell has learned
      nothing about the house, and filing "brAIn could not work out why"
      would be filing a fact about brAIn into a document about a home.
    """
    if answer["confidence"] == "explained" and answer["fact"]:
        # Filed under the entity the run was asked about, with the run that
        # worked it out: tagged by scanning the sentence, "the sprinklers
        # run late because the lawn is in sun until six" names no id and no
        # room, and became a fact about the whole house.
        _queue_memory_fact(answer["fact"], source="curiosity",
                           confidence="medium",
                           subject=str(candidate.get("entity_id") or ""),
                           run_id=run_id)
        return "memory"
    if answer["confidence"] == "guess" and answer["ask"]:
        if _propose_curiosity(candidate, answer):
            return "hypothesis"
        # The cap, the TTL or a near-duplicate refused it. Not an error:
        # three open questions is the whole design of that queue, and a
        # fourth waiting behind them is what it exists to prevent. Kept on
        # the curiosity entry as `deferred` and re-proposed when a slot
        # frees (`_repropose_deferred`), rather than settled as asked.
        return curiosity.REFUSED
    return ""


def _curiosity_enabled() -> bool:
    """The `ask_why` option: live from the Supervisor, the run.sh export
    otherwise. On by default — it is the feature, and the budget rather
    than the switch is what bounds it."""
    snap = addon_options.snapshot() or {}
    value = snap.get("ask_why")
    if value is None:
        raw = os.environ.get("BRAIN_ASK_WHY", "true").strip().lower()
        return raw not in ("false", "0", "no", "")
    return bool(value)


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

# Which areas have a naming run in flight. Flipped SYNCHRONOUSLY, before the
# first await in `_design_scenes` — `start_auth_check`'s rule and
# `h_baselines_run`'s: `asyncio.create_task` only SCHEDULES, so a guard read
# from inside the coroutine is a guard two presses in one tick both walk
# past. The press here is a button on the ask bar, and pressing it twice is
# what people do while a thing looks like it is doing nothing: without this,
# two Claude naming runs go out for one room, and both come back to compose
# the same four scenes — `proposals.knows` cannot tell them apart, because
# neither has been added yet when the other is checked.
SCENES_INFLIGHT: set[str] = set()


async def _name_and_offer_once(obj: dict, area: str, key: str) -> None:
    """`_name_and_offer`, releasing the area's claim however it ends.

    A separate wrapper rather than a try/finally inside the run, so the
    claim is taken and given back in one place and the run itself stays a
    function about naming four scenes.
    """
    try:
        await _name_and_offer(obj, area)
    finally:
        SCENES_INFLIGHT.discard(key)


async def _name_and_offer(obj: dict, area: str) -> None:
    """Ask Claude for four names, then offer the set. Never raises.

    The **one** optional model run in this feature, and it names things.
    Everything about which bulb takes which kelvin is composed from the
    registries, because a model choosing that is a guess wearing a config
    and one nobody can check by looking at the card. A failed run leaves
    the plain names, which are a perfectly good answer.
    """
    try:
        result = await _claude(
            engine.run_claude, scenes.name_prompt(area), scenes.SYSTEM,
            eff_model(), scenes.NAME_TIMEOUT_S, scenes.NAME_MAX_TURNS,
            "scene", job="scene_names", priority=run_queue.PRESS)
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
    # Before the first await, because that is the only place it can be:
    # everything below yields, and a second press lands in the gap.
    key = area.casefold()
    if key in SCENES_INFLIGHT:
        return {"refused": (f"brAIn is already composing four scenes for "
                            f"the {area} — they land on the Proposals tab "
                            "when the naming run comes back."), "area": area}
    SCENES_INFLIGHT.add(key)
    spawned = False
    try:
        try:
            snap = await checks.snapshot.collect_rooms()
        except Exception as exc:  # noqa: BLE001 — "I could not look" is its
            # own answer, and it is about brAIn rather than about the room.
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
        asyncio.create_task(_name_and_offer_once(obj, area, key))
        spawned = True
        return {"scenes": area, "lights": len(obj["scene"]["lights"])}
    finally:
        # The run that was started owns the claim from here; every other
        # ending — a refusal, a house we could not read, a raise — gives it
        # straight back, or one bad press locks the room out for good.
        if not spawned:
            SCENES_INFLIGHT.discard(key)


def _scene_room_slugs(configs) -> set[str]:
    """The rooms brAIn's mood scenes were written for, by slug.

    An id is `brain_scene_<slug(room)>_<mood>`, and a room's slug may have
    any number of underscores in it — `living_room`, `master_bedroom` — so
    the mood is what comes off the END. Splitting on `_` and taking the
    third piece cut every multi-word room to its first word, found none of
    its four moods under that, and offered the commonest rooms nothing,
    silently.
    """
    out: set[str] = set()
    for cfg in configs or []:
        if not isinstance(cfg, dict):
            continue
        cid = str(cfg.get("id") or "")
        if not cid.startswith(scenes.ID_PREFIX):
            continue
        slug, _, mood = cid[len(scenes.ID_PREFIX):].rpartition("_")
        if slug and mood in scenes.MOODS:
            out.add(slug)
    return out


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

    areas = _scene_room_slugs(snapshot.get("scenes") or [])
    house = scenes._house(snapshot)
    known = set(house.areas.values()) | {
        house.area_of(e) for e in (snapshot.get("states") or {})}
    offered = 0
    async with aiohttp.ClientSession() as session:
        for slug in sorted(areas):
            # The area's own name, as the registries have it — the slug in
            # the id is what survives a rename and the name is what a card
            # says. A room renamed since the scenes were written keeps its
            # slug, and the slug alone finds the same four scenes
            # (`existing_scenes` slugs what it is handed), so the schedule
            # is still offered under the old name rather than not at all.
            name = next((a for a in sorted(known)
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

    **It stands down when the services list could not be fetched, and
    that is what stops a declined playbook coming back.** A playbook's
    identity is the hash of its config (`proposals.key_for`), and the
    config ends in one notify step per target — which, with no
    `findings_notify_service` set, is every `notify.mobile_app_*` the
    snapshot could see. `snap["services"]` is a best-effort REST fetch
    that degrades to an empty set and flags itself unavailable, so a pass
    where `/services` timed out composed the same three playbooks with
    their notify steps missing, hashed them to three different keys, and
    offered every one the homeowner had already declined — buying a
    Claude paragraph for each. Both passes look successful in the log,
    which is why it read as "I keep dismissing it and it keeps coming
    back" with nothing to point at. Measured: flipping only that field
    moves all three keys and drops `freeze` entirely.

    This is `clear_resolved`'s rule in the half that OFFERS: "I could not
    look" and "there are no notifiers here" are different claims, and
    only one of them may change what this house is asked. Its sibling
    producers already carry it — `_offer_scene_schedule` returns on an
    unreadable `scenes.yaml`, `conditions.propose` on unreadable
    automations — and this one did not.
    """
    if not (snapshot.get("available") or {}).get("services"):
        log.info("not offering playbooks: the services list was not "
                 "available this pass, and a playbook keyed on a notifier "
                 "set we could not read is one that comes back declined")
        return 0
    service, _sev = _findings_notify_target()
    try:
        protected = automation_writer.protected_patterns()
        found = await asyncio.to_thread(
            playbooks.build, snapshot, protected, service)
    except Exception as exc:  # noqa: BLE001 — an offer is optional; the
        # pass that would have made it is not.
        log.warning("could not compose playbooks: %s", exc)
        return 0

    # The paragraph is a Claude run, so it answers to the three gates
    # every scheduled run answers to (`_offer_milestones`' rule): this is
    # reached from the checks pass on a timer, and "automatic insights
    # pause" is a promise a paused or over-budget house was still paying
    # for here. The PROPOSAL is not gated — it is deterministic and costs
    # nothing — so a gated pass offers the card with the sentence it was
    # composed with, which is exactly what a failed run leaves.
    settings = settings_store.load()
    may_describe = (bool(engine.get_auth()) and settings["auto_enabled"]
                    and not usage_store.budget_state(settings)["blocked"])
    offered = 0
    for obj in found:
        if await asyncio.to_thread(proposals.knows, obj):
            continue
        if not may_describe:
            if await asyncio.to_thread(proposals.add, obj):
                offered += 1
            continue
        try:
            result = await _claude(
                engine.run_claude, playbooks.describe_prompt(obj),
                playbooks.SYSTEM, eff_model(),
                playbooks.DESCRIBE_TIMEOUT_S, playbooks.DESCRIBE_MAX_TURNS,
                "playbook", job="playbook_text")
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

    Rows from a check in `checks.SHADOW` take the same three moves against
    a **different file** (`shadow_findings`) — a check being trialled runs
    and reaches nobody. It is a separate store rather than a status
    because `add_many` dedupes across every status and the settled ledger,
    so a shadow row sharing the file could suppress a real report of the
    same problem: a rule nobody has agreed to yet, silencing the analyst.
    """
    if CHECKS_STATE["running"]:
        return {"error": "a checks pass is already running",
                **(CHECKS_STATE["last"] or {})}
    CHECKS_STATE["running"] = True
    started = time.time()
    try:
        snapshot = await checks.snapshot.collect(started)
        _note_registry(snapshot)
        _note_access(snapshot, started)
        # Filed BEFORE the checks run, so this pass's own overrides count
        # toward the pattern the check is about to read. The ledger is
        # deduped on the event, which is what makes that safe: passes run
        # every few hours over a day-long window, so the same override is
        # offered four or five times and only the first one lands.
        await asyncio.to_thread(_record_overrides, snapshot, started)
        await asyncio.to_thread(_record_rhythm, snapshot, started)
        await asyncio.to_thread(_record_routines, snapshot, started)
        await asyncio.to_thread(_record_manual, snapshot, started)
        result = checks.run_all(snapshot, started)

        def apply() -> tuple[list[dict], int, list[dict], dict]:
            ran_sources = {checks.source_for(c) for c in result["ran"]}
            # Filed as waiting to be looked at rather than as work
            # (`triage.gate`), which every producer does now. Nothing is
            # hidden by this on its own: a row only leaves `triaging` for
            # `held` when a run says so about that row, and every other
            # ending is `open`.
            created = findings_store.add_many(triage.gate(result["findings"]))
            refreshed = findings_store.refresh_details(result["findings"])
            cleared = findings_store.clear_resolved(
                ran_sources,
                {findings_store.normalize(f["text"]) for f in result["findings"]})
            # And the other store, which nothing renders. Rows from a check
            # being trialled go here instead — a separate file rather than
            # a status, because `add_many` dedupes across every status and
            # a shadow row that suppressed a real report would silence the
            # analyst about a problem on the say-so of a rule nobody has
            # agreed to yet.
            shadow_rows = result.get("shadow") or []
            hidden = shadow_findings.add_many(shadow_rows, started)
            shadow_findings.clear_resolved(
                ran_sources,
                {findings_store.normalize(f["text"]) for f in shadow_rows})
            shadow_findings.prune(started)
            return created, refreshed, cleared, {
                "created": len(hidden), "found": len(shadow_rows)}

        created, refreshed, cleared, shadow_counts = await asyncio.to_thread(apply)
        # Between filing and surfacing: the Resident. What this pass hands
        # over is SIGNALS — its own rows, the overrides it mined, the
        # readings outside their band that no rule filed anything about,
        # and the fact that a pass happened at all — and the first look is
        # what decides which of them anybody is told. Handed over rather
        # than awaited, because a look runs on its own five-second tick and
        # a pass that waited on one would be a checks pass whose duration
        # is a Claude run's (`h_baselines_run`'s clock).
        # Two counts, and they were one variable: the signals handed to the
        # Resident, and the proposals the producers below file. The second
        # overwrote the first, so the summary reported the proposal total
        # as both `offered` and `proposed` and the hand-off was never seen.
        try:
            handed = _offer_findings(created, started)
            handed += _resident_offer_many(
                (snapshot.get("actions") or {}).get("overrides") or [],
                signals.from_override, started, _signal_context())
            handed += _measurement_signals(snapshot, started)
            _resident_offer(signals.from_time(
                f"checks pass ({reason})", started,
                text=f"a house-checks pass ran and filed {len(created)} row(s)"))
        except Exception as exc:  # noqa: BLE001 — the findings are filed
            # either way; a hand-off that fell over must not also take out
            # the pass that found them.
            log.warning("could not hand this pass's signals over: %s", exc)
            handed = 0
        surfaced: list[dict] = []
        triaged = await asyncio.to_thread(
            findings_store.statuses, [f["ts"] for f in created])
        # After the findings, and outside them. A proposal is not a
        # finding: different store, different tab, and a habit miner
        # that could fail this pass would cost a house its list of what
        # is broken to make an offer nobody asked for.
        try:
            proposed = await _offer_routines(started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer routines: %s", exc)
            proposed = 0
        # And the other producer: the automation brAIn would write for a
        # night nobody wants. Same store, same tab, same refusal to
        # enable anything on its own.
        try:
            proposed += await _offer_playbooks(snapshot, started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer playbooks: %s", exc)
        # And the third: the condition an automation somebody keeps
        # undoing does not have. The finding already reports the fight;
        # this is the change that ends it.
        try:
            proposed += await _offer_conditions(snapshot, started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer conditions: %s", exc)
        # And the fourth: the schedule that walks a room through the four
        # scenes it now has. Only once they really exist — a schedule
        # naming a scene that is not there errors at 07:00 every morning.
        try:
            proposed += await _offer_scene_schedule(snapshot, started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not offer a scene schedule: %s", exc)
        # And the fifth producer, which is not a proposal at all: the
        # card brAIn writes the day one of its own measurements first has
        # an answer. Here rather than in the nightly build because the
        # build writes the stores and this reads them, and a producer
        # that could fail must not cost a house its list of what is
        # broken.
        try:
            made = await _offer_milestones(started)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not evaluate the milestones: %s", exc)
            made = 0
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
        # And the one that asks rather than reports: at most one Claude
        # run, on the manual action brAIn can least account for. Last,
        # because it is the only producer here that costs real money on a
        # schedule, and a pass whose cheap work failed should not spend it.
        try:
            wondered = await _ask_why(started, reason)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not ask why: %s", exc)
            wondered = 0
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
            # What this pass handed the Resident, and what became of its
            # own rows. They are different questions: a signal is offered
            # and a row is judged minutes later by a look that is also
            # reading the study inbox and the event stream, so a pass that
            # filed nine and shows `waiting: 9` is a pass whose rows have
            # not been looked at YET rather than one nothing came back for.
            "offered": handed,
            "surfaced": len(surfaced),
            "held": len([t for t, st in triaged.items() if st == "held"]),
            "waiting": len([t for t, st in triaged.items()
                            if st == "triaging"]),
            "refreshed": refreshed,
            "cleared": cleared,
            "proposed": proposed,
            "milestones": made,
            "trials_evaluated": graded,
            "intents_fired": fired,
            "wondered": wondered,
            # Filed where nobody will see them, on purpose. The count is
            # the only thing that says a trialled check is running at all.
            "shadow": shadow_counts,
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
                   "milestones": 0, "wondered": 0,
                   "shadow": {"created": 0, "found": 0},
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
            # Warning, not debug: a pass that fails every tick is the house
            # checks stopping, and debug is a level nobody runs at.
            log.warning("checks loop: %s", exc)
        _beat("checks")
        await asyncio.sleep(CHECKS_TICK_S)


# Nightly. A baseline describes weeks, so measuring it more often buys
# nothing and costs a statistics query over every numeric sensor in the
# house; measuring it less often lets it describe a house that has
# changed. `base.stale` is what reports this loop having stopped.
BASELINE_INTERVAL_S = 24 * 3600
BASELINE_FIRST_DELAY_S = 300
BASELINE_STATE: dict = {"running": False, "starting": False, "last": None}


async def build_baselines(reason: str = "schedule") -> dict:
    """Measure what is normal in this house, and write the stores.

    Separate from the checks pass on purpose: this reads hourly
    statistics for a month over every numeric sensor, which is minutes of
    recorder work, and the answer changes over weeks. The checks pass
    only ever *reads* what this leaves.

    Four builders, four try blocks. They used to share one, so a thermal
    fit that raised threw away the baselines, closures and appliances
    measured a minute before it — three good stores unwritten over one
    bad one. Each is now its own attempt, the summary says which measured
    and which did not (`builders`), and a builder that refused to
    overwrite its store (`error` in its payload, see `baselines.refused`)
    is reported as a failure of that builder and nothing else.
    """
    if BASELINE_STATE["running"]:
        return {"error": "a baseline pass is already running",
                **(BASELINE_STATE["last"] or {})}
    BASELINE_STATE["running"] = True
    started = time.time()
    builders: dict[str, dict] = {}
    payload: dict = {}
    shut: dict = {}
    machines: dict = {}
    rooms: dict = {}

    def _done(name: str, result: dict) -> dict:
        err = str(result.get("error") or "")[:300]
        builders[name] = {"ok": not err, "error": err}
        if err:
            log.warning("baseline pass: %s did not measure: %s", name, err)
            journal.record("baselines", "error", error=err,
                           extra={"builder": name})
        return result

    def _failed(name: str, exc: BaseException) -> None:
        err = str(exc)[:300]
        builders[name] = {"ok": False, "error": err}
        log.warning("baseline pass: %s failed: %s", name, exc)
        journal.record("baselines", "error", error=err,
                       extra={"builder": name})

    try:
        import aiohttp

        import ha_data  # deferred so the module loads without aiohttp in tests
        async with aiohttp.ClientSession() as session:
            states = await ha_data._rest_get(session, "/states", timeout=60)
            by_id = {s["entity_id"]: s for s in (states or [])
                     if isinstance(s, dict) and s.get("entity_id")}
            # The registries, once, before any builder: the baselines read
            # the entity registry to keep diagnostic and config sensors off
            # the cap, and thermal needs all three. A registry that did not
            # answer costs the baselines that one filter and costs thermal
            # its whole pass — see thermal's block below.
            areas = devices = ents = None
            registry_error = ""
            try:
                areas, devices, ents = await ha_data._ws_commands(session, [
                    {"type": "config/area_registry/list"},
                    {"type": "config/device_registry/list"},
                    {"type": "config/entity_registry/list"}])
            except Exception as exc:  # noqa: BLE001 — a fetch, not the pass
                registry_error = str(exc)[:200]
                log.info("baseline pass: the registries did not answer: %s",
                         exc)
            try:
                payload = _done("baselines", await baselines.build(
                    session, by_id, started,
                    entities=ents if isinstance(ents, list) else None))
            except Exception as exc:  # noqa: BLE001 — one builder, not the pass
                _failed("baselines", exc)
            # The same pass, because it is the same claim about the same
            # house over the same month — and it has already paid for the
            # one /states fetch both halves need.
            try:
                shut = _done("closures",
                             await closures.build(session, by_id, started))
            except Exception as exc:  # noqa: BLE001
                _failed("closures", exc)
            # And the third: one /states fetch, three measurements of the
            # same house over the same nights. This one reads FIVE-MINUTE
            # statistics rather than hourly ones, because a dishwasher's
            # dry phase is twenty minutes and an hour cannot see it —
            # which is more rows per entity than the baselines read, and
            # is bounded by asking only power sensors and only ten days.
            try:
                machines = _done("appliances",
                                 await appliances.build(session, by_id, started))
            except Exception as exc:  # noqa: BLE001
                _failed("appliances", exc)
            # And the fourth. This one needs the registries as well as the
            # states — a room has to be nameable before it is worth
            # measuring, and "which thermometer is outdoors" is largely
            # "the one in no area at all". A registry that did not answer
            # is a skipped builder, never `areas or []`: with no areas
            # every room is unnameable and the store would be written as
            # a house with no rooms in it.
            try:
                if ents is None or areas is None:
                    raise RuntimeError(
                        "the registries did not answer — the thermal store "
                        "was left as it was"
                        + (f" ({registry_error})" if registry_error else ""))
                rooms = _done("thermal", await thermal.build(
                    session, by_id,
                    {"areas": areas, "devices": devices or [],
                     "entities": ents}, started))
            except Exception as exc:  # noqa: BLE001
                _failed("thermal", exc)
        errors = [f"{name}: {b['error']}" for name, b in builders.items()
                  if not b["ok"]]
        summary = {"reason": reason, "started_at": int(started),
                   "finished_at": int(time.time()),
                   "duration_s": round(time.time() - started, 1),
                   "measured": len(payload.get("entities") or {}),
                   "asked": payload.get("asked", 0),
                   "closures": len(shut.get("entities") or {}),
                   "appliances": len(machines.get("entities") or {}),
                   "rooms": len(rooms.get("rooms") or {}),
                   "tz": payload.get("tz", ""),
                   "builders": builders,
                   "error": "; ".join(errors)[:300]}
        if builders.get("baselines", {}).get("ok"):
            journal.record("baselines", "ok", duration_s=summary["duration_s"],
                           extra={"measured": summary["measured"],
                                  "asked": summary["asked"]})
    except Exception as exc:  # noqa: BLE001 — a bad pass must not take the loop down
        log.warning("baseline pass failed: %s", exc)
        journal.record("baselines", "error", error=str(exc))
        summary = {"reason": reason, "started_at": int(started),
                   "finished_at": int(time.time()), "measured": 0, "asked": 0,
                   "closures": 0, "appliances": 0, "rooms": 0, "tz": "",
                   "builders": builders, "error": str(exc)[:300]}
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
            log.warning("baseline loop: %s", exc)
        # The Resident's nightly grading rides the same hourly wake: it
        # decides for itself whether a day has passed, off its own state
        # file, so a baseline build that failed does not hold it back.
        await _outcomes_tick(time.time())
        # The nightly readers that understand the house rather than measure
        # it (`_understanding_tick`). Their own try: a reading that fell over
        # must not take the baselines' clock with it.
        try:
            await _understanding_tick(time.time())
        except Exception as exc:  # noqa: BLE001
            log.debug("understanding tick: %s", exc)
        _beat("baselines")
        await asyncio.sleep(3600)


# ---------------------------------------------------------------------------
# Understanding the house — what each entity IS (`world_model`), what the
# house is doing NOW (`situation`) and what is COMING UP (`occasions`)
# ---------------------------------------------------------------------------
#
# Three readers with one shape: code builds what can be checked, and a
# cheap model fills in only what needs judgement, out of closed
# vocabularies that each module's `parse` validates before anything keeps
# it. Every scheduled turn answers to the three gates every scheduled
# Claude run answers to (`_resident_gate`); a press needs only a
# credential, `h_ideas_run`'s rule. All three claim the `resident` source:
# they are the attention loop's understanding of the house, and a probe
# rather than a conversation anybody had.

# The readings the last checks pass matched against its own registry —
# `_FACTS_CTX`'s rule: refreshed from the snapshot that pass fetched, never
# a registry read for this block's own sake. The bus's known set and its
# added safety classes read this.
WORLD_VIEW: dict = {"world": {}, "at": 0.0}
WORLD_STATE: dict = {"running": False, "starting": False, "last": None,
                     "held": "", "error": ""}
SITUATION_STATE: dict = {"running": False, "refreshed_at": 0.0,
                         "last_error": "", "published": False}
OCCASIONS_STATE: dict = {"running": False, "starting": False, "last": None,
                         "error": ""}
# The frame waits for the panel to settle, like every other loop here.
SITUATION_FIRST_DELAY_S = 90


def _note_world(snapshot: dict) -> None:
    world = snapshot.get("world") if isinstance(snapshot, dict) else None
    if isinstance(world, dict):
        WORLD_VIEW.update(world=world, at=time.time())


def _world_known_ids() -> frozenset:
    try:
        return world_model.important_ids(WORLD_VIEW["world"])
    except Exception:  # noqa: BLE001 — a reading is optional; the bus is not
        return frozenset()


def _world_safety_roles() -> dict:
    try:
        return world_model.added_safety(WORLD_VIEW["world"])
    except Exception:  # noqa: BLE001
        return {}


def _understanding_gate(settings: dict, pressed: bool) -> str:
    """Why no turn may be spent, or "". A press skips the budget and the
    automatic switch — asking by hand always runs — and still needs a
    credential, because there is nothing to run without one."""
    if pressed:
        return "" if engine.get_auth() else "there is no Claude credential"
    return _resident_gate(settings)


async def _registry_snapshot() -> dict:
    """States and the three registries, in the checks snapshot's shape.

    A registry that did not answer RAISES rather than reading as empty:
    with no registry every entity would be read with no area and no
    device, which is a reading of a different house.
    """
    import aiohttp

    import ha_data  # deferred so the module loads without aiohttp in tests
    async with aiohttp.ClientSession() as session:
        states = await ha_data._rest_get(session, "/states", timeout=60)
        areas, devices, ents = await ha_data._ws_commands(session, [
            {"type": "config/area_registry/list"},
            {"type": "config/device_registry/list"},
            {"type": "config/entity_registry/list"}])
    if not isinstance(states, list) or ents is None or areas is None:
        raise RuntimeError("Home Assistant did not answer for its states "
                           "and registries")
    return {"states": {s["entity_id"]: s for s in states
                       if isinstance(s, dict) and s.get("entity_id")},
            "entities": ents, "devices": devices or [], "areas": areas}


async def _world_model_pass(reason: str = "schedule", *, pressed: bool = False,
                            snap: dict | None = None,
                            now: float | None = None) -> dict:
    """Read what each changed entity IS. Returns what it did, for a test.

    Guarded synchronously before the first await (`start_auth_check`'s
    rule): two passes would pay twice for the same rows.
    """
    if WORLD_STATE["running"]:
        return {"skipped": "a reading is already running"}
    WORLD_STATE["running"] = True
    try:
        return await _world_model_read(reason, pressed, snap, now)
    except Exception as exc:  # noqa: BLE001 — a reading is optional; the
        # loop that asked for one is not.
        WORLD_STATE["error"] = str(exc)[:200]
        log.warning("the entity reading failed: %s", exc)
        return {"error": str(exc)[:200]}
    finally:
        WORLD_STATE["running"] = False
        WORLD_STATE["starting"] = False


async def _world_model_read(reason: str, pressed: bool, snap: dict | None,
                            now: float | None) -> dict:
    now = time.time() if now is None else float(now)
    store = await asyncio.to_thread(world_model.load)
    if snap is None:
        snap = await _registry_snapshot()
    cands = world_model.candidates(snap)
    pending = world_model.needs_reading(store, cands)
    if pressed and not pending:
        why = "every entity has a current reading"
        WORLD_STATE["held"] = why
        return {"held": why, "pending": 0}
    if not pressed:
        ok, why = world_model.due(store, now, len(pending))
        if not ok:
            WORLD_STATE["held"] = why
            return {"held": why, "pending": len(pending)}
    settings = await asyncio.to_thread(settings_store.load)
    excuse = _understanding_gate(settings, pressed)
    if excuse:
        WORLD_STATE["held"] = excuse
        return {"held": excuse, "pending": len(pending)}
    WORLD_STATE["held"] = ""

    world_model.prune(store, cands)
    batches, _rest = world_model.batches(store, cands)
    areas = world_model.area_names(snap)
    read = skipped = ran = 0
    error = ""
    for rows in batches:
        ran += 1
        try:
            result = await _claude(
                engine.run_claude, world_model.frame(rows, areas),
                world_model.SYSTEM, "", world_model.TIMEOUT_S, 2, "resident",
                job=world_model.JOB, schema=world_model.SCHEMA)
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": str(exc), "meta": {}}
        await asyncio.to_thread(_record_usage, result, "world-model")
        if not result.get("ok"):
            # A failed run is not a verdict about any row: nothing is
            # stored and the rest of the batches wait for the next pass,
            # because a cause that failed one call fails the next.
            error = str(result.get("error") or "the reading failed")[:200]
            break
        run_id = str((result.get("meta") or {}).get("session_id") or "")
        got = world_model.parse(_answer(result), rows, areas,
                                run_id=run_id, now=now)
        if not got:
            error = "the reply could not be read"
            break
        for desc in rows:
            if desc["entity_id"] not in got:
                got[desc["entity_id"]] = world_model.unanswered(
                    desc, run_id=run_id, now=now)
                skipped += 1
        store.setdefault("entities", {}).update(got)
        read += len(got) - skipped
        # Saved per batch, so a panel that dies mid-pass keeps what it paid
        # for — `healing`'s write-after-every-attempt rule.
        await asyncio.to_thread(world_model.save, store)
    remaining = len(world_model.needs_reading(store, cands))
    store["last_pass"] = {"at": int(now), "reason": reason, "batches": ran,
                          "read": read, "skipped": skipped,
                          "remaining": remaining, "error": error}
    store["failures"] = int(store.get("failures") or 0) + 1 if error else 0
    await asyncio.to_thread(world_model.save, store)
    WORLD_STATE["last"] = dict(store["last_pass"])
    WORLD_STATE["error"] = error
    WORLD_VIEW.update(world=world_model.view(store, cands), at=time.time())
    if error:
        log.warning("the entity reading stopped after %d batch(es): %s",
                    ran, error)
    else:
        log.info("read %d entit%s (%d said nothing about); %d still to read",
                 read, "y" if read == 1 else "ies", skipped, remaining)
    return dict(store["last_pass"])


def _start_world_model() -> bool:
    """Start a pressed reading. Flipped synchronously, `h_baselines_run`'s
    rule: `create_task` only schedules."""
    if WORLD_STATE["running"] or WORLD_STATE["starting"]:
        return False
    WORLD_STATE["starting"] = True
    try:
        asyncio.get_running_loop().create_task(
            _world_model_pass("manual", pressed=True))
    except RuntimeError:
        WORLD_STATE["starting"] = False
        raise
    return True


async def _understanding_tick(now: float) -> None:
    """The nightly readers, from the baseline loop's hourly tick. Each
    decides for itself whether it is due."""
    await _world_model_pass("schedule", now=now)
    await _occasions_pass("schedule", now=now)


def _house_date(now: float) -> str:
    """Today's date on the house's own clock, as `YYYY-MM-DD`."""
    return f"{_local_now(now):%Y-%m-%d}"


async def _occasions_pass(reason: str = "schedule", *, pressed: bool = False,
                          now: float | None = None) -> dict:
    """Read the next three days. Guarded like the entity reading."""
    if OCCASIONS_STATE["running"]:
        return {"skipped": "a read is already running"}
    OCCASIONS_STATE["running"] = True
    try:
        return await _occasions_read(reason, pressed, now)
    except Exception as exc:  # noqa: BLE001
        OCCASIONS_STATE["error"] = str(exc)[:200]
        log.warning("reading what is coming up failed: %s", exc)
        return {"error": str(exc)[:200]}
    finally:
        OCCASIONS_STATE["running"] = False
        OCCASIONS_STATE["starting"] = False


async def _occasions_fetch(calendars: list[str], now: float):
    """`(weather_id, unit, daily, hourly, calendar_response, errors)`."""
    import aiohttp

    import ha_data
    errors: dict[str, str] = {}
    async with aiohttp.ClientSession() as session:
        states = await ha_data._rest_get(session, "/states", timeout=60)
        weather = next((s for s in states or [] if isinstance(s, dict)
                        and str(s.get("entity_id") or "").startswith("weather.")),
                       None)
        weather_id = str((weather or {}).get("entity_id") or "")
        unit = str(((weather or {}).get("attributes") or {})
                   .get("temperature_unit") or "°C")
        if not weather_id:
            errors["weather"] = "this house has no weather entity"
        cmds = occasions.commands(weather_id, calendars, now)
        answers = await ha_data._ws_calls(session, cmds) if cmds else []
    daily = hourly = None
    cal: dict = {}
    for cmd, answer in zip(cmds, answers):
        if not answer.get("ok"):
            what = ("calendar" if cmd["domain"] == "calendar"
                    else "weather")
            errors[what] = (f"Home Assistant would not answer "
                            f"{cmd['domain']}.{cmd['service']}: "
                            f"{answer.get('error') or 'refused'}")[:200]
            continue
        body = occasions._response(answer.get("result"))
        if cmd["domain"] == "weather":
            rows = (body.get(weather_id) or {}).get("forecast")
            if cmd["service_data"]["type"] == "daily":
                daily = rows
            else:
                hourly = rows
        else:
            cal = body
    if weather_id and daily is None and hourly is None \
            and "weather" not in errors:
        errors["weather"] = "the forecast came back empty"
    return weather_id, unit, daily, hourly, cal, errors


async def _occasions_read(reason: str, pressed: bool,
                          now: float | None) -> dict:
    now = time.time() if now is None else float(now)
    store = await asyncio.to_thread(occasions.load)
    if not pressed and not occasions.due(store, now):
        return {"held": "read recently"}
    settings = await asyncio.to_thread(settings_store.load)
    calendars = list(settings.get("occasion_calendars") or [])
    tz, _name = baselines.house_timezone()
    today = _house_date(now)
    weather_id, unit, daily, hourly, cal, errors = await _occasions_fetch(
        calendars, now)
    days = occasions.forecast_days(daily, hourly, now=now, tz=tz, unit=unit)
    rows = occasions.notable_weather(days)

    events = occasions.calendar_events(cal, now=now, tz=tz) if calendars else []
    judged: list[dict] | None = None
    run_id = ""
    if events:
        excuse = _understanding_gate(settings, pressed)
        if excuse:
            errors["calendar"] = ("the calendar was read and not judged: "
                                  + excuse)
        else:
            try:
                result = await _claude(
                    engine.run_claude, occasions.prompt(events, today),
                    occasions.SYSTEM, "", occasions.TIMEOUT_S, 2, "resident",
                    job=occasions.JOB, schema=occasions.SCHEMA)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc), "meta": {}}
            await asyncio.to_thread(_record_usage, result, "occasions")
            if result.get("ok"):
                run_id = str((result.get("meta") or {}).get("session_id") or "")
                judged = occasions.parse(_answer(result), events, today=today)
            else:
                errors["calendar"] = ("the calendar could not be judged: "
                                      + str(result.get("error") or "")[:160])
    if judged is None:
        # Not judged this time is not "nothing on the calendar": what an
        # earlier read found stands until it ends.
        judged = [o for o in occasions.current(store, today)
                  if o.get("kind") != "weather"] if calendars else []
    found = (rows + judged)[:occasions.MAX_OCCASIONS]
    filed = await asyncio.to_thread(occasions.file_facts, found, run_id=run_id)
    new_store = {"built_at": int(now), "reason": reason,
                 "occasions": found, "weather": weather_id,
                 "calendars": calendars, "events": len(events),
                 "filed": filed, "errors": errors}
    await asyncio.to_thread(occasions.save, new_store)
    OCCASIONS_STATE["last"] = {k: new_store[k] for k in
                               ("built_at", "reason", "weather", "events",
                                "filed", "errors")}
    OCCASIONS_STATE["error"] = "; ".join(errors.values())[:300]
    return {"occasions": found, "errors": errors, "filed": filed}


def _start_occasions() -> bool:
    if OCCASIONS_STATE["running"] or OCCASIONS_STATE["starting"]:
        return False
    OCCASIONS_STATE["starting"] = True
    try:
        asyncio.get_running_loop().create_task(
            _occasions_pass("manual", pressed=True))
    except RuntimeError:
        OCCASIONS_STATE["starting"] = False
        raise
    return True


async def _fetch_states_once() -> list:
    import aiohttp

    import ha_data
    async with aiohttp.ClientSession() as session:
        states = await ha_data._rest_get(session, "/states", timeout=30)
    if not isinstance(states, list):
        raise RuntimeError("Home Assistant did not answer for its states")
    return states


async def _situation_refresh(now: float | None = None, *, states=None,
                             run_model: bool = True) -> dict:
    """Rebuild the frame, describe it if it moved, publish the reading.

    One `/states` read; everything else is a store brAIn already wrote.
    Returns the public reading.
    """
    if SITUATION_STATE["running"]:
        return situation.reading(situation.load(), now)
    SITUATION_STATE["running"] = True
    try:
        return await _situation_pass(now, states, run_model)
    finally:
        SITUATION_STATE["running"] = False


async def _situation_pass(now: float | None, states, run_model: bool) -> dict:
    now = time.time() if now is None else float(now)
    store = await asyncio.to_thread(situation.load)
    settings = await asyncio.to_thread(settings_store.load)
    tz, tz_name = baselines.house_timezone()
    try:
        if states is None:
            states = await _fetch_states_once()
        upcoming = occasions.lines(await asyncio.to_thread(occasions.load),
                                   _house_date(now))
        frame = situation.build_frame(
            states, now=now, tz=tz, tz_name=tz_name,
            areas=dict(_NAMES), names=dict(_NAMES),
            closures_store=await asyncio.to_thread(closures.load),
            appliances_store=await asyncio.to_thread(appliances.load),
            calendars=settings.get("occasion_calendars") or [],
            occasions=upcoming, world=WORLD_VIEW["world"])
    except Exception as exc:  # noqa: BLE001 — a frame that could not be
        # built is a frame that says so; it reads `unknown`, never `away`.
        frame = situation.failed_frame(now, str(exc))
    store["frame"] = frame
    due, why = situation.due(store, frame, now)
    if due and run_model:
        if situation.runs_today(store, now, tz) >= situation.MAX_RUNS_PER_DAY:
            why = "the day's readings are spent"
        else:
            why = _understanding_gate(settings, False)
        if not why:
            local = _local_now(now)
            day = f"{local:%Y-%m-%d}"
            store["runs"] = situation.runs_today(store, now, tz) + 1
            store["day"] = day
            store["last_run_at"] = now
            try:
                result = await _claude(
                    engine.run_claude,
                    situation.prompt(frame, store.get("answer")),
                    situation.SYSTEM, "", situation.TIMEOUT_S, 2, "resident",
                    job=situation.JOB, schema=situation.SCHEMA)
            except Exception as exc:  # noqa: BLE001
                result = {"ok": False, "error": str(exc), "meta": {}}
            await asyncio.to_thread(_record_usage, result, "situation")
            if result.get("ok"):
                store["answer"] = situation.parse(
                    _answer(result), frame, store.get("answer"), now=now,
                    run_id=str((result.get("meta") or {}).get("session_id")
                               or ""))
                SITUATION_STATE["last_error"] = ""
            else:
                why = ("the last reading failed: "
                       + str(result.get("error") or "")[:120])
                SITUATION_STATE["last_error"] = why
    store["held"] = why
    await asyncio.to_thread(situation.save, store)
    read = situation.reading(store, now)
    SITUATION_STATE["refreshed_at"] = now
    SITUATION_STATE["published"] = await asyncio.to_thread(
        situation.publish, read)
    return read


async def _situation_loop() -> None:
    await asyncio.sleep(SITUATION_FIRST_DELAY_S)
    while True:
        try:
            await _situation_refresh()
        except Exception as exc:  # noqa: BLE001 — never let this kill the loop
            SITUATION_STATE["last_error"] = str(exc)[:200]
            log.debug("situation loop: %s", exc)
        await asyncio.sleep(situation.REFRESH_S)


def _situation_line(now: float) -> str:
    """The compact line every first look carries — read off the store, so a
    look never waits on a frame being built."""
    try:
        return situation.prompt_line(situation.reading(situation.load(), now))
    except Exception:  # noqa: BLE001 — context is optional; the look is not
        return ""


def _understanding_diagnostics() -> dict:
    """Counts and verdicts, never the readings or the frame themselves."""
    out: dict = {}
    try:
        store = world_model.load()
        out["world"] = {**world_model.summary(store),
                        "running": WORLD_STATE["running"],
                        "held": WORLD_STATE["held"],
                        "error": WORLD_STATE["error"],
                        "in_use": len(WORLD_VIEW["world"]),
                        "important": len(_world_known_ids()),
                        "added_safety": len(_world_safety_roles())}
    except Exception as exc:  # noqa: BLE001
        out["world"] = {"error": str(exc)[:200]}
    try:
        read = situation.reading(situation.load())
        out["situation"] = {
            "house_mode": read["house_mode"], "source": read["source"],
            "reason": read["reason"], "frame_at": read["frame_at"],
            "generated_at": read["generated_at"],
            "sentence_stale": read["sentence_stale"],
            "published": SITUATION_STATE["published"],
            "last_error": SITUATION_STATE["last_error"]}
    except Exception as exc:  # noqa: BLE001
        out["situation"] = {"error": str(exc)[:200]}
    try:
        store = occasions.load()
        out["occasions"] = {
            "built_at": store.get("built_at"),
            "count": len(store.get("occasions") or []),
            "calendars": len(store.get("calendars") or []),
            "weather": bool(store.get("weather")),
            "errors": store.get("errors") or {}}
    except Exception as exc:  # noqa: BLE001
        out["occasions"] = {"error": str(exc)[:200]}
    return out


async def h_world(request: web.Request) -> web.Response:
    """The entity readings: the summary, and one entity's on request."""
    store = await asyncio.to_thread(world_model.load)
    payload: dict = {**world_model.summary(store),
                     "running": WORLD_STATE["running"] or WORLD_STATE["starting"],
                     "held": WORLD_STATE["held"]}
    eid = (request.query.get("entity_id") or "").strip()
    if eid:
        if not ha_data_is_entity_id(eid):
            raise web.HTTPBadRequest(text="not an entity id")
        payload["entity"] = (store.get("entities") or {}).get(eid)
    return web.json_response(payload)


def ha_data_is_entity_id(value: str) -> bool:
    import ha_data  # noqa: PLC0415
    return ha_data.is_entity_id(value)


async def h_world_run(request: web.Request) -> web.Response:
    """Read the entities that changed, now. Skips the budget."""
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    if not _start_world_model():
        raise web.HTTPConflict(text="already reading the house")
    return web.json_response({"started": True})


async def h_situation(request: web.Request) -> web.Response:
    """What the house is doing now, and the frame that says so."""
    store = await asyncio.to_thread(situation.load)
    read = situation.reading(store)
    return web.json_response({**read, "frame": store.get("frame") or {}})


async def h_occasions(request: web.Request) -> web.Response:
    """What is coming up, which calendars brAIn may read, and which exist."""
    store = await asyncio.to_thread(occasions.load)
    settings = await asyncio.to_thread(settings_store.load)
    now = time.time()
    available = sorted(eid for eid in _NAMES if eid.startswith("calendar."))
    return web.json_response({
        "occasions": occasions.current(store, _house_date(now)),
        "lines": occasions.lines(store, _house_date(now)),
        "built_at": store.get("built_at"),
        "errors": store.get("errors") or {},
        "calendars": list(settings.get("occasion_calendars") or []),
        "available": [{"entity_id": eid,
                       "name": (_NAMES.get(eid) or {}).get("name") or eid}
                      for eid in available],
        "running": OCCASIONS_STATE["running"] or OCCASIONS_STATE["starting"]})


async def h_occasions_run(request: web.Request) -> web.Response:
    """Read the next three days now. Skips the budget."""
    if not _start_occasions():
        raise web.HTTPConflict(text="already reading what is coming up")
    return web.json_response({"started": True})


async def h_baselines(request: web.Request) -> web.Response:
    """What brAIn thinks is normal, as numbers rather than as a verdict."""
    store = await asyncio.to_thread(baselines.load)
    entity_id = (request.query.get("entity_id") or "").strip()
    payload = {
        "built_at": store.get("built_at", 0),
        "tz": store.get("tz", ""),
        "days": store.get("days", baselines.HISTORY_DAYS),
        "measured": len(store.get("entities") or {}),
        "asked": store.get("asked", 0),
        "cut": store.get("cut_count", 0),
        "cut_sample": list(store.get("cut") or []),
        "stale": baselines.is_stale(store) if store.get("built_at") else True,
        "running": _baselines_busy(),
        "last": BASELINE_STATE["last"],
    }
    if entity_id:
        if not actions.is_entity_id(entity_id):
            return web.json_response({"error": "not an entity id", **payload},
                                     status=400)
        payload["entity_id"] = entity_id
        payload["baseline"] = (store.get("entities") or {}).get(entity_id)
    return web.json_response(payload)


CURIOSITY_STATE: dict = {"starting": False}


async def h_curiosity(request: web.Request) -> web.Response:
    """What brAIn is curious about, and what it has worked out."""
    payload = await asyncio.to_thread(_curiosity_diagnostics)
    payload["running"] = bool(CURIOSITY_STATE["starting"])
    return web.json_response(payload)


async def h_curiosity_ask(request: web.Request) -> web.Response:
    """Ask the next question now, rather than waiting for a checks pass.

    **It spends a Claude run**, which is why it is a press and not a
    poll, and why it answers with what it started rather than with what
    it found: a run is minutes of model time, longer than ingress will
    hold a request open — `h_baselines_run`'s clock, and BRight's
    `_claude_job` failure before it. The outcome is read back from
    `GET /api/curiosity`.

    It deliberately ignores the day-and-week budget and nothing else. The
    budget exists to stop an *unattended* schedule spending money nobody
    asked it to; somebody pressing this has asked, which is the whole
    difference, and the same reason `budget_state` lets a typed question
    run while automatic insights are paused. What it does not ignore is
    the settling: a subject already asked about stays asked about, or the
    button would be a way to buy the same answer twice.
    """
    if CURIOSITY_STATE["starting"]:
        return web.json_response(
            {"running": True, "error": "brAIn is already working one out"},
            status=409)
    now = time.time()
    try:
        tz, _name = await asyncio.to_thread(baselines.house_timezone)
        ledger = await asyncio.to_thread(manual_ledger.load)
        found = await asyncio.to_thread(
            manual_ledger.candidates, ledger, tz, now)
        store = await asyncio.to_thread(curiosity.load)
        ranked = await asyncio.to_thread(
            curiosity.worth_asking, found, store, now, tz)
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"error": str(exc)[:200]}, status=500)
    # The budget is skipped and the settling is not, so what is askable
    # here is "eligible, whether or not there is room today" — which is
    # `why` or `hold`, never `skip`.
    askable = [r for r in ranked if r.get("why") or r.get("hold")]
    if not askable:
        return web.json_response(
            {"asked": 0, "error": "there is nothing brAIn cannot already "
                                  "account for"}, status=409)
    candidate = dict(askable[0])
    candidate.pop("hold", None)
    candidate["why"] = candidate.get("why") or curiosity.describe(candidate)
    # Flipped synchronously, for `start_auth_check`'s reason: a task that
    # has not been scheduled yet has set no flag, so two presses in one
    # tick would both pass a guard reading their own task's state.
    CURIOSITY_STATE["starting"] = True
    await asyncio.to_thread(curiosity.mark_asked, candidate, now)

    async def run_it() -> None:
        try:
            await _run_curiosity(candidate, ledger, tz, now)
        except Exception as exc:  # noqa: BLE001
            log.warning("a curiosity run failed: %s", exc)
            await asyncio.to_thread(curiosity.record_answer,
                                    candidate["subject"], None, "",
                                    str(exc)[:200], now)
        finally:
            CURIOSITY_STATE["starting"] = False
            await asyncio.to_thread(publish_diagnostics)

    asyncio.create_task(run_it())
    return web.json_response({"asked": 1, "running": True,
                              "subject": candidate["subject"],
                              "why": candidate["why"]})


async def h_baselines_run(request: web.Request) -> web.Response:
    """Start a measurement pass. Does NOT wait for it.

    A pass reads a month of hourly statistics for every numeric sensor in
    the house, plus ten days of five-minute statistics for the power ones
    — minutes of recorder work, which is longer than ingress will hold a
    request open. Awaiting it here handed the browser the *absence* of a
    reply while the pass ran on and wrote its stores anyway, which is
    BRight's `_claude_job` failure with a different clock. The outcome is
    read back from `GET /api/baselines`, which has carried `running` and
    `last` since the loop existed.

    It had no caller at all until this — no button, no CLI, nothing in
    the integration — which is the "a button that exists only in prose is
    a button nobody can press" rule, and it is the whole reason a fix to
    a nightly measurement took a day to be visible and could not be
    checked at all: the doors-and-windows fix shipped, the store went on
    reading `0 of 18` because the nightly pass had not come round yet,
    and there was nothing anywhere to ask it to measure now.
    """
    if _baselines_busy():
        return web.json_response(
            {"running": True, "error": "a baseline pass is already running",
             "last": BASELINE_STATE["last"]}, status=409)
    # `starting` rather than `running`, and flipped synchronously, for
    # `start_auth_check`'s reason: `create_task` only schedules, so
    # nothing inside the coroutine has run when the next request arrives
    # — two presses in one tick would both pass a guard reading the flag
    # their own task has not set yet. It is a second flag because
    # `build_baselines` owns `running` and is also called by the nightly
    # loop, and one function setting another's guard is how the two
    # callers stop agreeing about what is in flight.
    BASELINE_STATE["starting"] = True

    async def run_it() -> None:
        try:
            await build_baselines("manual")
        finally:
            BASELINE_STATE["starting"] = False
            publish_diagnostics()

    asyncio.create_task(run_it())
    return web.json_response({"running": True, "started": True,
                              "last": BASELINE_STATE["last"]}, status=202)


def _baselines_busy() -> bool:
    """Whether a measurement pass is in flight, however it was started."""
    return bool(BASELINE_STATE["running"] or BASELINE_STATE.get("starting"))


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


def _brief_block() -> dict:
    """What the morning brief is, in the aggregate's own shape.

    The two scheduled messages are the server's rather than `house.py`'s
    because they are about what brAIn *said*, not about what it has
    measured — but they belong in the same payload, because "there is
    nothing to say yet" and "there was something and it went out at 07:12"
    are the same screen's question.
    """
    on, fallback = _brief_enabled()
    local = _local_now(time.time())
    return {
        "enabled": on,
        "last_sent": int(BRIEF_STATE["last_sent"]),
        "text": BRIEF_STATE["last_text"],
        "reasons": list(BRIEF_STATE["last_reasons"]),
        "error": BRIEF_STATE["last_error"],
        "fallback_hour": fallback,
        # Whether the hour above is a measurement or the fallback. A brief
        # arriving at a typed-in hour and one arriving when this house is
        # actually up look identical from outside.
        "wake_measured": rhythm.wake_minute(
            rhythm.profile(), local) is not None,
    }


def _weekly_block() -> dict:
    on, want_day = _weekly_enabled()
    return {
        "enabled": on,
        "last_sent": int(WEEKLY_STATE["last_sent"]),
        "text": WEEKLY_STATE["last_text"],
        "error": WEEKLY_STATE["last_error"],
        "day": weekly.DAYS[want_day],
    }


async def h_house(request: web.Request) -> web.Response:
    """Every measurement's own answer about how far along it is.

    One route rather than seven, because the question a person is asking
    is about the house and not about any one store: a fresh install is
    silent everywhere at once, and seven separate fetches would tell them
    so seven times without ever adding up to "this is what brAIn is still
    waiting for".
    """
    import aiohttp  # noqa: PLC0415 — the module has no other need of it

    now = time.time()
    async with aiohttp.ClientSession() as session:
        week = await house.energy_week(session, now)
    payload = await asyncio.to_thread(house.snapshot, now, week,
                                      _brief_block(), _weekly_block())
    return web.json_response(payload)


def _baselines_rows(store: dict) -> list[dict]:
    rows = []
    for eid, entry in sorted((store.get("entities") or {}).items()):
        if not isinstance(entry, dict):
            continue
        rows.append({
            "entity_id": eid,
            # Nothing stores a friendly name against a baseline, and the
            # object id is what the store holds — saying so is better than
            # a name invented here that disagrees with Home Assistant's.
            "name": entry.get("name") or eid.split(".", 1)[-1].replace("_", " "),
            "unit": entry.get("unit") or "",
            "flat": bool(entry.get("flat")),
            "buckets_n": len(entry.get("buckets") or {}),
            "trend": entry.get("trend"),
        })
    return rows


def _closure_rows(store: dict) -> list[dict]:
    rows = []
    for eid, entry in sorted((store.get("entities") or {}).items()):
        if not isinstance(entry, dict):
            continue
        rows.append({
            "entity_id": eid,
            "name": entry.get("name") or eid.split(".", 1)[-1].replace("_", " "),
            "overall": entry.get("overall"),
            # The share only. The hours behind it are what made the bucket
            # count, and that number is already the store's `have`.
            "buckets": {h: (b or {}).get("open")
                        for h, b in (entry.get("buckets") or {}).items()},
        })
    return rows


def _thermal_payload(store: dict) -> dict:
    """The rooms, with the one derived number a person can act on.

    `hours_to_warm` is measured between this room's own extremes on the
    coldest night the month held — its coolest reading to its warmest,
    against `coldest` — because those are three numbers the store already
    holds. A target typed in here would be a threshold invented by the
    panel, which is the thing every floor in `thermal.py` exists to avoid.
    """
    outdoor = store.get("coldest")
    rooms = []
    for eid, entry in sorted((store.get("rooms") or {}).items()):
        if not isinstance(entry, dict):
            continue
        ends = (entry.get("coolest"), entry.get("warmest"))
        warm = None
        if isinstance(outdoor, (int, float)) and all(
                isinstance(v, (int, float)) for v in ends):
            warm = thermal.hours_to_warm(entry, ends[0], outdoor, ends[1])
        rooms.append({
            "id": eid,
            "name": entry.get("name") or eid.split(".", 1)[-1].replace("_", " "),
            "area": entry.get("area") or "",
            "k": entry.get("k"),
            "tau_h": entry.get("tau_h"),
            "gain": entry.get("gain"),
            "warmest": entry.get("warmest"),
            "coolest": entry.get("coolest"),
            "hours_to_warm": None if warm is None else round(warm, 1),
        })
    # The reference every `k` above was measured against, why it was the
    # one, and what else could have been — so the tab can say it and the
    # person who knows better can change it (`thermal_outdoor`). The
    # choice is read live: it takes effect at the next nightly pass, and
    # the tab has to be able to say a choice is waiting for one.
    try:
        chosen = settings_store.load().get("thermal_outdoor")
    except Exception:  # noqa: BLE001 — a setting nobody could read is unset
        chosen = None
    return {"outdoor": store.get("outdoor") or "",
            "unit": store.get("unit") or "",
            "outdoor_source": store.get("outdoor_source") or "",
            "outdoor_why": store.get("outdoor_why") or "",
            "outdoor_candidates": list(store.get("outdoor_candidates") or []),
            "outdoor_choice": chosen,
            "rooms": rooms}


async def _appliance_detail(now: float) -> dict:
    """Every profiled machine, and what each one is doing right now.

    The shapes are the nightly store's; what a machine is doing *now* is a
    live question, so this is the one drill-down that fetches — the same
    split and the same cheap fetch the checks pass makes, over the same
    window, so the tab and the chore cannot disagree about which machine
    is running.
    """
    import aiohttp  # noqa: PLC0415
    import datetime  # noqa: PLC0415

    store = await asyncio.to_thread(appliances.load)
    shapes = store.get("entities") or {}
    live: dict = {}
    error = ""
    ids = sorted(shapes)
    if ids:
        start = datetime.datetime.fromtimestamp(
            now - checks.snapshot.APPLIANCE_HOURS * 3600,
            tz=datetime.timezone.utc)
        try:
            async with aiohttp.ClientSession() as session:
                live = await appliances.fetch(session, ids, start)
            if live is None:
                # The recorder refused: what each machine is doing now is
                # unknown, which is not "idle".
                live, error = {}, ("the recorder did not answer for the "
                                   + "appliance sensors")
        except Exception as exc:  # noqa: BLE001 — the shapes still answer
            live, error = {}, str(exc)[:200]
    rows = []
    for eid, shape in sorted(shapes.items()):
        rows.append({"entity_id": eid, **shape,
                     "chore_kind": checks.chores.kind_of(shape.get("name") or ""),
                     "now": appliances.state_at(shape, live.get(eid) or [], now)
                     if live else {}})
    return {"built_at": store.get("built_at", 0),
            "asked": store.get("asked", 0),
            "days": store.get("days", appliances.HISTORY_DAYS),
            "hours": checks.snapshot.APPLIANCE_HOURS,
            "live_error": error,
            "appliances": rows}


def _habits_payload(now: float) -> dict:
    """What this house does by hand, and what it keeps undoing.

    One payload because they are one question from a person's side, and
    the patterns ride beside the raw overrides because a count with no
    shape is what `auto.overridden` shipped as and could not act on.
    """
    tz, _name = baselines.house_timezone()
    ledger = routines.load()
    rows = override_ledger.load()
    patterns = []
    for key, group in sorted(override_ledger.by_automation(rows).items()):
        shape = override_ledger.pattern(group, tz, now)
        if shape:
            patterns.append({"automation": key,
                             "name": group[-1].get("by_name") or key,
                             **shape})
    return {
        "routines": {
            "presses": len(ledger.get("rows") or []),
            "rows": routines.mine(ledger, tz, now),
            "automated": len(ledger.get("automated") or {}),
        },
        "overrides": {
            "events": len(rows),
            "automations": len(override_ledger.by_automation(rows)),
            "recent": sorted(rows, key=lambda r: r.get("ts") or 0,
                             reverse=True)[:50],
        },
        "patterns": patterns,
    }


async def h_house_store(request: web.Request) -> web.Response:
    """One measurement in full — the rows behind the aggregate's number.

    Split from the aggregate rather than folded into it because these are
    the expensive halves: every closure's whole week, every baseline in
    the house, a live recorder fetch. The aggregate is polled; this is
    opened.
    """
    name = request.match_info["name"]
    if name not in house.STORES:
        raise web.HTTPNotFound(text=f"no measurement called {name[:40]}")
    now = time.time()
    if name == "rhythm":
        return web.json_response(await asyncio.to_thread(rhythm.profile))
    if name == "baselines":
        store = await asyncio.to_thread(baselines.load)
        return web.json_response(_baselines_rows(store))
    if name == "thermal":
        store = await asyncio.to_thread(thermal.load)
        return web.json_response(_thermal_payload(store))
    if name == "closures":
        store = await asyncio.to_thread(closures.load)
        return web.json_response(_closure_rows(store))
    if name == "appliances":
        return web.json_response(await _appliance_detail(now))
    if name == "habits":
        return web.json_response(await asyncio.to_thread(_habits_payload, now))
    import aiohttp  # noqa: PLC0415

    async with aiohttp.ClientSession() as session:
        return web.json_response(await house.energy_week(session, now))


async def h_checks(request: web.Request) -> web.Response:
    return web.json_response({
        # `shadow` per row rather than a separate list: `brain check list`
        # prints one catalog, and a check that files somewhere the tab
        # does not render has to say so on its own line or somebody goes
        # looking for rows that are not there.
        "catalog": [{"id": c["id"], "title": c["title"],
                     "group": checks.title_for(c["id"]),
                     "shadow": checks.is_shadow(c["id"])}
                    for c in checks.CHECKS],
        "last": CHECKS_STATE["last"],
        "running": CHECKS_STATE["running"],
        "interval_hours": eff_checks_interval_hours(),
    })


async def h_checks_run(request: web.Request) -> web.Response:
    summary = await run_checks("manual")
    status = 409 if summary.get("error") == "a checks pass is already running" else 200
    return web.json_response(summary, status=status)


# ---------------------------------------------------------------------------
# The deep doctor — every face, one real round trip each
# ---------------------------------------------------------------------------
# `brain doctor` says whether the plumbing is connected; this says whether
# each face works end to end on this install. It is opt-in and costed and
# NEVER on a timer — the design page's own words, and the same rule the
# auth re-check follows for the same reason: a real Claude turn spent on a
# question nobody is asking is a turn spent forever.
#
# It rides the generation queue like a fix run does, so one deep run is in
# flight at a time. Its stages call the engine from `doctor.py` directly
# rather than through `run_queue` — a press somebody made, a handful of
# short runs — so they take no seat there; the queue's bound is on what
# the server itself starts.
DOCTOR_JOB = "doctor-deep"
DOCTOR_STATE: dict = {"running": False, "started_at": 0,
                      "stages": [], "last": None, "kind": ""}


def _doctor_hooks() -> "doctor.Hooks":
    """The panel's own implementations, handed to the stages.

    Three of the eight stages act on stores the server owns, and this is
    the whole of how they reach them: `_end_finding` is the ending every
    button and every To-do tick already goes through, `_undo_finding` is
    what the toast's Undo calls, and `_consolidate_now` is the same
    subprocess the Memory tab's button starts. A deep run that used copies
    of those would be testing the copies.
    """
    async def ws(commands: list[dict]):
        import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`
        import aiohttp  # noqa: PLC0415
        async with aiohttp.ClientSession() as session:
            return await ha_data._ws_commands(session, commands)

    return doctor.Hooks(
        end_finding=_end_finding,
        undo_finding=lambda entry: asyncio.to_thread(_undo_finding, entry),
        queue_memory=_queue_memory_fact,
        # The queue AND the facts store: the deep check's probe is read
        # into the store within the minute, and a cleanup that took it out
        # of the inbox and the document left a fact behind every run read.
        drop_memory=_unqueue_fact,
        inbox_pending=_inbox_pending,
        memory_text=_read_shared_memory,
        consolidate=_consolidate_now,
        record_usage=_record_usage,
        ws=ws,
        model=eff_model(),
        options=addon_options.snapshot() or {},
    )


def _doctor_payload() -> dict:
    """What `GET /api/doctor/deep` answers, running or not."""
    return {
        "running": DOCTOR_STATE["running"],
        "kind": DOCTOR_STATE["kind"],
        "started_at": DOCTOR_STATE["started_at"],
        "stages": DOCTOR_STATE["stages"],
        "last": DOCTOR_STATE["last"] or doctor.load() or None,
        "stage_catalog": [{"name": s["name"], "title": s["title"],
                           "proves": s["proves"]} for s in doctor.STAGES],
    }


async def _run_doctor_deep(job_id: str) -> None:
    """One deep run, on the generation queue's worker."""
    DOCTOR_STATE.update(running=True, kind="deep", stages=[],
                        started_at=int(time.time()))
    _set_job(job_id, state="generating", error="")
    try:
        def progress(payload: dict) -> None:
            DOCTOR_STATE["stages"] = payload["stages"]

        payload = await doctor.run_deep(_doctor_hooks(), progress=progress)
        DOCTOR_STATE.update(stages=payload["stages"], last=payload)
        await asyncio.to_thread(doctor.save, payload)
        _set_job(job_id, state="done", error="")
        log.info("deep doctor: %s (%s)", payload["verdict"],
                 ", ".join(f"{k} {v}" for k, v in payload["counts"].items()))
    except Exception as exc:  # noqa: BLE001 — the report is the product
        log.warning("deep doctor failed: %s", exc)
        _set_job(job_id, state="error", error=str(exc)[:500])
    finally:
        DOCTOR_STATE.update(running=False, kind="")
        publish_diagnostics()


async def h_doctor_deep_get(request: web.Request) -> web.Response:
    return web.json_response(_doctor_payload())


async def h_doctor_deep_start(request: web.Request) -> web.Response:
    """Start one. A second caller gets the one already running.

    409 with the live job's id rather than a collision, the way BRight's
    Claude jobs answer a second press: both presses are watching the same
    run, and starting a second would put two Claude invocations in flight
    against a subscription that allows one.
    """
    if DOCTOR_STATE["running"]:
        return web.json_response(
            {"error": f"a {DOCTOR_STATE['kind'] or 'deep'} check is already "
                      "running", "job": DOCTOR_JOB, **_doctor_payload()},
            status=409)
    _set_job(DOCTOR_JOB, kind="doctor", state="queued", error="")
    QUEUE.put_nowait(DOCTOR_JOB)
    return web.json_response({"started": True, "job": DOCTOR_JOB,
                              **_doctor_payload()})


# ---------------------------------------------------------------------------
# The rehearsal — planted defects on the real house
# ---------------------------------------------------------------------------
REHEARSE_JOB = "doctor-rehearse"
SWEEP_JOB = "doctor-sweep"


def _rehearsal_hooks() -> "rehearsal.Hooks":
    """The panel's write, remove and snapshot, handed to the rehearsal.

    `_apply_accepted` and `_remove_automation` are the two halves of what
    an accepted proposal does; using them here is what makes a rehearsal a
    real round trip of the writer rather than a test of a copy of it.
    """
    async def write(row: dict):
        return await _apply_accepted(row)

    async def remove(entry_id: str, entity_id: str = ""):
        written, failure = await _remove_automation(entry_id, entity_id or "")
        return written is not None, failure

    async def snapshot():
        return await checks.snapshot.collect(time.time())

    async def ws(commands: list[dict]):
        """`_ws_calls`, not `_ws_commands`: these commands CHANGE things.

        A successful `input_number/delete` answers `result: null`, which
        `_ws_commands` hands back as the same `None` that means the call
        failed — so a clean cleanup reported that Home Assistant would
        not delete the helper it had just deleted.
        """
        import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`
        import aiohttp  # noqa: PLC0415
        async with aiohttp.ClientSession() as session:
            return await ha_data._ws_calls(session, commands)

    return rehearsal.Hooks(write=write, remove=remove, snapshot=snapshot,
                           analyst=_rehearsal_analyst, ws=ws,
                           options=addon_options.snapshot() or {})


async def _rehearsal_analyst(planted: list[dict]) -> dict:
    """The automations card's own prompt, run once, persisting nothing.

    It goes through `build_orientation_prompt` and `ANALYST_SYSTEM` — the
    same builders `_search_run` uses — because what is being measured is
    the prompt people actually get. What it does NOT do is save a card,
    file its findings or queue its `learned` facts: a self-test that left
    a card behind would be reporting on a house it had changed.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    cat = get_category(rehearsal.ANALYST_CATEGORY)
    if cat is None:
        return {"ok": False, "findings": [],
                "error": f"there is no {rehearsal.ANALYST_CATEGORY} category "
                         "in this build"}
    try:
        orientation = await ha_data.collect_orientation(question=None)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "findings": [],
                "error": f"could not collect the orientation map: {exc}"}
    framing = dict(question=None, feedback=[],
                   hypothesis_budget=0, knowledge="", previous=None,
                   findings="")
    prompt = rehearsal.analyst_prompt(planted, build_orientation_prompt, cat,
                                      orientation, framing)
    model = eff_model()
    answer = await asyncio.to_thread(rehearsal.run_analyst, prompt,
                                     ANALYST_SYSTEM, model)
    _record_usage(answer.get("result") or {}, "doctor-rehearsal")
    answer.pop("result", None)
    if answer.get("ok"):
        return answer
    # The floor the card has and this did not. `_generate` slides a failed
    # or turn-exhausted search onto the snapshot path, so a card always
    # appears; the rehearsal ran only the search half and scored a
    # turn-exhausted run as `ran: false`, precision and recall both null.
    # That is a measurement of a path no card ever takes alone — and it
    # reported the analyst as not having run on a house where a card
    # would have been produced. `fallback` is carried rather than hidden,
    # the same way the journal records the slide: a rehearsal that keeps
    # taking it is saying something about the search path, and a number
    # with no note on how it was reached is the one nobody can act on.
    log.info("rehearsal: the search run did not land (%s) — falling back to "
             "the snapshot path, as a card would", answer.get("error", ""))
    searched = answer.get("error") or ""
    try:
        bundle = await ha_data.collect_bundle(
            cat, eff_history_days(), question=None)
    except Exception as exc:  # noqa: BLE001
        answer["error"] = (f"{searched}; and the snapshot fallback could "
                           f"not collect the home either: {exc}")
        return answer
    prompt = rehearsal.analyst_prompt(planted, build_prompt, cat, bundle,
                                      framing)
    answer = await asyncio.to_thread(rehearsal.run_analyst, prompt,
                                     SYSTEM_PROMPT, model, False)
    _record_usage(answer.get("result") or {}, "doctor-rehearsal")
    answer.pop("result", None)
    answer["fallback"] = True
    answer["searched_error"] = journal.scrub(searched)[:200]
    return answer


def _rehearsal_payload() -> dict:
    """State, and the offer.

    The plan rides the GET as well as the 428, because the panel has to be
    able to draw the confirmation dialog without first making a request it
    expects to fail. The 428 is still the contract for every other caller —
    the CLI, an automation, anything that POSTs without reading this first —
    and it is what keeps "nothing is created before consent" true of the
    API rather than only of the button.
    """
    protected = (addon_options.snapshot() or {}).get("protected_entities")
    last = rehearsal.load() or None
    return {
        "running": DOCTOR_STATE["running"] and DOCTOR_STATE["kind"] == "rehearse",
        # The sweep is its own press and its own in-flight state: a button
        # that greys itself out while the OTHER one runs is the pair of
        # controls nobody can tell apart.
        "sweeping": DOCTOR_STATE["running"] and DOCTOR_STATE["kind"] == "sweep",
        "started_at": DOCTOR_STATE["started_at"],
        "progress": DOCTOR_STATE.get("progress") or {},
        "last": last,
        # Whether there is anything for a sweep to take out, derived HERE
        # rather than in the panel: a control that offers to clear
        # nothing is a control asking to be understood, and two answers
        # to "is there litter" is how the button and the fault row start
        # disagreeing. Off the stored record, never a live snapshot — a
        # registry-and-states collect on every poll of a dialog somebody
        # has open is a read nobody asked for, and the record is what
        # every other surface reports from.
        "leftovers": rehearsal.outstanding(last),
        **rehearsal.plan(protected),
    }


async def _run_rehearsal(job_id: str) -> None:
    DOCTOR_STATE.update(running=True, kind="rehearse", stages=[],
                        progress={}, started_at=int(time.time()))
    _set_job(job_id, state="generating", error="")
    try:
        def progress(payload: dict) -> None:
            DOCTOR_STATE["progress"] = {"step": payload.get("step", ""),
                                        "created": payload.get("created") or []}

        payload = await rehearsal.run(_rehearsal_hooks(), progress=progress)
        await asyncio.to_thread(rehearsal.save, payload)
        DOCTOR_STATE["progress"] = {}
        _set_job(job_id, state="done", error="")
        swept = (payload.get("swept") or {}).get("removed") or []
        if swept:
            log.warning("rehearsal: an earlier run left %s behind; taken "
                        "out before planting", ", ".join(map(str, swept[:8])))
        log.info("rehearsal: %s of %s planted defects found, cleanup %s",
                 (payload.get("checks") or {}).get("found", 0),
                 (payload.get("checks") or {}).get("planted", 0),
                 (payload.get("cleanup") or {}).get("sentence", "?"))
    except Exception as exc:  # noqa: BLE001 — rehearsal.run has its own
        # finally; this is the belt for anything outside it.
        log.warning("rehearsal failed: %s", exc)
        _set_job(job_id, state="error", error=str(exc)[:500])
    finally:
        DOCTOR_STATE.update(running=False, kind="")
        publish_diagnostics()


async def h_rehearse_get(request: web.Request) -> web.Response:
    return web.json_response(_rehearsal_payload())


async def h_rehearse_start(request: web.Request) -> web.Response:
    """Start one — but only with consent, and only after saying what for.

    **428 Precondition Required** without `{"consent": true}`, carrying the
    exact list of what would be created. Nothing is written before that
    answer comes back: planting automations in somebody's config is a step
    some people will not want, and an offer they cannot read is not one
    they can decline.
    """
    body = await _json_body(request)
    protected = (addon_options.snapshot() or {}).get("protected_entities")
    offer = await asyncio.to_thread(rehearsal.plan, protected)
    if offer["refused"]:
        return web.json_response(offer, status=409)
    if not body.get("consent"):
        return web.json_response(
            {**offer,
             "error": "a rehearsal creates things in your Home Assistant — "
                      "call again with {\"consent\": true} to go ahead"},
            status=428)
    if DOCTOR_STATE["running"]:
        return web.json_response(
            {"error": f"a {DOCTOR_STATE['kind'] or 'deep'} check is already "
                      "running", "job": REHEARSE_JOB, **_rehearsal_payload()},
            status=409)
    _set_job(REHEARSE_JOB, kind="rehearse", state="queued", error="")
    QUEUE.put_nowait(REHEARSE_JOB)
    return web.json_response({"started": True, "job": REHEARSE_JOB,
                              **offer, **_rehearsal_payload()})


async def _run_sweep(job_id: str) -> None:
    """Take out what an earlier rehearsal left, and plant nothing."""
    DOCTOR_STATE.update(running=True, kind="sweep", stages=[],
                        progress={"step": "clearing up"},
                        started_at=int(time.time()))
    _set_job(job_id, state="generating", error="")
    try:
        out = await rehearsal.sweep_only(_rehearsal_hooks())
        DOCTOR_STATE["progress"] = {}
        _set_job(job_id, state="done", error="")
        log.info("rehearsal sweep: %s", out.get("sentence") or "nothing to do")
    except Exception as exc:  # noqa: BLE001 — `sweep_only` has its own
        # refusals; this is the belt for anything outside them.
        log.warning("rehearsal sweep failed: %s", exc)
        _set_job(job_id, state="error", error=str(exc)[:500])
    finally:
        DOCTOR_STATE.update(running=False, kind="")
        publish_diagnostics()


async def h_rehearse_sweep(request: web.Request) -> web.Response:
    """Clear the `brain_test_*` litter, creating nothing.

    **No consent step, because nothing is created.** The 428 on
    `h_rehearse_start` exists because a rehearsal writes automations into
    somebody's config; this only ever removes what `rehearsal.leftovers`
    already sees under brAIn's own prefix — the same scan `brain doctor`
    warns about — so the thing being asked for is the thing being
    removed, and an offer to read would be an offer to re-read the
    warning that sent them here.
    """
    if DOCTOR_STATE["running"]:
        return web.json_response(
            {"error": f"a {DOCTOR_STATE['kind'] or 'deep'} check is already "
                      "running", "job": SWEEP_JOB, **_rehearsal_payload()},
            status=409)
    _set_job(SWEEP_JOB, kind="sweep", state="queued", error="")
    QUEUE.put_nowait(SWEEP_JOB)
    return web.json_response({"started": True, "job": SWEEP_JOB,
                              **_rehearsal_payload()})


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


async def _device_classes() -> dict[str, str]:
    """`{entity_id: device_class}` for the whole house, in one call.

    A `binary_sensor` with no class is a door, a motion sensor, a leak
    detector or a plug's own power flag, and `episodes.subject_for` will not
    guess between them — so without this every one of them lands in
    *Everything else*, which is the section people scroll past. One REST
    read of `/states` is what the checks pass and every insight run already
    spend, and a fetch that fails is an empty map rather than an error: a
    tab that could not tell a door from a motion sensor is still a tab, and
    that is what the refusal-to-guess is for.
    """
    import aiohttp
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`
    try:
        async with aiohttp.ClientSession() as session:
            raw = await ha_data._rest_get(session, "/states", timeout=30)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read device classes for the activity tab: %s", exc)
        return {}
    out: dict[str, str] = {}
    for st in raw or []:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        klass = str(((st.get("attributes") or {}).get("device_class")) or "")
        if eid and klass:
            out[eid] = klass
    return out


async def h_activity(request: web.Request) -> web.Response:
    """A window of the house's own history, as what HAPPENED in it.

    This used to answer with the mined rows themselves — one per state
    change, newest first — which is Home Assistant's own logbook with a
    cause column added, and on a real house it is hundreds of rows an hour
    of a sensor reporting a number. `episodes.group` is what turns that into
    the things a person would say happened, in sections they would look for.

    Fetched per request and never cached: this is a question somebody is
    asking now, the answer changes every few seconds, and a cache would be a
    second copy of the logbook to keep true.
    """
    start, end = _activity_window(request)
    try:
        mined = await _activity(start, end)
    except Exception as exc:  # noqa: BLE001 — a failed look is an answer
        log.warning("activity fetch failed: %s", exc)
        return web.json_response({"available": False, "error": str(exc)[:200],
                                  "sections": [], "away": [], "counts": {},
                                  "dropped": 0, "changes": 0, "episodes": 0,
                                  "start": start, "end": end})
    classes = await _device_classes() if mined.get("available") else {}
    now = time.time()

    def shape() -> dict:
        rows = mined["actions"]
        cause = (request.query.get("cause") or "").strip()
        if cause and cause in actions.CAUSES:
            rows = [a for a in rows if a["cause"] == cause]
        grouped = episodes.group(rows, classes, now)
        # On the row it happened in, never in a block above the list: a
        # count of "somebody put things back 4×" is not something anybody
        # can act on, where *this* row being the one they undid is.
        episodes.mark_overrides(grouped, mined.get("overrides") or [])
        return {
            "available": True,
            "error": "",
            "start": mined["start"],
            "end": mined["end"],
            # The window that was actually used, not the one asked for: a
            # request for a week gets two days, and a caller echoing its
            # own argument would report a window it never had.
            "hours": _window_hours(mined["start"], mined["end"]),
            "sections": episodes.sections(grouped),
            # When the house was empty — the one thing here Home Assistant
            # holds every fact for and has never said.
            "away": episodes.away_spans(grouped, now),
            "counts": mined["counts"],
            "causes": list(actions.CAUSES),
            "capped": mined.get("capped", False),
            # What was NOT shown, and why. A list that quietly drops nine
            # tenths of its input is the thing this replaced.
            "dropped": grouped["dropped"],
            "changes": sum(e["count"] for e in grouped["episodes"]),
            "episodes": len(grouped["episodes"]),
        }

    return web.json_response(await asyncio.to_thread(shape))


# One paragraph per window, kept against the window it is about. Pressing
# twice must not cost twice, and the answer cannot change without the
# window changing — but a window that ends "now" moves, so the key rounds
# to the minute rather than pretending an open-ended one is stable.
_ACTIVITY_SUMMARIES: dict[tuple[int, int], dict] = {}
_ACTIVITY_SUMMARY_MAX = 12


async def h_activity_summary(request: web.Request) -> web.Response:
    """What this window adds up to, in a paragraph — and it is a PRESS.

    Everything else on this tab is arithmetic over one fetch, so opening it
    is free however often somebody does. This is the part that spends, so
    it is a button rather than something that happens on arrival: a Claude
    run behind a tab that refreshes on every visit is the "refresh
    everything" control this panel deleted, with a nicer name.

    It skips the usage budget and not the credential — `_ask_why`'s split,
    which is one promise with two halves: automatic runs pause, and asking
    by hand always runs.
    """
    if not await asyncio.to_thread(engine.get_auth):
        raise web.HTTPConflict(
            text="brAIn is not signed in, so there is nothing to ask.")
    start, end = _activity_window(request)
    key = (int(start // 60), int(end // 60))
    cached = _ACTIVITY_SUMMARIES.get(key)
    if cached:
        return web.json_response({**cached, "cached": True})
    unreadable = ("Home Assistant's logbook could not be read, so there is "
                  "nothing to summarise.")
    try:
        mined = await _activity(start, end)
    except Exception as exc:  # noqa: BLE001
        # The exception's own text goes to the LOG and not into the reply.
        # A fetch that raised and a logbook that answered `available: false`
        # are the same thing from out here — which is why they share a
        # sentence — and the half a person could act on is the same either
        # way, where the half they could not is a stack trace in a panel.
        log.warning("activity summary: the logbook could not be read: %s", exc)
        raise web.HTTPBadGateway(text=unreadable) from exc
    if not mined.get("available"):
        raise web.HTTPBadGateway(text=unreadable)
    classes = await _device_classes()
    now = time.time()

    def build() -> tuple[dict, str]:
        grouped = episodes.group(mined["actions"], classes, now)
        episodes.mark_overrides(grouped, mined.get("overrides") or [])
        payload = {
            "start": mined["start"], "end": mined["end"],
            "sections": episodes.sections(grouped),
            "away": episodes.away_spans(grouped, now),
            "dropped": grouped["dropped"],
        }
        # The house's own zone, named rather than assumed: every clock in
        # the prompt is this process's local time, and a run told which
        # zone it is reading cannot place an evening in somebody's morning.
        _tz, tz_name = baselines.house_timezone()
        return payload, episodes.summary_prompt(payload, tz_name)

    payload, prompt = await asyncio.to_thread(build)
    if not payload["sections"]:
        raise web.HTTPConflict(
            text="Nothing happened in this window, so there is nothing to "
                 "say about it.")
    result = await _claude(
        engine.run_analyst, prompt, episodes.SUMMARY_SYSTEM, eff_model(),
        episodes.SUMMARY_TIMEOUT_S, episodes.SUMMARY_MAX_TURNS, "activity",
        job="episode_summary", priority=run_queue.PRESS)
    text = str(result.get("text") or "").strip()
    if not result.get("ok"):
        raise web.HTTPBadGateway(
            text=str(result.get("error") or "the run did not finish")[:200])
    if len(text) < episodes.SUMMARY_MIN_CHARS:
        # `brief.py`'s floor: a four-word summary is worse than the silence
        # it replaced, and reporting one as an answer teaches somebody the
        # button does nothing.
        raise web.HTTPBadGateway(
            text="The reply was too short to be an answer. Try again.")
    answer = {"summary": text, "start": mined["start"], "end": mined["end"],
              "run_id": str((result.get("meta") or {}).get("session_id") or ""),
              "cached": False}
    _ACTIVITY_SUMMARIES[key] = answer
    while len(_ACTIVITY_SUMMARIES) > _ACTIVITY_SUMMARY_MAX:
        _ACTIVITY_SUMMARIES.pop(next(iter(_ACTIVITY_SUMMARIES)))
    return web.json_response(answer)


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
    """`claude --version`, probed once per process.

    Through `engine.resolve_claude_bin()`, never the bare name. The panel
    runs as root and the CLI is installed under the `claude` user's home
    with a symlink into `/root/.local/bin` — neither is on root's default
    PATH, so `["claude", "--version"]` resolves to nothing and this
    reported `unknown` on installs where Claude was working perfectly.
    That is the same "where does the CLI live" question `_claude_argv`
    answers, and two answers to it is one too many — which is exactly how
    it drifted: the resolver was written for the exec path and this probe
    kept the guess it had.

    `unknown` in a bundle is a fact nobody can supply afterwards, and it
    is the first line of every bug report about a CLI-version-dependent
    failure.
    """
    if _CLI_VERSION["value"] is None:
        try:
            out = subprocess.run([engine.resolve_claude_bin(), "--version"],
                                 capture_output=True, text=True, timeout=15)
            _CLI_VERSION["value"] = (out.stdout or out.stderr or "").strip().splitlines()[0][:80] \
                if (out.stdout or out.stderr) else "unknown"
        except (OSError, subprocess.SubprocessError, IndexError):
            _CLI_VERSION["value"] = "unknown"
    return _CLI_VERSION["value"]


_OPTION_SECRET_WORDS = ("token", "password", "secret", "api_key", "credential")


def _facts_summary_safe() -> dict:
    """The facts store's own summary, or a row saying it could not be
    read — `reports.faults`' rule: a payload it cannot read is a row."""
    try:
        return facts_store.summary()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


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
            # How long the oldest row still waiting for a look has waited.
            # `by_status` already carries the count and a count is not the
            # question: three rows waiting is a drain a minute from now,
            # and three rows that have waited since Tuesday is a drain that
            # stopped. Past `triage.STALE_S` the next drain shows them and
            # says nothing looked, so a number above it is the window
            # between the two.
            "triage_oldest_wait_s": max(
                [int(time.time() - f["ts"]) for f in rows
                 if f["status"] == "triaging"] or [0]),
            "triage_runs_today": _triage_runs_today(time.time()),
            "triage_runs_per_day": triage.MAX_PER_DAY,
            "scorecard": findings_store.scorecard(),
            # Which producers the homeowner has switched off. A quiet check
            # and a muted one look identical from the list, and only one
            # of them is a fault worth reading the log about.
            "muted": [m["source"] for m in _muted_rows()],
        },
        "memory": {
            "document_bytes": memory_bytes,
            "hypotheses_open": len(hypotheses.list_all("open")),
            "facts": _facts_summary_safe(),
        },
        "checks": CHECKS_STATE["last"],
        # The last deep run's verdict — three facts, never the transcript.
        # A bug report needs to know whether every face was walked, when,
        # and which one broke; the stage list is a page of prose and
        # belongs on the screen that asked for it.
        "doctor_deep": doctor.summary(),
        # And the other costed check: what the checks and the model
        # scored against defects whose ground truth is known by
        # construction. The one number in this payload that is
        # about the PROMPT rather than about the house.
        "rehearsal": rehearsal.summary(),
        # Numbers, not the buckets: a bug report needs to know whether the
        # house has been measured and when, not a month of hourly medians
        # for four hundred sensors.
        "baselines": {
            "built_at": _baseline_store.get("built_at", 0),
            "measured": len(_baseline_store.get("entities") or {}),
            "asked": _baseline_store.get("asked", 0),
            # What the nightly cap left out, and how many were never
            # candidates (no mean to bucket, or a settings-page sensor):
            # a sensor past the cap is one every reader is blind to.
            "eligible": _baseline_store.get(
                "eligible", _baseline_store.get("asked", 0)),
            "cut": _baseline_store.get("cut_count", 0),
            "cut_sample": list(_baseline_store.get("cut") or []),
            "skipped": dict(_baseline_store.get("skipped") or {}),
            "categories_read": _baseline_store.get("categories_read"),
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
        # Tidy, the upgrade advisor, the overnight health check, the house
        # book and the access review: run, held (and why), or failed.
        "maintainer": _maintainer_diagnostics(),
        # Answers given in the To-do app or on a notification, on
        # their way back to the one store that owns them.
        "finding_requests": _requests_diagnostics(),
        # What you do by hand, and what has been offered because of it.
        # An empty Proposals tab reads the same whether the miner found
        # no habit or the ledger has been empty for a month.
        "routines": _routines_diagnostics(),
        # And why. The queue is the whole point of this one being here:
        # a feature that asks one question a day is silent nearly all the
        # time, and "nothing to be curious about", "asked already this
        # morning" and "the loop died in March" are three silences that
        # look identical from every other surface.
        "curiosity": _curiosity_diagnostics(),
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
            # Why that sensor, and whether a person chose it: every room's
            # model is measured against it, and a reference nobody can
            # check is one nobody can correct.
            "outdoor_source": _thermal_store.get("outdoor_source", ""),
            "outdoor_why": _thermal_store.get("outdoor_why", ""),
            "coldest": _thermal_store.get("coldest"),
            "reason": _thermal_store.get("reason", ""),
        },
        # How many conversations the chat is holding open, how many are
        # answering, and what the cap is. A session the cap stopped and one
        # that crashed leave the same silence otherwise.
        "chat": chat_session.registry().summary(),
        # Whether the analyst's prompts are being sampled, how many runs
        # are on disk, and how many of those an ending has labelled.
        # Numbers only — the captures themselves are never bundled: this
        # payload is what gets attached to a public issue.
        "capture": capture.stats(bool(settings.get("capture"))),
        # Checks that run and are not on the tab, and how much of what
        # they said something else said too. No automatic promotion — this
        # is the number a person reads before moving an id out of
        # `checks.SHADOW`, which is a code change.
        "shadow_checks": shadow_findings.diagnostics(),
        # The attention loop: what is queued, what is waiting, what the
        # day has cost, and what it is watching. Three silences look
        # identical from every other surface — a house with nothing
        # happening, a queue that stopped draining, and a loop holding
        # everything because a gate said no — and each has its own number
        # here.
        "resident": _resident_diagnostics(),
        # What the Resident decided, graded against what the household did
        # next: a log nothing writes and a join that stopped running read
        # identically from every other screen.
        "outcomes": _outcomes_diagnostics(),
        # And the subscription under it. A socket that never connected, one
        # that is reading nothing because the house is quiet, and one that
        # is dropping everything because something is flooding it are three
        # different faults that look the same from outside.
        "eventbus": (EVENT_BUS.stats() if EVENT_BUS else
                     {"connected": False,
                      "idle_reason": "the event bus has not been started"}),
        # What brAIn understands about the house: the entity readings, the
        # situation and what is coming up. Each can stop quietly — a read
        # held by a gate, a frame nobody rebuilt, a calendar that would
        # not answer — and each says which here.
        "understanding": _understanding_diagnostics(),
        "daemons": _daemon_rollcall(),
        # The panel's own loops — the generation worker, the scheduler, the
        # checks — alive or not, and when each last went round. A dead
        # worker is cards and fixes queued for ever with every other
        # surface saying "queued", which `health.problems` now names.
        "loops": _loop_health(),
        # Every Claude run the server starts takes a seat here; who holds
        # one and who waits is what tells "brAIn is busy" from "stuck".
        "claude_runs": run_queue.stats(),
        "usage": {
            **{k: usage.get(k) for k in ("source", "used_percent", "limits")},
            # When a finished run last told the tracker to ask. The
            # heartbeat is slow on purpose, so "the figure is 40 minutes
            # old" and "nothing has run since Tuesday" are different
            # reports of the same stale number, and only one of them is
            # something to look into.
            "nudged_at": int(usage_store.nudged_at()) or None,
        },
    }
    # Derived last, from everything above it. The verdict is part of the
    # payload rather than a route of its own so that the panel, the mirror,
    # the integration's sensor and `brain report` cannot disagree about
    # whether brAIn is working — which is exactly the kind of drift a second
    # copy of a rule produces.
    payload["health"] = health.verdict(payload, safe_options)
    # And the flat sweep, derived last for the same reason and from the
    # same payload the report reads — so ⚙ → Diagnostics, the mirror,
    # Home Assistant's Download-diagnostics button and `brain report` all
    # answer "what is wrong with this install" with one list. `health` is
    # the VERDICT (a state and a sentence, and deliberately only the worst
    # thing); this is the inventory, and the two are different questions:
    # a check that could not look, a rehearsal that left something behind
    # and a producer the homeowner keeps marking Wrong are all faults and
    # none of them is brAIn failing to work.
    payload["faults"] = reports.faults(payload)
    return payload


def publish_diagnostics() -> None:
    """Write the payload to the shared volume, and notice the verdict moving.

    The mirror is skipped on a dev checkout (no /config), logged and
    swallowed otherwise: it is derived. The health comparison rides here
    because this is the one place the verdict is computed on a schedule —
    the panel kept no previous verdict anywhere, so `ok` on Monday and
    `degraded` on Tuesday were two files nobody diffed. `reports.note_health`
    keeps the last state in /data and files one problem report when it
    leaves `ok`; a dev checkout with no /data skips that too.
    """
    DIAG_STATE["published_at"] = time.time()
    mirror = DIAGNOSTICS_FILE.parent.parent.exists()
    if not mirror and not reports.tracks_health():
        return
    try:
        payload = _diagnostics_payload()
    except Exception as exc:  # noqa: BLE001
        log.debug("diagnostics payload failed: %s", exc)
        return
    reports.note_health(payload.get("health") or {}, payload)
    if not mirror:
        return
    try:
        DIAGNOSTICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(DIAGNOSTICS_FILE, payload)
    except Exception as exc:  # noqa: BLE001
        log.debug("diagnostics mirror write failed: %s", exc)


async def h_diagnostics(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_diagnostics_payload))


# ---------------------------------------------------------------------------
# Problem reports — the ⚙ dialog's Problems section and `brain report`
# ---------------------------------------------------------------------------

async def h_reports_list(request: web.Request) -> web.Response:
    rows = await asyncio.to_thread(reports.list_reports)
    return web.json_response({
        "reports": rows,
        "dir": str(reports.REPORTS_DIR),
        "available": reports.available(),
        "max": reports.MAX_REPORTS,
    })


async def h_report_get(request: web.Request) -> web.Response:
    text = await asyncio.to_thread(reports.read_report, request.match_info["name"])
    if text is None:
        return web.json_response({"error": "no such report"}, status=404)
    return web.Response(text=text, content_type="text/plain", charset="utf-8")


async def h_report_delete(request: web.Request) -> web.Response:
    ok = await asyncio.to_thread(reports.delete_report, request.match_info["name"])
    if not ok:
        return web.json_response({"error": "no such report"}, status=404)
    return web.json_response({"deleted": True})


async def h_reports_copy(request: web.Request) -> web.Response:
    """Several reports as one text, separated, for one paste."""
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.json_response({"error": "invalid JSON"}, status=400)
    names = (body or {}).get("names") if isinstance(body, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return web.json_response({"error": "names must be a list of file names"},
                                 status=400)
    text = await asyncio.to_thread(reports.combined, names[:reports.MAX_REPORTS])
    return web.Response(text=text, content_type="text/plain", charset="utf-8")


async def h_reports_run(request: web.Request) -> web.Response:
    """Write one report now — the manual kind, carrying the FULL diagnostics
    payload rather than the abridged subset a failure files. `brain report`
    and ⚙'s "Copy for a bug report" both come through here, so there is one
    shape of file whoever asked."""
    if not reports.available():
        return web.json_response(
            {"error": f"{reports.REPORTS_DIR} is not available — /share is not "
                      "mapped, so there is nowhere Home Assistant can see to "
                      "write a report"}, status=503)

    def run() -> str | None:
        payload = _diagnostics_payload()
        full = json.dumps(payload, indent=1, ensure_ascii=False, default=str)
        return reports.file_incident(
            "manual", "report requested",
            "Somebody asked for a report — from ⚙ → Problems, or `brain report`. "
            "Nothing failed to produce this file.",
            "Read it before attaching it to an issue: entity and area names "
            "are in it, credentials are not.",
            diagnostics=payload, dedup=False,
            extra_text="--- diagnostics (full) ---\n" + full)

    name = await asyncio.to_thread(run)
    if not name:
        return web.json_response({"error": "the report could not be written; "
                                           "the add-on log says why"}, status=500)
    return web.json_response({"name": name, "path": str(reports.REPORTS_DIR / name)})


# ---------------------------------------------------------------------------
# Captured runs — reviewable before anything leaves the add-on
# ---------------------------------------------------------------------------

async def h_capture_list(request: web.Request) -> web.Response:
    """One row per captured run: when, what, how many findings, how many
    endings have labelled them."""
    settings = await asyncio.to_thread(settings_store.load)
    return web.json_response({
        "enabled": bool(settings.get("capture")),
        "captures": await asyncio.to_thread(capture.listing),
        "max_files": capture.CAPTURE_MAX_FILES,
        "export_dir": str(capture.EXPORT_DIR),
    })


async def h_capture_get(request: web.Request) -> web.Response:
    """One whole capture, as it is on disk. Already redacted — the file is
    written that way, so there is no unredacted copy for this to leak."""
    entry = await asyncio.to_thread(capture.read, request.match_info["run_id"])
    if entry is None:
        return web.json_response({"error": "no such capture"}, status=404)
    return web.json_response(entry)


async def h_capture_export(request: web.Request) -> web.Response:
    """Copy one capture to /share, which is the one route out of the add-on.

    Deliberately a press rather than anything automatic: everything above
    this line keeps the file in /data, where Home Assistant cannot see it
    and a backup does not carry it.
    """
    path, error = await asyncio.to_thread(
        capture.export, request.match_info["run_id"])
    if error:
        return web.json_response(
            {"error": error},
            status=404 if "no capture" in error else 500)
    log.info("exported capture %s to %s", log_safe(request.match_info["run_id"]), path)
    return web.json_response({"ok": True, "path": path})


async def h_capture_delete(request: web.Request) -> web.Response:
    gone = await asyncio.to_thread(capture.delete, request.match_info["run_id"])
    if not gone:
        return web.json_response({"error": "no such capture"}, status=404)
    return web.json_response({"ok": True})


# ---------------------------------------------------------------------------
# Cases — one feed, three endings
# ---------------------------------------------------------------------------
#
# `cases.py` is a READ MODEL over the four stores that already exist, and
# nothing below writes a fifth. What the routes here add is the two things
# a read model cannot have: the endings, which are the server's and are
# the same six doors the four tabs already used, and the Resident's own
# numbers, which are what the feed's foot line says.
#
# **`cases.end` is synchronous and four of the six endings are not.**
# `cases.py` has to be drivable in a test with no event loop — that is the
# whole reason it holds no `async` — while `_end_finding` and its siblings
# queue a memory fact and label a capture off the loop. So a hook ANSWERS
# with the work rather than doing it: it hands back a zero-argument
# callable, `cases.end` fires exactly one of them per press as it always
# did, and the route awaits what came back. A thunk rather than a bare
# coroutine, because a refusal anywhere on the path would otherwise leave
# one un-awaited and Python would report it against the wrong line.


def _case_end_finding(key, word: str, note: str):
    """`wrong` or `ack` on a finding — the Findings tab's own ending."""
    spec = FINDING_VERBS[word]

    async def run() -> dict:
        finding = await asyncio.to_thread(findings_store.get, int(key))
        if finding is None:
            return {"error": "no such finding"}
        payload, fact = await _end_finding(finding, spec, note)
        payload["undo"] = _ending_undo(finding, spec, fact, payload)
        return payload
    return run


def _case_finding_todo(key):
    """*Do it* on a problem: onto the to-do list, and no memory line.

    The claim *Do it* deliberately does not make is "this is fixed" —
    pressing it is agreeing the report is real, and the fact is written
    when the chore is ticked off, which is when it becomes true. See
    `cases.py`'s own docstring; this is just the door.
    """
    async def run() -> dict:
        finding = await asyncio.to_thread(findings_store.get, int(key))
        if finding is None:
            return {"error": "no such finding"}
        return await _move_finding_to_todo(finding)
    return run


def _case_hypothesis(key, word: str, note: str):
    """Yes or no to a guess."""
    async def run() -> dict:
        payload = await _answer_hypothesis(int(key), word, note)
        return payload if payload is not None else {
            "error": "that guess has already been answered"}
    return run


def _case_proposal(key, word: str, note: str):
    """Accept or decline a suggestion — write, reload, verify, settle."""
    async def run() -> dict:
        payload, status = await _decide_proposal(int(key), word, note)
        return payload if status == 200 else {**payload, "status": status}
    return run


def _case_todo_done(key):
    """A chore ticked off, which is the moment the memory line is written."""
    async def run() -> dict:
        item = await asyncio.to_thread(todo_store.get, int(key))
        if item is None:
            return {"error": "no such item"}
        payload = await _finish_todo(item)
        return payload if payload is not None else {"error": "no such item"}
    return run


def _case_todo_drop(key):
    """A chore taken off the list undone, which releases the suppression."""
    async def run() -> dict:
        item = await asyncio.to_thread(todo_store.get, int(key))
        if item is None:
            return {"error": "no such item"}
        payload = await _drop_todo(item)
        return payload if payload is not None else {"error": "no such item"}
    return run


CASE_HOOKS = cases.Hooks(
    end_finding=_case_end_finding,
    finding_todo=_case_finding_todo,
    hypothesis=_case_hypothesis,
    proposal=_case_proposal,
    todo_done=_case_todo_done,
    todo_drop=_case_todo_drop,
)


def _cases_payload(now: float | None = None) -> dict:
    """The feed, and the line under it.

    `overflow` rides on each case rather than being derived in the panel:
    a hypothesis is a different store from a finding and the routes differ
    with it, so a second table of those in `app.js` would be a second thing
    to keep in step — `cases.overflow`'s own reason for handing back a
    route rather than a verb.
    """
    now = time.time() if now is None else now
    rows = [c for c in cases.list_cases(now=now) if cases.on_feed(c)]
    names: dict[str, dict] = {}
    for case in rows:
        # The presses, decided once (`answers.py`) and rendered as handed:
        # `answers` is the visible row, `more` what sits behind the ⋯, and
        # `overflow` is kept whole for a caller that wants every verb.
        case["overflow"] = cases.overflow(case)
        case["answers"] = cases.answers(case)
        case["more"] = cases.more(case)
        case["situation"] = cases.situation(case)
        # Pretty names: the entity the card is about, and every id the
        # prose mentions, so the panel can render words a person reads
        # rather than ids they translate. Only ids the last snapshot saw
        # — an id nothing knows stays an id, which is honest.
        row = _NAMES.get(case.get("entity_id") or "")
        case["entity_name"] = (row or {}).get("name") or ""
        case["area"] = (row or {}).get("area") or ""
        names.update(_entity_names_in(
            case.get("claim"), case.get("detail"), case.get("fix"),
            *(ev.get("entity") or "" for ev in case.get("evidence") or []),
            *(a.get("label") or "" for a in case.get("actions") or [])))
        if row:
            names[case["entity_id"]] = row
    return {
        "cases": rows,
        "names": names,
        "open": cases.open_count(now),
        "ledger": LEDGER.summary(now),
        "resident": _resident_diagnostics(),
        "eventbus": EVENT_BUS.stats() if EVENT_BUS else {
            "connected": False,
            "idle_reason": "the event bus has not been started"},
        "watching": len(resident.watched()),
    }


async def h_cases(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_cases_payload))


async def h_case_verb(request: web.Request) -> web.Response:
    """One of the three endings, on one case.

    404 for a case that is not there and 409 for one that cannot take this
    verb — which `cases.end` answers with the same None for, because from
    its side both are "this press changed nothing". The distinction is
    made here, once, by asking whether the case exists at all.
    """
    case_id = request.match_info["id"]
    verb = request.match_info["verb"]
    if verb not in cases.VERBS:
        raise web.HTTPNotFound(text="no such ending")
    body = await _json_body(request)
    note = str(body.get("note") or "").strip()[:findings_store.MAX_NOTE]
    now = time.time()

    case = await asyncio.to_thread(cases.get, case_id, now)
    if case is None:
        raise web.HTTPNotFound(text="no such case")
    ended = await asyncio.to_thread(
        cases.end, case_id, verb, note, hooks=CASE_HOOKS, now=now)
    if ended is None:
        raise web.HTTPConflict(
            text=f"a {case['kind']} case in {case['status']} cannot be "
                 f"answered with {verb}")

    work = ended.pop("result", None)
    outcome = await work() if callable(work) else None
    if isinstance(outcome, dict) and outcome.get("error"):
        # The hook refused in its own words — a proposal Home Assistant
        # would not load, a row somebody answered from a phone a second
        # ago. Said as it was said rather than flattened into a 404, which
        # is `cases.end`'s own note about `result`.
        raise web.HTTPConflict(text=str(outcome["error"]))
    # The answer carries every list the press moved, in one read: the
    # hook's own payload first (a finding ending answers with the findings
    # tab's list and the to-do counts, a proposal with the proposals), the
    # feed over it, the ending over that. The panel paints from what it
    # is handed, and a feed that arrived without the findings list it is
    # rendered beside left the row that had just been moved to be drawn
    # off the STALE list — as an old-style card with different buttons,
    # under the case that had just gone. Two lists, one press, one read.
    payload = {**(outcome if isinstance(outcome, dict) else {}),
               **await asyncio.to_thread(_cases_payload, now), **ended}
    # The token the finding routes already hand back, where the ending had
    # one. `not_now` has none on purpose: it took nothing away, and the
    # card says when it comes back.
    if isinstance(outcome, dict) and outcome.get("undo"):
        payload["undo"] = outcome["undo"]
    log.info("case %s: %s", log_safe(case_id), verb)
    return web.json_response(payload)


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
    # Awake only: a guess somebody dismissed is still open and is not
    # being asked. Listed here it came straight back onto the feed as a
    # loose card beside the case list that had correctly hidden it.
    open_claims = hypotheses.awake()
    payload["hypotheses"] = open_claims
    payload["open"] += len(open_claims)
    # How right each producer has been, from the endings people gave. It
    # rides this payload rather than its own route because it is read in
    # exactly one place — a line under the filter chips — and a number
    # about the list belongs with the list.
    payload["scorecard"] = findings_store.scorecard()
    # The producers the homeowner has muted, named. It rides here for the
    # scorecard's reason: the one place it is read is a line under the
    # filters, beside the scorecard rows that argue for each mute.
    payload["muted"] = _muted_rows()
    return payload


# What a muted producer was called when it was muted. The press clears
# the producer's rows, which is where a non-check producer's title lived,
# so it is remembered here at the moment it is still readable. In memory
# only: after a restart the card's category or the settled ledger usually
# still names it, and the id is the fallback for the rest.
MUTED_TITLES: dict[str, str] = {}


def _muted_rows() -> list[dict]:
    """Every muted producer with a title a person would recognise.

    In order: the check catalog's own title for a check ("Sensors frozen
    on one value", never its group's "Device check" — a mute is per rule,
    and three rows reading "Device check" are three things nobody can tell
    apart); the category's title for an insight category; the title the
    producer filed under, off a live row or the settled ledger; what it was
    called when it was muted; and the id itself when nothing knows better.
    """
    titles = findings_store.source_titles()
    out = []
    for source in settings_store.load().get("muted_sources") or []:
        title = ""
        if source.startswith("check:"):
            spec = checks.get_check(source[6:]) or {}
            title = str(spec.get("title") or "")
        else:
            cat = resolve_category(source) or {}
            title = str(cat.get("title") or "")
        out.append({"source": source,
                    "title": (title or titles.get(source)
                              or MUTED_TITLES.get(source) or source)})
    return out


async def h_findings(request: web.Request) -> web.Response:
    # The scheduler owns ingestion; sweeping here too is only about latency,
    # so opening the tab right after a study session finishes doesn't wait
    # out the tick. Both are idempotent, and an empty inbox costs one glob.
    def listing() -> tuple[list[dict], dict]:
        return findings_store.sweep_inbox(triage.gate), _findings_payload()

    swept, payload = await asyncio.to_thread(listing)
    # Nothing is announced and nothing is triaged here. A study session's
    # finding arrives gated like any other, and the drain on the
    # scheduler's own minute is what looks at it and tells the phone — a
    # Claude run behind a tab fetch is the "refresh everything" control
    # this panel deleted, with a nicer name. The sweep stays because it
    # is only about latency: the row is in the store the moment the tab
    # is opened rather than up to a minute later.
    if swept:
        log.info("swept %d finding(s) on a tab fetch", len(swept))
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
              "source": "correction",
              # What this ending means to anything counting them. `kind` is
              # what the settled ledger stores and two verbs share one, so
              # it cannot be the label: "I did it" and "Got it" are both
              # `fixed` and are different evidence about the report.
              "label": "wrong"},
    # "I already handled it myself" — the ending for anything needing hands,
    # and the one where what you did is worth more than that you did it. "I
    # fixed it" leaves brAIn knowing a problem is over; "replaced the CR2032,
    # it's a 3-monthly job on that sensor" leaves it knowing the house.
    "done": {"kind": "fixed",
             "memory": "Fixed by the homeowner on {date}: {text}",
             "noted": "Fixed by the homeowner on {date}: {text}. They said: "
                      "{note}",
             "source": "homeowner",
             "label": "done", "hint": True},
    # "I've read what brAIn changed" — the ending for an automated fix,
    # which already wrote its own memory line when it made the change.
    "ack": {"kind": "fixed", "memory": "", "label": "got_it"},
    # "Yes, that is real, and I will do it." The fourth ending, and the
    # only one that writes no memory line: "I will get to it" says nothing
    # true about the house — the battery is still flat — so the fact is
    # written when the chore is actually done and not when it is accepted.
    # The key is settled all the same, because a report you have agreed to
    # act on must not be raised at you again while it sits on your list.
    # `h_finding_todo` is what routes here; the spec is the ending half.
    "todo": {"kind": "accepted", "memory": "", "label": "accepted"},
    # "Yes" to a question the Resident filed as a finding. The case said
    # what it would teach if the homeowner agreed (`memory_hint`), and that
    # is the line filed — `hint` says to prefer it over the template, which
    # is the fallback for a case that offered none. Settled as `accepted`:
    # agreeing the guess was right is the report being confirmed.
    "confirm": {"kind": "accepted",
                "memory": "Confirmed by the homeowner: {text}",
                "noted": "Confirmed by the homeowner: {text}. They added: "
                         "{note}",
                "source": "homeowner", "label": "accepted", "hint": True},
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
    payload["undo"] = _ending_undo(finding, spec, fact, payload)
    # "Wrong — and stop raising these." The box on the Wrong form, for the
    # row that is the fourth of its kind: the ending above is about this
    # row, and the mute is about the rule that filed it. Only Wrong offers
    # it, because agreeing a report was real is no argument against the
    # producer. The rows it takes with it are counted, not undone: the
    # undo token above puts back THIS row, and the mute is one press on
    # the Findings tab to reverse.
    if verb in ("wrong", "ignore") and (body or {}).get("mute") is True \
            and finding.get("source") \
            and finding["source"] not in cases.UNMUTABLE_SOURCES:
        taken = await asyncio.to_thread(_mute_source, finding["source"])
        payload.update(await asyncio.to_thread(_findings_payload))
        payload["muted"] = _muted_rows()
        payload["also_cleared"] = len(taken)
        log.info("muted %s from a Wrong press (%d more row(s) taken off)",
                 finding["source"], len(taken))
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
    # And the label, on the capture of the run that raised it. This is the
    # one door every ending comes through — the tab's buttons, a tick in
    # the To-do app, a button on a notification — so hooking it here is
    # what makes "the ending is the label" true of the ANSWER rather than
    # of the surface it was given on. Best effort in every direction: a
    # capture that was never written, or has been pruned, simply has
    # nothing to label, and an ending must never fail because of one.
    if finding.get("run_id") and spec.get("label"):
        await asyncio.to_thread(
            capture.add_label, finding["run_id"],
            finding_key=findings_store.normalize(finding["text"]),
            verb=spec["label"], note=note)
    # A note only changes the sentence for endings that have a second one to
    # offer. "Got it" plus a comment is still "Got it": falling back to
    # `memory` is what stops a note silently costing the memory line.
    template = spec["noted"] if note and spec.get("noted") else spec["memory"]
    fact = ""
    subjects = _finding_subjects(finding)
    # An investigation's case says what it would teach if a person agreed
    # (`memory_hint`) — asked for, paid for and stored, and until now read
    # by nothing. On an ending that agrees, it is the line: a durable fact
    # about the house in the run's words, rather than the template's
    # "Fixed by the homeowner: <the card's title>".
    hint = str(finding.get("memory_hint") or "").strip()
    if spec.get("hint") and hint:
        fact = hint + (f" (The homeowner added: {note})" if note else "")
        await _submit_memory(
            fact, source=spec.get("source", "homeowner"),
            subject=subjects[0] if subjects else "", subjects=subjects[1:],
            run_id=str(finding.get("run_id") or ""))
    elif template:
        fact = template.format(text=finding["text"], note=note,
                               date=time.strftime("%Y-%m-%d"))
        # Filed under what the finding is about, and with the run that
        # raised it. A correction tagged by scanning its sentence lands on
        # the whole house — the report is written in friendly names — and
        # the next look at that very sensor is the run least likely to be
        # shown a house-wide fact (`_finding_subjects`).
        await _submit_memory(
            fact, source=spec.get("source", "homeowner"),
            subject=subjects[0] if subjects else "", subjects=subjects[1:],
            run_id=str(finding.get("run_id") or ""))
    # And the rule it corrects. Wrong on a check's row is the homeowner
    # saying this rule has this entity wrong — the sensor is not stuck, it
    # is a contact on a cupboard nobody opens — and until 2.2 that landed
    # in the settled ledger as one WORDING, so the next pass made the same
    # mistake in new words. The exception is keyed on the check id and the
    # entity, and the check reads it before filing (`House.excepted`). The
    # note is the fact's text where there is one, because it is the
    # sentence a person will want to read back beside the rule it muted.
    if spec.get("kind") == "ignored":
        written = await asyncio.to_thread(_record_exception, finding, note)
        if written:
            # Private to the press that made it: the route turns it into
            # the undo token and takes it off the payload (`_ending_undo`).
            payload["_exception_ids"] = written
    return payload, fact


def _ending_undo(finding: dict, spec: dict, fact: str, payload: dict) -> str:
    """The undo token for an ending, carrying every effect it had.

    The rule a Wrong press wrote is one of those effects, and the toast's
    Undo promises to put back all of them — "half of any of them is worse
    than none". A mis-tapped Wrong followed by Undo used to restore the row
    and leave the check muted for that entity until somebody found the
    rule on the Knowledge tab.
    """
    ids = payload.pop("_exception_ids", None) or []
    return undo_store.record(
        "finding", finding=finding,
        key=findings_store.normalize(finding["text"]),
        fact=fact, fact_source=spec.get("source", "homeowner"),
        exception=list(ids))


# Which producers' Wrong becomes a rule, and under what name. A check names
# itself; the Resident is one producer whose judgements are all its own,
# so its rule is `exception:resident` on the entities the case was about —
# what a later look at those entities is shown as "already dismissed here"
# (the reason it is retrievable by subject at all). An analyst card's row
# writes none: it names an entity it noticed on the way past rather than
# one it was asked about, and a rule on the wrong entity is worse than none.
def _exception_rule(finding: dict) -> tuple[str, list[str]]:
    source = str(finding.get("source") or "")
    if source.startswith("check:"):
        entity_id = str(finding.get("entity_id") or "")
        return (source[len("check:"):], [entity_id] if entity_id else [])
    if source == findings_store.RESIDENT_SOURCE:
        return "resident", _finding_subjects(finding)
    return "", []


def _record_exception(finding: dict, note: str) -> list[str]:
    """Best effort, `file_incident`'s rule: an ending must not fail on it.

    Returns the ids of the facts it wrote, which the undo token carries.
    """
    rule, subjects = _exception_rule(finding)
    if not rule or not subjects:
        return []
    report = str(finding.get("claim") or finding.get("text") or "")
    text = note.strip() if note else f'"{report}" was reported and marked wrong'
    try:
        row, _created = facts_store.add(
            text, subject=subjects[0], extra_subjects=subjects[1:],
            source="correction",
            predicate=facts_store.EXCEPTION_PREFIX + rule,
            run_id=str(finding.get("run_id") or ""), confidence=0.95,
            about=report,
            finding_key=findings_store.normalize(finding.get("text") or ""))
    except Exception as exc:  # noqa: BLE001
        log.debug("could not record the exception for %s: %s",
                  log_safe(subjects[0]), exc)
        return []
    return [row["id"]] if row else []


# ---------------------------------------------------------------------------
# The to-do list — work you have accepted, and the card it came from
# ---------------------------------------------------------------------------
#
# Every ending a finding had was a decision made on the spot. The one thing
# people actually say most often — *yes, that is real, I will do it* — had
# nowhere to go, so a battery that needed replacing stayed on the Findings
# tab as an open question until somebody got round to it, and a list of
# decisions waiting on you filled up with chores instead.
#
# Moving one here is that ending. Three things happen and they are the same
# three every ending does, with one deliberately missing:
#
#   * the row is deleted     — it is not a decision any more
#   * the key is settled     — as `accepted`, so nothing re-raises it while
#                              it sits on your list
#   * the fact is NOT written — because none is true yet. `done` on this
#                              tab writes the line `done` on the Findings
#                              tab would have, at the moment it becomes true
#
# and a fourth that only this ending does: the card's evidence is copied
# onto an item, because the row it came from is about to stop existing.


def _todo_payload() -> dict:
    """What the To-do tab reads, and the only thing it reads."""
    return todo_store.listing()


async def h_todo(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_todo_payload))


async def h_todo_add(request: web.Request) -> web.Response:
    """Put something on the list by hand.

    A list that only holds what brAIn noticed is not a list of what needs
    doing — it is a queue of brAIn's opinions — so this takes a plain
    sentence and nothing else is required. It settles no key and carries
    none, which is what `origin` records: there is no report behind it to
    suppress, and dropping it later releases nothing.
    """
    body = await _json_body(request)
    text = str((body or {}).get("text") or "").strip()
    if not text:
        raise web.HTTPBadRequest(text="what needs doing?")
    detail = str((body or {}).get("detail") or "").strip()
    severity = str((body or {}).get("severity") or "warning")
    if severity not in todo_store.SEVERITIES:
        severity = "warning"

    def write() -> tuple[dict | None, dict]:
        item = todo_store.add(text, detail=detail, severity=severity,
                              origin="hand")
        return item, _todo_payload()

    item, payload = await asyncio.to_thread(write)
    if item is None:
        raise web.HTTPConflict(
            text=f"the list is full — {todo_store.MAX_OPEN} is the cap, and "
                 "making room would mean dropping something you put there")
    payload["added"] = item
    return web.json_response(payload)


def _todo_or_404(request: web.Request) -> dict:
    try:
        item_id = int(request.match_info["id"])
    except (TypeError, ValueError):
        raise web.HTTPNotFound(text="no such item") from None
    item = todo_store.get(item_id)
    if item is None:
        raise web.HTTPNotFound(text="no such item")
    return item


async def h_finding_todo(request: web.Request) -> web.Response:
    """Accept a finding as work: off the list, onto the list.

    A separate handler rather than a row in the generic verb table because
    it does one thing the table cannot express — it has to create the item
    BEFORE the row is deleted, since the row is where the evidence is. If
    the item cannot be created nothing is settled and nothing is deleted,
    because a finding that vanished into a list that refused it is the one
    outcome with no way back.
    """
    finding = _finding_or_404(request)
    body = await _json_body(request)
    note = str((body or {}).get("note") or "").strip()[:findings_store.MAX_NOTE]
    # The step, if the caller has a better one than the producer's. A
    # resolution pressed in the chat does: "replace the CR2032 behind the
    # garage sensor" is what the conversation worked out, where `fix` is
    # whatever the check could say without looking. The item still carries
    # the finding's own text, because that is what the chore is ABOUT.
    fix = str((body or {}).get("fix") or "").strip()[:findings_store.MAX_NOTE]
    return web.json_response(await _move_finding_to_todo(finding, note, fix))


async def _move_finding_to_todo(finding: dict, note: str = "",
                                fix: str = "") -> dict:
    """Accept a finding as work, wherever the press came from.

    `_end_finding`'s rule one ending over: the tab's ＋ To-do and a case's
    *Do it* on a problem are the same three things — the item created, the
    row deleted, the key settled as `accepted` — and a second copy would be
    the same press teaching brAIn two different things depending on which
    screen it was given on.
    """
    key = findings_store.normalize(finding["text"])

    def place() -> dict | None:
        return todo_store.add(
            finding["text"],
            detail=finding.get("detail") or "",
            fix=fix or finding.get("fix") or "",
            entity_id=finding.get("entity_id") or "",
            severity=finding.get("severity") or "warning",
            origin="finding",
            source=finding.get("source") or "",
            source_title=finding.get("source_title") or "",
            finding_key=key,
            run_id=finding.get("run_id") or "")

    item = await asyncio.to_thread(place)
    if item is None:
        raise web.HTTPConflict(
            text=f"the to-do list is full — {todo_store.MAX_OPEN} is the cap. "
                 "The finding is untouched.")

    payload, _fact = await _end_finding(finding, FINDING_VERBS["todo"], note)
    payload["todo"] = todo_store.counts()
    payload["added"] = item
    # One token reverses both halves, because half of this undone is worse
    # than none of it: the row back with the item still there is the same
    # chore twice, and the item gone with the row still settled is work
    # that has silently disappeared.
    payload["undo"] = undo_store.record(
        "finding_todo", finding=finding, key=key, item=item, fact="",
        fact_source="homeowner")
    return payload


async def h_todo_done(request: web.Request) -> web.Response:
    """Tick one off — and write the fact the move deliberately did not.

    This is the moment it becomes true, so this is the moment memory hears
    about it, in exactly the sentence the Findings tab's own "I fixed it"
    would have written. The ledger entry is upgraded from `accepted` to
    `fixed` in place, keyed on what the item stored rather than on a second
    derivation from a copy of the text.
    """
    item = _todo_or_404(request)
    body = await _json_body(request)
    note = str((body or {}).get("note") or "").strip()[:todo_store.MAX_NOTE]
    payload = await _finish_todo(item, note)
    if payload is None:
        raise web.HTTPNotFound(text="no such item")
    return web.json_response(payload)


async def _finish_todo(item: dict, note: str = "") -> dict | None:
    """Tick a chore off and hand back the payload with its undo.

    `_complete_todo` is the three things "done" MEANS; this is the press
    around it, shared with a chore case's *Do it* so the tab's button and
    the feed's cannot hand back different answers.
    """
    done, fact = await _complete_todo(item, note)
    if done is None:
        return None
    payload = await asyncio.to_thread(_todo_payload)
    payload["undo"] = undo_store.record(
        "todo_done", item=item, fact=fact,
        fact_source=FINDING_VERBS["done"]["source"])
    return payload


async def _complete_todo(item: dict, note: str) -> tuple[dict | None, str]:
    """Finish a chore, wherever the press came from. One implementation.

    `_end_finding`'s rule, one store over: the tab's Done button and a tick
    in the To-do app both reach this, because "done" is three things — the
    item closed, the ledger entry upgraded from `accepted` to `fixed`, and
    the memory line the move deliberately did not write — and a second copy
    would be the same press teaching brAIn two different things depending
    on where it was made.
    """
    def finish() -> dict | None:
        closed = todo_store.complete(item["id"], note=note)
        if closed and item.get("finding_key"):
            findings_store.remember_answer(
                item["finding_key"], item["text"], "fixed", note=note,
                source=item.get("source", ""),
                source_title=item.get("source_title", ""))
        return closed

    done = await asyncio.to_thread(finish)
    if done is None:
        return None, ""

    # The same sentence "I fixed it" writes on the Findings tab, because it
    # is the same claim — said later, which is the only difference the to-do
    # list makes to it.
    spec = FINDING_VERBS["done"]
    template = spec["noted"] if note else spec["memory"]
    fact = template.format(text=item["text"], note=note,
                           date=time.strftime("%Y-%m-%d"))
    subjects = _finding_subjects(item)
    await _submit_memory(fact, source=spec["source"],
                         subject=subjects[0] if subjects else "",
                         run_id=str(item.get("run_id") or ""))
    if item.get("run_id"):
        await asyncio.to_thread(
            capture.add_label, item["run_id"],
            finding_key=item.get("finding_key") or "",
            verb=spec["label"], note=note)
    return done, fact


async def h_todo_reopen(request: web.Request) -> web.Response:
    """Put a finished chore back on the list.

    The one verb the Done filter carries, because a chore ticked off early
    is an ordinary mistake in a way a settled finding is not. What it does
    NOT do is take the memory line back: that was written when the thing
    was reported done, a consolidation may have filed it since, and editing
    the document is the only honest correction once it has — the same
    admission the undo token's five-minute life makes. The ledger goes back
    to `accepted`, because the work is waiting again.
    """
    item = _todo_or_404(request)

    def back() -> tuple[dict | None, dict]:
        restored = todo_store.reopen(item["id"])
        if restored and item.get("finding_key"):
            findings_store.remember_answer(
                item["finding_key"], item["text"], "accepted",
                source=item.get("source", ""),
                source_title=item.get("source_title", ""))
        return restored, _todo_payload()

    restored, payload = await asyncio.to_thread(back)
    if restored is None:
        raise web.HTTPNotFound(text="no such item")
    return web.json_response(payload)


async def h_todo_delete(request: web.Request) -> web.Response:
    """Take it off the list without doing it — and put the problem back.

    Deciding not to do something is not evidence it stopped being true, so
    a moved finding's key is released and the next checks pass is free to
    file it again. That is `clear_resolved`'s own argument: if it really is
    over, nothing comes back. A hand-added item carries no key and releases
    nothing, which is the whole of what `origin` is for.
    """
    item = _todo_or_404(request)
    payload = await _drop_todo(item)
    if payload is None:
        raise web.HTTPNotFound(text="no such item")
    return web.json_response(payload)


async def _drop_todo(item: dict) -> dict | None:
    """Take a chore off the list undone, wherever the press came from."""

    def drop() -> tuple[dict | None, bool, dict]:
        removed = todo_store.remove(item["id"])
        unsettled = False
        if removed and removed.get("finding_key"):
            unsettled = findings_store.unsettle(removed["finding_key"])
        return removed, unsettled, _todo_payload()

    removed, unsettled, payload = await asyncio.to_thread(drop)
    if removed is None:
        return None
    payload["unsettled"] = unsettled
    payload["undo"] = undo_store.record("todo_removed", item=removed)
    return payload


# ---------------------------------------------------------------------------
# Check again — the one check that filed this row, run now
# ---------------------------------------------------------------------------
#
# Every other ending on a finding is a person saying something about their
# house: it is fixed, it is normal here, come back tomorrow. This one says
# nothing at all — it asks the producer to look again, right now.
#
# It exists because a check reads one instant. A device unavailable while
# its hub rebooted, a reading implausible while a printer was hot, an
# add-on stopped mid-update: each is a true report of a moment that has
# since passed, and the row then sits there until somebody answers a
# question about a problem that is over. The scheduled pass would clear it
# — in up to `checks_interval_hours`, which is six by default, and on a
# list you are looking at now that may as well be never.
#
# Three rules, and all three are `clear_resolved`'s, because this is that
# same rule reached by a press rather than by a timer.
#
# **Only a check may be re-run.** A finding from the analyst came out of a
# Claude run over a whole category, and "run that again" is Regenerate on
# the card — it is not free, and it would not answer this question anyway.
# The button is absent on those rows rather than failing on them.
#
# **A check that could not look clears nothing.** A skipped or raising
# check is reported as such and the row is left exactly as it was: "I
# could not look" and "it went away" are different claims and only the
# second may take a row off the list.
#
# **The whole check clears, not the row.** `clear_resolved` is given this
# check's source and the keys it still reports, so a re-run that finds two
# of its three rows gone clears both. Clearing only the row that was
# pressed would leave the other two to be pressed individually about a
# thing the same look already proved is over.
async def h_finding_elevate(request: web.Request) -> web.Response:
    """Put a held finding on the list, because a person said to.

    The one press on the Looked-at filter, and it is `unsettle`'s: it
    stops the suppression and changes nothing else. What triage said is
    kept beside the row rather than erased — it is the only evidence that
    a verdict was wrong about this house, and a verdict nothing can
    correct is a verdict nobody should trust.

    A row that is not held is a 409 naming what it is instead, because
    "already on the list" and "somebody settled it while you were
    reading" are different things and only one of them is a surprise.
    """
    ts = _finding_ts(request)
    shaped = await asyncio.to_thread(findings_store.elevate, ts)
    if shaped is None:
        raise web.HTTPConflict(
            text="That one is not being held back any more — it is either "
                 "already on the list or it has been answered.")
    return web.json_response({
        "elevated": True, **(await asyncio.to_thread(_findings_payload))})


async def h_finding_recheck(request: web.Request) -> web.Response:
    finding = _finding_or_404(request)
    source = str(finding.get("source") or "")
    check_id = source[6:] if source.startswith("check:") else ""
    if not check_id or checks.get_check(check_id) is None:
        # Not a check's row, or a check this build no longer ships. Both
        # are "there is nothing here to re-run", and neither is an error
        # the person can do anything about.
        raise web.HTTPBadRequest(
            text="This one did not come from a house check, so there is "
                 "nothing to run again.")
    if CHECKS_STATE["running"]:
        raise web.HTTPConflict(
            text="A checks pass is already running — this row will be "
                 "brought up to date by it.")

    if checks.is_shadow(check_id):
        # The row predates the check being moved into the shadow set. It
        # is on the tab and this cannot honestly update it: a shadow
        # check files to a different store and reaches nobody, so running
        # it would answer about a row that is not this one.
        raise web.HTTPBadRequest(
            text="That check is being trialled and no longer files here.")

    started = time.time()
    snapshot = await checks.snapshot.collect(started)
    result = checks.run_all(snapshot, started, only=[check_id])
    if check_id not in result["ran"]:
        # The honest answer, and the one the row is left alone for. Both
        # halves are named: the snapshot key that was missing, or the
        # exception the rule raised.
        why = (result["skipped"].get(check_id)
               or result["errors"].get(check_id) or "it could not run")
        return web.json_response({
            "checked": False, "cleared": False, "why": why,
            **(await asyncio.to_thread(_findings_payload))})

    found = result["findings"]
    keys = {findings_store.normalize(f["text"]) for f in found}
    still = findings_store.normalize(finding.get("text", "")) in keys

    def apply() -> tuple[int, int, dict]:
        # New rows first, for the same reason the scheduled pass files
        # before it clears: a check looking again may find the problem has
        # moved rather than gone (the same hub, a different device), and
        # filing that in the same breath is what makes one press enough.
        created = findings_store.add_many(triage.gate(found))
        # The number in a detail is the half that is allowed to change —
        # the text is stable because the store dedupes on it — so a row
        # that is still there comes back with today's number rather than
        # the one it was filed with. Often that IS the answer.
        findings_store.refresh_details(found)
        # And the stamp that makes a "still there" answer survive the
        # toast. Without it the one outcome people actually get most of
        # the time — the problem is still there — left the card looking
        # exactly as it did before the press, which is what "it is an
        # invisible action" was.
        findings_store.mark_checked([f["text"] for f in found], started)
        cleared = findings_store.clear_resolved(
            {checks.source_for(check_id)}, keys)
        return len(created), len(cleared), _findings_payload()

    created, cleared, payload = await asyncio.to_thread(apply)
    return web.json_response({
        "checked": True, "cleared": not still, "created": created,
        # Everything else that check was reporting and no longer is. The
        # row pressed is not counted twice: it is already in `cleared`.
        "also_cleared": max(cleared - (0 if still else 1), 0),
        "why": "", **payload})


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


# How long a single registry read may take before the answer is "I could
# not look". A registry that will not answer must not hold a press open.
REGISTRY_LOOKUP_S = 10


async def _registry_entity_id(unique_id: str, platform: str = "automation"
                              ) -> tuple[str, bool]:
    """The entity id Core registered for this config id, and whether it
    could look at all: ``(entity_id, looked)``.

    An automation's registry entry is keyed on the `id` brAIn wrote into
    its config (Core makes that the `unique_id`), and that is the one
    question about it that is not a guess. The entity id is a CONSEQUENCE
    — `automation.<slug of the alias>` while that slug is free, `_2` when
    it is not, and Home Assistant transliterates where `slugify` here does
    not — so reading it back is the doctor helper's rule
    (`_ensure_helper`), applied to the automations brAIn writes.
    ``("", False)`` is "the registry would not answer", and the caller
    keeps its old behaviour rather than reading that as "not registered".
    """
    import aiohttp  # noqa: PLC0415
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    if not unique_id:
        return "", False
    try:
        async with aiohttp.ClientSession() as session:
            answer = await asyncio.wait_for(ha_data._ws_commands(
                session, [{"type": "config/entity_registry/list"}]),
                REGISTRY_LOOKUP_S)
    except Exception as exc:  # noqa: BLE001 — "I could not look"
        log.debug("entity registry unreadable: %s", exc)
        return "", False
    rows = answer[0] if answer else None
    if not isinstance(rows, list):
        return "", False
    for row in rows:
        if (isinstance(row, dict) and row.get("platform") == platform
                and str(row.get("unique_id") or "") == str(unique_id)):
            return str(row.get("entity_id") or ""), True
    return "", True


async def _wait_for_registration(unique_id: str) -> tuple[str, bool]:
    """`_registry_entity_id`, polled until it appears or the ceiling.

    A reload returns before Core has finished setting the automation up,
    which is why `_wait_for_entity` polls; the registry entry is written by
    the same setup. Stops asking the moment the registry will not answer,
    because a ceiling spent polling something that cannot be read is a
    press held open for nothing.
    """
    deadline = time.monotonic() + ACCEPT_VERIFY_S
    while True:
        eid, looked = await _registry_entity_id(unique_id)
        if eid or not looked:
            return eid, looked
        if time.monotonic() >= deadline:
            return "", True
        await asyncio.sleep(ACCEPT_POLL_S)


async def _drop_registry_entry(unique_id: str) -> str:
    """Delete the entity registry entry brAIn's own automation left. "" or why.

    Taking an automation out of the file leaves its registry entry, and
    Core re-publishes that as an `unavailable`, `restored: true` orphan —
    which kept the entity id, so the same sentence accepted again was
    registered as `_2` while verification passed on the orphan and the
    one-off's disarm switched the orphan off (`_registry_entity_id`).
    `dev.restored` then filed a finding about brAIn's own leftover. Found
    by the config id brAIn wrote, never by a guessed entity id: a guess is
    exactly the thing that could name somebody else's automation.
    """
    import aiohttp  # noqa: PLC0415
    import ha_data  # noqa: PLC0415

    eid, looked = await _registry_entity_id(unique_id)
    if not eid:
        return "" if looked else "the entity registry could not be read"
    try:
        async with aiohttp.ClientSession() as session:
            gone = await asyncio.wait_for(ha_data._ws_calls(
                session, [{"type": "config/entity_registry/remove",
                           "entity_id": eid}]), REGISTRY_LOOKUP_S)
    except Exception as exc:  # noqa: BLE001
        return f"{eid}'s registry entry could not be removed: {exc}"
    if not gone or not gone[0].get("ok"):
        return (f"{eid}'s registry entry could not be removed: "
                f"{(gone[0].get('error') if gone else '') or 'refused'}")
    return ""


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
    if not failure and target == "automations" and not row.get("edits"):
        # The entity id Core actually registered, read off the registry by
        # the config id brAIn wrote — before anything waits on a guessed
        # one. A guess passes on whatever already answers to that name: a
        # restored orphan of an earlier accept, or somebody's own
        # automation whose alias differs only in case. A registry that
        # will not answer leaves the guess, which is what this did before.
        real, looked = await _wait_for_registration(
            str(written.get("automation_id") or ""))
        if real:
            written["entity_id"] = real
            written["entity_ids"] = [real]
        elif looked:
            failure = ("it was written but Home Assistant never registered "
                       "it, so it is not running — check the add-on log and "
                       "Home Assistant's own")
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
        _report_async(reports.notify_failure, service, str(exc),
                      context="accepted-change announcement")


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
    body = await _json_body(request)
    note = str(body.get("note") or "")[:proposals.NOTE_MAX]
    payload, status_code = await _decide_proposal(ts, verb, note)
    return web.json_response(payload, status=status_code)


async def _decide_proposal(ts: int, verb: str,
                           note: str = "") -> tuple[dict, int]:
    """Accept or decline, wherever the press came from. `(payload, status)`.

    `_end_finding`'s rule, one store over: the Proposals tab's two buttons
    and an opportunity case's *Do it*/*Wrong* are the same two endings, and
    the whole of what makes an accept safe — write, reload, verify, settle,
    in that order — lives here once rather than in each surface that offers
    it. The status rides back rather than being raised, because a refusal
    is data the caller renders and a 409 is what it renders it as.
    """
    status = {"accept": "accepted", "decline": "declined"}.get(verb)
    if status is None:
        return {"error": "unknown verb"}, 404

    applied = None
    if status == "accepted":
        pending = await asyncio.to_thread(proposals.get, ts)
        if pending is None or pending.get("status") not in \
                proposals.OPEN_STATUSES:
            return {"error": "that proposal has already been answered"}, 409
        started = time.time()
        applied, why = await _apply_accepted(pending)
        journal.record("proposal", "applied" if applied else "error",
                       ok=bool(applied), error="" if applied else why,
                       duration_s=time.time() - started,
                       extra={"ts": ts})
        if applied is None:
            return {"error": why,
                    **await asyncio.to_thread(_proposals_payload)}, 409

    row = await asyncio.to_thread(proposals.decide, ts, status, note,
                                  None, applied)
    if row is None:
        return {"error": "that proposal has already been answered"}, 409
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
    return payload, 200


async def _wait_for_gone(entity_id: str) -> bool:
    """Whether this automation has stopped being provided, within the ceiling.

    `_wait_for_entity`'s mirror, and separate rather than a flag on it:
    "it turned up" and "it went away" are the two claims, they are read at
    opposite ends of a press, and one function answering both with a
    boolean argument is a call site nobody can read.

    **An entity disappearing is not what happens here, and asking whether
    it exists was a question that could never come back yes.** Every
    automation brAIn writes carries an `id`, so Core gives it a
    `unique_id` and therefore an entity REGISTRY entry — and a registry
    entry outlives the thing that provided it. Splice the entry out of
    `automations.yaml`, reload, and Core unloads the automation and then
    re-publishes the orphaned registry entry as a state of `unavailable`
    carrying `restored: true`. `GET /api/states/<id>` answers 200 for
    that, for ever.

    So this polled a 200 that was never going to become a 404, spent the
    whole `ACCEPT_VERIFY_S`, and reported that the automation "was not
    really removed" — after which `_remove_automation` did the honest
    thing with a failed verification and PUT THE ENTRY BACK. The removal
    worked every time; the check condemned it and the revert undid it,
    which is why a rehearsal's cleanup listed its own planted automations
    as left behind in both the file and the states.

    `checks/devices.py:restored` already reads exactly this shape and
    names it: entities left over with nothing providing them. What is
    being verified is that nothing provides it any more, and a restored
    orphan is that, said by Core in as many words.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    deadline = time.monotonic() + ACCEPT_VERIFY_S
    while True:
        state = await ha_data.entity_state(entity_id)
        if state is None or _is_restored_orphan(state):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(ACCEPT_POLL_S)


def _is_restored_orphan(state: dict) -> bool:
    """A state Core is publishing on behalf of nothing.

    `restored` is the authority — Core sets it on exactly these — and the
    `unavailable` half is required with it rather than instead of it: an
    automation that is merely unavailable for some other reason is still
    somebody's automation, and reading that as "removed" would let a
    failed splice pass verification.
    """
    attrs = state.get("attributes") or {}
    return (attrs.get("restored") is True
            and str(state.get("state")) == "unavailable")


async def _remove_automation(entry_id: str,
                             entity_id: str = "") -> tuple[dict | None, str]:
    """Splice one entry out, reload, and check it really went.

    `_apply_accepted`'s mirror, and the same three claims backwards: the
    bytes are out of the file, Home Assistant read the file again, and the
    entity has left Core. Any of them failing puts the file back and
    reloads again, so a removal that could not be honoured leaves nothing
    half done.

    A function rather than a block inside the Remove route because the
    rehearsal removes what it planted through it: a second implementation
    of taking an automation out is a second chance to leave one behind.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    written = await asyncio.to_thread(automation_writer.remove, entry_id)
    if written.get("missing"):
        # The entry is not in the file: somebody deleted it by hand, and
        # there is nothing to splice, nothing to reload and nothing to put
        # back. Reporting that as a failure would leave an intent card on
        # the tab with no way to end it — Remove is its only ending — so
        # "already gone" IS the removal having happened.
        return None, ""
    if not written.get("ok"):
        return None, str(written.get("error")
                         or "brAIn could not edit automations.yaml")
    failure = ""
    try:
        await ha_data.call_core_service("automation", "reload")
    except Exception as exc:  # noqa: BLE001
        failure = f"Home Assistant would not reload its automations: {exc}"
    if not failure and entity_id:
        try:
            if not await _wait_for_gone(entity_id):
                failure = (f"{entity_id} is still in Home Assistant after "
                           "the reload, so the automation was not really "
                           "removed")
        except Exception as exc:  # noqa: BLE001
            failure = f"brAIn could not check whether it went: {exc}"
    if not failure:
        return written, ""

    reverted = await asyncio.to_thread(automation_writer.revert, written)
    try:
        await ha_data.call_core_service("automation", "reload")
    except Exception as exc:  # noqa: BLE001 — the file is back; a second
        # failed reload is a log line.
        log.warning("could not reload after putting it back: %s", exc)
    if not reverted.get("ok"):
        failure += (" — and putting automations.yaml back failed: "
                    f"{reverted.get('error')}")
    return None, failure


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
    ts = int(request.match_info["ts"])
    row = await asyncio.to_thread(intents.get, ts)
    if row is None:
        return web.json_response({"error": "that one-off is not on the list"},
                                 status=404)

    written = None
    if row.get("status") != "refused" and row.get("automation_id"):
        # The entity Core registered for the id brAIn wrote, when the
        # registry will say: a row armed before that was read back carries
        # a guessed id, and waiting for a guess to go is waiting on a name
        # that may belong to something else.
        real, _looked = await _registry_entity_id(row["automation_id"])
        written, failure = await _remove_automation(
            row["automation_id"], real or row.get("entity_id") or "")
        if failure:
            return web.json_response(
                {"error": failure,
                 **await asyncio.to_thread(_proposals_payload)}, status=409)
        # And its registry entry, which the file outlives. Not a failure of
        # the removal when it cannot be done — the automation is gone and
        # the row may go — but said in the log, because the orphan it
        # leaves is one `dev.restored` will report.
        why = await _drop_registry_entry(row["automation_id"])
        if why:
            log.warning("one-off %s removed, but %s", ts, why)

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
        # An automation the accept APPENDED leaves a registry entry behind
        # once the file is back, which Core keeps as a restored orphan
        # under the very entity id the next accept of the same thing would
        # want. An edit put somebody's own automation back, whose entry is
        # theirs and stays.
        if (reverted.get("ok") and reloaded
                and written.get("target", "automations") == "automations"
                and not (entry.get("proposal") or {}).get("edits")):
            why = await _drop_registry_entry(
                str(written.get("automation_id") or ""))
            if why:
                log.warning("accept undone, but %s", why)

        def put_back() -> tuple[bool, dict]:
            restored = proposals.reopen(entry["proposal"]) is not None
            if entry.get("fact"):
                _unqueue_fact(entry["fact_source"], entry["fact"])
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

    if entry["kind"] in ("finding_todo", "todo_done", "todo_removed"):
        restored, payload = await asyncio.to_thread(_undo_todo, entry)
        payload["undone"] = restored
        if not restored:
            payload["error"] = "that has already moved on — nothing to put back"
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

    restored, payload = await asyncio.to_thread(_undo_finding, entry)
    payload["undone"] = restored
    return web.json_response(payload)


def _undo_todo(entry: dict) -> tuple[bool, dict]:
    """Reverse a press on the to-do list. Module-level, `_undo_finding`'s rule.

    Three presses, and each one is reversed as a whole or not at all —
    half of any of them is worse than none. Accepting a finding put a row
    away and an item up, so its undo takes the item down and the row back;
    completing wrote a fact and an upgraded ledger entry, so its undo puts
    the item back on the list, drops the queued fact and restates the entry
    as `accepted`; dropping released a suppression, so its undo re-settles.
    """
    kind = entry["kind"]
    item = entry.get("item") or {}
    restored = False

    if kind == "finding_todo":
        # The item first: if it has already been ticked off or dropped,
        # putting the finding row back would be the same work twice.
        gone = todo_store.remove(item.get("id") or 0) is not None
        restored = gone and findings_store.restore(entry["finding"]) is not None
        if restored and entry.get("key"):
            findings_store.unsettle(entry["key"])
    elif kind == "todo_done":
        restored = todo_store.reopen(item.get("id") or 0) is not None
        if restored and item.get("finding_key"):
            findings_store.remember_answer(
                item["finding_key"], item["text"], "accepted",
                source=item.get("source", ""),
                source_title=item.get("source_title", ""))
    elif kind == "todo_removed":
        restored = todo_store.restore(item) is not None
        if restored and item.get("finding_key"):
            findings_store.remember_answer(
                item["finding_key"], item["text"], "accepted",
                source=item.get("source", ""),
                source_title=item.get("source_title", ""))

    # The memory line has not been consolidated — the token is younger than
    # any pass — so it comes out of the inbox the way a queued fact does.
    if restored and entry.get("fact"):
        _unqueue_fact(entry["fact_source"], entry["fact"])
    payload = _todo_payload()
    payload["findings"] = findings_store.listing()["findings"]
    return restored, payload


def _undo_finding(entry: dict) -> tuple[bool, dict]:
    """Reverse an ending: the row, the settled key and the memory line.

    Module-level rather than a closure inside the route for the same
    reason `_end_finding` is: the deep doctor drives this to prove an undo
    round-trips, and a second implementation of putting a row back would
    be exactly the thing worth catching rather than the thing catching it.
    """
    if entry["kind"] == "finding":
        # The row may have been re-reported in the meantime, in which
        # case the list already holds a newer version of it and putting
        # this one back would throw away whatever has happened since.
        restored = findings_store.restore(entry["finding"]) is not None
        if entry.get("key"):
            findings_store.unsettle(entry["key"])
        # And the rule, which is the effect that reaches code: a Wrong on
        # a check's row muted that check for that entity, and an Undo that
        # left it would put the card back under a rule that will never let
        # the same report through again. A token minted before the ids
        # rode on it finds the rule by the report it was written about.
        if "exception" in entry:
            facts_store.forget_ids(entry.get("exception") or [])
        elif entry.get("key"):
            facts_store.forget_exceptions(entry["key"])
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
    # the same way a queued fact does from the Memory tab — and out of
    # the facts store, which read it within the minute.
    if entry.get("fact"):
        _unqueue_fact(entry["fact_source"], entry["fact"])
    return restored, _findings_payload()


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
        # The rule goes with the wording. "Let brAIn raise it again" on a
        # report somebody once marked Wrong released the key and left the
        # `exception:` fact standing the check down for that entity, so
        # the one press whose whole meaning is "tell me about this again"
        # could never bring the report back for the four checks that read
        # exceptions. Counted as an answer either way: a rule with no
        # ledger entry (the key aged out) is still a rule to release.
        forgot = facts_store.forget_exceptions(key)
        return ok or forgot > 0, _findings_payload()

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


def _mute_source(source: str) -> list[dict]:
    """Stop a producer's findings, and take what it has already filed off
    the list. One implementation for the two presses that do it (the
    scorecard's button and the Wrong form's box), and the half `triage.
    gate` cannot do for itself: the gate drops what arrives from now on,
    this clears what is already there. Nothing is settled and nothing
    goes into memory — a mute is about the RULE and not about the house."""
    current = settings_store.load().get("muted_sources") or []
    if source not in current:
        settings_store.save({"muted_sources": [*current, source]})
    # Before the rows go: they are where a non-check producer's title is.
    title = findings_store.source_titles().get(source)
    if title:
        MUTED_TITLES[source] = title
    return findings_store.clear_source(source)


# What a producer id looks like: `check:dev.frozen`, `custom-1788980390`,
# `user-1789499215`, `fix`. Anything else off the wire names nothing and
# is refused rather than written into the settings and the log.
_SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


def _source_of(body: dict) -> str:
    source = str((body or {}).get("source") or "").strip()
    if not _SOURCE_RE.match(source):
        raise web.HTTPBadRequest(text="which producer? `source` names it")
    return source


def _refuse_unmutable(source: str) -> None:
    """`cases.UNMUTABLE_SOURCES` is refused at the route as well as left off
    the ⋯, because a panel served before this release still offers the
    press — and pressing it deleted every open Resident case, a safety
    case included, while muting nothing that was ever read."""
    if source in cases.UNMUTABLE_SOURCES:
        raise web.HTTPConflict(
            text="That is not a rule brAIn can stop raising. Use Not a "
                 "problem on the card, and say why — that is what it "
                 "learns from.")


async def h_findings_mute(request: web.Request) -> web.Response:
    """"Stop raising these": a producer the homeowner has had enough of.

    A rule wrong about this house — a scorecard reading 0 confirmed against
    6 marked Wrong — used to have exactly one answer, Wrong one row at a
    time, which settles one wording and leaves the next pass to make the
    same mistake in new words. This is the press for the rule itself. It
    takes the producer's open rows off the list and answers with how many,
    because a press that removed six cards has to say so.
    """
    source = _source_of(await _json_body(request))
    _refuse_unmutable(source)

    def apply() -> dict:
        taken = _mute_source(source)
        # `muted` is the payload's list of producers; the flag is `ok`.
        return {"ok": True, "cleared": len(taken), **_findings_payload()}
    payload = await asyncio.to_thread(apply)
    # `_source_of` has already refused anything that is not a producer id;
    # the line breaks are stripped again here because this string arrived
    # off the wire and a log line is where a scanner (rightly) looks.
    log.info("muted %s (%d row(s) taken off the list)",
             source.replace("\r", "").replace("\n", ""), payload["cleared"])
    return web.json_response(payload)


async def h_findings_unmute(request: web.Request) -> web.Response:
    """"Raise these again": stops the mute and nothing more. Nothing comes
    back until the producer reports it on its next pass — `unsettle`'s
    rule, for its reason: what was on the list is not necessarily still
    true of the house."""
    source = _source_of(await _json_body(request))

    def apply() -> dict:
        current = settings_store.load().get("muted_sources") or []
        settings_store.save({"muted_sources": [s for s in current
                                               if s != source]})
        return {"ok": True, **_findings_payload()}
    return web.json_response(await asyncio.to_thread(apply))


async def h_finding_advice(request: web.Request) -> web.Response:
    """Replace what a finding says to do with what the conversation reached.

    The chat's door onto "What you'd need to do" — the `advice` kind an
    `offer_resolutions` call may carry. Not an ending: the row stays
    exactly where it is with a better sentence on it, and the press is
    the consent, exactly as it is for the three endings beside it. No
    undo token, because nothing was taken away.
    """
    finding = _finding_or_404(request)
    body = await _json_body(request)
    fix = str((body or {}).get("fix") or "").strip()
    if not fix:
        raise web.HTTPBadRequest(text="`fix` is the sentence to put on the card")

    def apply() -> dict:
        row = findings_store.set_fix(finding["ts"], fix, "chat")
        if row is None:
            raise web.HTTPConflict(text="that finding has gone from the list")
        return {"advised": True, **_findings_payload()}
    return web.json_response(await asyncio.to_thread(apply))


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


# What the chat is handed when you press Discuss.
#
# It used to say "look, don't touch" and that sentence was the whole of the
# guarantee, while the conversation it opened held every acting tool the
# project pre-approves. The guarantee is the session's now (a discussion's
# acting tools ASK — `chat_session.DISCUSS_ASK`), and the prompt says what
# the honest way to change something is: a `plan` option, which is the
# plan → Apply → Undo path every other change on the card already takes.
#
# It also used to send the finding's sentence and nothing else, so a
# Resident case — whose investigation had already read the entities, put
# numbers and times on them and weighed how sure it was — was discussed by
# a chat told to "check the current state and the history" from scratch,
# paying again for what the investigation had already paid for, and on a
# case that names no single entity it was not even told which ones. The
# evidence, the confidence, what the case said could be done and where the
# investigation's own transcript is now ride in the prompt
# (`_discuss_context`), and the chat is told to start from them.
#
# The first line is load-bearing twice over: it is what the chat bubble
# leads with, and — because a conversation's title is its first genuine
# user message — it is what the Chats rail calls the conversation. The old
# opener ("I want to talk about something you flagged…") titled every
# discussion identically, so a rail of three discussions was three copies
# of the same sentence with the finding buried mid-message.
DISCUSS_PROMPT = """Discussing: {text}
{detail}{fix}{entity}
Severity: {severity}{context}
You flagged this in my home. Tell me what is actually going on, and say
plainly whether you think it is really a problem here. {look}"""

# What only the conversation in the chat is told — a reply from a phone
# runs read-only and offers nothing, so it is handed the context above
# without this.
DISCUSS_OFFER = """

Anything that would change my house from this conversation asks me first —
that is how this conversation is set up — so do not try to make a change
here. If we agree something should change, offer it as a `plan` option
below whose label says exactly what to change: pressing it has brAIn work
out those steps for me to read and Apply, with an undo, and nothing changes
before I press Apply.

Then end your answer by calling offer_resolutions with the ways this could
actually be settled, so they are buttons I can press here. Offer only what
your own look supports, name each one the way I would say it, and leave out
any you cannot justify — two honest options beat four. If your look has
worked out what I should actually DO about it — which hub to power-cycle,
which automation to open, which setting to change — offer that as an
`advice` option too: pressing it puts your sentence on the card as what to
do, and leaves the finding open."""

# How much of the investigation's own words ride along. Enough for its
# conclusion, never its whole working: the evidence rows are the facts,
# and this is only the reasoning that joined them.
DISCUSS_RUN_CHARS = 700
DISCUSS_EVIDENCE_ROWS = 8

_CONFIDENCE_WORDS = ((0.8, "confident"), (0.5, "fairly sure"), (0.0, "not sure"))


def _investigation_said(run_id: str) -> str:
    """The last things the investigation said in prose, bounded.

    Read out of the engine's own project directory, where the run lives
    (`run_sources`' `store: "engine"`). Its closing reply is the case JSON
    — already on the row — so what is worth carrying is the prose it wrote
    on the way there. Never raises: a transcript that could not be read is
    a prompt without this paragraph, not a refused Discuss.
    """
    if not run_id:
        return ""
    try:
        events = conversations.transcript(engine.CLAUDE_HOME, run_id)
    except Exception:  # noqa: BLE001
        return ""
    said = [str(e.get("text") or "").strip() for e in events
            if e.get("type") == "text"]
    said = [t for t in said if t and not t.lstrip().startswith(("{", "```"))]
    text = " ".join(" ".join(said[-2:]).split())
    if len(text) > DISCUSS_RUN_CHARS:
        text = "…" + text[-DISCUSS_RUN_CHARS:]
    return text


def _discuss_context(finding: dict) -> tuple[str, bool]:
    """What the row already knows, as prompt lines — and whether there is
    evidence enough that the chat should start from it rather than look
    again from nothing."""
    lines: list[str] = []
    confidence = finding.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        word = next(w for floor, w in _CONFIDENCE_WORDS if confidence >= floor)
        lines.append(f"How sure brAIn was: {word}")
    stakes = {"high": "a lot", "medium": "somewhat",
              "low": "a little"}.get(finding.get("stakes") or "")
    if stakes:
        lines.append(f"How much it matters if right: {stakes}")
    evidence = [e for e in finding.get("evidence") or [] if isinstance(e, dict)]
    if evidence:
        lines.append("What the investigation read:")
        for row in evidence[:DISCUSS_EVIDENCE_ROWS]:
            when = f" ({row['when']})" if row.get("when") else ""
            lines.append(f"- {row.get('entity') or '?'}: "
                         f"{row.get('value') or '?'}{when}")
    acts = [a for a in finding.get("actions") or [] if isinstance(a, dict)]
    if acts:
        lines.append("What it said could be done:")
        for act in acts[:4]:
            ask = "would ask me first" if act.get("consent") else "brAIn could do it"
            detail = f" — {act['detail']}" if act.get("detail") else ""
            lines.append(f"- {act.get('label') or '?'} ({ask}){detail}")
    looked = (finding.get("triage") or {}).get("reason") or ""
    if looked:
        lines.append(f"What brAIn's first look said: {looked}")
    # The row's own `run_id` is the investigation that wrote the case
    # (`add_case`); a check's row carries none, and its triage
    # conversation is the run that looked at it instead.
    run_id = (finding.get("run_id")
              or (finding.get("investigation") or {}).get("run_id")
              or (finding.get("triage") or {}).get("run_id") or "")
    if run_id:
        said = _investigation_said(run_id)
        lines.append(f"The run that raised this is {run_id}"
                     + (f"; in its own words: {said}" if said else "."))
    return ("\n" + "\n".join(lines) + "\n") if lines else "\n", bool(evidence)


def _discuss_prompt(finding: dict, offer: bool = True) -> str:
    """The Discuss opener for one finding. ``offer`` is the chat's; a reply
    typed into a notification runs read-only and offers nothing."""
    context, has_evidence = _discuss_context(finding)
    entity = finding.get("entity_id") or ""
    if not entity:
        named = [str(e.get("entity")) for e in finding.get("evidence") or []
                 if isinstance(e, dict) and e.get("entity")]
        entity_line = (f"\nEntities it read: {', '.join(named[:6])}\n"
                       if named else "")
    else:
        entity_line = f"\nEntity: {entity}\n"
    look = ("Start from what was already read above — look again only at "
            "what has changed since, or at what it does not settle."
            if has_evidence else
            "Check the current state and the history before you answer.")
    prompt = DISCUSS_PROMPT.format(
        text=finding.get("claim") or finding.get("text") or "",
        detail=f"\n{finding['detail']}\n" if finding.get("detail") else "\n",
        fix=f"\nWhat you suggested: {finding['fix']}\n" if finding.get("fix") else "",
        entity=entity_line,
        severity=finding.get("severity") or "warning",
        context=context, look=look)
    return prompt + (DISCUSS_OFFER if offer else "")


REPLY_SYSTEM = """You are brAIn, answering a message somebody typed into a
notification on their phone about a problem you raised in their home. Use
the read-only tools to check the current state and the history before you
answer. Answer in plain text, under 80 words, no markdown and no greeting:
this is read on a lock screen. If they told you something about their
house rather than asking, say what you take from it in one sentence.
Change nothing."""

REPLY_TIMEOUT_S = 180
REPLY_MAX_TURNS = 24
REPLY_MAX_CHARS = 600


# Replies typed into a notification, being answered off the request drain.
# Held so the loop cannot collect a task mid-run (`_SAFETY_TASKS`' reason).
_REPLY_TASKS: set = set()


def _start_reply(finding: dict, text: str) -> tuple[bool, str]:
    """Start answering a reply and hand back at once.

    The drain runs every fifteen seconds and applies a burst in order, so
    awaiting the reply's run there held every Done, Wrong and To-do given
    after it — in the same burst and in the next — for as long as the run
    took. An empty reply is refused here, synchronously, because it is not
    a turn and spends nothing; everything after that is the task's, and a
    reply that could not be answered or delivered is logged by
    `_reply_settled` rather than reported to a drain that has moved on.
    """
    said = str(text or "").strip()
    if not said:
        return False, "the reply was empty"
    task = asyncio.get_running_loop().create_task(_reply_to_finding(finding, said))
    _REPLY_TASKS.add(task)
    task.add_done_callback(_reply_settled)
    return True, ""


def _reply_settled(task) -> None:
    _REPLY_TASKS.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning("a reply from a notification could not be answered: %s", exc)
        return
    ok, why = task.result()
    if not ok:
        log.warning("a reply from a notification was not answered: %s", why)


async def _settle_replies(timeout: float | None = None) -> None:
    """Wait for the replies in flight — what a test of the drain awaits
    before it reads what was sent."""
    if _REPLY_TASKS:
        await asyncio.wait(set(_REPLY_TASKS), timeout=timeout)


async def _reply_to_finding(finding: dict, text: str) -> tuple[bool, str]:
    """Answer a reply typed into a notification, as the next notification.

    The Reply button is the case's conversation reached from a lock
    screen: what was typed goes to the Resident with the finding it was
    typed under, the Resident looks (reading tools only — a reply must
    not be able to change the house) and its answer is pushed back to the
    same service with the same buttons, so the exchange can go on. Nothing
    here settles anything: the three verbs are still the only endings,
    and they are on the message the answer arrives in.

    Returns `(ok, why)`. An empty reply is not a turn; a run that failed
    still answers, in one sentence, because a reply that vanished into
    silence is worse than one that says brAIn could not look.
    """
    said = str(text or "").strip()
    if not said:
        return False, "the reply was empty"
    prompt = (await asyncio.to_thread(_discuss_prompt, finding, False)
              + f"\n\nThey replied from their phone: \u201c{said[:500]}\u201d\n"
              "Answer that.")
    started = time.time()
    try:
        result = await _claude(
            engine.run_analyst, prompt, REPLY_SYSTEM, eff_model(),
            REPLY_TIMEOUT_S, REPLY_MAX_TURNS, "resident", job="investigate",
            priority=run_queue.PRESS)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": str(exc), "text": ""}
    journal.record("reply", "ok" if result.get("ok") else "error",
                   ok=bool(result.get("ok")),
                   error="" if result.get("ok") else str(result.get("error")),
                   duration_s=time.time() - started,
                   extra={"ts": finding.get("ts")})
    answer = " ".join(str(result.get("text") or "").split())[:REPLY_MAX_CHARS]
    if not result.get("ok") or not answer:
        answer = ("brAIn could not look into that just now — open the panel "
                  "to carry on the conversation there.")
    title = f"brAIn: {str(finding.get('text') or 'your reply')[:60]}"
    sent = await _send_notification([finding], message=(title, answer))
    return sent, "" if sent else "the answer could not be delivered"


async def h_finding_discuss(request: web.Request) -> web.Response:
    """Open this finding as a conversation in the chat terminal.

    A finding is its own conversation — landing it in whichever chat was
    open put "the garage lights" under a half-finished question about the
    heating — and it is opened through the REGISTRY, never by resetting
    the attached session. The reset killed that session's process whatever
    it was doing, so pressing Discuss while a chat was mid-answer threw the
    answer and its approval card away with no warning, which is the one
    thing holding several conversations exists to prevent. `new` leaves a
    busy conversation answering in the background (and reuses an empty
    one rather than spending a slot), and the only refusal left is the
    cap's own sentence when every live chat is busy.

    The subject is handed to `new` rather than set afterwards, because it
    decides the process's argv (`chat_session.DISCUSS_ASK`): a discussion
    is spawned asking before it acts, not respawned into it.
    """
    finding = _finding_or_404(request)
    prompt = await asyncio.to_thread(_discuss_prompt, finding)
    registry = _chat_registry()
    try:
        await registry.new(finding_ts=int(finding["ts"]))
        session = _chat()
        await session.send(prompt)
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=_refusal(exc))
    return web.json_response({"ok": True, "finding": finding,
                              "session_id": session.session_id})


async def h_finding_fix(request: web.Request) -> web.Response:
    """"Show me what you'd change." Queues the READ-ONLY plan run.

    This route used to send the tool-enabled run at the house on the
    press. It is kept at the same path rather than renamed because a panel
    served before this update is still open in somebody's browser, and its
    Fix button must not 404 — what changed is what the press *buys*, and
    an old panel pressing it gets the plan step exactly as a new one does,
    which is the safer of the two answers to give a browser we cannot see.
    """
    finding = _finding_or_404(request)
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    # What a conversation about this finding agreed to change, when the
    # press came from a `plan` resolution in the chat. It is the plan
    # run's brief and nothing more: the run is still read-only, what it
    # writes is still a plan on the card, and the change still waits for
    # Apply — which is the whole reason the chat offers this rather than
    # acting itself.
    body = await _json_body(request)
    change = " ".join(str(body.get("change") or "").split())[:PLAN_CHANGE_MAX]
    job_id = f"{PLAN_JOB_PREFIX}{finding['ts']}"
    # The in-memory job is the authority on "a run is going" — it is what
    # actually knows. The stored status is the copy the browser renders, and
    # any left behind by a dead process is reconciled at startup.
    if finding["status"] in ("planning", "fixing") or not _enqueue(
            job_id, kind="plan", finding_ts=finding["ts"], change=change):
        raise web.HTTPConflict(text="already being looked at")

    def claim() -> dict:
        findings_store.set_status(finding["ts"], "planning", result="")
        return _findings_payload()

    return web.json_response(await asyncio.to_thread(claim))


async def h_finding_apply(request: web.Request) -> web.Response:
    """"Yes, do exactly that." Queues the one tool-enabled run in the panel.

    The consent is this press and nothing else, so it is refused without
    a plan on the row and refused for a plan that said software should not
    make this change — the card offers no Apply in either case, and a
    route that trusted the card would be a rule held in one place out of
    two. The plan itself is read off the row inside `_run_fix`, never
    taken from the request: what the run carries out has to be what was on
    the screen that was pressed.
    """
    finding = _finding_or_404(request)
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    plan = finding.get("plan") or {}
    if finding["status"] != "planned" or not plan.get("can_fix"):
        raise web.HTTPConflict(
            text="there is no plan on this finding to apply — press Fix it "
                 "first, and read what it says it would change")
    job_id = f"{FIX_JOB_PREFIX}{finding['ts']}"
    if not _enqueue(job_id, kind="fix", finding_ts=finding["ts"]):
        raise web.HTTPConflict(text="already being fixed")

    def claim() -> dict:
        findings_store.set_status(finding["ts"], "fixing", result="")
        return _findings_payload()

    return web.json_response(await asyncio.to_thread(claim))


async def h_finding_cancel(request: web.Request) -> web.Response:
    """"No, don't." The row goes back to open and KEEPS its plan.

    Keeping it is the whole of the decision: the plan cost a Claude run,
    and somebody who wants to read it again — or think about it and come
    back — should not pay for it twice. Nothing else changes: the finding
    is open, exactly as it was before the press, so every other ending is
    on the card again.
    """
    finding = _finding_or_404(request)
    if finding["status"] != "planned":
        raise web.HTTPConflict(text="there is no plan waiting on this one")

    def drop() -> dict:
        findings_store.set_status(finding["ts"], "open", result="")
        return _findings_payload()

    return web.json_response(await asyncio.to_thread(drop))


async def h_finding_unfix(request: web.Request) -> web.Response:
    """Put back what the fix changed, and say what it could not.

    Deliberately NOT the toast's `undo_store` token: that ring is five
    minutes long and in memory, which is right for "I misclicked" on a row
    and wrong for bytes in `/config` and an automation Core has reloaded.
    This is a button on the card for as long as the row says `fixed`,
    because the thing it reverses is durable — see `unfix.py` for why the
    files come back and the service calls only get listed.

    Four steps in this order, which are four different claims: the files
    are restored, the domains they belong to are reloaded, the row goes
    back to `open` carrying what happened, and the calls are reported. A
    reload that Core refuses does not fail the undo — the bytes are
    already back, and a failure there is a sentence on the card rather
    than a reason to leave the file reverted while the row says otherwise.
    """
    import ha_data  # noqa: PLC0415 — deferred; see `_wait_for_entity`

    finding = _finding_or_404(request)
    if finding["status"] != "fixed":
        raise web.HTTPConflict(
            text="there is nothing to undo: brAIn has not changed anything "
                 "for this finding")
    started = float(finding.get("fix_started") or 0)
    ended = float(finding.get("fix_ended") or 0)
    if started <= 0 or ended <= 0:
        # A fix from before the window was recorded — an add-on updated
        # while a fixed row sat on the tab. "I could not tell what this
        # changed" and "it changed nothing" are different claims, and
        # answering with the second would put the row back to open while
        # the change stands. The card hides the button for the same
        # reason; this is the half that cannot be hidden from.
        raise web.HTTPConflict(
            text="brAIn did not record what this fix changed — it ran "
                 "before the panel kept that window. `brain undo` in the "
                 "terminal lists every file Claude has edited.")

    entries = await asyncio.to_thread(unfix.journal_entries, started, ended)
    calls = await asyncio.to_thread(unfix.service_calls, started, ended)
    outcome = await asyncio.to_thread(unfix.revert_edits, entries)

    reload_failures = []
    for domain, service in outcome["reloads"]:
        try:
            await ha_data.call_core_service(domain, service)
        except Exception as exc:  # noqa: BLE001 — the bytes are already back
            reload_failures.append(
                f"{domain} would not reload, so Home Assistant is still "
                f"running what the fix wrote until it does: {exc}")
            log.warning("could not reload %s after an undo: %s", domain, exc)

    text = "\n\n".join([unfix.summary(outcome, calls)] + reload_failures)

    def restore() -> dict:
        findings_store.set_status(finding["ts"], "open", result=text,
                                  changed=[])
        return _findings_payload()

    payload = await asyncio.to_thread(restore)
    await asyncio.to_thread(outcomes.note_undone, finding["ts"],
                            finding.get("text") or "")
    # The fix queued "brAIn fixed this on …" when it finished, and that is
    # no longer true. A correction is the one thing that is right whether
    # or not the consolidator has got to it yet: still in the queue, the
    # two lines are reconciled in the same pass; already in the document,
    # this is the only honest way to say otherwise — which is the door the
    # memory inbox exists to be. Nothing is written when the fix recorded
    # no change, because there is no claim to correct.
    if finding.get("changed"):
        await _submit_memory(
            f"brAIn undid its own fix on {time.strftime('%Y-%m-%d')}: "
            f"{finding['text']} — the change was put back, so the house is "
            "as it was before it.", source="fix")
    log.info("finding %s undone: %d file(s) back, %d service call(s) listed",
             finding["ts"],
             len(outcome["restored"]) + len(outcome["removed"]), len(calls))
    return web.json_response(payload)


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
    insight = await asyncio.to_thread(_read_json, _insight_path(card_id))
    if insight is None:
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
                      confidence: str = "medium", *, subject: str = "",
                      subjects=(), run_id: str = "",
                      expires: str = "") -> None:
    """Append a candidate fact to the memory inbox.

    The panel does NOT write memory.md. One writer owns that document —
    the consolidator — which is what lets the terminal, voice, insights,
    and study sessions all feed the same memory without a lock between
    them. Everything here is a queue.

    ``subject``/``subjects`` are what the writer KNOWS the fact is about —
    the finding's entity, a case's evidence, the device a curiosity run
    asked about. Without them the facts store could only tag a line by
    finding a literal entity id or a room's name in it, and a sentence
    written for a person carries neither: a correction about "the porch
    sensor" landed as a fact about the whole house, which the next look
    at that sensor may never be shown. ``run_id`` is the conversation
    that taught it, which is what the Knowledge tab's "See the run" opens.
    Absent keys are not written, so a line from a writer that knows none
    of this is the line it always was.
    """
    try:
        MEMORY_INBOX_DIR.mkdir(parents=True, exist_ok=True)
        record = {"ts": int(time.time()), "source": source, "fact": fact,
                  "confidence": confidence}
        named = [str(s).strip() for s in ([subject] + list(subjects or ()))
                 if str(s or "").strip()]
        named = list(dict.fromkeys(named))
        if named:
            record["subject"] = named[0]
            if len(named) > 1:
                record["subjects"] = named[1:facts_store.MAX_SUBJECTS]
        if run_id:
            record["run_id"] = str(run_id)[:64]
        if expires:
            record["expires"] = str(expires)[:10]
        line = json.dumps(record, ensure_ascii=False)
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


# -- the knowledge cards: what brAIn learned about itself learning ----------

async def h_knowledge_cards(request: web.Request) -> web.Response:
    """Every milestone card there is, plus what is still being waited for.

    The two together because they are one screen: a card that exists and
    a measurement that has not landed are the same question asked at two
    different times, and a list of cards with no sense of what is coming
    reads as everything brAIn is ever going to know.
    """
    cards = await asyncio.to_thread(milestones.list_cards)
    settled = await asyncio.to_thread(milestones.settled)
    return web.json_response({
        "cards": cards,
        "pending": [{"id": m["id"], "store": m["store"], "title": m["title"]}
                    for m in milestones.MILESTONES if m["id"] not in settled],
        "running": [j for j in (JOBS.get(_milestone_job_id(m["id"])) or {}
                                for m in milestones.MILESTONES)
                    if j.get("state") in ("queued", "generating")],
    })


async def h_knowledge_card(request: web.Request) -> web.Response:
    card = await asyncio.to_thread(
        milestones.get_card, request.match_info["card_id"])
    if card is None:
        raise web.HTTPNotFound(text="no such knowledge card")
    return web.json_response(card)


async def h_knowledge_card_refresh(request: web.Request) -> web.Response:
    """Make this card again, on demand.

    The only thing that clears a settled milestone. A person asking for
    it again is the one case where re-running is not the loop the settled
    key exists to prevent — and it re-reads the store rather than
    replaying the stored prompt, because what the card should say is
    whatever is true now.
    """
    card_id = request.match_info["card_id"]
    entry = milestones.get(card_id)
    if entry is None:
        raise web.HTTPNotFound(text="no such knowledge card")
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    now = time.time()
    snapshot = await _house_snapshot(now)
    payloads = await asyncio.to_thread(_milestone_payloads)
    prog = (snapshot.get("stores") or {}).get(entry["store"]) or {}
    payload = payloads.get(entry["store"]) or {}
    if not entry["ready"](prog, payload):
        # Not an error: the measurement really is not there any more (a
        # store rebuilt from a shorter history, a meter removed), and
        # saying so beats a card written from numbers that have gone.
        return web.json_response(
            {"error": "that measurement does not have an answer right now",
             "state": prog.get("state"), "reason": prog.get("reason")},
            status=409)
    await asyncio.to_thread(milestones.unsettle, card_id)
    queued = _enqueue(
        _milestone_job_id(card_id), kind="milestone", milestone=card_id,
        prompt=milestones.prompt_for(entry, prog, payload),
        mark=entry["mark"](prog, payload), because="you asked for it again",
        title=entry["title"])
    return web.json_response({"id": card_id, "queued": queued})


# -- onboarding: learn the home, then propose cards worth having ------------

async def h_onboarding(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(onboarding.state))


async def _notify_services() -> list[dict]:
    """The notify services Home Assistant has registered, phones first.

    Asked of Core directly rather than through the checks snapshot: that
    one gathers the registries, the config files, a week of statistics
    and sixty days of battery means, and this needs one endpoint. The
    parsing is `onboarding.notify_candidates`', so there is one answer to
    "which of these can take a message".
    """
    import aiohttp  # noqa: PLC0415
    import ha_data  # noqa: PLC0415

    async with aiohttp.ClientSession() as session:
        raw = await ha_data._rest_get(session, "/services", timeout=20)
    names = set()
    for row in raw or []:
        domain = str((row or {}).get("domain") or "").lower()
        for name in ((row or {}).get("services") or {}):
            names.add(f"{domain}.{str(name).lower()}")
    return onboarding.notify_candidates(names)


async def h_onboarding_notify(request: web.Request) -> web.Response:
    """Step 0: where brAIn may speak, and the hours it may not.

    A house Core will not answer for gets an empty list and a reason
    rather than a 502 — the step is skippable and a first-run flow that
    cannot be got past over a notify service is worse than one with no
    notify service.
    """
    try:
        candidates = await _notify_services()
        error = ""
    except Exception as exc:  # noqa: BLE001 — report, don't 500
        log.info("could not list notify services: %s", exc)
        candidates, error = [], "Home Assistant did not answer"
    return web.json_response({
        "candidates": candidates, "error": error,
        # The panel cannot write these into the add-on's own options —
        # see `onboarding.save_notify`. `writable` says so out loud so
        # the screen can show the two lines to paste rather than
        # implying the Configuration tab has been updated.
        "writable": False,
        **await asyncio.to_thread(onboarding.notify_state),
    })


async def h_onboarding_notify_save(request: web.Request) -> web.Response:
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="expected a JSON object")
    try:
        saved = await asyncio.to_thread(
            onboarding.save_notify, body.get("service"),
            body.get("quiet_start"), body.get("quiet_end"), body.get("brief"))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    return web.json_response(saved)


async def h_onboarding_learn(request: web.Request) -> web.Response:
    """Queue the opening syllabus, and put one card up while it runs.

    The syllabus is five study sessions and takes the better part of
    half an hour, and for the whole of it the Insights tab said nothing
    at all — which on a first install is indistinguishable from an
    add-on that does not work. Home Overview runs in search mode off the
    orientation map, so it costs a small prompt and a few lookups rather
    than the whole house, and it is admitted to this home's card set at
    the same time: a card whose category `visible_categories` does not
    return is a file the dashboard skips, which is a Claude run spent on
    something nobody can see.
    """
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    result = await asyncio.to_thread(onboarding.start_learning)
    try:
        await asyncio.to_thread(onboarding.admit_first_card)
        result["first_card"] = onboarding.FIRST_CARD if _enqueue(
            onboarding.FIRST_CARD, because="your first card") else ""
    except Exception as exc:  # noqa: BLE001 — the syllabus is the step
        log.warning("could not queue the first card: %s", exc)
        result["first_card"] = ""
    return web.json_response(result)


async def h_onboarding_recommend(request: web.Request) -> web.Response:
    """One searching pass over the memory document and a map of the home.

    `run_analyst` over the map, which is what every other analytical site
    in this file does and for the same measured reason: a map plus
    read-only tools costs a prompt of a couple of thousand characters
    where the snapshot posts a hundred thousand, and it can go and LOOK — which matters more here than anywhere, because
    the system prompt asks each proposal to cite what it found. A
    snapshot is capped at `MAX_ENTITIES`, so this pass was proposing the
    card set for whichever entities fitted under the cap and calling a
    house sparse when they did not, with no way to read the history that
    would have settled either question.

    Reading tools only, because it is an unattended run over somebody's
    house that is about to be handed a list to tick.

    The snapshot path stays as the FLOOR under it, `_search_run`'s
    arrangement and for its reason one step earlier in a person's day: a
    map that could not be collected, a run that ended on its turn cap, a
    reply that did not parse — none of those is a reason for the one
    screen between a fresh install and having any cards at all to dead-end
    on a 502. A fallback is logged, because a pass that keeps taking it is
    a pass worth reading the log about.
    """
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")

    import ha_data  # deferred so the module loads without aiohttp in tests

    memory = await asyncio.to_thread(_read_shared_memory)

    async def searching() -> dict | None:
        """The map and read-only tools, or None to fall through."""
        try:
            orientation = await ha_data.collect_orientation(question=None)
        except Exception as exc:  # noqa: BLE001 — a failed map is a
            # fallback, not an error.
            log.warning("onboarding: could not collect the map (%s)", exc)
            return None
        result = await _claude(
            engine.run_analyst,
            onboarding.build_orientation_prompt(memory, orientation),
            onboarding.RECOMMEND_SYSTEM, eff_model(),
            TIMEOUT_S, ANALYST_MAX_TURNS, "card", job="onboarding",
            priority=run_queue.PRESS)
        return result

    async def snapshot() -> dict:
        """The whole slimmed home in one tool-free turn: what shipped."""
        # Any category works as a bundle shape here — we want the home, not
        # a topic — so borrow the broadest one available.
        shape = {"id": "onboarding", "title": "Home overview",
                 "focus": "A broad survey of this home."}
        try:
            bundle = await ha_data.collect_bundle(shape, eff_history_days())
        except Exception as exc:  # noqa: BLE001 — report, don't 500
            # `exc` is whatever the bundle collector hit, so its text is not
            # ours and is not written for anyone to read. The log gets it;
            # the response gets the one sentence that tells the user what to
            # do.
            log.warning("onboarding bundle failed: %s", exc, exc_info=True)
            raise web.HTTPBadGateway(text="could not read Home Assistant")
        return await _claude(
            engine.run_claude, onboarding.build_prompt(memory, bundle),
            onboarding.RECOMMEND_SYSTEM, eff_model(), TIMEOUT_S, 8, "card",
            job="onboarding", priority=run_queue.PRESS)

    def read(result: dict | None) -> dict | None:
        """The reply as recommendations, or None for "that did not work"."""
        if not result:
            return None
        # Claimed as a card run: it proposes the card set, and "everything
        # brAIn sent to Claude about the house" should include it.
        _record_usage(result, "onboarding")
        if not result.get("ok"):
            return None
        try:
            return onboarding.parse_recommendations(result.get("text") or "")
        except ValueError as exc:
            log.info("onboarding: the recommendations did not parse (%s)", exc)
            return None

    result = await searching()
    parsed = read(result)
    if parsed is None:
        log.warning("onboarding: the searching pass produced nothing (%s) — "
                    "posting the whole home instead",
                    (result or {}).get("error") or "unreadable reply")
        fallback = await snapshot()
        parsed = read(fallback)
        if parsed is None:
            raise web.HTTPBadGateway(
                text=(fallback.get("error") if fallback else "")
                or "recommendation failed")
    return web.json_response(await asyncio.to_thread(
        onboarding.save_recommendations, parsed))


async def h_onboarding_accept(request: web.Request) -> web.Response:
    body = await request.json()
    picked = body.get("accept")
    if not isinstance(picked, list):
        raise web.HTTPBadRequest(text="accept must be a list of indexes")
    # The shipped half. Two lists because there are two kinds of card and
    # only one of them is created — the other already exists in the code
    # and is admitted to this home's set.
    shipped = body.get("shipped")
    if shipped is not None and not isinstance(shipped, list):
        raise web.HTTPBadRequest(text="shipped must be a list of category ids")
    created = await asyncio.to_thread(onboarding.accept, picked, shipped)
    return web.json_response({"created": created, "onboarded": True,
                              "shipped": prompt_store.load_overrides()["accepted"]})


# ---------------------------------------------------------------------------
# Ideas — proposed cards, on their own page
# ---------------------------------------------------------------------------
# The run is STARTED and never awaited (`h_baselines_run`'s clock): it is
# a reasoning turn with tools over a whole house, which is minutes of
# work and far longer than ingress will hold a request open. The outcome
# is read back off `GET /api/ideas`, which is a small payload rather than
# the whole page of prose the run produced.

IDEAS_STATE = {"running": False, "starting": False, "started_at": 0.0}


def _measured_block() -> str:
    """What brAIn has measured, as lines a prompt can act on.

    `house.snapshot` is the one derivation of "is this measurement ready"
    and this reads it rather than asking the seven stores again — two
    answers to that question is the drift `house.py` exists to end. What
    the run needs from it is narrow: a store that is ready can carry a
    card, and one that is not cannot, so the sentence each store already
    writes about itself is exactly the right amount.
    """
    snap = house.snapshot()
    lines = []
    for name in house.STORES:
        row = (snap.get("stores") or {}).get(name) or {}
        state = row.get("state") or "unknown"
        says = row.get("summary") or row.get("reason") or ""
        lines.append(f"- {name}: {state}" + (f" — {says}" if says else ""))
    return "\n".join(lines)


def _ideas_payload() -> dict:
    """What the page renders, plus whether a pass is in flight."""
    return {**ideas.state(),
            "running": bool(IDEAS_STATE["running"] or IDEAS_STATE["starting"]),
            "due": ideas.due()}


async def _run_ideas() -> None:
    """One pass: the map, the memory, the measurements, then one turn.

    Every failure lands in `last_error` and the stamp is written either
    way, because a pass that failed must not leave the weekly schedule
    re-running it on the next tick for ever — `record_run`'s reason.
    """
    import ha_data  # noqa: PLC0415 — deferred, as everywhere else here

    filed = 0
    error = ""
    try:
        memory = await asyncio.to_thread(_read_shared_memory)
        have = [c.get("title") or "" for c in all_categories()]
        try:
            orientation = await ha_data.collect_orientation(question=None)
        except Exception as exc:  # noqa: BLE001 — a map that could not be
            # collected is a thinner prompt, not a failed pass.
            log.warning("ideas: could not collect the map (%s)", exc)
            orientation = None
        try:
            measured = _measured_block()
        except Exception as exc:  # noqa: BLE001
            log.warning("ideas: could not read the measurements (%s)", exc)
            measured = ""

        answered, open_ideas = await asyncio.to_thread(ideas.prompt_context)
        result = await _claude(
            engine.run_analyst,
            ideas.build_prompt(memory, orientation, have, measured,
                               answered=answered, open_ideas=open_ideas),
            ideas.system_prompt(), eff_model(),
            TIMEOUT_S, ANALYST_MAX_TURNS, "card", job="ideas")
        _record_usage(result, "ideas")
        if not result or not result.get("ok"):
            error = (result or {}).get("error") or "the ideas run failed"
        else:
            try:
                parsed = ideas.parse(result.get("text") or "")
            except ValueError as exc:
                # A reply that did not parse is a failed pass and not a
                # quiet house: the two look identical on the page unless
                # this says which.
                error = f"the reply did not parse ({exc})"
            else:
                outcome = await asyncio.to_thread(
                    ideas.add_many, parsed["ideas"],
                    run_id=result.get("session_id") or "")
                filed = len(outcome["filed"])
                if outcome["full"]:
                    log.info("ideas: %d proposed past the page cap",
                             outcome["full"])
    except Exception as exc:  # noqa: BLE001 — a pass that took the panel
        # down with it would be worse than one that reported itself.
        log.warning("ideas: the pass failed (%s)", exc, exc_info=True)
        error = str(exc)[:200]
    finally:
        await asyncio.to_thread(ideas.record_run, filed, error=error)
        IDEAS_STATE["running"] = False
        IDEAS_STATE["starting"] = False


def _start_ideas() -> bool:
    """Claim the pass. The flag flips SYNCHRONOUSLY, `start_auth_check`'s
    rule: `create_task` only schedules, so two presses in one tick would
    both pass a guard reading a flag neither task has set yet."""
    if IDEAS_STATE["running"] or IDEAS_STATE["starting"]:
        return False
    IDEAS_STATE["starting"] = True
    IDEAS_STATE["started_at"] = time.time()

    async def go() -> None:
        IDEAS_STATE["running"] = True
        IDEAS_STATE["starting"] = False
        await _run_ideas()

    try:
        asyncio.create_task(go())
    except RuntimeError:
        # No running loop. Unreachable from the two real callers (a
        # request handler and the scheduler are both inside one) and
        # released anyway: a claim that outlives the spawn it was made
        # for is a button that never works again, which is the failure
        # every guard in this file is written against.
        IDEAS_STATE["starting"] = False
        raise
    return True


async def h_ideas(request: web.Request) -> web.Response:
    return web.json_response(await asyncio.to_thread(_ideas_payload))


async def h_ideas_run(request: web.Request) -> web.Response:
    """Ask for ideas now. Deliberately skips the usage budget.

    "Automatic insights pause; asking by hand always runs" is one promise
    with two halves, and this is the second — `curiosity`'s pressed
    route makes the same call for the same reason.
    """
    if not engine.get_auth():
        raise web.HTTPBadRequest(text="connect your Claude account first")
    if not _start_ideas():
        raise web.HTTPConflict(text="already looking for ideas")
    return web.json_response(await asyncio.to_thread(_ideas_payload))


async def h_idea_accept(request: web.Request) -> web.Response:
    """Turn one idea into a card on the Insights tab."""
    idea_id = request.match_info.get("idea_id")
    created = await asyncio.to_thread(ideas.accept, idea_id)
    if not created:
        raise web.HTTPConflict(
            text="that idea is not open, or the card could not be created")
    payload = await asyncio.to_thread(_ideas_payload)
    return web.json_response({**payload, "created": created})


async def h_idea_dismiss(request: web.Request) -> web.Response:
    """Not for this house. It is not offered again.

    An optional ``{"reason": "..."}`` is kept and read back to the next
    pass (`ideas.prompt_context`) — never required, because "not for us"
    needs no essay.
    """
    idea_id = request.match_info.get("idea_id")
    body = await _json_body(request)
    reason = str(body.get("reason") or "")
    if not await asyncio.to_thread(
            lambda: ideas.dismiss(idea_id, reason=reason)):
        raise web.HTTPConflict(text="that idea is not open")
    return web.json_response(await asyncio.to_thread(_ideas_payload))


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


def _inbox_fingerprint(path: Path) -> tuple | None:
    """What this inbox file was when we read it, or None if it is not there.

    The inode rides along with the mtime and the size because the thing
    being guarded against is a file that went away and came back: the
    consolidator archives what it consumes by MOVING it into `processed/`,
    and a name that is free again is a name anything may reuse.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _consolidator_shared_fd() -> int | None:
    """Hold the consolidator's lock shared, or None if we could not.

    `_consolidation_running`'s probe, kept open instead of released: while
    this fd holds LOCK_SH nothing can take the exclusive lock a pass runs
    under, so the inbox cannot be archived out from under a read. Opened
    read-only (`O_RDONLY`, never a truncating write) for the reason
    CLAUDE.md gives — `9<` and not `9>` — and non-blocking, because asking
    a question must never be something a real pass makes us wait on. A
    refusal here is not an error: it means a pass IS running, and the
    fingerprint check below is what covers that case.

    Its own helper rather than a store's lock: this is one named file that
    a shell script owns and takes exclusively for a whole pass, so what is
    wanted is that exact path, shared, with no wait at all — where a store
    locks a sidecar beside itself and can afford to queue behind one.
    """
    try:
        fd = os.open(CONSOLIDATE_LOCK, os.O_RDONLY)
    except OSError:
        return None               # no lock file yet: nothing has ever run
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


@contextlib.contextmanager
def _consolidator_held_shared():
    """`_consolidator_shared_fd` as a `with`: the fd is closed on every
    exit from the block, in the one function that opened it, which is
    the shape a static reader can follow. Yields whether it is held."""
    fd = _consolidator_shared_fd()
    try:
        yield fd is not None
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                # Closing drops the lock anyway — this is the tidy half,
                # and a caller can do nothing with the news it failed.
                pass
            os.close(fd)


def _drop_from_inbox(item_id: str) -> bool:
    """Take a fact out of the queue before it reaches the document.

    Nothing is queued for removal afterwards: an inbox line has by
    definition never been filed (the consolidator archives what it consumes),
    so there is nothing in memory.md to forget. That is the difference from
    deleting a fact the document already holds.

    **A rewrite is a write of what we READ, and between the two the file
    may have stopped existing.** The consolidator is a separate process: it
    takes the queue, files it into `memory.md` and MOVES the inbox file into
    `processed/`. Land a rewrite after that and `atomic_write` creates the
    file again at its inbox path — carrying every line but the dropped one,
    all of them already in the document — so a press that removes one fact
    resurrects the other nineteen as pending, and the next pass files them a
    second time. Two guards, in the order they can be afforded. The
    consolidator's lock is taken **shared** around the read and the write,
    which is the whole race closed for as long as a pass is not already
    running; and because a refusal to take it means exactly that a pass IS
    running, each file is fingerprinted at read time and rewritten only if
    it is still the same file. "I could not tell" leaves the line in the
    queue, which is the old behaviour and is not a data loss — the pass that
    moved the file has already filed the fact.
    """
    with _consolidator_held_shared():
        kept: dict[Path, list[dict]] = {}
        dropped: set[Path] = set()
        lines: set[tuple[str, str]] = set()
        for path, obj in _inbox_lines():
            source, fact = str(obj.get("source") or ""), str(obj["fact"]).strip()
            if _inbox_id(source, fact) == item_id:
                dropped.add(path)
                lines.add((source, fact))
            else:
                kept.setdefault(path, []).append(obj)
        if not dropped:
            return False
        # The facts store read this line within a minute of it being
        # queued, so "never filed" stopped being true of an inbox line the
        # day that store existed: the ✕ and every Undo that comes through
        # here took the line out of the queue and left the fact asserting
        # it to every run. Forgotten from the store first, because that
        # half cannot race the consolidator.
        for source, fact in lines:
            _forget_queued_fact(source, fact)
        before = {path: _inbox_fingerprint(path) for path in dropped}
        # Only the files that actually held it are rewritten. Rewriting the
        # rest would drop any torn line they carry, which _inbox_lines skips
        # over — tidying a file we had no reason to touch is not this
        # function's job.
        for path in dropped:
            stamp = before[path]
            if stamp is None or _inbox_fingerprint(path) != stamp:
                # Archived, rewritten or rotated since the read. Whatever it
                # is now, it is not the file these lines came out of.
                log.info("inbox file %s moved while dropping a line — "
                         "leaving it alone", path.name)
                continue
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
        # True because the line MATCHED, which is the claim the caller acts
        # on: it is not in the queue any more, whether this rewrote the file
        # or a pass took the whole thing while we were reading it.
        return True


def _forget_queued_fact(source: str, fact: str) -> None:
    """Take the facts store's copy of one queued line out. Never raises."""
    try:
        facts_store.forget_text(fact, source=source)
    except Exception as exc:  # noqa: BLE001 — the queue half is the press
        log.debug("could not forget the filed copy of a queued line: %s", exc)


def _unqueue_fact(source: str, fact: str) -> bool:
    """An undo's memory half: out of the queue AND out of the store.

    The queue half finds nothing when a pass has already filed the line
    (the token outlives a pass now and then), and the store's copy has to
    go either way — a store still asserting the ending an Undo reversed is
    the same press counted as half undone. Returns whether the line was
    still in the queue, which is `_drop_from_inbox`'s own answer.
    """
    if _drop_from_inbox(_inbox_id(source, fact)):
        return True
    _forget_queued_fact(source, fact)
    return False


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
    # Current before it is listed: a fact taught a minute ago is the one
    # somebody opened the tab to see.
    await asyncio.to_thread(_ingest_facts)
    facts = await asyncio.to_thread(_facts_payload)
    return web.json_response({
        "inbox": inbox,
        "facts": facts["facts"],
        "facts_summary": facts["summary"],
        "hypotheses": hypotheses.list_all("open"),
        "hypothesis_budget": hypotheses.budget(),
        "shared_memory": _read_shared_memory(),
        "memory_state": await asyncio.to_thread(_memory_state),
        "inbox_pending": pending,
    })


FACTS_LIST_MAX = 200


def _facts_payload(query: str = "", subject: str = "",
                   limit: int = FACTS_LIST_MAX) -> dict:
    rows = facts_store.recall(query=query, subject=subject,
                              limit=max(1, min(int(limit), FACTS_LIST_MAX)))
    known = run_sources.lookup([r.get("run_id") for r in rows
                                if r.get("run_id")])
    for row in rows:
        # Provenance the House view can follow: a run id the ledger knows
        # opens in the reader every other engine-store run opens in. An
        # id nothing claimed is still shown — it is a fact about the
        # fact — and simply has no link.
        row["run_source"] = known.get(row.get("run_id") or "", "")
    return {"facts": rows, "summary": facts_store.summary(),
            "count": len(rows)}


async def h_facts(request: web.Request) -> web.Response:
    """What brAIn holds as facts, ranked for a question or a subject."""
    q = request.query
    try:
        limit = int(q.get("limit") or FACTS_LIST_MAX)
    except ValueError:
        limit = FACTS_LIST_MAX
    return web.json_response(await asyncio.to_thread(
        _facts_payload, str(q.get("query") or "")[:200],
        str(q.get("subject") or "")[:255], limit))


def _fact_subject_names() -> dict:
    """What a person calls each subject a fact can be about.

    Off the last checks pass's registry (`_NAMES`, `_FACTS_CTX`), never a
    fetch of its own: the browser is asked on every keystroke of a search,
    and a subject nobody has named yet is shown as its id, which is honest.
    """
    names = {eid: str(row.get("name") or "")
             for eid, row in _NAMES.items() if isinstance(row, dict)}
    for area_id, name in (_FACTS_CTX.get("areas") or {}).items():
        names[f"area:{area_id}"] = str(name or area_id)
    return names


def _facts_browse_payload(q) -> dict:
    def num(key, default):
        try:
            return int(q.get(key) or default)
        except (TypeError, ValueError):
            return default

    got = facts_store.browse(
        query=str(q.get("q") or q.get("query") or "")[:200],
        kind=str(q.get("kind") or "")[:16],
        source=str(q.get("source") or "")[:32],
        subject=str(q.get("subject") or "")[:255],
        sort=str(q.get("sort") or "newest")[:16],
        offset=num("offset", 0), limit=num("limit", 50),
        names=_fact_subject_names())
    known = run_sources.lookup([r.get("run_id") for r in got["facts"]
                                if r.get("run_id")])
    for row in got["facts"]:
        row["run_source"] = known.get(row.get("run_id") or "", "")
    return got


async def h_facts_browse(request: web.Request) -> web.Response:
    """Every fact brAIn holds, searchable and sortable — the Knowledge tab."""
    if request.query.get("ingest"):
        await asyncio.to_thread(_ingest_facts)
    return web.json_response(await asyncio.to_thread(
        _facts_browse_payload, request.query))


async def h_fact_forget(request: web.Request) -> web.Response:
    """Drop one fact. The document is not touched — a line already in
    memory.md is edited out of memory.md, beside the queue."""
    fact_id = request.match_info["id"]
    if not re.fullmatch(r"[0-9a-f]{8,64}", fact_id):
        raise web.HTTPBadRequest(text="not a fact id")
    gone = await asyncio.to_thread(facts_store.forget, fact_id)
    if not gone:
        raise web.HTTPNotFound(text="no such fact")
    return web.json_response({"ok": True, **await asyncio.to_thread(_facts_payload)})


async def h_habits(request: web.Request) -> web.Response:
    """One entity's habit — the shape, what keeps undoing it, whether
    anything already does it — off the three ledgers, in one answer."""
    entity_id = str(request.query.get("entity_id") or "").strip()
    if not entity_id:
        return web.json_response(await asyncio.to_thread(
            _habits_payload, time.time()))
    import ha_data  # noqa: PLC0415 — deferred, as every route that needs it

    if not ha_data.ENTITY_ID_RE.match(entity_id):
        raise web.HTTPBadRequest(text="not an entity id")

    def read() -> dict:
        tz, _name = baselines.house_timezone()
        ledger = routines.load()
        return habit_lookup.habit_of(
            entity_id, routine_rows=ledger.get("rows") or [],
            override_rows=override_ledger.load(),
            manual_rows=(manual_ledger.load().get("rows") or []),
            automated=ledger.get("automated") or {}, tz=tz, now=time.time())

    return web.json_response(await asyncio.to_thread(read))


SIMULATE_MAX_DAYS = 28


async def h_simulate(request: web.Request) -> web.Response:
    """When an automation WOULD have fired, and how that squares with what
    a person actually did — a replay, never a call. `simulate_automation`
    is the tool, and this is its one implementation: the same
    `_replay_config` the Replay button and the habit miner use, graded by
    `trials.evaluate` against the person ledger."""
    body = await _json_body(request)
    config = body.get("config")
    if not isinstance(config, dict):
        raise web.HTTPBadRequest(text="config must be an automation object")
    try:
        days = max(1, min(int(body.get("days") or 7), SIMULATE_MAX_DAYS))
    except (TypeError, ValueError):
        days = 7
    now = time.time()
    tz, _name = await asyncio.to_thread(baselines.house_timezone)
    import aiohttp  # noqa: PLC0415

    start = now - days * 86400
    try:
        async with aiohttp.ClientSession() as session:
            replay = await _replay_config(session, config, start, now, tz)
            if replay.get("refused"):
                return web.json_response({"days": days, "replay": replay,
                                          "refused": True})
            watched = sorted(shadow.entities_watched(config))
            history = await shadow.fetch_history(session, watched, start, now) \
                if watched else {}
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"days": days, "refused": True,
                                  "error": f"brAIn could not replay it: {exc}"})
    rows = (await asyncio.to_thread(routines.load)).get("rows") or []
    graded = await asyncio.to_thread(
        trials.evaluate, config, history, rows, start, now, tz, now)
    return web.json_response({"days": days, "replay": replay,
                              "against_you": graded})


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
    payload = await _answer_hypothesis(ts, "confirm")
    if payload is None:
        raise web.HTTPNotFound(text="no such open hypothesis")
    return web.json_response(payload)


async def _answer_hypothesis(ts: int, verb: str,
                             note: str = "") -> dict | None:
    """Confirm or reject a guess, wherever the press came from.

    `_end_finding`'s rule, one store over: the Findings tab's Yes/No and a
    question case's *Do it*/*Wrong* are the same two endings, and a second
    implementation would be one press teaching brAIn two different things.
    None for a guess that is not open, which is a 404 to whoever asked.
    """
    if verb == "confirm":
        settled = await asyncio.to_thread(hypotheses.confirm, ts)
        if not settled:
            return None
        # The statement a guess was built on when it carries one (a
        # curiosity guess's reason), and the claim itself otherwise.
        fact = settled.get("fact") or settled["text"]
        await _submit_memory(fact, source="confirmed",
                             subject=settled.get("subject") or "")
        payload = await asyncio.to_thread(_findings_payload)
        payload["undo"] = undo_store.record("hypothesis", ts=ts,
                                            fact=fact,
                                            fact_source="confirmed")
        return payload

    def settle() -> dict | None:
        done = hypotheses.reject(ts, note=note)
        if done:
            entry = knowledge_store.record_question(done["text"])
            if entry:
                knowledge_store.dismiss_question(entry["ts"])
        return done

    settled = await asyncio.to_thread(settle)
    if not settled:
        return None
    fact = ""
    if note:
        fact = (f'brAIn guessed: "{settled["text"]}". The homeowner says that '
                f"is wrong, because: {note}")
        await _submit_memory(fact, source="correction",
                             subject=settled.get("subject") or "")
    payload = await asyncio.to_thread(_findings_payload)
    # `question` is the ledger entry reject() also wrote, so undo can retire
    # the dead-end record too rather than leaving the claim un-askable.
    payload["undo"] = undo_store.record("hypothesis", ts=ts, fact=fact,
                                        fact_source="correction",
                                        question=settled["text"])
    return payload


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
    payload = await _answer_hypothesis(ts, "reject", note)
    if payload is None:
        raise web.HTTPNotFound(text="no such open hypothesis")
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
    # A line deleted here is a fact somebody wants gone, and the facts
    # store — what most runs read — would otherwise go on asserting it
    # until the minute tick noticed. Now, while the person is looking.
    await asyncio.to_thread(_reconcile_facts, True)
    return web.json_response({"saved": True})


# What an export IS: the durable knowledge, portable. The memory document,
# the findings work list, the settled ledger, the facts ledger and the
# facts store are the five things a rebuilt or second install cannot
# rediscover cheaply — the rest (inbox, hypotheses, questions) is in-flight
# dialogue state that will regenerate, and exporting state that import
# ignores just invites people to expect it back. The facts store came
# last and was missed: it is where a Wrong press's RULE lives, so an export
# without it moved every correction's wording and none of its effect.
EXPORT_VERSION = 1


def _export_payload() -> dict:
    return {
        "brain_export": EXPORT_VERSION,
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "memory_md": _read_shared_memory(),
        "findings": findings_store.list_all(),
        "settled": findings_store.settled_listing(),
        "knowledge_facts": knowledge_store.list_facts(),
        # A key an older import does not read is a key it ignores, which
        # is why this is additive rather than a new EXPORT_VERSION.
        "facts": facts_store.export_rows(),
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
        stored = body.get("facts")
        result["facts"] = facts_store.merge_rows(
            stored if isinstance(stored, list) else [])
        return result

    result = await asyncio.to_thread(fold)
    log.info("import: memory %s, %d finding(s), %d settled, %d fact(s), "
             "%d stored fact(s) and rule(s)",
             result["memory"], result["findings"], result["settled"],
             result["knowledge_facts"], result["facts"])
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
    """Begin a guided sign-in. `mode` picks which one — see `engine.FLOW_MODES`.

    An absent or unknown mode is the account sign-in, which is the one that
    can read your usage; the flow re-checks it, so nothing off the wire
    decides what gets run.
    """
    mode = ""
    if request.can_read_body:
        try:
            mode = str((await request.json()).get("mode") or "")
        except Exception:  # noqa: BLE001 — a body that is not JSON is no mode
            mode = ""
    status = await asyncio.to_thread(
        engine.SETUP_FLOW.start, mode or engine.DEFAULT_FLOW_MODE)
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

# What the chat is told before anybody types: who it is here, which of
# brAIn's own tools answer which question, how an automation is proposed
# rather than written, and — as of the moment the conversation starts —
# what brAIn is already worried about. Short on purpose: it is appended to
# Claude Code's own prompt on every spawn, and a current CLI records it
# once and replays it on every resume, which is why the house half is
# stamped "when this conversation started" and the model is pointed at
# `get_findings`/`get_health` for now. The per-message half is the
# `UserPromptSubmit` hook (`h_chat_context`).
CHAT_IDENTITY = """You are brAIn — the resident intelligence of this home, running inside its Home Assistant. The person you are talking with lives here.

Ask brAIn's own measurements before you guess: what_is_normal (is a reading unusual for this house at this hour), room_physics (how a room gains and loses heat), appliance_status, house_rhythm, door_habits and habits; recall for what brAIn remembers about something; get_findings for what it has already raised and get_health for whether brAIn itself is working.

To make a standing automation, describe it in one sentence and call the brain.intent service with it (call_service, domain "brain", service "intent", data {"sentence": "..."}): brAIn drafts it, replays it over the last month, grades it against what this household actually did and offers it as a card to accept or trial. Do not edit automations.yaml by hand and reload it — that skips the replay, the grade and the protected-entities check. Use simulate_automation on any config before you suggest it."""


def _chat_house_lines() -> list[str]:
    """The house as of now, in a few lines. Never raises; a store that
    cannot be read is a line that is not there."""
    lines: list[str] = []
    try:
        waiting = cases.open_count()
        lines.append(f"{waiting} thing{'s' if waiting != 1 else ''} waiting "
                     "on the household in brAIn's feed")
    except Exception:  # noqa: BLE001 — a feed that could not be read is a
        # line left out, not a count of nothing ("I could not look").
        pass
    try:
        diag = json.loads(DIAGNOSTICS_FILE.read_text(encoding="utf-8"))
        verdict = (diag or {}).get("health") or {}
        if verdict.get("state"):
            lines.append(f"brAIn's own health: {verdict['state']} — "
                         f"{verdict.get('reason') or ''}".rstrip(" —"))
    except (OSError, ValueError, AttributeError):
        # No mirror yet (a fresh install, or a dev checkout): the prompt
        # says nothing about health rather than claiming it is fine.
        pass
    try:
        prof = rhythm.profile()
        for half, word in ((rhythm.WEEKDAY, "weekdays"),
                           (rhythm.WEEKEND, "weekends")):
            part = prof.get(half) or {}
            wake = (part.get("wakes") or {}).get("at")
            settle = (part.get("settles") or {}).get("at")
            if wake or settle:
                bits = [f"up around {wake}" if wake else "",
                        f"settles around {settle}" if settle else ""]
                lines.append(f"on {word} the house is "
                             + " and ".join(b for b in bits if b))
    except Exception:  # noqa: BLE001 — an unmeasured rhythm is no line,
        # never a typed-in hour presented as the house's own.
        pass
    return lines


def _chat_system_prompt(session) -> str:
    """The appended system prompt for one chat spawn (see CHAT_IDENTITY)."""
    lines = _chat_house_lines()
    if not lines:
        return CHAT_IDENTITY
    return (CHAT_IDENTITY + "\n\nWhen this conversation started: "
            + "; ".join(lines) + ". That is a snapshot — ask get_findings "
            "and get_health for how things stand now.")


chat_session.PROMPT_PROVIDER = _chat_system_prompt

# What the context hook may hand one message, and how hard it looks.
CHAT_CONTEXT_CHARS = 1500
CHAT_CONTEXT_ENTITIES = 12
CHAT_CONTEXT_PROMPT_CHARS = 4000
# A friendly name shorter than this is a word that turns up in sentences
# about anything ("tv", "fan") and is not evidence the message is about it.
CHAT_CONTEXT_MIN_NAME = 4


def _subjects_in(text: str) -> tuple[list[str], list[str]]:
    """The entities and areas a message names, off the last checks pass.

    People type "the kitchen light", not `light.kitchen`, so an id written
    out counts and so does a friendly name appearing as whole words. Both
    come off `_NAMES`/`_FACTS_CTX` — the snapshot the pass already read —
    and an entity nothing has seen is not guessed at. Deterministic and
    bounded: this runs synchronously ahead of every chat message.
    """
    low = " ".join(str(text or "").lower().split())
    entities: list[str] = []

    def take(eid: str) -> None:
        if eid not in entities and len(entities) < CHAT_CONTEXT_ENTITIES:
            entities.append(eid)

    for m in _ENTITY_IN_TEXT_RE.finditer(low):
        if m.group(0) in _NAMES:
            take(m.group(0))
    for eid, row in list(_NAMES.items()):
        if len(entities) >= CHAT_CONTEXT_ENTITIES:
            break
        name = str((row or {}).get("name") or "").strip().lower()
        if len(name) < CHAT_CONTEXT_MIN_NAME or name not in low:
            continue
        if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", low):
            take(eid)
    areas = []
    for area_id, name in (_FACTS_CTX.get("areas") or {}).items():
        label = str(name or "").strip().lower()
        if len(label) >= 3 and label in low and re.search(
                r"(?<!\w)" + re.escape(label) + r"(?!\w)", low):
            areas.append(area_id)
    return entities, areas


# Which fact lines each conversation has already been handed, so a fact
# rides into it once. The hook's context is added to the turn and stays in
# the conversation, and `retrieval_block` leads with the house's core facts
# every time — without this, a forty-message chat carries the same standing
# preferences forty times, paid for on every turn after. In memory and
# bounded: a restart hands each conversation its facts once more, which is
# one repeat rather than one per message.
CHAT_CONTEXT_SESSIONS = 32
CHAT_CONTEXT_LINES_KEPT = 400
_CHAT_CONTEXT_GIVEN: "collections.OrderedDict[str, set]" = collections.OrderedDict()


def _not_yet_given(session_id: str, block: str) -> str:
    """``block`` less the fact lines this conversation already has.

    Keyed on the CLI's own session id, which the hook is handed on stdin;
    a message with none (an older CLI) is told everything, which is what
    the hook did before it could tell."""
    sid = str(session_id or "")[:128]
    if not sid or not block:
        return block
    given = _CHAT_CONTEXT_GIVEN.pop(sid, set())
    _CHAT_CONTEXT_GIVEN[sid] = given
    while len(_CHAT_CONTEXT_GIVEN) > CHAT_CONTEXT_SESSIONS:
        _CHAT_CONTEXT_GIVEN.popitem(last=False)
    fresh = [line for line in block.splitlines()
             if line.startswith("- ") and line not in given]
    if len(given) < CHAT_CONTEXT_LINES_KEPT:
        given.update(fresh[:CHAT_CONTEXT_LINES_KEPT - len(given)])
    return (facts_store.MEMORY_HEAD + "\n" + "\n".join(fresh)) if fresh else ""


def _chat_context(prompt: str, session_id: str = "") -> str:
    """What brAIn remembers that bears on one message, or "".

    The facts store's own retrieval (`facts_store.retrieval_block`) over
    the subjects the message names, plus a lexical recall when it names
    none — the same reader every scheduled run is handed, so the chat is
    told what the brief and the cards are told rather than a third copy of
    "what is relevant". Empty is an answer: the hook then adds nothing.
    A line this conversation was already handed is not handed again.
    """
    text = str(prompt or "")[:CHAT_CONTEXT_PROMPT_CHARS]
    if not text.strip():
        return ""
    entities, areas = _subjects_in(text)
    try:
        block = facts_store.retrieval_block(
            entities=entities, areas=areas, query=text,
            limit_chars=CHAT_CONTEXT_CHARS)
    except Exception as exc:  # noqa: BLE001 — a store that will not read
        log.debug("chat context retrieval failed: %s", exc)
        block = ""
    if not entities and not areas:
        try:
            extra = [r for r in facts_store.recall(query=text, limit=6)
                     if r.get("text") and r["text"] not in block]
        except Exception:  # noqa: BLE001
            extra = []
        if extra:
            more = "\n".join(f"- {r['text']}" for r in extra)
            block = (block + "\n" + more) if block else (
                facts_store.MEMORY_HEAD + "\n" + more)
    if not block.strip():
        return ""
    if len(block) > CHAT_CONTEXT_CHARS:
        block = block[:CHAT_CONTEXT_CHARS].rsplit("\n", 1)[0]
    block = _not_yet_given(session_id, block)
    if not block.strip():
        return ""
    return ("What brAIn remembers that bears on this message — from its own "
            "facts store, so check anything that matters against the house "
            "before you rely on it:\n" + block)


async def h_chat_context(request: web.Request) -> web.Response:
    """The chat's `UserPromptSubmit` hook asks here, once per message.

    One implementation of retrieval, on the side that has the registry the
    last checks pass saw (`scripts/brain-chat-context.py` is a few lines of
    plumbing). Answers ``{"context": ""}`` rather than an error for
    anything it cannot use, because the hook turns any failure into
    nothing and a message must never wait on this.
    """
    body = await _json_body(request)
    text = await asyncio.to_thread(_chat_context, str(body.get("prompt") or ""),
                                   str(body.get("session_id") or ""))
    return web.json_response({"context": text})


async def h_own(request: web.Request) -> web.Response:
    """Hand files under /config to the claude user — `brain own` and the
    edit hook ask here, so nobody is ever asked to run sudo chown.

    Loopback only, read off the socket (`ownership.from_loopback`): the
    panel is root, and an ingress page has no business asking it to chown
    anything. What may be handed over, and how it is checked, is
    `ownership.own`'s; every path gets its own answer.
    """
    if not ownership.from_loopback(request):
        return web.json_response({"error": ownership.LOOPBACK_ONLY},
                                 status=403)
    body = await _json_body(request)
    try:
        answer = await asyncio.to_thread(ownership.own, body.get("paths"),
                                         bool(body.get("recursive")))
    except ownership.Refused as exc:
        return web.json_response({"error": str(exc)}, status=exc.status)
    return web.json_response(answer)


# A file the chat cannot write is never the person's problem to fix.
CHAT_IDENTITY += "\n\n" + ownership.AGENT_RULE


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
        # The pill and the sentence, from the one function that decides
        # them — a record for an engine-store row, and for the rest the
        # held session or the flag its transcript kept across a restart.
        row["row_state"] = registry.row_state(
            row["id"], view_only=bool(row.get("view_only")))
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

    What it does leave behind is the handoff record and its transcript,
    which Claude Code writes as it goes, and `chat_session.pick_adopted`
    reads both: the conversation the chat handed over, or the one the
    terminal has written to since — never a conversation a chat session
    in the registry is already holding. "The most recently written" was the
    whole rule once, and a background chat that was still answering IS the
    most recently written, so switching back resumed that chat a second
    time beside the session holding it. The consolidator, voice and the
    automation listener write here too, which is why only a person's own
    conversations are candidates at all.

    It goes through the REGISTRY (`open`), so the cap is applied and a
    conversation already held is attached rather than spawned twice, and
    nothing is stopped to make the switch: a chat mid-answer goes on
    answering in the background, which is why this no longer refuses one.
    The terminal's Claude is left completely alone — it is somebody's shell
    and killing it is not ours to do.
    """
    registry = _chat_registry()
    attached = _chat()
    held_elsewhere = {s.session_id for s in registry.sessions()
                      if s.session_id and s is not attached}
    recent = await asyncio.to_thread(
        conversations.listing, chat_session.WORK_DIR, 10, ("you",))
    handoff = await asyncio.to_thread(chat_session.read_handoff)
    chosen = chat_session.pick_adopted(recent, handoff, held_elsewhere)
    if (chosen is not None and chosen["id"] == attached.session_id
            and handoff.get("session_id") == chosen["id"]
            and float(chosen.get("modified") or 0) > float(handoff.get("ts") or 0)
            and not attached.alive() and attached.state != "busy"):
        # The ordinary round trip: the chat handed this conversation to the
        # terminal (stopping its own process, so it is still the one on
        # screen) and the terminal carried it on. The id matches, which
        # read as "nothing to take up" — and the pane went on showing the
        # scrollback from before the handoff, with the terminal's turns
        # missing. Nothing is running here to lose, so re-read it.
        replay = await asyncio.to_thread(
            conversations.transcript, chat_session.WORK_DIR, chosen["id"])
        try:
            out = await attached.resume(chosen["id"], replay)
        except ValueError as exc:
            raise web.HTTPBadRequest(reason=_refusal(exc))
        except RuntimeError as exc:
            raise web.HTTPConflict(reason=_refusal(exc))
        return web.json_response({"ok": True, "adopted": True,
                                  "session_id": out.get("session_id") or chosen["id"],
                                  "title": chosen["title"]})
    if chosen is None or chosen["id"] == attached.session_id:
        # Already the same conversation (or there is nothing to take up):
        # switching is then just a change of renderer, which is the point.
        return web.json_response({"ok": True, "adopted": False,
                                  "session_id": attached.session_id})
    replay = []
    if registry.get(chosen["id"]) is None:
        replay = await asyncio.to_thread(
            conversations.transcript, chat_session.WORK_DIR, chosen["id"])
    try:
        out = await registry.open(chosen["id"], replay)
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=_refusal(exc))
    except RuntimeError as exc:
        # The cap, and only the cap: every live chat is busy and there is
        # no idle one to pause. Its own sentence says so.
        raise web.HTTPConflict(reason=_refusal(exc))
    return web.json_response({"ok": True, "adopted": True,
                              "session_id": out.get("session_id") or chosen["id"],
                              "title": chosen["title"]})


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
        out = await registry.open(session_id, replay)
    except ValueError as exc:
        raise web.HTTPBadRequest(reason=str(exc))
    except RuntimeError as exc:
        raise web.HTTPConflict(reason=_refusal(exc))
    # What the composer says now that this is the attached conversation:
    # `resumed: false` used to be a toast that vanished, and the row it was
    # about went on looking like any other. The state is the same
    # derivation every row gets, so the composer and the rail agree.
    out["row_state"] = registry.composer_state()
    return web.json_response(out)


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
            "max_sessions": chat_session.max_sessions(),
            # What sending into THIS conversation will do, for the line
            # above the message box — derived by the same function the
            # rows use, so the composer never disagrees with the rail.
            "composer_state": chat_session.registry().state_of(session)}


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
    app.router.add_delete("/api/insight/{id}", h_delete_insight)
    app.router.add_put("/api/insight/{id}", h_rename_insight)
    app.router.add_post("/api/insight/{id}/refine", h_insight_refine)
    app.router.add_delete("/api/card/{id}", h_delete_card)
    app.router.add_put("/api/card/{id}/tags", h_card_tags_put)
    app.router.add_get("/api/findings", h_findings)
    # The feed. One object over the four stores, and three endings on it.
    app.router.add_get("/api/cases", h_cases)
    app.router.add_post("/api/case/{id}/{verb}", h_case_verb)
    app.router.add_get("/api/checks", h_checks)
    app.router.add_post("/api/checks/run", h_checks_run)
    app.router.add_get("/api/doctor/deep", h_doctor_deep_get)
    app.router.add_post("/api/doctor/deep", h_doctor_deep_start)
    app.router.add_get("/api/doctor/rehearse", h_rehearse_get)
    app.router.add_post("/api/doctor/rehearse", h_rehearse_start)
    app.router.add_post("/api/doctor/rehearse/sweep", h_rehearse_sweep)
    app.router.add_get("/api/diagnostics", h_diagnostics)
    app.router.add_get("/api/reports", h_reports_list)
    # The two fixed names before the {name} pattern, which would otherwise
    # answer them with a 405.
    app.router.add_post("/api/reports/copy", h_reports_copy)
    app.router.add_post("/api/reports/run", h_reports_run)
    app.router.add_get("/api/reports/{name}", h_report_get)
    app.router.add_delete("/api/reports/{name}", h_report_delete)
    app.router.add_get("/api/capture", h_capture_list)
    app.router.add_get("/api/capture/{run_id}", h_capture_get)
    app.router.add_post("/api/capture/{run_id}/export", h_capture_export)
    app.router.add_delete("/api/capture/{run_id}", h_capture_delete)
    app.router.add_get("/api/resident/outcomes", h_resident_outcomes)
    app.router.add_get("/api/resident/eval", h_resident_eval_get)
    app.router.add_post("/api/resident/eval", h_resident_eval_start)
    app.router.add_get("/api/baselines", h_baselines)
    app.router.add_get("/api/world", h_world)
    app.router.add_post("/api/world/run", h_world_run)
    app.router.add_get("/api/situation", h_situation)
    app.router.add_get("/api/occasions", h_occasions)
    app.router.add_post("/api/occasions/run", h_occasions_run)
    app.router.add_post("/api/baselines/run", h_baselines_run)
    app.router.add_get("/api/curiosity", h_curiosity)
    app.router.add_post("/api/curiosity/ask", h_curiosity_ask)
    app.router.add_get("/api/appliances", h_appliances)
    # The fixed prefix before the {name} pattern, which would otherwise
    # answer the aggregate with a 404 for a store called "".
    app.router.add_get("/api/knowledge/house", h_house)
    app.router.add_get("/api/knowledge/house/{name}", h_house_store)
    # brAIn's own knowledge cards. Not insights: no schedule, no
    # category, and they never appear on the Insights tab.
    app.router.add_get("/api/knowledge/cards", h_knowledge_cards)
    app.router.add_get("/api/knowledge/card/{card_id}", h_knowledge_card)
    app.router.add_post("/api/knowledge/card/{card_id}/refresh",
                        h_knowledge_card_refresh)
    app.router.add_get("/api/weekly", h_weekly)
    app.router.add_post("/api/weekly/run", h_weekly_run)
    app.router.add_get("/api/activity", h_activity)
    app.router.add_get("/api/activity/entity/{entity_id}", h_activity_entity)
    app.router.add_post("/api/activity/summary", h_activity_summary)
    app.router.add_post("/api/finding/{ts}/fix", h_finding_fix)
    # The three halves of the plan-first fix. Before the {verb} catch-all
    # for snooze's reason: none of them is an ending, so none may fall
    # into the table of them.
    app.router.add_post("/api/finding/{ts}/apply", h_finding_apply)
    app.router.add_post("/api/finding/{ts}/cancel", h_finding_cancel)
    app.router.add_post("/api/finding/{ts}/unfix", h_finding_unfix)
    app.router.add_post("/api/finding/{ts}/snooze", h_finding_snooze)
    app.router.add_post("/api/finding/{ts}/discuss", h_finding_discuss)
    # Not an ending either: the chat's sentence onto the card. Before the
    # {verb} catch-all for snooze's reason.
    app.router.add_post("/api/finding/{ts}/advice", h_finding_advice)
    # The producer, not the row. Registered before /api/finding/{ts}/…
    # only for tidiness; the path does not collide.
    app.router.add_post("/api/findings/mute", h_findings_mute)
    app.router.add_post("/api/findings/unmute", h_findings_unmute)
    # Before the {ts} pattern, which would otherwise swallow it.
    app.router.add_get("/api/proposals", h_proposals)
    app.router.add_get("/api/playbook/{ts}/rehearsal", h_playbook_rehearsal)
    app.router.add_post("/api/proposal/{ts}/trial", h_proposal_trial)
    app.router.add_post("/api/intent/{ts}/remove", h_intent_remove)
    app.router.add_get("/api/scenes/areas", h_scene_areas)
    app.router.add_post("/api/scenes/design", h_scene_design)
    app.router.add_post("/api/proposal/{ts}/{verb}", h_proposal_decide)
    app.router.add_post("/api/findings/unsettle", h_finding_unsettle)
    app.router.add_post("/api/undo/{token}", h_undo)
    # Before the {verb} catch-all: aiohttp matches in registration order,
    # and "recheck" is not an ending, so it must not fall into the table
    # of them.
    app.router.add_post("/api/finding/{ts}/recheck", h_finding_recheck)
    app.router.add_post("/api/finding/{ts}/elevate", h_finding_elevate)
    # Before the generic {verb} route, like snooze and discuss: this ending
    # has to create the item before the row it reads is deleted, which the
    # verb table cannot express.
    app.router.add_post("/api/finding/{ts}/todo", h_finding_todo)
    app.router.add_post("/api/finding/{ts}/{verb}", h_finding_verb)
    app.router.add_delete("/api/finding/{ts}", h_finding_delete)
    app.router.add_get("/api/todo", h_todo)
    app.router.add_post("/api/todo", h_todo_add)
    app.router.add_post("/api/todo/{id}/done", h_todo_done)
    app.router.add_post("/api/todo/{id}/reopen", h_todo_reopen)
    app.router.add_delete("/api/todo/{id}", h_todo_delete)
    app.router.add_get("/api/insight/{id}/live", h_insight_live)
    app.router.add_get("/api/insight/{id}/history", h_history_list)
    app.router.add_get("/api/insight/{id}/history/{ts}", h_history_get)
    app.router.add_delete("/api/insight/{id}/history/{ts}", h_history_delete)
    app.router.add_get("/api/prompts", h_prompts)
    app.router.add_get("/api/prompt/{id}/preview", h_prompt_preview)
    app.router.add_put("/api/prompt/{id}", h_prompt_put)
    app.router.add_delete("/api/prompt/{id}", h_prompt_delete)
    app.router.add_post("/api/user_category", h_user_category_create)
    app.router.add_put("/api/user_category/{id}", h_user_category_put)
    app.router.add_delete("/api/user_category/{id}", h_user_category_delete)
    app.router.add_get("/api/insight/{id}/feedback", h_feedback_list)
    app.router.add_post("/api/insight/{id}/feedback", h_feedback_add)
    app.router.add_delete("/api/insight/{id}/feedback/{ts}", h_feedback_delete)
    app.router.add_get("/api/card_info", h_card_info)
    app.router.add_get("/api/dashboards", h_dashboards)
    app.router.add_post("/api/card/{id}/dashboard", h_card_to_dashboard)
    app.router.add_get("/api/onboarding", h_onboarding)
    app.router.add_get("/api/onboarding/notify", h_onboarding_notify)
    app.router.add_post("/api/onboarding/notify", h_onboarding_notify_save)
    app.router.add_post("/api/onboarding/learn", h_onboarding_learn)
    app.router.add_post("/api/onboarding/recommend", h_onboarding_recommend)
    app.router.add_post("/api/onboarding/accept", h_onboarding_accept)
    app.router.add_post("/api/onboarding/skip", h_onboarding_skip)
    app.router.add_post("/api/onboarding/reset", h_onboarding_reset)
    app.router.add_get("/api/ideas", h_ideas)
    app.router.add_post("/api/ideas/run", h_ideas_run)
    app.router.add_post("/api/idea/{idea_id}/accept", h_idea_accept)
    app.router.add_post("/api/idea/{idea_id}/dismiss", h_idea_dismiss)
    app.router.add_get("/api/knowledge", h_knowledge)
    app.router.add_get("/api/facts", h_facts)
    app.router.add_get("/api/facts/browse", h_facts_browse)
    app.router.add_post("/api/fact/{id}/forget", h_fact_forget)
    app.router.add_get("/api/habits", h_habits)
    app.router.add_post("/api/simulate", h_simulate)
    app.router.add_post("/api/hypothesis/{ts}/confirm", h_hypothesis_confirm)
    app.router.add_post("/api/hypothesis/{ts}/reject", h_hypothesis_reject)
    app.router.add_put("/api/memory", h_memory_put)
    app.router.add_post("/api/memory/consolidate", h_memory_consolidate)
    app.router.add_get("/api/memory/state", h_memory_state)
    app.router.add_get("/api/memory/export", h_memory_export)
    app.router.add_post("/api/memory/import", h_memory_import)
    app.router.add_post("/api/knowledge/fact", h_knowledge_fact_add)
    app.router.add_delete("/api/memory/inbox/{id}", h_inbox_delete)
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
    app.router.add_post("/api/chat/context", h_chat_context)
    app.router.add_post("/api/own", h_own)
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
    # ESPHome devices: their YAML here, their builds on the dashboard.
    esphome.setup(app)
    # Music Assistant: players, providers, queues and settings, over its API.
    music_assistant.setup(app)
    # Home Assistant's own maintainer: tidy, upgrades, health, the book.
    _maint_routes(app)

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
        # ...and the to-do mirror beside it, for the same reason: a boot
        # must not serve last week's list to the To-do app.
        await asyncio.to_thread(todo_store.publish_state)
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
        # Every failed run of any kind becomes one readable file: hooked on
        # the journal so a new run path is covered by having recorded itself.
        journal.on_record(_journal_report_listener)
        # And every run that spent something tells the usage tracker, which
        # is asking on a 30-minute heartbeat rather than every 5 minutes.
        journal.on_record(_journal_usage_listener)
        # And a usage limit met by any run holds the scheduled cards.
        journal.on_record(_journal_rate_listener)
        # The work queue belongs to the loop the worker runs on, and it
        # is a module global — so the first loop to touch it owns it for
        # the life of the process. In the add-on that is one loop and one
        # app and the distinction never arises; anywhere that builds a
        # second app (a test, the demo panel) the second worker's very
        # first `get()` raises "bound to a different event loop" into a
        # task nobody awaits, which surfaces as an unraisable exception
        # in an unrelated teardown. Rebinding here costs one object and
        # keeps the queue an implementation detail of the running app.
        _rebind_queue()
        _rebind_resident_queue()
        # The panel's own four files, read into memory before the first
        # request rather than on it — off the loop, where every read of them
        # now happens.
        await asyncio.to_thread(_warm_static)
        # Waiters from a loop that has gone (a test, a second app) can
        # never be woken; the run queue drops them, `_rebind_queue`'s rule.
        run_queue.QUEUE.reset()
        # Every long-lived loop is supervised: a done-callback says at
        # warning when one stops, and `/api/diagnostics` carries whether
        # each is alive and when the ones that beat last went round —
        # which `health.problems` reads. The stall windows are several of
        # each loop's own ticks, plus a pass's own length.
        app["worker"] = _supervise("worker", _worker())
        app["scheduler"] = _supervise("scheduler", _scheduler(),
                                      stall_after_s=600)
        app["checks"] = _supervise("checks", _checks_loop(),
                                   stall_after_s=CHECKS_FIRST_DELAY_S + 3600)
        app["baselines"] = _supervise("baselines", _baseline_loop(),
                                      stall_after_s=BASELINE_FIRST_DELAY_S
                                      + 3 * 3600)
        app["notify_flush"] = _supervise("notify_flush", _notify_flush_loop())
        app["brief"] = _supervise("brief", _brief_loop())
        app["evening"] = _supervise("evening", _evening_loop())
        app["healing"] = _supervise("healing", _heal_loop())
        app["weekly"] = _supervise("weekly", _weekly_loop())
        app["maintainer"] = _supervise("maintainer", _maint_loop())
        app["requests"] = _supervise("requests", _requests_loop())
        # The first thing in brAIn that is watched rather than polled, and
        # the loop that reads it. The bus files nothing and asks nothing —
        # its only output is a signal on the queue — and `_resident_loop`
        # is what decides whether any of it is worth anybody's attention.
        # On a machine that is not inside Home Assistant the bus says so
        # once and stays idle, which is what lets the panel come up on a
        # dev checkout at all.
        global EVENT_BUS
        EVENT_BUS = eventbus.EventBus(
            _resident_offer, on_event=_note_safety,
            known_ids=_known_entity_ids,
            # A callable, not a snapshot: a fresh install has no
            # measured night for a fortnight, and a bus that froze the
            # boot answer would use the fallback 23-6 for ever on
            # exactly the house that has since measured its own.
            rhythm_payload=rhythm.profile,
            # The HOUSE's clock. Left unset, `is_odd_hour` read the UTC
            # hour against the house's local night window, so on a house
            # in New York a person moving at 20:00 was "the small hours"
            # and one at 03:00 was not.
            tz=baselines.house_timezone()[0],
            # Binary sensors a confident entity reading made safety
            # sensors. It can only add: a device class wins whatever this
            # says (`signals.RegistryContext.safety_class_of`).
            safety_roles=_world_safety_roles)
        await EVENT_BUS.start()
        app["resident"] = _supervise("resident", _resident_loop())
        # What the house is doing now: a frame every few minutes, a cheap
        # sentence only when it moved.
        app["situation"] = _supervise("situation", _situation_loop())
        if addon_options.available():
            app["options"] = _supervise("options", _options_poller())
        if engine.get_auth():
            start_auth_check()

    async def on_cleanup(app: web.Application) -> None:
        # The chat session is a child process of ours; leaving it running
        # after the panel goes down orphans a Claude that nothing will ever
        # read from again.
        await chat_session.registry().stop_all()
        if EVENT_BUS is not None:
            # Waited out rather than cancelled and forgotten: the pump is
            # inside `async with ws`, and dropping the task would close the
            # socket under a read that is still in it.
            await EVENT_BUS.stop()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    web.run_app(make_app(), host=BIND_HOST, port=BIND_PORT, print=None,
                access_log_class=QuietAccessLogger)
