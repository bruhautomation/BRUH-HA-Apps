"""⚙ › Dashboard's wire to Morph's service, in this same container.

Morph's Settings page was Morph's own until brAIn 4.0; its settings live in
brAIn's ⚙ now. The service (`brain/morph/service/morphd.py`) still owns the
files and answers requests through its folder, `/config/.morph/requests` →
`responses`, the contract the integration's `morph/request` uses, so there
is one way to ask it anything. Its state is the mirror it keeps,
`/config/.morph/state.json`.

Only the kinds ⚙ › Dashboard presses are let through (`KINDS`). A Tell, a
save from Edit and an answer to a suggestion are the dashboard's own and
come through the integration, where the person pressing them is.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import atomic_write

SHARED = Path(os.environ.get("BRAIN_MORPH_SHARED", "/config/.morph"))
FEED = Path(os.environ.get("BRAIN_MORPH_DIR", "/config/.brain/morph")) / "feed.json"
TIMEOUT_S = 30
POLL_S = 0.2

KINDS = ("settings", "history", "undo_commit", "restore", "learn_now", "lessons",
         "regenerate", "code_reset", "code_redo", "code_merge_all")


def _read(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def state() -> dict:
    """What ⚙ › Dashboard draws: the service's own mirror."""
    st = _read(SHARED / "state.json")
    keep = ("version", "at", "head", "settings", "brain", "learning", "devloop", "code", "note")
    out = {k: st[k] for k in keep if k in st}
    # Who lives here, for "whose device is this": the people brAIn already
    # publishes for Morph's salience (`morph_bridge.people_rows`).
    people = (_read(FEED).get("people") or {}) if FEED else {}
    out["people"] = [{"entity_id": eid, "name": str((row or {}).get("name") or eid)}
                     for eid, row in people.items() if isinstance(eid, str) and eid.startswith("person.")]
    return out


def request(kind: str, payload: dict | None = None, *, timeout: float = TIMEOUT_S) -> dict:
    """Ask the service and wait for its answer. Blocking: call it off the
    loop. Never raises; a service that does not answer is said."""
    if kind not in KINDS:
        return {"ok": False, "error": f"Not a dashboard setting: {kind}"}
    if not SHARED.is_dir():
        return {"ok": False, "error": "The Morph dashboard has not started yet. Switch it on in ⚙ › Features."}
    rid = uuid.uuid4().hex
    req_dir, res_dir = SHARED / "requests", SHARED / "responses"
    try:
        req_dir.mkdir(parents=True, exist_ok=True)
        res_dir.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(req_dir / f"{rid}.json", {"id": rid, "kind": kind, "ts": time.time(),
                                                          "payload": payload or {}})
    except OSError as exc:
        return {"ok": False, "error": f"Could not ask the dashboard: {exc}"}
    answer = res_dir / f"{rid}.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if answer.exists():
            data = _read(answer)
            try:
                answer.unlink()
            except OSError:
                pass  # the service tidies its folder too
            return data or {"ok": False, "error": "The dashboard's answer could not be read."}
        time.sleep(POLL_S)
    try:
        (req_dir / f"{rid}.json").unlink()
    except OSError:
        pass  # taken after all; its late answer is dropped unread
    return {"ok": False, "error": "The dashboard's service did not answer. brAIn's log says why."}
