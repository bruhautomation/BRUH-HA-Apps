"""brAIn, reached the way BRight and Morph reach it: a file in its task folder.

brAIn's automation listener watches /config/.brain/tasks, claims a task by
RENAMING it, runs Claude, and writes /config/.brain/task_results/<id>.json
back: {id, result, status, data?, error?, session_id?}. A `conversation`
task resumes `session_id`, so one part is one conversation that can be
picked up days later — and, being unclaimed in brAIn's run ledger, it is
also the person's own conversation in brAIn's Chats.

The folder outlives the listener that made it (brAIn always creates it), so
the folder alone cannot tell a stopped listener from a working one. brAIn
5.5.25 and later rewrites a liveness mark, cache/automation_listener.json
({pid, ts, interval}), every `interval` seconds while its listener runs; a
mark older than three intervals means nothing is listening, and status()
says so before anyone waits. No mark at all is a brAIn from before the mark
and falls back to the folder, never read as a dead listener. A task nothing
claims within CLAIM_GRACE_S is still reported as nothing listening, with
what to do — never as brAIn being slow.

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
# brAIn's listener beats every 30s and a mark three beats old is stale.
BEAT_S = 30
STALE_BEATS = 3

NOT_LISTENING = (
    "brAIn is installed but is not picking up requests right now. Restarting the "
    "brAIn app usually brings it back; its “Automation integration” option must be on.")


def tasks_dir() -> Path:
    return BRAIN_SHARED / "tasks"


def results_dir() -> Path:
    return BRAIN_SHARED / "task_results"


def listener_mark() -> Path:
    return BRAIN_SHARED / "cache" / "automation_listener.json"


def _listener_stale(now: float | None = None) -> bool:
    """True only when brAIn's liveness mark exists and has gone stale. No mark
    (an older brAIn) or one that cannot be read is not evidence of a dead
    listener: the folder check stands."""
    try:
        mark = json.loads(listener_mark().read_text(encoding="utf-8"))
        ts = float(mark["ts"])
    except (OSError, ValueError, TypeError, KeyError):
        return False
    try:
        interval = float(mark.get("interval") or BEAT_S)
    except (TypeError, ValueError):
        interval = BEAT_S
    interval = max(1.0, interval)
    return ((time.time() if now is None else now) - ts) > STALE_BEATS * interval


def status() -> dict:
    """{state: ok|stopped|off|missing, sentence}."""
    if not BRAIN_SHARED.is_dir():
        return {"state": "missing", "sentence": (
            "brAIn is not installed. Everything else in BRUH Bambu Studio works without it; "
            "install brAIn to design parts by talking to it.")}
    if not tasks_dir().is_dir():
        return {"state": "off", "sentence": (
            "brAIn is installed, but its Automation integration is off, so nothing picks up "
            "design requests. Turn on “Automation integration” in brAIn's configuration.")}
    if _listener_stale():
        return {"state": "stopped", "sentence": NOT_LISTENING}
    return {"state": "ok", "sentence": "brAIn is connected."}


class NotListening(RuntimeError):
    """The task sat unclaimed: nothing is running brAIn's listener."""


def images_dir() -> Path:
    return BRAIN_SHARED / "task_images"


# What brAIn's listener takes as a picture: a JPEG or a PNG it reads once,
# hands to the run as a picture (never a path the run could open), and
# deletes. The check is the listener's; this only refuses to hand it more.
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _image_ext(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    return None


def submit(prompt: str, *, schema: dict, session_id: str = "", timeout: int = 600,
           kind: str = "conversation", images: list[bytes] | None = None,
           scheduled: bool = False, model: str = "") -> str:
    """Hand brAIn a task. `kind="conversation"` is a design conversation (the
    person's own, resumable); anything else is a one-off look. `images` are
    pictures handed to the run as pictures. `scheduled` makes brAIn's own
    pause and usage budget apply, for a look nobody pressed for. `model` is
    one of prefs.MODELS ("default" or empty leaves it to brAIn's plan).
    NotListening at once when brAIn's mark says nothing is listening, so no
    request is left in a folder nobody reads."""
    if _listener_stale():
        raise NotListening(NOT_LISTENING)
    task_id = f"bambu-{uuid.uuid4().hex[:12]}"
    task = {"id": task_id, "prompt": prompt, "ts": int(time.time()),
            "timeout": int(timeout), "source": "bruh_bambu", "tools": "read_only",
            "schema": schema}
    if kind == "conversation":
        task.update(kind="conversation", person_words="")
    if scheduled:
        task["scheduled"] = True
    if model and model != "default":
        task["model"] = model
    if session_id:
        task["session_id"] = str(session_id)[:80]
    if images:
        paths = []
        folder = images_dir()
        folder.mkdir(parents=True, exist_ok=True)
        for n, data in enumerate(images[:MAX_IMAGES]):
            ext = _image_ext(data or b"")
            if ext is None or len(data) > MAX_IMAGE_BYTES:
                continue
            path = folder / f"{task_id}-{n}.{ext}"
            scratch = folder / f".{task_id}-{n}.tmp"
            scratch.write_bytes(data)
            scratch.replace(path)
            paths.append(str(path))
        if paths:
            task["images"] = paths
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
            _drop_images(task_id)
            return data if isinstance(data, dict) else {}
        elapsed = time.time() - start
        if task_file.exists() and elapsed > CLAIM_GRACE_S:
            task_file.unlink(missing_ok=True)
            _drop_images(task_id)
            raise NotListening(
                f"brAIn did not pick the request up within {CLAIM_GRACE_S} seconds, so nothing is "
                "listening for requests. Restart the brAIn app; its “Automation "
                "integration” option must be on.")
        if elapsed > timeout + 60:
            _drop_images(task_id)
            raise TimeoutError("brAIn did not answer in time.")
        time.sleep(POLL_S)


def _drop_images(task_id: str) -> None:
    """The pictures a task carried, once it is over (brAIn deletes what it read)."""
    try:
        for path in images_dir().glob(f"{task_id}-*"):
            path.unlink(missing_ok=True)
    except OSError:
        pass  # brAIn deletes what it read; a leftover is swept by its listener
