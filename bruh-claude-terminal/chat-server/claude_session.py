"""One Claude Code subprocess per chat session.

Spawns `claude-run -p --input-format stream-json --output-format stream-json
--session-id <uuid> --verbose --include-partial-messages --replay-user-messages`
and exposes async send/receive to the FastAPI WebSocket layer.

Multi-turn invariant: stdin stays open across turns. Each user message goes in
as a single NDJSON line; each stdout line is one event. Closing stdin shuts the
turn loop down gracefully.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

log = logging.getLogger(__name__)

CLAUDE_BIN = os.environ.get("BRUH_CLAUDE_BIN", "/usr/local/bin/claude-run")
DEFAULT_CWD = os.environ.get("BRUH_CHAT_CWD", "/config")


@dataclass
class ClaudeSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cwd: str = DEFAULT_CWD
    model: Optional[str] = None
    permission_mode: str = "acceptEdits"
    _proc: Optional[asyncio.subprocess.Process] = None
    _events: "asyncio.Queue[dict]" = field(default_factory=asyncio.Queue)
    _stderr_buf: list = field(default_factory=list)
    _reader_task: Optional[asyncio.Task] = None
    _stderr_task: Optional[asyncio.Task] = None
    _closed: bool = False

    async def start(self) -> None:
        if self._proc is not None:
            raise RuntimeError("session already started")

        args = [
            CLAUDE_BIN,
            "-p",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--session-id", self.session_id,
            "--verbose",
            "--include-partial-messages",
            "--replay-user-messages",
            "--permission-mode", self.permission_mode,
        ]
        if self.model:
            args.extend(["--model", self.model])

        log.info(
            "claude_session.start session=%s cwd=%s mode=%s",
            self.session_id, self.cwd, self.permission_mode,
        )
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )
        self._reader_task = asyncio.create_task(self._pump_stdout())
        self._stderr_task = asyncio.create_task(self._pump_stderr())

    async def _pump_stdout(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            async for raw in self._proc.stdout:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "raw", "line": line}
                await self._events.put(event)
        except Exception as e:
            log.warning("stdout pump error: %r", e)
        finally:
            await self._events.put({"type": "_eof"})

    async def _pump_stderr(self) -> None:
        """Buffer stderr so we can surface it on failure without spamming logs."""
        assert self._proc and self._proc.stderr
        try:
            async for raw in self._proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                if line:
                    self._stderr_buf.append(line)
                    if len(self._stderr_buf) > 200:
                        self._stderr_buf = self._stderr_buf[-200:]
        except Exception as e:
            log.warning("stderr pump error: %r", e)

    async def send_user_message(self, content: str) -> None:
        if not content:
            return
        if self._proc is None or self._proc.stdin is None or self._proc.stdin.is_closing():
            raise RuntimeError("session not started or stdin closed")
        msg = {"type": "user", "content": content}
        line = (json.dumps(msg) + "\n").encode("utf-8")
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()

    async def events(self) -> AsyncIterator[dict]:
        while True:
            ev = await self._events.get()
            if ev.get("type") == "_eof":
                return
            yield ev

    def interrupt(self) -> None:
        """Send SIGINT to the running turn so Claude stops mid-response."""
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass

    def stderr_tail(self, lines: int = 20) -> list:
        return list(self._stderr_buf[-lines:])

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            log.warning("session %s did not exit; terminating", self.session_id)
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        for t in (self._reader_task, self._stderr_task):
            if t and not t.done():
                t.cancel()
