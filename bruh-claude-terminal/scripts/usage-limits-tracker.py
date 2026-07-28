#!/usr/bin/env python3
"""Anthropic usage limits tracker for BRUH Claude Terminal.

Periodically queries the Anthropic API for real account-wide usage
limits (session and weekly utilization percentages with reset times).
This data is the same as what's shown on claude.ai Settings > Usage.

Writes results to /config/.bruh_claude/usage_limits.json so the
Home Assistant custom integration can expose them as sensors.

Requires OAuth authentication — reads the access token from
Claude Code's credentials file (~/.claude/.credentials.json).
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CLAUDE_HOME = os.environ.get("HOME", "/data/home")
USAGE_FILE = "/config/.bruh_claude/usage_limits.json"
POLL_INTERVAL = int(os.environ.get("USAGE_LIMITS_INTERVAL", "120"))  # seconds

ANTHROPIC_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# Possible locations for Claude Code's OAuth credentials.
# The add-on sets up symlinks so all these may resolve to the same file.
CREDENTIAL_PATHS = [
    os.path.join(CLAUDE_HOME, ".claude", ".credentials.json"),
    os.path.join(CLAUDE_HOME, ".config", "claude", ".credentials.json"),
    "/data/.config/claude/.credentials.json",
]


# ---------------------------------------------------------------------------
# OAuth token discovery
# ---------------------------------------------------------------------------

def find_oauth_token():
    """Find the Claude Code OAuth access token from credentials files.

    Returns the access token string, or None if not found.
    """
    for path in CREDENTIAL_PATHS:
        token = _read_token_from_file(path)
        if token:
            return token
    return None


def _read_token_from_file(path):
    """Read the OAuth access token from a credentials JSON file."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None

    # Standard format: {"claudeAiOauth": {"accessToken": "sk-ant-oat01-..."}}
    oauth = data.get("claudeAiOauth", {})
    token = oauth.get("accessToken")
    if token:
        return token

    # Fallback: check for a flat "accessToken" key
    token = data.get("accessToken")
    if token:
        return token

    return None


# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------

def fetch_usage_limits(token):
    """Fetch account usage limits from the Anthropic API.

    Returns a dict with the API response, or None on failure.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "bruh-claude-terminal/1.0",
    }

    req = urllib.request.Request(ANTHROPIC_USAGE_URL, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        sys.stderr.write(
            f"usage-limits-tracker: HTTP {status} from Anthropic API: {body}\n"
        )
        return None
    except (urllib.error.URLError, OSError) as exc:
        sys.stderr.write(f"usage-limits-tracker: network error: {exc}\n")
        return None
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"usage-limits-tracker: invalid JSON response: {exc}\n")
        return None


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_usage(data):
    """Atomically write usage limits to the shared JSON file."""
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)

    # Wrap the raw API response with metadata
    output = {
        "source": "anthropic_api",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }

    tmp = USAGE_FILE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(output, fh, indent=2)
        os.replace(tmp, USAGE_FILE)
    except OSError as exc:
        sys.stderr.write(f"usage-limits-tracker: write error: {exc}\n")


def write_error_status(error_msg):
    """Write an error status file so sensors know what's wrong."""
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    output = {
        "source": "anthropic_api",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "error": error_msg,
    }
    tmp = USAGE_FILE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(output, fh, indent=2)
        os.replace(tmp, USAGE_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_once():
    """Fetch usage limits and write to file. Returns True on success."""
    token = find_oauth_token()
    if not token:
        sys.stderr.write(
            "usage-limits-tracker: no OAuth token found — "
            "Claude Code may not be authenticated yet\n"
        )
        write_error_status("no_oauth_token")
        return False

    data = fetch_usage_limits(token)
    if data is None:
        return False

    if "error" in data:
        sys.stderr.write(
            f"usage-limits-tracker: API error: {data.get('error')}\n"
        )
        write_error_status(str(data.get("error")))
        return False

    write_usage(data)
    return True


def main():
    sys.stderr.write(
        f"usage-limits-tracker: starting (interval={POLL_INTERVAL}s)\n"
    )

    # Initial backoff for first attempt — give Claude Code time to authenticate
    initial_delay = 10
    sys.stderr.write(
        f"usage-limits-tracker: waiting {initial_delay}s for Claude Code auth...\n"
    )
    time.sleep(initial_delay)

    consecutive_failures = 0
    last_logged = None

    while True:
        try:
            success = run_once()
            if success:
                consecutive_failures = 0
                # Log only when the numbers change — an unconditional
                # heartbeat every poll floods the add-on log (a third of
                # its lines at the default interval).
                try:
                    with open(USAGE_FILE) as fh:
                        stats = json.load(fh)
                    five_hour = stats.get("five_hour", {})
                    seven_day = stats.get("seven_day", {})
                    current = (
                        five_hour.get("utilization", "?"),
                        seven_day.get("utilization", "?"),
                    )
                    if current != last_logged:
                        sys.stderr.write(
                            f"usage-limits-tracker: "
                            f"session={current[0]}%, weekly={current[1]}%\n"
                        )
                        last_logged = current
                except Exception:
                    pass
            else:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    sys.stderr.write(
                        "usage-limits-tracker: 5 consecutive failures, "
                        "backing off to 5-minute interval\n"
                    )
        except Exception as exc:
            sys.stderr.write(f"usage-limits-tracker: error: {exc}\n")
            consecutive_failures += 1

        # Back off if failing repeatedly
        if consecutive_failures >= 5:
            time.sleep(300)  # 5 minutes
        else:
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
