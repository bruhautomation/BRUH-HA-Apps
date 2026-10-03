"""What was sent to a phone, and what happened to it afterwards.

Every notification brAIn sent used to be fire-and-forget: a line in the
log, and the only trace of what a person did about it was the ending it
eventually got on the Findings tab — which says nothing about the message.
A reminder answered within a minute and one swiped away unread for the
tenth week running looked identical from here, so nothing could ever say
"you clear every one of these without reading it", and the household's
sentence about what deserves an interruption could never be argued with by
what the household actually did.

So this is a ledger, one JSON line per message and one per thing that
happened to it. Four rules.

**A message is a row and an outcome is a row.** Appending is cheap and
never rewrites what somebody else is reading; the outcome of a delivery is
FOLDED out of the lines at read time (`fold`). A second writer — the
request drain answering a button while a send is in flight — appends its
line beside the other's, rather than racing it for a rewrite.

**Each outcome says what is knowable, and no more.** *answered* is a
button on the notification, read off the request the integration dropped
(`via: notification`). *cleared* is the companion app's
`mobile_app_notification_cleared`, which only Android sends — so an iPhone
household never clears anything here, and the summary says how many clears
have ever been seen rather than letting a zero read as "nobody swipes".
*opened* is not reported by Home Assistant at all — tapping a notification
opens the panel and fires nothing — so it is named as unknowable rather
than recorded as zero. *ignored* is derived: a day with neither.

**It holds words, not houses.** Titles, bodies, the ids of the findings a
message was about and their producers — what a person read on a lock
screen. It is named in `backup_exclude` with the other per-install
records, and it is capped.

**It never raises.** It is called from the send path and from the bus's
socket pump, and accounting that took down a notification would be worse
than no accounting.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.deliveries")

DELIVERIES_FILE = Path(os.environ.get("BRAIN_DELIVERIES",
                                      "/data/deliveries.jsonl"))

# What a message was. `notify` and `escalate` are `notify_router`'s tiers,
# `held` is a queue release, `reminder` a rung of the ladder, `brief` and
# `weekly` the two messages that are not about a problem, and `reply` the
# answer to somebody's Reply — a message they asked for, which no learned
# suggestion may count as one they did not want.
KINDS = ("notify", "escalate", "held", "reminder", "brief", "weekly", "reply")
# What happened to it, as `fold` reports it.
OUTCOMES = ("answered", "cleared", "ignored", "pending", "failed")

# The tag the companion app carries on a message and hands back in every
# event about it — the one thread from a swipe on a phone to the line that
# sent it. Prefixed so a house with other notifiers can tell whose it is.
TAG_PREFIX = "brain-d-"

# Newest lines kept, with slack before a compaction, `run_sources`'s
# arrangement: rewriting the file on every append would be a read and a
# write per notification.
MAX_LINES = 3000
PRUNE_SLACK = 500
# A message nobody answered or cleared in a day was ignored. Not sooner:
# a notification read at breakfast about something filed at midnight is
# not an ignored one.
IGNORED_AFTER_S = 24 * 60 * 60
# How far back an answer may be matched to the message it was about.
MATCH_WINDOW_S = 7 * 24 * 60 * 60
# What one line may hold. A body is a lock-screen paragraph at most.
TITLE_CHARS = 120
BODY_CHARS = 1500
MAX_ROWS = 24


def new_id() -> str:
    return secrets.token_hex(6)


def tag_for(delivery_id: str) -> str:
    return TAG_PREFIX + str(delivery_id)


def _append(line: dict, path: Path | None = None) -> bool:
    target = Path(path or DELIVERIES_FILE)
    # A dev checkout has no /data, and a ledger must not grow one.
    if not target.parent.is_dir():
        return False
    try:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
        _maybe_prune(target)
        return True
    except OSError as exc:
        log.info("could not write the delivery ledger: %s", exc)
        return False


def _maybe_prune(target: Path) -> None:
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= MAX_LINES + PRUNE_SLACK:
        return
    try:
        atomic_write.write_text(target, "\n".join(lines[-MAX_LINES:]) + "\n")
    except OSError as exc:
        log.info("could not compact the delivery ledger: %s", exc)


def _load(path: Path | None = None) -> list[dict] | None:
    """Every line, oldest first. None when the file exists and cannot be
    read — which is "I could not look", not "nothing was ever sent"."""
    target = Path(path or DELIVERIES_FILE)
    try:
        text = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError:
        return None
    out: list[dict] = []
    for raw in text.splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _ints(values) -> list[int]:
    out = []
    for v in values or []:
        if isinstance(v, bool):
            continue
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def record(kind: str, *, delivery_id: str, service: str, title: str,
           body: str, rows: list[dict] | None = None, ok: bool = True,
           error: str = "", dispatched: bool = False,
           when: float | None = None, path: Path | None = None) -> dict:
    """Write down one message. Returns the line. Never raises.

    `rows` are the findings it was about (a brief and a report have none),
    carried as ids, producers, entities and the worst severity — what the
    learned suggestions count by — and never as a copy of the store.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    sevs = [str(r.get("severity") or "") for r in rows]
    order = ("info", "warning", "serious", "critical")
    worst = max((s for s in sevs if s in order), key=order.index,
                default="")
    line = {
        "id": str(delivery_id),
        "at": int(time.time() if when is None else when),
        "kind": kind if kind in KINDS else "notify",
        "service": str(service or "")[:120],
        "title": str(title or "")[:TITLE_CHARS],
        "body": str(body or "")[:BODY_CHARS],
        "ts": _ints(r.get("ts") for r in rows)[:MAX_ROWS],
        "sources": sorted({str(r.get("source") or "")[:64]
                           for r in rows if r.get("source")})[:MAX_ROWS],
        "entities": sorted({str(r.get("entity_id") or "")[:255]
                            for r in rows if r.get("entity_id")})[:MAX_ROWS],
        "severity": worst,
        "ok": bool(ok),
    }
    if error:
        line["error"] = str(error)[:200]
    if dispatched:
        line["dispatched"] = True
    try:
        _append(line, path)
    except Exception as exc:  # noqa: BLE001 — accounting never fails a send
        log.info("could not record a delivery: %s", exc)
    return line


def note_answer(ts: int, action: str, *, via: str = "",
                when: float | None = None, path: Path | None = None) -> bool:
    """A button on a notification was pressed about finding `ts`.

    Matched to the newest message that carried that finding when it is
    folded, so a reminder answered is the reminder answered rather than
    the first message about the same row.
    """
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return False
    return _append({"ev": "answered", "ts": ts,
                    "action": str(action or "")[:24],
                    "via": str(via or "")[:32],
                    "at": int(time.time() if when is None else when)}, path)


def tag_of(data: dict) -> str:
    """Our tag out of a companion-app event, or "". The app hands the
    message's own `data` back flattened into the event; an older build
    nests it, so both are read."""
    if not isinstance(data, dict):
        return ""
    for holder in (data, data.get("data")):
        if isinstance(holder, dict):
            tag = str(holder.get("tag") or "")
            if tag.startswith(TAG_PREFIX):
                return tag
    return ""


def note_cleared(data: dict, *, when: float | None = None,
                 path: Path | None = None) -> bool:
    """`mobile_app_notification_cleared` for one of ours. Anything without
    our tag is somebody else's notification and is not an error."""
    tag = tag_of(data)
    if not tag:
        return False
    return _append({"ev": "cleared", "id": tag[len(TAG_PREFIX):][:32],
                    "at": int(time.time() if when is None else when)}, path)


def fold(now: float | None = None, path: Path | None = None) -> list[dict] | None:
    """Every message with what happened to it, newest first. None when the
    ledger could not be read.

    Each carries `outcome` (one of OUTCOMES) and, where it applies,
    `action` and `after_s` — how long after it was sent the answer or the
    clear came. A message that was both answered and cleared was answered:
    the swipe that follows a button press is the app tidying up.
    """
    lines = _load(path)
    if lines is None:
        return None
    now = time.time() if now is None else float(now)
    sent: list[dict] = []
    by_id: dict[str, dict] = {}
    for line in lines:
        if "ev" in line:
            continue
        row = dict(line)
        row["outcome"] = "pending"
        sent.append(row)
        by_id[str(row.get("id") or "")] = row
    for line in lines:
        ev = line.get("ev")
        at = float(line.get("at") or 0)
        if ev == "cleared":
            row = by_id.get(str(line.get("id") or ""))
            if row is not None and "cleared_at" not in row:
                row["cleared_at"] = at
        elif ev == "answered":
            ts = line.get("ts")
            match = None
            for row in sent:
                if (ts in (row.get("ts") or [])
                        and float(row.get("at") or 0) <= at
                        and at - float(row.get("at") or 0) <= MATCH_WINDOW_S):
                    match = row      # the newest earlier one wins
            if match is not None and "answered_at" not in match:
                match["answered_at"] = at
                match["action"] = str(line.get("action") or "")
    for row in sent:
        at = float(row.get("at") or 0)
        if not row.get("ok", True):
            row["outcome"] = "failed"
        elif "answered_at" in row:
            row["outcome"] = "answered"
            row["after_s"] = int(row["answered_at"] - at)
        elif "cleared_at" in row:
            row["outcome"] = "cleared"
            row["after_s"] = int(row["cleared_at"] - at)
        elif now - at >= IGNORED_AFTER_S:
            row["outcome"] = "ignored"
    sent.reverse()
    return sent


def recent(now: float | None = None, hours: float = 24, limit: int = 12,
           path: Path | None = None) -> list[dict]:
    """The last day's messages, as the dispatcher is shown them: what went,
    when, and what happened. `[]` for an unreadable ledger — the dispatcher
    is told it has no history, which is the truth about what it can see."""
    now = time.time() if now is None else float(now)
    rows = fold(now, path) or []
    out = []
    for row in rows:
        if now - float(row.get("at") or 0) > hours * 3600:
            break
        out.append({"at": int(row.get("at") or 0), "kind": row.get("kind"),
                    "title": row.get("title") or "",
                    "outcome": row.get("outcome"),
                    "action": row.get("action") or ""})
        if len(out) >= limit:
            break
    return out


def summary(now: float | None = None, path: Path | None = None) -> dict:
    """What the ledger holds, for `/api/diagnostics`.

    A queue nobody can see is a queue that silently swallows, and the
    failure this would hide is a household being sent messages nobody
    reads — or a ledger that stopped recording, which looks the same as a
    quiet week unless the payload says when the last line landed.
    """
    now = time.time() if now is None else float(now)
    rows = fold(now, path)
    if rows is None:
        return {"available": False,
                "error": "the delivery ledger could not be read"}
    week = [r for r in rows if now - float(r.get("at") or 0) <= 7 * 86400]
    by_kind: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    for r in week:
        by_kind[r.get("kind") or "notify"] = by_kind.get(
            r.get("kind") or "notify", 0) + 1
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    return {
        "available": True,
        "messages": len(rows),
        "week": len(week),
        "week_by_kind": by_kind,
        "week_by_outcome": by_outcome,
        "last_sent_at": int(rows[0].get("at") or 0) if rows else 0,
        "dispatched_week": sum(1 for r in week if r.get("dispatched")),
        # Android reports a swipe and iOS does not, so "no clears ever"
        # is a fact about the phone before it is a fact about anybody.
        "clears_ever": sum(1 for r in rows if "cleared_at" in r),
        "answers_ever": sum(1 for r in rows if "answered_at" in r),
        "opened": "not reported by Home Assistant",
    }


__all__ = [
    "DELIVERIES_FILE", "IGNORED_AFTER_S", "KINDS", "MAX_LINES", "OUTCOMES",
    "TAG_PREFIX", "fold", "new_id", "note_answer", "note_cleared", "recent",
    "record", "summary", "tag_for", "tag_of",
]
