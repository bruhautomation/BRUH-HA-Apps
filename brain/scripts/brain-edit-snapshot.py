#!/usr/bin/env python3
"""PreToolUse hook: snapshot a file before Claude overwrites it.

Registered against Write|Edit|NotebookEdit in /config/.claude/settings.local.json.
Claude Code pipes the tool call in as JSON on stdin; we copy the file's
CURRENT contents aside and append one line to an index, so `brain undo`
can put it back.

This is the narrow replacement for the old git auto-backup. It records
only what Claude itself touched — not the whole of /config — and it lives
under /data, so it never pollutes the config directory or the Supervisor's
own backups.

The hook must never block an edit: any failure here exits 0 silently. A
missing snapshot costs an undo, a raised exception would cost the edit.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

JOURNAL_DIR = Path(os.environ.get("BRAIN_EDIT_JOURNAL", "/data/.brain/edits"))
SNAP_DIR = JOURNAL_DIR / "snapshots"
INDEX = JOURNAL_DIR / "index.jsonl"

# Only /config is worth journalling — edits under /data or /tmp are the
# add-on's own scratch, and snapshotting them would balloon the journal.
WATCH_ROOTS = ("/config",)
# Never snapshot secrets, or files big enough to blow out the volume.
SKIP_NAMES = {"secrets.yaml"}
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_JOURNAL_BYTES = 256 * 1024 * 1024
RETAIN_DAYS = int(os.environ.get("BRAIN_EDIT_JOURNAL_DAYS", "14") or 14)


def watched(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    if resolved.name in SKIP_NAMES:
        return False
    return any(str(resolved).startswith(root) for root in WATCH_ROOTS)


def prune() -> None:
    """Drop snapshots past the retention window, then oldest-first while the
    journal is over its size cap."""
    if RETAIN_DAYS <= 0:
        return
    cutoff = time.time() - RETAIN_DAYS * 86400
    snaps = []
    for p in SNAP_DIR.glob("*"):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime < cutoff:
            p.unlink(missing_ok=True)
        else:
            snaps.append((st.st_mtime, st.st_size, p))

    total = sum(size for _, size, _ in snaps)
    for _, size, p in sorted(snaps):
        if total <= MAX_JOURNAL_BYTES:
            break
        p.unlink(missing_ok=True)
        total -= size


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    tool = str(payload.get("tool_name") or "")
    if tool not in ("Write", "Edit", "NotebookEdit", "MultiEdit"):
        return 0

    tool_input = payload.get("tool_input") or {}
    # NotebookEdit names its target notebook_path, not file_path — reading
    # only file_path meant notebook edits matched the hook and were never
    # snapshotted, so `brain undo` silently could not revert them.
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return 0
    path = Path(str(raw))
    if not watched(path):
        return 0

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.time()
    existed = path.is_file()
    snapshot = ""

    if existed:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                return 0
            digest = hashlib.sha256(str(path).encode()).hexdigest()[:10]
            snapshot = f"{int(ts)}-{digest}-{path.name}"
            shutil.copy2(path, SNAP_DIR / snapshot)
        except OSError:
            return 0

    entry = {
        "ts": ts,
        "path": str(path),
        "tool": tool,
        "snapshot": snapshot,
        # A brand-new file has nothing to restore — undo deletes it instead.
        "existed": existed,
    }
    try:
        with INDEX.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        return 0

    prune()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — a hook must never break the edit
        sys.exit(0)
