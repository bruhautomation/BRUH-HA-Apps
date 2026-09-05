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
import run_sources
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

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|[\r\x08]")
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
    {"id": "claude-opus-5", "group": "Pinned versions",
     "label": "Claude Opus 5", "hint": "deepest analysis, most tokens"},
    {"id": "claude-sonnet-5", "group": "Pinned versions",
     "label": "Claude Sonnet 5", "hint": "great default for insights"},
    {"id": "claude-haiku-4-5", "group": "Pinned versions",
     "label": "Claude Haiku 4.5", "hint": "cheapest runs"},
    {"id": "claude-opus-4-8", "group": "Previous generation",
     "label": "Claude Opus 4.8", "hint": ""},
    {"id": "claude-sonnet-4-6", "group": "Previous generation",
     "label": "Claude Sonnet 4.6", "hint": ""},
]


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
    """True when the Claude CLI holds a *live* OAuth credential of its own.

    When this file exists under our HOME, `claude -p` authenticates by itself —
    no env token needed. It's also the most reliable SUCCESS signal for the
    guided sign-in: some CLI versions save the credential without printing a
    token to the terminal.

    Expiry is checked because being shaped like a credential is not being
    one. A revoked session or a container that was down past the expiry
    leaves a well-formed dead token behind, and reporting that as "signed
    in" makes the panel's auth chip say the opposite of what the terminal
    is telling the same person. A missing expiry means the file records
    none, not that the token is past it.
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
            return expires / 1000.0 > time.time() + 60
        return True
    except (OSError, ValueError, AttributeError):
        return False


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
    paths = [AUTH_FILE, _credentials_path()]
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
    cli_live = _cli_credentials_present()

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
            # `present` is deliberately liveness and not existence for this
            # one store: it is the only file of the three that records an
            # expiry, so it is the only one where "there is a credential
            # here" and "there is a working credential here" are separable
            # questions — and reporting a dead token as a login is what sent
            # people to fix a sign-in that had already been redone.
            "cli": {"present": cli_live},
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
) -> dict:
    """Run `claude -p` headlessly. Returns {'ok', 'text', 'error', 'meta'}.

    Tools are disallowed outright: insights are pure generation over the data
    bundle in the prompt. Without this, the model sometimes attempted tool
    calls that non-interactive mode denies, burning through --max-turns and
    dying with "max number of turns" instead of producing the insight. The
    max_turns margin covers any residual multi-turn behavior.
    """
    return _run_cli(
        prompt, ["--disallowedTools", "*", "--system-prompt", system_prompt],
        model, timeout, max_turns, f"Claude timed out after {timeout}s",
        source)


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


def project_flags(*, settings: bool, files: bool) -> list[str]:
    """Flags that lend a CLAUDE_HOME run the Home Assistant project.

    Each is added only when its target exists: `--mcp-config` on a missing
    file is a refused run, and a dev checkout has no /config at all.
    """
    flags: list[str] = []
    mcp = os.path.join(HA_PROJECT, ".mcp.json")
    if os.path.isfile(mcp):
        flags += ["--mcp-config", mcp]
    if files and os.path.isdir(HA_PROJECT):
        flags += ["--add-dir", HA_PROJECT]
    local = os.path.join(HA_PROJECT, ".claude", "settings.local.json")
    if settings and os.path.isfile(local):
        flags += ["--settings", local]
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
    f"{MCP}get_areas",
    f"{MCP}get_registry",
    f"{MCP}get_automations",
    f"{MCP}get_automation_trace",
    f"{MCP}get_ha_config",
    f"{MCP}get_weather_forecast",
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
]


def run_analyst(
    prompt: str,
    system_prompt: str,
    model: str = "",
    timeout: int = 480,
    max_turns: int = 12,
    source: str = "",
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
    """
    return _run_cli(
        prompt,
        ["--append-system-prompt", system_prompt,
         "--allowedTools", ",".join(ANALYST_TOOLS),
         "--disallowedTools", ",".join(ANALYST_DENIED)]
        + project_flags(settings=False, files=False),
        model, timeout, max_turns,
        f"the analysis passed its {timeout}s limit and was stopped", source)


def run_agent(
    prompt: str,
    system_prompt: str,
    model: str = "",
    timeout: int = 900,
    max_turns: int = 30,
    source: str = "",
) -> dict:
    """Run `claude -p` WITH its tools. Same envelope as ``run_claude``.

    The one place the panel lets Claude touch the house (the Findings "Fix
    it" button). Two differences from ``run_claude``, both deliberate:

    * no ``--disallowedTools``, so the Home Assistant MCP tools and file
      access are available. Which of them may run without a prompt is
      governed by /config/.claude/settings.local.json, written at startup —
      the same permissions the Assist and Automation listeners run under, so
      there is one answer to "what may Claude do here" rather than two.
    * ``--append-system-prompt`` rather than ``--system-prompt``: replacing
      the CLI's own system prompt strips everything it knows about using its
      tools, which is precisely what this run needs.
    """
    return _run_cli(
        prompt, ["--append-system-prompt", system_prompt]
        + project_flags(settings=True, files=True),
        model, timeout, max_turns,
        f"the fix run passed its {timeout}s limit and was stopped", source)


def _run_cli(prompt: str, flags: list[str], model: str, timeout: int,
             max_turns: int, timeout_message: str, source: str = "") -> dict:
    """Invoke `claude -p` and parse its envelope.

    The su-exec drop to the non-root user, the credential injection, and the
    working directory are the fiddly parts, and they must not have two
    copies: a fix applied to one and not the other is how the tool-enabled
    path quietly stops authenticating the way the analysis path does.

    ``source`` claims the run's transcript for a face ("card", "fix") the
    way every other background caller does — a minted ``--session-id``,
    recorded in run_sources *before* the run, because a run that times out
    or crashes still left a transcript behind and it should still be
    labelled as the run it was. The same fallback the consolidator has: a
    CLI that rejects the flag names it on stderr and dies unspoken, and
    then the run is retried without it — the label is optional, the run is
    not. An unclaimed engine-directory transcript is simply not listed.
    """
    argv = _claude_argv() + [
        "-p",
        "--output-format", "json",
        "--max-turns", str(max_turns),
    ] + flags
    if model:
        argv += ["--model", model]
    started = time.monotonic()
    result = None
    if source:
        session_id = str(uuid.uuid4())
        if run_sources.record(session_id, source):
            result = _spawn_cli(argv + ["--session-id", session_id],
                                prompt, timeout, timeout_message)
            if not (result["ok"] or "session-id" not in (result.get("error") or "")):
                result = None
    if result is None:
        result = _spawn_cli(argv, prompt, timeout, timeout_message)
    _journal(source or "engine", result, model, timeout_message,
             time.monotonic() - started)
    return result


def _journal(source: str, result: dict, model: str, timeout_message: str,
             duration_s: float) -> None:
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
        run_id=str(meta.get("session_id") or "")[:64],
    )


def _spawn_cli(argv: list[str], prompt: str, timeout: int,
               timeout_message: str) -> dict:
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_claude_env(),
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
    if envelope.get("is_error") or not text:
        if envelope.get("subtype") == "error_max_turns":
            err = ("Claude hit the turn limit before finishing the insight — "
                   "hit Regenerate to try again")
        else:
            err = text or envelope.get("subtype") or stderr[-500:] or "empty result"
        return {"ok": False, "error": str(err)[:1000], "text": "", "meta": meta}
    return {"ok": True, "text": text, "error": "", "meta": meta}


def validate_auth(timeout: int = 120) -> dict:
    """Cheap end-to-end check that the stored credential actually works."""
    result = run_claude(
        "Reply with exactly: OK",
        "You are a connectivity check. Reply with exactly what the user asks and nothing else.",
        timeout=timeout,
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

class SetupTokenFlow:
    """Drives `claude setup-token` on a pty.

    Phases: idle → starting → awaiting_code → working → done | error.
    The panel polls status(); when phase == awaiting_code it shows `url`
    and posts the pasted code to submit_code().
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reset_locked()

    def _reset_locked(self) -> None:
        self.phase = "idle"
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
                    "detail": detail}

    def start(self) -> dict:
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
            self.phase = "starting"
            self._deadline = time.time() + 600
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
            argv = _claude_argv() + ["setup-token"]
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
                self.error = f"Could not start claude setup-token: {exc}"
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

    # -- internals ---------------------------------------------------------

    def _reader(self) -> None:
        fd = self._fd
        proc = self._proc
        buf = ""
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
                    text = ANSI_RE.sub("", chunk.decode("utf-8", "replace"))
                    buf += text
                    stripped = OAUTH_TOKEN_RE.sub("sk-ant-oat…", text).strip()
                    if stripped:
                        log.info("setup-token: %s", stripped[:400])
                    with self._lock:
                        self.output = buf
                    self._scan(buf)
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
                if _cli_credentials_present():
                    log.info("setup-token: credentials file detected — success")
                    with self._lock:
                        self.phase = "done"
                    break
                # gentle Enter nudges in case an unknown confirmation screen
                # ("press enter to continue") is blocking the CLI
                for i, at in enumerate(NUDGE_TIMES):
                    if elapsed > at and self._nudges <= i:
                        self._nudges = i + 1
                        log.info("setup-token: no output for %.0fs — nudging with Enter", elapsed)
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
                    log.warning("setup-token: exchange timed out after %.0fs", elapsed)
                    break
        finally:
            # process ended (or timed out) — one final scan, then settle state
            self._scan(buf)
            with self._lock:
                if self.phase not in ("done", "idle"):
                    if self.phase == "error":
                        pass
                    elif OAUTH_TOKEN_RE.search(buf) or _cli_credentials_present():
                        self.phase = "done"
                    else:
                        self.phase = "error"
                        tail = buf.strip()[-300:] or "setup-token exited unexpectedly"
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

    def _scan(self, buf: str) -> None:
        token = OAUTH_TOKEN_RE.search(buf)
        if token:
            try:
                save_auth(token.group(0), "oauth_token")
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
            if _cli_credentials_present():
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
