"""Today — the hidden half of the one screen, and the cards no store owns.

Today is the queue, Your list and a History drawer (docs/design/
ui-redesign-2026-10.md, "Where hidden things live"). Everything on it is
read out of the stores that already exist; this module adds exactly two
things those stores could not hold.

**A snooze and an ignore for the two cards that are not rows anywhere.**
The "Change ready" card is the name tidy's one pending table and an update
card is one assessed `update.*` entity — neither is a finding, so neither
has a `snoozed_until` or a settled key. Somebody pressing Snooze on one
still has to get it back on a date and find it under History › Snoozed,
so the press is written here, keyed `tidy:<proposal stamp>` or
`update:<entity>:<version>`. The key carries what makes it the same card:
a NEW tidy table or a NEWER version is a different decision, and an
ignore written about last month's table must not hide this month's.

**The History rows.** Four filters — Snoozed, Ignored, Done, Set aside by
brAIn — each one a list of one-line rows with one press (`history`). The
rows are composed from what the caller hands in, so this stays pure over
dicts and testable with the panel down; the presses are routes that
already existed (unsnooze, unsettle, elevate, reopen, unmute, tidy undo)
plus the one this module adds for its own keys. **Duplicates are one row
with a count**: six snoozed "Cooling time yesterday" cards are one thing
to bring back, and a drawer that listed them six times is the pile the
redesign was written against. Grouping is by the normalised title within
a filter, and the group's Restore carries every member's press.

Never raises on read: an unreadable file is "nothing hidden", the
direction in which being wrong shows a card rather than hiding one.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import atomic_write

HIDDEN_FILE = Path(os.environ.get("BRAIN_TODAY_HIDDEN_FILE",
                                  "/data/today-hidden.json"))
KEY_RE = re.compile(r"^(tidy|update):[A-Za-z0-9_.:\-]{1,160}$")
# `listed` is an update somebody put on Your list: off the queue for good,
# and NOT in History, because the list is where it lives now — the same
# card in two places is the pile the redesign was written against.
HOWS = ("snoozed", "ignored", "listed")
# How long a Snooze on one of these buys. A tidy table and an update are
# both "not this week", which is what a snooze on a low-stakes card means
# everywhere else (`cases.SNOOZE_BY_STAKES["low"]`).
SNOOZE_S = 7 * 86400
MAX_HIDDEN = 200
# Deleted History rows remembered, oldest forgotten first. Forgetting one
# costs nothing worse than an old row reappearing.
MAX_CLEARED = 2000
TITLE_MAX = 160
CLEARED_RE = re.compile(r"^(snoozed|ignored|done|aside)\|[^\n]{1,200}$")

FILTERS = ("snoozed", "ignored", "done", "aside")
FILTER_LABELS = {
    "snoozed": "Snoozed",
    "ignored": "Ignored",
    "done": "Done",
    "aside": "Set aside by brAIn",
}
# Rows per filter. The drawer is a record, not a queue, and a record
# rendered whole is a second list that never empties.
MAX_ROWS = 60


def _read() -> dict:
    try:
        data = json.loads(HIDDEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("hidden") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    out = {}
    for key, row in rows.items():
        if not KEY_RE.match(str(key)) or not isinstance(row, dict):
            continue
        if row.get("how") not in HOWS:
            continue
        out[str(key)] = {
            "how": row["how"],
            "until": int(row.get("until") or 0),
            "at": int(row.get("at") or 0),
            "title": str(row.get("title") or "")[:TITLE_MAX],
        }
    return out


def _read_cleared() -> dict:
    """`{row id: stamp}` — the History rows somebody deleted, and how new
    the newest thing in that row was when they did."""
    try:
        data = json.loads(HIDDEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("cleared") if isinstance(data, dict) else None
    if not isinstance(rows, dict):
        return {}
    out = {}
    for key, at in rows.items():
        if not CLEARED_RE.match(str(key)):
            continue
        try:
            out[str(key)] = int(at)
        except (TypeError, ValueError):
            continue
    return out


def _write(rows: dict, cleared: dict | None = None) -> None:
    if len(rows) > MAX_HIDDEN:
        rows = dict(sorted(rows.items(), key=lambda kv: kv[1]["at"])[-MAX_HIDDEN:])
    cleared = _read_cleared() if cleared is None else cleared
    if len(cleared) > MAX_CLEARED:
        cleared = dict(sorted(cleared.items(), key=lambda kv: kv[1])[-MAX_CLEARED:])
    HIDDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write.write_json(HIDDEN_FILE, {"hidden": rows, "cleared": cleared})


def clear(items: list) -> int:
    """Delete History rows: `[{"id": "<filter>|<key>", "at": stamp}]`.

    Deleting a row takes it off the record and changes nothing else — an
    ignored finding stays settled, a finished chore stays finished — so it
    is never a way back into the queue. The stamp is what keeps it gone:
    the row comes back only when something NEWER lands under the same
    title (the same problem ignored again next month is a new answer, and
    one somebody may want to see). Snoozed rows are not deletable; they
    come back on their own date whatever this list says. Returns how many
    were recorded.
    """
    cleared = _read_cleared()
    n = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("id") or "")
        if not CLEARED_RE.match(rid) or rid.startswith("snoozed|"):
            continue
        try:
            at = int(item.get("at") or 0)
        except (TypeError, ValueError):
            continue
        cleared[rid] = max(at, cleared.get(rid, 0))
        n += 1
    if n:
        _write(_read(), cleared)
    return n


def hidden(now: float | None = None) -> dict:
    """`{key: row}` for what is hidden right now: every ignore, and every
    snooze whose date has not come round."""
    now = time.time() if now is None else now
    return {k: v for k, v in _read().items()
            if v["how"] in ("ignored", "listed") or v["until"] > now}


def is_hidden(key: str, now: float | None = None) -> bool:
    return str(key) in hidden(now)


def hide(key: str, how: str, title: str = "",
         now: float | None = None) -> dict | None:
    """Snooze or ignore one card. None for a key or a word this refuses."""
    now = time.time() if now is None else now
    if not KEY_RE.match(str(key or "")) or how not in HOWS:
        return None
    rows = {k: v for k, v in _read().items()
            if v["how"] in ("ignored", "listed") or v["until"] > now}
    row = {"how": how, "at": int(now),
           "until": int(now + SNOOZE_S) if how == "snoozed" else 0,
           "title": " ".join(str(title or "").split())[:TITLE_MAX]}
    rows[str(key)] = row
    _write(rows)
    return {"key": key, **row}


def restore(key: str) -> bool:
    """Put one back. False when nothing was hidden under it."""
    rows = _read()
    if str(key) not in rows:
        return False
    rows.pop(str(key))
    _write(rows)
    return True


def tidy_key(proposal: dict | None) -> str:
    """The key a pending tidy table is snoozed or ignored under — its own
    stamp, so the next table is a different card."""
    at = int((proposal or {}).get("at") or 0)
    return f"tidy:{at}" if at else ""


def update_key(update: dict | None) -> str:
    u = update or {}
    eid = re.sub(r"[^A-Za-z0-9_.]", "", str(u.get("entity_id") or ""))
    ver = re.sub(r"[^A-Za-z0-9_.\-]", "", str(u.get("latest") or ""))
    return f"update:{eid}:{ver}"[:170] if eid else ""


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

_SPACE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACE.sub(" ", str(text or "").strip().lower())


def _day(ts: int) -> str:
    """'4 Oct' — a date with no year, for a line about something recent."""
    if not ts:
        return ""
    t = time.localtime(int(ts))
    return f"{t.tm_mday} {time.strftime('%b', t)}"


def _weekday(ts: int, now: float) -> str:
    """'Wed' inside a week, '12 Oct' past it: the snooze's own words."""
    if not ts:
        return ""
    if ts - now < 6 * 86400:
        return time.strftime("%a", time.localtime(int(ts)))
    return _day(ts)


def _press(label: str, route: str, body: dict | None = None,
           confirm: str = "") -> dict:
    out = {"label": label, "route": route, "body": body or {}}
    if confirm:
        out["confirm"] = confirm
    return out


def history(*, findings: list[dict], settled: list[dict], muted: list[dict],
            snoozed_cases: list[dict], todo_done: list[dict],
            tidy_batches: list[dict], hidden_rows: dict | None = None,
            cleared: dict | None = None,
            now: float | None = None) -> dict:
    """The drawer's four filters, each a list of grouped one-line rows.

    Every argument is a list the panel already serves somewhere: the
    findings store's rows (for the held ones), the settled ledger, the
    muted producers, the snoozed cases (`cases.list_cases("snoozed")` over
    every store), the finished chores, the tidy batches still undoable and
    this module's own hidden cards.
    """
    now = time.time() if now is None else now
    cleared = _read_cleared() if cleared is None else cleared
    raw: dict[str, list[dict]] = {f: [] for f in FILTERS}

    for case in snoozed_cases or []:
        until = int(case.get("snoozed_until") or 0)
        raw["snoozed"].append({
            "title": case.get("claim") or "",
            "meta": f"Snoozed until {_weekday(until, now)}" if until else "Snoozed",
            "at": int(case.get("created_at") or 0),
            "press": _press("Restore", f"/api/case/{case.get('id')}/wake"),
        })
    for key, row in (hidden_rows or {}).items():
        if row["how"] == "listed":
            continue
        target = "snoozed" if row["how"] == "snoozed" else "ignored"
        meta = (f"Snoozed until {_weekday(row['until'], now)}"
                if target == "snoozed" else "Ignored")
        raw[target].append({
            "title": row.get("title") or key.split(":", 1)[0].title(),
            "meta": meta, "at": int(row.get("at") or 0),
            "press": _press("Restore", "/api/today/restore", {"key": key}),
        })

    for entry in settled or []:
        kind = entry.get("kind")
        if kind not in ("ignored", "fixed"):
            # `accepted` is on Your list already; History would be the same
            # card in two places.
            continue
        when = int(entry.get("ts") or 0)
        note = str(entry.get("note") or "").strip()
        meta = ("Ignored " if kind == "ignored" else "Done ") + _day(when)
        if note:
            meta += f" · You said: {note}"
        raw["ignored" if kind == "ignored" else "done"].append({
            "title": entry.get("text") or "",
            "meta": meta.strip(), "at": when,
            "press": _press("Restore", "/api/findings/unsettle",
                            {"key": entry.get("key") or ""}),
        })
    for row in muted or []:
        raw["ignored"].append({
            "title": f"Everything like this: {row.get('title') or row.get('source')}",
            "meta": "Ignored · not raised at all", "at": 0,
            "press": _press("Restore", "/api/findings/unmute",
                            {"source": row.get("source") or ""}),
        })

    for item in todo_done or []:
        when = int(item.get("done_at") or 0)
        raw["done"].append({
            "title": item.get("text") or "",
            "meta": f"Done {_day(when)}".strip(), "at": when,
            "press": _press("Restore", f"/api/todo/{item.get('id')}/reopen"),
        })
    for batch in tidy_batches or []:
        n = len(batch.get("entries") or [])
        when = int(batch.get("at") or 0)
        raw["done"].append({
            "title": f"Tidied {n} name{'s' if n != 1 else ''} and rooms",
            "meta": f"Applied {_day(when)}".strip(), "at": when,
            # Undo, and the sentence that says what it puts back: that text
            # is safety-critical and travels with the press.
            "press": _press("Undo", f"/api/tidy/undo/{batch.get('id')}",
                            confirm="Puts back each field that still holds "
                                    "what brAIn wrote. A field you changed "
                                    "since is left alone."),
        })

    for f in findings or []:
        if f.get("status") != "held":
            continue
        reason = str(((f.get("triage") or {}).get("reason")) or "").strip()
        when = int(((f.get("triage") or {}).get("at")) or f.get("ts") or 0)
        meta = f"Set aside {_day(when)}".strip()
        if reason:
            # A reason stored before the stores clipped on a word boundary
            # was a bare slice ("Every sensor it builds t"). Saying it was
            # shortened is the honest repair for a row nobody will rewrite.
            if reason[-1] not in ".!?…)\"'”’":
                reason = reason.rstrip(" ,;:-–—") + "…"
            meta += f" · {reason}"
        raw["aside"].append({
            "title": f.get("text") or "",
            "meta": meta, "at": when,
            "press": _press("Restore", f"/api/finding/{f.get('ts')}/elevate"),
        })

    out: dict[str, list[dict]] = {}
    for name in FILTERS:
        groups: dict[str, dict] = {}
        for row in raw[name]:
            key = _norm(row["title"])
            if not key:
                continue
            g = groups.get(key)
            if g is None:
                groups[key] = {"title": row["title"], "meta": row["meta"],
                               "at": row["at"], "since": row["at"],
                               "count": 1, "presses": [row["press"]]}
                continue
            g["count"] += 1
            g["presses"].append(row["press"])
            if row["at"] and (not g["since"] or row["at"] < g["since"]):
                g["since"] = row["at"]
            if row["at"] > g["at"]:
                g["at"], g["meta"] = row["at"], row["meta"]
        rows = []
        for key, g in groups.items():
            g["id"] = f"{name}|{key}"[:210]
            if g["id"] in cleared and cleared[g["id"]] >= g["at"]:
                continue
            g["deletable"] = name != "snoozed"
            rows.append(g)
        rows.sort(key=lambda g: g["at"], reverse=True)
        for g in rows:
            if g["count"] > 1:
                g["meta"] = (f"{g['count']} times since {_day(g['since'])}"
                             if g["since"] else f"{g['count']} times")
            label = g["presses"][0]["label"]
            g["press"] = {"label": label, "steps": g.pop("presses")}
        out[name] = rows[:MAX_ROWS]
    return {
        "filters": [{"id": f, "label": FILTER_LABELS[f],
                     "count": len(out[f])} for f in FILTERS],
        "rows": out,
    }


__all__ = ["FILTERS", "FILTER_LABELS", "HIDDEN_FILE", "KEY_RE", "SNOOZE_S",
           "clear", "hidden", "hide", "history", "is_hidden", "restore", "tidy_key",
           "update_key"]
