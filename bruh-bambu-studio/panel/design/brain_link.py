"""brAIn, reached the way BRight and Morph reach it: a file in its task folder.

brAIn's automation listener watches /config/.brain/tasks, claims a task by
RENAMING it, runs Claude, and writes /config/.brain/task_results/<id>.json
back: {id, result, status, data?, error?, session_id?}. A `conversation`
task resumes `session_id`, so one part is one conversation that can be
picked up days later — and, being unclaimed in brAIn's run ledger, it is
also the person's own conversation in brAIn's Chats.

The folder outlives the listener that made it, so a brAIn that is stopped
looks exactly like a working one until a wait runs out. A task nothing
claims within CLAIM_GRACE_S is reported as nothing listening, by name, with
the switch to turn on — never as brAIn being slow.

Optional by construction: with no brAIn the Design tab says why and the
rest of the add-on is untouched.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

BRAIN_SHARED = Path(os.environ.get("BAMBU_BRAIN_SHARED", "/config/.brain"))
CLAIM_GRACE_S = 30
POLL_S = 1.0


def tasks_dir() -> Path:
    return BRAIN_SHARED / "tasks"


def results_dir() -> Path:
    return BRAIN_SHARED / "task_results"


def status() -> dict:
    """{state: ok|off|missing, sentence}."""
    if not BRAIN_SHARED.is_dir():
        return {"state": "missing", "sentence": (
            "brAIn is not installed. Everything else in BRUH Bambu Studio works without it; "
            "install brAIn to design parts by talking to it.")}
    if not tasks_dir().is_dir():
        return {"state": "off", "sentence": (
            "brAIn is installed, but its Automation integration is off, so nothing picks up "
            "design requests. Turn on “Automation integration” in brAIn's configuration.")}
    return {"state": "ok", "sentence": "brAIn is connected."}


class NotListening(RuntimeError):
    """The task sat unclaimed: nothing is running brAIn's listener."""


def submit(prompt: str, *, schema: dict, session_id: str = "", timeout: int = 600) -> str:
    task_id = f"bambu-{uuid.uuid4().hex[:12]}"
    task = {"id": task_id, "prompt": prompt, "ts": int(time.time()),
            "timeout": int(timeout), "source": "bruh_bambu", "tools": "read_only",
            "schema": schema, "kind": "conversation", "person_words": ""}
    if session_id:
        task["session_id"] = str(session_id)[:80]
    folder = tasks_dir()
    scratch = folder / f".{task_id}.tmp"
    scratch.write_text(json.dumps(task), encoding="utf-8")
    scratch.replace(folder / f"{task_id}.json")
    return task_id


def wait(task_id: str, timeout: int) -> dict:
    """Block until brAIn answers; NotListening if nothing claims it."""
    task_file = tasks_dir() / f"{task_id}.json"
    result_file = results_dir() / f"{task_id}.json"
    start = time.time()
    while True:
        if result_file.exists():
            try:
                data = json.loads(result_file.read_text())
            except ValueError:
                time.sleep(POLL_S)  # caught mid-write; the next read gets it whole
                continue
            result_file.unlink(missing_ok=True)
            return data if isinstance(data, dict) else {}
        elapsed = time.time() - start
        if task_file.exists() and elapsed > CLAIM_GRACE_S:
            task_file.unlink(missing_ok=True)
            raise NotListening(
                "brAIn did not pick the request up. Is brAIn running with its "
                "Automation integration turned on?")
        if elapsed > timeout + 60:
            raise TimeoutError("brAIn did not answer in time.")
        time.sleep(POLL_S)
