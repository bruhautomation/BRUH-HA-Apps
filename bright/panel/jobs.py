"""Fire-and-poll job registry — the panel's one way to run long work.

A request cannot outlive a minutes-long pass (ingress and Nabu Casa cut
long requests), so anything slow is started here and its outcome read back
by polling `get()`. One place, so no route grows its own half-tracked
task; one running job per name, so a double press is a 409 and not a
second probe racing the first at the same bulb.
"""
from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any, Awaitable, Callable

_JOBS: dict[str, dict[str, Any]] = {}
_MAX_FINISHED = 50


def _prune() -> None:
    finished = [job_id for job_id, job in _JOBS.items()
                if job["status"] != "running"]
    for job_id in finished[:-_MAX_FINISHED] if len(finished) > _MAX_FINISHED else []:
        del _JOBS[job_id]


def running(name: str) -> dict | None:
    for job in _JOBS.values():
        if job["name"] == name and job["status"] == "running":
            return job
    return None


def start(name: str, factory: Callable[..., Awaitable[Any]]) -> dict:
    """Start `factory()` as a task. Refuses (returns the live job with
    `already: True`) while a job of the same name is running.

    A factory that takes one parameter is handed a `report(dict)` callback;
    whatever it reports lands on the job as `progress`, which is what the
    poller renders while a folder-sized job grinds.
    """
    live = running(name)
    if live is not None:
        return {**live, "already": True}

    job_id = uuid.uuid4().hex[:12]
    job: dict[str, Any] = {
        "id": job_id,
        "name": name,
        "status": "running",
        "started": time.time(),
        "finished": None,
        "progress": None,
        "result": None,
        "error": None,
    }
    _JOBS[job_id] = job

    def report(info: dict) -> None:
        job["progress"] = info

    wants_report = bool(inspect.signature(factory).parameters)

    async def _run() -> None:
        try:
            job["result"] = await (factory(report) if wants_report
                                   else factory())
            job["status"] = "done"
        except Exception as exc:  # noqa: BLE001 — the job IS the error report
            job["error"] = str(exc)
            job["status"] = "error"
        finally:
            job["finished"] = time.time()
            _prune()

    job["_task"] = asyncio.create_task(_run())
    return job


async def wait(job_id: str) -> dict | None:
    """Await a job's completion and return its public record. Test-facing
    convenience — production reads poll `get()`."""
    job = _JOBS.get(job_id)
    if job is not None and "_task" in job:
        await asyncio.gather(job["_task"])
    return get(job_id)


def get(job_id: str) -> dict | None:
    job = _JOBS.get(job_id)
    if job is None:
        return None
    return {k: v for k, v in job.items() if not k.startswith("_")}


def clear() -> None:
    """For tests."""
    _JOBS.clear()
