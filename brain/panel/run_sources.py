"""Who asked for a conversation — the one thing Claude Code doesn't record.

The CLI files every conversation under its working directory and says
nothing about which of us started it. Six things drive the same Claude Code
from ``/config``: you (the chat pane and the classic terminal), the voice
assistant, the automation listener, a study session, and the memory
consolidator. In the rail they all looked identical, so a house that talks
to Assist and files memory on a schedule showed a column of near-identical
machine prompts with the person's own chats buried among them.

The contract is one line long, and it is a contract rather than a guess:
**a background caller mints the session id itself** (``--session-id``) and
records it here *before* the run. A conversation whose id is not in this
ledger is one nobody claimed — which is exactly what "a person typed it"
looks like, so the default falls out for free rather than being inferred
from prompt text that would drift the moment a prompt was reworded.

The ledger is an index, not a queue: nothing reads an entry and removes it.
It is capped instead, oldest-first, because a session id whose transcript
the CLI pruned months ago has nothing left to label.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import atomic_write

# Persistent and add-on owned. Not under /config: it is bookkeeping about
# our own processes, not something a person edits or backs up.
LEDGER = Path(os.environ.get("BRAIN_RUN_SOURCES", "/data/run-sources.jsonl"))

# Every face that drives Claude Code, and what to call it on screen. The
# panel renders `label`; `blurb` is the one-line "what this is" for the
# filter. "you" is not here on purpose — it is the absence of an entry.
#
# Most faces run from /config; the two marked `store: "engine"` run from
# CLAUDE_HOME (`engine._run_cli`), so the CLI files their transcripts under
# a different project directory and the panel lists them from there. They
# are records to read, never conversations to resume: the CLI can in fact
# resume by id across directories, but their earlier turns ran under the
# analyst's read-only scoping (or the fixer's) with a card contract, and
# quietly continuing that under the chat's permissions would change the
# conversation's rules mid-thread. In the engine's directory an UNCLAIMED
# id is dropped, not defaulted — nothing there is yours, and the odd
# unclaimed run (the auth self-check) is a probe, not a conversation.
SOURCES: dict[str, dict[str, str]] = {
    "voice": {"label": "Voice", "blurb": "Assist asked it something"},
    "automation": {"label": "Automation", "blurb": "an automation ran a task"},
    "memory": {"label": "Memory", "blurb": "filing the inbox into memory"},
    "study": {"label": "Study", "blurb": "a study session"},
    "card": {"label": "Cards", "blurb":
             "an insight run — scheduled, or a question you asked",
             "store": "engine"},
    "fix": {"label": "Fixes", "blurb": "a Fix it run at the house",
            "store": "engine"},
    # `brain doctor --deep` and `brain doctor --rehearse`. Claimed for the
    # same reason the consolidator's runs are: they are probes, not
    # conversations, and a rail offering somebody "Reply with exactly: OK"
    # as something they said is a rail with the person's own chats buried
    # under machine ones. Filed under the engine's store because that is
    # where nearly all of them run from (`engine._run_cli` works from
    # CLAUDE_HOME); the deep run's one chat-session probe lives in
    # /config's store and is claimed here too, so the default rail — which
    # asks for "you" — does not show it either.
    "doctor": {"label": "Doctor", "blurb": "a deep self-check round trip",
               "store": "engine"},
}

# The sources whose transcripts live in the engine's project directory
# rather than /config's. The server routes their listing there.
ENGINE_SOURCES = frozenset(
    key for key, meta in SOURCES.items() if meta.get("store") == "engine")

# Newest entries kept. Generous — a busy house making a session every voice
# command still takes weeks to roll a fortnight of chats out of the file.
MAX_ENTRIES = 4000
# Rewriting the file on every append would be one read+write per voice
# command; instead let it drift this far past the cap before compacting.
PRUNE_SLACK = 1000

_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,120}")


def known(source: str) -> bool:
    return source in SOURCES


def label(source: str) -> str:
    entry = SOURCES.get(source)
    return entry["label"] if entry else source


def record(session_id: str, source: str) -> bool:
    """Claim a session id for a source. Never raises — this is bookkeeping.

    Called before the run, because the point is to know whose a session is
    even if the run then fails: a crashed study session still left a
    transcript behind, and it should still be labelled as one.
    """
    if not session_id or not _ID_RE.fullmatch(session_id) or not known(source):
        return False
    line = json.dumps({"id": session_id, "source": source,
                       "ts": int(time.time())}, separators=(",", ":"))
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        return False
    _maybe_prune()
    return True


def _read() -> list[dict]:
    try:
        text = LEDGER.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("id"):
            out.append(entry)
    return out


def _maybe_prune() -> None:
    try:
        if LEDGER.stat().st_size < (MAX_ENTRIES + PRUNE_SLACK) * 60:
            return          # cheap upper bound on "could it even be over?"
    except OSError:
        return
    entries = _read()
    if len(entries) <= MAX_ENTRIES + PRUNE_SLACK:
        return
    keep = entries[-MAX_ENTRIES:]
    try:
        atomic_write.write_lines(LEDGER, keep, separators=(",", ":"))
    except OSError:
        # Pruning is housekeeping: an over-long ledger still answers every
        # question a short one does. The scratch file is cleaned up by the
        # writer, so there is nothing left to tidy here.
        pass


def lookup(session_ids) -> dict[str, str]:
    """``{session id: source}`` for the ids that were claimed.

    One read for a whole listing rather than one per row. Ids nobody
    claimed are simply absent — the caller's default is what "yours" means.
    """
    wanted = {sid for sid in session_ids if sid}
    if not wanted:
        return {}
    found: dict[str, str] = {}
    for entry in _read():
        sid = entry.get("id")
        source = entry.get("source")
        if sid in wanted and known(source):
            found[sid] = source          # last claim wins, as with a resume
    return found
