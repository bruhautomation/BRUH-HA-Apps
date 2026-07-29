"""Findings — the things BRain thinks are broken, and what it did about them.

Memory answers "what is true of this home". A hypothesis answers "am I right
about this home". A **finding** is the third thing neither of those covers:
something that is *wrong* and has an owner. A battery that died, a sensor
that stopped reporting, an automation that can never fire, an entity whose
name means nothing to anyone.

The lifecycle is deliberately short, because a list of problems nobody ever
settles is just a second inbox:

  open ──fix──▶ fixing ──▶ fixed        BRain made the change
                       ──▶ failed       it tried and couldn't
                       ──▶ needs_you    only a human can (replace the battery)
       ──ignore────────▶ ignored        not a problem — never raise it again
       ──done──────────▶ fixed          you handled it yourself

`ignored` is the important one. It is never shown again *and* it is fed back
into the analyst's prompt, so "stop telling me about the garage freezer"
sticks across every future run rather than having to be re-dismissed weekly.

Two producers write here:

  * insight runs — the ``findings`` array of the generation contract, added
    through :func:`add` by the panel
  * study sessions — ``brain learn`` drops JSONL into
    ``/config/.brain/findings/inbox/``, which :func:`sweep_inbox` folds in

Deduplication is by normalized title across *every* status, so a finding
that was fixed or ignored in March cannot come back in April wearing
slightly different words.

Stdlib only, so the test suite can import it without the add-on runtime.
"""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
from pathlib import Path

FINDINGS_FILE = Path(os.environ.get("BRAIN_FINDINGS_FILE", "/data/findings.json"))
# Where `brain learn` (and anything else on the CLI side) leaves findings it
# discovered. Same hand-off shape as the memory inbox: append-only JSONL on
# the shared volume, swept by whoever reads next.
INBOX_DIR = Path(os.environ.get(
    "BRAIN_FINDINGS_INBOX", "/config/.brain/findings/inbox"))

MAX_FINDINGS = 200
MAX_TEXT = 200
MAX_DETAIL = 600
MAX_FIX = 600
MAX_RESULT = 1500
MAX_CHANGED = 8

SEVERITIES = ("info", "warning", "serious", "critical")
STATUSES = ("open", "fixing", "fixed", "failed", "needs_you", "ignored")
# Statuses that still want the homeowner's attention on the Findings tab.
LIVE_STATUSES = ("open", "fixing", "failed", "needs_you")
# ...and the subset the tab badge counts: a fix already running isn't a
# decision anyone has to make.
UNSETTLED_STATUSES = ("open", "failed", "needs_you")

# What goes back into the analyst's prompt. Ignored findings are the point of
# the block — capped so it can never grow into a wall.
PROMPT_OPEN = 12
PROMPT_IGNORED = 20

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]")


def normalize(text: str) -> str:
    """Case/punctuation-insensitive form used to dedupe findings."""
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _load() -> list[dict]:
    try:
        data = json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("findings") if isinstance(data, dict) else None
    return [f for f in items if isinstance(f, dict)] if isinstance(items, list) else []


def _write(items: list[dict]) -> None:
    FINDINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FINDINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"findings": items}, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(FINDINGS_FILE)


def _unique_ts(used: set[int]) -> int:
    """A timestamp no entry already holds — ts doubles as the id the panel
    acts on, and one insight run can report three findings in one second."""
    ts = int(time.time())
    while ts in used:
        ts += 1
    return ts


def _clean_changed(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:200])
        if len(out) >= MAX_CHANGED:
            break
    return out


def _shape(entry: dict) -> dict:
    """One stored finding, normalized for the API."""
    status = entry.get("status")
    if status not in STATUSES:
        status = "open"
    severity = entry.get("severity")
    if severity not in SEVERITIES:
        severity = "warning"
    return {
        "ts": int(entry.get("ts") or 0),
        "text": str(entry.get("text") or "")[:MAX_TEXT],
        "detail": str(entry.get("detail") or "")[:MAX_DETAIL],
        "fix": str(entry.get("fix") or "")[:MAX_FIX],
        "severity": severity,
        "fixable": bool(entry.get("fixable", True)),
        "entity_id": str(entry.get("entity_id") or "")[:255],
        "source": str(entry.get("source") or "")[:64],
        "source_title": str(entry.get("source_title") or "")[:120],
        "status": status,
        "result": str(entry.get("result") or "")[:MAX_RESULT],
        "changed": _clean_changed(entry.get("changed")),
        "settled_at": int(entry.get("settled_at") or 0),
    }


# ---------------------------------------------------------------------------
# Inbox sweep (study sessions and other CLI-side producers)
# ---------------------------------------------------------------------------

def sweep_inbox() -> int:
    """Fold `/config/.brain/findings/inbox/*.jsonl` into the store.

    Same contract as the memory inbox: append-only JSONL, one JSON object
    per line, consumed once. A torn or unparseable line is skipped rather
    than taking the whole file down — a study session that dies mid-write
    must not be able to wedge the Findings tab.
    """
    try:
        files = sorted(INBOX_DIR.glob("*.jsonl"))
    except OSError:
        return 0
    pending: list[dict] = []
    swept: list[Path] = []
    for path in files:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        swept.append(path)
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                pending.append(obj)
    # One write for the whole sweep, not one per finding: a study session
    # that files five would otherwise rewrite the store five times, which on
    # an SD card is five erase cycles for one batch of results.
    added = len(add_many(pending))
    for path in swept:
        try:
            path.unlink()
        except OSError:
            pass
    return added


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def _matches(shaped: dict, status: str | None) -> bool:
    if status is None:
        return True
    if status == "live":
        return shaped["status"] in LIVE_STATUSES
    return shaped["status"] == status


def list_all(status: str | None = None) -> list[dict]:
    """Stored findings, newest first. ``status`` may be one status or the
    sentinel ``"live"`` for everything still wanting attention."""
    out = [s for s in (_shape(e) for e in _load())
           if s["text"] and _matches(s, status)]
    out.sort(key=lambda f: f["ts"], reverse=True)
    return out


def listing() -> dict:
    """Everything the Findings tab needs, from ONE read of the file.

    The tab wants the list and the badge count together, and asking for
    them separately meant parsing (and fully shaping) the same file twice
    per request — on a Pi, for a screen that polls.
    """
    shaped = [s for s in (_shape(e) for e in _load()) if s["text"]]
    shaped.sort(key=lambda f: f["ts"], reverse=True)
    return {
        "findings": shaped,
        "open": len([f for f in shaped if f["status"] in UNSETTLED_STATUSES]),
    }


def get(ts: int) -> dict | None:
    for entry in _load():
        if int(entry.get("ts") or 0) == ts:
            return _shape(entry)
    return None


def open_count() -> int:
    """What the Findings tab badge shows: things you haven't settled.

    Counted straight off the raw entries: /api/status polls this every few
    seconds, and shaping 200 findings (slicing every detail, fix and result
    string) to then throw all of it away but the length is real work on a
    Raspberry Pi.
    """
    return len([e for e in _load()
                if e.get("status", "open") in UNSETTLED_STATUSES
                and str(e.get("text") or "").strip()])


def is_known(text: str) -> bool:
    """True when this finding has been reported before in ANY status.

    Includes settled ones on purpose: re-raising something you already
    ignored is exactly the behaviour the ignore button is meant to buy off.
    """
    key = normalize(text)
    if not key:
        return True
    return any(normalize(f.get("text", "")) == key for f in _load())


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

def coerce(obj: dict) -> dict | None:
    """One wire-shaped finding — from a model reply or an inbox line — turned
    into a stored entry, or None if there is nothing there.

    Both producers hand over the same loose shape, so both go through here:
    a second hand-written coercion is how the panel and the CLI drift on what
    "fixable" defaults to.
    """
    if not isinstance(obj, dict):
        return None
    text = str(obj.get("text") or obj.get("finding") or "").strip()[:MAX_TEXT]
    if not normalize(text):
        return None
    severity = str(obj.get("severity") or "").strip().lower()
    return {
        "text": text,
        "detail": str(obj.get("detail") or "").strip()[:MAX_DETAIL],
        "fix": str(obj.get("fix") or "").strip()[:MAX_FIX],
        "severity": severity if severity in SEVERITIES else "warning",
        # absent means fixable; only an explicit false means hands required
        "fixable": obj.get("fixable", True) is not False,
        "entity_id": str(obj.get("entity_id") or "").strip()[:255],
        "source": str(obj.get("source") or "").strip()[:64],
        "source_title": str(obj.get("source_title") or "").strip()[:120],
        "status": "open",
        "result": "",
        "changed": [],
        "settled_at": 0,
    }


def _prune(items: list[dict]) -> list[dict]:
    """Cap the store, dropping oldest SETTLED entries first: an open finding
    is live work, and losing it silently is how a real problem disappears
    without ever being fixed."""
    if len(items) <= MAX_FINDINGS:
        return items
    settled = [f for f in items if f.get("status") in ("fixed", "ignored")]
    settled.sort(key=lambda f: int(f.get("settled_at") or f.get("ts") or 0))
    drop = {id(f) for f in settled[:len(items) - MAX_FINDINGS]}
    return [f for f in items if id(f) not in drop][-MAX_FINDINGS:]


def add_many(objs: list[dict]) -> list[dict]:
    """Record a batch of wire-shaped findings in ONE read and ONE write.

    Returns only the ones that were new — already-known findings are dropped
    silently, in any status, which is what makes a dismissal permanent.
    """
    items = _load()
    seen = {normalize(f.get("text", "")) for f in items}
    used = {int(f.get("ts") or 0) for f in items}
    created = []
    for obj in objs:
        entry = coerce(obj)
        if entry is None or normalize(entry["text"]) in seen:
            continue
        entry["ts"] = _unique_ts(used)
        used.add(entry["ts"])
        seen.add(normalize(entry["text"]))
        items.append(entry)
        created.append(_shape(entry))
    if created:
        _write(_prune(items))
    return created


def add(text: str, **fields) -> tuple[dict | None, bool]:
    """Record one finding. Returns (entry, created); an already-known finding
    returns the existing entry untouched, whatever status it now holds."""
    entry = coerce({"text": text, **fields})
    if entry is None:
        return None, False
    key = normalize(entry["text"])
    for existing in _load():
        if normalize(existing.get("text", "")) == key:
            return _shape(existing), False
    created = add_many([{"text": text, **fields}])
    return (created[0], True) if created else (None, False)


def set_status(ts: int, status: str, result: str = "",
               changed: list[str] | None = None) -> dict | None:
    """Move a finding along its lifecycle. Unknown ids return None."""
    if status not in STATUSES:
        raise ValueError(f"unknown finding status: {status}")
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != ts:
            continue
        entry["status"] = status
        if result:
            entry["result"] = str(result)[:MAX_RESULT]
        if changed is not None:
            entry["changed"] = _clean_changed(changed)
        entry["settled_at"] = 0 if status in ("open", "fixing") else int(time.time())
        _write(items)
        return _shape(entry)
    return None


def reconcile_running(reason: str) -> int:
    """Demote findings left mid-fix by a process that is no longer running.

    "fixing" is claimed on disk but owned by an in-memory job, so a restart
    (an add-on update, a crash) orphans it: the row still says fixing, the
    job that would settle it is gone, and the tab offers no buttons in that
    status — the finding becomes permanently unreachable. Called at startup,
    which is the only moment we know for certain that nothing is in flight.
    """
    items = _load()
    stuck = [f for f in items if f.get("status") == "fixing"]
    for entry in stuck:
        entry["status"] = "failed"
        entry["result"] = reason
        entry["settled_at"] = int(time.time())
    if stuck:
        _write(items)
    return len(stuck)


def remove(ts: int) -> bool:
    items = _load()
    kept = [f for f in items if int(f.get("ts") or 0) != ts]
    if len(kept) == len(items):
        return False
    _write(kept)
    return True


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

def prompt_block() -> str:
    """What the analyst needs to know about findings before it reports more.

    Two lists, both cheap and both load-bearing: what is already reported
    (so three cards don't all raise the same dead battery) and what the
    homeowner has explicitly waved off (so it stays waved off).
    """
    everything = list_all()
    live = [f for f in everything if f["status"] in LIVE_STATUSES][:PROMPT_OPEN]
    ignored = [f for f in everything if f["status"] == "ignored"][:PROMPT_IGNORED]
    parts: list[str] = []
    if live:
        parts.append(
            "PROBLEMS ALREADY ON THE FINDINGS LIST — do NOT report these again:")
        parts += [f"- {f['text']}" for f in live]
    if ignored:
        parts.append(
            "\nPROBLEMS THE HOMEOWNER DISMISSED — they are not problems in this "
            "home. Never raise them again, in any wording:")
        parts += [f"- {f['text']}" for f in ignored]
    return "\n".join(parts)
