"""Reports the owner has put away, in ⚙ › Developer's list (report #167).

The development loop's queue (`devloop/upstream.py`) keeps every report it
ever filed, so the list under Help develop brAIn only grows. This is the
panel's own note of which rows somebody archived — a list of fingerprints
and nothing else — and it never touches the loop's files or GitHub: an
archived report is still filed, still sent, still read back hourly; it is
only off the default view.

One rule is automatic, and it is the loop's own claim rather than a guess:
a fault report the loop marked "no longer seen" (`cleared_noted`, which the
loop sets only after looking while its stream was on, and clears the moment
the fault is back) is archived while that is true, unless somebody pressed
Unarchive on it. A report with a verdict from the cloud keeps its verdict.

Never raises on a read: a file that cannot be read is an empty archive,
which shows every row — the direction in which being wrong costs a longer
list rather than a hidden report.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import atomic_write

STORE = os.environ.get("BRAIN_DEVLOOP_ARCHIVE", "/data/devloop-archive.json")
FP_RE = re.compile(r"^[0-9a-f]{16}$")  # `devloop.upstream.FP_RE`
# More than the queue can hold; a cap so the file cannot grow without end.
MAX_ROWS = 2000
_LOCK = threading.Lock()


def _empty() -> dict:
    return {"archived": {}, "kept": {}}


def load() -> dict:
    try:
        with open(STORE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    for key in out:
        part = data.get(key)
        if isinstance(part, dict):
            out[key] = {k: v for k, v in part.items()
                        if isinstance(k, str) and FP_RE.match(k)}
    return out


def set_archived(fps, archived: bool, now: float | None = None) -> int:
    """Archive (or unarchive) these fingerprints. Returns how many moved.

    Unarchiving remembers the press (`kept`), so the automatic rule does
    not put a row straight back the moment somebody took it out."""
    now = time.time() if now is None else now
    fps = [f for f in (fps or []) if isinstance(f, str) and FP_RE.match(f)]
    if not fps:
        return 0
    with _LOCK:
        data = load()
        moved = 0
        for fp in fps:
            if archived:
                data["kept"].pop(fp, None)
                if fp not in data["archived"]:
                    moved += 1
                data["archived"][fp] = int(now)
            else:
                if data["archived"].pop(fp, None) is not None:
                    moved += 1
                data["kept"][fp] = int(now)
        for key in ("archived", "kept"):
            if len(data[key]) > MAX_ROWS:
                newest = sorted(data[key].items(), key=lambda kv: kv[1])[-MAX_ROWS:]
                data[key] = dict(newest)
        atomic_write.write_json(STORE, data)
    return moved


def auto_archived(row: dict, faults_on: bool) -> bool:
    """A fault report the loop says has not been seen since, while it was
    looking — and with no verdict from the cloud to show instead."""
    verdict = row.get("verdict")
    return bool(faults_on and row.get("stream") == "faults"
                and row.get("state") == "sent" and row.get("cleared_noted")
                and verdict in (None, "", "open"))


def decorate(rows: list[dict], settings: dict | None,
             data: dict | None = None) -> list[dict]:
    """Each row with `archived` and `archived_why` ("you", "no longer
    seen", or ""). The rows are copied, never changed in place."""
    data = load() if data is None else data
    settings = settings or {}
    faults_on = bool(settings.get("enabled")
                     and (settings.get("streams") or {}).get("faults"))
    out = []
    for row in rows or []:
        row = dict(row)
        fp = row.get("fp") or ""
        if fp in data["archived"]:
            row["archived"], row["archived_why"] = True, "you"
        elif fp not in data["kept"] and auto_archived(row, faults_on):
            row["archived"], row["archived_why"] = True, "no longer seen"
        else:
            row["archived"], row["archived_why"] = False, ""
        out.append(row)
    return out
