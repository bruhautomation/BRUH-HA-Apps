"""Claude Code's own conversation store, read from the outside.

The chat terminal and the classic terminal are two front ends onto one
Claude Code. What makes them genuinely interchangeable rather than merely
adjacent is this file: Claude Code writes every conversation to
``~/.claude/projects/<escaped working directory>/<session id>.jsonl``, in
the same message shapes it streams, so the panel can

  * list the conversations that exist — whichever face started them, and
  * replay one into the chat pane, so switching over shows the conversation
    instead of an empty box with a promise attached.

We never EDIT anything in this directory. It belongs to the CLI: the CLI
decides what a conversation is, when it is written and when it is pruned,
and a panel that started editing those files would be a second writer to
the one thing that must have exactly one. The single mutation offered is
``delete`` — a person removing a whole conversation on purpose — and it is
a *move* into a trash directory of ours, never a write into a file: the
CLI treats a missing session like one it pruned itself, and the move is
what makes the toast's Undo honest rather than hopeful.

Two things here are inference rather than contract, and both fail soft:

* **The directory name.** It is the working directory with every character
  outside ``[A-Za-z0-9]`` replaced by ``-``. Derived, not published — so if
  the computed name does not exist we go looking for a directory whose
  sessions say they ran in the right place, and if that fails too the
  listing is simply empty.
* **Which entry is the title.** The first genuine user message. The file
  also carries interruptions, tool results and injected notices as
  ``user`` entries, so those are filtered; a conversation whose title
  cannot be found is listed by its id rather than dropped.

*Who started it* is deliberately neither: the CLI does not record it, and
reading it back out of the prompt text would be inference that breaks the
day somebody rewords a prompt. It comes from ``run_sources`` instead, where
every background caller claims its own session id before running.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

import run_sources

# Where the CLI keeps its state. Same env var the add-on exports for every
# other Claude path, with the CLI's own default behind it.
CONFIG_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
    os.environ.get("BRAIN_HOME", "/data/home"), ".claude")

MAX_TITLE_CHARS = 120
# How far into a transcript to look for the first real user message before
# giving up. Some conversations open with a long injected context block.
TITLE_SCAN_LINES = 400
# A replayed conversation is a scrollback, not the context — the CLI still
# holds the whole thing. Newest N events, so a month-long session opens
# instantly instead of pushing 10 MB into a browser.
REPLAY_EVENTS = 400
# What a conversation IS: the things a person said and the things Claude said
# back. Tool calls are how it got there, and on a working session there are
# roughly ten of them for every sentence — see _budget.
SPEECH = ("user", "text", "thinking")
# How far back to read before budgeting. Bounded so a 10 MB transcript can't
# be held in memory whole on a Pi; comfortably more than REPLAY_EVENTS can
# spend, so the budget is what decides what you see, not this.
MAX_SCAN_EVENTS = 5000
MAX_TEXT = 4000
# How many sessions a filtered listing will look at before giving up. Only
# reached when the filter is rejecting nearly everything, which is exactly
# the case that must stay bounded.
MAX_FILTER_SCAN = 400

# Entries that are user-shaped but are not something a person typed.
_NOT_A_PROMPT = (
    "[Request interrupted",
    "<system-reminder>",
    "Caveat: The messages below",
    "<command-name>",
    "<local-command-stdout>",
)


def _escape(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def project_dir(cwd: str) -> Path | None:
    """The directory Claude Code files this working directory's chats in.

    The name is derived, so it is checked rather than trusted: if it is not
    there, fall back to asking the transcripts themselves which directory
    they ran in. That costs one line read per project and only happens when
    the derived name is wrong.
    """
    root = Path(CONFIG_DIR) / "projects"
    guess = root / _escape(cwd)
    if guess.is_dir():
        return guess
    if not root.is_dir():
        return None
    try:
        candidates = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime,
                            reverse=True)
    except OSError:
        return None
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        for entry in _iter_sessions(candidate):
            first = _first_line(entry)
            if first and first.get("cwd") == cwd:
                return candidate
            break   # one session per project is enough to identify it
    return None


def _iter_sessions(directory: Path):
    try:
        return sorted(directory.glob("*.jsonl"),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []


def _first_line(path: Path) -> dict | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip():
                    return json.loads(line)
    except (OSError, ValueError):
        return None
    return None


def _message_text(entry: dict) -> str:
    """The text of a user/assistant entry, or "" if it carries none."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        block.get("text", "") for block in content
        if isinstance(block, dict) and block.get("type") == "text")


def _is_prompt(entry: dict) -> bool:
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return False
    text = _message_text(entry).strip()
    if not text:
        return False
    return not text.startswith(_NOT_A_PROMPT)


def title_of(path: Path) -> str:
    """The conversation's first genuine user message, as a one-line title."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for count, line in enumerate(fh):
                if count > TITLE_SCAN_LINES:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if _is_prompt(entry):
                    text = " ".join(_message_text(entry).split())
                    return text[:MAX_TITLE_CHARS]
    except OSError:
        # A transcript that cannot be read has no title to offer.
        pass
    return ""


def listing(cwd: str, limit: int = 30, exclude: str | None = None,
            sources: tuple[str, ...] | None = None) -> list[dict]:
    """Recent conversations for this working directory, newest first.

    Each row carries the face that started it (``source``). Everything the
    add-on runs by itself claims its session id up front (run_sources), so
    an unclaimed id means a person typed it — which is why ``"you"`` is the
    default rather than something guessed from the opening message.

    ``sources`` keeps only those faces. Filtering here rather than in the
    panel is what makes ``limit`` mean "this many rows you asked for": a
    house whose voice assistant makes a session per command would otherwise
    spend a whole page of 30 on machine chats and hand back four of yours.
    """
    directory = project_dir(cwd)
    if directory is None:
        return []
    wanted = set(sources) if sources else None
    rows = []
    scanned = 0
    for path in _iter_sessions(directory):
        session_id = path.stem
        if exclude and session_id == exclude:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        # A file with nothing in it is a session that was opened and never
        # used; offering it as something to resume is a dead end.
        if stat.st_size < 200:
            continue
        rows.append({"id": session_id, "path": path, "modified": stat.st_mtime})
        scanned += 1
        # Bounded even when the filter matches nothing: a directory of ten
        # thousand voice sessions must not turn one listing into ten
        # thousand title reads.
        if len(rows) >= (limit if wanted is None else MAX_FILTER_SCAN):
            break
    claimed = run_sources.lookup(row["id"] for row in rows)   # one read, not one per row
    out = []
    for row in rows:
        source = claimed.get(row["id"], "you")
        if wanted is not None and source not in wanted:
            continue
        out.append({
            "id": row["id"],
            "title": title_of(row["path"]) or "(no opening message)",
            "modified": row["modified"],
            "age": _age(row["modified"]),
            "source": source,
        })
        if len(out) >= limit:
            break
    return out


def source_counts(cwd: str, limit: int = 200) -> dict[str, int]:
    """How many recent conversations belong to each face.

    Deliberately not ``listing()``: a count needs the id and nothing else,
    and listing reads up to 400 lines of every transcript to find its
    title. Paying for two hundred title scans to draw a number on a chip
    is how a filter row becomes the most expensive thing on the tab.
    """
    directory = project_dir(cwd)
    if directory is None:
        return {}
    ids = []
    for path in _iter_sessions(directory):
        try:
            if path.stat().st_size < 200:
                continue
        except OSError:
            continue
        ids.append(path.stem)
        if len(ids) >= limit:
            break
    claimed = run_sources.lookup(ids)
    counts: dict[str, int] = {}
    for session_id in ids:
        key = claimed.get(session_id, "you")
        counts[key] = counts.get(key, 0) + 1
    return counts


# Where a deleted conversation waits out the toast. On /data with the rest
# of our state, so the move stays on one filesystem in the shipped layout —
# and shutil.move copes if a custom CLAUDE_CONFIG_DIR puts it on another.
TRASH_DIR = os.environ.get("BRAIN_CHAT_TRASH", "/data/chat-trash")
# Comfortably past the undo token's TTL, and a cap besides: the trash is a
# grace period, not an archive, and an archive is exactly what the delete
# button promises not to quietly keep.
TRASH_TTL_S = 30 * 60
TRASH_MAX = 40

_SESSION_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")


def delete(cwd: str, session_id: str) -> dict | None:
    """Move one conversation out of Claude Code's store.

    Returns {"id", "path", "trash"} — enough for ``restore_deleted`` to put
    it back — or None when there is nothing under that id. The id is
    validated the same way ``transcript`` validates it, because it becomes
    a path either way.
    """
    if not _SESSION_ID_RE.fullmatch(session_id or ""):
        return None
    directory = project_dir(cwd)
    if directory is None:
        return None
    path = directory / f"{session_id}.jsonl"
    if not path.is_file():
        return None
    trash = Path(TRASH_DIR)
    try:
        trash.mkdir(parents=True, exist_ok=True)
        _prune_trash(trash)
        target = trash / f"{session_id}.jsonl"
        shutil.move(str(path), str(target))
    except OSError:
        return None
    return {"id": session_id, "path": str(path), "trash": str(target)}


def restore_deleted(entry: dict) -> bool:
    """Put a deleted conversation back where it came from.

    Refuses over an occupied path rather than overwriting: session ids are
    UUIDs, so a file already there means something else went badly wrong,
    and losing it to an Undo would compound the mistake.
    """
    src = Path(str(entry.get("trash") or ""))
    dst = Path(str(entry.get("path") or ""))
    if not src.is_file() or not dst.name or dst.exists():
        return False
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except OSError:
        return False
    return True


def _prune_trash(trash: Path) -> None:
    """Expired entries out, and the oldest beyond the cap with them."""
    try:
        entries = sorted(trash.glob("*.jsonl"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    now = time.time()
    for i, path in enumerate(entries):
        try:
            if i >= TRASH_MAX - 1 or path.stat().st_mtime + TRASH_TTL_S < now:
                path.unlink()
        except OSError:
            # A file another prune got to first needs nothing more done.
            pass


def _age(when: float) -> str:
    secs = max(0.0, time.time() - when)
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{round(secs / 60)} min ago"
    if secs < 86400:
        return f"{round(secs / 3600)} h ago"
    return f"{round(secs / 86400)} d ago"


def transcript(cwd: str, session_id: str, limit: int = REPLAY_EVENTS) -> list[dict]:
    """One conversation, in the chat pane's own event shapes.

    This is what turns "switch to chat" from a promise into the
    conversation: the CLI's stored messages are the same shapes it streams,
    so they render through exactly the same code path as a live turn.
    """
    directory = project_dir(cwd)
    if directory is None:
        return []
    # Session ids are UUIDs and this becomes a path — refuse anything that
    # could climb out of the directory rather than sanitising it.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", session_id or ""):
        return []
    path = directory / f"{session_id}.jsonl"
    if not path.is_file():
        return []
    events: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                events.extend(_replay(entry))
                if len(events) > MAX_SCAN_EVENTS * 2:
                    del events[:len(events) - MAX_SCAN_EVENTS]
    except OSError:
        return []
    return _budget(events, limit)


def _budget(events: list[dict], limit: int = REPLAY_EVENTS) -> list[dict]:
    """The newest ``limit`` events, spent on the conversation first.

    A flat "newest N" looks obviously right and is badly wrong on a real
    session. Measured against an actual transcript: 1844 events, of which
    1701 were tool calls and their results — 92%. The 400-event window
    carried **3 of the 17 things the person had said**, and 24 of 126
    replies. Switching faces showed you the last few minutes of tool chatter
    and almost none of the conversation, which reads exactly like "it didn't
    all come over", because it hadn't.

    So speech is kept first — it is the conversation, and it is small — and
    whatever budget is left buys the most recent tool calls.
    """
    if len(events) <= limit:
        return events
    speech = [i for i, e in enumerate(events) if e["type"] in SPEECH]
    keep = set(speech[-limit:])
    room = limit - len(keep)
    if room > 0:
        rest = [i for i in range(len(events)) if i not in keep]
        keep.update(rest[-room:])
    return _pair_up([e for i, e in enumerate(events) if i in keep])


def _pair_up(events: list[dict]) -> list[dict]:
    """A tool call and its result, or neither.

    Trimming by count cuts wherever the budget runs out, which lands between
    a call and its result often enough to matter. Half a pair is not a
    smaller version of the whole: a call with no result renders as a spinner
    that never stops, and a result with no call renders as nothing at all
    while still costing a slot.
    """
    done = {e.get("id") for e in events if e["type"] == "tool_result"}
    called = {e.get("id") for e in events if e["type"] == "tool"}
    return [e for e in events
            if not (e["type"] == "tool" and e.get("id") not in done)
            and not (e["type"] == "tool_result" and e.get("id") not in called)]


def _replay(entry: dict) -> list[dict]:
    """One stored entry → zero or more chat events.

    Deliberately close to ``chat_session._normalise`` but not shared with
    it: that one reads a live stream, where a ``user`` event is always a
    tool result coming back. Here a ``user`` entry is usually a person
    talking, and telling the two apart is the whole job.
    """
    if entry.get("isSidechain") or entry.get("isMeta"):
        return []
    etype = entry.get("type")

    if etype == "user":
        content = (entry.get("message") or {}).get("content")
        blocks = content if isinstance(content, list) else []
        results = [b for b in blocks
                   if isinstance(b, dict) and b.get("type") == "tool_result"]
        if results:
            out = []
            for block in results:
                inner = block.get("content")
                if isinstance(inner, list):
                    text = "\n".join(
                        part.get("text", "") for part in inner
                        if isinstance(part, dict) and part.get("type") == "text")
                else:
                    text = inner if isinstance(inner, str) else ""
                out.append({
                    "type": "tool_result",
                    "id": block.get("tool_use_id") or "",
                    "ok": not block.get("is_error"),
                    "text": _clip(text),
                })
            return out
        if _is_prompt(entry):
            return [{"type": "user", "text": _clip(_message_text(entry))}]
        return []

    if etype == "assistant":
        out = []
        for block in (entry.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                out.append({"type": "text", "text": _clip(block["text"])})
            elif kind == "thinking" and block.get("thinking"):
                out.append({"type": "thinking", "text": _clip(block["thinking"])})
            elif kind == "tool_use":
                args = block.get("input") if isinstance(block.get("input"), dict) else {}
                out.append({
                    "type": "tool",
                    "id": block.get("id") or "",
                    "name": block.get("name") or "tool",
                    "summary": _tool_summary(args),
                    "input": _clip(json.dumps(args, ensure_ascii=False, indent=2)),
                })
        return out

    return []


def _clip(text: str) -> str:
    text = str(text or "")
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n… (truncated)"


def _tool_summary(args: dict) -> str:
    # Same idea as chat_session.tool_summary, kept here so this module can be
    # read (and tested) without importing the live-session machinery.
    for key in ("file_path", "path", "pattern", "command", "url", "query",
                "entity_id", "prompt", "description", "notebook_path"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:200]
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return value.strip().splitlines()[0][:200]
    return ""
