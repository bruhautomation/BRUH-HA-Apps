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

**The endpoint sorts callers into rate-limit buckets by User-Agent, and
only Claude Code's own UA gets the usable one.** This tracker used to
introduce itself as `brain/1.0`, which put every poll in the bucket the
endpoint reserves for strangers: a wall of 429s after a few hours, with
quota to spare, persisting long after whatever window supposedly caused it
(anthropics/claude-code#30930, #31021, #31637 — every reporter was calling
it without the CLI's UA). The tools that poll this endpoint sustainably at
minute-scale intervals are the ones sending the UA the CLI sends. The
earlier "it meters per day" reading of this endpoint was that hostile
bucket being measured from inside; the right bucket does not behave that
way.

**Claude Code sends two different User-Agents, and sending the wrong one
of them is the same bug wearing an official-looking name.** Its
Messages-API client sends `claude-cli/<version> (external, cli)`; the
helper that fetches utilization sends `claude-code/<version>`. The usage
endpoint only ever sees the second. The first attempt at this fix read the
bundle, found the SDK's `getUserAgent()`, and sent *that* — so every poll
went on landing in the stranger bucket, the wall never lifted, and the
sensors went on ageing out into unavailable every couple of hours with the
fix already shipped. In the bundle the caller is `Hqq()` and the header it
sets is `jH()`, which is `claude-code/${VERSION}` and nothing else.

Identifying as Claude Code is not spoofing here: the tracker reports on the
account the *installed* Claude Code is signed into, using that install's
own credential, on that credential's behalf — it is that install's version
it names, discovered from `claude --version` at runtime.

Four rules still hold, each a bug that happened — a credential is offered
**once** however many paths lead to it; the poll is measured in minutes,
not seconds (Claude Code itself asks only on demand, so a timer is already
more than it needs); a 429 buys hours of silence, never the ordinary
cadence, because retrying a 429 is what sustains it; and `Retry-After` may
only ever lengthen that silence, because the endpoint sends
`Retry-After: 0` while still refusing, so obeying it literally is how a
tracker retries straight back into the limit it was just told about.
"""

import json
import os
import re
import subprocess
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
# Every 5 minutes. The interval was 30 minutes for as long as the tracker
# introduced itself as `brain/1.0` — the wrong User-Agent put it in the
# endpoint's hostile rate-limit bucket, where 2-minute polling bought nine
# working hours and then a 429 wall, which read as a daily meter. With the
# CLI's own UA (see user_agent below) the endpoint serves the statusline
# ecosystem at 1–5 minute cadences sustainably; 5 minutes keeps the sensors
# close to live (the five-hour window moves ~1% every three minutes at a
# hard sprint) while still asking for far less than the tools that poll on
# every keystroke's response. The hour-scale 429 ladder below stays as the
# safety net either way.
POLL_INTERVAL = int(os.environ.get("USAGE_LIMITS_INTERVAL", "300"))  # seconds
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
# The scope refusal, which is a settled fact about *which sign-in was used*
# rather than about the account: `claude setup-token` — what `ha login` is
# built on, deliberately, because a session credential refreshes itself and
# cannot be published to a shared file — mints a token whose scopes are
# `user:inference user:ccr_inference user:file_upload`. The usage endpoint
# requires `user:profile`, which only the interactive `claude /login` flow
# asks for. So the token runs Claude perfectly and can never read a usage
# figure, and no amount of retrying, backing off or re-running `ha login`
# changes that.
SCOPE_ERROR = "oauth_token_lacks_usage_scope"
AUTH_PROBLEMS = ("no_oauth_token", "api_key_has_no_usage_limits", "http_401",
                 SCOPE_ERROR)
# A bare `http_403` is deliberately NOT in that list. The narrowed code above
# is a verdict we can read; an unattributed 403 is "I could not tell why",
# and "I could not tell" must not blank four readings that are still true.
# It gets a gloss and a vocabulary entry instead, so it is never bare.
# What to wait after consecutive 429s. Being rate-limited is not an error to
# retry at the ordinary cadence: retrying is what sustains it, so each strike
# buys real quiet, and the last value repeats forever rather than growing
# without bound. Every step is longer than POLL_INTERVAL, or "backing off"
# would mean asking sooner than usual. Hour-scale on purpose even now the
# poll is minutes: a 429 in the CLI's bucket is rare and means something is
# genuinely wrong (a changed policy, a flagged token), and a few wasted
# requests spread over an evening is a cheap way to notice the moment it
# comes back.
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
    SCOPE_ERROR: (
        "The signed-in token can run Claude but is not allowed to read "
        "usage limits: `claude setup-token`, which `ha login` is built on, "
        "mints a token without the `user:profile` scope this endpoint "
        "requires. Retrying cannot clear it and neither can running "
        "`ha login` again. Run `claude /login` in the Terminal tab — the "
        "interactive sign-in asks for that scope — and the numbers come "
        "back on the next poll."
    ),
    "http_403": (
        "Anthropic refused this credential permission to read usage limits "
        "and did not say why. Signing in again with `claude /login` in the "
        "Terminal tab is what usually fixes it."
    ),
    "http_429": (
        "Anthropic rate-limited the usage endpoint itself — this is not your "
        "account's usage, and no amount of quota clears it. brAIn has backed "
        "off and will pick the reading up again on its own."
    ),
}

# How much of an error body to keep. The log line takes 200 characters of
# it, and for a while that truncation was the whole read — which the scope
# refusal survives by fifty characters and nothing more: its `error_code`
# sits at character 150 of a 191-character body, and one extra required
# scope named in the message pushes it past the cut. A parse that works on
# the bodies short enough to fit is the shape of bug this file keeps
# finding, so the parse gets the whole (bounded) body and the log its 200.
ERROR_BODY_MAX = 4096
ERROR_BODY_LOG = 200
# The API's own `error_code`, where it names one, mapped to this tracker's
# vocabulary. It only ever *narrows* a status we already have: a code that
# is not on this list leaves `http_<status>` exactly as it was, because a
# verdict invented from an unrecognised string is worse than the status.
API_ERROR_CODES = {
    "oauth_scope_insufficient": SCOPE_ERROR,
}
# A refusal that ends this credential and moves the search to the next
# store. A 403 is as much "wrong credential, try the other one" as a 401 —
# same shape as the 401-stops-the-search bug oauth_tokens() was written to
# end, and it took a scope refusal to notice the other half of it.
CREDENTIAL_REFUSALS = ("http_401", "http_403", SCOPE_ERROR)
# ...and the subset that can never answer differently while the credential
# itself is unchanged. A 401 is not on this list on purpose: an expired
# token and a five-minute server hiccup are refused identically, and
# blacklisting a credential for the life of the process over the second is
# how a working sign-in stays unread. A scope verdict is structural.
SETTLED_REFUSALS = (SCOPE_ERROR,)

ANTHROPIC_USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

# The endpoint buckets its rate limits by User-Agent: the UA Claude Code
# itself sends gets the bucket the statusline ecosystem polls sustainably,
# and everything else gets the one that answers 429 after a handful of
# requests and stays that way. `brain/1.0` — this tracker's old UA — is what
# put every install in the second bucket, which surfaced as sensors that
# went dark by mid-morning whatever the poll interval was; `claude-cli/…
# (external, cli)`, its replacement, is the CLI's *Messages-API* UA and
# lands in exactly the same bucket, which is why nothing changed. The one
# the usage endpoint wants is `claude-code/<version>` (see user_agent()).
# This is the one place brAIn deliberately does NOT introduce itself by its
# own name: the request is made with the installed CLI's credential on that
# install's behalf, so it carries that install's version, discovered from
# the binary at runtime. The fallback is a real shipped CLI version for the
# case where the binary cannot be asked — a stale-but-real version stays in
# the right bucket, where an invented one might not.
UA_FALLBACK_CLI_VERSION = "2.1.252"
# Where the add-on keeps the CLI it updates at boot (run.sh), then PATH.
# **The same list `engine.CLAUDE_BIN_CANDIDATES` walks, in the same order**,
# because "where does the Claude CLI live" having two answers is how one of
# them goes stale: run.sh installs the native binary under the `claude`
# user's home and the image symlinks it into `/root/.local/bin`, and
# neither is on the default PATH — so a probe that only tries the bare name
# resolves to nothing on a working install. The panel's own version probe
# had exactly that and reported `unknown` in every bug report from a house
# whose Claude was running perfectly; it goes through
# `engine.resolve_claude_bin()` now, and this list is the same one written
# where a standalone script can read it (`tests/test_usage_tracker.py`
# compares the two, so they cannot drift apart quietly).
CLI_PROBE_COMMANDS = (
    os.path.join(os.environ.get("BRAIN_HOME", "/data/home"),
                 ".local", "bin", "claude"),
    "/root/.local/bin/claude",
    "/usr/local/bin/claude",
    "claude",
)
# Read at import like every other env constant here (the tests' loader
# relies on that): a caller that already knows the installed version can
# hand it over and skip the probe entirely.
PINNED_CLI_VERSION = os.environ.get("BRAIN_CLI_VERSION", "").strip()
_ua_cache = {}


def _cli_version():
    """The installed Claude Code version, or a real fallback.

    `BRAIN_CLI_VERSION` short-circuits the probe (tests use it to stay
    hermetic). The probe itself is best-effort with a generous timeout — at
    add-on boot the binary may be cold on a slow disk — and any failure
    falls back rather than delaying the first poll forever.
    """
    if re.fullmatch(r"\d+\.\d+\.\d+", PINNED_CLI_VERSION):
        return PINNED_CLI_VERSION
    for cmd in CLI_PROBE_COMMANDS:
        try:
            proc = subprocess.run(
                [cmd, "--version"], capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.SubprocessError):
            continue
        match = re.search(r"\d+\.\d+\.\d+", proc.stdout or "")
        if match:
            return match.group(0)
    return UA_FALLBACK_CLI_VERSION


def user_agent():
    """The UA every poll sends, computed once per process.

    `claude-code/<version>` — the product name, not the SDK's. Claude Code
    sends **two different** User-Agents and the difference is the whole bug:
    its Messages-API client sends `claude-cli/<version> (external, cli)`,
    and the helper that fetches utilization sends `claude-code/<version>`.
    This tracker sent the first one to the second one's endpoint, which is
    the stranger bucket again under a name that merely looks official — so
    the 429 wall the previous fix was written to end never ended, and the
    sensors went on ageing out into unavailable every couple of hours.

    The version is the installed CLI's, probed from `claude --version`.
    Note it is an approximation on purpose: the CLI stamps a build-time
    constant into its own UA, which can lag the released version, and there
    is no way to read that constant without parsing the binary. (The figure
    once quoted here — 2.1.42 stamped inside a 2.1.252 bundle — came from a
    stale npm copy left on the box, not from the CLI the add-on runs: the
    shipped native binary stamps its own version, and the UA this sends has
    been checked against it.) The product prefix is what the bucket is keyed
    on; a real, current version behind it is the honest way to fill the rest.

    Cached because the probe spawns the CLI binary, and once per process is
    all the answer can change: run.sh updates the CLI before starting this
    tracker, never while it runs.
    """
    if "ua" not in _ua_cache:
        _ua_cache["ua"] = f"claude-code/{_cli_version()}"
    return _ua_cache["ua"]

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


def _say_once(state, key, message):
    """Write a line the first time this state has something new to say.

    Same job as _note_source and a separate ledger from it: what answered
    and what refused are different facts, and one key holding both would
    make each of them re-announce the other.
    """
    if state is None:
        sys.stderr.write(message)
        return
    said = state.setdefault("said", set())
    if key not in said:
        said.add(key)
        sys.stderr.write(message)


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
        # Not the delay-seconds form. That is the other half of what RFC 9110
        # allows, not a failure, so it falls through to the HTTP-date parse
        # below and only a value neither form accepts ends up as None.
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


def _error_code(status, body):
    """`http_<status>`, narrowed by the API's own error_code where it has one.

    The bug this exists for: a 403 arrived as a bare `http_403` — a code in
    no table, with no gloss, in nothing's documented vocabulary — and the
    tracker retried it hourly forever against a condition that can never
    clear. The status alone genuinely cannot tell those apart; the body can,
    and says `oauth_scope_insufficient` in as many words.

    It only ever narrows. An unreadable body, a body that is not JSON, a
    shape that carries no code, or a code this does not recognise all leave
    the status untouched — an invented verdict reads exactly like a real one
    and is the harder failure to notice.

    **And the envelope is one level deeper than this first read for it.**
    What the field actually sends is Anthropic's standard error shape —
    ``{"type": "error", "error": {"type": …, "message": …, "details": …}}``
    — where the first cut looked for ``details`` and ``error_code`` at the
    top level and found neither, so the one refusal this whole narrowing
    exists for came back `http_403` anyway: no gloss, not in `AUTH_PROBLEMS`,
    never settled, retried hourly for ever against a verdict that cannot
    change. A fix that could not fire is the same class as the `pop` that
    did not case-fold — the machinery was right and the path into the body
    was wrong — and the tests could not see it because they wrote the shape
    down from the same guess the code did, which is what makes a fixture
    copied from a real response the load-bearing part of this.

    **There is no `error_code` in that body at all**, which is why the
    structured scope field has to be read as well: `details.required_scopes`
    is the endpoint saying, in as many words, which scope it wanted and did
    not get, and that is exactly the claim `SCOPE_ERROR` makes. It is not an
    invented verdict — it is a documented field read literally. The message
    text is deliberately NOT matched: prose is what gets reworded, and the
    structured field is present in every refusal seen.
    """
    fallback = f"http_{status}"
    if not body:
        return fallback
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return fallback
    if not isinstance(parsed, dict):
        return fallback
    # The envelope's own `error` object first, then the top level: neither
    # placement is documented, and one file reading both is cheaper than a
    # release that misses the day it moves. Every real refusal seen has
    # been the nested one.
    scopes = ["error_code"]
    holders = [parsed]
    inner = parsed.get("error")
    if isinstance(inner, dict):
        holders.insert(0, inner)
    code = None
    for holder in holders:
        details = holder.get("details")
        for where in ((details if isinstance(details, dict) else {}), holder):
            for key in scopes:
                value = where.get(key)
                if isinstance(value, str) and value:
                    code = code or value
    if isinstance(code, str) and code:
        narrowed = API_ERROR_CODES.get(code)
        if narrowed:
            return narrowed
    # No code anywhere — which is the ordinary case, because this endpoint
    # does not send one. `required_scopes` is the fact itself.
    if status == 403 and _names_a_missing_scope(holders):
        return SCOPE_ERROR
    return fallback


def _names_a_missing_scope(holders):
    """Whether the body names a scope the endpoint required and did not get.

    `details.required_scopes` is a list of scope names. Its presence on a
    403 IS the scope refusal — there is nothing else a required-scopes list
    on a permission denial can mean — so this narrows on the field rather
    than on the sentence wrapped around it.
    """
    for holder in holders:
        details = holder.get("details")
        if not isinstance(details, dict):
            continue
        wanted = details.get("required_scopes")
        if isinstance(wanted, list) and any(
                isinstance(name, str) and name for name in wanted):
            return True
    return False


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
        # The rate-limit bucket rides on this header — see user_agent().
        "User-Agent": user_agent(),
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
            body = exc.read().decode("utf-8", errors="replace")[:ERROR_BODY_MAX]
        except Exception:
            # An error body we cannot read leaves the status code to speak for
            # itself, which the line below prints.
            pass
        sys.stderr.write(
            "usage-limits-tracker: HTTP "
            f"{status} from Anthropic API: {body[:ERROR_BODY_LOG]}\n"
        )
        if status == 429:
            _retry_after["seconds"] = _parse_retry_after(
                getattr(exc, "headers", None)
            )
        # 401 is its own answer: the token was found and refused, which is a
        # different thing to fix than a token that was never there. A 403
        # answers a third question again — the token is real, live and
        # refused *this endpoint* — and only the body says which.
        return None, _error_code(status, body)
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


def _restate_next_attempt(delay_s, strikes):
    """Correct `next_attempt_at` to what this process will actually do.

    Every failure records when the tracker will ask again, and the panel's
    popover renders that to a person by the clock ("not broken, waiting,
    back at 9:40"). A restart deliberately re-asks sooner than most of
    those promises — see _resume_backoff — which left the file claiming a
    wait that was never going to happen, and left it there for as long as
    the next poll took. Restating it costs one write at boot and is the
    difference between a clock somebody can read and one they learn to
    ignore. Nothing is restated when there is no failure on record: a good
    reading has no promise to correct.
    """
    try:
        with open(USAGE_FILE) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    error = data.get("last_error") or data.get("error")
    if not isinstance(error, str) or not error:
        return
    _record_failure(error, delay_s, strikes)


def _resume_backoff():
    """(seconds still owed to a pre-restart 429 backoff, strikes to resume).

    Backoff used to live only in memory, so restarting the add-on — the
    first thing anyone does when sensors go unavailable — polled the
    endpoint immediately and restarted the ladder from its first rung,
    which against a daily meter is retrying straight back into the limit.

    Only a rate limit's quiet is resumed, and the tempting generalisation
    — every failure asking again cannot help, which would take in the auth
    problems — is **wrong**, because a restart is not a timer expiring: it
    is a person acting, and the thing they most often did first is sign in
    again. A rate limit is the one failure a restart cannot have changed;
    every other one it plausibly did, so re-asking once is right and the
    promise on disk has to be re-earned rather than served (see
    _restate_next_attempt, which stops that promise being a lie in the
    meantime).
    """
    try:
        with open(USAGE_FILE) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return 0.0, 0
    if not isinstance(data, dict):
        return 0.0, 0
    error = data.get("last_error") or data.get("error")
    if error != "http_429":
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

    A refusal ends that credential, not the search. brAIn can hold a stale
    token in one store and a working sign-in in another, and stopping at
    the first refusal is what let the dead one speak for all of them. That
    was written for a 401 and keyed on one; a 403 is the same claim — this
    credential is the wrong one — so it moves the search along too.

    Anything else is about the request rather than the credential (a
    network error, a 500, a rate limit), so it stops here: retrying it on a
    second token proves nothing and costs a request on an endpoint that
    counts them.

    **A settled refusal is remembered against the token that earned it.**
    A scope verdict cannot answer differently until the credential itself
    changes, so asking again with it is a request nobody will ever answer
    — which is exactly what the tracker did, hourly, for as long as the
    add-on ran. The memory is keyed on the credential rather than on the
    poll, so it costs nothing the moment a real sign-in lands: a new token
    is not in it and is tried on the very next poll. It holds one entry per
    distinct credential this box has ever offered, which is a handful.
    """
    _retry_after["seconds"] = None
    unusable = state.setdefault("unusable", {}) if state is not None else {}
    if state is not None:
        # Whether this pass put a request on the wire at all — see main().
        state["asked"] = False
    data = error = settled = None
    for token in oauth_tokens(state):
        if token in unusable:
            # Not a request. The verdict stands until the credential moves.
            settled = settled or unusable[token]
            continue
        if state is not None:
            state["asked"] = True
        data, error = fetch_usage_limits(token)
        if error not in CREDENTIAL_REFUSALS:
            return data, error
        if error in SETTLED_REFUSALS:
            unusable[token] = error
            settled = settled or error
            # Keyed apart from run_once's remedy line: "I have stopped
            # asking with this" and "here is what to do about it" are two
            # facts, and one key holding both prints whichever fires first.
            _say_once(state, f"skipping:{error}",
                      "usage-limits-tracker: that credential cannot read "
                      f"usage limits ({error}) — brAIn will not ask with it "
                      "again until a different sign-in lands\n")
        else:
            sys.stderr.write(
                "usage-limits-tracker: that credential was refused, "
                "trying the next store\n"
            )
    return data, (error or settled or credential_problem())


def run_once(state):
    """Fetch usage limits and write to file → (succeeded, error).

    The error comes back rather than just a bool because the loop's next
    sleep depends on *which* failure this was: a rate limit has to be waited
    out, and everything else is retried at the ordinary cadence.
    """
    data, error = _fetch_with_any_credential(state)

    if data is None:
        if error in AUTH_PROBLEMS:
            # Said once, on its own ledger. It used to be gated on
            # `state["auth"]` — which _note_source writes the answering
            # store's name into on every pass that yields a credential, so
            # the two keys overwrote each other and this line came back
            # every poll for the whole life of the problem.
            #
            # The remedy is per-error, because for one of them the general
            # advice is the wrong advice: `ha login` is what mints the
            # under-scoped token in the first place, so telling somebody to
            # run it again is telling them to reproduce the fault.
            _say_once(
                state, error,
                f"usage-limits-tracker: no usable OAuth credential ({error}) — "
                + ("run `claude /login` in the Terminal tab; `ha login` "
                   "cannot mint a token with the usage scope"
                   if error == SCOPE_ERROR else
                   "sign in from the panel, the terminal, or with `ha login`")
                + "\n"
            )
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
    # A working poll re-arms every once-only line: a problem that comes
    # back is news again, and a ledger nothing clears would swallow it.
    if state is not None:
        state.pop("said", None)
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


def _next_failure_count(count, asked):
    """The consecutive-failure count after a poll that did not succeed.

    The ladder exists to stop hammering an endpoint, and a pass that put no
    request on the wire — nothing signed in, or every credential already
    refused for good — hammered nothing and has nothing to back off from.
    Charging it would slide the poll to the hourly rung, which is to say it
    would put the one poll that notices a *new* sign-in an hour away, on
    exactly the recovery the failure message tells somebody to perform.
    """
    return count + 1 if asked else 0


def main():
    sys.stderr.write(
        f"usage-limits-tracker: starting (interval={POLL_INTERVAL}s)\n"
    )

    # A rate-limit backoff promised before a restart is still owed after it.
    resumed_delay, rate_limit_strikes = _resume_backoff()
    # Initial backoff for first attempt — give Claude Code time to authenticate
    initial_delay = max(10, resumed_delay)
    _restate_next_attempt(initial_delay, rate_limit_strikes)
    if resumed_delay:
        sys.stderr.write(
            "usage-limits-tracker: resuming the backoff promised before the "
            f"restart — waiting {initial_delay / 60:.0f} minutes\n"
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
                consecutive_failures = _next_failure_count(
                    consecutive_failures, state.get("asked"))
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
