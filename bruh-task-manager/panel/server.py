#!/usr/bin/env python3
"""BRUH Task Manager's panel: one sampling loop, a page, and a few routes.

The loop measures on `sample_seconds` whether or not anybody has the page
open, because the runaway detector and the Home Assistant sensors need a
continuous record; what the page fetches is the newest snapshot, never a
fresh measurement (a CPU percentage needs two readings, and a page that
measured on demand would show nothing on its first load).

Routes:

* `GET /api/snapshot` — the machine, every app, the Level 2 status, the
  runaway list; with `?processes=1`, every process too (only fetched while
  the Processes tab is open, because it is the large half).
* `GET /api/app/{key}/impact?action=` — what Restart/Stop/Start will do,
  in sentences, for the confirmation.
* `POST /api/app/{key}/{action}` — starts the action as a JOB and answers at
  once. Restarting Home Assistant takes minutes and ingress does not hold a
  request that long; what reaches the browser otherwise is not an error but
  the absence of a reply, about an action that is still happening.
* `GET /api/job/{id}` — how that went.
* `POST /api/process/{pid}/end` — `{start, force}`; policy is re-asked over
  a fresh read of the process (policy.py, ending.py).
* `GET/POST /api/settings` — the Level 2 switches and the runaway
  threshold, written through the Supervisor (settings.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
import uuid

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apps as apps_mod  # noqa: E402
import policy  # noqa: E402
import procs  # noqa: E402
import settings as settings_mod  # noqa: E402
from ending import Ender  # noqa: E402
from machine import MachineSampler  # noqa: E402
from runaway import RunawayTracker  # noqa: E402

PANEL_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PANEL_PORT", "8103"))
PROC_ROOT = os.environ.get("TASK_MANAGER_PROC", "/proc")
SHARED = os.environ.get("TASK_MANAGER_SHARED", "/config/.bruh_task_manager")
VERSION = os.environ.get("ADDON_VERSION", "dev")

STATIC = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "application/javascript"),
    "/style.css": ("style.css", "text/css"),
    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
}

ACTIONS = ("restart", "stop", "start")
MAX_JOBS = 20
MIRROR_TOP = 10

_LOG = logging.getLogger("task_manager")


def _for_log(value, limit: int = 120) -> str:
    """A value from a request, safe to put in a log line.

    Line breaks and other control characters are replaced, so a name sent
    to the panel cannot forge a second log line; long values are cut.
    """
    text = "".join(ch if ch.isprintable() else "?" for ch in str(value))
    return text if len(text) <= limit else text[:limit] + "…"


class QuietAccessLogger(AbstractAccessLogger):
    """A poll that succeeded is not news; everything else is logged."""

    QUIET = ("/api/snapshot", "/api/health", "/api/job/")

    def log(self, request, response, time_taken):  # noqa: D401
        if (request.method == "GET" and response.status < 400
                and request.path.startswith(self.QUIET)
                and not self.logger.isEnabledFor(logging.DEBUG)):
            return
        level = logging.WARNING if response.status >= 400 else logging.INFO
        self.logger.log(level, "%s %s -> %s (%.0f ms)", request.method,
                        request.path, response.status, time_taken * 1000)


def write_json_atomic(path: str, data, mode: int = 0o600) -> None:
    """mkstemp beside the target, fsync, rename — never a shared scratch name.

    Owner-only: the one reader is Home Assistant Core, which runs as root, and
    the process list it mirrors is nobody else's business.
    """
    directory = os.path.dirname(path)
    fd, scratch = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(scratch, mode)
        os.replace(scratch, path)
    except BaseException:
        try:
            os.unlink(scratch)
        except OSError:
            pass  # the original failure is the one worth raising
        raise


class Monitor:
    """Everything the routes read, refreshed by one loop."""

    def __init__(self, supervisor=None, *, proc_root: str = PROC_ROOT,
                 shared: str | None = SHARED, options=None,
                 process_sampler=None, ender=None) -> None:
        self.supervisor = supervisor
        self.proc_root = proc_root
        self.shared = shared
        self.options = options or settings_mod.Options(supervisor)
        self.machine = MachineSampler(proc_root)
        self.apps = apps_mod.AppSampler(supervisor) if supervisor else None
        self.processes = process_sampler or procs.ProcessSampler(proc_root)
        self.ender = ender or Ender(self.processes)
        self.runaway = RunawayTracker()
        self.snapshot: dict = {}
        self.process_view: dict | None = None
        self.jobs: dict[str, dict] = {}
        self._tasks: set = set()
        self.started_at = time.time()

    # -- the loop --------------------------------------------------------

    async def tick(self) -> None:
        opts = await self.options.refresh()
        machine = self.machine.sample()
        app_rows = await self.apps.sample() if self.apps else []
        visible = await asyncio.to_thread(procs.host_visible, self.proc_root)
        status = settings_mod.level2_status(opts["process_view"],
                                            self.options.protected, visible)
        if status["active"]:
            sample = await asyncio.to_thread(self.processes.sample)
            self.process_view = self._decorate(sample, app_rows, opts)
        else:
            self.process_view = None
        runaway = self.runaway.update(app_rows, opts["runaway_cpu_percent"],
                                      opts["runaway_minutes"])
        for app in app_rows:
            since = self.runaway.above_since(app["key"])
            app["above_since"] = since
            app["runaway"] = any(r["key"] == app["key"] for r in runaway)
        self.snapshot = {
            "version": VERSION,
            "generated_at": time.time(),
            "sample_seconds": opts["sample_seconds"],
            "machine": machine,
            "apps": app_rows,
            "apps_error": self.apps.error if self.apps else
            "The Supervisor is not available here, so apps cannot be measured.",
            "level2": status,
            "process_keys": [g["key"] for g in self.process_view["groups"]]
            if self.process_view else [],
            "runaway": {"threshold": opts["runaway_cpu_percent"],
                        "minutes": opts["runaway_minutes"], "apps": runaway},
            "settings": self.settings_payload(),
        }
        self.ender.prune()
        await asyncio.to_thread(self.mirror)

    async def run(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 — the loop must outlive one bad pass
                _LOG.exception("A measurement pass failed")
            wait = (self.options.values.get("sample_seconds") or 5) - (time.monotonic() - started)
            await asyncio.sleep(max(wait, 0.5))

    # -- Level 2 ---------------------------------------------------------

    def _decorate(self, sample: dict, app_rows, opts) -> dict:
        names = {a["key"]: a["name"] for a in app_rows}
        for group in sample["groups"]:
            if group["kind"] == "addon":
                group["name"] = names.get(group["key"], group["name"])
            if group["kind"] == "self":
                group["name"] = "BRUH Task Manager"
            for row in group["procs"]:
                ok, why = policy.verdict(
                    row, group, level2_active=True,
                    ending_on=opts["allow_ending_processes"],
                    protected=opts["protected_processes"])
                row["can_end"] = ok
                row["why_not"] = why
                wait = self.ender.force_in(row["pid"], row["start"])
                row["force_in"] = None if wait is None else round(wait, 1)
        sample["groups"].sort(key=lambda g: (-(g["cpu"] or 0), g["name"].lower()))
        return sample

    def allowed(self, proc, identity):
        opts = self.options.values
        names = {a["key"]: a["name"] for a in self.snapshot.get("apps", [])}
        group = {"kind": identity.kind, "key": identity.key, "slug": identity.slug,
                 "name": names.get(identity.key, identity.name)}
        row = procs.row_of(proc, None)
        status = self.snapshot.get("level2") or {}
        return policy.verdict(row, group, level2_active=bool(status.get("active")),
                              ending_on=opts["allow_ending_processes"],
                              protected=opts["protected_processes"])

    # -- the mirror Home Assistant reads -----------------------------------

    def mirror_payload(self) -> dict:
        snap = self.snapshot
        apps = [a for a in snap.get("apps", []) if not a.get("is_self")]
        measured = [a for a in apps if a.get("cpu") is not None]
        top = [{"key": a["key"], "name": a["name"], "slug": a.get("slug"),
                "cpu": a.get("cpu"), "memory_mb": round(a["mem_bytes"] / 1048576, 1)
                if a.get("mem_bytes") else None}
               for a in measured[:MIRROR_TOP]]
        sample = snap.get("sample_seconds") or 5
        return {
            "version": VERSION,
            "generated_at": snap.get("generated_at"),
            "stale_after_s": max(60, sample * 6),
            "machine": snap.get("machine"),
            "busiest": top[0] if top else None,
            "top": top,
            "runaway": snap.get("runaway"),
            "level": (snap.get("level2") or {}).get("level", 1),
            "level_state": (snap.get("level2") or {}).get("state"),
        }

    def mirror(self) -> None:
        if not self.shared or not os.path.isdir(os.path.dirname(self.shared.rstrip("/"))):
            return
        try:
            os.makedirs(self.shared, exist_ok=True)
            write_json_atomic(os.path.join(self.shared, "state.json"),
                              self.mirror_payload())
        except OSError as exc:
            _LOG.warning("Could not write the state Home Assistant reads: %s", exc)

    # -- settings ----------------------------------------------------------

    def settings_payload(self) -> dict:
        values = dict(self.options.values)
        return {"values": values, "source": self.options.source,
                "slug": self.apps.self_slug if self.apps else None,
                "protected": self.options.protected,
                "can_save": self.supervisor is not None}

    # -- jobs ----------------------------------------------------------------

    def start_job(self, key: str, action: str, name: str) -> dict:
        job = {"id": uuid.uuid4().hex[:12], "key": key, "action": action,
               "name": name, "status": "running", "started": time.time(),
               "message": f"{action.capitalize()}ing {name}…"}
        self.jobs[job["id"]] = job
        while len(self.jobs) > MAX_JOBS:
            self.jobs.pop(next(iter(self.jobs)))
        task = asyncio.create_task(self._run_job(job))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def _run_job(self, job: dict) -> None:
        path = apps_mod.action_path(job["key"], job["action"])
        _LOG.warning("%s %s (%s)", _for_log(job["action"]).capitalize(),
                     _for_log(job["name"]), _for_log(job["key"]))
        try:
            await self.supervisor.post(path, timeout=900)
        except apps_mod.SupervisorError as exc:
            if job["key"] == "supervisor":
                # The Supervisor drops the connection as it restarts itself.
                job.update(status="done", message="The Supervisor is restarting.")
            else:
                job.update(status="failed", message=str(exc))
        else:
            past = {"restart": "restarted", "stop": "stopped", "start": "started"}
            job.update(status="done",
                       message=f"{job['name']} {past[job['action']]}.")
        job["finished"] = time.time()


# ----------------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------------

MONITOR = web.AppKey("monitor", Monitor)


def _monitor(request) -> Monitor:
    return request.app[MONITOR]


def static_handler(path: str):
    """One handler per named file, bound to its route.

    Never derived from `request.path`: mounted under a prefix (ingress, or
    a sub-application) the path is not the key, and a lookup that falls back
    to the page answers app.js with HTML.
    """
    name, ctype = STATIC[path]

    async def handler(request):
        with open(os.path.join(PANEL_DIR, name), "rb") as handle:
            body = handle.read()
        if name == "index.html":
            body = body.replace(b"{{VERSION}}", VERSION.encode())
        return web.Response(body=body, content_type=ctype,
                            headers={"Cache-Control": "no-cache"})

    return handler


async def h_health(request):
    return web.json_response({"ok": True, "version": VERSION})


async def h_snapshot(request):
    monitor = _monitor(request)
    body = dict(monitor.snapshot)
    if request.query.get("processes") == "1":
        body["processes"] = monitor.process_view
    return web.json_response(body)


def _app_row(monitor: Monitor, key: str):
    for row in monitor.snapshot.get("apps", []):
        if row["key"] == key:
            return row
    return None


async def h_impact(request):
    monitor = _monitor(request)
    key = request.match_info["key"]
    action = request.query.get("action", "")
    row = _app_row(monitor, key)
    if row is None or action not in row.get("actions", []):
        return web.json_response({"error": "That action is not offered for that app."},
                                 status=404)
    info = None
    if row["kind"] == "addon" and monitor.supervisor is not None:
        try:
            info = await monitor.supervisor.get(f"/addons/{row['slug']}/info")
        except apps_mod.SupervisorError:
            info = None
    return web.json_response({"key": key, "action": action, "name": row["name"],
                              "lines": apps_mod.impact(key, action, row["name"], info)})


async def h_action(request):
    monitor = _monitor(request)
    key = request.match_info["key"]
    action = request.match_info["action"]
    row = _app_row(monitor, key)
    if action not in ACTIONS or row is None or action not in row.get("actions", []):
        return web.json_response({"error": "That action is not offered for that app."},
                                 status=404)
    if monitor.supervisor is None or apps_mod.action_path(key, action) is None:
        return web.json_response({"error": "The Supervisor cannot do that here."},
                                 status=409)
    for job in monitor.jobs.values():
        if job["key"] == key and job["status"] == "running":
            return web.json_response(job)
    # From here on the key and the verb are the snapshot's and the table's own
    # strings, never the request's: they are logged, and a log line must not
    # carry what somebody typed into a URL.
    verb = ACTIONS[ACTIONS.index(action)]
    return web.json_response(monitor.start_job(row["key"], verb, row["name"]))


async def h_job(request):
    job = _monitor(request).jobs.get(request.match_info["id"])
    if job is None:
        return web.json_response({"error": "No such job."}, status=404)
    return web.json_response(job)


async def h_end(request):
    monitor = _monitor(request)
    try:
        pid = int(request.match_info["pid"])
        body = await request.json()
        start = int(body["start"])
        force = body.get("force") is True
    except (ValueError, KeyError, TypeError):
        return web.json_response({"error": "Send {start, force}."}, status=400)
    if pid <= 2:
        return web.json_response({"ok": False, "outcome": "refused",
                                  "message": policy.REFUSALS["os"]}, status=409)
    result = await monitor.ender.end(pid, start, force, monitor.allowed)
    status = 200 if result.get("ok") else (409 if result["outcome"] != "changed" else 410)
    return web.json_response(result, status=status)


async def h_settings_get(request):
    monitor = _monitor(request)
    await monitor.options.refresh(force=True)
    return web.json_response(monitor.settings_payload())


async def h_settings_post(request):
    monitor = _monitor(request)
    try:
        changes = settings_mod.changes_from(await request.json())
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    try:
        await monitor.options.update(changes)
    except RuntimeError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    named = [key for key in settings_mod.EDITABLE if key in changes]
    _LOG.warning("Settings changed from the panel: %s", ", ".join(named))
    return web.json_response(monitor.settings_payload())


def build_app(monitor: Monitor) -> web.Application:
    app = web.Application()
    app[MONITOR] = monitor
    for path in STATIC:
        app.router.add_get(path, static_handler(path))
    app.router.add_get("/api/health", h_health)
    app.router.add_get("/api/snapshot", h_snapshot)
    app.router.add_get("/api/app/{key}/impact", h_impact)
    app.router.add_post("/api/app/{key}/{action}", h_action)
    app.router.add_get("/api/job/{id}", h_job)
    app.router.add_post("/api/process/{pid}/end", h_end)
    app.router.add_get("/api/settings", h_settings_get)
    app.router.add_post("/api/settings", h_settings_post)

    async def start_loop(app):
        app["loop_task"] = asyncio.create_task(monitor.run())

    async def stop_loop(app):
        task = app.get("loop_task")
        if task:
            task.cancel()
        if monitor.supervisor is not None:
            await monitor.supervisor.close()

    app.on_startup.append(start_loop)
    app.on_cleanup.append(stop_loop)
    return app


def main() -> None:
    level = os.environ.get("TASK_MANAGER_LOG_LEVEL", "info").upper()
    level = {"TRACE": "DEBUG", "NOTICE": "INFO", "FATAL": "CRITICAL"}.get(level, level)
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    supervisor = apps_mod.Supervisor() if os.environ.get("SUPERVISOR_TOKEN") else None
    monitor = Monitor(supervisor)
    web.run_app(build_app(monitor), host="0.0.0.0", port=PORT,
                access_log_class=QuietAccessLogger,
                access_log=logging.getLogger("task_manager.access"),
                print=lambda _msg: _LOG.info("Panel listening on 0.0.0.0:%s", PORT))


if __name__ == "__main__":
    main()
