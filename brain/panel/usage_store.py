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


# How many spenders the breakdown names before folding the tail into one
# row. The list is capped and the window total is not, so a long tail says
# what it is not showing rather than quietly disagreeing with the pill.
MAX_BREAKDOWN = 6


def _breakdown(runs: list[dict], limit: int = MAX_BREAKDOWN) -> list[dict]:
    """Per-card token totals out of already-loaded runs, biggest first.

    "Why is my session gone?" is a question about *what spent it*, and the
    run ledger has always known — it records an id per run and nothing ever
    read it back. Rows are ``{"id", "tokens", "runs"}``; the tail past
    ``limit`` collapses into one row flagged ``rest`` rather than being
    dropped, because a breakdown that silently omits a third of the window
    is worse than no breakdown at all.
    """
    totals: dict[str, dict] = {}
    for run in runs:
        key = str(run.get("id") or "")
        row = totals.setdefault(key, {"id": key, "tokens": 0, "runs": 0})
        row["tokens"] += run["tokens"]
        row["runs"] += 1
    ranked = sorted(totals.values(), key=lambda r: -r["tokens"])
    if limit and len(ranked) > limit:
        tail = ranked[limit:]
        ranked = ranked[:limit] + [{
            "id": "", "rest": True,
            "tokens": sum(r["tokens"] for r in tail),
            "runs": sum(r["runs"] for r in tail),
        }]
    return ranked


def window_breakdown(hours: float = SESSION_HOURS, now: float | None = None,
                     limit: int = MAX_BREAKDOWN) -> list[dict]:
    """What spent the trailing window, biggest first."""
    now = time.time() if now is None else now
    cutoff = now - hours * 3600
    return _breakdown([r for r in _load_runs() if r["ts"] >= cutoff], limit)


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
NEEDS_NOTHING = ("oauth_token_awaiting_refresh", "api_key_has_no_usage_limits",
                 "http_429")


def needs_nothing(code: str) -> bool:
    """Whether this code's remedy is to do nothing.

    A code this does not recognise answers False: "I do not know what
    this means" and "there is nothing to do" are different claims, and
    only the second may keep a fault off a verdict.
    """
    return str(code or "") in NEEDS_NOTHING


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
    # Carried rather than re-derived by whoever reads it. `health.py` is
    # stdlib-only and pure over the payload it is handed — it answers "is
    # brAIn working" off the diagnostics dict and nothing else — so the
    # module that owns this vocabulary is the one that says what a code
    # means, and the answer rides in the file a person reads too. An older
    # mirror carries no flag, which reads as False: the fault surfaces,
    # which is the safe direction.
    out["needs_nothing"] = needs_nothing(code)
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
        "blocked": used_pct >= budget_pct,
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
