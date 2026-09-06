"""The run journal — one line per thing brAIn asked Claude, or did itself.

Read the CLAUDE.md history and one pattern repeats: a silent fallback read
as the real thing, a stale value reported as fresh, a swallowed stderr, a
guard that refused without changing the next attempt. None were visible
from the test suite; all would have been visible from inside the add-on
if anything had been counting. This is the counting.

Every Claude run of any kind — an insight, an asked question, a fix, the
auth check, a chat turn — and every house-checks pass records one line:
who ran it, how long it took, what it cost, and how it ended, in a fixed
vocabulary of outcomes so a field report can say "3 of 12 insight runs in
the last day ended `unparseable`" rather than "cards sometimes don't
generate". Fallbacks are outcomes too, because a fallback nobody counts
is a fallback read as the real thing.

The file is ``/data/journal.jsonl``, capped by line count and rewritten
in place when it grows past the cap. Prompts and replies are never
written here — only the shape of what happened — and error text is
scrubbed of anything credential-shaped before it lands, because this
file is what ``brain report`` bundles for a GitHub issue.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import atomic_write

JOURNAL_FILE = os.environ.get("BRAIN_JOURNAL_FILE", "/data/journal.jsonl")
MAX_LINES = int(os.environ.get("BRAIN_JOURNAL_MAX_LINES", "2000"))
MAX_ERROR = 300

# The outcome vocabulary. A reader keys on these, so a new one is a new
# word for the docs, not a free-text field.
OUTCOMES = (
    "ok",            # it did what it was asked
    "timeout",       # the process was killed at its deadline
    "max_turns",     # the CLI stopped at --max-turns
    "unparseable",   # it answered, and the answer was not the shape asked for
    "auth",          # the credential was refused
    "denied",        # a tool call was refused by the allow list
    "no_cli",        # the claude binary is missing
    "crash",         # the process exited non-zero with no envelope
    "fallback",      # a quieter path was taken instead of the one asked for
    "applied",       # a change was written to the house and verified there
    "healed",        # an overnight remediation made its one call
    "heal_failed",   # it made it and the call came back a failure
    "heal_skipped",  # it was refused before any call was made
    "error",         # anything else
)

_LOCK = threading.Lock()
_SECRET_RE = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}"
    r"|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")


def scrub(text: str) -> str:
    """Error text with anything credential-shaped replaced."""
    return _SECRET_RE.sub("[redacted]", str(text or ""))


def classify(result: dict, timeout_message: str = "") -> str:
    """The outcome word for an engine result envelope."""
    if result.get("ok"):
        return "ok"
    err = str(result.get("error") or "")
    low = err.lower()
    if timeout_message and err == timeout_message:
        return "timeout"
    if "timed out" in low or "timeout" in low:
        return "timeout"
    if "turn limit" in low or "max_turns" in low or "max turns" in low:
        return "max_turns"
    if "cli not found" in low:
        return "no_cli"
    if ("authenticat" in low or "oauth" in low or "401" in low
            or "not logged in" in low or "invalid api key" in low):
        return "auth"
    if "not permitted" in low or "permission" in low and "denied" in low:
        return "denied"
    if low.startswith("claude exited"):
        return "crash"
    if "unparseable" in low or "no json" in low:
        return "unparseable"
    return "error"


def record(source: str, outcome: str, *, ok: bool | None = None,
           error: str = "", duration_s: float | None = None,
           model: str = "", tokens: int | None = None,
           turns: int | None = None, run_id: str = "",
           extra: dict | None = None, now: float | None = None) -> dict:
    """Append one line. Never raises: accounting must not fail the run.

    ``run_id`` is Claude Code's own session id for the invocation, which
    `engine._run_cli` mints and claims in `run_sources` before the run.
    Carrying it here is what lets a journal line, a capture file, a
    transcript and a Chats rail row be joined into one run rather than
    four ids nothing can put together.
    """
    if outcome not in OUTCOMES:
        outcome = "error"
    row: dict = {
        "ts": int(time.time() if now is None else now),
        "source": str(source or "")[:32],
        "outcome": outcome,
        "ok": bool(outcome == "ok") if ok is None else bool(ok),
    }
    if duration_s is not None:
        row["duration_s"] = round(float(duration_s), 1)
    if model:
        row["model"] = str(model)[:64]
    if isinstance(tokens, int) and tokens > 0:
        row["tokens"] = tokens
    if isinstance(turns, int) and turns >= 0:
        row["turns"] = turns
    if run_id:
        row["run_id"] = str(run_id)[:64]
    if error:
        row["error"] = scrub(error)[:MAX_ERROR]
    if extra:
        row["extra"] = {str(k)[:32]: (scrub(v)[:120] if isinstance(v, str) else v)
                        for k, v in list(extra.items())[:8]}
    try:
        _append(row)
    except OSError:
        # The journal is a diagnostic, and a diagnostic that takes down the
        # thing it diagnoses is worse than a missing line.
        pass
    return row


def _append(row: dict) -> None:
    line = json.dumps(row, separators=(",", ":")) + "\n"
    with _LOCK:
        os.makedirs(os.path.dirname(JOURNAL_FILE) or ".", exist_ok=True)
        with open(JOURNAL_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
        # Cap by rewriting only when well past the limit, so an append is
        # an append and not a rewrite of two thousand lines every time.
        if _count_lines() > MAX_LINES + MAX_LINES // 4:
            rows = tail(MAX_LINES)
            atomic_write.write_text(
                JOURNAL_FILE,
                "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))


def _count_lines() -> int:
    try:
        with open(JOURNAL_FILE, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def tail(n: int = 50) -> list[dict]:
    """The newest ``n`` lines, oldest first. A torn line is skipped."""
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-n:] if n > 0 else lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def summary(hours: float = 24.0, now: float | None = None) -> dict:
    """What happened in the window, by source and by outcome.

    ``{"hours", "runs", "by_source": {src: {outcome: n}}, "by_outcome":
    {outcome: n}, "tokens", "failures": [last few non-ok rows]}`` — the
    numbers a diagnostics bundle carries, and the numbers the Diagnostics
    section under ⚙ renders.
    """
    now = time.time() if now is None else now
    cutoff = now - hours * 3600
    rows = [r for r in tail(0) if int(r.get("ts") or 0) >= cutoff]
    by_source: dict[str, dict[str, int]] = {}
    by_outcome: dict[str, int] = {}
    tokens = 0
    failures: list[dict] = []
    for r in rows:
        src = str(r.get("source") or "?")
        outcome = str(r.get("outcome") or "error")
        by_source.setdefault(src, {})
        by_source[src][outcome] = by_source[src].get(outcome, 0) + 1
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if isinstance(r.get("tokens"), int):
            tokens += r["tokens"]
        if outcome != "ok":
            failures.append(r)
    return {
        "hours": hours,
        "runs": len(rows),
        "by_source": by_source,
        "by_outcome": by_outcome,
        "tokens": tokens,
        "failures": failures[-10:],
    }
