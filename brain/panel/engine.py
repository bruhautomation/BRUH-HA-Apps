"""Claude CLI plumbing for brAIn.

Auth
----
Works with a Claude subscription (Pro/Max) — no API key required:
  * Guided flow: we drive `claude setup-token` over a pty, surface the OAuth
    URL in the panel, the user pastes the one-time code back, and we capture
    the resulting long-lived token (sk-ant-oat01-…).
  * Paste flow: the user runs `claude setup-token` anywhere (e.g. the BRUH
    Claude Terminal add-on) and pastes the token into the panel.
  * Shared login: the terminal's `ha login` writes a
    credential to /config/.brain/secrets/claude_auth.json; Insights
    picks it up automatically (read-only fallback, local creds win).
  * API key: a plain Anthropic API key also works, for users who prefer it.
The credential is stored at $BRAIN_SECRETS/claude_auth.json (0600)
and injected into the CLI environment (CLAUDE_CODE_OAUTH_TOKEN /
ANTHROPIC_API_KEY) on every run.

Generation
----------
`run_claude` shells out to `claude -p --output-format json` as the non-root
`claude` user (via su-exec when running as root). The caller supplies the
system prompt and user prompt; we parse the CLI's JSON envelope and return
the result text. `extract_json` then digs the insight object out of the
model's reply, tolerating stray code fences.

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import termios
import threading
import time
import uuid

import journal
import model_plan
import run_sources
import settings_store
import usage_store

log = logging.getLogger("brain.auth")

SECRETS_DIR = os.environ.get("BRAIN_SECRETS", "/data/secrets")
CLAUDE_HOME = os.environ.get("BRAIN_HOME", "/data/home")
AUTH_FILE = os.path.join(SECRETS_DIR, "claude_auth.json")
# Credential shared by the terminal (its `ha login` tool
# writes it to the /config volume, which we mount read-only). Insights only
# ever READS this file — logout must never touch it.
SHARED_AUTH_FILE = os.environ.get(
    "BRAIN_SHARED_AUTH", "/config/.brain/secrets/claude_auth.json")
# run.sh keeps the last known good copy of the CLI's own credential here and
# restores it whenever the live file has vanished. That is a fourth store in
# everything but name: it is not read to authenticate anything, but it is
# what the next boot puts back, so a sign-out that does not reach it is a
# sign-out the next restart undoes. The path is spelled here and in run.sh's
# `auth_backup_dir`, and `test_the_backup_path_is_the_one_run_sh_writes`
# holds the two together — a rename on one side only is otherwise silent.
AUTH_BACKUP_FILE = os.environ.get(
    "BRAIN_AUTH_BACKUP", "/data/.brain_auth_backup/.credentials.json")
# Touched while the guided sign-in is running and removed when it settles.
# The usage tracker renews the CLI's credential file itself now, and the
# flow below reads that file CHANGING as the code exchange having
# succeeded — so a renewal landing mid-flow would say "Connected!" about a
# code nothing had exchanged, which is `_signed_in_here`'s own bug in a
# new disguise. The tracker (`usage-limits-tracker.SIGNIN_HOLD_FILE`)
# spells the same path and writes nothing while the marker is fresh;
# `tests/test_usage_tracker.py` holds the two spellings together, the
# nudge file's rule.
SIGNIN_HOLD_FILE = os.environ.get("BRAIN_USAGE_SIGNIN_HOLD",
                                  "/data/usage-signin-hold")


def _hold_renewals() -> None:
    """Ask the usage tracker to leave the credentials file alone. Never
    raises: a hold that cannot be written costs one rare race, and a
    sign-in that failed to start over it would cost the sign-in."""
    try:
        os.makedirs(os.path.dirname(SIGNIN_HOLD_FILE) or ".", exist_ok=True)
        with open(SIGNIN_HOLD_FILE, "w") as fh:
            fh.write(str(int(time.time())))
    except OSError as exc:
        log.warning("could not hold usage renewals during sign-in: %s", exc)


def _release_renewals() -> None:
    try:
        os.remove(SIGNIN_HOLD_FILE)
    except OSError:
        # Never held, or already released — nothing to take back.
        pass

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|[\r\x08]")


def strip_ansi(text: str, sep: str = "") -> str:
    """Remove the terminal's own control sequences.

    `sep` is what each sequence becomes, and the two callers want different
    answers. For anything a person reads, "" is right: the CLI draws a run
    of spaces as one cursor-forward, so joining is what puts the sentence
    back together. For finding a TOKEN it is fatally wrong — see
    `find_oauth_token`.
    """
    return ANSI_RE.sub(sep, text)
URL_RE = re.compile(r"https://[^\s\"'\x1b]+")
# characters legal inside the OAuth authorize URL (used to stitch hard-wrapped lines)
URL_CHARS_RE = re.compile(r"^[A-Za-z0-9&?=%._~:/#+\-]+$")
OAUTH_TOKEN_RE = re.compile(r"sk-ant-oat\d{2}-[A-Za-z0-9_\-]{20,}")
# Post-code failure markers, observed from the real CLI: on a failed exchange
# it prints e.g. "OAuth error: Request failed with status code 400Press Enter
# to retry." and BLOCKS waiting for Enter. (\s* because the pty renderer
# sometimes draws spaces as cursor movements that ANSI-stripping removes.)
RETRY_RE = re.compile(r"Press\s*Enter\s*to\s*retry", re.IGNORECASE)
OAUTH_ERR_RE = re.compile(r"OAuth error:[^\n]*?(?=Press\s*Enter|$)", re.IGNORECASE)
# How long a code exchange may sit in "working" before we declare it dead
EXCHANGE_TIMEOUT = int(os.environ.get("BRAIN_EXCHANGE_TIMEOUT", "120"))
# When to press Enter into a silent exchange (unknown confirmation screens).
# Early nudges: a success/confirmation screen blocked on a keypress resolves
# in seconds instead of the user staring at "Exchanging code…".
NUDGE_TIMES = (10, 30, 75)

# pty terminal geometry: the authorize URL is many hundreds of characters
# long; a normal-width terminal hard-wraps it and a wrapped URL is what
# produced truncated "Missing redirect_uri parameter" links. Make the pty
# absurdly wide so the CLI never wraps it in the first place.
PTY_COLS = 4000
PTY_ROWS = 50

# ---------------------------------------------------------------------------
# Model picker
# ---------------------------------------------------------------------------
# What the ⚙ dialog offers in its model dropdown. Values are passed verbatim
# to `claude --model`, which takes both the tier aliases and full model ids.
# "" means "no --model flag at all" — whatever the CLI picks for the account.
#
# This list is a convenience, not a gate: the dialog keeps a "Custom…" escape
# hatch and the field stays a free-text add-on option, so a model released
# after this build still works by typing its id.
MODEL_CHOICES = [
    {"id": "", "group": "Automatic",
     "label": "CLI default", "hint": "whatever Claude Code picks for your plan"},
    {"id": "opus", "group": "Always the latest",
     "label": "Opus", "hint": "most capable tier"},
    {"id": "sonnet", "group": "Always the latest",
     "label": "Sonnet", "hint": "balanced speed and smarts"},
    {"id": "haiku", "group": "Always the latest",
     "label": "Haiku", "hint": "fastest, cheapest"},
    # The current generation first. The top pin used to be Opus 5 labelled
    # "deepest analysis" — a release behind what the `opus` alias already
    # resolves to, and dearer per token than it — and a pin in this list
    # is a GLOBAL override (it moves every job off the plan), so the stale
    # pin moved a whole install onto the older, pricier model.
    {"id": "claude-opus-5-5", "group": "Pinned versions",
     "label": "Claude Opus 5.5", "hint": "deepest analysis, most tokens"},
    {"id": "claude-sonnet-5-5", "group": "Pinned versions",
     "label": "Claude Sonnet 5.5", "hint": "great default for insights"},
    {"id": "claude-haiku-4-5", "group": "Pinned versions",
     "label": "Claude Haiku 4.5", "hint": "cheapest runs"},
    {"id": "claude-opus-5", "group": "Previous generation",
     "label": "Claude Opus 5", "hint": ""},
    {"id": "claude-sonnet-5", "group": "Previous generation",
     "label": "Claude Sonnet 5", "hint": ""},
    {"id": "claude-opus-4-8", "group": "Previous generation",
     "label": "Claude Opus 4.8", "hint": ""},
    {"id": "claude-sonnet-4-6", "group": "Previous generation",
     "label": "Claude Sonnet 4.6", "hint": ""},
]


def find_oauth_token(buf: str) -> str:
    """The `sk-ant-oat…` token from pty output, cut where its line ends.

    `buf` must be the output with escape sequences turned into SEPARATORS
    (`strip_ansi(text, "\n")`), never the display copy. `setup-token` prints
    the token as its own Ink element and the sentence "Store this token
    securely." as the next one, and Ink separates them by POSITIONING the
    cursor rather than by writing a newline. Stripping that escape to
    nothing glues the two together, and every character of `Store` is legal
    in the token's own alphabet — so the greedy match ran straight on into
    the prose and saved `sk-ant-oat01-…Store`.

    Nothing about the token itself can catch that: `sk-ant-oat` appears
    nowhere in the CLI bundle (the prefix and the length come from the
    server), so a length bound would be a number we invented, and it would
    be wrong the day the server changes one. The boundary is real and it is
    the escape sequence we were deleting.
    """
    match = OAUTH_TOKEN_RE.search(buf)
    return match.group(0) if match else ""


def extract_oauth_url(buf: str) -> str:
    """Find the complete OAuth authorize URL in (possibly wrapped) pty output.

    Two defenses against terminal hard-wrapping:
    - if a URL match runs to the end of its line, stitch on following lines
      that consist purely of URL characters (wrap continuations);
    - reject any candidate that lost its query string — showing a bare
      origin sends the user to "Invalid OAuth Request: Missing redirect_uri".
    """
    candidates = []
    lines = [ln.strip() for ln in buf.split("\n")]
    for i, line in enumerate(lines):
        match = URL_RE.search(line)
        if not match:
            continue
        url = match.group(0)
        if line.endswith(url):
            j = i + 1
            while j < len(lines) and lines[j] and URL_CHARS_RE.match(lines[j]):
                url += lines[j]
                j += 1
        url = url.rstrip(".,)\"'")
        if any(h in url for h in ("oauth", "claude.ai", "console.anthropic.com")):
            candidates.append(url)
    complete = [u for u in candidates if "?" in u and "=" in u]
    return max(complete, key=len) if complete else ""


# ---------------------------------------------------------------------------
# Credential storage
# ---------------------------------------------------------------------------

def _credentials_path() -> str:
    """The CLI's own credential store (written by a successful setup-token/login)."""
    return os.path.join(CLAUDE_HOME, ".claude", ".credentials.json")


def _cli_credentials_present() -> bool:
    """True when the Claude CLI holds an OAuth credential it can still use.

    When this file exists under our HOME, `claude -p` authenticates by itself —
    no env token needed. It's also the most reliable SUCCESS signal for the
    guided sign-in: some CLI versions save the credential without printing a
    token to the terminal.

    Expiry is checked because being shaped like a credential is not being
    one — but a lapsed `accessToken` is not by itself a dead credential.
    That token is short-lived by design and the file carries the
    `refreshToken` the CLI mints the next one from, entirely by itself, on
    its next run. So the question here is not "is this token live" but
    "can the CLI still get a live one from this file", and the two answers
    differ for several hours out of every day.

    Reading the first as the second is a loop with no way out: this is the
    LAST store `get_auth` consults, so a wrong "no" reports a terminal
    sign-in as `authenticated: false`, the panel shows the sign-in screen,
    and every Claude run in the server is gated on that same answer — so
    nothing brAIn does ever runs the CLI, which is the one thing that
    would have refreshed the token. It clears only when somebody opens the
    terminal and types `claude`, which a phone cannot do.

    A past expiry with no refresh token stays dead: that is the revoked
    session this check was written for, and there is nothing left in the
    file to renew. A missing expiry means the file records none, not that
    the token is past it. Liveness proper is `validate_auth`'s — a real
    run, where a refresh token the account has revoked comes back a 401.
    """
    try:
        with open(_credentials_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        oauth = data.get("claudeAiOauth") or {}
        token = oauth.get("accessToken", "")
        if not (isinstance(token, str) and token.startswith("sk-ant-")):
            return False
        expires = oauth.get("expiresAt")
        if isinstance(expires, (int, float)) and expires > 0:
            if expires / 1000.0 > time.time() + 60:
                return True
            refresh = oauth.get("refreshToken")
            # A non-empty string, which is deliberately the same predicate
            # `run.sh`'s jq applies to the same field on the same file:
            # two answers to "can the CLI renew this" is one too many, and
            # the one that runs at boot decides what this one then reads.
            return isinstance(refresh, str) and refresh != ""
        return True
    except (OSError, ValueError, AttributeError):
        return False


def _credential_fingerprint() -> tuple | None:
    """Identity of the CLI's credential file — (mtime_ns, size) — or None.

    Deliberately not its contents. This value is only ever compared against
    another taken from the same file, to answer "has the CLI rewritten this
    since we started"; reading a credential into memory to answer a question
    about a timestamp buys a copy of the secret for nothing.
    """
    try:
        st = os.stat(_credentials_path())
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _read_shared_auth() -> dict | None:
    """The credential the terminal shares via `ha login`.

    Shape contract: {"type": "oauth_token"|"api_key", "value": "<str>",
    "saved_at": <epoch int>}. Missing, unreadable, or malformed files are
    silently ignored — the shared file is entirely optional.
    """
    try:
        with open(SHARED_AUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("value")
    if data.get("type") not in ("oauth_token", "api_key"):
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return {"type": data["type"], "value": value.strip()}


def get_auth() -> dict | None:
    """Return {'type': 'oauth_token'|'api_key'|'cli_login', 'value': str,
    'source': 'local'|'shared'|'cli'} or None.

    Resolution order: locally stored credential → credential shared by the
    terminal login → the CLI's own saved login.
    """
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("value"):
            data["source"] = "local"
            return data
    except (OSError, ValueError):
        # No local credential, or an unreadable one, means trying the next
        # store below rather than reporting a failure here.
        pass
    shared = _read_shared_auth()
    if shared:
        shared["source"] = "shared"
        return shared
    if _cli_credentials_present():
        return {"type": "cli_login", "value": "", "source": "cli"}
    return None


def classify_credential(value: str) -> str | None:
    """Best-effort classification of a pasted credential."""
    value = value.strip()
    if value.startswith("sk-ant-oat"):
        return "oauth_token"
    if value.startswith("sk-ant-"):
        return "api_key"
    return None


def save_auth(value: str, cred_type: str | None = None) -> dict:
    cred_type = cred_type or classify_credential(value)
    if not cred_type:
        raise ValueError("Credential not recognized — expected sk-ant-oat… token or sk-ant-… API key")
    os.makedirs(SECRETS_DIR, exist_ok=True)
    # Epoch seconds, which is the shape contract both credential files share
    # (see _read_shared_auth) and what `ha-share-login` writes and greps for
    # as `"saved_at":[ ]*[0-9]+`. This wrote an ISO string, so the two stores
    # documented as one shape held two — latent only because each reader
    # happens to read the file it wrote, which is not a property to rely on.
    data = {"type": cred_type, "value": value.strip(), "saved_at": int(time.time())}
    fd = os.open(AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def clear_auth(include_shared: bool = False) -> None:
    """Forget the locally stored credential and the CLI's own login.

    `include_shared` is a caller's decision and never a default, but it is
    NOT optional in the sense the old docstring meant. That comment ("never
    touches SHARED_AUTH_FILE — that file belongs to the brAIn add-on") was
    written when the panel and the terminal were two add-ons; merged, this
    module writes that file itself (`share_auth`), and leaving it behind is
    not caution — `get_auth` reads it two branches below, so a sign-out that
    spares it hands the very next call the credential it just removed. From
    the panel that reads as a Sign out button that does nothing at all.

    So the *choice* is surfaced (the dialog says a shared copy exists and
    ticks the box) rather than made here, because the file may equally have
    been published from the terminal by somebody else — and it is the one
    credential of the three that other add-ons read.
    """
    paths = [AUTH_FILE, _credentials_path(), AUTH_BACKUP_FILE]
    if include_shared:
        paths.append(SHARED_AUTH_FILE)
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            # Signing out removes what is there; a store that is already empty
            # needs nothing done to it.
            pass


# ---------------------------------------------------------------------------
# Sharing a login with the other BRUH add-ons
# ---------------------------------------------------------------------------
# The shared file is the only one of the three credential stores on /config,
# which is why it is the one anything outside this container can read — and
# for the whole life of the panel the only way to write it was `ha login` in
# a terminal. So somebody who signed in through the panel had the sharing
# half of the feature available to them only through a command they had to
# know about, and `ha login --status` answered them "not set up".

def share_auth() -> dict:
    """Publish the panel's credential to the file other add-ons read.

    Returns {"shared": bool, "reason": str} — a refusal is a sentence rather
    than an exception, because every reason it can refuse is a state the
    dialog has to render anyway.

    Two things may NOT be published, and the second is the one worth
    spelling out:

    * an API key is publishable and an OAuth token is publishable; anything
      else is not the shape `_read_shared_auth` documents.
    * Claude Code's OWN `.credentials.json` is never publishable, however
      live it is. Its `accessToken` is a *session* token the CLI refreshes
      for itself; the shared file records no refresh token and no reader
      knows how to use one, so a copy of it works for a few hours and then
      breaks every add-on reading it, silently, with nothing to say why.
      `get_auth` reports that store as `cli_login` with an empty `value`,
      which is exactly the case this refuses.
    """
    auth = get_auth()
    if not auth:
        return {"shared": False, "reason": "not_signed_in"}
    if auth.get("source") == "shared":
        # Already the shared file — republishing it to itself is a no-op
        # dressed up as an action.
        return {"shared": True, "reason": "already_shared"}
    value = (auth.get("value") or "").strip()
    if auth["type"] == "cli_login" or not value:
        return {"shared": False, "reason": "cli_login_cannot_be_shared"}

    directory = os.path.dirname(SHARED_AUTH_FILE)
    try:
        os.makedirs(directory, exist_ok=True)
        os.chmod(directory, 0o700)
    except OSError as exc:
        log.warning("could not prepare the shared secrets directory: %s", exc)
        return {"shared": False, "reason": "unwritable"}

    data = {"type": auth["type"], "value": value, "saved_at": int(time.time())}
    try:
        # Same write shape as save_auth: 0600 from the open, never a chmod
        # after the bytes are already on disk under whatever the umask said.
        fd = os.open(SHARED_AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as exc:
        log.warning("could not write the shared credential: %s", exc)
        return {"shared": False, "reason": "unwritable"}

    # The consolidator, the study watcher and the listeners all read this
    # file as the `claude` user, and the panel is root. Root can write a
    # claude-owned file; the reverse is what fails, and it fails silently.
    _chown_claude(SHARED_AUTH_FILE)
    _chown_claude(directory)
    return {"shared": True, "reason": "ok"}


def unshare_auth() -> bool:
    """Withdraw the shared copy. True when a file was actually removed.

    Withdrawing the file is all this does — the token itself stays valid at
    Anthropic, which is why the dialog says so rather than letting somebody
    believe a press here revoked a credential.
    """
    try:
        os.remove(SHARED_AUTH_FILE)
        return True
    except OSError:
        return False


def _chown_claude(path: str) -> None:
    """Hand a file to the `claude` user when we are root, quietly otherwise."""
    try:
        import pwd
        uid = pwd.getpwnam("claude").pw_uid
        gid = pwd.getpwnam("claude").pw_gid
    except (ImportError, KeyError):
        # A dev checkout has no `claude` user, and the panel is the only
        # reader there.
        return
    try:
        os.chown(path, uid, gid)
    except OSError:
        # Not root, or a filesystem that will not take it: the file is
        # already written, and this is the recoverable half.
        pass


def auth_overview() -> dict:
    """Every credential store, and which one is actually in use.

    One payload rather than three questions, for the same reason
    `ha login --status` reports all three: "signed in" and "signed in AND
    shared" are different states, and a surface that can only see its own
    store answers the second one with the first one's words. Nothing here
    returns a credential — only its type, where it came from, and when it
    was saved.
    """
    auth = get_auth()
    shared = _read_shared_auth()
    cli_usable = _cli_credentials_present()

    def _saved_at(path: str) -> int | None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                stamp = json.load(f).get("saved_at")
        except (OSError, ValueError, AttributeError):
            return None
        return int(stamp) if isinstance(stamp, (int, float)) else None

    return {
        "authenticated": bool(auth),
        "type": auth["type"] if auth else None,
        # Which of the three stores answered — the field that makes a
        # "sign out did nothing" report diagnosable rather than a mystery.
        "source": auth.get("source") if auth else None,
        "saved_at": _saved_at(AUTH_FILE) if auth and auth.get("source") == "local"
        else (_saved_at(SHARED_AUTH_FILE) if auth and auth.get("source") == "shared" else None),
        "stores": {
            "local": {"present": os.path.exists(AUTH_FILE),
                      "saved_at": _saved_at(AUTH_FILE)},
            # `present` is deliberately usability and not existence for
            # this one store: it is the only file of the three that records
            # an expiry, so it is the only one where "there is a credential
            # here" and "there is a credential here the CLI can use" are
            # separable questions — and reporting a revoked session as a
            # login is what sent people to fix a sign-in already redone.
            # Usable, not live: an expired access token beside a refresh
            # token is one `claude` run away from a new one.
            "cli": {"present": cli_usable},
            "shared": {"present": bool(shared),
                       "type": shared["type"] if shared else None,
                       "saved_at": _saved_at(SHARED_AUTH_FILE)},
        },
        # Can this login be published to the other add-ons? A `cli_login` has
        # no shareable value at all (see share_auth), so the button is absent
        # rather than present-and-failing.
        "can_share": bool(auth) and auth["type"] != "cli_login" and bool(auth.get("value")),
        "shared_path": SHARED_AUTH_FILE,
    }


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------

# Where the CLI actually lives, in resolution order. run.sh installs the
# native binary under the claude user's home and the image symlinks it into
# /root/.local/bin — neither is on the default PATH, so `shutil.which` alone
# resolves to nothing and the bare name "claude" gets handed to su-exec,
# which then fails with "su-exec: claude: No such file or directory".
CLAUDE_BIN_CANDIDATES = (
    os.path.join(CLAUDE_HOME, ".local", "bin", "claude"),
    "/root/.local/bin/claude",
    "/usr/local/bin/claude",
)


def resolve_claude_bin() -> str:
    """Absolute path to the Claude CLI, or the bare name as a last resort.

    Always prefer an absolute path: this process runs as root but execs as
    the `claude` user, so a PATH-relative name is resolved against a PATH
    that may not contain the binary at all.
    """
    override = os.environ.get("BRAIN_CLAUDE_BIN")
    if override:
        return override
    for candidate in CLAUDE_BIN_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("claude") or "claude"


# run.sh installs this wrapper: it sources /data/.brain_env and drops to the
# claude user itself, so it must NOT be wrapped in su-exec again.
CLAUDE_RUN_WRAPPER = "/usr/local/bin/claude-run"


def _claude_argv() -> list[str]:
    """Base argv, dropping to the non-root `claude` user when we're root."""
    if not os.environ.get("BRAIN_CLAUDE_BIN") \
            and os.path.isfile(CLAUDE_RUN_WRAPPER) \
            and os.access(CLAUDE_RUN_WRAPPER, os.X_OK):
        return [CLAUDE_RUN_WRAPPER]
    claude_bin = resolve_claude_bin()
    if os.geteuid() == 0 and shutil.which("su-exec"):
        return ["su-exec", "claude", claude_bin]
    return [claude_bin]


def _claude_env() -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = CLAUDE_HOME
    # Claude Code keeps a memory of its own beside brAIn's, and it was on in
    # every session: "remember that" in the chat was written to the CLI's
    # MEMORY.md under the config dir as well as queued to brAIn's inbox, and
    # the CLI's copy was never consolidated, never shown on the Memory tab,
    # never reached by a correction or a forget — and went on loading into
    # every later session, where it could contradict memory.md. memory.md is
    # the only thing that is memory; the second one is switched off here and
    # in /data/.brain_env, which is every route a Claude process has.
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    # Never let a stale interactive login interfere; inject our credential.
    auth = get_auth()
    if auth:
        if auth["type"] == "api_key":
            env["ANTHROPIC_API_KEY"] = auth["value"]
            env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        elif auth["type"] == "cli_login":
            # the CLI authenticates from its own ~/.claude/.credentials.json
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        else:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = auth["value"]
            env.pop("ANTHROPIC_API_KEY", None)
    return env


def run_claude(
    prompt: str,
    system_prompt: str,
    model: str = "",
    timeout: int = 480,
    max_turns: int = 4,
    source: str = "",
    *,
    job: str = "",
    effort: str = "",
    schema: dict | None = None,
    pressed: bool = False,
) -> dict:
    """Run `claude -p` headlessly. Returns {'ok', 'text', 'error', 'meta'}.

    No tools: insights are pure generation over the data bundle in the
    prompt. Without that, the model sometimes attempted tool calls that
    non-interactive mode denies, burning turns and dying with "max number
    of turns" instead of producing the insight.

    **`--tools ""`, never `--disallowedTools "*"`, and the difference is the
    whole first look.** `--tools ""` takes the built-in set off the table;
    a `*` deny refuses every call the model makes — including the CLI's own
    StructuredOutput tool, which is how a `--json-schema` run hands its
    answer back. So every Resident first look and every snapshot card that
    carried a schema asked for that tool, was refused, asked again, and
    spent four to six turns at several times the price before giving up in
    prose — with no `structured_output`, and in roughly two runs of five no
    JSON in the prose either. A look that cannot be read sends its whole
    batch to `watch`, which is how a tripped leak sensor never reached
    `act`. The deny survives only as the fallback for a CLI too old to know
    `--tools`, where it is exactly what shipped.

    `job`, `effort` and `schema` are the 2.0 additions shared by all three
    runners — see `_run_cli`.
    """
    return _run_cli(
        prompt, ["--tools", "", "--strict-mcp-config",
                 "--system-prompt", system_prompt] + isolation_flags(),
        model, timeout, max_turns, f"Claude timed out after {timeout}s",
        source, job=job, effort=effort, schema=schema, pressed=pressed,
        fallbacks={"tools": ["--disallowedTools", "*"]})


# The analyst's tools: reading the home, and nothing else.
#
# This is an ALLOW-list of specific tool names rather than "everything that
# isn't obviously a write", because two of the MCP server's `get_`-shaped
# tools are not reads — `fire_event` fires a Home Assistant event, which can
# trigger an automation, and `remember_fact` writes to memory. A rule that
# sorted by prefix would have let both through.
#
# Left out on purpose, though they are genuine reads:
#   get_camera_snapshot — returns images, which are the most expensive thing
#     a run can ask for and answer no question about entity data
#   get_error_log       — a log tail, not a fact about the home
#   dashboards, services, supervisor info — not analysis inputs
MCP = "mcp__home-assistant__"

# The Home Assistant project: where `.mcp.json` names the MCP server and
# `.claude/settings.local.json` pre-approves its tools. Every other Claude
# path — the chat, the listeners, the worker pool — runs FROM this
# directory and inherits both for free. The engine deliberately does not
# (its transcripts are filed under CLAUDE_HOME so card and fix runs stay
# out of the Chats rail), and for as long as that was the whole story the
# analyst ran without a single Home Assistant tool and the fixer answered
# "I have no working Home Assistant connection ... this session is
# confined to /data/home" — accurately. The project is handed over by
# flag instead: `--mcp-config` for the server, `--add-dir` for the files,
# and `--settings` only where the project's own permission file is the
# intended answer to "what may run unprompted". The analyst never takes
# the settings file: its allow-list is asserted from both ends on
# purpose, and a file pre-approving Bash and Write would widen it.
HA_PROJECT = os.environ.get("BRAIN_CHAT_WORKDIR", "/config")

# The headless allow-list: what an unattended run that cannot ask anybody
# may do without a prompt. run.sh writes it beside the shared project file
# and it is handed over by `--settings`, never loaded by being in /config —
# see `setup_claude_settings` in run.sh for why it left
# /config/.claude/settings.local.json, which is the file the interactive
# terminal and the chat load too.
def headless_settings_file() -> str:
    """Where that file is: `BRAIN_HEADLESS_SETTINGS`, else beside the
    project in `.brain/`. A function rather than a constant so it follows
    `HA_PROJECT` wherever a test or a dev checkout points it."""
    return (os.environ.get("BRAIN_HEADLESS_SETTINGS")
            or os.path.join(HA_PROJECT, ".brain", "headless_settings.json"))

# Built-in tools that act OUTSIDE the run without a permission prompt:
# messaging a peer session, listing the sessions there are to message,
# firing a remote trigger, pushing a notification to somebody's phone,
# scheduling a job, watching a process, waking a session later. Claude Code
# ships them enabled and brAIn installs `latest`, so every brAIn process —
# a read-only analyst, a study run, a voice worker whose shell is denied —
# could message the chat or the always-alive spare voice worker, whose
# pre-approved tools would then act on the house on its behalf. That walks
# round "an unattended run can change nothing" and "voice cannot reach a
# shell" at once, with nothing but a prompt in the way.
#
# One list, read three ways: the engine denies it on every run (in
# ANALYST_DENIED and in `isolation_flags`), and run.sh writes the same
# names into the shared project file, the headless allow-list file and the
# voice scope — `tests/test_security.py` holds the shell copies to this
# one, because two answers to "what may a session reach outside itself" is
# how one face keeps a door the others closed.
PLATFORM_DENIED = [
    "SendMessage", "ListAgents", "ListPeers", "RemoteTrigger",
    "PushNotification", "SendUserMessage", "CronCreate", "CronDelete",
    "CronList", "ScheduleWakeup", "Monitor", "TeamCreate", "TeamDelete",
]


def isolation_settings() -> dict:
    """What every engine run is told about the platform around it.

    `crossSessionInbound: refuse` opts the session out of receiving a
    peer's messages; `autoMemoryEnabled: false` is the setting half of
    `CLAUDE_CODE_DISABLE_AUTO_MEMORY`; and the platform tools are denied
    by name. No `allow` at all — this is the floor every run stands on,
    and what a run may do is its runner's flags and nothing here.
    """
    return {
        "crossSessionInbound": "refuse",
        "autoMemoryEnabled": False,
        "permissions": {"deny": list(PLATFORM_DENIED)},
    }


def isolation_flags(settings_file: str = "") -> list[str]:
    """`--setting-sources` and `--settings` for one engine run.

    **No setting source is loaded, and that is deliberate rather than
    tidy.** The engine runs from CLAUDE_HOME, and there the user settings
    file and the "project" one are the same file — the one a terminal
    `/advisor opus` writes to — so `project,local` would have kept exactly
    the leak it was meant to close: an Opus advisor attached to every
    scheduled card, look and investigation, which nothing in the Resident's
    ledger counts. So every setting an engine run has is named here, by
    flag: the isolation JSON for a run that reads, and the headless
    allow-list file for the one that acts (which carries the same keys).
    """
    return ["--setting-sources", "",
            "--settings", settings_file or json.dumps(
                isolation_settings(), separators=(",", ":"))]


def project_flags(*, files: bool) -> list[str]:
    """Flags that lend a CLAUDE_HOME run the Home Assistant project.

    Each is added only when its target exists: `--mcp-config` on a missing
    file is a refused run, and a dev checkout has no /config at all. The
    project's permission file is no longer one of them — see
    `headless_settings_file` and `run_agent`.
    """
    flags: list[str] = []
    mcp = os.path.join(HA_PROJECT, ".mcp.json")
    if os.path.isfile(mcp):
        flags += ["--mcp-config", mcp]
    if files and os.path.isdir(HA_PROJECT):
        flags += ["--add-dir", HA_PROJECT]
    return flags
ANALYST_TOOLS = [
    f"{MCP}get_all_states",       # the search: by domain, by name substring
    f"{MCP}get_entity_state",     # one entity, in full
    f"{MCP}get_history",
    f"{MCP}get_statistics",
    f"{MCP}get_logbook",
    f"{MCP}get_baseline",         # what is NORMAL here, so "unusual" is a number
    f"{MCP}explain_change",       # what CAUSED a change, not just that it happened
    f"{MCP}get_activity",
    f"{MCP}get_house_model",   # what has been MEASURED here, and what has not
    # The measurements as tools (2.2): what is normal for an entity right
    # now, a room's physics, a machine's state by its own thresholds, the
    # house's rhythm, a door's usual hours, a person's habit with an
    # entity, an automation replayed against history, and what brAIn
    # remembers about a subject. Reads, every one — a replay calls nothing.
    f"{MCP}what_is_normal",
    f"{MCP}room_physics",
    f"{MCP}appliance_status",
    f"{MCP}house_rhythm",
    f"{MCP}door_habits",
    f"{MCP}habits",
    f"{MCP}simulate_automation",
    f"{MCP}recall",
    f"{MCP}get_findings",      # what is on the Findings tab, so a run can
                               # answer "what needs attention" without guessing
    f"{MCP}get_health",        # whether brAIn itself is working, in its own words
    f"{MCP}get_areas",
    f"{MCP}get_registry",
    f"{MCP}get_automations",
    f"{MCP}get_automation_trace",
    f"{MCP}get_automation_config",  # the definition a trace ran — runs have no files
    f"{MCP}search_related",         # what a script or scene touches, what uses an entity
    f"{MCP}get_ha_config",
    f"{MCP}get_weather_forecast",
    # The rest of the MCP server's reads. Every tool the server registers is
    # in exactly one of these two lists (tests/test_security.py drives
    # TOOL_IMPLEMENTATIONS against both), because a tool in neither is
    # neither allowed nor forbidden — it FAILS when the analyst reaches for
    # it, which is not the same guarantee and reads like a broken tool.
    f"{MCP}get_services",
    f"{MCP}get_service_details",
    f"{MCP}get_entity_counts",
    f"{MCP}list_dashboards",
    f"{MCP}get_dashboard",
    f"{MCP}get_error_log",
    f"{MCP}get_supervisor_info",
    # ESPHome, the reading half: the device list, one file, a validation
    # (ESPHome checks the YAML and changes nothing) and a device's log.
    f"{MCP}esphome_list_devices",
    f"{MCP}esphome_get_config",
    f"{MCP}esphome_validate",
    f"{MCP}esphome_logs",
    f"{MCP}esphome_job",
    # Music Assistant, the reading half: the overview, a search, and any
    # command the panel's own table says only reads.
    f"{MCP}music_assistant_status",
    f"{MCP}music_assistant_query",
    f"{MCP}music_assistant_search",
    # The BRUH add-ons, the reading half: who is on the Minecraft server,
    # what the label printer holds, what BRight is doing.
    f"{MCP}minecraft_status",
    f"{MCP}label_printer_status",
    f"{MCP}bright_status",
]
# Named explicitly rather than left to the allow-list, because `--allowedTools`
# governs what runs WITHOUT a prompt, and a headless run cannot be prompted:
# an un-listed tool would fail rather than be forbidden, and those are not the
# same guarantee. Insight generation must not be able to change the house even
# if the permission model shifts under it.
ANALYST_DENIED = [
    "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch",
    f"{MCP}call_service", f"{MCP}fire_event", f"{MCP}remember_fact",
    f"{MCP}send_notification", f"{MCP}activate_scene", f"{MCP}run_script",
    f"{MCP}reload_config", f"{MCP}render_template", f"{MCP}get_camera_snapshot",
    f"{MCP}control_light", f"{MCP}control_climate", f"{MCP}control_media_player",
    f"{MCP}control_cover", f"{MCP}control_fan", f"{MCP}control_switch",
    f"{MCP}control_lock", f"{MCP}control_alarm", f"{MCP}control_vacuum",
    # Denied because it changes nothing and MEANS nothing here: it offers a
    # person the ways a finding could end, and an unattended run has nobody
    # to offer them to. A tool in neither list fails when it is reached,
    # which from a card reads as a broken tool rather than as the policy it
    # is — so this says which, the way every other name here does.
    f"{MCP}offer_resolutions",
    # ESPHome, the acting half: every one writes a file, spends minutes of
    # somebody's CPU on a build, or replaces the firmware a device runs.
    f"{MCP}esphome_write_config", f"{MCP}esphome_create_device",
    f"{MCP}esphome_delete_device", f"{MCP}esphome_compile",
    f"{MCP}esphome_install", f"{MCP}esphome_update_firmware",
    f"{MCP}esphome_clean", f"{MCP}esphome_set_secret",
    # Music Assistant, the acting half: every one plays, changes or forgets
    # something on a server a family listens to.
    f"{MCP}music_assistant_command", f"{MCP}music_assistant_player",
    f"{MCP}music_assistant_play", f"{MCP}music_assistant_remove_players",
    # The BRUH add-ons, the acting half: every one moves a player, changes
    # a world, installs server code, prints on paper or turns the lights
    # into a show — none of it an unattended card's business.
    f"{MCP}minecraft_teleport", f"{MCP}minecraft_player",
    f"{MCP}minecraft_world", f"{MCP}minecraft_command",
    f"{MCP}minecraft_server", f"{MCP}minecraft_addons",
    f"{MCP}print_label", f"{MCP}bright_show",
    # The platform's own reach past the run — a peer session, a phone, a
    # timer. `--tools ""` already takes the built-ins off an analyst run;
    # they are named here as well because this list is what a study
    # session and a `house`/`read_only` automation task are scoped by, and
    # those keep the built-in set.
    *PLATFORM_DENIED,
]


def run_analyst(
    prompt: str,
    system_prompt: str,
    model: str = "",
    timeout: int = 480,
    max_turns: int = 40,
    source: str = "",
    *,
    job: str = "",
    effort: str = "",
    schema: dict | None = None,
    pressed: bool = False,
) -> dict:
    """Run `claude -p` with READ-ONLY Home Assistant tools. Same envelope.

    The searching half of insight generation. ``run_claude`` posts the whole
    home and asks a question about it; this posts what the home *contains*
    and lets Claude go and get the rows it decides it needs — which for a
    targeted question is thirty entities rather than five hundred, and can
    include the history a single-shot question could never afford.

    It sits between the other two on purpose. ``run_claude`` can change
    nothing because it holds no tools; ``run_agent`` can change the house
    because somebody pressed Fix. This runs unattended, on a schedule or on
    a typed question, so it gets tools that only read — enforced from both
    ends (see ANALYST_TOOLS and ANALYST_DENIED) rather than trusting one
    flag's semantics with the house on the other side of it.

    ``--append-system-prompt``, not ``--system-prompt``: replacing the CLI's
    own prompt strips what it knows about calling tools, which is the entire
    point of this path.

    ``--tools ""`` takes Claude Code's own agentic harness off the run —
    Agent, TodoWrite, Read, Glob, Grep and the rest, about 22k tokens of
    tool definitions a read-only house analyst never calls — while the MCP
    server's tools stay, because they are not built-ins. ``--strict-mcp-config``
    is what keeps it to that one server: a user-scope server or a plugin
    the terminal installed would otherwise load into every unattended run,
    with its tools in context and its own reach.
    """
    return _run_cli(
        prompt,
        ["--append-system-prompt", system_prompt,
         "--tools", "",
         "--allowedTools", ",".join(ANALYST_TOOLS),
         "--disallowedTools", ",".join(ANALYST_DENIED)]
        + project_flags(files=False) + ["--strict-mcp-config"]
        + isolation_flags(),
        model, timeout, max_turns,
        f"the analysis passed its {timeout}s limit and was stopped", source,
        job=job, effort=effort, schema=schema, pressed=pressed)


def run_agent(
    prompt: str,
    system_prompt: str,
    model: str = "",
    timeout: int = 900,
    max_turns: int = 60,
    source: str = "",
    *,
    job: str = "",
    effort: str = "",
    schema: dict | None = None,
    pressed: bool = False,
) -> dict:
    """Run `claude -p` WITH its tools. Same envelope as ``run_claude``.

    The one place the panel lets Claude touch the house (the Findings "Fix
    it" button). Two differences from ``run_claude``, both deliberate:

    * no ``--disallowedTools``, so the Home Assistant MCP tools and file
      access are available. Which of them may run without a prompt is
      governed by the headless allow-list file run.sh writes
      (`headless_settings_file`) — the same permissions the Assist and
      Automation listeners run under, so there is one answer to "what may
      an unattended Claude do here" rather than two. It used to be the
      shared project file, which the interactive terminal and the chat
      load too, and that is the reason it moved: a person at a prompt
      should be asked.
    * ``--append-system-prompt`` rather than ``--system-prompt``: replacing
      the CLI's own system prompt strips everything it knows about using its
      tools, which is precisely what this run needs.

    The headless file also carries the PreToolUse hooks — the edit
    snapshot `unfix` reverses out of, and the protected-entity guard —
    which is why it is handed over whole rather than as a bare allow-list.
    """
    headless = headless_settings_file()
    headless = headless if os.path.isfile(headless) else ""
    return _run_cli(
        prompt, ["--append-system-prompt", system_prompt]
        + project_flags(files=True) + ["--strict-mcp-config"]
        + isolation_flags(headless),
        model, timeout, max_turns,
        f"the fix run passed its {timeout}s limit and was stopped", source,
        job=job, effort=effort, schema=schema, pressed=pressed)


# There is NO turn cap on a panel run. `_run_cli` sends no `--max-turns`
# at all: the wall clock is the guard, and it is the only one that answers
# "how much may this cost" in a unit people have an intuition about. The
# caps used to be "large and invisible" and one of them was neither — the
# Resident's first look ran under a cap of four, and a structured reply
# the CLI validates against a schema is itself a tool turn, so a look that
# needed one more try ended `error_max_turns`, spent its tokens, filed
# nothing and wrote a fault into the next report. That fault is the one
# this was reported from, in the words it arrived in: *"I really don't
# want to get 'max number of turns errors'. Get rid of that constraint."*
# The `max_turns` argument every runner still takes is accepted and
# ignored, so no caller changes shape; a run that loops on a failing tool
# is ended by its timeout, which it always was past the cap anyway.
#
# The landing below stays, for a CLI that carries a cap of its own: a
# guard that trips has to change what happens next, or every token the
# run spent is thrown away with the answer. So a run that ends on
# `error_max_turns` is asked to LAND: one more invocation, `--resume` on
# the same session, two turns, and a prompt that says finish now with what
# you have. The resumed conversation still holds everything the run read,
# so what comes back is the answer in the task's own format with one
# sentence about what it did not get to — a partial that files, instead
# of a thorough one that never did. The landing is charged to the same
# wall-clock budget as the run.
LANDING_TURNS = 2
LANDING_MIN_S = 20
LANDING_PROMPT = (
    "You have run out of room for further investigation. Do not call any "
    "more tools. Finish NOW with what you already have, in exactly the "
    "format the task asked for, and end with one sentence saying what you "
    "did not get to."
)


def hit_turn_cap(result: dict) -> bool:
    """Did this run end on the CLI's own turn cap (not ours, not a timeout)?"""
    return (not result.get("ok")
            and journal.classify(result) == "max_turns")


# An overloaded API is not a failed run, and a card that died on a 529
# with 15 minutes of its budget unspent is a card nobody asked for twice.
# The CLI retries inside a call; when it gives up, `_run_cli` waits this
# long and tries the whole run once more — once, because a second refusal
# in a row is the service saying wait longer than any run can. Bounded by
# the run's own clock: no retry is started without room for it.
OVERLOAD_RETRY_S = int(os.environ.get("BRAIN_OVERLOAD_RETRY_S", "45"))
_OVERLOADED_RE = re.compile(r"\b529\b|overloaded", re.IGNORECASE)


def overloaded(result: dict) -> bool:
    """Did this run fail because the API said it was overloaded?"""
    return (not result.get("ok")
            and bool(_OVERLOADED_RE.search(str(result.get("error") or ""))))


# The flags the runners add that an older CLI may not know. Each is
# optional in the same sense `--session-id` is: the CLI names an unknown
# flag on stderr and dies unspoken, and the run is retried without it.
# What is NOT optional is the run — a job planned for `--effort low` on
# a CLI that predates effort still runs, at the CLI's default depth.
#
# The value is how many argv entries follow the flag: `--strict-mcp-config`
# takes none, and removing "its value" would take the next flag with it.
_OPTIONAL_FLAGS = {
    "effort": 1, "json-schema": 1, "session-id": 1, "tools": 1,
    "strict-mcp-config": 0, "setting-sources": 1, "settings": 1,
}
# The arg parser's own sentence, and the only thing read: the name is
# taken out of "unknown option '--tools'" rather than searched for as a
# word, because a word search found "tools" in every error that mentioned
# an allow-list and "effort" in any reply that used the word.
_UNKNOWN_OPTION_RE = re.compile(r"unknown option ['\"]?--([A-Za-z][\w-]*)",
                                re.IGNORECASE)
# Claude Code refuses to start a second conversation under an id whose
# transcript already exists — before any request, so the refusal costs
# nothing and answers nothing. `_run_cli` mints a fresh id per spawn so it
# should never be seen; when it is, the run gets one fresh id and goes
# again rather than ending on a sentence about bookkeeping.
_SESSION_IN_USE_RE = re.compile(r"session id\b.*\balready in use", re.IGNORECASE)


def _rejected_flag(result: dict) -> str | None:
    """Which optional flag a failed run's stderr names, if any."""
    if result.get("ok"):
        return None
    match = _UNKNOWN_OPTION_RE.search(str(result.get("error") or ""))
    if match and match.group(1) in _OPTIONAL_FLAGS:
        return match.group(1)
    return None


def session_in_use(result: dict) -> bool:
    """Did the CLI refuse the run because its session id was taken?"""
    return (not result.get("ok")
            and bool(_SESSION_IN_USE_RE.search(str(result.get("error") or ""))))


def _without(argv: list[str], flag: str) -> list[str]:
    """`argv` with `--<flag>` and its value(s) removed."""
    arity = _OPTIONAL_FLAGS.get(flag, 1)
    out: list[str] = []
    skip = 0
    for item in argv:
        if skip:
            skip -= 1
            continue
        if item == f"--{flag}":
            skip = arity
            continue
        out.append(item)
    return out


def _mint(source: str) -> str:
    """A fresh session id, claimed for `source` before anything runs.

    Claimed first because a run that times out or crashes still leaves a
    transcript behind and it should still be labelled as the run it was.
    """
    session_id = str(uuid.uuid4())
    if source:
        run_sources.record(session_id, source)
    return session_id


def _run_cli(prompt: str, flags: list[str], model: str, timeout: int,
             max_turns: int, timeout_message: str, source: str = "",
             *, job: str = "", effort: str = "",
             schema: dict | None = None, pressed: bool = False,
             fallbacks: dict | None = None) -> dict:
    """Invoke `claude -p` and parse its envelope.

    Three 2.0 additions ride on every runner and are resolved here, once:

    * `job` names what the run is for ("card", "triage", "fix_apply").
      When the caller passed no `model`, the model and the effort come
      from `model_plan.resolve(job, …)` — the tiering the design page
      calls "Haiku looks, Sonnet thinks, Opus acts". An explicit `model`
      still wins, because a caller that named one meant it — up to the
      one tier a timer may never reach (`model_plan.guard_override`).
    * `effort` becomes `--effort`, a depth request the CLI may not know.
    * `schema` becomes `--json-schema`: the CLI validates the reply against
      it and returns the object as `structured_output`, which lands in
      the result as `data`. A CLI that rejects the flag runs without it
      and `data` is then whatever `extract_json` can read out of the
      text, so callers keep one code path and one fallback.

    `pressed` says a person asked for this run. It is what lets a typed
    model reach a job a timer may not run on it, and nothing else.

    `fallbacks` names what replaces an optional flag the installed CLI
    refuses, where dropping it alone would widen the run: `run_claude`
    trades a refused `--tools ""` for the `--disallowedTools "*"` that
    shipped before it, rather than for no restriction at all.

    The su-exec drop to the non-root user, the credential injection, and the
    working directory are the fiddly parts, and they must not have two
    copies: a fix applied to one and not the other is how the tool-enabled
    path quietly stops authenticating the way the analysis path does.

    **Every spawn mints its own ``--session-id``**, claimed for ``source``
    before it starts (the label is optional, the run is not: a CLI that
    rejects the flag gets the run without it). Reusing one id across
    re-spawns was the bug: an attempt that reached the API — a 529, a flag
    the API rather than the arg parser refused — has already written a
    transcript under that id, and the CLI refuses a second conversation
    under it with "Session ID … is already in use" before any request. So
    the documented overload retry could never retry: it waited its pause,
    spent a spawn, replaced the real 529 with a sentence about bookkeeping,
    and the journal still said the run was retried.

    A run that ends on the turn cap is landed (see LANDING_PROMPT) on the
    id the CLI reports for it, and the landed answer is the run's result;
    the journal line says so (``extra.landed``). A landing that also fails
    leaves the ordinary error, which names no setting — there is none.
    """
    refused_override = ""
    if job and model:
        # A model the caller named is, in every server.py call site, the
        # global override handed down — so the override's one guard is
        # asked here too, not only where the plan reads it.
        thinking = _thinking()
        model, refused_override = model_plan.guard_override(
            job, model, thinking, pressed=pressed)
        if refused_override:
            log.warning("%s: %s", job, refused_override)
            model, planned_effort = model_plan.resolve(
                job, thinking, "", pressed=pressed)
            effort = effort or planned_effort
    elif job:
        model, planned_effort = planned(job, pressed=pressed)
        effort = effort or planned_effort
    base = _claude_argv() + ["-p", "--output-format", "json"]
    if model:
        base += ["--model", model]
    if effort:
        base += ["--effort", effort]
    if schema:
        base += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
    # No `--max-turns`: see the note above LANDING_TURNS. The argument is
    # kept so every runner and every caller keeps its shape.
    del max_turns
    fallbacks = dict(fallbacks or {})
    started = time.monotonic()
    dropped: list[str] = []

    def spawn(limit: int) -> tuple[dict, str]:
        sid = "" if "session-id" in dropped else _mint(source)
        tail = ["--session-id", sid] if sid else []
        return _spawn_cli(base + flags + tail, prompt, limit,
                          timeout_message), sid

    result, session_id = spawn(timeout)
    # An optional flag the installed CLI does not know: drop it (or trade
    # it for its fallback) and go again, at most once per flag, so a run
    # never fails over a request.
    while (flag := _rejected_flag(result)) and flag not in dropped:
        dropped.append(flag)
        base = _without(base, flag)
        flags = _without(flags, flag) + fallbacks.pop(flag, [])
        result, session_id = spawn(timeout)
    if session_in_use(result) and "session-id" not in dropped:
        # Should be unreachable with an id minted per spawn; when it is
        # reached anyway (a clock collision, a store restored from a
        # backup), one fresh id is the whole remedy.
        result, session_id = spawn(timeout)
    retried = False
    if overloaded(result):
        remaining = int(timeout - (time.monotonic() - started))
        if remaining > OVERLOAD_RETRY_S + LANDING_MIN_S:
            time.sleep(OVERLOAD_RETRY_S)
            result, session_id = spawn(remaining - OVERLOAD_RETRY_S)
            retried = True
    if schema and result.get("ok") and "data" not in result:
        # The CLI ran without --json-schema (too old, or it was dropped
        # above): read the object out of the text so callers see one shape.
        result["data"] = extract_json(result.get("text") or "")
    landed = False
    if hit_turn_cap(result):
        # The CLI's own id first: after the older-CLI retry above the
        # minted one names no conversation at all.
        resume_id = str((result.get("meta") or {}).get("session_id")
                        or session_id)
        remaining = int(timeout - (time.monotonic() - started))
        if resume_id and remaining >= LANDING_MIN_S:
            landing = _spawn_cli(
                base + ["--max-turns", str(LANDING_TURNS)] + flags
                + ["--resume", resume_id],
                LANDING_PROMPT, remaining, timeout_message)
            if landing["ok"]:
                result, landed = landing, True
    # The model actually sent, on the result: the Resident's ledger charges
    # a run to the tier it RAN on (`model_plan.tier_of`), and a card's
    # capture names it. Empty when the CLI chose — the account's default.
    result.setdefault("meta", {})
    result["meta"]["model"] = model or ""
    extra: dict = {}
    if landed:
        extra["landed"] = True
    if retried:
        extra["retried"] = "overloaded"
    if job:
        extra["job"] = job
    if effort:
        extra["effort"] = effort
    if dropped:
        extra["dropped_flags"] = dropped
    if refused_override:
        extra["refused_override"] = True
    _journal(source or "engine", result, model, timeout_message,
             time.monotonic() - started, extra=extra or None,
             run_id=session_id)
    return result


def _thinking() -> str:
    """The `thinking` dial as saved, or the default. Never raises."""
    try:
        value = str(settings_store.load().get("thinking") or "")
    except Exception:  # noqa: BLE001 - a settings file that will not read is the defaults
        value = ""
    return value if value in model_plan.THINKING else model_plan.DEFAULT_THINKING


def planned(job: str, *, pressed: bool = False) -> tuple[str, str]:
    """`(model, effort)` the model plan gives a job on this install.

    The global `model` option (the add-on's Configuration tab, or the
    panel's override of it) wins when set — a person who typed a model
    meant every run — and the `thinking` setting scales the tiers. Read
    at call time rather than at import, the way `insights_enabled()` is,
    so a change in ⚙ reaches the next run. The one exception is the
    override's own guard: a typed Fable on a job nobody pressed for falls
    back to the job's own tier (`model_plan.guard_override`).
    """
    try:
        settings = settings_store.load()
    except Exception:  # noqa: BLE001 - a settings file that will not read is the defaults
        settings = {}
    override = str(settings.get("model") or os.environ.get("BRAIN_MODEL", "") or "")
    thinking = str(settings.get("thinking") or model_plan.DEFAULT_THINKING)
    if override:
        override, refused = model_plan.guard_override(
            job, override, thinking, pressed=pressed)
        if refused:
            log.warning("%s: %s", job, refused)
    return model_plan.resolve(job, thinking, override, pressed=pressed)


def _journal(source: str, result: dict, model: str, timeout_message: str,
             duration_s: float, extra: dict | None = None,
             run_id: str = "") -> None:
    """One journal line per invocation, whatever happened to it.

    Best effort by construction (journal.record never raises), and kept
    out of the spawn path so a journal problem cannot be mistaken for a
    CLI problem.
    """
    meta = result.get("meta") or {}
    journal.record(
        source, journal.classify(result, timeout_message),
        error=result.get("error") or "",
        duration_s=duration_s,
        model=model or "",
        tokens=usage_store.tokens_from_meta(meta),
        turns=meta.get("num_turns") if isinstance(meta.get("num_turns"), int) else None,
        # The CLI's own id first; the one this spawn was minted under when
        # the envelope carried none (plain output, an older shape).
        run_id=str(meta.get("session_id") or run_id or "")[:64],
        extra=extra,
    )


def _engine_env() -> dict[str, str]:
    """`_claude_env` plus what only an unattended engine run is told.

    No advisor. A `/advisor opus` typed in the terminal is saved to the
    shared user settings and the CLI attaches that advisor to every run
    that loads them; `isolation_flags` loads none, and this is the second
    lock on the same door, because nothing in `model_plan` plans an
    advisor and nothing in the Resident's ledger would count one.
    """
    env = _claude_env()
    env["CLAUDE_CODE_DISABLE_ADVISOR_TOOL"] = "1"
    return env


def _spawn_cli(argv: list[str], prompt: str, timeout: int,
               timeout_message: str) -> dict:
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_engine_env(),
            cwd=CLAUDE_HOME if os.path.isdir(CLAUDE_HOME) else None,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": timeout_message, "text": "", "meta": {}}
    except FileNotFoundError:
        return {"ok": False, "error": "claude CLI not found", "text": "", "meta": {}}
    return _envelope(proc)


def _envelope(proc: subprocess.CompletedProcess) -> dict:
    """Parse the `claude -p --output-format json` envelope into our result."""
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        return {
            "ok": False,
            "error": f"claude exited {proc.returncode}: {stderr[-500:] or 'no output'}",
            "text": "", "meta": {},
        }
    try:
        envelope = json.loads(stdout)
    except ValueError:
        # -p json output should be a single object; salvage raw text otherwise
        return {"ok": True, "text": stdout, "error": "", "meta": {}}
    if isinstance(envelope, list):  # stream-ish output: take the result event
        envelope = next(
            (e for e in reversed(envelope) if isinstance(e, dict) and e.get("type") == "result"),
            {},
        )
    text = envelope.get("result") or ""
    meta = {
        k: envelope.get(k)
        for k in ("total_cost_usd", "duration_ms", "num_turns", "session_id", "subtype")
        if envelope.get(k) is not None
    }
    if isinstance(envelope.get("usage"), dict):
        meta["usage"] = envelope["usage"]
    # `--json-schema` answers with the validated object beside the text.
    # It is carried as `data` so a structured run and a text run have one
    # result shape; absent when the CLI did not produce one.
    structured = envelope.get("structured_output")
    if envelope.get("is_error") or not (text or structured is not None):
        if envelope.get("subtype") == "error_max_turns":
            # Reached only when the landing in _run_cli failed too. No
            # setting is named because there is none to change: the cap
            # is a runaway guard, and what ended this run is the wall
            # clock or the model, not a number somebody can raise.
            err = "Claude ran out of room before finishing — try Regenerate"
        else:
            err = text or envelope.get("subtype") or stderr[-500:] or "empty result"
        return {"ok": False, "error": str(err)[:1000], "text": "", "meta": meta}
    out = {"ok": True, "text": text, "error": "", "meta": meta}
    if structured is not None:
        out["data"] = structured if isinstance(structured, dict) else None
    return out


def validate_auth(timeout: int = 120) -> dict:
    """Cheap end-to-end check that the stored credential actually works."""
    result = run_claude(
        "Reply with exactly: OK",
        "You are a connectivity check. Reply with exactly what the user asks and nothing else.",
        timeout=timeout, job="auth_check",
    )
    ok = result["ok"] and "OK" in result["text"].upper()
    return {"ok": ok, "error": "" if ok else (result["error"] or "unexpected reply")}


# ---------------------------------------------------------------------------
# Insight JSON extraction
# ---------------------------------------------------------------------------

def extract_json(text: str) -> dict | None:
    """Pull the insight JSON object out of a model reply."""
    text = text.strip()
    # strip a markdown fence if present
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```\s*$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        # Not JSON, so there is no object to return. The caller reads None as
        # "the model did not answer in the shape we asked for".
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Guided `claude setup-token` flow (subscription OAuth, no API key)
# ---------------------------------------------------------------------------

# The two sign-ins, and the difference between them is a SCOPE.
#
# `claude setup-token` asks Anthropic for `user:inference` and nothing else.
# `claude auth login` asks for `org:create_api_key user:profile user:inference
# user:sessions:claude_code user:mcp_servers user:file_upload`. Measured off
# the authorize URL each one prints, which is the only place either states it.
#
# `user:profile` is what `/api/oauth/usage` requires, so a house signed in
# with the first can never report its usage — not because anything is broken
# but because nobody ever asked for the permission. brAIn knew that and said
# so, and then named the remedy as `claude /login` **in the Terminal tab**:
# a shell command, in a tab `enable_terminal` can remove and whose default
# face is a chat with no shell in it. So the panel's own sign-in screen minted
# the usage-blind credential, and the only cure it could name was somewhere a
# person may have no way to reach. That is the whole of the complaint.
#
# `auth login` is a plain subcommand rather than the TUI's `/login`, so it
# drives on a pty exactly like `setup-token` does: it prints an authorize URL
# and waits for a pasted code. One flow serves both — the argv is the only
# real difference, because success for `auth login` arrives as the credential
# file being rewritten, which `_signed_in_here` already is.
#
# Neither replaces the other. A session credential refreshes itself and so
# cannot be copied to the shared file other BRUH add-ons read; a long-lived
# token can, and is the whole point of `ha login --share`. So the account
# sign-in is what the panel offers first and the token is what you add when
# something else needs it.
FLOW_MODES = {
    "account": {
        "argv": ["auth", "login"],
        "label": "auth login",
        "what": "your Claude account",
    },
    "token": {
        "argv": ["setup-token"],
        "label": "setup-token",
        "what": "a long-lived token",
    },
}
DEFAULT_FLOW_MODE = "account"


class SetupTokenFlow:
    """Drives `claude auth login` (or `claude setup-token`) on a pty.

    Phases: idle → starting → awaiting_code → working → done | error.
    The panel polls status(); when phase == awaiting_code it shows `url`
    and posts the pasted code to submit_code().

    The mode picks the argv and nothing else. `setup-token` prints a token
    this scrapes and saves; `auth login` prints none and writes the CLI's
    own credential file, which `_signed_in_here` reads as the success it is.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reset_locked()

    def _reset_locked(self) -> None:
        self.phase = "idle"
        self.mode = DEFAULT_FLOW_MODE
        self.url = ""
        self.error = ""
        self.output = ""
        self._fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._deadline = 0.0
        self._url_from = 0        # scan offset: URLs before this are stale
        self._code_from = 0       # scan offset: only look for errors after the code
        self._code_sent_at = 0.0
        self._nudges = 0
        # The credential file as it looked before this flow ran. Written once
        # in start(), before the reader thread exists, and never mutated
        # after — so the reader may read it without the lock, and the
        # `finally` block (which already holds it) cannot deadlock on it.
        self._cred_before = None

    # -- public API --------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            detail = ""
            for line in reversed(self.output.split("\n")):
                line = line.strip()
                if line:
                    detail = OAUTH_TOKEN_RE.sub("sk-ant-oat…", line)[:200]
                    break
            return {"phase": self.phase, "url": self.url, "error": self.error,
                    "detail": detail, "mode": self.mode}

    def start(self, mode: str = DEFAULT_FLOW_MODE) -> dict:
        if mode not in FLOW_MODES:
            mode = DEFAULT_FLOW_MODE
        with self._lock:
            active = self.phase in ("starting", "awaiting_code", "working")
            proc_dead = self._proc is None or self._proc.poll() is not None
            stuck = (
                self.phase == "working"
                and self._code_sent_at
                and time.time() - self._code_sent_at > EXCHANGE_TIMEOUT + 30
            )
        if active and not proc_dead and not stuck:
            # a live flow exists (e.g. the page was reloaded) — reattach to it
            return self.status()
        if active:
            # the previous flow died or wedged — tear it down and start fresh
            self.cancel()
        with self._lock:
            self._reset_locked()
            self.mode = mode
            self.phase = "starting"
            self._deadline = time.time() + 600
            self._cred_before = _credential_fingerprint()
        # From here until the flow settles, the credentials file changing
        # means the exchange succeeded — so nothing else may change it.
        _hold_renewals()
        try:
            leader, follower = pty.openpty()
            # ultra-wide terminal so the OAuth URL is never hard-wrapped
            try:
                winsz = struct.pack("HHHH", PTY_ROWS, PTY_COLS, 0, 0)
                fcntl.ioctl(follower, termios.TIOCSWINSZ, winsz)
            except OSError:
                # A pty that will not take a window size still works — the only cost
                # is that a long OAuth URL may wrap.
                pass
            argv = _claude_argv() + list(FLOW_MODES[mode]["argv"])
            env = dict(os.environ)
            env["HOME"] = CLAUDE_HOME
            env["TERM"] = "xterm-256color"
            env["COLUMNS"] = str(PTY_COLS)
            env["LINES"] = str(PTY_ROWS)
            self._proc = subprocess.Popen(
                argv, stdin=follower, stdout=follower, stderr=follower,
                env=env, close_fds=True,
                cwd=CLAUDE_HOME if os.path.isdir(CLAUDE_HOME) else None,
            )
            os.close(follower)
            self._fd = leader
            self._thread = threading.Thread(target=self._reader, daemon=True)
            self._thread.start()
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self.phase = "error"
                self.error = f"Could not start claude {self._label()}: {exc}"
            # No reader thread will run, so nothing else releases it.
            _release_renewals()
        return self.status()

    def submit_code(self, code: str) -> dict:
        code = code.strip()
        with self._lock:
            if self.phase != "awaiting_code" or self._fd is None:
                return {"phase": self.phase, "url": self.url,
                        "error": self.error or "Flow is not waiting for a code",
                        "detail": ""}
            self.phase = "working"
            self.error = ""
            self._code_from = len(self.output)
            self._code_sent_at = time.time()
            self._nudges = 0
        try:
            os.write(self._fd, (code + "\r").encode())
        except OSError as exc:
            with self._lock:
                self.phase = "error"
                self.error = f"Could not send code: {exc}"
        return self.status()

    def cancel(self) -> None:
        with self._lock:
            proc = self._proc
            self._proc = None
            if self.phase not in ("done",):
                self.phase = "idle"
            self.url = ""
            self.error = ""
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                # Already exited.
                pass
        _release_renewals()

    # -- internals ---------------------------------------------------------

    def _label(self) -> str:
        """The command this flow is driving, for the log and for a failure."""
        return FLOW_MODES.get(self.mode, FLOW_MODES[DEFAULT_FLOW_MODE])["label"]

    def _signed_in_here(self) -> bool:
        """True when the CLI wrote a usable credential *during this flow*.

        `_cli_credentials_present` answers "can the CLI still use the file
        on disk", which is the right question for `get_auth` and the wrong
        one here. A credential that was already there answers it too — so a
        stale file (an access token lapsed weeks ago beside a refresh token
        the account has since revoked) made this flow report success the
        instant a code was submitted, having exchanged nothing. The panel
        said "Connected!", `get_auth` went on returning that same dead file,
        and every real Claude run 401'd: a sign-in that cannot be completed
        because it claims to have completed already, and one no amount of
        retrying clears, because each retry re-reads the file that caused it.

        A successful exchange REWRITES that file, so the honest question is
        whether it has changed since we started. The presence test stays in
        front of it: a file deleted or corrupted mid-flow has changed too,
        and a change is only success when what is there now is usable.
        """
        return _cli_credentials_present() and (
            _credential_fingerprint() != self._cred_before)

    def _reader(self) -> None:
        fd = self._fd
        proc = self._proc
        buf = ""
        # The same bytes with every escape sequence kept as a boundary. Only
        # the token is read from here; everything else reads `buf`, whose
        # joined-up text is what the URL, the retry prompt and the status
        # detail are all written against.
        tokens = ""
        logged = 0       # how much of the redacted accumulation is in the log
        try:
            while proc and proc.poll() is None and time.time() < self._deadline:
                ready, _, _ = select.select([fd], [], [], 1.0)
                if ready:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    raw = chunk.decode("utf-8", "replace")
                    text = strip_ansi(raw)
                    buf += text
                    tokens += strip_ansi(raw, "\n")
                    # Redact the ACCUMULATION and log what is new in it,
                    # never this chunk on its own: a token split across two
                    # reads matches neither half, and both halves would go
                    # to the log in the clear. A completed token makes the
                    # redacted text shorter than what we have already
                    # logged, and that read is skipped rather than risked.
                    redacted = OAUTH_TOKEN_RE.sub("sk-ant-oat…", tokens)
                    fresh = redacted[logged:] if logged <= len(redacted) else ""
                    logged = len(redacted)
                    if fresh.strip():
                        log.info("%s: %s", self._label(), fresh.strip()[:400])
                    with self._lock:
                        self.output = buf
                    self._scan(buf, tokens)
                    with self._lock:
                        if self.phase == "done":
                            break

                # ---- per-tick checks (MUST run even when there is NO new
                # output: a silent hang produces exactly zero output) --------
                with self._lock:
                    working = self.phase == "working"
                    sent_at = self._code_sent_at
                if not working or not sent_at:
                    continue
                elapsed = time.time() - sent_at
                # some CLI versions save the credential without printing the
                # token — the credentials file appearing IS success
                if self._signed_in_here():
                    log.info("%s: credentials file written — success", self._label())
                    with self._lock:
                        self.phase = "done"
                    break
                # gentle Enter nudges in case an unknown confirmation screen
                # ("press enter to continue") is blocking the CLI
                for i, at in enumerate(NUDGE_TIMES):
                    if elapsed > at and self._nudges <= i:
                        self._nudges = i + 1
                        log.info("%s: no output for %.0fs — nudging with Enter", self._label(), elapsed)
                        try:
                            os.write(fd, b"\r")
                        except OSError:
                            # The pty is gone, which the loop discovers on its next read.
                            pass
                # watchdog: a code exchange that neither succeeds nor prints a
                # retry prompt within the window is declared dead so the UI
                # never hangs on "Exchanging code…" again
                if elapsed > EXCHANGE_TIMEOUT:
                    with self._lock:
                        tail = buf[self._code_from:].strip()[-200:]
                        self.phase = "error"
                        self.error = (
                            "Timed out exchanging the code — no response from the sign-in "
                            "process. This usually means the add-on cannot reach "
                            "claude.com/anthropic.com (check the network), or the CLI is stuck. "
                            "The 'Paste a token' tab is a reliable alternative."
                            + (f" CLI output: …{tail}" if tail else "")
                        )
                    log.warning("%s: exchange timed out after %.0fs", self._label(), elapsed)
                    break
        finally:
            # process ended (or timed out) — one final scan, then settle state
            self._scan(buf, tokens)
            with self._lock:
                if self.phase not in ("done", "idle"):
                    if self.phase == "error":
                        pass
                    elif find_oauth_token(tokens) or self._signed_in_here():
                        self.phase = "done"
                    else:
                        self.phase = "error"
                        tail = buf.strip()[-300:] or f"claude {self._label()} exited unexpectedly"
                        self.error = self.error or f"Setup did not complete: …{tail}"
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    # Already exited.
                    pass
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    # Already closed.
                    pass
            # Settled, whichever way: the tracker may renew again.
            _release_renewals()

    def _scan(self, buf: str, tokens: str | None = None) -> None:
        """`buf` is the display text; `tokens` the boundary-preserving copy.

        They are two readings of one stream and the token may only ever come
        from the second — `find_oauth_token` says why. `tokens` defaults to
        `buf` for a caller that has neither escapes nor anything glued.
        """
        token = find_oauth_token(buf if tokens is None else tokens)
        if token:
            try:
                save_auth(token, "oauth_token")
                with self._lock:
                    self.phase = "done"
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self.phase = "error"
                    self.error = f"Token capture failed: {exc}"
            return

        with self._lock:
            phase = self.phase
            url_from = self._url_from
            code_from = self._code_from

        if phase == "working":
            # success may arrive as a saved credentials file instead of a
            # token printed to the terminal
            if self._signed_in_here():
                with self._lock:
                    self.phase = "done"
                return
            # Failed exchange: the CLI prints "OAuth error: …Press Enter to
            # retry." and blocks. Press Enter for the user — the CLI then mints
            # a FRESH authorize URL (new state/code_challenge; the old page's
            # code is dead) — and loop back to the awaiting-code stage.
            after_code = buf[code_from:]
            if RETRY_RE.search(after_code):
                err = OAUTH_ERR_RE.search(after_code)
                msg = (err.group(0).strip() if err else "The sign-in attempt failed.")
                with self._lock:
                    self.error = (
                        f"{msg} — a fresh sign-in link was generated. "
                        "Open the new link below and paste the new code."
                    )
                    self.url = ""
                    self._url_from = len(buf)
                    self._code_sent_at = 0.0
                    self.phase = "starting"
                try:
                    if self._fd is not None:
                        os.write(self._fd, b"\r")
                except OSError:
                    # The pty is gone; the phase set above is what the UI reads.
                    pass
            return

        if phase == "starting" or not self.url:
            url = extract_oauth_url(buf[url_from:])
            if url:
                with self._lock:
                    self.url = url
                    if self.phase == "starting":
                        self.phase = "awaiting_code"


# module-level singleton used by the server
SETUP_FLOW = SetupTokenFlow()
