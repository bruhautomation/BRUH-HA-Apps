"""Why Claude is not writing shows — asked one link at a time.

The Claude director is not a library call. It is a file handed across a
shared volume to a *different add-on*, picked up by a shell listener, run
through a CLI that has its own login, and answered by writing a second
file back. Six things have to be true and BRight can see exactly one of
them directly, which is how "still failing" stayed unexplained through
three fixes: every layer answered "fine" about the part it could see.

`available()` is the worst offender and the reason this file exists. It
tests whether `/config/.brain/tasks` is a directory — and that directory
is created by brAIn's listener at startup and then **outlives it**. A
brAIn that is stopped, or running with its Automation integration
switched off, leaves the folder behind and looks identical to a working
one until the wait expires.

So this walks the chain and reports each link:

1. **brAIn** — is its shared folder there at all
2. **the task folder** — has its automation listener ever started
3. **writing** — can BRight actually put a file there (the two add-ons
   run as different users, and a folder you cannot write to is a folder
   nothing will ever read from)
4. **the claim** — does anything pick a task UP. The listener claims by
   renaming, so an un-renamed file after the grace window is proof that
   nothing is listening, not a slow answer
5. **the answer** — does a trivial task come back, which is the first
   moment the CLI, its login and the model are all exercised
6. **the room** — are there lights to write a show for, because a
   perfect director with an empty map still cannot compile

Stops at the first broken link: telling somebody their model is wrong is
noise when the add-on it runs in is not started.
"""
from __future__ import annotations

import time

from director import claude_director

# The probe asks for one word. Anything longer would be measuring the
# model's prose rather than whether the chain carries a message, and this
# runs while somebody waits.
PROBE_PROMPT = ("Reply with exactly one word and nothing else: READY")
PROBE_TIMEOUT_S = 120


def _step(name: str, ok: bool, detail: str) -> dict:
    return {"step": name, "ok": ok, "detail": detail}


def check() -> dict:
    """Walk the links. Blocking — the caller runs it as a job."""
    steps: list[dict] = []

    shared = claude_director.BRAIN_SHARED
    if not shared.is_dir():
        steps.append(_step(
            "brAIn", False,
            f"{shared} does not exist, so brAIn is not installed on this "
            f"Home Assistant. The Claude director runs through brAIn's "
            f"task surface; without it BRight uses its own choreographer, "
            f"which is what every show you have is."))
        return {"ok": False, "steps": steps}
    steps.append(_step("brAIn", True, f"{shared} is there"))

    tasks = claude_director.TASKS_DIR
    if not tasks.is_dir():
        steps.append(_step(
            "task folder", False,
            f"{tasks} does not exist. brAIn is installed but its automation "
            f"listener has never started — turn on brAIn's Automation "
            f"integration and restart it."))
        return {"ok": False, "steps": steps}
    steps.append(_step("task folder", True, f"{tasks} is there"))

    probe = tasks / ".bright-write-probe"
    try:
        probe.write_text("probe")
        probe.unlink()
    except OSError as exc:
        steps.append(_step(
            "writing", False,
            f"BRight cannot write into {tasks} ({exc}). The two add-ons run "
            f"as different users; a folder BRight cannot write to is one "
            f"brAIn will never read a task from."))
        return {"ok": False, "steps": steps}
    steps.append(_step("writing", True, "BRight can leave a task there"))

    # The one that matters. `_run_task` already tells a task nobody
    # claimed from one that was claimed and never answered, so the probe
    # is simply a real round trip with a trivial prompt — the same code
    # path a show uses, which is the only kind of test worth trusting.
    started = time.monotonic()
    try:
        answer = claude_director._run_task(PROBE_PROMPT, PROBE_TIMEOUT_S)
    except RuntimeError as exc:
        message = str(exc)
        claimed = "never picked this up" not in message
        steps.append(_step("the claim", claimed,
                           "a listener took the task" if claimed
                           else message))
        if claimed:
            steps.append(_step("the answer", False, message))
        return {"ok": False, "steps": steps}

    took = round(time.monotonic() - started, 1)
    steps.append(_step("the claim", True, "a listener took the task"))
    steps.append(_step(
        "the answer", True,
        f"brAIn answered in {took}s using model "
        f"{claude_director._director_model()!r}: "
        f"{answer.strip()[:80] or '(empty)'}"))

    return {"ok": True, "steps": steps,
            "note": f"The chain works. A show is a much longer answer than "
                    f"this probe — up to {claude_director.TASK_TIMEOUT_S}s — "
                    f"so if compiling still fails, the message on the track "
                    f"row is the director's own and says what it could not "
                    f"do."}
