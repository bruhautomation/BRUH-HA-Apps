"""Claude CLI plumbing for BRUH Insights.

Auth
----
Works with a Claude subscription (Pro/Max) — no API key required:
  * Guided flow: we drive `claude setup-token` over a pty, surface the OAuth
    URL in the panel, the user pastes the one-time code back, and we capture
    the resulting long-lived token (sk-ant-oat01-…).
  * Paste flow: the user runs `claude setup-token` anywhere (e.g. the BRUH
    Claude Terminal add-on) and pastes the token into the panel.
  * API key: a plain Anthropic API key also works, for users who prefer it.
The credential is stored at $BRUH_INSIGHTS_SECRETS/claude_auth.json (0600)
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

SECRETS_DIR = os.environ.get("BRUH_INSIGHTS_SECRETS", "/data/secrets")
CLAUDE_HOME = os.environ.get("BRUH_INSIGHTS_HOME", "/data/home")
AUTH_FILE = os.path.join(SECRETS_DIR, "claude_auth.json")

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|[\r\x08]")
URL_RE = re.compile(r"https://[^\s\"'\x1b]+")
# characters legal inside the OAuth authorize URL (used to stitch hard-wrapped lines)
URL_CHARS_RE = re.compile(r"^[A-Za-z0-9&?=%._~:/#+\-]+$")
OAUTH_TOKEN_RE = re.compile(r"sk-ant-oat01-[A-Za-z0-9_\-]{20,}")

# pty terminal geometry: the authorize URL is many hundreds of characters
# long; a normal-width terminal hard-wraps it and a wrapped URL is what
# produced truncated "Missing redirect_uri parameter" links. Make the pty
# absurdly wide so the CLI never wraps it in the first place.
PTY_COLS = 4000
PTY_ROWS = 50


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

def get_auth() -> dict | None:
    """Return {'type': 'oauth_token'|'api_key', 'value': str} or None."""
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("value"):
            return data
    except (OSError, ValueError):
        pass
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
    try:
        os.remove(AUTH_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI invocation
# ---------------------------------------------------------------------------

def _claude_argv() -> list[str]:
    """Base argv, dropping to the non-root `claude` user when we're root."""
    claude_bin = os.environ.get("BRUH_CLAUDE_BIN") or shutil.which("claude") or "claude"
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
        else:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = auth["value"]
            env.pop("ANTHROPIC_API_KEY", None)
    return env


def run_claude(
    prompt: str,
    system_prompt: str,
    model: str = "",
    timeout: int = 480,
    max_turns: int = 1,
) -> dict:
    """Run `claude -p` headlessly. Returns {'ok', 'text', 'error', 'meta'}."""
    argv = _claude_argv() + [
        "-p",
        "--output-format", "json",
        "--max-turns", str(max_turns),
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
    if envelope.get("is_error") or not text:
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

    # -- public API --------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            return {"phase": self.phase, "url": self.url, "error": self.error}

    def start(self) -> dict:
        with self._lock:
            if self.phase in ("starting", "awaiting_code", "working"):
                return {"phase": self.phase, "url": self.url, "error": self.error}
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
                        "error": self.error or "Flow is not waiting for a code"}
            self.phase = "working"
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
                if not ready:
                    continue
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += ANSI_RE.sub("", chunk.decode("utf-8", "replace"))
                buf = buf[-20000:]
                self._scan(buf)
                with self._lock:
                    self.output = buf
                    if self.phase == "done":
                        break
        finally:
            # process ended (or timed out) — one final scan, then settle state
            self._scan(buf)
            with self._lock:
                if self.phase not in ("done", "idle"):
                    if self.phase == "error":
                        pass
                    elif OAUTH_TOKEN_RE.search(buf):
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
        if self.phase in ("starting",) or not self.url:
            url = extract_oauth_url(buf)
            if url:
                with self._lock:
                    self.url = url
                    if self.phase == "starting":
                        self.phase = "awaiting_code"


# module-level singleton used by the server
SETUP_FLOW = SetupTokenFlow()
