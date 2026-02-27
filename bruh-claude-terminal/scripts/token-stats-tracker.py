#!/usr/bin/env python3
"""Token usage stats tracker for BRUH Claude Terminal.

Periodically scans Claude Code session JSONL files for token usage
data, then writes aggregated stats to a shared JSON file that the
Home Assistant custom integration can read as sensor data.

Token counts (input_tokens, output_tokens, cache_*) are the real values
returned by the Anthropic API in each response's ``usage`` field — they
are not estimated.

Also tracks per-model usage (Sonnet, Opus, Haiku) and estimates
session reset times based on session activity windows.

Output: /config/.bruh_claude/token_stats.json
"""

import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CLAUDE_HOME = os.environ.get("HOME", "/data/home")
STATS_FILE = "/config/.bruh_claude/token_stats.json"
POLL_INTERVAL = int(os.environ.get("TOKEN_STATS_INTERVAL", "60"))  # seconds

# Directories where Claude Code stores session JSONL files
SESSION_DIRS = [
    os.path.join(CLAUDE_HOME, ".claude", "projects"),
    os.path.join(CLAUDE_HOME, ".claude"),
]


# ---------------------------------------------------------------------------
# Model classification
# ---------------------------------------------------------------------------

# Map model ID substrings to model family names.
# Claude API model IDs look like: claude-sonnet-4-20250514, claude-opus-4-20250514, etc.
MODEL_FAMILIES = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
}

# Session window duration — Anthropic's rolling session window is approximately
# 5 hours for most plans.  This is used to estimate when the session resets.
SESSION_WINDOW_HOURS = int(os.environ.get("SESSION_WINDOW_HOURS", "5"))


def classify_model(model_id):
    """Classify a model ID string into a model family (sonnet, opus, haiku).

    Returns 'unknown' if the model can't be classified.
    """
    if not model_id:
        return "unknown"
    model_lower = model_id.lower()
    for substring, family in MODEL_FAMILIES.items():
        if substring in model_lower:
            return family
    return "unknown"


# ---------------------------------------------------------------------------
# Session file discovery
# ---------------------------------------------------------------------------

def find_session_files():
    """Find all JSONL session files under known Claude Code directories."""
    files = []
    for base in SESSION_DIRS:
        if not os.path.isdir(base):
            continue
        for pattern in ["**/*.jsonl", "*.jsonl"]:
            files.extend(glob.glob(os.path.join(base, pattern), recursive=True))
    # Deduplicate
    return sorted(set(files))


# ---------------------------------------------------------------------------
# JSONL parsing
# ---------------------------------------------------------------------------

def parse_session_file(path):
    """Parse a single JSONL session file and extract token/cost data.

    Returns a list of dicts with keys:
      session_id, timestamp, input_tokens, output_tokens,
      cache_creation_tokens, cache_read_tokens
    """
    entries = []
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Only assistant messages carry token usage
                if record.get("type") != "assistant":
                    continue

                msg = record.get("message", {})
                usage = msg.get("usage") or record.get("usage") or {}

                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)

                # Skip entries with no token data
                if not input_tokens and not output_tokens:
                    continue

                timestamp_str = record.get("timestamp", "")
                session_id = record.get("sessionId", "")

                # Extract model name from the message or record
                model_id = msg.get("model", "") or record.get("model", "")
                model_family = classify_model(model_id)

                entries.append({
                    "session_id": session_id,
                    "timestamp": timestamp_str,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_tokens": cache_creation,
                    "cache_read_tokens": cache_read,
                    "model": model_id,
                    "model_family": model_family,
                })
    except OSError:
        pass
    return entries


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_stats(all_entries):
    """Aggregate token entries into session-level and time-period stats."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())  # Monday

    # Parse timestamps and attach datetime objects
    for entry in all_entries:
        ts = entry.get("timestamp", "")
        try:
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            entry["_dt"] = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            entry["_dt"] = None

    # Find the most recent session
    sessions = {}
    for e in all_entries:
        sid = e.get("session_id", "unknown")
        if sid not in sessions:
            sessions[sid] = []
        sessions[sid].append(e)

    # Sort sessions by their latest timestamp
    def session_max_ts(sid):
        entries = sessions[sid]
        dts = [e["_dt"] for e in entries if e["_dt"]]
        return max(dts) if dts else datetime.min.replace(tzinfo=timezone.utc)

    sorted_sessions = sorted(sessions.keys(), key=session_max_ts, reverse=True)
    latest_session_id = sorted_sessions[0] if sorted_sessions else None

    # Period boundaries
    today_end = today_start + timedelta(days=1)
    week_end = week_start + timedelta(days=7)

    # Current session stats
    session_entries = sessions.get(latest_session_id, []) if latest_session_id else []
    session_stats = _sum_entries(session_entries)
    session_stats["session_id"] = latest_session_id or ""

    # Session start / last activity times
    session_dts = [e["_dt"] for e in session_entries if e["_dt"]]
    if session_dts:
        session_stats["started_at"] = min(session_dts).isoformat()
        session_stats["last_activity"] = max(session_dts).isoformat()

    # Today's stats
    today_entries = [e for e in all_entries if e["_dt"] and e["_dt"] >= today_start]
    today_stats = _sum_entries(today_entries)
    today_stats["period_start"] = today_start.isoformat()
    today_stats["resets_at"] = today_end.isoformat()

    # This week's stats (Monday to Sunday)
    week_entries = [e for e in all_entries if e["_dt"] and e["_dt"] >= week_start]
    week_stats = _sum_entries(week_entries)
    week_stats["period_start"] = week_start.isoformat()
    week_stats["resets_at"] = week_end.isoformat()

    # Count sessions active this week
    week_session_ids = set()
    for e in week_entries:
        sid = e.get("session_id")
        if sid:
            week_session_ids.add(sid)
    week_stats["session_count"] = len(week_session_ids)

    # Estimate session reset time based on first activity in the current session
    session_reset_at = None
    if session_dts:
        session_start = min(session_dts)
        session_reset_at = (session_start + timedelta(hours=SESSION_WINDOW_HOURS)).isoformat()
    session_stats["reset_at"] = session_reset_at

    # All-time stats
    all_time_stats = _sum_entries(all_entries)

    # Per-model weekly stats
    models_week = _per_model_stats(week_entries)

    # Per-model session stats
    models_session = _per_model_stats(session_entries)

    return {
        "session": session_stats,
        "today": today_stats,
        "week": week_stats,
        "all_time": all_time_stats,
        "models_week": models_week,
        "models_session": models_session,
        "total_sessions": len(sessions),
        "updated_at": now.isoformat(),
    }


def _sum_entries(entries):
    """Sum token counts for a list of entries (all values from the Anthropic API)."""
    return {
        "input_tokens": sum(e.get("input_tokens", 0) for e in entries),
        "output_tokens": sum(e.get("output_tokens", 0) for e in entries),
        "total_tokens": sum(
            e.get("input_tokens", 0) + e.get("output_tokens", 0) for e in entries
        ),
        "cache_creation_tokens": sum(e.get("cache_creation_tokens", 0) for e in entries),
        "cache_read_tokens": sum(e.get("cache_read_tokens", 0) for e in entries),
        "message_count": len(entries),
    }


def _per_model_stats(entries):
    """Group entries by model family and sum token counts for each.

    Returns a dict keyed by model family (sonnet, opus, haiku, unknown)
    with the same structure as _sum_entries.
    """
    by_family = {}
    for e in entries:
        family = e.get("model_family", "unknown")
        if family not in by_family:
            by_family[family] = []
        by_family[family].append(e)

    result = {}
    for family, family_entries in by_family.items():
        stats = _sum_entries(family_entries)
        # Include the most recently seen full model ID for reference
        model_ids = [e.get("model", "") for e in family_entries if e.get("model")]
        if model_ids:
            stats["model_id"] = model_ids[-1]
        result[family] = stats
    return result


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def write_stats(stats):
    """Atomically write stats to the shared JSON file."""
    os.makedirs(os.path.dirname(STATS_FILE), exist_ok=True)
    tmp = STATS_FILE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(stats, fh, indent=2)
        os.replace(tmp, STATS_FILE)
    except OSError as exc:
        sys.stderr.write(f"token-stats-tracker: write error: {exc}\n")


def run_once():
    """Scan session files and write stats."""
    files = find_session_files()
    all_entries = []
    for f in files:
        all_entries.extend(parse_session_file(f))
    stats = aggregate_stats(all_entries)
    stats["session_files_scanned"] = len(files)
    write_stats(stats)
    return stats


def main():
    sys.stderr.write(
        f"token-stats-tracker: starting (interval={POLL_INTERVAL}s, "
        f"home={CLAUDE_HOME})\n"
    )
    while True:
        try:
            stats = run_once()
            total = stats.get("all_time", {}).get("total_tokens", 0)
            files = stats.get("session_files_scanned", 0)
            sys.stderr.write(
                f"token-stats-tracker: scanned {files} files, "
                f"all-time tokens: {total}\n"
            )
        except Exception as exc:
            sys.stderr.write(f"token-stats-tracker: error: {exc}\n")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
