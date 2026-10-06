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

import datetime as dt
import html
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
# How many sessions an UNFILTERED listing stats and tail-reads before
# sorting. More than the page needs on purpose: the scan is ordered by
# mtime, which the CLI bumps on a mere resume (see _last_activity), so a
# margin keeps a browsed-but-idle conversation from squeezing a genuinely
# newer one out of the scan before the honest sort happens.
LIST_SCAN = 120
# How far into a transcript's tail to look for the newest timestamped entry.
# The untimestamped housekeeping lines at the end are small; the sized ones
# (user/assistant) all carry a timestamp, so this is generous.
TAIL_BYTES = 16384

# Entries that are user-shaped but are not something a person typed.
_NOT_A_PROMPT = (
    "[Request interrupted",
    "<system-reminder>",
    "Caveat: The messages below",
    "<command-name>",
    "<local-command-stdout>",
    "<task-notification>",
)

# User-shaped entries the CLI writes ITSELF, into the person's half of the
# conversation: a background task (a backgrounded shell, a sub-agent)
# finishing, and the reminders it injects. The tag is what says which, and
# nothing else does — such an entry carries no isMeta. Rendered as a bubble
# they read as something the person typed: four kilobytes of raw XML with
# escaped newlines, which is what a walkthrough found in a real chat.
_INJECTED = {
    "<task-notification>": "task",
    "<system-reminder>": "reminder",
}
# A one-line heading, never the body: the row is collapsed and the summary
# is what it says while it is.
MAX_INJECTED_SUMMARY = 200


def _tag(text: str, name: str) -> str:
    match = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
    return match.group(1).strip() if match else ""


def _unescape(text: str) -> str:
    r"""A body as a person would read it.

    The CLI writes these as XML, so ``>=`` arrives as ``&gt;=``; and a body
    that was itself JSON-escaped arrives as one line with a literal ``\n``
    in it. The second is only undone when the text has no real line breaks
    of its own, so a body that merely mentions ``\n`` keeps it.
    """
    text = html.unescape(text)
    if "\\n" in text and "\n" not in text.strip():
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text


def injected_event(text: str) -> dict | None:
    """A CLI-injected user turn as a ``background`` event, or None.

    One classifier for every reader — the live stream (``chat_session.
    _normalise``), this module's replay, and a scrollback the panel saved
    before this existed — because a second copy of "which user turns are
    not the person" is the copy that lets one through. ``None`` means the
    text is not one of these and the caller decides what it is.
    """
    stripped = (text or "").lstrip()
    kind = next((k for tag, k in _INJECTED.items()
                 if stripped.startswith(tag)), None)
    if kind is None:
        return None
    if kind == "task":
        status = _unescape(_tag(stripped, "status"))
        summary = _unescape(_tag(stripped, "summary"))
        body = _tag(stripped, "result")
        if not body:
            # No result block: what follows the notification (the CLI
            # appends where the output can be read) is the body there is.
            body = stripped.split("</task-notification>", 1)[-1].strip()
        heading = summary or ("Background task " + (status or "finished"))
    else:
        status = ""
        body = _tag(stripped, "system-reminder") or stripped
        heading = "Note from Claude Code"
    heading = " ".join(heading.split())
    if len(heading) > MAX_INJECTED_SUMMARY:
        heading = heading[:MAX_INJECTED_SUMMARY - 1] + "…"
    return {"type": "background", "kind": kind, "status": status,
            "summary": heading, "text": _clip(_unescape(body))}


def injected_events(text: str) -> list[dict] | None:
    """What the chat shows for a CLI-injected turn: None if it is not one.

    A finished task is news in the conversation and becomes one collapsed
    row; a reminder is the CLI talking to the model, was never shown, and
    is still not. Either way it is never a bubble.
    """
    event = injected_event(text)
    if event is None:
        return None
    return [event] if event["kind"] == "task" else []


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
    return _first_prompt(path)[:MAX_TITLE_CHARS]


# A machine run opens with the prompt brAIn built, not with anything a
# person typed, so its first message is the worst possible title: every
# card run reads "INSIGHT CATEGORY: …", every asked card "The user asked
# this question about their home — …", and the list of them is a column of
# identical openers cut off before the part that tells them apart. These
# pull out the part that does. Display only — `title_of` stays the literal
# opener, because `adopt_machine_runs` classifies by it.
_CARD_TITLE_RE = re.compile(r"^INSIGHT CATEGORY:\s*(.+?)(?:\s+ANALYSIS FOCUS:|$)")
_QUESTION_RE = re.compile(r"\bQUESTION:\s*(.+?)(?:\s+Choose the most fitting|$)")
_FIXED_TITLES = (
    ("Propose insight cards worth adding", "Ideas for new cards"),
)


def display_title(path: Path) -> str:
    """The title a person should read for a conversation in the list."""
    text = _first_prompt(path)
    m = _CARD_TITLE_RE.match(text)
    if m:
        return m.group(1).strip()[:MAX_TITLE_CHARS]
    if text.startswith("The user asked this question"):
        m = _QUESTION_RE.search(text)
        if m:
            return m.group(1).strip()[:MAX_TITLE_CHARS]
    for prefix, title in _FIXED_TITLES:
        if text.startswith(prefix):
            return title
    return text[:MAX_TITLE_CHARS]


def _first_prompt(path: Path) -> str:
    """The first genuine user message, whitespace folded, uncut."""
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
                    return " ".join(_message_text(entry).split())
    except OSError:
        # A transcript that cannot be read has no title to offer.
        pass
    return ""


def listing(cwd: str, limit: int = 30,
            sources: tuple[str, ...] | None = None,
            default_source: str = "you") -> list[dict]:
    """Recent conversations for this working directory, newest first.

    "Newest" means the newest thing anyone SAID, not the file's mtime: the
    CLI touches a session file the moment it is resumed, before a word is
    exchanged (see ``_last_activity``), so ordering by mtime made merely
    browsing old conversations shuffle them all to the top stamped "just
    now". The scan is still mtime-ordered — a touch only ever moves a file
    *up*, so the newest activity is always inside the top of an mtime scan
    — but what a row reports, and where it sorts, is its last entry's own
    timestamp.

    Each row carries the face that started it (``source``). Everything the
    add-on runs by itself claims its session id up front (run_sources), so
    an unclaimed id means a person typed it — which is why ``"you"`` is the
    default rather than something guessed from the opening message.

    ``sources`` keeps only those faces. Filtering here rather than in the
    panel is what makes ``limit`` mean "this many rows you asked for": a
    house whose voice assistant makes a session per command would otherwise
    spend a whole page of 30 on machine chats and hand back four of yours.

    ``default_source`` is what an unclaimed id means, and it depends on the
    directory: in /config it means a person typed it ("you"), while in the
    engine's directory nothing is anyone's typing — the caller passes ""
    there, and an unclaimed row (the auth self-check, mostly) is dropped
    rather than mislabelled.
    """
    directory = project_dir(cwd)
    if directory is None:
        return []
    wanted = set(sources) if sources else None
    rows = []
    # Bounded even when the filter matches nothing: a directory of ten
    # thousand voice sessions must not turn one listing into ten thousand
    # title reads. Unfiltered still over-scans (LIST_SCAN, not limit) so
    # the activity sort below has room to demote touched-but-idle files.
    scan_cap = MAX_FILTER_SCAN if wanted is not None else LIST_SCAN
    for path in _iter_sessions(directory):
        try:
            stat = path.stat()
        except OSError:
            continue
        # A file with nothing in it is a session that was opened and never
        # used; offering it as something to resume is a dead end.
        if stat.st_size < 200:
            continue
        rows.append({"id": path.stem, "path": path,
                     "modified": _last_activity(path, stat.st_mtime)})
        if len(rows) >= scan_cap:
            break
    rows.sort(key=lambda r: r["modified"], reverse=True)
    claimed = run_sources.lookup(row["id"] for row in rows)   # one read, not one per row
    out = []
    for row in rows:
        source = claimed.get(row["id"], default_source)
        if not source or (wanted is not None and source not in wanted):
            continue
        out.append({
            "id": row["id"],
            "title": display_title(row["path"]) or "(no opening message)",
            "modified": row["modified"],
            "age": _age(row["modified"]),
            "source": source,
        })
        if len(out) >= limit:
            break
    return out


def _last_activity(path: Path, mtime: float) -> float:
    """When something last happened IN a conversation, not to its file.

    Claude Code bumps a session file's mtime the moment it is resumed —
    before any message is exchanged (verified against CLI 2.1.234: spawning
    ``--resume`` and killing it without a turn leaves the size unchanged
    and the mtime fresh). The panel resumes a conversation just to LOOK at
    it, so mtime made the act of browsing rewrite the rail's own ordering.
    The entries themselves are stamped as they are written; the newest
    stamped one is the honest "last activity". The untimestamped lines at
    the tail (``last-prompt``, ``mode``) are housekeeping, skipped.

    Falls back to the mtime when no stamped entry is in the tail window —
    an mtime that may be a touch is still better than no answer at all.
    """
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return mtime
    lines = tail.splitlines()
    if size > TAIL_BYTES and lines:
        lines = lines[1:]           # the first line of a mid-file seek is torn
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            stamp = json.loads(line).get("timestamp")
        except (ValueError, AttributeError):
            continue
        if not isinstance(stamp, str):
            continue
        try:
            return dt.datetime.fromisoformat(
                stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
    return mtime


def source_counts(cwd: str, limit: int = 200,
                  default_source: str = "you") -> dict[str, int]:
    """How many recent conversations belong to each face.

    Deliberately not ``listing()``: a count needs the id and nothing else,
    and listing reads up to 400 lines of every transcript to find its
    title. Paying for two hundred title scans to draw a number on a chip
    is how a filter row becomes the most expensive thing on the tab.

    Same ``default_source`` contract as ``listing``: "" means an unclaimed
    id counts toward nobody.
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
        key = claimed.get(session_id, default_source)
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


# The one-time repair for transcripts written before their callers claimed
# session ids. The claim contract deliberately never infers a source from a
# person's wording — but these are OUR OWN shipped prompts, matched verbatim
# at the opening line: the worker pool's reflection pass, and its one-shot
# voice fallback (whose first genuine message is the local-time prefix, or
# the history-replay wrapper). Nothing a person would ever type opens with
# any of them.
MACHINE_OPENERS = (
    ("From this smart-home voice conversation, extract", "memory"),
    ("(Local time: ", "voice"),
    ("Previous conversation:", "voice"),
)
# Guarded by a marker: once the callers claim for themselves this scan
# would only re-read every genuine chat's title on every boot, forever.
BACKFILL_MARKER = os.environ.get("BRAIN_SOURCES_BACKFILL_MARKER",
                                 "/data/.run-sources-backfilled")


def backfill_sources(cwd: str, limit: int = MAX_FILTER_SCAN) -> int:
    """Label old machine transcripts whose callers claimed nothing.

    Before 1.28.2 the pool's reflection pass and one-shot voice fallback ran
    with no ``--session-id`` at all, so every one of them sat in "Your
    chats" — the rail's whole reason for existing, defeated by its own
    plumbing. New runs claim for themselves now; this labels the backlog
    once so the list is honest immediately rather than in a fortnight when
    the CLI has pruned the old files. Returns how many were labelled.
    """
    marker = Path(BACKFILL_MARKER)
    if marker.exists():
        return 0
    directory = project_dir(cwd)
    count = 0
    if directory is not None:
        paths = []
        for path in _iter_sessions(directory):
            try:
                if path.stat().st_size < 200:
                    continue
            except OSError:
                continue
            paths.append(path)
            if len(paths) >= limit:
                break
        claimed = run_sources.lookup(p.stem for p in paths)
        for path in paths:
            if path.stem in claimed:
                continue
            title = title_of(path)
            for prefix, source in MACHINE_OPENERS:
                if title.startswith(prefix):
                    if run_sources.record(path.stem, source):
                        count += 1
                    break
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{int(time.time())}\n", encoding="utf-8")
    except OSError:
        # It will simply run again next boot — idempotent, because claims
        # already made are skipped.
        pass
    return count


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
        mtime = path.stat().st_mtime
        shutil.move(str(path), str(target))
        # The TTL is judged by mtime, and shutil.move preserves the
        # *conversation's* mtime — its last-activity time, routinely older
        # than the TTL, which made a just-deleted conversation "expired"
        # on arrival: the very next prune (the second id of one batch
        # delete, even) unlinked it while the toast still offered Undo.
        # The trash file's mtime is its time of *deletion*; the original
        # rides along for restore_deleted to put back.
        os.utime(target)
    except OSError:
        return None
    return {"id": session_id, "path": str(path), "trash": str(target),
            "mtime": mtime}


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
        # Deletion stamped the trash copy's mtime; hand back the original
        # so the restored row keeps its place in the rail's ordering.
        mtime = entry.get("mtime")
        if isinstance(mtime, (int, float)) and mtime > 0:
            os.utime(dst, (mtime, mtime))
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


# What a run's tool traffic may cost to read. Generous — an investigation
# reads histories — and bounded, because this is read once per case on
# the loop's thread pool and a pathological transcript must not stall it.
MAX_TOOL_TRAFFIC_CHARS = 2_000_000


def tool_traffic(cwd: str, session_id: str) -> str | None:
    """Everything a run SENT to its tools and got back, as one string.

    What `parse_case`'s invented-evidence guard has to read. It used to
    read the CLI's final reply instead, which is the one place the answer
    under test is written — so on a CLI that echoes its JSON every cited
    id was "read" and the guard was vacuous, and on one that answers with
    validated `structured_output` and a line of prose no neighbour was
    ever "read" and a real case was thrown away. Tool inputs and tool
    results are what the run actually touched; the assistant's own text
    is deliberately left out, final answer included.

    None — never "" — for a transcript that cannot be found or read,
    because "I could not look" and "it looked at nothing" are different
    claims, and only the second may refuse a case.
    """
    directory = project_dir(cwd)
    if directory is None:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", session_id or ""):
        return None
    path = directory / f"{session_id}.jsonl"
    if not path.is_file():
        return None
    parts: list[str] = []
    size = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                message = entry.get("message") if isinstance(entry, dict) else None
                content = message.get("content") if isinstance(message, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        piece = json.dumps(block.get("input") or {})
                    elif block.get("type") == "tool_result":
                        piece = _result_text(block.get("content"))
                    else:
                        continue
                    parts.append(piece)
                    size += len(piece)
                    if size > MAX_TOOL_TRAFFIC_CHARS:
                        return "\n".join(parts)
    except OSError:
        return None
    return "\n".join(parts)


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(c.get("text") or "") for c in content
                         if isinstance(c, dict))
    return ""


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
        injected = injected_events(_message_text(entry))
        if injected is not None:
            return injected
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
