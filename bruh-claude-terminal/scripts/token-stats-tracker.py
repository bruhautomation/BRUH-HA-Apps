#!/usr/bin/env python3
"""Token usage stats tracker for BRUH Claude Terminal.

Periodically scans Claude Code session JSONL files for token usage and
cost data, then writes aggregated stats to a shared JSON file that the
Home Assistant custom integration can read as sensor data.

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
      cache_creation_tokens, cache_read_tokens, cost_usd
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
                cost = record.get("costUSD") or record.get("cost_usd") or 0

                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                cache_creation = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)

                # Skip entries with no usage data at all
                if not input_tokens and not output_tokens and not cost:
                    continue

                timestamp_str = record.get("timestamp", "")
                session_id = record.get("sessionId", "")

                entries.append({
                    "session_id": session_id,
                    "timestamp": timestamp_str,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_tokens": cache_creation,
                    "cache_read_tokens": cache_read,
                    "cost_usd": float(cost) if cost else 0.0,
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

    # Current session stats
    session_entries = sessions.get(latest_session_id, []) if latest_session_id else []
    session_stats = _sum_entries(session_entries)
    session_stats["session_id"] = latest_session_id or ""

    # Today's stats
    today_entries = [e for e in all_entries if e["_dt"] and e["_dt"] >= today_start]
    today_stats = _sum_entries(today_entries)

    # This week's stats (Monday to now)
    week_entries = [e for e in all_entries if e["_dt"] and e["_dt"] >= week_start]
    week_stats = _sum_entries(week_entries)

    # All-time stats
    all_time_stats = _sum_entries(all_entries)

    return {
        "session": session_stats,
        "today": today_stats,
        "week": week_stats,
        "all_time": all_time_stats,
        "total_sessions": len(sessions),
        "updated_at": now.isoformat(),
    }


def _sum_entries(entries):
    """Sum token counts and costs for a list of entries."""
    return {
        "input_tokens": sum(e.get("input_tokens", 0) for e in entries),
        "output_tokens": sum(e.get("output_tokens", 0) for e in entries),
        "total_tokens": sum(
            e.get("input_tokens", 0) + e.get("output_tokens", 0) for e in entries
        ),
        "cache_creation_tokens": sum(e.get("cache_creation_tokens", 0) for e in entries),
        "cache_read_tokens": sum(e.get("cache_read_tokens", 0) for e in entries),
        "cost_usd": round(sum(e.get("cost_usd", 0) for e in entries), 4),
        "message_count": len(entries),
    }


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
