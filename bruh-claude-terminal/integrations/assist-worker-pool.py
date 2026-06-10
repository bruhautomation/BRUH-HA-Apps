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
import shlex
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from queue import Empty, Queue

# ---------------------------------------------------------------------------
# Configuration (env-overridable; tests point these at temp dirs/stubs)
# ---------------------------------------------------------------------------

SHARED_DIR = os.environ.get("BRUH_SHARED_DIR", "/config/.bruh_claude")
REQUESTS_DIR = os.path.join(SHARED_DIR, "requests")
RESPONSES_DIR = os.path.join(SHARED_DIR, "responses")
SESSIONS_DIR = os.path.join(SHARED_DIR, "sessions")
CACHE_DIR = os.path.join(SHARED_DIR, "cache")
LOG_DIR = os.path.join(SHARED_DIR, "logs")
AREA_MAP_FILE = os.path.join(CACHE_DIR, "area_map.txt")

WORK_DIR = os.environ.get("BRUH_ASSIST_WORKDIR", "/config")

MAX_TURNS = os.environ.get("BRUH_ASSIST_MAX_TURNS", "5")
DEFAULT_TIMEOUT = int(os.environ.get("BRUH_ASSIST_TIMEOUT", "105"))
TIMEOUT_MARGIN = 15
LIMIT_FLOOR = int(os.environ.get("BRUH_ASSIST_LIMIT_FLOOR", "30"))

POLL_INTERVAL = float(os.environ.get("BRUH_ASSIST_POLL", "0.15"))
MAX_WORKERS = int(os.environ.get("BRUH_ASSIST_POOL_SIZE", "3"))
WORKER_IDLE_REAP = int(os.environ.get("BRUH_ASSIST_IDLE_REAP", "300"))
WORKER_MAX_AGE = int(os.environ.get("BRUH_ASSIST_MAX_AGE", "1800"))
SPARE_RECYCLE = int(os.environ.get("BRUH_ASSIST_SPARE_RECYCLE", "600"))

AREA_MAP_TTL = 300
AREA_MAP_MAX_BYTES = 16000

# Last-used agent profile (custom prompt + model), persisted so the spare
# can be pre-warmed right at startup instead of after the first request.
LAST_PROFILE_FILE = os.path.join(CACHE_DIR, "last_profile.json")

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
TEMPLATE_API = os.environ.get(
    "BRUH_TEMPLATE_API", "http://supervisor/core/api/template"
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

# Mirrors the base system prompt in assist-listener.sh. Keep in sync.
BASE_SYSTEM_PROMPT = """You are a Home Assistant voice assistant. You have FULL authorization to control all devices — never ask for permission or confirmation. Act immediately, then confirm what you did.
This is a VOICE interface: replies are spoken aloud, so answer in 1-2 short sentences unless the user explicitly asks for detail or a document.
Use your MCP tools (control_light, control_climate, control_media_player, control_cover, control_fan, control_switch, control_lock, control_alarm, control_vacuum, call_service, get_all_states, get_areas, activate_scene, run_script, send_notification, get_service_details).
For questions about the PAST ('how cold did it get last night', 'when did the garage open'), use get_history (recent detail) or get_statistics (daily min/max/mean over weeks).
To CHECK A CAMERA or visually verify something, use get_camera_snapshot and describe what you see."""

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
    """Append to the same daily debug log the classic listener uses."""
    path = os.path.join(LOG_DIR, f"assist-{time.strftime('%Y%m%d')}.log")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(path, "a") as fh:
            for line in lines:
                fh.write(line.replace("{ts}", stamp) + "\n")
    except OSError:
        pass


def resolve_claude_cmd() -> list[str]:
    """Resolve how to invoke claude, matching the listeners' logic."""
    override = os.environ.get("BRUH_CLAUDE_BIN", "")
    if override:
        return shlex.split(override)
    if os.access("/usr/local/bin/claude-run", os.X_OK):
        return ["/usr/local/bin/claude-run"]
    if os.geteuid() == 0:
        return ["su-exec", "claude", "/root/.local/bin/claude"]
    return ["claude"]


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


def build_system_prompt(custom: str) -> str:
    prompt = BASE_SYSTEM_PROMPT
    area_map = get_area_map()
    if area_map.strip():
        prompt += MAP_PROMPT.format(area_map=area_map.rstrip())
    else:
        prompt += NO_MAP_PROMPT
    if custom:
        prompt = f"{custom}\n\n{prompt}"
    return prompt


def save_last_profile(custom: str, model: str) -> None:
    """Remember the agent profile so the next pool start pre-warms with it."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = LAST_PROFILE_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"system_prompt": custom, "model": model}, fh)
        os.replace(tmp, LAST_PROFILE_FILE)
    except OSError:
        pass


def prewarm_spare(pool: "Pool") -> None:
    """Spawn the spare at startup from the last-used agent profile, so even
    the first voice command after an add-on restart skips the cold start."""
    custom, model = "", "default"
    try:
        with open(LAST_PROFILE_FILE) as fh:
            data = json.load(fh)
        custom = data.get("system_prompt") or ""
        model = data.get("model") or "default"
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    pool._spawn_spare((build_system_prompt(custom), model))


# ---------------------------------------------------------------------------
# Worker: one live `claude` stream-json process
# ---------------------------------------------------------------------------


class Worker:
    def __init__(self, profile: tuple[str, str], resume: str | None = None):
        self.profile = profile  # (system_prompt, model)
        self.created = time.time()
        self.last_used = self.created
        self.session_id: str | None = None
        self.lock = threading.Lock()  # serializes turns on this worker
        self._events: Queue = Queue()

        system_prompt, model = profile
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
        if model and model != "default":
            cmd += ["--model", model]
        if resume:
            cmd += ["--resume", resume]
            self.session_id = resume

        self.proc = subprocess.Popen(
            cmd,
            cwd=WORK_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
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

    def ask(self, text: str, deadline: float) -> str | None:
        """Send one user message, wait for its result event."""
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
            if etype == "result":
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
                return worker, "warm"
            if worker:
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

    def _drop_worker(self, conv_id: str, worker: Worker) -> None:
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
                    worker.kill()
                    self.workers.pop(conv_id, None)
            # Enforce the cap (LRU), keeping the most recently used.
            while len(self.workers) > MAX_WORKERS - 1:
                oldest = min(self.workers, key=lambda c: self.workers[c].last_used)
                self.workers.pop(oldest).kill()
            # Recycle a stale spare so its baked-in area map stays fresh.
            if self.spare is not None and (
                not self.spare.alive() or now - self.spare.created > SPARE_RECYCLE
            ):
                profile = self.spare.profile
                self.spare.kill()
                self.spare = None
                self._spawn_spare(profile)

    # -- request handling -----------------------------------------------------

    def handle(self, req: dict) -> None:
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
        system_prompt = build_system_prompt(custom_prompt)
        profile = (system_prompt, model)
        save_last_profile(custom_prompt, model)

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
                message = text
                # A truly fresh session can't see earlier turns — replay the
                # transcript the integration sends (like the classic listener).
                if mode == "cold" and req.get("conversation_history"):
                    lines = [
                        f"{m.get('role', '?').upper()}: {m.get('content', '')}"
                        for m in req["conversation_history"]
                    ]
                    message = (
                        "Previous conversation:\n" + "\n".join(lines)
                        + f"\n\nUSER: {text}"
                    )

                with worker.lock:
                    response = worker.ask(message, deadline)
                if response is not None:
                    worker.last_used = time.time()
                    self._store_session(conv_id, worker.session_id)
                else:
                    # Worker hung, died, or errored — drop it and fall back
                    # to a one-shot invocation within the remaining budget.
                    self._drop_worker(conv_id, worker)
                    mode += "+fallback"
                    response = self._oneshot(req, system_prompt, model, deadline)
            except Exception as exc:  # noqa: BLE001 — never drop a request
                log(f"worker path failed for {req_id}: {exc}")
                mode = "error+fallback"
                response = self._oneshot(req, system_prompt, model, deadline)

        duration = time.time() - start
        if response is None:
            if time.time() >= deadline:
                response = (
                    f"Claude timed out after {int(duration)}s. This may be "
                    "caused by a broken MCP server connection. Try restarting "
                    "the BRUH Claude Terminal add-on."
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
        write_response(req_id, response)

    @staticmethod
    def _oneshot(
        req: dict, system_prompt: str, model: str, deadline: float
    ) -> str | None:
        """Classic spawn-per-request fallback — identical to the bash path."""
        remaining = int(deadline - time.time())
        if remaining < 10:
            return None
        text = req["text"]
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
        ]
        if model and model != "default":
            cmd += ["--model", model]
        try:
            proc = subprocess.run(
                cmd,
                input=text,
                capture_output=True,
                text=True,
                timeout=remaining,
                cwd=WORK_DIR,
            )
            return proc.stdout.strip() or None
        except (subprocess.TimeoutExpired, OSError):
            return None


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


def main() -> None:
    for d in (REQUESTS_DIR, RESPONSES_DIR, SESSIONS_DIR, CACHE_DIR, LOG_DIR):
        os.makedirs(d, exist_ok=True)

    log(
        f"starting (poll={POLL_INTERVAL}s, max_workers={MAX_WORKERS}, "
        f"max_turns={MAX_TURNS}, default_timeout={DEFAULT_TIMEOUT}s)"
    )
    # Refresh the map synchronously first so the pre-warmed spare bakes in
    # the same map the first request will build — otherwise their system
    # prompts differ and the spare is never adopted.
    refresh_area_map()
    cleanup_stale_files()

    pool = Pool()
    prewarm_spare(pool)
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

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
