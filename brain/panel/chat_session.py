"""The chat terminal: one long-lived Claude Code session, as events.

The classic terminal is xterm over ttyd over tmux — a character grid, which
is the wrong medium for a phone. A grid cannot reflow, so at ~40 columns a
sentence breaks mid-word and a tool call spends twenty lines saying what a
chip could say in one. This module is the other half of the answer: the same
Claude Code, driven headlessly in ``stream-json`` mode, with its output
turned into a small list of typed events the panel can render as real DOM.

What it is NOT: a second brain. It is the same CLI, the same credential, the
same ``/config`` working directory and therefore the same
``/config/.claude/settings.local.json`` permissions as the Assist listener,
the Automation listener and the Findings fixer. There is one answer to "what
may Claude do here", not two.

Design notes worth keeping:

* **One session, not a pool.** The chat tab is a place, like the terminal
  tab is a place. Two people opening the panel are looking at the same
  conversation, the same way they would be looking at the same tmux.

* **The transcript is ours, not the CLI's.** Claude Code owns the real
  conversation (and resumes it by ``session_id``); we keep a normalised,
  capped copy so a reload can repaint the screen without asking the model
  anything. Losing it costs a scrollback, never context.

* **Events are normalised at the boundary.** The CLI's stream-json shape is
  a moving target across versions; everything that knows about
  ``message.content[].type`` lives in ``_normalise`` and nothing downstream
  does. An event we do not recognise is dropped rather than rendered raw.

* **Stopping is two-stage.** A ``control_request`` interrupt is the polite
  way and is what a recent CLI supports; if the turn has not ended shortly
  after, the process is killed and respawned with ``--resume``. The context
  survives either way, because the CLI wrote it down.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import engine

# Where the chat runs. /config so the project's settings.local.json (the
# permission set) and CLAUDE.md (the description of this house) both apply —
# the same working directory the listeners use.
WORK_DIR = os.environ.get("BRAIN_CHAT_WORKDIR", "/config")

# The transcript we keep for repainting a reloaded page. Capped hard: this
# is a scrollback, and an unbounded one in a long-lived process is a leak
# with a friendly name.
TRANSCRIPT_FILE = os.environ.get(
    "BRAIN_CHAT_TRANSCRIPT", "/data/chat_transcript.json")
MAX_EVENTS = 600

# A single tool result can be a whole file. The panel shows a preview and
# offers the rest on request, so what we keep is bounded too.
MAX_RESULT_CHARS = 4000
MAX_TEXT_CHARS = 60000

# In stream-json mode the turn cap spans the life of the process rather than
# one exchange, so it is a runaway guard, not a per-answer budget.
MAX_TURNS = int(os.environ.get("BRAIN_CHAT_MAX_TURNS", "400"))

# How long to wait for a polite interrupt before killing the process.
INTERRUPT_GRACE = 5.0

# Tool calls whose "arguments" are really the interesting content, so the
# chip shows that rather than a JSON blob.
_TOOL_SUMMARY_KEYS = (
    "file_path", "path", "pattern", "command", "url", "query",
    "entity_id", "prompt", "description", "notebook_path",
)


def _clip(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[:limit] + "\n… (truncated)"


def tool_summary(name: str, args: dict) -> str:
    """One line describing a tool call, for the collapsed chip.

    The first recognised argument wins, because tool calls are overwhelmingly
    "do this thing to that one named object" — and the name of the object is
    the only part a reader scanning the transcript is looking for.
    """
    if not isinstance(args, dict):
        return ""
    for key in _TOOL_SUMMARY_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return _clip(value.strip().splitlines()[0], 200)
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return _clip(value.strip().splitlines()[0], 200)
    return ""


class ChatSession:
    """One live ``claude`` process, plus the transcript of what it said."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.session_id: str | None = None
        # Set by the server from the same effective-model resolution every
        # other Claude path uses; kept as a plain attribute rather than an
        # import so this module never depends on the web layer.
        self.model = os.environ.get("BRAIN_MODEL", "")
        self.events: list[dict] = []
        self.state = "idle"          # idle | starting | ready | busy | error
        self.error = ""
        self._subs: set[asyncio.Queue] = set()
        self._seq = 0
        self._lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._busy_since = 0.0
        self._load()

    # -- transcript ------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(Path(TRANSCRIPT_FILE).read_text("utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            events = data.get("events")
            if isinstance(events, list):
                self.events = [e for e in events if isinstance(e, dict)][-MAX_EVENTS:]
                self._seq = max((e.get("seq") or 0) for e in self.events) if self.events else 0
            if isinstance(data.get("session_id"), str):
                self.session_id = data["session_id"]

    def _persist(self) -> None:
        path = Path(TRANSCRIPT_FILE)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(
                {"session_id": self.session_id, "events": self.events},
                ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass  # a lost scrollback is not worth failing a turn over

    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "events": self.events,
            "state": self.state,
            "error": self.error,
            "session_id": self.session_id,
        }

    # -- subscribers -----------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        # Bounded: a browser tab that stopped reading (a suspended phone,
        # usually) must not grow a queue until the add-on runs out of memory.
        # An overflowing subscriber is dropped and reconnects to a snapshot,
        # which is strictly better than losing the process it was watching.
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def _emit(self, event: dict, *, keep: bool = True) -> dict:
        self._seq += 1
        event["seq"] = self._seq
        event.setdefault("ts", time.time())
        if keep:
            self.events.append(event)
            if len(self.events) > MAX_EVENTS:
                del self.events[:len(self.events) - MAX_EVENTS]
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._subs.discard(q)
        return event

    def _set_state(self, state: str, error: str = "") -> None:
        self.state = state
        self.error = error
        # Not kept in the transcript: state is a fact about now, and a
        # replayed "busy" from last Tuesday is a spinner that never stops.
        self._emit({"type": "state", "state": state, "error": error}, keep=False)

    # -- process ---------------------------------------------------------

    def _argv(self) -> list[str]:
        argv = engine._claude_argv() + [
            "-p",
            "--verbose",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--max-turns", str(MAX_TURNS),
        ]
        if self.model:
            argv += ["--model", self.model]
        if self.session_id:
            argv += ["--resume", self.session_id]
        return argv

    def alive(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    async def start(self) -> None:
        """Spawn the CLI, resuming the previous conversation if there is one.

        A resume that fails (the CLI's session store was cleared, or the
        conversation is from an incompatible version) is not fatal: it falls
        back to a fresh session, because a chat tab that refuses to open is
        worse than one that has forgotten last week.
        """
        async with self._lock:
            if self.alive():
                return
            self._set_state("starting")
            try:
                await self._spawn()
            except FileNotFoundError:
                self._set_state("error", "The Claude CLI was not found in this add-on.")
                return
            except OSError as exc:
                self._set_state("error", f"Could not start Claude: {exc}")
                return
            self._set_state("ready")

    async def _spawn(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *self._argv(),
            cwd=WORK_DIR if os.path.isdir(WORK_DIR) else None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=engine._claude_env(),
            limit=1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read_loop(self.proc))

    async def _read_loop(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        try:
            while True:
                try:
                    line = await proc.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    # One oversized line (a tool result bigger than the
                    # stream limit). Skip it rather than tearing down a
                    # working session.
                    continue
                if not line:
                    break
                raw = line.decode("utf-8", "replace").strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                sid = event.get("session_id")
                if isinstance(sid, str) and sid:
                    self.session_id = sid
                for norm in _normalise(event):
                    # Deltas and run stats are live-only: the assistant event
                    # that follows carries the same text as a whole block, so
                    # keeping both would double every answer in the
                    # transcript a reload repaints.
                    self._emit(norm, keep=norm.pop("_keep", True))
                if event.get("type") == "result":
                    self._busy_since = 0.0
                    self._set_state("ready")
                    self._persist()
        finally:
            # Only the *current* process reports; a reader still winding down
            # after stop() must not overwrite the state its replacement set.
            if proc is self.proc:
                was_busy = self.state == "busy"
                self._busy_since = 0.0
                if was_busy:
                    # An exit while the user was waiting is a failed turn and
                    # has to say so, with whatever the CLI put on stderr.
                    detail = ""
                    if proc.stderr is not None:
                        try:
                            raw = await asyncio.wait_for(proc.stderr.read(), 2)
                            detail = raw.decode("utf-8", "replace").strip()[-400:]
                        except (asyncio.TimeoutError, ValueError):
                            pass
                    self._set_state("error", detail or "The Claude session ended.")
                else:
                    # An exit while idle is just a session that ended.
                    self._set_state("idle")
                self._persist()

    # -- turns -----------------------------------------------------------

    async def send(self, text: str) -> dict:
        text = (text or "").strip()
        if not text:
            raise ValueError("empty message")
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError("message too long")
        if not self.alive():
            await self.start()
        if not self.alive():
            raise RuntimeError(self.error or "the Claude session is not running")
        if self.state == "busy":
            raise RuntimeError("Claude is still answering — stop it first")

        self._emit({"type": "user", "text": text})
        self._persist()
        payload = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        }) + "\n"
        assert self.proc is not None and self.proc.stdin is not None
        try:
            self.proc.stdin.write(payload.encode())
            await self.proc.stdin.drain()
        except (OSError, ConnectionResetError) as exc:
            self._set_state("error", f"Could not reach the Claude session: {exc}")
            raise RuntimeError(self.error) from exc
        self._busy_since = time.time()
        self._set_state("busy")
        return {"ok": True}

    async def interrupt(self) -> dict:
        """Politely, then not.

        The control request is what a current CLI answers; older ones ignore
        it silently, which is indistinguishable from "still thinking". So the
        grace period is short and the fallback is unconditional — and because
        the CLI persists the conversation itself, respawning with --resume
        picks it back up where the last completed turn left it.
        """
        if not self.alive():
            return {"ok": True, "method": "none"}
        try:
            assert self.proc is not None and self.proc.stdin is not None
            self.proc.stdin.write((json.dumps({
                "type": "control_request",
                "request_id": f"int-{int(time.time() * 1000)}",
                "request": {"subtype": "interrupt"},
            }) + "\n").encode())
            await self.proc.stdin.drain()
        except (OSError, ConnectionResetError, AssertionError):
            pass
        deadline = time.time() + INTERRUPT_GRACE
        while time.time() < deadline:
            if self.state != "busy":
                return {"ok": True, "method": "interrupt"}
            await asyncio.sleep(0.2)
        await self.stop()
        self._emit({"type": "notice", "text": "Stopped."})
        await self.start()
        return {"ok": True, "method": "restart"}

    async def stop(self) -> None:
        proc, self.proc = self.proc, None
        if self._reader:
            self._reader.cancel()
            self._reader = None
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except (OSError, ProcessLookupError):
                pass
        self._busy_since = 0.0
        self._set_state("idle")

    async def reset(self) -> dict:
        """Start a genuinely new conversation.

        Drops the resume id as well as the transcript — keeping the id would
        make "New chat" mean "same conversation, blank screen", which is the
        one thing it must not mean.
        """
        await self.stop()
        self.session_id = None
        self.events = []
        self._seq = 0
        self._persist()
        self._emit({"type": "cleared"}, keep=False)
        await self.start()
        return {"ok": True}


# ---------------------------------------------------------------------------
# Normalising the CLI's stream into something a browser can render
# ---------------------------------------------------------------------------

def _normalise(event: dict) -> list[dict]:
    """Turn one stream-json event into zero or more transcript events.

    Everything that knows the CLI's wire shape is here. The panel only ever
    sees: text, text_delta, thinking, tool, tool_result, result, notice.
    """
    etype = event.get("type")

    if etype == "stream_event":
        delta = (event.get("event") or {}).get("delta") or {}
        if delta.get("type") == "text_delta" and delta.get("text"):
            # Not kept: the assistant event that follows carries the whole
            # block, so keeping deltas too would double every answer in the
            # transcript a reload repaints.
            return [{"type": "text_delta", "text": delta["text"], "_keep": False}]
        return []

    if etype == "assistant":
        out = []
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and block.get("text"):
                out.append({"type": "text", "text": _clip(block["text"], MAX_RESULT_CHARS * 4)})
            elif btype == "thinking" and block.get("thinking"):
                out.append({"type": "thinking",
                            "text": _clip(block["thinking"], MAX_RESULT_CHARS)})
            elif btype == "tool_use":
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                out.append({
                    "type": "tool",
                    "id": block.get("id") or "",
                    "name": block.get("name") or "tool",
                    "summary": tool_summary(block.get("name") or "", args),
                    "input": _clip(json.dumps(args, ensure_ascii=False, indent=2),
                                   MAX_RESULT_CHARS),
                })
        return out

    if etype == "user":
        # A "user" event coming *from* the CLI is a tool result being fed
        # back, not something the person typed.
        out = []
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            content = block.get("content")
            if isinstance(content, list):
                text = "\n".join(
                    part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text")
            else:
                text = content if isinstance(content, str) else ""
            out.append({
                "type": "tool_result",
                "id": block.get("tool_use_id") or "",
                "ok": not block.get("is_error"),
                "text": _clip(text, MAX_RESULT_CHARS),
            })
        return out

    if etype == "result":
        if event.get("is_error"):
            return [{"type": "notice", "level": "error",
                     "text": _error_text(event)}]
        return [{
            "type": "result",
            "duration_ms": event.get("duration_ms"),
            "cost_usd": event.get("total_cost_usd"),
            "turns": event.get("num_turns"),
            "_keep": False,
        }]

    return []


def _error_text(event: dict) -> str:
    subtype = event.get("subtype") or ""
    if subtype == "error_max_turns":
        return ("Claude reached this session's turn limit. Start a new chat "
                "to carry on.")
    result = event.get("result")
    if isinstance(result, str) and result.strip():
        return _clip(result.strip(), 1000)
    return subtype or "The turn ended with an error."


# One session per add-on, created lazily so importing this module (which the
# tests do) never spawns anything.
_session: ChatSession | None = None


def session() -> ChatSession:
    global _session
    if _session is None:
        _session = ChatSession()
    return _session
