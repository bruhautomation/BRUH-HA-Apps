"""The memory extractions the Stop hook could not start itself.

`scripts/brain-memory-extract.py` is a Stop hook: it runs as the `claude`
user under the CLI, and its pass is one more `claude -p`. Claude Code hands
a hook every variable but the two a credential travels in, so the hook read
them off the CLI's own /proc/<pid>/environ — and on an AppArmor host that
read is refused (brAIn's profile grants `ptrace (trace,read)` and not
`readby`, and the kernel asks the tracee's profile too). The pass then ran
with no credential, fell through to the CLI's own .credentials.json and was
refused: `memory_extract` ended `auth` on every run while every chat, card
and Resident look worked (reports #81).

The one process that holds the credential every other run is handed is the
panel, and the store it reads (/data/secrets) is root's and stays that way.
So the hook leaves a request here and the panel's scheduler tick runs the
pass: the same script, the same `--extract` half, as the `claude` user,
with the environment `engine._claude_env` builds for every run.

Rules, each about what crosses from a process running as `claude` into one
running as root.

- **A request carries no credential and no command.** Three fields: a
  session id (refused unless it is shaped like one), a transcript path (an
  absolute path to a regular file) and a cwd. The child runs as `claude`,
  so it can read nothing a `claude` process could not read already.
- **Taken once.** A request is deleted before its pass starts; a pass that
  fails is a journal row, never a retry loop.
- **Bounded.** At most `MAX_PER_TICK` passes a tick and `MAX_PER_DAY` a
  day, one per conversation per tick (the latest request wins: it read
  the most), and a request older than `MAX_AGE_S` is dropped unread — a
  panel that was down for a day owes nobody a day's backlog of runs.
- **Never raises.** It is called from the scheduler tick.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("brain.extract_requests")

# Spelled the same in the hook (tests/test_memory_extract.py holds both).
REQUEST_DIR = Path(os.environ.get(
    "BRAIN_EXTRACT_REQUEST_DIR", "/data/.brain/memory-extract-requests"))
SCRIPT = os.environ.get("BRAIN_MEMORY_EXTRACT_SCRIPT",
                        "/opt/scripts/brain-memory-extract.py")

MAX_PER_TICK = 4
MAX_PER_DAY = 120
MAX_AGE_S = 3600
MAX_FILES = 200
MAX_PATH_CHARS = 1024
MAX_REQUEST_BYTES = 8192

_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")

STATE: dict = {"day": "", "started": 0, "last_started_at": None,
               "dropped": 0, "last_error": ""}


def _clean(obj) -> dict | None:
    """A request's three fields, or None for anything else."""
    if not isinstance(obj, dict):
        return None
    sid = obj.get("session_id")
    transcript = obj.get("transcript")
    cwd = obj.get("cwd") or ""
    if not isinstance(sid, str) or not _ID_RE.fullmatch(sid) \
            or sid in (".", ".."):
        return None
    if not isinstance(transcript, str) or not transcript \
            or len(transcript) > MAX_PATH_CHARS \
            or not os.path.isabs(transcript):
        return None
    if not isinstance(cwd, str):
        cwd = ""
    try:
        ts = int(obj.get("ts") or 0)
    except (TypeError, ValueError):
        ts = 0
    return {"session_id": sid, "transcript": transcript,
            "cwd": cwd[:MAX_PATH_CHARS], "ts": ts}


def take(directory: Path | None = None, now: float | None = None) -> list[dict]:
    """Every waiting request, read and deleted, oldest first, one per
    conversation (the newest), stale and malformed ones dropped."""
    directory = Path(directory or REQUEST_DIR)
    now = time.time() if now is None else now
    try:
        files = sorted(p for p in directory.glob("*.json") if p.is_file())
    except OSError:
        return []
    by_session: dict[str, dict] = {}
    for path in files[:MAX_FILES]:
        try:
            if path.stat().st_size > MAX_REQUEST_BYTES:
                raise ValueError("too large")
            request = _clean(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            request = None
        try:
            path.unlink()
        except OSError:
            # Not deleted is not taken: the next tick would run it twice.
            continue
        if request is None or (request["ts"] and now - request["ts"] > MAX_AGE_S):
            STATE["dropped"] += 1
            continue
        if not os.path.isfile(request["transcript"]):
            STATE["dropped"] += 1
            continue
        by_session.pop(request["session_id"], None)
        by_session[request["session_id"]] = request
    return list(by_session.values())


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def drain(env: dict, prefix: list[str], script: str | None = None,
          directory: Path | None = None, now: float | None = None) -> int:
    """Start the pass for each waiting request; how many were started.

    ``env`` is the environment a Claude run is handed (the caller builds it
    with ``engine._claude_env``, so the credential is ``get_auth``'s) and
    ``prefix`` is how this process drops to the `claude` user. The child is
    detached exactly as the hook detaches its own: the scheduler tick does
    not wait on a model.
    """
    try:
        now = time.time() if now is None else now
        if STATE["day"] != _day(now):
            STATE.update(day=_day(now), started=0)
        requests = take(directory, now)
        started = 0
        for request in requests:
            if started >= MAX_PER_TICK or STATE["started"] >= MAX_PER_DAY:
                STATE["dropped"] += 1
                continue
            argv = list(prefix) + [
                sys.executable, script or SCRIPT, "--extract",
                request["session_id"], request["transcript"], request["cwd"]]
            try:
                subprocess.Popen(
                    argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, start_new_session=True,
                    close_fds=True, env=env)
            except (OSError, ValueError) as exc:
                STATE["last_error"] = str(exc)[:200]
                log.warning("could not start a memory extraction: %s", exc)
                continue
            started += 1
            STATE["started"] += 1
            STATE["last_started_at"] = int(now)
        return started
    except Exception as exc:  # noqa: BLE001 — called from the scheduler tick
        STATE["last_error"] = str(exc)[:200]
        log.debug("memory extraction requests failed: %s", exc)
        return 0
