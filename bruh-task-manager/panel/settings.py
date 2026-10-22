"""The add-on's options, read live, and the Level 2 verdict built on them.

The options live where the Supervisor keeps them, so the Configuration tab
and the panel's switches are one setting. A switch pressed in the panel is
written back through `POST /addons/self/options` and takes effect at once:
the panel reads the options from the Supervisor (`/addons/self/info`), not
from /data/options.json, which the Supervisor only rewrites when the
container starts — reading that file would make every switch wait for a
restart. The file is the fallback for when the Supervisor cannot be asked.

**Level 2 is two switches and a fact.** The `process_view` option says the
person wants it; Protection mode OFF is what lets the Supervisor give this
container the host's process list (and only the person can change that, on
the add-on's Info page); and whether the host's processes are actually
visible is the fact, because Protection mode only takes effect when the
container is created. `level2_status` keeps those three apart, so the page
can say exactly which step is missing instead of "Level 2 is unavailable".
"""
from __future__ import annotations

import json
import os
import time

from apps import SupervisorError

OPTIONS_FILE = os.environ.get("TASK_MANAGER_OPTIONS", "/data/options.json")
REFRESH_S = 15

DEFAULTS = {
    "enable_ha_integration": True,
    "process_view": False,
    "allow_ending_processes": False,
    "protected_processes": [],
    "runaway_cpu_percent": 80,
    "runaway_minutes": 10,
    "sample_seconds": 5,
    "log_level": "info",
}

BOUNDS = {
    "runaway_cpu_percent": (10, 100),
    "runaway_minutes": (1, 240),
    "sample_seconds": (2, 60),
}

# What the panel may change. log_level and the integration switch need a
# restart to mean anything, so they stay on the Configuration tab.
EDITABLE = ("process_view", "allow_ending_processes", "protected_processes",
            "runaway_cpu_percent", "runaway_minutes", "sample_seconds")


def clean(options: dict | None) -> dict:
    out = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        value = (options or {}).get(key, default)
        if isinstance(default, bool):
            out[key] = value if isinstance(value, bool) else default
        elif isinstance(default, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = default
            low, high = BOUNDS.get(key, (value, value))
            out[key] = min(max(value, low), high)
        elif isinstance(default, list):
            items = value if isinstance(value, list) else []
            out[key] = [str(v).strip()[:80] for v in items
                        if isinstance(v, str) and v.strip()][:50]
        else:
            out[key] = value if isinstance(value, str) else default
    return out


def changes_from(body) -> dict:
    """The editable keys a request carried, cleaned; anything else is ignored."""
    if not isinstance(body, dict):
        raise ValueError("Send a JSON object.")
    picked = {k: body[k] for k in EDITABLE if k in body}
    if not picked:
        raise ValueError("Nothing to change.")
    merged = clean({**DEFAULTS, **picked})
    return {k: merged[k] for k in picked}


class Options:
    def __init__(self, supervisor=None, path: str = OPTIONS_FILE,
                 clock=time.monotonic) -> None:
        self.supervisor = supervisor
        self.path = path
        self.clock = clock
        self.values = self._from_file()
        self.protected: bool | None = None
        self.source = "file"
        self._at: float | None = None

    def _from_file(self) -> dict:
        try:
            with open(self.path) as handle:
                return clean(json.load(handle))
        except (OSError, ValueError):
            return clean({})

    async def refresh(self, force: bool = False) -> dict:
        now = self.clock()
        if not force and self._at is not None and now - self._at < REFRESH_S:
            return self.values
        self._at = now
        if self.supervisor is None:
            self.values = self._from_file()
            return self.values
        try:
            info = await self.supervisor.get("/addons/self/info")
        except SupervisorError:
            self.values = self._from_file()
            self.source = "file"
            return self.values
        if isinstance(info.get("options"), dict):
            self.values = clean(info["options"])
            self.source = "supervisor"
        if isinstance(info.get("protected"), bool):
            self.protected = info["protected"]
        return self.values

    async def update(self, changes: dict) -> dict:
        """Write through the Supervisor; refuse rather than pretend."""
        if self.supervisor is None:
            raise RuntimeError("The Supervisor cannot be reached, so the setting "
                               "was not saved.")
        info = await self.supervisor.get("/addons/self/info")
        current = info.get("options") if isinstance(info.get("options"), dict) else {}
        merged = {**clean(current), **changes}
        try:
            await self.supervisor.post("/addons/self/options",
                                       json={"options": merged})
        except SupervisorError as exc:
            raise RuntimeError(f"The Supervisor refused the setting: {exc}") from None
        return await self.refresh(force=True)


LEVEL2_SENTENCES = {
    "active": "Level 2 is on: every process on this machine is listed, "
              "grouped by the app it belongs to.",
    "needs_protection_off": "Level 2 is switched on, but Protection mode is "
                            "still on, so the Supervisor keeps this add-on in "
                            "its own box. Turn Protection mode off on the "
                            "add-on's Info page, then restart the add-on.",
    "needs_restart": "Protection mode is off, but it only takes effect when "
                     "the add-on starts. Restart BRUH Task Manager from its "
                     "Info page.",
    "unknown": "Level 2 is switched on, but the Supervisor could not be asked "
               "whether Protection mode is off, and no other process is "
               "visible.",
    "exposed": "Protection mode is off but Level 2 is switched off, so nothing "
               "reads the other processes. Turn Protection mode back on unless "
               "you are about to use Level 2.",
    "off": "Level 1: every app, Home Assistant and the Supervisor, measured "
           "by the Supervisor. Processes inside them are not shown.",
}


def level2_status(option_on: bool, protected, host_visible: bool) -> dict:
    """Which of Level 2's three conditions hold, and the one sentence for it."""
    steps = {
        "option": bool(option_on),
        "protection_off": protected is False,
        "visible": bool(host_visible),
    }
    if option_on and host_visible:
        state = "active"
    elif option_on and protected is True:
        state = "needs_protection_off"
    elif option_on and protected is False:
        state = "needs_restart"
    elif option_on:
        state = "unknown"
    elif host_visible or protected is False:
        state = "exposed"
    else:
        state = "off"
    sentence = LEVEL2_SENTENCES[state]
    return {"state": state, "active": state == "active", "level": 2 if state == "active" else 1,
            "steps": steps, "sentence": sentence}
