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
import logging
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
    "rate_limited",  # the account's usage limit (or the API's rate limit) said wait
    "error",         # anything else
)

# Which of those is a PROBLEM. Six of the fifteen non-`ok` outcomes are
# not: `applied` and `healed` are successes, `heal_skipped` and `denied`
# are refusals doing their job, `fallback` is a quieter path that still
# produced a card, and `rate_limited` is the account saying "not now" —
# a window that resets, answered by the scheduler backing off rather than
# by a problem report per run, forty of which about one spent window is
# how the reports folder stops being opened.
#
# :func:`summary` used to decide this with ``outcome != "ok"``, and a
# successful overnight heal therefore arrived in ``failures`` — where
# `reports.faults` renders it, at the top of *what is wrong right now*,
# as ``Run (healing): ended healed`` with **no detail on it**, which is
# the fault shape nobody can act on. The row was already carrying the
# answer: `record` takes `ok` from the caller (healing passes
# ``ok=True``) and writes it down, and the summary read past it.
#
# The set lives here rather than in `reports.py`, which had its own copy
# and is the module that imports this one: two answers to "is this row a
# failure" is how a producer ends up in one list and not the other.
FAILURE_OUTCOMES = frozenset({
    "timeout", "crash", "unparseable", "auth", "no_cli", "error",
    "heal_failed", "max_turns",
})


def is_failure(row: dict) -> bool:
    """Whether this journal row is something that went wrong.

    ``ok`` is the authority, because it is the caller's own claim about
    its own run and the outcome word cannot always carry it: `healing`
    records ``healed`` with ``ok=True``. The outcome set is the floor
    under a row written before `ok` was on one, or by a caller that let
    it default.
    """
    if not isinstance(row, dict):
        return False
    if row.get("ok"):
        return False
    return outcome_of(row) in FAILURE_OUTCOMES


def outcome_of(row: dict) -> str:
    """The outcome word a row should be COUNTED under.

    The stored word, except an ``error`` whose own text is the account's
    usage limit: that is ``rate_limited`` written before `classify` knew the
    wording, or by a caller that wrote ``error`` itself. The row carries
    the answer either way — the `ok` rule — and a session limit counted as
    a failure is how one evening's limit read as "most Claude runs are
    failing" for the next 24 hours.
    """
    outcome = str(row.get("outcome") or "error")
    if outcome == "error" and _RATE_LIMITED_RE.search(str(row.get("error") or "")):
        return "rate_limited"
    return outcome


# The four fields only a Claude invocation can carry. A checks pass, a
# baseline build and an overnight heal are journal rows with no model
# behind them and set none of these; `engine._journal` sets all four where
# the envelope has them, and the chat sets its model and its turns.
RUN_FIELDS = ("tokens", "turns", "model", "run_id")


def is_claude_run(row: dict) -> bool:
    """Whether a model actually ran for this row.

    Asked by the usage tracker's nudge: the account's usage figure moves
    when a run spends tokens and at no other time, so a finished run is
    the one moment worth asking the endpoint about — and, because only a
    run mints the next access token from the refresh token, the one moment
    the credential is certain to be live.

    Keyed on the ROW and never on a list of source names: a source is a
    string a caller passes, so the set of names that mean "a model ran"
    would be a second place the answer lives, and the drift is invisible
    until a new producer is missing from it.

    Presence, not truthiness. `record` writes each of these keys only for
    a value it accepted, and a run that ended on its first turn writes
    ``turns: 0`` — which a truthiness test reads as no run at all.
    """
    if not isinstance(row, dict):
        return False
    return any(key in row for key in RUN_FIELDS)


_LOCK = threading.Lock()
# Who wants to hear about a row once it has landed. `server` registers the
# problem-report writer here so a failed run of ANY kind is reported without
# every caller of `record` having to remember to. Each listener runs in its
# own try: a listener that raised would fail the run it was told about, which
# is the one thing this module promises not to do.
_LISTENERS: list = []
_SECRET_RE = re.compile(
    r"(sk-ant-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}"
    r"|eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})")


# How the CLI says the account cannot run anything right now: the
# subscription's "You've hit your limit · resets 3pm", its older "usage
# limit reached", the monthly spend cap, and the API's own 429 /
# `rate_limit_error` — including "Server is temporarily limiting
# requests", which is the API's limit and not the account's and is
# answered the same way, by waiting. A 529 is deliberately not here: an
# overloaded service is retried once inside the run (`engine.overloaded`).
_RATE_LIMITED_RE = re.compile(
    r"hit your (?:[a-z\- ]*?)limit|usage limit|rate[ _-]?limit|"
    r"\b429\b|limiting requests|spend limit", re.IGNORECASE)


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
    # The CLI's own verdict is on the envelope; the words are for a result
    # that arrived without one (a shell path's stderr, an older shape).
    if (result.get("meta") or {}).get("subtype") == "error_max_turns":
        return "max_turns"
    if ("turn limit" in low or "max_turns" in low or "max turns" in low
            or "ran out of room" in low):
        return "max_turns"
    if "cli not found" in low:
        return "no_cli"
    # Before the auth words: "usage limit" and "429" are a window, not a
    # credential, and the remedy for one is to wait — `_RATE_LIMITED_RE`
    # is the CLI's own wordings, the subscription's and the API's.
    if _RATE_LIMITED_RE.search(err):
        return "rate_limited"
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


def on_record(fn):
    """Register ``fn(row)`` to be called after every recorded row. Returns
    ``fn`` so it can be used as a decorator; `off_record` removes it."""
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)
    return fn


def off_record(fn) -> None:
    try:
        _LISTENERS.remove(fn)
    except ValueError:
        # Not registered, or already removed: the state this was asked
        # for is the state there is.
        pass


def _notify(row: dict) -> None:
    for fn in list(_LISTENERS):
        try:
            fn(row)
        except Exception:  # noqa: BLE001 — a listener may not fail the run
            logging.getLogger("brain.journal").debug(
                "journal listener %r raised", fn, exc_info=True)


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
    if not is_shell_row(row):
        # A shell row meets the panel's handlers through `book_shell_rows`
        # and nowhere else: notified here as well, one run would be booked,
        # reported and counted twice.
        _notify(row)
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
    {outcome: n}, "tokens", "failures": [last few rows that went wrong]}``
    — the numbers a diagnostics bundle carries, and the numbers the
    Diagnostics section under ⚙ renders.

    ``failures`` is :func:`is_failure`'s set and not "everything that is
    not `ok`": five of the outcome words are successes and refusals, and
    counting them made the fault list open with a heal that worked.
    """
    now = time.time() if now is None else now
    cutoff = now - hours * 3600
    rows = [r for r in tail(0) if int(r.get("ts") or 0) >= cutoff]
    by_source: dict[str, dict[str, int]] = {}
    by_outcome: dict[str, int] = {}
    tokens = 0
    failures: list[dict] = []
    failed_by_outcome: dict[str, int] = {}
    claude_failed = 0
    claude_failed_by: dict[str, int] = {}
    for r in rows:
        src = str(r.get("source") or "?")
        outcome = outcome_of(r)
        by_source.setdefault(src, {})
        by_source[src][outcome] = by_source[src].get(outcome, 0) + 1
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if isinstance(r.get("tokens"), int):
            tokens += r["tokens"]
        if is_failure(r):
            failures.append(r)
            failed_by_outcome[outcome] = failed_by_outcome.get(outcome, 0) + 1
            if is_claude_run(r):
                claude_failed += 1
                claude_failed_by[outcome] = claude_failed_by.get(outcome, 0) + 1
    return {
        "hours": hours,
        "runs": len(rows),
        # Rows a model actually ran for (`is_claude_run`) — the one
        # definition of "a Claude run" the status strip and ⚙ say. `runs`
        # is every journal line: checks passes, baseline builds, and the
        # summary row `_generate` writes beside the run it is about.
        "claude_runs": sum(1 for r in rows if is_claude_run(r)),
        "by_source": by_source,
        "by_outcome": by_outcome,
        # `is_failure`'s count over the whole window, which `failures` (the
        # last ten) cannot give: health's rate is read off this, never off
        # "everything that is not ok".
        "failed": len(failures),
        "failed_by_outcome": failed_by_outcome,
        # The same count over `claude_runs` alone — the numerator for the
        # denominator a person reads. Health's "N of M runs did not
        # succeed" divides these two, so it is a fraction of one set: it
        # divided every failed row (a summary row beside each failed card
        # among them) by every journal line, and a brief reading "677 of
        # 721 runs failed" sat beside a Diagnostics count of 224 ok.
        "claude_failed": claude_failed,
        "claude_failed_by_outcome": claude_failed_by,
        "tokens": tokens,
        "failures": failures[-10:],
    }


# ---------------------------------------------------------------------------
# The shell half
# ---------------------------------------------------------------------------
#
# Study, the memory consolidator, the automation listener and the memory
# extractor all drive `claude -p` from a shell or a separate process, and
# none of them could reach `record`: so their failures filed no problem
# report, their runs nudged no usage reading, and their tokens were in
# neither the breakdown nor the estimate the budget falls back to — while
# CLAUDE.md said every Claude run of every kind recorded itself here.
#
# They reach it now through this file's own command line (`python3
# journal.py record …`), which appends the row and nudges the tracker from
# whichever process ran the model. What it cannot do from there is what
# only the panel's listeners do — a problem report, the usage ledger, the
# scheduler's rate-limit pause — so the row carries ``extra.shell`` and
# the panel books every such row it has not booked yet (`book_shell_rows`)
# on its scheduler tick, through the same listeners an in-process row
# meets. One row, written once, read by both halves.

# Beside the journal unless told otherwise, so anything that points the
# journal somewhere else (a test, a dev checkout) moves the mark with it.
SHELL_MARK_FILE = os.environ.get("BRAIN_SHELL_MARK_FILE", "")
# On a first boot with no mark, rows older than this are history rather
# than news: booking a week of them would file a week of reports at once.
SHELL_BACKLOG_S = 3600
# How far back the booking pass reads. A tick is a minute; a shell run is
# minutes. Two hundred rows is hours of a busy house.
SHELL_TAIL = 200
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHELL_MEMORY_MARK: dict = {"ts": None, "n": 0}


def is_shell_row(row) -> bool:
    """A row the command line wrote, which the panel's listeners never saw."""
    return (isinstance(row, dict) and isinstance(row.get("extra"), dict)
            and row["extra"].get("shell") is True)


def _countable(usage) -> int:
    """`usage_store.tokens_from_meta`'s arithmetic, asked of one usage
    block. Imported rather than restated: two answers to "which fields
    count" is the drift that module's docstring is about."""
    try:
        import usage_store
        return int(usage_store.tokens_from_meta({"usage": usage}) or 0)
    except Exception:  # noqa: BLE001 — accounting never fails a run
        return 0


def envelope_of(text: str) -> dict:
    """The `--output-format json` result envelope out of a run's stdout,
    or ``{}``. The CLI prints one object; a stream prints one per line,
    and the result is the last of them."""
    text = (text or "").strip()
    if not text:
        return {}
    candidates = [text] + [line for line in reversed(text.splitlines())
                           if line.strip().startswith("{")]
    for chunk in candidates:
        try:
            obj = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(obj, dict) and (obj.get("type") == "result"
                                      or "is_error" in obj
                                      or "subtype" in obj):
            return obj
    return {}


def transcript_tokens(run_id: str, roots: list[str] | None = None) -> int:
    """What a run with no envelope spent, read off the transcript the CLI
    left behind (``projects/<dir>/<run id>.jsonl``). The consolidator and
    study read their answer as text, so their runs carry no usage block —
    but the CLI wrote one per model call into the transcript, and a run
    nothing counted is a run the budget estimate reads as free.

    One call is written as several lines (one per content block) carrying
    the same message id and the same usage, so it is counted once per id.
    ``0`` for anything that cannot be read: an uncounted run is the state
    this was in before it existed.
    """
    if not run_id or not _SAFE_RUN_ID.match(run_id):
        return 0
    if roots is None:
        roots = [os.environ.get("CLAUDE_CONFIG_DIR") or "",
                 os.path.join(os.environ.get("HOME") or "", ".claude"),
                 "/data/home/.claude"]
    import glob
    seen_roots: set[str] = set()
    for root in roots:
        if not root:
            continue
        real = os.path.realpath(root)
        if real in seen_roots:
            continue
        seen_roots.add(real)
        for path in glob.glob(os.path.join(real, "projects", "*", run_id + ".jsonl")):
            usage_by_id: dict[str, dict] = {}
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh):
                        if n > 20000:
                            break
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        msg = obj.get("message") if isinstance(obj, dict) else None
                        if (not isinstance(msg, dict) or obj.get("type") != "assistant"
                                or not isinstance(msg.get("usage"), dict)):
                            continue
                        usage_by_id[str(msg.get("id") or n)] = msg["usage"]
            except OSError:
                continue
            total = sum(_countable(u) for u in usage_by_id.values())
            if total:
                return total
    return 0


def record_shell(source: str, exit_code: int, *, envelope: dict | None = None,
                 stderr_text: str = "", error: str = "",
                 run_id: str = "", model: str = "",
                 duration_s: float | None = None, extra: dict | None = None,
                 timeout_exit: int = 124, roots: list[str] | None = None) -> dict:
    """One shell run, judged the way `engine._run_cli` judges its own.

    The envelope is the authority when there is one — its `is_error`,
    `subtype`, `num_turns`, `session_id` and usage are the CLI's own
    account — and the exit status when there is not. 124 is `timeout`'s
    and says so by name, never "crash". A failure with no words of its
    own carries the CLI's last stderr line, because "claude exited 1" is
    the sentence that sends somebody to the wrong place. ``error`` is the
    caller's own verdict on a run that exited 0 and still failed it — a
    study session that answered with no JSON is `unparseable`, which no
    exit status can say.
    """
    env = envelope if isinstance(envelope, dict) else {}
    subtype = str(env.get("subtype") or "")
    turns = None
    tokens = 0
    if env:
        ok = (int(exit_code) == 0 and not env.get("is_error")
              and subtype in ("", "success"))
        err = "" if ok else str(env.get("result") or "")
        if isinstance(env.get("num_turns"), int):
            turns = env["num_turns"]
        run_id = run_id or str(env.get("session_id") or "")
        tokens = _countable(env.get("usage"))
        if duration_s is None and isinstance(env.get("duration_ms"), (int, float)):
            duration_s = env["duration_ms"] / 1000.0
    else:
        ok = int(exit_code) == 0
        err = ""
    if error:
        ok, err = False, str(error)
    if not ok and not err:
        lines = [ln.strip() for ln in (stderr_text or "").splitlines() if ln.strip()]
        err = lines[-1] if lines else ""
    if not ok and int(exit_code) == int(timeout_exit):
        outcome = "timeout"
        err = err or f"timed out (exit {exit_code})"
    else:
        if not ok and not err:
            err = f"claude exited {exit_code}"
        outcome = classify({"ok": ok, "error": err, "meta": {"subtype": subtype}})
    if not tokens and run_id:
        tokens = transcript_tokens(run_id, roots)
    row_extra = {"shell": True, "exit": int(exit_code)}
    for key, value in (extra or {}).items():
        if key not in row_extra and len(row_extra) < 8:
            row_extra[key] = value
    row = record(source, outcome, ok=ok, error=err, duration_s=duration_s,
                 model=model, tokens=tokens or None, turns=turns,
                 run_id=run_id if _SAFE_RUN_ID.match(run_id or "") else "",
                 extra=row_extra)
    if is_claude_run(row):
        # The one listener that has to run where the model ran: the
        # tracker asks again after a run, and nothing else would tell it.
        try:
            import usage_store
            usage_store.nudge()
        except Exception:  # noqa: BLE001 — a nudge is freshness, not a duty
            pass
    return row


def _mark_path() -> str:
    return SHELL_MARK_FILE or os.path.join(
        os.path.dirname(JOURNAL_FILE) or ".", "journal-shell-mark.json")


def _load_mark() -> tuple[int, int] | None:
    path = _mark_path()
    if not os.path.isdir(os.path.dirname(path) or "."):
        mem = _SHELL_MEMORY_MARK
        return None if mem["ts"] is None else (int(mem["ts"]), int(mem["n"]))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
        return int(obj["ts"]), int(obj.get("n") or 0)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_mark(ts: int, n: int) -> None:
    path = _mark_path()
    if not os.path.isdir(os.path.dirname(path) or "."):
        _SHELL_MEMORY_MARK.update(ts=ts, n=n)
        return
    try:
        atomic_write.write_text(path, json.dumps({"ts": ts, "n": n}))
    except OSError:
        _SHELL_MEMORY_MARK.update(ts=ts, n=n)


def book_shell_rows(handlers, now: float | None = None) -> int:
    """Hand every shell row not booked yet to ``handlers``; how many.

    The mark is the newest booked row's second and how many rows share
    it, because `record` stamps whole seconds and two runs can finish in
    one — a mark of the second alone would skip the second of them.
    Kept on disk, so a restart books what landed while the panel was down
    rather than either booking everything again (a report per old
    failure, the usage ledger counted twice) or nothing. A first boot
    starts `SHELL_BACKLOG_S` back. A handler that raises costs that
    handler, never the pass or the mark.
    """
    now = time.time() if now is None else now
    mark = _load_mark()
    if mark is None:
        mark = (int(now - SHELL_BACKLOG_S), 0)
    mark_ts, mark_n = mark
    rows = [r for r in tail(SHELL_TAIL) if is_shell_row(r)]
    fresh: list[dict] = []
    at_mark = 0
    for row in rows:
        ts = int(row.get("ts") or 0)
        if ts < mark_ts:
            continue
        if ts == mark_ts:
            at_mark += 1
            if at_mark <= mark_n:
                continue
        fresh.append(row)
    if not fresh:
        if _load_mark() is None:
            # A first boot: pin the backlog window where it started, or
            # it slides forward a minute every tick until a row lands.
            _save_mark(mark_ts, mark_n)
        return 0
    # Every row in the newest booked second is booked now, whichever pass
    # booked it, so the mark is that second and all of them.
    last_ts = max(int(r.get("ts") or 0) for r in fresh)
    last_n = sum(1 for r in rows if int(r.get("ts") or 0) == last_ts)
    for row in fresh:
        for handler in handlers:
            try:
                handler(row)
            except Exception:  # noqa: BLE001 — one handler, never the pass
                logging.getLogger("brain.journal").debug(
                    "shell row handler %r raised", handler, exc_info=True)
    _save_mark(last_ts, last_n)
    return len(fresh)


def main(argv: list[str] | None = None) -> int:
    """``journal.py record --source S --exit N [...]`` — the shell half's
    one door. Always exits 0 and prints nothing: this is bookkeeping about
    a run, and it may never be the reason a pass reports a failure."""
    import argparse
    parser = argparse.ArgumentParser(prog="journal.py")
    sub = parser.add_subparsers(dest="cmd")
    rec = sub.add_parser("record")
    rec.add_argument("--source", required=True)
    rec.add_argument("--exit", type=int, default=0, dest="exit_code")
    rec.add_argument("--envelope", default="",
                     help="a file holding the run's JSON stdout")
    rec.add_argument("--stderr", default="", help="a file holding its stderr")
    rec.add_argument("--error", default="",
                     help="the caller's own failure verdict on a run that exited 0")
    rec.add_argument("--run-id", default="")
    rec.add_argument("--model", default="")
    rec.add_argument("--duration", type=float, default=None)
    rec.add_argument("--timeout-exit", type=int, default=124)
    rec.add_argument("--extra", action="append", default=[],
                     help="key=value, carried on the row")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 0
    if args.cmd != "record":
        return 0

    def _read(path: str, limit: int = 2_000_000) -> str:
        if not path:
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read(limit)
        except OSError:
            return ""

    extra: dict = {}
    for pair in args.extra:
        key, _, value = pair.partition("=")
        if key.strip():
            extra[key.strip()[:32]] = value[:120]
    try:
        record_shell(args.source, args.exit_code,
                     envelope=envelope_of(_read(args.envelope)),
                     stderr_text=_read(args.stderr, 200_000),
                     error=args.error.strip()[:MAX_ERROR],
                     run_id=args.run_id.strip(), model=args.model.strip(),
                     duration_s=args.duration, extra=extra,
                     timeout_exit=args.timeout_exit)
    except Exception:  # noqa: BLE001 — never the reason a pass fails
        pass
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
