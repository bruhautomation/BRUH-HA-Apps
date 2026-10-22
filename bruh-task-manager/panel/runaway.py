"""An app above the threshold for long enough is running away.

A streak, not an average: an update or a backup pins a CPU for a minute and
then stops, and that is not what anybody means by "running too hard". A
reading that could not be taken (the Supervisor did not answer) leaves the
streak where it was rather than resetting it — "I could not look" is not
"it calmed down" — and a reading below the threshold ends it.

Nothing here stops anything. The panel marks the app, the binary sensor turns
on, and what happens next is a person's decision or an automation's.
"""
from __future__ import annotations

import time


class RunawayTracker:
    def __init__(self, clock=time.time) -> None:
        self.clock = clock
        self.since: dict[str, float] = {}

    def update(self, apps, threshold: float, minutes: float) -> list[dict]:
        now = self.clock()
        present = set()
        out = []
        for app in apps:
            key = app.get("key")
            if not key or app.get("is_self"):
                continue
            present.add(key)
            cpu = app.get("cpu")
            if cpu is None:
                pass
            elif cpu >= threshold:
                self.since.setdefault(key, now)
            else:
                self.since.pop(key, None)
            started = self.since.get(key)
            if started is not None and now - started >= minutes * 60:
                out.append({"key": key, "name": app.get("name"), "slug": app.get("slug"),
                            "cpu": cpu, "since": started,
                            "minutes": round((now - started) / 60, 1)})
        for key in list(self.since):
            if key not in present:
                self.since.pop(key, None)
        out.sort(key=lambda r: r["since"])
        return out

    def above_since(self, key: str):
        return self.since.get(key)
