"""End process: ask first, force only when asking did not work.

SIGTERM is a request — a process can save, flush and exit — and SIGKILL is
not, so Force end is offered only after a SIGTERM to the SAME process (same
pid and start time) has had `GRACE_S` to work and the process is still
there. A pid reused in between is a different process and starts again from
asking.

Two answers that read alike are kept apart, because they mean different
things to do next: the process is gone, versus the kernel refused. The
refusal is usually AppArmor — the RECEIVING app's profile decides whether it
accepts signals from another profile, and many do not — and its remedy is
Restart app, which the Supervisor can always do.
"""
from __future__ import annotations

import asyncio
import errno
import logging
import os
import signal
import time

from procs import read_proc

GRACE_S = 5.0
WAIT_S = 3.0

_LOG = logging.getLogger("task_manager.ending")


class Ender:
    def __init__(self, sampler, *, kill=os.kill, clock=time.monotonic,
                 sleep=asyncio.sleep) -> None:
        self.sampler = sampler
        self.kill = kill
        self.clock = clock
        self.sleep = sleep
        self.asked: dict[tuple[int, int], float] = {}

    def _alive(self, pid: int, start: int) -> bool:
        proc = read_proc(self.sampler.root, pid)
        return proc is not None and proc.start == start and proc.state not in ("Z", "X")

    def force_in(self, pid: int, start: int):
        """Seconds until Force end is offered; None before anything was asked."""
        at = self.asked.get((pid, start))
        if at is None:
            return None
        return max(0.0, GRACE_S - (self.clock() - at))

    async def end(self, pid: int, start: int, force: bool, allowed) -> dict:
        """`allowed(proc, identity)` is policy, asked over a fresh read."""
        proc, identity = self.sampler.describe(pid)
        if proc is None:
            return {"ok": True, "outcome": "gone",
                    "message": "That process has already ended."}
        if proc.start != start:
            return {"ok": False, "outcome": "changed",
                    "message": "A different process has that number now, so "
                               "nothing was sent. Refresh and look again."}
        ok, why = allowed(proc, identity)
        if not ok:
            return {"ok": False, "outcome": "refused", "message": why}
        if force:
            wait = self.force_in(pid, start)
            if wait is None:
                return {"ok": False, "outcome": "ask_first",
                        "message": "Ask it to stop first; Force end is for a "
                                   "process that did not."}
            if wait > 0:
                return {"ok": False, "outcome": "too_soon", "retry_in": round(wait, 1),
                        "message": f"Give it {wait:.0f} more seconds to stop on its own."}
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            self.kill(pid, sig)
        except ProcessLookupError:
            return {"ok": True, "outcome": "gone",
                    "message": "That process has already ended."}
        except PermissionError as exc:
            _LOG.warning("End process %s (%s, %s) refused: %s",
                         pid, proc.comm, identity.name, exc)
            reason = ("the app's security profile does not accept signals from "
                      "other apps" if exc.errno in (errno.EACCES, errno.EPERM)
                      else str(exc))
            return {"ok": False, "outcome": "denied",
                    "message": f"Linux refused: {reason}. Use Restart on "
                               f"{identity.name} instead."}
        _LOG.warning("%s process %s (%s) in %s",
                     "Force-ended" if force else "Asked to stop", pid,
                     proc.comm, identity.name)
        if not force:
            self.asked[(pid, start)] = self.clock()
        waited = 0.0
        while waited < WAIT_S:
            if not self._alive(pid, start):
                self.asked.pop((pid, start), None)
                return {"ok": True, "outcome": "ended",
                        "message": f"{proc.comm} has ended."}
            await self.sleep(0.25)
            waited += 0.25
        if force:
            return {"ok": False, "outcome": "still_running",
                    "message": f"{proc.comm} is still running after Force end. "
                               f"It may be stuck in the kernel; Restart "
                               f"{identity.name} instead."}
        wait = self.force_in(pid, start) or 0.0
        return {"ok": True, "outcome": "asked", "retry_in": round(wait, 1),
                "message": f"Asked {proc.comm} to stop, and it is still running. "
                           f"Force end is offered in {wait:.0f} seconds if it "
                           f"does not stop."}

    def prune(self) -> None:
        now = self.clock()
        for key, at in list(self.asked.items()):
            if now - at > 600:
                self.asked.pop(key, None)
