"""Which processes may be ended, decided in code and never by the page.

The panel renders whatever `verdict` says, and the route that ends a process
asks it again over a FRESH read of the process — a button the page drew a
minute ago is not permission to signal whatever holds that pid now.

The rule is narrow on purpose. A process may be ended only when it is inside
an app's container, is not the thing keeping that container alive, and is not
on the protected list — and only while Level 2 is really in effect and ending
is switched on. Everything else gets a sentence saying why not and, where
there is one, what to press instead:

* the kernel and Home Assistant OS: ending systemd, dockerd or
  NetworkManager can leave the machine unreachable until it is power-cycled;
* the Supervisor, Home Assistant and the Supervisor plugins: each has a
  Restart that shuts it down cleanly, which a signal does not;
* this add-on: ending its own panel ends the page you pressed it on;
* a container nothing could name: refusing is the only safe answer to
  "I do not know what this is";
* an app's init or process supervisor (s6, tini, the container's pid 1):
  ending it stops the whole app, which Stop does cleanly.
"""
from __future__ import annotations

import fnmatch
import os

# The processes that keep an app's container alive. Ending one stops the
# whole app; the s6 ones also restart the services under them, so a signal
# to them is never "end this one process".
SUPERVISION = frozenset({
    "s6-svscan", "s6-supervise", "s6-linux-init", "s6-linux-init-shutdownd",
    "s6-rc", "s6-overlay-suexec", "s6-ipcserverd", "s6-fdholderd",
    "tini", "docker-init", "dumb-init", "catatonit",
})

REFUSALS = {
    "kernel": "Part of the Linux kernel. It cannot be ended, and nothing "
              "would be gained by trying.",
    "os": "Part of Home Assistant OS. Ending it can leave the whole machine "
          "unreachable until it is switched off and on again.",
    "supervisor": "The Supervisor runs every app. Use Restart on the "
                  "Supervisor's row instead.",
    "core": "This is Home Assistant itself. Use Restart on its row instead — "
            "that shuts it down cleanly and saves its database first.",
    "plugin": "A Supervisor plugin. Use Restart on its row instead.",
    "self": "This is BRUH Task Manager.",
    "container": "BRUH Task Manager could not tell which app this container "
                 "belongs to, so it will not end anything in it.",
}


def protected_match(patterns, *names) -> str | None:
    """The first pattern that matches any of the names, case-insensitively."""
    for pattern in patterns or ():
        pattern = str(pattern or "").strip().lower()
        if not pattern:
            continue
        for name in names:
            if name and fnmatch.fnmatchcase(str(name).lower(), pattern):
                return pattern
    return None


def verdict(row: dict, group: dict, *, level2_active: bool,
            ending_on: bool, protected=()) -> tuple[bool, str]:
    """(may it be ended, the sentence the page shows when it may not)."""
    if not level2_active:
        return False, "Level 2 is not in effect."
    if not ending_on:
        return False, ("Ending processes is switched off in Settings.")
    kind = group.get("kind")
    if kind != "addon":
        return False, REFUSALS.get(kind, REFUSALS["container"])
    app = group.get("name") or group.get("slug") or "this app"
    if row.get("kernel"):
        return False, REFUSALS["kernel"]
    if row.get("ns_pid") == 1 or row.get("name") in SUPERVISION:
        return False, (f"This keeps {app} running; ending it stops the whole "
                       f"app. Use Restart or Stop on {app} instead.")
    exe = os.path.basename((row.get("cmd") or "").split(" ", 1)[0])
    hit = protected_match(protected, row.get("name"), exe,
                          group.get("slug"), group.get("name"))
    if hit:
        return False, f"On your Never end these list ({hit})."
    return True, ""
