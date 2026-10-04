"""One gate for every Claude run the panel starts, with a priority on it.

The add-on used to claim that one Claude invocation was in flight at a
time — the generation queue's single worker — and that claim stopped being
true the release the Resident, triage, curiosity, the brief, the weekly
report, a phone's Reply and the activity paragraph each began spawning runs
of their own with `asyncio.to_thread`. Those landed on the default thread
pool beside every store read the panel makes: eight threads on a four-core
Pi, no limit across them and no order between them. Two minutes-long
investigations and a Reply could hold three of the eight while a Done
pressed in Home Assistant waited behind a findings read that had no thread
to run on, and nothing was protecting the subscription's rate limit or the
box's memory from five CLIs at once.

So every engine run made from the server goes through here, and three
rules hold:

**Its own threads.** Runs execute on an executor of their own, so a store
read never waits for a model and a model never takes a thread a store read
needed. The default pool goes back to being what `asyncio.to_thread` is
for: short, blocking I/O.

**Bounded, with a seat kept for a person.** At most `SLOTS` runs at once,
and an unattended run may hold at most `SLOTS - 1` of them, so a press —
Fix it, a Reply, Ask — never waits behind a house full of scheduled work.
Safety rides the same reserved seat as a press: a leak the Resident is
acting on is not something to queue behind a card refresh.

**Ordered.** Waiters are served safety first, then presses, then
everything scheduled, and first-come within a priority — `heapq` over
`(priority, sequence)` — so nothing loses the same lottery twice.

Nothing here knows what a run is: it is handed a callable and runs it,
which is what lets the server keep one helper (`server._claude`) and every
call site keep its shape.
"""
from __future__ import annotations

import asyncio
import functools
import heapq
import itertools
import os
import threading
from concurrent.futures import ThreadPoolExecutor

SAFETY = 0
PRESS = 1
SCHEDULED = 2
PRIORITY_NAMES = {SAFETY: "safety", PRESS: "press", SCHEDULED: "scheduled"}

# How many Claude processes the panel may have running at once. Three is
# one long scheduled run, one more beside it, and the seat a person's press
# always has — and three `claude` processes is what a Pi with 4 GB can hold
# beside Home Assistant without the kernel choosing what to kill.
SLOTS = max(1, int(os.environ.get("BRAIN_CLAUDE_SLOTS", "3") or 3))


class RunQueue:
    """A bounded, prioritised gate in front of a dedicated executor."""

    def __init__(self, slots: int = SLOTS) -> None:
        self.slots = max(1, int(slots))
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._seq = itertools.count()
        self._waiters: list = []
        # Futures granted a seat whose waiter has not woken yet. A waiter
        # cancelled in that gap must hand the seat back, and only this set
        # can tell it that it holds one.
        self._granted: set = set()
        self.running = {SAFETY: 0, PRESS: 0, SCHEDULED: 0}
        self.started = 0
        self.finished = 0

    # -- the executor ----------------------------------------------------
    def _pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.slots, thread_name_prefix="claude-run")
            return self._executor

    # -- admission -------------------------------------------------------
    def _total(self) -> int:
        return sum(self.running.values())

    def _may_start(self, priority: int) -> bool:
        if self._total() >= self.slots:
            return False
        if priority == SCHEDULED and self.slots > 1:
            # The seat kept for a person: unattended work may fill every
            # slot but one.
            return self.running[SCHEDULED] < self.slots - 1
        return True

    def _wake(self) -> None:
        """Start whichever waiters may start now, best priority first.

        A scheduled waiter at the head that may not start (its seats are
        full) must not block a press behind it, so the scan goes on past
        it rather than stopping at the head of the heap.
        """
        held = []
        while self._waiters:
            entry = heapq.heappop(self._waiters)
            priority, _seq, future = entry
            if future.done():
                continue            # cancelled while it waited
            if self._may_start(priority):
                try:
                    future.get_loop().call_soon_threadsafe(_resolve, future)
                except RuntimeError:
                    # Its loop has closed under it (a test, a second app);
                    # nobody is waiting on this future any more.
                    continue
                self.running[priority] += 1
                self._granted.add(future)
            else:
                held.append(entry)
        for entry in held:
            heapq.heappush(self._waiters, entry)

    async def acquire(self, priority: int = SCHEDULED) -> None:
        priority = priority if priority in PRIORITY_NAMES else SCHEDULED
        if not self._waiters and self._may_start(priority):
            self.running[priority] += 1
            return
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._seq), future))
        # A press arriving while only scheduled work waits may have a seat
        # free right now — the waiters ahead of it are the ones that may
        # not start — so it is offered one at once rather than at the next
        # release.
        self._wake()
        try:
            await future
        except asyncio.CancelledError:
            if future in self._granted:
                # Granted a seat in the same instant it was cancelled: give
                # the seat back rather than leak it.
                self._granted.discard(future)
                self.release(priority)
            raise
        self._granted.discard(future)

    def release(self, priority: int = SCHEDULED) -> None:
        priority = priority if priority in PRIORITY_NAMES else SCHEDULED
        if self.running[priority] > 0:
            self.running[priority] -= 1
        self._wake()

    # -- the one entry point ---------------------------------------------
    async def run(self, fn, *args, priority: int = SCHEDULED, **kwargs):
        """Run ``fn(*args, **kwargs)`` on the run executor, in turn."""
        await self.acquire(priority)
        self.started += 1
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._pool(), functools.partial(fn, *args, **kwargs))
        finally:
            self.finished += 1
            self.release(priority)

    def stats(self) -> dict:
        """What `/api/diagnostics` carries: who is running and who waits."""
        waiting = {name: 0 for name in PRIORITY_NAMES.values()}
        for priority, _seq, future in self._waiters:
            if not future.done():
                waiting[PRIORITY_NAMES.get(priority, "scheduled")] += 1
        return {
            "slots": self.slots,
            "running": {PRIORITY_NAMES[p]: n for p, n in self.running.items()},
            "waiting": waiting,
            "started": self.started,
            "finished": self.finished,
        }

    def reset(self) -> None:
        """Forget waiters from a loop that has gone (a test, a second app).

        A future bound to a dead loop can never be resolved, and one left
        in the heap would hold its place for ever; the running counts are
        kept, because a run still executing will release its own seat.
        """
        self._waiters = [entry for entry in self._waiters
                         if not entry[2].done()
                         and not entry[2].get_loop().is_closed()]
        heapq.heapify(self._waiters)


def _resolve(future: asyncio.Future) -> None:
    if not future.done():
        future.set_result(None)


QUEUE = RunQueue()


async def run(fn, *args, priority: int = SCHEDULED, **kwargs):
    """The module's one queue — see `RunQueue.run`."""
    return await QUEUE.run(fn, *args, priority=priority, **kwargs)


def stats() -> dict:
    return QUEUE.stats()


__all__ = ["PRESS", "PRIORITY_NAMES", "QUEUE", "RunQueue", "SAFETY",
           "SCHEDULED", "SLOTS", "run", "stats"]
