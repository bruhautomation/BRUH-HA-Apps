"""An answer given somewhere else, on its way back to the one store.

brAIn's work list lives on the Findings tab, behind ingress, and every
ending is a press there. The two places people actually are — the To-do
app and their phone's lock screen — could show a finding and could not
end one, so answering meant opening the panel to press a button you had
already pressed.

The panel owns the findings store and is deliberately the only writer:
`brain findings` goes through its API on 8099 rather than the files for
exactly that reason. Home Assistant cannot reach that port — 8099 is
`null` in `ports:` on purpose, and it is going to stay that way — so what
crosses the gap is a **request**, not a write. The integration drops a
small JSON file on the shared volume; the panel picks it up, applies it
through `findings_store` like any other ending, and deletes it. One
writer, two front doors.

Four rules, and each of them is about somebody's phone being out of date
by a few seconds rather than about anything going wrong.

**A request naming a finding that is gone is not an error.** Somebody
ticks an item off in the To-do app while the panel has already cleared
it, or presses a notification from Tuesday. The answer is to drop the
request and say so in the log — not to retry, and certainly not to
resurrect the row.

**Applying twice has to be harmless**, because the delete can fail (a
read-only `/config`, a permission that changed) and the next pass will
find the same file. Settling an already-settled finding returns nothing
and changes nothing, and a snooze written twice is the same snooze — so
there is no ledger of applied ids here, and there does not need to be.

**Every field is data from another process.** The id is an int or the
request is dropped; the verb is one of a closed set; the note is capped
and goes where a typed note goes. Nothing here trusts a filename or a
key it has not checked.

**And the queue is bounded.** A directory nothing drains — an add-on
stopped for a week while somebody keeps pressing buttons — must not
become the reason the panel is slow to start.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("brain.requests")

REQUEST_DIR = Path(os.environ.get(
    "BRAIN_FINDING_REQUESTS_DIR", "/config/.brain/finding-requests"))

# The endings a person can give from outside the panel. They are the
# tab's own verbs and nothing new: "I've fixed it", "you have misread my
# house", and "not now". Anything else — a fix run, a regeneration — is
# work rather than an answer, and belongs behind the panel where the
# thing it starts can be watched.
ACTIONS = ("fixed", "wrong", "snooze")

# ...and the tab's own verb for each, so the two front doors settle a
# finding through exactly the same code. "fixed" is the tab's "done" —
# a person saying they handled it — and the wording differs only because
# a button says "I've fixed it" while an action id has to be one word.
VERBS = {"fixed": "done", "wrong": "wrong"}

# A request is a few hundred bytes. Anything larger is not one.
MAX_BYTES = 16 * 1024
# One pass. A backlog past this is drained over several, oldest first,
# so an add-on that was off for a week starts in bounded time.
MAX_PER_PASS = 50
# Past this the directory is not a queue any more, and the oldest are
# dropped: a request from three weeks ago is about a finding that has
# almost certainly been answered another way.
MAX_QUEUED = 500
KEEP_S = 14 * 86400
NOTE_MAX = 500
SNOOZE_DEFAULT_H = 24
SNOOZE_MAX_H = 24 * 30


def parse(obj) -> dict | None:
    """A validated request, or None for anything that is not one."""
    if not isinstance(obj, dict):
        return None
    ts = obj.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    action = str(obj.get("action") or "").strip().lower()
    if action not in ACTIONS:
        return None
    hours = obj.get("hours")
    if isinstance(hours, bool) or not isinstance(hours, (int, float)):
        hours = SNOOZE_DEFAULT_H
    hours = max(1.0, min(float(hours), SNOOZE_MAX_H))
    return {
        "ts": int(ts),
        "action": action,
        "note": str(obj.get("note") or "").strip()[:NOTE_MAX],
        "hours": hours,
        # Where the answer came from, for the log line and for nothing
        # else: an ending is an ending whichever surface gave it, and a
        # per-surface rule here would be a second policy nobody can see.
        "via": str(obj.get("via") or "")[:32],
    }


def verb_for(action: str) -> str:
    """The Findings tab's verb for a request's action, or "" for a snooze."""
    return VERBS.get(action, "")


def _files() -> list[Path]:
    try:
        found = [p for p in REQUEST_DIR.glob("*.json") if p.is_file()]
    except OSError:
        return []
    found.sort(key=lambda p: p.name)
    return found


def _prune(files: list[Path], now: float) -> list[Path]:
    """Drop what is too old or too many, oldest first. Returns what is left."""
    stale = []
    for path in files:
        try:
            if now - path.stat().st_mtime > KEEP_S:
                stale.append(path)
        except OSError:
            continue
    keep = [p for p in files if p not in stale]
    if len(keep) > MAX_QUEUED:
        stale += keep[:len(keep) - MAX_QUEUED]
        keep = keep[len(keep) - MAX_QUEUED:]
    for path in stale:
        _drop(path)
    if stale:
        log.warning("dropped %d stale finding request(s)", len(stale))
    return keep


def _drop(path: Path) -> None:
    try:
        path.unlink()
    except OSError as exc:
        # The request was already applied by the time this runs, and
        # applying it again is a no-op — see the module docstring.
        log.info("could not remove %s: %s", path, exc)


def _read(path: Path) -> dict | None:
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        return parse(json.loads(raw))
    except ValueError:
        return None


def collect(now: float | None = None) -> list[dict]:
    """Take what is waiting: validated requests, files removed.

    Deliberately does NOT apply them. An ending is three things — the
    settled key, the memory line in the homeowner's own words, and the
    row deleted — and the panel already has one implementation of that
    (`FINDING_VERBS`, shared with the tab's own buttons). A second one
    here would be a tick in the To-do app teaching brAIn something
    different from the identical press on the Findings tab.
    """
    now = time.time() if now is None else now
    files = _prune(_files(), now)
    out: list[dict] = []
    for path in files[:MAX_PER_PASS]:
        req = _read(path)
        _drop(path)
        if req is None:
            log.info("ignored an unreadable finding request: %s", path.name)
            continue
        out.append(req)
    return out


def pending() -> int:
    """How many requests are waiting, for the diagnostics bundle."""
    return len(_files())


__all__ = [
    "ACTIONS", "KEEP_S", "MAX_BYTES", "MAX_PER_PASS", "MAX_QUEUED",
    "NOTE_MAX", "REQUEST_DIR", "SNOOZE_DEFAULT_H", "SNOOZE_MAX_H",
    "collect", "parse", "pending", "verb_for",
]
