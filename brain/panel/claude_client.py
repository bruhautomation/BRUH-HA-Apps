"""Claude CLI plumbing for BRain.

Auth
----
Works with a Claude subscription (Pro/Max) — no API key required:
  * Guided flow: we drive `claude setup-token` over a pty, surface the OAuth
    URL in the panel, the user pastes the one-time code back, and we capture
    the resulting long-lived token (sk-ant-oat01-…).
  * Paste flow: the user runs `claude setup-token` anywhere (e.g. the BRUH
    Claude Terminal add-on) and pastes the token into the panel.
  * Shared login: the BRain add-on's `ha-share-login` writes a
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

log = logging.getLogger("brain.auth")

SECRETS_DIR = os.environ.get("BRAIN_SECRETS", "/data/secrets")
CLAUDE_HOME = os.environ.get("BRAIN_HOME", "/data/home")
AUTH_FILE = os.path.join(SECRETS_DIR, "claude_auth.json")
# Credential shared by the BRain add-on (its `ha-share-login` tool
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
    """True when the Claude CLI holds a usable OAuth credential in its own store.

    When this file exists under our HOME, `claude -p` authenticates by itself —
    no env token needed. It's also the most reliable SUCCESS signal for the
    guided sign-in: some CLI versions save the credential without printing a
    token to the terminal.
    """
    try:
        with open(_credentials_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        token = (data.get("claudeAiOauth") or {}).get("accessToken", "")
        return isinstance(token, str) and token.startswith("sk-ant-")
    except (OSError, ValueError, AttributeError):
        return False


def _read_shared_auth() -> dict | None:
    """The credential the BRain add-on shares via `ha-share-login`.

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
    BRain add-on → the CLI's own saved login.
    """
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("value"):
            data["source"] = "local"
            return data
    except (OSError, ValueError):
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
    data = {"type": cred_type, "value": value.strip(), "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    fd = os.open(AUTH_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def clear_auth() -> None:
    """Forget the locally stored credential and the CLI's own login.

    NEVER touches SHARED_AUTH_FILE — that file belongs to the BRain
    add-on. (The /config mount is writable for the memory file, but this
    module never writes anything under it.)
    """
    for path in (AUTH_FILE, _credentials_path()):
        try:
            os.remove(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------

def _claude_argv() -> list[str]:
    """Base argv, dropping to the non-root `claude` user when we're root."""
    claude_bin = os.environ.get("BRAIN_CLAUDE_BIN") or shutil.which("claude") or "claude"
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
) -> dict:
    """Run `claude -p` headlessly. Returns {'ok', 'text', 'error', 'meta'}.

    Tools are disallowed outright: insights are pure generation over the data
    bundle in the prompt. Without this, the model sometimes attempted tool
    calls that non-interactive mode denies, burning through --max-turns and
    dying with "max number of turns" instead of producing the insight. The
    max_turns margin covers any residual multi-turn behavior.
    """
    argv = _claude_argv() + [
        "-p",
        "--output-format", "json",
        "--max-turns", str(max_turns),
        "--disallowedTools", "*",
        "--system-prompt", system_prompt,
    ]
    if model:
        argv += ["--model", model]
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
        return {"ok": False, "error": f"Claude timed out after {timeout}s", "text": "", "meta": {}}
    except FileNotFoundError:
        return {"ok": False, "error": "claude CLI not found", "text": "", "meta": {}}

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
                    pass
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
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
