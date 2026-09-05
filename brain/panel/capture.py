"""Capture — what the analyst was sent, what it said, and what you made of it.

BRight's `detect_hits` is the lesson this file exists for. That function
returned **zero** results on every real track for its whole life, and the
suite was green throughout, because its only fixture was a synthetic stab
loud enough to clear a threshold no real mix reaches. brAIn's analyst
prompts have exactly the same exposure: `_CARD_CONTRACT` is 10 KB of
output rules shared by two prompt builders, and no test in this repository
runs it against a real house or a real model. A prompt edit ships on
somebody's judgement and is measured by nothing.

So: with `capture` switched on in ⚙, every card run writes one file — the
bundle the analyst was given, the card that came back, and later the
**ending** the person gave each finding it raised. That last part is the
half that matters. An ending on the Findings tab is already a label ("I
did it" says the report was right, "Wrong" says it was not); pairing it
with the prompt that produced it turns a house into a graded example, and
a directory of graded examples is a corpus a prompt change can be scored
against before it ships.

Five rules, and four of them are refusals.

**Off by default, and it says exactly what it records.** A house's entity
names are a floor plan. The design page's own "not building" list says
*any capture that is on by default*, and this is that line honoured: one
switch, one sentence under it, nothing recorded until somebody turns it
on.

**Nothing leaves the add-on until a person exports it.** These files live
in `/data`, which Home Assistant cannot see and a backup does not carry
(`backup_exclude` names the directory). `export` is a deliberate press
that copies one file to `/share/brain/corpus/`, where the file editor and
Samba can reach it — and that copy is the only route out.

**Redacted at write time, never at export time.** A redaction applied on
the way out is a redaction that never ran for the file somebody found by
another route. The rules are `brain-report.sh`'s, and
`tests/test_capture.py` drives the shell's `redact()` and this module's
against the same fixture strings, because two implementations of "what a
credential looks like" is one too many and the one nobody runs is the one
that drifts.

**Capped, oldest first.** `CAPTURE_MAX_FILES` runs, because this is a
sample and not an archive: fifty houses' worth of prompt is plenty to see
a contract drift, and an uncapped directory on an SD card is a different
bug report.

**A run id off the wire is not a filename.** `path_for` refuses anything
`safe_id` rejects *and* anything that does not normalise to a path under
the capture directory — the same deliberate redundancy
`chat_session.transcript_path` carries, spelled the same way, because a
guard a static analyser cannot follow is a guard somebody deletes.

Stdlib only, so the tests can drive it without the add-on runtime.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.capture")

CAPTURE_DIR = Path(os.environ.get("BRAIN_CAPTURE_DIR", "/data/capture"))
# Where an exported entry lands: the shared volume, because /data is
# invisible to Home Assistant and a file nobody can open is not reviewable.
EXPORT_DIR = Path(os.environ.get("BRAIN_CORPUS_DIR", "/share/brain/corpus"))

# A sample, not an archive.
CAPTURE_MAX_FILES = 50

# The entry format. `tests/corpus/schema.json` describes the same shape, so
# a change here is a change there — and the corpus validator is what fails
# if only one of them moves.
SCHEMA = 1

# The two kinds of corpus entry. A `checks` entry carries a house snapshot
# and the check ids that should fire on it, and is replayed with no model
# at all; an `analyst` entry carries a prompt bundle and a model's reply,
# and needs one. Capture only ever writes the second.
KINDS = ("analyst", "checks")

MAX_LABELS = 20
MAX_NOTE = 400

# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

# The same three shapes `brain-report.sh`'s `redact()` and `journal.scrub`
# look for, kept as one list so a fourth can only be added in one place.
_TEXT_RULES = (
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "[redacted]"),
    (re.compile(r"(Bearer[ =:]+)[A-Za-z0-9._\-]{8,}"), r"\1[redacted]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"
                r"\.[A-Za-z0-9_\-]{10,}"), "[redacted]"),
)

# The shell does this one textually, over `"token": "…"` in a JSON file.
# Here the object is still an object, so it is done structurally — which
# catches the same fields and cannot be fooled by whitespace. The names are
# the shell's, exactly.
SECRET_KEYS = frozenset((
    "access_token", "refresh_token", "token", "api_key", "oauth_token",
    "value",
))
# A short string under a secret-shaped key is a setting, not a credential
# ("value": "on"), and blanking it would make the entry unreadable for
# nothing. The shell's own rule is the same number.
SECRET_MIN = 8


def redact(value):
    """The same value with anything credential-shaped replaced.

    Walks dicts and lists, because a bundle is nested and a regex over a
    serialised copy would have to be re-applied every time anything
    re-serialised it. Applied on the way IN, once, so there is no path by
    which an unredacted capture exists on disk.
    """
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if (isinstance(key, str) and key.lower() in SECRET_KEYS
                    and isinstance(item, str) and len(item) >= SECRET_MIN):
                out[key] = "[redacted]"
                continue
            out[key] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for pattern, replacement in _TEXT_RULES:
            value = pattern.sub(replacement, value)
        return value
    return value


# ---------------------------------------------------------------------------
# Where an entry lives
# ---------------------------------------------------------------------------

_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-]{0,127}")


def safe_id(run_id: str) -> bool:
    """Whether this run id may be used as a filename."""
    return bool(run_id) and run_id not in (".", "..") \
        and bool(_SAFE_ID_RE.fullmatch(run_id))


def path_for(run_id: str, directory: Path | None = None):
    """Where one capture lives, or None for an id with no business being one.

    Two checks, and they are not redundant. `safe_id` is the rule — a run
    id is a session uuid, and anything that is not one names no run. The
    normalise-and-prefix check underneath is the same rule written where a
    person or a scanner can follow it to the `open()` at the end of it: the
    ids reaching here come off the wire, and a boolean regex several call
    frames away is not a barrier anything can see.
    """
    if not safe_id(run_id):
        return None
    base = os.path.normpath(os.path.abspath(
        str(CAPTURE_DIR if directory is None else directory)))
    candidate = os.path.normpath(os.path.join(base, f"{run_id}.json"))
    if not candidate.startswith(base + os.sep):
        return None
    return Path(candidate)


def run_id_from(meta: dict) -> str:
    """The id a capture is filed under, from an engine result's meta.

    Claude Code's own session id, which `engine._run_cli` mints and claims
    in `run_sources` *before* the run — so a capture, a journal line, a
    transcript and a Chats rail row all name the same run rather than four
    ids nothing can join. A CLI that returned none leaves an empty string
    and the run is simply not captured: a made-up id would file an entry
    nothing else in the add-on can point at.
    """
    session = str((meta or {}).get("session_id") or "")
    return session if safe_id(session) else ""


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def record(run_id: str, *, source: str, category: str = "",
           question: str = "", model: str = "", gather_mode: str = "",
           prompt_chars: int = 0, bundle=None, reply=None,
           tokens=None, now: float | None = None):
    """Write one capture. Returns its path, or None if it was not written.

    Never raises: a capture is a diagnostic, and a diagnostic that takes
    down the run it is capturing is worse than a missing file.
    """
    path = path_for(run_id)
    if path is None:
        return None
    entry = {
        "schema": SCHEMA,
        "kind": "analyst",
        "captured_at": int(time.time() if now is None else now),
        "run_id": run_id,
        "source": str(source or "")[:32],
        "category": str(category or "")[:64],
        "question": str(question or "")[:600],
        "model": str(model or "")[:64],
        "gather_mode": str(gather_mode or "")[:32],
        "prompt_chars": int(prompt_chars or 0),
        # What the analyst was given. Which shape this is depends on
        # `gather_mode`: the orientation MAP for a search run, the slimmed
        # entity bundle for a snapshot one. Both are "what it was sent",
        # and a replay rebuilds the prompt from whichever it finds.
        "bundle": redact(bundle if bundle is not None else {}),
        "reply": redact(reply if reply is not None else {}),
        "tokens": tokens or {},
        # Filled in later, by an ending on the Findings tab.
        "labels": [],
    }
    try:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(path, entry)
        prune()
    except OSError as exc:
        log.warning("could not write the capture for %s: %s", run_id, exc)
        return None
    return path


def prune(keep: int | None = None) -> int:
    """Drop the oldest captures past the cap. Returns how many went.

    Oldest by the file's own mtime rather than by the id, because a run id
    is a uuid and sorts by nothing; the name breaks a tie only so that two
    files written in the same clock tick are dropped in a defined order
    rather than an arbitrary one. A file that will not delete is left
    where it is and retried next time — a capture is not worth an
    exception.

    ``keep`` defaults to the module's cap read *at call time*, not bound
    at definition: a constant a test cannot move is a constant nothing
    can drive.
    """
    keep = CAPTURE_MAX_FILES if keep is None else keep
    try:
        files = sorted(CAPTURE_DIR.glob("*.json"),
                       key=lambda p: (p.stat().st_mtime, p.name))
    except OSError:
        return 0
    gone = 0
    for path in files[:max(0, len(files) - max(0, keep))]:
        try:
            path.unlink()
            gone += 1
        except OSError:
            # Already gone, or a read-only /data. Either way the cap is
            # a housekeeping rule, and the next pass tries again.
            pass
    return gone


def add_label(run_id: str, *, finding_key: str, verb: str, note: str = "",
              now: float | None = None) -> bool:
    """Record what a person decided about one finding this run raised.

    The label the whole file exists for. Best effort in every direction:
    an ending must never fail because a capture could not be updated, and
    a run that was not captured (the switch was off, the file has been
    pruned) simply has nothing to label.
    """
    path = path_for(run_id)
    if path is None:
        return False
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(entry, dict):
        return False
    labels = entry.get("labels")
    if not isinstance(labels, list):
        labels = []
    labels = [row for row in labels
              if isinstance(row, dict) and row.get("finding_key") != finding_key]
    labels.append({
        "finding_key": str(finding_key or "")[:200],
        "verb": str(verb or "")[:16],
        # A correction is the homeowner's own words about their house, so
        # it goes through the same redaction the rest of the entry did —
        # it is the one field here a person typed.
        "note": redact(str(note or "").strip()[:MAX_NOTE]),
        "ended_at": int(time.time() if now is None else now),
    })
    entry["labels"] = labels[-MAX_LABELS:]
    try:
        atomic_write.write_json(path, entry)
    except OSError as exc:
        log.debug("could not label the capture for %s: %s", run_id, exc)
        return False
    return True


# ---------------------------------------------------------------------------
# Reading, exporting, deleting
# ---------------------------------------------------------------------------

def _summary(path: Path, entry: dict) -> dict:
    reply = entry.get("reply") or {}
    findings = reply.get("findings") if isinstance(reply, dict) else None
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "run_id": str(entry.get("run_id") or path.stem),
        "captured_at": int(entry.get("captured_at") or 0),
        "source": str(entry.get("source") or ""),
        "category": str(entry.get("category") or ""),
        "question": str(entry.get("question") or ""),
        "model": str(entry.get("model") or ""),
        "gather_mode": str(entry.get("gather_mode") or ""),
        "findings": len(findings) if isinstance(findings, list) else 0,
        "labels": len(entry.get("labels") or []),
        "bytes": size,
    }


def listing() -> list[dict]:
    """One row per capture, newest first — the ⚙ Diagnostics list."""
    out: list[dict] = []
    try:
        files = list(CAPTURE_DIR.glob("*.json"))
    except OSError:
        return out
    for path in files:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(entry, dict):
            out.append(_summary(path, entry))
    out.sort(key=lambda r: r["captured_at"], reverse=True)
    return out


def read(run_id: str) -> dict | None:
    """One whole capture, as it is on disk — already redacted."""
    path = path_for(run_id)
    if path is None:
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def export(run_id: str) -> tuple[str, str]:
    """Copy one capture to the shared volume. Returns ``(path, error)``.

    The one route out of the add-on, and it is a press. The file is copied
    rather than moved: exporting is not deleting, and somebody who exports
    the wrong entry should still be able to delete it from the list they
    exported it from.
    """
    entry = read(run_id)
    if entry is None:
        return "", "there is no capture with that id"
    if not EXPORT_DIR.parent.parent.is_dir():
        # A dev checkout has no /share, and creating one on somebody's
        # laptop is worse than refusing — the same rule the findings
        # mirror follows.
        return "", f"{EXPORT_DIR.parent.parent} does not exist on this install"
    target = path_for(run_id, EXPORT_DIR)
    if target is None:
        return "", "that id cannot be a filename"
    try:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(target, entry)
    except OSError as exc:
        return "", f"could not write {target}: {exc}"
    return str(target), ""


def delete(run_id: str) -> bool:
    path = path_for(run_id)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def stats(enabled: bool = False) -> dict:
    """``{enabled, files, labelled, bytes}`` — what /api/diagnostics carries.

    Numbers only. The captures themselves are never in a diagnostics
    bundle: `brain report` is attached to a public issue, and a bundle
    is exactly the wrong route out for a file whose whole content is
    somebody's house.
    """
    rows = listing()
    return {
        "enabled": bool(enabled),
        "files": len(rows),
        "labelled": len([r for r in rows if r["labels"]]),
        "bytes": sum(r["bytes"] for r in rows),
        "max_files": CAPTURE_MAX_FILES,
    }
