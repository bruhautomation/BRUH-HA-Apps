#!/usr/bin/env python3
"""Persistent Claude worker pool for the Assist integration (fast mode).

Replaces the spawn-per-request model of assist-listener.sh: instead of
booting the Claude Code CLI + MCP server for every voice command, the pool
keeps long-lived `claude -p --input-format stream-json --output-format
stream-json` processes alive:

  - one live worker per active conversation (follow-up turns reuse the
    process: no CLI boot, no MCP handshake, session context in memory)
  - one pre-warmed spare so even NEW conversations skip the cold start
    (the spare is spawned with the most recently seen agent profile)

File IPC is identical to assist-listener.sh — same requests/ and
responses/ directories, same atomic claim-by-rename, same response JSON —
so the HA integration needs no changes and the classic listener remains a
drop-in fallback (assist_fast_mode: false).

Resilience: any worker error/timeout falls back to a one-shot
`claude -p` invocation (exactly what the classic listener does), so the
worst case equals current behavior. Claude session ids are persisted to
sessions/<conversation_id> so context survives pool restarts via --resume.

Stdlib only, by design (matches ha_mcp_server.py).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue

# ---------------------------------------------------------------------------
# Configuration (env-overridable; tests point these at temp dirs/stubs)
# ---------------------------------------------------------------------------

SHARED_DIR = os.environ.get("BRAIN_SHARED_DIR", "/config/.brain")
REQUESTS_DIR = os.path.join(SHARED_DIR, "requests")
RESPONSES_DIR = os.path.join(SHARED_DIR, "responses")
SESSIONS_DIR = os.path.join(SHARED_DIR, "sessions")
CACHE_DIR = os.path.join(SHARED_DIR, "cache")
LOG_DIR = os.path.join(SHARED_DIR, "logs")
AREA_MAP_FILE = os.path.join(CACHE_DIR, "area_map.txt")

WORK_DIR = os.environ.get("BRAIN_ASSIST_WORKDIR", "/config")

MAX_TURNS = os.environ.get("BRAIN_ASSIST_MAX_TURNS", "5")
DEFAULT_TIMEOUT = int(os.environ.get("BRAIN_ASSIST_TIMEOUT", "105"))
TIMEOUT_MARGIN = 15
LIMIT_FLOOR = int(os.environ.get("BRAIN_ASSIST_LIMIT_FLOOR", "30"))

POLL_INTERVAL = float(os.environ.get("BRAIN_ASSIST_POLL", "0.15"))
MAX_WORKERS = int(os.environ.get("BRAIN_ASSIST_POOL_SIZE", "3"))
WORKER_IDLE_REAP = int(os.environ.get("BRAIN_ASSIST_IDLE_REAP", "300"))
WORKER_MAX_AGE = int(os.environ.get("BRAIN_ASSIST_MAX_AGE", "1800"))
SPARE_RECYCLE = int(os.environ.get("BRAIN_ASSIST_SPARE_RECYCLE", "600"))

AREA_MAP_TTL = 300
AREA_MAP_MAX_BYTES = 16000

# Learned household memory (see brain memory / the memory consolidator). The
# voice distillate is spliced into the system prompt, and finished
# conversations can be reflected into new candidate facts.
MEMORY_DIR = os.environ.get("BRAIN_MEMORY_DIR", "/config/.brain/memory")
MEMORY_FILE = os.path.join(MEMORY_DIR, "memory.md")
VOICE_FILE = os.path.join(MEMORY_DIR, "voice.md")
MEMORY_INBOX_DIR = os.path.join(MEMORY_DIR, "inbox")
MEMORY_MAX_BYTES = 2048
MEMORY_TTL = 300
MEMORY_INJECTION = os.environ.get("BRAIN_MEMORY_INJECTION", "true").lower() != "false"
ASSIST_LEARNING = os.environ.get("BRAIN_ASSIST_LEARNING", "true").lower() != "false"

# Transcript buffer caps (per worker) and the trigger heuristic for the
# end-of-conversation reflection pass.
TRANSCRIPT_MAX_EXCHANGES = 8
TRANSCRIPT_MAX_BYTES = 4096
REFLECT_KEYWORDS = (
    "actually", "remember", "call it", "we call", "always", "never",
    "prefer", "instead",
)
REFLECT_TIMEOUT = 60
REFLECT_MODEL = os.environ.get("BRAIN_MEMORY_MODEL", "haiku")

REFLECTION_PROMPT = (
    "From this smart-home voice conversation, extract 0-3 durable facts "
    "worth remembering about the household (preferences, corrections, "
    "entity nicknames, patterns). Exclude transient states, one-off "
    "commands, secrets, anything sensitive. Output one JSON object per "
    'line: {"fact": ..., "confidence": "high|medium|low"} or the single '
    "word NONE."
)

# HA's configured timezone (written by run.sh at startup; refreshed here as
# a fallback). Voice answers must use local time, never the container UTC.
TIMEZONE_FILE = os.path.join(CACHE_DIR, "ha_timezone")

# Internal HTTP API (health + streaming conversations). Reachable by HA Core
# over the hassio network; conversation requests require the shared token.
# 8099 belongs to the ingress panel in the merged add-on; the worker pool's
# internal API moved to 8098. The integration never hardcodes this — it reads
# the port back out of the endpoint file publish_endpoint() writes.
API_PORT = int(os.environ.get("BRAIN_API_PORT", "8098"))
API_TOKEN_FILE = os.path.join(SHARED_DIR, "api_token")
API_ENDPOINT_FILE = os.path.join(SHARED_DIR, "api_endpoint.json")
POOL_STATUS_FILE = os.path.join(CACHE_DIR, "pool_status.json")

# Voice tool scoping: with mcp_only (default), workers get a deny-list
# settings file so voice can control the house but not run Bash/edit files.
TOOL_ACCESS = os.environ.get("BRAIN_ASSIST_TOOL_ACCESS", "mcp_only")
ASSIST_SETTINGS_FILE = os.path.join(SHARED_DIR, "assist_settings.json")

# --include-partial-messages gives token-level deltas for streaming TTS.
# Disabled automatically if the installed CLI predates the flag.
PARTIAL_MESSAGES_OK = True

# Last-used agent profile (custom prompt + model), persisted so the spare
# can be pre-warmed right at startup instead of after the first request.
LAST_PROFILE_FILE = os.path.join(CACHE_DIR, "last_profile.json")

# Claude CLI auth failures surface as the response text in -p / stream-json
# modes ("Failed to authenticate: OAuth session expired and could not be
# refreshed", "Please run /login", ...). Detect them so users get an
# actionable message instead of a raw CLI error, and so the pool recycles
# its workers — fresh processes re-read the credentials file, which the
# user fixes by logging in once in the interactive terminal.
# Deliberately specific phrasings — a legitimate assistant answer that
# merely mentions logins/refreshing must never trip this.
AUTH_ERROR_RE = re.compile(
    r"OAuth session expired|OAuth token (?:refresh failed|revoked)"
    r"|failed to authenticate|please run /login|invalid api key"
    r"|authentication[_ ]error",
    re.IGNORECASE,
)
AUTH_ERROR_MESSAGE = (
    "Claude's saved login has expired and could not be refreshed "
    "automatically. Open the brAIn add-on from the sidebar and run "
    "/login once — Assist and background tasks pick up the fresh login "
    "automatically."
)

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
TEMPLATE_API = os.environ.get(
    "BRAIN_TEMPLATE_API", "http://supervisor/core/api/template"
)
HA_CONFIG_API = os.environ.get(
    "BRAIN_HA_CONFIG_API", "http://supervisor/core/api/config"
)

# Mirrors the area-map template in assist-listener.sh — pure core Jinja so
# it renders on any HA version. Weather/People come FIRST so an oversized,
# truncated map can only ever drop areas, never these sections. Keep the
# two copies in sync.
AREA_MAP_TEMPLATE = """\
{%- set domains = ['light','switch','climate','media_player','cover','fan','lock','vacuum','scene','script','alarm_control_panel','input_boolean'] -%}
{%- set weather = states.weather | map(attribute='entity_id') | list -%}
{%- if weather %}Weather: {{ weather | join(', ') }}
{% endif -%}
{%- set people = states.person | map(attribute='entity_id') | list -%}
{%- if people %}People: {{ people | join(', ') }}
{% endif -%}
{%- for a in areas() -%}
{%- set ns = namespace(ents=[]) -%}
{%- for e in area_entities(a) -%}
{%- if '.' in e and e.split('.')[0] in domains -%}{%- set ns.ents = ns.ents + [e] -%}{%- endif -%}
{%- endfor -%}
{%- if ns.ents %}{{ area_name(a) }}: {{ ns.ents | join(', ') }}
{% endif -%}
{%- endfor -%}
"""

# Prompt layering (mirrored in assist-listener.sh — keep in sync):
# identity/tone/verbosity come from exactly ONE source. A custom personality
# leads with explicit precedence and the operational block stays
# identity-free; without one, the default style applies. Mixing two
# "You are X" statements is what waters personalities down.
PERSONALITY_FRAME = """PERSONALITY — this defines who you are, how you speak, and how verbose you are. It takes precedence over any tone or style implied by the instructions below:
{custom}"""

DEFAULT_STYLE_PROMPT = """You are a helpful, efficient Home Assistant voice assistant. Answer in 1-2 short sentences unless the user explicitly asks for detail."""

OPERATIONAL_PROMPT = """You are connected to the user's Home Assistant with FULL authorization to control all devices — never ask for permission or confirmation. Act on requests immediately, then confirm.
Replies are spoken aloud by TTS.
Use your MCP tools (control_light, control_climate, control_media_player, control_cover, control_fan, control_switch, control_lock, control_alarm, control_vacuum, call_service, get_all_states, get_areas, activate_scene, run_script, send_notification, get_service_details).
For questions about the PAST ('how cold did it get last night', 'when did the garage open'), use get_history (recent detail) or get_statistics (daily min/max/mean over weeks).
For FORECASTS ('weather tomorrow / this week'), use get_weather_forecast; get_entity_state on the weather entity only gives current conditions.
To CHECK A CAMERA or visually verify something, use get_camera_snapshot and describe what you see.
When the user states a durable preference, correction, or nickname ('actually...', 'we call X...', 'always/never...'), call the remember_fact tool so it sticks for future conversations."""

MAP_PROMPT = """

Known areas and their controllable entity_ids (current and complete):
{area_map}

Act on these entity_ids DIRECTLY with your control_* tools in your FIRST response — never call get_areas or get_all_states to verify an entity that is already listed.
For weather questions, call get_entity_state on a Weather entity above.
Only for entities not listed anywhere above, search with get_all_states (domain and name_filter arguments)."""

NO_MAP_PROMPT = """
For room/area requests (e.g. 'turn off the bedroom lights') call get_areas to resolve the room to entity_ids first.
If unsure of an entity_id, call get_all_states with a domain filter first."""


def log(msg: str) -> None:
    print(f"[assist-pool] {msg}", flush=True)


def debug_log(lines: list[str]) -> None:
    """Append to the same daily debug log the classic listener uses.

    These logs contain full voice/request transcripts, so they are created
    0600 — under /config they otherwise ride along into every HA full
    backup readable by anything that can open the archive."""
    path = os.path.join(LOG_DIR, f"assist-{time.strftime('%Y%m%d')}.log")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as fh:
            for line in lines:
                fh.write(line.replace("{ts}", stamp) + "\n")
    except OSError:
        pass


def resolve_claude_cmd() -> list[str]:
    """Resolve how to invoke claude, matching the listeners' logic."""
    override = os.environ.get("BRAIN_CLAUDE_BIN", "")
    if override:
        return shlex.split(override)
    if os.access("/usr/local/bin/claude-run", os.X_OK):
        return ["/usr/local/bin/claude-run"]
    if os.geteuid() == 0:
        return ["su-exec", "claude", "/root/.local/bin/claude"]
    return ["claude"]


def scoping_args() -> list:
    """Per-channel tool scoping: in mcp_only mode workers load a deny-list
    settings file (written by run.sh) that blocks Bash/file/web tools while
    the project allowlist keeps every MCP tool available."""
    if TOOL_ACCESS == "mcp_only" and os.path.isfile(ASSIST_SETTINGS_FILE):
        return ["--settings", ASSIST_SETTINGS_FILE]
    return []


# ---------------------------------------------------------------------------
# Area map (same cache file as the classic listener)
# ---------------------------------------------------------------------------

_area_lock = threading.Lock()


def refresh_area_map() -> bool:
    if not SUPERVISOR_TOKEN:
        return False
    payload = json.dumps({"template": AREA_MAP_TEMPLATE}).encode()
    req = urllib.request.Request(
        TEMPLATE_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            rendered = resp.read().decode()
    except Exception as exc:  # noqa: BLE001
        debug_log([f"[{{ts}}] AREA-MAP refresh FAILED: {exc}"])
        return False
    if not rendered or rendered.startswith("{") or ":" not in rendered:
        debug_log([f"[{{ts}}] AREA-MAP refresh FAILED: {rendered[:300]}"])
        return False
    if len(rendered) > AREA_MAP_MAX_BYTES:
        debug_log([
            f"[{{ts}}] AREA-MAP truncated: {len(rendered)} chars > "
            f"{AREA_MAP_MAX_BYTES} (some areas omitted)"
        ])
        rendered = _truncate_at_line(rendered, AREA_MAP_MAX_BYTES)
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = AREA_MAP_FILE + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(rendered)
    os.replace(tmp, AREA_MAP_FILE)
    return True


def _truncate_at_line(text: str, cap: int) -> str:
    """Cap text without leaving a cut-off entity_id on the last line."""
    if len(text) <= cap:
        return text
    cut = text[:cap]
    return cut[: cut.rfind("\n") + 1]


def get_area_map() -> str:
    """Cached map with stale-while-revalidate, like the classic listener."""
    try:
        age = time.time() - os.path.getmtime(AREA_MAP_FILE)
        if age > AREA_MAP_TTL:
            threading.Thread(target=refresh_area_map, daemon=True).start()
        with open(AREA_MAP_FILE) as fh:
            return fh.read()
    except OSError:
        with _area_lock:
            refresh_area_map()
        try:
            with open(AREA_MAP_FILE) as fh:
                return fh.read()
        except OSError:
            return ""


# ---------------------------------------------------------------------------
# Learned household memory (voice distillate)
# ---------------------------------------------------------------------------

_memory_lock = threading.Lock()
# text=None means "never loaded" (get_memory then loads synchronously once).
_memory_cache: dict = {"text": None, "ts": 0.0}


def refresh_memory() -> None:
    """(Re)load the learned-household snippet for the system prompt.

    Prefers voice.md (the consolidator's distillate), falls back to the
    first 2 KB of memory.md. The result is CACHED: the system prompt is
    part of the worker profile tuple, so it must stay stable between the
    spare pre-warm and the requests that would adopt that spare (see the
    area-map note in main()). Refreshes happen only at startup and on the
    housekeeping cadence — never per request.
    """
    text = ""
    for path in (VOICE_FILE, MEMORY_FILE):
        try:
            with open(path) as fh:
                text = fh.read(MEMORY_MAX_BYTES + 1)
        except OSError:
            continue
        if text.strip():
            break
        text = ""
    if len(text) > MEMORY_MAX_BYTES:
        text = _truncate_at_line(text, MEMORY_MAX_BYTES)
    with _memory_lock:
        _memory_cache["text"] = text
        _memory_cache["ts"] = time.time()


def get_memory() -> str:
    """Cached memory snippet (loads synchronously on first use)."""
    with _memory_lock:
        cached = _memory_cache["text"]
    if cached is None:
        refresh_memory()
        with _memory_lock:
            cached = _memory_cache["text"] or ""
    return cached


def get_ha_timezone() -> str:
    """HA's time_zone, from the startup cache or fetched directly."""
    try:
        with open(TIMEZONE_FILE) as fh:
            tz = fh.read().strip()
        if tz:
            return tz
    except OSError:
        pass
    if not SUPERVISOR_TOKEN:
        return ""
    try:
        req = urllib.request.Request(
            HA_CONFIG_API,
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            tz = json.loads(resp.read().decode()).get("time_zone") or ""
        if tz:
            os.makedirs(CACHE_DIR, exist_ok=True)
            with open(TIMEZONE_FILE, "w") as fh:
                fh.write(tz)
        return tz
    except Exception:  # noqa: BLE001
        return ""


def local_time_line() -> str:
    """One-line local-time stamp prepended to each user message, so 'what
    time is it' costs zero tool calls and answers in the right zone."""
    tz = get_ha_timezone()
    if not tz:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(tz))
        return f"(Local time: {now.strftime('%A %Y-%m-%d %H:%M')} {tz})\n"
    except Exception:  # noqa: BLE001 — missing tzdata etc.: skip the stamp
        return ""


def build_system_prompt(custom: str) -> str:
    if custom:
        prompt = PERSONALITY_FRAME.format(custom=custom) + "\n\n" + OPERATIONAL_PROMPT
    else:
        prompt = DEFAULT_STYLE_PROMPT + "\n" + OPERATIONAL_PROMPT
    tz = get_ha_timezone()
    if tz:
        prompt += (
            f"\nThe user's timezone is {tz}. Every user message starts with "
            "the current local time — ALWAYS answer times in that local "
            "timezone, never UTC."
        )
    area_map = get_area_map()
    if area_map.strip():
        prompt += MAP_PROMPT.format(area_map=area_map.rstrip())
    else:
        prompt += NO_MAP_PROMPT
    if MEMORY_INJECTION:
        memory = get_memory()
        if memory.strip():
            prompt += "\n\nKnown about this household (learned):\n" + memory.rstrip()
    return prompt


def save_last_profile(custom: str, model: str, denied_csv: str = "") -> None:
    """Remember the agent profile so the next pool start pre-warms with it."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = LAST_PROFILE_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(
                {"system_prompt": custom, "model": model, "denied": denied_csv}, fh
            )
        os.replace(tmp, LAST_PROFILE_FILE)
    except OSError:
        pass


def normalize_denied(value) -> str:
    """Normalize a deny-list (list or csv) to a stable, sorted csv string so
    it can key the worker profile and ride in the MCP env."""
    if isinstance(value, str):
        parts = value.split(",")
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = []
    cleaned = sorted({str(p).strip().lower() for p in parts if str(p).strip()})
    return ",".join(cleaned)


def prewarm_spare(pool: "Pool") -> None:
    """Spawn the spare at startup from the last-used agent profile, so even
    the first voice command after an add-on restart skips the cold start."""
    custom, model, denied = "", "default", ""
    try:
        with open(LAST_PROFILE_FILE) as fh:
            data = json.load(fh)
        custom = data.get("system_prompt") or ""
        model = data.get("model") or "default"
        denied = data.get("denied") or ""
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    pool._spawn_spare((build_system_prompt(custom), model, denied))


# ---------------------------------------------------------------------------
# Assist learning: end-of-conversation reflection into the memory inbox
# ---------------------------------------------------------------------------


def _record_exchange(worker: "Worker", user_text: str, response_text: str) -> None:
    """Append one exchange to a worker's bounded transcript buffer."""
    try:
        worker.transcript.append(
            (str(user_text)[:800], str(response_text)[:800])
        )
        while len(worker.transcript) > TRANSCRIPT_MAX_EXCHANGES or sum(
            len(u) + len(a) for u, a in worker.transcript
        ) > TRANSCRIPT_MAX_BYTES:
            worker.transcript.pop(0)
    except Exception:  # noqa: BLE001 — bookkeeping must never break requests
        pass


def _transcript_worth_reflecting(transcript: list) -> bool:
    """Cheap heuristic: multi-exchange conversations, or single exchanges
    containing corrective/preference language, are worth a reflection."""
    if not transcript:
        return False
    if len(transcript) >= 2:
        return True
    blob = " ".join(u.lower() for u, _ in transcript)
    return any(kw in blob for kw in REFLECT_KEYWORDS)


def reflect_on_transcript(transcript: list) -> None:
    """One-shot cheap Claude pass extracting durable facts (daemon thread).

    Never raises: any failure (unauthenticated, timeout, garbage output)
    just means no facts are stored this time.
    """
    try:
        convo = "\n".join(f"USER: {u}\nASSISTANT: {a}" for u, a in transcript)
        cmd = resolve_claude_cmd() + [
            "-p",
            "--disallowedTools", "*",
            "--max-turns", "1",
            "--model", REFLECT_MODEL,
        ]
        proc = subprocess.run(
            cmd,
            input=REFLECTION_PROMPT + "\n\nConversation:\n" + convo,
            capture_output=True,
            text=True,
            timeout=REFLECT_TIMEOUT,
            cwd=WORK_DIR,
        )
        if proc.returncode != 0:
            return
        facts = []
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line or line.upper() == "NONE":
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            fact = obj.get("fact")
            if not isinstance(fact, str) or not fact.strip():
                continue
            confidence = obj.get("confidence")
            if confidence not in ("high", "medium", "low"):
                confidence = "medium"
            facts.append({
                "ts": int(time.time()),
                "source": "assist",
                "fact": fact.strip()[:500],
                "confidence": confidence,
            })
            if len(facts) >= 3:
                break
        if not facts:
            return
        os.makedirs(MEMORY_INBOX_DIR, exist_ok=True)
        path = os.path.join(MEMORY_INBOX_DIR, f"{int(time.time())}-assist.jsonl")
        with open(path, "a") as fh:
            for record in facts:
                fh.write(json.dumps(record) + "\n")
        log(f"reflection stored {len(facts)} candidate fact(s)")
    except Exception as exc:  # noqa: BLE001 — reflection must never crash the pool
        try:
            log(f"reflection skipped: {exc}")
        except Exception:  # noqa: BLE001
            pass


def maybe_reflect(worker: "Worker") -> None:
    """Kick off a background reflection for a worker being retired."""
    if not ASSIST_LEARNING:
        return
    try:
        transcript = list(worker.transcript)
        worker.transcript = []  # never reflect the same exchanges twice
    except Exception:  # noqa: BLE001
        return
    if not _transcript_worth_reflecting(transcript):
        return
    threading.Thread(
        target=reflect_on_transcript, args=(transcript,), daemon=True
    ).start()


# ---------------------------------------------------------------------------
# Worker: one live `claude` stream-json process
# ---------------------------------------------------------------------------


class Worker:
    def __init__(self, profile: tuple, resume: str | None = None):
        self.profile = profile  # (system_prompt, model, denied_services_csv)
        self.created = time.time()
        self.last_used = self.created
        self.session_id: str | None = None
        self.lock = threading.Lock()  # serializes turns on this worker
        self._events: Queue = Queue()
        # Bounded conversation buffer for the end-of-life reflection pass
        # (see _record_exchange / maybe_reflect).
        self.transcript: list = []

        system_prompt, model, denied_csv = profile
        cmd = resolve_claude_cmd() + [
            "-p",
            "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            # Generous cap: in stream-json mode the budget spans the whole
            # process, not one request; per-request control is the timeout.
            "--max-turns", str(max(int(MAX_TURNS) * 10, 50)),
            "--system-prompt", system_prompt,
        ]
        if PARTIAL_MESSAGES_OK:
            cmd += ["--include-partial-messages"]
        cmd += scoping_args()
        if model and model != "default":
            cmd += ["--model", model]
        if resume:
            cmd += ["--resume", resume]
            self.session_id = resume

        # Pass this agent's service deny-list to the MCP server (inherited
        # via claude's environment). Per-worker, so it is per-agent.
        env = dict(os.environ)
        env["BRAIN_DENIED_SERVICES"] = denied_csv
        self.proc = subprocess.Popen(
            cmd,
            cwd=WORK_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=env,
        )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        try:
            for line in self.proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = event.get("session_id")
                if sid:
                    self.session_id = sid
                self._events.put(event)
        finally:
            self._events.put({"type": "_eof"})

    def alive(self) -> bool:
        return self.proc.poll() is None

    def ask(self, text: str, deadline: float, delta_cb=None) -> str | None:
        """Send one user message, wait for its result event.

        When delta_cb is given, assistant text is forwarded incrementally:
        token-level via stream_event deltas when the CLI supports
        --include-partial-messages, otherwise per-turn via assistant
        message events.
        """
        msg = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}],
            },
        }
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")  # type: ignore[union-attr]
            self.proc.stdin.flush()  # type: ignore[union-attr]
        except (OSError, ValueError):
            return None

        saw_partial = False
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            try:
                event = self._events.get(timeout=min(remaining, 1.0))
            except Empty:
                continue
            etype = event.get("type")
            if etype == "_eof":
                return None
            if etype == "stream_event" and delta_cb is not None:
                delta = (event.get("event") or {}).get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    saw_partial = True
                    delta_cb(delta["text"])
            elif etype == "assistant" and delta_cb is not None and not saw_partial:
                # Coarse fallback: stream each turn's text as one chunk
                for block in (event.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        delta_cb(block["text"])
            elif etype == "result":
                if event.get("is_error"):
                    return None
                result = event.get("result")
                return result if isinstance(result, str) and result else None

    def kill(self) -> None:
        try:
            self.proc.kill()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Pool
# ---------------------------------------------------------------------------


class Pool:
    def __init__(self) -> None:
        self.workers: dict[str, Worker] = {}  # conversation_id -> Worker
        self.spare: Worker | None = None
        self.lock = threading.Lock()
        self.conv_locks: dict[str, threading.Lock] = {}
        self.started = time.time()
        self.last_request: dict | None = None

    # -- worker lifecycle ---------------------------------------------------

    def _spawn_spare(self, profile: tuple[str, str]) -> None:
        def _do() -> None:
            try:
                worker = Worker(profile)
            except OSError as exc:
                log(f"spare spawn failed: {exc}")
                return
            with self.lock:
                if self.spare is not None:
                    self.spare.kill()
                self.spare = worker
        threading.Thread(target=_do, daemon=True).start()

    def _take_worker(
        self, conv_id: str, profile: tuple[str, str]
    ) -> tuple[Worker, str]:
        """Return (worker, mode) where mode is warm|spare|cold."""
        with self.lock:
            worker = self.workers.get(conv_id)
            if worker and worker.alive() and worker.profile == profile:
                # clear_conversation deletes the session mapping; a live
                # worker that already answered must honor that and start
                # fresh instead of reusing its in-process context.
                if worker.last_used > worker.created and not os.path.isfile(
                    os.path.join(SESSIONS_DIR, conv_id)
                ):
                    worker.kill()
                    self.workers.pop(conv_id, None)
                else:
                    return worker, "warm"
            elif worker:
                worker.kill()
                self.workers.pop(conv_id, None)

            if (
                self.spare is not None
                and self.spare.alive()
                and self.spare.profile == profile
            ):
                worker = self.spare
                self.spare = None
                self.workers[conv_id] = worker
                self._spawn_spare(profile)
                return worker, "spare"

        # Cold spawn (outside the lock — process startup can take seconds).
        resume = self._stored_session(conv_id)
        worker = Worker(profile, resume=resume)
        with self.lock:
            self.workers[conv_id] = worker
        if self.spare is None or not self.spare.alive():
            self._spawn_spare(profile)
        return worker, "cold" if not resume else "cold-resume"

    def drop_all(self) -> None:
        """Kill every pooled worker and the spare (e.g. after an auth
        failure) so the next request spawns fresh processes that re-read
        the credentials file from disk."""
        with self.lock:
            for conv_id, worker in list(self.workers.items()):
                worker.kill()
                self.workers.pop(conv_id, None)
            if self.spare is not None:
                self.spare.kill()
                self.spare = None

    def _drop_worker(self, conv_id: str, worker: Worker) -> None:
        maybe_reflect(worker)
        worker.kill()
        with self.lock:
            if self.workers.get(conv_id) is worker:
                self.workers.pop(conv_id, None)

    @staticmethod
    def _stored_session(conv_id: str) -> str | None:
        try:
            with open(os.path.join(SESSIONS_DIR, conv_id)) as fh:
                sid = "".join(c for c in fh.read() if c in "0123456789abcdef-")
            return sid if len(sid) == 36 else None
        except OSError:
            return None

    @staticmethod
    def _store_session(conv_id: str, session_id: str | None) -> None:
        if not session_id:
            return
        try:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            with open(os.path.join(SESSIONS_DIR, conv_id), "w") as fh:
                fh.write(session_id)
        except OSError:
            pass

    def reap(self) -> None:
        now = time.time()
        with self.lock:
            for conv_id, worker in list(self.workers.items()):
                if (
                    not worker.alive()
                    or now - worker.last_used > WORKER_IDLE_REAP
                    or now - worker.created > WORKER_MAX_AGE
                ):
                    maybe_reflect(worker)
                    worker.kill()
                    self.workers.pop(conv_id, None)
            # Enforce the cap (LRU), keeping the most recently used.
            while len(self.workers) > MAX_WORKERS - 1:
                oldest = min(self.workers, key=lambda c: self.workers[c].last_used)
                evicted = self.workers.pop(oldest)
                maybe_reflect(evicted)
                evicted.kill()
            # Recycle a stale spare so its baked-in area map stays fresh.
            if self.spare is not None and (
                not self.spare.alive() or now - self.spare.created > SPARE_RECYCLE
            ):
                profile = self.spare.profile
                self.spare.kill()
                self.spare = None
                self._spawn_spare(profile)
        # Refresh the cached memory snippet on the same housekeeping
        # cadence the spare/area map use — never per request, because the
        # system prompt keys the worker profile (spare adoption).
        with _memory_lock:
            memory_age = now - _memory_cache["ts"]
        if memory_age > MEMORY_TTL:
            threading.Thread(target=refresh_memory, daemon=True).start()

    # -- request handling -----------------------------------------------------

    def handle(self, req: dict) -> None:
        """File-protocol frontend: process the request, write the response."""
        response = self.process(req)
        write_response(req["id"], response)

    def process(self, req: dict, delta_cb=None) -> str:
        req_id = req["id"]
        text = req["text"]
        conv_id = "".join(
            c for c in str(req.get("conversation_id") or req_id)
            if c.isalnum() or c in "_-"
        )
        timeout = req.get("timeout")
        window = timeout if isinstance(timeout, int) and timeout > 0 else DEFAULT_TIMEOUT
        limit = max(window - TIMEOUT_MARGIN, LIMIT_FLOOR)
        deadline = time.time() + limit

        custom_prompt = req.get("system_prompt") or ""
        model = req.get("model") or "default"
        denied_csv = normalize_denied(req.get("denied_services"))
        system_prompt = build_system_prompt(custom_prompt)
        profile = (system_prompt, model, denied_csv)
        save_last_profile(custom_prompt, model, denied_csv)

        debug_log([
            "================================================================",
            f"[{{ts}}] REQUEST {req_id}",
            "  Channel:  conversation_agent (fast mode)",
            f"  Text:     {text}",
            f"  Model:    {model}",
            f"  AreaMap:  {len(get_area_map())} chars",
        ])

        start = time.time()
        conv_lock = self.conv_locks.setdefault(conv_id, threading.Lock())
        with conv_lock:
            try:
                worker, mode = self._take_worker(conv_id, profile)
                message = local_time_line() + text
                # A truly fresh session can't see earlier turns — replay the
                # transcript the integration sends (like the classic listener).
                if mode == "cold" and req.get("conversation_history"):
                    lines = [
                        f"{m.get('role', '?').upper()}: {m.get('content', '')}"
                        for m in req["conversation_history"]
                    ]
                    message = (
                        "Previous conversation:\n" + "\n".join(lines)
                        + f"\n\n{local_time_line()}USER: {text}"
                    )

                with worker.lock:
                    response = worker.ask(message, deadline, delta_cb=delta_cb)
                if response is None and not worker.alive() and \
                        time.time() - worker.created < 5 and PARTIAL_MESSAGES_OK:
                    # CLI likely predates --include-partial-messages: disable
                    # it for future workers and let the fallback answer now.
                    globals()["PARTIAL_MESSAGES_OK"] = False
                    log("worker died at spawn — disabling --include-partial-messages")
                if response is not None:
                    worker.last_used = time.time()
                    self._store_session(conv_id, worker.session_id)
                    _record_exchange(worker, text, response)
                else:
                    # Worker hung, died, or errored — drop it and fall back
                    # to a one-shot invocation within the remaining budget.
                    self._drop_worker(conv_id, worker)
                    mode += "+fallback"
                    response = self._oneshot(req, system_prompt, model, deadline, denied_csv)
            except Exception as exc:  # noqa: BLE001 — never drop a request
                log(f"worker path failed for {req_id}: {exc}")
                mode = "error+fallback"
                response = self._oneshot(req, system_prompt, model, deadline, denied_csv)

        duration = time.time() - start
        if response and AUTH_ERROR_RE.search(response):
            log(f"request {req_id}: Claude auth failure — recycling worker pool "
                f"({response[:160]!r})")
            self.drop_all()
            response = AUTH_ERROR_MESSAGE
        if response is None:
            if time.time() >= deadline:
                response = (
                    f"Claude timed out after {int(duration)}s. This may be "
                    "caused by a broken MCP server connection. Try restarting "
                    "the brAIn add-on."
                )
            else:
                response = (
                    "Sorry, Claude didn't produce a response. Check the BRUH "
                    "Claude Terminal add-on logs for details."
                )

        debug_log([
            f"[{{ts}}] RESPONSE {req_id}",
            f"  Duration:  {duration:.1f}s",
            f"  Worker:    {mode}",
            f"  Response:  {len(response)} chars",
            f"  Preview:   {response[:200]}",
            "----------------------------------------------------------------",
        ])
        log(f"request {req_id}: {duration:.1f}s ({mode})")
        self.last_request = {
            "ts": time.time(), "duration_s": round(duration, 1), "mode": mode,
        }
        write_pool_status(self)
        return response

    @staticmethod
    def _oneshot(
        req: dict, system_prompt: str, model: str, deadline: float,
        denied_csv: str = "",
    ) -> str | None:
        """Classic spawn-per-request fallback — identical to the bash path."""
        remaining = int(deadline - time.time())
        if remaining < 10:
            return None
        text = local_time_line() + req["text"]
        if req.get("conversation_history"):
            lines = [
                f"{m.get('role', '?').upper()}: {m.get('content', '')}"
                for m in req["conversation_history"]
            ]
            text = "Previous conversation:\n" + "\n".join(lines) + f"\n\nUSER: {text}"
        cmd = resolve_claude_cmd() + [
            "-p", "--verbose",
            "--max-turns", str(MAX_TURNS),
            "--system-prompt", system_prompt,
        ] + scoping_args()
        if model and model != "default":
            cmd += ["--model", model]
        env = dict(os.environ)
        env["BRAIN_DENIED_SERVICES"] = denied_csv
        try:
            proc = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=remaining,
                cwd=WORK_DIR,
                env=env,
            )
            return proc.stdout.strip() or None
        except (subprocess.TimeoutExpired, OSError):
            return None


# ---------------------------------------------------------------------------
# HTTP frontend: /health (liveness open; telemetry token-auth) +
# /conversation (token-auth, SSE streaming)
# ---------------------------------------------------------------------------


def load_or_create_token() -> str:
    """Shared secret for the conversation endpoint, exchanged over the
    /config volume both containers already share (0600)."""
    try:
        with open(API_TOKEN_FILE) as fh:
            token = fh.read().strip()
        if len(token) >= 16:
            return token
    except OSError:
        pass
    token = secrets.token_hex(16)
    os.makedirs(SHARED_DIR, exist_ok=True)
    fd = os.open(API_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token)
    return token


def publish_endpoint(port: int) -> None:
    """Tell the integration where to find us (read off the shared volume).
    The container hostname is reachable from HA Core on the hassio network."""
    data = {
        "host": os.environ.get("HOSTNAME") or socket.gethostname(),
        "port": port,
        "protocol_version": 1,
        "ts": time.time(),
    }
    tmp = API_ENDPOINT_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(data, fh)
    os.replace(tmp, API_ENDPOINT_FILE)


def write_pool_status(pool) -> None:
    """Heartbeat consumed by the integration's health sensor (file fallback
    when the HTTP endpoint isn't reachable)."""
    try:
        status = {
            "ts": time.time(),
            "status": "ok",
            "workers": len(pool.workers),
            "spare_ready": bool(pool.spare is not None and pool.spare.alive()),
            "uptime_s": int(time.time() - pool.started),
            "last_request": pool.last_request,
            "tool_access": TOOL_ACCESS,
        }
        tmp = POOL_STATUS_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(status, fh)
        os.replace(tmp, POOL_STATUS_FILE)
    except OSError:
        pass


class ApiHandler(BaseHTTPRequestHandler):
    """Stdlib HTTP handler — one thread per connection via ThreadingHTTPServer."""

    pool: "Pool" = None  # set by start_http_server
    token: str = ""

    # Quiet the default per-request stderr logging
    def log_message(self, fmt, *args):  # noqa: N802
        pass

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _token_ok(self) -> bool:
        # Constant-time compare: this token gates an endpoint whose prompt
        # grants full device control, so no timing side channels.
        supplied = self.headers.get("X-BRUH-Token", "")
        return bool(self.token) and secrets.compare_digest(supplied, self.token)

    def do_GET(self):  # noqa: N802
        if self.path != "/health":
            self._json(404, {"error": "not found"})
            return
        # Unauthenticated callers get liveness only; operational telemetry
        # (worker counts, request timing, tool access) needs the token.
        if not self._token_ok():
            self._json(200, {"status": "ok"})
            return
        pool = self.pool
        self._json(200, {
            "status": "ok",
            "workers": len(pool.workers),
            "spare_ready": bool(pool.spare is not None and pool.spare.alive()),
            "uptime_s": int(time.time() - pool.started),
            "last_request": pool.last_request,
            "tool_access": TOOL_ACCESS,
        })

    def do_POST(self):  # noqa: N802
        if self.path != "/conversation":
            self._json(404, {"error": "not found"})
            return
        if not self._token_ok():
            self._json(401, {"error": "bad token"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(length))
        except Exception:  # noqa: BLE001
            self._json(400, {"error": "invalid request body"})
            return
        # Explicit validation, NOT assert: asserts vanish under `python -O`,
        # which would turn malformed input into an unhandled error path.
        if not isinstance(req, dict) or not req.get("id") or not req.get("text"):
            self._json(400, {"error": "invalid request body"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        write_lock = threading.Lock()

        def emit(payload: dict) -> None:
            data = f"data: {json.dumps(payload)}\n\n".encode()
            with write_lock:
                self.wfile.write(data)
                self.wfile.flush()

        def delta_cb(text: str) -> None:
            try:
                emit({"type": "delta", "text": text})
            except OSError:
                pass  # client went away; result still completes server-side

        try:
            response = self.pool.process(req, delta_cb=delta_cb)
            emit({"type": "result", "text": response})
        except OSError:
            pass  # client disconnected mid-stream
        except Exception as exc:  # noqa: BLE001
            try:
                emit({"type": "error", "message": str(exc)})
            except OSError:
                pass


def start_http_server(pool) -> None:
    """Serve the internal API; failure is non-fatal (file IPC keeps working)."""
    try:
        token = load_or_create_token()
        ApiHandler.pool = pool
        ApiHandler.token = token
        # The API must be reachable by HA Core over the hassio network, so
        # loopback-only is not an option by default — but the bind address
        # is overridable for setups that can scope it tighter. Every
        # endpoint is token-gated (or telemetry-free) regardless.
        bind_addr = os.environ.get("BRAIN_POOL_BIND", "0.0.0.0")
        server = ThreadingHTTPServer((bind_addr, API_PORT), ApiHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        publish_endpoint(API_PORT)
        log(f"HTTP API listening on :{API_PORT} (health + streaming conversations)")
    except Exception as exc:  # noqa: BLE001
        log(f"HTTP API failed to start ({exc}) — file IPC only")
        try:
            os.remove(API_ENDPOINT_FILE)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# File IPC (same protocol as assist-listener.sh)
# ---------------------------------------------------------------------------


def write_response(req_id: str, text: str) -> None:
    os.makedirs(RESPONSES_DIR, exist_ok=True)
    path = os.path.join(RESPONSES_DIR, f"{req_id}.json")
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump({"id": req_id, "text": text}, fh)
    os.replace(tmp, path)


def claim_request(path: str) -> dict | None:
    """Atomically claim and parse a request file; None if lost the race or
    the request is invalid/stale."""
    work = f"{path[:-5]}.work.{os.getpid()}.{uuid.uuid4().hex[:6]}"
    try:
        os.rename(path, work)
    except OSError:
        return None
    try:
        with open(work) as fh:
            req = json.load(fh)
    except (OSError, json.JSONDecodeError):
        req = None
    try:
        os.remove(work)
    except OSError:
        pass
    if not isinstance(req, dict) or not req.get("id") or not req.get("text"):
        return None

    # Discard requests nobody is waiting for anymore.
    timeout = req.get("timeout")
    window = timeout if isinstance(timeout, int) and timeout > 0 else 120
    ts = req.get("ts")
    age = time.time() - ts if isinstance(ts, (int, float)) else 0
    if age > window + 10:
        log(f"discarding stale request {req['id']} ({int(age)}s old)")
        return None
    return req


# Retention: sessions/ otherwise grows one uuid-mapping file per
# conversation forever (slow-motion inode exhaustion on flash-backed HA
# hardware), and logs/ holds plaintext voice transcripts that should not
# accumulate indefinitely — they're captured by HA full backups.
SESSION_RETENTION_S = 7 * 86400   # matches assist-listener.sh's prune
LOG_RETENTION_S = int(os.environ.get("BRAIN_LOG_RETENTION_DAYS", "7")) * 86400


def _prune_older_than(directory: str, cutoff: float) -> None:
    try:
        for name in os.listdir(directory):
            path = os.path.join(directory, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


def cleanup_stale_files() -> None:
    cutoff = time.time() - 1800
    for directory, suffix in ((RESPONSES_DIR, ".json"), (RESPONSES_DIR, ".tmp")):
        try:
            for name in os.listdir(directory):
                if name.endswith(suffix):
                    path = os.path.join(directory, name)
                    try:
                        if os.path.getmtime(path) < cutoff:
                            os.remove(path)
                    except OSError:
                        pass
        except OSError:
            pass
    now = time.time()
    _prune_older_than(SESSIONS_DIR, now - SESSION_RETENTION_S)
    _prune_older_than(LOG_DIR, now - LOG_RETENTION_S)


def main() -> None:
    for d in (REQUESTS_DIR, RESPONSES_DIR, SESSIONS_DIR, CACHE_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)
    try:
        os.chmod(LOG_DIR, 0o700)  # transcripts inside are 0600
    except OSError:
        pass

    log(
        f"starting (poll={POLL_INTERVAL}s, max_workers={MAX_WORKERS}, "
        f"max_turns={MAX_TURNS}, default_timeout={DEFAULT_TIMEOUT}s)"
    )
    # Refresh the map synchronously first so the pre-warmed spare bakes in
    # the same map the first request will build — otherwise their system
    # prompts differ and the spare is never adopted. The learned-memory
    # snippet is part of the same system prompt, so it gets the identical
    # treatment: loaded synchronously once here, then only refreshed on the
    # housekeeping cadence (see Pool.reap), never per request.
    refresh_area_map()
    refresh_memory()
    cleanup_stale_files()

    pool = Pool()
    start_http_server(pool)
    prewarm_spare(pool)
    write_pool_status(pool)
    last_housekeeping = time.time()

    while True:
        try:
            names = [
                n for n in os.listdir(REQUESTS_DIR) if n.endswith(".json")
            ]
        except OSError:
            names = []
        for name in names:
            req = claim_request(os.path.join(REQUESTS_DIR, name))
            if req:
                threading.Thread(
                    target=pool.handle, args=(req,), daemon=True
                ).start()

        now = time.time()
        if now - last_housekeeping > 30:
            last_housekeeping = now
            pool.reap()
            cleanup_stale_files()
            write_pool_status(pool)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
