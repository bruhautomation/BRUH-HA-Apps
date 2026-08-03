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
from pathlib import Path

USAGE_FILE = os.environ.get("BRAIN_USAGE_FILE", "/data/usage.json")

# Written by brAIn's usage-limits tracker (real Anthropic account
# utilization). Entirely optional — missing/stale files are ignored.
LIMITS_FILE = os.environ.get(
    "BRAIN_USAGE_LIMITS", "/config/.brain/usage_limits.json")
# Real utilization older than this is considered stale (tracker not running)
LIMITS_MAX_AGE_S = 2 * 3600

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
    path = Path(USAGE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"runs": runs}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


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


def window_tokens(hours: float = SESSION_HOURS, now: float | None = None) -> int:
    """Tokens Insights spent in the trailing window."""
    now = time.time() if now is None else now
    cutoff = now - hours * 3600
    return sum(r["tokens"] for r in _load_runs() if r["ts"] >= cutoff)


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


def _fresh_payload() -> dict | None:
    """The whole tracker file, only when the data is fresh."""
    try:
        with open(LIMITS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    updated = data.get("updated_at")
    if isinstance(updated, str):
        stamp = _parse_iso_epoch(updated)
        if stamp is None or time.time() - stamp > LIMITS_MAX_AGE_S:
            return None
    return data


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
    }
