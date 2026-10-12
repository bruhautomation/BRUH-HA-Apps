"""brAIn, reached the way BRight reaches it: a file in its task folder.

brAIn's automation listener watches ``/config/.brain/tasks``, claims a task
by RENAMING it, runs Claude Code in ``/config`` with its tools, and writes
``/config/.brain/task_results/<id>.json`` back: ``{id, result, status,
data?, error?}``. That is the whole contract, and it is the one
``brain.run_task`` and BRight's director already ride, so Morph adds no
second door into brAIn and asks for no second login.

What Morph adds is the HEALTH of that door, because the folder outlives the
listener that made it (`bright/panel/director_check.py` is the reason this
paragraph exists): a brAIn that is stopped looks exactly like a working one
until a wait expires. So a task that nothing claims within ``CLAIM_GRACE_S``
is reported as "nothing is listening", by name, with the switch to turn on —
never left to time out as if brAIn were merely slow.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import paths

CLAIM_GRACE_S = 30
POLL_S = 1.0


def tasks_dir() -> Path:
    return paths.BRAIN_SHARED / "tasks"


def results_dir() -> Path:
    return paths.BRAIN_SHARED / "task_results"


def installed() -> bool:
    return paths.BRAIN_SHARED.is_dir()


def available() -> bool:
    return tasks_dir().is_dir()


def status() -> dict:
    """What the Settings view says about brAIn, and why."""
    if not installed():
        return {"state": "missing", "sentence": "brAIn is not installed. Morph works as a "
                "dashboard on its own; install brAIn to design it by talking to it."}
    if not available():
        return {"state": "off", "sentence": "brAIn is installed but its Automation integration "
                "is off, so nothing picks up Morph's requests. Turn on "
                "“Automation integration” in brAIn's configuration."}
    last = paths.read_json(paths.SHARED / "brain_seen.json", {}) or {}
    return {"state": "ok", "sentence": "brAIn is ready.", "last_answer_at": last.get("at")}


def new_id(prefix: str = "morph") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def submit(task_id: str, prompt: str, *, schema: dict | None = None, tools: str = "full",
           timeout: int = 900, model: str = "", scheduled: bool = False,
           memory: bool = False) -> None:
    """Hand brAIn one task. Written to a scratch name and renamed, because
    the listener globs ``*.json`` and must never read half a file."""
    task = {"id": task_id, "prompt": prompt, "ts": int(time.time()), "timeout": int(timeout),
            "source": "morph", "tools": tools}
    if schema:
        task["schema"] = schema
    if model:
        task["model"] = model
    if scheduled:
        task["scheduled"] = True
    if memory:
        task["memory"] = True
    tdir = tasks_dir()
    scratch = tdir / f".{task_id}.tmp"
    scratch.write_text(json.dumps(task), encoding="utf-8")
    scratch.replace(tdir / f"{task_id}.json")


def claimed(task_id: str) -> bool:
    return not (tasks_dir() / f"{task_id}.json").exists()


def result(task_id: str) -> dict | None:
    path = results_dir() / f"{task_id}.json"
    data = paths.read_json(path)
    if not isinstance(data, dict):
        return None
    try:
        path.unlink()
    except OSError:
        pass  # the listener may have tidied it already; the answer is in hand
    paths.write_json(paths.SHARED / "brain_seen.json", {"at": time.time()})
    return data


def withdraw(task_id: str) -> bool:
    """Take back a task nothing claimed, so it does not run an hour later
    against a dashboard that has moved on."""
    try:
        (tasks_dir() / f"{task_id}.json").unlink()
        return True
    except OSError:
        return False


def answer_data(res: dict) -> tuple[dict | None, str, str]:
    """(validated object, text, error code) out of a result file."""
    if res.get("status") != "completed":
        return None, str(res.get("result") or ""), str(res.get("error") or "failed")
    data = res.get("data")
    text = str(res.get("result") or "")
    if not isinstance(data, dict):
        # A CLI too old for --json-schema answers in prose; take the first
        # JSON object in it rather than nothing.
        data = _first_object(text)
    return data, text, ""


def _first_object(text: str) -> dict | None:
    start = text.find("{")
    while start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except ValueError:
                        break
                    break
        start = text.find("{", start + 1)
    return None
