#!/usr/bin/env python3
"""A player's skin through SkinsRestorer, and whether it went on (#760, #762).

SkinsRestorer answers `skin set` only after it has fetched the skin — from
Mojang for a Java player's name, from MineSkin for a picture — seconds after
RCON came back with nothing, and a picture first says "Uploading skin,
please wait…". One second of listening (console_reply's) heard none of it,
so nobody could tell whether a skin had gone on.

So a skin command is listened for until SkinsRestorer's own last word — a
change, a clear, or an error — up to SKIN_WAIT_S; and SkinsRestorer's record
of the player on disk changing is a yes too (its answer to a console
command can go to the RCON sender, which is gone by then, and never reach
the console). Used by the HA bridge's `skin` kind (`set_skin`) and by a
`skin set`/`skin clear` sent through `rcon_command`.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import console_reply  # noqa: E402

SKIN_WAIT_S = 30.0
# What a skin may be: a Java Edition player's name (their skin is used), an
# https link to a picture or a texture, or clear. One token each, so nothing
# else can ride to the console.
_NAME = re.compile(r"^[A-Za-z0-9_]{3,16}$")
_URL = re.compile(r"^https://[A-Za-z0-9.\-]+(?::\d{1,5})?/[A-Za-z0-9._~%/+\-=&?#:@!$,;]{1,300}$")
_PLAYER = re.compile(r"^[A-Za-z0-9_.]{1,17}$")
CLEAR = ("clear", "reset", "default", "none", "own")
# A `skin set`/`skin clear` typed through rcon_command.
COMMAND = re.compile(r"^(?:skinsrestorer:)?skin\s+(?:set\s+\S+|clear)\s+(?P<player>[A-Za-z0-9_.]{1,17})\s*$",
                     re.IGNORECASE)
_PENDING = re.compile(r"please wait|uploading|generating|fetching|downloading", re.IGNORECASE)
_FAILED = re.compile(
    r"error|invalid|could ?n[o']t|unable|failed|not found|no such|does ?n[o']t exist|"
    r"too many|rate.?limit|cooldown|unknown|usage:|<--\[here\]", re.IGNORECASE)
_DONE = re.compile(r"\b(changed|cleared|updated|applied|set)\b", re.IGNORECASE)


def command(skin: Any, player: Any) -> str:
    """SkinsRestorer's console command for one player's skin; ValueError
    with the reason for anything else."""
    skin, player = str(skin or "").strip(), str(player or "").strip()
    if not _PLAYER.match(player):
        raise ValueError("player is one Minecraft name.")
    if skin.lower() in CLEAR:
        return f"skin clear {player}"
    if _NAME.match(skin) or _URL.match(skin):
        return f"skin set {skin} {player}"
    raise ValueError("skin is a Java Edition player's name, an https link to a skin picture "
                     "(a PNG), or clear.")


def verdict(lines: list[str], player: str) -> tuple[Optional[bool], str]:
    """(worked, the line that says so) from SkinsRestorer's console lines;
    (None, "") while it has not said yet."""
    for line in lines:
        low = line.lower()
        if not ("skin" in low or player.lower() in low):
            continue          # another plugin, in the same seconds
        if _FAILED.search(line):
            return False, line
        if _PENDING.search(line):
            continue
        if "skin" in low and _DONE.search(line):
            return True, line
    return None, ""


def record(server_dir: Optional[Path], player: str) -> tuple:
    """SkinsRestorer's record of a player as (mtime, size) per place it may
    be: `players/<uuid>.player` (15.x, the uuid from usercache.json) and
    `Players/<name>.player` (14.x)."""
    if server_dir is None:
        return ()
    root = Path(server_dir) / "plugins" / "SkinsRestorer"
    paths = [root / "Players" / f"{player.lower()}.player"]
    try:
        cache = json.loads((Path(server_dir) / "usercache.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = []
    for row in cache if isinstance(cache, list) else []:
        if isinstance(row, dict) and str(row.get("name", "")).lower() == player.lower():
            paths.append(root / "players" / f"{row.get('uuid')}.player")
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def apply(run: Callable[[str], str], skin: Any, player: Any, log_path: Optional[Path],
          server_dir: Optional[Path], *, cmd: Optional[str] = None, wait: float = SKIN_WAIT_S,
          sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Send the skin command and wait for its answer: {"worked": True,
    False or None (nothing said in time), "reply": SkinsRestorer's words}."""
    cmd = cmd or command(skin, player)
    player = str(player).strip()
    start = console_reply.log_end(log_path)
    before = record(server_dir, player)
    reply = console_reply.plain(run(cmd) or "").strip()
    if reply:
        if _FAILED.search(reply):
            return {"worked": False, "reply": reply}
        worked, line = verdict([reply], player)
        if worked is not None:
            return {"worked": worked, "reply": line}
    deadline = clock() + wait
    lines: list[str] = []
    while True:
        if start is not None:
            lines = console_reply.readable(console_reply.lines_since(Path(log_path), start))
            worked, line = verdict(lines, player)
            if worked is not None:
                return {"worked": worked, "reply": line}
        if before and record(server_dir, player) != before:
            return {"worked": True, "reply": f"SkinsRestorer saved {player}'s new skin."}
        if clock() >= deadline:
            heard = " ".join(ln for ln in lines if "skin" in ln.lower())[:300]
            return {"worked": None, "reply": heard or reply}
        sleep(console_reply.STEP_S)


__all__ = ["SKIN_WAIT_S", "COMMAND", "command", "verdict", "record", "apply"]
