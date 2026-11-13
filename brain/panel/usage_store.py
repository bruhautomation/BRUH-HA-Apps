"""Token-usage tracking and session budgeting for brAIn.

Every Claude invocation's token count is recorded to one JSON file so the
add-on knows how much of the user's 5-hour subscription session window it
has consumed. The ⚙ settings dialog sets a budget (a percentage of the
session); once it's reached, scheduled generation pauses until the window
rolls over. Manual clicks always work.

Two signals, best first:
  1. Real account utilization — the usage-limits tracker writes
     /config/.brain/usage_limits.json with the ACTUAL utilization
     percentages from the Anthropic API (all Claude use on the account,
     not just Insights). Fresh data wins.
  2. Local estimate — otherwise we sum the tokens Insights itself spent in
     the trailing 5 hours against a rough per-plan session allowance.
     The allowances are honest ballparks (Anthropic doesn't publish exact
     numbers and they vary with load); they exist so the slider means
     something even without the tracker.

The tracker also reports the account's SEVEN-DAY window, which the panel
shows beside the session because that is the limit that usually ends
someone's week. It is reported only, never budgeted against: pausing
generation on a weekly number would pause it for days. There is no
estimate fallback for it — a made-up weekly percentage is worse than
none, so without the tracker it is simply absent.

File shape: {"runs": [{"ts": 1752…, "id": "energy", "tokens": 41230}, …]}
(pruned to the last 24h; atomic tmp+replace like insight storage).

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os
import time

import atomic_write

USAGE_FILE = os.environ.get("BRAIN_USAGE_FILE", "/data/usage.json")

# Written by brAIn's usage-limits tracker (real Anthropic account
# utilization). Entirely optional — missing/stale files are ignored.
LIMITS_FILE = os.environ.get(
    "BRAIN_USAGE_LIMITS", "/config/.brain/usage_limits.json")
# Real utilization older than this is considered stale (tracker not running)
LIMITS_MAX_AGE_S = 2 * 3600

# The tracker polls on a slow heartbeat and asks immediately when brAIn
# has just finished a Claude run — see `nudge`. The path is spelled here
# and in usage-limits-tracker.py, which is a separate process that imports
# nothing from the panel, so `tests/test_usage_nudge.py` reads both ends:
# a rename that goes silent on one side is the failure `AUTH_BACKUP_FILE`
# already had once.
NUDGE_FILE = os.environ.get("BRAIN_USAGE_NUDGE", "/data/usage-nudge")

SESSION_HOURS = 5.0
KEEP_HOURS = 24.0
DEFAULT_BUDGET = 25

# Rough per-plan token allowances for one 5-hour session window. Estimates
# only — used when real account utilization isn't available.
PLAN_SESSION_TOKENS = {
    "pro": 300_000,
    "max5": 1_500_000,
    "max20": 6_000_000,
}
PLAN_LABELS = {
    "pro": "Claude Pro",
    "max5": "Claude Max (5×)",
    "max20": "Claude Max (20×)",
}


def _load_runs() -> list[dict]:
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        runs = data.get("runs")
        if isinstance(runs, list):
            return [r for r in runs
                    if isinstance(r, dict) and isinstance(r.get("ts"), (int, float))
                    and isinstance(r.get("tokens"), int)]
    except (OSError, ValueError, AttributeError):
        # An absent or corrupt usage file reads as no runs, which is what a
        # fresh install has.
        pass
    return []


def _write_runs(runs: list[dict]) -> None:
    atomic_write.write_json(USAGE_FILE, {"runs": runs})


def record_run(tokens: int, insight_id: str = "", now: float | None = None) -> None:
    """Record one Claude invocation's token count (best-effort; never raises)."""
    if not isinstance(tokens, int) or tokens <= 0:
        return
    now = time.time() if now is None else now
    try:
        runs = _load_runs()
        runs.append({"ts": int(now), "id": str(insight_id)[:64], "tokens": tokens})
        cutoff = now - KEEP_HOURS * 3600
        runs = [r for r in runs if r["ts"] >= cutoff]
        _write_runs(runs)
    except OSError:
        # Usage accounting must never fail the run it is accounting for.
        pass


def tokens_from_meta(meta: dict) -> int:
    """Countable tokens out of a claude -p result envelope's usage block.

    Cache reads are excluded — they are nearly free against the session
    limit; input, cache creation, and output are what burn it.
    """
    usage = meta.get("usage") if isinstance(meta, dict) else None
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key in ("input_tokens", "cache_creation_input_tokens", "output_tokens"):
        val = usage.get(key)
        if isinstance(val, int) and val > 0:
            total += val
    return total


def split_from_meta(meta: dict) -> dict:
    """One run's token counts, split the way a person reads a bill.

    ``total`` is whatever ``tokens_from_meta`` counts and nothing else, so
    the number on a card, the number in the log, and the number the budget
    is measured against cannot disagree — three readings of one run that
    differ is how a usage figure stops being believed.

    ``cached`` is reported and deliberately left out of ``total``: a cache
    read is nearly free against the session limit, and folding it in would
    inflate every number on screen for tokens that were never charged.
    """
    usage = meta.get("usage") if isinstance(meta, dict) else None
    usage = usage if isinstance(usage, dict) else {}

    def count(key: str) -> int:
        val = usage.get(key)
        return val if isinstance(val, int) and val > 0 else 0

    return {
        # Cache creation is an input cost — it is the prompt, written down.
        "input": count("input_tokens") + count("cache_creation_input_tokens"),
        "output": count("output_tokens"),
        "cached": count("cache_read_input_tokens"),
        "total": tokens_from_meta(meta),
    }


def window_tokens(hours: float = SESSION_HOURS, now: float | None = None) -> int:
    """Tokens Insights spent in the trailing window."""
    now = time.time() if now is None else now
    cutoff = now - hours * 3600
    return sum(r["tokens"] for r in _load_runs() if r["ts"] >= cutoff)


# Where the session went, in the household's words (#880). The ledger keeps
# one id per run — a card's, a job's, a shell run's journal source — and an
# id is nothing a person reads, so the list is the sum under these names,
# with each one's share. ONE table: every id a writer records is named here,
# exactly or by its prefix, and `python3 usage_store.py` greps the tree for
# every writer and fails on one that is not (the `__main__` below). Chats
# are not in it: a chat turn is never booked into this ledger, and the
# note under the list says so rather than showing a row that cannot fill.
SPEND_GROUPS = {
    "checks": "Watching the house",
    "cards": "Insight cards and reports",
    "dashboard": "Dashboard requests",
    "voice": "Voice",
    "automations": "Automations",
    "memory": "Memory and learning",
    "fixes": "Fixes",
    "setup": "Setup and self-tests",
    "other": "Other brAIn work",
}
SPEND_IDS = {
    # The Resident and what it reads the house with.
    "resident-look": "checks", "resident-investigate": "checks",
    "resident-escalate": "checks", "resident-reflect": "checks",
    "world-model": "checks", "situation": "checks", "occasions": "checks",
    # Cards, and what is said about them.
    "ideas": "cards", "deep-review": "cards",
    # Shell runs, by their journal source (`journal.record_shell`,
    # `brain_run_journal.py record`, booked by `server._book_shell_usage`).
    "voice": "voice",
    "task": "automations",
    "morph": "dashboard",
    "memory": "memory", "memory_extract": "memory", "study": "memory",
    # The assistant's nightly reflection on how it should be.
    "presence-reflect": "memory",
    # Setting up, and brAIn testing itself.
    "onboarding": "setup", "eval-first-look": "setup", "devloop": "setup",
    "doctor-snapshot": "setup", "doctor-analyst": "setup",
    "doctor-fixer": "setup", "doctor-rehearsal": "setup",
    # `_book_shell_usage`'s name for a shell row that carried no source.
    "shell": "other",
}
SPEND_PREFIXES = (
    ("followup-", "checks"),
    ("milestone-", "cards"),
    # A card somebody made (`user_categories.ID_PREFIX`) or asked for.
    ("user-", "cards"), ("custom-", "cards"),
    ("fix-", "fixes"), ("plan-", "fixes"),
)


def _card_ids() -> frozenset:
    try:
        import categories  # noqa: PLC0415 — the shipped cards, read lazily
        return frozenset(c.get("id") for c in categories.CATEGORIES)
    except Exception:  # noqa: BLE001 — without the catalogue a card is other
        return frozenset()


def spend_group(run_id: str) -> str:
    """Which household name a run's id is spent under: exactly, by prefix,
    or a shipped card's own id; "other" for an id no writer records today
    (one left in the ledger by an older release)."""
    rid = str(run_id or "")
    if rid in SPEND_IDS:
        return SPEND_IDS[rid]
    for prefix, group in SPEND_PREFIXES:
        if rid.startswith(prefix):
            return group
    return "cards" if rid in _card_ids() else "other"


def _breakdown(runs: list[dict]) -> list[dict]:
    """Where the window's tokens went, by household name, biggest first.

    Rows are ``{"id", "label", "tokens", "runs", "share"}``: ``id`` is the
    group's key, never a run's, and ``share`` the whole percent of what the
    list adds up to (one total, so the shares are of the same thing). Every
    run lands in a group, so nothing is folded away.
    """
    totals: dict[str, dict] = {}
    for run in runs:
        key = spend_group(run.get("id"))
        row = totals.setdefault(key, {"id": key, "label": SPEND_GROUPS[key],
                                      "tokens": 0, "runs": 0})
        row["tokens"] += run["tokens"]
        row["runs"] += 1
    ranked = sorted(totals.values(), key=lambda r: -r["tokens"])
    whole = sum(r["tokens"] for r in ranked) or 1
    for row in ranked:
        row["share"] = round(100 * row["tokens"] / whole)
    return ranked


def window_breakdown(hours: float = SESSION_HOURS,
                     now: float | None = None) -> list[dict]:
    """What spent the trailing window, biggest first."""
    now = time.time() if now is None else now
    cutoff = now - hours * 3600
    return _breakdown([r for r in _load_runs() if r["ts"] >= cutoff])


def _parse_iso_epoch(value) -> int | None:
    """ISO timestamp ("…+00:00" / "…Z") → epoch seconds, else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        import datetime
        return int(datetime.datetime.fromisoformat(
            value.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _tracker_file() -> dict | None:
    """The tracker's file as written, fresh or not — or None if unreadable."""
    try:
        with open(LIMITS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def nudge() -> bool:
    """Tell the tracker the account's usage has just moved. Never raises.

    The figure changes when a run spends tokens and at no other time, so a
    finished run is the moment worth one request — and it is also the only
    moment the credential is certain to be usable, because the CLI mints
    the next access token from the refresh token as part of a run and
    nothing else on the box can. A quiet house therefore has nothing to
    ask with, which is why the heartbeat is slow and this exists.

    It is a file's mtime rather than a signal: the tracker is a separate
    process started by run.sh, both ends run as root, and a pid to signal
    is one more thing that can be stale. Content is deliberately not read
    — the only question is "has anything happened since I last asked".

    Best-effort by construction. This is called from the journal listener,
    which may not fail the run it is being told about.
    """
    try:
        os.makedirs(os.path.dirname(NUDGE_FILE) or ".", exist_ok=True)
        with open(NUDGE_FILE, "w") as fh:
            fh.write("")
        return True
    except OSError:
        # A nudge that could not be written costs freshness until the next
        # heartbeat, which is the state this was in before it existed.
        return False


def nudged_at() -> float:
    """When the last nudge landed, or 0.0. Never raises."""
    try:
        return os.path.getmtime(NUDGE_FILE)
    except OSError:
        return 0.0


def _fresh_payload() -> dict | None:
    """The whole tracker file, only when the data is fresh.

    A file with no ``updated_at`` at all is **not** fresh. It used to be:
    the staleness test was skipped whenever the stamp was missing or not a
    string, so a file holding numbers and no timestamp read as current
    forever. The tracker always writes one on a real reading, so an absent
    stamp means the file is something other than a reading — and treating
    that as live is the failure this whole module exists to avoid.
    """
    data = _tracker_file()
    if data is None or data.get("error"):
        return None
    stamp = _parse_iso_epoch(data.get("updated_at"))
    if stamp is None or time.time() - stamp > LIMITS_MAX_AGE_S:
        return None
    return data


# The tracker's own codes that mean "no figure, and nobody has anything to
# do about it". They are still reported on the pill and in the popover —
# the number really is brAIn's local estimate and saying so is the whole
# point of `limits_problem` — but they are not the ADD-ON being degraded,
# which is a different question with a different reader.
#
# `oauth_token_awaiting_refresh` is the one this was written for. It says
# in as many words that nothing is wrong with the sign-in and that signing
# in again will not help: Claude Code mints the next access token itself
# on its next run. It is deliberately absent from the tracker's own
# `AUTH_PROBLEMS` for exactly that reason, and health was the one reader
# that had not been told — so `sensor.brain_health` went `degraded`, HA's
# Repairs raised `health_degraded`, and `reports.file_incident` wrote a
# problem file, several hours out of every day, about a credential doing
# what credentials do. A verdict that fires on a healthy install is the
# check catalog's own first rule, one module over.
#
# `api_key_has_no_usage_limits` is here for the opposite reason: it can
# never clear, because an API key has no subscription window to report.
# Permanently degraded over an account that is working is worse noise than
# the daily kind. And `http_429` is the endpoint's limit rather than the
# account's — the tracker answers it with a backoff ladder built for it,
# which is a refusal doing its job.
#
# Everything else stays a problem, because everything else names something
# a person can do: sign in, re-run the account sign-in for the scope, or
# find out why the tracker has written nothing at all.
#
# `oauth_renewal_rate_limited` is the same claim as `http_429` about the
# OTHER endpoint the tracker calls: Anthropic is rate limiting the renewal
# of the account credential, and the tracker waits on a ladder of its own
# and asks again by itself.
NEEDS_NOTHING = ("oauth_token_awaiting_refresh", "api_key_has_no_usage_limits",
                 "http_429", "oauth_renewal_rate_limited")

# ...and the one whose "nothing to do" has a shelf life. The tracker
# renews the account credential itself now, on every pass, so "between
# refreshes" is a state that lasts a poll or two — and one that has lasted
# longer is the tracker unable to renew for hours, which is something a
# person needs to hear about. This is the report that prompted it: four
# usage sensors unavailable for a day, and the only thing anywhere about it
# was a verdict saying nothing was wrong. Three hours is six ordinary
# polls, or one renewal that failed and five more chances to make it.
#
# The 429 ladder is deliberately not on this table, and stays needs-nothing
# at any age: its rungs are hours long by design, it keeps asking on its own
# (every rung at most the tracker's RETRY_AFTER_MAX_S, a nudge never
# shortening one), and turning a rate limit into a fault on the health
# sensor is a decision a person makes, not one a clock makes. An API key
# can never clear, so it gets no clock either.
STUCK_AFTER = {"oauth_token_awaiting_refresh": 3 * 3600}

# What a stuck code says once it has outlived its shelf life. It is the
# reader's sentence because the tracker wrote its gloss when it was true.
STUCK_DETAIL = {
    "oauth_token_awaiting_refresh": (
        "It has been the answer for {hours} hours now, which is longer than "
        "a renewal should take — the add-on log says what the tracker ran "
        "into."),
}

# ...and the needs-nothing codes whose SENTENCE goes out of date while the
# verdict does not. A house sat on `http_429` for thirty hours with the
# figure an estimate the whole time, and the only words anywhere said it
# would lift on its own — true of an evening, untrue of a day and a half.
# Past this the verdict is unchanged and the words say how long it has
# stood (`overdue` on the payload, for the popover and the brief).
OVERDUE_AFTER = {"http_429": 24 * 3600,
                 "oauth_renewal_rate_limited": 24 * 3600}
OVERDUE_DETAIL = {
    "oauth_renewal_rate_limited": (
        "Anthropic has refused to renew the sign-in's access token for "
        "{hours} hours now, so the usage figure is brAIn's own estimate. "
        "Nothing is wrong with the sign-in; the tracker goes on trying every "
        "few hours and the add-on log says what it was told."),
    "http_429": (
        "The usage endpoint has refused every request for {hours} hours "
        "now, so the usage figure is brAIn's own estimate. This is not the "
        "account's usage; the tracker goes on asking every few hours and "
        "the add-on log says what it was told."),
}


def needs_nothing(code: str, since: float | None = None,
                  now: float | None = None) -> bool:
    """Whether this code's remedy is to do nothing.

    A code this does not recognise answers False: "I do not know what
    this means" and "there is nothing to do" are different claims, and
    only the second may keep a fault off a verdict. And a code that has
    stood longer than its shelf life (`STUCK_AFTER`) answers False too,
    because "wait" is only an answer for as long as waiting can work.
    """
    code = str(code or "")
    if code not in NEEDS_NOTHING:
        return False
    limit = STUCK_AFTER.get(code)
    if limit and since:
        return ((now if now is not None else time.time()) - since) < limit
    return True


def limits_problem() -> dict:
    """Why the account's real numbers are missing, in the tracker's words.

    The panel used to have no way to ask. When the tracker fails, its file
    goes stale, ``budget_state`` slides to the local estimate, and the pill
    keeps showing a percentage — one built from brAIn's own insight runs,
    so on a home that mostly uses the terminal and the chat it sits at 0%
    and never moves, with the weekly figure simply gone. That reads exactly
    like a broken sensor, and the only thing the popover had to say about
    it was "sign in with your Claude subscription" — telling somebody who
    is signed in to redo the thing that worked, which is the one piece of
    advice guaranteed to waste their evening.

    So the reason travels with the fallback. ``code`` is the tracker's own
    status vocabulary (the same strings the diagnostic sensor reports),
    ``detail`` its gloss where it has one, and ``next_attempt`` when it
    will ask again — because during a 429 backoff the honest answer is
    "not broken, waiting, back at 9:40".
    """
    data = _tracker_file()
    if data is None:
        return {"code": "not_running"}
    # `error` is a settled fact the tracker wrote in place of a reading;
    # `last_error` rides beside numbers it deliberately did not overwrite.
    code = data.get("error") or data.get("last_error")
    if not isinstance(code, str) or not code:
        return {"code": "stale"}
    detail = data.get("detail") or data.get("last_error_detail")
    out = {"code": code}
    if isinstance(detail, str) and detail:
        out["detail"] = detail
    nxt = _parse_iso_epoch(data.get("next_attempt_at"))
    if nxt:
        out["next_attempt"] = nxt
    # How long this verdict has stood. The tracker keeps the stamp across
    # its own rewrites and across a restart, so this is the age of the
    # PROBLEM rather than of the last poll that reported it.
    since = _parse_iso_epoch(data.get("error_since"))
    if since:
        out["since"] = since
    # Carried rather than re-derived by whoever reads it. `health.py` is
    # stdlib-only and pure over the payload it is handed — it answers "is
    # brAIn working" off the diagnostics dict and nothing else — so the
    # module that owns this vocabulary is the one that says what a code
    # means, and the answer rides in the file a person reads too. An older
    # mirror carries no flag, which reads as False: the fault surfaces,
    # which is the safe direction.
    out["needs_nothing"] = needs_nothing(code, since)
    if code in STUCK_AFTER and since and not out["needs_nothing"]:
        # The same code, no longer the same claim: it is the reader's job
        # to say so, because the tracker wrote the gloss when it was true.
        hours = (time.time() - since) / 3600
        out["stuck"] = True
        out["detail"] = ((out.get("detail") or "") + " "
                         + STUCK_DETAIL.get(
                             code, "It has been the answer for {hours} "
                             "hours now.").format(hours=f"{hours:.0f}")
                         ).strip()
    limit = OVERDUE_AFTER.get(code)
    if limit and since and time.time() - since >= limit:
        hours = (time.time() - since) / 3600
        out["overdue"] = True
        out["detail"] = ((out.get("detail") or "") + " "
                         + OVERDUE_DETAIL[code].format(hours=f"{hours:.0f}")
                         ).strip()
    return out


def _fresh_block(name: str) -> dict | None:
    """One utilization block ("five_hour", "seven_day") out of fresh data."""
    block = (_fresh_payload() or {}).get(name)
    return block if isinstance(block, dict) else None


def _fresh_limits() -> dict | None:
    """The tracker file's five_hour block, only when the data is fresh."""
    return _fresh_block("five_hour")


def _pct(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and 0 <= value <= 100 else None


def real_session_utilization() -> float | None:
    """The account's ACTUAL five-hour utilization %, if fresh data exists."""
    return _pct((_fresh_limits() or {}).get("utilization"))


def budget_state(settings: dict, now: float | None = None) -> dict:
    """Everything the scheduler and the panel need to know about budget.

    blocked is True when the session's usage has reached the configured
    budget — the scheduler then skips auto-refresh until the window rolls.
    resets_at (epoch seconds, or None) is when the session window resets:
    the account's real reset time when the tracker provides it, otherwise
    when the oldest run counted by the local estimate ages out.

    The weekly window rides along (week_percent / week_resets_at, both None
    without the tracker). Nothing schedules against it — a Claude plan's
    seven-day limit is the one that actually stops your week, so the panel
    shows it next to the session rather than making you go looking.
    """
    budget_pct = int(settings.get("budget_percent") or DEFAULT_BUDGET)
    # "No limit: run until Anthropic rate-limits." Only a literal True: the
    # one direction a malformed value may fall is the cap that was there.
    no_limit = settings.get("budget_no_limit") is True
    plan = settings.get("plan") if settings.get("plan") in PLAN_SESSION_TOKENS else "pro"
    now = time.time() if now is None else now
    cutoff = now - SESSION_HOURS * 3600
    runs = [r for r in _load_runs() if r["ts"] >= cutoff]
    spent = sum(r["tokens"] for r in runs)
    payload = _fresh_payload() or {}
    five = payload.get("five_hour") if isinstance(payload.get("five_hour"), dict) else {}
    week = payload.get("seven_day") if isinstance(payload.get("seven_day"), dict) else {}
    real = _pct(five.get("utilization"))
    resets_at: int | None = None
    if real is not None:
        used_pct = real
        source = "account"
        resets_at = _parse_iso_epoch(five.get("resets_at"))
    else:
        allowance = PLAN_SESSION_TOKENS[plan]
        used_pct = min(100.0, spent / allowance * 100.0)
        source = "estimate"
        if runs:
            resets_at = int(min(r["ts"] for r in runs) + SESSION_HOURS * 3600)
    week_pct = _pct(week.get("utilization"))
    return {
        "used_percent": round(used_pct, 1),
        "budget_percent": budget_pct,
        # With no limit, brAIn's own estimate stops nothing: only the
        # account's own figure saying the session is spent does, and the
        # rate-limit pause (server.RATE_LIMIT_STATE) covers the case where
        # that figure is unavailable and Anthropic refuses a run.
        "blocked": (source == "account" and used_pct >= 100) if no_limit
                   else used_pct >= budget_pct,
        "no_limit": no_limit,
        "source": source,
        "window_tokens": spent,
        "resets_at": resets_at,
        "week_percent": None if week_pct is None else round(week_pct, 1),
        "week_resets_at": _parse_iso_epoch(week.get("resets_at")),
        "plan": plan,
        "plan_label": PLAN_LABELS[plan],
        "plan_session_tokens": PLAN_SESSION_TOKENS[plan],
        # What brAIn itself spent the window on. Always brAIn's own runs,
        # never the account's — when `source` is "account" the pill's
        # percentage covers every Claude use on the subscription (terminal,
        # chat, voice) and these rows are a subset of it. The panel says so;
        # a breakdown read as exhaustive is how you conclude the terminal is
        # free.
        "runs": len(runs),
        "breakdown": _breakdown(runs),
        # Why the account's own numbers are not the ones above. Present
        # only when they are missing, so the panel can say what is wrong
        # instead of showing a frozen estimate as if it were live — and so
        # it stops telling a signed-in person to sign in.
        **({} if source == "account" else {"limits": limits_problem()}),
    }


# ---------------------------------------------------------------------------
# The self-check: every writer in the tree, and the group each id lands in
# ---------------------------------------------------------------------------
#
# `python3 brain/panel/usage_store.py` (from anywhere). It reads the source,
# never the ledger: each `_record_usage` call however it is made (directly,
# through `asyncio.to_thread`, or as doctor's `record_usage` hook), each id a
# variable carries (the functions below, which name what the variable holds),
# and each journal source a shell run is booked under (`journal.record_shell`,
# `brain_journal_record`, `brain_run_journal.py record`, the pool's
# `record_run`). It prints every id or prefix with its group and exits 1 on
# one this table does not place, or on a variable writer it does not know.

# A writer whose id is a variable: the function it is in, and what it holds.
_VARIABLE_WRITERS = {
    "_search_run": ("a card's id", ("energy", "user-", "custom-")),
    "_snapshot_run": ("a card's id", ("energy", "user-", "custom-")),
    "_run_plan": ("PLAN_JOB_PREFIX", ("plan-",)),
    "_run_fix": ("FIX_JOB_PREFIX", ("fix-",)),
    "_run_typed_fix": ("FIX_JOB_PREFIX", ("fix-",)),
    "_run_milestone": ("_milestone_job_id", ("milestone-",)),
}


def _self_check() -> int:
    import re as _re
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent       # brain/
    found: list[tuple[str, str, str]] = []                 # (id, where, how)
    unknown: list[str] = []
    call = _re.compile(
        r"(?:_record_usage|record_usage)\s*(?:\(|,)\s*[^,()]*(?:\([^()]*\))?[^,()]*,"
        r"\s*(f?\"[^\"]*\"|[A-Za-z_][\w.]*)\s*\)")
    for path in sorted((root / "panel").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name == "usage_store.py":
            continue
        for m in call.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            where = f"{path.relative_to(root)}:{line}"
            arg = m.group(1)
            if arg.startswith(("\"", "f\"")):
                lit = arg[2:-1] if arg.startswith("f") else arg[1:-1]
                if "{" in lit:
                    lit = lit.split("{", 1)[0]
                found.append((lit, where, "literal" if "{" not in arg else "prefix"))
                continue
            head = text[:m.start()]
            fn = _re.findall(r"^(?:async )?def (\w+)", head, _re.M)
            fn = fn[-1] if fn else "?"
            if fn not in _VARIABLE_WRITERS:
                unknown.append(f"{where}: `{arg}` in {fn}() — a variable this check cannot place")
                continue
            what, examples = _VARIABLE_WRITERS[fn]
            for ex in examples:
                found.append((ex, where, f"{arg} in {fn}() = {what}"))
    # The journal sources a shell run is booked under.
    shell = [
        (_re.compile(r"brain_journal_record\s+([\w-]+)\s"), ("scripts", "integrations")),
        (_re.compile(r"(?:brain_run_journal\.py|journal_py\")\s+record\s+(\"\$\{\w+:-\w+\}\"|[\w-]+)\s"),
         ("scripts", "integrations")),
        (_re.compile(r"(?:^|[^\w.]|\)\.)record_run\(\s*\"([\w-]+)\"", _re.M), ("integrations", "scripts")),
        (_re.compile(r"record_shell\(\s*(\"[\w-]+\"|[A-Z_]+)"), ("scripts", "integrations", "panel")),
        (_re.compile(r"_book_shell_usage[\s\S]{0,400}?or \"([\w-]+)\""), ("panel",)),
    ]
    for rx, dirs in shell:
        for d in dirs:
            for path in sorted((root / d).rglob("*")):
                if not path.is_file() or path.suffix not in (".py", ".sh", ""):
                    continue
                if path.name in ("journal.py", "brain_run_journal.py", "usage_store.py") \
                        and "record_shell(" not in rx.pattern and "_book" not in rx.pattern:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    if text[:m.start()].rsplit("\n", 1)[-1].lstrip().startswith("#"):
                        continue
                    where = f"{path.relative_to(root)}:{line}"
                    arg = m.group(1)
                    if path.name == "journal.py" and arg in ("source",):
                        continue
                    if arg.startswith("\"${"):
                        var, default = _re.match(r"\"\$\{(\w+):-(\w+)\}\"", arg).groups()
                        found.append((default, where, f"journal source ({var} unset)"))
                        for v in _re.findall(rf"{var}=\$\(.*?then \"(\w+)\"", text):
                            found.append((v, where, f"journal source ({var})"))
                        continue
                    if _re.fullmatch(r"[A-Z_]+", arg):
                        c = _re.search(rf"^{arg}\s*=\s*\"([\w-]+)\"", text, _re.M)
                        if not c:
                            unknown.append(f"{where}: {arg} has no literal value")
                            continue
                        arg = c.group(1)
                    found.append((arg.strip("\""), where, "journal source"))
    seen = set()
    width = max((len(i) for i, _w, _h in found), default=10)
    for rid, where, how in sorted(found, key=lambda r: (spend_group(r[0]), r[0], r[1])):
        group = spend_group(rid)
        placed = (rid in SPEND_IDS or any(rid.startswith(p) for p, _g in SPEND_PREFIXES)
                  or rid in _card_ids())
        mark = "" if placed else "   <-- NOT IN THE TABLE"
        if not placed:
            unknown.append(f"{where}: `{rid}` is not in SPEND_IDS or SPEND_PREFIXES")
        key = (rid, where)
        if key in seen:
            continue
        seen.add(key)
        print(f"{rid:<{width}}  {SPEND_GROUPS[group]:<26}  {where}  ({how})"
              + mark)
    for rid in sorted(set(SPEND_IDS) & _card_ids()):
        unknown.append(f"`{rid}` is a shipped card's id AND a run's: one of them "
                       "is always counted in the wrong place")
    written = {spend_group(r) for r, _w, _h in found}
    idle = [g for g in SPEND_GROUPS if g not in written]
    for g in idle:
        unknown.append(f"group `{g}` ({SPEND_GROUPS[g]}): no writer records an id under it")
    print(f"\n{len(found)} writer ids, {len(written)} groups written.")
    if unknown:
        print("\nFAILED:")
        for u in unknown:
            print("  " + u)
        return 1
    print("Every writer's id is placed, and every group has a writer.")
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(_self_check())
