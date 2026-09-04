"""Findings — the things brAIn thinks are broken, and what it did about them.

Memory answers "what is true of this home". A hypothesis answers "am I right
about this home". A **finding** is the third thing neither of those covers:
something that is *wrong* and has an owner. A battery that died, a sensor
that stopped reporting, an automation that can never fire, an entity whose
name means nothing to anyone.

The lifecycle is deliberately short, because a list of problems nobody ever
settles is just a second inbox:

  open ──fix──▶ fixing ──▶ fixed       brAIn made the change; you haven't
                       │               read what it did yet
                       ├─▶ failed      it tried and couldn't
                       └─▶ needs_you   only a human can (replace the battery)
       ──"I've handled it"───▶ settled: you fixed it yourself
       ──"Wrong"─────────────▶ settled: it isn't a problem here, and here is
                                        why — in the homeowner's own words
  fixed ──"Got it"────────────▶ settled: you have seen what brAIn changed

**A finding leaves the list when a person ends it, and then it is gone.**
Every ending is a press, and every press deletes the row — there is no
archive of dismissed cards to scroll past, because a list of things nobody
has to look at again is exactly the clutter this tab exists to avoid. Note
that `fixed` is therefore still *live*: brAIn changing something in your
house is news, and news you have not read is not settled.

What survives an ending is the answer, not the row. It goes two places: a
plain line in `memory.md` (this is now true of the home) and a normalised
key in the settled ledger, which is what stops the analyst reporting the
same thing at you next week. The ledger is an index, never a queue —
nothing is swept out of it, because sweeping it is how a problem you
already answered comes back.

**"Wrong" carries a reason, and the reason is the valuable half.** A key
suppresses one wording; "that sensor always reads on, it isn't stuck" tells
the analyst why a whole shape of report is noise in this home, and it is
the difference between a list that gets quieter and one that keeps making
the same mistake in new words. The note rides along on the ledger entry —
there is no second store for it, because a correction with no report to
correct is not a thing anybody wrote — and ``prompt_block`` renders it
under the finding it belongs to. It is not an instruction and is not
phrased as one: the model is handed what the homeowner said and left to
work out what follows from it.

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

import atomic_write

import functools
import json
import logging
import os
import re
import threading
import time
import unicodedata
from pathlib import Path

log = logging.getLogger("brain.findings")

FINDINGS_FILE = Path(os.environ.get("BRAIN_FINDINGS_FILE", "/data/findings.json"))
# Where `brain learn` (and anything else on the CLI side) leaves findings it
# discovered. Same hand-off shape as the memory inbox: append-only JSONL on
# the shared volume, swept by whoever reads next.
INBOX_DIR = Path(os.environ.get(
    "BRAIN_FINDINGS_INBOX", "/config/.brain/findings/inbox"))
# The answers, kept after the rows are gone. Not the findings file, because
# this one is an index that is never swept — see settle_and_clear.
SETTLED_FILE = Path(os.environ.get(
    "BRAIN_FINDINGS_SETTLED", "/data/findings-settled.json"))
# A compact mirror on the shared volume, for the HA integration. The store
# itself lives in /data, which Home Assistant cannot see — so a critical
# finding discovered at 3am was invisible until somebody opened the panel.
# This file is what the integration's sensor reads and its event watcher
# diffs; it is derived, never read back, and republished on every write.
STATE_FILE = Path(os.environ.get(
    "BRAIN_FINDINGS_STATE", "/config/.brain/findings_state.json"))
# Plenty for a sensor attribute; the panel remains the place to work a list.
STATE_MAX_ROWS = 50
# Per-row cap on the prose in the mirror. See `_publish_state`.
STATE_MAX_PROSE = 240

MAX_FINDINGS = 200
# Far more than the list, because it is one short line each and losing the
# oldest entry is how a problem you answered in spring comes back in autumn.
MAX_SETTLED = 1000
MAX_TEXT = 200
MAX_DETAIL = 600
MAX_FIX = 600
MAX_RESULT = 1500
MAX_CHANGED = 8
# A correction is a sentence, not an essay. Long enough for "that sensor
# always reads on because it watches the fridge compressor", short enough
# that twenty of them still fit in a prompt beside everything else.
MAX_NOTE = 400

SEVERITIES = ("info", "warning", "serious", "critical")
STATUSES = ("open", "fixing", "fixed", "failed", "needs_you", "ignored")
# Statuses that still want the homeowner's attention on the Findings tab.
# `fixed` is in here: an automated fix changed something in the house, and
# that stays on the list until somebody has read what it did.
LIVE_STATUSES = ("open", "fixing", "fixed", "failed", "needs_you")
# ...and the subset the tab badge counts: a fix already running isn't a
# decision anyone has to make.
UNSETTLED_STATUSES = ("open", "fixed", "failed", "needs_you")

# What goes back into the analyst's prompt. Ignored findings are the point of
# the block — capped so it can never grow into a wall.
PROMPT_OPEN = 12
PROMPT_IGNORED = 20
PROMPT_FIXED = 20

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

# atomic_write makes each individual write atomic; it does nothing for the
# read-modify-write around it. The panel mutates this store from the event
# loop (add_many in _generate, set_status in _run_fix) *and* from request
# threads (the verb handlers run under asyncio.to_thread), so two operations
# could both _load, both mutate, and the last _write wins — a fresh finding
# silently vanishing under a user's "Wrong", or the reverse. Every mutator
# holds this lock across its whole load→mutate→write; an RLock because
# settle_and_clear writes both files through nested helpers.
_LOCK = threading.RLock()


def _mutates(fn):
    """One store operation at a time, whole, whichever thread asks."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return wrapped


def _load() -> list[dict]:
    try:
        data = json.loads(FINDINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("findings") if isinstance(data, dict) else None
    return [f for f in items if isinstance(f, dict)] if isinstance(items, list) else []


def _write(items: list[dict]) -> None:
    atomic_write.write_json(FINDINGS_FILE, {"findings": items})
    # Every write republishes the shared-volume mirror, so the two can never
    # drift: there is no code path that changes the store without it.
    _publish_state(items)


def _publish_state(items: list[dict]) -> None:
    """Mirror a summary of the live list onto the shared volume.

    Best-effort by design, with the failure logged rather than raised: the
    mirror is how Home Assistant *sees* findings, but a read-only /config
    must not be able to lose the finding itself, which is already safe in
    /data by the time this runs.

    Skipped entirely when the shared volume's parent directory does not
    exist — that is a dev checkout or a test, not a broken install, and
    creating a stray /config on somebody's laptop would be worse than
    skipping.
    """
    if not STATE_FILE.parent.parent.is_dir():
        return
    now = time.time()
    shaped = [s for s in (_shape(e) for e in items) if s["text"]]
    shaped.sort(key=lambda f: f["ts"], reverse=True)
    live = [s for s in shaped
            if s["status"] in LIVE_STATUSES and not is_snoozed(s, now)]
    open_rows = [s for s in live if s["status"] in UNSETTLED_STATUSES]
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(STATE_FILE, {
            "ts": int(now),
            "open": len(open_rows),
            "by_severity": {sev: len([s for s in open_rows
                                      if s["severity"] == sev])
                            for sev in SEVERITIES},
            "findings": [
                # `detail` and `fix` are cut harder here than in the
                # store: this file is a summary Home Assistant reads on
                # a timer, the panel holds the full text, and a to-do
                # item's description is read on a phone before deciding
                # whether to get up. Fifty rows of 600 characters each
                # would be 60 KB of mirror for two paragraphs nobody
                # scrolls to the end of.
                {**{k: s[k] for k in ("ts", "text", "severity", "status",
                                      "entity_id", "fixable", "source_title")},
                 "detail": s["detail"][:STATE_MAX_PROSE],
                 "fix": s["fix"][:STATE_MAX_PROSE]}
                for s in live[:STATE_MAX_ROWS]
            ],
        })
    except OSError as exc:
        log.warning("could not publish findings state to %s: %s",
                    STATE_FILE, exc)


@_mutates
def publish_state() -> None:
    """Republish the mirror from the store as it stands.

    Called at startup so the integration has a current file to read even
    when nothing has changed since the last boot — the alternative is a
    sensor reporting last week until the first new finding lands.
    """
    _publish_state(_load())


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
        # "Not now" is not a decision, so it is not a status. Dismissing is
        # permanent and is fed back into every future analysis; snoozing has
        # to leave the finding exactly as open as it was and just stop it
        # asking. A separate field is the only way to keep those apart.
        "snoozed_until": int(entry.get("snoozed_until") or 0),
    }


# ---------------------------------------------------------------------------
# Inbox sweep (study sessions and other CLI-side producers)
# ---------------------------------------------------------------------------

@_mutates
def sweep_inbox() -> list[dict]:
    """Fold `/config/.brain/findings/inbox/*.jsonl` into the store.

    Same contract as the memory inbox: append-only JSONL, one JSON object
    per line, consumed once. A torn or unparseable line is skipped rather
    than taking the whole file down — a study session that dies mid-write
    must not be able to wedge the Findings tab.

    Returns the findings that were actually NEW — the callers that log a
    count take a len(), and the notify hook needs the entries themselves,
    because "3 findings arrived" is not a message anyone can act on.
    """
    try:
        files = sorted(INBOX_DIR.glob("*.jsonl"))
    except OSError:
        return []
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
    added = add_many(pending)
    for path in swept:
        try:
            path.unlink()
        except OSError:
            # The findings are already filed. An inbox file that will not delete is
            # swept again next pass and deduped by the settled ledger.
            pass
    return added


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def is_snoozed(shaped: dict, now: float | None = None) -> bool:
    """Waiting for its time to come back round."""
    until = shaped.get("snoozed_until") or 0
    return bool(until) and until > (now if now is not None else time.time())


def _matches(shaped: dict, status: str | None) -> bool:
    if status is None:
        return True
    if status == "snoozed":
        return is_snoozed(shaped)
    if status == "live":
        # A snoozed finding is still live — it is just not asking yet, so it
        # stays out of the list you are being shown until it is due.
        return shaped["status"] in LIVE_STATUSES and not is_snoozed(shaped)
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
    now = time.time()
    return {
        "findings": shaped,
        "open": len([f for f in shaped
                     if f["status"] in UNSETTLED_STATUSES
                     and not is_snoozed(f, now)]),
        "snoozed": len([f for f in shaped if is_snoozed(f, now)]),
        # The answers, so the tab can show what it has stopped asking about.
        # Same read, same reply: a second endpoint for it would be a second
        # thing to keep in step with every button that settles something.
        "settled": settled_listing(),
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
    now = time.time()
    return len([e for e in _load()
                if e.get("status", "open") in UNSETTLED_STATUSES
                and str(e.get("text") or "").strip()
                and not (e.get("snoozed_until") or 0) > now])


def is_known(text: str) -> bool:
    """True when this finding has been reported before in ANY status.

    Reads the settled ledger as well as the list, because settling now
    deletes the row: without the ledger, "you already dealt with this"
    would last exactly as long as the card did.
    """
    key = normalize(text)
    if not key:
        return True
    if any(normalize(f.get("text", "")) == key for f in _load()):
        return True
    return any(e.get("key") == key for e in _load_settled())


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


@_mutates
def add_many(objs: list[dict]) -> list[dict]:
    """Record a batch of wire-shaped findings in ONE read and ONE write.

    Returns only the ones that were new — already-known findings are dropped
    silently, in any status, which is what makes a dismissal permanent.

    "Known" spans the settled ledger as well as the list. It has to: settling
    now deletes the row, so deduping against the list alone would make every
    ending behave like Forget, and the analyst would re-report next week the
    thing you answered today.
    """
    items = _load()
    seen = {normalize(f.get("text", "")) for f in items}
    seen |= {str(e.get("key") or "") for e in _load_settled()}
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


@_mutates
def add(text: str, **fields) -> tuple[dict | None, bool]:
    """Record one finding. Returns (entry, created); an already-known finding
    returns the existing entry untouched, whatever status it now holds.

    A finding that was settled has no entry left to return, so it comes back
    as (None, False): nothing to show, and nothing created.
    """
    entry = coerce({"text": text, **fields})
    if entry is None:
        return None, False
    key = normalize(entry["text"])
    for existing in _load():
        if normalize(existing.get("text", "")) == key:
            return _shape(existing), False
    created = add_many([{"text": text, **fields}])
    return (created[0], True) if created else (None, False)


@_mutates
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


@_mutates
def snooze(ts: int, until: int) -> dict | None:
    """Take a finding off the list until ``until`` (epoch seconds).

    Deliberately does NOT touch the status. "Remind me later" and "not a
    problem" are different answers — the second is permanent and teaches
    the analyst never to raise it again, and using it for the first would
    quietly throw away a real problem you meant to come back to.

    ``until <= 0`` brings it back now.
    """
    items = _load()
    for entry in items:
        if int(entry.get("ts") or 0) != ts:
            continue
        entry["snoozed_until"] = max(0, int(until))
        _write(items)
        return _shape(entry)
    return None


@_mutates
def settle_and_clear(ts: int, kind: str, note: str = "") -> dict | None:
    """Finish with a finding: remember the answer, drop the row.

    A settled finding used to sit in the list for good — the tab filled up
    with things nobody had to look at again, and "dismissed" and "fixed"
    read as two kinds of clutter rather than two different answers.

    What has to survive is not the row, it is the ANSWER: that this was
    dealt with, or that it is not a problem in this home. Both of those are
    facts about the house, so they go where facts about the house go (the
    caller writes them into memory), and the record kept here is the small
    thing the analyst needs — a normalised key, so the same problem is never
    reported at you twice.

    That is the same shape as the facts ledger: an index, not a queue.
    Nothing is deleted from it, because deleting is exactly how something
    you already answered comes back.

    ``note`` is the homeowner's reason, kept verbatim on the ledger entry so
    the analyst reads why rather than only what.
    """
    if kind not in ("fixed", "ignored"):
        raise ValueError(f"unknown settlement: {kind}")
    items = _load()
    settled = None
    kept = []
    for entry in items:
        if int(entry.get("ts") or 0) == ts:
            settled = _shape(entry)
            continue
        kept.append(entry)
    if settled is None:
        return None
    _write(kept)
    _remember_settled(settled, kind, note=note)
    settled["note"] = str(note or "").strip()[:MAX_NOTE]
    return settled


def _remember_settled(shaped: dict, kind: str, when: int = 0,
                      note: str = "") -> None:
    ledger = _load_settled()
    key = normalize(shaped["text"])
    ledger = [e for e in ledger if e.get("key") != key]
    ledger.append({
        "key": key,
        "text": shaped["text"],
        "kind": kind,
        "ts": when or int(time.time()),
        "note": str(note or "").strip()[:MAX_NOTE],
        # Who raised it. An ending is a label — "I did it" says the report
        # was right, "Wrong" says it was not — and without the producer on
        # the entry nothing can add those labels up per producer. That sum
        # is the scorecard, and the scorecard is what says which check or
        # which card is worth trusting in this house.
        "source": str(shaped.get("source") or "")[:64],
        "source_title": str(shaped.get("source_title") or "")[:120],
    })
    _write_settled(ledger[-MAX_SETTLED:])


def _load_settled() -> list[dict]:
    try:
        data = json.loads(SETTLED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("settled") if isinstance(data, dict) else None
    return [e for e in items if isinstance(e, dict)] if isinstance(items, list) else []


def _write_settled(items: list[dict]) -> None:
    atomic_write.write_json(SETTLED_FILE, {"settled": items})


def scorecard() -> list[dict]:
    """How right each producer has been, from the endings people gave.

    ``[{source, title, confirmed, wrong, total}, ...]``, most-settled first.
    "I did it" and "Got it" after a fix count as confirmed; "Wrong" counts
    as wrong. Snoozes and open rows count as nothing — a decision not yet
    made is not a label. Only settled entries that recorded a producer
    take part, so a ledger from before that field existed simply scores
    nothing rather than scoring everything as one anonymous producer.
    """
    by: dict[str, dict] = {}
    for e in _load_settled():
        src = str(e.get("source") or "")
        if not src:
            continue
        row = by.setdefault(src, {
            "source": src, "title": str(e.get("source_title") or src),
            "confirmed": 0, "wrong": 0})
        if e.get("kind") == "fixed":
            row["confirmed"] += 1
        elif e.get("kind") == "ignored":
            row["wrong"] += 1
    rows = list(by.values())
    for r in rows:
        r["total"] = r["confirmed"] + r["wrong"]
    rows.sort(key=lambda r: (-r["total"], r["source"]))
    return rows


def settled_listing() -> list[dict]:
    """What has been answered, newest first — for the Settled filter."""
    return sorted(_load_settled(), key=lambda e: e.get("ts") or 0, reverse=True)


@_mutates
def unsettle(key: str) -> bool:
    """Put an answered problem back in play.

    Drops it from the ledger, which is the one thing that ever removes an
    entry — and it is a deliberate act by the person it was hidden from,
    which is the only reason good enough.
    """
    ledger = _load_settled()
    kept = [e for e in ledger if e.get("key") != key]
    if len(kept) == len(ledger):
        return False
    _write_settled(kept)
    return True


@_mutates
def merge_rows(rows: list[dict]) -> int:
    """Fold another install's exported findings in — for `brain memory
    import`. Unlike add_many this preserves each row's lifecycle (status,
    result, snooze, settled_at): a migration is moving live work, not
    re-reporting it. Known texts are skipped in any status, and the settled
    ledger still wins — an answer given on THIS install is never undone by
    a row imported from another one."""
    items = _load()
    seen = {normalize(f.get("text", "")) for f in items}
    seen |= {str(e.get("key") or "") for e in _load_settled()}
    used = {int(f.get("ts") or 0) for f in items}
    added = 0
    for row in rows:
        entry = coerce(row)
        if entry is None or normalize(entry["text"]) in seen:
            continue
        status = row.get("status")
        entry["status"] = status if status in STATUSES else "open"
        entry["result"] = str(row.get("result") or "")[:MAX_RESULT]
        entry["changed"] = _clean_changed(row.get("changed"))
        entry["settled_at"] = int(row.get("settled_at") or 0)
        entry["snoozed_until"] = int(row.get("snoozed_until") or 0)
        # The original ts is the id everything exported alongside it refers
        # to, so it is kept where it is free; a collision gets a fresh one.
        ts = int(row.get("ts") or 0)
        entry["ts"] = ts if ts > 0 and ts not in used else _unique_ts(used)
        used.add(entry["ts"])
        seen.add(normalize(entry["text"]))
        items.append(entry)
        added += 1
    if added:
        _write(_prune(items))
    return added


@_mutates
def merge_settled(entries: list[dict]) -> int:
    """Fold another install's settled ledger in — existing entries win.

    The ledger is what stops the analyst re-reporting an answered problem,
    so a migration that dropped it would replay every dismissal the old
    install had already bought off.
    """
    ledger = _load_settled()
    known = {str(e.get("key") or "") for e in ledger}
    added = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = normalize(str(entry.get("key") or entry.get("text") or ""))
        if not key or key in known:
            continue
        kind = entry.get("kind")
        ledger.append({
            "key": key,
            "text": str(entry.get("text") or "")[:MAX_TEXT],
            "kind": kind if kind in ("fixed", "ignored") else "ignored",
            "ts": int(entry.get("ts") or 0) or int(time.time()),
            "note": str(entry.get("note") or "").strip()[:MAX_NOTE],
        })
        known.add(key)
        added += 1
    if added:
        _write_settled(ledger[-MAX_SETTLED:])
    return added


@_mutates
def migrate_settled() -> int:
    """Fold pre-ledger dismissals into the ledger and drop their rows.

    Before the ledger, "Not a problem" left the card in the list forever
    under a Dismissed filter. That filter is gone, so an upgrade would
    otherwise strand every one of those answers somewhere nobody can see —
    still suppressing the finding, with nothing on screen saying so. Run at
    startup; idempotent, because after the first pass there are no rows in
    that status left to move.

    `fixed` rows are deliberately left alone: they are live now, and the
    homeowner reads what brAIn changed and presses Got it.
    """
    items = _load()
    kept, moved = [], []
    for entry in items:
        if entry.get("status") == "ignored":
            moved.append(_shape(entry))
            continue
        kept.append(entry)
    for shaped in moved:
        _remember_settled(shaped, "ignored", when=shaped.get("settled_at") or 0)
    if moved:
        _write(kept)
    return len(moved)


@_mutates
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


# What the house checks may take back. A row somebody has sent Claude at,
# or that Claude has changed, is theirs to end — a check clears only what
# is still simply *open*.
CLEARABLE = ("open", "needs_you", "failed")


@_mutates
def refresh_details(objs: list[dict]) -> int:
    """Update the detail and severity of rows a producer has re-reported.

    A check's finding text is stable on purpose (the store dedupes by it),
    which leaves the number that changes — days left, since when — in
    ``detail``. Re-reporting through :func:`add_many` drops the row as
    known; this is the other half, so a battery forecast filed a week ago
    says "about 2 days" today rather than "about 9". Returns how many rows
    changed.
    """
    items = _load()
    by_key = {normalize(f.get("text", "")): f for f in items}
    changed = 0
    for obj in objs:
        entry = coerce(obj)
        if entry is None:
            continue
        cur = by_key.get(normalize(entry["text"]))
        if cur is None or cur.get("status") not in CLEARABLE:
            continue
        if (cur.get("detail") != entry["detail"]
                or cur.get("severity") != entry["severity"]):
            cur["detail"] = entry["detail"]
            cur["severity"] = entry["severity"]
            changed += 1
    if changed:
        _write(items)
    return changed


@_mutates
def clear_resolved(sources: set[str], keep_keys: set[str]) -> list[dict]:
    """Drop open rows a producer no longer reports.

    A device that came back, a battery that was changed, an automation
    that was fixed by hand without anyone pressing the button: the check
    that filed it stops finding it, and the row should go rather than sit
    on the list until somebody presses "I did it" about a thing that is
    fine. Only rows from ``sources`` (the checks that actually RAN this
    pass — a check whose data was missing must not clear anything) and
    only rows still in a clearable status.

    Nothing is written to the settled ledger and no memory line is
    queued: a problem that went away on its own is not a fact about the
    house, and if it comes back the check files it again. Returns the
    rows that were removed.
    """
    items = _load()
    kept: list[dict] = []
    gone: list[dict] = []
    for f in items:
        if (f.get("source") in sources
                and f.get("status") in CLEARABLE
                and normalize(f.get("text", "")) not in keep_keys):
            gone.append(_shape(f))
            continue
        kept.append(f)
    if gone:
        _write(kept)
    return gone


@_mutates
def remove(ts: int) -> bool:
    items = _load()
    kept = [f for f in items if int(f.get("ts") or 0) != ts]
    if len(kept) == len(items):
        return False
    _write(kept)
    return True


@_mutates
def restore(shaped: dict) -> dict | None:
    """Put a row back exactly as it was — the undo half of an ending.

    Keyed on the original ``ts``, because that is the id the panel acted on
    and a restored finding that came back under a new one would be a
    different card to everything holding a reference to it (the chat's
    action strip, a pending undo, an open menu).

    Refuses when something already occupies that id: the analyst re-reporting
    the problem in the meantime is the one case where the row on the list is
    newer than the one being restored, and overwriting it would throw away
    whatever has happened since.
    """
    ts = int(shaped.get("ts") or 0)
    if not ts or not str(shaped.get("text") or "").strip():
        return None
    items = _load()
    if any(int(f.get("ts") or 0) == ts for f in items):
        return None
    entry = {k: v for k, v in _shape(shaped).items()}
    items.append(entry)
    _write(_prune(items))
    return _shape(entry)


# ---------------------------------------------------------------------------
# Prompt injection
# ---------------------------------------------------------------------------

def prompt_block() -> str:
    """What the analyst needs to know about findings before it reports more.

    Three lists, all cheap and all load-bearing: what is already reported
    (so three cards don't all raise the same dead battery), what the
    homeowner has explicitly waved off (so it stays waved off), and what
    they have already dealt with (so a finished job is not handed back).

    The last two come from the settled ledger rather than the list, because
    settling deletes the row — plus any legacy row still carrying a settled
    status from before the ledger existed.

    Where a dismissal carries the homeowner's reason, the reason is rendered
    with it. That is the part worth the tokens: a key stops one wording, and
    "the porch sensor watches the compressor, it is meant to sit on" stops
    every report built on the same wrong assumption.
    """
    everything = list_all()
    live = [f for f in everything if f["status"] in LIVE_STATUSES][:PROMPT_OPEN]

    def _settled(kind: str, limit: int) -> list[tuple[str, str]]:
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for text, note in ([(e.get("text", ""), str(e.get("note") or ""))
                            for e in settled_listing() if e.get("kind") == kind]
                           + [(f["text"], "") for f in everything
                              if f["status"] == kind]):
            key = normalize(text)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append((text, note.strip()[:MAX_NOTE]))
            if len(out) >= limit:
                break
        return out

    ignored = _settled("ignored", PROMPT_IGNORED)
    fixed = _settled("fixed", PROMPT_FIXED)
    parts: list[str] = []
    if live:
        parts.append(
            "PROBLEMS ALREADY ON THE FINDINGS LIST — do NOT report these again:")
        parts += [f"- {f['text']}" for f in live]
    if ignored:
        parts.append(
            "\nPROBLEMS THE HOMEOWNER SAID WERE WRONG OR NOT PROBLEMS HERE — "
            "never raise them again, in any wording. Where they said why, that "
            "reason is about this house and holds beyond the one report: take "
            "it into account in what you look at next, rather than only "
            "avoiding these words:")
        parts += [f"- {t}" + (f"\n  They said: {n}" if n else "")
                  for t, n in ignored]
    if fixed:
        parts.append(
            "\nPROBLEMS THE HOMEOWNER HAS ALREADY DEALT WITH — do not raise "
            "them again unless the data shows they have come back:")
        parts += [f"- {t}" for t, _ in fixed]
    return "\n".join(parts)
