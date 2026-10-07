"""The queue from this house's fault list to a GitHub issue.

One fault, one issue, for as long as the fault exists. The rows are
`reports.faults` — the same sweep that opens every problem report and
⚙ › Diagnostics — so "what is wrong with this install" has one answer
whether a person or the loop is asking.

Four rules.

**A fingerprint is the fault, not the sentence.** `where` plus `what`
with every digit folded, so "3 of 12 runs failed" and "4 of 13 runs
failed" are one issue, and the number lives in the body where it can
move. Computed over the RAW text, never the aliased one, so a rename on
the house cannot split one fault into two issues.

**Nothing leaves without a press until review is turned off.** A new
fingerprint lands `pending`; Send moves it on, Discard ends it for good
(a discarded fingerprint is never queued again, which is the whole of
what the press means). The preview is the composed body, built by the
same function the sender calls, so what was read is what is sent.

**After the first send, the loop only ever says WHEN.** "Still happening
on 2.17.1", "not seen since Tuesday", "back again" — dates, versions and
counts, nothing from the house — so those follow-ups go without a press
even in review mode. They are what lets an issue close itself: a fix
that shipped is a fingerprint that stopped, said on the issue it fixed.

**It never raises.** It runs on the checks loop's tick, and a report
about a fault that took down the loop reporting it is the worse outcome
— `reports.file_incident`'s rule, one module over.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time

import atomic_write
import reports

from . import STREAMS, data_dir, enabled, load_settings, read_token, stream_on
from . import github
from .aliases import Aliases

log = logging.getLogger("brain.devloop")

# How often the fault list is swept into the queue. Hourly: the faults
# change over hours, and the diagnostics payload is not free to build.
SWEEP_INTERVAL_S = 3600
# At most this many new issues per pass, so a house that has just broken
# in twelve places does not file twelve issues in one second; the rest
# go on the next pass.
MAX_SENDS_PER_PASS = 5
# How long a sent fingerprint has to be absent before the issue is told it
# stopped. Two days, because a checks pass that skipped a check is not
# the fault going away and the next pass may bring it back.
CLEAR_AFTER_S = 48 * 3600
MAX_QUEUE = 60
MAX_ABRIDGED = 20_000
FP_RE = re.compile(r"^[0-9a-f]{16}$")
# Rows that are about the fault list itself rather than a fault.
SKIP_WHERE = frozenset({"This list"})
STATES = ("pending", "ready", "sent", "discarded")

_GITHUB_TOKEN_RE = re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b")
_LOCK = threading.Lock()
STATE: dict = {"last_sweep": 0.0, "last_send": 0.0, "error": "", "running": False}


def _queue_file():
    return data_dir() / "queue.json"


def _load() -> dict:
    try:
        data = json.loads(_queue_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": {}}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"items": {}}
    return data


def _save(data: dict) -> None:
    atomic_write.write_json(_queue_file(), data, mode=0o600)


def fingerprint(where: str, what: str) -> str:
    norm = re.sub(r"\d+", "#", f"{where}|{what}".strip().lower())
    return hashlib.sha256(norm.encode("utf-8", "replace")).hexdigest()[:16]


def _digest(text: str) -> str:
    """An exact hash. A rolling issue's key and body change in exactly the
    digits `fingerprint` folds away (a version, a count), so folding them
    would file every release's scorecard into the first one and never
    rewrite a body whose only change is a number."""
    return hashlib.sha256(str(text).encode("utf-8", "replace")).hexdigest()[:16]


def scrub(text: str) -> str:
    """Everything credential-shaped out: the reports' own rules plus a
    GitHub token, which this package is the first to hold."""
    return _GITHUB_TOKEN_RE.sub("[redacted]", reports.redact(str(text or "")))


def _abridged(diagnostics: dict) -> str:
    small = reports.abridge(diagnostics)
    if isinstance(small, dict):
        small.pop("faults", None)  # the issue IS one of them
    text = json.dumps(small, indent=1, ensure_ascii=False, default=str)
    return text[:MAX_ABRIDGED]


def _version(diagnostics: dict) -> str:
    v = (diagnostics or {}).get("versions") or {}
    return str(v.get("addon") or "dev") if isinstance(v, dict) else "dev"


# ---------------------------------------------------------------------------
# Sweeping
# ---------------------------------------------------------------------------

def sweep(diagnostics: dict, names: dict | None = None,
          now: float | None = None) -> dict:
    """Fold the current fault list into the queue. Never raises.

    The faults stream's own door, kept because it is the one the hourly
    tick has always called; every stream goes through `ingest`."""
    from . import streams  # noqa: PLC0415 — streams imports reports too
    rows = streams.faults(diagnostics) if stream_on("faults") else []
    return ingest("faults", rows, diagnostics, names, now)


def ingest(stream: str, rows: list[dict], diagnostics: dict | None = None,
           names: dict | None = None, now: float | None = None) -> dict:
    """File one stream's rows into the queue and stamp the stream as run.
    Never raises."""
    try:
        with _LOCK:
            return _ingest(stream, rows or [], diagnostics or {}, names or {},
                           now or time.time())
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        log.warning("devloop %s pass failed: %s", stream, exc)
        STATE["error"] = f"{stream} pass failed: {exc}"[:300]
        return {"error": STATE["error"]}


def _ingest(stream: str, rows: list[dict], diagnostics: dict, names: dict,
            now: float) -> dict:
    if stream not in STREAMS:
        raise ValueError(f"unknown stream: {stream}")
    settings = load_settings()
    aliases = Aliases.load()
    aliases.learn(names)
    data = _load()
    items: dict = data["items"]
    version = _version(diagnostics)
    health = (diagnostics or {}).get("health") or {}
    abridged = _abridged(diagnostics) if stream == "faults" else ""
    rolling = bool(STREAMS[stream].get("rolling"))
    seen_now: set[str] = set()
    added = 0
    for row in rows:
        where, what = str(row.get("where") or ""), str(row.get("what") or "")
        if not what:
            continue
        # A row that names its own key (a rolling stream's one issue) is
        # that key; any other is the fault, digits folded.
        fp = _digest(f"{stream}|{row['key']}") if row.get("key") \
            else fingerprint(where, what)
        if fp in seen_now:
            continue
        seen_now.add(fp)
        entry = items.get(fp)
        if entry is None:
            entry = items[fp] = {
                "fp": fp, "first_seen": now, "seen": 0, "stream": stream,
                "state": "pending" if settings["review"] else "ready",
            }
            added += 1
        if entry.get("cleared_noted"):
            entry["returned"] = True
            entry["cleared_noted"] = False
        entry.update({
            "stream": stream, "rolling": rolling,
            "where": where[:200], "what": what[:300],
            "detail": str(row.get("detail") or "")[:400],
            "body": str(row.get("body") or "")[:20_000],
            "last_seen": now, "seen": int(entry.get("seen") or 0) + 1,
            "version": version,
            "health": f"{health.get('state') or '?'}"
                      + (f" — {health.get('reason')}" if health.get("reason") else ""),
            "abridged": abridged,
        })
    _prune(items)
    data["swept_at"] = now
    data.setdefault("last_run", {})[stream] = now
    _save(data)
    aliases.save()
    STATE["last_sweep"] = now
    return {"stream": stream, "rows": len(seen_now), "added": added}


# ---------------------------------------------------------------------------
# The schedule and the caps
# ---------------------------------------------------------------------------

def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def due_streams(now: float | None = None) -> list[str]:
    """The streams whose schedule says a pass is owed now."""
    now = now or time.time()
    settings = load_settings()
    if not settings.get("enabled"):
        return []
    last = _load().get("last_run") or {}
    out = []
    for name in STREAMS:
        hours = int((settings.get("schedule") or {}).get(name) or 0)
        if not hours or not (settings.get("streams") or {}).get(name):
            continue
        if now - float(last.get(name) or 0) >= hours * 3600:
            out.append(name)
    return out


def runs_left(now: float | None = None) -> int:
    """How many Claude-run passes today's cap still allows."""
    now = now or time.time()
    used = _load().get("runs") or {}
    count = int(used.get("count") or 0) if used.get("day") == _day(now) else 0
    return max(0, int(load_settings().get("max_runs_per_day") or 0) - count)


def spend_run(now: float | None = None) -> bool:
    """Take one Claude-run pass from today's cap, or say there is none."""
    now = now or time.time()
    with _LOCK:
        if runs_left(now) <= 0:
            return False
        data = _load()
        used = data.get("runs") or {}
        count = int(used.get("count") or 0) if used.get("day") == _day(now) else 0
        data["runs"] = {"day": _day(now), "count": count + 1}
        _save(data)
    return True


def mark_run(stream: str, now: float | None = None) -> None:
    """Stamp a stream as run without filing anything (a pass that found
    nothing still ran, and must not be asked again until it is due)."""
    with _LOCK:
        data = _load()
        data.setdefault("last_run", {})[stream] = now or time.time()
        _save(data)


def _issues_today(items: dict, now: float) -> int:
    return sum(1 for e in items.values() if isinstance(e, dict)
               and now - float(e.get("sent_at") or 0) < 86400
               and e.get("created_here"))


def _prune(items: dict) -> None:
    if len(items) <= MAX_QUEUE:
        return
    # Discarded and long-quiet entries go first; a pending one somebody has
    # not looked at yet is kept over a sent one that has been fixed.
    def rank(e: dict) -> tuple:
        order = {"discarded": 0, "sent": 1, "ready": 2, "pending": 3}
        return (order.get(e.get("state"), 0), e.get("last_seen") or 0)
    for fp in sorted(items, key=lambda k: rank(items[k]))[:len(items) - MAX_QUEUE]:
        items.pop(fp, None)


# ---------------------------------------------------------------------------
# Composing — the one function the preview and the sender both call
# ---------------------------------------------------------------------------

def _date(epoch) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(epoch or 0)))


def compose(entry: dict, aliases: Aliases | None = None) -> dict:
    """``{"title", "body"}`` exactly as they would be sent."""
    aliases = aliases or Aliases.load()

    def clean(text: str) -> str:
        return aliases.apply(scrub(text))

    where, what = clean(entry.get("where", "")), clean(entry.get("what", ""))
    title = f"[{where}] {what}"[:120] if where else what[:120]
    lines = [
        github.MARKER.format(fp=entry.get("fp", "")),
        ("Filed by brAIn's development loop from a house that switched it "
         + "on. Entity ids, names and rooms are replaced with stable aliases "
         + "and anything credential-shaped is removed."),
        "",
        f"**Where:** {where}",
        f"**What:** {what}",
    ]
    if entry.get("detail"):
        lines.append(f"**Detail:** {clean(entry['detail'])}")
    if entry.get("body"):
        lines += ["", clean(entry["body"])]
    lines += ["", "| | |", "|---|---|",
              f"| brAIn | {clean(entry.get('version', '?'))} |",
              f"| First seen | {_date(entry.get('first_seen'))} |"]
    # A rolling issue is rewritten only when what it says changes, so it
    # carries no per-pass counter: one would make every pass a rewrite.
    if not entry.get("rolling"):
        lines += [f"| Last seen | {_date(entry.get('last_seen'))} |",
                  f"| Seen on | {int(entry.get('seen') or 0)} passes |"]
    lines += [f"| Health | {clean(entry.get('health', '?'))} |", ""]
    if entry.get("abridged"):
        lines += [
            "<details><summary>Diagnostics (abridged)</summary>",
            "",
            "```json",
            clean(entry["abridged"]),
            "```",
            "</details>",
        ]
    lines += ["", f"Stream: `{entry.get('stream') or 'faults'}`"]
    return {"title": title, "body": "\n".join(lines)}


# ---------------------------------------------------------------------------
# The person's presses
# ---------------------------------------------------------------------------

def listing() -> list[dict]:
    rows = []
    for e in _load()["items"].values():
        if not isinstance(e, dict):
            continue
        rows.append({k: e.get(k) for k in (
            "fp", "stream", "where", "what", "state", "seen", "first_seen", "last_seen",
            "issue", "issue_url", "error", "cleared_noted")})
    order = {"pending": 0, "ready": 1, "sent": 2, "discarded": 3}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -(r["last_seen"] or 0)))
    return rows


def preview(fp: str) -> dict | None:
    if not FP_RE.match(fp or ""):
        return None
    entry = _load()["items"].get(fp)
    return compose(entry) if isinstance(entry, dict) else None


def mark(fp: str, state: str) -> bool:
    """Send (``ready``) or Discard (``discarded``) one fingerprint."""
    if not FP_RE.match(fp or "") or state not in ("ready", "discarded"):
        return False
    with _LOCK:
        data = _load()
        entry = data["items"].get(fp)
        if not isinstance(entry, dict) or entry.get("state") == "sent":
            return False
        entry["state"] = state
        entry.pop("error", None)
        _save(data)
    return True


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_due(now: float | None = None) -> dict:
    """Send what is ready and say what changed on what was sent. Never raises."""
    try:
        with _LOCK:
            return _send_due(now or time.time())
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        log.warning("devloop send failed: %s", exc)
        STATE["error"] = f"send failed: {exc}"[:300]
        return {"error": STATE["error"]}


def _send_due(now: float) -> dict:
    if not enabled():
        return {"skipped": "the development loop is off"}
    settings = load_settings()
    token, repo = read_token(), settings["repo"]
    if not token or not repo:
        STATE["error"] = "set a repository and a token to send"
        return {"skipped": STATE["error"]}
    data = _load()
    items: dict = data["items"]
    work = [e for e in items.values() if isinstance(e, dict) and (
        e.get("state") == "ready" or (e.get("state") == "sent" and e.get("issue")))]
    if not work:
        STATE["error"] = ""
        return {"sent": 0, "updated": 0}
    ok, why = github.check_repo(token, repo)
    if not ok:
        STATE["error"] = why
        return {"error": why}
    aliases = Aliases.load()
    sent = updated = 0
    # The day's cap counts only issues this house CREATED: a fingerprint
    # found again by its marker, a comment and a rewritten scorecard file
    # nothing new and cost nobody's attention.
    room = max(0, int(settings.get("max_issues_per_day") or 0)
               - _issues_today(items, now))
    capped = 0
    for entry in sorted(work, key=lambda e: e.get("first_seen") or 0):
        if entry["state"] == "ready":
            if sent >= min(MAX_SENDS_PER_PASS, room):
                capped += 1
                continue
            if _file(token, repo, entry, aliases, now):
                sent += 1
        elif entry.get("rolling"):
            if _rewrite(token, repo, entry, aliases):
                updated += 1
        elif _follow_up(token, repo, entry, now):
            updated += 1
    _save(data)
    aliases.save()
    STATE.update(last_send=now, error="")
    return {"sent": sent, "updated": updated, "capped": capped}


def _rewrite(token: str, repo: str, entry: dict, aliases: Aliases) -> bool:
    """A rolling issue is one issue whose body is the current answer: the
    body is rewritten when what it says has changed, and never commented
    on — a scorecard with a comment a day is a scorecard nobody reads."""
    doc = compose(entry, aliases)
    digest = _digest(doc["body"])
    if digest == entry.get("body_digest"):
        return False
    ok, err = github.update_issue(token, repo, int(entry.get("issue") or 0),
                                  doc["title"], doc["body"])
    if not ok:
        entry["error"] = err
        return False
    entry["body_digest"] = digest
    entry.pop("error", None)
    return True


def _file(token: str, repo: str, entry: dict, aliases: Aliases, now: float) -> bool:
    number, err = github.find_issue(token, repo, entry["fp"])
    if err:
        entry["error"] = err
        return False
    if number:
        issue, err = github.get_issue(token, repo, number)
    else:
        doc = compose(entry, aliases)
        issue, err = github.create_issue(
            token, repo, doc["title"], doc["body"],
            labels=[github.LABEL, f"devloop:{entry.get('stream') or 'faults'}"])
        if issue:
            entry["created_here"] = True
            entry["body_digest"] = _digest(doc["body"])
    if err or not issue:
        entry["error"] = err or "GitHub did not return the issue"
        return False
    entry.update(state="sent", issue=int(issue.get("number") or 0),
                 issue_url=str(issue.get("html_url") or ""), sent_at=now,
                 noted_version=entry.get("version"), cleared_noted=False,
                 returned=False)
    entry.pop("error", None)
    return True


def _follow_up(token: str, repo: str, entry: dict, now: float) -> bool:
    """One comment, when there is something to say: it stopped, it came
    back, or it is still happening on a newer version. Dates and versions
    only — nothing composed from the house."""
    number = int(entry.get("issue") or 0)
    absent = now - float(entry.get("last_seen") or 0)
    version = str(entry.get("version") or "?")
    text, reopen = "", False
    # "Not seen" is a claim only a sweep that LOOKED can make: with the
    # stream switched off nothing was looking, and silence is not the
    # fault going away (`clear_resolved`'s rule).
    stream = str(entry.get("stream") or "faults")
    if not STREAMS.get(stream, {}).get("clears"):
        # A request, an idea or a gap is said once; whether it stopped is
        # not a question the stream can answer.
        return False
    looked = stream_on(stream)
    if looked and absent >= CLEAR_AFTER_S and not entry.get("cleared_noted"):
        text = (f"Not seen since {_date(entry.get('last_seen'))} "
                f"(brAIn {version}).")
        entry["cleared_noted"] = True
    elif absent < CLEAR_AFTER_S and (entry.get("returned")
                                     or version != entry.get("noted_version")):
        issue, err = github.get_issue(token, repo, number)
        if err or not issue:
            entry["error"] = err
            return False
        reopen = issue.get("state") == "closed"
        if reopen:
            text = (f"Back again on brAIn {version} after this was closed "
                    f"(last seen {_date(entry.get('last_seen'))}).")
        elif entry.get("returned"):
            text = f"Back again on brAIn {version}."
        else:
            text = f"Still happening on brAIn {version}."
        entry["returned"] = False
        entry["noted_version"] = version
    if not text:
        return False
    ok, err = github.comment(token, repo, number, text, reopen=reopen)
    if not ok:
        entry["error"] = err
        return False
    entry.pop("error", None)
    return True


def status() -> dict:
    data = _load()
    return {
        "last_run": data.get("last_run") or {},
        "runs_left": runs_left(),
        "last_sweep": STATE["last_sweep"] or data.get("swept_at") or 0,
        "last_send": STATE["last_send"],
        "error": STATE["error"],
        "running": STATE["running"],
    }
