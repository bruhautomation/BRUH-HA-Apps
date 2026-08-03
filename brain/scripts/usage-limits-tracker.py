#!/usr/bin/env python3
"""Anthropic usage limits tracker for brAIn.

Periodically queries the Anthropic API for real account-wide usage
limits (session and weekly utilization percentages with reset times).
This data is the same as what's shown on claude.ai Settings > Usage.

Writes results to /config/.brain/usage_limits.json so the
Home Assistant custom integration can expose them as sensors.

Requires OAuth authentication, and looks in **every** place brAIn keeps a
credential, in the same order as engine.get_auth and brain-auth-env.sh:
Claude Code's own credentials file, then the panel's store, then the file
`ha login` shares. It used to read only the first of those, so signing in
through the panel — the primary sign-in surface — left the tracker
reporting `no_oauth_token` and every usage sensor unavailable while the
rest of the add-on was perfectly authenticated.
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

CLAUDE_HOME = os.environ.get("BRAIN_HOME") or os.environ.get("HOME", "/data/home")
CLAUDE_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR", "")
USAGE_FILE = "/config/.brain/usage_limits.json"
POLL_INTERVAL = int(os.environ.get("USAGE_LIMITS_INTERVAL", "120"))  # seconds
# How long a reading stays usable when polls start failing. Matches
# usage_store.LIMITS_MAX_AGE_S, which is the panel's own staleness rule for
# the same file — two answers to "is this still true" would be one too many.
STALE_AFTER_S = 2 * 3600

ANTHROPIC_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# Possible locations for Claude Code's OAuth credentials.
# The add-on sets up symlinks so all these may resolve to the same file.
CREDENTIAL_PATHS = [
    p for p in (
        os.path.join(CLAUDE_CONFIG_DIR, ".credentials.json")
        if CLAUDE_CONFIG_DIR else "",
        os.path.join(CLAUDE_HOME, ".claude", ".credentials.json"),
        os.path.join(CLAUDE_HOME, ".config", "claude", ".credentials.json"),
        "/data/.config/claude/.credentials.json",
    ) if p
]

# The panel's own store, and the file `ha login` shares with other add-ons.
# Shape: {"type": "oauth_token"|"api_key", "value": "<str>", ...}
BRAIN_AUTH_PATHS = [
    (os.path.join(os.environ.get("BRAIN_SECRETS", "/data/secrets"),
                  "claude_auth.json"), "panel"),
    (os.environ.get("BRAIN_SHARED_AUTH",
                    "/config/.brain/secrets/claude_auth.json"), "ha login"),
]


# ---------------------------------------------------------------------------
# OAuth token discovery
# ---------------------------------------------------------------------------

def find_oauth_token(state=None):
    """Find brAIn's OAuth access token, wherever it was signed in.

    Returns the token, or None. **It returns the token and nothing else.**
    Naming the store it came from is useful in the log, but a label that
    rides home in the same tuple as a credential is a label nothing can
    tell apart from the credential — not a reader skimming the call site,
    not a scanner, and not whoever swaps the order in a year's time. So the
    store is logged here, where it is a literal at the point it is known,
    and never handed back. Why there is *no* token is a separate question
    with a separate answer: see credential_problem().
    """
    for path in CREDENTIAL_PATHS:
        token = _read_token_from_file(path)
        if token:
            _note_source(state, "claude cli")
            return token

    for path, label in BRAIN_AUTH_PATHS:
        data = _load_brain_auth(path)
        if _auth_kind(data) == "oauth_token":
            value = _auth_value(data)
            if value:
                _note_source(state, label)
                return value
    return None


def credential_problem():
    """Why there is no usable OAuth credential, as a fixed status string.

    Only ever called once find_oauth_token has come back empty, so nothing
    on this path has read a credential value — it reads `type` and stops.
    An API key is a different problem to no sign-in at all: it bills per
    token and has no subscription window, so there is no utilization to
    report and never will be, and telling someone to sign in again is
    telling them to redo the thing that worked.
    """
    for path, _label in BRAIN_AUTH_PATHS:
        if _auth_kind(_load_brain_auth(path)) == "api_key":
            return "api_key_has_no_usage_limits"
    return "no_oauth_token"


def _note_source(state, label):
    """Log which store answered, once, not every two minutes."""
    if state is None:
        return
    if state.get("auth") != label:
        sys.stderr.write(f"usage-limits-tracker: using the {label} credential\n")
        state["auth"] = label


def _read_token_from_file(path):
    """Read the OAuth access token from a credentials JSON file."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    # Standard format: {"claudeAiOauth": {"accessToken": "sk-ant-oat01-..."}}
    oauth = data.get("claudeAiOauth")
    if isinstance(oauth, dict):
        token = oauth.get("accessToken")
        if isinstance(token, str) and token.strip():
            return token.strip()

    # Fallback: check for a flat "accessToken" key
    token = data.get("accessToken")
    if isinstance(token, str) and token.strip():
        return token.strip()

    return None


def _load_brain_auth(path):
    """One of brAIn's own credential files as a dict, or None.

    Split from the two readers below so that asking *what kind* of
    credential a store holds never goes near the value it holds.
    """
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _auth_kind(data):
    """"oauth_token" | "api_key" | None — the type, never the secret."""
    if not isinstance(data, dict):
        return None
    kind = data.get("type")
    return kind if kind in ("oauth_token", "api_key") else None


def _auth_value(data):
    """The credential itself. Everything this returns is secret."""
    if not isinstance(data, dict):
        return None
    value = data.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


# ---------------------------------------------------------------------------
# Anthropic API
# ---------------------------------------------------------------------------

def fetch_usage_limits(token):
    """Fetch account usage limits from the Anthropic API.

    Returns (data, error): exactly one of them is set. The error is a short
    code the sensors can show, because "unavailable" with no reason is the
    one thing a person cannot act on.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "brain/1.0",
    }

    req = urllib.request.Request(ANTHROPIC_USAGE_URL, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body), None
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
        # 401 is its own answer: the token was found and refused, which is a
        # different thing to fix than a token that was never there.
        return None, f"http_{status}"
    except (urllib.error.URLError, OSError) as exc:
        sys.stderr.write(f"usage-limits-tracker: network error: {exc}\n")
        return None, "network_error"
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"usage-limits-tracker: invalid JSON response: {exc}\n")
        return None, "invalid_response"


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

def _last_reading_is_fresh():
    """True when the file already holds real numbers that aren't stale yet.

    A transient failure — a dropped connection, a 500 — must not turn four
    working sensors unavailable for one poll. When the last reading is still
    inside the staleness window it is left alone and simply ages out if the
    failures keep coming, which the sensors treat as unavailable anyway. The
    file is never rewritten with an older timestamp than it already has, so
    "still fresh" cannot be extended by failing.
    """
    try:
        with open(USAGE_FILE) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or "error" in data:
        return False
    if not any(k in data for k in ("five_hour", "seven_day")):
        return False
    stamp = data.get("updated_at")
    if not isinstance(stamp, str):
        return False
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - when).total_seconds()
    return age < STALE_AFTER_S


def run_once(state):
    """Fetch usage limits and write to file. Returns True on success."""
    token = find_oauth_token(state)
    if not token:
        problem = credential_problem()
        if state.get("auth") != problem:
            sys.stderr.write(
                f"usage-limits-tracker: no usable OAuth credential ({problem}) — "
                "sign in from the panel, the terminal, or with `ha login`\n"
            )
            state["auth"] = problem
        write_error_status(problem)
        return False

    data, error = fetch_usage_limits(token)
    if data is None:
        if not _last_reading_is_fresh():
            write_error_status(error)
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
    # Which credential store answered last time, so the log says so once
    # rather than every two minutes.
    state = {}

    while True:
        try:
            success = run_once(state)
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
                # Announce the slowdown once, on the poll that causes it —
                # `>=` here logged the same line every five minutes forever.
                if consecutive_failures == 5:
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
