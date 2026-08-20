"""Undo for the presses that end something — "I misclicked", nothing more.

Every ending on the Findings tab deletes a row. That is the point of them:
a work list that keeps what you have finished with is not a work list. But
it means a mis-tap is unrecoverable, and the two endings sit next to each
other and mean opposite things ("I fixed it" / "you've got this wrong"), so
the mis-tap is not hypothetical.

**This is deliberately in memory, and deliberately short-lived.** It is the
thing the toast offers while the toast is on screen — not a history, not an
audit trail, and not something to build a "recently settled" view on. A
restart losing it is correct: the toast is long gone by then, and a durable
undo log would be a second record of decisions that memory.md already holds,
which is exactly the duplication the Findings redesign removed.

An entry is taken exactly once. Undo is not idempotent in the useful
direction — pressing it twice must not restore a row twice, and a token that
has been spent is a token that is gone.

Stdlib only, so the test suite can import it without the add-on runtime.
"""
from __future__ import annotations

import secrets
import threading
import time

# Long enough to read a toast and change your mind, short enough that a
# token found in a log is worthless. The toast itself is gone well before.
TTL_S = 300
# A ring, not a log. More than a handful of pending undos means somebody is
# working through a list fast, and only the newest few are reachable anyway.
MAX_ENTRIES = 32

_LOCK = threading.Lock()
_ENTRIES: dict[str, dict] = {}


def _expire(now: float) -> None:
    """Caller holds the lock."""
    for token in [t for t, e in _ENTRIES.items() if e["at"] + TTL_S < now]:
        del _ENTRIES[token]


def record(kind: str, **payload) -> str:
    """Remember how to reverse what just happened. Returns the token.

    ``kind`` is what the reversal is, not what the action was — the caller
    that undoes reads it, and there is no dispatch table here on purpose:
    this module knows nothing about findings or hypotheses, only that
    something wants putting back.
    """
    now = time.time()
    token = secrets.token_urlsafe(12)
    with _LOCK:
        _expire(now)
        _ENTRIES[token] = {"kind": kind, "at": now, **payload}
        # Oldest first out. dicts keep insertion order, so this is the ring.
        while len(_ENTRIES) > MAX_ENTRIES:
            del _ENTRIES[next(iter(_ENTRIES))]
    return token


def take(token: str) -> dict | None:
    """The entry for this token, removed. None if unknown or expired.

    Removed, not read: pressing Undo twice on a toast that is still up must
    not restore the same row twice, and the second press has to be able to
    say "already undone" rather than quietly doing it again.
    """
    now = time.time()
    with _LOCK:
        _expire(now)
        return _ENTRIES.pop(token, None)


def clear() -> None:
    """Forget every pending undo — for tests, and for a fresh start."""
    with _LOCK:
        _ENTRIES.clear()
