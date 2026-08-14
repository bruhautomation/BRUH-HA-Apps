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

**This endpoint is polled gently, and the reason is the endpoint.** It is
undocumented, it is rate-limited far harder than anything else brAIn
touches, and a token that gets hammered on it answers 429 with quota to
spare and keeps doing so long after the window that supposedly caused it
(anthropics/claude-code#30930, #31021, #31637). Claude Code's own client
calls it *on demand only*, from the `/usage` screen, never on a timer.

**And it appears to meter per day, not per burst.** Polling every two
minutes gave about nine working hours and then a wall of 429s until the
small hours — a fixed nightly recovery, which is a daily allowance being
spent by mid-morning and not a burst limit that would clear in minutes.
That is why the interval is measured in half hours rather than minutes,
and why the 429 backoff is measured in hours: against a daily cap the only
lever is the total number of requests in a day. Four rules hold here, and
each is a bug that happened — a credential is offered **once** however
many paths lead to it; the poll is slow enough to fit a day inside the
cap; a 429 buys hours of silence, never the ordinary cadence; and
`Retry-After` may only ever lengthen that silence, because the endpoint
sends `Retry-After: 0` while still refusing, so obeying it literally is
how a tracker retries straight back into the limit it was just told about.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CLAUDE_HOME = os.environ.get("BRAIN_HOME") or os.environ.get("HOME", "/data/home")
CLAUDE_CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR", "")
USAGE_FILE = "/config/.brain/usage_limits.json"
# Every 30 minutes — 48 requests a day. Not a comfort setting: the endpoint
# appears to meter per *day*, not per burst. Polling every 2 minutes bought
# roughly nine hours of working sensors and then a 429 wall until the small
# hours, which is a day's allowance spent by mid-morning and is what a fixed
# nightly recovery time means. Every 5 minutes is 288 requests and still
# over. What this costs is resolution nobody can see: the five-hour window
# moves about 1% every three minutes at a hard sprint, so a half-hourly
# reading is never more than a percent or two behind the truth, and a
# sensor that is slightly behind all day beats one that is exactly right
# until 10am and unavailable after it.
POLL_INTERVAL = int(os.environ.get("USAGE_LIMITS_INTERVAL", "1800"))  # seconds
# How long a reading stays usable when polls start failing. Matches
# usage_store.LIMITS_MAX_AGE_S, which is the panel's own staleness rule for
# the same file — two answers to "is this still true" would be one too many.
STALE_AFTER_S = 2 * 3600
# Treat a credential expiring within the next minute as already gone, so a
# token cannot die between being chosen and being used.
EXPIRY_SKEW_S = 60
# Statuses that are settled facts about the sign-in rather than weather.
# These overwrite a good reading; a network blip does not. A 429 is
# deliberately absent: it says nothing about the sign-in, so it must not
# blank four working sensors — it lets the last reading age out instead.
AUTH_PROBLEMS = ("no_oauth_token", "api_key_has_no_usage_limits", "http_401")
# What to wait after consecutive 429s. Being rate-limited is not an error to
# retry at the ordinary cadence: retrying is what sustains it, so each strike
# buys real quiet, and the last value repeats forever rather than growing
# without bound. Every step is longer than POLL_INTERVAL, or "backing off"
# would mean asking sooner than usual — the reason these are hours and not
# the 15/30/60 minutes they started as. Hours also suit what the evidence
# says the limit is: if a day's allowance is gone, the next honest attempt
# is a long way off, and four wasted requests spread over an evening is a
# cheap way to notice the moment it comes back.
RATE_LIMIT_BACKOFF_S = (3600, 7200, 14400)
# A ceiling on a server-supplied Retry-After, so one absurd header cannot
# park the tracker for a day.
RETRY_AFTER_MAX_S = 6 * 3600
# What to wait after five consecutive failures that are *not* rate limits.
# Also longer than POLL_INTERVAL, for the same reason.
FAILURE_BACKOFF_S = 3600
# What a status means, for the diagnostic sensor to show beside it. HA hides
# an unavailable entity's attributes, so a code with no gloss is a code the
# one person who needs it reads on a support thread instead.
ERROR_DETAIL = {
    "http_429": (
        "Anthropic rate-limited the usage endpoint itself — this is not your "
        "account's usage, and no amount of quota clears it. brAIn has backed "
        "off and will pick the reading up again on its own."
    ),
}

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

def oauth_tokens(state=None):
    """Yield every OAuth token brAIn could authenticate with, best first.

    Yields the token and nothing else. **It never yields a label beside
    one.** Naming the store is useful in the log, but a label that travels
    with a credential is a label nothing can tell apart from the credential
    — not a reader skimming the call site, not a scanner, and not whoever
    swaps the order in a year. So the store is logged here, where it is a
    literal at the point it is known, and never handed out.

    It yields *all* of them rather than the first, because "found a token"
    and "found a token that works" are different claims and only the second
    one matters. Why there is none at all is a separate question with a
    separate answer: see credential_problem().

    **Each distinct credential is yielded once.** The caller retries the
    next one on a 401, so a duplicate is not a second chance — it is the
    same rejected request sent again with no pause, which is exactly what
    gets a token flagged on an endpoint this sensitive. And duplicates were
    the normal case, not the edge: run.sh exports CLAUDE_CONFIG_DIR as
    $BRAIN_HOME/.claude, making the first two CREDENTIAL_PATHS the *same
    string*, and symlinks $BRAIN_HOME/.config/claude onto /data/.config/claude,
    making the other two the same file. One sign-in, four identical requests
    per poll, every poll. Paths are collapsed by realpath and credentials by
    value, because the three stores can equally well hold one token that
    arrived by three routes.
    """
    seen_paths = set()
    seen_tokens = set()

    def unseen(token):
        """True the first time this exact credential is offered.

        Compared by value. This was a SHA-256 digest first, on the instinct
        that a set of live credentials is a copy of the secret — and it is
        not: a Python string goes into a set by reference, so the digest
        bought no fewer copies of the token than the token does, and cost a
        hash of a credential for it. CodeQL read that hash as password
        storage, which it never was, but a scanner asking why a token is
        being hashed at all is asking the right question of the wrong line.
        The set is local to one pass, holds at most a handful of entries,
        and dies with the generator.
        """
        if token in seen_tokens:
            return False
        seen_tokens.add(token)
        return True

    def unread(path):
        """True the first time this file is read, symlinks resolved."""
        real = os.path.realpath(path)
        if real in seen_paths:
            return False
        seen_paths.add(real)
        return True

    for path in CREDENTIAL_PATHS:
        if not unread(path):
            continue
        token = _read_token_from_file(path)
        if token and unseen(token):
            _note_source(state, "claude cli")
            yield token

    for path, label in BRAIN_AUTH_PATHS:
        if not unread(path):
            continue
        data = _load_brain_auth(path)
        if _auth_kind(data) == "oauth_token":
            value = _auth_value(data)
            if value and unseen(value):
                _note_source(state, label)
                yield value


def find_oauth_token(state=None):
    """The first credential worth trying, or None."""
    return next(oauth_tokens(state), None)


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
    """Log which store answered, once, not every poll."""
    if state is None:
        return
    if state.get("auth") != label:
        sys.stderr.write(f"usage-limits-tracker: using the {label} credential\n")
        state["auth"] = label


def _oauth_expired(oauth):
    """True when this credential's own expiry has already passed.

    Claude Code refreshes its token itself, but a revoked session, a
    container that was down past the expiry, or a refresh that errored
    mid-flight all leave a well-formed *dead* token on disk. Treating one
    as authoritative because it is shaped right is what makes a working
    credential in the next store unreachable.

    A missing or zero expiry means the file does not record one — not that
    the token is past it.
    """
    expires = oauth.get("expiresAt")
    if not isinstance(expires, (int, float)) or expires <= 0:
        return False
    return expires / 1000.0 <= time.time() + EXPIRY_SKEW_S


def _read_token_from_file(path):
    """Read a live OAuth access token from a credentials JSON file."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    # Standard format: {"claudeAiOauth": {"accessToken": "sk-ant-oat01-..."}}
    oauth = data.get("claudeAiOauth")
    if isinstance(oauth, dict) and not _oauth_expired(oauth):
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

# Where fetch_usage_limits leaves the server's Retry-After for the sleep at
# the bottom of the loop to read. A module-level holder rather than a third
# return value because the hint is advice about *waiting* and every caller
# and test of fetch_usage_limits is about the (data, error) answer — widening
# that pair everywhere to carry a number only one line reads is the worse
# trade. Cleared at the start of each poll so a stale hint cannot outlive
# the response it came with.
_retry_after = {"seconds": None}


def _parse_retry_after(headers):
    """Retry-After as seconds from now, or None.

    RFC 9110 allows either a delay in seconds or an HTTP-date, and both turn
    up in the wild, so both are read. Anything unparseable is None: no hint
    is a better answer than a wrong one, since the schedule works without it.
    """
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except AttributeError:
        return None
    if raw is None:
        return None
    raw = str(raw).strip()
    if not raw:
        return None

    try:
        return max(0.0, float(int(raw)))
    except ValueError:
        pass

    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


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
            # An error body we cannot read leaves the status code to speak for
            # itself, which the line below prints.
            pass
        sys.stderr.write(
            f"usage-limits-tracker: HTTP {status} from Anthropic API: {body}\n"
        )
        if status == 429:
            _retry_after["seconds"] = _parse_retry_after(
                getattr(exc, "headers", None)
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


def _record_failure(error, delay_s, strikes=0):
    """Leave the reason for a failed poll beside whatever the file holds.

    A failure that leaves a fresh reading alone (deliberate — see run_once)
    used to leave nothing at all: the reading aged out, four sensors went
    unavailable, and the *why* was only written on the next attempt — which
    during a four-hour 429 backoff is hours after the person is looking at
    an unexplained "stale". These keys ride beside the reading without
    touching the numbers or their timestamp, so staleness still ages from
    the real reading; the diagnostic sensor can name the reason the moment
    the reading goes stale; and a restart can honour a promise of quiet
    made before it (see _resume_backoff). A successful poll rewrites the
    file whole, which is what clears them.
    """
    try:
        with open(USAGE_FILE) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        data = {}
    now = datetime.now(timezone.utc)
    data["last_error"] = error
    data["last_error_at"] = now.isoformat()
    data["next_attempt_at"] = (now + timedelta(seconds=delay_s)).isoformat()
    detail = ERROR_DETAIL.get(error)
    if detail:
        data["last_error_detail"] = detail
    else:
        data.pop("last_error_detail", None)
    if strikes:
        data["rate_limit_strikes"] = strikes
    else:
        data.pop("rate_limit_strikes", None)
    tmp = USAGE_FILE + ".tmp"
    try:
        os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, USAGE_FILE)
    except OSError:
        # Same rule as write_error_status: a failed write leaves whatever
        # was there to age out.
        pass


def _resume_backoff():
    """(seconds still owed to a pre-restart 429 backoff, strikes to resume).

    Backoff used to live only in memory, so restarting the add-on — the
    first thing anyone does when sensors go unavailable — polled the
    endpoint immediately and restarted the ladder from its first rung,
    which against a daily meter is retrying straight back into the limit.
    Only a rate limit's quiet is resumed: every other failure is cheap to
    re-ask about, and a restart asking straight away is the right default.
    """
    try:
        with open(USAGE_FILE) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return 0.0, 0
    if not isinstance(data, dict):
        return 0.0, 0
    if "http_429" not in (data.get("last_error"), data.get("error")):
        return 0.0, 0
    raw = data.get("next_attempt_at")
    if not isinstance(raw, str):
        return 0.0, 0
    try:
        when = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return 0.0, 0
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    remaining = (when - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        return 0.0, 0
    strikes = data.get("rate_limit_strikes")
    strikes = strikes if isinstance(strikes, int) and strikes > 0 else 1
    return min(remaining, RETRY_AFTER_MAX_S), strikes


def write_error_status(error_msg, detail=None):
    """Write an error status file so sensors know what's wrong."""
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    output = {
        "source": "anthropic_api",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "error": error_msg,
    }
    if detail:
        output["detail"] = detail
    tmp = USAGE_FILE + ".tmp"
    try:
        with open(tmp, "w") as fh:
            json.dump(output, fh, indent=2)
        os.replace(tmp, USAGE_FILE)
    except OSError:
        # The sensors read this file. A failed write leaves the previous
        # reading to age out, which is what the two-hour window is for.
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


def _fetch_with_any_credential(state):
    """Try each credential in turn until one is accepted → (data, error).

    A 401 ends that credential, not the search. brAIn can hold a stale
    token in one store and a working sign-in in another, and stopping at
    the first refusal is what let the dead one speak for all of them.
    Anything other than a 401 is about the request rather than the
    credential, so it stops here.
    """
    _retry_after["seconds"] = None
    data = error = None
    for token in oauth_tokens(state):
        data, error = fetch_usage_limits(token)
        if error != "http_401":
            return data, error
        sys.stderr.write(
            "usage-limits-tracker: that credential was refused, "
            "trying the next store\n"
        )
    return data, (error or credential_problem())


def run_once(state):
    """Fetch usage limits and write to file → (succeeded, error).

    The error comes back rather than just a bool because the loop's next
    sleep depends on *which* failure this was: a rate limit has to be waited
    out, and everything else is retried at the ordinary cadence.
    """
    data, error = _fetch_with_any_credential(state)

    if data is None:
        if error in AUTH_PROBLEMS and state.get("auth") != error:
            sys.stderr.write(
                f"usage-limits-tracker: no usable OAuth credential ({error}) — "
                "sign in from the panel, the terminal, or with `ha login`\n"
            )
            state["auth"] = error
        # A settled fact about the sign-in is worth saying even over good
        # numbers; a blip waits for the reading to age out instead.
        if error in AUTH_PROBLEMS or not _last_reading_is_fresh():
            write_error_status(error, ERROR_DETAIL.get(error))
        return False, error

    if "error" in data:
        sys.stderr.write(
            f"usage-limits-tracker: API error: {data.get('error')}\n"
        )
        write_error_status(str(data.get("error")))
        return False, str(data.get("error"))

    write_usage(data)
    return True, None


def _rate_limit_delay(strikes, retry_after):
    """How long to stay off the endpoint after `strikes` consecutive 429s.

    The schedule is a floor the server may raise and never lower. This
    endpoint answers `Retry-After: 0` while still refusing, so a tracker
    that obeys the header literally retries straight back into the limit it
    was just told about — and each of those retries is what keeps the limit
    in place.
    """
    step = RATE_LIMIT_BACKOFF_S[min(strikes, len(RATE_LIMIT_BACKOFF_S)) - 1]
    if isinstance(retry_after, (int, float)) and retry_after > step:
        return min(float(retry_after), RETRY_AFTER_MAX_S)
    return float(step)


def main():
    sys.stderr.write(
        f"usage-limits-tracker: starting (interval={POLL_INTERVAL}s)\n"
    )

    # A rate-limit backoff promised before a restart is still owed after it.
    resumed_delay, rate_limit_strikes = _resume_backoff()
    # Initial backoff for first attempt — give Claude Code time to authenticate
    initial_delay = max(10, resumed_delay)
    if resumed_delay:
        sys.stderr.write(
            "usage-limits-tracker: resuming the rate-limit backoff from "
            f"before the restart — waiting {initial_delay / 60:.0f} minutes\n"
        )
    else:
        sys.stderr.write(
            f"usage-limits-tracker: waiting {initial_delay}s for Claude Code auth...\n"
        )
    time.sleep(initial_delay)

    consecutive_failures = 0
    # Consecutive 429s. Separate from the count above because a rate limit
    # is the one failure that retrying makes worse. Seeded by _resume_backoff
    # so a restart mid-wall picks the ladder up where it left it.
    last_logged = None
    # Which credential store answered last time, so the log says so once
    # rather than every poll.
    state = {}

    while True:
        try:
            success, error = run_once(state)
            if success:
                consecutive_failures = 0
                rate_limit_strikes = 0
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
                    # Logging a change in utilisation must not end the poll loop.
                    pass
            else:
                consecutive_failures += 1
                if error == "http_429":
                    rate_limit_strikes += 1
                else:
                    rate_limit_strikes = 0
                # Announce the slowdown once, on the poll that causes it —
                # `>=` here logged the same line every five minutes forever.
                # A rate limit says its own piece below, with a number.
                if consecutive_failures == 5 and not rate_limit_strikes:
                    sys.stderr.write(
                        "usage-limits-tracker: 5 consecutive failures, "
                        f"backing off to {FAILURE_BACKOFF_S // 60} minutes\n"
                    )
        except Exception as exc:
            sys.stderr.write(f"usage-limits-tracker: error: {exc}\n")
            success, error = False, "tracker_error"
            consecutive_failures += 1
            rate_limit_strikes = 0

        if rate_limit_strikes:
            delay = _rate_limit_delay(rate_limit_strikes,
                                      _retry_after["seconds"])
            # Every strike up to the cap lengthens the wait, so each one is
            # news; past the cap the number stops changing and so does the
            # log, rather than repeating the same line forever.
            if rate_limit_strikes <= len(RATE_LIMIT_BACKOFF_S):
                sys.stderr.write(
                    "usage-limits-tracker: rate-limited by the usage endpoint "
                    f"(not your account's usage) — waiting {delay / 60:.0f} "
                    "minutes before asking again\n"
                )
        elif consecutive_failures >= 5:
            delay = FAILURE_BACKOFF_S
        else:
            delay = POLL_INTERVAL

        if not success:
            # The reason and the next attempt, on disk, before the wait —
            # not on the attempt after it.
            _record_failure(error or "tracker_error", delay,
                            rate_limit_strikes)

        time.sleep(delay)


if __name__ == "__main__":
    main()
