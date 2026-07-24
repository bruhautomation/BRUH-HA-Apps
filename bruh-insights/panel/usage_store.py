"""Token-usage tracking and session budgeting for BRUH Insights.

Every Claude invocation's token count is recorded to one JSON file so the
add-on knows how much of the user's 5-hour subscription session window it
has consumed. The ⚙ settings dialog sets a budget (a percentage of the
session); once it's reached, scheduled generation pauses until the window
rolls over. Manual clicks always work.

Two signals, best first:
  1. Real account utilization — when the BRUH Terminal add-on is installed,
     its usage-limits tracker writes /config/.bruh_claude/usage_limits.json
     with the ACTUAL five-hour utilization percentage from the Anthropic
     API (all Claude use on the account, not just Insights). Fresh data
     wins.
  2. Local estimate — otherwise we sum the tokens Insights itself spent in
     the trailing 5 hours against a rough per-plan session allowance.
     The allowances are honest ballparks (Anthropic doesn't publish exact
     numbers and they vary with load); they exist so the slider means
     something even without the tracker.

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

USAGE_FILE = os.environ.get("BRUH_INSIGHTS_USAGE_FILE", "/data/usage.json")

# Written by BRUH Terminal's usage-limits tracker (real Anthropic account
# utilization). Entirely optional — missing/stale files are ignored.
LIMITS_FILE = os.environ.get(
    "BRUH_INSIGHTS_USAGE_LIMITS", "/config/.bruh_claude/usage_limits.json")
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


def _fresh_limits() -> dict | None:
    """The tracker file's five_hour block, only when the data is fresh."""
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
    five = data.get("five_hour")
    return five if isinstance(five, dict) else None


def real_session_utilization() -> float | None:
    """The account's ACTUAL five-hour utilization %, if fresh data exists."""
    util = (_fresh_limits() or {}).get("utilization")
    if isinstance(util, (int, float)) and 0 <= util <= 100:
        return float(util)
    return None


def budget_state(settings: dict, now: float | None = None) -> dict:
    """Everything the scheduler and the panel need to know about budget.

    blocked is True when the session's usage has reached the configured
    budget — the scheduler then skips auto-refresh until the window rolls.
    resets_at (epoch seconds, or None) is when the session window resets:
    the account's real reset time when the tracker provides it, otherwise
    when the oldest run counted by the local estimate ages out.
    """
    budget_pct = int(settings.get("budget_percent") or DEFAULT_BUDGET)
    plan = settings.get("plan") if settings.get("plan") in PLAN_SESSION_TOKENS else "pro"
    now = time.time() if now is None else now
    cutoff = now - SESSION_HOURS * 3600
    runs = [r for r in _load_runs() if r["ts"] >= cutoff]
    spent = sum(r["tokens"] for r in runs)
    five = _fresh_limits() or {}
    real = five.get("utilization")
    resets_at: int | None = None
    if isinstance(real, (int, float)) and 0 <= real <= 100:
        used_pct = float(real)
        source = "account"
        resets_at = _parse_iso_epoch(five.get("resets_at"))
    else:
        allowance = PLAN_SESSION_TOKENS[plan]
        used_pct = min(100.0, spent / allowance * 100.0)
        source = "estimate"
        if runs:
            resets_at = int(min(r["ts"] for r in runs) + SESSION_HOURS * 3600)
    return {
        "used_percent": round(used_pct, 1),
        "budget_percent": budget_pct,
        "blocked": used_pct >= budget_pct,
        "source": source,
        "window_tokens": spent,
        "resets_at": resets_at,
        "plan": plan,
        "plan_label": PLAN_LABELS[plan],
        "plan_session_tokens": PLAN_SESSION_TOKENS[plan],
    }
