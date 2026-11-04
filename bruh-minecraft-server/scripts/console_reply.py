#!/usr/bin/env python3
"""A console command's answer, including what a plugin printed instead.

RCON hands back only what a command sends to *its sender*. Vanilla commands
do that; many plugins do not: SkinsRestorer's `skin set` and `sr status`,
Skript's `sk reload`, a data pack `reload`'s failures all write to the
server's console logger and send the RCON sender nothing. So a command typed
through RCON came back as "" whether it worked or not, and a caller could
not tell success from failure.

The server's console is already on disk (`console.log`, the launcher's
copy of stdout, which the panel's live console tails). So the lines the
server writes in the moment after the command are its answer: read from
where the file ended before the command was sent, with the panel's own RCON
chatter and the server's echo of the command left out.

Used by the HA bridge (`rcon_command`) and the panel's console box, and with
`always=True` by the world-scripts writer, which wants Skript's or the data
pack loader's errors even when RCON also said something.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable, Optional

# A log line's prefix: Paper's `[12:34:56 INFO]: `, vanilla's
# `[12:34:56] [Server thread/INFO]: `, Fabric's `[12:34:56] [Server thread/INFO] (Mod): `.
_PREFIX = re.compile(r"^\[[^\]]*\](?:\s*\[[^\]]*\])?(?:\s*\([^)]*\))?:?\s?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_COLOUR = re.compile(r"§.")
# Lines that are the server talking about RCON, not answering the command:
# the connection opening and closing, and the "issued server command" echo
# (Essentials and Paper write one for every console command).
_NOISE = (
    re.compile(r"Thread RCON Client /\S+ (started|shutting down)"),
    re.compile(r"\bissued server command: ", re.IGNORECASE),
    re.compile(r"^\s*$"),
)
# Somebody talking in chat in the same second is not the command's answer.
_CHAT = re.compile(r"^(\[Not Secure\] )?<[^>]{1,40}> ")

WAIT_S = 1.0       # how long a silent command is listened for
SETTLE_S = 0.3     # once lines arrive, this long with nothing new ends it
STEP_S = 0.1


def plain(text: str) -> str:
    """Text without ANSI escapes or `§` colour codes."""
    return _COLOUR.sub("", _ANSI.sub("", str(text or "")))


def readable(raw_lines: list[str]) -> list[str]:
    """The lines a person would read as the answer: prefixes and colour off,
    RCON chatter, the command's echo and chat left out."""
    out: list[str] = []
    for raw in raw_lines:
        line = plain(raw).rstrip()
        text = _PREFIX.sub("", line, count=1) if line.startswith("[") else line
        if any(p.search(text) or p.search(line) for p in _NOISE) or _CHAT.match(text):
            continue
        out.append(text)
    return out


def log_end(path: Optional[Path]) -> Optional[int]:
    """Where the console file ends now, or None when there is none to read."""
    if path is None:
        return None
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def lines_since(path: Path, start: int, limit: int = 65_536) -> list[str]:
    """The whole lines written to `path` after byte `start` (a file that was
    rotated meanwhile is read from its beginning)."""
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, 2)
            if size < start:
                start = 0
            fh.seek(start)
            chunk = fh.read(min(limit, max(0, size - start)))
    except OSError:
        return []
    text = chunk.decode("utf-8", errors="replace")
    if not text.endswith("\n"):
        # A line still being written is read on the next look.
        text = text[: text.rfind("\n") + 1]
    return text.splitlines()


def listen(path: Path, start: int, *, wait: float = WAIT_S, settle: float = SETTLE_S,
           until: Optional[re.Pattern] = None,
           sleep: Callable[[float], None] = time.sleep,
           clock: Callable[[], float] = time.monotonic) -> list[str]:
    """The readable console lines written after `start`, collected until
    `wait` runs out, `settle` passes with nothing new once something came,
    or a line matches `until`."""
    deadline = clock() + wait
    got: list[str] = []
    last_change = clock()
    while True:
        lines = readable(lines_since(path, start))
        now = clock()
        if len(lines) != len(got):
            got, last_change = lines, now
            if until is not None and any(until.search(line) for line in got):
                return got
        if now >= deadline or (got and now - last_change >= settle):
            return got
        sleep(STEP_S)


def command(run: Callable[[str], str], cmd: str, log_path: Optional[Path], *,
            always: bool = False, wait: float = WAIT_S, settle: float = SETTLE_S,
            until: Optional[re.Pattern] = None,
            sleep: Callable[[float], None] = time.sleep,
            clock: Callable[[], float] = time.monotonic) -> str:
    """`run(cmd)`'s reply, or — when it is empty, or `always` — the reply
    with the console lines the server wrote right after it.

    `run` is the RCON call (it raises when the server does not answer, and
    that is left to the caller). A server without a console file answers
    with RCON's reply alone, exactly as before.
    """
    start = log_end(log_path)
    reply = run(cmd)
    reply = "" if reply is None else str(reply)
    if start is None or (plain(reply).strip() and not always):
        return reply
    lines = listen(Path(log_path), start, wait=wait, settle=settle, until=until,
                   sleep=sleep, clock=clock)
    head = [plain(reply).strip()] if plain(reply).strip() else []
    return "\n".join(head + [line for line in lines if line.strip() not in head])
